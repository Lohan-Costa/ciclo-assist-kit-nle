"""Decupar uma mídia sozinho — um turno do modelo por mídia, fora da conversa.

⭐⭐ **É o único lugar do produto que gasta a assinatura do editor SEM ele ter perguntado
nada.** Tudo o mais aqui responde a um pedido dele; isto trabalha enquanto ele monta. Por
isso duas coisas são regra, não preferência:

1. **o gasto é medido e devolvido**, por mídia, para a tela poder dizer o preço antes;
2. **a fila é interrompível**, e o que já foi decupado fica.

## ⛔ Por que o modelo NÃO escreve a nota aqui

Ele poderia chamar `anotar_o_que_vi` sozinho — e aí cada mídia acordaria o portão (ADR
0003) pedindo aprovação ao editor, que está montando. Em vez disso ele **responde**, e
quem grava é o serviço: o texto vira nota nossa, validada pelo vocabulário de
`midia/decupagem.py`. O modelo aqui é um par de olhos, não um agente com permissão.

⚠️ E a persona é OUTRA. A do chat fala com o editor num painel estreito; esta fala com um
programa e responde JSON. Reaproveitar a do chat produziria prosa simpática que ninguém lê.
"""

from __future__ import annotations

import json
import logging
import re
import subprocess
import tempfile
import threading
import time
from collections import deque
from pathlib import Path
from typing import Any

from ..midia import decupagem as _decupagem
from ..midia import intencao as _intencao
from .claude import SEM_CONTA, MotorIndisponivel, _ambiente_do_cli, achar_o_cli, frase_do_erro

log = logging.getLogger("cicloassist.motor.decupador")

#: ⚠️ Fechado e curto. Cada frase a mais aqui é multiplicada por CADA mídia da fila — num
#: acervo de trezentas, uma linha inútil custa trezentas vezes.
PERSONA = """Você decupa material bruto de cinema e TV para um assistente de edição.

Olhe os quadros e descreva o plano como um assistente escreveria na decupagem: quem
aparece e como está (roupa, cabelo), o que faz, onde está, a luz, o enquadramento, o que a
câmera faz, e o que aquele plano tem de particular para quem vai montar.

Descreva o que VÊ. Não invente nome de personagem, de ator nem de cena: se não souber quem
é, escreva "uma mulher", "dois homens". Não afirme emoção como fato — descreva a expressão
("expressão contida", "sorri") em vez de diagnosticar sentimento.

{IDIOMA}

{CLAQUETE}

Responda SOMENTE com um objeto JSON, sem cercas de código e sem uma palavra antes ou
depois. A chave de primeiro nível é a CHAVE da mídia, e o valor é a decupagem dela:

{"<chave da mídia>": {
   "descricao": "prosa, 2 a 5 frases",
   "etiquetas": ["palavras soltas para achar depois: pessoas, objetos, figurino, clima"],
   "enquadramento": "geral|conjunto|médio|americano|close|detalhe",
   "angulo": "normal|plongée|contra-plongée",
   "camera": "parada|pan|tilt|travelling|mão|zoom",
   "local": "interior|exterior",
   "momento": "dia|noite",
   "claquete": "SÓ se houver claquete — o objeto descrito acima"}}

Deixe um campo fora se os quadros não permitirem responder. Não invente valor.
Quando vierem várias mídias, olhe os quadros de TODAS antes de responder, e descreva cada
uma pelo que ela mostra — sem repetir a descrição de uma na outra."""


def _idioma() -> str:
    """⭐ A regra de idioma, com os termos do set tirados de `midia/termos.json`.

    MEDIDO em 2026-09-22: o modelo escreveu `clapperboard` em **39** decupagens e
    `claquete` em 2 — e o editor, procurando "claquete", não achou nada. O dicionário da
    busca conserta o que já foi escrito; isto conserta o que vem.
    ⚠️ Curta de propósito: cada palavra aqui é multiplicada por cada mídia da fila.
    """
    grupos = _intencao.grupos_de_termos()
    # ⚠️ O artigo quando o gênero está marcado: MEDIDO, o qwen3-vl escreveu "um claquete".
    artigo = {"f": "a ", "m": "o "}
    termos = "; ".join(f"{artigo.get(g.get('genero', ''), '')}{g['preferido']} "
                       f"(não {', '.join(g['evitar'])})" for g in grupos if g["evitar"])
    return ("Escreva em português do Brasil, com o vocabulário do set"
            + (f": {termos}." if termos else "."))


