"""Os testes de estado do `httpserver.rs` e do `ponte_premiere.rs` (`d57904e`) portados — os nomes são os do Rust."""
import json
import time
from pathlib import Path

import ponte
import servidor as S
import trabalhos as tb


def _corpo(r):
    return json.loads(r.corpo)


def _job_pronto(resultado, done=True, erro=None):
    jid = tb.reservar("x")
    if done:
        (tb.terminou_mal(jid, erro) if erro else tb.terminou_bem(jid, resultado))
    return jid


def test_motor_ocupado_e_visto_por_um_job_nao_terminado():
    assert tb.em_curso() is None
    a = tb.reservar("x")
    assert tb.em_curso() == a
    tb.terminou_bem(a, {})
    assert tb.em_curso() is None


def test_reservar_job_recusa_em_vez_de_enfileirar():
    a = tb.reservar("x")
    try:
        tb.reservar("y")
        raise AssertionError("devia recusar")
    except tb.Ocupado as o:
        assert o.outro == a
    assert len(tb._jobs) == 1, "e não deixa job fantasma para trás"
    tb.terminou_bem(a, {})
    tb.reservar("z")


def test_jobs_terminados_sao_podados_ao_reservar_o_proximo():
    v = tb.reservar("x")
    tb.terminou_bem(v, {})
    tb._jobs[v].terminado = time.monotonic() - tb.JOB_TTL - 1
    r = tb.reservar("x")
    tb.terminou_bem(r, {})
    novo = tb.reservar("x")
    assert v not in tb._jobs, "o terminado e vencido sai"
    assert r in tb._jobs, "o terminado HÁ POUCO fica: o painel ainda pode vir buscar o resultado"
    assert novo in tb._jobs


def _barra(teto, evento):
    j = tb.reservar("x")
    tb.sink_na_faixa(j, 0.0, teto)(evento)
    return tb.obter(j)


def test_a_barra_segue_o_overall_e_para_no_teto():
    j = _barra(0.95, {"kind": "status", "overall": 1.0, "message": "quase"})
    assert abs(j.fraction - 0.95) < 1e-6 and j.stage == "quase" and not j.waiting
    tb._zerar()
    assert abs(_barra(1.0, {"kind": "status", "overall": 1.0}).fraction - 1.0) < 1e-6


def test_sem_overall_a_barra_cai_no_contador_da_fase():
    assert abs(_barra(1.0, {"kind": "status", "current": 3, "total": 4}).fraction - 0.75) < 1e-6
    tb._zerar()
    assert _barra(1.0, {"kind": "status", "current": 0, "total": 0}).fraction == 0.0


def test_so_o_status_mexe_na_barra_e_mensagem_vazia_nao_apaga_a_etapa():
    j = _barra(1.0, {"kind": "peaks", "overall": 0.5, "message": "y"})
    assert j.fraction == 0.0 and j.waiting
    tb._zerar()
    j = _barra(1.0, {"kind": "status", "overall": 0.5})
    assert abs(j.fraction - 0.5) < 1e-6 and j.stage == "x"


def test_a_faixa_desloca_a_barra():
    """O `/api/v1/avid/sincronizar` reparte a barra: seleção 0–0,2, sync 0,2–0,9."""
    assert abs(_barra_faixa(0.2, 0.9, {"kind": "status", "overall": 0.5}) - 0.55) < 1e-6


def _barra_faixa(lo, hi, ev):
    j = tb.reservar("x")
    tb.sink_na_faixa(j, lo, hi)(ev)
    return tb.obter(j).fraction


def test_status_do_job_tem_os_campos_do_rust():
    j = tb.reservar("iniciando…")
    s = tb.status(j)
    assert set(s) == {"state", "fraction", "stage", "elapsed_ms", "result", "error"}
    assert s["state"] == "waiting"
    tb.etapa(j, 0.3, "lendo")
    assert tb.status(j)["state"] == "running"
    tb.terminou_mal(j, "quebrou")
    assert tb.status(j)["state"] == "error" and tb.status(j)["error"] == "quebrou"


def test_fila_do_painel_entrega_uma_vez_e_carimba_presenca():
    assert not tb.ouvindo("premiere") and not tb.ouvindo("resolve")
    tb.marcar_presenca("resolve")
    assert tb.ouvindo("resolve") and not tb.ouvindo("premiere")
    assert tb.enfileirar_nle([{"id": "a"}, {"id": "b"}], "premiere") == 2
    assert tb.pegar_job("premiere")["id"] == "a"
    assert tb.ouvindo("premiere")
    assert tb.pegar_job("premiere")["id"] == "b"
    assert tb.pegar_job("premiere") is None
    tb.enfileirar_nle([{"id": "r1"}], "resolve")
    assert tb.pegar_job("premiere") is None, "o Premiere NÃO pode levar trabalho endereçado ao Resolve"
    assert tb.pegar_job("resolve")["id"] == "r1"
    tb.enfileirar_nle([{"id": "x", "nle": "resolve"}], "premiere")
    assert tb.pegar_job("resolve") is None, "o `nle` do job de entrada é ignorado"
    assert tb.pegar_job("premiere")["id"] == "x"
    tb.enfileirar_nle([{"id": "velho"}], "qualquer-coisa")
    assert tb.pegar_job("premiere")["id"] == "velho"


def test_a_batida_do_painel_do_avid_nao_vira_presenca_do_premiere():
    assert tb.nle_de("avid") == "avid" and tb.nle_de("resolve") == "resolve"
    assert tb.nle_de(None) == "premiere" and tb.nle_de("premiere") == "premiere"
    tb.marcar_presenca("avid")
    assert tb.ouvindo("avid") and not tb.ouvindo("premiere")


