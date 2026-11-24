"""A MINIATURA da lista da Carta Aberta (protótipo v3.4, coluna entre o status e o tipo).

- Vídeo: um quadro do MEIO da mídia, pelo extrator do produto (`midia.frames.extrair_varios`: ele já sabe do OP-Atom
  MPEG-2 cuja busca rápida entrega o quadro N/2, e do RAW de câmera pelo SDK).
- Som: a forma de onda, preta sobre azul (o desenho do Production Manager, a referência do autor).
- Item (subclipe, multicam, nest): a miniatura da mídia de BAIXO, no ponto onde o item começa.

⛔ Guardada na pasta de DADOS desta máquina (endereçada por arquivo + tamanho + data), nunca no projeto: o projeto mora em
rede e é dos editores; a miniatura é um cache desta máquina, refeito em segundos.
⭐ No máximo duas gerações ao mesmo tempo: uma pasta de 200 mídias pediria 200 ffmpeg de uma vez.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
import threading
from fractions import Fraction
from pathlib import Path

from . import diario, itens as _itens, referencias as _refs
from .projeto import Projeto

LARGURA, ALTURA = 124, 70
_VEZ = threading.BoundedSemaphore(2)


def _pasta() -> Path:
    from ..servico import config
    return config.pasta() / "carta" / "miniaturas"


def alvo(proj: Projeto, id_: str) -> tuple[str, int, str, Fraction | None] | None:
    """(arquivo NESTA máquina, quadro, "video"|"audio", taxa) da referência ou do item `id_`; None se nada alcança."""
    from .vista import _fps, _letras_por_rotulo, traduzir
    refs = {d["id"]: d for _, d in _refs.todas(proj)}
    itens = {d["id"]: d for _, d in _itens.todos(proj)}
    quadro = None
    d = itens.get(id_)
    for _ in range(8):                                    # desce as camadas até uma mídia
        if d is None:
            break
        lugares = _itens._lugares(d)
        if not lugares:
            return None
        primeiro = next((l for l in lugares if l.get("imagem", True)), lugares[0])
        if quadro is None:
            quadro = int(d.get("entrada_q") or primeiro.get("inicio_q") or primeiro.get("entrada_q") or 0)
        if primeiro.get("midia"):
            id_ = primeiro["midia"]
            break
        d = itens.get(primeiro.get("item", ""))
    ref = refs.get(id_)
    if ref is None:
        return None
    ident = ref.get("identidade") or {}
    letras = _letras_por_rotulo()
    for f in diario.formas(proj).get(id_, []):
        c = traduzir(f, letras)
        if c and os.path.exists(c):
            if quadro is None:
                quadro = int(ident.get("quadros") or 0) // 2
            return c, quadro, "audio" if ident.get("tipo") == "audio" else "video", _fps(ident)
    return None


def gerar(arquivo: str, quadro: int, tipo: str, taxa: Fraction | None) -> bytes | None:
    """O JPEG da miniatura (do cache desta máquina, ou feito agora)."""
    try:
        st = os.stat(arquivo)
    except OSError:
        return None
    chave = hashlib.sha1(f"{arquivo}|{st.st_size}|{st.st_mtime_ns}|{quadro}|{tipo}".encode()).hexdigest()
    destino = _pasta() / f"{chave}.jpg"
    if destino.is_file():
        return destino.read_bytes()
    with _VEZ:
        if destino.is_file():
            return destino.read_bytes()
        dados = _som(arquivo) if tipo == "audio" else _video(arquivo, quadro, taxa)
        if not dados:
            return None
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".parcial")
        tmp.write_bytes(dados)
        os.replace(tmp, destino)
        return dados


def _video(arquivo: str, quadro: int, taxa: Fraction | None) -> bytes | None:
    from ..midia import frames
    try:
        return frames.extrair_varios(arquivo, [max(0, quadro)], taxa or Fraction(24000, 1001), largura=LARGURA * 2).get(max(0, quadro))
    except Exception:  # noqa: BLE001 — sem miniatura não é erro: a linha fica sem ela
        return None


def _som(arquivo: str) -> bytes | None:
    from ..midia import frames
    filtro = (f"color=c=0x1f3fd6:s={LARGURA * 2}x{ALTURA * 2}[f];"
              f"[0:a]aformat=channel_layouts=mono,showwavespic=s={LARGURA * 2}x{ALTURA * 2}:colors=0x0b0b0b:scale=cbrt[o];"
              "[f][o]overlay=format=auto")
    try:
        r = subprocess.run([frames.achar_ffmpeg(), "-v", "error", "-t", "600", "-i", arquivo, "-filter_complex", filtro,
                            "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "pipe:1"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 and r.stdout else None
