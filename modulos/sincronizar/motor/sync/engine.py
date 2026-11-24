"""
Sincronizar — SyncEngine: recebe os arquivos de uma diária e devolve um `Daily`.

O material real é uma DIÁRIA: N tomadas, cada uma com o seu som direto e um ou
mais clipes de câmera. Não há um som contínuo do dia. O trabalho do engine é
descobrir QUEM VAI COM QUEM e por QUANTOS FRAMES.

Dois caminhos, e o primeiro é o diferencial do app
──────────────────────────────────────────────────

1. COM TIMECODE — alinhamento do desenho (`sync/tcmatch.py`).
   Câmera e gravador têm relógios diferentes, mas ambos correm em tempo real: a
   diferença entre eles é uma constante. Como gravaram os mesmos momentos, o
   padrão de blocos e buracos é o mesmo nos dois, e deslizar um sobre o outro
   revela essa constante — sem decodificar um frame de áudio. Daí sai, para cada
   clipe, UM candidato a som (1,1 em média no material real, contra 24 de uma
   busca cega). A waveform então só confirma e refina.

   Isso não é otimização: é o que torna o resultado CORRETO. Numa busca cega, as
   tomadas repetidas da mesma cena competem entre si e a correlação escolhe a
   errada (medido: 2 erros em 25). Com o candidato dado pelo TC, não há
   concorrente.

2. SEM TIMECODE — busca cega, como antes.
   Cada clipe é correlacionado contra todos os sons; vence o de maior pico. A
   ambiguidade acústica (tomadas repetidas) é resolvida por CRONOLOGIA: clipes e
   sons avançam na mesma ordem, então um clipe duvidoso é restringido ao intervalo
   entre os seus vizinhos confiáveis. Restrição física, não acústica — nenhuma
   métrica de áudio resolve isso sozinha.

Confiança
─────────
Nunca o valor absoluto da correlação (varia com o conteúdo da cena: fala contínua
correlaciona mais que cena esparsa, mesmo estando certa). Sempre a RAZÃO entre o
pico e o melhor concorrente — o quão inequívoco foi o match. Ver `sync/waveform.py`.

Um clipe sem som direto NÃO é um erro: a câmera roda antes do gravador, entre
tomadas, e em planos sem som (uma diária real do dataset tem 21 vídeos para 5
áudios). Ele vai para os órfãos, sinalizado, e nunca é descartado.
"""

from __future__ import annotations

import base64
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

import numpy as np

from media import peakcache
from media.inspector import probe
from media.audio import PCM_RATE, extract_pcm, extract_pcm_window, normalize
from sync import chronology
from sync.daycycle import (
    DAY_S,
    align_block_to_window,
    align_to_window,
    day_from_wall_clock,
    tc_day_seconds,
    unwrap_along_order,
)
from sync.model import (
    MAX_DAILY_SPAN_TC_HOURS,
    CameraAngle,
    CameraGroup,
    Daily,
    SoundClip,
    Take,
)
from sync.tcmatch import (
    Interval,
    candidate_sounds,
    clock_offsets,
    nominal_fps,
    predicted_offset_seconds,
    tc_to_real_seconds,
)
from sync.waveform import PEAK_RATE, confirm_offset, peaks_u8, sync_camera_to_wav

#: `(mensagem, atual, total)` — o que as fases internas emitem. O `progress` que
#: `run()` recebe leva um 4º argumento a mais (a fração GERAL, ver `_PHASE_BANDS`).
ProgressCallback = Callable[[str, int, int], None]

#: A barra de progresso é UMA só, e atravessa o sync inteiro de 0 a 1 — cada fase
#: ocupa uma FAIXA fixa dela, e o `atual/total` da fase é mapeado dentro da sua
#: faixa. Antes cada fase mandava o seu próprio 0-100% e a barra voltava a zero
#: três vezes num sync; o usuário lê isso como "travou e recomeçou".
#:
#: Os tamanhos vêm de medição, não de chute (77 proxies RED + 7 WAVs, 18,5 GB,
#: caches quentes): pareamento 67 s, corroboração 28 s, o resto abaixo de 1 s. O
#: probe leva uma faixa maior do que o seu tempo QUENTE porque a frio — pasta
#: nova, que é justamente quando o usuário está olhando — ele é o passo longo.
_PHASE_BANDS = {
    "probe":  (0.00, 0.10),   # ler metadados de cada arquivo
    "pair":   (0.10, 0.72),   # parear e medir cada clipe contra o som
    "verify": (0.72, 0.98),   # corroborar pelo regime de relógio
    "final":  (0.98, 1.00),   # posicionar na timeline e materializar
}

TICKS_PER_SEC = 254_016_000_000

# Razão pico/melhor-concorrente a partir da qual um match é inequívoco. Calibrado
# em 2026-07-11 contra o dataset real: matches corretos ficaram entre 1,86 e 4,86;
# os ambíguos (tomadas repetidas), em ~1,06. Ver o registro interno de decisões.
TRUST_RATIO = 1.5

# Abaixo disto, mesmo após a desambiguação, o resultado é sinalizado em vez de
# aceito em silêncio.
FLAG_RATIO = 1.15

# Clipes curtos demais não têm sinal de sync — e quebram a normalização do ZNCC
# (um clipe de 0,4 s devolveu pico 3,79, impossível: o ZNCC não passa de 1).
# Entram no projeto, mas sinalizados, sem passar pela correlação.
MIN_SYNC_DURATION_S = 5.0

# Quando o offset da waveform bate com o que o relógio do REGIME prevê dentro
# desta margem, o match está CORROBORADO — duas medições independentes, uma do
# relógio e outra do som, chegando ao mesmo lugar.
#
# É apertado de propósito: dentro de um regime o Δ é constante a ~0,1 s (medido
# em 24 tomadas seguidas). Uma folga grande aqui aceitaria como "corroborado" um
# offset dezenas de segundos errado.
TC_AGREEMENT_S = 5.0

# ── A JANELA: o que o timecode já sabe, não se paga para descobrir ───────────
#
# O áudio de uma câmera vive INTERLEAVADO com o vídeo: para ler 20 s de som de um
# MXF ProRes, o ffmpeg atravessa 20 s de imagem junto. Ler o arquivo INTEIRO de
# cada clipe custava 18 MINUTOS numa diária de Alexa (42 clipes, 202 GB) — e era
# desperdício, porque o timecode JÁ DIZ onde o clipe cai. Basta olhar ali.
#
# WAVEFORM_WINDOW_S — quanto do clipe se lê. MEDIDO contra a correlação do arquivo
# inteiro, na diária real: 10 s erra até 5,4 frames (pouco sinal: o mic da câmera
# correlaciona a só 0,02–0,09 com o boom); 20 s erra no máximo 1 frame; 30 s não
# melhora nada e custa 30% a mais. 20 s é o ponto onde a curva vira.
WAVEFORM_WINDOW_S = 20.0

# Onde a janela começa DENTRO do clipe. Os primeiros instantes costumam ser
# ajuste/silêncio (a câmera parte antes da ação), e silêncio não correlaciona.
WAVEFORM_WINDOW_LEAD_S = 2.0

# A JANELA SÓ ENTRA ONDE HÁ O QUE ECONOMIZAR.
#
# Ela troca sinal por tempo: com 20 s em vez do clipe inteiro, a estimativa fica
# ~0,5 frame mais ruidosa. Isso se paga quando o arquivo é caro — e só então.
# Medido nos três datasets reais:
#
#   MIDIA MULTCAM  .mov   464 MB   4,7 MB/s de mídia   ler inteiro: 1,5 s
#   PROJETO X      .mp4   509 MB   1,4 MB/s            ler inteiro: 1,7 s
#   PROJETO Y      .mxf  2991 MB  56,6 MB/s            ler inteiro:  10 s   ← Alexa 35
#
# Nos dois primeiros a janela economizaria segundos e custaria 1 frame em alguns
# clipes (medido: 2 de 26 na D02, que o usuário já validou no Premiere). Não vale.
# No terceiro ela economiza 15 MINUTOS numa diária. Vale muito.
#
# Num disco lento (um NAS) o ponto de virada desce; se isso aparecer, medir e
# baixar o teto — não chutar.
WHOLE_FILE_BUDGET_BYTES = 1_000_000_000

# Meia-largura da janela em que a correlação é refeita ao redor do offset previsto
# pelo regime. Generosa, porque o palpite inicial da correlação pode estar longe —
# mas estreita o bastante para que a tomada vizinha (que competia e vencia) fique
# de fora do páreo.
TC_SEARCH_WINDOW_S = 30.0

# A confiança de um clipe FIXADO (`pinned`) — o RE-SYNC PARCIAL (Etapa D). Sempre
# acima de TRUST_RATIO, para que ele conte como âncora nas duas desambiguações
# (`_corroborate_by_delta` e a passada 2 de `_pair_by_waveform`) exatamente como um
# clipe medido com alta confiança contaria. O valor em si não é lido em nenhuma
# outra conta — só comparado contra TRUST_RATIO.
PINNED_CONFIDENCE = 999.0


def _natural_sort_key(path: Path):
    """Ordena nomes tratando runs de dígitos numericamente ('PANA2' < 'PANA10')."""
    parts = re.split(r"(\d+)", path.name)
    return [int(p) if p.isdigit() else p for p in parts]


def _tc_usable(clips: list["_Clip"]) -> bool:
    """O timecode desta câmera serve como relógio do dia? Ver `chronology.tc_usable`."""
    return chronology.tc_usable([c.tc_sec for c in clips], [c.tc_frames for c in clips])


def _peaks_b64(pcm, path=None) -> str:
    """Peaks prontos para o IPC: uint8 → base64 (JSON com floats seria 4x maior).

    Com `path`, também vão para o cache em disco — o PCM inteiro acabou de ser
    pago; guardar a onda é de graça e poupa o `compute_peaks` de reler o arquivo."""
    pk = peaks_u8(pcm)
    if path is not None:
        peakcache.store(path, pk)
    return base64.b64encode(pk.tobytes()).decode("ascii")


def _com_audio_de(meta_video: dict, meta_audio: dict, canais: int | None = None) -> dict:
    """Metadados de um clipe cujo ÁUDIO mora noutro arquivo.

    O caso é a mídia gerenciada do Avid (MXF OP-Atom): o arquivo de vídeo carrega
    fps, timecode e duração, e **não tem uma amostra de som**; o áudio vive em
    arquivos irmãos, um por canal.

    Sem isto, `has_audio` viria `False` e o clipe seria recusado como
    não-sincronizável (`_Clip.syncable`) — em silêncio, porque não é erro: é um
    vídeo mudo, o que é uma coisa perfeitamente possível.

    Fica de FORA de propósito tudo que descreve o VÍDEO. Em especial `fps` e
    `tc_start`: um OP-Atom de áudio traz timecode próprio, e deixá-lo sobrescrever
    o do vídeo trocaria o relógio do clipe por outro — a classe de erro mais cara
    deste projeto.

    `canais` sobrepõe o total quando quem chamou sabe quantos arquivos formam o
    clipe (o probe do arquivo de áudio só enxerga o canal DELE).
    """
    fundido = dict(meta_video)
    for campo in ("has_audio", "sample_rate", "sample_depth", "channels",
                  "total_audio_channels"):
        if campo in meta_audio:
            fundido[campo] = meta_audio[campo]
    if canais:
        fundido["channels"] = int(canais)
        fundido["total_audio_channels"] = int(canais)
    return fundido


# A duração de câmera mora em `sync.model` — leve, sem scipy — porque a escrita
# de merged do Premiere também a usa (ver `premiere/escrita.py`).
from sync.model import duration_frames as _duration_frames  # noqa: E402


def _ticks_per_frame(fps: float) -> int:
    return round(TICKS_PER_SEC / fps)


# Duas câmeras a 23,976 podem reportar 23.976 e 23.98 — é o mesmo fps, e
# tratá-las como divergentes encheria a tela de avisos falsos.
_FPS_EPSILON = 0.01


def _wall_clock_abs(meta: dict) -> float | None:
    """O instante real de gravação. Ver `chronology.wall_clock_abs`."""
    return chronology.wall_clock_abs(meta)


def _base_da_fonte(
    gid: str,
    clips: list["_Clip"],
    declaradas: dict[str, str],
    nomes: dict[str, str],
    emit: ProgressCallback,
    total: int,
) -> str:
    """
    Em que ordem confiar NESTA câmera: o que o usuário declarou, ou o que o
    diagnóstico propõe.

    **Ausente = automático**, e automático chama a MESMA função que a interface usa
    para propor (`chronology.propose`). É isso que impede a tela de recomendar uma
    base e o motor fazer outra — o pior tipo de divergência, porque é invisível.

    Uma base que o material não sustenta não é obedecida em silêncio: o motor avisa
    e cai na que serve. Prometer uma ordem que os arquivos não têm seria pior que
    ignorar a escolha.
    """
    arquivos = [{"nome": c.path.name, "tc_sec": c.tc_sec,
                 "tc_frames": c.tc_frames, "meta": c.meta} for c in clips]
    proposta = chronology.propose("camera", arquivos)
    escolhida = declaradas.get(gid)
    if not escolhida or escolhida == "auto":
        return proposta

    if escolhida == "timecode" and not _tc_usable(clips):
        emit(f"{nomes.get(gid) or gid}: o timecode desta câmera não serve como "
             f"relógio — usando a ordem dos nomes.", 0, total)
        return "name"
    return escolhida


def _ordenar_sons(sounds: list["_Sound"]) -> None:
    """
    Põe a lista de sons em ordem CRONOLÓGICA, no lugar.

    ⚠️ POR QUE ISTO PRECISOU EXISTIR: a passada 2 do pareamento
    (`_pair_by_waveform`) trata esta lista como se ela já fosse cronológica — ela
    monta a janela de desambiguação com `sounds[lo:hi+1]`, entre o som do vizinho
    anterior e o do próximo. Só que a lista chegava na ordem do PAYLOAD, que é a
    ordem do NOME. E o nome de um arquivo de gravador segue a cena e a tomada, não
    o relógio: no material real, `LOCAL-2-005` foi gravado 20 h depois do `-004`.
    Com a ordem errada, a janela pode ser o intervalo errado — ou ficar vazia, e aí
    um clipe perfeitamente sincronizável vira `ambiguous` por engano.

    A autoridade, em ordem:
      1. **timecode** (já desdobrado em dias por `_unwrap_sounds`);
      2. **relógio de parede** do BWF ou do caminho — é o que salva o material em
         que o gravador não escreve TC nenhum (visto: 21 WAVs, todos sem TC, mas
         com `hl-AAAA-MM-DD/HH-MM-SS.wav`);
      3. a ordem de entrada, preservada — sem autoridade, mexer seria pior.
    """
    entrada = {id(s): i for i, s in enumerate(sounds)}

    def chave(s: "_Sound") -> tuple:
        tc = s.tc_abs_sec
        if tc is not None:
            return (0, tc, entrada[id(s)])
        parede = chronology.wall_clock_abs(s.meta)
        if parede is not None:
            return (1, parede, entrada[id(s)])
        return (2, 0.0, entrada[id(s)])

    sounds.sort(key=chave)


