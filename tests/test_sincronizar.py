"""A ponte com o Sincronizar: quem sincroniza é ele, e o Ciclo Assist escolhe o material.

Testado contra um Sincronizar de mentira (um `ThreadingHTTPServer` que responde como o de
verdade, versão 0.3.1) — nunca contra o app instalado: teste que depende de o editor ter um
programa aberto reporta o humor da máquina, não o código.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from cicloassist import nle as N
from cicloassist import sincronizar as O
from cicloassist.nle import premiere as P
from cicloassist.nle.premiere import ponte as PT

ARVORE = [
    {"nome": "D02", "id": "d2", "especie": "bin", "bin": "DIARIA"},
    {"nome": "A001.mp4", "id": "1", "especie": "clipe", "bin": "DIARIA/D02/CAM A",
     "arquivo": r"D:\D02\CAM A\A001.mp4"},
    {"nome": "A002.mp4", "id": "2", "especie": "clipe", "bin": "DIARIA/D02/CAM A",
     "arquivo": r"D:\D02\CAM A\A002.mp4"},
    {"nome": "T001.WAV", "id": "3", "especie": "clipe", "bin": "DIARIA/D02/SOM",
     "arquivo": r"D:\D02\SOM\T001.WAV"},
    {"nome": "SEQ D02", "id": "4", "especie": "sequencia", "bin": "DIARIA/D02"},
    {"nome": "arte.psd", "id": "5", "especie": "clipe", "bin": "DIARIA/D02",
     "arquivo": r"D:\D02\arte.psd"},
]


class _SincronizarFalso:
    """O Sincronizar de mentira. `roteiro` diz o que cada rota responde."""

    def __init__(self, **roteiro):
        self.pedidos: list[tuple[str, dict | None]] = []
        self.roteiro = roteiro
        falso = self

        class Mao(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _responder(self, dado, status=200):
                corpo = json.dumps(dado).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corpo)))
                self.end_headers()
                self.wfile.write(corpo)

            def _atender(self, corpo=None):
                caminho = self.path.split("?")[0]
                falso.pedidos.append((caminho, corpo))
                if self.headers.get("X-Ciclo-Token") != falso.token_esperado:
                    return self._responder({"error": "token ausente ou inválido"}, 401)
                resposta = falso.roteiro.get(caminho)
                if callable(resposta):
                    resposta = resposta(corpo, self.path)
                if isinstance(resposta, tuple):
                    return self._responder(resposta[1], resposta[0])
                if resposta is None:
                    return self._responder({"error": "rota desconhecida"}, 404)
                return self._responder(resposta)

            def do_GET(self):
                self._atender()

            def do_POST(self):
                n = int(self.headers.get("Content-Length") or 0)
                self._atender(json.loads(self.rfile.read(n) or b"{}"))

        self.token_esperado = "tok-do-sincronizar"
        self.servidor = ThreadingHTTPServer(("127.0.0.1", 0), Mao)
        self.porta = self.servidor.server_address[1]
        threading.Thread(target=self.servidor.serve_forever, daemon=True).start()

    def parar(self):
        self.servidor.shutdown()

    def rotas(self) -> list[str]:
        return [c for c, _ in self.pedidos]


def _porta_fechada() -> int:
    """Uma porta que NINGUÉM escuta: a do sistema que acabou de ser solta. ⛔ A porta 1 não serve: no Mac mini do
    laboratório (2026-11-22) um serviço do sistema responde nela ("-unknown service") e o teste quebrava."""
    import socket
    with socket.socket() as s_:
        s_.bind(("127.0.0.1", 0))
        return s_.getsockname()[1]


@pytest.fixture
def sinc(monkeypatch, tmp_path):
    def criar(**roteiro):
        falso = _SincronizarFalso(**roteiro)
        monkeypatch.setattr(O, "URL", f"http://127.0.0.1:{falso.porta}")
        monkeypatch.setattr(O, "_token", "")
        monkeypatch.setattr(O, "pasta_de_dados", lambda: tmp_path)
        (tmp_path / "plugin-token").write_text("tok-do-sincronizar", encoding="utf-8")
        monkeypatch.setattr(O, "arquivo_do_token", lambda: tmp_path / "plugin-token")
        monkeypatch.setattr(O, "INTERVALO_S", 0.01)
        return falso
    return criar


@pytest.fixture(autouse=True)
def premiere_falso(monkeypatch):
    # O NLE do turno é global e o padrão é o Avid: sem isto a ferramenta tomaria o
    # caminho do Media Composer.
    monkeypatch.setattr(N, "_atual", N.PREMIERE)
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda funcao, *a, **k: {"itens": list(ARVORE)})
    # Os caminhos da ARVORE são de mentira (`D:\\D02\\…`): sem isto todos seriam OFFLINE.
    from cicloassist.mcp.ferramentas import sincronizar as FO
    monkeypatch.setattr(FO, "_existe", lambda arquivo: True)


# ── o cliente ────────────────────────────────────────────────────────────────

def test_a_saude_nao_se_faz_passar_por_painel(sinc):
    """⚠️ `?nle=` MARCA PRESENÇA de painel no app: o botão "Enviar" dele passaria a
    prometer um painel que não existe."""
    falso = sinc(**{"/health": {"ok": True, "busy": False, "version": "0.3.1"}})
    assert O.saude()["version"] == "0.3.1"
    assert falso.pedidos == [("/health", None)]


def test_token_novo_depois_de_o_sincronizar_reiniciar(sinc, tmp_path):
    """⚠️ O app sorteia um token a cada arranque: o 401 manda RELER o arquivo."""
    falso = sinc(**{"/health": {"ok": True}})
    O.token()                                   # lê o antigo
    falso.token_esperado = "tok-novo"
    (tmp_path / "plugin-token").write_text("tok-novo", encoding="utf-8")
    assert O.saude()["ok"] is True              # releu e passou
    assert falso.rotas().count("/health") == 2  # a primeira levou 401


def test_sincronizar_fechado_diz_onde_ele_mora(sinc, monkeypatch):
    sinc(**{"/health": {"ok": True}})
    monkeypatch.setattr(O, "URL", f"http://127.0.0.1:{_porta_fechada()}")
    with pytest.raises(O.SincronizarIndisponivel, match="bandeja"):
        O.saude()


def test_ocupado_e_resposta_normal_com_a_frase_certa(sinc):
    sinc(**{"/syncmap": (409, {"error": "ocupado"})})
    with pytest.raises(O.SincronizarOcupado, match="um por vez"):
        O.sincronizar([{"path": "x.mov", "group": "cam"}])


def test_o_sync_e_acompanhado_ate_o_fim(sinc):
    estados = iter([
        {"state": "waiting", "stage": "esperando a vez", "fraction": 0},
        {"state": "running", "stage": "ouvindo o som", "fraction": 0.4},
        {"state": "done", "stage": "pronto", "fraction": 1,
         "result": {"name": "D02", "groups": [{"name": "D02", "fps": 23.976,
                                               "camera_groups": [{"cameras": [1, 2]}],
                                               "takes": [1, 2, 3],
                                               "orphan_paths": ["x.mov"],
                                               "orphan_sounds": []}]}},
    ])
    sinc(**{"/syncmap": {"job_id": "j1"},
              "/prproj/status": lambda corpo, caminho: next(estados)})
    etapas = []
    job = O.sincronizar([{"path": "x.mov", "group": "cam"}])
    resultado = O.esperar(job, relatar=lambda etapa, fracao: etapas.append(etapa))
    assert etapas == ["esperando a vez", "ouvindo o som", "pronto"]
    resumo = O.resumo_do_mapa(resultado)
    assert resumo["quantas"] == 1
    # ⛔ Um `camera_group` é UMA câmera física; os de dentro são clipes dela.
    assert resumo["diarias"][0] == {"diaria": "D02", "fps": 23.976, "cameras": 1,
                                    "nomes_das_cameras": [], "clipes_de_camera": 2,
                                    "takes_sincronizados": 3, "cameras_sem_som": 1,
                                    "sons_sem_camera": 0}


def test_sync_que_falha_traz_o_motivo_dele(sinc):
    sinc(**{"/syncmap": {"job_id": "j1"},
              "/prproj/status": {"state": "error", "error": "nenhum timecode utilizável"}})
    with pytest.raises(O.SincronizarFalhou, match="nenhum timecode utilizável"):
        O.esperar(O.sincronizar([{"path": "x.mov", "group": "cam"}]))


# ── a ferramenta ─────────────────────────────────────────────────────────────

def _ferramenta():
    from cicloassist.mcp.ferramentas import sincronizar as FO
    return FO


def test_so_a_midia_da_bin_vai_para_o_sincronizar(sinc):
    """⛔ Sequência e `.psd` não são mídia para o Sincronizar: ele receberia caminho que não
    abre, e a diária dele nasceria torta."""
    FO = _ferramenta()
    assert FO._arquivos_da_bin("DIARIA/D02") == [
        r"D:\D02\CAM A\A001.mp4", r"D:\D02\CAM A\A002.mp4", r"D:\D02\SOM\T001.WAV"]


#: O Sincronizar de mentira com a diária sincronizada e o painel do Premiere escutando.
def _sinc_inteiro(**mudar):
    roteiro = {
        "/health": {"ok": True, "busy": False},
        "/api/v1/info": {"ok": True, "version": "0.3.2", "busy": False,
                         "paineis": {"premiere": True, "resolve": False, "avid": False}},
        "/syncmap": {"job_id": "j9"},
        "/prproj/status": {"state": "done", "result": {"groups": [
            {"name": "D02", "fps": 23.976, "camera_groups": [{"cameras": [1, 2]}],
             "takes": [1, 2], "orphan_paths": [], "orphan_sounds": []}]}},
        "/api/v1/nlejob": {"montagem_id": "ponte-7", "nome": "D02"},
        "/api/v1/montagem": {"estado": "feito", "nome": "D02", "resumo": "ok|1 sequência"},
    }
    roteiro.update(mudar)
    return roteiro


def test_a_conferencia_barra_antes_do_cartao(sinc):
    FO = _ferramenta()
    sinc(**_sinc_inteiro(**{"/health": {"ok": True, "busy": True}}))
    assert "ocupado" in FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])

    sinc(**_sinc_inteiro())
    assert FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}]) == ""
    assert "pelo menos duas" in FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/VAZIA"]}])
    assert "fontes" in FO._conferir(bin="DIARIA/D02")     # só a bin: o palpite pelo nome saiu, e o modelo tem de declarar


def test_sem_painel_do_sincronizar_nem_chega_a_sincronizar(sinc):
    """⚠️⚠️ O sync leva MINUTOS e quem monta a sequência é o painel dele. Descobrir a
    ausência no fim seria fazer o editor esperar por nada — a recusa vem antes do cartão.
    """
    FO = _ferramenta()
    falso = sinc(**_sinc_inteiro(**{
        "/api/v1/info": {"ok": True, "busy": False, "paineis": {"premiere": False}}}))
    assert "aba Preparar" in FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    assert "/syncmap" not in falso.rotas()

    # ⛔ `so_preparar` entregava ao Studio (aposentado), aposentado (2026-11-06): recusado com a frase.
    assert "Studio" in FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], so_preparar=True)


def test_sincronizar_antigo_diz_para_atualizar(sinc):
    """Sem `/api/v1` (0.3.1 e antes) a rota devolve 404 — e "HTTP 404" não diz nada a
    quem lê. A frase tem de nomear o conserto."""
    FO = _ferramenta()
    sinc(**_sinc_inteiro(**{"/api/v1/info": None}))
    assert "antigo" in FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])


def test_sincronizar_monta_a_sequencia_e_diz_que_ela_esta_la(sinc):
    FO = _ferramenta()
    falso = sinc(**_sinc_inteiro())
    r = FO.sincronizar(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], metodo="forma_de_onda")

    enviado = dict(falso.pedidos)["/syncmap"]
    assert enviado["method"] == "waveform"          # o nome em português vira o do Sincronizar
    assert len(enviado["clips"]) == 3
    assert {c["kind"] for c in enviado["clips"]} == {"camera", "sound"}
    assert r["quantas"] == 1 and r["diarias"][0]["takes_sincronizados"] == 2

    # ⭐⭐ O ciclo fecha: o pedido de montagem leva o JOB do sync (não o mapa) e os
    #    rótulos das fontes, que são o que separa as câmeras em trilhas do outro lado.
    pedido = dict(falso.pedidos)["/api/v1/nlejob"]
    assert pedido["job_id"] == "j9" and pedido["nome"] == "D02" and pedido["nle"] == "premiere"
    assert pedido["labels"][r"D:\D02\CAM A\A001.mp4"] == "CAM A"
    assert "map" not in pedido, "o formato do job do painel é assunto do Sincronizar"

    assert "montou a sequência" in r["feito"] and "está no projeto" in r["agora"]
    assert "falta_montar" not in r
    # ⛔⛔ Nunca a fila do painel dele: quem lê /nlejob TIRA o trabalho da fila.
    assert "/nlejob" not in falso.rotas()


def test_o_painel_que_fecha_no_meio_nao_leva_o_sync_junto(sinc):
    """⚠️ Entre a conferência e o fim do sync o editor pode ter fechado o painel. O mapa
    custou minutos de máquina: ele volta inteiro, com o que houve."""
    FO = _ferramenta()
    sinc(**_sinc_inteiro(**{
        "/api/v1/nlejob": (412, {"error": "o painel do Sincronizar não está aberto"})}))
    r = FO.sincronizar(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    assert r["diarias"][0]["takes_sincronizados"] == 2, "o sync não se perde"
    assert "aba Preparar" in r["falta_montar"]
    assert "não foi montada" in r["feito"]


def test_montagem_que_falha_traz_o_motivo_do_painel(sinc):
    FO = _ferramenta()
    sinc(**_sinc_inteiro(**{
        "/api/v1/montagem": {"estado": "erro", "resumo": "err|sem item para A001.mp4"}}))
    r = FO.sincronizar(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    assert r["erro_da_montagem"] == "err|sem item para A001.mp4"
    assert r["diarias"][0]["takes_sincronizados"] == 2


def test_so_preparar_foi_aposentado_com_o_studio(sinc):
    """A janela do Studio (aposentado) que recebia o material saiu (plano um app só): nada vai a `/open`."""
    FO = _ferramenta()
    falso = sinc(**_sinc_inteiro())
    r = FO.sincronizar(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], so_preparar=True)
    assert "Studio" in r["erro"] and "/open" not in falso.rotas() and "/syncmap" not in falso.rotas()


def test_sincronizar_fora_do_ar_vira_frase_e_nao_excecao(sinc, monkeypatch):
    FO = _ferramenta()
    sinc(**{"/health": {"ok": True}})
    monkeypatch.setattr(O, "URL", f"http://127.0.0.1:{_porta_fechada()}")
    r = FO.sincronizar(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}])
    assert "não respondeu" in r["erro"]


def test_a_ferramenta_passa_pelo_portao_nos_dois_editores():
    from cicloassist.mcp.registro import FERRAMENTAS

    f = FERRAMENTAS["sincronizar"]
    assert f.escreve and set(f.nles) == {"avid", "premiere"} and f.conferir is not None


# ── o Media Composer (contrato: DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md §8) ─────────

def _sinc_no_avid(**mudar):
    roteiro = {
        "/health": {"ok": True, "busy": False},
        "/api/v1/info": {"ok": True, "busy": False, "nles": {"avid": True},
                         "capacidades": ["sincronizar", "montar", "avid_sincronizar"]},
        "/api/v1/avid/sincronizar": {"job_id": "a1"},
        "/prproj/status": {"state": "done", "result": {
            "mapa": {"groups": [{"name": "D02 SYNC", "fps": 23.976,
                                 "camera_groups": [{"cameras": [1]}],
                                 "takes": list(range(24)),
                                 "orphan_paths": ["a.mp4", "b.mp4"], "orphan_sounds": []}]},
            "fontes": [{"label": "CAM A", "kind": "camera", "clipes": 26},
                       {"label": "SOM DIRETO", "kind": "sound", "clipes": 24}],
            "bins": ["D02/CAM A", "D02/SOM DIRETO"],
            "faltando": [],
            "montagem": {"names": ["D02 SYNC"], "path": "x.avb", "count": 1}}},
    }
    roteiro.update(mudar)
    return roteiro


def test_no_avid_um_pedido_so_e_a_resposta_que_o_prompt_pede(sinc, monkeypatch):
    """⭐ No MC não há painel: o Sincronizar lê as bins, sincroniza e monta num pedido só."""
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    falso = sinc(**_sinc_no_avid())
    assert FO._conferir(bin="D02") == ""
    r = FO.sincronizar(bin="D02", metodo="hibrido")

    assert dict(falso.pedidos)["/api/v1/avid/sincronizar"] == {"pasta": "D02", "metodo": "hybrid"}
    d = r["diarias"][0]
    assert (d["cameras"], d["takes_sincronizados"], d["cameras_sem_som"]) == (1, 24, 2)
    assert r["sequencia"] == "D02 SYNC" and "duplo clique" in r["agora"]
    # Nada do caminho do Premiere: nem classificar arquivo, nem a fila do painel.
    assert not {"/sources", "/syncmap", "/api/v1/nlejob", "/nlejob"} & set(falso.rotas())


def test_no_avid_a_conferencia_barra_antes_do_cartao(sinc, monkeypatch):
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    sinc(**_sinc_no_avid(**{"/api/v1/info": {"ok": True, "nles": {"avid": False},
                                                 "capacidades": ["avid_sincronizar"]}}))
    assert "Media Composer não está aberto" in FO._conferir(bin="D02")
    sinc(**_sinc_no_avid(**{"/api/v1/info": {"ok": True, "nles": {"avid": True},
                                                 "capacidades": ["sincronizar"]}}))
    assert "antigo" in FO._conferir(bin="D02")
    sinc(**_sinc_no_avid())
    assert "pasta" in FO._conferir(bin="")
    assert "so_preparar" in FO._conferir(bin="D02", so_preparar=True)


def test_no_avid_o_erro_do_job_vira_frase(sinc, monkeypatch):
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    sinc(**_sinc_no_avid(**{"/prproj/status": {
        "state": "error", "error": "não há bin na pasta \"D09\" do projeto aberto"}}))
    assert "não há bin" in FO.sincronizar(bin="D09")["erro"]

    sinc(**_sinc_no_avid(**{"/api/v1/avid/sincronizar": (412, {"error": "x"})}))
    assert "não está aberto" in FO.sincronizar(bin="D02")["erro"]

    sinc(**_sinc_no_avid(**{"/api/v1/avid/sincronizar": (409, {"error": "x"})}))
    assert FO.sincronizar(bin="D02")["ocupado"] is True


def test_no_avid_as_bins_da_raiz_vao_como_lista(sinc, monkeypatch):
    """⛔⛔ O teste do autor (2026-11-01): CAM e SOM na RAIZ do projeto, sem pasta nenhuma. O
    endpoint do Sincronizar sempre aceitou `bins`; o Assist só sabia mandar `pasta`."""
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    falso = sinc(**_sinc_no_avid())
    assert FO._conferir(bins=["M07 CAM", "M07 SOM.avb"]) == ""
    FO.sincronizar(bins=["M07 CAM", "M07 SOM.avb"])
    assert dict(falso.pedidos)["/api/v1/avid/sincronizar"] == {
        "metodo": "hybrid", "bins": ["M07 CAM", "M07 SOM"], "nome": "M07 SYNC"}


def test_no_avid_o_nome_do_projeto_como_pasta_volta_com_as_bins_que_ha(sinc, monkeypatch):
    """O modelo mandou `desktop` (o projeto) e depois o caminho dele: a recusa vem ANTES do
    cartão, com as bins do projeto para ele acertar."""
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    sinc(**_sinc_no_avid())
    monkeypatch.setattr(FO, "bins_do_projeto_aberto", lambda: ["desktop Bin", "M07 CAM", "M07 SOM"])
    recusa = FO._conferir(bin="desktop")
    assert "não há bin dentro da pasta 'desktop'" in recusa and "M07 CAM" in recusa and "`bins`" in recusa
    assert "M07 FALTA" in FO._conferir(bins=["M07 CAM", "M07 FALTA"])
    assert FO._conferir(bins=["m07 cam", "M07 SOM"]) == ""        # o Sincronizar compara sem caixa


def test_nome_da_diaria_sem_pasta():
    FO = _ferramenta()
    assert FO.nome_das_bins(["M07 CAM", "M07 SOM"]) == "M07 SYNC"
    assert FO.nome_das_bins(["CAMERA", "AUDIO"]) == "DIARIA SYNC"


def test_no_avid_os_subclipes_por_cena_seguem_o_sync_no_mesmo_cartao(sinc, monkeypatch):
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    resultado_do_sync = _sinc_no_avid()["/prproj/status"]["result"]
    resultado_do_sync["montagem"]["path"] = r"C:\Proj\D02 SYNC.avb"
    estados = {
        "a1": {"state": "done", "result": resultado_do_sync},
        "l1": {"state": "done", "result": {"leitura_id": "L", "tomadas": [{}] * 26}},
        "g1": {"state": "done", "result": {
            "bins": [{"cena": "C04", "takes": 20}, {"cena": "C07", "takes": 6}],
            "total": 26, "caminhos": [r"C:\Proj\CENAS\C04.avb", r"C:\Proj\CENAS\C07.avb"],
            "aberta": True}},
    }
    falso = sinc(**_sinc_no_avid(**{
        "/avid/subclipes/ler": {"job_id": "l1"},
        "/avid/subclipes/gerar": {"job_id": "g1"},
        "/prproj/status": lambda corpo, caminho: estados[caminho.split("id=")[1]]}))
    salvos = []
    monkeypatch.setattr(FO, "_mostrar_a_pasta_nova", lambda b: salvos.append(b) or {"salvou": True})
    r = FO.sincronizar(bin="D02", subclipes="por_cena")

    assert salvos == [r"C:\Proj\D02 SYNC.avb"]       # ⭐ a op. 8 no fim, com a bin da RAIZ
    assert r["painel_de_bins"] == {"salvou": True} and "Ctrl+S" not in r["agora"]
    pedidos = dict(falso.pedidos)
    assert pedidos["/avid/subclipes/ler"] == {"bin": r"C:\Proj\D02 SYNC.avb"}
    assert pedidos["/avid/subclipes/gerar"] == {
        "leitura_id": "L", "padrao": "%{nomedevideo}", "por_cena": True,  # ⭐ de fábrica: o vídeo
        "nome": ""}
    s = r["subclipes"]
    assert s["tomadas"] == 26 and s["bins"] == ["C04.avb", "C07.avb"]
    assert [b["cena"] for b in s["bins_por_cena"]] == ["C04", "C07"]
    assert "CENAS" in r["feito"]


def test_no_avid_a_bin_dos_subclipes_leva_o_nome_que_o_editor_pediu(sinc, monkeypatch):
    """⛔ 2026-11-01: "uma bin chamada subclipes" saía `D01 SUBCLIPES`."""
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    resultado_do_sync = _sinc_no_avid()["/prproj/status"]["result"]
    resultado_do_sync["montagem"]["path"] = r"C:\Proj\D01.avb"
    estados = {
        "a1": {"state": "done", "result": resultado_do_sync},
        "l1": {"state": "done", "result": {"leitura_id": "L", "tomadas": [{}] * 4}},
        "g1": {"state": "done", "result": {"total": 4, "caminhos": [r"C:\Proj\subclipes.avb"],
                                           "aberta": True}},
    }
    falso = sinc(**_sinc_no_avid(**{
        "/avid/subclipes/ler": {"job_id": "l1"}, "/avid/subclipes/gerar": {"job_id": "g1"},
        "/prproj/status": lambda corpo, caminho: estados[caminho.split("id=")[1]]}))
    r = FO.sincronizar(bin="D01", subclipes="uma_bin", bin_dos_subclipes="subclipes")
    assert dict(falso.pedidos)["/avid/subclipes/gerar"]["nome"] == "subclipes"
    assert r["subclipes"]["bins"] == ["subclipes.avb"] and "na bin subclipes" in r["feito"]


def test_no_avid_subclipe_que_falha_nao_leva_o_sync_junto(sinc, monkeypatch):
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    sinc(**_sinc_no_avid(**{"/avid/subclipes/ler": (409, {"error": "x"})}))
    r = FO.sincronizar(bin="D02", subclipes="por_cena")
    assert r["sequencia"] == "D02 SYNC" and "ocupado" in r["subclipes_falharam"]


def test_no_premiere_subclipes_e_recusado_antes_do_cartao(sinc):
    FO = _ferramenta()
    sinc(**_sinc_inteiro())
    assert "Media Composer" in FO._conferir(fontes=[{"tipo": "camera", "bins": ["DIARIA/D02"]}, {"tipo": "som", "bins": ["DIARIA/D02"]}], subclipes="por_cena")


def test_por_cena_sem_save_diz_o_gesto_e_nao_perde_o_sync(sinc, monkeypatch):
    monkeypatch.setattr(N, "_atual", N.AVID)
    FO = _ferramenta()
    resultado_do_sync = _sinc_no_avid()["/prproj/status"]["result"]
    resultado_do_sync["montagem"]["path"] = r"C:\Proj\D02 SYNC.avb"
    estados = {
        "a1": {"state": "done", "result": resultado_do_sync},
        "l1": {"state": "done", "result": {"leitura_id": "L", "tomadas": [{}]}},
        "g1": {"state": "done", "result": {"bins": [{"cena": "C04", "takes": 1}], "total": 1,
                                           "caminhos": [r"C:\Proj\CENAS\C04.avb"]}},
    }
    sinc(**_sinc_no_avid(**{
        "/avid/subclipes/ler": {"job_id": "l1"}, "/avid/subclipes/gerar": {"job_id": "g1"},
        "/prproj/status": lambda corpo, caminho: estados[caminho.split("id=")[1]]}))
    monkeypatch.setattr(FO, "_mostrar_a_pasta_nova", lambda b: {"salvou": False})
    r = FO.sincronizar(bin="D02", subclipes="por_cena")
    assert r["sequencia"] == "D02 SYNC" and r["subclipes"]["tomadas"] == 1
    assert "Ctrl+S" in r["agora"]


def test_mostrar_a_pasta_nova_abre_a_bin_da_raiz_e_salva(monkeypatch):
    FO = _ferramenta()
    chamadas = []

    class MC:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def projeto(self, recarregar=False): return {"caminho": r"C:\Proj"}
        def caminho_relativo_da_bin(self, p): return "D02 SYNC.avb"
        def _chamar(self, nome, **kw): chamadas.append((nome, kw["bin_path"]))

    monkeypatch.setattr(FO, "MediaComposer", MC)
    monkeypatch.setattr(FO._salvar, "sujar", lambda m, b: chamadas.append(("sujar", b)))
    monkeypatch.setattr(FO._salvar, "salvar_tudo", lambda c, relatar=None: {"salvou": True, "projeto": c})
    assert FO._mostrar_a_pasta_nova(r"C:\Proj\D02 SYNC.avb") == {"salvou": True, "projeto": r"C:\Proj"}
    assert chamadas == [("sujar", r"C:\Proj\D02 SYNC.avb")]

    def falha(c, relatar=None):
        raise FO._salvar.SalvarFalhou("há um aviso do Media Composer na tela")
    monkeypatch.setattr(FO._salvar, "salvar_tudo", falha)
    assert FO._mostrar_a_pasta_nova("x")["erro"].startswith("há um aviso")


def test_a_camera_em_duas_bins_e_uma_fonte_so_e_o_som_pega_so_o_audio(sinc):
    FO = _ferramenta()
    falso = sinc(**_sinc_inteiro())
    FO.sincronizar(fontes=[{"tipo": "camera", "nome": "CAM A", "bins": ["DIARIA/D02"]},
                           {"tipo": "som", "bins": ["DIARIA/D02"]}])
    clipes = dict(falso.pedidos)["/syncmap"]["clips"]
    assert {c["group"] for c in clipes if c["kind"] == "camera"} == {"CAM A"}
    assert [c["path"] for c in clipes if c["kind"] == "sound"] == [r"D:\D02\SOM\T001.WAV"]
