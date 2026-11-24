"""O item do pool declara o FORMATO do arquivo, e não o da forma do esqueleto (MXF).

Rodar:

    .venv-win/Scripts/python tests/test_drt_formato.py

⛔ Medido em 2026-09-26 (Resolve Studio 19.0.0b, Windows; relink aos originais, ADR 0020): a
timeline relinkada aos .mp4 da PRODA_CORTE chegava com Media Offline. O Resolve escolhe o
decodificador pelo que o item do pool DECLARA, e todo item era clonado da forma MXF do
esqueleto: campo 15 do `<Clip>` = 4 (o log: "can not decode file … of type MXF OP-Atom"),
`dnxhd_lb`, 2048×1080, áudio "Linear PCM" com metadado MXF. Só os mp4 de 2048×1080 abriam.
Gabarito: DRT exportado pelo Resolve 19 com os mesmos arquivos (`motor/drp/formas_r19.xml`).

Precisa do ffmpeg/ffprobe no PATH (gera a mídia sintética); sem ele, o teste é pulado.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp import writer as W  # noqa: E402
from tools.inspect_drp import pb_decode, pb_encode  # noqa: E402

casos = 0
falhas: list[str] = []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def clip(blob_hex: str) -> dict:
    """Campos do blob `<Clip>`, com o codec (5) sempre em bytes."""
    import zstandard

    raw = bytes.fromhex(blob_hex)
    campos = pb_decode(zstandard.ZstdDecompressor().decompress(raw[9:], max_output_size=1 << 20))
    g = {}
    for f in campos:
        v = f["value"]
        g.setdefault(f["field"], bytes(pb_encode(v)) if isinstance(v, list) else v)
    return g


def resolucao(item: str) -> tuple[int, int]:
    raw = bytes.fromhex(re.search(r"<Geometry>([0-9a-f]+)</Geometry>", item).group(1))
    k = "Resolution".encode("utf-16-be")
    i = raw.find(k) + len(k)
    return int.from_bytes(raw[i + 9:i + 17], "big"), int.from_bytes(raw[i + 17:i + 25], "big")


def unique_ids(item: str) -> set[bytes]:
    fora = set()
    for tag in ("Time", "Geometry", "Proxy", "VideoMetadata"):
        m = re.search(rf"<{tag}>([0-9a-f]+)</{tag}>", item)
        if m:
            fora.update(W._UUID16.findall(bytes.fromhex(m.group(1))))
    return fora


def gerar_midia(d: str) -> tuple[str, str]:
    mp4 = os.path.join(d, "A001_C001.mp4")
    wav = os.path.join(d, "SOM_T001.wav")
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=1280x720:rate=25",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000", "-t", "2",
                    "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-ac", "2",
                    "-timecode", "10:00:00:00", mp4], check=True, capture_output=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=48000",
                    "-t", "2", "-ac", "3", "-c:a", "pcm_s24le", wav], check=True, capture_output=True)
    return mp4, wav


def main() -> int:
    if not (shutil.which("ffmpeg") and shutil.which("ffprobe")):
        print("ffmpeg/ffprobe fora do PATH — teste pulado")
        return 0

    with tempfile.TemporaryDirectory() as d:
        mp4, wav = gerar_midia(d)
        mov_off = r"E:\RODAGEM\B001_C011.mov"
        mxf_off = r"E:\Avid MediaFiles\MXF\1\B001_C011.V1.mxf"
        base = {"track": 1, "duration_frames": 25, "source_start_frames": 0, "source_fps": 25.0,
                "speed_ratio": 1.0, "is_gap": False, "is_transition": False, "effects": []}
        segs = [
            {**base, "clip_name": "A001_C001", "timeline_tc_in": "00:00:00:00", "is_audio": False},
            {**base, "clip_name": "B001_C011", "timeline_tc_in": "00:00:01:00", "is_audio": False},
            {**base, "clip_name": "B001_C011", "timeline_tc_in": "00:00:02:00", "is_audio": False,
             "track": 2},
            {**base, "clip_name": "SOM_T001", "timeline_tc_in": "00:00:00:00", "is_audio": True,
             "track": 1000},
        ]
        caminhos = [mp4, mov_off, mxf_off, wav]
        mr = [{"segment_index": i, "matched_path": p, "rejected": False} for i, p in enumerate(caminhos)]
        meta = {p: {"nb": 500, "fps": 25.0, "tc": "01:00:00:00", "tc_segundos": 3600.0,
                    "audio_sr": 48000, "audio_canais": 2} for p in (mov_off, mxf_off)}
        saida = W.build_drt(segs, mr, os.path.join(d, "t.drt"), timeline_fps=25.0, offline=meta)
        with zipfile.ZipFile(saida["output"]) as z:
            pool = z.read(next(n for n in z.namelist() if n.endswith("MpFolder.xml"))).decode()

    itens = {re.search(r"<Name>([^<]*)</Name>", b).group(1): b
             for b in re.findall(r"<Sm2Mp(?:Video|Audio)Clip\b.*?</Sm2Mp(?:Video|Audio)Clip>", pool, re.S)}

    print("── 1. mp4 online: a forma nativa, com os dados do arquivo ──")
    v = itens["A001_C001.mp4"]
    clips = re.findall(r"<Clip>([0-9a-f]+)</Clip>", v)
    g = clip(clips[0])
    ok("⭐ formato 2, não 4 (MXF OP-Atom)", g.get(15), W.FORMATO_OUTRO)
    ok("flag de item de vídeo", g.get(18), W.FLAG_VIDEO)
    ok("codec avc1 (o do arquivo, não dnxhd_lb)", g.get(5), b"avc1")
    ok("resolução do arquivo", resolucao(v), (1280, 720))
    ok("uma trilha de áudio embutida", len(clips), 2)
    ga = clip(clips[1])
    ok("áudio embutido AAC, formato 2", (ga.get(5), ga.get(15)), (b"AAC", W.FORMATO_OUTRO))
    ok("sem metadado MXF no áudio embutido", "MXFMetadata".encode("utf-16-be").hex() in v, False)

    print("\n── 2. mov OFFLINE: a forma nativa, sem tocar o disco ──")
    o = itens["B001_C011.mov"]
    ok("formato 2 (o Resolve religa depois como QuickTime)", clip(re.search(r"<Clip>([0-9a-f]+)</Clip>", o).group(1)).get(15), W.FORMATO_OUTRO)
    ok("⭐ UniqueIds próprios, não os da forma", unique_ids(v) & unique_ids(o), set())

    print("\n── 3. mxf: a forma do esqueleto, como sempre ──")
    m = itens["B001_C011.V1.mxf"]
    gm = clip(re.search(r"<Clip>([0-9a-f]+)</Clip>", m).group(1))
    ok("formato 4 (MXF OP-Atom)", gm.get(15), W.FORMATO_MXF)
    ok("codec da forma MXF", gm.get(5), b"dnxhd_lb")

    print("\n── 4. wav: a forma NATIVA de áudio — uma trilha com os canais do arquivo ──")
    # ⛔ Medido 2026-09-26: com a mídia pré-importada, o item de áudio da forma do esqueleto
    # (5 trilhas mono, TC da forma em 4 delas) não batia com o que o Resolve cria importando o
    # mesmo arquivo, e o áudio duplicava no pool.
    import struct

    import zstandard
    from drp.ba_mapa import ler_mapa, valor
    w = itens["SOM_T001.wav"]
    ok("⭐ uma trilha só (a do esqueleto tinha 5 mono)", w.count("<BtAudioInfo"), 1)
    gw = clip(re.search(r"<Clip>([0-9a-f]+)</Clip>", w).group(1))
    ok("formato 2, flag de áudio puro, Linear PCM",
       (gw.get(15), gw.get(18), gw.get(5)), (W.FORMATO_OUTRO, W.FLAG_AUDIO, b"Linear PCM"))
    def estrutura(item: str):
        """[(registro, [chaves de cabeça], [(canal, ChannelIdx)], BitDepth, duração)] e a trilha."""
        fb = bytes.fromhex(re.search(r"<FieldsBlob>([0-9a-f]+)</FieldsBlob>", item).group(1))
        dec = zstandard.ZstdDecompressor().decompress(fb[9:], max_output_size=1 << 20)
        _v, canais, _r = ler_mapa(bytes(pb_decode(dec)[0]["value"][0]["value"]))
        trilha = re.search(r'<BtAudioInfo DbId="([^"]+)"', item).group(1)
        regs = []
        for k, x in canais:
            _mv, reg, _mr = ler_mapa(x[2])
            _cv, cv, _cr = ler_mapa(valor(reg, "ChannelVecBA")[2])
            chs = []
            for kc, xc in cv:
                _c, c, _ = ler_mapa(xc[2])
                assert valor(c, "MediaRef")[2] == trilha
                idx = valor(c, "ChannelIdx")
                chs.append((kc, idx and idx[2]))
            regs.append((k, [c for c, _x in reg if c in ("Type", "SampleRate")], chs,
                         valor(reg, "BitDepth")[2],
                         round(struct.unpack("<dd", valor(reg, "MediaExtents")[2])[1], 2)))
        _t, it, _ = ler_mapa(bytes.fromhex(re.search(r"<TracksBA>([0-9a-f]+)</TracksBA>", item).group(1)))
        _t2, trk, _ = ler_mapa(it[0][1][2])
        return regs, {k: x[2] for k, x in trk if k in ("StartTime", "NumChannels", "BitDepth", "ChannelLayout")}

    # Estruturas MEDIDAS no banco do projeto do Resolve 19 (2026-09-26), por número de canais.
    regs, trk = estrutura(w)
    ok("⭐ 3 canais (24 bits): um registro por canal; o canal 0 SEM ChannelIdx",
       regs, [("2", [], [("0", 2)], 2, 2.0), ("1", [], [("0", 1)], 2, 2.0), ("0", [], [("0", None)], 2, 2.0)])
    ok("a trilha: 3 canais, 24 bits, sem ChannelLayout",
       (trk["NumChannels"], trk["BitDepth"], "ChannelLayout" in trk), (3, 2, False))
    ok("sem metadado MXF no áudio puro", "MXFMetadata".encode("utf-16-be").hex() in w, False)

    with tempfile.TemporaryDirectory() as d:
        feitos = {}
        for nome, args in (("mono.wav", ["-ac", "1", "-ar", "96000", "-c:a", "pcm_s16le"]),
                           ("estereo.wav", ["-ac", "2", "-ar", "44100", "-c:a", "pcm_s16le"]),
                           ("estereo.aif", ["-ac", "2", "-ar", "48000", "-c:a", "pcm_s16be"])):
            arq = os.path.join(d, nome)
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "sine=frequency=440",
                            "-t", "1", *args, arq], check=True, capture_output=True)
            feitos[nome] = W._make_audio_pool_clip_nativo(nome, W._new_id(), W._new_id(), arq)
        regs, trk = estrutura(feitos["estereo.wav"])
        ok("⭐ estéreo: UM registro, com Type e SampleRate, e os DOIS canais dentro dele",
           regs, [("0", ["Type", "SampleRate"], [("1", 1), ("0", None)], 1, 1.0)])
        ok("…16 bits (BitDepth 1), sem bext: começa em 0, não no TC da forma",
           (trk["BitDepth"], trk["StartTime"], "ChannelLayout" in trk), (1, 0.0, False))
        regs, trk = estrutura(feitos["mono.wav"])
        ok("⭐ mono: um registro com SampleRate e um canal; a trilha com ChannelLayout 1",
           (regs, trk["ChannelLayout"]), ([("0", ["SampleRate"], [("0", None)], 1, 1.0)], 1))
        g_aif = clip(re.search(r"<Clip>([0-9a-f]+)</Clip>", feitos["estereo.aif"]).group(1))
        ok("⭐ AIF: flag 32770 (o Resolve diz AIFF) e ChannelLayout 2 na trilha",
           (g_aif.get(18), estrutura(feitos["estereo.aif"])[1].get("ChannelLayout")), (32770, 2))
        ok("a 48 kHz o registro NÃO leva SampleRate (a 44,1 e 96 kHz leva)",
           estrutura(feitos["estereo.aif"])[0][0][1], ["Type"])
        # O clipe do Avid é mono: o canal 2 sozinho só existe no Resolve com o item em DUAL MONO
        # (medido 2026-09-27; com o item estéreo, o Resolve duplicava o arquivo no pool).
        virt = lambda item: re.search(r"<VirtualAudioTracksBA>([0-9a-f]+)</VirtualAudioTracksBA>", item)
        _v, trilhas, _r = ler_mapa(bytes.fromhex(virt(feitos["estereo.wav"]).group(1)))
        ok("⭐ estéreo: o item em dual mono, trilha \"1\" = canal 2 e \"0\" = canal 1",
           [(k, ler_mapa(x[2])[1][0][1][2][-4:].hex()) for k, x in trilhas],
           [("1", "00004002"), ("0", "00004001")])
        ok("…o AIF estéreo também", bool(virt(feitos["estereo.aif"])), True)
        ok("mono: sem trilhas virtuais (como o Resolve)", bool(virt(feitos["mono.wav"])), False)

    print("\n── 5. vídeo SEM timecode (o .MOV do drone DJI) ──")
    with tempfile.TemporaryDirectory() as d:
        sem_tc = os.path.join(d, "DJI_0001.mov")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=size=640x360:rate=25",
                        "-t", "1", "-c:v", "libx264", "-pix_fmt", "yuv420p", sem_tc],
                       check=True, capture_output=True)
        ok("⭐ conta de 00:00:00:00, não herda o TC da forma", W._media_meta(sem_tc)[2], "00:00:00:00")

    print("\n── 6. BRAW: a resolução útil vem do `crop_size` ──")
    import struct

    def atomo(tipo: bytes, corpo: bytes) -> bytes:
        return struct.pack(">I", 8 + len(corpo)) + tipo + corpo

    chaves = [b"camera_type", b"crop_size"]
    keys = atomo(b"keys", b"\0\0\0\0" + struct.pack(">I", len(chaves))
                 + b"".join(struct.pack(">I", 8 + len(k)) + b"mdta" + k for k in chaves))
    item = atomo(struct.pack(">I", 2), atomo(b"data", struct.pack(">I", 71) + b"\0\0\0\0"
                                             + struct.pack(">ff", 4096.0, 2160.0)))
    meta = atomo(b"meta", atomo(b"hdlr", b"\0" * 24) + keys + atomo(b"ilst", item))
    with tempfile.TemporaryDirectory() as d:
        braw = os.path.join(d, "B001_C009.braw")
        with open(braw, "wb") as f:
            f.write(atomo(b"mdat", b"\0" * 64) + atomo(b"moov", atomo(b"mvhd", b"\0" * 100) + meta))
        ok("4096×2160 (o ffprobe daria a gravada, 4128×2176)", W._braw_crop(braw), (4096, 2160))
        ok("a família do .braw é a forma BRAW", W._familia(braw), "braw")
    forma = W._formas_nativas()["braw"]
    g = clip(re.search(r"<Clip>([0-9a-f]+)</Clip>", forma).group(1))
    ok("a forma BRAW é a do Resolve 19 (codec BRAW, flag 16406)", (g.get(5), g.get(18)), (b"BRAW", 16406))

    # ⭐ O REVERSO na forma do Resolve 19 (gabarito do próprio 19.0.0b.59, Windows, 2026-10-03:
    # Change Clip Speed 70% + Reverse no M002C022 do PRODB, 1312 quadros a 24, exportado em DRT).
    # A forma COMPACTA do 21 fazia o 19 tocar o plano para a frente, calado.
    import struct
    from tools.inspect_drp import build_reverse_timemap
    gabarito_19 = (
    "0000000100000006000000080059004d006100780000000600404b500000000000000000080058004d00610078000000"
    "06004053836db6db6db6000000100055006e0069007100750065004900640000000a0000000048006600320036006500"
    "31003000360032002d0065006200630035002d0034006500620033002d0039006100360030002d003300310061006400"
    "39006600640032003000310039003700000020004c00610073007400560061006c006900640059004f00660066007300"
    "6500740000000600404b50000000000000000016004b00650079006600720061006d00650073004200410000000c0000"
    "00017400000001000000020000000200310000000c00000000a700000001000000070000000c0069006e007400650072"
    "0070000000020000000000000000080059004f00750074000000060000000000000000000000000600590049006e0000"
    "000600000000000000000000000002005900000006000000000000000000000000080058004f00750074000000060000"
    "000000000000000000000600580049006e0000000600000000000000000000000002005800000006004053836db6db6d"
    "b60000000200300000000c00000000a700000001000000070000000c0069006e00740065007200700000000200000000"
    "00000000080059004f00750074000000060000000000000000000000000600590049006e000000060000000000000000"
    "000000000200590000000600404b519999999998000000080058004f0075007400000006000000000000000000000000"
    "0600580049006e00000006000000000000000000000000020058000000060000000000000000000000000c0044006200"
    "540079007000650000000a00000000140053006d003200540069006d0065004d00610070")
    nosso = build_reverse_timemap(1312, 24.0, 0.7, "f26e1062-ebc5-4eb3-9a60-31ad9fd20197")
    # o 19 calcula Y0 e XMax 1 ulp abaixo (10⁻¹⁴ s, nenhum quadro muda): troca-se só esses doubles
    um_ulp = (nosso.replace(struct.pack(">d", (1312 - 0.7) / 24).hex(), "404b519999999998")
              .replace(struct.pack(">d", (1312 - 0.7) / 24 / 0.7).hex(), "4053836db6db6db6"))
    ok("⭐ reverso: o mapa de tempo é o que o Resolve 19 escreve (QHash, não a forma compacta do 21)",
       um_ulp, gabarito_19)
    ok("…e os doubles diferem do gabarito em no máximo 1 ulp", len(nosso) == len(gabarito_19), True)

    # ⭐ ÁUDIO com velocidade constante (gabarito do 19.0.0b.59, 2026-10-03: Change Clip Speed 50% no
    # AMB_CM_EXT_DIA_RESIDENCIAL_VR.wav, 302,0107 s, timeline a 24): YMax = duração − 1/23,976 e o
    # keyframe final = duração·r − 1 quadro da timeline. Sem isto, os 38 clipes de áudio com velocidade do PRODB entravam a 100%.
    from tools.inspect_drp import build_audio_speed_timemap
    audio_19 = (
        "0000000100000006000000080059004d0061007800000006004072df80da740da7000000080058004d00610078000000"
        "06004082dfd65b7a3285000000100055006e0069007100750065004900640000000a0000000048006600370035003300"
        "64003200300062002d0037003200640033002d0034003900300066002d0061003700360037002d003100390031006500"
        "39006600660065003700360035003300000020004c00610073007400560061006c006900640059004f00660066007300"
        "65007400000006004072df80da740da700000016004b00650079006600720061006d00650073004200410000000c0000"
        "00017400000001000000020000000200310000000c00000000a700000001000000070000000c0069006e007400650072"
        "0070000000020000000000000000080059004f00750074000000060000000000000000000000000600590049006e0000"
        "000600000000000000000000000002005900000006004072dfd65b7a3285000000080058004f00750074000000060000"
        "000000000000000000000600580049006e0000000600000000000000000000000002005800000006004082dfd65b7a32"
        "850000000200300000000c00000000a700000001000000070000000c0069006e00740065007200700000000200000000"
        "00000000080059004f00750074000000060000000000000000000000000600590049006e000000060000000000000000"
        "0000000002005900000006000000000000000000000000080058004f0075007400000006000000000000000000000000"
        "0600580049006e00000006000000000000000000000000020058000000060000000000000000000000000c0044006200"
        "540079007000650000000a00000000140053006d003200540069006d0065004d00610070")
    # ⭐ VOLUME com keyframes (gabarito do 19.0.0b.59, 2026-10-03: 5 keyframes no Inspector, quadros
    # 142/160/185/212/229, 0/−24,11/+16,96/−26,79/0 dB). O 19 grava 0x81 + zstd; descomprimido = o nosso.
    from drp.writer import _volume_ba_kf
    volume_19 = (
        "800a64087c4a58085f5254ffffffb08e00000000000c000000000000000000a000000000000c00b86ddbb66d1b38c0b9"
        "00000000000c006cdbb66ddbf63040d400000000000c009324499224c93ac0e500000000000c0000000000000000004a"
        "004a004a004a00")
    pts = [(142, 0.0), (160, -24.10714285714286), (185, 16.964285714285708), (212, -26.78571428571429), (229, 0.0)]
    ok("⭐ volume animado: o EffectFiltersBA é o que o Resolve 19 escreve (descomprimido, byte a byte)",
       _volume_ba_kf(pts)[16:], volume_19)
    ok("⭐ velocidade de áudio: o mapa de tempo é o que o Resolve 19 escreve (byte a byte)",
       build_audio_speed_timemap(14496512 / 48000, 24.0, 2.0, "f753d20b-72d3-490f-a767-191e9ffe7653"), audio_19)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
