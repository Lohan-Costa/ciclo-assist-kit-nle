"""Gera os stubs protobuf do `mcapi` a partir do `.proto` do banco de dados.

    python tools/gerar_stubs.py

⭐ **A fonte é o banco, não este repo.** O `.proto` do Panel SDK não é publicado pela
Avid — o SDK é fechado. O que existe foi extraído por **gRPC server reflection** do
próprio Media Composer e vive em `bancodedadosnles/plugins/avid-panel-sdk/dados/`. Copiar
o arquivo para cá criaria uma segunda verdade que envelhece em silêncio; gerar a partir
dele mantém uma só.

⚠️ **Só o arquivo de TIPOS é compilado, e não o de serviço.** As chamadas são montadas
genericamente (`canal.unary_unary("/mcapi.MCAPI/" + metodo, ...)`), então os stubs de
serviço não fazem falta — e o `MCAPI.proto` traz `option (api_scope)`, uma extensão
customizada que arrastaria `descriptor.proto` para dentro da compilação sem benefício.

O arquivo do banco é a CONCATENAÇÃO dos dois `.proto`, separados por marcadores
`// ===== FILE: ... =====`. Este script recorta o segundo.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RAIZ = Path(__file__).resolve().parent.parent
# O banco mora na raiz da pasta da família; o app pode estar 1 ou 2 níveis abaixo
# (2 ATIVOS/, 9 ARQUIVADOS/…). Sobe de pasta até achar.
BANCO = next((p / "bancodedadosnles" for p in RAIZ.parents if (p / "bancodedadosnles").is_dir()),
             RAIZ.parent / "bancodedadosnles")
PROTO_DO_BANCO = BANCO / "plugins" / "avid-panel-sdk" / "dados" / "mcapi.proto"
DESTINO = RAIZ / "cicloassist" / "avid" / "proto"

MARCADOR = "// ================= FILE: MCAPI_Types.proto ================="


def main() -> int:
    if not PROTO_DO_BANCO.exists():
        sys.exit(
            f"não achei o .proto em {PROTO_DO_BANCO}\n"
            "Ele vem do bancodedadosnles, que precisa estar numa pasta acima deste repo."
        )

    texto = PROTO_DO_BANCO.read_text(encoding="utf-8")
    if MARCADOR not in texto:
        sys.exit(
            "o marcador do MCAPI_Types.proto sumiu do arquivo do banco.\n"
            "O formato mudou — conferir antes de mexer aqui."
        )
    tipos = texto.split(MARCADOR, 1)[1]

    DESTINO.mkdir(parents=True, exist_ok=True)
    (DESTINO / "__init__.py").touch()

    with tempfile.TemporaryDirectory() as tmp:
        origem = Path(tmp) / "mcapi_tipos.proto"
        origem.write_text(tipos, encoding="utf-8")

        resultado = subprocess.run(
            [sys.executable, "-m", "grpc_tools.protoc",
             f"--proto_path={tmp}",
             f"--python_out={DESTINO}",
             str(origem)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if resultado.returncode != 0:
            print(resultado.stdout)
            print(resultado.stderr, file=sys.stderr)
            return resultado.returncode

    gerado = DESTINO / "mcapi_tipos_pb2.py"
    linhas = len(gerado.read_text(encoding="utf-8").splitlines())
    print(f"gerado {gerado.relative_to(RAIZ)} ({linhas} linhas)")
    print(f"fonte  {PROTO_DO_BANCO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
