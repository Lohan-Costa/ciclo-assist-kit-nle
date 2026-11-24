"""Pranchas do app standalone — o banco de mídia (spec docs/spec/2026-09-14-app-banco-de-midia.md).

Tema claro copiado do MSYNC (`MSYNC/frontend/src/style.css` + `tailwind.config.js`): fundos
#ffffff/#f5f5f3/#ececea, texto #1f2023/#56585c/#9a9c9f, bordas 0,5 px, destaque #378add, 13 px na
fonte do sistema, ícones Tabler (os SVG do próprio node_modules do MSYNC) ao lado do texto.

Telas ESTÁTICAS (decisão do editor). Dados de exemplo: produções, nomes e números são inventados.
Rodar: python3 gerar.py  → escreve os .dc.html e o canvas.json nesta pasta.
"""
import json
import re
from pathlib import Path

DEST = Path(__file__).resolve().parent
ICONES = DEST.parents[3] / "MSYNC" / "frontend" / "node_modules" / "@tabler" / "icons" / "icons" / "outline"

W, H = 1440, 900
MONO = 'ui-monospace, SFMono-Regular, Menlo, monospace'

_cache = {}


def ico(nome, tam=14, cor=None, filled=False):
    """Um ícone Tabler inline, no tamanho e na cor pedidos (currentColor por padrão)."""
    if nome not in _cache:
        svg = (ICONES / f"{nome}.svg").read_text()
        corpo = re.search(r">(.*)</svg>", svg, re.S).group(1)
        corpo = re.sub(r'<path stroke="none" d="M0 0h24v24H0z" fill="none" />', "", corpo)
        _cache[nome] = " ".join(corpo.split())
    estilo = f' style="color:{cor};flex:none"' if cor else ' style="flex:none"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{tam}" height="{tam}" viewBox="0 0 24 24" '
            f'fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round"{estilo}>{_cache[nome]}</svg>')


CSS = """
body { margin: 0; background: #ececea; }
a { color: #185fa5; } a:hover { color: #378add; }
.win { width: 1440px; height: 900px; display: flex; flex-direction: column; overflow: hidden;
  background: #ffffff; color: #1f2023; -webkit-font-smoothing: antialiased;
  font: 13px/1.4 -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif; }
.mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
.trunc { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; min-width: 0; }
.titlebar { flex: none; height: 40px; background: #f5f5f3; border-bottom: 0.5px solid #e6e6e3;
  display: flex; align-items: center; gap: 10px; padding: 0 12px; }
.lights { display: flex; gap: 8px; margin-right: 8px; }
.lights i { width: 12px; height: 12px; border-radius: 50%; display: block; }
.brand { display: flex; align-items: center; gap: 6px; font-size: 12px; font-weight: 500; color: #56585c; }
.tbtn { display: inline-flex; align-items: center; gap: 4px; border: 0.5px solid #d2d2cd; border-radius: 6px;
  padding: 4px 8px; font-size: 11px; color: #56585c; white-space: nowrap; background: transparent; }
.tbtn.confirm { border-color: #bfe3d4; color: #0f6e56; }
.tbtn.danger { border-color: #f0c6c6; color: #a32d2d; }
.tbtn.accent { border-color: #378add; color: #185fa5; background: #e8f0fb; }
.tbtn.off { color: #9a9c9f; border-style: dashed; }
.pill { display: inline-flex; align-items: center; gap: 3px; font-size: 10px; padding: 1px 6px;
  border-radius: 10px; white-space: nowrap; }
.p-ok { background: #e1f5ee; color: #0f6e56; }
.p-warn { background: #faeeda; color: #854f0b; }
.p-info { background: #e6f1fb; color: #185fa5; }
.p-bad { background: #fcebeb; color: #a32d2d; }
.p-local { background: #ececea; color: #56585c; }
.label { font-size: 10px; font-weight: 600; color: #9a9c9f; letter-spacing: 0.05em; text-transform: uppercase; }
.sub { font-size: 10px; color: #9a9c9f; }
.body { flex: 1; display: flex; min-height: 0; }
.rail { width: 64px; flex: none; background: #f5f5f3; border-right: 0.5px solid #e6e6e3;
  display: flex; flex-direction: column; gap: 2px; padding: 8px 6px; }
.nav { display: flex; flex-direction: column; align-items: center; gap: 3px; padding: 7px 2px 6px;
  border-radius: 6px; color: #56585c; font-size: 10px; }
.nav.active { background: #ffffff; color: #1f2023; font-weight: 500; }
.chat { width: 360px; flex: none; border-right: 0.5px solid #e6e6e3; display: flex; flex-direction: column; }
.phead { flex: none; display: flex; align-items: center; gap: 8px; padding: 8px 12px;
  border-bottom: 0.5px solid #e6e6e3; min-height: 25px; }
.ptitle { font-size: 13px; font-weight: 500; color: #1f2023; }
.msgs { flex: 1; overflow: hidden; padding: 14px; display: flex; flex-direction: column; gap: 14px; }
.me { align-self: flex-end; max-width: 86%; background: #f5f5f3; border: 0.5px solid #e6e6e3;
  border-radius: 10px; padding: 7px 10px; line-height: 1.45; }
.ai { line-height: 1.5; display: flex; flex-direction: column; gap: 8px; }
.ai p { margin: 0; }
.mcard { display: flex; gap: 8px; align-items: center; padding: 6px; border: 0.5px solid #e6e6e3; border-radius: 6px; }
.mthumb { width: 64px; height: 36px; border-radius: 3px; flex: none; position: relative; }
.compose { flex: none; padding: 10px 12px 12px; border-top: 0.5px solid #e6e6e3; }
.cbox { border: 0.5px solid #d2d2cd; border-radius: 10px; padding: 8px 10px; display: flex; flex-direction: column; gap: 8px; }
.send { width: 26px; height: 26px; border-radius: 6px; background: #378add; color: #ffffff;
  display: flex; align-items: center; justify-content: center; }
.center { flex: 1; min-width: 0; display: flex; flex-direction: column; }
.toolbar { flex: none; display: flex; align-items: center; gap: 8px; padding: 8px 12px; border-bottom: 0.5px solid #e6e6e3; }
.crumb { font-size: 13px; font-weight: 500; flex: 1; display: flex; align-items: center; gap: 6px; min-width: 0; white-space: nowrap; }
.crumb span.c { color: #9a9c9f; font-weight: 400; }
.search { display: flex; align-items: center; gap: 6px; border: 0.5px solid #d2d2cd; border-radius: 6px;
  padding: 4px 8px; width: 320px; color: #9a9c9f; font-size: 12px; }
.search.foco { border-color: #378add; color: #1f2023; }
.seg { display: flex; border: 0.5px solid #d2d2cd; border-radius: 6px; overflow: hidden; }
.seg span { padding: 4px 7px; color: #9a9c9f; display: flex; align-items: center; gap: 4px; font-size: 11px; }
.seg span.on { background: #f5f5f3; color: #1f2023; }
.seg span + span { border-left: 0.5px solid #d2d2cd; }
.filters { flex: none; display: flex; flex-wrap: wrap; row-gap: 6px; gap: 6px; align-items: center; padding: 7px 12px; border-bottom: 0.5px solid #e6e6e3; }
.fchip { display: inline-flex; gap: 4px; align-items: center; border: 0.5px solid #d2d2cd; border-radius: 10px;
  padding: 2px 8px; font-size: 11px; color: #56585c; white-space: nowrap; }
.fchip.on { background: #e8f0fb; border-color: #378add; color: #185fa5; }
.cover { flex: none; display: flex; gap: 14px; white-space: nowrap; align-items: center; padding: 6px 12px; background: #f5f5f3;
  border-bottom: 0.5px solid #e6e6e3; font-size: 11px; color: #56585c; }
.cover .it { display: flex; align-items: center; gap: 6px; }
.bar { width: 40px; height: 3px; background: #e6e6e3; border-radius: 2px; overflow: hidden; }
.bar i { display: block; height: 100%; background: #2d9d57; }
.grid { flex: 1; overflow: hidden; padding: 12px; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px; align-content: start; grid-auto-rows: max-content; }
.card { border: 0.5px solid #e6e6e3; border-radius: 6px; overflow: hidden; background: #ffffff; }
.card.sel { border-color: #378add; box-shadow: 0 0 0 1px #378add; }
.thumb { position: relative; aspect-ratio: 16 / 9; }
.tc { position: absolute; right: 4px; bottom: 4px; font: 10px ui-monospace, SFMono-Regular, Menlo, monospace;
  color: #ffffff; background: rgba(0, 0, 0, 0.55); padding: 0 4px; border-radius: 3px; }
.tl { position: absolute; left: 4px; top: 4px; display: flex; gap: 3px; }
.cbody { padding: 6px 8px 8px; display: flex; flex-direction: column; gap: 4px; }
.cname { font-size: 12px; font-weight: 500; }
.row { display: flex; align-items: center; gap: 6px; min-width: 0; }
.stages { display: flex; gap: 6px; color: #d2d2cd; margin-left: auto; }
.stages .ok { color: #2d9d57; }
.insp { width: 320px; flex: none; border-left: 0.5px solid #e6e6e3; display: flex; flex-direction: column; overflow: hidden; }
.sec { padding: 10px 12px; border-bottom: 0.5px solid #e6e6e3; display: flex; flex-direction: column; gap: 7px; }
.kv { display: grid; grid-template-columns: 92px minmax(0, 1fr); gap: 4px 8px; font-size: 11px; margin: 0; }
.kv dt { color: #9a9c9f; } .kv dd { margin: 0; color: #1f2023; }
.tag { display: inline-flex; align-items: center; gap: 4px; border: 0.5px solid #d2d2cd; border-radius: 10px;
  padding: 1px 7px; font-size: 11px; color: #1f2023; background: #ffffff; }
.tag.inf { border-style: dashed; color: #56585c; }
.foot { flex: none; height: 24px; border-top: 0.5px solid #e6e6e3; background: #f5f5f3; font-size: 10px;
  color: #56585c; display: flex; align-items: center; gap: 16px; padding: 0 12px; }
.foot .it { display: flex; align-items: center; gap: 5px; }
.dot { width: 6px; height: 6px; border-radius: 50%; flex: none; }
.tblwrap { flex: 1; overflow: hidden; }
table.tbl { width: 100%; border-collapse: collapse; font-size: 11px; }
.tbl th { text-align: left; font-weight: 500; color: #56585c; background: #f5f5f3; padding: 6px 8px;
  border-bottom: 0.5px solid #e6e6e3; white-space: nowrap; }
.tbl td { padding: 6px 8px; border-bottom: 0.5px solid #e6e6e3; white-space: nowrap; color: #1f2023; }
.tbl tr.sel td { background: #e8f0fb; }
.tbl td.m { color: #56585c; }
.page { flex: 1; overflow: hidden; padding: 16px 20px; display: flex; flex-direction: column; gap: 14px; }
.box { border: 0.5px solid #e6e6e3; border-radius: 10px; background: #ffffff; }
.boxh { display: flex; align-items: center; gap: 8px; padding: 9px 12px; border-bottom: 0.5px solid #e6e6e3; }
.h2 { font-size: 15px; font-weight: 600; margin: 0; }
.p { font-size: 12px; color: #56585c; margin: 0; line-height: 1.5; }
.check { color: #2d9d57; } .miss { color: #a32d2d; } .na { color: #9a9c9f; }
.prog { height: 3px; background: #e6e6e3; border-radius: 2px; overflow: hidden; }
.prog i { display: block; height: 100%; background: #2d9d57; }
.hl { background: #faeeda; color: #854f0b; border-radius: 2px; padding: 0 2px; }

.tree { width: 248px; flex: none; background: #f5f5f3; border-right: 0.5px solid #e6e6e3; display: flex; flex-direction: column; overflow: hidden; }
.trow { display: flex; align-items: center; gap: 4px; padding: 3px 4px; border-radius: 6px; font-size: 12px; color: #1f2023; white-space: nowrap; }
.trow.sel { background: #e8f0fb; }
.trow .n { flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
.trow .q { font-size: 10px; color: #9a9c9f; }
.kbd { font: 10px ui-monospace, SFMono-Regular, Menlo, monospace; border: 0.5px solid #d2d2cd; border-radius: 3px; padding: 0 4px; color: #56585c; background: #ffffff; }
.tcbox { display: flex; flex-direction: column; gap: 1px; padding: 3px 8px; border: 0.5px solid #e6e6e3; border-radius: 6px; background: #ffffff; }
.tcbox b { font: 500 11px ui-monospace, SFMono-Regular, Menlo, monospace; color: #1f2023; }
.tl-track { position: relative; height: 46px; border-bottom: 0.5px solid #e6e6e3; }
.tl-clip { position: absolute; top: 4px; bottom: 4px; border-radius: 4px; overflow: hidden; display: flex; flex-direction: column; justify-content: flex-end; }
.tl-head { width: 56px; flex: none; display: flex; align-items: center; justify-content: center; font: 500 10px ui-monospace, SFMono-Regular, Menlo, monospace; color: #56585c; border-right: 0.5px solid #e6e6e3; background: #f5f5f3; }
.switch { width: 26px; height: 15px; border-radius: 8px; background: #d2d2cd; position: relative; flex: none; }
.switch i { position: absolute; top: 2px; left: 2px; width: 11px; height: 11px; border-radius: 50%; background: #ffffff; }
.switch.on { background: #378add; } .switch.on i { left: 13px; }
"""

