"""`separar_falas` — a cena vira uma bin com uma timeline por fala.

⭐⭐ A segunda das três funções do produto (CLAUDE.md, topo). O modelo transcreve os takes,
propõe a espinha da cena — que falas existem, em que ordem, que variantes — e diz em que
trecho de cada take cada uma é dita. O serviço confere contra a transcrição e escreve.
A regra e o porquê de cada conferência estão em `plano/falas.py`.

⛔ Escreve, e por isso passa pelo portão. Mas a conferência roda ANTES do cartão
(`registro.conferir`): um pedido reprovado volta ao modelo com o motivo, e o editor só vê o
que já passou.

⛔ Numa bin NOVA (`C07 FALAS.avb`, `C07 FALAS 2.avb`…), com o fecho oculto: nunca por cima
de bin nenhuma do editor, e subclipe fora da bin derruba o Media Composer ao carregar
(banco, 2026-08-30). A exceção é `acrescentar_em`, pedida pelo editor em 2026-09-15: a
bin de falas que já existe ganha as timelines que faltam, pela dança do `montar_corte`
(fechar, gravar ao lado com o UID preservado, abrir, e a original de volta se o MC recusar).
"""

from __future__ import annotations

import logging
from fractions import Fraction
import re
import shutil
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

import avb

from ...avid import take as _take
from ...midia import voz as _voz
from ...avid import timeline as _timeline
from ...avid.atributos import copiar_bin
from ...avid.mcapi import TEMPO_DE_ARQUIVO_S, McApiErro, MediaComposer, relativo_ao_projeto
from ...avid.take import TakeErro, com_extensao_de_bin
from ...midia import cache as _cache
from ...plano import falas as _falas
from ...servico import arrastados as _arrastados
from ..registro import AMBOS, ferramenta
from .corte import _abrir, _caminho_livre, _nome_de_arquivo
from .fala import falas_do_take
from .roteiro import _roteiro_do_arquivo, resolver, segmentos_no_take
from ... import nle as _nle

log = logging.getLogger("cicloassist.mcp.falas")


def _projeto() -> dict:
    with MediaComposer() as mc:
        return mc.projeto()


def _segmentos_do_take(caminho_da_bin: str):
    """`segmentos(take) -> [(entrada, saida)] | None` em frames do take, numerados como
    `transcrever` os mostrou — a lista vem de `fala.falas_do_take`, e de nenhum outro lugar.

    ⭐ Só do CACHE, como `roteiro.segmentos_no_take`: conferir não dispara ASR.
    """
    lembrados: dict[str, object] = {}

    def segmentos(nome: str):
        if nome not in lembrados:
            take = resolver(caminho_da_bin, nome)
            som = take.som
            lista = None
            if som is not None and som.arquivos:
                midia = som.midia()
                do_master = midia.ler_transcricao() if midia.tem_transcricao() else []
                # ⭐ a borda da voz medida (L2), só do cache: o corte que se monta é o mesmo que `transcrever` mostrou
                do_master = _voz.anexar(do_master, _voz.ler(midia)) if do_master else do_master
                if do_master:
                    lista = [(f["inicio_no_take_frames"], f["saida_no_take_frames"])
                             for f in falas_do_take(take, do_master)]
            lembrados[nome] = lista
        return lembrados[nome]

    return segmentos


def _takes_da_cena(caminho_da_bin: str, cena: str) -> list[str] | None:
    """Os clipes visíveis da bin cuja claquete é desta cena — o que o editor espera ver.

    ⚠️ Pela CLAQUETE do nome, não pela bin inteira: uma bin de diária tem várias cenas.
    Nome fora da convenção fica de fora da conta (não dá para saber de que cena é), e bin
    ilegível devolve None — sem conferência de takes, em vez de uma recusa falsa.
    """
    alvo = _falas.cena_normalizada(cena)
    if _nle.qual() == _nle.PREMIERE:
        return _takes_da_cena_no_premiere(caminho_da_bin, alvo)
    try:
        with avb.open(str(caminho_da_bin)) as f:
            return [str(i.mob.name) for i in f.content.items
                    if i.user_placed and _take.especie(i.mob) in ("subclipe", "master")
                    and _falas.cena_normalizada(
                        _take.ler_claquete(str(i.mob.name or ""))["cena"] or "") == alvo]
    except Exception as e:                    # noqa: BLE001 — sem a lista, sem essa conferência
        log.warning("não consegui listar os takes de %s (%s)", caminho_da_bin, e)
        return None


