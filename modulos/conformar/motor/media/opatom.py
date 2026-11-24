"""
Órbita — leitor de MXF OP-Atom (o formato da mídia GERENCIADA do Avid).

## O problema que este módulo resolve

O Avid grava cada TRACK de um clipe num arquivo `.mxf` separado: o vídeo num, e
**cada canal de áudio no seu**. Um clipe de câmera com 2 canais são TRÊS arquivos.
Para o resto do Órbita, um clipe sempre foi UM arquivo — e é essa suposição que
quebra aqui.

E ela quebra em silêncio, do pior jeito: o `.mxf` já está no `MEDIA_EXTENSIONS`
do Rust, então o portão de extensão deixa passar; e a regra que decide câmera-vs-som
é "tem fps → câmera". O arquivo de áudio de uma câmera **não tem fps** — logo cada
canal de cada câmera entraria no motor como um gravador de som direto próprio.
Nada falharia; a diária só sairia errada.

Por isso o agrupamento tem de acontecer ANTES de o motor ver a lista: N arquivos
entram, um clipe `{vídeo, áudios[]}` sai.

## A chave: `material_package_umid`

É uma tag de FORMATO que o `ffprobe` já entrega, idêntica em todas as tracks do
mesmo clipe. Medida sobre 540 arquivos reais: 111 clipes, zero falhas.

Ela vale duas vezes, e a segunda é o motivo de este módulo existir agora: o
`material_package_umid` **é o MobID do MasterMob** — a mesma identidade que uma
composição AAF/`.avb` usa para apontar para mídia gerenciada. Agrupar na leitura e
identificar o master na escrita são a mesma chave.

## As três armadilhas (todas medidas, todas com defesa aqui)

1. **O `timecode` pode ser o do MATERIAL, não o da fonte.** O mesmo clipe lê
   `08:12:41:20` numa pasta e `01:00:00:00` noutra, conforme como a mídia foi
   criada. É um relógio que PASSA numa checagem de "tem TC" e mente. Defesa:
   `timecode_verdict()` — ver a docstring dela.
2. **`reel_name` NÃO é o nome do clipe de câmera.** Pode vir vazio ou trazer só o
   CARTÃO (`A001`). Defesa: este módulo **não usa** `reel_name` para nada; ele é
   exposto como informação crua e nada depende dele.
3. **Agrupar por NOME DE ARQUIVO cobre ~7% do acervo real.** Há duas
   nomenclaturas (`CLIPE_A01.mxf`, com a track no fim, e `A01.<hash>.mxf`, com a
   track na FRENTE e o resto não-compartilhado). Defesa: o nome do arquivo não
   entra em decisão nenhuma aqui — nem para agrupar, nem para ordenar canais.

Detalhes de FORMATO (e a medição) vivem no banco de NLEs,
`protocolos/mxf/README.md` §rota ffprobe.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from . import fftools, safepath

# O timecode padrão de início de sequência do Avid. Não é um TC de fonte: é o que
# sobra quando o TC da fonte se perdeu. Ver `timecode_report`.
AVID_DEFAULT_TC = "01:00:00:00"

# Valores que NÃO são leitura de relógio nenhum: o início padrão de sequência do
# Avid e o zero de quem não tem TC (as duas formas de "não sei" se disfarçando de
# resposta). Repetição DESTES entre clipes é o sinal da armadilha nº 1.
TC_SENTINELAS = (AVID_DEFAULT_TC, "00:00:00:00")


# ── O que sai da leitura ─────────────────────────────────────────────────────


@dataclass
class OpAtomFile:
    """Um arquivo `.mxf` OP-Atom = UMA track de um clipe."""

    path: str
    clip_umid: str          # material_package_umid — a chave de agrupamento
    clip_name: str | None   # material_package_name (nome na bin; editável)
    file_umid: str | None   # file_package_umid da própria essência
    kind: str               # "video" | "audio" | "data"
    track_index: int | None  # posição da track DENTRO do clipe (ver `_essence`)
    fps_num: int | None = None
    fps_den: int | None = None
    duration_frames: int | None = None
    duration_s: float | None = None
    sample_rate: int | None = None
    channels: int | None = None
    tc_start: str | None = None
    reel_name: str | None = None   # ⚠️ cru, sem consumidor — ver armadilha 2
    op_pattern: str | None = None

    @property
    def fps(self) -> float | None:
        """Taxa como float. O par num/den fica guardado de propósito: arredondar
        23,976 para 24 derivaria ~1,7 s numa timeline de 29 min."""
        if not self.fps_num or not self.fps_den:
            return None
        return self.fps_num / self.fps_den


@dataclass
class OpAtomClip:
    """As N tracks de um clipe, reunidas. É isto que o motor deveria receber."""

    umid: str
    name: str | None
    video: str | None = None
    audio: list[str] = field(default_factory=list)   # em ordem de track
    data: list[str] = field(default_factory=list)    # excluídas da essência
    fps_num: int | None = None
    fps_den: int | None = None
    duration_frames: int | None = None
    duration_s: float | None = None
    sample_rate: int | None = None
    channels_total: int = 0
    tc_start: str | None = None
    tc_is_avid_default: bool = False

    @property
    def fps(self) -> float | None:
        if not self.fps_num or not self.fps_den:
            return None
        return self.fps_num / self.fps_den

    @property
    def paths(self) -> list[str]:
        return ([self.video] if self.video else []) + self.audio + self.data

    @property
    def has_video(self) -> bool:
        return self.video is not None


@dataclass
class ScanResult:
    clips: list[OpAtomClip] = field(default_factory=list)
    # Arquivos que o `ffprobe` leu mas que NÃO são OP-Atom (ou não têm a chave de
    # agrupamento). Ficam listados em vez de sumirem: um arquivo engolido em
    # silêncio é exatamente o modo de falha que este módulo existe para evitar.
    ignored: list[tuple[str, str]] = field(default_factory=list)  # (path, motivo)
    duplicates: list[str] = field(default_factory=list)  # mesma essência noutro caminho


# ── Parte pura: do JSON do ffprobe para os fatos ─────────────────────────────


def is_op_atom(op_pattern: str | None) -> bool:
    """O UL de Operational Pattern diz se é OP-Atom, sem parser próprio.

    O `ffprobe` entrega o UL em quatro grupos hexadecimais. No SMPTE 390M o
    **byte 13** (o primeiro do quarto grupo) vale `0x10` para a família OP-Atom.
    Observados no material: `…10000000` (o canônico), `…10020000` e `…10030000` —
    o significado do qualificador ainda é desconhecido, e por isso NÃO se olha
    para ele.
    """
    if not op_pattern:
        return False
    grupos = op_pattern.strip().lower().split(".")
    if len(grupos) != 4:
        return False
    return grupos[2] == "0d010201" and grupos[3][:2] == "10"


def _int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _fraction(raw: str | None) -> tuple[int | None, int | None]:
    """`"24000/1001"` → `(24000, 1001)`. Guardado como fração de propósito."""
    if not raw or "/" not in raw:
        return None, None
    num, _, den = raw.partition("/")
    n, d = _int(num), _int(den)
    if not n or not d:
        return None, None
    return n, d


def _video_rate(stream: dict) -> tuple[int | None, int | None]:
    """A taxa de quadros — por VOTAÇÃO entre três candidatas, nunca por uma só.

    ⚠️ Medido no material do usuário: **`r_frame_rate` mente por um fator de 2**
    em parte dos arquivos (`12000/1001` num clipe cuja taxa real é `24000/1001`),
    e noutros o `avg_frame_rate` vem `0/0`. Nenhuma das duas serve sozinha, e o
    erro é do pior tipo: silencioso e plausível — 11,988 é um número que ninguém
    estranha até a timeline sair com o dobro da duração.

    A terceira candidata é o **inverso do `time_base`**, e é a mais confiável
    porque é ela que faz a conta fechar: `duration_ts` está NESSA base, e
    `duration_ts × time_base` reproduz a duração em segundos nos dois casos.

    Regra: vence a taxa apoiada por pelo menos duas candidatas; no empate, a do
    `time_base`. Assim nenhuma fonte isolada decide.

    ⛔ Sem acordo e com o `time_base` que não é de quadro (o MP4 de celular de taxa
    variável: `1/90000`, `1/600` → 90000 fps): média ABAIXO do cabeçalho = taxa
    variável, vale o `r_frame_rate` (é por ele que o Resolve conta o arquivo,
    `sonda.taxa_variavel`); ACIMA = o MXF do Avid, vale a média. Antes (até
    2026-10-28) a votação devolvia 90000 fps. Medido em 372 arquivos de
    `MIDIAS DE TESTES` + `Avid MediaFiles`: só os 5 V01.mxf do Avid diferem do
    `r_frame_rate` cru (11,988 → 23,976; 14,985 → 29,97).
    """
    candidatas: list[tuple[int, int]] = []

    tb_num, tb_den = _fraction(stream.get("time_base"))
    # O `time_base` de vídeo é a DURAÇÃO de um quadro; invertê-lo dá a taxa.
    pelo_time_base = (tb_den, tb_num) if tb_num and tb_den else (None, None)

    for chave in ("avg_frame_rate", "r_frame_rate"):
        n, d = _fraction(stream.get(chave))
        if n and d:
            candidatas.append((n, d))
    if pelo_time_base[0] and pelo_time_base[1]:
        candidatas.append(pelo_time_base)  # type: ignore[arg-type]

    if not candidatas:
        return None, None

    def valor(par):
        return par[0] / par[1]

    for par in candidatas:
        if sum(1 for outra in candidatas if abs(valor(outra) - valor(par)) < 1e-6) >= 2:
            return par
    if pelo_time_base[0] and valor(pelo_time_base) <= _TAXA_MAXIMA:
        return pelo_time_base
    # sem acordo nem time_base de quadro: média ACIMA do cabeçalho = o MXF do Avid (vale a média); ABAIXO = taxa
    # variável (vale o cabeçalho, como o Resolve) — a mesma leitura de `sonda.taxa_variavel`
    r, a = _fraction(stream.get("r_frame_rate")), _fraction(stream.get("avg_frame_rate"))
    if r[0] and r[1] and a[0] and a[1]:
        return a if valor(a) > valor(r) else r
    return candidatas[0]


#: acima disso o inverso do `time_base` é relógio do contêiner, não quadro (o alto de câmera lenta chega a 240)
_TAXA_MAXIMA = 300


def _essence(streams: list[dict]) -> tuple[dict | None, int | None]:
    """A stream de ESSÊNCIA do arquivo e o índice da track dela no clipe.

    Um OP-Atom carrega uma essência só, mas o `ffprobe` lista TODAS as tracks do
    clipe (as outras entram como `data`, vazias). Isso é de graça duas vezes:

    - de UM arquivo já se sabe quantas tracks o clipe tem;
    - **a posição da essência na lista é o número da track dentro do clipe** —
      no `V01` a essência está em 0, no `A01` em 1, no `A02` em 2. É daqui que sai
      a ORDEM DOS CANAIS, e não do nome do arquivo (ver armadilha 3).

    Arquivo de track de dados não tem essência de vídeo/áudio: devolve
    `(None, None)` e o chamador o classifica como `data`.
    """
    for pos, s in enumerate(streams):
        if s.get("codec_type") in ("video", "audio"):
            return s, _int(s.get("index")) if s.get("index") is not None else pos
    return None, None


def parse_probe(doc: dict, path: str) -> OpAtomFile | str:
    """Um documento do `ffprobe` (`-show_format -show_streams`) → `OpAtomFile`.

    Devolve uma **string com o motivo** quando o arquivo não serve — nunca `None`
    mudo, para o motivo chegar ao `ScanResult.ignored` e ao log.
    """
    fmt = doc.get("format") or {}
    ftags = fmt.get("tags") or {}
    streams = doc.get("streams") or []

    op = ftags.get("operational_pattern_ul")
    if not is_op_atom(op):
        return f"não é OP-Atom (operational_pattern_ul={op or 'ausente'})"

    umid = ftags.get("material_package_umid")
    if not umid:
        # Sem a chave não há agrupamento possível. Chutar por nome seria pior que
        # ignorar: a rota por nome cobre ~7% do acervo real (armadilha 3).
        return "sem material_package_umid (chave de agrupamento)"

    essence, track_index = _essence(streams)
    if essence is None:
        return _data_file(path, umid, ftags, op)

    kind = essence["codec_type"]
    stags = essence.get("tags") or {}
    fps_num, fps_den = _video_rate(essence) if kind == "video" else (None, None)

    duration_s = None
    try:
        duration_s = float(essence["duration"])
    except (KeyError, TypeError, ValueError):
        pass

    # Duração em FRAMES sem passar por segundos: `duration_ts` está na base de
    # tempo da própria stream, então a conta é exata (649 frames, não 649,0001).
    duration_frames = None
    tb_num, tb_den = _fraction(essence.get("time_base"))
    dur_ts = _int(essence.get("duration_ts"))
    if kind == "video" and dur_ts and tb_num and tb_den and fps_num and fps_den:
        # ts * time_base = segundos; segundos * fps = frames.
        duration_frames = round(dur_ts * tb_num * fps_num / (tb_den * fps_den))

    return OpAtomFile(
        path=path,
        clip_umid=umid,
        clip_name=ftags.get("material_package_name"),
        file_umid=stags.get("file_package_umid"),
        kind=kind,
        track_index=track_index,
        fps_num=fps_num,
        fps_den=fps_den,
        duration_frames=duration_frames,
        duration_s=duration_s,
        sample_rate=_int(essence.get("sample_rate")),
        channels=_int(essence.get("channels")),
        tc_start=stags.get("timecode"),
        reel_name=stags.get("reel_name"),
        op_pattern=op,
    )


def _data_file(path: str, umid: str, ftags: dict, op: str | None) -> OpAtomFile:
    """Track de DADOS (`D01.*`): pertence ao clipe, mas não é essência.

    Existe de verdade no material (23 de 540 arquivos medidos) e não tem
    `reel_name` nem `timecode`. Fica registrada no clipe para o inventário
    fechar, e fora de qualquer tratamento de mídia.
    """
    return OpAtomFile(
        path=path,
        clip_umid=umid,
        clip_name=ftags.get("material_package_name"),
        file_umid=None,
        kind="data",
        track_index=None,
        op_pattern=op,
    )


def group(files: list[OpAtomFile]) -> tuple[list[OpAtomClip], list[str]]:
    """Junta as tracks pelo `clip_umid`. Devolve `(clipes, duplicatas)`.

    ORDEM DOS CANAIS: por `track_index` (a posição da essência na lista de
    streams), nunca pelo nome do arquivo.

    DUPLICATAS: o mesmo `file_package_umid` aparece em mais de um caminho quando
    há cópias entre as pastas numeradas da `Avid MediaFiles`. Fica a primeira
    ocorrência e as outras são REPORTADAS — contar a mesma track duas vezes
    inflaria a contagem de canais do clipe.
    """
    por_clipe: dict[str, list[OpAtomFile]] = {}
    vistos: set[str] = set()
    duplicatas: list[str] = []

    for f in files:
        if f.file_umid:
            if f.file_umid in vistos:
                duplicatas.append(f.path)
                continue
            vistos.add(f.file_umid)
        por_clipe.setdefault(f.clip_umid, []).append(f)

    clipes: list[OpAtomClip] = []
    for umid, tracks in por_clipe.items():
        video = next((t for t in tracks if t.kind == "video"), None)
        audios = sorted(
            (t for t in tracks if t.kind == "audio"),
            key=lambda t: (t.track_index if t.track_index is not None else 1 << 30, t.path),
        )
        dados = [t for t in tracks if t.kind == "data"]

        # O nome vem de qualquer track (é do clipe, não da track). O TC e a taxa
        # vêm do vídeo quando há vídeo; num clipe só de áudio, da primeira track.
        fonte = video or (audios[0] if audios else tracks[0])
        tc = fonte.tc_start

        clipes.append(
            OpAtomClip(
                umid=umid,
                name=next((t.clip_name for t in tracks if t.clip_name), None),
                video=video.path if video else None,
                audio=[t.path for t in audios],
                data=[t.path for t in dados],
                fps_num=fonte.fps_num,
                fps_den=fonte.fps_den,
                duration_frames=fonte.duration_frames,
                duration_s=fonte.duration_s,
                sample_rate=next((t.sample_rate for t in audios if t.sample_rate), None),
                channels_total=sum(t.channels or 0 for t in audios),
                tc_start=tc,
                tc_is_avid_default=(tc == AVID_DEFAULT_TC),
            )
        )

    return clipes, duplicatas


def timecode_report(clips: list[OpAtomClip]) -> dict:
    """O TC deste conjunto de clipes serve para posicionar no tempo?

    **A armadilha nº 1, virada em código.** O `ffprobe` expõe UM timecode, e ele
    pode ser o do MaterialPackage (o "início da sequência") em vez do da fonte —
    depende de como a mídia foi criada. O mesmo clipe foi medido lendo
    `08:12:41:20` numa pasta e `01:00:00:00` noutra.

    Um TC que existe mas mente é PIOR que TC nenhum: passa em toda checagem de
    presença e leva o motor a distribuir a diária por uma distância falsa — a
    mesma classe de erro do TC rec-run.

    ⚠️ **TC repetido tem DUAS causas, e só uma é mentira** — isto custou um falso
    positivo antes de virar regra:

    - o **mesmo material importado duas vezes** (`X` e `X.new.01` convivendo na
      mesma pasta) compartilha o TC porque compartilha a FONTE. O relógio está
      certo; o que se repetiu foi o clipe. Acusar isso seria alarme falso sobre
      material bom — e alarme falso é como um aviso deixa de ser lido.
    - vários clipes colapsados num **valor-sentinela** (`01:00:00:00`, o início
      padrão de sequência do Avid, ou `00:00:00:00`, o zero de quem não tem TC).
      Esses valores não são leitura de relógio nenhum: são "não sei" com cara de
      resposta. É esta a armadilha.

    Por isso o veredicto olha para os SENTINELAS, não para repetição em geral —
    e a repetição toda continua exposta em `repetidos`, para quem quiser julgar.

    Veredictos:
      - `"utilizavel"` — nenhum sentinela repetido.
      - `"suspeito_material"` — TODOS os clipes no mesmo TC.
      - `"misto_suspeito"` — parte do conjunto colapsada num sentinela. É o caso
        mais traiçoeiro: a variação do resto faria uma checagem ingênua aprovar o
        conjunto inteiro.
      - `"ausente"` — ninguém tem TC.
      - `"indeterminado"` — um clipe só. Sem dois relógios não há variação para
        observar, e afirmar qualquer coisa seria chute.
    """
    com_tc = [c.tc_start for c in clips if c.tc_start]
    distintos = sorted(set(com_tc))
    repetidos = sorted({tc for tc in distintos if com_tc.count(tc) > 1})
    sentinelas = [tc for tc in repetidos if tc in TC_SENTINELAS]

    if not com_tc:
        veredicto = "ausente"
    elif len(clips) < 2:
        veredicto = "indeterminado"
    elif len(distintos) == 1:
        veredicto = "suspeito_material"
    elif sentinelas:
        veredicto = "misto_suspeito"
    else:
        veredicto = "utilizavel"

    return {
        "veredicto": veredicto,
        "com_tc": len(com_tc),
        "sem_tc": len(clips) - len(com_tc),
        "distintos": len(distintos),
        "repetidos": repetidos,
        "sentinelas_repetidos": sentinelas,
        "em_padrao_avid": sum(1 for c in clips if c.tc_is_avid_default),
    }


def timecode_verdict(clips: list[OpAtomClip]) -> str:
    """Só o veredicto de `timecode_report`, para quem não quer a evidência."""
    return timecode_report(clips)["veredicto"]


# ── Parte com I/O ────────────────────────────────────────────────────────────


def probe_file(path: str, timeout: int = 30) -> dict | None:
    """Um `ffprobe` por arquivo, em JSON. `None` se o ffprobe faltar ou falhar."""
    exe = fftools.ffprobe()
    if not exe:
        return None
    try:
        saida = subprocess.run(
            [exe, "-v", "error", "-show_format", "-show_streams", "-of", "json",
             safepath.ff_input(path)],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=timeout, check=True, **fftools.SEM_JANELA,
        ).stdout
        return json.loads(saida)
    except Exception:
        return None


def _mxf_files(roots) -> list[str]:
    """Todos os `.mxf` sob os caminhos dados, em ordem estável.

    Descarta os `._*` do macOS (forks de recurso do AppleDouble): eles têm a
    extensão certa e nenhum conteúdo, e o `ffprobe` gasta um processo em cada um.
    """
    achados: list[str] = []
    for root in roots:
        p = Path(root)
        if p.is_file():
            candidatos = [p]
        else:
            candidatos = sorted(q for q in p.rglob("*") if q.is_file())
        for q in candidatos:
            if q.suffix.lower() == ".mxf" and not q.name.startswith("._"):
                achados.append(str(q))
    return sorted(achados)


def colapsar_entradas(entries: list[dict], on_progress=None) -> list[dict]:
    """Entradas do motor com arquivos OP-Atom → UMA entrada por CLIPE.

    É a ponte entre este módulo e o `sync/engine.py`. O motor recebe uma lista de
    arquivos; se houver `.mxf` do Avid nela, cada clipe está espalhado em N deles e
    precisa ser reunido **antes** de o motor olhar — senão cada canal de áudio de
    cada câmera entra como um gravador de som direto próprio (ver o cabeçalho).

    O que sai por clipe:
      - `path`        = o arquivo de VÍDEO (é ele que tem fps, timecode e duração,
                        e é ele que um NLE referencia). Num clipe sem vídeo, o
                        primeiro arquivo de áudio.
      - `audio_path`  = o primeiro canal de áudio, que é o guia de sync.
      - `audio_channels` = quantos canais o clipe tem de verdade.
      - `kind`        = `"sound"` quando não há vídeo — sem isso a regra "tem fps →
                        câmera" já classificaria certo, mas dizer explicitamente
                        poupa o motor de adivinhar.

    Entradas que não são `.mxf` passam INTACTAS. O `group_id`/`group_order` da
    primeira entrada de cada clipe é preservado: quem agrupa câmeras é quem chamou,
    e este módulo não tem opinião sobre isso.
    """
    saida: list[dict] = []
    mxf: list[dict] = []
    for e in entries:
        entrada = {"path": e, "group_id": e, "group_order": None} if isinstance(e, str) else dict(e)
        # ⭐ IDEMPOTÊNCIA. Uma entrada que já declara `audio_path` JÁ É um clipe
        # reunido, e passá-la por aqui de novo a estragaria: na segunda volta cada
        # clipe traz um arquivo só na lista, então o agrupamento veria um som
        # estéreo como MONO e devolveria `audio_channels=1`. Aconteceu — o motor
        # colapsa por conta própria e o chamador que já tinha colapsado pagava por
        # isso, sem erro nenhum, só com um canal a menos na timeline.
        if entrada.get("audio_path"):
            saida.append(entrada)
        elif Path(entrada["path"]).suffix.lower() == ".mxf":
            mxf.append(entrada)
        else:
            saida.append(entrada)

    if not mxf:
        return saida

    por_caminho = {e["path"]: e for e in mxf}
    arquivos: list[OpAtomFile] = []
    total = len(mxf)
    for i, e in enumerate(mxf, 1):
        if on_progress:
            on_progress(i, total, e["path"])
        doc = probe_file(e["path"])
        lido = parse_probe(doc, e["path"]) if doc is not None else "ffprobe não leu"
        if isinstance(lido, str):
            # Não é OP-Atom (ou não deu para ler): segue como arquivo solto, que é
            # o comportamento de sempre. Um `.mxf` de câmera comum cai aqui.
            saida.append(e)
        else:
            arquivos.append(lido)

    clipes, _duplicatas = group(arquivos)
    for c in clipes:
        base = por_caminho.get(c.video or (c.audio[0] if c.audio else ""), {})
        if not base:
            base = next((por_caminho[p] for p in c.paths if p in por_caminho), {})
        entrada = dict(base)
        entrada["path"] = c.video or (c.audio[0] if c.audio else base.get("path"))
        if c.audio:
            entrada["audio_path"] = c.audio[0]
            entrada["audio_channels"] = c.channels_total or len(c.audio)
        if not c.has_video:
            entrada["kind"] = "sound"
        saida.append(entrada)
    return saida


def scan(roots, on_progress=None) -> ScanResult:
    """Varre pastas/arquivos e devolve os clipes OP-Atom reunidos.

    `on_progress(feito, total, caminho)` é opcional — uma varredura de centenas de
    arquivos é um processo longo, e processo longo sem barra é inaceitável aqui.
    """
    caminhos = _mxf_files(roots)
    total = len(caminhos)
    arquivos: list[OpAtomFile] = []
    ignorados: list[tuple[str, str]] = []

    for i, caminho in enumerate(caminhos, 1):
        if on_progress:
            on_progress(i, total, caminho)
        doc = probe_file(caminho)
        if doc is None:
            ignorados.append((caminho, "ffprobe não leu o arquivo"))
            continue
        lido = parse_probe(doc, caminho)
        if isinstance(lido, str):
            ignorados.append((caminho, lido))
        else:
            arquivos.append(lido)

    clipes, duplicatas = group(arquivos)
    clipes.sort(key=lambda c: (c.name or "", c.umid))
    return ScanResult(clips=clipes, ignored=ignorados, duplicates=duplicatas)
