"""
Sincronizar — configurações persistentes do app.

ONDE: no diretório de DADOS do app (junto dos logs), nunca no diretório de cache —
o caminho do cache é justamente uma das coisas configuráveis aqui, e um arquivo
que diz onde fica o cache não pode morar dentro dele.

  macOS   ~/Library/Application Support/CicloAssist/sincronizar/settings.json
  Windows %LOCALAPPDATA%\\CicloAssist\\sincronizar\\settings.json
  Linux   ~/.config/Orbita/settings.json

Ler NUNCA levanta: um settings.json corrompido (disco cheio no meio da escrita,
edição à mão) volta aos padrões em vez de derrubar o sidecar no boot. Configuração
é conveniência; perder o app inteiro por causa dela seria desproporcional.

⚠️ O MÓDULO se chama `appsettings`, não `settings`, de propósito: o bundle do
PyInstaller (`--onefile`) põe TODOS os módulos num namespace plano, e `settings` é
genérico o bastante para um dia colidir com o de alguma dependência — silenciosamente,
e só no binário empacotado, que é o pior lugar para descobrir.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

#: ⭐ Fase 3 do plano um app só (2026-11-07): o módulo Sincronizar do Ciclo Assist guarda os dados DENTRO da pasta do
#: Ciclo Assist (`…/CicloAssist/sincronizar`) — era `…/Orbita` (APPDATA no Windows). A migração do que havia lá é do
#: servidor (`servidor/segredo.py::migrar_da_pasta_antiga`).
MODULO = "sincronizar"

#: Teto padrão do cache. 5 GB comporta várias diárias de waveform sem que o
#: usuário precise pensar no assunto — e é pequeno o bastante para não assustar
#: quem descobre a pasta um ano depois.
DEFAULT_CACHE_MAX_MB = 5120

#: Resolução de reprodução do monitor (proxy de vídeo). Tetos em media.proxy:
#: "full" = FHD-capped, "half"/"quarter" relativos. `half` é imperceptível no
#: tamanho do monitor e mantém o transcode barato.
PLAYBACK_RESOLUTIONS = ("full", "half", "quarter")
DEFAULT_PLAYBACK_RESOLUTION = "half"

_DEFAULTS: dict = {
    # `None` = usar o diretório de cache padrão da plataforma (ver media.cachedir).
    "cache_dir": None,
    "cache_max_mb": DEFAULT_CACHE_MAX_MB,
    "playback_resolution": DEFAULT_PLAYBACK_RESOLUTION,
    # Pré-render automático em segundo plano: DESLIGADO por padrão. Ele deixa o
    # playback liso no material pesado, mas é trabalho que começa sozinho — quem
    # decide pagar esse custo é o usuário, não o app.
    "auto_render": False,
    # ⭐⭐ Fechar a janela MANTÉM o Órbita na bandeja: DESLIGADO por padrão.
    #
    # O X que esconde em vez de encerrar existe por um motivo real (ADR 0010: o app
    # SERVE o painel do NLE, e derrubá-lo no meio de uma edição é o pior momento
    # possível) — mas é um comportamento que SURPREENDE. Quem fecha a janela espera
    # ter fechado o programa, e descobrir um processo vivo que não se pediu é pior
    # que perder a ponte com o painel, que pelo menos se anuncia ("desconectado",
    # com o atalho para reabrir). Decisão do autor, 2026-09-21: a conveniência de
    # quem passa o dia no NLE vira ESCOLHA de quem passa o dia no NLE.
    "close_to_tray": False,
    # ⭐ O IDIOMA ESCOLHIDO NO APP, para que os plugins o sigam.
    #
    # A janela do app guarda a escolha no `localStorage` dela, que é privado
    # daquela origem — o painel do Media Composer, servido por outra, não o
    # enxerga. Sem isto ele perguntava ao `navigator.language`, e ali quem
    # responde é o **QtWebEngine**, que reporta o locale DELE (tipicamente
    # `en-US`): o painel abria em inglês ao lado de uma janela em português,
    # dentro de um Windows em português. Persistir aqui é o que dá aos dois uma
    # fonte só.
    "locale": "pt-BR",
}

#: Os idiomas que existem. Qualquer outra coisa no `settings.json` volta ao base.
LOCALES = ("pt-BR", "en")


def app_data_dir() -> Path:
    """Dados do módulo (settings, logs, desfazer) — persistentes, não descartáveis.

    `SINCRONIZAR_DADOS` manda (os testes do servidor isolam por ele); depois `CICLOASSIST_DADOS` (o mesmo isolamento
    do Ciclo Assist, `cicloassist/servico/config.py::pasta`) + `sincronizar`; senão a pasta do Ciclo Assist da
    plataforma — a MESMA conta de lá (LOCALAPPDATA no Windows, Application Support no Mac)."""
    explicita = os.environ.get("SINCRONIZAR_DADOS")
    if explicita:
        return Path(explicita)
    ciclo = os.environ.get("CICLOASSIST_DADOS")
    if ciclo:
        return Path(ciclo) / MODULO
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local") / "CicloAssist"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support" / "CicloAssist"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cicloassist"
    return base / MODULO


def logs_dir() -> Path:
    return app_data_dir() / "logs"


def rename_journal_dir() -> Path:
    """Onde ficam os lotes de renomeação, para o desfazer da aba Renomear.

    ⚠️ Diretório de **DADOS**, nunca o de cache — e a distinção é a que o cabeçalho
    deste módulo já faz: o cache é purgável por política (`cachedir.enforce_limit`
    apaga o mais antigo quando o teto estoura), e um histórico de desfazer que some
    quando o cache enche não é histórico.
    """
    return app_data_dir() / "renomeacoes"


def _settings_file() -> Path:
    return app_data_dir() / "settings.json"


def load() -> dict:
    """As configurações, com os padrões preenchidos. Nunca levanta."""
    data = dict(_DEFAULTS)
    try:
        raw = json.loads(_settings_file().read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            # Só chaves conhecidas: um settings.json de uma versão FUTURA não pode
            # injetar campo nenhum aqui dentro.
            for k in _DEFAULTS:
                if k in raw:
                    data[k] = raw[k]
    except (OSError, ValueError):
        pass
    return _sanitize(data)


def _sanitize(data: dict) -> dict:
    """Valores fora do razoável voltam ao padrão — inclusive os que o usuário
    digitou. Um teto de 0 MB apagaria o cache a cada escrita."""
    out = dict(data)

    cache_dir = out.get("cache_dir")
    out["cache_dir"] = str(cache_dir) if cache_dir else None

    try:
        mb = int(out.get("cache_max_mb") or 0)
    except (TypeError, ValueError):
        mb = 0
    out["cache_max_mb"] = mb if mb >= 100 else DEFAULT_CACHE_MAX_MB

    # ⚠️ Booleanos saem BOOLEANOS: um `"false"` escrito à mão no JSON é verdadeiro
    # em Python, e o usuário veria ligado o que acabou de desligar.
    for chave in ("auto_render", "close_to_tray"):
        valor = out.get(chave)
        out[chave] = (valor.strip().lower() not in ("", "0", "false", "no")
                      if isinstance(valor, str) else bool(valor))

    res = out.get("playback_resolution")
    out["playback_resolution"] = (
        res if res in PLAYBACK_RESOLUTIONS else DEFAULT_PLAYBACK_RESOLUTION
    )

    # ⚠️ `pt-BR` é o BASE, e é para onde um valor estranho volta — nunca para o
    # que o sistema diz. Um `settings.json` corrompido não pode trocar o idioma
    # de quem usa por um que ninguém escolheu.
    out["locale"] = out.get("locale") if out.get("locale") in LOCALES else "pt-BR"
    return out


def save(patch: dict) -> dict:
    """Aplica só as chaves conhecidas e devolve as configurações resultantes."""
    data = load()
    for k in _DEFAULTS:
        if k in patch:
            data[k] = patch[k]
    data = _sanitize(data)
    try:
        f = _settings_file()
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_suffix(".part")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(f)
    except OSError:
        # Não conseguiu gravar (disco cheio, sem permissão): o app segue com o
        # valor em memória. Mentir dizendo que salvou seria pior.
        pass
    return data
