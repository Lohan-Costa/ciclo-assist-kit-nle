r"""O writer de DRT com caminho do Windows — o defeito que só aparece fora do macOS.

Rodar:

    .venv-win/Scripts/python tests/test_drp_windows.py

⚠️⚠️ `re.sub(padrão, TEXTO, …)` interpreta `\` no TEXTO de substituição. O writer punha o
caminho do arquivo ali, e `D:\MIDIAS\x.mov` estourava `re.error: bad escape \M` — o writer
nasceu no macOS, onde caminho não tem barra invertida, e nunca tinha gerado um DRT no
Windows até 2026-09-24. Pior que estourar seria o caso sem erro: `\1` ou `\g<0>` num nome
de pasta seriam SUBSTITUÍDOS pelo `re`, e o DRT apontaria para um arquivo que não existe.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp import writer as W  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<52} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    caminhos = [r"D:\MIDIAS DE TESTES\x.mov", r"E:\A\1\g<0>\cena.mxf", r"\\SERVIDOR\share\y.mov"]
    for c in caminhos:
        ok("campo cheio: " + c[:22], W._set_field("<A><M>velho</M></A>", "M", c),
           f"<A><M>{c}</M></A>")
        ok("campo vazio: " + c[:22], W._set_field("<A><M/></A>", "M", c), f"<A><M>{c}</M></A>")

    trilha = '<Sm2TiTrack DbId="x"><Items></Items></Sm2TiTrack>'
    clipe = r"<Clip><MediaFilePath>D:\MIDIAS\1\x.mov</MediaFilePath></Clip>"
    saida = W._make_video_track(trilha, [clipe])
    ok("a trilha leva o clipe com o caminho intacto", clipe in saida, True)

    print("\n── clipe OFFLINE (o original está com o colorista) ───────────")
    import os
    import re
    import tempfile
    import zipfile

    orig = r"F:\CARTAO\A001\B001_C011.braw"
    segs = [{"clip_name": "B001_C011", "track": 1, "timeline_tc_in": "00:00:00:00",
             "duration_frames": 48, "source_start_frames": 438, "source_fps": 23.976,
             "speed_ratio": 1.0, "is_audio": False, "is_gap": False, "is_transition": False,
             "effects": []},
            # Som do mesmo arquivo em A1, lendo o CANAL 4 (o editor usou só esse canal).
            {"clip_name": "B001_C011", "track": 1000, "timeline_tc_in": "00:00:00:00",
             "duration_frames": 48, "source_start_frames": 438, "source_fps": 23.976,
             "speed_ratio": 1.0, "is_audio": True, "is_gap": False, "is_transition": False,
             "effects": [], "canal_arquivo": 4}]
    mr = [{"segment_index": 0, "matched_path": orig, "rejected": False, "offline": True},
          {"segment_index": 1, "matched_path": orig, "rejected": False, "offline": True}]
    meta = {orig: {"nb": 3063, "fps": 23.976, "tc": "01:31:48:11", "tc_segundos": 132203 / 23.976,
                   "audio_sr": 48000, "audio_canais": 2}}
    tocados: list[str] = []
    getmtime, isfile = os.path.getmtime, os.path.isfile
    os.path.getmtime = lambda p: tocados.append(str(p)) or getmtime(p)   # type: ignore
    try:
        with tempfile.TemporaryDirectory() as d:
            saida = W.build_drt(segs, mr, os.path.join(d, "t.drt"), timeline_fps=23.976,
                                offline=meta)
            with zipfile.ZipFile(saida["output"]) as z:
                seq = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()
                              if "SeqContainer" in n)
            campo = lambda t: (re.search(rf"<{t}>(.*?)</{t}>", seq, re.S) or [None, None])[1]  # noqa: E731
            ok("⭐ o clipe offline ENTRA no DRT", saida["clips_generated"], 1)
            ok("aponta para o original", campo("MediaFilePath"), orig)
            ok("reel = nome do arquivo de câmera", campo("MediaReelNumber"), "B001_C011")
            ok("⭐ TC de mídia na taxa EXATA 24000/1001 (como o Resolve grava)",
               round(float(campo("MediaStartTime")), 6), round(132203 * 1001 / 24000, 6))
            ok("In = o offset da bin", campo("In"), "438")
            audio = re.search(r"<Sm2TiAudioClip\b.*?</Sm2TiAudioClip>", seq, re.S).group(0)
            ok("⭐ MediaTrackIdx = CANAL lido − 1 (não a posição da trilha)",
               re.search(r"<MediaTrackIdx>(.*?)</MediaTrackIdx>", audio).group(1), "3")
    finally:
        os.path.getmtime = getmtime
    ok("⛔ o caminho offline NUNCA foi tocado no disco (SMB)", [t for t in tocados if "CARTAO" in t], [])

    print("\n── o esqueleto do Resolve 19 ─────────────────────────────────")
    with zipfile.ZipFile(W._skeleton_path()) as z:
        tudo = b"".join(z.read(n) for n in z.namelist())
    ok("⭐ o padrão é o formato 14 (Resolve 19) — o 19 recusa o 15",
       re.search(rb'DbPrjVer="(\d+)"', tudo).group(1), b"14")
    ok("e ele traz o clipe da TIMELINE (o gerador antigo o apagava)", b"Sm2MpTimelineClip" in tudo, True)

    print("\n── clipe desligado no Avid ───────────────────────────────────")
    desl = [dict(segs[0], disabled=True), dict(segs[1], disabled=True)]
    with tempfile.TemporaryDirectory() as d:
        saida = W.build_drt(desl, mr, os.path.join(d, "t.drt"), timeline_fps=23.976, offline=meta)
        with zipfile.ZipFile(saida["output"]) as z:
            seq = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist()
                          if "SeqContainer" in n)
    ok("⭐ VÍDEO desligado não entra (o Resolve 19 também não o importa)",
       saida["clips_generated"], 0)
    audio = re.search(r"<Sm2TiAudioClip\b.*?</Sm2TiAudioClip>", seq, re.S)
    ok("⭐ SOM desligado entra DESLIGADO (Flags=2, como o nativo)",
       re.search(r"<Flags>(.*?)</Flags>", audio.group(0)).group(1) if audio else None, "2")

    print("\n── FieldsBlob comprimido (Resolve 19) ────────────────────────")
    from tools.inspect_drp import fieldsblob_decode, fieldsblob_encode
    import zstandard
    corpo = bytes([0x81]) + zstandard.ZstdCompressor().compress(b"\x08\x96\x01")
    fb = ((2).to_bytes(4, "big") + len(corpo).to_bytes(4, "big") + corpo).hex()
    dec = fieldsblob_decode(fb)
    ok("flag 0x81 = protobuf zstd, decodificado", dec["fields"][0]["value"], 150)
    ok("e recodificado ainda comprimido", fieldsblob_decode(fieldsblob_encode(dec))["fields"][0]["value"], 150)
    ok("e o cache não guarda o offline depois", orig in W._META_CACHE, False)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
