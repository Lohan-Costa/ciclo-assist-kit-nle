"""Cria e confere as venvs dos módulos (Sincronizar e Conformar) — chamado por `instalar.ps1` e `dev.ps1`.

⛔ A venv da raiz não serve a eles (falta `scipy`, `zstandard`, `opencv`…), e o app só sobe a Preparar e o Conformar se
a venv DO MÓDULO executar (`app/src-tauri/src/lib.rs`). Sem este passo, numa máquina nova as duas abas ficavam fora do
ar (achado na fase 5, 2026-11-08). As venvs moram no SSD e são uma por sistema: `.venv-win` no Windows, `.venv` no Mac.

    python tools/preparar_modulos.py            # cria o que falta; instala se a lista de pacotes mudou
    python tools/preparar_modulos.py --limpo    # refaz as duas do zero

⭐ FUNCIONA, não EXISTE: num disco que atravessa máquinas o python do outro sistema está lá e está errado; só
executá-lo responde. ⚠️ Sem `--upgrade pip`: falha no Windows e deixa lixo (matriz de plataforma, seção H).
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]

#: módulo → a lista de pacotes com versões exatas, relativa à pasta dele.
MODULOS = {"sincronizar": "motor/requirements.txt", "conformar": "requirements.lock"}
CARIMBO = ".deps-instaladas"


class Falhou(Exception):
    """Uma frase que diz qual módulo não ficou pronto."""


def _rodar(cmd: list[str]) -> int:
    try:
        return subprocess.run(cmd, stdin=subprocess.DEVNULL).returncode
    except OSError:  # o executável do outro sistema: WinError 193 · Exec format error
        return 1


def pasta_da_venv(modulo: Path) -> Path:
    return modulo / (".venv-win" if sys.platform == "win32" else ".venv")


def python_da(venv: Path) -> Path:
    return venv / "Scripts" / "python.exe" if sys.platform == "win32" else venv / "bin" / "python"


def funciona(py: Path) -> bool:
    return py.is_file() and _rodar([str(py), "-c", "import sys"]) == 0


def precisa_instalar(venv: Path, lista: Path) -> bool:
    carimbo = venv / CARIMBO
    return not carimbo.is_file() or lista.stat().st_mtime > carimbo.stat().st_mtime


def preparar(modulo: Path, lista_relativa: str, limpo: bool = False) -> bool:
    """Deixa a venv do módulo pronta. Devolve se precisou mexer nela."""
    lista, venv = modulo / lista_relativa, pasta_da_venv(modulo)
    if not lista.is_file():
        raise Falhou(f"{modulo.name}: não achei a lista de pacotes {lista}")
    py = python_da(venv)
    nova = limpo or not funciona(py)
    if nova:
        if venv.exists():
            shutil.rmtree(venv)
        print(f"  {modulo.name}: criando {venv.name}", flush=True)
        if _rodar([sys.executable, "-m", "venv", "--copies", str(venv)]) != 0 or not funciona(py):
            raise Falhou(f"{modulo.name}: não consegui criar o ambiente em {venv}")
    if not (nova or precisa_instalar(venv, lista)):
        return False
    print(f"  {modulo.name}: instalando os pacotes (a primeira vez demora)", flush=True)
    if _rodar([str(py), "-m", "pip", "install", "--quiet", "--disable-pip-version-check", "-r", str(lista)]) != 0:
        raise Falhou(f"{modulo.name}: o pip falhou ao instalar {lista.name}")
    (venv / CARIMBO).touch()
    return True


def main(argv: list[str] | None = None) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--limpo", action="store_true", help="refaz as venvs do zero")
    args = ap.parse_args(argv)
    for nome, lista in MODULOS.items():
        try:
            mexeu = preparar(RAIZ / "modulos" / nome, lista, limpo=args.limpo)
        except Falhou as e:
            print(f"  ERRO — {e}", flush=True)
            return 1
        print(f"  {nome}: {'pronto' if mexeu else 'já estava pronto'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