def _unwrap_sounds(
    sounds: list["_Sound"],
    groups: dict[str, list["_Clip"]],
    order: list[str],
) -> None:
    """Em que DIA cada som direto cai.

    O som não tem ordem própria confiável — o nome de um arquivo de gravador segue
    a cena e a tomada, não o relógio (no material real, `LOCAL-2-005` é o quinto e
    foi gravado 20 h depois do quarto). Duas autoridades, nesta ordem:

    1. **O RELÓGIO DE PAREDE do próprio arquivo** (BWF), que dá os dias RELATIVOS
       entre os sons com precisão — e é o único jeito de saber que um som está 20 h
       depois do anterior, coisa que nenhuma janela adivinha. Aplicado ao CONJUNTO:
       os dias relativos vêm do BWF, e um único deslocamento inteiro encaixa o
       conjunto na janela das câmeras.
    2. **A janela das câmeras**, para quem não tem data. Entre os deslocamentos
       possíveis — que são só múltiplos de 24 h — vence o que aproxima.

    ⚠️ Isto NÃO é sincronizar. O Δ livre entre o relógio do gravador e o da câmera é
    problema do `tcmatch`, e ele continua livre; aqui a única pergunta é de que DIA
    é este arquivo, e a resposta é um número inteiro de voltas de 24 h.

    Sem câmera com relógio utilizável não há janela, e todo som fica no dia 0 — que
    é exatamente o comportamento de antes deste módulo existir.
    """
    lo = hi = None
    for gid in order:
        clips = groups[gid]
        if not _tc_usable(clips):
            continue
        for c in clips:
            t = c.tc_abs_sec
            if t is None:
                continue
            lo = t if lo is None else min(lo, t)
            hi = t + c.duration_s if hi is None else max(hi, t + c.duration_s)

    if lo is None or hi is None:
        return

    com_tc = [s for s in sounds if s.tc_sec is not None]

    # 1. Dias relativos pelo relógio de parede, para quem o tem.
    datados: list[tuple[_Sound, int]] = []
    for s in com_tc:
        wall = _wall_clock_abs(s.meta)
        if wall is None:
            continue
        k = day_from_wall_clock(s.tc_sec, wall)
        if k is not None:
            datados.append((s, k))

    if datados:
        base = min(k for _, k in datados)
        for s, k in datados:
            s.day_index = k - base
        # Um deslocamento ÚNICO para o conjunto inteiro: os dias relativos entre os
        # sons vêm do BWF e não se mexem — o que a janela decide é só onde o BLOCO
        # começa. Ancora pelo som mais cedo, que é quem define a origem do bloco.
        primeiro = min(datados, key=lambda sk: sk[0].tc_sec + sk[1] - base)[0]
        desloca = align_to_window(primeiro.tc_abs_sec, lo, hi)
        if desloca:
            for s, _ in datados:
                s.day_index += desloca

    # 2. Quem não tem data cai na janela — EM BLOCO, por gravador.
    #
    # ⚠️ Um a um era um bug, e dos caros: `align_to_window` desempata por distância,
    # e quando o relógio do gravador está longe do da câmera (o Δ entre os dois é
    # LIVRE) essa distância fica quase igual para "ficar" e para "voltar um dia".
    # O fio de navalha passava NO MEIO do gravador, partindo os arquivos dele em
    # dois blocos a 24 h de distância — e destruindo a única coisa que o material
    # afirmava com certeza, que é a distância entre os arquivos do MESMO gravador.
    #
    # Por GRAVADOR (`group_id`) porque dois podem rodar com relógios diferentes: o
    # bloco é o conjunto que compartilha um relógio, não "todos os sons".
    #
    # A volta escolhida aqui pode até estar errada — o Δ livre do `tcmatch` a
    # absorve. Partir o bloco, não.
    datados_ids = {id(s) for s, _ in datados}
    sem_data: dict[str | None, list[_Sound]] = {}
    for s in com_tc:
        if id(s) not in datados_ids:
            sem_data.setdefault(s.group_id, []).append(s)

    for bloco in sem_data.values():
        desloca = align_block_to_window([s.tc_sec for s in bloco], lo, hi)
        for s in bloco:
            s.day_index = desloca


def _detect_project_fps(cam_fps: list[float]) -> float:
    """fps do projeto = o mais comum entre as câmeras (não o da primeira: com uma
    câmera fora do padrão no topo da lista, o projeto herdaria o fps errado em
    silêncio)."""
    counts: dict[float, int] = {}
    for f in cam_fps:
        key = next((k for k in counts if abs(k - f) < _FPS_EPSILON), f)
        counts[key] = counts.get(key, 0) + 1
    # Empate resolve pelo maior fps: entre dois igualmente comuns, o mais alto
    # preserva mais frames.
    return max(counts.items(), key=lambda kv: (kv[1], kv[0]))[0]


# ── Estrutura interna do trabalho ────────────────────────────────────────────


class _Clip:
    """Um clipe de câmera durante o processamento (vira um CameraAngle no fim)."""

    def __init__(self, path: Path, meta: dict, group_id: str,
                 group_order: int | None, fps: float, audio_path: Path | None = None):
        self.path = path
        # ⭐ ONDE MORA O ÁUDIO DESTE CLIPE — quase sempre dentro do próprio arquivo,
        # mas nem sempre. Na mídia gerenciada do Avid (MXF OP-Atom) cada track é um
        # arquivo separado: o vídeo num, e o áudio-guia noutro, IRMÃO. O motor
        # correlaciona forma de onda, então precisa saber de onde LER o som sem
        # deixar de tratar o clipe como o arquivo de vídeo (que é o que carrega
        # fps, timecode e duração, e é o que o NLE vai referenciar).
        self.audio_path = audio_path or path
        self.meta = meta
        self.group_id = group_id
        self.group_order = group_order
        self.group_name = ""
        self.duration_s = (meta.get("duration_ms") or 0.0) / 1000
        self.duration_frames = _duration_frames(meta.get("duration_ms") or 0, fps,
                                                meta.get("frame_count"), meta.get("fps"))
        self.has_audio = bool(meta.get("has_audio"))
        self.size_bytes = int(meta.get("size_bytes") or 0)

        self.tc_sec = tc_to_real_seconds(
            meta.get("tc_start") or "", meta.get("fps") or fps,
            bool(meta.get("tc_drop_frame")),
        )
        self.tc_frames: int | None = (
            None if self.tc_sec is None else round(self.tc_sec * fps)
        )
        # Em que DIA da captação este clipe está. 0 até alguém desdobrar — quem
        # preenche é `daycycle.unwrap_along_order`, depois da ordenação provisória
        # do grupo. Ver `sync/daycycle.py`: o TC é um círculo de 24 h, e este é o
        # contador de voltas.
        self.day_index = 0
        self._fps = fps
        # O fps do PRÓPRIO ARQUIVO — o mesmo com que `tc_sec` foi calculado. Uma
        # volta de timecode dura `nominal·86400/fps` segundos reais, e usar o fps do
        # projeto aqui erraria numa diária com câmeras de fps diferentes.
        self._tc_fps = float(meta.get("fps") or fps)

        self.sound: _Sound | None = None
        self.offset_frames = 0
        self.confidence = 0.0
        self.flagged = False
        self.flag_reason: str | None = None
        self.sync_source: str | None = None   # "waveform" | "timecode" (ver model.py)
        self.pcm: np.ndarray | None = None
        self.peaks: str | None = None
        self.timeline_start = 0
        # Este clipe foi posicionado SEM relógio nenhum (nem som, nem tradução do
        # TC da câmera)? Então a posição dele é uma emenda, e quem decide onde ela
        # cai é `_encostar_sem_relogio`. Ver `tests/test_orfaos_em_ordem.py`.
        self.sem_relogio = False
        self.implied_delta: float | None = None
        # ⚠️ FIXADO PELO USUÁRIO — e isto NÃO é o mesmo que `confidence == 999`.
        # Os dois casos escrevem `PINNED_CONFIDENCE`, e têm regras OPOSTAS:
        #   • fixado no re-sync parcial → verdade confirmada por uma pessoa; nunca
        #     se move e nunca é re-medido;
        #   • posicionado por TC puro (`_pair_by_tc_only`) → confiança de teto para
        #     servir de âncora, mas o áudio nunca foi conferido; pode ser
        #     reposicionado se colidir com outro clipe da mesma câmera.
        # Sem este campo, `_resolve_source_overlaps` não distingue os dois.
        self.pinned = False
        # Em que ordem confiar nesta fonte ("name" | "timecode" | "free").
        # Preenchido no agrupamento; ver `_base_da_fonte`.
        self.basis: str = "name"
        # ⚠️ O timecode DESTA FONTE é rec-run — só anda enquanto a câmera grava?
        #
        # Se for, ele ORDENA os clipes (é monotônico) mas NÃO mede a distância
        # entre eles: cada clipe começa onde o anterior terminou, e a pausa do
        # operador não fica registrada em lugar nenhum. Quem precisa de ESPAÇO —
        # hoje só `_travar_cronologia` — tem de olhar para cá antes de usar o TC.
        # Preenchido no agrupamento, sobre a fonte INTEIRA e em ordem de TC (uma
        # ilha vê só um recorte dela, e o recorte não responde a pergunta).
        self.tc_rec_run: bool = False

    # ⚠️ `tc_sec`/`tc_frames` são a LEITURA CRUA (0…24 h) e não mudam nunca — é o
    # que o NLE exibe como TC de origem do arquivo (`alternate_start_ticks`).
    # `tc_abs_*` é o eixo do DIA, e é ele que ordena, pareia e posiciona.
    # Propriedades derivadas de propósito: um `tc_abs` guardado e um `day_index`
    # mudado depois divergiriam em silêncio. Ver `sync/daycycle.py`.
    @property
    def tc_abs_sec(self) -> float | None:
        if self.tc_sec is None:
            return None
        # `tc_day_seconds`, e NÃO 86400: a volta é do TIMECODE, que a 23,976 fps
        # dura 86 486 s reais. Ver o aviso em `daycycle.tc_day_seconds`.
        return self.tc_sec + self.day_index * tc_day_seconds(self._tc_fps)

    @property
    def tc_abs_frames(self) -> int | None:
        if self.tc_abs_sec is None:
            return None
        return round(self.tc_abs_sec * self._fps)

    @property
    def syncable(self) -> tuple[bool, str | None]:
        """Este clipe tem como ser sincronizado? Se não, por quê."""
        if not self.has_audio:
            # Uma câmera sem faixa de áudio (um drone, no material real) não tem
            # com o que correlacionar. Não é erro — é uma limitação física.
            return False, "no_audio"
        if self.duration_s < MIN_SYNC_DURATION_S:
            # Curto demais para ter sinal — e quebra a normalização do ZNCC (um
            # clipe de 0,4 s devolveu pico 3,79, impossível: ZNCC não passa de 1).
            return False, "too_short"
        return True, None


class _Sound:
    """Um som direto durante o processamento (vira um SoundClip no fim)."""

    def __init__(self, path: Path, meta: dict, audio_path: Path | None = None):
        self.path = path
        # Ver `_Clip.audio_path`: um gravador importado no Avid vira N arquivos
        # OP-Atom mono, e o guia de sync é o primeiro deles.
        self.audio_path = audio_path or path
        self.meta = meta
        self.duration_s = (meta.get("duration_ms") or 0.0) / 1000
        self.tc_sec: float | None = meta.get("tc_start_sec")
        # A taxa em que `tc_sec` conta, quando ele veio de um TIMECODE em vez de um
        # contador de amostras. `None` para BWF. Ver `tc_abs_sec`.
        self.tc_sec_fps: float | None = meta.get("tc_sec_fps")
        # Idem `_Clip.day_index` — mas o som não tem ordem própria confiável (no
        # material real, `LOCAL-2-005` é o quinto e está 20 h depois do quarto), então
        # quem o preenche é `_unwrap_sounds`, pela data do BWF ou pela janela das
        # câmeras. Ver `sync/daycycle.py`.
        self.day_index = 0
        self.pcm: np.ndarray | None = None
        self.peaks: str | None = None
        self.clips: list[_Clip] = []
        self.timeline_start = 0
        self.implied_delta: float | None = None
        # De QUAL gravador este som veio. Dois gravadores PODEM rodar ao mesmo
        # tempo, então a track do som não é uma só — ver `_SOUND_TRACK`.
        self.group_id: str | None = None
        self.placed = False

    @property
    def tc_abs_sec(self) -> float | None:
        """O TC do som no eixo do DIA.

        ⚠️ A volta PADRÃO é `DAY_S` (86400 s exatos), e NÃO a do timecode como no
        `_Clip`: o `tc_start_sec` de um BWF vem de `TimeReference / sample_rate` —
        amostras desde a meia-noite REAL. Amostras não contam em frames, então não
        herdam o 0,1 % do timecode NTSC.

        ⚠️ MAS nem todo som traz um contador de amostras. A track de áudio de um
        MXF OP-Atom não é BWF: o relógio dela é um TIMECODE, e para ela vale a
        volta do timecode, a mesma do `_Clip`. Quem separa os dois casos é
        `tc_sec_fps` — a taxa em que o valor conta, que o `media/inspector.py` só
        preenche quando o valor veio de um TC. A 24 fps cravado as duas voltas
        coincidem; a 23,976 divergem 86 s por dia, o bastante para descolar o som
        da câmera numa captação que atravessa a meia-noite.
        """
        if self.tc_sec is None:
            return None
        # `getattr` com padrão porque há teste que instancia `_Sound` por `__new__`
        # e preenche só o que vai exercitar — sem `__init__`, o atributo não existe.
        tc_fps = getattr(self, "tc_sec_fps", None)
        volta = tc_day_seconds(float(tc_fps)) if tc_fps else DAY_S
        return self.tc_sec + self.day_index * volta

    def load_pcm(self) -> np.ndarray:
        """PCM do som, extraindo se preciso. Os peaks (que a timeline usa) são
        calculados na primeira extração e SOBREVIVEM ao `release` — assim liberar
        a memória não obriga a reler o arquivo do disco depois. Eles também vão
        para o CACHE EM DISCO (o mesmo dos `.pek`): é o que deixa o PRÓXIMO sync
        desta diária — e o `compute_peaks` de segundo plano — sem ter de reler o
        arquivo só para desenhar a onda."""
        if self.pcm is None:
            self.pcm = normalize(extract_pcm(str(self.audio_path)))
            self.peaks = _peaks_b64(self.pcm, self.audio_path)
        return self.pcm

    def release(self) -> None:
        """Devolve o PCM à memória. Uma diária tem dezenas de sons de ~9 min:
        segurar todos custaria centenas de MB, e no caminho do timecode cada som
        é usado por ~1 clipe — cachear não compraria nada."""
        self.pcm = None


# ── O engine ─────────────────────────────────────────────────────────────────


