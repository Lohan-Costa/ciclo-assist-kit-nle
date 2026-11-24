"""Duas correções trazidas do fork Assist anterior/Órbita, travadas por regressão.

Fonte: `_ASSIST ANTERIOR`, commits `34b798b` ("Source File" absoluto escapava do
"Source Path" — e o `.exists()` sobre o caminho resultante ABRE SESSÃO SMB no
Windows, para um host que um `.avb`/AAF de TERCEIRO escolhe) e `be71bfa`
(`LoadMobsIntoViewer` → `GetViewerMobs`/`CloseBin` colados DERRUBA o Media
Composer — medido pelo Ciclo Assist em 2026-09-13, 5 de 5 quedas). Portado
para este app em 2026-09-24. Não fala com Media Composer nenhum.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
# o serviço põe o motor no caminho ao subir (`main.py`); o `mcapi` importa `media.safepath`
sys.path.insert(0, str(RAIZ / "motor"))

import avid.mcapi as M  # noqa: E402
from avid.mcapi import MediaComposer  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo: str, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<58} -> {obtido}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    print("── 'Source File' absoluto/UNC não escapa do 'Source Path' ───")
    mc = MediaComposer()
    tocados: list[str] = []
    exists_real = Path.exists

    def exists_espiao(self):  # noqa: ANN001
        tocados.append(str(self))
        return False

    Path.exists = exists_espiao  # type: ignore[method-assign]
    try:
        mc.arquivo_do_master("mob", colunas={
            "Source Path": r"D:\projeto\CAM A",
            "Source File": r"\\atacante\share\x.mov",
            "Name": "clipe",
        })
        ok("o UNC do atacante nunca é TOCADO (.exists)",
           any("atacante" in t for t in tocados), False)
        ok("o caminho testado usa só o NOME do Source File",
           tocados[-1], str(Path(r"D:\projeto\CAM A") / "x.mov"))

        tocados.clear()
        mc.arquivo_do_master("mob", colunas={
            "Source Path": "/Volumes/INGEST/CAM",
            "Source File": "/etc/passwd",
            "Name": "clipe2",
        })
        ok("mesmo padrão para 'Source File' como caminho POSIX absoluto",
           tocados[-1], str(Path("/Volumes/INGEST/CAM") / "passwd"))

        tocados.clear()
        mc.arquivo_do_master("mob", colunas={
            "Source Path": r"D:\projeto\CAM A",
            "Source File": "20240531_PANA2774.mov",
            "Name": "clipe3",
        })
        ok("'Source File' normal (só nome) continua funcionando",
           tocados[-1], str(Path(r"D:\projeto\CAM A") / "20240531_PANA2774.mov"))
    finally:
        Path.exists = exists_real

    print("\n── bins(): a lixeira fica de fora por padrão ─────────────────")

    class _Resp:
        def __init__(self, caminho: str) -> None:
            self.body = type("B", (), {"absolute_path": caminho})()

    caminhos = [
        r"D:\projeto\CAM A.avb",
        r"D:\projeto\Trash\CAM A.avb",
        r"D:\projeto\Trash\SYNC\D01.avb",
    ]
    mc2 = MediaComposer()
    mc2._fluxo = lambda metodo, **kw: [_Resp(c) for c in caminhos]  # type: ignore[method-assign]
    mc2._projeto = {"path": r"D:\projeto"}
    ok("só a bin viva sobra por padrão", mc2.bins(), [r"D:\projeto\CAM A.avb"])
    ok("incluir_lixeira=True devolve tudo", len(mc2.bins(incluir_lixeira=True)), 3)

    print("\n── a guarda de 3s entre carregar e consultar/fechar o monitor ─")

    class _Relogio:
        def __init__(self) -> None:
            self.agora = 1000.0
            self.dormiu: list[float] = []

        def monotonic(self) -> float:
            return self.agora

        def sleep(self, s: float) -> None:
            self.dormiu.append(round(s, 2))
            self.agora += s

    class _CanalFalso:
        def unary_unary(self, *_a, **_kw):
            return lambda _req, timeout=None: object()

    relogio = _Relogio()
    monotonic_real, sleep_real = time.monotonic, time.sleep
    time.monotonic, time.sleep = relogio.monotonic, relogio.sleep
    M._carregou_em = None
    try:
        mc3 = MediaComposer()
        mc3._canal = _CanalFalso()  # type: ignore[assignment]

        mc3._chamar("LoadMobsIntoViewer")
        relogio.agora += 0.5
        mc3._chamar("GetViewerMobs")
        ok("espera o que falta para completar 3s", relogio.dormiu, [2.5])

        relogio.dormiu.clear()
        relogio.agora += 10
        mc3._chamar("CloseBin")
        ok("depois de assentado não espera mais nada", relogio.dormiu, [])

        relogio.dormiu.clear()
        M._carregou_em = None
        mc3._chamar("CloseBin")
        ok("sem carregar antes, ninguém espera", relogio.dormiu, [])

        relogio.dormiu.clear()
        mc3._chamar("LoadMobsIntoViewer")
        mc3._chamar("GetOpenProjectInfo")
        ok("consulta que não mexe no monitor não espera", relogio.dormiu, [])
    finally:
        time.monotonic, time.sleep = monotonic_real, sleep_real
        M._carregou_em = None

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
