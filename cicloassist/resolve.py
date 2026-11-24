"""Abrir o DaVinci Resolve e um projeto nele — o Ciclo Assist vive FORA dos programas.

⭐⭐ Pedido do autor (2026-10-29): *"o usuário pode pedir coisas com o Ciclo Assist ainda
desconectado de qualquer app"*. O que o piloto fazia com mouse (abrir o Resolve, New Project,
digitar o nome) vira processo + API.

Tudo aqui é conhecimento do banco (`plugins/resolve-scripting/api-scripting.md`, matriz de
plataforma §G3), não descoberta nova:

- ⛔ **O Resolve abre DESTACADO, nunca como filho deste processo.** Aberto como filho de um
  Python, o servidor de scripts ficou mudo (duas vezes, `hipotese` da causa; o remédio medido
  é reabrir pelo `Start-Process`). No Windows quem o lança é o `explorer.exe` — o mesmo pai
  do duplo clique; no Mac, `open -a` SEM o `LANG` da sessão (o MC aborta com ele).
- ⛔ **A porta 1144 antes do `scriptapp`.** Sem o servidor de scripts no ar, o `scriptapp`
  leva ~4,1 s SEGURANDO O GIL e o serviço inteiro para. Daí também a API rodar num processo
  FILHO (`_na_api`): o pior caso congela o filho, nunca o painel.
- ⭐ `CreateProject`/`LoadProject` funcionam por fora, inclusive com o Resolve na janela de
  projetos (48 de 48 chamadas da casca, 2026-10-18).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import subprocess
import sys
import time
from typing import Any

log = logging.getLogger("cicloassist.resolve")

PORTA_DE_SCRIPTS = 1144

#: Do clique ao servidor de scripts no ar. MEDIDO no piloto: 16 s até a janela de projetos;
#: numa máquina ocupada a partida passa de um minuto.
PRAZO_DE_ABRIR_S = 180.0

#: A primeira conexão depois de certas aberturas falha (banco, 2 vezes): tenta por este tempo.
PRAZO_DA_API_S = 45.0

if sys.platform == "darwin":
    APLICATIVO = "/Applications/DaVinci Resolve/DaVinci Resolve.app"
    _API = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
    _LIB = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
else:
    APLICATIVO = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\Resolve.exe"
    _API = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"), "Blackmagic Design",
                        "DaVinci Resolve", "Support", "Developer", "Scripting")
    _LIB = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"


class ResolveIndisponivel(RuntimeError):
    """Não deu para abrir o Resolve ou falar com ele — a frase diz o gesto."""


def instalado() -> bool:
    return os.path.exists(APLICATIVO)


def servidor_no_ar() -> bool:
    """O servidor de scripts escutando. Sonda de `socket`: solta o GIL, 0,3 s no pior caso."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_DE_SCRIPTS), timeout=0.3):
            return True
    except OSError:
        return False


