"""Abrir o seletor nativo de arquivo e pasta.

## Por que isto vive no SERVIÇO e não no painel

O painel é QtWebEngine. Um `<input type="file">` até abre o diálogo do sistema, mas o
navegador entrega só o **nome** do arquivo — o caminho absoluto é justamente o que ele
esconde por segurança, e é justamente o que precisamos para varrer a pasta e ler a mídia.

Então quem abre o diálogo é o serviço, que roda como processo local e enxerga o disco. O
painel pede, o serviço pergunta ao usuário, e volta um caminho de verdade.

## O diálogo roda num processo À PARTE, nos dois sistemas — e isso é requisito

macOS pelo `osascript`; Windows por um Python filho (`dialogo_win.py`, o Explorer
moderno) e, só como reserva, pelo `powershell` com WinForms. A escolha não é de
conveniência: um diálogo modal aberto **dentro** deste processo travaria o servidor
HTTP, e o painel — que bate `/health` a cada 4 s — daria o Media Composer por
desconectado enquanto o editor procura a pasta com calma. Num processo separado, o
modal trava apenas aquela requisição, que é o que se quer, e por isso a chamada é a
única coisa que aquela requisição faz. O teto de tempo é generoso pelo mesmo motivo:
achar uma pasta na rede leva minutos.

⚠️ **O diálogo precisa vir para a FRENTE.** Ele nasce atrás da janela do Media
Composer nos dois SOs, e o editor conclui que o botão não fez nada. No macOS a solução
é o `activate` do System Events; no Windows, uma janela 1x1 `TopMost` servindo de dona
do diálogo — em WinForms na reserva, em `ctypes` no moderno. É a mesma correção escrita
em três línguas.
"""

from __future__ import annotations

import logging
import subprocess
import sys

log = logging.getLogger("delapraca.escolher")

TEMPO_LIMITE_S = 300  # 5 min: o editor pode ir procurar a pasta na rede com calma


class NaoSuportado(RuntimeError):
    """Não há seletor nativo nesta plataforma."""


# ── macOS ───────────────────────────────────────────────────────────────────

def _osascript(script: str) -> str | None:
    """Roda AppleScript. `None` quando o usuário cancelou."""
    try:
        r = subprocess.run(["osascript", "-e", script], capture_output=True,
                           text=True, timeout=TEMPO_LIMITE_S)
    except subprocess.TimeoutExpired:
        raise RuntimeError("o seletor ficou aberto tempo demais") from None
    except FileNotFoundError:
        raise NaoSuportado("osascript não encontrado") from None

    saida = (r.stdout or "").strip()
    if r.returncode != 0:
        erro = (r.stderr or "").strip()
        # -128 é "o usuário cancelou". Não é erro, é resposta.
        if "-128" in erro or "User canceled" in erro:
            return None
        raise RuntimeError(erro.splitlines()[-1] if erro else "o seletor falhou")
    return saida or None


# ── Windows ─────────────────────────────────────────────────────────────────

# O preâmbulo de todo script de diálogo.
#
# ⚠️ `[Console]::OutputEncoding` não é detalhe: sem ele o PowerShell devolve o caminho
# na codepage ANSI da máquina, e um caminho com acento — `D:\GRAVAÇÕES\...`, que é a
# regra e não a exceção neste ramo — volta corrompido. O caminho corrompido não levanta
# erro: ele simplesmente não existe, e o app relata "pasta vazia".
#
# ⭐ `$dono` é um formulário invisível com `TopMost`. Passado como *owner* do diálogo,
# é o que traz a janela para a frente do Media Composer.
_PREAMBULO = r"""
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$dono = New-Object System.Windows.Forms.Form
$dono.TopMost = $true
$dono.ShowInTaskbar = $false
$dono.Opacity = 0
$dono.Size = New-Object System.Drawing.Size(1,1)
$dono.StartPosition = 'CenterScreen'
$dono.Show()
$dono.Activate()
"""

_EPILOGO = r"""
$dono.Close()
$dono.Dispose()
"""


