"""
Relinker — Módulo AAF: Writer
Atualiza os URLStrings em SourceMobs [ImportDescriptor] de um arquivo AAF
com novos caminhos de mídia, preservando toda a estrutura interna:
  Selectors, Group Clips, Transitions, OperationGroups, NestedScopes, etc.

A estratégia é cirúrgica: apenas o campo URLString dos locators de
SourceMobs com ImportDescriptor é tocado. Nada mais muda no AAF.

Dependência: pyaaf2 (modo 'rw')
"""

from __future__ import annotations

import logging
import re
import shutil
from pathlib import Path
from typing import Optional

import aaf2
from origem import marcar_aaf
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)
from media.opatom import _video_rate  # noqa: E402 — a taxa por votação, nunca um campo cru (B074)

log = logging.getLogger("relinker.aaf.writer")


# Sufixos que o Avid acrescenta ao NOME do clipe (não existem no arquivo original):
# '.new.NN' (AMA-link→transcode), '.sync.NN' (subclipe sincronizado), '.grp', etc.
# Removidos do nome dos mobs no AAF de saída pra o Avid relinkar por nome contra a
# mídia AMA-linkada (ex.: '04 Dark Drone.wav.new.01' → '04 Dark Drone.wav'). A
# EXTENSÃO é mantida (o nome da mídia AMA do Avid inclui '.wav'). Ver memória
# effects-subclips-naming (a normalização de match já faz algo parecido).
_AVID_MOB_SUFFIX_RE = re.compile(
    r"\.(new|sync|cds|grp|sub|copy|exported|cpy)\.\d{1,4}$", re.IGNORECASE)


def _strip_avid_mob_suffix(name: str) -> str:
    """Remove sufixos do Avid (.new.NN/.sync.NN/…) do fim do nome, mantendo a extensão."""
    if not name:
        return name
    out, prev = name, None
    while out != prev:
        prev = out
        out = _AVID_MOB_SUFFIX_RE.sub("", out)
    return out


def _clean_mob_names(f) -> int:
    """Tira os sufixos do Avid dos nomes dos MasterMobs no AAF de saída → o Avid
    relinka por nome contra a mídia AMA-linkada. Retorna quantos foram renomeados."""
    n = 0
    for mob in f.content.mobs:
        if type(mob).__name__ != "MasterMob":
            continue
        old = getattr(mob, "name", "") or ""
        new = _strip_avid_mob_suffix(old)
        if new and new != old:
            try:
                mob.name = new
                n += 1
            except Exception as e:
                log.debug("Falha ao renomear mob '%s': %s", old, e)
    return n

# GUID do container AMA de MXF — é o que faz o Media Composer despachar a mídia
# pro plugin AMA de MXF na importação (em vez de tratar como mídia importada
# gerenciada). Descoberto por engenharia reversa de AAFs que auto-linkam:
# tanto os gerados pelo create_ama_link do pyaaf2 quanto os do próprio Avid
# carregam exatamente este valor no MediaContainerGUID do descriptor de essência.
_MXF_AMA_CONTAINER_GUID = "60eb8921-2a02-4406-891c-d9b6a6ae0645"

# MediaContainerGUID por tipo de essência — é o que faz o Avid despachar a mídia
# pro plugin AMA correto. ⚠️ O pyaaf2 deixa QuickTime no GUID "Generic" (bug: o
# código que setaria o de QuickTime está comentado em ama.py), e o Avid 2021 então
# falha com "Cannot access the AMA media stream plugin to play this clip". Por isso
# FORÇAMOS o GUID certo por extensão: MXF, QuickTime e WAV.
# Valores extraídos de AAFs de referência exportados pelo PRÓPRIO Avid (MC 2021):
#   MXF       → 60eb8921…  ;  QuickTime/.mov/.mp4 → 87a0584d…  ;  WAV/AIFF → 3711d3cc…
# (O "QuickTime" da tabela do pyaaf2, 781f84b7, NÃO toca no MC 2021 — usar o do Avid.)
_AMA_CONTAINER_GUID = {
    "mxf": _MXF_AMA_CONTAINER_GUID,
    "quicktime": "87a0584d-cafa-41f5-9a68-f0cadefdbb71",
    "wav": "3711d3cc-62d0-49d7-b0ae-c118101d1a16",
}
# ContainerHandlerGUID — identifica o PLUGIN/handler AMA que abre o stream. O erro
# "Cannot access the AMA media stream plugin" surge quando falta (o pyaaf2 não seta
# p/ QuickTime). Valor do AAF de referência do Avid MC 2021 (handler de QuickTime).
_AMA_HANDLER_GUID = {
    "quicktime": "3c06dc73-0276-4c4c-ba3f-3f47120cd1e9",
}
_MXF_EXTS = {".mxf"}
_WAV_EXTS = {".wav", ".wave", ".bwf", ".aif", ".aiff", ".aifc"}
_QUICKTIME_EXTS = {".mov", ".mp4", ".m4v", ".mpg", ".mpe", ".mpeg",
                   ".3gp", ".3g2", ".qt", ".avi", ".m2ts", ".mts"}


def _ama_container_key(ext: str) -> Optional[str]:
    """Mapeia a extensão p/ a chave de MediaContainerGUID (ou None p/ manter o do pyaaf2)."""
    if ext in _MXF_EXTS:
        return "mxf"
    if ext in _QUICKTIME_EXTS:
        return "quicktime"
    if ext in _WAV_EXTS:
        return "wav"
    return None

# ResolutionID default para o patch do bug de MXFMPEG2VideoDescriptor.link (ver
# _patch_pyaaf2_mpeg2). 4076 = XDCAM HD 50Mbit. Só afeta MXF MPEG2 (XDCAM); outros
# codecs MXF (DNxHD/AVC-Intra/ProRes) e formatos não-MXF não passam por este patch.
# TODO: derivar do header MXF quando for MPEG2 de outra taxa.
_XDCAM_HD50_RESOLUTION_ID = 4076

_MPEG2_PATCHED = False


def _ffprobe_meta(path: str) -> dict:
    """Metadata no formato ffprobe (format+streams) — exigido pelo create_ama_link
    do pyaaf2 para essências NÃO-MXF (QuickTime/.mov/.mp4, WAV, etc.).

    MXF não precisa (pyaaf2 lê o header direto). Lança em falha (caller trata).
    """
    import subprocess
    import json
    from media import fftools
    out = subprocess.run(
        [fftools.ffprobe_exe(), "-v", "quiet", "-print_format", "json",
         "-show_format", "-show_streams", path],
        capture_output=True, text=True, timeout=60, **fftools.SEM_JANELA,
    )
    meta = json.loads(out.stdout) if out.stdout else {}
    if "format" not in meta:
        raise RuntimeError(f"ffprobe não retornou 'format' para {path}: {out.stderr[:200]}")
    meta["format"]["filename"] = path     # pyaaf2 usa este campo
    return meta


