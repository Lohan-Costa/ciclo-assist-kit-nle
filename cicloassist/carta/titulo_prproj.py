"""O título do Premiere no `.prproj`: ler e ESCREVER o blob do `Source Text` (o param 0 do `AE.ADBE Text`).

O mapa campo a campo mora no banco: `protocolos/prproj/titulo-essential-graphics.md` (medido no 23.6 Mac, o mesmo
formato no 26.5 Windows). O blob = 12 bytes de cabeçalho (`u32` tamanho do resto · `00000000` · `44332211`) + um
FlatBuffers SEM esquema publicado: por isso o leitor guarda TODO campo que encontra (inclusive os que o mapa não
explica) e o escritor devolve cada um com o mesmo tipo — mexer num título é trocar só os campos pedidos.

Árvore: `{"_": "tab", "campos": {índice: valor}}`, e cada valor é `("u8"|"u32"|"f32", número)`, `("str", texto)`,
`("tab", árvore)`, `("vec", [árvore, …])` ou `("vecstr", [texto, …])` (as fontes: nomes PostScript).
"""

from __future__ import annotations

import base64
import struct

CABECALHO_FIM = bytes.fromhex("0000000044332211")

#: os campos que APONTAM para outra coisa (o resto é escalar), por tipo de tabela — do mapa do banco
_FILHOS = {
    "raiz": {0: ("tab", "doc")},
    "doc": {0: ("vec", "trecho"), 1: ("vecstr", None), 10: ("tab", "cor"), 17: ("tab", "cor"), 37: ("vec", "sombra"),
            40: ("tab", "?")},
    "trecho": {0: ("str", None), 1: ("tab", "estilo")},
    "estilo": {2: ("tab", "cor"), 4: ("tab", "cor"), 17: ("vec", "contorno"), 21: ("tab", "?"), 23: ("tab", "?")},
    "contorno": {0: ("tab", "cor")},
    "sombra": {0: ("tab", "cor")},
}
#: escalares de 1 byte (bool/enum curto); os outros escalares conhecidos são de 4 bytes
_U8 = {"raiz": {4}, "doc": {11, 18, 21, 26, 27, 38, 43, 44}, "estilo": {5, 14, 15, 16}, "cor": {0, 1, 2},
       "contorno": {1}, "sombra": {1}}
_F32 = {"doc": {6, 7, 12, 13, 14, 15, 16, 19, 20, 34}, "estilo": {1, 6, 8, 9, 10}, "contorno": {2}}


class TituloErro(ValueError):
    pass


# ── ler ───────────────────────────────────────────────────────────────────────

def _u32(b, o): return struct.unpack_from("<I", b, o)[0]
def _i32(b, o): return struct.unpack_from("<i", b, o)[0]
def _u16(b, o): return struct.unpack_from("<H", b, o)[0]


