"""Spike — o arquivo que o Premiere aponta casa com o master que o Avid já processou?

    python spikes/o_convertido_casa.py

P0(b) do plano `docs/plano/2026-09-17-premiere.md`. O Premiere aponta o ORIGINAL (ou um
proxy dele); o cache do Ciclo Assist está endereçado pelo UMID do master do Avid, que em
mídia convertida é OUTRA mídia — outro arquivo, outro codec, outro UMID. A pergunta:

1. o que os dois arquivos têm em comum, nos metadados, que sirva de CANDIDATO;
2. se uma comparação de CONTEÚDO (quadros nas mesmas posições) separa o par verdadeiro
   do vizinho mais parecido — a regra do banco é que nome + duração nunca decidem
   sozinhos (`transversal/banco-de-midias-compartilhado.md` §2).

Os pares são reais e desta máquina:

| par | original | convertido | por quem |
|---|---|---|---|
| A | `20240531_PANA2774.mov` (ProRes) | `V01.E69CCE70….mxf` (MPEG-2) | transcode do Media Composer |
| B | `A001_03170214_C001.mp4` (H.264) | `a001_03170214_C001.mxf` (DNxHD) | DaVinci Resolve |

E o controle negativo de cada um é o take VIZINHO da mesma câmera, no mesmo cenário — o
impostor mais difícil que o acervo oferece.

Sai 0 se todo par verdadeiro passa e todo impostor é recusado pelo conteúdo.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import time
import unicodedata
from fractions import Fraction
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cicloassist.midia import frames  # noqa: E402

MULTICAM = Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODE\MIDIA MULTCAM\CAM B")
PRODA = Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\MIDIAS\CONVERTIDOS\D02_230405\01_CAMERAS"
            r"\CAM_A_Blackmagic-4k\A01")
ACERVO = Path(r"D:\Avid MediaFiles\MXF")
CACHE = Path.home() / "AppData" / "Local" / "CicloAssist" / "midia"

POSICOES = 5


def video_do_manifesto(nome: str) -> Path:
    """O OP-Atom de imagem de um master que o cache já conhece, pelo manifesto."""
    for m in CACHE.glob("*/midia.json"):
        dados = json.loads(m.read_text(encoding="utf-8"))
        if dados.get("nome") == nome:
            for a in dados.get("arquivos", []):
                if Path(a).name.upper().startswith("V01"):
                    return Path(a)
    raise SystemExit(f"o cache não conhece {nome}")


def sondar(arquivo: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0", "-count_packets",
         "-show_entries", "stream=avg_frame_rate,nb_read_packets:stream_tags=timecode"
         ":format_tags=timecode,reel_name,material_package_name,material_package_umid"
         ":format=duration",
         "-of", "json", str(arquivo)],
        capture_output=True, timeout=300)
    d = json.loads(r.stdout or b"{}")
    fluxo = (d.get("streams") or [{}])[0]
    marcas = (d.get("format") or {}).get("tags") or {}
    tc = (fluxo.get("tags") or {}).get("timecode") or marcas.get("timecode") or ""
    return {
        "arquivo": arquivo.name,
        # ⚠️ `avg_frame_rate`, não `r_frame_rate`: no OP-Atom o segundo vem pela METADE
        #    (banco, entrelaçamento-e-locators; medido de novo aqui: 12000/1001).
        "fps": str(Fraction(fluxo.get("avg_frame_rate") or "0/1")),
        "quadros": int(fluxo.get("nb_read_packets") or 0),
        "tc": tc,
        "nome_da_fonte": marcas.get("reel_name") or marcas.get("material_package_name")
                         or arquivo.stem,
        "umid": marcas.get("material_package_umid", ""),
    }


def normalizar(nome: str) -> str:
    """O nome como pista: sem extensão, sem sufixo `.new.NN` do Avid, sem caixa e acento."""
    n = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().casefold()
    n = re.sub(r"\.new\.\d+$", "", n)
    return re.sub(r"\.[a-z0-9]{2,4}$", "", n)


def candidato(a: dict, b: dict) -> dict:
    return {
        "nome": normalizar(a["nome_da_fonte"]) == normalizar(b["nome_da_fonte"]),
        "tc": bool(a["tc"]) and a["tc"] == b["tc"],
        "fps": a["fps"] == b["fps"],
        # banco (`protocolos/avb/escrita.md`): o original costuma ter 1 quadro a mais.
        "quadros": abs(a["quadros"] - b["quadros"]) <= 1,
    }


JANELA = 1440  # quadros do começo decodificados por inteiro (~1 min a 23,976)


def quadros_exatos(arquivo: Path, posicoes: list[int], lado: int = 32):
    """Os quadros N, decodificados em ORDEM — nunca por busca.

    ⛔⛔ MEDIDO aqui (2026-09-17): no OP-Atom MPEG-2 do transcode do Avid o ffprobe avisa
    `cannot find current edit unit for stream 0, invalid index?`, e o `-ss` antes do `-i`
    entrega OUTRO quadro — as mãos da atriz em outra posição. Comparar conteúdo com busca
    rápida reprovaria o par verdadeiro por culpa do contêiner.
    """
    import numpy as np

    expr = "+".join(f"eq(n\,{q})" for q in posicoes)
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(arquivo), "-an",
         "-vf", f"select={expr},scale={lado}:{lado},format=gray",
         "-vsync", "0", "-f", "rawvideo", "pipe:1"],
        capture_output=True, timeout=600)
    bruto = np.frombuffer(r.stdout, dtype=np.uint8).astype(np.float32)
    return bruto.reshape(-1, lado * lado)


def correlacao(x, y) -> float:
    """Pearson: indiferente a nível e ganho — o transcode muda a curva, não a imagem."""
    import numpy as np

    x = (x - x.mean()) / (x.std() + 1e-6)
    y = (y - y.mean()) / (y.std() + 1e-6)
    return float(np.mean(x * y))


def comparar(a: Path, b: Path, total: int) -> dict:
    posicoes = frames.distribuir(0, min(total, JANELA), POSICOES)
    qa, qb = quadros_exatos(a, posicoes), quadros_exatos(b, posicoes)
    if len(qa) != len(posicoes) or len(qb) != len(posicoes):
        return {"erro": f"decodifiquei {len(qa)} e {len(qb)} de {len(posicoes)}"}
    corr = [correlacao(x, y) for x, y in zip(qa, qb)]
    return {"corr_min": round(min(corr), 3), "corr_med": round(sum(corr) / len(corr), 3)}


def main() -> int:
    pares = [
        ("A verdadeiro", MULTICAM / "20240531_PANA2774.mov",
         video_do_manifesto("20240531_PANA2774.new.01"), True),
        ("A impostor", MULTICAM / "20240531_PANA2774.mov",
         video_do_manifesto("20240531_PANA2775.new.01"), False),
        ("B verdadeiro", PRODA / "A001_03170214_C001.mp4",
         ACERVO / "0200230405" / "a001_03170214_C001.mxf", True),
        ("B impostor", PRODA / "A001_03170214_C001.mp4",
         ACERVO / "0200230405" / "a001_03170256_C002.mxf", False),
    ]
    resultados = []
    for rotulo, original, convertido, verdadeiro in pares:
        t0 = time.perf_counter()
        so, sc = sondar(original), sondar(convertido)
        cand = candidato(so, sc)
        total = min(so["quadros"], sc["quadros"])
        cont = comparar(original, convertido, total)
        dt = time.perf_counter() - t0
        resultados.append((rotulo, verdadeiro, cand, cont))
        print(f"\n── {rotulo}  ({dt:.1f} s)")
        print(f"   original   {so}")
        print(f"   convertido {sc}")
        print(f"   candidato  {cand}")
        print(f"   conteúdo   {cont}")

    # Critério escrito antes da segunda rodada: correlação mínima ≥ 0,95 aprova.
    piso = 0.95
    ok = True
    print("\n══ veredito (corr_min ≥ %.2f aprova)" % piso)
    for rotulo, verdadeiro, cand, cont in resultados:
        aprovado = cont.get("corr_min", -1) >= piso
        certo = aprovado == verdadeiro
        ok &= certo
        print(f"   {'✅' if certo else '❌'} {rotulo}: {'aprova' if aprovado else 'recusa'} "
              f"(candidato por metadado: {all(cand.values())})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
