"""Exporta pelo List Tool a sequência que está no Record — PILOTO (Mac, MC 25.12, List Tool aberto na posição medida em
2026-11-25: janela em x 286–1303). Rodar com o Python do PILOTO, da pasta `piloto/`, com o MC já na frente:

    .venv/bin/python <este> <pasta de fotos> "MC S6 CMX3600" "<pasta de saída>"       # SEM_LOAD=1: não clica Load

Input › Load → Preview → Save List › To one file → digita o nome (a pasta o diálogo lembra; a 1ª vez: Cmd+Shift+G) →
Salvar. ⛔ O formato (Output Format) e as TRILHAS marcadas (Input › Tracks) NÃO são mexidos aqui: o List Tool lembra
as trilhas da sequência anterior e o botão alterna — conferir a foto `a_load` e marcar à mão antes (banco
`protocolos/edl/README.md` §5b).
"""
import sys, os, time, subprocess
sys.path.insert(0, ".")
from piloto import maos
S, nome, pasta = sys.argv[1], sys.argv[2], sys.argv[3]
tag = nome.replace(" ", "_")
def front():
    f = subprocess.run(["lsappinfo","front"],capture_output=True,text=True).stdout.strip()
    return subprocess.run(["lsappinfo","info","-only","name",f],capture_output=True,text=True).stdout
def foto(n, r=None):
    subprocess.run(["screencapture","-x"] + (["-R", r] if r else []) + [f"{S}/{tag}_{n}.png"])
def ok(): assert "Avid" in front(), front()
alvo = os.path.join(pasta, nome + ".edl")
assert not os.path.exists(alvo), "já existe: " + alvo
try:
    if not os.environ.get("SEM_LOAD"):
        ok(); maos.clicar(324, 229); time.sleep(0.8)
        ok(); maos.clicar(627, 279); time.sleep(2.5)
    foto("a_load", "290,90,1020,600")
    ok(); maos.clicar(890, 128); time.sleep(3.0); foto("b_preview", "680,140,620,530")
    ok(); maos.clicar(997, 129); time.sleep(1.0)
    ok(); maos.clicar(977, 156); time.sleep(2.5); foto("c_dialogo", "560,160,800,450")
    ok(); maos.digitar(nome); time.sleep(0.8); foto("d_nome", "560,160,800,450")
    ok(); maos.clicar(1299, 580); time.sleep(2.5)
finally:
    print("terminal:", maos.devolver_ao_terminal())
print("salvo:", os.path.exists(alvo), alvo)
