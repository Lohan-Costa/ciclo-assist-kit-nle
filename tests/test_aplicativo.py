"""A janela do app (`app/`) e o que o serviço sabe dela (`servico/aplicativo.py`).

Decisão do autor, 2026-10-18/21: o Assist sai do painel encaixável e vira janela de app
(`docs/plano/2026-10-18-app-sem-painel.md`). Estes testes cobrem o lado do serviço e do
painel; a casca em Rust tem o seu (`cargo test` em `app/src-tauri`).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import threading
from pathlib import Path

import sys

import pytest

from cicloassist.servico import aplicativo
from cicloassist.servico import rotas  # noqa: F401  (registra as rotas por import)
from cicloassist.servico.http import ROTAS, Pedido

PAINEL = Path(__file__).resolve().parent.parent / "cicloassist" / "painel"


@pytest.fixture(autouse=True)
def sem_app():
    aplicativo.apresentar(None)
    yield
    aplicativo.apresentar(None)


def _post(caminho: str, corpo: dict):
    fn, _ = ROTAS[("POST", caminho)]
    r = fn(Pedido("POST", caminho, {"sec-fetch-site": "same-origin"}, json.dumps(corpo).encode()))
    return r.status, json.loads(r.corpo)


def test_sem_app_as_rotas_respondem_200_e_dizem_que_nao_ha_janela():
    """A bancada (`dev.ps1`) e o painel dentro do NLE sobem o serviço sem app: o pino não
    pode virar erro ali — é o serviço sem aplicativo, não um defeito."""
    assert _post("/app/fixar", {"fixar": True}) == (200, {"janela": False, "motivo": "sem aplicativo"})
    assert _post("/app/fechar", {})[1]["janela"] is False


def test_app_que_nao_existe_e_recusado_no_arranque(tmp_path):
    """Conferido AGORA, e não na hora do clique: um `--app` errado apareceria no meio do
    trabalho, com cara de defeito do pino."""
    assert aplicativo.apresentar(str(tmp_path / "nao-existe.exe")) is None
    assert not aplicativo.presente()


def test_o_pino_reinvoca_o_executavel_com_o_argumento(tmp_path, monkeypatch):
    exe = tmp_path / "cicloassist.exe"
    exe.write_bytes(b"")
    aplicativo.apresentar(str(exe))
    chamadas = []
    monkeypatch.setattr(aplicativo.subprocess, "Popen", lambda args, **_: chamadas.append(args))
    assert _post("/app/fixar", {"fixar": True}) == (200, {"janela": True})
    assert _post("/app/fixar", {"fixar": False}) == (200, {"janela": True})
    assert _post("/app/fechar", {}) == (200, {"janela": True})
    assert chamadas == [[str(exe), "--fixar"], [str(exe), "--soltar"], [str(exe), "--encerrar"]]


def test_os_argumentos_sao_os_que_a_casca_entende():
    """Dois literais em dois idiomas divergem calados: o `lib.rs` tem de tratar cada
    argumento que o serviço manda, senão o pino "funciona" e nada acontece."""
    lib = (Path(__file__).resolve().parent.parent / "app" / "src-tauri" / "src" / "lib.rs").read_text(
        encoding="utf-8")
    for arg in ("--fixar", "--soltar", "--encerrar"):
        assert f'"{arg}"' in lib, arg


def _vigiar(vivo, ocupado):
    parar = threading.Event()
    t = aplicativo.vigiar(1234, parar, intervalo_s=0.01, vivo=vivo, ocupado_agora=ocupado)
    return parar, t


def test_o_servico_encerra_quando_o_app_fecha():
    estado = {"vivo": True}
    parar, t = _vigiar(lambda: estado["vivo"], lambda: False)
    assert not parar.wait(0.05)
    estado["vivo"] = False
    assert parar.wait(2.0)
    t.join(1.0)


def test_mas_nunca_no_meio_de_um_trabalho():
    """O app fechou com um turno (ou a fila) andando: o serviço termina o trabalho e então
    sai — matar no meio perderia a resposta e deixaria a bin do editor a meio caminho."""
    estado = {"ocupado": True}
    parar, t = _vigiar(lambda: False, lambda: estado["ocupado"])
    assert not parar.wait(0.1)
    estado["ocupado"] = False
    assert parar.wait(2.0)
    t.join(1.0)


def test_o_app_vivo_do_proprio_processo():
    import os

    vivo = aplicativo.app_vivo(os.getpid())
    assert vivo is not None and vivo()


def test_o_arrasto_da_casca_devolve_o_caminho_exato():
    """⭐ O alvo nativo (`arrasto_win.rs`) entrega CAMINHOS do Explorer; o painel os passa
    a `text/uri-list` para cair no MESMO `aoSoltar` de sempre (a autorização de leitura,
    ADR 0005). A ida e a volta têm de devolver o caminho EXATO — um `#`, um `%` ou um
    acento perdido viraria "não encontrei" para um arquivo que está lá."""
    node = shutil.which("node")
    if not node:
        pytest.skip("node não está instalado; o painel não é conferido nesta máquina")
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    pedaco = lambda nome: re.search(r"function %s\(.*?\n\}" % nome, js, re.S).group(0)  # noqa: E731
    casos = ["C:\\Users\\usuario\\roteiro #1.pdf", "\\\\nas\\share\\a b.mov", "D:\\100%\\x.txt"]
    programa = ('var MIME_DO_AVID = "text/x.avid.mc-api-asset-list+json";\n'
                + pedaco("caminhoDaUri") + "\n" + pedaco("caminhosDoArrasto") + "\n"
                + pedaco("dtDaCasca") + "\n"
                + "var dt = dtDaCasca({tipo: 'arquivos', fase: 'soltou', caminhos: %s});\n" % json.dumps(casos)
                + "var av = dtDaCasca({tipo: 'avid', fase: 'soltou', dados: '[{\"id\":\"x\"}]'});\n"
                + "var antes = dtDaCasca({tipo: 'avid', fase: 'sobre', dados: 'y'});\n"
                + "console.log(JSON.stringify([caminhosDoArrasto(dt), av.types, av.getData(MIME_DO_AVID),"
                + " antes.getData(MIME_DO_AVID)]));")
    r = subprocess.run([node, "-e", programa], capture_output=True, text=True, timeout=30, encoding="utf-8")
    assert r.returncode == 0, r.stderr
    caminhos, tipos, dados, antes = json.loads(r.stdout)
    assert caminhos == casos
    assert tipos == ["text/x.avid.mc-api-asset-list+json"]   # ⛔ do Avid, NUNCA o uri-list (o .aaf falso)
    assert dados == '[{"id":"x"}]'
    assert antes == ""                                        # o dado só existe no soltar


def test_o_pino_so_aparece_na_casca():
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    assert re.search(r'id="pino"[^>]*hidden|hidden[^>]*id="pino"', html, re.S)


# ── o MC 24.6 visto pela janela (2026-10-21) ───────────────────────────────────


class _MonitorFalso:
    """Um MC que, como o 24.6, mostra no Source um EMBRULHO do mob carregado."""

    def __init__(self, embrulho: str):
        self.embrulho = embrulho
        self.carregados: list[str] = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def _enum(self, metodo, campo, nome):
        return {"Source": 0, "Record": 1}[nome]

    def _chamar(self, metodo, _timeout=None, **campos):
        from types import SimpleNamespace as N
        if metodo == "LoadMobsIntoViewer":
            self.carregados.append(campos["mob_ids"][0])
            return N(body=N())
        if metodo == "GetViewerMobs":
            return N(body=N(mobs=[N(view_type=0, mob_id=self.embrulho.upper()),
                                  N(view_type=1, mob_id="SEQ-DO-RECORD")]))
        raise AssertionError(metodo)


def test_no_24_6_o_mesmo_clipe_e_reconhecido_pelo_embrulho(monkeypatch):
    """⛔ MEDIDO no MC 24.6: o Source devolve um mob que não é o master (sem bin, id novo a
    cada carga). Sem lembrar o embrulho, "já está no Source" dizia sempre não, e o 2º clique
    no mesmo clipe abria a bin e carregava de novo — o MC pendurado mais 30 s."""
    import time

    mc = _MonitorFalso("060a2b34-embrulho-do-source")
    monkeypatch.setattr(rotas._mcapi, "MediaComposer", lambda *a, **k: mc)
    monkeypatch.setattr(rotas, "_EMBRULHOS", {})
    master = "060a2b340101010001010f0013-000000-b297c16a463103c6-35e5f6be9cd9-3c2d"
    assert not rotas._ja_esta_no_monitor(master)          # antes de carregar: não está
    assert rotas._carregar_no_monitor(master, "Source")
    for _ in range(100):                                   # a lembrança é lida numa thread
        if rotas._EMBRULHOS:
            break
        time.sleep(0.01)
    assert rotas._ja_esta_no_monitor(master)
    assert not rotas._ja_esta_no_monitor(master.replace("b297", "c397"))   # outro clipe não


def test_o_carregar_tem_prazo_proprio_maior_que_o_de_consulta():
    from cicloassist.avid.mcapi import TEMPO_DE_CONSULTA_S
    assert rotas.TEMPO_DE_CARREGAR_S >= 60 > TEMPO_DE_CONSULTA_S


def test_o_texto_depois_de_ferramenta_vira_paragrafo():
    """Visto na janela: "Vou checar os dois.No roteiro" — duas mensagens do modelo emendadas."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert re.search(r'tipo === "ferramenta"\) \{\s+depoisDeFerramenta = true;', js)
    assert r'if (depoisDeFerramenta && bruto && !/\s$/.test(bruto)) { bruto += "\n\n"; }' in js


