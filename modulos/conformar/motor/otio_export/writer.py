"""
otio_export/writer.py — gera um `.otio` (OpenTimelineIO) a partir dos segmentos +
matches do app. OTIO é o formato neutro de timeline: o DaVinci Resolve (free e Studio)
importa nativo, e serve de baseline aberto p/ outras NLEs.

FASE 1 (baseline aberto):
    - todas as tracks de VÍDEO e ÁUDIO
    - cortes (cada segmento vira um Clip no lugar absoluto da timeline)
    - relink (Clip casado → ExternalReference com o caminho do original;
      Clip sem match → MissingReference, p/ o editor religar à mão)
    - gaps (espaços vazios entre clipes viram Gap — timeline contígua)
    - velocidade CONSTANTE (LinearTimeWarp(time_scalar=speed_ratio))

Fora do escopo da Fase 1 (refino futuro, ver ROADMAP):
    - transições reais (cross-dissolve): aqui são "achatadas" — a duração da
      transição é absorvida estendendo o clipe anterior (sem buraco preto), igual
      ao comportamento atual do DRT.
    - rampa de velocidade: clipes ramped entram com a velocidade média (constante),
      como nota no CLAUDE.md (export de rampa ainda é linear).

Modelo de tempo
---------------
Os segmentos do parser usam frames NOMINAIS non-drop contínuos, com o TC formatado por
`round(fps)` (ex.: 25, 24, 30). Para casar com isso, o OTIO usa a mesma taxa inteira
nominal (`rate`) em toda a timeline → cortes frame-exatos. Drop-frame e o start-TC real
do AAF são só exibição; `global_start_time` recebe o start real (default 01:00:00:00).

Uso programático:
    from otio_export.writer import build_otio
    build_otio(segments, match_results, "saida.otio", timeline_fps=25)
"""
from __future__ import annotations

import os
from pathlib import Path


def _tc_to_frames(tc: str, rate: int) -> int:
    """'HH:MM:SS:FF' → frames nominais na taxa `rate` (non-drop)."""
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * rate + f


def _media_track_number(seg: dict) -> int:
    """Número de track de áudio 1-based (A1=1…). Tracks de áudio chegam como 1000+."""
    return int(seg.get("track") or 1000) - 1000 + 1


def _media_origin(path: str, tc_base: int, is_audio: bool = False) -> tuple[int, int | None]:
    """VÍDEO: (tc_embutido_frames, total_frames) do arquivo casado, em frames na base
    `tc_base`. O Resolve endereça o VÍDEO no espaço do TC EMBUTIDO da mídia (tag
    `timecode`), então o in-point no OTIO tem que ser ABSOLUTO (TC embutido + offset do
    AAF) — senão clipes com TC≠0 caem fora do alcance e entram offline/zerados. Arquivos
    com TC 0 (drones) dão offset 0 → sem mudança. Reusa o probe ffprobe cacheado do DRT.

    (Áudio NÃO usa isto — o Resolve endereça áudio a partir do início do arquivo, então o
    in-point fica relativo ao frame 0; ver _make_clip.)"""
    try:
        from drp.writer import _media_meta
        nb, _fps, tc = _media_meta(path)
        start = _tc_to_frames(tc, tc_base) if tc else 0
        return start, nb
    except Exception:
        return 0, None