#: ⭐ A leitura da claquete (pedido do editor, 2026-09-22). Os formatos são os que ELE
#: descreveu e os MEDIDOS no material: a claquete deste acervo diz ROLO · CENA · PLANO ·
#: TOMADA (não "take"), e o rolo é câmera + cartão (A02 = câmera A, rolo 2).
#:
#: ⛔⛔ **Nenhum valor que se possa copiar, e a ESTRUTURA inteira mesmo assim.** As duas
#: metades desta frase são medidas, e cada uma custou uma rodada no Mac (8 mídias,
#: qwen3-vl:8b, 2026-09-23 — `spikes/o_exemplo_que_o_modelo_copia.py`):
#:
#: - o exemplo com valores plausíveis (`X07 · 31 · 8 · 5`) voltou como LEITURA em 7 das 8,
#:   e no cache em 30 de 50 mídias. Trocá-lo por outro valor plausível não adianta: a
#:   primeira versão usava a claquete real do take medido, e "leu certo" e "copiou" davam
#:   o mesmo número. ⇒ o lugar do valor (`‹cena›`), que denuncia a cópia — eco 7 → **0**;
#: - e nenhum literal na PROSA: a versão anterior explicava a notação americana com
#:   `"01-2"/"12A"`, e o modelo passou a devolver `rolo ["01-2"] · cena 01 · plano 2` em
#:   3 de 4. Todo literal do prompt é material de cópia, não só o do exemplo;
#: - ⛔ mas **os campos não saem da estrutura JSON**. Descrevendo-os em prosa ("copie o
#:   texto e dele tire rolo, cena…"), as 4 claquetes legíveis voltaram VAZIAS — e não por
#:   não ver: o `texto` trouxe a claquete inteira e certa, sem um campo preenchido. O banco
#:   já media isso em 2026-09-22: campo fora da lista de campos não é respondido.
#:
#: ⭐ E a AUSÊNCIA é dita como o caso comum, porque é o que o material mostra: a maioria das
#: mídias não tem claquete, e era aí que ele inventava. ⚠️ Isto NÃO acabou com a invenção
#: (4 de 4 continuaram respondendo onde não havia); o que mudou é que o chute deixou de ser
#: sempre o MESMO valor plausível e passou a ser pego pela conferência do rolo.
CLAQUETE = (
    'Quadros CABEÇA = começo do take, maiores. A maioria das mídias NÃO tem claquete: só '
    'responda "claquete" se VIR no quadro uma prancheta escrita — não vendo uma, omita o '
    'campo inteiro, e isso é o normal. Vendo uma: "claquete": {"texto": "copie aqui o que '
    'está escrito", "rolo": ["‹rolo›"], "cena": "‹cena›", "plano": "‹plano›", "take": '
    '"‹tomada›", "serie": false, "marcas": []} — cada ‹…› é o LUGAR do que você leu no '
    'quadro, nunca a resposta. Rolo = câmera+cartão, pode ser mais de um; tomada = take; '
    'cena e plano podem vir juntos num campo só, separe-os; marcas = PICKUP, MOS… escritas '
    'nela. Pequena ou borrada: {"legivel": false}. Nunca chute.'
)

PERSONA = PERSONA.replace("{IDIOMA}", _idioma()).replace("{CLAQUETE}", CLAQUETE)

#: O que pedimos por mídia. ⭐ Poucos quadros: seis cobrem um plano e custam metade de doze.
QUADROS = 6

#: ⭐⭐ A DENSIDADE, escolhida pelo editor (F3 do plano da decupagem; pedido dele:
#: *"manual e/ou automático"*). Seis quadros descrevem bem um plano e descrevem MAL um
#: master de quatro minutos que vai do geral ao close — e é o editor quem sabe qual dos
#: dois ele está mandando analisar.
#:
#: ⚠️ O automático já existe e mora na MICRO: `micro.posicoes_do_trecho` dá de 3 a 8 quadros
#: por trecho conforme o movimento medido. Aqui é a escolha manual da macro.
#:
#: ⛔ E ela muda o PREÇO, que é a promessa central da aba: o nível escolhido entra na conta
#: mostrada antes do clique, e a tela diz quantos quadros por mídia ele comprou.
DENSIDADES = {"macro": 6, "fino": 12, "exaustivo": 24}
DENSIDADE_PADRAO = "macro"


def quadros_da_densidade(nome: str | None) -> int:
    """Quantos quadros um nível pede. ⚠️ Nome desconhecido cai no padrão, nunca em erro:
    é escolha de tela, e um 400 aqui viraria "o botão não faz nada"."""
    return DENSIDADES.get(str(nome or "").strip().lower(), DENSIDADES[DENSIDADE_PADRAO])

#: ⭐⭐ Quantas mídias por TURNO, e este número vale dinheiro.
#:
#: MEDIDO em 2026-09-11: um turno de `claude -p` custa ~40 mil tokens de PISO — o prompt
#: de sistema e a maquinaria do CLI —, e só ~2,5 mil são o trabalho (seis quadros e a
#: resposta). Nosso catálogo inteiro de ferramentas é 3,4 mil. Ou seja: **o custo é do
#: turno, não do conteúdo**, e uma mídia por turno paga o piso trezentas vezes num acervo
#: de trezentas.
#:
#: ⚠️ E não dá para crescer à vontade: as imagens ficam no contexto e cada mídia a mais
#: soma ~2,5 mil tokens que são reenviados nas idas e voltas seguintes.
POR_TURNO = 3

#: ⭐⭐ O PREÇO, medido em 2026-09-11 com mídia real desta máquina (Haiku 4.5, 6 quadros):
#:
#:     1 mídia por turno    42.205 tokens · US$ 0,0254 · ~20 s por mídia
#:     3 mídias por turno   16.818 tokens · US$ 0,0153 · ~10 s por mídia
#:
#: A tela usa isto para dizer o custo ANTES, e é o único lugar onde ele está escrito.
#: ⚠️ Estimativa, não promessa: material mais longo e modelo mais caro mudam a conta.
#: ⚠️⚠️ E 2026-09-22: a leitura da claquete acrescenta 2 quadros de 1568 px por mídia
#: (~1,8 mil tokens cada). O número abaixo é ESTIMATIVA (16.818 + ~3.700), NÃO medido —
#: e a tela mostra este preço antes do clique. Medir com uma fila curta e trocar.
TOKENS_POR_MIDIA = 20500
CUSTO_POR_MIDIA_USD = 0.019
SEGUNDOS_POR_MIDIA = 10

