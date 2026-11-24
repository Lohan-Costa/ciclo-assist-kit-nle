"""Onde os planos começam e terminam — e em que TRECHOS a decupagem micro olha.

⭐⭐ A base da decupagem MICRO (plano `sobre-a-decupagem-hoje`, F1). Ela COMPLEMENTA a macro
(a nota do material inteiro) e nunca a substitui — decisão do editor, 2026-09-22.

## O detector — medido antes (F0, banco `transversal/deteccao-de-corte.md`)

A UNIÃO de dois, porque cada um vê o que o outro não vê:

| | vê | não vê |
|---|---|---|
| `scdet` do ffmpeg (limiar 8, a receita de `_PRODUCAO-V/.../planos.py`) | corte em material rápido com grafismo | **nenhum** dissolve ou fade (0 de 5) |
| pixel 64×36 (abaixo) | dissolve de 6 a 48 quadros, fade, corte | ~1/3 dos cortes em promo rápida |

Validação: 12 de 12, 0 falso positivo num take contínuo de 3 min. ⛔ Sem árbitro de embedding:
o MobileNet derrubou corte real (é semântico).

⭐ **Uma passada só**: o `scdet` roda no vídeo cheio e escreve no stderr; o mesmo ffmpeg
reduz para 64×36 e entrega no stdout. Decodificar duas vezes custaria o dobro.
⭐ **Em fluxo**: só uma janela de `2·max(ESCALAS)+1` quadros fica em memória — uma peça de
30 min em float seriam ~500 MB, com o Media Composer aberto ao lado.

## Os trechos: um para o montado, outro para o bruto

- **Montado** (tem corte): cada plano é um trecho.
- **Bruto** (original de câmera, zero corte POR CONSTRUÇÃO): as fronteiras graduais que
  aparecem são MUDANÇAS de momento (alguém passa na frente, a câmera vai da porta para a
  atriz), e é isso que a micro quer. E o plano longo é dividido pela AÇÃO: medido, o
  movimento por 10 s vai de ~0,2 (take parado) a ~6,6 (take agitado).
- ⭐ "Zero corte seco" é o sinal de bruto — e é o primeiro trecho dele que ganha os quadros
  da CABEÇA para ler a claquete. Peça montada não tem claquete para ler.
"""

from __future__ import annotations

import json
import logging
import math
import re
import subprocess
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

import numpy as np

from . import cache as _cache

log = logging.getLogger("cicloassist.midia.cortes")

LADO = (64, 36)
ESCALAS = (6, 12, 24)
LIMIAR_SCDET = 8.0
FUNDIR_SCDET_S = 0.4
#: Corte pelo pixel: pico ISOLADO (≥ isso × o maior vizinho em ±3) e acima do limiar
#: adaptativo (mediana + C·1,4826·MAD numa janela de ±24), com piso.
ISOLAMENTO = 3.0
C_MAD = 8.0
PISO_CORTE = 0.015
DZ_MIN = 0.2
PISO_GRADUAL = 0.08
LAMBDA_MIN = 0.6
RAIO_UNIAO = 3
#: A divisão do plano longo pela ação. ⚠️ Calibragem INICIAL, sobre 4 takes do acervo — a
#: medir em uso: quantos trechos o editor acha demais ou de menos.
MOVIMENTO_POR_TRECHO = 4.0
TRECHO_MIN_S = 10.0
TRECHO_MAX_S = 60.0
#: ⭐ Trecho mais curto que isso é juntado ao vizinho. MEDIDO: a peça montada da Copa deu 77
#: trechos em 60 s (planos de 0,1 a 0,6 s) — 2 h de Mac para 1 min de material, e um plano de
#: 0,4 s mal tem o que descrever. No bruto, "mudanças" coladas davam pedaços de 1 a 3 s.
TRECHO_JUNTAR_S = 4.0
#: No montado, um grupo nunca passa disso: é um quadro por plano no pedido ao modelo.
PLANOS_POR_TRECHO = 8

#: ⛔⛔ Quanto se espera por UM quadro antes de matar o ffmpeg. Todo outro ffmpeg da casa
#: roda por `subprocess.run(timeout=…)`; este lê em FLUXO e não tinha prazo nenhum — e o
#: preço de um travamento aqui não é esta mídia: a fila é **uma tarefa por vez**, então o
#: editor ficaria sem poder analisar nada, com a barra em "correndo", até reiniciar o
#: serviço. ⭐ O prazo é de PARADA, não de duração: um arquivo de três horas leva minutos
#: legitimamente, mas entrega quadro o tempo todo. Quem não entrega travou.
PRAZO_SEM_QUADRO_S = 120.0

