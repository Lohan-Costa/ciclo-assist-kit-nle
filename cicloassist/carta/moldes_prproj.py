"""Os MOLDES do enxerto no projeto do EDITOR (o botão "Importar para o Premiere", 2026-11-14).

A escrita da timeline (`entrega_prproj.escrever_timeline`) copia estruturas que o PRÓPRIO Premiere gravou — nunca
adivinhadas (estrutura adivinhada já deu "projeto danificado"): a sequência, o clipe de som mono com e sem ganho, as
transições e o merged. Na bancada elas moravam na `ENTREGA v01`; o projeto do editor não as tem.

Decisão do autor (2026-11-14, caminho 1 + a ideia dele): o que o projeto do editor JÁ tem serve de molde; o que falta,
o Premiere monta numa CÓPIA de trabalho aberta ao lado (`cicloMontar`), que nunca volta para o projeto do editor — só a
sequência pedida volta, pelo `importSequences`.

⭐ A sequência-molde é feita SEMPRE na cópia: ela é consumida (esvaziada e renomeada com o nome da timeline), e uma
sequência do editor consumida voltaria pelo `importSequences` com o MESMO ObjectUID da original dele.
⭐ O merged não tem via de API (em nenhuma plataforma): sem um no projeto do editor, o PROJETO-MODELO do app (`MODELO`)
entra na cópia e dá o molde; sem modelo, os subclipes sincronizados vão pela mídia nativa, e é dito (`merged_fora`).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from . import entrega_prproj as _ep
from . import merged_prproj as _mp

#: a sequência que o Premiere monta na cópia, com tudo o que falta
NOME_DOS_MOLDES = "MOLDES (Ciclo Assist)"
#: a bin dela na cópia (a cópia nunca volta ao editor; a bin é só para não misturar)
BIN_DOS_MOLDES = "Ciclo Assist moldes"
#: o PROJETO-MODELO do app (decisão do autor, 2026-11-14): um merged de mídia sintética hiperleve, importado na CÓPIA
#: quando o projeto do editor não tem merged de onde tirar o molde — a "calibragem", calada (opção A do autor: nada
#: extra entra no projeto do editor). Feito na versão MAIS ANTIGA do Premiere suportada (o novo converte o antigo).
MODELO = Path(__file__).with_name("moldes") / "modelo.prproj"
#: o modelo de cada Premiere que não abre o de cima (um Premiere antigo não abre projeto novo): o do 26 rebaixado pelo
#: `laboratorio-de-midia/lab/prproj_downgrade.py` (2026-11-15) e PROVADO no Premiere de destino (o merged entra)
MODELOS = {23: MODELO.with_name("modelo 23.prproj"), 25: MODELO.with_name("modelo 25.prproj")}


def modelo_para(versao: str) -> Path:
    """O projeto-modelo que o Premiere `versao` abre: o do 26 para o 26+ (e versão desconhecida), senão o da maior
    versão de `MODELOS` que não passa da dele (o 24 abre o do 23)."""
    try:
        maior = int(str(versao).split(".")[0])
    except ValueError:
        return MODELO
    if maior >= 26:
        return MODELO
    cabem = [v for v in MODELOS if v <= maior]
    return MODELOS[max(cabem)] if cabem else MODELOS[min(MODELOS)]


#: a bin dele na cópia
BIN_DO_MODELO = BIN_DOS_MOLDES + "/modelo"
#: o molde do TÍTULO (2026-11-20): um gráfico com UMA camada de texto, feito pelo próprio Premiere (Graphics and
#: Titles › New Layer › Text) num projeto sem mídia — no 26 o `importMGT` do Basic Title põe um gráfico VAZIO (banco
#: `prproj/titulo-essential-graphics.md`). Importado na CÓPIA quando a timeline tem título e o editor não tem molde.
#: ⬜ 23 e 25: sem molde ainda (o título fica de fora, dito).
MOLDES_DE_TITULO = {26: MODELO.with_name("titulo 26.prproj")}
BIN_DO_TITULO = BIN_DOS_MOLDES + "/titulo"


def molde_de_titulo_para(versao: str) -> Path | None:
    """O molde de título que o Premiere `versao` abre (o do 26 para o 26+), ou None."""
    try:
        maior = int(str(versao).split(".")[0])
    except ValueError:
        maior = 26
    cabem = [v for v in MOLDES_DE_TITULO if v <= maior]
    return MOLDES_DE_TITULO[max(cabem)] if cabem else None
#: a mídia sintética dos modelos, onde ELA estiver nesta instalação
MIDIA_DO_MODELO = MODELO.with_name("midia")
#: os campos em que o `.prproj` guarda o caminho ABSOLUTO do arquivo de mídia
_CAMPOS_DE_CAMINHO = ("FilePath", "ActualMediaFilePath")


def modelo_no_lugar(modelo: Path, destino: Path, midia: Path | None = None) -> dict:
    """Grava em `destino` uma cópia do projeto-modelo com a mídia apontando para `midia` (padrão: a pasta `midia/` ao
    lado dos modelos, onde o app estiver). ⭐ Os modelos guardam o caminho ABSOLUTO de quando foram feitos
    (`/Volumes/SSD/…/moldes/midia/…`): noutra máquina, noutro sistema ou com o app instalado noutro lugar, o
    Premiere pediria para localizar a mídia no meio da calibragem calada. Só os arquivos que existem em `midia` são
    trocados (o caminho no formato do sistema em que o app roda — é o mesmo do Premiere). O original não muda.
    Devolve {"trocados", "faltam": [nomes sem arquivo em `midia`]}."""
    import gzip
    import re
    from xml.sax.saxutils import escape
    pasta = Path(midia) if midia else MIDIA_DO_MODELO
    dados = Path(modelo).read_bytes()
    xml = (gzip.decompress(dados) if dados[:2] == b"\x1f\x8b" else dados).decode("utf-8")
    trocados, faltam = 0, set()

    def trocar(m: re.Match) -> str:
        nonlocal trocados
        antigo = m.group(2)
        nome = re.split(r"[\\/]", antigo)[-1]
        novo = pasta / nome
        if not novo.is_file():
            faltam.add(nome)
            return m.group(0)
        trocados += 1
        return f"<{m.group(1)}>{escape(str(novo.resolve()))}</{m.group(1)}>"

    xml = re.sub(r"<(%s)>([^<]*)</\1>" % "|".join(_CAMPOS_DE_CAMINHO), trocar, xml)
    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_bytes(gzip.compress(xml.encode("utf-8")))
    return {"trocados": trocados, "faltam": sorted(faltam)}
#: o ganho do molde "com ganho" (qualquer valor ≠ 0 serve: o que se copia é a ESTRUTURA do filtro de volume)
GANHO_DO_MOLDE_DB = 4.0


def inventario(R: ET.Element, por: dict | None = None) -> dict:
    """O que o projeto JÁ tem como molde: {"som_sem_ganho", "som_com_ganho", "transicao_V", "transicao_A": bool,
    "merged": nº de canais do maior merged (0 = nenhum)}."""
    por = por if por is not None else {_ep._chave(e): e for e in R if _ep._chave(e)}
    som = _ep._moldes_de_som(R, por)
    tr = _ep._moldes_de_transicao(R)
    m = _mp.molde(R, por)
    return {"som_sem_ganho": "sem_ganho" in som, "som_com_ganho": "com_ganho" in som,
            "transicao_V": "V" in tr, "transicao_A": "A" in tr, "merged": len(m["canais"]) if m else 0,
            "titulo": _ep.molde_de_titulo(R, por) is not None,
            "esticar": _ep.molde_de_esticar(R, por) is not None,
            "cor": _ep.molde_de_cor(R, por) is not None}


def o_que_a_timeline_pede(proj, item: dict) -> dict:
    """{"video", "som", "ganho", "transicao_V", "transicao_A", "merged": bool} — os moldes de que a timeline precisa."""
    from . import itens as _itens
    trilhas = item.get("trilhas", [])
    clipes_a = [c for t in trilhas if t["tipo"] == "A" for c in t.get("clipes", [])]
    pede = {"video": any(t["tipo"] == "V" and t.get("clipes") for t in trilhas), "som": bool(clipes_a),
            "ganho": any(c.get("ganho_db") not in (None, 0, 0.0) or c.get("ganho_no_item_db") for c in clipes_a),
            "transicao_V": False, "transicao_A": False, "merged": False,
            "titulo": any(_ep.titulo_do_trecho(s) for t in trilhas if t["tipo"] == "V" for s in t.get("sem_clipe") or []),
            "esticar": any(c.get("enquadramento") == "stretch" for t in trilhas if t["tipo"] == "V"
                           for c in t.get("clipes", [])),
            "cor": any(_ep.cor_do_clipe(c) for t in trilhas if t["tipo"] == "V" for c in t.get("clipes", []))}
    for t in trilhas:
        for x in t.get("transicoes") or []:
            lado = (_ep.TRANSICAO_DO_AVID.get(x.get("efeito") or "") or (None,))[0]
            if lado:
                pede[f"transicao_{lado}"] = True
    usados = {c["item"] for t in trilhas for c in t.get("clipes", []) if c.get("item")}
    if usados:
        pede["merged"] = any(d["id"] in usados and d.get("tipo") == "sincronizado" for _, d in _itens.todos(proj))
    return pede


def faltam(inv: dict, pede: dict) -> list[str]:
    """Os moldes que o Premiere tem de montar na cópia. "sequencia" está sempre (ver o docstring do módulo)."""
    out = ["sequencia"]
    if pede.get("som") and not inv["som_sem_ganho"]:
        out.append("som")
    if pede.get("ganho") and not inv["som_com_ganho"]:
        out.append("ganho")
    for lado in ("V", "A"):
        if pede.get(f"transicao_{lado}") and not inv[f"transicao_{lado}"]:
            out.append(f"transicao_{lado}")
    if pede.get("merged") and not inv["merged"]:
        out.append("merged")          # ⛔ sem via de API: fica dito, nunca montado
    if pede.get("esticar") and not inv.get("esticar"):
        out.append("esticar")
    if pede.get("cor") and not inv.get("cor"):
        out.append("cor")
    if pede.get("titulo") and not inv.get("titulo"):
        out.append("titulo")          # vem do molde do app (`MOLDES_DE_TITULO`), importado na cópia
    return out


def _no(R: ET.Element, cpi_uid: str) -> str | None:
    """O `nodeId` do ExtendScript de um ClipProjectItem: o `Node/ID` dele em hexadecimal, 8 dígitos (medido: 1000018 →
    `000f4252`)."""
    for cpi in R.iter("ClipProjectItem"):
        if cpi.get("ObjectUID") == cpi_uid:
            x = cpi.find("./ProjectItem/Node/ID")
            if x is None:
                x = next(cpi.iter("ID"), None)
            return f"{int(x.text):08x}" if x is not None and (x.text or "").isdigit() else None
    return None


def plano(R: ET.Element, faltando: list[str], arquivos: list[str]) -> tuple[str, list[str]]:
    """(o plano do `cicloMontar`, o que não deu para montar com o porquê). `arquivos`: os da timeline (os primeiros
    servem de mídia: a sequência nasce do formato do 1º clipe de IMAGEM — taxa e quadro iguais aos da timeline)."""
    midia = _ep.midia_do_projeto(R)
    nao: list[str] = []
    video = mono = None
    for a in arquivos:
        info = midia.get(_ep._norm(a)) or {}
        if video is None and info.get("video_clip") and info.get("cpi"):
            video = _no(R, info["cpi"])
        if mono is None and not info.get("video_clip"):
            for mc_uid, _ac, _k, canais in info.get("audio") or []:
                if canais == 1:
                    cpi = next((c.get("ObjectUID") for c in R.iter("ClipProjectItem")
                                if (c.find(".//MasterClip") is not None
                                    and c.find(".//MasterClip").get("ObjectURef") == mc_uid)), None)
                    mono = _no(R, cpi) if cpi else None
                    break
    if video is None:
        raise _ep.CartaErro("nenhum arquivo de imagem da timeline está no projeto: não há como fazer a sequência-molde")
    # ⛔ A receita da transição é a da bancada (2026-11-14): planos de 2 s com SOBRA dos dois lados na fonte e 20 quadros
    #   centrados no corte. Com planos de 1 s a partir do início da fonte o Premiere fez a transição de UM lado só
    #   (`HasOutgoingClip` false) — que não serve de molde para o corte entre dois planos (medido no 26.0.2 Mac).
    L = [f"seq\t{NOME_DOS_MOLDES}\t{BIN_DOS_MOLDES}", f"p\t{video}\t1\t3\t0\t1\t0"]
    if "transicao_V" in faltando:
        L += [f"p\t{video}\t5\t7\t2\t1\t0", "tr\t1\t0\t2\t20\t0.5\tini"]
    if "esticar" in faltando:
        # o molde do STRETCH (2026-11-20): um plano de imagem em 10 s com a escala NÃO uniforme (os valores não importam:
        # a escrita põe os da mídia; o que se copia é o Motion com o Uniform Scale desligado)
        L += [f"p\t{video}\t1\t3\t10\t1\t0", "esc\t1\t0\t10\t93.75\t100"]
    if "cor" in faltando:
        # o molde da COR do Avid (2026-11-20): um plano de imagem em 14 s com ProcAmp → Lumetri (os valores não importam:
        # a escrita põe a Saturation e a curva de cada clipe; o que se copia são os dois componentes, nessa ordem)
        L += [f"p	{video}	1	3	14	1	0", "cor	1	0	14"]
    precisa_mono = [f for f in ("som", "ganho", "transicao_A") if f in faltando]
    if precisa_mono and mono is None:
        nao += [f"{f}: nenhum som MONO da timeline está no projeto" for f in precisa_mono]
    elif precisa_mono:
        L += [f"p\t{mono}\t1\t3\t0\t0\t0"]
        if "transicao_A" in faltando:
            L += [f"p\t{mono}\t5\t7\t2\t0\t0", "tr\t0\t0\t2\t20\t0.5\tini"]
        if "ganho" in faltando:
            L += [f"p\t{mono}\t8\t9\t5\t0\t0\t{_ep.nivel_do_volume(GANHO_DO_MOLDE_DB)}"]
    if "merged" in faltando:
        nao.append("merged: o Premiere não faz merged pela API (os sincronizados vão pela mídia nativa)")
    return "\n".join(L), nao
