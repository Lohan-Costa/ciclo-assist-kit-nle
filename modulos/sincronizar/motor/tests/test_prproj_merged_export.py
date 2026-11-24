"""
O MERGED CLIP NO EXPORT DE PRODUÇÃO — `ExportOptions.merged_clips`.

Até 2026-09-16 o `_build_merged_clip` só era chamado pela sonda
(`.dev/sonda-premiere/gerar_merged.py`), por subclasse. O formato validado na GUI pela
sonda é o que a flag liga aqui: a bin normal intocada, mais uma sub-bin com um
"<câmera> - Merged" por câmera de cada tomada.

Os testes do validador são por MUTAÇÃO: cada um estraga o arquivo do jeito que a
regra existe para pegar, e confere que ela pega.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prproj.builder import ExportOptions, _B, _LABEL_MERGED_NAME, _MERGED_BIN_NAME
from prproj.validate import validate_root
from sync.model import CameraAngle, CameraGroup, Daily, Project, SoundClip, Take


def _arquivo(tmp: Path, nome: str) -> Path:
    p = tmp / nome
    p.write_bytes(b"x")
    return p


def _diaria(tmp: Path, nome: str = "D", fps: float = 24.0) -> Daily:
    """Duas câmeras numa tomada de som de 3 canais, e uma câmera ÓRFÃ."""
    cam_a = CameraAngle(path=_arquivo(tmp, f"{nome}_A001.mov"), fps=fps,
                        duration_frames=240, timeline_start_frames=0,
                        sync_offset_frames=30, audio_channels=2)
    cam_b = CameraAngle(path=_arquivo(tmp, f"{nome}_B001.mov"), fps=fps,
                        duration_frames=200, timeline_start_frames=10,
                        sync_offset_frames=40, audio_channels=2)
    orfa = CameraAngle(path=_arquivo(tmp, f"{nome}_A002.mov"), fps=fps,
                       duration_frames=100, timeline_start_frames=600,
                       sync_offset_frames=600, audio_channels=2)
    snd = SoundClip(path=_arquivo(tmp, f"{nome}_T01.wav"), sample_rate=48000,
                    duration_ms=15000, channels=3, timeline_start_frames=0)
    return Daily(
        camera_groups=[CameraGroup(cameras=[cam_a, orfa], name="CAM A", id="a"),
                       CameraGroup(cameras=[cam_b], name="CAM B", id="b")],
        takes=[Take(sound=snd, cameras=[cam_a, cam_b])],
        orphan_cameras=[orfa],
        name=nome, fps=fps)


def _montar(project: Project, merged: bool) -> ET.Element:
    xml = _B(project, ExportOptions(merged_clips=merged)).build()
    return ET.fromstring(xml.split("?>", 1)[1])


def _bins(root: ET.Element) -> dict[str, ET.Element]:
    return {b.findtext("./ProjectItem/Name"): b for b in root.iter("BinProjectItem")}


def _itens_da_bin(root: ET.Element, bin_el: ET.Element) -> list[ET.Element]:
    por_uid = {e.get("ObjectUID"): e for e in root if e.get("ObjectUID")}
    return [por_uid[i.get("ObjectURef")]
            for i in bin_el.findall("./ProjectItemContainer/Items/Item")]


def _seqs_merged(root: ET.Element) -> list[ET.Element]:
    return [s for s in root.iter("Sequence")
            if s.findtext(".//BE.Sequence.IsMergedClip") == "true"]


def test_sem_a_flag_nada_de_merged(tmp_path):
    """O default é o formato de hoje — nenhum usuário recebe merged sem pedir."""
    root = _montar(Project(name="P", groups=[_diaria(tmp_path)]), merged=False)
    assert _seqs_merged(root) == []
    assert _MERGED_BIN_NAME not in _bins(root)


def test_com_a_flag_um_merged_por_camera_da_tomada_e_o_orfao_fica_de_fora(tmp_path):
    root = _montar(Project(name="P", groups=[_diaria(tmp_path)]), merged=True)

    assert len(_seqs_merged(root)) == 2
    itens = _itens_da_bin(root, _bins(root)[_MERGED_BIN_NAME])
    nomes = sorted(i.findtext("./ProjectItem/Name") for i in itens)
    assert nomes == ["D_A001 - Merged", "D_B001 - Merged"]   # sem D_A002, a órfã
    for i in itens:
        assert i.findtext(".//Column.PropertyText.Label") == _LABEL_MERGED_NAME


def test_a_bin_normal_nao_muda_com_a_flag(tmp_path):
    """Os merged se SOMAM: a mídia crua e a sequência continuam lá, iguais."""
    def filhos(merged: bool) -> list[str]:
        root = _montar(Project(name="P", groups=[_diaria(tmp_path)]), merged)
        return [i.tag + ":" + (i.findtext("./ProjectItem/Name") or "")
                for i in _itens_da_bin(root, _bins(root)["D"])]

    sem, com = filhos(False), filhos(True)
    assert com[:-1] == sem
    assert com[-1] == f"BinProjectItem:{_MERGED_BIN_NAME}"


def test_o_arquivo_com_merged_passa_no_validador(tmp_path):
    """Inclui a regra da mídia na bin: os MasterClips internos do merged são exceção."""
    root = _montar(Project(name="P", groups=[_diaria(tmp_path)]), merged=True)
    assert validate_root(root) == []


def test_cada_diaria_usa_o_proprio_fps_no_merged(tmp_path):
    """⚠️ A sonda montava o merged antes de `_build_sequence` fixar a diária — com duas
    diárias de fps diferentes, a segunda herdaria os ticks da primeira."""
    d24 = _diaria(tmp_path, "X", fps=24.0)
    d30 = _diaria(tmp_path, "Y", fps=30.0)
    root = _montar(Project(name="P", groups=[d24, d30]), merged=True)

    # Vários ClipLoggingInfo levam o mesmo nome; alguns com INT64_MAX (= sem taxa).
    sem_taxa = str(2**63 - 1)
    taxa: dict[str, set[str]] = {}
    for cli in root.iter("ClipLoggingInfo"):
        if cli.findtext("MediaFrameRate") not in (None, sem_taxa):
            taxa.setdefault(cli.findtext("ClipName"), set()).add(cli.findtext("MediaFrameRate"))
    assert taxa["X_A001.mov - Merged"] == {str(round(254016000000 / 24))}
    assert taxa["Y_A001.mov - Merged"] == {str(round(254016000000 / 30))}


# ── O validador, por mutação ─────────────────────────────────────────────────

def test_validador_acusa_o_ciclo_que_fecha_o_premiere(tmp_path):
    """Aponta o SubClip de vídeo da sequência merged para o MasterClip DE BIN do merged
    — o engano registrado no banco (prproj/escrita.md §2)."""
    root = _montar(Project(name="P", groups=[_diaria(tmp_path)]), merged=True)
    item = _itens_da_bin(root, _bins(root)[_MERGED_BIN_NAME])[0]
    mc_da_bin = item.find("MasterClip").get("ObjectURef")

    sc = next(s for s in root.iter("SubClip")
              if (s.findtext("Name") or "").endswith(" - Merged"))
    sc.find("MasterClip").set("ObjectURef", mc_da_bin)

    assert any("ciclo" in p for p in validate_root(root))


def test_sem_a_marca_MergeClipUtils_o_interno_vira_recovered_clips(tmp_path):
    """Prova que é a marca `MZ.MergeClipUtils.*` — e não outra coisa — que isenta os
    MasterClips internos da regra de mídia sem bin."""
    root = _montar(Project(name="P", groups=[_diaria(tmp_path)]), merged=True)
    for props in root.iter("Properties"):
        for p in list(props):
            if p.tag.startswith("MZ.MergeClipUtils."):
                props.remove(p)

    assert any("Recovered Clips" in p for p in validate_root(root))
