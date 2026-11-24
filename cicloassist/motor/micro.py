"""A decupagem MICRO: uma nota por TRECHO, com entrada e saída (plano `sobre-a-decupagem-hoje`, F2).

⭐⭐ **Complementa a macro, nunca a substitui** (decisão do editor, 2026-09-22): *"essa
leitura é complementar e não substitui a macro, que é mais rápida"*. A nota `escopo: midia`
continua; esta acrescenta notas `escopo: trecho`, e é nela que a CLAQUETE é relida (o trecho
da cabeça de um take bruto).

Os trechos vêm de `midia/cortes.py` (a união scdet ∪ pixel, medida na F0). O motor é o
**Qwen no Mac** (decisão do editor, 2026-09-21): não gasta assinatura, e a micro multiplica o
número de pedidos — pelo Claude, uma peça de 30 min seria ~US$ 3 (plano, estimativa).

Tudo o mais é o que a macro já usa, e por isso a mesma validação: `decupador.PERSONA` (via
`percepcao.persona_plana`), `decupador.notas_da_resposta`, a leitura e a conferência da
claquete (`ler_claquete`, `conferir_a_claquete`).
"""

from __future__ import annotations

import base64
import json
import logging
import time
import urllib.error
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from ..midia import cache as _cache
from ..midia import cortes as _cortes
from ..midia import frames as _frames
from ..midia import vetores as _vetores
from . import decupador as _dec
from . import percepcao as _perc

log = logging.getLogger("cicloassist.motor.micro")

#: Quadros por trecho de um take BRUTO: poucos no parado, mais onde há ação (o `movimento`
#: do trecho é a soma de `d1`; medido de ~0,2 a ~6,6 por 10 s). ⚠️ Calibragem inicial.
QUADROS_MIN, QUADROS_MAX = 3, 8
ESCOPO = "trecho"

# ── o preço, e aqui ele é TEMPO ──────────────────────────────────────────────
#
# ⭐⭐ A micro não gasta a assinatura (roda no Mac), e por isso é fácil achar que ela é de
# graça. Não é: ela é a coisa MAIS LENTA do produto — horas de Mac para uma diária —, e o
# notebook precisa ficar acordado o tempo todo, porque os quadros saem daqui. Tempo de horas
# tem de ser DITO antes do clique, pela mesma razão que o dólar da macro é.
#
# MEDIDO em 2026-09-22, Mac mini, `qwen3-vl:8b-instruct`, material real do acervo:
#
#     bruto    ~50 s por trecho   ⇒ ~2,5 min de Mac por minuto de take
#     montado  ~87 s por trecho de 8 planos  ⇒ ~16 min de Mac por minuto de peça
#
# ⚠️ O trecho do montado custa mais porque é um GRUPO de até `cortes.PLANOS_POR_TRECHO`
# planos: são mais quadros no mesmo pedido.
SEGUNDOS_POR_TRECHO = {"bruto": 50.0, "montado": 87.0}
#: ⚠️⚠️ **ESTIMATIVA, não medição**, e a tela usa isto SÓ para a mídia cujos cortes ainda
#: não foram procurados — quem já tem `cortes.json` entra na conta pelo número REAL de
#: trechos. Sai das mesmas rodadas acima: a promo da Copa deu 11 trechos em 60 s; o take
#: contínuo, dividido pela ação, ~3 por minuto.
#: ⛔ E a diferença entre os dois é de 6×, então a tela **nunca escolhe um** para material
#: que ninguém varreu: ela mostra a FAIXA e diz que é faixa. Chutar o bruto (que é a maior
#: parte de um acervo de câmera) faria o editor começar às 18 h um trabalho de 9 horas
#: achando que eram 90 minutos.
TRECHOS_POR_MINUTO = {"bruto": 3.0, "montado": 11.0}
#: Procurar os cortes, antes de qualquer nota: uma passada de ffmpeg no NOTEBOOK (não no
#: Mac), decode-bound. MEDIDO: 14,5 s num take contínuo de 12 min em 1080p.
SEGUNDOS_DE_DETECCAO_POR_MINUTO = 1.2


