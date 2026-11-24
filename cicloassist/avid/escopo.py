"""O que está no projeto ABERTO — o escopo de toda busca.

⭐⭐ **Decisão do editor (2026-09-13): a busca só alcança mídia referenciada por alguma bin
do projeto aberto.** A `Avid MediaFiles` pura não é escopo: tem mídia de outras produções e
mídia que ele tirou da bin e ficou no disco. Resultado de outro projeto, ou de material
descartado, é resposta errada que **parece certa** — o editor carrega o clipe na Source e
descobre que não é dali.

⭐ O mesmo limite existe no produto da Avid: a ajuda do Media Composer 25.6.0 diz que o
PhraseFind AI procura *"audible dialogue throughout bins in a single project"* — as bins do
projeto, não o disco (banco: `transversal/ia-embarcada-nos-nles.md`, §3b).

## ⭐ O ÍNDICE é global; o FILTRO é por projeto

O cache é endereçado pelo UMID do master justamente para atravessar projetos: analisou uma
vez, e quem usar aquele material de novo acha pronto. Quem se estreita é a RESPOSTA, na
hora de responder — nunca o que se guarda.

## ⛔⛔ A foto do último projeto varrido não serve como filtro

`bins.ler()` é o resultado da última vez que alguém clicou em "ler as bins" — que pode ser
de **outro projeto** e de dias atrás (medido em 2026-09-13: a foto era do `_Assist anterior`,
de 11/09, com o editor trabalhando noutro). Filtrar por ela devolveria o erro que se queria
evitar, de cabeça para baixo: esconderia o material do projeto de hoje e deixaria passar o
de ontem.

⇒ Aqui a lista vem do projeto **aberto agora**, e só é reaproveitada enquanto for dele e
recente (`VALIDADE_S`). Varrer custa pouco — medido no `_Assist anterior`: 5.524 mobs em 42
bins, 0,4 s (2026-09-11) e **323 masterclipes em 33 bins, 1,1 s** (2026-09-14, disco frio) —
e o cache de processo existe só para não repetir isso a cada chamada de um mesmo turno.

## ⚠️ Sem Media Composer aberto, o filtro NÃO vira "não achei nada"

Devolver zero porque o MC está fechado seria dizer ao editor que o material dele não existe.
Sem projeto aberto usamos a última varredura, dizendo de que projeto ela é e quando foi
feita; sem varredura nenhuma não há filtro, e a resposta **diz isso**. Toda resposta carrega
de onde veio o escopo, com a confiança que ele merece — `confirmado` só quando o Media
Composer respondeu.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from . import bins as _bins
from .mcapi import McApiErro, MediaComposer

log = logging.getLogger("cicloassist.avid.escopo")

#: Por quanto tempo a lista de chaves do projeto é reaproveitada sem reler as bins.
#:
#: ⚠️ Não é economia de disco (1,1 s nas 33 bins deste projeto, medido em 2026-09-14), é
#: de LATÊNCIA dentro de um turno: o modelo encadeia `procurar_no_material` e
#: `planos_parecidos` na mesma resposta, e cada um releria tudo.
#:
#: ⭐ E é também o relógio de "o editor trocou de projeto?": ao vencer, `agora()` pergunta
#: ao Media Composer de novo. Dois minutos é o que se espera de atraso para a busca seguir
#: o editor até o projeto novo — e uma bin criada agora aparecer na busca de daqui a pouco.
VALIDADE_S = 120

#: E quando NÃO há projeto aberto, o que se descobriu também vale por um pouco — menos.
#:
#: ⛔ MEDIDO em 2026-09-14, com o Media Composer FECHADO: `projeto_aberto()` gasta
#: **2,0 s** até o gRPC desistir, e isso acontecia a cada busca (a segunda chamada
#: seguida levou os mesmos 2,05 s). Duas ferramentas no mesmo turno = 4 s de espera para
#: descobrir duas vezes que o MC está fechado.
#:
#: ⚠️ Curto de propósito: aqui o cache guarda uma AUSÊNCIA, e o editor que acabou de abrir
#: o Media Composer não pode esperar cinco minutos para a busca achar o projeto dele.
VALIDADE_SEM_PROJETO_S = 30

SEM_PROJETO = "sem-projeto"

_trava = threading.Lock()
_projeto_em_cache: str = ""
_escopo_em_cache: "Escopo | None" = None
#: Até quando "não há Media Composer" vale sem perguntar de novo. ⛔ Ver `projeto_aberto`.
_sem_projeto_ate: float = 0.0


@dataclass(frozen=True)
class Escopo:
    """As chaves de master que o projeto aberto contém — ou `None`, que é "não sei".

    ⛔ `chaves=None` e `chaves=frozenset()` são coisas MUITO diferentes: a primeira é
    "ninguém leu bin nenhuma, não filtre"; a segunda seria "o projeto está vazio". Quem
    tratar as duas igual esconde o acervo inteiro ou o entrega inteiro.
    """

    chaves: frozenset[str] | None
    projeto: str = ""
    #: Quando as bins foram lidas — o carimbo que vai para a tela e para a resposta.
    quando: int = 0
    #: `projeto` · `foto` · `sem-projeto` · `nenhum` — de onde saiu a lista.
    #: ⚠️ `sem-projeto` é do PREMIERE: *"não sei de que projeto é, mas o BANCO é o limite"*
    #: (`nle/premiere._so_o_banco`). Não é `foto` — que é uma varredura velha das bins do
    #: Avid — nem `nenhum`, que é sem filtro nenhum.
    origem: str = "nenhum"
    #: Quando ESTE processo montou o escopo. ⚠️ Não é `quando`: uma foto de ontem lida
    #: agora tem `quando` de ontem e `lido_em` de agora, e é `lido_em` que diz quando
    #: vale a pena perguntar de novo.
    lido_em: float = 0.0
    #: ⭐⭐ De que editor este recorte fala — `avid` ou `premiere`. Ele não muda nada do
    #: filtro; muda as PALAVRAS do aviso, e isso é o produto. MEDIDO em 2026-09-21, com o
    #: painel dentro do Premiere: a tela dizia "423 masterclipes" e "o Media Composer não
    #: respondeu" sobre um projeto `.prproj` aberto na frente do editor — três substantivos
    #: do Avid numa frase que era para explicar o recorte. Nomenclatura errada não é enfeite:
    #: o editor lê "masterclipe" e vai procurar uma coisa que o Premiere não tem.
    editor: str = "avid"

    @property
    def filtra(self) -> bool:
        return self.chaves is not None

    @property
    def nome_do_projeto(self) -> str:
        return Path(self.projeto).name if self.projeto else ""

    def cobre(self, chave: str) -> bool:
        """Esta mídia está no projeto? Sem lista, tudo passa."""
        return self.chaves is None or chave in self.chaves

    def filtrar(self, itens: Iterable[dict], campo: str = "chave") -> list[dict]:
        return [i for i in itens if self.cobre(str(i.get(campo) or ""))]

    @property
    def _palavras(self) -> tuple[str, str, str]:
        """(nome do editor, o que o projeto tem, de onde a lista saiu) — ver `editor`."""
        if self.editor == "premiere":
            return ("O Premiere", "clipe(s)", "os itens do projeto aberto")
        return ("O Media Composer", "masterclipe(s)", "as bins do projeto aberto")

    @property
    def aviso(self) -> str:
        """A frase que vai na resposta do modelo — ela explica o que ficou de fora.

        ⚠️ Um filtro calado é pior que filtro nenhum: o modelo diria "não existe" sobre
        material que existe, e o editor acreditaria.
        """
        nle, unidade, de_onde = self._palavras
        if self.origem == "projeto":
            return (f"A busca cobre {de_onde} "
                    f"({self.nome_do_projeto}, {len(self.chaves or ())} {unidade}). "
                    f"Material que não está nele não aparece aqui.")
        if self.origem == "foto":
            quando = time.strftime("%d/%m %H:%M", time.localtime(self.quando)) if self.quando else "?"
            return (f"{nle} não respondeu, então a busca usou a última leitura "
                    f"de bins ({self.nome_do_projeto}, {len(self.chaves or ())} "
                    f"{unidade}, de {quando}). Se o projeto aberto for outro, o "
                    f"resultado é do projeto errado.")
        if self.editor == "premiere":
            # ⛔⛔ Banco vazio NÃO é "não achei": é "ainda não analisei nada aqui", e a
            #    diferença é a mesma de sempre — sem a frase, o editor lê que o material
            #    dele não tem o que ele procurou.
            if not self.chaves:
                return ("Ainda não analisei nada no Premiere. Importe a mídia no projeto e "
                        "mande processar: o que já estiver pronto de outro editor é "
                        "aproveitado em vez de refeito.")
            return (f"Ainda não sei de que projeto é esta busca, então ela cobre os "
                    f"{len(self.chaves)} clipe(s) já analisados no Premiere.")
        if self.origem == "banco":
            # ⚠️ "Todo o cache" seria falso desde que os bancos se separaram: o que ela
            #   cobre é o deste editor. E o aviso continua dizendo o que fazer.
            return (f"Ninguém leu as bins deste projeto ainda, então a busca cobre as "
                    f"{len(self.chaves or ())} mídias já analisadas no Media Composer — "
                    f"inclusive de outras produções. Para estreitar, abra a aba Vetores e "
                    f"leia as bins do projeto.")
        return ("Ninguém leu as bins deste projeto ainda, então a busca cobre TODO o cache "
                "— inclusive material de outras produções. Para estreitar, abra a aba "
                "Vetores e leia as bins do projeto.")

    def como_dicionario(self) -> dict[str, Any]:
        """Procedência do escopo, para ir junto de toda resposta que ele estreitou.

        ⚠️ `origem` não é o `fonte` do vocabulário de procedência da casa (aquele fala de
        onde saiu um DADO de mídia: claquete, roteiro, transcrição, visual, heurística).
        Aqui se declara de onde saiu o RECORTE — e "lido do projeto aberto" x "foto de uma
        varredura antiga" é a diferença entre confirmado e inferido.
        """
        return {
            "projeto": self.nome_do_projeto,
            "caminho": self.projeto,
            "masters_no_projeto": len(self.chaves) if self.chaves is not None else None,
            # ⭐ A tela precisa saber de que editor é este recorte para escolher as
            #   palavras (ver `editor`): "masterclipes" não existe no Premiere.
            "editor": self.editor,
            "origem": self.origem,
            "confianca": "confirmado" if self.origem == "projeto" else "inferido",
            "lido_em": self.quando or "",
        }


VAZIO = Escopo(chaves=None)


def projeto_aberto(recarregar: bool = False) -> str:
    """O caminho do projeto aberto, cacheado no processo.

    ⚠️ Cacheado porque cada consulta ao Media Composer custa o piso de ~500 ms, e isto
    entraria em TODO turno.

    ⛔⛔ **Mas o cache não pode ser eterno desde que a BUSCA depende dele.** Enquanto isto
    só amarrava a conversa a um projeto, trocar de projeto sem reiniciar o serviço era um
    incômodo. Agora o escopo da busca sai daqui: um cache preso faria `procurar_no_material`
    responder com o material do projeto ANTERIOR, calado, com o editor olhando as bins do
    novo. Por isso `agora()` recarrega isto toda vez que a lista de bins expira
    (`VALIDADE_S`) — o caminho quente continua sem perguntar nada, e a troca de projeto é
    notada em minutos, sem ninguém reiniciar nada.

    ⛔⛔ **E a falha vale por `VALIDADE_SEM_PROJETO_S`** (2026-09-22). Ela não era guardada
    aqui — só em `agora()` —, e o caminho da busca passa por esta função **quatro vezes**
    (`recortes_do_projeto`, `ha_projeto_para_indexar`, `recortes_prontos` e a taxa do
    projeto). MEDIDO com o Media Composer fechado: **8,47 s por busca**, quatro idas ao
    gRPC gastando 2 s cada para descobrir a MESMA ausência — contra os 0,3–0,4 s de uma
    busca quente. ⚠️ Trinta segundos é curto de propósito: quem acabou de abrir o Media
    Composer não pode esperar minutos pelo próprio projeto. E `recarregar=True` fura o
    cache, que é como `agora()` continua notando a troca de projeto.
    """
    global _projeto_em_cache, _sem_projeto_ate
    if _projeto_em_cache and not recarregar:
        return _projeto_em_cache
    if not recarregar and time.time() < _sem_projeto_ate:
        return SEM_PROJETO
    try:
        with MediaComposer() as mc:
            caminho = mc.projeto().get("caminho") or ""
    except McApiErro:
        caminho = ""        # sem MC aberto ainda dá para conversar; só não há projeto a que amarrar
    if not caminho:
        # ⛔⛔ A AUSÊNCIA nunca vai para `_projeto_em_cache` (2026-11-02): o MC na Select Project
        #   responde "sem caminho", e guardar "sem-projeto" ali o tornava um projeto ETERNO — o topo
        #   da janela disse "Media Composer 2024.6 · sem-projeto" com o FLUXO F1B aberto (o fluxo
        #   abriu o MC, que passou pela Select Project). Ausência vale `VALIDADE_SEM_PROJETO_S`.
        _projeto_em_cache = ""
        _sem_projeto_ate = time.time() + VALIDADE_SEM_PROJETO_S
        return SEM_PROJETO
    _projeto_em_cache = caminho
    _sem_projeto_ate = 0.0
    return _projeto_em_cache


def em_cache() -> str:
    """O projeto que já foi descoberto, SEM perguntar ao Media Composer.

    Para quem não pode pagar os 500 ms nem arriscar um gRPC no meio da partida do MC.
    """
    return _projeto_em_cache


def esquecer() -> None:
    """Joga fora o que este processo sabe — o projeto e a lista de chaves."""
    global _projeto_em_cache, _escopo_em_cache, _sem_projeto_ate
    with _trava:
        _projeto_em_cache = ""
        _escopo_em_cache = None
        # ⚠️ A ausência também: "esqueça tudo" tem de incluir "esqueça que não havia MC",
        #   senão um teste (ou um `/limpar`) herdaria a ausência do anterior.
        _sem_projeto_ate = 0.0


def projeto_do_recorte() -> str:
    """De que projeto é a lista que a busca está usando agora, se é de algum.

    ⭐ É o que responde "o recorte em uso ainda é do projeto que está na tela dele?" — e
    não `em_cache()`, que é só o último caminho descoberto: os dois são o mesmo na vida
    real e diferentes na hora que interessa, que é logo depois da troca.
    """
    guardado = _escopo_em_cache
    return guardado.projeto if guardado is not None and guardado.origem == "projeto" else ""


def esquecer_a_lista() -> None:
    """Joga fora só a lista de chaves, mantendo o caminho recém-descoberto.

    ⭐ Para quem acabou de ver o editor TROCAR de projeto: o caminho novo já está certo,
    e o que precisa cair é a lista do projeto anterior — sem pagar outra consulta ao
    Media Composer para redescobrir o que se acabou de descobrir.
    """
    global _escopo_em_cache
    with _trava:
        _escopo_em_cache = None


def _com_apelidos(masters, raiz: Path | None) -> frozenset[str]:
    """As chaves das bins mais a chave de CACHE de cada uma.

    ⭐ Desde a P1 do Premiere (2026-09-17) o master AMA é guardado pela chave do ARQUIVO,
    com o `mob_id` como apelido: sem esta tradução, o material AMA do projeto aberto
    sairia "fora do projeto" em toda busca.
    """
    from ..midia import cache as _cache

    ids = set()
    for m in masters:
        try:
            ids.add(_cache.de_umid(str(m)))
        except _cache.ChaveInvalida:
            ids.add(str(m))
    try:
        return _cache.com_apelidos(ids, raiz)
    except OSError:
        return frozenset(ids)


def agora(raiz: Path | None = None) -> Escopo:
    """O escopo de busca de agora: as chaves das bins do projeto aberto.

    ⚠️ Uma varredura por vez: duas buscas no mesmo turno não podem ler 42 bins em
    paralelo enquanto o ASR disputa a máquina.
    """
    global _escopo_em_cache

    with _trava:
        # ⚠️ A pergunta ao Media Composer entra DENTRO da trava, e depois do cache: sem
        #   isso, com o MC fechado, cada busca paga 2 s de gRPC para receber a mesma
        #   ausência (medido — ver `VALIDADE_SEM_PROJETO_S`).
        guardado = _escopo_em_cache
        if guardado is not None and guardado.origem == "projeto":
            # ⭐ Perguntar o projeto aqui é de graça: quem guardou uma lista já descobriu
            #   o caminho, e `projeto_aberto()` devolve o que está no cache do módulo.
            #   Trocou de projeto no meio da sessão? A lista guardada não serve.
            if (guardado.projeto == projeto_aberto()
                    and time.time() - guardado.lido_em < VALIDADE_S):
                return guardado
        elif (guardado is not None
                and time.time() - guardado.lido_em < VALIDADE_SEM_PROJETO_S):
            return guardado

        # ⛔ Aqui a lista venceu, e é a ÚNICA hora em que vale pagar os ~500 ms para
        #   perguntar de novo QUAL é o projeto: sem isto, quem trocasse de projeto no meio
        #   do dia continuaria buscando no anterior até reiniciar o serviço.
        projeto = projeto_aberto(recarregar=True)

        if projeto and projeto != SEM_PROJETO:
            try:
                masters = _bins.varrer(projeto)
            except OSError as e:
                log.warning("não consegui ler as bins de %s (%s)", projeto, e)
                masters = {}
            if masters:
                # ⭐ O resultado serve à aba Vetores tão bem quanto a nós: guardar aqui
                #   poupa ao editor um clique em "ler as bins" para ver a coluna cheia.
                # ⛔ E só com masters: gravar uma varredura VAZIA por cima apagaria a
                #   última boa — a leitura de um projeto recém-criado cegaria a busca no
                #   projeto anterior, que é justamente para onde o editor volta.
                _bins.guardar(projeto, masters, raiz)
                _escopo_em_cache = Escopo(
                    chaves=_com_apelidos(masters, raiz), projeto=projeto,
                    quando=int(time.time()), origem="projeto", lido_em=time.time())
                return _escopo_em_cache
            # Projeto aberto sem bin legível: cai para a foto, que ao menos diz de onde é.

        foto = _bins.ler(raiz)
        chaves = _com_apelidos(foto.get("masters") or {}, raiz)
        if chaves:
            _escopo_em_cache = Escopo(
                chaves=chaves, projeto=str(foto.get("projeto") or ""),
                quando=int(foto.get("quando") or 0), origem="foto",
                lido_em=time.time())
        else:
            # ⛔⛔ Nem projeto nem foto: SEM recorte de projeto, mas **dentro do banco do
            #    Avid** (2026-09-22). A regra *"não sei ≠ nenhuma"* existe para que
            #    desconhecer o projeto não esconda o acervo do editor — ela nunca autorizou
            #    mostrar o acervo do OUTRO editor, e é a mesma decisão que o Premiere já
            #    tinha (`nle/premiere._so_o_banco`). Sem isto, o Avid sem bins lidas
            #    devolvia entradas do banco do Premiere, com o nome de arquivo dele.
            #    ⚠️ Banco vazio continua sendo `None` (sem filtro): no primeiro dia de uso
            #    não há entrada nenhuma, e filtrar por um conjunto vazio faria a busca
            #    responder "não achei" sobre um cache que ela nem olhou.
            do_banco = _cache_do_avid(raiz)
            _escopo_em_cache = Escopo(chaves=do_banco or None,
                                      origem="banco" if do_banco else "nenhum",
                                      lido_em=time.time())
        return _escopo_em_cache


def _cache_do_avid(raiz: Path | None) -> frozenset[str]:
    """As chaves que o banco do AVID conhece. ⚠️ Leitura de manifesto por entrada; é o
    caminho raro (sem projeto e sem foto), e a alternativa é mostrar o banco do outro."""
    from ..midia import cache as _cache

    try:
        return frozenset(_cache.chaves_da_origem("avid", raiz))
    except Exception:  # noqa: BLE001 — sem banco legível, o comportamento de antes
        log.debug("não consegui listar o banco do Avid", exc_info=True)
        return frozenset()
