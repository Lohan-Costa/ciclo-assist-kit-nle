"""Extração de quadros — o que faz o Claude enxergar o material.

Não existe modelo de visão neste produto: **o Claude é o modelo de visão**, e o frame
chega a ele como conteúdo de imagem no resultado da ferramenta MCP. Este módulo só entrega
o JPEG.

## Duas decisões que valem explicar

⭐ **768 px de largura, não 4K.** O Chat Video Pro manda PNG 3840×2160 para o modelo
(medido pelo banco, `CVP_PNG_Preset`). Não copiamos: 4K por quadro estoura contexto e
custo sem melhorar a resposta a *"o que há neste plano"*. Medido aqui: 768 px sai a ~20 KB
por quadro e a cena é perfeitamente legível. Se um dia houver dúvida, é comparável — basta
rodar a mesma cena nas duas larguras.

⚠️ **O quadro é sempre contado no tempo do MASTER**, nunca no do subclipe. É o que faz o
cache servir para qualquer recorte da mesma mídia (ver `cache.py`).
"""

from __future__ import annotations

import logging
import subprocess
from fractions import Fraction
from pathlib import Path

from .. import binarios as _binarios
from . import decodificadores as _sdk

log = logging.getLogger("cicloassist.midia.frames")

LARGURA = 768
QUALIDADE = 4  # escala do ffmpeg: 2 é quase sem perda, 31 é lixo. 4 é bom e pequeno.

#: Vai no `gerador.quadros.json`. Mudou aqui, o cache antigo deixa de servir sozinho.
#:
#: ⚠️ **A FERRAMENTA não entra na receita, e é decisão.** O RAW de câmera é lido pelo SDK
#: do fabricante (`decodificadores.py`) e não pelo ffmpeg, mas a receita é *"JPEG de 768 px
#: no tempo do master"* — e os dois caminhos a cumprem. Pôr a ferramenta aqui invalidaria
#: os quadros de TODO o cache (118 mídias nesta máquina) para registrar algo que não muda
#: o que sai. É a mesma razão pela qual `busca_confiavel` troca de estratégia de ffmpeg
#: sem mexer na assinatura.
ASSINATURA = {"ferramenta": "ffmpeg", "largura": LARGURA, "qualidade": QUALIDADE}


class FfmpegAusente(RuntimeError):
    """O ffmpeg não está instalado. É pré-requisito do produto, não dependência Python."""


class ExtracaoFalhou(RuntimeError):
    """O ffmpeg rodou e não produziu quadro."""


def achar_ffmpeg() -> str:
    caminho = _binarios.achar("ffmpeg")
    if not caminho:
        raise FfmpegAusente(
            f"O ffmpeg não foi encontrado nesta máquina (procurei {_binarios.onde_procurei()}). "
            "Ele é necessário para o Ciclo Assist ver o material."
        )
    return caminho


def segundos_do_frame(frame: int, taxa: Fraction) -> float:
    """Posição de um quadro, em segundos.

    ⚠️ A divisão é racional até o fim. `frame / 23.976` acumula erro e, num clipe longo,
    entrega o quadro vizinho — o que num corte por fala é a diferença entre pegar a
    palavra e pegar o silêncio antes dela.
    """
    return float(frame / taxa)


def busca_confiavel(video: Path | str) -> bool:
    """A busca rápida deste arquivo cai no quadro certo?

    ⛔⛔ **MEDIDO em 2026-09-17** (banco, `protocolos/mxf/README.md`): nos OP-Atom MPEG-2 que
    o Media Composer gera por transcode, o `r_frame_rate` vem pela METADE do
    `avg_frame_rate`, os `pts` dos pacotes andam de dois em dois — e metade dos quadros nem
    tem `pts` —, e `-ss t` entrega **o quadro N/2**. Não é erro de borda: o quadro é de outro
    ponto do clipe, e a decupagem descreve o que o take não é.

    Sem exceção nem susto: quando a busca não é confiável, extrai-se decodificando em ordem.
    """
    try:
        from . import identidade as _identidade
        return not _identidade.sondar(video).get("busca_suspeita")
    except Exception:  # noqa: BLE001 — sem ffprobe, segue como antes
        return True


def _em_ordem(video: Path | str, posicoes: list[int], largura: int,
              qualidade: int) -> dict[int, bytes]:
    """Os quadros pedidos, decodificando do começo até o último deles. UMA passada.

    ⚠️ Custa decodificar até a última posição — dezenas de segundos num clipe longo. Por isso
    quem pede vários quadros usa `extrair_varios`, e não um `extrair` por quadro.
    """
    if not posicoes:
        return {}
    ffmpeg = achar_ffmpeg()
    expr = "+".join(f"eq(n\\,{p})" for p in sorted(set(posicoes)))
    comando = [
        ffmpeg, "-v", "error", "-i", str(video), "-an",
        "-vf", f"select={expr},scale={largura}:-2",
        "-vsync", "0", "-q:v", str(qualidade),
        # ⚠️ Sem isto o ffmpeg decodifica o arquivo INTEIRO depois do último quadro pedido
        #   — num clipe de 25 min são dezenas de segundos jogados fora por chamada.
        "-frames:v", str(len(set(posicoes))),
        "-f", "image2pipe", "-vcodec", "mjpeg", "pipe:1",
    ]
    r = subprocess.run(comando, capture_output=True, timeout=1200)
    if r.returncode != 0 or not r.stdout:
        erro = (r.stderr or b"").decode("utf-8", "replace").strip()
        raise ExtracaoFalhou(
            f"não consegui extrair {len(posicoes)} quadro(s) de {Path(video).name}"
            + (f": {erro[:300]}" if erro else ""))
    # Os JPEG saem concatenados, na ordem das posições: cada um começa em FFD8 e acaba em FFD9.
    corrente, dados = [], r.stdout
    inicio = 0
    while True:
        fim = dados.find(b"\xff\xd9", inicio)
        if fim < 0:
            break
        corrente.append(dados[inicio:fim + 2])
        inicio = fim + 2
    pedidas = sorted(set(posicoes))
    # ⚠️ Sem esta conferência, um JPEG a menos (ou a mais) deslocaria TODAS as posições
    #    seguintes: o quadro 1000 viraria o 500, sem erro nenhum — que é exatamente o
    #    defeito que este caminho existe para consertar.
    if len(corrente) < len(pedidas):
        # ⛔ E ESTOURA, em vez de devolver o que veio: quem chama cairia no `extrair` posição
        #   a posição, e num arquivo destes cada um decodifica o clipe outra vez — doze
        #   passadas para terminar falhando do mesmo jeito.
        raise ExtracaoFalhou(
            f"pedi {len(pedidas)} quadro(s) de {Path(video).name} e vieram {len(corrente)}; "
            f"o arquivo pode estar truncado")
    return dict(zip(pedidas, corrente[: len(pedidas)]))


