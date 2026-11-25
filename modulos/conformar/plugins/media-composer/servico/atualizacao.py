"""A EXECUÇÃO do "Atualizar timeline", do lado do serviço (caminho B, decidido em 2026-09-27).

A casca do NLE exporta a timeline de TRABALHO do colorista (o arquivo que o próprio Resolve dele
grava) para `recebidos/<uuid>.drt` e conta os planos de cada trilha pela API. Aqui:

1. confere que o arquivo exportado É aquela timeline (a contagem da API bate com a do arquivo). O
   `Export` do Resolve por script externo exporta a timeline errada (banco `resolve-scripting/
   api-scripting.md` §7): se não bater, para, antes de mexer em qualquer coisa;
2. traduz as trilhas do DRT para as da Carta (o writer compacta as trilhas) e monta o plano de
   edição (`motor/atualizar.py`), com o áudio indo para o da versão nova;
3. reescreve o arquivo (`motor/drp/reescrever.py`: só Start/Duration/In, itens apagados, ids novos,
   marcadores do colorista pelo mapa de tempo) num `recebidos/<uuid>.drt` novo;
4. diz à casca o que INSERIR pela API (a mídia desta máquina, o trecho da fonte, o quadro, a trilha)
   e os SINAIS (marcador de timeline + cor local) nos planos novos, aparados e a conferir.

Nada é apagado nem alterado na timeline do colorista: a casca importa o reescrito como timeline NOVA,
confere a contagem que este módulo prevê e só então manda a antiga para o Backup.
"""

from __future__ import annotations

import json
import re
import uuid
import zipfile
from pathlib import Path

RE_DRT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.drt$")
#: Os Sinais do Atualizar: o que pede cada situação (o código de cores é o da equipe, em Ajustes).
SINAL = {"novo": "refazer", "trocado": "refazer", "esticado": "conferir", "aparado": "conferir",
         "camada": "conferir"}
ROTULO = {"novo": "NOVO NO CORTE: sem correção", "trocado": "TAKE TROCADO: sem correção",
          "esticado": "PLANO ESTICADO: o pedaço novo está sem correção",
          "aparado": "PLANO APARADO: conferir a correção nas pontas",
          "camada": "CAMADA SOBRE UM TRECHO QUE SAIU: conferir"}


def arquivo_de_trabalho(caminho: str, recebidos: Path) -> str:
    """Só o arquivo que a casca gravou em `recebidos/<uuid>.drt` (a mesma tranca do V9).

    ⛔ Pentest 2026-09-29 (A2): o `resolve()` TOCA o disco — num caminho `\\\\host\\...` ele consulta o
    host (SMB, o hash NTLM do usuário) ANTES de a comparação com `recebidos` recusá-lo. O caminho de
    rede é recusado pela forma, sem tocar em nada (a mesma regra de `caminho_confiavel`)."""
    bruto = str(caminho or "")
    if bruto.replace("\\", "/").startswith("//"):
        raise ValueError("o arquivo da timeline de trabalho não veio da casca do De Lá Pra Cá")
    p = Path(bruto).resolve()
    if p.parent != recebidos.resolve() or not RE_DRT.match(p.name) or not p.is_file():
        raise ValueError("o arquivo da timeline de trabalho não veio da casca do De Lá Pra Cá")
    return str(p)


def devolvido_por(arquivos: dict):
    """O que o setor devolveu à edição passou pela caixa `para-edicao` de um canal."""
    def devolvido(seg: dict, master: dict) -> bool:
        c = str(arquivos.get(seg.get("mob_id") or "") or master.get("caminho_na_bin") or "")
        return "para-edicao" in c.replace("\\", "/").lower().split("/")
    return devolvido


