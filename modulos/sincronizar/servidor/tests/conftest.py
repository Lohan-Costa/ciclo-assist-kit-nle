"""O servidor do Sincronizar nos testes: a pasta dele no caminho, e a pasta de dados num tmp.

⛔ `SINCRONIZAR_DADOS` aponta para o tmp ANTES de qualquer import: sem isso o token dos testes seria publicado na
pasta real do usuário (`…/Orbita/plugin-token`), por cima do token do servidor no ar — e os painéis abertos
passariam a ser recusados. É a lição do `LOCALAPPDATA` do Assist no Mac (2026-09-14).
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["SINCRONIZAR_DADOS"] = tempfile.mkdtemp(prefix="sincronizar-testes-")
# ⭐ Fase 4: o token é o ÚNICO do Ciclo Assist (`<dados do Ciclo Assist>/plugin-token`) — aqui, um de teste num tmp
os.environ["CICLOASSIST_DADOS"] = tempfile.mkdtemp(prefix="cicloassist-testes-")
(Path(os.environ["CICLOASSIST_DADOS"]) / "plugin-token").write_text("t" * 64, encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _estado_limpo():
    import ponte
    import trabalhos
    ponte._zerar()
    trabalhos._zerar()
    yield
    ponte._zerar()
    trabalhos._zerar()
