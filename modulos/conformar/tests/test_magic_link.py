"""Magic Link, lado de quem envia — sem Media Composer.

Rodar:

    .venv-win/Scripts/python tests/test_magic_link.py

A pasta combinada vive na `.delapraca.json` do PROJETO (segue a produção); o nome do arquivo
diz a sequência e não colide; um item da lista que a timeline não tem mais "mudou" e não vai.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import magic_link  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<58} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    with tempfile.TemporaryDirectory() as tmp:
        projeto, combinada = Path(tmp) / "PROJETO", Path(tmp) / "magic"
        projeto.mkdir()
        combinada.mkdir()
        ok("sem configuração, não há canais", magic_link.canais_do_projeto(str(projeto)), {})
        magic_link.guardar_canal_no_projeto(str(projeto), "cor", str(combinada))
        ok("o canal fica guardado NO PROJETO", magic_link.canais_do_projeto(str(projeto)),
           {"cor": str(combinada)})
        ok("…na .delapraca.json", (projeto / ".delapraca.json").is_file(), True)
        import json as _json
        cfg = _json.loads((projeto / ".delapraca.json").read_text(encoding="utf-8"))
        cfg["magic_link"]["pasta"] = str(combinada)          # a pasta única de antes
        (projeto / ".delapraca.json").write_text(_json.dumps(cfg), encoding="utf-8")
        ok("⭐ a pasta única antiga não vira canal", sorted(magic_link.canais_do_projeto(str(projeto))),
           ["cor"])
        for ruim, trecho in (("relativa", "caminho completo"), (str(Path(tmp) / "nao-existe"), "não existe")):
            try:
                magic_link.guardar_canal_no_projeto(str(projeto), "vfx", ruim)
                ok(f"pasta {ruim[:20]} recusada", "aceitou", "recusou")
            except ValueError as e:
                ok(f"pasta {ruim[-20:]} recusada", trecho in str(e), True)
        try:
            magic_link.guardar_canal_no_projeto(str(projeto), "som", str(combinada))
            ok("setor que não existe é recusado", "aceitou", "recusou")
        except ValueError:
            ok("setor que não existe é recusado", "recusou", "recusou")

    e1, e2 = magic_link.novo_envio("insert_vfx"), magic_link.novo_envio("insert_vfx")
    ok("cada envio tem id próprio", e1["id"] != e2["id"], True)
    ok("remetente: máquina e usuário", sorted(e1["remetente"]), ["maquina", "usuario"])
    e3 = magic_link.novo_envio("insert_vfx", "vfx")
    ok("⭐ o envelope diz o canal e a direção", (e3["canal"], e3["de"], e3["para"]),
       ("vfx", "edicao", "vfx"))
    ok("sem canal, o envelope é o de antes", "canal" in e1, False)
    ok("o tipo do insert vem da lista de setores", magic_link.TIPOS_INSERT,
       {"cor": "insert_cor", "vfx": "insert_vfx"})
    c1 = magic_link.caminho_do_envio(r"S:\magic", "PRODA_CORTE.02", e1)
    c2 = magic_link.caminho_do_envio(r"S:\magic", "PRODA_CORTE.02", e2)
    ok("o nome diz a sequência e termina em .carta.json",
       (Path(c1).name.startswith("PRODA_CORTE"), c1.endswith(".carta.json")), (True, True))
    ok("dois envios da mesma sequência não colidem", c1 != c2, True)
    ok("nome hostil não escapa da pasta", Path(magic_link.caminho_do_envio(
        r"S:\magic", r"..\..\Windows\x", e1)).parent, Path(r"S:\magic"))

    seq = {"timeline_fps": 25.0, "segments": [
        {"track": 1, "timeline_tc_in": "00:00:04:00", "timeline_tc_out": "00:00:08:00", "mob_id": "m2",
         "is_gap": False, "is_transition": False}]}
    valem, mudaram = magic_link.conferir_itens(
        [{"track": 1, "timeline_tc_in": "00:00:04:00", "timeline_tc_out": "00:00:08:00", "mob_id": "m2"},
         {"track": 1, "timeline_tc_in": "00:00:05:00", "timeline_tc_out": "00:00:07:00", "mob_id": "m2"},
         {"track": 1, "timeline_tc_in": "00:00:07:00", "timeline_tc_out": "00:00:09:00", "mob_id": "m2"},
         {"track": 2, "timeline_tc_in": "00:00:04:00", "timeline_tc_out": "00:00:08:00", "mob_id": "m2"}],
        seq)
    ok("item igual e trecho dentro VALEM", len(valem), 2)
    ok("⭐ item que passou do fim ou mudou de trilha MUDOU (não vai)", len(mudaram), 2)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
