"""O bloco `titulo` da Carta → o gerador "Text" da página Edit do Resolve 19 (`Sm2TiGenerator` Rich).

Decodificado em 2026-09-27 do `TEXT MAPEAMENTO corrigido.drt` (o autor refez no Resolve as
variações T01–T19 do Avid). Banco: `protocolos/drt-drp/dados/text-gerador.json`.

O título inteiro mora no `<EffectFiltersBA>` do clipe: `[u32 2][u32 n][0x81] + zstd(protobuf)`,
com um registro por filtro, na ordem 48 (texto), 16 (sombra), 56 (contorno, só quando usado) e
54 (caixa). Cada filtro tem posições fixas (campo 9); vazia = `4a 00`.

Conversões Avid → Resolve (calibradas nas amostras; `avid.py` diz as unidades do modelo neutro):
- **posição:** o Avid mede em ALTURAS de quadro a partir do centro; o Resolve, em fração de
  cada eixo a partir do canto inferior esquerdo. X: `0.5 + x·altura/largura`; Y: `0.5 + y +
  corpo·0.354` (o Y do Avid é o da linha de base: com o corpo padrão, −0,0295 = o centro).
  Amostras: T14 (−0,607; 0,416) → (0,159; 0,945), feito à mão no Resolve em (0,172; 0,970).
- **corpo:** `fração da altura × 1152` (o padrão do Avid, 0,0833, vira o padrão do Resolve, 96).
  A escala visual não foi conferida lado a lado: `pendente`.
"""

from __future__ import annotations

import os
import re
import struct

import zstandard

FORMA = os.path.join(os.path.dirname(os.path.abspath(__file__)), "texto_r19.xml")

#: Blob padrão ("Basic Title") que o Resolve grava no campo 4 do texto — o valor de fábrica.
_PADRAO_P15 = bytes.fromhex(
    "2280010a7e427c7c0000000bb100000a0000006200610060000f0000000800000001000000380400240000001a"
    "0000004200610073006900630020005400690074006c00650002000000040137000000160000004f0070006500"
    "6e002000530061006e0073000000c042043f00120000002300460046004600460046004600ecf71e03")

CORPO_POR_ALTURA = 1152.0
#: `ancora` → o valor do Anchor do Text = 3 × vertical (0 base, 1 centro, 2 topo) + horizontal
#: (0 esquerda, 1 centro, 2 direita). Medidos: topo-esquerda 6 (2026-09-27), base-centro 1 e
#: topo-centro 7, centro-centro = ausente (gabarito do autor, 2026-10-04); os outros, pela regra.
ANCORA = {f"{v}_{h}": 3 * iv + ih for iv, v in enumerate(("base", "centro", "topo"))
          for ih, h in enumerate(("esquerda", "centro", "direita"))}
BASE_POR_CORPO = 0.354

# ── protobuf mínimo ────────────────────────────────────────────────────────────────────────


def _varint(n: int) -> bytes:
    fora = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            fora.append(b | 0x80)
        else:
            fora.append(b)
            return bytes(fora)


def _campo(n: int, dado) -> bytes:
    if isinstance(dado, int):
        return _varint(n << 3) + _varint(dado)
    return _varint((n << 3) | 2) + _varint(len(dado)) + dado


def _duplo(n: int, v: float) -> bytes:
    return _varint((n << 3) | 1) + struct.pack("<d", v)


def _valor(param: int, interno: bytes, padrao: bytes = b"") -> bytes:
    """Uma posição preenchida: `1 = param`, `3 = {1 = {interno}}` (+ o padrão, se houver)."""
    return _campo(1, param) + _campo(3, _campo(1, interno)) + padrao


def _ponto(param: int, x: float, y: float) -> bytes:
    # Par X/Y em BIG-ENDIAN (QDataStream), dentro do campo 7 — medido na posição e na sombra.
    return _valor(param, _campo(7, struct.pack(">dd", x, y)))


