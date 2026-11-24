"""Novo modelo de injeção de áudio a partir de uma bin do MC (manutenção dos modelos, não roda no produto).

Uso (da raiz do app, com o venv):  .venv-win\\Scripts\\python.exe tools\\neutralizar_modelo_audio.py BIN.avb
       no Mac, com o NOME do master (a bin pode ter vários):  .venv/bin/python tools/neutralizar_modelo_audio.py BIN.avb "LOCAL-3/001"
       e a VARIANTE (opcional) `cena` | `semcena`: o molde do WAV com ou sem cena e take (a fonte de baixo é de tape
       ou de mídia), em audio_<…>ch_<variante>.avb e na chave `audio|…|<variante>`
  BIN.avb = bin com UM WAV linkado (AMA) pelo MC, no formato que falta. Grava o modelo em
  motor/avb_export/templates/audio_<coding>_<bits>bit_<canais>ch.avb e acrescenta a chave no manifest.json.

Por que existe (2026-10-13): os 8 modelos embarcados vieram de bins do MAC (neutralize_templates.py do LEITURA-DE-MDB,
arquivado — `strings`, `/tmp`, caminhos POSIX). Uma bin do Windows difere em duas coisas:
  1. o locator do arquivo é `WINF` (`02 02 <u16 caminho> 01 02 4C <u16 00 00 + utf8> 03`), e o clone (`clone_generic`,
     `relink.relink`) só conhece o `FILE` do Mac (`02 02 00 00 01 01 4C <u16 posix> 01 02 4C <u16 00 00 + utf8> 03`)
     → o chunk é REESCRITO como `FILE` com o caminho neutro. Os objetos da bin se acham pelo índice, não pela posição,
     então trocar classe e tamanho do chunk é seguro (o relink já muda o tamanho do mesmo chunk);
  2. a identidade (nome do arquivo, volume, projeto, bin, data do arquivo) é a do projeto onde foi linkado.
O nome do arquivo aparece em vários enquadramentos de campo (u16, u32, com prefixo); é trocado por um nome neutro do
MESMO TAMANHO, que nenhum tamanho de campo precisa mudar. Volume/projeto/bin viram os valores dos outros modelos
(`AVB-MEDIA`, `TEMPLATE`, `TEMPLATE Bin1`) — o `avb_bin/audio._patch_volume` procura `AVB-MEDIA`.
"""
from __future__ import annotations

import json
import os
import re
import struct
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]
from avb_export import media_bin as MB  # noqa: E402
from avb_export import relink as AR  # noqa: E402
from avb_export.reader import topen  # noqa: E402

TEMPLATES = RAIZ / "motor" / "avb_export" / "templates"


def _master_e_formato(bin_path):
    with topen(bin_path) as f:
        nome = fmt = None
        for m in f.content.mobs:
            pd = m.property_data
            if pd.get("mob_type_id") == 2:
                nome = pd.get("name")
            d = pd.get("descriptor")
            if d is not None and type(d).__name__ == "PCMADescriptor":
                dp = d.property_data
                fmt = (dp["coding_format"], dp["quantization_bits"], dp["channels"])
        return nome, fmt


def _winf_para_file(d: bytes, caminho: str) -> tuple[bytes, int]:
    """Reescreve todo chunk `WINF` como `FILE` (locator do Mac) com `caminho`. Do fim para o começo."""
    d = bytearray(d)
    edits = [(pos, size) for pos, cid, size in AR.walk_chunks(d) if cid == b"WINF"]
    posix = caminho.encode("macroman")
    utf8 = b"\x00\x00" + caminho.encode("utf-8")
    corpo = (b"\x02\x02" + struct.pack("<H", 0) + b"\x01\x01\x4c" + struct.pack("<H", len(posix)) + posix
             + b"\x01\x02\x4c" + struct.pack("<H", len(utf8)) + utf8 + b"\x03")
    for pos, size in sorted(edits, reverse=True):
        velho = bytes(d[pos + 8:pos + 8 + size])
        if not (velho.startswith(b"\x02\x02") and velho.endswith(b"\x03") and b"\x01\x02\x4c" in velho):
            raise SystemExit(f"chunk WINF em {pos} com forma desconhecida: {velho[:16].hex(' ')}")
        d[pos:pos + 8 + size] = b"FILE"[::-1] + struct.pack("<I", len(corpo)) + corpo
    return bytes(d), len(edits)


