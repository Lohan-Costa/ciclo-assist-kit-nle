"""A aba Renomear — a costura entre o Media Composer e `nomes/`.

⭐⭐ **Este módulo é ADAPTADOR, e é de propósito que ele seja fino.** As regras de nome
moram em `nomes/template.py`; a leitura de coluna mora no `avid/mcapi.py`; o parse de
claquete mora em `media/claquete.py`. O que mora aqui é o que liga os três — e é por isso
que, a aba Subclipar for nomear os subclipes, o que ela reaproveita é tudo menos este
arquivo.

## O que o spike de 2026-08-28 estabeleceu, e que este módulo respeita

⭐ **`SetMobInfo` renomeia os QUATRO tipos** — masterclipe, subclipe, sequência e
efeito. É o que autoriza a aba a receber tudo sem filtro, como o autor pediu.

⚠️⚠️ **Tipo é CONJUNTO, não valor.** `GetListOfBinItems` não devolve o tipo do item;
descobre-se perguntando por flag. E as flags se sobrepõem: um `.wav` AMA responde a
`masterClips` **e** a `linkedMasterClips`. Tratar como valor único faria o mesmo clipe
aparecer duas vezes na lista.

⚠️⚠️ **As colunas COM VALOR, não todas.** `GetMobInfo` no padrão devolveu **31**
colunas num master AMA; com `includes_empty_columns=True`, **191**. Cento e noventa e um
campos num autocomplete é inutilizável; "todas" é opção explícita.

⭐ E quem abre as comportas é `includes_empty_columns`, **não** `only_visible_columns` —
medido, porque o nome do segundo sugere o contrário.

⚠️ **Coluna readonly o Media Composer recusa sozinho** (`"Unable to modify column
data."`, ErrorType 70) — então validar aqui é para dar mensagem boa, não para ficar
seguro. Mas com 192 colunas, descobrir só na hora de aplicar um lote de 50 é caro.
"""

from __future__ import annotations

import re

import registro

from avid.mcapi import McApiError
from nomes import campos as _campos
from nomes import preview as _preview

from media import claquete as _claquete

log = registro.log(__name__)

#: As formas que o `GetListOfBinItems` sabe listar. ⚠️ Sem `AllTypes`: ele não
#: acrescenta nada às demais e só duplicaria toda linha da lista.
#: ⚠️ Sem `sources` também — um SourceMob não é item de bin que o editor renomeie; ele
#: é a mídia por baixo, e apareceria como um duplicado sem nome do masterclipe.
TIPOS = ("masterClips", "linkedMasterClips", "subclips", "sequences", "effects",
         "motionEffects", "groups", "stereoscopicClips", "preCompsRE", "preCompsTMK")


# ─────────────────────────────────────────────────────────────────────────────
# Os derivadores: o parse por rótulo, rebaixado a UM provedor de campo.
#
# ⭐ Antes de 2026-08-28 a claquete ERA o mecanismo — hoje ela é uma fonte entre
# outras, e só entra onde a coluna não veio. É a correção de enquadramento do autor:
# onde o metadado é bom (Projeto B tem `Scene` e `Take` separados), o parse é
# desnecessário; onde o Resolve apagou tudo (PRODUCAO-A D01/D02/D04), ele é o que resta.
# ─────────────────────────────────────────────────────────────────────────────

