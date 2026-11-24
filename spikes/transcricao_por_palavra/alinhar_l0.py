"""L0 do alinhador por palavra: CTC forçado em numpy sobre modelos ONNX (plano docs/plano/2026-11-11-alinhador-por-palavra.md).

    python alinhar_l0.py <modelo> <wav> <saida.json> [--texto gabarito.json | --whisper nosso.json]

<modelo>: w2v_pt | w2v_pt_int8 | omni | nemo_pt. Os modelos moram em $MODELOS_L0 (fora do Git, no SSD).
--texto  : alinha o texto EXATO do gabarito no arquivo inteiro (mede só o alinhador).
--whisper: alinha o texto do nosso ASR, fala a fala, numa janela em volta de cada fala (o caso real).
Sem torch: ffmpeg decodifica, onnxruntime infere, o Viterbi é numpy.
"""
import json, os, re, resource, subprocess, sys, time, unicodedata
import numpy as np
import onnxruntime as ort

MOD = os.environ.get("MODELOS_L0", "/Volumes/SSD/MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/"
                     "2026-11-11 TRANSCRICAO POR PALAVRA/modelos_l0")
SR = 16000


def carregar(wav):
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(raw, np.float32).copy()


def palavras_de(texto):
    """Palavras como o editor as vê (com pontuação), e a forma limpa que vai ao modelo."""
    out = []
    for w in texto.split():
        limpa = re.sub(r"[^\w'-]", "", unicodedata.normalize("NFC", w)).strip("-'")
        if limpa:
            out.append((w, limpa))
    return out


# ---------------------------------------------------------------- modelos
class Modelo:
    passo = 0.02        # segundos por quadro de saída
    branco = 0
    def __init__(self, arq, threads=4):
        so = ort.SessionOptions(); so.intra_op_num_threads = int(os.environ.get("L0_THREADS", threads))
        if os.environ.get("L0_SEM_ARENA"): so.enable_cpu_mem_arena = False
        self.s = ort.InferenceSession(arq, so, providers=["CPUExecutionProvider"])
    def tokens(self, palavra):  # -> lista de ids (ou None se não der)
        raise NotImplementedError
    separador = None    # id entre palavras, ou None


class W2V(Modelo):
    def __init__(self, arq):
        super().__init__(arq)
        self.voc = json.load(open(f"{MOD}/w2v_pt/vocab.json"))
        self.branco = self.voc["<pad>"]; self.separador = self.voc["|"]
    def logprobs(self, x):
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        lg = self.s.run(None, {"input_values": x[None]})[0][0]
        return lg - np.logaddexp.reduce(lg, axis=1, keepdims=True)
    def tokens(self, w):
        return [self.voc[c] for c in w.lower() if c in self.voc]


class Omni(Modelo):
    def __init__(self, arq):
        super().__init__(arq)
        d = f"{MOD}/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05"
        self.voc = {}
        for ln in open(f"{d}/tokens.txt", encoding="utf-8"):
            p = ln.rstrip("\n").rsplit(" ", 1)
            if len(p) == 2: self.voc[p[0]] = int(p[1])
        self.branco = 0; self.separador = self.voc["|"]
    def logprobs(self, x):
        x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
        lg = self.s.run(None, {"x": x[None]})[0][0]
        return lg - np.logaddexp.reduce(lg, axis=1, keepdims=True)
    def tokens(self, w):
        return [self.voc[c] for c in w.lower() if c in self.voc]