def _takes_da_cena_no_premiere(bin_: str, alvo: str) -> list[str] | None:
    """Os clipes (e merged) da bin do Premiere cuja claquete é desta cena — pela árvore do projeto
    (MCP no 27.1+, ponte CEP nas versões antigas: `premiere.arvore` escolhe)."""
    from ...nle import premiere as P
    try:
        itens = P.arvore()
    except Exception as e:                    # noqa: BLE001 — sem a lista, sem essa conferência
        log.warning("não consegui listar os takes de %s no Premiere (%s)", bin_, e)
        return None
    b = bin_.strip("/")
    return [str(i["nome"]) for i in itens
            if i.get("especie") in ("clipe", "merged") and str(i.get("bin") or "") == b
            and _falas.cena_normalizada(_take.ler_claquete(str(i["nome"]))["cena"] or "") == alvo]


def _escopo_dos_takes(da_cena: list[str] | None) -> list[str] | None:
    """Os takes que TÊM de entrar: os arrastados, quando o editor arrastou takes desta cena.

    ⭐ Sem arrasto (ou arrasto de outra coisa), vale a bin inteira, como sempre.
    """
    if da_cena is None:
        return None
    arrastados = {n.casefold() for n in _arrastados.clipes()}
    escolhidos = [t for t in da_cena if t.casefold() in arrastados]
    return escolhidos or da_cena


def _o_roteiro(roteiro: str):
    """(falas do roteiro, nome do arquivo) — ou (None, "") quando não há um só roteiro.

    ⭐ Sem `roteiro` no pedido, vale o ÚNICO roteiro arrastado nesta sessão. MEDIDO em
    2026-09-15: o Haiku leu o roteiro com `ler_arquivo` e nunca chamou
    `estruturar_o_roteiro`; uma conferência que dependesse de ele lembrar de passar o
    arquivo não conferiria justamente no caso em que falhou. Com dois roteiros arrastados,
    escolher seria adivinhar.
    """
    if str(roteiro or "").strip():
        falas, erro = _roteiro_do_arquivo(roteiro)
        if erro:
            raise _falas.FalasInvalidas(f"roteiro: {erro}")
        return falas, Path(roteiro).name
    achados = []
    for caminho in _arrastados.arquivos():
        if Path(caminho).suffix.lower() not in _arrastados.TEXTO:
            continue
        falas, _ = _roteiro_do_arquivo(caminho)
        if falas:
            achados.append((falas, Path(caminho).name))
    return achados[0] if len(achados) == 1 else (None, "")


_NOME_DE_FALA = re.compile(r"^(?P<cena>\S+?)_FALA(?P<n>\d+)(?:\.(?P<v>\d+))? - (?P<texto>.*)$")


def _ja_na_bin(destino: Path, cena: str) -> dict[tuple[int, int], str]:
    """As timelines de fala que a bin de destino já tem: (momento, variante) → texto."""
    alvo = _falas.cena_normalizada(cena)
    achadas = {}
    with avb.open(str(destino)) as f:
        for i in f.content.items:
            m = _NOME_DE_FALA.match(str(i.mob.name or "")) if i.user_placed else None
            if m and _falas.cena_normalizada(m["cena"]) == alvo:
                texto = m["texto"].rstrip("…").strip()
                achadas[(int(m["n"]), int(m["v"] or 1))] = texto
    return achadas


#: Trechos por take do pedido RECUSADO mais cheio, por (bin, cena). É o que faz
#: `conferir_cobertura` notar que o modelo "consertou" uma recusa tirando trecho.
#: ⚠️ Na memória do processo: é da conversa de agora, não do projeto.
_recusados: dict[tuple[str, str], dict[str, int]] = {}
#: O último pedido INTEIRO por (bin, cena): a base de `corrigir_o_anterior`.
#: ⭐⭐ MEDIDO no ensaio da C07 (2026-10-22, Sonnet 5): cada reprovação fazia o modelo
#:    reescrever as 16 falas — ~13 mil caracteres e minutos de pensamento por volta —
#:    para mudar dois trechos. Com a base aqui, ele manda só os momentos consertados.
_ultimos: dict[tuple[str, str], tuple[list, list | None]] = {}
_trava = threading.Lock()


