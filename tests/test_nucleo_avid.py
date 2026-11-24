"""Só o Assist fala com o Media Composer (fase 4 do plano um app só, passo 4, 2026-11-07).

O Sincronizar e o Conformar guardam em `MediaComposer._canal` um `CanalDoNucleo` (`avid/canal_do_nucleo.py`, o MESMO
arquivo nos dois) em vez de um canal gRPC: o pedido serializado vai a `POST /nucleo/avid/chamar`, e a chamada ao MC sai
daqui (`mcapi.chamar_cru`), com a pausa do monitor deste processo valendo para o app inteiro.
"""
import base64
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import grpc
import pytest

from cicloassist.avid import mcapi
from cicloassist.avid.proto import mcapi_tipos_pb2 as pb
from cicloassist.servico import nucleo, rotas
from cicloassist.servico.http import Pedido

RAIZ = Path(__file__).resolve().parent.parent
CANAIS = (RAIZ / "modulos/sincronizar/motor/avid/canal_do_nucleo.py",
          RAIZ / "modulos/conformar/plugins/media-composer/servico/avid/canal_do_nucleo.py")


def _pedido(corpo, token=True):
    cab = {"content-type": "application/json"}
    if token:
        cab[nucleo.HEADER.lower()] = nucleo.token()
    return Pedido("POST", "/nucleo/avid/chamar", cab, json.dumps(corpo).encode(), {})


def _corpo(rota="/mcapi.MCAPI/GetAppInfo", tipo="unario", modulo="sincronizar", pedido=b""):
    return {"modulo": modulo, "rota": rota, "tipo": tipo, "prazo": 5,
            "pedido": base64.b64encode(pedido).decode()}


@pytest.fixture
def canal_mod(monkeypatch, tmp_path):
    """O `canal_do_nucleo` do Sincronizar, com o HTTP levado direto à rota (sem rede) e o token publicado."""
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path))
    nucleo.publicar(tmp_path)
    spec = importlib.util.spec_from_file_location("canal_do_nucleo_teste", CANAIS[0])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    def urlopen(req, timeout=None):
        cab = {k.lower(): v for k, v in req.header_items()}
        r = rotas.rota_nucleo_avid(Pedido("POST", "/nucleo/avid/chamar", cab, req.data, {}))
        if r.status >= 400:
            raise urllib.error.HTTPError(req.full_url, r.status, "x", {}, io.BytesIO(r.corpo))
        return io.BytesIO(r.corpo)

    monkeypatch.setattr(mod.urllib.request, "urlopen", urlopen)
    return mod


def test_o_canal_e_o_mesmo_arquivo_nos_dois_modulos():
    assert CANAIS[0].read_bytes() == CANAIS[1].read_bytes(), "mudou um canal_do_nucleo.py, copie no outro"


def test_sem_o_token_nada_passa():
    assert rotas.rota_nucleo_avid(_pedido(_corpo(), token=False)).status == 401


def test_so_os_modulos_e_so_rotas_do_mc(monkeypatch):
    monkeypatch.setattr(mcapi, "chamar_cru", lambda *a, **k: pytest.fail("não podia chegar ao MC"))
    assert rotas.rota_nucleo_avid(_pedido(_corpo(modulo="assistir"))).status == 403
    monkeypatch.undo()
    for rota, tipo in (("/outro.Servico/GetAppInfo", "unario"), ("/mcapi.MCAPI/../x", "unario"),
                       ("/mcapi.MCAPI/NaoExiste", "unario"), ("/mcapi.MCAPI/GetAppInfo", "bidi"),
                       ("/mcapi.MCAPI/GetAppInfo", "reflexao")):
        assert rotas.rota_nucleo_avid(_pedido(_corpo(rota, tipo))).status == 400, (rota, tipo)


def test_ida_e_volta_pelo_canal(canal_mod, monkeypatch):
    vistos = []

    def chamar_cru(rota, pedido, tipo, prazo):
        vistos.append((rota, tipo, pb.GetAppInfoRequest.FromString(pedido).HasField("header")))
        r = pb.GetAppInfoResponse()
        r.body.app_name, r.body.app_version = "Media Composer", "2025.12"
        return [r.SerializeToString()]

    monkeypatch.setattr(mcapi, "chamar_cru", chamar_cru)
    canal = canal_mod.CanalDoNucleo("sincronizar")
    stub = canal.unary_unary("/mcapi.MCAPI/GetAppInfo", pb.GetAppInfoRequest.SerializeToString,
                             pb.GetAppInfoResponse.FromString)
    req = pb.GetAppInfoRequest()
    req.header.SetInParent()
    r = stub(req, timeout=3.0)
    assert (r.body.app_name, r.body.app_version) == ("Media Composer", "2025.12")
    assert vistos == [("/mcapi.MCAPI/GetAppInfo", "unario", True)]


