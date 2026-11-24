"""A sessão de conversa — identidade do projeto e a regra do resume.

⚠️⚠️ **O que estes testes protegem é uma escolha que falha em SILÊNCIO.** Medido em
2026-09-10: `--session-id` num id que já existe **não dá erro** — começa conversa nova e
descarta o fio. Já `--resume` num id inexistente falha limpo, dizendo
`No conversation found with session ID`.

⇒ Sempre `--resume` primeiro, com queda para `--session-id`. Inverter a ordem custa a
conversa inteira do editor, sem nada acusando.
"""

from __future__ import annotations

import pytest

from cicloassist.motor import sessao as S


# ── a identidade do projeto ──────────────────────────────────────────────────

def test_mesmo_projeto_da_mesmo_id():
    """⭐ Derivado, não sorteado: abrir o mesmo projeto amanhã recupera o fio sem que a
    gente guarde mapa nenhum."""
    caminho = r"C:\Users\ed\Avid Projects\MEU"
    assert S.id_do_projeto(caminho) == S.id_do_projeto(caminho)


def test_projetos_diferentes_dao_ids_diferentes():
    assert S.id_do_projeto(r"C:\a") != S.id_do_projeto(r"C:\b")


def test_caixa_e_barra_final_nao_criam_conversa_nova():
    """⚠️ No Windows `C:\\X` e `c:\\x\\` são a MESMA pasta. Sem normalizar, o editor
    ganharia duas conversas para o mesmo projeto conforme o caminho chegasse de um jeito
    ou de outro — e nada indicaria o porquê."""
    base = S.id_do_projeto(r"C:\Users\ed\Avid Projects\MEU")
    assert S.id_do_projeto(r"c:\users\ed\avid projects\meu") == base
    assert S.id_do_projeto("C:/Users/ed/Avid Projects/MEU/") == base
    assert S.id_do_projeto(r"C:\Users\ed\Avid Projects\MEU\\") == base


def test_id_e_uuid_valido():
    """O CLI exige UUID no `--session-id`; qualquer outra coisa é recusada."""
    import uuid

    uuid.UUID(S.id_do_projeto(r"C:\qualquer"))


# ── o registro de sessões ────────────────────────────────────────────────────

def test_mesmo_projeto_reusa_a_sessao():
    S.encerrar_todas()
    a = S.do_projeto(r"C:\proj", "http://127.0.0.1:7824/mcp/x", ["t"])
    b = S.do_projeto(r"C:\proj", "http://127.0.0.1:7824/mcp/x", ["t"])
    assert a is b
    S.encerrar_todas()


def test_o_segredo_do_mcp_e_atualizado_no_reuso():
    """⚠️ O endereço do MCP carrega um segredo sorteado a CADA arranque do serviço. Uma
    sessão reusada com o segredo velho apontaria para uma rota que já não existe, e o
    modelo ficaria sem ferramenta nenhuma — sem erro visível."""
    S.encerrar_todas()
    a = S.do_projeto(r"C:\proj", "http://127.0.0.1:7824/mcp/velho", ["t"])
    b = S.do_projeto(r"C:\proj", "http://127.0.0.1:7824/mcp/novo", ["t", "u"])
    assert a is b
    assert b.url_do_mcp.endswith("/novo")
    assert b.ferramentas == ["t", "u"]
    S.encerrar_todas()


def test_projetos_diferentes_sao_sessoes_diferentes():
    S.encerrar_todas()
    a = S.do_projeto(r"C:\um", "http://x", [])
    b = S.do_projeto(r"C:\outro", "http://x", [])
    assert a is not b
    assert a.id != b.id
    S.encerrar_todas()


# ── a linha de comando ───────────────────────────────────────────────────────

def comando_de(sessao, retomar):
    from pathlib import Path

    return sessao._comando("claude", Path("mcp.json"), retomar)


def test_resume_e_session_id_sao_excludentes():
    """Passar os dois é erro de uso do CLI — o `--resume` já diz qual sessão é."""
    s = S.Sessao("11111111-1111-1111-1111-111111111111", "http://x", [])
    com_resume = comando_de(s, True)
    com_novo = comando_de(s, False)
    assert "--resume" in com_resume and "--session-id" not in com_resume
    assert "--session-id" in com_novo and "--resume" not in com_novo


