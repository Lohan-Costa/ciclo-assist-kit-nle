#!/usr/bin/env python3
"""clone_generic.py — clone AMA FORMAT-GENÉRICO (byte-surgery, via ONLINE-provada).
(Vendorizado do eng-rev `avb_clone_generic.py`.)

Compõe as peças provadas p/ clonar um clipe-template p/ um arquivo NOVO de FORMATO DIFERENTE:
  1. cadeia   (clone)             — mob_id fresco + duração + _AMA_FILE_DATE_TIME(mtime) + nome
  2. geometria(descriptor_patch)  — patch dos campos de geometria do CDCI (widths/aspect/caixas)
                                     p/ o formato do arquivo (ffprobe via video_descriptor)
  3. path     (relink)            — reescreve path_posix/utf8 (tamanho diferente + fixup de chunk)

ORDEM: size-neutral (1,2) ANTES do size-changing (3), pois 1/2 usam offsets do pyavb (object_positions)
que o passo 3 invalidaria. O passo 3 recalcula posições andando os chunks (stdlib).

VÍDEO precisa do passo 2 (resolução contínua). ÁUDIO PCM: use template do FORMATO EXATO (coding+bits+
canais) e pule o passo 2 (descriptor já casa; evita adicionar attr size-changing tipo SoundEssenceCoding).

Validado offline por golden: clone A004(1920)->B001(2048) => geometria/path/date == master B001 REAL.

USO (biblioteca): clone_generic(template_bin, clip_name, target_file, out_bin, kind="video")
"""
import os, sys, copy, math, struct, subprocess, unicodedata

from . import reader as avb_read
from . import clone as AC
from . import relink as AR
from . import offsets as O
from . import descriptor_patch as DP
from . import video_descriptor as VD
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)


def _find_timecode(f, clip_name):
    """(instance_id, start, fps) do componente Timecode na cadeia do clipe (fica num SourceMob)."""
    def pd(o): return getattr(o, "property_data", {}) or {}
    def walk(comp, d=0):
        if comp is None or d > 6: return []
        r = [comp] if type(comp).__name__ == "Timecode" else []
        for c in pd(comp).get("components", []): r += walk(c, d + 1)
        for t in pd(comp).get("tracks", []): r += walk(pd(t).get("component"), d + 1)
        return r
    for m in f.content.mobs:
        if (pd(m).get("name") or "") != clip_name: continue
        for t in pd(m).get("tracks", []):
            for tc in walk(pd(t).get("component")):
                return tc.instance_id, pd(tc).get("start"), pd(tc).get("fps")
    return None, None, None


def _find_audio_start(f, clip_name):
    """(start_time, edit_rate, [sclp_iids]) do TC de áudio. O TC mora nos SourceClips da ESSÊNCIA
    (SourceMob, mob_type_id==3) com start_time NÃO-ZERO — NÃO no master (start_time=0). Varre TODOS
    os mobs do clipe e pega o start NÃO-ZERO (o TC) + os iids das SCLPs que o têm (p/ patch preciso)."""
    def pd(o): return getattr(o, "property_data", {}) or {}
    scs = []
    def walk(c, d=0):
        if c is None or d > 7: return
        if type(c).__name__ == "SourceClip" and pd(c).get("start_time"):   # não-zero = o TC (essência)
            scs.append(c)
        for x in pd(c).get("components", []): walk(x, d + 1)
        for t in pd(c).get("tracks", []): walk(pd(t).get("component"), d + 1)
    # ⭐ O TC mora nos SourceClips do mob da ESSÊNCIA (o do PCMADescriptor) — medido nos 13 moldes (2026-10-28). Dois
    # moldes (WAV 24 bits estéreo, AIFF 16 bits) têm o start ZERO ali, e a busca por "não-zero" não os achava: um WAV
    # com TC nesses formatos ficava em 00:00:00:00. Pelo mob, o start zero também vale.
    for m in f.content.mobs:
        if (pd(m).get("name") or "") != clip_name or type(pd(m).get("descriptor")).__name__ != "PCMADescriptor":
            continue
        for t in pd(m).get("tracks", []):
            c = pd(t).get("component")
            if type(c).__name__ == "SourceClip":
                scs.append(c)
            for x in pd(c).get("components", []) if c is not None else []:
                if type(x).__name__ == "SourceClip":
                    scs.append(x)
    if scs:
        st = int(pd(scs[0]).get("start_time") or 0)
        er = float(pd(scs[0]).get("edit_rate") or 24)
        return st, er, [c.instance_id for c in scs if int(pd(c).get("start_time") or 0) == st]
    for m in f.content.mobs:
        if (pd(m).get("name") or "") != clip_name:
            continue
        for t in pd(m).get("tracks", []):
            walk(pd(t).get("component"))
    if not scs:
        return None, None, []
    st = pd(scs[0]).get("start_time")
    er = float(pd(scs[0]).get("edit_rate") or 24)
    iids = [c.instance_id for c in scs if pd(c).get("start_time") == st]
    return st, er, iids


def _own_track_sourceclips(mob):
    """[(instance_id, length, edit_rate), ...] dos SourceClip FILHOS DIRETOS das próprias tracks de
    `mob` (não desce noutros mobs). Usado p/ achar/patchear a duração da essência embutida (ex.: áudio
    MPGA dentro de um clipe de vídeo) sem se confundir com a duração do MASTER (mob diferente)."""
    def pd(o): return getattr(o, "property_data", {}) or {}
    out = []
    for t in pd(mob).get("tracks", []):
        c = pd(t).get("component")
        for x in pd(c).get("components", []) or []:
            if type(x).__name__ == "SourceClip":
                out.append((x.instance_id, x.property_data.get("length"), float(x.property_data.get("edit_rate") or 0)))
    return out


def _inicio_exato_bwf(path, edit_rate):
    """O início do áudio em quadros do projeto, FRACIONÁRIO (o pulldown não cai em quadro inteiro), a partir do
    `time_reference` do bext. None sem time_reference. Ver `_probe_bwf_start` e `tempos_do_audio`."""
    try:
        o = __import__("json").loads(subprocess.check_output([fftools.ffprobe_exe(), "-v", "error", "-select_streams",
             "a:0", "-show_entries", "format_tags=time_reference:stream=sample_rate", "-of", "json", path]).decode())
        tr = (o.get("format", {}).get("tags", {}) or {}).get("time_reference")
        sr = float(o["streams"][0]["sample_rate"])
        if tr and str(tr).isdigit():
            nominal = int(round(edit_rate))
            tc_frames = round(int(tr) / sr * nominal)          # TC nominal (24)
            # pulldown p/ frames ACTUAL: NTSC (23.976/29.97) usa 1000/1001 EXATO (não edit_rate arredondado)
            factor = 1000.0 / 1001.0 if abs(edit_rate - nominal) > 0.005 else 1.0
            return tc_frames * factor
    except Exception:
        pass
    return None


