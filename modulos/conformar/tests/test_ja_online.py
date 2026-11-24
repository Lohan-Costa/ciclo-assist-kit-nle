"""Já online sem casamento: só o OFFLINE fica à vista na _SEQ (autor, 2026-10-13).

Rodar:

    .venv/bin/python tests/test_ja_online.py        (Windows: .venv-win/Scripts/python)

`ja_online.classificar` com o índice da Avid MediaFiles e a varredura do projeto FALSOS (arquivos de verdade num
temporário), e `relink_avb._com_ja_online`, que acrescenta esses masters ao conjunto que a _SEQ oculta.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import ja_online  # noqa: E402
from avb_bin import ama_do_projeto  # noqa: E402
from media import pmr  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


URN = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.{:08x}.0000000a.00000000.00000000"
M = [SimpleNamespace(nome=f"M{i}", mob_id=URN.format(i), esta_offline=None) for i in range(6)]


def chave(i):
    return ja_online.chave_mob(URN.format(i))


def classificar():
    print("classificar")
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_jaonline_"))
    existe = tmp / "M0.mxf"
    existe.write_bytes(b"x")
    ama_arq = tmp / "M2.mov"
    ama_arq.write_bytes(b"x")
    data = int(os.path.getmtime(ama_arq))
    projeto = tmp / "projeto"
    projeto.mkdir()

    pmr.raizes_de_midia = lambda: ["X"]
    pmr.indice_de = lambda raizes: pmr.Leitura(por_master={
        URN.format(0).upper(): [str(existe)],          # existe → gerenciada (e a caixa da URN não importa)
        URN.format(1): [str(tmp / "sumiu.mxf")],       # no índice, mas o arquivo sumiu → não está online
    })
    ama_do_projeto.varrer = lambda pasta, cache=None, ignorar=(): {
        "a": [{"mob_id": URN.format(2), "caminho": str(ama_arq), "data": data}],         # AMA online
        "b": [{"mob_id": URN.format(3), "caminho": str(ama_arq), "data": data - 99}],    # data não bate → offline
    }
    M[4].esta_offline = False                                                            # rota da bin: AMA conferido

    r = ja_online.classificar(M, str(projeto))
    ok("Avid MediaFiles com o arquivo no disco: gerenciada", r.get(chave(0)), "gerenciada")
    ok("no índice, mas o arquivo sumiu: fora", chave(1) in r, False)
    ok("link AMA do projeto, online: ama", r.get(chave(2)), "ama")
    ok("link AMA com a data errada: fora", chave(3) in r, False)
    ok("esta_offline False (bin): ama", r.get(chave(4)), "ama")
    ok("nada sabido: fora (fica à vista)", chave(5) in r, False)
    ok("sem pasta de projeto: sem a varredura AMA", ja_online.classificar(M[2:3], "").get(chave(2)), None)
    ok("lista vazia: vazio", ja_online.classificar([], str(projeto)), {})

    def quebra(_):
        raise OSError("disco fora")
    pmr.indice_de = quebra
    ok("índice ilegível não derruba (AMA ainda vale)", ja_online.classificar(M, str(projeto)).get(chave(2)), "ama")


def seq_oculta():
    print("a _SEQ oculta o que já está online")
    import relink_avb

    mobs = [SimpleNamespace(mob_id=URN.format(i)) for i in range(3)]
    f = SimpleNamespace(content=SimpleNamespace(mobs=mobs))
    t = SimpleNamespace(ja_online={chave(1): "gerenciada"})
    ok("acrescenta o já online", relink_avb._com_ja_online(f, {"x"}, t), {"x", URN.format(1)})
    ok("sem ja_online: igual", relink_avb._com_ja_online(f, {"x"}, SimpleNamespace()), {"x"})


def rota_da_aaf():
    print("rota da AAF: os MobIDs novos da cópia importada")
    import relink_avb
    from relink import Trabalho

    t = Trabalho()
    t.masters = [SimpleNamespace(nome="A", mob_id="aa", mob_id_urn="u:aa"), SimpleNamespace(nome="B", mob_id="bb", mob_id_urn="u:bb")]
    t.escolhas, t.ignorados, t.ja_online = {"aa": "A.mov"}, {"bb"}, {"bb": "gerenciada"}
    api = "060a2b340101010501010f2013000000" + "11" * 16
    with relink_avb._com_ids(t, {"aa": api, "bb": api.replace("11", "22")}) as c:
        novo_b = c.trocas["bb"][0]
        ok("ignorados traduzidos", t.ignorados, {novo_b})
        ok("já online traduzidos", t.ja_online, {novo_b: "gerenciada"})
        ok("a ignorada fica fora dos decididos", novo_b in t.decididos(), False)
    ok("na saída: ignorados de volta", t.ignorados, {"bb"})
    ok("na saída: já online de volta", t.ja_online, {"bb": "gerenciada"})


def main() -> int:
    classificar()
    seq_oculta()
    rota_da_aaf()
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
