"""O padrão de nome dos SUBCLIPES — o motor da aba Renomear, aplicado ao take.

⭐ Portado do Assist anterior (`modulos/preparar/nomear.py`) em 2026-09-05.

⭐⭐ **A mesma máquina, outra costura.** `nomes/template.py` e `nomes/campos.py` não
mudaram uma linha para isto: o que muda é de onde vêm os campos. Na aba Renomear eles
vêm das colunas ao vivo do Media Composer; aqui vêm do `Tomada` que o leitor já produziu e
das colunas dos masters da própria `.avb`. Era exatamente para isto que aquelas duas
camadas não sabem o que é Avid.

## O contrato que torna a mudança segura

⭐⭐ **`PADRAO` é `%nome`, e `%nome` é o nome que o app daria sozinho** — a claquete
quando ela resolveu, o nome do master quando não (§11). Então quem não mexer em nada
continua com exatamente os nomes de antes, fallback incluído. Há teste que prova.

## As duas origens

⚠️ O autor apontou a ambiguidade quando propôs o sistema: *"o subclipe é composto por
duas origens, então devemos ter algumas tags como `%nomedovideo` `%nomedoaudio` para
evitar dualidade"*. Aqui elas existem, e `%nome` nunca precisa adivinhar de qual se
está falando — ele é o nome do SUBCLIPE, uma terceira coisa.

## Precedência

Coluna medida do Avid > campo do take > derivado. É a mesma ordem da outra aba, pelo
mesmo motivo: uma coluna que o técnico de som preencheu vale mais que qualquer
reconstrução nossa. É o que faz Projeto B funcionar aqui — lá a claquete não resolve
(`24-1` não tem rótulo), mas `Scene` e `Tomada` estão na bin, separados.

⭐⭐ **Com UMA exceção declarada: `%cena`.** Ela é o campo que o editor pode corrigir na
tela, e por isso rende **o que a tela mostra** — inclusive a correção à mão. A regra é do
autor, 2026-09-06, e ele a nomeou pelas duas pontas:

> *"temos dois propósitos diferentes para `%cena` e `%scene`. `%cena` = valor indicado no
> painel refletindo possível alteração manual e o presumido. `%scene` = valor da coluna
> Scene como ele é, incluindo apenas o presumido mas não a alteração manual."*

⚠️ Sem a exceção, uma bin com uma coluna chamada `Cena` faria a coluna crua ganhar da
correção que o editor acabou de digitar — a tela mostrando uma coisa e a bin recebendo
outra, calada. A coluna não se perde: ela continua acessível pelo nome dela.
"""

from __future__ import annotations

import registro

import re

from nomes import campos as _campos
from nomes import template as _template

log = registro.log(__name__)

#: ⭐ O padrão de fábrica. Ver o contrato no topo do módulo.
PADRAO = "%nome"


def _sem_prefixo(valor, letra: str) -> str:
    """`"C04"` → `"04"`. Ver `renomear.derivador_de_claquete`, mesma regra."""
    return str(valor or "").lstrip(letra + letra.lower())


def _dois_digitos_de_take(bruto) -> str:
    r"""`"T7"` → `"07"`; `"T002.1"` → `"002.1"`; sem dígito → `""`.

    ⚠️ `zfill`, nunca fatiar: take 100 truncado viraria `00` e colidiria com o take 0.

    ⚠️⚠️ **E o PONTO sobrevive.** `T002.1` é o take de um órfão batizado pela posição
    (`takes._batizar_orfaos`), e o ponto é o que o distingue do take 002 de verdade.
    Um `re.sub(r"\D", "", ...)` — que foi o que se escreveu primeiro — devolvia `0021`,
    transformando o órfão do take 2 num take 21 que pode existir de verdade. Achado
    rodando sobre a `_D02_SYNC.avb`, não na mesa.
    """
    texto = str(bruto or "").lstrip("Tt")
    inteiro, ponto, resto = texto.partition(".")
    inteiro = re.sub(r"\D", "", inteiro)
    if not inteiro:
        return ""
    return inteiro.zfill(2) + ponto + resto


