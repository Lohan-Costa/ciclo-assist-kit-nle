"""Casar o PROXY que o Premiere usa com o ORIGINAL de câmera, numa pasta que o editor indica.

Candidato = arquivo de vídeo com o mesmo nome do proxy, sem a extensão (ALEXA `.mov` → `.mxf`,
DJI `.mov` → `.MP4`/`.MOV`). Cada candidato é CONFERIDO antes de valer:

  • não vazio, legível e inteiro (o MXF termina no RIP — `mxf_completo`);
  • mesma duração do proxy (±1 quadro);
  • mesmo timecode, quando os dois têm (o DJI não tem; o proxy dele traz 00:00:00:00);
  • NÃO é cópia do proxy: mesmo raster E mesmo codec do proxy = outra cópia da conversão.

Sobrou mais de um candidato → `ambiguo`, para o editor escolher (regra do projeto: empate no
casamento é do editor, nunca desempate automático). EXCETO cópias idênticas do mesmo arquivo
(mesmo tamanho e mesmos bytes no início, meio e fim): não há o que escolher, valem como um original
só, no caminho da primeira raiz indicada. Medido 2026-10-03: dois HDs com 67 MXF repetidos — todos
idênticos.
"""
from __future__ import annotations

import os
import subprocess
import unicodedata

from media import sonda  # noqa: E402 — a leitura única do ffprobe por arquivo
from media.opatom import _video_rate  # noqa: E402 — a votação da taxa (B074)
from media.confirmacao import PISO_IMAGEM, MARGEM_IMAGEM, confirmar_pela_imagem, quadro_rgb  # noqa: E402,F401

EXT_VIDEO = {".mxf", ".mov", ".mp4", ".r3d", ".braw", ".ari", ".arx", ".crm", ".mts", ".avi"}

_SONDA: dict[str, dict] = {}


_CHAVE_RIP = bytes.fromhex("060e2b34020501010d01020101110100")


def mxf_completo(caminho: str) -> bool:
    """Um MXF termina no Random Index Pack (SMPTE 377: chave `06 0e 2b 34 02 05 01 01 0d 01 02 01
    01 11 01 00`; os 4 últimos bytes = o tamanho do RIP). Um MXF TRUNCADO (cópia ou gravação
    interrompida) fica SEM o RIP — o cabeçalho (duração, TC) continua dizendo o arquivo inteiro,
    por isso o ffprobe não acusa (medido 2026-10-02: A048C005 e A080C002 do
    PRODB, Media Offline no Resolve)."""
    import struct
    try:
        with open(caminho, "rb") as f:
            f.seek(0, 2)
            tam = f.tell()
            if tam < 64:
                return False
            f.seek(tam - 4)
            n = struct.unpack(">I", f.read(4))[0]
            if not 20 <= n <= min(tam, 1 << 20):
                return False
            f.seek(tam - n)
            return f.read(16) == _CHAVE_RIP
    except OSError:
        return False


def sondar(caminho: str) -> dict:
    """`{ok, w, h, codec, fps, dur_s, tc}` pelo ffprobe (cacheado). ARRIRAW e X-OCN: o vídeo
    sai `unknown` e 0×0, mas a duração e o TC (camada `format`) valem — banco,
    `protocolos/mxf/codecs-proprietarios.md`."""
    if caminho in _SONDA:
        return _SONDA[caminho]
    r = {"ok": False}
    try:
        if os.path.getsize(caminho) > 0:
            j = sonda.ler(caminho)                 # a leitura única (`media/sonda.py`)
            st = sonda.primeiro(j, "video")        # o `-select_streams v:0` de antes
            fmt = j.get("format") or {}
            # a taxa por VOTAÇÃO (r/avg/time_base), nunca um campo cru: o `r_frame_rate` mente ×2 no OP-Atom (banco,
            # bugs-do-mundo-real B074). Desde 2026-10-18 ela também decide a grade de quadros do arquivo apontado.
            num, den = _video_rate(st)
            fps = num / den if num and den else None
            dur = st.get("duration") or fmt.get("duration")
            r = {"ok": bool(fmt) and dur not in (None, "N/A"),
                 "w": st.get("width") or 0, "h": st.get("height") or 0,
                 "codec": st.get("codec_name"), "fps": fps,
                 "dur_s": float(dur) if dur not in (None, "N/A") else None,
                 "tc": (st.get("tags") or {}).get("timecode") or (fmt.get("tags") or {}).get("timecode"),
                 # reel / tape name (autor, 2026-11-22: "metadados bastante usados pelos editores online"): o do mov
                 # fica na trilha de TC (`reel_name`); o MXF pode trazer `tape_name` no formato
                 "reel": next((t.get("reel_name") for t in [(x.get("tags") or {}) for x in j.get("streams") or []]
                               if t.get("reel_name")), None)
                         or (fmt.get("tags") or {}).get("reel_name") or (fmt.get("tags") or {}).get("tape_name")}
        if r.get("ok") and os.path.splitext(caminho)[1].lower() in (".mov", ".mp4", ".m4v"):
            t = tmcd_cru(caminho)
            if t:
                r["tmcd"] = t
    except subprocess.TimeoutExpired:
        # LENTO não é ilegível: sem cache. ⛔ Medido 2026-10-04 (PRODB frio, 8 simultâneas): 5
        # ARRIRAW passaram de 60 s e eram recusados como ilegíveis — originais perfeitos no proxy.
        return {"ok": False, "lento": True}
    except (OSError, ValueError, subprocess.SubprocessError):
        pass
    _SONDA[caminho] = r
    return r


