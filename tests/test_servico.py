"""O porteiro e o roteamento — a lógica que decide quem fala com o serviço.

⚠️ Estes testes existem porque a regra do porteiro já foi escrita ERRADA uma vez, no
ADR 0005 original, e o modo de falha é confuso de propósito: o painel carrega, os POSTs
funcionam, e todo GET volta 401. Um teste que fixe o cabeçalho certo custa quatro linhas
e evita repetir a depuração que o banco já pagou.
"""

from __future__ import annotations

from cicloassist.servico import rotas  # noqa: F401  (registra as rotas por import)
from cicloassist.servico.http import (
    ROTAS,
    CorpoInvalido,
    Pedido,
    cors_para,
    veio_do_painel,
)


def pedido(**cabecalhos: str) -> Pedido:
    return Pedido("GET", "/x", {k.lower().replace("_", "-"): v for k, v in cabecalhos.items()})


# ── o porteiro ───────────────────────────────────────────────────────────────

def test_painel_servido_por_nos_passa_pelo_sec_fetch_site():
    assert veio_do_painel(pedido(sec_fetch_site="same-origin"))


def test_loader_do_avpi_passa_pela_origem():
    """⚠️ A origem é literalmente `avpi://` — MEDIDA, não suposta. Não vem com o id do
    plugin colado, não vem `null`, não vem ausente."""
    assert veio_do_painel(pedido(origin="avpi://"))


def test_get_do_painel_sem_origin_ainda_passa():
    """⭐ O caso que derruba quem aposta no `Origin`: um GET same-origin NÃO manda
    `Origin` nenhum. Se o porteiro exigisse Origin, o painel carregaria e toda leitura
    voltaria 403 — com os POSTs funcionando, o que faz o sintoma apontar para o lugar
    errado. Medido pelo banco em 2026-08-09."""
    assert veio_do_painel(pedido(sec_fetch_site="same-origin"))
    assert "origin" not in pedido(sec_fetch_site="same-origin").cabecalhos


def test_site_qualquer_chamando_localhost_e_recusado():
    assert not veio_do_painel(pedido(sec_fetch_site="cross-site", origin="https://mau.example"))


def test_pedido_sem_cabecalho_nenhum_e_recusado():
    """curl, script, qualquer processo local: sem prova de origem, não passa."""
    assert not veio_do_painel(pedido())


def test_origem_parecida_com_avpi_nao_passa():
    assert not veio_do_painel(pedido(origin="https://avpi.example.com"))


# ── CORS ─────────────────────────────────────────────────────────────────────

def test_loader_recebe_a_origem_de_volta():
    """⚠️⚠️ Sem este cabeçalho o loader diz "o serviço não está rodando" COM o serviço
    rodando: o fetch abre a conexão, o servidor responde 200, e o navegador recusa
    entregar a resposta à página. O `catch` do loader não distingue os dois casos.
    Medido dentro do Media Composer em 2026-09-10."""
    assert cors_para(pedido(origin="avpi://")) == {"Access-Control-Allow-Origin": "avpi://"}


def test_nunca_libera_para_qualquer_origem():
    """⛔ Um `*` abriria o serviço para qualquer página no navegador do editor."""
    for cabecalhos in ({}, {"origin": "https://mau.example"}, {"sec_fetch_site": "same-origin"}):
        assert "*" not in str(cors_para(pedido(**cabecalhos)))


def test_pagina_do_painel_nao_precisa_de_cors():
    """Depois de carregada ela é same-origin — e same-origin não usa CORS."""
    assert cors_para(pedido(sec_fetch_site="same-origin")) == {}


# ── o roteamento ─────────────────────────────────────────────────────────────

def test_rotas_que_agem_exigem_o_painel():
    _, exige = ROTAS[("POST", "/conversar")]
    assert exige is True


