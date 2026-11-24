"""Op. 8, salvar tudo: o MC em foco e Ctrl+S — o clique na timeline só se o direto não gravou.

⛔ O teste do autor (2026-11-01): com a timeline VAZIA, "o vazio entre a régua e a trilha" não
existia e o save falhou. Autor: "basta o MC estar em foco… contanto que o foco não esteja numa bin".
"""

from __future__ import annotations

import sys

import pytest

from cicloassist.avid import salvar as S

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="o gesto é do Windows")


@pytest.fixture
def mc(monkeypatch, tmp_path):
    (tmp_path / "X.avp").write_bytes(b"")
    gestos: list = []
    monkeypatch.setattr(S.janela, "janela_principal", lambda exe, titulo="": 7)
    monkeypatch.setattr(S.janela, "existe_aviso", lambda t: False)
    monkeypatch.setattr(S.janela, "focar", lambda h: True)
    monkeypatch.setattr(S.maos, "da_frente", lambda: 7)
    monkeypatch.setattr(S.maos, "tecla", lambda h, vk, *m: gestos.append(("tecla", chr(vk))))
    monkeypatch.setattr(S.maos, "clicar", lambda h, x, y: gestos.append(("clique", x, y)))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    return tmp_path, gestos


def test_o_avp_nao_e_a_sombra_do_exfat(tmp_path):
    (tmp_path / "._X.avp").write_bytes(b"sombra")
    (tmp_path / "X.avp").write_bytes(b"")
    assert S.arquivo_do_projeto(tmp_path).name == "X.avp"


def test_ctrl_s_direto_sem_perguntar_ao_modelo(mc, monkeypatch):
    pasta, gestos = mc
    monkeypatch.setattr(S, "esperar_mudar", lambda avp, antes, prazo_s=0: True)
    monkeypatch.setattr(S, "_ponto_da_timeline", lambda *a: pytest.fail("perguntou ao modelo à toa"))
    r = S._salvar_tudo(pasta)
    assert r["salvou"] and gestos == [("tecla", "S")] and r["custo_usd"] == 0


def test_foco_numa_bin_cai_para_o_clique_na_timeline(mc, monkeypatch):
    pasta, gestos = mc
    respostas = iter([False, True])          # o direto não gravou o .avp; o 2º, sim
    monkeypatch.setattr(S, "esperar_mudar", lambda avp, antes, prazo_s=0: next(respostas))
    monkeypatch.setattr(S, "_ponto_da_timeline", lambda h, relatar: (7, 100, 900, 0.02))
    r = S._salvar_tudo(pasta)
    assert r["salvou"] and gestos == [("tecla", "S"), ("clique", 100, 900), ("tecla", "S")]


def test_dois_monitores_a_timeline_na_outra_janela_recebe_o_clique_e_o_ctrl_s(mc, monkeypatch):
    """MEDIDO (2026-11-02): no layout padrão de dois monitores a Timeline mora na janela
    "AvidMediaComposer" do monitor 2; o clique e o 2º Ctrl+S vão para ELA."""
    pasta, gestos = mc
    respostas = iter([False, True])
    monkeypatch.setattr(S, "esperar_mudar", lambda avp, antes, prazo_s=0: next(respostas))
    monkeypatch.setattr(S, "_ponto_da_timeline", lambda h, relatar: (9, 2880, 100, 0.02))
    focadas = []
    monkeypatch.setattr(S.janela, "focar", lambda h: focadas.append(h) or True)
    monkeypatch.setattr(S.maos, "tecla", lambda h, vk, *m: gestos.append(("tecla", chr(vk), h)))
    monkeypatch.setattr(S.maos, "clicar", lambda h, x, y: gestos.append(("clique", x, y, h)))
    r = S._salvar_tudo(pasta)
    assert r["salvou"] and focadas == [7, 9]
    assert gestos == [("tecla", "S", 7), ("clique", 2880, 100, 9), ("tecla", "S", 9)]


def test_janelas_de_trabalho_a_outra_grande_primeiro_sem_aviso_nem_select(monkeypatch):
    monkeypatch.setattr(S.janela, "janelas", lambda exe: [
        (7, "Avid Media Composer  - DOIS MONITORES R1", (0, 0, 1920, 1020)),
        (9, "AvidMediaComposer", (1920, -549, 3840, 483)),
        (11, "AvidMediaComposer", (701, 401, 1219, 591)),          # o aviso de teclado
        (13, "Select Project", (274, 84, 1626, 843)),
    ])
    assert S._janelas_de_trabalho(7) == [9, 7]


