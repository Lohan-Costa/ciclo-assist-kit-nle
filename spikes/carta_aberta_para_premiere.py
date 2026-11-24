"""Spike — Carta Aberta, Avid → Premiere: os objetos VIVOS de uma bin do MC viram objetos vivos no `.prproj`.

    python spikes/carta_aberta_para_premiere.py <bin .avb> <pasta da mídia> <saída .prproj> [--json pedidos.json]

| no Avid (lido da bin) | no Premiere |
|---|---|
| group clip (`usage 4`) + o mob de alinhamento (`usage 5`) | Multi-Camera Source Sequence com as fontes INTEIRAS, cada uma no deslocamento do Avid (o `Filler` da frente) — nunca o gesto de ponto de entrada, que corta as cabeças (banco `premiere-cep/subclipe-e-merged-clip.md`) |
| subclipe SINCRONIZADO (`usage 2`, imagem de um master, som de outro) | merged clip (o escritor do módulo Sincronizar, validado em produção): `sync_offset` = início do som − início da imagem |
| subclipe simples (`usage 2`, um master) | um pedido de `createSubClip` para a ponte (o Premiere tem API para isso; o escritor não faz subclipe) |

A mídia de cada master é achada na pasta pelo NOME (o master `X` → o arquivo `X.*` ou `X`): no produto é o registro de
formas da Carta Aberta (identidade por conteúdo), aqui o laboratório garante os nomes. A escrita é toda do
`modulos/sincronizar/motor/prproj/builder.py` — nada de XML novo aqui.
⚠️ Limites deste spike: um som direto por grupo; o merged cobre a câmera INTEIRA (o recorte do subclipe sincronizado
não é levado — a imagem do `.sync.01` do MC começa no 0, que é o caso real); efeitos e ângulo escolhido não viajam.
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "modulos" / "sincronizar" / "motor"))

import avb  # noqa: E402

from cicloassist.avid import timeline as _T  # noqa: E402,F401  (aplica o avb_fiel)
from prproj import builder as B  # noqa: E402
from prproj.alvo import adaptar  # noqa: E402
from prproj.compress import write_prproj  # noqa: E402
from sync.model import CameraAngle, CameraGroup, Daily, Project, SoundClip, Take  # noqa: E402

FPS = 24000 / 1001


# ── a leitura do Avid ────────────────────────────────────────────────────────

@dataclass
class Fonte:
    master: str
    deslocamento: int
    imagem: bool = False
    som: bool = False


@dataclass
class Grupo:
    nome: str
    comprimento: int
    fontes: list[Fonte] = field(default_factory=list)


@dataclass
class Subclipe:
    nome: str
    comprimento: int
    imagem: tuple[str, int] | None = None      # (master, início)
    som: tuple[str, int] | None = None


def ler_bin(caminho: str) -> tuple[list[Grupo], list[Subclipe]]:
    grupos, subs = [], []
    with avb.open(caminho) as f:
        mobs = {str(m.mob_id): m for m in f.content.mobs}
        visiveis = [i.mob for i in f.content.items if i.user_placed]
        for m in visiveis:
            uso = getattr(m, "usage_code", None)
            if uso == 4:
                sel = next(t.component for t in m.tracks if type(t.component).__name__ == "Selector")
                alin = mobs[str(sel.tracks[0].component.mob_id)]
                g = Grupo(m.name, m.length)
                por = {}
                for t in alin.tracks:
                    antes = 0
                    for c in t.component.components:
                        if type(c).__name__ == "SourceClip":
                            nome = mobs[str(c.mob_id)].name
                            fo = por.setdefault(nome, Fonte(nome, antes))
                            fo.imagem |= t.component.media_kind == "picture"
                            fo.som |= t.component.media_kind == "sound"
                            break
                        antes += c.length
                g.fontes = list(por.values())
                grupos.append(g)
            elif uso == 2:
                s = Subclipe(m.name, m.length)
                for t in m.tracks:
                    c = t.component
                    if type(c).__name__ != "SourceClip":
                        continue
                    par = (mobs[str(c.mob_id)].name, c.start_time)
                    if c.media_kind == "picture" and s.imagem is None:
                        s.imagem = par
                    elif c.media_kind == "sound" and s.som is None:
                        s.som = par
                subs.append(s)
    return grupos, subs


# ── a mídia de cada master ───────────────────────────────────────────────────

def _sonda(arq: Path) -> dict:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(arq)],
                         capture_output=True, text=True, check=True).stdout
    return json.loads(out)


def _tc_quadros(tc: str, base: int = 24) -> int:
    h, m, s, q = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * base + q


def achar(master: str, pasta: Path) -> Path:
    alvo = master.lower()
    for p in sorted(pasta.rglob("*")):
        if p.is_file() and not p.name.startswith(".") and (p.name.lower() == alvo or p.stem.lower() == alvo):
            return p
    raise SystemExit(f"⛔ não achei a mídia do master {master!r} em {pasta}")


def camera(arq: Path, inicio: int, sync: int = 0) -> CameraAngle:
    d = _sonda(arq)
    v = next(s for s in d["streams"] if s["codec_type"] == "video")
    a = [s for s in d["streams"] if s["codec_type"] == "audio"]
    tc = v.get("tags", {}).get("timecode") or d["format"].get("tags", {}).get("timecode")
    q = _tc_quadros(tc) if tc else None
    # ⭐ O TC do merged é o do VÍDEO (autor, 2026-11-12): o builder põe `alternate_start_ticks` no `MZ.ZeroPoint` do merged.
    return CameraAngle(path=arq, fps=FPS, duration_frames=int(v["nb_frames"]), timeline_start_frames=inicio,
                       sync_offset_frames=sync, tc_start_frames=q,
                       alternate_start_ticks=q * round(B.TICKS_PER_SEC / FPS) if q is not None else None,
                       audio_channels=sum(int(s.get("channels", 1)) for s in a), sync_source="timecode")


def som(arq: Path, inicio: int) -> SoundClip:
    d = _sonda(arq)
    a = next(s for s in d["streams"] if s["codec_type"] == "audio")
    tr = int(d["format"].get("tags", {}).get("time_reference", 0) or 0)
    return SoundClip(path=arq, sample_rate=int(a["sample_rate"]), duration_ms=float(d["format"]["duration"]) * 1000,
                     channels=int(a["channels"]), timeline_start_frames=inicio,
                     tc_start_sec=tr / int(a["sample_rate"]) if tr else None)


# ── a escrita ────────────────────────────────────────────────────────────────

def traduzir(bin_avb: str, pasta: Path, saida: Path, bin_premiere: str = "CARTA ABERTA") -> dict:
    grupos, subs = ler_bin(bin_avb)
    pedidos = {"subclipes": [], "multicam": [], "merged": []}

    class _Carta(B._B):
        def _bins_da_raiz(self):
            filhos = []
            for g in grupos:
                cams = [f for f in g.fontes if f.imagem]
                sons = [f for f in g.fontes if not f.imagem and f.som]
                s = som(achar(sons[0].master, pasta), sons[0].deslocamento) if sons else None
                cs = [camera(achar(f.master, pasta), f.deslocamento,
                             f.deslocamento - (sons[0].deslocamento if sons else 0)) for f in cams]
                d = Daily(camera_groups=[CameraGroup(cameras=[c], name=c.path.stem) for c in cs],
                          takes=[Take(sound=s, cameras=cs)] if s else [], fps=FPS, name=g.nome)
                inicio = min([c.tc_start_frames - c.timeline_start_frames for c in cs if c.tc_start_frames is not None]
                             or [0])
                d.start_tc_frames = inicio
                self.daily = d
                seq = self._build_sequence(d, g.nome, multicam=True)
                filhos.append(self._make_clip_item(seq, g.nome, None))
                pedidos["multicam"].append({"nome": g.nome, "fontes": [(c.path.name, c.timeline_start_frames)
                                                                       for c in cs] + ([(s.path.name, s.timeline_start_frames)] if s else [])})
            for sc in subs:
                if sc.imagem and sc.som and sc.imagem[0] != sc.som[0]:
                    cam = camera(achar(sc.imagem[0], pasta), 0, sc.som[1] - sc.imagem[1])
                    snd = som(achar(sc.som[0], pasta), 0)
                    self.daily = Daily(fps=FPS, name=sc.nome, camera_groups=[CameraGroup(cameras=[cam])],
                                       takes=[Take(sound=snd, cameras=[cam])])
                    filhos += self._build_merged_items(self.daily, nome_de=lambda t, c, n=sc.nome: n)
                    pedidos["merged"].append({"nome": sc.nome, "camera": cam.path.name, "som": snd.path.name,
                                              "sync_offset_frames": cam.sync_offset_frames})
                else:
                    master, ini = sc.imagem or sc.som
                    pedidos["subclipes"].append({"nome": sc.nome, "arquivo": achar(master, pasta).name,
                                                 "in_quadros": ini, "out_quadros": ini + sc.comprimento})
            # ⛔ Toda mídia crua com linha própria na bin, senão "Recovered Clips" (banco, escrita.md §4).
            for path, (mc, *_r) in self.cam_media.items():
                filhos.insert(0, self._make_clip_item(mc, Path(path).name, B._LABEL_VIDEO_NAME))
            for path, (mc, *_r) in self.snd_media.items():
                filhos.insert(0, self._make_clip_item(mc, Path(path).name, B._LABEL_AUDIO_NAME))
            return [self._make_bin(bin_premiere, filhos)]

    opts = B.ExportOptions()
    write_prproj(adaptar(_Carta(Project(name="CARTA ABERTA"), opts).build(), opts.premiere_alvo), saida)
    return pedidos


if __name__ == "__main__":
    a = sys.argv[1:]
    js = None
    if "--json" in a:
        i = a.index("--json"); js = a[i + 1]; del a[i:i + 2]
    if Path(a[2]).exists():
        raise SystemExit(f"⛔ {a[2]} já existe: nunca por cima")
    r = traduzir(a[0], Path(a[1]), Path(a[2]))
    print(json.dumps(r, ensure_ascii=False, indent=1))
    if js:
        Path(js).write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
