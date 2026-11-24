"""Spike — ESCREVER um group clip (multicâmera) do Media Composer pelo pyavb, a partir dos masters e de um
ponto de sincronia por fonte. Carta Aberta, plano `docs/plano/2026-11-11-carta-aberta.md`, C0(f) escrita.

    python spikes/carta_aberta_group_clip.py <bin com os masters> <bin NOVA de saída> NOME MASTER=SYNC [...] [--angulo N]
    python spikes/carta_aberta_group_clip.py --comparar <bin> GRUPO_A <bin> GRUPO_B

A forma é a lida no grupo feito à mão (banco `protocolos/avb/sincronizacao-e-subclipes.md` §5):

- o GRUPO: `CompositionMob usage=4`, uma trilha por trilha do grupo (V1, A1…An), cada uma um `Selector`
  (`is_ganged`, `selected 0`) com um ângulo por fonte: `Track` só com `component` + `lock_number`, um `SourceClip`
  de `start 0` e o grupo inteiro de comprimento, apontando a trilha N do mob de alinhamento;
- o mob de ALINHAMENTO: `CompositionMob usage=5`, oculto, uma trilha por trilha de CADA fonte
  (`Filler(deslocamento) · SourceClip(master inteiro) · Filler(resto)`), imagem e som numerados em sequência entre as
  fontes. ⭐ deslocamento = maior ponto de sincronia − o desta fonte: as fontes vão INTEIRAS (o Premiere, por ponto de
  entrada, corta as cabeças — banco `premiere-cep/subclipe-e-merged-clip.md`).
- o som do grupo: a trilha k do grupo junta a k-ésima trilha de som de cada fonte que a tem (A1 = 1/5/9 no exemplo).

A bin nova leva os masters e as fontes deles OCULTOS (o fecho, como `timeline.escrever_bin`). Nunca grava por cima.
"""

from __future__ import annotations

import contextlib
import os
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import avb  # noqa: E402
from avb.mobid import MobID  # noqa: E402

from cicloassist.avid import timeline as T  # noqa: E402  (também aplica o avb_fiel)


def _novo_id():
    return MobID(bytes_le=bytes(bytearray(T.PREFIXO_DE_COMPOSICAO) + os.urandom(16)))


def _comp(f, nome, edit_rate, usage, total):
    c = f.create.Composition(nome, "CompositionMob")
    c.name = nome
    c.mob_id = _novo_id()
    c.edit_rate = edit_rate
    c.media_kind_id = 0
    c.usage_code = usage
    c.mob_type_id = 1
    c.length = total
    c.mc_mode = 0
    c.num_scalars = 0
    c.param_list = None
    c.tracks = []
    return c


def _trilhas(master):
    """(espécie, índice, comprimento) das trilhas de imagem e som do master."""
    return [(t.component.media_kind, t.index, t.component.length) for t in master.tracks
            if t.component.media_kind in ("picture", "sound")]


def montar_grupo(f, nome, fontes, edit_rate, angulo: int = 0, angulo_do_som: int | None = None):
    """`fontes` = [(master, ponto_de_sincronia_em_quadros)]; `angulo` = o escolhido (0 = a 1ª fonte), em TODAS as
    trilhas (ganged). `angulo_do_som` = a fonte que as trilhas de SOM tocam, se não for a da imagem (o som direto, como
    a multicâmera do Premiere): MEDIDO no MC 25.12 Mac (2026-11-12, `carta_aberta_som_dos_angulos.py`) — com o som
    apontando o som direto e a imagem a CAM 1, o export traz a imagem da CAM 1 e o tom do som direto, ganged ou não.
    Devolve (grupo, alinhamento), já em `f`."""
    maior = max(s for _, s in fontes)
    desl = [maior - s for _, s in fontes]
    total = max(d + max(c for _, _, c in _trilhas(m)) for (m, _), d in zip(fontes, desl))

    alin = _comp(f, f"{nome}.grp", edit_rate, 5, total)
    alin.attributes = T._atributos(f, _SAVED_AAF_AUDIO_RATE_NUM=24000, _SAVED_AAF_AUDIO_RATE_DEN=1001)
    contagem = {"picture": 0, "sound": 0}
    angulos = []  # por fonte: {"picture": [índice no alinhamento], "sound": [...]}
    for (master, _), d in zip(fontes, desl):
        meus = {"picture": [], "sound": []}
        for kind, indice, comp in _trilhas(master):
            contagem[kind] += 1
            seq = f.create.Sequence(edit_rate, kind)
            sc = f.create.SourceClip(edit_rate, kind)
            sc.mob_id = MobID(str(master.mob_id))
            sc.track_id = indice
            sc.start_time = 0
            sc.length = comp
            seq.components = [T._filler(f, edit_rate, d, kind), sc,
                              T._filler(f, edit_rate, total - d - comp, kind)]
            tr = f.create.Track()
            tr.index = contagem[kind]
            tr.component = seq
            tr.lock_number = 0
            tr.session_attr = (T._atributos(f, _MONSTATE=2, _ENBLSTATE=1) if kind == "sound"
                               else T._atributos(f, _ENBLSTATE=1))
            alin.tracks.append(tr)
            meus[kind].append(contagem[kind])
        angulos.append(meus)

    grupo = _comp(f, nome, edit_rate, 4, total)
    grupo.attributes = T._atributos(f, _SAVED_AAF_AUDIO_RATE_NUM=24000, _SAVED_AAF_AUDIO_RATE_DEN=1001)

    def selector(kind, alvos, escolhido=None):
        sel = f.create.Selector(edit_rate, kind)
        sel.length = total
        sel.mc_mode = 0
        sel.num_scalars = 0
        sel.is_ganged = True
        sel.selected = escolhido if escolhido is not None else min(angulo, len(alvos) - 1)
        sel.tracks = []
        for alvo in alvos:
            sc = f.create.SourceClip(edit_rate, kind)
            sc.mob_id = MobID(str(alin.mob_id))
            sc.track_id = alvo
            sc.start_time = 0
            sc.length = total
            a = f.create.Track()
            a.component = sc
            a.lock_number = 0
            sel.tracks.append(a)
        return sel

    imagem = [a["picture"][0] for a in angulos if a["picture"]]
    if imagem:
        tr = f.create.Track()
        tr.index = 1
        tr.component = selector("picture", imagem)
        tr.lock_number = 0
        tr.filler_proxy = T._referencia_de_track(f, edit_rate, "picture")
        tr.session_attr = T._atributos(f, _MONSTATE=1, _ENBLSTATE=1)
        grupo.tracks.append(tr)
    n_som = max(len(a["sound"]) for a in angulos)
    for k in range(n_som):
        alvos = [a["sound"][k] for a in angulos if len(a["sound"]) > k]
        do_som = angulos[angulo_do_som]["sound"] if angulo_do_som is not None else []
        escolhido = alvos.index(do_som[k]) if len(do_som) > k else None
        tr = f.create.Track()
        tr.index = k + 1
        tr.component = selector("sound", alvos, escolhido)
        tr.lock_number = 0
        tr.session_attr = T._atributos(f, _MONSTATE=2, _ENBLSTATE=1)
        tr.attributes = T._atributos(f, AudioMixerCompSolo=0, AudioMixerCompMute=0)
        grupo.tracks.append(tr)

    f.content.add_mob(alin).user_placed = False
    f.content.add_mob(grupo).user_placed = True
    return grupo, alin