def ler_trabalho(partida, trabalho: str, contagem_api: dict, inicio: int | None = None):
    """A timeline de trabalho que a casca exportou, conferida: `(ini, itens, no_arquivo, itens_c)`.

    Confere que o arquivo é DRT e que é a timeline que o Resolve contou (a API e o arquivo têm de
    ter os mesmos itens por trilha). `itens_c` são os itens já nas trilhas da Carta."""
    import atualizar as A
    from drp import reescrever as RW

    # O início da timeline: o que o Resolve diz (`GetStartFrame`), senão o da Carta de partida (o
    # writer usou o mesmo). NUNCA o primeiro plano: a PRODA começa em 00:00:00:01 e a conta andava
    # um quadro (medido 2026-09-28).
    # ⚠️ 0 É um início válido (timeline em 00:00:00:00): `is None`, nunca `or` (revisão 2026-09-28).
    tsf = partida.resultado.get("timeline_start_frames")
    ini = int(inicio) if inicio is not None else int(tsf) if tsf is not None else RW.inicio_timeline(trabalho)
    try:
        itens = RW.itens(trabalho, inicio=ini)
    except (zipfile.BadZipFile, StopIteration, KeyError, UnicodeDecodeError):
        # a ponte sem a constante usa o número (1 = DRT); se a versão renumerar, sai outro formato
        raise ValueError("o Resolve exportou a timeline de trabalho num formato que não é DRT — "
                         "nada foi alterado") from None
    no_arquivo = RW.contagem(trabalho)            # itens + transições: o que a API conta
    api = {str(k): int(v) for k, v in (contagem_api or {}).items() if int(v or 0) > 0}
    if no_arquivo != api:
        raise ValueError("o Resolve exportou uma timeline diferente da de trabalho "
                         f"(arquivo {no_arquivo}, Resolve {api}) — abra a timeline de trabalho no "
                         "Resolve e tente de novo; nada foi alterado")
    usadas = A.trilhas_usadas(partida.resultado)
    return ini, itens, no_arquivo, A.trilhas_da_carta(itens, usadas)


def _regioes_de_transicao(carta, usadas: dict, ini: int) -> dict:
    """{(trilha do DRT, início absoluto, duração): transição da Carta} — a REGIÃO, que bate 58/58 no U03."""
    import atualizar as A

    fora = {}
    for t in A.transicoes(carta.resultado):
        idx, nova_trilha = A.trilha_do_drt(t["trilha"], usadas)
        if not nova_trilha:
            fora[(f"{t['trilha'][0]}{idx}", ini + t["inicio"], t["dur"])] = t
    return fora


