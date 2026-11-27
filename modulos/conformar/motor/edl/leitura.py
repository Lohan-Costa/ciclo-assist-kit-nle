"""Ler uma EDL como o Premiere 26.0.2 e o Media Composer 25.12 a escrevem (banco `protocolos/edl/README.md`, 2026-11-25).

O que o leitor tem de aguentar — cada item medido nas EDLs da rodada 1:

- ⛔ a CODIFICAÇÃO: o MC escreve UTF-8; o Premiere no Mac, MacRoman (`Ç` = 0x82). Tenta-se UTF-8 estrito; se falhar,
  MacRoman quando há bytes de 0x80–0x9F (letras no MacRoman, pontuação no cp1252), senão cp1252. A escolha vai no resultado.
- o REEL de qualquer largura (8 no CMX 3600; até 129 colunas, com espaços, no File_129): a linha é lida da DIREITA
  (os quatro TC, a transição, o canal) e o que sobra depois do número é o reel.
- o número do evento com 3 ou 6 dígitos; canais `V`, `A`, `A2`…`A10`, `AA`, `AA/V`, `B`; transições `C`, `D`, `Wnnn`, `K`.
- o par de linhas de uma transição (o `C` de duração zero e o `D`/`W` com o mesmo número): vira UM evento com `de` (a fonte
  que sai) e o resto (a que entra).
- comentários com e sem espaço depois do `*` (`* FROM CLIP NAME:` no Premiere e no CMX do MC; `*FROM CLIP NAME:` no
  File_129 do MC), e o `M2` (velocidade em quadros por segundo) que vem depois da linha do evento, antes ou depois dos
  comentários.

Não confere nada: devolve o que a lista diz. Quem confere contra a montagem é o conferidor.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_TC = r"(\d{2}[:;]\d{2}[:;]\d{2}[:;.]\d{2})"
_EVENTO = re.compile(
    r"^(?P<num>\d{3,6})\s+(?P<resto>.*?)\s+(?P<canal>V|A\d*|AA|AA/V|A\d*/V|B|NONE)\s+"
    r"(?P<trans>C|D|W\d{3}|K[BO]?)\s+(?:(?P<dur>\d{3})\s+)?"
    + _TC + r"\s+" + _TC + r"\s+" + _TC + r"\s+" + _TC + r"\s*$")
_M2 = re.compile(r"^M2\s+(?P<reel>.*?)\s+(?P<vel>-?\d+(?:\.\d+)?)\s+" + _TC + r"\s*$")
_AUD = re.compile(r"^AUD\s+(\d+)(?:\s+(\d+))?\s*$")
_COMENTARIO = re.compile(r"^\*\s?(?P<chave>[A-Z][A-Z ]*?)\s*:\s*(?P<valor>.*)$")


@dataclass
class Evento:
    num: int
    reel: str
    canal: str
    transicao: str = "C"            # C, D, Wnnn, K…
    duracao: int = 0                # da transição, em quadros
    src_in: str = ""
    src_out: str = ""
    rec_in: str = ""
    rec_out: str = ""
    de: dict | None = None          # numa transição: a fonte que SAI (reel, src_in, src_out)
    velocidade: float | None = None  # o M2, em quadros por segundo
    clip: str = ""                  # FROM CLIP NAME (numa transição: o TO, a fonte que entra)
    clip_de: str = ""               # FROM CLIP NAME numa transição (a que sai)
    arquivo: str = ""               # SOURCE FILE, quando houver
    comentarios: list[str] = field(default_factory=list)

    @property
    def canais(self) -> list[str]:
        """`AA/V` → ['V', 'A', 'A2']; `A3` → ['A3']."""
        if self.canal in ("NONE", ""):
            return []
        out = []
        for parte in self.canal.split("/"):
            out += ["A", "A2"] if parte == "AA" else [parte]
        return out


@dataclass
class Edl:
    titulo: str = ""
    fcm: str = ""                   # "NON-DROP FRAME" | "DROP FRAME"
    codificacao: str = ""
    eventos: list[Evento] = field(default_factory=list)
    nao_lidas: list[str] = field(default_factory=list)

    @property
    def drop_frame(self) -> bool:
        return self.fcm.upper().startswith("DROP")


def decodificar(dados: bytes) -> tuple[str, str]:
    if dados.startswith(b"\xef\xbb\xbf"):
        return dados[3:].decode("utf-8"), "utf-8-sig"
    try:
        return dados.decode("utf-8"), "utf-8"
    except UnicodeDecodeError:
        pass
    if any(0x80 <= b <= 0x9F for b in dados):
        return dados.decode("mac_roman"), "mac_roman"
    return dados.decode("cp1252", errors="replace"), "cp1252"


def ler(dados: bytes | str) -> Edl:
    if isinstance(dados, bytes):
        texto, cod = decodificar(dados)
    else:
        texto, cod = dados, "str"
    edl = Edl(codificacao=cod)
    atual: Evento | None = None
    for bruta in texto.splitlines():
        linha = bruta.rstrip()
        if not linha.strip():
            continue
        if linha.startswith("TITLE:"):
            edl.titulo = linha[6:].strip()
            continue
        if linha.startswith("FCM:"):
            if not edl.fcm:                       # o Premiere repete o FCM dentro da transição
                edl.fcm = linha[4:].strip()
            continue
        m = _EVENTO.match(linha)
        if m:
            g = m.groupdict()
            tcs = m.groups()[-4:]
            num = int(g["num"])
            reel = g["resto"].strip()
            ev = Evento(num=num, reel=reel, canal=g["canal"], transicao=g["trans"], duracao=int(g["dur"] or 0),
                        src_in=tcs[0], src_out=tcs[1], rec_in=tcs[2], rec_out=tcs[3])
            # a 2ª linha de uma transição: mesmo número, mesmo canal, logo depois de um C
            if (atual is not None and atual.num == num and atual.canal == ev.canal and atual.transicao == "C"
                    and ev.transicao != "C" and atual.de is None):
                ev.de = {"reel": atual.reel, "src_in": atual.src_in, "src_out": atual.src_out}
                ev.comentarios = atual.comentarios
                edl.eventos[-1] = ev
            else:
                edl.eventos.append(ev)
            atual = ev
            continue
        m = _M2.match(linha)
        if m and atual is not None:
            atual.velocidade = float(m.group("vel"))
            continue
        m = _COMENTARIO.match(linha)
        if m and atual is not None:
            chave, valor = m.group("chave").strip().upper(), m.group("valor").strip()
            atual.comentarios.append(linha)
            if chave == "FROM CLIP NAME":
                if atual.de is not None or atual.transicao != "C":
                    atual.clip_de = valor
                else:
                    atual.clip = valor
            elif chave == "TO CLIP NAME" and atual.transicao != "C":
                atual.clip = valor            # num C (o AUDIO DISSOLVE do MC sai assim) o TO fica só no comentário
            elif chave in ("SOURCE FILE", "FROM FILE"):
                atual.arquivo = valor
            continue
        if linha.startswith("*") and atual is not None:
            atual.comentarios.append(linha)       # BLEND, AUDIO LEVEL…, EFFECTS NAME IS (sem dois-pontos certos)
            continue
        m = _AUD.match(linha)
        if m and atual is not None:
            # `AUD  3    4` (Premiere 26.0.2, 2026-11-25): os canais além de A/A2 — o evento vem com `NONE` (ou `AA`) e esta
            # linha diz quais (A3, A4). Sem ela, os canais 3 e 4 do som não existiriam para quem lê.
            extra = [f"A{n}" for n in m.groups() if n]
            base = [] if atual.canal in ("NONE", "") else [atual.canal]
            atual.canal = "/".join(base + extra)
            continue
        if linha.startswith("EFFECTS NAME IS") and atual is not None:
            atual.comentarios.append(linha)
            continue
        edl.nao_lidas.append(linha)
    return edl


def quadros(tc: str, base: int, drop_frame: bool = False) -> int:
    """HH:MM:SS:FF → quadros desde a meia-noite (base nominal: 24, 25, 30…). Com drop-frame (29,97/59,94) os
    números pulados descontados."""
    h, m, s, f = (int(x) for x in re.split(r"[:;.]", tc))
    total = ((h * 60 + m) * 60 + s) * base + f
    if drop_frame:
        pula = 2 * (base // 30)
        minutos = h * 60 + m
        total -= pula * (minutos - minutos // 10)
    return total