def test_a_conversa_entra_por_stdin():
    """⭐ É `--input-format stream-json` que transforma o processo em conversa: sem ele o
    processo morre depois do primeiro `result`, e cada pergunta volta a custar um
    processo novo."""
    s = S.Sessao("11111111-1111-1111-1111-111111111111", "http://x", [])
    comando = comando_de(s, True)
    assert comando[comando.index("--input-format") + 1] == "stream-json"


def test_as_flags_de_contencao_sobrevivem_a_sessao():
    """⛔ Uma sessão que retoma não pode retomar SEM as travas: `--restricted` fora deixa
    um shell na estação do cliente, e sem `--strict-mcp-config` entram os MCP pessoais do
    editor."""
    s = S.Sessao("11111111-1111-1111-1111-111111111111", "http://x", ["a"])
    for retomar in (True, False):
        comando = comando_de(s, retomar)
        assert "--restricted" in comando
        # ⛔⛔ E sem ferramenta NATIVA nenhuma: o `--restricted` deixa `Write` e `Edit`.
        assert comando[comando.index("--tools") + 1] == ""
        assert "--strict-mcp-config" in comando
        assert "--permission-prompt-tool" in comando


def test_a_deixa_para_criar_e_a_mensagem_do_cli():
    """A queda de `--resume` para `--session-id` depende deste texto. Se o CLI mudar a
    mensagem, a queda para de acontecer — e o sintoma seria "a conversa não começa"."""
    assert S.SEM_CONVERSA == "no conversation found"


# ── cancelar ─────────────────────────────────────────────────────────────────
#
# ⛔⛔ Pedido do editor em 2026-09-12: faltava um botão para interromper. O trabalho do
# turno roda DENTRO do `claude -p`, então parar de verdade é matar o subprocesso — e o
# perigo é um turno morto se anunciar como terminado.

class _Falso:
    """Um subprocesso que se deixa matar."""

    def __init__(self, vivo=True):
        self.morto = False
        self._vivo = vivo
        self.stdin = None
        self.stderr = None

    def poll(self):
        return None if self._vivo else 0

    def kill(self):
        self.morto = True
        self._vivo = False


def _sessao_com(proc):
    s = S.Sessao("id", "http://x", [])
    s._proc = proc
    return s


def test_cancelar_mata_o_subprocesso():
    proc = _Falso()
    s = _sessao_com(proc)
    assert s.cancelar() is True
    assert proc.morto


def test_cancelar_sem_turno_nao_mente():
    assert _sessao_com(None).cancelar() is False
    assert _sessao_com(_Falso(vivo=False)).cancelar() is False


def test_cancelar_NAO_espera_a_trava_do_turno():
    """⛔⛔ `perguntar()` segura `self._trava` o turno inteiro. Se `cancelar()` pedisse a
    mesma trava, ficaria esperando justamente o que quer interromper — que é o defeito
    que já fazia `/limpar` no meio de um turno ficar pendurado."""
    proc = _Falso()
    s = _sessao_com(proc)
    s._trava.acquire()          # como se um turno estivesse rodando
    try:
        assert s.cancelar() is True
    finally:
        s._trava.release()


def test_o_pedido_de_cancelamento_fica_marcado():
    """⚠️ O laço do turno precisa saber que o EOF foi PEDIDO: um processo morto dá EOF
    igual a um turno que acabou bem, e sem esta marca ele emitiria "fim"."""
    s = _sessao_com(_Falso())
    assert not s._cancelado.is_set()
    s.cancelar()
    assert s._cancelado.is_set()


# ── o fio que o /clear não limpava ───────────────────────────────────────────
#
# ⛔⛔ MEDIDO em 2026-09-12, e custou 121 mil tokens do editor. Ele deu /clear logo depois
# de o serviço reiniciar, o log disse "havia sessão: False", e o turno seguinte retomou uma
# conversa de 582.570 tokens debaixo do Haiku (janela de 200 mil). O CLI auto-compactou por
# 70 segundos sem produzir uma palavra.

