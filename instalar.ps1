# =============================================================================
# Ciclo Assist — INSTALAR (para quem USA, não para quem programa)
#
# Não rode este arquivo direto: dê **duplo clique em `INSTALAR.bat`**, que é quem sabe
# destravar a execução de scripts do Windows e manter a janela aberta.
#
# O que ele faz, nesta ordem:
#   1. confere o Python
#   2. confere o Claude Code — e sabe distinguir "não tem", "tem só o app" e "falta login"
#   3. confere o ffmpeg
#   4. prepara o ambiente do aplicativo
#   5. instala a ponte do Premiere e tira as integrações antigas (nenhum painel dentro dos editores)
#   6. oferece iniciar o serviço junto com o Windows
#
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ ESTE ARQUIVO PRECISA ESTAR EM UTF-8 **COM BOM**. NÃO REMOVA O BOM.
#
# O Windows PowerShell 5.1 lê um `.ps1` sem BOM como ANSI (cp1252). Um traço longo vira
# `â€"`, e o `0x94` do cp1252 é `”` — que o parser aceita como aspas de fechamento. A
# string termina onde não devia, o resto da linha vira código, e o script morre com
# `Missing closing '}'` apontando dezenas de linhas ADIANTE do acento que causou tudo.
# Medido no De Lá Pra Cá em 2026-08-15. `tests/test_scripts_powershell.py` trava a volta.
# ─────────────────────────────────────────────────────────────────────────────
#
# ⚠️ `Stop` NÃO serve aqui — é do PowerShell 5.1, não deste script: com ele, qualquer
# linha que um EXECUTÁVEL escreva em stderr vira erro terminante, mesmo com código de
# saída 0. A verificação é EXPLÍCITA, por `$LASTEXITCODE`.
# =============================================================================

# ⛔⛔ **`param()` TEM de ser a primeira instrução do script**, antes de qualquer linha
# executável. Fora do topo, o PowerShell o interpreta como um COMANDO chamado `param` —
# e o modo de falha é o pior possível: o parser aceita o arquivo, aparece um
# `CommandNotFoundException` no meio da saída, **o script continua rodando**, e o
# parâmetro simplesmente não existe. Medido aqui em 2026-09-10: `-Conferir` foi ignorado
# em silêncio e o instalador seguiu para a tela de consentimento.
#
# ⭐ `-Conferir` roda SÓ as verificações e não instala nada. Serve ao suporte ("rode
# INSTALAR.bat -Conferir e me mande a saída") e permite exercitar os caminhos de detecção
# sem mexer na máquina de ninguém.
param([switch]$Conferir)

$ErrorActionPreference = "Continue"

