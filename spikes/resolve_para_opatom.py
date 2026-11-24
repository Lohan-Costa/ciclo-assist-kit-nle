"""F3 — o Resolve Studio escreve OP-Atom que o Media Composer aceite? (plano 2026-10-31)

O elo desconhecido do ensaio. Esta primeira passada NÃO toca no Media Composer nem na
`Avid MediaFiles` do editor: renderiza numa pasta descartável e só OLHA o que saiu.

Perguntas:
  1. É Studio? (`GetProductName`) — a regra da casa: sem Studio, recusa.
  2. Que presets de fábrica falam de Avid/AAF/MXF?
  3. Com o preset, sai OP-Atom (um arquivo por trilha), com o MESMO material_package_umid
     entre a imagem e o som de um clipe (senão não se agrupa — banco: o ffmpeg erra isso)?
  4. Sai o AAF ao lado?

Banco antes: no Resolve 19 do Windows `SetCurrentRenderFormatAndCodec` devolve False e o
render sai em H.264 mudo, calado; o caminho que funciona é `LoadRenderPreset` de fábrica
(`plugins/resolve-scripting/api-scripting.md`).

Uso:  python spikes/resolve_para_opatom.py <saida> [--preset "Avid AAF"] [--midia arq ...]
      (o Resolve Studio precisa estar ABERTO, com External scripting: Local)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

LAB = os.path.normpath(os.path.join(os.path.dirname(__file__), "..", "..", "..",
                                    "laboratorio-de-midia", "saida", "base", "B01_FORMATOS"))
MIDIA_PADRAO = [os.path.join(LAB, "B01_MOV-PRORES.mov"), os.path.join(LAB, "B01_WAV-BWF.wav")]
PROJETO = "CICLO_SPIKE_OPATOM"
PASTA_PM = "LABORATORIO"


def conectar():
    api = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Blackmagic Design",
                       "DaVinci Resolve", "Support", "Developer", "Scripting")
    os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB",
                          r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll")
    sys.path.append(os.path.join(api, "Modules"))
    import DaVinciResolveScript as dvr  # noqa: E402
    return dvr.scriptapp("Resolve")


def sondar(arquivo: str) -> dict:
    r = subprocess.run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json",
                        arquivo], capture_output=True, text=True, encoding="utf-8", errors="replace")
    try:
        d = json.loads(r.stdout)
    except ValueError:
        return {"erro": r.stderr[:200]}
    fmt = d.get("format", {})
    tags = fmt.get("tags", {})
    return {
        "formato": fmt.get("format_name"),
        "trilhas": [(s.get("codec_type"), s.get("codec_name"), s.get("channels")) for s in d.get("streams", [])],
        "op": tags.get("operational_pattern_ul"),
        "material_umid": tags.get("material_package_umid"),
        "nome_pacote": tags.get("material_package_name") or tags.get("reel_name"),
        "tc": tags.get("timecode"),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("saida")
    ap.add_argument("--preset", default="")
    ap.add_argument("--codec", default="", help='força mxf + este codec pela API depois do preset (ex.: "DNxHD1080p36")')
    ap.add_argument("--preset-arquivo", default="",
                    help="o preset NOSSO (.xml) a injetar por ImportRenderPreset; o nome é o do arquivo")
    ap.add_argument("--midia", nargs="*", default=MIDIA_PADRAO)
    a = ap.parse_args()
    rel: dict = {"quando": time.strftime("%Y-%m-%d %H:%M:%S")}

    r = conectar()
    if not r:
        print("⛔ não consegui falar com o Resolve (aberto? Studio? External scripting: Local?)")
        return 2
    rel["produto"], rel["versao"] = r.GetProductName(), r.GetVersionString()
    print(f"Resolve: {rel['produto']} {rel['versao']}")
    if "studio" not in (rel["produto"] or "").lower():
        print("⛔ não é o Studio — a regra da casa recusa")
        return 3

    pm = r.GetProjectManager()
    pm.GotoRootFolder()
    if PASTA_PM not in (pm.GetFolderListInCurrentFolder() or []):
        pm.CreateFolder(PASTA_PM)
    pm.OpenFolder(PASTA_PM)
    pr = pm.LoadProject(PROJETO) or pm.CreateProject(PROJETO)
    if not pr:
        print("⛔ o projeto não abriu")
        return 4
    if pr.GetTimelineCount() == 0:
        pr.SetSetting("timelineFrameRate", "25")

    if a.preset_arquivo:
        # ⭐ banco (resolve-scripting/api-scripting.md §Render OP-Atom): o preset NOSSO, injetado; o nome é o do
        # ARQUIVO, com maiúsculas. Nunca o do usuário (ele muda) nem o "Avid AAF" de fábrica.
        rel["preset_importado"] = bool(r.ImportRenderPreset(os.path.abspath(a.preset_arquivo)))
        a.preset = os.path.splitext(os.path.basename(a.preset_arquivo))[0]
        print("preset importado:", rel["preset_importado"], a.preset)
    presets = pr.GetRenderPresetList() or []
    rel["presets_avid"] = [p for p in presets if any(k in p.lower() for k in ("avid", "aaf", "mxf", "dnx"))]
    print("presets ligados a Avid/AAF/MXF/DNx:", rel["presets_avid"])
    preset = a.preset or next((p for p in rel["presets_avid"] if "aaf" in p.lower()), "")
    if not preset:
        print("⛔ nenhum preset de AAF; lista inteira:", presets)
        json.dump(rel, open(os.path.join(a.saida, "relatorio.json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        return 5
    rel["preset"] = preset

    mp = pr.GetMediaPool()
    raiz = mp.GetRootFolder()
    velhos = raiz.GetClipList() or []
    if pr.GetTimelineCount():
        mp.DeleteTimelines([pr.GetTimelineByIndex(i) for i in range(1, pr.GetTimelineCount() + 1)])
    if velhos:
        mp.DeleteClips(velhos)
    itens = r.GetMediaStorage().AddItemListToMediaPool(a.midia) or []
    rel["importados"] = [i.GetName() for i in itens]
    video = [i for i in itens if "video" in (i.GetClipProperty("Type") or "").lower()] or itens[:1]
    tl = mp.CreateTimelineFromClips("SPIKE_OPATOM", video)
    pr.SetCurrentTimeline(tl)

    os.makedirs(a.saida, exist_ok=True)
    r.OpenPage("deliver")
    time.sleep(1)
    rel["preset_carregou"] = bool(pr.LoadRenderPreset(preset))
    if a.codec:
        # ⛔ MEDIDO (2026-10-31, 19.1.4): o LoadRenderPreset do preset nosso devolve True e DEIXA o formato anterior
        # (saiu DPX, modo 1). O que vale é forçar pela API depois do load: clipes individuais + mxf (= OP-Atom).
        rel["modo_ok"] = bool(pr.SetCurrentRenderMode(0))
        rel["codec_ok"] = bool(pr.SetCurrentRenderFormatAndCodec("mxf", a.codec))
        print("modo 0:", rel["modo_ok"], "| mxf", a.codec, ":", rel["codec_ok"])
    rel["modo"] = pr.GetCurrentRenderMode()
    pr.SetRenderSettings({"SelectAllFrames": True, "TargetDir": a.saida})
    rel["formato_codec"] = pr.GetCurrentRenderFormatAndCodec()
    job = pr.AddRenderJob()
    rel["trabalho"] = next((x for x in (pr.GetRenderJobList() or []) if x.get("JobId") == job), None)
    print("trabalho:", rel["trabalho"])
    t0 = time.time()
    pr.StartRendering(job)
    while pr.IsRenderingInProgress() and time.time() - t0 < 600:
        time.sleep(1)
    rel["render_s"] = round(time.time() - t0, 1)
    rel["estado"] = pr.GetRenderJobStatus(job)
    pr.DeleteRenderJob(job)
    r.OpenPage("edit")
    print("render:", rel["estado"], f"{rel['render_s']} s")

    saidas = []
    for base, _, nomes in os.walk(a.saida):
        for n in nomes:
            if n == "relatorio.json":
                continue
            caminho = os.path.join(base, n)
            item = {"arquivo": os.path.relpath(caminho, a.saida), "bytes": os.path.getsize(caminho)}
            if n.lower().endswith(".mxf"):
                item.update(sondar(caminho))
            saidas.append(item)
    rel["saidas"] = saidas
    for s in saidas:
        print(" ", s)
    umids = {s.get("material_umid") for s in saidas if s.get("material_umid")}
    rel["veredito"] = {
        "mxf": sum(1 for s in saidas if s["arquivo"].lower().endswith(".mxf")),
        "aaf": sum(1 for s in saidas if s["arquivo"].lower().endswith(".aaf")),
        "umids_distintos": len(umids),
        # O UL do OP-Atom é 060e2b34.04010102.0d010201.10…: o byte 13 (0x10) é o que o diz.
        # ⚠️ A primeira versão procurava a sequência errada e disse False para OP-Atom de verdade.
        "opatom": bool(ops := [s["op"] for s in saidas if s.get("op")])
                  and all(o.replace(".", "").lower()[16:26] == "0d01020110" for o in ops),
    }
    print("veredito:", rel["veredito"])
    json.dump(rel, open(os.path.join(a.saida, "relatorio.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    sys.exit(main())
