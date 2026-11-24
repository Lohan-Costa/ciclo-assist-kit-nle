"""O AGENTE DO PILOTO: entra quando o script desiste, olha a tela e decide (autor, 2026-11-08).

O script continua sendo o caminho: rápido, medido e sem custo de decisão. O agente é chamado só quando ele não soube o que fazer.

⛔⛔ **O modelo sugere, o CÓDIGO decide** (`julgar`). A regra da casa era "diálogo desconhecido = foto e PARE"; o autor autorizou clicar, e o limite
ficou aqui, onde o texto de um diálogo não alcança. Fora desta lista nada é clicado, por mais convicto que o modelo esteja:
- botão que ele não listou entre os que viu;
- janela cujo texto fala em apagar, substituir, perder, ou em falha do programa (o OK de "apagar 5 clipes?" apaga);
- OK, Close e Continue quando há outra escolha na janela: aí é uma pergunta, e a pergunta é do editor;
- "Don't warn me again" fora do aviso de teclado, que é onde o autor o mandou clicar: em outro aviso, ele calaria aquele aviso para sempre.

⛔ O clique passa pelo localizador, com a cruz (`localizador.localizar`): ponto sem certeza alta ou não confirmado não é clicado.
⛔ Mesmo botão na mesma janela de novo = parar (banco, 2026-10-17: um clique repetido 10× no vazio). Teto de `MAX_CONSULTAS` por operação.
⛔ F12, janela cortada e operação recusada de saída não chamam o agente (`pode_socorrer`): o editor mandou parar, ou o layout é dele.
⭐ `perguntar` não espera aqui dentro: a operação termina com a frase, e o fluxo oferece "tentar de novo" (ADR 0008: o editor não tem prazo).
⭐ Cada consulta deixa a foto e a decisão em `<dados>/piloto/socorro/`: é de onde sai o próximo caso que o script aprende a resolver sozinho.
"""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from ..motor import agentes as _agentes
from ..servico import config as _config
from . import borda as _borda
from . import espaco as _espaco
from . import localizador, maos, tela

log = logging.getLogger("cicloassist.piloto.auxilio")

AGENTE = "agente-do-piloto"
ACOES = ("esperar", "repetir", "clicar", "perguntar", "parar")
MAX_CONSULTAS = 4
ESPERA_S = 15

_SO_SE_UNICO = frozenset({"ok", "close", "continue", "dismiss"})
_ADIAR = frozenset({"not now", "later", "remind me later"})
_NAO_AVISAR = frozenset({"don't warn me again"})
_TECLADO = re.compile(r"keyboard|teclado|input language|layout", re.I)
#: ⭐ MEDIDO (2026-11-19, MC 2024.6, Windows, 1º arranque depois de reiniciar a máquina): ao entrar no projeto, "This volume has
#: not yet been mounted by the application. You can either mount all volumes or load another project." — Mount All
#: Volumes · Load Another Project. Montar os volumes só faz o MC ler os discos; é a resposta que deixa o projeto abrir.
_MONTAR = frozenset({"mount all volumes"})
_NAO_MONTADO = re.compile(r"not (yet )?been mounted|mount all volumes", re.I)
_RISCO = re.compile(r"\b(delet|remov|overwrit|discard|eras|replac|revert|apag|exclu|substitu|sobrescr|descart|fatal|exception|access[ _]violation|assert|crash|lose\b|lost\b|perd)", re.I)

Relatar = Callable[[str, float | None, str], None]


class TelaInesperada(Exception):
    """Marca o erro de "a tela não está como o script esperava": é o que autoriza chamar o agente."""


class PrecisaDoEditor(RuntimeError):
    """A operação parou e a frase diz o que o editor precisa ver."""


@dataclass(frozen=True)
class Olhar:
    hwnd: int                                           # a janela do programa que ficou na frente
    monitor: tuple[int, int, int, int]                  # o que vai na foto
    dialogo: tuple[int, int, int, int] | None = None    # onde procurar o botão, quando se sabe


def _norma(t: Any) -> str:
    return " ".join(str(t).replace("’", "'").replace("…", "").replace("...", "").casefold().split())


