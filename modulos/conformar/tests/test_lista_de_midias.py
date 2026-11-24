"""A "lista de mídias" da tela "antes de montar" e o IGNORAR (autor, 2026-10-06).

Rodar:

    .venv-win/Scripts/python tests/test_lista_de_midias.py      (Mac: .venv/bin/python)

- cada arquivo de vídeo da sequência, com o estado: `original` (casou, ou imagem parada que já é o
  final), `sem_original` (o proxy existe) ou `nao_encontrado` (nem o proxy);
- o codec vem do cache da sondagem que o casamento já fez; sem ele, a extensão;
- ignorar tira o arquivo do "no proxy" do relatório, ⛔ MAS NÃO o que nem o proxy existe ("se o png não
  existir nas pastas nem no caminho original, ele deve ser sinalizado mesmo ignorado");
- os ignorados são lembrados POR PROJETO (como as pastas), e a lista inteira se regrava;
- a rota leva `ignorar` só como lista de texto, com teto.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import sessao_receber as R  # noqa: E402
import tools.prproj_para_drt as T  # noqa: E402
from prproj import originais as O  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        casou, sem, png, sumiu = (t / "A001.mov"), (t / "B002.mov"), (t / "mascara.png"), str(t / "C003.mxf")
        for f in (casou, sem, png):
            f.write_bytes(b"x")
        # o codec é o do arquivo ENCONTRADO (2026-10-19): o original casado, não o proxy
        orig = str(t / "A001_original.mov")
        casamento = {str(casou): {"estado": "original", "original": orig}, str(sem): {"estado": "sem_original"},
                     str(png): {"estado": "proprio"}, sumiu: {"estado": "sem_original"}}

        print("a lista")
        with mock.patch.dict(O._SONDA, {orig: {"codec": "prores"}, str(casou): {"codec": "h264"},
                                        str(sem): {"codec": "unknown"}}):
            lista = {m["nome"]: m for m in T.lista_de_midias(casamento)}
        ok("os quatro arquivos, cada um com o estado",
           {n: m["estado"] for n, m in lista.items()},
           {"A001.mov": "original", "B002.mov": "sem_original", "mascara.png": "original",
            "C003.mxf": "nao_encontrado"})
        ok("o codec da sondagem; 'unknown' (ARRIRAW) e sem sondagem viram a extensão",
           (lista["A001.mov"]["codec"], lista["B002.mov"]["codec"], lista["mascara.png"]["codec"],
            lista["C003.mxf"]["codec"]), ("prores", "MOV", "PNG", "MXF"))

        print("ignorar")
        ok("sem ignorar: os dois que não casaram estão no 'no proxy'",
           T.faltam_sem_ignorados(casamento, set()), ["B002.mov", "C003.mxf"])
        ok("⭐ ignorado com o proxy no disco: sai do relatório",
           T.faltam_sem_ignorados(casamento, {str(sem)}), ["C003.mxf"])
        ok("⛔ ignorado que NEM o proxy existe: continua no relatório",
           T.faltam_sem_ignorados(casamento, {sumiu}), ["B002.mov", "C003.mxf"])

        print("lembrado por projeto")
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: t / "dados"):
            (t / "dados").mkdir()
            prproj = str(t / "EP05.prproj")
            ok("projeto novo: nada lembrado", R.ignorados_do_projeto(prproj), [])
            R.lembrar_ignorados(prproj, [str(sem), str(sem)])
            ok("grava a lista (sem repetir)", R.ignorados_do_projeto(prproj), [str(sem)])
            ok("outro projeto não enxerga", R.ignorados_do_projeto(str(t / "OUTRO.prproj")), [])
            R.lembrar_ignorados(prproj, [])
            ok("desfazer todos: a lista some", R.ignorados_do_projeto(prproj), [])

        print("a rota")
        from api import rotas
        pedidos = []

        class Receber:
            def preparar_avulso(self, chave, mob_id="", originais=None, raizes=None, notas=False, sinais=None):
                pedidos.append(sinais)
                return {"drt": "x"}
        ctx = lambda corpo: SimpleNamespace(json=lambda: corpo, servico=SimpleNamespace(receber=Receber()))  # noqa: E731
        rotas.receber_preparar(ctx({"avulso": "11111111-1111-1111-1111-111111111111", "mob_id": "s",
                                    "ignorar": [str(sem), 5, {"x": 1}, "y" * 5000]}))
        ok("⭐ só texto passa (número, objeto e texto gigante ficam de fora)",
           pedidos and pedidos[-1].get("ignorar"), [str(sem)])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
