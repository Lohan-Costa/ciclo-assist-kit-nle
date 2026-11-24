"""A borda real da voz, medida na forma de onda da LAPELA de cada ator, para corrigir o tempo por palavra do ASR.

    python spikes/edicao_de_cena/bordas.py --medir

O ASR estima a borda: 77% das palavras da C07 estão coladas à seguinte, e 106 duram mais de 0,8 s. Aqui o início da primeira palavra e o fim da última
de cada segmento são procurados no envelope da lapela de quem fala, em janelas de 10 ms.

⛔ Medido em C07_P02-002: na MISTURA não dá (o piso alto faz a voz "continuar" sempre; a primeira versão bateu no limite de busca em toda borda e piorou contra o
editor humano). Na lapela, a Personagem F some no quadro 1200 e o Personagem G entra no 1204, um respiro real que o ASR não via.

Sem modelo. O resultado de cada take é guardado na pasta de saída do fluxo.
"""

from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import numpy as np

JANELA_S = 0.010
TAXA = 16000
#: Voz é o que passa disto acima do piso de sala da lapela (10 dB). Medido em C07_P02-002: na pausa real entre dois atores, a lapela fica 6 dB acima do piso.
FATOR_DO_PISO = 10.0
PERCENTIL_DO_PISO = 20
#: A voz de um ator vaza para a lapela do outro; só conta onde o canal dele não perde do outro por mais que isto.
TOLERANCIA_DB = 3.0
#: Pausa dentro da palavra (oclusiva) não é o fim da voz.
SILENCIO_QUE_ENCERRA_S = 0.12
#: Até onde a borda pode andar a partir do que o ASR disse.
ALCANCE_FORA_S = 0.60
ALCANCE_DENTRO_S = 0.50
#: Acima disto os dois canais escutam a mesma coisa: não são lapelas de pessoas diferentes.
CORRELACAO_MAXIMA = 0.85
#: A partir daqui dois canais são cópias um do outro.
COPIA = 0.97
#: A lapela do ator precisa ganhar da outra por esta margem para valer; a mesma de `midia/falantes.py`.
MARGEM_DB = 3.0


def envelope(arquivo: str) -> np.ndarray:
    """Energia por janela de 10 ms, de um canal inteiro."""
    bruto = subprocess.run(["ffmpeg", "-v", "error", "-i", arquivo, "-map", "0:a:0", "-ac", "1", "-ar", str(TAXA), "-f", "s16le", "-"],
                           capture_output=True, timeout=300, check=True).stdout
    amostras = np.frombuffer(bruto, dtype=np.int16).astype(np.float32) / 32768.0
    passo = int(TAXA * JANELA_S)
    n = len(amostras) // passo
    energia = np.square(amostras[:n * passo]).reshape(n, passo).mean(axis=1)
    del amostras, bruto
    return energia.astype(np.float32)


def _db(x):
    return 10 * np.log10(np.maximum(x, 1e-12))


def _fechar(v: np.ndarray, janelas: int) -> np.ndarray:
    """Preenche buracos curtos (a oclusiva dentro da palavra)."""
    v = v.copy()
    fora = np.flatnonzero(~v)
    if len(fora) == 0:
        return v
    for g in np.split(fora, np.flatnonzero(np.diff(fora) != 1) + 1):
        if len(g) <= janelas and g[0] > 0 and g[-1] < len(v) - 1:
            v[g] = True
    return v