def derivador_de_claquete(ficha: dict) -> dict | None:
    """`%cena`, `%plano` e `%take` a partir da claquete — ou `None`.

    ⭐ Tenta a COLUNA antes do nome, e a ordem é a da confiança: `Scene` é o que o
    técnico de som escreveu no set; o nome do clipe é o que o Avid montou depois, e
    pode ter sido renomeado por qualquer um no caminho.

    ⚠️⚠️ Devolve a cena **sem o prefixo** — `04`, não `C04`. Quem põe o `C` é o padrão
    que o editor escreve (`C%cena`), e devolver `C04` faria `C%cena` render `CC04`.

    ⚠️⚠️ A coluna `Scene` **não traz o take** — ele mora na coluna `Take`, separado.
    Medido na D03: `Scene='PROJETO A - 05-04 FOLLY C9 P1 SERIE'` e `Take='011'`. A
    gramática exige os três campos juntos (é ela que protege o material de câmera), então
    ler `Scene` sozinha NUNCA casaria — e o derivador cairia calado para o nome, que é a
    fonte menos confiável. Por isso as duas colunas são recompostas antes: `Scene` +
    `-T` + `Take` reconstrói exatamente o nome de arquivo que o gravador escreveu.

    ⚠️ `None` quando nenhuma fonte casa, e isso é resposta legítima (§11): Projeto B
    (`24-1`, sem rótulo), o ambiente da D04 e o doc do Projeto C passam por aqui e saem sem
    cena. **Nunca se inventa.**
    """
    cena_crua = str(ficha.get("scene") or "").strip()
    take_cru = str(ficha.get("take") or "").strip()
    recomposta = f"{cena_crua}-T{take_cru}" if cena_crua and take_cru else ""
    for fonte in (recomposta, cena_crua, ficha.get("name"), ficha.get("tapeid")):
        c = _claquete.ler(str(fonte or ""))
        if not c:
            continue
        return {
            "cena": c.cena.lstrip("Cc"),
            "plano": c.plano.lstrip("Pp"),
            # ⚠️ `lstrip("0")` levaria o take 0 a virar string vazia — daí o `or "0"`.
            "take": (re.sub(r"\D", "", c.take).lstrip("0") or "0") + _sufixo_presumido(take_cru),
        }
    return None


def _sufixo_presumido(take_cru: str) -> str:
    """`.1` de um take `001.1` — o órfão que o Subclipar batizou pela POSIÇÃO.

    ⛔ A claquete não o enxerga (o `.1` parece extensão de arquivo para quem lê nome), e
    perdê-lo dava ao órfão o nome do take real anterior, ou um take `0011` que não existe.
    """
    m = re.search(r"\.(\d+)\s*$", str(take_cru or ""))
    return f".{m.group(1)}" if m else ""


def derivador_de_take2(ficha: dict) -> dict | None:
    """`%take2` — o take com **pelo menos** dois dígitos.

    ⚠️⚠️ *Pelo menos*, nunca *exatamente*. Um `zfill(2)` acrescenta zero à esquerda e
    preserva o resto; um fatiamento `[-2:]` truncaria, e aí take `100` viraria `00` e
    colidiria com o take 0 — dois clipes com o mesmo nome, sem nada na tela que
    denuncie. O defeito existiu no script de medição da Fase 2 e virou teste.
    """
    cru = str(ficha.get("take") or "")
    bruto = re.sub(r"\D", "", cru.split(".")[0]) if _sufixo_presumido(cru) else re.sub(r"\D", "", cru)
    return {"take2": bruto.zfill(2) + _sufixo_presumido(cru)} if bruto else None


def _vazio(valor) -> bool:
    """Ausência de VALOR: `None` ou só espaço. Mesma regra de
    `nomes.campos._vazio` — repetida aqui, e não importada, porque é uma
    linha e importar privado de outro módulo é acoplamento sem ganho."""
    return valor is None or (isinstance(valor, str) and not valor.strip())


DERIVADORES = (derivador_de_claquete, derivador_de_take2)


# ─────────────────────────────────────────────────────────────────────────────
# Do arrasto ao levantamento
# ─────────────────────────────────────────────────────────────────────────────

def tipos_por_mob(mc, bin_relativo: str) -> dict[str, list[str]]:
    """`{mob_id → [tipos]}` de uma bin, perguntando uma vez por flag.

    ⚠️⚠️ Lista de tipos, não um tipo: as flags se sobrepõem (ver o topo do módulo).

    ⚠️ Uma flag que a versão do Media Composer não conhece responde `UNIMPLEMENTED`.
    Perder a lista inteira por causa de `stereoscopicClips` seria trocar tudo por nada,
    então cada flag falha sozinha e o que deu certo continua valendo.
    """
    fora: dict[str, list[str]] = {}
    nomes: dict[str, str] = {}
    for tipo in TIPOS:
        try:
            itens = mc.itens_da_bin(bin_relativo, flags=(tipo,))
        except McApiError as e:
            log.info("a flag %r não respondeu nesta versão do MC: %s", tipo, e)
            continue
        for i in itens:
            if not i.mob_id:
                continue
            fora.setdefault(i.mob_id, []).append(tipo)
            nomes[i.mob_id] = i.name
    fora["_nomes"] = nomes  # type: ignore[assignment]
    return fora


