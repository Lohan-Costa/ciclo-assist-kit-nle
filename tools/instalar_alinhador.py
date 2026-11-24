"""Põe o modelo do alinhador por palavra (Omnilingual 300M CTC int8, ~350 MB) na pasta de modelos do produto. SÓ NO MAC.

    python tools/instalar_alinhador.py --de <pasta do release extraído>

O release vem do sherpa-onnx (`midia.alinhamento.URL_DO_MODELO`, .tar.bz2): baixar e extrair à mão, uma vez. No SSD já há
uma cópia em `MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-11 TRANSCRICAO POR PALAVRA/modelos_l0/`.
Copia só os dois arquivos que o produto lê, para um temporário e depois renomeia (cópia pela metade não carrega).
"""
import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import alinhamento as al  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--de", required=True, type=Path)
    args = ap.parse_args()
    if sys.platform == "win32":
        print("⛔ o alinhador roda só no Mac (no notebook com o Media Composer não cabe).")
        return 1
    falta = [a for a in al.ARQUIVOS_DO_MODELO if not (args.de / a).is_file()]
    if falta:
        print(f"⛔ faltam em {args.de}: {', '.join(falta)}")
        return 1
    destino = al.pasta_do_modelo()
    destino.mkdir(parents=True, exist_ok=True)
    for a in al.ARQUIVOS_DO_MODELO:
        tmp = destino / (a + ".parcial")
        shutil.copyfile(args.de / a, tmp)
        tmp.replace(destino / a)
    motivo = al.motivo_para_nao_rodar()
    print(f"✅ modelo em {destino}" if not motivo else f"⚠️ copiado, mas: {motivo}")
    return 0 if not motivo else 1


if __name__ == "__main__":
    raise SystemExit(main())
