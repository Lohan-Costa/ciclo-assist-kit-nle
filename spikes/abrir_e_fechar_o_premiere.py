"""Spike — abrir, criar e fechar o Premiere pelo `cicloassist.premiere_app`, sem ninguém na frente.

    python spikes/abrir_e_fechar_o_premiere.py [--porta 7834]

Sobe o serviço NESTE processo numa porta própria, instala uma CÓPIA de teste da ponte invisível
(`ponte_cep/`) apontando para ela, e roda:

1. `abrir(<novo>.prproj)` com o Premiere FECHADO → lança sem projeto e CRIA pela ponte;
2. `fechar()` → salva e sai; confere que o PROCESSO sumiu (e por que caminho: quit/wm_close/forçado);
3. `abrir(<o mesmo>.prproj)` → agora existe: vai na LINHA DE COMANDO;
4. `fechar()` de novo.

O projeto nasce no temporário. A extensão de teste é removida no fim. Sai 0 se tudo passou.
"""

from __future__ import annotations

import argparse
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

TRABALHO = Path(tempfile.mkdtemp(prefix="abrir_premiere_"))
os.environ["CICLOASSIST_DADOS"] = str(TRABALHO / "dados")
ID_TESTE = "com.ciclomedia.cicloassist.teste.abrir"


def instalar_ponte(porta: int) -> Path:
    destino = Path(os.environ["APPDATA"]) / "Adobe" / "CEP" / "extensions" / ID_TESTE
    if destino.exists():
        shutil.rmtree(destino)
    shutil.copytree(RAIZ / "ponte_cep", destino)
    m = destino / "CSXS" / "manifest.xml"
    m.write_text(m.read_text(encoding="utf-8").replace("com.ciclomedia.cicloassist.ponte", ID_TESTE),
                 encoding="utf-8")
    i = destino / "index.html"
    i.write_text(i.read_text(encoding="utf-8").replace("127.0.0.1:7824", f"127.0.0.1:{porta}"),
                 encoding="utf-8")
    return destino


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--porta", type=int, default=7834)
    args = ap.parse_args()
    with socket.socket() as s:
        if s.connect_ex(("127.0.0.1", args.porta)) == 0:
            print(f"⛔ porta {args.porta} ocupada")
            return 2

    from cicloassist import premiere_app as PA
    from cicloassist.servico.http import subir

    if PA.processo_vivo():
        print("⛔ o Premiere já está aberto: o CEP só lê a extensão de teste no arranque. Feche-o.")
        return 2
    print("Premiere:", PA.executavel())
    subir(args.porta)
    extensao = instalar_ponte(args.porta)
    projeto = TRABALHO / "CICLO TESTE ABRIR.prproj"
    falhas = []

    def passo(nome, f):
        t = time.monotonic()
        try:
            r = f()
            print(f"✅ {nome} ({time.monotonic() - t:.1f} s): {r}")
            return r
        except Exception as e:  # noqa: BLE001
            print(f"❌ {nome} ({time.monotonic() - t:.1f} s): {e}")
            falhas.append(nome)
            return None

    relatar = lambda etapa, fr, det: None  # noqa: E731
    try:
        r = passo("1. abrir criando", lambda: PA.abrir(str(projeto), relatar))
        if r and r["como"] != "criado":
            falhas.append("1. como")
        if not projeto.exists():
            time.sleep(3)
        print("   o .prproj existe:", projeto.exists())
        r = passo("2. fechar", lambda: PA.fechar(relatar))
        print("   processo vivo depois:", PA.processo_vivo())
        if PA.processo_vivo():
            falhas.append("2. processo")
        time.sleep(5)
        r = passo("3. abrir o que existe", lambda: PA.abrir(str(projeto), relatar))
        if r and r["como"] not in ("ja_aberto", "aberto"):
            falhas.append("3. como")
        r = passo("4. fechar", lambda: PA.fechar(relatar))
        if PA.processo_vivo():
            falhas.append("4. processo")
    finally:
        if PA.processo_vivo():
            print("⚠️ o Premiere ficou aberto")
        shutil.rmtree(extensao, ignore_errors=True)
    print("FALHAS:", falhas or "nenhuma")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
