"""O portão é a única tranca do serviço — então é o que mais merece teste.

Ele é função pura de propósito: dá para exercitar todas as combinações sem subir
servidor nenhum. Rodar:

    PYTHONPATH=plugins/media-composer/servico .venv/bin/python tests/test_portao.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "plugins/media-composer/servico"))

from api.portao import MAX_CORPO_BYTES, PORTA, portao  # noqa: E402

NOSSA_ORIGEM = f"http://127.0.0.1:{PORTA}"

# (nome, host, origin, sec_fetch_site, corpo_len, rota, deve_passar)
CASOS = [
    # ── o loader dentro do .avpi ─────────────────────────────────────────────
    ("loader bate em /health", "127.0.0.1:7823", "avpi://", None, None, "/health", True),
    ("loader com barra final", "127.0.0.1:7823", "avpi://", None, None, "/health", True),
    # A lista do loader é curta de propósito: só dizer que está vivo.
    ("loader NAO alcanca /mc/info", "127.0.0.1:7823", "avpi://", None, None, "/mc/info", False),
    ("loader NAO alcanca rota de trabalho", "127.0.0.1:7823", "avpi://", None, None, "/sequences", False),

    # ── a UI servida ─────────────────────────────────────────────────────────
    # ⭐ O caso que a primeira versão do Órbita errou: GET same-origin não manda Origin.
    ("GET da UI: sem Origin, com Sec-Fetch-Site", "127.0.0.1:7823", None, "same-origin", None, "/mc/info", True),
    ("GET da UI: Sec-Fetch-Site maiusculo", "127.0.0.1:7823", None, "Same-Origin", None, "/mc/info", True),
    ("POST da UI: manda a nossa Origin", "127.0.0.1:7823", NOSSA_ORIGEM, "same-origin", 10, "/aplicar", True),
    ("POST da UI: nossa Origin sem Sec-Fetch", "127.0.0.1:7823", NOSSA_ORIGEM, None, 10, "/aplicar", True),
    ("nossa Origin via localhost", "localhost:7823", "http://localhost:7823", None, None, "/mc/info", True),

    # ── a primeira carga da UI (navegação de topo, sem Origin) ───────────────
    ("navegacao de topo para /painel", "127.0.0.1:7823", None, None, None, "/painel", True),
    # ⚠️ A isenção vale SÓ para /painel. Sem isso, toda rota viraria pública.
    ("sem credencial em /mc/info", "127.0.0.1:7823", None, None, None, "/mc/info", False),
    ("sem credencial em /health", "127.0.0.1:7823", None, None, None, "/health", False),

    # ── o atacante que este portão barra: uma página web ─────────────────────
    ("site faz fetch (https)", "127.0.0.1:7823", "https://evil.example", "cross-site", None, "/health", False),
    ("site faz fetch (http)", "127.0.0.1:7823", "http://evil.example", "cross-site", None, "/health", False),
    ("site tenta forjar rota do loader", "127.0.0.1:7823", "https://evil.example", None, None, "/health", False),
    ("site com same-site (subdominio)", "127.0.0.1:7823", "https://evil.example", "same-site", None, "/mc/info", False),
    # Combinação que navegador nenhum produz, mas um processo local sim. A tranca de
    # origem não custa nada para manter de pé, então mantemos.
    ("Origin de site + Sec-Fetch forjado", "127.0.0.1:7823", "https://evil.example", "same-origin", None, "/mc/info", False),

    # ── DNS rebinding ────────────────────────────────────────────────────────
    ("Host de dominio externo", "evil.example", None, "same-origin", None, "/mc/info", False),
    ("Host ausente", None, None, "same-origin", None, "/mc/info", False),
    ("Host 127.0.0.1 sem porta", "127.0.0.1", None, "same-origin", None, "/mc/info", True),

    # ── teto de corpo ────────────────────────────────────────────────────────
    ("corpo no limite", "127.0.0.1:7823", None, "same-origin", MAX_CORPO_BYTES, "/aplicar", True),
    ("corpo acima do limite", "127.0.0.1:7823", None, "same-origin", MAX_CORPO_BYTES + 1, "/aplicar", False),
]


def main() -> int:
    falhas = []
    for nome, host, origin, sfs, corpo, rota, deve_passar in CASOS:
        recusa = portao(host, origin, sfs, corpo, rota)
        passou = recusa is None
        ok = passou == deve_passar
        marca = "  ok  " if ok else " FALHA"
        detalhe = "" if passou else f"  ({recusa[0]})"
        print(f"{marca} {nome}{detalhe}")
        if not ok:
            esperado = "passar" if deve_passar else "recusar"
            falhas.append(f"{nome}: esperava {esperado}")

    # ficha B033 (2026-10-28): a origem própria é a da porta REAL do socket, não a constante
    for nome, origin, porta, deve_passar in (
            ("serviço na 7899: o painel da 7899 entra", "http://127.0.0.1:7899", 7899, True),
            ("serviço na 7899: uma origem na 7823 não", "http://127.0.0.1:7823", 7899, False)):
        passou = portao("127.0.0.1:%d" % porta, origin, "same-origin", 10, "/aplicar", porta=porta) is None
        print(f"{'  ok  ' if passou == deve_passar else ' FALHA'} {nome}")
        if passou != deve_passar:
            falhas.append(nome)

    print(f"\n{len(CASOS) + 2 - len(falhas)}/{len(CASOS) + 2} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