def ajustar_transicoes(nova, drt: str, usadas: dict, ini: int, planos_novos: list | None = None,
                       do_editor: set | None = None, colorista_tirou: set | None = None) -> tuple[dict, list[str]]:
    """A timeline reescrita fica com as transições da versão NOVA (autor, 2026-10-01: "a atualização deve
    manter transição, nada deve ser perdido"): ESCREVE as que o editor pôs e TIRA as que ele tirou.

    Tudo comparado na posição NOVA (revisão de código 2026-10-01: a versão antiga contra o DRT já movido não
    via a transição que o editor tirou depois de um ripple, e uma transição de outro tamanho no mesmo corte
    ficava em dobro):
    - `do_editor`: as transições da timeline que estavam na versão antiga, onde o reescritor as pôs;
      sai a que não está na versão nova (inclusive a que mudou de tamanho: a nova entra no lugar);
    - `colorista_tirou`: as da versão antiga que já não estavam na timeline, levadas à posição nova — o
      colorista as tirou, e não voltam (as dele, fora da versão antiga, nunca são tocadas).

    ⭐ O ALINHAMENTO sai da GEOMETRIA da timeline, não do `cutpoint` do Avid. Medido no Resolve 21
    (2026-10-01): uma transição cujo alinhamento não casa com onde os planos se encontram é DESCARTADA na
    importação, calada — e o lado de lá pode faltar NESTA máquina (a mídia que não está aqui: o Trazer fez
    ali um fade de entrada). `planos_novos`: `[(trilha, início, fim)]` que a casca vai inserir (contam)."""
    from aaf.parser import frames_to_tc
    from drp import reescrever as RW

    na_nova = _regioes_de_transicao(nova, usadas, ini)
    no_drt = {(t["trilha"], t["start"], t["dur"]) for t in RW.transicoes(drt)}
    pedacos = [(i["trilha"], i["start"], i["start"] + i["dur"]) for i in RW.itens(drt, absoluto=True)]
    pedacos += list(planos_novos or [])
    fps = float(nova.resultado.get("timeline_fps") or 24)
    tirar = (no_drt & set(do_editor or ())) - set(na_nova)
    acrescentar, avisos = [], []
    for k in sorted(set(na_nova) & set(colorista_tirou or ()) - no_drt, key=lambda k: (k[1], k[0])):
        # estava na versão antiga e já não estava na timeline: tirada aqui (ou perdida num Importar antigo).
        # Não volta sozinha — mas nada some calado.
        avisos.append(f"transição de {k[2]} quadro(s) na {k[0]} em {frames_to_tc(k[1], fps)}: está na versão do "
                      "editor e não estava na sua timeline — não foi reposta; conferir")
    for k in sorted(set(na_nova) - no_drt - set(colorista_tirou or ()), key=lambda k: (k[1], k[0])):
        t, (trilha, a, d) = na_nova[k], k
        b = a + d
        fins = [f for (tr, _i, f) in pedacos if tr == trilha and a <= f <= b]
        inis = [i for (tr, i, _f) in pedacos if tr == trilha and a <= i <= b]
        corte = next((f for f in fins if f in inis), None)
        if corte is not None:                      # dois planos se encontram dentro da região
            align = 1 if corte == a else (3 if corte == b else 2)
        elif a in inis and not fins:               # só o da direita, começando no início: fade de entrada
            align = 1
        elif b in fins and not inis:               # só o da esquerda, terminando no fim: fade de saída
            align = 3
        else:
            # o plano de um lado não está na timeline (um título que o Importar perdeu, a mídia que não está
            # nesta máquina) ou os planos não se encontram: uma transição ali ficaria sobre o vazio
            avisos.append(f"transição de {d} quadro(s) na {trilha} em {frames_to_tc(a, fps)}: os planos em "
                          "volta dela não estão na timeline como no Avid — não foi escrita; conferir")
            continue
        acrescentar.append({"trilha": trilha, "start": a, "dur": d, "audio": trilha[0] == "A", "align": align})
        ef = (t.get("efeito") or "").upper()
        if trilha[0] == "V" and ef and "DISSOLVE" not in ef:
            avisos.append(f"transição {t.get('efeito')} do Avid na {trilha}: entrou como Cross Dissolve — conferir")
    if not acrescentar and not tirar:
        return {}, avisos
    return RW.ajustar_transicoes(drt, acrescentar, tirar), avisos


def encaixe(partida, itens_c: list[dict], arquivos: dict) -> dict:
    """Quanto da versão antiga está na timeline de trabalho (`motor/atualizar.py::encaixe`), com o
    `minimo` e se `bate`. O que a cor devolveu à edição fica fora pela MESMA regra do plano:
    `arquivos` = os das duas versões (revisão 2026-09-28: a guarda media outro conjunto)."""
    import atualizar as A

    e = A.encaixe(partida.resultado, itens_c, devolvido=devolvido_por(arquivos))
    return {**e, "minimo": A.ENCAIXE_MINIMO, "bate": e["pct"] >= A.ENCAIXE_MINIMO}


def texto_nao_bate(e: dict) -> str:
    return (f"A versão antiga não bate com a timeline de trabalho: só {e['no_lugar']} de "
            f"{e['planos']} planos dela estão no lugar ({e['pct']:g}% da imagem). Nada foi alterado. "
            "Confira se escolheu o arquivo de onde esta timeline veio.")