def _ja_na_bin_no_premiere(bin_: str, cena: str) -> dict[tuple[int, int], str]:
    """As timelines de fala que já estão na bin do Premiere, pelo nome (a mesma regra do Avid).

    ⛔ Pela árvore que ESCOLHE a via (`premiere.arvore`: MCP no 27.1+, ponte CEP nas antigas). Antes
    era só o MCP, e no Premiere 2026 o `acrescentar_em` passava no cartão e falhava DEPOIS do clique
    com "o servidor MCP do Premiere não respondeu" (pelo chat, 2026-11-07).
    """
    from ...nle import premiere as P
    itens = P.arvore()
    def caminho(i):
        return f"{i['bin']}/{i['nome']}" if i.get("bin") else str(i["nome"])
    if not any(i.get("especie") == "bin" and caminho(i) == bin_ for i in itens):
        raise _falas.FalasInvalidas(f"acrescentar_em: não achei a bin {bin_} no projeto do Premiere")
    alvo, achadas = _falas.cena_normalizada(cena), {}
    for i in itens:
        if i.get("especie") != "sequencia" or str(i.get("bin") or "") != bin_:
            continue
        m = _NOME_DE_FALA.match(str(i["nome"]))
        if m and _falas.cena_normalizada(m["cena"]) == alvo:
            achadas[(int(m["n"]), int(m["v"] or 1))] = m["texto"]
    return achadas


def _chave_do_momento(f: object) -> tuple[object, object]:
    if not isinstance(f, dict):
        return (None, None)
    return (f.get("fala"), f.get("variante") or 1)


def _com_o_anterior(chave: tuple[str, str], falas: list, deixadas_de_fora) -> tuple[list, object]:
    """Os momentos consertados encaixados no último pedido desta cena.

    Momento que já existia (mesma fala e variante) é TROCADO; momento novo entra; os outros
    ficam como estavam. `deixadas_de_fora`, quando vem, substitui a lista inteira.
    """
    with _trava:
        base = _ultimos.get(chave)
    if base is None:
        raise _falas.FalasInvalidas(
            "corrigir_o_anterior: não há pedido anterior desta cena nesta conversa. Mande o "
            "pedido inteiro.")
    trocar = {_chave_do_momento(f): f for f in falas}
    juntas = [trocar.pop(_chave_do_momento(f), f) for f in base[0]]
    juntas.extend(trocar.values())
    juntas.sort(key=lambda f: (_chave_do_momento(f)[0] or 0, _chave_do_momento(f)[1] or 1))
    return juntas, (deixadas_de_fora if deixadas_de_fora is not None else base[1])


@dataclass
class _Pedido:
    falas: list
    takes: dict
    caminho: str
    conf: _falas.Conferencia
    projeto: dict | None
    de_fora: list
    roteiro: list | None
    roteiro_nome: str
    destino: Path | None
    ja_na_bin: dict


