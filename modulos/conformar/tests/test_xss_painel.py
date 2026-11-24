r"""O escape do painel — a fronteira entre "nome de arquivo" e "HTML".

⚠️⚠️ **O nome de um arquivo de mídia é ENTRADA DE TERCEIRO.** O acervo vive em storage
compartilhado de produção: quem nomeia não é quem executa o plugin. E o painel monta HTML
com esses nomes, inclusive **dentro de atributos** (`data-arquivo="…"`).

O defeito que este teste trava: `textContent → innerHTML` escapa `&`, `<` e `>` e **não
escapa aspas**. Um arquivo chamado `a".onerror="alert(1)` fechava o atributo e injetava um
handler. ⚠️ E não é hipótese: no **macOS aspas são LEGAIS em nome de arquivo** (no Windows
não), e o painel roda nos dois.

Guia de Desenvolvimento Seguro da Emissora, §6 (XSS): sanitizar entrada **e saída**.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PAINEL_JS = RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.js"
PAINEL_HTML = RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.html"

# (entrada, o que NÃO pode sobreviver ao escape)
PERIGOSOS = [
    ('a".onerror="alert(1)', '"'),
    ("a'.onerror='alert(1)", "'"),
    ('<img src=x onerror=alert(1)>', "<"),
    ('" autofocus onfocus="alert(1)', '"'),
    ("</script><script>alert(1)</script>", "<"),
    ("javascript:alert(1)", None),          # inofensivo aqui, mas não pode sumir o texto
]


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<50} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    # ⚠️ As checagens que NÃO dependem do node vêm PRIMEIRO, e é de propósito: elas antes
    # ficavam depois do `return 0` do "PULADO", então numa máquina sem node o teste saía
    # verde sem executar uma única asserção — e o `publish.py` trata saída 0 como sucesso.
    # Um portão que só falha onde já se sabia que ele passa não é portão.
    print("── as defesas de cabeçalho e de marcação ────────────────────")
    servidor = (RAIZ / "plugins" / "media-composer" / "servico" / "api"
                / "servidor.py").read_text(encoding="utf-8")
    for cabecalho in ("X-Content-Type-Options", "X-Frame-Options",
                      "Content-Security-Policy"):
        ok(f"{cabecalho} é enviado", cabecalho in servidor, True)
    # ⚠️ A CSP só vale se a página não tiver script/estilo embutido — senão alguém
    # afrouxa a diretiva para a página voltar a funcionar, e a defesa vira enfeite.
    html = PAINEL_HTML.read_text(encoding="utf-8")
    ok("a UI não tem <script> embutido", "<script>" not in html, True)
    ok("nem atributo style=", 'style="' not in html, True)

    # ⚠️ O escape é a defesa de verdade; sem o node dá para conferir ao menos que ele
    # ainda trata ASPAS — que é o defeito que este arquivo existe para travar.
    fonte = PAINEL_JS.read_text(encoding="utf-8")
    i = fonte.find("function escapar")
    if i < 0:
        print("FALHA: não achei `escapar` em painel.js")
        return 1
    fim = re.search(r"\n\}\n", fonte[i:])
    if fim is None:
        # Falha legível em vez de `AttributeError` sobre `NoneType`: quem lê o vermelho
        # precisa saber QUAL invariante quebrou, não onde o teste tropeçou.
        print("FALHA: `escapar` não termina com `}` na coluna 0 — ajuste a extração")
        return 1
    trecho = fonte[i:i + fim.end()]
    ok("⭐ o escape ainda cobre aspas (a correção não regrediu)",
       "&quot;" in trecho and "&#39;" in trecho, True)

    if not shutil.which("node"):
        print("\n⚠️ `node` ausente: o comportamento do escape NÃO foi exercitado.")
        print(f"\n{casos - len(falhas)}/{casos} casos (parcial — instale o node)")
        for f in falhas:
            print(f"  ✗ {f}")
        # ⚠️ Sem node, o resultado é PARCIAL — mas o que rodou tem de valer. Falhar aqui
        # tornaria o teste impossível de rodar numa máquina limpa; passar calado foi o
        # defeito anterior. O aviso alto é o meio-termo honesto.
        return 1 if falhas else 0

    # `escapar` usa o DOM; um stub de `document` basta e mantém a função REAL sob teste.
    programa = """
const document = {
  createElement: () => ({
    set textContent(v) { this._t = String(v); },
    get innerHTML() {
      return this._t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    },
  }),
};
""" + trecho + """
const entrada = JSON.parse(require("fs").readFileSync(0, "utf8"));
process.stdout.write(JSON.stringify(entrada.map(escapar)));
"""
    r = subprocess.run(["node", "-e", programa],
                       input=json.dumps([e for e, _ in PERIGOSOS]),
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=60)
    if r.returncode != 0:
        print("FALHA ao rodar o node:", r.stderr)
        return 1
    saidas = json.loads(r.stdout)

    print("── nada perigoso sobrevive ao escape ────────────────────────")
    for (entrada, proibido), saida in zip(PERIGOSOS, saidas):
        rotulo = (entrada[:36] + "…") if len(entrada) > 37 else entrada
        if proibido is None:
            ok(f"texto preservado: {rotulo}", saida == entrada, True)
            continue
        ok(f"sem {proibido!r} cru: {rotulo}", proibido not in saida, True)

    print("\n── e o conteúdo não se perde (escapar ≠ apagar) ─────────────")
    ok("o nome continua legível",
       "alert(1)" in saidas[0] and "&quot;" in saidas[0], True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