#: ⚠️⚠️ **ARITMÉTICA, não medição.** Um JPEG de 768 px na receita da casa (`frames.LARGURA`)
#: ocupa ~442 tokens pela fórmula de tokens por imagem (largura × altura ÷ 750); 450 é ela
#: arredondada. Serve só para a conta de quem SOBE a densidade: o preço de 6 quadros é o
#: medido acima, e cada quadro além dos seis soma isto. ⚠️ Medir de verdade com uma fila
#: curta em `fino`, como o preço da claquete também espera.
TOKENS_POR_QUADRO = 450
#: O mesmo, em dólar: `CUSTO_POR_MIDIA_USD / TOKENS_POR_MIDIA` é o preço médio do token
#: desta mistura de entrada, cache e saída — é a única conversão que temos medida.
CUSTO_POR_QUADRO_USD = TOKENS_POR_QUADRO * CUSTO_POR_MIDIA_USD / TOKENS_POR_MIDIA


def preco_por_densidade(segundos_base: float | None = None,
                        teto_de_quadros: int = 0) -> dict[str, dict[str, float]]:
    """O que cada nível custa por mídia — para a tela dizer ANTES do clique.

    ⭐ A conta mora aqui, junto do número medido, e não no JavaScript: preço copiado para
    a tela envelhece calado (é a mesma razão de `TOKENS_POR_MIDIA` estar neste módulo).

    ⛔⛔ **E ela depende do MOTOR, que é a armadilha desta conta.** Pelo Claude o tempo quase
    não muda com a densidade — o custo é do TURNO, e olhar 12 quadros em vez de 6 não dobra
    nada. Pelo Mac o tempo É a inferência, e ela cresce com o número de imagens: usar a
    régua do Claude ali mostrou **20 min** para um trabalho de **3 horas** (visto na tela em
    2026-09-22, antes deste conserto). ⇒ `segundos_base` é o do motor, e com ele a conta
    passa a ser proporcional.

    `teto_de_quadros` é o limite do motor (no Mac, o que cabe no contexto do Ollama): o
    nível continua na lista, e o que muda é `quadros_efetivos` — a tela mostra os dois, e o
    editor vê que pediu 24 e vai receber 22.
    """
    base = DENSIDADES[DENSIDADE_PADRAO]
    saida: dict[str, dict[str, float]] = {}
    for nome, n in DENSIDADES.items():
        efetivos = min(n, teto_de_quadros) if teto_de_quadros else n
        if segundos_base is None:
            # ⚠️ Claude: um segundo a mais por quadro extra é folga honesta sobre o turno.
            segundos = SEGUNDOS_POR_MIDIA + max(0, efetivos - base) // 6
        else:
            # ⚠️ Mac: proporcional aos quadros, sobre o tempo MEDIDO no nível padrão.
            #   Estimativa — a inferência não é exatamente linear —, e o sinal está certo:
            #   mais quadros, mais tempo.
            segundos = round(segundos_base * efetivos / base)
        saida[nome] = {
            "quadros": n,
            "quadros_efetivos": efetivos,
            "tokens_por_midia": TOKENS_POR_MIDIA + (efetivos - base) * TOKENS_POR_QUADRO,
            "custo_por_midia_usd": round(
                CUSTO_POR_MIDIA_USD + (efetivos - base) * CUSTO_POR_QUADRO_USD, 5),
            "segundos_por_midia": segundos,
            # ⚠️ Medido só no padrão; os outros são a conta acima.
            "medido": efetivos == base,
        }
    return saida


class DecupagemFalhou(RuntimeError):
    """O turno não produziu uma decupagem utilizável."""


class SemConta(DecupagemFalhou):
    """⭐ O Ciclo Assist não está conectado a uma conta Claude (2026-11-07): nenhum lote vai dar certo, e a fila para com
    a frase que manda à seção Conta — antes cada lote falhava como "o modelo não respondeu em JSON", calado."""


def _uma_nota(dados: dict[str, Any]) -> dict[str, Any] | None:
    """Um dicionário cru do modelo → a nota que a gente grava, ou `None` se não serve."""
    if not isinstance(dados, dict):
        return None
    descricao = str(dados.get("descricao") or "").strip()
    if not descricao:
        return None

    campos: dict[str, str] = {}
    avisos: list[str] = []
    for campo, lista in _decupagem.CAMPOS.items():
        valor = dados.get(campo)
        if not valor:
            continue
        try:
            campos[campo] = _decupagem.normalizar(campo, str(valor), lista)
        except _decupagem.ValorForaDoVocabulario as e:
            # ⚠️ Descarta o CAMPO, não a decupagem: a prosa continua valendo e a busca
            #    por texto ainda acha. Gravar "plano bonito" em `enquadramento` sujaria o
            #    filtro para sempre.
            avisos.append(str(e))

    etiquetas = [str(e).strip() for e in (dados.get("etiquetas") or []) if str(e).strip()]
    nota = {"descricao": descricao, "etiquetas": etiquetas[:20], "avisos": avisos, **campos}
    claquete = ler_claquete(dados.get("claquete"))
    if claquete is not None:
        nota["claquete"] = claquete
    # ⛔⛔ E cena/plano/take NÃO sobem para o topo aqui. Quem promove é `conferir_a_claquete`,
    #    depois de conferir — ver a docstring dela. Promover antes é o que pôs 44 chutes nos
    #    filtros da busca (medido no cache em 2026-09-23).
    return nota


