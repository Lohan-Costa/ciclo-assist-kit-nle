"""O BWF de gravador como o Media Composer o grava ao linkar (`media/bwf.como_o_avid`; medido 2026-10-25, MC 25.12).

Rodar:

    .venv/bin/python tests/test_bwf.py        (Windows: .venv-win/Scripts/python)

WAVs SINTÉTICOS num temporário (um bloco `bext` e um `iXML` como os do Sound Devices MixPre-6 do PRODC): o nome do
master é CENA/TAKE (sem a extensão), o `_USER` na ordem do MC, as trilhas renumeradas pela ordem do arquivo, o tape; sem
cena e take, o nome do arquivo e só TapeID, Shoot Date (o bext ou a data do arquivo, sem zeros) e Soundroll TC Rate —
como a bin do laboratório `nomes_audio_bin_mc2512.avb` (MC 25.12 Mac).
"""

from __future__ import annotations

import os
import struct
import sys
import time
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from media import bwf  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def wav(caminho: Path, desc: str = "", ixml: str = "", data="2022-04-07", hora="16:29:30") -> Path:
    blocos = b""
    if desc or data:
        bext = desc.encode("latin-1").ljust(256, b"\0") + b"\0" * 64 + data.encode().ljust(10, b"\0") \
            + hora.encode().ljust(8, b"\0") + b"\0" * (602 - 338)
        blocos += b"bext" + struct.pack("<I", len(bext)) + bext
    fmt = struct.pack("<HHIIHH", 1, 1, 48000, 48000 * 3, 3, 24)
    blocos += b"fmt " + struct.pack("<I", len(fmt)) + fmt
    if ixml:
        x = ixml.encode()
        blocos += b"iXML" + struct.pack("<I", len(x)) + x + (b"\0" if len(x) & 1 else b"")
    blocos += b"data" + struct.pack("<I", 6) + b"\0" * 6
    caminho.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(blocos)) + b"WAVE" + blocos)
    return caminho


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_bwf_"))
    desc = ("sSPEED=030.000-ND\r\nsTAKE=002\r\nsUBITS=$00000000\r\nsSCENE=faixa-w-C4\r\n"
            "sFILENAME=FAIXA-W-C4-002.WAV\r\nsTAPE=220407\r\nsCIRCLED=FALSE\r\nsTRK3=BOOM\r\nsTRK4=LAPELA\r\n")
    ixml = ("<BWFXML><PROJECT>04-07-22</PROJECT><SCENE>faixa-w-C4</SCENE><TAKE>002</TAKE><TAPE>220407</TAPE>"
            "<TRACK_LIST><TRACK_COUNT>2</TRACK_COUNT><TRACK><CHANNEL_INDEX>3</CHANNEL_INDEX>"
            "<INTERLEAVE_INDEX>1</INTERLEAVE_INDEX><NAME>BOOM</NAME></TRACK>"
            "<TRACK><CHANNEL_INDEX>4</CHANNEL_INDEX><INTERLEAVE_INDEX>2</INTERLEAVE_INDEX><NAME>LAPELA</NAME></TRACK>"
            "</TRACK_LIST></BWFXML>")
    r = bwf.como_o_avid(str(wav(tmp / "FAIXA-W-C4-002.WAV", desc, ixml)))
    ok("⭐ o nome do master é CENA/TAKE, sem a extensão", r["nome"], "faixa-w-C4/002")
    ok("⭐ o _USER como o MC grava, na mesma ordem", list(r["user"].items()),
       [("UBITS", "$00000000"), ("TapeID", "FAIXA-W-C4-002.WAV"), ("Shoot Date", "2022-04-07 16:29:30"),
        ("Scene", "faixa-w-C4"), ("Take", "002"), ("TRK1", "BOOM"), ("TRK2", "LAPELA"),
        ("Production", "04-07-22"), ("Circled", "no")])
    ok("a fonte de tape = sTAPE", r["tape"], "220407")
    r = bwf.como_o_avid(str(wav(tmp / "sem_ixml.WAV", desc)))
    ok("sem iXML: os sTRKn do bext NÃO viram TRK (LAB_V01 no MC 25.12)", [k for k in r["user"] if k.startswith("TRK")],
       [])
    ok("…e sem Production", "Production" in r["user"], False)
    so_ixml = ("<BWFXML><PROJECT>LAB-PROD</PROJECT><SCENE>LAB-CENA2</SCENE><TAKE>002</TAKE><TRACK_LIST><TRACK>"
               "<CHANNEL_INDEX>1</CHANNEL_INDEX><NAME>CANAL1</NAME></TRACK></TRACK_LIST></BWFXML>")
    r = bwf.como_o_avid(str(wav(tmp / "LAB_V02-A.WAV", "", so_ixml, data="2026-10-25", hora="09:50:00")))
    ok("cena só no iXML, sem sFILENAME e sem INTERLEAVE_INDEX: TapeID = o arquivo, sem TRK (LAB_V02)", r["user"],
       {"TapeID": "LAB_V02-A.WAV", "Shoot Date": "2026-10-25 09:50:00", "Scene": "LAB-CENA2", "Take": "002",
        "Production": "LAB-PROD"})
    r = bwf.como_o_avid(str(wav(tmp / "LAB_V03-A.WAV", "", "", data="2026-10-25", hora="09:50:00")))
    ok("⭐ sem cena, com bext: o arquivo com a extensão e as três colunas do MC (LAB_V03)", r,
       {"nome": "LAB_V03-A.WAV", "tape": None,
        "user": {"TapeID": "LAB_V03-A.WAV", "Shoot Date": "2026-10-25 09:50:00", "Soundroll TC Rate": "25"}})
    simples = wav(tmp / "LAB_V04 plain.wav", "", "", data="", hora="")
    quando = time.mktime((2026, 10, 25, 9, 45, 19, 0, 0, -1))
    os.utime(simples, (quando, quando))
    r = bwf.como_o_avid(str(simples))
    ok("⭐ sem bext: o Shoot Date é a data do ARQUIVO, sem zeros (LAB_V04: 2026-10-25 9:45:19)",
       (r["nome"], r["user"]["Shoot Date"]), ("LAB_V04 plain.wav", "2026-10-25 9:45:19"))
    r = bwf.como_o_avid(str(wav(tmp / "LAB V07 ação.WAV", "", "", data="2026-10-25", hora="09:50:00")))
    ok("com acento: o TapeID em 00 00 + UTF-8 + 00, como o MC (LAB_V07)", r["user"]["TapeID"],
       bytearray(b"\x00\x00LAB V07 a\xc3\xa7\xc3\xa3o.WAV\x00"))
    ok("…e nada do molde: só as três colunas", sorted(r["user"]), ["Shoot Date", "Soundroll TC Rate", "TapeID"])
    ok("arquivo que não é WAV: None", bwf.como_o_avid(str(Path(__file__))), None)
    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
