"""v2 das pranchas da aba Busca IA — as respostas do editor escritas no canvas.

(1) lista E grade, seletor no canto dos chips, zoom na grade · (2) clique seleciona, duplo
carrega na Source · (3) momentos com anterior/próximo trocando a miniatura · (4) só a frase ·
regra geral: nenhum texto mais escuro que #a3a3a3.
"""
import json
from pathlib import Path

DEST = Path(__file__).resolve().parent
#: O `canvas.json` que o editor SALVOU no canvas (notas e respostas dele), extraído da
#: versão 1789347017-83c1. As pranchas nascem daqui para as notas dele sobreviverem.
BASE = DEST / "salvo"

# Tinta: #ececec (principal) · #c4c4c4 (secundária) · #a3a3a3 (o piso — nada abaixo disto).
T1, T2, T3 = "#ececec", "#c4c4c4", "#a3a3a3"

CSS = f"""
body {{ margin: 0; background: #1a1a1a; }}
a {{ color: #4cc4b8; }} a:hover {{ color: #7fd8cf; }}
.painel {{ width: {{W}}px; height: 620px; overflow: hidden; display: flex; flex-direction: column;
  background: #232323; color: {T1}; font: 13px/1.55 -apple-system, "Segoe UI", Roboto, sans-serif;
  -webkit-font-smoothing: antialiased; }}
.topo {{ flex: none; display: flex; align-items: center; justify-content: space-between; gap: 8px;
  padding: 9px 12px; border-bottom: 1px solid #3d3d3d; background: #2b2b2b; }}
.marca {{ display: flex; align-items: center; gap: 8px; }}
.ponto {{ width: 7px; height: 7px; border-radius: 50%; background: #4cc4b8; }}
.topo h1 {{ margin: 0; font-size: 12px; font-weight: 600; letter-spacing: .3px; }}
.versao {{ color: {T3}; font-size: 10px; }}
.abas {{ flex: none; display: flex; align-items: stretch; gap: 2px; padding: 0 8px;
  border-bottom: 1px solid #3d3d3d; background: #2b2b2b; }}
.aba {{ border-bottom: 2px solid transparent; padding: 7px 10px 6px; font-size: 11.5px; color: {T3}; }}
.aba.ativa {{ color: {T1}; border-bottom-color: #4cc4b8; }}
.espaco {{ flex: 1 1 auto; }}
.engrenagem {{ padding: 5px 7px; color: {T3}; display: flex; align-items: center; }}
.tela {{ flex: 1 1 auto; overflow: hidden; padding: 12px 12px 18px; display: flex; flex-direction: column; gap: 8px; }}
.busca {{ display: flex; align-items: center; gap: 7px; background: #1d1d1d; border: 1px solid #3d3d3d;
  border-radius: 5px; padding: 6px 8px; }}
.busca.foco {{ border-color: #4cc4b8; }}
.busca .q {{ flex: 1 1 auto; min-width: 0; font-size: 12px; color: {T1}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.busca .q.vazio {{ color: {T3}; }}
.busca svg {{ flex: none; color: {T3}; }}
.dica {{ margin: -3px 0 0; font-size: 10.5px; color: {T3}; }}
.fontes {{ display: flex; flex-wrap: wrap; gap: 5px; align-items: center; }}
.chip {{ display: flex; align-items: center; gap: 5px; border: 1px solid #3d3d3d; border-radius: 11px;
  padding: 2px 8px; font-size: 10.5px; color: {T2}; }}
.chip b {{ font-size: 9.5px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em; color: {T3}; }}
.chip.ligado {{ border-color: #4cc4b8; background: #1b3634; color: {T1}; }}
.chip.ligado b {{ color: #4cc4b8; }}
.chip.desligado {{ border-style: dashed; color: {T3}; }}
.chip.avid {{ border-color: #4cc4b8; background: #1b3634; color: {T1}; padding: 2px 4px 2px 8px; }}
.chip.avid b {{ color: #4cc4b8; }}
.chip .x {{ color: {T3}; font-size: 13px; line-height: 1; padding: 0 3px; }}
.vista {{ margin-left: auto; display: flex; align-items: center; gap: 7px; }}
.seg {{ display: flex; border: 1px solid #3d3d3d; border-radius: 5px; overflow: hidden; }}
.seg span {{ display: flex; align-items: center; padding: 3px 6px; color: {T3}; }}
.seg span.on {{ background: #3a3a3a; color: {T1}; }}
.seg span + span {{ border-left: 1px solid #3d3d3d; }}
.zoom {{ display: flex; align-items: center; gap: 5px; color: {T3}; }}
.trilho {{ width: 52px; height: 3px; background: #3d3d3d; border-radius: 2px; position: relative; }}
.trilho i {{ position: absolute; left: 0; top: 0; height: 100%; background: #4cc4b8; border-radius: 2px; }}
.trilho b {{ position: absolute; top: -4px; width: 11px; height: 11px; margin-left: -5px; border-radius: 50%; background: {T1}; }}
.cobertura {{ font-size: 10.5px; color: {T3}; line-height: 1.45; }}
.cobertura em {{ font-style: normal; color: {T2}; }}
.resultados {{ display: flex; flex-direction: column; gap: 6px; }}
.res {{ display: flex; gap: 9px; background: #2b2b2b; border: 1px solid #333333; border-radius: 5px; padding: 7px 8px; }}
.res.sel {{ border-color: #4cc4b8; background: #1f302e; }}
.coluna-thumb {{ flex: none; display: flex; flex-direction: column; gap: 4px; width: 104px; }}
.thumb {{ flex: none; width: 104px; height: 58px; border-radius: 3px; position: relative; overflow: hidden; background: #111; }}
.thumb svg {{ display: block; }}
.tc {{ position: absolute; left: 3px; bottom: 3px; font: 9.5px/1 ui-monospace, "Cascadia Mono", Consolas, monospace;
  color: {T1}; background: rgba(0,0,0,.66); padding: 2px 3px; border-radius: 2px; }}
.corpo {{ flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; gap: 3px; }}
.linha1 {{ display: flex; align-items: baseline; gap: 6px; }}
.nome {{ flex: 1 1 auto; min-width: 0; font-size: 11.5px; color: {T1}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.especie {{ flex: none; font-size: 9.5px; text-transform: uppercase; letter-spacing: .05em; color: {T3}; }}
.bin {{ font-size: 10px; color: {T3}; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
.porque {{ display: flex; flex-wrap: wrap; gap: 4px; }}
.motivo {{ display: flex; align-items: center; gap: 4px; font-size: 10px; color: {T2};
  border: 1px solid #3d3d3d; border-radius: 9px; padding: 0 6px 0 5px; }}
.motivo svg {{ color: {T3}; }}
.trecho {{ font-size: 10.5px; color: {T2}; line-height: 1.4; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; }}
.trecho mark {{ background: none; color: {T1}; font-weight: 600; text-decoration: underline; text-decoration-color: #4cc4b8; text-underline-offset: 2px; }}
.mais {{ font-size: 10px; color: {T3}; }}
.momentos {{ display: flex; align-items: center; justify-content: space-between; gap: 4px; font-size: 10px; color: {T2};
  font-variant-numeric: tabular-nums; }}
.passo {{ display: flex; align-items: center; justify-content: center; width: 22px; height: 18px;
  border: 1px solid #3d3d3d; border-radius: 4px; color: {T1}; background: #343434; }}
.passo.off {{ color: {T3}; background: transparent; border-style: dashed; }}
.rodape {{ display: flex; align-items: center; gap: 8px; margin-top: 3px; }}
.dica-clique {{ flex: 1 1 auto; font-size: 10px; color: {T3}; }}
.botao {{ background: #343434; border: 1px solid #3d3d3d; border-radius: 5px; padding: 4px 8px; font-size: 10.5px; color: {T1}; white-space: nowrap; }}
.botao.forte {{ border-color: #4cc4b8; color: #4cc4b8; background: transparent; }}
.aviso-asr {{ font-size: 10.5px; color: {T3}; border-top: 1px solid #333333; padding-top: 7px; line-height: 1.45; }}
.ocorr {{ display: flex; flex-direction: column; gap: 1px; margin-top: 2px; }}
.oc {{ display: flex; gap: 7px; font-size: 10.5px; color: {T2}; line-height: 1.4; padding: 1px 4px; margin: 0 -4px; border-radius: 3px; }}
.oc.atual {{ background: #2c4744; color: {T1}; }}
.oc code {{ flex: none; font: 10px/1.4 ui-monospace, "Cascadia Mono", Consolas, monospace; color: {T3}; }}
.oc.atual code {{ color: #4cc4b8; }}
.vazio {{ font-size: 11.5px; color: {T2}; line-height: 1.5; margin: 6px 0 0; }}
.vazio b {{ color: {T1}; font-weight: 600; }}
.progresso {{ height: 3px; background: #343434; border-radius: 2px; overflow: hidden; }}
.progresso i {{ display: block; height: 100%; background: #4cc4b8; }}
.andamento {{ display: flex; align-items: center; gap: 8px; font-size: 10.5px; color: {T3}; }}
.andamento span {{ flex: 1 1 auto; }}
.acoes {{ display: flex; gap: 6px; margin-top: 3px; }}
.grade {{ display: grid; gap: 7px; }}
.cel {{ display: flex; flex-direction: column; gap: 3px; min-width: 0; }}
.cel .thumb {{ width: 100%; }}
.cel .nome {{ font-size: 10.5px; }}
.cel .icones {{ position: absolute; right: 3px; top: 3px; display: flex; gap: 2px; }}
.cel .icones i {{ display: flex; background: rgba(0,0,0,.66); border-radius: 2px; padding: 2px; color: {T1}; }}
.cel.sel .thumb {{ outline: 2px solid #4cc4b8; outline-offset: -2px; }}
.cel .setas {{ position: absolute; left: 0; right: 0; top: 50%; margin-top: -9px; display: flex; justify-content: space-between; padding: 0 3px; }}
.cel .setas i {{ display: flex; align-items: center; justify-content: center; width: 18px; height: 18px; border-radius: 50%; background: rgba(0,0,0,.66); color: {T1}; }}
.cel .conta {{ position: absolute; right: 3px; bottom: 3px; font: 9.5px/1 ui-monospace, "Cascadia Mono", Consolas, monospace;
  color: {T1}; background: rgba(0,0,0,.66); padding: 2px 3px; border-radius: 2px; }}
"""