def test_a_rota_das_pendencias_tambem_exige_o_painel():
    """⚠️ É um GET, e mesmo assim passa pelo porteiro: ela conta o que o editor ainda não
    decidiu. `Sec-Fetch-Site` funciona no GET — o `Origin` é que não vem, e é por isso que
    o porteiro olha aquele cabeçalho e nunca este."""
    _, exige = ROTAS[("GET", "/pendencias")]
    assert exige is True


def test_as_rotas_de_configuracao_exigem_o_painel():
    """⛔ Elas leem e MUDAM a máquina do editor — inclusive apagam. Nenhuma pode atender
    a quem não é a página."""
    for metodo, caminho in [("GET", "/configuracoes"), ("POST", "/configuracoes"),
                            ("POST", "/cache/apagar")]:
        assert ROTAS[(metodo, caminho)][1] is True, f"{metodo} {caminho} sem porteiro"


def test_a_rota_dos_vetores_exige_o_painel():
    """Ela conta o que há na máquina do editor — que material foi analisado, e quanto ele
    ocupa. É leitura, e mesmo assim não é de qualquer um."""
    assert ROTAS[("GET", "/vetores")][1] is True


def test_saude_e_painel_nao_exigem_porteiro():
    """`/painel` é NAVEGAÇÃO DE TOPO vinda de `avpi://` — ela não manda
    `Sec-Fetch-Site: same-origin`. Exigir o porteiro aqui deixaria o painel em branco."""
    assert ROTAS[("GET", "/saude")][1] is False
    assert ROTAS[("GET", "/painel")][1] is False


def test_a_rota_do_mcp_nao_e_adivinhavel():
    """O subprocesso do Claude não manda cabeçalho de navegador, então o porteiro dele
    é o segredo do caminho — e ele não pode ser `/mcp` puro."""
    caminhos = [c for (m, c) in ROTAS if c.startswith("/mcp")]
    assert caminhos and all(c != "/mcp" for c in caminhos)
    assert all(len(c) > len("/mcp/") + 20 for c in caminhos)


def test_registro_recusa_rota_repetida():
    """Sobrescrita silenciosa de rota: tudo sobe e a rota errada responde. Aconteceu no
    projeto anterior, quando dois módulos declararam `/mc/info`."""
    from cicloassist.servico.http import rota

    import pytest

    with pytest.raises(ValueError, match="já registrada"):

        @rota("GET", "/saude", exige_painel=False)
        def _colidente(_):  # pragma: no cover
            return None


# ── a fronteira do corpo ─────────────────────────────────────────────────────

def corpo(bytes_: bytes) -> Pedido:
    return Pedido("POST", "/conversar", {}, bytes_)


def test_corpo_em_outra_codificacao_e_erro_do_cliente():
    """⚠️⚠️ MEDIDO 2026-09-10: `json.loads` sobre BYTES adivinha a codificação e levanta
    `UnicodeDecodeError` — que NÃO é `JSONDecodeError` e escapa do `except` óbvio. A rota
    estourou e o serviço respondeu `500 falha interna`, culpando a si mesmo por uma
    entrada torta que veio de fora."""
    import pytest

    with pytest.raises(CorpoInvalido, match="UTF-8"):
        corpo("transcrição".encode("cp1252")).json()


def test_json_torto_tambem_e_erro_do_cliente():
    import pytest

    with pytest.raises(CorpoInvalido, match="JSON inválido"):
        corpo(b"{nao e json}").json()


def test_corpo_vazio_nao_e_erro():
    assert corpo(b"").json() is None


def test_utf8_legitimo_atravessa_com_acento():
    assert corpo('{"pergunta":"transcrição à noite"}'.encode("utf-8")).json() == {
        "pergunta": "transcrição à noite"
    }


