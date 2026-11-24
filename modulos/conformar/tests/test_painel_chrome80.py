"""O painel é UM só para todos os NLEs — e o navegador mais velho deles é o do Resolve.

Rodar:

    .venv-win/Scripts/python tests/test_painel_chrome80.py

Medido em 2026-09-25 (banco de NLEs, `plugins/resolve-scripting/workflow-integration.md` §5):
o Resolve 19 hospeda o painel no Electron 8.0.1 / **Chrome 80**. Lá, o que é mais novo que o
Chrome 80 some CALADO — a declaração CSS é descartada, e o painel fica errado sem erro nenhum
(o banco já registrou a mesma armadilha no CEP do Premiere com `color-mix`). Este teste é a
régua: o painel.css e o painel.js não usam o que o Chrome 80 não tem, e todo flex com `gap`
tem a reserva de margens de `html.sem-flex-gap`.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

UI = Path(__file__).resolve().parent.parent / "plugins" / "media-composer" / "servico" / "ui"

#: CSS mais novo que o Chrome 80 → (o que é, desde quando).
CSS_PROIBIDO = {
    r"color-mix\(": "color-mix (Chrome 111)",
    r"(?<![\w-])inset\s*:": "inset (Chrome 87)",
    r":has\(": ":has (Chrome 105)",
    r":is\(|:where\(": ":is/:where (Chrome 88)",
    r"aspect-ratio\s*:": "aspect-ratio (Chrome 88)",
    r"@container": "container queries (Chrome 105)",
    r"\b\d*\.?\d+(dvh|svh|lvh)\b": "dvh/svh (Chrome 108)",
}
#: JS mais novo que o Chrome 80.
JS_PROIBIDO = {
    r"\.replaceAll\(": "replaceAll (Chrome 85)",
    r"\|\|=|&&=|\?\?=": "atribuição lógica (Chrome 85)",
    r"\.at\(": ".at() (Chrome 92)",
    r"structuredClone\(": "structuredClone (Chrome 98)",
    r"Object\.hasOwn\(": "Object.hasOwn (Chrome 93)",
    r"\.findLast\(|\.toSorted\(|\.toReversed\(": "arrays novos (Chrome 97+)",
    r"this\.#\w|\n[ \t]+#\w+\s*[;=(]":"campo privado de classe (Chrome 84)",
}


def _sem_comentarios_css(css: str) -> str:
    return re.sub(r"/\*.*?\*/", "", css, flags=re.DOTALL)


def _sem_comentarios_js(js: str) -> str:
    js = re.sub(r"/\*.*?\*/", "", js, flags=re.DOTALL)
    return re.sub(r"(?m)^\s*//.*$|(?<=[;{}),])\s*//.*$", "", js)


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 56 else f"{repr(obtido)[:53]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<64} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    css = _sem_comentarios_css((UI / "painel.css").read_text(encoding="utf-8"))
    js = _sem_comentarios_js((UI / "painel.js").read_text(encoding="utf-8"))

    print("── 1. nada mais novo que o Chrome 80 ──")
    for rx, nome in CSS_PROIBIDO.items():
        ok(f"painel.css sem {nome}", len(re.findall(rx, css)), 0)
    for rx, nome in JS_PROIBIDO.items():
        ok(f"painel.js sem {nome}", len(re.findall(rx, js)), 0)

    print("\n── 2. todo flex com gap tem a reserva de margens ──")
    reserva = set()
    for sel, _corpo in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        for s in sel.split(","):
            s = " ".join(s.split())
            m = re.match(r"html\.sem-flex-gap (.+?) > \* \+ \*$", s)
            if m:
                reserva.add(m.group(1))
    faltando = []
    for sel, corpo in re.findall(r"([^{}@]+)\{([^{}]*)\}", css):
        c = " ".join(corpo.split())
        e_flex = re.search(r"display\s*:\s*(inline-)?flex", c)
        tem_gap = re.search(r"(?<![\w-])gap\s*:", c)
        if not (e_flex and tem_gap):
            continue
        for s in sel.split(","):
            s = " ".join(s.split())
            if s and not s.startswith("html.sem-flex-gap") and s not in reserva:
                faltando.append(s)
    ok("flex com gap sem reserva em html.sem-flex-gap", faltando, [])
    ok("o painel.js liga a reserva quando falta gap em flex",
       "sem-flex-gap" in js and "row-gap" in js, True)

    print("\n── 3. o mesmo painel, cada NLE com o seu ──")
    html = (UI / "painel.html").read_text(encoding="utf-8")
    ok("o CSS esconde o que é de outro NLE (o Premiere recebe como o Resolve, 2026-10-19)",
       'body[data-nle="resolve"] [data-so="mc"]' in css
       and 'body[data-nle="premiere"] [data-so="mc"]' in css
       and 'body[data-nle="baselight"] [data-so="mc"]' in css
       and 'body:not([data-nle="resolve"]):not([data-nle="premiere"]):not([data-nle="baselight"]) [data-so="resolve"]'
       in css, True)
    # Três caminhos (organograma de 2026-09-25): o passo 1 é o MESMO nos dois NLEs; o relink
    # é só do Media Composer; o arquivo do Resolve (Carta, bin) só do Resolve; o Magic Link
    # (um bloco por canal) aparece nos dois.
    ok("o passo 1 é comum aos dois NLEs", '<div class="passo" id="passoOrigem">' in html, True)
    ok("o relink do Avid (passos 2 e 3) só aparece no Media Composer",
       'id="soRelink" data-so="mc"' in html, True)
    ok("o Magic Link de receber não é de um NLE só",
       bool(re.search(r'<div id="mlReceber"(?![^>]*data-so)', html)), True)
    # Organograma "Um painel, três NLEs" (2026-10-12): UMA caixa "Importar / relinkar" nos dois, com o botão
    # da sequência aberta — no Resolve, desde 2026-10-19, ele traz a timeline aberta para a conferência.
    ok("a caixa \"Importar / relinkar\" é comum aos dois NLEs",
       bool(re.search(r'<button data-modo="importar" class="on">Importar / relinkar</button>', html)), True)
    ok("\"Carregar a sequência aberta\" nos dois; no Resolve, ligado (a timeline aberta, 2026-10-19)",
       'id="btnSeqAberta">Carregar a sequência aberta' in html
       and 'id="rcBtnSeqAberta">Carregar a sequência aberta' in html, True)
    ok("a aba Daqui Pra Lá existe nos dois NLEs", '<button id="tabDaquiPraLa" role="tab">' in html, True)
    ok("o NLE vem de lista fechada (valor estranho vira 'mc')",
       bool(re.search(r'\["mc", "resolve", "premiere", "baselight"\]\.includes', js)), True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
