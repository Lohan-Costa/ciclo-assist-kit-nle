"""A CÓPIA RELINKADA de um .prproj: o mesmo projeto com cada mídia apontando para o arquivo que o casamento decidiu.

Premiere → Premiere (organograma aprovado pelo autor em 2026-10-22): o app nunca troca a mídia dentro do projeto do
editor — grava esta cópia e o Premiere importa dela só a sequência pedida (`app.project.importSequences`), que entra
como sequência NOVA com clipes novos; a original fica intacta.

Medido (banco `plugins/premiere-cep/api-extendscript.md`): 23.2 (2026-10-09, PRODUCAO_B e B11) e 26.5.2 (2026-10-22, R04:
corte idêntico em ticks, 0 offline, 143/144 pela referência). As regras de escrita:
- num `<Media>`, `FilePath`, `ActualMediaFilePath` e `RelativePath` levam o caminho novo; o `Title` acompanha o NOME do
  arquivo quando ele muda; o `OfflineReason` sai;
- o `FrameRect` do `VideoStream` acompanha o raster do arquivo novo (a ESCALA não: corrige-se pela API depois);
- um arquivo pode ter vários `<Media>` (o mesmo WAV três vezes no R04): todos mudam;
- o gzip sai com o cabeçalho que o Premiere escreve (FLG=0, sem nome: banco `prproj/relink-e-geometria.md` §0).
"""

from __future__ import annotations

import gzip
import ntpath
import re
import struct
import zlib

_MEDIA = re.compile(r'<Media ObjectUID="[^"]+"[^>]*>.*?</Media>', re.S)
_CAMPOS = ("FilePath", "ActualMediaFilePath", "RelativePath")


def ler_xml(caminho: str) -> str:
    with open(caminho, "rb") as f:
        dados = f.read()
    if dados[:2] == b"\x1f\x8b":
        dados = gzip.decompress(dados)
    return dados.decode("utf-8")


def gravar_xml(caminho: str, xml: str) -> None:
    dados = xml.encode("utf-8")
    co = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    corpo = co.compress(dados) + co.flush()
    with open(caminho, "wb") as f:
        f.write(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x13" + corpo
                + struct.pack("<II", zlib.crc32(dados) & 0xFFFFFFFF, len(dados) & 0xFFFFFFFF))


def _esc(texto: str) -> str:
    return texto.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _des(texto: str) -> str:
    return texto.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")


def relinkar(xml: str, troca: dict[str, str], raster: dict[str, tuple[int, int]] | None = None) -> tuple[str, dict]:
    """`troca` = {caminho declarado (o texto do `FilePath`): arquivo novo}; `raster` = {arquivo novo: (w, h)} quando o
    raster muda. Devolve o XML novo e `{media, caminhos}`: quantos `<Media>` e quantos caminhos distintos mudaram.
    A comparação do caminho declarado ignora a caixa (o Windows não a distingue; o Premiere grava como veio)."""
    chave = {k.lower(): v for k, v in troca.items() if k and v and k != v}
    raster = raster or {}
    feitos: set[str] = set()
    media = 0
    trocas_vs: list[tuple[str, tuple[int, int]]] = []

    def um(m: re.Match) -> str:
        nonlocal media
        bloco = m.group(0)
        fp = re.search(r"<FilePath>([^<]*)</FilePath>", bloco)
        if not fp:
            return bloco
        velho = _des(fp.group(1))
        novo = chave.get(velho.lower())
        if not novo:
            return bloco
        n = bloco
        for campo in _CAMPOS:
            n = re.sub(rf"<{campo}>[^<]*</{campo}>", lambda _m, c=campo: f"<{c}>{_esc(novo)}</{c}>", n)
        nome_velho, nome_novo = ntpath.basename(velho), ntpath.basename(novo)
        if nome_velho != nome_novo:
            n = n.replace(f"<Title>{_esc(nome_velho)}</Title>", f"<Title>{_esc(nome_novo)}</Title>")
        n = re.sub(r"\s*<OfflineReason>[^<]*</OfflineReason>", "", n)
        vs = re.search(r'<VideoStream ObjectRef="(\d+)"/>', n)
        if vs and novo in raster:
            trocas_vs.append((vs.group(1), raster[novo]))
        media += 1
        feitos.add(velho.lower())
        return n

    xml = _MEDIA.sub(um, xml)
    for oid, (w, h) in trocas_vs:
        xml = re.sub(r'(<VideoStream ObjectID="%s"[^>]*>.*?<FrameRect>)[^<]*(</FrameRect>)' % re.escape(oid),
                     lambda mm, w=w, h=h: f"{mm.group(1)}0,0,{w},{h}{mm.group(2)}", xml, count=1, flags=re.S)
    return xml, {"media": media, "caminhos": len(feitos)}


def gravar_copia(prproj: str, saida: str, troca: dict[str, str],
                 raster: dict[str, tuple[int, int]] | None = None) -> dict:
    """O .prproj `prproj` → `saida` relinkado (nunca o mesmo arquivo: o original fica intacto)."""
    if ntpath.normcase(prproj) == ntpath.normcase(saida):
        raise ValueError("a cópia não pode sobrescrever o projeto do editor")
    xml, conta = relinkar(ler_xml(prproj), troca, raster)
    gravar_xml(saida, xml)
    return conta
