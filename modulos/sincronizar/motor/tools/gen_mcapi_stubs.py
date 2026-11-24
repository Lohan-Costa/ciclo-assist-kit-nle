"""Regera o stub protobuf da API do Media Composer.

O `.proto` veio da base de conhecimento interna (`plugins/avid-panel-sdk/dados/mcapi.proto`), que
o extraiu por **gRPC server reflection** do próprio Media Composer — não há SDK
público. Lá ele é a CONCATENAÇÃO de dois arquivos; aqui fica só o segundo
(`MCAPI_Types.proto`), que tem as 252 mensagens. O primeiro só declara o
`service`, e os métodos são chamados por caminho em `avid/mcapi.py`.

    python tools/gen_mcapi_stubs.py

Requer `grpcio-tools`, que é dependência de DESENVOLVIMENTO — o app em produção
precisa só do `grpcio`.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]          # src-python
PROTO = RAIZ / "avid" / "proto" / "mcapi_types.proto"


def main() -> int:
    if not PROTO.exists():
        print(f"proto não encontrado: {PROTO}", file=sys.stderr)
        return 1
    # `-I` na RAIZ faz o import gerado sair como `avid.proto.…` (e não achatado),
    # que é o que permite o stub viver dentro do pacote.
    cmd = [sys.executable, "-m", "grpc_tools.protoc", f"-I{RAIZ}",
           f"--python_out={RAIZ}", str(PROTO.relative_to(RAIZ))]
    print(" ".join(cmd))
    r = subprocess.run(cmd, cwd=RAIZ)
    if r.returncode == 0:
        saida = PROTO.with_name("mcapi_types_pb2.py")
        print(f"gerado: {saida.relative_to(RAIZ)} ({saida.stat().st_size} bytes)")
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
