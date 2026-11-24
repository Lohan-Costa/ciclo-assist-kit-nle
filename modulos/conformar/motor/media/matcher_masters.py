"""Casar os masters de um AAF com os arquivos originais.

## O que este matcher NÃO faz, e por quê

**Não há confirmação visual.** O matcher do RELINKER compara frames por pHash contra um
vídeo de referência — faz todo o sentido num app que roda **fora** do editor, onde não há
outra forma de conferir. Dentro do Media Composer não é o caso: o editor tem a timeline na
tela, e o que um pHash produziria com dezenas de chamadas de ffmpeg ele confere de graça,
olhando. A decisão é dele; nosso trabalho é **não errar calado** e deixar explícito o que
ficou ambíguo.

Consequência prática: este módulo trabalha sobre o índice que o `indexer` já montou. A única
exceção é o empate entre WAVs: lê o cabeçalho (bext) para explicar ao editor se são o mesmo áudio
(`_explicar_empate_de_audio`).

**Não há relink forçado.** Mídia convertida com TC zerado, fps convertido errado e
parentes ficam para uma etapa própria, com opções explícitas. Aqui, relink normal.

## O que ele faz, e é o que importa

A **regra dos nomes frouxos**. O Avid quebra o match por nome de duas formas que aparecem
o tempo todo em material real:

1. **Sufixos empilhados.** Um clipe importado vira `A001_…_C002.new.01`; um transcode
   vira `.sync`, `.cds`, `.copy`, `.sub`, `.grp`, `.exported` — e o contador `.01` se
   acumula por cima. O nome nativo deixa de casar com o arquivo.
2. **Separadores trocados.** O Avid grava nomes por timecode, e o mesmo item aparece
   como `17;25;16 Cordas.wav` no disco e `17_25_16 Cordas` no AAF. Ponto e vírgula,
   underline, hífen e ponto viram todos espaço — sem isso, os dois não casam e a mídia
   entra offline.

As duas regras vêm de `media/matcher.py`, do RELINKER, onde foram descobertas.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field

from .matcher import (
    _nome_do_arquivo,
    _duration_ok,
    _has_significant_token_overlap,
    _normalize_name,
    _token_sort_ratio,
)

log = logging.getLogger("delapraca.media.matcher_masters")

OPCOES_PADRAO = {
    # Score de nome abaixo do qual nem se considera candidato.
    "score_minimo": 0.70,
    # Score a partir do qual um candidato único é aceito sem revisão.
    "score_confiavel": 0.90,
    # Tolerância do portão de duração — o mesmo critério do RELINKER.
    "duration_tol_secs": 0.3,
    "duration_tol_rel": 0.01,
    # Quantos candidatos mostrar ao editor quando houver dúvida.
    "max_candidatos": 5,
}

# Ordem de confiança dos métodos. Um master resolvido por caminho não é rebaixado por
# outro que empatou no nome.
FORCA = {"manual": 6, "caminho": 5, "umid": 4, "nome_exato": 3, "reel": 3, "imagem": 3, "nome_frouxo": 2}


@dataclass
class Casamento:
    """O que se decidiu sobre um master.

    Três estados, e a diferença entre os dois últimos é o ponto:

    - **resolvido** — `arquivo` preenchido; entra no relink sem perguntar.
    - **sugerido** — há um palpite bom, mas ele **não** vira relink sozinho:
      aparece no painel para o editor confirmar com um clique.
    - **não resolvido** — nada plausível, ou ambíguo demais para palpitar.
    """

    master: object                       # aaf.masters.Master
    arquivo: str | None = None
    sugestao: str | None = None
    metodo: str = "nao_resolvido"
    confianca: float = 0.0
    ambiguo: bool = False
    candidatos: list[dict] = field(default_factory=list)
    motivo: str = ""
    #: o arquivo do master é um TRECHO do original (o render da cor voltando, BL09): `{desloc_quadros, desloc_s,
    #: motivo}` de `prproj.originais._trecho` — quem entrega desloca o ponto de entrada (`baselight_conform.da_carta`)
    trecho: dict | None = None

    @property
    def resolvido(self) -> bool:
        return self.arquivo is not None

    @property
    def precisa_de_revisao(self) -> bool:
        """O editor precisa olhar para este?"""
        return self.ambiguo or not self.resolvido or self.confianca < 0.9

    def to_dict(self) -> dict:
        return {
            "nome": self.master.nome,
            "mob_id": self.master.mob_id,
            "e_audio": self.master.e_audio,
            "segmentos": self.master.segmentos,
            "arquivo": self.arquivo,
            "sugestao": self.sugestao,
            "metodo": self.metodo,
            "confianca": round(self.confianca, 3),
            "ambiguo": self.ambiguo,
            "precisa_de_revisao": self.precisa_de_revisao,
            "motivo": self.motivo,
            "candidatos": self.candidatos,
            # para o relink manual e a coluna "De onde veio" (ver `aaf.masters.Master`)
            "origem": getattr(self.master, "origem", "") or "",
            "uso_frames": getattr(self.master, "uso_frames", None),
            "duracao_frames": getattr(self.master, "duracao_frames", None),
            "edit_rate": getattr(self.master, "edit_rate", None),
            "usa_imagem": bool(getattr(self.master, "usa_imagem", False)),
            "canais_som": int(getattr(self.master, "canais_som", 0) or 0),
            # a janela de conflito mostra o quadro do DAILY ao lado do de cada candidato (autor, 2026-11-22)
            "daily": _daily(self.master) if not self.master.e_audio else None,
            "duracao_s": _duracao_do_master(self.master),
            **({"trecho": self.trecho} if self.trecho else {}),
        }


def _chave_uid(valor) -> str:
    """UMID de qualquer procedência → 32 bytes em hex.

    ⚠️ O prefixo sai antes do filtro de hexadecimais: `urn:smpte:umid:` contribui com o
    **e** de `smpt`**e** e o **d** de `umi`**d**; o `0x` do ffprobe contribui com o
    **0**. Nenhum estoura — só fazem duas representações do MESMO UMID compararem como
    diferentes, e o estágio inteiro deixa de disparar sem que ninguém perceba.
    """
    if not valor:
        return ""
    s = str(valor).strip()
    baixo = s.lower()
    if baixo.startswith("urn:smpte:umid:"):
        s = s[len("urn:smpte:umid:"):]
    elif baixo.startswith("0x"):
        s = s[2:]
    hexa = "".join(c for c in s if c in "0123456789abcdefABCDEF").lower()
    return hexa if len(hexa) in (32, 64) else ""


def _duracao_do_master(master) -> float | None:
    if master.duracao_frames and master.edit_rate:
        return master.duracao_frames / master.edit_rate
    return None


def _passa_na_duracao(master, arquivo: dict, opcoes: dict):
    """True / False / None (neutro), no mesmo critério do RELINKER.

    ⚠️ Neutro **não** é aprovação: quer dizer que falta duração de um dos lados e o
    portão não opina. Reprovar aqui deixaria de fora todo áudio cujo `duration_ms` o
    indexer não leu.
    """
    return _duration_ok({"media_ref": {"source_duration_secs": _duracao_do_master(master)}},
                        arquivo, opcoes)


def casar_masters(masters, indice: dict, opcoes: dict | None = None,
                  progresso=None) -> list[Casamento]:
    """Casa cada master com um arquivo do índice.

    Args:
        masters: de `aaf.masters.masters_em_uso()`.
        indice: de `media.indexer.index_folder()` — usa a chave `"files"`.
        progresso: `callable(feito, total, nome)`, opcional.

    A cascata, e o que cada degrau vale:

    | # | estágio | como casa | confiança |
    |---|---|---|---|
    | 1 | **caminho** | o master já aponta para um arquivo que existe | 1.00 |
    | 2 | **UMID** | identidade de essência — não depende de nome nenhum | 0.95 |
    | 3 | **nome exato** | normalizado: sufixos Avid fora, separadores unificados | 1.00 |
    | 4 | **nome frouxo** | `token_sort_ratio` ≥ 0.70 | o próprio score |

    A duração é **veto transversal**: reprova um candidato em qualquer estágio de nome.

    ⭐ Empate não vira escolha. Dois candidatos igualmente plausíveis são marcados
    `ambiguo` e vão para o editor — *relink errado é pior que nenhum relink*.
    """
    opcoes = {**OPCOES_PADRAO, **(opcoes or {})}
    arquivos = indice.get("files") or []

    # Índices montados uma vez: com centenas de masters e milhares de arquivos, refazer
    # a normalização por par custa mais que todo o resto do matcher junto.
    por_caminho = {a["path"]: a for a in arquivos}
    por_uid: dict[str, list[dict]] = {}
    por_nome: dict[str, list[dict]] = {}
    normalizados: list[tuple[str, dict]] = []
    for a in arquivos:
        uid = _chave_uid(a.get("uid"))
        if uid:
            por_uid.setdefault(uid, []).append(a)
        nome = _normalize_name(_nome_do_arquivo(a))      # sequência de imagens: o nome-base (P10)
        if nome:
            por_nome.setdefault(nome, []).append(a)
            normalizados.append((nome, a))

    resultados: list[Casamento] = []
    total = len(masters)

    for i, master in enumerate(masters):
        if progresso:
            progresso(i, total, master.nome)
        resultados.append(_casar_um(master, opcoes, por_caminho, por_uid,
                                    por_nome, normalizados))

    if progresso:
        progresso(total, total, "")
    _suprimir_duplicatas(resultados)
    return resultados


def _casar_um(master, opcoes, por_caminho, por_uid, por_nome, normalizados) -> Casamento:
    r = Casamento(master=master)

    # ── 1) caminho ──────────────────────────────────────────────────────────
    caminho = getattr(master, "caminho_conhecido", None)
    if caminho and caminho in por_caminho:
        r.arquivo, r.metodo, r.confianca = caminho, "caminho", 1.0
        return r

    # ── 2) UMID ─────────────────────────────────────────────────────────────
    # Identidade de essência: quando existe, não depende de nome nem de duração.
    uid = _chave_uid(master.mob_id)
    if uid:
        candidatos = por_uid.get(uid) or []
        if len(candidatos) == 1:
            r.arquivo, r.metodo, r.confianca = candidatos[0]["path"], "umid", 0.95
            return r
        if len(candidatos) > 1:
            r.ambiguo = True
            r.candidatos = [_cand(a, 0.95, "umid") for a in candidatos[:opcoes["max_candidatos"]]]
            r.motivo = f"{len(candidatos)} arquivos com o mesmo UMID"
            return r

    # ── 3 e 4) nome ─────────────────────────────────────────────────────────
    alvo = _normalize_name(master.nome)
    if not alvo:
        r.motivo = "o master não tem nome utilizável"
        return r

    exatos = por_nome.get(alvo) or []
    if exatos:
        return _decidir(r, [(a, 1.0) for a in exatos], "nome_exato", opcoes)

    # ── 3b) reel / tape name: CRITÉRIO (autor, 2026-11-22), com as mesmas provas do nome ────────────────────────────
    # Nenhum arquivo com o nome do master: o reel gravado no DAILY (o arquivo que o master aponta) procura o original
    # de mesmo nome que o reel (laboratório BL08, P4: `CENA12_T3` com reel `B001C007`). O MC 25.12 não leva o
    # `reel_name` ao AAF — o reel vem do arquivo (`media/confirmacao.reel_do_arquivo`).
    if not master.e_audio:
        reel = _reel(master)
        if reel and _normalize_name(reel) != alvo:
            por_reel = [a for a in por_nome.get(_normalize_name(reel)) or [] if a["path"] != _daily(master)]
            if por_reel:
                r2 = _decidir(r, [(a, 1.0) for a in por_reel], "reel", opcoes)
                if r2.arquivo and not r2.motivo:
                    r2.motivo = f"casado pelo reel do daily ({reel}): o nome do master é outro"
                return r2

    pontuados: list[tuple[dict, float]] = []
    for nome, arquivo in normalizados:
        score = _token_sort_ratio(alvo, nome)
        if score < opcoes["score_minimo"]:
            continue
        # ⚠️ Guarda contra o falso positivo mais comum do acervo: `A004_03170917_C003`
        # e `A002_03170813_C004` diferem só em dígitos e pontuam altíssimo por
        # similaridade de caracteres. Exigir um token longo em comum separa os dois.
        if not _has_significant_token_overlap(alvo, nome):
            continue
        pontuados.append((arquivo, score))

    if not pontuados:
        r.motivo = "nenhum arquivo com nome parecido"
        return r

    melhor = max(s for _a, s in pontuados)
    topo = [(a, s) for a, s in pontuados if s >= melhor - 1e-9]
    return _decidir(r, topo, "nome_frouxo", opcoes, todos=pontuados)


def _tc_em_quadros(tc, fps) -> int | None:
    """`"HH:MM:SS:FF"` (o `tc_start` do indexador; `;` do drop-frame) → quadros na base NOMINAL, ou `None`.

    ⛔ CORRIGE (2026-11-21, laboratório Baselight 2997DF, MC 25.12 Mac): o rótulo DROP-FRAME (`;`, base 30/60) vira a
    contagem CONTÍNUA — a mesma unidade do `tc_quadros` do master (o `Timecode.start` do AVB é sempre contínuo; banco
    avb/fontes.md, 107892 = 01;00;00;00). Lido como non-drop, o 14:59:50;00 do original saía 54 s depois do master
    (1618080 → "14:58:56:00") e o arquivo CERTO era recusado por "timecode diferente": 0 de 2 casados."""
    import re
    m = re.match(r"\s*(\d{1,2})[:;.](\d{2})[:;.](\d{2})([:;.])(\d{1,3})", str(tc or ""))
    if not m or not fps:
        return None
    h, mi, s, sep, f = m.groups()
    h, mi, s, f = int(h), int(mi), int(s), int(f)
    n = round(float(fps))
    q = ((h * 60 + mi) * 60 + s) * n + f
    if sep == ";" and n in (30, 60):
        minutos = h * 60 + mi
        q -= (n // 15) * (minutos - minutos // 10)          # 2 (ou 4) rótulos pulados por minuto, menos os décimos
    return q


def _tc_texto(q: int, fps) -> str:
    n = round(float(fps or 24)) or 24
    s, f = divmod(int(q), n)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


#: TCs "iguais" até 1 s: o MC grava o TC do H.264 com desconto de 2 quadros num corpus e sem noutro
#: (`clone_generic._probe_start_tc`), e o MP4 de 60p/100p conta os quadros na METADE da base (banco `avb/escrita.md`).
#: Um take de outra câmera ou de outra diária com o mesmo nome difere por muito mais que isso.
TC_TOLERANCIA_S = 1.0


def _portao_tc(master, arquivo: dict):
    """A regra da B110 (autor, 2026-10-31), a mesma do `.prproj` (`prproj/originais.casar_um`): `None` = não opina
    (o master sem TC real — o fluxo do proxy sem TC: o zero do lado do projeto não muda nada); `True` = confere;
    `False` = TCs reais diferentes (outro arquivo com o mesmo nome); `"duvida"` = o master tem TC real e o candidato
    vem zerado ou sem TC — uma conversão que perdeu o TC? O arquivo do master não está no disco (senão o 1º estágio
    teria casado), então ele ENTRA, com o aviso ("depende do disco"). ⚠️ "Sem TC" pode ser só o leitor que não acha o
    TC de uma câmera (R04: Sony MP4) — por isso é aviso, nunca recusa."""
    a, fa = getattr(master, "tc_quadros", None), getattr(master, "tc_fps", None)
    if not a or not fa or getattr(master, "e_audio", False):
        # ⚠️ Só IMAGEM: o TC do WAV mora no `time_reference` do bext (B087), que nem o MediaInfo do indexador nem o
        # ffprobe dão como TC — todo som direto viraria "TC a conferir". A conversão que perde o TC é a de vídeo.
        return None
    fb = arquivo.get("frame_rate") or fa
    b = _tc_em_quadros(arquivo.get("tc_start"), fb)
    if b is None and arquivo.get("path"):
        # O MediaInfo do indexador não lê o TC de todo MP4 (lab B110: o .mp4 com `tmcd` 10:00:00:00 veio sem
        # `tc_start`) — a reserva é a sondagem do ffprobe do `.prproj` (com cache): um processo por candidato que chega aqui.
        try:
            from prproj.originais import sondar
            s = sondar(arquivo["path"])
            b = _tc_em_quadros(s.get("tc"), s.get("fps") or fb) if s.get("ok") else None
            fb = s.get("fps") or fb
        except Exception:  # noqa: BLE001 — sem a sondagem, fica o que o indexador disse
            pass
    if not b:
        return "duvida"
    if abs(a / round(float(fa)) - b / round(float(fb))) <= TC_TOLERANCIA_S:
        return True
    # ⭐ O MESMO RÓTULO, só com a marca de drop-frame diferente (laboratório BL08, P7, 2026-11-22): o original de 29,97
    # grava `16:58:50;00` (DF) e a conversão copiou o rótulo como `16:58:50:00` (NDF). Contados em quadros eles ficam
    # 61 s longe e o arquivo certo era recusado; o rótulo idêntico é a prova — a conversão perdeu só o `;`.
    tc_cand = str(arquivo.get("tc_start") or "")
    if not tc_cand and arquivo.get("path"):
        try:
            from prproj.originais import sondar
            tc_cand = str(sondar(arquivo["path"]).get("tc") or "")
        except Exception:  # noqa: BLE001
            tc_cand = ""
    rotulo = tc_cand.replace(";", ":").replace(".", ":")[:11]
    return bool(rotulo) and rotulo == _tc_texto(a, fa)


def _decidir(r: Casamento, topo, metodo, opcoes, todos=None) -> Casamento:
    """Aplica o portão de duração ao topo e decide — ou manda para o editor."""
    viaveis, reprovados, tc_diferente, duvidosos = [], 0, 0, []
    for arquivo, score in topo:
        portao = _passa_na_duracao(r.master, arquivo, opcoes)
        if portao is False:
            reprovados += 1
            continue
        tc = _portao_tc(r.master, arquivo)
        if tc is False:
            tc_diferente += 1
            continue
        (duvidosos if tc == "duvida" else viaveis).append((arquivo, score, portao))
    # o candidato de TC zerado/ausente só conta quando nenhum outro confere o TC (B110: o que confere vence)
    duvida = None
    if not viaveis and duvidosos:
        viaveis = duvidosos
        a, fa = r.master.tc_quadros, r.master.tc_fps
        duvida = (f"TC a conferir: o candidato tem TC zerado ou ausente; o do master, {_tc_texto(a, fa)} "
                  "(uma conversão que perdeu o TC?)")

    if len(viaveis) == 1:
        arquivo, score, portao = viaveis[0]
        r.metodo = metodo
        # Duração confirmada sobe a confiança; portão neutro (falta o dado de um dos
        # lados) mantém o score do nome, sem premiar nem punir.
        r.confianca = 1.0 if (metodo == "nome_exato" and portao is True) else score
        r.candidatos = [_cand(arquivo, score, metodo, provas=_provas(r.master, arquivo, portao))]

        if metodo == "nome_frouxo":
            # ⭐ Match frouxo NUNCA vira relink sozinho — só sugestão.
            #
            # Medido neste acervo: de 101 casamentos por nome, **100 foram exatos e o
            # único frouxo era falso positivo** — `23_19_13 Cordas Trompa Oboé.wav`
            # casou com `09;36;23 Cordas Trompa_02.wav` a 0,731, porque "cordas" e
            # "trompa" bastam para o guard de tokens e os números do timecode diferem
            # em silêncio. São músicas diferentes.
            #
            # A normalização de separadores é o que de fato resolve o acervo, e ela
            # resolve por nome EXATO. O frouxo não agregou um acerto sequer e produziu
            # o único erro. Como o critério aqui é humano — o editor tem a imagem na
            # tela —, o palpite vale como atalho, não como decisão.
            r.sugestao = arquivo["path"]
            r.motivo = f"sugestão por semelhança de nome ({score:.0%}) — confirme"
            return r

        r.arquivo = arquivo["path"]
        if portao is None:
            r.motivo = "sem duração para conferir"
        if duvida:
            # entra (é a única mídia), mas no topo da revisão com o motivo — `precisa_de_revisao` abaixo de 0,9
            r.confianca, r.motivo = min(r.confianca, 0.85), duvida
        return r

    if len(viaveis) > 1 and _copias_identicas([a["path"] for a, _s, _p in viaveis]):
        # Cópias IDÊNTICAS (backup, dois HDs): não há o que escolher — valem como um original só, o da 1ª pasta
        # (a regra do casador do Premiere). Os outros ficam na lista, para o editor ver qual foi usado.
        arquivo, score, _p = sorted(viaveis, key=lambda v: v[0]["path"])[0]
        r.arquivo, r.metodo, r.confianca = arquivo["path"], metodo, 1.0 if metodo != "nome_frouxo" else score
        r.candidatos = [_cand(a, s, metodo, provas=_provas(r.master, a, p)) for a, s, p in viaveis]
        pasta = os.sep.join(os.path.dirname(arquivo["path"]).split(os.sep)[-3:])
        r.motivo = f"{len(viaveis)} cópias idênticas — usada a de …{os.sep}{pasta}"
        return r

    if len(viaveis) > 1 and not r.master.e_audio and metodo != "nome_frouxo":
        # ⭐ O empate só se resolve com CONFIRMAÇÃO VISUAL; sem ela, nunca decidimos sozinhos (autor, 2026-11-22):
        # o quadro do DAILY × o de cada candidato (`media/confirmacao.py`).
        daily = _daily(r.master)
        if daily:
            from .confirmacao import confirmar_pela_imagem
            escolhido, notas = confirmar_pela_imagem(daily, [a["path"] for a, _s, _p in viaveis],
                                                     _duracao_do_master(r.master))
            if notas:
                r.candidatos = [_cand(a, s, metodo, provas=_provas(r.master, a, p, notas.get(a["path"])))
                                for a, s, p in viaveis[:opcoes["max_candidatos"]]]
            if escolhido:
                outras = sorted((v for k, v in notas.items() if k != escolhido), reverse=True)
                r.arquivo, r.metodo, r.confianca = escolhido, "imagem", 0.95
                r.motivo = (f"{len(viaveis)} arquivos empatam em nome e duração; a imagem do daily confirmou este "
                            f"({notas[escolhido]:.2f} × {outras[0]:.2f})")
                return r
            if notas:
                r.ambiguo, r.metodo = True, metodo
                r.motivo = (f"{len(viaveis)} arquivos empatam em nome e duração, e a imagem do daily não separa "
                            f"({' × '.join(f'{v:.2f}' for v in sorted(notas.values(), reverse=True))}) — escolha")
                return r

    if len(viaveis) > 1:
        r.ambiguo = True
        r.metodo = metodo
        r.candidatos = [_cand(a, s, metodo, provas=_provas(r.master, a, p))
                        for a, s, p in viaveis[:opcoes["max_candidatos"]]]
        r.motivo = f"{len(viaveis)} arquivos igualmente plausíveis"
        _explicar_empate_de_audio(r)
        return r

    # ⭐ O RENDER DA COR VOLTANDO (BL09, 2026-11-23; a regra do casador do Premiere, `prproj.originais._trecho`): o
    # arquivo do master é MAIS CURTO que o original de mesmo nome/reel, na mesma taxa, com o TC real DENTRO dele — o
    # Baselight grava no render o TC de fonte e o reel do original. Duração e TC reprovavam o original certo. Entra com
    # o deslocamento e no topo da revisão (0,85): quem entrega tem de deslocar o ponto (o Baselight o faz).
    if not viaveis and metodo in ("nome_exato", "reel") and not r.master.e_audio:
        trechos = [(a, t) for a, _s in topo if (t := _trecho_do_master(r.master, a))]
        if len(trechos) > 1 and _copias_identicas([a["path"] for a, _t in trechos]):
            trechos = sorted(trechos, key=lambda v: v[0]["path"])[:1]
        if len(trechos) == 1:
            arquivo, t = trechos[0]
            r.arquivo, r.metodo, r.confianca, r.trecho = arquivo["path"], metodo, 0.85, t
            r.candidatos = [_cand(arquivo, 1.0, metodo)]
            r.motivo = t["motivo"]
            return r
        if len(trechos) > 1:
            r.ambiguo, r.metodo = True, metodo
            r.candidatos = [_cand(a, 1.0, metodo) for a, _t in trechos[:opcoes["max_candidatos"]]]
            r.motivo = f"{len(trechos)} originais contêm o trecho deste master — escolha"
            return r

    # Todos reprovados pela duração — é informação, não silêncio. ⭐ E os candidatos
    # REPROVADOS continuam na lista de propósito: o editor tem a imagem na tela e decide
    # com um clique. O portão tira do automático, não do alcance.
    fonte = todos or topo
    r.candidatos = [_cand(a, s, metodo) for a, s in list(fonte)[:opcoes["max_candidatos"]]]
    if tc_diferente and not reprovados:
        r.motivo = (f"{tc_diferente} arquivo(s) com o nome certo, mas timecode diferente (o do master, "
                    f"{_tc_texto(r.master.tc_quadros, r.master.tc_fps)}) — outro arquivo de mesmo nome? confirme")
    elif reprovados:
        # ⚠️ O NÚMERO junto, senão "duração incompatível" não dá para julgar. Com ele o
        # editor distingue na hora os dois casos que produzem a mesma recusa: mídia
        # consolidada (master curto, arquivo inteiro — o candidato é o certo) e clipe
        # homônimo de outra diária (durações sem relação — o candidato é o errado).
        dur = _duracao_do_master(r.master)
        quanto = f", o master tem {dur:.1f}s" if dur else ""
        r.motivo = (f"{reprovados} arquivo(s) com o nome certo, mas duração "
                    f"incompatível{quanto} — confirme se for o certo")
    else:
        r.motivo = "nenhum candidato passou"
    return r


def _explicar_empate_de_audio(r: Casamento) -> None:
    """Num empate entre WAVs, o bext diz ao editor SE são o mesmo áudio — sem escolher por ele.

    ⭐ Empate continua do editor (autor, 2026-09-27). O que muda é a explicação: a `referencia` + a `amostra_inicial` do
    bext sobrevivem à troca de nome entre cópias (`media/bwf.identidade`). Iguais = o MESMO áudio em cópias diferentes
    (no PRODUCAO-A: o do Pro Tools em 24 bits × uma conversão do ffmpeg em 16); diferentes = áudios DIFERENTES com o
    mesmo nome (versão de aprovação × final) — aí escolher errado troca a mixagem.

    ⚠️ É a única leitura de arquivo deste módulo, e só no empate: um cabeçalho de WAV (o `data` é pulado)."""
    from .bwf import identidade

    ids = []
    for c in r.candidatos:
        if not str(c.get("path", "")).lower().endswith((".wav", ".bwf")):
            return
        i = identidade(c["path"])
        if i:
            c["bext"] = i
        ids.append(i)
    chaves = {(i.get("referencia"), i.get("amostra_inicial")) for i in ids}
    if not all(i.get("referencia") for i in ids):
        return
    if len(chaves) == 1:
        bits = sorted({i.get("bits") for i in ids if i.get("bits")}, reverse=True)
        diferenca = f" — diferem em {' × '.join(f'{b} bits' for b in bits)}" if len(bits) > 1 else ""
        r.motivo = (f"{len(ids)} cópias do MESMO áudio (mesma origem e TC no bext){diferenca} — escolha qual usar")
    else:
        r.motivo = (f"{len(ids)} áudios DIFERENTES com o mesmo nome (origens diferentes no bext: versões?) — "
                    "confira qual é o da edição")


def _cand(arquivo: dict, score: float, metodo: str, provas: dict | None = None) -> dict:
    d = {
        "path": arquivo["path"],
        "filename": arquivo.get("filename"),
        "score": round(float(score), 3),
        "metodo": metodo,
        "duration_ms": arquivo.get("duration_ms"),
        "frame_rate": arquivo.get("frame_rate"),
        "tc": arquivo.get("tc_start"),
        "largura": arquivo.get("width"),
        "altura": arquivo.get("height"),
    }
    if provas:
        d["provas"] = provas
    return d


def _provas(master, arquivo: dict, portao_duracao, imagem: float | None = None) -> dict:
    """O que bateu e o que não bateu, com o número — a janela de conflito mostra (autor, 2026-11-22: "nunca esconde o
    porquê"). `True`/`False`/`None` (não se sabe) em cada critério."""
    tc = None
    try:
        tc = _portao_tc(master, arquivo)
    except Exception:  # noqa: BLE001 — prova que não se lê não derruba o casamento
        pass
    return {"duracao": portao_duracao, "tc": None if tc == "duvida" else tc, "tc_duvida": tc == "duvida",
            "imagem": imagem}


def _trecho_do_master(master, arquivo: dict) -> dict | None:
    """O master (pelo arquivo dele, o daily; sem ele, pelo TC e a duração do próprio master) é um trecho de `arquivo`?"""
    try:
        from prproj.originais import _trecho, sondar
        s = sondar(arquivo["path"])
        if not s.get("ok"):
            return None
        daily = _daily(master)
        px = sondar(daily) if daily else {}
        if not px.get("ok"):
            fps = float(master.edit_rate or 0) or None
            tq, tf = getattr(master, "tc_quadros", None), getattr(master, "tc_fps", None)
            if not (fps and master.duracao_frames and tq and tf and abs(float(tf) - fps) < 0.01):
                return None
            px = {"ok": True, "fps": fps, "dur_s": master.duracao_frames / fps, "tc_quadros": tq,
                  "tc": _tc_texto(tq, fps)}
        return _trecho(px, s)
    except Exception:  # noqa: BLE001 — a prova do trecho é a mais; sem ela, vale a recusa de sempre
        return None


def _daily(master) -> str | None:
    """O arquivo que o master aponta (o DAILY do offline: `origem`, o caminho que o AAF/a bin grava), se está nesta
    máquina. ⚠️ O AAF do MC no Mac grava o caminho sem o `/Volumes` (`/SSD/…`)."""
    o = getattr(master, "origem", "") or ""
    if not o:
        return None
    for c in (o, "/Volumes" + o if o.startswith("/") and not o.startswith("/Volumes/") else None):
        if c and os.path.isfile(c):
            return c
    return None


def _reel(master) -> str | None:
    import re as _re
    daily = _daily(master)
    if not daily:
        return None
    from .confirmacao import reel_do_arquivo
    reel = (reel_do_arquivo(daily) or "").strip()
    # reel degenerado (só dígitos ou 1–2 caracteres: o "1" do BRAW, banco B040) não identifica nada
    return None if not reel or _re.fullmatch(r"\d+|.{1,2}", reel) else reel


def _copias_identicas(caminhos: list[str]) -> bool:
    from .matcher import _copias_identicas as iguais
    return iguais(caminhos)


def _suprimir_duplicatas(resultados: list[Casamento]) -> None:
    """Um arquivo não pode ser a fonte de dois masters diferentes.

    Quando dois reivindicam o mesmo arquivo, o de método mais forte fica e o outro volta
    a ser não resolvido — com o motivo dito. Vem do RELINKER, onde o caso real era "CAM B
    casa CAM A.mxf quando CAM A já o tem a 100%".

    ⭐ Exceção: dois masters com o MESMO nome procurado não disputam — são o mesmo original.
    Medido em 2026-09-26 no relink aos originais pela Carta (ADR 0020): o Avid tem vários
    masters de um mesmo arquivo (o `Source File` igual — T.01 e T.02 da mesma fita), e a
    supressão deixava o segundo offline sem motivo. A disputa da regra é entre nomes
    DIFERENTES (CAM B × CAM A), e essa continua.
    """
    dono: dict[str, Casamento] = {}
    for r in resultados:
        if not r.resolvido:
            continue
        atual = dono.get(r.arquivo)
        if atual is None:
            dono[r.arquivo] = r
            continue
        if _normalize_name(r.master.nome) == _normalize_name(atual.master.nome):
            continue
        if FORCA.get(r.metodo, 0) > FORCA.get(atual.metodo, 0):
            perdedor, dono[r.arquivo] = atual, r
        else:
            perdedor = r
        vencedor = dono[r.arquivo]
        perdedor.candidatos = perdedor.candidatos or [
            _cand({"path": perdedor.arquivo, "filename": None}, perdedor.confianca,
                  perdedor.metodo)]
        perdedor.arquivo = None
        perdedor.metodo = "nao_resolvido"
        perdedor.confianca = 0.0
        perdedor.motivo = (f"esse arquivo já é de {vencedor.master.nome!r} "
                           f"(por {vencedor.metodo})")


def resumo(resultados: list[Casamento]) -> dict:
    """Números para a UI e para o log."""
    por_metodo: dict[str, int] = {}
    for r in resultados:
        por_metodo[r.metodo] = por_metodo.get(r.metodo, 0) + 1
    return {
        "total": len(resultados),
        "resolvidos": sum(1 for r in resultados if r.resolvido),
        "sugeridos": sum(1 for r in resultados if r.sugestao and not r.resolvido),
        "ambiguos": sum(1 for r in resultados if r.ambiguo),
        "nao_resolvidos": sum(1 for r in resultados if not r.resolvido),
        "precisam_de_revisao": sum(1 for r in resultados if r.precisa_de_revisao),
        "segmentos_resolvidos": sum(r.master.segmentos for r in resultados if r.resolvido),
        "segmentos_total": sum(r.master.segmentos for r in resultados),
        "por_metodo": por_metodo,
    }
