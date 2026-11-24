"""O `.prproj` escrito para o Premiere 2023 (`prproj/alvo.py`)."""

from __future__ import annotations

import gzip
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prproj.alvo import _CAMPOS_NOVOS, _VERSOES_2023, adaptar
from prproj.builder import ExportOptions, _B, build_prproj
from prproj.validate import validate, validate_root
sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_prproj_merged_export import _diaria  # noqa: E402  (a mesma diária de teste)
from sync.model import Project


def _xml(tmp_path) -> str:
    projeto = Project(name="P", groups=[_diaria(tmp_path)])
    return _B(projeto, ExportOptions(merged_clips=True)).build()


def _raiz(xml: str) -> ET.Element:
    return ET.fromstring(xml.split("?>", 1)[1])


def test_alvo_25_devolve_intacto(tmp_path):
    xml = _xml(tmp_path)
    assert adaptar(xml, "25") is xml


def test_alvo_desconhecido_recusa(tmp_path):
    with pytest.raises(ValueError):
        adaptar(_xml(tmp_path), "2019")


def test_2023_rebaixa_as_versoes_e_tira_os_campos_novos(tmp_path):
    antes = _raiz(_xml(tmp_path))
    depois = _raiz(adaptar(_xml(tmp_path), "2023"))

    # A premissa: o builder escreve, hoje, as classes que a tabela cobre.
    presentes = {o.tag for o in antes}
    assert {"Project", "Media", "MasterClip", "SubClip", "VideoClipTrackItem",
            "AudioClipTrackItem", "VideoTrackGroup"} <= presentes

    for obj in depois:
        if obj.tag in _VERSOES_2023:
            assert obj.get("Version") == _VERSOES_2023[obj.tag], obj.tag
        for campo in _CAMPOS_NOVOS.get(obj.tag, ()):
            assert obj.find(campo) is None, f"{obj.tag}/{campo}"
    assert depois.find("Project").get("Version") == "41"
    # nada além disso some: o número de objetos é o mesmo
    assert len(list(depois)) == len(list(antes))


def test_2023_troca_a_captura_pela_classe_que_ele_conhece(tmp_path):
    raiz = _raiz(adaptar(_xml(tmp_path), "2023"))
    assert raiz.find("DummyCaptureSettings") is None
    cap = raiz.find("CaptureSettings")
    assert cap.get("Version") == "10"
    assert cap.get("ClassID") == "328c2aa2-47f9-4211-805b-b6a6dbd4ca29"
    ref = raiz.find("ProjectSettings/CaptureSettings").get("ObjectRef")
    assert cap.get("ObjectID") == ref
    assert cap.findtext("RecordModuleDisplayName") == "DV"


def test_2023_passa_no_validador(tmp_path):
    assert validate_root(_raiz(adaptar(_xml(tmp_path), "2023"))) == []


def test_build_prproj_aplica_o_alvo(tmp_path):
    saida = tmp_path / "x.prproj"
    build_prproj(Project(name="P", groups=[_diaria(tmp_path)]), saida,
                 ExportOptions(merged_clips=True, premiere_alvo="2023"))
    texto = gzip.open(saida, "rt", encoding="utf-8").read()
    assert 'Version="41"' in texto and "DummyCaptureSettings" not in texto
    assert validate(saida) == []