def _probe_bwf_start(path, edit_rate):
    """start_time do ÁUDIO (= o que o Avid armazena) a partir do BWF bext time_reference (samples desde
    meia-noite): TC nominal @ round(edit_rate) frames, depois pulldown p/ o edit_rate ACTUAL, e o PISO.
    Ex 23.976: nominal=24, pulldown 24->23.976 = /1.001. None se o arquivo não tiver time_reference.

    ⛔ PISO, não arredondamento (CORRIGE, 2026-10-31, MC 2024.6, gabaritos do próprio MC): 01:00:08:00 a 29,97 dá
    108131,87 quadros e o MC grava **108131**; o `round` dava 108132. A 23,976 a fração era ,49 e os dois coincidiam —
    por isso "validada em 4 clipes" passava. O banco já tinha a prova sem saber: 10:00:00 a 23,98 → `09:59:24:00`
    (863136,86 → piso)."""
    ini = _inicio_exato_bwf(path, edit_rate)
    return None if ini is None else int(math.floor(ini + 1e-6))


def tempos_do_audio(path, edit_rate, amostras, taxa_amostras):
    """(start_time, duração do master) como o MC os grava, em quadros do projeto.

    A duração é a dos quadros que o som TOCA: teto(início exato + duração) − piso(início exato). MEDIDO (2026-10-31,
    MC 2024.6, o mesmo WAV de 8 s com TC 01:00:08:00 linkado em 5 projetos): 23,976 → 193 (191,8 de duração, mas o
    início cai em ,49 e o som alcança 193 quadros) · 24 → 192 · 25 → 200 · 29,97 NDF e DF → 241. ⭐ Isto explica o
    "às vezes ceil, às vezes ceil+1" que o banco não fechava (56 masters de um projeto real, 2026-08-16)."""
    nominal = int(round(edit_rate))
    exata = nominal * 1000.0 / 1001.0 if abs(edit_rate - nominal) > 0.005 else float(edit_rate)
    ini = _inicio_exato_bwf(path, edit_rate) or 0.0
    start = int(math.floor(ini + 1e-6))
    fim = ini + amostras / float(taxa_amostras) * exata
    return start, max(1, int(math.ceil(fim - 1e-6)) - start)


def _tc_to_frames(tcstr, fps):
    p = [int(x) for x in tcstr.replace(";", ":").split(":")]
    h, m, s, fr = (p + [0, 0, 0, 0])[:4]
    return (h * 3600 + m * 60 + s) * fps + fr


def _xmp_tc(path):
    """(quadros na base do XMP, base) do `xmpDM:startTimecode`; None sem XMP."""
    import re
    try:
        with open(path, "rb") as fh:
            b = fh.read(8 * 1024 * 1024)
        i = b.find(b"startTimecode")
        if i < 0:
            return None
        trecho = b[i:i + 400].decode("latin-1")
        fmt = re.search(r'timeFormat="?>?(\d+)', trecho) or re.search(r"timeFormat>(\d+)", trecho)
        val = re.search(r'timeValue="([\d:;]+)"', trecho) or re.search(r"timeValue>([\d:;]+)<", trecho)
        if not val or not fmt:
            return None
        base = int(fmt.group(1))
        if base > 1000:                                     # "2997DropTimecode", "23976Timecode", "5994…"
            base = int(round(base / (1000 if base > 10000 else 100)))
        p = [int(x) for x in val.group(1).replace(";", ":").split(":")]
        h, m, s, fr = (p + [0, 0, 0, 0])[:4]
        return (h * 3600 + m * 60 + s) * base + fr, base
    except Exception:
        return None


def _fase_do_tc(path, tc_fps):
    """Em que quadro do PAR (ou trio…) o arquivo começa, quando a taxa do XMP passa de 30 (50/60p).
    ⭐ Medido 20/20 (MP4 60p do PRODC, TC da bin em base 30, MC 24.6, 2026-10-18): quadro 60 PAR → a essência começa
    em 4; ÍMPAR → em 3 (e o áudio, 3 antes). 0 sem XMP ou até 30 qps."""
    x = _xmp_tc(path)
    if not x:
        return 0
    # o TC do Avid conta até 30: acima disso (50/60p) o quadro vai aos PARES — e a trilha de TC da bin está a 60
    # (medido), então a razão não sai dela
    k = int(round(x[1] / 30)) if x[1] > 30 else 1
    return x[0] % k if k > 1 else 0


def _sclps_com_inicio(mob):
    """[(instance_id, length, start_time)] dos SourceClip das próprias tracks de `mob`."""
    out = []
    for t in (getattr(mob, "property_data", {}) or {}).get("tracks", []) or []:
        c = t.property_data.get("component")
        for x in (c.property_data.get("components", []) if c is not None else []) or []:
            if type(x).__name__ == "SourceClip":
                out.append((x.instance_id, x.property_data.get("length"), x.property_data.get("start_time")))
    return out


def _campos_sclp(template_bin, iid, length):
    """Deslocamentos (no objeto) do `length` (u32) e do `start_time` (s32 logo depois do track_id s16) de um
    SourceClip — pelo log de leitura do pyavb, não por valor (o start 1 casaria com qualquer campo)."""
    log = O.map_object(template_bin, iid)
    off_len = next((e["off"] for e in log if e["kind"] == "read_u32le" and e["value"] == length and e["off"] > 30),
                   None)
    if off_len is None:
        return None, None
    depois = [e for e in log if e["off"] > off_len]
    for a, b in zip(depois, depois[1:]):
        if a["kind"] == "read_s16le" and b["kind"] == "read_s32le":
            return off_len, b["off"]
    return off_len, None


