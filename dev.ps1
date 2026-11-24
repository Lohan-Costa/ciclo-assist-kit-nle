# =============================================================================
# Ciclo Assist — modo desenvolvedor (WINDOWS)
#
# Uso:   .\dev.ps1                 sobe o serviço
#        .\dev.ps1 -Limpo          recria o venv do zero
#        .\dev.ps1 -Verboso        log em nível debug
#
# Se o PowerShell recusar o script ("execução de scripts desabilitada"):
#   powershell -ExecutionPolicy Bypass -File .\dev.ps1
#
# ⚠️ Rode de um terminal JÁ ABERTO. Um duplo-clique executa e fecha a janela ao
#    terminar (ou ao falhar), levando a mensagem junto.
#
# ─────────────────────────────────────────────────────────────────────────────
# ⚠️⚠️ ESTE ARQUIVO PRECISA ESTAR EM UTF-8 **COM BOM**. NÃO REMOVA O BOM.
#
# O Windows PowerShell 5.1 lê um `.ps1` sem BOM como **ANSI (cp1252)**, não como
# UTF-8. Um traço longo (—, `E2 80 94` em UTF-8) chega ao parser como `â€"`, e o
# `0x94` do cp1252 é `”` — que o PowerShell aceita como **aspas de fechamento**.
# A string termina onde não devia, o resto da linha vira código, e o script morre
# com `Missing closing '}'` apontando para uma chave que está lá.
#
# ⭐ A mensagem acusa o lugar ERRADO: o erro aparece dezenas de linhas depois do
# acento que o causou. Medido no De Lá Pra Cá em 2026-08-15. Se editar com uma
# ferramenta que grave UTF-8 sem BOM, regrave com BOM:
#
#   $t = [IO.File]::ReadAllText($p, [Text.UTF8Encoding]::new($false))
#   [IO.File]::WriteAllText($p, $t, [Text.UTF8Encoding]::new($true))
#
# E confira antes de confiar:
#   [System.Management.Automation.Language.Parser]::ParseFile($p, [ref]$null, [ref]$e)
# ─────────────────────────────────────────────────────────────────────────────
#
# ─────────────────────────────────────────────────────────────────────────────
# ⭐ O QUE ESTE APP EXIGE E OS OUTROS NÃO
#
# 1. O `claude` CLI é o MOTOR, não um extra. Sem ele o painel abre, conversa e
#    não responde nada. É a inversão que define o produto: não somos cliente de
#    IA nenhuma — o Claude é que chama as nossas ferramentas.
#
# 2. `ffmpeg` é OBRIGATÓRIO, não opcional. Sem ele o `ver_frames` e o
#    `transcrever` não funcionam, que são duas das três funções do produto.
#
# 3. Os stubs do protobuf são GERADOS do `bancodedadosnles` (subindo de pasta). Eles estão
#    versionados para um clone rodar sem o banco ao lado, mas se sumirem, o
#    `cicloassist.avid.mcapi` nem importa — e o erro fala de protobuf, não de
#    banco de dados.
# =============================================================================

param(
    [switch]$Limpo,
    [switch]$Verboso
)

# ⚠️ **`Stop` NÃO serve aqui, e a razão é do PowerShell 5.1, não deste script.**
#
# Com `$ErrorActionPreference = "Stop"`, qualquer linha que um EXECUTÁVEL escreva em
# stderr vira um `NativeCommandError` TERMINANTE — mesmo com código de saída 0, e mesmo
# quando escrever ali é o comportamento correto do programa. Medido no De Lá Pra Cá:
# `py -3.13` numa máquina sem o 3.13 imprime em stderr, e o script morria **na sondagem
# que existe justamente para descobrir isso**.
#
# Então a verificação é EXPLÍCITA: todo comando externo que importa é seguido de um teste
# de `$LASTEXITCODE` (ou do artefato que ele devia produzir), e `Morre` encerra.
$ErrorActionPreference = "Continue"

# Este projeto fala português no log e nos caminhos. Fixar as duas pontas custa duas
# linhas e evita a confusão clássica de `DiretÃ³rio` na tela, que faz procurar bug de
# codificação onde não há.
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONUTF8 = "1"   # o serviço herda: stdout e I/O de texto em UTF-8

