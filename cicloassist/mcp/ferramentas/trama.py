"""`o_que_acontece` — a linha do tempo de um take: o que se VÊ e o que se DIZ, em ordem.

⭐⭐ A F4 do plano da decupagem micro, e o pedido do editor por trás dela: perguntar *"o que
está acontecendo neste material?"* e receber a **trama**, não a lista de elementos.

A resposta é composta na hora, a partir do que já está no cache:

| camada | de onde | em que tempo |
|---|---|---|
| os trechos (o que acontece) | notas `escopo: trecho` da micro + `cortes.json` | quadros do MASTER da IMAGEM |
| as falas (o que é dito) | `transcricao.json` | segundos do MASTER do SOM |
| a claquete, cena/plano/take | a nota da cabeça, que subiu para a macro | — |

⛔⛔ **E os dois masters têm offsets DIFERENTES** (medido na C07: imagem em 0, som em 234
quadros — quase 10 s). Por isso tudo é convertido para o **tempo do TAKE** antes de virar
resposta: usar o offset da imagem para a fala descreveria a cena vizinha com total confiança.

⚠️ **Não é resumo gravado.** A trama é composta na resposta, acompanhando a pergunta — um
resumo no cache envelheceria calado na primeira redecupagem.

⚠️ **Nada é processado aqui**: a ferramenta LÊ. Sem a micro feita, ela devolve o que há (a
decupagem do material inteiro e as falas) e diz o gesto que falta — "Decupar em trechos" na
aba Vetores.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from typing import Any

from ... import nle as _nle
from ...avid import take as _take
from ...avid.take import TakeErro
from ...midia import cache as _cache
from ...midia import cortes as _cortes
from ...midia import falantes as _falantes
from ...midia import voz as _voz
from ..registro import AMBOS, ferramenta
from . import fala as _fala

log = logging.getLogger("cicloassist.mcp.trama")

#: Quantas falas entram em cada trecho antes de virar contagem. ⚠️ Um trecho de 40 s de
#: diálogo tem dezenas; a trama quer o que se diz ali, não a transcrição inteira (para essa
#: existe `transcrever`, com a numeração de segmento que o `separar_falas` aceita).
FALAS_POR_TRECHO = 6


def _relogio(segundos: float) -> str:
    s = max(0, int(round(segundos)))
    return f"{s // 60:02d}:{s % 60:02d}"


def _campos_da_nota(nota: dict[str, Any]) -> dict[str, Any]:
    saida = {c: nota[c] for c in ("enquadramento", "angulo", "camera", "local", "momento")
             if nota.get(c)}
    if nota.get("etiquetas"):
        saida["etiquetas"] = list(nota["etiquetas"])[:8]
    return saida


def linha_do_take(take, com_falas: bool = True) -> dict[str, Any]:
    """A linha do tempo deste take — tudo no TEMPO DO TAKE (0 = a entrada dele)."""
    taxa = Fraction(take.fps["num"], take.fps["den"])
    fps = float(taxa)
    imagem, som = take.imagem, take.som
    duracao = take.duracao_frames
    saida: dict[str, Any] = {
        "take": take.nome, "duracao_s": round(duracao / fps, 1),
        "linha": [], "avisos": list(take.avisos or []),
    }

    trechos: list[dict[str, Any]] = []
    macro = None
    if imagem is not None:
        try:
            midia = imagem.midia(rotulo=take.rotulo(imagem))
        except _cache.ChaveInvalida:
            midia = None
        if midia is not None and midia.existe:
            notas = midia.ler_notas()
            macro = next((n for n in notas if n.get("escopo") == "midia"), None)
            por_inicio = {int(n["inicio_frames"]): n for n in notas
                          if n.get("escopo") == "trecho" and n.get("inicio_frames") is not None}
            dados = _cortes.ler(midia) or {}
            base = imagem.inicio_frames
            for t in dados.get("trechos") or []:
                # ⚠️ Só o que ENCOSTA na janela do take: o master pode ter dez minutos e o
                #    subclipe trinta segundos.
                if t["fim"] <= base or t["inicio"] >= base + duracao:
                    continue
                nota = por_inicio.get(int(t["inicio"]))
                trechos.append({
                    "em": _relogio(max(0, t["inicio"] - base) / fps),
                    "ate": _relogio(min(duracao, t["fim"] - base) / fps),
                    "_de_s": max(0.0, (t["inicio"] - base) / fps),
                    "_ate_s": min(duracao / fps, (t["fim"] - base) / fps),
                    "entrada": t.get("entrada"),
                    **({"descricao": nota.get("descricao"), **_campos_da_nota(nota)}
                       if nota else {"descricao": None}),
                    **({"claquete": nota["claquete"]} if nota and nota.get("claquete") else {}),
                })
            if macro:
                saida["do_material_inteiro"] = {
                    "descricao": macro.get("descricao"), **_campos_da_nota(macro),
                    **({"claquete": macro["claquete"]} if macro.get("claquete") else {}),
                }
                for campo in ("cena", "plano", "take"):
                    if macro.get(campo):
                        saida.setdefault("claquete_diz", {})[campo] = macro[campo]

    falas: list[dict[str, Any]] = []
    if com_falas and som is not None:
        try:
            midia_som = som.midia(rotulo=take.rotulo(som))
        except _cache.ChaveInvalida:
            midia_som = None
        if midia_som is not None and midia_som.tem_transcricao():
            # ⭐ A MESMA lista que `transcrever` numera: o `segmento` daqui é o de lá, e é
            #   ele que `separar_falas` aceita. Numerar por conta própria faria o segmento
            #   12 desta resposta não ser o 12 que o modelo lê depois.
            # ⭐ quem fala (plano 2026-11-06): só o que já está no cache — ler não mede nada
            transcricao = _falantes.anexar(midia_som.ler_transcricao(), _falantes.ler(midia_som))
            transcricao = _voz.anexar(transcricao, _voz.ler(midia_som))
            for f in _fala.falas_do_take(take, transcricao):
                # ⚠️ Em QUADROS do take: o tempo cru do ASR saiu da resposta do
                #   `transcrever` de propósito ("campo que existe para não ser usado um dia
                #   é usado"), e aqui o número serve para ordenar, nunca para cortar.
                # ⚠️ E ele é a ENTRADA DO CORTE, que já traz o respiro medido antes da
                #   primeira palavra: uma fala que começa logo depois de uma fronteira cai
                #   no trecho ANTERIOR, por até `asr.RESPIRO_ANTES_S` (0,17 s). É a margem que
                #   existe para o corte não comer a sílaba, e num trecho de 4 s ou mais ela
                #   não muda o que se lê. Quem quiser o instante da palavra usa
                #   `transcrever`, que é a ferramenta de cortar.
                quando = float(f["inicio_no_take_frames"]) / fps
                falas.append({"segmento": f["segmento"], "em": _relogio(quando),
                              "_s": quando, "texto": f["texto"],
                              **({"quem": f["quem"]} if f.get("quem") else {})})

    if not trechos:
        # ⚠️ Sem micro, a linha é a fala — e o aviso diz o GESTO que falta, não só o estado.
        saida["linha"] = [{"em": f["em"], "diz": f["texto"], "segmento": f["segmento"],
                           **({"quem": f["quem"]} if f.get("quem") else {})} for f in falas]
        saida["sem_trechos"] = (
            "esta mídia ainda não tem decupagem por trechos; o que há é a decupagem do "
            "material inteiro e a fala. Para ter a linha do tempo visual, peça ao editor "
            'para mandar "Decupar em trechos" na aba Vetores.')
        return saida

    coladas = 0
    for t in trechos:
        dentro = [f for f in falas if t["_de_s"] <= f["_s"] < t["_ate_s"]]
        coladas += len(dentro)
        if dentro:
            t["diz"] = [{"segmento": f["segmento"], "em": f["em"], "texto": f["texto"],
                         **({"quem": f["quem"]} if f.get("quem") else {})} for f in dentro[:FALAS_POR_TRECHO]]
            if len(dentro) > FALAS_POR_TRECHO:
                t["mais_falas"] = len(dentro) - FALAS_POR_TRECHO
    # ⚠️ A conta do que ficou de fora sai do MESMO critério de quem entrou — os segundos.
    #   Comparando o relógio `MM:SS` (como esta linha fazia), uma fala na fronteira era
    #   "dentro" por arredondamento e "fora" pela conta, e o número não fechava com nada.
    #   ⛔ E os trechos só perdem os campos de segundos DEPOIS desta conta.
    fora = len(falas) - coladas
    for t in trechos:
        t.pop("_de_s", None)
        t.pop("_ate_s", None)
    saida["linha"] = trechos
    saida["falas_no_take"] = len(falas)
    if fora:
        saida["falas_fora_dos_trechos"] = fora
    sem_nota = sum(1 for t in trechos if not t.get("descricao"))
    if sem_nota:
        saida["trechos_sem_decupagem"] = sem_nota
        saida["aviso"] = (f"{sem_nota} de {len(trechos)} trechos ainda não foram decupados — "
                          'a fila da aba Vetores ("Decupar em trechos") completa.')
    return saida


@ferramenta(
    nome="o_que_acontece",
    descricao=(
        "A linha do tempo de um take: o que ACONTECE em cada trecho (a decupagem por "
        "trechos) com as falas ditas ali, em ordem de tempo. Use quando perguntarem o que "
        "acontece num material, qual é a trama de uma cena, onde alguém faz alguma coisa, "
        "ou para entender um take antes de montar. Não processa nada: devolve o que já foi "
        "analisado, e diz quando falta."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "A bin, como a listagem devolveu."},
            "item": {"type": "string",
                     "description": "O clipe: nome ou o identificador da listagem."},
            "com_falas": {"type": "boolean", "default": True,
                          "description": "Incluir o que é dito em cada trecho."},
            "a_partir": {"type": "integer", "default": 0,
                         "description": "Continuar a linha a partir deste trecho (a "
                                        "resposta diz `proximo` quando sobrou)."},
        },
        "required": ["bin", "item"],
    },
    escreve=False,
    nles=AMBOS,
)
def o_que_acontece(bin: str, item: str, com_falas: bool = True,
                   a_partir: int = 0) -> dict[str, Any]:
    try:
        take = _nle.resolver_take(bin, item)
    except TakeErro as e:
        return {"erro": f"não consegui abrir esse take: {e}"}
    if take.imagem is None and take.som is None:
        return {"erro": f"esse take não tem mídia: {_take.por_que_falta(None, 'imagem')}"}

    dados = linha_do_take(take, com_falas=com_falas)
    # ⛔ O mesmo teto de saída do `transcrever`: lista sem limite não tem teto, e um take
    #   de dez minutos com micro feita passa do limite de saída do CLI. Truncar calado
    #   faria o modelo contar a trama sem o fim dela.
    inteira = len(dados["linha"])
    pagina, proximo = _fala.paginar(dados["linha"], max(0, int(a_partir or 0)))
    dados["linha"] = pagina
    # ⚠️⚠️ O TAMANHO do que está sendo mostrado, sempre — a mesma regra da aba Busca. Sem
    #   ele, uma página de 8 trechos de um take que tem 31 se lê como o take inteiro, e o
    #   modelo conta a trama achando que viu o fim. ⭐ E o nome diz de quantos é a conta,
    #   porque a linha pode ser de trechos (com micro) ou de falas (sem ela).
    dados["mostrando"] = len(pagina)
    dados["trechos_no_take" if not dados.get("sem_trechos") else "falas_no_take"] = inteira
    if proximo:
        dados["proximo"] = proximo
        dados["aviso_pagina"] = (f"a linha continua ({inteira - len(pagina)} depois desta "
                                 f"página): chame de novo com a_partir={proximo}.")
    dados["confianca"] = "inferido"
    dados["fonte"] = "visual"
    return dados