def contexto_da_bin(caminho_avb: str) -> tuple[dict, dict]:
    """`(colunas_por_nome, nomes_por_mob)` — tudo o que a ficha precisa da `.avb`.

    ⭐ **Um `open` só para os dois**, e a varredura é a mesma: abrir a bin duas vezes
    para colher dois dicionários do mesmo laço seria pagar duas vezes o passo caro
    deste módulo.

    ⚠️ As colunas são chaveadas por NOME e os nomes por MOB ID, e a assimetria é do
    material, não descuido: o `Tomada` guarda a ponte para o som por NOME (`nome_do_som`)
    e a ponte para a imagem por MOB ID (`Trecho.mob_id`). Uma chave só obrigaria a
    traduzir de um lado, e tradução é onde divergência nasce.

    ⚠️ TUDO dentro do `with`: o leitor do pyavb é preguiçoso, e ler atributo depois de
    fechar estoura em `seek of closed file`.

    ⚠️ Falha vira dicionário vazio, não exceção: sem as colunas o padrão ainda funciona
    com o que o `Tomada` sabe, e perder o trabalho inteiro por causa de um enriquecimento
    seria trocar tudo por nada.
    """
    # ⚠️ `leitura.abrir`, e não `avb.open` cru: uma bin com áudio de MÚSICA derruba o
    # pyavb 1.4.0 numa tag de extensão que ele não conhece. Ver `avid/leitura.py`.
    from avid.leitura import abrir
    # ⚠️ Master **e** subclipe: desde 2026-09-05 o subclipe autorado carrega a
    # própria claquete no `_USER` (ver `subclipes.montar_mob`), e ler só os
    # masters faria uma bin de subclipes voltar sem coluna nenhuma — que era
    # exatamente o buraco por onde a identidade se perdia na ida e volta.
    from avid.percurso import e_master, e_subclipe

    colunas: dict[str, dict] = {}
    mobs: dict[str, str] = {}
    try:
        with abrir(caminho_avb) as f:
            for mob in f.content.mobs:
                nome = getattr(mob, "name", None)
                if not (e_master(mob) or e_subclipe(mob)) or not nome:
                    continue
                mobs[str(mob.mob_id)] = str(nome)
                try:
                    u = dict(mob.attributes).get("_USER")
                    colunas[str(nome)] = dict(u) if u else {}
                except Exception:  # noqa: BLE001
                    colunas[str(nome)] = {}
    except Exception as e:  # noqa: BLE001
        log.info("não deu para ler o contexto de %r: %s", caminho_avb, e)
    return colunas, mobs


def ficha(take, colunas: dict, nomes_por_mob: dict | None = None) -> dict:
    """Os campos de UM take, na precedência declarada.

    Args:
        take: o `Tomada`.
        colunas: o que `contexto_da_bin` devolveu.
        nomes_por_mob: `{mob_id → nome}`, para `%nomedevideo`.
    """
    nomes_por_mob = nomes_por_mob or {}
    do_som = colunas.get(str(take.nome_do_som or ""), {})

    # ⭐ A imagem do take: o primeiro trecho de `picture`. Um take órfão de imagem não
    # tem nenhum, e o campo sai VAZIO — nunca ausente.
    nome_de_video = ""
    for t in (take.trechos or ()):
        if t.media_kind == "picture":
            nome_de_video = str(nomes_por_mob.get(t.mob_id, "") or "")
            if nome_de_video:
                break

    take_bruto = _dois_digitos_de_take(take.take)
    do_take = {
        # ⭐⭐ O campo que faz o padrão de fábrica reproduzir o comportamento de hoje.
        "nome": str(take.nome or ""),
        "episodio": _sem_prefixo(getattr(take, "episodio", None), "E"),
        "cena": _sem_prefixo(take.cena, "C"),
        "plano": _sem_prefixo(take.plano, "P"),
        "take": _sem_prefixo(take.take, "T"),
        "take2": take_bruto,
        "nomedoaudio": str(take.nome_do_som or ""),
        "nomedevideo": nome_de_video,
        "origem": str(take.origem or ""),
        "convencao": str(take.convencao or ""),
        "duracao": str(take.duracao or 0),
        "segundos": (f"{take.duracao / take.edit_rate:.1f}"
                     if take.edit_rate else ""),
    }
    # ⚠️ A ordem É a precedência: coluna medida primeiro. `juntar` fica com a primeira
    # que traz a chave.
    #
    # ⭐⭐ `cena` vem ANTES de tudo — é a exceção declarada no topo do módulo. É o único
    # campo que o editor corrige na tela, e o que a tela mostra tem de ser o que a bin
    # recebe. `%scene` (a coluna crua) continua onde estava.
    return _campos.juntar({"cena": do_take["cena"]},
                          _campos.de_colunas(do_som), do_take)


