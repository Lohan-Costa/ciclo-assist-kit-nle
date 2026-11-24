"""
Sincronizar — Media Inspector
Extrai metadados técnicos de arquivos de vídeo e áudio.

Timecode — onde ele REALMENTE mora (custou um bug, 2026-07-12):

  Vídeo (.mp4/.mov): NÃO está no track General. Está num track separado, que o
  MediaInfo reporta como `track_type == "Other"` (é o tmcd do QuickTime).
  Procurar só no General fazia o app achar que material com TC não tinha TC — e,
  sem TC, a timeline não tinha como distribuir os clipes ao longo do dia.

  WAV (BWF): o MediaInfo NÃO expõe o `time_reference` do chunk bext (só admite
  que ele existe, em `delay__origin`). Quem lê é o ffprobe. `time_reference` é a
  contagem de AMOSTRAS desde a meia-noite — a origem do TC do gravador.

  MXF OP-Atom (mídia do Avid, e o que o Resolve exporta para ele): o MediaInfo
  responde, e responde ERRADO — custou um bug, 2026-08-14. Ele devolve o timecode
  de SISTEMA do MXF: uma faixa sintética de 120 h (`00:00:00:00` →
  `119:59:59:23`) que existe em todo arquivo e não descreve nenhum. Era um
  `00:00:00:00` que passava em qualquer checagem de "tem TC", e por isso a diária
  inteira empilhava no mesmo instante da timeline. O TC de FONTE está nas tags de
  STREAM do ffprobe (`TAG:timecode`) — ver `_ffprobe_stream_timecode` e
  `_tc_track_e_do_clipe`.

Gravadores de som também escrevem CENA e TOMADA nos metadados do BWF
(`SCENE`, `TAKE`), que é como o material se organiza de verdade numa diária.
"""

from __future__ import annotations

import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from . import fftools, safepath, nameconv


def _parse_encoded_date(raw: str | None) -> str | None:
    """
    Converte o 'encoded_date' do MediaInfo (data/hora real de gravação, gravada
    pela própria câmera no container QuickTime — não confundir com datas do
    sistema de arquivos, que mudam ao copiar) para ISO 8601 comparável.

    Formatos observados: 'YYYY-MM-DD HH:MM:SS UTC' ou 'YYYY-MM-DD HH:MM:SS'.
    Retorna None se ausente ou não reconhecido.
    """
    if not raw:
        return None
    raw = raw.strip()
    for fmt, tz in (("%Y-%m-%d %H:%M:%S UTC", timezone.utc), ("%Y-%m-%d %H:%M:%S", None)):
        try:
            dt = datetime.strptime(raw, fmt)
            if tz is not None:
                dt = dt.replace(tzinfo=tz)
            return dt.isoformat()
        except ValueError:
            continue
    return None