def _abre_inteira(dados: bytes) -> bool:
    with tempfile.NamedTemporaryFile(suffix=".avb", delete=False) as t:
        t.write(dados)
    try:
        with topen(t.name) as f:
            for m in f.content.mobs:
                for tr in m.property_data.get("tracks") or []:
                    _ = tr.property_data
        return True
    except Exception as e:  # noqa: BLE001
        print("  não abre:", e)
        return False
    finally:
        os.unlink(t.name)


def main(src: str) -> None:
    nome, fmt = _master_e_formato(src)
    if not nome or not fmt:
        raise SystemExit("a bin precisa ter UM master de áudio AMA (PCMADescriptor)")
    coding, bits, canais = fmt
    base = f"audio_{coding}_{bits}bit_{canais}ch"
    neutro = (f"AVB_AUDIO_{coding}_{bits}BIT_{canais}CH".ljust(len(nome) - 4, "_") + ".WAV")[:len(nome)]
    assert len(neutro) == len(nome), (neutro, nome)
    saida = TEMPLATES / f"{base}.avb"
    print(f"master {nome!r} → formato {fmt} → {saida.name}, clipe {neutro!r}")

    with tempfile.TemporaryDirectory() as tmp:
        extraido = os.path.join(tmp, "x.avb")
        MB.extract_template_bin(src, nome, extraido)          # só a cadeia do clipe, Bin.uid novo
        d = open(extraido, "rb").read()

    with topen(src) as f:                                       # o que identifica o projeto, lido da própria bin
        projeto = bin_nome = None
        for m in f.content.mobs:
            a = m.property_data.get("attributes")
            if a is not None and "_PJ" in a:
                projeto = a["_PJ"]
    bin_nome = Path(src).stem
    vol = re.search(rb"[\x20-\x7e]{1,40} \([A-Z]:\)", d)
    volume = vol.group().decode("latin-1") if vol else None

    d, n_loc = _winf_para_file(d, f"/AVB_TEMPLATES/{base.replace('audio_', 'avb_audio_')}.WAV")
    n_nome = d.count(nome.encode("latin-1"))
    d = d.replace(nome.encode("latin-1"), neutro.encode("latin-1"))   # mesmo tamanho: todo enquadramento
    trocas = {"locator WINF→FILE": n_loc, "nome": n_nome}
    for velho, novo in ((volume, "AVB-MEDIA"), (projeto, "TEMPLATE"), (bin_nome, "TEMPLATE Bin1")):
        if not velho:
            continue
        d, a = AR.replace_field(d, velho, novo)
        d, b = AR.replace_field(d, b"\x00\x00" + velho.encode("latin-1"), b"\x00\x00" + novo.encode("latin-1"))
        trocas[velho] = a + b
    for data in sorted({m.group() for m in re.finditer(rb"(?:19|20)\d\d-\d\d-\d\d \d\d:\d\d:\d\d", d)}):
        d = d.replace(data, b"2024-01-01 00:00:00")           # data do ARQUIVO (mesmo tamanho)
        trocas[data.decode()] = 1
    print("  trocas:", trocas)

    if not _abre_inteira(d):
        raise SystemExit("o modelo não abre inteiro — nada gravado")
    sujos = [t for t in (nome, Path(nome).stem, volume, projeto, bin_nome, "G//", ":\\") if t]
    resto = [s.decode("latin-1") for s in re.findall(rb"[\x20-\x7e]{4,}", d)
             if any(t.lower() in s.decode("latin-1").lower() for t in sujos)]
    resto = [s for s in resto if "TEMPLATE" not in s and "AVB" not in s]
    if resto:
        raise SystemExit(f"sobrou identidade no modelo: {resto[:10]}")
    saida.write_bytes(d)

    # o manifest é alinhado à mão: a chave nova entra como uma linha, sem reformatar o resto
    man_p = TEMPLATES / "manifest.json"
    texto = man_p.read_text(encoding="utf-8")
    chave = f"audio|{coding}|{bits}|{canais}"
    if f'"{chave}"' not in texto:
        linha = json.dumps({chave: {"file": saida.name, "clip": neutro, "kind": "audio"}})[1:-1]
        texto = texto.replace('  "templates": {\n', '  "templates": {\n    ' + linha + ",\n", 1)
        json.loads(texto)
        man_p.write_text(texto, encoding="utf-8")
    print(f"  gravado {saida} e a chave audio|{coding}|{bits}|{canais} no manifest.json")


