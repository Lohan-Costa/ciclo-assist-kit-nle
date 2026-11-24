"""`organizar_bins`: criar pasta, mover e renomear bin ou pasta no projeto do Media Composer.

Motor: `cicloassist/avid/organizar.py` (o painel lateral do MC É o disco). ⛔ Passa pelo portão:
mexe na organização do projeto do editor. O plano inteiro vai num cartão só, como o
`organizar_o_projeto` do Premiere — é o que deixa "organize o projeto do jeito X" ser UM pedido.
"""

from __future__ import annotations

from pathlib import Path

from ...avid import organizar as _organizar
from ...avid import painel_lateral as _painel
from ...avid.mcapi import McApiErro, MediaComposer
from ...servico import turno as _turno
from ..registro import ferramenta


def _projeto() -> str:
    with MediaComposer() as m:
        caminho = m.projeto(recarregar=True).get("caminho")
    if not caminho:
        raise _organizar.OrganizarFalhou("o Media Composer não está com um projeto aberto")
    return str(caminho)


def _conferir(operacoes=None, **_) -> str:
    try:
        return _organizar.conferir(_projeto(), operacoes)
    except _organizar.OrganizarFalhou as e:
        return str(e)
    except McApiErro as e:
        return f"Não consegui falar com o Media Composer: {e}"


@ferramenta(
    nome="organizar_bins",
    descricao=(
        "ESCREVE no projeto do Media Composer: cria PASTAS, MOVE bins e pastas para dentro de uma pasta, e "
        "RENOMEIA bin ou pasta. Mande o plano INTEIRO de uma vez (\"organize o projeto do jeito X\" é um pedido "
        "só): o editor aprova num clique. Os caminhos são os de listar_bins, relativos ao projeto, com '/' e "
        "sem .avb (ex.: 'D01/D01 CAM'); raiz = vazio. Uma pasta criada no plano pode receber bins logo depois, e "
        "uma bin renomeada é achada pelo nome novo adiante. Bin aberta é fechada antes (o MC a grava). No fim o "
        "painel lateral é atualizado pelo gesto na tela (clique direito ▸ Refresh), e a resposta diz se a lista "
        "do MC bateu com o disco ('painel_atualizado'). Nunca apaga bin nem mídia."
    ),
    esquema={
        "type": "object",
        "properties": {
            "operacoes": {
                "type": "array",
                "description": "Na ordem em que devem acontecer.",
                "items": {
                    "type": "object",
                    "properties": {
                        "acao": {"type": "string", "enum": list(_organizar.ACOES)},
                        "item": {"type": "string",
                                 "description": "mover/renomear: a bin ou pasta, relativa ao projeto (sem .avb)."},
                        "nome": {"type": "string",
                                 "description": "criar_pasta: o nome da pasta. renomear: o nome NOVO (só o nome)."},
                        "dentro_de": {"type": "string",
                                      "description": "criar_pasta: a pasta mãe; vazio = raiz do projeto."},
                        "para": {"type": "string",
                                 "description": "mover: a pasta de destino; vazio = raiz do projeto."},
                    },
                    "required": ["acao"],
                },
            },
        },
        "required": ["operacoes"],
    },
    escreve=True,
    conferir=_conferir,
)
def organizar_bins(operacoes: list[dict] | None = None) -> dict[str, object]:
    operacoes = list(operacoes or [])
    try:
        projeto = _projeto()
        # ⛔ O cartão pode ter esperado horas (ADR 0008): confere de novo contra o disco de AGORA.
        problema = _organizar.conferir(projeto, operacoes)
        if problema:
            return {"erro": f"o projeto mudou desde que você aprovou: {problema}", "nada_foi_feito": True}
        with MediaComposer() as m:
            def fechar(bin_absoluta: Path) -> None:
                _turno.avisar("fechando a bin antes de mexer", None, bin_absoluta.stem)
                try:
                    m._chamar("CloseBin", _timeout=60,
                              bin_path=m.caminho_relativo_da_bin(str(bin_absoluta)))
                except Exception:  # noqa: BLE001 — bin já fechada (como no montar_corte)
                    pass

            feitas = _organizar.executar(projeto, operacoes, fechar_bin=fechar)
    except _organizar.OrganizarFalhou as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer recusou: {e}"}

    saida: dict[str, object] = {"feitas": feitas, "quantas": len(feitas)}
    # ⭐ Até o refresh o MC lista o nome VELHO (medido), e o save só grava com algo modificado —
    #   renomear não suja nada. O refresh do painel lateral (achado pelo REA) não depende disso.
    try:
        r = _painel.atualizar(projeto, relatar=_turno.avisar)
        saida["painel_atualizado"] = bool(r.get("atualizado"))
        saida["custo_usd"] = r.get("custo_usd", 0.0)
    except _painel.AtualizarFalhou as e:
        saida["painel_atualizado"] = False
        saida["refresh_falhou"] = str(e)
    saida["manchete"] = f"{len(feitas)} operação(ões) feitas no disco do projeto"
    if not saida["painel_atualizado"]:
        saida["agora"] = ("Feito no disco, mas não confirmei o painel lateral do Media Composer em dia: clique "
                          "com o botão direito num vazio do painel de bins e escolha Refresh.")
    return saida
