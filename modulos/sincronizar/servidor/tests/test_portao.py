"""Os testes do portão do `httpserver.rs` (`d57904e`) portados um a um — os nomes são os do Rust."""
import portao as P
import segredo

PORTA = 7817
H = "127.0.0.1:7817"
TOK = segredo.token()


def pf(host, origin, fetch, token, body, rota):
    return P.portao(host, origin, fetch, token, body, rota, porta=PORTA, token_confere=segredo.confere)


def pt(host, origin, token, body, rota):
    return pf(host, origin, None, token, body, rota)


def comum(host, origin, token, body):
    return pt(host, origin, token, body, "/sync")


def test_o_painel_legitimo_entra():
    assert comum(H, None, TOK, 120) is None
    assert comum("localhost:7817", None, TOK, None) is None


def test_painel_do_avid_entra_pela_origem_sem_token():
    for rota in P.ROTAS_DO_PAINEL_AVID:
        assert pt(H, "avpi://", None, 10, rota) is None, rota


def test_painel_do_avid_nao_alcanca_as_rotas_pesadas():
    for rota in ["/sync", "/sources", "/prproj", "/dailies", "/cache/clear", "/folder/open", "/open",
                 "/avid/renomear/ler", "/avid/nome/prever", "/avid/renomear/aplicar", "/avid/renomear/desfazer",
                 "/avid/renomear/historico", "/avid/timeline", "/avid/subclipes/ler", "/avid/subclipes/gerar",
                 "/avid/subclipes/cena", "/avid/subclipes/remover", "/avid/subclipes/prever",
                 "/premiere/merged/ler", "/premiere/merged/gerar", "/premiere/renomear/ler",
                 "/premiere/renomear/plano", "/premiere/renomear/desfazer", "/premiere/renomear/fim"]:
        assert pt(H, "avpi://", None, 10, rota) == P.SEM_TOKEN, rota


def test_origem_parecida_com_a_do_painel_nao_entra():
    for falsa in ["avpi://outro", "avpi:/", "avpi", "javpi://", "avpi://x.example"]:
        assert pt(H, falsa, None, 10, "/health") == P.SEM_TOKEN, falsa


def test_site_nao_vira_painel_do_avid_escolhendo_a_rota():
    assert pt(H, "https://site.example", None, 10, "/health") == P.ORIGEM_WEB


def test_o_painel_servido_entra_como_ele_realmente_chama():
    for rota in ["/health", "/settings", "/cache/clear", "/folder/open", "/sources", "/sync"]:
        assert pf(H, None, "same-origin", None, 10, rota) is None, rota


def test_cross_site_nao_e_same_origin():
    for valor in ["cross-site", "same-site", "none", "", "SAME_ORIGIN", "same-origin-ish"]:
        assert pf(H, None, valor, None, 10, "/sync") == P.SEM_TOKEN, valor


def test_same_origin_nao_escapa_do_resto_do_portao():
    assert pf("dominio-do-atacante.example", None, "same-origin", None, None, "/sync") == P.HOST_NAO_LOCAL
    assert pf(H, None, "same-origin", None, P.MAX_BODY_BYTES + 1, "/sync") == P.CORPO_GRANDE


def test_site_com_origem_web_cai_mesmo_mentindo_o_fetch_site():
    assert pf(H, "https://site.example", "same-origin", None, 10, "/sync") == P.ORIGEM_WEB


def test_a_ui_servida_alcanca_as_mesmas_rotas_dos_outros_paineis():
    for rota in ["/health", "/sync", "/sources", "/syncmap", "/prproj", "/dailies", "/cache/clear",
                 "/folder/open", "/open", "/settings", "/nlejob", "/avid/renomear/ler", "/avid/subclipes/prever"]:
        for origem in ["http://127.0.0.1:7817", "http://localhost:7817"]:
            assert pt(H, origem, None, 10, rota) is None, (rota, origem)


def test_origem_quase_a_nossa_nao_entra():
    for falsa in ["http://127.0.0.1:7818", "http://127.0.0.1", "https://127.0.0.1:7817",
                  "http://127.0.0.1:7817.example", "http://evil.com/127.0.0.1:7817", "http://127.0.0.1:78170",
                  "http://localhost", "http://127.0.0.1:7817@evil.com"]:
        assert pt(H, falsa, None, 10, "/sync") == P.ORIGEM_WEB, falsa


def test_a_primeira_carga_da_ui_entra_sem_credencial_nenhuma():
    assert pt(H, None, None, None, P.ROTA_UI_PAINEL_AVID) is None
    assert pt(H, None, None, None, P.ROTA_PONTE_PREMIERE) is None


def test_a_carga_livre_vale_so_para_a_rota_da_ui():
    for rota in ["/sync", "/sources", "/cache/clear", "/open", "/health", "/premiere/host.jsx",
                 "/premiere/ponte.js", "/premiere/pedido", "/premiere/chamar", "/avid/subclipes/gerar"]:
        assert pt(H, None, None, None, rota) == P.SEM_TOKEN, rota


def test_a_ui_servida_nao_escapa_do_resto_do_portao():
    assert pt("dominio-do-atacante.example", "http://127.0.0.1:7817", None, None, "/sync") == P.HOST_NAO_LOCAL
    assert pt(H, "http://127.0.0.1:7817", None, P.MAX_BODY_BYTES + 1, "/sync") == P.CORPO_GRANDE
    assert pt(H, None, None, P.MAX_BODY_BYTES + 1, P.ROTA_UI_PAINEL_AVID) == P.CORPO_GRANDE


