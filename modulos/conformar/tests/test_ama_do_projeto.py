"""O que o projeto já linkou (AMA), lido das bins — `motor/avb_bin/ama_do_projeto.py` (2026-10-13).

Base do REAPROVEITAMENTO no relink do MC: o `LinkFile` de um arquivo que o projeto já linkou é ~10× mais lento e deixa
uma cópia a mais (banco, `avid-panel-sdk/windows.md` §14). Amostra real: `03 CASOS/MIDIA/M07 REUSO AMA` (48 vídeos
linkados pelo MC + 46 áudios injetados). Sem a pasta de amostras: os casos com a bin real são PULADOS.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "tests"))

from avb_bin import ama_do_projeto as A  # noqa: E402
from casos import raiz_das_amostras  # noqa: E402

AMOSTRA = Path(raiz_das_amostras()) / "03 CASOS" / "MIDIA" / "M07 REUSO AMA" / "PRODA_MIDIAS_LINKADAS.avb"


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<52} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── online: o arquivo existe E a data bate ─────────────────────")
    with tempfile.TemporaryDirectory() as tmp:
        arq = Path(tmp) / "x.mov"
        arq.write_bytes(b"x")
        mt = int(os.path.getmtime(arq))
        ok("data igual = online", A.online({"caminho": str(arq), "data": mt}), True)
        ok("data diferente = offline", A.online({"caminho": str(arq), "data": mt - 10}), False)
        ok("sem data = offline (o MC também)", A.online({"caminho": str(arq), "data": None}), False)
        ok("arquivo sumiu = offline", A.online({"caminho": str(Path(tmp) / "nao.mov"), "data": mt}), False)
        indice = {A.chave(str(arq)): [{"caminho": str(arq), "data": mt - 1, "mob_id": "velho"},
                                      {"caminho": str(arq), "data": mt, "mob_id": "bom"}]}
        ok("reaproveitável = o 1º ONLINE", (A.reaproveitavel(indice, str(arq)) or {}).get("mob_id"), "bom")
        ok("caixa/barras não importam (Windows)",
           (A.reaproveitavel(indice, str(arq).upper() if os.name == "nt" else str(arq)) or {}).get("mob_id"),
           "bom")

    if not AMOSTRA.exists():
        print(f"\n(PULADO: sem a amostra {AMOSTRA})")
    else:
        print("\n── a bin real (M07): 48 vídeos do LinkFile + 46 áudios injetados ─")
        itens = A.da_bin(str(AMOSTRA))
        ok("94 arquivos com master AMA", len(itens), 94)
        ext = sorted({Path(v[0]["caminho"]).suffix.lower() for v in itens.values()})
        ok("vídeo do LinkFile entra (WinFileLocator)", ".braw" in ext and ".mov" in ext, True)
        ok("áudio injetado entra", ".wav" in ext, True)
        ok("todo item com MobID e data", all(x["mob_id"] and x["data"] is not None
                                             for v in itens.values() for x in v), True)

        print("\n── o cache: relê só a bin que mudou ───────────────────────────")
        with tempfile.TemporaryDirectory() as tmp:
            proj = Path(tmp) / "PROJ"
            (proj / "PASTA").mkdir(parents=True)
            shutil.copy(AMOSTRA, proj / "PASTA" / "A.avb")
            cache = str(Path(tmp) / "cache.json")
            r1 = A.varrer(str(proj), cache)
            ok("1ª varredura acha os 94", len(r1), 94)
            ok("cada item sabe a bin", all(x["bin"].endswith("A.avb") for v in r1.values() for x in v), True)
            t = time.time()
            r2 = A.varrer(str(proj), cache)
            ok("2ª varredura (cache) = mesmo resultado", r2 == r1, True)
            ok("2ª varredura rápida (< 0,2 s)", time.time() - t < 0.2, True)
            ok("bin ignorada fica de fora", len(A.varrer(str(proj), None, ignorar=(str(proj / "PASTA" / "A.avb"),))), 0)

        print("\n── classificar (o \"só offline\") acha o caminho no Windows ────")
        from avb_bin.masters import classificar
        from avb_export.reader import topen
        with topen(str(AMOSTRA)) as f:
            vistos = [classificar(m) for m in f.content.mastermobs()
                      if (m.attributes is not None and "_IMPORTED_AMA" in m.attributes)]
        ok("e_ama em todos os 94", sum(1 for e, _ in vistos if e), 94)
        # online ou offline depende do HD G: — o que não pode é "não sei" (None) para quem tem caminho
        ok("offline decidido (True/False), nunca None", sum(1 for _, o in vistos if o is None), 0)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