ASSINATURA = {
    "versao": 1, "lado": list(LADO), "escalas": list(ESCALAS), "scdet": LIMIAR_SCDET,
    "isolamento": ISOLAMENTO, "c_mad": C_MAD, "piso_corte": PISO_CORTE, "dz_min": DZ_MIN,
    "piso_gradual": PISO_GRADUAL, "lambda_min": LAMBDA_MIN,
    "movimento_por_trecho": MOVIMENTO_POR_TRECHO, "trecho_s": [TRECHO_MIN_S, TRECHO_MAX_S],
    "juntar_s": TRECHO_JUNTAR_S, "planos_por_trecho": PLANOS_POR_TRECHO,
}
ARQUIVO = "cortes.json"


class DeteccaoFalhou(RuntimeError):
    """O ffmpeg não conseguiu ler o vídeo."""


@dataclass
class Trecho:
    #: Quadros do MASTER, fim exclusivo — coerente com `quadros/00001357.jpg` e as notas.
    inicio: int
    fim: int
    #: Como o trecho começa: `inicio` · `corte` · `dissolve` · `fade` · `mudanca` · `divisao`.
    entrada: str
    #: Soma de `d1` no trecho — a medida da ação, e o que decide a densidade de quadros.
    movimento: float
    #: ⭐ O primeiro trecho de um take BRUTO: é nele que se lê a claquete.
    cabeca: bool = False
    #: O início de cada PLANO dentro do trecho (quadros do master). Um só no bruto; vários
    #: no montado, quando planos curtos foram juntados — e aí o modelo vê um quadro de cada.
    planos: list[int] | None = None


# ── a passada ────────────────────────────────────────────────────────────────

_SCDET = re.compile(r"lavfi\.scd\.score:\s*([0-9.]+),\s*lavfi\.scd\.time:\s*([0-9.]+)")


def _ler_exato(fluxo, n: int) -> bytes:
    """⚠️ `read` num pipe volta PARCIAL: sem o laço, o quadro 300 começaria no meio do 299 e
    a série viraria lixo sem erro nenhum."""
    partes, falta = [], n
    while falta:
        bloco = fluxo.read(falta)
        if not bloco:
            break
        partes.append(bloco)
        falta -= len(bloco)
    return b"".join(partes)