def _lancar() -> None:
    if sys.platform == "darwin":
        ambiente = {k: v for k, v in os.environ.items()
                    if k != "LANG" and not k.startswith("LC_")}
        subprocess.Popen(["open", "-a", APLICATIVO], env=ambiente,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    else:
        # ⛔ Pelo explorer: o Resolve nasce filho DELE, como no duplo clique — nunca nosso.
        subprocess.Popen(["explorer.exe", APLICATIVO], stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ── o servidor de scripts MUDO, e o contorno (2026-11-04) ─────────────────────
#
# ⛔⛔ MEDIDO de novo em 2026-11-04 (Studio 19.1.4, Win11), pelo chat: o Resolve aberto pela
# ferramenta levou 44 s até `Started script server`, as três tentativas dele falharam
# (`Failed to connect to script server`) e o servidor TERMINOU 0,3 s depois de abrir a porta.
# O `abrir()` de antes viu a porta naquele instante, deu por pronto, e o `scriptapp` voltou None
# — com uma frase sugerindo "o Free", que era falsa. É o padrão do banco
# (`plugins/resolve-scripting/api-scripting.md` §"O servidor de scripts"): abertura lenta =
# sessão inteira muda; o remédio medido é reabrir. ⇒ "pronto" é a API RESPONDER, "mudo" é o
# LOG do Resolve dizer, e o mudo SEM projeto aberto é fechado e reaberto sozinho.

#: Quantas vezes reabrir um Resolve mudo antes de devolver o gesto ao editor.
REABERTURAS = 2

#: Do pedido de fechar (WM_CLOSE) o Resolve mudo ao processo sumir; depois disso, à força —
#: só quando não há projeto aberto (não há o que perder).
PRAZO_DE_FECHAR_MUDO_S = 60.0

if sys.platform == "win32":
    _LOG_DO_RESOLVE = os.path.join(os.environ.get("APPDATA", ""), "Blackmagic Design",
                                   "DaVinci Resolve", "Support", "logs", "ResolveDebug.txt")
else:  # ⬜ macOS: o caminho do log é `pendente` (sem ele, mudo nunca é detectado: o de antes)
    _LOG_DO_RESOLVE = ""

#: A linha FINAL da desistência (as anteriores terminam em ", retrying").
_DESISTIU = "Failed to connect to script server"


def servidor_desistiu(desde: float = 0.0) -> bool:
    """O log da sessão atual do Resolve diz que o servidor de scripts desistiu de ligar?
    `desde` (relógio de parede): o log mais velho que isto é de outra sessão e não conta.
    ⚠️ O `ResolveDebug.txt` é reescrito a cada abertura (medido: a 1ª linha é a hora do arranque)."""
    if not _LOG_DO_RESOLVE:
        return False
    try:
        if desde and os.path.getmtime(_LOG_DO_RESOLVE) < desde:
            return False
        with open(_LOG_DO_RESOLVE, encoding="utf-8", errors="replace") as f:
            return any(l.strip() == _DESISTIU for l in f)
    except OSError:
        return False


def sem_projeto_aberto() -> bool:
    """Só a janela de projetos na tela: fechar o Resolve não perde trabalho nenhum.
    ⛔ Na dúvida, NÃO (macOS sem a leitura de janelas, nenhuma janela visível): quem fecha à
    força um Resolve com projeto aberto perde o que o editor não salvou."""
    if sys.platform != "win32":
        return False
    try:
        from . import janela
        titulos = [t for _h, t, _r in janela.janelas("Resolve.exe")]
    except Exception:  # noqa: BLE001
        return False
    return bool(titulos) and all(t.strip() == "Project Manager" for t in titulos)


def _fechar_mudo(prazo: float = PRAZO_DE_FECHAR_MUDO_S) -> None:
    """Fecha um Resolve mudo SEM projeto aberto: pede (WM_CLOSE), espera, e então força."""
    if sys.platform == "win32":
        try:
            from . import janela
            import ctypes
            for hwnd, _t, _r in janela.janelas("Resolve.exe"):
                ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)  # WM_CLOSE
        except Exception:  # noqa: BLE001
            log.debug("WM_CLOSE no Resolve falhou", exc_info=True)
    t = time.monotonic()
    while time.monotonic() - t < prazo:
        if not processo_vivo():
            return
        time.sleep(1.0)
    log.warning("o Resolve mudo não fechou em %d s; encerrando à força (sem projeto aberto)", prazo)
    _forcar()


def _forcar() -> None:
    """Encerra o processo à força e espera ele sumir. ⚠️ Só para quem NÃO tem o que perder.
    macOS: o SIGTERM não basta para o Resolve preso no desligamento (medido 2026-11-05)."""
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/F", "/IM", "Resolve.exe"], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=30, creationflags=0x08000000)
    else:
        subprocess.run(["pkill", "-9", "-x", "Resolve"], capture_output=True,
                       stdin=subprocess.DEVNULL, timeout=30)
    t = time.monotonic()
    while processo_vivo() and time.monotonic() - t < 30:
        time.sleep(1.0)


_MUDO_COM_PROJETO = (
    "o DaVinci Resolve está aberto, mas o servidor de scripts dele não ligou nesta abertura "
    "(falha conhecida do Resolve quando ele demora a abrir; não é o Free). Como há um projeto "
    "aberto nele, não o fechei: salve o projeto, feche o Resolve e peça de novo — eu o abro.")


def _api_responde(prazo: float = PRAZO_DA_API_S) -> dict[str, Any] | None:
    """Uma chamada de verdade (`projeto_atual`): a porta aberta não prova nada (ela pisca 0,3 s
    antes do servidor desistir). None = não respondeu."""
    try:
        return _na_api("atual", prazo=prazo)
    except ResolveIndisponivel:
        return None


def abrir(relatar=None, prazo: float = PRAZO_DE_ABRIR_S) -> dict[str, Any]:
    """Abre o Resolve se ele não estiver no ar e espera a API RESPONDER. Devolve os segundos.

    Resolve mudo (o log diz que o servidor de scripts desistiu): sem projeto aberto, fecha e
    reabre (até `REABERTURAS` vezes); com projeto, devolve o gesto ao editor."""
    def contar(o_que: str, t0: float) -> None:
        if relatar:
            relatar(o_que, None, f"{int(time.monotonic() - t0)} s")

    t = time.monotonic()
    if servidor_no_ar() and _api_responde() is not None:
        return {"ja_estava": True, "segundos": 0.0}
    if not instalado():
        raise ResolveIndisponivel(f"não achei o DaVinci Resolve em {APLICATIVO}")
    reaberturas = 0
    while True:
        lancado_em = 0.0
        if processo_vivo():
            if servidor_desistiu():
                if not sem_projeto_aberto():
                    raise ResolveIndisponivel(_MUDO_COM_PROJETO)
                if reaberturas >= REABERTURAS:
                    break
                reaberturas += 1
                log.warning("Resolve com o servidor de scripts mudo e sem projeto: fechando e "
                            "abrindo de novo (%d de %d)", reaberturas, REABERTURAS)
                contar("o servidor de scripts do Resolve não ligou; fechando e abrindo de novo", t)
                _fechar_mudo()
                continue
            # vivo e ainda sem veredito: está abrindo (aberto por outro gesto) — só esperar
        else:
            lancado_em = time.time()
            _lancar()
        inicio = time.monotonic()
        while time.monotonic() - inicio < prazo:
            contar("abrindo o DaVinci Resolve", t)
            if servidor_no_ar() and _api_responde() is not None:
                log.info("Resolve pronto para script em %.1f s (%d reabertura[s])",
                         time.monotonic() - t, reaberturas)
                return {"ja_estava": False, "segundos": round(time.monotonic() - t, 1),
                        "reaberturas": reaberturas}
            if servidor_desistiu(lancado_em) and processo_vivo():
                break  # mudo: volta ao topo, que decide reabrir
            time.sleep(1.0)
        else:
            raise ResolveIndisponivel(
                f"o DaVinci Resolve não ficou pronto para script em {int(prazo)} s. Se a janela "
                f"dele abriu, feche-o e peça de novo.")
    raise ResolveIndisponivel(
        f"o servidor de scripts do DaVinci Resolve não ligou em {REABERTURAS + 1} aberturas seguidas "
        f"(falha conhecida do Resolve com a máquina ocupada; não é o Free). Feche outros programas "
        f"pesados, feche o Resolve e peça de novo.")


# O que roda no processo FILHO. Sai uma linha JSON. ⚠️ Sem f-string: as chaves são do Python de lá.
_CODIGO = r"""
import json, os, sys, time
# ⛔ O pai lê UTF-8; sem isto o filho escreve em cp1252 e um projeto "UIA ÇÃO 01" quebrava a leitura (0xC7) e virava
# "a conversa com o DaVinci Resolve falhou: sem resposta" (medido 2026-11-05, piloto).
sys.stdout.reconfigure(encoding="utf-8")
os.environ.setdefault("RESOLVE_SCRIPT_API", sys.argv[1])
os.environ.setdefault("RESOLVE_SCRIPT_LIB", sys.argv[2])
sys.path.append(os.path.join(sys.argv[1], "Modules"))
acao, nome, prazo = sys.argv[3], sys.argv[4], float(sys.argv[5])
try:
    import DaVinciResolveScript as dvr
except ImportError:
    print(json.dumps({"erro": "a API de script do DaVinci Resolve não está instalada nesta máquina"})); sys.exit(0)
fim = time.monotonic() + prazo
r = None
while r is None and time.monotonic() < fim:
    r = dvr.scriptapp("Resolve")
    if r is None:
        time.sleep(2)
if r is None:
    print(json.dumps({"erro": "o DaVinci Resolve não respondeu ao script (o Free não aceita script externo; no Studio, feche e abra o Resolve)"})); sys.exit(0)
pm = r.GetProjectManager()
atual = pm.GetCurrentProject()
saida = {"versao": r.GetVersionString(), "antes": atual.GetName() if atual else ""}
if acao == "projeto":
    if atual and atual.GetName() == nome:
        saida.update(projeto=nome, como="ja_aberto")
    elif pm.LoadProject(nome):
        saida.update(projeto=nome, como="aberto")
    elif pm.CreateProject(nome):
        saida.update(projeto=nome, como="criado")
    else:
        saida["erro"] = "o Resolve não abriu nem criou o projeto " + repr(nome)
elif acao == "fechar":
    # ⛔ Nunca no meio de um render: o Quit o interromperia e a mídia sairia pela metade.
    if atual and atual.IsRenderingInProgress():
        saida["erro"] = "o Resolve está renderizando; espere o render acabar para fechá-lo"
    else:
        saida["projeto"] = saida["antes"]
        # ⛔ O "Untitled Project" (o rascunho que o Resolve abre sem projeto) nunca foi salvo: o SaveProject
        # abre o diálogo "Save Current Project" pedindo um NOME e a API fica presa atrás dele (medido no Mac,
        # 2026-11-05: 75 s e "não respondeu ao script a tempo"). Rascunho não se salva; fecha-se.
        rascunho = bool(atual) and atual.GetName() == "Untitled Project"
        saida["salvo"] = bool(pm.SaveProject()) if atual and not rascunho else False
        # A resposta sai ANTES do Quit: depois dele não há com quem falar.
        print(json.dumps(saida, ensure_ascii=False), flush=True)
        r.Quit()
        sys.exit(0)
elif acao == "arquivos_do_pool":
    # So le: o caminho de cada clipe da pasta do Media Pool e das filhas. `nome` vazio = o pool inteiro.
    mp = atual.GetMediaPool() if atual else None
    pasta = mp.GetRootFolder() if mp else None
    if pasta is None:
        saida["erro"] = "o DaVinci Resolve não está com um projeto aberto"
    else:
        partes = [p for p in nome.replace("\\", "/").split("/") if p]
        if partes and partes[0].casefold() == pasta.GetName().casefold():
            partes = partes[1:]
        for parte in partes:
            pasta = next((s for s in (pasta.GetSubFolderList() or []) if s.GetName().casefold() == parte.casefold()), None)
            if pasta is None:
                saida["erro"] = "não há a pasta " + repr(nome) + " no Media Pool"
                break
        if pasta is not None:
            arquivos, fila = [], [pasta]
            while fila:
                atual_pasta = fila.pop()
                fila += list(atual_pasta.GetSubFolderList() or [])
                arquivos += [c for c in (x.GetClipProperty("File Path") for x in (atual_pasta.GetClipList() or [])) if c]
            saida["arquivos"] = sorted(set(arquivos))
else:
    saida["projeto"] = saida["antes"]
print(json.dumps(saida, ensure_ascii=False))
"""


def _na_api(acao: str, nome: str = "", prazo: float = PRAZO_DA_API_S) -> dict[str, Any]:
    if not servidor_no_ar():
        raise ResolveIndisponivel("o DaVinci Resolve não está aberto (o servidor de scripts não respondeu)")
    opcoes: dict[str, Any] = {}
    if sys.platform == "win32":
        opcoes["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    try:
        p = subprocess.run([sys.executable, "-c", _CODIGO, _API, _LIB, acao, nome, str(prazo)],
                           capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL, timeout=prazo + 30, **opcoes)
    except subprocess.TimeoutExpired:
        raise ResolveIndisponivel("o DaVinci Resolve não respondeu ao script a tempo") from None
    linhas = [l for l in (p.stdout or "").splitlines() if l.strip().startswith("{")]
    if not linhas:
        raise ResolveIndisponivel("a conversa com o DaVinci Resolve falhou: "
                                  + ((p.stderr or "").strip().splitlines() or ["sem resposta"])[-1])
    r = json.loads(linhas[-1])
    if r.get("erro"):
        if "não respondeu ao script" in str(r["erro"]) and servidor_desistiu():
            # ⛔ O Studio mudo NÃO é o Free: a frase do Free mandava o editor caçar a licença.
            raise ResolveIndisponivel(
                _MUDO_COM_PROJETO if not sem_projeto_aberto() else
                "o servidor de scripts do DaVinci Resolve não ligou nesta abertura (falha "
                "conhecida quando ele demora a abrir; não é o Free). Peça de novo: eu fecho e "
                "abro o Resolve.")
        raise ResolveIndisponivel(str(r["erro"]))
    return r


def projeto(nome: str) -> dict[str, Any]:
    """Abre o projeto `nome` no Resolve, ou o cria. `como`: ja_aberto · aberto · criado."""
    return _na_api("projeto", nome)


def projeto_atual() -> dict[str, Any]:
    return _na_api("atual")


def arquivos_do_pool(pasta: str = "") -> list[str]:
    """Os arquivos da pasta do Media Pool e das filhas (só leitura). Vazio = o pool inteiro. `ResolveIndisponivel` com o motivo."""
    return list(_na_api("arquivos_do_pool", pasta).get("arquivos") or [])


#: Do `Quit` ao processo sumir. MEDIDO (2026-11-01, 19.1.4): a porta cai em 1,3 s e o
#: `Resolve.exe` ainda vive ~12 s depois.
PRAZO_DE_FECHAR_S = 90.0
#: Porta de scripts fechada e o processo ainda vivo: no normal ele sai em ~4 s (medido no Mac, 21.1).
PRESO_NO_DESLIGAMENTO_S = 20.0


def processo_vivo() -> bool:
    """O processo do Resolve existe? ⚠️ macOS: o nome `Resolve` no `pgrep` é `pendente`."""
    try:
        if sys.platform == "win32":
            p = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Resolve.exe", "/NH"],
                               capture_output=True, text=True, stdin=subprocess.DEVNULL,
                               timeout=10, creationflags=0x08000000)
            return "resolve.exe" in (p.stdout or "").lower()
        p = subprocess.run(["pgrep", "-x", "Resolve"], capture_output=True,
                           stdin=subprocess.DEVNULL, timeout=10)
        return p.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def fechar(relatar=None, prazo: float = PRAZO_DE_FECHAR_S) -> dict[str, Any]:
    """Salva o projeto aberto e fecha o Resolve (`SaveProject` → `Quit`), esperando ele sair.

    ⛔ "Fechou" é o PROCESSO sumir, não a palavra da API nem a porta: o `Quit` só PEDE, a
    porta de scripts cai em 1,3 s com o processo ainda vivo por ~12 s (medido), e um
    diálogo na tela dele seguraria o processo para sempre.
    """
    if not servidor_no_ar():
        return {"ja_estava_fechado": True, "segundos": 0.0, "projeto": "", "salvo": False}
    t = time.monotonic()
    r = _na_api("fechar")
    # ⛔ macOS (21.1, medido 2026-11-05): o Quit pela API às vezes TRAVA o desligamento — processo vivo, sem
    #   janela, porta de scripts fechada, a pilha parada em `Fusion…ScriptState::Recycle` (1 em 3 com o Quit
    #   logo depois de abrir). Não sai sozinho; nem o SIGTERM o tira. Com o projeto JÁ salvo (ou o rascunho, que
    #   não tem o que salvar) não há o que perder: passado `PRESO_NO_DESLIGAMENTO_S` sem porta, encerra-se.
    sem_perda = bool(r.get("salvo")) or r.get("projeto") == "Untitled Project"
    sem_porta_desde = None
    while time.monotonic() - t < prazo:
        if not servidor_no_ar() and not processo_vivo():
            return {"ja_estava_fechado": False, "segundos": round(time.monotonic() - t, 1),
                    "projeto": r.get("projeto") or "", "salvo": bool(r.get("salvo")),
                    "versao": r.get("versao") or ""}
        if servidor_no_ar():
            sem_porta_desde = None
        elif sem_porta_desde is None:
            sem_porta_desde = time.monotonic()
        elif sem_perda and time.monotonic() - sem_porta_desde > PRESO_NO_DESLIGAMENTO_S:
            log.warning("o Resolve ficou preso no desligamento (%d s sem a porta); encerrando à força "
                        "— o projeto %r já estava salvo", PRESO_NO_DESLIGAMENTO_S, r.get("projeto"))
            _forcar()
            sem_porta_desde = time.monotonic()
        if relatar:
            relatar("fechando o DaVinci Resolve", None, f"{int(time.monotonic() - t)} s")
        time.sleep(1.0)
    raise ResolveIndisponivel(
        f"pedi para o DaVinci Resolve fechar e ele continua aberto depois de {int(prazo)} s — "
        f"pode haver um diálogo esperando na tela dele.")