# ── o contrato entre a tela e o serviço ──────────────────────────────────────
#
# ⚠️⚠️ **O painel vem do DISCO; as rotas vivem na MEMÓRIA do processo.** Em 2026-09-11
# isso custou meia sessão: a tela de hoje foi falar com o serviço de ontem e respondeu
# "rota desconhecida" na engrenagem. Em execução, quem avisa é o `capacidades` do
# `/saude`. Aqui, o que se trava é o outro lado do mesmo erro: a tela pedir uma rota que
# NUNCA existiu, ou ganhar uma aba sem tela.

import re                                                        # noqa: E402
from pathlib import Path                                         # noqa: E402

PAINEL = Path(__file__).resolve().parent.parent / "cicloassist" / "painel"


def capacidades_do_servico() -> set[str]:
    return {c.lstrip("/") for (_, c) in ROTAS if not c.startswith("/mcp/")}


def test_o_painel_so_pede_rotas_que_existem():
    """⭐ O `PRECISO_DE` do painel é a lista com que a tela confere o serviço na partida.
    Um nome errado ali faria a tela acusar de velho um serviço que está em dia — e o
    editor iria reiniciar o serviço para sempre, sem nunca resolver."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    bloco = re.search(r"var PRECISO_DE = \[(.*?)\];", js, re.S)
    assert bloco, "o painel perdeu a lista PRECISO_DE"

    pedidas = set(re.findall(r'"([^"]+)"', bloco.group(1)))
    assert pedidas <= capacidades_do_servico(), (
        f"a tela pede o que o serviço não tem: {sorted(pedidas - capacidades_do_servico())}"
    )


def test_o_painel_nao_pode_ser_guardado_em_cache():
    """⚠️⚠️ MEDIDO em 2026-09-11 dentro do Media Composer: o Reload trouxe a página
    ANTIGA — a tela recarregou idêntica, sem a mudança recém-escrita, enquanto o `curl`
    devolvia o HTML novo. A resposta ia sem cabeçalho de cache nenhum. O sintoma diz "o
    código novo não funcionou"."""
    from cicloassist.servico.rotas import painel

    assert painel(None).extras.get("Cache-Control") == "no-store"


def test_o_hidden_ganha_do_display():
    """⛔ O JavaScript troca de tela escrevendo `el.hidden`, e o `hidden` do navegador é
    um `display:none` de folha padrão que QUALQUER `display` de autor vence. Sem esta
    regra, `.conversa`, `.status` e `.compositor` (todos `display:flex`) continuam na tela
    por baixo da aba aberta — foi assim que a aba Vetores nasceu, com a conversa colada
    em cima."""
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")
    assert re.search(r"\[hidden\]\s*\{[^}]*display:\s*none\s*!important", css), (
        "o painel perdeu a regra que faz o atributo hidden valer"
    )


def test_o_javascript_do_painel_e_valido():
    """⚠️⚠️ **Um erro de sintaxe no painel não aparece como erro: aparece como painel que
    não faz nada.** MEDIDO em 2026-09-11: uma quebra de linha dentro de uma string deixou
    o arquivo inteiro sem executar — nenhuma aba trocava, o modelo não aparecia na barra,
    o ponto ficava cinza. Nada no serviço acusa, porque o serviço está bem.

    ⭐ `node --check` custa 50 ms e pega a classe inteira. ⚠️ Ele NÃO é pré-requisito do
    produto (o painel roda no QtWebEngine), então o teste pula quando não houver node —
    é conferência de quem desenvolve, não de quem usa.
    """
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node não está instalado; o painel não é conferido nesta máquina")

    for nome in ("painel.js", "fluxo.js"):
        r = subprocess.run([node, "--check", str(PAINEL / nome)],
                           capture_output=True, text=True, timeout=30)
        assert r.returncode == 0, f"o {nome} não compila:\n{r.stderr}"


