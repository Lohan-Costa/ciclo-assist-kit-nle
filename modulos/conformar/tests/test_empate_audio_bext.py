"""O empate entre WAVs explicado pelo bext (`media/bwf.identidade` + `matcher_masters._explicar_empate_de_audio`).

Rodar:  .venv/bin/python tests/test_empate_audio_bext.py

O caso real (PRODUCAO-A, 2026-09-27): `24;23;20 CB.wav` do Pro Tools (24 bits) e `24_23_20 CB.wav` convertido pelo
ffmpeg (16 bits) empatam no nome — mesma `referencia` e mesma `amostra_inicial` no bext. O empate CONTINUA do editor
(memória `empate-no-casamento-e-do-editor`); o que se confere aqui é a explicação: "mesmo áudio, 24 × 16 bits" ou
"áudios DIFERENTES". WAVs sintéticos num temporário.
"""
from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from media import bwf  # noqa: E402
from media.matcher_masters import casar_masters  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def wav(caminho: Path, origem: str, ref: str, amostra: int, bits: int) -> Path:
    bext = (b"\0" * 256 + origem.encode().ljust(32, b"\0") + ref.encode().ljust(32, b"\0")
            + b"2023-12-14" + b"10:40:54" + struct.pack("<II", amostra & 0xFFFFFFFF, amostra >> 32) + b"\0" * 256)
    fmt = struct.pack("<HHIIHH", 1, 2, 48000, 48000 * 2 * bits // 8, 2 * bits // 8, bits)
    blocos = b"bext" + struct.pack("<I", len(bext)) + bext + b"fmt " + struct.pack("<I", len(fmt)) + fmt
    blocos += b"data" + struct.pack("<I", 4) + b"\0" * 4
    caminho.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(blocos)) + b"WAVE" + blocos)
    return caminho


def empate(pasta: Path, *arquivos: Path):
    master = SimpleNamespace(nome="24_23_20 CB.wav", mob_id="", duracao_frames=None, edit_rate=None, segmentos=1,
                             e_audio=True)
    indice = {"files": [{"path": str(a), "filename": a.name, "duration_ms": None} for a in arquivos]}
    return casar_masters([master], indice)[0]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_empate_"))

    print("identidade:")
    a = wav(tmp / "24;23;20 CB.wav", "Pro Tools", "aaiHRlPyUkPk", 31628024, 24)
    i = bwf.identidade(str(a))
    ok("origem", i.get("origem"), "Pro Tools")
    ok("referência", i.get("referencia"), "aaiHRlPyUkPk")
    ok("amostra inicial (TC em amostras)", i.get("amostra_inicial"), 31628024)
    ok("bits / canais", (i.get("bits"), i.get("canais")), (24, 2))
    grande = wav(tmp / "grande.wav", "x", "y", (1 << 32) + 7, 24)
    ok("amostra inicial acima de 32 bits", bwf.identidade(str(grande)).get("amostra_inicial"), (1 << 32) + 7)
    nao = tmp / "nao.wav"
    nao.write_bytes(b"isto nao e wav")
    ok("arquivo que não é WAV → vazio", bwf.identidade(str(nao)), {})

    print("empate — o MESMO áudio em duas cópias:")
    d1 = tmp / "mesmo"
    d1.mkdir()
    a = wav(d1 / "24;23;20 CB.wav", "Pro Tools", "aaiHRlPyUkPk", 31628024, 24)
    b = wav(d1 / "24_23_20 CB.wav", "", "aaiHRlPyUkPk", 31628024, 16)
    r = empate(d1, a, b)
    ok("continua AMBÍGUO (o editor escolhe)", (r.ambiguo, r.arquivo), (True, None))
    ok("o motivo diz que é o mesmo áudio", "MESMO áudio" in r.motivo, True)
    ok("o motivo diz a diferença (24 × 16 bits)", "24 bits × 16 bits" in r.motivo, True)
    ok("cada candidato leva o bext", [c.get("bext", {}).get("bits") for c in r.candidatos], [24, 16])

    print("empate — áudios DIFERENTES com o mesmo nome:")
    d2 = tmp / "versoes"
    d2.mkdir()
    a = wav(d2 / "24;23;20 CB.wav", "Pro Tools", "aaiHRlPyUkPk", 31628024, 24)
    b = wav(d2 / "24_23_20 CB.wav", "Pro Tools", "aaiOUTRAMIXk", 31628024, 24)
    r = empate(d2, a, b)
    ok("continua AMBÍGUO", (r.ambiguo, r.arquivo), (True, None))
    ok("o motivo diz que são áudios diferentes", "áudios DIFERENTES" in r.motivo, True)

    print("empate sem bext — o motivo de antes:")
    d3 = tmp / "sem"
    d3.mkdir()
    a = wav(d3 / "24;23;20 CB.wav", "", "", 0, 24)
    b = wav(d3 / "24_23_20 CB.wav", "", "", 0, 16)
    r = empate(d3, a, b)
    ok("sem referência no bext, nada se afirma", r.motivo, "2 arquivos igualmente plausíveis")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
