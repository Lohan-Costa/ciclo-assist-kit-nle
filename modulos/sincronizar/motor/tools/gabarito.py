#!/usr/bin/env python3
"""
gabarito.py — mede o sync do Órbita contra uma timeline montada À MÃO.

## Por que existe

Até aqui a qualidade do sync era avaliada por opinião ("parece certo na tela"). Com
uma diária que um editor sincronizou manualmente e exportou em XML (FCP7/`xmeml`),
dá para MEDIR: para cada clipe, onde o editor o pôs e onde o motor põe.

O que se mede não é a posição absoluta — a origem da timeline é arbitrária — e sim
se todos os clipes guardam a MESMA distância entre si. Um sync correto difere do
gabarito por uma constante; um sync errado difere por clipe.

## O número que mais importa

Não é o acerto: é a **honestidade do aviso**. Um motor que erra 20% e sinaliza
exatamente esses 20% é utilizável — o editor sabe onde olhar. Um que erra 5% em
silêncio é pior, porque ensina a confiar no que não dá. Daí a matriz no fim:
acertou/errou × sinalizou/não sinalizou.

## Uso

    python tools/gabarito.py <timeline.xml> <pasta-do-material>

A pasta do material é varrida sozinha: subpasta com `.wav` vira som direto, as
outras viram câmeras (uma fonte por subpasta).
"""

from __future__ import annotations

import argparse
import collections
import statistics
import sys
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

#: Tolerâncias de comparação, em frames. `EXATO` é o que o editor consegue ver;
#: meio segundo já é um erro perceptível; acima de um segundo o clipe está no
#: lugar errado, e não "quase certo".
EXATO = 1
BOM = 12
PERTO = 24

AUDIO_EXT = {".wav", ".aif", ".aiff", ".bwf"}


# ── O gabarito ───────────────────────────────────────────────────────────────

def ler_xml(caminho: Path) -> dict[str, dict]:
    """
    Onde o EDITOR pôs cada clipe, lido do XML exportado do Premiere.

    Devolve `{nome_do_arquivo: {"start", "end", "label", "track"}}`, só das tracks
    de VÍDEO — o áudio embutido segue o vídeo e repetiria a mesma informação.
    """
    raiz = ET.parse(caminho).getroot()
    seq = raiz.find("sequence")
    if seq is None:
        raise SystemExit("XML sem <sequence> — isto é um export de timeline?")

    esperado: dict[str, dict] = {}
    for i, tr in enumerate(seq.find("media").find("video").findall("track"), 1):
        for ci in tr.findall("clipitem"):
            nome = ci.findtext("name") or ""
            url = ci.findtext("file/pathurl") or ""
            if url:
                nome = Path(urllib.parse.unquote(url)).name
            if not nome:
                continue
            # ⚠️ Chave em MINÚSCULAS: o Premiere escreve `.mts` no XML enquanto o
            # disco tem `.MTS`. Comparar cru fazia 20 clipes de handcam parecerem
            # "sumidos do motor" — era o instrumento errando, não o motor.
            esperado[nome.lower()] = {
                "start": int(ci.findtext("start") or 0),
                "end": int(ci.findtext("end") or 0),
                "label": ci.findtext("labels/label2") or "—",
                "track": f"V{i}",
            }
    return esperado


#: Cores com que o editor marcou o que ELE não conseguiu sincronizar. A posição
#: desses clipes no gabarito é arrumação, não medida — contá-los como erro nosso
#: seria cobrar do motor um acerto que o gabarito não tem.
SEM_SYNC_NO_GABARITO = {"magenta", "yellow"}


def ordem_confere(esperado: dict, nossos: dict, fonte: str | None = None) -> tuple[int, int]:
    """
    A CRONOLOGIA bate? Conta os pares fora de ordem (inversões).

    É a medida mais robusta que este gabarito oferece: mesmo onde a posição
    absoluta é arrumação do editor, a ORDEM em que ele pôs os clipes é a ordem real
    de gravação — e é isso que o usuário pediu para preservar.
    """
    nomes = [n for n in esperado if n in nossos
             and (fonte is None or nossos[n]["fonte"] == fonte)]
    nomes.sort(key=lambda n: esperado[n]["start"])
    pos = [nossos[n]["start"] for n in nomes]
    inversoes = sum(1 for i in range(len(pos)) for j in range(i + 1, len(pos))
                    if pos[i] > pos[j])
    pares = len(pos) * (len(pos) - 1) // 2
    return inversoes, pares