def _passada(arquivo: Path) -> dict[str, Any]:
    """Uma decodificação: as séries do pixel (em fluxo) e os achados do `scdet`."""
    from .frames import achar_ffmpeg
    w, h = LADO
    kmax = max(ESCALAS)
    cmd = [achar_ffmpeg(), "-nostdin", "-hide_banner", "-v", "info", "-i", str(arquivo),
           "-map", "0:v:0", "-an", "-sn", "-dn",
           "-vf", f"scdet=threshold=3,scale={w}:{h}:flags=area,format=rgb24",
           "-fps_mode", "passthrough", "-f", "rawvideo", "-"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            stdin=subprocess.DEVNULL,
                            **({"creationflags": 0x08000000} if hasattr(subprocess, "STARTUPINFO") else {}))
    # ⛔ O stderr DRENADO numa thread (a regra da casa, `CLAUDE.md`): com `-v info` o scdet
    #    escreve uma linha por quadro candidato, e um pipe cheio (~64 KB) TRAVA o ffmpeg.
    scdet: list[tuple[float, float]] = []
    cauda: deque[str] = deque(maxlen=20)

    def drenar() -> None:
        for linha in iter(proc.stderr.readline, b""):
            texto = linha.decode("utf-8", "replace")
            achado = _SCDET.search(texto)
            if achado:
                scdet.append((float(achado.group(1)), float(achado.group(2))))
            else:
                cauda.append(texto.strip())

    t_err = threading.Thread(target=drenar, daemon=True)
    t_err.start()

    # ⛔ O cão de guarda: mata o ffmpeg que parou de entregar quadro. Sem ele, um volume de
    #   rede que some trava a thread da fila para sempre (ver `PRAZO_SEM_QUADRO_S`).
    parado = threading.Event()
    ultimo = [time.monotonic()]
    travou: list[bool] = []

    def vigiar() -> None:
        while not parado.wait(1.0):
            if time.monotonic() - ultimo[0] > PRAZO_SEM_QUADRO_S:
                travou.append(True)
                try:
                    proc.kill()
                except OSError:
                    pass
                return

    t_cao = threading.Thread(target=vigiar, daemon=True)
    t_cao.start()

    tam = w * h * 3
    janela: deque[np.ndarray] = deque(maxlen=2 * kmax + 1)
    d1, dz, sig = [], [], []
    D = {k: [] for k in ESCALAS}           # D_k indexado pelo quadro CENTRAL
    anterior = anterior_z = None
    n = 0
    while True:
        bruto = _ler_exato(proc.stdout, tam)
        if len(bruto) < tam:
            break
        ultimo[0] = time.monotonic()
        f = np.frombuffer(bruto, np.uint8).reshape(h, w, 3).astype(np.float32) / 255
        lum = f.mean(axis=2)
        z = (lum - lum.mean()) / (lum.std() + 1e-3)
        d1.append(0.0 if anterior is None else float(np.abs(f - anterior).mean()))
        dz.append(0.0 if anterior_z is None else float(np.abs(z - anterior_z).mean()))
        sig.append(float(lum.std()))
        janela.append(f)
        for k in ESCALAS:
            # quando chega o quadro n, o central com meia-janela k é n−k
            if n >= 2 * k:
                D[k].append(float(np.abs(janela[-1] - janela[-1 - 2 * k]).mean()))
        anterior, anterior_z = f, z
        n += 1
    parado.set()
    proc.stdout.close()
    try:
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)
    t_err.join(timeout=5)
    # ⛔⛔ ANTES do teste de `n == 0`, e é a ordem que importa: morto no meio, `n` é maior
    #    que zero e a série está PELA METADE. Seguir daria fronteiras plausíveis para meia
    #    mídia, gravadas no cache como se fossem a mídia inteira — e ninguém as refaria.
    if travou:
        raise DeteccaoFalhou(
            f"o ffmpeg travou lendo {arquivo.name} (nenhum quadro em "
            f"{PRAZO_SEM_QUADRO_S:.0f} s, no quadro {n}); a mídia pode estar num volume "
            f"que saiu do ar: {' | '.join(cauda)[-200:]}")
    if n == 0:
        raise DeteccaoFalhou(f"o ffmpeg não leu {arquivo.name}: {' | '.join(cauda)[-300:]}")
    series_D = {}
    for k in ESCALAS:
        arr = np.zeros(n, np.float32)
        vals = np.asarray(D[k], np.float32)
        arr[k:k + len(vals)] = vals
        series_D[k] = arr
    return {"n": n, "d1": np.asarray(d1, np.float32), "dz": np.asarray(dz, np.float32),
            "sig": np.asarray(sig, np.float32), "D": series_D, "scdet": scdet}


# ── os detectores (os do spike F0, com os mesmos números) ────────────────────

def _limiar(x: np.ndarray, t: int) -> float:
    janela = x[max(0, t - 24):t + 25]
    med = float(np.median(janela))
    mad = float(np.median(np.abs(janela - med)))
    return max(PISO_CORTE, med + C_MAD * 1.4826 * mad)


def _cortes_do_pixel(d1: np.ndarray, dz: np.ndarray) -> list[int]:
    saida = []
    for t in range(1, len(d1)):
        viz = np.concatenate([d1[max(1, t - 3):t], d1[t + 1:t + 4]])
        if viz.size and d1[t] > ISOLAMENTO * max(float(viz.max()), 1e-4) \
                and d1[t] > _limiar(d1, t) and dz[t] > DZ_MIN:
            saida.append(t)
    return saida


