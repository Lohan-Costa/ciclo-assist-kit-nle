"""Spike — o portão que não espera: o modelo entende que deve parar e aguardar?

    python spikes/portao_sem_relogio.py

## O que aconteceu antes, e por que este spike existe

Em 2026-09-10, no primeiro teste de campo, `montar_corte` "deu timeout" três vezes
seguidas — sempre que o editor **não estava na frente do computador** quando o cartão de
aprovação apareceu. Com ele presente, a mesma chamada com os mesmos 14 cortes passou em
5,5 s. O portão bloqueava a chamada MCP até o clique, e quem decidia o prazo era o CLI:

> **MEDIDO (2026-09-10, CLI 2.1.267):** sem `MCP_TOOL_TIMEOUT`, o CLI desiste de uma
> chamada de ferramenta em **60,0 s**. Com a variável em 20000, desiste em **20,0 s**
> exatos — ela vale. O erro que chega no modelo pelo caminho padrão é
> `"The operation timed out."`, sem uma palavra sobre permissão.

Sessenta segundos para ler um plano de catorze cortes e decidir. E o modelo, lendo um
timeout genérico, concluía que o servidor estava quebrado: quebrava o plano em lotes e
criava sequências parciais na bin do editor.

⛔ **A correção não foi esticar o prazo — foi tirar o relógio** (ADR 0008). O portão
responde na hora, o turno termina, e o cartão espera o editor pelo tempo que for.

## O elo que este spike prova

Tirar a espera criou um risco novo, e ele é de COMPORTAMENTO, não de código: o portão
agora responde `deny` a um pedido que não foi recusado. Se o modelo ler isso como "não",
ele pode pedir desculpa e tentar outro caminho; se ler como "falhou", pode repetir a
chamada e empilhar cartões. O que se mede aqui:

1. a chamada volta **na hora** (nada de bloquear);
2. o pedido vira **uma** pendência — não duas, mesmo com o modelo achando o `deny` esquisito;
3. o turno **termina** sozinho, com o modelo dizendo que está esperando;
4. o clique do editor, **depois** do turno morto, executa a ação de verdade;
5. no turno seguinte o modelo **sabe** que já foi feito, e não oferece fazer de novo.

Sai `0` se os cinco passarem.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.mcp.registro import Ferramenta, FERRAMENTAS, somente_leitura  # noqa: E402
from cicloassist.motor.claude import _ambiente_do_cli  # noqa: E402
from cicloassist.servico import pendencias as _pend  # noqa: E402
from cicloassist.servico import turno as _turno  # noqa: E402
from cicloassist.servico.http import subir  # noqa: E402
from cicloassist.servico.rotas import url_do_mcp  # noqa: E402

#: Quanto tempo o portão pode levar para responder. Generoso: o que se quer flagrar é
#: BLOQUEIO (dezenas de segundos), não latência.
RESPOSTA_IMEDIATA_S = 5.0

PEDIDO = "Anote no caderno do projeto a frase: o portao nao espera."

#: O que a ferramenta de escrita registrou, se chegou a rodar.
ESCRITO: list[str] = []


def escrever_nota(texto: str) -> dict:
    """A escrita que só pode acontecer DEPOIS do clique.

    ⚠️ Não se usa `montar_corte` nem `anotar_o_que_vi` aqui, embora sejam as escritas do
    produto: as duas dependem do Media Composer aberto, e o modelo tenderia a LER o
    material antes. Um erro de ponte gRPC abortaria o turno antes de o cartão aparecer —
    e o spike morreria por um motivo que não tem nada a ver com o portão.
    """
    ESCRITO.append(texto)
    return {"ok": True, "gravado": texto}


FERRAMENTAS["escrever_nota"] = Ferramenta(
    nome="escrever_nota",
    descricao="Grava uma nota de texto no caderno do projeto.",
    esquema={
        "type": "object",
        "properties": {"texto": {"type": "string"}},
        "required": ["texto"],
    },
    funcao=escrever_nota,
    escreve=True,
)


class Conversa:
    """Um `claude -p` vivo, para dar dois turnos na mesma sessão."""

    def __init__(self, porta: int):
        cli = shutil.which("claude")
        if not cli:
            sys.exit("claude não encontrado no PATH.")
        self._tmp = tempfile.TemporaryDirectory()
        config = Path(self._tmp.name) / "mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"ciclo": {"type": "http", "url": url_do_mcp(porta)}}}),
            encoding="utf-8",
        )
        self.proc = subprocess.Popen(
            [
                cli, "-p",
                "--output-format", "stream-json", "--verbose",
                "--input-format", "stream-json",
                "--mcp-config", str(config), "--strict-mcp-config",
                "--restricted",
                "--permission-prompts", "host",
                "--permission-prompt-tool", "mcp__ciclo__pedir_confirmacao",
                "--allowedTools", ",".join(somente_leitura()),
            ],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            env=_ambiente_do_cli(),
        )

    def turno(self, texto: str) -> dict:
        """Manda uma pergunta e devolve o que aconteceu até o `result`."""
        self.proc.stdin.write(json.dumps({
            "type": "user",
            "message": {"role": "user", "content": [{"type": "text", "text": texto}]},
        }, ensure_ascii=False) + "\n")
        self.proc.stdin.flush()

        comeco = time.monotonic()
        dito, chamadas = [], []
        for linha in self.proc.stdout:
            linha = linha.strip()
            if not linha:
                continue
            try:
                ev = json.loads(linha)
            except json.JSONDecodeError:
                continue
            if ev.get("type") == "assistant":
                for b in ev.get("message", {}).get("content", []):
                    if b.get("type") == "text" and b.get("text"):
                        dito.append(b["text"])
                    elif b.get("type") == "tool_use":
                        chamadas.append(b.get("name", ""))
            elif ev.get("type") == "result":
                break
        return {
            "texto": " ".join(dito).strip(),
            "chamadas": chamadas,
            "segundos": round(time.monotonic() - comeco, 1),
        }

    def fechar(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=5)
        except Exception:
            self.proc.kill()
        self._tmp.cleanup()


def main() -> int:
    servidor = subir(0)
    porta = servidor.server_address[1]
    _pend.esquecer_tudo()

    turno = _turno.comecar()
    cartoes: list[dict] = []
    tempo_da_chamada: dict[str, float] = {}

    def escutar():
        for tipo, dado in turno.eventos():
            if tipo == "aprovacao":
                tempo_da_chamada["cartao"] = time.monotonic()
                cartoes.append(dado)
                print(f"    · cartão na tela: {dado['ferramenta']}")

    threading.Thread(target=escutar, daemon=True).start()

    conversa = Conversa(porta)
    try:
        print("=" * 74)
        print("TURNO 1 — o modelo pede uma escrita; o portão manda esperar")
        print("=" * 74)
        tempo_da_chamada["inicio"] = time.monotonic()
        primeiro = conversa.turno(PEDIDO)
        _turno.terminar(turno)

        abertas = _pend.abertas()
        print(f"  turno durou ..... {primeiro['segundos']}s")
        print(f"  ferramentas ..... {primeiro['chamadas']}")
        print(f"  pendências ...... {len(abertas)}")
        print(f"  escreveu? ....... {ESCRITO}  ← precisa estar VAZIO")
        print(f"  disse ........... {primeiro['texto'][:220]}")

        # ⭐ O teto do "não bloqueou": o turno inteiro tem de caber MUITO abaixo do prazo
        #   do CLI. Se o portão voltasse a esperar, este número passaria de 60 s.
        nao_bloqueou = primeiro["segundos"] < 60
        um_cartao = len(abertas) == 1
        nao_escreveu = not ESCRITO
        pediu_uma_vez = primeiro["chamadas"].count("mcp__ciclo__escrever_nota") == 1

        print()
        print("=" * 74)
        print("O EDITOR CLICA — muito depois, com o turno já morto")
        print("=" * 74)
        if not abertas:
            print("  ✗ não há pendência para clicar")
            return 1
        resultado = _pend.decidir(abertas[0].id, True)
        print(f"  resultado ....... {resultado}")
        print(f"  escreveu? ....... {ESCRITO}  ← agora precisa ter a nota")
        executou = bool(ESCRITO) and resultado.get("ok")

        print()
        print("=" * 74)
        print("TURNO 2 — o modelo fica sabendo pelo recado, sem turno só para isso")
        print("=" * 74)
        recados = _pend.recados()
        print(f"  recado .......... {recados}")
        turno2 = _turno.comecar()
        threading.Thread(target=lambda: list(turno2.eventos()), daemon=True).start()
        pergunta = "(entretanto: " + " ".join(recados) + ")\n\nA nota já está gravada?"
        segundo = conversa.turno(pergunta)
        _turno.terminar(turno2)
        print(f"  ferramentas ..... {segundo['chamadas']}")
        print(f"  disse ........... {segundo['texto'][:220]}")
        sabe_que_foi_feito = not any("escrever_nota" in c for c in segundo["chamadas"])

        print()
        print("=" * 74)
        for rotulo, passou in [
            ("a chamada não bloqueou", nao_bloqueou),
            ("virou UMA pendência", um_cartao),
            ("não pediu duas vezes", pediu_uma_vez),
            ("nada foi escrito antes do clique", nao_escreveu),
            ("o clique executou de verdade", executou),
            ("o modelo soube sem refazer", sabe_que_foi_feito),
        ]:
            print(f"  {'✓' if passou else '✗'} {rotulo}")

        tudo = all([nao_bloqueou, um_cartao, pediu_uma_vez, nao_escreveu, executou,
                    sabe_que_foi_feito])
        print()
        print(f"  {'PASSOU ✓' if tudo else 'FALHOU ✗'}")
        return 0 if tudo else 1
    finally:
        conversa.fechar()
        _pend.esquecer_tudo()
        servidor.shutdown()
        servidor.server_close()


if __name__ == "__main__":
    raise SystemExit(main())