def levantar(mc, mob_ids, *, todas_as_colunas: bool = False) -> dict:
    """O que o painel recebe quando o editor solta clipes na aba.

    Returns:
        `{"itens": [{mob_id, nome, tipos, campos}], "catalogo": [...],
        "ignorados": [mob_id]}`.

    ⭐ Tudo vai de uma vez porque o CATÁLOGO é do cliente — é ele que alimenta o
    autocomplete, e uma ida ao servidor por tecla digitada ali seria desperdício.

    ⚠️ Mas o PREVIEW não roda no cliente, e a mudança de rumo é deliberada: um parser
    de wildcard em JavaScript seria uma segunda implementação da mesma gramática, e a
    que divergisse seria a do preview contra a do aplicar. Ver `prever`.

    ⚠️ Só a bin do PRIMEIRO mob é varrida. Arrastar de duas bins diferentes é possível
    na interface do Avid, e o que vier de fora sai em `ignorados` — visível, nunca
    descartado calado.
    """
    mob_ids = [m for m in (mob_ids or []) if m]
    if not mob_ids:
        return {"itens": [], "catalogo": [], "ignorados": []}

    absoluto = mc.bin_do_mob(mob_ids[0])
    relativo = mc.caminho_relativo_da_bin(absoluto) if absoluto else ""
    tipos = tipos_por_mob(mc, relativo)
    nomes = tipos.pop("_nomes", {})

    itens, brutas, ignorados = [], [], []
    for mob in mob_ids:
        if mob not in tipos:
            ignorados.append(mob)
            continue
        try:
            colunas = mc.colunas_do_master(mob, todas=todas_as_colunas)
        except McApiError as e:
            # ⚠️ Um efeito ou uma sequência podem não responder coluna nenhuma. O item
            # entra na lista assim mesmo — o autor pediu a aba SEM FILTRO, e um item
            # que some é pior que um item sem campos.
            log.info("sem colunas para %s: %s", mob, e)
            colunas = {}
        colunas.setdefault("Name", nomes.get(mob, ""))
        brutas.append(colunas)
        itens.append({"mob_id": mob, "nome": nomes.get(mob, ""),
                      "tipos": tipos[mob],
                      # ⚠️ A bin viaja POR ITEM, e não uma só para o lote: hoje
                      # todos vêm da mesma (só a do primeiro mob é varrida), mas
                      # é o `aplicar` que decide onde dar `Save Bin` — e ele
                      # precisa saber, não supor.
                      "bin": absoluto or ""})

    rotulos: dict = {}
    for b in brutas:
        for chave, rotulo in _campos.rotulos(b).items():
            rotulos.setdefault(chave, rotulo)

    fichas = _campos.completar([_campos.de_colunas(b) for b in brutas])
    fichas = _campos.completar([_campos.derivar(f, DERIVADORES) for f in fichas])

    # ⭐⭐ `%nome_original` — o campo que veio do NOSSO HISTÓRICO.
    #
    # Ele nasceu de um botão "voltar ao nome original" que estava certo por
    # dentro e errado por fora: o autor renomeou 150 itens, trouxe 5 para a tela,
    # pediu para voltar — e voltaram os 150. O escopo do botão era o LOTE; o que
    # a mão de quem usa esperava era ESTES CLIPES.
    #
    # Como campo, o escopo fica certo por construção: o padrão sempre se aplica
    # ao que está na tela, como qualquer outro. E ainda ganha composição —
    # `%nome_original`, `BKP_%nome_original`, o que o editor quiser.
    #
    # ⚠️ Item sem histórico recebe o NOME DE AGORA, e não vazio: "voltar ao
    # original" de quem este app nunca renomeou é ficar como está. Vazio
    # bloquearia o lote inteiro (é a regra do preview), transformando um clipe
    # que ninguém tocou num impedimento.
    from avid import desfazer as _desfazer

    originais = _desfazer.originais_de([i["mob_id"] for i in itens])
    for item, ficha in zip(itens, fichas):
        ficha["nome_original"] = originais.get(item["mob_id"]) or item.get("nome", "")
        item["campos"] = {k: v for k, v in ficha.items() if not k.startswith("_")}

    catalogo = [{"nome": c.nome, "rotulo": c.rotulo, "procedencia": c.procedencia,
                 "exemplo": c.exemplo}
                for c in _campos.catalogo(
                    fichas, rotulos=rotulos,
                    procedencias={"nome_original": _campos.HISTORICO})]
    return {"itens": itens, "catalogo": catalogo, "ignorados": ignorados}