ENGRENAGEM = """<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"></path></svg>"""


def ico(nome, t=11):
    p = {
        "lupa": '<circle cx="11" cy="11" r="7"></circle><path d="M20 20l-3.5-3.5"></path>',
        "imagem": '<rect x="3" y="5" width="18" height="14" rx="2"></rect><path d="M3 16l5-5 4 4 3-3 6 6"></path>',
        "fala": '<path d="M4 10v4M8 7v10M12 4v16M16 8v8M20 11v2"></path>',
        "texto": '<path d="M5 6h14M5 11h14M5 16h9"></path>',
        "lista": '<path d="M9 6h11M9 12h11M9 18h11"></path><circle cx="4.5" cy="6" r="1"></circle><circle cx="4.5" cy="12" r="1"></circle><circle cx="4.5" cy="18" r="1"></circle>',
        "grade": '<rect x="4" y="4" width="7" height="7" rx="1"></rect><rect x="13" y="4" width="7" height="7" rx="1"></rect><rect x="4" y="13" width="7" height="7" rx="1"></rect><rect x="13" y="13" width="7" height="7" rx="1"></rect>',
        "menor": '<rect x="7" y="7" width="10" height="10" rx="1.5"></rect>',
        "maior": '<rect x="3" y="3" width="18" height="18" rx="2"></rect>',
        "esq": '<path d="M15 5l-7 7 7 7"></path>',
        "dir": '<path d="M9 5l7 7-7 7"></path>',
    }[nome]
    return (f'<svg viewBox="0 0 24 24" width="{t}" height="{t}" fill="none" stroke="currentColor" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round">{p}</svg>')


