"""O núcleo: a ponte única do Premiere para os outros módulos (fase 4 do plano um app só, 2026-11-07)."""
import json
import os
import stat
import sys

from cicloassist.nle import premiere as P
from cicloassist.servico import nucleo, rotas
from cicloassist.servico.http import Pedido


def _pedido(corpo, token=True):
    cab = {"content-type": "application/json"}
    if token:
        cab[nucleo.HEADER.lower()] = nucleo.token()
    return Pedido("POST", "/nucleo/premiere/chamar", cab, json.dumps(corpo).encode(), {})


def test_sem_o_token_nada_passa():
    r = rotas.rota_nucleo_chamar(_pedido({"modulo": "sincronizar", "funcao": "sincAppVersion"}, token=False))
    assert r.status == 401


def test_cada_modulo_so_chama_o_proprio_prefixo(monkeypatch):
    chamadas = []
    monkeypatch.setattr(rotas._ponte, "chamar_cru", lambda f, *a, prazo: chamadas.append((f, a)) or "26.0.2")
    r = rotas.rota_nucleo_chamar(_pedido({"modulo": "sincronizar", "funcao": "sincAppVersion", "args": [1, "x"]}))
    assert r.status == 200 and json.loads(r.corpo) == {"ok": True, "r": "26.0.2"}
    assert chamadas == [("sincAppVersion", (1, "x"))]
    for modulo, funcao in (("sincronizar", "cicloProjeto"), ("sincronizar", "dlpcLer"), ("conformar", "sincX"),
                           ("assistir", "cicloX"), ("sincronizar", "sinc"), ("sincronizar", "sinc_x")):
        assert rotas.rota_nucleo_chamar(_pedido({"modulo": modulo, "funcao": funcao})).status == 403, funcao
    assert len(chamadas) == 1


def test_premiere_fechado_vira_409(monkeypatch):
    def fechado(*a, **k):
        raise rotas._ponte.PremiereIndisponivel("fechado")
    monkeypatch.setattr(rotas._ponte, "chamar_cru", fechado)
    assert rotas.rota_nucleo_chamar(_pedido({"modulo": "conformar", "funcao": "dlpcLer"})).status == 409


def test_o_token_e_publicado_so_para_o_usuario(tmp_path):
    p = nucleo.publicar(tmp_path)
    assert p.read_text(encoding="utf-8") == nucleo.token()
    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(p).st_mode) == 0o600


def test_a_ponte_carrega_o_extendscript_dos_tres_modulos():
    b = P.host_jsx_inteiro()
    assert b"function sincAppVersion" in b and b"function dlpc" in b and b"function ciclo" in b
