"""Qual editor está do outro lado — Media Composer ou Premiere — e o que muda com isso.

P2 do plano `docs/plano/2026-09-17-premiere.md`. O produto nasceu no Avid, e quase tudo
dele não depende de NLE: o cache, o ASR, os quadros, os vetores, a decupagem, o motor.
O que depende cabe em poucas perguntas, e elas moram aqui:

| pergunta | Avid | Premiere |
|---|---|---|
| qual é o projeto aberto? | gRPC (`avid/escopo.py`) | ExtendScript pela ponte do painel |
| o que é este item? | `.avb` (`avid/take.py`) | ExtendScript + a identidade do arquivo |
| que mídia o projeto usa? | as bins | os caminhos dos itens → `midia/identidade` |

## Quem diz qual é o NLE

O PAINEL. A página servida é a mesma nos dois; no Premiere ela tem `window.__adobe_cep__`
(banco, `plugins/premiere-cep/painel-servido-e-identidade.md`) e declara `nle: "premiere"`
em cada pergunta. O serviço guarda o do turno em andamento.

⚠️ **Um valor do processo, e não do fio de execução.** A ferramenta roda na thread que
atende o `/mcp`, que não é a do turno — um `contextvar` chegaria vazio lá. Funciona porque
o turno é um por vez (regra da casa, `servico/turno.py`): o NLE do turno vivo é o NLE de
toda ferramenta chamada nele. Com o Avid e o Premiere abertos ao mesmo tempo, vale o
último que perguntou — e é esse que está esperando resposta.
"""

from __future__ import annotations

import threading

AVID = "avid"
PREMIERE = "premiere"
TODOS = (AVID, PREMIERE)

NOMES = {AVID: "Avid Media Composer", PREMIERE: "Adobe Premiere Pro"}

_atual = AVID
_trava = threading.Lock()


def de_texto(valor: object) -> str:
    """O que o painel mandou → um NLE conhecido. Desconhecido é Avid, o de sempre."""
    texto = str(valor or "").strip().lower()
    return PREMIERE if texto == PREMIERE else AVID


def definir(nle: str) -> None:
    global _atual
    with _trava:
        _atual = de_texto(nle)


def atual() -> str:
    with _trava:
        return _atual


def nome() -> str:
    return NOMES[atual()]


def qual(nle: str | None = None) -> str:
    """O NLE desta pergunta: o que veio escrito, ou o do turno vivo.

    ⛔⛔ **Quem pergunta PELA TELA passa o seu, e quem pergunta pelo TURNO omite.** As duas
    coisas são diferentes e a diferença custou o defeito de 2026-09-21: a aba Busca (que
    nasceu três dias depois do porte) chamava o Avid direto, e no Premiere respondia com o
    recorte de um projeto do Media Composer que nem estava aberto.

    ⚠️ E ler o NLE de um pedido **não pode mexer no global** (`definir`). O global é o
    editor do TURNO em andamento, do qual dependem a persona e a lista de ferramentas
    (`registro.ferramenta(nles=…)`); uma busca na aba do Premiere virando esse valor no meio
    de um turno do Avid entregaria ao modelo as ferramentas do editor errado.
    """
    return de_texto(nle) if nle is not None else atual()


def projeto_aberto(recarregar: bool = False, nle: str | None = None) -> str:
    """O caminho do projeto aberto naquele NLE, ou `SEM_PROJETO`."""
    if qual(nle) == PREMIERE:
        from . import premiere
        return premiere.projeto_aberto(recarregar=recarregar)
    from ..avid import escopo
    return escopo.projeto_aberto(recarregar=recarregar)


def resolver_take(bin: str, item: str, nle: str | None = None):
    """O item → `avid.take.Take`, pelo NLE do turno. Erros como `TakeErro`."""
    if qual(nle) == PREMIERE:
        from . import premiere
        return premiere.resolver_take(bin, item)
    from . import avid
    return avid.resolver_take(bin, item)


def escopo_agora(nle: str | None = None):
    """O recorte de busca do projeto aberto (`avid.escopo.Escopo`), naquele NLE."""
    if qual(nle) == PREMIERE:
        from . import premiere
        return premiere.escopo_agora()
    from ..avid import escopo
    return escopo.agora()


