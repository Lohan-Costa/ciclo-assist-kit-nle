"""O EXECUTOR: um fluxo de várias operações, rodado por código nosso, não pelo modelo (F1).

Plano: `docs/plano/2026-10-31-o-assist-operador.md`. A queixa que isto fecha é a do autor de
2026-09-20 — *"cada modelo está interpretando a sua forma de execução… precisamos ser mais
previsíveis"*. Medido em 2026-11-01: dirigido turno a turno, o modelo chamou câmera e som em
PARALELO, tentou o sync 3× com o mesmo erro e pediu ao editor gestos que não eram dele.

⇒ **O modelo PLANEJA; quem EXECUTA é este módulo.** O plano é DADO (banco,
`transversal/modelo-de-execucao-de-agente.md`, "plano de ações como dado"):

```json
{"nome": "Preparar diária D01",
 "parametros": {"pasta": "C:/…/D01", "projeto": "D01"},
 "passos": [
   {"id": "conv", "op": "converter_para_opatom", "args": {"projeto": "{projeto}", "pasta": "{pasta}"}},
   {"id": "cam",  "op": "importar_masters_opatom", "args": {"pasta": "{conv.pasta}", "bin": "D01 CAMERA"}}]}
```

- `op` é uma FERRAMENTA registrada (`mcp/registro.py`) — as operações com nome já existem, com
  a conferência delas; o executor as COMPÕE e não reescreve nenhuma.
- `{nome}` é um parâmetro; `{passo.campo}` é a SAÍDA de um passo anterior. Não há outra
  sintaxe: nada de expressão, nada de código. ⛔ Plano vindo de fora (receita compartilhada) é
  entrada não confiável, e a única coisa que ele consegue fazer é chamar as nossas operações.

## Cada passo: referências → conferência → ação → conferido

⚠️ A conferência de um passo só faz sentido no mundo em que ele vai rodar: o `conferir` do
`importar_masters_opatom` olha a pasta MXF que o passo anterior ainda vai CRIAR. Por isso antes
do cartão só se confere a ESTRUTURA do plano e o PRIMEIRO passo; os outros, logo antes de rodar.

⚠️ As ferramentas não levantam quando falham: devolvem `{"erro": …}`. Isso é falha do passo.
`problemas` não vazio é um passo que andou e deixou algo de fora — vira AVISO e o fluxo segue
(o plano: "arquivo ilegível no meio da pasta: seguir com os outros e dizer quais").

## Os estados, e o que sobrevive a quê

## Ramos (fase N3 do plano `2026-11-08-janela-de-nodes.md`)

`depois_de: [ids]` diz de quem o passo depende; sem ele, do passo anterior da lista (é o que mantém as receitas em linha iguais). `se: {campo: "passo.campo", e: sim|nao|igual,
valor}` diz quando o passo roda. Sem expressão, de propósito. Passo cujo `se` não foi atendido, ou cujos antecessores ficaram todos fora, fica `fora` e o fluxo segue.
⭐ A lista está em ordem topológica (`validar` exige), e por isso continua rodando um passo de cada vez: dois ramos sem condição rodam um depois do outro.
⛔ Rodar dois ao mesmo tempo não foi feito: abrir o MC e salvar usam o mouse (piloto), e a regra é nunca dois no mesmo programa.

## Voltas e perguntas (fase N4)

`volta: {para: id, teto: 1..5, se?}` num passo: depois de feito, o fluxo repete do passo `para` até ele, no máximo `teto` vezes; no teto, para e diz. A saída da rodada anterior fica
em `saidas_da_volta`, para o passo de cima ler `{perguntar.respostas}`, e na primeira rodada essa referência vale "".
⛔ Volta não repete passo que grava: `validar` recusa. É o que impede um sync rodar duas vezes.
`perguntar_ao_editor` é do executor, não do modelo: o fluxo vira `perguntando`, a thread sai (não segura a fila) e `responder` o retoma.

`correndo` · `pausado` · `perguntando` · `esperando` (um passo falhou: a decisão é de alguém) · `cancelado` ·
`pronto` · `interrompido` (o serviço reiniciou com ele correndo).

⛔ O estado vai para o DISCO depois de cada passo conferido, com a saída do passo — é dela que
as referências dos passos seguintes vivem ao retomar. Retomar começa do passo seguinte ao
último CONFERIDO, nunca do último "começado".

⚠️ Pausar e cancelar valem ENTRE passos: o passo em curso termina (um render do Resolve não é
cortado no meio). Dentro de um passo pilotado, o F12 do piloto continua valendo.

⭐ Roda sobre `tarefas.comecar`: a regra "uma tarefa de fundo por vez" (CPU) vale também aqui,
e um fluxo pausado não segura a fila — a thread sai, o estado fica no disco.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Iterator

from . import tarefas as _tarefas

log = logging.getLogger("cicloassist.servico.fluxo")

#: A ferramenta que monta um fluxo não pode ser passo de um: um plano que se chama a si mesmo
#: seria uma fila sem fim, e um que chama `continuar_fluxo` mexeria no próprio estado.
PROIBIDAS = frozenset({"executar_fluxo", "continuar_fluxo", "pedir_confirmacao"})
MAXIMO_DE_PASSOS = 30

_ID = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
#: Um texto que é SÓ um marcador ("{pasta}", "{conv.pasta}") pode virar lista ao rodar.
_SO_UM_MARCADOR = re.compile(r"^\{[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z0-9_]+)*\}$")
#: `{nome}` ou `{passo.campo.sub}` — e nada mais.
_REF = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z0-9_]+)*)\}")

ESTADOS_FINAIS = frozenset({"pronto", "cancelado"})
#: Passo que o fluxo já deixou para trás. `fora`: o ramo dele não foi seguido.
_TERMINADOS = ("feito", "pulado", "fora")
CONDICOES = ("sim", "nao", "igual")
OP_PERGUNTAR = "perguntar_ao_editor"
#: ⭐ Peça do executor (N4b). ⛔ A gravação continua `sempre_pergunta` e fora dos passos: aqui o fluxo PARA, a tela mostra as regras, e só o clique do editor grava
#: (`confirmar`). Nem o modelo nem o modo automático respondem por ele.
OP_CONFIRMAR = "confirmar_na_memoria"
OP_GRAVAR_NA_MEMORIA = "gravar_na_memoria_da_producao"
TETO_DE_VOLTAS = 5

_trava = threading.RLock()


class PlanoInvalido(ValueError):
    """O plano não passa na conferência de estrutura. A mensagem diz o que consertar."""


class FluxoOcupado(RuntimeError):
    """Já há um fluxo que não terminou. Um de cada vez, como a fila de fundo."""


# ── o plano ──────────────────────────────────────────────────────────────────


def _ferramentas() -> dict[str, Any]:
    from ..mcp import ferramentas as _registrar  # noqa: F401 — o import registra
    from ..mcp.registro import FERRAMENTAS
    return FERRAMENTAS


def _referencias(valor: Any) -> list[str]:
    if isinstance(valor, str):
        return _REF.findall(valor)
    if isinstance(valor, list):
        return [r for v in valor for r in _referencias(v)]
    if isinstance(valor, dict):
        return [r for v in valor.values() for r in _referencias(v)]
    return []


def _problemas_do_se(rotulo: str, se: Any, anteriores: set[str]) -> list[str]:
    if not isinstance(se, dict) or not isinstance(se.get("campo"), str) or se.get("e") not in CONDICOES:
        return [f"{rotulo}: 'se' tem de ser {{campo: \"passo.campo\", e: {' | '.join(CONDICOES)}, valor}}"]
    saida: list[str] = []
    raiz, _, campo = se["campo"].partition(".")
    if not campo or raiz not in anteriores:
        saida.append(f"{rotulo}: 'se' olha {se['campo']!r}, a saída de um passo que não vem ANTES dele")
    if se["e"] == "igual" and "valor" not in se:
        saida.append(f"{rotulo}: 'se' com 'igual' precisa de 'valor'")
    return saida


def _ids(passos: list[Any]) -> list[str]:
    return [str(p.get("id") or "") if isinstance(p, dict) else "" for p in passos]


def _podem_ler_adiante(passos: list[Any]) -> dict[str, set[str]]:
    """Dentro de uma volta, um passo pode ler a saída da rodada anterior de quem vem depois dele."""
    ids, saida = _ids(passos), {}
    for i, p in enumerate(passos):
        v = p.get("volta") if isinstance(p, dict) else None
        if isinstance(v, dict) and v.get("para") in ids[:i]:
            inicio = ids.index(v["para"])
            for j in range(inicio, i + 1):
                saida.setdefault(ids[j], set()).update(ids[j:i + 1])
    return saida


def _problemas_das_voltas(passos: list[Any], registradas: dict[str, Any]) -> list[str]:
    ids, saida, faixas = _ids(passos), [], []
    for i, p in enumerate(passos):
        if not isinstance(p, dict) or p.get("volta") is None:
            continue
        rotulo, v = f"passo {i + 1} ({ids[i]})", p["volta"]
        if not isinstance(v, dict) or v.get("para") not in ids[:i]:
            saida.append(f"{rotulo}: 'volta' tem de ser {{para: id de um passo ANTES dele, teto}}")
            continue
        teto = v.get("teto")
        if isinstance(teto, bool) or not isinstance(teto, int) or not 1 <= teto <= TETO_DE_VOLTAS:
            saida.append(f"{rotulo}: toda volta tem teto, de 1 a {TETO_DE_VOLTAS}")
        if v.get("se") is not None:
            saida += _problemas_do_se(rotulo, v["se"], set(ids[:i + 1]))
        inicio = ids.index(v["para"])
        if any(a <= i and inicio <= b for a, b in faixas):
            saida.append(f"{rotulo}: duas voltas não podem se cruzar")
        faixas.append((inicio, i))
        for q, pid in zip(passos[inicio:i + 1], ids[inicio:i + 1]):
            op = op_atual(str(q.get("op") or "")) if isinstance(q, dict) else ""
            if op in registradas and registradas[op].escreve:
                saida.append(f"{rotulo}: a volta repetiria {pid}, que grava algo: só repete quem não grava")
    return saida


def _problemas_do_ramo(rotulo: str, passo: dict[str, Any], anteriores: set[str]) -> list[str]:
    saida: list[str] = []
    deps = passo.get("depois_de")
    if deps is not None:
        if not isinstance(deps, list) or not all(isinstance(d, str) for d in deps):
            saida.append(f"{rotulo}: 'depois_de' tem de ser uma lista de ids")
        else:
            saida += [f"{rotulo}: 'depois_de' cita {d!r}, que não vem ANTES dele" for d in deps if d not in anteriores]
    if passo.get("se") is not None:
        saida += _problemas_do_se(rotulo, passo["se"], anteriores)
    return saida


def validar(plano: Any) -> list[str]:
    """Os defeitos de ESTRUTURA do plano, um por linha. Vazio = passa.

    Não consulta o mundo: é o que se confere sem saber se o Resolve está aberto.
    """
    if not isinstance(plano, dict):
        return ["o plano tem de ser um objeto com 'passos'"]
    problemas: list[str] = []
    params = plano.get("parametros") or {}
    if not isinstance(params, dict):
        problemas.append("'parametros' tem de ser um objeto {nome: valor}")
        params = {}
    for nome, valor in params.items():
        if not _ID.match(str(nome)):
            problemas.append(f"parâmetro com nome inválido: {nome!r} (minúsculas, dígitos e _)")
        if not isinstance(valor, (str, int, float, bool, list)) or valor is None:
            problemas.append(f"parâmetro {nome!r}: valor tem de ser texto, número, sim/não ou lista")
    passos = plano.get("passos")
    if not isinstance(passos, list) or not passos:
        return problemas + ["o plano não tem passos"]
    if len(passos) > MAXIMO_DE_PASSOS:
        problemas.append(f"{len(passos)} passos — o teto é {MAXIMO_DE_PASSOS}; divida em dois fluxos")

    registradas = _ferramentas()
    vistos: set[str] = set()
    adiante = _podem_ler_adiante(passos)
    for n, passo in enumerate(passos, 1):
        if not isinstance(passo, dict):
            problemas.append(f"passo {n}: tem de ser um objeto {{id, op, args}}")
            continue
        pid = str(passo.get("id") or "")
        op = op_atual(str(passo.get("op") or ""))
        args = passo.get("args") or {}
        rotulo = f"passo {n} ({pid or op or '?'})"
        problemas += _problemas_do_ramo(rotulo, passo, vistos)
        if not _ID.match(pid):
            problemas.append(f"{rotulo}: 'id' tem de ser minúsculas, dígitos e _ (ex.: conv)")
        elif pid in vistos:
            problemas.append(f"{rotulo}: id repetido")
        elif pid in params:
            problemas.append(f"{rotulo}: o id {pid!r} é também um parâmetro")
        # ⛔ `sempre_pergunta`: o cartão do fluxo aprova o plano, e o modo automático nem isso. O que só vale se o editor disser não entra.
        if op in PROIBIDAS or (op in registradas and registradas[op].sempre_pergunta):
            problemas.append(f"{rotulo}: {op} não pode ser passo de um fluxo")
        elif op not in registradas:
            problemas.append(f"{rotulo}: não existe a operação {op!r}")
        if not isinstance(args, dict):
            problemas.append(f"{rotulo}: 'args' tem de ser um objeto")
            args = {}
        elif op in registradas and op not in PROIBIDAS:
            esquema = registradas[op].esquema or {}
            aceitos = set((esquema.get("properties") or {}).keys())
            for chave in args:
                if chave not in aceitos:
                    problemas.append(f"{rotulo}: {op} não aceita {chave!r} "
                                     f"(aceita: {', '.join(sorted(aceitos)) or 'nada'})")
            for chave in esquema.get("required") or []:
                if chave not in args:
                    problemas.append(f"{rotulo}: falta {chave!r}, que {op} exige")
            # ⛔⛔ O VALOR também (2026-11-03, prova da F3): um plano com `programa: "media composer"`
            #   (o certo é media_composer) e `bins: "{camera.bin},{som.bin}"` (texto onde vai lista)
            #   passou por aqui e chegou ao cartão — e falharia no passo 4, com o editor fora da ilha.
            #   ⚠️ Só valor LITERAL: o que tem marcador ({param}, {passo.campo}) se conhece ao rodar.
            props = esquema.get("properties") or {}
            for chave, valor in args.items():
                spec = props.get(chave) or {}
                if spec.get("type") == "array" and isinstance(valor, str) and not _SO_UM_MARCADOR.match(valor):
                    problemas.append(f"{rotulo}: {chave!r} tem de ser uma LISTA "
                                     f"(ex.: [\"{{camera.bin}}\", \"{{som.bin}}\"]), não o texto {valor!r}")
                opcoes = spec.get("enum")
                if opcoes and isinstance(valor, str) and "{" not in valor and valor not in opcoes:
                    problemas.append(f"{rotulo}: {chave!r} = {valor!r} não existe "
                                     f"(use um de: {', '.join(map(str, opcoes))})")
        for ref in _referencias(args):
            raiz = ref.split(".", 1)[0]
            if "." in ref:
                if raiz not in vistos and raiz not in adiante.get(pid, ()):
                    problemas.append(f"{rotulo}: {{{ref}}} aponta um passo que não vem ANTES dele")
            elif raiz not in params:
                problemas.append(f"{rotulo}: {{{ref}}} não é um parâmetro do plano")
        if pid:
            vistos.add(pid)
    return problemas + _problemas_das_voltas(passos, registradas)


def _caminho(valor: Any, partes: list[str]) -> Any:
    for parte in partes:
        if isinstance(valor, dict) and parte in valor:
            valor = valor[parte]
        elif isinstance(valor, list) and parte.isdigit() and int(parte) < len(valor):
            valor = valor[int(parte)]
        else:
            raise KeyError(parte)
    return valor


def resolver(valor: Any, parametros: dict[str, Any], saidas: dict[str, Any],
             pulados: frozenset[str] = frozenset(), vazios: frozenset[str] = frozenset()) -> Any:
    """Troca as referências pelos valores. ⭐ `"{x}"` sozinho mantém o TIPO (uma lista continua
    lista); dentro de um texto, vira texto."""
    if isinstance(valor, list):
        return [resolver(v, parametros, saidas, pulados, vazios) for v in valor]
    if isinstance(valor, dict):
        return {k: resolver(v, parametros, saidas, pulados, vazios) for k, v in valor.items()}
    if not isinstance(valor, str):
        return valor

    def um(ref: str) -> Any:
        partes = ref.split(".")
        if len(partes) == 1:
            if ref not in parametros:
                raise PlanoInvalido(f"o parâmetro {ref!r} não foi dado")
            return parametros[ref]
        if partes[0] not in saidas:
            if partes[0] in vazios:      # a primeira rodada de uma volta: ainda não há resposta
                return ""
            if partes[0] in pulados:
                raise PlanoInvalido(f"este passo usa a saída de {partes[0]!r}, que foi PULADO; "
                                    "corrija os argumentos dele ou pule este também")
            raise PlanoInvalido(f"o passo {partes[0]!r} ainda não rodou")
        try:
            return _caminho(saidas[partes[0]], partes[1:])
        except KeyError:
            raise PlanoInvalido(f"o passo {partes[0]!r} não devolveu {'.'.join(partes[1:])!r}") from None

    inteiro = _REF.fullmatch(valor)
    if inteiro:
        return um(inteiro.group(1))
    return _REF.sub(lambda m: str(um(m.group(1))), valor)


# ── o estado ─────────────────────────────────────────────────────────────────


#: ⭐ Fase 3 do plano um app só (2026-11-07): as ferramentas do Sincronizar trocaram de nome. Fluxos e receitas
#: GRAVADOS antes (o retomar, as receitas do editor) ainda citam os antigos — eles valem como os novos. É história:
#: nenhum código novo escreve estes nomes.
NOMES_ANTIGOS = {"sincronizar_com_o_" + "orbita": "sincronizar", "merged_pelo_" + "orbita": "criar_merged"}


def op_atual(op: str) -> str:
    return NOMES_ANTIGOS.get(op, op)


@dataclass
class Passo:
    id: str
    op: str
    args: dict[str, Any]

    def __post_init__(self) -> None:
        self.op = op_atual(self.op)

    #: `a_fazer` · `correndo` · `feito` · `falhou` · `pulado`
    estado: str = "a_fazer"
    saida: dict[str, Any] = field(default_factory=dict)
    motivo: str = ""
    avisos: list[str] = field(default_factory=list)
    segundos: float = 0.0
    tentativas: int = 0
    #: De quem depende. `None`: do passo anterior da lista.
    depois_de: list[str] | None = None
    se: dict[str, Any] | None = None
    #: O gerente já conferiu este passo: a tela acende o node dele e depois o do passo.
    revisado: bool = False
    volta: dict[str, Any] | None = None
    #: O que o editor respondeu, num `perguntar_ao_editor`.
    respostas: list[dict[str, str]] | None = None
    #: O que o clique decidiu, num `confirmar_na_memoria`.
    confirmacao: dict[str, Any] | None = None
    teto_atingido: bool = False


@dataclass
class Fluxo:
    id: str
    nome: str
    parametros: dict[str, Any]
    passos: list[Passo]
    #: De onde veio: `modelo` (montado no chat) ou `receita:<nome>` (botão).
    origem: str = "modelo"
    estado: str = "pausado"
    criado: float = field(default_factory=time.time)
    atualizado: float = field(default_factory=time.time)
    #: O que está acontecendo agora, para a janela (o `turno.avisar` das operações cai aqui).
    andamento: dict[str, Any] = field(default_factory=dict)
    #: Pedido vindo da janela, que o laço lê ENTRE passos: `pausar` · `cancelar`.
    pedido: str = ""
    #: ⛔⛔ Os caminhos que estavam AUTORIZADOS quando o editor aprovou o plano (arrasto ou
    #: seletor, `servico/arrastados.py`). A autorização mora na MEMÓRIA do serviço: MEDIDO na
    #: prova de 2026-11-02, o app fechado e reaberto no meio do conform, e o "Tentar de novo"
    #: recusou o `.prproj` do PRÓPRIO plano aprovado ("Não tenho permissão para abrir…"). Retomar
    #: os reautoriza — só estes, que o gesto e o clique no cartão já cobriam; nunca um caminho
    #: que um `tentar_de_novo` com args trouxer depois.
    autorizados: list[str] = field(default_factory=list)
    #: Quantas vezes cada volta já rodou, e a saída da rodada anterior de quem manda voltar.
    voltas: dict[str, int] = field(default_factory=dict)
    saidas_da_volta: dict[str, Any] = field(default_factory=dict)

    @property
    def atual(self) -> int:
        """O índice do próximo passo a rodar (o primeiro que não está feito nem pulado)."""
        for i, p in enumerate(self.passos):
            if p.estado not in _TERMINADOS:
                return i
        return len(self.passos)

    def saidas(self) -> dict[str, Any]:
        return {p.id: p.saida for p in self.passos if p.estado == "feito"}

    def como_dicionario(self) -> dict[str, Any]:
        d = asdict(self)
        d["atual"] = self.atual
        d["total"] = len(self.passos)
        d["feitos"] = sum(1 for p in self.passos if p.estado == "feito")
        return d

    @classmethod
    def de_dicionario(cls, d: dict[str, Any]) -> "Fluxo":
        passos = [Passo(**{k: v for k, v in p.items() if k in Passo.__dataclass_fields__})
                  for p in d.get("passos") or []]
        campos = {k: v for k, v in d.items() if k in cls.__dataclass_fields__ and k != "passos"}
        return cls(passos=passos, **campos)


def pasta() -> Path:
    from .config import pasta as _pasta
    return _pasta() / "fluxos"


def _arquivo(id_: str) -> Path:
    return pasta() / f"{id_}.json"


def _gravar(f: Fluxo) -> None:
    with _trava:
        f.atualizado = time.time()
        destino = _arquivo(f.id)
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".tmp")
        tmp.write_text(json.dumps(f.como_dicionario(), ensure_ascii=False, indent=1, default=str),
                       encoding="utf-8")
        os.replace(tmp, destino)


def ler(id_: str) -> Fluxo | None:
    try:
        return Fluxo.de_dicionario(json.loads(_arquivo(id_).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return None


#: Os fluxos vivos nesta memória, por id. O disco é a verdade; isto evita relê-lo a cada passo.
_vivos: dict[str, Fluxo] = {}
_acordado = False


def _acordar() -> None:
    """Na primeira consulta depois de o serviço subir: o que estava `correndo` foi cortado."""
    global _acordado
    with _trava:
        if _acordado:
            return
        _acordado = True
        if not pasta().is_dir():
            return
        terminados: list[Fluxo] = []
        for arq in pasta().glob("*.json"):
            f = ler(arq.stem)
            if f is None:
                continue
            if f.estado in ESTADOS_FINAIS:
                terminados.append(f)
                continue
            if f.estado == "correndo":
                f.estado = "interrompido"
                for p in f.passos:
                    if p.estado == "correndo":
                        # ⚠️ Não sabemos se ele terminou: refazer é a resposta segura só se a
                        #   operação for idempotente — e a janela PERGUNTA antes de retomar.
                        p.estado = "a_fazer"
                        p.motivo = "o serviço reiniciou no meio deste passo"
                f.andamento = {}
                _gravar(f)
                log.info("fluxo %s: interrompido pelo reinício do serviço", f.id)
            _vivos[f.id] = f
        # ⭐ E o último que TERMINOU (2026-11-02): depois de um reinício, a janela ficava sem o
        #   resultado do fluxo que acabara de rodar ("sem fluxo"). Só o mais recente: a pasta cresce.
        if terminados:
            ult = max(terminados, key=lambda f: f.atualizado)
            _vivos.setdefault(ult.id, ult)


def em_aberto() -> Fluxo | None:
    """O fluxo que não terminou (há no máximo um). `None` quando não há."""
    _acordar()
    with _trava:
        abertos = [f for f in _vivos.values() if f.estado not in ESTADOS_FINAIS]
        return max(abertos, key=lambda f: f.criado) if abertos else None


def ultimo() -> Fluxo | None:
    """O aberto, ou o último que terminou — a janela mostra o resultado depois do fim."""
    _acordar()
    with _trava:
        return em_aberto() or (max(_vivos.values(), key=lambda f: f.atualizado) if _vivos else None)


def criar(plano: dict[str, Any], origem: str = "modelo") -> Fluxo:
    problemas = validar(plano)
    if problemas:
        raise PlanoInvalido("; ".join(problemas))
    aberto = em_aberto()
    if aberto is not None:
        raise FluxoOcupado(f"o fluxo '{aberto.nome}' ainda não terminou ({aberto.estado})")
    f = Fluxo(
        id=time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6],
        nome=str(plano.get("nome") or "fluxo").strip()[:120],
        parametros=dict(plano.get("parametros") or {}),
        passos=[Passo(id=str(p["id"]), op=str(p["op"]), args=dict(p.get("args") or {}), depois_de=p.get("depois_de"), se=p.get("se"), volta=p.get("volta"))
                for p in plano["passos"]],
        origem=origem,
    )
    f.autorizados = _caminhos_autorizados([f.parametros, [q.args for q in f.passos]])
    with _trava:
        _vivos[f.id] = f
    _gravar(f)
    log.info("fluxo %s criado: %s, %d passos (%s)", f.id, f.nome, len(f.passos), origem)
    return f


def _textos(valor: Any) -> Iterator[str]:
    if isinstance(valor, str):
        yield valor
    elif isinstance(valor, dict):
        for v in valor.values():
            yield from _textos(v)
    elif isinstance(valor, (list, tuple)):
        for v in valor:
            yield from _textos(v)


def _caminhos_autorizados(valores: Any) -> list[str]:
    """Os textos do plano que são caminhos autorizados AGORA (o momento da aprovação)."""
    from . import arrastados as _arrastados
    vistos: list[str] = []
    for t in _textos(valores):
        if t and t not in vistos and len(t) < 1024 and _arrastados.autorizado(t):
            vistos.append(t)
    return vistos[:200]


def _reautorizar(f: Fluxo) -> None:
    from . import arrastados as _arrastados
    for c in f.autorizados:
        if not _arrastados.autorizado(c):
            _arrastados.autorizar(c)
            log.info("fluxo %s: autorização de %s refeita (o serviço reiniciou)", f.id, c)


# ── a execução ───────────────────────────────────────────────────────────────

#: ⭐ "Esta thread roda um passo de um fluxo que o EDITOR aprovou." É o que deixa uma operação
#: que exige o consentimento dele na conversa (abrir_programa: "só abre o programa que o editor
#: nomeou") aceitar o clique no cartão do fluxo — que listava aquele passo pelo nome.
_aprovado = threading.local()


def em_fluxo_aprovado() -> bool:
    return bool(getattr(_aprovado, "fluxo", ""))


@contextlib.contextmanager
def consentido(de_onde: str):
    """A conferência de um plano que o EDITOR escolheu (o botão de uma receita): a receita
    nomeia os programas, e escolhê-la é ele nomeando. ⛔ Nunca para um plano do modelo."""
    anterior = getattr(_aprovado, "fluxo", "")
    _aprovado.fluxo = de_onde
    try:
        yield
    finally:
        _aprovado.fluxo = anterior


def _relator(f: Fluxo):
    def relatar(etapa: str, fracao: float | None = None, detalhe: str = "") -> None:
        try:
            f.andamento = {
                "passo": f.atual, "etapa": str(etapa or ""), "detalhe": str(detalhe or ""),
                "fracao": None if fracao is None else max(0.0, min(1.0, float(fracao))),
                "em": time.time(),
            }
            n = len(f.passos)
            _tarefas_avisar(f.atual / max(1, n) + (fracao or 0.0) / max(1, n),
                            f"passo {f.atual + 1}/{n}: {etapa}")
        except Exception:  # pragma: no cover — relato não derruba trabalho
            pass
    return relatar


_aviso_da_tarefa = threading.local()


def _tarefas_avisar(fracao: float, texto: str) -> None:
    aviso = getattr(_aviso_da_tarefa, "aviso", None)
    if aviso:
        aviso(fracao, texto)


#: O que o editor precisa saber depois de cancelar NO MEIO de cada passo que se deixa interromper.
_O_QUE_FICA = {
    "sincronizar": "O Sincronizar termina o sync do lado dele (ele não tem como parar um sync em "
                                "curso): as bins podem aparecer no projeto daqui a pouco.",
    "conformar_no_resolve": "A timeline ficou pela metade no Resolve: confira ou apague-a lá.",
}


#: ⭐ Os passos que passam pelo revisor de IA antes de rodar (decisão 6 do plano de 2026-11-08).
PASSOS_REVISADOS = ("sincronizar", "criar_merged")


def _revisar_antes_do_sync(op: str, args: dict[str, Any]) -> None:
    """Todo fluxo autônomo tem um gerente, ligado por padrão: aqui, ele confere as fontes antes de cada sync.

    Incoerente: o fluxo para e pergunta. ⛔ Sem IA disponível o sync não roda, e o fluxo diz o motivo: é um sync às cegas
    numa diária inteira, e o gerente existe justamente para isso. Só sai se o editor pedir um fluxo sem supervisão."""
    if op not in PASSOS_REVISADOS or args.get("sem_supervisao"):
        return
    from ..mcp.ferramentas import sincronizar as _fo
    from ..motor import revisor_do_sync as _revisor
    try:
        resumo = _fo.resumo_para_o_revisor(**args)
        veredito = _revisor.revisar(str(args.get("nome") or ""), resumo)
    except (_revisor.RevisorFalhou, ValueError) as e:
        raise PlanoInvalido(f"O revisor de IA não conseguiu conferir as fontes, e o sync não roda sem ele: {e}") from e
    if not veredito["coerente"]:
        raise PlanoInvalido(f"O revisor de IA parou o fluxo: {veredito['motivo']} {veredito['pergunta']}".strip())


def _argumentos(f: Fluxo, passo: Passo, args: dict[str, Any] | None = None) -> dict[str, Any]:
    depois = f.passos[f.passos.index(passo) + 1:]
    return resolver(passo.args if args is None else args, f.parametros, {**f.saidas_da_volta, **f.saidas()},
                    frozenset(p.id for p in f.passos if p.estado in ("pulado", "fora")), frozenset(p.id for p in depois))


def _sem_dialogo_no_mc(passo: Passo) -> None:
    """⭐ Antes de um passo que fala com o MC, um diálogo no caminho é assunto do agente do piloto: com ele aberto a API fica muda, e o passo só saberia dizer "não respondeu".

    ⛔ Abrir e fechar têm o socorro deles, e `salvar_tudo` também.
    """
    from .catalogo_de_pecas import CATALOGO, MEDIA_COMPOSER, O_NLE_ABERTO

    peca = CATALOGO.get(passo.op)
    if sys.platform != "win32" or peca is None or peca.programa not in (MEDIA_COMPOSER, O_NLE_ABERTO) or passo.op == "salvar_tudo":
        return
    from ..avid import socorro as _socorro
    from ..piloto.auxilio import TelaInesperada

    if not _socorro.inesperada():
        return

    class DialogoNoCaminho(PlanoInvalido, TelaInesperada):
        pass

    def tentar() -> None:
        if _socorro.inesperada():
            raise DialogoNoCaminho("há um diálogo do Media Composer na tela, e a API dele não responde enquanto ele estiver aberto")

    from . import turno as _turno

    _socorro.com_agente(f"seguir com o passo {passo.id} do fluxo no Media Composer", tentar, PlanoInvalido, _turno.avisar)


def _rodar_passo(f: Fluxo, passo: Passo) -> None:
    """Um passo: referências → conferência → ação. Grava o resultado no `passo`."""
    from . import pendencias as _pendencias

    ferramenta = _ferramentas().get(passo.op)
    passo.tentativas += 1
    passo.estado, passo.motivo, passo.avisos, passo.revisado = "correndo", "", [], False
    _gravar(f)
    inicio = time.monotonic()
    try:
        if ferramenta is None:
            raise PlanoInvalido(f"a operação {passo.op!r} não existe mais nesta versão")
        args = _argumentos(f, passo)
        with _pendencias.relatando_para(_relator(f), cancelar=lambda: f.pedido == "cancelar"):
            _sem_dialogo_no_mc(passo)
        if ferramenta.conferir is not None:
            motivo = ferramenta.conferir(**args)
            if motivo:
                raise PlanoInvalido(motivo)
        _revisar_antes_do_sync(passo.op, args)
        passo.revisado = True
        with _pendencias.relatando_para(_relator(f), cancelar=lambda: f.pedido == "cancelar"):
            saida = ferramenta.funcao(**args)
    except _pendencias.PassoCancelado as e:
        # ⭐ Cancelado NO MEIO, num ponto de espera (autor, 2026-11-04). ⚠️ O programa de fora pode
        #   terminar o que já começou do lado dele — o Sincronizar não tem como parar um sync em curso.
        log.info("fluxo %s, passo %s: cancelado no meio (%s)", f.id, passo.id, e)
        passo.estado = "cancelado"
        passo.motivo = (f"cancelado no meio pelo editor. {_O_QUE_FICA.get(passo.op, '')}").strip()
        passo.segundos = round(time.monotonic() - inicio, 1)
        return
    except Exception as e:  # noqa: BLE001 — a falha é do fluxo saber, não do log
        log.info("fluxo %s, passo %s: falhou (%s)", f.id, passo.id, e)
        passo.estado, passo.motivo = "falhou", str(e) or e.__class__.__name__
        passo.segundos = round(time.monotonic() - inicio, 1)
        return
    passo.segundos = round(time.monotonic() - inicio, 1)
    saida = saida if isinstance(saida, dict) else {"resultado": saida}
    if saida.get("erro"):
        passo.estado, passo.motivo, passo.saida = "falhou", str(saida["erro"]), saida
        return
    problemas = saida.get("problemas")
    if isinstance(problemas, list):
        passo.avisos = [str(p) for p in problemas if p]
    passo.estado, passo.saida = "feito", saida
    log.info("fluxo %s, passo %s: feito em %.1f s", f.id, passo.id, passo.segundos)


def _fora_do_caminho(f: Fluxo, i: int) -> str:
    """Por que o passo `i` não roda, ou "" se ele roda. ⚠️ Levanta `PlanoInvalido` quando não dá para decidir: é falha, e o editor vê."""
    passo = f.passos[i]
    por_id = {p.id: p for p in f.passos}
    deps = passo.depois_de if passo.depois_de is not None else ([f.passos[i - 1].id] if i else [])
    if deps and all(por_id[d].estado == "fora" for d in deps if d in por_id):
        return "o caminho até este node não foi seguido"
    if not passo.se:
        return ""
    return _motivo_do_se(passo.se, por_id)


def _motivo_do_se(se: dict[str, Any], por_id: dict[str, Passo]) -> str:
    """"" quando a condição vale; senão, por que não."""
    raiz, _, campo = str(se.get("campo") or "").partition(".")
    origem = por_id.get(raiz)
    if origem is None or origem.estado != "feito":
        return f"sem a saída de '{raiz}', que não rodou, este caminho não foi seguido"
    try:
        valor = _caminho(origem.saida, campo.split("."))
    except KeyError:
        raise PlanoInvalido(f"não dá para decidir o caminho: o passo {raiz!r} não devolveu {campo!r}") from None
    e = se.get("e")
    atendida = bool(valor) if e == "sim" else not valor if e == "nao" else str(valor) == str(se.get("valor"))
    return "" if atendida else "a condição não foi atendida"


def _perguntas_de(valor: Any) -> list[dict[str, Any]]:
    """Texto solto ou o formato do agente de metadado (`{texto, opcoes, sobre}`)."""
    saida = []
    for p in valor if isinstance(valor, list) else []:
        texto = p if isinstance(p, str) else str(p.get("texto") or "") if isinstance(p, dict) else ""
        if texto.strip():
            opcoes = p.get("opcoes") if isinstance(p, dict) and isinstance(p.get("opcoes"), list) else []
            sobre = str(p.get("sobre") or "").strip() if isinstance(p, dict) else ""
            saida.append({"texto": texto.strip(), "opcoes": [str(o) for o in opcoes][:8], **({"sobre": sobre} if sobre else {})})
    return saida


def _perguntar(f: Fluxo, passo: Passo) -> bool:
    """`True` quando o passo terminou; `False` quando o fluxo parou para esperar o editor."""
    if passo.respostas is not None:
        passo.saida, passo.estado = {"respostas": passo.respostas}, "feito"
        return True
    perguntas = _perguntas_de(_argumentos(f, passo).get("perguntas"))
    if not perguntas:
        passo.saida, passo.estado = {"respostas": []}, "feito"     # nada a perguntar: ninguém é interrompido
        return True
    passo.tentativas += 1
    passo.saida, passo.estado, passo.motivo = {"perguntas": perguntas, "titulo": str(passo.args.get("titulo") or "")}, "perguntando", ""
    f.estado, f.andamento = "perguntando", {}
    return False


def _nao_sabidos(respostas: Any) -> list[str]:
    """Os trechos de nome a que o editor respondeu "não sei". ⛔ Pergunta sem resposta não é "não sei" e não entra."""
    from ..midia import metadado_da_diaria as _diaria

    trechos = (str(r.get("sobre") or "").strip() for r in (respostas if isinstance(respostas, list) else [])
               if isinstance(r, dict) and _diaria.memoria._chave(str(r.get("resposta") or "")) in ("nao sei", "nao se sabe"))
    return list(dict.fromkeys(t for t in trechos if t))


def _confirmar(f: Fluxo, passo: Passo) -> bool:
    """`True` quando o passo terminou; `False` quando parou esperando o clique. Sem nada a confirmar, ninguém é interrompido."""
    if passo.confirmacao is not None:
        passo.saida, passo.estado = passo.confirmacao, "feito"
        return True
    # ⚠️ `respostas` é opcional de verdade: quando o agente não perguntou nada, o node Perguntar fica de fora, e isso não é erro.
    args = _argumentos(f, passo, {k: v for k, v in passo.args.items() if k != "respostas"})
    try:
        respostas = _argumentos(f, passo, {"respostas": passo.args.get("respostas") or []})["respostas"]
    except PlanoInvalido:
        respostas = []
    # ⛔ Só o que a conferência aprovou nos arquivos: regra reprovada não vira memória.
    regras = [{"forma": str(r["forma"]), "molde": str(r["molde"]), "exemplo": str(r.get("exemplo") or ""), "arquivos": r.get("arquivos") or 0}
              for r in (args.get("regras") if isinstance(args.get("regras"), list) else []) if isinstance(r, dict) and r.get("aprovada") is True and r.get("forma") and r.get("molde")]
    nao_se_sabe = _nao_sabidos(respostas)
    if not regras and not nao_se_sabe:
        passo.saida, passo.estado = {"gravou": False, "regras": 0, "motivo": "não havia nada a confirmar"}, "feito"
        return True
    producao = args.get("producao") if isinstance(args.get("producao"), dict) else {"memoria": str(args.get("producao") or "") or None}
    sugestoes = [*producao.get("no_ixml", []), *producao.get("memorias_existentes", []), producao.get("projeto_aberto") or ""]
    passo.tentativas += 1
    passo.saida = {"confirmar": {"regras": regras, "nao_se_sabe": nao_se_sabe, "memoria": producao.get("memoria"), "projeto_aberto": producao.get("projeto_aberto") or "",
                                 "sugestoes": list(dict.fromkeys(n for n in sugestoes if n))[:5],
                                 "origem": {k: str(args.get(k) or "") for k in ("pasta", "bin", "programa")}}}
    passo.estado, passo.motivo = "perguntando", ""
    f.estado, f.andamento = "perguntando", {}
    return False


def confirmar(gravar: bool, producao: str = "", apelido: bool = False) -> Fluxo:
    """O clique do editor no cartão. ⛔ As regras saem do que está guardado no PASSO, nunca do corpo do pedido: a tela só diz sim ou não e o nome da produção."""
    f = em_aberto()
    passo = f.passos[f.atual] if f is not None and f.estado == "perguntando" else None
    if passo is None or passo.op != OP_CONFIRMAR:
        raise PlanoInvalido("não há confirmação esperando resposta")
    cartao = passo.saida.get("confirmar") or {}
    if gravar:
        nome = str(cartao.get("memoria") or producao or "").strip()
        if not nome:
            raise PlanoInvalido("Diga de que produção é esta diária.")
        _reautorizar(f)      # o clique pode vir depois de o serviço reiniciar, e a conferência relê a pasta
        projeto = str(cartao.get("projeto_aberto") or "")
        try:
            # ⭐ O mesmo caminho do chat: a ferramenta confere de novo nos arquivos antes de gravar.
            r = _ferramentas()[OP_GRAVAR_NA_MEMORIA].funcao(
                producao=nome, regras=[{"forma": x["forma"], "molde": x["molde"]} for x in cartao.get("regras") or []], nao_se_sabe=cartao.get("nao_se_sabe") or [],
                apelidos=[projeto] if apelido and projeto and projeto != nome else [], **(cartao.get("origem") or {}))
        except Exception as e:  # noqa: BLE001 — o programa fechado na hora do clique não pode virar erro 500: o editor abre e clica de novo
            raise PlanoInvalido(f"Não consegui conferir as regras agora: {e}") from e
        if r.get("erro"):
            raise PlanoInvalido(str(r["erro"]))
        decisao = {"gravou": True, "producao": r.get("producao") or nome, "regras": r.get("regras") or 0, "arquivo": r.get("arquivo") or "", "manchete": r.get("manchete") or ""}
    else:
        decisao = {"gravou": False, "regras": 0, "motivo": "o editor preferiu não gravar"}
    with _trava:
        passo.confirmacao = decisao
        _gravar(f)
    return iniciar(f.id)


def _voltar(f: Fluxo, i: int) -> str:
    """Repete da origem até aqui. Devolve o motivo quando o fluxo tem de parar: o teto, ou uma condição que não dá para decidir."""
    passo = f.passos[i]
    v = passo.volta or {}
    por_id = {p.id: p for p in f.passos}
    if v.get("se") and _motivo_do_se(v["se"], por_id):
        return ""
    feitas = f.voltas.get(passo.id, 0)
    if feitas >= int(v.get("teto") or 0):
        passo.estado, passo.teto_atingido = "falhou", True
        passo.motivo = f"chegou ao teto de {feitas} volta(s) sem resolver. Pule este node para seguir, ou cancele."
        return passo.motivo
    f.voltas[passo.id] = feitas + 1
    f.saidas_da_volta[passo.id] = passo.saida
    inicio = next(n for n, p in enumerate(f.passos) if p.id == v["para"])
    for q in f.passos[inicio:i + 1]:
        q.estado, q.saida, q.motivo, q.avisos, q.revisado, q.respostas, q.teto_atingido = "a_fazer", {}, "", [], False, None, False
        q.confirmacao = None
    return ""


def _correr(f: Fluxo, aviso, parar: threading.Event) -> dict[str, Any]:
    """⭐ Com a janela do app à vista o fluxo inteiro (`espaco.a_vista`, autor 2026-10-31)."""
    from ..piloto import espaco as _espaco

    with _espaco.a_vista():
        return _correr_a_vista(f, aviso, parar, _espaco.reafirmar, _espaco.janela_do_app_cortada)


def _correr_a_vista(f: Fluxo, aviso, parar: threading.Event, reafirmar,
                    cortada=lambda: "") -> dict[str, Any]:
    _aprovado.fluxo = f.id
    _aviso_da_tarefa.aviso = aviso
    try:
        while True:
            i = f.atual
            if i >= len(f.passos):
                f.estado, f.andamento = "pronto", {}
                _gravar(f)
                break
            # ⭐ Os pedidos da janela valem ENTRE passos: o passo anterior já foi conferido e
            #   gravado, e é dele que o retomar parte.
            if f.pedido or parar.is_set():
                f.estado = "cancelado" if f.pedido == "cancelar" else "pausado"
                f.pedido, f.andamento = "", {}
                _gravar(f)
                break
            passo = f.passos[i]
            try:
                fora = _fora_do_caminho(f, i)
            except PlanoInvalido as e:
                passo.estado, passo.motivo = "falhou", str(e)
                f.estado, f.andamento = "esperando", {}
                _gravar(f)
                break
            if fora:
                passo.estado, passo.motivo = "fora", fora
                _gravar(f)
                continue
            # ⭐ Antes de CADA passo (de graça: só geometria): a janela pode ser arrastada para a
            #   faixa sem monitor no meio do fluxo. Cortada, o passo não roda — o editor arruma e retoma.
            motivo = cortada()
            if motivo:
                passo.estado, passo.motivo = "falhou", motivo
                f.estado, f.andamento = "esperando", {}
                _gravar(f)
                break
            if passo.op in (OP_PERGUNTAR, OP_CONFIRMAR):
                try:
                    if not (_perguntar if passo.op == OP_PERGUNTAR else _confirmar)(f, passo):
                        _gravar(f)
                        break
                except PlanoInvalido as e:
                    passo.estado, passo.motivo = "falhou", str(e)
            else:
                _rodar_passo(f, passo)
                reafirmar()       # o passo pode ter aberto um programa por cima da janela
            if passo.estado == "cancelado":
                f.estado, f.pedido, f.andamento = "cancelado", "", {}
                _gravar(f)
                break
            if passo.estado == "falhou":
                f.estado, f.andamento = "esperando", {}
                _gravar(f)
                break
            # ⭐ Sem nada a perguntar, não há resposta para levar de volta: repetir só gastaria o teto.
            if passo.estado == "feito" and passo.volta and not (passo.op == OP_PERGUNTAR and not passo.saida.get("respostas")):
                try:
                    parou = _voltar(f, i)
                except PlanoInvalido as e:
                    passo.estado, passo.motivo, parou = "falhou", str(e), str(e)
                if parou:
                    f.estado, f.andamento = "esperando", {}
                    _gravar(f)
                    break
            _gravar(f)
    except Exception as e:  # noqa: BLE001
        # ⛔ Algo estourou FORA de um passo (o `_gravar` com o disco cheio, um arquivo travado):
        #   sem isto a tarefa morria e o fluxo ficava "correndo" para sempre — o Retomar não fazia
        #   nada e nenhum fluxo novo era aceito até reiniciar o serviço (revisão de 2026-11-01).
        log.exception("fluxo %s: falhou entre os passos", f.id)
        f.estado, f.andamento, f.pedido = "esperando", {}, ""
        if f.atual < len(f.passos):
            p = f.passos[f.atual]
            p.estado, p.motivo = "falhou", f"o Ciclo Assist falhou entre os passos: {e}"
        try:
            _gravar(f)
        except Exception:  # noqa: BLE001 — o disco é o problema; a memória ao menos diz a verdade
            log.exception("fluxo %s: nem o estado de falha pôde ser gravado", f.id)
    finally:
        _aprovado.fluxo = ""
        _aviso_da_tarefa.aviso = None
    log.info("fluxo %s: %s (%d de %d passos)", f.id, f.estado,
             sum(1 for p in f.passos if p.estado == "feito"), len(f.passos))
    return resumo(f)


def iniciar(id_: str) -> Fluxo:
    """Põe o fluxo para rodar (do passo atual). Serve para começar E para retomar."""
    _acordar()
    with _trava:
        f = _vivos.get(id_) or ler(id_)
        if f is None:
            raise KeyError(id_)
        _vivos[f.id] = f
        if f.estado in ESTADOS_FINAIS:
            raise FluxoOcupado(f"o fluxo '{f.nome}' já terminou ({f.estado})")
        if f.estado == "correndo":
            return f
        f.estado, f.pedido = "correndo", ""
        _gravar(f)
    _reautorizar(f)
    try:
        _tarefas.comecar("fluxo", f.nome, lambda aviso, parar: _correr(f, aviso, parar))
    except _tarefas.TarefaEmCurso as e:
        with _trava:
            f.estado = "pausado"
            _gravar(f)
        raise FluxoOcupado(f"há outra tarefa de fundo correndo ({e}); o fluxo espera a vez") from None
    return f


def responder(respostas: Any) -> Fluxo:
    """O editor respondeu as perguntas do node em que o fluxo parou."""
    f = em_aberto()
    if f is None or f.estado != "perguntando" or f.passos[f.atual].op != OP_PERGUNTAR:
        raise PlanoInvalido("não há pergunta esperando resposta")
    # ⭐ O `sobre` vem da pergunta guardada, nunca do corpo: é o trecho do nome que um "não sei" registra na memória.
    sobre = {p["texto"]: p["sobre"] for p in f.passos[f.atual].saida.get("perguntas") or [] if p.get("sobre")}
    limpas = [{"pergunta": str(r.get("pergunta") or ""), "resposta": str(r.get("resposta") or "").strip(), **({"sobre": sobre[str(r.get("pergunta"))]} if str(r.get("pergunta")) in sobre else {})}
              for r in (respostas if isinstance(respostas, list) else []) if isinstance(r, dict) and str(r.get("resposta") or "").strip()]
    if not limpas:
        raise PlanoInvalido("responda ao menos uma pergunta")
    with _trava:
        f.passos[f.atual].respostas = limpas
        _gravar(f)
    return iniciar(f.id)


def pedir(acao: str) -> Fluxo | None:
    """O editor apertou Pausar ou Cancelar na janela."""
    if acao not in ("pausar", "cancelar"):
        raise ValueError(acao)
    f = em_aberto()
    if f is None:
        return None
    with _trava:
        if f.estado == "correndo":
            f.pedido = acao
        elif acao == "cancelar":
            # Parado (pausado, esperando, interrompido): cancelar é imediato.
            f.estado, f.pedido, f.andamento = "cancelado", "", {}
        _gravar(f)
    return f


def descartar(id_: str) -> None:
    """Apaga um fluxo que NUNCA rodou (o início foi recusado): sem isto ele ficaria "pausado",
    bloqueando o próximo pedido, sem o modelo saber que existe (revisão de 2026-11-01)."""
    with _trava:
        f = _vivos.get(id_)
        if f is not None and any(p.estado != "a_fazer" or p.tentativas for p in f.passos):
            raise PlanoInvalido("este fluxo já rodou; cancele em vez de descartar")
        _vivos.pop(id_, None)
        try:
            _arquivo(id_).unlink()
        except OSError:
            pass


def pular(id_: str) -> Fluxo:
    """Marca o passo que falhou como pulado. O editor (ou o modelo, pelo cartão) decidiu."""
    f = _vivos.get(id_) or ler(id_)
    if f is None:
        raise KeyError(id_)
    if f.estado not in ("esperando", "interrompido"):
        # ⛔ Pular é a resposta a um passo que FALHOU (ou que o reinício cortou): num fluxo só
        #   pausado ele descartaria um passo que ninguém viu dar errado.
        raise PlanoInvalido(f"só se pula o passo que parou o fluxo (o fluxo está {f.estado})")
    with _trava:
        p = f.passos[f.atual] if f.atual < len(f.passos) else None
        if p is not None:
            p.estado = "pulado"
        _gravar(f)
    return f


def corrigir(id_: str, args: dict[str, Any]) -> Fluxo:
    """Troca argumentos do passo atual (o que falhou) antes de tentar de novo."""
    f = _vivos.get(id_) or ler(id_)
    if f is None:
        raise KeyError(id_)
    if f.atual >= len(f.passos):
        raise PlanoInvalido("o fluxo não tem passo a corrigir")
    p = f.passos[f.atual]
    teste = {"parametros": f.parametros,
             "passos": [{"id": q.id, "op": q.op, "args": ({**q.args, **args} if q is p else q.args),
                         **({"depois_de": q.depois_de} if q.depois_de is not None else {}), **({"se": q.se} if q.se else {}), **({"volta": q.volta} if q.volta else {})}
                        for q in f.passos]}
    problemas = validar(teste)
    if problemas:
        raise PlanoInvalido("; ".join(problemas))
    with _trava:
        # ⭐ O NOME acompanha a correção (2026-11-02): "Conformar SEQ_QUE_NAO_EXISTE…" seguiu rodando
        #   `transicao-pesoa` depois do tentar_de_novo, e o conselho estranhou o título. Só quando o
        #   argumento era um parâmetro inteiro (`{sequencia}`) cujo valor está no nome.
        for chave, novo in args.items():
            m = re.fullmatch(r"\{(\w+)\}", str(p.args.get(chave, "")))
            velho = f.parametros.get(m.group(1)) if m else None
            if isinstance(velho, str) and velho and isinstance(novo, str) and novo and velho in f.nome:
                f.nome = f.nome.replace(velho, novo)[:120]
        p.args = {**p.args, **args}
        p.estado, p.motivo = "a_fazer", ""
        _gravar(f)
    return f


# ── o que se conta ───────────────────────────────────────────────────────────


#: ⛔ O TETO do conselho automático (revisão de 2026-11-01): as DUAS primeiras falhas de um passo
#: chamam o modelo; da terceira em diante a decisão é do editor, pelos botões.
CONSELHOS_POR_PASSO = 2


def decidir(acao: str, args: dict[str, Any] | None = None) -> Fluxo:
    """`tentar_de_novo` (com args corrigidos) · `pular` · `cancelar` · `retomar` no fluxo parado.

    Uma conta só para o `continuar_fluxo` (o modelo), a janela (o botão do conselho) e o
    conselho automático — três cópias divergiriam caladas."""
    f = em_aberto()
    if f is None:
        raise PlanoInvalido("não há fluxo parado")
    if f.estado == "correndo":
        raise PlanoInvalido(f"o fluxo '{f.nome}' está correndo")
    if args and acao != "tentar_de_novo":
        raise PlanoInvalido("args só vale com tentar_de_novo")
    if acao == "cancelar":
        pedir("cancelar")
        return f
    if acao == "pular":
        pular(f.id)
    elif acao == "tentar_de_novo" and args:
        corrigir(f.id, args)
    elif acao not in ("tentar_de_novo", "retomar"):
        raise PlanoInvalido(f"ação desconhecida: {acao!r}")
    return iniciar(f.id)


def condicoes_da_receita(f: Fluxo) -> str:
    """A seção "Quando as condições mudam" da receita de onde o fluxo veio, ou ""."""
    if not f.origem.startswith("receita:"):
        return ""
    try:
        r = _receitas_todas().get(f.origem.removeprefix("receita:"))
    except Exception:  # noqa: BLE001 — receita apagada ou ilegível: o conselho segue sem ela
        return ""
    return getattr(r, "condicoes", "") or ""


def _receitas_todas():
    from . import receitas as _receitas
    return _receitas.todas()


def resumo(f: Fluxo) -> dict[str, Any]:
    feitos = [p for p in f.passos if p.estado == "feito"]
    d: dict[str, Any] = {"fluxo": f.id, "nome": f.nome, "estado": f.estado,
                         "feitos": len(feitos), "total": len(f.passos)}
    avisos = [f"{p.id}: {a}" for p in f.passos for a in p.avisos]
    if avisos:
        d["avisos"] = avisos
    falhou = next((p for p in f.passos if p.estado == "falhou"), None)
    if falhou:
        d["falhou"] = {"passo": falhou.id, "op": falhou.op, "motivo": falhou.motivo}
    return d


def descrever(f: Fluxo) -> str:
    """O fluxo em poucas linhas, para o modelo (o preâmbulo do turno) — com teto."""
    linhas = [f"Fluxo '{f.nome}' ({f.id}): {f.estado}, {sum(p.estado == 'feito' for p in f.passos)} "
              f"de {len(f.passos)} passos feitos."]
    for n, p in enumerate(f.passos, 1):
        linha = f"  {n}. {p.id} = {p.op} — {p.estado}"
        if p.motivo:
            linha += f": {p.motivo[:400]}"
        if p.avisos:
            linha += f" (avisos: {'; '.join(p.avisos)[:300]})"
        linhas.append(linha)
    return "\n".join(linhas)


def recado() -> str:
    """O que o próximo turno do modelo precisa saber do fluxo — vazio quando nada pede."""
    f = em_aberto()
    # ⚠️ "pausado" não entra: foi o editor quem pausou, e um fluxo pausado e esquecido pesaria em
    #   TODA pergunta dali em diante (revisão de 2026-11-01).
    if f is None or f.estado not in ("esperando", "interrompido"):
        return ""
    texto = descrever(f)
    if f.estado == "esperando":
        texto += ("\nO passo que falhou espera uma decisão. Explique ao editor em poucas linhas o que "
                  "houve e, se souber a saída, proponha com continuar_fluxo (tentar_de_novo, com "
                  "argumentos corrigidos se for o caso; pular; ou cancelar). Não refaça os passos "
                  "feitos por fora do fluxo.")
    return texto


def esquecer() -> None:
    """Só os testes: esquece a memória (o disco fica)."""
    global _acordado
    with _trava:
        _vivos.clear()
        _acordado = False