def preferir_nao_avisar(r: dict[str, Any]) -> dict[str, Any]:
    """⛔ MEDIDO (2026-11-19, aviso de teclado sobre a Select Project, MC 2024.6): o agente sugeriu OK, e OK passava
    como "a única escolha" porque a conta tira o "Don't warn me again" das alternativas — o aviso voltaria na próxima
    abertura. No aviso de TECLADO a resposta da casa é o "Don't warn me again" (autor; memória `mc-abre-sem-foco`):
    a sugestão de OK/Close/Continue vira esse botão. Fora do teclado, nada muda (calar outro aviso é do editor).

    ⭐ E o aviso de volume não montado (`_NAO_MONTADO`): a resposta é SEMPRE "Mount All Volumes" (autor, 2026-11-19),
    e não depende do que o modelo sugerir — MEDIDO na 2ª rodada: ele viu o aviso certo e preferiu PERGUNTAR."""
    montar = next((b for b in r.get("botoes") or [] if _norma(b) in _MONTAR), None)
    if montar and _NAO_MONTADO.search(f"{r.get('texto_da_janela') or ''} {r.get('tela') or ''}"):
        return dict(r, acao="clicar", botao=montar)
    if _norma(r.get("acao")) != "clicar" or _norma(r.get("botao")) not in _SO_SE_UNICO:
        return r
    if not _TECLADO.search(f"{r.get('texto_da_janela') or ''} {r.get('tela') or ''}"):
        return r
    calar = next((b for b in r.get("botoes") or [] if _norma(b) in _NAO_AVISAR), None)
    return dict(r, botao=calar) if calar else r


def julgar(r: dict[str, Any]) -> tuple[str, str]:
    """`(ação que vale, por que mudou)`. Puro: a cerca inteira mora aqui."""
    acao = _norma(r.get("acao"))
    if acao not in ACOES:
        return "parar", f"resposta com ação desconhecida: {acao!r}"
    if acao != "clicar":
        return acao, ""
    botao, texto = _norma(r.get("botao")), f"{r.get('texto_da_janela') or ''} {r.get('tela') or ''}"
    botoes = {_norma(b) for b in r.get("botoes") or []}
    if not botao or botao not in botoes:
        return "perguntar", "o botão indicado não está entre os que ele viu na janela"
    if _RISCO.search(texto):
        return "perguntar", "o texto da janela fala em apagar, substituir, perder trabalho ou em falha do programa"
    if botao in _NAO_AVISAR:
        return ("clicar", "") if _TECLADO.search(texto) else ("perguntar", "calar este aviso para sempre é decisão sua")
    if botao in _ADIAR:
        return "clicar", ""
    if botao in _MONTAR:
        return ("clicar", "") if _NAO_MONTADO.search(texto) else ("perguntar", "montar volumes fora do aviso conhecido é decisão sua")
    if botao in _SO_SE_UNICO:
        return ("perguntar", "a janela oferece outra escolha") if botoes - {botao} - _NAO_AVISAR else ("clicar", "")
    return "perguntar", f"o botão {r.get('botao')!r} não está entre os que posso clicar sozinho"


def pode_socorrer(e: BaseException) -> bool:
    """Só o que é "a tela não está como eu esperava". ⭐ O erro embrulhado guarda a causa em `__cause__`."""
    if isinstance(e, TelaInesperada):
        return True
    causa = e.__cause__
    return isinstance(causa, localizador.NaoAchei) and not isinstance(causa, localizador.JanelaCortada)


def _sem_relato(*_):
    return None


