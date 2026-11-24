"""⛔⛔ A borda do piloto DERRUBAVA o serviço na 2ª subida (2026-11-04) — e a conversa do editor ia junto.

A classe de janela é registrada uma vez por processo; na 2ª subida o callback da 1ª borda (já solto)
continuava na classe, e a primeira mensagem caía em memória solta (0xc0000005 no python.exe). O teste sobe a
borda, deixa a thread sair, força a coleta e sobe de novo — num SUBPROCESSO, porque a falha mata o processo.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="a borda só existe no Windows")


def test_a_janela_da_borda_chama_sempre_um_callback_vivo():
    """MEDIDO (04/11) contra a versão antiga, com callbacks nascendo entre as subidas como no serviço: a
    janela da 2ª borda chamava o endereço do callback da 1ª (já solto), e não o dela. Reproduzir a QUEDA
    depende de sorte (o que ocupa a memória); o ponteiro errado, não."""
    codigo = textwrap.dedent("""
        import ctypes, gc, time
        from ctypes import wintypes
        from cicloassist.piloto import borda
        borda.APAGADA_S = 0.3
        u = ctypes.WinDLL("user32")
        u.FindWindowW.restype = wintypes.HWND
        u.GetClassLongPtrW.restype = ctypes.c_void_p
        u.GetClassLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
        vivo = ctypes.cast(borda._PROC_DO_PROCESSO, ctypes.c_void_p).value
        ocupa = []
        for vez in range(3):
            with borda.acesa(f"teste {vez}"):
                time.sleep(0.5)
                h = u.FindWindowW(borda._CLASSE_NOME, None)
                assert h, "a borda não abriu janela"
                assert u.GetClassLongPtrW(h, -24) == vivo, f"subida {vez}: a janela chama um callback solto"
            t = borda._thread
            t.join(5)
            assert not t.is_alive(), "a thread da borda não saiu"
            gc.collect()
            # como no serviço: callbacks novos nascem entre uma subida e outra e ocupam a memória solta
            ocupa += [ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(lambda h, l: True)
                      for _ in range(5)]
        print("ok")
    """)
    r = subprocess.run([sys.executable, "-c", codigo], capture_output=True, text=True, timeout=60)
    assert r.returncode == 0 and "ok" in r.stdout, (r.returncode, r.stdout, r.stderr[-800:])