def _qcor(rgb, alfa: float = 1.0) -> bytes:
    """QColor serializada: 0x01 (RGB) + alfa, R, G, B em u16 BE + u16 0."""
    c = [alfa] + list(rgb)
    return b"\x01" + b"".join(struct.pack(">H", round(min(1, max(0, v)) * 0xFFFF)) for v in c) + b"\0\0"


def _filtro(tipo: int, cabeca_intocado: int | None, posicoes: list) -> bytes:
    """Um filtro: `1 = tipo`, a marca de intocado (campo 2 ou 3 = 0) SÓ quando nada foi
    preenchido (o 48 guarda o `3 = 0` sempre — medido), e as posições (campo 9)."""
    corpo = _campo(1, tipo)
    if cabeca_intocado is not None and (tipo == 48 or not any(posicoes)):
        corpo += _campo(cabeca_intocado, 0)
    for p in posicoes:
        corpo += _campo(9, p or b"")
    return _campo(1, corpo)


# ── o texto rico (parâmetro 15) ────────────────────────────────────────────────────────────


def _bloco(dado: bytes) -> bytes:
    """Todo bloco do texto rico leva um u32 com o PRÓPRIO tamanho (inclusive os 4 bytes)."""
    return struct.pack("<I", len(dado) + 4) + dado


def _u16(s: str) -> bytes:
    return _bloco(s.encode("utf-16-le"))


_ALINHA = {"centro": 0x04, "direita": 0x02, "justificado": 0x08}   # esquerda = ausente (Qt::Align*)
#: Font Case do Inspector (gabarito "Gabaritos finais" do autor, 2026-10-04): 1 byte antes do alinhamento.
CAIXA = {"maiusculas": 1, "minusculas": 2, "versalete": 3, "titulo": 4}
#: Font Style T² / T₂: 1 byte depois do tracking.
VERTICAL = {"sobrescrito": 1, "subscrito": 2}
# Bits do u32 de flags do formato: bit ligado = campo AUSENTE. A ORDEM dos campos no blob é a dos
# bits (medido: 22 variações de 2026-09-27 no 19 + 30 do gabarito de 2026-10-04 no 21.1).
_BIT_ESTILO, _BIT_CAIXA, _BIT_ALINHA, _BIT_TRACKING, _BIT_VERTICAL, _BIT_ENTRELINHA = 2, 3, 4, 7, 8, 9
_BIT_PESO, _BIT_ITALICO, _BIT_SOBRELINHA, _BIT_SUBLINHADO, _BIT_RISCADO = 11, 12, 13, 14, 15
_BIT_COR_SUBLINHADO, _BIT_SUBLINHADO_2, _BIT_COR2, _BIT_TRACO = 17, 18, 19, 20
_FLAGS_TUDO_AUSENTE = 0x031EFFFC | (1 << _BIT_ESTILO) | (1 << _BIT_ITALICO) | (1 << _BIT_COR2) | (1 << _BIT_TRACO)