#: O rolo que o NOME do arquivo de câmera já traz: `A009_03190918_C010` (Blackmagic),
#: `A001C003` (ARRI), `A001_C003` (RED), `A_0002C016_260629_125302` (o material da *Mãe de
#: Ouro*, 2026-09-23) — câmera A, cartão 9 ou 2.
#: ⛔ O `_?` e o `{3,4}` são desse último: sem eles o nome não casava, a conferência ficava
#: SEM referência, e aí ela aprova o que vier — justamente num material cuja claquete é
#: outra (campos em inglês, `ROLL # A02`). Um acervo novo não pode chegar desprotegido.
_ROLO_NO_NOME = re.compile(r"^([A-Z])_?(\d{3,4})(?:_|C\d)", re.IGNORECASE)
_ROLO_LIDO = re.compile(r"^([A-Z])0*(\d+)$", re.IGNORECASE)


#: ⭐ Os campos que a claquete lida empresta ao TOPO da nota — onde a busca filtra e ordena.
_DO_TOPO = ("cena", "plano", "take")


def _valores_do_exemplo() -> tuple[str, ...]:
    """Os cena/plano/take que a INSTRUÇÃO põe na boca do modelo, lidos do próprio texto.

    ⛔ Lidos de `CLAQUETE`, nunca copiados para cá: dois literais iguais em dois lugares
    divergem calados, e a conferência passaria a procurar o exemplo de ontem — que é
    justamente o defeito que ela existe para pegar.
    """
    achados = [re.search(rf'"{campo}":\s*"([^"]+)"', CLAQUETE) for campo in _DO_TOPO]
    return tuple(m.group(1) for m in achados if m) if all(achados) else ()


#: Os nomes de campo do JSON — eles aparecem entre aspas na instrução e não são valores.
_NOMES_DE_CAMPO = frozenset(
    ("claquete", "legivel", "rolo", "cena", "plano", "take", "tomada", "serie", "marcas",
     "texto"))
#: ⭐ Um número de um ou dois dígitos é cena/plano/take plausível em QUALQUER material:
#: reprovar por ele sozinho reprovaria leitura boa. O que denuncia cópia é o literal
#: estranho — `X07`, `01-2`, `12A`, `como está`.
_NUMERO_PLAUSIVEL = re.compile(r"^\d{1,2}$")


def _literais_da_instrucao() -> frozenset[str]:
    """Todo valor entre aspas que a instrução contém — e que o modelo pode copiar.

    ⛔⛔ MEDIDO em 2026-09-23: trocar os valores do exemplo por `‹cena›` acabou com o eco
    de `31 · 8 · 5` e o modelo passou a devolver `rolo ["01-2"] · cena 01 · plano 2`, que é
    a FRASE SEGUINTE (`"01-2"/"12A" = cena 01 plano 2`) — escrita ali como explicação de
    notação, não como exemplo. ⇒ **Todo literal do prompt é material de cópia**, e a
    conferência precisa olhar a instrução inteira, não só o bloco de exemplo.
    """
    return frozenset(v for v in re.findall(r'"([^"]+)"', CLAQUETE)
                     if v not in _NOMES_DE_CAMPO and not _NUMERO_PLAUSIVEL.match(v))


def _ecoou_a_instrucao(q: dict[str, Any]) -> str:
    """⛔⛔ A resposta é o EXEMPLO da instrução de volta? O aviso, ou "".

    MEDIDO no cache real em 2026-09-23: **30 de 50 mídias com micro feita** devolveram o
    `31 · 8 · 5` do exemplo como se o tivessem lido — e em 8 notas (4 mídias) isso passou
    pela conferência do rolo, porque o modelo leu o rolo CERTO (`A002_…` → `A002`) e copiou
    só o resto. O banco já registrava que o exemplo não pode ser uma claquete do acervo
    (`ia-embarcada-nos-nles.md` §3c); o que falta é ele não poder virar FATO, venha de onde
    vier.

    ⚠️ Não apaga nada: a claquete fica com o número e o aviso. Uma claquete real que por
    azar seja igual ao exemplo perde os filtros, não a leitura — e o preço inverso (um
    chute plausível mandando na busca) já foi pago 30 vezes.
    """
    exemplo = _valores_do_exemplo()
    if exemplo and tuple(str(q.get(c) or "") for c in _DO_TOPO) == exemplo:
        return (f"cena/plano/take iguais ao EXEMPLO da instrução ({' · '.join(exemplo)}); "
                f"o modelo pode tê-lo copiado em vez de ler")
    # ⭐ E qualquer literal ESTRANHO da instrução devolvido como leitura — o `X07` do rolo
    #   (20 vezes no cache), o `01-2` da frase de notação, o `‹cena›` de um exemplo
    #   impreenchível. Número curto não entra: esse é valor plausível de material de verdade.
    # ⛔ `texto` fica FORA, e é medição: o exemplo traz `"texto": "como está"` e essa string
    #   voltou em toda leitura — **inclusive nas 4 certas**. Reprovar por ela derrubaria
    #   justamente as leituras boas. Esse campo se conserta no prompt, não na conferência.
    literais = _literais_da_instrucao()
    for campo in (*_DO_TOPO, "rolo"):
        bruto = q.get(campo)
        for valor in (bruto if isinstance(bruto, list) else [bruto]):
            texto = str(valor or "").strip()
            if texto and (texto in literais or "‹" in texto):
                return (f"{campo} veio com {texto!r}, que está ESCRITO na instrução; "
                        f"o modelo pode tê-lo copiado em vez de ler")
    return ""


#: ⛔ A confusão de OCR que reprovava leitura CERTA — MEDIDO em 2026-09-23: a claquete
#: escrita à mão diz `A01` (e o zero parece um O), o modelo devolveu `AO1`, o rolo "não
#: bateu" com `A001_…` e a leitura inteira caiu para `hipotese` — com cena, plano e tomada
#: lidos CERTOS (4 · 3 · 1, conferidos no quadro). A conferência existe para pegar chute,
#: não caligrafia.
_CONFUSAO_DE_OCR = str.maketrans({"O": "0", "o": "0", "I": "1", "l": "1", "|": "1"})


