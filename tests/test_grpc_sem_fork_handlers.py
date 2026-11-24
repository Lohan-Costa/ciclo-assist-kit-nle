"""⛔⛔ Os "fork handlers" do gRPC prendiam o processo inteiro ~62 s a cada subprocesso (revisão de 2026-11-07).

MEDIDO: com canais de gRPC abrindo e fechando (o `mcapi` abre um por chamada) e um subprocesso aberto ao mesmo tempo
(ffmpeg, ffprobe, `claude -p`, o app), o fork esperava as threads do gRPC SEGURANDO O GIL — o processo inteiro parado,
a porta muda, e o supervisor do app matava o motor ("parou de responder… o processo continua vivo"). Eram os
travamentos do Conformar de 06–07/11 (e o retrato do `pilhas.txt` de 24/10: uma thread em `_fork_exec`, a CPU parada);
desde a fase 4 todo o gRPC com o MC passa pelo Assist, e era ele que ficava exposto. 3 de 3 travaram; com
`GRPC_ENABLE_FORK_SUPPORT=0`, 0 de 3 em 40 mil forks.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import textwrap
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

#: Os arquivos que importam o gRPC nos módulos: cada um desliga os handlers ANTES do import.
DOS_MODULOS = [
    RAIZ / "modulos/conformar/plugins/media-composer/servico/avid/mcapi.py",
    RAIZ / "modulos/conformar/plugins/media-composer/servico/avid/canal_do_nucleo.py",
    RAIZ / "modulos/sincronizar/motor/avid/mcapi.py",
    RAIZ / "modulos/sincronizar/motor/avid/canal_do_nucleo.py",
]


def _ambiente_sem_a_variavel() -> dict:
    env = {k: v for k, v in os.environ.items() if k != "GRPC_ENABLE_FORK_SUPPORT"}
    env["GRPC_VERBOSITY"] = "ERROR"
    return env


def test_importar_o_cicloassist_desliga_os_fork_handlers():
    r = subprocess.run([sys.executable, "-c", "import cicloassist, os; print(os.environ['GRPC_ENABLE_FORK_SUPPORT'])"],
                       cwd=RAIZ, env=_ambiente_sem_a_variavel(), capture_output=True, text=True, timeout=60)
    assert r.stdout.strip() == "0", r.stderr


def test_os_modulos_desligam_antes_de_importar_o_grpc():
    for p in DOS_MODULOS:
        texto = p.read_text(encoding="utf-8")
        assert 'setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")' in texto, p
        primeiro_import = re.search(r"^[ \t]*import grpc\b", texto, re.M).start()  # o de código, não o da documentação
        assert texto.index('setdefault("GRPC_ENABLE_FORK_SUPPORT"') < primeiro_import, p


def test_subprocesso_com_canais_em_uso_nao_prende_o_processo():
    """O cenário medido, em 4 s: canais novos por chamada a um servidor local + subprocessos. Com os handlers ligados,
    um fork leva ~62 s; o prazo de 45 s do teste estoura e ele falha dizendo isso."""
    roteiro = textwrap.dedent("""
        import cicloassist  # o que desliga os handlers
        import subprocess, threading, time
        from concurrent import futures
        import grpc
        srv = grpc.server(futures.ThreadPoolExecutor(4))
        srv.add_generic_rpc_handlers([grpc.method_handlers_generic_handler("t.T", {
            "Eco": grpc.unary_unary_rpc_method_handler(lambda r, c: r, lambda b: b, lambda b: b)})])
        porta = srv.add_insecure_port("127.0.0.1:0"); srv.start()
        fim = time.monotonic() + 4
        pior = [0.0]
        def chamar():
            while time.monotonic() < fim:
                ch = grpc.insecure_channel(f"127.0.0.1:{porta}")
                ch.unary_unary("/t.T/Eco", request_serializer=lambda b: b, response_deserializer=lambda b: b)(b"x", timeout=5)
                ch.close()
        def forkar():
            while time.monotonic() < fim:
                a = time.monotonic(); subprocess.run([__import__("sys").executable, "-c", "pass"])
                pior[0] = max(pior[0], time.monotonic() - a)
        ts = [threading.Thread(target=chamar) for _ in range(3)] + [threading.Thread(target=forkar) for _ in range(2)]
        [t.start() for t in ts]; [t.join() for t in ts]
        print(round(pior[0], 2), flush=True)
        import os; os._exit(0)
    """)
    try:
        r = subprocess.run([sys.executable, "-c", roteiro], cwd=RAIZ, env=_ambiente_sem_a_variavel(),
                           capture_output=True, text=True, timeout=45)
    except subprocess.TimeoutExpired:
        raise AssertionError("um subprocesso prendeu o processo por mais de 40 s: os fork handlers do gRPC voltaram")
    assert r.returncode == 0, r.stderr[-2000:]
    assert float(r.stdout.strip().splitlines()[-1]) < 5, f"um fork levou {r.stdout.strip()} s"