# Miniaturas GENÉRICAS — nunca quadro de cliente (o canvas fica online).
CENAS = {
    "noite": ('#1c1712', '<rect x="0" y="38" width="104" height="20" fill="#2a2119"></rect><circle cx="80" cy="16" r="9" fill="#6b4a26" opacity=".55"></circle><ellipse cx="44" cy="34" rx="15" ry="19" fill="#4a3526"></ellipse><circle cx="44" cy="20" r="9" fill="#7a5a44"></circle>'),
    "noite-b": ('#1a1511', '<rect x="0" y="40" width="104" height="18" fill="#2a2119"></rect><circle cx="22" cy="14" r="8" fill="#6b4a26" opacity=".5"></circle><ellipse cx="62" cy="36" rx="19" ry="21" fill="#4a3526"></ellipse><circle cx="62" cy="19" r="11" fill="#7a5a44"></circle>'),
    "noite2": ('#15130f', '<rect x="64" y="8" width="26" height="18" fill="#3a2d1e"></rect><ellipse cx="34" cy="40" rx="20" ry="22" fill="#3d2c22"></ellipse><circle cx="34" cy="22" r="10" fill="#6e513e"></circle>'),
    "dia": ('#8fa8b5', '<rect x="0" y="34" width="104" height="24" fill="#5f7a4d"></rect><rect x="12" y="20" width="18" height="20" fill="#4a5f3b"></rect><ellipse cx="62" cy="40" rx="9" ry="14" fill="#394236"></ellipse><circle cx="62" cy="27" r="5" fill="#8a6f5c"></circle>'),
    "interior": ('#5d5347', '<rect x="0" y="40" width="104" height="18" fill="#473f36"></rect><rect x="8" y="10" width="22" height="16" fill="#7c6f5f"></rect><ellipse cx="70" cy="38" rx="17" ry="20" fill="#3b332c"></ellipse><circle cx="70" cy="22" r="8" fill="#9a806c"></circle>'),
    "geral": ('#6f8796', '<rect x="0" y="30" width="104" height="28" fill="#50614c"></rect><rect x="30" y="18" width="40" height="18" fill="#8b8277"></rect><rect x="44" y="26" width="10" height="10" fill="#3d3a35"></rect>'),
    "detalhe": ('#2b2622', '<rect x="18" y="14" width="70" height="34" rx="4" fill="#5a4d40"></rect><circle cx="52" cy="31" r="10" fill="#8a7864"></circle>'),
}