def _tc_string_to_frames(tc: str, fps_int: int, drop: bool) -> int:
    """TC 'HH:MM:SS:FF' (ou ';FF' drop) → contagem CONTÍNUA de frames (a convenção que o
    AAF guarda em Timecode.Start). Inverso de _frames_to_tc_df. Non-drop = aritmética
    direta; drop-frame (30/60) desconta os labels pulados."""
    parts = re.split(r"[:;.]", tc.strip())
    if len(parts) != 4:
        raise ValueError(f"TC inválido: {tc!r}")
    h, m, s, ff = (int(x) for x in parts)
    total = ((h * 3600 + m * 60 + s) * fps_int) + ff
    if drop and fps_int in (30, 60):
        dropf = 4 if fps_int == 60 else 2
        total_min = h * 60 + m
        total -= dropf * (total_min - total_min // 10)
    return total


def _probe_online_tc(local_path: str):
    """(start_frames_continuos, fps_nominal_int, drop, edit_rate_Fraction, n_frames) do TC
    EMBUTIDO do arquivo ONLINE casado, via ffprobe — ou None se não houver TC/fps legível.

    Usado p/ REBASEAR o TC de origem ao ORIGINAL: o offline (proxy) pode ter o TC zerado
    ou errado (ex.: C004/C005 do print, Start 00:00:00:00), e o Avid precisa do TC real do
    arquivo p/ posicionar o clipe. O tape enxertado tem o arquivo como origem (frame 0), então
    o Start do TC = o TC EMBUTIDO em frame 0 (sem o precharge acumulado da cadeia offline)."""
    from fractions import Fraction
    try:
        meta = _ffprobe_meta(local_path)
    except Exception as e:
        log.debug("ffprobe TC falhou p/ %s: %s", local_path, e)
        return None
    streams = meta.get("streams", []) or []
    vid = next((s for s in streams if s.get("codec_type") == "video"), None)
    if vid is None:
        return None
    # TC embutido: format.tags.timecode, ou tags.timecode de qualquer stream (tmcd/data/video).
    tc = ((meta.get("format", {}) or {}).get("tags", {}) or {}).get("timecode")
    if not tc:
        for s in streams:
            t = ((s.get("tags", {}) or {}).get("timecode"))
            if t:
                tc = t
                break
    if not tc:
        return None
    num, den = _video_rate(vid)   # por votação (B074): o `r_frame_rate` do MXF do Avid é a metade
    if not num or not den:
        return None
    er = Fraction(num, den)
    fps_real = float(er)
    if fps_real <= 0:
        return None
    fps_int = round(fps_real)
    drop = (";" in tc) or ("." in tc)
    try:
        start = _tc_string_to_frames(tc, fps_int, drop)
    except Exception as e:
        log.debug("Conversão de TC '%s' falhou: %s", tc, e)
        return None
    nb = vid.get("nb_frames")
    try:
        nb = int(nb)
    except Exception:
        dur = float((meta.get("format", {}) or {}).get("duration") or 0)
        nb = round(dur * fps_real) if dur else 0
    return (start, fps_int, drop, er, nb, tc)


def _patch_pyaaf2_mpeg2() -> None:
    """Corrige o NameError de MXFMPEG2VideoDescriptor.link no pyaaf2 1.7.1.

    `aaf2/mxf.py` linha ~690 usa `d` antes de existir ao linkar descriptors
    MPEG2 (XDCAM). Sem este patch, create_ama_link explode em qualquer MXF
    XDCAM. O fix seta ResolutionID e delega pro link do pai (CDCI), que não
    tem o bug. Aplicado uma vez por processo.
    """
    global _MPEG2_PATCHED
    if _MPEG2_PATCHED:
        return
    from aaf2 import mxf as aaf_mxf

    def _fixed_link(self):
        self.data["ResolutionID"] = _XDCAM_HD50_RESOLUTION_ID
        return super(aaf_mxf.MXFMPEG2VideoDescriptor, self).link()

    aaf_mxf.MXFMPEG2VideoDescriptor.link = _fixed_link
    _MPEG2_PATCHED = True


# ── Utilitários ───────────────────────────────────────────────────────────

def _macos_boot_volume_name() -> str:
    """Nome do volume de boot (o symlink em /Volumes que aponta para '/')."""
    import os
    try:
        for name in os.listdir("/Volumes"):
            if os.path.realpath(os.path.join("/Volumes", name)) == "/":
                return name
    except OSError:
        pass
    return "Macintosh HD"


def path_to_aaf_url(local_path: str) -> str:
    """
    Converte um path local para URL file:/// no formato que o **Avid** espera.

    CRÍTICO (macOS): o Avid usa o NOME DO VOLUME como raiz da URL, não o caminho
    POSIX. Ex.:
      /Volumes/DRIVE/a/b.mxf        → file:///DRIVE/a/b.mxf
      /Users/x/b.mxf (volume boot)  → file:///Macintosh%20HD/Users/x/b.mxf
    `Path.as_uri()` geraria file:///Volumes/DRIVE/... — o Avid interpreta
    "Volumes" como nome de volume, não encontra, e a mídia fica offline / o AMA
    falha ("SelectFileMob() failed"). Por isso convertemos manualmente.

    ⚠️ **WINDOWS: `pendente`, não medido.** Aqui usamos `Path.as_uri()`, que dá
    `file:///D:/a/b.mxf`. É a forma canônica e provavelmente a certa — mas *no macOS
    a forma canônica também parecia certa e estava errada*, e o modo de falha é o
    mesmo dos dois lados: a mídia fica **offline em silêncio**, sem mensagem que
    aponte para a URL. Só uma comparação contra um AAF exportado pelo próprio Media
    Composer no Windows fecha essa questão.

    ⭐ Isto **não afeta o relink**, que é o caminho em produção: lá quem cria o
    AMA-link é o `LinkFile` do próprio MC, e o AAF reescrito só troca MobID. Esta
    função serve à rota de autoria (`.avb` / AAF montado por fora), ainda dormente.
    """
    import sys
    import os
    import urllib.parse

    if sys.platform != "darwin":
        return Path(local_path).as_uri()

    abs_path = os.path.abspath(local_path)
    if abs_path.startswith("/Volumes/"):
        # /Volumes/<Vol>/resto → <Vol>/resto  (inclui o boot via "/Volumes/Macintosh HD/…")
        vol_rel = abs_path[len("/Volumes/"):]
    else:
        # Caminho no volume de boot (montado em "/") → prefixa o nome do volume
        vol_rel = f"{_macos_boot_volume_name()}/{abs_path.lstrip('/')}"

    encoded = "/".join(urllib.parse.quote(seg) for seg in vol_rel.split("/"))
    return f"file:///{encoded}"


def _aaf_url_to_local(url: str) -> Optional[str]:
    """Inverte path_to_aaf_url (macOS): file:///<Vol>/resto → path POSIX local."""
    import sys
    import os
    import urllib.parse

    if not url or not url.startswith("file://"):
        return None
    raw = urllib.parse.unquote(url[len("file://"):])
    if sys.platform != "darwin":
        return raw
    parts = raw.lstrip("/").split("/", 1)
    vol = parts[0]
    rest = parts[1] if len(parts) > 1 else ""
    try:
        if os.path.realpath(os.path.join("/Volumes", vol)) == "/":
            return "/" + rest                      # volume de boot
    except OSError:
        pass
    return "/Volumes/" + vol + (("/" + rest) if rest else "")


def _file_umid_mobid(local_path: str):
    """
    Lê o file_package_umid do MXF (via ffprobe) e devolve um aaf2 MobID.
    Retorna None se não for possível (arquivo ausente, sem UMID, não-MXF, etc.).
    """
    import subprocess
    import re
    from aaf2.mobid import MobID

    if not local_path or not Path(local_path).exists():
        return None
    try:
        from media import fftools
        out = subprocess.run(
            [fftools.ffprobe_exe(), "-v", "error", "-show_entries", "format_tags:stream_tags", local_path],
            capture_output=True, text=True, timeout=30, **fftools.SEM_JANELA,
        ).stdout
    except Exception as e:
        log.debug("ffprobe falhou para UMID de '%s': %s", local_path, e)
        return None
    m = re.search(r"file_package_umid=0x([0-9A-Fa-f]{64})", out)
    if not m:
        return None
    h = m.group(1).lower()
    groups = [h[i:i + 8] for i in range(0, 64, 8)]
    try:
        return MobID("urn:smpte:umid:" + ".".join(groups))
    except Exception as e:
        log.debug("MobID inválido a partir do UMID '%s': %s", h, e)
        return None


def _material_num(mob_id) -> str:
    """Material number (4 últimos grupos do UMID) — o que o Avid casa no AMA."""
    s = str(mob_id)
    parts = s.split(":")[-1].split(".")
    return ".".join(parts[4:8]) if len(parts) >= 8 else s


def _avid_chain_id(mob_id, matnum: str, inst_byte: int):
    """Reescreve um MobID para o esquema da cadeia AMA do Avid: o material number
    (4 últimos grupos) vira `matnum` e o instance-byte (2º byte do grupo 3) vira
    `inst_byte`, preservando o resto.

    O Avid organiza a cadeia AMA com master (instance 0x00), file/tape source
    (0xa1) e physical source (0xb1) COMPARTILHANDO o mesmo material number (derivado
    do arquivo). O create_ama_link do pyaaf2, p/ formatos sem UMID embutido
    (WAV/QuickTime), gera os 3 mobs no MESMO instance (0x00) e com material numbers
    ALEATÓRIOS e DISTINTOS → o Avid não casa o AMA-link por identidade. Aqui
    reescrevemos cada source mob p/ matnum REAL (lido do SourceMob-folha offline =
    o que o Avid re-deriva ao AMA-linkar o arquivo) + o instance-byte por papel,
    espelhando a referência do Avid (e evitando colisão de mob_id entre eles).
    """
    from aaf2.mobid import MobID
    parts = str(mob_id).split(":")[-1].split(".")
    mat = (matnum or "").split(".")
    if len(parts) < 8 or len(mat) < 4:
        return mob_id
    g = parts[3]                                   # 8 hex chars, ex. "13000000"
    parts[3] = g[:2] + format(inst_byte & 0xFF, "02x") + g[4:]
    parts[4:8] = mat[:4]
    try:
        return MobID("urn:smpte:umid:" + ".".join(parts))
    except Exception as e:
        log.debug("MobID inválido (matnum=%s inst=%#x): %s", matnum, inst_byte, e)
        return mob_id


def _iter_sourceclips(mob):
    """Itera recursivamente todos os SourceClips dentro dos slots de um mob."""
    def walk(seg):
        k = type(seg).__name__
        if k == "SourceClip":
            yield seg
        elif hasattr(seg, "components"):           # Sequence
            for c in seg.components:
                yield from walk(c)
        elif k == "NestedScope":
            for s in getattr(seg, "slots", []):
                yield from walk(s)
        elif k == "OperationGroup":
            try:
                for inp in (seg.get("InputSegments") or []):
                    yield from walk(inp)
            except Exception:
                pass
        elif k == "Selector":
            try:
                sp = seg.get("Selected")
                sel = sp.value if hasattr(sp, "value") else sp
                if sel is not None:
                    yield from walk(sel)
            except Exception:
                pass
            try:
                for alt in (seg.get("Alternates") or []):
                    yield from walk(alt)
            except Exception:
                pass
    for slot in mob.slots:
        yield from walk(slot.segment)


def build_url_map(
    segments: list[dict],
    match_results: list[dict],
) -> dict[str, str]:
    """
    Constrói o mapa {original_url → new_url} a partir dos resultados de matching.

    Inclui o media_ref principal de cada segmento e todos os
    selector_alternates (câmeras do Group Clip).

    Segmentos com matched_path=None (não resolvidos) são ignorados.
    Deduplicação: se dois segmentos apontam para a mesma URL original,
    o primeiro mapeamento encontrado prevalece.

    Args:
        segments:       lista de Segment.to_dict() do parse_aaf()
        match_results:  lista de MatchResult.to_dict() do match_segments()

    Returns:
        dict mapeando cada URL original para a nova URL
    """
    url_map: dict[str, str] = {}
    # Rastreia o método que originou cada entrada, para dar precedência ao manual:
    # uma troca manual do usuário sempre sobrescreve um match automático na mesma URL.
    url_method: dict[str, str] = {}
    _RANK = {"path": 5, "uid": 4, "exact_name": 3, "reel": 3, "fuzzy_name": 2, "visual": 1, "manual": 9}

    # Indexa segmentos por índice para lookup O(1)
    seg_by_idx: dict[int, dict] = {i: s for i, s in enumerate(segments)}

    def _consider(url: str, path: str, method: str) -> None:
        """Registra url→path se for a primeira entrada OU se o método tiver
        precedência maior que o já registrado (manual > auto)."""
        if not url or not path:
            return
        cur = url_method.get(url)
        if cur is None or _RANK.get(method, 0) > _RANK.get(cur, 0):
            url_map[url] = path_to_aaf_url(path)
            url_method[url] = method
            log.debug("Mapeado (%s): %s → %s", method, url[-60:], path[-40:])

    for result in match_results:
        if not result:          # null no array esparso (gap/transition/effect)
            continue
        seg_idx      = result.get("segment_index")
        matched_path = result.get("matched_path")

        if matched_path is None:
            continue

        seg = seg_by_idx.get(seg_idx, {})  # type: ignore[arg-type]
        method = result.get("match_method", "")

        # ── Media ref principal ──────────────────────────────────────────
        media_ref = seg.get("media_ref") or {}
        _consider(media_ref.get("url", ""), matched_path, method)

        # ── Câmeras alternativas (Group Clip) ────────────────────────────
        for alt_match in result.get("alternate_matches", []):
            _consider(alt_match.get("original_url", ""),
                      alt_match.get("matched_path"),
                      alt_match.get("method", ""))

    log.info("URL map construído: %d entrada(s)", len(url_map))
    return url_map


def _norm_name(name: str) -> str:
    """Nome normalizado p/ casar MasterMob×match: minúsculas, sem extensão de mídia,
    sem sufixos do Avid (.sync/.new/.NN) e com separadores → espaço."""
    if not name:
        return ""
    n = _strip_avid_mob_suffix(name)
    n = _MEDIA_EXT_RE.sub("", n) if "_MEDIA_EXT_RE" in globals() else re.sub(
        r"\.(mxf|mov|mp4|m4v|avi|mkv|wav|wave|bwf|aif|aiff|aifc|mp3|m4a|aac|flac|"
        r"mts|m2ts|r3d|braw|dpx|exr|tif|tiff|jpg|jpeg|png)$", "", n, flags=re.IGNORECASE)
    n = re.sub(r"[\._\-/\\]+", " ", n.lower())
    return " ".join(n.split())


def build_name_map(segments: list, match_results: list) -> dict:
    """Mapa {nome_normalizado → path_local} a partir do match — para AAF OFFLINE,
    onde as SourceMobs não têm URLString (mídia de fita/sem proxy). O relink então
    é dirigido pelo NOME do MasterMob (= clip_name), não por URL existente."""
    name_map: dict[str, str] = {}
    seg_by_idx = {i: s for i, s in enumerate(segments)}
    for result in match_results or []:
        if not result:
            continue
        path = result.get("matched_path")
        if not path:
            continue
        seg = seg_by_idx.get(result.get("segment_index"), {}) or {}
        key = _norm_name(seg.get("clip_name") or "")
        if key and key not in name_map:
            name_map[key] = path
    log.info("Name map (offline) construído: %d entrada(s)", len(name_map))
    return name_map


def _rename_offline_to_match(f, name_map: dict) -> int:
    """Relink NATIVO (AAF offline de fita): renomeia TODO mob (master/source/tape)
    cujo nome casa um arquivo do name_map para o NOME DO ARQUIVO (caixa corrigida).

    O editor offline manda o nome em caixa diferente da mídia original (ex.: 'a001…'
    no AAF vs 'A001….mp4' no disco) → o Relink nativo do Avid não casa. Corrigindo o
    nome (e o do mob de tape, que é o tape name), o Avid relinka offline↔original por
    nome de fonte + TC. NÃO faz graft (o matnum AMA do .mp4 é proprietário). Devolve
    quantos mobs foram renomeados."""
    import os as _os
    # Áudio: o Avid MANTÉM a extensão (.wav) no nome do clipe e o Relink nativo casa
    # por nome COM extensão. Vídeo: o nome vem SEM extensão. Então mantemos a extensão
    # quando o arquivo casado é áudio; do contrário usamos só o stem.
    _AUDIO_EXTS = {".wav", ".wave", ".bwf", ".aif", ".aiff", ".aifc",
                   ".mp3", ".m4a", ".aac", ".flac"}
    renamed = 0
    for mob in list(f.content.mobs):
        old = getattr(mob, "name", "") or ""
        tgt = name_map.get(_norm_name(old))
        if not tgt:
            continue
        base = _os.path.basename(tgt)
        ext = _os.path.splitext(base)[1].lower()
        new = base if ext in _AUDIO_EXTS else _os.path.splitext(base)[0]
        if new and new != old:
            try:
                mob.name = new
                renamed += 1
            except Exception as e:
                log.debug("Falha ao renomear (nativo) '%s'→'%s': %s", old, new, e)
    log.info("Relink nativo: %d mob(s) renomeado(s) p/ casar a caixa do original", renamed)
    return renamed


# ── Writer principal ──────────────────────────────────────────────────────

def relink_aaf(
    source_aaf: str,
    output_aaf: str,
    url_map: dict[str, str],
    dry_run: bool = False,
    ama_autolink: bool = True,
    name_map: dict[str, str] | None = None,
    denest: bool = True,
) -> dict:
    """
    Cria uma cópia do AAF com os URLStrings dos SourceMobs atualizados.

    Itera sobre todos os SourceMob [ImportDescriptor] no AAF e substitui
    a URLString de cada locator conforme o url_map fornecido.
    SourceMobs não mapeados (ex: CDCIDescriptor, PCMDescriptor ou
    ImportDescriptor com URL não listada) são preservados sem alteração.

    Args:
        source_aaf:  path do AAF original (leitura)
        output_aaf:  path do AAF de saída (será criado/sobrescrito)
        url_map:     {original_url: new_url}  (file:/// → file:///)
        dry_run:     se True, apenas inspeciona sem gravar nada

    Returns:
        {
            "output_path":    str,
            "updated_count":  int,   # locators efetivamente atualizados
            "skipped_count":  int,   # locators sem mapeamento (preservados)
            "error_count":    int,   # locators com erro de acesso
            "mobs_updated":   [{"mob_name": str, "old_url": str, "new_url": str}],
            "mobs_skipped":   [{"mob_name": str, "url": str}],
            "dry_run":        bool,
        }
    """
    src = Path(source_aaf)
    out = Path(output_aaf)

    if not src.exists():
        raise FileNotFoundError(f"AAF de origem não encontrado: {source_aaf}")
    if src.resolve() == out.resolve():
        raise ValueError(
            "source_aaf e output_aaf devem ser arquivos diferentes. "
            "O original nunca é modificado no lugar."
        )
    name_map = name_map or {}
    if not url_map and not name_map:
        raise ValueError("url_map e name_map vazios — nada para atualizar.")

    mobs_updated: list[dict] = []
    mobs_skipped: list[dict] = []
    error_count = 0
    # SourceMobs relinkados → (mob, novo_path_local) p/ alinhar MobID ao UMID do arquivo
    align_targets: list = []
    ids_aligned: list[dict] = []
    # mob_id (str) do SourceMob-folha relinkado → nova URL (para promoção AMA)
    relinked_leaves: dict[str, str] = {}
    ama_promoted: list[dict] = []
    # TC de origem rebaseado ao arquivo ONLINE (offline tinha TC zerado/diferente)
    tc_rebased: list[dict] = []
    names_cleaned = 0
    names_renamed = 0
    denest_result = {"subclips": 0, "groupclips": 0}

    def _process_mobs(f) -> None:
        """Percorre todos os SourceMobs e aplica o url_map (ou apenas inspeciona)."""
        nonlocal error_count
        for mob in f.content.mobs:
            if type(mob).__name__ != 'SourceMob':
                continue
            desc = getattr(mob, 'descriptor', None)
            if not desc or type(desc).__name__ != 'ImportDescriptor':
                continue

            mob_name = getattr(mob, 'name', '') or ''

            try:
                locators = list(getattr(desc, 'locator', []))
            except Exception as e:
                log.warning("Falha ao ler locators de '%s': %s", mob_name, e)
                error_count += 1
                continue

            for loc in locators:
                try:
                    current_url = loc['URLString'].value
                except Exception as e:
                    log.warning("Falha ao ler URLString de '%s': %s", mob_name, e)
                    error_count += 1
                    continue

                if current_url in url_map:
                    new_url = url_map[current_url]
                    if not dry_run:
                        loc['URLString'].value = new_url
                        log.info("✓ %s: ...%s → ...%s",
                                 mob_name, current_url[-50:], new_url[-50:])
                        align_targets.append((mob, _aaf_url_to_local(new_url)))
                        relinked_leaves[str(mob.mob_id)] = new_url
                    mobs_updated.append({
                        "mob_name": mob_name,
                        "old_url": current_url,
                        "new_url": new_url,
                    })
                else:
                    mobs_skipped.append({
                        "mob_name": mob_name,
                        "url": current_url,
                    })

    def _align_source_ids(f) -> None:
        """
        Alinha o MobID do SourceMob-folha (ImportDescriptor) ao UMID real do arquivo
        relinkado — SOMENTE quando o material number diverge.

        Necessário porque clipes que no projeto original foram IMPORTADOS (e não
        AMA-linkados) carregam um MobID interno do Avid em vez do UMID do arquivo;
        sem isso o Avid não casa o AMA-link por identidade ("não relinka"). Clipes
        que já têm o UMID correto (a maioria) não são tocados.
        """
        # 1) Descobre os pares (mob_id_antigo → mob_id_novo) a aplicar.
        remap: dict = {}
        for mob, local_path in align_targets:
            target = _file_umid_mobid(local_path) if local_path else None
            if target is None:
                continue
            if _material_num(mob.mob_id) == _material_num(target):
                continue  # já casa — não mexe
            old = mob.mob_id
            mob.mob_id = target
            remap[str(old)] = target
            ids_aligned.append({
                "mob_name": getattr(mob, "name", "") or "",
                "old_id": str(old),
                "new_id": str(target),
            })
            log.info("MobID alinhado ao UMID: %s  %s → %s",
                     getattr(mob, "name", ""), _material_num(old), _material_num(target))

        if not remap:
            return

        # 2) Atualiza todas as referências (SourceClips) ao MobID antigo.
        for m in f.content.mobs:
            for sc in _iter_sourceclips(m):
                try:
                    cur = sc.mob_id
                except Exception:
                    continue
                if cur is not None and str(cur) in remap:
                    sc.mob_id = remap[str(cur)]

    def _first_sourceclip(seg):
        """Primeiro SourceClip alcançável dentro de um segmento (desce Selector +
        Alternates, OperationGroup/InputSegments e Sequence/NestedScope). Cobre o
        áudio do subclipe envolto em OperationGroup 'Audio Gain' e o selector de
        áudio multicam (Selected=Filler, fonte real num Alternate)."""
        k = type(seg).__name__
        if k == "SourceClip":
            return seg
        if k == "Selector":
            try:
                sel = seg["Selected"].value
                r = _first_sourceclip(sel) if sel is not None else None
                if r is not None:
                    return r
            except Exception:
                pass
            try:
                for alt in (list(seg.get("Alternates") or [])):
                    r = _first_sourceclip(alt)
                    if r is not None:
                        return r
            except Exception:
                pass
        if k == "OperationGroup":
            try:
                for ip in (list(seg.get("InputSegments") or [])):
                    r = _first_sourceclip(ip)
                    if r is not None:
                        return r
            except Exception:
                pass
        if hasattr(seg, "components"):
            for c in seg.components:
                r = _first_sourceclip(c)
                if r is not None:
                    return r
        return None

    def _add_imported_ama(f, master) -> bool:
        """Garante _IMPORTED_AMA=1 no MobAttributeList do MasterMob. True se mudou."""
        try:
            current = list(master["MobAttributeList"].value or [])
        except Exception:
            current = []
        for tv in current:
            if tv.name == "_IMPORTED_AMA":
                return False
        current.append(f.create.TaggedValue("_IMPORTED_AMA", 1))
        master["MobAttributeList"].value = current
        return True

    def _master_relink_local(f, master):
        """`(path_local, leaf_mob_id)` do original relinkado p/ um MasterMob.

        Desce a cadeia do master (pelo 1º SourceClip de cada slot) até achar um
        SourceMob-folha cujo mob_id está em relinked_leaves, e devolve o path
        local correspondente + o mob_id da folha (de onde vem o material number
        REAL do arquivo, usado p/ casar o AMA-link de formatos sem UMID embutido).
        Retorna `(None, None)` se não achar.
        """
        for slot in master.slots:
            sc = _first_sourceclip(slot.segment)
            if sc is None:
                continue
            cur = next((m for m in f.content.mobs
                        if str(m.mob_id) == str(sc.mob_id)), None)
            seen = {str(master.mob_id)}
            depth = 0
            while cur is not None and depth < 6:
                cid = str(cur.mob_id)
                if cid in seen:
                    break
                seen.add(cid)
                if cid in relinked_leaves:
                    return _aaf_url_to_local(relinked_leaves[cid]), cid
                nxt = None
                for s in cur.slots:
                    r = _first_sourceclip(s.segment)
                    if r is not None and str(r.mob_id) != cid:
                        nxt = next((m for m in f.content.mobs
                                    if str(m.mob_id) == str(r.mob_id)), None)
                        if nxt is not None:
                            break
                cur = nxt
                depth += 1
        # O graft AMA só serve quando há um leaf com URL/UMID p/ alinhar o matnum
        # (caso AMA-based, ex. EFEITOS). Em AAF OFFLINE de fita (sem URL) o matnum do
        # Avid é proprietário/não-derivável → graft não funde. Esses casam por NOME via
        # _rename_offline_to_match (relink nativo do Avid), não pelo graft.
        return None, None

    def _rebase_source_tc(f) -> None:
        """Rebaseia o TC DE ORIGEM ao arquivo ONLINE casado, no caminho NATIVO (roda
        SEMPRE, independe do graft AMA — que está desligado p/ .mp4/.mov).

        Problema: o Avid relinka por NOME de fonte + TC. Quando o online tem um TC
        diferente do que o AAF herdou do proxy (ex.: original com TC zerado vs. o AAF que
        aponta 03:34:40:10), o TC de origem do clipe cai FORA do alcance do arquivo →
        offline. Aqui detectamos esse caso (TC herdado fora do range do online, via
        ffprobe) e DESLOCAMOS o offset de origem para o clipe cair no TC real do online.

        Determinístico e independente do AAF/mídias: nada é hardcodado. Quando o TC
        herdado JÁ cai no alcance do online (ex.: clipes cujo TC bate), não toca em nada.
        """
        import os as _os
        mobs = {str(m.mob_id): m for m in f.content.mobs}
        for master in list(f.content.mastermobs()):
            local, leaf_id = _master_relink_local(f, master)
            if not local or not _os.path.exists(local):
                continue
            if _os.path.splitext(local)[1].lower() in _WAV_EXTS:
                continue
            online = _probe_online_tc(local)
            if online is None:
                continue
            on_start, _on_fps_int, _on_drop, on_er, on_nb, on_tcstr = online
            on_fps = float(on_er) if on_er else float(_on_fps_int)
            if on_fps <= 0:
                continue
            online_s0 = on_start / on_fps
            online_s1 = (on_start + int(on_nb or 0)) / on_fps
            info = _source_tc_for_master(f, master)
            if info is None:
                continue
            cur_disp, fps_int, _drop, er, _length = info
            chain_fps = float(er) if er else float(fps_int or 0)
            if chain_fps <= 0:
                continue
            cur_s = cur_disp / chain_fps
            # Se o TC herdado já cai no alcance do arquivo online (com folga de 0,5s p/
            # precharge/arredondamento), o relink nativo do Avid acha a mídia → não mexe.
            if (online_s0 - 0.5) <= cur_s <= (online_s1 + 0.5):
                continue
            # Fora do alcance → rebaseia p/ o INÍCIO do online (assume arquivo per-take:
            # o conteúdo do clipe começa no frame 0 do arquivo online — caso do TC zerado).
            target = round(online_s0 * chain_fps)
            delta = target - cur_disp
            if delta == 0:
                continue
            # Aplica o delta às SourceClips da camada logo abaixo do master (a "proxy" que
            # carrega o offset de TC), em TODOS os slots (V+A) p/ manter a sincronia.
            applied = 0
            proxy_ids = set()
            for slot in master.slots:
                sc = _first_sourceclip(slot.segment)
                if sc is not None:
                    proxy_ids.add(str(sc.mob_id))
            for pid in proxy_ids:
                proxy = mobs.get(pid)
                if proxy is None:
                    continue
                for s in proxy.slots:
                    psc = _first_sourceclip(s.segment)
                    if psc is None or "StartTime" not in psc:
                        continue
                    old = int(psc["StartTime"].value or 0)
                    new = max(0, old + delta)
                    if new != old:
                        psc["StartTime"].value = new
                        applied += 1
            if applied:
                log.info("TC de origem rebaseado ao online: %s  TC=%s (era frame %d @%gfps, "
                         "fora do alcance do arquivo) → frame %d",
                         getattr(master, "name", ""), on_tcstr, int(cur_disp), chain_fps,
                         int(target))
                tc_rebased.append({
                    "mob_name": getattr(master, "name", "") or "",
                    "online_tc": on_tcstr,
                    "online_start": int(target),
                    "offline_start": int(cur_disp),
                    "fps": int(round(chain_fps)),
                    "drop": bool(_drop),
                })

    def _denest_timeline(f) -> dict:
        """De-nest: entrega a timeline com os clipes ORIGINAIS, sem subclip/groupclip.

        - SUBCLIP (Usage_SubClip): repointa o SourceClip da timeline direto pro
          MasterMob original, IN-PLACE (mob_id + SourceMobSlotID do slot interno +
          start += start interno do subclipe). Equivale ao "decompose subclip" do Avid.
        - GROUP CLIP / multicam (Selector): substitui o Selector pelo SourceClip da
          CÂMERA selecionada (resolvida ao original). Equivale ao "commit multicam".
        Devolve {'subclips': n, 'groupclips': n}.
        """
        counts = {"subclips": 0, "groupclips": 0}
        mobs = {str(m.mob_id): m for m in f.content.mobs}

        def _repoint_subclip(sc) -> bool:
            mob = getattr(sc, "mob", None)
            if (mob is None or type(mob).__name__ != "CompositionMob"
                    or getattr(mob, "usage", None) != "Usage_SubClip"):
                return False
            sid = getattr(sc, "slot_id", None)
            tslot = next((s for s in mob.slots if getattr(s, "slot_id", None) == sid), None)
            if tslot is None:
                tslot = next((s for s in mob.slots if s.media_kind == sc.media_kind), None)
            if tslot is None:
                return False
            inner = _first_sourceclip(tslot.segment)
            im = getattr(inner, "mob", None) if inner else None
            if im is None:
                return False
            try:
                sc.mob_id = im.mob_id
                islot = getattr(inner, "slot_id", None)
                if islot is not None:
                    sc["SourceMobSlotID"].value = islot
                cur = sc["StartTime"].value if "StartTime" in sc else 0
                sc["StartTime"].value = (cur or 0) + (getattr(inner, "start", 0) or 0)
                return True
            except Exception as e:
                log.debug("Falha ao de-nest subclip: %s", e)
                return False

        def _is_groupclip(sel):
            """True se o Selector aponta p/ um Group Clip (multicam): a fonte
            selecionada resolve a um CompositionMob com AppCode 4/5."""
            try:
                selm = sel["Selected"].value
                mob = getattr(_first_sourceclip(selm), "mob", None) if selm is not None else None
                if mob is None or type(mob).__name__ != "CompositionMob":
                    return False
                try:
                    ac = mob["AppCode"].value
                except Exception:
                    ac = getattr(mob, "application_code", None)
                return ac in (4, 5)
            except Exception:
                return False

        def walk(seg):
            k = type(seg).__name__
            if k == "SourceClip":
                if _repoint_subclip(seg):
                    counts["subclips"] += 1
                return
            if k == "Sequence":
                comps = list(seg.components)
                new = []
                changed = False
                for c in comps:
                    if type(c).__name__ == "Selector" and _is_groupclip(c):
                        # commit multicam: substitui pelo SourceClip da câmera selecionada
                        sc = _first_sourceclip(c["Selected"].value)
                        if sc is not None:
                            rep = f.create.SourceClip(media_kind=sc.media_kind)
                            rep.mob_id = sc.mob_id
                            rep["SourceMobSlotID"].value = getattr(sc, "slot_id", 1)
                            rep["StartTime"].value = getattr(sc, "start", 0) or 0
                            rep.length = c.length
                            _repoint_subclip(rep)   # a câmera pode ser subclipe
                            new.append(rep)
                            counts["groupclips"] += 1
                            changed = True
                            continue
                    walk(c)        # subclip in-place / desce em selector multi-res
                    new.append(c)
                if changed:
                    seg["Components"].value = new
                return
            if k == "NestedScope":
                for s in seg.slots:
                    walk(s.segment if hasattr(s, "segment") else s)
                return
            if k == "OperationGroup":
                try:
                    for ip in (list(seg.get("InputSegments")) or []):
                        walk(ip)
                except Exception:
                    pass
                return
            if k == "Selector":
                try:
                    sel = seg["Selected"].value
                    if sel is not None:
                        walk(sel)
                except Exception:
                    pass
                return

        try:
            for top in list(f.content.toplevel()):
                for slot in top.slots:
                    walk(slot.segment)
        except Exception as e:
            log.warning("Erro no de-nest da timeline: %s", e)
        log.info("De-nest: %d subclipe(s) achatado(s), %d groupclip(s) committed",
                 counts["subclips"], counts["groupclips"])
        return counts

    def _ensure_aafklv_def(f) -> None:
        """Garante uma ContainerDef com short_name 'AAFKLV' no dictionary.

        O create_ama_link (mxf.py) faz lookup_containerdef('AAFKLV'). AAFs
        exportados do Avid já têm essa ContainerDef (AUID 4b464141-…-01ff), mas
        registrada com o nome 'MXF' — o lookup por nome falha ('No Definition:
        aafklv'). Como as referências de definição são por AUID (o nome é só
        rótulo), renomeamos a existente; se não houver, criamos.
        """
        from aaf2.auid import AUID
        try:
            f.dictionary.lookup_containerdef("AAFKLV")
            return
        except Exception:
            pass
        klv_auid = AUID("4b464141-000d-4d4f-060e-2b34010101ff")
        existing = f.dictionary["ContainerDefinitions"].get(klv_auid, None)
        if existing is not None:
            existing.name = "ContainerDef_AAFKLV"
        else:
            d = f.create.ContainerDef(klv_auid, "ContainerDef_AAFKLV", "")
            f.dictionary["ContainerDefinitions"].append(d)

    def _build_pcm_descriptor(f, abspath, meta, old_desc):
        """Constrói um PCMDescriptor (como o Avid faz) p/ substituir o WAVEDescriptor
        do pyaaf2 — que o MC rejeita ("unrecognized audio coding"). Campos extraídos
        do AAF de referência do Avid (MC 2021) + ffprobe.
        """
        from aaf2.auid import AUID
        astream = next((s for s in (meta.get("streams") or [])
                        if s.get("codec_type") == "audio"), {})
        sr = int(float(astream.get("sample_rate") or 48000))
        bits = int(astream.get("bits_per_sample") or astream.get("bits_per_raw_sample") or 0) or 16
        ch = int(astream.get("channels") or 1)
        block = max(1, (bits + 7) // 8) * ch

        # duração em SAMPLES: do WAVEDescriptor do pyaaf2 (se houver) ou do ffprobe
        def _samples_from_meta():
            for key in ("duration_ts", "nb_samples"):
                v = astream.get(key)
                if v:
                    try: return int(v)
                    except Exception: pass
            dur = astream.get("duration") or (meta.get("format") or {}).get("duration")
            try: return int(round(float(dur) * sr)) if dur else None
            except Exception: return None

        pcm = f.create.PCMDescriptor()
        # taxa/duração: reusa o que o pyaaf2 já calculou do arquivo (WAVEDescriptor)
        try: pcm["SampleRate"].value = old_desc["SampleRate"].value
        except Exception: pcm["SampleRate"].value = sr
        try:
            pcm["Length"].value = old_desc["Length"].value
        except Exception:
            n = _samples_from_meta()
            if n is not None:
                pcm["Length"].value = n
        pcm["AudioSamplingRate"].value = sr
        pcm["Channels"].value = ch
        pcm["QuantizationBits"].value = bits
        pcm["BlockAlign"].value = block
        pcm["AverageBPS"].value = block * sr
        # ContainerFormat = MXF (AAFKLV) — o Avid usa MXF, não AAF
        try:
            _ensure_aafklv_def(f)
            pcm["ContainerFormat"].value = f.dictionary.lookup_containerdef("AAFKLV")
        except Exception as e:
            log.debug("ContainerFormat MXF no PCM falhou: %s", e)
        try: pcm["MediaContainerGUID"].value = AUID(_AMA_CONTAINER_GUID["wav"])
        except Exception: pass
        # extras que o Avid escreve (confirmados na referência)
        for prop, val in (("Locked", False), ("AudioRefLevel", -20),
                          ("SequenceOffset", 0), ("DialNorm", 27), ("DataOffset", 0)):
            try: pcm[prop].value = val
            except Exception: pass
        try: pcm["ElectroSpatial"].value = "ElectroSpatialFormulation_SingleChannelMode"
        except Exception: pass
        loc = f.create.NetworkLocator()
        loc["URLString"].value = path_to_aaf_url(abspath)
        pcm["Locator"].append(loc)
        return pcm

    def _build_wav_essence(f, leaf_mob, abspath, matnum, master):
        """Constrói a cadeia AMA de ÁUDIO do Avid p/ um WAV, em UNIDADES DE EDIÇÃO.

        O create_ama_link do pyaaf2 gera a cadeia de áudio em unidades de SAMPLE
        (slots a 96000, len 0/sample-count, sem timecode) — o Avid lê isso por um
        caminho diferente ("WaveAiff Plug-In" em vez de "WaveAiff") e não funde o
        AMA-link → fica offline. A referência do Avid usa: master → SourceMob PCM
        (essência, instance 0xb1) → SourceMob ImportDescriptor (tape, 0xa1, com slot
        Timecode), TUDO na edit rate do projeto (24000/1001), len em frames.

        Reusamos o `leaf_mob` (o SourceMob-folha offline já relinkado) como o TAPE:
        ele já tem o slot Timecode + sound slots na edit rate + ImportDescriptor com
        a URL do original. Criamos só o SourceMob PCM (b1) entre o master e o tape.
        Devolve o SourceMob PCM (que o caller repointa a partir do master).
        """
        import os as _os
        # edit rate + comprimento (frames) a partir do 1º sound slot do master
        snd = next((s for s in master.slots if s.media_kind == "Sound"), None)
        if snd is None:
            raise RuntimeError(f"master {master.name!r} sem sound slot")
        edit_rate = snd["EditRate"].value
        clip_len = int(snd.segment.length)
        # slot de som do leaf (tape) a referenciar
        leaf_snd = next((s.slot_id for s in leaf_mob.slots if s.media_kind == "Sound"), 2)

        meta = _ffprobe_meta(abspath)
        pcm = _build_pcm_descriptor(f, abspath, meta, None)

        pcm_mob = f.create.SourceMob()
        pcm_mob.name = _os.path.basename(abspath)
        pcm_mob.descriptor = pcm
        # 1 sound slot (slot_id=2, como a referência), edit rate do projeto
        slot = pcm_mob.create_sound_slot(edit_rate)
        slot.slot_id = 2
        sc = leaf_mob.create_source_clip(leaf_snd, start=0, length=clip_len,
                                         media_kind="sound")
        slot.segment["Components"].append(sc)
        slot.segment.length = clip_len
        f.content.mobs.append(pcm_mob)
        # mob_id no esquema do Avid: instance 0xb1 + matnum REAL do arquivo
        pcm_mob.mob_id = _avid_chain_id(leaf_mob.mob_id, matnum, 0xb1)
        log.info("Essência PCM (edit-rate) criada p/ %s: len=%d @ %s",
                 pcm_mob.name, clip_len, edit_rate)
        return pcm_mob

    def _build_ama_source(f, local_path, umid_matnum=None):
        """create_ama_link no original → SourceMob de essência (descarta o master extra).

        Format-aware: MXF é linkado direto (pyaaf2 lê o header); demais formatos
        (QuickTime/.mov/.mp4, WAV, etc.) precisam do metadata do ffprobe. Não fica
        preso ao XDCAM/MXF — qualquer formato de câmera que o pyaaf2+ffmpeg conheçam.
        Corrige a URLString pro formato Avid e seta o MediaContainerGUID por tipo.

        `umid_matnum` (4 grupos): p/ formatos SEM UMID embutido (WAV/QuickTime), o
        pyaaf2 gera MobIDs aleatórios → o Avid não casa o AMA-link por identidade.
        Reescrevemos o material number da cadeia gerada para `umid_matnum` (lido do
        SourceMob-folha offline = o que o Avid re-deriva ao AMA-linkar o arquivo).
        """
        import os as _os
        from aaf2.auid import AUID
        import sys as _sys, io as _io

        abspath = _os.path.abspath(str(local_path))   # as_uri() exige caminho absoluto
        ext = _os.path.splitext(abspath)[1].lower()
        is_mxf = ext in _MXF_EXTS

        _patch_pyaaf2_mpeg2()     # corrige o bug de MXF MPEG2 (no-op p/ não-MXF)
        if is_mxf:
            _ensure_aafklv_def(f)
            meta = {}
        else:
            meta = _ffprobe_meta(abspath)   # QuickTime/WAV/etc. exigem o ffprobe

        _saved = _sys.stdout
        try:
            _sys.stdout = _io.StringIO()    # silencia o dump do pyaaf2
            result = f.content.create_ama_link(abspath, meta)
        finally:
            _sys.stdout = _saved

        new_master = next((m for m in result if type(m).__name__ == "MasterMob"), None)
        new_source = next((m for m in result if type(m).__name__ == "SourceMob"), None)
        if new_master is not None:
            # Mantemos o MasterMob ORIGINAL (a timeline referencia o mob_id dele);
            # o master que o create_ama_link cria é descartado.
            try:
                f.content['Mobs'].pop(new_master.mob_id)
            except Exception as e:
                log.warning("Não removi o MasterMob extra do AMA-link: %s", e)
        if new_source is None:
            raise RuntimeError(f"create_ama_link não devolveu SourceMob para {abspath}")

        # Formatos sem UMID embutido (WAV/QuickTime): o pyaaf2 gera os source mobs
        # da cadeia (essência + tape) no MESMO instance (0x00) e com material numbers
        # aleatórios/distintos → o Avid não funde o AMA-link por identidade (fica
        # offline). Reescrevemos cada source mob p/ o matnum REAL do arquivo + o
        # instance-byte por papel (tape/import=0xa1, essência=0xb1), espelhando a
        # cadeia que o Avid cria ao AMA-linkar o mesmo arquivo. Corrigimos os
        # SourceClips internos. (MXF já vem com o UMID do header → não mexemos.)
        if not is_mxf and umid_matnum:
            gen_sources = [m for m in result if type(m).__name__ == "SourceMob"]
            remap = {}
            for sm in gen_sources:
                dn = type(getattr(sm, "descriptor", None)).__name__
                inst = 0xa1 if dn in ("ImportDescriptor", "TapeDescriptor") else 0xb1
                new_id = _avid_chain_id(sm.mob_id, umid_matnum, inst)
                if str(new_id) != str(sm.mob_id):
                    remap[str(sm.mob_id)] = new_id
                    sm.mob_id = new_id
            if remap:
                for sm in gen_sources:
                    for sc in _iter_sourceclips(sm):
                        if str(sc.mob_id) in remap:
                            sc.mob_id = remap[str(sc.mob_id)]
                log.info("Matnum AMA alinhado ao arquivo (%s): %s",
                         _os.path.basename(abspath), umid_matnum)

        desc = getattr(new_source, "descriptor", None)
        if desc is not None:
            # GUID por tipo: força MXF/QuickTime/WAV (o pyaaf2 erra o de QuickTime →
            # deixa "Generic", e o Avid não consegue tocar). Outros mantêm o do pyaaf2.
            ckey = _ama_container_key(ext)
            guid = _AMA_CONTAINER_GUID.get(ckey)
            if guid:
                try:
                    desc["MediaContainerGUID"].value = AUID(guid)
                except Exception:
                    pass
            hguid = _AMA_HANDLER_GUID.get(ckey)
            if hguid:
                try:
                    desc["ContainerHandlerGUID"].value = AUID(hguid)
                except Exception as e:
                    log.debug("Não setei ContainerHandlerGUID: %s", e)
            avid_url = path_to_aaf_url(abspath)
            try:
                for loc in (desc["Locator"].value or []):
                    loc["URLString"].value = avid_url
            except Exception as e:
                log.debug("Falha ao reescrever locator do AMA source: %s", e)

            # QuickTime/.mov/.mp4: o Avid AMA-linka o vídeo como descriptor SÓ-VÍDEO
            # (a referência usa CDCIDescriptor); o áudio embutido (geralmente AAC) que o
            # pyaaf2 descreve como PCM causa "PMM_MISMATCH_AUDIO_FORMAT". Removemos o
            # sub-descriptor de áudio e os sound slots → vídeo toca, sem o erro. (O áudio
            # da câmera embutida não é o que entra na timeline; suportá-lo = refino futuro.)
            if ckey == "quicktime":
                try:
                    subs = list(desc["FileDescriptors"].value or [])
                    vids = [s for s in subs if type(s).__name__ in ("CDCIDescriptor", "RGBADescriptor")]
                    if vids and len(vids) < len(subs):
                        desc["FileDescriptors"].value = vids
                    keep = [sl for sl in new_source.slots if sl.media_kind != "Sound"]
                    if len(keep) < len(list(new_source.slots)):
                        new_source["Slots"].value = keep
                except Exception as e:
                    log.debug("Falha ao tornar QuickTime só-vídeo: %s", e)

            # WAV/AIFF: o pyaaf2 gera WAVEDescriptor, que o MC rejeita ("unrecognized
            # audio coding"). O Avid usa PCMDescriptor — trocamos por um fiel.
            elif ckey == "wav" and type(desc).__name__ == "WAVEDescriptor":
                try:
                    pcm = _build_pcm_descriptor(f, abspath, meta, desc)
                    new_source.descriptor = pcm
                except Exception as e:
                    log.warning("Falha ao converter WAVE→PCMDescriptor (%s): %s",
                                _os.path.basename(abspath), e)
        return new_source

    def _mob_timecode(mob):
        """(componente Timecode, edit_rate) do 1º slot de timecode do mob, ou (None, None)."""
        for s in mob.slots:
            stack = [s.segment]
            while stack:
                x = stack.pop()
                if type(x).__name__ == "Timecode":
                    er = None
                    try: er = s["EditRate"].value
                    except Exception: pass
                    return x, er
                stack.extend(getattr(x, "components", []) or [])
        return None, None

    def _source_tc_for_master(f, master):
        """TC de ORIGEM exibido p/ o MasterMob (frames), espelhando o que o Avid mostra
        na coluna Start. Desce a cadeia offline (slot de imagem) acumulando os
        `start` dos SourceClips (inclui o precharge do codec) até achar um slot de
        Timecode; devolve (start, fps, drop, edit_rate, length) ou None.

        Deve rodar ANTES do repoint do master (a cadeia offline ainda intacta).
        """
        mobs = {str(m.mob_id): m for m in f.content.mobs}
        slots = sorted(master.slots, key=lambda s: 0 if s.media_kind == "Picture" else 1)
        for slot in slots:
            sc = _first_sourceclip(slot.segment)
            if sc is None:
                continue
            acc = int(sc["StartTime"].value or 0) if "StartTime" in sc else 0
            cur = mobs.get(str(sc.mob_id))
            seen = {str(master.mob_id)}
            depth = 0
            while cur is not None and depth < 8:
                cid = str(cur.mob_id)
                if cid in seen:
                    break
                seen.add(cid)
                tc, er = _mob_timecode(cur)
                if tc is not None:
                    return (int(tc["Start"].value or 0) + acc,
                            tc["FPS"].value, bool(tc["Drop"].value), er, tc.length)
                nxt = None
                for s in cur.slots:
                    r = _first_sourceclip(s.segment)
                    if r is not None and str(r.mob_id) != cid:
                        acc += int(r["StartTime"].value or 0) if "StartTime" in r else 0
                        nxt = mobs.get(str(r.mob_id))
                        if nxt is not None:
                            break
                cur = nxt
                depth += 1
        return None

    def _grafted_tape_mob(f, new_source):
        """O SourceMob de tape (ImportDescriptor/TapeDescriptor) alcançável a partir
        da essência enxertada, ou None."""
        mobs = {str(m.mob_id): m for m in f.content.mobs}
        cur = new_source
        seen = set()
        depth = 0
        while cur is not None and depth < 6:
            cid = str(cur.mob_id)
            if cid in seen:
                break
            seen.add(cid)
            dn = type(getattr(cur, "descriptor", None)).__name__
            if dn in ("ImportDescriptor", "TapeDescriptor"):
                return cur
            nxt = None
            for s in cur.slots:
                r = _first_sourceclip(s.segment)
                if r is not None and str(r.mob_id) != cid:
                    nxt = mobs.get(str(r.mob_id))
                    if nxt is not None:
                        break
            cur = nxt
            depth += 1
        return None

    def _graft_ama_essence(f) -> None:
        """Enxerta a essência AMA do original sob cada MasterMob relinkado.

        O Avid só consegue criar o sample mapper (tocar a mídia) quando o
        descriptor de essência descreve o arquivo REAL. No relink cirúrgico, o
        descriptor de 1º nível ainda descreve o proxy do Avid MediaFiles → o MC
        reconhece o link mas falha ao tocar ("SelectFileMob() failed").

        Aqui, para cada MasterMob, geramos via create_ama_link a SourceMob de
        essência do original (MultipleDescriptor com sub-descriptors lidos do
        arquivo) e repontamos os SourceClips dos slots do master para ela —
        preservando o mob_id, os slot_ids e os start/length do master (que a
        timeline referencia). Também marcamos o master com _IMPORTED_AMA.
        """
        import os as _os
        cache: dict = {}   # local_path → SourceMob de essência (1 por arquivo)
        # Snapshot ANTES de criar novos masters (que são descartados em _build_ama_source).
        masters = [m for m in f.content.mastermobs()]
        for master in masters:
            local, leaf_id = _master_relink_local(f, master)
            if not local or not _os.path.exists(local):
                continue
            matnum = _material_num(leaf_id) if leaf_id else None
            ext = _os.path.splitext(local)[1].lower()
            is_wav = ext in _WAV_EXTS
            # TC de origem (frames) — computado ANTES do repoint, com a cadeia offline
            # ainda intacta. WAV reusa o leaf (que já tem o slot Timecode); só o vídeo
            # via create_ama_link perde o TC e precisa que a gente o reinsira no tape.
            src_tc = None if is_wav else _source_tc_for_master(f, master)
            # REBASE: prefere o TC EMBUTIDO do arquivo ONLINE (verdade) — o offline pode ter
            # TC zerado/errado (proxy). O tape enxertado tem o arquivo como origem (frame 0),
            # então o TC do online (frame 0) é o Start correto; sem isso o Avid posiciona o
            # clipe no TC do proxy (ex.: 00:00:00:00) e a referência sai do ponto.
            online_tc = None if is_wav else _probe_online_tc(local)
            try:
                if local not in cache:
                    if is_wav and leaf_id and matnum:
                        # Áudio: cadeia AMA em edit-rate (reusa o leaf como tape),
                        # NÃO a cadeia sample-based do create_ama_link.
                        leaf_mob = next((m for m in f.content.mobs
                                         if str(m.mob_id) == leaf_id), None)
                        if leaf_mob is None:
                            raise RuntimeError("leaf do WAV não encontrado")
                        cache[local] = _build_wav_essence(f, leaf_mob, local, matnum, master)
                    else:
                        cache[local] = _build_ama_source(f, local, umid_matnum=matnum)
                new_source = cache[local]
            except Exception as e:
                log.warning("Falha ao gerar essência AMA p/ %s: %s",
                            getattr(master, "name", ""), e)
                continue
            pic_slots = [s.slot_id for s in new_source.slots if s.media_kind == "Picture"]
            snd_slots = [s.slot_id for s in new_source.slots if s.media_kind == "Sound"]
            snd_i = 0
            repointed = 0
            for slot in master.slots:
                sc = _first_sourceclip(slot.segment)
                if sc is None:
                    continue
                if slot.media_kind == "Picture" and pic_slots:
                    sc.mob_id = new_source.mob_id
                    sc["SourceMobSlotID"].value = pic_slots[0]
                    repointed += 1
                elif slot.media_kind == "Sound" and snd_slots:
                    sc.mob_id = new_source.mob_id
                    sc["SourceMobSlotID"].value = snd_slots[min(snd_i, len(snd_slots) - 1)]
                    snd_i += 1
                    repointed += 1
            # Reinsere o TC de origem no tape do vídeo (a cadeia do create_ama_link não o
            # traz → Start/End ficam zerados, quebrando o handoff p/ DaVinci/VFX e o
            # posicionamento no Avid). Prefere o TC do ONLINE (frame 0); cai no offline só
            # se o arquivo não tiver TC legível. O tape virou origem do clipe (posição 0).
            if online_tc is not None or src_tc is not None:
                tape = _grafted_tape_mob(f, new_source)
                if tape is not None and _mob_timecode(tape)[0] is None:
                    # Decisão de rebase: mantém o TC OFFLINE quando ele CONCORDA com o online
                    # (preserva o comportamento validado, que inclui o precharge do codec);
                    # rebaseia ao ONLINE só quando o offline está ausente ou DIVERGE muito —
                    # o caso do proxy com TC zerado/errado (ex.: C004/C005). Tolerância = 1s
                    # (o precharge é de poucos frames; a divergência do zerado é de horas).
                    off_start = src_tc[0] if src_tc is not None else None
                    on_start = online_tc[0] if online_tc is not None else None
                    on_fps = online_tc[1] if online_tc is not None else None
                    tol = int(on_fps or 30)  # ~1 segundo
                    use_online = (online_tc is not None and
                                  (off_start is None or abs(int(off_start) - int(on_start)) > tol))
                    if use_online:
                        start, fps, drop, er, length, tc_str = online_tc
                        source = "online"
                    else:
                        start, fps, drop, er, length = src_tc
                        tc_str = None
                        source = "offline"
                    er = er or new_source.slots[0]["EditRate"].value
                    try:
                        tcslot = tape.create_timecode_slot(er, int(fps), bool(drop), length)
                        tcslot.segment["Start"].value = int(start)
                        log.info("TC de origem (%s) no tape: %s start=%d fps=%s%s",
                                 source, getattr(master, "name", ""), int(start), fps,
                                 f" tc={tc_str}" if tc_str else "")
                        # Anota o rebase efetivo (online substituiu um offline divergente)
                        # p/ a UI avisar o editor.
                        if use_online and off_start is not None:
                            tc_rebased.append({
                                "mob_name": getattr(master, "name", "") or "",
                                "online_start": int(start),
                                "online_tc": tc_str,
                                "offline_start": int(off_start),
                                "fps": int(fps),
                                "drop": bool(drop),
                            })
                    except Exception as e:
                        log.warning("Falha ao reinserir TC no tape de %s: %s",
                                    getattr(master, "name", ""), e)
            _add_imported_ama(f, master)
            ama_promoted.append({
                "master": getattr(master, "name", "") or "",
                "source_desc": type(new_source.descriptor).__name__,
                "slots_repointed": repointed,
                "local": local,
            })
            log.info("Essência AMA enxertada: master=%s slots=%d arquivo=...%s",
                     getattr(master, "name", ""), repointed, local[-40:])

    if dry_run:
        log.info("[DRY RUN] Inspecionando AAF: %s", src.name)
        with aaf2.open(str(src), "r") as f:
            _process_mobs(f)
    else:
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(str(src), str(out))
        except OSError as e:
            raise RuntimeError(
                f"Falha ao copiar AAF para '{out}': {e}. "
                "Verifique espaço em disco e permissões."
            ) from e
        log.info("AAF copiado: %s → %s", src.name, out.name)

        try:
            with aaf2.open(str(out), 'rw') as f:
                # De-nest PRIMEIRO: achata subclip/groupclip → a timeline passa a
                # referenciar os MasterMobs originais (que depois são renomeados/relinkados).
                if denest:
                    denest_result = _denest_timeline(f)
                _process_mobs(f)
                # Rebase de TC ao arquivo ONLINE (caminho NATIVO, roda sempre): corrige o
                # caso do online com TC ≠ do que o AAF herdou (ex.: original com TC zerado)
                # → o clipe cairia fora do alcance do arquivo e ficaria offline no Avid.
                if not dry_run:
                    _rebase_source_tc(f)
                if ama_autolink:
                    # Enxerta a essência AMA dos clipes COM URL/UMID (AMA-based, ex.
                    # EFEITOS) — funde por matnum. Offline de fita (só name_map) não
                    # entra aqui (graft não funde .mp4) → vai pro relink nativo abaixo.
                    _graft_ama_essence(f)
                else:
                    _align_source_ids(f)   # legado: alinha MobIDs ao UMID dos arquivos
                # Relink NATIVO p/ offline de fita: corrige a caixa dos nomes p/ casar
                # os originais (o Avid relinka por nome de fonte + TC).
                if name_map:
                    names_renamed += _rename_offline_to_match(f, name_map)
                # Tira sufixos do Avid (.new/.sync) dos nomes → relink por nome no MC.
                names_cleaned += _clean_mob_names(f)
                marcar_aaf(f)   # quem tratou fica registrado (origem.py)
            # pyaaf2 chama f.save() automaticamente no __exit__
        except Exception:
            # Rollback: remove arquivo de saída parcialmente escrito
            try:
                out.unlink()
                log.warning("Rollback: '%s' removido após falha na escrita.", out.name)
            except OSError:
                pass
            raise

        log.info(
            "AAF relinkado: %d atualizado(s), %d sem mapeamento, %d erro(s), "
            "%d MobID alinhado(s), %d AMA promovido(s), %d nome(s) limpo(s)",
            len(mobs_updated), len(mobs_skipped), error_count,
            len(ids_aligned), len(ama_promoted), names_cleaned,
        )

    return {
        "output_path":   str(out),
        "updated_count": len(mobs_updated),
        "skipped_count": len(mobs_skipped),
        "error_count":   error_count,
        "mobs_updated":  mobs_updated,
        "mobs_skipped":  mobs_skipped,
        "ids_aligned":   ids_aligned,
        "ama_promoted":  ama_promoted,
        "tc_rebased":    tc_rebased,
        "names_cleaned": names_cleaned,
        "names_renamed": names_renamed,
        "denested_subclips":  denest_result.get("subclips", 0),
        "denested_groupclips": denest_result.get("groupclips", 0),
        "dry_run":       dry_run,
    }
