#!/bin/zsh
# Monta a dylib do ARO e a coloca onde o Media Composer a procura (De Lá Pra Cá, 2026-10-25).
# A pasta de destino tem de existir e ser do seu usuário (o ____liberar_pasta_ARO.command já fez isso).
#
# Modos:
#   ./compilar.sh              monta aro_servidor.c e INSTALA no caminho do sistema (lab)
#   ./compilar.sh sonda        monta a sonda do passo 1.5 (servidor-escuta) e instala
#   ./compilar.sh build <saida>  SÓ monta aro_servidor.c em <saida> (+ codesign), sem instalar
#                                 — é o que o instalador do app (servico/integracoes.py) usa
set -e
AQUI="${0:A:h}"
DEST="/Library/Application Support/Avid Internal/AvidRemoteObjects364.dylib"

MODO_BUILD=""
FONTE="$AQUI/aro_servidor.c"
if [[ "$1" == "build" ]]; then
  MODO_BUILD="$2"; [[ -z "$MODO_BUILD" ]] && { echo "uso: compilar.sh build <saida.dylib>"; exit 2; }
elif [[ "$1" == "sonda" ]]; then
  FONTE="$AQUI/aro_sonda.c"
fi
SAIDA="${MODO_BUILD:-$AQUI/AvidRemoteObjects364.dylib}"

# Gera as escutas das três vtables e as tabelas. Cada escuta conhece o próprio índice; o corpo só
# chama o logger da sua interface (srv_log/in_log/out_log). Os slots REAIS são sobrescritos no constructor.
python3 - "$AQUI/aro_stubs.h" <<'PY'
import sys
fams = [("srv", 128), ("in", 64), ("out", 64)]
out = ["/* GERADO por compilar.sh — não editar. As escutas das três vtables do ARO (passo 2). */", ""]
for fam, n in fams:
    out.append(f"long {fam}_log(int idx, long a0, long a1, long a2, long a3, void *ra);")
out.append("")
for fam, n in fams:
    for i in range(n):
        out.append(f"static long {fam}_s{i}(long a0,long a1,long a2,long a3,long a4,long a5,long a6,long a7)"
                   f"{{(void)a4;(void)a5;(void)a6;(void)a7;return {fam}_log({i},a0,a1,a2,a3,__builtin_return_address(0));}}")
    out.append("")
for fam, n in fams:
    out.append(f"void *{fam}_vtable[{n}] = {{")
    out.append("  " + ", ".join(f"{fam}_s{i}" for i in range(n)))
    out.append("};")
    out.append("")
open(sys.argv[1], "w").write("\n".join(out) + "\n")
print("aro_stubs.h: srv[128] in[64] out[64]")
PY

# arm64 (o MC 25.12 roda nativo arm64); assinatura ad-hoc — o MC tem disable-library-validation
clang -arch arm64 -dynamiclib -O1 -fvisibility=hidden -framework CoreFoundation -o "$SAIDA" "$FONTE"
codesign -s - -f "$SAIDA"

if [[ -n "$MODO_BUILD" ]]; then
  echo "montada de $(basename "$FONTE") em:"
  echo "  $SAIDA"
else
  cp "$SAIDA" "$DEST"
  echo "montada de $(basename "$FONTE") e instalada em:"
  echo "  $DEST"
fi
