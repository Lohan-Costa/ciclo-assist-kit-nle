"""O dicionário de intenção: o que o editor DIGITA → as palavras que o material USA.

⛔⛔ **MEDIDO em 2026-09-20, no acervo do editor.** Ele procurou `drone` e a busca devolveu
zero — com material de drone no projeto. A decupagem tinha escrito *"Vista aérea de uma
rodovia com múltiplas faixas e pontes…"*, e os clipes se chamam `DJI_0311`, `DJI_0313`. No
cache inteiro: **`drone` 0 ocorrências, `aérea` 4, `voo` 2**.

A descrição não está errada — *"vista aérea"* é o que se vê. O que está errado é exigir que
quem procura acerte a palavra que outro escolheu. ⇒ **`drone` é uma INTENÇÃO**, e o que a
satisfaz é um conjunto de palavras.

## As três regras que este módulo segue

⭐⭐ **A expansão é OU dentro de um termo, e E entre termos.** "drone praia" continua
querendo as duas coisas; o que muda é que "drone" passa a ser satisfeito por *aérea*, por
*DJI* ou por *sobrevoo*. Expandir para OU entre termos devolveria o acervo inteiro.

⛔⛔ **A expansão é DITA.** Ela muda o que a busca acha, e busca que se alarga calada é a
irmã do filtro calado: o editor lê "8 achados" e não sabe que dois vieram de uma palavra que
ele não escreveu. A resposta carrega `expansoes`, e a tela mostra.

⭐ **Só expande o que NÃO acha sozinho.** Se a palavra digitada já existe no material, ela
manda — o dicionário é rede, não tradutor. Assim um dia em que a decupagem passe a escrever
"drone" a busca fica mais precisa em vez de continuar igual.

⚠️ **Isto não é sinônimo de vocabulário.** `decupagem.SINONIMOS` normaliza um valor para o
termo canônico de um campo FECHADO (`primeiro plano` → `close`, e o campo passa a valer
`close`). Aqui nada é normalizado: o termo digitado ganha companhia na busca por TEXTO, e
os cinco campos fechados continuam com a régua deles.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

from .decupagem import sem_acento

log = logging.getLogger("cicloassist.midia.intencao")

#: O que o editor digita → o que o material provavelmente escreveu.
#:
#: ⭐ Ancorado no vocabulário REAL do acervo (medido em 2026-09-20: `mulher` 269, `homem`
#: 189, `cabelo` 93, `carro` 24, `cachorro` 20, `areia` 20, `árvores` 19…), e não numa lista
#: de sinônimos de dicionário. Mapeamento que nenhum material satisfaz é promessa vazia.
#:
#: ⚠️ **Inglês entra porque o ofício é bilíngue** — o editor pensa em `wide`, `close-up`,
#: `handheld`, `b-roll`, e nenhum desses sai da boca do modelo, que escreve em português.
INTENCOES: dict[str, tuple[str, ...]] = {
    # ── o caso que deu origem a este módulo ──────────────────────────────────
    "drone": ("aérea", "aéreo", "dji", "sobrevoo", "vista de cima", "de cima"),
    "aereo": ("aérea", "aéreo", "drone", "dji"),
    "aerial": ("aérea", "aéreo", "drone", "dji"),

    # ── enquadramento e câmera, em inglês e na gíria da ilha ────────────────
    "wide": ("geral", "plano geral", "aberto", "conjunto"),
    "closeup": ("close", "primeiro plano", "rosto"),
    "close up": ("close", "primeiro plano", "rosto"),
    "handheld": ("mão", "câmera na mão", "trêmula", "instável"),
    "steadicam": ("travelling", "mão", "suave"),
    "dolly": ("travelling",),
    "zoom in": ("zoom",),
    "pan": ("panorâmica", "pan", "gira"),
    "tilt": ("tilt", "inclina"),
    "estabelecimento": ("geral", "estabelecendo", "fachada", "exterior"),
    "establishing": ("geral", "estabelecendo", "fachada", "exterior"),

    # ── o que o editor procura quando procura um TIPO de plano ──────────────
    "b-roll": ("ambiente", "cobertura", "detalhe", "geral"),
    "broll": ("ambiente", "cobertura", "detalhe", "geral"),
    "cobertura": ("ambiente", "cobertura", "detalhe"),
    "passagem": ("corredor", "porta", "caminha", "atravessa", "entra"),
    "ambiente": ("ambiente", "vegetação", "paisagem", "exterior"),
    "paisagem": ("paisagem", "vegetação", "montanhas", "horizonte", "aérea"),

    # ── lugares, pelo que a descrição costuma dizer ─────────────────────────
    # ⛔ `mar` SAIU das duas: medido, ele sozinho cobre **36% do acervo** — casa
    #    "Pessoa U", "marido", "marcar", "Maria". Expansão que cobre um terço do
    #    material não estreita nada, só faz a busca parecer que funcionou.
    "praia": ("praia", "areia", "litoral", "costeira", "orla", "oceano"),
    "beach": ("praia", "areia", "litoral", "orla"),
    "cidade": ("cidade", "edifícios", "prédios", "rua", "avenida", "urbana"),
    "city": ("cidade", "edifícios", "prédios", "rua", "urbana"),
    "rua": ("rua", "avenida", "calçada", "rodovia", "cruzamento"),
    "estrada": ("rodovia", "estrada", "avenida", "pista"),
    "natureza": ("vegetação", "árvores", "mata", "verde", "paisagem"),
    "escritorio": ("escritório", "mesa", "computador", "sala"),
    "consultorio": ("consultório", "poltrona", "terapeuta"),
    "casa": ("casa", "sala", "sofá", "cômodo", "quarto", "cozinha"),
    "interiores": ("interior", "cômodo", "sala", "quarto"),

    # ── gente, pelo que o modelo escreve ────────────────────────────────────
    "pessoa": ("mulher", "homem", "pessoa"),
    "gente": ("mulher", "homem", "pessoa", "pessoas", "grupo"),
    "woman": ("mulher",),
    "man": ("homem",),
    "people": ("pessoas", "grupo", "mulher", "homem"),
    "crianca": ("criança", "menino", "menina"),
    "child": ("criança", "menino", "menina"),
    "multidao": ("multidão", "grupo", "pessoas", "movimento"),
    "entrevista": ("entrevista", "fala", "responde", "sentada", "sentado"),
    # ⚠️ Sem `fala`: numa transcrição, "falar/falando/falava" está em toda diária.
    "conversa": ("conversa", "conversam", "conversando", "diálogo", "papo"),

    # ── coisas que aparecem muito neste acervo ──────────────────────────────
    "carro": ("carro", "veículo", "automóvel", "carros"),
    "car": ("carro", "veículo", "automóvel"),
    "transito": ("trânsito", "carros", "rodovia", "avenida", "cruzamento"),
    "cachorro": ("cachorro", "cão", "animal"),
    "dog": ("cachorro", "cão"),
    "figurino": ("roupa", "camisa", "blusa", "terno", "gravata", "vestido"),
    "mascara": ("máscara",),
    "mask": ("máscara",),

    # ── luz e clima, que o editor nomeia diferente do modelo ────────────────
    "golden hour": ("entardecer", "pôr do sol", "luz quente", "dourada"),
    "por do sol": ("pôr do sol", "entardecer", "crepúsculo"),
    "sunset": ("pôr do sol", "entardecer"),
    "chuva": ("chuva", "molhado", "nublado", "cinza"),
    "sol": ("sol", "ensolarado", "luz natural", "claro"),
    "escuro": ("escuro", "escura", "penumbra", "noite", "baixa"),
}

#: ⭐⭐ Os termos EQUIVALENTES entre línguas — `termos.json`, ao lado deste arquivo.
#:
#: Pedido do editor (2026-09-22): ele procurou `claquete` e não achou nada, porque a
#: decupagem tinha escrito `clapperboard` (medido: **39 notas contra 2**). *"Devemos ter um
#: dicionário de termos para não limitar as opções… deixar em aberto para ir completando."*
#:
#: ⭐ Diferente de `INTENCOES` (mão única: `drone` → `aérea`), aqui o grupo vale nos DOIS
#: sentidos — `claquete` acha `clapperboard` e vice-versa —, e cada grupo tem um PREFERIDO,
#: que é a palavra que a decupagem passa a escrever (`motor/decupador.PERSONA`).
#: ⚠️ É DADO, não código: completar é acrescentar um grupo no JSON.
ARQUIVO_DE_TERMOS = Path(__file__).with_name("termos.json")


def grupos_de_termos() -> list[dict[str, Any]]:
    """Os grupos de `termos.json` — `[{preferido, tambem}]`. Arquivo ilegível é lista vazia:
    um dicionário quebrado não pode derrubar a busca."""
    try:
        dados = json.loads(ARQUIVO_DE_TERMOS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    saida = []
    for g in dados.get("grupos") or []:
        if not isinstance(g, dict) or not str(g.get("preferido") or "").strip():
            continue
        tambem = [str(t).strip() for t in g.get("tambem") or [] if str(t).strip()]
        # ⚠️ `evitar` ≠ `tambem`: "lapela" é português legítimo e a busca a aceita, mas
        #    não é algo que a decupagem deva deixar de escrever.
        evitar = [str(t).strip() for t in g.get("evitar") or [] if str(t).strip()]
        saida.append({"preferido": str(g["preferido"]).strip(), "tambem": tambem,
                      "evitar": evitar, "genero": str(g.get("genero") or "")})
    return saida


def _montar() -> dict[str, tuple[str, ...]]:
    mapa: dict[str, list[str]] = {sem_acento(k): list(v) for k, v in INTENCOES.items()}
    for g in grupos_de_termos():
        todos = [g["preferido"], *g["tambem"]]
        for termo in todos:
            outros = [t for t in todos if sem_acento(t) != sem_acento(termo)]
            atual = mapa.setdefault(sem_acento(termo), [])
            atual.extend(t for t in outros if t not in atual)
    return {k: tuple(v) for k, v in mapa.items()}


#: O mapa consultado: chave sem acento e em minúsculas.
_POR_TERMO: dict[str, tuple[str, ...]] = _montar()

#: ⭐ O dicionário é ABERTO — o editor pediu para ir completando —, e um arquivo que só é
#: lido na partida não é aberto: ele acrescentaria um grupo, procuraria, nada mudaria, e
#: nada na tela diria por quê. A assinatura do arquivo (mtime + tamanho) decide, como a das
#: bins decide o índice de recortes; relógio erra nos dois sentidos.
#:
#: ⚠️⚠️ **Mas conferir a cada consulta é caro:** `equivalentes` é chamada uma vez por
#: (fala × termo) — dezenas de milhares de vezes numa busca —, e um `stat` por chamada
#: somaria ~0,1 s numa busca que leva 0,3 s. Por isso a conferência tem um piso de tempo:
#: no pior caso o grupo novo entra dois segundos depois de gravado.
RECONFERIR_S = 2.0
_assinatura: tuple = ()
_conferido_em: float = 0.0
_trava_do_mapa = threading.Lock()


def _atual() -> dict[str, tuple[str, ...]]:
    global _POR_TERMO, _assinatura, _conferido_em
    agora = time.monotonic()
    if agora - _conferido_em < RECONFERIR_S:
        return _POR_TERMO
    with _trava_do_mapa:
        _conferido_em = agora
        try:
            st = ARQUIVO_DE_TERMOS.stat()
            marca = (st.st_mtime_ns, st.st_size)
        except OSError:
            # Sumiu ou está ilegível: fica o que já havia. Um dicionário que some não pode
            # apagar a busca — ela volta a ser exata, que é o comportamento sem ele.
            return _POR_TERMO
        if marca != _assinatura:
            if _assinatura:
                log.info("termos.json mudou; relendo o dicionário")
            _assinatura = marca
            _POR_TERMO = _montar()
        return _POR_TERMO


def equivalentes(termo: str) -> tuple[str, ...]:
    """As palavras que satisfazem esta intenção, **sem** o termo digitado.

    `()` quando o termo não é uma intenção conhecida — que é o caso da esmagadora maioria
    e tem de ser barato.
    """
    return _atual().get(sem_acento(str(termo or "").strip()), ())


def alternativas(termo: str) -> tuple[str, ...]:
    """O termo digitado **mais** os equivalentes — o conjunto que a busca aceita por OU.

    ⭐ O digitado vem primeiro de propósito: quem tiver a palavra exata casa por ela, e o
    trecho mostrado na tela destaca a palavra que o editor escreveu, não a que o dicionário
    acrescentou.
    """
    t = str(termo or "").strip()
    if not t:
        return ()
    return (t, *equivalentes(t))


def expansoes_de(termos: list[str]) -> dict[str, list[str]]:
    """O que foi acrescentado a cada termo, para a RESPOSTA dizer.

    ⛔⛔ Busca que se alarga calada é a irmã do filtro calado: o editor lê "8 achados" e não
    sabe que seis vieram de uma palavra que ele não escreveu — e, quando a expansão erra
    (um dia vai errar), ele não tem como perceber nem como contornar.
    """
    saida: dict[str, list[str]] = {}
    for t in termos:
        extras = equivalentes(t)
        if extras:
            saida[t] = list(extras)
    return saida
