"""`aplicar_metadados`: o nome, as colunas e a fita do BWF numa bin REAL do MC 2024.6 (som gerenciado).

O dado: `tests/dados/som_gerenciado_mc2024.avb` — a bin que o MC gravou ao importar os 11 WAV do laboratório pelo
`som_direto_gerenciado` (2026-11-01). Provado na tela no mesmo dia: os 11 batem com o link do MC (nome e `_USER`), a
coluna Tape mostra o sTAPE, e o sync do Sincronizar dividiu por cena pela COLUNA (`spikes/cena_so_no_metadado.py`).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import avb

import cicloassist.avid  # noqa: F401  (o avb_fiel)
from cicloassist.avid import importar_opatom as I

import pytest

DADO = Path(__file__).parent / "dados" / "som_gerenciado_mc2024.avb"

# ⚠️ O `.gitignore` ignora `.avb` (bins de projeto não vão ao Git); esta foi adicionada com `git add -f`.
pytestmark = pytest.mark.skipif(not DADO.is_file(), reason="a bin de dado não está neste clone")


def _masters(caminho: Path) -> dict[str, dict]:
    fora = {}
    with avb.open(str(caminho)) as f:
        for m in f.content.mobs:
            if m.property_data.get("mob_type_id") == 2:
                a = m.property_data.get("attributes")
                fora[str(m.mob_id)] = {"nome": m.name, "user": dict(a["_USER"]) if a is not None and "_USER" in a else {}}
    return fora


def test_nome_colunas_e_so_quem_foi_pedido(tmp_path):
    b = tmp_path / "x.avb"
    shutil.copy(DADO, b)
    antes = _masters(b)
    alvo, outro = sorted(antes)[:2]
    meta = {"nome": "99/7", "user": {"Scene": "99", "Take": "7", "TapeID": "X.WAV"}, "tape": "SR99"}
    assert I.aplicar_metadados(b, {alvo: meta}) == 1
    depois = _masters(b)
    assert depois[alvo]["nome"] == "99/7"
    assert depois[alvo]["user"] == {"Scene": "99", "Take": "7", "TapeID": "X.WAV"}
    assert depois[outro] == antes[outro]                      # quem não foi pedido não muda


def test_o_estado_da_bin_vai_para_a_nova_antes_da_troca(tmp_path, monkeypatch):
    """No Mac o `os.replace` apaga os atributos estendidos da bin (colunas, vista): têm de ser copiados antes."""
    b = tmp_path / "x.avb"
    shutil.copy(DADO, b)
    alvo = sorted(_masters(b))[0]
    chamadas = []
    monkeypatch.setattr(I, "copiar_atributos", lambda de, para: chamadas.append((Path(de), Path(para), Path(para).is_file())))
    I.aplicar_metadados(b, {alvo: {"nome": "1/1", "user": {"Scene": "1", "Take": "1"}, "tape": None}})
    assert chamadas == [(b, b.with_name("x.avb.novo"), True)]


def test_preserva_o_uid_da_bin(tmp_path):
    """⛔ Randomizar o uid faria o MC tratar a bin como outra (`.AutoCopy`) — banco, escrita."""
    b = tmp_path / "x.avb"
    shutil.copy(DADO, b)
    with avb.open(str(b)) as f:
        uid = f.content.uid
    alvo = sorted(_masters(b))[0]
    I.aplicar_metadados(b, {alvo: {"nome": "1/1", "user": {"Scene": "1", "Take": "1"}, "tape": None}})
    with avb.open(str(b)) as f:
        assert f.content.uid == uid


def test_sem_metadado_nao_regrava(tmp_path):
    b = tmp_path / "x.avb"
    shutil.copy(DADO, b)
    antes = b.read_bytes()
    assert I.aplicar_metadados(b, {"060a2b34": None}) == 0
    assert b.read_bytes() == antes