def test_toda_aba_tem_uma_tela():
    """⚠️ Acrescentar uma aba é somar um `<button data-tela>` e um `<section data-tela>`.
    Só o botão dá uma aba que, clicada, esconde tudo e não mostra nada — e o JavaScript
    não tem como reclamar."""
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    botoes = set(re.findall(r'<button[^>]*\sdata-tela="([^"]+)"', html))
    telas = set(re.findall(r'<(?:section|main|footer)[^>]*\sdata-tela="([^"]+)"', html))

    assert botoes, "o painel perdeu as abas"
    assert botoes <= telas, f"aba sem tela: {sorted(botoes - telas)}"


# ── o que a segunda rodada de campo pediu (2026-09-12) ───────────────────────

def test_o_painel_tem_o_botao_de_parar():
    """⛔ Sem ele, a única saída de um turno caro era esperar."""
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    assert 'id="pararConversa"' in html


def test_o_botao_de_parar_avisa_o_que_NAO_para():
    """⛔⛔ Cancelar mata o modelo, mas **não** interrompe ferramenta já disparada: no modo
    automático a escrita na bin roda na thread do /mcp. Quem clica precisa saber."""
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    botao = re.search(r'id="pararConversa"[^>]*', html, re.S)
    assert botao and "termina de rodar" in botao.group(0)


def test_o_painel_mostra_o_fio_que_vem_de_antes():
    """⭐⭐ "Tela em branco, contexto cheio": ele fechou o MC sem /clear e o teste seguinte
    rodou sobre meio milhão de tokens de anteontem."""
    html = (PAINEL / "index.html").read_text(encoding="utf-8")
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert 'id="fioAviso"' in html
    assert "mostrarOFio" in js


def test_a_saude_conta_o_fio():
    from cicloassist.servico.rotas import saude

    import json as _json
    corpo = _json.loads(saude(None).corpo)
    assert "fio" in corpo and "turnos" in corpo["fio"]


def test_o_fio_nao_consulta_o_media_composer():
    """⛔⛔ `/saude` é batida pelo loader a cada 3 s e `_projeto_aberto()` NÃO cacheia a
    falha: consultar dali viraria uma tentativa de gRPC a cada três segundos, justamente
    enquanto o Media Composer sobe."""
    from cicloassist.servico import rotas

    chamou = []
    antes = rotas.MediaComposer
    rotas.MediaComposer = lambda *a, **k: chamou.append(1)
    try:
        rotas._fio()
    finally:
        rotas.MediaComposer = antes
    assert not chamou