_EXT_DE_MIDIA = (".mov", ".mp4", ".m4v", ".mxf", ".braw", ".r3d", ".ari", ".mts", ".avi")


def _sem_extensao(reel: str) -> str:
    """O reel que o Baselight grava no render vem com a extensão do original quando o plano entrou pelo NOME do arquivo
    (BL08, 2026-11-23: `A002C001.mov`); a chave do índice é o nome sem extensão."""
    reel = (reel or "").strip()
    raiz, ext = os.path.splitext(reel)
    return raiz if ext.lower() in _EXT_DE_MIDIA else reel


def tmcd_cru(caminho: str) -> dict | None:
    """O 1º quadro da trilha de TC (`tmcd`) do QuickTime, CRU: `{quadro, base, df, taxa}` — o contador, a base do rótulo
    (`nframes`), o drop-frame e a taxa em que o contador anda (timescale/frameDuration). ⭐ Por que (BL08, 2026-11-23): o
    render do Baselight de um plano de OUTRA taxa sai na taxa da timeline (23,976) e grava o TC de FONTE na base do
    ORIGINAL (`nframes` 30 com DF, ou 60): o contador é o quadro exato do original no in do plano. O ffprobe converte
    isso por tempo (59,94 → "12:00:01:23", com erro de fração de quadro) ou o recusa ("Drop frame is only allowed with
    multiples of 30000/1001") e o TC some. Lê só o `moov` (com seek), nada da mídia além de 4 bytes. None se não houver."""
    import struct

    try:
        with open(caminho, "rb") as fh:
            fim = os.fstat(fh.fileno()).st_size
            pos, moov = 0, None
            while pos + 8 <= fim:
                fh.seek(pos)
                sz, tipo = struct.unpack(">I4s", fh.read(8))
                cab = 8
                if sz == 1:
                    sz, cab = struct.unpack(">Q", fh.read(8))[0], 16
                elif sz == 0:
                    sz = fim - pos
                if sz < cab:
                    return None
                if tipo == b"moov":
                    if sz > 64 * 1024 * 1024:
                        return None
                    fh.seek(pos + cab)
                    moov = fh.read(sz - cab)
                    break
                pos += sz
            if moov is None:
                return None

            def filhos(b, a, e):
                while a + 8 <= e:
                    sz, tipo = struct.unpack(">I4s", b[a:a + 8])
                    if sz < 8 or a + sz > e:
                        return
                    yield tipo, a + 8, a + sz
                    a += sz

            def achar(b, a, e, caminho_):
                for tipo, ia, ie in filhos(b, a, e):
                    if tipo == caminho_[0]:
                        return (ia, ie) if len(caminho_) == 1 else achar(b, ia, ie, caminho_[1:])
                return None

            for tipo, ta, te in filhos(moov, 0, len(moov)):
                if tipo != b"trak":
                    continue
                stbl = achar(moov, ta, te, [b"mdia", b"minf", b"stbl"])
                if not stbl:
                    continue
                stsd = achar(moov, stbl[0], stbl[1], [b"stsd"])
                if not stsd or moov[stsd[0] + 12:stsd[0] + 16] != b"tmcd":
                    continue
                e = stsd[0] + 8                               # versão/flags (4) + quantidade (4) → a 1ª entrada
                # entrada: tamanho, tipo, 6 reservados, dref (16) + 4 reservados → flags, timescale, frameDuration, nframes
                flags, escala, dur_q, base = struct.unpack(">IIIB", moov[e + 20:e + 33])
                co = achar(moov, stbl[0], stbl[1], [b"stco"])
                if co:
                    desloc = struct.unpack(">I", moov[co[0] + 8:co[0] + 12])[0]
                else:
                    co = achar(moov, stbl[0], stbl[1], [b"co64"])
                    if not co:
                        return None
                    desloc = struct.unpack(">Q", moov[co[0] + 8:co[0] + 16])[0]
                fh.seek(desloc)
                quadro = struct.unpack(">I", fh.read(4))[0]
                return {"quadro": quadro, "base": base, "df": bool(flags & 1),
                        "taxa": (escala / dur_q) if escala and dur_q else None}
    except (OSError, struct.error, ValueError):
        return None
    return None


def _chave(nome: str) -> str:
    """A chave do índice: o nome em NFC e minúsculo. ⛔ O exFAT/HFS+ do Mac LISTAM em NFD e o projeto grava NFC
    (matriz de plataforma, "Unicode do nome"): sem isso `CORAÇÃO_01` do projeto não achava o original da pasta
    (laboratório BL08, P5, 2026-11-22)."""
    return unicodedata.normalize("NFC", nome).lower()