def _formato_do_clipe(bin_path, nome):
    """(coding, bits, canais) do PCMA na cadeia do master `nome`, e os textos que identificam o WAV e o projeto:
    o `_USER` do master (o que o MC tirou do gravador), os nomes das fontes (arquivo, tape), o projeto e a bin."""
    with topen(bin_path) as f:
        por = {m.mob_id: m for m in f.content.mobs}
        master = next(m for m in f.content.mobs if m.property_data.get("mob_type_id") == 2
                      and m.property_data.get("name") == nome)
        fmt, nomes, pilha, vistos = None, [], [master], set()
        while pilha:
            m = pilha.pop()
            if m.mob_id in vistos:
                continue
            vistos.add(m.mob_id)
            if m is not master and m.property_data.get("name"):
                nomes.append(m.property_data.get("name"))
            d = m.property_data.get("descriptor")
            if d is not None and type(d).__name__ == "PCMADescriptor":
                dp = d.property_data
                fmt = (dp["coding_format"], dp["quantization_bits"], dp["channels"])
            for t in m.property_data.get("tracks") or []:
                c = t.property_data.get("component")
                for x in (c.property_data.get("components") or []) if type(c).__name__ == "Sequence" else [c]:
                    alvo = por.get(getattr(x, "mob_id", None))
                    if alvo is not None:
                        pilha.append(alvo)
        a = master.property_data.get("attributes") or {}
        user = dict(a.get("_USER") or {}) if hasattr(a, "get") else {}
        org = a.get("_ORG_BIN") if hasattr(a, "get") else None
        bin_nome = getattr(org, "name", None) if org is not None else None
        projeto = None
        for mid in vistos:                                 # o projeto da CADEIA deste master, não de outro da bin
            at = por[mid].property_data.get("attributes")
            if at is not None and "_PJ" in at:
                projeto = at["_PJ"]
    return fmt, user, nomes, projeto, bin_nome


