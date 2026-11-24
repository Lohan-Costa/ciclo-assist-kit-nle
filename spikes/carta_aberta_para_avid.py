"""Spike — Carta Aberta, Premiere → Avid: multicâmera, merged e subclipe do Premiere viram group clip, subclipe
sincronizado e subclipe no MC, sobre os masters que o projeto do Avid já tem.

    python spikes/carta_aberta_para_avid.py <lido do premiere .json> <saída .avb> --masters <bin.avb> [<bin.avb> ...]
        [--som <arquivo do som direto>]

O `.json` é o que a ponte lê do Premiere (o leitor de teste é `j_ler_volta.jsx` do scratchpad da sessão de 2026-11-12):
por sequência multicâmera/merged, cada trilha com arquivo, início, entrada e fim em quadros; por subclipe, arquivo e
entrada/saída. A escrita no Avid é a dos spikes já provados (`carta_aberta_group_clip.montar_grupo`,
`carta_aberta_avid_g01.montar_subclipe`).

| no Premiere | no Avid |
|---|---|
| multicâmera: cada fonte em `início − entrada` (onde o quadro 0 dela cai) | group clip: ponto de sincronia = maior deslocamento − o da fonte (o `Filler` da frente = o deslocamento) |
| merged: imagem desde a entrada dela, som direto desde a entrada dele | subclipe sincronizado (`.sync`): início POR trilha |
| subclipe: entrada/saída no tempo da mídia | subclipe |

⚠️ A API não diz de que ARQUIVO vem cada trilha de um merged (todas apontam o próprio merged): o som direto é dado em
`--som`, e as trilhas dele são as que vêm DEPOIS dos canais da câmera (a forma do merged nativo, banco
`premiere-cep/subclipe-e-merged-clip.md`). ⬜ ler do `.prproj`.
⚠️ O master do Avid é achado pelo NOME (arquivo `X.mov` → master `X`; o WAV, com a extensão) — no produto, o registro de
formas da Carta Aberta.
"""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import avb  # noqa: E402

from cicloassist.avid import timeline as T  # noqa: E402
from carta_aberta_group_clip import montar_grupo  # noqa: E402
from carta_aberta_avid_g01 import montar_subclipe, _trilhas  # noqa: E402


def _q(tc: str, base: int = 24) -> int:
    h, m, s_, q = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s_) * base + q


def _master(masters: dict, arquivo: str):
    for n in (arquivo, Path(arquivo).stem):
        if n in masters:
            return masters[n]
    raise SystemExit(f"⛔ nenhum master do Avid para {arquivo!r}")


def traduzir(lido: dict, saida: str, bins: list[str], som: str | None) -> list[str]:
    if Path(saida).exists():
        raise SystemExit(f"⛔ {saida} já existe: nunca por cima")
    feitos = []
    with contextlib.ExitStack() as p:
        f = p.enter_context(avb.open())
        origens = [p.enter_context(avb.open(b)) for b in bins]
        masters = {m.name: m for o in origens for m in o.content.mobs if getattr(m, "mob_type", "") == "MasterMob"}
        rate = next(iter(masters.values())).tracks[0].component.edit_rate
        usados = []

        for mc in lido.get("multicam", []):
            desl = {}
            for tr in mc["trilhas"].values():
                desl.setdefault(tr["arquivo"], round(tr["inicio"] - tr["entrada"]))
            maior = max(desl.values())
            fontes = [(_master(masters, a), maior - d) for a, d in desl.items()]
            # ⭐ o som do grupo é o som DIRETO (a fonte sem imagem), como a multicâmera do Premiere toca
            sem_imagem = [i for i, (m, _) in enumerate(fontes) if not _trilhas(m, "picture")]
            g, _ = montar_grupo(f, mc["nome"].replace("Várias câmeras", " GRUPO"), fontes, rate,
                                angulo_do_som=sem_imagem[0] if sem_imagem else None)
            usados += [m for m, _ in fontes]
            feitos.append(f"{g.name}: " + ", ".join(f"{a} em {d}" for a, d in desl.items()))

        for mg in lido.get("merged", []):
            cam_arq = mg["nome"].split(" – ")[0].split(" - ")[0]
            cam, snd = _master(masters, cam_arq), _master(masters, som)
            n_cam = len(_trilhas(cam, "sound"))
            trs = mg["trilhas"]
            v = trs["V1"]
            a_som = trs[f"A{n_cam + 1}"]
            comp = round(v["fim"] - v["inicio"])
            ini_v, ini_s = round(v["entrada"]), round(a_som["entrada"])
            nome = mg["nome"].replace(" – Mesclado", ".sync.premiere")
            s = montar_subclipe(f, nome, [(cam, "picture", 1, ini_v)] +
                                [(snd, "sound", i, ini_s) for i in _trilhas(snd, "sound")], comp, rate)
            usados += [cam, snd]
            feitos.append(f"{s.name}: imagem desde {ini_v}, som direto desde {ini_s}, {comp} quadros")

        for sc in lido.get("subclipes", []):
            m = _master(masters, sc["arquivo"])
            # ⛔ `getInPoint/getOutPoint` de um subclipe do Premiere devolvem o MASTER inteiro (banco): a janela é
            #   `SubclipStart` − `MediaStart` (TC), com `SubclipDuration`.
            if sc.get("subclip_start") and sc.get("media_start"):
                ini = _q(sc["subclip_start"]) - _q(sc["media_start"])
                fim = ini + _q(sc["subclip_dur"])
            else:
                ini, fim = round(sc["inicio"]), round(sc["fim"])
            s = montar_subclipe(f, sc["nome"], [(m, "picture", 1, ini)] +
                                [(m, "sound", i, ini) for i in _trilhas(m, "sound")], fim - ini, rate)
            usados.append(m)
            feitos.append(f"{s.name}: {ini}–{fim}")

        ja: set[str] = set()
        for o in origens:
            ids = {x.mob_id for x in usados if str(x.mob_id) in {str(y.mob_id) for y in o.content.mobs}}
            T._levar_fecho(f, o, ids, ja)
            ja |= {str(y.mob_id) for y in o.content.mobs}
        f.write(saida)
    return feitos


if __name__ == "__main__":
    a = sys.argv[1:]
    som = None
    if "--som" in a:
        i = a.index("--som"); som = a[i + 1]; del a[i:i + 2]
    i = a.index("--masters")
    for linha in traduzir(json.loads(Path(a[0]).read_text(encoding="utf-8")), a[1], a[i + 1:], som):
        print("✅", linha)