def _drt_dos_offline(nova, segs, arquivo_do_seg, metas, offline, recebidos: Path, avisos: list) -> str:
    """O DRT AUXILIAR dos planos novos sem mídia nesta máquina: só os rótulos offline (nome, TC e duração do Avid),
    escritos pelo MESMO writer do Importar (`build_drt(..., offline=metas)`). A ponte o importa para os itens offline
    nascerem no pool e insere cada plano no quadro dele (`AppendToTimeline` aceita o item offline: medido no Studio 21.1,
    Mac, 2026-11-25 — A3, quadro 100, 48 quadros, início de fonte 10). Devolve o NOME do arquivo em `recebidos`, ou ""."""
    if not offline:
        return ""
    from drp.writer import build_drt

    idxs = sorted({int(x["segmento"]) for x in offline})
    sub = [segs[i] for i in idxs]
    casados = [{**arquivo_do_seg[i], "segment_index": k} for k, i in enumerate(idxs)]
    usados = {c.get("matched_path") for c in casados}
    destino = recebidos / f"{uuid.uuid4()}.drt"
    try:
        build_drt(sub, casados, str(destino), timeline_name="De Lá Pra Cá · offline do Atualizar",
                  timeline_fps=float(nova.resultado.get("timeline_fps") or 25.0),
                  offline={k: v for k, v in metas.items() if k in usados})
    except Exception as e:  # noqa: BLE001 — o resto da atualização segue; o aviso diz o que ficou de fora
        avisos.append(f"{len(offline)} plano(s) sem mídia não entraram offline (o rótulo não foi escrito: {e})")
        return ""
    return destino.name