def extrair_varios(
    video: Path | str,
    posicoes: list[int],
    taxa: Fraction,
    largura: int = LARGURA,
    qualidade: int = QUALIDADE,
) -> dict[int, bytes]:
    """Vários quadros do mesmo arquivo. Rápido quando a busca serve; em ordem quando não."""
    if _sdk.tipo_de(video):
        # ⭐ RAW de câmera: cada quadro é uma chamada ao SDK, e ele abre o clipe a cada
        #   uma. Medido no BRAW 4K: 0,13–0,18 s por quadro — não vale complicar.
        return {p: _decodificar_raw(video, p, largura) for p in posicoes}
    if busca_confiavel(video):
        return {p: extrair(video, p, taxa, largura, qualidade) for p in posicoes}
    return _em_ordem(video, posicoes, largura, qualidade)


def extrair(
    video: Path | str,
    frame_no_master: int,
    taxa: Fraction,
    largura: int = LARGURA,
    qualidade: int = QUALIDADE,
) -> bytes:
    """Um quadro do arquivo, em JPEG.

    ⚠️ `-ss` ANTES de `-i` é busca rápida (o ffmpeg pula no contêiner em vez de decodificar
    tudo até lá). Medido: 3 quadros de um DNxHD 1080p em 0,38 s. Depois do `-i` seria
    exato ao quadro mas decodificaria o clipe inteiro — e num take de 4 minutos isso
    transforma uma pergunta em uma espera.

    ⭐ **RAW de câmera não passa por aqui**: BRAW, R3D e ARRIRAW não abrem no ffmpeg, e vão
    para o decodificador do fabricante (`midia/decodificadores.py`).
    """
    if _sdk.tipo_de(video):
        return _decodificar_raw(video, frame_no_master, largura)
    if not busca_confiavel(video):
        # ⛔ Este arquivo entrega o quadro errado por busca: decodifica em ordem (ver
        #    `busca_confiavel`). Um quadro só — quem pede vários usa `extrair_varios`.
        achados = _em_ordem(video, [frame_no_master], largura, qualidade)
        if frame_no_master not in achados:
            raise ExtracaoFalhou(
                f"não consegui extrair o quadro {frame_no_master} de {Path(video).name}")
        return achados[frame_no_master]

    ffmpeg = achar_ffmpeg()
    posicao = segundos_do_frame(frame_no_master, taxa)

    comando = [
        ffmpeg,
        "-v", "error",
        "-ss", f"{posicao:.6f}",
        "-i", str(video),
        "-frames:v", "1",
        "-vf", f"scale={largura}:-2",
        "-q:v", str(qualidade),
        "-f", "image2pipe", "-vcodec", "mjpeg",
        "pipe:1",
    ]
    resultado = subprocess.run(comando, capture_output=True, timeout=120)

    if resultado.returncode != 0 or not resultado.stdout:
        erro = (resultado.stderr or b"").decode("utf-8", "replace").strip()
        raise ExtracaoFalhou(
            f"não consegui extrair o quadro {frame_no_master} de {Path(video).name}"
            + (f": {erro[:300]}" if erro else "")
        )
    return resultado.stdout


def _decodificar_raw(video: Path | str, frame: int, largura: int) -> bytes:
    """O quadro de um RAW de câmera, pelo SDK. ⚠️ `SdkIndisponivel` SOBE com a frase dele.

    ⛔ Não vira `ExtracaoFalhou`: "não consegui extrair o quadro" manda o editor procurar
    defeito no material, quando o que falta é um decodificador que ele pode instalar.
    """
    return _sdk.decodificar(video, frame, largura)


def distribuir(inicio: int, duracao: int, quantos: int) -> list[int]:
    """Quais quadros pedir dentro de um intervalo.

    ⚠️ **Nem a primeira nem a última posição.** O primeiro quadro de um take costuma ser
    a claquete ou o resto do plano anterior, e o último costuma pegar o corte. Amostrar as
    pontas faz o modelo descrever o que o take NÃO é — e ele descreveria com confiança,
    porque a imagem é real.

    Com `quantos=3` numa duração de 100, sai [25, 50, 75].
    """
    if quantos < 1 or duracao < 1:
        return []
    if quantos == 1:
        return [inicio + duracao // 2]
    passo = duracao / (quantos + 1)
    return [inicio + int(passo * (i + 1)) for i in range(quantos)]
