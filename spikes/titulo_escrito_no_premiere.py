"""ESCREVER um título no `.prproj` e reabrir no Premiere: o mapa do `Source Text` (banco
`protocolos/prproj/titulo-essential-graphics.md`) conferido de uma vez — cada valor é inconfundível, e quem diz se o
campo é aquele é o painel Properties do Premiere reaberto (lido na foto).

    python spikes/titulo_escrito_no_premiere.py <origem.prproj> <destino.prproj>

A origem tem UM título (a camada "New Text Layer" do 26.5); o destino é uma cópia NOVA com o blob trocado e o
`BinaryHash` novo (12 bytes aleatórios + o tamanho, banco `prproj/escrita.md`). Sai 0 se escreveu e a releitura
devolve exatamente o que foi pedido.
"""

from __future__ import annotations

import gzip
import os
import re
import struct
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cicloassist.carta import titulo_prproj as T  # noqa: E402

#: o que se escreve — valores que não se confundem com nenhum padrão
PEDIDO = {
    "texto": "producao-a",       # minúsculo de propósito: o All Caps tem de aparecer MAIÚSCULO na tela
    "fonte": "ArialMT",
    "estilo": {
        1: ("f32", 137.0),          # corpo
        2: ("cor", (0xC8, 0x32, 0x14)),   # fill
        4: ("cor", (0x1E, 0x5A, 0xA0)),   # stroke
        5: ("u8", 1),               # stroke ligado
        6: ("f32", 7.0),            # espessura
        8: ("f32", 23.0),           # tracking
        12: ("u32", 2),             # All Caps
        15: ("u8", 1),              # Faux Italic
        24: ("u32", 2),             # stroke Outer
    },
    "doc": {
        4: ("u32", 2),              # alinhamento: centro
        10: ("cor", (0x78, 0x14, 0xA0)),  # cor da sombra
        11: ("u8", 1),              # sombra ligada
        12: ("f32", 60.0),          # opacidade da sombra
        13: ("f32", 200.0),         # ângulo
        14: ("f32", 12.0),          # distância
        15: ("f32", 3.0),           # tamanho
        16: ("f32", 27.0),          # desfoque
        17: ("cor", (0x50, 0xA0, 0x3C)),  # cor do fundo
        18: ("u8", 1),              # fundo ligado
        19: ("f32", 45.0),          # opacidade do fundo
        20: ("f32", 9.0),           # tamanho do fundo
        34: ("f32", 6.0),           # cantos do fundo
    },
}


def _cor(rgb):
    return ("tab", {"_": "tab", "tipo": "cor", "campos": {0: ("u8", rgb[0]), 1: ("u8", rgb[1]), 2: ("u8", rgb[2])}})


def _aplicar(campos: dict, pedido: dict) -> None:
    for i, (tp, v) in pedido.items():
        campos[i] = _cor(v) if tp == "cor" else (tp, v)


def compor(arv: dict) -> dict:
    doc = arv["campos"][0][1]["campos"]
    trecho = doc[0][1][0]["campos"]
    trecho[0] = ("str", PEDIDO["texto"])
    estilo = trecho[1][1]["campos"]
    _aplicar(estilo, PEDIDO["estilo"])
    estilo[0] = ("u32", 0)                       # a fonte 0 do vetor
    doc[1] = ("vecstr", [PEDIDO["fonte"]])
    _aplicar(doc, PEDIDO["doc"])
    return arv


_PARAM = re.compile(r"(<Name>Source Text</Name>.*?<StartKeyframeValue Encoding=\"base64\" BinaryHash=\")"
                    r"([0-9a-f-]+)(\">)([^<]+)(</StartKeyframeValue>)", re.S)


def main(origem: str, destino: str) -> int:
    if Path(destino).exists():
        print(f"⛔ {destino} já existe: escreva numa cópia NOVA")
        return 2
    xml = gzip.open(origem).read().decode("utf-8")
    achados = _PARAM.findall(xml)
    if len(achados) != 1:
        print(f"⛔ a origem tem {len(achados)} Source Text com valor próprio (esperado 1)")
        return 2
    novo = T.escrever(compor(T.ler(achados[0][3].strip())))
    tam = len(__import__("base64").b64decode(novo)) + 12
    h = os.urandom(12).hex()
    hash_novo = f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:24]}{struct.pack('>I', tam).hex()}"
    xml2 = _PARAM.sub(lambda m: m.group(1) + hash_novo + m.group(3) + novo + "\n\t\t" + m.group(5), xml, count=1)
    with gzip.open(destino, "wb") as fh:
        fh.write(xml2.encode("utf-8"))
    relido = T.ler(_PARAM.findall(gzip.open(destino).read().decode("utf-8"))[0][3].strip())
    ok = relido == compor(T.ler(achados[0][3].strip()))
    print(f"{'✅' if ok else '⛔'} {destino}: blob de {tam - 12} bytes, hash {hash_novo}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2]))
