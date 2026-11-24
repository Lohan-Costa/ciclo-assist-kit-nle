"""Marcadores de TIMELINE e cor LOCAL do segmento no DRT (os "Sinais do Import").

Decodificado em 2026-09-27 das amostras do autor (`CLIP COLOR E MARQUER.drt`, `16 segmentos e
cores.drt`); banco `protocolos/drt-drp/dados/marcadores-e-cores.json`. Regra de ofício do autor
(banco `transversal/operacoes-de-nle.md` §J.3): marcador na TIMELINE, cor LOCAL do segmento.

Nada disto mora na sequência: são blocos "travados" do `project.xml` (`Sm2LockableBlobMap ›
LocableBlobSet`), um por dono, com um mapa Qt `{"BlobData": QByteArray}` no `FieldsBlob`:
- cor local: `Sm2TiItemLockableBlob`, dono = o clipe da timeline; `BlobData` = protobuf campo 5;
- marcadores: `Sm2SequenceLockableBlob`, dono = a `Sm2Sequence` (no `MpFolder.xml`).
"""

from __future__ import annotations

import struct
import uuid

import zstandard

#: Cor de CLIPE (local e global usam a mesma tabela). Números pares FORA da ordem do menu, e
#: SEM vermelho — só o marcador tem vermelho.
COR_DE_CLIPE = {"Orange": 28, "Apricot": 16, "Yellow": 32, "Lime": 22, "Olive": 26, "Green": 2,
                "Teal": 4, "Navy": 24, "Blue": 6, "Purple": 8, "Violet": 30, "Pink": 10, "Tan": 12,
                "Beige": 18, "Brown": 14, "Chocolate": 20}
#: Cor de MARCADOR: potências de 2 na ordem do menu — mas o Resolve PULA o 256 (Fuchsia = 512).
COR_DE_MARCADOR = {"Blue": 2, "Cyan": 4, "Green": 8, "Yellow": 16, "Red": 32, "Pink": 64,
                   "Purple": 128, "Fuchsia": 512, "Rose": 1024, "Lavender": 2048, "Sky": 4096,
                   "Mint": 8192, "Lemon": 16384, "Sand": 32768, "Cocoa": 65536, "Cream": 131072}
#: O código de fábrica (decidido pelo autor em 2026-09-27; a equipe muda em Ajustes).
#: `distorcao` (o Reformat Stretch, 2026-09-27): cores que nenhum outro sinal usa, para os takes
#: esticados saltarem aos olhos na timeline — é o erro que o colorista não pode deixar passar.
CODIGO = {"distorcao": {"marcador": "Fuchsia", "clipe": "Pink"},
          "refazer": {"marcador": "Red", "clipe": "Chocolate"},
          "conferir": {"marcador": "Yellow", "clipe": "Yellow"}}
#: A palavra-chave de todo marcador da automação: o colorista filtra (e apaga) só os nossos.
PALAVRA_CHAVE = "DLPC"
#: As categorias, na ordem da tela de Ajustes, com o que cai em cada uma (só leitura: mudar uma
#: situação de categoria ficou para depois — organograma aprovado pelo autor em 2026-09-27).
CATEGORIAS = {
    "distorcao": {"rotulo": "Possível distorção", "sub": "avisar a produção",
                  "quais": ["Reformat Stretch"]},
    "refazer": {"rotulo": "Refazer", "sub": "no destino",
                "quais": ["estabilizador", "efeito não traduzido", "efeito animado que não se reproduz"]},
    "conferir": {"rotulo": "Conferir", "sub": "",
                 "quais": ["cor no Avid", "velocidade", "efeito animado traduzido"]},
}
MAX_PALAVRA = 32


def de_fabrica() -> dict:
    return {"cores": {c: dict(v) for c, v in CODIGO.items()}, "palavra": PALAVRA_CHAVE}


def validar_codigo(d) -> dict:
    """O código de cores da equipe (`{"cores": {categoria: {marcador, clipe}}, "palavra"}`) →
    o mesmo, conferido. O que faltar ou não existir nas tabelas do Resolve volta ao de fábrica:
    um arquivo velho ou mexido à mão nunca derruba o Trazer."""
    fora = de_fabrica()
    d = d if isinstance(d, dict) else {}
    cores = d.get("cores") if isinstance(d.get("cores"), dict) else {}
    for cat in fora["cores"]:
        v = cores.get(cat) if isinstance(cores.get(cat), dict) else {}
        if v.get("marcador") in COR_DE_MARCADOR:
            fora["cores"][cat]["marcador"] = v["marcador"]
        if v.get("clipe") in COR_DE_CLIPE:
            fora["cores"][cat]["clipe"] = v["clipe"]
    p = d.get("palavra")
    if isinstance(p, str):
        p = "".join(ch for ch in p.strip() if ch.isprintable() and ch not in ",;")[:MAX_PALAVRA]
        if p:
            fora["palavra"] = p
    return fora