def test_a_ponte_enfileira_a_montagem_e_conta_o_fim():
    jid = _job_pronto({"name": "PROJETO", "groups": [{"name": "", "fps": 24, "takes": []}]})
    pedido = {"job_id": jid, "nle": "premiere", "nome": "DIÁRIA 02", "labels": {"/x/cam.mov": "CAM A"}}
    assert S.api_enfileirar_montagem(pedido).status == 412
    tb.marcar_presenca("premiere")
    assert S.api_enfileirar_montagem(pedido).status == 200
    job = tb.pegar_job("premiere")
    assert job["name"] == "DIÁRIA 02" and len(job["map"]["groups"]) == 1
    assert job["map"]["groups"][0]["name"] == "DIÁRIA 02"
    assert job["labels"]["/x/cam.mov"] == "CAM A"
    assert tb.montagem(job["id"])["estado"] == "montando"
    tb.montagem_terminou(job["id"], True, "ok|1 sequência")
    assert tb.montagem(job["id"]) == {"estado": "feito", "nome": "DIÁRIA 02", "nle": "premiere",
                                      "resumo": "ok|1 sequência"}


def test_o_merged_escreve_e_enfileira_a_importacao():
    jid = _job_pronto({"name": "PRODE D06", "groups": [{"fps": 24, "takes": []}]})
    pedido = {"job_id": jid, "proxies": {"/c.mov": "/p.mov"}}
    visto = {}

    def escrever(p):
        visto.update(p)
        return {"arquivo": p["output_path"], "merged": 11, "bins": {"NAO RESOLVIDO": 11}}
    assert S.api_enfileirar_merged(pedido, escrever).status == 412 and not visto
    tb.marcar_presenca("premiere")
    assert S.api_enfileirar_merged(pedido, escrever).status == 200
    assert visto["proxies"]["/c.mov"] == "/p.mov" and visto["raiz"] == "CENAS"
    saida = visto["output_path"]
    assert saida.endswith("PRODE D06 MERGED.prproj") and Path(saida).parent.is_dir()
    job = tb.pegar_job("premiere")
    assert job["tipo"] == "merged" and job["arquivo"] == saida
    Path(saida).parent.rmdir()


def test_o_merged_sem_tomada_nao_vai_para_a_fila():
    tb.marcar_presenca("premiere")
    jid = _job_pronto({"groups": []})
    nada = lambda p: {"merged": 0, "bins": {}}  # noqa: E731
    assert S.api_enfileirar_merged({"job_id": jid}, nada).status == 422
    assert tb.pegar_job("premiere") is None
    assert S.api_enfileirar_merged({"job_id": "x"}, nada).status == 410


def test_a_ponte_recusa_o_sync_que_nao_serve():
    tb.marcar_presenca("premiere")
    assert S.api_enfileirar_montagem({"job_id": "sumiu"}).status == 410
    assert S.api_enfileirar_montagem({}).status == 400
    rodando = tb.reservar("x")
    assert S.api_enfileirar_montagem({"job_id": rodando}).status == 409
    tb.terminou_bem(rodando, {"fps": 24, "takes": []})
    assert S.api_enfileirar_montagem({"job_id": rodando}).status == 200
    job = tb.pegar_job("premiere")
    assert len(job["map"]["groups"]) == 1 and job["map"]["groups"][0]["fps"] == 24


def test_o_sync_que_falhou_diz_o_erro():
    tb.marcar_presenca("premiere")
    jid = _job_pronto(None, erro="arquivo não encontrado")
    r = S.api_enfileirar_montagem({"job_id": jid})
    assert r.status == 409 and _corpo(r)["error"] == "arquivo não encontrado"


# ── a ponte do Premiere ──

def test_so_funcoes_nossas_viram_expressao():
    assert ponte.expressao("sincEstado", []) == "sincEstado()"
    assert ponte.expressao("sincImport", ["D:\\a b\\x.prproj", 3]) == 'sincImport("D:\\\\a b\\\\x.prproj", 3)'
    for mau in ["app.quit", "sincX);app.quit(", "eval", "", "sinc\n"]:
        try:
            ponte.expressao(mau, [])
            raise AssertionError(mau)
        except ValueError:
            pass


def test_acento_vira_escape_ascii():
    assert ponte.expressao("sincX", ["Órbita"]) == 'sincX("\\u00d3rbita")'
    assert ponte.expressao("sincX", ["🎬"]) == 'sincX("\\ud83c\\udfac")', "par substituto, como o encode_utf16"


def test_a_volta_completa_pelo_nucleo(monkeypatch):
    # ⭐ Fase 4: o pedido vai ao núcleo do Ciclo Assist (a ponte única) e o resultado espera quem pediu
    feitos = []
    monkeypatch.setattr(ponte, "_chamar_no_nucleo", lambda f, a: feitos.append((f, a)) or "ok")
    i = ponte.enfileirar("sincTeste", [1])
    for _ in range(100):
        if ponte.resultado(i) != (False, None):
            break
        time.sleep(0.01)
    assert feitos == [("sincTeste", [1])]
    i2 = ponte.enfileirar("sincTeste", [2])
    for _ in range(100):
        r = ponte.resultado(i2)
        if r != (False, None):
            break
        time.sleep(0.01)
    assert r == (True, "ok") and ponte.resultado(i2) is None


def test_nucleo_fora_vira_err_que_a_pagina_mostra(monkeypatch, tmp_path):
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path))  # sem token publicado
    i = ponte.enfileirar("sincAcorda", [])
    for _ in range(200):
        r = ponte.resultado(i)
        if r != (False, None):
            break
        time.sleep(0.01)
    assert r[0] is True and r[1].startswith("err|") and "Ciclo Assist" in r[1]
    assert ponte.viva() is False