def preparar(partida, nova, trabalho: str, contagem_api: dict, recebidos: Path, midia,
             sinais: dict | None = None, codigo: dict | None = None, inicio: int | None = None) -> dict:
    """`partida`/`nova`: as Cartas lidas. `midia(carta) -> (segs, casados)`: a mídia DESTA máquina
    para a Carta nova (o mesmo caminho do Importar). Devolve o que a casca precisa."""
    import atualizar as A
    from drp import reescrever as RW
    from drp import sinais as SN

    ini, itens, no_arquivo, itens_c = ler_trabalho(partida, trabalho, contagem_api, inicio)
    usadas = A.trilhas_usadas(partida.resultado)      # a trilha do DRT de cada plano a inserir
    # ⭐ A guarda (organograma de 2026-09-28): o plano de edição casa pela POSIÇÃO, então uma versão
    # antiga que não é desta timeline faria apagar e mover o que não mudou. Para ANTES de mexer.
    arquivos = {**partida.arquivos, **nova.arquivos}
    e = encaixe(partida, itens_c, arquivos)
    if not e["bate"]:
        raise ValueError(texto_nao_bate(e))
    pe = A.plano_de_edicao(partida.resultado, nova.resultado, itens_c, devolvido=devolvido_por(arquivos))

    # O que inserir: a mídia desta máquina para cada plano novo / pedaço esticado — ANTES de reescrever,
    # porque só o plano que VAI entrar segura a transição do corte dele (revisão de código 2026-10-01).
    # `midia` devolve (segs, casados) ou (segs, casados, metas): `metas` = {rótulo: {nb, fps, tc, …}} dos planos que
    # NÃO têm arquivo nesta máquina — eles entram OFFLINE no lugar (autor, 2026-11-25: "pode fazer o som novo entrar como
    # offline também. lembre da regra de nada sumir na timeline"). Antes eram pulados com um aviso.
    r_midia = midia(nova) if pe["inserir"] else ([], [], {})
    segs, casados = r_midia[0], r_midia[1]
    metas = dict(r_midia[2]) if len(r_midia) > 2 and r_midia[2] else {}
    arquivo_do_seg = {c["segment_index"]: c for c in casados}

    def entra(x) -> bool:
        """O plano novo entra: com o arquivo desta máquina, ou OFFLINE pelo rótulo (com os metadados do Avid)."""
        c = arquivo_do_seg.get(x["segmento"])
        return bool(c) and (not c.get("offline") or c.get("matched_path") in metas)
    com_midia = entra

    # Os cortes onde um plano novo vai encostar: ali a transição do colorista FICA (o plano já vem do
    # motor de corte a corte, `atualizar._de_corte_a_corte`).
    cortes = set()
    for x in pe["inserir"]:
        idx, nova_trilha = A.trilha_do_drt(x["trilha"], usadas)
        if not nova_trilha and com_midia(x):
            cortes |= {(x["trilha"][0], idx, ini + int(x["inicio"])),
                       (x["trilha"][0], idx, ini + int(x["inicio"]) + int(x["dur"]))}
    # As transições da timeline ANTES de reescrever: as que batem com a versão antiga são do EDITOR (o rastro
    # do reescritor diz onde cada uma foi parar); as da versão antiga que não estão aqui, o colorista tirou.
    na_velha = _regioes_de_transicao(partida, usadas, ini)
    no_trabalho = {(t["trilha"], t["start"], t["dur"]) for t in RW.transicoes(trabalho)}
    rastro: dict = {}
    destino = recebidos / f"{uuid.uuid4()}.drt"
    conta = RW.aplicar(trabalho, str(destino), pe["itens"], ini,
                       mover_quadro=lambda q: A.quadro_novo(pe["mapa"], q), cortes=cortes, rastro=rastro)
    do_editor = {(k[0], rastro[k], k[2]) for k in no_trabalho & set(na_velha) if rastro.get(k) is not None}
    colorista_tirou = set()
    for k in set(na_velha) - no_trabalho:
        q, ok = A.quadro_novo(pe["mapa"], k[1] - ini)
        if ok:
            colorista_tirou.add((k[0], ini + int(q), k[2]))
    n_trilhas = {"V": max([int(t[1:]) for t in no_arquivo if t[0] == "V"] or [0]),
                 "A": max([int(t[1:]) for t in no_arquivo if t[0] == "A"] or [0])}
    novas_trilhas: dict[str, int] = {}
    inserir, avisos = [], []
    for x in pe["inserir"]:
        c = arquivo_do_seg.get(x["segmento"])
        s = segs[x["segmento"]] if x["segmento"] < len(segs) else {}
        letra = x["trilha"][0]
        idx, nova_trilha = A.trilha_do_drt(x["trilha"], usadas)
        if nova_trilha:
            if x["trilha"] not in novas_trilhas:
                n_trilhas[letra] += 1
                novas_trilhas[x["trilha"]] = n_trilhas[letra]
            idx = novas_trilhas[x["trilha"]]
        if not entra(x):
            avisos.append(f"{x['nome']}: sem a mídia nesta máquina e sem o que o Avid diz dela — o plano não foi "
                          "inserido")
            continue
        offline = bool(c.get("offline"))
        if offline:
            avisos.append(f"{x['nome']}: sem a mídia nesta máquina — entrou OFFLINE no lugar; religue no Resolve")
        # A velocidade do EDITOR (a conformação de fps não é decisão de edição e o Resolve a faz
        # sozinho, quadro a quadro): a mesma regra das notas (`notas._velocidade`; revisão 2026-09-28).
        classe = str(s.get("motion_class") or "native")
        rel = float(s.get("relative_speed") or 1.0) or 1.0
        editor = classe not in ("native", "conform")
        inicio_fonte = int(s.get("source_start_frames") or 0) + int(x.get("fonte_offset") or 0)
        quadros_fonte = max(1, round(int(x["dur"]) / rel)) if editor and rel > 0 else int(x["dur"])
        if editor:
            avisos.append(f"{x['nome']}: tem velocidade {round(100 / rel) if rel else 0}% no Avid "
                          f"({classe}); entrou em 100% — refazer")
        canal = int(s.get("canal_arquivo") or s.get("source_slot_id") or 1)
        if letra == "A" and canal > 1:
            # a API não escolhe o canal do arquivo: o Resolve põe o dele; avisar para conferir
            avisos.append(f"{x['nome']}: o Avid usava o canal {canal} do arquivo — conferir o canal no Resolve")
        # ⚠️ `fim_fonte` é EXCLUSIVO: é o `endFrame` do `AppendToTimeline`, e o Resolve põe
        # `endFrame - startFrame` quadros (medido 2026-10-01, Studio 21.1, timeline vazia: 100→147 deu
        # 47, no vídeo e no áudio). Com o `- 1` de antes, cada plano novo entrava UM QUADRO mais curto
        # — um buraco de um quadro entre dois vídeos. No 19.0.0b, `pendente`: a casca confere a duração.
        inserir.append({"arquivo": c["matched_path"], "inicio_fonte": inicio_fonte,
                        "fim_fonte": inicio_fonte + quadros_fonte, "tipo": letra, "trilha": idx,
                        "trilha_nova": nova_trilha, "quadro": ini + int(x["inicio"]), "dur": int(x["dur"]),
                        "classe": x["classe"], "nome": x["nome"],
                        "canal": canal, "offline": offline, "segmento": x["segmento"]})
    drt_offline = _drt_dos_offline(nova, segs, arquivo_do_seg, metas, [x for x in inserir if x["offline"]],
                                   recebidos, avisos)
    if not drt_offline:     # sem o DRT dos rótulos, os offline não têm item no pool: não vão (e o aviso já diz)
        inserir = [x for x in inserir if not x["offline"]]
        avisos[:] = [a for a in avisos if "entrou OFFLINE" not in a]
    # As transições: DEPOIS de saber quais planos novos entram (os sem mídia aqui não contam como vizinhos).
    # O fim é `fim_fonte - inicio_fonte` e não `dur`: a casca insere a 100%, e é isso que o plano ocupa na
    # timeline (com velocidade do editor, `dur` seria o do Avid, e o aviso "refazer" já sai acima).
    novos = [(f"{x['tipo']}{x['trilha']}", int(x["quadro"]), int(x["quadro"]) + int(x["fim_fonte"]) - int(x["inicio_fonte"]))
             for x in inserir if not x.get("trilha_nova")]
    novas_tr, avisos_tr = ajustar_transicoes(nova, str(destino), usadas, ini, novos, do_editor, colorista_tirou)
    conta.update({k: v for k, v in novas_tr.items() if v})
    esperado = RW.contagem(str(destino))
    avisos += avisos_tr
    for t, i in novas_trilhas.items():
        avisos.append(f"a montagem nova usa uma trilha que a de trabalho não tinha ({t}): criada como "
                      f"{t[0]}{i}")
    if conta.get("marcadores_fora_do_lugar"):
        avisos.append(f"{conta['marcadores_fora_do_lugar']} marcador(es) seu(s) estava(m) num trecho que "
                      "saiu: ficaram no ponto do corte")

    # Os Sinais: marcador de timeline (no quadro) e cor LOCAL do plano (a casca acha o plano pela
    # trilha e pelo início). Só vídeo; o código de cores é o da equipe.
    sinais = sinais or {}
    codigo = SN.validar_codigo(codigo)
    marcas = []

    def sinal(classe, tipo, trilha_drt, quadro_abs, dur):
        if tipo != "V":
            return
        cat = SINAL[classe]
        marcas.append({"quadro": quadro_abs - ini, "quadro_abs": quadro_abs, "trilha": trilha_drt,
                       "dur": dur, "classe": classe, "cor_marcador": codigo["cores"][cat]["marcador"],
                       "cor_clipe": codigo["cores"][cat]["clipe"], "nome": ROTULO[classe],
                       "palavra": codigo["palavra"]})

    for x in inserir:
        sinal(x["classe"], x["tipo"], x["trilha"], x["quadro"], x["dur"])
    por_id = {i["id"]: i for i in itens}
    for a in pe["aparados"]:
        it = por_id[a["id"]]
        sinal("aparado", it["trilha"][0], int(it["trilha"][1:]), ini + int(a["inicio"]), int(a["dur"]))
    for a in pe["conferir"]:
        it = por_id[a["id"]]
        sinal("camada", it["trilha"][0], int(it["trilha"][1:]), ini + int(a["inicio"]), int(a["dur"]))

    Path(str(destino)[:-4] + ".midias.json").write_text(json.dumps(
        {"drt": destino.name, "midias": sorted({x["arquivo"] for x in inserir if not x["offline"]}),
         "offline_drt": drt_offline}, ensure_ascii=False),
        encoding="utf-8")
    return {"drt": str(destino), "esperado": esperado, "inserir": inserir,
            "marcas": marcas if (sinais.get("marcar") or sinais.get("colorir")) else [],
            "marcar": bool(sinais.get("marcar")), "colorir": bool(sinais.get("colorir")),
            "acoes": {k: v for k, v in conta.items() if k != "marcadores_fora_do_lugar"},
            "marcadores_fora_do_lugar": conta.get("marcadores_fora_do_lugar", 0),
            "avisos": avisos, "inicio": ini, "encaixe": e}