def run(
    file_entries: list[str | dict],
    progress: ProgressCallback | None = None,
    project_name: str = "DIARIA",
    on_sound: Callable[[dict], None] | None = None,
    on_clip: Callable[[dict], None] | None = None,
    fps: float | None = None,
    start_tc_frames: int = 0,
    pinned: dict[str, tuple[int, str]] | None = None,
    selected: set[str] | None = None,
    sync_method: str = "hybrid",
) -> Daily:
    """
    Recebe os arquivos de uma diária e devolve um `Daily` sincronizado.

    Cada item de `file_entries` é `{"path", "group_id", "group_order"}` (o grupo é
    a câmera física — uma pasta arrastada) ou uma string solta.

    `fps` — framerate do PROJETO. Se None, detecta (o mais comum entre as câmeras).
    Todos os offsets e durações são medidos nessa grade.

    `on_sound` / `on_clip` — alimentam a timeline ao vivo, com os peaks de
    waveform. Carregam dados de EXIBIÇÃO; o modelo de domínio continua puro.

    `sync_method` — como parear e posicionar:
      - "timecode": SÓ o timecode. Cada clipe vai para o seu TC de entrada e o
        offset é a diferença de TC contra o som (cam_TC − snd_TC), que é o sync
        EXATO quando os aparelhos compartilham o relógio (jam sync). Não lê um
        frame de áudio para sincronizar — é a opção para quando o TC está certo, e
        a waveform vira o conserto pontual pela seleção. Ver `_pair_by_tc_only`.
      - "waveform": SÓ a forma de onda, ignorando o TC no pareamento (`_pair_by_waveform`).
      - "hybrid" (padrão): o TC propõe o par e a waveform confirma/refina quando o
        relógio serve; senão, busca cega. É o comportamento histórico.

    RE-SYNC PARCIAL (Etapa D) — `pinned` e `selected` andam juntos e são `None` os
    dois no caminho normal (sync cheio), que fica bit a bit como sempre foi.

    `pinned` — `{path: (offset_frames, sound_path)}` para os clipes que o usuário
    NÃO selecionou. Eles não são medidos de novo: entram já resolvidos, com
    confiança `PINNED_CONFIDENCE` — e é exatamente isso que os torna ÂNCORA
    confiável para a desambiguação por cronologia (`_pair_by_waveform`) e para a
    corroboração por regime de relógio (`_corroborate_by_delta`) dos clipes que
    FORAM selecionados. Sem ler o arquivo deles de novo: é o que faz um re-sync de
    1 clipe custar 1 clipe, não a diária inteira.

    `selected` — os paths que de fato passam pela correlação. `None` (o padrão)
    processa todo mundo, igual a antes; um conjunto processa só ele, e trata quem
    ficou de fora como já resolvido (por `pinned`, ou por já não ter sido tocado).
    """
    entries = [
        {"path": e, "group_id": e, "group_order": None} if isinstance(e, str) else e
        for e in file_entries
    ]


    def emit(msg: str, cur: int, tot: int, phase: str = "pair",
             frac: float | None = None) -> None:
        """Um evento de progresso.

        `cur`/`tot` são da FASE (é o contador "12/77" que a tela mostra); o 4º
        argumento que sai daqui é a fração GERAL, já mapeada na faixa da fase —
        é ela que move a barra, e é por isso que a barra nunca anda para trás.

        `frac` sobrepõe a fração dentro da fase, para os passos que não têm o que
        contar (posicionar a timeline é um passo só, e "0 de 1" na tela é pior que
        contador nenhum — daí `tot=0`, que apaga o contador, com `frac` explícita).
        """
        if progress:
            lo, hi = _PHASE_BANDS[phase]
            done = frac if frac is not None else ((cur / tot) if tot else 0.0)
            progress(msg, cur, tot, lo + min(1.0, max(0.0, done)) * (hi - lo))

    # ⭐ MÍDIA GERENCIADA DO AVID: N arquivos viram 1 clipe, antes de qualquer
    # outra coisa. Um clipe OP-Atom é o vídeo mais um arquivo por canal de áudio,
    # e sem reuni-los aqui cada canal de cada câmera entraria como um gravador de
    # som direto — sem erro nenhum, só com a diária errada. Só custa alguma coisa
    # quando há `.mxf` na lista; qualquer outra mídia passa intacta.
    if any(str(e.get("path", "")).lower().endswith(".mxf") for e in entries):
        from media.opatom import colapsar_entradas

        antes = len(entries)
        entries = colapsar_entradas(entries)
        if len(entries) != antes:
            emit(f"Mídia do Avid: {antes} arquivos em {len(entries)} clipes.",
                 0, len(entries), "probe")

    # ── 1. Probe ─────────────────────────────────────────────────────────────
    total = len(entries)
    emit("Lendo metadados...", 0, total, "probe")

    probed = []
    for i, e in enumerate(entries):
        meta = probe(e["path"])
        # ⭐ CLIPE DE VÁRIOS ARQUIVOS. Um clipe sempre foi UM arquivo aqui; na mídia
        # gerenciada do Avid (MXF OP-Atom) o vídeo e cada canal de áudio são
        # arquivos SEPARADOS. Quando a entrada declara `audio_path`, o probe do
        # arquivo de vídeo não sabe nada de som — e a diferença é grave, porque
        # `has_audio=False` faria o clipe ser recusado como não-sincronizável
        # (`_Clip.syncable`). Os fatos de ÁUDIO vêm do arquivo de áudio; os de
        # VÍDEO (fps, timecode, duração) continuam vindo do de vídeo.
        audio_path = e.get("audio_path")
        if audio_path:
            meta = _com_audio_de(meta, probe(audio_path), e.get("audio_channels"))
        probed.append(
            (Path(e["path"]), meta, e.get("group_id"), e.get("group_order"), e.get("kind"),
             Path(audio_path) if audio_path else None)
        )
        emit(f"Metadados: {Path(e['path']).name}", i + 1, total, "probe")

    # ── 2. Separar câmeras de sons ───────────────────────────────────────────
    #
    # A regra continua a mesma — TEM FPS → CÂMERA — e ela nunca errou no material
    # real. O que mudou é que agora ela é VISÍVEL na tela: a fonte mostra como foi
    # classificada, e o usuário pode discordar. Quando ele discorda, `kind` chega
    # aqui e MANDA.
    #
    # Um arquivo sem fps não pode ser câmera por decreto (não há vídeo nele para
    # pôr numa track), então essa direção é ignorada — e a UI nem oferece o botão.
    def _is_camera(meta: dict, kind: str | None) -> bool:
        if not meta.get("fps"):
            return False                      # sem vídeo, não há câmera possível
        return kind != "sound"                # o usuário pode rebaixar uma câmera a som

    cam_entries = [(p, m, gid, gord, ap) for p, m, gid, gord, k, ap in probed
                   if _is_camera(m, k)]
    # O `gid` do som É guardado: dois gravadores podem rodar ao mesmo tempo, e
    # sem saber de qual fonte cada som veio não há como dar uma track a cada um.
    snd_entries = [(p, m, gid, ap) for p, m, gid, _, k, ap in probed
                   if not _is_camera(m, k) and m.get("has_audio")]

    if not cam_entries:
        raise ValueError("Nenhum clipe de câmera encontrado.")

    # ── Arquivos de som VAZIOS ───────────────────────────────────────────────
    #
    # ⚠️ O CASO REAL: um gravador de campo que começa e para a gravação no mesmo
    # instante deixa um WAV de 44 bytes — só o cabeçalho, com o chunk `data` de
    # tamanho zero. O arquivo é válido: o probe lê sample rate e canais, `has_audio`
    # dá True, e ele passava por todos os filtros acima. Só que a extração devolve
    # ZERO amostras, e o sync inteiro morria com a mensagem do numpy
    # ("zero-size array to reduction operation maximum...") — verdadeira e inútil
    # para quem está olhando a tela. Numa pasta com dezenas de arquivos, não havia
    # como o editor saber qual era o culpado.
    #
    # Agora eles são separados AQUI, com nome e sobrenome, antes de qualquer
    # processamento. Um som vazio não é erro do usuário nem do app: é material que
    # não existe. O que não podia continuar é ele derrubar tudo em silêncio.
    vazios = [p for p, m, _, _ in snd_entries if not m.get("duration_ms")]
    if vazios:
        snd_entries = [(p, m, g, a) for p, m, g, a in snd_entries if m.get("duration_ms")]
        nomes = ", ".join(p.name for p in vazios[:4])
        resto = f" (e mais {len(vazios) - 4})" if len(vazios) > 4 else ""
        emit(
            f"Ignorando {len(vazios)} arquivo(s) de som sem áudio gravado: {nomes}{resto}",
            0, total,
        )
        # Se TODOS os sons eram vazios, seguir calado seria pior: o editor mandou
        # som, o app entregaria uma diária muda, e ninguém saberia por quê.
        if not snd_entries:
            raise ValueError(
                f"Os {len(vazios)} arquivo(s) de som enviados não têm áudio gravado "
                f"(duração zero): {nomes}{resto}. "
                "O gravador criou o arquivo e parou antes de gravar. "
                "Confira a pasta do som direto e sincronize de novo."
            )

    # O NOME da fonte vem do frontend (é o que o usuário vê e pode renomear). Antes
    # ele era derivado do `group_id`, que era o caminho da pasta — e agora é um uuid,
    # do qual não se deriva nome nenhum.
    source_names: dict[str, str] = {
        str(e["group_id"]): e["source_name"]
        for e in entries
        if e.get("group_id") and e.get("source_name")
    }

    # Em que ordem confiar em cada fonte. Campo OPCIONAL: sem ele, o motor
    # diagnostica e propõe sozinho (`_base_da_fonte`), que é o comportamento de
    # sempre. Um cliente antigo — ou o painel de NLE, que pode não mandar o campo —
    # continua funcionando exatamente como antes.
    source_chronology: dict[str, str] = {
        str(e["group_id"]): str(e["chronology"])
        for e in entries
        if e.get("group_id") and e.get("chronology")
    }

    # UM GRUPO SEM SOM DIRETO É LEGÍTIMO — não é erro.
    #
    # É o dia de B-roll, o plano MOS, a câmera que rodou sozinha. Antes isto
    # levantava `ValueError` e derrubava a diária inteira. Todo o caminho para
    # tratá-lo JÁ EXISTIA e estava inalcançável: `_place_on_timeline` sabe lidar com
    # `c.sound is None` (ancora o clipe pelo próprio TC, ou o emenda no cursor) e
    # `_build_daily` já os recolhe em `orphan_cameras`. Os clipes saem sinalizados
    # como `no_sound`, que é a resposta honesta.
    has_sound = bool(snd_entries)

    project_fps = float(fps) if fps else _detect_project_fps(
        [m["fps"] for _, m, _, _, _ in cam_entries]
    )
    diverging = sorted({
        m["fps"] for _, m, _, _, _ in cam_entries
        if abs(m["fps"] - project_fps) >= _FPS_EPSILON
    })
    if diverging:
        listed = ", ".join(f"{f:g}" for f in diverging)
        emit(f"Atenção: câmeras a {listed} fps num projeto a {project_fps:g} fps.",
             0, total)

    sounds = []
    for spath, smeta, sgid, sapath in snd_entries:
        snd = _Sound(spath, smeta, audio_path=sapath)
        snd.group_id = sgid or str(spath)
        sounds.append(snd)

    # ── 3. Agrupar câmeras por câmera física ─────────────────────────────────
    groups: dict[str, list[_Clip]] = {}
    group_order_seen: list[str] = []
    group_names: dict[str, str] = {}

    for cam_path, cam_meta, gid, gord, cam_apath in cam_entries:
        gid = gid or str(cam_path)
        if gid not in groups:
            groups[gid] = []
            group_order_seen.append(gid)
        groups[gid].append(
            _Clip(cam_path, cam_meta, gid, gord, project_fps, audio_path=cam_apath))

    for gid, clips in groups.items():
        # Ordem de gravação, em TRÊS passos — e a ordem deles importa.
        #
        # 1. ORDEM PROVISÓRIA, pelo NOME. É de onde sai a informação que o timecode
        #    não tem: o contador de clipe de um cartão (`A001`…`A077`) é monotônico
        #    na gravação, e o TC não é (ele vira à meia-noite).
        # 2. DESDOBRAR o TC ao longo dessa ordem — uma queda grande é uma virada de
        #    dia. Ver `sync/daycycle.py`.
        # 3. ORDEM FINAL pelo TC DESDOBRADO, quando o relógio serve. É o passo que
        #    conserta um arquivo fora de ordem no nome, que era o motivo de ordenar
        #    por TC antes de tudo — só que agora sem cortar a diária ao meio.
        #
        # NÃO usar `recorded_at`: o relógio interno da câmera do dataset é
        # não-monotônico, e nos arquivos convertidos ele traz a data da CONVERSÃO,
        # não a da filmagem (o proxy RED do material real diz 2026-07-09).
        if all(c.group_order is not None for c in clips):
            clips.sort(key=lambda c: c.group_order)
        else:
            clips.sort(key=lambda c: _natural_sort_key(c.path))

        if _tc_usable(clips):
            days, wrapped = unwrap_along_order([c.tc_sec for c in clips])
            for c, d in zip(clips, days):
                c.day_index = d
            if wrapped:
                emit(f"{source_names.get(gid) or gid}: a captação atravessa a "
                     f"meia-noite — o timecode foi desdobrado.", 0, total)

        # ⭐ O passo 3 agora obedece à BASE DECLARADA para esta fonte.
        #
        # Antes ele rodava sempre que o relógio andasse, e com isso o timecode
        # SOBRESCREVIA a ordem que veio da interface. Numa captação organizada isso
        # é o certo; numa captação falha é o motor confiando num relógio que não
        # merece — e o usuário não tinha como dizer em qual câmera confiar.
        #
        # Os passos 1 e 2 continuam SEMPRE: o `day_index` do passo 2 depende da
        # ordem provisória do passo 1, e sem ele a virada da meia-noite volta a
        # partir a diária em duas.
        base = _base_da_fonte(gid, clips, source_chronology, source_names, emit, total)
        for c in clips:
            c.basis = base
        if base == "timecode":
            clips.sort(key=lambda c: c.tc_abs_sec)

            # ⚠️ Aqui, e não dentro da ilha: a pergunta é sobre a FONTE INTEIRA e
            # em ordem de TC — uma ilha vê só um recorte dela. Ver `_Clip.tc_rec_run`.
            rec = chronology.rec_run([c.tc_abs_frames for c in clips],
                                     [c.duration_frames for c in clips])
            for c in clips:
                c.tc_rec_run = rec
            if rec:
                emit(f"{source_names.get(gid) or gid}: o timecode desta câmera é "
                     f"rec-run (só anda enquanto grava) — ele põe os clipes em "
                     f"ordem, mas não mede a distância entre eles; quem posiciona "
                     f"é a forma de onda.", 0, total)

        # O nome que o usuário deu à fonte. Sem ele (payload antigo, ou um arquivo
        # solto), cai no que sempre se fez: o nome da pasta, ou o do próprio arquivo
        # quando a fonte tem um clipe só.
        name = source_names.get(gid) or (
            Path(gid).name if len(clips) > 1 else clips[0].path.name
        )
        group_names[gid] = name
        for c in clips:
            c.group_name = name

    # Os sons entram no mesmo eixo das câmeras — depois delas, porque é a janela
    # delas que responde de que dia é cada som. Ver `_unwrap_sounds`.
    _unwrap_sounds(sounds, groups, group_order_seen)
    _ordenar_sons(sounds)

    all_clips = [c for gid in group_order_seen for c in groups[gid]]

    # ── 3.5 Fixar os clipes que o RE-SYNC PARCIAL não selecionou ─────────────
    #
    # Eles não passam pela correlação: entram já resolvidos, com a confiança no
    # teto — é isso que os torna ÂNCORA para os que FORAM selecionados, sem gastar
    # um segundo relendo um arquivo que ninguém pediu para reconsiderar.
    if pinned:
        sound_by_path = {str(s.path): s for s in sounds}
        for c in all_clips:
            fixado = pinned.get(str(c.path))
            if fixado is None:
                continue
            offset_frames, sound_path = fixado
            snd = sound_by_path.get(sound_path)
            if snd is None:
                # O som apontado não está (mais) nesta diária — não há como
                # ancorar nele. Cai para a correlação normal, se selecionado; senão
                # fica sem som, como um órfão.
                continue
            c.sound = snd
            c.offset_frames = offset_frames
            c.confidence = PINNED_CONFIDENCE
            c.pinned = True
            snd.clips.append(c)
            if c.tc_abs_sec is not None and snd.tc_abs_sec is not None:
                c.implied_delta = (
                    snd.tc_abs_sec + offset_frames / project_fps) - c.tc_abs_sec

    # ── 4. Parear cada clipe com o seu som ───────────────────────────────────
    # Só entram no alinhamento por TC as câmeras cujo relógio SERVE (ver
    # _tc_usable) e os sons que têm TC. Uma câmera com relógio inútil ainda é
    # sincronizada pela waveform — o que ela não pode é envenenar o desenho.
    tc_gids = [gid for gid in group_order_seen if _tc_usable(groups[gid])]
    tc_clips = [c for gid in tc_gids for c in groups[gid]]
    tc_sounds = [s for s in sounds if s.tc_sec is not None]

    offsets = []
    if tc_clips and tc_sounds:
        emit("Alinhando o desenho dos arquivos pelo timecode...", 0, len(all_clips))
        offsets = clock_offsets(
            [Interval(str(c.path), c.tc_abs_sec, c.tc_abs_sec + c.duration_s)
             for c in tc_clips],
            [Interval(str(s.path), s.tc_abs_sec, s.tc_abs_sec + s.duration_s)
             for s in tc_sounds],
        )

    if not has_sound:
        # Nada com que parear. Cada clipe fica sinalizado `no_sound` e vai para a
        # bin — sinalizado, nunca descartado. `_place_on_timeline` os posiciona pelo
        # TC (ou os emenda em sequência, se não houver relógio).
        emit("Sem som direto: os clipes vão sinalizados.", 0, len(all_clips))
        for c in all_clips:
            c.flagged, c.flag_reason = True, "no_sound"
            _emit_clip(on_clip, c, project_fps)
    elif sync_method == "timecode":
        # TIMECODE PURO — sem ler áudio. Coloca cada clipe no seu TC e o pareia com
        # o som cujo TC se sobrepõe. Ver `_pair_by_tc_only`.
        emit("Posicionando pelo timecode...", 0, len(all_clips))
        _pair_by_tc_only(
            all_clips, sounds, project_fps, emit, on_clip, on_sound, selected=selected,
        )
    elif sync_method == "waveform":
        # FORMA DE ONDA PURA — ignora o TC no pareamento, mesmo quando ele serviria.
        # É a escolha do usuário: "não confie no relógio, ouça".
        emit("Pareando por forma de onda...", 0, len(all_clips))
        _pair_by_waveform(
            groups, group_order_seen, sounds, project_fps, emit, on_clip, on_sound,
            selected=selected,
        )
    elif offsets:
        listed = ", ".join(f"{o.coverage:.0%}" for o in offsets)
        emit(f"{len(offsets)} alinhamento(s) de relógio ({listed})", 0, len(all_clips))
        _pair_by_timecode(
            tc_clips, tc_sounds, offsets, project_fps, emit, on_clip, on_sound,
            selected=selected,
        )

        # As câmeras sem relógio utilizável caem na busca cega.
        rest = {gid: groups[gid] for gid in group_order_seen if gid not in tc_gids}
        if rest:
            emit("Câmeras sem relógio — pareando por forma de onda...",
                 0, len(all_clips))
            _pair_by_waveform(
                rest, list(rest), sounds, project_fps, emit, on_clip, on_sound,
                selected=selected,
            )
    else:
        # Ou não há timecode, ou o desenho não identifica Δ (som contínuo, sem
        # buracos para encaixar — ver tcmatch._plateau_width). Nos dois casos quem
        # responde é a forma de onda.
        emit("Pareando por forma de onda...", 0, len(all_clips))
        _pair_by_waveform(
            groups, group_order_seen, sounds, project_fps, emit, on_clip, on_sound,
            selected=selected,
        )

    # ── 4.4. Fonte com relógio confiável anda como uma corrente ──────────────
    #
    # Antes da resolução de sobreposição, de propósito: travar a cronologia já
    # elimina boa parte das colisões (posições de timecode não se sobrepõem numa
    # câmera que se comporta), e as que sobrarem são as de verdade.
    _travar_cronologia(groups, group_order_seen, project_fps, emit, on_clip)

    # ── 4.5. Dois clipes da MESMA câmera não podem ocupar o mesmo tempo ──────
    #
    # Aqui, e não depois: neste ponto o grafo clipe↔som já fechou (então a ilha
    # existe) e o som ainda está carregável (então dá para RE-MEDIR). Depois de
    # `_place_on_timeline` só existiria `timeline_start`, e corrigir por ali
    # desincronizaria o clipe do próprio som. Ver `_resolve_source_overlaps`.
    _resolve_source_overlaps(
        groups, group_order_seen, project_fps, emit, on_clip, sync_method,
    )

    for s in sounds:
        s.release()

    # ── 5. Posições absolutas na timeline ────────────────────────────────────
    emit("Montando a timeline...", 0, 0, "final", frac=0.0)
    _place_on_timeline(groups, group_order_seen, sounds, project_fps)

    # ── 6. Materializar o Daily ──────────────────────────────────────────────
    daily = _build_daily(
        groups, group_order_seen, group_names, sounds, all_clips,
        project_fps, project_name, start_tc_frames,
    )
    # ⚠️ AVISA, NÃO RECUSA — decisão do usuário em 2026-08-05. Antes disto o motor
    # levantava quando a diária passava de 24 h, e isso o impedia de ENTREGAR
    # material que ele havia sincronizado perfeitamente. Quem sabe se aquilo são
    # dois dias de trabalho ou um dia esquisito é quem filmou; o programa mostra a
    # medida e oferece a divisão (ver `sync/resultsplit.py`).
    warning = daily.span_warning()
    if warning:
        emit(warning, 0, 0, "final", frac=1.0)
    emit("Pronto.", 0, 0, "final", frac=1.0)
    return daily


