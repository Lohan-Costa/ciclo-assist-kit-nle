"""Abrir e fechar o Premiere Pro, e um projeto nele — o Premiere como um dos programas do fluxo.

⭐⭐ Pedido do autor (2026-11-01): *"mapear logo os comandos básicos de abrir e fechar os
programas … assim já ganhamos a liberdade de conversar cross NLE"*. O mapa dos três programas
mora em `cicloassist/mcp/ferramentas/programas.py`; aqui, o do Premiere.

Tudo conhecimento do banco (`plugins/premiere-cep/api-extendscript.md`,
`painel-servido-e-identidade.md`, matriz de plataforma §G2):

- ⭐ Abrir com o `.prproj` na LINHA DE COMANDO abre o projeto direto; sem argumento, a tela
  inicial — e a PONTE invisível sobe nas duas (7–9 s no 26.5.2).
- ⭐ Criar é `app.newProject(caminho)` pela ponte, sem diálogo; abrir outro com o Premiere de
  pé é `app.openDocument(caminho, true, true, true)` (sem diálogo de conversão nem de mídia).
- ⛔⛔ **`app.quit()` pela ponte já NÃO fechou o Premiere** (23.2, 2026-10-10) e derrubou a
  ponte junto. ⇒ salva ANTES (chamada separada), pede a saída, e confere o PROCESSO. Se ele
  ficar, `WM_CLOSE` na janela principal (2–3 s na tela inicial do 26.5.2) e, por último,
  encerrar à força — SÓ com o projeto já salvo.
- ⚠️ O caminho vai ao ExtendScript com a barra invertida no Windows (matriz §G2).
- ⛔ Sem a ponte instalada (⚙ › Integrações, ou `tools/integracoes.py --fazer`) o Premiere abre e nada responde: a frase
  diz o gesto.
"""

from __future__ import annotations

import glob
import os
import re
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from .nle.premiere import ponte as _ponte

#: Do lançamento à ponte responder. MEDIDO: 7–9 s no 26.5.2 com a ponte do laboratório; numa
#: máquina ocupada, ou com um projeto pesado na linha de comando, passa de um minuto.
PRAZO_DE_ABRIR_S = 240.0
#: Do `app.quit()` ao processo sumir, antes de tentar o `WM_CLOSE`.
PRAZO_DE_SAIR_S = 45.0
#: Depois do `WM_CLOSE`, antes de encerrar à força.
PRAZO_DO_WM_CLOSE_S = 20.0

EXE_WINDOWS = "Adobe Premiere Pro.exe"


class PremiereNaoAbre(RuntimeError):
    """Não deu para abrir, fechar ou falar com o Premiere — a frase diz o gesto."""


def instalados() -> dict[int, str]:
    """Os Premiere instalados, por ANO da pasta (2023, 2026…) → o executável.

    ⛔ Sem a versão BETA (autor, 2026-11-01: "a versão mais atual, excluindo versões beta"): a pasta
    `Adobe Premiere Pro (Beta)` também casa com o padrão, e um projeto aberto nela é convertido para
    um formato que a versão de produção não abre de volta.
    ⚠️ O ano da pasta não é a versão do programa (2023 = 23.x)."""
    if sys.platform == "darwin":
        achados = glob.glob("/Applications/Adobe Premiere Pro */Adobe Premiere Pro *.app")
    else:
        base = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        achados = glob.glob(os.path.join(base, "Adobe", "Adobe Premiere Pro *", EXE_WINDOWS))
    por_ano: dict[int, str] = {}
    for c in achados:
        if "beta" in c.lower():
            continue
        m = re.search(r"Premiere Pro (\d{4})", c)
        if m:
            por_ano[int(m.group(1))] = c
    return por_ano


def beta() -> str:
    """O Premiere BETA instalado (`Adobe Premiere Pro (Beta)`), ou "".

    ⭐ Autor, 2026-11-06: *"pode ajustar o produto para que ele abra o premiere beta"* — só quando
    PEDIDO (`versao="beta"`); sem pedido continua o mais novo de produção (a conversão de
    projeto de `instalados()` continua valendo)."""
    if sys.platform == "darwin":
        achados = glob.glob("/Applications/Adobe Premiere Pro*/Adobe Premiere Pro*.app")
    else:
        base = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        achados = glob.glob(os.path.join(base, "Adobe", "Adobe Premiere Pro*", EXE_WINDOWS))
    return next((c for c in sorted(achados) if "beta" in c.lower()), "")


