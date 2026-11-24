# =============================================================================
# De Lá Pra Cá — modo desenvolvedor (WINDOWS)
#
# Uso:   .\dev.ps1                 sobe o serviço
#        .\dev.ps1 -Limpo          recria o venv do zero
#
# Se o PowerShell recusar o script ("execução de scripts desabilitada"):
#   powershell -ExecutionPolicy Bypass -File .\dev.ps1
#
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ ESTE ARQUIVO PRECISA ESTAR EM UTF-8 **COM BOM**. NÃO REMOVA O BOM.
#
# O Windows PowerShell 5.1 lê um `.ps1` sem BOM como **ANSI (cp1252)**, não como
# UTF-8. Então um traço longo (—, `E2 80 94` em UTF-8) chega ao parser como `â€"`,
# e o `0x94` do cp1252 é `”` — que o PowerShell aceita como **aspas de fechamento**.
# Resultado: a string termina onde não devia, o resto da linha vira código, e o
# script morre com `Missing closing '}'` apontando para uma chave que está lá.
#
# ⭐ A mensagem acusa o lugar ERRADO: o erro aparece dezenas de linhas depois do
# acento que o causou. Aconteceu neste arquivo, medido em 2026-08-15. Se você editar
# este script com uma ferramenta que grave UTF-8 sem BOM, regrave com BOM:
#
#   $t = [IO.File]::ReadAllText($p, [Text.UTF8Encoding]::new($false))
#   [IO.File]::WriteAllText($p, $t, [Text.UTF8Encoding]::new($true))
#
# E confira antes de confiar:
#   [System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$null, [ref]$e)
# ─────────────────────────────────────────────────────────────────────────────
#
# ─────────────────────────────────────────────────────────────────────────────
# ⭐ AS TRÊS DECISÕES DESTE ARQUIVO QUE NÃO SÃO ÓBVIAS
#
# 1. O venv do Windows é `.venv-win`, SEPARADO do `.venv` do macOS.
#    O disco é compartilhado entre as duas máquinas, e a tentação é usar um venv só —
#    `Scripts/`+`Lib/` do Windows conviveriam com `bin/`+`lib/` do macOS. **Não
#    convivem: medido nesta máquina, `Test-Path .venv\Lib` e `.venv\lib` respondem
#    ambos `True`** — o Windows é insensível à caixa mesmo em exFAT, então `Lib` E
#    `lib` são a MESMA pasta, e um venv seria escrito dentro do outro. Além disso o
#    `pyvenv.cfg` é um só e aponta para o interpretador de quem rodou `venv` por
#    último; o `Scripts\python.exe` continuaria no disco e falharia com
#    `No Python at '/opt/homebrew/...\python.exe'`.
#
# 2. Checa se o venv FUNCIONA, não se ele EXISTE.
#    Num disco que atravessa sistemas operacionais, o artefato do outro SO está lá e
#    está errado — e nada levanta exceção. A checagem certa é EXECUTAR o interpretador.
#
# 3. NÃO roda `pip install --upgrade pip`.
#    Medido: falha no Windows (`WinError 145` — o pip não substitui os próprios
#    arquivos enquanto roda) e deixa uma pasta `~ip-*.dist-info` que faz TODA chamada
#    futura de pip imprimir `WARNING: Ignoring invalid distribution ~ip`. Não é
#    necessário para instalar as dependências do projeto.
# =============================================================================

param(
    [switch]$Limpo
)

# ⚠️ **`Stop` NÃO serve aqui, e a razão é do PowerShell 5.1, não deste script.**
#
# Com `$ErrorActionPreference = "Stop"`, qualquer linha que um EXECUTÁVEL escreva em
# stderr vira um `NativeCommandError` TERMINANTE — mesmo com código de saída 0, e mesmo
# quando escrever ali é o comportamento correto do programa. Medido: `py -3.13` numa
# máquina sem o 3.13 imprime "No suitable Python runtime found" em stderr, e o script
# inteiro morria **na sondagem que existe justamente para descobrir isso**.
#
# Então a verificação de erro aqui é EXPLÍCITA: todo comando externo que importa é
# seguido de um teste de `$LASTEXITCODE` (ou do artefato que ele devia produzir), e
# `Morre` encerra. É mais verboso e é o que funciona.
$ErrorActionPreference = "Continue"

