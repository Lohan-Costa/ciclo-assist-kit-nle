"""O portão de TC do relink Avid → Avid com DROP-FRAME (`media/matcher_masters._tc_em_quadros`).

Rodar:

    .venv/bin/python tests/test_relink_tc_drop_frame.py        (Windows: .venv-win/Scripts/python)

## Por que este teste existe

2026-11-21, laboratório Baselight (projeto LAB BASELIGHT 2997DF, MC 25.12 Mac): o `tc_quadros` do master é a contagem
CONTÍNUA (o `Timecode.start` do AVB; 01;00;00;00 = 107892), e o TC do arquivo chegava como RÓTULO drop-frame
("14:59:50;00", a sondagem do ffprobe). Lido como non-drop, o rótulo saía 54 s depois do master e os DOIS originais
certos foram recusados por "timecode diferente" — 0 de 2 casados, o online parado.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from aaf.masters import Master  # noqa: E402
from media.matcher_masters import _tc_em_quadros, casar_masters  # noqa: E402

F2997 = 30000 / 1001


def master(tc, fps=30, nome="A002C001_251121_R1AB_MOV-PRORES", edit_rate=F2997):
    m = Master(nome=nome, mob_id="", mob_id_urn="", e_audio=False, duracao_frames=600, edit_rate=edit_rate)
    m.tc_quadros, m.tc_fps = tc, fps
    m.caminho_conhecido = None
    return m


def arq(tc, fr=29.97, nome="A002C001_251121_R1AB_MOV-PRORES"):
    return {"path": os.path.join("X:\\nao_existe", nome + ".mov"), "filename": nome + ".mov", "extension": ".mov",
            "duration_ms": 600 * 1001 / round(fr),             # 600 quadros na taxa NTSC
            "frame_rate": fr, "tc_start": tc}


def um(m, *arquivos):
    return casar_masters([m], {"files": list(arquivos)})[0]


def test_rotulo_df_vira_contagem_continua():
    assert _tc_em_quadros("01:00:00;00", F2997) == 107892
    assert _tc_em_quadros("14:59:50;00", F2997) == 1618080          # o A002C001 do laboratório
    assert _tc_em_quadros("15:00:00;00", F2997) == 1618080 + 300    # 15:00 é décimo minuto: não pula
    assert _tc_em_quadros("15:01:00;02", F2997) == 1618080 + 300 + 1800   # o quadro depois de 15:00:59;29 (15:01 pula ;00 e ;01)
    assert _tc_em_quadros("15:10:00;00", F2997) == 1636362          # o décimo minuto não pula
    assert _tc_em_quadros("15:09:55;00", F2997) == 1636362 - 150    # o B002C001 (o master: 1636212)
    assert _tc_em_quadros("01:00:00;00", 59.94) == 215784           # 59,94: 4 rótulos por minuto
    assert _tc_em_quadros("01:00:00:00", F2997) == 108000           # non-drop não muda
    assert _tc_em_quadros("10:00:00:00", 24) == 864000


def test_original_df_casa_com_o_master():
    r = um(master(1618080), arq("14:59:50;00"))
    assert r.arquivo and r.confianca == 1.0, r.motivo


def test_df_de_outro_take_continua_recusado():
    r = um(master(1618080), arq("15:09:55;00"))
    assert r.arquivo is None and "timecode diferente" in r.motivo


def test_23976_nao_muda():
    r = um(master(864000, fps=24, edit_rate=24000 / 1001), arq("10:00:00:00", fr=23.976))
    assert r.arquivo and r.confianca == 1.0


if __name__ == "__main__":
    for n, f in list(globals().items()):
        if n.startswith("test_"):
            f(); print("ok", n)
