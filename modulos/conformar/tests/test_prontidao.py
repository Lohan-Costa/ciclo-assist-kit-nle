"""O painel só trabalha com o motor PRONTO; o app é o dono do motor em todo NLE (autor, 2026-10-04).

Rodar:

    .venv/bin/python tests/test_prontidao.py        (Windows: .venv-win/Scripts/python)

O incidente que isto trava: o editor fez o Importar inteiro do PRODUCAO_B pelo painel do Resolve e só
no FIM viu a timeline toda offline — o motor, subido pela casca com o PATH mínimo de `.app`, estava
sem ffprobe. Três camadas:

  1. `/prontidao`: ffprobe e ffmpeg RODAM, a pasta grava; o painel esconde as opções até `ok`;
  2. a trava antes de montar: metade das mídias sem TC/duração = o motor, e nada é importado;
  3. a casca do Resolve não sobe mais motor nenhum: espera o APP (a ordem não importa).
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

import prontidao  # noqa: E402
from media import fftools  # noqa: E402
from sessao_receber import travar_se_o_motor_nao_le  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    print("── 1. prontidão ──")
    with mock.patch.object(fftools, "ffprobe", lambda: None), \
            mock.patch.object(fftools, "ffmpeg", lambda: "/nao/existe/ffmpeg"):
        r = prontidao.conferir(forcar=True)
    por = {i["id"]: i for i in r["itens"]}
    ok("⛔ sem ffprobe (o incidente): NÃO pronto", (r["ok"], por["ffprobe"]["ok"]), (False, False))
    ok("…e o item diz o que é e o GESTO que resolve",
       ("ffprobe" in por["ffprobe"]["erro"], "aplicativo" in por["ffprobe"]["gesto"]), (True, True))
    ok("ffmpeg que não roda também não passa (confere que FUNCIONA, não que existe)",
       por["ffmpeg"]["ok"], False)
    real = prontidao.conferir(forcar=True)
    if all(i["ok"] for i in real["itens"] if i["id"] != "pasta"):
        ok("nesta bancada, com ffprobe e ffmpeg, pronto", real["ok"], True)
    else:
        print("  (sem ffmpeg nesta máquina — o caso positivo fica de fora)")
    ok("o resultado fica guardado (a batida de 4 s não roda ffprobe toda vez)",
       prontidao.conferir() is prontidao.conferir(), True)

    print("── 1b. o motor é o do APLICATIVO ──")

    class Servico:
        def __init__(self, app=None, bancada=False, ocupada=False):
            import threading
            self.app_exe, self.bancada, self.parar = app, bancada, threading.Event()
            self.sessao = type("S", (), {"ocupada": ocupada})()

    def item_app(s):
        return next(i for i in prontidao.conferir(s, forcar=True)["itens"] if i["id"] == "aplicativo")
    ok("⛔ motor órfão (casca antiga o subiu): NÃO pronto, e o gesto é abrir o app",
       (item_app(Servico())["ok"], "Abra o aplicativo" in item_app(Servico())["gesto"]), (False, True))
    ok("motor do app: pronto", item_app(Servico(app="/x/delapraca"))["ok"], True)
    ok("motor da bancada (dev.sh/dev.ps1 --bancada): pronto", item_app(Servico(bancada=True))["ok"], True)

    from api import rotas
    ctx = lambda s: type("C", (), {"servico": s, "query": ""})()          # noqa: E731
    orfao = Servico()
    ok("o órfão CEDE a porta quando o app pede", rotas.motor_ceder(ctx(orfao))[0], 200)
    import time as _t
    _t.sleep(0.5)
    ok("…e encerra de fato (o evento de parar)", orfao.parar.is_set(), True)
    ok("⛔ o motor de OUTRO app não cede", rotas.motor_ceder(ctx(Servico(app="/x/delapraca")))[0], 409)
    ok("⛔ nem o órfão no meio de um trabalho", rotas.motor_ceder(ctx(Servico(ocupada=True)))[0], 409)

    print("── 2. a trava antes de montar ──")
    bom, ruim = (100, 24.0, "01:00:00:00"), (None, None, None)
    travou = lambda lidos: _travou(lidos)                     # noqa: E731
    ok("arquivo quebrado aqui e ali: segue (2 de 7)", travou([("a", bom)] * 5 + [("b", ruim)] * 2), None)
    ok("menos de 3 falhas nunca trava (timeline pequena)", travou([("b", ruim)] * 2), None)
    with mock.patch.object(fftools, "ffprobe", lambda: None):
        msg = travou([("a", bom)] * 3 + [("b", ruim)] * 3)
    ok("⛔ metade sem TC/duração E o motor sem ffprobe (o incidente): NADA é importado",
       bool(msg) and "Nada foi importado" in msg and "ffprobe" in msg, True)
    ok("…mas com o motor PRONTO, formato que o ffprobe não lê (BRAW, R3D, ARRIRAW) segue",
       travou([("braw", ruim)] * 6), None)

    print("── 3. o painel nasce bloqueado ──")
    # ⭐ Fase 4 do plano um app só (2026-11-07): a casca do Resolve saiu; ficam as conferências do painel.
    js = (RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.js").read_text(encoding="utf-8")
    html = (RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.html").read_text(encoding="utf-8")
    ok("o painel nasce bloqueado e libera pela /prontidao",
       ("bloquear(true);" in js, 'api("/prontidao"' in js, 'id="prontidao"' in html), (True, True, True))
    ok("⛔ o painel não pede mais à casca para subir o motor", "ponte().religar()" in js, False)
    ok("⛔ a área de espera NÃO é `section` (o painel esconde toda section fora da aba ativa: a tela "
       "ficava vazia — autor, 2026-10-04)", '<div id="prontidao"' in html, True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


def _travou(lidos):
    try:
        travar_se_o_motor_nao_le(lidos)
    except RuntimeError as e:
        return str(e)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
