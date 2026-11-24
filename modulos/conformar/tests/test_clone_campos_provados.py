"""O clone de master troca a duração, as amostras e a data SÓ onde o valor É o campo (banco, B067; 2026-10-28).

Rodar:  .venv/bin/python tests/test_clone_campos_provados.py        (Windows: .venv-win/Scripts/python)

O molde do WAV sem cena (`audio_1_24bit_1ch_semcena`, 1 s) tem duração 25 — e 25 é também a REFERÊNCIA da Sequence
para o objeto 25; as 48000 amostras são também o `sample_rate`, o `edit_rate` do PCMA e o `_SAVED_AAF_AUDIO_RATE_NUM`.
A troca por valor (`scoped_replace_u32` cru) gravava a duração na referência — um WAV de 7 s quebrava a bin ("bad
index: 175"); com 1 s a referência apontaria calada para outro objeto — e as amostras na taxa. E a duração saía pela
RAZÃO do molde (25/48000, com o quadro de guarda do MC): 175 quadros num WAV de 7 s a 23,976 (o certo é 168).
WAV sintético num temporário; o ffprobe embarcado.
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import wave
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import avb  # noqa: E402
from avb_bin import audio  # noqa: E402
from avb_export import clone as AC, media_bin  # noqa: E402

casos, falhas = 0, []


def ok(rotulo, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {rotulo}")
    else:
        falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")
        print(f"  ✗ {rotulo}: veio {obtido!r}, esperava {esperado!r}")


def main() -> int:
    molde, clipe, _ = media_bin.load_bundled_templates()[("audio", 1, 24, 1, "semcena")]
    print("a prova no molde de 1 s:")
    with avb.open(molde) as f:
        info = AC.clip_info(f, clipe)
        pos = list(f.object_positions)
    raw = open(molde, "rb").read()
    rngs = AC.ranges_for(pos, raw, info["indices"])
    cru = sum(raw[s:e].count(struct.pack("<I", 25)) for s, e in rngs)
    provados = AC.campos_provados(molde, info["indices"], 25, {"length"})
    ok("o 25 aparece 5 vezes; só 4 são duração (a 5ª é a referência da Sequence)", (cru, len(provados)), (5, 4))
    amostras = AC.campos_provados(molde, info["indices"], 48000, {"length", "_SAVED_AAF_AUDIO_LENGTH"})
    cru48 = sum(raw[s:e].count(struct.pack("<I", 48000)) for s, e in rngs)
    ok("o 48000 aparece 8 vezes; só 3 são amostras (não a taxa)", (cru48, len(amostras)), (8, 3))

    print("um WAV sem cena de 7 s, de ponta a ponta:")
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_b067_"))
    w = wave.open(str(tmp / "musica.wav"), "wb")
    w.setnchannels(1), w.setsampwidth(3), w.setframerate(48000)
    w.writeframes(b"\0\0\0" * 48000 * 7)
    w.close()
    try:
        audio.autorar_masters([str(tmp / "musica.wav")], str(tmp / "saida.avb"), fps=24000 / 1001)
        with avb.open(str(tmp / "saida.avb")) as f:
            master = next(m for m in f.content.mobs if m.mob_type == "MasterMob")
            pcma = next(m.descriptor for m in f.content.mobs
                        if type(getattr(m, "descriptor", None)).__name__ == "PCMADescriptor")
            ok("a bin reabre e a duração é 7 s a 23,976 = 168 quadros (não 175)",
               [t.component.length for t in master.tracks], [168])
            ok("o PCMA: 336000 amostras, taxa e edit_rate 48000 intactos",
               (pcma.property_data.get("length"), pcma.property_data.get("sample_rate"),
                pcma.property_data.get("edit_rate")), (336000, 48000.0, 48000.0))
            taxa = {m.attributes.get("_SAVED_AAF_AUDIO_RATE_NUM") for m in f.content.mobs
                    if getattr(m, "attributes", None) and "_SAVED_AAF_AUDIO_RATE_NUM" in m.attributes}
            ok("_SAVED_AAF_AUDIO_RATE_NUM continua 48000 em todos", taxa, {48000})
    except Exception as e:  # noqa: BLE001
        falhas.append(f"a bin do WAV de 7 s quebrou: {e}")
        print(f"  ✗ a bin do WAV de 7 s quebrou: {e}")
    finally:
        for p in tmp.iterdir():
            os.remove(p)
        tmp.rmdir()

    print("o TC do arquivo no master (autor, 2026-10-28):")
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_tc_"))

    def wav_bwf(nome, canais, tr):
        dados = b"\0" * (3 * canais) * 48000 * 3
        fmt = struct.pack("<HHIIHH", 1, canais, 48000, 48000 * 3 * canais, 3 * canais, 24)
        blocos = b"fmt " + struct.pack("<I", len(fmt)) + fmt
        if tr is not None:
            bext = (b"\0" * 320 + b"2026-10-28" + b"10:00:00" + struct.pack("<II", tr & 0xFFFFFFFF, tr >> 32)
                    + b"\0" * 256)
            blocos = b"bext" + struct.pack("<I", len(bext)) + bext + blocos
        blocos += b"data" + struct.pack("<I", len(dados)) + dados
        p = tmp / nome
        p.write_bytes(b"RIFF" + struct.pack("<I", 4 + len(blocos)) + b"WAVE" + blocos)
        return p

    def starts(bin_):
        fora = []
        with avb.open(str(bin_)) as f:
            for m in f.content.mobs:
                if type(getattr(m, "descriptor", None)).__name__ != "PCMADescriptor":
                    continue
                for t in m.tracks:
                    c = t.component
                    for x in ([c] if type(c).__name__ == "SourceClip" else list(getattr(c, "components", []) or [])):
                        if type(x).__name__ == "SourceClip":
                            fora.append(x.start_time)
        return fora

    # 42.120 s de RELÓGIO → 1009870 quadros a 23,976 (a fórmula do banco: relógio → TC de 24 → ×1000/1001); o MC 25.12
    # mostra esse start como 11:41:17:22 (conferido na coluna Start, 2026-10-28). Um gravador a 23,976 carimba o
    # relógio ×1,001 e o MC mostra o TC redondo (11:42:00:00 no som do PRODUCAO-A)
    tr = (11 * 3600 + 42 * 60) * 48000
    try:
        for rotulo, nome, canais, t, esperado in (
                ("sem TC no BWF → 00:00:00:00 (como o LinkFile do MC 25.12)", "m_semtc.wav", 1, None, [0]),
                ("mono com TC → o TC do arquivo", "m_tc.wav", 1, tr, [1009870]),
                ("estéreo 24 bits (molde de start ZERO) → o TC nos dois canais", "e_tc.wav", 2, tr, [1009870] * 2)):
            p = wav_bwf(nome, canais, t)
            audio.autorar_masters([str(p)], str(p.with_suffix(".avb")), fps=24000 / 1001)
            ok(rotulo, starts(p.with_suffix(".avb")), esperado)
    finally:
        for p in tmp.iterdir():
            os.remove(p)
        tmp.rmdir()

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
