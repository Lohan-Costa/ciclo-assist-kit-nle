"""Spike — Carta Aberta: de que ARQUIVO vem cada trilha de um merged clip, lido do `.prproj` (a API não diz).

    python spikes/carta_aberta_merged_do_prproj.py <projeto.prproj>

A API do Premiere devolve, para cada trilha de um merged, o PRÓPRIO merged (banco `premiere-cep/subclipe-e-merged-clip.md`,
"O caminho de VOLTA"). No `.prproj` o merged é uma `Sequence` com `IsMergedClip` (banco `prproj/escrita.md` §2): cada
trilha → `TrackItem › SubClip › Clip › Source › Media.FilePath`, com o `InPoint` (entrada no arquivo) e os canais
(`SecondaryContent.ChannelIndex`). Reusa o leitor do Conformar (`modulos/conformar/motor/prproj`).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ / "modulos" / "conformar"))

from motor.prproj.leitura import Leitor, _int  # noqa: E402
from motor.prproj.projeto import Projeto  # noqa: E402

TICKS_POR_S = 254016000000


def fontes_dos_merged(caminho: str) -> list[dict]:
    p = Projeto(caminho)
    le = Leitor(p)
    out = []
    for s in p.de_tipo("Sequence"):
        if not le.eh_merged(s):
            continue
        _, tpq = le.quadro(s)
        q = (lambda t: round(_int(t) / tpq)) if tpq else (lambda t: _int(t))
        trilhas = []
        for tipo in ("Video", "Audio"):
            for k, (trilha, itens) in enumerate(le.trilhas(s, tipo), 1):
                for it in itens:
                    sc = p.ref(it, "SubClip")
                    clip = p.ref(sc, "Clip") if sc is not None else None
                    fonte = p.ref(clip, "Source") if clip is not None else None
                    media = p.ref(fonte, "Media") if fonte is not None else None
                    fonte_oid = fonte.oid if fonte is not None else None
                    trilhas.append({
                        "_fonte": fonte_oid,
                        "_grupo": _int(p.campo(sc, "OrigChGrp")) if sc is not None else 0,
                        "trilha": f"{tipo[0]}{k}",
                        "arquivo": p.campo(media, "FilePath") if media is not None else f"({fonte.tag if fonte else '?'})",
                        "inicio_q": q(p.campo(it, "Start")),
                        "entrada_q": q(p.campo(clip, "InPoint")) if clip is not None else None,
                        "canais": le._canais(clip) if clip is not None and tipo == "Audio" else [],
                    })
        # ⚠️ O CANAL tem duas formas (banco `prproj/escrita.md` §7.1/§11g): a do Premiere — UMA fonte com os N canais,
        #    o `SecondaryContent.ChannelIndex` escolhe — e a do nosso escritor — UMA fonte POR canal, todas com
        #    `ChannelIndex 0`, e quem escolhe é a fonte. Na segunda, o canal sai do `OrigChGrp` (bate nas duas formas
        #    medidas, mas o banco diz que ele não é o que SELECIONA: `inferido`).
        por_arquivo: dict[str, set] = {}
        for t in trilhas:
            if t["canais"]:
                por_arquivo.setdefault(t["arquivo"], set()).add(t["_fonte"])
        for t in trilhas:
            if t["canais"] and len(por_arquivo[t["arquivo"]]) > 1 and t["canais"] == [0]:
                t["canais"], t["canal_por"] = [t["_grupo"]], "OrigChGrp (uma fonte por canal)"
            elif t["canais"]:
                t["canal_por"] = "ChannelIndex"
            del t["_fonte"], t["_grupo"]
        out.append({"merged": p.nome_da_sequencia(s), "uid": s.uid, "trilhas": trilhas})
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    for m in fontes_dos_merged(sys.argv[1]):
        print(f"== {m['merged']}  ({m['uid']})")
        for t in m["trilhas"]:
            print(f"   {t['trilha']:4} {Path(t['arquivo']).name:38} início {t['inicio_q']:>5} q · entrada no arquivo "
                  f"{t['entrada_q']} q · canais {t['canais']} {('(' + t['canal_por'] + ')') if t.get('canal_por') else ''}")
