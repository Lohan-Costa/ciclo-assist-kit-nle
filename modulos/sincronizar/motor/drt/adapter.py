"""
drt/adapter.py — traduz uma DIÁRIA do Órbita para a entrada do writer do DRT.

A fronteira core↔adapter (ADR 0002): o motor de sync (`sync/`) não conhece o
Resolve. Este módulo é o ÚNICO que sabe o formato de entrada do `drt.writer`
(o mesmo `segments`/`match_results` que o RELINKER produz a partir de um AAF).
Para o Órbita o "match" é trivial: cada clipe JÁ É um arquivo real, então
`matched_path` é o próprio caminho do clipe.

Mapa (diária pós-sync, com as posições já normalizadas para origin=0):

  VÍDEO  — uma track por CÂMERA FÍSICA (grupo). V1 = primeiro grupo, como no
           PRPROJ (convenção de NLE: V1 embaixo). Cada clipe entra INTEIRO
           (source_start=0), na sua posição de timeline, a 100% (sem retime).
  ÁUDIO  — o som direto (multicanal) vira N tracks MONO, uma por canal, nas
           PRIMEIRAS tracks (A1..An). Com a opção "áudio da câmera", cada câmera
           física ganha uma track MONO (canal 0, guia de sync) ABAIXO do som
           direto (A(n+1)..). No AudioTrackVec do Resolve vec[0] = A1 (topo),
           então o som direto fica nos primeiros números de track e a câmera nos
           seguintes (ver `daily_to_segments`).

SIMPLIFICAÇÕES desta primeira saída (documentadas, como as do PRPROJ):
  - A timeline começa em 01:00:00:00 (offset fixo do writer). O `start_tc_frames`
    do projeto NÃO é honrado ainda — as posições RELATIVAS (e portanto o sync)
    ficam corretas; só o TC absoluto do início da timeline é convencional.
  - Sem transições, velocidade ou efeitos — é corte + relink + TC, o caminho mais
    validado do writer (Etapa 1 do RELINKER).
  - Clipes IGNORADOS não entram no DRT (o writer monta o pool a partir das tracks;
    "na bin, fora de sequência" exigiria estender o writer — fica para depois).
"""

from __future__ import annotations

from sync.model import Daily


def frames_to_tc(frames: int, nominal: int) -> str:
    """Frames NOMINAIS (non-drop) → 'HH:MM:SS:FF'. Inverso exato do
    `drt.writer._tc_to_frames` na mesma base `nominal`."""
    frames = max(0, int(frames))
    f = frames % nominal
    total_s = frames // nominal
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def daily_to_segments(
    daily: Daily, include_camera_audio: bool = False
) -> tuple[list[dict], list[dict]]:
    """(segments, match_results) para `drt.writer.build_drt`. Ver o cabeçalho.

    `include_camera_audio`: mesma opção do Premiere. O som ORIGINAL de cada câmera
    entra DEPOIS das tracks do som direto (A1..An = som direto; A(n+1).. = câmera),
    um bloco de tracks por câmera física — o MESMO layout do adapter do Premiere
    (`prproj/builder.py`), para os dois exports baterem. O writer do DRT já sabe
    ler áudio EMBUTIDO num arquivo de vídeo (reusa o pool clip do vídeo), então
    basta apontar o segmento de áudio para o arquivo da câmera.
    """
    nominal = max(1, round(float(daily.fps or 24.0)))
    segments: list[dict] = []
    matches: list[dict] = []

    def _add(seg: dict, path: str) -> None:
        matches.append({"segment_index": len(segments), "matched_path": path})
        segments.append(seg)

    # VÍDEO — uma track por grupo (câmera física). Um clipe de câmera é sempre
    # de um grupo, então iterar os grupos já cobre os órfãos de câmera (mesmos
    # objetos). Clipe inteiro: source_start=0, velocidade 100%.
    for gi, group in enumerate(daily.camera_groups):
        for cam in group.cameras:
            _add({
                "clip_name": cam.path.name,
                "is_audio": False,
                "timeline_tc_in": frames_to_tc(cam.timeline_start_frames, nominal),
                "duration_frames": int(cam.duration_frames),
                "source_start_frames": 0,
                "track": gi + 1,
            }, str(cam.path))

    # ── ÁUDIO ────────────────────────────────────────────────────────────────
    # No Resolve o AudioTrackVec é TOP-to-bottom: vec[0] = A1 (a track de CIMA;
    # o áudio cresce PARA BAIXO a partir do centro — ao contrário do vídeo, que
    # cresce para cima, por isso a track 1 de vídeo é a V1 de BAIXO). O usuário
    # quer o SOM DIRETO nas primeiras tracks (A1..) e o áudio da CÂMERA nas de
    # baixo — então o som direto recebe os PRIMEIROS números de track e a câmera
    # os seguintes.
    #
    #   A1..An   = som direto: uma track por canal (mono).
    #   A(n+1).. = câmera: uma track MONO por câmera física (canal 0, guia de sync).
    #              Overlap entre câmeras é resolvido por tracks diferentes.
    n_snd_tracks = max((int(s.channels or 1) for s in daily.all_sounds), default=0)

    # Som direto das tomadas E os órfãos — nas primeiras tracks (A1..An).
    for snd in daily.all_sounds:
        dur = int(round((snd.duration_ms or 0) / 1000 * nominal))
        tc = frames_to_tc(snd.timeline_start_frames, nominal)
        for ch in range(1, max(1, int(snd.channels or 1)) + 1):
            _add({
                "clip_name": snd.path.name,
                "is_audio": True,
                "timeline_tc_in": tc,
                "duration_frames": dur,
                "source_start_frames": 0,
                "track": ch,
            }, str(snd.path))

    # Áudio da câmera (opção) — nas tracks ABAIXO do som direto.
    if include_camera_audio:
        for gi, group in enumerate(daily.camera_groups):
            for cam in group.cameras:
                _add({
                    "clip_name": cam.path.name,
                    "is_audio": True,
                    "timeline_tc_in": frames_to_tc(cam.timeline_start_frames, nominal),
                    "duration_frames": int(cam.duration_frames),
                    "source_start_frames": 0,
                    "track": n_snd_tracks + gi + 1,  # uma track por câmera, canal 0
                }, str(cam.path))

    return segments, matches


def build_daily_drt(
    daily: Daily, output_path: str, include_camera_audio: bool = False
) -> dict:
    """Gera o `.drt` de UMA diária. Envolve `daily_to_segments` + `build_drt`."""
    from drt.writer import build_drt

    segments, matches = daily_to_segments(daily, include_camera_audio=include_camera_audio)
    return build_drt(
        segments, matches, output_path,
        timeline_name=daily.name,
        timeline_fps=float(daily.fps or 24.0),
    )