# ── O material ───────────────────────────────────────────────────────────────

def montar_entradas(pasta: Path, cronologia: list[str] | None = None) -> list[dict]:
    """Uma fonte por subpasta; quem tem `.wav` é som direto."""
    geral, por_fonte = None, {}
    for spec in cronologia or []:
        if "=" in spec:
            nome, base = spec.split("=", 1)
            por_fonte[nome] = base
        else:
            geral = spec

    def base_de(nome: str) -> str | None:
        return por_fonte.get(nome, geral)

    entradas: list[dict] = []
    for sub in sorted(p for p in pasta.iterdir() if p.is_dir()):
        arquivos = sorted(
            a for a in sub.rglob("*")
            if a.is_file() and not a.name.startswith("._") and a.suffix.lower() != ".ds_store"
        )
        if not arquivos:
            continue
        e_som = any(a.suffix.lower() in AUDIO_EXT for a in arquivos)
        for i, a in enumerate(arquivos):
            entrada = {"path": str(a), "group_id": sub.name, "group_order": i,
                       "source_name": sub.name}
            if e_som:
                entrada["kind"] = "sound"
            elif base_de(sub.name):
                entrada["chronology"] = base_de(sub.name)
            entradas.append(entrada)
    return entradas


# ── A comparação ─────────────────────────────────────────────────────────────

