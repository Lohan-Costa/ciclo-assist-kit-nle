"""O vigia da janela travada (2026-10-29): um dump por episódio, só depois do limite."""

from __future__ import annotations

import subprocess
import sys

import pytest

from cicloassist.servico import travamento as T


class Relogio:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def _vigia(tmp_path, monkeypatch, respostas):
    monkeypatch.setattr(T, "pasta_dos_dumps", lambda: tmp_path)
    rel, dumps = Relogio(), []
    v = T.Vigia(42, limite_s=15, achar=lambda pid: [7], perguntar=lambda h: respostas.pop(0),
                despejar=lambda pid, p: dumps.append(p) or p, agora=rel)
    return v, rel, dumps


def test_respondendo_nao_faz_nada(tmp_path, monkeypatch):
    v, rel, dumps = _vigia(tmp_path, monkeypatch, [True, True])
    assert v.olhar() == "ok" and v.olhar() == "ok" and dumps == []


def test_presa_alem_do_limite_grava_um_dump_so(tmp_path, monkeypatch):
    v, rel, dumps = _vigia(tmp_path, monkeypatch, [False, False, False, False, True])
    assert v.olhar() == "lenta"          # t=0: primeira falta
    rel.t = 10
    assert v.olhar() == "lenta"          # ainda abaixo do limite
    rel.t = 20
    assert v.olhar() == "travada" and len(dumps) == 1
    rel.t = 30
    assert v.olhar() == "travada" and len(dumps) == 1   # um por episódio
    rel.t = 40
    assert v.olhar() == "voltou"
    assert v.presa_desde is None and not v.despejou


def test_demora_curta_nao_vira_dump(tmp_path, monkeypatch):
    v, rel, dumps = _vigia(tmp_path, monkeypatch, [False, True])
    v.olhar()
    rel.t = 5
    assert v.olhar() == "voltou" and dumps == []


def test_sem_janela_nao_conta_como_travada(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "pasta_dos_dumps", lambda: tmp_path)
    v = T.Vigia(42, achar=lambda pid: [], perguntar=lambda h: pytest.fail("perguntou"))
    assert v.olhar() == "sem_janela"


def test_dump_que_falha_e_dito_e_nao_derruba(tmp_path, monkeypatch):
    monkeypatch.setattr(T, "pasta_dos_dumps", lambda: tmp_path)
    rel = Relogio()

    def falha(pid, p):
        raise OSError("sem permissão")
    v = T.Vigia(42, limite_s=15, achar=lambda pid: [7], perguntar=lambda h: False,
                despejar=falha, agora=rel)
    v.olhar()
    rel.t = 20
    assert v.olhar() == "travada" and v.dumps == []


@pytest.mark.skipif(sys.platform != "win32", reason="MiniDumpWriteDump é do Windows")
def test_o_dump_de_verdade_sai(tmp_path):
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        caminho = T.gravar_dump(p.pid, tmp_path / "x.dmp")
        assert caminho.stat().st_size > 10_000
        assert caminho.read_bytes()[:4] == b"MDMP"
    finally:
        p.kill()


def test_o_limite_conta_de_quando_a_pergunta_saiu(tmp_path, monkeypatch):
    """A pergunta que não volta leva o prazo dela (3 s): a trava começou ANTES da resposta faltar."""
    monkeypatch.setattr(T, "pasta_dos_dumps", lambda: tmp_path)
    rel, dumps = Relogio(), []

    def perguntar(h):
        rel.t += 3                     # o SendMessageTimeout esgota o prazo
        return False
    v = T.Vigia(42, limite_s=8, achar=lambda pid: [7], perguntar=perguntar,
                despejar=lambda pid, p: dumps.append(p) or p, agora=rel)
    assert v.olhar() == "lenta" and v.presa_desde == 0
    rel.t = 3                          # 2 s depois de a resposta faltar (t=3 → 5 → 8 com o prazo)
    assert v.olhar() == "lenta"        # perguntou em 3, faltou em 6: 6 s presa
    rel.t = 8
    assert v.olhar() == "travada" and len(dumps) == 1


def test_nao_lidos_e_marcar_lido(tmp_path):
    import os
    a, b = tmp_path / "1_a.dmp", tmp_path / "2_b.dmp"
    a.write_bytes(b"x"); b.write_bytes(b"y")
    os.utime(a, (100, 100)); os.utime(b, (200, 200))
    assert [t["arquivo"] for t in T.nao_lidos(tmp_path)] == ["1_a.dmp", "2_b.dmp"]
    T.marcar_lido(a)
    assert [t["arquivo"] for t in T.nao_lidos(tmp_path)] == ["2_b.dmp"]
    assert T.nao_lidos(tmp_path / "nao-existe") == []


def test_podar_guarda_os_mais_recentes_com_os_simbolos(tmp_path):
    import os
    for i in range(13):
        d = tmp_path / f"{i:02d}.dmp"
        d.write_bytes(b"x"); os.utime(d, (i, i))
        (tmp_path / f"{i:02d}").mkdir(); (tmp_path / f"{i:02d}" / "cicloassist.pdb").write_bytes(b"p")
    T.marcar_lido(tmp_path / "00.dmp")
    saiu = T.podar(tmp_path, manter=10)
    assert sorted(p.name for p in saiu) == ["00.dmp", "01.dmp", "02.dmp"]
    assert sorted(p.name for p in tmp_path.glob("*.dmp"))[0] == "03.dmp"
    assert not (tmp_path / "00").exists() and not (tmp_path / "00.lido").exists()
    assert (tmp_path / "03" / "cicloassist.pdb").exists()
