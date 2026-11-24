"""O código de cores dos Sinais do Import, editável em Ajustes (aprovado pelo autor em 2026-09-27).

Rodar:

    .venv-win/Scripts/python tests/test_codigo_de_cores.py

Confere as quatro decisões do organograma:
- o código fica NESTA máquina (a pasta de dados, isolada aqui numa pasta temporária);
- a palavra-chave DLPC pode ser trocada;
- as categorias são fixas (nome inventado não entra);
- cor repetida em duas categorias AVISA e deixa.
E que o writer usa o código da equipe, e que arquivo mexido à mão nunca derruba o Trazer.
"""

from __future__ import annotations

import json
import re
import sys
import tempfile
import zipfile
from pathlib import Path
from unittest import mock

import zstandard

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import codigo_de_cores as CC  # noqa: E402
from api import rotas  # noqa: E402,F401  (registra as rotas)
from api.servidor import _ROTAS, Contexto  # noqa: E402
from drp import sinais as SN  # noqa: E402
from drp.writer import _sinais  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 62 else f"{repr(obtido)[:59]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── 1. validar ──")
    fab = SN.de_fabrica()
    ok("sem nada: o de fábrica", SN.validar_codigo(None), fab)
    ok("⭐ o de fábrica é o aprovado (Fuchsia/Pink, Red/Chocolate, Yellow/Yellow, DLPC)",
       [(v["marcador"], v["clipe"]) for v in fab["cores"].values()] + [fab["palavra"]],
       [("Fuchsia", "Pink"), ("Red", "Chocolate"), ("Yellow", "Yellow"), "DLPC"])
    mexido = {"cores": {"refazer": {"marcador": "Roxo", "clipe": "Orange"}, "inventada": {"marcador": "Blue"}},
              "palavra": "  COR;EQUIPE,A\n  "}
    v = SN.validar_codigo(mexido)
    ok("nome fora da tabela volta ao de fábrica; o válido fica", v["cores"]["refazer"],
       {"marcador": "Red", "clipe": "Orange"})
    ok("categoria inventada não entra", sorted(v["cores"]), sorted(SN.CATEGORIAS))
    ok("a palavra-chave sem vírgula, ponto e vírgula e controle", v["palavra"], "COREQUIPEA")
    ok("palavra vazia volta a DLPC", SN.validar_codigo({"palavra": "   "})["palavra"], "DLPC")
    ok("palavra longa é cortada em 32", len(SN.validar_codigo({"palavra": "X" * 80})["palavra"]), 32)

    print("\n── 2. cor repetida avisa e deixa ──")
    ok("o de fábrica não tem cor repetida", SN.repeticoes(fab), [])
    rep = SN.validar_codigo({"cores": {"refazer": {"clipe": "Yellow"}}})
    ok("Refazer e Conferir com o mesmo segmento: aviso, e o código fica",
       (SN.repeticoes(rep), rep["cores"]["refazer"]["clipe"]),
       (["Refazer e Conferir estão com o mesmo segmento Yellow"], "Yellow"))

    print("\n── 3. o writer usa o código da equipe ──")
    pool = '<Sm2Sequence DbId="SEQ-1">'
    sinais = [{"segmento": 0, "cor": "distorcao", "inicio": 10, "linhas": [[("STRETCH", True)]]},
              {"segmento": 1, "cor": "refazer", "inicio": 50, "linhas": [[("ESTABILIZADO", False)]]}]
    equipe = {"cores": {"distorcao": {"marcador": "Purple", "clipe": "Violet"}}, "palavra": "COR-SALA2"}
    blocos, n_m, n_c = _sinais(sinais, {0: "CLIPE-A", 1: "CLIPE-B"}, pool, True, True, equipe)
    ok("dois segmentos pintados e dois marcadores", (n_m, n_c), (2, 2))
    def cor_do(bloco):
        fim = bloco.split("<FieldsBlob>")[1].split("<")[0][-4:]     # 0x28 + a cor (campo 5)
        return next(n for n, v in SN.COR_DE_CLIPE.items() if fim == "28%02x" % v)

    ok("⭐ o segmento do Stretch com a cor da equipe (Violet)",
       ("BlobOwner>CLIPE-A" in blocos[0], cor_do(blocos[0])), (True, "Violet"))
    ok("…e o outro no de fábrica (Chocolate)", ("BlobOwner>CLIPE-B" in blocos[1], cor_do(blocos[1])),
       (True, "Chocolate"))
    fb = re.search(r"<FieldsBlob>(\w+)</FieldsBlob>", blocos[2]).group(1)
    from drp.ba_mapa import ler_mapa
    _v, itens, _r = ler_mapa(bytes.fromhex(fb))
    dados = zstandard.ZstdDecompressor().decompress(itens[0][1][2][9:], max_output_size=1 << 20)
    ok("⭐ a palavra-chave da equipe no marcador, sem a DLPC", (b"COR-SALA2" in dados, b"DLPC" in dados),
       (True, False))
    ok("o marcador do Stretch em Purple (128)", bytes([0x08, 0x80, 0x01]) in dados, True)

    print("\n── 4. guardado NESTA máquina, pela rota do painel ──")
    with tempfile.TemporaryDirectory() as d, \
            mock.patch.object(CC.plataforma, "pasta_dados", lambda: Path(d)):
        def chamar(metodo, corpo=None):
            ctx = Contexto(metodo, "/ajustes/sinais", {}, json.dumps(corpo).encode() if corpo else b"", None)
            return _ROTAS[(metodo, "/ajustes/sinais")](ctx)

        st, r = chamar("GET")
        ok("sem arquivo: o de fábrica, as tabelas e as categorias",
           (st, r["codigo"] == fab, len(r["tabelas"]["marcador"]), len(r["tabelas"]["clipe"]),
            list(r["categorias"])), (200, True, 16, 16, ["distorcao", "refazer", "conferir"]))
        st, r = chamar("POST", {"codigo": {"cores": {"conferir": {"clipe": "Chocolate"}}, "palavra": "SALA2"}})
        ok("⭐ gravar: fica valendo e avisa a repetição",
           (st, r["codigo"]["cores"]["conferir"]["clipe"], r["codigo"]["palavra"], r["avisos"]),
           (200, "Chocolate", "SALA2", ["Refazer e Conferir estão com o mesmo segmento Chocolate"]))
        ok("o arquivo está na pasta de dados da máquina", (Path(d) / CC.ARQUIVO).is_file(), True)
        ok("…e o Trazer lê o mesmo", CC.ler()["palavra"], "SALA2")
        (Path(d) / CC.ARQUIVO).write_text("{ quebrado", encoding="utf-8")
        ok("⭐ arquivo quebrado não derruba: volta o de fábrica", CC.ler(), fab)
        st, r = chamar("POST", {"fabrica": True})
        ok("Voltar ao de fábrica", (st, r["codigo"]), (200, fab))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
