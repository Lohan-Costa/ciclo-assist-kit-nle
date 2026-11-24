"""O alinhador forçado (CTC): ONDE cada palavra que o Whisper ouviu está no som — a borda da palavra no nível do Premiere.

⭐⭐ Fase L1 do plano `docs/plano/2026-11-11-alinhador-por-palavra.md`. O Whisper dá o TEXTO (bom) e um tempo aproximado
(ruim: em fala de set erra a palavra em até ~1 s). Um modelo acústico CTC dá, a cada 20 ms, a probabilidade de cada letra;
o texto do Whisper vira uma sequência de letras, e um Viterbi em numpy acha o caminho que a emite. É o princípio do
alinhador Kaldi que o Resolve só roda em inglês (banco `transversal/transcricao-por-palavra.md`).

## As decisões, todas medidas ou do autor

- **Modelo:** Omnilingual ASR 300M CTC v2 int8 (Meta, 1600 línguas; o release `asr-models` do sherpa-onnx). Empatou com o
  wav2vec2 PT large em PT e cobre o inglês: um modelo para todos (autor, 2026-11-11). Sem torch: onnxruntime.
- ⛔ **Só no Mac** (autor): não há CTC pequeno bom em PT, e o de 290 MB sobe a ~850 MB com a janela ≤ 6 s — não cabe no
  notebook com o Media Composer aberto (o SigLIP caiu lá com 169 MB livres). No Windows o estágio diz `nao_medido` e tudo
  segue como antes; levar o pedido ao Mac pela rede é a L4.
- **A regra do juiz de ouvido** (18 bordas cegas, autor): o início é o do CTC **menos 41 ms** (o desvio fixo medido: +36 ms
  no sintético, +41 ms no take real); o fim é o do CTC **mais 60 ms** (a última letra sai cedo, −134 ms de mediana) e
  depois o `voz` o leva até onde a voz acaba na lapela — `max(voz, CTC + 60 ms)`. 13 de 17 a ≤ 1 quadro do ouvido, 0
  cortando a voz (Premiere 10 de 17).
- **Janela ≤ 6 s:** cada segundo de janela custa ~30 MB no onnxruntime; uma fala longa é repartida no maior vão entre as
  palavras. A janela vai 0,5 s além da fala, sem entrar na fala vizinha (o CTC forçado põe a palavra onde houver voz).
- **Sob demanda** (autor): roda quando a transcrição de uma mídia é pedida; nada de fila no acervo.
- **Estágio próprio:** ligar o alinhador NÃO invalida transcrição nenhuma. Sem ele, fica o tempo do Whisper, dito.

Guardado CRU (o tempo do CTC); a regra (−41/+60 ms) é aplicada ao LER (`bordas`), e a assinatura a inclui: mudou a regra,
o estágio refaz — barato, ~4,5 % da duração no Mac mini.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from typing import Any, Callable

import numpy as np

log = logging.getLogger("cicloassist.midia.alinhamento")

SR = 16000
PASTA_DO_MODELO = "omnilingual-asr-300M-ctc-v2-int8"
#: O que o release do sherpa-onnx traz (`sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05`).
ARQUIVOS_DO_MODELO = ("model.int8.onnx", "tokens.txt")
URL_DO_MODELO = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
                 "sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05.tar.bz2")

DESVIO_INICIO_S = 0.041
FOLGA_FIM_S = 0.060
MARGEM_S = 0.5
JANELA_MAX_S = 6.0
#: Palavras das falas VIZINHAS que vão junto como contexto, e são descartadas depois. ⛔ Sem elas, a janela que entra
#: no começo da fala seguinte (o Whisper erra onde ela começa) faz o CTC esticar a última letra por cima da voz do
#: outro: medido no take C4 P1-T001, "secretária." +660 ms e "toda." +120 ms além do ouvido.
CONTEXTO = 2
#: …e só as que o Whisper põe a até 1 s da borda da janela: sem o teto, o contexto atravessava silêncios longos e o
#: custo do take de 9 min foi de 26 s / 1,3 GB a 100 s / 2,8 GB.
CONTEXTO_MAX_S = 1.0
THREADS = 4

ASSINATURA = {"modelo": PASTA_DO_MODELO, "versao": 2, "margem_s": MARGEM_S, "janela_max_s": JANELA_MAX_S,
              "contexto": CONTEXTO, "contexto_max_s": CONTEXTO_MAX_S}
ARQUIVO = "alinhamento.json"

NAO_MEDIDO = "nao_medido"


class AlinhadorIndisponivel(RuntimeError):
    """Não há como alinhar aqui: o motivo, em português, para o log e a procedência."""


# ── onde pode rodar, e o modelo ──────────────────────────────────────────────

def motivo_para_nao_rodar() -> str:
    """`""` se pode rodar nesta máquina; senão o porquê."""
    if sys.platform == "win32":
        return "o alinhador por palavra roda no Mac (no notebook com o Media Composer não cabe)"
    if not all((pasta_do_modelo() / a).is_file() for a in ARQUIVOS_DO_MODELO):
        return f"o modelo do alinhador não está em {pasta_do_modelo()} (tools/instalar_alinhador.py)"
    try:
        import onnxruntime  # noqa: F401, PLC0415
    except ImportError:
        return "o onnxruntime não está instalado"
    return ""


def pasta_do_modelo() -> Path:
    """`CICLOASSIST_ALINHADOR` (desenvolvimento) → `config.json` › `alinhador` (o modelo no SSD) → a pasta de modelos
    do produto, ao lado do de imagem. ⭐ A chave do config vale para o app aberto pelo Finder, que não herda o ambiente."""
    if os.environ.get("CICLOASSIST_ALINHADOR"):
        return Path(os.environ["CICLOASSIST_ALINHADOR"])
    from ..servico import config  # noqa: PLC0415
    escolhida = config.ler().get("alinhador")
    if isinstance(escolhida, str) and escolhida.strip():
        return Path(escolhida)
    return config.pasta() / "modelos" / PASTA_DO_MODELO


class Modelo:
    """A sessão do Omnilingual. Entrada: onda crua a 16 kHz normalizada; saída: log-probabilidade por letra a cada 20 ms.

    ⚠️ Sem prepack e sem arena (banco §7): com eles a sessão sobe ~2× o arquivo e não devolve a memória. Carregar custa
    ~0,4–0,7 s, então a sessão é de UM master (quem chama a solta): residente no serviço seriam ~600 MB parados."""

    branco = 0

    def __init__(self, pasta: Path | None = None):
        import onnxruntime as ort  # noqa: PLC0415
        pasta = pasta or pasta_do_modelo()
        so = ort.SessionOptions()
        so.intra_op_num_threads = THREADS
        so.enable_cpu_mem_arena = False
        so.add_session_config_entry("session.disable_prepacking", "1")
        self.s = ort.InferenceSession(str(pasta / "model.int8.onnx"), so, providers=["CPUExecutionProvider"])
        self.entrada = self.s.get_inputs()[0].name
        self.voc: dict[str, int] = {}
        for ln in (pasta / "tokens.txt").read_text(encoding="utf-8").splitlines():
            p = ln.rsplit(" ", 1)
            if len(p) == 2:
                self.voc[p[0]] = int(p[1])
        self.separador = self.voc.get("|")

    def logprobs(self, x: np.ndarray) -> np.ndarray:
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        lg = self.s.run(None, {self.entrada: x[None].astype(np.float32)})[0][0]
        return lg - np.logaddexp.reduce(lg, axis=1, keepdims=True)

    def tokens(self, palavra: str) -> list[int]:
        return [self.voc[c] for c in palavra.lower() if c in self.voc]


def limpa(palavra: str) -> str:
    """A palavra como vai ao modelo: sem pontuação (o editor continua vendo a escrita)."""
    return re.sub(r"[^\w'-]", "", unicodedata.normalize("NFC", palavra)).strip("-'")


# ── o Viterbi ────────────────────────────────────────────────────────────────

def viterbi(lp: np.ndarray, seq: np.ndarray, branco: int) -> np.ndarray | None:
    """CTC forçado: o caminho mais provável que emite `seq`. O estado de cada quadro (2k+1 = token k), ou `None`."""
    T, S = lp.shape[0], 2 * len(seq) + 1
    if T < len(seq):
        return None
    ext = np.full(S, branco)
    ext[1::2] = seq
    em = lp[:, ext]
    pula = np.zeros(S, bool)
    pula[3::2] = ext[3::2] != ext[1:-2:2]
    NEG = -1e30
    dp = np.full(S, NEG)
    dp[0], dp[1] = em[0, 0], em[0, 1]
    bp = np.zeros((T, S), np.int8)
    idx = np.arange(S)
    for t in range(1, T):
        b = np.concatenate([[NEG], dp[:-1]])
        c = np.where(pula, np.concatenate([[NEG, NEG], dp[:-2]]), NEG)
        st = np.stack([dp, b, c])
        k = st.argmax(0)
        dp = st[k, idx] + em[t]
        bp[t] = k
    s = S - 1 if S == 1 or dp[S - 1] >= dp[S - 2] else S - 2
    if dp[s] < NEG / 2:
        return None
    estados = np.empty(T, np.int32)
    for t in range(T - 1, -1, -1):
        estados[t] = s
        s -= int(bp[t, s])  # ⚠️ numpy 2: int + int8 dá int8 (NEP 50) e estoura sem o int()
    return estados


def alinhar_trecho(modelo, x: np.ndarray, palavras: list[str], t0: float = 0.0) -> list[tuple[float, float] | None]:
    """Uma janela de som e as palavras que ela contém → `(inicio, fim)` CRUS do CTC de cada uma (`None` = sem letra)."""
    seq: list[int] = []
    dono: list[int] = []
    for i, w in enumerate(palavras):
        tk = modelo.tokens(limpa(w))
        if not tk:
            continue
        if modelo.separador is not None and seq:
            seq.append(modelo.separador)
            dono.append(-1)
        seq += tk
        dono += [i] * len(tk)
    saida: list[tuple[float, float] | None] = [None] * len(palavras)
    if not seq or len(x) < SR // 10:
        return saida
    lp = modelo.logprobs(x)
    est = viterbi(lp, np.array(seq), modelo.branco)
    if est is None:
        return saida
    passo = len(x) / SR / lp.shape[0]
    ini: dict[int, int] = {}
    fim: dict[int, int] = {}
    for t, s in enumerate(est):
        if s % 2 == 0 or dono[s // 2] < 0:
            continue
        i = dono[s // 2]
        ini.setdefault(i, t)
        fim[i] = t + 1
    for i in ini:
        saida[i] = (round(t0 + ini[i] * passo, 3), round(t0 + fim[i] * passo, 3))
    return saida


# ── as janelas ───────────────────────────────────────────────────────────────

def janelas(falas: list[dict[str, Any]], duracao: float) -> list[tuple[list[tuple[int, int]], int, int, float, float]]:
    """As janelas a alinhar: `(palavras, p, q, início, fim)`. `palavras` é a sequência `(fala, índice)` que vai ao modelo
    (com o contexto das vizinhas); só `palavras[p:q]` são desta janela. Uma por fala; a fala longa, repartida no maior vão.

    Pura. A janela vai `MARGEM_S` além da primeira e da última palavra (do contexto, quando há)."""
    todas = [(i, k) for i, f in enumerate(falas) for k, w in enumerate(f.get("palavras") or [])
             if w.get("t") is not None and w.get("fim") is not None]
    pos = {ik: n for n, ik in enumerate(todas)}
    w = lambda n: falas[todas[n][0]]["palavras"][todas[n][1]]  # noqa: E731
    saida = []
    for i, f in enumerate(falas):
        ns = [pos[(i, k)] for k in range(len(f.get("palavras") or [])) if (i, k) in pos]
        if not ns:
            continue
        pal = [w(n) for n in ns]
        for p, q in _repartir(pal, 0, len(pal)):
            lo, hi = max(0, ns[p] - CONTEXTO), min(len(todas), ns[q - 1] + 1 + CONTEXTO)
            while lo < ns[p] and float(w(ns[p])["t"]) - float(w(lo)["fim"]) > CONTEXTO_MAX_S:
                lo += 1
            while hi > ns[q - 1] + 1 and float(w(hi - 1)["t"]) - float(w(ns[q - 1])["fim"]) > CONTEXTO_MAX_S:
                hi -= 1
            a = max(0.0, float(w(lo)["t"]) - MARGEM_S)
            b = min(duracao, float(w(hi - 1)["fim"]) + MARGEM_S)
            if b > a:
                saida.append((todas[lo:hi], ns[p] - lo, ns[q - 1] + 1 - lo, a, b))
    return saida


def _repartir(pal: list[dict[str, Any]], p: int, q: int) -> list[tuple[int, int]]:
    """Corta `pal[p:q]` no maior vão até cada pedaço caber em `JANELA_MAX_S` (com a margem)."""
    if q - p <= 1 or float(pal[q - 1]["fim"]) - float(pal[p]["t"]) + 2 * MARGEM_S <= JANELA_MAX_S:
        return [(p, q)]
    vaos = [float(pal[k]["t"]) - float(pal[k - 1]["fim"]) for k in range(p + 1, q)]
    k = p + 1 + int(np.argmax(vaos))
    return _repartir(pal, p, k) + _repartir(pal, k, q)


# ── o estágio no cache ───────────────────────────────────────────────────────

def _impressao_da_transcricao(midia) -> str:
    try:
        return hashlib.sha1(midia.arquivo("transcricao.json").read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def impressao(midia) -> str:
    """De que alinhamento o `voz.json` depende (`""` = nenhum)."""
    try:
        return hashlib.sha1(midia.arquivo(ARQUIVO).read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def ler(midia) -> dict[str, Any]:
    """O `alinhamento.json` SE ainda vale (receita de hoje e a mesma transcrição); senão `{}`."""
    dados = midia._ler_json(midia.arquivo(ARQUIVO))
    if (not dados or dados.get("assinatura") != ASSINATURA
            or dados.get("transcricao") != _impressao_da_transcricao(midia)):
        return {}
    return dados


def carregar_som(wav: Path) -> np.ndarray:
    from .audio import achar_ffmpeg  # noqa: PLC0415
    raw = subprocess.run([achar_ffmpeg(), "-v", "error", "-i", str(wav), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True, timeout=600).stdout
    return np.frombuffer(raw, np.float32).copy()


def alinhar(falas: list[dict[str, Any]], x: np.ndarray, modelo,
            andando: Callable[[float], None] | None = None) -> list[list[list[float] | None]]:
    """Pura (com o modelo dado): por fala, por palavra, `[inicio, fim]` CRU do CTC ou `None`. Mesma ordem."""
    saida: list[list[list[float] | None]] = [[None] * len(f.get("palavras") or []) for f in falas]
    js = janelas(falas, len(x) / SR)
    for n, (seq, p, q, a, b) in enumerate(js):
        res = alinhar_trecho(modelo, x[int(a * SR):int(b * SR)],
                             [str(falas[i]["palavras"][k].get("palavra") or "") for i, k in seq], a)
        for (i, k), r in zip(seq[p:q], res[p:q]):
            saida[i][k] = list(r) if r else None
        if andando and n % 10 == 0:
            andando(n / max(len(js), 1))
    return saida


def garantir(midia, wav: Path, forcar: bool = False, andando: Callable[[float], None] | None = None,
             modelo=None) -> dict[str, Any]:
    """Deixa `alinhamento.json` no cache e o devolve. Barato quando já está: só lê.

    Sem como rodar aqui: `{"nao_medido": motivo}`, sem gravar (outra máquina pode alinhar a mesma mídia)."""
    if not forcar and (pronto := ler(midia)):
        return pronto
    if modelo is None:
        if motivo := motivo_para_nao_rodar():
            return {NAO_MEDIDO: motivo}
        modelo = Modelo()
    falas = midia.ler_transcricao()
    x = carregar_som(Path(wav))
    palavras = alinhar(falas, x, modelo, andando)
    total = sum(len(p) for p in palavras)
    feitas = sum(1 for p in palavras for w in p if w)
    dados = {"assinatura": ASSINATURA, "transcricao": _impressao_da_transcricao(midia),
             "palavras": palavras, "alinhadas": feitas, "total": total}
    from .cache import escrever_atomico  # noqa: PLC0415
    escrever_atomico(midia.pasta / ARQUIVO, json.dumps(dados, ensure_ascii=False).encode("utf-8"))
    log.info("alinhamento de %s: %d de %d palavras", midia.chave, feitas, total)
    return dados


def bordas(dados: dict[str, Any] | None, falas: list[dict[str, Any]]) -> list[list[tuple[float, float] | None]] | None:
    """⭐ A regra do juiz de ouvido sobre o CTC cru: `(inicio − 41 ms, fim + 60 ms)` por palavra. `None` = sem alinhamento.

    ⛔ Só se as contagens baterem com a transcrição (alinhamento de outra transcrição não se cola calado)."""
    cru = (dados or {}).get("palavras")
    if not cru or len(cru) != len(falas):
        return None
    saida = []
    for f, ws in zip(falas, cru):
        if len(ws) != len(f.get("palavras") or []):
            return None
        saida.append([(max(0.0, round(w[0] - DESVIO_INICIO_S, 3)), round(w[1] + FOLGA_FIM_S, 3)) if w else None
                      for w in ws])
    return saida