def _ocr(rolo: str) -> str:
    """O rolo lido com a confusão de OCR desfeita nos DÍGITOS — a letra da câmera fica."""
    texto = str(rolo or "").strip()
    return texto[:1] + texto[1:].translate(_CONFUSAO_DE_OCR)


def _ecoou_o_nome_do_arquivo(q: dict[str, Any], nomes: list[str]) -> str:
    """⛔⛔ O modelo devolve o NOME DO ARQUIVO como se fosse a claquete — e o nome é NOSSO:
    ele vai no cabeçalho do pedido ("6 quadros da mídia A_0001C001_260629_083016_h1DF4").

    MEDIDO em 2026-09-23, numa claquete filmada no ESCURO (só o timecode em LED aceso): o
    `texto` trouxe o TC certo (`08:30:08:12`) e os campos vieram
    `cena 260629 · plano 083016 · take h1DF4` — a data, a hora e o sufixo do arquivo,
    repartidos nos três. É o eco da instrução outra vez, com outra fonte.

    ⚠️ A comparação é por TOKEN inteiro, nunca por pedaço: a cena `4` de um take real está
    "dentro" de `03170345` como substring, e reprovar por isso derrubaria leitura boa.

    ⛔⛔ E o `rolo` fica de FORA, que é o oposto do que parece. Ele coincide com o nome do
    arquivo **por definição** — é isso que `_rolo_que_nao_bate` exige para aprovar. Medido
    ao rodar esta conferência no cache: ela reprovou `rolo A001` em `A001_0317…` (o rolo
    certo!) e `rolo A02` em `A_0002C016…_A02.mxf`, onde o `_A02` é o sufixo de TRILHA do
    OP-Atom. Quem denuncia a cópia do nome é cena/plano/take.
    """
    tokens = {p.lower() for n in nomes for p in re.split(r"[^0-9A-Za-z]+", str(n or ""))
              if len(p) >= 3}
    if not tokens:
        return ""
    for campo in _DO_TOPO:
        bruto = q.get(campo)
        for valor in (bruto if isinstance(bruto, list) else [bruto]):
            texto = str(valor or "").strip()
            if len(texto) >= 3 and texto.lower() in tokens:
                return (f"{campo} veio com {texto!r}, que é um pedaço do NOME DO ARQUIVO "
                        f"(ele vai no pedido); o modelo pode tê-lo copiado em vez de ler")
    return ""


def _rolo_que_nao_bate(q: dict[str, Any], nomes: list[str]) -> tuple[str, str]:
    """`(aviso, conferido)` — a leitura contra o rolo que o NOME do arquivo já diz.

    ⛔⛔ MEDIDO (qwen3-vl 8B, 2026-09-22, 4 takes com claquete): 3 lidos certo, e no
    quarto — a claquete pequena, segurada longe num plano aberto — o modelo CHUTOU
    "A02 · 1 · 1 · 1" (o rolo era o do exemplo da instrução) em vez de dizer ilegível. O
    arquivo se chamava `A009_…`.
    """
    if not q.get("rolo"):
        return "", ""
    do_nome = next((m for m in (_ROLO_NO_NOME.match(str(n or "")) for n in nomes) if m), None)
    if do_nome is None:
        return "", ""
    esperado = (do_nome.group(1).upper(), int(do_nome.group(2)))
    lidos = [m for m in (_ROLO_LIDO.match(_ocr(r)) for r in q["rolo"]) if m]
    if any((m.group(1).upper(), int(m.group(2))) == esperado for m in lidos):
        return "", "rolo bate com o nome do arquivo"
    return (f"o rolo lido ({', '.join(q['rolo'])}) não bate com o nome do arquivo "
            f"({do_nome.group(0).rstrip('_C')}); a leitura pode estar errada"), ""


