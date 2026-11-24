"""O piloto adaptativo, sem tela e sem modelo: coordenadas, a decisão de NÃO clicar, e a prova do save."""

from __future__ import annotations

import os
import time

import numpy as np
import sys

import pytest

from cicloassist.avid import salvar
from cicloassist.piloto import localizador, tela


#: MEDIDO (2026-11-02, manhã): o principal a 125 % e o monitor 2 à DIREITA, 549 px mais alto.
_MONITORES = [(0, 0, 1920, 1080), (1920, -549, 3840, 531)]


@pytest.fixture(autouse=True)
def _monitores_fixos(monkeypatch):
    """O teste não pode depender dos monitores de quem roda a suíte (o autor mudou o lado no mesmo dia)."""
    monkeypatch.setattr(tela, "monitores", lambda: list(_MONITORES))


def _foto(w=1920, h=1080, x0=0, y0=0):
    return tela.Foto(np.zeros((h, w, 3), np.uint8), x0, y0)


def test_foto_converte_entre_foto_e_tela_com_origem_negativa():
    f = _foto(x0=-1920, y0=-549)
    assert f.da_tela(10, 20) == (-1910, -529)
    assert f.da_foto(-1910, -529) == (10, 20)


def test_recorte_corta_aos_limites_e_guarda_a_origem():
    r = _foto().recorte((-9, -9, 1929, 1029))      # a janela maximizada começa em (-9, -9)
    assert r.img.shape[:2] == (1029, 1920)
    assert (r.x0, r.y0) == (0, 0)
    with pytest.raises(tela.SemTela):
        _foto().recorte((3000, 0, 3100, 10))


def test_com_cruz_nao_mexe_na_original():
    img = np.zeros((50, 50, 3), np.uint8)
    m = tela.com_cruz(img, 25, 25)
    assert img.sum() == 0 and tuple(m[25, 25]) == (0, 0, 255)


def test_json_aceita_texto_em_volta_e_recusa_sem_json():
    assert localizador._json('```json\n{"achou": true}\n```') == {"achou": True}
    with pytest.raises(localizador.NaoAchei):
        localizador._json("não sei")


def _respostas(monkeypatch, *rs):
    fila = list(rs)
    monkeypatch.setattr(localizador._tela, "jpeg", lambda img, largura=None: b"jpg")
    monkeypatch.setattr(localizador, "perguntar", lambda jpg, texto, modelo="": (fila.pop(0), 1.0, 0.01))


def test_localizar_escala_para_a_tela_e_confere(monkeypatch):
    _respostas(monkeypatch, {"achou": True, "x": 683, "y": 300, "certeza": "alta"}, {"confere": True})
    a = localizador.localizar(_foto(x0=0, y0=0), "x", regiao=(-9, -9, 1929, 1029))
    # 1920 px de largura → 1366 enviados: escala 1920/1366
    assert (a.x, a.y) == (int(683 * 1920 / 1366), int(300 * 1920 / 1366))
    assert a.custo_usd == pytest.approx(0.02)


def test_dois_monitores_o_monitor_2_vai_inteiro_a_1366_e_volta_em_coordenada_de_tela(monkeypatch):
    """A geometria MEDIDA em 2026-11-02: área virtual (0, −549) 3840×1629, o monitor 2 em
    (1920, −549)–(3840, 531). Recortado pelo monitor, a escala é a de um monitor só (1920/1366,
    não 3840/1366), e o ponto volta na área virtual — com o y negativo."""
    _respostas(monkeypatch, {"achou": True, "x": 683, "y": 100, "certeza": "alta"}, {"confere": True})
    area = _foto(w=3840, h=1629, x0=0, y0=-549)
    a = localizador.localizar(area, "x", regiao=(1920, -549, 3840, 531))
    assert (a.x, a.y) == (1920 + int(683 * 1920 / 1366), -549 + int(100 * 1920 / 1366))


@pytest.mark.parametrize("primeira, segunda, palavra", [
    ({"achou": False, "o_que_vi": "nada"}, None, "não achei"),
    ({"achou": True, "x": 1, "y": 1, "certeza": "baixa"}, None, "certeza"),
    ({"achou": True, "x": 5000, "y": 1, "certeza": "alta"}, None, "fora"),
    ({"achou": True, "x": 1, "y": 1, "certeza": "alta"}, {"confere": False, "sob_a_cruz": "um clipe"}, "um clipe"),
])
def test_na_duvida_nao_devolve_ponto(monkeypatch, primeira, segunda, palavra):
    _respostas(monkeypatch, primeira, *([segunda] if segunda else []))
    with pytest.raises(localizador.NaoAchei, match=palavra):
        localizador.localizar(_foto(), "x")


