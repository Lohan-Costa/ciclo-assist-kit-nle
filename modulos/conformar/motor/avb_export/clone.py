#!/usr/bin/env python3
"""avb_clone.py — cria AMA-links para arquivos NOVOS clonando clipes de um bin-template,
por BYTE-SURGERY (o writer do pyavb NÃO é usado).

HISTÓRICO: a 1ª versão desta tool autorava o clone com o WRITER do pyavb (f.write). O clone
reabria no pyavb, mas o Media Composer o trazia OFFLINE — confirmado em ~5 iterações (v5..v9)
mesmo com todos os campos (MobID/durações/MSMLocator) corretos. Causa: o pyavb-write reserializa
o bin de um jeito que o MC não aceita p/ mobs AMA modificados. Trocando SÓ a via de escrita por
byte-surgery (patch cru sobre o template), o MESMO conteúdo lógico vem ONLINE. Confirmado no MC
25.12 (2026-06-28): clones DJI_0004 (2434f) e DJI_0005 (5884f) online + tocando a duração inteira.

COMO FUNCIONA: usa pyavb APENAS como LEITOR-oráculo (localizar valores e o intervalo de bytes de
cada objeto via o TOC AVBFile.object_positions + instance_id), e patcha o arquivo cru:
  1. MobID fresco  — region-replace da serialização de 24 bytes do material (size-neutral), global;
     pega TODAS as refs do mob (header, SourceClip, MSMLocator) de uma vez.
  2. duração       — u32 LE, ESCOPADO aos objetos do clipe (mob+Seq+SrcClip+descriptor).
  3. _AMA_FILE_DATE_TIME — u32 LE = mtime do arquivo, ESCOPADO ao ATTR do clipe (resolve colisão
     entre clipes que compartilham a mesma data).
  4. nome + filename do path — replace da string (size-neutral neste protótipo).

REQUISITOS: pyavb (read) + ffprobe. Template VÍDEO-PURO (sem áudio PCM; PCMA o pyavb não lê).
Template e alvo devem ser da MESMA família (container+codec+resolução+layout) —
ver bancodedadosnles/protocolos/avb/dados/codec-templates.json.

LIMITAÇÃO (protótipo): nome e caminho novos têm que ter o MESMO nº de bytes do template (verdade p/
arquivos na mesma pasta com nomes do mesmo padrão/tamanho, ex.: DJI_0012 -> DJI_0004). Para nomes/
caminhos de tamanho diferente é preciso o fixup de chunk-size de string (ver avb_relink.py).

USO:
  python3 avb_clone.py TEMPLATE.avb SAIDA.avb \
      --job CLIPE_BASE_NO_TEMPLATE "/caminho/arquivo_novo.mov" \
      --job OUTRO_CLIPE_BASE       "/caminho/outro.mov"
Importe a SAIDA em projeto novo / AMA Management vazia.
"""
import os, sys, struct, subprocess, argparse
import os as _os
import sys as _sys

# rodando como script solto (`python tools/x.py`): o `motor` no caminho, para achar `media`
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)


def region(ml):
    """material UUID (16B, bytes_le) -> serialização de 24 bytes no disco (com tags)."""
    return bytes([0x48]) + ml[0:4] + bytes([0x46]) + ml[4:6] + bytes([0x46]) + ml[6:8] \
         + bytes([0x41, 8, 0, 0, 0]) + ml[8:16]


