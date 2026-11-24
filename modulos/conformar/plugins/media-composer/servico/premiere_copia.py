"""PREMIERE → PREMIERE pela ponte (organograma aprovado pelo autor em 2026-10-22).

O `/receber/preparar` com `destino: "premiere"` e um `.prproj` grava a CÓPIA relinkada (`sessao_receber.
_copia_para_premiere`) e guarda o plano. Aqui:

1. `executar` — a ponte importa a sequência da cópia no projeto ABERTO (bin De Lá Pra Cá › <nome da cópia>), corrige a
   escala do arquivo de outro raster e devolve cada clipe novo com o caminho. ⭐ A CONFERÊNCIA DOS CAMINHOS: cada clipe
   contra a decisão do casamento — o `importSequences` do 26 religa sozinho, calado (banco, api-extendscript.md,
   2026-10-22: 21 sons que a cópia deixava num disco inexistente entraram religados). O que o Premiere ligou por conta
   própria vira "religado pelo Premiere: conferir", com marcador (o empate é do editor).
2. `conferir_*` — a conferência pela referência com o mesmo contrato da casca do Resolve (`conferirInicio`,
   `conferirQuadros`, `conferirFim`): o painel conduz em lotes, o Premiere exporta PNG, o serviço o converte no JPEG
   que a conferência espera.

Mac `pendente`: nada aqui depende do sistema além do caminho (o `getMediaPath` do Mac usa "/"), mas não foi medido.
"""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path

import premiere_ponte

log = logging.getLogger("delapraca.premiere_copia")

DADO_RELINK = "dlpc-relink"
DADO_CONFERENCIA = "dlpc-conferencia"
#: o PNG do `exportFramePNG` chega DEPOIS da chamada (23.2: 7 quadros em 0,5 s; 26.5.2: 144 em 82 s pela ponte livre)
ESPERA_QUADRO_S = 60.0

_CONF: dict = {}


def _norm(caminho: str) -> str:
    """O mesmo `dlpcNorm` do host: barras do Windows e caixa baixa (o Windows não distingue a caixa)."""
    return str(caminho or "").replace("/", "\\").lower()


def executar(plano: dict) -> dict:
    t0 = time.monotonic()
    r = premiere_ponte.chamar("dlpcImportarCopia", {
        "copia": plano["copia"], "seq": plano["seq"], "original": plano["original"], "nome": plano["nome"],
        "bin": plano["bin"], "escalas": {_norm(k): v for k, v in (plano.get("escalas") or {}).items()}}, prazo=900)
    if not isinstance(r, dict) or r.get("erro") or not r.get("ok"):
        return {"ok": False, "erro": (r or {}).get("erro") if isinstance(r, dict) else "a ponte não respondeu"}
    plano["seq_id"] = r["id"]                   # a conferência acha o plano (a taxa) pela sequência criada
    alvos = {_norm(v) for v in (plano.get("decidido") or {}).values()}
    itens = [x for x in r.get("itens") or [] if x.get("caminho")]      # sem caminho: gráfico, ajuste, cor sólida
    offline = [x for x in itens if x.get("offline")]
    religados = [x for x in itens if not x.get("offline") and _norm(x["caminho"]) not in alvos]
    marcas = list(plano.get("marcas") or [])
    onde = plano.get("onde") or {}
    for x in religados:
        lugar = onde.get(os.path.basename(x["caminho"].replace("\\", "/")).lower()) \
            or onde.get(os.path.basename(str(x.get("nome") or "")).lower())
        if lugar:
            marcas.append({**lugar, "nome": "Religado pelo Premiere",
                           "nota": f"o Premiere ligou {x['caminho']} por conta própria: conferir"})
    cor = {"Arquivo não encontrado": "Red", "Sem original": "Red", "Escala a conferir": "Yellow",
           "Religado pelo Premiere": "Yellow"}
    marcados = 0
    if marcas:
        m = premiere_ponte.chamar("dlpcMarcar", {
            "id": r["id"], "dado": DADO_RELINK,
            "marcas": [{"t": str(x["t"]), "nome": x["nome"],
                        "nota": f'{x.get("trilha", "")} · {x.get("plano", "")} · {x.get("nota", "")}',
                        "cor": cor.get(x["nome"], "Yellow")} for x in marcas[:2000]]}, prazo=120)
        marcados = (m or {}).get("marcadores") or 0
    no_lugar = len(itens) - len(offline) - len(religados)
    log.info("Premiere → Premiere: “%s” em %.1f s — %d clipes, %d nos arquivos decididos, %d religados pelo Premiere, "
             "%d offline, %d com escala, %d marcadores", r.get("sequencia"), time.monotonic() - t0, len(itens),
             no_lugar, len(religados), len(offline), r.get("escalas") or 0, marcados)
    return {"ok": True, "id": r["id"], "sequencia": r.get("sequencia"), "bin": f'{plano["bin"]} › {plano["nome"]}',
            "sequencias": r.get("novas") or 0, "clipes": len(itens), "no_lugar": no_lugar,
            "religados_pelo_premiere": [x["caminho"] for x in religados], "offline": [x["nome"] for x in offline],
            "religados_no_lugar": r.get("religados_no_lugar") or 0, "escalas": r.get("escalas") or 0,
            "marcadores": marcados, "segundos": round(time.monotonic() - t0, 1)}


