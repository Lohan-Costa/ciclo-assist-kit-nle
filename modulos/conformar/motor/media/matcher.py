"""
Relinker — Motor de Matching (Fase 2)
Correlaciona segmentos extraídos do AAF com arquivos de mídia reais
via cascata de quatro estágios:

  1. Path exact   — local_path do AAF existe no índice (arquivo no lugar original)
  2. UID          — mob_id do AAF vs unique_id extraído por pymediainfo
  3. Nome         — clip_name/mob_name vs filename sem extensão (fuzzy + token sort)
  4. Visual pHash — frame do vídeo de referência vs frame do candidato

Cada estágio é tentado apenas se os anteriores falharem (ou produzirem
baixa confiança). O resultado é um MatchResult por segmento com o
melhor candidato, método usado e confiança.

Dependências: difflib (stdlib), frames.extractor, frames.comparator
"""

from __future__ import annotations

import logging
import os
import re
import time
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

log = logging.getLogger("relinker.media.matcher")

# ── Opções padrão ─────────────────────────────────────────────────────────

DEFAULT_OPTIONS: dict = {
    # Score mínimo de nome para aceitar como match (sem confirmação visual)
    "fuzzy_threshold": 0.70,
    # Score de nome acima do qual o match é aceito sem verificação visual
    "visual_skip_threshold": 0.90,
    # Distância de Hamming MÉDIA máxima (multi-frame) para aceitar um match visual.
    # Mais rígido que antes (era 10): um frame único coincidente não basta — a
    # MÉDIA das amostras precisa ser baixa. 0=idêntico, 64=completamente diferente.
    "visual_hamming_threshold": 6,
    # Distância por-frame que conta como "concorda" (usada no quórum de consistência).
    "visual_agree_dist": 8,
    # Fração mínima de amostras que precisam concordar (≤ agree_dist) para aceitar.
    "visual_min_agree": 0.75,
    # Quantos frames amostrar ao longo do segmento para corroboração.
    "visual_samples": 4,
    # Número de frames a avançar dentro do clipe antes de extrair para comparação
    # (evita edge cases em cortes; aplicado tanto no ref_video quanto no candidato)
    "visual_frame_offset": 5,
    # Número máximo de candidatos retornados por segmento
    "max_candidates": 5,
    # Usar visual como fallback quando fuzzy é ambíguo (requer ref_video)
    "visual_fallback": True,
    # TC do primeiro frame do vídeo de referência (padrão: início do vídeo)
    "ref_tc_start": "00:00:00:00",
    # ── Portão de duração (determinístico) ────────────────────────────────
    # A duração-fonte do AAF (media_ref.source_duration_secs) é comparada com a
    # duração do arquivo candidato. Mismatch → candidato reprovado. Tolerância =
    # max(abs, rel × duração) para absorver diferenças de container/fps.
    "duration_tol_secs": 0.3,
    "duration_tol_rel": 0.01,
    # Máx. de candidatos a testar visualmente (após o portão de duração).
    "visual_max_candidates": 8,
    # ── Busca de offset temporal (mídia com frame 0 deslocado: TC zerado/recorte) ──
    # Quando o score no seek esperado é baixo, varre offsets p/ achar o alinhamento
    # real por IMAGEM (desambigua o que o TC sozinho não distingue). Só no fallback
    # (1 mídia deslocada); o tiebreak multi-candidato fica conservador (janela/humano).
    "offset_search": True,
    "offset_search_max_secs": 120,   # janela máx. de varredura (cada direção)
    "offset_search_probes": 60,      # nº de sondas grossas (1 frame cada)
}


# ── Estruturas de saída ───────────────────────────────────────────────────

@dataclass
class MatchResult:
    """Resultado do matching para um segmento (ou alternate)."""
    segment_index: int
    segment: dict

    matched_path: Optional[str]      # path absoluto do arquivo matched (None se não resolvido)
    match_method: str                # 'path'|'uid'|'exact_name'|'fuzzy_name'|'visual'|'unresolved'
    confidence: float                # 0.0–1.0

    candidates: list[dict]           # top candidatos com scores, ordenados por score desc
    visual_score: Optional[float] = None   # score pHash se visual foi executado

    # Ambiguidade: ≥2 candidatos empataram por nome E duração e o visual não desempatou
    # (ou não havia ref). Vai para revisão — o humano escolhe entre os `candidates`.
    ambiguous: bool = False
    # Verificado por imagem: o desempate visual escolheu este candidato com confiança.
    verified: bool = False

    # Matching das câmeras alternativas (Group Clip)
    alternate_matches: list[dict] = field(default_factory=list)

    # Sequência de imagem (1 arquivo = 1 frame), quando matched_path é representativo
    # de uma sequência. Preenchido em match_segments a partir do índice. None = arquivo único.
    sequence: Optional[dict] = None

    # Correção de offset temporal (frames) achada pela busca visual quando o frame 0
    # do arquivo casado está deslocado vs o que o AAF assume (TC zerado / recorte de
    # cabeça). O frame real da fonte = source_start_frames + source_offset_correction.
    # Usado p/ alinhar o preview/export/janela de desempate. 0 = sem deslocamento.
    source_offset_correction: int = 0

    # As notas da confirmação pelo daily ({candidato: semelhança}), quando houve empate: a janela de conflito mostra.
    imagem: Optional[dict] = None

    def to_dict(self) -> dict:
        return {
            "segment_index": self.segment_index,
            "matched_path": self.matched_path,
            "match_method": self.match_method,
            "confidence": round(self.confidence, 4),
            "candidates": self.candidates,
            "visual_score": self.visual_score,
            "ambiguous": self.ambiguous,
            "verified": self.verified,
            "alternate_matches": self.alternate_matches,
            "sequence": self.sequence,
            "source_offset_correction": self.source_offset_correction,
            "imagem": self.imagem,
        }


# ── Funções utilitárias ───────────────────────────────────────────────────

# Sufixos que o Avid acrescenta ao nome do clipe e que NÃO existem no arquivo
# original em disco. Empilham (ex: '04 Dark Drone.wav.new.01', 'A001_…_C002.sync.01').
# Removidos iterativamente antes de comparar nomes.
_AVID_NAME_SUFFIX_RE = re.compile(r"\.(sync|new|cds|copy|sub|grp|exported)$", re.IGNORECASE)
_MEDIA_EXT_RE = re.compile(
    r"\.(mxf|mov|mp4|m4v|wav|aif|aiff|flac|mts|mp3|mxf|r3d|braw)$", re.IGNORECASE
)
_TRAILING_COUNTER_RE = re.compile(r"\.\d{1,3}$")   # contador de export/versão: '.01'


def _strip_avid_suffixes(name: str) -> str:
    """Remove extensões de mídia e sufixos do Avid (.sync/.new/.NN) empilhados.

    'A001_…_C002.sync.01' → 'A001_…_C002'
    '04 Dark Drone.wav.new.01' → '04 Dark Drone'
    """
    prev = None
    while name != prev:
        prev = name
        name = _TRAILING_COUNTER_RE.sub("", name)
        name = _AVID_NAME_SUFFIX_RE.sub("", name)
        name = _MEDIA_EXT_RE.sub("", name)
    return name


