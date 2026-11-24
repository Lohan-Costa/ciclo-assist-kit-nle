"""Organizar o projeto do Media Composer pelo disco (`avid/organizar.py`).

⭐ O painel lateral do MC É o disco (banco, `arrastar.md`); o save ou o refresh mostra o novo.
"""

from pathlib import Path

from cicloassist.avid import organizar as O


def _projeto(tmp_path: Path) -> Path:
    p = tmp_path / "FLUXO"
    p.mkdir()
    (p / "FLUXO.avp").write_bytes(b"")
    for b in ("D01 CAM", "D01 SOM", "D01 SUBCLIPES"):
        (p / f"{b}.avb").write_bytes(b"x")
    (p / "CENAS").mkdir()
    (p / "CENAS" / "C10.avb").write_bytes(b"x")
    (p / "Statistics").mkdir()
    return p


def test_a_arvore_ve_bins_e_pastas_e_ignora_as_do_sistema(tmp_path):
    a = O.arvore(_projeto(tmp_path))
    assert a["d01 cam"] == "bin" and a["cenas"] == "pasta" and a["cenas/c10"] == "bin"
    assert "statistics" not in a


def test_renomear_a_bin_que_o_fluxo_criou(tmp_path):
    p = _projeto(tmp_path)
    ops = [{"acao": "renomear", "item": "D01 SUBCLIPES", "nome": "subclipes"}]
    assert O.conferir(p, ops) == ""
    fechadas = []
    feitas = O.executar(p, ops, fechar_bin=fechadas.append)
    assert (p / "subclipes.avb").is_file() and not (p / "D01 SUBCLIPES.avb").exists()
    assert [f.name for f in fechadas] == ["D01 SUBCLIPES.avb"]       # ⛔ fechada ANTES
    assert feitas == [{"acao": "renomear", "de": "D01 SUBCLIPES", "para": "subclipes", "especie": "bin"}]


def test_um_plano_cria_a_pasta_e_move_para_ela(tmp_path):
    """⭐ "Organize o projeto do jeito X": a pasta nasce e recebe as bins no MESMO plano."""
    p = _projeto(tmp_path)
    ops = [{"acao": "criar_pasta", "nome": "D01"},
           {"acao": "mover", "item": "D01 CAM", "para": "D01"},
           {"acao": "mover", "item": "D01 SOM.avb", "para": "D01"},
           {"acao": "renomear", "item": "D01/D01 CAM", "nome": "CAMERA"}]
    assert O.conferir(p, ops) == ""
    O.executar(p, ops)
    assert (p / "D01" / "CAMERA.avb").is_file() and (p / "D01" / "D01 SOM.avb").is_file()


def test_mover_e_renomear_PASTA_leva_as_bins_de_dentro(tmp_path):
    p = _projeto(tmp_path)
    fechadas = []
    ops = [{"acao": "criar_pasta", "nome": "ARQUIVO"},
           {"acao": "mover", "item": "CENAS", "para": "ARQUIVO"},
           {"acao": "renomear", "item": "ARQUIVO/CENAS", "nome": "CENAS D01"}]
    assert O.conferir(p, ops) == ""
    O.executar(p, ops, fechar_bin=fechadas.append)
    assert (p / "ARQUIVO" / "CENAS D01" / "C10.avb").is_file()
    assert [f.name for f in fechadas] == ["C10.avb", "C10.avb"]


def test_a_conferencia_pega_o_que_quebraria(tmp_path):
    p = _projeto(tmp_path)
    assert "não há bin nem pasta" in O.conferir(p, [{"acao": "renomear", "item": "NADA", "nome": "x"}])
    assert "já existe" in O.conferir(p, [{"acao": "renomear", "item": "D01 CAM", "nome": "D01 SOM"}])
    assert "não há pasta" in O.conferir(p, [{"acao": "mover", "item": "D01 CAM", "para": "FALTA"}])
    assert "caractere" in O.conferir(p, [{"acao": "renomear", "item": "D01 CAM", "nome": "a/b"}])
    assert "dentro dela mesma" in O.conferir(p, [
        {"acao": "criar_pasta", "nome": "F", "dentro_de": "CENAS"},
        {"acao": "mover", "item": "CENAS", "para": "CENAS/F"}])
    assert "ação" in O.conferir(p, [{"acao": "apagar", "item": "D01 CAM"}])


def test_trocar_so_a_caixa_do_nome_e_permitido(tmp_path):
    p = _projeto(tmp_path)
    ops = [{"acao": "renomear", "item": "D01 CAM", "nome": "d01 cam"}]
    assert O.conferir(p, ops) == ""
    O.executar(p, ops)
    assert "d01 cam.avb" in [x.name for x in p.iterdir()]


def test_falha_no_meio_diz_o_que_ja_foi_feito(tmp_path, monkeypatch):
    p = _projeto(tmp_path)
    ops = [{"acao": "renomear", "item": "D01 CAM", "nome": "CAM"},
           {"acao": "renomear", "item": "D01 SOM", "nome": "SOM"}]
    real = O.os.replace
    chamadas = []

    def quebra(a, b):
        chamadas.append(a)
        if len(chamadas) == 2:
            raise PermissionError("em uso")
        real(a, b)

    monkeypatch.setattr(O.os, "replace", quebra)
    try:
        O.executar(p, ops)
    except O.OrganizarFalhou as e:
        assert "operação 2" in str(e) and "D01 CAM→CAM" in str(e)
    else:
        raise AssertionError("tinha de falhar")