def test_o_fio_vem_do_DISCO_e_nao_do_caminho(tmp_path, monkeypatch):
    """⭐ O caminho só semeia o PRIMEIRO fio; depois quem manda é o que foi gravado."""
    monkeypatch.setattr(S._config, "ler_estado", lambda: {"fios": {"chave-x": "fio-novo"}})
    assert S.fio_do_projeto("chave-x") == "fio-novo"
    assert S.fio_do_projeto("chave-sem-registro") == "chave-sem-registro"


def test_limpar_SEM_sessao_viva_ainda_joga_o_fio_fora(monkeypatch):
    """⛔⛔ O defeito exato: `_sessoes` nasce vazio quando o serviço reinicia, e o /clear
    virava no-op — devolvendo `havia sessão: False` e deixando o fio velho de pé."""
    estado = {"fios": {}}
    caminho = r"C:\p"
    chave = S.id_do_projeto(caminho)
    estado["fios"][chave] = "fio-velho"
    monkeypatch.setattr(S._config, "ler_estado", lambda: estado)
    monkeypatch.setattr(S._config, "gravar_estado", lambda m: estado.update(m))
    monkeypatch.setattr(S, "_sessoes", {})

    assert S.recomecar(caminho) is True, "havia fio gravado — não pode dizer que não havia"
    assert estado["fios"][chave] != "fio-velho", "o fio velho continuaria sendo retomado"


def test_recomecar_grava_o_fio_novo(monkeypatch):
    """⚠️ Sem gravar, o "limpei" só valia até o serviço reiniciar."""
    gravado = {}
    monkeypatch.setattr(S._config, "ler_estado", lambda: gravado)
    monkeypatch.setattr(S._config, "gravar_estado", lambda m: gravado.update(m))
    s = S.Sessao("fio-velho", "http://x", [], chave="chave-x")
    novo = s.recomecar()
    assert novo != "fio-velho"
    assert gravado["fios"]["chave-x"] == novo


# ── o stderr que travava o turno ─────────────────────────────────────────────

def test_ler_stderr_NAO_le_do_cano(monkeypatch):
    """⛔⛔ `proc.stderr.read()` lê até o EOF — e num processo que fica VIVO entre turnos
    esse EOF nunca chega. Foi isso que deixou o painel cinco minutos em "pensando", já
    depois de o `result` ter chegado e o gasto ter aparecido na tela."""
    s = S.Sessao("id", "http://x", [])

    class CanoQueTrava:
        def read(self, *a):
            raise AssertionError("ninguém pode ler do cano aqui — ver _drenar_stderr")

    s._proc = type("P", (), {"stderr": CanoQueTrava()})()
    s._stderr.extend(["erro de verdade", "outra linha"])
    assert s._ler_stderr() == "erro de verdade\nutra linha".replace("utra", "outra")


def test_todo_lugar_que_sobe_o_cli_desliga_as_ferramentas_nativas():
    """⛔⛔ Três lugares sobem o `claude -p` (conversa, sessão, decupador), e basta UM
    esquecer o `--tools ""` para o modelo voltar a ter `Write` e `Edit` — o `--restricted`
    sozinho deixa 29 ferramentas nativas (medido, `spikes/o_que_o_restricted_deixa.py`).
    Conferir pelo código-fonte é grosseiro de propósito: pega o quarto lugar que alguém
    criar amanhã copiando só metade das flags."""
    from pathlib import Path
    import cicloassist.motor as M
    for arquivo in sorted(Path(M.__file__).parent.glob("*.py")):
        fonte = arquivo.read_text(encoding="utf-8")
        restritos = fonte.count('"--restricted"')
        sem_nativas = fonte.count('"--tools", ""')
        assert restritos == sem_nativas, (
            f"{arquivo.name}: {restritos} --restricted e {sem_nativas} --tools \"\"")


# ── o CLI que morre na partida ───────────────────────────────────────────────

def _cli_que_morre(s, mensagem="error: unknown option '--restricted'"):
    import subprocess
    import sys

    def subir(retomar):
        proc = subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.stdin.readline(); sys.stderr.write({mensagem!r} + '\\n'); "
             "sys.exit(1)"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1)
        s._drenar_stderr(proc)
        return proc
    return subir