TONS = ["#3b3f45", "#5b5347", "#2f3a36", "#6a5a4a", "#394252", "#4e4a5a", "#2c3033", "#5f6a60",
        "#46403a", "#384048", "#6b6258", "#303a44"]


def tom(i):
    t = TONS[i % len(TONS)]
    return f"background: linear-gradient(180deg, {t} 0%, #1f2023 140%);"


def doc(corpo):
    return ('<!doctype html>\n<html>\n<head>\n  <meta charset="utf-8">\n  <script src="./support.js"></script>\n'
            '</head>\n<body>\n<x-dc>\n<helmet>\n  <style>' + CSS + '</style>\n</helmet>\n'
            + corpo + '\n</x-dc>\n</body>\n</html>\n')


# ---------------------------------------------------------------- moldura

RAIL = [("midias", "movie", "Mídias"), ("entidades", "masks-theater", "Entidades"),
        ("ingestao", "folder-down", "Ingestão"), ("reconectar", "plug-connected", "Reconectar"),
        ("bancos", "database", "Bancos")]


def titlebar(banco="Acervo Ciclo", tipo="remoto"):
    pill = '<span class="pill p-info">' + ico("network", 10) + ' remoto · NAS</span>' if tipo == "remoto" else \
        '<span class="pill p-local">' + ico("folder", 10) + ' local</span>'
    return f"""
<div class="titlebar">
  <div class="lights"><i style="background:#ff5f57"></i><i style="background:#febc2e"></i><i style="background:#28c840"></i></div>
  <span class="tbtn" style="color:#1f2023">{ico("database", 12)} {banco} {ico("chevron-down", 12, "#9a9c9f")}</span>
  {pill}
  <div style="flex:1"></div>
  <span class="brand">{ico("movie", 13)} Ciclo Assist</span>
  <div style="flex:1"></div>
  <span class="sub" style="display:flex;align-items:center;gap:5px">{ico("cpu", 12)} processando 3 · Mac mini</span>
  <span style="width:22px;height:22px;border-radius:50%;background:#e1f5ee;color:#0f6e56;font-size:9px;font-weight:600;display:flex;align-items:center;justify-content:center">LC</span>
</div>"""


def rail(ativo):
    itens = "".join(
        f'<div class="nav{" active" if k == ativo else ""}">{ico(i, 16)}<span>{t}</span></div>' for k, i, t in RAIL)
    return f"""
<div class="rail">{itens}<div style="flex:1"></div><div class="nav">{ico("settings", 16)}<span>Ajustes</span></div></div>"""


def chat(mensagens, rascunho="Pergunte sobre o banco, ou peça uma seleção…"):
    return f"""
<div class="chat">
  <div class="phead">{ico("message", 14, "#56585c")}<span class="ptitle">Conversa</span>
    <span class="pill p-local">Claude · Sonnet 5</span><div style="flex:1"></div>
    <span class="tbtn">{ico("plus", 12)} Nova</span></div>
  <div class="msgs">{mensagens}</div>
  <div class="compose"><div class="cbox">
    <div style="color:#9a9c9f;font-size:12px;min-height:34px">{rascunho}</div>
    <div class="row" style="color:#9a9c9f">{ico("paperclip", 14)}<span class="sub">arraste mídias, roteiros ou fotos</span>
      <div style="flex:1"></div><span class="send">{ico("arrow-up", 14)}</span></div>
  </div></div>
</div>"""


def rodape(extra=""):
    return f"""
<div class="foot">
  <span class="it">{ico("movie", 11)} 2.310 mídias · 2.140 h</span>
  <span class="it"><span class="dot" style="background:#a32d2d"></span> 214 offline</span>
  <span class="it">{ico("clock", 11)} fila: 3 tarefas</span>
  <span class="it"><span class="dot" style="background:#1d9e75"></span> Mac mini conectado</span>
  <span class="it">{ico("users", 11)} 4 pessoas neste banco</span>
  <div style="flex:1"></div>{extra}
  <span class="it">esta máquina: MacBook Pro · perfil leve</span>
</div>"""


def janela(ativo, conversa, centro, inspetor="", banco="Acervo Ciclo", tipo="remoto"):
    return (f'<div class="win">{titlebar(banco, tipo)}<div class="body">{rail(ativo)}{conversa}'
            f'<div class="center">{centro}</div>{inspetor}</div>{rodape()}</div>')


def ai(*paragrafos):
    return '<div class="ai">' + "".join(paragrafos) + "</div>"


def me(texto):
    return f'<div class="me">{texto}</div>'


def mcard(i, nome, tc, motivo):
    return f"""<div class="mcard"><div class="mthumb" style="{tom(i)}"></div>
  <div style="display:flex;flex-direction:column;gap:2px;min-width:0;flex:1">
    <span class="trunc" style="font-size:12px;font-weight:500">{nome}</span>
    <span class="row sub"><span class="mono">{tc}</span> · <span class="trunc">{motivo}</span></span></div></div>"""


PORTA_AVID = '<span class="pill p-info">' + ico("box", 10) + ' Avid MediaFiles</span>'
PORTA_ARQ = '<span class="pill p-local">' + ico("file", 10) + ' arquivo</span>'


def estagios(fala, img, vet, dec):
    def e(nome, ok):
        return f'<span class="{"ok" if ok else ""}">{ico(nome, 12)}</span>'
    return f'<span class="stages">{e("wave-sine", fala)}{e("photo", img)}{e("vector-triangle", vet)}{e("file-description", dec)}</span>'


def card(i, nome, meta, porta, tc, est, sel=False, extra=""):
    return f"""<div class="card{" sel" if sel else ""}">
  <div class="thumb" style="{tom(i)}"><div class="tl">{extra}</div><span class="tc">{tc}</span></div>
  <div class="cbody"><span class="cname trunc">{nome}</span>
    <div class="row"><span class="sub trunc">{meta}</span></div>
    <div class="row">{porta}{estagios(*est)}</div></div></div>"""


# ---------------------------------------------------------------- a lista: árvore dentro da tabela (estrutura da lista do Premiere)

ROTULO = {"laranja": "#e8a33d", "roxo": "#b35ad6", "azul": "#5b8fd9", "verde": "#3fae7a", "": None}

#: (nível, tipo, nome, rótulo, aberta, colunas{...}, marcas)
#: tipo: pasta | video | audio | foto
ARVORE = [
    (0, "pasta", "Rio de Dentro", "laranja", True, {}, ""),
    (1, "pasta", "Entrevistas", "laranja", True, {"itens": "41"}, ""),
    (2, "video", "ENT_MARTA_01.mov", "azul", None, dict(dur="01:03:12:04", tc="09:02:44:10", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(1, 1, 1, 0), est="offline"), ""),
    (2, "video", "ENT_MARTA_02.mov", "azul", None, dict(dur="00:58:03:11", tc="09:40:03:00", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(1, 1, 1, 0), est="online"), ""),
    (2, "video", "ENT_MARTA_03.mov", "azul", None, dict(dur="01:12:40:11", tc="10:14:22:05", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(1, 1, 1, 1), est="online"), "sel"),
    (2, "video", "ENT_MARTA_04.mov", "azul", None, dict(dur="00:49:20:02", tc="10:02:10:00", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(0, 1, 0, 0), est="online"), ""),
    (2, "video", "ENT_JOAO_BARQUEIRO_01.braw", "azul", None, dict(dur="00:47:30:00", tc="11:02:00:00", fmt="BRAW · 6K", porta="arq", an=(0, 0, 0, 0), est="online"), ""),
    (2, "video", "ENT_SEU_LUIS_01.mov", "", None, dict(dur="00:22:14:08", tc="14:20:00:00", fmt="H.264 · 1920×1080", porta="arq", an=(1, 1, 1, 0), est="online"), ""),
    (1, "pasta", "Material de arquivo", "laranja", False, {"itens": "58"}, ""),
    (1, "pasta", "Imagens de apoio", "laranja", False, {"itens": "120"}, ""),
    (0, "pasta", "Brutos D12", "laranja", True, {}, ""),
    (1, "pasta", "CAM_A", "laranja", True, {"itens": "38"}, ""),
    (2, "video", "A012C003.braw", "roxo", None, dict(dur="00:04:31:14", tc="14:02:11:09", fmt="BRAW 8:1 · 6144×3456", porta="arq", an=(1, 1, 1, 0), est="online"), "fam"),
    (2, "video", "A012C003_proxy.mov", "roxo", None, dict(dur="00:04:31:14", tc="14:02:11:09", fmt="ProRes Proxy · 1920×1080", porta="arq", an=(1, 1, 1, 0), est="online"), "fam"),
    (2, "video", "A012C003", "roxo", None, dict(dur="00:04:31:14", tc="14:02:11:09", fmt="DNxHR LB · OP-Atom", porta="avid", an=(1, 1, 1, 0), est="online"), "fam"),
    (2, "video", "A012C004.braw", "azul", None, dict(dur="00:02:18:21", tc="14:08:40:21", fmt="BRAW 8:1 · 6144×3456", porta="arq", an=(1, 1, 1, 1), est="online"), ""),
    (1, "pasta", "CAM_B", "laranja", False, {"itens": "27"}, ""),
    (1, "pasta", "SOM", "laranja", True, {"itens": "22"}, ""),
    (2, "audio", "D12_T003.wav", "verde", None, dict(dur="00:05:02:07", tc="14:01:52:14", fmt="PCM · 8 canais · 48 kHz", porta="arq", an=(1, 0, 0, 0), est="online"), ""),
    (2, "audio", "D12_T004.wav", "verde", None, dict(dur="00:03:59:13", tc="14:08:31:02", fmt="PCM · 8 canais · 48 kHz", porta="arq", an=(1, 0, 0, 0), est="online"), ""),
    (0, "pasta", "Produção Exemplo", "laranja", False, {"itens": "654"}, ""),
    (0, "pasta", "Sem pasta", "", False, {"itens": "1.244"}, ""),
]

#: (chave, título, largura)
COLUNAS = [("nome", "Nome", 244), ("dur", "Duração", 90), ("tc", "TC início", 90), ("an", "Análises", 82),
           ("est", "Estado", 72), ("fmt", "Formato", 176), ("porta", "Porta", 118)]


def rotulo(cor):
    c = ROTULO[cor]
    if not c:
        return '<span style="display:block;width:11px;height:11px;border-radius:3px;border:1px solid #d2d2cd"></span>'
    return f'<span style="display:block;width:11px;height:11px;border-radius:3px;background:{c}"></span>'