[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"

function Titulo($m) { Write-Host ""; Write-Host "  $m" -ForegroundColor White }
function Passo($m)  { Write-Host "> $m"        -ForegroundColor Cyan }
function Ok($m)     { Write-Host "   OK  $m"   -ForegroundColor Green }
function Aviso($m)  { Write-Host "   !   $m"   -ForegroundColor Yellow }
function Nota($m)   { Write-Host "       $m"   -ForegroundColor DarkGray }

# ⚠️ Nunca `exit 1` seco num script de duplo clique: a janela fecha e leva a mensagem de
# erro junto. Quem está lendo precisa VER o que deu errado.
function Morre($m) {
    Write-Host ""
    Write-Host "   X   $m" -ForegroundColor Red
    Write-Host ""
    Write-Host "   Nada foi quebrado — o que já existia continua como estava." -ForegroundColor DarkGray
    Write-Host ""
    Read-Host "   Pressione Enter para fechar"
    exit 1
}

function Pergunta($m) {
    $r = Read-Host "   $m [s/N]"
    return ($r -match '^[sSyY]')
}

Write-Host ""
Write-Host "  +----------------------------------------------+"
Write-Host "  |   Ciclo Assist - instalacao                  |"
Write-Host "  |   assistente de edicao no Media Composer     |"
Write-Host "  +----------------------------------------------+"

$RAIZ = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RAIZ

# ── O que o editor precisa saber ANTES de instalar ───────────────────────────
#
# ⭐⭐ Vem primeiro, antes de qualquer passo, porque é consentimento — e
#    consentimento depois de instalado não é consentimento. Ver `docs/ameacas.md` §1:
#    o produto não tem inteligência própria, então para o Claude responder sobre o
#    material, o material precisa CHEGAR até ele.
#
# ⚠️ Uma produção sob NDA precisa decidir isto com o gerente dela, não descobrir depois.
if ($Conferir) {
    Write-Host ""
    Write-Host "   (modo conferência — nada será instalado)" -ForegroundColor DarkGray
}

# ⚠️ A tela de consentimento não aparece no modo conferência porque nada é instalado —
#    e pedir consentimento para não fazer nada só ensina a clicar "sim" sem ler.
Write-Host ""
if (-not $Conferir) {
Write-Host "  ------------------------------------------------" -ForegroundColor Yellow
Write-Host "   Antes de instalar, uma coisa importante" -ForegroundColor Yellow
Write-Host "  ------------------------------------------------" -ForegroundColor Yellow
Write-Host ""
Write-Host "   O Ciclo Assist não tem inteligência própria: ele conversa com o"
Write-Host "   Claude, que roda na SUA assinatura."
Write-Host ""
Write-Host "   Para ele responder sobre o seu material, parte do material SAI"
Write-Host "   desta máquina e vai para a Anthropic:" -ForegroundColor White
Write-Host ""
Write-Host "     - quadros do vídeo, reduzidos (quando você pede para ele VER)"
Write-Host "     - a transcrição do som direto (quando você pede para ele OUVIR)"
Write-Host "     - nomes de bin, de clipe e o caminho do projeto"
Write-Host "     - o que você escreve no painel"
Write-Host ""
Write-Host "   O arquivo de mídia original NÃO sai. A bin e o projeto NÃO saem."
Write-Host "   Nada passa por servidor nosso — não temos servidor."
Write-Host ""
Nota "Se o seu projeto tem acordo de confidencialidade, decida isto com quem"
Nota "responde por ele antes de seguir."
Write-Host ""
if (-not (Pergunta "Entendi e quero instalar")) {
    Write-Host ""
    Write-Host "   Tudo bem — nada foi instalado." -ForegroundColor DarkGray
    Write-Host ""
    Read-Host "   Pressione Enter para fechar"
    exit 0
}
}

$VENV   = Join-Path $RAIZ ".venv-win"
$PY     = Join-Path $VENV "Scripts\python.exe"
$PORTA  = 7824

# ── 1. Python ────────────────────────────────────────────────────────────────
Titulo "1 de 6 — Python"

$LANCADOR = $null
foreach ($v in @("3.13", "3.12", "3.11")) {
    $null = (& py "-$v" -c "import sys" 2>&1)
    if ($LASTEXITCODE -eq 0) { $LANCADOR = $v; break }
}
if (-not $LANCADOR) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) {
        Morre @"
O Python não está instalado nesta máquina.

       Baixe em https://www.python.org/downloads/  (versão 3.11 ou mais nova)
       ⚠️ Na primeira tela do instalador, MARQUE "Add Python to PATH".
       Depois rode este instalador de novo.
"@
    }
    $v = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ([version]$v -lt [version]"3.11") { Morre "Python $v é antigo demais — preciso de 3.11 ou mais novo." }
    Ok "Python $v"
} else {
    Ok "Python $LANCADOR"
}

# ── 2. O Claude Code ─────────────────────────────────────────────────────────
Titulo "2 de 6 — Claude Code (o motor)"

# ⭐⭐ **Três estados, não dois**, e tratá-los como um só manda a pessoa pelo caminho
#    errado. Quem instalou o app de desktop tem o Claude aberto na tela e paga a
#    assinatura — e conclui, com razão, que já está pronto. Ver ADR 0006.
$claude = Get-Command claude -ErrorAction SilentlyContinue
if (-not $claude) {
    $temApp = Test-Path (Join-Path $env:LOCALAPPDATA "AnthropicClaude")
    if ($temApp) {
        Morre @"
Você tem o APLICATIVO do Claude, mas falta o CLAUDE CODE.

       São dois programas diferentes, com instaladores diferentes. A sua conta
       e a sua assinatura já servem — falta só instalar este segundo programa.

       Baixe em https://claude.com/claude-code
       Depois rode este instalador de novo.
"@
    }
    Morre @"
O Claude Code não está instalado.

       É ele que faz o trabalho: o Ciclo Assist não tem inteligência própria,
       ele conversa com o Claude que roda na SUA assinatura.

       Baixe em https://claude.com/claude-code
       Depois rode este instalador de novo.
"@
}

$versao = (& claude --version 2>&1 | Select-Object -First 1)
Ok "Claude Code $versao"