def _preparar(bin: str, cena: str, falas: list, deixadas_de_fora=None, roteiro: str = "",
              acrescentar_em: str = "", corrigir_o_anterior: bool = False) -> _Pedido:
    """Valida, resolve os takes e confere — o conteúdo e o que ficou de fora.

    Levanta `FalasInvalidas`, `TakeErro` ou `McApiErro` com a frase para o modelo.
    """
    if not _falas.cena_normalizada(cena):
        raise _falas.FalasInvalidas("diga a cena (ex.: 7 ou C07)")
    premiere = _nle.qual() == _nle.PREMIERE
    if premiere:
        # ⭐ No Premiere a bin é um CAMINHO do projeto ("CENAS/C07"), não um arquivo.
        projeto, raiz, caminho = {"caminho": "", "fps_aprox": 0}, Path(""), str(bin or "").strip("/")
    else:
        precisa_do_projeto = not Path(bin).is_absolute() or \
            (acrescentar_em and not Path(acrescentar_em).is_absolute())
        projeto = _projeto() if precisa_do_projeto else None
        raiz = Path((projeto or {}).get("caminho") or "")
        caminho = com_extensao_de_bin(bin if Path(bin).is_absolute() else str(raiz / bin))

    chave = (caminho.casefold(), _falas.cena_normalizada(cena))
    if corrigir_o_anterior:
        falas, deixadas_de_fora = _com_o_anterior(chave, list(falas or []), deixadas_de_fora)
    with _trava:
        # ⭐ Guardado ANTES de conferir: um pedido que nem valida também é a base que o
        #   modelo vai consertar. E é idempotente: o portão e a execução preparam o MESMO
        #   pedido, e reencaixar os mesmos momentos numa base que já os tem não muda nada.
        _ultimos[chave] = (list(falas or []), deixadas_de_fora)

    destino, ja_na_bin = None, {}
    if premiere and str(acrescentar_em or "").strip():
        destino = Path(str(acrescentar_em).strip("/"))
        if str(destino) == caminho:
            raise _falas.FalasInvalidas("acrescentar_em é a bin dos takes; as falas vão para "
                                       "uma bin de falas, nunca para a do material")
        ja_na_bin = _ja_na_bin_no_premiere(str(destino), cena)
    elif str(acrescentar_em or "").strip():
        destino = Path(com_extensao_de_bin(acrescentar_em))
        destino = destino if destino.is_absolute() else raiz / destino
        if not destino.is_file():
            raise _falas.FalasInvalidas(f"acrescentar_em: não achei a bin {destino.name}")
        if destino.resolve() == Path(caminho).resolve():
            raise _falas.FalasInvalidas("acrescentar_em é a bin dos takes; as falas vão para "
                                       "uma bin de falas, nunca para a do material")
        ja_na_bin = _ja_na_bin(destino, cena)

    validadas = _falas.validar(_falas.trechos_por_segmento(falas, _segmentos_do_take(caminho)))
    repetidas = [f for f in validadas if (f.n, f.variante) in ja_na_bin]
    if repetidas:
        ultima = max(n for n, _ in ja_na_bin)
        raise _falas.FalasInvalidas(
            f"{', '.join(f.rotulo for f in repetidas[:6])} já existe(m) em {destino.stem}. "
            f"Numere os momentos novos sem repetir: a bin vai até a FALA{ultima:02d}.")
    de_fora = _falas.validar_de_fora(deixadas_de_fora)
    falas_do_roteiro, nome_do_roteiro = _o_roteiro(roteiro)

    takes = {}
    for f in validadas:
        for t in f.trechos:
            if t.take not in takes:
                takes[t.take] = resolver(caminho, t.take)
    conf = _falas.conferir(validadas, segmentos_no_take(caminho),
                           lambda nome: takes[nome].duracao_frames)

    with _trava:
        anterior = dict(_recusados.get(chave, {}))
    conf.problemas.extend(_falas.conferir_cobertura(
        validadas, de_fora, roteiro=falas_do_roteiro,
        takes_da_cena=_escopo_dos_takes(_takes_da_cena(caminho, cena)),
        textos_ja_na_bin=list(ja_na_bin.values()), anterior=anterior))
    with _trava:
        if conf.fecha:
            _recusados.pop(chave, None)
        else:
            # ⛔ O MAIS CHEIO, não o último: senão três encolhidas pequenas somariam uma
            #    grande sem nenhuma ser notada.
            for take, quantos in _falas.trechos_por_take(validadas).items():
                anterior[take] = max(anterior.get(take, 0), quantos)
            _recusados[chave] = anterior

    return _Pedido(validadas, takes, caminho, conf, projeto, de_fora, falas_do_roteiro,
                   nome_do_roteiro, destino, ja_na_bin)


def _conferir_pedido(bin: str = "", cena: str = "", falas: list | None = None,
                     deixadas_de_fora=None, roteiro: str = "", acrescentar_em: str = "",
                     corrigir_o_anterior: bool = False, **_resto) -> str:
    """A conferência que o portão roda antes do cartão. Vazio: pode mostrar."""
    try:
        p = _preparar(bin, cena, falas or [], deixadas_de_fora, roteiro, acrescentar_em,
                      corrigir_o_anterior)
    except (_falas.FalasInvalidas, TakeErro, McApiErro, _cache.ChaveInvalida) as e:
        return str(e)
    if p.conf.fecha:
        return ""
    return (_falas.relatar(p.conf) + "\nMande só os momentos consertados, com "
            "corrigir_o_anterior: true — o resto do pedido continua guardado.")


_TRECHO = {
    "type": "object",
    "properties": {
        "take": {"type": "string", "description": "Nome do subclipe ou master."},
        "do_segmento": {"type": "integer", "description": (
            "O número `segmento` da fala na transcrição DESTE take.")},
        "ate_o_segmento": {"type": "integer", "description": (
            "Só quando a fala ocupa segmentos seguidos: o último deles. O trecho vai da "
            "entrada do primeiro à saída do último.")},
    },
    "required": ["take", "do_segmento"],
}

