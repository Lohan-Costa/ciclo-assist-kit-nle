"""As funções puras das rotas (testes do `httpserver.rs` portados) e o servidor de verdade, numa porta de teste."""
import json
import threading
import urllib.error
import urllib.request
from pathlib import Path

import pytest

import paginas
import ponte
import segredo
import servidor as S
import trabalhos as tb


def test_traduz_clips_para_files():
    p = S.build_sync_params({"clips": [{"path": "/x/cam.mov"}, {"path": "/x/som.wav", "kind": "sound"}],
                             "method": "waveform", "fps": 24})
    f = p["files"]
    assert len(f) == 2 and f[0]["path"] == "/x/cam.mov" and f[0]["group_id"] == "/x/cam.mov"
    assert "kind" not in f[0] and f[1]["kind"] == "sound"
    assert p["sync_method"] == "waveform" and p["fps"] == 24


def test_a_base_de_cronologia_e_repassada_e_e_opcional():
    com = S.build_sync_params({"clips": [{"path": "/a.mov", "group": "CAM A", "chronology": "timecode"}]})
    assert com["files"][0]["chronology"] == "timecode"
    sem = S.build_sync_params({"clips": [{"path": "/a.mov", "group": "CAM A"}]})
    assert "chronology" not in sem["files"][0]


def test_group_e_group_order_para_cronologia():
    f = S.build_sync_params({"clips": [{"path": "/B/1.mov", "group": "CAM B", "group_order": 0},
                                       {"path": "/B/2.mov", "group": "CAM B", "group_order": 1}]})["files"]
    assert [x["group_id"] for x in f] == ["CAM B", "CAM B"] and [x["group_order"] for x in f] == [0, 1]


def test_defaults_e_vazio():
    p = S.build_sync_params({"clips": [{"path": "/a.mov"}]})
    assert p["sync_method"] == "hybrid" and p["fps"] is None
    assert S.build_sync_params({"clips": []}) is None and S.build_sync_params({}) is None
    assert S.build_sync_params({"clips": [{"path": 3}, "x"]}) is None


def test_temp_path_higieniza_o_nome():
    nome = Path(S.temp_prproj_path("../A VIDA/de cada:um")).name
    assert nome.startswith("sincronizar_") and nome.endswith(".prproj")
    assert not any(c in nome for c in "/\\:") and ".." not in nome
    assert "sincronizar_sincronizar_" in S.temp_prproj_path("")


def test_query_param_extrai_e_decodifica():
    assert S.query_param("/prproj/status?id=job_1_2", "id") == "job_1_2"
    assert S.query_param("/prproj/status?a=1&id=xyz", "id") == "xyz"
    assert S.query_param("/x?id=a%20b+c", "id") == "a b c"
    assert S.query_param("/prproj/status", "id") is None and S.query_param("/x?other=1", "id") is None


def test_montar_avid_nao_embrulha_o_envelope_de_novo():
    p = S.montar_avid_params({"result": {"name": "x", "groups": [{"fps": 25.0, "name": "y"}]},
                              "name": "teste dentro do MC", "start_tc_frames": 86400,
                              "mob_ids": {"/a.mov": "abc"}, "mob_lengths": {"/a.mov": 240}})
    gs = p["result"]["groups"]
    assert len(gs) == 1 and gs[0]["fps"] == 25.0 and gs[0]["name"] == "teste dentro do MC"
    assert gs[0]["start_tc_frames"] == 86400 and p["result"]["name"] == "teste dentro do MC"
    assert p["mob_ids"]["/a.mov"] == "abc" and p["mob_lengths"]["/a.mov"] == 240
    assert p["options"]["include_camera_audio"] is False


