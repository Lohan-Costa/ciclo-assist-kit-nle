"""O SEGREDO dos plugins (`plugin-token`): o que o painel CEP, o script do Resolve e o Ciclo Assist apresentam.

(Não se chama `token.py`: sombrearia o módulo `token` da biblioteca padrão, que o `tokenize` importa.)

Porte do `plugin_token.rs` do Órbita (`d57904e`). Sorteado a CADA arranque e publicado num arquivo do usuário: o plugin
lê (tem disco), a aba do navegador não — é a fronteira navegador ↔ disco que ele fecha. Um processo local malicioso
rodando como o usuário lê o arquivo; contra ele não há defesa neste nível.

⭐ Fase 3 do plano um app só (2026-11-07): a pasta é a do MÓDULO dentro do Ciclo Assist (`…/CicloAssist/sincronizar`,
a conta do motor, `appsettings.app_data_dir` — uma só) e o cabeçalho é `X-Sincronizar-Token`. Era `…/Orbita` e
`X-Sincronizar-Token`. `migrar_da_pasta_antiga` traz o que importa de lá na primeira subida.
"""
from __future__ import annotations

import hmac
import os
import secrets
import sys
from pathlib import Path

TOKEN_FILE = "plugin-token"
HEADER = "X-Ciclo-Token"
#: o nome da pasta antiga (só para a migração)
PASTA_ANTIGA = "Orbita"

_MOTOR = Path(__file__).resolve().parent.parent / "motor"

_token: str | None = None


def pasta_de_dados() -> Path:
    """A pasta de dados do módulo — a MESMA conta do motor (`appsettings.app_data_dir`): `SINCRONIZAR_DADOS` manda
    (os testes isolam por ele), depois `CICLOASSIST_DADOS`/sincronizar, senão `…/CicloAssist/sincronizar`."""
    if str(_MOTOR) not in sys.path:
        sys.path.insert(0, str(_MOTOR))
    import appsettings  # noqa: E402 — do motor
    return appsettings.app_data_dir()


def pasta_antiga() -> Path:
    """Onde o Órbita guardava (`%APPDATA%\\Orbita`, `~/Library/Application Support/Orbita`)."""
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or os.environ.get("USERPROFILE") or Path.home())
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        x = os.environ.get("XDG_CONFIG_HOME")
        base = Path(x) if x else Path.home() / ".config"
    return base / PASTA_ANTIGA


#: O que vale levar: as escolhas do editor e o histórico do DESFAZER do Renomear. O token é sorteado a cada arranque,
#: o log começa de novo e o cache (outra pasta) se refaz sozinho.
MIGRAVEIS = ("settings.json", "renomeacoes")


def migrar_da_pasta_antiga(antiga: Path | None = None, nova: Path | None = None) -> list[str]:
    """Copia (não move: a pasta antiga fica, como tudo que se aposenta aqui) o que falta na nova. Devolve o que copiou.
    Idempotente: o que já existe na nova nunca é sobrescrito."""
    import shutil
    antiga = antiga or pasta_antiga()
    nova = nova or pasta_de_dados()
    copiados = []
    if not antiga.is_dir():
        return copiados
    nova.mkdir(parents=True, exist_ok=True)
    for nome in MIGRAVEIS:
        de, para = antiga / nome, nova / nome
        if para.exists() or not de.exists():
            continue
        if de.is_dir():
            shutil.copytree(de, para, ignore=shutil.ignore_patterns("._*", ".DS_Store"))
        else:
            shutil.copy2(de, para)
        copiados.append(nome)
    return copiados


def caminho() -> Path:
    return pasta_do_ciclo() / TOKEN_FILE


def pasta_do_ciclo() -> Path:
    """A pasta de dados do Ciclo Assist (onde o núcleo publica o token ÚNICO): `CICLOASSIST_DADOS`, senão a mãe da do
    módulo (`…/CicloAssist/sincronizar` → `…/CicloAssist`)."""
    explicita = os.environ.get("CICLOASSIST_DADOS")
    return Path(explicita) if explicita else pasta_de_dados().parent


_lido: tuple[float, str] = (-1.0, "")


def token() -> str:
    """⭐ Passo 2 da fase 4 (2026-11-07): o token é o ÚNICO do Ciclo Assist (`<dados>/plugin-token`, sorteado pelo
    núcleo a cada arranque — `cicloassist/servico/nucleo.py`). Relido quando o arquivo muda (o Assist reiniciou).
    Sem o arquivo: vazio, e ninguém entra (`confere` recusa)."""
    global _lido
    p = caminho()
    try:
        m = p.stat().st_mtime
    except OSError:
        return ""
    if m != _lido[0]:
        try:
            _lido = (m, p.read_text(encoding="utf-8").strip())
        except OSError:
            return ""
    return _lido[1]


def publicar() -> Path:
    """Não publica mais nada (o núcleo publica): devolve onde o token ÚNICO mora, para o log."""
    return caminho()


def confere(apresentado: str) -> bool:
    """Comparação em tempo constante (`hmac.compare_digest`, o laço XOR do Rust)."""
    esperado = token()
    if not esperado or not apresentado:
        return False
    return hmac.compare_digest(apresentado.encode("utf-8", "replace"), esperado.encode("ascii"))
