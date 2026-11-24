#!/usr/bin/env python3
"""
avb_relink.py — relink de caminhos AMA em bins .avb do Avid Media Composer.

100% stdlib (sem pyavb). Faz byte-surgery nos chunks FILE (MacFileLocator),
trocando path_posix (macroman) e path_utf8 (utf-8) e corrigindo o tamanho do
chunk. O .avb NÃO tem tabela de offsets — as posições são recalculadas na
leitura — então mudar o comprimento das strings é seguro desde que se corrija
o u16 da string e o u32 'size' do chunk.

Validado em Avid Media Composer 25.12 (mídia AMA online após relink, inclusive
caminhos de comprimento diferente). Ver bancodedadosnles/protocolos/avb/escrita.md.

ATENÇÃO (regra do AMA online): para o clipe vir ONLINE, além do caminho a bin
precisa casar com o arquivo em:
  - mtime do arquivo == atributo _AMA_FILE_DATE_TIME (esta ferramenta NÃO mexe
    nesse atributo; mover o arquivo com `mv` preserva o mtime e funciona; para
    cópia/arquivo novo, alinhe o mtime: `touch -r origem destino`).
  - tamanho e handler do plugin (preservados; não mexemos).

Uso:
  python3 avb_relink.py list  BIN.avb
  python3 avb_relink.py relink BIN.avb SAIDA.avb --replace /Volumes/old /Volumes/new
  python3 avb_relink.py relink BIN.avb SAIDA.avb --map mapa.json   # {"/cam/antigo.mov":"/novo/x.mov"}
  python3 avb_relink.py relink BIN.avb SAIDA.avb --replace /old /new --sync-mtime
"""
import sys, os, struct, json, argparse, unicodedata

MAGIC = b"Domain"
FILE_CLASS = b"FILE"   # gravado invertido em LE no disco ('ELIF')


def _read_string_field(buf, off):
    """Lê u16(len)+bytes a partir de off. Retorna (raw_bytes_incl_prefix, payload_bytes)."""
    n = struct.unpack_from("<H", buf, off)[0]
    return buf[off:off + 2 + n], buf[off + 2:off + 2 + n]


def parse_header_end(d):
    """Retorna (offset_inicio_tabela, num_objects). Pura leitura do cabeçalho AObjDoc."""
    if d[0:2] != b"\x06\x00":
        raise ValueError("não é .avb little-endian (esperado 06 00)")
    o = 2
    if d[o:o + 6] != MAGIC:
        raise ValueError("magic 'Domain' ausente")
    o += 6
    o += 4                                   # fourcc OBJD (invertido no disco)
    n = struct.unpack_from("<H", d, o)[0]; o += 2 + n      # string 'AObjDoc'
    o += 1                                   # u8 version (0x04)
    n = struct.unpack_from("<H", d, o)[0]; o += 2 + n      # string last_save_str
    num_objects = struct.unpack_from("<I", d, o)[0]; o += 4
    o += 4                                   # root_index
    o += 4                                   # sentinel IIII
    o += 4                                   # datetime (u32)
    o += 4                                   # skip
    o += 4                                   # fourcc ATob
    o += 4                                   # fourcc ATve
    o += 32                                  # creator_version (u16=30 + 30, padded)
    o += 16                                  # reserved
    return o, num_objects


def walk_chunks(d):
    """Gera (pos, class_id, size). class_id já desinvertido (ex.: b'FILE')."""
    o, num = parse_header_end(d)
    for _ in range(num):
        pos = o
        class_id = bytes(d[o:o + 4])[::-1]
        size = struct.unpack_from("<I", d, o + 4)[0]
        yield pos, class_id, size
        o += 8 + size