_DE_FORA = {
    "type": "object",
    "properties": {
        "roteiro": {"type": "integer", "description": (
            "O número da fala no roteiro (estruturar_o_roteiro) que não entrou.")},
        "take": {"type": "string", "description": "O take que não entrou, inteiro ou em parte."},
        "porque": {"type": "string", "description": (
            "O motivo, para o editor ler: take abortado, fala que nenhum take diz, só claquete.")},
    },
    "required": ["porque"],
}


@ferramenta(
    nome="separar_falas",
    descricao=(
        "Separa as falas de uma cena: grava uma bin com UMA timeline por fala, e em cada "
        "uma o trecho de cada take em que aquela fala é dita, lado a lado. Serve com "
        "roteiro ou sem. Transcreva TODOS os takes da cena antes e consulte o método "
        "separar-falas. Cada trecho aponta o número `segmento` da transcrição daquele take "
        "— nunca frames. Toda fala do roteiro e todo take da cena entram, ou vão em "
        "deixadas_de_fora com o porquê. O pedido é conferido antes de chegar ao editor; se "
        "voltar reprovado, mande SÓ os momentos consertados, com corrigir_o_anterior: o "
        "resto do pedido anterior é mantido pelo serviço."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "Caminho da bin dos takes."},
            "cena": {"type": "string", "description": "A cena, ex. 7 ou C07."},
            "falas": {
                "type": "array",
                "description": "Os momentos da cena, na ordem em que acontecem.",
                "items": {
                    "type": "object",
                    "properties": {
                        "fala": {"type": "integer", "description": (
                            "O número do MOMENTO na cena, a partir de 1.")},
                        "variante": {"type": "integer", "default": 1, "description": (
                            "1 para o texto mais dito; 2, 3… para texto distinto do mesmo "
                            "momento (improviso). Takes que improvisam IGUAL são a mesma "
                            "variante.")},
                        "texto": {"type": "string", "description": (
                            "O que é dito, como os takes desta variante dizem.")},
                        "personagem": {"type": "string", "description": (
                            "Quem fala, se o roteiro ou a claquete disserem. Nunca pelo rosto.")},
                        "trechos": {"type": "array", "items": _TRECHO, "description": (
                            "Um por take em que a fala é dita, na ordem dos takes.")},
                        "confianca": {"type": "string", "enum": ["confirmado", "inferido",
                                                                 "hipotese"]},
                        "fonte": {"type": "string", "enum": ["claquete", "roteiro",
                                                             "transcricao", "visual",
                                                             "heuristica"]},
                        "porque": {"type": "string", "description": (
                            "Só quando houver algo a dizer: take de fora, variante duvidosa.")},
                    },
                    "required": ["fala", "texto", "trechos", "confianca", "fonte"],
                },
            },
            "deixadas_de_fora": {"type": "array", "items": _DE_FORA, "description": (
                "O que ficou de fora de propósito — fala do roteiro que nenhum take diz, take "
                "abortado. Sem isto, faltar fala ou take reprova o pedido.")},
            "roteiro": {"type": "string", "description": (
                "O caminho do roteiro arrastado. Se só um roteiro foi arrastado, ele já vale.")},
            "acrescentar_em": {"type": "string", "description": (
                "Uma bin de falas que JÁ existe (ex.: C07 FALAS.avb), para completar ou "
                "separar em lotes. Numere os momentos novos sem repetir os dela. Sem isto, a "
                "bin é nova.")},
            "corrigir_o_anterior": {"type": "boolean", "default": False, "description": (
                "Depois de uma reprovação: true e, em falas, SÓ os momentos consertados "
                "(mesma fala e variante trocam o anterior). O resto do último pedido desta "
                "cena continua valendo. deixadas_de_fora, se vier, troca a lista inteira.")},
        },
        "required": ["bin", "cena", "falas"],
    },
    escreve=True,
    conferir=_conferir_pedido,
    nles=AMBOS,
)
def separar_falas(bin: str, cena: str, falas: list, deixadas_de_fora=None, roteiro: str = "",
                  acrescentar_em: str = "", corrigir_o_anterior: bool = False
                  ) -> dict[str, object]:
    # ⛔ Confere de novo ao executar: entre o cartão e o clique pode ter passado um dia, e o
    #    automático não passa pelo cartão.
    try:
        p = _preparar(bin, cena, falas, deixadas_de_fora, roteiro, acrescentar_em,
                      corrigir_o_anterior)
        projeto = p.projeto if p.projeto is not None else _projeto()
    except (_falas.FalasInvalidas, TakeErro, McApiErro, _cache.ChaveInvalida) as e:
        return {"erro": f"as falas não foram separadas: {e}"}
    if not p.conf.fecha:
        return {"erro": "as falas não passaram na conferência:\n" + _falas.relatar(p.conf)}

    rotulo_da_cena = _falas.cena_normalizada(cena)
    if _nle.qual() == _nle.PREMIERE:
        return _separar_no_premiere(p, rotulo_da_cena)
    timelines = []
    for f in sorted(p.falas, key=lambda x: (x.n, x.variante)):
        entradas = [_timeline.Entrada(mob_id=p.takes[t.take].mob_id, duracao=t.duracao,
                                      trilhas=_timeline.trilhas_do_take(p.takes[t.take]),
                                      start_time=t.inicio)
                    for t in f.trechos]
        timelines.append((_falas.nome_da_timeline(rotulo_da_cena, f), entradas))

    raiz = Path(projeto.get("caminho") or Path(p.caminho).parent)
    fps, drop = projeto["fps_aprox"], bool(projeto.get("drop_frame"))
    aviso = ""
    if p.destino is not None:
        alvo, acrescentou, aviso = _acrescentar(p.destino, timelines, fps, p.caminho, drop, raiz,
                                                rotulo_da_cena)
        if alvo is None:
            return {"erro": aviso}
    else:
        alvo, acrescentou = _caminho_livre(
            raiz / f"{_nome_de_arquivo(rotulo_da_cena + ' FALAS')}.avb"), False
        try:
            _escrever_varias(alvo, timelines, fps, p.caminho, drop)
        except (ValueError, OSError) as e:
            return {"erro": f"não consegui escrever a bin de falas: {e}"}
    relativo = relativo_ao_projeto(str(alvo), str(raiz)) or str(alvo)   # ver mcapi
    aberta = acrescentou or _abrir(relativo)[0]

    resposta = {
        "ok": True,
        "bin": relativo,
        "acrescentada_a_bin_existente": acrescentou,
        "cena": rotulo_da_cena,
        "timelines": len(timelines),
        "momentos": len({f.n for f in p.falas}),
        "variantes": sum(1 for f in p.falas if f.variante > 1),
        "trechos": sum(len(f.trechos) for f in p.falas),
        "aberta_no_avid": aberta,
        "nomes": [nome for nome, _ in timelines],
        # ⭐ O que ficou de fora vai na resposta, e o modelo tem de dizê-lo ao editor.
        "deixadas_de_fora": [{"roteiro": d.roteiro, "take": d.take, "porque": d.porque}
                             for d in p.de_fora],
    }
    if p.roteiro:
        resposta["roteiro_conferido"] = f"{p.roteiro_nome} ({len(p.roteiro)} falas)"
    if aviso:
        resposta["aviso_para_o_editor"] = aviso
    return resposta


