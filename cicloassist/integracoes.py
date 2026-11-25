"""O instalador ÚNICO de integrações do Ciclo Assist (fase 4 do plano um app só, passo 3 — 2026-11-07).

⭐ Decisão do autor (2026-11-07): **nenhum painel visível dentro dos NLEs** — o editor só usa o Ciclo Assist pela janela
do app. No Premiere fica UMA extensão invisível, a ponte do Assist (`ponte_cep/`), que carrega o ExtendScript dos três
módulos e atende o Sincronizar e o Conformar pelo núcleo (`servico/nucleo.py`). Todo o resto que os três apps
instalavam sai: as pontes próprias do ex-Órbita e do De Lá Pra Cá, os painéis do MC (`.avpi`) e do Resolve, os
scripts do Resolve e as extensões de experimento.

⛔ Desinstalar MOVE para uma pasta de cópia (nada se apaga sem o autor), e um ATALHO (symlink) só perde o atalho —
o destino dele é de outro projeto e não é nosso para mover. ⚠️ O CEP e o MC só leem as pastas no ARRANQUE: com o
programa aberto, feche e abra.
⚠️ Windows: os caminhos do MC e do Resolve abaixo seguem a matriz de plataforma (seção G); não medidos nesta passada.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PONTE = (RAIZ / "ponte_cep", "com.ciclomedia.cicloassist.ponte")
#: CSXS 9 a 12 cobrem o Premiere 2019 ao 2026; ligar a mais é inócuo (banco).
VERSOES_CSXS = range(9, 13)

#: As extensões do Premiere que saem (nome da pasta instalada).
EXTENSOES_ANTIGAS = ("com.orbita.ponte", "com.orbita.sync", "com.orbita.sonda", "com.ciclomedia.delapraca.ppro",
                     "com.ciclomedia.cicloassist.ppro", "com.ciclomedia.lab.ponte", "com.producao-g.diarias")
#: Os painéis do Media Composer que saem (prefixos do `.avpi`).
PREFIXOS_AVPI = ("com.ciclomedia.", "com.orbita.")
#: O painel do Resolve (Workflow Integration) e os scripts que saem.
RESOLVE_PAINEIS = ("com.ciclomedia.delapraca",)
RESOLVE_SCRIPTS = ("orbita_sync.lua", "orbita_sync.py", "delapraca.lua", "delapraca.py")


def _windows() -> bool:
    return platform.system() == "Windows"


def pasta_cep() -> Path:
    if _windows():
        return Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Adobe" / "CEP" / "extensions"
    return Path.home() / "Library" / "Application Support" / "Adobe" / "CEP" / "extensions"


def pasta_avpi() -> Path:
    if _windows():
        return Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / "Avid" / "PanelSDKPlugins"
    return Path("/Library/Application Support/Avid/PanelSDKPlugins")


def pasta_resolve_paineis() -> Path:
    if _windows():
        return (Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / "Blackmagic Design" / "DaVinci Resolve"
                / "Support" / "Workflow Integration Plugins")
    return Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins")


def pastas_resolve_scripts() -> list[Path]:
    if _windows():
        base = (Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming") / "Blackmagic Design"
                / "DaVinci Resolve" / "Support" / "Fusion" / "Scripts")
    else:
        base = Path.home() / "Library" / "Application Support" / "Blackmagic Design" / "DaVinci Resolve" / "Fusion" / "Scripts"
    return [base / d for d in ("Utility", "Views", "Edit", "Color", "Deliver", "Comp", "Tool")]


@dataclass
class Antiga:
    nle: str
    caminho: Path


def antigas() -> list[Antiga]:
    """O que está instalado e sai (só o que EXISTE — atalho quebrado inclusive)."""
    achadas: list[Antiga] = []

    def ver(nle: str, p: Path) -> None:
        if p.exists() or p.is_symlink():
            achadas.append(Antiga(nle, p))

    for nome in EXTENSOES_ANTIGAS:
        ver("premiere", pasta_cep() / nome)
    if pasta_avpi().is_dir():
        for p in sorted(pasta_avpi().iterdir()):
            if p.name.startswith(PREFIXOS_AVPI) and p.name.endswith(".avpi"):
                ver("media_composer", p)
    for nome in RESOLVE_PAINEIS:
        ver("resolve", pasta_resolve_paineis() / nome)
    for pasta in pastas_resolve_scripts():
        for nome in RESOLVE_SCRIPTS:
            ver("resolve", pasta / nome)
    return achadas


def desinstalar_antigas(copia: Path) -> list[dict]:
    """Tira cada integração antiga: MOVE para `copia/<nle>/<nome>` (atalho: só remove o atalho). Devolve o feito.

    ⛔ Uma que não sai (sem permissão — `/Library/…/PanelSDKPlugins` no Mac, `%PROGRAMDATA%` no Windows, ou o NLE
    aberto segurando o arquivo) vai na lista com `falha` e as outras seguem: antes a primeira exceção derrubava o
    instalador inteiro, e a ponte do Premiere nunca era instalada (revisão de 2026-11-07)."""
    feitos = []
    for a in antigas():
        try:
            feitos.append(_tirar(a, copia))
        except OSError as e:
            feitos.append({"nle": a.nle, "tirado": str(a.caminho), "falha": str(e)})
    return feitos


def _tirar(a: Antiga, copia: Path) -> dict:
    if a.caminho.is_symlink():
        alvo = os.readlink(a.caminho)
        a.caminho.unlink()
        return {"nle": a.nle, "tirado": str(a.caminho), "atalho_para": alvo}
    destino = copia / a.nle / (a.caminho.parent.name + "__" + a.caminho.name
                               if a.caminho.parent.name in ("Utility", "Views", "Edit", "Color", "Deliver",
                                                            "Comp", "Tool") else a.caminho.name)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.exists():
        destino = destino.with_name(destino.name + ".2")
    shutil.move(str(a.caminho), str(destino))
    return {"nle": a.nle, "tirado": str(a.caminho), "copia": str(destino)}


def ligar_modo_depuracao() -> list[str]:
    """`PlayerDebugMode = 1` em cada CSXS — sem ele o CEP recusa a extensão não assinada EM SILÊNCIO (banco)."""
    falhas = []
    for n in VERSOES_CSXS:
        comando = (["reg", "add", rf"HKCU\Software\Adobe\CSXS.{n}", "/v", "PlayerDebugMode", "/t", "REG_SZ",
                    "/d", "1", "/f"] if _windows() else ["defaults", "write", f"com.adobe.CSXS.{n}", "PlayerDebugMode", "1"])
        r = subprocess.run(comando, capture_output=True, text=True)
        if r.returncode != 0:
            falhas.append(f"CSXS.{n}: {r.stderr.strip()}")
    return falhas


def instalar_ponte(pasta: Path | None = None) -> Path:
    """Copia a ponte do Assist (cópia, nunca atalho; sem `.debug`, que abriria o DevTools sem senha)."""
    origem, id_ = PONTE
    destino = (pasta or pasta_cep()) / id_
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.is_symlink() or destino.is_file():
        destino.unlink()
    elif destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(origem, destino, ignore=shutil.ignore_patterns(".debug", "._*", ".DS_Store"))
    return destino


# ── o estado, para a seção Integrações da janela de configurações (2026-11-07) ────────────────────────────────────

def _arquivos_da_ponte(raiz: Path) -> dict[str, bytes]:
    """`{caminho relativo: conteúdo}` do que a instalação copia (o mesmo filtro do `instalar_ponte`)."""
    ignorar = shutil.ignore_patterns(".debug", "._*", ".DS_Store")
    achados: dict[str, bytes] = {}
    for pasta, dirs, nomes in os.walk(raiz):
        dirs[:] = [d for d in dirs if d not in ignorar(pasta, dirs)]
        for nome in set(nomes) - ignorar(pasta, nomes):
            p = Path(pasta) / nome
            achados[p.relative_to(raiz).as_posix()] = p.read_bytes()
    return achados


def situacao_da_ponte(pasta: Path | None = None) -> str:
    """`instalada` (igual à deste app), `desatualizada` (existe e difere) ou `ausente`.

    ⭐ Compara o CONTEÚDO, não o número da versão: o `ExtensionBundleVersion` não muda a cada mudança do loader."""
    origem, id_ = PONTE
    destino = (pasta or pasta_cep()) / id_
    if destino.is_symlink() or not destino.is_dir():
        return "desatualizada" if destino.is_symlink() or destino.exists() else "ausente"
    try:
        return "instalada" if _arquivos_da_ponte(destino) == _arquivos_da_ponte(origem) else "desatualizada"
    except OSError:
        return "desatualizada"


def modo_depuracao_ligado() -> bool:
    """`PlayerDebugMode = 1` em TODOS os CSXS que ligamos (falta um, e a versão do Premiere dele recusa a ponte)."""
    for n in VERSOES_CSXS:
        comando = (["reg", "query", rf"HKCU\Software\Adobe\CSXS.{n}", "/v", "PlayerDebugMode"] if _windows()
                   else ["defaults", "read", f"com.adobe.CSXS.{n}", "PlayerDebugMode"])
        try:
            r = subprocess.run(comando, capture_output=True, text=True, timeout=5)
        except (OSError, subprocess.TimeoutExpired):
            return False
        saida = r.stdout.strip()
        if r.returncode != 0 or not (saida == "1" or saida.endswith("REG_SZ    1")):
            return False
    return True


def estado() -> dict:
    """O que a seção Integrações mostra: a ponte do Premiere e as integrações antigas que ainda estão instaladas."""
    _, id_ = PONTE
    return {
        "ponte": {"situacao": situacao_da_ponte(), "caminho": str(pasta_cep() / id_),
                  "modo_depuracao": modo_depuracao_ligado()},
        "antigas": [{"nle": a.nle, "caminho": str(a.caminho), "atalho": a.caminho.is_symlink()} for a in antigas()],
    }