def test_o_save_se_prova_pela_data_do_avp(tmp_path):
    avp = tmp_path / "P.avp"
    avp.write_text("x")
    antes = avp.stat().st_mtime
    assert salvar.arquivo_do_projeto(tmp_path) == avp
    assert not salvar.esperar_mudar(avp, antes, prazo_s=0.3)
    os.utime(avp, (antes + 5, antes + 5))
    assert salvar.esperar_mudar(avp, antes, prazo_s=0.3)


def test_sem_avp_e_falha_dita(tmp_path):
    with pytest.raises(salvar.SalvarFalhou, match=".avp"):
        salvar.arquivo_do_projeto(tmp_path)


def test_salvar_tudo_passa_pelo_portao():
    import cicloassist.mcp.ferramentas  # noqa: F401  (o registro é efeito do import)
    from cicloassist.mcp.registro import FERRAMENTAS
    assert FERRAMENTAS["salvar_tudo"].escreve is True


class _MC:
    def __init__(self, recusa_open=False):
        self.chamadas, self.recusa_open = [], recusa_open

    def caminho_relativo_da_bin(self, p):
        return os.path.basename(p)

    def _chamar(self, nome, **kw):
        self.chamadas.append(nome)
        if nome == "OpenBin" and self.recusa_open and self.chamadas.count("OpenBin") == 1:
            raise RuntimeError("FILE_OPEN_FAILURE")


def _bin_com_atributo(p):
    import cicloassist.avid  # noqa: F401
    import avb
    with avb.open() as f:
        f.content.attributes["BIN_COLUMNS_WIDTHS"] = bytearray(b"{}")
        uid = f.content.uid
        f.write(str(p))
    return uid


def test_sujar_tira_os_atributos_e_preserva_o_uid(tmp_path, monkeypatch):
    import avb
    monkeypatch.setattr(salvar.time, "sleep", lambda s: None)
    p = tmp_path / "SYNC.avb"
    uid = _bin_com_atributo(p)
    m = _MC()
    salvar.sujar(m, p)
    assert m.chamadas == ["CloseBin", "OpenBin"]
    with avb.open(str(p)) as f:
        assert f.content.uid == uid and len(f.content.attributes) == 0
    assert not (tmp_path / "SYNC.avb.novo").exists()


def test_sujar_recusado_devolve_a_bin_byte_a_byte(tmp_path, monkeypatch):
    monkeypatch.setattr(salvar.time, "sleep", lambda s: None)
    p = tmp_path / "SYNC.avb"
    _bin_com_atributo(p)
    antes = p.read_bytes()
    m = _MC(recusa_open=True)
    with pytest.raises(RuntimeError):
        salvar.sujar(m, p)
    assert p.read_bytes() == antes and m.chamadas == ["CloseBin", "OpenBin", "OpenBin"]


def test_novo_projeto_le_a_janela_depois_da_troca_de_aba(monkeypatch):
    """MEDIDO (2026-11-02): no monitor de 100 % a Select Project tem 607 px de altura na aba
    Projects e 751 na New Project; com a região herdada de antes da troca, o Create (no rodapé)
    ficava fora do recorte. A região tem de ser a da janela AGORA."""
    from cicloassist.avid import abrir

    agora = {"r": (2194, -465, 3276, 142)}
    monkeypatch.setattr(abrir._janela, "janelas", lambda exe: [(1, "Select Project", agora["r"])])
    vistas = []

    class _P:
        passos: list = []

        def relatar(self, *a):
            pass

        def achar_varios(self, alvos, regiao=None):
            vistas.append(regiao)
            raise RuntimeError("parar aqui")

    agora["r"] = (2194, -465, 3276, 286)          # a aba New Project esticou a janela
    with pytest.raises(RuntimeError):
        abrir._novo_projeto(_P(), "X", "1080p/25")
    assert vistas == [(2194, -465, 3276, 286)]


# MEDIDO (2026-11-02, MC 2024.6, layout PADRÃO de dois monitores): as janelas de topo do MC.
_DOIS_MONITORES = [
    (3868688, "Avid Media Composer  - DOIS MONITORES R1", (0, 0, 1920, 1020)),
    (25954250, "AvidMediaComposer", (1920, -549, 3840, 483)),   # Composer + Timeline, 12 px maior
]


