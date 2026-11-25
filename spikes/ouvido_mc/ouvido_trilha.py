"""Uma trilha de som por vez: cópia da _SEQ (Bin.uid e MobID da sequência novos, nome '<seq> A<n>') com só a A<n>
habilitada (_ENBLSTATE), aberta no MC e exportada pelo preset do lab (iUseEnabledTracks). Mede o tom (sem as claques).
Uso: ouvido_trilha.py <saida> <alvo> <sequência> <n>..."""
import json, os, random, subprocess, sys, time
from pathlib import Path
import numpy as np
sys.path[:0] = ['plugins/media-composer/servico', 'motor']
sys.path.insert(0, "/Volumes/SSD/PROGRAMAS COM CLAUDE/piloto")
from piloto import olhos
from avb_export.reader import topen
from avb.mobid import MobID
from avid.mcapi import MediaComposer
from avid.acoes import Acoes
PROJ = Path("/Volumes/SSD/MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/PROJETO/LAB COR MC")
PREF = bytes.fromhex("060a2b340101010501010f1013000000")
SAI, alvo, nome = sys.argv[1], sys.argv[2], sys.argv[3]
PASTA = PROJ / "OUVIDO v01"; PASTA.mkdir(exist_ok=True)
origem = PROJ / alvo / f"{alvo}_SEQ.avb"

def tons(arq):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", arq, "-map", "0:a:0", "-f", "f32le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.float32).astype(float)
    SPF = 2002
    out = []
    for q in range(0, int(len(x) / SPF) - 12, 24):          # meio segundo por vez
        seg = x[q * SPF:(q + 24) * SPF]
        salto = np.flatnonzero(np.abs(np.diff(seg)) > 0.12)
        b = [0] + [int(i) for i in salto] + [len(seg)]
        i0, i1 = max(zip(b, b[1:]), key=lambda ab: ab[1] - ab[0])
        seg = seg[i0 + 120:i1 - 120]
        if len(seg) < 4800:
            continue
        mag = np.abs(np.fft.rfft(seg * np.hanning(len(seg)))) * 4 / len(seg)
        fr = np.fft.rfftfreq(len(seg), 1 / 48000); db = 20 * np.log10(mag + 1e-12)
        pk = sorted({(round(float(fr[i]) / 10) * 10, round(float(db[i]))) for i in range(1, len(db) - 1)
                     if db[i] > -45 and db[i] >= db[i - 1] and db[i] >= db[i + 1]})
        out.append((q, pk))
    return out

with MediaComposer(timeout=60) as mc:
    a = Acoes(mc)
    for n in [int(v) for v in sys.argv[4:]]:
        dest = PASTA / f"{alvo} A{n}.avb"
        if dest.exists():
            print("JA_EXISTE", dest); continue
        with topen(str(origem)) as f:
            seq = next(m for m in f.content.mobs if getattr(m, "mob_type", "") == "CompositionMob" and m.name == nome)
            for t in seq.tracks:
                if getattr(t.component, "media_kind", "") == "sound":
                    t.session_attr["_ENBLSTATE"] = 1 if t.index == n else 0
            seq.name = f"{nome} A{n}"
            seq.mob_id = MobID(bytes_le=PREF + os.urandom(16))
            f.content.uid = random.getrandbits(63)
            f.write(str(dest))
        mc.abrir_bin(str(dest))
        s = [x for x in mc.itens_de(str(dest), flags=("sequences",)) if x.name == f"{nome} A{n}"][0]
        arq = a.export_file(s.mob_id, SAI, f"{alvo.replace(' ', '_')}_A{n}", preset="DLPC_LAB_DNXLB", espera_s=120)
        dlg = [w["titulo"] for w in olhos.janelas("AvidMediaComposer") if w["titulo"] != "Bins.1" and not w["titulo"].startswith("Avid Media Composer  -")]
        try:
            mc.fechar_bin(str(dest))
        except Exception as e:
            print("  não fechou", e)
        if dlg:
            print("FOTO", olhos.foto_da_tela(SAI, f"dialogo_A{n}"), dlg); sys.exit(1)
        print(f"A{n}:", [(q, pk) for q, pk in tons(arq) if pk], flush=True)
