"""`planos_parecidos` — onde mais existe um plano assim.

⭐ É o pedido do editor em 2026-09-11: *"arrastar uma imagem, ou apontar o quadro que está
no monitor, e achar planos parecidos, para match cut"*. O motor foi medido antes de ser
escolhido (`spikes/busca_visual.py`): MobileNetV2 em ONNX, 14 MB, 99% de acerto contra
38% ao acaso — sem CLIP de 350 MB e sem torch.

⚠️ **O que ela responde, e o que ela NÃO responde.** A parecença é de enquadramento e
conteúdo do quadro. Foi medida em cena fechada — mesma luz, mesmo cenário —, e *"ache a
Personagem F em outra cena"* continua por medir. A descrição da ferramenta diz isso ao modelo,
para ele não vender ao editor uma certeza que não temos.

⚠️ E ela só devolve material das bins do projeto ABERTO — decisão do editor em
2026-09-13, e a mesma regra do PhraseFind AI do Media Composer ("bins in a single
project"). O ÍNDICE continua global por UMID; quem se estreita é a resposta.

⚠️ E ela só enxerga o que foi vetorizado. Sem a aba Vetores ter passado pelo acervo, a
busca acha pouco — e a resposta diz isso, em vez de devolver uma lista curta como se fosse
o acervo inteiro.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from pathlib import Path

from ... import nle as _nle
from ...avid.mcapi import McApiErro
from ...avid.take import TakeErro
from ...midia import cache as _cache
from ...midia import frames as _frames
from ...midia import vetores as _vetores
from ...servico import arrastados as _arrastados
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.parecidos")

MAXIMO = 12


def _quadro_do_take(bin: str, item: str, posicao: int | None) -> tuple[bytes, str, str]:
    """O JPEG de um quadro do take, o nome do take e a chave do master da imagem."""
    take = _nle.resolver_take(bin, item)

    imagem = take.imagem
    if imagem is None or not imagem.arquivos:
        raise TakeErro("esse take não tem imagem")

    # ⚠️ O quadro do MEIO por padrão. A primeira posição costuma ser claquete ou resto do
    #    plano anterior — procurar parecido com uma claquete acha todas as claquetes.
    if posicao is None:
        posicao = imagem.inicio_frames + take.duracao_frames // 2

    midia = imagem.midia(rotulo=take.rotulo(imagem))
    if midia.tem_quadro(posicao):
        return midia.caminho_do_quadro(posicao).read_bytes(), take.nome, midia.chave

    taxa = Fraction(take.fps["num"], take.fps["den"])
    jpeg = _frames.extrair(imagem.arquivos[0], posicao, taxa)
    midia.guardar_quadro(posicao, jpeg)
    return jpeg, take.nome, midia.chave


@ferramenta(
    nome="planos_parecidos",
    descricao=(
        "Acha, no material já analisado, os planos mais PARECIDOS com um take do Avid ou "
        "com uma imagem que o editor arrastou para o chat. Serve para match cut, para "
        "achar outra tomada do mesmo enquadramento, ou para localizar onde mais aquele "
        "cenário aparece. A parecença é de ENQUADRAMENTO e conteúdo do quadro — não é "
        "reconhecimento de pessoa, e não foi medida entre cenas diferentes: diga isso ao "
        "editor em vez de afirmar que é a mesma pessoa. Só encontra mídia que já tem "
        "vetor E que está em alguma bin do projeto ABERTO: quem gera os vetores é a aba "
        "Vetores do painel."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string",
                    "description": "Caminho da bin do take de referência."},
            "item": {"type": "string",
                     "description": "Nome do clipe de referência (subclipe ou master), ou o MobID."},
            "imagem": {
                "type": "string",
                "description": ("Caminho de uma imagem que o editor ARRASTOU para o "
                                "chat, em vez de um take. Só funciona com arquivo "
                                "arrastado."),
            },
            "frame_no_master": {
                "type": "integer",
                "description": ("Quadro exato a usar como referência, em tempo do "
                                "master. Padrão: o meio do take."),
            },
            "quantos": {"type": "integer",
                        "description": f"Quantos resultados, de 1 a {MAXIMO}. Padrão 6.",
                        "default": 6},
        },
        "required": [],
    },
    escreve=False,
    nles=AMBOS,
)
def planos_parecidos(bin: str = "", item: str = "", imagem: str = "",
                     frame_no_master: int | None = None,
                     quantos: int = 6) -> dict[str, object]:
    quantos = max(1, min(int(quantos or 6), MAXIMO))

    if not _vetores.temos_o_modelo():
        # ⭐ Dizer o que falta, e não "não achei nada": o editor tem um botão que resolve.
        return {"erro": "o modelo de imagem ainda não foi baixado; a aba Vetores o traz "
                        "na primeira análise visual"}

    de_onde = ""
    excluir = ""
    try:
        if imagem:
            # ⛔⛔ Só o que o editor ARRASTOU. O caminho chega aqui dentro de texto que o
            #    MODELO escreve; sem a lista de arrastados, "procure parecido com esta
            #    imagem" seria a máquina inteira legível (ADR 0005).
            if not _arrastados.autorizado(imagem):
                return {"erro": _arrastados.recusa(imagem)}
            alvo_no_disco = Path(imagem)
            if alvo_no_disco.suffix.lower() not in _arrastados.IMAGEM:
                return {"erro": f"não sei olhar {alvo_no_disco.suffix or 'esse formato'} "
                                f"como imagem"}
            jpeg = alvo_no_disco.read_bytes()
            de_onde = alvo_no_disco.name
        elif bin and item:
            _turno.avisar("olhando o take", None, item)
            jpeg, de_onde, excluir = _quadro_do_take(bin, item, frame_no_master)
        else:
            return {"erro": "diga de que take, ou arraste uma imagem para o chat"}
    except (TakeErro, McApiErro, _cache.ChaveInvalida, OSError) as e:
        return {"erro": str(e)}

    try:
        alvo = _vetores.de_jpeg(jpeg)
    except _vetores.ModeloIndisponivel as e:
        return {"erro": str(e)}

    _turno.avisar("procurando planos parecidos", None, de_onde)
    # ⭐⭐ Só o que está nas bins do projeto ABERTO. Um match cut proposto com material de
    #   outra produção é pior que nenhum: a parecença é verdadeira e o plano não existe
    #   para este editor (`avid/escopo.py`).
    recorte = _nle.escopo_agora()
    achados = _vetores.procurar(alvo, limite=quantos, exceto=excluir,
                                chaves=recorte.chaves, exceto_frame=frame_no_master)

    return {
        "referencia": de_onde,
        "escopo": recorte.como_dicionario(),
        "parecidos": [
            {
                "midia": a["nome"] or a["chave"][:12],
                "frame_no_master": a["frame_no_master"],
                # ⭐ Em material MONTADO a resposta diz QUAL plano da peça — sem isso, três
                #   linhas da mesma peça pareceriam o mesmo resultado repetido.
                **({"plano": a["plano"], "de_planos": a["de_planos"]} if a.get("plano") else {}),
                "parecenca": a["parecenca"],
                # ⚠️ Procedência em todo item, como manda a casa: isto é medida de
                #   parecença visual, não observação confirmada.
                "confianca": "inferido",
                "fonte": "visual",
                "medida": a["parecenca"],
            }
            for a in achados
        ],
        "aviso": ("A parecença é de enquadramento e conteúdo do quadro, medida em cena "
                  "fechada. Só entra material que já tem vetor. " + recorte.aviso),
    }