def cabecalho(ordem="nome", sentido="asc", colunas=COLUNAS, arrastando=None):
    cels = ['<div style="width:28px;flex:none;border-right:0.5px solid #e6e6e3;align-self:stretch"></div>']
    for chave, titulo, w in colunas:
        seta = ""
        if chave == ordem:
            seta = ico("arrow-up" if sentido == "asc" else "arrow-down", 11, "#1f2023")
        peso = "font-weight:600;color:#1f2023;" if chave == ordem else ""
        alca = ('<span style="position:absolute;right:-2px;top:3px;bottom:3px;width:3px;border-radius:2px;background:#378add"></span>'
                if chave == arrastando else "")
        cels.append(f'<div style="width:{w}px;flex:none;position:relative;display:flex;align-items:center;gap:4px;padding:0 8px;'
                    f'border-right:0.5px solid #e6e6e3;align-self:stretch;{peso}"><span class="trunc">{titulo}</span>{seta}{alca}</div>')
    return (f'<div style="display:flex;align-items:center;height:26px;background:#f5f5f3;border-bottom:0.5px solid #e6e6e3;'
            f'font-size:11px;color:#56585c;white-space:nowrap">{"".join(cels)}</div>')


def celula(chave, v, w):
    base = f'width:{w}px;flex:none;padding:0 8px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;'
    if v is None:
        return f'<div style="{base}"></div>'
    if chave in ("dur", "tc"):
        return f'<div class="mono" style="{base}font-size:11px">{v}</div>'
    if chave == "porta":
        return f'<div style="{base}">{PORTA_AVID if v == "avid" else PORTA_ARQ}</div>'
    if chave == "an":
        return f'<div style="{base};display:flex;align-items:center">{estagios(*v).replace("margin-left: auto", "")}</div>'
    if chave == "est":
        pill = '<span class="pill p-ok">online</span>' if v == "online" else '<span class="pill p-bad">offline</span>'
        return f'<div style="{base}">{pill}</div>'
    return f'<div style="{base};color:#56585c;font-size:11px">{v}</div>'


def linha(nivel, tipo, nome, cor, aberta, dados, marca, colunas=COLUNAS, destaque=None):
    sel = marca == "sel"
    fundo = "background:#e8f0fb;" if sel else (destaque or "")
    seta = (ico("chevron-down" if aberta else "chevron-right", 12, "#9a9c9f") if tipo == "pasta"
            else '<span style="width:12px;flex:none"></span>')
    icone = {"pasta": ico("folder", 14, "#56585c"), "video": ico("movie", 14, "#56585c"),
             "audio": ico("wave-sine", 14, "#56585c"), "foto": ico("photo", 14, "#56585c")}[tipo]
    peso = "font-weight:500;" if tipo == "pasta" else ""
    tinta = "color:#9a9c9f;" if dados.get("est") == "offline" else ""
    extra = ""
    if marca == "fam":
        extra = f'<span title="família" style="color:#9a9c9f;display:flex">{ico("versions", 11)}</span>'
    if tipo == "pasta" and dados.get("itens"):
        extra = f'<span class="sub">{dados["itens"]}</span>'
    nome_w = colunas[0][2]
    cels = [f'<div style="width:28px;flex:none;display:flex;justify-content:center">{rotulo(cor)}</div>',
            f'<div style="width:{nome_w}px;flex:none;display:flex;align-items:center;gap:4px;padding:0 8px 0 {4 + nivel * 16}px;overflow:hidden">'
            f'{seta}{icone}<span class="trunc" style="font-size:12px;{peso}{tinta}">{nome}</span>{extra}</div>']
    for chave, _, w in colunas[1:]:
        cels.append(celula(chave, dados.get(chave), w))
    return f'<div style="display:flex;align-items:center;height:26px;border-bottom:0.5px solid #f0f0ee;{fundo}">{"".join(cels)}</div>'


def buscas(filtro="", inteligente="", n_itens="2.310 itens", ativa=None):
    f_txt = f'<span style="color:#1f2023">{filtro}</span>' if filtro else '<span>Filtrar por nome, pasta, formato, TC…</span>'
    i_txt = f'<span style="color:#1f2023">{inteligente}</span>' if inteligente else '<span class="trunc">Descreva o que procura: “Personagem E falando da enchente”, “close noturno no cais”…</span>'
    borda_i = "border-color:#378add;box-shadow:0 0 0 2px #e8f0fb;" if ativa == "inteligente" else ""
    return f"""
<div style="flex:none;display:flex;flex-direction:column;gap:8px;padding:10px 12px;border-bottom:0.5px solid #e6e6e3">
  <div class="row" style="gap:8px">
    <div class="search" style="width:300px">{ico("filter", 13)}{f_txt}</div>
    <div style="flex:1"></div>
    <span class="sub">{n_itens}</span>
    <span class="tbtn">{ico("columns-3", 12)} Colunas</span>
  </div>
  <div class="row" style="gap:8px;border:0.5px solid #d2d2cd;border-radius:6px;padding:5px 8px;{borda_i}">
    {ico("text-scan-2", 14, "#185fa5")}<span class="label" style="color:#185fa5;white-space:nowrap">Busca inteligente</span>
    <span style="width:0.5px;align-self:stretch;background:#e6e6e3"></span>
    <div style="flex:1;min-width:0;font-size:12px;color:#9a9c9f;display:flex">{i_txt}</div>
    {'<span class="tbtn" style="padding:2px 6px">' + ico("x", 11) + ' limpar</span>' if inteligente else '<span class="kbd">↵</span>'}
  </div>
</div>"""


def rolagem(horizontal_frac=0.78):
    return (f'<div style="flex:none;height:10px;display:flex;align-items:center;padding:0 12px 0 40px">'
            f'<div style="height:6px;width:{horizontal_frac * 100:.0f}%;border-radius:4px;background:#d2d2cd"></div></div>')


def lista(linhas_html, ordem="nome", sentido="asc", arrastando=None):
    return (f'<div style="flex:1;min-height:0;display:flex;flex-direction:column;overflow:hidden">'
            f'<div style="flex:1;min-height:0;overflow:hidden;position:relative">{cabecalho(ordem, sentido, arrastando=arrastando)}{linhas_html}'
            f'<div style="position:absolute;right:2px;top:30px;width:6px;height:38%;border-radius:4px;background:#d2d2cd"></div></div>'
            f'{rolagem()}</div>')


def inspetor_midia():
    return f"""
<div class="insp">
  <div class="phead">{ico("info-circle", 14, "#56585c")}<span class="ptitle">ENT_MARTA_03.mov</span></div>
  <div class="sec" style="padding-top:12px">
    <div class="thumb" style="{tom(1)};border-radius:6px"><span class="tc">10:14:22:05</span></div>
    <div class="row">{PORTA_ARQ}<span class="pill p-ok">{ico("check", 10)} online</span><span class="pill p-local">entrevista</span></div>
  </div>
  <div class="sec"><span class="label">Arquivo</span>
    <dl class="kv"><dt>Duração</dt><dd class="mono">01:12:40:11</dd><dt>TC início</dt><dd class="mono">10:14:22:05</dd>
      <dt>Formato</dt><dd>ProRes 422 HQ · 3840×2160 · 23,976</dd><dt>Som</dt><dd>2 pistas · 48 kHz</dd>
      <dt>Onde está</dt><dd class="trunc">NAS-PRODUCAO › Rio de Dentro › Entrevistas</dd></dl></div>
  <div class="sec"><span class="label">Análises</span>
    <dl class="kv"><dt>{ico("wave-sine", 11)} Fala</dt><dd><span class="check">pronta</span> · 612 falas</dd>
      <dt>{ico("photo", 11)} Imagem</dt><dd><span class="check">pronta</span> · 214 planos</dd>
      <dt>{ico("vector-triangle", 11)} Frase</dt><dd><span class="check">pronta</span> · Mac mini</dd>
      <dt>{ico("file-description", 11)} Decupagem</dt><dd>9 trechos · <a>decupar mais…</a></dd></dl></div>
  <div class="sec" style="border-bottom:none"><span class="label">Anotações</span>
    <div style="display:flex;flex-wrap:wrap;gap:5px">
      <span class="tag">{ico("user", 11)} Personagem E</span><span class="tag">{ico("map-pin", 11)} Cais do porto</span>
      <span class="tag">{ico("tag", 11)} enchente de 1987</span><span class="tag inf">{ico("tag", 11)} barqueiros · inferido</span>
    </div><span class="tbtn" style="align-self:flex-start">{ico("plus", 12)} Anotar</span></div>
</div>"""


def tela_main():
    linhas = "".join(linha(*r) for r in ARVORE)
    centro = buscas() + lista(linhas, arrastando="dur")
    chip = f'<span class="tag" style="border-color:#378add;background:#e8f0fb;color:#185fa5">{ico("folder", 11)} Entrevistas · 41 {ico("x", 11)}</span>'
    conversa = chat(
        me(chip + "<div style='margin-top:6px'>quais trechos falam da enchente de 87?</div>")
        + ai("<p>Nas <b>41 entrevistas</b> desta pasta: <b>6 momentos</b> em 3 delas. Os três mais fortes:</p>",
             mcard(1, "ENT_MARTA_03", "10:31:04:12", "“a água chegou no segundo andar”"),
             mcard(3, "ENT_MARTA_02", "09:52:40:03", "“a gente perdeu o barco em 87”"),
             mcard(8, "ENT_JOAO_BARQUEIRO_01", "11:20:15:00", "fala de enchente"),
             '<p class="sub">Recorte: Rio de Dentro › Entrevistas (arrastada da lista) · 38 com fala transcrita, de 41.</p>',
             f'<div class="row"><span class="tbtn">{ico("list-check", 12)} Mostrar na lista</span><span class="tbtn">{ico("file-export", 12)} Levar ao NLE</span></div>'),
        rascunho="Arraste uma pasta da lista para procurar só nela…")
    return doc(janela("midias", conversa, centro, inspetor_midia()))


