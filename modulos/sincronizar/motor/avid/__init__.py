"""Adapter Avid (Media Composer) — `.avb`. Espelha `drt/` e `prproj/`: traduz uma
diária JÁ sincronizada para a entrada do writer de `.avb`.

Só o ADAPTER mora aqui. O writer (a autoria da CompositionMob) ainda é o do
RELINKER — ver o cabeçalho de `adapter.py`.
"""

from .adapter import daily_to_avb_segments  # noqa: F401
