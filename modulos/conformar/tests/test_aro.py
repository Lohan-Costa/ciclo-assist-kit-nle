"""O parser do canal ARO (`servico/aro.py`) — sem Media Composer.

O ARO é o 2º caminho da seleção (o 1º é o Cmd+C de `coleta`): a dylib lê a seleção por dentro e
responde por um socket. Aqui trocamos o socket por respostas de mentira e conferimos que
`ler_selecao` monta o `{mob_id, masters, clipes, erro}` certo. Banco:
`plugins/avid-panel-sdk/arrastar.md` §"IDENTIDADE RESOLVIDA".

Rodar:  .venv/bin/python tests/test_aro.py
"""
from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import aro  # noqa: E402
from avb.mobid import MobID  # noqa: E402

# a dylib entrega o MobID CRU (ordem interna = bytes_le); o parser converte p/ URN externa com o pyavb
M1 = "060a2b340101010101010f0013000000" + "97a79e0e5ccede18f70f40dad8c0d110"
M2 = "060a2b340101010101010f0013000000" + "1f91962f3a61d05b1e3d95b7a6c4910c"
SEQ = "060a2b340101010101010f0013000000" + "deadbeefdeadbeefdeadbeefdeadbeef"
U1 = str(MobID(bytes_le=bytes.fromhex(M1)))
U2 = str(MobID(bytes_le=bytes.fromhex(M2)))
USEQ = str(MobID(bytes_le=bytes.fromhex(SEQ)))


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

    def com(resp):
        aro._comando = lambda *a, **k: resp  # troca o socket por uma resposta de mentira

    # 1) seleção normal: SEQ + dois MOBs, sem repetição
    com(f"SEQ {SEQ}\nMOB {M1}\nMOB {M2}\nMOB {M1}\nCOUNT 3\nEND\n")
    sel = aro.ler_selecao()
    ok("mob_id da sequência (convertido p/ URN)", sel["mob_id"], USEQ)
    ok("masters em URN, sem repetição", sel["masters"], [U1, U2])
    ok("clipes = nº de segmentos selecionados (com master)", sel["clipes"], 3)
    ok("sem erro", sel["erro"], None)

    # 2) nada selecionado: sem MOB, só COUNT 0
    com("COUNT 0\nEND\n")
    sel = aro.ler_selecao()
    ok("nada selecionado: masters vazio", sel["masters"], [])
    ok("nada selecionado: sem erro (seleção vazia é válida)", sel["erro"], None)

    # 3) sem timeline: ERR vira `erro`
    com("ERR timeline\nEND\n")
    sel = aro.ler_selecao()
    ok("ERR timeline -> erro preenchido", sel["erro"], "timeline")
    ok("ERR timeline -> sem masters", sel["masters"], [])

    # 4) canal fora do ar: _comando devolve None -> ler_selecao devolve None (cai no Caminho A)
    com(None)
    ok("canal fora do ar -> None", aro.ler_selecao(), None)

    # 5) disponivel() lê o PONG
    aro._comando = lambda cmd, *a, **k: "PONG main=1 slide=0x0 classes=47\nEND\n" if cmd == "PING" else None
    ok("disponivel() com PONG", aro.disponivel(), True)
    aro._comando = lambda *a, **k: None
    ok("disponivel() sem resposta", aro.disponivel(), False)

    # 6) a rota com o MC FECHADO diz isso — não "dylib não instalada?" (revisão 2026-10-28)
    import plataforma
    from api import rotas
    original = plataforma.media_composer_aberto
    try:
        plataforma.media_composer_aberto = lambda: False
        aro._comando = lambda *a, **k: (_ for _ in ()).throw(AssertionError("não devia chamar o ARO"))
        _, r = rotas.mc_selecao_aro(None)
        ok("MC fechado -> mc_fechado", r.get("mc_fechado"), True)
        ok("MC fechado -> a mensagem diz que o MC está fechado", "Media Composer está fechado" in r["erro"], True)
        plataforma.media_composer_aberto = lambda: True
        aro._comando = lambda *a, **k: None
        _, r = rotas.mc_selecao_aro(None)
        ok("MC aberto sem o canal -> a mensagem da dylib", "dylib" in r["erro"], True)
    finally:
        plataforma.media_composer_aberto = original

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