def formato(familia: str, corpo: float, cor: str, *, estilo: str = "", alinhamento: str = "centro",
            peso: int | None = None, italico: int | None = None, cor2: str | None = None,
            traco: float | None = None, entrelinha: float | None = None,
            tracking: float | None = None, caixa: str | None = None, vertical: str | None = None,
            sobrelinha: bool = False, sublinhado: bool = False, riscado: bool = False) -> bytes:
    """O formato de um trecho do texto rico, nas unidades do Inspector:
    `entrelinha` (Line Spacing) = px de um quadro de 1080 SOMADOS à altura natural da linha da fonte
    (0 = o padrão; 257 afastou as linhas 386 px num quadro de 1620); `tracking` = o número do
    Inspector; `caixa` = Font Case (`CAIXA`); `vertical` = T²/T₂ (`VERTICAL`); `sobrelinha`,
    `sublinhado`, `riscado` = os três primeiros ícones de Font Style (conferidos pela imagem)."""
    flags = _FLAGS_TUDO_AUSENTE
    dado = _u16(familia) + struct.pack("<f", corpo)

    def poe(bit: int, b: bytes) -> None:
        nonlocal dado, flags
        dado += b
        flags &= ~(1 << bit)

    if estilo:
        poe(_BIT_ESTILO, _u16(estilo))
    if caixa in CAIXA:
        poe(_BIT_CAIXA, bytes([CAIXA[caixa]]))
    if alinhamento in _ALINHA:
        poe(_BIT_ALINHA, bytes([_ALINHA[alinhamento]]))
    if tracking:
        poe(_BIT_TRACKING, struct.pack("<f", tracking))
    if vertical in VERTICAL:
        poe(_BIT_VERTICAL, bytes([VERTICAL[vertical]]))
    if entrelinha:
        poe(_BIT_ENTRELINHA, struct.pack("<f", entrelinha))
    if peso is not None:
        poe(_BIT_PESO, struct.pack("<H", peso))
    if italico is not None:
        poe(_BIT_ITALICO, bytes([italico]))
    if sobrelinha:
        poe(_BIT_SOBRELINHA, b"\x01")
    if sublinhado:
        poe(_BIT_SUBLINHADO, b"\x01")
    if riscado:
        poe(_BIT_RISCADO, b"\x01")
    dado += _u16(cor)
    if sublinhado:
        # o sublinhado leva também a SUA cor (a do texto) e mais um byte 1 — medido no T08
        poe(_BIT_COR_SUBLINHADO, _u16(cor))
        poe(_BIT_SUBLINHADO_2, b"\x01")
    if cor2:
        poe(_BIT_COR2, _u16(cor2))
    if traco is not None:
        poe(_BIT_TRACO, struct.pack("<f", traco))
    return _bloco(dado + struct.pack("<I", flags))


#: O que vem depois de cada trecho: FECHA a linha ou CONTINUA nela (outra cor na mesma linha).
#: Medido: "Basic " branco + "Title" rosa numa linha só (`text com duas cores.drt`, 2026-09-27)
#: → `04 01` no trecho que continua e `01 00` no que fecha. Nas 22 variações, todo trecho fechava.
_FECHA_LINHA, _CONTINUA = b"\x01\x00", b"\x04\x01"


def texto_rico_trechos(trechos: list[tuple[str, bytes, bool]]) -> bytes:
    """O blob do parâmetro 15 a partir de TRECHOS `(texto, formato, fecha_a_linha)`: etiquetas
    (`b`, um `a` por trecho, um `` ` `` por formato), a lista dos trechos, cada trecho com o
    índice do SEU formato e a marca de fim de linha, e os formatos (um por trecho, na ordem)."""
    n = len(trechos)
    etiquetas = "b" + "a" * n + "`" * n
    dado = b"\x0b\xb1\x00\x00" + _bloco(etiquetas.encode("utf-16-le"))
    dado += _bloco(_bloco(b"".join(struct.pack("<I", i + 1) for i in range(n))) + b"\x38\x04\x00")
    for i, (texto, _fmt, fecha) in enumerate(trechos):
        dado += _bloco(_u16(texto) + struct.pack("<I", 1 + n + i) + (_FECHA_LINHA if fecha else _CONTINUA))
    dado += b"".join(fmt for _t, fmt, _f in trechos)
    return _bloco(dado)


def texto_rico(linhas: list[str], fmt: bytes) -> bytes:
    """Uma cor só: cada linha é um trecho que fecha a linha."""
    return texto_rico_trechos([(linha, fmt, True) for linha in linhas])


# ── do modelo neutro ao gerador ────────────────────────────────────────────────────────────


def _hex(rgb) -> str:
    return "#" + "".join(f"{round(min(1, max(0, v)) * 255):02x}" for v in rgb)