def tela_busca_inteligente():
    """A busca inteligente responde NA LISTA: a árvore filtra até as mídias que casam, e cada mídia abre os momentos."""
    def momento(tc, texto, motivo, forte=False):
        return (f'<div style="display:flex;align-items:center;height:26px;border-bottom:0.5px solid #f0f0ee;{"background:#e8f0fb;" if forte else ""}">'
                f'<div style="width:28px;flex:none"></div>'
                f'<div style="flex:1;min-width:0;display:flex;align-items:center;gap:8px;padding:0 8px 0 {4 + 3 * 16 + 12}px;font-size:11px">'
                f'<span class="mono" style="color:#185fa5;width:76px;flex:none">{tc}</span>'
                f'<span class="trunc" style="flex:1;color:#1f2023">{texto}</span>'
                f'<span class="pill p-local" style="flex:none">{motivo}</span></div></div>')

    L = []
    L.append(linha(0, "pasta", "Rio de Dentro", "laranja", True, {"itens": "3 de 412"}, ""))
    L.append(linha(1, "pasta", "Entrevistas", "laranja", True, {"itens": "3 de 41"}, ""))
    L.append(linha(2, "video", "ENT_MARTA_03.mov", "azul", True, dict(dur="01:12:40:11", tc="10:14:22:05", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(1, 1, 1, 1), est="online"), ""))
    L.append(momento("10:31:04:12", "“E a água chegou no segundo andar. No segundo andar!”", f'{ico("wave-sine", 10)} fala', True))
    L.append(momento("10:30:58:17", "“Meu pai amarrou o barco no poste, achando que segurava.”", f'{ico("wave-sine", 10)} fala'))
    L.append(momento("10:12:40:00", "Personagem E junto à janela, fotos da enchente na parede", f'{ico("file-description", 10)} decupagem'))
    L.append(linha(2, "video", "ENT_MARTA_02.mov", "azul", True, dict(dur="00:58:03:11", tc="09:40:03:00", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(1, 1, 1, 0), est="online"), ""))
    L.append(momento("09:52:40:03", "“A gente perdeu o barco em 87.”", f'{ico("wave-sine", 10)} fala'))
    L.append(momento("09:55:12:08", "“…chegou no segundo andar, e a gente em cima do telhado.”", f'{ico("wave-sine", 10)} fala'))
    L.append(linha(2, "video", "ENT_MARTA_01.mov", "azul", False, dict(dur="01:03:12:04", tc="09:02:44:10", fmt="ProRes 422 HQ · 3840×2160", porta="arq", an=(1, 1, 1, 0), est="offline"), ""))
    L.append(linha(0, "pasta", "Material de arquivo", "laranja", True, {"itens": "1 de 58"}, ""))
    L.append(linha(1, "video", "ARQ_TVE_1987_ENCHENTE.mp4", "", True, dict(dur="00:06:48:00", tc="00:00:00:00", fmt="H.264 · 720×480", porta="arq", an=(1, 1, 1, 0), est="online"), ""))
    # momentos da mídia de arquivo ficam no nível 2
    L.append(momento("00:02:10:00", "telhados submersos, barcos entre as casas", f'{ico("vector-triangle", 10)} busca por frase').replace(f"{4 + 3 * 16 + 12}px", f"{4 + 2 * 16 + 12}px"))
    linhas = "".join(L)
    # a linha de alcance, dentro da lista e acima do cabeçalho
    alcance = f"""
<div class="cover" style="gap:12px">
  <span style="font-size:11px;color:#1f2023"><b style="font-weight:600">4 mídias · 8 momentos</b></span>
  <span class="label">procurado em</span>
  <span class="it">{ico("wave-sine", 12)} fala 1.842</span><span class="it">{ico("photo", 12)} imagem 1.790</span>
  <span class="it">{ico("vector-triangle", 12)} frase 212</span><span class="it">{ico("file-description", 12)} decupadas 138</span>
  <div style="flex:1"></div><span class="sub">de 2.310</span>
</div>"""
    centro = buscas(inteligente="Personagem E falando da enchente", n_itens="4 de 2.310", ativa="inteligente") + alcance + lista(linhas, ordem="tc", sentido="asc")
    conversa = chat(
        me("quais entrevistas falta transcrever?")
        + ai("<p>Faltam <b>3 de 41</b>: <span class='mono'>ENT_JOAO_BARQUEIRO_01</span> (BRAW, na fila), <span class='mono'>ENT_MARTA_04</span> e <span class='mono'>ENT_SEU_LUIS_02</span>.</p>"))
    return doc(janela("midias", conversa, centro, inspetor_midia()))


def tela_cobertura():
    vazio = f"""
<div style="flex:1;display:flex;align-items:center;justify-content:center;padding:24px">
  <div style="width:520px;display:flex;flex-direction:column;gap:14px">
    <div class="row">{ico("text-scan-2", 18, "#9a9c9f")}<span class="h2">Nada parecido nas 212 mídias com busca por frase</span></div>
    <p class="p">Isso não quer dizer que o banco não tem esse plano: <b>2.098 mídias ainda não têm a busca por frase</b>. Nas outras camadas também não apareceu: nenhuma fala menciona barco no cais, e nenhuma das 138 decupagens descreve isso.</p>
    <div class="box" style="padding:12px;display:flex;flex-direction:column;gap:10px">
      <div class="row">{ico("server", 14, "#56585c")}<b style="font-weight:600;font-size:12px">A busca por frase roda no Mac mini</b><span class="pill p-ok">conectado</span></div>
      <div class="row" style="gap:10px"><div class="prog" style="flex:1"><i style="width:9%"></i></div><span class="sub">212 de 2.310</span></div>
      <span class="sub">Indexar o que falta leva cerca de 31 h no Mac mini. Esta máquina não roda essa etapa (perfil leve).</span>
      <div class="row"><span class="tbtn accent">{ico("player-play", 12)} Indexar o que falta · ~31 h</span><span class="tbtn">Só Rio de Dentro · 214 mídias · ~3 h</span></div>
    </div>
  </div>
</div>"""
    centro = buscas(inteligente="barco amarrado no cais, fim de tarde", n_itens="0 de 2.310", ativa="inteligente") + vazio
    conversa = chat(me("qual o tamanho do banco hoje?") + ai("<p><b>2.310 mídias</b>, 2.140 h, em 4 produções. 214 estão offline.</p>"))
    return doc(janela("midias", conversa, centro))


# ---------------------------------------------------------------- 4 · família (+ vínculo esboçado)

def tela_familia():
    def membro(i, nome, papel, porta, lugar, fmt, pista, estado, acoes=""):
        return f"""<div class="box" style="display:flex;gap:12px;padding:10px 12px;align-items:center">
  <div class="mthumb" style="{tom(i)};width:96px;height:54px"></div>
  <div style="flex:1;display:flex;flex-direction:column;gap:3px;min-width:0">
    <div class="row"><b style="font-weight:600">{nome}</b>{papel}{porta}</div>
    <span class="sub trunc">{lugar}</span><span style="font-size:11px;color:#56585c">{fmt}</span></div>
  <div style="width:250px;display:flex;flex-direction:column;gap:3px"><span class="label">Como foi ligada</span><span style="font-size:11px">{pista}</span></div>
  <div style="width:170px;display:flex;flex-direction:column;gap:5px;align-items:flex-end">{estado}{acoes}</div></div>"""

    comp = [("TC início", "14:02:11:09", "14:02:11:09", "14:02:11:09"), ("Duração", "00:04:31:14", "00:04:31:14", "00:04:31:14"),
            ("Quadros", "6.518", "6.518", "6.518"), ("Taxa", "23,976", "23,976", "23,976"),
            ("Resolução", "6144×3456", "1920×1080", "1920×1080"), ("Codec", "BRAW 8:1", "ProRes Proxy", "DNxHR LB"),
            ("Imagem", "—", "igual · 99%", "igual · 98%"), ("Tamanho", "38,2 GB", "1,9 GB", "2,4 GB")]
    linhas = "".join(
        f'<tr><td class="m">{a}</td><td class="mono">{b}</td><td class="mono">{c}</td><td class="mono">{d}</td>'
        f'<td>{"<span class=check>" + ico("check", 11) + " igual</span>" if a in ("TC início", "Duração", "Quadros", "Taxa") else ("<span class=na>difere · esperado</span>" if a in ("Resolução", "Codec", "Tamanho") else "<span class=check>" + ico("check", 11) + " 1:1</span>")}</td></tr>'
        for a, b, c, d in comp)
    centro = f"""
<div class="toolbar">
  <span class="tbtn">{ico("arrow-left", 12)} A012C003</span>
  <div class="crumb">{ico("versions", 14, "#56585c")}<span class="c">Família de</span> A012C003 <span class="pill p-local">3 membros</span></div>
  <span class="tbtn">{ico("search", 12)} Procurar variações em…</span>
</div>
<div class="page">
  <p class="p">Original e versões convertidas da mesma imagem. Variação não é a mesma mídia (o conteúdo difere), é um parente: TC, duração e quadros 1:1, só a janela ou o codec mudam.</p>
  {membro(2, "A012C003.braw", '<span class="pill p-ok">original</span>', PORTA_ARQ, "NAS-PRODUCAO › Brutos › D12 › CAM_A › A012C003.braw", "BRAW 8:1 · 6144×3456 · 23,976 · 38,2 GB", "é a de maior resolução da família", '<span class="pill p-warn">' + ico("alert-triangle", 10) + ' imagem não decodifica aqui</span>')}
  {membro(2, "A012C003_proxy.mov", '<span class="pill p-local">proxy</span>', PORTA_ARQ, "NAS-PRODUCAO › Brutos › D12 › CAM_A › Proxy › A012C003_proxy.mov", "ProRes Proxy · 1920×1080 · 23,976 · 1,9 GB", f'{ico("check", 11, "#2d9d57")} sufixo _proxy · pasta Proxy · comparação 1:1', '<span class="pill p-ok">' + ico("check", 10) + ' confirmado</span><span class="sub">analisada por esta — a mais leve</span>')}
  {membro(2, "A012C003 (MXF)", '<span class="pill p-local">transcode</span>', PORTA_AVID, "E: › Avid MediaFiles › MXF › 1 › A012C003.5F3A1V01.mxf (+2 de som)", "DNxHR LB · 1920×1080 · OP-Atom · 2,4 GB", f'{ico("eye", 11, "#56585c")} só comparação 1:1 — nome de arquivo do Avid não diz nada', '<span class="pill p-info">inferido</span>', f'<div class="row"><span class="tbtn danger">Não é</span><span class="tbtn confirm">{ico("check", 12)} Confirmar</span></div>')}
  <div style="display:flex;gap:14px;min-height:0">
    <div class="box" style="flex:1.4;overflow:hidden">
      <div class="boxh"><span class="ptitle" style="font-size:12px">Comparação 1:1</span><div style="flex:1"></div><span class="sub">quadros amostrados: 12</span></div>
      <table class="tbl"><thead><tr><th></th><th>original</th><th>proxy</th><th>MXF</th><th></th></tr></thead><tbody>{linhas}</tbody></table>
    </div>
    <div class="box" style="flex:1;display:flex;flex-direction:column;opacity:1">
      <div class="boxh">{ico("link", 13, "#9a9c9f")}<span class="ptitle" style="font-size:12px;color:#56585c">Som direto casado</span><span class="pill p-local">em breve</span></div>
      <div style="padding:12px;display:flex;flex-direction:column;gap:9px">
        <div class="row" style="border:0.5px dashed #d2d2cd;border-radius:6px;padding:8px 10px">
          {ico("microphone", 14, "#9a9c9f")}<div style="display:flex;flex-direction:column;gap:2px;flex:1"><span style="font-size:12px;color:#56585c">D12_T003.wav · 8 canais</span>
          <span class="sub">deslocamento <span class="mono">+234 f</span> · origem: bin sincronizada do Avid</span></div></div>
        <p class="p" style="color:#9a9c9f">Lugar reservado para o vínculo câmera × som direto: vem das timelines de sync das diárias e dos subclipes do Órbita, e leva ao NLE a imagem com o som bom.</p>
      </div>
    </div>
  </div>
</div>"""
    conversa = chat(
        me("por que o A012C003 foi analisado pelo proxy?")
        + ai("<p>O original é BRAW, que o ffmpeg desta máquina não decodifica. O proxy é 1:1 com ele (mesmo TC, duração e 6.518 quadros), então os quadros, a fala e a busca feitos no proxy valem para a família inteira.</p>",
             "<p>Na hora de levar ao NLE você escolhe qual membro vai.</p>"))
    return doc(janela("midias", conversa, centro))


# ---------------------------------------------------------------- 5 · entidades

