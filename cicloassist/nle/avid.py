"""O lado Avid das perguntas de `nle`: o que as ferramentas faziam cada uma na sua cópia."""

from __future__ import annotations

from pathlib import Path

from ..avid.mcapi import McApiErro, MediaComposer
from ..avid.take import Take, TakeErro, com_extensao_de_bin, resolver


def caminho_absoluto(bin: str) -> str:
    """Caminho de bin → absoluto. Só abre conexão com o MC se for relativo: saber onde o
    projeto mora custa uma chamada (~500 ms)."""
    p = Path(com_extensao_de_bin(bin))
    if p.is_absolute():
        return str(p)
    with MediaComposer() as mc:
        return str(Path(mc.projeto().get("caminho") or "") / bin)


def resolver_take(bin: str, item: str) -> Take:
    try:
        return resolver(caminho_absoluto(bin), item)
    except McApiErro as e:
        raise TakeErro(f"o Media Composer não respondeu ({e}); ele está aberto?") from e