function Info($m) { Write-Host "> $m"        -ForegroundColor Cyan }
function Ok($m)   { Write-Host "OK $m"       -ForegroundColor Green }
function Aviso($m){ Write-Host "!  $m"       -ForegroundColor Yellow }
function Nota($m) { Write-Host "   $m"       -ForegroundColor DarkGray }
function Morre($m){ Write-Host "X  ERRO: $m" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "+--------------------------------------+"
Write-Host "|       Ciclo Assist - Dev Mode        |"
Write-Host "|       Media Composer (Windows)       |"
Write-Host "+--------------------------------------+"
Write-Host ""

$RAIZ = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $RAIZ
Info "Diretório: $RAIZ"

$VENV  = Join-Path $RAIZ ".venv-win"
$PY    = Join-Path $VENV "Scripts\python.exe"
$PORTA = 7824

# ── 1. Python 3.11+ ──────────────────────────────────────────────────────────
$LANCADOR = $null
foreach ($v in @("3.13", "3.12", "3.11")) {
    # ⭐ Sondar EXECUTANDO, não perguntando se existe.
    $null = (& py "-$v" -c "import sys" 2>&1)
    if ($LASTEXITCODE -eq 0) { $LANCADOR = $v; break }
}
if (-not $LANCADOR) {
    $cmd = Get-Command python -ErrorAction SilentlyContinue
    if (-not $cmd) { Morre "Python 3.11+ não encontrado. Instale de python.org (marque 'Add to PATH')." }
    $v = & python -c "import sys; print('%d.%d' % sys.version_info[:2])"
    if ([version]$v -lt [version]"3.11") { Morre "Python $v é antigo demais — preciso de 3.11+." }
    Ok "Python $v (do PATH)"
} else {
    Ok "Python $LANCADOR (via launcher py)"
}

# ── 2. O motor: o Claude Code ────────────────────────────────────────────────
# ⭐ Este é o pré-requisito que nenhum outro app da casa tem. Sem ele o painel sobe,
#    o editor pergunta, e nada responde — com um erro que só aparece no meio do turno.
$claude = Get-Command claude -ErrorAction SilentlyContinue
if ($claude) {
    $vc = (& claude --version 2>&1 | Select-Object -First 1)
    Ok "claude $vc"
} else {
    Aviso "O Claude Code NÃO está no PATH — o serviço sobe, mas não responde nada."
    Nota "Ele é o motor do produto: instale e faça login uma vez."
    Nota "https://claude.com/claude-code"
}

# ── 3. ffmpeg e ffprobe ──────────────────────────────────────────────────────
foreach ($bin in @("ffmpeg", "ffprobe")) {
    $c = Get-Command $bin -ErrorAction SilentlyContinue
    if ($c) {
        Ok "$bin ($($c.Source))"
    } else {
        Aviso "$bin não está no PATH."
        Nota "Sem ele, ver_frames e transcrever não funcionam."
        Nota "winget install Gyan.FFmpeg"
    }
}

# ── 4. venv ──────────────────────────────────────────────────────────────────
if ($Limpo -and (Test-Path $VENV)) {
    Info "Removendo o venv antigo..."
    Remove-Item -Recurse -Force $VENV
}

# ⭐ FUNCIONA, não EXISTE: o disco é compartilhado entre máquinas, e o `python.exe`
#    pode estar lá apontando para o interpretador da outra. Só executá-lo responde.
$venvOk = $false
if (Test-Path $PY) {
    & $PY -c "import sys" 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { $venvOk = $true }
    else { Aviso "o .venv-win existe mas não executa — recriando"; Remove-Item -Recurse -Force $VENV }
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

# ── 5. dependências ──────────────────────────────────────────────────────────
$REQ     = Join-Path $RAIZ "requirements.txt"
$LOCK    = Join-Path $RAIZ "requirements.lock"
$CARIMBO = Join-Path $VENV ".deps-instaladas"
$precisa = $venvNovo -or (-not (Test-Path $CARIMBO))
if (-not $precisa) {
    $fonte = if (Test-Path $LOCK) { $LOCK } else { $REQ }
    if ((Get-Item $fonte).LastWriteTime -gt (Get-Item $CARIMBO).LastWriteTime) { $precisa = $true }
}
if ($precisa) {
    Info "Instalando dependências Python..."
    Nota "A primeira vez baixa bastante (grpcio, ctranslate2, onnxruntime)."
    # ⚠️ Sem `pip install --upgrade pip`: medido no De Lá Pra Cá, falha no Windows
    #    (`WinError 145` — o pip não substitui os próprios arquivos enquanto roda) e
    #    deixa uma pasta `~ip-*.dist-info` que faz TODA chamada futura de pip imprimir
    #    `WARNING: Ignoring invalid distribution ~ip`.
    # ⚠️⚠️ Instala pelo LOCK, não pelo requirements.txt: este último é todo `>=`, e
    #    instalar por ele deixa a estação do editor puxar silenciosamente a versão mais
    #    nova de cada pacote no dia da instalação. Regerar: python tools\lock.py
    if (Test-Path $LOCK) { & $PY -m pip install --quiet -r $LOCK }
    else {
        Aviso "sem requirements.lock — instalando com versões soltas"
        & $PY -m pip install --quiet -r $REQ
    }
    if ($LASTEXITCODE -ne 0) { Morre "pip falhou" }
    New-Item -ItemType File -Path $CARIMBO -Force | Out-Null
    Ok "Dependências OK"
} else {
    Ok "Dependências já instaladas"
}

# ── 5b. As venvs dos módulos ─────────────────────────────────────────────────
# ⛔ A Preparar e o Conformar têm venv própria; sem ela o app não sobe essas abas (fase 5, 2026-11-08).
$prepararModulos = Join-Path $RAIZ "tools\preparar_modulos.py"
if ($Limpo) { & $PY $prepararModulos --limpo } else { & $PY $prepararModulos }
if ($LASTEXITCODE -ne 0) { Morre "não consegui preparar os módulos (o motivo está acima)" }
Ok "Módulos prontos"

# ── 6. Os stubs do protobuf ──────────────────────────────────────────────────
# ⚠️ Sem eles o `cicloassist.avid.mcapi` nem importa, e a mensagem fala de protobuf.
& $PY -c "from cicloassist.avid.proto import mcapi_tipos_pb2" 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Aviso "Os stubs do mcapi não estão gerados."
    # O banco mora na raiz da pasta da familia; o app pode estar 1 ou 2 niveis abaixo
    # (2 ATIVOS\, 9 ARQUIVADOS\...). Sobe de pasta ate achar.
    $banco = $null
    $d = Split-Path -Parent $RAIZ
    while ($d) {
        $c = Join-Path $d "bancodedadosnles"
        if (Test-Path $c) { $banco = $c; break }
        $d = Split-Path -Parent $d
    }
    if (-not $banco) {
        Morre "preciso do bancodedadosnles (procurei subindo a partir de $RAIZ) para gerar os stubs"
    }
    Info "Gerando a partir do banco..."
    & $PY (Join-Path $RAIZ "tools\gerar_stubs.py")
    if ($LASTEXITCODE -ne 0) { Morre "gerar_stubs.py falhou" }
    Ok "Stubs gerados"
} else {
    Ok "Stubs do mcapi OK"
}

# ── 7. O modelo de transcrição ───────────────────────────────────────────────
# Não bloqueia nada; só avisa, porque o primeiro `transcrever` parece travamento.
$hf = Join-Path $env:USERPROFILE ".cache\huggingface\hub"
$temModelo = (Test-Path $hf) -and (Get-ChildItem $hf -Directory -Filter "*faster-whisper*" -ErrorAction SilentlyContinue)
if ($temModelo) { Ok "Modelo de transcrição em cache" }
else {
    Aviso "O modelo do faster-whisper ainda não foi baixado (~244 MB)."
    Nota "Baixa sozinho na primeira transcrição, e essa demora bem mais."
}

# ── 8. Sem painel no MC (fase 4 do plano um app só, 2026-11-07): o Ciclo Assist é usado pela janela dele; o `.avpi`
#    e o `empacotar_avpi.py` saíram. Integrações: ⚙ › Integrações, ou `python tools\integracoes.py --fazer`.

# ── 9. A porta ───────────────────────────────────────────────────────────────
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

# ── 10. O Media Composer e o gateway ─────────────────────────────────────────
$mc = Get-Process -Name "AvidMediaComposer" -ErrorAction SilentlyContinue
if ($mc) { Ok "Media Composer está aberto" }
else     { Aviso "Media Composer fechado — o serviço sobe, mas sem nada para dirigir." }

# ── 11. Subir ────────────────────────────────────────────────────────────────
if ($Verboso) { $env:CICLOASSIST_LOG = "debug" }
if (-not $env:CICLOASSIST_LOG) { $env:CICLOASSIST_LOG = "info" }

Write-Host ""
Write-Host "Tudo pronto. Subindo o serviço..." -ForegroundColor Green
Write-Host "  painel:  http://127.0.0.1:$PORTA/painel" -ForegroundColor Cyan
Write-Host "  app:     ABRIR-APP.bat (a janela do Ciclo Assist)" -ForegroundColor Cyan
Write-Host "  (Ctrl+C para encerrar)" -ForegroundColor DarkGray
Write-Host ""

# `-m` a partir da raiz: o pacote está aqui, então não há PYTHONPATH a montar — e
# assim se evita a armadilha do separador (`;` no Windows, `:` no POSIX), que faz o
# interpretador enxergar UM caminho inexistente em vez de dois válidos.
& $PY -m cicloassist.servico
