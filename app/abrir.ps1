# Compila (se mudou) e abre a janela do Ciclo Assist.
#
#   powershell -ExecutionPolicy Bypass -File app\abrir.ps1      (ou duplo clique em ABRIR-APP.bat)
#
# A compilacao mora FORA do SSD (exFAT nao tem hard link: o cargo copiaria ~200 MB a cada build) -
# o mesmo arranjo do De La Pra Ca. O app sobe o servico sozinho e o encerra ao fechar.

$ErrorActionPreference = "Stop"
$RAIZ = Split-Path -Parent $PSScriptRoot
if (-not $env:CARGO_TARGET_DIR) { $env:CARGO_TARGET_DIR = Join-Path $env:LOCALAPPDATA "CicloAssist-build\target" }
New-Item -ItemType Directory -Force -Path $env:CARGO_TARGET_DIR | Out-Null
$EXE = Join-Path $env:CARGO_TARGET_DIR "debug\cicloassist.exe"

# O Windows TRAVA o .exe que esta rodando: o build falharia com "Access is denied".
Get-Process cicloassist -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $EXE } | Stop-Process -Force

if (-not (Get-Command cargo -ErrorAction SilentlyContinue)) { throw "cargo nao encontrado (instale o Rust: https://rustup.rs)" }
# O cargo escreve o progresso em stderr; com $ErrorActionPreference=Stop isso viraria erro.
$ErrorActionPreference = "Continue"
& cargo build --manifest-path (Join-Path $RAIZ "app\src-tauri\Cargo.toml") 2>&1 | ForEach-Object { "$_" }
if ($LASTEXITCODE -ne 0) { throw "a compilacao falhou (codigo $LASTEXITCODE)" }
# O servico do app que acabou de morrer leva alguns segundos para sair. Abrir antes disso faz o app
# novo ver a 7824 ainda atendendo, usar o servico velho como se fosse dele, e ficar sem servico
# quando o velho termina de sair (medido em 2026-10-22). Espera a porta ESCUTAR de ninguem.
for ($i = 0; $i -lt 30; $i++) {
    if (-not (Get-NetTCPConnection -LocalPort 7824 -State Listen -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Milliseconds 500
}
Start-Process $EXE
