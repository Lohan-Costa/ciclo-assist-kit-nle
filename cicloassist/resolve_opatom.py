"""Vídeo → OP-Atom pelo DaVinci Resolve Studio: a operação 3 do ensaio.

Plano: `docs/plano/2026-10-31-operacoes-do-ensaio.md`. O Resolve renderiza cada clipe em
MXF OP-Atom (um arquivo de vídeo e um por canal de som) direto numa pasta NOVA de
`Avid MediaFiles\\MXF`, e o Media Composer passa a ver a mídia como gerenciada.

Tudo aqui é conhecimento do banco (`plugins/resolve-scripting/api-scripting.md` §Render
OP-Atom; `transversal/operacoes.md`), não descoberta nova:

- ⛔⛔ **`LoadRenderPreset` pode devolver True SEM aplicar** (31/10): com o preset já importado,
  o `Import` dá False e o `Load` dá True deixando dpx/modo 1. Forçar o codec na mão dá OP-Atom
  sem o resto do preset — nome de arquivo = quadro do TC (`00090250.mxf`), som 16 bits. ⇒ a
  dança é SEMPRE apagar → importar → carregar → CONFERIR (mxf + modo 0, individual) → só então
  o codec. Divergiu, PARAR — nunca forçar.
- ⛔ **Pasta só com dígitos**, senão o MC não indexa; convenção do autor: a de vídeo termina em
  **0**, o som dela em **1** (`protocolos/msm/README.md`). E pasta NOVA: MXF que cai numa pasta
  já indexada não é relido, e o mob importado dele nasce sem offset (o crash de 31/10).
- ⭐ O nome do arquivo é o do CLIPE (o preset grava assim), e é o que o MC mostra.

Diferenças de propósito em relação ao script do ensaio (`tools/ensaio/resolve_render_opatom.py`):
a fila de render do editor NÃO é apagada (só o NOSSO trabalho sai, no fim); a timeline é
NOVA, nunca a dele; os clipes que já estão no Media Pool são reaproveitados pelo caminho.

⚠️ Roda num processo FILHO (como `resolve.py`): o pior caso da API congela o filho, nunca o
serviço. Ele fala por linhas JSON — `{"etapa": …}` enquanto anda e `{"fim": …}` ou
`{"erro": …}` no final.
"""

from __future__ import annotations

import datetime
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from . import resolve as _resolve

#: O preset NOSSO, versionado no repo — nunca o do usuário, nunca o de fábrica.
PRESET_ARQ = Path(__file__).resolve().parent.parent / "resolve" / "presets" / "CICLO-OP-ATOM.xml"
PRESET = "CICLO-OP-ATOM"

#: O codec de cada altura de quadro. Só o que já foi medido no MC (1080, 31/10).
CODECS = {1080: "DNxHD1080p36"}

#: As taxas que o Resolve aceita em `timelineFrameRate` como texto, pelo que o ffprobe diz.
TAXAS = {"24000/1001": "23.976", "24/1": "24", "25/1": "25", "30000/1001": "29.97", "30/1": "30",
         "50/1": "50", "60000/1001": "59.94", "60/1": "60"}

VIDEOS = {".mov", ".mp4", ".mxf", ".m4v"}

#: Sem uma linha do filho por este tempo, ele é dado como travado (ele avisa a cada 5 s no render).
SILENCIO_MAXIMO_S = 300


class ConversaoFalhou(RuntimeError):
    """A frase vai ao modelo como está."""


def videos_da_pasta(pasta: str | Path, extensoes: set[str] | None = None) -> list[Path]:
    """Os vídeos de uma pasta e das subpastas, em ordem; pula pasta de trabalho (`_…`) e `._*`."""
    extensoes = extensoes or VIDEOS
    raiz = Path(pasta)
    achados = []
    for p in sorted(raiz.rglob("*")):
        partes = p.relative_to(raiz).parts
        if any(x.startswith("_") or x.startswith(".") for x in partes):
            continue
        if p.is_file() and p.suffix.lower() in extensoes:
            achados.append(p)
    return achados


def pasta_nova(mxf: str | Path, hoje: datetime.date | None = None) -> Path:
    """A próxima pasta de VÍDEO livre em `…\\MXF`: AAAAMMDD + (vazio, 1, 2…) + "0", e cujo par de
    som (o mesmo nome terminando em 1) também esteja livre."""
    base = (hoje or datetime.date.today()).strftime("%Y%m%d")
    mxf = Path(mxf)
    for k in ["", *map(str, range(1, 100))]:
        nome = f"{base}{k}0"
        if not (mxf / nome).exists() and not (mxf / (nome[:-1] + "1")).exists():
            return mxf / nome
    raise ConversaoFalhou(f"não achei pasta livre em {mxf} para hoje")