def _normalize_name(name: str) -> str:
    """
    Normaliza um nome para comparação insensível a maiúsculas,
    acentos, separadores e sufixos do Avid (.sync/.new/extensão).

    'CAM_A.mxf' → 'cam a'
    'Câmera_Principal-01' → 'camera principal 01'
    'A001_…_C002.sync.01' → 'a001 … c002'
    """
    if not name:
        return ""
    # Remove sufixos do Avid e extensões antes de quebrar separadores
    name = _strip_avid_suffixes(name)
    # Strip acentos via NFKD
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_name = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Minúsculas
    ascii_name = ascii_name.lower()
    # Separadores → espaço. Inclui ';' e ':' porque o mesmo arquivo circula com nomes de TIMECODE
    # diferentes (ex.: música '17;25;16 Cordas.wav' numa cópia e '17_25_16 Cordas.wav' noutra) — sem
    # normalizar ';'/':' os dois não casam e a mídia entra offline. ⛔ CORRIGE (2026-10-25): NÃO é o Avid que
    # troca: o link do MC 25.12 mantém o ';' (laboratório `nomes_audio`); no PRODUCAO-A as duas CÓPIAS dos WAV
    # do Pro Tools já tinham nomes diferentes no disco (a do editor com '_', a do acervo com ';').
    ascii_name = re.sub(r"[\._\-/\\;:]+", " ", ascii_name)
    # Colapsa espaços
    ascii_name = " ".join(ascii_name.split())
    return ascii_name


def _nome_do_arquivo(f: dict) -> str:
    """O nome de um arquivo do índice para casar: o nome sem extensão, ou o NOME-BASE quando ele representa uma SEQUÊNCIA
    de imagens (`A003C001.1641600.dpx` → `A003C001`; laboratório BL08, P10, 2026-11-22: o daily `.mov` não casava com a
    pasta de DPX porque o nome comparado era o do 1º quadro)."""
    seq = f.get("sequence") or {}
    return seq.get("base") or Path(f.get("filename") or "").stem


def _token_sort_ratio(a: str, b: str) -> float:
    """
    Score de similaridade após ordenar tokens (equivalente ao
    rapidfuzz.fuzz.token_sort_ratio, usando apenas stdlib).

    Lida melhor com nomes que têm partes reordenadas:
      'CAM A EXTERIOR' vs 'EXTERIOR CAM A' → 1.0
    """
    a_sorted = " ".join(sorted(a.split()))
    b_sorted = " ".join(sorted(b.split()))
    return SequenceMatcher(None, a_sorted, b_sorted).ratio()


def _normalize_uid(uid: str) -> str:
    """Normaliza UID removendo hífens, espaços e forçando minúsculas."""
    return re.sub(r"[\s\-{}]", "", uid).lower()


def _has_significant_token_overlap(a: str, b: str, min_len: int = 4) -> bool:
    """
    Retorna True se ao menos 1 token significativo for compartilhado entre a e b.

    Previne falsos positivos: similaridade de caracteres entre nomes que diferem
    apenas em dígitos (ex: A004_... vs A002_...).

    Regras:
    1. Strings normalizadas idênticas → True (match óbvio, mesmo com tokens curtos)
    2. Pelo menos uma das strings tem tokens len≥min_len → exige interseção desses
    3. Nenhuma das strings tem tokens len≥min_len → aceita overlap de qualquer token

    Exemplos:
      'a004 03170917 c003' vs 'a002 03170813 c004' → False (tokens longos divergem)
      'a004 03170917 c003' vs 'a004 03170917 c003' → True  (idênticas)
      'cam a'              vs 'cam a'              → True  (idênticas, regra 1)
      'cam a exterior'     vs 'exterior cam a'     → True  (token 'exterior' shared)
    """
    if a == b:
        return True
    ta = {t for t in a.split() if len(t) >= min_len}
    tb = {t for t in b.split() if len(t) >= min_len}
    if ta or tb:
        # Ao menos uma das strings tem tokens longos: exige interseção entre eles
        return bool(ta & tb)
    # Ambas têm apenas tokens curtos: fallback para overlap geral
    return bool(set(a.split()) & set(b.split()))


def _candidate_dict(file: dict, score: float, method: str) -> dict:
    """Cria um dict de candidato padronizado."""
    return {
        "path": file["path"],
        "filename": file["filename"],
        "score": round(score, 4),
        "method": method,
        "duration_ms": file.get("duration_ms"),
        "frame_rate": file.get("frame_rate"),
        "uid": file.get("uid"),
    }


