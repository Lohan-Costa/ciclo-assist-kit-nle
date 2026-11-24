"""De quem é cada canal do som direto: o nome que o técnico de som deu, e o PAPEL que ele diz.

⭐⭐ Plano `docs/plano/2026-11-06-transcricao-por-canal.md` (F1). Porte de `_ASSIST ANTERIOR/assist_anterior/som/canais.py`
e `ixml.py`, que pagaram as lições abaixo; o banco tem a página inteira
(`transversal/metadado-de-canal-do-som-direto.md`).

## O papel: o que é FECHADO é o técnico; o resto é gente

A lista de lapelas é aberta (`MIC2`, `LAP1`, `Tr2MIC1`, e em PRODUCAO-F `PESSOA-H` e `DITO`, os nomes dos personagens).
O que acaba é o ofício: mixdown, boom, ambiente, playback. ⇒ **`PESSOA` é o default**, e o vocabulário lista só o que
é fechado.

⛔⛔ Errar tem lado: o MIXDOWN tido por pessoa põe a mistura de todos na disputa e resolve a cena inteira para um
falante só. Por isso trilha **sem nome** é `SEM_NOME`, nunca `PESSOA` (na D02 as duas sem nome são o mixdown; no take
do laboratório `C4 P4-T003` também).

## O nome: três fontes, e nenhuma é a POSIÇÃO

1. As colunas `TRK1..n` do master na bin (`_USER`) — o Avid as preenche do iXML ao importar.
2. O `TRACK_LIST` do iXML do WAV — ⛔ o canal é o `INTERLEAVE_INDEX`, nunca o `CHANNEL_INDEX` (o boom da D02 é
   `CHANNEL_INDEX 10` e mora no QUINTO canal; no laboratório, `CHANNEL_INDEX 4/5/10` em 3/4/5).
3. Nada. ⛔ A posição não diz o papel (o canal 3 é `BOOM 2` num take e `BOOM 1` noutro, na mesma diária) — sem nome,
   a resposta é "não avaliado", nunca um chute.
"""

from __future__ import annotations

import logging
import re
import struct
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

log = logging.getLogger("cicloassist.midia.canais")

#: O mixdown do gravador. ⛔ Contém todas as vozes — nunca disputa quem fala.
MISTURA = "mistura"
#: O microfone direcional. Serve para transcrever, não para dizer quem falou.
BOOM = "boom"
#: Ambiente, sala, playback. Não é ninguém.
AMBIENTE = "ambiente"
#: Uma pessoa — rótulo genérico (`MIC2`) ou o nome dela (`PESSOA-H`).
PESSOA = "pessoa"
#: A trilha existe e não foi nomeada. ⚠️ Não é pessoa.
SEM_NOME = "sem-nome"

_VOCABULARIO: dict[str, set[str]] = {
    MISTURA: {"TRL", "TRR", "MIXL", "MIXR", "MIX", "LR"},
    BOOM: {"BOOM", "SHOTGUN", "GUN"},
    AMBIENTE: {"MESA", "AMB", "AMBIENTE", "ROOM", "SALA", "MUSICA", "PLAYBACK", "PB",
               # ⚠️ o par mid-side de PRODUCAO-F: dois canais de UM microfone, nunca a lapela de alguém
               "STEREOMSL", "STEREOMSR"},
}

#: ⚠️ O prefixo de trilha do gravador colado no nome (`Tr2MIC1`). Exige DÍGITO depois do `Tr`: sem isso `TrL`
#: (mistura) viraria `L`.
_PREFIXO_DE_TRILHA = re.compile(r"^TR[0-9]+")
_SUFIXO_NUMERICO = re.compile(r"[0-9]+$")


def normalizar(nome: str) -> str:
    """Maiúsculas, sem separador, sem o prefixo `Tr<n>`. `"Tr2"` → `""` (número de trilha não é nome)."""
    bruto = re.sub(r"[^A-Za-z0-9]", "", (nome or "").upper())
    return _PREFIXO_DE_TRILHA.sub("", bruto) if bruto else ""


def papel(nome: str) -> str:
    """O papel de uma trilha pelo nome INTEIRO (com sufixo numérico opcional), nunca por substring: um personagem
    chamado `BOOMER` não vira o boom."""
    n = normalizar(nome)
    if not n:
        return SEM_NOME
    raiz = _SUFIXO_NUMERICO.sub("", n)
    for tecnico, rotulos in _VOCABULARIO.items():
        if n in rotulos or raiz in rotulos:
            return tecnico
    return PESSOA


@dataclass(frozen=True)
class Trilha:
    """Uma trilha do som direto. `canal` = posição no MASTER, base 1 (o `TRKn`, o `_A0n` do OP-Atom, o
    `INTERLEAVE_INDEX` do WAV)."""

    canal: int
    nome: str
    papel: str

    @property
    def e_pessoa(self) -> bool:
        return self.papel == PESSOA

    def como_dicionario(self) -> dict[str, Any]:
        return asdict(self)


