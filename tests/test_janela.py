"""A janela de contexto que sobrevive ao modelo novo, ao reinício e ao Reload."""
from __future__ import annotations

from cicloassist.motor import claude as C


def test_a_janela_aprendida_e_GRAVADA(tmp_path, monkeypatch):
    """⭐⭐ Era memória de processo: o editor trocava de modelo e a barra sumia."""
    gravado = {}
    monkeypatch.setattr(C._config, "gravar_estado", lambda m: gravado.update(m))
    monkeypatch.setattr(C, "_JANELAS", {})
    monkeypatch.setattr(C, "_ULTIMO_CONTEXTO", {"m": 50_000})
    list(C._traduzir({"type": "result", "modelUsage": {
        "m": {"contextWindow": 200_000, "inputTokens": 1}}}))
    assert gravado["janelas"]["m"] == 200_000


def test_o_primeiro_turno_de_um_modelo_NOVO_ja_mostra_a_barra(monkeypatch):
    """⛔ MEDIDO em campo: ele trocou para Haiku e a barra não apareceu o turno inteiro,
    porque a janela só chega no `result` e só era lida no turno SEGUINTE."""
    monkeypatch.setattr(C._config, "gravar_estado", lambda m: None)
    monkeypatch.setattr(C, "_JANELAS", {})
    monkeypatch.setattr(C, "_ULTIMO_CONTEXTO", {"m": 50_000})
    usos = [d for t, d in C._traduzir({"type": "result", "modelUsage": {
        "m": {"contextWindow": 200_000, "inputTokens": 1}}}) if t == "uso"]
    assert usos and usos[0]["fracao"] == 0.25


def test_janela_ja_conhecida_nao_regrava_nem_reemite(monkeypatch):
    """⚠️ Sem isto, todo turno gravaria o estado e reemitiria `uso` de graça."""
    chamou = []
    monkeypatch.setattr(C._config, "gravar_estado", lambda m: chamou.append(m))
    monkeypatch.setattr(C, "_JANELAS", {"m": 200_000})
    monkeypatch.setattr(C, "_ULTIMO_CONTEXTO", {"m": 50_000})
    eventos = list(C._traduzir({"type": "result", "modelUsage": {
        "m": {"contextWindow": 200_000, "inputTokens": 1}}}))
    assert not chamou
    assert not [d for t, d in eventos if t == "uso"]


def test_o_ao_vivo_usa_a_janela_aprendida(monkeypatch):
    monkeypatch.setattr(C, "_JANELAS", {"m": 1_000_000})
    (tipo, dado), = C._traduzir({"type": "stream_event", "event": {
        "type": "message_start",
        "message": {"model": "m", "usage": {"input_tokens": 250_000}}}})
    assert tipo == "uso" and dado["fracao"] == 0.25


def test_modelo_do_mac_nao_tem_dolar_nem_a_janela_que_o_CLI_inventa(monkeypatch):
    """⛔⛔ MEDIDO em 2026-09-16: para o Ollama o CLI diz `contextWindow: 200000` e um
    `costUSD` de Sonnet. O Mac carregou 40.960 e não cobra."""
    monkeypatch.setattr(C._config, "gravar_estado", lambda m: None)
    monkeypatch.setattr(C, "_JANELAS", {})
    monkeypatch.setattr(C, "_ULTIMO_CONTEXTO", {"qwen3-vl:8b-instruct": 10_240})
    monkeypatch.setattr(C, "_janela_do_mac", lambda m: 40_960)
    eventos = list(C._traduzir({"type": "result", "modelUsage": {"qwen3-vl:8b-instruct": {
        "contextWindow": 200_000, "inputTokens": 10_240, "outputTokens": 60,
        "costUSD": 0.0048, "costBasis": "unknown"}}}))
    gasto = [d for t, d in eventos if t == "gasto"][0]
    assert gasto["custo_usd"] is None and gasto["tokens"] == 10_300
    uso = [d for t, d in eventos if t == "uso"][0]
    assert uso["janela"] == 40_960 and uso["fracao"] == 0.25


def test_o_pedido_de_ferramenta_sendo_escrito_aparece_no_painel():
    """⛔⛔ MEDIDO em 2026-09-16: 10 min de "pensando…" com o modelo escrevendo o pedido de
    uma ferramenta — os `input_json_delta` eram descartados."""
    ev = lambda interno: {"type": "stream_event", "event": interno}  # noqa: E731
    saidas = list(C._traduzir(ev({"type": "content_block_start", "content_block": {
        "type": "tool_use", "name": "mcp__ciclo__separar_falas"}})))
    assert saidas == [("progresso", {"etapa": "escrevendo o pedido de separar falas",
                                     "fracao": None})]
    etapas = []
    for _ in range(30):
        etapas += [d["etapa"] for t, d in C._traduzir(ev({
            "type": "content_block_delta",
            "delta": {"type": "input_json_delta", "partial_json": "x" * 100}}))
            if t == "progresso"]
    # 3.000 caracteres, um aviso a cada 400: sete, e o último diz o tamanho.
    assert len(etapas) == 7
    assert etapas[-1] == "escrevendo o pedido de separar falas · 2,8 mil caracteres"


def test_a_falha_do_servidor_que_o_CLI_repete_aparece_no_painel():
    """⛔⛔ MEDIDO em 2026-09-16: `500 unexpected end of JSON input` a cada ~4 min, até 10
    vezes, com o painel em "pensando…"."""
    etapas = [d["etapa"] for t, d in C._traduzir({
        "type": "system", "subtype": "api_retry", "attempt": 2, "max_retries": 10,
        "error_status": 500, "error": "unexpected end of JSON input"}) if t == "progresso"]
    assert etapas == ["o servidor do modelo falhou: unexpected end of JSON input"
                      " — tentando de novo (2 de 10)"]
    etapas = [d["etapa"] for t, d in C._traduzir({
        "type": "system", "subtype": "api_error", "retryAttempt": 1, "maxRetries": 10,
        "error": {"formatted": "500 unexpected end of JSON input"}}) if t == "progresso"]
    assert "(1 de 10)" in etapas[0] and "500" in etapas[0]


def test_o_pensamento_sem_texto_diz_ao_painel_que_o_silencio_e_pensamento():
    """⛔⛔ Ensaio da C07 (2026-10-22, Sonnet 5): o bloco de pensamento chega sem texto (só a
    assinatura), e o painel ficou 5 min em "sem sinal" — lido como transcrição travada."""
    ev = lambda interno: {"type": "stream_event", "event": interno}  # noqa: E731
    inicio = list(C._traduzir(ev({"type": "content_block_start",
                                  "content_block": {"type": "thinking", "thinking": ""}})))
    assert inicio[0][0] == "progresso" and inicio[0][1]["pensando"] is True
    # A assinatura não é texto: nada a mostrar, e nada que pareça progresso.
    assert list(C._traduzir(ev({"type": "content_block_delta", "delta": {
        "type": "signature_delta", "signature": "x" * 5000}}))) == []
    # O texto que vem depois desliga o "pensando há".
    depois = list(C._traduzir(ev({"type": "content_block_start",
                                  "content_block": {"type": "text", "text": ""}})))
    assert depois == [("progresso", {"etapa": "", "fracao": None})]