# ⭐ `claude auth status` devolve JSON, é instantâneo e não gasta nada da assinatura —
#    diferente de mandar uma pergunta só para descobrir se há login.
$bruto = (& claude auth status 2>&1 | Out-String)
$logado = $false
$plano = ""
try {
    $auth = $bruto | ConvertFrom-Json
    $logado = [bool]$auth.loggedIn
    $plano = "$($auth.email) · $($auth.subscriptionType)"
} catch {
    Aviso "não consegui ler o estado do login; seguindo assim mesmo"
}

if ($logado) {
    Ok "Conta conectada — $plano"
} else {
    Aviso "O Claude Code está instalado mas você ainda não entrou na sua conta."
    Nota "Vou abrir o login agora. Volte para esta janela quando terminar."
    if ($Conferir) {
        Nota "(modo conferência — não vou abrir o login)"
    } elseif (Pergunta "Fazer login agora?") {
        & claude auth login
        $bruto = (& claude auth status 2>&1 | Out-String)
        try { $logado = [bool]($bruto | ConvertFrom-Json).loggedIn } catch { }
        if ($logado) { Ok "Conta conectada" }
        else { Aviso "ainda sem login — o painel vai abrir, mas não vai responder" }
    } else {
        Aviso "Sem login o painel abre e não responde. Rode: claude auth login"
    }
}

# ── 3. ffmpeg ────────────────────────────────────────────────────────────────
Titulo "3 de 6 — ffmpeg"

$faltando = @()
foreach ($bin in @("ffmpeg", "ffprobe")) {
    if (Get-Command $bin -ErrorAction SilentlyContinue) { Ok $bin }
    else { $faltando += $bin }
}
if ($faltando.Count -gt 0) {
    Aviso "faltando: $($faltando -join ', ')"
    Nota "Sem ele o Ciclo Assist não consegue VER nem OUVIR o material —"
    Nota "duas das três funções param. Instale com:"
    Nota "    winget install Gyan.FFmpeg"
    Nota "e feche e reabra esta janela depois."
    if (-not (Pergunta "Continuar mesmo assim?")) { Morre "instalação interrompida por você" }
}

if ($Conferir) {
    Titulo "Conferência terminada"
    Nota "Nada foi instalado. Para instalar de verdade, rode sem -Conferir."
    Write-Host ""
    Read-Host "   Pressione Enter para fechar"
    exit 0
}

# ── 4. O ambiente do aplicativo ──────────────────────────────────────────────
Titulo "4 de 6 — preparando o aplicativo"

# ⭐ FUNCIONA, não EXISTE: num disco que atravessa máquinas, o `python.exe` do outro
#    sistema está lá e está errado, sem levantar exceção nenhuma.
$venvOk = $false
if (Test-Path $PY) {
    & $PY -c "import sys" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $venvOk = $true } else { Remove-Item -Recurse -Force $VENV }
}
if (-not $venvOk) {
    Passo "criando o ambiente (a primeira vez demora)"
    if ($LANCADOR) { & py "-$LANCADOR" -m venv --copies $VENV } else { & python -m venv --copies $VENV }
    if (-not (Test-Path $PY)) { Morre "não consegui criar o ambiente em $VENV" }
}

Passo "instalando o que o aplicativo precisa"
# ⚠️ Sem `--upgrade pip`: falha no Windows (WinError 145 — o pip não substitui os
#    próprios arquivos enquanto roda) e deixa uma pasta `~ip-*.dist-info` que polui
#    toda chamada futura de pip.
# ⚠️⚠️ Pelo LOCK, com versões exatas. O requirements.txt é todo `>=`, e instalar por
#    ele faz a máquina do editor puxar a versão mais nova de cada pacote no dia da
#    instalação — duas instalações no mesmo mês podem não ser o mesmo produto.
$lock = Join-Path $RAIZ "requirements.lock"
$fonte = if (Test-Path $lock) { $lock } else { Join-Path $RAIZ "requirements.txt" }
& $PY -m pip install --quiet -r $fonte
if ($LASTEXITCODE -ne 0) { Morre "não consegui instalar as dependências do Python" }
Ok "ambiente pronto"

# ⛔ A Preparar e o Conformar têm venv própria; sem ela o app não sobe essas abas (fase 5, 2026-11-08).
Passo "preparando os módulos Preparar e Conformar (a primeira vez demora)"
& $PY (Join-Path $RAIZ "tools\preparar_modulos.py")
if ($LASTEXITCODE -ne 0) { Morre "não consegui preparar os módulos (o motivo está acima)" }
Ok "módulos prontos"