def _trilhas(numeradas: dict[int, str]) -> list[Trilha]:
    return [Trilha(canal=k, nome=numeradas[k], papel=papel(numeradas[k])) for k in sorted(numeradas)]


# ── 1. as colunas da bin ─────────────────────────────────────────────────────

_COLUNA_TRK = re.compile(r"^TRK([0-9]+)$", re.I)


def de_colunas(colunas: dict | None, canais: int = 0) -> list[Trilha]:
    """As colunas `TRK1..TRKn` de um master → trilhas.

    ⚠️⚠️ Ordem NUMÉRICA (`TRK10` depois de `TRK9`). ⚠️ O Avid só grava a coluna que TEM nome: no laboratório o
    master tem `TRK3..5` e não tem `TRK1/2` (o mixdown sem nome). Com `canais` (quantos o master tem), as ausentes
    entram como `SEM_NOME` — sumir com elas não muda nada aqui, mas a lista passa a dizer o que existe.
    """
    numeradas: dict[int, str] = {}
    for chave, valor in (colunas or {}).items():
        m = _COLUNA_TRK.match(str(chave).strip())
        if m and int(m.group(1)) >= 1:
            numeradas[int(m.group(1))] = str(valor or "").strip()
    if not numeradas:
        return []
    for k in range(1, max(canais, max(numeradas)) + 1):
        numeradas.setdefault(k, "")
    return _trilhas(numeradas)


# ── 2. o iXML do WAV ─────────────────────────────────────────────────────────

_TETO_DE_CHUNK = 1 << 20
_MAX_CHUNKS = 256
_TRACK_LIST = re.compile(r"<TRACK_LIST>(.*?)</TRACK_LIST>", re.S | re.I)
_TRACK = re.compile(r"<TRACK>(.*?)</TRACK>", re.S | re.I)
_NAME = re.compile(r"<NAME>(.*?)</NAME>", re.S | re.I)
_INTERLEAVE = re.compile(r"<INTERLEAVE_INDEX>\s*([0-9]+)\s*</INTERLEAVE_INDEX>", re.S | re.I)


def _ixml_bruto(caminho: Path | str) -> str | None:
    """O chunk `iXML`, percorrendo o RIFF por `seek` — ⚠️ o `data` de um take tem centenas de MB e o iXML costuma
    vir DEPOIS dele. Padding de chunk ímpar respeitado (sem ele o percurso desalinha e "não tem iXML" se confunde
    com o caso legítimo)."""
    try:
        with Path(caminho).open("rb") as f:
            cab = f.read(12)
            if len(cab) < 12 or cab[:4] not in (b"RIFF", b"RF64") or cab[8:12] != b"WAVE":
                return None
            for _ in range(_MAX_CHUNKS):
                h = f.read(8)
                if len(h) < 8:
                    return None
                cid, tam = h[:4], struct.unpack("<I", h[4:8])[0]
                if cid == b"iXML":
                    return f.read(min(tam, _TETO_DE_CHUNK)).decode("utf-8", "replace")
                f.seek(tam + (tam & 1), 1)
    except OSError as e:
        log.info("não deu para ler o iXML de %s: %s", caminho, e)
    return None


def de_ixml(caminho: Path | str) -> list[Trilha]:
    """O `TRACK_LIST` do iXML → trilhas, pelo `INTERLEAVE_INDEX`. Sem iXML (metade dos WAVs) = `[]`, não erro.

    ⚠️ `<TRACK>` sem `<NAME>` continua sendo uma trilha (o mixdown da D02 e do laboratório é assim)."""
    xml = _ixml_bruto(caminho)
    bloco = _TRACK_LIST.search(xml or "")
    if not bloco:
        return []
    numeradas: dict[int, str] = {}
    for i, t in enumerate(_TRACK.finditer(bloco.group(1)), start=1):
        idx = _INTERLEAVE.search(t.group(1))
        nome = _NAME.search(t.group(1))
        numeradas[int(idx.group(1)) if idx else i] = nome.group(1).strip() if nome else ""
    return _trilhas(numeradas)


# ── a ordem dos canais nos arquivos ──────────────────────────────────────────

_SUFIXO_A = re.compile(r"(?:^|[_ .])A(\d{1,2})(?=[._]|$)", re.I)


def posicao_do_arquivo(caminho: str | Path) -> int | None:
    """O canal de um OP-Atom de som pelo NOME (`…_A03.mxf`, `A03.E69C….mxf`). `None` = não sei."""
    nome = Path(caminho).stem
    achados = _SUFIXO_A.findall(nome)
    return int(achados[-1]) if achados else None


def resumo(trilhas: list[Trilha]) -> str:
    """`MIC2 (3) · MIC3 (4) · BOOM (5) · 2 sem nome` — para log e para o modelo."""
    nomeadas = [f"{t.nome} ({t.canal})" for t in trilhas if t.nome]
    sem = sum(1 for t in trilhas if not t.nome)
    return " · ".join(nomeadas + ([f"{sem} sem nome"] if sem else [])) or "nenhuma"