def test_a_resposta_ganha_rodape_de_tempo_e_tokens():
    """⭐ Os dois números já chegavam e eram destruídos junto com a linha de atividade."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert 'pe.className = "rodape"' in js
    assert 'tipo === "fim"' in js, "o evento `fim` continua sem ramo no dispatcher"


def test_dois_servicos_NAO_podem_bindar_a_mesma_porta():
    """⛔⛔ MEDIDO em 2026-09-12: dois serviços escutando a 7824 ao mesmo tempo — um de
    15:32 e outro de 17:26 — com o novo logando "serviço em http://127.0.0.1:7824" e o
    VELHO respondendo tudo. No Windows, `allow_reuse_address` não é "reaproveitar socket
    em TIME_WAIT": é deixar um segundo processo roubar a porta em silêncio.

    O sintoma é indistinguível de painel desatualizado — e "reinicie o serviço", que é o
    conselho impresso em três lugares do produto, não resolvia."""
    from http.server import ThreadingHTTPServer

    from cicloassist.servico import http as H

    assert H.subir.__module__  # a função existe
    assert issubclass(H.PortaOcupada, OSError), (
        "o __main__ trata porta ocupada capturando OSError; herdar de outra coisa "
        "devolveria traceback cru ao editor"
    )
    # ⚠️ No Windows a opção deixa um segundo processo bindar a porta viva; no POSIX ela só
    #    reaproveita TIME_WAIT, e desligá-la travava o reinício por ~30 s (medido no macOS).
    import os
    assert H._Servidor.allow_reuse_address == (os.name != "nt")
    assert ThreadingHTTPServer.allow_reuse_address == 1, "a classe da stdlib não é nossa"


def test_um_segundo_servico_na_mesma_porta_e_recusado():
    """O que a regra de porta promete, medido de verdade: com o primeiro de pé, o segundo
    não sobe — em qualquer sistema."""
    import socket

    import pytest

    from cicloassist.servico import http as H

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    primeiro = H.subir(porta)
    try:
        with pytest.raises(H.PortaOcupada):
            H.subir(porta)
    finally:
        primeiro.shutdown()
        primeiro.server_close()


def test_avisa_ANTES_de_gastar_quando_a_conversa_nao_cabe():
    """⛔⛔ MEDIDO em 2026-09-12: 582.570 tokens retomados debaixo do Haiku (200 mil de
    janela). O CLI auto-compactou por 70 segundos SEM UMA PALAVRA na tela, queimou 121 mil
    tokens, e o editor cancelou achando que estava travado."""
    from cicloassist.motor import claude as _claude
    from cicloassist.servico import config as _config
    from cicloassist.servico import rotas

    _claude._JANELAS["modelo-pequeno"] = 200_000
    antes = _config.ler_estado
    _config.ler_estado = lambda: {"fio": {"contexto": 582_570}}
    try:
        aviso = rotas._nao_cabe_na_janela("modelo-pequeno")
        assert "582" in aviso and "200" in aviso and "/clear" in aviso
        # Cabendo, cala a boca: aviso que sempre aparece deixa de ser aviso.
        _claude._JANELAS["modelo-grande"] = 1_000_000
        assert rotas._nao_cabe_na_janela("modelo-grande") == ""
    finally:
        _config.ler_estado = antes


def test_a_compactacao_do_CLI_vira_linha_na_tela():
    """⛔ O evento existia no stream e era jogado fora — era o "1 minuto sem dizer nada"."""
    from cicloassist.motor.claude import _traduzir

    evento = {"type": "system", "subtype": "compact_boundary",
              "compactMetadata": {"preTokens": 582_570, "postTokens": 108_239}}
    saidas = dict(_traduzir(evento))
    assert "progresso" in saidas
    assert "resumindo" in saidas["progresso"]["etapa"]


# ── a cor que separa o que é do Avid do que veio de fora (2026-09-12) ────────

def test_o_anexo_declara_de_onde_veio():
    """⭐ Duas origens chegam pelo MESMO gesto e têm consequências diferentes: o mob do
    Media Composer o plugin alcança pela ponte gRPC; o arquivo do Explorer só é legível
    porque o editor arrastou AQUELE arquivo (`servico/arrastados.py`). A cor diz qual é
    qual sem ninguém ler o rótulo."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")

    assert 'chip.dataset.origem' in js, "o chip de anexo parou de declarar a origem"
    assert '--externo:' in css, "o painel perdeu a cor do material de fora do Avid"
    assert '.anexo[data-origem="externo"]' in css


def test_problema_no_anexo_ganha_da_origem():
    """⚠️ `.anexo.ruim` e `.anexo[data-origem=…]` têm a MESMA especificidade (0,2,0) — quem
    ganha é a ORDEM no arquivo. Invertida, um anexo ilegível do Explorer ficaria violeta
    em vez de âmbar, e o aviso que evita um turno gasto sumiria de vista."""
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")
    assert css.index('.anexo[data-origem="externo"]') < css.index('.anexo.ruim'), (
        "a regra da origem passou a vencer a do problema"
    )


