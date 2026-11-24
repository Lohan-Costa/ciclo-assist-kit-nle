"""Importa o glossário audiovisual do editor (planilha do Google) para `skills/glossario.json`.

    python tools/importar_glossario.py                 # baixa a planilha e mostra o resumo
    python tools/importar_glossario.py --gravar        # e grava o glossário
    python tools/importar_glossario.py --csv X.csv     # de um CSV já baixado

⭐⭐ **A planilha é a FONTE, e continua viva** (decisão do editor, 2026-09-22): *"o audiovisual
é muito vivo e mutável… ir colhendo os significados e onde cada expressão entra ajuda a guiar
melhor o programa"*. Ele anota lá, como sempre fez; reimportar é rodar isto de novo. O JSON
do repo é uma FOTO da planilha — nunca editado à mão, senão a próxima importação apaga.

⭐ E o que o modelo procurou e o glossário não tinha fica anotado na pasta de dados
(`glossario_pendentes.json`, ver `mcp/ferramentas/glossario.py`): `--pendentes` lista, para
ir para a planilha.

⚠️ **Formato medido na planilha (2026-09-22):** a coluna de sinônimos está VAZIA em todas as
263 linhas; os equivalentes vêm dentro do próprio termo — `AD / Assistente de direção`,
`V.O (voice over)`, `Comp/Composição/ Composition`. E o cabeçalho está uma coluna fora do
lugar: a "área" dos dados é a coluna F, não a G do título.

⚠️ **Procedência:** a planilha diz ser baseada no dicionário audiovisual da Bamboo Stock. As
descrições entram como estão; antes de DISTRIBUIR o produto, revisar o texto delas.
"""

from __future__ import annotations

import csv
import io
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

PLANILHA = "13np8z6RcDUMHYWfAatF5sroMF1M1DFghF9nQXOKqoa8"
URL = f"https://docs.google.com/spreadsheets/d/{PLANILHA}/export?format=csv"
DESTINO = Path(__file__).resolve().parents[1] / "cicloassist" / "skills" / "glossario.json"

#: Parêntese que QUALIFICA o termo em vez de ser outra forma dele: `Master (áudio)`,
#: `SD (cartão)`, `Cópia(s)`.
QUALIFICADORES = {"áudio", "audio", "vídeo", "video", "cartão", "cartao", "s"}


def _limpo(texto: str) -> str:
    return re.sub(r"\s+", " ", str(texto or "")).strip()


def formas_do_termo(termo: str) -> list[str]:
    """`V.O (voice over)` → `["V.O", "voice over"]`; `A.C / Assistente de câmera` → as duas."""
    formas: list[str] = []
    for pedaco in re.split(r"\s*/\s*", termo):
        dentro = re.findall(r"\(([^)]*)\)", pedaco)
        fora = _limpo(re.sub(r"\([^)]*\)", "", pedaco))
        if fora:
            formas.append(fora)
        for d in dentro:
            for f in re.split(r"\s*,\s*", d):
                f = _limpo(f)
                if f and f.lower() not in QUALIFICADORES:
                    formas.append(f)
    vistas, saida = set(), []
    for f in formas:
        if f.lower() not in vistas:
            vistas.add(f.lower())
            saida.append(f)
    return saida


def ler(texto_csv: str) -> list[dict]:
    linhas = list(csv.reader(io.StringIO(texto_csv)))
    entradas = []
    for l in linhas[4:]:
        l = l + [""] * 8
        termo = _limpo(l[1])
        if not termo:
            continue
        entradas.append({
            "termo": termo,
            "formas": formas_do_termo(termo),
            "sinonimos": [s for s in (_limpo(x) for x in re.split(r"[;,/]", l[2])) if s],
            "significado": _limpo(l[3]),
            "como_se_diz": _limpo(l[4]),
            "area": _limpo(l[5] or l[6]),
        })
    return entradas


def main() -> int:
    if "--pendentes" in sys.argv:
        from cicloassist.mcp.ferramentas import glossario as G
        pend = G.pendentes()
        print(f"{len(pend)} termo(s) que o modelo procurou e o glossário não tinha:\n")
        for termo, info in sorted(pend.items(), key=lambda kv: -kv[1].get("vezes", 0)):
            print(f"  {info.get('vezes', 1):3d}×  {termo}   ({info.get('motivo', '')}; "
                  f"última vez {info.get('ultima', '')})")
        return 0

    if "--csv" in sys.argv:
        texto = Path(sys.argv[sys.argv.index("--csv") + 1]).read_text(encoding="utf-8")
    else:
        with urllib.request.urlopen(URL, timeout=30) as r:
            texto = r.read().decode("utf-8")
    entradas = ler(texto)
    com_formas = sum(1 for e in entradas if len(e["formas"]) > 1)
    print(f"{len(entradas)} termos · {com_formas} com mais de uma forma · "
          f"{sum(1 for e in entradas if e['como_se_diz'])} com frase de uso")
    for e in entradas[:5]:
        print(f"  {e['termo']!r} → formas {e['formas']} · {e['area']}")
    if "--gravar" not in sys.argv:
        print("\n(nada gravado — rode com --gravar)")
        return 0
    DESTINO.write_text(json.dumps({
        "_meta": {
            "fonte": f"planilha do editor, docs.google.com/spreadsheets/d/{PLANILHA}",
            "procedencia": "baseada no dicionário audiovisual da Bamboo Stock (dito na "
                           "planilha); revisar o texto antes de distribuir o produto",
            "importado_em": time.strftime("%Y-%m-%d %H:%M"),
            "nao_edite": "FOTO da planilha — edite a planilha e rode "
                         "tools/importar_glossario.py --gravar",
        },
        "termos": entradas,
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"\ngravado em {DESTINO}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