def _locator_paths(chunk_data):
    """Acha (off_posix, posix_str) e (off_utf8, utf8_str) dentro de um chunk FILE.
    Marcadores: 01 01 4C => path_posix(macroman); 01 02 4C => path_utf8(utf-8 c/ prefixo 0000)."""
    res = {}
    p = chunk_data.find(b"\x01\x01\x4c")
    if p >= 0:
        _, payload = _read_string_field(chunk_data, p + 3)
        res["posix"] = (p + 3, payload.rstrip(b"\x00").decode("macroman"))
    p = chunk_data.find(b"\x01\x02\x4c")
    if p >= 0:
        _, payload = _read_string_field(chunk_data, p + 3)
        res["utf8"] = (p + 3, payload.strip(b"\x00").decode("utf-8"))
    return res


def _build_string_field(payload_bytes):
    return struct.pack("<H", len(payload_bytes)) + payload_bytes


def iter_file_paths(d):
    """Gera (chunk_pos, chunk_size, path_posix) para cada chunk FILE com path_posix."""
    for pos, cid, size in walk_chunks(d):
        if cid != FILE_CLASS:
            continue
        data = bytes(d[pos + 8:pos + 8 + size])
        locs = _locator_paths(data)
        if "posix" in locs:
            yield pos, size, locs["posix"][1]


def _transform(path, replace, mapping):
    if mapping and path in mapping:
        return mapping[path]
    if replace:
        old, new = replace
        if path.startswith(old):
            return new + path[len(old):]
    return None


def relink(d, replace=None, mapping=None):
    """Retorna (novo_bytes, lista_de_mudancas[(old,new)]). Edita do fim p/ o começo."""
    d = bytearray(d)
    edits = []   # (pos, old_size, new_chunk_bytes, old_path, new_path)
    for pos, cid, size in walk_chunks(d):
        if cid != FILE_CLASS:
            continue
        data = bytes(d[pos + 8:pos + 8 + size])
        locs = _locator_paths(data)
        if "posix" not in locs:
            continue
        old_path = locs["posix"][1]
        new_path = _transform(old_path, replace, mapping)
        if not new_path or new_path == old_path:
            continue
        # ⭐ O MC grava o caminho em NFC (MC 25.12 Mac, `LAB V07 ação.WAV`: macroman 0x8D e UTF-8 composto); o exFAT e
        # o HFS+ LISTAM em NFD, e o NFD nem cabe no macroman (o cedilha solto) — o clone de um arquivo com acento caía.
        new_path = unicodedata.normalize("NFC", new_path)
        new_data = bytearray(data)
        # path_utf8 primeiro (offset maior) p/ não invalidar o offset do posix
        items = []
        if "utf8" in locs:
            items.append(("utf8", locs["utf8"][0], new_path.encode("utf-8"), b"\x00\x00"))
        items.append(("posix", locs["posix"][0], new_path.encode("macroman"), b""))
        for _, off, payload, prefix in sorted(items, key=lambda x: -x[1]):
            field = _build_string_field(prefix + payload)
            old_len = 2 + struct.unpack_from("<H", new_data, off)[0]
            new_data[off:off + old_len] = field
        chunk = bytes(d[pos:pos + 4]) + struct.pack("<I", len(new_data)) + bytes(new_data)
        edits.append((pos, size, chunk, old_path, new_path))
    for pos, old_size, chunk, _, _ in sorted(edits, key=lambda x: -x[0]):
        d[pos:pos + 8 + old_size] = chunk
    return bytes(d), [(e[3], e[4]) for e in edits]


def replace_field(data, old, new):
    """Substitui um campo string length-prefixado (<u16 len><bytes>) de tamanho DIFERENTE em QUALQUER
    chunk, corrigindo o u32 size do chunk. Genérico (ex: NOME de mob). `old`/`new` = str ou bytes.
    Casa só o campo EXATO (não substrings/paths). Edita do fim p/ o começo. Retorna (novo_bytes, n)."""
    if isinstance(old, str): old = old.encode("latin-1")
    if isinstance(new, str): new = new.encode("latin-1")
    d = bytearray(data)
    needle = struct.pack("<H", len(old)) + old
    repl = struct.pack("<H", len(new)) + new
    edits = []                                   # (pos, old_chunk_size, new_chunk_bytes)
    n = 0
    for pos, cid, size in walk_chunks(d):
        cdata = bytes(d[pos + 8:pos + 8 + size])
        if needle not in cdata:
            continue
        ncd = cdata.replace(needle, repl)
        n += cdata.count(needle)
        chunk = bytes(d[pos:pos + 4]) + struct.pack("<I", len(ncd)) + ncd
        edits.append((pos, size, chunk))
    for pos, old_size, chunk in sorted(edits, key=lambda x: -x[0]):
        d[pos:pos + 8 + old_size] = chunk
    return bytes(d), n