def test_cli_que_morre_sem_result_e_erro_e_nao_fim():
    """⛔⛔ MEDIDO no macOS (2026-09-14): um `claude` velho no PATH recusava `--restricted`,
    saía na partida, e o turno terminava em `fim` — o painel dizia "pronto" com a resposta
    vazia, e o motivo ficava no stderr que ninguém lia."""
    s = S.Sessao("id", "http://x", [])
    s._subir = _cli_que_morre(s)
    eventos = list(s.perguntar("oi"))
    tipos = [t for t, _ in eventos]
    assert "fim" not in tipos
    assert tipos[-1] == "erro"
    assert "unknown option" in eventos[-1][1]["detalhe"]


def test_sem_conversa_sem_result_ainda_cria_a_sessao():
    """A queda de `--resume` para `--session-id` continua valendo quando o CLI sai sem
    `result`: a deixa é o texto do stderr, não o formato da saída."""
    s = S.Sessao("id", "http://x", [])
    chamadas = []
    morre = _cli_que_morre(s, "No conversation found with session ID: id")

    def subir(retomar):
        chamadas.append(retomar)
        return morre(retomar)
    s._subir = subir
    eventos = list(s.perguntar("oi"))
    assert chamadas == [True, False]
    assert eventos[-1][0] == "erro"


# ── o modelo do Mac (M2) ─────────────────────────────────────────────────────

MAC = "http://192.168.1.4:11434"
LOCAL = "ollama:qwen3-vl:8b-instruct"


def test_modelo_do_mac_troca_o_ENDERECO_e_nao_leva_a_credencial(monkeypatch):
    """⛔⛔ Sem chave própria, o CLI mandaria o token OAuth do editor para o Mac."""
    from cicloassist.motor import claude as C
    from cicloassist.motor import percepcao as P
    # ⚠️ A suíte não bate no Mac de verdade: desde 2026-09-17 o ambiente do modelo local
    #   confere se o Ollama responde ANTES de subir o CLI (ver o teste do Ollama fora do ar).
    monkeypatch.setattr(P, "responde", lambda url, timeout=3: True)
    monkeypatch.setenv("CICLOASSIST_OLLAMA", MAC)
    monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "segredo")
    monkeypatch.setenv("CLAUDE_CODE_OAUTH_TOKEN", "segredo")
    nome, amb = C.ambiente_do_modelo(LOCAL)
    assert nome == "qwen3-vl:8b-instruct"
    assert amb["ANTHROPIC_BASE_URL"] == MAC
    assert amb["ANTHROPIC_API_KEY"] == "ollama"
    assert "ANTHROPIC_AUTH_TOKEN" not in amb and "CLAUDE_CODE_OAUTH_TOKEN" not in amb
    # O modelo "rápido" que o CLI usa por dentro também vai para o Mac: senão é 404.
    assert amb["ANTHROPIC_SMALL_FAST_MODEL"] == nome
    assert amb["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == nome
    assert amb["MCP_TOOL_TIMEOUT"]
    # O Ollama retém o pedido de ferramenta: 5 min sem byte é normal, não travamento.
    assert int(amb["API_TIMEOUT_MS"]) >= 1_800_000
    assert amb["API_FORCE_IDLE_TIMEOUT"] == "0"


def test_modelo_do_claude_nao_ganha_endereco(monkeypatch):
    from cicloassist.motor import claude as C
    monkeypatch.setenv("CICLOASSIST_OLLAMA", MAC)
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)
    nome, amb = C.ambiente_do_modelo("claude-haiku-4-5-20251001")
    assert nome == "claude-haiku-4-5-20251001"
    assert "ANTHROPIC_BASE_URL" not in amb


def test_modelo_do_mac_SEM_mac_nao_cai_calado_para_a_assinatura(monkeypatch):
    """O editor escolheu o Mac para NÃO gastar a assinatura."""
    import pytest
    from cicloassist.motor import claude as C
    with pytest.raises(C.MotorIndisponivel):
        C.ambiente_do_modelo(LOCAL)