def _graduais(s: dict[str, Any], cortes: list[int]) -> list[dict]:
    d1, n = s["d1"], s["n"]
    acum = np.concatenate([[0.0], np.cumsum(d1)])
    achados: list[dict] = []
    for k in ESCALAS:
        D = s["D"][k]
        t = k
        while t < n - k:
            caminho = acum[t + k + 1] - acum[t - k + 1]
            lam = D[t] / caminho if caminho > 1e-6 else 0.0
            if D[t] > PISO_GRADUAL and lam > LAMBDA_MIN and all(abs(t - x) > k for x in cortes):
                ini = t
                while t < n - k and D[t] > PISO_GRADUAL * 0.7:
                    t += 1
                centro = ini + int(np.argmax(D[ini:t + 1]))
                achados.append({"inicio": max(0, centro - k), "fim": centro + k,
                                "medida": float(D[centro]), "k": k})
            t += 1
    # ⚠️ A mesma transição aparece em várias escalas. A EXTENSÃO sai da que mais a vê (maior
    #    D) — escolhendo pela menor, um dissolve de 36 quadros saía partido em dois. E o
    #    CENTRO é refinado dentro dela pela menor escala que passa do piso: MEDIDO, ficando
    #    com o centro do k=24, um dissolve de 12 centrado em 94 saía em 85.
    achados.sort(key=lambda a: -a["medida"])
    escolhidos: list[dict] = []
    for g in achados:
        if all(g["fim"] < a["inicio"] or g["inicio"] > a["fim"] for a in escolhidos):
            for k in ESCALAS:
                if k >= g["k"]:
                    break
                trecho = s["D"][k][g["inicio"]:g["fim"] + 1]
                if trecho.size and float(trecho.max()) > PISO_GRADUAL:
                    centro = g["inicio"] + int(np.argmax(trecho))
                    g["inicio"], g["fim"] = max(0, centro - k), centro + k
                    break
            meio = (g["inicio"] + g["fim"]) // 2
            g["tipo"] = "fade" if s["sig"][max(0, meio - 3):meio + 4].min() < 0.02 else "dissolve"
            if g["tipo"] == "fade":
                # ⭐ No fade o ponto de mudança é o quadro mais ESCURO (chapado), não o pico
                #   de diferença. MEDIDO: pelo pico, o centro saía até 18 quadros fora.
                ini = max(0, g["inicio"] - max(ESCALAS))
                g["centro"] = ini + int(np.argmin(s["sig"][ini:g["fim"] + max(ESCALAS)]))
            escolhidos.append(g)
    return escolhidos


def _cortes_do_scdet(achados: list[tuple[float, float]], taxa: Fraction) -> list[int]:
    tempos: list[float] = []
    for sc, tt in sorted(achados, key=lambda x: x[1]):
        if sc >= LIMIAR_SCDET and (not tempos or tt - tempos[-1] >= FUNDIR_SCDET_S):
            tempos.append(tt)
    return [round(tt * float(taxa)) for tt in tempos]