def _mel_slaney(n_fft=512, n_mels=80, sr=SR, fmin=0.0, fmax=8000.0):
    def hz2mel(f):
        f = np.asarray(f, float); m = f / (200.0 / 3)
        return np.where(f >= 1000, 15 + np.log(np.maximum(f, 1e-10) / 1000) / (np.log(6.4) / 27), m)
    def mel2hz(m):
        m = np.asarray(m, float); f = m * (200.0 / 3)
        return np.where(m >= 15, 1000 * np.exp((np.log(6.4) / 27) * (m - 15)), f)
    fft = np.linspace(0, sr / 2, n_fft // 2 + 1)
    pts = mel2hz(np.linspace(hz2mel(fmin), hz2mel(fmax), n_mels + 2))
    fdiff = np.diff(pts); ramps = pts[:, None] - fft[None, :]
    lo = -ramps[:-2] / fdiff[:-1, None]; hi = ramps[2:] / fdiff[1:, None]
    w = np.maximum(0, np.minimum(lo, hi))
    return w * (2.0 / (pts[2:n_mels + 2] - pts[:n_mels]))[:, None]


class NeMo(Modelo):
    passo = 0.08
    def __init__(self, arq):
        super().__init__(arq)
        d = f"{MOD}/sherpa-onnx-nemo-stt_pt_fastconformer_hybrid_large_pc-int8"
        self.voc = {}
        for ln in open(f"{d}/tokens.txt", encoding="utf-8"):
            p = ln.rstrip("\n").rsplit(" ", 1)
            self.voc[p[0]] = int(p[1])
        self.branco = self.voc["<blk>"]; self.fb = _mel_slaney()
    def logprobs(self, x):
        x = np.concatenate([x[:1], x[1:] - 0.97 * x[:-1]])
        x = np.pad(x, 256)  # center=True
        win = np.pad(np.hanning(400), (56, 56))  # torch.hann_window(periodic=False), centrada no n_fft
        n = 1 + (len(x) - 512) // 160
        fr = np.lib.stride_tricks.as_strided(x, (n, 512), (x.strides[0] * 160, x.strides[0]))
        p = np.abs(np.fft.rfft(fr * win, 512)) ** 2
        m = np.log(p @ self.fb.T + 2 ** -24).T  # 80 x n
        m = (m - m.mean(1, keepdims=True)) / (m.std(1, keepdims=True) + 1e-5)
        lp = self.s.run(None, {"audio_signal": m[None].astype(np.float32),
                               "length": np.array([m.shape[1]], np.int64)})[0][0]
        return lp
    def tokens(self, w):
        s = "▁" + w; out = []; i = 0
        while i < len(s):
            for j in range(len(s), i, -1):
                if s[i:j] in self.voc: out.append(self.voc[s[i:j]]); i = j; break
            else:
                i += 1  # caractere fora do vocabulário
        return out


def abrir(nome):
    if nome == "w2v_pt": return W2V(f"{MOD}/w2v_pt/model.onnx")
    if nome == "w2v_pt_int8": return W2V(f"{MOD}/w2v_pt/model.int8.onnx")
    if nome == "omni": return Omni(f"{MOD}/sherpa-onnx-omnilingual-asr-1600-languages-300M-ctc-v2-int8-2026-02-05/model.int8.onnx")
    if nome == "nemo_pt": return NeMo(f"{MOD}/sherpa-onnx-nemo-stt_pt_fastconformer_hybrid_large_pc-int8/model.int8.onnx")
    raise SystemExit(f"modelo desconhecido: {nome}")


# ---------------------------------------------------------------- o alinhamento
def viterbi(lp, seq, branco):
    """CTC forçado: o caminho mais provável que emite `seq`. Devolve o estado de cada quadro (2k+1 = token k)."""
    T = lp.shape[0]; S = 2 * len(seq) + 1
    ext = np.full(S, branco); ext[1::2] = seq
    em = lp[:, ext]
    pula = np.zeros(S, bool); pula[3::2] = ext[3::2] != ext[1:-2:2]
    NEG = -1e30
    dp = np.full(S, NEG); dp[0] = em[0, 0]; dp[1] = em[0, 1]
    bp = np.zeros((T, S), np.int8)
    for t in range(1, T):
        a = dp; b = np.concatenate([[NEG], dp[:-1]]); c = np.concatenate([[NEG, NEG], dp[:-2]])
        c = np.where(pula, c, NEG)
        st = np.stack([a, b, c]); k = st.argmax(0); dp = st[k, np.arange(S)] + em[t]; bp[t] = k
    s = S - 1 if dp[S - 1] >= dp[S - 2] else S - 2
    if dp[s] < NEG / 2: return None
    estados = np.empty(T, np.int32)
    for t in range(T - 1, -1, -1):
        estados[t] = s; s -= int(bp[t, s])
    return estados


def alinhar(m, x, palavras, t0=0.0):
    """palavras: [(como_escrita, limpa)]. Devolve [(inicio, fim, como_escrita)] em segundos do arquivo."""
    seq = []; dono = []
    for i, (_, w) in enumerate(palavras):
        tk = m.tokens(w)
        if not tk: continue
        if m.separador is not None and seq: seq.append(m.separador); dono.append(-1)
        seq += tk; dono += [i] * len(tk)
    if not seq: return []
    lp = m.logprobs(x)
    est = viterbi(lp, np.array(seq), m.branco)
    if est is None: return []
    passo = len(x) / SR / lp.shape[0]
    tok = np.where(est % 2 == 1, est // 2, -1)
    ini = {}; fim = {}
    for t, k in enumerate(tok):
        if k < 0 or dono[k] < 0: continue
        i = dono[k]; ini.setdefault(i, t); fim[i] = t + 1
    return [(t0 + ini[i] * passo, t0 + fim[i] * passo, palavras[i][0]) for i in sorted(ini)]


# ---------------------------------------------------------------- camada 3: a energia ajusta a borda
H = 0.005  # passo do envelope

def envelope(x):
    n = int(SR * H); w = 2 * n
    k = (len(x) - w) // n + 1
    fr = np.lib.stride_tricks.as_strided(x, (k, w), (x.strides[0] * n, x.strides[0]))
    return 10 * np.log10((fr.astype(np.float64) ** 2).mean(1) + 1e-12)  # quadro j cobre [j*H, j*H+2H)


PONTE = float(os.environ.get("L0_PONTE", "0.12"))   # silêncio curto DENTRO da palavra (oclusão de /t/, /k/, /p/)
PAUSA = float(os.environ.get("L0_PAUSA", "0.35"))   # a ponte só vale antes de pausa (fim de fala): é onde o corte cai
VALE = float(os.environ.get("L0_VALE", "9"))     # o vale entre coladas fica até isto antes do início do CTC seguinte


def canais(wav, quais):
    """Os canais pedidos, cada um a 16 kHz (a lapela de cada um: a energia da MISTURA não cai na pausa de um set)."""
    n = int(subprocess.run(["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries", "stream=channels",
                            "-of", "csv=p=0", wav], capture_output=True, text=True).stdout.strip())
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", wav, "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True, check=True).stdout
    y = np.frombuffer(raw, np.float32).reshape(-1, n).T
    return [y[c].copy() for c in quais]


ABAIXO = float(os.environ.get("L0_ABAIXO", "30"))
ACIMA = float(os.environ.get("L0_ACIMA", "15"))


def refinar(res, x, abaixo_do_pico=None, acima_do_piso=None, alcance=0.6, lapelas=None):
    """Leva cada borda do CTC até onde a energia some (pausa) ou ao vale entre duas palavras coladas.
    Com `lapelas`, cada palavra usa o envelope do canal DOMINANTE nela (o microfone de quem fala)."""
    if not res: return res
    abaixo_do_pico = ABAIXO if abaixo_do_pico is None else abaixo_do_pico
    acima_do_piso = ACIMA if acima_do_piso is None else acima_do_piso
    envs = [envelope(c) for c in lapelas] if lapelas else [envelope(x)]
    m = min(len(v) for v in envs); envs = [v[:m] for v in envs]
    pisos = [max(np.percentile(v, 5), -100.0) for v in envs]
    j = lambda t: int(np.clip(round(t / H), 0, m - 1))
    a = [r[0] for r in res]; b = [r[1] for r in res]; n = len(res)
    ini = list(a); fim = list(b); cola_dir = [False] * n
    dono = []
    for i in range(n):
        sl = slice(j(a[i]), max(j(b[i]), j(a[i]) + 1))
        dono.append(int(np.argmax([np.mean(10 ** (v[sl] / 10)) for v in envs])))
    for i in range(n):
        e = envs[dono[i]]; piso = pisos[dono[i]]
        pico = e[j(a[i]):max(j(b[i]), j(a[i]) + 1)].max()
        thr = max(piso + acima_do_piso, pico - abaixo_do_pico)
        L = b[i - 1] if i else max(0.0, a[i] - alcance); R = a[i + 1] if i + 1 < n else b[i] + alcance
        L = max(L, a[i] - alcance); R = min(R, b[i] + alcance)
        k = j(a[i])
        while k - 1 >= j(L) and e[k - 1] > thr: k -= 1
        ini[i] = k * H
        k = j(b[i])
        while True:
            while k + 1 <= j(R) and e[k] > thr: k += 1
            antes_de_pausa = i + 1 == n or a[i + 1] - b[i] > PAUSA
            if k >= j(R) or PONTE <= 0 or not antes_de_pausa: break
            volta = [q for q in range(k + 1, min(j(R), k + int(PONTE / H)) + 1) if e[q] > thr]
            if not volta: break
            k = volta[0]
        fim[i] = k * H
        if i + 1 < n and k >= j(R): cola_dir[i] = True
    for i in range(n - 1):
        # colada: a energia não cai entre as duas (ou as bordas se cruzaram) -> borda no vale entre elas
        if cola_dir[i] or fim[i] >= ini[i + 1]:
            lo, hi = sorted((max(j(b[i]), j(a[i + 1] - VALE)), j(a[i + 1])))
            e = envs[dono[i]] + envs[dono[i + 1]] if dono[i] != dono[i + 1] else envs[dono[i]]
            v = (lo + int(np.argmin(e[lo:hi + 1]))) * H if hi > lo else a[i + 1]
            fim[i] = ini[i + 1] = v
    return [(ini[i], fim[i], res[i][2]) for i in range(n)]


def main():
    nome, wav, saida = sys.argv[1:4]
    modo, fonte = sys.argv[4], sys.argv[5]
    t = time.time(); m = abrir(nome); t_carga = time.time() - t
    x = carregar(wav); dur = len(x) / SR
    t = time.time(); res = []
    if modo == "--texto":
        g = json.load(open(fonte))
        res = alinhar(m, x, palavras_de(" ".join(w["palavra"] for w in g)))
    else:
        falas = json.load(open(fonte))["falas"]
        for i, f in enumerate(falas):
            a = max(0.0, f["inicio"] - 0.5, falas[i - 1]["fim"] if i else 0.0)
            b = min(dur, f["fim"] + 0.5, falas[i + 1]["inicio"] if i + 1 < len(falas) else dur)
            if i + 1 < len(falas): b = max(b, f["fim"])
            res += alinhar(m, x[int(a * SR):int(b * SR)], palavras_de(f["texto"]), a)
    lap = None
    if "--lapelas" in sys.argv:
        lap = canais(sys.argv[sys.argv.index("--lapelas") + 2], [int(c) for c in sys.argv[sys.argv.index("--lapelas") + 1].split(",")])
    if "--energia" in sys.argv: res = refinar(res, x, lapelas=lap)
    t_alinhar = time.time() - t
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / (1 if sys.platform == "darwin" else 1 / 1024) / 1e6
    json.dump({"modelo": nome + ("+energia" if "--energia" in sys.argv else "") + ("(lapelas)" if "--lapelas" in sys.argv else ""), "modo": modo, "audio_s": dur, "carga_s": t_carga, "alinhar_s": t_alinhar,
               "pico_mb": rss, "palavras": [{"t": a, "fim": b, "palavra": w} for a, b, w in res]},
              open(saida, "w"), ensure_ascii=False, indent=1)
    print(f"{nome} {modo}: {len(res)} palavras, áudio {dur:.0f} s, carga {t_carga:.1f} s, alinhar {t_alinhar:.1f} s, "
          f"pico {rss:.0f} MB")


if __name__ == "__main__":
    main()