def test_o_comando_leva_o_nome_do_ollama_sem_prefixo():
    from pathlib import Path
    s = S.Sessao("abc", "http://x", [], LOCAL)
    comando = s._comando("claude", Path("mcp.json"), False, "qwen3-vl:8b-instruct")
    assert comando[comando.index("--model") + 1] == "qwen3-vl:8b-instruct"


def test_trocar_entre_claude_e_mac_e_conversa_NOVA(monkeypatch):
    """⛔⛔ O `--resume` levaria um fio de centenas de milhares de tokens para um servidor
    que carrega 40 mil, e o Ollama corta o excesso calado."""
    monkeypatch.setattr(S, "_gravar_fio", lambda *a: None)
    S.encerrar_todas()
    a = S.do_projeto(r"C:\proj", "http://x", [], "claude-haiku-4-5-20251001")
    antes = a.id
    b = S.do_projeto(r"C:\proj", "http://x", [], LOCAL)
    assert b is a and b.id != antes and b.modelo == LOCAL
    meio = b.id
    S.do_projeto(r"C:\proj", "http://x", [], "claude-sonnet-5")
    assert a.id != meio
    # Entre dois modelos do Claude, o fio continua.
    fio = a.id
    S.do_projeto(r"C:\proj", "http://x", [], "claude-opus-5")
    assert a.id == fio
    S.encerrar_todas()


