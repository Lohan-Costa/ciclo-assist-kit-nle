"""As ferramentas que leem o Media Composer aberto.

Só LEITURA aqui. Tudo que escreve no projeto do editor mora noutro módulo e passa pelo
portão de confirmação — ver ADR 0003.

⚠️ **Uma conexão por chamada, de propósito.** Seria mais barato manter o canal aberto,
mas o Media Composer vai e vem: o editor fecha o app, troca de projeto, abre um modal.
Um canal guardado entre chamadas guarda também um projeto que já não é o aberto — e o
`projeto()` é cacheado DENTRO da sessão justamente porque a sessão é curta. Custa um
handshake; compra não responder sobre o projeto errado.
"""

from __future__ import annotations

from pathlib import Path

from ...avid.mcapi import McApiErro, McApiFechado, MediaComposer
from ...avid.take import TakeErro, com_extensao_de_bin, resolver
from ..registro import ferramenta


def _explicar(e: McApiErro) -> str:
    """Erro do Avid → frase que o modelo consegue AGIR sobre.

    ⚠️ O modelo não tem tela: se a ferramenta devolve só "falhou", ele tenta de novo,
    igual, e gasta um turno do editor. Dizer o que fazer corta o laço.
    """
    if isinstance(e, McApiFechado):
        return (
            "O Media Composer não está respondendo. Peça ao editor para abrir o "
            "Media Composer com um projeto antes de tentar de novo."
        )
    return f"O Media Composer recusou a chamada: {e}"


@ferramenta(
    nome="estado_do_projeto",
    descricao=(
        "O projeto aberto agora no Avid Media Composer: caminho, formato, resolução, "
        "taxa de quadros, e a versão do Media Composer. Use isto primeiro, antes de "
        "qualquer outra ferramenta do Avid, para saber com o que se está trabalhando."
    ),
    escreve=False,
)
def estado_do_projeto() -> dict[str, object]:
    try:
        with MediaComposer() as mc:
            return {"media_composer": mc.info(), "projeto": mc.projeto()}
    except McApiErro as e:
        return {"erro": _explicar(e)}


@ferramenta(
    nome="listar_bins",
    descricao=(
        "Lista as bins do projeto aberto no Avid, por caminho completo. A lixeira do "
        "projeto fica de fora, salvo se incluir_lixeira for verdadeiro."
    ),
    esquema={
        "type": "object",
        "properties": {
            "incluir_lixeira": {
                "type": "boolean",
                "description": "Incluir bins que estão na lixeira do projeto.",
                "default": False,
            }
        },
    },
    escreve=False,
)
def listar_bins(incluir_lixeira: bool = False) -> dict[str, object]:
    try:
        with MediaComposer() as mc:
            bins = mc.bins(incluir_lixeira=incluir_lixeira)
            return {"quantidade": len(bins), "bins": bins}
    except McApiErro as e:
        return {"erro": _explicar(e)}


#: ⛔ **Era só `masterClips`, e a bin de subclipes voltava VAZIA.** MEDIDO em 2026-09-15: o
#: modelo listou `CENAS\C07.avb` sem dizer os tipos, recebeu `"quantidade": 0` e concluiu
#: que os dez takes não estavam lá — é a bin onde eles moram. Subclipe é o que o editor
#: mais arrasta; ficar de fora do padrão é responder "vazio" sobre a bin mais usada.
TIPOS_PADRAO = ["masterClips", "subclips"]
@ferramenta(
    nome="listar_itens_da_bin",
    descricao=(
        "Lista o conteúdo de uma bin do Avid: nome, identificador (MobID) e se está "
        "selecionado. Aceita o caminho completo da bin ou o caminho relativo ao "
        "projeto. Os tipos possíveis são masterClips, subclips, sequences, groups, "
        "effects e AllTypes; sem tipos, lista masterclipes e subclipes."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {
                "type": "string",
                "description": "Caminho da bin, completo ou relativo ao projeto.",
            },
            "tipos": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Tipos de item a listar.",
                "default": TIPOS_PADRAO,
            },
            "apenas_selecionados": {
                "type": "boolean",
                "description": "Só os itens que o editor selecionou na bin.",
                "default": False,
            },
        },
        "required": ["bin"],
    },
    escreve=False,
)
def listar_itens_da_bin(
    bin: str,
    tipos: list[str] | None = None,
    apenas_selecionados: bool = False,
) -> dict[str, object]:
    try:
        with MediaComposer() as mc:
            # ⚠️ O modelo passa o caminho que VIU — e o que ele viu foi o absoluto, que
            # `listar_bins` devolveu. Mas o `GetListOfBinItems` só entende o relativo à
            # pasta do projeto, e recusa as outras formas com a MESMA mensagem
            # ("Bin is not open"), que manda depurar o estado da bin em vez do caminho.
            # Normalizar aqui é o que evita esse laço inteiro.
            relativa = mc.caminho_relativo_da_bin(bin)
            itens = mc.itens_da_bin(
                relativa,
                tipos=tuple(tipos or TIPOS_PADRAO),
                apenas_selecionados=apenas_selecionados,
            )
            return {
                # ⭐ O caminho COMPLETO volta junto, e não só o relativo: é ele que
                # `resolver_take` precisa, e a lição da fase 1 é que o modelo devolve o
                # que a ferramenta anterior lhe mostrou. Mostrar só o relativo faria a
                # próxima chamada chegar com um caminho que não abre arquivo nenhum.
                "bin": _absoluta(mc, bin),
                "bin_relativa": relativa,
                "tipos": list(tipos or TIPOS_PADRAO),
                "quantidade": len(itens),
                "itens": [
                    {"nome": i.nome, "mob_id": i.mob_id, "selecionado": i.selecionado}
                    for i in itens
                ],
            }
    except McApiErro as e:
        return {"erro": _explicar(e)}


def _absoluta(mc: MediaComposer, caminho: str) -> str:
    """Caminho de bin → absoluto, aceitando que já venha assim."""
    p = Path(com_extensao_de_bin(caminho))
    if p.is_absolute():
        return str(p)
    raiz = mc.projeto().get("caminho") or ""
    return str(Path(raiz) / caminho)


@ferramenta(
    nome="resolver_take",
    descricao=(
        "Traduz um clipe do Avid — subclipe ou masterclipe, mídia gerenciada ou AMA — no "
        "endereço físico: o arquivo de vídeo, os canais de áudio, e o ponto de entrada de "
        "cada um. Também separa "
        "cena, plano e take da claquete. Use antes de qualquer análise do conteúdo de um "
        "take — é o que diz onde a mídia está. Passe a bin e o nome do item que "
        "listar_itens_da_bin mostrou."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {
                "type": "string",
                "description": "Caminho da bin, como listar_itens_da_bin devolveu.",
            },
            "item": {
                "type": "string",
                "description": "Nome do clipe (subclipe ou master), ou o MobID dele.",
            },
        },
        "required": ["bin", "item"],
    },
    escreve=False,
)
def resolver_take(bin: str, item: str) -> dict[str, object]:
    try:
        caminho = bin
        if not Path(bin).is_absolute():
            # Só abre conexão com o MC se for realmente preciso: resolver um caminho
            # relativo exige saber onde o projeto mora, e isso custa uma chamada.
            with MediaComposer() as mc:
                caminho = _absoluta(mc, bin)
        return resolver(caminho, item).como_dicionario()
    except TakeErro as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": _explicar(e)}