# ── 5. As integrações ────────────────────────────────────────────────────────
Titulo "5 de 6 — integrações com os editores"

# ⭐ Fase 4 do plano um app só (2026-11-07): NENHUM painel dentro dos editores — o Ciclo Assist é usado pela janela
#    dele. No Media Composer e no Resolve não há o que instalar (o app fala com eles por fora); no Premiere vai UMA
#    extensão invisível, a ponte. O instalador único também TIRA as integrações antigas (Órbita, De Lá Pra Cá, os
#    painéis de antes), movendo-as para uma pasta de cópia — nada é apagado. O mesmo da ⚙ › Integrações.
Passo "instalando a ponte do Premiere e tirando as integrações antigas"
& $PY (Join-Path $RAIZ "tools\integracoes.py") --fazer
# 2 = a ponte entrou, mas alguma integração antiga não saiu (o motivo foi impresso acima): aviso, não aborta.
if ($LASTEXITCODE -eq 2) { Aviso "a ponte foi instalada, mas alguma integração antiga ficou (veja acima)" }
elseif ($LASTEXITCODE -ne 0) { Morre "não consegui instalar as integrações" }
Nota "Se o Premiere estiver aberto, feche e abra: ele só carrega extensões ao começar."

# ── 6. Iniciar junto com o Windows ───────────────────────────────────────────
Titulo "6 de 6 — deixar o Ciclo Assist pronto"

# ⭐ Sem isto o editor liga a máquina e o serviço não está rodando — e é culpa nossa por não
#    ter subido. Um atalho na Inicialização resolve, é reversível, e não exige administrador.
$inicializacao = [Environment]::GetFolderPath("Startup")
$atalho = Join-Path $inicializacao "Ciclo Assist.lnk"
$iniciar = Join-Path $RAIZ "iniciar.vbs"

# Um .vbs de uma linha porque um atalho para .bat sempre pisca uma janela preta na
# tela a cada logon — e um serviço que assusta no primeiro dia não sobrevive ao segundo.
@"
' Sobe o servico do Ciclo Assist sem janela. Gerado por instalar.ps1.
CreateObject("WScript.Shell").Run """$PY"" -m cicloassist.servico", 0, False
"@ | Set-Content -Path $iniciar -Encoding Default
# ⛔ `Default` = a codepage ANSI, a que o Windows Script Host lê. `-Encoding UTF8` no PowerShell 5.1 grava BOM, e o
#    wscript abre o diálogo "Invalid character" (800A0408, linha 1, coluna 1) e o serviço não sobe (medido, 2026-11-08).

if (Pergunta "Iniciar o Ciclo Assist junto com o Windows?") {
    $ws = New-Object -ComObject WScript.Shell
    $lnk = $ws.CreateShortcut($atalho)
    $lnk.TargetPath = "wscript.exe"
    $lnk.Arguments = """$iniciar"""
    $lnk.WorkingDirectory = $RAIZ
    $lnk.Description = "Ciclo Assist"
    $lnk.Save()
    Ok "vai subir sozinho no próximo logon"
    Nota "Para desfazer: apague $atalho"
} else {
    Nota "Tudo bem. Para usar, rode dev.ps1 ou dê duplo clique em iniciar.vbs"
}

$jaRodando = Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue
if (-not $jaRodando) {
    Passo "iniciando agora"
    Start-Process "wscript.exe" -ArgumentList """$iniciar""" -WorkingDirectory $RAIZ
    Start-Sleep -Seconds 4
    $jaRodando = Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue
}
if ($jaRodando) { Ok "serviço no ar" } else { Aviso "o serviço não subiu; rode dev.ps1 para ver o erro" }

Write-Host ""
Write-Host "  +----------------------------------------------+" -ForegroundColor Green
Write-Host "  |   Pronto.                                    |" -ForegroundColor Green
Write-Host "  +----------------------------------------------+" -ForegroundColor Green
Write-Host ""
Write-Host "  Abra o Ciclo Assist: duplo clique em ABRIR-APP.bat" -ForegroundColor White
Write-Host ""
Nota "Nada aparece dentro do Media Composer nem do Premiere: tudo é pela janela do app."
Write-Host ""
Read-Host "  Pressione Enter para fechar"