def indexar(raizes: list[str]) -> dict[str, list[str]]:
    """{nome sem extensão, minúsculo: [caminhos]} dos vídeos sob `raizes`. Pula AppleDouble
    (`._x`, que o macOS grava em exFAT) e as pastas de trabalho do Premiere."""
    idx: dict[str, list[str]] = {}
    for raiz in raizes:
        for pasta, subs, arqs in os.walk(raiz):
            subs[:] = [s for s in subs if not s.startswith(".")
                       and "Auto-Save" not in s and "Previews" not in s]
            for a in arqs:
                if a.startswith("._"):
                    continue
                base, ext = os.path.splitext(a)
                if ext.lower() in EXT_VIDEO:
                    idx.setdefault(_chave(base), []).append(os.path.join(pasta, a))
                elif ext.lower() in EXT_PARADA or ext.lower() in EXT_SOM:
                    # imagem parada e som não têm proxy: o nome INTEIRO é a identidade (chave à parte)
                    idx.setdefault(_CHAVE_NOME + _chave(a), []).append(os.path.join(pasta, a))
    return idx


_CHAVE_NOME = "\0nome:"
_RECUSADO = "\0recusado\0/"


def _chave_recusada(caminho: str) -> str:
    """A chave de um caminho que a tranca recusou (UNC de outra produtora…): só o NOME do arquivo, atrás de um
    prefixo com NUL. Ela serve para procurar o nome nas pastas indicadas e para a lista; quem a recebe testa
    `recusado()` ANTES de qualquer função de disco. R04, 2026-10-18: 15 arquivos em \\\\169.254.100.100\\…
    viravam um item só, sem nome, e offline."""
    nome = os.path.basename((caminho or "").replace("\\", "/"))
    return _RECUSADO + nome if nome else ""


def recusado(caminho: str | None) -> bool:
    return bool(caminho) and caminho.startswith(_RECUSADO)
EXT_SOM = {".wav", ".aif", ".aiff", ".bwf", ".mp3", ".m4a"}


def pelo_nome(caminho: str, indice: dict[str, list[str]], prova=None) -> tuple[list[str], list[str]]:
    """(achados, cópias idênticas) do arquivo de nome INTEIRO igual ao de `caminho` nas pastas indexadas —
    para o que não tem proxy (imagem parada, som). Cópias idênticas valem como um só; dois diferentes, o
    editor escolhe. ⛔ O nome só ORDENA (bugs-do-mundo-real B024): `prova(candidato) → bool` confere o que o
    projeto diz do arquivo (a duração do som, o raster da imagem) e recusa o homônimo que não bate."""
    bons = list(indice.get(_CHAVE_NOME + _chave(os.path.basename(caminho.replace("\\", "/"))), []))
    if prova is not None:
        bons = [c for c in bons if prova(c)]
    copias = []
    if len(bons) > 1:
        imp = _impressao(bons[0])
        if imp is not None and all(_impressao(c) == imp for c in bons[1:]):
            copias, bons = bons[1:], bons[:1]
    imagem = None
    if len(bons) > 1 and proxy_existe:
        # ⭐⭐ EMPATE SÓ COM CONFIRMAÇÃO VISUAL (autor, 2026-11-22): o quadro do DAILY × o de cada candidato. Um bate e
        # os outros não → ele; sem essa confirmação, o empate fica para o editor — nunca decidimos sozinhos.
        escolhido, imagem = _confirmar_pela_imagem(proxy, bons, px)
        if escolhido:
            bons = [escolhido]
    return bons, copias


def _mesma_duracao(caminho: str, dur_s: float) -> bool:
    """A duração do arquivo (ffprobe, `format`) bate com a do projeto (±0,1 s: o projeto guarda a do arquivo)."""
    try:
        d = float((sonda.ler(caminho).get("format") or {}).get("duration") or 0)
    except (OSError, ValueError, subprocess.SubprocessError):
        return False
    return d > 0 and abs(d - dur_s) <= 0.1


def relocar_sons(segmentos: list[dict], indice: dict[str, list[str]]) -> dict[str, dict]:
    """{caminho do projeto: {realocado | candidatos}} do som que NÃO está no caminho do projeto (o som direto e
    a trilha, que não passam pelo casamento do vídeo). R04, 2026-10-18: os 21 WAV do corte apontavam para S:\\
    e Y:\\ e estavam todos na pasta indicada — entravam offline."""
    video = {s["media_ref"]["local_path"] for s in segmentos if s.get("media_ref") and not s.get("is_audio")}
    fora: dict[str, dict] = {}
    for s in segmentos:
        p = (s.get("media_ref") or {}).get("local_path") if s.get("is_audio") else None
        if not p or p in video or p in fora or (not recusado(p) and os.path.isfile(p)):
            continue
        dur = (s.get("media_ref") or {}).get("dur_s")
        bons, _copias = pelo_nome(p, indice, (lambda c, d=dur: _mesma_duracao(c, d)) if dur else None)
        fora[p] = {"realocado": bons[0]} if len(bons) == 1 else {"candidatos": bons}
    return fora


