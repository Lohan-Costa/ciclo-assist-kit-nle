"""Spike — Carta Aberta C1, a prova na D01 da PRODUCAO-A: N mídias, quantas com cada forma, quantas sem vínculo e por
quê (o "pronto quando" da C1, plano §5).

    python spikes/carta_aberta_c1_d01.py <raiz de um projeto NOVO (pasta vazia que já existe)>

No Mac mini (2026-11-12) o que existe da D01: a OP-Atom do SOM (5 masters em `Avid MediaFiles/MXF/0102304031`, o projeto
do MC é do Windows), a versão de trabalho (21 MP4 da câmera A, 5 WAV do som direto em `CONVERTIDOS/D01_230403`), e o
original BRAW não (o NAS está desligado). Os gestos são os da C1 sem a tela: mandar do Avid (os masters), mandar do
Premiere (os MP4, como os clipes de uma bin), anexar a pasta do som direto como `trabalho`.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cicloassist.carta import anexar, diario, projeto, referencias  # noqa: E402
from cicloassist.midia import acervo  # noqa: E402

MXF = Path("/Volumes/SSD/Avid MediaFiles/MXF/0102304031")
D01 = Path("/Volumes/SSD/MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/MIDIAS/CONVERTIDOS/D01_230403")


def dizer(titulo: str, c: anexar.Conta, t0: float) -> None:
    print(f"{titulo} ({time.time() - t0:.1f} s): {len(c.novas)} novas, {len(c.ja_estavam)} já estavam, "
          f"{len(c.vinculos)} vínculos, {len(c.empates)} empates, {len(c.sem_par)} sem par, {len(c.ilegiveis)} ilegíveis")
    for n, arqs in c.empates.items():
        print(f"   empate {n}: {arqs}")
    for a in c.sem_par[:8]:
        print(f"   sem par: {a}")
    for a, e in c.ilegiveis.items():
        print(f"   ilegível: {a}: {e}")


def main(raiz: str) -> int:
    raiz = Path(raiz)
    proj = projeto.abrir(raiz) if (raiz / projeto.PASTA_INTERNA).exists() else projeto.novo(raiz, "PRODUCAO-A",
                                                                                              "24000/1001")
    (raiz / "Diarias" / "D01").mkdir(parents=True, exist_ok=True)     # o EDITOR cria a pasta (aqui, o spike por ele)

    t = time.time(); c = anexar.mandar_do_avid(proj, "Diarias/D01", acervo.varrer(MXF)); dizer("mandar do Avid", c, t)
    cams = sorted(p for p in (D01 / "01_CAMERAS").rglob("*.mp4") if not p.name.startswith("._"))
    t = time.time(); c = anexar.mandar_arquivos(proj, "Diarias/D01", cams, "trabalho", "premiere")
    dizer("mandar do Premiere (câmera A)", c, t)
    t = time.time(); c = anexar.anexar(proj, D01 / "02_SOM-DIRETO", "trabalho"); dizer("anexar o som direto", c, t)
    # a mesma pasta tem OP-Atom de OUTRO master do Avid (um `.mxf` por canal): é a forma `avid`, não `trabalho`
    t = time.time(); c = anexar.anexar(proj, D01 / "02_SOM-DIRETO", "avid"); dizer("anexar a OP-Atom do som", c, t)

    formas = diario.formas(proj)
    refs = referencias.todas(proj)
    conta: dict[tuple, list[str]] = {}
    for _, d in refs:
        tem = tuple(sorted({f["forma"] for f in formas.get(d["id"], [])}))
        conta.setdefault(tem, []).append(d["nome"])
    print(f"\n== D01: {len(refs)} mídias")
    for tem, nomes in sorted(conta.items()):
        falta = [f for f in anexar.FORMAS if f not in tem]
        print(f"   {len(nomes):3} com {' + '.join(tem) or 'nada'}  (falta: {', '.join(falta)})")
    print("   por quê: original (BRAW) — o NAS está desligado; avid da câmera A — a OP-Atom dela não está neste disco")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1]))