def test_montar_avid_com_varias_diarias_nao_renomeia_todas():
    p = S.montar_avid_params({"result": {"groups": [{"fps": 25.0, "name": "DIA 1"}, {"fps": 25.0, "name": "DIA 2"}]},
                              "name": "MEU PROJETO"})
    assert [g["name"] for g in p["result"]["groups"]] == ["DIA 1", "DIA 2"]
    assert p["result"]["name"] == "MEU PROJETO"


def test_montar_avid_aceita_diaria_solta_sem_envelope():
    p = S.montar_avid_params({"result": {"fps": 24.0, "camera_groups": []}, "name": "SOLTA", "start_tc_frames": 100})
    assert p["result"]["fps"] == 24.0 and p["result"]["name"] == "SOLTA" and p["result"]["start_tc_frames"] == 100
    assert "groups" not in p["result"]


def test_montar_avid_sem_resultado_e_recusado_antes_do_sidecar():
    for e in ({}, {"result": None}, {"result": "texto"}, {"result": [1, 2]}):
        assert S.montar_avid_params(e) is None


def test_montar_avid_tem_nome_padrao_e_respeita_o_audio_de_camera():
    assert S.montar_avid_params({"result": {"groups": [{}]}})["result"]["groups"][0]["name"] == "Sincronizar"
    assert S.montar_avid_params({"result": {"groups": [{}]}, "name": "   "})["result"]["groups"][0]["name"] == "Sincronizar"
    assert S.montar_avid_params({"result": {}, "include_camera_audio": True})["options"]["include_camera_audio"]


def test_montar_avid_nao_mexe_no_resultado_guardado():
    r = {"groups": [{"name": "A"}]}
    S.montar_avid_params({"result": r, "name": "B"})
    assert r == {"groups": [{"name": "A"}]}, "o job guardado não pode mudar por baixo de quem o pedir de novo"


def test_a_pasta_pega_as_bins_de_dentro_sem_caixa():
    arvore = ["D02/CAM A", "D02/SOM DIRETO", "D02/EXTRA/CAM B", "D020/CAM A", "D01/CAM A", "ORBITA DEMO D02"]
    assert S.bins_da_pasta(arvore, "d02") == ["D02/CAM A", "D02/SOM DIRETO", "D02/EXTRA/CAM B"]
    assert len(S.bins_da_pasta(arvore, "D02\\")) == 3
    assert S.bins_da_pasta(arvore, "ORBITA DEMO D02") == ["ORBITA DEMO D02"]
    assert S.bins_da_pasta(arvore, "  ") == []
    assert S.nome_real_da_pasta(S.bins_da_pasta(arvore, "d02"), "d02") == "D02"
    assert S.nome_real_da_pasta(S.bins_da_pasta(arvore, "d02/extra"), "d02/extra") == "D02/EXTRA"
    assert S.nome_real_da_pasta([], "d02") == "d02"


def test_as_fontes_viram_clipes_como_no_painel():
    clips, rot = S.clipes_das_fontes([
        {"label": "CAM A", "kind": "camera", "files": ["/m/a1.mp4", "/m/a2.mp4"]},
        {"label": "SOM DIRETO", "kind": "sound", "files": ["/m/s1.wav"]},
        {"label": "CAM A", "kind": "camera", "files": ["/n/a1.mp4"]}])
    assert rot == ["CAM A", "SOM DIRETO", "CAM A 2"] and len(clips) == 4
    assert clips[1]["group_order"] == 1 and clips[2]["kind"] == "sound" and "kind" not in clips[0]
    assert clips[3]["group"] == "CAM A 2"
    p = S.build_sync_params({"clips": clips, "method": "hybrid"})
    assert len(p["files"]) == 4 and p["files"][2]["kind"] == "sound"


def test_a_ui_injeta_o_dicionario_uma_vez_so():
    assert paginas.montar_ui("<a><!--SINC_I18N--></a>", "X;") == "<a><script>\nX;</script></a>"
    for ruim in ("<a></a>", "<!--SINC_I18N--><!--SINC_I18N-->"):
        with pytest.raises(RuntimeError):
            paginas.montar_ui(ruim, "X")
    js = paginas.js_dos_dicionarios('{"b":"</script>","a":"é"}', '{"x":1}')
    assert 'window.SINC_I18N = {"en":{"x":1},"pt-BR":{"a":"é","b":"<\\/script>"}};' in js


