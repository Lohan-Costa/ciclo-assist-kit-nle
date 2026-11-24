"""Decupar no servidor de percepção — o Ollama do Mac mini na rede.

⛔⛔ **Nunca neste notebook.** Telas azuis repetidas rodando modelo local ao lado do Media
Composer — a última em 2026-09-13, com o `gemma3:4b` carregando. Por isso não há endereço
padrão e o loopback é RECUSADO: quem esquecer de configurar recebe "decupa pelo Claude",
não uma tela azul. Spec: `docs/spec/2026-09-13-servidor-de-percepcao-mac.md`.

## ⭐⭐ O Mac é um BACKEND HTTP, não um servidor MCP (spec §3)

O Claude não sabe que o Mac existe. Quem fala com ele é o serviço, numa direção só
(notebook → Mac), com os quadros no corpo do pedido — o Mac não guarda nada do cliente e
nunca monta a mídia do Avid. E o que volta passa pela MESMA validação da decupagem pelo
Claude (`decupador.notas_da_resposta`): vocabulário fechado, chave que ninguém pediu não
vira nota.

## Por que a decupagem é a primeira coisa a ir

É o único trabalho do produto que gasta a assinatura do editor sem ele pedir: 165 mídias
são **2,8 milhões de tokens** no mesmo balde de 5 h da montagem. ⭐ **M1 MEDIDA em
2026-09-13** (7 mídias / 29 campos): `qwen3-vl:8b-instruct` 90%, zero inventados, ~62 s
por mídia.
"""

from __future__ import annotations

import base64
import ipaddress
import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from fractions import Fraction
from typing import Any

from . import decupador as _dec

log = logging.getLogger("cicloassist.motor.percepcao")

#: ⭐ O vencedor da M1 (90%, visão E tools). ⚠️ A tag é CONTRATO com o Mac (spec §9):
#: trocar lá sem trocar aqui dá "o Ollama não tem …".
MODELO = "qwen3-vl:8b-instruct"

#: ⛔⛔ MEDIDO: o contexto PADRÃO do Ollama é 4096 e seis quadros são 6.229 tokens — o
#: pedido volta 400 com `exceed_context_size_error`.
CONTEXTO = 12288

#: ⛔⛔ E o que PASSA do contexto o Ollama corta **calado** (CLAUDE.md, o M2): o pedido não
#: falha — o modelo é que vê menos do que foi mandado, e a tela continua dizendo o número
#: cheio. Com a densidade da aba (até 24 quadros por mídia), 12.288 não serve: seis quadros
#: já são ~6,2 mil tokens.
#:
#: ⇒ O contexto ACOMPANHA o tamanho do pedido, até o teto que aquele Mac comprovadamente
#: carrega — 40.960 é o `num_ctx` do chat pelo Ollama na mesma máquina (medido em
#: 2026-09-16). E o que não couber nele é CORTADO AQUI, com o número real voltando na
#: resposta: cortar aqui é uma decisão que se conta; cortar lá dentro, ninguém vê.
#:
#: ⚠️ `TOKENS_POR_QUADRO` sai da medição acima (6.229 ÷ 6, arredondado). O quadro da
#: CABEÇA é de 1568 px — ~4× a área, e **NÃO MEDIDO**: a folga é generosa de propósito.
CONTEXTO_MAXIMO = 40960
TOKENS_POR_QUADRO = 1040
TOKENS_POR_QUADRO_DA_CABECA = 4200
#: Prompt de sistema, cabeçalho e a resposta.
TOKENS_DE_SOBRA = 2048
#: ⚠️ Folga sobre a conta: os números acima são estimativa, e estourar é corte calado.
FOLGA = 1.2


def contexto_para(quadros: int, da_cabeca: int = 0) -> int:
    """O `num_ctx` que este pedido precisa — nunca menos que `CONTEXTO`, nunca mais que o
    que o Mac carrega."""
    preciso = (TOKENS_DE_SOBRA + quadros * TOKENS_POR_QUADRO
               + da_cabeca * TOKENS_POR_QUADRO_DA_CABECA) * FOLGA
    return int(max(CONTEXTO, min(CONTEXTO_MAXIMO, preciso)))