# Este projeto fala português no log e nos caminhos. Nesta máquina o console já estava
# em UTF-8 (`chcp` = 65001) e a saída sai correta — mas isso é configuração de máquina,
# não garantia. Fixar as duas pontas custa duas linhas e evita a confusão clássica de
# `DiretÃ³rio` na tela, que faz procurar bug de codificação onde não há.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"   # o serviço Python herda: stdout e I/O de texto em UTF-8

function Info($m) { Write-Host "> $m"        -ForegroundColor Cyan }
function Ok($m)   { Write-Host "OK $m"       -ForegroundColor Green }
function Aviso($m){ Write-Host "!  $m"       -ForegroundColor Yellow }
function Nota($m) { Write-Host "   $m"       -ForegroundColor DarkGray }
function Morre($m){ Write-Host "X  ERRO: $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "+--------------------------------------+"
Write-Host "|      De La Pra Ca - Dev Mode         |"
Write-Host "|      Media Composer (Windows)        |"
Write-Host "+--------------------------------------+"
Write-Host ""

$RAIZ = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RAIZ
Info "Diretório: $RAIZ"

$VENV   = Join-Path $RAIZ ".venv-win"
$PY     = Join-Path $VENV "Scripts\python.exe"
$PORTA  = 7823

# ── 1. Python 3.12+ ──────────────────────────────────────────────────────────
$LANCADOR = $null
foreach ($v in @("3.12", "3.13")) {
    # ⭐ Sondar EXECUTANDO, não perguntando se existe: um `python.exe` no disco pode
    #    apontar para o interpretador da outra máquina (ver nota 2 no cabeçalho).
    $null = (& py "-$v" -c "import sys" 2>&1)
    if ($LASTEXITCODE -eq 0) { $LANCADOR = $v; break }
}
if (-not $LANCADOR) {
    # Sem o launcher `py`, tenta o `python` do PATH — mas confere a VERSÃO.
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { Morre "Python 3.12+ não encontrado. Instale de python.org (marque 'Add to PATH')." }
    $v = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ([version]$v -lt [version]"3.12") { Morre "Python $v é antigo demais — preciso de 3.12+ (o numpy do requirements.lock não instala no 3.11)." }
    $LANCADOR = $null
    Ok "Python $v (do PATH)"
} else {
    Ok "Python $LANCADOR (via launcher py)"
}

# ── 2. ffmpeg ────────────────────────────────────────────────────────────────
$ff = Get-Command ffmpeg -ErrorAction SilentlyContinue
if ($ff) {
    Ok "ffmpeg ($($ff.Source))"
} else {
    Aviso "ffmpeg não está no PATH."
    Nota "O relink não precisa dele hoje (o matcher não abre mídia), mas os"
    Nota "writers de saída precisam.  winget install Gyan.FFmpeg"
}

# ── 3. venv ──────────────────────────────────────────────────────────────────
if ($Limpo -and (Test-Path $VENV)) {
    Info "Removendo o venv antigo..."
    Remove-Item -Recurse -Force $VENV
}

# ⭐ FUNCIONA, não EXISTE: o `python.exe` pode estar no disco e apontar para o
#    interpretador da outra máquina. Só executá-lo responde.
$venvOk = $false
if (Test-Path $PY) {
    # ⚠️ E tem de ser 3.12+ (revisão de código 2026-10-01): um .venv-win 3.11 de antes seguia em uso, com o
    #    numpy velho, porque só a CRIAÇÃO exigia a versão.
    & $PY -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $venvOk = $true }
    else { Aviso "o .venv-win existe mas não executa ou não é 3.12+ — recriando"; Remove-Item -Recurse -Force $VENV }
}