def e_beta(versao: str | int = "") -> bool:
    return "beta" in str(versao or "").lower()


def executavel(versao: str | int = "") -> str:
    """O Premiere pedido (`versao` = o ano, ex. 2026, ou "beta") ou, sem pedido, o MAIS NOVO de
    produção. "" = não há."""
    if e_beta(versao):
        return beta()
    por_ano = instalados()
    if not por_ano:
        return ""
    if str(versao or "").strip():
        m = re.search(r"\d{4}", str(versao))
        return por_ano.get(int(m.group(0)), "") if m else ""
    return por_ano[max(por_ano)]


def processo_vivo() -> bool:
    """O processo PRINCIPAL do Premiere existe? ⚠️ macOS: o `pgrep` ancorado no executável (o
    `AdobeIPCBroker` e o `crashpad_handler` levam o caminho e ficam vivos — banco)."""
    try:
        if sys.platform == "win32":
            p = subprocess.run(["tasklist", "/FI", f"IMAGENAME eq {EXE_WINDOWS}", "/NH"],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=10, creationflags=0x08000000)
            return EXE_WINDOWS.lower() in (p.stdout or "").lower()
        p = subprocess.run(["pgrep", "-f", r"^/Applications/Adobe Premiere Pro [^/]+/Adobe Premiere Pro "
                            r"[^/]+\.app/Contents/MacOS/Adobe Premiere Pro [^/ ]+( |$)"],
                           capture_output=True, stdin=subprocess.DEVNULL, timeout=10)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _para_o_extendscript(caminho: str) -> str:
    return os.path.normpath(caminho) if sys.platform == "win32" else caminho


def _lancar(exe: str, projeto: str = "") -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", "-a", exe] + ([projeto] if projeto else []),
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return
    # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP: o Premiere não morre com o serviço.
    subprocess.Popen([exe] + ([projeto] if projeto else []), stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=0x00000008 | 0x00000200, close_fds=True)


def _esperar(condicao, prazo: float, relatar, etapa: str, comeco: float) -> bool:
    fim = time.monotonic() + prazo
    while time.monotonic() < fim:
        if condicao():
            return True
        if relatar:
            relatar(etapa, None, f"{int(time.monotonic() - comeco)} s")
        time.sleep(1.0)
    return condicao()


def _esquecer_o_projeto() -> None:
    try:
        from .nle import premiere as _premiere  # noqa: PLC0415
        _premiere.esquecer()
    except Exception:  # noqa: BLE001  — cache de leitura; não pode derrubar o abrir/fechar
        pass


def abrir(projeto: str, relatar=None, prazo: float = PRAZO_DE_ABRIR_S, versao: str = "") -> dict[str, Any]:
    """Abre o Premiere (se fechado) e o `.prproj` `projeto`, CRIANDO-o se não existir.

    Devolve `ja_estava`, `segundos`, `como` (ja_aberto · aberto · criado) e o `caminho`."""
    caminho = _para_o_extendscript(str(Path(projeto).expanduser()))
    comeco = time.monotonic()
    ja_estava = processo_vivo()
    pronta = _ponte.painel_vivo
    if not ja_estava:
        exe = executavel(versao)
        if not exe:
            anos = ", ".join(str(a) for a in sorted(instalados())) or "nenhum"
            raise PremiereNaoAbre(f"não achei o Premiere Pro {versao or ''} nesta máquina (instalados: {anos})".replace("  ", " "))
        # ⭐ Projeto que EXISTE vai na linha de comando; o novo nasce pela ponte.
        _lancar(exe, caminho if os.path.exists(caminho) else "")
        # ⛔ a ponte NOVA, e passada a espera de um long-poll da ponte de um Premiere que
        #   acabou de fechar (`ponte.bateu_desde`)
        lancado = time.monotonic()

        def pronta() -> bool:
            return (_ponte.bateu_desde(lancado)
                    and time.monotonic() > lancado + _ponte.ESPERA_DO_PAINEL_S + 1)
    if not _esperar(pronta, prazo, relatar, "abrindo o Premiere", comeco):
        raise PremiereNaoAbre(
            "o Premiere não ligou com o Ciclo Assist em "
            f"{int(prazo)} s. Se ele abriu, a ponte pode não estar instalada "
            "(⚙ Configurações › Integrações, e reabrir o Premiere) — ou há um diálogo na tela dele.")
    if relatar:
        relatar("abrindo o projeto no Premiere", None, Path(caminho).name)
    try:
        r = _ponte.chamar("cicloAbrirProjeto", caminho, prazo=180.0)
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        raise PremiereNaoAbre(str(e)) from e
    _esquecer_o_projeto()
    if r.get("ok") is False:
        raise PremiereNaoAbre(f"o Premiere não {'criou' if r.get('como') == 'criado' else 'abriu'} "
                              f"o projeto {caminho}")
    return {"ja_estava": ja_estava, "segundos": round(time.monotonic() - comeco, 1),
            "como": r.get("como") or "", "caminho": r.get("caminho") or caminho}