def escrever(origem: str, saida: str, nome: str, pares: list[tuple[str, int]], angulo: int = 0) -> None:
    if Path(saida).exists():
        raise SystemExit(f"⛔ {saida} já existe: nunca por cima")
    with contextlib.ExitStack() as pilha:
        f = pilha.enter_context(avb.open())
        o = pilha.enter_context(avb.open(origem))
        masters = {m.name: m for m in o.content.mobs if getattr(m, "mob_type", "") == "MasterMob"}
        fontes = [(masters[n], s) for n, s in pares]
        rate = fontes[0][0].tracks[0].component.edit_rate
        grupo, alin = montar_grupo(f, nome, fontes, rate, angulo)
        levados = T._levar_fecho(f, o, {m.mob_id for m, _ in fontes}, set())
        f.write(saida)
    print(f"✅ {saida}: grupo {nome!r} ({grupo.length} quadros, {len(grupo.tracks)} trilhas), "
          f"alinhamento {alin.name!r} ({len(alin.tracks)} trilhas), {levados} mob(s) de fecho ocultos")


def assinatura(caminho: str, nome: str) -> list:
    """A forma do grupo, sem ids nem nomes: o que tem de ser igual entre o feito à mão e o escrito."""
    out = []
    with avb.open(caminho) as f:
        mobs = {str(m.mob_id): m for m in f.content.mobs}
        g = next(m for m in f.content.mobs if m.name == nome and getattr(m, "usage_code", None) == 4)
        out.append(("grupo", g.length, g.edit_rate))
        alvo = None
        for t in g.tracks:
            s = t.component
            angs = [(a.component.track_id, a.component.start_time, a.component.length) for a in s.tracks]
            alvo = s.tracks[0].component.mob_id
            out.append((s.media_kind, t.index, s.is_ganged, s.selected, angs))
        al = mobs[str(alvo)]
        out.append(("alinhamento", al.usage_code, al.length))
        for t in al.tracks:
            comps = []
            for c in t.component.components:
                if type(c).__name__ == "SourceClip":
                    comps.append(("SC", mobs[str(c.mob_id)].name, c.track_id, c.start_time, c.length))
                else:
                    comps.append((type(c).__name__, c.length))
            out.append((t.component.media_kind, t.index, comps))
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    if a and a[0] == "--comparar":
        x, y = assinatura(a[1], a[2]), assinatura(a[3], a[4])
        for i, (p, q) in enumerate(zip(x, y)):
            print("  " if p == q else "≠ ", p if p == q else f"{p}\n   {q}")
        print("IGUAIS" if x == y else "DIFERENTES", len(x), len(y))
        sys.exit(0 if x == y else 1)
    angulo = 0
    if "--angulo" in a:
        i = a.index("--angulo"); angulo = int(a[i + 1]) - 1; del a[i:i + 2]
    escrever(a[0], a[1], a[2], [(s.split("=")[0], int(s.split("=")[1])) for s in a[3:]], angulo)