def test_e_origem_propria_normaliza_o_que_o_navegador_manda():
    for o in ["http://127.0.0.1:7817", "HTTP://127.0.0.1:7817", " http://127.0.0.1:7817 ",
              "http://127.0.0.1:7817/", "http://localhost:7817"]:
        assert P.e_origem_propria(o, PORTA), o
    assert not P.e_origem_propria("avpi://", PORTA)
    assert not P.e_origem_propria("", PORTA)


def test_o_painel_do_avid_ainda_precisa_falar_com_o_host_local():
    assert pt("dominio-do-atacante.example", "avpi://", None, None, "/health") == P.HOST_NAO_LOCAL
    assert pt("127.0.0.1", "avpi://", None, P.MAX_BODY_BYTES + 1, "/health") == P.CORPO_GRANDE


def test_pagina_web_qualquer_nao_entra_nem_com_host_certo():
    assert comum(H, "https://site-malicioso.example", None, 10) == P.ORIGEM_WEB
    assert comum(H, None, None, 10) == P.SEM_TOKEN


def test_token_errado_ou_pela_metade_nao_entra():
    for t in ["", "abc", TOK[:32], TOK + "0", TOK.upper() if TOK.upper() != TOK else "x"]:
        assert comum("127.0.0.1", None, t, None) == P.SEM_TOKEN, t


def test_dns_rebinding_continua_barrado():
    assert comum("dominio-do-atacante.example", None, TOK, None) == P.HOST_NAO_LOCAL
    assert comum(None, None, TOK, None) == P.HOST_NAO_LOCAL


def test_host_nao_passa_por_parecido():
    assert comum("localhost.atacante.example", "https://x.example", TOK, None) == P.HOST_NAO_LOCAL
    assert pf("localhost.atacante.example", None, "same-origin", None, None, "/settings") == P.HOST_NAO_LOCAL


def test_corpo_gigante_e_recusado_antes_de_alocar():
    assert comum("127.0.0.1", None, TOK, P.MAX_BODY_BYTES + 1) == P.CORPO_GRANDE
    assert comum("127.0.0.1", None, TOK, P.MAX_BODY_BYTES) is None


def test_quem_nao_se_identifica_nem_tem_o_corpo_olhado():
    assert comum("127.0.0.1", None, None, P.MAX_BODY_BYTES + 1) == P.SEM_TOKEN


def test_a_recusa_certa_tem_o_status_certo():
    assert P.SEM_TOKEN[0] == 401 and P.ORIGEM_WEB[0] == 403 and P.HOST_NAO_LOCAL[0] == 403
    assert P.CORPO_GRANDE[0] == 413


def test_a_porta_e_a_do_servidor_que_pergunta():
    """⭐ Novo (o Rust tinha a 7817 fixa): numa porta de teste, a origem e o Host são os DELA."""
    assert P.portao("127.0.0.1:7827", "http://127.0.0.1:7827", None, None, 1, "/sync", porta=7827,
                    token_confere=segredo.confere) is None
    assert P.portao("127.0.0.1:7817", None, None, TOK, 1, "/sync", porta=7827,
                    token_confere=segredo.confere) == P.HOST_NAO_LOCAL


def test_o_token_e_o_unico_do_ciclo_assist_e_e_relido(tmp_path, monkeypatch):
    # ⭐ Fase 4 (2026-11-07): quem sorteia é o núcleo do Ciclo Assist; o Sincronizar confere o arquivo dele
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path))
    p = tmp_path / "plugin-token"
    assert segredo.publicar() == p and not segredo.confere("x"), "sem o arquivo ninguém entra"
    p.write_text("a" * 64, encoding="utf-8")
    assert segredo.confere("a" * 64)
    import os as _os
    p.write_text("b" * 64, encoding="utf-8")
    _os.utime(p, (p.stat().st_atime, p.stat().st_mtime + 5))   # o Assist reiniciou
    assert segredo.confere("b" * 64) and not segredo.confere("a" * 64)


def test_a_migracao_da_pasta_do_orbita_copia_so_o_que_falta(tmp_path):
    # ⭐ Fase 3 (2026-11-07): as escolhas e o desfazer do Renomear vêm de …/Orbita; o que já existe na nova fica
    import segredo
    antiga, nova = tmp_path / "Orbita", tmp_path / "CicloAssist" / "sincronizar"
    (antiga / "renomeacoes").mkdir(parents=True)
    (antiga / "renomeacoes" / "lote.json").write_text("{}", encoding="utf-8")
    (antiga / "settings.json").write_text('{"locale": "en"}', encoding="utf-8")
    (antiga / "plugin-token").write_text("velho", encoding="utf-8")
    assert segredo.migrar_da_pasta_antiga(antiga, nova) == ["settings.json", "renomeacoes"]
    assert (nova / "renomeacoes" / "lote.json").is_file() and not (nova / "plugin-token").exists()
    (nova / "settings.json").write_text('{"locale": "pt-BR"}', encoding="utf-8")
    assert segredo.migrar_da_pasta_antiga(antiga, nova) == []
    assert "pt-BR" in (nova / "settings.json").read_text(encoding="utf-8")
    assert (antiga / "settings.json").is_file(), "copia, nunca move"
    assert segredo.migrar_da_pasta_antiga(tmp_path / "nao-existe", nova) == []


def test_a_pasta_do_modulo_mora_no_ciclo_assist(monkeypatch, tmp_path):
    import segredo
    monkeypatch.delenv("SINCRONIZAR_DADOS", raising=False)
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path))
    assert segredo.pasta_de_dados() == tmp_path / "sincronizar"
    assert segredo.HEADER == "X-Ciclo-Token"