def _janela_principal() -> int:
    if sys.platform != "win32":
        return 0
    from . import janela as _janela  # noqa: PLC0415
    return _janela.janela_principal(EXE_WINDOWS) or 0


def _wm_close(hwnd: int) -> None:
    import ctypes  # noqa: PLC0415
    ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)   # WM_CLOSE


def _encerrar_a_forca() -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/IM", EXE_WINDOWS, "/F"], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=30, creationflags=0x08000000)
    else:
        subprocess.run(["pkill", "-f", "/Contents/MacOS/Adobe Premiere Pro"], capture_output=True, timeout=30)


def fechar(relatar=None) -> dict[str, Any]:
    """Salva o projeto aberto e fecha o Premiere. Devolve `como` saiu: quit · wm_close · forcado.

    ⛔ Só encerra À FORÇA com o projeto salvo (ou sem projeto): o que o editor não salvou não
    se perde por um gesto nosso.
    """
    if not processo_vivo():
        return {"ja_estava_fechado": True, "segundos": 0.0, "caminho": "", "salvo": False, "como": ""}
    comeco = time.monotonic()
    salvo, caminho, sem_ponte = False, "", False
    try:
        r = _ponte.chamar("cicloSalvar", prazo=120.0)
        salvo, caminho = bool(r.get("salvo")), str(r.get("caminho") or "")
    except _ponte.PremiereIndisponivel:
        sem_ponte = True
    except _ponte.ExtendScriptFalhou as e:
        raise PremiereNaoAbre(f"não consegui salvar o projeto antes de fechar ({e}); "
                              "não fechei o Premiere") from e
    seguro = salvo or (not sem_ponte and not caminho)
    como = "quit"
    if not sem_ponte:
        try:
            _ponte.chamar("cicloSair", prazo=5.0)
        except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou):
            pass        # ⚠️ a ponte morre com o Premiere: não ter resposta é o esperado
    saiu = _esperar(lambda: not processo_vivo(), 0 if sem_ponte else PRAZO_DE_SAIR_S,
                    relatar, "fechando o Premiere", comeco)
    if not saiu:
        hwnd = _janela_principal()
        if hwnd:
            como = "wm_close"
            _wm_close(hwnd)
            saiu = _esperar(lambda: not processo_vivo(), PRAZO_DO_WM_CLOSE_S, relatar,
                            "fechando o Premiere", comeco)
    if not saiu:
        if not seguro:
            raise PremiereNaoAbre(
                "o Premiere não fechou e eu não consegui confirmar que o projeto está salvo — "
                "não encerrei à força. Pode haver um diálogo na tela dele.")
        como = "forcado"
        _encerrar_a_forca()
        saiu = _esperar(lambda: not processo_vivo(), 15.0, relatar, "fechando o Premiere", comeco)
        if not saiu:
            raise PremiereNaoAbre("o Premiere não fechou nem à força")
    _esquecer_o_projeto()
    return {"ja_estava_fechado": False, "segundos": round(time.monotonic() - comeco, 1),
            "caminho": caminho, "salvo": salvo, "como": como}