def recortes_do_projeto(esperar: float = 0.0, nle: str | None = None) -> dict:
    """`{chave do master: [Recorte, …]}` do projeto aberto — a preferência por subclipes.

    ⛔ **Nunca espera por padrão, nos dois editores** (o conserto de 2026-09-21): quem tem
    índice velho o recebe na hora e o build corre no fundo. ⚠️ Nunca levanta: sem índice a
    busca responde por master, que é o comportamento de antes da preferência.
    """
    editor = qual(nle)
    projeto = projeto_aberto(nle=editor)
    from ..avid import escopo
    if not projeto or projeto == escopo.SEM_PROJETO:
        return {}
    try:
        if editor == PREMIERE:
            from .premiere import recortes
            return recortes.indice(projeto, esperar=esperar)
        from ..avid import subclipes
        return subclipes.indice(projeto, esperar=esperar)
    except Exception:  # noqa: BLE001 — ordem que falha não pode parar a busca
        import logging
        logging.getLogger("cicloassist.nle").debug(
            "não consegui indexar os recortes de %s", projeto, exc_info=True)
        return {}


def ha_projeto_para_indexar(nle: str | None = None) -> bool:
    """Dá para montar índice de recortes agora? (Isto é, há projeto aberto.)

    ⛔⛔ **Sem isto a tela MENTE, e ela mentia nos dois editores.** "Ainda estou lendo os
    subclipes… procure de novo em alguns segundos" saía sempre que não havia índice —
    inclusive quando não havia projeto ABERTO, e aí ninguém estava lendo coisa nenhuma e
    procurar de novo nunca mudaria nada. Achado em 2026-09-21 ao dirigir o painel por CDP
    fingindo estar no Premiere; o caminho do Avid com o Media Composer fechado é o mesmo.
    """
    from ..avid import escopo
    projeto = projeto_aberto(nle=qual(nle))
    return bool(projeto) and projeto != escopo.SEM_PROJETO


def recortes_prontos(nle: str | None = None) -> bool:
    """Há índice servível (mesmo velho)? ⚠️ A tela precisa DIZER quando não há: pedir a
    preferência e não tê-la é um resultado diferente de não pedir."""
    editor = qual(nle)
    projeto = projeto_aberto(nle=editor)
    from ..avid import escopo
    if not projeto or projeto == escopo.SEM_PROJETO:
        return False
    try:
        if editor == PREMIERE:
            from .premiere import recortes
            return recortes.esta_pronto(projeto)
        from ..avid import subclipes
        return subclipes.esta_pronto(projeto)
    except Exception:  # noqa: BLE001
        return False


def taxa_do_projeto(nle: str | None = None):
    """A taxa em que o editor EXIBE o material — a base do timecode da fala.

    ⛔ `None` sem projeto aberto, e aí a fala fica só com o `mm:ss`: o arquivo de som não
    declara taxa nenhuma (medido: `time_base = 1/48000`), e chutar 25 fps erraria todo
    material 23,976 — que é este acervo inteiro. Ver `midia/timecode.py`.
    """
    from ..midia import timecode as _timecode
    if qual(nle) == PREMIERE:
        from . import premiere
        try:
            estado = premiere.estado() or {}
        except Exception:  # noqa: BLE001 — sem ponte não há taxa, e a linha diz menos
            return None
        return _timecode.taxa_do_projeto(estado)
    from ..avid import escopo, mcapi
    # ⛔ Perguntar PRIMEIRO ao cache do escopo, que guarda a ausência por 30 s: sem projeto
    #   aberto a resposta é `None` de qualquer forma, e o gRPC gasta 2,0 s para desistir.
    #   Esta função é chamada uma vez por busca da aba — era um dos quatro tropeços que
    #   faziam uma busca custar 8,47 s com o Media Composer fechado (medido em 2026-09-22).
    if escopo.projeto_aberto() == escopo.SEM_PROJETO:
        return None
    try:
        with mcapi.MediaComposer() as mc:
            return _timecode.taxa_do_projeto(mc.projeto())
    except Exception:  # noqa: BLE001
        return None


def esquecer_os_recortes() -> None:
    """Descarta os índices guardados dos DOIS editores. Trocou de projeto, trocou de índice."""
    from ..avid import subclipes
    from .premiere import recortes
    subclipes.esquecer()
    recortes.esquecer()
