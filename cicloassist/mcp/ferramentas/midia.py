"""`ver_quadros_da_midia` — olhar um MASTER, sem passar por bin nem take.

⭐ Existe porque a decupagem em lote não tem take nenhum em mãos. A varredura do acervo
entrega **chave do master + arquivo**, e `ver_frames` precisa de `bin` + `item` — ele
resolve um subclipe dentro de uma bin, que é o caminho da CONVERSA. Aqui o caminho é o
outro: a fila de fundo percorre mídia, não bin.

⚠️ E os quadros são os MESMOS: numerados em tempo do master, no mesmo cache. Vetorizar
uma mídia já deixou 12 quadros prontos — decupá-la depois não extrai nada de novo.
"""

from __future__ import annotations

import base64
import logging
from fractions import Fraction

from ...midia import acervo as _acervo
from ...midia import cache as _cache
from ...midia import frames as _frames
from ...midia import identidade as _identidade
from ...midia import vetores as _vetores
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.midia")

#: ⭐ O teto subiu de 12 para 24 em 2026-09-22, com a densidade da aba (F3): o nível
#: `exaustivo` pede 24 quadros por mídia, e um teto abaixo do que a fila manda cortaria a
#: escolha do editor em silêncio — ele pagaria por 24 e o modelo olharia 12.
MAXIMO = 24


def quadros_de(chave: str, quantos: int = 6) -> tuple[list[bytes], list[int], dict]:
    """Os JPEG de um master, do cache quando houver. `(jpegs, posições, clipe)`.

    ⭐ Prefere o que já está em disco: a vetorização amostra 12 quadros por mídia, então
    quem já passou por ela não paga ffmpeg nenhum aqui.
    """
    midia = _cache.Midia(chave)
    clipe = (_acervo.ler().get("clipes") or {}).get(midia.chave) or {}

    guardados = midia.quadros_guardados()
    if len(guardados) >= quantos:
        # Espalha a escolha pelo material em vez de pegar os primeiros — que seriam
        # sempre o começo do plano.
        passo = len(guardados) / quantos
        posicoes = [guardados[int(i * passo)] for i in range(quantos)]
        return [midia.caminho_do_quadro(p).read_bytes() for p in posicoes], posicoes, clipe

    # Não há quadros bastantes: extrai, e guarda para a próxima.
    arquivos = (clipe.get("por_tipo") or {}).get("video") or []
    if not arquivos or not clipe.get("fps"):
        raise _vetores.ModeloIndisponivel(
            "não sei onde está a imagem dessa mídia; mande procurar a mídia primeiro"
        )

    taxa = Fraction(str(clipe["fps"]))
    duracao = int(float(clipe.get("duracao_s") or 0) * taxa)
    posicoes = _frames.distribuir(0, max(1, duracao), quantos)

    faltam = [p for p in posicoes if not midia.tem_quadro(p)]
    # ⛔⛔ Aqui havia um `try` que devolvia `[{"type": "text", …}]` — a forma de resposta da
    #    FERRAMENTA, não desta função, que devolve `(jpegs, posições, clipe)`. Quem chama
    #    desempacota três valores, e uma mídia que o ffmpeg não lê virava
    #    `ValueError: not enough values to unpack`: no chat, o modelo recebia essa frase em
    #    vez do motivo; na fila do Mac (`percepcao.decupar`), o `ValueError` não é nenhuma
    #    das exceções tratadas e derrubava a TAREFA INTEIRA — que é exatamente a regressão
    #    que a revisão de 2026-09-13 dizia ter consertado.
    #    ⭐ `extrair_varios` já levanta `ExtracaoFalhou`/`FfmpegAusente`/`OSError`, e os dois
    #    caminhos que chamam isto tratam as três: deixar subir é o conserto.
    novos = _frames.extrair_varios(arquivos[0], faltam, taxa) if faltam else {}

    jpegs = []
    saiu = []
    extraiu = False
    for i, posicao in enumerate(posicoes):
        _turno.avisar("vendo os quadros", i / max(1, len(posicoes)),
                      clipe.get("nome") or midia.chave[:12])
        if midia.tem_quadro(posicao):
            jpegs.append(midia.caminho_do_quadro(posicao).read_bytes())
        else:
            jpeg = novos.get(posicao) or _frames.extrair(arquivos[0], posicao, taxa)
            midia.guardar_quadro(posicao, jpeg)
            jpegs.append(jpeg)
            extraiu = True
        saiu.append(posicao)

    # ⛔ Revisão de 2026-09-13: os quadros eram guardados SEM a receita, e o inventário lê
    #    "quadro sem receita" como "a refazer". Com 7 mídias decupadas passava batido; a
    #    decupagem no Mac fez 165 aparecerem "↻ a refazer" na aba Vetores, todas feitas com
    #    a receita de hoje. ⚠️ Só onde não há receita nenhuma: se há outra, os quadros velhos
    #    continuam sendo de outra receita, e carimbar a de hoje esconderia isso.
    if extraiu and not midia.ler_gerador("quadros"):
        midia.registrar_gerador("quadros", dict(_frames.ASSINATURA))
    return jpegs, saiu, clipe


#: ⭐ Os quadros da CABEÇA do take, para ler a claquete. MEDIDO em 2026-09-22 no acervo do
#: editor: a 768 px (a receita dos quadros) uma claquete que enche o quadro é legível, mas a
#: segurada longe da câmera num plano aberto vira mancha; a 1568 px lê-se rolo, cena e
#: plano. E a amostragem normal EVITA as pontas de propósito (`frames.distribuir`) — é
#: exatamente onde a claquete está.
SEGUNDOS_DA_CABECA = (1.0, 3.0)
LARGURA_DA_CABECA = 1568


