#!/usr/bin/env bash
# =============================================================================
# De Lá Pra Cá — modo desenvolvedor (macOS)
#
# Uso:   ./dev.sh                 sobe o serviço
#        ./dev.sh --limpo         recria o venv do zero
#
# O gêmeo deste arquivo no Windows é `dev.ps1` (mesmo roteiro, shell idiomático).
# O venv de lá é `.venv-win`, SEPARADO: no Windows `.venv/Lib` e `.venv/lib` são a
# mesma pasta, e um venv seria escrito dentro do outro (ver ADR 0011).
#
# Se der "Permission denied" — o bit de execução não sobreviveu a uma cópia
# entre volumes — use `bash dev.sh`, ou devolva o bit com `chmod +x dev.sh`.
# =============================================================================

set -e

# ── Cores ──────────────────────────────────────────────────────────────────
RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'
CYAN='\033[0;36m'; DIM='\033[2m'; BOLD='\033[1m'; RESET='\033[0m'

info()  { echo -e "${CYAN}▸ $*${RESET}"; }
ok()    { echo -e "${GREEN}✓ $*${RESET}"; }
warn()  { echo -e "${YELLOW}⚠ $*${RESET}"; }
nota()  { echo -e "${DIM}  $*${RESET}"; }
die()   { echo -e "${RED}✗ ERRO: $*${RESET}"; exit 1; }

echo -e "${BOLD}"
echo "╔══════════════════════════════════════╗"
echo "║      De Lá Pra Cá — Dev Mode         ║"
echo "║      Media Composer                  ║"
echo "╚══════════════════════════════════════╝"
echo -e "${RESET}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
info "Diretório: $SCRIPT_DIR"

LIMPO=0
for arg in "$@"; do
    case "$arg" in
        --limpo) LIMPO=1 ;;
        -h|--help) sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) die "opção desconhecida: $arg  (use --limpo ou --help)" ;;
    esac
done

# ── 1. Python 3.12+ ────────────────────────────────────────────────────────
PYTHON=""
# ⚠️ 3.12+: o requirements.lock fixa numpy 2.5.2 / scipy 1.18.0, que não instalam no 3.11
# (medido 2026-10-01: o venv do Mac era 3.11 e ficou com o numpy velho, sem erro visível).
# O 3.12 vem primeiro porque é a versão do Windows, onde o lock é gerado.
for cmd in python3.12 python3.13 python3 python; do
    if command -v "$cmd" &>/dev/null; then
        VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || echo "0.0")
        MAJOR=${VER%%.*}; MINOR=${VER##*.}
        if [ "$MAJOR" -ge 3 ] && [ "$MINOR" -ge 12 ]; then
            PYTHON="$cmd"; ok "Python $VER ($cmd)"; break
        fi
    fi
done
[ -z "$PYTHON" ] && die "Python 3.12+ não encontrado.  brew install python@3.12"

# ── 2. ffmpeg ──────────────────────────────────────────────────────────────
if command -v ffmpeg &>/dev/null; then
    ok "ffmpeg $(ffmpeg -version 2>&1 | head -1 | awk '{print $3}')"
else
    warn "ffmpeg não está no PATH."
    nota "O relink não precisa dele hoje (o matcher não abre mídia), mas os"
    nota "writers de saída precisam.  brew install ffmpeg"
fi

# ── 3. venv ────────────────────────────────────────────────────────────────
# ⚠️ `--copies`: o volume é ExFAT e não tem symlinks. Sem isso o venv nasce
#    quebrado, e o erro que aparece depois não fala de symlink nenhum.
VENV=".venv"
if [ "$LIMPO" = "1" ] && [ -d "$VENV" ]; then
    info "Removendo o venv antigo…"; rm -rf "$VENV"
fi
# ⚠️ O venv que JÁ EXISTE também tem de ser 3.12+ (revisão de código 2026-10-01): exigir 3.12 só na
#    criação deixava o .venv 3.11 de antes em uso, com o numpy velho — o defeito medido continuava.
if [ -d "$VENV" ] && ! "$VENV/bin/python" -c "import sys; sys.exit(0 if sys.version_info >= (3, 12) else 1)" 2>/dev/null; then
    warn "O venv existente não é Python 3.12+ (ou não executa) — recriando."
    rm -rf "$VENV"
fi
if [ ! -d "$VENV" ]; then
    info "Criando venv (--copies, o volume é ExFAT)…"
    "$PYTHON" -m venv --copies "$VENV"
    ok "venv criado"
    NOVO_VENV=1
fi

# Reinstala quando o venv é novo ou quando o requirements mudou depois dele.
CARIMBO="$VENV/.deps-instaladas"
if [ "${NOVO_VENV:-0}" = "1" ] || [ ! -f "$CARIMBO" ] || [ requirements.lock -nt "$CARIMBO" ]; then
    info "Instalando dependências Python…"
    "$VENV/bin/pip" install --quiet --upgrade pip
    # ⚠️ Pelo LOCK, não pelo requirements.txt (que é todo `>=`). Ver dev.ps1 e
    # tools/lock.py — instalar pelo `.txt` deixa o build puxar a versão mais nova.
    "$VENV/bin/pip" install --quiet -r requirements.lock
    touch "$CARIMBO"
    ok "Dependências OK"
else
    ok "Dependências já instaladas"
fi

# ── 4. Sem painel no MC (fase 4 do plano um app só, 2026-11-07): o De Lá Pra Cá é o módulo Conformar do Ciclo
#    Assist, que o mostra na janela dele; o `.avpi` e as ferramentas dele (`pack`, `reload`) saíram.

# ── 5. A porta ─────────────────────────────────────────────────────────────
PORTA=7823
if lsof -nP -iTCP:$PORTA -sTCP:LISTEN >/dev/null 2>&1; then
    PID=$(lsof -nP -tiTCP:$PORTA -sTCP:LISTEN | head -1)
    warn "A porta $PORTA já está ocupada (pid $PID) — outra instância do serviço?"
    read -r -p "$(echo -e "${YELLOW}  Encerrar aquele processo e continuar? [s/N] ${RESET}")" R
    case "$R" in
        [sSyY]*) kill "$PID" 2>/dev/null || true; sleep 1; ok "Encerrado" ;;
        *) die "porta ocupada — encerre o outro serviço e tente de novo" ;;
    esac
fi

# ── 6. O Media Composer ────────────────────────────────────────────────────
if pgrep -f "MacOS/AvidMediaComposer" >/dev/null 2>&1; then
    ok "Media Composer está aberto"
else
    warn "Media Composer fechado — o painel vai abrir, mas sem nada para dirigir."
fi

# ── 7. Subir ───────────────────────────────────────────────────────────────
echo ""
echo -e "${BOLD}${GREEN}Tudo pronto. Subindo o serviço…${RESET}"
echo -e "${CYAN}  painel:  http://127.0.0.1:$PORTA/painel${RESET}"
echo -e "${DIM}  (Ctrl+C para encerrar)${RESET}"
echo ""

export PYTHONPATH="motor:plugins/media-composer/servico"
exec "$VENV/bin/python" plugins/media-composer/servico/main.py --bancada --log "${DLPC_LOG:-info}"