class MicroIndisponivel(RuntimeError):
    """A micro não tem onde rodar (sem o Mac configurado)."""


def _relogio(segundos: float) -> str:
    s = int(round(segundos))
    return f"{s // 60:02d}:{s % 60:02d}"


def posicoes_do_trecho(t: dict[str, Any], bruto: bool) -> list[int]:
    """Que quadros o modelo vê neste trecho.

    - montado com vários planos: UM do meio de cada plano (é a sequência que se descreve);
    - bruto: de `QUADROS_MIN` a `QUADROS_MAX`, conforme o movimento — `frames.distribuir`
      no trecho, que já evita as pontas.
    """
    planos = list(t.get("planos") or [t["inicio"]])
    if not bruto and len(planos) > 1:
        fins = [*planos[1:], t["fim"]]
        return [(a + b) // 2 for a, b in zip(planos, fins) if b > a]
    n = max(QUADROS_MIN, min(QUADROS_MAX, round(2 + float(t.get("movimento") or 0))))
    return _frames.distribuir(t["inicio"], max(1, t["fim"] - t["inicio"]), n)


def _jpegs(midia: _cache.Midia, arquivo: str, posicoes: list[int],
           taxa: Fraction) -> list[bytes]:
    """Do cache quando houver; o que faltar é extraído numa passada e GUARDADO (mesma
    receita dos quadros da macro: 768 px, posição em tempo do master)."""
    faltam = [p for p in posicoes if not midia.tem_quadro(p)]
    novos = _frames.extrair_varios(arquivo, faltam, taxa) if faltam else {}
    saida = []
    for p in posicoes:
        if midia.tem_quadro(p):
            saida.append(midia.caminho_do_quadro(p).read_bytes())
        elif novos.get(p):
            midia.guardar_quadro(p, novos[p])
            saida.append(novos[p])
    if faltam and not midia.ler_gerador("quadros"):
        midia.registrar_gerador("quadros", dict(_frames.ASSINATURA))
    return saida


def corpo_do_trecho(jpegs: list[bytes], posicoes: list[int], t: dict[str, Any], bruto: bool,
                    taxa: Fraction, nome: str, cabeca: list[bytes], modelo: str,
                    segundos_da_cabeca: list[float] | None = None) -> dict:
    fps = float(taxa)
    montado = not bruto and len(t.get("planos") or []) > 1
    # ⚠️ A cabeça vai PRIMEIRO, em ordem: MEDIDO, com ela no fim do pedido o modelo narrou
    #    "a claquete é mostrada novamente no final". No trecho da cabeça ela é mesmo o começo
    #    (1 s e 3 s; `frames.distribuir` evita a ponta), então a ordem é a do tempo.
    segundos = [*(f"{s:.1f} (maior, para ler a claquete)" for s in (segundos_da_cabeca or [])),
                *(f"{p / fps:.1f}" for p in posicoes)]
    cabecalho = (
        f"{len(jpegs) + len(cabeca)} quadro(s) de UM TRECHO ({_relogio(t['inicio'] / fps)} a "
        f"{_relogio(t['fim'] / fps)}) da mídia {nome}, em ordem, nos segundos "
        + ", ".join(segundos) + "."
        + ("\nCada quadro é de um PLANO diferente, em sequência (material montado): descreva "
           "a sequência de planos em ordem." if montado else
           "\nDescreva o que ACONTECE neste trecho, em ordem — não só o que está no quadro.")
        + "\n\nDecupe este trecho."
    )
    return {
        "model": modelo, "stream": False,
        # ⛔ MEDIDO: num trecho de 8 planos o Qwen devolveu JSON quebrado ("Expecting ','").
        #    O Ollama FORÇA JSON válido com `format: json`.
        "format": "json",
        # ⛔ O contexto acompanha o pedido: um trecho de 8 planos mais os 2 quadros grandes
        #   da cabeça passa de `CONTEXTO`, e o Ollama corta calado o que não cabe.
        "options": {"temperature": 0,
                    "num_ctx": _perc.contexto_para(len(jpegs), len(cabeca))},
        "messages": [
            {"role": "system", "content": _perc.persona_plana()},
            {"role": "user", "content": cabecalho,
             "images": [base64.b64encode(j).decode("ascii") for j in [*cabeca, *jpegs]]},
        ],
    }


def decupar_trecho(url: str, midia: _cache.Midia, arquivo: str, taxa: Fraction,
                   t: dict[str, Any], bruto: bool, nome: str,
                   modelo: str = _perc.MODELO) -> dict[str, Any]:
    """UM trecho no Mac → a nota validada (sem gravar). Levanta como `percepcao.decupar`."""
    from ..mcp.ferramentas.midia import quadros_da_cabeca   # tardio: ciclo no registro

    posicoes = posicoes_do_trecho(t, bruto)
    jpegs = _jpegs(midia, arquivo, posicoes, taxa)
    if not jpegs:
        raise _dec.DecupagemFalhou("não consegui extrair os quadros do trecho")
    cabeca, segs = quadros_da_cabeca(midia.chave) if t.get("cabeca") else ([], [])
    corpo = corpo_do_trecho(jpegs, posicoes, t, bruto, taxa, nome, cabeca, modelo, segs)
    comeco = time.monotonic()
    try:
        resposta = _perc.pedir(url, "/api/chat", corpo, timeout=_perc.PRAZO_S)
    except urllib.error.HTTPError as e:
        detalhe = e.read().decode("utf-8", "replace")[:200]
        raise _dec.DecupagemFalhou(f"o Mac respondeu HTTP {e.code}: {detalhe}") from None
    except (urllib.error.URLError, OSError) as e:
        raise _perc.MacIndisponivel(f"o Mac não respondeu: {e}") from None
    texto = (resposta.get("message") or {}).get("content") or ""
    notas, avisos = _dec.notas_da_resposta(_dec._json_da_resposta(texto), [midia.chave])
    nota = notas.get(midia.chave)
    if not nota:
        raise _dec.DecupagemFalhou("; ".join(avisos) or "o Mac não devolveu a decupagem")
    if not t.get("cabeca") and nota.get("claquete"):
        # ⛔⛔ MEDIDO (2026-09-22): num trecho do MEIO do take, sem claquete nenhuma, o modelo
        #    devolveu "31 · 8 · 5" — o EXEMPLO da instrução — com o rolo tirado do nome do
        #    arquivo. Só o trecho da cabeça lê claquete; a de cauda fica para quando houver
        #    gabarito dela.
        claquete = nota.pop("claquete")
        for campo in ("cena", "plano", "take"):
            if nota.get(campo) == claquete.get(campo):
                nota.pop(campo, None)
    return {"nota": nota, "segundos": round(time.monotonic() - comeco, 1),
            "quadros": len(jpegs) + len(cabeca)}


def chave_do_trecho(nome: str, t: dict[str, Any]) -> str:
    """O `trecho` da nota — único por trecho: `Midia.anotar` substitui pelo mesmo valor."""
    return f"{nome} · trecho {t['inicio']}"


def ja_feitos(midia: _cache.Midia) -> set[int]:
    return {int(n["inicio_frames"]) for n in midia.ler_notas()
            if n.get("escopo") == ESCOPO and n.get("inicio_frames") is not None}


def falta(midia: _cache.Midia) -> bool:
    """Falta micro nesta mídia? Sem `cortes.json` de hoje, falta; senão, falta trecho."""
    dados = _cortes.ler(midia)
    if dados is None:
        return True
    feitos = ja_feitos(midia)
    return any(t["inicio"] not in feitos for t in dados["trechos"])


def _subir_claquete(midia: _cache.Midia, claquete: dict[str, Any]) -> None:
    """⭐ A claquete lida no trecho da cabeça vai também para a nota MACRO — que é onde a
    busca e o cartão a mostram —, se lá não houver uma leitura legível.

    ⛔⛔ E só sobe a que a conferência APROVOU. Medido no cache em 2026-09-23: das 44 notas
    com a claquete em `hipotese`, **22 eram a nota macro** — esta função subia justamente a
    leitura que `decupador.conferir_a_claquete` acabara de reprovar, e com ela os campos de
    topo que mandam nos filtros da busca. A checagem era só `legivel`, que uma leitura
    reprovada continua sendo: ela é o que o modelo diz ter lido, não o que confere.
    """
    if claquete.get("confianca") == "hipotese":
        return
    notas = midia.ler_notas()
    mudou = False
    for n in notas:
        if n.get("escopo") == "midia" and not (n.get("claquete") or {}).get("legivel"):
            n["claquete"] = claquete
            for campo in ("cena", "plano", "take"):
                if claquete.get(campo):
                    n[campo] = claquete[campo]
            mudou = True
    if mudou:
        _cache.escrever_atomico(midia.pasta / "notas.json",
                                json.dumps({"notas": notas}, ensure_ascii=False, indent=1)
                                .encode("utf-8"))


def processar(midia: _cache.Midia, arquivo: str, taxa: Fraction, nome: str, url: str,
              avisar: Callable[[float, str], None] | None = None,
              parar=None, refazer: bool = False) -> dict[str, int]:
    """A micro de UMA mídia: os trechos (do cache ou detectados agora) e uma nota por trecho
    que ainda não tem. Interrompível ENTRE trechos (no meio de um pedido não há por onde)."""
    if not url:
        raise MicroIndisponivel("a decupagem micro roda no Mac: configure o endereço dele")
    avisar = avisar or (lambda *_: None)
    avisar(0.0, f"{nome} · procurando os cortes")
    dados = _cortes.de_uma(midia, arquivo, taxa)
    bruto = bool(dados.get("bruto"))
    if not bruto:
        # ⭐⭐ UM VETOR POR PLANO, e só em material montado: sem isto, `planos_parecidos`
        #   representa uma peça de 600 planos com os 12 quadros espalhados da amostragem —
        #   quase nenhum plano tem vetor. Acrescenta aos que já existem (não mexe na
        #   receita: mudá-la invalidaria o cache inteiro).
        avisar(0.0, f"{nome} · vetor de cada plano")
        try:
            _vetores.vetorizar_planos(midia, arquivo, taxa, dados["trechos"], nome)
        except (_vetores.ModeloIndisponivel, _frames.ExtracaoFalhou, OSError) as e:
            log.warning("micro: sem vetores por plano em %s (%s)", nome, e)
    feitos = set() if refazer else ja_feitos(midia)
    todos = dados["trechos"]
    pendentes = [t for t in todos if t["inicio"] not in feitos]
    fps = float(taxa)
    arquivos_stem = [Path(a).stem for a in midia.manifesto().get("arquivos") or []]
    resultado = {"trechos": len(todos), "feitos": 0, "falharam": 0}
    for i, t in enumerate(pendentes):
        if parar is not None and parar.is_set():
            break
        avisar(i / max(1, len(pendentes)),
               f"{nome} · trecho {i + 1} de {len(pendentes)} ({_relogio(t['inicio'] / fps)})")
        try:
            feito = decupar_trecho(url, midia, arquivo, taxa, t, bruto, nome)
        except _perc.MacIndisponivel:
            raise
        except (_dec.DecupagemFalhou, _frames.ExtracaoFalhou, OSError) as e:
            log.warning("micro: não decupei %s @%d: %s", nome, t["inicio"], e)
            resultado["falharam"] += 1
            continue
        nota = _dec.conferir_a_claquete(feito["nota"], [nome, *arquivos_stem])
        nota.pop("avisos", None)
        midia.anotar({
            "trecho": chave_do_trecho(nome, t),
            "escopo": ESCOPO,
            "inicio_frames": t["inicio"], "duracao_frames": t["fim"] - t["inicio"],
            "inicio_s": round(t["inicio"] / fps, 3), "fim_s": round(t["fim"] / fps, 3),
            "entrada": t.get("entrada"), "planos": t.get("planos"),
            "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "confianca": "inferido", "fonte": "visual", "modelo": _perc.MODELO,
            **nota,
        })
        if t.get("cabeca") and (nota.get("claquete") or {}).get("legivel"):
            _subir_claquete(midia, nota["claquete"])
        resultado["feitos"] += 1
        log.info("micro %s @%s: %.0f s, %d quadros", nome, _relogio(t["inicio"] / fps),
                 feito["segundos"], feito["quadros"])
    return resultado