def tela_entidades():
    ents = [("Pessoa S", "personagem", "Produção Exemplo", "Personagem B", "312", "41", True),
            ("Pessoa T", "personagem", "Produção Exemplo", "Personagem C", "268", "12", False),
            ("Personagem D", "personagem", "Produção Exemplo", "Personagem A", "140", "0", False),
            ("Personagem E", "pessoa", "Rio de Dentro", "—", "3 entrevistas", "0", False),
            ("João barqueiro", "pessoa", "Rio de Dentro", "—", "1 entrevista", "0", False),
            ("Cais do porto", "local", "todas", "—", "86", "23", False),
            ("Casa da praia", "local", "Produção Exemplo", "—", "121", "4", False),
            ("“Deixa comigo, meu bem”", "bordão", "Produção Exemplo", "Pessoa S", "37", "9", False),
            ("Barco Estrela do Mar", "objeto", "Produção Exemplo", "—", "19", "6", False)]
    ico_tipo = {"personagem": "masks-theater", "pessoa": "user", "local": "map-pin", "bordão": "quote", "objeto": "package"}
    linhas = "".join(f"""<tr class="{"sel" if s else ""}"><td><div class="row">{ico(ico_tipo[t], 12, "#56585c")}<b style="font-weight:500">{n}</b></div></td>
<td class="m">{t}</td><td class="m">{p}</td><td class="m">{a}</td><td>{c}</td><td>{('<span class="pill p-info">' + i + ' a revisar</span>') if i != "0" else '<span class="na">—</span>'}</td></tr>""" for n, t, p, a, c, i, s in ents)
    tabela = f'<div class="tblwrap"><table class="tbl"><thead><tr><th>Nome</th><th>Tipo</th><th>Produção</th><th>Intérprete / de quem</th><th>Aparições confirmadas</th><th>Inferidas</th></tr></thead><tbody>{linhas}</tbody></table></div>'
    centro = f"""
<div class="toolbar">
  <div class="crumb">{ico("masks-theater", 14, "#56585c")}<span>Entidades</span></div>
  <div class="search" style="width:220px">{ico("search", 13)}<span class="trunc">Procurar pessoa, local, bordão…</span></div>
  <span class="tbtn">{ico("plus", 12)} Nova entidade</span>
  <span class="tbtn">{ico("clipboard-text", 12)} Ler elenco do roteiro…</span>
</div>
<div class="filters">
  <span class="fchip on">Todas</span><span class="fchip">{ico("masks-theater", 11)} Personagens</span><span class="fchip">{ico("user", 11)} Pessoas</span>
  <span class="fchip">{ico("map-pin", 11)} Locais</span><span class="fchip">{ico("package", 11)} Objetos</span><span class="fchip">{ico("quote", 11)} Bordões</span>
  <span style="width:10px"></span><span class="label">Produção</span><span class="fchip">Produção Exemplo</span><span class="fchip">Rio de Dentro</span>
</div>
{tabela}"""
    aparicoes = [(0, "CAP042", "01:12:40:03", "roteiro ancorado · 94%", False),
                 (5, "CAP041", "01:31:02:11", "roteiro ancorado · 88%", False),
                 (10, "CAP040", "01:04:18:20", "roteiro ancorado · 41%", True),
                 (5, "CAP041", "01:40:55:02", "sem roteiro · anotação sugerida", True)]
    ap = "".join(f"""<div class="row" style="padding:5px 0;border-bottom:0.5px solid #e6e6e3"><div class="mthumb" style="{tom(i)};width:56px;height:32px"></div>
  <div style="display:flex;flex-direction:column;gap:1px;flex:1;min-width:0"><span style="font-size:11px;font-weight:500">{c} <span class="mono sub">{tc}</span></span><span class="sub trunc">{m}</span></div>
  {('<div class="row" style="gap:4px"><span class="tbtn danger" style="padding:3px 6px">' + ico("x", 11) + '</span><span class="tbtn confirm" style="padding:3px 6px">' + ico("check", 11) + '</span></div>') if inf else '<span class="check">' + ico("circle-check", 13) + '</span>'}</div>""" for i, c, tc, m, inf in aparicoes)
    inspetor = f"""
<div class="insp">
  <div class="phead">{ico("masks-theater", 14, "#56585c")}<span class="ptitle">Pessoa S</span><span class="pill p-local">personagem</span></div>
  <div class="sec"><dl class="kv"><dt>Produção</dt><dd>Produção Exemplo</dd><dt>Intérprete</dt><dd>{ico("user", 11)} Personagem B</dd>
    <dt>Também chamada</dt><dd>Lena, dona Pessoa S</dd><dt>Bordão</dt><dd>“Deixa comigo, meu bem”</dd></dl></div>
  <div class="sec"><span class="label">De onde vêm as aparições</span>
    <dl class="kv"><dt>Roteiro</dt><dd>198 · capítulos 1–42</dd><dt>Anotação</dt><dd>114</dd><dt>Claquete</dt><dd>—</dd></dl>
    <span class="sub">Nunca pelo rosto nem pela voz: roteiro, claquete e o que você anotou.</span></div>
  <div class="sec" style="flex:1;border-bottom:none;overflow:hidden"><div class="row"><span class="label">A revisar</span><span class="pill p-info">41</span><div style="flex:1"></div><span class="tbtn">Ver todas</span></div>{ap}</div>
</div>"""
    conversa = chat(
        me("quantas vezes a helena fala o bordão nos capítulos?")
        + ai("<p><b>37 vezes</b> confirmadas, em 29 capítulos. Mais 9 prováveis: a frase está na transcrição, mas o roteiro do capítulo não diz quem fala.</p>",
             f'<div class="row"><span class="tbtn">{ico("eye", 12)} Revisar as 9</span><span class="tbtn">{ico("stack-2", 12)} Coleção com as 37</span></div>',
             '<p class="sub">Procurei nos 42 capítulos com fala transcrita, de 42.</p>'))
    return doc(janela("entidades", conversa, centro, inspetor))


# ---------------------------------------------------------------- 6 · levar ao NLE

def tela_nle():
    def destino(nome, icone, formato, estado, sel=False):
        borda = "border-color:#378add;box-shadow:0 0 0 1px #378add;" if sel else ""
        return f"""<div class="box" style="flex:1;padding:12px;display:flex;flex-direction:column;gap:6px;{borda}">
  <div class="row">{ico(icone, 16, "#185fa5" if sel else "#56585c")}<b style="font-weight:600">{nome}</b></div>
  <span class="sub">{formato}</span><span style="font-size:11px">{estado}</span></div>"""

    itens = [(1, "ENT_MARTA_03", "10:31:04:12 → 10:31:11:20", "original", True),
             (3, "ENT_MARTA_02", "09:52:40:03 → 09:52:47:00", "original", True),
             (8, "ENT_JOAO_BARQUEIRO_01", "11:20:15:00 → 11:20:29:12", "proxy (original BRAW)", True),
             (4, "ARQ_TVE_1987_ENCHENTE", "00:02:10:00 → 00:02:31:00", "offline", False),
             (9, "DRONE_CAIS_0412", "00:00:12:00 → 00:00:20:00", "original", True)]
    lista = "".join(f"""<div class="row" style="padding:6px 12px;border-bottom:0.5px solid #e6e6e3"><div class="mthumb" style="{tom(i)};width:52px;height:29px"></div>
  <b style="font-weight:500;width:170px" class="trunc">{n}</b><span class="mono sub" style="flex:1;white-space:nowrap">{tc}</span>
  {('<span class="pill p-local">' + ico("versions", 10) + ' ' + v + '</span>') if ok else '<span class="pill p-bad">' + ico("cloud-off", 10) + ' offline · não vai</span>'}</div>""" for i, n, tc, v, ok in itens)
    centro = f"""
<div class="toolbar">
  <div class="crumb">{ico("file-export", 14, "#56585c")}<span class="c">Levar ao NLE</span> 12 momentos selecionados</div>
</div>
<div class="page">
  <span class="label">Para onde</span>
  <div style="display:flex;gap:12px">
    {destino("Avid Media Composer", "box", "bin .avb · mídia linkada por AMA", "decupagem nas colunas · falas como marcadores", True)}
    {destino("Premiere Pro", "file", "projeto .prproj", "bins e sequência · marcadores")}
    {destino("DaVinci Resolve", "file", ".drt", "timeline · metadados de cena")}
    {destino("Prévia em MP4", "player-play", "um arquivo, com TC queimado", "para revisar ou mandar a alguém")}
  </div>
  <div style="display:flex;gap:14px;min-height:0;flex:1">
    <div class="box" style="flex:1;display:flex;flex-direction:column;gap:0;overflow:hidden">
      <div class="boxh"><span class="ptitle" style="font-size:12px">Como vai</span></div>
      <div style="padding:12px;display:flex;flex-direction:column;gap:12px">
        <div style="display:flex;flex-direction:column;gap:5px"><span class="label">Qual membro da família</span>
          <div class="seg" style="align-self:flex-start"><span class="on">Original quando legível</span><span>Sempre o proxy</span><span>Gerenciada do Avid, se houver</span></div></div>
        <div style="display:flex;flex-direction:column;gap:5px"><span class="label">Organização</span>
          <div class="seg" style="align-self:flex-start"><span class="on">Uma bin com a sequência</span><span>Uma bin por entrevistado</span><span>Só os subclipes</span></div></div>
        <div style="display:flex;flex-direction:column;gap:6px"><span class="label">Junto com a mídia</span>
          <div style="display:flex;flex-wrap:wrap;gap:8px 16px;font-size:12px;white-space:nowrap"><span class="row">{ico("square-check", 14, "#378add")} decupagem nas colunas</span>
            <span class="row">{ico("square-check", 14, "#378add")} anotações</span><span class="row">{ico("square-check", 14, "#378add")} falas como marcadores</span>
            <span class="row">{ico("square", 14, "#9a9c9f")} respiro de 12 f nas bordas</span></div></div>
        <div style="display:flex;flex-direction:column;gap:5px"><span class="label">Onde gravar</span>
          <div class="row"><span class="tag mono" style="flex:1">NAS-PRODUCAO › Rio de Dentro › Avid › ENCHENTE 87.avb</span><span class="tbtn">Escolher…</span></div></div>
      </div>
    </div>
    <div class="box" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
      <div class="boxh"><span class="ptitle" style="font-size:12px">O que vai</span><div style="flex:1"></div><span class="sub">11 de 12</span></div>
      {lista}
      <div class="row sub" style="padding:8px 12px">+ 7 momentos</div>
      <div style="flex:1"></div>
      <div class="row" style="padding:10px 12px;border-top:0.5px solid #e6e6e3;background:#faeeda;color:#854f0b;font-size:11px">{ico("alert-triangle", 12)} 1 momento está offline e fica de fora. <a style="color:#854f0b;text-decoration:underline">Reconectar antes</a></div>
    </div>
  </div>
  <div class="row"><div style="flex:1"></div><span class="tbtn">Cancelar</span><span class="tbtn accent">{ico("file-export", 12)} Gerar a bin</span></div>
</div>"""
    conversa = chat(
        me("leva os momentos da enchente pro avid")
        + ai("<p>Preparei a entrega: 11 momentos numa bin nova, com a mídia linkada por AMA e a decupagem nas colunas. Confira as opções ao lado antes de gerar.</p>",
             "<p>Um momento (<span class='mono'>ARQ_TVE_1987_ENCHENTE</span>) está offline e ficaria de fora.</p>"))
    return doc(janela("midias", conversa, centro))


# ---------------------------------------------------------------- 8 · banco novo, vazio