def conferir_a_claquete(nota: dict[str, Any], nomes: list[str]) -> dict[str, Any]:
    """A claquete lida conferida por quem NÃO depende do modelo — e a única porta por onde
    cena/plano/take chegam ao topo da nota.

    Duas conferências, e cada uma pega o que a outra deixa passar: o rolo contra o nome do
    arquivo (o modelo chutou a claquete inteira) e o eco da instrução (ele leu o rolo certo
    e copiou o resto — 8 notas medidas). Reprovada, a leitura vira `hipotese` com o aviso —
    o número continua lá para o editor ver — e **não** empresta nada aos campos de topo.

    ⛔⛔ A promoção mora AQUI, e não em `_uma_nota`, porque a ordem inversa é o que encheu
    a busca de chute: a nota nascia com cena/plano/take de FATO e a conferência, rodando
    depois, escrevia a dúvida só dentro do objeto `claquete` — que nenhum filtro lê. Medido
    no cache em 2026-09-23: **44 notas** `hipotese`, as 44 com os três campos no topo.
    Caminho que esquecer de conferir agora perde a promoção, que é a falha segura.
    """
    q = nota.get("claquete")
    if not isinstance(q, dict) or not q.get("legivel"):
        return nota
    # ⭐ O rótulo sai do valor aqui também, e não só em `ler_claquete`: é o que deixa a
    #   ferramenta de limpeza consertar o `"CENA 1"` que já foi gravado no cache.
    for campo in _DO_TOPO:
        if isinstance(q.get(campo), str) and q[campo]:
            q[campo] = _sem_rotulo(q[campo])
    if q.get("confianca") == "hipotese":
        # ⛔⛔ O que JÁ foi reprovado continua reprovado, e isto não é zelo: a instrução
        #    muda (o exemplo `31 · 8 · 5` saiu dela em 2026-09-23), e com ela o critério.
        #    Sem esta trava, passar de novo por uma nota velha a APROVARIA — o eco de
        #    ontem não é eco hoje — e devolveria aos filtros o chute que a limpeza tirou.
        #    É a mesma armadilha do `consertar_quadros`: critério que muda com o código.
        for campo in _DO_TOPO:
            # ⚠️ Com `default`: campo que falta nos DOIS lados compara igual (None == None)
            #   e um `pop` sem ele levanta `KeyError` no meio da conferência.
            if campo in nota and nota[campo] == q.get(campo):
                nota.pop(campo, None)
        return nota
    aviso, conferido = _rolo_que_nao_bate(q, nomes)
    aviso = _ecoou_a_instrucao(q) or _ecoou_o_nome_do_arquivo(q, nomes) or aviso
    if aviso:
        q["confianca"] = "hipotese"
        q["aviso"] = aviso
        # ⛔ E desfaz a promoção de uma passada anterior — é o que deixa a limpeza do cache
        #   antigo usar esta mesma função, em vez de um critério à parte que envelhece.
        for campo in _DO_TOPO:
            # ⚠️ Com `default`: campo que falta nos DOIS lados compara igual (None == None)
            #   e um `pop` sem ele levanta `KeyError` no meio da conferência.
            if campo in nota and nota[campo] == q.get(campo):
                nota.pop(campo, None)
        return nota
    if conferido:
        q["conferido"] = conferido
    # ⭐ Sobreviveu: cena, plano e take valem nos filtros e na ordem da busca
    #   (`decupagem.formatar` já os lê), com a procedência dentro de `claquete`.
    for campo in _DO_TOPO:
        if q.get(campo):
            nota[campo] = q[campo]
    return nota


#: ⛔⛔ O modelo devolve o RÓTULO junto com o valor — MEDIDO em 2026-09-23, numa claquete
#: real e bem legível: `"cena": "CENA 1", "plano": "PLANO 1", "take": "TOMADA 1"`. Isso
#: passou a conferência (o rolo batia) e foi para os filtros, onde procurar cena `1` não
#: casa `CENA 1`. O rótulo está IMPRESSO na prancheta, embaixo de cada campo — ele está
#: lendo o que vê, e é aqui que se separa o valor do nome dele.
#: ⚠️ Em PORTUGUÊS e em INGLÊS: a claquete da *PRODUCAO-F* (medida em 2026-09-23) traz
#: `ROLL # · SCENE · SHOT · TAKE` impressos, e o `#` junto do rolo.
_ROTULO_NO_VALOR = re.compile(
    r"^(?:n[.º°]?\s*)?(?:rolo|roll|cena|scene|plano|shot|take|tomada|s[eé]rie|series)"
    r"[\s:.#\-]*", re.IGNORECASE)


def _sem_rotulo(valor: str) -> str:
    """`"CENA 1"` → `"1"`. Só tira o rótulo quando sobra alguma coisa."""
    limpo = _ROTULO_NO_VALOR.sub("", valor).strip()
    return limpo or valor


def _curto(valor: Any, maximo: int = 12) -> str:
    # ⚠️ O rótulo sai ANTES do corte: cortando primeiro, `"ROLL # A02"` vira `"ROLL # A"`
    #   nos 8 caracteres do rolo e depois `"A"` — o cartão perde o número da câmera.
    return _sem_rotulo(" ".join(str(valor or "").split()))[:maximo]


def ler_claquete(bruto: Any) -> dict[str, Any] | None:
    """O que o modelo leu na claquete → o que se grava. `None` = não havia claquete.

    ⭐ Pedido do editor (2026-09-22): *"ao identificar claquete, tentar ler o conteúdo e
    retornar rolo de câmera (pode ter mais de um), cena, plano, take e se é gravação em
    série. Se não der pra ler, um aviso de ilegível."*

    ⛔ Texto do modelo é entrada não confiável: cada campo é curto, a lista de rolos tem
    teto, e ilegível é um estado EXPLÍCITO (`legivel: False`) — nunca números chutados.
    ⚠️ Procedência na própria leitura: `fonte: claquete`, `confianca: inferido` (é leitura
    de IA sobre um quadro, e caligrafia de claquete engana).
    """
    if not isinstance(bruto, dict) or not bruto:
        return None
    rolos = bruto.get("rolo") or bruto.get("rolos") or []
    if isinstance(rolos, str):
        rolos = rolos.replace("/", ",").split(",")
    rolos = [_curto(r, 8).upper() for r in rolos if _curto(r)][:4]
    lida = {
        "rolo": rolos,
        "cena": _curto(bruto.get("cena")),
        "plano": _curto(bruto.get("plano")),
        "take": _curto(bruto.get("take") or bruto.get("tomada")),
        "serie": bool(bruto.get("serie")),
        # ⭐ Anotações a mais na claquete — MEDIDO no acervo: "PICKUP" escrito no campo do
        #   plano (A005_C009). Série é uma delas; as outras não têm campo, e não se perdem.
        "marcas": [_curto(m, 20).upper() for m in (bruto.get("marcas") or [])
                   if isinstance(m, str) and _curto(m)][:5],
        "texto": " ".join(str(bruto.get("texto") or "").split())[:200],
    }
    legivel = bruto.get("legivel")
    if legivel is False or not any(lida[c] for c in ("rolo", "cena", "plano", "take")):
        # Viu a claquete e não leu nada que preste: ILEGÍVEL, dito — e nada inventado.
        return {"legivel": False, "confianca": "inferido", "fonte": "claquete",
                **({"texto": lida["texto"]} if lida["texto"] else {})}
    return {"legivel": True, **{k: v for k, v in lida.items() if v not in ("", [], False)},
            "confianca": "inferido", "fonte": "claquete"}


