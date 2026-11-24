#!/usr/bin/env python3
"""audio_descriptor.py — autora o descriptor PCMA de um master de ÁUDIO AMA genérico do ffprobe.

Espelha video_descriptor.py p/ áudio. Diff de corpus (eng-rev/tools/avb_corpus.py, população AMA
essência = physical_media presente, 50 instâncias) isolou os campos derivados de input; o resto é
boilerplate constante (audio_ref_level=-20, locked=False, dial_norm=27, electro_spatial=2,
SoundEssenceCoding, peak_* zerados, wchar do plugin…). Validado por golden-diff.

Mapa ffprobe -> PCMA (confirmado):
  channels          = ffprobe channels
  quantization_bits = ffprobe bits_per_sample (24, NÃO o sample_fmt s32 do container)
  sample_rate/edit_rate = ffprobe sample_rate
  coding_format     = 1 (PCM int: pcm_s16/s24/s32) | 10 (IEEE float: pcm_f32/f64)
  block_align       = channels * (bits // 8)          (int 24b: ch*3 ; float 32b: ch*4)
  average_bps       = block_align * sample_rate
"""
import json, subprocess
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)


def probe_audio(path, stream="a:0"):
    """ffprobe -> {channels, bits, sample_rate, coding_format}. bits do bits_per_sample/raw."""
    o = subprocess.check_output([
        fftools.ffprobe_exe(), "-v", "error", "-select_streams", stream, "-show_entries",
        "stream=channels,sample_rate,sample_fmt,codec_name,bits_per_sample,bits_per_raw_sample",
        "-of", "json", path])
    s = json.loads(o)["streams"][0]
    codec = s.get("codec_name", "") or ""
    fmt = s.get("sample_fmt", "") or ""
    is_float = codec.startswith("pcm_f") or fmt.startswith(("flt", "dbl"))
    bits = int(s.get("bits_per_sample") or 0) or int(s.get("bits_per_raw_sample") or 0)
    if not bits:                                   # fallback pelo sample_fmt
        bits = {"s16": 16, "s32": 32, "flt": 32, "dbl": 64}.get(fmt.rstrip("p"), 16)
    return {"channels": int(s["channels"]), "bits": bits, "sample_rate": float(s["sample_rate"]),
            "coding_format": 10 if is_float else 1}


def patch_pcma(descriptor, meta):
    """Muta o property_data de um PCMADescriptor pyavb (clonado de um SKELETON) p/ o formato do
    arquivo (meta = probe_audio). Só toca nos campos derivados; boilerplate fica do skeleton."""
    pd = descriptor.property_data
    ch = meta["channels"]; bits = meta["bits"]; sr = meta["sample_rate"]
    pd["channels"] = ch
    pd["quantization_bits"] = bits
    pd["sample_rate"] = sr
    pd["edit_rate"] = sr
    pd["coding_format"] = meta["coding_format"]
    pd["block_align"] = ch * (bits // 8)
    pd["average_bps"] = ch * (bits // 8) * int(sr)
    # SoundEssenceCoding: label SMPTE presente SÓ no PCM IEEE-float (coding_format=10), ausente no int
    # (descoberto pelo golden-diff: 9/9 float têm, 124/124 int não). Sem ele o float pode vir errado.
    attrs = pd.get("attributes")
    if attrs is not None:
        if meta["coding_format"] == 10:
            attrs["SoundEssenceCoding"] = bytearray.fromhex("060e2b34040101010e04020201010000")
        elif "SoundEssenceCoding" in attrs:
            del attrs["SoundEssenceCoding"]
    return descriptor


if __name__ == "__main__":
    import sys
    print(json.dumps(probe_audio(sys.argv[1]), indent=2))