def _impressao(caminho: str) -> tuple | None:
    """Tamanho + SHA-1 de 1 MB do início, do meio e do fim. Hash inteiro de um ARRIRAW (dezenas de
    GB) custaria minutos por arquivo; cópias de um mesmo arquivo batem nos três trechos."""
    import hashlib
    bloco = 1 << 20
    try:
        tam = os.path.getsize(caminho)
        h = hashlib.sha1()
        with open(caminho, "rb") as f:
            for pos in (0, tam // 2, max(0, tam - bloco)):
                f.seek(pos)
                h.update(f.read(bloco))
        return tam, h.hexdigest()
    except OSError:
        return None


def _tc_frames(tc: str | None, fps: float | None) -> int | None:
    if not tc or not fps:
        return None
    try:
        h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    except ValueError:
        return None
    n = round(fps)
    return ((h * 60 + m) * 60 + s) * n + f


def _tc_instantes(quadros: int, fps: float) -> list[float]:
    """Os instantes (s) que um TC em `quadros` na taxa `fps` pode querer dizer. Acima de 30 qps o campo de
    quadros costuma correr na METADE da taxa (MP4 de 60p em base 30 — banco `avb/escrita.md`; o 100p da
    Sony em base 50), e cada programa lê de um jeito: medido no R04 (2026-10-18), o C0296.MP4 de 100p
    está no .prproj como 21:01:03:22 e a conversão do Resolve grava 21:01:03:44 — o mesmo instante."""
    n = round(fps)
    seg, q = divmod(int(quadros), n)
    bases = [n] + ([n / 2] if n > 30 and q < n / 2 else [])
    return [(seg + q / b, b) for b in bases]


def _tc_confere(a: int, fps_a: float, b: int, fps_b: float) -> bool:
    """Dois TCs, cada um na SUA taxa, dizem o mesmo instante? Mesma taxa = o mesmo instante, exato (em uma das
    leituras da base). Taxas diferentes (o proxy é uma conversão): até 1 quadro da base mais GROSSA, porque o
    proxy arredonda o início do original para a grade dele — R04: o JUL_7672 de 100p começa em …:58:42 e o
    proxy de 60p (base 30) em …:58:12, 0,42 s × 0,40 s."""
    mesma = round(fps_a) == round(fps_b)
    return any(abs(x - y) <= (1e-6 if mesma else 1.01 / min(bx, by))
               for x, bx in _tc_instantes(a, fps_a) for y, by in _tc_instantes(b, fps_b))


#: Imagem parada usada no corte (máscara 1.85 em PNG, gráfico em JPG/TIFF/PSD): é o PRÓPRIO
#: arquivo final, não um proxy — não há original de câmera a procurar (revisão de código,
#: 2026-10-03: o PNG da máscara 1.85 recebia "REFAZER no original" sem precisar).
EXT_PARADA = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".exr", ".dpx", ".bmp", ".tga"}


#: FourCC do `CodecType` do projeto → o `codec_name` do ffprobe (a mesma família). Fora da tabela, a
#: recusa de "cópia do proxy" pelo projeto não roda (as outras provas rodam).
_FOURCC_FFPROBE = {
    "HEVC": "hevc", "hvc1": "hevc", "hev1": "hevc",
    "avc1": "h264", "H264": "h264", "h264": "h264", "AVC1": "h264",
    "ap4h": "prores", "ap4x": "prores", "apch": "prores", "apcn": "prores", "apcs": "prores",
    "apco": "prores", "aprh": "prores", "aprn": "prores",
    "AVdh": "dnxhd", "AVdn": "dnxhd", "mjpg": "mjpeg", "jpeg": "mjpeg",
}


def _do_projeto(projeto: dict | None) -> dict:
    """O que o .prproj sabe do proxy (`leitura._midia_no_projeto`), na forma de `sondar`."""
    if not projeto or not projeto.get("dur_s"):
        return {"ok": False}
    return {"ok": True, "w": projeto.get("w") or 0, "h": projeto.get("h") or 0,
            "codec": _FOURCC_FFPROBE.get(projeto.get("fourcc") or ""), "fps": projeto.get("fps"),
            "dur_s": projeto["dur_s"], "tc": None, "tc_quadros": projeto.get("tc_quadros")}


def _dentro(caminho: str, raizes: list[str] | None) -> bool:
    """O arquivo mora numa das pastas que o editor indicou (pelo TEXTO do caminho; nada é tocado)."""
    c = os.path.normcase(os.path.abspath(caminho))
    return any(c.startswith(os.path.normcase(os.path.abspath(r)).rstrip("\\/") + os.sep) for r in raizes or [])


#: Confirmação visual do empate e reel como critério: a regra e os limiares moram em `media/confirmacao.py` (os dois
#: casadores usam a mesma). `_quadro_rgb` fica aqui como nome próprio para os testes poderem trocá-lo.
_quadro_rgb = quadro_rgb


def _confirmar_pela_imagem(proxy: str, candidatos: list[str], px: dict) -> tuple[str | None, dict | None]:
    return confirmar_pela_imagem(proxy, candidatos, px.get("dur_s"), quadro=lambda c, t: _quadro_rgb(c, t))