def cmd_list(args):
    d = open(args.bin, "rb").read()
    rows = list(iter_file_paths(d))
    print("%d chunk(s) FILE com path_posix:\n" % len(rows))
    for _, _, path in rows:
        exists = os.path.exists(path)
        mark = "OK " if exists else "OFF"
        extra = ""
        if exists:
            extra = "  mtime=%d size=%d" % (int(os.stat(path).st_mtime), os.path.getsize(path))
        print("  [%s] %s%s" % (mark, path, extra))


def _sync_mtime(changes):
    """Alinha o mtime do arquivo NOVO ao do ANTIGO (quando o antigo existe).
    Mantém o _AMA_FILE_DATE_TIME da bin válido sem parsear a bin."""
    done = skipped = 0
    print("\n--sync-mtime:")
    for old, new in changes:
        if old == new or not os.path.exists(new):
            print("   skip (novo ausente): %s" % new); skipped += 1; continue
        if not os.path.exists(old):
            print("   skip (antigo ausente; mv já preserva o mtime): %s" % old); skipped += 1; continue
        if os.path.samefile(old, new):
            print("   ok (mesmo arquivo/symlink): %s" % new); done += 1; continue
        st = os.stat(old)
        os.utime(new, ns=(st.st_atime_ns, st.st_mtime_ns))
        print("   set mtime %d -> %s" % (int(st.st_mtime), new)); done += 1
    print("   (%d ajustado(s), %d pulado(s))" % (done, skipped))


def cmd_relink(args):
    d = open(args.bin, "rb").read()
    mapping = None
    if args.map:
        mapping = json.load(open(args.map, encoding="utf-8"))
    replace = tuple(args.replace) if args.replace else None
    if not mapping and not replace:
        sys.exit("informe --replace OLD NEW ou --map mapa.json")
    out, changes = relink(d, replace=replace, mapping=mapping)
    if not changes:
        print("nenhum caminho casou; nada a fazer."); return
    open(args.out, "wb").write(out)
    print("%d caminho(s) relinkado(s) -> %s  (in=%d out=%d bytes)" %
          (len(changes), args.out, len(d), len(out)))
    for old, new in changes:
        warn = "" if os.path.exists(new) else "  [!! arquivo novo não existe]"
        print("   %s\n     -> %s%s" % (old, new, warn))
    if args.sync_mtime:
        _sync_mtime(changes)
    else:
        print("\nLembrete: para ONLINE, o mtime do arquivo deve casar com _AMA_FILE_DATE_TIME.")
        print("Mover (mv) preserva mtime; p/ cópia use --sync-mtime ou: touch -r <origem> <destino>.")


def main():
    ap = argparse.ArgumentParser(description="Relink de caminhos AMA em bins .avb (stdlib).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    pl = sub.add_parser("list", help="lista os caminhos de arquivo da bin")
    pl.add_argument("bin")
    pl.set_defaults(func=cmd_list)
    pr = sub.add_parser("relink", help="reescreve caminhos numa nova bin")
    pr.add_argument("bin"); pr.add_argument("out")
    pr.add_argument("--replace", nargs=2, metavar=("OLD", "NEW"),
                    help="substituição por prefixo de caminho")
    pr.add_argument("--map", metavar="JSON", help="JSON {caminho_antigo: caminho_novo}")
    pr.add_argument("--sync-mtime", action="store_true",
                    help="alinha o mtime do arquivo novo ao do antigo (quando o antigo existe)")
    pr.set_defaults(func=cmd_relink)
    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