$venvNovo = $false
if (-not $venvOk) {
    Info "Criando o venv do Windows (.venv-win)..."
    if ($LANCADOR) { & py "-$LANCADOR" -m venv --copies $VENV }
    else           { & python -m venv --copies $VENV }
    if (-not (Test-Path $PY)) { Morre "não consegui criar o venv em $VENV" }
    $venvNovo = $true
    Ok "venv criado"
}

# Reinstala quando o venv é novo ou quando o requirements mudou depois dele.
$CARIMBO = Join-Path $VENV ".deps-instaladas"
$precisa = $venvNovo -or (-not (Test-Path $CARIMBO))
if (-not $precisa) {
    $req = Get-Item (Join-Path $RAIZ "requirements.lock")
    $car = Get-Item $CARIMBO
    if ($req.LastWriteTime -gt $car.LastWriteTime) { $precisa = $true }
}
if ($precisa) {
    Info "Instalando dependências Python..."
    # ⚠️ Sem `--upgrade pip` — ver a nota 3 no cabeçalho.
    # ⚠️⚠️ Instala pelo LOCK, não pelo requirements.txt: este último é todo `>=`, e
    # instalar por ele deixa a estação do editor puxar silenciosamente a versão mais
    # nova de cada pacote. Regerar o lock: `python tools/lock.py`.
    & $PY -m pip install --quiet -r (Join-Path $RAIZ "requirements.lock")
    if ($LASTEXITCODE -ne 0) { Morre "pip falhou" }
    New-Item -ItemType File -Path $CARIMBO -Force | Out-Null
    Ok "Dependências OK"
} else {
    Ok "Dependências já instaladas"
}

# ── 4. Sem painel no MC (fase 4 do plano um app só, 2026-11-07): o De Lá Pra Cá é o módulo Conformar do Ciclo
#    Assist, que o mostra na janela dele; o `.avpi` e as ferramentas dele (`pack`, `reload`) saíram.

# ── 5. A porta ───────────────────────────────────────────────────────────────
$ocupada = Get-NetTCPConnection -LocalPort $PORTA -State Listen -ErrorAction SilentlyContinue
if ($ocupada) {
    $pidDono = ($ocupada | Select-Object -First 1).OwningProcess
    Aviso "A porta $PORTA já está ocupada (pid $pidDono) — outra instância do serviço?"
    $r = Read-Host "  Encerrar aquele processo e continuar? [s/N]"
    if ($r -match '^[sSyY]') {
        Stop-Process -Id $pidDono -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Ok "Encerrado"
    } else {
        Morre "porta ocupada — encerre o outro serviço e tente de novo"
    }
}

# ── 6. O Media Composer ──────────────────────────────────────────────────────
$mc = Get-Process -Name "AvidMediaComposer" -ErrorAction SilentlyContinue
if ($mc) {
    Ok "Media Composer está aberto"
} else {
    Aviso "Media Composer fechado — o painel vai abrir, mas sem nada para dirigir."
}

# ── 7. Subir ─────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "Tudo pronto. Subindo o serviço..." -ForegroundColor Green
Write-Host "  painel:  http://127.0.0.1:$PORTA/painel" -ForegroundColor Cyan
Write-Host "  (Ctrl+C para encerrar)" -ForegroundColor DarkGray
Write-Host ""

# ⚠️ O separador de PYTHONPATH é `;` no Windows e `:` no POSIX. Cravar `:` aqui faz
#    o interpretador enxergar UM caminho inexistente em vez de dois válidos — e o erro
#    que aparece é `ModuleNotFoundError: api`, que manda procurar no lugar errado.
$env:PYTHONPATH = "$RAIZ\motor;$RAIZ\plugins\media-composer\servico"
if (-not $env:DLPC_LOG) { $env:DLPC_LOG = "info" }
& $PY (Join-Path $RAIZ "plugins\media-composer\servico\main.py") --bancada --log $env:DLPC_LOG