def casar_um(proxy: str, indice: dict[str, list[str]], projeto: dict | None = None,
             raizes: list[str] | None = None) -> dict:
    """Casa UM proxy. `projeto` = o que o .prproj sabe dele (duração, TC, raster, codec): a prova
    quando o proxy não está nesta máquina.

    ⛔ Até 2026-10-09 as provas (cópia do proxy, duração, TC) só rodavam se o PROXY abrisse: sem ele,
    o arquivo de mesmo nome entrava como original só pelo nome — no R02 sem o HD dos proxies, o insert
    extra e os 2 packs de VFX viraram "original"; com o HD, "sem original". Dois drones com
    `DJI_0001.MP4` e um só na pasta: o do outro drone entraria calado. Regra do banco: o nome só
    ORDENA a busca, nunca decide (bugs-do-mundo-real B024, B107)."""
    if os.path.splitext(proxy)[1].lower() in EXT_PARADA:
        existe = not recusado(proxy) and os.path.isfile(proxy)
        if existe:
            return {"proxy": proxy, "estado": "proprio", "original": proxy, "candidatos": [], "copias": [],
                    "recusados": [], "proxy_existe": True}
        # Fora do lugar: o mesmo arquivo (nome inteiro) nas pastas indicadas — R04, 2026-10-18: o logo do
        # Y:\ estava em ISOLADO\MIDIA\04_GRAPHICS e entrava offline. Mais de um diferente = o editor escolhe.
        w, h = (projeto or {}).get("w"), (projeto or {}).get("h")
        prova = (lambda c: (sondar(c).get("w"), sondar(c).get("h")) == (w, h)) if w and h else None
        bons, copias = pelo_nome(proxy, indice, prova)
        estado = "proprio" if len(bons) == 1 else ("ambiguo" if bons else "sem_original")
        return {"proxy": proxy, "estado": estado, "original": bons[0] if len(bons) == 1 else None,
                "candidatos": list(bons), "copias": copias, "recusados": [], "proxy_existe": False}
    nome = _chave(os.path.splitext(os.path.basename(proxy.replace("\\", "/")))[0])   # D:\… no Mac (2026-10-24)
    cands = [c for c in indice.get(nome, []) if os.path.normcase(c) != os.path.normcase(proxy)]
    px = sondar(proxy) if not recusado(proxy) and os.path.exists(proxy) else {"ok": False}
    proxy_existe = bool(px.get("ok"))
    conferido_por = "proxy"
    if not proxy_existe and not px.get("lento"):
        px = _do_projeto(projeto)
        conferido_por = "projeto" if px.get("ok") else "nome"
    lento = bool(px.get("lento"))
    # ⭐ PELO REEL (autor, 2026-11-22: reel e tape name são CRITÉRIO de casamento, como o nome — metadados que os editores
    # online usam muito): nenhum arquivo com o nome do daily — o daily RENOMEADO (BL08, P4: `CENA12_T3` com reel
    # `B001C007`) — e o reel dele é o nome de um original. As provas de sempre (duração, TC, raster, cópia) valem igual.
    por_reel = None
    reel = _sem_extensao(px.get("reel") or "")
    if not cands and reel and _chave(reel) != nome:
        cands = [c for c in indice.get(_chave(reel), []) if os.path.normcase(c) != os.path.normcase(proxy)]
        por_reel = px["reel"] if cands else None
    bons, recusados = [], []
    # A cópia do proxy não é original, mas SEM o proxy nesta máquina ela é a PRÓPRIA mídia do editor em outro
    # lugar: a timeline aponta para ela (`realocado`) em vez de entrar offline. R04, 2026-10-18: o .prproj de
    # 2023 aponta para G:\, J:\, Y:\…; os 16 .mov da câmera estavam todos na pasta e entravam offline.
    mesmas, provadas = [], []
    duvidosos: list[tuple[str, str]] = []   # nome + duração batem; o TC do projeto é real e o do candidato, zero/nenhum
    maiores_zerados: list[tuple[str, str]] = []   # idem, mas MAIOR que o arquivo do projeto: o original de TC zerado
    trechos: list[tuple[str, dict]] = []   # o arquivo do projeto é um TRECHO do candidato (o render da cor voltando)
    for c in cands:
        s = sondar(c)
        if s.get("lento"):
            lento = True
            recusados.append((c, "o disco não respondeu a tempo (lento ou com defeito?) — confira"))
            continue
        if s.get("ok") and c.lower().endswith(".mxf") and not mxf_completo(c):
            recusados.append((c, "incompleto: o MXF não termina (arquivo truncado)"))
            continue
        if not s.get("ok"):
            recusados.append((c, "incompleto: vazio ou ilegível"))
            continue
        copia = False
        tr = _trecho(px, s) if px.get("ok") else None
        if tr:
            trechos.append((c, tr))
            continue
        if px.get("ok"):
            copia = bool(px.get("codec") and s.get("w") == px.get("w") and s.get("h") == px.get("h")
                         and s.get("codec") == px.get("codec"))
            if copia and proxy_existe:
                recusados.append((c, "cópia do proxy (mesmo raster e codec)"))
                continue
            # (sem o proxy, a cópia passa ainda pela duração e pelo TC: tem de ser a MESMA mídia)
            fps = px.get("fps") or s.get("fps")
            if px.get("dur_s") and s.get("dur_s") and fps \
                    and abs(px["dur_s"] - s["dur_s"]) * fps > 1.01:
                recusados.append((c, f"duração diferente ({s['dur_s']:.2f}s × {px['dur_s']:.2f}s)"))
                continue
            # cada TC na taxa do SEU arquivo (o .mov de 100p convertido do proxy de 60p)
            fps_c = s.get("fps") or fps
            a = px["tc_quadros"] if px.get("tc_quadros") is not None else _tc_frames(px.get("tc"), fps)
            b = _tc_frames(s.get("tc"), fps_c)
            if a and b and not _tc_confere(a, fps, b, fps_c):
                recusados.append((c, f"timecode diferente ({s.get('tc')} × "
                                     f"{px.get('tc') or _tc_texto(a, fps)})"))
                continue
            # ⛔ O CONVERTIDO DE TC ZERADO (autor, 2026-10-31): a TL já usa o ORIGINAL (TC 10:00:00:00) e ao lado há
            # a conversão de mesmo nome e duração que perdeu o TC (00:00:00:00 ou nenhum). Sem esta prova ele passava
            # só por nome + duração e virava "original", calado — a timeline trocada pelo convertido. O zero é
            # legítimo (banco `mxf/timecode.md`) e o ffprobe não lê o TC de toda câmera, então não se recusa de saída:
            # a decisão sai depois do laço (abaixo). O DJI segue passando — lá o zero é do lado do PROJETO (o proxy),
            # e a regra só olha o projeto com TC real.
            if a and not b and not copia:
                msg = (f"o candidato tem TC {'zerado' if s.get('tc') else 'ausente'}; o do projeto, "
                       f"{px.get('tc') or _tc_texto(a, fps)}")
                # ⭐ O ORIGINAL de TC zerado com a CONVERSÃO carimbada (autor, 2026-11-22; laboratório BL08, P12): maior
                # nas DUAS medidas que o arquivo do projeto, ele não é uma conversão dele (a conversão nunca cresce — a
                # mesma regra do raster abaixo). Entra como original, COM a dúvida à vista; o menor segue como antes.
                if px.get("w") and px.get("h") and s.get("w") and s.get("h") and s["w"] > px["w"] and s["h"] > px["h"]:
                    maiores_zerados.append((c, msg + f" — maior que o arquivo do projeto ({s['w']}×{s['h']} × "
                                                     f"{px['w']}×{px['h']}): o original de câmera, confira o TC"))
                else:
                    duvidosos.append((c, msg + " (uma conversão que perdeu o TC?)"))
                continue
            # ⛔ A CONVERSÃO PARA BAIXO (autor, 2026-10-31, lab B110: o DCI_CORTE 1920 H.264 com o MESMO TC trocava a TL
            # que já usava o 4K): nome, duração e TC não separam o convertido do original de câmera — o raster separa.
            # O original nunca é menor que o arquivo que a timeline usa; com esse arquivo no disco, ele fica. Menor nas
            # DUAS medidas: o anamórfico 1440×1080 com proxy 1920×1080 e o vertical não caem aqui.
            if proxy_existe and px.get("w") and px.get("h") and s.get("w") and s.get("h") \
                    and s["w"] < px["w"] and s["h"] < px["h"]:
                recusados.append((c, f"menor que o arquivo do projeto ({s['w']}×{s['h']} × {px['w']}×{px['h']}): "
                                     "uma conversão — fica o do projeto"))
                continue
        if copia:
            recusados.append((c, "cópia do proxy (mesmo raster e codec)"))
            mesmas.append(c)
            # a prova COMPLETA pelo projeto: raster e codec (acima), a duração (as duas conhecidas) e o TC quando há
            if conferido_por == "projeto" and px.get("dur_s") and s.get("dur_s"):
                provadas.append(c)
            continue
        bons.append(c)
    # a cópia achada vale como o arquivo do projeto só se for UMA (ou cópias idênticas): duas diferentes,
    # o editor religa à mão — nunca a 1ª da lista
    if len(mesmas) > 1:
        imp = _impressao(mesmas[0])
        if imp is None or not all(_impressao(c) == imp for c in mesmas[1:]):
            mesmas = []
    realocado = mesmas[0] if mesmas and not proxy_existe else None
    copias = []
    if len(bons) > 1:
        imp = _impressao(bons[0])
        if imp is not None and all(_impressao(c) == imp for c in bons[1:]):
            copias, bons = bons[1:], bons[:1]
    imagem = None
    if len(bons) > 1 and proxy_existe:
        # ⭐⭐ EMPATE SÓ COM CONFIRMAÇÃO VISUAL (autor, 2026-11-22): o quadro do DAILY × o de cada candidato. Um bate e
        # os outros não → ele; sem essa confirmação, o empate fica para o editor — nunca decidimos sozinhos.
        escolhido, imagem = _confirmar_pela_imagem(proxy, bons, px)
        if escolhido:
            bons = [escolhido]
    # O zerado só fica quando é a ÚNICA mídia (autor, 2026-10-31, "depende do disco"): com o arquivo do projeto no disco
    # (a TL já usa o original) ele é recusado e o do projeto fica; sem ele (R04: o J: dos Sony ausente, os 1024×540
    # convertidos SEM TC são o que há — 141/143 pela referência) entra, com a `duvida` à vista (marcador "conferir").
    # Mais de um zerado sem o do projeto = empate, do editor.
    duvida = None
    trecho = None
    if not bons and not mesmas and trechos:
        # ⭐ O RENDER DA COR VOLTANDO (BL09, 2026-11-22): o Baselight grava no render o TC de FONTE e o reel do original
        # (medido: C001C003_COR.mov, 47 quadros, 17:00:02:12, reel C001C003). Mais de um original que o contenha = empate.
        if len(trechos) > 1:
            # cópias IDÊNTICAS do mesmo original (backup, os originais do BL09 copiados do BL08) valem como um só, com o
            # mesmo trecho — a regra de cima; diferentes, empate (2026-11-23: o C001C003 empatava consigo mesmo)
            imp = _impressao(trechos[0][0])
            if imp is not None and all(_impressao(c) == imp for c, _t in trechos[1:]):
                copias, trechos = [c for c, _t in trechos[1:]], trechos[:1]
        bons = [c for c, _t in trechos]
        if len(trechos) == 1:
            trecho = trechos[0][1]
    if not bons and maiores_zerados:
        bons = [c for c, _m in maiores_zerados]
        duvida = maiores_zerados[0][1]
        recusados += duvidosos
    else:
        recusados += maiores_zerados
        if bons or proxy_existe:
            recusados += duvidosos
        elif duvidosos:
            bons = [c for c, _m in duvidosos]
            duvida = duvidosos[0][1]
    if len(bons) == 1:
        estado = "original"
    elif bons:
        estado = "ambiguo"
    elif lento:
        estado = "lento"          # o disco não respondeu: nem "incompleto", nem "sem original"
    elif any("incompleto" in m for _c, m in recusados):
        estado = "incompleto"
    else:
        estado = "sem_original"
    # ⭐ UM FLUXO PARA TODO PROTOCOLO (autor, 2026-10-19): o arquivo DO PROJETO, no lugar dele, DENTRO das pastas que
    # o editor indicou é a mídia que ele apontou — "encontrado", como o master achado pelo AAF, sem o "REFAZER no
    # original" (lab O01, a B22: o AAF dizia "encontrada" e o .prproj "sem original" para o MESMO arquivo).
    # ⛔ A cópia achada noutro lugar (`realocado`) NÃO entra aqui: sem o arquivo do projeto, nada diz se ela é o
    # original ou uma cópia do proxy (PRODB: o ProRes Proxy copiado ao lado do ARRIRAW) — continua "sem original".
    if estado == "sem_original" and proxy_existe and _dentro(proxy, raizes):
        estado, bons = "proprio", [proxy]
    # ⭐ MUDOU DE LUGAR (autor, 2026-10-22, "provar e aceitar"): a cópia achada noutra pasta com a prova completa do que o
    # projeto registra (raster, codec, duração e o TC quando há) É o arquivo do projeto, só noutro caminho — vale como o
    # próprio no lugar ("encontrado"), sem marcador. Sem a prova inteira, segue `realocado` = "sem original". O original
    # de câmera achado (outro raster/codec) continua vencendo: isto só vale quando nenhum original casou.
    mudou = bool(realocado and estado == "sem_original" and realocado in provadas and _dentro(realocado, raizes))
    if mudou:
        estado, bons = "proprio", [realocado]
    return {"proxy": proxy, "estado": estado, "original": bons[0] if len(bons) == 1 else None,
            "candidatos": bons, "copias": copias, "recusados": recusados, "proxy_existe": proxy_existe,
            "conferido_por": conferido_por, **({"duvida": duvida} if duvida else {}),
            **({"por_reel": por_reel} if por_reel else {}),
            **({"trecho": trecho} if trecho and len(bons) == 1 else {}),
            **({"imagem": imagem} if imagem else {}),
            **({"lento": True} if lento else {}), **({"mudou": True} if mudou else {}),
            **({"realocado": realocado} if realocado and estado != "original" else {})}