def test_principal_e_a_do_titulo_e_nao_a_maior():
    from cicloassist import janela
    assert janela.escolher_principal(_DOIS_MONITORES) == 25954250          # a regra antiga
    assert janela.escolher_principal(_DOIS_MONITORES, "Avid Media Composer") == 3868688
    # sem nenhuma com o título (a abertura), a maior de todas
    assert janela.escolher_principal(_DOIS_MONITORES[1:], "Avid Media Composer") == 25954250


def test_aviso_e_pequeno_e_a_janela_do_composer_nao_e():
    from cicloassist import janela
    assert janela.pequena((701, 401, 1219, 591))          # aviso de teclado, medido
    assert janela.pequena((759, 457, 1161, 582))          # barra de carregar, medida
    assert not janela.pequena((1920, -549, 3840, 483))    # o Composer/Timeline: mesmo título


def test_do_painel_acha_a_janela_solta_pelo_titulo(monkeypatch):
    from cicloassist import janela
    monkeypatch.setattr(janela, "janelas", lambda exe: [
        (3474780, "Bins", (957, 40, 1846, 475)), (12518890, "Timeline", (2398, -8, 3839, 482))])
    assert janela.do_painel("x.exe", "Bins") == 3474780
    assert janela.do_painel("x.exe", "Timeline") == 12518890
    assert janela.do_painel("x.exe", "Composer") is None      # encaixado: sem janela própria
    monkeypatch.setattr(janela, "janelas", lambda exe: [
        (1573996, "Bins.1", (710, 210, 1210, 810)), (9, "Bins Extra", (0, 0, 9, 9))])
    assert janela.do_painel("x.exe", "Bins") == 1573996      # MEDIDO: o MC numera ao reabrir


def test_recorte_pequeno_ganha_margem_ate_o_minimo():
    """MEDIDO (2026-11-02): no recorte de 518×190 do aviso o ponto saiu 29 px abaixo; com 818×490, exato."""
    r = localizador._com_margem(_foto(), (701, 401, 1219, 591))
    assert (r[2] - r[0], r[3] - r[1]) == localizador.MINIMO
    assert (r[0] + r[2]) // 2 == (701 + 1219) // 2 and (r[1] + r[3]) // 2 == (401 + 591) // 2
    grande = (0, 0, 1920, 1020)
    assert localizador._com_margem(_foto(), grande) == grande


def test_localizar_no_recorte_pequeno_manda_a_imagem_com_margem(monkeypatch):
    tamanhos = []

    def perguntar(jpg, texto, modelo=""):
        tamanhos.append(texto.split("A imagem tem ")[1].split(" px")[0] if "A imagem tem" in texto else "conferir")
        return ({"achou": True, "x": 400, "y": 240, "certeza": "alta"} if "Onde está" in texto
                else {"confere": True}), 1.0, 0.01
    monkeypatch.setattr(localizador, "perguntar", perguntar)
    a = localizador.localizar(_foto(), "x", regiao=(701, 401, 1219, 591))
    assert tamanhos[0] == "800x480"
    assert (a.x, a.y) == (560 + 400, 256 + 240)       # a origem do recorte COM a margem


@pytest.mark.skipif(sys.platform != "win32", reason="janelas do MC: só Windows")
def test_dois_avisos_o_habilitado_primeiro(monkeypatch):
    """MEDIDO (2026-11-02): a barra de carregar (desabilitada pelo modal) e o aviso de teclado
    (habilitado, nascido atrás da principal) ao mesmo tempo — o abrir procurava o botão na barra."""
    from cicloassist.avid import abrir
    monkeypatch.setattr(abrir._janela, "janelas", lambda exe: [
        (15993378, "AvidMediaComposer", (759, 457, 1161, 582)),     # a barra
        (4327668, "Avid Media Composer ", (0, 0, 1920, 1020)),
        (3802526, "AvidMediaComposer", (701, 401, 1219, 591)),      # o aviso
    ])
    monkeypatch.setattr(abrir._janela, "habilitada", lambda h: h != 15993378)
    assert [h for h, _r in abrir._avisos()] == [3802526, 15993378]
    assert abrir._aviso_na_tela() == 3802526
    monkeypatch.setattr(abrir._janela, "habilitada", lambda h: h == 4327668)   # só a barra, sem modal
    assert abrir._aviso_na_tela() == 0