def tela_vazio():
    centro = f"""
<div class="toolbar"><div class="crumb">{ico("movie", 14, "#56585c")}<span>Todas as mídias</span></div></div>
<div style="flex:1;display:flex;align-items:center;justify-content:center">
  <div style="width:520px;display:flex;flex-direction:column;gap:16px;align-items:flex-start">
    <span class="h2">Este banco ainda não tem mídia</span>
    <p class="p">Um banco é uma pasta: tudo que o Ciclo Assist descobre das mídias fica nela. A mídia em si continua onde está.</p>
    <div style="display:flex;flex-direction:column;gap:8px;width:100%">
      <div class="box row" style="padding:12px;gap:12px">{ico("folder-down", 18, "#378add")}<div style="flex:1;display:flex;flex-direction:column;gap:2px"><b style="font-weight:600">Observar uma pasta</b><span class="sub">Toda mídia que cair nela entra e é analisada sozinha.</span></div>{ico("chevron-right", 14, "#9a9c9f")}</div>
      <div class="box row" style="padding:12px;gap:12px">{ico("box", 18, "#378add")}<div style="flex:1;display:flex;flex-direction:column;gap:2px"><b style="font-weight:600">Ler uma Avid MediaFiles</b><span class="sub">A mídia gerenciada do Media Composer, tratada à parte.</span></div>{ico("chevron-right", 14, "#9a9c9f")}</div>
      <div class="box row" style="padding:12px;gap:12px">{ico("file", 18, "#378add")}<div style="flex:1;display:flex;flex-direction:column;gap:2px"><b style="font-weight:600">Adicionar arquivos</b><span class="sub">Ou arraste do Finder para cá.</span></div>{ico("chevron-right", 14, "#9a9c9f")}</div>
      <div class="box row" style="padding:12px;gap:12px">{ico("git-merge", 18, "#378add")}<div style="flex:1;display:flex;flex-direction:column;gap:2px"><b style="font-weight:600">Somar outro banco</b><span class="sub">Traz o que já foi analisado em outro lugar, sem refazer.</span></div>{ico("chevron-right", 14, "#9a9c9f")}</div>
    </div>
  </div>
</div>"""
    conversa = f"""
<div class="chat">
  <div class="phead">{ico("message", 14, "#56585c")}<span class="ptitle">Conversa</span><span class="pill p-local">Claude · Sonnet 5</span></div>
  <div class="msgs" style="justify-content:center;align-items:center;text-align:center">
    <span class="sub" style="max-width:240px;line-height:1.5">A conversa trabalha sobre o que o banco conhece. Com o banco vazio, ainda não há o que procurar.</span></div>
  <div class="compose"><div class="cbox"><div style="color:#9a9c9f;font-size:12px;min-height:34px">Pergunte sobre o banco…</div>
    <div class="row" style="color:#9a9c9f">{ico("paperclip", 14)}<div style="flex:1"></div><span class="send" style="background:#d2d2cd">{ico("arrow-up", 14)}</span></div></div></div>
</div>"""
    win = (f'<div class="win">{titlebar("Entrevistas Personagem E", "local")}<div class="body">{rail("midias")}{conversa}'
           f'<div class="center">{centro}</div></div>'
           f'<div class="foot"><span class="it">{ico("folder", 11)} banco local · /Volumes/SSD_LC/Bancos/Entrevistas Personagem E</span><div style="flex:1"></div><span class="it">esta máquina: MacBook Pro · perfil leve</span></div></div>')
    return doc(win)


# ---------------------------------------------------------------- 9 · ingestão

def tela_ingestao():
    def pasta(nome, lugar, porta, etapas, estado):
        chips = "".join(f'<span class="pill {c}">{ico(i, 10)} {t}</span>' for i, t, c in etapas)
        return f"""<tr><td><div style="display:flex;flex-direction:column;gap:2px"><div class="row">{ico("folder", 13, "#56585c")}<b style="font-weight:500">{nome}</b></div><span class="sub">{lugar}</span><span style="font-size:11px">{estado}</span></div></td>
<td>{porta}</td><td><div style="display:flex;flex-wrap:wrap;gap:4px;white-space:normal">{chips}</div></td></tr>"""

    E_OK, E_MAC, E_DEM, E_OFF = "p-ok", "p-info", "p-local", "p-warn"
    pastas = "".join([
        pasta("Entrevistas", "NAS-PRODUCAO › Rio de Dentro › Entrevistas", PORTA_ARQ,
              [("photo", "quadros", E_OK), ("wave-sine", "fala", E_OK), ("vector-triangle", "busca por frase · Mac mini", E_MAC), ("file-description", "decupagem sob demanda", E_DEM)],
              f'<span class="row">{ico("eye", 12, "#2d9d57")} observando · 41 mídias</span>'),
        pasta("Capítulos exibidos", "NAS-PRODUCAO › Produção Exemplo › Finalizados", PORTA_ARQ,
              [("photo", "quadros + planos", E_OK), ("wave-sine", "fala", E_OK), ("clipboard-text", "roteiro do capítulo", E_OK), ("file-description", "decupagem sob demanda", E_DEM)],
              f'<span class="row">{ico("clock", 12, "#854f0b")} 1 copiando · aguardando terminar</span>'),
        pasta("Avid MediaFiles do E:", "E: › Avid MediaFiles › MXF e UME (MXF-* fica de fora)", PORTA_AVID,
              [("photo", "quadros", E_OK), ("wave-sine", "fala", E_OK), ("versions", "procurar variações", E_OK)],
              f'<span class="row">{ico("eye", 12, "#2d9d57")} observando · pelo .pmr · 0,3 s</span>'),
        pasta("Material de arquivo", "NAS-PRODUCAO › Rio de Dentro › Arquivo", PORTA_ARQ,
              [("photo", "quadros", E_OK), ("wave-sine", "fala", E_OK), ("vector-triangle", "busca por frase · Mac mini", E_MAC)],
              f'<span class="row">{ico("cloud-off", 12, "#a32d2d")} pasta offline desde 12/09</span>'),
    ])

    def tarefa(nome, etapa, onde, frac, texto, cor="#2d9d57"):
        return f"""<div style="display:flex;flex-direction:column;gap:5px;padding:9px 12px;border-bottom:0.5px solid #e6e6e3">
  <div class="row"><b style="font-weight:500" class="trunc">{nome}</b><span class="pill p-local">{etapa}</span><div style="flex:1"></div><span class="sub">{onde}</span></div>
  <div class="prog"><i style="width:{frac}%;background:{cor}"></i></div><span class="sub">{texto}</span></div>"""

    fila = (tarefa("MAR_ABERTO_CAP043", "fala", "esta máquina", 62, "transcrevendo · 27 de 44 min · faltam ~6 min")
            + tarefa("ENT_JOAO_BARQUEIRO_01", "busca por frase", "Mac mini", 30, "enviando quadros · 64 de 214 planos")
            + tarefa("ENT_MARTA_04", "quadros", "esta máquina", 0, "na fila · entra depois da fala", "#d2d2cd")
            + f"""<div style="display:flex;flex-direction:column;gap:4px;padding:9px 12px;background:#faeeda">
  <div class="row" style="color:#854f0b">{ico("alert-triangle", 12)}<b style="font-weight:500">3 etapas puladas nesta máquina</b></div>
  <span style="font-size:11px;color:#854f0b">Whisper grande e VLM local não rodam no perfil leve. Vão para o Mac mini quando ele estiver livre.</span></div>""")
    centro = f"""
<div class="toolbar">
  <div class="crumb">{ico("folder-down", 14, "#56585c")}<span>Ingestão</span></div>
  <span class="tbtn">{ico("plus", 12)} Observar pasta</span><span class="tbtn">{ico("file", 12)} Adicionar arquivos</span>
</div>
<div class="page" style="flex-direction:row;gap:14px">
  <div style="flex:1.6;display:flex;flex-direction:column;gap:14px;min-width:0">
    <div class="box" style="overflow:hidden"><div class="boxh"><span class="ptitle" style="font-size:12px">Pastas observadas</span><div style="flex:1"></div><span class="sub">o que cai nelas entra no banco</span></div>
      <table class="tbl"><thead><tr><th>Pasta</th><th>Porta</th><th>Etapas</th></tr></thead><tbody>{pastas}</tbody></table></div>
    <div class="box" style="padding:12px;display:flex;flex-direction:column;gap:8px">
      <div class="row"><span class="label">Regra de chegada</span></div>
      <span class="p">Um arquivo só entra quando para de crescer: tamanho igual por 20 s. Arquivos <span class="mono">._*</span> e pastas ocultas ficam de fora.</span>
      <div class="row"><span class="pill p-ok">{ico("wave-sine", 10)} idioma da fala: detectar</span><span class="pill p-local">decupagem: só sob demanda</span></div>
    </div>
  </div>
  <div style="flex:1;display:flex;flex-direction:column;gap:14px;min-width:0">
    <div class="box" style="overflow:hidden"><div class="boxh"><span class="ptitle" style="font-size:12px">Fila</span><span class="pill p-local">3</span><div style="flex:1"></div><span class="tbtn">{ico("player-pause", 12)} Pausar</span></div>{fila}</div>
    <div class="box" style="overflow:hidden"><div class="boxh">{ico("device-laptop", 13, "#56585c")}<span class="ptitle" style="font-size:12px">Esta máquina</span><span class="pill p-local">perfil leve</span></div>
      <div style="padding:10px 12px"><dl class="kv"><dt>Máquina</dt><dd>MacBook Pro · Media Composer aberto</dd>
        <dt>Roda aqui</dt><dd>quadros, planos, fala (Whisper small), vetor de imagem</dd>
        <dt>Manda ao Mac</dt><dd>busca por frase, Whisper grande, decupagem local</dd>
        <dt>Nunca aqui</dt><dd>modelo local (a máquina com o NLE fica com o NLE)</dd></dl></div></div>
  </div>
</div>"""
    conversa = chat(
        me("o que falta processar da semana?")
        + ai("<p>Da semana entraram <b>57 mídias</b>. Faltam:</p>",
             "<p>· 3 na fila agora (1 capítulo, 2 entrevistas)<br>· 1 capítulo ainda copiando para o NAS<br>· a pasta <b>Material de arquivo</b> está offline desde 12/09 — o que cair nela não está sendo visto</p>"))
    return doc(janela("ingestao", conversa, centro))


# ---------------------------------------------------------------- 10 · reconectar

def tela_reconectar():
    def crit(ok):
        if ok is None:
            return f'<span class="na">{ico("minus", 11)}</span>'
        return f'<span class="check">{ico("check", 11)}</span>' if ok else f'<span class="miss">{ico("x", 11)}</span>'

    cands = [("ENT_MARTA_01.mov", "NAS › Entrevistas", "HD_ENTREGA › Personagem E", True, True, True, True, True, True, "idêntico", "p-ok", True),
             ("ARQ_TVE_1987_ENCHENTE.mp4", "NAS › Arquivo", "HD_ENTREGA › Arquivo › …_v2.mp4", False, True, True, True, False, False, "conteúdo difere", "p-warn", False),
             ("A014C007.braw", "NAS › D14 › CAM_A", "HD_ENTREGA › D14 › …_proxy.mov", False, False, True, True, False, False, "parece variação", "p-info", False),
             ("CAP037_FINAL.mxf", "NAS › Finalizados", "HD_ENTREGA › Finalizados", True, True, True, False, True, False, "duração difere 1 f", "p-warn", False)]
    linhas = "".join(f"""<tr class="{"sel" if sel else ""}"><td><div style="display:flex;flex-direction:column;gap:1px"><b style="font-weight:500">{n}</b><span class="sub">visto por último: {a}</span></div></td>
<td><span class="mono" style="font-size:10px;color:#56585c">{b}</span></td><td>{crit(c1)}</td><td>{crit(c2)}</td><td>{crit(c3)}</td><td>{crit(c4)}</td><td>{crit(c5)}</td><td>{crit(c6)}</td>
<td><span class="pill {pc}">{v}</span></td></tr>""" for n, a, b, c1, c2, c3, c4, c5, c6, v, pc, sel in cands)
    centro = f"""
<div class="toolbar">
  <div class="crumb">{ico("plug-connected", 14, "#56585c")}<span>Reconectar</span><span class="pill p-bad">214 offline</span></div>
</div>
<div class="page">
  <div class="box row" style="padding:10px 12px;gap:10px">{ico("folder", 16, "#56585c")}
    <div style="flex:1;display:flex;flex-direction:column;gap:1px"><span class="label">Procurar em</span><span class="mono" style="font-size:12px">/Volumes/HD_ENTREGA</span></div>
    <span class="sub">14.822 arquivos lidos · 3 min 12 s</span><span class="tbtn">Outra pasta…</span></div>
  <div style="display:flex;gap:12px">
    <div class="box" style="flex:1;padding:12px;display:flex;flex-direction:column;gap:6px"><div class="row">{ico("circle-check", 16, "#2d9d57")}<b style="font-weight:600">188 com certeza</b></div>
      <span class="sub">conteúdo idêntico (tamanho + início e fim do arquivo)</span><span class="tbtn confirm" style="align-self:flex-start">{ico("check", 12)} Reconectar as 188</span></div>
    <div class="box" style="flex:1;padding:12px;display:flex;flex-direction:column;gap:6px;border-color:#378add"><div class="row">{ico("eye", 16, "#185fa5")}<b style="font-weight:600">21 candidatos</b></div>
      <span class="sub">nome, TC ou duração batem, mas o conteúdo não confirma</span><span class="tbtn accent" style="align-self:flex-start">Revisar um a um</span></div>
    <div class="box" style="flex:1;padding:12px;display:flex;flex-direction:column;gap:6px"><div class="row">{ico("versions", 16, "#56585c")}<b style="font-weight:600">3 variações achadas</b></div>
      <span class="sub">não são a mídia perdida, mas são da família dela</span><span class="tbtn" style="align-self:flex-start">Ligar à família</span></div>
    <div class="box" style="flex:1;padding:12px;display:flex;flex-direction:column;gap:6px"><div class="row">{ico("alert-triangle", 16, "#854f0b")}<b style="font-weight:600">2 sem candidato</b></div>
      <span class="sub">continuam offline; as análises delas seguem no banco</span><span class="tbtn" style="align-self:flex-start">Ver quais</span></div>
  </div>
  <div class="box" style="overflow:hidden;flex:1">
    <div class="boxh"><span class="ptitle" style="font-size:12px">Candidatos</span><div style="flex:1"></div>
      <span class="sub">o conteúdo decide sozinho; nome, extensão, TC e duração só sugerem</span></div>
    <table class="tbl"><thead><tr><th>Mídia offline</th><th>Achado em</th><th>Nome</th><th>Extensão</th><th>TC</th><th>Duração</th><th>Tamanho</th><th>Conteúdo</th><th>Veredito</th></tr></thead><tbody>{linhas}</tbody></table>
    <div class="row" style="padding:10px 12px;gap:8px"><span class="sub" style="flex:1">Selecionada: ENT_MARTA_01.mov → conteúdo idêntico. Todas as análises e anotações continuam valendo.</span>
      <span class="tbtn danger">Não é</span><span class="tbtn confirm">{ico("check", 12)} Reconectar</span></div>
  </div>
</div>"""
    conversa = chat(
        me("o HD de entrega chegou, reconecta o que der")
        + ai("<p>Li o <span class='mono'>HD_ENTREGA</span>. <b>188 mídias</b> batem por conteúdo e posso reconectar sem perguntar.</p>",
             "<p>Outras 21 só batem por nome ou TC — essas quem decide é você. E achei 3 proxies de brutos que estavam sem família.</p>"))
    return doc(janela("reconectar", conversa, centro))


