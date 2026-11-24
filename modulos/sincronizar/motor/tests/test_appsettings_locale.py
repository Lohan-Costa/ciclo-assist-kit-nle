"""O idioma escolhido no app, persistido para os PLUGINS o seguirem.

⭐⭐ Por que ele mora aqui e não só no `localStorage` da janela: o painel do
Media Composer é servido por outra origem e não enxerga aquele armazenamento.
Perguntando ao `navigator.language`, quem responde dentro do MC é o
QtWebEngine — que reporta o locale DELE, tipicamente `en-US`. O painel abria
em inglês ao lado de uma janela em português, num Windows em português.

O `settings.json` é a fonte única que os dois alcançam.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import appsettings


def _apontar(monkeypatch, pasta: Path) -> None:
    monkeypatch.setattr(appsettings, "app_data_dir", lambda: pasta)


def test_o_padrao_e_o_idioma_BASE_do_produto(monkeypatch, tmp_path):
    """⚠️ pt-BR, e não o que o sistema diz. Um app que adivinha o idioma pelo
    ambiente já nos deu o painel em inglês; o padrão é uma decisão."""
    _apontar(monkeypatch, tmp_path)
    assert appsettings.load()["locale"] == "pt-BR"


def test_a_escolha_sobrevive_a_gravacao(monkeypatch, tmp_path):
    _apontar(monkeypatch, tmp_path)
    appsettings.save({"locale": "en"})
    assert appsettings.load()["locale"] == "en"
    assert json.loads((tmp_path / "settings.json").read_text(encoding="utf-8"))["locale"] == "en"


def test_valor_estranho_volta_ao_BASE_e_nao_ao_do_sistema(monkeypatch, tmp_path):
    """Um `settings.json` corrompido não pode trocar o idioma de quem usa por um
    que ninguém escolheu."""
    _apontar(monkeypatch, tmp_path)
    (tmp_path / "settings.json").write_text(json.dumps({"locale": "klingon"}),
                                            encoding="utf-8")
    assert appsettings.load()["locale"] == "pt-BR"


def test_arquivo_ilegivel_nao_derruba_a_leitura(monkeypatch, tmp_path):
    _apontar(monkeypatch, tmp_path)
    (tmp_path / "settings.json").write_text("{isto não é json", encoding="utf-8")
    assert appsettings.load()["locale"] == "pt-BR"


def test_gravar_o_idioma_NAO_apaga_as_outras_configuracoes(monkeypatch, tmp_path):
    """⚠️ `save` é patch, não substituição — trocar de idioma não pode zerar o
    teto do cache que a pessoa ajustou."""
    _apontar(monkeypatch, tmp_path)
    appsettings.save({"cache_max_mb": 4096, "auto_render": True})
    appsettings.save({"locale": "en"})

    d = appsettings.load()
    assert d["locale"] == "en"
    assert d["cache_max_mb"] == 4096
    assert d["auto_render"] is True


# ── a bandeja: opção nova, e o padrão é o menos surpreendente ────────────────

def test_fechar_para_a_bandeja_nasce_DESLIGADO(monkeypatch, tmp_path):
    """⭐⭐ O X que não fecha surpreende: quem fecha a janela espera ter fechado o
    programa. A conveniência de manter o motor servindo os painéis do NLE (ADR 0010)
    continua disponível — mas como ESCOLHA, não como padrão."""
    _apontar(monkeypatch, tmp_path)
    assert appsettings.load()["close_to_tray"] is False


def test_a_escolha_da_bandeja_sobrevive_a_gravacao(monkeypatch, tmp_path):
    _apontar(monkeypatch, tmp_path)
    appsettings.save({"close_to_tray": True})
    assert appsettings.load()["close_to_tray"] is True


def test_booleano_escrito_como_texto_nao_liga_sozinho(monkeypatch, tmp_path):
    """⛔ `"false"` é uma string VERDADEIRA em Python. Sem sanear, um settings.json
    editado à mão ligaria justamente o que o usuário escreveu para desligar."""
    _apontar(monkeypatch, tmp_path)
    (tmp_path / "settings.json").write_text(
        json.dumps({"close_to_tray": "false", "auto_render": "true"}), encoding="utf-8")
    d = appsettings.load()
    assert d["close_to_tray"] is False
    assert d["auto_render"] is True
