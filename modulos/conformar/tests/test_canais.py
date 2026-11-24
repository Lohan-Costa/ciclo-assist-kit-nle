"""Magic Link em canais — a edição no meio, um canal por setor (`canais.py`).

Rodar:

    .venv-win/Scripts/python tests/test_canais.py

- Sem papel (autor, 2026-09-25): a ilha é o que ela CONECTA. Um canal liga a Edição a um setor.
- A pasta de um canal tem uma caixa para cada lado, e cada caixa o seu `importado`.
- A edição grava na caixa do setor; o insert pega o tipo do canal.
- Arquivar move para `importado/<timelines|inserts>` e nunca sobrescreve.
- ⭐ Setor novo (som) é UMA entrada em `SETORES`, e o resto acompanha.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import canais  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 56 else f"{repr(obtido)[:53]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    def recusa(rotulo, fn, erro=ValueError):
        try:
            fn()
            ok(rotulo, "aceitou", erro.__name__)
        except erro:
            ok(rotulo, erro.__name__, erro.__name__)

    with tempfile.TemporaryDirectory() as tmp:
        dados = Path(tmp) / "dados"
        with mock.patch.object(canais.plataforma, "pasta_dados", lambda: dados):
            print("── 1. os canais desta máquina (o Resolve) ──")
            ok("sem nada guardado, nenhum canal", canais.canais_da_maquina(), {})
            dados.mkdir(parents=True)
            (dados / canais.CONFIG).write_text(json.dumps({"papel": "cor", "pasta": "S:/antiga"}),
                                               encoding="utf-8")
            canais.guardar_canal_na_maquina("cor", r"S:\magic-cor")
            ok("o canal fica guardado na máquina", canais.canais_da_maquina(), {"cor": r"S:\magic-cor"})
            ok("⭐ o papel antigo sai do arquivo (não existe mais)",
               "papel" in json.loads((dados / canais.CONFIG).read_text(encoding="utf-8")), False)
            (dados / canais.CONFIG).write_text("{ estragado", encoding="utf-8")
            ok("config estragada volta ao padrão (sem canais)", canais.canais_da_maquina(), {})

        print("\n── 2. os dois lados de um canal ──")
        ok("um canal liga a Edição a um setor", canais.lados("cor"), ("edicao", "cor"))
        ok("as caixas se chamam para-<lado>",
           (canais.caixa_nome("edicao"), canais.caixa_nome("vfx")), ("para-edicao", "para-vfx"))
        ok("os rótulos dos lados vêm da lista de setores", canais.ROTULO_LADO,
           {"edicao": "Edição", "cor": "Cor", "vfx": "VFX"})

        print("\n── 3. a pasta do canal ──")
        canal = Path(tmp) / "magic-cor"
        canal.mkdir()
        cfg = {"cor": str(canal)}
        saida = canais.caixa_de_saida(cfg, "cor")
        ok("a Edição envia para a caixa da Cor", Path(saida), canal / "para-cor")
        ok("as duas caixas nascem com importado/timelines e importado/inserts",
           sorted(str(p.relative_to(canal)).replace("\\", "/") for p in canal.rglob("*") if p.is_dir()),
           ["para-cor", "para-cor/importado", "para-cor/importado/inserts",
            "para-cor/importado/timelines", "para-edicao", "para-edicao/importado",
            "para-edicao/importado/inserts", "para-edicao/importado/timelines"])
        recusa("canal desconhecido é recusado", lambda: canais.caixa_de_saida(cfg, "som"))
        recusa("canal não conectado pede para conectar", lambda: canais.caixa_de_saida({}, "vfx"))
        recusa("canal que sumiu da rede também",
               lambda: canais.caixa_de_saida({"vfx": str(Path(tmp) / "fora")}, "vfx"))
        ok("⭐ o insert pega o tipo do canal",
           (canais.tipo_do_insert("cor"), canais.tipo_do_insert("vfx")), ("insert_cor", "insert_vfx"))
        recusa("pasta relativa é recusada", lambda: canais.validar_pasta("magic"))

        print("\n── 4. arquivar o que já entrou ──")
        caixa = canal / "para-cor"
        (caixa / "A__1.carta.json").write_text("{}", encoding="utf-8")
        ok("na caixa, a Carta está pendente", canais.e_pendente(str(caixa / "A__1.carta.json")), True)
        novo = canais.arquivar(str(caixa / "A__1.carta.json"), "insert_cor")
        ok("o insert desce para importado/inserts", Path(novo).parent, caixa / "importado" / "inserts")
        ok("…e sai da fila", (caixa / "A__1.carta.json").exists(), False)
        ok("no importado, não está mais pendente", canais.e_pendente(novo), False)
        (caixa / "A__1.carta.json").write_text("{}", encoding="utf-8")
        novo2 = canais.arquivar(str(caixa / "A__1.carta.json"), "insert_cor")
        ok("⭐ nome repetido nunca sobrescreve", Path(novo2).name, "A__1_2.carta.json")
        (caixa / "T__9.carta.json").write_text("{}", encoding="utf-8")
        ok("a timeline desce para importado/timelines",
           Path(canais.arquivar(str(caixa / "T__9.carta.json"), "timeline")).parent.name, "timelines")

        print("\n── 5. um setor novo é uma linha ──")
        som = {"rotulo": "Som", "de": "do Som", "para": "para o Som", "insert": "insert_som"}
        with mock.patch.dict(canais.SETORES, {"som": som}):
            ok("o canal Som liga a Edição ao Som", canais.lados("som"), ("edicao", "som"))
            ok("o insert pelo canal Som é um insert de som", canais.tipo_do_insert("som"), "insert_som")
            som_dir = Path(tmp) / "magic-som"
            som_dir.mkdir()
            ok("a Edição envia para a caixa do Som",
               Path(canais.caixa_de_saida({"som": str(som_dir)}, "som")).name, "para-som")

    # B098: a câmera com 4 streams MONO tem 4 canais no DRT (o palpite de canal cicla por eles), não 1
    from drp import writer as W
    quatro = {"streams": [{"codec_type": "video"}] + [{"codec_type": "audio", "channels": 1, "sample_rate": "48000",
                                                       "duration_ts": "480000"} for _ in range(4)], "format": {}}
    with mock.patch.object(W._sonda, "ler", return_value=quatro):
        W._META_CACHE_A.pop("/x/camera_4_mono.mov", None)
        ok("DRT: 4 streams mono = 4 canais", W._audio_meta("/x/camera_4_mono.mov")[3], 4)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