def _audio_total_frames(path: str, rate_fps: float) -> int | None:
    """Duração total do WAV em frames (na taxa real `rate_fps`). Usado p/ o
    available_range = [0, total] do áudio — necessário p/ o Resolve HONRAR o in-point
    (sem available ele toca todo clipe do início do arquivo)."""
    try:
        from drp.writer import _audio_meta
        _mst, dur, _sr, _ch, _dts = _audio_meta(path)
        return round(dur * rate_fps) if dur else None
    except Exception:
        return None


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #
def build_otio(segments: list, match_results: list, output_otio: str,
               timeline_name: str | None = None, timeline_fps: float = 25.0,
               drop_frame: bool = False, start_frames: int | None = None,
               origem: str | None = None) -> dict:
    """Gera `output_otio` (JSON OTIO) a partir de `segments` + `match_results`.

    `origem` = o NLE de onde veio a timeline ('avid', 'premiere', 'resolve'): vai, com a versão do app, nos metadados
    `DeLaPraCa` da timeline — o OTIO diz quem o escreveu, como o `Resolve_OTIO` (origem.py).

    Retorna um dict de estatísticas (clipes de vídeo/áudio, mídias, tracks).
    """
    import opentimelineio as otio
    RationalTime = otio.opentime.RationalTime
    TimeRange = otio.opentime.TimeRange

    # Duas taxas distintas (CRÍTICO p/ 23.976/29.97/59.94):
    #   tc_base = round(fps)  → base inteira p/ converter TC 'HH:MM:SS:FF' ↔ frames
    #             (o campo FF vai de 0..base-1; non-drop usa a base inteira).
    #   rate_fps = fps REAL (ex.: 24000/1001) → rótulo de taxa dos RationalTime.
    # Se rotularmos a 24 um material 23.976, RationalTime(frames, 24) dá os SEGUNDOS
    # errados: em TC altos (ex.: 09:33 ≈ 826k frames) o desvio de 0,1% vira ~800 frames
    # e o Resolve joga o in-point ANTES do início real do arquivo → offline / frame
    # errado (claquete). O número do frame é o mesmo; só o rótulo da taxa muda.
    tc_base = max(1, round(float(timeline_fps or 25.0)))
    rate_fps = float(timeline_fps) if timeline_fps else tc_base
    if start_frames is None:
        start_frames = 3600 * tc_base   # 01:00:00:00 (padrão editorial / Resolve)

    def rt(frames: int) -> "otio.opentime.RationalTime":
        return RationalTime(int(frames), rate_fps)

    # matched_path por segment_index (rejeitados contam como sem match)
    matched: dict[int, str] = {}
    # correção de offset de fonte (frames, domínio nativo) achada pelo match visual
    offc_by_index: dict[int, int] = {}
    for r in (match_results or []):
        if r and r.get("matched_path") and not r.get("rejected"):
            matched[r.get("segment_index")] = r["matched_path"]
            offc_by_index[r.get("segment_index")] = int(r.get("source_offset_correction") or 0)

    # Classifica os segmentos com índice preservado (p/ casar com match_results)
    def _is_real_clip(s: dict) -> bool:
        if not s or s.get("is_gap") or s.get("is_transition") or s.get("is_effect"):
            return False
        nm = (s.get("clip_name") or "").strip()
        return bool(nm) and not nm.startswith("(")

    # Spans de transição por track (frames absolutos 0-based) — p/ achatar
    v_trans: dict[int, list[tuple[int, int]]] = {}
    a_trans: dict[int, list[tuple[int, int]]] = {}
    for s in (segments or []):
        if not s or not s.get("is_transition"):
            continue
        st = _tc_to_frames(s["timeline_tc_in"], tc_base)
        en = st + int(s.get("duration_frames") or 0)
        if s.get("is_audio"):
            a_trans.setdefault(_media_track_number(s), []).append((st, en))
        else:
            v_trans.setdefault(int(s.get("track") or 1), []).append((st, en))

    # Clipes reais por track
    v_by_track: dict[int, list[tuple[int, dict]]] = {}
    a_by_track: dict[int, list[tuple[int, dict]]] = {}
    for i, s in enumerate(segments or []):
        if not _is_real_clip(s):
            continue
        if s.get("is_audio"):
            a_by_track.setdefault(_media_track_number(s), []).append((i, s))
        else:
            v_by_track.setdefault(int(s.get("track") or 1), []).append((i, s))

    media_refs: dict[str, "otio.schema.ExternalReference"] = {}
    stats = {"video_clips": 0, "audio_clips": 0, "unmatched": 0}

    def _media_ref(path: str | None, name: str, media_total: int | None,
                   media_start: int, media_rate: float):
        """ExternalReference (relink) ou MissingReference (sem match). Quando há duração,
        seta o available_range começando no TC embutido — coerente com o in-point absoluto
        do source_range (ver _media_origin). `media_rate` = taxa do domínio da mídia (nativa
        p/ clipe de fps diferente da timeline; igual à da timeline no caso comum)."""
        if not path:
            stats["unmatched"] += 1
            return otio.schema.MissingReference(name=name)
        ap = os.path.abspath(path)
        if ap not in media_refs:
            media_refs[ap] = ap   # marca o arquivo único (p/ contagem de "mídias")
        avail = None
        if media_total:
            avail = TimeRange(start_time=RationalTime(int(media_start), media_rate),
                              duration=RationalTime(int(media_total), media_rate))
        # Resolve aceita caminho POSIX absoluto direto como target_url.
        return otio.schema.ExternalReference(target_url=ap, available_range=avail)

    def _make_clip(seg: dict, matched_path: str | None, eff_dur: int, offset_corr: int = 0):
        """Clip OTIO: source_range (frames da mídia) + relink + velocidade.

        `eff_dur` = duração efetiva na TIMELINE em frames (já inclui a absorção de
        transição).

        fps/velocidade (camada de tradução p/ o Resolve): o Resolve conforma a fps da mídia
        à da timeline sozinho. Para clipe com fps≠ (conformação do Avid), endereçamos a mídia
        no DOMÍNIO NATIVO dela (taxa nativa, TC lido na base nativa) e a duração consumida =
        eff_dur/conform_ratio frames nativos — em segundos isso é exatamente eff_dur/timeline,
        então a posição na timeline fica idêntica SEM enviar a velocidade de conform. Só a
        velocidade RELATIVA (criativa, relative_speed) vira LinearTimeWarp; conform puro (≈1)
        não anexa efeito (senão o Resolve aplica a conformação duas vezes e o OUT sai fora)."""
        sr = float(seg.get("speed_ratio") or 1.0) or 1.0
        rel = float(seg.get("relative_speed") or sr) or sr
        conform = float(seg.get("conform_ratio") or 1.0) or 1.0
        is_audio = bool(seg.get("is_audio"))
        name = seg.get("clip_name") or "clip"
        nat = (seg.get("media_ref") or {}).get("source_fps")
        # Domínio da mídia: nativo quando a fps difere da timeline (conformação); senão o da TL.
        fps_differ = (not is_audio) and bool(nat) and abs(conform - 1.0) > 0.012
        if fps_differ:
            m_base, m_rate = max(1, round(float(nat))), float(nat)
        else:
            m_base, m_rate = tc_base, rate_fps

        def mrt(frames: int) -> "otio.opentime.RationalTime":
            return RationalTime(int(frames), m_rate)

        # VÍDEO: in-point ABSOLUTO na mídia = TC embutido (na base nativa) + offset do AAF +
        # correção visual. ÁUDIO: in-point RELATIVO ao início do arquivo (sample 0); o Resolve
        # endereça áudio do começo do arquivo, não pelo BWF TC. available_range = [0, dur]
        # mesmo assim (sem ele o Resolve ignora o source_range.start).
        media_start, media_total = (0, None)
        if matched_path and not is_audio:
            media_start, media_total = _media_origin(matched_path, m_base, False)
        elif matched_path and is_audio:
            media_total = _audio_total_frames(matched_path, m_rate)
        src_start = media_start + int(seg.get("source_start_frames") or 0) + int(offset_corr or 0)
        # Duração consumida na mídia (domínio nativo). Same-fps: = eff_dur. Conform: eff_dur/conform.
        media_dur = max(1, round(eff_dur / conform)) if fps_differ else max(1, eff_dur)
        clip = otio.schema.Clip(
            name=name,
            media_reference=_media_ref(matched_path, name, media_total, media_start, m_rate),
            source_range=TimeRange(start_time=mrt(src_start), duration=mrt(media_dur)),
        )
        if abs(rel - 1.0) > 1e-3:
            clip.effects.append(otio.schema.LinearTimeWarp(time_scalar=rel))
        return clip

    def _spans_cover(trans_spans: list[tuple[int, int]], a: int, b: int) -> bool:
        """True se algum span de transição cai dentro do gap (a, b) — então o gap é
        uma transição (achatada estendendo o clipe anterior), não um vazio real."""
        for (ts, te) in trans_spans:
            if ts < b and te > a:   # interseção com (a, b)
                return True
        return False

    def _build_track(clips: list[tuple[int, dict]], trans_spans: list[tuple[int, int]],
                     kind):
        """Monta uma Track OTIO (vídeo ou áudio) com Clips + Gaps por posição absoluta.

        Transições entre dois clipes são achatadas: o clipe anterior é estendido até o
        início do próximo (sem buraco preto). Gaps "de verdade" viram otio.schema.Gap.
        """
        track = otio.schema.Track(kind=kind)
        # ordena por início absoluto
        items = sorted(clips, key=lambda it: _tc_to_frames(it[1]["timeline_tc_in"], tc_base))
        # pré-calcula início/dur de cada clipe
        placed = []
        for idx, s in items:
            st = _tc_to_frames(s["timeline_tc_in"], tc_base)
            du = int(s.get("duration_frames") or 0)
            if du <= 0:
                continue
            placed.append([st, du, idx, s])
        # absorve transições: estende cada clipe até o próximo quando há transição no meio
        for k in range(len(placed) - 1):
            st, du, idx, s = placed[k]
            nxt_st = placed[k + 1][0]
            cur_end = st + du
            if nxt_st > cur_end and _spans_cover(trans_spans, cur_end, nxt_st):
                placed[k][1] = nxt_st - st   # estende a duração até o próximo clipe

        cursor = 0
        for st, du, idx, s in placed:
            # corta sobreposição (segurança: OTIO não permite itens sobrepostos)
            if st < cursor:
                du -= (cursor - st)
                st = cursor
            if du <= 0:
                continue
            if st > cursor:
                track.append(otio.schema.Gap(
                    source_range=TimeRange(start_time=rt(0), duration=rt(st - cursor))))
            track.append(_make_clip(s, matched.get(idx), du, offc_by_index.get(idx, 0)))
            cursor = st + du
            if kind == otio.schema.TrackKind.Video:
                stats["video_clips"] += 1
            else:
                stats["audio_clips"] += 1
        return track

    tl = otio.schema.Timeline(name=timeline_name or "Timeline")
    tl.global_start_time = rt(start_frames)
    from origem import CHAVE_OTIO, versao_do_app
    tl.metadata[CHAVE_OTIO] = {"versao": versao_do_app(), **({"origem": origem} if origem else {})}

    # Tracks de vídeo (V1, V2…) e áudio (A1, A2…) em ordem ascendente de número.
    for t in sorted(v_by_track):
        tr = _build_track(v_by_track[t], v_trans.get(t, []), otio.schema.TrackKind.Video)
        tr.name = f"V{t}"
        tl.tracks.append(tr)
    for t in sorted(a_by_track):
        tr = _build_track(a_by_track[t], a_trans.get(t, []), otio.schema.TrackKind.Audio)
        tr.name = f"A{t}"
        tl.tracks.append(tr)

    Path(output_otio).parent.mkdir(parents=True, exist_ok=True)
    otio.adapters.write_to_file(tl, output_otio, adapter_name="otio_json")

    return {
        "output": output_otio,
        "clips_generated": stats["video_clips"],
        "audio_clips": stats["audio_clips"],
        "pool_clips": len(media_refs),
        "video_tracks": len(v_by_track),
        "audio_tracks": len(a_by_track),
        "unmatched": stats["unmatched"],
        "timeline_name": timeline_name,
    }


if __name__ == "__main__":
    import json
    import sys
    from aaf.parser import parse_aaf
    if len(sys.argv) < 3:
        print("uso: python -m otio_export.writer <aaf> <saida.otio> [timeline_name]\n"
              "(teste: casa cada segmento consigo mesmo via clip_name como matched_path)")
        raise SystemExit(1)
    parsed = parse_aaf(sys.argv[1])
    segs = parsed["segments"]
    mr = [{"segment_index": i, "matched_path": f"/tmp/{s.get('clip_name')}.mxf"}
          for i, s in enumerate(segs) if s.get("clip_name")]
    res = build_otio(
        segs, mr, sys.argv[2],
        timeline_name=sys.argv[3] if len(sys.argv) > 3 else None,
        timeline_fps=parsed.get("timeline_fps", 25),
        start_frames=parsed.get("timeline_start_frames"),
    )
    print(json.dumps(res, indent=2))
