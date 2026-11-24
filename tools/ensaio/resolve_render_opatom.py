"""Resolve → OP-Atom para o ensaio M06: projeto novo, os 4 vídeos, o preset NOSSO aplicado DE VERDADE (conferido), render
direto numa pasta numérica nova. `--renderizar` para executar; sem ele, só prepara e mostra o trabalho."""
import sys, os, time, glob, json, subprocess
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\PROGRAMAS COM CLAUDE\laboratorio-de-midia")
from lab.bancadas import resolve as R

PROJETO = "CICLO ENSAIO M06"
PRESET_ARQ = r"D:\PROGRAMAS COM CLAUDE\2 ATIVOS\_CICLO ASSIST\resolve\presets\CICLO-OP-ATOM.xml"
PRESET = "CICLO-OP-ATOM"
CODEC = "DNxHD1080p36"
DESTINO = r"D:\Avid MediaFiles\MXF\202610310"
MIDIA = sorted(glob.glob(r"D:\PROGRAMAS COM CLAUDE\laboratorio-de-midia\saida\multicam\M06_4TOMADAS\CAM 1\*.mov"))
renderizar = "--renderizar" in sys.argv

r = R.conectar()
pm = r.GetProjectManager()
pr = pm.GetCurrentProject()
if not pr or pr.GetName() != PROJETO:
    pm.GotoRootFolder()
    pr = pm.LoadProject(PROJETO) or pm.CreateProject(PROJETO)
assert pr and pr.GetName() == PROJETO, "o projeto não abriu"
print("projeto:", pr.GetName())
if pr.GetTimelineCount() == 0:
    print("timelineFrameRate 25:", pr.SetSetting("timelineFrameRate", "25"),
          "| resolução:", pr.SetSetting("timelineResolutionWidth", "1920"), pr.SetSetting("timelineResolutionHeight", "1080"))

mp = pr.GetMediaPool()
raiz = mp.GetRootFolder()
clipes = raiz.GetClipList() or []
if len(clipes) != 4:
    if clipes: mp.DeleteClips(clipes)
    clipes = r.GetMediaStorage().AddItemListToMediaPool(MIDIA) or []
print("clipes:", [c.GetName() for c in clipes])
assert len(clipes) == 4, "esperava 4 vídeos"
tl = pr.GetTimelineByIndex(1) if pr.GetTimelineCount() else mp.CreateTimelineFromClips("M06_CAM1", clipes)
pr.SetCurrentTimeline(tl)
print("timeline:", tl.GetName(), "| itens V1:", len(tl.GetItemListInTrack("video", 1) or []))

# ⛔ banco 31/10: com o preset JÁ existente o Import devolve False e o Load devolve True SEM aplicar. Apagar e reinjetar.
r.OpenPage("deliver"); time.sleep(1)
if PRESET in (pr.GetRenderPresetList() or []):
    print("apagar o preset velho:", pr.DeleteRenderPreset(PRESET))
print("importar o preset:", r.ImportRenderPreset(PRESET_ARQ))
print("carregar o preset:", pr.LoadRenderPreset(PRESET))
fc = pr.GetCurrentRenderFormatAndCodec(); modo = pr.GetCurrentRenderMode()
print("depois do preset → formato/codec:", fc, "| modo:", modo)
if (fc or {}).get("format") != "mxf" or modo != 0:
    sys.exit("⛔ o preset NÃO foi aplicado (formato/modo errados) — parar, não forçar")
print("codec", CODEC, ":", pr.SetCurrentRenderFormatAndCodec("mxf", CODEC))
os.makedirs(DESTINO, exist_ok=True)
print("destino:", pr.SetRenderSettings({"SelectAllFrames": True, "TargetDir": DESTINO}))
print("formato/codec final:", pr.GetCurrentRenderFormatAndCodec(), "| modo:", pr.GetCurrentRenderMode())
for j in pr.GetRenderJobList() or []: pr.DeleteRenderJob(j["JobId"])
job = pr.AddRenderJob()
trab = next((x for x in (pr.GetRenderJobList() or []) if x.get("JobId") == job), None)
print("trabalho:", json.dumps(trab, ensure_ascii=False, indent=1))
if not renderizar:
    sys.exit(0)

t0 = time.time(); pr.StartRendering(job); ultimo = 0
while pr.IsRenderingInProgress() and time.time() - t0 < 900:
    if time.time() - ultimo > 30:
        ultimo = time.time(); print(f"{time.time()-t0:.0f}s", pr.GetRenderJobStatus(job))
    time.sleep(2)
print("render:", pr.GetRenderJobStatus(job), f"{time.time()-t0:.0f} s")
r.OpenPage("edit")
for f in sorted(os.listdir(DESTINO)):
    p = os.path.join(DESTINO, f)
    s = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_name,bits_per_sample:format_tags=material_package_name:stream_tags=timecode",
                        "-of", "compact", p], capture_output=True, text=True).stdout.replace("\n", " ")
    print(f"{f:40} {os.path.getsize(p):>10}  {s[:200]}")