# ── a conferência pela referência (o mesmo contrato da casca do Resolve) ─────────────────────────────────────────

def conferir_inicio(pedido: dict, planos=None) -> dict:
    """`planos` = os planos de cópia da sessão (`SessaoReceber._relinks`): a taxa (ticks por quadro) vem deles."""
    sid = str((pedido or {}).get("uid") or "")
    if not sid:
        return {"ok": False, "erro": "a sequência da cópia não foi informada"}
    r = premiere_ponte.chamar("dlpcConfInicio", sid, prazo=60)
    if not isinstance(r, dict) or r.get("erro"):
        return {"ok": False, "erro": (r or {}).get("erro") or "o Premiere não abriu a sequência"}
    plano = next((p for p in (planos or {}).values() if p.get("seq_id") == sid), None)
    _CONF.clear()
    _CONF.update({"id": sid, "tpf": (plano or {}).get("tpf") or 0, "nome": r.get("nome")})
    return {"ok": True, "nome": r.get("nome")}


def conferir_quadros(pedido: dict) -> dict:
    from PIL import Image

    from resolve_externo import _imagem_confiavel

    if not _CONF:
        return {"ok": False, "erro": "a conferência não foi iniciada"}
    tpf = int(_CONF.get("tpf") or 0)
    if not tpf:
        return {"ok": False, "erro": "não sei a taxa da sequência (prepare a cópia de novo)"}
    pontos, fora, pedir = (pedido or {}).get("pontos") or [], [], []
    for pt in pontos[:50]:
        if not isinstance(pt, dict) or not isinstance(pt.get("quadro"), int) or not _imagem_confiavel(pt.get("imagem")):
            fora.append({"quadro": pt.get("quadro") if isinstance(pt, dict) else None, "ok": False, "erro": "ponto recusado"})
            continue
        png = str(Path(pt["imagem"]).with_suffix(""))           # o Premiere acrescenta o ".png"
        try:
            os.remove(png + ".png")
        except OSError:
            pass
        pedir.append((pt, png))
    if pedir:
        r = premiere_ponte.chamar("dlpcExportarQuadros", {
            "id": _CONF["id"], "pontos": [{"t": str(pt["quadro"] * tpf), "arquivo": png} for pt, png in pedir]},
            prazo=300)
        if not isinstance(r, dict) or r.get("erro"):
            return {"ok": False, "erro": (r or {}).get("erro") or "o Premiere não exportou os quadros"}
    limite = time.monotonic() + ESPERA_QUADRO_S
    for pt, png in pedir:
        arq, anterior = png + ".png", -1
        while time.monotonic() < limite:
            tam = os.path.getsize(arq) if os.path.isfile(arq) else -1
            if tam > 0 and tam == anterior:                 # existe E parou de crescer
                break
            anterior = tam
            time.sleep(0.15)
        ok = False
        try:
            with Image.open(arq) as im:
                im.convert("RGB").save(pt["imagem"], quality=92)
            os.remove(arq)
            ok = True
        except OSError as e:
            log.info("quadro %s: %s", pt.get("quadro"), e)
        fora.append({"quadro": pt["quadro"], "ok": ok, "erro": "" if ok else "o Premiere não exportou o quadro"})
    return {"ok": True, "quadros": fora}


