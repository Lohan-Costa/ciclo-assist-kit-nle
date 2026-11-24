import json, sys, time
from pathlib import Path
from cicloassist.midia import audio, asr
src = sys.argv[1]; out = Path(sys.argv[2])
wav = out.with_suffix('.wav')
if not wav.exists(): audio.mixar([src], wav)
t=time.time(); falas = asr.transcrever(wav); dt=time.time()-t
json.dump({'segundos':dt,'falas':[f.como_dicionario() for f in falas]}, open(out,'w'), ensure_ascii=False, indent=1)
print('ok', len(falas), round(dt,1))