def fichas(takes, colunas: dict, nomes_por_mob: dict | None = None) -> list[dict]:
    """As fichas de todos os takes, **com a união das chaves preenchida**.

    ⚠️⚠️ O `completar` não é detalhe: sem ele, o mesmo padrão bloquearia num take e
    passaria no vizinho, dentro da MESMA bin — porque um tem a coluna `Production` e o
    outro não.
    """
    return _campos.completar(
        [ficha(t, colunas, nomes_por_mob) for t in (takes or [])])


def catalogo(fs) -> list[dict]:
    """Os campos disponíveis, no formato que o painel desenha."""
    return [{"nome": c.nome, "rotulo": c.rotulo, "procedencia": c.procedencia,
             "exemplo": c.exemplo}
            for c in _campos.catalogo(fs)]


def prever(takes, padrao: str | None, colunas: dict,
           nomes_por_mob: dict | None = None) -> dict:
    """O que cada subclipe vai se chamar — **e é isto que a tela desenha**.

    ⭐⭐ **A fonte única.** `aplicar` chama esta função e escreve o que ela devolveu;
    o painel desenha o que ela devolveu. Não existe janela em que o conferido e o
    escrito divirjam, porque é a mesma resposta.

    ⛔⛔ E ela precisou existir porque não era assim. O preview do Subclipar vinha de
    `nomes/preview.py` — o motor genérico, compartilhado com a aba Renomear — enquanto a
    escrita passava por `aplicar`, aqui, que tem uma regra a mais: **quem não casa o
    padrão cai no nome de origem**. Duas implementações da mesma pergunta, e a que
    divergia era justamente a do PREVIEW contra a do APLICAR. O autor viu as duas caras
    disso em 2026-09-06:

    > *"o preview no painel mostra que os subclipes serão feitos com o plano mantido.
    > 25-1 25-2 e etc... mas quando chega na bin, ele gera só com o nome informado na
    > cena, 25 (puro)."*

    e, no mesmo teste, um padrão que não desenhava nada:

    > *"a tag `%nome_do_audio` sozinho não mostra como seria o nome do subclipe, mas
    > adicionando um simples 'a' ele funciona."*

    O segundo é a mesma raiz: para o motor genérico, um nome que sai vazio **bloqueia**,
    e a tela escondia a lista inteira. Aqui vazio não é impedimento nenhum — é um take
    que vai receber o nome de origem.

    Returns:
        `{"tokens", "invalidos", "bloqueado", "linhas"}`, no formato que o painel já
        pinta. Cada linha traz `de_origem` — se aquele nome veio do padrão ou do
        fallback. ⚠️ A distinção é informação do editor, não detalhe interno: ele pediu
        que esses takes não saíssem sem nome, não que saíssem sem aviso.
    """
    takes = list(takes or [])
    fs = fichas(takes, colunas, nomes_por_mob)
    catalogo = fs[0] if fs else {}
    tokens = [{"bruto": t.bruto, "inicio": t.inicio, "fim": t.fim,
               "campo": t.campo, "cauda": t.cauda}
              for t in _template.analisar(str(padrao or ""), catalogo)]
    invalidos = [t for t in tokens if t["campo"] is None]
    # ⛔ Só o campo DESCONHECIDO bloqueia. `render` recusa esse de qualquer jeito, então
    # deixar o botão vivo seria prometer uma escrita que vai falhar.
    if invalidos or not takes:
        return {"bloqueado": bool(invalidos), "invalidos": invalidos,
                "tokens": tokens, "linhas": []}

    efetivo = str(padrao or "").strip() or PADRAO
    usados = _template.campos_usados(efetivo, catalogo)
    linhas = []
    for take, f in zip(takes, fs):
        nome = _template.render(efetivo, f)
        vazios = [c for c in usados if not str(f.get(c) or "").strip()]
        # ⛔⛔ TODOS os campos do padrão vazios também é "não casou" (Ciclo Assist,
        # 2026-11-01): `C%{cena}_P%{plano}_T%{take2}` num material sem cena, plano nem
        # take rendia `C_P_T` — não vazio, então passava, e os quatro subclipes saíam
        # com o MESMO nome. A regra do autor (05/09, em `aplicar`) é o nome de origem.
        # ⚠️ Vazio PARCIAL (cena sem plano → `C10_P_T001`) continua rendendo: é decisão
        # pendente do autor, não deste conserto.
        de_origem = not nome.strip() or (bool(usados) and len(vazios) == len(usados))
        if de_origem:
            nome = _nome_padrao(take)
        linhas.append({
            "nome": nome,
            "de_origem": de_origem,
            "vazios": vazios,
            "vazio_total": False,   # ⚠️ nunca: o fallback já respondeu por ele
            "repetido": False,
        })
    # ⚠️ Nome repetido é marcado nos DOIS lados — quem vê só o segundo assinalado conclui
    # que o primeiro está certo. O Avid ACEITA repetido, então isto avisa, não impede.
    contagem: dict[str, int] = {}
    for l in linhas:
        contagem[l["nome"]] = contagem.get(l["nome"], 0) + 1
    for l in linhas:
        l["repetido"] = contagem[l["nome"]] > 1

    return {"bloqueado": False, "invalidos": [], "tokens": tokens, "linhas": linhas}


