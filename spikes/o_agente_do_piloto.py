"""O agente do piloto no Media Composer de verdade (EDITOR NA TELA; freio F12).

  python spikes/o_agente_do_piloto.py estado
  python spikes/o_agente_do_piloto.py arrancar <projeto>          # abre o MC até a Select Project
  python spikes/o_agente_do_piloto.py duplicar <projeto> <formato> # New Project com um nome que já existe: o aviso de verdade
  python spikes/o_agente_do_piloto.py abrir <projeto>             # a operação do produto, com o aviso na tela
  python spikes/o_agente_do_piloto.py pedir_sair                  # File > Exit, para a pergunta Leave/Cancel ficar na tela
  python spikes/o_agente_do_piloto.py salvar                      # a operação do produto, com a pergunta na tela
  python spikes/o_agente_do_piloto.py cancelar                    # fecha a pergunta pelo Cancel
  python spikes/o_agente_do_piloto.py fechar

Cada comando deixa uma foto e devolve o foco ao terminal.
"""
import json
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.stdout.reconfigure(encoding="utf-8")
p = RAIZ
while not (p / "piloto" / "piloto").is_dir():
    p = p.parent
sys.path.insert(0, str(p / "piloto"))

from piloto import maos as maos_familia  # noqa: E402

from cicloassist import janela as J  # noqa: E402
from cicloassist.avid import abrir as A  # noqa: E402
from cicloassist.avid import salvar as S  # noqa: E402
from cicloassist.avid import socorro as SC  # noqa: E402
from cicloassist.piloto import localizador as L  # noqa: E402
from cicloassist.piloto import maos, tela  # noqa: E402

FOTOS = Path(tempfile.gettempdir()) / "provas_agente_do_piloto"
FOTOS.mkdir(exist_ok=True)


def relato(a, b=None, c=""):
    print(f"   · {a} {c}", flush=True)


def foto(nome):
    f = tela.fotografar()
    (FOTOS / f"{nome}.jpg").write_bytes(tela.jpeg(f.img, 1600))
    print("foto:", FOTOS / f"{nome}.jpg", flush=True)


def estado():
    print(json.dumps({"janelas": [{"h": h, "titulo": t, "ret": r, "habilitada": J.habilitada(h), "popup": J.e_popup(h), "pequena": J.aviso(r)} for h, t, r in J.janelas(A.EXE)],
                      "projeto": A.projeto_aberto(), "modal": SC._modal()}, ensure_ascii=False, indent=1), flush=True)


def esperar_select(prazo=240):
    p = A._Piloto(relato)
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        maos.freio()
        if A._janela_com_titulo(A.SELECT_PROJECT) and not A._aviso_na_tela():
            return p
        if A._aviso_na_tela():
            try:
                A._aviso_resolvido(p)
            except (L.NaoAchei, A.McNaoAbre) as e:
                print("aviso ainda não:", e, flush=True)
            time.sleep(3)
        time.sleep(0.5)
    raise SystemExit("a Select Project não apareceu")


def arrancar():
    if not A.aberto():
        A._lancar()
    esperar_select()


def duplicar(projeto, formato):
    p = esperar_select()
    a = p.achar_varios({"aba_novo": "a aba New Project no alto (ao lado da aba Projects)"}, A._regiao_select_project())
    p.clicar_em(a["aba_novo"], "aba New Project", espera=0.6)
    A._novo_projeto(p, projeto, formato)
    time.sleep(2.0)
    print("passos:", p.passos, "US$", round(p.custo, 4), flush=True)


def sair_pergunta():
    p = A._Piloto(relato)
    p.no_menu("File", "Exit")
    time.sleep(1.5)


def cancelar():
    import subprocess
    from cicloassist.piloto import espaco
    from cicloassist.servico import aplicativo as _app
    exe = subprocess.run(["powershell", "-NoProfile", "-Command", "(Get-Process cicloassist -ErrorAction SilentlyContinue | Select-Object -First 1).Path"], capture_output=True, text=True).stdout.strip()
    if exe:
        _app.apresentar(exe)        # a janela do app sai da frente, como nas operações do produto
    with espaco.tela_livre():
        h = SC._olhar()
        a = L.localizar(tela.fotografar(), "o botão Cancel da pergunta 'Leave the application?'", regiao=h.dialogo or h.monitor)
        maos.clicar(h.hwnd, a.x, a.y)
        time.sleep(1.0)


def caminho_do_projeto():
    return str(A.pasta_de_projetos() / A.projeto_aberto())


cmd, args = sys.argv[1], sys.argv[2:]
try:
    if cmd == "estado":
        pass
    elif cmd == "arrancar":
        arrancar()
    elif cmd == "duplicar":
        duplicar(*args)
    elif cmd == "abrir":
        print(json.dumps(A.abrir(args[0], relatar=relato), ensure_ascii=False, indent=1), flush=True)
    elif cmd == "pedir_sair":
        sair_pergunta()
    elif cmd == "salvar":
        try:
            print(json.dumps(S.salvar_tudo(caminho_do_projeto(), relatar=relato), ensure_ascii=False, indent=1), flush=True)
        except S.SalvarFalhou as e:
            print("PAROU COM A FRASE:", e, flush=True)
    elif cmd == "cancelar":
        cancelar()
    elif cmd == "api":              # com um diálogo na tela: que frase a API muda devolve
        from cicloassist.avid.mcapi import McApiErro, MediaComposer
        t0 = time.monotonic()
        try:
            with MediaComposer() as m:
                print("info:", m.info(), flush=True)
        except McApiErro as e:
            print(f"ERRO em {time.monotonic() - t0:.1f} s:", e, flush=True)
    elif cmd == "passo":            # o que o executor faz antes de um passo que fala com o MC
        from types import SimpleNamespace
        from cicloassist.servico import fluxo as F
        t0 = time.monotonic()
        try:
            F._sem_dialogo_no_mc(SimpleNamespace(op="importar_masters_opatom", id="camera"))
            print(f"LIVRE em {time.monotonic() - t0:.1f} s", flush=True)
        except F.PlanoInvalido as e:
            print(f"PAROU em {time.monotonic() - t0:.1f} s:", e, flush=True)
    elif cmd == "fechar":
        print(json.dumps(A.fechar(relatar=relato), ensure_ascii=False, indent=1), flush=True)
    estado()
    foto(f"{time.strftime('%H%M%S')}_{cmd}")
finally:
    print("foco no terminal:", maos_familia.devolver_ao_terminal(), flush=True)