def _frames_to_tc(frames: int, fps: float) -> str:
    """Converte frames absolutos para HH:MM:SS:FF."""
    fps_int = round(fps)
    ff = frames % fps_int
    ss = (frames // fps_int) % 60
    mm = (frames // fps_int // 60) % 60
    hh = frames // fps_int // 3600
    return f"{hh:02d}:{mm:02d}:{ss:02d}:{ff:02d}"


def _tc_to_seconds(tc: str, fps: float) -> float:
    """Converte HH:MM:SS:FF (non-drop, frames nominais) para segundos reais de seek.

    Frames nominais (round(fps)) ÷ taxa real — consistente com _frames_to_tc e o
    extractor; evita drift proporcional ao tempo em fps fracionário (23.976).
    """
    parts = tc.replace(";", ":").split(":")
    if len(parts) != 4:
        return 0.0
    hh, mm, ss, ff = int(parts[0]), int(parts[1]), int(parts[2]), int(parts[3])
    fps_int = round(fps) or 1
    total_frames = ((hh * 60 + mm) * 60 + ss) * fps_int + ff
    return total_frames / (fps if fps else fps_int)


# ── Portão de duração ──────────────────────────────────────────────────────

def _candidate_secs(file: dict) -> Optional[float]:
    """Duração do arquivo candidato em segundos (a partir de duration_ms)."""
    dur_ms = file.get("duration_ms")
    try:
        return float(dur_ms) / 1000.0 if dur_ms else None
    except (TypeError, ValueError):
        return None


def _seg_source_secs(seg: dict) -> Optional[float]:
    """Duração da mídia-fonte do segmento (do AAF), em segundos."""
    mr = seg.get("media_ref") or {}
    s = mr.get("source_duration_secs")
    try:
        return float(s) if s else None
    except (TypeError, ValueError):
        return None


def _duration_ok(seg: dict, file: dict, opts: dict) -> Optional[bool]:
    """
    Portão determinístico de duração: a duração-fonte do segmento (do AAF) deve
    bater com a duração do arquivo candidato.

    Retorna:
        True  — durações compatíveis dentro da tolerância
        False — durações divergem → candidato REPROVADO
        None  — falta duração de um dos lados → portão neutro (não reprova)
    """
    seg_secs  = _seg_source_secs(seg)
    cand_secs = _candidate_secs(file)
    if not seg_secs or not cand_secs:
        return None
    tol = max(opts.get("duration_tol_secs", 0.3),
              opts.get("duration_tol_rel", 0.01) * seg_secs)
    return abs(seg_secs - cand_secs) <= tol


# ── Estágio 3: score de candidatos por nome ───────────────────────────────

def _score_files_by_name(
    clip_name: str,
    mob_name: str,
    files: list[dict],
    max_candidates: int,
) -> list[tuple[float, dict]]:
    """
    Calcula score de similaridade de nome para cada arquivo no índice.

    Usa o melhor score entre clip_name e mob_name vs filename, com a seguinte
    prioridade:
    - clip_name  = nome do MasterMob/timeline clip (nome visível no bin do Avid)
    - mob_name   = nome do SourceMob ImportDescriptor (arquivo físico no AAF)

    O mob_name recebe uma penalidade de 20% quando clip_name é informativo
    (≥ 2 tokens), pois pode estar corrompido (ex: proxy mal-nomeado quando TC
    foi zerado no Avid). Isso previne que mob_name produza score 1.0 e decrete
    exact_name incorretamente.

    Retorna lista ordenada por score descendente.
    """
    norm_clip = _normalize_name(clip_name)
    norm_mob  = _normalize_name(mob_name)

    # clip_name "informativo": tem ao menos 2 tokens (ex: 'a004 03170917 c003')
    # vs genérico: 1 token (ex: 'sblend v2', 'motion control')
    clip_is_informative = len(norm_clip.split()) >= 2

    scored: list[tuple[float, dict]] = []

    for f in files:
        stem = _nome_do_arquivo(f)        # nome sem extensão
        norm_file = _normalize_name(stem)
        if not norm_file:
            continue

        score_clip = _token_sort_ratio(norm_clip, norm_file) if norm_clip else 0.0
        score_mob  = _token_sort_ratio(norm_mob,  norm_file) if norm_mob  else 0.0

        if clip_is_informative:
            # Penaliza mob_name: mesmo que seja 1.0, resulta em 0.80
            # → nunca pode produzir exact_name sozinho (threshold = 1.0)
            score = max(score_clip, score_mob * 0.8)
        else:
            # clip_name genérico: usa mob_name livremente como fallback
            score = max(score_clip, score_mob)

        if score > 0.0:
            scored.append((score, f))

    scored.sort(key=lambda x: -x[0])
    return scored[:max_candidates]


# ── Estágio 4: visual pHash ───────────────────────────────────────────────

def _cand_seek_frame(
    source_start_frames: int,
    timeline_off: int,
    duration_frames: int,
    speed_ratio: float,
    motion_effect_type: Optional[str],
    phase_offset: int,
    source_offset_map: Optional[list] = None,
) -> int:
    """Mapeia um offset de timeline (frames desde o início do segmento) para o
    frame correspondente na fonte, considerando o efeito de velocidade.

    Quando o segmento traz `source_offset_map` (o mapa timeline→fonte que o Avid
    já integrou — cobre rampa, constante, freeze e reverse), interpola direto nele.
    Caso contrário, cai no cálculo por speed_ratio (constante) / freeze / reverse.
    """
    if source_offset_map:
        return source_start_frames + int(round(_interp_map(source_offset_map, timeline_off)))
    me = motion_effect_type or 'constant'
    if me == 'freeze':
        return source_start_frames + phase_offset
    if me == 'reverse':
        return source_start_frames + max(0, duration_frames - timeline_off)
    # speed_ratio = SpeedRatio do Avid = tl/src (frames de timeline por frame de fonte).
    # A fonte avança 1/speed_ratio por frame de timeline (ex.: clipe 23.976 numa TL 29.97
    # tem SpeedRatio 1.25 e a fonte avança 0.8 frame/frame). DIVIDE, não multiplica.
    sr = speed_ratio if speed_ratio > 0 else 1.0
    return source_start_frames + int(round(timeline_off / sr))


def _interp_map(points: list, x: float) -> float:
    """Interpolação linear de y em x sobre uma lista [(x, y)] ordenada por x.

    Clampa nas extremidades. Usado para o offset map (timeline→fonte) do MotionEffect.
    """
    if not points:
        return x
    if x <= points[0][0]:
        return points[0][1]
    if x >= points[-1][0]:
        return points[-1][1]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        if x <= x1:
            if x1 == x0:
                return y0
            t = (x - x0) / (x1 - x0)
            return y0 + (y1 - y0) * t
    return points[-1][1]


# Categorias de efeito que alteram a imagem e NÃO sabemos reproduzir → o match
# visual fica não-conclusivo (não penaliza; confia em duração+nome). Ver
# memória visual-match-safety.
_UNREPRODUCIBLE_IMAGE_CATEGORIES = {"color", "animate", "mask"}

# A posição do 3DWarp do Avid é em MILÉSIMOS do frame (1000 = largura/altura
# inteira), NÃO em pixels — derivado por template matching pixel-exato:
#   Tx(px) = pos_x * W/1000 ;  Ty(px, p/ baixo) = -pos_y * H/1000
# Logo o deslocamento como FRAÇÃO do frame é pos/1000 — resolution-independent.
_AVID_POS_UNIT = 1000.0


def _geometric_vf(effects: Optional[list]) -> Optional[str]:
    """Filtro ffmpeg que reproduz um efeito geométrico (3DWarp/SBlend) no frame
    do candidato, para alinhar com o ref_video (que tem o efeito queimado).

    Suporta punch-in (scale ≥ 1) com position. scale<1 (PiP sobre fundo) não é
    reproduzível de forma confiável → None. Calibrado (pixel-exato) contra o MC 2021:
    posição em milésimos do frame → deslocamento = pos/1000 da dimensão.
    """
    for e in (effects or []):
        if e.get("category") != "geometric" or not e.get("reproducible"):
            continue
        p = e.get("params") or {}
        sx = p.get("scale_x") or p.get("scale_y") or 1.0
        sy = p.get("scale_y") or sx
        px = float(p.get("pos_x", 0.0) or 0.0)
        py = float(p.get("pos_y", 0.0) or 0.0)
        # Efeito praticamente nulo → não vale transformar.
        if abs(sx - 1.0) < 1e-3 and abs(sy - 1.0) < 1e-3 and abs(px) < 1 and abs(py) < 1:
            return None
        # scale<1 (imagem encolhe sobre fundo) não é reproduzível só com crop.
        if sx < 1.0 or sy < 1.0:
            return None
        pxf = px / _AVID_POS_UNIT     # fração do frame (pos em milésimos)
        pyf = py / _AVID_POS_UNIT
        cw = f"iw/{sx}"
        ch = f"ih/{sy}"
        # Sinal explícito p/ evitar '+-'/'--' nas expressões. x: imagem desloca pra
        # direita com pos_x>0 (janela de crop pra esquerda); y: pos_y<0 = pra baixo.
        x = f"(iw-{cw})/2-({pxf})*({cw})"
        y = f"(ih-{ch})/2+({pyf})*({ch})"
        # Sem vírgulas nas expressões (separador de filtro do -vf).
        return f"scale=iw*{sx}:ih*{sy},crop={cw}:{ch}:{x}:{y}"
    return None


def _try_visual_match(
    timeline_tc_in: str,
    source_start_frames: int,
    source_fps: float,
    candidate_path: str,
    ref_video: str,
    ref_tc_start: str,
    frame_offset: int,
    hamming_threshold: int,
    duration_frames: int = 0,
    n_samples: int = 4,
    agree_dist: int = 8,
    min_agree: float = 0.75,
    speed_ratio: float = 1.0,
    motion_effect_type: Optional[str] = None,
    phase_offset: int = 0,
    source_offset_map: Optional[list] = None,
    effects: Optional[list] = None,
    cand_fps: Optional[float] = None,
) -> Optional[float]:
    """
    Corroboração visual MULTI-FRAME: amostra vários frames ao longo do segmento,
    compara cada par (ref × candidato) por pHash e agrega.

    Um único frame coincidentemente próximo NÃO basta — exigimos que a MÉDIA das
    distâncias seja baixa E que um quórum das amostras concorde. Isso elimina os
    falsos-positivos em que duas cenas diferentes têm um par de frames parecido.

    Retorna o score agregado (0.0–1.0), já penalizado por inconsistência, ou None
    se nenhuma amostra pôde ser extraída/comparada. O caller aplica o threshold.
    """
    from frames.extractor import extract_frame
    from frames.comparator import compare_frames

    # Efeito que altera a imagem e não sabemos reproduzir (cor/animate/máscara):
    # o frame do candidato (limpo) nunca casaria com o ref (com efeito queimado).
    # Retorna não-conclusivo para não gerar falso-negativo — confia em duração+nome.
    for e in (effects or []):
        if e.get("category") in _UNREPRODUCIBLE_IMAGE_CATEGORIES:
            log.debug("Visual pulado: efeito não-reproduzível '%s'", e.get("name"))
            return None

    # Efeito geométrico reproduzível (3DWarp/SBlend): aplica a mesma transformação
    # ao frame do candidato para alinhar com o ref_video.
    cand_vf = _geometric_vf(effects)

    fps = source_fps               # domínio da TIMELINE (ref_video, timeline_tc)
    cfps = cand_fps or fps         # domínio da FONTE (mídia casada) — pode diferir (23.976 vs 29.97)
    ref_offset_secs = _tc_to_seconds(ref_tc_start, fps)
    base_secs = _tc_to_seconds(timeline_tc_in, fps) - ref_offset_secs

    # Offsets (em frames desde o início do segmento) distribuídos no interior do
    # clipe, evitando as bordas (cortes/transições). Fallback para frame_offset
    # quando a duração é desconhecida/curta.
    dur = max(1, int(duration_frames or 0))
    if dur <= 2 or n_samples <= 1:
        offsets = [max(0, frame_offset)]
    else:
        fracs = [(i + 1) / (n_samples + 1) for i in range(n_samples)]  # ex: .2 .4 .6 .8
        offsets = sorted({max(1, min(dur - 1, int(round(dur * f)))) for f in fracs})

    distances: list[int] = []
    for off in offsets:
        ref_secs = base_secs + off / fps
        if ref_secs < 0:
            ref_secs = 0.0
        ref_tc = _frames_to_tc(round(ref_secs * fps), fps)
        cand_frames = _cand_seek_frame(
            source_start_frames, off, dur, speed_ratio, motion_effect_type, phase_offset,
            source_offset_map,
        )
        cand_tc = _frames_to_tc(max(0, cand_frames), cfps)   # frames da FONTE → TC na fps da fonte

        ref_fp = cand_fp = None
        try:
            # Seek rápido (accurate=False): matching visual tolera; ~10x mais barato.
            ref_fp = extract_frame(ref_video, ref_tc, fps, accurate=False)["frame_path"]
            cand_fp = extract_frame(candidate_path, cand_tc, cfps, accurate=False, vf=cand_vf)["frame_path"]
            cmp = compare_frames(ref_fp, cand_fp, hamming_threshold)
            # Descarta frames pretos/uniformes: colidem no pHash (distância ~0) e
            # produziriam corroboração falsa. Não contam como amostra.
            if cmp.get("low_detail"):
                log.debug("Visual sample descartada (baixo detalhe) @ off=%d", off)
            else:
                distances.append(int(cmp["hamming_distance"]))
        except Exception as e:
            log.debug("Visual sample falhou (%s @ off=%d): %s", Path(candidate_path).name, off, e)
        finally:
            for p in (ref_fp, cand_fp):
                if p:
                    try:
                        os.unlink(p)
                    except OSError:
                        pass

    if not distances:
        return None

    mean_d = sum(distances) / len(distances)
    agree = sum(1 for d in distances if d <= agree_dist) / len(distances)
    score = 1.0 - mean_d / 64.0

    # Penaliza: (a) quórum de concordância não atingido OU (b) poucas amostras
    # válidas (após descartar frames pretos) — para não recair no "frame único".
    min_valid = 3 if n_samples >= 4 else 1
    if agree < min_agree or len(distances) < min_valid:
        score = min(score, 0.5)

    log.info(
        "Visual %s: dists=%s mean=%.1f agree=%.0f%% score=%.3f",
        Path(candidate_path).name, distances, mean_d, agree * 100, score,
    )
    return float(score)


def _visual_score_at(seg: dict, cand_file: dict, ref_video: str, opts: dict,
                     extra_off: int = 0) -> Optional[float]:
    """Score visual (pHash multi-frame) de UM candidato, deslocando o seek da fonte
    por `extra_off` frames (p/ a busca de offset). extra_off=0 = comportamento normal."""
    return _try_visual_match(
        timeline_tc_in=seg.get("timeline_tc_in", "00:00:00:00"),
        source_start_frames=(seg.get("source_start_frames", 0) or 0) + extra_off,
        source_fps=seg.get("source_fps", 25.0),
        candidate_path=cand_file["path"],
        ref_video=ref_video,
        ref_tc_start=opts["ref_tc_start"],
        frame_offset=opts["visual_frame_offset"],
        hamming_threshold=opts["visual_hamming_threshold"],
        duration_frames=seg.get("duration_frames", 0) or 0,
        n_samples=opts["visual_samples"],
        agree_dist=opts["visual_agree_dist"],
        min_agree=opts["visual_min_agree"],
        speed_ratio=seg.get("speed_ratio", 1.0) or 1.0,
        motion_effect_type=seg.get("motion_effect_type"),
        phase_offset=seg.get("phase_offset", 0) or 0,
        source_offset_map=seg.get("source_offset_map") or [],
        effects=seg.get("effects") or [],
        # fps NATIVA do SourceMob do AAF — domínio em que o frame de fonte vive (≠ timeline
        # e ≠ arquivo online; ex.: offline 29.97 conformado, online 23.976). O ffmpeg busca
        # o online por TEMPO, então a fps do arquivo online não importa pro seek.
        cand_fps=(seg.get("media_ref") or {}).get("source_fps"),
    )


def _visual_score_for(seg: dict, cand_file: dict, ref_video: str, opts: dict) -> Optional[float]:
    """Score visual no seek esperado (extra_off=0). Reusado no desempate de ambiguidade
    (que fica conservador — sem busca de offset, p/ não deslizar um clipe errado)."""
    return _visual_score_at(seg, cand_file, ref_video, opts, 0)


def _coarse_align_offset(seg: dict, cand_file: dict, ref_video: str, opts: dict) -> Optional[int]:
    """Varredura GROSSA (1 frame) p/ achar o offset de fonte que melhor alinha o
    candidato ao REF, quando o frame 0 do arquivo está deslocado (TC zerado/recorte).

    Fixa um frame do REF no meio do clipe e desliza só o candidato. Devolve o offset
    (frames) de menor distância pHash, ou None. É só o chute grosso — o chamador
    confirma com o score multi-frame estrito.
    """
    from frames.extractor import extract_frame
    from frames.comparator import compare_frames
    fps = seg.get("source_fps") or 25.0
    dur = max(1, int(seg.get("duration_frames") or 0))
    src_start = int(seg.get("source_start_frames") or 0)
    cand_dur_f = int(round((_candidate_secs(cand_file) or 0) * fps))
    mid = dur // 2

    ref_offset_secs = _tc_to_seconds(opts["ref_tc_start"], fps)
    base_secs = _tc_to_seconds(seg.get("timeline_tc_in", "00:00:00:00"), fps) - ref_offset_secs
    ref_secs = max(0.0, base_secs + mid / fps)
    ref_tc = _frames_to_tc(round(ref_secs * fps), fps)
    cand_vf = _geometric_vf(seg.get("effects"))

    cap = int(opts.get("offset_search_max_secs", 120) * fps)
    window = min(cap, cand_dur_f) if cand_dur_f else cap
    n_probes = max(8, int(opts.get("offset_search_probes", 60)))
    step = max(1, window // n_probes)

    ref_fp = None
    best_off, best_d = None, 65
    try:
        ref_fp = extract_frame(ref_video, ref_tc, fps, accurate=False)["frame_path"]
        for off in range(-window, window + 1, step):
            cf = src_start + mid + off
            if cf < 0 or (cand_dur_f and cf >= cand_dur_f):
                continue
            cand_fp = None
            try:
                cand_fp = extract_frame(cand_file["path"], _frames_to_tc(cf, fps), fps,
                                        accurate=False, vf=cand_vf)["frame_path"]
                cmp = compare_frames(ref_fp, cand_fp, opts["visual_hamming_threshold"])
                d = 65 if cmp.get("low_detail") else int(cmp["hamming_distance"])
                if d < best_d:
                    best_d, best_off = d, off
            except Exception:
                pass
            finally:
                if cand_fp:
                    try: os.unlink(cand_fp)
                    except OSError: pass
    except Exception as e:
        log.debug("Busca grossa de offset falhou (%s): %s", Path(cand_file["path"]).name, e)
        return None
    finally:
        if ref_fp:
            try: os.unlink(ref_fp)
            except OSError: pass
    return best_off


def _search_visual_offset(seg: dict, cand_file: dict, ref_video: str,
                          opts: dict) -> tuple[Optional[float], int]:
    """Score visual COM busca de offset. Devolve (score, offset_frames).

    Primeiro tenta o seek esperado (offset 0). Se já é bom, retorna sem buscar. Senão
    faz a varredura grossa + refino fino e confirma com o score multi-frame estrito —
    recupera mídia com frame 0 deslocado SEM relaxar o limiar de aceite (um arquivo
    diferente não concorda em várias amostras em nenhum offset)."""
    base = _visual_score_at(seg, cand_file, ref_video, opts, 0)
    good = 1.0 - opts["visual_hamming_threshold"] / 64.0
    if not opts.get("offset_search", True):
        return base, 0
    if base is not None and base >= good:
        return base, 0

    coarse = _coarse_align_offset(seg, cand_file, ref_video, opts)
    if not coarse:
        return base, 0

    fps = seg.get("source_fps") or 25.0
    fine = max(1, int(round(0.2 * fps)))
    best_sc = base if base is not None else -1.0
    best_off = 0
    for off in sorted({coarse + d * fine for d in (-2, -1, 0, 1, 2)}):
        sc = _visual_score_at(seg, cand_file, ref_video, opts, off)
        if sc is not None and sc > best_sc:
            best_sc, best_off = sc, off
    return best_sc, best_off


def compare_candidates(seg: dict, candidates: list[dict], ref_video: Optional[str],
                       options: Optional[dict] = None, align: bool = False) -> dict:
    """Prepara dados p/ a janela de desempate visual (REF × candidatos, só vídeo).

    Por padrão (`align=False`) é INSTANTÂNEO: só calcula o TC de fonte a exibir (no 1º
    frame do segmento) e o TC do REF — SEM ffmpeg. O frontend extrai os frames (REF +
    1 por candidato). Isso mantém a janela rápida (o custo é só N+1 extrações).

    `align=True` (opt-in, caro) roda a busca de offset por candidato p/ compensar mídia
    com frame 0 deslocado (TC zerado/recorte) — usar só sob demanda no candidato em foco."""
    opts = {**DEFAULT_OPTIONS, **(options or {})}
    fps = seg.get("source_fps") or 25.0
    dur = max(1, int(seg.get("duration_frames") or 0))
    # Ponto EXIBIDO = primeiro frame do segmento (offset 0 = o que o monitor mostra). O
    # alinhamento por offset continua robusto (multi-frame, no meio do clipe, dentro de
    # _search_visual_offset).
    disp_off = 0
    ref_offset_secs = _tc_to_seconds(opts["ref_tc_start"], fps)
    base_secs = _tc_to_seconds(seg.get("timeline_tc_in", "00:00:00:00"), fps) - ref_offset_secs
    ref_tc = _frames_to_tc(max(0, round((base_secs + disp_off / fps) * fps)), fps)
    src_start = int(seg.get("source_start_frames") or 0)
    # Frame de FONTE no ponto exibido (mapeia o offset de timeline p/ a fonte via velocidade).
    src_disp = _cand_seek_frame(
        src_start, disp_off, dur, seg.get("speed_ratio", 1.0) or 1.0,
        seg.get("motion_effect_type"), seg.get("phase_offset", 0) or 0,
        seg.get("source_offset_map") or [])

    # fps do domínio da FONTE = edit rate do SourceMob do AAF (não do arquivo online).
    src_fps = (seg.get("media_ref") or {}).get("source_fps") or fps

    out: list[dict] = []
    for f in candidates:
        # align=False: instantâneo (só TC, sem ffmpeg). align=True: busca de offset (caro).
        if ref_video and align:
            score, off = _search_visual_offset(seg, f, ref_video, opts)
        else:
            score, off = None, 0
        cfps = src_fps
        cand_frame = max(0, src_disp + off)
        out.append({
            "path": f.get("path"),
            "filename": f.get("filename") or (f.get("path") or "").split("/")[-1],
            "offset": off,
            "offset_secs": round(off / fps, 3),
            "score": round(score, 4) if score is not None else None,
            "cand_tc": _frames_to_tc(cand_frame, cfps),
        })
    out.sort(key=lambda c: -(c["score"] if c["score"] is not None else -1.0))
    return {"ref_tc": ref_tc, "ref_fps": fps, "disp_offset": disp_off, "candidates": out}


def _visual_tiebreak(seg: dict, cands: list[dict], ref_video: str, opts: dict):
    """Desempata candidatos AMBÍGUOS (mesmo nome E duração) por imagem.

    Retorna `(arquivo, score)` apenas quando há um vencedor CLARO — acima do limiar de
    match E com margem sobre o 2º colocado. Se dois candidatos casam igualmente bem
    (conteúdo idêntico/duplicado) ou nada extrai, retorna `(None, None)` → fica ambíguo
    e vai para revisão (princípio: relink errado é pior que nenhum)."""
    import control
    scored: list[tuple[float, dict]] = []
    for f in cands:
        control.check()   # ponto de cancelamento (desempate pode extrair vários frames)
        v = _visual_score_for(seg, f, ref_video, opts)
        if v is not None:
            scored.append((v, f))
    if not scored:
        return None, None
    scored.sort(key=lambda x: -x[0])
    best_v, best_f = scored[0]
    second = scored[1][0] if len(scored) > 1 else -1.0
    hamming_match_score = 1.0 - opts["visual_hamming_threshold"] / 64
    if best_v >= hamming_match_score and (best_v - second) >= 0.06:
        return best_f, best_v
    return None, None


# ── Matching de um alternate ──────────────────────────────────────────────

def _match_alternate(
    alt: dict,
    files: list[dict],
    opts: dict,
    seg_idx: int,
) -> dict:
    """
    Tenta match para uma câmera alternativa (selector_alternate).
    Usa apenas stages 1-3 (sem visual, pois não temos TC de ref para alternates).

    Retorna dict com:
        mob_name, original_url, matched_path, method, confidence.

    original_url é incluído para que o writer possa construir o url_map
    mapeando a URL original do AAF para o novo caminho encontrado.
    """
    mob_name     = alt.get("mob_name", "")
    local_path   = alt.get("local_path", "")
    original_url = alt.get("url", "")     # URL original do AAF (file:///...)

    base = {"mob_name": mob_name, "original_url": original_url}

    # Stage 1: path exato
    if local_path:
        for f in files:
            if f["path"] == local_path:
                return {**base, "matched_path": f["path"], "method": "path", "confidence": 1.0}

    # Stage 2: UID
    # (alternates não têm mob_id separado; pula)

    # Stage 3: nome + portão de duração (alt carrega source_duration_secs do AAF)
    alt_seg = {"media_ref": {"source_duration_secs": alt.get("source_duration_secs")}}
    scored = _score_files_by_name(mob_name, mob_name, files, opts["max_candidates"])
    if scored:
        best_score, best_file = scored[0]
        dur_ok = _duration_ok(alt_seg, best_file, opts)
        if best_score == 1.0 and dur_ok is not False:
            return {**base, "matched_path": best_file["path"], "method": "exact_name", "confidence": 1.0}
        if best_score >= opts["fuzzy_threshold"] and dur_ok is not False:
            return {**base, "matched_path": best_file["path"], "method": "fuzzy_name", "confidence": round(best_score, 4)}

    return {**base, "matched_path": None, "method": "unresolved", "confidence": 0.0}


# ── Matching de um segmento ───────────────────────────────────────────────

#: reel que não identifica nada (banco, bugs-do-mundo-real B040; a mesma regra de `atualizar.py`): só dígitos ou 1–2
#: caracteres — o BRAW grava "1" e juntaria a câmera A e a B.
_REEL_DEGENERADO = re.compile(r"\d+|.{1,2}")


def _daily_do_segmento(seg: dict) -> Optional[str]:
    """O arquivo que o AAF aponta (o DAILY do offline), se está nesta máquina. ⚠️ O AAF do MC no Mac grava o caminho
    SEM o `/Volumes` (`/SSD/…`, o volume como raiz — `aaf/writer.path_to_aaf_url`)."""
    mr = seg.get("media_ref") or {}
    tentativas = []
    lp = mr.get("local_path") or ""
    if lp:
        tentativas += [lp, "/Volumes" + lp] if lp.startswith("/") and not lp.startswith("/Volumes/") else [lp]
    if mr.get("url"):
        try:
            from aaf.writer import _aaf_url_to_local
            tentativas.append(_aaf_url_to_local(mr["url"]))
        except Exception:   # noqa: BLE001 — sem o writer (pyaaf2) só não se tenta a URL
            pass
    return next((t for t in tentativas if t and os.path.isfile(t)), None)


def _reel_do_segmento(seg: dict, daily: Optional[str]) -> Optional[str]:
    """O reel / tape name do plano (CRITÉRIO de casamento, autor, 2026-11-22): o do AAF quando vier (`tape_name`), senão
    o gravado no arquivo do daily — o MC 25.12 não leva o `reel_name` do QuickTime para o AAF (BL08, P4)."""
    mr = seg.get("media_ref") or {}
    reel = (mr.get("tape_name") or "").strip()
    if not reel and daily:
        from media.confirmacao import reel_do_arquivo
        reel = (reel_do_arquivo(daily) or "").strip()
    return None if not reel or _REEL_DEGENERADO.fullmatch(reel) else reel


def _match_one(
    idx: int,
    seg: dict,
    files: list[dict],
    ref_video: Optional[str],
    opts: dict,
) -> MatchResult:
    """
    Executa a cascata de matching para um segmento.
    Retorna MatchResult preenchido.
    """
    media_ref = seg.get("media_ref", {}) or {}
    clip_name   = seg.get("clip_name", "")
    mob_id      = seg.get("mob_id", "")
    mob_name    = media_ref.get("mob_name", "")
    local_path  = media_ref.get("local_path", "")
    alts        = seg.get("selector_alternates", [])

    candidates: list[dict] = []

    # ── Stage 1: Path exato ───────────────────────────────────────────────
    if local_path:
        for f in files:
            if f["path"] == local_path:
                log.info("[%d] Path match: %s", idx, f["filename"])
                alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
                return MatchResult(
                    idx, seg,
                    matched_path=f["path"],
                    match_method="path",
                    confidence=1.0,
                    candidates=[_candidate_dict(f, 1.0, "path")],
                    alternate_matches=alt_matches,
                )

    # ── Stage 2: UID ──────────────────────────────────────────────────────
    if mob_id:
        norm_mob_id = _normalize_uid(mob_id)
        for f in files:
            file_uid = f.get("uid") or ""
            if file_uid and _normalize_uid(file_uid) == norm_mob_id:
                log.info("[%d] UID match: %s", idx, f["filename"])
                alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
                return MatchResult(
                    idx, seg,
                    matched_path=f["path"],
                    match_method="uid",
                    confidence=0.95,
                    candidates=[_candidate_dict(f, 0.95, "uid")],
                    alternate_matches=alt_matches,
                )

    # ── Stage 3: Nome (fuzzy + token sort) ───────────────────────────────
    log.debug("[%d] Nome matching — clip='%s' mob='%s'", idx, clip_name, mob_name)
    scored = _score_files_by_name(clip_name, mob_name, files, opts["max_candidates"])
    candidates = [_candidate_dict(f, s, "fuzzy_name") for s, f in scored]

    for s, f in scored[:3]:
        log.debug("[%d]   candidato: '%s' score=%.3f", idx, f["filename"], s)

    best_score = scored[0][0] if scored else 0.0
    best_file  = scored[0][1] if scored else None

    # ── Nome forte (exato 1.0 ou fuzzy alto) + DESEMPATE por duração/imagem ──────
    # `top` = candidatos que empatam no melhor score (disputa real de identidade).
    EPS = 1e-9
    top = [f for s, f in scored if s >= best_score - EPS] if scored else []

    name_strong = False
    method_name = "fuzzy_name"
    if best_score == 1.0:
        # Guard de token overlap: ao menos 1 token len≥4 compartilhado, p/ evitar falso
        # positivo por similaridade de caracteres (ex: A004_... vs A002_...). Descarta do
        # topo os 1.0 sem token em comum (mob_name corrompido / TC zerado).
        norm_clip_check = _normalize_name(clip_name)
        top = [f for f in top
               if _has_significant_token_overlap(
                   norm_clip_check, _normalize_name(_nome_do_arquivo(f)))]
        if top:
            name_strong, method_name = True, "exact_name"
    elif best_score >= opts["visual_skip_threshold"]:
        name_strong, method_name = True, "fuzzy_name"

    # ── Reel / tape name: CRITÉRIO, com as mesmas provas do nome (autor, 2026-11-22) ──────────────────────────────
    # Sem original com o nome do plano, o reel do daily procura o original de MESMO NOME que o reel (BL08, P4: o daily
    # renomeado `CENA12_T3` com reel `B001C007`). Depois segue a mesma cascata: duração, cópias, empate.
    daily = _daily_do_segmento(seg)
    if not (name_strong and top):
        reel = _reel_do_segmento(seg, daily)
        if reel and _normalize_name(reel) != _normalize_name(clip_name):
            chave = _normalize_name(reel)
            por_reel = [f for f in files if f["path"] != daily
                        and _normalize_name(_nome_do_arquivo(f)) == chave]
            if por_reel:
                log.info("[%d] Reel '%s' (o plano se chama '%s'): %d candidato(s)", idx, reel, clip_name, len(por_reel))
                top, name_strong, method_name = por_reel, True, "reel"
                candidates = [_candidate_dict(f, 1.0, "reel") for f in por_reel] + candidates

    if name_strong and top:
        conf = {"exact_name": 1.0, "reel": 0.95}.get(method_name, best_score)
        # Partição por duração: descarta os que REPROVAM (False); mantém pass(True)+neutro(None).
        viable = [f for f in top if _duration_ok(seg, f, opts) is not False]

        if len(viable) == 1:
            # Único viável → escolhe ELE, mesmo que outro de mesmo nome exista com duração
            # errada. Resolve o caso de dois "D001" com durações diferentes.
            chosen = viable[0]
            log.info("[%d] %s (duração ok): %s", idx, method_name, chosen["filename"])
            alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
            return MatchResult(idx, seg, matched_path=chosen["path"], match_method=method_name,
                               confidence=conf, candidates=candidates, alternate_matches=alt_matches)

        if len(viable) >= 2 and _copias_identicas([f["path"] for f in viable]):
            # Cópias IDÊNTICAS do mesmo arquivo (backup, dois HDs): não há o que escolher — valem
            # como um original só, o da 1ª pasta (a regra do casador do Premiere, prproj/originais).
            chosen = viable[0]
            log.info("[%d] %s (%d cópias idênticas): %s", idx, method_name, len(viable), chosen["filename"])
            alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
            return MatchResult(idx, seg, matched_path=chosen["path"], match_method=method_name,
                               confidence=conf, candidates=candidates, alternate_matches=alt_matches)

        if len(viable) >= 2:
            # AMBÍGUO: ≥2 empatam por nome E duração (ex.: câmera de gravação contínua
            # fatiada). Desempata por IMAGEM quando há ref; senão vai para revisão.
            if ref_video and not seg.get("is_audio"):
                chosen, vscore = _visual_tiebreak(seg, viable, ref_video, opts)
                if chosen is not None:
                    log.info("[%d] Desempate visual (%.3f): %s", idx, vscore, chosen["filename"])
                    alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
                    return MatchResult(idx, seg, matched_path=chosen["path"], match_method=method_name,
                                       confidence=conf, candidates=candidates,
                                       visual_score=round(vscore, 4), verified=True,
                                       alternate_matches=alt_matches)
            # Sem vídeo de referência (ou ele não decidiu): o quadro do DAILY × o de cada candidato. Só resolve com
            # confirmação visual; sem ela, nunca decidimos sozinhos (autor, 2026-11-22; `media/confirmacao.py`).
            if daily and not seg.get("is_audio") and opts.get("confirmar_pelo_daily", True):
                from media.confirmacao import confirmar_pela_imagem
                escolhido, notas = confirmar_pela_imagem(
                    daily, [f["path"] for f in viable if f["path"] != daily],
                    media_ref.get("source_duration_secs"))
                if escolhido:
                    log.info("[%d] Confirmado pela imagem do daily (%.3f): %s", idx, notas[escolhido],
                             Path(escolhido).name)
                    alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
                    return MatchResult(idx, seg, matched_path=escolhido, match_method=method_name,
                                       confidence=conf, candidates=candidates,
                                       visual_score=notas[escolhido], verified=True,
                                       alternate_matches=alt_matches, imagem=notas)
                if notas:
                    log.info("[%d] A imagem do daily não separa os candidatos: %s", idx,
                             {Path(k).name: v for k, v in notas.items()})
            log.warning("[%d] Ambíguo: %d candidatos empatam por nome+duração — revisão.",
                        idx, len(viable))
            alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
            # ⛔⛔ SEM caminho até o editor revisar (autor, 2026-11-22: "precisamos evitar erros calados"). Até aqui
            # saía o 1º candidato com `ambiguous=True` — e ninguém lia a marca: o `build_url_map` religava o plano
            # no 1º da lista, calado (laboratório BL08, P2: o DIA01 ia para o DIA02). Os candidatos ficam para a revisão.
            return MatchResult(idx, seg, matched_path=None, match_method="unresolved",
                               confidence=0.0, candidates=candidates, ambiguous=True,
                               alternate_matches=alt_matches)
        # len(viable) == 0 → nome forte mas duração reprova em TODOS → segue para o
        # fallback abaixo (visual/fuzzy-baixo), que com duração reprovada cai em não-resolvido.

    # ── Stage 4: Visual pHash (APENAS confirmação, sobre candidatos que passam
    #    no portão de duração) ───────────────────────────────────────────────
    #
    # Otimização: o visual SEMPRE vai para revisão humana (nunca auto-aceita como
    # "encontrado"). Logo, se já existe um candidato por nome aceitável
    # (best_score ≥ fuzzy_threshold), o fallback fuzzy abaixo já dá uma resposta
    # de revisão — rodar o visual (extração de frames, caro) não muda o resultado
    # e o humano confirma no stepper de revisão. Então o visual só roda quando NÃO
    # há candidato por nome utilizável (é a única pista). Grande economia no re-match.
    # ÁUDIO nunca passa pelo visual (não tem frame p/ comparar) — só metadados/nome.
    if (ref_video and opts["visual_fallback"] and best_score < opts["fuzzy_threshold"]
            and not seg.get("is_audio")):
        # Elegíveis = arquivos cuja duração NÃO reprova (True ou None/sem dado).
        # Isso remove deterministicamente candidatos de duração errada (ex: A003=960
        # nunca testa contra CAM A/B=1572) — o cerne do anti-falso-positivo.
        name_score = {f["path"]: s for s, f in scored}
        eligible = [f for f in files if _duration_ok(seg, f, opts) is not False]
        # Prioriza por score de nome (melhores primeiro), depois limita.
        eligible.sort(key=lambda f: -name_score.get(f["path"], 0.0))
        n_excluded = len(files) - len(eligible)
        if n_excluded:
            log.debug("[%d] Portão de duração excluiu %d candidato(s) do visual", idx, n_excluded)
        visual_top = [(name_score.get(f["path"], 0.0), f)
                      for f in eligible[:opts["visual_max_candidates"]]]

        import control
        best_visual_score = -1.0
        best_visual_file  = None
        best_visual_off   = 0

        for _, cand_file in visual_top:
            control.check()   # busca de offset extrai vários frames — cancelável
            # Busca de offset: recupera mídia com frame 0 deslocado (TC zerado/recorte),
            # alinhando por imagem. O aceite continua estrito (a busca não relaxa o limiar).
            vscore, voff = _search_visual_offset(seg, cand_file, ref_video, opts)
            if vscore is not None and vscore > best_visual_score:
                best_visual_score = vscore
                best_visual_file  = cand_file
                best_visual_off   = voff

        # Aceite por MÉDIA de distância (multi-frame). hamming_threshold agora é
        # bem mais rígido (6 → score ≥ ~0.906).
        hamming_match_score = 1.0 - opts["visual_hamming_threshold"] / 64
        if best_visual_file and best_visual_score >= hamming_match_score:
            log.info("[%d] Visual match (%.3f, off=%+df): %s",
                     idx, best_visual_score, best_visual_off, best_visual_file["filename"])
            alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
            return MatchResult(
                idx, seg,
                matched_path=best_visual_file["path"],
                match_method="visual",
                confidence=best_visual_score,
                candidates=candidates,
                visual_score=round(best_visual_score, 4),
                alternate_matches=alt_matches,
                source_offset_correction=best_visual_off,
            )

    # ── Fuzzy name com baixa confiança (melhor que nada) ──────────────────
    # Só se a duração não reprovar — evita anexar arquivo de nome parecido mas
    # tamanho incompatível.
    if best_score >= opts["fuzzy_threshold"] and best_file and _duration_ok(seg, best_file, opts) is not False:
        log.info("[%d] Fuzzy name (baixa confiança %.2f): %s", idx, best_score, best_file["filename"])
        alt_matches = [_match_alternate(a, files, opts, idx) for a in alts]
        return MatchResult(
            idx, seg,
            matched_path=best_file["path"],
            match_method="fuzzy_name",
            confidence=best_score,
            candidates=candidates,
            alternate_matches=alt_matches,
        )

    # ── Não resolvido ─────────────────────────────────────────────────────
    log.warning("[%d] Não resolvido: clip='%s' mob='%s'", idx, clip_name, mob_name)
    return MatchResult(
        idx, seg,
        matched_path=None,
        match_method="unresolved",
        confidence=0.0,
        candidates=candidates,
        alternate_matches=[],
    )


# ── Ponto de entrada público ──────────────────────────────────────────────

def _copias_identicas(caminhos: list[str]) -> bool:
    """Todos os arquivos são o MESMO conteúdo: mesmo tamanho e mesmo SHA-1 de 1 MB do início, do meio e do fim (o
    `_impressao` de `prproj/originais.py` — hash inteiro de um ARRIRAW custaria minutos). Ilegível = não."""
    import hashlib
    bloco, impressoes = 1 << 20, []
    for c in caminhos:
        try:
            tam = os.path.getsize(c)
            h = hashlib.sha1()
            with open(c, "rb") as f:
                for pos in (0, tam // 2, max(0, tam - bloco)):
                    f.seek(pos)
                    h.update(f.read(bloco))
            impressoes.append((tam, h.hexdigest()))
        except OSError:
            return False
    return len(impressoes) > 1 and all(i == impressoes[0] for i in impressoes[1:])


def match_segments(
    segments: list[dict],
    index: dict,
    ref_video: Optional[str] = None,
    options: Optional[dict] = None,
    only_indices: Optional[list] = None,
) -> dict:
    """
    Executa o motor de matching para uma lista de segmentos.

    Args:
        segments: lista de dicts de Segment.to_dict() vindos do parser
        index:    dict de index_folder() com chave "files"
        ref_video: path para o vídeo de referência offline (opcional, para visual match)
        options:  overrides das opções padrão (DEFAULT_OPTIONS)
        only_indices: se fornecido, **só casa esses índices de segmento** (os demais
                  ficam de fora dos resultados). Usado no "Scan completo" para procurar
                  apenas os clipes ainda offline, sem re-casar (nem gastar visual com) os
                  já resolvidos. `segment_index` segue o índice original (enumerate).

    Retorna:
        {
            "results": [MatchResult.to_dict(), ...],
            "stats": {
                "total": int,
                "skipped": int,
                "matched_path": int,
                "matched_uid": int,
                "matched_exact_name": int,
                "matched_fuzzy_name": int,
                "matched_visual": int,
                "unresolved": int,
            }
        }
    """
    _bench_t = time.perf_counter()
    opts  = {**DEFAULT_OPTIONS, **(options or {})}
    files = index.get("files", [])

    if not files:
        log.warning("Índice de arquivos vazio — matching não é possível.")

    if ref_video and not Path(ref_video).exists():
        log.warning("Vídeo de referência não encontrado: %s — visual match desativado.", ref_video)
        ref_video = None

    results: list[dict] = []
    skipped = 0
    target = set(only_indices) if only_indices is not None else None

    import control
    for i, seg in enumerate(segments):
        # Scan completo: só processa os índices pedidos (os já resolvidos ficam de fora,
        # o caller preserva os resultados antigos deles).
        if target is not None and i not in target:
            continue
        control.check()   # ponto de cancelamento (entre segmentos)
        # Gaps, transições e efeitos sem mídia não precisam de match
        if seg.get("is_gap") or seg.get("is_transition") or seg.get("is_effect"):
            skipped += 1
            continue

        # Sem media_ref E sem clip_name não há por onde casar (ScopeReference,
        # graphic-only, etc.). MAS em AAF OFFLINE o media_ref vem vazio e o match é
        # SÓ pelo nome (clip_name) — não pular nesse caso, senão nada casa.
        if not seg.get("media_ref") and not (seg.get("clip_name") or "").strip():
            results.append(
                MatchResult(i, seg, None, "unresolved", 0.0, []).to_dict()
            )
            continue

        result = _match_one(i, seg, files, ref_video, opts)
        results.append(result.to_dict())

    # ── Propagação por origem (mesma media_ref.url ⇒ mesma mídia física) ──────
    # No AAF, usos da mesma fonte compartilham um SourceMob/URL; o writer relinka
    # por URL. Aqui propagamos o MELHOR match de cada URL a todos os segmentos
    # irmãos (resolve 1 → resolve todos), e damos precedência a métodos mais
    # confiáveis. Não cria matches novos — só propaga os já encontrados.
    _RANK = {"path": 5, "uid": 4, "exact_name": 3, "manual": 3, "reel": 3, "fuzzy_name": 2, "visual": 1}
    seg_by_idx = {i: s for i, s in enumerate(segments)}

    def _url_of(res: dict) -> str:
        seg = seg_by_idx.get(res.get("segment_index"), {})
        return ((seg.get("media_ref") or {}).get("url")) or ""

    best_by_url: dict[str, dict] = {}
    for res in results:
        if not res.get("matched_path"):
            continue
        url = _url_of(res)
        if not url:
            continue
        rank = _RANK.get(res.get("match_method", ""), 0)
        cur = best_by_url.get(url)
        if cur is None or rank > _RANK.get(cur.get("match_method", ""), 0):
            best_by_url[url] = res

    for res in results:
        url = _url_of(res)
        donor = best_by_url.get(url)
        if not donor or donor is res:
            continue
        cur_rank = _RANK.get(res.get("match_method", ""), 0)
        if _RANK.get(donor.get("match_method", ""), 0) > cur_rank:
            res["matched_path"]  = donor["matched_path"]
            res["match_method"]  = donor["match_method"]
            res["confidence"]    = donor["confidence"]
            res["propagated_from_url"] = True

    # ── Supressão de duplicata entre origens ─────────────────────────────────
    # Um arquivo físico deve servir UMA origem. Se um arquivo já é match SÓLIDO
    # (path/uid/exact_name) de uma origem, claims MAIS FRACOS (fuzzy/visual) do
    # MESMO arquivo por OUTRA origem são removidos (viram unresolved) — evita o
    # falso-positivo "CAM B casa CAM A.mxf quando CAM A já o tem a 100%".
    SOLID_RANK = 3   # exact_name/path/uid/manual
    best_path: dict[str, tuple] = {}   # matched_path → (rank, url)
    for res in results:
        p = res.get("matched_path")
        if not p:
            continue
        rank = _RANK.get(res.get("match_method", ""), 0)
        url  = _url_of(res)
        cur  = best_path.get(p)
        if cur is None or rank > cur[0]:
            best_path[p] = (rank, url)
    for res in results:
        p = res.get("matched_path")
        if not p:
            continue
        best_rank, best_url = best_path[p]
        my_rank = _RANK.get(res.get("match_method", ""), 0)
        if best_rank >= SOLID_RANK and _url_of(res) != best_url and my_rank < best_rank:
            res["matched_path"] = None
            res["match_method"] = "unresolved"
            res["confidence"]   = 0.0
            res["suppressed_dup"] = True
            log.info("[%s] Suprimido (arquivo já é match sólido de outra origem): %s",
                     res.get("segment_index"), Path(p).name)

    # ── Sequência de imagem por matched_path final ───────────────────────────
    # Liga a info de sequência (do índice) ao matched_path final de cada resultado,
    # já considerando propagação/supressão. None = arquivo único.
    path_to_seq = {f["path"]: f["sequence"] for f in files if f.get("sequence")}
    for res in results:
        res["sequence"] = path_to_seq.get(res.get("matched_path"))

    # ── Estatísticas (após propagação) ───────────────────────────────────────
    stats: dict = {
        "total": len(results),
        "skipped": skipped,
        "matched_path": 0,
        "matched_uid": 0,
        "matched_exact_name": 0,
        "matched_fuzzy_name": 0,
        "matched_visual": 0,
        "matched_reel": 0,
        "unresolved": 0,
    }
    for res in results:
        method_key = f"matched_{res.get('match_method')}"
        if method_key in stats:
            stats[method_key] += 1
        else:
            stats["unresolved"] += 1

    log.info(
        "Matching concluído: total=%d | path=%d uid=%d exact=%d fuzzy=%d visual=%d unresolved=%d",
        stats["total"],
        stats["matched_path"],
        stats["matched_uid"],
        stats["matched_exact_name"],
        stats["matched_fuzzy_name"],
        stats["matched_visual"],
        stats["unresolved"],
    )
    # Benchmark opt-in: total + quebra por método (visual é a etapa cara).
    import bench
    bench.record("match", (time.perf_counter() - _bench_t) * 1000.0,
                 total=stats["total"], visual=stats["matched_visual"],
                 unresolved=stats["unresolved"], files=len(files),
                 has_ref=bool(ref_video))
    return {"results": results, "stats": stats}