def _trecho(px: dict, s: dict) -> dict | None:
    """O arquivo do projeto (`px`) é um TRECHO do candidato (`s`)? — o render que a cor devolve à montagem: mais curto,
    com o TC de FONTE do plano e o reel (ou o nome) do original. TC real dos dois lados (zero não prova nada) e o trecho
    inteiro DENTRO do original. `{desloc_quadros, desloc_s, motivo}` (quadros do ORIGINAL) ou None. A duração MENOR é a
    própria assinatura: o daily inteiro (a mesma duração) segue pelas provas de sempre.

    ⭐ OUTRA TAXA (BL08, 2026-11-23): o render sai na taxa da TIMELINE e o TC de fonte vem no contador cru do `tmcd`, na
    base do original (`tmcd_cru`). Vale só quando essa base é a do original — sem ela, a taxa diferente não prova nada."""
    fps, fps_c = px.get("fps"), s.get("fps")
    if not (fps and fps_c and px.get("dur_s") and s.get("dur_s")):
        return None
    t = px.get("tmcd") or {}
    mesma = abs(fps - fps_c) < 0.01
    if not mesma and not (t.get("base") and t["base"] == round(fps_c) and t.get("quadro")):
        return None
    if px["dur_s"] >= s["dur_s"] - 1.0 / fps_c:
        return None
    if mesma:                                           # a conta de sempre (BL09): rótulo × rótulo
        b = _tc_frames(s.get("tc"), fps_c)
        a = px["tc_quadros"] if px.get("tc_quadros") is not None else _tc_frames(px.get("tc"), fps)
    else:                                               # o contador do `tmcd` é CONTÍNUO: o rótulo DF do original também
        from media.matcher_masters import _tc_em_quadros
        b, a = _tc_em_quadros(s.get("tc"), fps_c), t["quadro"]
    if not a or not b or a < b or (a - b) / fps_c + px["dur_s"] > s["dur_s"] + 0.5 / fps_c:
        return None
    dur_p, dur_c = round(px["dur_s"] * fps), round(s["dur_s"] * fps_c)
    taxa = "" if mesma else f", render em {fps:.3f} de um original em {fps_c:.3f}".replace(".", ",")
    return {"desloc_quadros": a - b, "desloc_s": (a - b) / fps_c,
            "motivo": f"um trecho do original ({dur_p} de {dur_c} quadros, a partir de "
                      f"{(px.get('tc') or _tc_texto(a, fps)) if mesma else f'{a - b} quadros depois de {s.get('tc')}'}"
                      f"{taxa}): o render da cor "
                      f"voltando? — conformado no original pelo {'reel' if px.get('reel') else 'nome'} e pelo TC"}


