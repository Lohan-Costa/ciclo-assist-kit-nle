"""O vigia do Media Composer (`servico/main.py`): quando o serviço pode encerrar sozinho.

Rodar:

    PYTHONPATH="motor;plugins/media-composer/servico" .venv-win/Scripts/python tests/test_vigia.py

## Por que este teste existe

Medido em 2026-09-28: o autor testava o Avid e o Resolve na MESMA máquina, fechou o Avid, e
60 s depois o serviço saiu no meio de um "Atualizar timeline" no Resolve. O painel do Resolve
ficou em "serviço fora do ar" / "Failed to fetch". O vigia só olhava o Media Composer e o
trabalho do lado do Avid. Agora o painel do Resolve falando (`ultimo_uso_receptor`, a cada 4 s)
também conta como uso.
"""

from __future__ import annotations

import sys
import threading
import time
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import main as servico_main  # noqa: E402
import plataforma  # noqa: E402


def rodar(mc_abre_e_fecha: bool, receptor_falando: bool, ocupada: bool = False) -> bool:
    """Roda o vigia em escala de tempo curta. Devolve True se ele ENCERROU o serviço."""
    vistas = iter([True] if mc_abre_e_fecha else [])
    plataforma.media_composer_aberto = lambda: next(vistas, False)
    servico = types.SimpleNamespace(sessao=types.SimpleNamespace(ocupada=ocupada))
    parar = threading.Event()
    fim = time.monotonic() + 0.6
    t = threading.Thread(target=servico_main.vigiar_media_composer,
                         args=(servico, parar, 0.15, 0.01), daemon=True)
    t.start()
    while time.monotonic() < fim and not parar.is_set():
        if receptor_falando:
            servico.ultimo_uso_receptor = time.monotonic()
        time.sleep(0.02)
    encerrou = parar.is_set()
    parar.set()
    t.join(1)
    return encerrou


def rodar_app(matar: bool, ocupada: bool = False, importando: bool = False) -> bool:
    """A vigia do APLICATIVO (`--pai`) contra um processo de verdade no papel do app. True se encerrou.
    (2026-10-04, Windows: o app saiu e o motor ficou órfão, com o painel "conectado".)"""
    import subprocess
    app = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    try:
        servico = types.SimpleNamespace(
            sessao=types.SimpleNamespace(ocupada=ocupada),
            receber=types.SimpleNamespace(progresso=lambda: {"ativo": importando}))
        parar = threading.Event()
        t = threading.Thread(target=servico_main.vigiar_app, args=(servico, parar, app.pid, 0.05),
                             daemon=True)
        t.start()
        time.sleep(0.2)
        if matar:
            app.kill()
            app.wait()
        fim = time.monotonic() + 1.5
        while time.monotonic() < fim and not parar.is_set():
            time.sleep(0.02)
        encerrou = parar.is_set()
        parar.set()
        t.join(1)
        return encerrou
    finally:
        if app.poll() is None:
            app.kill()
            app.wait()


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def checa(cond: bool, rotulo: str) -> None:
        nonlocal casos
        casos += 1
        print(("  ok   " if cond else "  FALHA ") + rotulo)
        if not cond:
            falhas.append(rotulo)

    checa(rodar(True, False), "o Media Composer fechou e ninguém mais usa: encerra depois da carência")
    checa(not rodar(True, True),
          "⭐ o Media Composer fechou, mas o painel do Resolve está falando: o serviço FICA")
    checa(not rodar(True, False, ocupada=True), "trabalho em curso do lado do Avid: o serviço fica")
    checa(not rodar(False, False), "o Media Composer nunca abriu: não é 'fechou', o serviço fica")

    checa(not rodar_app(matar=False), "o aplicativo aberto: o serviço fica")
    checa(rodar_app(matar=True), "⭐ o aplicativo saiu (por qualquer caminho): o serviço encerra")
    checa(not rodar_app(matar=True, importando=True),
          "o aplicativo saiu no meio de um Importar: o serviço espera o trabalho terminar")
    checa(not rodar_app(matar=True, ocupada=True), "…e no meio de um relink do Avid também")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