def test_a_espera_do_carregar_diz_de_quem_e():
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert "está abrindo a mídia" in js and "clearTimeout(demora)" in js


# ── o Premiere pela ponte invisível (2026-10-21) ───────────────────────────────


def test_a_extensao_da_ponte_e_invisivel_sem_node_e_xml_valido():
    """⛔⛔ Dois hifens dentro de comentário fazem o CEP recusar o manifesto em silêncio (23.2) — e o
    XML do ElementTree aceita; por isso a conferência do texto de cada comentário."""
    import xml.etree.ElementTree as ET

    caminho = Path(__file__).resolve().parents[1] / "ponte_cep" / "CSXS" / "manifest.xml"
    texto = caminho.read_text(encoding="utf-8")
    raiz = ET.fromstring(texto.encode("utf-8"))
    for comentario in re.findall(r"<!--(.*?)-->", texto, re.S):
        assert "--" not in comentario
    assert raiz.get("ExtensionBundleId") == "com.ciclomedia.cicloassist.ponte"
    assert [e.text for e in raiz.iter("AutoVisible")] == ["false"]       # sem interface no Premiere
    assert "--enable-nodejs" not in [p.text for p in raiz.iter("Parameter")]
    assert not list(raiz.iter("Menu"))                                    # nem entrada de menu
    loader = (caminho.parent.parent / "index.html").read_text(encoding="utf-8")
    assert "127.0.0.1:7824" in loader and "/premiere/ponte" in loader