# ─────────────────────────────────────────────────────────────────────────────
# O preview
#
# ⭐⭐ **Ele mora em `nomes/preview.py`, e é reexportado aqui.** Quando a aba Subclipes
# ganhou padrão de nome (2026-08-28), as duas passaram a precisar exatamente das mesmas
# quatro respostas do validador — e duas cópias delas divergiriam no dia em que uma
# regra mudasse. O que é do Avid fica neste módulo; o que é do NOME subiu.
#
# ⚠️ O nome `renomear.prever` continua valendo: é o que a rota do painel chama, e
# quebrar a importação para mudar de casa seria trocar acoplamento por churn.
# ─────────────────────────────────────────────────────────────────────────────

prever = _preview.prever


# ─────────────────────────────────────────────────────────────────────────────
# Aplicar — a única parte que ESCREVE no projeto do editor
# ─────────────────────────────────────────────────────────────────────────────
#
# ⚠️⚠️ **A bin do editor NÃO ganha coluna nenhuma.** O Assist anterior guardava o nome
# antigo numa coluna custom e removeu a tentativa inteira: `CreateCustomColumn` cria
# uma coluna NOVA a cada chamada (nove `GA Nome Original` lado a lado, medido) e o
# MCAPI não tem rpc de apagar coluna. Aqui a rede de segurança mora FORA da bin, em
# `avid/desfazer.py` — decisão do autor, 2026-09-04.

def _nomes_no_disco(caminho_avb: str) -> list[str]:
    """Os nomes dos mobs como estão NO ARQUIVO. Levanta se não der para ler.

    ⚠️ Lê TODO mob que tenha nome, sem distinguir master de composição. O leitor
    de `.avb` com a taxonomia completa chega na etapa do subclipador; para
    confirmar uma gravação, "o nome novo apareceu no arquivo?" basta.
    """
    import avb

    with avb.open(caminho_avb) as f:
        return [str(m.name) for m in f.content.mobs if getattr(m, "name", None)]