# ── Pareamento por TIMECODE PURO (sem áudio) ─────────────────────────────────


def _pair_by_tc_only(
    clips: list[_Clip],
    sounds: list[_Sound],
    fps: float,
    emit: ProgressCallback,
    on_clip,
    on_sound=None,
    selected: set[str] | None = None,
) -> None:
    """
    SINCRONIZAÇÃO POR TIMECODE PURO — sem correlação, sem ler áudio de câmera.

    Coloca cada clipe no seu TC de entrada e o pareia com o som cujo TC se
    sobrepõe. O offset é a diferença de TC (`cam_TC − snd_TC`) — que é o sync
    EXATO quando câmera e gravador compartilham o relógio (jam sync). É a opção
    para quando o usuário SABE que o TC está certo: vê a timeline inteira na hora,
    e conserta pontualmente, pela seleção, os poucos clipes onde o TC falhou
    (re-sync por forma de onda daquela seleção).

    O que NÃO tem TC não tem como ser posicionado por aqui: fica sinalizado
    (`no_tc`). O que tem TC mas não cai em som nenhum vai para os órfãos,
    ancorado pelo próprio TC em `_place_on_timeline`.

    `selected` (RE-SYNC PARCIAL) — processa só quem está nele; o resto já chegou
    fixado por `pinned` e não é tocado.
    """
    snd_with_tc = [s for s in sounds if s.tc_sec is not None]
    to_process = [c for c in clips if selected is None or str(c.path) in selected]
    total = len(to_process)
    done = 0

    for c in to_process:
        if c.tc_sec is None:
            # Sem relógio, o TC puro não tem o que fazer — é a resposta honesta.
            c.flagged, c.flag_reason = True, "no_tc"
            done += 1
            emit(f"{c.path.name}: sem timecode", done, total)
            _emit_clip(on_clip, c, fps)
            continue

        # O som cujo TC mais se sobrepõe ao do clipe. Sobreposição, e não só
        # "contém o início", porque um clipe pode começar antes do gravador e
        # ainda pertencer àquele som.
        best = None
        for s in snd_with_tc:
            overlap = (min(c.tc_abs_sec + c.duration_s, s.tc_abs_sec + s.duration_s)
                       - max(c.tc_abs_sec, s.tc_abs_sec))
            if overlap > 0 and (best is None or overlap > best[1]):
                best = (s, overlap)

        if best is None:
            c.flagged, c.flag_reason = True, "no_sound"
            done += 1
            emit(f"{c.path.name}: TC fora de qualquer som", done, total)
            _emit_clip(on_clip, c, fps)
            continue

        snd = best[0]
        c.sound = snd
        c.offset_frames = round((c.tc_abs_sec - snd.tc_abs_sec) * fps)
        # O TC é a fonte da verdade aqui — confiança no teto, como um clipe fixado.
        # Isso também o credencia como âncora se um resync por waveform vier depois.
        c.confidence = PINNED_CONFIDENCE
        # Posicionado pelo TC, SEM verificar o áudio — a timeline pinta diferente.
        c.sync_source = "timecode"
        snd.clips.append(c)
        done += 1
        emit(f"TC {c.path.name}: {c.offset_frames:+d} frames", done, total)
        _emit_clip(on_clip, c, fps)
        _ensure_sound_peaks(snd)
        _emit_sound(on_sound, snd, c, fps)


# ── Pareamento COM timecode ──────────────────────────────────────────────────


def _pair_by_timecode(
    clips: list[_Clip],
    sounds: list[_Sound],
    offsets: list,
    fps: float,
    emit: ProgressCallback,
    on_clip,
    on_sound=None,
    selected: set[str] | None = None,
) -> None:
    """
    O diferencial: o timecode diz QUEM VAI COM QUEM; a waveform diz por QUANTOS
    FRAMES.

    O alinhamento do desenho reduz os candidatos de "todos os sons do dia" para
    um ou dois. A correlação então roda contra esses — e sem tomadas repetidas
    concorrendo, ela deixa de ter como escolher a errada.

    `selected` (RE-SYNC PARCIAL) — `None` processa `clips` inteiro, como sempre.
    Um conjunto pula quem está fora dele: já foi resolvido por `pinned` em `run()`,
    e mexer nele de novo seria o re-sync parcial custar a diária inteira.
    """
    cam_ivs = [
        Interval(str(c.path), c.tc_abs_sec, c.tc_abs_sec + c.duration_s)
        for c in clips if c.tc_abs_sec is not None
    ]
    snd_ivs = [
        Interval(str(s.path), s.tc_abs_sec, s.tc_abs_sec + s.duration_s)
        for s in sounds if s.tc_abs_sec is not None
    ]
    by_path = {str(s.path): s for s in sounds}

    # O progresso conta só o que VAI SER PROCESSADO — num re-sync parcial, o pulado
    # nem entra na conta, para a barra não andar pela diária inteira e mentir que
    # tudo foi reprocessado.
    total = sum(1 for c in clips if selected is None or str(c.path) in selected)
    done = 0
    for c in clips:
        if selected is not None and str(c.path) not in selected:
            # Fixado pelo `pinned` de `run()` (ou nem tocado) — o re-sync parcial
            # não lê o arquivo dele de novo.
            continue

        ok, reason = c.syncable
        if not ok:
            c.flagged, c.flag_reason = True, reason
            done += 1
            emit(f"{c.path.name}: não sincronizável ({reason})", done, total)
            _emit_clip(on_clip, c, fps)
            continue

        iv = next((i for i in cam_ivs if i.key == str(c.path)), None)
        cands = candidate_sounds(iv, snd_ivs, offsets) if iv else []

        if not cands:
            # Não caiu dentro de som nenhum, em nenhum regime. Normal: a câmera
            # roda antes do gravador, entre tomadas, e em planos sem som.
            c.flagged, c.flag_reason = True, "no_sound"
            done += 1
            emit(f"{c.path.name}: sem som direto correspondente", done, total)
            _emit_clip(on_clip, c, fps)
            continue

        emit(f"Sincronizando {c.path.name}...", done, total)

        # O TIMECODE JÁ DISSE QUAL É O SOM. O que falta é ONDE, dentro dele — e para
        # isso não é preciso ler o clipe inteiro: uma JANELA dele basta, e a busca
        # continua varrendo o som TODO, exatamente como antes.
        #
        # Não caia na tentação de estreitar também a busca DENTRO do som usando o Δ
        # do `clock_offsets`: esse Δ é GROSSO (candidatos a 30 s de distância um do
        # outro — ele foi feito para escolher o som, não para apontar dentro dele).
        # Uma janela de busca de ±2 s em cima dele prendeu a correlação no lugar
        # errado e moveu 3 clipes da D02 em ~3 s. O som é barato de ler; a câmera é
        # que não é. Economize no lado caro, e só nele.
        best = None
        if c.size_bytes > WHOLE_FILE_BUDGET_BYTES:
            for snd_key in dict.fromkeys(k for k, _ in cands):
                snd = by_path[snd_key]
                r = _measure_window(c, snd, fps)
                if r is None:
                    continue
                if best is None or r[1] > best[1]:
                    best = (*r, snd)

        # NÃO filtrar aqui por `TRUST_RATIO`. Esse limiar foi calibrado para a razão
        # do ENVELOPE (`sync_camera_to_wav`); a correlação de PCM cru da janela tem
        # outra escala e fica em ~1,1–3,9 mesmo quando acerta. Barrar por ele mandava
        # metade dos clipes para a leitura integral sem motivo — e devolvia os 18
        # minutos. Quem julga se o resultado presta é `_corroborate_by_delta`, que
        # compara o Δ deste clipe com o do REGIME do relógio: é uma medida absoluta,
        # e não depende da escala de nenhuma razão.
        if best is None:
            whole = _measure_whole_file(c, cands, by_path, fps)
            if whole is not None:
                best = whole

        if best is None:
            c.flagged, c.flag_reason = True, "no_sound"
            done += 1
            emit(f"{c.path.name}: não foi possível medir", done, total)
            _emit_clip(on_clip, c, fps)
            continue

        offset, ratio, snd = best
        c.sound, c.offset_frames, c.confidence = snd, offset, ratio
        c.sync_source = "waveform"   # o som confirmou de verdade
        snd.clips.append(c)

        # Δ IMPLÍCITO deste par: agora que o offset é conhecido, dá para dizer
        # exatamente quanto o relógio da câmera está adiantado em relação ao do
        # gravador. É o número que a checagem de coerência abaixo usa — muito mais
        # preciso que o Δ grosso do encaixe do desenho, que só serviu para propor
        # o candidato.
        c.implied_delta = (snd.tc_abs_sec + offset / fps) - c.tc_abs_sec

        c.pcm = None
        done += 1
        emit(f"Sync {c.path.name}: {offset:+d} frames", done, total)
        _emit_clip(on_clip, c, fps)
        _ensure_sound_peaks(snd)
        _emit_sound(on_sound, snd, c, fps)

    _corroborate_by_delta(clips, fps, on_clip, selected=selected, emit=emit)


