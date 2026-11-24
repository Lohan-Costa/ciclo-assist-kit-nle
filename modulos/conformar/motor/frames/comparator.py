"""
Relinker — Módulo Frames: Comparador Visual
Compara dois frames usando hashing perceptual (pHash via imagehash).
Retorna um score de similaridade de 0.0 (completamente diferente) a 1.0 (idênticos).

Dependências: imagehash, Pillow
"""

import logging
from pathlib import Path

log = logging.getLogger("relinker.frames.comparator")

# Threshold padrão de similaridade (distância de Hamming máxima em bits)
DEFAULT_THRESHOLD = 10  # em 64 bits totais do pHash


def compare_frames(frame_a: str, frame_b: str, threshold: int = DEFAULT_THRESHOLD) -> dict:
    """
    Compara dois frames e retorna o score de similaridade.

    Args:
        frame_a: caminho para o frame de referência (do vídeo de referência)
        frame_b: caminho para o frame candidato (da mídia bruta)
        threshold: distância máxima em bits para considerar similar

    Retorna:
        {
            "score": float,          # 0.0 a 1.0
            "hamming_distance": int, # distância em bits (0 = idênticos)
            "is_match": bool,        # True se dentro do threshold
            "threshold_used": int
        }
    """
    import imagehash
    from PIL import Image

    path_a = Path(frame_a)
    path_b = Path(frame_b)

    if not path_a.exists():
        raise FileNotFoundError(f"Frame A não encontrado: {frame_a}")
    if not path_b.exists():
        raise FileNotFoundError(f"Frame B não encontrado: {frame_b}")

    log.info("Comparando frames: %s × %s", path_a.name, path_b.name)

    img_a = Image.open(str(path_a)).convert("RGB")
    img_b = Image.open(str(path_b)).convert("RGB")

    # Detecta frames de baixo detalhe (pretos/quase uniformes): o pHash de dois
    # frames pretos dá distância ~0, gerando corroboração FALSA. Sinalizamos para
    # que o caller possa descartar a amostra. Usamos o desvio-padrão do luminance.
    import numpy as np
    LOW_DETAIL_STD = 12.0   # std de luminância (0–255) abaixo disso ≈ frame chapado
    std_a = float(np.asarray(img_a.convert("L"), dtype=np.float32).std())
    std_b = float(np.asarray(img_b.convert("L"), dtype=np.float32).std())
    low_detail = std_a < LOW_DETAIL_STD or std_b < LOW_DETAIL_STD

    hash_a = imagehash.phash(img_a)
    hash_b = imagehash.phash(img_b)

    distance = hash_a - hash_b  # distância de Hamming em bits
    max_bits = 64               # pHash usa 64 bits
    score = 1.0 - (distance / max_bits)

    is_match = distance <= threshold

    log.info(
        "Resultado: distância=%d bits, score=%.3f, match=%s low_detail=%s (std %.1f/%.1f)",
        distance, score, is_match, low_detail, std_a, std_b
    )

    return {
        "score": round(float(score), 4),
        "hamming_distance": int(distance),   # numpy.int64 → int nativo (JSON serializable)
        "is_match": bool(is_match),
        "threshold_used": int(threshold),
        "low_detail": bool(low_detail),
    }


# ── Alinhamento/diferença pixel-exato (cv2) ────────────────────────────────
# Usado no preview: snap temporal preciso (matchTemplate) e modo diferença.
# Mais preciso que o pHash quando o conteúdo é o MESMO (clipe com efeito vs ref);
# o pHash segue para o matching em massa (tolerante a codec/resolução).

def corr_score(path_a: str, path_b: str) -> float:
    """Correlação cruzada normalizada (NCC) entre dois frames (0..1, maior=melhor).

    Lê em cinza, alinha tamanhos (redimensiona b para a) e correlaciona — robusto
    para escolher o frame-fonte que mais casa com o ref no preview.
    """
    import cv2
    a = cv2.imread(str(path_a), cv2.IMREAD_GRAYSCALE)
    b = cv2.imread(str(path_b), cv2.IMREAD_GRAYSCALE)
    if a is None or b is None:
        return -1.0
    if b.shape != a.shape:
        b = cv2.resize(b, (a.shape[1], a.shape[0]), interpolation=cv2.INTER_AREA)
    try:
        res = cv2.matchTemplate(a, b, cv2.TM_CCOEFF_NORMED)
        return float(res[0][0])
    except Exception:
        return -1.0


# A composição CLIPE × REF (diferença / wipe) agora é feita ao vivo no frontend
# via <canvas> (ver renderDiffCanvas em src/main.js) — não gera mais PNG de diff.