def sondar(arquivo: Path) -> dict[str, Any]:
    """{taxa, largura, altura} do primeiro vídeo do arquivo, pelo ffprobe."""
    from .binarios import achar
    p = subprocess.run([achar("ffprobe") or "ffprobe", "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=r_frame_rate,width,height", "-of", "json", str(arquivo)],
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=30)
    s = (json.loads(p.stdout or "{}").get("streams") or [{}])[0]
    return {"taxa": s.get("r_frame_rate"), "largura": s.get("width"), "altura": s.get("height")}


def conferir_videos(videos: list[Path]) -> tuple[str, dict[str, Any]]:
    """("", formato) quando os vídeos podem ir juntos; senão (motivo, {})."""
    if not videos:
        return "não há vídeo (.mov, .mp4, .mxf) nessa pasta", {}
    formatos = {}
    for v in videos:
        s = sondar(v)
        formatos[(s["taxa"], s["largura"], s["altura"])] = v.name
    if len(formatos) > 1:
        lista = "; ".join(f"{n}: {t} {w}x{h}" for (t, w, h), n in formatos.items())
        return f"os vídeos misturam taxa ou tamanho ({lista}) — converta um formato por vez", {}
    (taxa, w, h), = formatos
    if taxa not in TAXAS:
        return f"taxa {taxa} ainda não medida aqui", {}
    if h not in CODECS:
        return f"ainda não sei o codec para {w}x{h} (medido: {', '.join(f'{a}p' for a in CODECS)})", {}
    return "", {"taxa": TAXAS[taxa], "largura": w, "altura": h, "codec": CODECS[h]}


