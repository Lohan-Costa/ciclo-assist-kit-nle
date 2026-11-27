"""Exporta a EDL de uma sequência do Premiere 26.0.2 Mac PILOTANDO (não há EDL por script — banco protocolos/edl §1).

    python3 spikes/edl_som_premiere/exportar_edl.py "<sequência>" "<nome do arquivo sem .edl>"

A sequência vira a ativa pela ponte; Arquivo › Exportar › EDL… pelo NOME (System Events); o diálogo de configurações
como ESTÁ (as caixas e o mapa de áudio ficam lembrados entre exportações) → OK; o salvar do Mac abre na pasta do projeto
com o nome-base selecionado → digita o nome → Salvar. Fotos de cada passo em `fotos/` da pasta da rodada. Pontos medidos
em 2026-11-25 (monitor 1920×1080): OK (1163, 779), Salvar (1684, 704) — conferidos pela foto antes de confiar de novo.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))
import ponte  # noqa: E402

PILOTO = ponte.FAMILIA / "piloto"
sys.path.insert(0, str(PILOTO))
from piloto import maos  # noqa: E402

FOTOS = ponte.PASTA / "fotos"


def frente() -> str:
    f = subprocess.run(["lsappinfo", "front"], capture_output=True, text=True).stdout.strip()
    return subprocess.run(["lsappinfo", "info", "-only", "name", f], capture_output=True, text=True).stdout


def main(seq: str, nome: str) -> int:
    FOTOS.mkdir(exist_ok=True)
    alvo = ponte.PASTA / f"{nome}.edl"
    if alvo.exists():
        raise SystemExit(f"já existe: {alvo}")
    r = ponte.js('(function(n){for(var i=0;i<app.project.sequences.numSequences;i++){var q=app.project.sequences[i];'
                 'if(q.name==n){app.project.openSequence(q.sequenceID);return app.project.activeSequence.name;}}'
                 'return "";})(%s)' % json.dumps(seq))
    if r != seq:
        raise SystemExit(f"sequência não achada: {seq!r} → {r!r}")
    pid = subprocess.run(["pgrep", "-f", "MacOS/Adobe Premiere Pro 2026$"], capture_output=True, text=True).stdout.split()[0]
    se = f'tell application "System Events" to tell (first process whose unix id is {pid})'
    subprocess.run(["osascript", "-e", f'tell application "System Events" to set frontmost of (first process whose unix id is {pid}) to true'])
    time.sleep(1.5)
    subprocess.run(["osascript", "-e", f'{se} to click menu item "EDL…" of menu 1 of menu item "Exportar" of menu "Arquivo" of menu bar 1'],
                   capture_output=True)
    time.sleep(2.5)
    tag = nome.replace(" ", "_")
    foto = lambda n, r=None: subprocess.run(["screencapture", "-x"] + (["-R", r] if r else []) + [str(FOTOS / f"{tag}_{n}.png")])
    try:
        assert "Premiere" in frente(), frente()
        foto("1_dialogo", "700,230,520,600")
        maos.clicar(1163, 779); time.sleep(2.5)
        assert "Premiere" in frente(), frente()
        foto("2_salvar", "840,120,1000,640")
        maos.digitar(nome); time.sleep(0.8)
        foto("3_nome", "840,150,400,40")
        maos.clicar(1684, 704); time.sleep(2.5)
    finally:
        print("terminal:", maos.devolver_ao_terminal())
    print("salvo:", alvo.exists(), alvo.name)
    return 0 if alvo.exists() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