def frame_count(path):
    # RÁPIDO: nb_frames do header (mp4/mov já trazem). Fallback p/ -count_frames (lento, exato).
    r = subprocess.run([fftools.ffprobe_exe(), "-v", "error", "-select_streams", "v:0",
                        "-show_entries", "stream=nb_frames", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    out = r.stdout.strip()
    if out.isdigit() and int(out) > 0:
        return int(out)
    r = subprocess.run([fftools.ffprobe_exe(), "-v", "error", "-select_streams", "v:0", "-count_frames",
                        "-show_entries", "stream=nb_read_frames", "-of", "default=nw=1:nk=1", path],
                       capture_output=True, text=True)
    out = r.stdout.strip()
    if not out.isdigit():
        raise SystemExit("ffprobe nao retornou nb_frames p/ %s (%r)" % (path, out))
    return int(out)


def collect_indices(mob):
    """instance_ids de todos os objetos do clipe a partir de um mob (p/ escopar replaces)."""
    s = set()
    if getattr(mob, "instance_id", None) is not None:
        s.add(mob.instance_id)
    a = getattr(mob, "attributes", None)
    if getattr(a, "instance_id", None) is not None:
        s.add(a.instance_id)
    d = getattr(mob, "descriptor", None)
    if d is not None:
        if getattr(d, "instance_id", None) is not None:
            s.add(d.instance_id)
        L = getattr(d, "locator", None)
        if getattr(L, "instance_id", None) is not None:
            s.add(L.instance_id)
    for t in mob.tracks:
        c = getattr(t, "component", None)
        if c is None:
            continue
        if getattr(c, "instance_id", None) is not None:
            s.add(c.instance_id)
        for sc in getattr(c, "components", []) or []:
            if getattr(sc, "instance_id", None) is not None:
                s.add(sc.instance_id)
    return s


def clip_info(f, clipname):
    mobs = [m for m in f.content.mobs if getattr(m, "name", None) == clipname]
    if not mobs:
        raise SystemExit("clipe-base %r nao esta no template" % clipname)
    info = {"mobids": [], "indices": set(), "length": None, "date": None, "name": clipname}
    for m in mobs:
        info["mobids"].append(m.mob_id.bytes_le)
        info["indices"] |= collect_indices(m)
        if getattr(m, "descriptor", None) is None:           # MasterMob: duração do clipe
            for t in m.tracks:
                c = getattr(t, "component", None)
                if c is not None and getattr(c, "length", None):
                    info["length"] = c.length
                    info["edit_rate"] = getattr(c, "edit_rate", None)
        else:
            a = getattr(m, "attributes", {}) or {}
            if "_AMA_FILE_DATE_TIME" in a:
                info["date"] = a["_AMA_FILE_DATE_TIME"]
    if info["length"] is None or info["date"] is None:
        raise SystemExit("clipe %r: nao achei duracao/data (template vídeo-puro?)" % clipname)
    return info


def ranges_for(pos, raw, indices):
    out = []
    for iid in indices:
        hdr = pos[iid]
        _, size = struct.unpack(b"<4sI", raw[hdr:hdr + 8])
        out.append((hdr + 8, hdr + 8 + size))
    return out


def scoped_replace_u32(data, ranges, old, new, apenas=None):
    """Troca o u32 `old` por `new` nos objetos do clipe. `apenas` = os offsets absolutos PROVADOS (`campos_provados`):
    sem ele, toda ocorrência do valor — o que acerta campo alheio de mesmo valor (B067, abaixo)."""
    ob, nb = struct.pack("<I", old), struct.pack("<I", new)
    n = 0
    for s, e in ranges:
        seg = bytes(data[s:e])
        if apenas is None:
            c = seg.count(ob)
            if c:
                data[s:e] = seg.replace(ob, nb)
                n += c
            continue
        i = seg.find(ob)
        while i >= 0:
            if s + i in apenas:
                data[s + i:s + i + 4] = nb
                n += 1
            i = seg.find(ob, i + 1)
    return n


_PROVADOS: dict = {}


def campos_provados(template_bin, indices, valor, nomes):
    """Os offsets absolutos em que `valor` (u32 LE) É um dos campos `nomes` nos objetos `indices` do molde — provado
    trocando UMA ocorrência por vez, relendo o objeto no pyavb e conferindo que mudou um daqueles campos.

    ⛔ B067 (banco, bugs-do-mundo-real), medido em 2026-10-28 no molde `audio_1_24bit_1ch_semcena` (1 s): a duração
    25 é também a REFERÊNCIA da Sequence para o objeto 25, e as 48000 amostras são também o `sample_rate` do PCMA e o
    `_SAVED_AAF_AUDIO_RATE_NUM`. A troca por valor gravava a duração nova na referência ("bad index: 175" num WAV de
    7 s; com 1 s a referência apontaria CALADA para outro objeto) e o número de amostras na taxa. Os outros 14
    moldes não tinham colisão — por sorte, não por desenho. Uma vez por molde (os offsets valem no clone: as trocas
    de antes do nome não mudam tamanho)."""
    import contextlib
    import io
    import tempfile
    import avb

    chave = (template_bin, valor, tuple(sorted(nomes)))
    if chave in _PROVADOS:
        return _PROVADOS[chave]

    def campos(o):
        out = {}
        for k, v in (getattr(o, "property_data", None) or {}).items():
            out[k] = repr(v)
        if type(o).__name__ == "Attributes":
            out.update({k: repr(v) for k, v in o.items()})
        return out

    raw = open(template_bin, "rb").read()
    with avb.open(template_bin) as f:
        pos = list(f.object_positions)
        antes = {iid: campos(f.read_object(iid)) for iid in indices}
    ob = struct.pack("<I", valor)
    provados = set()
    fd, tmp = tempfile.mkstemp(suffix=".avb")
    os.close(fd)
    try:
        for s, e in ranges_for(pos, raw, indices):
            iid = next(i for i in indices if pos[i] + 8 == s)
            i = raw.find(ob, s, e)
            while i >= 0:
                d = bytearray(raw)
                prova = (valor + 7) & 0xFFFFFFFF
                d[i:i + 4] = struct.pack("<I", prova)
                with open(tmp, "wb") as fh:
                    fh.write(d)
                try:
                    # o pyavb IMPRIME o traceback da janela que quebra a releitura (referência) antes de levantar:
                    # calado aqui, senão cada molde novo enchia o log do serviço
                    with avb.open(tmp) as g, contextlib.redirect_stdout(io.StringIO()), \
                            contextlib.redirect_stderr(io.StringIO()):
                        depois = campos(g.read_object(iid))
                    # o campo relido tem de ser EXATAMENTE a prova: uma janela desalinhada (1 byte depois do campo)
                    # também o "muda", e com valor 0 (o start do molde estéreo) haveria várias assim
                    if any(depois.get(n) == repr(prova) for n in nomes):
                        provados.add(i)
                except Exception:  # noqa: BLE001 — releitura quebrada = não era o campo (era uma referência)
                    pass
                i = raw.find(ob, i + 1, e)
    finally:
        os.remove(tmp)
    _PROVADOS[chave] = provados
    return provados


def clone_one(data, pos, raw, info, target, do_name=True, frames=None, template_bin=None):
    """Clona a cadeia (size-neutral): MobID fresco + duração + data. Com do_name=True também troca o
    NOME (replace cru same-size, exige len igual) — usado pelo CLI/regressão. Com do_name=False PULA o
    nome (e a trava de tamanho): quem chama faz o nome via replace_field (tamanho variável), como no
    caminho de áudio — deixando nome+path na fase size-changing do fim."""
    if not os.path.exists(target):
        print("AVISO: arquivo-alvo nao existe:", target)
    F = frames or frame_count(target)                       # `frames`: quem chama já sabe (o MC mede o stream mais longo)
    mt = int(os.stat(target).st_mtime)
    oldname = info["name"]
    rngs = ranges_for(pos, raw, info["indices"])
    vistos = set()
    for blle in info["mobids"]:                              # 1) MobID fresco
        # ⚠️ O plugin AMA do Blackmagic RAW dá o MESMO material aos 3 mobs do clipe (master, fonte, MultiDescriptor;
        # só o byte de instância muda — MC 24.6, 2026-10-18): o 1º replace já troca todos, e os três seguem juntos.
        if bytes(blle[16:32]) in vistos:
            continue
        vistos.add(bytes(blle[16:32]))
        r_old, r_new = region(blle[16:32]), region(os.urandom(16))
        if data.count(r_old) == 0:
            raise SystemExit("region do MobID nao encontrada")
        data[:] = data.replace(r_old, r_new)
    # 2) duração e 3) data — só onde o valor É o campo (B067; `template_bin` = o molde de onde `data` veio)
    so_l = campos_provados(template_bin, info["indices"], info["length"], {"length"}) if template_bin else None
    so_d = campos_provados(template_bin, info["indices"], info["date"], {"_AMA_FILE_DATE_TIME"}) if template_bin else None
    nL = scoped_replace_u32(data, rngs, info["length"], F, so_l)
    nD = scoped_replace_u32(data, rngs, info["date"], mt, so_d)
    nN = 0
    if do_name:                                              # 4) nome + path (same-size, legado CLI)
        newname = os.path.splitext(os.path.basename(target))[0]
        if len(newname) != len(oldname):
            raise SystemExit("nome novo %r tem tamanho != template %r; use do_name=False + "
                             "replace_field (ver clone_generic)" % (newname, oldname))
        ob, nb = oldname.encode("latin-1"), newname.encode("latin-1")
        nN = data.count(ob)
        data[:] = data.replace(ob, nb)
    print("  %s -> %s F=%d (len %d->%d x%d, date->%d x%d, name x%d)"
          % (oldname, "(nome adiado)" if not do_name else os.path.splitext(os.path.basename(target))[0],
             F, info["length"], F, nL, mt, nD, nN))
    return F


def main():
    ap = argparse.ArgumentParser(description="Clona clipes AMA de um template p/ arquivos novos (byte-surgery).")
    ap.add_argument("template")
    ap.add_argument("output")
    ap.add_argument("--job", nargs=2, action="append", metavar=("CLIPE_BASE", "ARQUIVO"),
                    required=True, help="clipe-base no template -> arquivo-alvo (repetível)")
    args = ap.parse_args()
    import avb
    raw = open(args.template, "rb").read()
    data = bytearray(raw)
    with avb.open(args.template) as f:
        pos = list(f.object_positions)
        infos = [(clip_info(f, base), tgt) for base, tgt in args.job]
    for info, tgt in infos:
        clone_one(data, pos, raw, info, tgt)
    if len(data) != len(raw):
        raise SystemExit("ERRO: tamanho mudou (%d->%d) — patch nao size-neutral" % (len(raw), len(data)))
    open(args.output, "wb").write(data)
    print("OK size=%d ->" % len(data), args.output)


if __name__ == "__main__":
    main()
