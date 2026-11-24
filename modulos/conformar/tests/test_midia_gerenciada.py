"""A mídia GERENCIADA no export: o `.mxf` exato de cada trilha, pelo índice do Avid.

Rodar:

    .venv-win/Scripts/python tests/test_midia_gerenciada.py

Medido em 2026-09-24 contra o DRT nativo do Resolve 19 da mesma timeline: com o índice
(`msmFMID.pmr`), o arquivo de 628 clipes de áudio e dos 108 de vídeo bate com o que o Resolve
ligou ao importar o AAF. Este teste trava a leitura do registro LONG (a essência do ARQUIVO)
e a escolha do arquivo por canal, sem Avid e sem mídia.
"""

from __future__ import annotations

import struct
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from avb_bin.segmentos import montar_midia  # noqa: E402
from media import pmr  # noqa: E402


def _registro_longo(cabeca: bytes, nome: str, tape: str) -> bytes:
    return cabeca + struct.pack("<H", len(nome)) + nome.encode() + struct.pack("<H", len(tape)) + tape.encode()


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<58} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── o índice: LONG = essência do arquivo, SHORT = master ──────")
    arq_v, arq_a1, arq_a2, master = (bytes([n]) * 32 for n in (1, 2, 3, 9))
    corpo = struct.pack("<III", 0x7A9, 0, 3)
    for cab, nome in ((arq_v, "TAKE.mxf"), (arq_a1, "TAKE_A01.mxf"), (arq_a2, "TAKE_A02.mxf")):
        corpo += _registro_longo(cab, nome, "FITA") + master + b"\0\0\0\0"
    with tempfile.TemporaryDirectory() as d:
        mxf = Path(d) / "Avid MediaFiles" / "MXF" / "1"
        mxf.mkdir(parents=True)
        (mxf / "msmFMID.pmr").write_bytes(corpo)
        (Path(d) / "Avid MediaFiles" / "MXF-OUTRO_PROJETO").mkdir()
        regs = pmr.ler_registros(mxf / "msmFMID.pmr")
        ok("três arquivos, todos do MESMO master", {m for _n, _a, m in regs}, {pmr._urn(master)})
        ok("⭐ cada arquivo com a SUA essência", [(n, a == pmr._urn(c)) for (n, a, _m), c in
                                               zip(regs, (arq_v, arq_a1, arq_a2))],
           [("TAKE.mxf", True), ("TAKE_A01.mxf", True), ("TAKE_A02.mxf", True)])
        ok("o `ler` antigo segue igual (nome, master)", pmr.ler(mxf / "msmFMID.pmr")[0],
           ("TAKE.mxf", pmr._urn(master)))
        leitura = pmr.indice_de([str(Path(d) / "Avid MediaFiles")])
        ok("índice por arquivo", len(leitura.por_arquivo), 3)
        ok("⛔ MXF-<projeto> ignorada (mídia que o editor tirou do ar)",
           [Path(p).name for p in leitura.ignoradas], ["MXF-OUTRO_PROJETO"])

        # ⛔ Laboratório A01 (2026-10-11): o editor MOVEU os .mxf da pasta `1-…` para a `3572`; o
        # índice da `1-…` ficou e vinha antes na ordem → o DRT apontava o arquivo que sumiu.
        velha, nova = Path(d) / "Avid MediaFiles" / "MXF" / "1-velha", Path(d) / "Avid MediaFiles" / "MXF" / "3572"
        for p in (velha, nova):
            p.mkdir()
            (p / "msmFMID.pmr").write_bytes(corpo)
        for n in ("TAKE.mxf", "TAKE_A01.mxf", "TAKE_A02.mxf"):
            (nova / n).write_bytes(b"")
        leitura = pmr.indice_de([str(Path(d) / "Avid MediaFiles")])
        ok("⭐ a mesma essência em dois índices: vale a que EXISTE no disco",
           Path(leitura.por_arquivo[pmr._urn(arq_v)]).parent.name, "3572")

    print("\n── o arquivo de cada clipe ───────────────────────────────────")
    ger = {"urn:v": r"D:\MXF\1\TAKE.mxf", "urn:a1": r"D:\MXF\1\TAKE_A01.mxf",
           "urn:a2": r"D:\MXF\1\TAKE_A02.mxf"}
    seg = lambda **k: {"mob_id": "M", "is_gap": False, "is_transition": False,  # noqa: E731
                       "is_audio": False, "source_start_frames": 10, "media_ref": {}, **k}
    leitura = {"segments": [seg(), seg(is_audio=True, canal_arquivo=2, source_slot_id=2),
                            seg(mob_id="SEM", is_audio=True, canal_arquivo=1)],
               "masters": {"M": {"nome": "TAKE", "essencias": {"picture:1": "urn:v",
                                                                "sound:1": "urn:a1",
                                                                "sound:2": "urn:a2"}},
                           "SEM": {"nome": "WAV", "duracao_frames": 100,
                                   "identidade": {"reel": "WAV", "tc_inicio": 0, "tc_fps": 24,
                                                  "fps": 24.0}}}}
    segs, casados, metas = montar_midia(leitura, {}, r"E:\X", gerenciados=ger)
    por = {c["segment_index"]: c for c in casados}
    ok("vídeo → o .mxf de imagem", por[0]["matched_path"], ger["urn:v"])
    ok("⭐ som canal 2 → o .mxf DO CANAL 2", por[1]["matched_path"], ger["urn:a2"])
    ok("⭐ …lido no canal 1 (o .mxf de um canal é MONO)", segs[1]["canal_arquivo"], 1)
    ok("gerenciada = online", (por[1]["gerenciada"], por[1]["offline"]), (True, False))
    ok("sem gerenciada nem AMA → referência offline", (por[2]["offline"], len(metas)), (True, 1))

    arq = {"M": r"F:\AMA\TAKE.mov"}
    _s, casados, _m = montar_midia(leitura, arq, r"E:\X", gerenciados=ger)
    ok("⭐ gerenciada GANHA do AMA (regra do autor, banco pmr §9)",
       casados[0]["matched_path"], ger["urn:v"])
    _s, casados, _m = montar_midia(leitura, arq, r"E:\X")
    ok("sem gerenciada, vale o AMA", casados[0]["matched_path"], arq["M"])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