def quadros_que_cabem(da_cabeca: int = 0) -> int:
    """Quantos quadros normais cabem no maior contexto que o Mac carrega."""
    espaco = (CONTEXTO_MAXIMO / FOLGA) - TOKENS_DE_SOBRA \
        - da_cabeca * TOKENS_POR_QUADRO_DA_CABECA
    return max(1, int(espaco // TOKENS_POR_QUADRO))

#: Medido na M1: mediana de 62 s por mídia com o modelo quente; a primeira, fria, 151 s.
#: ⚠️ MEDIDO de novo em 2026-09-22, com os 2 quadros da CABEÇA a 1568 px para ler a
#: claquete (8 imagens): **92–97 s por mídia**, quente, em 8 pedidos. É o preço da leitura.
SEGUNDOS_POR_MIDIA = 95
PRAZO_S = 300.0

#: ⚠️ Quantas mídias seguidas sem RESPOSTA do Mac antes de desistir da fila. Mac dormindo
#: ou fora da rede não é "esta mídia falhou": sem isto, 165 mídias × 300 s de prazo seriam
#: catorze horas de fila falhando em silêncio enquanto o editor dorme.
FALHAS_SEGUIDAS = 3


class MacIndisponivel(RuntimeError):
    """O servidor de percepção não está configurado, não responde ou não serve."""


def _host_aceito(host: str) -> bool:
    """⛔ Faixa privada ou `.local`, e NUNCA este notebook (spec §6, ADR 0005).

    O endereço vem do `config.json`, que a página pode gravar: aceitar qualquer host seria
    a página escolhendo para onde o serviço faz requisição — com quadros do cliente dentro.
    """
    host = host.strip("[]").lower()
    if not host or host == "localhost":
        return False
    if host.endswith(".local"):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_private and not ip.is_loopback and not ip.is_unspecified


def validar(url: str) -> str:
    """A URL normalizada (`http://ip:porta`), ou `ValueError` dizendo o porquê."""
    url = (url or "").strip().rstrip("/")
    if not url:
        raise ValueError("endereço vazio")
    if "//" not in url:
        url = "http://" + url
    partes = urllib.parse.urlsplit(url)
    if partes.scheme not in ("http", "https"):
        raise ValueError("o endereço do Mac começa com http://")
    host = partes.hostname or ""
    if host in ("localhost", "::1") or host.startswith("127.") or host == "0.0.0.0":
        raise ValueError("recusado: este endereço é o próprio notebook. O servidor é o Mac.")
    if not _host_aceito(host):
        raise ValueError("só endereço da rede local (192.168.x.y, 10.x, 172.16–31.x ou "
                         "nome .local)")
    try:
        porta = partes.port or 11434
    except ValueError:
        raise ValueError("a porta do endereço do Mac não é um número") from None
    # ⚠️ IPv6 precisa de colchetes na URL; sem eles "fd00::5:11434" vira outro endereço.
    return f"{partes.scheme}://{f'[{host}]' if ':' in host else host}:{porta}"


def endereco() -> str:
    """Onde está o Mac, ou `""` quando a decupagem deve continuar pelo Claude.

    Precedência igual à do cache: `CICLOASSIST_OLLAMA` → `config.json` (`ollama`).
    ⚠️ Endereço inválido vira `""` com aviso no log, nunca exceção: config ruim não pode
    impedir a aba de abrir.
    """
    from ..servico import config as _config
    bruto = os.environ.get("CICLOASSIST_OLLAMA") or _config.ler().get("ollama") or ""
    if not bruto:
        return ""
    try:
        return validar(str(bruto))
    except ValueError as e:
        log.warning("endereço do Mac ignorado (%s): %s", bruto, e)
        return ""


def pedir(url: str, caminho: str, corpo: dict | None = None,
          timeout: float = PRAZO_S) -> dict:
    """POST/GET no Ollama com a stdlib. ⚠️ Sem framework — regra da casa."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    req = urllib.request.Request(
        url.rstrip("/") + caminho, data=dados,
        headers={"Content-Type": "application/json"},
        method="POST" if dados else "GET",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        bruto = r.read()
    try:
        return json.loads(bruto.decode("utf-8"))
    except ValueError:
        # ⛔ Revisão de 2026-09-13: um `JSONDecodeError` aqui não era capturado por ninguém e
        #    derrubava a fila inteira. Resposta que não é JSON é outra coisa respondendo no
        #    lugar do Ollama (proxy, página de roteador): é o Mac indisponível, e conta para
        #    as falhas seguidas.
        raise MacIndisponivel(f"quem respondeu em {url} não é o Ollama") from None


def responde(url: str, timeout: float = 3.0) -> bool:
    """O Ollama está no ar AGORA? Uma batida curta, sem julgar o modelo.

    ⛔⛔ MEDIDO em campo (2026-09-17): o Ollama do Mac caiu no meio de uma conversa — a
    máquina respondendo ping, a porta 11434 muda. Sem esta batida, o turno inteiro é gasto
    para descobrir isso: o CLI repete `Connection error` e fica pendurado.
    """
    if not url:
        return False
    try:
        pedir(url, "/api/tags", timeout=timeout)
        return True
    except (urllib.error.URLError, OSError, MacIndisponivel):
        return False


def conferir(url: str, modelo: str = MODELO) -> list[str]:
    """Confere que o Mac responde e que o modelo VÊ. Devolve as capacidades.

    ⛔⛔ Modelo sem `vision` recebendo seis JPEG é a suposição mais cara daqui: aceitaria
    calado e escreveria uma decupagem plausível e inventada (spec §5.3). Conferir custa um
    pedido; descobrir pela busca apontando o plano errado custa o acervo.
    """
    try:
        info = pedir(url, "/api/show", {"model": modelo}, timeout=30)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise MacIndisponivel(
                f"o Ollama do Mac não tem {modelo!r} (ollama pull {modelo})") from None
        raise MacIndisponivel(f"o Mac respondeu HTTP {e.code}") from None
    except (urllib.error.URLError, OSError) as e:
        raise MacIndisponivel(
            f"o Mac não respondeu em {url} ({e}). Ligado? Ollama no ar? Mesma rede?"
        ) from None
    capacidades = list(info.get("capabilities") or [])
    if "vision" not in capacidades:
        raise MacIndisponivel(f"{modelo} não vê imagem (capacidades: {capacidades})")
    return capacidades


def contexto_carregado(url: str, modelo: str) -> int:
    """O `context_length` do modelo como o Ollama o carregou (`/api/ps`), ou 0.

    0 = não carregado, ou o Mac não respondeu: quem pergunta é a barra de contexto, e
    barra sem denominador é honesta; barra que derruba o turno, não.
    """
    try:
        carregados = pedir(url, "/api/ps", timeout=5).get("models") or []
    except (MacIndisponivel, urllib.error.URLError, OSError, ValueError):
        return 0
    for m in carregados:
        if modelo in (m.get("name"), m.get("model")):
            return int(m.get("context_length") or 0)
    return 0


def persona_plana() -> str:
    """A `PERSONA` do decupador, com o envelope por chave trocado por resposta PLANA.

    ⭐⭐ Correção de TRANSPORTE, não de tarefa. O envelope `{"<chave>": {...}}` existe porque
    o `claude -p` tem piso de ~40 mil tokens e vale juntar três mídias por turno. O Ollama
    não tem piso: uma mídia por pedido é de graça, e a chave perde a função.

    ⛔ MEDIDO (qwen2.5vl:7b, 2026-09-12): com o envelope, o modelo copiou o PLACEHOLDER
    `"<chave da mídia>"` como chave; e sem a última frase, devolveu um ARRAY com uma
    decupagem por quadro. Os `assert` fazem uma mudança na `PERSONA` quebrar os testes em
    vez de mandar prompt velho em silêncio.
    """
    p = _dec.PERSONA
    envelope = (
        'Responda SOMENTE com um objeto JSON, sem cercas de código e sem uma palavra antes '
        'ou\ndepois. A chave de primeiro nível é a CHAVE da mídia, e o valor é a decupagem '
        'dela:\n\n{"<chave da mídia>": {\n   '
    )
    assert envelope in p, "a PERSONA do decupador mudou; reveja persona_plana()"
    p = p.replace(envelope, (
        'Responda SOMENTE com um objeto JSON, sem cercas de código e sem uma palavra antes '
        'ou\ndepois, com exatamente estes campos:\n\n{\n   '
    ))
    # ⛔ MEDIDO (qwen3-vl 8B, 2026-09-22): o que não está NESTA lista o modelo não responde
    #    — "exatamente estes campos" vence um parágrafo. Com a claquete fora da lista, ela
    #    veio `null` em 4 de 4 takes com claquete.
    fim = '"claquete": "SÓ se houver claquete — o objeto descrito acima"}}'
    assert p.count(fim) == 1, "a PERSONA do decupador mudou; reveja persona_plana()"
    p = p.replace(fim, fim[:-2] + "\n}")

    varias = p.find("\nQuando vierem várias mídias")
    assert varias > 0, "a PERSONA do decupador mudou; reveja persona_plana()"
    return p[:varias].rstrip() + (
        "\n\nOs quadros são do MESMO plano, em ordem de tempo. Responda UM ÚNICO objeto "
        "descrevendo esse plano — nunca um objeto por quadro, nunca uma lista."
    )


def corpo_do_pedido(jpegs: list[bytes], posicoes: list[int], clipe: dict, chave: str,
                    modelo: str = MODELO, cabeca: list[bytes] | None = None,
                    segundos_da_cabeca: list[float] | None = None) -> dict[str, Any]:
    """O pedido de `/api/chat`, igual ao da M1 — mesmo cabeçalho que o MCP manda."""
    # ⚠️ O `fps` do acervo é FRAÇÃO em texto (`24000/1001`): `float()` direto levanta.
    fps = float(Fraction(str(clipe.get("fps") or 25)))
    cabecalho = (
        f"{len(jpegs)} quadro(s) da mídia {clipe.get('nome') or chave[:12]}"
        + (f", duração {float(clipe['duracao_s']):.1f}s" if clipe.get("duracao_s") else "")
        + ".\nOs quadros estão em ordem, nos segundos "
        + ", ".join(f"{p / fps:.1f}" for p in posicoes)
        + " do material."
        + (f"\nOs {len(cabeca)} últimos são a CABEÇA do take, em resolução maior, para ler "
           "a claquete — segundos " + ", ".join(f"{s:.1f}" for s in (segundos_da_cabeca or []))
           + "." if cabeca else "")
        + "\n\nDecupe esta mídia."
    )
    return {
        "model": modelo,
        "stream": False,
        # ⭐ `temperature: 0`: a fila tem de dar a mesma nota se rodada de novo.
        # ⛔ E o contexto acompanha o PEDIDO: com a densidade da aba são até 24 quadros, e
        #   o que passa do `num_ctx` o Ollama corta calado (ver `contexto_para`).
        "options": {"temperature": 0,
                    "num_ctx": contexto_para(len(jpegs), len(cabeca or []))},
        "messages": [
            {"role": "system", "content": persona_plana()},
            {"role": "user", "content": cabecalho,
             "images": [base64.b64encode(j).decode("ascii")
                        for j in [*jpegs, *(cabeca or [])]]},
        ],
    }


def decupar(url: str, chave: str, modelo: str = MODELO,
            prazo: float = PRAZO_S, quadros: int = 0) -> dict[str, Any]:
    """UMA mídia no Mac. Mesmo formato de `decupador.decupar`: notas, avisos, uso, segundos.

    Levanta `MacIndisponivel` quando o problema é o Mac (não respondeu, HTTP) e
    `DecupagemFalhou` quando o problema é a resposta — a fila trata os dois diferente.
    """
    from ..mcp.ferramentas.midia import quadros_da_cabeca, quadros_de   # tardio: ciclo

    # ⭐ A densidade escolhida pelo editor vale nos DOIS motores: o Mac não cobra dólar, mas
    #   cobra tempo, e "olhei 24 quadros" é a mesma decisão dele dos dois lados.
    # ⛔⛔ Com um TETO, e ele é do Ollama: o que passa do contexto ele corta calado. Cortar
    #   aqui é uma decisão que volta na resposta (`quadros`) e vai para a procedência da
    #   nota; cortar lá dentro, ninguém vê — e a tela continuaria dizendo 24.
    pedidos = quadros or _dec.QUADROS
    cabem = quadros_que_cabem(2)
    if pedidos > cabem:
        log.info("o Mac olha %d quadros em vez de %d: o contexto dele não leva mais",
                 cabem, pedidos)
    jpegs, posicoes, clipe = quadros_de(chave, min(pedidos, cabem))
    cabeca, segundos = quadros_da_cabeca(chave)
    corpo = corpo_do_pedido(jpegs, posicoes, clipe, chave, modelo, cabeca, segundos)

    comeco = time.monotonic()
    try:
        resposta = pedir(url, "/api/chat", corpo, timeout=prazo)
    except urllib.error.HTTPError as e:
        # ⛔ O corpo é onde o Ollama DIZ o que houve: o 400 sozinho não distingue "não cabe
        #    no contexto" de "modelo não existe".
        detalhe = e.read().decode("utf-8", "replace")[:200]
        raise _dec.DecupagemFalhou(f"o Mac respondeu HTTP {e.code}: {detalhe}") from None
    except (urllib.error.URLError, OSError) as e:
        raise MacIndisponivel(f"o Mac não respondeu: {e}") from None

    texto = (resposta.get("message") or {}).get("content") or ""
    notas, avisos = _dec.notas_da_resposta(_dec._json_da_resposta(texto), [chave])
    entrada = resposta.get("prompt_eval_count") or 0
    saida = resposta.get("eval_count") or 0
    return {
        "notas": notas,
        "avisos": avisos,
        # ⭐ Quantos quadros ele OLHOU de verdade — pode ser menos que o pedido, e é este
        #   número que vai para a procedência da nota.
        "quadros": len(jpegs),
        # ⭐ Sem `custo_usd` de propósito: não passa pela assinatura, e inventar preço é a
        #   forma mais fácil de mentir sobre dinheiro.
        "uso": {"modelo": modelo, "entrada": entrada, "saida": saida,
                "tokens": entrada + saida, "local": True},
        "segundos": round(time.monotonic() - comeco, 1),
    }