def _acrescentar(destino: Path, timelines, fps: float, base: str, drop: bool, raiz: Path,
                 rotulo_da_cena: str) -> tuple[Path | None, bool, str]:
    """As timelines numa bin que JÁ existe. Devolve (bin onde ficaram, acrescentou, aviso).

    ⛔⛔ A mesma dança do `montar_corte`, e pelos mesmos motivos medidos (ver lá): fechar
    ANTES de tocar no arquivo, copiar DEPOIS do `CloseBin` (que salva), e se o Media
    Composer recusar a bin regravada, ela volta byte a byte e as timelines vão para uma bin
    nova. Sem erro, `alvo` None e o aviso é a mensagem de erro.
    """
    relativo = relativo_ao_projeto(str(destino), str(raiz)) or str(destino)
    try:
        with MediaComposer() as mc:
            mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=relativo)
    except McApiErro as e:
        log.debug("CloseBin de %s: %s", relativo, e)   # bin fechada também responde erro

    copia = Path(tempfile.mkdtemp(prefix="cicloassist-")) / destino.name
    try:
        copiar_bin(destino, copia)
        try:
            _timeline.acrescentar_timelines(destino, timelines, fps, base=base,
                                            drop_frame=drop)
        except (ValueError, OSError) as e:
            copiar_bin(copia, destino)
            _abrir(relativo)
            return None, False, f"não consegui acrescentar em {destino.stem}: {e}"

        aberta, recusa = _abrir(relativo)
        if not recusa:
            return destino, True, ""

        log.warning("o MC recusou %s depois de receber as falas (%s); devolvendo a original",
                    relativo, recusa)
        copiar_bin(copia, destino)
        _abrir(relativo)
        nova = _caminho_livre(raiz / f"{_nome_de_arquivo(rotulo_da_cena + ' FALAS')}.avb")
        try:
            _escrever_varias(nova, timelines, fps, base, drop)
        except (ValueError, OSError) as e:
            return None, False, (f"o Media Composer recusou a bin {destino.stem} depois de "
                                 f"receber as falas, e ela foi devolvida como estava; a bin "
                                 f"nova também falhou: {e}")
        return nova, False, (
            f"O Media Composer recusou abrir a bin {destino.stem} depois de ela receber as "
            f"falas ({recusa}). Ela foi devolvida exatamente como estava, e as timelines foram "
            f"gravadas numa bin NOVA, {nova.stem}. Diga isso ao editor com estas palavras.")
    finally:
        shutil.rmtree(copia.parent, ignore_errors=True)