def repeticoes(codigo: dict) -> list[str]:
    """Avisos (não erros) quando duas categorias dividem a mesma cor: a equipe pode querer."""
    avisos = []
    cats = list(CATEGORIAS)
    for campo, nome in (("marcador", "marcador"), ("clipe", "segmento")):
        for i, a in enumerate(cats):
            for b in cats[i + 1:]:
                ca, cb = codigo["cores"][a][campo], codigo["cores"][b][campo]
                if ca == cb:
                    avisos.append(f"{CATEGORIAS[a]['rotulo']} e {CATEGORIAS[b]['rotulo']} estão com o "
                                  f"mesmo {nome} {ca}")
    return avisos


def _varint(n: int) -> bytes:
    fora = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        fora.append(b | (0x80 if n else 0))
        if not n:
            return bytes(fora)


def _campo(n: int, dado) -> bytes:
    if isinstance(dado, int):
        return _varint(n << 3) + _varint(dado)
    return _varint((n << 3) | 2) + _varint(len(dado)) + dado


def _blob_data(pb: bytes, comprimir: bool = False) -> bytes:
    """`[u32 0x2711][u32 n][0x80 cru | 0x81 zstd]` + o protobuf (medido nos dois tipos)."""
    corpo = (b"\x81" + zstandard.ZstdCompressor().compress(pb)) if comprimir else (b"\x80" + pb)
    return struct.pack(">II", 0x2711, len(corpo)) + corpo


def _fields_blob(dado: bytes) -> str:
    """O mapa Qt `{"BlobData": QByteArray}` do `FieldsBlob` (medido byte a byte)."""
    chave = "BlobData".encode("utf-16-be")
    return (struct.pack(">III", 1, 1, len(chave)) + chave + struct.pack(">I", 0x0C) + b"\x00"
            + struct.pack(">I", len(dado)) + dado).hex()


def _elemento(tipo: str, dono: str, dado: bytes) -> str:
    return (f"<Element>\n     <{tipo} DbId=\"{uuid.uuid4()}\">\n      <FieldsBlob>{_fields_blob(dado)}"
            f"</FieldsBlob>\n      <BlobOwner>{dono}</BlobOwner>\n      <DbSavedTime>0</DbSavedTime>\n"
            f"     </{tipo}>\n    </Element>\n    ")


def cor_local(dono: str, cor: str) -> str:
    """O bloco que pinta o segmento `dono` (DbId do clipe da timeline) com a cor de clipe `cor`."""
    return _elemento("Sm2TiItemLockableBlob", dono, _blob_data(_campo(5, COR_DE_CLIPE[cor])))


def pb_marcadores(marcadores: list[dict]) -> bytes:
    """`{quadro, cor, nome, nota, duracao, palavras}` → o protobuf do bloco da sequência:
    campo 2 = envelope { campo 1 por marcador = { 1: quadro, 2: [u32 2][u32 n] + { 1: { 1: cor,
    2: palavra-chave…, 3: nota, 3: duração (TEXTO), 3: nome } } } }."""
    entradas = b""
    for m in marcadores:
        dentro = _campo(1, COR_DE_MARCADOR[m["cor"]])
        for p in m.get("palavras") or []:
            dentro += _campo(2, p.encode("utf-8"))
        dentro += (_campo(3, (m.get("nota") or "").encode("utf-8"))
                   + _campo(3, str(int(m.get("duracao") or 1)).encode("utf-8"))
                   + _campo(3, (m.get("nome") or "").encode("utf-8")))
        inner = _campo(1, dentro)
        entradas += _campo(1, _campo(1, int(m["quadro"])) + _campo(2, struct.pack(">II", 2, len(inner)) + inner))
    return _campo(2, entradas)


def marcadores(dono: str, lista: list[dict]) -> str:
    """O bloco dos marcadores da timeline (`dono` = DbId da `Sm2Sequence`)."""
    return _elemento("Sm2SequenceLockableBlob", dono, _blob_data(pb_marcadores(lista), comprimir=True))


def no_project_xml(project_xml: str, elementos: list[str]) -> str:
    """Põe os blocos dentro do `LocableBlobSet` (a grafia é do Resolve)."""
    if not elementos:
        return project_xml
    return project_xml.replace("<LocableBlobSet>\n", "<LocableBlobSet>\n    " + "".join(elementos), 1)
