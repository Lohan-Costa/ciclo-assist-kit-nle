"""O CONFORM PELO MAPA no relink (plano 2026-11-26, etapa 3): o original que a Carta conhece vira `caminho_conhecido`
(o degrau 1 do `casar_masters`, sem varrer pasta); o que discorda do banco vira EMPATE com os dois candidatos; sem o
núcleo no ar, o relink segue como antes. O lado do núcleo: `tests/test_carta_mapa.py` do app.

Rodar:

    .venv/bin/python tests/test_mapa_da_carta.py        (Windows: .venv-win/Scripts/python)
"""
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import mapa_da_carta as mc  # noqa: E402
import premiere_ponte  # noqa: E402
from media.matcher_masters import Casamento  # noqa: E402

casos = 0
falhas: list[str] = []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


class M:
    def __init__(self, k, origem, antes=None):
        self.mob_id, self.nome, self.origem, self.e_audio, self.segmentos = k, k, origem, False, 1
        self.caminho_conhecido = antes


def main() -> int:
    d = Path(tempfile.mkdtemp())
    proxy, orig, outro = str(d / "p.mov"), str(d / "o.mov"), str(d / "banco.mov")
    resp = {"achados": {k: {"arquivo": orig, "carta": "PROD", "forma_do_offline": "trabalho", "frase": "pelo mapa"}
                        for k in ("A", "B", "C")}, "alertas": [{"chave": "D", "motivo": "a impressão não confere"}]}
    ms = [M("A", proxy), M("B", proxy, antes=proxy), M("C", proxy, antes=outro), M("D", proxy)]
    discordam = mc.aplicar(ms, resp)
    ok("o original do mapa vira o caminho conhecido (e o próprio offline não é discordância)",
       [m.caminho_conhecido for m in ms], [orig, orig, None, None])
    ok("o caminho do banco que não é o offline nem o do mapa: discorda", discordam, {"C": outro})
    cs = [Casamento(master=m, arquivo=m.caminho_conhecido, metodo="caminho" if m.caminho_conhecido else "nao_resolvido",
                    confianca=1.0 if m.caminho_conhecido else 0.0) for m in ms]
    mc.marcar(cs, resp, discordam)
    ok("o casado pelo mapa diz que foi pelo mapa", (cs[0].metodo, cs[0].motivo, cs[0].precisa_de_revisao),
       ("mapa", "pelo mapa", False))
    ok("mapa × banco: empate com os dois candidatos, nada escolhido",
       (cs[2].ambiguo, cs[2].arquivo, [c["path"] for c in cs[2].candidatos]), (True, None, [orig, outro]))
    ok("…e o motivo diz que o editor decide", "o editor decide" in cs[2].motivo, True)
    ok("o alerta do mapa vai ao motivo de quem não casou", "impressão não confere" in cs[3].motivo, True)

    original = premiere_ponte._nucleo

    def fora(*a, **k):
        raise premiere_ponte.PremiereIndisponivel("fora do ar")
    premiere_ponte._nucleo = fora
    try:
        ok("sem o Ciclo Assist no ar: resposta vazia, o relink de sempre", mc.consultar([M("A", "/x.mov")]), mc.VAZIO)
    finally:
        premiere_ponte._nucleo = original
    ok("master sem offline nem pergunta", mc.consultar([M("A", "")]), mc.VAZIO)
    print(f"{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
