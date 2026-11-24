"""A rota de relink pela bin relinka a timeline PEDIDA, mesmo numa bin com várias (`avb_bin/masters.py`).

Rodar:

    .venv-win/Scripts/python tests/test_bin_varias_timelines.py

## Por que este teste existe

A rota `.avb` (ADR 0013) lia os masters — e achatava, media, repontava e ajustava — na "composição de mais trilhas" da
bin (`percurso.timeline`). Numa bin com várias timelines é outra qualquer. Medido em 2026-10-12 na bin do laboratório
(caso `03 CASOS/ATUALIZAR/O02 BIN COM VARIAS TIMELINES`, 92 sequências): a escolhida era a `O01_MARCADO` (placa B02),
e relinkar a `LAB_ANIMATTE` (B14 frente e fundo) deixaria os originais dela de fora, sem erro. Agora a sequência vai
pelo MobID — o do arrasto ou o do monitor Record, na forma da API — e um MobID que não está na bin é recusado.

Sem a pasta do caso, o teste diz que pulou e sai 0.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico")]
logging.disable(logging.WARNING)

from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
BIN = Path(raiz_das_amostras()) / "03 CASOS" / "ATUALIZAR" / "O02 BIN COM VARIAS TIMELINES" / "LAB 92 timelines.avb"
#: a LAB_ANIMATTE na forma do pyavb (urn) e na da API do MC (a do arrasto e do `GetViewerMobs`)
ANIMATTE_URN = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.0e4f90f3.aa007adb.df976917.9c2a9b9c"


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    if not BIN.is_file():
        print(f"  PULADO — {BIN} não está neste disco")
        return 0

    from avb_bin.masters import masters_de_arquivo
    from avb_bin.percurso import timeline
    from avb_export.reader import topen

    with topen(str(BIN)) as f:
        ok("a 'composição de mais trilhas' NÃO é a pedida (o defeito)", timeline(f).name, "O01_MARCADO")

    nomes = lambda ms: sorted({m.nome for m in ms})  # noqa: E731
    ok("sem MobID: os masters de OUTRA timeline (o comportamento antigo)",
       nomes(masters_de_arquivo(str(BIN))), ["B02_2398_MOV-PRORES.mov"])
    ok("⭐ com o MobID (urn do pyavb): os masters da LAB_ANIMATTE",
       nomes(masters_de_arquivo(str(BIN), mob_id=ANIMATTE_URN)), ["B14_FRENTE.mov", "B14_FUNDO.mov"])
    api = "060a2b340101010501010f1013-000000-0e4f90f3aa007adb-df9769179c2a-9b9c"
    ok("⭐ com o MobID na forma da API do MC (arrasto / Record): o mesmo",
       nomes(masters_de_arquivo(str(BIN), mob_id=api)), ["B14_FRENTE.mov", "B14_FUNDO.mov"])
    try:
        masters_de_arquivo(str(BIN), mob_id="0" * 64)
        recusou = False
    except ValueError:
        recusou = True
    ok("MobID que não está na bin: recusa (nunca outra timeline)", recusou, True)

    print("\n── depois de o MC salvar a bin de trabalho (AutoCopy) ──")
    salva = BIN.with_name("LAB 92 timelines - salva pelo MC (AutoCopy).avb")
    if salva.is_file():
        import relink_avb as R
        from avb_bin.segmentos import escolher_sequencia
        with topen(str(BIN)) as f:
            pedida = escolher_sequencia(f, mob_id=ANIMATTE_URN)
            assinatura = R._assinatura(pedida)
        with topen(str(salva)) as f:
            ok("o MC trocou o MobID: a pedida não está mais pelo id",
               escolher_sequencia(f, mob_id=ANIMATTE_URN) is None, True)
            achada = R._reencontrar(f, ANIMATTE_URN, assinatura)
            ok("⭐ reencontrada pela assinatura: a cópia AutoCopy dela", achada.name if achada else None,
               "LAB_ANIMATTE.AutoCopy.01")
            ok("assinatura que não casa com nada: None (o relink recusa)",
               R._reencontrar(f, ANIMATTE_URN, ("LAB_ANIMATTE", 99, 1)), None)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