class Socorro:
    """As consultas de uma operação."""

    def __init__(self, programa: str, objetivo: str, olhar: Callable[[], Olhar], relatar: Relatar | None = None):
        self.programa, self.objetivo, self.olhar = programa, objetivo, olhar
        self.relatar = relatar or _sem_relato
        self.custo = 0.0
        self.decisoes: list[dict[str, Any]] = []
        self.clicados: set[tuple[str, str]] = set()

    @property
    def consultas(self) -> int:
        return len(self.decisoes)

    def _guardar(self, jpg: bytes, registro: dict[str, Any]) -> str:
        """⚠️ Um defeito ao guardar não pode derrubar a operação."""
        try:
            pasta = _config.pasta() / "piloto" / "socorro"
            pasta.mkdir(parents=True, exist_ok=True)
            carimbo = time.strftime("%Y%m%d-%H%M%S")
            foto = pasta / f"{carimbo}_{self.consultas}.jpg"
            foto.write_bytes(jpg)
            with (pasta / "decisoes.jsonl").open("a", encoding="utf-8") as f:
                f.write(json.dumps({"quando": carimbo, "programa": self.programa, "objetivo": self.objetivo, "foto": foto.name, **registro}, ensure_ascii=False) + "\n")
            return str(foto)
        except OSError as e:
            log.warning("não guardei a decisão do agente do piloto: %s", e)
            return ""

    def _consultar(self, falha: str) -> tuple[dict[str, Any], str, str, str]:
        o = self.olhar()
        jpg = tela.jpeg(tela.fotografar().recorte(o.monitor).img, localizador.LARGURA)
        agente = _agentes.buscar(AGENTE)
        pedido = _agentes.montar_pedido(agente, {"programa": self.programa, "objetivo": self.objetivo, "o_que_falhou": falha,
                                                 "ja_tentado": [f"{d['acao']} {d.get('botao') or ''}".strip() for d in self.decisoes]})
        r, _s, custo = localizador.perguntar(jpg, pedido, sistema=agente.instrucao)
        self.custo += custo
        _agentes.conferir_saida(agente, r)
        r = preferir_nao_avisar(r)
        acao, recusa = julgar(r)
        foto = self._guardar(jpg, {"falha": falha, "resposta": r, "vale": acao, "recusa": recusa, "custo_usd": custo})
        self.decisoes.append({"tela": r["tela"], "sugeriu": r["acao"], "acao": acao, "botao": r["botao"], "recusa": recusa, "foto": foto})
        log.info("agente do piloto: %s (sugeriu %s) · %s", acao, r["acao"], r["tela"])
        return r, acao, recusa, foto

    def _esperar(self) -> None:
        for _ in range(ESPERA_S):
            maos.freio()
            time.sleep(1.0)

    def _clicar(self, r: dict[str, Any]) -> None:
        chave = (_norma(r["botao"]), _norma(r["texto_da_janela"]))
        if chave in self.clicados:
            raise PrecisaDoEditor(f"O agente do piloto já clicou em '{r['botao']}' nesta janela e ela continuou na tela: {r['tela']}. Resolva na tela e mande tentar de novo.")
        self.clicados.add(chave)
        o = self.olhar()
        alvo = f"o botão '{r['botao']}' da janela de aviso do {self.programa}. O ponto é sobre esse botão, NUNCA sobre outro"
        self.relatar(f"o agente do piloto vai clicar em {r['botao']}", None, "")
        a = localizador.localizar(tela.fotografar(), alvo, regiao=o.dialogo or o.monitor)
        self.custo += a.custo_usd
        maos.clicar(o.hwnd, a.x, a.y)
        time.sleep(1.0)

    def tratar(self, falha: str) -> None:
        """Volta quando vale tentar de novo; senão levanta `PrecisaDoEditor`."""
        if self.consultas >= MAX_CONSULTAS:
            raise PrecisaDoEditor(f"{falha} (o agente do piloto já olhou a tela {MAX_CONSULTAS} vezes nesta operação e não resolveu)")
        self.relatar("o script não soube continuar: o agente do piloto está olhando a tela", None, "")
        try:
            # ⛔ MEDIDO (2026-11-09, teste pilotado): a falha pode vir antes de a operação tirar a janela do app da frente, e o agente fotografou o próprio Ciclo Assist por cima do diálogo.
            with _borda.acesa(f"CICLO ASSIST  ·  o agente do piloto está olhando o {self.programa}  ·  F12 para"), _espaco.tela_livre():
                r, acao, recusa, foto = self._consultar(falha)
                if acao == "esperar":
                    self.relatar("o agente do piloto viu o programa trabalhando: esperando", None, "")
                    self._esperar()
                    return
                if acao == "repetir":       # ⭐ A tela está normal e o script errou o ponto (medido: o menu File, colado à borda, reprovado na conferência)
                    self.relatar("o agente do piloto não viu nada atrapalhando: tentando de novo", None, "")
                    time.sleep(1.0)
                    return
                if acao == "clicar":
                    self._clicar(r)
                    return
        except (localizador.NaoAchei, _agentes.AgenteFalhou, tela.SemTela, maos.ForaDeFoco, maos.Parado) as e:
            raise PrecisaDoEditor(f"{falha} (o agente do piloto também não conseguiu: {e})") from e
        pedido = r["pergunta"] or recusa or r["motivo"]
        raise PrecisaDoEditor(f"O agente do piloto parou: {r['tela']} {pedido} Resolva na tela e mande tentar de novo." + (f" (foto: {foto})" if foto else ""))

    def anotar(self, resultado: Any) -> Any:
        if self.consultas and isinstance(resultado, dict):
            resultado["custo_usd"] = round(float(resultado.get("custo_usd") or 0) + self.custo, 4)
            resultado["agente_do_piloto"] = {"consultas": self.consultas, "custo_usd": round(self.custo, 4), "decisoes": self.decisoes}
        return resultado


def com_socorro(programa: str, objetivo: str, tentar: Callable[[], Any], falha: type[Exception], olhar: Callable[[], Olhar], relatar: Relatar | None = None) -> Any:
    """Roda `tentar`; se a tela surpreender o script, chama o agente e tenta de novo. ⛔ `tentar` tem de ser repetível: olha o estado antes de agir."""
    socorro = Socorro(programa, objetivo, olhar, relatar)
    while True:
        try:
            resultado = tentar()
        except falha as e:
            if not pode_socorrer(e):
                raise
            try:
                socorro.tratar(str(e))
            except PrecisaDoEditor as p:
                raise falha(str(p)) from e
            continue
        return socorro.anotar(resultado)