def test_o_primeiro_turno_de_conversa_nova_traz_o_gasto():
    """⛔ `_turno_ja_de_pe` saía no `result` sem traduzir: o primeiro turno de toda conversa
    nova ficava sem gasto e sem janela (medido em 2026-09-16)."""
    import json
    import subprocess
    import sys
    resultado = json.dumps({"type": "result", "modelUsage": {"claude-x": {
        "contextWindow": 200000, "inputTokens": 10, "outputTokens": 2, "costUSD": 0.01}}})
    s = S.Sessao("id", "http://x", [])
    chamadas = []

    def subir(retomar):
        chamadas.append(retomar)
        if retomar:
            return _cli_que_morre(s, "No conversation found with session ID: id")(retomar)
        return subprocess.Popen(
            [sys.executable, "-c",
             f"import sys; sys.stdin.readline(); print({resultado!r}); sys.stdout.flush(); "
             "sys.stdin.readline()"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", bufsize=1)
    s._subir = subir
    eventos = list(s.perguntar("oi"))
    s.encerrar()
    assert chamadas == [True, False]
    assert any(t == "gasto" for t, _ in eventos)
    assert eventos[-1][0] == "fim"


# ── o servidor do modelo que para no meio (medido em campo, 2026-09-17) ──────

def _cli_que_diz(s, linhas: list[str]):
    """Um `claude -p` de mentira que cospe estas linhas e depois fica esperando."""
    import subprocess
    import sys

    fim_de_linha = chr(10)
    programa = ("import sys" + fim_de_linha
                + "sys.stdin.readline()" + fim_de_linha
                + fim_de_linha.join(f"print({linha!r}); sys.stdout.flush()"
                                    for linha in linhas)
                + fim_de_linha + "sys.stdin.readline()" + fim_de_linha)

    def subir(retomar):
        return subprocess.Popen([sys.executable, "-c", programa],
                                stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                bufsize=1)

    s._subir = subir
    return s


def test_falhas_seguidas_do_servidor_encerram_o_turno_com_a_frase_certa(monkeypatch):
    """⛔⛔ MEDIDO: o Ollama do Mac caiu, o CLI repetiu `Connection error` e o turno NUNCA
    terminou — painel em "pensando…" por 40 minutos, com o trabalho já feito."""
    import json

    falha = json.dumps({"type": "system", "subtype": "api_error",
                        "error": {"message": "Connection error."}})
    s = S.Sessao("id", "http://x", [], modelo="ollama:qwen3-vl:8b-instruct")
    _cli_que_diz(s, [falha] * (S.FALHAS_SEGUIDAS_ATE_DESISTIR + 5))

    eventos = list(s.perguntar("organiza as bins"))
    s.encerrar()
    tipos = [t for t, _ in eventos]
    assert tipos[-1] == "erro"
    mensagem = eventos[-1][1]["mensagem"]
    assert "Mac" in mensagem and "Ollama" in mensagem
    assert "o que já foi feito" in mensagem.lower()
    # ⭐ E cada falha apareceu na tela antes: silêncio é o que fez o editor esperar.
    assert tipos.count("progresso") >= S.FALHAS_SEGUIDAS_ATE_DESISTIR


def test_uma_falha_isolada_no_meio_do_turno_nao_derruba(monkeypatch):
    """⚠️ Repetir é normal (rede oscila): só falhas SEGUIDAS contam."""
    import json

    linhas = []
    for _ in range(S.FALHAS_SEGUIDAS_ATE_DESISTIR + 2):
        linhas.append(json.dumps({"type": "system", "subtype": "api_error",
                                  "error": {"message": "Connection error."}}))
        linhas.append(json.dumps({"type": "assistant",
                                  "message": {"content": [{"type": "text", "text": "ok"}]}}))
    linhas.append(json.dumps({"type": "result", "is_error": False}))
    s = S.Sessao("id", "http://x", [])
    _cli_que_diz(s, linhas)

    tipos = [t for t, _ in s.perguntar("oi")]
    s.encerrar()
    assert "erro" not in tipos and tipos[-1] == "fim"


def test_modelo_local_com_o_ollama_fora_do_ar_nao_gasta_o_turno(monkeypatch):
    """⭐ Uma batida de 3 s antes de subir o CLI, em vez de um turno pendurado."""
    from cicloassist.motor import claude as C
    from cicloassist.motor import percepcao as P

    monkeypatch.setattr(P, "endereco", lambda: "http://192.168.1.4:11434")
    monkeypatch.setattr(P, "responde", lambda url, timeout=3: False)
    with pytest.raises(C.MotorIndisponivel, match="não respondeu em http://192.168.1.4:11434"):
        C.ambiente_do_modelo("ollama:qwen3-vl:8b-instruct")

    monkeypatch.setattr(P, "responde", lambda url, timeout=3: True)
    nome, ambiente = C.ambiente_do_modelo("ollama:qwen3-vl:8b-instruct")
    assert nome == "qwen3-vl:8b-instruct"
    assert ambiente["ANTHROPIC_BASE_URL"] == "http://192.168.1.4:11434"


# ── o motor do Mac (2026-10-22) ──────────────────────────────────────────────

class _ProcDoPrimeiroTurno:
    """Um CLI recém-criado que o editor mandou parar: stdout acaba sem `result`."""

    def __init__(self):
        import io
        self.stdin = io.StringIO()
        self.stdout = iter([])
        self.stderr = None

    def poll(self):
        return 0

    def kill(self):
        pass

    def wait(self, timeout=None):
        return 0


def test_parar_o_PRIMEIRO_turno_e_cancelado_e_nao_erro(monkeypatch):
    """⛔⛔ Em campo: o editor parou um turno do Qwen e leu "O Claude encerrou sem
    responder". O primeiro turno de toda conversa nova passa por `_turno_ja_de_pe`, que
    não tinha a checagem de cancelamento."""
    s = S.Sessao("id", "http://x", [], S._config.LOCAL + "qwen3-vl:8b-instruct")
    s._proc = _ProcDoPrimeiroTurno()
    s._cancelado.set()
    eventos = list(s._turno_ja_de_pe("oi"))
    assert [t for t, _ in eventos if t != "progresso"] == ["cancelado"]


def test_as_frases_de_falha_dizem_quem_responde():
    assert S.Sessao("id", "http://x", [], S._config.LOCAL + "qwen3-vl")._quem() == \
        "O modelo do Mac"
    assert S.Sessao("id", "http://x", [], "claude-sonnet-5")._quem() == "O Claude"


def test_o_motor_do_mac_avisa_que_vai_ler_o_pedido_antes_de_responder():
    """⭐ O Ollama não manda evento nenhum enquanto lê o pedido (~135 s frio, medido)."""
    local = list(S.Sessao("id", "http://x", [], S._config.LOCAL + "qwen3-vl")._aviso_do_local())
    assert local and local[0][1]["pensando"] is True and "Mac" in local[0][1]["etapa"]
    assert list(S.Sessao("id", "http://x", [], "claude-sonnet-5")._aviso_do_local()) == []
