"""As configurações do De Lá Pra Cá nesta máquina: onde fica o cache e até quanto ele cresce.

Organograma de cache e logs aprovado pelo autor em 2026-10-05 (base: `DRAMASYNC/src-python/
appsettings.py`, do Órbita).

ONDE: `configuracoes.json` na pasta de DADOS (`plataforma.pasta_dados()`), nunca no cache — o
lugar do cache é justamente uma das coisas guardadas aqui, e um arquivo que diz onde fica o cache
não pode morar dentro dele. ⚠️ A casca do Resolve (`plugins/resolve/casca/main.js`, `pastaCache`)
lê ESTE arquivo para saber onde está `recebidos/`: as duas regras têm de bater.

Ler NUNCA levanta: um arquivo corrompido volta aos padrões. Configuração é conveniência.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

import plataforma

ARQUIVO = "configuracoes.json"

#: Teto padrão do cache (decisão 1 do organograma): uma conferência do filme inteiro ocupa
#: ~2,5 GB; 20 GB guardam umas oito antes de a mais antiga sair.
TETO_PADRAO_GB = 20
TETO_MINIMO_GB = 1
TETO_MAXIMO_GB = 2000

_PADROES: dict = {
    # `None` = a pasta padrão do sistema (`plataforma.pasta_cache_padrao`).
    "cache_dir": None,
    "cache_max_gb": TETO_PADRAO_GB,
    # Decisão 5: o cache do lugar antigo não se migra; o painel avisa e oferece apagar. "Manter"
    # para de avisar.
    "cache_antigo_dispensado": False,
    # Aviso de versão nova (organograma de 2026-10-05, decisão 3): a caixa nas Configurações desliga.
    "avisar_versao_nova": True,
}


def _arquivo() -> Path:
    return plataforma.pasta_dados() / ARQUIVO


def pasta_aceitavel(caminho) -> str | None:
    """O caminho escolhido para o cache, se for aceitável; senão `None` (= o padrão).

    ⛔ Nada de caminho de REDE (`\\\\servidor\\…`, `//servidor/…`): o DRT de `recebidos/` vai para o
    Resolve, e um DRT num compartilhamento faz o Resolve abrir sessão SMB com aquele host (ataque V9
    da revisão de 2026-09-24, `main.js › drtConfiavel`). Só caminho ABSOLUTO local."""
    if not isinstance(caminho, str):
        return None
    c = caminho.strip()
    if not c or "\x00" in c or c.startswith(("\\\\", "//")):
        return None
    if plataforma.E_WINDOWS:
        if not re.match(r"^[A-Za-z]:[\\/]", c):
            return None
    elif not c.startswith("/"):
        return None
    return os.path.normpath(c)


def _sanear(dado: dict) -> dict:
    fora = dict(dado)
    fora["cache_dir"] = pasta_aceitavel(fora.get("cache_dir"))
    try:
        gb = int(fora.get("cache_max_gb"))
    except (TypeError, ValueError):
        gb = TETO_PADRAO_GB
    fora["cache_max_gb"] = gb if TETO_MINIMO_GB <= gb <= TETO_MAXIMO_GB else TETO_PADRAO_GB
    fora["cache_antigo_dispensado"] = fora.get("cache_antigo_dispensado") is True
    fora["avisar_versao_nova"] = fora.get("avisar_versao_nova") is not False
    return fora


def ler() -> dict:
    """As configurações, com os padrões preenchidos. Nunca levanta."""
    dado = dict(_PADROES)
    try:
        bruto = json.loads(_arquivo().read_text(encoding="utf-8"))
        if isinstance(bruto, dict):
            # Só as chaves conhecidas: um arquivo de uma versão futura não injeta nada.
            dado.update({k: bruto[k] for k in _PADROES if k in bruto})
    except (OSError, ValueError):
        pass
    return _sanear(dado)


def gravar(mudancas: dict) -> dict:
    """Aplica só as chaves conhecidas e devolve o resultado. Levanta `OSError` se não gravou —
    dizer "guardado" sem ter guardado seria pior que o erro."""
    dado = ler()
    dado.update({k: mudancas[k] for k in _PADROES if k in mudancas})
    dado = _sanear(dado)
    alvo = _arquivo()
    alvo.parent.mkdir(parents=True, exist_ok=True)
    tmp = alvo.with_name(f"{ARQUIVO}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(dado, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, alvo)
    return dado