def origem_comum(deltas: list[int], tol: int = BOM) -> int:
    """
    A constante que separa as duas timelines.

    As origens são arbitrárias (o editor começou onde quis; o motor, onde o TC
    mandou), então o que se compara é a FORMA. O deslocamento certo é o do maior
    aglomerado de deltas — usar a média deixaria os erros grosseiros puxarem a
    régua e transformariam acertos em erros.
    """
    if not deltas:
        return 0
    ordenados = sorted(deltas)
    melhor, melhor_n = ordenados[0], 0
    for d in ordenados:
        grupo = [x for x in ordenados if abs(x - d) <= tol]
        if len(grupo) > melhor_n:
            melhor, melhor_n = int(statistics.median(grupo)), len(grupo)
    return melhor


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("xml", type=Path, help="timeline exportada do Premiere (FCP7 XML)")
    ap.add_argument("material", type=Path, help="pasta da diária")
    ap.add_argument("--metodo", default="hybrid",
                    choices=("hybrid", "timecode", "waveform"))
    ap.add_argument("--cronologia", default=None, action="append",
                    help="base declarada: `base` para todas as câmeras, ou "
                         "`FONTE=base` por fonte (repetível). Sem isto, o motor "
                         "diagnostica sozinho.")
    args = ap.parse_args()

    esperado = ler_xml(args.xml)
    print(f"gabarito: {len(esperado)} clipes de vídeo em {args.xml.name}")
    labels = collections.Counter(v["label"] for v in esperado.values())
    print(f"  labels: {dict(labels)}")

    entradas = montar_entradas(args.material, args.cronologia)
    fontes = collections.Counter(e["group_id"] for e in entradas)
    print(f"material: {len(entradas)} arquivos — {dict(fontes)}\n")

    from sync.engine import run

    ultimo = [""]

    def emit(msg, cur=0, tot=0, fase=None, frac=None):
        if msg != ultimo[0] and ("Reconferindo" in msg or "por cima" in msg
                                 or "sem áudio" in msg):
            ultimo[0] = msg
            print(f"  · {msg[:78]}")

    diaria = run(entradas, progress=emit, project_name="GABARITO",
                 sync_method=args.metodo)
    fps = diaria.fps

    nossos: dict[str, dict] = {}
    for cg in diaria.camera_groups:
        for c in cg.cameras:
            nossos[c.path.name.lower()] = {"start": c.timeline_start_frames,
                                           "flagged": c.flagged, "reason": c.flag_reason,
                                           "conf": c.confidence, "fonte": cg.name}
    for c in diaria.orphan_cameras:
        nossos[c.path.name.lower()] = {"start": c.timeline_start_frames,
                                       "flagged": True, "reason": c.flag_reason or "orfao",
                                       "conf": c.confidence, "fonte": "(órfã)"}

    comuns = [n for n in esperado if n in nossos]
    faltando = [n for n in esperado if n not in nossos]
    print(f"\ncomparando {len(comuns)} clipes"
          + (f" ({len(faltando)} do gabarito não saíram do motor)" if faltando else ""))

    deltas = [nossos[n]["start"] - esperado[n]["start"] for n in comuns
              if esperado[n]["label"].lower() not in SEM_SYNC_NO_GABARITO]
    origem = origem_comum(deltas)
    print(f"deslocamento comum entre as timelines: {origem} frames "
          f"({origem / fps:.1f} s)\n")

    # ── Resultado por clipe ──────────────────────────────────────────────────
    faixas = collections.Counter()
    matriz = collections.Counter()
    erros: list[tuple[int, str, dict]] = []

    for n in comuns:
        if esperado[n]["label"].lower() in SEM_SYNC_NO_GABARITO:
            continue          # o editor também não achou o ponto; não é gabarito
        err = abs((nossos[n]["start"] - esperado[n]["start"]) - origem)
        if err <= EXATO:
            faixa = "exato"
        elif err <= BOM:
            faixa = "<=0,5s"
        elif err <= PERTO:
            faixa = "<=1s"
        else:
            faixa = "errado"
        faixas[faixa] += 1
        certo = faixa != "errado"
        matriz[(certo, nossos[n]["flagged"])] += 1
        if not certo:
            erros.append((err, n, nossos[n]))

    total = max(1, sum(faixas.values()))

    print(f"(dos {len(comuns)}, {len(comuns) - total} foram marcados pelo editor "
          f"como sem sync e não entram na precisão)\n")
    print("CRONOLOGIA (a ordem em que o editor pôs os clipes)")
    for fonte in sorted({nossos[n]["fonte"] for n in comuns}):
        inv, pares = ordem_confere(esperado, nossos, fonte)
        if pares:
            print(f"  {fonte[:24]:26} {pares - inv:5}/{pares} pares na ordem certa"
                  f"  ({(pares - inv) / pares * 100:5.1f}%)")

    print("\nPRECISÃO DA POSIÇÃO")
    for faixa in ("exato", "<=0,5s", "<=1s", "errado"):
        n = faixas[faixa]
        print(f"  {faixa:8} {n:4}  {n / total * 100:5.1f}%  {'█' * round(n / total * 40)}")

    print("\nHONESTIDADE DO AVISO  (o número que mais importa)")
    print(f"  certo e calado      {matriz[(True, False)]:4}   ✅ como tem de ser")
    print(f"  errado e SINALIZADO {matriz[(False, True)]:4}   ✅ errou, mas avisou")
    print(f"  errado e CALADO     {matriz[(False, False)]:4}   ❌ o caso grave")
    print(f"  certo e sinalizado  {matriz[(True, True)]:4}"
          f"   ⚠️  alarme à toa")
    perigosos = matriz[(False, False)]
    print(f"\n  → {perigosos} clipe(s) errados sem aviso "
          f"({perigosos / total * 100:.1f}% do total)")

    if erros:
        print("\nPIORES ERROS")
        for err, n, info in sorted(erros, reverse=True)[:10]:
            lbl = esperado[n]["label"]
            print(f"  {err / fps:8.1f}s  {n[:30]:32} {info['fonte'][:12]:14}"
                  f" conf={info['conf']:6.2f} {'⚑ ' + str(info['reason']) if info['flagged'] else 'sem aviso'}"
                  f"  [{lbl}]")

    # ── O que o EDITOR não conseguiu sincronizar ─────────────────────────────
    magenta = [n for n in comuns
               if esperado[n]["label"].lower() in SEM_SYNC_NO_GABARITO]
    if magenta:
        print(f"\nO EDITOR MARCOU {len(magenta)} clipe(s) como SEM SYNC:")
        for n in magenta:
            err = abs((nossos[n]["start"] - esperado[n]["start"]) - origem)
            print(f"  {n[:34]:36} nosso erro {err / fps:7.1f}s"
                  f"  {'⚑ ' + str(nossos[n]['reason']) if nossos[n]['flagged'] else 'sem aviso'}")
        print("  (a posição destes no gabarito é um palpite do editor — não conta"
              " como erro nosso)")

    return 0 if matriz[(False, False)] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