def notas_da_resposta(
    dados: dict[str, Any], pedidas: list[str]
) -> tuple[dict[str, dict[str, Any]], list[str]]:
    """A resposta crua do modelo → `({chave: nota}, avisos)`.

    ⛔⛔ **Chave que ninguém pediu NÃO vira nota.** Ela gravaria decupagem em cima da mídia
    errada, e ninguém descobriria: a descrição seria plausível, e a busca passaria a
    apontar o plano errado para sempre.

    ⭐ Uma mídia só: aceita também a resposta "plana", sem a chave em volta — é o formato
    que o modelo devolve naturalmente quando só há uma, e recusá-la seria perder o turno
    inteiro por causa de uma casca.
    """
    alvos = set(pedidas)
    if len(pedidas) == 1 and "descricao" in dados:
        dados = {pedidas[0]: dados}

    notas: dict[str, dict[str, Any]] = {}
    avisos: list[str] = []
    for chave, cru in dados.items():
        if chave not in alvos:
            avisos.append(f"o modelo respondeu sobre {str(chave)[:16]}…, que não foi pedida")
            continue
        nota = _uma_nota(cru)
        if nota is None:
            avisos.append(f"resposta sem descrição para {str(chave)[:16]}…")
            continue
        avisos.extend(nota.pop("avisos", []))
        notas[chave] = nota

    if not notas:
        raise DecupagemFalhou("; ".join(avisos) or "nenhuma decupagem utilizável")

    faltaram = alvos - set(notas)
    if faltaram:
        avisos.append(f"{len(faltaram)} mídia(s) ficaram sem resposta neste turno")
    return notas, avisos


def _json_da_resposta(texto: str) -> dict[str, Any]:
    """O JSON que o modelo respondeu, tolerando cerca de código e prosa em volta.

    ⚠️ O prompt pede JSON puro e o modelo quase sempre obedece — mas "quase sempre" numa
    fila de trezentas mídias são dezenas de falhas. Aceitar ```json e texto em volta custa
    quatro linhas e recupera todas elas.
    """
    bruto = (texto or "").strip()
    cerca = re.search(r"```(?:json)?\s*(.+?)```", bruto, re.S)
    if cerca:
        bruto = cerca.group(1).strip()
    if not bruto.startswith("{"):
        abre = bruto.find("{")
        fim = bruto.rfind("}")
        if abre < 0 or fim < abre:
            raise DecupagemFalhou("o modelo não respondeu em JSON")
        bruto = bruto[abre:fim + 1]
    try:
        dados = json.loads(bruto)
    except json.JSONDecodeError as e:
        raise DecupagemFalhou(f"JSON inválido na resposta: {e}") from None
    if not isinstance(dados, dict) or not dados:
        raise DecupagemFalhou("a resposta não veio como objeto JSON")
    return dados


def _uso_do_result(evento: dict) -> dict[str, Any]:
    """Os tokens do turno, do evento `result` do CLI.

    ⭐ MEDIDO em `spikes/o_que_o_cli_conta.py`: `modelUsage[<modelo>]` traz as quatro
    contagens. **O cache conta como entrada** — ele não é cobrado igual, mas atravessa a
    janela igual, e é o que faz a conta bater com o que o editor vê na assinatura dele.
    """
    total = {"entrada": 0, "cache_lido": 0, "cache_escrito": 0, "saida": 0, "modelo": ""}
    for modelo, u in (evento.get("modelUsage") or {}).items():
        total["modelo"] = total["modelo"] or modelo
        total["entrada"] += u.get("inputTokens") or 0
        total["cache_lido"] += u.get("cacheReadInputTokens") or 0
        total["cache_escrito"] += u.get("cacheCreationInputTokens") or 0
        total["saida"] += u.get("outputTokens") or 0
    total["tokens"] = (total["entrada"] + total["cache_lido"]
                       + total["cache_escrito"] + total["saida"])
    # ⚠️ O custo em dólar vem do CLI e depende do plano; guardamos o que ele disser, sem
    #    recalcular — inventar preço é a forma mais fácil de mentir sobre dinheiro.
    if evento.get("total_cost_usd") is not None:
        total["custo_usd"] = evento["total_cost_usd"]
    return total


