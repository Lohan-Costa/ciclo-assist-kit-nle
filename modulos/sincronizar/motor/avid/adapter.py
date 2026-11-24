"""
avb/adapter.py — traduz uma DIÁRIA do Órbita para a entrada do writer de `.avb`.

A fronteira core↔adapter (ADR 0002): o motor de sync (`sync/`) não conhece o Avid.
Este módulo é o ÚNICO que sabe a forma que o writer espera.

## Por que o Avid tem um adapter próprio, e não reusa o do DRT

O layout é o MESMO dos outros dois (uma track de vídeo por câmera física, som
direto em tracks mono no topo, áudio de câmera opcional abaixo) — o que muda é a
FORMA do segmento, e ela muda em três pontos que não dá para inferir depois:

1. **A track de áudio é numerada a partir de 1000** (`1000+n` = A(n+1)). É como o
   writer separa som de vídeo: sem isso, um segmento de áudio vira uma track de
   VÍDEO.
2. **Cada segmento precisa de `mob_id`** — um segmento sem ele vira GAP em
   silêncio, e a timeline sai com buracos no lugar dos clipes.
3. **`source_slot_id` é o CANAL dentro da fonte**, e ele não é o número da track.
   O som direto e o áudio de câmera são dois blocos que começam em tracks
   diferentes, então o mesmo canal 1 cai em tracks diferentes conforme a fonte.
   Os dois têm `is_audio=True` e só quem monta sabe a diferença — por isso o
   adapter emite a forma final em vez de traduzir a saída do DRT, onde essa
   distinção já se perdeu.

## O que o Órbita NÃO usa do writer

O writer do Avid nasceu no RELINKER, que reconstrói timelines EDITADAS: transição,
velocidade, ganho, Title+, subclipe, multicam. Uma diária sincronizada não tem
nada disso — é corte seco, clipe inteiro, a 100%. Todos os campos de efeito saem
daqui desligados, de propósito e explicitamente: um `False` escrito é mais fácil
de auditar do que um campo ausente que o writer interpreta.

## ⚠️ O writer ainda é o do RELINKER

`build_avb` (`RELINKER/src-python/avb_export/translate.py`) NÃO foi portado para
cá — diferente do `drp/writer.py`, que virou `drt/writer.py`. Este adapter produz
a entrada dele. Portar (ou reduzir a um writer de cortes) é uma decisão em aberto:
o `translate.py` tem ~1500 linhas, quase todas de efeito, e o Órbita usa a fatia
mais fina delas.
"""

from __future__ import annotations

from sync.model import Daily

# A partir deste número, uma track é de SOM. `1000` = A1, `1001` = A2…
# É a convenção do writer, não uma escolha nossa.
SOUND_TRACK_BASE = 1000


def trilhas_do_som_mono(sons) -> list[int]:
    """Quantas trilhas abaixo cada som começa: os canais de um take mono (um canal cada, mesma posição e duração) vão um
    por trilha, em vez de um sobrescrever o outro. Os demais sons começam na primeira trilha, como sempre."""
    vistos: dict[tuple, int] = {}
    saida: list[int] = []
    for s in sons:
        if int(s.channels or 1) != 1:
            saida.append(0)
            continue
        chave = (s.timeline_start_frames, round(s.duration_ms or 0))
        saida.append(vistos.get(chave, 0))
        vistos[chave] = saida[-1] + 1
    return saida


