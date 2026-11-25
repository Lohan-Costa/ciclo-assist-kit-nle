"""O único lugar do serviço que sabe em qual sistema operacional está.

## Por que existe

O plugin nasceu no macOS e o Windows é a plataforma-alvo. Espalhar
`if sys.platform == "darwin"` pelo código produz o pior modo de falha possível — o
que o banco de NLEs chama de **silêncio**: o caminho existe, é sintaticamente
válido, e simplesmente nunca aponta para nada. Nada levanta exceção; o sintoma
aparece longe da causa (*"89 clipes não encontrados"* com a mídia inteira no disco).

Então as diferenças moram todas aqui, cada uma com a medição que a justifica.

## O que foi MEDIDO nesta máquina (Windows 11 23H2, MC 25.6.0.58781, 2026-08-15)

| o quê | macOS | Windows |
|---|---|---|
| Painéis `.avpi` | `/Library/Application Support/Avid/PanelSDKPlugins` | `%PROGRAMDATA%\\Avid\\PanelSDKPlugins` |
| Settings do usuário do MC | `/Users/Shared/AvidMediaComposer/Avid Users` | `C:\\Users\\Public\\Documents\\Avid Media Composer\\Avid Users` |
| Executável do MC | `…/AvidMediaComposer.app/Contents/MacOS/AvidMediaComposer` | `C:\\Program Files\\Avid\\Avid Media Composer\\AvidMediaComposer.exe` |
| Pasta de trabalho do serviço | `~/Library/Application Support/DeLaPraCa` | `%LOCALAPPDATA%\\DeLaPraCa` |
| Um gateway é órfão quando… | `ppid == 1` (o `launchd` adota) | **seu `ppid` não está entre os PIDs vivos** |

⚠️ **É `%PROGRAMDATA%`, não `%APPDATA%`.** A pasta de painéis do Avid é de SISTEMA
nos dois SOs — ao contrário do Premiere (CEP) e do Resolve, que instalam por usuário.

⚠️ **`localhost` não aparece em lugar nenhum deste arquivo, e é de propósito.** No
Windows o nome resolve para IPv6 ao escutar e IPv4 ao discar, e a máquina *descarta*
o pacote em vez de recusá-lo: paga-se **timeout** antes do fallback (medido: 2 s a
15 s por requisição, contra 0,012 s pelo literal). Falamos com o Media Composer por
`[::1]:9100` e com o painel por `127.0.0.1:7823`, sempre literal.

## A regra que atravessa tudo

**Cheque se FUNCIONA, não se EXISTE.** Num volume compartilhado entre os dois SOs, o
artefato do outro sistema *está lá* e está errado. Toda função daqui que resolve
caminho devolve `None` quando o alvo não existe de verdade, em vez de devolver uma
string bonita que nunca vai abrir.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

log = logging.getLogger("delapraca.plataforma")

E_WINDOWS = sys.platform == "win32"
E_MACOS = sys.platform == "darwin"

# ⚠️ `CREATE_NO_WINDOW` (0x08000000): sem isto TODO subprocesso do serviço abre uma
# janela preta no Windows. Numa varredura de mídia são centenas de `ffprobe`, e a tela
# do editor pisca sem parar enquanto o plugin trabalha.
SEM_JANELA: dict = {"creationflags": 0x08000000} if E_WINDOWS else {}


#: Onde os instaladores do macOS põem os binários (banco, `transversal/matriz-de-plataforma.md`,
#: linha "onde os instaladores põem"): Homebrew no ARM e no Intel.
PASTAS_DE_INSTALADORES_MAC = ("/opt/homebrew/bin", "/usr/local/bin")


def completar_path() -> list[str]:
    """No macOS, põe no PATH do serviço as pastas dos instaladores que existem e faltam. Devolve as
    acrescentadas.

    ⛔ MEDIDO 2026-10-04 (macOS 15.6.1, Resolve 21.1): o serviço que a CASCA do Resolve sobe nasce com
    `PATH=/usr/bin:/bin:/usr/sbin:/sbin` (o de todo `.app` — matriz, linha "PATH de processo lançado").
    O `ffprobe` do Homebrew não estava nele, e o motor o chama pelo nome em 16 lugares: cada
    `_media_meta` falhava calado, todo clipe do pool herdava o TC da forma do esqueleto (03:44:58:12),
    o casamento com os originais não sondava nada (tudo no proxy) e a timeline do PRODUCAO_B entrou
    INTEIRA offline. De manhã o mesmo gesto tinha funcionado porque o serviço fora aberto pelo
    `ATUALIZAR.command`, com o PATH do terminal. Um lugar só, aqui, vale para as 16 chamadas e para
    quem quer que suba o serviço. No Windows, nada: o PATH do perfil já tem o `winget`."""
    if not E_MACOS:
        return []
    atual = os.environ.get("PATH", "").split(os.pathsep)
    novas = [p for p in PASTAS_DE_INSTALADORES_MAC if p not in atual and os.path.isdir(p)]
    if novas:
        os.environ["PATH"] = os.pathsep.join([*atual, *novas]).strip(os.pathsep)
    return novas


# ── caminhos do nosso serviço ───────────────────────────────────────────────

def versao() -> str:
    """A versão do build, lida do arquivo `VERSION` da raiz.

    ⭐ É o selo do rodapé do painel (a webview do MC guarda a página: o número denuncia build velha em cache)
    e a versão que os plugins instalados carregam (`integracoes.py`): plugin ≠ motor = "versão antiga".
    `VERSION` é o arquivo que o `tools/pack.py` incrementa. Montado (PyInstaller), ele viaja na raiz do pacote
    (`tools/montar_motor.py`); se faltar, o padrão é melhor que estourar por causa de um rótulo.
    """
    raiz = (Path(getattr(sys, "_MEIPASS", "")) if getattr(sys, "frozen", False)
            else Path(__file__).resolve().parents[3])
    try:
        return (raiz / "VERSION").read_text(encoding="utf-8").strip() or "0.0.0"
    except OSError:
        return "0.0.0"


def pasta_dados() -> Path:
    """Onde o serviço guarda o que precisa sobreviver entre execuções.

    ⚠️ **Não é uma pasta temporária, e isso é requisito.** Quem lê o AAF reescrito é
    o processo do *Media Composer*, e no macOS o TCC impede que ele leia
    `/private/tmp`. No Windows a pasta do perfil é a escolha equivalente: existe
    sempre, é do usuário que roda o MC, e não depende de o disco do projeto estar
    montado.
    """
    return _dados_padrao()


def _dados_padrao() -> Path:
    if E_WINDOWS:
        # `%LOCALAPPDATA%` e não `%APPDATA%`: isto é cache de trabalho de uma máquina,
        # não configuração que deva viajar num perfil móvel.
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")
        return Path(base) / "DeLaPraCa"
    if E_MACOS:
        return Path.home() / "Library/Application Support/DeLaPraCa"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "DeLaPraCa"


def _dados_desviados() -> Path | None:
    """A pasta de dados quando ela NÃO é a do sistema (teste ou bancada que trocou `pasta_dados`).

    ⛔ Banco, matriz "teste isolado por variável de ambiente": isolar só a pasta de dados deixa o
    cache e os logs na pasta REAL do usuário no Mac (`~/Library/Caches`, `~/Library/Logs`). Então,
    desviada a de dados, os outros dois vão junto, dentro dela."""
    d = pasta_dados()
    return d if d != _dados_padrao() else None


def pasta_do_ciclo_assist() -> Path:
    """A pasta de dados do Ciclo Assist — a MESMA conta de `cicloassist/servico/config.pasta()` (e do
    `avid/canal_do_nucleo.pasta_do_ciclo`): `CICLOASSIST_DADOS`, senão `%LOCALAPPDATA%\\CicloAssist` ·
    `~/Library/Application Support/CicloAssist`."""
    explicita = os.environ.get("CICLOASSIST_DADOS")
    if explicita:
        return Path(explicita)
    if E_WINDOWS:
        return Path(os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData/Local")) / "CicloAssist"
    if E_MACOS:
        return Path.home() / "Library/Application Support/CicloAssist"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "cicloassist"


def pasta_cache_padrao() -> Path:
    """Onde o cache mora quando o editor não escolheu outro lugar.

    ⭐ Desde 2026-11-07 (autor: "levar o cache para a pasta do Ciclo Assist, o caminho padrão"): o Conformar é módulo do
    Ciclo Assist, e o cache dele mora na pasta do app — `<CicloAssist>/conformar/cache`, nos dois sistemas. Antes:
    `%LOCALAPPDATA%\\DeLaPraCa\\Cache` · `~/Library/Caches/DeLaPraCa` (o cache velho foi apagado pelo autor, não migrado:
    é refeito quando preciso)."""
    desviada = _dados_desviados()
    if desviada is not None:
        return desviada / "Cache"
    return pasta_do_ciclo_assist() / "conformar" / "cache"


def pasta_logs() -> Path:
    """Os logs: ⭐ desde 2026-11-07 (autor: "trazer os logs junto, arquivados no lugar certo") na pasta do Ciclo Assist,
    ao lado dos do Assist — `<CicloAssist>/logs/conformar`, nos dois sistemas. Os de antes (`_logs_antigos`) são movidos
    para `antes-de-2026-11-07/` por `arquivar_logs_antigos`, na partida."""
    desviada = _dados_desviados()
    if desviada is not None:
        return desviada / "Logs"
    return pasta_do_ciclo_assist() / "logs" / "conformar"


def _logs_antigos() -> Path:
    """Onde os logs moravam até 2026-11-07: Windows `%LOCALAPPDATA%\\DeLaPraCa\\Logs` · macOS `~/Library/Logs/DeLaPraCa`."""
    if E_MACOS:
        return Path.home() / "Library/Logs/DeLaPraCa"
    return _dados_padrao() / "Logs"


#: Escritos por DENTRO do Media Composer pela dylib do ARO (laboratório, caminho fixo no C): ficam onde estão.
_DO_LABORATORIO = ("aro_servidor.log", "aro_sonda.log")


def arquivar_logs_antigos() -> list[str]:
    """Move os logs da pasta antiga para `<pasta_logs>/antes-de-2026-11-07/` (nada se apaga). Idempotente; arquivo que
    não se move (aberto no Windows) fica e é tentado na próxima partida. Devolve os nomes movidos."""
    if _dados_desviados() is not None:
        return []
    antiga = _logs_antigos()
    if not antiga.is_dir():
        return []
    destino = pasta_logs() / "antes-de-2026-11-07"
    movidos = []
    for f in sorted(antiga.iterdir()):
        if f.name in _DO_LABORATORIO or f.name.startswith("._"):
            continue
        try:
            destino.mkdir(parents=True, exist_ok=True)
            alvo = destino / f.name
            if alvo.exists():
                alvo = destino / f"{f.stem}.{int(time.time())}{f.suffix}"
            shutil.move(str(f), str(alvo))
            movidos.append(f.name)
        except OSError:
            continue
    try:
        antiga.rmdir()           # só se ficou vazia (sem os do laboratório)
    except OSError:
        pass
    return movidos


def pasta_trabalho() -> Path:
    """A subpasta dos AAF reescritos, já criada — no CACHE (o app a refaz; ver `cache.py`)."""
    import cache

    return cache.sub("trabalho")


# ── caminhos do DaVinci Resolve (Magic Link, lado de quem recebe) ────────────

def raiz_resolve_usuario() -> Path:
    """A pasta de suporte do Resolve DO USUÁRIO — existe se o Resolve já rodou aqui.

    Banco, `transversal/matriz-de-plataforma.md` §G3: no Windows há um `Support\\` que o
    macOS não tem (medido no Windows com o Studio 19.0.0b.59; macOS pelo README do Órbita).
    """
    if E_WINDOWS:
        base = os.environ.get("APPDATA") or str(Path.home() / "AppData/Roaming")
        return Path(base) / "Blackmagic Design" / "DaVinci Resolve" / "Support"
    return Path.home() / "Library/Application Support/Blackmagic Design/DaVinci Resolve"


def raiz_scripts_resolve() -> Path:
    """Onde um script aparece em Workspace → Scripts (o menu relê a pasta a cada abertura)."""
    return raiz_resolve_usuario() / "Fusion" / "Scripts" / "Utility"


def raiz_workflow_integrations() -> Path:
    """Onde o Resolve procura os Workflow Integration Plugins (a casca do painel). **De SISTEMA.**

    Banco, `plugins/resolve-scripting/workflow-integration.md` §5 e a matriz §G3: no Windows,
    medido 2026-09-25 (Studio 19.0.0b.59) — a pasta não existia e foi criada SEM elevação; o
    Resolve só a varre ao ABRIR. macOS pelo README da Blackmagic, `pendente` de medição
    (e `/Library` pode pedir administrador).
    """
    if E_WINDOWS:
        base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        return Path(base) / "Blackmagic Design" / "DaVinci Resolve" / "Support" / "Workflow Integration Plugins"
    return Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve/Workflow Integration Plugins")


def origem_workflow_integration_node() -> Path:
    """O `WorkflowIntegration.node` que a instalação do Resolve traz (no exemplo oficial).

    Não o redistribuímos: a instalação o COPIA daqui para a casca. Windows medido 2026-09-25;
    macOS inferido do README (`pendente`).
    """
    if E_WINDOWS:
        base = Path(os.environ.get("PROGRAMDATA") or r"C:\ProgramData") / "Blackmagic Design" / "DaVinci Resolve" / "Support"
    else:
        base = Path("/Library/Application Support/Blackmagic Design/DaVinci Resolve")
    return base / "Developer" / "Workflow Integrations" / "Examples" / "SamplePlugin" / "WorkflowIntegration.node"


# ── caminhos do Media Composer ──────────────────────────────────────────────

def raiz_paineis() -> Path:
    """A pasta onde os `.avpi` são instalados. **De sistema nos dois SOs.**"""
    if E_WINDOWS:
        base = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
        return Path(base) / "Avid" / "PanelSDKPlugins"
    return Path("/Library/Application Support/Avid/PanelSDKPlugins")


def raiz_settings_avid() -> Path | None:
    """A pasta `Avid Users`, onde vive o `<usuário> Settings.xml`. `None` se não há.

    Devolve `None` em vez de um caminho inexistente: um `Path` que nunca existe se
    propaga silenciosamente por várias camadas antes de virar sintoma.
    """
    candidatos = (
        [Path(r"C:\Users\Public\Documents\Avid Media Composer\Avid Users")]
        if E_WINDOWS else
        [Path("/Users/Shared/AvidMediaComposer/Avid Users")]
    )
    for c in candidatos:
        if c.is_dir():
            return c
    return None


def executavel_mc() -> Path | None:
    """O binário do Media Composer, se estiver instalado onde se espera."""
    if E_WINDOWS:
        p = Path(r"C:\Program Files\Avid\Avid Media Composer\AvidMediaComposer.exe")
    else:
        p = Path("/Applications/Avid Media Composer/AvidMediaComposer.app"
                 "/Contents/MacOS/AvidMediaComposer")
    return p if p.exists() else None


NOME_PROC_MC = "AvidMediaComposer.exe" if E_WINDOWS else "AvidMediaComposer"
NOME_PROC_GATEWAY = "avid-api-gateway.exe" if E_WINDOWS else "avid-api-gateway"


# ── processos ───────────────────────────────────────────────────────────────

def processos() -> list[tuple[int, int, str]]:
    """`[(pid, ppid, nome do executável)]` de tudo que está rodando.

    No Windows usa `CreateToolhelp32Snapshot` por `ctypes` — sem subprocesso, sem
    janela e sem dependência. As alternativas foram descartadas com motivo:
    `tasklist` **não traz PPID**, e `wmic` está formalmente deprecado desde o
    Windows 10 21H1. `Get-CimInstance Win32_Process` traz tudo, mas custa ~300 ms e
    um processo do PowerShell por consulta.
    """
    if E_WINDOWS:
        return _processos_windows()
    try:
        r = subprocess.run(["ps", "-axo", "pid=,ppid=,comm="],
                           capture_output=True, text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return []
    fora = []
    for linha in (r.stdout or "").splitlines():
        partes = linha.split(None, 2)
        if len(partes) == 3 and partes[0].isdigit() and partes[1].isdigit():
            fora.append((int(partes[0]), int(partes[1]), partes[2].strip()))
    return fora


def _processos_windows() -> list[tuple[int, int, str]]:
    import ctypes
    from ctypes import wintypes

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", wintypes.LONG),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", wintypes.WCHAR * 260),
        ]

    k32 = ctypes.windll.kernel32
    # ⚠️ Sem declarar o `restype`, o ctypes trata o HANDLE de 64 bits como `int` de 32 e
    # o **trunca** — a comparação com INVALID_HANDLE_VALUE passa a ser sobre outro
    # número, e o `CloseHandle` fecha coisa nenhuma. Falha silenciosa clássica.
    k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
    k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID = ctypes.c_void_p(-1).value

    snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if not snap or snap == INVALID:
        log.debug("CreateToolhelp32Snapshot falhou")
        return []
    try:
        entrada = PROCESSENTRY32W()
        entrada.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        if not k32.Process32FirstW(snap, ctypes.byref(entrada)):
            return []
        fora = []
        while True:
            fora.append((int(entrada.th32ProcessID),
                         int(entrada.th32ParentProcessID),
                         entrada.szExeFile))
            if not k32.Process32NextW(snap, ctypes.byref(entrada)):
                break
        return fora
    finally:
        k32.CloseHandle(snap)


def media_composer_aberto() -> bool:
    """O Media Composer está de pé?"""
    alvo = NOME_PROC_MC.lower()
    return any(nome.lower() == alvo or nome.lower().endswith("/" + alvo)
               for _, _, nome in processos())


def gateways_orfaos() -> list[int]:
    """PIDs de `avid-api-gateway` cujo pai já morreu.

    ⭐ **A assinatura do órfão muda de sistema operacional**, e é o tipo de detalhe
    que faz um zelador portado do macOS não encontrar nada no Windows:

    * **macOS** — o `launchd` adota o órfão, então `ppid == 1`.
    * **Windows** — não há reparentagem: o processo **mantém o `ppid` antigo**, que
      simplesmente deixa de apontar para alguém vivo.

    ⚠️ O Windows **recicla PID**. Se o PID do MC morto for reatribuído antes desta
    consulta, o órfão parece ter pai vivo por um ciclo. Por isso quem usa isto deve
    **reconsultar**, nunca decidir uma vez só.
    """
    procs = processos()
    vivos = {pid for pid, _, _ in procs}
    alvo = NOME_PROC_GATEWAY.lower()
    fora = []
    for pid, ppid, nome in procs:
        base = nome.lower().rsplit("/", 1)[-1]
        if base != alvo and alvo not in base:
            continue
        orfao = (ppid == 1) if E_MACOS else (ppid not in vivos)
        if orfao:
            fora.append(pid)
    return fora


# ── volumes ─────────────────────────────────────────────────────────────────

def raiz_do_volume(drive: str) -> Path | None:
    """A coluna `Drive` de uma bin do Avid → a raiz do volume no disco.

    ⭐ **O valor que a API devolve no Windows é `'SSD (D:)'`** — nem a letra,
    nem só o rótulo. Medido, não inferido: a primeira tentativa foi escrita olhando um
    print onde a coluna estava truncada (`CICLO-MED…`), o que escondia o ` (D:)`; a
    correção compilou, passou nos testes escritos com o valor imaginado e **não
    consertou nada**.

    No macOS o rótulo **já é um caminho** (`/Volumes/<rótulo>`, o sistema monta por
    nome) e por isso o bug não existe lá. No Windows não há caminho por rótulo, e um
    `f"{drive}:\\\\"` ingênuo produz `SSD (D:):\\` — sintaticamente válido,
    nunca existente, e o app relata *"clipes não encontrados"* com a mídia intacta ali.

    Três formas são aceitas, nesta ordem: a letra entre parênteses (vem de graça), a
    letra crua (`D`, `D:`, cobre volume **sem rótulo**), e a busca do rótulo entre os
    volumes montados (plano B — falha se dois volumes tiverem o mesmo nome).
    """
    drive = (drive or "").strip()
    if not drive:
        return None

    if not E_WINDOWS:
        p = Path("/Volumes") / drive
        return p if p.is_dir() else None

    # 1 e 2) a letra que vem na própria string (grátis, e não falha com nomes repetidos)
    letra = letra_do_drive(drive)
    if letra:
        raiz = Path(f"{letra}:\\")
        if raiz.is_dir():
            return raiz

    # 3) plano B: procurar o rótulo entre os volumes montados. Só agora, porque isto
    #    consulta o disco e **falha se dois volumes tiverem o mesmo nome**.
    for letra, nome in volumes_montados().items():
        if nome and nome.casefold() == rotulo_do_drive(drive).casefold():
            return Path(f"{letra}:\\")
    return None


def letra_do_drive(drive: str) -> str | None:
    """A letra de unidade contida na coluna `Drive`, sem tocar no disco.

        'SSD (D:)'  → 'D'
        'D:'  /  'D'  /  'D:\\'  → 'D'      (volume SEM rótulo)
        'SSD'       → None          (só o rótulo; cabe ao plano B)
        'ARQUIVO (2024)'    → None          (parênteses sem dois-pontos ≠ unidade)

    Separada de `raiz_do_volume` para ser **testável sem depender das unidades da
    máquina** — o formato é o que se errou da primeira vez, e é o que a regressão
    precisa travar.
    """
    import re

    drive = (drive or "").strip()
    if not drive:
        return None
    # Exigir os dois-pontos é o que impede confundir um volume chamado 'ARQUIVO (2024)'
    # com uma letra de unidade.
    m = re.search(r"\(([A-Za-z]):\)\s*$", drive)
    if m:
        return m.group(1).upper()
    cru = drive.rstrip("\\/")
    if re.fullmatch(r"[A-Za-z]:?", cru):
        return cru[0].upper()
    return None


def rotulo_do_drive(drive: str) -> str:
    """A coluna `Drive` sem o sufixo de letra. `'SSD (D:)'` → `'SSD'`."""
    import re

    return re.sub(r"\s*\([A-Za-z]:\)\s*$", "", (drive or "").strip()).strip()


def volumes_montados() -> dict[str, str]:
    """`{letra: rótulo}` dos volumes montados no Windows. `{}` nos outros SOs.

    ⚠️ **`SetErrorMode(SEM_FAILCRITICALERRORS)` não é opcional aqui.** Sem ele,
    consultar um **leitor de cartão vazio** abre o diálogo modal *"Insira um disco na
    unidade"* — e este processo roda em segundo plano, atrás da janela do Media
    Composer: ele **congela esperando um clique numa janela que ninguém vê**.
    """
    if not E_WINDOWS:
        return {}
    import ctypes

    k32 = ctypes.windll.kernel32
    anterior = k32.SetErrorMode(0x0001)          # SEM_FAILCRITICALERRORS
    try:
        montadas = k32.GetLogicalDrives()
        buf = ctypes.create_unicode_buffer(261)
        fora: dict[str, str] = {}
        for i in range(26):
            if not montadas & (1 << i):
                continue
            letra = chr(ord("A") + i)
            raiz = ctypes.c_wchar_p(f"{letra}:\\")
            if k32.GetVolumeInformationW(raiz, buf, 261, None, None, None, None, 0):
                fora[letra] = buf.value
            else:
                fora[letra] = ""
        return fora
    finally:
        k32.SetErrorMode(anterior)


# ── abrir coisas ────────────────────────────────────────────────────────────

def abrir_url(url: str) -> None:
    """Abre uma URL no navegador do usuário.

    Quem chama é responsável por garantir que a URL vem de uma **lista fechada** —
    esta função não valida nada, e o processo roda como o usuário.
    """
    if E_WINDOWS:
        os.startfile(url)  # noqa: S606 — destino de lista fechada, ver rotas.LINKS
        return
    if E_MACOS:
        subprocess.run(["open", url], timeout=10, check=False)
        return
    subprocess.run(["xdg-open", url], timeout=10, check=False)


def abrir_pasta(pasta: Path) -> None:
    """Mostra uma pasta no Explorer/Finder (matriz, linha "abrir pasta").

    Quem chama passa uma pasta que o PRÓPRIO serviço calculou (`cache.pasta_conhecida`): nunca um
    caminho vindo do painel. `os.startfile` num arquivo o EXECUTARIA — por isso só pasta."""
    if not pasta.is_dir():
        raise FileNotFoundError(str(pasta))
    if E_WINDOWS:
        os.startfile(str(pasta))  # noqa: S606 — pasta conhecida, ver docstring
        return
    if E_MACOS:
        subprocess.run(["open", str(pasta)], timeout=10, check=False)
        return
    subprocess.run(["xdg-open", str(pasta)], timeout=10, check=False)


# ── liberar as portas do Panel SDK ──────────────────────────────────────────

def matar_processo(pid: int, forcado: bool = False) -> None:
    """Encerra um processo. No Windows não há sinal — é `TerminateProcess`."""
    if E_WINDOWS:
        import ctypes

        PROCESS_TERMINATE = 0x0001
        h = ctypes.windll.kernel32.OpenProcess(PROCESS_TERMINATE, False, pid)
        if h:
            try:
                ctypes.windll.kernel32.TerminateProcess(h, 1)
            finally:
                ctypes.windll.kernel32.CloseHandle(h)
        return
    import signal as _signal

    os.kill(pid, _signal.SIGKILL if forcado else _signal.SIGTERM)


def liberar_gateway(todos: bool = False) -> dict:
    """Mata o `avid-api-gateway` que ficou segurando as portas do Panel SDK.

    ⭐ **Mora aqui, na camada de plataforma, e não na ferramenta de linha de comando**,
    porque agora tem DOIS chamadores: o `tools/reload.py` e o botão "liberar a porta" do
    aplicativo. Duas cópias da mesma rotina de matar processo é onde uma delas esquece a
    reconsulta e passa a mentir que matou.

    ⚠️ **Reconsultar em vez de decidir uma vez:** o Windows **recicla PID**, e um processo
    que demora a morrer ainda aparece no instantâneo anterior. Por isso mata-se, espera-se
    e pergunta-se de novo — insistindo com força só em quem sobreviveu.

    Devolve `{"mortos": [...], "restantes": [...], "mc_aberto": bool}` — o suficiente para
    a interface dizer o que aconteceu sem interpretar texto.
    """
    import time as _time

    alvo = NOME_PROC_GATEWAY.lower()

    def gateways_vivos() -> list[int]:
        return [pid for pid, _pai, nome in processos()
                if alvo in nome.lower().rsplit("/", 1)[-1]]

    pids = gateways_vivos() if todos else gateways_orfaos()
    resultado = {"mortos": [], "restantes": [], "mc_aberto": media_composer_aberto(),
                 "alvos": list(pids)}
    if not pids:
        return resultado

    for pid in pids:
        try:
            matar_processo(pid)
        except Exception:  # noqa: BLE001 — um pid que já morreu não é erro
            pass
    _time.sleep(1.0)

    teimosos = [p for p in gateways_vivos() if p in pids]
    for pid in teimosos:
        try:
            matar_processo(pid, forcado=True)
        except Exception:  # noqa: BLE001
            pass
    if teimosos:
        _time.sleep(1.0)

    restantes = gateways_vivos()
    resultado["restantes"] = restantes
    resultado["mortos"] = [p for p in pids if p not in restantes]
    return resultado


# ── apagar no exFAT do macOS ─────────────────────────────────────────────────────

def _remover(fn, caminho: str) -> None:
    """`fn(caminho)`; se o nome LISTADO não serve, tenta as duas normalizações do Unicode."""
    import unicodedata

    for alvo in (caminho, unicodedata.normalize("NFC", caminho), unicodedata.normalize("NFD", caminho)):
        try:
            fn(alvo)
            return
        except FileNotFoundError:
            continue
    raise FileNotFoundError(2, "não apaguei pelo nome listado nem em NFC/NFD", caminho)


def apagar_arquivo(caminho) -> None:
    """`unlink` que aguenta nome acentuado num disco exFAT do Mac (ver `apagar_arvore`)."""
    if not E_MACOS:
        os.remove(caminho)
        return
    _remover(os.remove, str(caminho))


def apagar_arvore(pasta) -> None:
    """`shutil.rmtree` que aguenta nome acentuado num disco exFAT do Mac. Levanta se algo ficar.

    MEDIDO 2026-10-05 (macOS 15.6.1, SSD exFAT): o exFAT LISTA em NFD, mas o arquivo gravado em NFC só sai
    pelo nome NFC — `rmtree` recebe "não encontrado" e, com o `FileNotFoundError` tratado como "já não
    existe", o "Limpar" do cache dizia que liberou e não apagava NADA (`Conferências/<timeline> · …`).
    No Windows, o `rmtree` de sempre (banco, matriz: "apagar nome com acento no exFAT").
    """
    import shutil

    if not E_MACOS:
        shutil.rmtree(pasta)
        return
    pasta = str(pasta)
    for raiz, dirs, arqs in os.walk(pasta, topdown=False):
        for n in arqs:
            _remover(os.remove, os.path.join(raiz, n))
        for n in dirs:
            c = os.path.join(raiz, n)
            _remover(os.remove if os.path.islink(c) else os.rmdir, c)
    _remover(os.rmdir, pasta)