def aplicar(takes, padrao: str | None, colunas: dict,
            nomes_por_mob: dict | None = None) -> list:
    """Os mesmos takes, com `nome` rendido pelo padrão.

    ⚠️ **Só o nome muda.** Cena, trechos e a marca de órfão decidem em que BIN o take
    cai e para onde o subclipe aponta; mexer neles aqui seria renomear mudando o
    material.

    ⚠️ Padrão vazio cai no `PADRAO` — vazio quer dizer *"do jeito de sempre"*, nunca
    *"clipe sem nome"*.

    ⭐⭐ **Escreve o que `prever` devolveu, e nada mais** — ver o aviso lá.

    ⭐⭐ E o take que não casa o padrão CAI NO NOME PADRÃO, em vez de recusar o lote —
    decisão do autor, 2026-09-05:

    > *"Caso um dos padrões escolhidos gere um clipe que não tem match — digamos, o
    > padrão é `%cena_%plano-%take` mas um ou mais subclipes não têm essa informação —,
    > eles seguem com o nome original do vídeo (e áudio, na exceção). Eles não devem vir
    > com o nome vazio."*

    ⚠️ Isto DIVERGE da aba Renomear de propósito, onde vazio bloqueia o lote inteiro. As
    duas situações não são a mesma: lá o editor escreve **por cima** de nomes que já
    existem, e aplicar metade deixa a bin em dois estados; aqui os subclipes estão sendo
    CRIADOS, e um que não casa o padrão continua sendo material que ele quer na bin.
    Recusar tudo por causa de um faria o take sem claquete impedir os cinquenta que têm.

    Raises:
        PadraoInvalido: campo que não existe no catálogo.
    """
    from dataclasses import replace

    takes = list(takes or [])
    if not takes:
        return takes
    previsto = prever(takes, padrao, colunas, nomes_por_mob)
    if previsto["invalidos"]:
        # ⚠️ Levanta o mesmo erro que `render` levantaria — quem chama já o trata.
        _template.render(str(padrao or "").strip() or PADRAO,
                         fichas(takes, colunas, nomes_por_mob)[0])
    linhas = previsto["linhas"]
    sem_padrao = sum(1 for l in linhas if l["de_origem"])
    if sem_padrao:
        log.info("%d subclipe(s) não casaram o padrão %r e ficaram com o nome de "
                 "origem", sem_padrao, str(padrao or "").strip() or PADRAO)
    return [replace(take, nome=l["nome"]) for take, l in zip(takes, linhas)]


def _nome_padrao(take) -> str:
    """O nome de origem: o do master de VÍDEO; o do som quando não há imagem.

    ⭐ A regra do autor, 2026-09-05 — e a exceção é literal: *"salvo exceções de
    ser um subclipe formado apenas pelo áudio"*.

    ⚠️ `or take.nome` no fim: um take sem master nenhum na bin ainda precisa de
    nome, e o que ele já tem é melhor que vazio.
    """
    return (getattr(take, "nome_do_video", "") or take.nome_do_som
            or take.nome or "").strip() or take.nome
