#!/bin/bash
# Abre a janela do Ciclo Assist no Mac (duplo clique no Finder) — o par do ABRIR-APP.bat do Windows.
# Compila antes, se o codigo mudou. A compilacao mora FORA do SSD (exFAT nao tem hard link: o cargo copiaria
# ~200 MB a cada build), em ~/Library/Caches/CicloAssist-build. O app sobe o servico sozinho e o encerra ao fechar.

RAIZ="$(cd "$(dirname "$0")" && pwd)"
export PATH="/opt/homebrew/bin:$HOME/.cargo/bin:/usr/local/bin:$PATH"   # o Finder nao passa o PATH do terminal
export CARGO_TARGET_DIR="${CARGO_TARGET_DIR:-$HOME/Library/Caches/CicloAssist-build/target}"
mkdir -p "$CARGO_TARGET_DIR"
EXE="$CARGO_TARGET_DIR/debug/cicloassist"

falhou() { echo; echo "⛔ $1"; echo; read -n 1 -s -r -p "Aperte uma tecla para fechar esta janela."; exit 1; }

# a janela que estiver aberta fecha antes (e leva o servico junto)
pkill -f "^$EXE" 2>/dev/null

if command -v cargo >/dev/null 2>&1; then
    echo "Preparando o Ciclo Assist (na primeira vez depois de uma atualizacao leva alguns minutos)..."
    cargo build --manifest-path "$RAIZ/app/src-tauri/Cargo.toml" || falhou "a compilacao falhou (o erro esta acima)."
elif [ ! -x "$EXE" ]; then
    falhou "o Rust nao esta instalado (https://rustup.rs) e o app ainda nao foi compilado nesta maquina."
else
    echo "Rust nao encontrado: abrindo a ultima versao compilada."
fi

# o servico do app que acabou de fechar leva alguns segundos para sair; abrir antes disso faz o app novo usar o
# servico velho e ficar sem servico quando ele termina (medido no Windows, 2026-10-22)
for i in $(seq 1 30); do
    lsof -nP -iTCP:7824 -sTCP:LISTEN >/dev/null 2>&1 || break
    sleep 0.5
done

nohup "$EXE" >/dev/null 2>&1 &
disown
echo "Ciclo Assist aberto. Esta janela pode ser fechada."
exit 0