def test_o_erro_do_mc_volta_com_o_codigo(canal_mod, monkeypatch):
    class Fechado(grpc.RpcError):
        def code(self):
            return grpc.StatusCode.UNAVAILABLE

        def details(self):
            return "connection refused"

    def chamar_cru(*a, **k):
        raise Fechado()

    monkeypatch.setattr(mcapi, "chamar_cru", chamar_cru)
    stub = canal_mod.CanalDoNucleo("conformar").unary_unary(
        "/mcapi.MCAPI/GetAppInfo", pb.GetAppInfoRequest.SerializeToString, pb.GetAppInfoResponse.FromString)
    with pytest.raises(grpc.RpcError) as e:
        stub(pb.GetAppInfoRequest())
    assert e.value.code() == grpc.StatusCode.UNAVAILABLE and e.value.frase == ""


def test_sem_o_assist_a_frase_diz_quem_falta(canal_mod, monkeypatch):
    def recusado(*a, **k):
        raise urllib.error.URLError(ConnectionRefusedError(61, "refused"))

    monkeypatch.setattr(canal_mod.urllib.request, "urlopen", recusado)
    stub = canal_mod.CanalDoNucleo("sincronizar").unary_unary(
        "/mcapi.MCAPI/GetAppInfo", pb.GetAppInfoRequest.SerializeToString, pb.GetAppInfoResponse.FromString)
    with pytest.raises(grpc.RpcError) as e:
        stub(pb.GetAppInfoRequest())
    assert e.value.code() == grpc.StatusCode.UNAVAILABLE and e.value.frase == canal_mod.ASSIST_FORA


def test_token_velho_e_relido_e_repetido_uma_vez(canal_mod, monkeypatch, tmp_path):
    """⭐ Revisão de 2026-11-07: o Assist religado entre ler o token e enviar dava "recusou (401)" ao editor. O canal
    relê o `plugin-token` e repete UMA vez — e um segundo 401 continua sendo erro, nunca um laço."""
    respostas = []
    urlopen_de_verdade = canal_mod.urllib.request.urlopen

    arquivo = nucleo.caminho(tmp_path)
    arquivo.write_text("token-do-assist-anterior", encoding="utf-8")

    def urlopen(req, timeout=None):
        respostas.append(dict(req.header_items()).get("X-ciclo-token"))
        if len(respostas) == 1:
            nucleo.publicar(tmp_path)  # o Assist novo publica o dele; o pedido já tinha saído com o velho
        return urlopen_de_verdade(req, timeout)  # a rota de verdade: 401 para o velho

    monkeypatch.setattr(canal_mod.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(mcapi, "chamar_cru", lambda *a, **k: [pb.GetAppInfoResponse().SerializeToString()])
    stub = canal_mod.CanalDoNucleo("sincronizar").unary_unary(
        "/mcapi.MCAPI/GetAppInfo", pb.GetAppInfoRequest.SerializeToString, pb.GetAppInfoResponse.FromString)
    stub(pb.GetAppInfoRequest())
    assert len(respostas) == 2 and respostas[0] != respostas[1], "releu o token antes de repetir"

    def sempre_401(req, timeout=None):
        respostas.append("x")
        raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(b"{}"))

    respostas.clear()
    monkeypatch.setattr(canal_mod.urllib.request, "urlopen", sempre_401)
    with pytest.raises(grpc.RpcError) as e:
        stub(pb.GetAppInfoRequest())
    assert len(respostas) == 2 and "401" in e.value.details()


class _CanalFalso:
    def __init__(self):
        self.chamados = []

    def unary_unary(self, rota, request_serializer, response_deserializer):
        return lambda pedido, timeout=None: self.chamados.append(rota) or b"ok"

    unary_stream = unary_unary

    def close(self):
        pass


def test_a_pausa_do_monitor_vale_para_quem_pede_pelo_nucleo(monkeypatch):
    """⭐ O motivo do passo 4: carregar e logo fechar a bin, vindo de OUTRO módulo, espera o monitor assentar aqui."""
    canal = _CanalFalso()
    esperas = []
    monkeypatch.setattr(mcapi.grpc, "insecure_channel", lambda endereco: canal)
    monkeypatch.setattr(mcapi.time, "sleep", esperas.append)
    monkeypatch.setattr(mcapi, "_carregou_em", None)
    monkeypatch.setattr(mcapi, "_carregando", 0)
    assert mcapi.chamar_cru("/mcapi.MCAPI/LoadMobsIntoViewer", b"", "unario") == [b"ok"]
    assert mcapi.chamar_cru("/mcapi.MCAPI/CloseBin", b"", "unario") == [b"ok"]
    assert len(esperas) == 1 and 2.5 < esperas[0] <= mcapi.ASSENTAR_DEPOIS_DE_CARREGAR_S
    assert canal.chamados == ["/mcapi.MCAPI/LoadMobsIntoViewer", "/mcapi.MCAPI/CloseBin"]
