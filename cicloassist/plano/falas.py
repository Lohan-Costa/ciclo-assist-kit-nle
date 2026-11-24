"""Separar as falas de uma cena — a espinha que o modelo propõe e o código confere.

⭐⭐ **O formato é do editor, e vem do projeto anterior** (`_ASSIST ANTERIOR`, 2026-08-30/31):
uma bin com **uma timeline por fala**, cada uma enfileirando o trecho de cada take em que
aquela fala é dita — o fluxo que assistentes de montagem já fazem à mão, e que vive dentro
do Avid depois de o painel fechar.

```
C07_FALA01     - Boa tarde, doutora.
C07_FALA02     - Sinceramente? Não.
C07_FALA02.02  - Não… sinceramente, não sei.        ← variante: texto distinto
```

- `FALAnn` é o **momento** na cena, ordinal. `.vv` é **texto distinto** do mesmo momento —
  improviso agrupado, não "diferente do roteiro". Sem sufixo é a variante 1.
- ⛔ **Nada é cunhado.** Cada trecho REFERENCIA o clipe que o editor já tem, com o in/out da
  fala dentro dele — *"devemos retirar as falas através de in-out do subclipe principal, sem
  criar novos"* (o editor, 2026-08-30).
- ⭐ **O material manda no texto.** Com roteiro, ele dá a ordem e o nome; sem roteiro, a
  espinha emerge dos próprios takes, que são quase-duplicatas textuais. O código não sabe a
  diferença — confere o mesmo nos dois casos.

## A divisão do trabalho, a mesma do mapa de corte

O modelo julga o casamento ("Sinceramente? Não!" é a mesma fala que "Sinceramente, não."),
que é semântica. O código confere o que é conta, e cada conferência fecha um defeito que
uma verificação ingênua premiaria — *toda verificação define um gradiente, e o modelo desce
por ele* (`mapa.py`, o checker que aprovou dezesseis cortes no plano aberto):

| confere | fecha |
|---|---|
| a fala está no trecho (`parecenca` texto → dito) | o timestamp de um take aplicado em outro |
| nenhum segmento de OUTRA fala cabe inteiro no trecho | o take inteiro apontado para toda fala, que passaria na primeira |
| a ordem das falas dentro de cada take | fala do fim da cena ocupando o lugar de uma do começo |
| o mesmo trecho em duas falas | a mesma frase servindo a dois momentos |
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import esquema as _esquema
from .mapa import PARECENCA_MINIMA, parecenca


class FalasInvalidas(ValueError):
    """O pedido não tem a forma de uma separação de falas. A mensagem diz o que consertar."""


#: Quanto de um segmento do ASR tem de cair dentro do trecho para ele contar como "dentro".
#:
#: ⛔ A primeira versão media PALAVRAS a mais no trecho, e não servia: numa cena de três
#: falas, o take inteiro apontado para uma delas dava 30% de pureza — o mesmo número da fala
#: com o respiro mordendo os dois vizinhos. ⭐ Por SEGMENTO a diferença é de natureza: o
#: respiro morde a borda do vizinho (poucos frames), o take inteiro engole o vizinho TODO.
INTEIRO_DENTRO = 0.8

#: A borda do trecho em que um vizinho engolido, ou uma sobreposição, é respiro e não erro.
#:
#: ⚠️ MEDIDO na C07 (`spikes/as_falas_conferidas.py`, 10 takes, ~370 falas): o ASR partiu
#: "…flexibilizar **demais.**" num segmento de 9–10 frames, e o respiro da fala anterior o
#: cobre INTEIRO — 4 reprovações de pedido honesto, todas essa. Meio segundo a 24 fps; o
#: take inteiro engole segmentos a centenas de frames da borda.
MARGEM_DE_RESPIRO = 12

#: Quanto dois trechos do mesmo take podem se sobrepor antes de serem "o mesmo trecho". O
#: respiro de uma fala encosta na seguinte; metade do menor já é a mesma frase.
SOBREPOSICAO_MAXIMA = 0.5

#: O nome da timeline carrega o começo do texto — é o que torna a bin legível sem abrir nada.
TEXTO_NO_NOME = 40


@dataclass(frozen=True)
class Trecho:
    take: str
    inicio: int
    duracao: int

    @property
    def fim(self) -> int:
        return self.inicio + self.duracao


@dataclass
class Fala:
    n: int
    variante: int
    texto: str
    trechos: list[Trecho]
    confianca: str
    fonte: str
    personagem: str = ""
    porque: str = ""

    @property
    def rotulo(self) -> str:
        return f"FALA{self.n:02d}" + (f".{self.variante:02d}" if self.variante > 1 else "")


@dataclass
class Conferencia:
    problemas: list[str] = field(default_factory=list)
    nao_conferidos: list[str] = field(default_factory=list)

    @property
    def fecha(self) -> bool:
        return not self.problemas and not self.nao_conferidos


def cena_normalizada(cena: str) -> str:
    """`7`, `C7`, `07`, `c07` → `C07`. ⭐ Dois dígitos porque a bin ordena por texto, e
    `C10` antes de `C4` é confusão gratuita. O que não é número volta em caixa alta."""
    bruto = str(cena or "").strip()
    m = re.fullmatch(r"[cC]?\s*0*(\d{1,3})", bruto)
    return f"C{int(m.group(1)):02d}" if m else bruto.upper()


def nome_da_timeline(cena: str, fala: Fala) -> str:
    texto = " ".join(fala.texto.split())
    if len(texto) > TEXTO_NO_NOME:
        texto = texto[:TEXTO_NO_NOME].rstrip() + "…"
    return f"{cena_normalizada(cena)}_{fala.rotulo} - {texto}"


def _inteiro(valor, campo: str, onde: str, minimo: int) -> int:
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise FalasInvalidas(f"{onde}: {campo} tem de ser um número inteiro")
    if valor < minimo:
        raise FalasInvalidas(f"{onde}: {campo}={valor}, e o mínimo é {minimo}")
    return valor


def trechos_por_segmento(pedidas, segmentos_do_take):
    """O pedido do modelo, em SEGMENTOS da transcrição → o mesmo pedido em frames.

    `segmentos_do_take(take) -> [(entrada, saida)] | None`, em frames do take e na ordem
    de `transcrever` (o segmento 1 é o primeiro da lista); `None` quando não há transcrição.

    ⭐⭐ **MEDIDO em 2026-09-15** (Haiku, C07): copiando `inicio_no_take_frames` e
    `duracao_frames` à mão, o primeiro pedido tinha 32 trechos errados em 237 — e cada
    reprovação fazia o modelo reescrever 13 mil tokens de JSON, errando de novo. Com o
    número do segmento, o erro de CÓPIA deixa de existir; sobra o de ESCOLHA, que a
    conferência continua pegando igual.

    ⛔ Trecho em frames é recusado, não aceito "também": dois jeitos de pedir deixariam o
    jeito que errava vivo, e o modelo volta ao que viu na transcrição.

    ⚠️ Junta TODAS as recusas numa mensagem: parar na primeira custaria uma rodada inteira
    por trecho errado.
    """
    if not isinstance(pedidas, list):
        return pedidas
    problemas: list[str] = []
    traduzidas = []
    for i, p in enumerate(pedidas, 1):
        if not isinstance(p, dict) or not isinstance(p.get("trechos"), list):
            traduzidas.append(p)
            continue
        rotulo = p.get("fala")
        onde = f"FALA{rotulo:02d}" if isinstance(rotulo, int) else f"fala {i}"
        novos = []
        for k, t in enumerate(p["trechos"], 1):
            take = str(t.get("take") or "").strip() if isinstance(t, dict) else ""
            if not take:
                novos.append(t)      # a forma, `validar` recusa com a frase dela
                continue
            ot = f"{onde}, {take}"
            de, ate = t.get("do_segmento"), t.get("ate_o_segmento")
            if ate is None:
                ate = de
            if not all(isinstance(x, int) and not isinstance(x, bool) for x in (de, ate)):
                problemas.append(
                    f"{ot}: diga do_segmento (e ate_o_segmento se a fala ocupa mais de um) "
                    f"com o número `segmento` que transcrever mostrou. Não copie frames.")
                continue
            lista = segmentos_do_take(take)
            if lista is None:
                problemas.append(f"{ot}: {take} não tem transcrição. Transcreva o take antes.")
                continue
            if de < 1 or ate < de or ate > len(lista):
                problemas.append(
                    f"{ot}: segmentos {de}–{ate}, e a transcrição de {take} vai do 1 ao "
                    f"{len(lista)}" + (" (ate_o_segmento vem depois do do_segmento)"
                                       if ate < de else ""))
                continue
            # ⚠️ O segmento 1 pode começar antes do take — é a fala que atravessa o in-point
            #    (quase sempre a claquete). O trecho começa no take; a âncora decide se é fala.
            entrada = max(0, lista[de - 1][0])
            saida = lista[ate - 1][1]
            novos.append({"take": take, "inicio_no_take_frames": entrada,
                          "duracao_frames": saida - entrada})
        traduzidas.append({**p, "trechos": novos})
    if problemas:
        linhas = [f"- {x}" for x in problemas[:12]]
        if len(problemas) > 12:
            linhas.append(f"- … e mais {len(problemas) - 12}")
        raise FalasInvalidas("\n".join(linhas))
    return traduzidas


def validar(pedidas) -> list[Fala]:
    """A FORMA do pedido. Recusa o pedido inteiro: bin de falas pela metade é pior que nenhuma."""
    if not isinstance(pedidas, list) or not pedidas:
        raise FalasInvalidas("nenhuma fala no pedido")
    falas: list[Fala] = []
    for i, p in enumerate(pedidas, 1):
        if not isinstance(p, dict):
            raise FalasInvalidas(f"fala {i} não é um objeto")
        onde = f"fala {i}"
        n = _inteiro(p.get("fala"), "fala", onde, 1)
        # `null` do modelo vale como a variante 1, que é o padrão do esquema.
        v = _inteiro(1 if p.get("variante") is None else p.get("variante"),
                     "variante", onde, 1)
        onde = f"FALA{n:02d}" + (f".{v:02d}" if v > 1 else "")
        texto = str(p.get("texto") or "").strip()
        if not texto:
            raise FalasInvalidas(f"{onde}: sem texto — é ele que dá nome à timeline e que é "
                                 f"conferido contra o take")
        confianca = str(p.get("confianca") or "")
        fonte = str(p.get("fonte") or "")
        if confianca not in _esquema.CONFIANCAS:
            raise FalasInvalidas(f"{onde}: confianca {confianca!r}; use "
                                 f"{', '.join(_esquema.CONFIANCAS)}")
        if fonte not in _esquema.FONTES:
            raise FalasInvalidas(f"{onde}: fonte {fonte!r}; use {', '.join(_esquema.FONTES)}")
        brutos = p.get("trechos")
        if not isinstance(brutos, list) or not brutos:
            raise FalasInvalidas(f"{onde}: sem trechos — diga em que takes ela é dita")
        trechos = []
        for k, t in enumerate(brutos, 1):
            if not isinstance(t, dict) or not str(t.get("take") or "").strip():
                raise FalasInvalidas(f"{onde}, trecho {k}: diga o take")
            ot = f"{onde}, trecho {k} ({t['take']})"
            duracao = _inteiro(t.get("duracao_frames"), "duracao_frames", ot, 1)
            if duracao < _esquema.DURACAO_MINIMA:
                raise FalasInvalidas(f"{ot}: duracao_frames={duracao} parece segundo no "
                                     f"lugar de frame")
            inicio = t.get("inicio_no_take_frames", 0)
            if isinstance(inicio, int) and not isinstance(inicio, bool) and inicio < 0:
                # ⚠️ MEDIDO na C07: o `transcrever` devolve a fala que ATRAVESSA o in-point
                #    (a claquete cantada) com início negativo, e o modelo copia.
                raise FalasInvalidas(
                    f"{ot}: inicio_no_take_frames={inicio} começa antes do take. Essa fala "
                    f"atravessa o início do subclipe — quase sempre é a claquete. Se é mesmo "
                    f"fala da cena, use 0 e desconte da duração.")
            trechos.append(Trecho(str(t["take"]).strip(),
                                  _inteiro(inicio, "inicio_no_take_frames", ot, 0),
                                  duracao))
        falas.append(Fala(n, v, texto, trechos, confianca, fonte,
                          str(p.get("personagem") or "").strip(),
                          str(p.get("porque") or "").strip()))

    vistos = {}
    for f in falas:
        if (f.n, f.variante) in vistos:
            raise FalasInvalidas(f"{f.rotulo} aparece duas vezes. Texto distinto do mesmo "
                                 f"momento é outra variante.")
        vistos[(f.n, f.variante)] = f
    for f in falas:
        if (f.n, 1) not in vistos:
            raise FalasInvalidas(f"{f.rotulo} existe sem a FALA{f.n:02d}: a variante 1 é o "
                                 f"texto mais dito, e toda fala tem uma")
    return falas


#: Quanto olhar adiante do trecho atrás do resto de uma fala partida pelo ASR: ~30 s a 24 fps.
OLHAR_ADIANTE_FRAMES = 720
#: Quanto do que o trecho diz tem de estar na fala para ele contar como o começo dela.
COMECO_DA_FALA = 0.8


def _a_fala_continua(texto: str, dito: str, t: "Trecho", segmentos) -> str:
    """Se a fala começa no trecho e TERMINA nos segmentos seguintes, a frase que diz isso.

    ⭐ MEDIDO em 2026-10-22 (Qwen3-VL, o caso "1 fala, 1 clipe"): o ASR partiu a fala 1 em
       "Antes de surpreender os dois," (segmento 4) e "você nunca imaginou…" (segmento 5);
       o modelo apontou só o 4, ouviu "confira o segmento" e desistiu. A conta de que falta
       o seguinte é da máquina — e a frase diz o GESTO: `ate_o_segmento`.
    """
    # ⚠️ A janela começa no fim do trecho, e o recorte do ASR devolve também quem ATRAVESSA
    #    a borda — inclusive o próprio segmento apontado, se o respiro o estender. Fica de
    #    fora o que já está no trecho.
    # ⛔ Só quando o trecho É o começo da fala: quase tudo o que ele diz está nela. Sem isto,
    #    um trecho de OUTRA fala somado ao segmento seguinte passava do piso e a frase
    #    mandava estender o erro (o caso do tempo de um take aplicado em outro).
    if parecenca(dito, texto) < COMECO_DA_FALA:
        return ""
    adiante = segmentos(t.take, t.fim, OLHAR_ADIANTE_FRAMES) or []
    seguintes = [txt for de, _ate, txt in adiante if de > t.inicio and txt not in dito]
    for k in range(1, min(3, len(seguintes)) + 1):
        junto = " ".join([dito, *seguintes[:k]])
        if parecenca(texto, junto) >= PARECENCA_MINIMA:
            quais = "o segmento seguinte" if k == 1 else f"os {k} segmentos seguintes"
            return (f"a fala começa aqui (\"{dito[:40]}\") e continua em {quais} "
                    f"(\"{seguintes[k - 1][:40]}\"). Mantenha do_segmento e acrescente "
                    f"ate_o_segmento com o número {'dele' if k == 1 else 'do último'}.")
    return ""


def conferir(falas: list[Fala], segmentos, duracao_do_take=None) -> Conferencia:
    """O que é conta. `segmentos(take, inicio, duracao) -> [(de, ate, texto)] | None`, em
    frames do take (None: não transcrito); `duracao_do_take(take) -> int | None`."""
    conf = Conferencia()

    for f in falas:
        for t in f.trechos:
            onde = f"{f.rotulo}, {t.take}"
            if duracao_do_take is not None:
                total = duracao_do_take(t.take)
                if total is not None and t.fim > total:
                    conf.problemas.append(f"{onde}: o trecho vai até o frame {t.fim} e o take "
                                          f"tem {total}")
                    continue
            achados = segmentos(t.take, t.inicio, t.duracao)
            if achados is None:
                if t.take not in conf.nao_conferidos:
                    conf.nao_conferidos.append(t.take)
                continue
            dito = " ".join(texto for _, _, texto in achados)
            cobre = parecenca(f.texto, dito)
            if cobre < PARECENCA_MINIMA:
                continua = _a_fala_continua(f.texto, dito, t, segmentos)
                if continua:
                    conf.problemas.append(f"{onde}: {continua}")
                    continue
                conf.problemas.append(
                    f"{onde}: a fala é \"{f.texto[:48]}\", mas nesse trecho o take diz "
                    f"\"{dito[:64]}\" (parecença {cobre:.0%}). Confira o take e o segmento: "
                    # ⛔ MEDIDO (2026-09-16, Qwen3-VL): "releia" não bastou a quem nunca
                    #    tinha lido — o modelo inventou os segmentos e desistiu. Diga COMO.
                    f"chame transcrever para {t.take} (vem do cache, na hora) e use o "
                    f"número do segmento que ela devolve.")
                continue
            # ⛔ Um segmento que cabe INTEIRO no trecho e não é desta fala: o trecho engoliu
            #    outra fala. ⚠️ Segmento sem palavra de 3 letras ("Não.") dá parecença 1 e
            #    fica — é o órfão legítimo que o ator diz colado na própria fala.
            alheios = [texto for de, ate, texto in achados
                       if ate > de and (min(ate, t.fim) - max(de, t.inicio)) >=
                       INTEIRO_DENTRO * (ate - de)
                       and not (ate <= t.inicio + MARGEM_DE_RESPIRO
                                or de >= t.fim - MARGEM_DE_RESPIRO)
                       and parecenca(texto, f.texto) < PARECENCA_MINIMA]
            if alheios:
                conf.problemas.append(
                    f"{onde}: o trecho engole {len(alheios)} fala(s) que não são esta — "
                    f"\"{alheios[0][:48]}\". Aponte só o(s) segmento(s) desta fala.")

    # ⛔ A ordem dentro de cada take: o momento 3 não pode começar antes do momento 2 no
    #    mesmo take. Variantes do mesmo momento não se comparam entre si.
    por_take: dict[str, list[tuple[int, int, str]]] = {}
    for f in falas:
        for t in f.trechos:
            por_take.setdefault(t.take, []).append((t.inicio, f.n, f.rotulo))
    for take, lista in por_take.items():
        lista.sort()
        for (_, n_a, r_a), (_, n_b, r_b) in zip(lista, lista[1:]):
            if n_b < n_a:
                conf.problemas.append(
                    f"{take}: a {r_b} começa depois da {r_a} neste take — fora da ordem da "
                    f"cena. Se o ator repetiu a fala, use só uma das vezes.")

    # ⛔ O mesmo trecho servindo a dois momentos.
    todos = [(f, t) for f in falas for t in f.trechos]
    for i, (fa, ta) in enumerate(todos):
        for fb, tb in todos[i + 1:]:
            if ta.take != tb.take or fa is fb:
                continue
            cruza = min(ta.fim, tb.fim) - max(ta.inicio, tb.inicio)
            if cruza > MARGEM_DE_RESPIRO and \
                    cruza > SOBREPOSICAO_MAXIMA * min(ta.duracao, tb.duracao):
                conf.problemas.append(
                    f"{ta.take}: a {fa.rotulo} e a {fb.rotulo} apontam o MESMO trecho "
                    f"(frames {max(ta.inicio, tb.inicio)}–{min(ta.fim, tb.fim)}).")
    return conf


# ── o que ficou de fora ──────────────────────────────────────────────────────
#
# ⛔⛔ **MEDIDO em 2026-09-15** (Haiku, C07, roteiro arrastado): o primeiro pedido tinha 33
# momentos e 237 trechos, com 32 trechos apontando errado. A cada reprovação o modelo tirou
# falas em vez de consertar — 33 → 20 → 10 — e o de 10 PASSOU. O editor recebeu 10 das 16
# falas do roteiro, e o método (§5) já proibia exatamente isso.
#
# ⇒ As conferências acima respondem "o que está no pedido está certo?". Nenhuma respondia
#   "falta alguma coisa?" — e sem essa pergunta, cortar é o jeito mais barato de passar. É
#   o mesmo gradiente do checker que aprovou dezesseis cortes no plano aberto (CLAUDE.md).
#   Tirar continua possível, mas DITO: em `deixadas_de_fora`, com o porquê, e o editor vê.

#: Quanto das palavras de uma fala do roteiro tem de aparecer nos textos do pedido.
#:
#: ⚠️ MEDIDO nos pedidos reais de 2026-09-15 contra as 16 falas do roteiro da C07: as falas
#: presentes deram de **75% a 100%**, as ausentes de **8% a 50%**. A comparação é contra o
#: texto de TODOS os momentos juntos, porque o modelo quebra uma fala do roteiro em várias
#: frases (16 falas viraram 33 momentos). ⚠️ Fala curta de palavra comum ("Não sei, não
#: sei…") pode parecer coberta por outra — a rede pega o sumiço em bloco, não a fala solta.
COBERTURA_MINIMA = 0.6


@dataclass(frozen=True)
class DeFora:
    """O que o modelo deixou de fora de propósito, e por quê — é o que o editor lê."""
    porque: str
    roteiro: int | None = None
    take: str = ""


def validar_de_fora(brutos) -> list[DeFora]:
    if brutos in (None, ""):
        return []
    if not isinstance(brutos, list):
        raise FalasInvalidas("deixadas_de_fora tem de ser uma lista")
    saida = []
    for i, b in enumerate(brutos, 1):
        if not isinstance(b, dict):
            raise FalasInvalidas(f"deixadas_de_fora {i} não é um objeto")
        porque = str(b.get("porque") or "").strip()
        roteiro = b.get("roteiro")
        take = str(b.get("take") or "").strip()
        if roteiro is not None and (isinstance(roteiro, bool) or not isinstance(roteiro, int)):
            raise FalasInvalidas(f"deixadas_de_fora {i}: roteiro é o número da fala no roteiro")
        if roteiro is None and not take:
            raise FalasInvalidas(f"deixadas_de_fora {i}: diga a fala do roteiro, o take, ou os dois")
        if not porque:
            raise FalasInvalidas(f"deixadas_de_fora {i}: sem porque — é o que o editor vai ler")
        saida.append(DeFora(porque, roteiro, take))
    return saida


def trechos_por_take(falas: list[Fala]) -> dict[str, int]:
    conta: dict[str, int] = {}
    for f in falas:
        for t in f.trechos:
            conta[t.take] = conta.get(t.take, 0) + 1
    return conta


def conferir_cobertura(falas: list[Fala], de_fora: list[DeFora], roteiro=None,
                       takes_da_cena=None, textos_ja_na_bin=(),
                       anterior: dict[str, int] | None = None) -> list[str]:
    """O que falta, e não foi dito que falta. Lista vazia: nada sumiu calado.

    - `roteiro`: as falas do roteiro (`mapa.Fala`), ou None sem roteiro.
    - `takes_da_cena`: os takes da cena na bin, ou None quando não se sabe.
    - `textos_ja_na_bin`: momentos que já estão na bin de destino (a separação em lotes).
    - `anterior`: trechos por take no pedido RECUSADO de antes — o encolhimento.
    """
    problemas: list[str] = []
    fora_do_roteiro = {d.roteiro for d in de_fora if d.roteiro is not None}
    takes_fora = {d.take.casefold() for d in de_fora if d.take}

    if roteiro:
        dito = " ".join(f.texto for f in falas)
        na_bin = [t for t in textos_ja_na_bin if t]

        def coberta(r) -> bool:
            if parecenca(r.texto, dito) >= COBERTURA_MINIMA:
                return True
            # ⚠️ Ao CONTRÁRIO para o que já está na bin: dela só se lê o NOME da timeline, com
            #    o texto cortado em 40 caracteres. O começo de uma fala longa nunca cobriria
            #    60% dela; o que se pergunta é se aquele começo é desta fala.
            return any(parecenca(t, r.texto) >= COBERTURA_MINIMA for t in na_bin)

        faltam = [r for r in roteiro if r.n not in fora_do_roteiro and not coberta(r)]
        for r in faltam[:8]:
            problemas.append(
                f"roteiro {r.n} ({r.personagem}): \"{r.texto[:56]}\" não está em momento "
                f"nenhum. Separe esta fala; se nenhum take a diz, ponha em deixadas_de_fora "
                f"com o porquê.")
        if len(faltam) > 8:
            problemas.append(f"… e mais {len(faltam) - 8} falas do roteiro de fora "
                             f"({', '.join(str(r.n) for r in faltam[8:])})")

    conta = trechos_por_take(falas)
    presentes = {t.casefold() for t in conta}
    for take in takes_da_cena or []:
        if take.casefold() not in presentes and take.casefold() not in takes_fora:
            problemas.append(
                f"{take}: nenhum trecho. Se ficou de fora por decisão (abortado, sem som, só "
                f"claquete), ponha em deixadas_de_fora com o porquê.")

    for take, antes in sorted((anterior or {}).items()):
        agora = conta.get(take, 0)
        if agora < antes and take.casefold() not in takes_fora:
            problemas.append(
                f"{take}: tinha {antes} trechos no pedido recusado e agora tem {agora}. Não "
                f"conserte uma recusa tirando trecho — corrija o segmento apontado e mande o "
                f"resto igual. Se tirar é decisão, diga em deixadas_de_fora.")
    return problemas


def relatar(conf: Conferencia, limite: int = 12) -> str:
    """⚠️ Curto: cada linha de reprovação é contexto que o editor paga num turno que errou."""
    linhas = [f"- {p}" for p in conf.problemas[:limite]]
    if len(conf.problemas) > limite:
        linhas.append(f"- … e mais {len(conf.problemas) - limite}")
    if conf.nao_conferidos:
        linhas.append(f"- sem transcrição para conferir: {', '.join(conf.nao_conferidos)}. "
                      f"Transcreva esses takes antes.")
    return "\n".join(linhas)
