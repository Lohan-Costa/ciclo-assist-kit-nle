"""Carimba a receita nos quadros que foram guardados sem ela.

    python tools/carimbar_receita_quadros.py           # só diz o que faria
    python tools/carimbar_receita_quadros.py --fazer   # grava

⛔ O defeito (revisão de 2026-09-13): `quadros_de` guardava quadros SEM `gerador.quadros.json`,
e o inventário lê "quadro sem receita" como "a refazer". A decupagem no Mac passou por 165
mídias numa noite, e 162 apareceram "↻ a refazer" na aba Vetores. O conserto no código só vale
para quadros extraídos depois dele; os já guardados precisam deste carimbo.

⛔⛔ **Carimbar é AFIRMAR com que receita o quadro foi feito**, e afirmação errada esconde
cache velho para sempre. Por isso nada aqui é suposto:
- só mídia SEM receita nenhuma (quem tem outra continua com a dela);
- e só se o JPEG guardado tiver a largura da receita de hoje — lida do próprio arquivo, no
  marcador SOF. Largura diferente fica de fora e é listada.

⚠️ A receita (`frames.ASSINATURA`) não mudou desde o primeiro commit (2026-09-10), conferido
no git — mas a largura medida é o que decide, não essa conferência.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.midia import cache as _cache  # noqa: E402
from cicloassist.midia import frames as _frames  # noqa: E402

ESTAGIO = "quadros"


def largura_do_jpeg(dados: bytes) -> int | None:
    """A largura gravada no marcador SOF do JPEG, ou `None` se não achar.

    ⭐ Sem Pillow, como o resto do produto: o SOF0/SOF1/SOF2 guarda altura e largura em
    bytes fixos depois do marcador.
    """
    if dados[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 9 < len(dados):
        if dados[i] != 0xFF:
            i += 1
            continue
        marcador = dados[i + 1]
        if marcador in (0xC0, 0xC1, 0xC2):
            return int.from_bytes(dados[i + 7:i + 9], "big")
        if marcador in (0xD8, 0x01) or 0xD0 <= marcador <= 0xD7:
            i += 2
            continue
        tamanho = int.from_bytes(dados[i + 2:i + 4], "big")
        i += 2 + tamanho
    return None


def avaliar(midia: _cache.Midia) -> tuple[str, str]:
    """`(veredito, detalhe)`: `carimbar` · `tem_receita` · `sem_quadros` · `largura`."""
    if midia.ler_gerador(ESTAGIO):
        return "tem_receita", ""
    guardados = midia.quadros_guardados()
    if not guardados:
        return "sem_quadros", ""
    # ⚠️ Confere TODOS os quadros: uma mídia pode ter quadros de duas origens.
    esperada = _frames.ASSINATURA["largura"]
    for posicao in guardados:
        largura = largura_do_jpeg(midia.caminho_do_quadro(posicao).read_bytes())
        if largura != esperada:
            return "largura", f"quadro {posicao}: {largura} px, receita pede {esperada}"
    return "carimbar", f"{len(guardados)} quadros com {esperada} px"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--fazer", action="store_true", help="grava (sem isto, só mostra)")
    args = p.parse_args()

    contagem: dict[str, int] = {}
    fora: list[str] = []
    carimbar: list[_cache.Midia] = []
    for midia in _cache.todas():
        veredito, detalhe = avaliar(midia)
        contagem[veredito] = contagem.get(veredito, 0) + 1
        if veredito == "carimbar":
            carimbar.append(midia)
        elif veredito == "largura":
            fora.append(f"{midia.nome or midia.chave[:16]} — {detalhe}")

    print(f"cache ........... {_cache.raiz()}")
    print(f"receita de hoje . {_frames.ASSINATURA}")
    for chave, rotulo in (("carimbar", "a carimbar"), ("tem_receita", "já têm receita"),
                          ("sem_quadros", "sem quadros"), ("largura", "largura diferente")):
        print(f"{rotulo:17s} {contagem.get(chave, 0)}")
    for linha in fora:
        print(f"   fora: {linha}")

    if not args.fazer:
        print("\nnada gravado. Rode com --fazer para carimbar.")
        return 0
    for midia in carimbar:
        midia.registrar_gerador(ESTAGIO, dict(_frames.ASSINATURA))
    print(f"\ncarimbadas: {len(carimbar)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