# ---------------------------------------------------------------- 11 · bancos

def tela_bancos():
    def banco(nome, tipo, lugar, numeros, gente, acoes, aberto=False):
        pill = '<span class="pill p-info">' + ico("network", 10) + ' remoto</span>' if tipo == "remoto" else '<span class="pill p-local">' + ico("folder", 10) + ' local</span>'
        borda = "border-color:#378add;box-shadow:0 0 0 1px #378add;" if aberto else ""
        return f"""<div class="box" style="padding:12px;display:flex;flex-direction:column;gap:8px;{borda}">
  <div class="row">{ico("database", 16, "#56585c")}<b style="font-weight:600;font-size:13px">{nome}</b>{pill}{'<span class="pill p-ok">aberto</span>' if aberto else ''}<div style="flex:1"></div>{acoes}</div>
  <span class="sub mono">{lugar}</span>
  <div class="row" style="gap:16px;font-size:11px;color:#56585c">{numeros}</div>{gente}</div>"""

    remoto = banco("Acervo Ciclo", "remoto", "servidor: nas-producao · 192.168.1.20:7830", "<span>2.310 mídias</span><span>2.140 h</span><span>1,2 TB de análises</span><span>4 produções</span>",
                   f'<div class="row" style="gap:6px"><span class="sub">conectados agora:</span><span class="tag">LC · MacBook Pro</span><span class="tag">RA · iMac sala 2</span><span class="tag">Mac mini · processando</span></div>',
                   f'<span class="tbtn">{ico("users", 12)} Usuários</span><span class="tbtn">{ico("file-export", 12)} Exportar como local…</span>', True)
    local1 = banco("Entrevistas Personagem E", "local", "/Volumes/SSD_LC/Bancos/Entrevistas Personagem E", "<span>41 mídias</span><span>38 h</span><span>22 GB</span>",
                   '<span class="sub">analisado por você entre 02/09 e 13/09 · não está em nenhum remoto</span>',
                   f'<span class="tbtn">Abrir</span><span class="tbtn accent">{ico("git-merge", 12)} Somar a um remoto…</span>')
    local2 = banco("Diárias D10–D14", "local", "/Volumes/HD_ENTREGA/Banco Diárias", "<span>612 mídias</span><span>94 h</span><span>71 GB</span>",
                   '<span class="sub">recebido do Montador A em 10/09 · cópia exportada do Acervo Ciclo</span>',
                   f'<span class="tbtn">Abrir</span><span class="tbtn">{ico("git-merge", 12)} Somar a um remoto…</span>')
    centro = f"""
<div class="toolbar">
  <div class="crumb">{ico("database", 14, "#56585c")}<span>Bancos</span></div>
  <span class="tbtn">{ico("plus", 12)} Novo banco local</span><span class="tbtn">{ico("network", 12)} Conectar a um remoto…</span>
</div>
<div class="page" style="flex-direction:row;gap:16px">
  <div style="flex:1.7;display:flex;flex-direction:column;gap:12px;min-width:0">
    <span class="label">Remotos</span>{remoto}
    <span class="label" style="margin-top:6px">Locais nesta máquina</span>{local1}{local2}
  </div>
  <div style="flex:1;display:flex;flex-direction:column;gap:12px;min-width:0">
    <div class="box" style="padding:14px;display:flex;flex-direction:column;gap:12px">
      <span class="ptitle">Local e remoto são o mesmo banco</span>
      <div class="row" style="align-items:flex-start;gap:10px">{ico("folder", 16, "#56585c")}<div style="display:flex;flex-direction:column;gap:3px"><b style="font-weight:600;font-size:12px">Local</b>
        <span class="p">Uma pasta. Sem usuários nem permissões: copie para outro HD, mande a outro editor, abra em qualquer máquina.</span></div></div>
      <div class="row" style="align-items:flex-start;gap:10px">{ico("network", 16, "#185fa5")}<div style="display:flex;flex-direction:column;gap:3px"><b style="font-weight:600;font-size:12px">Remoto</b>
        <span class="p">A mesma pasta atrás de um servidor, no NAS ou no Mac mini. Várias pessoas ao mesmo tempo, cada uma com a sua permissão.</span></div></div>
      <div style="border-top:0.5px solid #e6e6e3;padding-top:10px;display:flex;flex-direction:column;gap:8px">
        <div class="row" style="font-size:12px">{ico("folder", 13, "#56585c")}{ico("arrow-right", 12, "#9a9c9f")}{ico("network", 13, "#185fa5")}<span><b style="font-weight:600">Somar</b> um local a um remoto: o remoto guarda uma cópia, conflitos revisados por você.</span></div>
        <div class="row" style="font-size:12px">{ico("network", 13, "#185fa5")}{ico("arrow-right", 12, "#9a9c9f")}{ico("folder", 13, "#56585c")}<span><b style="font-weight:600">Exportar</b> um remoto como local: uma cópia sem amarras.</span></div>
      </div>
    </div>
  </div>
</div>"""
    conversa = chat(
        me("quero mandar as diárias da D15 pro Montador A num HD")
        + ai("<p>Dá para exportar só a produção <b>Brutos D15</b> do Acervo Ciclo como um banco local: 188 mídias, ~24 GB de análises. A mídia não vai junto — só o que foi descoberto dela.</p>",
             "<p>Quando ele devolver, você soma de volta e revisa o que ele mudou.</p>"))
    return doc(janela("bancos", conversa, centro))


# ---------------------------------------------------------------- 12 · permissões

def tela_permissoes():
    papeis = ["Leitura", "Escrita", "Exclusão", "Administração"]

    def pessoa(ini, cor, nome, quem, papel, agora, ultimo):
        seg = "".join(f'<span class="{"on" if p == papel else ""}">{p}</span>' for p in papeis)
        return f"""<tr><td><div class="row"><span style="width:24px;height:24px;border-radius:50%;background:{cor[0]};color:{cor[1]};font-size:9px;font-weight:600;display:flex;align-items:center;justify-content:center">{ini}</span>
  <div style="display:flex;flex-direction:column;gap:1px"><b style="font-weight:500">{nome}</b><span class="sub">{quem}</span></div></div></td>
<td><div class="seg">{seg}</div></td><td>{agora}</td><td class="m">{ultimo}</td><td><span class="tbtn" style="padding:3px 6px">{ico("dots", 12)}</span></td></tr>"""

    on = '<span class="row">' + '<span class="dot" style="background:#1d9e75"></span> conectado</span>'
    off = '<span class="row na"><span class="dot" style="background:#d2d2cd"></span> —</span>'
    gente = "".join([
        pessoa("LC", ("#e1f5ee", "#0f6e56"), "Lohan Costa", "dono do banco", "Administração", on, "anotou 12 trechos"),
        pessoa("RA", ("#e6f1fb", "#185fa5"), "Montador A", "montador", "Exclusão", on, "somou um banco"),
        pessoa("MB", ("#faeeda", "#854f0b"), "Assistente B", "assistente de montagem", "Escrita", off, "reconectou 40"),
        pessoa("DI", ("#ececea", "#56585c"), "Direção", "consulta", "Leitura", off, "procurou 9 vezes"),
        pessoa("MM", ("#ececea", "#56585c"), "Mac mini", "processador da rede", "Escrita", on, "busca por frase"),
    ])
    registro = "".join(f'<div class="row" style="padding:6px 0;border-bottom:0.5px solid #e6e6e3;font-size:11px"><span class="mono sub" style="width:40px">{h}</span><b style="font-weight:500">{q}</b><span class="trunc" style="color:#56585c;flex:1">{o}</span></div>'
                       for h, q, o in [("15:42", "Lohan", "anotou ENT_MARTA_03 10:31:04 · Personagem E"),
                                       ("15:30", "Mac mini", "busca por frase pronta · ENT_MARTA_02"),
                                       ("14:58", "Montador A", "confirmou 9 aparições de Pessoa S"),
                                       ("14:12", "Assistente B", "tentou excluir A012C004 · recusado: sem permissão"),
                                       ("11:03", "Montador A", "somou o banco Diárias D10–D14 · 3 conflitos resolvidos")])
    centro = f"""
<div class="toolbar">
  <span class="tbtn">{ico("arrow-left", 12)} Bancos</span>
  <div class="crumb">{ico("users", 14, "#56585c")}<span class="c">Acervo Ciclo ›</span> Usuários e permissões</div>
  <span class="tbtn">{ico("plus", 12)} Convidar</span>
</div>
<div class="page" style="flex-direction:row;gap:16px">
  <div style="flex:2.6;display:flex;flex-direction:column;gap:12px;min-width:0">
    <div class="box" style="overflow:hidden"><table class="tbl"><thead><tr><th>Pessoa</th><th>Pode</th><th>Agora</th><th>Última ação</th><th></th></tr></thead><tbody>{gente}</tbody></table></div>
    <div class="box" style="padding:12px;display:grid;grid-template-columns:repeat(4, minmax(0, 1fr));gap:12px">
      <div style="display:flex;flex-direction:column;gap:3px"><b style="font-weight:600;font-size:12px">Leitura</b><span class="sub">procura, vê, conversa e leva ao NLE</span></div>
      <div style="display:flex;flex-direction:column;gap:3px"><b style="font-weight:600;font-size:12px">Escrita</b><span class="sub">+ anota, processa, reconecta, soma bancos</span></div>
      <div style="display:flex;flex-direction:column;gap:3px"><b style="font-weight:600;font-size:12px">Exclusão</b><span class="sub">+ tira mídia e análise do banco</span></div>
      <div style="display:flex;flex-direction:column;gap:3px"><b style="font-weight:600;font-size:12px">Administração</b><span class="sub">+ pessoas, permissões e exportar</span></div>
    </div>
    <div class="row box" style="padding:10px 12px;gap:10px"><span class="p" style="flex:1">Quem entrar por convite começa com</span><div class="seg"><span class="on">Leitura</span><span>Escrita</span></div></div>
  </div>
  <div class="box" style="flex:1;display:flex;flex-direction:column;overflow:hidden">
    <div class="boxh">{ico("history", 13, "#56585c")}<span class="ptitle" style="font-size:12px">Registro</span><div style="flex:1"></div><span class="sub">hoje</span></div>
    <div style="padding:4px 12px">{registro}</div>
  </div>
</div>"""
    conversa = chat(
        me("a mariana pode apagar mídia?")
        + ai("<p>Não. Ela tem <b>Escrita</b>: anota, processa e reconecta, mas não tira nada do banco. Hoje às 14:12 ela tentou excluir <span class='mono'>A012C004</span> e o servidor recusou.</p>",
             "<p>Só quem administra muda isso — você.</p>"))
    return doc(janela("bancos", conversa, centro))


