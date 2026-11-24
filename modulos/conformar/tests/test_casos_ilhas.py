"""Cada caso de teste é uma ILHA: um projeto não acha mídia de outro (regra do autor, 2026-10-04).

Rodar:

    .venv/bin/python tests/test_casos_ilhas.py        (Windows: .venv-win/Scripts/python)

"Não podemos misturar projetos": o PRODUCAO-A é laboratório, o PRODB é filme real, e o resultado de
um teste não pode depender do que outro projeto deixou no disco. Antes, o teste do caso U03 (PRODA)
varria todo `Avid MediaFiles` montado e todo volume — a contagem mudava com os HDs plugados, e o room
tone ausente aparecia como "falha".

Trava aqui:
  1. todo `caso.json` é legível e declara o projeto e as mídias;
  2. `isolar_midia` não deixa passar NADA fora das pastas do caso (nem mídia de outro projeto no
     mesmo `Avid MediaFiles`);
  3. nenhum teste chama a busca de mídia da máquina (`_midia_da_carta`, `raizes_de_midia`) sem isolar.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "tests")]

import casos as ilhas  # noqa: E402

n, falhas = 0, []


def ok(nome, obtido, esperado):
    global n
    n += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    print("── 3. nenhum teste busca mídia na máquina sem isolar ──")
    soltos = []
    for f in sorted((RAIZ / "tests").glob("test_*.py")):
        if f.name == Path(__file__).name:
            continue
        t = f.read_text(encoding="utf-8")
        busca = re.search(r"_midia_da_carta\(|raizes_de_midia\(\)", t)
        if busca and "isolar_midia" not in t:
            soltos.append(f.name)
    ok("todo teste que busca mídia o faz dentro de `isolar_midia` (as pastas do caso)", soltos, [])

    base = ilhas.amostras()
    if base is None:
        print("  pasta de testes não está nesta máquina — o resto PULA")
        return _fim()

    print("── 1. os manifestos ──")
    manifestos = sorted((base / "03 CASOS").rglob("caso.json"))
    ok("há manifestos (U03, R02, R03…)", len(manifestos) >= 3, True)
    for m in manifestos:
        c = json.loads(m.read_text(encoding="utf-8"))
        ok(f"{m.parent.name}: declara projeto e mídias", (bool(c.get("projeto")), isinstance(c.get("midia"), dict)),
           (True, True))

    print("── 2. o isolamento ──")
    u03 = ilhas.carregar("ATUALIZAR/U03 ATUALIZAR COM AAF")
    if u03["faltando"]:
        print(f"  mídia da PRODA fora desta máquina ({', '.join(u03['faltando'])}) — PULADO")
        return _fim()
    from avb_bin import segmentos
    from media import pmr
    dentro = next(p for p in u03["raizes_gerenciada"][0].iterdir() if p.suffix.lower() == ".mxf")
    # uma mídia de OUTRO projeto no MESMO `Avid MediaFiles` (o SSD guarda PRODE, PRODUCAO-S…)
    vizinhas = [p for p in (u03["raizes_gerenciada"][0].parent).iterdir()
                if p.is_dir() and p not in u03["raizes_gerenciada"]]
    fora = next((x for v in vizinhas for x in v.iterdir() if x.suffix.lower() == ".mxf"), None)
    with ilhas.isolar_midia(u03):
        ok("um MXF da PRODA passa", segmentos.caminho_confiavel(str(dentro))[0] == str(dentro), True)
        if fora is not None:
            ok(f"⛔ um MXF de OUTRO projeto no mesmo disco ({fora.parent.name}) NÃO passa",
               segmentos.caminho_confiavel(str(fora))[0], None)
        idx = pmr.indice_de(pmr.raizes_de_midia()).por_arquivo or {}
        pastas = {str(Path(p).parent) for p in idx.values()}
        ok("o índice da gerenciada só tem as pastas que o caso declara",
           pastas <= {str(p) for p in u03["raizes_gerenciada"]}, True)
    return _fim()


def _fim() -> int:
    print(f"\n{n - len(falhas)}/{n} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