def test_o_realce_do_arrasto_nao_promete_outra_origem():
    """⚠️ O realce acende no `dragover` e o chip nasce no `drop`. Se a cor de um seguisse
    um critério e a do outro seguisse outro, o realce prometeria uma origem e o chip
    entregaria a outra — e quem arrasta do Media Composer vê SEMPRE os dois MIMEs, porque
    o `text/uri-list` que vem junto é lixo (banco: `plugins/avid-panel-sdk/arrastar.md`).
    Por isso os dois decidem pela presença do MIME do Avid, nessa ordem."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert 'classList.toggle("de-fora", !doAvid)' in js
    # E o realce tem de APAGAR em todos os caminhos de saída, inclusive no arrasto que não
    # entregou nada — antes ele ficava aceso em cima da mensagem de erro.
    assert js.count("apagarRealce()") >= 3, (
        "algum caminho de saída do arrasto deixou o realce aceso"
    )


def test_o_arrasto_do_finder_da_caminho_absoluto():
    """⛔ MEDIDO no macOS (2026-09-14): `replace(/^file:\\/{2,3}/, "")` comia a TERCEIRA
    barra, que é a raiz do caminho. `file:///Users/x` virava `Users/x`, relativo, e todo
    arquivo arrastado do Finder aparecia como "não encontrei". Roda a função do painel."""
    import json
    import re
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("node não está instalado; o painel não é conferido nesta máquina")

    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    funcao = re.search(r"function caminhoDaUri\(uri\) \{.*?\n\}", js, re.S).group(0)
    casos = {
        "file:///Users/ed/Desktop/Roteiro.docx": "/Users/ed/Desktop/Roteiro.docx",
        "file:///Volumes/SSD/PROGRAMAS%20COM%20CLAUDE/Cena%C3%A7%C3%A3o.txt":
            "/Volumes/SSD/PROGRAMAS COM CLAUDE/Cenação.txt",
        "file://localhost/Users/x/a.txt": "/Users/x/a.txt",
        "file:///C:/Users/ed/Roteiro%20C07.docx": "C:\\Users\\ed\\Roteiro C07.docx",
        "file://servidor/obras/roteiro.txt": "\\\\servidor\\obras\\roteiro.txt",
    }
    programa = funcao + "\nconsole.log(JSON.stringify(%s.map(caminhoDaUri)));" % json.dumps(
        list(casos))
    r = subprocess.run([node, "-e", programa], capture_output=True, text=True, timeout=30,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == list(casos.values())


# ── os três achados do porte para o Assist anterior (2026-09-19/20) ─────────────
#
# Cada um falha de um jeito que NÃO aponta para si mesmo, e nenhum tinha teste.


def test_toda_variavel_de_cor_usada_existe():
    """⛔ `var(--x)` sem fallback e sem `--x` declarada é declaração INVÁLIDA: o navegador
    a descarta e a cor simplesmente não se aplica, calada. O painel tinha quatro —
    `--tinta-1` (três vezes) e `--aviso` —, herdadas de uma paleta que nunca existiu aqui.
    Achado no porte para o Assist anterior em 2026-09-19."""
    css = (PAINEL / "painel.css").read_text(encoding="utf-8")
    declaradas = set(re.findall(r"^\s*(--[\w-]+)\s*:", css, re.M))
    # ⚠️ Só as SEM fallback: `var(--x, #ccc)` é escolha legítima, não defeito.
    usadas = set(re.findall(r"var\(\s*(--[\w-]+)\s*\)", css))
    assert usadas <= declaradas, (
        f"o painel usa cor que ninguém define, e ela não se aplica: "
        f"{sorted(usadas - declaradas)}"
    )


def test_o_painel_nao_monta_texto_com_innerHTML():
    """⚠️ A regra é do próprio painel, e o aviso de fio continuado era o único lugar a
    furá-la. Os números vêm do serviço, mas a regra não abre exceção para dado "que parece
    seguro" — é assim que a primeira exceção vira a segunda."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    # ⚠️ A ATRIBUIÇÃO, não a palavra: o próprio painel comenta a regra citando o nome.
    escritas = re.findall(r"\.innerHTML\s*(?:\+)?=[^=]", js)
    assert not escritas, f"voltou um innerHTML ao painel: {escritas}"