def test_health_nao_entrega_o_caminho_do_executavel():
    fonte = Path(S.__file__).read_text(encoding="utf-8")
    assert '"exe"' not in fonte


# ── o servidor de verdade ─────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def no_ar():
    srv = S.Servidor(("127.0.0.1", 0), S._Atendente)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv.server_address[1]
    srv.shutdown()


def pedir(porta, metodo, rota, corpo=None, token=True, cab=None):
    h = {"Content-Type": "application/json"}
    if token:
        h[segredo.HEADER] = segredo.token()
    h.update(cab or {})
    dados = corpo if isinstance(corpo, bytes) else (json.dumps(corpo).encode() if corpo is not None else None)
    req = urllib.request.Request(f"http://127.0.0.1:{porta}{rota}", data=dados, method=metodo, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, dict(r.headers), r.read()
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read()


def js(t):
    return json.loads(t[2])


def test_sem_token_nada_passa_nem_o_health(no_ar):
    st, h, b = pedir(no_ar, "GET", "/health", token=False)
    assert st == 401 and json.loads(b) == {"error": "token ausente ou inválido"}
    assert h.get("Access-Control-Allow-Origin") == "*", "o painel legítimo lê o motivo para reler o token"


def test_pagina_web_nem_le_o_motivo(no_ar):
    st, h, _ = pedir(no_ar, "GET", "/health", token=False, cab={"Origin": "https://site.example"})
    assert st == 403 and "Access-Control-Allow-Origin" not in h


def test_health_e_preflight(no_ar):
    st, _, b = pedir(no_ar, "GET", "/health?nle=resolve")
    assert st == 200 and json.loads(b) == {"ok": True, "app": "sincronizar", "version": S.VERSAO, "busy": False}
    assert tb.ouvindo("resolve")
    assert pedir(no_ar, "OPTIONS", "/syncmap", token=False)[0] == 200


def test_rota_e_caminho_exato(no_ar):
    assert pedir(no_ar, "GET", "/healthFOO")[0] == 404
    assert pedir(no_ar, "GET", "/health/")[0] == 404


def test_o_que_era_do_studio_diz_por_que_saiu(no_ar):
    for r in ("/open", "/sync", "/prproj", "/dailies", "/splitresult", "/app/studio"):
        st, _, b = pedir(no_ar, "POST", r, {})
        assert st == 410 and json.loads(b)["aposentada"] is True, r


def test_status_de_job(no_ar):
    assert pedir(no_ar, "GET", "/prproj/status")[0] == 400
    assert pedir(no_ar, "GET", "/prproj/status?id=nada")[0] == 404
    j = tb.reservar("x")
    tb.terminou_bem(j, {"a": 1})
    st, _, b = pedir(no_ar, "GET", f"/prproj/status?id={j}")
    assert st == 200 and json.loads(b)["state"] == "done" and json.loads(b)["result"] == {"a": 1}


def test_com_job_rodando_o_motor_esta_ocupado(no_ar):
    tb.reservar("x")
    assert js(pedir(no_ar, "GET", "/health"))["busy"] is True
    st, _, b = pedir(no_ar, "GET", "/settings")
    assert st == 409 and json.loads(b) == {"error": "ocupado", "busy": True}
    st, _, b = pedir(no_ar, "POST", "/avid/bins", {})
    assert st == 409 and "job_id" in json.loads(b)


def test_a_ponte_pela_rota(no_ar, monkeypatch):
    st, _, b = pedir(no_ar, "POST", "/premiere/chamar", {"funcao": "sincEstado", "args": []})
    assert st == 409, "sem a ponte viva, nem entra na fila"
    monkeypatch.setattr(ponte, "viva", lambda: True)
    pedidos = []
    monkeypatch.setattr(ponte, "_chamar_no_nucleo", lambda f, a: pedidos.append((f, a)) or "feito")
    assert pedir(no_ar, "POST", "/premiere/chamar", {"funcao": "app.quit", "args": []})[0] == 400
    i = js(pedir(no_ar, "POST", "/premiere/chamar", {"funcao": "sincEstado", "args": ["é"]}))["id"]
    import time as _t
    for _ in range(100):
        r = js(pedir(no_ar, "GET", f"/premiere/resultado?id={i}"))
        if r.get("pronto"):
            break
        _t.sleep(0.01)
    assert r == {"pronto": True, "r": "feito"} and pedidos == [("sincEstado", ["é"])]
    assert pedir(no_ar, "GET", f"/premiere/resultado?id={i}")[0] == 404
    for rota in ("/premiere/pedido", "/premiere/ponte.js", "/premiere/host.jsx"):
        st, _, b = pedir(no_ar, "GET", rota)
        assert st == 410 and json.loads(b)["aposentada"] is True, rota
    c = js(pedir(no_ar, "GET", "/conexao"))
    assert c["premiere"] is True and c["programa"] == "premiere"


def test_a_api_v1(no_ar):
    i = js(pedir(no_ar, "GET", "/api/v1/info"))
    assert i["capacidades"] == ["sincronizar", "montar", "merged", "avid_sincronizar"] and i["motor"] == "python"
    assert pedir(no_ar, "GET", "/api/v1/montagem")[0] == 400
    assert pedir(no_ar, "GET", "/api/v1/montagem?id=x")[0] == 404
    assert pedir(no_ar, "POST", "/api/v1/nlejob", {})[0] == 400
    st, _, b = pedir(no_ar, "POST", "/nlejob/done", {"id": "nada", "ok": True})
    assert st == 200 and json.loads(b) == {"ok": True}
    assert js(pedir(no_ar, "GET", "/nlejob?nle=avid")) == {}
    assert tb.ouvindo("avid")


def test_os_campos_que_faltam_sao_ditos(no_ar):
    for rota, erro in [("/avid/mobs", "faltou mob_ids"), ("/avid/renomear/ler", "faltou mob_ids"),
                       ("/avid/nome/prever", "faltaram fichas"), ("/avid/renomear/aplicar", "faltou levantamento_id"),
                       ("/avid/timeline", "faltou mob_id"), ("/avid/subclipes/ler", "faltou bin"),
                       ("/avid/subclipes/prever", "faltou leitura_id"), ("/avid/subclipes/gerar", "faltou leitura_id"),
                       ("/premiere/merged/ler", "faltou a sequência"), ("/premiere/merged/gerar", "faltou leitura_id"),
                       ("/avid/montar", "faltou o resultado do sync"), ("/syncmap", "nenhum clipe"),
                       ("/folder/open", "pasta desconhecida"), ("/link/open", "link desconhecido")]:
        st, _, b = pedir(no_ar, "POST", rota, {})
        assert (st, json.loads(b)) == (400, {"error": erro}), rota


def test_a_primeira_carga_da_ui_e_html(no_ar):
    if paginas.pasta_da_pagina() is None:
        pytest.skip("os arquivos da Preparar não estão nesta máquina")
    st, h, b = pedir(no_ar, "GET", "/avid/panel?casca=app&embutido=1", token=False)
    assert st == 200 and h["Content-Type"].startswith("text/html") and h["Cache-Control"] == "no-store"
    assert b"window.SINC_I18N" in b and b"<!--SINC_I18N-->" not in b
    # ⭐ Fase 4: a página da ponte própria saiu (410) — quem carrega o `host.jsx` do Sincronizar é a ponte do Assist
    assert pedir(no_ar, "GET", "/premiere/ponte", token=False)[0] == 410
    assert pedir(no_ar, "GET", "/premiere/host.jsx", token=False)[0] == 401, "o portão continua antes de tudo"
    assert b"function sinc" in (paginas.PAGINA / "host.jsx").read_bytes()


def test_o_motor_usa_o_ffmpeg_fixado():
    """⛔ O 8.1.1 do Homebrew deu outra `confidence` que o 8.1.2 fixado do Órbita (medido em 2026-11-07)."""
    import motor
    if not motor.BINARIOS.is_dir():
        pytest.skip("sem modulos/sincronizar/binarios nesta máquina")
    for nome in ("ffmpeg", "ffprobe"):
        assert motor._achar(nome) == motor.fixado(nome) and motor.fixado(nome)


def test_o_arrasto_do_mac_sem_identidade_e_recusado_com_a_frase(no_ar):
    # ⭐ 2026-11-07: o arrasto do MC no Mac só traz MobIDs; sem um válido, a recusa diz por quê (sem tocar no MC)
    st, _, b = pedir(no_ar, "POST", "/arrasto/mc", {"mob_ids": ["curto", 3]}, cab={"Sec-Fetch-Site": "same-origin"})
    assert st == 200 and json.loads(b) == {"ok": False, "erro": "o arrasto do Media Composer não trouxe identidade"}


def test_a_pagina_mora_no_modulo_e_sem_o_botao_do_studio():
    # ⭐ 2026-11-07: a página do Sincronizar mora no módulo (copiada do Órbita d57904e) e o Studio saiu dela
    base = paginas.pasta_da_pagina()
    assert base is not None and base.parts[-2:] == ("sincronizar", "pagina"), base
    html = (base / "painel.html").read_text(encoding="utf-8")
    assert "btStudio" not in html and "/app/studio" not in html
    assert '"/arrasto/mc"' in html, "a página pergunta a espécie do arrasto do Mac"
    assert '$("tabSources").textContent = "Órbita"' not in html, "a subaba é Sincronizar (o nome da função)"


def test_a_camera_em_duas_bins_e_uma_fonte_so():
    fontes = S.fontes_declaradas([{"tipo": "camera", "nome": "CAM A", "bins": ["D1 CARTAO 1", "D1 CARTAO 2"]},
                                  {"tipo": "som", "bins": ["D1 SOM"]}])
    lidas = {"D1 CARTAO 1": {"sources": [{"files": ["a1"]}], "mob_ids": {"a1": "m1"}},
             "D1 CARTAO 2": {"sources": [{"files": ["a2"]}], "mob_ids": {"a2": "m2"}, "missing": ["x"]},
             "D1 SOM": {"sources": [{"files": ["s1"]}], "name": "D1"}}

    def ler(bins):
        juntas = {"sources": [], "missing": [], "mob_ids": {}}
        for b in bins:
            juntas["sources"] += lidas[b]["sources"]
            juntas["missing"] += lidas[b].get("missing", [])
            juntas["mob_ids"].update(lidas[b].get("mob_ids", {}))
            if "name" in lidas[b]:
                juntas["name"] = lidas[b]["name"]
        return juntas

    sel = S.fundir_selecoes(fontes, ler)
    assert [(f["kind"], f["label"], f["files"]) for f in sel["sources"]] == [
        ("camera", "CAM A", ["a1", "a2"]), ("sound", "SOM DIRETO", ["s1"])]
    assert sel["mob_ids"] == {"a1": "m1", "a2": "m2"} and sel["missing"] == ["x"] and sel["name"] == "D1"


def test_fonte_sem_tipo_ou_sem_bin_e_recusada():
    assert S.fontes_declaradas([{"tipo": "camera"}]) is None
    assert S.fontes_declaradas([{"bins": ["x"]}]) is None
    assert S.fontes_declaradas([]) is None