def _escrever_varias(alvo: Path, timelines, fps: float, base: str,
                     drop_frame: bool = False) -> None:
    """Todas as timelines numa bin só, com o fecho de todas.

    ⚠️ No temporário primeiro, pelo motivo do `corte._escrever_bin_nova`: uma escrita pela
    metade dentro do projeto seria uma bin corrompida na janela do editor.
    """
    temporario = Path(tempfile.gettempdir()) / alvo.name
    _timeline.escrever_bin(temporario, timelines, fps, base=base, drop_frame=drop_frame)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(temporario.read_bytes())
    temporario.unlink(missing_ok=True)


def _separar_no_premiere(p, rotulo_da_cena: str) -> dict[str, object]:
    """⭐ F3 do plano 2026-11-06-mcp-do-premiere: uma sequência por fala, numa bin de falas do
    Premiere, montada pelo MCP nativo (`nle/premiere/montagem.py`) com o som direto INTEIRO."""
    from ...nle.premiere import mcp_nativo as M
    from ...nle.premiere import montagem as G
    if M.via("montagem") != "mcp":
        return _separar_pela_ponte(p, rotulo_da_cena)
    try:
        proj = M.projeto_ativo()
        if not proj:
            return {"erro": "não há projeto aberto no Premiere"}
        pid = proj["agentProjectId"]
        itens = G.itens_do_projeto(pid)
        if p.destino is not None:
            destino, acrescentou = str(p.destino), True
        else:
            base = f"{rotulo_da_cena} FALAS"
            existentes = {i.get("path") for i in itens if i.get("type") == "bin"}
            destino, n = base, 2
            while destino in existentes:
                destino, n = f"{base} {n}", n + 1
            acrescentou = False
        ids: dict[str, tuple] = {}
        for nome in {t.take for f in p.falas for t in f.trechos}:
            item = G.achar_take(itens, nome, p.caminho)
            ids[nome] = (item["itemId"], True, True)
            if item.get("type") != "sequence":
                md = M.chamar("getClipMetadata", {"agentProjectId": pid, "itemIds": [item["itemId"]],
                                                  "fields": ["hasVideo", "hasAudio"]})
                v = {x["field"]: x.get("value") for x in md["results"][0].get("values") or []}
                ids[nome] = (item["itemId"], bool(v.get("hasVideo")), bool(v.get("hasAudio", True)))
        nomes, divergencias, avisos, trechos = [], [], [], 0
        for f in sorted(p.falas, key=lambda x: (x.n, x.variante)):
            nome = _falas.nome_da_timeline(rotulo_da_cena, f)
            pedacos, pos = [], 0
            for t in f.trechos:
                item_id, tem_v, tem_a = ids[t.take]
                pedacos.append(G.Pedaco(item_id, t.take, t.inicio, t.duracao, t.inicio, t.duracao,
                                        pos, pos, tem_video=tem_v, tem_audio=tem_a))
                pos += t.duracao
            take0 = p.takes[f.trechos[0].take]
            fps = Fraction(take0.fps["num"], take0.fps["den"]) if take0.fps else None
            r = G.montar(nome, pedacos, bin_da_sequencia=destino, pid=pid, fps_sem_imagem=fps)
            itens = G.itens_do_projeto(pid)   # a bin de falas pode ter nascido agora
            nomes.append(nome)
            trechos += len(pedacos)
            divergencias += [f"{nome}: {d}" for d in r.divergencias]
            avisos += r.avisos
    except G.MontagemFalhou as e:
        return {"erro": f"as falas não foram separadas no Premiere: {e}"}
    except (M.McpIndisponivel, M.McpFalhou) as e:
        return {"erro": f"o Premiere não respondeu ao separar as falas: {e}"}
    resposta: dict[str, object] = {
        "ok": not divergencias, "bin": destino, "acrescentada_a_bin_existente": acrescentou,
        "cena": rotulo_da_cena, "timelines": len(nomes), "momentos": len({f.n for f in p.falas}),
        "variantes": sum(1 for f in p.falas if f.variante > 1), "trechos": trechos, "nomes": nomes,
        "deixadas_de_fora": [{"roteiro": d.roteiro, "take": d.take, "porque": d.porque} for d in p.de_fora],
        "desfazer": "cada timeline é um passo do Desfazer do Premiere; a bin inteira se apaga do projeto",
    }
    if p.roteiro:
        resposta["roteiro_conferido"] = f"{p.roteiro_nome} ({len(p.roteiro)} falas)"
    if divergencias:
        resposta["erro"] = "as timelines foram montadas mas NÃO conferem: " + "; ".join(divergencias[:6])
    if avisos:
        resposta["avisos"] = avisos
    return resposta