def thumb(cena, tc, w=104, h=58, extra=""):
    fundo, formas = CENAS[cena]
    estilo = f' style="height:{h}px"' if w == "100%" else ""
    largura = "100%" if w == "100%" else str(w)
    return (f'<div class="thumb"{estilo}><svg viewBox="0 0 104 58" width="{largura}" height="{h}" preserveAspectRatio="xMidYMid slice">'
            f'<rect width="104" height="58" fill="{fundo}"></rect>{formas}</svg>'
            f'{extra}<span class="tc">{tc}</span></div>')


def motivo(tipo, texto):
    return f'<span class="motivo">{ico(tipo, 10)}{texto}</span>'


def momentos(atual, total):
    """⭐ Decisão do editor: anterior/próximo trocam SÓ a miniatura ao lado (e o TC)."""
    esq = "passo off" if atual == 1 else "passo"
    dir_ = "passo off" if atual == total else "passo"
    return (f'<div class="momentos"><span class="{esq}">{ico("esq", 10)}</span>'
            f'<span>{atual} de {total}</span><span class="{dir_}">{ico("dir", 10)}</span></div>')


def res(cena, tc, nome, especie, bin_, motivos, trecho="", mom=None, sel=False, extra="", nota=""):
    m = "".join(motivo(t, x) for t, x in motivos)
    coluna = thumb(cena, tc) + (momentos(*mom) if mom else "")
    rodape = ('<div class="rodape"><span class="dica-clique">duplo clique abre na Source neste TC</span>'
              '<span class="botao">Levar ao chat</span></div>') if sel else ""
    return f"""<div class="res{' sel' if sel else ''}"><div class="coluna-thumb">{coluna}</div><div class="corpo">
<div class="linha1"><span class="nome">{nome}</span><span class="especie">{especie}</span></div>
<div class="bin">{bin_}</div><div class="porque">{m}</div>
{f'<div class="trecho">{trecho}</div>' if trecho else ''}{extra}
{f'<div class="mais">{nota}</div>' if nota else ''}{rodape}
</div></div>"""


def painel(conteudo):
    return f"""<div class="painel">
<div class="topo"><div class="marca"><span class="ponto"></span><h1>Ciclo Assist</h1></div><span class="versao">0.3.0</span></div>
<div class="abas"><span class="aba">Claude</span><span class="aba ativa">Busca IA</span><span class="aba">Vetores</span><span class="espaco"></span><span class="engrenagem">{ENGRENAGEM}</span></div>
<div class="tela">{conteudo}</div></div>"""


def busca(q, vazio=False, foco=False):
    return (f'<div class="busca{" foco" if foco else ""}">{ico("lupa", 13)}'
            f'<span class="q{" vazio" if vazio else ""}">{q}</span></div>')