def _powershell(corpo: str) -> str | None:
    """Roda um script de diálogo e devolve a linha que ele imprimiu (ou `None`).

    O contrato com o script é mínimo de propósito: **cancelar imprime nada**. Assim
    "o editor desistiu" e "deu erro" não se confundem — o segundo levanta.
    """
    script = _PREAMBULO + corpo + _EPILOGO
    try:
        r = subprocess.run(
            ["powershell.exe", "-NoProfile", "-STA", "-WindowStyle", "Hidden",
             "-ExecutionPolicy", "Bypass", "-Command", script],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=TEMPO_LIMITE_S,
            # A janela preta do console não deve piscar: o diálogo é GUI e aparece
            # de qualquer forma.
            creationflags=0x08000000,   # CREATE_NO_WINDOW
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("o seletor ficou aberto tempo demais") from None
    except FileNotFoundError:
        raise NaoSuportado("powershell.exe não encontrado") from None

    saida = (r.stdout or "").strip()
    if r.returncode != 0 and not saida:
        erro = (r.stderr or "").strip()
        raise RuntimeError(erro.splitlines()[-1] if erro else "o seletor falhou")
    return saida or None


# ── a interface pública ─────────────────────────────────────────────────────

# O seletor de pasta do Windows é o `IFileOpenDialog` com `FOS_PICKFOLDERS` — o Explorer
# moderno, com barra de endereço, "Acesso rápido" e **onde colar um caminho**. Mora em
# `dialogo_win.py`, que roda como processo filho. A recursão nas subpastas nunca dependeu
# do diálogo: quem varre é o `media/indexer.index_folder`, e sempre varreu.
#
# ⚠️⚠️ **CORRIGE o que estava escrito aqui (e no banco de NLEs) em 2026-08-16:** que o
# diálogo moderno exigiria "COM na unha" e só voltaria barato na Fase 6. Isso vale para o
# **PowerShell**, não para o Python. As duas tentativas que falharam foram:
#
# 1. `IFileOpenDialog` com a interface declarada em PowerShell — `NullReferenceException`
#    ao ler os resultados, num trecho que só roda com alguém clicando.
# 2. `OpenFileDialog` com `ValidateNames`/`CheckFileExists` desligados — o `FileName`
#    volta em duas formas conforme o gesto, e entregava a pasta MÃE.
#
# ⭐ **O que mudou não foi a interface COM, foi a LINGUAGEM.** Em `ctypes` a vtable se
# indexa direto e o marshalling é nosso, então o trecho que quebrava por inspeção virou
# depurável — e as chamadas puderam ser medidas SEM ninguém clicar (`CoCreateInstance`,
# `SetOptions` e a confirmação por `GetOptions` voltam `S_OK`; ver `dialogo_win.py`).
#
# ⚠️ **O antigo `FolderBrowserDialog` continua aqui como reserva, e o fracasso é
# FALANTE.** Cair calado para o diálogo antigo é o pior desfecho possível: o editor vê a
# árvore de novo, conclui que nada mudou, e quem for depurar procura no lugar errado.
# Por isso `ultimo_erro` é preenchido e a rota o devolve como `aviso`.


# Guardado para a rota poder contar ao editor por que algo falhou, em vez de deixá-lo
# olhando para um diálogo que não fez nada.
ultimo_erro: str | None = None


def _dialogo_win_moderno(titulo: str, *extras: str) -> list[str]:
    """Roda `dialogo_win.py` num processo filho. Lista vazia = o editor cancelou."""
    from pathlib import Path

    # ⚠️ Empacotado (PyInstaller), `sys.executable` é o EXECUTÁVEL DO SERVIÇO, não um
    # Python — chamá-lo com um `.py` subiria outro serviço em vez de abrir um diálogo. Ele
    # mesmo abre o diálogo com `--dialogo-win` (`main.ARG_DIALOGO`).
    if getattr(sys, "frozen", False):
        comando = [sys.executable, "--dialogo-win"]
    else:
        script = Path(__file__).resolve().with_name("dialogo_win.py")
        if not script.exists():
            raise RuntimeError(f"{script.name} não foi encontrado ao lado do serviço")
        comando = [sys.executable, str(script)]

    try:
        r = subprocess.run(
            [*comando, "--titulo", titulo, *extras],
            capture_output=True, encoding="utf-8", errors="replace",
            timeout=TEMPO_LIMITE_S,
            creationflags=0x08000000,  # CREATE_NO_WINDOW: o diálogo é GUI, o console não
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("o seletor ficou aberto tempo demais") from None

    if r.returncode != 0:
        erro = (r.stderr or "").strip()
        raise RuntimeError(erro.splitlines()[-1] if erro else "o seletor moderno falhou")
    return [linha.strip() for linha in (r.stdout or "").splitlines() if linha.strip()]


def _dialogo_win_antigo(titulo: str) -> list[str]:
    """A árvore do `SHBrowseForFolder`. Reserva, nunca a primeira escolha."""
    um = _powershell(f"""
$d = New-Object System.Windows.Forms.FolderBrowserDialog
$d.Description = "{_escapar_ps(titulo)}"
$d.ShowNewFolderButton = $false
if ($d.ShowDialog($dono) -eq [System.Windows.Forms.DialogResult]::OK) {{
  [Console]::Out.WriteLine($d.SelectedPath)
}}
""")
    return [um] if um else []


def escolher_pastas(titulo: str = "Onde estão as mídias originais") -> list[str]:
    """Diálogo de pasta. Devolve uma LISTA — vazia se o editor cancelou.

    ⭐ No Windows podem vir VÁRIAS de uma vez (`FOS_ALLOWMULTISELECT`): o editor marca
    as diárias todas numa passada, e o painel já acumula pastas. No macOS vem uma.
    """
    global ultimo_erro
    ultimo_erro = None

    if sys.platform == "win32":
        try:
            return _dialogo_win_moderno(titulo)
        except (RuntimeError, OSError) as e:
            # Não engolir: o editor vai ver a árvore antiga e precisa saber por quê.
            ultimo_erro = str(e)
            log.warning("seletor moderno indisponível (%s) — caindo para o antigo", e)
            return _dialogo_win_antigo(titulo)

    um = escolher_pasta(titulo)
    return [um] if um else []


def escolher_pasta(titulo: str = "Onde estão as mídias originais") -> str | None:
    """Diálogo de pasta. Devolve o caminho absoluto, ou `None` se cancelado."""
    if sys.platform == "win32":
        pastas = escolher_pastas(titulo)
        return pastas[0] if pastas else None
    if sys.platform == "darwin":
        # `activate` traz o diálogo para a frente: sem isso ele nasce atrás da janela do
        # Media Composer e o editor acha que o botão não fez nada.
        return _osascript(
            'tell application "System Events" to activate\n'
            f'set d to choose folder with prompt "{_escapar(titulo)}"\n'
            "POSIX path of d"
        )
    raise NaoSuportado("não há seletor nativo nesta plataforma")


def nomear_arquivo(titulo: str = "Dê um nome e escolha onde",
                   sugestao: str = "") -> str | None:
    """Diálogo *Salvar como*: o editor digita um NOME e escolhe ONDE, numa janela só.

    Devolve o caminho composto — **não cria nada**. Quem chama decide o que fazer.

    ⭐ Existe para não partir "nome + local" em duas superfícies (um campo nosso mais um
    seletor). Nomear e escolher onde guardar é um gesto único que o editor faz todo dia
    no sistema dele, e é lá que ele deve acontecer — a lição que este projeto já pagou.
    """
    global ultimo_erro
    ultimo_erro = None

    if sys.platform == "win32":
        try:
            achados = _dialogo_win_moderno(titulo, "--salvar", "--sugestao", sugestao)
        except (RuntimeError, OSError) as e:
            ultimo_erro = str(e)
            log.warning("diálogo de salvar indisponível (%s)", e)
            return None
        return achados[0] if achados else None

    if sys.platform == "darwin":
        # `choose file name` é o equivalente do AppleScript — mesmo gesto, mesma janela
        # que o editor conhece. `activate` pelo mesmo motivo de sempre.
        script = ('tell application "System Events" to activate\n'
                  f'set f to choose file name with prompt "{_escapar(titulo)}"')
        if sugestao:
            script += f' default name "{_escapar(sugestao)}"'
        return _osascript(script + "\nPOSIX path of f")

    raise NaoSuportado("não há seletor nativo nesta plataforma")


def escolher_arquivo(titulo: str = "Escolha a timeline",
                     extensoes: tuple[str, ...] = ("aaf",)) -> str | None:
    """Diálogo de arquivo, filtrado por extensão."""
    if sys.platform == "win32":
        # `Filter` é `rótulo|padrões`, com os padrões separados por ponto e vírgula.
        # O segundo par ("Todos os arquivos") existe de propósito: um AAF com extensão
        # inesperada é melhor recusado DEPOIS, com mensagem clara, do que invisível no
        # diálogo — mesma decisão do ramo macOS logo abaixo.
        padroes = ";".join(f"*.{e.lstrip('.')}" for e in extensoes)
        rotulo = " ".join(e.upper().lstrip(".") for e in extensoes)
        return _powershell(f"""
$d = New-Object System.Windows.Forms.OpenFileDialog
$d.Title = "{_escapar_ps(titulo)}"
$d.Filter = "{rotulo}|{padroes}|Todos os arquivos|*.*"
$d.Multiselect = $false
$d.CheckFileExists = $true
if ($d.ShowDialog($dono) -eq [System.Windows.Forms.DialogResult]::OK) {{
  [Console]::Out.WriteLine($d.FileName)
}}
""")

    if sys.platform == "darwin":
        # ⚠️ O `of type` do AppleScript espera UTIs em algumas versões e aceita
        # extensões em outras. Quando o filtro é recusado, o diálogo abre **sem
        # filtro** em vez de falhar — é melhor deixar o editor escolher um arquivo
        # qualquer (e recusá-lo depois, com mensagem clara) do que não abrir diálogo.
        lista = ", ".join(f'"{e}"' for e in extensoes)
        com_filtro = (
            'tell application "System Events" to activate\n'
            f'set f to choose file with prompt "{_escapar(titulo)}" of type {{{lista}}}\n'
            "POSIX path of f"
        )
        try:
            return _osascript(com_filtro)
        except RuntimeError as e:
            log.info("filtro de tipo recusado (%s) — abrindo sem filtro", e)
            return _osascript(
                'tell application "System Events" to activate\n'
                f'set f to choose file with prompt "{_escapar(titulo)}"\n'
                "POSIX path of f"
            )
    raise NaoSuportado("não há seletor nativo nesta plataforma")


def _escapar(texto: str) -> str:
    """Texto dentro de uma string de AppleScript."""
    return texto.replace("\\", "\\\\").replace('"', '\\"')


def _escapar_ps(texto: str) -> str:
    """Texto dentro de uma string de aspas duplas do PowerShell.

    ⚠️ O `` ` `` é o escape do PowerShell, e o `$` inicia interpolação — os dois têm
    de sair antes das aspas. Os títulos daqui são literais do nosso código, não entrada
    do editor, mas quem escapa "só onde precisa" acaba não escapando quando passa a
    precisar.

    ⚠️ As aspas CURVAS “ ” „ também fecham a string: o PowerShell as aceita como aspas
    duplas. O título do relink manual (“nome do clipe”) derrubava o diálogo com
    `UnexpectedToken` — medido no MC 25.6/Windows em 2026-10-13. Escapadas, aparecem como são.
    """
    texto = texto.replace("`", "``").replace("$", "`$")
    for aspa in ('"', "“", "”", "„"):
        texto = texto.replace(aspa, "`" + aspa)
    return texto