def quadros_da_cabeca(chave: str) -> tuple[list[bytes], list[float]]:
    """JPEGs do começo do take em resolução maior — `([], [])` quando não dá.

    ⚠️ NÃO vão para o cache de quadros: a receita de lá é 768 px (`frames.ASSINATURA`), e
    misturar faria a aba Vetores ver quadros de outra receita.
    """
    try:
        midia = _cache.Midia(chave)
    except _cache.ChaveInvalida:
        return [], []
    clipe = (_acervo.ler().get("clipes") or {}).get(midia.chave) or {}
    arquivos = list((clipe.get("por_tipo") or {}).get("video") or [])
    fps, duracao = clipe.get("fps"), float(clipe.get("duracao_s") or 0)
    if not arquivos:
        # A entrada do Premiere não está no acervo do Avid: o arquivo vem do manifesto.
        for a in midia.manifesto().get("arquivos") or []:
            try:
                sonda = _identidade.sondar(a)
            except _identidade.IdentidadeErro:
                continue
            if sonda.get("tipo") == "video":
                arquivos, fps = [a], sonda.get("fps")
                duracao = float(sonda.get("duracao_s") or 0)
                break
    if not arquivos or not fps:
        return [], []
    taxa = Fraction(str(fps))
    segundos = [s for s in SEGUNDOS_DA_CABECA if not duracao or s < duracao] or \
        [duracao * 0.3]
    posicoes = [int(s * taxa) for s in segundos]
    try:
        feitos = _frames.extrair_varios(arquivos[0], posicoes, taxa,
                                        largura=LARGURA_DA_CABECA)
    except (_frames.FfmpegAusente, _frames.ExtracaoFalhou, OSError) as e:
        log.info("sem os quadros da cabeça de %s (%s)", chave[:12], e)
        return [], []
    saida = [(feitos[p], s) for p, s in zip(posicoes, segundos) if feitos.get(p)]
    return [j for j, _ in saida], [s for _, s in saida]


@ferramenta(
    nome="ver_quadros_da_midia",
    descricao=(
        "Extrai quadros de uma MÍDIA do acervo pela chave dela (não por bin/take) e os "
        "devolve como IMAGENS. Use quando o pedido vier com a chave de uma mídia, como "
        "na decupagem em lote. Para um take de uma bin, use ver_frames."
    ),
    esquema={
        "type": "object",
        "properties": {
            "chave": {"type": "string",
                      "description": "A chave da mídia (64 hexadecimais)."},
            "quantos": {"type": "integer",
                        "description": f"Quantos quadros, de 1 a {MAXIMO}. Padrão 6.",
                        "default": 6},
            "claquete": {"type": "boolean",
                         "description": "Acrescenta 2 quadros da CABEÇA do take em "
                                        "resolução maior, para ler a claquete.",
                         "default": False},
        },
        "required": ["chave"],
    },
    escreve=False,
    nles=AMBOS,
)
def ver_quadros_da_midia(chave: str, quantos: int = 6,
                         claquete: bool = False) -> list[dict]:
    quantos = max(1, min(int(quantos or 6), MAXIMO))
    try:
        jpegs, posicoes, clipe = quadros_de(chave, quantos)
    except (_cache.ChaveInvalida, _vetores.ModeloIndisponivel, OSError,
            _frames.FfmpegAusente, _frames.ExtracaoFalhou, ValueError) as e:
        return [{"type": "text", "text": f"Não consegui ver essa mídia: {e}"}]

    taxa = Fraction(str(clipe.get("fps") or "25"))
    # ⚠️ O texto vem ANTES das imagens: sem ele o modelo recebe fotos soltas e não sabe de
    #    que material são, nem em que ordem, nem quanto tempo as separa.
    cabecalho = (
        f"{len(jpegs)} quadro(s) da mídia {clipe.get('nome') or chave[:12]}"
        + (f", duração {float(clipe['duracao_s']):.1f}s" if clipe.get("duracao_s") else "")
        + ".\nOs quadros estão em ordem, nos segundos "
        + ", ".join(f"{p / float(taxa):.1f}" for p in posicoes)
        + " do material."
    )
    def _imagens(lista):
        return [{"type": "image", "data": base64.b64encode(j).decode("ascii"),
                 "mimeType": "image/jpeg"} for j in lista]

    blocos: list[dict] = []
    # ⛔⛔ A CABEÇA vai PRIMEIRO, e é a ordem do tempo. MEDIDO no outro motor (o Qwen do
    #    Mac, `motor/micro.py`, 2026-09-22): com ela no fim do pedido, o modelo narrou
    #    "a claquete é mostrada novamente no final" — ele lê a sequência de imagens como a
    #    sequência do material. ⚠️ Aqui cada grupo vem com o seu texto antes, o que já
    #    desfaz a ambiguidade; a ordem certa é de graça e a leitura pelo Claude NÃO foi
    #    medida, então ela segue a regra que o outro motor pagou para aprender.
    if claquete:
        cabeca, segundos = quadros_da_cabeca(chave)
        if cabeca:
            blocos.append({"type": "text", "text": (
                "CABEÇA do take (o começo dele), em resolução maior, para ler a claquete — "
                "segundos " + ", ".join(f"{s:.1f}" for s in segundos) + ".")})
            blocos += _imagens(cabeca)
    blocos.append({"type": "text", "text": cabecalho})
    blocos += _imagens(jpegs)
    return blocos
