"""A conversa que dura — um processo vivo por projeto, e o fio que volta amanhã.

⭐ **Um turno deixa de ser um processo.** Antes, cada pergunta subia um `claude -p`,
respondia e morria: o editor pedia um corte e, na pergunta seguinte, o modelo não lembrava
de nada. Medido em 2026-09-10: no mesmo processo o 2º turno respondeu em **0,89 s** contra
1,95 s do 1º — **2,2× mais rápido**, e lembrando.

## Como a sessão é identificada

⭐ O id é **derivado do caminho do projeto**, não sorteado. Abrir o mesmo projeto amanhã dá
o mesmo id, sem guardar mapa em lugar nenhum.

## ⚠️⚠️ `--session-id` e `--resume` não são intercambiáveis, e errar é silencioso

Medido em 2026-09-10:

| | id que JÁ existe | id que NÃO existe |
|---|---|---|
| `--session-id` | ⛔ **começa conversa nova, sem erro** — o fio some calado | cria |
| `--resume` | retoma | falha limpo: `No conversation found with session ID` |

⇒ **Sempre tentar `--resume` primeiro, e cair para `--session-id` quando ele disser que
não existe.** O erro do `--resume` é honesto e barato; o do `--session-id` é invisível e
custa a conversa inteira do editor.

⭐ E assim **não guardamos estado nenhum**: quem sabe se a sessão existe é o próprio CLI.
Uma fonte de verdade, não duas.

## Morte de processo é rotina, não exceção

O CLI encerra sozinho depois de um tempo ocioso — o ADR 0004 pedia medir quanto. **Não é
preciso:** tratar a morte como normal e ressuscitar com `--resume` cobre o ocioso, o
travamento e o reinício do serviço com o mesmo código. Um desenho que não depende do número
é melhor que o número.
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
import threading
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Iterator

from ..servico import config as _config
from .claude import (SEM_CONTA, MotorIndisponivel, persona, _traduzir, achar_o_cli, ambiente_do_modelo,
                     frase_do_erro)

log = logging.getLogger("cicloassist.motor.sessao")

#: O que o CLI diz quando a sessão ainda não existe. É a deixa para criar em vez de retomar.
SEM_CONVERSA = "no conversation found"


def id_do_projeto(caminho: str) -> str:
    """Caminho do projeto → UUID estável.

    ⚠️ Minúsculas e sem barra final: no Windows `C:\\X` e `c:\\x\\` são a MESMA pasta, e
    sem normalizar o editor ganharia duas conversas para o mesmo projeto conforme o
    caminho chegasse de um jeito ou de outro.
    """
    normal = str(caminho).replace("/", "\\").rstrip("\\").lower()
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "cicloassist:" + normal))


def _fios() -> dict:
    guardado = _config.ler_estado().get("fios")
    return guardado if isinstance(guardado, dict) else {}


def fio_do_projeto(chave: str) -> str:
    """O id do fio VIVO daquele projeto — do disco, não derivado do caminho.

    ⛔⛔ **MEDIDO em 2026-09-12, e custou 121 mil tokens do editor.** `id_do_projeto()` é
    determinístico de propósito: abrir o mesmo projeto amanhã reencontra a conversa. Mas
    `recomecar()` só trocava o id NA MEMÓRIA do processo. Depois de o serviço reiniciar,
    `_sessoes` nasce vazio, e então:

      - `/clear` não achava sessão nenhuma e virava no-op (`havia sessão: False`);
      - o turno seguinte criava uma `Sessao` com o id derivado do caminho — o MESMO de
        sempre — e subia com `--resume`, trazendo de volta o fio inteiro.

    Em campo isso retomou uma conversa de **582.570 tokens** debaixo do Haiku, cuja janela
    é de 200 mil. O CLI auto-compactou por **70 segundos sem produzir uma palavra**,
    queimou 121 mil tokens e o editor ficou cinco minutos olhando "pensando".

    ⇒ O caminho só semeia o PRIMEIRO fio. Depois disso quem manda é o que está gravado.
    """
    return _fios().get(chave) or chave


def _gravar_fio(chave: str, id_: str) -> None:
    atual = dict(_fios())
    atual[chave] = id_
    _config.gravar_estado({"fios": atual})


#: Quantas falhas de API seguidas antes de desistir do turno.
FALHAS_SEGUIDAS_ATE_DESISTIR = 3


def _frase_do_motor_calado(modelo: str) -> str:
    """O que o editor precisa LER quando o servidor do modelo para de responder."""
    if _config.e_local(modelo):
        return ("O servidor do modelo no Mac parou de responder no meio do turno (o Ollama "
                "caiu, dormiu, ou a rede oscilou). O que já foi feito no projeto está feito. "
                "Religue o Ollama e peça de novo — ou escolha um modelo do Claude na barra.")
    return ("O servidor do modelo parou de responder no meio do turno. O que já foi feito "
            "está feito; peça de novo daqui a pouco.")


class Sessao:
    """A conversa de um projeto. Segura o subprocesso e o mantém vivo entre turnos."""

    def __init__(self, id_: str, url_do_mcp: str, ferramentas_de_leitura: list[str],
                 modelo: str = "", chave: str = "", nle: str = "avid", papel: str = "chat"):
        self.id = id_
        #: O editor desta conversa: decide a persona (`claude.persona`).
        self.nle = nle
        #: ⭐ "chat" ou "fluxos" (2026-11-03): a persona e, pelo endereço do MCP, as ferramentas.
        self.papel = papel
        #: A identidade do PROJETO — não muda quando o fio é jogado fora.
        self.chave = chave or id_
        self.url_do_mcp = url_do_mcp
        self.ferramentas = list(ferramentas_de_leitura)
        #: O que o editor escolheu no painel. Vazio = o padrão da conta dele.
        self.modelo = modelo
        self._proc: subprocess.Popen | None = None
        self._tmp: tempfile.TemporaryDirectory | None = None
        self._trava = threading.Lock()
        #: Quantos turnos já rodaram nesta instância — só para o log.
        self.turnos = 0
        #: ⛔⛔ Pedido de parada do editor. **Não é uma flag cooperativa**: o trabalho de um
        #: turno roda DENTRO do `claude -p`, então conferir um sinal entre as linhas do
        #: stdout só pararia de PINTAR. Parar de verdade é matar o subprocesso, e é o que
        #: `cancelar()` faz. O evento serve só para o laço saber que o EOF foi pedido, e
        #: não avisar "pronto" para um turno que ninguém terminou.
        self._cancelado = threading.Event()
        #: As últimas linhas de stderr do CLI, drenadas de contínuo. Tamanho fixo porque
        #: o que serve a um diagnóstico é o FIM, e um processo que vive horas encheria a
        #: memória com aviso repetido.
        self._stderr: deque[str] = deque(maxlen=200)

    # ── o processo ───────────────────────────────────────────────────────────

    def _comando(self, cli: str, config: Path, retomar: bool,
                 modelo: str | None = None) -> list[str]:
        """`modelo` é o que vai no `--model` — para o Mac, o nome SEM o `ollama:`."""
        modelo = self.modelo if modelo is None else modelo
        comando = [
            cli, "-p",
            "--system-prompt", persona(self.nle, self.papel),
            "--output-format", "stream-json",
            "--include-partial-messages",
            "--verbose",
            # ⭐ É esta flag que transforma o processo em conversa: a pergunta entra pelo
            #    stdin, e o processo continua vivo depois do `result`.
            "--input-format", "stream-json",
            "--mcp-config", str(config),
            "--strict-mcp-config",
            "--restricted",
            # ⛔⛔ Sem ferramenta nativa nenhuma — o `--restricted` deixa 29, com `Write` e
            #    `Edit` (medido, `spikes/o_que_o_restricted_deixa.py`). Ver `claude.py`.
            "--tools", "",
            "--permission-prompts", "host",
            "--permission-prompt-tool", "mcp__ciclo__pedir_confirmacao",
            "--allowedTools", ",".join(self.ferramentas),
        ]
        # ⭐ O modelo é escolha do editor, no dropdown do painel (config.json). Sem
        #   escolha, o CLI usa o padrão da conta dele — que é o certo para quem nunca
        #   abriu essa lista.
        if modelo:
            comando += ["--model", modelo]
        # ⭐ O esforço vale só para os modelos do Claude: o Ollama não pensa por orçamento.
        #   ⚠️ É lido ao SUBIR o processo — trocar no config vale na conversa seguinte.
        if not _config.e_local(self.modelo) and _config.esforco():
            comando += ["--effort", _config.esforco()]
        # ⚠️ Excludentes: o `--resume` já diz qual sessão é.
        comando += ["--resume", self.id] if retomar else ["--session-id", self.id]
        return comando

    def _subir(self, retomar: bool) -> subprocess.Popen:
        cli = achar_o_cli()   # levanta MotorIndisponivel, com ONDE procurou
        # ⭐ Claude ou Mac se decide AQUI, na partida: o endereço é do processo inteiro.
        modelo, ambiente = ambiente_do_modelo(self.modelo)
        if self._tmp is None:
            self._tmp = tempfile.TemporaryDirectory(prefix="cicloassist-")
        config = Path(self._tmp.name) / "mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"ciclo": {"type": "http", "url": self.url_do_mcp}}}),
            encoding="utf-8",
        )
        log.info("sessão %s: subindo (%s)", self.id[:8], "resume" if retomar else "nova")
        proc = subprocess.Popen(
            self._comando(cli, config, retomar, modelo),
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=ambiente,
        )
        self._drenar_stderr(proc)
        return proc

    def _drenar_stderr(self, proc: subprocess.Popen) -> None:
        """Lê o stderr continuamente, numa thread, para um buraco de tamanho fixo.

        ⛔⛔ **MEDIDO em 2026-09-12: foi isto que travou o painel por cinco minutos.**
        `_ler_stderr` fazia `proc.stderr.read()` — sem tamanho, ou seja, **até o EOF**. Num
        processo que fica VIVO entre turnos, esse EOF nunca chega: a chamada bloqueava para
        sempre. O turno já tinha recebido o `result`, o painel já mostrava o gasto, e a
        thread ficou parada ali até o editor cancelar e o processo morrer.

        ⚠️ E há o segundo lado, que ainda não mordeu mas é o mesmo cano: com `stderr=PIPE`
        e ninguém lendo, o buffer do sistema (~64 KB) enche e o CLI **bloqueia ao
        escrever** — o stdout para de sair e o turno congela sem nada acusando.

        ⇒ Drenar sempre, guardar só o fim (que é o que interessa num diagnóstico) e nunca
        mais chamar `read()` sem tamanho.
        """
        def moer() -> None:
            try:
                for linha in proc.stderr:
                    self._stderr.append(linha.rstrip())
            except Exception:
                pass

        self._stderr.clear()
        self._dreno = threading.Thread(target=moer, name="stderr", daemon=True)
        self._dreno.start()

    def _stderr_do_morto(self, proc: subprocess.Popen) -> str:
        """O stderr de um processo que JÁ saiu, depois de a drenagem alcançar o fim.

        ⚠️ O EOF do stdout chega antes de a thread de drenagem ler a última linha: sem
        esperar por ela, o motivo da morte ("unknown option") às vezes ainda não estava lá.
        """
        try:
            proc.wait(timeout=2)
        except Exception:
            pass
        dreno = getattr(self, "_dreno", None)
        if dreno is not None:
            dreno.join(timeout=2)
        return self._ler_stderr()

    def _vivo(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def encerrar(self) -> None:
        with self._trava:
            self._matar()
            if self._tmp is not None:
                self._tmp.cleanup()
                self._tmp = None

    def recomecar(self) -> str:
        """Joga a conversa fora e começa outra. Devolve o id novo.

        ⭐⭐ **Pedido do editor em 2026-09-11**, e a razão é dura: a janela de contexto
        enche. Um fio que já montou dois cortes carrega transcrições inteiras, e a partir
        de certo ponto o modelo passa mais tempo relendo do que trabalhando — quando não
        para de responder até a janela virar.

        ⛔⛔ **Id NOVO, e não só matar o processo.** O `--resume` retoma pelo id; matar o
        subprocesso e subir outro com o mesmo id traria o fio de volta inteiro, e o editor
        veria o "limpei" sem nada ter sido limpo. É a mesma armadilha que o docstring do
        módulo descreve do outro lado.

        ⚠️ O id do projeto deixa de ser derivável do caminho depois disto — e é o certo:
        o vínculo com o projeto continua sendo a CHAVE do dicionário de sessões; o id é a
        identidade do FIO, e o fio é outro.
        """
        with self._trava:
            self._matar()
            antigo = self.id
            self.id = str(uuid.uuid4())
            self.turnos = 0
            # ⛔⛔ Gravado, senão o "limpei" só vale até o serviço reiniciar — e o turno
            #    seguinte retoma o fio que o editor achava que tinha jogado fora.
            _gravar_fio(self.chave, self.id)
            log.info("sessão %s: recomeçada como %s", antigo[:8], self.id[:8])
            return self.id

    def cancelar(self) -> bool:
        """Mata o subprocesso agora. Devolve se havia algo rodando.

        ⛔⛔ **Sem `self._trava`, de propósito.** `perguntar()` segura essa trava o turno
        INTEIRO (ela é o que garante um turno por vez), então qualquer coisa que a peça
        para cancelar ficaria esperando justamente o que quer interromper. Era esse o
        defeito que já fazia `/limpar` no meio de um turno ficar pendurado.

        ⚠️ O fio NÃO se perde: só o processo morre, o id continua, e o turno seguinte
        retoma com `--resume`. O CLI pode ter gravado o turno parcial no histórico dele —
        isso não está medido.

        ⛔ E cancelar **não interrompe ferramenta já em execução**: no modo automático o
        `allow` já foi dado e a escrita na bin roda na thread do `/mcp`. Quem clica precisa
        saber disso — está escrito no botão.
        """
        proc = self._proc
        if proc is None or proc.poll() is not None:
            return False
        self._cancelado.set()
        log.info("sessão %s: cancelada pelo editor", self.id[:8])
        try:
            proc.kill()
        except Exception:
            return False
        return True

    def _matar(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
            self._proc.wait(timeout=5)
        except Exception:
            self._proc.kill()
        finally:
            self._proc = None

    # ── o turno ──────────────────────────────────────────────────────────────

    def _quem(self) -> str:
        """Quem responde, para as frases de falha. ⛔ Com o motor no Mac, dizer "o Claude"
        manda o editor procurar o defeito na assinatura (visto em campo, 2026-10-22)."""
        return "O modelo do Mac" if _config.e_local(self.modelo) else "O Claude"

    def _aviso_do_local(self) -> Iterator[tuple[str, dict]]:
        """⭐ O Ollama lê o pedido INTEIRO antes da primeira palavra, sem evento nenhum.
        MEDIDO: ~11 mil tokens de persona e ferramentas, ~135 s frio. Sem esta linha o
        painel ficava em "sem sinal" e o editor cancelava achando que o Mac não respondia
        (2026-10-22: o Mac respondia `ok` em 0,7 s pelo mesmo endereço)."""
        if _config.e_local(self.modelo):
            yield "progresso", {"etapa": "o modelo do Mac lê o pedido inteiro antes da "
                                         "primeira palavra — num pedido grande, 1 a 3 min "
                                         "sem sinal", "fracao": None, "pensando": True}

    def perguntar(self, texto: str) -> Iterator[tuple[str, dict]]:
        """Um turno. Gera eventos `(tipo, dado)` até o `result`, e o processo segue vivo."""
        with self._trava:
            yield from self._turno(texto, tentativa=1)

    def _turno(self, texto: str, tentativa: int) -> Iterator[tuple[str, dict]]:
        if not self._vivo():
            # ⭐ `--resume` primeiro, SEMPRE. Ver o docstring do módulo: usar
            #    `--session-id` numa sessão existente descarta o fio em silêncio.
            try:
                self._proc = self._subir(retomar=True)
            except MotorIndisponivel as e:
                yield "erro", {"mensagem": str(e)}
                return

        proc = self._proc
        assert proc is not None

        mensagem = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": texto}]},
        }
        try:
            proc.stdin.write(json.dumps(mensagem, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            # O processo morreu entre turnos — ocioso, travado, o que for. Rotina.
            log.info("sessão %s: processo morto ao escrever; ressuscitando", self.id[:8])
            self._matar()
            if tentativa <= 2:
                yield from self._turno(texto, tentativa + 1)
            else:
                yield "erro", {"mensagem": "Não consegui manter a conversa de pé."}
            return

        comeco = time.monotonic()
        yield from self._aviso_do_local()
        houve_texto = False
        falhou = False
        texto_do_erro = ""
        veio_o_result = False
        #: ⛔⛔ Falhas de API SEGUIDAS, sem nada entre elas. MEDIDO em campo (2026-09-17): o
        #: Ollama do Mac caiu, o CLI ficou repetindo `Connection error` e o turno nunca
        #: terminou — painel em "pensando…" por 40 minutos. O CLI repete até dez vezes e
        #: pode não emitir `result` nenhum; quem tem de desistir e dizer o motivo é a gente.
        falhas_seguidas = 0
        self._cancelado.clear()

        for linha in proc.stdout:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                log.warning("linha não-JSON no stdout: %s", linha[:200])
                continue

            if evento.get("type") == "result":
                veio_o_result = True
                falhou = bool(evento.get("is_error"))
                texto_do_erro = str(evento.get("result") or "") if falhou else ""
                # ⚠️⚠️ **Traduzir ANTES de sair do laço.** O `result` é o único evento que
                #    carrega `modelUsage` — contexto usado, janela e custo do turno. Este
                #    `break` estava acima da tradução, e o medidor de conversa do painel
                #    nascia vazio e ficava vazio para sempre: o dado existia, chegava, e
                #    era descartado uma linha antes de ser lido.
                #
                # ⚠️ O "erro" que o tradutor tira do `result` fica de fora: quem cuida da
                #    falha é o bloco abaixo, que sabe distinguir "o turno falhou" de "a
                #    sessão ainda não existia e é para criar". Deixar os dois emitirem
                #    poria dois erros na tela para um problema só.
                for saida in _traduzir(evento):
                    if saida[0] != "erro":
                        yield saida
                break

            if (evento.get("type") == "system"
                    and evento.get("subtype") in ("api_error", "api_retry")):
                falhas_seguidas += 1
            elif evento.get("type") != "system":
                falhas_seguidas = 0

            for saida in _traduzir(evento):
                if saida[0] == "texto":
                    houve_texto = True
                yield saida

            if falhas_seguidas >= FALHAS_SEGUIDAS_ATE_DESISTIR:
                log.warning("sessão %s: %d falhas seguidas do servidor do modelo; desistindo",
                            self.id[:8], falhas_seguidas)
                self._matar()
                yield "erro", {"mensagem": _frase_do_motor_calado(self.modelo)}
                return

        # ⛔⛔ ANTES de qualquer diagnóstico de falha. Um processo morto dá EOF no stdout,
        #    `falhou` fica False, e o turno cancelado seguia daqui para `yield "fim"` — ou
        #    seja, um turno que ninguém terminou se anunciava como terminado. Pior: sem
        #    texto e com stderr vazio, o ramo de baixo podia ler o cancelamento como "a
        #    sessão não existia" e RESSUSCITAR o fio com `--session-id`.
        if self._cancelado.is_set():
            self._cancelado.clear()
            self._matar()
            yield "cancelado", {"duracao_s": round(time.monotonic() - comeco, 2),
                                "houve_texto": houve_texto}
            return

        # ⛔⛔ EOF sem `result` é processo MORTO, nunca turno terminado. MEDIDO no macOS
        #    (2026-09-14): um `claude` velho no PATH recusava `--restricted` na partida, e o
        #    painel mostrava "pronto" com a resposta vazia — o motivo ficava no stderr, que
        #    ninguém lia. Com texto já na tela ou sem, o editor precisa ler que parou.
        if not veio_o_result:
            erro = self._stderr_do_morto(proc)
            if SEM_CONVERSA in erro.lower() and not houve_texto and tentativa <= 2:
                log.info("sessão %s: não existia; criando", self.id[:8])
                self._matar()
                self._proc = self._subir(retomar=False)
                yield from self._turno_ja_de_pe(texto)
                return
            self._matar()
            log.warning("sessão %s: o CLI saiu sem result: %s", self.id[:8], erro[-400:])
            yield "erro", {
                "mensagem": f"{self._quem()} parou no meio do turno." if houve_texto
                            else f"{self._quem()} encerrou sem responder.",
                "detalhe": erro[-400:],
            }
            return

        if falhou and not houve_texto:
            erro = self._ler_stderr()
            # ⚠️ A sessão ainda não existe: o `--resume` recusou, e agora é criar.
            if SEM_CONVERSA in erro.lower() and tentativa <= 2:
                log.info("sessão %s: não existia; criando", self.id[:8])
                self._matar()
                self._proc = self._subir(retomar=False)
                yield from self._turno_ja_de_pe(texto)
                return
            self._matar()
            # ⚠️ De novo, e não é redundância: o editor pode ter clicado em parar DEPOIS
            #    do teste lá em cima. Dizer "o Claude encerrou sem responder" a quem
            #    acabou de mandar parar troca a causa — e foi o que ele leu em campo.
            if self._cancelado.is_set():
                self._cancelado.clear()
                yield "cancelado", {"duracao_s": round(time.monotonic() - comeco, 2),
                                    "houve_texto": houve_texto}
                return
            # ⭐ Sem conta (2026-11-07): o CLI responde "Not logged in · Please run /login" no lugar do modelo — a frase
            #    diz onde entrar, em vez de "encerrou sem responder".
            if frase_do_erro(texto_do_erro) == SEM_CONTA:
                yield "erro", {"mensagem": SEM_CONTA}
                return
            yield "erro", {
                "mensagem": f"{self._quem()} encerrou sem responder.",
                "detalhe": erro[:400],
            }
            return

        self.turnos += 1
        yield "fim", {"duracao_s": round(time.monotonic() - comeco, 2),
                      "turno": self.turnos}

    def _turno_ja_de_pe(self, texto: str) -> Iterator[tuple[str, dict]]:
        """Repete o turno num processo recém-criado, sem tentar `--resume` de novo."""
        proc = self._proc
        assert proc is not None
        mensagem = {
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": texto}]},
        }
        comeco = time.monotonic()
        try:
            proc.stdin.write(json.dumps(mensagem, ensure_ascii=False) + "\n")
            proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            yield "erro", {"mensagem": f"Não consegui falar com {self._quem().lower()}."}
            return

        yield from self._aviso_do_local()
        veio_o_result = False
        for linha in proc.stdout:
            linha = linha.strip()
            if not linha:
                continue
            try:
                evento = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if evento.get("type") == "result":
                veio_o_result = True
                # ⛔ O mesmo defeito que o `_turno` já pagou: sair sem traduzir jogava fora
                #    o `modelUsage` do PRIMEIRO turno de toda conversa nova — sem gasto e
                #    sem janela. MEDIDO em 2026-09-16 (`spikes/o_ollama_como_motor.py`).
                for saida in _traduzir(evento):
                    if saida[0] != "erro":
                        yield saida
                break
            yield from _traduzir(evento)

        if not veio_o_result:
            # ⛔⛔ O cancelamento ANTES do erro, como no `_turno`. Este é o caminho do
            #    PRIMEIRO turno de toda conversa nova, e não tinha a checagem: o editor
            #    parou um turno do Qwen e leu "O Claude encerrou sem responder" (2026-10-22).
            if self._cancelado.is_set():
                self._cancelado.clear()
                self._matar()
                yield "cancelado", {"duracao_s": round(time.monotonic() - comeco, 2),
                                    "houve_texto": False}
                return
            # O mesmo buraco do `_turno`: processo morto não é turno terminado.
            erro = self._stderr_do_morto(proc)
            self._matar()
            yield "erro", {"mensagem": f"{self._quem()} encerrou sem responder.",
                           "detalhe": erro[-400:]}
            return

        self.turnos += 1
        yield "fim", {"duracao_s": round(time.monotonic() - comeco, 2),
                      "turno": self.turnos}

    def _ler_stderr(self) -> str:
        """O que o CLI reclamou, do buraco que a thread de drenagem enche.

        ⛔ NUNCA voltar a ler do pipe aqui: ver `_drenar_stderr`.
        """
        return '\n'.join(self._stderr)


# ── a sessão ativa ───────────────────────────────────────────────────────────

_sessoes: dict[str, Sessao] = {}
_trava = threading.Lock()


def do_projeto(caminho: str, url_do_mcp: str, ferramentas: list[str],
               modelo: str = "", nle: str = "avid", papel: str = "chat") -> Sessao:
    """A sessão daquele projeto, criada na primeira vez e reusada depois."""
    chave = id_do_projeto(caminho)
    with _trava:
        s = _sessoes.get(chave)
        if s is None:
            # ⭐ O caminho dá a CHAVE; o disco dá o FIO. Ver `fio_do_projeto`.
            s = Sessao(fio_do_projeto(chave), url_do_mcp, ferramentas, modelo,
                       chave=chave, nle=nle, papel=papel)
            _sessoes[chave] = s
        else:
            # O endereço do MCP carrega um segredo sorteado a cada arranque do serviço.
            s.url_do_mcp = url_do_mcp
            s.ferramentas = list(ferramentas)
            # ⭐⭐ **Trocar de modelo derruba o processo, de propósito.** O modelo é
            #    escolhido na PARTIDA do `claude -p`; mudar a flag sem reiniciar não muda
            #    nada, e o painel mostraria um nome que não corresponde a quem está
            #    respondendo. O fio da conversa não se perde: o `--resume` o retoma no
            #    turno seguinte (ADR 0004).
            # ⛔⛔ Sem projeto aberto em nenhum dos dois, o Avid e o Premiere caem na MESMA
            #    chave de sessão. Sem isto, um turno do Premiere reaproveitaria o processo do
            #    Avid — com `persona("avid")` no `--system-prompt` e a lista de ferramentas
            #    do Avid já apresentada: o modelo ouviria que está dentro do Media Composer
            #    enquanto o editor está no Premiere.
            if nle != s.nle:
                log.info("sessão %s: editor %s → %s; reiniciando o processo",
                         s.id[:8], s.nle, nle)
                s.nle = nle
                s._matar()
            if _config.e_local(modelo) != _config.e_local(s.modelo):
                # ⛔⛔ Entre Claude e Mac, conversa NOVA. O `--resume` levaria um fio de
                #    centenas de milhares de tokens para um servidor que carrega 40 mil —
                #    e o Ollama corta o excesso CALADO: o modelo perderia o começo da
                #    conversa e o editor leria "o modelo local é burro". E para avaliar o
                #    modelo local, a resposta tem de ser só dele.
                log.info("sessão %s: motor %s → %s; conversa nova", s.id[:8],
                         s.modelo or "(padrão)", modelo or "(padrão)")
                s.cancelar()
                s.recomecar()
                s.modelo = modelo
            elif modelo != s.modelo:
                log.info("sessão %s: modelo %s → %s; reiniciando o processo",
                         s.id[:8], s.modelo or "(padrão)", modelo or "(padrão)")
                s.modelo = modelo
                s._matar()
        return s


def cancelar(caminho: str) -> bool:
    """Interrompe o turno em andamento daquele projeto."""
    s = _sessoes.get(id_do_projeto(caminho))
    # ⚠️ Sem o `_trava` do módulo: `do_projeto()` o segura, e travar aqui recriaria o
    #    mesmo impasse que `cancelar()` existe para desfazer.
    return bool(s and s.cancelar())


def recomecar(caminho: str) -> bool:
    """Limpa a conversa daquele projeto. Devolve se havia alguma.

    ⛔⛔ **Funciona mesmo sem `Sessao` viva na memória** — e é esse o ponto. Antes, um
    `/clear` logo depois de o serviço reiniciar não achava nada em `_sessoes`, devolvia
    `havia sessão: False` e **não limpava coisa alguma**; o turno seguinte então retomava
    pelo id derivado do caminho o fio que o editor acabara de mandar jogar fora. Em campo
    isso trouxe de volta 582 mil tokens debaixo do Haiku. Ver `fio_do_projeto`.
    """
    chave = id_do_projeto(caminho)
    # ⭐ Mata ANTES de pedir a trava. `Sessao.recomecar()` faz `with self._trava`, e um
    #   `/limpar` durante um turno ficava pendurado até o turno acabar — segurando de
    #   quebra o `_trava` do módulo e travando `do_projeto()` de qualquer outra aba.
    s = _sessoes.get(chave)
    if s is not None:
        s.cancelar()
    with _trava:
        s = _sessoes.get(chave)
        if s is not None:
            s.recomecar()
            return True
        # Sem sessão na memória: o fio pode estar vivo do mesmo jeito, gravado no disco.
        havia = bool(_fios().get(chave))
        _gravar_fio(chave, str(uuid.uuid4()))
        log.info("fio do projeto %s jogado fora sem sessão viva (havia: %s)",
                 chave[:8], havia)
        return havia


def encerrar_todas() -> None:
    with _trava:
        for s in list(_sessoes.values()):
            s.encerrar()
        _sessoes.clear()