class Som:
    """As lapelas de um take, com o relógio em quadros do TAKE. Sem nomes de trilha: as lapelas são o par de canais que MENOS escuta a mesma coisa."""

    def __init__(self, take):
        self.taxa = Fraction(take.fps["num"], take.fps["den"])
        self.base = float(take.som.inicio_s)
        env = [envelope(str(a)) for a in take.som.arquivos]
        n = min(len(e) for e in env)
        matriz = np.corrcoef(np.stack([_db(e[:n]) for e in env]))
        np.fill_diagonal(matriz, 2.0)
        # ⛔ Dois canais iguais são cópias da mistura (medido: correlação 1,00). Sem tirá-los, nos takes da Personagem F o par escolhido foi mistura + lapela.
        copias = sorted({int(k) for k in np.argwhere((matriz >= COPIA) & (matriz <= 1.0001)).ravel()})
        matriz[copias, :] = 2.0
        matriz[:, copias] = 2.0
        i, j = np.unravel_index(np.argmin(matriz), matriz.shape)
        self.correlacao = float(matriz[i, j])
        self.lapelas = sorted((int(i), int(j))) if self.correlacao <= CORRELACAO_MAXIMA else []
        self.env = {c: env[c][:n] for c in self.lapelas}
        self.ref = {c: max(float(np.percentile(e, 95)), 1e-10) for c, e in self.env.items()}
        self.voz = {}
        for c in self.lapelas:
            outro = self.lapelas[0] if c == self.lapelas[1] else self.lapelas[1]
            limite = max(float(np.percentile(self.env[c], PERCENTIL_DO_PISO)), 1e-10) * FATOR_DO_PISO
            suave = np.convolve(self.env[c], np.ones(3) / 3, mode="same")
            suave_o = np.convolve(self.env[outro], np.ones(3) / 3, mode="same")
            relativo = _db(suave / self.ref[c]) >= _db(suave_o / self.ref[outro]) - TOLERANCIA_DB
            self.voz[c] = _fechar((suave > limite) & relativo, int(SILENCIO_QUE_ENCERRA_S / JANELA_S))

    def indice(self, quadro: float) -> int:
        return int((self.base + float(quadro / self.taxa)) / JANELA_S)

    def quadro(self, i: int) -> int:
        return round(((i * JANELA_S) - self.base) * float(self.taxa))

    def canal_de(self, a: int, b: int) -> tuple[int | None, float]:
        """A lapela de quem fala entre os quadros a e b. (canal ou None, margem em dB)"""
        if not self.lapelas:
            return None, 0.0
        i, j = self.indice(a), max(self.indice(a) + 1, self.indice(b))
        niveis = {c: float(_db(max(float(e[i:j].mean()), 1e-12) / self.ref[c])) for c, e in self.env.items()}
        c1, c2 = self.lapelas
        margem = abs(niveis[c1] - niveis[c2])
        return (max(niveis, key=niveis.get) if margem >= MARGEM_DB else None), margem

    def _procura(self, i: int, canal: int, sentido: int) -> int | None:
        """A borda da voz a partir da janela i. sentido +1: o fim; -1: o início. None: sem voz por perto, fica o ASR."""
        v = self.voz[canal]
        fora, dentro = int(ALCANCE_FORA_S / JANELA_S), int(ALCANCE_DENTRO_S / JANELA_S)
        i = min(max(i, 0), len(v) - 1)
        if v[i]:
            k = i
            while 0 <= k + sentido < len(v) and v[k + sentido] and abs(k + sentido - i) <= fora:
                k += sentido
            return k
        k = i
        while 0 <= k - sentido < len(v) and abs(k - sentido - i) <= dentro:
            k -= sentido
            if v[k]:
                return k
        return None

    def fim_da_voz(self, quadro: float, canal: int) -> int | None:
        k = self._procura(self.indice(quadro), canal, +1)
        return None if k is None else self.quadro(k + 1)

    def inicio_da_voz(self, quadro: float, canal: int) -> int | None:
        k = self._procura(self.indice(quadro), canal, -1)
        return None if k is None else self.quadro(k)


def refinar(take, segs: list[dict]) -> dict[int, dict]:
    """Por segmento: início e fim da voz, em quadros do take. Sem lapela dominante, a borda fica a do ASR, marcada."""
    som = Som(take)
    saida = {}
    for s in segs:
        pal = s.get("palavras") or []
        if not pal:
            continue
        a, b = int(pal[0]["inicio"]), int(pal[-1]["fim"])
        c_ini, m_ini = som.canal_de(int(pal[0]["inicio"]), int(pal[0]["fim"]))
        c_fim, m_fim = som.canal_de(int(pal[-1]["inicio"]), int(pal[-1]["fim"]))
        ini = som.inicio_da_voz(a, c_ini) if c_ini is not None else None
        fim = som.fim_da_voz(b, c_fim) if c_fim is not None else None
        saida[int(s["segmento"])] = {"ini": a if ini is None else ini, "fim": b if fim is None else fim, "asr_ini": a, "asr_fim": b,
                                     "medido_ini": ini is not None, "medido_fim": fim is not None, "canal_ini": c_ini, "canal_fim": c_fim,
                                     "margem_ini": round(m_ini, 1), "margem_fim": round(m_fim, 1), "lapelas": som.lapelas}
    return saida