def test_o_arrasto_escolhe_um_efeito_compativel():
    """⛔ O banco manda *"escolha um efeito compatível"*
    (`plugins/avid-panel-sdk/arrastar.md`): `dropEffect` incompatível com o `effectAllowed`
    da origem **cancela o drop em silêncio** — o realce acende e soltar não faz nada. O
    literal `"move"` acertava o Media Composer e cancelaria uma origem que só copia."""
    import json
    import shutil
    import subprocess

    node = shutil.which("node")
    if node is None:
        pytest.skip("node não está instalado; o painel não é conferido nesta máquina")

    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    assert 'dropEffect = "move"' not in js, "o efeito do arrasto voltou a ser literal"
    funcao = re.search(r"function efeitoCompativel\(dt\) \{.*?\n\}", js, re.S).group(0)
    casos = {
        # o Media Composer, e o padrão de quem não declara nada: continuam "move"
        "move": "move", "all": "move", "uninitialized": "move", "": "move",
        "copyMove": "move",
        # ⭐ onde o literal cancelaria o drop
        "copy": "copy", "copyLink": "copy", "link": "link",
        "none": None,
    }
    programa = (funcao + "\nconsole.log(JSON.stringify(" + json.dumps(list(casos)) +
                ".map(function (p) { return efeitoCompativel({ effectAllowed: p }); })));")
    r = subprocess.run([node, "-e", programa], capture_output=True, text=True, timeout=30,
                       encoding="utf-8")
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout) == list(casos.values())


def test_todo_id_que_o_painel_procura_existe_no_html():
    """⚠️⚠️ **Um `getElementById` que volta `null` não aparece como erro: aparece como
    painel que não faz nada.** É a mesma classe do erro de sintaxe (acima), e o `node
    --check` não a pega — o arquivo compila perfeitamente e quebra na primeira chamada.

    ⭐ Barato de conferir sem DOM nenhum: os dois arquivos são texto, e um `id` que só
    existe num deles é a divergência inteira.
    """
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")
    html = (PAINEL / "index.html").read_text(encoding="utf-8")

    procurados = set(re.findall(r'getElementById\(\s*"([^"]+)"\s*\)', js))
    existem = set(re.findall(r'\sid="([^"]+)"', html))
    assert procurados <= existem, (
        f"o painel procura id que o HTML não tem: {sorted(procurados - existem)}")


def test_arrasto_que_nasce_no_painel_nao_acende_o_solte_aqui():
    """⛔⛔ Visto pelo editor no Media Composer (2026-09-21): arrastando um resultado da aba
    Busca, o painel acendia **"solte aqui"** no rodapé — prometendo receber o que ele mesmo
    acabara de mostrar. A miniatura é um `<img>`, e `<img>` é arrastável por padrão: o
    arrasto carrega `Files`, que é exatamente o que o realce procura.

    ⚠️ Duas travas, e as duas fazem falta: a imagem deixa de ser arrastável, e QUALQUER
    arrasto iniciado dentro da página fica marcado (pega o texto selecionado e o que vier
    depois). ⭐ Conferido por CDP: de fora acende, de dentro não, e de fora **volta** a
    acender — a marca não fica pendurada."""
    js = (PAINEL / "painel.js").read_text(encoding="utf-8")

    assert js.count("img.draggable = false") >= 2, (
        "as miniaturas da busca voltaram a ser arrastáveis")
    assert 'addEventListener("dragstart"' in js, "ninguém marca o arrasto que nasce aqui"
    assert "if (arrastandoDeDentro) { return; }" in js, (
        "o dragover parou de respeitar a marca")
    # ⛔ Sem as duas desmarcações o realce nunca mais acende: um arrasto interno deixaria
    #   o painel surdo ao arrasto seguinte, que é o defeito oposto e pior.
    for evento in ('"dragend"', '"drop"'):
        assert f'addEventListener({evento}, function () {{ arrastandoDeDentro = false; }}' in js, (
            f"o {evento} parou de desmarcar — o painel ficaria surdo ao próximo arrasto")