def _ensure_sound_peaks(snd: _Sound) -> None:
    """A waveform do SOM, que a timeline desenha.

    Primeiro o CACHE EM DISCO (os nossos `.pek`): num segundo sync da mesma diária
    — e no modo TC, que promete "sem processamento" — reler 2,5 GB de som só para
    redesenhar uma onda que não mudou seria pagar duas vezes pela mesma imagem.

    Sem cache, vale a leitura integral: o som é a REFERÊNCIA — é contra ele que o
    usuário confere o sync com os olhos. As waveforms das CÂMERAS não são feitas
    aqui: elas custariam o arquivo inteiro de cada clipe, que é justamente o que
    este caminho existe para evitar. Vêm depois, em segundo plano
    (comando `compute_peaks`).
    """
    if snd.peaks is not None:
        return
    cached = peakcache.load(snd.path)
    if cached is not None:
        snd.peaks = base64.b64encode(cached.tobytes()).decode("ascii")
        return
    snd.load_pcm()
    snd.release()


def _measure_window(
    c: _Clip,
    snd: _Sound,
    fps: float,
    near_frames: int | None = None,
    half_frames: int = 0,
) -> tuple[int, float] | None:
    """
    Onde `c` cai dentro de `snd` — lendo só uma JANELA do clipe.

    Devolve `(offset_frames, razão)`, ou `None` se não houver janela utilizável.

    A ECONOMIA É SÓ DO LADO DA CÂMERA, e é onde ela toda está: o áudio de câmera
    vive interleavado com o vídeo, então ler 20 s de som de um MXF ProRes custa ler
    20 s de imagem junto (~4 s de disco). O SOM é lido inteiro — um dia de som
    direto são ~2,5 GB contra os 202 GB das câmeras.

    Por padrão a busca varre o som TODO: nada restringe ONDE o pico pode cair, só
    QUANTO do clipe se usa para achá-lo. `near_frames` restringe a busca a
    ±`half_frames` de um offset previsto — e **só deve ser usado quando a previsão
    for PRECISA** (o Δ medido de um regime de relógio). O Δ grosso do
    `clock_offsets` NÃO serve: os candidatos dele ficam a 30 s um do outro, e
    prender a busca neles moveu clipes da D02 em 3 s.
    """
    cam_dur = c.duration_s

    cw0 = min(WAVEFORM_WINDOW_LEAD_S, max(0.0, cam_dur - WAVEFORM_WINDOW_S))
    cw = min(WAVEFORM_WINDOW_S, cam_dur - cw0)
    if cw < MIN_SYNC_DURATION_S:
        return None

    cam_pcm = normalize(extract_pcm_window(c.audio_path, cw0, cw))
    snd_pcm = snd.load_pcm()
    snd.release()
    if len(snd_pcm) < len(cam_pcm):
        return None

    # A janela do clipe começa em `cw0` DENTRO dele, então ela cai em
    # `offset + cw0` dentro do som.
    lo = 0
    if near_frames is not None:
        lo = max(0, round((near_frames - half_frames) / fps * PCM_RATE)
                 + round(cw0 * PCM_RATE))
        hi = min(len(snd_pcm),
                 round((near_frames + half_frames) / fps * PCM_RATE)
                 + round(cw0 * PCM_RATE) + len(cam_pcm))
        snd_pcm = snd_pcm[lo:hi]
        if len(snd_pcm) < len(cam_pcm):
            return None

    found = confirm_offset(cam_pcm, snd_pcm)
    if found is None:
        return None

    pos_s, ratio = found
    return round((lo / PCM_RATE + pos_s - cw0) * fps), ratio


def _measure_whole_file(
    c: _Clip, cands, by_path: dict[str, _Sound], fps: float
) -> tuple[int, float, _Sound] | None:
    """O caminho CARO: lê o clipe inteiro. Só para quem a janela não resolveu."""
    if c.pcm is None:
        c.pcm = normalize(extract_pcm(str(c.audio_path)))

    best = None
    for snd_key in dict.fromkeys(k for k, _ in cands):
        snd = by_path[snd_key]
        offset, ratio = sync_camera_to_wav(
            wav_path=str(snd.path), camera_path=str(c.path), fps=fps,
            ref_pcm=snd.load_pcm(), cam_pcm=c.pcm,
        )
        snd.release()
        if best is None or ratio > best[1]:
            best = (offset, ratio, snd)
    return best


def _corroborate_by_delta(
    clips: list[_Clip], fps: float, on_clip, selected: set[str] | None = None,
    emit: ProgressCallback | None = None,
) -> None:
    """
    Usa o Δ IMPLÍCITO para consertar o que a correlação errou — e sinalizar o que
    ela não tem como acertar.

    ⚠️ ESTA FASE NÃO É BARATA e por muito tempo foi MUDA. Medida no material do
    usuário (77 proxies RED, 18,5 GB): 28 s dos 95 s do sync — quase um terço —
    depois de a barra do pareamento já ter chegado a 100%. A tela ficava meio
    minuto parada no fim, que é exatamente onde "está travado?" nasce. Por isso
    ela agora recebe o `emit` e tem faixa própria na barra (`_PHASE_BANDS`).

    Δ implícito = o quanto o relógio da câmera está adiantado em relação ao do
    gravador, calculado EXATAMENTE a partir do offset que a waveform achou. Ele só
    muda quando alguém reinicia um aparelho: dentro de um regime é praticamente
    uma constante (medido no material real: variação de 0,0 s ao longo de 24
    tomadas).

    Daí a alavanca: um clipe cujo Δ destoa do regime está errado, e o Δ do regime
    DIZ ONDE ELE DEVERIA ESTAR. Então em vez de só sinalizá-lo, refazemos a
    correlação numa janela estreita ao redor desse offset previsto — e aí não há
    concorrente para ela escolher errado.

    Os regimes são descobertos agrupando os Δ (não há como saber de antemão
    quantos são: uma diária real tem dois, e outra tem um segundo GRAVADOR, com um
    relógio a 6 horas de distância do primeiro).

    Um regime SEM nenhum clipe confiável não tem como se autocorrigir — nada nele
    corrobora nada. Esses clipes ficam sinalizados, e é a resposta honesta:
    "sincronizei, mas não confio; olhe".
    """
    paired = [c for c in clips
              if c.sound is not None and c.implied_delta is not None and c.tc_sec is not None]
    anchors = [c for c in paired if c.confidence >= TRUST_RATIO]
    if len(anchors) < 2:
        return

    # O contador desta fase é "clipes conferidos", e ele anda a cada volta — mesmo
    # nas baratas. É de propósito: a maioria só é conferida (rápido), e é o punhado
    # que precisa de nova medição que custa os segundos. Uma barra que só andasse
    # nos caros ficaria parada por quase toda a fase.
    def step(msg: str, i: int) -> None:
        if emit:
            emit(msg, i, len(paired), "verify")

    for i, c in enumerate(paired):
        if selected is not None and str(c.path) not in selected:
            # Fixado pelo `pinned` — ele É a âncora (entrou em `anchors` acima), e
            # não o alvo de mais uma corroboração.
            continue

        step(f"Conferindo {c.path.name}...", i)

        # O regime de um clipe se descobre pelo TEMPO dele, não pelo Δ dele. Um
        # clipe mal sincronizado tem o Δ errado — agrupar por Δ o jogaria no regime
        # errado, justamente o clipe que se quer consertar. Já o tempo não mente: um
        # regime é um trecho contíguo do dia, e as âncoras confiáveis ao redor dizem
        # qual relógio valia ali.
        near = [a for a in anchors
                if a is not c and abs(a.tc_abs_sec - c.tc_abs_sec) <= ANCHOR_REACH_S]

        if len(near) < 2:
            # Nenhuma âncora por perto. Não há relógio corroborado com que julgar
            # nem corrigir este clipe. Se a correlação também não se garante, o
            # honesto é dizer que não sabemos.
            #
            # ⛔⛔ AQUI JÁ SE TENTOU DESFAZER O PAR, E FOI PIOR — 2026-08-22.
            #
            # O raciocínio parecia bom: "um par de confiança 1,02 é ruído com
            # aparência de dado; sem som o editor vê o buraco, com som errado ele
            # não vê nada". Medido na D03 de `PROJETO EXEMPLO`, desfazer o par levou
            # a diária de **34 tomadas e 2 órfãos** para **23 e 13** — e o autor,
            # abrindo o alpha 0.1.20 lado a lado, viu a diferença na hora.
            #
            # ⭐ O erro foi tratar a escolha como BINÁRIA (palpite ou nada) quando
            # existe uma terceira via, que é justamente esta: **sincronizar E
            # MARCAR**. Um clipe posicionado e sinalizado é uma conferência de
            # segundos, com os vizinhos sincronizados delimitando onde ele pode
            # estar; um bloco de órfãos no fim da timeline é trabalho manual do
            # zero. Palavras do autor sobre os órfãos, que valem aqui também:
            # *"o editor faz uma revisão pontual sabendo que o clipe só pode
            # existir dentro de um espaço de tempo"*.
            #
            # ⚠️ Isto NÃO quer dizer que o pareamento destes clipes esteja certo —
            # não está, e o alpha erra igual. Quer dizer que a resposta para o
            # erro de pareamento não é apagar o par. Ver DECISIONS 28ª e 30ª.
            if c.confidence < TRUST_RATIO:
                c.flagged, c.flag_reason = True, "unverified"
                _emit_clip(on_clip, c, fps)
            continue

        regime_delta = float(np.median([a.implied_delta for a in near]))
        if abs(c.implied_delta - regime_delta) <= TC_AGREEMENT_S:
            continue   # corroborado: o relógio e o som dizem a mesma coisa

        # O regime diz onde este clipe DEVERIA cair. Refaz a correlação só ali — e
        # assim a tomada vizinha, que competia e vencia, sai do páreo.
        predicted_frames = round(
            (regime_delta - c.sound.tc_abs_sec + c.tc_abs_sec) * fps)
        half = round(TC_SEARCH_WINDOW_S * fps)

        # Daqui para baixo é a parte CARA (relê o arquivo do clipe), e é ela que
        # faz esta fase durar dezenas de segundos. Dizer o que está acontecendo é
        # o que separa "está trabalhando" de "travou".
        step(f"Reconferindo {c.path.name} pelo relógio...", i)

        # AQUI a previsão é PRECISA (vem do Δ medido de várias âncoras, não do Δ
        # grosso do `clock_offsets`), então uma janela estreita é segura — e num
        # arquivo de câmera original ela é a diferença entre 10 s e 4 s por clipe.
        found = None
        if c.size_bytes > WHOLE_FILE_BUDGET_BYTES:
            found = _measure_window(
                c, c.sound, fps,
                near_frames=predicted_frames, half_frames=half,
            )
        if found is None:
            offset, ratio = sync_camera_to_wav(
                wav_path=str(c.sound.path), camera_path=str(c.path), fps=fps,
                ref_pcm=c.sound.load_pcm(),
                cam_pcm=normalize(extract_pcm(str(c.audio_path))),
                min_offset_frames=predicted_frames - half,
                max_offset_frames=predicted_frames + half,
            )
            c.sound.release()
        else:
            offset, ratio = found
        c.offset_frames, c.confidence = offset, ratio
        c.implied_delta = (c.sound.tc_abs_sec + offset / fps) - c.tc_abs_sec

        if abs(c.implied_delta - regime_delta) <= TC_AGREEMENT_S:
            _emit_clip(on_clip, c, fps)
            continue   # a janela resolveu: agora concorda com o regime

        # A forma de onda não confirma nem levada pela mão — mas o relógio deste
        # trecho do dia é a MELHOR estimativa que existe, e é dele que sai a posição.
        # Deixar aqui o resultado ruim da correlação seria trocar a medida boa por
        # uma que sabemos ser ruim.
        c.offset_frames = predicted_frames
        c.implied_delta = regime_delta

        # QUÃO confiável é esse relógio decide se o clipe ainda NAGA. Um regime
        # corroborado por VÁRIAS âncoras que concordam apertado (dentro de um regime o
        # Δ é constante a ~0,1 s) posiciona a ~2–3 frames — não é um "não sei", é um
        # sync por timecode legítimo. Vira ardósia (`sync_source="timecode"`) e SAI da
        # lista de "revisar no NLE", em vez de âmbar-hachurado: pintar de duvidoso um
        # clipe que 6 âncoras colocam a 0,02 s do lugar ensina o usuário a ignorar o
        # aviso quando ele importa. Poucas âncoras, ou âncoras que discordam entre si,
        # NÃO dão esse aval — aí segue sinalizado (`tc_only`), como o 2º gravador da
        # tarde (0 âncoras) do material real. Ver o registro interno de decisões.
        near_deltas = [a.implied_delta for a in near]
        clock_trustworthy = (
            len(near) >= CLOCK_TRUST_MIN_ANCHORS
            and max(near_deltas) - min(near_deltas) <= TC_AGREEMENT_S
        )
        if clock_trustworthy:
            c.sync_source = "timecode"
        else:
            c.flagged, c.flag_reason = True, "tc_only"
        _emit_clip(on_clip, c, fps)

    step("Conferência concluída.", len(paired))


# Até que distância no tempo uma âncora ainda diz respeito a este clipe. Um regime
# de relógio é um trecho contíguo do dia; depois de um intervalo longo (o almoço,
# no material real) o aparelho pode ter sido reiniciado, e o relógio de antes já
# não vale.
ANCHOR_REACH_S = 3600.0

# Quantas âncoras próximas (e concordando dentro de TC_AGREEMENT_S) bastam para o
# relógio de um regime posicionar um clipe SEM alarme. Abaixo disso o clipe ainda
# cai no relógio, mas sinalizado (`tc_only`): uma ou duas âncoras dão uma mediana
# frágil. Medido no D03: a manhã tem 6 âncoras concordando a ±0,05 s (relógio
# sólido — os planos de abertura, sem sinal de onda, caem certos nele); a tarde,
# com um 2º gravador sem âncora nenhuma, tem 0 e segue duvidosa.
CLOCK_TRUST_MIN_ANCHORS = 3


# ── Pareamento SEM timecode ──────────────────────────────────────────────────