def _tc_do_xmp(path, fps):
    """`xmpDM:startTimecode` do XMP embutido (MP4 de câmera sem `tmcd`: o MC tira o TC DAQUI — medido no MC 24.6,
    2026-10-18, MP4 H.264 60p do PRODC: XMP 15:30:14:10 a 60 = Start 15:30:14:05 na coluna, que mostra 60p em base 30).
    Em frames na base `fps` do componente Timecode da bin. None sem XMP."""
    x = _xmp_tc(path)
    if not x:
        return None
    q, base = x
    seg, fr = divmod(q, base)
    return int(seg * fps + (fr * fps) // base)          # trunca: o 60p ímpar é a 2ª metade do quadro 30 (".")


def _probe_tc_cru(path, fps, unidade_xmp=None):
    """TC de início do arquivo, em frames, SEM desconto: o `timecode` do ffprobe (tmcd) e, sem ele, o do XMP — este
    na `unidade_xmp` (a taxa de EDIÇÃO do componente Timecode: no MP4 60p do PRODC o `fps` dele é 30, a base de
    exibição, e ele conta a 60). None sem timecode embutido."""
    try:
        o = subprocess.check_output([fftools.ffprobe_exe(), "-v", "error", "-show_entries",
             "format_tags=timecode:stream_tags=timecode", "-of", "default=nw=1:nk=1", path]).decode()
        tc = o.strip().split("\n")[0].strip()
        return _tc_to_frames(tc, fps) if tc else _tc_do_xmp(path, unidade_xmp or fps)
    except Exception:
        return None


def _quadros_como_o_mc(path):
    """A duração que o MC dá a um arquivo com áudio MPEG embutido: o stream MAIS LONGO, em quadros do vídeo
    (medido 20/20 no MC 24.6, 2026-10-18, MP4 H.264 60p + AAC do PRODC: ⌈pacotes × 1024 / 48000 × 60⌉ quando o AAC é
    mais longo — 981 para 979 quadros de vídeo). None se não souber (o chamador cai no `frame_count`)."""
    import math
    from fractions import Fraction

    def sonda(sel, ent):
        return subprocess.run([fftools.ffprobe_exe(), "-v", "error", "-select_streams", sel, "-show_entries", ent,
                               "-of", "default=nw=1", path], capture_output=True, text=True).stdout
    try:
        v = dict(x.split("=", 1) for x in sonda("v:0", "stream=nb_frames,r_frame_rate,avg_frame_rate,time_base").split()
                 if "=" in x)
        a = dict(x.split("=", 1) for x in sonda("a:0", "stream=nb_frames,codec_name,sample_rate").split() if "=" in x)
        quadros, taxa = int(v["nb_frames"]), Fraction(*VD._video_rate(v))   # por votação (B074)
        por_pacote = {"aac": 1024, "mp3": 1152, "mp2": 1152}.get(a.get("codec_name", ""))
        if not por_pacote or not a.get("nb_frames", "").isdigit():
            return quadros
        amostras = int(a["nb_frames"]) * por_pacote
        return max(quadros, math.ceil(Fraction(amostras, int(a["sample_rate"])) * taxa))
    except Exception:
        return None


def _probe_start_tc(path, fps, desconto=-2, unidade_xmp=None):
    """TC de início do arquivo -> frames no formato do Avid (= ffprobe_TC + `desconto`).

    ⚠️ O −2 do padrão foi medido num corpus H.264 (MP4 de câmera) e NÃO é universal: nos .mov H.264 25p do PRODUCAO-C (MC 24.6, Windows, 2026-10-18) o MC grava o TC do ffprobe sem desconto — o −2 deixou os 12 clones
    2 quadros adiantados. Quem tem o molde calibra o desconto por ele (`clone_generic`)."""
    cru = _probe_tc_cru(path, fps, unidade_xmp)
    return cru + desconto if cru is not None else None


def _amostras_do_audio(path):
    """Amostras do 1º stream de áudio (PCM: nb_frames = amostras; BRAW in24 conferido: 319 quadros → 638638).
    None se o ffprobe não souber."""
    try:
        o = subprocess.check_output([fftools.ffprobe_exe(), "-v", "error", "-select_streams", "a:0",
             "-show_entries", "stream=nb_frames,codec_name", "-of", "default=nw=1", path]).decode()
        d = dict(x.split("=", 1) for x in o.split() if "=" in x)
        if not d.get("codec_name", "").startswith("pcm"):       # AAC/MP3: nb_frames são pacotes, não amostras
            return None
        n = d.get("nb_frames", "")
        return int(n) if n.isdigit() and int(n) > 0 else None
    except Exception:
        return None


def _tags_do_arquivo(path):
    """`format_tags` do ffprobe, com a chave em minúsculas ({} se não ler)."""
    import json
    try:
        o = subprocess.check_output([fftools.ffprobe_exe(), "-v", "error", "-show_entries", "format_tags",
                                     "-of", "json", path]).decode("utf-8", "replace")
        return {k.lower(): str(v) for k, v in (json.loads(o).get("format", {}).get("tags") or {}).items()}
    except Exception:
        return {}


def _metadados_da_camera(raw, user, tpl_file, target_file):
    """Colunas do `_USER` do master que o plugin AMA tirou do ARQUIVO (BRAW: Clip Number, Reel Name, Date Recorded =
    as tags `clip_number`, `reel_name`, `date_recorded` — MC 24.6, 2026-10-18). Clonadas, ficariam as do molde.
    Só troca a coluna cujo valor no molde é IGUAL à tag do arquivo do molde (a prova de que veio dele); o par
    `<u16>chave<u16>valor` inteiro é a agulha, para um valor curto ("2") não casar com outro campo. Size-changing."""
    if not user or not tpl_file or not os.path.isfile(tpl_file):
        return raw, 0
    t_tpl, t_alvo = _tags_do_arquivo(tpl_file), _tags_do_arquivo(target_file)
    n = 0
    for k, v in user.items():
        if not isinstance(v, str):
            continue
        tag = k.lower().replace(" ", "_")
        novo = t_alvo.get(tag)
        if t_tpl.get(tag) != v or novo is None or novo == v:
            continue
        kb, vb, nb = k.encode("latin-1", "replace"), v.encode("latin-1", "replace"), novo.encode("latin-1", "replace")
        agulha = struct.pack("<H", len(kb)) + kb + struct.pack("<H", len(vb)) + vb
        troca = struct.pack("<H", len(kb)) + kb + struct.pack("<H", len(nb)) + nb
        d = bytearray(raw)
        edits = []
        for pos, _cid, size in AR.walk_chunks(d):
            cdata = bytes(d[pos + 8:pos + 8 + size])
            if agulha in cdata:
                nd = cdata.replace(agulha, troca)
                edits.append((pos, size, bytes(d[pos:pos + 4]) + struct.pack("<I", len(nd)) + nd))
        for pos, size, chunk in sorted(edits, key=lambda e: -e[0]):
            d[pos:pos + 8 + size] = chunk
        raw = d
        n += len(edits)
    return raw, n


def _forma_avid(caminho):
    r"""`D:\A\B` → `D//A/B`, a forma que o MC grava no `WinFileLocator` (size-neutral)."""
    if len(caminho) > 2 and caminho[1] == ":" and caminho[2] in "\\/":
        return caminho[0] + "//" + caminho[3:].replace("\\", "/")
    return caminho.replace("\\", "/")


def _do_avid(caminho):
    r"""`D//A/B` → `D:\A\B` (o arquivo do molde, para o ffprobe)."""
    if len(caminho) > 2 and caminho[1:3] == "//":
        return caminho[0] + ":\\" + caminho[3:].replace("/", "\\")
    return caminho


def _relink_win(raw, velho, novo):
    """Troca o caminho de um `WinFileLocator` (molde linkado no Windows): os campos `path` e `path_utf8`
    (este com o prefixo `\\0\\0`) são strings u16-prefixadas; `replace_field` corrige o tamanho do chunk.
    O `AR.relink` não serve: ele só conhece o `MacFileLocator` (`path_posix`)."""
    n = 0
    for pre in (b"", b"\x00\x00"):
        raw, k = AR.replace_field(bytes(raw), pre + velho.encode("utf-8"), pre + novo.encode("utf-8"))
        n += k
    return bytearray(raw), n


def _uid_novo(raw, uid):
    """`Bin.uid` novo nos bytes — sempre (banco avb/escrita.md: o uid do molde, com a bin do molde ABERTA no MC,
    faz o `OpenBin` do clone cair em FILE_OPEN_FAILURE). O MC 24.6 grava o uid em DOIS objetos (2026-10-18)."""
    import random
    velho = struct.pack("<Q", uid)
    return bytearray(bytes(raw).replace(velho, struct.pack("<Q", random.getrandbits(63))))


def _target_geometry(tpl_pd, meta, ext):
    """property_data-alvo (só geometria) via o gerador de produção video_descriptor, sobre um shim."""
    class Shim:
        def __init__(s, pd): s.property_data = pd
    sp = {k: ([list(p) if isinstance(p, list) else p for p in v] if isinstance(v, list) else v)
          for k, v in tpl_pd.items() if k not in ("attributes", "locator", "physical_media", "uuid")}
    sh = Shim(copy.deepcopy(sp))
    sh.property_data["attributes"] = {"_SD_AVC_SUB_DESCRIPTOR": {"ATN_AVCLevel": 40, "ATN_AVCProfile": 100}}
    VD.patch_cdci_geometry(sh, meta, ext=ext)
    return sh.property_data


def _audio_samples(path):
    """(nº de samples, sample_rate) do stream de áudio. samples = descriptor.length no PCMA AMA
    (duration_ts em time_base 1/sample_rate; fallback nb_samples / duração×rate)."""
    o = subprocess.check_output([fftools.ffprobe_exe(), "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=duration_ts,nb_samples,duration,sample_rate", "-of", "json", path]).decode()
    s = __import__("json").loads(o)["streams"][0]
    sr = float(s["sample_rate"])
    for k in ("duration_ts", "nb_samples"):
        v = s.get(k)
        if v and str(v).isdigit() and int(v) > 0:
            return int(v), sr
    return int(round(float(s["duration"]) * sr)), sr


def _clone_audio_chain(raw, pos, info, target_file, tpl_desc_len, tpl_start=None, edit_rate=24.0,
                       template_bin=None, sclp_iids=None, tpl_sr=48000.0, master_len_min=None):
    """cadeia de ÁUDIO (byte-surgery): mob_id fresco + DOIS lengths (master em frames@timeline +
    descriptor em SAMPLES) + _AMA_FILE_DATE_TIME + start_time (TC da fonte, do BWF por-arquivo).
    master_len = frames@timeline do arquivo. O ratio do template (info_len/tpl_desc_len) = fps/tpl_sr;
    corrige-se pela taxa REAL do arquivo (× tpl_sr/target_sr) — senão um 44.1kHz clonado de template
    48kHz fica CURTO (~9%) e a timeline pede além do fim -> PMM_INSUFFICIENT_MEDIA nos cortes.
    Retorna (samples, target_sr)."""
    import math
    samples, target_sr = _audio_samples(target_file)
    ratio = (info["length"] / tpl_desc_len) if tpl_desc_len else 0
    # CEIL (não round): o master deve cobrir o último frame PARCIAL do arquivo — senão a timeline
    # (que edita nesse frame) pede 1 frame além do master -> PMM no corte. A essência tem o frame parcial.
    master_len = int(math.ceil(samples * ratio * (tpl_sr / target_sr))) if ratio else info["length"]
    # ⛔ A RAZÃO do molde carrega o quadro de guarda do MC: o `semcena` (1 s = 25 quadros a 23,976, não 24) punha 4 %
    # a mais em todo WAV (uma música de 3 min ~7 s além do arquivo; 2026-10-28). Com a taxa do molde, a conta é a do
    # tempo: amostras ÷ taxa × quadros por segundo (o 23,976 do pyavb volta a 24000/1001).
    # ⛔ B001 (2026-10-31): a taxa é a do PROJETO (`edit_rate`, que o chamador passa como `fps`), nunca a do molde —
    # os moldes embarcados são todos de 23,976, e um projeto a 25 recebia 192 quadros no lugar de 200, calado.
    # E a duração conta os quadros que o som toca a partir do início FRACIONÁRIO (`tempos_do_audio`).
    if edit_rate and edit_rate > 0:
        _st, master_len = tempos_do_audio(target_file, edit_rate, samples, target_sr)
    # ⭐ `master_len_min` = o maior `start+length` que a TIMELINE pede deste master.
    # O Avid NÃO declara a duração do master por uma fórmula fixa: medido em 56 masters de
    # um projeto real (2026-08-16), `ceil(real)` explica 33, `ceil(real)+1` explica 4 e 16
    # não casam com nenhuma candidata — ele às vezes conta um frame de guarda, preenchido
    # com silêncio. Perseguir a fórmula seria adivinhar; usar o que a timeline PEDE é
    # exato, e reproduz a declaração contra a qual o editor cortou.
    # ⚠️ Isto NÃO muda nenhum frame da edição: start, duração e conteúdo de cada corte
    # ficam idênticos. O único campo que muda é a duração DECLARADA do master.
    if master_len_min and master_len_min > master_len:
        master_len = int(master_len_min)
    mt = int(os.stat(target_file).st_mtime)
    rngs = AC.ranges_for(pos, bytes(raw), info["indices"])
    # mob_id fresco: master+essências+físico de áudio COMPARTILHAM o material (bytes[16:32]), diferindo
    # só na instância (bytes[12:16]) -> trocar cada material DISTINTO 1x (região global pega a família toda).
    seen = set()
    for blle in info["mobids"]:
        material = bytes(blle[16:32])
        if material in seen:
            continue
        seen.add(material)
        r_old, r_new = AC.region(material), AC.region(os.urandom(16))
        if raw.count(r_old):
            raw[:] = raw.replace(r_old, r_new)
    # só onde o valor É o campo (B067): no molde de 1 s as 48000 amostras são também a TAXA e a duração 25 uma referência
    prova = (lambda v, nomes: AC.campos_provados(template_bin, info["indices"], v, nomes)) if template_bin else \
        (lambda v, nomes: None)
    AC.scoped_replace_u32(raw, rngs, info["length"], master_len, prova(info["length"], {"length"}))  # master/tracks
    AC.scoped_replace_u32(raw, rngs, tpl_desc_len, samples,                                      # descriptor (samples)
                          prova(tpl_desc_len, {"length", "_SAVED_AAF_AUDIO_LENGTH"}))
    AC.scoped_replace_u32(raw, rngs, info["date"], mt, prova(info["date"], {"_AMA_FILE_DATE_TIME"}))
    # start_time (TC da fonte) = SourceClip.start_time. O scoped_replace COLIDE com object-refs de mesmo
    # valor -> patch PRECISO, só nos offsets PROVADOS de `start_time` (B067). ⭐ Sempre (autor, 2026-10-28; antes só com
    # AVB_AUDIO_TC=1): o TC do BWF do arquivo; SEM TC, zero — medido no MC 25.12: um WAV sem bext ligado pelo próprio
    # MC sai com Start 00:00:00:00. Antes o master ficava com o start do MOLDE (09:59:24:00 num WAV sem TC).
    new_start = None
    if tpl_start is not None and template_bin and sclp_iids:
        new_start = _probe_bwf_start(target_file, edit_rate)
        if new_start is None:
            new_start = 0
        if new_start != tpl_start:
            for off in AC.campos_provados(template_bin, set(sclp_iids), tpl_start, {"start_time"}):
                struct.pack_into("<i", raw, off, new_start)
    print("  [audio] samples=%d sr=%.0f master_len=%d date=%d start=%s" % (samples, target_sr, master_len, mt, new_start))
    return samples, target_sr, master_len


#: a fonte de MÍDIA (WAV sem cena) de todo áudio linkado: um `Timecode` de 10.800.000 quadros e, nas trilhas, um
#: clipe de 48 h + a duração do master seguido de filler até completar. MEDIDO em 2026-10-31 (MC 2024.6, o mesmo WAV
#: em projetos 23,976 · 24 · 25 · 29,97 NDF/DF): 4143250 · 4147392 · 4320200 · 5179062 = arred(172800 s × taxa) + master.
DURACAO_DA_FONTE_DE_MIDIA = 10_800_000
SEGUNDOS_ANTES_DO_CLIPE = 172_800


def _exp10_do_mc(er):
    """A taxa como o MC a grava (mantissa s32, expoente s16). MEDIDO (2026-10-31): 23,976 → 23976e-3 · 24 → 24e0 ·
    25 → 25e0 · 29,97 → 2997e-2. ⏳ 47,952, 59,94 e as inteiras acima de 30 seguem a mesma forma, sem gabarito."""
    nominal = int(round(er))
    if abs(er - nominal) <= 0.005:
        return nominal, 0
    if nominal == 24:
        return 23976, -3
    return int(round(nominal * 1000 / 1001 * 100)), -2


def _taxa_exata(er):
    nominal = int(round(er))
    return nominal * 1000.0 / 1001.0 if abs(er - nominal) > 0.005 else float(er)


def _cadeia_de_audio(template_bin, clip_name):
    """[(instance_id, papel, classe)] do mob e de cada componente do master, da fonte de arquivo (PCMA) e da fonte de
    MÍDIA do clipe. A fonte de TAPE (WAV com cena) fica de fora: ela traz o TC do GRAVADOR (o molde de cena tem 30
    quadros num projeto 23,976) — ⏳ pendente de gabarito com um WAV de cena em outra taxa."""
    out = []
    with avb_read.topen(template_bin) as f:
        for m in f.content.mobs:
            pd = m.property_data
            if (pd.get("name") or "") != clip_name:
                continue
            d = pd.get("descriptor")
            papel = "master" if pd.get("mob_type_id") == 2 else (type(d).__name__ if d is not None else "?")
            if papel not in ("master", "PCMADescriptor", "MediaDescriptor"):
                continue
            out.append((m.instance_id, papel, type(m).__name__))
            for t in pd.get("tracks") or []:
                c = t.property_data.get("component")
                if c is None:
                    continue
                out.append((c.instance_id, papel, type(c).__name__))
                if type(c).__name__ == "Sequence":
                    for x in c.property_data.get("components") or []:
                        out.append((x.instance_id, papel, type(x).__name__))
    vistos, unicos = set(), []
    for item in out:
        if item[0] not in vistos:
            vistos.add(item[0]); unicos.append(item)
    return unicos


def _patch_taxa_da_cadeia(raw, template_bin, pos, clip_name, er, master_len, tpl_master_len, drop=False):
    """⛔ B001 no AVB de áudio (2026-10-31): escreve a TAXA DO PROJETO em todo componente da cadeia, e o que depende
    dela na fonte de mídia (o `Timecode` e o clipe de 48 h). Antes, só o start usava o `fps`: num projeto 25 o master
    saía a 23,976 com 192 quadros (o MC grava 200), e a fonte de mídia, com a duração do MOLDE. Size-neutral, pelos
    offsets do molde — então ANTES da troca de nome. Devolve quantos campos mudou."""
    nominal = int(round(er))
    mant, exp = _exp10_do_mc(er)
    n = 0
    cadeia = _cadeia_de_audio(template_bin, clip_name)
    with avb_read.topen(template_bin) as f:
        objs = {iid: f.read_object(iid).property_data for iid, _p, _c in cadeia}
        tpl_er = next((float(v.get("edit_rate")) for v in objs.values() if v.get("edit_rate")), None)
    for iid, papel, classe in cadeia:
        log = O.map_object(template_bin, iid)
        base = pos[iid] + 8
        par = next((i for i in range(len(log) - 1) if log[i]["kind"] == "read_s32le"
                    and log[i + 1]["kind"] == "read_s16le" and log[i + 1]["off"] == log[i]["off"] + 4), None)
        if par is not None and objs[iid].get("edit_rate") is not None:
            struct.pack_into("<i", raw, base + log[par]["off"], mant)
            struct.pack_into("<h", raw, base + log[par]["off"] + 4, exp)
            n += 1
        if papel == "MediaDescriptor" and classe == "Timecode":
            # o fps é o ÚLTIMO u16 (flags u32 → fps u16 → 6 bytes → start); os u16 de antes são os tamanhos das
            # strings do Component (0xFFFF = sem nome) — o primeiro u16 pegava um deles
            u16 = next((i for i in range(len(log) - 1, 0, -1) if log[i]["kind"] == "read_u16le"), None)
            if u16 is None or log[u16 - 1]["kind"] != "read_u32le":
                raise RuntimeError("molde: não achei fps/flags no Timecode da fonte de mídia")
            struct.pack_into("<H", raw, base + log[u16]["off"], nominal)
            struct.pack_into("<I", raw, base + log[u16 - 1]["off"], 1 if drop else 0)
            n += 2
    # o clipe de 48 h e o filler da fonte de mídia: o valor do molde tem de bater com a regra, senão não se adivinha
    if tpl_er:
        antes_clip = int(round(SEGUNDOS_ANTES_DO_CLIPE * _taxa_exata(tpl_er))) + int(tpl_master_len)
        novo_clip = int(round(SEGUNDOS_ANTES_DO_CLIPE * _taxa_exata(er))) + int(master_len)
        midia = {iid for iid, papel, classe in cadeia if papel == "MediaDescriptor" and classe in ("SourceClip", "Filler")}
        clips = {iid for iid in midia if objs[iid].get("length") == antes_clip}
        fillers = {iid for iid in midia if objs[iid].get("length") == DURACAO_DA_FONTE_DE_MIDIA - antes_clip}
        if midia and not clips:
            raise RuntimeError(f"molde: a fonte de mídia não segue a regra das 48 h (esperava {antes_clip})")
        for alvo, velho, novo in ((clips, antes_clip, novo_clip),
                                  (fillers, DURACAO_DA_FONTE_DE_MIDIA - antes_clip, DURACAO_DA_FONTE_DE_MIDIA - novo_clip)):
            if alvo and velho != novo:
                for off in AC.campos_provados(template_bin, alvo, velho, {"length"}):
                    struct.pack_into("<I", raw, off, novo); n += 1
    return n


def conferir_taxa_do_audio(out_bin, nome, er, master_len, start=None, drop=False):
    """A PROVA: relê a bin gravada e confere, campo a campo, a regra dos gabaritos do MC. Lista vazia = igual ao MC."""
    nominal = int(round(er))
    erros = []
    with avb_read.topen(out_bin) as f:
        # ⏳ Com TAPE (WAV de cena) a fonte de arquivo NÃO tem a duração do master: no molde de 2 canais com cena
        # (do MC) o master tem 3181 e a fonte de arquivo 3180, e sem gabarito de cena em outra taxa a regra não se
        # sabe. Ali a prova confere taxa, master e start — a duração da fonte de arquivo fica de fora, DITO.
        com_tape = any(type(m.property_data.get("descriptor")).__name__ == "TapeDescriptor"
                       for m in f.content.mobs)
        for m in f.content.mobs:
            pd = m.property_data
            if (pd.get("name") or "") != nome:
                continue
            d = pd.get("descriptor")
            papel = "master" if pd.get("mob_type_id") == 2 else (type(d).__name__ if d is not None else "?")
            if papel not in ("master", "PCMADescriptor", "MediaDescriptor"):
                continue
            comps = []
            for t in pd.get("tracks") or []:
                c = t.property_data.get("component")
                comps += [c] + (list(c.property_data.get("components") or []) if type(c).__name__ == "Sequence" else [])
            for c in [m] + comps:
                e = c.property_data.get("edit_rate")
                if e is not None and abs(float(e) - er) > 0.002:
                    erros.append(f"{papel} {type(c).__name__}: edit_rate {e} (projeto {er})")
            for c in comps:
                cp = c.property_data
                if type(c).__name__ == "SourceClip" and (papel == "master" or (papel == "PCMADescriptor" and not com_tape)) \
                        and cp.get("length") != master_len:
                    erros.append(f"{papel} SourceClip: length {cp.get('length')} (esperado {master_len})")
                if type(c).__name__ == "SourceClip" and papel == "PCMADescriptor" and start is not None \
                        and cp.get("start_time") != start:
                    erros.append(f"PCMA SourceClip: start {cp.get('start_time')} (esperado {start})")
                if type(c).__name__ == "Timecode" and papel == "MediaDescriptor":
                    if cp.get("fps") != nominal or int(cp.get("flags") or 0) != (1 if drop else 0):
                        erros.append(f"Timecode da fonte: fps {cp.get('fps')} flags {cp.get('flags')}")
                if type(c).__name__ == "SourceClip" and papel == "MediaDescriptor":
                    esperado = int(round(SEGUNDOS_ANTES_DO_CLIPE * _taxa_exata(er))) + master_len
                    if cp.get("length") != esperado:
                        erros.append(f"fonte de mídia: clipe {cp.get('length')} (esperado {esperado})")
    return erros


def _patch_pcma_rate(raw, template_bin, iid, base, pcma_pd, target_sr):
    """byte-patch da TAXA no descriptor PCMA (size-neutral): sample_rate + edit_rate (mantissas exp10
    = s32le) e average_bps (u32le = block_align × sr). Necessário quando o arquivo tem taxa ≠ do
    template (ex.: 44.1kHz clonado de template 48kHz) — senão a duração da essência fica errada."""
    tpl_sr = int(round(float(pcma_pd.get("sample_rate") or 0)))
    if not tpl_sr or int(round(target_sr)) == tpl_sr:
        return 0
    log = O.map_object(template_bin, iid)
    n = 0
    for off in O.find_field(log, tpl_sr, kind="read_s32le"):        # sample_rate + edit_rate (mantissas)
        struct.pack_into("<i", raw, base + off, int(round(target_sr))); n += 1
    tpl_avg = int(pcma_pd.get("average_bps") or 0)
    ba = int(pcma_pd.get("block_align") or 0)
    if tpl_avg and ba:
        for off in O.find_field(log, tpl_avg, kind="read_u32le"):    # average_bps = block_align × sr
            struct.pack_into("<I", raw, base + off, ba * int(round(target_sr))); n += 1
    return n


def clone_generic(template_bin, clip_name, target_file, out_bin, kind="video", fps=None, drop=False,
                  master_len_min=None, mesma_geometria=False):
    """Clona `clip_name` do template p/ `target_file` (formato diferente) em `out_bin`. Retorna resumo.

    `fps` = edit_rate da TIMELINE de destino. ⚠️ **Passe sempre que souber.** Sem ele a
    taxa vem do TEMPLATE (`_find_audio_start`), e os 8 templates de áudio embarcados têm
    **23,976 gravado**: num projeto a 25 ou 29,97 o master de áudio sai contando na base
    errada — duração e start_time deslocados, **em silêncio**. O `clone_offline` ao lado já
    aceitava `fps` com a nota "preferir sempre"; aqui faltava. (Medido 2026-08-16.)
    """
    want_cls = "PCMADescriptor" if kind == "audio" else "CDCIDescriptor"
    with avb_read.topen(template_bin) as f:
        pos = list(f.object_positions)
        info = AC.clip_info(f, clip_name)
        cdci = old_path = win_path = pcma_len = None
        bin_uid = f.content.uid
        mpga = None                                                # vídeo: áudio MPEG embutido (se houver)
        multi_pcma = []                                            # vídeo: PCM dentro de um MultiDescriptor
        multi_video = []                                           # vídeo: RGBA/CDCI dentro de um MultiDescriptor
        essencias = []                                             # vídeo: SourceClips das fontes (len, início)
        user = {}                                                  # _USER do master (metadados da câmera)
        for m in f.content.mobs:
            if (m.property_data.get("name") or "") != clip_name:
                continue
            d = m.property_data.get("descriptor")
            if d is None and kind != "audio":
                try:
                    user = dict((m.property_data.get("attributes") or {}).get("_USER") or {})
                except Exception:
                    user = {}
            if d is not None and type(d).__name__ == want_cls:
                cdci = (d.instance_id, dict(d.property_data))
                pcma_len = d.property_data.get("length")          # áudio: samples do descriptor
                phys = d.property_data.get("physical_media")
                if phys is not None:
                    loc = phys.property_data.get("locator")
                    old_path = loc.property_data.get("path_posix") if loc else None
                    if loc is not None and type(loc).__name__ == "WinFileLocator":
                        win_path = loc.property_data.get("path") or None
            if kind != "audio" and d is not None:
                essencias += _sclps_com_inicio(m)
            if kind != "audio" and d is not None and type(d).__name__ == "PCMADescriptor" and d.property_data.get("length"):
                # MOV com PCM: a essência de som é um mob próprio, em AMOSTRAS (o MC grava as do arquivo — 5/5, PRODC
                # 1080p100, MC 24.6, 2026-10-18); clonado, ficava a do molde.
                multi_pcma.append((d.instance_id, d.property_data.get("length"),
                                   float(d.property_data.get("sample_rate") or 48000)))
            if kind != "audio" and d is not None and type(d).__name__ == "MPGADescriptor":
                mpga = (d.instance_id, dict(d.property_data), _own_track_sourceclips(m))
            if kind != "audio" and d is not None and type(d).__name__ == "MultiDescriptor":
                # RAW de câmera com som embutido (BRAW: RGBADescriptor + PCMADescriptor, medido no MC 24.6,
                # 2026-10-18): o caminho mora no physical_media do MultiDescriptor, e o PCMA conta AMOSTRAS.
                phys = d.property_data.get("physical_media")
                loc = phys.property_data.get("locator") if phys is not None else None
                if loc is not None and type(loc).__name__ == "WinFileLocator":
                    win_path = loc.property_data.get("path") or None
                elif loc is not None:
                    old_path = loc.property_data.get("path_posix") or old_path
                for s in d.property_data.get("descriptors") or []:
                    if type(s).__name__ != "PCMADescriptor" and s.property_data.get("length"):
                        multi_video.append((s.instance_id, s.property_data.get("length")))
                    if type(s).__name__ == "PCMADescriptor" and s.property_data.get("length"):
                        multi_pcma.append((s.instance_id, s.property_data.get("length"),
                                           float(s.property_data.get("sample_rate") or 48000)))
        tc_iid, tc_start, tc_fps = _find_timecode(f, clip_name)   # TC (vídeo: Timecode component)
        tc_er = None                                               # a taxa em que ele CONTA (pode ≠ fps)
        if tc_iid is not None:
            try:
                tc_er = float(f.read_object(tc_iid).property_data.get("edit_rate") or 0) or None
            except Exception:
                tc_er = None
        aud_start, aud_er, sclp_iids = _find_audio_start(f, clip_name) if kind == "audio" else (None, None, [])
    raw = bytearray(open(template_bin, "rb").read())
    npatch = 0
    desloc = 0                                                     # fase do TC: alvo × molde (`_fase_do_tc`)
    # 1) cadeia (size-neutral)
    if kind == "audio":
        tpl_sr = float(cdci[1].get("sample_rate") or 48000) if cdci else 48000.0
        # ⚠️ `fps` do chamador VENCE a taxa do template — ver o docstring.
        er_alvo = fps or aud_er or 24.0
        _samples, target_sr, audio_len = _clone_audio_chain(raw, pos, info, target_file, pcma_len, aud_start,
                           er_alvo, template_bin=template_bin, sclp_iids=sclp_iids,
                           tpl_sr=tpl_sr, master_len_min=master_len_min)
        # 2a) TAXA do descriptor (size-neutral) — patcha sample_rate/edit_rate/average_bps p/ a taxa
        # REAL do arquivo (senão 44.1kHz em template 48kHz fica com duração errada -> PMM nos cortes)
        if cdci is not None:
            npatch = _patch_pcma_rate(raw, template_bin, cdci[0], pos[cdci[0]] + 8, cdci[1], target_sr)
        # 2b) a TAXA DO PROJETO na cadeia inteira (B001, 2026-10-31) — antes da troca de nome, que muda o tamanho
        npatch += _patch_taxa_da_cadeia(raw, template_bin, pos, clip_name, er_alvo, audio_len,
                                        info["length"], drop=drop)
    else:
        F = AC.clone_one(raw, pos, bytes(raw), info, target_file, do_name=False,   # nome adiado p/ replace_field
                         frames=_quadros_como_o_mc(target_file) if mpga is not None else None,
                         template_bin=template_bin)
        # 2) geometria de vídeo (size-neutral). ⚠️ Molde da MESMA assinatura (raster incluído): a geometria do molde
        # É a do MC, e recalcular estraga — MOV 960×540 do PRODC: o MC grava 1920×1080 e o patch levou a 960×1080,
        # PAR 0,5 (2026-10-18).
        if cdci is not None and not mesma_geometria:
            meta = VD.probe_video(target_file)
            tgt = _target_geometry(cdci[1], meta, os.path.splitext(target_file)[1])
            log = O.map_object(template_bin, cdci[0])
            patches = DP.plan_video_geometry(log, cdci[1], tgt)
            DP.apply_patches(raw, pos[cdci[0]] + 8, patches)
            npatch = len(patches)
        # 2c) ÁUDIO MPEG EMBUTIDO (ex.: AAC/MP2 num .mov/.mp4): a duração da SUA PRÓPRIA essência (mob
        # MPGADescriptor) NÃO é tocada pelo clone_one (só o comprimento do MASTER, que por coincidência
        # de valor no template é o único ajustado por scoped_replace) — fica presa na duração antiga
        # do template, incoerente com o vídeo clonado -> "Range specified for Dup is outside range of
        # component" no MC ao editar (Extract) perto do fim do clipe. Patch preciso por offset (como o
        # TC abaixo), não scoped_replace: o comprimento do MASTER e o da essência MPGA no template quase
        # nunca coincidem em valor (ex.: 5267 vs 5268), então o replace por-valor nunca os alcançaria.
        if mpga is not None and F:
            desc_iid, desc_pd, own_clips = mpga
            desc_len = desc_pd.get("length")
            sr = float(desc_pd.get("sample_rate") or 0)
            video_er = next((er for _i, _l, er in own_clips if er), None) or tc_fps or 23.976
            if desc_len and sr:
                import math
                # ⭐ O MC grava quadros × sr/taxa + o PRIMING do AAC (2112 no PRODC, 6/6, MC 24.6, 2026-10-18). O acréscimo
                # sai do MOLDE (o que ele tem além da conta), não de uma constante: outro encoder, outro priming.
                tpl_len = info.get("length") or 0
                extra = desc_len - int(round(tpl_len / video_er * sr)) if tpl_len else 0
                if not 0 <= extra <= 8192:                   # molde de outra forma (ex.: duração do próprio AAC)
                    extra = 0
                new_desc_len = max(1, int(math.ceil(F * sr / video_er - 1e-6)) + extra)   # 981×48000/60 = 784800,0000001
                if new_desc_len != desc_len:
                    log = O.map_object(template_bin, desc_iid)
                    offs = O.find_field(log, desc_len)
                    if offs:
                        struct.pack_into("<I", raw, pos[desc_iid] + 8 + offs[0], new_desc_len)
        # 2d) PCM do MultiDescriptor: as amostras do arquivo NOVO (o ffprobe conta; senão, pela duração do vídeo)
        if multi_pcma and F:
            amostras = _amostras_do_audio(target_file)
            for desc_iid, desc_len, sr in multi_pcma:
                novo = amostras or max(1, int(round(F / (fps or 23.976) * sr)))
                if novo != desc_len:
                    log = O.map_object(template_bin, desc_iid)
                    offs = O.find_field(log, desc_len)
                    if offs:
                        struct.pack_into("<I", raw, pos[desc_iid] + 8 + offs[0], novo)
        # 2e) ESSÊNCIAS: cada SourceClip das fontes guarda, em relação ao master, a diferença que tinha no MOLDE
        # (MP4 + AAC: vídeo = F, áudio = F + 3) e o início anda com a FASE do TC (ver `_fase_do_tc`). Sem isso o
        # clone herdava comprimento e início do molde (MPGA 13312 × 13309; início 4 × 3 — PRODC, 2026-10-18).
        tpl_len = info.get("length") or 0
        tpl_file = _do_avid(win_path) if win_path else old_path
        if tpl_file and os.path.isfile(tpl_file):
            desloc = _fase_do_tc(tpl_file, tc_fps) - _fase_do_tc(target_file, tc_fps)
        if F and tpl_len and essencias:
            for sc_iid, sc_len, sc_ini in essencias:
                if sc_len is None or abs(sc_len - tpl_len) > 1000:   # outra unidade (amostras): não é deste passo
                    continue
                off_len, off_ini = _campos_sclp(template_bin, sc_iid, sc_len)
                if off_len is not None:
                    struct.pack_into("<I", raw, pos[sc_iid] + 8 + off_len, max(1, F + sc_len - tpl_len))
                if off_ini is not None and desloc and sc_ini is not None and sc_ini + desloc >= 0:
                    struct.pack_into("<i", raw, pos[sc_iid] + 8 + off_ini, sc_ini + desloc)
        # 2f) vídeo dentro do MultiDescriptor (BRAW: RGBADescriptor) — em quadros, como o master
        for desc_iid, desc_len in (multi_video if F else []):
            novo = F + desc_len - tpl_len if tpl_len and abs(desc_len - tpl_len) <= 1000 else None
            if novo and novo != desc_len:
                log = O.map_object(template_bin, desc_iid)
                offs = O.find_field(log, desc_len)
                if offs:
                    struct.pack_into("<I", raw, pos[desc_iid] + 8 + offs[0], novo)
    # 2b) Timecode de início POR CLIPE (size-neutral) — senão todos herdam o TC do template
    tc_patched = False
    if tc_iid is not None and tc_start is not None:
        # O desconto entre o ffprobe e o MC sai do MOLDE: o MC leu o arquivo dele e gravou `tc_start`.
        tpl_file = _do_avid(win_path) if win_path else old_path
        unidade = int(round(tc_er)) if tc_er else None
        tpl_cru = (_probe_tc_cru(tpl_file, tc_fps or 24, unidade)
                   if tpl_file and os.path.isfile(tpl_file) else None)
        # ⭐ O TC que o MC grava = o do XMP − o início da essência (MP4 60p do PRODC: −4 no quadro par, −3 no ímpar):
        # o desconto do molde anda com a fase, no sentido contrário ao do início.
        desconto = (tc_start - tpl_cru - desloc) if tpl_cru is not None else -2
        new_start = _probe_start_tc(target_file, tc_fps or 24, desconto, unidade)
        if new_start is not None and new_start != tc_start:
            tclog = O.map_object(template_bin, tc_iid)
            offs = O.find_field(tclog, tc_start)
            if offs:
                struct.pack_into("<i", raw, pos[tc_iid] + 8 + offs[0], new_start)
                tc_patched = True
    # 3) NOME + PATH (size-changing) por ÚLTIMO (recalculam posições andando os chunks). Unificado
    # p/ ÁUDIO e VÍDEO: nome de tamanho VARIÁVEL via replace_field (o clone_one NÃO tocou o nome),
    # depois path via relink direto do old_path. Convenção: ÁUDIO mantém extensão (...T003.WAV);
    # VÍDEO sem extensão (A004_...).
    changes = []
    raw, n_meta = _metadados_da_camera(raw, user, _do_avid(win_path) if win_path else old_path, target_file)
    base = os.path.basename(target_file)
    newname = unicodedata.normalize("NFC", base if kind == "audio" else os.path.splitext(base)[0])
    if newname != clip_name:
        # o nome do mob é macroman e em NFC, como o MC grava (`LAB V07 ação.WAV` → `a\x8d\x8bo`); o `replace_field` com
        # texto codificaria em latin-1 (o ç viraria outro caractere) e o NFD do exFAT nem codifica
        out, _ = AR.replace_field(bytes(raw), clip_name.encode("macroman", "replace"),
                                  newname.encode("macroman", "replace")); raw = bytearray(out)
    if old_path:
        out, changes = AR.relink(bytes(raw), mapping={old_path: os.path.abspath(target_file)})
        raw = bytearray(out)
    elif win_path:
        novo = _forma_avid(os.path.abspath(target_file))
        raw, n = _relink_win(raw, win_path, novo)
        changes = [(win_path, novo)] * n
    raw = _uid_novo(raw, bin_uid)
    open(out_bin, "wb").write(raw)
    if kind == "audio":
        # ⭐ A PROVA, sempre: relida a bin, a cadeia tem de ser a que o MC grava. Diferente = o arquivo não entra (quem
        # chama o põe em `pulados` com o motivo) — áudio com a taxa errada toca deslocado, e ninguém vê na hora.
        erros = conferir_taxa_do_audio(out_bin, newname, er_alvo, audio_len,
                                       _probe_bwf_start(target_file, er_alvo), drop=drop)
        if erros:
            raise RuntimeError("a cadeia de áudio não ficou como o MC grava: " + "; ".join(erros[:4]))
    return {"clip": clip_name, "target": os.path.basename(target_file),
            "geometry_patches": npatch, "tc_patched": tc_patched, "path_changes": len(changes), "meta_changes": n_meta, "out": out_bin}


def clone_offline(template_bin, clip_name, out_bin, new_name, master_len, kind="video", locator=None, fps=None):
    """Autora um master OFFLINE (mídia AUSENTE): clona a cadeia do template com NOME + DURAÇÃO dados
    e um locator inexistente -> o Avid mostra o clipe OFFLINE (preserva a edição, sem 'missing mob').
    NÃO faz ffprobe (o arquivo não está disponível). Retorna out_bin.

    ÁUDIO tem DOIS lengths incompatíveis (como em clone_generic/_clone_audio_chain): o do MASTER/
    tracks em FRAMES@timeline (=master_len, coberto pelo scoped_replace abaixo) e o do PCMADescriptor
    em SAMPLES@sample_rate (independente — nunca numericamente igual a master_len, então o
    scoped_replace por VALOR nunca o alcança). Deixado no valor do template (duração antiga, bem
    maior que master_len) ele fica incoerente com os tracks encurtados -> CM_INVALID_DUP no SAVE do
    Avid (diagnosticado 2026-07-05/06: MOTO_68 salvava com descriptor.length=4373334 amostras vs
    tracks=407 frames). Convertido explicitamente aqui: samples = ceil(master_len/edit_rate*sample_rate).
    `fps` = edit_rate da TIMELINE (preferir sempre; passar do chamador) — fallback: TC de áudio achado
    no template (_find_audio_start, só funciona se o template tiver start_time não-zero) -> 24.0."""
    with avb_read.topen(template_bin) as f:
        pos = list(f.object_positions)
        info = AC.clip_info(f, clip_name)
        old_path = None
        pcma_len = pcma_sr = None
        for m in f.content.mobs:
            if (m.property_data.get("name") or "") != clip_name:
                continue
            d = m.property_data.get("descriptor")
            if d is not None:
                phys = d.property_data.get("physical_media")
                loc = (phys.property_data.get("locator") if phys else None) or d.property_data.get("locator")
                if loc:
                    old_path = loc.property_data.get("path_posix")
                if kind == "audio" and type(d).__name__ == "PCMADescriptor":
                    pcma_len = d.property_data.get("length")
                    pcma_sr = float(d.property_data.get("sample_rate") or 48000)
        _aud_start, aud_er, _sclp_iids = _find_audio_start(f, clip_name) if kind == "audio" else (None, None, [])
    raw = bytearray(open(template_bin, "rb").read())
    rngs = AC.ranges_for(pos, bytes(raw), info["indices"])
    seen = set()                                                     # mob_id fresco
    for blle in info["mobids"]:
        material = bytes(blle[16:32])
        if material in seen:
            continue
        seen.add(material)
        r_old, r_new = AC.region(material), AC.region(os.urandom(16))
        if raw.count(r_old):
            raw[:] = raw.replace(r_old, r_new)
    AC.scoped_replace_u32(raw, rngs, info["length"], max(1, int(master_len)),   # duração -> master_len (só o campo, B067)
                          AC.campos_provados(template_bin, info["indices"], info["length"], {"length"}))
    if pcma_len is not None:                                         # descriptor: SAMPLES coerentes
        import math
        er = fps or aud_er or 24.0
        new_samples = max(1, int(math.ceil(master_len / er * pcma_sr)))
        AC.scoped_replace_u32(raw, rngs, pcma_len, new_samples,
                              AC.campos_provados(template_bin, info["indices"], pcma_len,
                                                 {"length", "_SAVED_AAF_AUDIO_LENGTH"}))
    new_name = unicodedata.normalize("NFC", new_name)                # macroman e NFC, como no clone_generic
    if new_name != clip_name:                                        # nome (size-changing) por último
        out, _ = AR.replace_field(bytes(raw), clip_name.encode("macroman", "replace"),
                                  new_name.encode("macroman", "replace")); raw = bytearray(out)
    ext = os.path.splitext(old_path or "")[1] or (".wav" if kind == "audio" else ".mp4")
    loc = locator or ("/AVB_OFFLINE/" + new_name + (ext if not new_name.lower().endswith(ext) else ""))
    if old_path:
        out, _ = AR.relink(bytes(raw), mapping={old_path: loc}); raw = bytearray(out)
    open(out_bin, "wb").write(raw)
    return out_bin