def efeitos_do_texto(titulo: dict, largura: int = 1920, altura: int = 1080) -> tuple[bytes, list[str]]:
    """(`EffectFiltersBA` pronto, avisos) da PRIMEIRA caixa do título."""
    avisos: list[str] = []
    caixas = titulo.get("caixas") or []
    cx = caixas[0] if caixas else {"texto": ""}
    if len(caixas) > 1:
        avisos.append(f"{len(caixas) - 1} caixa(s) de texto a mais ficaram só na Carta "
                      f"({', '.join(repr(c.get('texto', ''))[:40] for c in caixas[1:])})")
    padrao = not titulo.get("estilo_lido")
    fonte = cx.get("fonte") or {}
    corpo_frac = cx.get("corpo") or 0.0833333
    # `corpo_resolve`: já no "Size" do Resolve (px de um quadro de 1080 — medido 2026-10-04 no
    # caminho do Premiere). Sem ele, a conversão do Avid (fração × 1152, escala visual pendente).
    corpo = round(cx["corpo_resolve"] if cx.get("corpo_resolve") else corpo_frac * CORPO_POR_ALTURA, 2)
    cor = _hex(cx.get("cor") or [1, 1, 1])
    contorno = cx.get("contorno")
    estilo = fonte.get("estilo") or ""
    fmt = formato(fonte.get("familia") or "Open Sans", corpo, cor,
                  estilo=estilo, alinhamento=cx.get("alinhamento") or "centro",
                  # Sem face escolhida o Resolve grava só o peso 63; com face, a face manda e
                  # vem junto o peso 75 do Bold e o itálico 1 do Italic (T01, T07, T10, T11).
                  peso=63 if not estilo else (75 if "Bold" in estilo else None),
                  italico=1 if "Italic" in estilo else None,
                  cor2=_hex(contorno["cor"]) if contorno else (cor if cor != "#ffffff" else None),
                  traco=-float(round(contorno.get("espessura", 1) * 2)) / 2 if contorno else None,
                  entrelinha=cx.get("entrelinha"))
    if cx.get("trechos"):
        # Linhas de trechos coloridos (a trilha de notas: o "estamos aqui" em vermelho). Cada
        # trecho leva o seu formato; o último de cada linha a fecha (medido: `texto_rico_trechos`).
        runs = []
        for linha in cx["trechos"]:
            for k, (texto, rgb) in enumerate(linha):
                c = _hex(rgb)
                f = formato(fonte.get("familia") or "Open Sans", corpo, c, estilo=estilo,
                            alinhamento=cx.get("alinhamento") or "centro",
                            peso=63 if not estilo else None, cor2=c if c != "#ffffff" else None)
                runs.append((texto, f, k == len(linha) - 1))
        rico = texto_rico_trechos(runs)
    else:
        rico = texto_rico((cx.get("texto") or "").split("\n"), fmt)
    p15 = _valor(15, _campo(8, rico), _PADRAO_P15)

    pos48 = [p15, b"", b"", b"", b"", b"", b"", b""]
    # ANCHOR (posição 2, parâmetro 21, inteiro) — medido no "NOTAS DEMO … reposicionado" do autor
    # (2026-09-27): "esquerda + topo" = 6. Com ele, a Position é o canto SUPERIOR ESQUERDO da caixa:
    # o texto cresce para a direita e para baixo sem deslocar o que já está escrito.
    if cx.get("ancora") in ANCORA and ANCORA[cx["ancora"]] != 4:
        pos48[2] = _valor(21, _campo(4, ANCORA[cx["ancora"]]))
    p = cx.get("posicao")
    if cx.get("posicao_resolve"):
        # Já em fração do quadro do Resolve (X da esquerda, Y de baixo): sem conversão do Avid.
        pos48[3] = _ponto(17, *cx["posicao_resolve"])
    elif p and not padrao:
        x = 0.5 + float(p.get("x") or 0) * altura / largura
        y = 0.5 + float(p.get("y") or 0) + corpo_frac * BASE_POR_CORPO
        if abs(x - 0.5) > 1e-3 or abs(y - 0.5) > 1e-3:
            pos48[3] = _ponto(17, x, y)

    sombra = [b"", b"", b"", b""]
    s = cx.get("sombra")
    if s:
        dx, dy = (s.get("deslocamento") or [0.01, -0.01])[:2]
        # O Avid mede em alturas com Y para cima; o Resolve, em fração de cada eixo.
        sombra[1] = _ponto(38, float(dx) * altura / largura, -float(dy))
        if s.get("cor"):
            # Color do Drop Shadow (p37, slot 0): QColor como a do contorno (gabarito 2026-10-04)
            sombra[0] = _valor(37, _campo(6, _qcor(s["cor"])))
        avisos.append("sombra: posição e cor trazidas; desfoque e opacidade no padrão do Resolve "
                      "(Blur 20, Opacity 75)")

    tr = None
    if contorno:
        tr = [_valor(23, _campo(6, _qcor(contorno.get("cor") or [0, 0, 0]))),
              _valor(24, _campo(1, round(float(contorno.get("espessura") or 1) * 2)),
                     _campo(4, _campo(1, _campo(1, 2)))) + _campo(9, 0),
              _valor(172, _campo(5, 1))]

    caixa = [b""] * 8
    f = titulo.get("fundo")
    if f:
        # A opacidade do fundo é o controle "Opacity" (p34, slot 7: inteiro = % × 2; o padrão do
        # Resolve é 50) — a cor vai opaca. Medido 2026-10-04 (gabarito do autor, T21/T22, pela imagem):
        # antes, com a opacidade só na cor, um fundo opaco do Avid chegava a 50%.
        caixa[0] = _valor(27, _campo(6, _qcor(f.get("cor") or [0, 0, 0])))
        caixa[7] = _valor(34, _campo(1, round(float(f.get("opacidade", 1.0)) * 200)))
        if f.get("tela_cheia"):
            caixa[3] = _valor(31, _duplo(2, 1.0))
            caixa[4] = _valor(32, _duplo(2, 1.0))

    corpo_pb = (_filtro(48, 3, pos48) + _filtro(16, 2, sombra)
                + (_filtro(56, None, tr) if tr else b"") + _filtro(54, 2, caixa))
    if padrao:
        avisos.append(f"{titulo.get('titulador') or 'título'}: texto trazido; o estilo ficou no padrão "
                      "do Resolve")
    tf = titulo.get("transform")
    if tf:
        # O Transform do CLIPE (Zoom/Position do Inspector) mora no mesmo `EffectFiltersBA`: o
        # registro que o clipe de vídeo leva cru (0x80) entra antes dos filtros do texto, dentro
        # do zstd. Medido 2026-10-04 (Resolve 21.1): o Zoom animado vale no gerador, nas duas
        # ordens, com o tempo em quadros desde o início do clipe.
        from tools.inspect_drp import build_effect_filters_ba
        kf = tf.get("kf_zoom")
        x, y = tf.get("pos") or (0.0, 0.0)
        cru = bytes.fromhex(build_effect_filters_ba(
            zoom_x=tf.get("zoom"), zoom_y=tf.get("zoom"),
            pos_x=x or None, pos_y=y or None,
            animado={"zoom_x": kf, "zoom_y": kf} if kf else None))
        corpo_pb = cru[9:] + corpo_pb                   # sem o [u32 2][u32 tamanho][0x80]
    comp = zstandard.ZstdCompressor().compress(corpo_pb)
    return (struct.pack(">II", 2, len(comp) + 1) + b"\x81" + comp), avisos


def forma() -> str:
    with open(FORMA, encoding="utf-8") as f:
        return re.search(r"<Sm2TiGenerator\b.*?</Sm2TiGenerator>", f.read(), re.DOTALL).group(0)