def _pair_by_waveform(
    groups: dict[str, list[_Clip]],
    order: list[str],
    sounds: list[_Sound],
    fps: float,
    emit: ProgressCallback,
    on_clip,
    on_sound=None,
    selected: set[str] | None = None,
) -> None:
    """
    Sem timecode: cada clipe é correlacionado contra TODOS os sons; vence o de
    maior pico.

    A ambiguidade acústica (tomadas repetidas da mesma cena soam parecidas) é
    resolvida por CRONOLOGIA — clipes e sons avançam na mesma ordem, então um
    clipe duvidoso fica restrito aos sons entre os seus vizinhos confiáveis.
    Restrição física, não acústica: nenhuma métrica de áudio resolve isso sozinha.

    `selected` (RE-SYNC PARCIAL) — quem fica de fora não passa pela passada 1 (não
    lê o arquivo, não corre contra `sounds`); ele já chegou aqui com `c.sound`
    resolvido por `pinned`, com confiança no teto — e é isso que o credencia como
    âncora da passada 2 (`trusted`, mais abaixo) sem precisar de nenhum caso especial
    ali.
    """
    # O total (e o progresso) conta só o que VAI SER PROCESSADO. Num re-sync
    # parcial isto é o que impede a barra de andar por toda a diária e dar a
    # impressão de que tudo foi reprocessado — o pulado nem entra na conta.
    def _in_scope(c: _Clip) -> bool:
        return selected is None or str(c.path) in selected

    total = sum(1 for g in groups.values() for c in g if _in_scope(c))
    done = 0

    for gid in order:
        clips = groups[gid]

        # Passada 1: busca livre, contra todos os sons.
        for c in clips:
            if not _in_scope(c):
                continue

            ok, reason = c.syncable
            if not ok:
                c.flagged, c.flag_reason = True, reason
                done += 1
                emit(f"{c.path.name}: não sincronizável ({reason})", done, total)
                _emit_clip(on_clip, c, fps)
                continue

            emit(f"Sincronizando {c.path.name}...", done, total)
            c.pcm = normalize(extract_pcm(str(c.audio_path)))
            c.peaks = _peaks_b64(c.pcm, c.audio_path)

            best = None
            for s in sounds:
                offset, ratio = sync_camera_to_wav(
                    wav_path=str(s.path), camera_path=str(c.path), fps=fps,
                    ref_pcm=s.load_pcm(), cam_pcm=c.pcm,
                )
                if best is None or ratio > best[1]:
                    best = (offset, ratio, s)

            offset, ratio, snd = best
            c.sound, c.offset_frames, c.confidence = snd, offset, ratio
            c.sync_source = "waveform"
            done += 1
            emit(f"Sync {c.path.name}: {offset:+d} frames", done, total)
            _emit_clip(on_clip, c, fps)

        # Passada 2: os duvidosos são reexaminados só entre os sons que a
        # CRONOLOGIA permite — entre o som do vizinho confiável anterior e o do
        # próximo. Uma câmera não grava dois arquivos ao mesmo tempo, e o gravador
        # não volta no tempo: é uma restrição física, e é o que resolve a
        # ambiguidade acústica das tomadas repetidas (nenhuma métrica de áudio
        # resolve isso sozinha).
        trusted = {c for c in clips if c.confidence >= TRUST_RATIO and c.sound}
        snd_index = {s: i for i, s in enumerate(sounds)}

        for i, c in enumerate(clips):
            if c.flagged or c.confidence >= TRUST_RATIO or not c.sound:
                continue

            prev = next((clips[j] for j in range(i - 1, -1, -1) if clips[j] in trusted), None)
            nxt = next((clips[j] for j in range(i + 1, len(clips)) if clips[j] in trusted), None)
            if prev is None and nxt is None:
                # Grupo inteiro ambíguo: não há âncora com que desambiguar.
                c.flagged, c.flag_reason = True, "ambiguous"
                _emit_clip(on_clip, c, fps)
                continue

            lo = snd_index[prev.sound] if prev else 0
            hi = snd_index[nxt.sound] if nxt else len(sounds) - 1
            window = sounds[lo : hi + 1]
            if not window:
                c.flagged, c.flag_reason = True, "ambiguous"
                _emit_clip(on_clip, c, fps)
                continue

            emit(f"Refinando {c.path.name} entre vizinhos...", done, total)
            best = None
            for s in window:
                # A cronologia restringe DUAS coisas, e as duas importam:
                #   - QUAL som (a janela acima), quando há vários;
                #   - ONDE dentro do som, quando um vizinho compartilha o mesmo
                #     som. Este clipe tem que começar depois do fim do anterior e
                #     terminar antes do início do próximo — uma câmera não grava
                #     dois arquivos ao mesmo tempo.
                # Sem a segunda, um projeto com um único som direto (o caso de uma
                # gravação contínua) fica sem desambiguação nenhuma.
                lo = hi = None
                if prev is not None and prev.sound is s:
                    lo = prev.offset_frames + prev.duration_frames
                if nxt is not None and nxt.sound is s:
                    hi = nxt.offset_frames - c.duration_frames
                if lo is not None and hi is not None and hi < lo:
                    # Janela impossível: uma das âncoras está errada, ou a ordem
                    # dos arquivos do grupo está.
                    continue

                offset, ratio = sync_camera_to_wav(
                    wav_path=str(s.path), camera_path=str(c.path), fps=fps,
                    ref_pcm=s.load_pcm(), cam_pcm=c.pcm,
                    min_offset_frames=lo, max_offset_frames=hi,
                )
                if best is None or ratio > best[1]:
                    best = (offset, ratio, s)

            if best is None:
                c.flagged, c.flag_reason = True, "anchor_window_impossible"
                _emit_clip(on_clip, c, fps)
                continue

            offset, ratio, snd = best
            c.sound, c.offset_frames, c.confidence = snd, offset, ratio
            c.sync_source = "waveform"
            if ratio < FLAG_RATIO:
                c.flagged, c.flag_reason = True, "ambiguous"
            _emit_clip(on_clip, c, fps)

        for c in clips:
            if c.sound and c not in c.sound.clips:
                c.sound.clips.append(c)
            if c.sound:
                _emit_sound(on_sound, c.sound, c, fps)
            c.pcm = None