def _ffprobe_tags_text(path: str) -> str:
    """
    Tags de formato via ffprobe, como TEXTO CRU — de propósito, não como JSON.

    Gravadores de som emitem MAIS DE UMA tag `comment` (o ZOOM F8 manda um blob
    `CHAVE=valor` e depois uma nota livre). Em JSON as chaves repetidas colapsam
    e a última vence, o que apagava justamente o blob com SCENE/TAKE. No texto
    cru as duas sobrevivem.

    Vazio se o ffprobe não estiver disponível — o app segue, só sem o TC do WAV.
    """
    exe = fftools.ffprobe()
    if not exe:
        return ""
    try:
        return subprocess.run(
            # `file:` FIXA o protocolo (nada de http://) e garante que a string
            # nunca comece com `-`, que o ffprobe leria como OPÇÃO. Ver media/safepath.
            [exe, "-v", "error", "-show_entries", "format_tags", "-of", "default",
             safepath.ff_input(path)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30, check=True,
        ).stdout
    except Exception:
        return ""


#: Quanto o TC track pode exceder a duração do clipe antes de ser descartado.
#: Um TC track legítimo cobre exatamente o clipe — medido, `frame_count` bate
#: 1,00× em .mov, .mp4 e MXF XDCAM. O timecode de sistema do OP-Atom bate 4371×
#: (10.368.000 frames de faixa contra os 2.372 do clipe). Entre 1× e 4371× cabe
#: qualquer folga; 2× é generoso com o caso legítimo e ainda três ordens de
#: grandeza abaixo do erro que se quer pegar.
_TC_TRACK_FOLGA = 2.0

#: `HH:MM:SS:FF`, com `;` marcando drop-frame. Duas casas na hora, porque timecode
#: conta de `00` a `23`.
#:
#: ⚠️ Já admitiu TRÊS casas, e era um tiro no pé: o único valor de 3 dígitos que se
#: conhece é `119:59:59:23`, justamente o fim da faixa sintética que este módulo
#: existe para rejeitar. E ele vem do `time_code_of_last_frame` do MediaInfo, que
#: nunca passa por aqui — esta regex só olha a saída do ffprobe. Aceitá-lo deixaria
#: um clipe pousar a cinco dias de distância na timeline, carimbado com a
#: procedência mais confiável (`ffprobe-stream`), o que é pior que o bug original:
#: `tc_to_real_seconds` valida minuto, segundo e frame, mas NÃO a hora.
_TC_RE = re.compile(r"^\d{2}:\d{2}:\d{2}[:;]\d{2}$")


def _primeiro_int(v) -> int | None:
    """Primeiro inteiro de um campo do MediaInfo.

    O `frame_count` chega como `int` num arquivo de vídeo e como a string
    `"10368000 / 5664000"` num de áudio (o MediaInfo junta os valores das duas
    contagens do track). Pegar o primeiro número cobre as duas formas.
    """
    if isinstance(v, int):
        return v
    m = re.search(r"\d+", str(v or ""))
    return int(m.group()) if m else None


def _tc_track_e_do_clipe(tc_track, clip_frames: float | None) -> bool:
    """Este TC track descreve o clipe, ou é a faixa sintética do MXF?

    A distinção não dá para fazer olhando o VALOR do TC: `00:00:00:00` é um
    timecode perfeitamente legítimo (há material real começando nele). O que
    denuncia a faixa sintética é a EXTENSÃO — ela cobre 120 h num arquivo de 98 s.

    Sem `frame_count` ou sem duração não há o que comparar, e aí o track passa:
    na dúvida, o comportamento de sempre.
    """
    tc_frames = _primeiro_int(getattr(tc_track, "frame_count", None))
    if not tc_frames or not clip_frames:
        return True
    return tc_frames <= clip_frames * _TC_TRACK_FOLGA


def _ffprobe_stream_timecode(path: str) -> str | None:
    """O TC de FONTE, das tags de STREAM — a rota que funciona no MXF OP-Atom.

    ⚠️ Repare que NÃO é `format_tags`, que é tudo o que `_ffprobe_tags_text` pede:
    no OP-Atom o bloco de formato não tem `timecode` nenhum, o TC vive na stream
    de essência. (No XDCAM é o contrário — daí a consulta pedir os dois numa
    chamada só e ficar com o primeiro que vier.)

    Devolve a string CRUA, com o separador preservado: `;` é a marca de
    drop-frame, e quem chama depende dela.
    """
    exe = fftools.ffprobe()
    if not exe:
        return None
    try:
        saida = subprocess.run(
            [exe, "-v", "error", "-show_entries", "stream_tags=timecode:format_tags=timecode",
             "-of", "default=nw=1:nk=1", safepath.ff_input(path)],
            capture_output=True, encoding="utf-8", errors="replace", timeout=30, check=True,
        ).stdout
    except Exception:
        return None
    for linha in saida.splitlines():
        tc = linha.strip()
        if _TC_RE.match(tc):
            return tc
    return None


def _tc_rate(media_info) -> float | None:
    """A taxa em que o TC deste arquivo CONTA, do track de timecode.

    Necessária num arquivo só de áudio, que não tem frame rate própria para
    converter `HH:MM:SS:FF` em segundos. O MediaInfo expõe `framerate_num/den` no
    track de TC mesmo quando o resto dele é a faixa sintética inútil — é o único
    pedaço daquele track que se aproveita.
    """
    for t in media_info.tracks:
        if t.track_type != "Other":
            continue
        num = _primeiro_int(getattr(t, "framerate_num", None))
        den = _primeiro_int(getattr(t, "framerate_den", None))
        if num and den:
            return num / den
    return None


def _bwf_start_seconds(tags_text: str, sample_rate: int | None) -> float | None:
    """
    Início do WAV em segundos desde a meia-noite, do chunk bext do BWF.

    `time_reference` conta AMOSTRAS desde a meia-noite — é a origem do TC do
    gravador de som.
    """
    if not sample_rate:
        return None
    m = re.search(r"^TAG:time_reference=(\d+)\s*$", tags_text, re.MULTILINE)
    if not m:
        return None
    return int(m.group(1)) / float(sample_rate)


def _bwf_origination(tags_text: str) -> tuple[str | None, str | None]:
    """A DATA e a HORA REAIS de gravação, do chunk bext do BWF.

    `OriginationDate`/`OriginationTime` são escritos pelo gravador no instante da
    gravação e vivem DENTRO do arquivo — sobrevivem a cópia, a renomeação e a
    mudança de disco. É o metadado de data mais confiável do ecossistema, e o único
    que o material real tem (o vídeo chega transcodado, sem data nenhuma).

    ⚠️ A HORA DE PAREDE NÃO É O TIMECODE. Medido no material: parede 23:57:02 com
    TC 23:16:57 — ~40 min de distância, porque o TC vem de um jam sync e a parede
    do relógio interno. Serve para saber o DIA, não para posicionar.

    ⚠️ O `creation_time` daqui é HORA PURA (`23:57:02`). Em m4a/mp3 a mesma tag é
    um ISO completo, ou herdada do sistema de arquivos — e essa não vale nada para
    nós. Daí a regex exigir a forma inteira e ancorada: qualquer outra coisa vira
    `None`, que é a decisão "só metadado interno e confiável" virada em código.
    """
    d = re.search(r"^TAG:date=(\d{4}-\d{2}-\d{2})\s*$", tags_text, re.MULTILINE)
    t = re.search(r"^TAG:creation_time=(\d{2}:\d{2}:\d{2})\s*$", tags_text, re.MULTILINE)
    return (d.group(1) if d else None), (t.group(1) if t else None)


def _tape(tags_text: str) -> str | None:
    """O rótulo de DIÁRIA que o próprio sonoplasta digitou no gravador.

    Vem como `sTAPE=250516` dentro do blob `comment` (as mesmas linhas
    `CHAVE=valor` de `_scene_take`) e é o campo "tape/day" do relatório de som. É a
    melhor pista de NOME de diária que existe no material — mas é NOME, não
    fronteira: quem decide onde uma diária começa e termina é o buraco no eixo do
    tempo (ver `sync/dailysplit.py`).
    """
    m = re.search(r"^s?TAPE=(.*)$", tags_text, re.MULTILINE)
    if not m:
        return None
    return m.group(1).strip() or None


def _scene_take(tags_text: str) -> tuple[str | None, str | None]:
    """
    Cena e tomada, dos metadados que o gravador de som escreve no BWF.

    É a organização REAL de uma diária de ficção — o mesmo que está na claquete e
    no relatório de continuidade. Vem dentro do blob `comment` (linhas
    `CHAVE=valor`), não em tags próprias.
    """
    # ⚠️ O `s` opcional é o que faz isto funcionar com Sound Devices. O ZOOM F8
    # escreve `SCENE=`; o MixPre escreve `sSCENE=`. Só a primeira forma era lida, e
    # por isso a cena e a tomada do material real NUNCA chegaram ao app — o campo
    # existia no arquivo e voltava vazio. Mesma regra em `_tape`.
    scene = re.search(r"^s?SCENE=(.*)$", tags_text, re.MULTILINE)
    take = re.search(r"^s?TAKE=(.*)$", tags_text, re.MULTILINE)
    s = scene.group(1).strip() if scene else None
    t = take.group(1).strip() if take else None
    return (s or None), (t or None)


def _codec_label(vt) -> str | None:
    """Nome amigável do codec (ex.: 'ProRes 422 HQ', 'H.264', 'XDCAM 50')."""
    if vt is None:
        return None
    commercial = getattr(vt, "commercial_name", None) or getattr(vt, "format_commercial", None)
    if commercial:
        c = str(commercial).strip()
        if c.startswith("Apple "):
            c = c[len("Apple "):]
        if c.upper() == "XDCAM HD422":
            return "XDCAM 50"
        return c
    fmt  = getattr(vt, "format", None)
    prof = getattr(vt, "format_profile", None)
    if fmt:
        f = str(fmt).strip()
        fu = f.upper()
        if fu == "AVC":
            return "H.264"
        if fu == "HEVC":
            return "H.265"
        if "PRORES" in fu:
            return f"ProRes {prof}".strip() if prof else "ProRes"
        return f"{f} {prof}".strip() if prof else f
    return None


def probe(path: str) -> dict:
    """
    Extrai metadados de um arquivo de mídia via pymediainfo.

    Retorna dict com:
        path, filename, extension, size_bytes,
        fps, tc_start, duration_ms, width, height,
        codec_label, has_audio, sample_rate, sample_depth

    O resultado é CACHEADO em disco por (caminho, tamanho, mtime): numa diária de
    50 clipes, o primeiro sync lê todos, mas o re-sync parcial (que relê todos só
    para montar o contexto) fica instantâneo. Ver `media/probecache.py`.
    """
    from media import probecache

    cached = probecache.load(path)
    if cached is not None:
        return cached
    meta = _probe_uncached(path)
    probecache.store(path, meta)
    return meta


def _probe_uncached(path: str) -> dict:
    from pymediainfo import MediaInfo

    # ⚠️ MediaInfo BUSCA A REDE quando a string tem `://` (a libmediainfo embarcada
    # traz o Reader_libcurl). Sem esta validação, um caminho vindo de fora vira
    # requisição HTTP saindo da máquina do editor. Ver media/safepath.
    fp = safepath.ensure_local_file(path)

    # ⚠️ AQUI VAI O CAMINHO CRU, e NÃO o `ff_input()` — a diferença é medida:
    #     MediaInfo.parse("file:/Volumes/…")  → FileNotFoundError
    #     ffprobe          "file:/Volumes/…"  → OK
    # O prefixo `file:` é um protocolo do ffmpeg; o MediaInfo não o entende e trata
    # a string inteira como nome de arquivo. Usar o mesmo argumento nos dois quebrou
    # a leitura de metadados de TODA mídia (visto num sync real de 14 clipes, que é
    # onde isto aparece — nenhum teste unitário toca o MediaInfo de verdade).
    # A defesa contra SSRF aqui é o `ensure_local_file` acima, que recusa `://`;
    # o prefixo é a defesa do lado do ffmpeg, onde ele funciona.
    media_info = MediaInfo.parse(str(fp))

    video_track = next(
        (t for t in media_info.tracks if t.track_type == "Video"), None
    )
    audio_track = next(
        (t for t in media_info.tracks if t.track_type == "Audio"), None
    )
    general_track = next(
        (t for t in media_info.tracks if t.track_type == "General"), None
    )

    result: dict = {
        "path": str(fp),
        "filename": fp.name,
        "extension": fp.suffix.lower(),
        "has_audio": audio_track is not None,
        "recorded_at": _parse_encoded_date(getattr(general_track, "encoded_date", None)),
    }

    # A DATA QUE O NOME CARREGA. Não custa subprocesso nenhum, e é a única data que
    # sobra num arquivo de câmera transcodado — o `recorded_at` acima traz a data do
    # TRANSCODE nesses casos, e por isso segue sem consumidor. Ver `media/nameconv.py`.
    result["name_date"], result["name_time"], result["date_source"] = nameconv.parse_name_date(fp)
    result["folder_date"] = nameconv.parse_folder_date(fp)

    try:
        result["size_bytes"] = fp.stat().st_size
    except OSError:
        result["size_bytes"] = None

    if video_track:
        fps = float(video_track.frame_rate) if video_track.frame_rate else None
        duration_ms = float(video_track.duration) if video_track.duration else None

        # O TC do vídeo mora no track do TIMECODE (o tmcd), que o MediaInfo
        # reporta como "Other" — não no General. Ver o cabeçalho do módulo.
        tc_track = next(
            (t for t in media_info.tracks
             if t.track_type == "Other"
             and getattr(t, "time_code_of_first_frame", None)),
            None,
        )
        tc_start = getattr(tc_track, "time_code_of_first_frame", None)
        drop_frame = str(getattr(tc_track, "timecode_dropframe", "")).lower() == "yes"
        # DE ONDE veio o TC. Vai junto no resultado e para o log: um TC errado se
        # parece com um TC certo, e sem a procedência não há como ver a diferença
        # sem reproduzir a leitura à mão. Foi o que este bug custou.
        tc_source = "mediainfo" if tc_start else None

        # ⚠️ Ter achado um TC track não é ter achado o TC. No MXF OP-Atom o que se
        # acha é a faixa sintética do timecode de sistema, e o valor dela pode ser
        # `00:00:00:00` para TODO arquivo — um zero que passa em qualquer teste de
        # presença e empilha a diária inteira no mesmo ponto. Ver o cabeçalho.
        #
        # SUSPEITO, não descartado. Medido em dois acervos: a faixa é sempre
        # degenerada (115× a 8853× o clipe), mas onde ela COMEÇA varia com o
        # programa que escreveu a mídia — no OP-Atom DNx do Resolve ela começa no
        # zero e mente, no OP-Atom XDCAM do próprio Avid ela começa no TC de fonte
        # e acerta. Como não dá para saber qual é qual sem uma segunda opinião, o
        # valor fica de lado e só volta se o ffprobe não tiver nada melhor —
        # trocá-lo por `None` faria uma instalação sem ffprobe REGREDIR justamente
        # no material em que o MediaInfo estava certo.
        tc_suspeito = tc_drop_suspeito = None
        if tc_track is not None and not _tc_track_e_do_clipe(
            tc_track, (duration_ms / 1000.0 * fps) if (duration_ms and fps) else None
        ):
            tc_suspeito, tc_drop_suspeito = tc_start, drop_frame
            tc_start, drop_frame, tc_source = None, False, None

        if not tc_start and general_track:
            tc_start = (
                getattr(general_track, "time_code_of_first_frame", None)
                or getattr(general_track, "comapplequicktimetimecode", None)
            )
            tc_source = "mediainfo-general" if tc_start else None

        # Última rota, e a única que serve ao OP-Atom: o TC de fonte nas tags de
        # stream do ffprobe. Só custa um subprocesso quando o MediaInfo não
        # entregou nada aproveitável, então o material que já funcionava não paga
        # por isto (e o resultado ainda cai no cache de probe).
        if not tc_start:
            tc_start = _ffprobe_stream_timecode(str(fp))
            if tc_start:
                drop_frame = ";" in tc_start
                tc_source = "ffprobe-stream"

        # O suspeito de volta, por não haver nada melhor. Um TC que PODE estar
        # certo vale mais que nenhum — e `tc_source` deixa a incerteza no log em
        # vez de escondê-la atrás de um valor que parece igual aos outros.
        if not tc_start and tc_suspeito:
            tc_start, drop_frame = tc_suspeito, tc_drop_suspeito
            tc_source = "mediainfo-suspeito"

        result.update(
            {
                "fps": fps,
                "tc_start": tc_start,
                "tc_source": tc_source,
                "tc_drop_frame": drop_frame,
                "duration_ms": duration_ms,
                # A contagem REAL de frames. O `duration_ms` vem arredondado e,
                # convertido com `ceil`, dava um frame a mais (ver
                # `engine._duration_frames`).
                "frame_count": _primeiro_int(getattr(video_track, "frame_count", None)),
                "width": int(video_track.width) if video_track.width else None,
                "height": int(video_track.height) if video_track.height else None,
                "codec_label": _codec_label(video_track),
                # Subamostragem de croma ("4:2:0", "4:2:2", "4:4:4"). O monitor usa
                # isto para NÃO confiar no `<video>` do WebView com 4:4:4 (ProRes
                # 4444): o WKWebView do macOS "decodifica" mas renderiza quebrado
                # (só uma faixa no topo) — ali o proxy H.264 4:2:0 é obrigatório.
                "chroma_subsampling": (
                    str(video_track.chroma_subsampling)
                    if getattr(video_track, "chroma_subsampling", None)
                    else None
                ),
            }
        )
    else:
        # Arquivo de áudio puro: usa duração do general track
        if general_track and getattr(general_track, "duration", None):
            result["duration_ms"] = float(general_track.duration)

    if audio_track:
        sample_rate = (
            int(audio_track.sampling_rate) if audio_track.sampling_rate else None
        )
        result["sample_rate"] = sample_rate
        result["sample_depth"] = (
            int(audio_track.bit_depth) if getattr(audio_track, "bit_depth", None) else None
        )
        result["channels"] = (
            int(audio_track.channel_s) if getattr(audio_track, "channel_s", None) else None
        )
        # TOTAL de canais somando TODOS os streams de áudio — uma câmera pode ter
        # vários streams mono separados (ex.: PANA com 4 tracks mono), e o
        # `audio_track` acima é só o PRIMEIRO. O plugin de NLE precisa do total para
        # reservar as tracks de áudio certas ao montar a sequência.
        total_ch = 0
        for t in media_info.tracks:
            if t.track_type == "Audio" and getattr(t, "channel_s", None):
                try:
                    total_ch += int(t.channel_s)
                except (TypeError, ValueError):
                    pass
        result["total_audio_channels"] = total_ch or result["channels"] or 0

        # Só arquivos de áudio puro: num vídeo, o TC que vale é o do tmcd.
        if not video_track:
            tags = _ffprobe_tags_text(str(fp))
            result["tc_start_sec"] = _bwf_start_seconds(tags, sample_rate)
            result["tc_source"] = "bwf-time-reference" if result["tc_start_sec"] is not None else None
            result["scene"], result["take"] = _scene_take(tags)
            # Mesmo texto, zero subprocessos a mais: a data/hora reais e o rótulo
            # de diária já estão nele. Ver `_bwf_origination` e `_tape`.
            result["bwf_date"], result["bwf_time"] = _bwf_origination(tags)
            result["tape"] = _tape(tags)
            if result["bwf_date"] and result["date_source"] is None:
                result["date_source"] = "bwf"

            # Áudio que NÃO é BWF não tem `time_reference` — é o caso das tracks
            # de áudio do OP-Atom, que carregam o TC como `HH:MM:SS:FF` na stream.
            # Sem isto o som fica sem relógio, e som sem relógio é o que ancora o
            # sync: o TC do vídeo sozinho não resolve a diária.
            if result["tc_start_sec"] is None:
                from sync.tcmatch import tc_to_real_seconds

                tc = _ffprobe_stream_timecode(str(fp))
                # ⚠️ NÃO usar `comment_Soundroll TC Rate` daqui. Ela PARECE a taxa
                # do rolo (um material real declara `25` num projeto a 23,976), e
                # tentei usá-la — deslocava o som em 36 s. O contra-teste: só a taxa
                # de 23,976 reproduz o relógio de parede do PRÓPRIO gravador
                # (`comment_Shoot Date`) com 0,03 s de erro; a 25 erra 36 s, que é
                # exatamente a deriva de 0,1 % do NTSC em 10 h de timecode. Seja lá o
                # que aquela tag descreve, não é a base em que o TC conta.
                rate = _tc_rate(media_info)
                # ⚠️ A procedência só vale se a conversão VINGOU. `tc_to_real_seconds`
                # devolve `None` num TC malformado ou com frame >= a base (um TC track
                # dizendo 23,976 num relógio que conta até 24, por exemplo) — e
                # carimbar `ffprobe-stream` num `tc_start_sec` que ficou `None` é
                # exatamente a mentira que `tc_source` foi criado para evitar.
                segundos = tc_to_real_seconds(tc, rate, ";" in tc) if (tc and rate) else None
                if segundos is not None:
                    result["tc_start_sec"] = segundos
                    result["tc_source"] = "ffprobe-stream"
                    # ⚠️ A TAXA EM QUE ESSE VALOR CONTA, e é por isso que ela viaja
                    # junto. `tc_start_sec` sempre significou "amostras desde a
                    # meia-noite REAL" (é de um BWF), e o motor conta com isso: o
                    # som dá a volta do dia por 86 400 s exatos. Este aqui vem de um
                    # TIMECODE, então herda o 0,1 % do NTSC e a volta dele é a do
                    # timecode — 86 486 s a 23,976. A 24 fps cravado dá no mesmo; a
                    # 23,976 são 86 s de erro por dia. Ver `_Sound.tc_abs_sec`.
                    result["tc_sec_fps"] = rate

    return result