# O que roda no processo FILHO. ⚠️ Sem f-string: as chaves são do Python de lá.
_CODIGO = r"""
import json, os, sys, time
def diz(**k): print(json.dumps(k, ensure_ascii=False), flush=True)
api, lib, pedido = sys.argv[1], sys.argv[2], json.loads(sys.argv[3])
os.environ.setdefault("RESOLVE_SCRIPT_API", api); os.environ.setdefault("RESOLVE_SCRIPT_LIB", lib)
sys.path.append(os.path.join(api, "Modules"))
try:
    import DaVinciResolveScript as dvr
except ImportError:
    diz(erro="a API de script do DaVinci Resolve não está instalada nesta máquina"); sys.exit(0)
fim = time.monotonic() + 45; r = None
while r is None and time.monotonic() < fim:
    r = dvr.scriptapp("Resolve")
    if r is None: time.sleep(2)
if r is None:
    diz(erro="o DaVinci Resolve não respondeu ao script (só o Studio aceita; feche e abra o Resolve)"); sys.exit(0)
nome, videos, destino, codec = pedido["projeto"], pedido["videos"], pedido["destino"], pedido["codec"]
pm = r.GetProjectManager(); pr = pm.GetCurrentProject()
if not pr or pr.GetName() != nome:
    pr = pm.LoadProject(nome) or pm.CreateProject(nome)
if not pr or pr.GetName() != nome:
    diz(erro="o Resolve não abriu nem criou o projeto " + repr(nome)); sys.exit(0)
diz(etapa="projeto", projeto=nome)
if pr.GetTimelineCount() == 0:
    pr.SetSetting("timelineFrameRate", pedido["taxa"])
    pr.SetSetting("timelineResolutionWidth", str(pedido["largura"]))
    pr.SetSetting("timelineResolutionHeight", str(pedido["altura"]))
taxa_do_projeto = pr.GetSetting("timelineFrameRate")
if str(taxa_do_projeto).rstrip("0").rstrip(".") != pedido["taxa"].rstrip("0").rstrip("."):
    diz(erro="o projeto '%s' está a %s e os vídeos a %s — use outro projeto" % (nome, taxa_do_projeto, pedido["taxa"])); sys.exit(0)
mp = pr.GetMediaPool()
def clipes_de(pasta):
    out = list(pasta.GetClipList() or [])
    for sub in pasta.GetSubFolderList() or []: out += clipes_de(sub)
    return out
norm = lambda c: os.path.normcase(os.path.normpath(c))
ja = {norm(c.GetClipProperty("File Path") or ""): c for c in clipes_de(mp.GetRootFolder())}
faltam = [v for v in videos if norm(v) not in ja]
if faltam:
    for c in r.GetMediaStorage().AddItemListToMediaPool(faltam) or []:
        ja[norm(c.GetClipProperty("File Path") or "")] = c
clipes = [ja.get(norm(v)) for v in videos]
if not all(clipes):
    diz(erro="o Resolve não importou: " + ", ".join(os.path.basename(v) for v, c in zip(videos, clipes) if not c)); sys.exit(0)
diz(etapa="clipes", clipes=[c.GetName() for c in clipes], reaproveitados=len(videos) - len(faltam))
# ⭐ GRUPOS: uma timeline e um render por grupo. O OP-Atom manda um grupo só, no tamanho do projeto; o
#   proxy manda um por PROPORÇÃO, cada um numa timeline do tamanho do proxy (medido 2026-11-07, Studio 21.1:
#   DCI 4096×2160 numa timeline 1920×1080 sai com tarja, mesmo pedindo 2048×1080 no render).
por_caminho = dict(zip(videos, clipes))
grupos = pedido.get("grupos") or [{"videos": videos, "timeline": pedido["timeline"]}]
saida = pedido.get("formato_saida", "mxf")
pagina = r.GetCurrentPage()
feitos = []; t_total = time.time()
for g in grupos:
    tl_nome = g["timeline"]
    tl = mp.CreateTimelineFromClips(tl_nome, [por_caminho[v] for v in g["videos"]])
    if not tl:
        r.OpenPage(pagina or "edit"); diz(erro="o Resolve não criou a timeline " + repr(tl_nome)); sys.exit(0)
    if g.get("largura"):
        tl.SetSetting("useCustomSettings", "1")
        tl.SetSetting("timelineResolutionWidth", str(g["largura"])); tl.SetSetting("timelineResolutionHeight", str(g["altura"]))
        lido = (str(tl.GetSetting("timelineResolutionWidth")), str(tl.GetSetting("timelineResolutionHeight")))
        if lido != (str(g["largura"]), str(g["altura"])):
            r.OpenPage(pagina or "edit"); diz(erro="a timeline %s ficou %sx%s, pedi %sx%s — parei sem renderizar" % (tl_nome, lido[0], lido[1], g["largura"], g["altura"])); sys.exit(0)
    pr.SetCurrentTimeline(tl)
    r.OpenPage("deliver"); time.sleep(1)
    if pedido["preset"] in (pr.GetRenderPresetList() or []):
        pr.DeleteRenderPreset(pedido["preset"])
    importou = r.ImportRenderPreset(pedido["preset_arq"])
    carregou = pr.LoadRenderPreset(pedido["preset"])
    fc = pr.GetCurrentRenderFormatAndCodec() or {}; modo = pr.GetCurrentRenderMode()
    diz(etapa="preset", importou=bool(importou), carregou=bool(carregou), formato=fc, modo=modo)
    if fc.get("format") != "mxf" or modo != 0:
        r.OpenPage(pagina or "edit")
        diz(erro="o preset %s NÃO foi aplicado (formato %s, modo %s; esperado mxf e clipes individuais). Parei sem renderizar: forçar o codec na mão gera arquivos com o nome errado e som de 16 bits." % (pedido["preset"], fc, modo)); sys.exit(0)
    if not pr.SetCurrentRenderFormatAndCodec(saida, codec):
        r.OpenPage(pagina or "edit"); diz(erro="o Resolve recusou o codec %s/%s" % (saida, codec)); sys.exit(0)
    os.makedirs(destino, exist_ok=True)
    ajustes = {"SelectAllFrames": True, "TargetDir": destino}
    if g.get("largura"):
        ajustes.update({"FormatWidth": int(g["largura"]), "FormatHeight": int(g["altura"])})
    pr.SetRenderSettings(ajustes)
    job = pr.AddRenderJob()
    trab = next((x for x in (pr.GetRenderJobList() or []) if x.get("JobId") == job), {})
    if not job or os.path.normcase(os.path.normpath(trab.get("TargetDir", ""))) != norm(destino):
        r.OpenPage(pagina or "edit"); diz(erro="o trabalho de render não ficou com o destino pedido: " + json.dumps(trab, ensure_ascii=False)); sys.exit(0)
    if g.get("largura") and (trab.get("FormatWidth"), trab.get("FormatHeight")) != (int(g["largura"]), int(g["altura"])):
        pr.DeleteRenderJob(job); r.OpenPage(pagina or "edit")
        diz(erro="o trabalho de render ficou %sx%s, pedi %sx%s — parei sem renderizar" % (trab.get("FormatWidth"), trab.get("FormatHeight"), g["largura"], g["altura"])); sys.exit(0)
    diz(etapa="trabalho", trabalho={k: trab.get(k) for k in ("OutputFilename", "TargetDir", "RenderMode", "IsExportAudio", "FormatWidth", "FormatHeight", "FrameRate", "VideoCodec")})
    t0 = time.time(); pr.StartRendering(job)
    while pr.IsRenderingInProgress() and time.time() - t0 < pedido["prazo"]:
        st = pr.GetRenderJobStatus(job) or {}
        diz(etapa="render", pct=st.get("CompletionPercentage"), segundos=round(time.time() - t0))
        time.sleep(5)
    st = pr.GetRenderJobStatus(job) or {}
    if pr.IsRenderingInProgress():
        pr.StopRendering()
        st["JobStatus"] = "parado: passou do prazo"
    pr.DeleteRenderJob(job)
    feitos.append({"timeline": tl_nome, "status": st.get("JobStatus"), "segundos": round(time.time() - t0, 1)})
    if st.get("JobStatus") != "Complete":
        break
r.OpenPage(pagina or "edit")
ruim = next((f["status"] for f in feitos if f["status"] != "Complete"), "Complete")
diz(fim={"status": ruim, "segundos": round(time.time() - t_total, 1), "timeline": feitos[0]["timeline"] if feitos else "", "grupos": feitos})
"""