def _tc_texto(q: int, fps: float | None) -> str:
    n = round(fps or 24)
    s, f = divmod(int(q), n)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def casar(segmentos: list[dict], raizes: list[str], progresso=None,
          indice: dict[str, list[str]] | None = None) -> dict[str, dict]:
    """{caminho do proxy: resultado} para cada arquivo distinto dos segmentos de vídeo.
    `progresso(feitos, total, atual)` a cada arquivo (é a etapa lenta: um ffprobe por candidato);
    `atual` = o proxy que está sendo casado (o painel mostra qual)."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    indice = indice if indice is not None else indexar(raizes)
    proxies = sorted({s["media_ref"]["local_path"] for s in segmentos
                      if s.get("media_ref") and not s.get("is_audio")})
    # o que o PROJETO sabe de cada proxy (a prova quando o arquivo dele não está aqui)
    projeto: dict[str, dict] = {}
    for s in segmentos:
        m = (s.get("prproj") or {}).get("midia")
        if m and s.get("media_ref") and not s.get("is_audio"):
            projeto.setdefault(s["media_ref"]["local_path"], m)
    # EM PARALELO (2026-10-04): cada proxy é independente e as sondagens são processos do ffprobe
    # esperando disco — medido no PRODB (Windows, disco quente), 28 de 30 s da análise eram 600
    # ffprobe em série. `progresso` corre na thread de quem chamou: se lança (Cancelar), as que
    # faltam são descartadas.
    feitos: dict[str, dict] = {}
    ex = ThreadPoolExecutor(max_workers=max(1, min(SONDAGENS_SIMULTANEAS, len(proxies))))
    try:
        futuros = {ex.submit(casar_um, p, indice, projeto.get(p), raizes): p for p in proxies}
        if progresso and proxies:
            progresso(0, len(proxies), proxies[0])
        for fut in as_completed(futuros):
            feitos[futuros[fut]] = fut.result()
            if progresso:
                progresso(len(feitos), len(proxies), futuros[fut])
    finally:
        ex.shutdown(wait=True, cancel_futures=True)
    # Os que esbarraram num disco lento, de novo, UM POR VEZ (sem disputa); se nem assim, o motivo
    # diz "o disco não respondeu" — nunca que o arquivo é ilegível.
    for p in [p for p in proxies if feitos[p].get("lento")]:
        feitos[p] = casar_um(p, indice, projeto.get(p), raizes)
    if progresso:
        progresso(len(proxies), len(proxies), "")
    return {p: feitos[p] for p in proxies}       # na ordem de sempre (a do nome)


#: Sondagens simultâneas (processos do ffprobe esperando disco).
#: ⭐ MEDIDO 2026-10-04 (Windows, filme de 588 planos, originais ARRIRAW num HD USB, disco frio = HDs
#: ejetados e replugados): análise em série 301 s; 4 simultâneas 267 s, nenhum estouro; 8 simultâneas
#: 233 s, mas 5 ARRIRAW passaram do limite de 60 s (refeitos em série). 4: o disco não engasga.
SONDAGENS_SIMULTANEAS = 4
