"""Quem fala cada fala — pela LAPELA mais forte, sobre a transcrição que já existe.

⭐⭐ Plano `docs/plano/2026-11-06-transcricao-por-canal.md` (F1). Decisão do autor (2026-11-06): *energia das lapelas
+ Whisper só no ambíguo*. A transcrição da MIXAGEM fica como está (o cache sobrevive, nada se ouve de novo); este
estágio acrescenta, por fala, o canal que fala. Porte da regra de `_ASSIST ANTERIOR/assist_anterior/som/atribuicao.py`.

## Por que a lapela, e não um modelo

Medido em 2026-11-06 (banco `transversal/ia-embarcada-nos-nles.md` §3e): o "Separar falas sobrepostas" do Premiere
(1 crédito/s, na nuvem) separou o take `C4 P4-T003` em duas vozes, e elas SÃO as lapelas — onde a MIC2 lidera, o
`falante_2` domina 97 %; onde a MIC3 lidera, o `falante_1`, 88 %. O técnico de som já separou os atores no set.
Medido no Assist anterior (D02): 91,9 % atribuído; quem usa lapela domina por 8–27 dB, a equipe fica em 0–3 dB.

## A regra (pura: `atribuir`), e o que ela recusa

Ganha a trilha de PESSOA com mais energia no intervalo da fala, por uma margem (3 dB). E:

1. ⛔ O mixdown nunca disputa (contém todas as vozes).
2. ⛔ O boom nunca disputa, mesmo sendo o mais alto: pega os dois atores; deixá-lo disputar faria o plano em que ele
   está mais perto roubar a fala da lapela, calado.
3. ⚠️⚠️ Com menos de DUAS lapelas medidas é **não avaliado**, nunca "resolvido": sem com o que comparar não há
   margem (o oitavo falso-verde do Assist anterior: "100 % resolvido" num documentário de uma lapela só).
4. Empate dentro da margem = **ambígua, com os candidatos** (decisão do autor: nada some calado). A F2 transcreve as
   lapelas em disputa nesse trecho.

⚠️ A margem de 3 dB NÃO foi calibrada contra verdade-terreno — saiu de inspeção num take (Assist anterior). Fica exposta.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import binarios as _binarios
from . import canais as _canais

log = logging.getLogger("cicloassist.midia.falantes")

#: ⚠️ Escolhida por inspeção (Assist anterior, D02), não medida contra verdade-terreno.
MARGEM_DB = 3.0
#: A janela do envelope de energia. 50 ms: uma sílaba tem ~200 ms; a fala mais curta que importa ("Ação"), ~400.
JANELA_S = 0.05
TAXA = 16000
#: Abaixo disto (dBFS) o canal está calado nesta fala — não disputa (canal de reserva gravando ruído).
PISO_DB = -70.0

RESOLVIDA = "resolvida"
AMBIGUA = "ambigua"
SEM_COMPARACAO = "sem-comparacao"
#: Não há nome de trilha nenhum (bin sem `TRK`, WAV sem iXML): a posição não diz o papel.
SEM_NOMES = "sem-nomes"

#: Vai em `falantes.json`: mudou, o estágio é refeito sozinho na próxima leitura.
#: ⭐⭐ Cada canal é medido contra o PRÓPRIO nível (o percentil abaixo do envelope do take inteiro), não em dBFS cru.
#: MEDIDO em 2026-11-06 no `C4 P4-T003` (MIC2/MIC3/BOOM): em dBFS cru a MIC2 entra ~8 dB acima da MIC3 (ganho da
#: mesa) e a EQUIPE ("Cena 4, plano 4, tomada 3", "Ação", "Cortou") saía "MIC2 por 5–8 dB" — 10 de 19 de
#: concordância com o "Separar falas" da Adobe. Normalizado pelo p95: a equipe cai em 0–3 dB (ambígua — a faixa que o
#: Assist anterior mediu para a equipe na D02) e os atores ficam em 9–21 dB. É a "dominância exclusiva" do banco
#: (`metadado-de-canal-do-som-direto.md` §6b), a única estatística que ORDENA certo.
PERCENTIL_DE_REFERENCIA = 95

#: ⭐ F2 (autor, 2026-11-06): uma fala AMBÍGUA só é ouvida lapela a lapela quando DUAS ou mais lapelas estão "altas"
#: — acima disto, em dB relativos ao p95 do próprio canal. MEDIDO no `C4 P4-T003`: a fala do próprio ator fica de −5 a
#: +4; a equipe ao fundo, de −24 a −11; a leitura da claquete (diante dos atores), −4 nas duas. Abaixo do limiar, a
#: ambígua é "provável equipe" e nada roda — transcrever a equipe lapela por lapela não acrescenta nada.
ALTA_DB = -8.0
#: Textos das lapelas tão parecidos quanto isto (por LETRAS, `difflib`) são a MESMA voz ouvida pelas duas (a claquete);
#: abaixo, vozes diferentes ao mesmo tempo — fala SOBREPOSTA. ⛔ Por palavras inteiras (Jaccard) a 1ª versão errou:
#: "Será 4, os câmeras?" × "Sena 4, câmera…" (a mesma voz, o ASR errando diferente em cada lapela) deu 0 palavras em
#: comum e virou "sobreposta". MEDIDO por letras: a mesma voz 0,80–1,00; vozes diferentes 0,32–0,50.
MESMA_VOZ = 0.65
#: A borda do trecho recortado para o Whisper, dos dois lados (a palavra que o ASR da mixagem cortou no meio).
FOLGA_S = 0.25

SOBREPOSTA = "sobreposta"

ASSINATURA = {"regra": "lapela-mais-forte", "versao": 4, "margem_db": MARGEM_DB, "janela_s": JANELA_S,
              "taxa": TAXA, "piso_db": PISO_DB, "normalizacao": f"p{PERCENTIL_DE_REFERENCIA}",
              "alta_db": ALTA_DB, "mesma_voz": MESMA_VOZ, "folga_s": FOLGA_S}


class MedicaoFalhou(RuntimeError):
    pass


@dataclass(frozen=True)
class Atribuicao:
    """O veredito de UMA fala. ⚠️ `margem_db` None = não houve comparação (medida vazia = NÃO MEDIDO, nunca zero)."""

    motivo: str
    canal: int | None = None
    nome: str = ""
    margem_db: float | None = None
    candidatos: tuple[dict[str, Any], ...] = ()
    niveis_db: dict[int, float] = field(default_factory=dict)

    def como_dicionario(self) -> dict[str, Any]:
        d: dict[str, Any] = {"motivo": self.motivo}
        if self.canal is not None:
            d.update(canal=self.canal, nome=self.nome)
        if self.margem_db is not None:
            d["margem_db"] = round(self.margem_db, 1)
        if self.candidatos:
            d["candidatos"] = list(self.candidatos)
        if self.niveis_db:
            d["niveis_db"] = {str(k): round(v, 1) for k, v in self.niveis_db.items()}
        return d


def atribuir(niveis_db: dict[int, float], trilhas: list[_canais.Trilha],
             margem_db: float = MARGEM_DB, piso_db: float = PISO_DB) -> Atribuicao:
    """A regra, pura. `niveis_db`: canal (base 1) → nível (dB) no intervalo da fala; abaixo de `piso_db` não disputa."""
    if not trilhas or all(not t.nome for t in trilhas):
        return Atribuicao(SEM_NOMES)
    pessoas = [t for t in trilhas if t.e_pessoa and t.canal in niveis_db and niveis_db[t.canal] > piso_db]
    medidos = {t.canal: niveis_db[t.canal] for t in pessoas}
    if len(pessoas) < 2:
        # ⚠️ uma lapela só NÃO é "ela falou": é não avaliado. Os níveis vão junto, para quem quiser auditar.
        return Atribuicao(SEM_COMPARACAO, niveis_db=medidos)
    ordem = sorted(pessoas, key=lambda t: niveis_db[t.canal], reverse=True)
    primeiro, segundo = ordem[0], ordem[1]
    margem = niveis_db[primeiro.canal] - niveis_db[segundo.canal]
    if margem >= margem_db:
        return Atribuicao(RESOLVIDA, primeiro.canal, primeiro.nome, margem, niveis_db=medidos)
    empatados = tuple({"canal": t.canal, "nome": t.nome,
                       "abaixo_db": round(niveis_db[primeiro.canal] - niveis_db[t.canal], 1)}
                      for t in ordem if niveis_db[primeiro.canal] - niveis_db[t.canal] < margem_db)
    return Atribuicao(AMBIGUA, margem_db=margem, candidatos=empatados, niveis_db=medidos)


# ── a medição: o envelope de energia de cada canal ───────────────────────────

def _streams(arquivo: str) -> list[int]:
    """Canais de cada stream de áudio do arquivo (`[5]` num BWF de 5; `[1, 1, 1, 1]` no `.mov` do RED)."""
    ffprobe = _binarios.achar("ffprobe")
    if not ffprobe:
        raise MedicaoFalhou("o ffprobe não foi encontrado nesta máquina")
    try:
        r = subprocess.run([ffprobe, "-v", "error", "-select_streams", "a", "-show_entries",
                            "stream=channels", "-of", "csv=p=0", arquivo],
                           capture_output=True, text=True, timeout=60, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError) as e:
        raise MedicaoFalhou(f"não consegui sondar {arquivo}: {e}") from e
    return [int(x) for x in r.stdout.split() if x.strip().isdigit()]


def _envelope_do_stream(ffmpeg: str, arquivo: str, stream: int, canais: int,
                         janela_s: float = JANELA_S) -> list[list[float]]:
    """Energia média (potência) por janela, por canal deste stream. Lido EM FLUXO: memória constante num take de
    centenas de MB (a lição do `energia.py` do Assist anterior)."""
    import numpy as np  # noqa: PLC0415 — numpy já é dependência (vetores); import local para o módulo ser leve

    por_janela = int(TAXA * janela_s)
    bloco = por_janela * canais * 2 * 200          # 200 janelas por leitura (10 s)
    cmd = [ffmpeg, "-v", "error", "-i", arquivo, "-map", f"0:a:{stream}", "-ar", str(TAXA),
           "-f", "s16le", "-acodec", "pcm_s16le", "-"]
    try:
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except OSError as e:
        raise MedicaoFalhou(f"não consegui abrir {arquivo}: {e}") from e
    partes: list[Any] = []
    resto = b""
    assert p.stdout is not None
    while True:
        lido = p.stdout.read(bloco)
        if not lido:
            break
        dados = resto + lido
        uteis = len(dados) // (por_janela * canais * 2) * (por_janela * canais * 2)
        resto = dados[uteis:]
        if uteis:
            a = np.frombuffer(dados[:uteis], np.int16).astype(np.float32) / 32768.0
            a = a.reshape(-1, por_janela, canais)
            partes.append((a * a).mean(axis=1))          # [janelas, canais]
    if p.wait(timeout=60) != 0 and not partes:
        raise MedicaoFalhou(f"o ffmpeg não conseguiu ler o som de {Path(arquivo).name}")
    if not partes:
        return [[] for _ in range(canais)]
    env = np.concatenate(partes, axis=0)
    return [env[:, c].tolist() for c in range(canais)]


def fontes(arquivos: list[str]) -> dict[int, tuple[str, int, int]]:
    """canal do MASTER (base 1) → (arquivo, stream de áudio, canal dentro do stream). A mesma conta de `envelopes`."""
    if len(arquivos) == 1:
        saida, canal = {}, 1
        for st, n in enumerate(_streams(arquivos[0])):
            for c in range(n):
                saida[canal] = (arquivos[0], st, c)
                canal += 1
        return saida
    posicoes = [_canais.posicao_do_arquivo(a) for a in arquivos]
    if None in posicoes or len(set(posicoes)) != len(posicoes):
        posicoes = list(range(1, len(arquivos) + 1))
    return {pos: (arq, 0, 0) for pos, arq in zip(posicoes, arquivos)}


def envelopes(arquivos: list[str], janela_s: float = JANELA_S) -> dict[int, list[float]]:
    """canal do MASTER (base 1) → potência por janela de `janela_s` (padrão `JANELA_S`; a borda da voz usa 10 ms).

    ⭐ OP-Atom: um arquivo por canal, e a posição sai do NOME (`_A03`) — sem ela, a ordem da lista. Um arquivo só
    (BWF, `.mov` AMA): os canais na ordem de interleave, stream a stream."""
    ffmpeg = _binarios.achar("ffmpeg")
    if not ffmpeg:
        raise MedicaoFalhou("o ffmpeg não foi encontrado nesta máquina")
    saida: dict[int, list[float]] = {}
    if len(arquivos) == 1:
        canal = 1
        for s, n in enumerate(_streams(arquivos[0])):
            for env in _envelope_do_stream(ffmpeg, arquivos[0], s, n, janela_s):
                saida[canal] = env
                canal += 1
        return saida
    posicoes = [_canais.posicao_do_arquivo(a) for a in arquivos]
    if None in posicoes or len(set(posicoes)) != len(posicoes):
        posicoes = list(range(1, len(arquivos) + 1))
        log.info("canais sem posição no nome; uso a ordem da lista (%d arquivos)", len(arquivos))
    for pos, arq in sorted(zip(posicoes, arquivos)):
        envs = _envelope_do_stream(ffmpeg, arq, 0, 1, janela_s)
        saida[pos] = envs[0] if envs else []
    return saida


def nivel_db(env: list[float], inicio_s: float, fim_s: float) -> float | None:
    """Nível médio (dBFS) do canal entre `inicio_s` e `fim_s`. `None` = fora do que foi medido."""
    a = max(0, int(inicio_s / JANELA_S))
    b = min(len(env), max(a + 1, int(math.ceil(fim_s / JANELA_S))))
    if a >= b:
        return None
    pot = sum(env[a:b]) / (b - a)
    return 10 * math.log10(pot) if pot > 0 else -120.0


def referencia_db(env: list[float]) -> float:
    """O nível de referência do canal no take: o percentil `PERCENTIL_DE_REFERENCIA` do envelope, em dB."""
    if not env:
        return 0.0
    ordenado = sorted(env)
    pot = ordenado[min(len(ordenado) - 1, int(len(ordenado) * PERCENTIL_DE_REFERENCIA / 100))]
    return 10 * math.log10(pot) if pot > 0 else -120.0


def atribuir_falas(falas: list[dict[str, Any]], envs: dict[int, list[float]],
                   trilhas: list[_canais.Trilha]) -> list[dict[str, Any]]:
    """Uma atribuição por fala, na MESMA ordem da transcrição (o índice é a ligação).

    ⚠️ O piso (`PISO_DB`) é conferido no nível CRU (canal calado de verdade); a disputa, no NORMALIZADO."""
    ref = {c: referencia_db(env) for c, env in envs.items()}
    saida = []
    for f in falas:
        ini, fim = float(f.get("inicio") or 0), float(f.get("fim") or 0)
        crus = {c: n for c, env in envs.items() if (n := nivel_db(env, ini, fim)) is not None}
        rel = {c: (n - ref[c]) if n > PISO_DB else PISO_DB - 1 for c, n in crus.items()}
        d = atribuir(rel, trilhas, piso_db=PISO_DB - 0.5).como_dicionario()
        if d["motivo"] == AMBIGUA:
            altas = [c["canal"] for c in d.get("candidatos") or [] if rel.get(c["canal"], -999) >= ALTA_DB]
            if len(altas) >= 2:
                d["altas"] = altas            # F2 ouve estas lapelas neste trecho
            else:
                d["provavel"] = "equipe"      # ninguém de lapela perto: a voz vem de longe
        saida.append(d)
    return saida


# ── F2: ouvir as lapelas em disputa, só no trecho ────────────────────────────

def _letras(texto: str) -> str:
    import re  # noqa: PLC0415
    import unicodedata  # noqa: PLC0415
    t = unicodedata.normalize("NFKD", (texto or "").lower())
    return re.sub(r"[^a-z0-9]", "", "".join(ch for ch in t if not unicodedata.combining(ch)))


def parecenca(a: str, b: str) -> float:
    """Parecença por LETRAS (sem acento, espaço nem pontuação), 0 a 1 — tolera o ASR errando diferente em cada
    lapela ("Será" × "Sena")."""
    import difflib  # noqa: PLC0415
    la, lb = _letras(a), _letras(b)
    if not la and not lb:
        return 1.0
    return difflib.SequenceMatcher(None, la, lb).ratio()


def _recortar(fonte: tuple[str, int, int], inicio_s: float, fim_s: float, destino: Path) -> Path:
    ffmpeg = _binarios.achar("ffmpeg")
    if not ffmpeg:
        raise MedicaoFalhou("o ffmpeg não foi encontrado nesta máquina")
    arq, st, c = fonte
    ini = max(0.0, inicio_s - FOLGA_S)
    r = subprocess.run([ffmpeg, "-v", "error", "-y", "-ss", f"{ini:.3f}", "-t", f"{fim_s + FOLGA_S - ini:.3f}",
                        "-i", arq, "-map", f"0:a:{st}", "-af", f"pan=mono|c0=c{c}", "-ar", str(TAXA),
                        "-acodec", "pcm_s16le", str(destino)],
                       capture_output=True, timeout=120, stdin=subprocess.DEVNULL)
    if r.returncode != 0:
        raise MedicaoFalhou(f"não consegui recortar o canal de {Path(arq).name}")
    return destino


def ouvir_ambiguas(falas: list[dict[str, Any]], atribuicoes: list[dict[str, Any]], arquivos: list[str],
                   trilhas: list[_canais.Trilha], ouvir=None) -> int:
    """⭐ F2: para cada ambígua com lapelas ALTAS, transcreve cada uma no trecho e decide mesma voz × sobreposta.

    `ouvir(wav) -> texto` (padrão: o Whisper do produto). Devolve quantas foram ouvidas. Falha numa fala não derruba
    as outras: ela fica ambígua, como estava."""
    import tempfile  # noqa: PLC0415
    if ouvir is None:
        from . import asr as _asr  # noqa: PLC0415 — carregar o modelo só quando há o que ouvir

        def ouvir(wav):
            return " ".join(f.texto for f in _asr.transcrever(wav)).strip()
    nomes = {t.canal: t.nome for t in trilhas}
    mapa = None
    ouvidas = 0
    with tempfile.TemporaryDirectory(prefix="cicloassist-vozes-") as tmp:
        for f, a in zip(falas, atribuicoes):
            if a.get("motivo") != AMBIGUA or not a.get("altas"):
                continue
            try:
                mapa = mapa or fontes(arquivos)
                vozes = []
                for canal in a["altas"]:
                    wav = _recortar(mapa[canal], float(f["inicio"]), float(f["fim"]),
                                    Path(tmp) / f"c{canal}.wav")
                    vozes.append({"canal": canal, "nome": nomes.get(canal, ""), "texto": ouvir(wav)})
            except (MedicaoFalhou, KeyError, OSError, subprocess.SubprocessError, RuntimeError) as e:
                log.info("não consegui ouvir as lapelas em %.1f s: %s", float(f.get("inicio") or 0), e)
                continue
            ouvidas += 1
            com_texto = [v for v in vozes if v["texto"]]
            iguais = all(parecenca(com_texto[0]["texto"], v["texto"]) >= MESMA_VOZ for v in com_texto[1:])
            if len(com_texto) >= 2 and not iguais:
                a["motivo"] = SOBREPOSTA
                a["vozes"] = com_texto
            else:
                a["mesma_voz"] = True     # uma voz que as lapelas ouviram juntas (a claquete): não é de ninguém
                a["vozes"] = vozes
    return ouvidas


# ── o estágio no cache ───────────────────────────────────────────────────────

ARQUIVO = "falantes.json"


def _impressao_da_transcricao(midia) -> str:
    """A transcrição de que estas atribuições dependem. Refeita a transcrição, o estágio cai sozinho."""
    try:
        return hashlib.sha1(midia.arquivo("transcricao.json").read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def ler(midia) -> dict[str, Any]:
    """O `falantes.json` SE ainda vale (receita de hoje e a mesma transcrição); senão `{}`."""
    dados = midia._ler_json(midia.arquivo(ARQUIVO))
    if (not dados or dados.get("assinatura") != ASSINATURA
            or dados.get("transcricao") != _impressao_da_transcricao(midia)):
        return {}
    return dados


def garantir(midia, arquivos: list[str], trilhas: list[_canais.Trilha], fonte_dos_nomes: str = "",
             forcar: bool = False, ouvir=None) -> dict[str, Any]:
    """Deixa `falantes.json` no cache e o devolve. Barato quando já está: só lê.

    ⚠️ Sem nomes de trilha (`trilhas` vazio), grava o "sem nomes" — e isso é RESPOSTA (a tela diz "não sei quem
    fala: as trilhas não têm nome"), não falha. Volta a ser medido quando o nome aparecer (`forcar`, ou uma
    receita/transcrição nova)."""
    if not forcar:
        pronto = ler(midia)
        if pronto and (pronto.get("trilhas") or not trilhas):
            return pronto
    falas = midia.ler_transcricao()
    dados: dict[str, Any] = {"assinatura": ASSINATURA, "transcricao": _impressao_da_transcricao(midia),
                             "fonte_dos_nomes": fonte_dos_nomes,
                             "trilhas": [t.como_dicionario() for t in trilhas]}
    if not trilhas or all(not t.nome for t in trilhas):
        dados["falas"] = [{"motivo": SEM_NOMES} for _ in falas]
    else:
        envs = envelopes([str(a) for a in arquivos])
        dados["canais_medidos"] = sorted(envs)
        dados["falas"] = atribuir_falas(falas, envs, trilhas)
        dados["ouvidas"] = ouvir_ambiguas(falas, dados["falas"], [str(a) for a in arquivos], trilhas, ouvir)
    from .cache import escrever_atomico  # noqa: PLC0415 — `cache` importa muito; aqui só quando grava
    escrever_atomico(midia.pasta / ARQUIVO, json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8"))
    return dados


def contagem(dados: dict[str, Any]) -> dict[str, int]:
    """`{"resolvida": 23, "ambigua": 4, …}` — o resumo que vai para o log e para a tela."""
    c: dict[str, int] = {}
    for f in dados.get("falas") or []:
        c[f.get("motivo", "?")] = c.get(f.get("motivo", "?"), 0) + 1
    return c


# ── F3: como quem fala APARECE (chat, busca) ─────────────────────────────────

def rotulo(a: dict[str, Any] | None) -> str:
    """A atribuição de UMA fala em poucas palavras, para o modelo e para a tela. `""` = nada a dizer (sem nomes,
    uma lapela só) — o campo some em vez de dizer "não sei" em cada fala; quem diz isso é o resumo do take."""
    if not a:
        return ""
    m = a.get("motivo")
    if m == RESOLVIDA:
        return str(a.get("nome") or "")
    if m == SOBREPOSTA:
        vozes = " + ".join(f'{v.get("nome")} «{str(v.get("texto") or "")[:60]}»' for v in a.get("vozes") or [])
        return f"sobreposta: {vozes}"
    if m == AMBIGUA:
        nomes = " ou ".join(str(c.get("nome")) for c in a.get("candidatos") or [] if c.get("nome"))
        if a.get("mesma_voz"):
            return f"a mesma voz em {nomes.replace(' ou ', ' e ')} (de fora das lapelas: equipe, claquete)"
        if a.get("provavel") == "equipe":
            return "provável equipe"
        return f"ambígua: {nomes}" if nomes else "ambígua"
    return ""


def anexar(falas: list[dict[str, Any]], dados: dict[str, Any] | None) -> list[dict[str, Any]]:
    """As falas do master com `quem` (o `rotulo`), pela POSIÇÃO — a mesma ordem da transcrição de onde saíram.

    ⛔ Só se as contagens baterem: `falantes.json` de outra transcrição (contagem diferente) não se cola calado."""
    ats = (dados or {}).get("falas") or []
    if not ats or len(ats) != len(falas):
        return falas
    return [{**f, "quem": q} if (q := rotulo(a)) else f for f, a in zip(falas, ats)]


def resumo(dados: dict[str, Any] | None) -> str:
    """Uma linha para o take: de onde vieram os nomes e quanto se resolveu — ou por que não se sabe."""
    if not dados:
        return ""
    if dados.get("erro"):
        return f"não consegui ver quem fala: {dados['erro']}"
    trilhas = [_canais.Trilha(**t) for t in dados.get("trilhas") or []]
    if not trilhas or all(not t.nome for t in trilhas):
        return ("não sei quem fala: as trilhas de som deste take não têm nome (nem coluna TRK na bin, nem iXML no "
                "arquivo) — e a posição do canal não diz quem é")
    pessoas = [t for t in trilhas if t.e_pessoa]
    c = contagem(dados)
    if len(pessoas) < 2:
        return f"uma lapela só ({_canais.resumo(pessoas) or 'nenhuma'}): sem com quem comparar, não digo quem fala"
    partes = [f"{c.get(RESOLVIDA, 0)} resolvidas"]
    if c.get(SOBREPOSTA):
        partes.append(f"{c[SOBREPOSTA]} sobrepostas")
    if c.get(AMBIGUA):
        partes.append(f"{c[AMBIGUA]} ambíguas (equipe ou vozes de fora das lapelas)")
    fonte = {"bin": "colunas da bin", "ixml": "iXML do arquivo"}.get(str(dados.get("fonte_dos_nomes")), "")
    return (f"quem fala, pela lapela mais forte ({', '.join(t.nome for t in pessoas)}"
            f"{'; nomes das ' + fonte if fonte else ''}): " + ", ".join(partes))