def _travar_cronologia(
    groups: dict[str, list["_Clip"]],
    order: list[str],
    fps: float,
    emit: ProgressCallback,
    on_clip,
) -> None:
    """
    Numa fonte cujo relógio é confiável, os clipes andam JUNTOS — como uma corrente.

    ## A ideia

    Uma câmera com timecode bom já sabe a distância entre os seus próprios clipes: é
    o intervalo do relógio. O que ela NÃO sabe é onde essa corrente começa em relação
    ao som — e isso a forma de onda mede bem.

    Então, para `basis == "timecode"`, o sync deixa de decidir a posição de cada
    clipe e passa a decidir a de todos de uma vez: a corrente inteira desliza pelo
    deslocamento que MELHOR concorda com as medições confiáveis, e cada clipe mantém
    a distância que o relógio manda.

    ## Por que isto importa (medido, não suposto)

    No material do gabarito, posicionar por timecode acerta 63% contra 12% do
    híbrido. A causa é a ilha: quando dezenas de clipes casam com um mesmo som, o
    posicionamento vem dos offsets medidos um a um — e basta um punhado de medições
    ruins (som curto é ímã de falso positivo) para espalhar a câmera inteira. Travar
    a corrente tira do falso positivo o poder de mover um clipe sozinho.

    ## ⚠️ Por ILHA, e o motivo é uma armadilha de quadro de referência

    `offset_frames` é medido contra o SOM DAQUELE CLIPE. Dois clipes presos a sons
    diferentes têm offsets que não se comparam — a primeira versão desta função
    somou os dois como se fossem o mesmo eixo e moveu clipes que estavam certos (dois
    testes de sobreposição pegaram na hora). Dentro da ilha existe um eixo comum, o
    `rel` de `_relative_positions`, e é nele que a conta fecha.

    ## O que continua livre

    `free` e `name` não passam por aqui: lá cada clipe encontra o seu lugar, que é o
    comportamento de sempre. E a forma de onda continua sendo lida em todos os casos
    — ela deixa de POSICIONAR e passa a CONFIRMAR, que é o papel em que ela é boa.
    """
    travados = 0

    for clips, snds in _build_islands(groups, order):
        if len(clips) < 2 or not snds:
            continue
        rel = _relative_positions(clips, snds)

        por_fonte: dict[str, list[_Clip]] = {}
        for c in clips:
            if (getattr(c, "basis", "name") == "timecode" and c.sound is not None
                    and c.tc_abs_frames is not None and c in rel and c.sound in rel):
                por_fonte.setdefault(c.group_id, []).append(c)

        for gid, da_fonte in por_fonte.items():
            # ⚠️ TRÊS clipes, não dois — a corrente precisa de CORROBORAÇÃO.
            #
            # Com dois, a "mediana dos resíduos" é literalmente um dos dois: o
            # motor copia o resíduo de um clipe no outro e chama isso de voto.
            # Não há nada ali que confirme que o espaçamento do relógio vale — e
            # desde que se sabe que um TC pode ser rec-run (não medir distância
            # nenhuma), com dois clipes NÃO DÁ para descobrir de que tipo ele é.
            # Medido no MULTCAM: a CAM A, de dois clipes, era arrastada 38 frames
            # (1,6 s) para longe de uma medição de forma de onda confiável.
            if len(da_fonte) < 3:
                continue

            # ⚠️ REC-RUN NÃO MEDE DISTÂNCIA — travar a corrente por ele destrói o
            # que a forma de onda acertou. Ver `_Clip.tc_rec_run`.
            if da_fonte[0].tc_rec_run:
                continue

            # Quanto a corrente teria de deslizar se CADA clipe estivesse certo.
            residuos = [(rel[c] - c.tc_abs_frames, c) for c in da_fonte]
            confiaveis = [r for r, c in residuos if c.confidence >= TRUST_RATIO]
            votantes = sorted(confiaveis or [r for r, _ in residuos])
            # Voto por MEDIANA, não média: uma medição perdida a 20 minutos de
            # distância puxaria a média e levaria a corrente inteira junto.
            deslize = votantes[len(votantes) // 2]

            for r, c in residuos:
                novo_rel = c.tc_abs_frames + deslize
                if novo_rel == rel[c]:
                    continue
                # ⚠️ QUEM ANDOU PELA CORRENTE PRECISA DIZER ISSO.
                #
                # Medido no gabarito: travar a cronologia melhorou a ordem
                # (66,7% → 82,6%) e a posição (11,7% → 25,6%), MAS piorou o número
                # que mais importa — clipes errados e CALADOS foram de 21 para 26.
                # A causa: um clipe que a forma de onda não confirmou saía do lugar
                # pela corrente e perdia o aviso no caminho, ficando com cara de
                # sync verificado. Duas marcas, conforme o motivo:
                #   • discorda MUITO do coro → o relógio dele mente em algum ponto;
                #   • nunca foi confirmado → posicionado pelo relógio, e só.
                if abs(r - deslize) > round(TC_AGREEMENT_S * fps):
                    c.flagged, c.flag_reason = True, "chronology_locked"
                elif c.confidence < TRUST_RATIO:
                    c.flagged, c.flag_reason = True, "tc_only"
                if c.confidence < TRUST_RATIO:
                    # A cor da timeline não pode dizer "conferido pela onda".
                    c.sync_source = "timecode"
                c.offset_frames = novo_rel - rel[c.sound]
                rel[c] = novo_rel
                travados += 1
                _emit_clip(on_clip, c, fps)

    if travados:
        emit(f"Cronologia travada pelo timecode em {travados} clipe(s).", 0, 0)


# ── Sobreposição DENTRO da ilha ──────────────────────────────────────────────

#: Teto de re-medições por sync. Cada uma lê uma janela do clipe do disco; num
#: material muito bagunçado, deixar sem teto transformaria o sync numa espera.
#: Passando disto, o resto é encaixado e sinalizado — que é a resposta honesta.
MAX_OVERLAP_REMEASURES = 40


def _prioridade_de_ancora(c: "_Clip", ordem: int, delta_tipico: float | None):
    """
    Quem fica no lugar quando dois clipes da mesma câmera se sobrepõem.

    Menor tupla ganha. A ordem das regras é o desenho todo:

    1. **Fixado pelo usuário** — é a única verdade humana no conjunto. Mover o que
       uma pessoa confirmou é pior que o sintoma que se está consertando.
    2. **Maior confiança, com `≥ 99` tratado como PLATÔ.** O 99 é saturação
       ("não havia concorrente"), não uma nota — e o 999 do TC puro quer dizer
       "confiança de teto para servir de âncora", com o áudio nunca conferido.
       Tratar os dois como iguais evita que um empate falso decida a disputa.
    3. **Concordância com o relógio do conjunto** — entre dois clipes igualmente
       (in)confiáveis, ganha o que está mais perto do Δ típico das âncoras.
    4. **Duração** — o clipe mais longo tem mais sinal e erra menos.
    5. **Ordem no grupo** — desempate final, só para o resultado ser determinístico.
    """
    conf = min(c.confidence, 99.0)
    if delta_tipico is not None and c.implied_delta is not None:
        desvio = abs(c.implied_delta - delta_tipico)
    else:
        desvio = float("inf")
    return (0 if c.pinned else 1, -conf, desvio, -c.duration_frames, ordem)


def _espaco_livre(
    inicio_desejado: int, dur: int, ocupados: list[tuple[int, int]]
) -> tuple[float, float, int] | None:
    """
    O vão desta track onde `c` ainda cabe, e o ponto legal mais PRÓXIMO de onde a
    correlação queria pô-lo.

    Devolve `(lo, hi, alvo)`: o clipe pode começar em qualquer ponto de `[lo, hi]`
    (que podem ser ±infinito, para o espaço antes do primeiro e depois do último), e
    `alvo` é `inicio_desejado` grampeado nesse intervalo.

    Escolher o vão pela DISTÂNCIA ao ponto medido é o que impede a correção de
    arrastar um clipe para o outro lado da diária só porque lá havia mais espaço —
    o conserto tem de mentir o mínimo possível sobre o que a medição disse.

    ⚠️ `hi` é o último INÍCIO possível (`fim_do_vão − duração`), não o fim do vão.
    Confundir os dois foi o primeiro bug desta função: num vão sem limite à
    esquerda, o clipe era encostado num ponto que o fazia invadir o vizinho.
    """
    bordas = sorted(ocupados)
    vaos: list[tuple[float, float]] = []
    anterior: float = -math.inf
    for ini, fim in bordas:
        vaos.append((anterior, float(ini)))
        anterior = float(fim)
    vaos.append((anterior, math.inf))

    melhor = None
    for lo, hi in vaos:
        lo_h = lo
        hi_h = hi - dur if hi != math.inf else math.inf
        if hi_h < lo_h:
            continue                      # o vão não comporta este clipe
        alvo = min(max(float(inicio_desejado), lo_h), hi_h)
        dist = abs(alvo - inicio_desejado)
        if melhor is None or dist < melhor[0]:
            melhor = (dist, lo_h, hi_h, int(round(alvo)))

    if melhor is None:
        return None
    _, lo_h, hi_h, alvo = melhor
    return lo_h, hi_h, alvo


def _resolve_source_overlaps(
    groups: dict[str, list["_Clip"]],
    order: list[str],
    fps: float,
    emit: ProgressCallback,
    on_clip,
    sync_method: str = "hybrid",
) -> None:
    """
    Dois clipes da MESMA câmera sobrepostos DENTRO da mesma ilha.

    ## Por que este passe existe

    `_resolve_track_overlaps` já garantia que duas ilhas não se pisam. Mas ele
    empurra a ilha INTEIRA e compara os intervalos dela só contra as ilhas já
    posicionadas — **nunca contra os membros dela mesma**. E uma ilha é a componente
    conexa do grafo clipe↔som: num WAV de 30 min, dezenas de clipes da mesma câmera
    caem numa ilha só. Ou seja, a regra ficava inerte exatamente no caso mais comum
    de documentário. Foi assim que uma diária real veio com a câmera empilhada.

    ## O que uma sobreposição dessas significa

    **Não é um problema de arrumação — é a prova de que um dos dois casou errado.**
    Uma câmera não grava dois arquivos ao mesmo tempo. Empurrar o segundo esconderia
    o erro atrás de uma timeline arrumada; o certo é manter o clipe em que se confia
    e RE-MEDIR o outro dentro do espaço que sobrou — a mesma restrição física que a
    passada 2 do pareamento já usa, agora aplicada onde ela faltava.

    ## ⚠️ A correção é no OFFSET, nunca na posição

    `_place_on_timeline` translada cada ilha rigidamente, então dentro dela a
    posição é função exclusiva dos `offset_frames`. Mexer em `timeline_start` aqui
    desincronizaria o clipe do próprio som e faria o `.prproj` sair com
    `timeline_start_frames` mentindo em relação a `sync_offset_frames`.
    """
    restantes = MAX_OVERLAP_REMEASURES
    conflitos = 0

    for clips, snds in _build_islands(groups, order):
        if len(clips) < 2 or not snds:
            continue

        # A semente é o clipe de maior confiança: assim a régua da ilha não depende
        # de quem vai ser corrigido daqui a pouco.
        semente = min(clips, key=lambda c: _prioridade_de_ancora(c, 0, None))
        rel = _relative_positions(clips, snds, seed=semente)

        por_camera: dict[str, list[_Clip]] = {}
        for c in clips:
            if c.sound is not None and c in rel and c.sound in rel:
                por_camera.setdefault(c.group_id, []).append(c)

        for gid, da_camera in por_camera.items():
            if len(da_camera) < 2:
                continue

            deltas = [c.implied_delta for c in da_camera
                      if c.implied_delta is not None and c.confidence >= TRUST_RATIO]
            delta_tipico = sorted(deltas)[len(deltas) // 2] if deltas else None

            ordem_no_grupo = {c: i for i, c in enumerate(groups[gid])}
            def prio(c: _Clip) -> tuple:
                return _prioridade_de_ancora(c, ordem_no_grupo.get(c, 0), delta_tipico)

            # 1. Quem fica: os melhores primeiro, aceitos enquanto couberem.
            aceitos: list[tuple[int, int]] = []
            congelados: list[_Clip] = []
            perdedores: list[_Clip] = []
            for c in sorted(da_camera, key=prio):
                ini, fim = rel[c], rel[c] + c.duration_frames
                if any(ini < f and i < fim for i, f in aceitos):
                    perdedores.append(c)
                else:
                    aceitos.append((ini, fim))
                    congelados.append(c)

            if not perdedores:
                continue
            conflitos += len(perdedores)

            # 2. Cada perdedor é recolocado no vão que sobrou — medindo, se der.
            for c in sorted(perdedores, key=lambda x: rel[x]):
                vao = _espaco_livre(rel[c], c.duration_frames, aceitos)
                if vao is None:
                    # Nem encaixe é possível: a timeline não tem como mentir menos
                    # que isto. Sinaliza e deixa onde está.
                    c.flagged, c.flag_reason = True, "overlap_unresolved"
                    _emit_clip(on_clip, c, fps)
                    continue
                lo, hi, alvo = vao
                s = c.sound

                # ⚠️ O vão pode ser ABERTO (±infinito) — é o espaço antes do
                # primeiro clipe e depois do último. Para virar janela de busca ele
                # precisa ser fechado, e quem o fecha é o próprio som: o clipe tem
                # de caber DENTRO dele. Sem esta interseção, `(-inf + inf)` vira
                # NaN e a re-medição estoura — apareceu no material real, não em
                # teste sintético.
                # O clipe precisa CRUZAR o som, não caber inteiro dentro dele: a
                # câmera pode continuar rodando depois de o gravador parar, e o sync
                # daquele trecho continua válido. Exigir contenção total descartava
                # a re-medição em 43 de 44 conflitos no material real — o mesmo erro
                # de premissa que o ZNCC já tinha cometido (ver [[takes-model]]).
                # `_measure_window` grampeia a janela ao som e devolve `None` se não
                # sobrar sinal, então basta haver interseção.
                dur_som = math.ceil(s.duration_s * fps)
                lo_busca = max(lo, float(rel[s] - c.duration_frames))
                hi_busca = min(hi, float(rel[s] + dur_som))

                pode_remedir = (
                    not c.pinned
                    and c.syncable[0]
                    and sync_method != "timecode"
                    and restantes > 0
                    and hi_busca >= lo_busca
                )
                medido = None
                if pode_remedir:
                    restantes -= 1
                    emit(f"Reconferindo {c.path.name} (sobreposto na mesma câmera)...",
                         0, 0)
                    # `near`/`half` aqui NÃO são uma previsão frouxa (o que o aviso
                    # de `_measure_window` proíbe): são o vão FÍSICO onde o clipe
                    # cabe, expresso como centro e metade.
                    centro_off = int((lo_busca + hi_busca) // 2) - rel[s]
                    metade = int((hi_busca - lo_busca) // 2) + 1
                    medido = _measure_window(c, s, fps,
                                             near_frames=centro_off,
                                             half_frames=metade)

                if medido is not None and medido[1] >= FLAG_RATIO:
                    offset, ratio = medido
                    novo_rel = int(min(max(rel[s] + offset, lo), hi))  # o vão é lei
                    c.offset_frames = novo_rel - rel[s]
                    c.confidence = ratio
                    c.sync_source = "waveform"
                else:
                    # Sem como medir, ou a medição não convenceu: vai para o ponto
                    # LEGAL MAIS PRÓXIMO do que a correlação tinha achado, e
                    # SINALIZA. Nunca inventa uma posição fora do vão, e mente o
                    # mínimo possível sobre a medição que existia.
                    c.offset_frames = alvo - rel[s]
                    c.flagged, c.flag_reason = True, "overlap_pushed"

                rel[c] = rel[s] + c.offset_frames
                aceitos.append((rel[c], rel[c] + c.duration_frames))
                _emit_clip(on_clip, c, fps)

    if conflitos:
        emit(f"{conflitos} clipe(s) estavam por cima de outro da mesma câmera.", 0, 0)


# ── Posições na timeline ─────────────────────────────────────────────────────


def _build_islands(
    groups: dict[str, list["_Clip"]],
    order: list[str],
) -> list[tuple[list["_Clip"], list["_Sound"]]]:
    """
    As ILHAS do grafo clipe ↔ som: cada componente conexa é um conjunto de clipes
    cujas posições relativas o sync já determina entre si.

    Um clipe e o som dele estão na mesma ilha; dois clipes que casaram com o MESMO
    som também. Um clipe sem som é uma ilha de um elemento só.

    ⚠️ A consequência que importa: num material com um WAV longo, dezenas de clipes
    — inclusive vários da MESMA câmera — caem numa ilha só. Ver
    `_resolve_source_overlaps`, que existe por causa disso.
    """
    all_clips = [c for gid in order for c in groups[gid]]
    islands: list[tuple[list[_Clip], list[_Sound]]] = []
    seen: set[_Clip] = set()

    for c0 in all_clips:
        if c0 in seen:
            continue
        clips: list[_Clip] = []
        snds: list[_Sound] = []
        stack = [c0]
        while stack:
            c = stack.pop()
            if c in seen:
                continue
            seen.add(c)
            clips.append(c)
            s = c.sound
            if s is not None and s not in snds:
                snds.append(s)
                stack.extend(x for x in s.clips if x not in seen)
        islands.append((clips, snds))

    return islands


def _relative_positions(
    clips: list["_Clip"],
    snds: list["_Sound"],
    seed: "_Clip | None" = None,
) -> dict:
    """
    Onde cada clipe e cada som da ilha ficam UM EM RELAÇÃO AO OUTRO, propagando os
    `offset_frames` medidos. A origem é arbitrária: a ilha inteira é depois
    transladada rigidamente (por TC ou pelo cursor), então o `seed` só decide de
    onde a contagem parte, nunca o resultado.

    Ponto fixo: um som herda a posição de qualquer clipe seu já conhecido, e um
    clipe herda a do seu som. Repete até nada mudar.
    """
    if not clips:
        return {}
    rel: dict = {seed if seed is not None else clips[0]: 0}
    changed = True
    while changed:
        changed = False
        for s in snds:
            if s in rel:
                continue
            anchor = next((c for c in s.clips if c in rel), None)
            if anchor is not None:
                rel[s] = rel[anchor] - anchor.offset_frames
                changed = True
        for c in clips:
            if c in rel or c.sound is None or c.sound not in rel:
                continue
            rel[c] = rel[c.sound] + c.offset_frames
            changed = True
    return rel


def _place_on_timeline(
    groups: dict[str, list[_Clip]],
    order: list[str],
    sounds: list[_Sound],
    fps: float,
) -> None:
    """
    Onde cada arquivo cai na timeline.

    A regra, na ordem de autoridade:

    1. DENTRO de uma ilha do grafo clipe ↔ som ↔ clipe, mandam os OFFSETS DE SYNC.
       Eles são a única coisa que foi MEDIDA contra o áudio de verdade.

    2. ENTRE ilhas, manda o TIMECODE de uma câmera de referência. Numa diária cada
       tomada é uma ilha (o som de uma tomada não tem relação nenhuma com o da
       outra), e o relógio da câmera é o que diz onde cada uma cai no dia — com os
       buracos reais entre elas, como num NLE.

    Por que nesta ordem, e não o contrário
    ──────────────────────────────────────
    O timecode de uma câmera pode não ser um relógio de parede. A câmera do
    dataset antigo grava em REC-RUN: o TC só avança enquanto ela grava, então os
    buracos entre os clipes simplesmente não existem nele. Posicionar por TC ali
    dá 51 s de intervalo onde a realidade (e a waveform) diz 166 s.

    Deixando o sync mandar dentro da ilha, isso deixa de importar: naquele dataset
    tudo compartilha um único som direto, o grafo é uma ilha só, e o TC vira apenas
    um deslocamento global — que a normalização da origem come. Já numa diária, em
    que as ilhas são independentes, o TC é indispensável e (por ser free-run) é
    confiável. Cada regime usa o que ele tem de bom.

    Sobras (clipe sem som — a câmera rodou antes do gravador, ou é um plano MOS):
    o clipe é uma ilha de um elemento só, ancorada pelo próprio TC.
    """
    islands = _build_islands(groups, order)

    # ── Posições RELATIVAS dentro de cada ilha, a partir dos offsets ─────────
    for clips, snds in islands:
        rel = _relative_positions(clips, snds)
        for c in clips:
            c.timeline_start = rel.get(c, 0)
        for s in snds:
            s.timeline_start = rel.get(s, 0)
            s.placed = True

    # ── Ancorar cada ilha no dia, pelo relógio da câmera de referência ───────
    ref_gid = max(
        (gid for gid in order if _tc_usable(groups[gid])),
        key=lambda g: len(groups[g]),
        default=None,
    )

    # ⭐⭐ O SOM MANDA NO RELÓGIO DA DIÁRIA, QUANDO ELE SABE AS HORAS.
    #
    # ⛔ O DEFEITO (relatado pelo autor em 2026-08-22, D03 de `PROJETO EXEMPLO`): os
    # áudios tinham TC a partir de 15h44 e caíam no COMEÇO da timeline. Medido, a
    # causa era haver DOIS RELÓGIOS na mesma sequência:
    #
    #   câmera `a005_C001`   TC 00:50:33  → posicionada em 24:51:59  (+24 h)
    #   som da mesma tomada  TC 15:54:47  → herdou a posição da CÂMERA
    #   som órfão FOLLY-T001 TC 15:45:08  → posicionado no PRÓPRIO TC
    #
    # As ilhas eram ancoradas pelo TC da CÂMERA e os sons sem câmera pelo TC DELES.
    # Quando os dois aparelhos não compartilham relógio — que é o caso comum, a
    # câmera em rec-run começando perto do zero e o gravador em hora-do-dia —, as
    # duas metades da timeline ficam a horas de distância uma da outra.
    #
    # ⭐ O gravador é quem tem RELÓGIO DE PAREDE. A câmera pode estar em rec-run
    # (o TC só anda enquanto ela grava, então nem descreve o dia) ou simplesmente
    # zerada. O autor comparou com o `autosequence` do Media Composer, que põe cada
    # arquivo no TC dele: é essa a leitura que o editor espera, e é a do som.
    #
    # ⚠️ Sem som com TC na ilha, o TC da câmera segue valendo — ele é o que resta,
    # e continua sendo melhor que emendar. Nada aqui muda para o material antigo em
    # que tudo compartilha um único som direto: lá a diária é UMA ilha, e ancorar
    # pelo som ou pela câmera difere por um deslocamento global, que a normalização
    # da origem come.
    # ⭐ O TRADUTOR ENTRE OS DOIS RELÓGIOS. Uma ilha SÓ DE CÂMERA (clipe que não
    # achou som) não tem como se ancorar no relógio do gravador sozinha — o TC dela
    # é de outro aparelho. Mas os clipes que SINCRONIZARAM já mediram a distância
    # entre os dois relógios (`implied_delta`), e é ela que traduz.
    #
    # ⚠️ E o Δ vale por VIZINHANÇA, não para o dia inteiro: ele muda quando alguém
    # reinicia um aparelho. Mesma régua e mesmo alcance de `_corroborate_by_delta`
    # — sem âncora por perto, não há tradução, e aí vale a regra do autor: emendar
    # na ordem (ver `tests/test_orfaos_em_ordem.py`).
    deltas = sorted(
        (c.tc_abs_sec, c.implied_delta)
        for grp in groups.values() for c in grp
        if c.sound is not None
        and c.implied_delta is not None
        and c.tc_abs_sec is not None
        and c.confidence >= TRUST_RATIO       # só quem MEDIU bem serve de tradutor
    )

    def _delta_para(c: "_Clip") -> float | None:
        """O Δ de relógio que vale na vizinhança deste clipe, ou `None`."""
        if c.tc_abs_sec is None or not deltas:
            return None
        perto = [d for t, d in deltas if abs(t - c.tc_abs_sec) <= ANCHOR_REACH_S]
        return float(np.median(perto)) if perto else None

    cursor = 0
    for clips, snds in islands:
        ancora_som = next((s for s in snds if s.tc_abs_sec is not None), None)

        # Ilha só de câmera: traduzir o TC dela para o relógio do som, se der.
        traduzido = None
        if ancora_som is None:
            for c in clips:
                d = _delta_para(c)
                if d is not None:
                    traduzido = round((c.tc_abs_sec + d) * fps) - c.timeline_start
                    break

        anchor = None
        if ancora_som is None and traduzido is None and not deltas:
            # Nenhum relógio de som na diária INTEIRA: o TC da câmera é o que há,
            # e continua valendo. É o material antigo, em que a câmera é a única
            # que sabe as horas.
            if ref_gid is not None:
                anchor = next((c for c in clips
                               if c.group_id == ref_gid and c.tc_abs_frames is not None), None)
            if anchor is None:
                anchor = next((c for c in clips if c.tc_abs_frames is not None
                               and _tc_usable(groups[c.group_id])), None)

        if ancora_som is not None:
            shift = round(ancora_som.tc_abs_sec * fps) - ancora_som.timeline_start
        elif traduzido is not None:
            shift = traduzido
        elif anchor is not None:
            shift = anchor.tc_abs_frames - anchor.timeline_start
        else:
            # Ilha sem relógio nenhum: emendada depois da última. Não há
            # informação para espalhá-la, e inventar um buraco seria mentir.
            #
            # ⚠️ O `cursor` é o fim do que já foi posicionado NA ORDEM EM QUE AS
            # ILHAS SÃO PERCORRIDAS, que não é a ordem da câmera. Ele serve de
            # ponto de partida, mas quem manda de verdade é `_encostar_sem_relogio`
            # logo abaixo: a regra do autor é "o C cola no B", e o B é o vizinho
            # DAQUELA CÂMERA — não o último elemento posicionado no dia.
            shift = cursor - min(c.timeline_start for c in clips)
            for c in clips:
                c.sem_relogio = True

        for c in clips:
            c.timeline_start += shift
        for s in snds:
            s.timeline_start += shift

        cursor = max(cursor,
                     max(c.timeline_start + c.duration_frames for c in clips))

    # ── Sons SEM câmera nenhuma: posicionados pelo próprio TC ────────────────
    #
    # Um som que não pareou com câmera (o relógio do gravador está horas distante
    # do da câmera, como na D02 do PROJETO X) não entra em ilha nenhuma e ficaria
    # de fora. Mas o arquivo EXISTE e tem lugar no dia — é o que o Premiere mostra.
    # Ancora pelo próprio TC; sem TC, emenda depois do último (não há como
    # espalhá-lo, e inventar um buraco seria mentir).
    for s in sounds:
        if s.placed:
            continue
        dur_frames = math.ceil(s.duration_s * fps)
        if s.tc_abs_sec is not None:
            s.timeline_start = round(s.tc_abs_sec * fps)
        else:
            s.timeline_start = cursor
        s.placed = True
        cursor = max(cursor, s.timeline_start + dur_frames)

    # ── Clipe sem relógio ENCOSTA NO VIZINHO DA PRÓPRIA CÂMERA ──────────────
    _encostar_sem_relogio(groups, order)

    # ── Nenhum clipe da MESMA câmera (nem dois sons) se sobrepõe ─────────────
    _resolve_track_overlaps(islands, [s for s in sounds if not s.clips], fps)


def _encostar_sem_relogio(groups: dict[str, list["_Clip"]], order: list[str]) -> None:
    """Um clipe sem relógio cola no VIZINHO ANTERIOR DA MESMA CÂMERA.

    ⭐ A regra, ditada pelo autor em 2026-08-22 (editor):

        "A B C D E: se A B e D E sincronizaram e o C não, e não houver TC para
        presumir a distância entre B e D, o C fica colado no B. O mesmo se C e D
        não acharem sync mas B e E acharem: o C vai colado após o B e o D colado
        após o C. Assim todos os clipes ficam na ordem, e o editor faz uma revisão
        pontual sabendo que o clipe só pode existir dentro de um espaço de tempo —
        os clipes anteriores e posteriores que acharam sync."

    ⚠️ POR QUE NÃO BASTA O `cursor` do laço de ilhas: ele é o fim do que já foi
    posicionado NA ORDEM DAS ILHAS, que não é a ordem da câmera. Medido na D03 de
    `PROJETO EXEMPLO` (2026-08-22): os 11 clipes dos cartões a006/a007 emendavam
    corretamente ENTRE SI, mas a cadeia inteira começava em 08:16 numa diária que
    termina em 03:52 — um buraco de 4h23 que ninguém pediu, porque o cursor vinha
    adiantado de outra ilha.

    ⭐ "Colado no B" é uma afirmação sobre a CÂMERA, não sobre o dia. Por isso a
    conta se faz percorrendo cada fonte na sua própria ordem.

    Quem tem relógio (som, ou TC traduzido) não é tocado: a distância medida é
    melhor que a colagem, e a colagem é o piso.
    """
    for gid in order:
        clips = groups.get(gid) or []
        if not clips:
            continue
        # A ordem da CÂMERA: `group_order` quando o painel a informa (é o que o
        # arrasto e a leitura de bin mandam), com o TC de desempate.
        na_ordem = sorted(
            clips,
            key=lambda c: (c.group_order if c.group_order is not None else 0,
                           c.tc_abs_sec if c.tc_abs_sec is not None else 0.0),
        )
        anterior = None
        for c in na_ordem:
            if c.sem_relogio and anterior is not None:
                c.timeline_start = anterior.timeline_start + anterior.duration_frames
            anterior = c


# Track "virtual" de todo som direto — dois sons também não podem se sobrepor.
#: Fallback da track de som, para um som que não sabe de que fonte veio.
#:
#: ⚠️ A track do som é POR GRAVADOR, e não uma só: dois gravadores PODEM rodar ao
#: mesmo tempo (um no boom, outro em lapelas), e nesse caso a sobreposição entre
#: eles é real — empurrar um para depois do outro inventaria uma distância que não
#: existe. Só dois sons do MESMO gravador é que não podem coexistir.
_SOUND_TRACK = "__sound__"


def _resolve_track_overlaps(
    islands: list[tuple[list["_Clip"], list["_Sound"]]],
    orphan_snds: list["_Sound"],
    fps: float,
) -> None:
    """
    Empurra as UNIDADES (tomadas e sons órfãos) para a frente até nenhum clipe da
    MESMA câmera — nem dois sons — se sobrepor. Uma câmera não grava dois arquivos
    ao mesmo tempo, e o gravador não grava dois sons ao mesmo tempo: na timeline
    isso vira uma track só, e uma track não tem dois clipes no mesmo instante.

    Move a UNIDADE INTEIRA (os clipes E o som da tomada, pelo mesmo Δ), então o sync
    interno se preserva — é a mesma razão de `_place_on_timeline` posicionar por
    ilha. Só empurra para a FRENTE, e só o mínimo: uma tomada que já cabe não se mexe.

    ⚠️ O QUE ESTÁ OCUPADO É UMA LISTA DE INTERVALOS, NÃO UM ÚLTIMO FIM.
    Guardar só o fim máximo de cada track parece equivalente e não é: uma tomada
    longa deixa BURACOS entre os seus clipes, e uma unidade que caberia num deles
    era empurrada para além da tomada inteira. Medido no material real da BOLIVIA:
    `A002_A041` (3,5 s, órfão por ser curto demais para sincronizar) cabia entre
    `A040` e `A042` e ia parar 53 minutos à frente. Ver `test_engine_overlap.py`.

    ⭐ QUANDO OS DOIS CLIPES TÊM TC, O TC VENCE (decisão do autor, 2026-10-21).
    Um clipe em câmera lenta dura mais (tempo de arquivo) do que o seu intervalo de
    cena, e INVADE legitimamente o TC da tomada seguinte da mesma câmera — medido no
    caso M05 do laboratório: empurrado, o 2º clipe ia 10 s para fora do próprio TC. Então
    um conflito SÓ entre clipes de câmera com TC não empurra: o seguinte fica no TC dele
    (por cima), e o de antes é MARCADO (`overlap_cut`) para o editor revisar o corte.
    A detecção de slow pelos metadados fica de fora (o fps de captura nem sempre vem
    no arquivo). Sem TC, ou com som no conflito, continua o empurrão: aí a posição pode
    ser erro de sync, e um gravador não grava dois sons ao mesmo tempo.
    """
    def sound_end(s: "_Sound") -> int:
        return s.timeline_start + math.ceil(s.duration_s * fps)

    # Uma unidade = uma ilha (clipes+som) ou um som órfão sozinho.
    units = [(clips, snds) for clips, snds in islands]
    units += [([], [s]) for s in orphan_snds]

    def unit_start(u):
        clips, snds = u
        return min([c.timeline_start for c in clips]
                   + [s.timeline_start for s in snds])

    units.sort(key=unit_start)

    # track → intervalos [início, fim) já ocupados nela, em ordem.
    occupied: dict[str, list[tuple[int, int]]] = {}

    for clips, snds in units:
        intervals = [
            (c.group_id, c.timeline_start, c.timeline_start + c.duration_frames, c)
            for c in clips
        ]
        intervals += [
            (s.group_id or _SOUND_TRACK, s.timeline_start, sound_end(s), None) for s in snds
        ]

        shift = _min_forward_shift(intervals, occupied)

        if shift:
            for c in clips:
                c.timeline_start += shift
            for s in snds:
                s.timeline_start += shift

        for _key, start, end, dono in intervals:
            for o_start, o_end, o_dono in occupied.get(_key, ()):
                if _tc_vence(dono, o_dono) and start + shift < o_end and o_start < end + shift:
                    # ⚠️ por CIMA de outra marca: o clipe lento chega marcado `no_audio`
                    # (câmera de alta velocidade não grava som), e "cortado pela tomada
                    # seguinte" é o que o editor precisa ir conferir (M05, 2026-10-21)
                    o_dono.flagged, o_dono.flag_reason = True, "overlap_cut"
        for key, start, end, dono in intervals:
            occupied.setdefault(key, []).append((start + shift, end + shift, dono))


def _tc_vence(a, b) -> bool:
    """Dois clipes de câmera COM TC: o conflito entre eles não empurra (ver acima)."""
    return (a is not None and b is not None
            and getattr(a, "tc_sec", None) is not None
            and getattr(b, "tc_sec", None) is not None)


def _min_forward_shift(
    intervals: list[tuple],
    occupied: dict[str, list[tuple]],
) -> int:
    """O MENOR deslocamento para a frente que tira esta unidade de cima de tudo.

    Zero quando ela já cabe — inclusive dentro de um buraco no meio do que já está
    posicionado, que é o caso que o "último fim" errava.

    Repete até estabilizar porque um empurrão pode criar uma colisão nova mais à
    frente (na mesma track ou em outra da unidade). Termina sempre: o deslocamento
    só CRESCE, e os candidatos são os fins de uma lista finita de intervalos.
    """
    shift = 0
    while True:
        needed = shift
        for key, start, end, *dono in intervals:
            dono = dono[0] if dono else None
            for occ_start, occ_end, *occ_dono in occupied.get(key, ()):
                if _tc_vence(dono, occ_dono[0] if occ_dono else None):
                    continue   # o TC vence: sobrepõe e marca, não empurra
                # [a,b) e [c,d) se cruzam quando a < d e c < b.
                if start + shift < occ_end and occ_start < end + shift:
                    needed = max(needed, occ_end - start)
        if needed == shift:
            return shift
        shift = needed


# ── Materialização ───────────────────────────────────────────────────────────


def _build_daily(
    groups: dict[str, list[_Clip]],
    order: list[str],
    names: dict[str, str],
    sounds: list[_Sound],
    all_clips: list[_Clip],
    fps: float,
    project_name: str,
    start_tc_frames: int,
) -> Daily:
    tpf = _ticks_per_frame(fps)
    angle_of: dict[_Clip, CameraAngle] = {}

    camera_groups: list[CameraGroup] = []
    for gid in order:
        angles = []
        for c in groups[gid]:
            angle = CameraAngle(
                path=c.path,
                fps=fps,
                duration_frames=c.duration_frames,
                timeline_start_frames=c.timeline_start,
                sync_offset_frames=c.offset_frames,
                # ⚠️ CRU, e nunca desdobrado. Este é o TC DE ORIGEM DO ARQUIVO — o que
                # o NLE exibe no clipe (`<AlternateStart>` no PRPROJ). Um TC
                # desdobrado viraria `24:01:52:11`, que não existe em lugar nenhum.
                # O eixo desdobrado (`tc_abs_*`) já cumpriu o papel dele lá em cima,
                # em `timeline_start_frames`. Ver `sync/daycycle.py`.
                tc_start_frames=c.tc_frames,
                alternate_start_ticks=None if c.tc_frames is None else c.tc_frames * tpf,
                # TOTAL de canais (soma de todos os streams) — o plugin de NLE reserva
                # as tracks de áudio por isto. Fallback ao 1º stream / 2.
                audio_channels=int(
                    c.meta.get("total_audio_channels") or c.meta.get("channels") or 2
                ),
                flagged=c.flagged,
                flag_reason=c.flag_reason,
                confidence=c.confidence,
                sync_source=c.sync_source,
            )
            angle_of[c] = angle
            angles.append(angle)
        camera_groups.append(CameraGroup(cameras=angles, name=names[gid], id=gid))

    def _sound_clip(s: _Sound) -> SoundClip:
        return SoundClip(
            path=s.path,
            sample_rate=int(s.meta.get("sample_rate") or 48000),
            duration_ms=float(s.meta.get("duration_ms") or 0.0),
            channels=int(s.meta.get("channels") or 2),
            timeline_start_frames=s.timeline_start,
            tc_start_sec=s.tc_sec,
            scene=s.meta.get("scene"),
            take=s.meta.get("take"),
        )

    takes: list[Take] = []
    orphan_sounds: list[SoundClip] = []
    for s in sounds:
        if s.clips:
            takes.append(Take(
                sound=_sound_clip(s),
                cameras=[angle_of[c] for c in s.clips],
            ))
        else:
            # Som sem câmera: não vira tomada, mas NÃO some — vai posicionado pelo
            # próprio TC (ver `_place_on_timeline`). É o que faz o app mostrar o
            # mesmo que o Premiere quando o relógio do gravador destoa do da câmera.
            orphan_sounds.append(_sound_clip(s))

    orphans = [angle_of[c] for c in all_clips if c.sound is None]

    daily = Daily(
        camera_groups=camera_groups,
        takes=takes,
        orphan_cameras=orphans,
        orphan_sounds=orphan_sounds,
        fps=fps,
        name=project_name,
        start_tc_frames=start_tc_frames,
    )
    daily.normalize_origin()
    return daily


def _emit_clip(on_clip, c: _Clip, fps: float) -> None:
    """
    Manda o estado atual de um clipe para a timeline (upsert por path).

    A posição vai como o TIMECODE do clipe — a posição definitiva só existe no
    fim, depois de o grafo de sync ser resolvido e a origem normalizada. Para o
    preenchimento ao vivo isso basta e é honesto: o TC é onde o clipe cai no dia, e
    é onde ele vai ficar.
    """
    if not on_clip:
        return
    on_clip({
        "group_id": c.group_id,
        "group_name": c.group_name,
        "path": str(c.path),
        "name": c.path.name,
        "fps": fps,
        "duration_frames": c.duration_frames,
        "timeline_start_frames": c.tc_abs_frames or 0,
        "sync_offset_frames": c.offset_frames,
        "sound_path": str(c.sound.path) if c.sound else None,
        "flagged": c.flagged,
        "flag_reason": c.flag_reason,
        "confidence": c.confidence,
        "sync_source": c.sync_source,
        "peak_rate": PEAK_RATE,
        "peaks": c.peaks,
    })


def _emit_sound(on_sound, s: "_Sound", anchor: _Clip, fps: float) -> None:
    """Manda um som para a timeline, pendurado no clipe que o ancora."""
    if not on_sound or s.peaks is None:
        return
    on_sound({
        "path": str(s.path),
        "name": s.path.name,
        "fps": fps,
        "duration_ms": s.meta.get("duration_ms") or 0.0,
        "timeline_start_frames": (anchor.tc_abs_frames or 0) - anchor.offset_frames,
        "channels": int(s.meta.get("channels") or 2),
        "peak_rate": PEAK_RATE,
        "peaks": s.peaks,
    })
