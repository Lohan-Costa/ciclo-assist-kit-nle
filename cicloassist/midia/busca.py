"""Procurar no material: a decupagem **e** a fala, numa linha por MÍDIA.

⛔⛔ **MEDIDO em 2026-09-20, no acervo do editor, e é o achado que dá forma a este módulo.**
Ele procurou `Personagem F` e a aba devolveu **4 resultados**, dizendo *"há mais informações com
esse indicador"*. Tinha razão:

| onde `personagem f` aparece no cache | quantos |
|---|---|
| decupagem (nota de mídia) | **2** |
| nota de take | 2 |
| **transcrição** | **241 falas em 86 mídias** |

E a camada de fala é muito maior que a de imagem: **319 mídias transcritas contra 168
decupadas**. A busca cobria a menor das duas.

⇒ Aqui as duas são varridas juntas. ⭐ **Nome próprio é o caso que prova a regra:** "Personagem F"
vem do roteiro ou da claquete, e quem a diz em voz alta é o DIÁLOGO — nunca o rosto (não há
reconhecimento facial neste produto, e não vai haver).

## Uma linha por MÍDIA, e as falas DENTRO dela

Decisão do editor (2026-09-20). Uma linha por FALA daria **241 linhas** para "Personagem F" — lista
que ninguém lê, com a mesma mídia repetida dezenas de vezes. O cartão é da mídia, e as falas
que casaram abrem dentro dele, como os planos parecidos já abrem.

## ⚠️ A fala se localiza em mm:ss do MASTER, e não em timecode

**MEDIDO: só 10 de 306 mídias transcritas têm a taxa gravada na fonte do cache.** Sem taxa
não há conversão para quadro nem para timecode, e inventar 25 fps erraria todo material
23,976. mm:ss desde o início do master é exato, não depende de nada, e responde a pergunta
que o editor faz aqui — *onde ouvir isto*.

⛔ **E é "onde ouvir", nunca "onde cortar".** O tempo cru do reconhecedor saiu da resposta de
`transcrever` justamente porque *"campo que existe para não ser usado um dia é usado"*
(CLAUDE.md). Quem for montar passa por `transcrever`, que dá o respiro medido; aqui o número
serve para achar o momento com o olho.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import cache as _cache
from . import decupagem as _decupagem
from . import falantes as _falantes
from . import intencao as _intencao
from . import timecode as _timecode

log = logging.getLogger("cicloassist.midia.busca")

#: Quantas falas de uma mesma mídia entram no cartão. ⚠️ Não é economia de bytes: uma mídia
#: com 30 falas casando empurraria as outras mídias para fora da tela, e a resposta à
#: pergunta *"onde mais?"* é justamente as outras.
FALAS_POR_MIDIA = 8


#: ⭐⭐ **As três faixas da preferência por subclipe** (pedido do editor, 2026-09-21).
#:
#: *"Em um trabalho real, os editores trabalham com subclipe ou groupclipe, recorrendo ao
#: bruto só quando não há esses tipos de arquivos."* ⛔ **É PREFERÊNCIA, não exclusão** —
#: nada some da lista, o que muda é a ordem.
FAIXA_RECORTE = 1      #: subclipe ou group clip: é com isto que o editor monta
FAIXA_NOVO = 2         #: master cujo material ainda não apareceu acima
FAIXA_REPETIDO = 3     #: master que é a origem de um recorte já mostrado — redundante


@dataclass
class Achado:
    """Um ITEM que casou: um subclipe da bin, ou o master.

    ⚠️ `chave` é sempre a do MASTER, inclusive num subclipe — é ela que endereça o cache
    (quadro, vetor, decupagem, fala). O subclipe não tem entrada no cache e nem deveria:
    processar um recorte seria reprocessar o material que o master já tem pronto.
    """

    chave: str
    midia: str
    #: A nota de decupagem que casou, se alguma — já no formato de `decupagem.procurar`.
    nota: dict[str, Any] | None = None
    #: As falas que casaram, com `inicio`, `texto` e o relógio pronto. Até `FALAS_POR_MIDIA`.
    falas: list[dict[str, Any]] = field(default_factory=list)
    #: Quantas falas casaram ao todo — pode ser maior que `len(falas)`.
    quantas_falas: int = 0

    # ── o recorte, quando este achado é um ───────────────────────────────────
    #: `master`, `subclipe` ou `grupo`.
    especie: str = "master"
    #: O nome do subclipe na bin, quando for um. Vazio no master.
    item: str = ""
    #: A bin do subclipe, relativa ao projeto — é o que o editor lê.
    bin: str = ""
    #: ⚠️ Todas as bins onde este MESMO recorte está. Medido no projeto do editor: 290
    #: pares (master, recorte) são **130 recortes distintos** — ele copia o subclipe entre
    #: as bins de trabalho, e um deles está em 6. Cinco linhas idênticas enchiam a lista
    #: antes de mostrar qualquer outra coisa.
    bins: list[str] = field(default_factory=list)
    #: ⭐ O MobID do RECORTE — é por ele que o Source carrega o subclipe em vez do master
    #: (medido em 2026-09-21: `LoadMobsIntoViewer` aceita o mob de um subclipe).
    mob_do_item: str = ""
    #: ⭐ Em que timelines do projeto este item aparece. Pedido do editor (2026-09-21).
    timelines: list[str] = field(default_factory=list)
    faixa: int = FAIXA_NOVO
    #: ⚠️ O recorte HERDOU o match sem poder conferir o tempo (a decupagem de mídia não tem
    #: posição: ela descreve o master inteiro). A tela diz, porque é menos certo.
    herdado: bool = False
    #: Onde começa este recorte no master, em quadros — só para a miniatura.
    inicio_no_master: int | None = None

    @property
    def por_imagem(self) -> bool:
        return self.nota is not None

    def como_dicionario(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "chave": self.chave,
            "midia": self.midia,
            "falas": self.falas,
            "quantas_falas": self.quantas_falas,
            "especie": self.especie,
            "item": self.item,
            "bin": self.bin,
            "bins": self.bins,
            "mob_do_item": self.mob_do_item,
            "timelines": self.timelines,
            "faixa": self.faixa,
            "herdado": self.herdado,
            # ⭐ De ONDE veio o resultado, em toda linha: sem isto o editor não sabe se
            #   achou porque alguém olhou o plano ou porque alguém o disse em voz alta —
            #   e as duas coisas se conferem de jeitos diferentes.
            "achado_por": ([*(["imagem"] if self.nota else []),
                            *(["fala"] if self.falas else [])]),
        }
        if self.nota:
            d.update({k: v for k, v in self.nota.items() if k not in ("chave", "midia")})
        # ⚠️ DEPOIS do `update`: num recorte a miniatura é do pedaço dele, não do meio do
        #   master — e a nota traria o `inicio_frames` dela por cima.
        if self.inicio_no_master is not None:
            d["inicio_frames"] = self.inicio_no_master
        return d


def relogio(segundos: float) -> str:
    """`254.3` → `04:14`. mm:ss desde o começo do master — ver o cabeçalho do módulo."""
    try:
        s = max(0, int(float(segundos)))
    except (TypeError, ValueError):
        return "00:00"
    return f"{s // 60:02d}:{s % 60:02d}"


def _timelines_de(chave: str) -> list[str]:
    """Em que timelines este MASTER aparece direto (sem subclipe no meio).

    ⚠️ Import tardio e tolerante: `midia/` não depende de `avid/`, e sem índice a etiqueta
    simplesmente não aparece.
    """
    try:
        from ..avid import subclipes as _subclipes

        return _subclipes.timelines_de(chave)
    except Exception:  # noqa: BLE001
        return []


def _casa_por_ou(texto_sem_acento: str, termo: str) -> bool:
    """Este termo é satisfeito pelo texto — por ele mesmo **ou** por uma equivalência.

    ⭐ OU dentro do termo, E entre termos (ver `midia/intencao.py`).
    """
    return any(_decupagem.casa_termo(texto_sem_acento, a)
               for a in _intencao.alternativas(termo))


def tc_do_master(midia: _cache.Midia) -> str:
    """O timecode de fonte deste master, ou `""`. Guardado — ver `midia/timecode.py`."""
    try:
        return _timecode.do_master(midia)
    except Exception:  # noqa: BLE001 — sem TC a linha fica com o mm:ss, e só
        log.debug("não consegui o timecode de %s", midia.chave[:12], exc_info=True)
        return ""


def falas_que_casam(midia: _cache.Midia, termos: list[str], tc_base: str = "",
                    fps=None, falante: str = "") -> list[dict[str, Any]]:
    """As falas desta mídia que satisfazem TODOS os termos.

    ⚠️ Todos os termos na MESMA fala, e não espalhados pela transcrição: "Personagem F consultório"
    espalhado casaria quase toda diária de uma novela, e o editor pediu um momento.

    ⭐ `tc_base` + `fps` dão o **timecode completo** do in de cada trecho — pedido do editor
    em 2026-09-21: o `mm:ss` serve para achar com o olho e não serve para digitar no Avid.
    Sem os dois, a fala sai só com o relógio, que é o comportamento de antes.
    """
    if not termos and not falante:
        return []
    # ⭐ quem fala, pela lapela (plano 2026-11-06): só o que o cache JÁ tem — a busca nunca mede nada
    transcricao = _falantes.anexar(midia.ler_transcricao(), _falantes.ler(midia))
    achadas = []
    for i, fala in enumerate(transcricao):
        if not isinstance(fala, dict):
            continue
        texto = str(fala.get("texto") or "")
        if not texto:
            continue
        sem = _decupagem.sem_acento(texto)
        quem = str(fala.get("quem") or "")
        if falante and not _e_de(quem, falante):
            continue
        if all(_casa_por_ou(sem, t) for t in termos):
            achadas.append({
                "n": i,
                # ⛔⛔ De QUE MASTER é este segundo. Parece redundante — o achado já tem uma
                #    chave —, e não é: numa linha fundida (`_fundir`) a chave que fica é a
                #    da IMAGEM, porque é ela que endereça a miniatura, enquanto a fala veio
                #    do SOM. MEDIDO no projeto do editor em 2026-09-22: **59 de 59** pares
                #    imagem+som têm TC de fonte DIFERENTE, e a diferença é de HORAS (a
                #    câmera em `03:14:14:17`, o gravador em `11:42:00:00` — TC de rolo
                #    contra hora do dia). Sem isto, o TC da fala saía do master errado por
                #    8 h e meia, e é um número para o editor DIGITAR no Avid.
                "chave_do_master": midia.chave,
                "inicio": fala.get("inicio"),
                "quando": relogio(fala.get("inicio") or 0),
                "tc": (_timecode.somar_segundos(tc_base, fala.get("inicio") or 0, fps)
                       if (tc_base and fps) else ""),
                "texto": texto.strip(),
                **({"quem": quem} if quem else {}),
                # Procedência em todo item: isto é o reconhecedor, não alguém escutando.
                "confianca": "inferido",
                "fonte": "transcricao",
                "medida": fala.get("certeza"),
            })
    return achadas


def _e_de(quem: str, falante: str) -> bool:
    """A fala é de `falante`? A RESOLVIDA (o rótulo é o nome) ou uma das vozes da SOBREPOSTA — nunca a ambígua."""
    f = falante.strip().upper()
    q = quem.strip().upper()
    return bool(f) and (q == f or (q.startswith("SOBREPOSTA:") and f"{f} «" in q))


@dataclass
class Alcance:
    """O tamanho do que a busca varreu — os quatro números que a tela precisa dizer.

    ⛔⛔ **Os dois primeiros não são o mesmo número, e o editor perguntou.** Vendo
    "168 de 323 mídias decupadas" ele leu *"168 seriam as mídias do projeto e 323 o total do
    banco?"* — não: os DOIS são do recorte. E faltava o terceiro: o projeto tem 423
    masterclipes, dos quais o cache só conhece 323. Rótulo que gera essa pergunta é rótulo
    que falhou.
    """

    #: Mídias do recorte com decupagem DE MÍDIA de verdade.
    decupadas: int = 0
    #: Mídias do recorte com transcrição.
    transcritas: int = 0
    #: Mídias do recorte que o cache conhece.
    no_cache: int = 0
    #: Masterclipes do projeto — `None` quando não há recorte ("não sei qual é o projeto").
    no_projeto: int | None = None

    def como_dicionario(self) -> dict[str, Any]:
        return {"decupadas": self.decupadas, "transcritas": self.transcritas,
                "no_cache": self.no_cache, "no_projeto": self.no_projeto}


def medir_alcance(raiz: Path | None = None,
                  chaves: "frozenset[str] | set[str] | None" = None,
                  no_projeto: int | None = None) -> Alcance:
    """Quantas mídias do recorte cada camada alcança.

    ⛔ **`decupadas` conta decupagem, não ARQUIVO.** Até 2026-09-20 ela contava quem tinha
    um `notas.json` no disco — e **4 das 172 estavam VAZIAS** (as que o
    `tools/consertar_quadros.py` esvaziou ao tirar as notas feitas sobre quadro errado). O
    número que a tela mostra prometia material que a busca não tinha.
    """
    a = Alcance(no_projeto=no_projeto)
    for midia in _cache.todas(raiz):
        if chaves is not None and midia.chave not in chaves:
            continue
        a.no_cache += 1
        # ⚠️ A conta é do que ESTA BUSCA alcança, e ela lê as duas camadas de imagem: a
        #   nota do material inteiro (a macro) e a do trecho (a micro). Contando só a
        #   macro, uma mídia decupada em trechos — que a busca acha, e com posição — ficava
        #   FORA do número, e a frase prometia menos material do que ela varre.
        #   ⭐ Diferente da coluna "decupada" da aba Vetores, que é a macro e só: lá a
        #   pergunta é "o que falta processar", aqui é "onde eu procurei".
        if any(n.get("escopo") in ("midia", "trecho") for n in midia.ler_notas()):
            a.decupadas += 1
        if midia.tem_transcricao():
            a.transcritas += 1
    return a


def procurar(
    termos: list[str] | None = None,
    campos: dict[str, str] | None = None,
    raiz: Path | None = None,
    limite: int | None = None,
    chaves: "frozenset[str] | set[str] | None" = None,
    recortes: dict[str, list] | None = None,
    falante: str = "",
) -> list[Achado]:
    """As mídias do recorte que casam, pela imagem **ou** pela fala.

    `falante` (a lapela, ex. `MIC2`) estreita às FALAS dessa pessoa — e aí a decupagem não responde: ela descreve a
    imagem, não diz quem falou.

    `campos` (os cinco fechados) só se aplicam à DECUPAGEM — uma fala não tem
    enquadramento. ⇒ Com campo pedido, a fala sozinha não basta: quem pede "close" está
    falando de imagem, e devolver um clipe só porque alguém disse a palavra lá dentro seria
    responder outra pergunta.

    `chaves` estreita ao projeto aberto. `None` é **sem filtro**, nunca "nenhum".

    `recortes` é o índice de subclipes do projeto (`avid/subclipes.indice`), e é o que liga
    a preferência do editor. Sem ele, só masters — que era o comportamento até 2026-09-21.

    ⚠️ Devolve TUDO: quem corta é quem chama, porque só ele pode dizer na tela quantos
    ficaram de fora. Cortar aqui transformaria a preferência em exclusão calada.
    """
    termos = [t for t in (termos or []) if t and t.strip()]
    campos = {k: v for k, v in (campos or {}).items() if v}
    recortes = recortes or {}

    de_master: list[Achado] = []
    #: ⛔⛔ **Um subclipe é UMA linha, mesmo vindo de dois masters.** O cache é endereçado
    #: por master e um subclipe sincronizado mistura DOIS — medido no projeto do editor:
    #: **140 dos 150 recortes**. Emitindo um achado por (master, recorte), o mesmo
    #: `C04_P06-T002` saía duas vezes: uma com as falas (do master de som, sem miniatura) e
    #: outra com o quadro e a decupagem. Foi o que ele viu na tela em 2026-09-21.
    #: ⇒ Aqui as duas contribuições se juntam: a imagem traz a miniatura e a decupagem, o
    #: som traz as falas. A regra "uma linha é um MASTER" vale na aba Vetores, não aqui —
    #: lá a pergunta é "o que falta processar", e o master é a unidade de processamento.
    de_recorte: dict[tuple, Achado] = {}

    for midia in _cache.todas(raiz):
        if chaves is not None and midia.chave not in chaves:
            continue

        # ⭐ Entre as notas que casam, a de TRECHO (decupagem micro) ganha da macro: ela tem
        #   POSIÇÃO, e o duplo clique leva a agulha até lá. A macro continua respondendo
        #   quando nenhum trecho casar — a micro complementa, não substitui.
        casaram = ([] if falante else
                   [n for n in midia.ler_notas() if _casa_com_intencao(n, termos, campos)])
        com_posicao = [n for n in casaram if n.get("escopo") == "trecho"]
        nota_que_casou = (com_posicao or casaram or [None])[0]

        # ⚠️ A fala não responde a campo fechado — ver o docstring.
        falas = [] if campos else falas_que_casam(midia, termos, falante=falante)

        if nota_que_casou is None and not falas:
            continue

        formatada = (_decupagem.formatar(nota_que_casou, midia, termos)
                     if nota_que_casou is not None else None)
        if formatada is not None:
            # ⭐ A descrição INTEIRA, para a setinha do cartão (pedido do editor,
            #   2026-09-22). Só aqui, e não no `formatar`: este módulo é o da ABA, e o
            #   `formatar` também serve o chat, onde parágrafos inteiros por resultado
            #   encheriam o contexto do modelo.
            formatada["descricao"] = str(nota_que_casou.get("descricao") or "")
        nome = midia.nome or midia.chave[:12]
        dos_recortes, o_master = _com_os_recortes(
            midia.chave, nome, formatada, falas, recortes.get(midia.chave) or [])
        de_master.append(o_master)
        for achado in dos_recortes:
            chave_de_juncao = (achado.item, tuple(achado.bins))
            anterior = de_recorte.get(chave_de_juncao)
            de_recorte[chave_de_juncao] = (_fundir(anterior, achado) if anterior
                                           else achado)

    achados = [*de_recorte.values(), *de_master]

    # ⭐⭐ A ordem: primeiro a FAIXA (subclipe → master novo → master repetido), e só depois
    #   o critério de sempre — quem casou nas DUAS camadas antes de quem casou numa, porque
    #   é o resultado de que o editor tem mais certeza sem abrir nada.
    achados.sort(key=lambda a: (
        a.faixa,
        0 if (a.nota and a.falas) else (1 if a.nota else 2),
        str((a.nota or {}).get("cena") or ""),
        str((a.nota or {}).get("plano") or ""),
        a.midia,
        a.item,
    ))
    return achados[:limite] if limite else achados


def carimbar_o_timecode(achados: list[Achado], fps) -> None:
    """Põe o TC completo nas falas destes achados — **depois do corte**.

    ⛔⛔ **MEDIDO em 2026-09-21: dentro da busca, isto custava 17,4 s.** Ler o TC é um
    `ffprobe` por master (172 ms frio) e a busca por "personagem f" casa 86 mídias — pagava-se o
    preço de todas para mostrar 40. Aqui só as linhas que o editor vai LER custam, e o
    valor fica guardado para sempre (o TC de fonte de um arquivo não muda).

    ⚠️ Sem taxa não se inventa nada: a fala continua com o `mm:ss`.
    """
    if not fps:
        return
    por_chave: dict[str, str] = {}

    def tc_de(chave: str) -> str:
        if chave not in por_chave:
            try:
                por_chave[chave] = _timecode.do_master(_cache.Midia(chave))
            except Exception:  # noqa: BLE001 — sem TC a linha fica com o relógio
                por_chave[chave] = ""
        return por_chave[chave]

    for achado in achados:
        for fala in achado.falas:
            # ⛔⛔ O TC sai do master DA FALA, nunca do master do achado. Numa linha fundida
            #    a chave do achado é a da IMAGEM (ela endereça a miniatura) e a fala veio do
            #    SOM — e os dois têm TC de fonte diferente em **59 de 59** pares medidos no
            #    projeto do editor, por HORAS. Ver `falas_que_casam`.
            tc = tc_de(fala.get("chave_do_master") or achado.chave)
            if tc:
                fala["tc"] = _timecode.somar_segundos(tc, fala.get("inicio") or 0, fps)


def _fundir(a: Achado, b: Achado) -> Achado:
    """As duas metades do MESMO recorte, numa linha só — ver `de_recorte` em `procurar`.

    ⭐ A IMAGEM manda no que se olha (miniatura, decupagem, nome do master na etiqueta) e o
    SOM traz as falas. Quem tiver nota fica com a nota; as falas se somam.
    """
    com_nota, sem_nota = (a, b) if a.nota is not None else (b, a)
    juntas = [*com_nota.falas, *sem_nota.falas]
    juntas.sort(key=lambda f: (f.get("inicio") or 0))
    return Achado(
        # ⚠️ A `chave` é a do master da IMAGEM quando há um: é ela que endereça o quadro
        #   que a tela mostra, e um subclipe sem miniatura foi o sintoma que o editor viu.
        chave=(com_nota.chave if com_nota.nota is not None
               else (com_nota.chave or sem_nota.chave)),
        midia=com_nota.midia if com_nota.nota is not None else sem_nota.midia,
        nota=com_nota.nota,
        falas=juntas[:FALAS_POR_MIDIA],
        quantas_falas=com_nota.quantas_falas + sem_nota.quantas_falas,
        especie=com_nota.especie,
        item=com_nota.item,
        bin=com_nota.bin,
        bins=com_nota.bins,
        mob_do_item=com_nota.mob_do_item or sem_nota.mob_do_item,
        timelines=com_nota.timelines or sem_nota.timelines,
        faixa=min(com_nota.faixa, sem_nota.faixa),
        # ⚠️ Só herdou se NENHUMA das metades pôde conferir o tempo: se o som confirmou a
        #   fala dentro da janela, o recorte não está herdando nada.
        herdado=com_nota.herdado and sem_nota.herdado and not juntas,
        inicio_no_master=(com_nota.inicio_no_master
                          if com_nota.nota is not None else sem_nota.inicio_no_master),
    )


def _com_os_recortes(chave: str, nome: str, nota: dict[str, Any] | None,
                     falas: list[dict[str, Any]],
                     recortes: list) -> tuple[list[Achado], Achado]:
    """Um master que casou vira: os recortes dele que também casam, mais ele mesmo.

    ⭐⭐ **A regra das três faixas** (`FAIXA_*`), decidida com o editor em 2026-09-21.

    **Um recorte casa por CONTER, quando há tempo para conferir:**

    | o que casou | tem tempo? | como o recorte entra |
    |---|---|---|
    | fala | sim (`inicio`, em segundos do master) | só se a janela dele **cobrir** aquele segundo |
    | decupagem de MÍDIA | não — ela descreve o master inteiro | **herdando**, e a tela diz que herdou |

    ⚠️⚠️ E a janela é a **daquele master**: um subclipe sincronizado mistura dois, com
    in-points diferentes (medido: imagem em 0, som em 214 frames). A fala está no tempo do
    master de SOM, e conferi-la contra o offset da imagem dessincroniza em 9 s — calado.

    ⛔ **O master só vai para a 3ª faixa se os recortes cobrirem TUDO o que ele casou.**
    Uma fala em 08:00 que nenhum subclipe alcança é material que só existe no master:
    mandá-lo para o fim por "já apareceu" enterraria a única linha que o tem.
    """
    saida: list[Achado] = []
    cobertas: set[int] = set()

    for _, iguais in _juntar_copias(chave, recortes).items():
        recorte = iguais[0]
        janela = recorte.janelas[chave]
        minhas = [f for f in falas if janela.cobre(f.get("inicio"))]
        # A nota de mídia não tem posição: ou o recorte a herda, ou não há nada a herdar.
        herda_a_nota = nota is not None
        if not minhas and not herda_a_nota:
            continue
        cobertas.update(f["n"] for f in minhas)
        onde = sorted({r.bin for r in iguais})
        saida.append(Achado(
            chave=chave, midia=nome, nota=nota,
            falas=minhas[:FALAS_POR_MIDIA], quantas_falas=len(minhas),
            especie=recorte.especie, item=recorte.nome, bin=onde[0], bins=onde,
            mob_do_item=getattr(recorte, "mob_id", ""),
            timelines=list(getattr(recorte, "timelines", []) or []),
            faixa=FAIXA_RECORTE,
            herdado=herda_a_nota and not minhas,
            inicio_no_master=_em_quadros(janela.inicio_s, recorte.fps_aprox),
        ))

    # ⭐ O master é sempre emitido: preferência não é exclusão.
    tudo_coberto = bool(saida) and all(f["n"] in cobertas for f in falas)
    o_master = Achado(
        chave=chave, midia=nome, nota=nota,
        falas=falas[:FALAS_POR_MIDIA], quantas_falas=len(falas),
        faixa=FAIXA_REPETIDO if tudo_coberto else FAIXA_NOVO,
        timelines=_timelines_de(chave),
    )
    return saida, o_master


def _juntar_copias(chave: str, recortes: list) -> dict[tuple, list]:
    """O MESMO recorte copiado em várias bins vira UMA entrada, com as bins juntas.

    ⛔⛔ **MEDIDO no projeto do editor (2026-09-21): 290 pares (master, recorte) são 130
    recortes DISTINTOS** — ele copia o subclipe entre as bins de trabalho (`C04_FALAS`,
    `C04_FALAS NOVO`, `C04_FALAS NOVO 5`, `CENAS/C04`…), e um deles está em **6**. Sem
    juntar, uma busca por "personagem f" mostrava `C04_P06-T002` cinco vezes seguidas antes de
    qualquer outro material — a lista inteira gasta em cópias.

    ⚠️ A identidade é **nome + janela**, não só a janela: dois subclipes diferentes podem
    coincidir no recorte (um take inteiro aparado igual), e juntá-los perderia um nome que
    o editor reconhece.
    """
    juntos: dict[tuple, list] = {}
    for recorte in recortes:
        janela = recorte.janelas.get(chave)
        if janela is None:
            continue
        identidade = (recorte.nome, round(janela.inicio_s, 2), round(janela.fim_s, 2))
        juntos.setdefault(identidade, []).append(recorte)
    return juntos


def _em_quadros(segundos: float, fps: float) -> int | None:
    """Segundos do master → quadro, para a miniatura. `None` sem taxa — nunca chutando 25."""
    if not fps or fps <= 0:
        return None
    return max(0, int(round(float(segundos) * float(fps))))


def _casa_com_intencao(nota: dict[str, Any], termos: list[str],
                       campos: dict[str, str]) -> bool:
    """`decupagem.casa`, mas com o dicionário de intenção nos termos livres.

    ⚠️ Os CAMPOS continuam com a régua de `decupagem.casa`: lá o vocabulário é fechado e já
    tem os sinônimos dele. O dicionário de intenção é para o texto livre.
    """
    if campos and not _decupagem.casa(nota, [], campos):
        return False
    if not termos:
        return bool(campos)
    texto = _decupagem.texto_da_nota(nota)
    return all(_casa_por_ou(texto, t) for t in termos)
