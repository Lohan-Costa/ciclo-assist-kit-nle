"""O contrato de progresso entre `media/indexer` e `relink` — travado por regressão.

Rodar:

    PYTHONPATH="motor;plugins/media-composer/servico" .venv-win/Scripts/python tests/test_progresso.py

## Por que este teste existe

O `index_folder` emite duas formas de payload, uma por fase; o `relink` lia **`done`** e
**`path`**, que não existem em nenhuma das duas. Não houve exceção: a barra ficava em
**0%** e o rótulo em **`meta`** (o fallback caindo no nome da fase) durante toda a
varredura — o editor via `0% meta` por minutos e a janela seguinte aparecia do nada.

⚠️ E o comentário no código **documentava o contrato errado**, o que prova que ele foi
escrito de memória em vez de conferido contra o emissor. Um teste que exercite as chaves
REAIS é a única coisa que impede isso de voltar numa renomeação.

⭐ Por isso a tradução saiu de dentro de `preparar`: função aninhada não se testa, e foi
justamente a falta de teste que deixou o contrato divergir sem ninguém notar.
"""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

from media import indexer  # noqa: E402
from relink import traduzir_progresso_do_indice as traduzir  # noqa: E402

# Os payloads REAIS, copiados do `index_folder` rodando contra um acervo de verdade
# (5 WAVs de som direto, 2026-08-16) — não inventados a partir do docstring.
SCAN = {"phase": "scan", "scanned": 5, "found": 5, "current": ""}
META = [
    {"phase": "meta", "i": 1, "total": 5, "indexed": 0,
     "current": r"E:\...\PRODUCAO-A - PRAIA 03-04-T001.WAV"},
    {"phase": "meta", "i": 3, "total": 5, "indexed": 2,
     "current": r"E:\...\PRODUCAO-A - CENA-PRAIA 03-04-T001.WAV"},
    {"phase": "meta", "i": 5, "total": 5, "indexed": 5, "current": ""},
]


def main() -> int:
    falhas: list[str] = []

    def checa(ok: bool, rotulo: str, detalhe: str = "") -> None:
        print(f"{'  ok  ' if ok else ' FALHA'} {rotulo}")
        if not ok:
            falhas.append(detalhe or rotulo)

    # ── 1) o emissor ainda emite as chaves que lemos ────────────────────────
    # Guarda contra renomeação: se `index_folder` trocar `i`/`total`/`current`, isto cai.
    # No artefato público não há docstring (`sanear.py`): ali a prova é o CÓDIGO do emissor.
    doc = inspect.getdoc(indexer.index_folder) or ""
    contrato = doc or inspect.getsource(indexer.index_folder)
    for chave in ('"phase"', '"scanned"', '"found"', '"i"', '"total"', '"current"'):
        checa(chave in contrato, f"o indexer ainda documenta {chave}",
              f"{chave} sumiu do contrato de index_folder — a tradução precisa mudar junto")
    if doc:
        checa('"done"' not in doc and '"path"' not in doc,
              "o indexer NÃO emite 'done'/'path' (as chaves do bug)")

    # ── 2) a fase de varredura é indeterminada, e diz algo útil ─────────────
    etapa, feito, total, det = traduzir(SCAN)
    checa(total == 0, f"scan não inventa total (veio {total})")
    checa("5" in det, f"scan mostra o que já viu (veio {det!r})")
    checa(etapa != "meta", f"o rótulo não é o nome da fase (veio {etapa!r})")

    # ── 3) ⭐ a fase de metadados PROGRIDE — o caso que o bug quebrava ──────
    pcts = []
    for info in META:
        etapa, feito, total, det = traduzir(info)
        checa(total == 5, f"total correto em i={info['i']} (veio {total})")
        checa(feito == info["i"], f"feito correto em i={info['i']} (veio {feito})")
        pcts.append(100 * feito // total if total else 0)
    checa(pcts == [20, 60, 100], f"a barra sobe 20→60→100 (veio {pcts})",
          f"a barra não progride: {pcts} — é exatamente o bug de 2026-08-16")
    checa(any(p > 0 for p in pcts), "algum evento passa de 0%",
          "todos os eventos deram 0% — a barra ficaria parada como no bug")

    # ── 4) o detalhe é o NOME do arquivo, não o caminho inteiro ────────────
    _e, _f, _t, det = traduzir(META[0])
    checa(det == "PRODUCAO-A - PRAIA 03-04-T001.WAV",
          f"mostra o nome do arquivo, não o caminho (veio {det!r})")
    _e, _f, _t, det = traduzir(META[2])
    checa(det == "", f"sem 'current', o detalhe fica vazio (veio {det!r})")

    total_casos = 7 + 3 + 8 + 2
    print(f"\n{total_casos - len(falhas)}/{total_casos} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
