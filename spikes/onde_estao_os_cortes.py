"""Spike F0 da decupagem micro — onde estão os cortes? (plano `sobre-a-decupagem-hoje`)

    python spikes/onde_estao_os_cortes.py [--so-gerar] [--manter]

A peça de que a micro depende é saber onde um plano começa e termina. Três detectores, os
dois gabaritos EXATOS e de graça:

1. **Sintético feito de material REAL** (takes diferentes de *PRODUCAO-A*): corte seco,
   dissolves de 6/12/24/48 quadros e fade para preto (`xfade`). A posição de cada fronteira
   sai da conta das durações — é verdade exata.
2. **Um take contínuo de câmera** (3 min): um arquivo original é UMA gravação, então a
   verdade é ZERO cortes e toda detecção é falso positivo. Mede a PRECISÃO, que a peça
   montada mede mal (ela só tem os cortes que o editor fez).

Os detectores:

- **A · scdet** — a receita do PRODUCAO-V (`_PRODUCAO-V/.../decupador/planos.py`): `scdet`
  com limiar 8 (calibrado lá em novela), fusão de gatilhos a menos de 0,4 s. ⚠️ Lá o
  árbitro é o SigLIP, que reprovou neste notebook por memória (`CLAUDE.md`).
- **B · pixel** — uma passada de ffmpeg em miniatura 64×36 crua, e o numpy: `d1` (corte),
  e para o gradual o par (λ linearidade, π concentração) numa meia-janela `k`.
- **C · pixel + MobileNet** — B, com o embedding que RODA aqui derrubando a fronteira cujos
  dois lados são a mesma imagem.

Métricas: TP/FP/FN crus, precisão/recall/F1 a ±2 quadros (corte) e por sobreposição
(gradual), e o erro em quadros COM SINAL. Sai 0 se rodou; a resposta é a tabela.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from fractions import Fraction
from pathlib import Path

import numpy as np

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

MIDIA = Path(r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\MIDIAS\CONVERTIDOS")
#: Takes de DIÁRIAS e lugares diferentes, e dois da mesma cena (o corte difícil:
#: plano/contraplano no mesmo ambiente).
FONTES = [
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A01/A001_03170423_C007.mp4",
    "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A09/A009_03190918_C010.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180147_C009.mp4",
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A02/A002_03170700_C002.mp4",
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A02/A002_03170703_C003.mp4",
    "D01_230403/01_CAMERAS/CAM_A_Blackmagic-4k/B01/B001_03150130_C010.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A07/A007_03180748_C002.mp4",
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A01/A001_03170452_C012.mp4",
    "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A09/A009_03190920_C011.mp4",
    "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A09/A009_03190922_C012.mp4",
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A01/A001_03170436_C009.mp4",
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A01/A001_03170437_C010.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180353_C014.mp4",
]
#: ⭐ O conjunto de VALIDAÇÃO: outros 13 takes e outra ordem de junções (com uma de 36
#: quadros, que a calibração não viu). Nenhum limiar é ajustado olhando para ele.
FONTES_B = [
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180354_C016.mp4",
    "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A09/A009_03190845_C003.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180428_C023.mp4",
    "D01_230403/01_CAMERAS/CAM_A_Blackmagic-4k/B01/B001_03150204_C021.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A07/A007_03180749_C003.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180402_C019.mp4",
    "D02_230405/01_CAMERAS/CAM_A_Blackmagic-4k/A02/A002_03170657_C001.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180141_C008.mp4",
    "D03_230406/01_CAMERAS/CAM_A_Blackmagic-4k/A05/A005_03180359_C018.mp4",
    "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A09/A009_03190831_C002.mp4",
    "D01_230403/01_CAMERAS/CAM_A_Blackmagic-4k/B01/B001_03150127_C008.mp4",
    "D01_230403/01_CAMERAS/CAM_A_Blackmagic-4k/B01/B001_03150122_C006.mp4",
    "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A08/A008_03190522_C010.mp4",
]
JUNCOES_B = [("fade", 24), ("corte", 0), ("fadeblack", 12), ("corte", 0), ("fade", 36),
             ("corte", 0), ("corte", 0), ("fade", 8), ("corte", 0), ("fadeblack", 36),
             ("corte", 0), ("fade", 18)]
CONTINUO = MIDIA / "D04_230407/01_CAMERAS/CAM_A_Blackmagic-4k/A08/A008_03190339_C003.mp4"
TAXA = Fraction(24000, 1001)
SEG_S = 5.2          # o que se lê de cada fonte (sobra para o trim)
QUADROS_POR_TRECHO = 120
INICIO_S = 8.0       # pula a claquete da cabeça
#: A junção ENTRE o trecho i e o i+1: ("corte", 0) ou (transição do xfade, quadros).
JUNCOES = [("corte", 0), ("corte", 0), ("fade", 6), ("corte", 0), ("fade", 12),
           ("corte", 0), ("fade", 24), ("fadeblack", 24), ("corte", 0), ("fade", 48),
           ("corte", 0), ("corte", 0)]
LADO = (64, 36)


# ── o gabarito sintético ─────────────────────────────────────────────────────

def gerar_sintetico(pasta: Path, fontes: list[str] | None = None,
                    juncoes: list | None = None,
                    nome: str = "sintetico") -> tuple[Path, list[dict]]:
    """O arquivo emendado e a verdade: `[{tipo, inicio, fim}]` em QUADROS da saída.

    ⚠️ Um corte seco pelo `xfade` não existe (duração mínima de um quadro); as junções são
    feitas por `concat` quando TODAS entre dois `xfade` são cortes — aqui, cada junção é
    montada em série: `xfade` para as graduais, e para o corte um `xfade` de UM quadro,
    que é o corte seco com a fronteira naquele quadro.
    """
    fontes, juncoes = fontes or FONTES, juncoes or JUNCOES
    n = len(juncoes) + 1
    entradas, filtros = [], []
    for i, rel in enumerate(fontes[:n]):
        entradas += ["-ss", str(INICIO_S), "-t", str(SEG_S), "-i", str(MIDIA / rel)]
        filtros.append(f"[{i}:v]scale=640:360,setsar=1,settb=AVTB,setpts=PTS-STARTPTS,fps={TAXA},trim=end_frame={QUADROS_POR_TRECHO},format=yuv420p[v{i}]")
    quadro = 1 / float(TAXA)
    # ⚠️ MEDIDO: com `-t 5` cada trecho saía com 119 OU 120 quadros, e a verdade derivava
    #    até 3 quadros. Cortado por QUADRO (`trim`), o trecho tem 120 = 5,005 s — e a conta
    #    tem de usar isso, não os 5,0 s.
    seg = QUADROS_POR_TRECHO * quadro
    atual, dur = "v0", seg
    verdade = []
    for j, (tipo, q) in enumerate(juncoes):
        saida = f"x{j}"
        if tipo == "corte":
            # ⛔ MEDIDO: um `xfade` de UM quadro arredonda para duração zero e a cadeia PARA
            #    ali, sem erro — o arquivo saiu com 120 quadros. Corte seco é `concat`.
            d = 0.0
            offset = dur
            filtros.append(f"[{atual}][v{j + 1}]concat=n=2:v=1:a=0,fps={TAXA}[{saida}]")
        else:
            d = q * quadro
            offset = dur - d
            filtros.append(f"[{atual}][v{j + 1}]xfade=transition={tipo}:duration={d:.6f}"
                           f":offset={offset:.6f}[{saida}]")
        ini = round(offset * float(TAXA))
        verdade.append({"tipo": "corte" if tipo == "corte" else
                        ("fade" if tipo == "fadeblack" else "dissolve"),
                        "quadros": q, "inicio": ini, "fim": ini + max(1, q)})
        atual, dur = saida, dur + seg - d
    arquivo = pasta / f"{nome}.mp4"
    cmd = ["ffmpeg", "-v", "error", "-y", *entradas, "-filter_complex", ";".join(filtros),
           "-map", f"[{atual}]", "-c:v", "libx264", "-crf", "20", "-preset", "veryfast",
           str(arquivo)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("ffmpeg recusou o sintético:\n" + r.stderr[-1500:])
    (pasta / f"{nome}.json").write_text(json.dumps(verdade, indent=1), encoding="utf-8")
    return arquivo, verdade


# ── a série de pixel ─────────────────────────────────────────────────────────

def miniaturas(arquivo: Path, limite_s: float | None = None) -> np.ndarray:
    """Todos os quadros em 64×36 RGB, em ORDEM (sem busca: a armadilha do N/2 não se aplica).

    ⚠️ Leitura exata por quadro: `read` num pipe pode voltar parcial, e aí o quadro 300
    começaria no meio do 299 — a série vira lixo sem erro nenhum.
    """
    w, h = LADO
    cmd = ["ffmpeg", "-nostdin", "-v", "error", *(["-t", str(limite_s)] if limite_s else []),
           "-i", str(arquivo), "-map", "0:v:0", "-an", "-sn", "-dn",
           "-vf", f"scale={w}:{h}:flags=area,format=rgb24",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    bruto = subprocess.run(cmd, capture_output=True, check=True).stdout
    tam = w * h * 3
    n = len(bruto) // tam
    return np.frombuffer(bruto[:n * tam], np.uint8).reshape(n, h, w, 3).astype(np.float32) / 255


def series(q: np.ndarray, k: int) -> dict[str, np.ndarray]:
    n = len(q)
    lum = q.mean(axis=3)
    d1 = np.zeros(n, np.float32)
    d1[1:] = np.abs(q[1:] - q[:-1]).mean(axis=(1, 2, 3))
    z = (lum - lum.mean(axis=(1, 2), keepdims=True)) / (lum.std(axis=(1, 2), keepdims=True) + 1e-3)
    dz = np.zeros(n, np.float32)
    dz[1:] = np.abs(z[1:] - z[:-1]).mean(axis=(1, 2))
    D = np.zeros(n, np.float32)
    P = np.zeros(n, np.float32)
    mx = np.zeros(n, np.float32)
    DZ = np.zeros(n, np.float32)
    for t in range(k, n - k):
        D[t] = np.abs(q[t + k] - q[t - k]).mean()
        DZ[t] = np.abs(z[t + k] - z[t - k]).mean()
        janela = d1[t - k + 1:t + k + 1]
        P[t] = janela.sum()
        mx[t] = janela.max()
    lam = np.where(P > 1e-6, D / np.maximum(P, 1e-6), 0)
    pi = np.where(P > 1e-6, mx / np.maximum(P, 1e-6), 0)
    return {"d1": d1, "dz": dz, "D": D, "DZ": DZ, "lam": lam, "pi": pi,
            "sig": lum.std(axis=(1, 2)), "mu": lum.mean(axis=(1, 2))}


def _limiar(x: np.ndarray, t: int, meia: int, c: float, piso: float) -> float:
    janela = x[max(0, t - meia):t + meia + 1]
    med = float(np.median(janela))
    mad = float(np.median(np.abs(janela - med)))
    return max(piso, med + c * 1.4826 * mad)


#: As meias-janelas do gradual. ⚠️ MEDIDO: com k=6 só, o dissolve de 48 quadros passou —
#: a diferença entre quadros a 12 de distância, no meio de uma mistura de 48, é pequena.
ESCALAS = (6, 12, 24)


def _em_escala(q: np.ndarray, d1: np.ndarray, k: int) -> tuple[np.ndarray, np.ndarray]:
    """(D, λ) com meia-janela k, vetorizado: D = |F(t+k) − F(t−k)|, λ = D / caminho."""
    n = len(q)
    D = np.zeros(n, np.float32)
    lam = np.zeros(n, np.float32)
    if n <= 2 * k:
        return D, lam
    D[k:n - k] = np.abs(q[2 * k:] - q[:n - 2 * k]).mean(axis=(1, 2, 3))
    acum = np.concatenate([[0.0], np.cumsum(d1)])
    t = np.arange(k, n - k)
    caminho = acum[t + k + 1] - acum[t - k + 1]
    lam[k:n - k] = np.where(caminho > 1e-6, D[k:n - k] / np.maximum(caminho, 1e-6), 0)
    return D, lam


def detectar_pixel(q: np.ndarray, s: dict[str, np.ndarray], c: float = 8.0,
                   piso_corte: float = 0.015, isolamento: float = 3.0,
                   piso_grad: float = 0.08, lam_min: float = 0.6,
                   dz_min: float = 0.2) -> list[dict]:
    """Cortes: um pico de `d1` ISOLADO (muitas vezes maior que os vizinhos) e acima do
    limiar adaptativo. Graduais: em cada escala, `D` alto com a trajetória RETA (λ alto) e
    sem corte perto. O `dz` (imune a luz) é o porteiro dos dois.

    ⚠️ MEDIDO no sintético: os cortes dão `d1` de 0,037 a 0,305 contra ruído de mediana
    0,0009 (p90 0,0054) — um piso fixo de 0,06 perdia o de 0,037 (mesmo cenário, dois
    takes). O que separa corte de ruído é o ISOLAMENTO, não o tamanho.
    """
    d1, dz = s["d1"], s["dz"]
    n = len(d1)
    achados: list[dict] = []
    for t in range(1, n):
        viz = np.concatenate([d1[max(1, t - 3):t], d1[t + 1:t + 4]])
        if viz.size and d1[t] > isolamento * max(float(viz.max()), 1e-4) \
                and d1[t] > _limiar(d1, t, 24, c, piso_corte) and dz[t] > dz_min:
            achados.append({"tipo": "corte", "inicio": t, "fim": t + 1, "medida": float(d1[t])})
    cortes = [a["inicio"] for a in achados]

    graduais: list[dict] = []
    for k in ESCALAS:
        D, lam = _em_escala(q, d1, k)
        t = k
        while t < n - k:
            if D[t] > piso_grad and lam[t] > lam_min and all(abs(t - x) > k for x in cortes):
                ini = t
                while t < n - k and D[t] > piso_grad * 0.7:
                    t += 1
                centro = ini + int(np.argmax(D[ini:t + 1]))
                graduais.append({"tipo": "gradual", "inicio": max(0, centro - k),
                                 "fim": centro + k, "medida": float(D[centro]), "k": k})
            t += 1
    # A mesma transição aparece em várias escalas: fica a de maior D, uma por região.
    graduais.sort(key=lambda a: -a["medida"])
    for g in graduais:
        if all(g["fim"] < a["inicio"] or g["inicio"] > a["fim"] for a in achados):
            # ⭐ Fade: no meio da transição a imagem é (quase) chapada — o desvio da luma cai.
            meio = (g["inicio"] + g["fim"]) // 2
            if s["sig"][max(0, meio - 3):meio + 4].min() < 0.02:
                g["tipo"] = "fade"
            achados.append(g)
    return sorted(achados, key=lambda a: a["inicio"])


# ── o scdet (a receita do PRODUCAO-V) ──────────────────────────────────────────

def detectar_scdet(arquivo: Path, limiar: float = 8.0, limite_s: float | None = None,
                   fundir_s: float = 0.4) -> list[dict]:
    import re
    cmd = ["ffmpeg", "-nostdin", "-hide_banner", *(["-t", str(limite_s)] if limite_s else []),
           "-i", str(arquivo), "-vf", "scdet=threshold=3", "-f", "null", "-"]
    err = subprocess.run(cmd, capture_output=True, text=True).stderr
    brutos = [(float(a), float(b)) for a, b in
              re.findall(r"lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)", err)]
    tempos = []
    for sc, tt in sorted(brutos, key=lambda x: x[1]):
        if sc >= limiar and (not tempos or tt - tempos[-1] >= fundir_s):
            tempos.append(tt)
    # ⚠️ Tempo → quadro na taxa do ARQUIVO. MEDIDO: com 23,976 fixo, a peça da Copa (29,97)
    #    saiu com 52 "cortes só do scdet" — eram as posições dele escaladas, não cortes.
    from cicloassist.midia import identidade as _id
    try:
        fps = float(Fraction(str(_id.sondar(arquivo).get("fps") or TAXA)))
    except Exception:  # noqa: BLE001
        fps = float(TAXA)
    return [{"tipo": "corte", "inicio": round(tt * fps), "fim": round(tt * fps) + 1,
             "medida": 0.0} for tt in tempos]


# ── o árbitro: MobileNet ─────────────────────────────────────────────────────

def confirmar_com_mobilenet(arquivo: Path, achados: list[dict], limite: float) -> list[dict]:
    """Derruba a fronteira cujos dois lados (2 quadros antes / depois) são a mesma imagem."""
    from cicloassist.midia import frames as F
    from cicloassist.midia import vetores as V
    if not achados:
        return achados
    pos = []
    for a in achados:
        pos += [max(0, a["inicio"] - 3), a["fim"] + 3]
    jpegs = F.extrair_varios(arquivo, sorted(set(pos)), TAXA)
    vet = {p: V.de_jpeg(j) for p, j in jpegs.items()}
    saida = []
    for a in achados:
        va, vb = vet.get(max(0, a["inicio"] - 3)), vet.get(a["fim"] + 3)
        if va is None or vb is None:
            saida.append(a)
            continue
        sim = float(np.dot(va, vb) / (np.linalg.norm(va) * np.linalg.norm(vb) + 1e-9))
        a = {**a, "sim": round(sim, 3)}
        if sim < limite:
            saida.append(a)
    return saida


def unir(scdet: list[dict], pixel: list[dict], raio: int = 3) -> list[dict]:
    """⭐ D · a UNIÃO: os cortes dos dois, e as transições graduais só do pixel.

    MEDIDO (2026-09-22): cada um vê o que o outro não vê. No sintético o scdet perde TODO
    dissolve e fade (0 de 5 na validação); na peça montada da Copa (corte rápido, grafismo)
    o pixel perde ~1/3 dos cortes — o teste de pico isolado falha quando os vizinhos
    também mudam muito. E para a decupagem perder um corte é o erro caro (a nota mistura
    dois planos); sobrar um é barato (uma nota a mais).
    """
    saida = list(pixel)
    for a in scdet:
        if all(abs(a["inicio"] - b["inicio"]) > raio and not (b["inicio"] <= a["inicio"] <= b["fim"])
               for b in pixel):
            saida.append({**a, "de": "scdet"})
    return sorted(saida, key=lambda a: a["inicio"])


# ── a régua ──────────────────────────────────────────────────────────────────

def comparar(verdade: list[dict], achados: list[dict], tol: int = 2) -> dict:
    usados, tp, erros, faltou = set(), 0, [], []
    for v in verdade:
        centro_v = (v["inicio"] + v["fim"]) / 2
        melhor = None
        for i, a in enumerate(achados):
            if i in usados:
                continue
            sobrepoe = a["inicio"] <= v["fim"] + tol and a["fim"] >= v["inicio"] - tol
            if sobrepoe:
                centro_a = (a["inicio"] + a["fim"]) / 2
                if melhor is None or abs(centro_a - centro_v) < abs(melhor[1] - centro_v):
                    melhor = (i, centro_a)
        if melhor is None:
            faltou.append(f"{v['tipo']}{v.get('quadros') or ''}@{v['inicio']}")
            continue
        usados.add(melhor[0])
        tp += 1
        if v["tipo"] == "corte":
            erros.append(round(achados[melhor[0]]["inicio"] - v["inicio"]))
    fp = len(achados) - len(usados)
    fn = len(verdade) - tp
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "P": round(p, 2), "R": round(r, 2),
            "F1": round(2 * p * r / (p + r), 2) if p + r else 0.0,
            "erro_corte_quadros": erros, "faltou": faltou,
            "sobrou": [f"{a['tipo']}@{a['inicio']}" for i, a in enumerate(achados) if i not in usados]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--so-gerar", action="store_true")
    ap.add_argument("--pasta", default="")
    ap.add_argument("--continuo-s", type=float, default=180.0)
    ap.add_argument("--k", type=int, default=6)
    args = ap.parse_args()
    pasta = Path(args.pasta or tempfile.mkdtemp(prefix="cortes_"))
    pasta.mkdir(parents=True, exist_ok=True)
    conjuntos = []
    for nome, fontes, juncoes in (("sintetico", FONTES, JUNCOES),
                                  ("validacao", FONTES_B, JUNCOES_B)):
        arq, verd = pasta / f"{nome}.mp4", pasta / f"{nome}.json"
        if arq.is_file() and verd.is_file():
            verdade = json.loads(verd.read_text(encoding="utf-8"))
        else:
            arq, verdade = gerar_sintetico(pasta, fontes, juncoes, nome)
        print(f"{nome}: {len(verdade)} fronteiras · "
              + ", ".join(f"{v['tipo']}{v['quadros'] or ''}@{v['inicio']}" for v in verdade))
        conjuntos.append((nome.upper(), arq, verdade))
    if args.so_gerar:
        return 0

    resultado = {}
    for nome, arquivo, verd, limite in (*[(n, a, v, None) for n, a, v in conjuntos],
                                        ("CONTÍNUO (0 cortes)", CONTINUO, [], args.continuo_s)):
        t = time.perf_counter()
        q = miniaturas(arquivo, limite)
        s = series(q, args.k)
        t_pix = time.perf_counter() - t
        t = time.perf_counter()
        a_sc = detectar_scdet(arquivo, limite_s=limite)
        t_sc = time.perf_counter() - t
        a_px = detectar_pixel(q, s)
        t = time.perf_counter()
        a_mn = confirmar_com_mobilenet(arquivo, a_px, limite=0.90)
        t_mn = time.perf_counter() - t
        print(f"\n== {nome} · {len(q)} quadros · pixel {t_pix:.1f} s · scdet {t_sc:.1f} s · "
              f"MobileNet {t_mn:.1f} s")
        a_un = unir(a_sc, a_px)
        for rot, ach in (("A scdet", a_sc), ("B pixel", a_px), ("C pixel+MobileNet", a_mn),
                         ("D scdet ∪ pixel", a_un)):
            m = comparar(verd, ach)
            resultado[f"{nome}/{rot}"] = m
            print(f"  {rot:20s} TP {m['TP']:2d} FP {m['FP']:3d} FN {m['FN']:2d} · P {m['P']} "
                  f"R {m['R']} F1 {m['F1']} · erro corte {m['erro_corte_quadros']}")
            if m["faltou"]:
                print(f"  {'':20s} faltou: {m['faltou']}")
            if m["sobrou"][:8]:
                print(f"  {'':20s} sobrou: {m['sobrou'][:8]}{' …' if len(m['sobrou']) > 8 else ''}")
        np.savez(pasta / f"series_{nome.split()[0].lower()}.npz", **s)
    (pasta / "resultado.json").write_text(json.dumps(resultado, indent=1, ensure_ascii=False),
                                          encoding="utf-8")
    print(f"\npasta: {pasta}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
