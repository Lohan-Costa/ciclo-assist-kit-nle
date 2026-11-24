"""O que o servidor SERVE: a página da Preparar (`modulos/sincronizar/pagina/painel.html` + os dicionários).

Lida do disco A CADA pedido — editar o HTML e dar Reload basta. ⭐ Fase 4 do plano um app só (2026-11-07): a ponte
própria do Premiere, o painel CEP e o `.avpi` do MC saíram; o `host.jsx` (`pagina/host.jsx`) quem carrega é a ponte
ÚNICA do Ciclo Assist (`cicloassist/nle/premiere::HOSTS_DOS_MODULOS`), e quem a instala é o instalador único.

⭐ O idioma vem do APP (`settings.json` da pasta de dados), não do `navigator.language`: dentro do MC quem responde é
o QtWebEngine, tipicamente `en-US` — o painel saía em inglês ao lado do app em português.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

import segredo

MARCADOR_I18N = "<!--SINC_I18N-->"

#: `modulos/sincronizar/pagina` — `SINCRONIZAR_PAGINA` muda (testes).
PAGINA = Path(__file__).resolve().parents[1] / "pagina"


def pasta_da_pagina() -> Optional[Path]:
    explicita = os.environ.get("SINCRONIZAR_PAGINA")
    p = Path(explicita) if explicita else PAGINA
    return p if (p / "painel.html").is_file() else None


def _pagina() -> Path:
    base = pasta_da_pagina()
    if base is None:
        raise RuntimeError(f"a página da Preparar não foi encontrada em {PAGINA}")
    return base


def _ler(p: Path) -> str:
    """⛔ BYTES decodificados, nunca `read_text`: ele traduz CRLF em LF, e o `host.jsx` (que tem CRLF) saía com
    1321 bytes a menos que o do Rust — medido no diferencial. Servir é entregar o arquivo como ele é."""
    return p.read_bytes().decode("utf-8")


def _locale_do_app() -> str:
    try:
        v = json.loads((segredo.pasta_de_dados() / "settings.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "pt-BR"
    return "en" if isinstance(v, dict) and v.get("locale") == "en" else "pt-BR"


def _json_como_o_serde(v) -> str:
    """O `serde_json::to_string` sem `preserve_order`: compacto, chaves em ordem, UTF-8 cru."""
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def js_dos_dicionarios(pt_br: str, en: str) -> str:
    try:
        pt = json.loads(pt_br)
    except ValueError as e:
        raise RuntimeError(f"i18n pt-BR inválido: {e}")
    try:
        en_ = json.loads(en)
    except ValueError as e:
        raise RuntimeError(f"i18n en inválido: {e}")
    # ⚠️ `</` escapado: uma tradução com `</script>` fecharia a tag no meio do dicionário
    bruto = _json_como_o_serde({"pt-BR": pt, "en": en_}).replace("</", "<\\/")
    return ("/* GERADO pelo Sincronizar a partir de pagina/i18n/*.json — não edite. */\n"
            f"window.SINC_I18N = {bruto};\n")


def js_do_locale(locale: str) -> str:
    return ("/* O idioma vem do app, não do navegador — ver `locale_do_app`. */\n"
            f"window.SINC_LOCALE = {_json_como_o_serde(locale)};\n")


def montar_ui(html: str, dicionario: str) -> str:
    n = html.count(MARCADOR_I18N)
    if n == 1:
        return html.replace(MARCADOR_I18N, f"<script>\n{dicionario}</script>")
    if n == 0:
        raise RuntimeError(f"painel.html não tem o marcador {MARCADOR_I18N} — o i18n não teria onde entrar")
    raise RuntimeError(f"painel.html tem o marcador {MARCADOR_I18N} {n} vezes; "
                       "o dicionário entraria em todas (inclusive dentro de comentário)")


def ui_do_painel() -> str:
    src = _pagina()
    try:
        html = _ler(src / "painel.html")
    except OSError as e:
        raise RuntimeError(f"ler a interface do painel do Avid: {e}")
    pt = _ler(src / "i18n" / "pt-BR.json")
    en = _ler(src / "i18n" / "en.json")
    return montar_ui(html, js_dos_dicionarios(pt, en) + js_do_locale(_locale_do_app()))