def test_menu_aberto_nao_e_aviso(monkeypatch):
    """MEDIDO (2026-11-02): o menu File aberto tem o título "AvidMediaComposer", é pequeno e habilitado."""
    from cicloassist.avid import abrir
    monkeypatch.setattr(abrir._janela, "janelas", lambda exe: [
        (3278164, "AvidMediaComposer", (4, 39, 290, 564)),            # o menu File (popup do Qt)
        (4327668, "Avid Media Composer  - DOIS MONITORES F2", (0, 0, 1920, 1020)),
    ])
    monkeypatch.setattr(abrir._janela, "e_popup", lambda h: h == 3278164)
    monkeypatch.setattr(abrir._janela, "habilitada", lambda h: True)
    assert abrir._avisos() == [] and abrir._aviso_na_tela() == 0


def test_janela_maximizada_passa_e_a_que_pega_a_faixa_sem_monitor_nao():
    assert tela.parte_fora((-9, -9, 1929, 1029)) == 0                   # maximizada: a folga das bordas
    assert tela.parte_fora((1920, -549, 3840, 483)) == 0                # inteira no monitor 2
    assert tela.parte_fora((1700, 60, 2318, 1080)) > 0                  # atravessada, desce na faixa morta
    assert tela.parte_fora((2194, -700, 3276, 142)) > 0                 # passa do topo do monitor 2


def test_localizar_em_janela_cortada_para_sem_perguntar(monkeypatch):
    """Decisão do autor (2026-11-02): não se arruma o layout do editor — para e diz por quê."""
    monkeypatch.setattr(localizador, "perguntar", lambda *a, **k: pytest.fail("perguntou ao modelo à toa"))
    area = _foto(w=3840, h=1629, x0=0, y0=-549)
    with pytest.raises(localizador.JanelaCortada, match="não mexo no seu layout"):
        localizador.localizar(area, "x", regiao=(1700, 60, 2318, 1080))
    with pytest.raises(localizador.JanelaCortada):
        localizador.localizar_varios(area, {"a": "x"}, (1700, 60, 2318, 1080))


@pytest.mark.skipif(sys.platform != "win32", reason="janelas do MC: só Windows")
def test_aviso_com_foco_mas_enterrado_vai_ao_topo_da_pilha(monkeypatch):
    """MEDIDO (2026-11-02): o aviso era a janela da FRENTE com 8 janelas acima dele — foco ≠ pilha."""
    from cicloassist.avid import abrir
    monkeypatch.setattr(abrir._janela, "janelas", lambda exe: [
        (1378864, "Avid Media Composer ", (0, 0, 1920, 1020)),
        (3933298, "AvidMediaComposer", (701, 401, 1219, 591))])
    monkeypatch.setattr(abrir._janela, "habilitada", lambda h: h == 3933298)
    monkeypatch.setattr(abrir._janela, "e_popup", lambda h: False)
    monkeypatch.setattr(abrir.maos, "da_frente", lambda: 3933298)
    topo = []
    monkeypatch.setattr(abrir._janela, "ao_topo", lambda h: topo.append(h) or True)
    assert abrir._frente_do_mc() == 3933298 and topo == [3933298]


@pytest.mark.skipif(sys.platform != "win32", reason="janelas do MC: só Windows")
def test_barra_presa_atras_da_select_project_nao_e_aviso(monkeypatch):
    """⛔⛔ MEDIDO (2026-11-03, teste do chat): a barra de carregar (402×125) ficou visível e
    DESABILITADA atrás da Select Project habilitada; contada como aviso, o abrir nunca agiu e
    desistiu em 60 s dizendo "há um aviso na tela", com a tela limpa."""
    from cicloassist.avid import abrir
    janelas = [(1, "Select Project", (409, 101, 1491, 860)),
               (2, "AvidMediaComposer", (759, 457, 1161, 582)),          # a barra presa
               (3, "Avid Media Composer ", (0, 0, 1920, 1020))]
    monkeypatch.setattr(abrir._janela, "e_popup", lambda h: False)
    monkeypatch.setattr(abrir._janela, "habilitada", lambda h: h != 2)
    assert abrir._barra_presa(janelas)
    # Um aviso de verdade é HABILITADO (e desabilita a Select Project): continua aviso.
    monkeypatch.setattr(abrir._janela, "habilitada", lambda h: h == 2)
    assert not abrir._barra_presa(janelas)
    # Sem Select Project (o MC carregando um projeto), a barra é barra de carregar: o laço espera.
    assert not abrir._barra_presa([j for j in janelas if j[0] != 1])
