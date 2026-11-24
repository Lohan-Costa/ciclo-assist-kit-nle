"""O áudio INJETADO como o Media Composer o linka (`avb_bin/audio.autorar_masters`; medido 2026-10-25, MC 25.12 Mac).

Rodar:

    .venv/bin/python tests/test_audio_como_o_avid.py        (Windows: .venv-win/Scripts/python)

WAVs SINTÉTICOS num temporário, autorados pelo caminho do app e lidos de volta. O gabarito são as bins do MC: o
laboratório `nomes_audio_bin_mc2512.avb` (11 WAV) e o link do autor dos 3 WAV do PRODC (14/14 iguais em nome, `_USER` e
cadeia de fontes). Aqui fica o que quebrava:
- o nome com acento como o exFAT LISTA (NFD) derrubava o clone (o cedilha solto não cabe no macroman) — e o MC grava NFC;
- o WAV sem cena herdava o `_USER` do molde (a data torta de quem foi neutralizado, a cena e as trilhas de outro WAV);
- a fonte de baixo é de TAPE com cena e de MÍDIA sem — o molde da variante certa, e sem "AVBTAP" na coluna Tape.
"""

from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import unicodedata
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin import audio  # noqa: E402
from avb_export.reader import topen  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def wav(caminho: Path, canais: int, desc: str = "", data: str = "2026-10-25", hora: str = "09:50:00") -> str:
    """1 s de tom, 48 kHz, 24-bit, com um bext (descrição + data/hora) como o do laboratório."""
    amostra = [struct.pack("<i", int(0.25 * 8388607 * math.sin(2 * math.pi * 1000 * i / 48000)))[:3]
               for i in range(48000)]
    dados = b"".join(a * canais for a in amostra)
    bext = (desc.encode("latin-1").ljust(256, b"\0") + b"\0" * 64 + data.encode().ljust(10, b"\0")
            + hora.encode().ljust(8, b"\0") + struct.pack("<Q", 48000 * 3600 * 10) + b"\0" * (602 - 346))
    fmt = struct.pack("<HHIIHH", 1, canais, 48000, 48000 * 3 * canais, 3 * canais, 24)
    blocos = (b"bext" + struct.pack("<I", len(bext)) + bext + b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"data" + struct.pack("<I", len(dados)) + dados)
    caminho.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(blocos)) + b"WAVE" + blocos)
    return str(caminho)


def masters(bin_avb: str) -> dict:
    fora = {}
    with topen(bin_avb) as f:
        por = {str(m.mob_id): m for m in f.content.mobs}
        for m in f.content.mobs:
            if m.property_data.get("mob_type_id") == 2:
                a = m.property_data.get("attributes")
                user = dict(a["_USER"]) if a is not None and "_USER" in a else {}
                fontes = sorted((type(x.property_data.get("descriptor")).__name__, x.name)
                                for x in audio._fontes_de(m, por))
                fora[m.name] = (user, fontes)
    return fora


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_audio_avid_"))
    # o nome como o exFAT do Mac o lista: NFD
    acento = unicodedata.normalize("NFD", "LAB V07 ação.WAV")
    cena = ("sTAKE=003\r\nsSCENE=FAIXA-W-C3\r\nsFILENAME=FAIXA-W-C3-003.WAV\r\nsTAPE=220407\r\n"
            "sCIRCLED=FALSE\r\n")
    arquivos = [wav(tmp / acento, 1), wav(tmp / "LAB_V03-A.WAV", 1), wav(tmp / "FAIXA-W-C3-003.WAV", 2, cena)]
    r = audio.autorar_masters(arquivos, str(tmp / "saida.avb"), fps=24000 / 1001)
    ok("⭐ os três autorados, nenhum pulado (o acento em NFD derrubava o clone)", (r["clipes"], r["pulados"]), (3, []))
    m = masters(str(tmp / "saida.avb"))
    nfc = "LAB V07 ação.WAV"
    ok("⭐ o nome com acento em NFC, como o MC grava", nfc in m, True)
    ok("…o TapeID com acento no bloco 00 00 + UTF-8 + 00", m.get(nfc, ({}, []))[0].get("TapeID"),
       bytearray(b"\x00\x00" + nfc.encode("utf-8") + b"\x00"))
    ok("⭐ sem cena: só as três colunas do MC, nada do molde", m["LAB_V03-A.WAV"][0],
       {"TapeID": "LAB_V03-A.WAV", "Shoot Date": "2026-10-25 09:50:00", "Soundroll TC Rate": "25"})
    ok("⭐ sem cena: a fonte de baixo é de MÍDIA com o nome do arquivo (molde 1ch semcena)", m["LAB_V03-A.WAV"][1],
       [("MediaDescriptor", "LAB_V03-A.WAV"), ("PCMADescriptor", "LAB_V03-A.WAV")])
    ok("⭐ com cena: a fonte de baixo é de TAPE com o sTAPE (molde 2ch cena)", m["FAIXA-W-C3/003"][1],
       [("PCMADescriptor", "FAIXA-W-C3-003.WAV"), ("TapeDescriptor", "220407")])
    ok("nenhum nome de molde (AVB…/TEMPLATE) sobrou nas fontes",
       [n for _u, fs in m.values() for _c, n in fs if n.startswith(("AVB", "TEMPLATE"))], [])

    # sem a variante (o molde de sempre, de gravador), o WAV sem cena não leva o "AVBTAP" do molde para a coluna Tape
    real = audio.MB.load_bundled_templates

    def sem_variantes():
        return {k: v for k, v in real().items() if not isinstance(k[-1], str) or k[0] != "audio"}

    audio.MB.load_bundled_templates = sem_variantes
    try:
        audio.autorar_masters([arquivos[1]], str(tmp / "reserva.avb"), fps=24000 / 1001)
    finally:
        audio.MB.load_bundled_templates = real
    ok("reserva: molde de gravador para WAV sem cena → a fonte de tape com o nome do arquivo",
       masters(str(tmp / "reserva.avb"))["LAB_V03-A.WAV"][1],
       [("PCMADescriptor", "LAB_V03-A.WAV"), ("TapeDescriptor", "LAB_V03-A.WAV")])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
