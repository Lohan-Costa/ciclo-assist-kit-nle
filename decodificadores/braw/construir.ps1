# Constrói o `ciclo-decodificar-braw.exe` — o único jeito de o produto ver um quadro BRAW.
#
# Pré-requisitos NA MÁQUINA DE QUEM CONSTRÓI (não na de quem usa):
#   - Blackmagic RAW SDK instalado (o `.idl`, o dispatch e as libs vêm dele);
#   - Visual Studio Build Tools 2022 (cl.exe) e o Windows SDK (midl.exe).
#
# ⛔⛔ **O SDK é preciso no BUILD; o usuário só precisa do RUNTIME.** É a distinção que
# separa este helper de um binding: nada do fabricante entra no nosso pacote, e o
# `.dll` que o binário carrega é o que já está na máquina do editor (ver o `.cpp`).
#
# ⚠️ **O header não existe: ele é GERADO.** No Windows o SDK entrega `BlackmagicRawAPI.idl`,
# e quem produz o `.h` e o `_i.c` é o MIDL. Foi a primeira coisa a surpreender neste porte
# — no macOS o header vem pronto.
#
# Uso:  .\decodificadores\braw\construir.ps1  [-Sdk <pasta Win do SDK>]

param(
    [string]$Sdk = "",
    [string]$Saida = ""
)

$ErrorActionPreference = "Stop"
$aqui = Split-Path -Parent $MyInvocation.MyCommand.Path
$raiz = Split-Path -Parent (Split-Path -Parent $aqui)
if (-not $Saida) { $Saida = Join-Path $raiz "decodificadores\bin" }

# ── o SDK ────────────────────────────────────────────────────────────────────
if (-not $Sdk) {
    $candidatos = @(
        "C:\Program Files (x86)\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK\Win",
        "C:\Program Files\Blackmagic Design\Blackmagic RAW\Blackmagic RAW SDK\Win"
    )
    $Sdk = $candidatos | Where-Object { Test-Path (Join-Path $_ "Include\BlackmagicRawAPI.idl") } | Select-Object -First 1
}
if (-not $Sdk -or -not (Test-Path (Join-Path $Sdk "Include\BlackmagicRawAPI.idl"))) {
    Write-Error @"
Não achei o Blackmagic RAW SDK. Baixe em
  https://www.blackmagicdesign.com/support/family/blackmagic-raw
e rode de novo (ou passe -Sdk "<pasta>\Blackmagic RAW SDK\Win").
"@
}
Write-Host "SDK: $Sdk"

# ── o compilador ─────────────────────────────────────────────────────────────
$vcvars = Get-ChildItem "C:\Program Files*\Microsoft Visual Studio\2022\*\VC\Auxiliary\Build\vcvars64.bat" `
    -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $vcvars) {
    Write-Error @"
Não achei o vcvars64.bat do Visual Studio 2022. Instale os Build Tools
(workload "Desktop development with C++", que traz cl.exe e o Windows SDK).
"@
}
Write-Host "cl.exe: $($vcvars.FullName)"

$gerado = Join-Path $aqui "gerado"
New-Item -ItemType Directory -Force $gerado | Out-Null
New-Item -ItemType Directory -Force $Saida  | Out-Null

$terceiros = Join-Path $raiz "decodificadores\terceiros"
$comum     = Join-Path $raiz "decodificadores"
$exe       = Join-Path $Saida "ciclo-decodificar-braw.exe"

# ⚠️ Tudo num `cmd` só: o vcvars monta o ambiente (PATH, INCLUDE, LIB) e ele NÃO sobrevive
#    entre chamadas. O MIDL precisa do cl.exe no PATH — foi o primeiro erro deste build
#    ("MIDL1005: cannot find C preprocessor cl.exe").
$lote = @"
@echo off
call "$($vcvars.FullName)" >nul
if errorlevel 1 exit /b 1
echo [1/2] MIDL: gerando o header a partir do .idl
midl /nologo /W1 /char signed /env x64 /out "$gerado" ^
     /h BlackmagicRawAPI.h /iid BlackmagicRawAPI_i.c ^
     "$Sdk\Include\BlackmagicRawAPI.idl"
if errorlevel 1 exit /b 1
echo [2/2] cl: compilando o decodificador
cl /nologo /std:c++17 /EHsc /O2 /MT /W3 ^
   /I "$gerado" /I "$Sdk\Include" /I "$comum" /I "$terceiros" ^
   "$aqui\decodificar_braw.cpp" "$Sdk\Include\BlackmagicRawAPIDispatch.cpp" "$gerado\BlackmagicRawAPI_i.c" ^
   /Fe:"$exe" /Fo:"$gerado\\" ^
   /link ole32.lib oleaut32.lib
if errorlevel 1 exit /b 1
"@
$bat = Join-Path $gerado "construir.bat"
Set-Content -Path $bat -Value $lote -Encoding ASCII
& cmd /c "`"$bat`""
if ($LASTEXITCODE -ne 0) { Write-Error "a construção falhou (código $LASTEXITCODE)" }

Write-Host ""
Write-Host "pronto: $exe"
Write-Host "confira com:  python tools\conferir_braw.py <arquivo.braw>"