def main_mac(src: str, nome: str, variante: str = "") -> None:
    """A bin do Mac (o MC 25.12 com vários masters): extrai a cadeia de `nome`, troca o locator `FILE` pelo caminho
    neutro e, pelo MESMO TAMANHO (todo enquadramento de campo, sem mexer em tamanho), o que identifica o WAV e o
    projeto. Autor, 2026-10-25: os dois WAV do PRODC sem modelo (24-bit 4 canais e 1 canal), linkados por ele no MC."""
    fmt, user, fontes, projeto, bin_org = _formato_do_clipe(src, nome)
    if not fmt:
        raise SystemExit(f"o master {nome!r} não tem PCMA na cadeia")
    coding, bits, canais = fmt
    base = f"audio_{coding}_{bits}bit_{canais}ch"
    saida = TEMPLATES / f"{base}{'_' + variante if variante else ''}.avb"
    rotulo = f"AVB_A{coding}_{bits}B{canais}CH"

    def igual(texto, novo):
        return (novo.ljust(len(texto), "_"))[:len(texto)]

    with tempfile.TemporaryDirectory() as tmp:
        extraido = os.path.join(tmp, "x.avb")
        MB.extract_template_bin(src, nome, extraido)
        d = open(extraido, "rb").read()
        with topen(extraido) as f:
            caminhos = set()
            for m in f.content.mobs:
                dd = m.property_data.get("descriptor")
                loc = dd.property_data.get("locator") if dd is not None else None
                if loc is not None and loc.property_data.get("path_posix"):
                    caminhos.add(loc.property_data.get("path_posix"))
    neutro_arq = f"/AVB_TEMPLATES/{base.replace('audio_', 'avb_audio_')}.WAV"
    d, n_loc = AR.relink(d, mapping={c: neutro_arq for c in caminhos})
    trocas = {"locator": n_loc}
    bin_nome = bin_org or Path(src).stem
    # o rótulo do volume (o MC grava o nome do disco): o mesmo `AVB-MEDIA` dos outros modelos, que o
    # `avb_bin/audio._patch_volume` procura — tamanho variável, pelo campo
    volume = caminhos and next(iter(caminhos)).split("/")[2] if caminhos and next(iter(caminhos)).startswith("/Volumes/") else None
    if volume:
        d, a1 = AR.replace_field(d, volume, "AVB-MEDIA")
        d, a2 = AR.replace_field(d, b"\x00\x00" + volume.encode("latin-1"), b"\x00\x00AVB-MEDIA")
        trocas[volume] = a1 + a2
    # do mais longo para o mais curto: um texto contido em outro (o projeto no nome da bin) vem depois
    pares = {nome: igual(nome, rotulo), bin_nome: igual(bin_nome, "TEMPLATE Bin1")}
    if projeto:
        pares[projeto] = igual(projeto, "TEMPLATE")
    for f_nome in fontes:
        pares[f_nome] = igual(f_nome, f"AVB_AUDIO_{coding}_{bits}BIT_{canais}CH.WAV" if f_nome.lower().endswith(".wav")
                              else "AVBTAPE")
    for k, v in user.items():
        if not isinstance(v, str) or len(v) < 4 or k in ("UBITS", "Shoot Date", "Circled"):
            continue
        pares.setdefault(v, igual(v, "AVB_" + k.upper().replace(" ", "_")))
    for velho in sorted(pares, key=len, reverse=True):
        novo = pares[velho]
        n = d.count(velho.encode("latin-1"))
        d = d.replace(velho.encode("latin-1"), novo.encode("latin-1"))
        trocas[velho] = n
    for data in sorted({m.group() for m in re.finditer(rb"(?:19|20)\d\d[-/]\d\d[-/]\d\d \d\d:\d\d:\d\d", d)}):
        sep = data[4:5]
        d = d.replace(data, b"2024" + sep + b"01" + sep + b"01 00:00:00")
        trocas[data.decode()] = 1
    # ⭐ O clone acha o molde pelo NOME e quer master e fonte de arquivo com o MESMO (`clone.clip_info`: a data do
    # arquivo mora na fonte). O MC dá ao master a CENA/TAKE do BWF e à fonte o arquivo; no molde, o master leva o nome
    # neutro da fonte (pelo campo, tamanho variável) — a cena/take de cada WAV volta no `audio._como_o_avid`.
    arq_neutro = next((pares[x] for x in fontes if x.lower().endswith(".wav")), None)
    if arq_neutro and arq_neutro != pares[nome]:
        d, n_m = AR.replace_field(d, pares[nome], arq_neutro)
        trocas["master = fonte"] = n_m
        pares[nome] = arq_neutro
    print(f"master {nome!r} → formato {fmt} → {saida.name}, clipe {pares[nome]!r}")
    print("  trocas:", trocas)
    if not _abre_inteira(d):
        raise SystemExit("o modelo não abre inteiro — nada gravado")
    sujos = [t for t in list(pares) + [Path(c).stem for c in caminhos] + ["Volumes", "SSD"] if t]
    resto = [s.decode("latin-1") for s in re.findall(rb"[\x20-\x7e]{4,}", d)
             if any(t.lower() in s.decode("latin-1").lower() for t in sujos)]
    resto = [s for s in resto if "TEMPLATE" not in s and "AVB" not in s]
    if resto:
        raise SystemExit(f"sobrou identidade no modelo: {resto[:10]}")
    saida.write_bytes(d)
    man_p = TEMPLATES / "manifest.json"
    texto = man_p.read_text(encoding="utf-8")
    chave = f"audio|{coding}|{bits}|{canais}" + (f"|{variante}" if variante else "")
    if f'"{chave}"' in texto:                          # refeito: a linha velha sai (o clipe pode ter mudado)
        texto = "\n".join(x for x in texto.split("\n") if f'"{chave}"' not in x)
    if True:
        linha = json.dumps({chave: {"file": saida.name, "clip": pares[nome], "kind": "audio"}})[1:-1]
        texto = texto.replace('  "templates": {\n', '  "templates": {\n    ' + linha + ",\n", 1)
        json.loads(texto)
        man_p.write_text(texto, encoding="utf-8")
    print(f"  gravado {saida} e a chave {chave} no manifest.json")


if __name__ == "__main__":
    if len(sys.argv) > 2:
        main_mac(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else "")
    else:
        main(sys.argv[1])