def decupar(
    itens: list[tuple[str, str]],
    url_do_mcp: str,
    quadros: int = QUADROS,
    modelo: str = "",
    timeout_s: float = 480.0,
) -> dict[str, Any]:
    """Um turno para VÁRIAS mídias. `itens` são pares `(chave, nome)`.

    Devolve `{"notas": {chave: nota}, "uso": {...}, "segundos": …}`. Cada nota já vem com
    os campos fechados normalizados — o que o modelo escrever fora do vocabulário é
    **descartado com aviso**, nunca gravado torto.

    ⭐⭐ Várias por turno porque **o custo é do turno**: ~40 mil tokens de piso contra ~2,5
    mil de conteúdo por mídia (medido em 2026-09-11). Ver `POR_TURNO`.

    ⚠️ E a resposta é conferida contra o que foi PEDIDO: chave que não estava na lista é
    descartada. Sem isso, um modelo que inventasse uma chave gravaria decupagem em cima da
    mídia errada — e ninguém descobriria, porque a descrição seria plausível.
    """
    if not itens:
        return {"notas": {}, "uso": {}, "segundos": 0.0}

    cli = achar_o_cli()
    lista = "\n".join(
        f"- {chave}" + (f'  (nome na bin: "{nome}")' if nome else "")
        for chave, nome in itens
    )
    pedido = (
        f"Decupe {'esta mídia' if len(itens) == 1 else f'estas {len(itens)} mídias'}:\n"
        f"{lista}\n\n"
        f"Para cada uma, chame ver_quadros_da_midia com a chave dela, quantos={quadros} "
        f"e claquete=true. "
        f"Depois responda UM objeto JSON com uma entrada por chave."
    )

    with tempfile.TemporaryDirectory() as tmp:
        config = Path(tmp) / "mcp.json"
        config.write_text(
            json.dumps({"mcpServers": {"ciclo": {"type": "http", "url": url_do_mcp}}}),
            encoding="utf-8",
        )
        comando = [
            cli, "-p", pedido,
            "--system-prompt", PERSONA,
            "--output-format", "stream-json",
            "--verbose",
            "--mcp-config", str(config),
            "--strict-mcp-config",
            "--restricted",
            # ⛔⛔ Sem ferramenta nativa: o `--restricted` deixa `Write`, `Edit`, `Read`…
            #    (medido, `spikes/o_que_o_restricted_deixa.py`). Ver `claude.py`.
            "--tools", "",
            # ⛔ UMA ferramenta, e ela só lê. Sem portão, sem escrita, sem surpresa: este
            #    turno acontece sem o editor por perto, e o que ele pode fazer na máquina
            #    dele é olhar seis JPEG.
            "--allowedTools", "mcp__ciclo__ver_quadros_da_midia",
        ]
        if modelo:
            comando += ["--model", modelo]

        comeco = time.monotonic()
        processo = subprocess.Popen(
            comando, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,     # sem isto o CLI espera 3 s por stdin
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            # ⚠️ Faltava o `env=` aqui: o MCP_TOOL_TIMEOUT de 10 min não chegava à fila de
            #    decupagem, que rodava com o padrão de fábrica do CLI.
            env=_ambiente_do_cli(),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )

        # ⛔ O stderr DRENADO numa thread, e o prazo num relógio que mata o processo — o mesmo
        #    cano de `sessao._drenar_stderr`. Com `stderr=PIPE` e ninguém lendo, o buffer
        #    enche e o CLI trava ao escrever; e o `wait(timeout)` depois do laço nunca
        #    disparava, porque o laço só sai no EOF.
        stderr: deque[str] = deque(maxlen=50)

        def moer() -> None:
            try:
                for trecho in processo.stderr:
                    stderr.append(trecho.rstrip())
            except Exception:
                pass

        dreno = threading.Thread(target=moer, name="stderr-decupador", daemon=True)
        dreno.start()
        estourou = threading.Event()

        def estourar() -> None:
            estourou.set()
            processo.kill()

        relogio = threading.Timer(timeout_s, estourar)
        relogio.daemon = True
        relogio.start()

        # ⚠️⚠️ DOIS textos, e juntá-los quebra tudo. O CLI manda a resposta nos blocos
        #    `assistant` E de novo no campo `result` do fim — concatenar os dois produz
        #    `{...}{...}`, e o parser morre com "Extra data" numa resposta perfeita.
        #    MEDIDO em 2026-09-11: 2 de 3 mídias falharam assim na primeira rodada.
        do_assistente: list[str] = []
        do_result = ""
        uso: dict[str, Any] = {}
        veio_o_result = False
        try:
            for linha in processo.stdout:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    evento = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if evento.get("type") == "assistant":
                    for bloco in evento.get("message", {}).get("content", []):
                        if bloco.get("type") == "text":
                            do_assistente.append(bloco.get("text") or "")
                elif evento.get("type") == "result":
                    veio_o_result = True
                    uso = _uso_do_result(evento)
                    if evento.get("result"):
                        do_result = str(evento["result"])
            processo.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            processo.kill()
            raise DecupagemFalhou("o modelo não respondeu no prazo") from None
        finally:
            relogio.cancel()
            if processo.poll() is None:
                processo.kill()
        if estourou.is_set():
            raise DecupagemFalhou("o modelo não respondeu no prazo")
        if not veio_o_result:
            # ⛔ MEDIDO no macOS (2026-09-14): com o CLI morrendo na partida (um `claude` velho
            #    que recusa `--restricted`), cada lote falhava como "não respondeu em JSON" —
            #    a causa certa estava no stderr, que ninguém lia.
            dreno.join(timeout=2)
            motivo = " | ".join(list(stderr)[-5:]) or f"saiu com código {processo.returncode}"
            raise DecupagemFalhou(f"o Claude encerrou sem responder: {motivo[-400:]}")

    # ⭐ Sem conta, o CLI responde "Not logged in · Please run /login" no lugar do modelo (medido 2026-11-07).
    if frase_do_erro(do_result or "\n".join(do_assistente)) == SEM_CONTA:
        raise SemConta(SEM_CONTA)
    # O `result` é a resposta final já consolidada; os blocos do assistente são o plano B
    # para quando ele vier vazio.
    dados = _json_da_resposta(do_result or "\n".join(do_assistente))

    notas, avisos = notas_da_resposta(dados, [chave for chave, _ in itens])
    return {
        "notas": notas,
        "avisos": avisos,
        "uso": uso,
        "segundos": round(time.monotonic() - comeco, 1),
    }
