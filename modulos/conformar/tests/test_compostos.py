"""NEST do Premiere → Compound Clip do Resolve; MULTICAM continua achatada (autor, 2026-10-04).

Rodar:

    .venv/bin/python tests/test_compostos.py        (Windows: .venv-win/Scripts/python)

O que precisa do Resolve foi medido no 21.1 (Mac): a API não alcança clipe DENTRO de compound, e
a composição do Fusion montada ANTES sobrevive ao `CreateCompoundClip` (correlação 1,0 do quadro
antes × depois). Aqui fica o resto: o sinal que separa nest de multicam (a chave
`Source.Monitor.Multicam.SwitchOnMulticamName` da SEQUÊNCIA — o `IsMulticam` do clipe falta nos
takes "desligados"), o grupo que vai para a casca e o `aplicar_compostos` com uma timeline de
mentira.

O caso R02 (no SSD, `DLPC_AMOSTRAS`) dá o lado negativo: 2 takes multicam, nenhum nest. O projeto
`…PARA RESOLVE.prproj` no HD PRODUCAO_B dá o positivo (`C87_COMP_INTERFONE_2` em 01:22:49:07); sem o
HD, essa parte é PULADA.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from drp.compostos import aplicar_compostos  # noqa: E402
from tools.prproj_para_drt import _compostos  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


# ── uma timeline de mentira, só o que `aplicar_compostos` usa ───────────────

class Item:
    def __init__(self, nome, inicio):
        self.nome, self.inicio = nome, inicio

    def GetName(self):
        return self.nome

    def GetStart(self):
        return self.inicio


class Timeline:
    def __init__(self, trilhas, cria=True):
        self.trilhas, self.pedidos = trilhas, []
        if not cria:
            self.CreateCompoundClip = None

    def GetStartFrame(self):
        return 86400

    def GetItemListInTrack(self, tipo, n):
        return self.trilhas.get(n, []) if tipo == "video" else []

    def CreateCompoundClip(self, itens, info):           # noqa: N802 — o nome da API
        self.pedidos.append(([i.GetName() for i in itens], info))
        return Item(info["name"], itens[0].GetStart())


def _producao_b() -> str | None:
    """O `.prproj` da versão final do filme, pelo manifesto do caso R03 (nada escrito aqui)."""
    import casos as ilhas
    c = ilhas.carregar("REAL/R03 PRODUCAO_B FILME")
    p = c and c["arquivo"].get("prproj_final")
    return str(p) if p else None


def main() -> int:
    print("── o grupo que vai para a casca ──")
    segs = [
        {"track": 1, "timeline_tc_in": "01:22:46:09", "clip_name": "A093C001.mov"},
        {"track": 3, "timeline_tc_in": "01:22:49:07", "clip_name": "A044C016.mov",
         "composto": {"id": "3:1", "nome": "C87_COMP_INTERFONE_2"}},
        {"track": 4, "timeline_tc_in": "01:22:49:07", "clip_name": "87-INSERT-EXTRA-2.mp4",
         "composto": {"id": "3:1", "nome": "C87_COMP_INTERFONE_2"}},
        # o áudio do nest fica de fora (o compound é de vídeo, como o CreateCompoundClip dos itens)
        {"track": 1003, "timeline_tc_in": "01:22:49:07", "clip_name": "x.wav", "is_audio": True,
         "composto": {"id": "3:1", "nome": "C87_COMP_INTERFONE_2"}},
        # plano do nest sem arquivo nenhum: não está na timeline, não entra no grupo
        {"track": 5, "timeline_tc_in": "01:22:49:07", "clip_name": "sumiu.mov",
         "composto": {"id": "3:1", "nome": "C87_COMP_INTERFONE_2"}},
    ]
    mr = [{"segment_index": i, "matched_path": f"/orig/{s['clip_name']}"} for i, s in enumerate(segs)
          if s["clip_name"] != "sumiu.mov"]
    g = _compostos(segs, mr, 24)
    ok("um grupo por uso do nest, só os clipes de VÍDEO que estão na timeline",
       g, [{"nome": "C87_COMP_INTERFONE_2", "clipes": [
           {"trilha": 3, "quadro": 119263, "arquivo": "A044C016.mov"},
           {"trilha": 4, "quadro": 119263, "arquivo": "87-INSERT-EXTRA-2.mp4"}]}])

    print("── aplicar_compostos (timeline de mentira) ──")
    tl = Timeline({3: [Item("A044C016.mov", 86400 + 119263)],
                   4: [Item("87-INSERT-EXTRA-2.mp4", 86400 + 119263)]})
    r = aplicar_compostos(tl, {"compostos": g})
    ok("cria o Compound Clip com o nome do nest e os dois clipes", (r[0]["ok"], tl.pedidos),
       (True, [(["A044C016.mov", "87-INSERT-EXTRA-2.mp4"], {"name": "C87_COMP_INTERFONE_2"})]))
    tl = Timeline({3: [Item("A044C016.mov", 86400 + 119263)]})
    r = aplicar_compostos(tl, {"compostos": g})
    ok("⛔ clipe que não se acha: NÃO junta parte do nest (fica em trilhas, com o erro)",
       (r[0]["ok"], tl.pedidos, "1 de 2" in r[0]["erro"]), (False, [], True))
    r = aplicar_compostos(Timeline({}, cria=False), {"compostos": g})
    ok("Resolve sem CreateCompoundClip: tudo em trilhas, com o aviso",
       (r[0]["ok"], "não cria Compound Clip" in r[0]["erro"]), (False, True))
    ok("sem nest no relatório: nada a fazer", aplicar_compostos(Timeline({}), {}), [])

    from prproj.leitura import Leitor
    from prproj.projeto import Projeto

    print("── R02 (SSD): 2 takes multicam, nenhum nest ──")
    caso = None
    from casos import CANDIDATAS_AMOSTRAS  # noqa: E402 (a pasta de testes, nas duas máquinas)
    for raiz in CANDIDATAS_AMOSTRAS:
        p = os.path.join(raiz or "", "03 CASOS", "REAL", "R02 PRODUCAO_B EXEMPLOS", "premiere",
                         "DU exemplos especificos.prproj")
        if raiz and os.path.exists(p):
            caso = p
            break
    if caso is None:
        print("  caso R02 não encontrado — PULADO")
    else:
        L = Leitor(Projeto(caso))
        ok("as sequências multicam têm a chave", sum(L.eh_multicam(s) for s in L._todas), 2)
        segs = L.ler("DU exemplos especificos", audio=False)["segmentos"]
        ok("⛔ take multicam NÃO vira compound (achatado na câmera escolhida)",
           [s["clip_name"] for s in segs if s.get("composto")], [])

    print("── PRODUCAO_B (HD): o nest do interfone ──")
    proj = _producao_b()
    if proj is None:
        print("  HD PRODUCAO_B não montado — PULADO")
    else:
        L = Leitor(Projeto(proj))
        nomes = {L.p.nome_da_sequencia(s): s for s in L._todas}
        ok("o nest não tem a chave; o take de dentro dele tem",
           (L.eh_multicam(nomes["C87_COMP_INTERFONE_2"]), L.eh_multicam(nomes["87-INST2 - SERIE2"])),
           (False, True))
        segs = L.ler("DU_ROLO-UNICO_PARA-COR_ADD_TAKE_ROLO03_AUDIOS", audio=False)["segmentos"]
        mr = [{"segment_index": i, "matched_path": "/x/" + s["clip_name"]} for i, s in enumerate(segs)
              if not (s["is_gap"] or s["is_transition"] or s["is_effect"])]
        ok("⭐ um nest só no filme: C87 em 01:22:49:07, placa na V3 e policiais na V4",
           _compostos(segs, mr, 24), [{"nome": "C87_COMP_INTERFONE_2", "clipes": [
               {"trilha": 3, "quadro": 119263, "arquivo": "A044C016_240725_R1X0.mov"},
               {"trilha": 4, "quadro": 119263, "arquivo": "87-INSERT-EXTRA-2.mp4"}]}])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
