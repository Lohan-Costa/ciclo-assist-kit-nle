"""`ver_frames` — a ferramenta que faz o Claude enxergar o material.

⭐ Não há modelo de visão neste produto. O quadro volta como bloco `image` no resultado
MCP e **o Claude é o modelo de visão**. É a decisão que tornou desnecessária a LLM local
que o projeto anterior perseguia.
"""

from __future__ import annotations

import base64
import logging
from fractions import Fraction

from ... import nle as _nle
from ...avid import take as _take
from ...avid.take import TakeErro
from ...midia import cache as _cache
from ...midia import estagios as _estagios
from ...midia import frames as _frames
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.visual")

ESTAGIO = _estagios.QUADROS
#: ⭐ O mesmo teto de `ver_quadros_da_midia` (24, desde a densidade da aba): quem está na
#: conversa pode pedir tantos quadros quanto a fila de fundo olha. ⚠️ O PADRÃO continua 3 —
#: no chat cada quadro é contexto do turno do editor, e é ele quem espera a resposta.
MAXIMO = 24


@ferramenta(
    nome="ver_frames",
    descricao=(
        "Extrai quadros de um take (Avid ou Premiere) e os devolve como IMAGENS, para você olhar e "
        "descrever o que há no plano: enquadramento, quem aparece, o que acontece, se é "
        "close ou geral. Use quando alguém perguntar o que existe num take, numa cena ou "
        "numa bin, ou pedir para encontrar material por descrição visual. Os quadros são "
        "guardados em cache, então pedir de novo é instantâneo."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {
                "type": "string",
                "description": "A bin, como a listagem de itens devolveu.",
            },
            "item": {"type": "string", "description": "O clipe: nome ou o identificador que a listagem mostrou (MobID no Avid, id no Premiere)."},
            "quantos": {
                "type": "integer",
                "description": f"Quantos quadros ver, de 1 a {MAXIMO}. Padrão 3.",
                "default": 3,
            },
        },
        "required": ["bin", "item"],
    },
    escreve=False,
    nles=AMBOS,
)
def ver_frames(bin: str, item: str, quantos: int = 3) -> list[dict]:
    quantos = max(1, min(int(quantos), MAXIMO))

    try:
        take = _nle.resolver_take(bin, item)
    except TakeErro as e:
        return [{"type": "text", "text": f"Não consegui abrir esse take: {e}"}]

    imagem = take.imagem
    if imagem is None or not imagem.arquivos:
        falta = ("o take não tem trilha de imagem" if imagem is None
                 else _take.por_que_falta(imagem, "imagem"))
        return [{"type": "text", "text": f"Não há o que mostrar: {falta}."}]

    video = imagem.arquivos[0]
    taxa = Fraction(take.fps["num"], take.fps["den"])

    # ⭐ As posições são calculadas no tempo do MASTER — `inicio_frames` da imagem, que
    # NÃO é o do som. É o que faz o cache servir a qualquer outro recorte da mesma mídia.
    posicoes = _frames.distribuir(imagem.inicio_frames, take.duracao_frames, quantos)

    try:
        midia = imagem.midia(rotulo=take.rotulo(imagem))
    except _cache.ChaveInvalida as e:
        # Sem chave válida não há cache, mas ainda dá para mostrar os quadros. Degradar é
        # melhor que recusar: o editor quer ver o plano, não saber do nosso cache.
        log.warning("sem cache para %s: %s", imagem.master, e)
        midia = None

    receita = _estagios.assinatura(ESTAGIO)
    if midia is not None and midia.precisa_refazer(ESTAGIO, receita):
        # Mudou a largura ou a qualidade: o que está guardado é de outra receita.
        midia.limpar_estagio(ESTAGIO)
        midia.registrar_gerador(ESTAGIO, receita)
        midia.anotar_fonte({
            "master": imagem.master,
            "arquivo": video,
            "fps": take.fps,
            "mob_id": imagem.mob_id,
        })

    # ⛔ Numa passada só o que falta: em arquivo de busca não confiável (o OP-Atom MPEG-2
    #    do transcode do Avid), cada quadro custaria decodificar o clipe de novo.
    faltam = [p for p in posicoes if not (midia is not None and midia.tem_quadro(p))]
    try:
        novos = _frames.extrair_varios(video, faltam, taxa) if faltam else {}
    except (_frames.FfmpegAusente, _frames.ExtracaoFalhou, OSError) as e:
        return [{"type": "text", "text": f"Falhei ao extrair os quadros: {e}"}]

    blocos: list[dict] = []
    reaproveitados = 0
    for i, posicao in enumerate(posicoes):
        # ⚠️ Extrair quadro é ffmpeg com seek: rápido por quadro, e devagar quando são
        #   oito de um take longo. O painel conta de quantos em quantos, para o editor
        #   saber que está andando — e para a barra não pular de nada a tudo.
        _turno.avisar("vendo os quadros", i / max(1, len(posicoes)),
                      f"{take.nome} · quadro {i + 1} de {len(posicoes)}")
        try:
            if midia is not None and midia.tem_quadro(posicao):
                jpeg = midia.caminho_do_quadro(posicao).read_bytes()
                reaproveitados += 1
            elif posicao in novos:
                jpeg = novos[posicao]
                if midia is not None:
                    midia.guardar_quadro(posicao, jpeg)
            else:
                jpeg = _frames.extrair(video, posicao, taxa)
                if midia is not None:
                    midia.guardar_quadro(posicao, jpeg)
        except (_frames.FfmpegAusente, _frames.ExtracaoFalhou, OSError) as e:
            return [{"type": "text", "text": f"Falhei ao extrair os quadros: {e}"}]

        blocos.append({
            "type": "image",
            "data": base64.b64encode(jpeg).decode("ascii"),
            "mimeType": "image/jpeg",
        })

    # ⚠️ O texto vem ANTES das imagens de propósito: sem ele o modelo recebe fotos soltas
    # e não sabe de que take são, nem em que ordem, nem quanto tempo separa uma da outra.
    relativo = [p - imagem.inicio_frames for p in posicoes]
    cabecalho = (
        f"{len(blocos)} quadro(s) do take {take.nome}"
        + (f" (cena {take.cena}, plano {take.plano}, take {take.take})"
           if take.cena else "")
        + f", duração {take.duracao_s:.1f}s.\n"
        f"Master de imagem: {imagem.master}.\n"
        f"Os quadros estão em ordem, nos segundos "
        f"{', '.join(f'{p / float(taxa):.1f}' for p in relativo)} do take."
        + (f"\n({reaproveitados} vieram do cache.)" if reaproveitados else "")
    )
    for aviso in take.avisos:
        cabecalho += f"\n⚠ {aviso}"

    return [{"type": "text", "text": cabecalho}, *blocos]