def test_a_ponte_servida_carrega_o_script_de_fora():
    assert ("GET", "/premiere/ponte") in ROTAS and ("GET", "/conexao") in ROTAS
    assert ("POST", "/premiere/selecao") in ROTAS
    html = (PAINEL / "ponte.html").read_text(encoding="utf-8")
    assert '<script src="/static/ponte.js"></script>' in html
    assert "<script>" not in html                                         # nada inline


def test_o_aviso_de_fio_so_aparece_depois_de_um_turno_nesta_visita(monkeypatch):
    """⛔ Visto na janela do app: reiniciado o app, "esta conversa continua de antes (2 turnos)"
    — e o primeiro turno da visita nova joga o fio fora. Só um Reload no MEIO da visita (um
    turno já feito) continua de verdade, e aí o fio diz de que editor é."""
    from cicloassist.servico import config, presenca

    fio = {"turnos": 2, "contexto": 28000, "fracao": 0.03, "nle": "avid", "projeto": ""}
    monkeypatch.setattr(config, "ler_estado", lambda: {"fio": fio})
    monkeypatch.setattr(rotas, "_visita_do_fio", {})
    presenca.esquecer()
    assert rotas._fio()["novo"] is True                  # processo novo: a próxima pergunta é limpa

    visita = presenca.bater()
    assert rotas._fio()["novo"] is True                  # visita sem turno ainda: também
    rotas._visita_do_fio["chave-do-projeto"] = visita     # houve um turno nesta visita
    f = rotas._fio()
    assert f["novo"] is False and f["turnos"] == 2 and f["nle"] == "avid"
    presenca.esquecer()