# ---------------------------------------------------------------- 13 · somar bancos

def tela_somar():
    esq = ("E a água chegou no <span style='background:#fcebeb;color:#a32d2d;border-radius:2px;padding:0 2px'>segundo ano</span>. No segundo andar!",
           "Whisper small · MacBook Pro de Lohan · 04/09", "612 falas · 4 trechos anotados à mão")
    dir_ = ("E a água chegou no <span style='background:#e1f5ee;color:#0f6e56;border-radius:2px;padding:0 2px'>segundo andar</span>. No segundo andar!",
            "Whisper large-v3 · Mac mini · 13/09 · revisada por Montador A", "618 falas · 0 trechos anotados")

    def lado(titulo, pill, txt, proc, nums, sel):
        borda = "border-color:#378add;box-shadow:0 0 0 1px #378add;" if sel else ""
        return f"""<div class="box" style="flex:1;display:flex;flex-direction:column;{borda}">
  <div class="boxh"><span class="ptitle" style="font-size:12px">{titulo}</span>{pill}<div style="flex:1"></div>
    {'<span class="tbtn accent">' + ico("check", 12) + ' Fica esta</span>' if sel else '<span class="tbtn">Fica esta</span>'}</div>
  <div style="padding:12px;display:flex;flex-direction:column;gap:8px">
    <div style="display:flex;gap:10px"><span class="mono sub" style="width:78px;flex:none">10:31:04:12</span><span style="font-size:12px;line-height:1.5">{txt}</span></div>
    <div style="display:flex;gap:10px"><span class="mono sub" style="width:78px;flex:none">10:31:12:00</span><span style="font-size:12px;line-height:1.5;color:#56585c">E a senhora ficou onde?</span></div>
    <div style="border-top:0.5px solid #e6e6e3;padding-top:8px;display:flex;flex-direction:column;gap:2px"><span class="sub">{proc}</span><span class="sub">{nums}</span></div>
  </div></div>"""

    conflitos = "".join(f"""<div class="row" style="padding:8px 12px;border-bottom:0.5px solid #e6e6e3;{"background:#e8f0fb;" if s else ""}">
  {ico(i, 13, "#56585c")}<div style="flex:1;display:flex;flex-direction:column;gap:1px;min-width:0"><b style="font-weight:500;font-size:12px" class="trunc">{n}</b><span class="sub">{d}</span></div>{e}</div>"""
                        for i, n, d, e, s in [
                            ("wave-sine", "ENT_MARTA_03 · transcrição", "6 falas diferem", '<span class="pill p-info">revisando</span>', True),
                            ("file-description", "ENT_MARTA_03 · decupagem 10:12–10:14", "enquadramento: close × médio", '<span class="pill p-warn">a decidir</span>', False),
                            ("wave-sine", "ENT_MARTA_02 · transcrição", "receitas diferentes, texto igual", '<span class="pill p-ok">' + ico("check", 10) + ' fica a mais nova</span>', False)])
    centro = f"""
<div class="toolbar">
  <div class="crumb">{ico("git-merge", 14, "#56585c")}<span class="c">Somar</span> Entrevistas Personagem E <span class="pill p-local">local</span> {ico("arrow-right", 12, "#9a9c9f")} Acervo Ciclo <span class="pill p-info">remoto</span></div>
  <span class="tbtn">Cancelar</span><span class="tbtn accent">{ico("git-merge", 12)} Somar · 3 conflitos decididos</span>
</div>
<div class="page">
  <div style="display:grid;grid-template-columns:repeat(5, minmax(0, 1fr));gap:12px">
    <div class="box" style="padding:10px 12px"><span class="label">Novas</span><div class="h2">29</div><span class="sub">mídias entram como estão</span></div>
    <div class="box" style="padding:10px 12px"><span class="label">Fundem</span><div class="h2">9</div><span class="sub">mesma mídia, sem conflito</span></div>
    <div class="box" style="padding:10px 12px;border-color:#378add"><span class="label" style="color:#185fa5">Conflitos</span><div class="h2">3</div><span class="sub">você escolhe o que fica</span></div>
    <div class="box" style="padding:10px 12px"><span class="label">Anotações</span><div class="h2">57</div><span class="sub">somam, nenhuma se perde</span></div>
    <div class="box" style="padding:10px 12px"><span class="label">Entidades</span><div class="h2">4</div><span class="sub">2 já existiam · unidas</span></div>
  </div>
  <div style="display:flex;gap:14px;flex:1;min-height:0">
    <div class="box" style="width:300px;flex:none;overflow:hidden"><div class="boxh"><span class="ptitle" style="font-size:12px">Conflitos</span></div>{conflitos}</div>
    <div style="flex:1;display:flex;flex-direction:column;gap:12px;min-width:0">
      <div class="row"><b style="font-weight:600">ENT_MARTA_03 · transcrição</b><span class="sub">fala 214 de 612 · 1 de 6 diferenças</span><div style="flex:1"></div>
        <span class="tbtn">{ico("arrow-left", 12)}</span><span class="tbtn">{ico("arrow-right", 12)}</span></div>
      <div style="display:flex;gap:12px">{lado("Banco local", '<span class="pill p-local">Entrevistas Personagem E</span>', *esq, False)}{lado("Já no remoto", '<span class="pill p-info">Acervo Ciclo</span>', *dir_, True)}</div>
      <div class="box row" style="padding:10px 12px;gap:10px;background:#f5f5f3">{ico("history", 14, "#56585c")}<span class="p" style="flex:1">A versão que não ficar vai para o histórico da mídia. As 4 anotações feitas à mão no banco local entram de qualquer jeito, presas aos seus timecodes.</span></div>
    </div>
  </div>
</div>"""
    conversa = chat(
        me("qual transcrição é melhor na marta 03?")
        + ai("<p>A do remoto: é do Whisper large, foi revisada pelo Montador A e acerta “segundo andar” onde a sua diz “segundo ano”. Das 6 diferenças, a do remoto está certa em 5.</p>",
             "<p>A exceção é a fala 388: a sua pegou um nome próprio (“Personagem E”) que a outra escreveu “Personagem E”. Posso deixar a do remoto e corrigir só essa palavra.</p>"))
    return doc(janela("bancos", conversa, centro))



# ---------------------------------------------------------------- canvas

TELAS = [
    # página, arquivo, título, função, nota
    ("page-1", "Main", "1 · Lista com árvore", tela_main,
     "A lista É a árvore (estrutura da lista do Premiere): rótulo de cor antes do nome (laranja nas pastas, pode ficar vazio), pastas que abrem no lugar, e colunas redimensionáveis — a alça azul entre Duração e TC mostra a borda sendo puxada. Clique no cabeçalho ordena; de novo, inverte. Duas buscas: o filtro de metadados, simples, e a busca inteligente, que responde na própria lista. Arrastar uma pasta da lista para a conversa recorta a busca nela."),
    ("page-1", "BuscaInteligente", "2 · Busca inteligente na lista", tela_busca_inteligente,
     "Sem ir ao chat: a árvore se reduz às pastas e mídias que casam, e cada mídia abre os momentos achados (TC, o trecho, a camada que achou). A faixa diz em quanto do banco a busca procurou. Ordenado por TC início."),
    ("page-1", "Cobertura", "3 · Busca inteligente sem resultado", tela_cobertura,
     "Nada achado com a busca por frase alcançando 9% do banco: a tela diz isso, diz onde a etapa roda e quanto falta."),
    ("page-1", "Familia", "4 · Família da mídia (+ vínculo)", tela_familia,
     "Original, proxy e transcode gerenciado do Avid. Cada membro diz COMO foi ligado (nome, pasta, comparação 1:1) e se está confirmado ou inferido. Embaixo à direita, o lugar reservado para o som direto casado (futuro)."),
    ("page-1", "Entidades", "5 · Entidades", tela_entidades,
     "Personagens, pessoas, locais, objetos e bordões por produção. Aparição vem de roteiro ancorado, claquete ou anotação; as inferidas esperam confirmação."),
    ("page-1", "LevarAoNLE", "6 · Levar ao NLE", tela_nle,
     "Quatro destinos. Escolher qual membro da família vai, como organizar, o que acompanha. O que está offline fica de fora — dito antes de gerar."),
    ("page-1", "Vazio", "7 · Banco novo", tela_vazio,
     "Banco local recém-criado. Quatro portas: observar pasta, Avid MediaFiles (à parte), arquivos soltos, somar outro banco."),
    ("page-2", "Ingestao", "8 · Ingestão e fila", tela_ingestao,
     "Pastas observadas com etapas por pasta e porta de entrada. Fila persistente dizendo em que máquina roda cada etapa; o perfil desta máquina e o que foi pulado aqui."),
    ("page-2", "Reconectar", "9 · Reconectar", tela_reconectar,
     "Guiado pelo usuário: aponta uma pasta, o conteúdo decide sozinho (188), nome/TC/duração só sugerem (21). Variação achada não é a mídia perdida — vai para a família."),
    ("page-3", "Bancos", "10 · Bancos local e remoto", tela_bancos,
     "Mesmo formato, dois modos. Local: pasta sem amarras. Remoto: servidor com permissões. Somar local → remoto; exportar remoto → local."),
    ("page-3", "Permissoes", "11 · Usuários e permissões", tela_permissoes,
     "Quatro papéis cumulativos, por pessoa, e o registro do que cada um fez — inclusive o que foi recusado. Como o banco sabe quem é quem ainda está por decidir no spec."),
    ("page-3", "Somar", "12 · Somar bancos", tela_somar,
     "O que entra, o que funde, o que conflita. Conflito lado a lado com a procedência de cada versão; a que perde vai para o histórico, anotação manual sempre soma."),
]


def main():
    artboards, notas = [], []
    por_pagina = {}
    for pagina, nome, titulo, funcao, nota in TELAS:
        (DEST / f"{nome}.dc.html").write_text(funcao())
        i = por_pagina.get(pagina, 0)
        por_pagina[pagina] = i + 1
        col, lin = i % 4, i // 4
        x, y = col * (W + 120), lin * (H + 340)
        artboards.append({"file": f"{nome}.dc.html", "title": titulo, "x": x, "y": y, "w": W, "h": H, "page": pagina})
        notas.append({"id": f"nota-{nome.lower()}", "x": x, "y": y + H + 36, "w": 900, "text": nota, "page": pagina})
    canvas = {
        "pages": [{"id": "page-1", "name": "Mídias"}, {"id": "page-2", "name": "Ingestão e reconectar"},
                  {"id": "page-3", "name": "Bancos"}],
        "artboards": artboards,
        "annotations": notas,
        "launch": {"view": "canvas", "page": "page-1"},
    }
    (DEST / "canvas.json").write_text(json.dumps(canvas, ensure_ascii=False, indent=2))
    print(f"{len(artboards)} pranchas")


if __name__ == "__main__":
    main()