def frames_to_tc(frames: int, nominal: int) -> str:
    """Frames NOMINAIS (non-drop) → 'HH:MM:SS:FF'.

    O writer posiciona cada clipe lendo `timeline_tc_in` de volta para frames, então
    esta conversão e a do writer têm de ser a MESMA na mesma base `nominal` — um
    frame de diferença aqui é um frame de dessincronia lá.
    """
    frames = max(0, int(frames))
    f = frames % nominal
    total_s = frames // nominal
    s = total_s % 60
    m = (total_s // 60) % 60
    h = total_s // 3600
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _seg(clip_name: str, start: int, dur: int, track: int, nominal: int,
         *, is_audio: bool = False, slot: int | None = None) -> dict:
    """Um segmento na forma do writer: corte seco, clipe inteiro, sem efeito.

    `mob_id` recebe o NOME do arquivo porque o writer resolve o master em duas
    tentativas — primeiro pela ponte de mob_id (que só existe quando a origem é um
    AAF), depois pelo nome. No Órbita não há AAF nenhum: a fonte é um arquivo real,
    e a resolução é sempre pelo nome. O campo precisa existir e ser não-vazio
    mesmo assim, porque o writer trata segmento sem `mob_id` como GAP.
    """
    seg = {
        "clip_name": clip_name,
        "is_audio": is_audio,
        # ⭐ A POSIÇÃO AUTORITATIVA é esta, em frames inteiros. O `timeline_tc_in`
        # ao lado é DERIVADO dela e existe só porque o writer do RELINKER lê a
        # posição em timecode — enquanto ele for a alternativa ao nosso writer,
        # vale manter os segmentos aceitos pelos dois. Um teste garante que os
        # dois campos concordam; se um dia o writer do RELINKER sair de cena, o
        # `timeline_tc_in` sai junto.
        "timeline_start_frames": max(0, int(start)),
        "timeline_tc_in": frames_to_tc(start, nominal),
        "duration_frames": int(dur),
        "source_start_frames": 0,
        "track": track,
        "mob_id": clip_name,
        # Uma diária sincronizada é corte seco. Explícito para poder ser auditado.
        "is_transition": False,
        "is_gap": False,
        "disabled": False,
        "is_effect": False,
        "has_motion_effect": False,
        "cutpoint": 0,
    }
    if is_audio:
        seg["source_slot_id"] = slot if slot is not None else 1
    return seg


def daily_to_avb_segments(
    daily: Daily, include_camera_audio: bool = False
) -> tuple[list[dict], list[dict]]:
    """(segments, match_results) para o writer de `.avb`.

    Layout (o mesmo do Premiere e do Resolve):

      VÍDEO  — uma track por CÂMERA FÍSICA (grupo). V1 = primeiro grupo. Cada clipe
               entra INTEIRO (`source_start=0`), na sua posição de timeline, a 100%.
      ÁUDIO  — o som direto multicanal vira N tracks MONO (A1..An), uma por canal.
               Com `include_camera_audio`, cada câmera física ganha abaixo dele um
               BLOCO de tracks do tamanho da sua estrutura real (2 canais = 2
               tracks, 4 = 4). Nenhum canal se perde.

    `match_results` casa cada segmento com o caminho do arquivo, no mesmo formato
    que o RELINKER produz a partir de um AAF. Para o Órbita o "match" é trivial:
    cada clipe JÁ É um arquivo real.
    """
    # ⚠️ DUAS taxas, e confundi-las custa segundos de timeline.
    #   `nominal` (24) é a base do TIMECODE — non-drop conta 24 quadros por segundo
    #   de relógio, e é assim que o Avid exibe a posição.
    #   `real` (23,976) é a taxa da TIMELINE — é ela que diz quantos quadros cabem
    #   num segundo de mídia.
    # Converter uma duração em milissegundos pela nominal estica o clipe: medido,
    # um som de 5700 s saía 137 quadros (5,7 s) mais longo do que é. O clamp do
    # writer escondia o erro enquanto o som era o clipe mais longo da timeline.
    real = float(daily.fps or 24.0)
    nominal = max(1, round(real))
    segments: list[dict] = []
    matches: list[dict] = []

    def _add(seg: dict, path: str) -> None:
        matches.append({"segment_index": len(segments), "matched_path": path})
        segments.append(seg)

    # ── VÍDEO — uma track por câmera física ──────────────────────────────────
    for gi, group in enumerate(daily.camera_groups):
        for cam in group.cameras:
            _add(
                _seg(cam.path.name, cam.timeline_start_frames,
                     cam.duration_frames, gi + 1, nominal),
                str(cam.path),
            )

    # ── ÁUDIO — som direto nas primeiras tracks, um segmento por canal ───────
    deslocamentos = trilhas_do_som_mono(daily.all_sounds)
    n_snd_tracks = max((int(s.channels or 1) + deslocamentos[i] for i, s in enumerate(daily.all_sounds)), default=0)

    for i_som, snd in enumerate(daily.all_sounds):
        dur = int(round((snd.duration_ms or 0) / 1000 * real))
        for ch in range(1, max(1, int(snd.channels or 1)) + 1):
            _add(
                _seg(snd.path.name, snd.timeline_start_frames, dur,
                     SOUND_TRACK_BASE + deslocamentos[i_som] + (ch - 1), nominal, is_audio=True, slot=ch),
                str(snd.path),
            )

    # ── ÁUDIO DA CÂMERA (opção) — TODOS os canais, um bloco por câmera ──────
    #
    # Cada câmera física ganha um BLOCO de tracks do tamanho da sua estrutura
    # real: uma câmera de 2 canais ocupa 2 tracks, uma de 4 ocupa 4. Decisão do
    # usuário (2026-08-08), contra a alternativa de trazer só o canal 1 como guia:
    # nenhum canal se perde. O custo é uma timeline mais alta, e ele é aceito.
    #
    # ⚠️ Os blocos são alocados em SEQUÊNCIA, então o tamanho de um bloco desloca
    # todos os seguintes — daí `base` acumular em vez de ser calculado por índice
    # de grupo. Com blocos de tamanhos diferentes, `base + gi` poria a segunda
    # câmera em cima da primeira.
    if include_camera_audio:
        base = SOUND_TRACK_BASE + n_snd_tracks
        for group in daily.camera_groups:
            # O bloco é do GRUPO (a câmera física), dimensionado pelo clipe mais
            # rico dele: os clipes de uma mesma câmera compartilham as tracks.
            n_ch = max((int(c.audio_channels or 0) for c in group.cameras), default=0)
            if n_ch <= 0:
                continue                      # câmera muda não ocupa track nenhuma
            for cam in group.cameras:
                # Um clipe com MENOS canais que o bloco preenche só o que tem —
                # emitir um canal que não existe na fonte criaria um segmento
                # apontando para um slot vazio.
                for ch in range(1, min(int(cam.audio_channels or 0), n_ch) + 1):
                    _add(
                        _seg(cam.path.name, cam.timeline_start_frames,
                             cam.duration_frames, base + ch - 1, nominal,
                             is_audio=True, slot=ch),
                        str(cam.path),
                    )
            base += n_ch

    return segments, matches