def _separar_pela_ponte(p, rotulo_da_cena: str) -> dict[str, object]:
    """⭐ F6: as timelines de fala no Premiere SEM o MCP nativo (2025/2026), pelo ExtendScript."""
    from ...nle import premiere as P
    from ...nle.premiere import montagem as G
    from ...nle.premiere import montagem_cep as C
    from ...nle.premiere import ponte
    if not ponte.painel_vivo():
        return {"erro": ("o Premiere não está ligado ao Ciclo Assist: nem o servidor MCP (27.1+) nem a ponte "
                         "do painel respondem.")}
    if p.destino is not None:
        destino, acrescentou = str(p.destino), True
    else:
        existentes = {b.get("caminho") for b in P.bins()}
        base = f"{rotulo_da_cena} FALAS"
        destino, n = base, 2
        while destino in existentes:
            destino, n = f"{base} {n}", n + 1
        acrescentou = False
    nomes, divergencias, trechos = [], [], 0
    try:
        for f in sorted(p.falas, key=lambda x: (x.n, x.variante)):
            nome = _falas.nome_da_timeline(rotulo_da_cena, f)
            pedacos, pos = [], 0
            for t in f.trechos:
                tk = p.takes[t.take]
                pedacos.append(G.Pedaco(tk.mob_id, t.take, t.inicio, t.duracao, t.inicio, t.duracao, pos, pos,
                                        tem_video=tk.imagem is not None, tem_audio=tk.som is not None))
                pos += t.duracao
            tk0 = p.takes[f.trechos[0].take]
            r = C.montar(nome, pedacos, Fraction(tk0.fps["num"], tk0.fps["den"]), destino)
            nomes.append(nome)
            trechos += len(pedacos)
            divergencias += [f"{nome}: {d}" for d in r.divergencias]
    except G.MontagemFalhou as e:
        return {"erro": f"as falas não foram separadas no Premiere: {e}"}
    resposta: dict[str, object] = {
        "ok": not divergencias, "bin": destino, "acrescentada_a_bin_existente": acrescentou,
        "cena": rotulo_da_cena, "timelines": len(nomes), "momentos": len({f.n for f in p.falas}),
        "variantes": sum(1 for f in p.falas if f.variante > 1), "trechos": trechos, "nomes": nomes,
        "deixadas_de_fora": [{"roteiro": d.roteiro, "take": d.take, "porque": d.porque} for d in p.de_fora],
        "via": "ponte do painel (ExtendScript) — esta versão do Premiere não tem o servidor MCP",
    }
    if divergencias:
        resposta["erro"] = "as timelines foram montadas mas NÃO conferem: " + "; ".join(divergencias[:6])
    return resposta