def vista(modo, zoom=0.5):
    """O seletor lista/grade, onde o editor o desenhou; o zoom só existe na grade."""
    z = ""
    if modo == "grade":
        pct = int(zoom * 100)
        z = (f'<span class="zoom">{ico("menor", 10)}<span class="trilho"><i style="width:{pct}%"></i>'
             f'<b style="left:{pct}%"></b></span>{ico("maior", 12)}</span>')
    return (f'<span class="vista">{z}<span class="seg">'
            f'<span class="{"on" if modo == "lista" else ""}" title="Lista">{ico("lista", 12)}</span>'
            f'<span class="{"on" if modo == "grade" else ""}" title="Grade">{ico("grade", 12)}</span>'
            f'</span></span>')


def fontes(img="ligado", fala="ligado", dec="ligado", n=("165", "17", "172"), modo="lista", zoom=0.5, curto=False):
    r = (lambda s: s[0]) if curto else (lambda s: s)
    return (f'<div class="fontes"><span class="chip {img}"><b>{r("Imagem") if not curto else "Img"}</b>{n[0]}</span>'
            f'<span class="chip {fala}"><b>Fala</b>{n[1]}</span>'
            f'<span class="chip {dec}"><b>{"Decup" if curto else "Decupagem"}</b>{n[2]}</span>'
            f'{vista(modo, zoom)}</div>')


def arquivo(nome, corpo, w=440):
    html = f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <script src="./support.js"></script>
</head>
<body>
<x-dc>
<helmet>
  <style>{CSS.replace('{W}', str(w))}</style>