def _tabela(b: bytes, t: int, tipo: str, prof: int = 0) -> dict:
    if prof > 16:
        raise TituloErro("tabelas aninhadas demais")
    v = t - _i32(b, t)
    vl, tl = _u16(b, v), _u16(b, v + 2)
    offs = [_u16(b, v + 4 + 2 * i) for i in range((vl - 4) // 2)]
    presentes = sorted((o, i) for i, o in enumerate(offs) if o)
    campos: dict[int, tuple] = {}
    for k, (o, i) in enumerate(presentes):
        p = t + o
        fim = presentes[k + 1][0] if k + 1 < len(presentes) else tl
        filho = _FILHOS.get(tipo, {}).get(i)
        if filho:
            alvo = p + _u32(b, p)
            if filho[0] == "str":
                n = _u32(b, alvo)
                campos[i] = ("str", b[alvo + 4:alvo + 4 + n].decode("utf-8"))
            elif filho[0] == "tab":
                campos[i] = ("tab", _tabela(b, alvo, filho[1], prof + 1))
            else:
                n = _u32(b, alvo)
                itens = []
                for j in range(n):
                    e = alvo + 4 + 4 * j
                    a = e + _u32(b, e)
                    itens.append(b[a + 4:a + 4 + _u32(b, a)].decode("utf-8") if filho[0] == "vecstr"
                                 else _tabela(b, a, filho[1], prof + 1))
                campos[i] = (filho[0], itens)
        elif i in _U8.get(tipo, ()) or fim - o == 1:
            campos[i] = ("u8", b[p])
        elif i in _F32.get(tipo, ()):
            campos[i] = ("f32", struct.unpack_from("<f", b, p)[0])
        else:
            campos[i] = ("u32", _u32(b, p))           # inteiro de 4 bytes (u32/enum) — ou um f32 que o mapa não conhece
    return {"_": "tab", "tipo": tipo, "campos": campos}


def ler(b64: str) -> dict:
    """A árvore do blob (`b64` = o `StartKeyframeValue` do param `Source Text`)."""
    cru = base64.b64decode(b64)
    if len(cru) < 16 or cru[4:12] != CABECALHO_FIM or _u32(cru, 0) != len(cru) - 12:
        raise TituloErro("não é o blob do Source Text (cabeçalho)")
    b = cru[12:]
    return _tabela(b, _u32(b, 0), "raiz")


# ── escrever ──────────────────────────────────────────────────────────────────

class _Escrita:
    """FlatBuffers escrito de FRENTE para trás: cada tabela vem depois do vtable dela e ANTES dos filhos (os offsets
    `uoffset` apontam sempre para frente, como exige o formato). Tudo alinhado a 4."""

    def __init__(self):
        self.b = bytearray(4)                      # o offset da raiz, preenchido no fim

    def _alinhar(self, n=4):
        while len(self.b) % n:
            self.b.append(0)

    def tabela(self, arv: dict) -> int:
        campos = arv["campos"]
        # os campos de 4 bytes primeiro, depois os de 1 (sem buracos de alinhamento entre eles)
        ordem = sorted(campos, key=lambda i: (campos[i][0] == "u8", i))
        n = max(campos) + 1 if campos else 0
        pos: dict[int, int] = {}
        o = 4                                       # o soffset do vtable vem primeiro
        for i in ordem:
            pos[i] = o
            o += 1 if campos[i][0] == "u8" else 4
        tam_tab = o                                 # exato, como o Premiere grava (o alinhamento vem antes do próximo objeto)
        self._alinhar()
        vt = len(self.b)
        self.b += struct.pack("<HH", 4 + 2 * n, tam_tab)
        for i in range(n):
            self.b += struct.pack("<H", pos.get(i, 0))
        self._alinhar()
        t = len(self.b)
        self.b += struct.pack("<i", t - vt)
        self.b += bytes(tam_tab - 4)
        pendentes = []
        for i in ordem:
            tp, val = campos[i]
            p = t + pos[i]
            if tp == "u8":
                self.b[p] = int(val) & 0xFF
            elif tp == "u32":
                struct.pack_into("<I", self.b, p, int(val))
            elif tp == "f32":
                struct.pack_into("<f", self.b, p, float(val))
            else:
                pendentes.append((p, tp, val))
        for p, tp, val in pendentes:
            alvo = self._filho(tp, val)
            struct.pack_into("<I", self.b, p, alvo - p)
        return t

    def _filho(self, tp: str, val) -> int:
        self._alinhar()
        if tp == "str":
            dados = val.encode("utf-8")
            alvo = len(self.b)
            self.b += struct.pack("<I", len(dados)) + dados + b"\0"
            return alvo
        if tp == "tab":
            return self.tabela(val)
        alvo = len(self.b)                          # vetor: n e os offsets, depois as tabelas (ou strings)
        self.b += struct.pack("<I", len(val)) + bytes(4 * len(val))
        for j, item in enumerate(val):
            e = alvo + 4 + 4 * j
            struct.pack_into("<I", self.b, e, (self._filho("str", item) if tp == "vecstr" else self.tabela(item)) - e)
        return alvo


def escrever(arv: dict) -> str:
    """A árvore de volta ao base64 do `StartKeyframeValue`."""
    w = _Escrita()
    struct.pack_into("<I", w.b, 0, w.tabela(arv))
    w._alinhar()
    corpo = bytes(w.b)
    return base64.b64encode(struct.pack("<I", len(corpo)) + CABECALHO_FIM + corpo).decode("ascii")


# ── o título do AVID (o modelo neutro da Carta) num blob ──────────────────────
#
# O modelo neutro (`modulos/conformar/motor/titulos/avid.py`) mede como o Avid: `corpo` = fração da ALTURA do quadro,
# `posicao` = o centro da caixa em ALTURAS a partir do centro do quadro (Y para cima), cores RGB de 0 a 1. O Titler+
# LEGACY (o da PRODA_CORTE) chega só com o texto (`estilo_lido: false`): vai com o estilo padrão do Avid, dito.

#: o corpo padrão do Titler+ (fração da altura), o mesmo que o Resolve usa como padrão (`titulos/resolve.py`)
CORPO_PADRAO = 0.0833333
#: a fonte quando o Avid não diz qual é (o Legacy): a do Basic Title de fábrica não é a do Avid; Arial é o neutro
FONTE_PADRAO = "ArialMT"
_ALINHAMENTO = {"esquerda": 0, "direita": 1, "centro": 2}
#: os campos do mapa (banco) que o PAINEL controla — zerados antes de compor; os outros (21, 23 do estilo; 26, 27, 38,
#: 40, 43, 44 do documento) são de estrutura e ficam como o Premiere os gravou no molde
_ESTILO_CONHECIDO = (1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 24)
_DOC_CONHECIDO = (4, 5, 6, 7, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 34, 37)


def _u8(x: float) -> int:
    return max(0, min(255, round(float(x) * 255)))


def _tab_cor(rgb) -> tuple:
    return ("tab", {"_": "tab", "tipo": "cor", "campos": {i: ("u8", _u8(v)) for i, v in enumerate(rgb[:3])}})


def postscript_de(familia: str, estilo: str) -> tuple[str, bool]:
    """(nome PostScript, achada nesta máquina?). Pelo índice de fontes do Conformar (`titulos/fontes.py`); fora dele,
    a dedução `Familia-Estilo` sem espaços (o padrão Adobe/Monotype) — e o Premiere mostra a fonte faltando."""
    import sys
    from pathlib import Path
    raiz = Path(__file__).resolve().parents[2] / "modulos" / "conformar" / "motor"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    try:
        from titulos import fontes  # noqa: PLC0415
        idx = fontes.indice()
    except Exception:  # noqa: BLE001 — sem o índice, a dedução
        idx = {}
    f, e = (familia or "").strip().lower(), (estilo or "Regular").strip().lower() or "regular"
    candidatas = [(ps, d) for ps, d in idx.items() if str(d.get("familia", "")).lower() == f]
    for ps, d in candidatas:
        if str(d.get("face", "")).lower() == e:
            return d.get("postscript") or _nome_ps(idx, ps), True
    if candidatas and e == "regular":
        return _nome_ps(idx, candidatas[0][0]), True
    nome = (familia or "").replace(" ", "")
    return (f"{nome}-{estilo.replace(' ', '')}" if estilo and e != "regular" else nome), False


def _nome_ps(idx: dict, chave: str) -> str:
    """O índice guarda a chave em minúsculas; o nome com as maiúsculas vem do próprio arquivo (o nome 6)."""
    d = idx.get(chave) or {}
    try:
        import sys  # noqa: F401
        from titulos import fontes  # noqa: PLC0415
        for nomes, _a, _l in fontes._faces_do_arquivo(d["arquivo"]):
            if (nomes.get(6) or "").lower() == chave:
                return nomes[6]
    except Exception:  # noqa: BLE001
        pass
    return chave


def compor_do_avid(arv: dict, titulo: dict, caixa: dict, largura: int, altura: int) -> tuple[dict, tuple | None, list]:
    """Escreve no blob `arv` (a camada de texto do molde) UMA caixa do título do Avid. Devolve (arv, a posição da camada
    normalizada ao quadro ou None = a do molde, o centro, avisos). Um campo que o Avid não diz fica no padrão do Avid."""
    avisos: list[str] = []
    doc = arv["campos"][0][1]["campos"]
    trechos = doc[0][1]
    trecho = trechos[0]["campos"]
    doc[0] = ("vec", [trechos[0]])                      # um trecho: o estilo é um só por caixa no modelo neutro
    estilo = trecho[1][1]["campos"]
    # ⛔ ZERAR o estilo do molde antes: a camada nova do Premiere HERDA o último estilo usado na sessão (medido no 26.5,
    #   2026-11-20: o molde feito depois de um título de teste trouxe fundo verde, itálico, caixa alta, sombra…). O
    #   que o Avid não diz fica no padrão — ausente no blob é o padrão do Premiere.
    for k in _ESTILO_CONHECIDO:
        estilo.pop(k, None)
    for k in _DOC_CONHECIDO:
        doc.pop(k, None)
    # o texto (a quebra de linha do Premiere é \r — banco `prproj/estruturas.md`)
    trecho[0] = ("str", str(caixa.get("texto") or "").replace("\r\n", "\r").replace("\n", "\r"))
    if not titulo.get("estilo_lido"):
        avisos.append(f"título {titulo.get('titulador') or 'do Avid'}: o estilo não é lido; foi com o padrão "
                      "(Arial, centro)")
    # a fonte
    f = caixa.get("fonte") or {}
    if f.get("familia"):
        ps, achada = postscript_de(f["familia"], f.get("estilo") or "")
        if not achada:
            avisos.append(f"fonte {f['familia']} {f.get('estilo') or ''}".strip() + " não está nesta máquina")
    else:
        ps = FONTE_PADRAO
    doc[1] = ("vecstr", [ps])
    estilo[0] = ("u32", 0)
    # o corpo, a cor
    estilo[1] = ("f32", round(float(caixa.get("corpo") or CORPO_PADRAO) * altura, 3))
    if caixa.get("cor"):
        estilo[2] = _tab_cor(caixa["cor"])
    else:
        estilo.pop(2, None)                             # ausente = branco
    # o contorno: ligado só se o Avid tiver
    if caixa.get("contorno"):
        estilo[5] = ("u8", 1)
        estilo[4] = _tab_cor(caixa["contorno"].get("cor") or (0, 0, 0))
        estilo[6] = ("f32", float(caixa["contorno"].get("espessura") or 1.0))
        estilo[24] = ("u32", 2)
        avisos.append("contorno: a espessura do Avid foi como está (a unidade não foi medida)")
    # alinhamento horizontal; vertical ao CENTRO (o Avid posiciona pelo centro da caixa)
    doc[4] = ("u32", _ALINHAMENTO.get(caixa.get("alinhamento") or "centro", 2))
    doc[5] = ("u32", 1)
    # a sombra
    if caixa.get("sombra"):
        s = caixa["sombra"]
        dx, dy = (list(s.get("deslocamento") or [0, 0]) + [0, 0])[:2]
        doc[11] = ("u8", 1)
        doc[10] = _tab_cor(s.get("cor") or (0, 0, 0))
        import math
        # ⭐ o ângulo do Premiere é de onde vem a LUZ (135° = sombra para baixo-direita, o padrão dele e do Avid): o
        #   deslocamento (Y para cima) aponta para a sombra, então o ângulo é o dele + 180°
        doc[13] = ("f32", round((math.degrees(math.atan2(float(dy), float(dx))) + 180) % 360, 3))
        doc[14] = ("f32", round(math.hypot(float(dx), float(dy)) * altura, 3))
        doc[16] = ("f32", round(float(s.get("suavidade") or 0.0), 3))
        if s.get("opacidade") is not None:
            doc[12] = ("f32", round(float(s["opacidade"]) * 100, 3))
        avisos.append("sombra: distância e desfoque na unidade do Avid, sem medida no Premiere")
    if titulo.get("fundo"):
        avisos.append("fundo de tela cheia do título: não vai (o fundo do Premiere é só atrás do texto)")
    pos = None
    if caixa.get("linha_de_base_y") is not None and not caixa.get("posicao"):
        # ⭐ o Legacy diz onde fica a LINHA DE BASE; no Premiere, com o vertical ao centro, a linha de base cai no ponto
        #   da posição (medido no 26.5: posição 540 → o pé das maiúsculas em 541). X ao centro (o Legacy da PRODA está
        #   centrado; outro alinhamento do Legacy: não medido)
        pos = (0.5, round(float(caixa["linha_de_base_y"]), 6))
    elif caixa.get("posicao"):
        p = caixa["posicao"]
        pos = (round(0.5 + float(p.get("x") or 0) * altura / largura, 6), round(0.5 - float(p.get("y") or 0), 6))
        avisos.append("posição: convertida pelo centro da caixa (sem medida no Premiere)")
    return arv, pos, avisos