def conferir_fim(pedido: dict) -> dict:
    pedido = pedido or {}
    sid = _CONF.get("id")
    tpf = int(_CONF.get("tpf") or 0)
    _CONF.clear()
    if not sid or not tpf:
        return {"ok": True, "marcadores": 0}
    marcas = [m for m in pedido.get("marcas") or [] if isinstance(m, dict) and isinstance(m.get("quadro"), int)]
    r = premiere_ponte.chamar("dlpcMarcar", {
        "id": sid, "dado": DADO_CONFERENCIA,
        "marcas": [{"t": str(m["quadro"] * tpf), "nome": str(m.get("nome") or "DLPC")[:120],
                    "nota": str(m.get("nota") or "")[:500], "cor": str(pedido.get("cor") or "Purple")}
                   for m in marcas[:5000]]}, prazo=120)
    if not isinstance(r, dict) or r.get("erro"):
        return {"ok": False, "erro": (r or {}).get("erro") or "o Premiere não pôs os marcadores", "marcadores": 0}
    return {"ok": True, "marcadores": r.get("marcadores") or 0}


def _alterado_no_premiere(prproj: str) -> bool | None:
    """O Premiere tem mudança NÃO salva neste projeto? Pelo título da janela principal: `Adobe Premiere - <caminho> *`
    (medido no 26.5.2 Windows, 2026-10-22; o cabeçalho diz "- Edited"). ⚠️ O 26 já marca o projeto como alterado AO ABRIR
    um projeto com mídia offline — o aviso é de cautela, não prova de mudança na sequência. Fora do Windows: None
    (Mac `pendente`)."""
    import sys

    if sys.platform != "win32" or not prproj:
        return None
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    achados: list[str] = []
    nome = os.path.basename(prproj).lower()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cada(h, _l):
        n = u.GetWindowTextLengthW(h)
        if n and u.IsWindowVisible(h):
            b = ctypes.create_unicode_buffer(n + 1)
            u.GetWindowTextW(h, b, n + 1)
            t = b.value
            if t.lower().startswith("adobe premiere") and nome in t.lower():
                achados.append(t)
        return True

    u.EnumWindows(cada, 0)
    if not achados:
        return None
    return any(t.rstrip().endswith("*") for t in achados)


def sequencia_ativa() -> dict:
    """O projeto e a sequência ativa do Premiere, e quando o projeto foi SALVO (o app lê o arquivo, não a memória)."""
    r = premiere_ponte.chamar("dlpcSequenciaAtiva", prazo=15)
    if not isinstance(r, dict) or r.get("erro"):
        return {"ok": False, "erro": (r or {}).get("erro") or "o Premiere não respondeu"}
    prproj = r.get("projeto") or ""
    salvo = os.path.getmtime(prproj) if os.path.isfile(prproj) else None
    return {"ok": True, "prproj": prproj, "id": r.get("id"), "nome": r.get("nome"),
            "existe": os.path.isfile(prproj), "salvo": salvo, "alterado": _alterado_no_premiere(prproj)}