def test_o_painel_anuncia_o_fio_mesmo_vindo_do_outro_editor():
    """⭐ A conversa é da janela (2026-11-01): ela continua quando o editor troca de NLE."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert "fio.nle !== NLE" not in js


# ── o guarda-chuva: a moldura é uma só (2026-10-21) ────────────────────────────


def test_embutido_o_painel_esconde_a_propria_moldura_e_abre_as_configuracoes():
    """⭐ O contrato dos três apps no guarda-chuva: `?embutido=1` esconde a moldura (o topo dele já mostra a
    conexão e o pino, a engrenagem é uma só, a assinatura é do rodapé) e `cicloEmbutido.configuracoes()` vai e
    volta das configurações — é o que a engrenagem única chama na aba visível."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")
    assert "window.cicloEmbutido = {" in js and "configuracoes: function (abrir)" in js
    # ⛔ `configuracoes(false)` FECHA e volta à subaba de antes: o guarda-chuva chama assim no app que sai de vista
    assert "var querer = abrir === undefined ? !aberta : !!abrir;" in js
    assert "mostrarTela(telaAntesDosAjustes)" in js
    # as subabas do Assistir com o nome do que fazem, e a régua comum das três
    assert 'textContent = "Assistir"' in js and 'textContent = "Buscar"' in js
    assert ".embutido .abas .aba { padding: 8px 12px;" in css
    assert ".embutido .topo .pino" in css and ".embutido .abas .engrenagem" in css
    # o seletor de editor só aparece embutido com os DOIS ligados
    assert "seletor.hidden = vivos.length < 2 && (EMBUTIDO || NLE_PEDIDO === \"\");" in js


@pytest.mark.skipif(sys.platform != "win32", reason="caminho C:\\ de propósito; no Mac o Path não separa por barra invertida")
def test_a_conexao_tem_o_detalhe_que_o_topo_mostra(monkeypatch):
    class MC:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def esta_vivo(self): return True
        def info(self): return {"versao": "2024.6.58520"}

    monkeypatch.setattr(rotas._mcapi, "MediaComposer", lambda *a, **k: MC())
    monkeypatch.setattr(rotas._escopo, "projeto_aberto", lambda *a, **k: r"C:\Avid Projects\DLPC PRODUCAO-A 2024" + "\\")
    monkeypatch.setattr(rotas._ponte, "painel_vivo", lambda: True)
    monkeypatch.setattr(rotas._ponte, "chamar", lambda f, *a, **k: {"versao": "23.6.0", "nome": "DEMO.prproj"})
    monkeypatch.setattr(rotas._resolve, "servidor_no_ar", lambda: False)
    monkeypatch.setattr(rotas, "_conexao_guardada", [])
    monkeypatch.setattr("cicloassist.nle.premiere.mcp_nativo.situacao", lambda: {"disponivel": False})
    fn, _ = ROTAS[("GET", "/conexao")]
    c = json.loads(fn(Pedido("GET", "/conexao", {})).corpo)
    assert c["avid"] and c["premiere"] and c["resolve"] is False
    assert c["detalhe"]["avid"] == {"versao": "2024.6.58520", "projeto": "DLPC PRODUCAO-A 2024"}
    assert c["detalhe"]["premiere"] == {"versao": "23.6.0", "projeto": "DEMO", "mcp": {"disponivel": False}}


