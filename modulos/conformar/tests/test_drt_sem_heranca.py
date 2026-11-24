"""O DRT não herda nada da timeline-modelo do esqueleto — em especial, os MARCADORES.

Rodar:

    .venv-win/Scripts/python tests/test_drt_sem_heranca.py

⛔ Medido em 2026-09-25 (Resolve Studio 19.0.0b.59, Windows e Mac): toda timeline gerada chegava
com os 23 marcadores da PRODA_CORTE ("pn - usuario-c", "sonorizar cena"…), até num projeto zerado.
Eles moravam num `Sm2SequenceLockableBlob` do `project.xml` do esqueleto, com o texto dentro de
um blob **zstd** — invisível a uma busca por texto, hex ou zlib. Este teste DESCOMPRIME tudo o
que o DRT carrega (zstd e zlib, em qualquer posição do campo) e procura o que só a timeline-modelo
teria: os autores e as notas dos marcadores.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
import zlib
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp import writer as W  # noqa: E402

#: O que só os marcadores da timeline-modelo (PRODA_CORTE) têm.
HERANCA = ("Editor_Keyboard", "usuario-b", "pn - usuario-c", "sonorizar cena", "AMBIENCIA DE DENTRO")


def conteudo_expandido(caminho_drt: str) -> bytes:
    """Tudo o que o DRT carrega, com cada campo hex aberto e cada stream zstd/zlib descomprimido."""
    import zstandard

    partes = []
    with zipfile.ZipFile(caminho_drt) as z:
        for n in z.namelist():
            dado = z.read(n)
            partes.append(dado)
            for m in re.finditer(rb">([0-9a-fA-F]{16,})<", dado):
                if len(m.group(1)) % 2:
                    continue
                b = bytes.fromhex(m.group(1).decode())
                partes.append(b)
                i = b.find(b"\x28\xb5\x2f\xfd")
                if i >= 0:
                    try:
                        partes.append(zstandard.ZstdDecompressor().decompressobj().decompress(b[i:]))
                    except Exception:  # noqa: BLE001
                        pass
                for off in range(len(b) - 2):
                    if b[off] == 0x78 and b[off + 1] in (0x01, 0x5E, 0x9C, 0xDA):
                        try:
                            partes.append(zlib.decompressobj().decompress(b[off:]))
                        except Exception:  # noqa: BLE001
                            pass
    return b"".join(partes)


def herdado(tudo: bytes) -> list[str]:
    return [t for t in HERANCA
            if any(t.encode(c) in tudo for c in ("utf-8", "utf-16-le", "utf-16-be"))]


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── 1. a função que tira o bloco ──")
    xml = ("<X><Element>\n <BtMetadataLockableBlob DbId=\"a\"><FieldsBlob>00</FieldsBlob>"
           "</BtMetadataLockableBlob>\n</Element><Element>\n <Sm2SequenceLockableBlob DbId=\"b\">"
           "<FieldsBlob>11</FieldsBlob><BlobOwner>c</BlobOwner></Sm2SequenceLockableBlob>\n</Element></X>")
    limpo = W.sem_marcadores_da_timeline(xml)
    ok("tira o item dos marcadores da timeline", "Sm2SequenceLockableBlob" in limpo, False)
    ok("…e deixa os outros itens da lista", "BtMetadataLockableBlob" in limpo, True)

    print("\n── 2. o esqueleto ──")
    esq = W._skeleton_path()
    tudo = conteudo_expandido(esq)
    ok("o esqueleto não tem o bloco dos marcadores", b"Sm2SequenceLockableBlob" in tudo, False)
    ok("⭐ nada dos marcadores da PRODA_CORTE, nem descomprimido", herdado(tudo), [])

    print("\n── 3. um DRT gerado ──")
    segs = [{"clip_name": "B001_C011", "track": 1, "timeline_tc_in": "00:00:00:00",
             "duration_frames": 48, "source_start_frames": 0, "source_fps": 25.0,
             "speed_ratio": 1.0, "is_audio": False, "is_gap": False, "is_transition": False,
             "effects": []}]
    orig = r"E:\RODAGEM\B001_C011.mov"
    mr = [{"segment_index": 0, "matched_path": orig, "rejected": False, "offline": True}]
    meta = {orig: {"nb": 500, "fps": 25.0, "tc": "01:00:00:00", "tc_segundos": 3600.0,
                   "audio_sr": 48000, "audio_canais": 2}}
    with tempfile.TemporaryDirectory() as d:
        saida = W.build_drt(segs, mr, os.path.join(d, "t.drt"), timeline_fps=25.0, offline=meta)
        tudo = conteudo_expandido(saida["output"])
        ok("o DRT foi gerado", saida["clips_generated"], 1)
        ok("o DRT não tem o bloco dos marcadores", b"Sm2SequenceLockableBlob" in tudo, False)
        ok("⭐ nenhum marcador herdado da timeline-modelo", herdado(tudo), [])

        # ⭐ A régua funciona: um esqueleto CONTAMINADO (o bloco devolvido ao project.xml) é
        # pego — senão o teste passaria calado com a busca cega, como a de 2026-09-25.
        import zstandard
        blob = zstandard.ZstdCompressor().compress("Editor_Keyboard pn - usuario-c".encode("utf-8"))
        contaminado = os.path.join(d, "contaminado.drt")
        with zipfile.ZipFile(saida["output"]) as zi, zipfile.ZipFile(contaminado, "w") as zo:
            for n in zi.namelist():
                t = zi.read(n)
                if n.endswith("project.xml"):
                    t += (b"<Element><Sm2SequenceLockableBlob><FieldsBlob>" + b"00" * 9
                          + blob.hex().encode() + b"</FieldsBlob></Sm2SequenceLockableBlob></Element>")
                zo.writestr(n, t)
        ok("a régua ACHA marcador escondido em zstd", herdado(conteudo_expandido(contaminado)),
           ["Editor_Keyboard", "pn - usuario-c"])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