def _nao_achou(*_a):
    raise S.localizador.NaoAchei("a conferência não confirmou: só cinza liso")


def test_nada_sujo_e_timeline_nao_confirmada_e_nada_a_salvar(mc, monkeypatch):
    """⛔ A prova da F1 (2026-11-01): depois do sync por cena, nada sujo → o passo FALHAVA."""
    pasta, gestos = mc
    monkeypatch.setattr(S, "esperar_mudar", lambda avp, antes, prazo_s=0: False)
    monkeypatch.setattr(S, "_ponto_da_timeline", _nao_achou)
    r = S._salvar_tudo(pasta)
    assert r["salvou"] is False and "nada modificado" in r["nota"] and gestos == [("tecla", "S")]


def test_bin_regravada_sozinha_e_timeline_nao_achada_e_falha(mc, monkeypatch):
    """Com a bin em foco o Ctrl+S salvou SÓ ela: aí não achar a timeline é falha de verdade."""
    pasta, _ = mc
    b = pasta / "D01 SOM.avb"
    b.write_bytes(b"")
    import os
    os.utime(b, (1, 1))

    def direto(avp, antes, prazo_s=0):
        os.utime(b, None)                     # o MC regravou a bin, não o .avp
        return False

    monkeypatch.setattr(S, "esperar_mudar", direto)
    monkeypatch.setattr(S, "_ponto_da_timeline", _nao_achou)
    with pytest.raises(S.SalvarFalhou, match="D01 SOM"):
        S._salvar_tudo(pasta)


# MEDIDO (2026-11-02, MC 2024.6): o layout LIVRE do autor — cada painel solto é uma janela com o nome dele.
_LAYOUT_LIVRE = [
    (3278990, "Composer", (1920, -549, 3840, -13)),
    (6686422, "Effect Palette", (1927, -5, 2406, 442)),
    (3081552, "Audio EQ", (2, 61, 217, 403)),
    (3474780, "Bins", (957, 40, 1846, 475)),
    (7669608, "Audio Mixer", (968, 487, 1777, 985)),
    (12518890, "Timeline", (2398, -8, 3839, 482)),
    (3868688, "Avid Media Composer  - DOIS MONITORES R1", (0, 0, 1920, 1020)),
    (25954250, "AvidMediaComposer", (1920, -549, 3840, 483)),
]


def test_layout_livre_a_timeline_solta_vem_primeiro_mesmo_pequena(monkeypatch):
    pequena = [(h, t, (2398, 300, 2900, 482) if t == "Timeline" else r) for h, t, r in _LAYOUT_LIVRE]
    for janelas in (_LAYOUT_LIVRE, pequena):            # grande ou pequena (< 1/4 do monitor)
        monkeypatch.setattr(S.janela, "janelas", lambda exe, j=janelas: j)
        ordem = S._janelas_de_trabalho(3868688)
        assert ordem[0] == 12518890 and ordem[-1] == 3868688
        assert 3474780 not in ordem and 7669608 not in ordem     # Bins e Mixer: pequenas, não são timeline


def test_ponto_achado_sem_sinal_de_bin_espera_pouco_e_diz_nada_a_salvar(mc, monkeypatch):
    pasta, gestos = mc
    prazos = []

    def esperar(avp, antes, prazo_s=S.PRAZO_DO_SAVE_S):
        prazos.append(prazo_s)
        return False
    monkeypatch.setattr(S, "esperar_mudar", esperar)
    monkeypatch.setattr(S, "_ponto_da_timeline", lambda h, relatar: (7, 100, 900, 0.02))
    r = S._salvar_tudo(pasta)
    assert r["salvou"] is False and "nada modificado" in r["nota"]
    assert prazos == [S.PRAZO_DO_SAVE_DIRETO_S, S.PRAZO_DO_SAVE_DIRETO_S]


def test_timeline_em_janela_cortada_diz_cortada_e_nao_nao_achei(monkeypatch):
    monkeypatch.setattr(S, "_janelas_de_trabalho", lambda p: [9, 7])
    monkeypatch.setattr(S, "_retangulo", lambda h: (0, 0, 10, 10))
    monkeypatch.setattr(S.tela, "fotografar", lambda: None)

    erros = iter([S.localizador.JanelaCortada("a janela está cortada"), S.localizador.NaoAchei("não achei")])
    monkeypatch.setattr(S.localizador, "localizar", lambda *a, **k: (_ for _ in ()).throw(next(erros)))
    with pytest.raises(S.localizador.JanelaCortada):
        S._ponto_da_timeline(7, lambda *a: None)