</helmet>
{painel(corpo)}
</x-dc>
</body>
</html>
"""
    (DEST / nome).write_text(html, encoding="utf-8")


COB = ('<div class="cobertura">Busca nas <em>307 mídias das bins do projeto aberto</em> (Trash fora). '
       'O número em cada fonte é quanto já foi indexado.</div>')

# 1 — frase, em lista
arquivo("Main.dc.html", busca("close noturno no consultório", foco=True) + fontes() + COB
    + '<div class="resultados">'
    + res("noite", "01:02:14:08", "C07 T03 PERSONAGEM-F CLOSE", "subclipe", "CENAS › C07",
          [("imagem", "imagem forte"), ("texto", "close · noite · interior")],
          "Close de uma mulher de blusa vermelha, luz baixa e quente; quadros ao fundo, abajur aceso.",
          mom=(1, 3), sel=True)
    + res("noite2", "01:04:51:12", "C07 T05 PERSONAGEM-F OMBRO", "subclipe", "CENAS › C07",
          [("imagem", "imagem forte")], nota="sem decupagem — achado só pela imagem")
    + res("interior", "00:12:03:00", "A001_C009", "master", "DIÁRIA 01 › CAM A",
          [("texto", "close · interior"), ("imagem", "imagem média")],
          "Mulher sentada à mesa conversa com alguém fora de quadro; abajur ao fundo.", mom=(1, 2))
    + '</div>')

# 2 — fala: o momento atual é a ocorrência destacada
FALA_EXTRA = ('<div class="ocorr">'
    '<div class="oc"><code>01:02:31:04</code><span>— Então <mark>sobe comigo</mark>, a gente conversa lá em cima.</span></div>'
    '<div class="oc atual"><code>01:02:58:17</code><span>— Eu disse <mark>sobe comigo</mark>.</span></div></div>')
arquivo("Fala.dc.html", busca('"sobe comigo"', foco=True) + fontes(img="desligado", dec="desligado")
    + '<div class="cobertura">Entre aspas, as palavras nessa ordem. <em>17 mídias com fala transcrita</em> nas bins do projeto.</div>'
    + '<div class="resultados">'
    + res("noite-b", "01:02:58:17", "C07 T03 PERSONAGEM-F CLOSE", "subclipe", "CENAS › C07",
          [("fala", "2 vezes")], extra=FALA_EXTRA, mom=(2, 2), sel=True)
    + res("interior", "01:06:10:02", "C07 T07 MASTER", "subclipe", "CENAS › C07",
          [("fala", "1 vez · parecida")],
          "— Então <mark>sob comigo</mark>, a gente conversa…", nota="grafia do reconhecedor: “sob comigo”")
    + '</div>'
    + '<div class="aviso-asr">A busca acha a fala como o reconhecedor escreveu. Nome próprio e palavra rara podem vir trocados — por isso a grafia parecida também entra, marcada.</div>')

# 3 — parecidos (quadro arrastado): cada resultado é um plano, sem momentos
arquivo("Parecidos.dc.html",
    '<div class="busca foco">' + ico("lupa", 13) + '<span class="chip avid"><b>MC</b>C07 T03 · 01:02:14:08<span class="x">×</span></span><span class="q vazio">refinar com uma frase…</span></div>'
    + '<div class="dica">Parecidos com o quadro arrastado do Media Composer. O próprio plano fica fora.</div>'
    + fontes(fala="desligado", dec="desligado")
    + '<div class="resultados">'
    + res("noite2", "01:04:51:12", "C07 T05 PERSONAGEM-F OMBRO", "subclipe", "CENAS › C07", [("imagem", "muito parecido")], sel=True)
    + res("noite", "01:03:40:20", "C07 T04 PERSONAGEM-F CLOSE 2", "subclipe", "CENAS › C07", [("imagem", "muito parecido")])
    + res("interior", "00:12:03:00", "A001_C009", "master", "DIÁRIA 01 › CAM A", [("imagem", "parecido")])
    + '</div>')

# 4 — cobertura incompleta
arquivo("Cobertura.dc.html", busca("praia ao entardecer", foco=True) + fontes(n=("48", "17", "172"))
    + '<p class="vazio">Nada parecido com <b>praia ao entardecer</b> nas <b>48 mídias</b> com imagem indexada.</p>'
    + '<p class="vazio" style="margin-top:0">Ainda faltam <b>259 mídias</b> das bins deste projeto. Não dá para dizer que o material não tem — só que o que foi olhado não tem.</p>'
    + '<div class="acoes"><span class="botao forte">Indexar o que falta · ≈ 9 min neste computador</span></div>'
    + '<div style="height:10px"></div>'
    + '<div class="progresso"><i style="width:34%"></i></div>'
    + '<div class="andamento"><span>indexando imagem · 88 de 259 · A001_C044</span><span class="botao" style="flex:none">Parar</span></div>'
    + '<div class="cobertura">Roda no fundo, como na aba Vetores: dá para voltar ao chat e montar enquanto isso.</div>')


# 5 e 6 — grade, dois pontos do zoom. ⭐ Responsiva: o zoom define a LARGURA MÍNIMA da
#          miniatura e a grade põe quantas colunas couberem (auto-fill).
def cel(cena, tc, nome, icones, sel=False, mom=None, h=72):
    ic = '<span class="icones">' + "".join(f'<i>{ico(i, 9)}</i>' for i in icones) + '</span>'
    extra = ic
    if mom:
        extra += f'<span class="conta">{mom[0]}/{mom[1]}</span>'
        if sel:
            extra += f'<span class="setas"><i>{ico("esq", 10)}</i><i>{ico("dir", 10)}</i></span>'
    return (f'<div class="cel{" sel" if sel else ""}">{thumb(cena, tc, w="100%", h=h, extra=extra)}'
            f'<span class="nome">{nome}</span></div>')


CELULAS = [
    ("noite", "01:02:14:08", "C07 T03 PERSONAGEM-F CLOSE", ["imagem", "texto"], True, (1, 3)),
    ("noite2", "01:04:51:12", "C07 T05 PERSONAGEM-F OMBRO", ["imagem"], False, None),
    ("interior", "00:12:03:00", "A001_C009", ["texto", "imagem"], False, (1, 2)),
    ("noite-b", "01:03:40:20", "C07 T04 PERSONAGEM-F CLOSE 2", ["imagem"], False, None),
    ("detalhe", "01:05:02:03", "C07 INSERT ABAJUR", ["texto"], False, None),
    ("interior", "00:31:22:10", "A002_C014", ["imagem"], False, None),
    ("geral", "00:02:10:00", "A001_C002", ["imagem"], False, None),
    ("noite", "01:07:12:15", "C07 T08 PERSONAGEM-F CLOSE", ["imagem"], False, (1, 2)),
    ("detalhe", "01:05:30:00", "C07 INSERT RETRATO", ["imagem"], False, None),
]

DETALHE_SEL = ('<div class="res sel" style="margin-top:2px"><div class="corpo"><div class="linha1"><span class="nome">C07 T03 PERSONAGEM-F CLOSE</span>'
    '<span class="especie">subclipe</span></div><div class="bin">CENAS › C07 · 01:02:14:08 · momento 1 de 3</div>'
    '<div class="trecho">Close de uma mulher de blusa vermelha, luz baixa e quente; quadros ao fundo, abajur aceso.</div>'
    '<div class="rodape"><span class="dica-clique">duplo clique abre na Source neste TC</span><span class="botao">Levar ao chat</span></div></div></div>')


def grade(minimo, h, quantas):
    celulas = "".join(cel(*c, h=h) for c in CELULAS[:quantas])
    return (f'<div class="grade" style="grid-template-columns: repeat(auto-fill, minmax({minimo}px, 1fr))">'
            f'{celulas}</div>')


arquivo("Grade.dc.html", busca("close noturno no consultório", foco=True)
    + fontes(modo="grade", zoom=0.3) + grade(118, 70, 9) + DETALHE_SEL)
arquivo("GradeZoom.dc.html", busca("close noturno no consultório", foco=True)
    + fontes(modo="grade", zoom=0.8) + grade(190, 112, 4) + DETALHE_SEL)

# 7 — 340 px: chips encurtados para o seletor caber na mesma linha
arquivo("Estreito.dc.html", busca("close noturno no consultório", foco=True) + fontes(curto=True)
    + '<div class="cobertura">307 mídias das bins do projeto · Trash fora</div>'
    + '<div class="resultados">'
    + res("noite", "01:02:14:08", "C07 T03 PERSONAGEM-F CLOSE", "subclipe", "CENAS › C07",
          [("imagem", "forte"), ("texto", "close · noite")],
          "Close de uma mulher de blusa vermelha, luz baixa e quente.", mom=(1, 3), sel=True)
    + res("noite2", "01:04:51:12", "C07 T05 PERSONAGEM-F OMBRO", "subclipe", "CENAS › C07", [("imagem", "forte")])
    + '</div>', w=340)

# canvas.json: parte do que o editor SALVOU (notas dele intactas), com as pranchas novas.
salvo = json.loads((BASE / "canvas.json").read_text(encoding="utf-8"))
salvo["artboards"] = [
    {"file": "Main.dc.html", "title": "1 · Frase, em lista", "x": 0, "y": 0, "w": 440, "h": 620},
    {"file": "Fala.dc.html", "title": "2 · Fala: palavra ou frase", "x": 520, "y": 0, "w": 440, "h": 620},
    {"file": "Parecidos.dc.html", "title": "3 · Quadro arrastado do Avid", "x": 1040, "y": 0, "w": 440, "h": 620},
    {"file": "Grade.dc.html", "title": "5 · Grade, zoom pequeno", "x": 0, "y": 760, "w": 440, "h": 620},
    {"file": "GradeZoom.dc.html", "title": "6 · Grade, zoom grande", "x": 520, "y": 760, "w": 440, "h": 620},
    {"file": "Cobertura.dc.html", "title": "4 · Nada achado, índice incompleto", "x": 1040, "y": 760, "w": 440, "h": 620},
    {"file": "Estreito.dc.html", "title": "7 · Lista em 340 px", "x": 0, "y": 1520, "w": 340, "h": 620},
]
ids = {n["id"] for n in salvo.get("annotations", [])}
if "v2" not in ids:
    salvo["annotations"].append({
        "id": "v2", "x": 440, "y": 1520, "w": 340, "text":
        "v2 — o que mudou com as respostas:\n\n"
        "• Seletor lista / grade no canto dos chips, onde o retângulo foi desenhado.\n"
        "• Grade responsiva: o zoom define o tamanho MÍNIMO da miniatura e cabem quantas colunas der (telas 5 e 6).\n"
        "• Clique seleciona (borda verde-água); duplo clique abre na Source no TC do momento.\n"
        "• Momentos: ‹ 1 de 3 › embaixo da miniatura troca só a imagem e o TC. Na grade, as setas aparecem na selecionada.\n"
        "• Sem filtros de campo: só a frase.\n"
        "• Texto: principal #ececec · secundário #c4c4c4 · piso #a3a3a3."})
(DEST / "canvas.json").write_text(json.dumps(salvo, ensure_ascii=False, indent=1), encoding="utf-8")
print("ok")
