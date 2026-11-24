"""A decupagem: o vocabulário do que o modelo VÊ, e a busca sobre o que ele já escreveu.

O produto tem duas camadas visuais, e elas respondem perguntas diferentes:

| camada | responde | onde |
|---|---|---|
| **vetor** (MobileNetV2) | *"parecido com este quadro"* | `midia/vetores.py` |
| **decupagem** (o Claude olhando) | *"onde tem close noturno de luz quente?"* | aqui |

⭐ **Não há modelo de visão neste produto: o Claude é o modelo de visão.** A decupagem é o
que ele escreve depois de olhar os quadros, e é muito mais rica que qualquer classificador
pequeno — enquadramento, figurino, cenário, luz, câmera, o que a pessoa está fazendo, e até
a função do plano na cena ("cobertura de Personagem F na conversa com Eduardo").

## ⛔ Por que campos fechados, se a prosa já diz tudo

Porque **prosa não filtra**. Numa sessão o modelo escreve `close`, noutra `plano fechado`,
noutra `primeiro plano` — as três estão certas, e as três quebram *"me mostre todos os
closes"*. Os campos abaixo são poucos, fechados, e existem só onde a resposta é objetiva:
o que é medida do plano, não julgamento.

⚠️ **O resto continua prosa livre**, de propósito. Emoção, intenção, o que o take tem de
melhor — isso não cabe em enum, e forçar caberia produziria rótulo pior que a frase.

⚠️⚠️ E a procedência não muda: o que sai daqui é `confianca: inferido`, `fonte: visual`.
É leitura de IA sobre quadros, não anotação de set — e "Personagem F" vem do roteiro ou da
claquete, nunca do rosto. **Não há reconhecimento facial aqui.**
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path
from typing import Any

#: ⭐ O tamanho do plano. Lista curta de propósito: é a que um assistente de edição usa na
#: decupagem, e cada termo a mais é um termo que o modelo escolhe errado.
ENQUADRAMENTOS = ("geral", "conjunto", "médio", "americano", "close", "detalhe")

#: A altura da câmera em relação ao olhar.
ANGULOS = ("normal", "plongée", "contra-plongée")

#: O que a câmera FAZ. ⚠️ "parada" é resposta, não ausência de resposta.
CAMERAS = ("parada", "pan", "tilt", "travelling", "mão", "zoom")

LOCAIS = ("interior", "exterior")
MOMENTOS = ("dia", "noite")

#: ⭐ O que o modelo escreve naturalmente → o termo da lista. Sem isto, cada anotação
#: gastaria um turno do editor levando uma recusa por sinônimo — e todos estes são o mesmo
#: plano com outro nome na boca de quem monta.
SINONIMOS = {
    "plano geral": "geral", "pg": "geral", "wide": "geral", "plano aberto": "geral",
    "aberto": "geral",
    "plano de conjunto": "conjunto", "conjunto médio": "conjunto",
    "plano médio": "médio", "meio": "médio", "médio close": "médio",
    "plano americano": "americano",
    "primeiro plano": "close", "pp": "close", "plano fechado": "close",
    "fechado": "close", "closeup": "close", "close-up": "close", "cu": "close",
    "super close": "detalhe", "big close": "detalhe", "primeiríssimo plano": "detalhe",
    "insert": "detalhe", "detalhe de mão": "detalhe",
    "plongee": "plongée", "alto": "plongée", "de cima": "plongée",
    "contra plongée": "contra-plongée", "contra-plongee": "contra-plongée",
    "contraplongée": "contra-plongée", "baixo": "contra-plongée", "de baixo": "contra-plongée",
    "fixa": "parada", "estática": "parada", "tripé": "parada", "sem movimento": "parada",
    "panorâmica": "pan", "travelin": "travelling", "dolly": "travelling",
    "câmera na mão": "mão", "camera na mao": "mão", "handheld": "mão", "steadicam": "mão",
    "int": "interior", "dentro": "interior", "interna": "interior",
    "ext": "exterior", "fora": "exterior", "externa": "exterior",
    "diurno": "dia", "noturno": "noite", "de noite": "noite", "de dia": "dia",
}


#: O mesmo mapa, com as chaves sem acento — é assim que ele é consultado.
_SINONIMOS_SEM_ACENTO: dict[str, str] = {}


class ValorForaDoVocabulario(ValueError):
    """O termo não está na lista e não é sinônimo conhecido de nenhum."""


def sem_acento(texto: str) -> str:
    """Para comparar e para buscar. ⚠️ Quem digita "consultorio" tem de achar
    "consultório" — e quem escreve "plongee" tem de cair em "plongée"."""
    return "".join(
        c for c in unicodedata.normalize("NFKD", texto.lower())
        if not unicodedata.combining(c)
    )


def normalizar(campo: str, valor: str, lista: tuple[str, ...]) -> str:
    """O valor que o modelo escreveu → o termo da lista. Vazio continua vazio.

    ⭐ Aceita sinônimo e ignora acento, mas **não inventa**: o que não casa levanta, com a
    lista inteira na mensagem. Um campo fechado que aceita qualquer coisa não filtra nada,
    e o editor descobriria isso só quando a busca não achasse o que ele sabe que existe.
    """
    bruto = (valor or "").strip()
    if not bruto:
        return ""

    alvo = sem_acento(bruto)
    por_termo = {sem_acento(t): t for t in lista}
    if alvo in por_termo:
        return por_termo[alvo]

    # ⚠️⚠️ O dicionário é consultado SEM ACENTO dos dois lados. A primeira versão
    #    comparava a chave crua com o texto já normalizado, e todo sinônimo acentuado —
    #    "tripé", "panorâmica", "contra plongée" — simplesmente nunca casava. O teste
    #    pegou; em produção teria virado "não é um valor que eu use" para a palavra que
    #    está escrita na própria lista de sinônimos.
    sinonimo = _SINONIMOS_SEM_ACENTO.get(alvo)
    if sinonimo and sinonimo in lista:
        return sinonimo

    raise ValorForaDoVocabulario(
        f"{campo}={bruto!r} não é um valor que eu use. Escolha um destes: "
        f"{', '.join(lista)}."
    )


_SINONIMOS_SEM_ACENTO.update({sem_acento(k): v for k, v in SINONIMOS.items()})


#: Os campos fechados de uma nota, e a lista de cada um.
CAMPOS = {
    "enquadramento": ENQUADRAMENTOS,
    "angulo": ANGULOS,
    "camera": CAMERAS,
    "local": LOCAIS,
    "momento": MOMENTOS,
}


def normalizar_campos(dados: dict[str, Any]) -> dict[str, str]:
    """Todos os campos fechados de uma vez. Levanta no primeiro que não casar."""
    return {
        campo: normalizar(campo, str(dados.get(campo) or ""), lista)
        for campo, lista in CAMPOS.items()
        if dados.get(campo)
    }


# ── a busca ──────────────────────────────────────────────────────────────────


def texto_da_nota(nota: dict[str, Any]) -> str:
    """Tudo que é procurável numa nota, num texto só e sem acento."""
    pedacos = [
        str(nota.get("trecho") or ""),
        str(nota.get("descricao") or ""),
        " ".join(str(e) for e in (nota.get("etiquetas") or [])),
        " ".join(str(nota.get(c) or "") for c in CAMPOS),
        str(nota.get("cena") or ""), str(nota.get("plano") or ""),
    ]
    return sem_acento(" ".join(pedacos))


#: ⚠️ As regex de termo ficam guardadas: `casa_termo` é chamada uma vez por fala por termo
#: (numa busca real, dezenas de milhares de vezes), e compilar a cada chamada é o gasto.
_REGEX_DE_TERMO: dict[str, "re.Pattern[str]"] = {}


def casa_termo(texto_sem_acento: str, termo: str) -> bool:
    """Este termo aparece no texto — no COMEÇO de uma palavra, nunca no meio.

    ⛔⛔ **MEDIDO em 2026-09-20, e o defeito estava aqui desde sempre.** A busca era
    `termo in texto`, substring puro. Com `cão` sem acento vira `cao`, que casa **toda
    palavra terminada em -ção**: `ação`, `alimentação`, `apresentação`, `alteração`. Uma
    busca por "cachorro" (que o dicionário de intenção expande para `cão`) devolveu **200
    mídias** de um acervo de 332. `sol` casava `absolutamente` e `resolve`; `mar` casava
    `amar`, `arrumar`, `câmara`.

    ⭐ **Começo de palavra, e não palavra inteira**, porque o português flexiona: `carro`
    tem de achar `carros`, `aérea` tem de achar `aéreas`, `conversa` tem de achar
    `conversam`. É a régua que erra menos nas duas direções.

    ⚠️ Vale para o texto LIVRE. Os cinco campos fechados continuam comparados por
    igualdade — lá o vocabulário é conhecido e não há o que flexionar.
    """
    alvo = sem_acento(str(termo or "").strip())
    if not alvo:
        return False
    padrao = _REGEX_DE_TERMO.get(alvo)
    if padrao is None:
        padrao = _REGEX_DE_TERMO[alvo] = re.compile(r"\b" + re.escape(alvo))
    return bool(padrao.search(texto_sem_acento))


def casa(nota: dict[str, Any], termos: list[str], campos: dict[str, str]) -> bool:
    """A nota atende a TODOS os termos e a TODOS os campos pedidos?

    ⭐ **E, não OU.** Quem procura "close noite consultório" quer as três coisas juntas;
    devolver o que tem qualquer uma delas entregaria o acervo inteiro e faria o editor
    parar de confiar na busca.

    ⭐⭐ **Nota SEM o campo cai para o texto.** Os campos fechados nasceram em 2026-09-11,
    e toda decupagem escrita antes deles diz "Close de Personagem F" na prosa e não tem
    `enquadramento`. Um filtro que exigisse o campo devolveria ZERO no dia em que nasceu —
    com o material descrito bem ali. Quem TEM o campo é comparado por ele; quem não tem é
    comparado pelo que escreveu.
    """
    texto = texto_da_nota(nota)

    for campo, valor in campos.items():
        if not valor:
            continue
        gravado = str(nota.get(campo) or "").strip()
        if gravado:
            if gravado.lower() != valor.lower():
                return False
        elif not casa_termo(texto, valor):
            return False

    if not termos:
        return True
    return all(casa_termo(texto, t) for t in termos if t.strip())


def formatar(nota: dict[str, Any], midia, termos: list[str]) -> dict[str, Any]:
    """Uma nota que casou, na linha que a resposta entrega.

    ⭐ Mora aqui, e não dentro de `procurar`, porque a busca unificada (`midia/busca.py`)
    entrega a MESMA linha — duas formatações da mesma coisa divergiriam caladas, e a tela
    lê as duas pelos mesmos nomes de campo.
    """
    return {
        # ⚠️ O `trecho` de uma nota da MICRO é uma chave interna ("X.mp4 · trecho 412"),
        #   não um nome que o editor reconheça: não vira título do cartão.
        "take": "" if nota.get("escopo") == "trecho" else (nota.get("trecho") or ""),
        **({"escopo": "trecho", "inicio_s": nota.get("inicio_s"), "fim_s": nota.get("fim_s")}
           if nota.get("escopo") == "trecho" else {}),
        "midia": midia.nome or midia.chave[:12],
        "chave": midia.chave,
        "cena": nota.get("cena") or "",
        "plano": nota.get("plano") or "",
        "take_numero": nota.get("take") or "",
        "inicio_frames": nota.get("inicio_frames"),
        "duracao_frames": nota.get("duracao_frames"),
        "trecho_da_descricao": trecho_em_volta(nota, termos),
        "etiquetas": list(nota.get("etiquetas") or []),
        # ⭐ A leitura da claquete, com a procedência dentro (fonte `claquete`).
        **({"claquete": nota["claquete"]} if isinstance(nota.get("claquete"), dict) else {}),
        **{c: nota.get(c) or "" for c in CAMPOS if nota.get(c)},
        # Procedência em todo item: isto é leitura de IA sobre quadros.
        "confianca": nota.get("confianca") or "inferido",
        "fonte": nota.get("fonte") or "visual",
    }


#: ⭐⭐ Quantas notas da MESMA mídia entram na resposta. Uma peça montada decupada em
#: trechos tem uma nota por plano — 600 numa peça de meia hora —, e sem teto ela preencheria
#: sozinha a lista inteira, empurrando para fora justamente a resposta à pergunta *"onde
#: MAIS?"*. É a mesma régua que `planos_parecidos` já usa (até 3 planos da mesma peça).
#: ⛔ E o que ficou de fora é CONTADO, nunca cortado calado.
NOTAS_POR_MIDIA = 3


def procurar(
    termos: list[str] | None = None,
    campos: dict[str, str] | None = None,
    raiz: Path | None = None,
    limite: int = 20,
    chaves: "frozenset[str] | set[str] | None" = None,
    por_midia: int = NOTAS_POR_MIDIA,
    contador: dict[str, int] | None = None,
) -> list[dict[str, Any]]:
    """Onde, em TODO o material já decupado, existe isto.

    ⭐ É a peça que faltava para a decupagem virar busca. `ler_o_que_ja_sabemos` responde
    sobre **um** take que alguém já sabe qual é; esta responde *"onde tem…?"* sobre o
    acervo inteiro, sem Media Composer e sem modelo — é leitura de disco.

    ⚠️ E ela só enxerga o que JÁ foi decupado. Material que ninguém olhou não está aqui,
    e a resposta diz isso em vez de deixar parecer que o acervo foi varrido.

    `chaves` estreita a busca a esses masters — ⭐ é por onde entra o escopo do projeto
    aberto (`avid/escopo.py`). `None` quer dizer **sem filtro**, nunca "nenhum": o cache é
    global de propósito, e quem decide o recorte é quem chama.
    """
    from . import cache as _cache

    termos = [t for t in (termos or []) if t and t.strip()]
    campos = {k: v for k, v in (campos or {}).items() if v}

    achados: list[dict[str, Any]] = []
    sobraram = 0
    for midia in _cache.todas(raiz):
        if chaves is not None and midia.chave not in chaves:
            continue
        # ⚠️ Em ordem de tempo dentro da mídia (`anotar` já as guarda assim): cortando no
        #   teto, o que fica é o começo do material, e não uma escolha ao acaso.
        casaram = [n for n in midia.ler_notas() if casa(n, termos, campos)]
        if por_midia and len(casaram) > por_midia:
            sobraram += len(casaram) - por_midia
            casaram = casaram[:por_midia]
        achados.extend(formatar(n, midia, termos) for n in casaram)

    # Cena e plano na ordem em que o editor pensa a lista. ⚠️ A posição desempata: sem
    # ela, as notas de TRECHO (que não têm cena nem plano) saíam em ordem arbitrária.
    achados.sort(key=lambda a: (str(a["cena"]), str(a["plano"]), str(a["take"]),
                                str(a["midia"]), a.get("inicio_frames") or 0))
    if contador is not None:
        contador["por_midia"] = sobraram
        contador["alem_do_limite"] = max(0, len(achados) - limite)
    return achados[:limite]


def quantas_decupadas(raiz: Path | None = None,
                      chaves: "frozenset[str] | set[str] | None" = None) -> tuple[int, int]:
    """`(mídias com nota, mídias no cache)` — o tamanho do que a busca alcança.

    ⭐ Vai junto de toda resposta de busca. Sem isto, "não achei" se confunde com "não
    existe", e a diferença é o produto inteiro: uma coisa é o material não ter o que você
    procura, outra é ninguém ter olhado para ele ainda.
    """
    from . import cache as _cache

    com = total = 0
    for midia in _cache.todas(raiz):
        # ⚠️ O tamanho tem de ser o do MESMO recorte que a busca varreu: dizer "3 de 358"
        #   com a busca cobrindo 40 seria um número que desmente o outro.
        if chaves is not None and midia.chave not in chaves:
            continue
        total += 1
        if midia.arquivo("notas.json").is_file():
            com += 1
    return com, total


def trecho_em_volta(nota: dict[str, Any], termos: list[str], janela: int = 90) -> str:
    """Um pedaço da descrição em volta do primeiro termo achado.

    ⚠️ Devolver a descrição inteira de cada resultado encheria a resposta do modelo com
    mil palavras que ele não pediu — e a descrição de um take completo tem parágrafos.
    """
    descricao = str(nota.get("descricao") or "")
    if not descricao:
        return ""
    plano = sem_acento(descricao)
    for termo in termos:
        onde = plano.find(sem_acento(termo))
        if onde >= 0:
            comeco = max(0, onde - janela // 3)
            pedaco = descricao[comeco:comeco + janela].strip()
            return ("…" if comeco else "") + pedaco + ("…" if comeco + janela < len(descricao) else "")
    return descricao[:janela] + ("…" if len(descricao) > janela else "")