def test_a_conexao_ve_o_resolve_e_le_o_detalhe_no_fundo(monkeypatch):
    """⭐ Com o Resolve aberto o topo dizia "nenhum editor aberto" (pilotado em 2026-10-29). O
    detalhe vem de um processo filho: a rota nunca espera por ele."""
    import threading as _t
    class MC:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def esta_vivo(self): return False
    lido = _t.Event()
    def atual():
        lido.set()
        return {"versao": "19.1.4.11", "antes": "PRODC ASSIST"}
    monkeypatch.setattr(rotas._mcapi, "MediaComposer", lambda *a, **k: MC())
    monkeypatch.setattr(rotas._ponte, "painel_vivo", lambda: False)
    monkeypatch.setattr(rotas._resolve, "servidor_no_ar", lambda: True)
    monkeypatch.setattr(rotas._resolve, "projeto_atual", atual)
    monkeypatch.setattr(rotas, "_resolve_guardado", [0.0, {}])
    monkeypatch.setattr(rotas, "_conexao_guardada", [])
    fn, _ = ROTAS[("GET", "/conexao")]
    c = json.loads(fn(Pedido("GET", "/conexao", {})).corpo)
    assert c["resolve"] and c["detalhe"]["resolve"] == {}      # a primeira não espera
    assert lido.wait(2)
    for _ in range(50):
        if rotas._resolve_guardado[1]: break
        _t.Event().wait(0.02)
    monkeypatch.setattr(rotas, "_conexao_guardada", [])
    c = json.loads(fn(Pedido("GET", "/conexao", {})).corpo)
    assert c["detalhe"]["resolve"] == {"versao": "19.1.4.11", "projeto": "PRODC ASSIST"}


def test_a_conexao_reconhece_o_baselight(monkeypatch):
    """(proposta 2026-11-22-baselight-no-app, etapa 1) O Baselight aberto aparece na conexão com a versão do .app; os
    serviços dele no ar com a interface fechada NÃO contam."""
    from cicloassist import baselight as B
    class MC:
        def __enter__(self): return self
        def __exit__(self, *_): return None
        def esta_vivo(self): return False
    monkeypatch.setattr(rotas._mcapi, "MediaComposer", lambda *a, **k: MC())
    monkeypatch.setattr(rotas._ponte, "painel_vivo", lambda: False)
    monkeypatch.setattr(rotas._resolve, "servidor_no_ar", lambda: False)
    monkeypatch.setattr(rotas, "_conexao_guardada", [])
    monkeypatch.setattr(B, "_linha_do_processo", lambda: "123 /Applications/Baselight/7.0.3.26500/"
                        "Baselight-7.0.3.26500.app/Contents/MacOS/Baselight")
    fn, _ = ROTAS[("GET", "/conexao")]
    c = json.loads(fn(Pedido("GET", "/conexao", {})).corpo)
    assert c["baselight"] is True and c["detalhe"]["baselight"] == {"versao": "7.0.3"}
    monkeypatch.setattr(rotas, "_conexao_guardada", [])
    monkeypatch.setattr(B, "_linha_do_processo", lambda: "")
    c = json.loads(fn(Pedido("GET", "/conexao", {})).corpo)
    assert c["baselight"] is False and c["detalhe"]["baselight"] == {}