def guardado(pasta: Path, nome: str, take, segs: list[dict]) -> dict[int, dict]:
    arq = pasta / "bordas" / f"{nome}.json"
    if arq.exists():
        return {int(k): v for k, v in json.loads(arq.read_text(encoding="utf-8")).items()}
    feito = refinar(take, segs)
    arq.parent.mkdir(parents=True, exist_ok=True)
    arq.write_text(json.dumps(feito), encoding="utf-8")
    return feito


#: As emendas de som do corte final do curta, em quadros do take (leitura do AAF). O remendo de 24 quadros de P03-001 fica de fora.
EMENDAS_DO_EDITOR = {"C07_P03-001": [(323, 556), (1054, 1237), (4174, 4334)], "C07_P02-002": [(425, 521), (526, 772), (779, 965), (3051, 3450)],
                     "C07_P01-002": [(2495, 3007), (4602, 4708)], "C07_P02-004": [(4429, 4662)]}


def medir() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import no_papel as P
    from cicloassist.avid.take import resolver

    takes = P.carregar_takes()
    pasta = Path(P.SAIDA + " v3")
    medidos, n_bordas, altera_ini, altera_fim = 0, 0, [], []
    dentro = {"asr": 0, "refinado": 0}
    total = 0
    for nome in "C07_P01-001 C07_P01-002 C07_P02-002 C07_P02-003 C07_P02-004 C07_P03-001 C07_P03-003".split():
        b = guardado(pasta, nome, resolver(P.BIN, nome), takes[nome])
        print(f"{nome}: {len(b)} segmentos · lapelas {next(iter(b.values()))['lapelas']}")
        for v in b.values():
            n_bordas += 2
            medidos += v["medido_ini"] + v["medido_fim"]
            if v["medido_ini"]:
                altera_ini.append(v["asr_ini"] - v["ini"])
            if v["medido_fim"]:
                altera_fim.append(v["fim"] - v["asr_fim"])
        for de, ate in EMENDAS_DO_EDITOR.get(nome, []):
            for q in (de, ate):
                total += 1
                dentro["asr"] += any(v["asr_ini"] < q < v["asr_fim"] for v in b.values())
                dentro["refinado"] += any(v["ini"] < q < v["fim"] for v in b.values())
    print(f"\nbordas medidas na lapela: {medidos} de {n_bordas}")
    print(f"início recuou (q): mediana {np.median(altera_ini):.0f} · p5 {np.percentile(altera_ini, 5):.0f} · p95 {np.percentile(altera_ini, 95):.0f}")
    print(f"fim avançou (q): mediana {np.median(altera_fim):.0f} · p5 {np.percentile(altera_fim, 5):.0f} · p95 {np.percentile(altera_fim, 95):.0f}")
    print(f"emendas do editor humano dentro de voz: ASR {dentro['asr']}/{total} · refinado {dentro['refinado']}/{total}")

    print("\nos pontos que o autor ouviu:")
    for nome, segs in (("C07_P02-002", (10, 11, 21, 22)), ("C07_P03-001", (19, 20))):
        b = guardado(pasta, nome, resolver(P.BIN, nome), takes[nome])
        for n in segs:
            v = b[n]
            print(f"  {nome} seg {n}: voz {v['ini']}-{v['fim']} · ASR {v['asr_ini']}-{v['asr_fim']} · medido {v['medido_ini']}/{v['medido_fim']} · canal {v['canal_ini']}/{v['canal_fim']}")
    return 0


if __name__ == "__main__":
    if "--medir" in sys.argv:
        sys.exit(medir())
