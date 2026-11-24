"""Roda um script com VIGIA: foto da tela a cada 60 s e parada no primeiro diálogo do processo vigiado (foto e sai,
sem clicar — regra do piloto). Uso: py vigiar.py <exe vigiado> <script.py> [args…]"""
import os
import subprocess
import sys
import time

from boot import S, olhos

exe, script, args = sys.argv[1], sys.argv[2], sys.argv[3:]
log = open(os.path.join(S, os.path.splitext(os.path.basename(script))[0] + ".log"), "w", encoding="utf-8")
env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
proc = subprocess.Popen([sys.executable, script, *args], stdout=log, stderr=subprocess.STDOUT, env=env)
inicio = proxima_foto = time.time()
while proc.poll() is None:
    janelas = olhos.janelas(exe)
    dialogos = [j for j in janelas if j.get("tem_dono") or j["titulo"] in ("Message", "Warning", "Error")]
    if dialogos:
        print(f"[{int(time.time() - inicio)} s] DIÁLOGO: {[d['titulo'] for d in dialogos]} — foto:",
              olhos.foto_da_tela(S, "dialogo"), flush=True)
        sys.exit(2)
    if time.time() >= proxima_foto:
        principal = next((j for j in janelas if not j.get("tem_dono")), None)
        if principal:
            from boot import maos
            maos.frente(principal["hwnd"])          # a foto é do programa vigiado, não do terminal
            time.sleep(0.5)
        print(f"[{int(time.time() - inicio)} s] foto:", olhos.foto_da_tela(S, "vigia"), flush=True)
        proxima_foto += 60
    time.sleep(2)
print(f"[{int(time.time() - inicio)} s] fim, código {proc.returncode} — foto:", olhos.foto_da_tela(S, "fim"))