def aplicar(mc, plano, *, progresso=None, confirmar: bool = True,
            leitor_do_disco=None, tentativas: int = 20, espera: float = 0.5) -> dict:
    """Renomeia em lote. `plano` é `[{mob_id, bin, nome_atual, nome_novo}]`.

    Returns:
        `{"aplicados", "inalterados", "falhas": [...], "confirmado", "erro"}`.

    ## ⚠️ A `bin` viaja POR ITEM, e isto diverge do Assist anterior de propósito

    Lá o `aplicar` recebe UMA bin e faz um `Save Bin` no fim, porque o arrasto vem
    de uma bin só. Aqui o editor pode arrastar de bins diferentes sem perceber — e
    salvar apenas a última deixaria as outras com o asterisco no nome e a
    confirmação por releitura falhando para elas. Então se salva **uma vez por bin
    tocada**, na ordem em que apareceram.

    ## ⚠️⚠️ Confirmar a gravação, nunca presumi-la

    `salvar_bin_ativa()` devolve `True` quando o `DoCommand` é **aceito**, não
    quando a bin está no disco — `Save Bin` é assíncrono. A primeira medição do
    spike concluiu *"não persiste"* lendo o arquivo cedo demais, e estava errada.
    Daí a releitura, e daí `confirmado: False` ser resposta possível e honesta: o
    rename ACONTECEU na sessão; o que não se conseguiu foi provar que chegou ao
    arquivo, e o editor precisa saber para salvar à mão.

    ## ⚠️ Falha é POR ITEM

    Um `SetMobInfo` que falhe não derruba os outros — mas sumir do relatório seria
    pior que falhar: a bin fica em dois estados, e a lista é o único jeito de o
    editor saber onde parou.
    """
    import time

    plano = list(plano or [])
    fazer = [x for x in plano
             if str(x.get("nome_novo") or "") != str(x.get("nome_atual") or "")]
    # ⚠️ Renomear para o mesmo nome gasta uma chamada gRPC e suja a bin sem motivo:
    # num lote de 50 em que 3 mudam, seriam 47 escritas inúteis.
    inalterados = len(plano) - len(fazer)
    base = {"aplicados": 0, "inalterados": inalterados, "falhas": [],
            "confirmado": False, "erro": ""}
    if not fazer:
        return base

    total = len(fazer)
    aplicados = 0
    falhas = []
    for n, item in enumerate(fazer):
        if progresso:
            progresso(n, total, item.get("nome_novo") or "")
        try:
            mc.renomear_item(item["mob_id"], str(item.get("nome_novo") or ""))
            aplicados += 1
        except McApiError as e:
            log.warning("não renomeou %s: %s", item.get("mob_id"), e)
            falhas.append({"mob_id": item.get("mob_id"),
                           "nome_atual": item.get("nome_atual"),
                           "nome_novo": item.get("nome_novo"), "erro": str(e)})
    if progresso:
        progresso(total, total, "")

    base["aplicados"] = aplicados
    base["falhas"] = falhas
    if not aplicados:
        return base

    # ⚠️ UM `Save Bin` por BIN, no fim — nunca por item: `SetMobInfo` já é uma
    # chamada por clipe, e salvar a bin inteira a cada um faria o Media Composer
    # gravar o arquivo cinquenta vezes.
    # ⚠️ `abrir_bin` antes de cada `Save Bin`, porque ele age sobre a bin em FOCO.
    ids_que_falharam = {f["mob_id"] for f in falhas}
    bins = []
    for x in fazer:
        b = str(x.get("bin") or "")
        if b and b not in bins and x.get("mob_id") not in ids_que_falharam:
            bins.append(b)

    for b in bins:
        try:
            mc.abrir_bin(b)
        except McApiError as e:
            log.info("não deu para ativar a bin %s antes de salvar: %s", b, e)
            continue
        try:
            aceito = mc.salvar_bin_ativa()
        except McApiError as e:
            log.info("o Media Composer não aceitou o Save Bin de %s: %s", b, e)
            aceito = False
        # ⭐ Sem `DoCommand` (MC 24.6) o Save Bin é recusado — e o `CloseBin` grava: fecha e reabre.
        # Sem isto o nome novo ficava só na sessão, com a confirmação falhando dez segundos depois.
        if not aceito and hasattr(mc, "gravar_bin_fechando"):
            try:
                mc.gravar_bin_fechando(b)
            except McApiError as e:
                log.info("não deu para gravar %s fechando e reabrindo: %s", b, e)

    if not confirmar or not bins:
        return base

    # A confirmação exige que TODAS as bins tocadas mostrem os nomes novos: dar
    # `confirmado: True` com uma bin ainda por gravar seria a mentira exata que
    # esta releitura existe para impedir.
    esperados_por_bin: dict[str, set] = {}
    for x in fazer:
        if x.get("mob_id") in ids_que_falharam:
            continue
        b = str(x.get("bin") or "")
        if b:
            esperados_por_bin.setdefault(b, set()).add(str(x.get("nome_novo") or ""))

    ler = leitor_do_disco or _nomes_no_disco
    for _ in range(max(1, int(tentativas))):
        faltou = False
        for b, esperados in esperados_por_bin.items():
            try:
                no_disco = set(ler(b) or ())
            except Exception as e:  # noqa: BLE001
                # ⚠️ A bin pode estar sendo gravada AGORA. Falhar a LEITURA não é
                # falhar o renomeamento — ele já aconteceu na sessão.
                log.debug("ainda não deu para reler %s: %s", b, e)
                no_disco = set()
            if not esperados <= no_disco:
                faltou = True
                break
        if not faltou:
            base["confirmado"] = True
            return base
        if espera:
            time.sleep(espera)

    log.info("a(s) bin(s) não confirmaram a gravação em %d tentativa(s)", tentativas)
    return base
