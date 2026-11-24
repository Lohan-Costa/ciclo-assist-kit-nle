"""Deixa a IMAGEM da cena 7 pronta para o fluxo de edição: vetores e decupagem micro no Mac.

    python spikes/edicao_de_cena/preparar_c07.py --olhar    # só conta o que o cache já tem
    python spikes/edicao_de_cena/preparar_c07.py            # processa o que falta

Só lê a bin no disco: não fala com o Media Composer. Pode ser interrompido e repetido: a micro pula o trecho já feito.
Plano: `docs/plano/2026-11-09-edicao-de-cena.md`.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(RAIZ))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid.take import resolver  # noqa: E402
from cicloassist.motor import micro as _micro, percepcao as _perc  # noqa: E402
from cicloassist.midia import vetores as _vetores  # noqa: E402

BIN = r"%USERPROFILE%\Documents\Avid Projects\producao-a_CURTA\CENAS\C07.avb"
TAKES = ("C07_P01-001 C07_P01-002 C07_P02-001 C07_P02-002 C07_P02-003 "
         "C07_P02-004 C07_P03-001 C07_P03-002 C07_P03-003").split()   # C07_P02-001.1 tem 8 quadros


def duracao_em_quadros(arquivo: str, taxa: Fraction) -> int:
    saida = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", arquivo],
                           capture_output=True, text=True, timeout=60).stdout.strip()
    return int(float(saida) * taxa)


def contagem(midia) -> dict:
    notas = {}
    arq = midia.arquivo("notas.json")
    if arq.exists():
        dado = json.loads(arq.read_text(encoding="utf-8"))
        for n in (dado.get("notas", []) if isinstance(dado, dict) else dado):
            notas[n.get("escopo")] = notas.get(n.get("escopo"), 0) + 1
    pasta = midia.arquivo("quadros")
    return {"quadros": len(list(pasta.glob("*.jpg"))) if pasta.exists() else 0,
            "vetores": _vetores.quantos(midia), "cortes": midia.arquivo("cortes.json").exists(), "notas": notas}


def main() -> int:
    olhar = "--olhar" in sys.argv
    url = _perc.endereco()
    if not olhar:
        print("Mac:", url, _perc.conferir(url))
    inicio = time.monotonic()
    vistos: set[str] = set()
    for nome in TAKES:
        take = resolver(BIN, nome)
        fonte = take.imagem
        if fonte is None or fonte.chave in vistos:
            print(f"{nome}: sem imagem própria, pulado")
            continue
        vistos.add(fonte.chave)
        midia = fonte.midia(rotulo=take.rotulo(fonte))
        print(f"{nome}: {contagem(midia)}")
        if olhar:
            continue
        taxa = Fraction(take.fps["num"], take.fps["den"])
        arquivo = str(fonte.arquivos[0])
        t0 = time.monotonic()
        try:
            feito = _vetores.vetorizar_master(midia, arquivo, taxa, duracao_em_quadros(arquivo, taxa), fonte.master)
            print(f"   vetores: {feito} em {time.monotonic() - t0:.0f} s")
            t0 = time.monotonic()
            feito = _micro.processar(midia, arquivo, taxa, fonte.master, url,
                                     avisar=lambda _f, txt: print("   ", txt))
            print(f"   micro: {feito} em {time.monotonic() - t0:.0f} s")
        except _perc.MacIndisponivel as e:
            print(f"⛔ o Mac parou de responder: {e}")
            return 2
        except Exception as e:  # noqa: BLE001 — uma mídia ruim não pode derrubar as outras
            print(f"   ⚠️ falhou: {type(e).__name__}: {e}")
        print(f"   depois: {contagem(midia)}")
    print(f"fim em {(time.monotonic() - inicio) / 60:.1f} min")
    return 0


if __name__ == "__main__":
    sys.exit(main())
