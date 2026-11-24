"""O CATÁLOGO CURADO: que programa cada peça ocupa e o que ela entrega (fase N1 do plano `2026-11-08-janela-de-nodes.md`).

⭐ Só as peças em uso, não as 52 ferramentas. As ENTRADAS não estão aqui porque já existem: são o esquema da ferramenta.
⭐ `saidas` são os campos que a ferramenta devolve de verdade (lidos no código, 2026-11-08) e que interessam a outro node; `{passo.campo}` das receitas da casa
tem de estar aqui, e um teste confere.
⭐ `programa` é o que o executor vai usar na N3 para nunca rodar duas peças ao mesmo tempo no mesmo programa (medido: carregar, consultar e fechar colados derrubam o MC 5 de 5).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..resolve_proxy import ALTURA as _ALTURA_DO_PROXY

#: ⛔ Tirar o gerente só quando o editor pede um fluxo sem supervisão: não é um campo para ligar por engano.
SEMPRE_OCULTOS = frozenset({"sem_supervisao", "so_preparar"})
RESOLVE, PREMIERE, MEDIA_COMPOSER = "resolve", "premiere", "media_composer"
#: O programa vem do argumento `programa` do passo.
DO_ARGUMENTO = "do_argumento"
#: O NLE que o fluxo abriu por último: o sync roda no Premiere ou no Media Composer.
O_NLE_ABERTO = "o_nle_aberto"

#: ⭐ Como a peça usa o piloto (autor, 2026-11-08: o node tem de dizer). `SEMPRE` e `NO_MC` operam a tela: foto, modelo e mouse.
#: `SO_FOCO` só alterna o foco da janela do MC para ele indexar, sem mouse e sem modelo: é outra conversa e não entra no preço.
#: ⛔ A mesma regra está em `usoDoPiloto` (`painel/oficina.js`), porque o node muda na hora em que o editor troca o programa.
PILOTO_SEMPRE, PILOTO_NO_MC, PILOTO_SO_FOCO = "sempre", "no_mc", "so_foco"


@dataclass(frozen=True)
class Peca:
    programa: str
    saidas: tuple[str, ...] = ()
    #: `(rótulo, valor)` do que a operação não deixa mudar.
    travados: tuple[tuple[str, str], ...] = ()
    #: Argumentos que a tela não oferece. Quem já os tem na receita continua com eles.
    ocultos: tuple[str, ...] = ()
    #: O agente que esta peça chama. A conferência por código mora dentro dela: não é peça na tela, e ninguém a apaga sem querer.
    agente: str = ""
    piloto: str = ""
    #: `(campo, valor)`: o piloto só entra com este argumento.
    piloto_se: tuple[str, str] | None = None
    #: O que o piloto faz nesta peça, na língua do editor.
    piloto_faz: str = ""


_SO_FOCO = "Se a mídia ainda não foi indexada, alterna o foco da janela do Media Composer até ele indexar. Sem mouse e sem IA, mas a tela troca sozinha."

CATALOGO: dict[str, Peca] = {
    "abrir_programa": Peca(DO_ARGUMENTO, ("programa", "projeto"), piloto=PILOTO_NO_MC,
                           piloto_faz="No Media Composer o piloto escolhe ou cria o projeto olhando a tela, porque o programa não tem API para isso. No Resolve e no Premiere ele não entra."),
    "fechar_programa": Peca(DO_ARGUMENTO, ("programa",), piloto=PILOTO_NO_MC,
                            piloto_faz="No Media Composer o piloto faz File, Exit e Leave na tela. No Resolve e no Premiere ele não entra."),
    "converter_para_proxy": Peca(RESOLVE, ("pasta", "proxies", "problemas"), (("Codec", "ProRes Proxy"), ("Altura", str(_ALTURA_DO_PROXY)))),
    "converter_para_opatom": Peca(RESOLVE, ("pasta", "codec", "formato")),
    "importar_no_premiere": Peca(PREMIERE, ("bins", "importados", "sem_proxy")),
    "importar_masters_opatom": Peca(MEDIA_COMPOSER, ("bin", "masters"), piloto=PILOTO_SO_FOCO, piloto_faz=_SO_FOCO),
    "som_direto_gerenciado": Peca(MEDIA_COMPOSER, ("bin", "masters"), piloto=PILOTO_SO_FOCO, piloto_faz=_SO_FOCO),
    "organizar_bins": Peca(MEDIA_COMPOSER, piloto=PILOTO_SEMPRE, piloto_faz="No fim, o piloto clica com o botão direito no painel de bins e dá Refresh, para o Media Composer mostrar o que mudou."),
    "sincronizar": Peca(O_NLE_ABERTO, ocultos=("bin", "bins", "padrao"), piloto=PILOTO_NO_MC, piloto_se=("subclipes", "por_cena"),
                        piloto_faz="No Media Composer, com subclipes por cena, o piloto salva o projeto na tela para a pasta CENAS aparecer. No Premiere ele não entra."),
    "criar_merged": Peca(PREMIERE),
    "salvar_tudo": Peca(MEDIA_COMPOSER, piloto=PILOTO_SEMPRE, piloto_faz="O piloto clica num vazio da timeline e aperta Ctrl+S, porque o Media Composer não tem API para salvar o projeto."),
    "conformar_no_resolve": Peca(RESOLVE, ("timeline_no_resolve", "importou")),
    "entender_metadados_da_diaria": Peca("", ("regras_aprovadas", "regras_reprovadas", "perguntas", "producao"), agente="agente-de-metadado"),
    "perguntar_ao_editor": Peca("", ("respostas",)),
    "confirmar_na_memoria": Peca("", ("gravou", "producao", "regras")),
}

#: Medido em 2026-11-08 na diária PRODB (`docs/plano/2026-11-08-agentes.md`): 4.840 tokens e 16,7 s. O revisor do sync: ~4 s, tokens não medidos.
CUSTO_DO_AGENTE_DE_METADADO = (4840, 17)
SEGUNDOS_DO_GERENTE = 4
#: Medido em 2026-11-01 no MC 2024.6 (banco, `skills/piloto/SKILL.md`): abrir, criar, trocar e sair; US$ 0,04 a 0,12 de localizador e 22 a 58 s por operação.
CUSTO_DO_PILOTO = "US$ 0,04 a 0,12 e perto de 1 min"
#: Medido em 2026-11-08 no MC 2024.6, um aviso resolvido com um clique (`spikes/o_agente_do_piloto.py`): US$ 0,027, a consulta e a conferência do ponto.
CUSTO_DO_AGENTE_DO_PILOTO = "cerca de US$ 0,03"
