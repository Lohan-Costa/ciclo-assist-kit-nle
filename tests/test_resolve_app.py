

def test_o_script_do_resolve_escreve_utf8():
    """Projeto com acento ("UIA ÇÃO 01") quebrava a leitura da resposta: o filho escrevia em cp1252 (2026-11-05)."""
    from cicloassist import resolve
    assert 'sys.stdout.reconfigure(encoding="utf-8")' in resolve._CODIGO