def _rodar(pedido: dict, relatar: Callable[[str, float | None, str], None]) -> dict[str, Any]:
    if not _resolve.servidor_no_ar():
        raise ConversaoFalhou("o DaVinci Resolve não está aberto — abra-o antes (abrir_programa)")
    opcoes: dict[str, Any] = {}
    if sys.platform == "win32":
        opcoes["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    proc = subprocess.Popen([sys.executable, "-c", _CODIGO, _resolve._API, _resolve._LIB, json.dumps(pedido)],
                            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace", **opcoes)
    erros: list[str] = []
    threading.Thread(target=lambda: erros.extend(proc.stderr), daemon=True).start()
    linhas: list[dict] = []
    ultima = [time.monotonic()]

    def ler() -> None:
        for l in proc.stdout:
            ultima[0] = time.monotonic()
            if l.strip().startswith("{"):
                try:
                    linhas.append(json.loads(l))
                except ValueError:
                    continue
                d = linhas[-1]
                if d.get("etapa") == "render":
                    relatar(f"renderizando {pedido.get('rotulo', 'OP-Atom')} no DaVinci Resolve", (d.get("pct") or 0) / 100,
                            f"{d.get('segundos')} s")
                elif d.get("etapa"):
                    relatar(f"Resolve: {d['etapa']}", None, "")

    leitor = threading.Thread(target=ler, daemon=True)
    leitor.start()
    while proc.poll() is None:
        if time.monotonic() - ultima[0] > SILENCIO_MAXIMO_S:
            proc.kill()
            raise ConversaoFalhou(f"o DaVinci Resolve ficou {SILENCIO_MAXIMO_S // 60} min sem responder ao script")
        time.sleep(0.5)
    leitor.join(2)
    falhas = [d["erro"] for d in linhas if d.get("erro")]
    if falhas:
        raise ConversaoFalhou(falhas[-1])
    fins = [d["fim"] for d in linhas if d.get("fim")]
    if not fins:
        raise ConversaoFalhou("a conversa com o Resolve terminou sem resposta: "
                              + ("".join(erros).strip().splitlines() or ["sem mensagem"])[-1])
    etapas = {d["etapa"]: d for d in linhas if d.get("etapa") and d["etapa"] != "render"}
    return {**fins[-1], "etapas": etapas}


def ler_sonda(nome: str, d: dict) -> dict[str, Any]:
    """Um item da conferência a partir do JSON do ffprobe.

    ⛔ O stream que interessa NÃO é o primeiro: no MXF de som do Resolve o índice 0 é `data`
    (medido 2026-11-01, Studio 19.1.4: data · pcm_s24le · data). Lendo o primeiro, os 8
    arquivos de som da M06 contavam como zero, e a conferência de 24 bits ficava muda."""
    sts = d.get("streams") or []
    st = next((s for s in sts if s.get("codec_type") in ("video", "audio")), sts[0] if sts else {})
    return {"arquivo": nome, "tipo": st.get("codec_type"), "codec": st.get("codec_name"),
            "bits": st.get("bits_per_raw_sample") or st.get("bits_per_sample"),
            "tc": (st.get("tags") or {}).get("timecode"),
            "master": (d.get("format") or {}).get("tags", {}).get("material_package_name")}


def conferir_saida(destino: Path, clipes: list[str]) -> dict[str, Any]:
    """Lê o que caiu na pasta: um MXF de vídeo por clipe (nome = o do clipe) e os de som."""
    from .binarios import achar
    arquivos = sorted(p for p in destino.glob("*.mxf") if not p.name.startswith("._"))
    itens = []
    for p in arquivos:
        s = subprocess.run([achar("ffprobe") or "ffprobe", "-v", "error", "-show_entries",
                            "stream=codec_type,codec_name,bits_per_raw_sample,bits_per_sample:stream_tags=timecode"
                            ":format_tags=material_package_name",
                            "-of", "json", str(p)], capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL, timeout=30)
        itens.append(ler_sonda(p.name, json.loads(s.stdout or "{}")))
    videos = [i for i in itens if i["tipo"] == "video"]
    sons = [i for i in itens if i["tipo"] == "audio"]
    masters = {i["master"] for i in videos}
    faltam = [c for c in clipes if Path(c).stem not in masters and c not in masters]
    problemas = []
    if len(videos) != len(clipes):
        problemas.append(f"{len(videos)} MXF de vídeo para {len(clipes)} clipes")
    if faltam:
        problemas.append("sem MXF de vídeo com o nome do clipe: " + ", ".join(faltam))
    rasos = sorted({i["arquivo"] for i in sons if str(i["bits"]) not in ("24", "0", "None")})
    if rasos:
        problemas.append("som com menos de 24 bits: " + ", ".join(rasos[:4]))
    # ⚠️ Zero som NÃO é problema: câmera sem áudio é legítima, e acusar perda que não existe é
    #    o defeito do "12 clipes" de 31/10. O número vai na manchete.
    return {"videos": len(videos), "sons": len(sons),
            "clipes": [{"master": i["master"], "tc": i["tc"]} for i in videos],
            "arquivos": [i["arquivo"] for i in itens], "problemas": problemas}


def converter(projeto: str, videos: list[Path], mxf: Path, *, destino: Path | None = None,
              relatar: Callable[[str, float | None, str], None] | None = None,
              prazo_s: float = 1800) -> dict[str, Any]:
    """Renderiza os vídeos em OP-Atom numa pasta nova. Devolve a pasta, os arquivos e os problemas."""
    relatar = relatar or (lambda *_: None)
    motivo, formato = conferir_videos(videos)
    if motivo:
        raise ConversaoFalhou(motivo)
    destino = destino or pasta_nova(mxf)
    if destino.exists() and any(destino.iterdir()):
        raise ConversaoFalhou(f"a pasta {destino} já tem arquivos — a conversão só escreve em pasta nova")
    pedido = {"projeto": projeto, "videos": [str(v) for v in videos], "destino": str(destino),
              "codec": formato["codec"], "taxa": formato["taxa"], "largura": formato["largura"],
              "altura": formato["altura"], "preset": PRESET, "preset_arq": str(PRESET_ARQ),
              "timeline": f"OPATOM {datetime.datetime.now():%Y%m%d-%H%M%S}", "prazo": prazo_s}
    r = _rodar(pedido, relatar)
    if r.get("status") != "Complete":
        raise ConversaoFalhou(f"o render terminou como '{r.get('status')}' (pasta {destino})")
    saida = conferir_saida(destino, [v.name for v in videos])
    # ⭐ `formato` no padrão do Media Composer ("1080p/25"): é o que um fluxo passa ao abrir_programa
    #   para CRIAR o projeto "com a resolução e o fps da mídia convertida" ({conv.formato}). Na prova
    #   da F3 (2026-11-03) o modelo pediu exatamente este campo, e ele não existia.
    return {"pasta": str(destino), "codec": formato["codec"], "taxa": formato["taxa"],
            "formato": f"{formato['altura']}p/{formato['taxa']}",
            "segundos": r.get("segundos"), "timeline_no_resolve": r.get("timeline"), **saida}