def detectar(arquivo: str | Path, taxa: Fraction) -> tuple[list[dict], dict[str, Any]]:
    """As fronteiras de `arquivo` — `[{quadro, fim, tipo, fonte, medida}]` — e as séries."""
    s = _passada(Path(arquivo))
    pixel = _cortes_do_pixel(s["d1"], s["dz"])
    cortes = sorted(set(pixel))
    for q in _cortes_do_scdet(s["scdet"], taxa):
        if all(abs(q - c) > RAIO_UNIAO for c in cortes):
            cortes.append(q)
    cortes.sort()
    fronteiras = [{"quadro": c, "fim": c + 1, "tipo": "corte",
                   "fonte": "pixel" if c in pixel else "scdet",
                   "medida": round(float(s["d1"][c]) if c < s["n"] else 0.0, 4)}
                  for c in cortes if 0 < c < s["n"]]
    graduais = _graduais(s, cortes)
    # ⛔ Um corte do scdet DENTRO de uma transição gradual é a mesma transição contada duas
    #    vezes (MEDIDO: ele dispara no meio de um fade para o preto).
    fronteiras = [f for f in fronteiras
                  if f["fonte"] != "scdet"
                  or not any(g["inicio"] - 2 <= f["quadro"] <= g["fim"] + 2 for g in graduais)]
    for g in graduais:
        fronteiras.append({"quadro": g.get("centro", (g["inicio"] + g["fim"]) // 2),
                           "fim": g["fim"], "tipo": g["tipo"], "fonte": "pixel",
                           "medida": round(g["medida"], 4)})
    fronteiras.sort(key=lambda f: f["quadro"])
    return fronteiras, s


# ── os trechos ───────────────────────────────────────────────────────────────

def _dividir(inicio: int, fim: int, d1: np.ndarray, taxa: Fraction) -> list[tuple[int, int]]:
    """Um trecho longo em pedaços de AÇÃO parecida: mais cortes onde há movimento."""
    dur = (fim - inicio) / float(taxa)
    movimento = float(d1[inicio:fim].sum())
    n = round(movimento / MOVIMENTO_POR_TRECHO)
    n = max(n, math.ceil(dur / TRECHO_MAX_S), 1)
    n = min(n, max(1, math.floor(dur / TRECHO_MIN_S)))
    if n <= 1:
        return [(inicio, fim)]
    acum = np.cumsum(d1[inicio:fim]) + 1e-9 * np.arange(fim - inicio)  # monotônico
    alvos = [acum[-1] * i / n for i in range(1, n)]
    pontos = [inicio + int(np.searchsorted(acum, a)) for a in alvos]
    # nenhum pedaço menor que o mínimo
    minimo = int(TRECHO_MIN_S * float(taxa))
    limites = [inicio]
    for p in pontos:
        if p - limites[-1] >= minimo and fim - p >= minimo:
            limites.append(p)
    limites.append(fim)
    return list(zip(limites[:-1], limites[1:]))


def trechos(fronteiras: list[dict], s: dict[str, Any], taxa: Fraction) -> list[Trecho]:
    n, d1 = s["n"], s["d1"]
    bruto = not any(f["tipo"] == "corte" for f in fronteiras)
    marcos = [(0, "inicio")] + [(f["quadro"], "mudanca" if bruto else f["tipo"])
                                for f in fronteiras]
    saida: list[Trecho] = []
    for i, (ini, entrada) in enumerate(marcos):
        fim = marcos[i + 1][0] if i + 1 < len(marcos) else n
        if fim <= ini:
            continue
        for j, (a, b) in enumerate(_dividir(ini, fim, d1, taxa)):
            saida.append(Trecho(inicio=a, fim=b, entrada=entrada if j == 0 else "divisao",
                                movimento=round(float(d1[a:b].sum()), 3)))
    for t in saida:
        t.planos = [t.inicio]
    saida = _juntar_curtos(saida, taxa)
    if bruto and saida:
        saida[0].cabeca = True
    return saida


def _juntar_curtos(lista: list[Trecho], taxa: Fraction) -> list[Trecho]:
    """Junta trechos curtos ao anterior até `TRECHO_JUNTAR_S`, sem passar de
    `PLANOS_POR_TRECHO` planos — o grupo guarda o início de cada plano."""
    minimo = TRECHO_JUNTAR_S * float(taxa)
    saida: list[Trecho] = []
    for t in lista:
        ultimo = saida[-1] if saida else None
        curto_o_ultimo = ultimo is not None and ultimo.fim - ultimo.inicio < minimo
        curto_este = t.fim - t.inicio < minimo
        if ultimo is not None and (curto_o_ultimo or curto_este)                 and len(ultimo.planos or []) + len(t.planos or []) <= PLANOS_POR_TRECHO:
            ultimo.fim = t.fim
            ultimo.movimento = round(ultimo.movimento + t.movimento, 3)
            ultimo.planos = [*(ultimo.planos or []), *(t.planos or [])]
            continue
        saida.append(t)
    return saida


# ── o estágio de cache ───────────────────────────────────────────────────────

def ler(midia: _cache.Midia) -> dict[str, Any] | None:
    """O `cortes.json` desta mídia, se feito com a receita de HOJE."""
    if midia.precisa_refazer("cortes", ASSINATURA):
        return None
    dados = midia._ler_json(midia.arquivo(ARQUIVO)) if midia.existe else {}
    return dados if dados.get("trechos") is not None else None


def de_uma(midia: _cache.Midia, arquivo: str | Path, taxa: Fraction,
           forcar: bool = False) -> dict[str, Any]:
    """Detecta (ou lê do cache) as fronteiras e os trechos desta mídia."""
    if not forcar:
        pronto = ler(midia)
        if pronto is not None:
            return pronto
    fronteiras, s = detectar(arquivo, taxa)
    lista = trechos(fronteiras, s, taxa)
    dados = {
        "quadros": s["n"], "taxa": str(taxa),
        "bruto": not any(f["tipo"] == "corte" for f in fronteiras),
        "fronteiras": fronteiras,
        "trechos": [asdict(t) for t in lista],
        # Procedência, como manda a casa: leitura de imagem, com o número que sustenta.
        "confianca": "inferido", "fonte": "visual",
    }
    _cache.escrever_atomico(midia.pasta / ARQUIVO,
                            json.dumps(dados, ensure_ascii=False, indent=1).encode("utf-8"))
    midia.registrar_gerador("cortes", ASSINATURA)
    log.info("cortes de %s: %d fronteira(s), %d trecho(s)%s", midia.nome or midia.chave[:12],
             len(fronteiras), len(lista), " (bruto)" if dados["bruto"] else "")
    return dados
