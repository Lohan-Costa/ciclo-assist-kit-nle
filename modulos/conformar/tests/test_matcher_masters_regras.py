"""O casador do religar do app (`media/matcher_masters`) com as regras do autor de 2026-11-22, as mesmas dos outros dois:

    .venv/bin/python tests/test_matcher_masters_regras.py        (Windows: .venv-win/Scripts/python)

- REEL do daily é critério quando nenhum arquivo tem o nome do master (BL08, P4);
- cópias IDÊNTICAS valem como uma (P9), dizendo qual foi usada;
- EMPATE só se resolve pela imagem do daily (P2); sem separar, continua do editor — com as notas nos candidatos;
- o mesmo RÓTULO de TC com e sem drop-frame é o mesmo TC (P7: `16:58:50;00` × `16:58:50:00`).
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from aaf.masters import Master  # noqa: E402
from media import confirmacao as C  # noqa: E402
from media import matcher_masters as MM  # noqa: E402


def _arq(d, rel, dado=b"x"):
    p = os.path.join(d, rel)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    open(p, "wb").write(dado)
    return {"path": p, "filename": os.path.basename(p), "duration_ms": 10000.0, "frame_rate": 24.0}


def _master(nome, daily):
    return Master(nome=nome, mob_id="", mob_id_urn="", duracao_frames=240, edit_rate=24.0, origem=daily)


def test_reel_copias_e_imagem():
    with tempfile.TemporaryDirectory() as d:
        daily = _arq(d, "DAILIES/CENA12_T3.mov")["path"]
        o7 = _arq(d, "ORIG/B001C007.mov")
        with mock.patch.object(C, "reel_do_arquivo", lambda c: "B001C007"):
            r = MM.casar_masters([_master("CENA12_T3", daily)], {"files": [o7]})[0]
        assert r.arquivo == o7["path"] and r.metodo == "reel" and "reel" in r.motivo, r

        a, b = _arq(d, "A/C001.mov", b"igual"), _arq(d, "BACKUP/C001.mov", b"igual")
        r = MM.casar_masters([_master("C001", _arq(d, "DAILIES/C001.mov")["path"])], {"files": [a, b]})[0]
        assert r.arquivo == a["path"] and "cópias idênticas" in r.motivo and len(r.candidatos) == 2, r

        d1, d2 = _arq(d, "DIA01/A004.mov", b"1"), _arq(d, "DIA02/A004.mov", b"2")
        dl = _arq(d, "DAILIES/A004.mov")["path"]
        q = {dl: bytes([100] * 6912), d1["path"]: bytes([100] * 6912), d2["path"]: bytes([160] * 6912)}
        with mock.patch.object(C.confirmar_pela_imagem, "__defaults__", (lambda c, t: q[c],)):
            r = MM.casar_masters([_master("A004", dl)], {"files": [d1, d2]})[0]
        assert r.arquivo == d1["path"] and r.metodo == "imagem" and not r.ambiguo, r
        assert {c["path"]: c["provas"]["imagem"] for c in r.candidatos} == {d1["path"]: 1.0, d2["path"]: 0.765}
        q[d2["path"]] = bytes([101] * 6912)                     # parecidos: continua do editor
        with mock.patch.object(C.confirmar_pela_imagem, "__defaults__", (lambda c, t: q[c],)):
            r = MM.casar_masters([_master("A004", dl)], {"files": [d1, d2]})[0]
        assert r.arquivo is None and r.ambiguo and "não separa" in r.motivo, r


def test_rotulo_igual_com_e_sem_drop_frame():
    m = Master(nome="A002C001", mob_id="", mob_id_urn="", tc_quadros=1833900, tc_fps=30)
    assert MM._portao_tc(m, {"tc_start": "16:58:50;00", "frame_rate": 30000 / 1001}) is True
    assert MM._portao_tc(m, {"tc_start": "15:00:00;00", "frame_rate": 30000 / 1001}) is False


def test_o_render_da_cor_e_um_trecho_do_original():
    """BL09 pelo MC (2026-11-23): o master do render (47 quadros, TC 17:00:02:12, reel C001C003) reprovava no original
    pela duração e pelo TC. Casa pelo reel COM o deslocamento, no topo da revisão; fora do original, continua recusado."""
    from prproj import originais as O
    fps = 24000 / 1001
    with tempfile.TemporaryDirectory() as d:
        rnd = _arq(d, "RENDER/C001C003_COR.mov")["path"]
        org = {**_arq(d, "ORIG/C001C003.mov"), "duration_ms": 240 * 1001 / 24 , "frame_rate": fps,
               "tc_start": "17:00:00:00"}
        sondas = {rnd: {"ok": True, "fps": fps, "dur_s": 47 / fps, "tc": "17:00:02:12", "reel": "C001C003"},
                  org["path"]: {"ok": True, "fps": fps, "dur_s": 240 / fps, "tc": "17:00:00:00", "reel": "C001C003"}}
        m = Master(nome="C001C003_COR", mob_id="", mob_id_urn="", duracao_frames=47, edit_rate=fps, origem=rnd,
                   tc_quadros=tc(17, 0, 2, 12), tc_fps=24)
        with mock.patch.object(C, "reel_do_arquivo", lambda c: "C001C003"), \
             mock.patch.object(O, "sondar", lambda c: sondas.get(c, {"ok": False})):
            r = MM.casar_masters([m], {"files": [org]})[0]
            assert r.arquivo == org["path"] and r.metodo == "reel" and r.trecho["desloc_quadros"] == 60, r
            assert r.precisa_de_revisao and "render da cor" in r.motivo and r.to_dict()["trecho"], r
            sondas[rnd] = {**sondas[rnd], "tc": "17:00:09:00"}              # o fim passa do original: não é trecho
            r = MM.casar_masters([m], {"files": [org]})[0]
            assert r.arquivo is None and r.trecho is None, r


def test_o_ponto_anda_no_original():
    """BL09 pelo MC (2026-11-23): `montar_midia` troca o render pelo original e o In (contado desde o início do render)
    anda os 60 quadros — medido no Baselight: sem isso o plano entrou em 4–43 e a conferência aprovou."""
    from avb_bin import segmentos as SG
    from prproj import originais as O
    fps = 24000 / 1001
    rnd, org = "/r/C001C003_COR.mov", "/o/C001C003.mov"
    sondas = {rnd: {"ok": True, "fps": fps, "dur_s": 47 / fps, "tc": "17:00:02:12"},
              org: {"ok": True, "fps": fps, "dur_s": 240 / fps, "tc": "17:00:00:00"}}
    seg = {"source_start_frames": 4, "media_ref": {"local_path": rnd, "source_fps": fps}}
    with mock.patch.object(O, "sondar", lambda c: sondas[c]), mock.patch.object(os.path, "isfile", lambda c: True):
        SG._deslocar_trecho(seg, org, fps)
        assert seg["source_start_frames"] == 64 and seg["trecho"]["desloc_quadros"] == 60, seg
        mesmo = {"source_start_frames": 4, "media_ref": {"local_path": org, "source_fps": fps}}
        SG._deslocar_trecho(mesmo, org, fps)                        # o próprio original: nada anda
        assert mesmo["source_start_frames"] == 4 and "trecho" not in mesmo


def tc(h, m, s, f, n=24):
    return ((h * 60 + m) * 60 + s) * n + f


if __name__ == "__main__":
    for t in (test_reel_copias_e_imagem, test_rotulo_igual_com_e_sem_drop_frame,
              test_o_render_da_cor_e_um_trecho_do_original, test_o_ponto_anda_no_original):
        t()
        print("ok", t.__name__)
    sys.exit(0)
