"""A varredura da mídia gerenciada só olha `Avid MediaFiles/MXF` e `/UME`.

⛔ POR QUE ESTE TESTE EXISTE (2026-08-22, relatado pelo autor, editor de Media
Composer): renomear `MXF` para `MXF-<projeto>` é a convenção com que editores
guardam o material de um projeto para trabalhar noutro **no mesmo disco** sem
misturar mídia, render e import. A pasta renomeada some para o Avid, e volta a
valer quando é renomeada de volta.

Logo, `MXF-PROJETO X` é mídia que o editor pôs OFFLINE de propósito. O Órbita
varria `Avid MediaFiles` inteira e a lia como se fosse online — e a falha é
silenciosa, porque os MobIDs são os mesmos nas duas cópias: o clipe "resolve" e
ninguém vê que veio da pasta aposentada. Medido num acervo real: 738 de 2327
arquivos estavam na pasta estacionada, e um sync de verdade usou justamente
essa cópia.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from avid.masters import PASTAS_DE_ESSENCIA, pastas_de_midia_do_avid


@pytest.fixture()
def volume(tmp_path, monkeypatch):
    """Um volume falso com as pastas que o Avid enxerga e as que ele ignora."""
    base = tmp_path / "Avid MediaFiles"
    for nome in ("MXF", "UME", "MXF-PROJETO X", "MXF-projetoexemplo-tbm", "OMFI MediaFiles"):
        (base / nome / "1").mkdir(parents=True)

    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("avid.masters.unidades_por_rotulo", dict)
    monkeypatch.setattr("avid.masters.raiz_do_drive",
                        lambda drive, sistema, unidades=None: tmp_path if drive else None)
    return base


def test_so_mxf_e_ume_entram(volume):
    achadas = {Path(q).name for q in pastas_de_midia_do_avid([{"Drive": "VOL (E:)"}])}
    assert achadas == {"MXF", "UME"}


def test_a_pasta_estacionada_fica_de_fora(volume):
    """O caso concreto que motivou tudo: `MXF-<projeto>` é material aposentado."""
    saida = pastas_de_midia_do_avid([{"Drive": "VOL (E:)"}])
    assert not any("MXF-" in Path(q).name for q in saida), (
        "uma pasta 'MXF-<algo>' entrou na varredura — é mídia que o editor pôs "
        "offline de propósito, e lê-la devolve a cópia errada em silêncio"
    )


def test_a_raiz_inteira_nunca_e_devolvida(volume):
    """A regressão exata: devolver `Avid MediaFiles` faz o `rglob` do scan
    alcançar TODAS as irmãs, que é o bug que este módulo conserta."""
    saida = pastas_de_midia_do_avid([{"Drive": "VOL (E:)"}])
    assert str(volume) not in saida
    assert all(Path(q).name in PASTAS_DE_ESSENCIA for q in saida)


def test_sem_mxf_no_volume_devolve_vazio(tmp_path, monkeypatch):
    """Volume com `Avid MediaFiles` mas sem pasta de essência não vira raiz —
    devolver a base aqui reabriria a porta pelas irmãs."""
    (tmp_path / "Avid MediaFiles" / "MXF-SO ESTE").mkdir(parents=True)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("avid.masters.unidades_por_rotulo", dict)
    monkeypatch.setattr("avid.masters.raiz_do_drive",
                        lambda drive, sistema, unidades=None: tmp_path)
    assert pastas_de_midia_do_avid([{"Drive": "VOL (E:)"}]) == []


def test_a_caixa_do_nome_nao_decide(tmp_path, monkeypatch):
    """O disco do autor tem `Avid Mediafiles` (com `f` minúsculo) e a Avid
    documenta `Avid MediaFiles`. No Windows tanto faz; num volume macOS sensível
    a maiúsculas, a diferença sumiria com a mídia inteira."""
    (tmp_path / "Avid Mediafiles" / "mxf" / "1").mkdir(parents=True)
    monkeypatch.setattr("platform.system", lambda: "Windows")
    monkeypatch.setattr("avid.masters.unidades_por_rotulo", dict)
    monkeypatch.setattr("avid.masters.raiz_do_drive",
                        lambda drive, sistema, unidades=None: tmp_path)
    saida = pastas_de_midia_do_avid([{"Drive": "VOL (E:)"}])
    assert len(saida) == 1
    assert Path(saida[0]).name.casefold() == "mxf"


def test_o_mesmo_volume_nao_entra_duas_vezes(volume):
    """Dezenas de masters do mesmo volume são o caso comum; repetir a raiz
    multiplicaria a varredura por N."""
    muitos = [{"Drive": "VOL (E:)"} for _ in range(20)]
    saida = pastas_de_midia_do_avid(muitos)
    assert len(saida) == len(set(saida)) == 2
