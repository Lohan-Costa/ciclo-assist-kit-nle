"""A voz × o silêncio, pela LAPELA de quem fala — a borda real da fala, sem modelo nenhum.

⭐⭐ Fase L2 do plano `docs/plano/2026-11-11-alinhador-por-palavra.md` (§8). Decisões do autor (2026-11-11):
a borda medida **só ESTENDE** o corte de hoje (nunca encurta), e palavra sem voz em lapela nenhuma é **marcada e
mostrada** ("fora das lapelas — provável equipe"), nunca apagada.

## Por que a lapela, e não a mistura

MEDIDO (banco `transversal/transcricao-por-palavra.md` §7, take `05-04 C4 P1-T001`): na MISTURA de um set a energia
não cai na pausa — ruído de equipe, sala e os outros microfones —, e o fim "medido" passava **+417 ms** (mediana) do
fim do Premiere. Na lapela de quem fala a pausa existe. O `spikes/edicao_de_cena/bordas.py` achou a mesma coisa na
C07 contra as emendas do editor humano, e a regra daqui é a dele:

- voz = **10 dB acima do piso** da lapela (o percentil 20 do envelope) **e** sem perder da outra lapela por mais de
  3 dB (a voz de um ator vaza para a lapela do outro);
- silêncio de até **120 ms** não encerra a voz: é a oclusiva DENTRO da palavra (o /t/ de "doubt it");
- a borda anda no máximo 0,6 s para fora e 0,5 s para dentro do que o ASR disse.

E o juiz de ouvido do autor (18 bordas cegas) cravou a trava: **o fim nunca antes do fim do ASR** — o reconhecedor
fecha a palavra cedo; cortar antes dele é cortar voz, que é o erro que o editor não aceita.

## Sem lapela de pessoa, não se inventa

Lapelas pelo NOME da trilha (`canais.PESSOA`). Sem nomes, o par de canais que MENOS escuta a mesma coisa (o
`bordas.py`: correlação ≤ 0,85, cópias ≥ 0,97 fora) — isto é medição de borda, não atribuição de falante: o
`falantes` continua sem chutar quem fala. Sem nem isso: `nao_medido`, e o corte segue exatamente como antes.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import numpy as np

from . import alinhamento as _alin
from . import canais as _canais
from . import falantes as _falantes

log = logging.getLogger("cicloassist.midia.voz")

JANELA_S = 0.010
ACIMA_DO_PISO_DB = 10.0
PERCENTIL_DO_PISO = 20
PERCENTIL_DE_REFERENCIA = 95
TOLERANCIA_DB = 3.0
SILENCIO_QUE_ENCERRA_S = 0.12
ALCANCE_FORA_S = 0.60
ALCANCE_DENTRO_S = 0.50
#: Um vão sem voz em lapela nenhuma a partir disto é PAUSA — vira item `silencio` e a borda vizinha é medida.
PAUSA_S = 0.30
#: Abaixo desta fração de janelas com voz (em qualquer lapela) a palavra é `fora_das_lapelas`.
VOZ_MINIMA = 0.20
#: ⭐⭐ A QUEDA (2º juiz de ouvido, 2026-11-11): com o alinhador, o fim é onde o nível da lapela de quem fala fica
#: `QUEDA_DB` abaixo do pico do fim da palavra (os últimos `PICO_S`) por `QUEDA_S` — e não onde a máscara apaga. A máscara
#: (piso global +10 dB) seguia acesa no RESTO FRACO depois do tombo (sala, respiro, a outra lapela) e alongava o fim em
#: +400…+680 ms: Premiere 14 × L1 5 de ouvido. Com a queda: 10 de 14 fins. ⚠️ `hipotese`: ajustada nesses 14; conferir num 2º take.
QUEDA_DB = 10.0
QUEDA_S = 0.05
PICO_S = 0.30
#: O fim nunca encosta na palavra seguinte (medido: passava dela em "apartamento," e "de").
ANTES_DA_PROXIMA_S = 0.03
CORRELACAO_MAXIMA = 0.85
COPIA = 0.97

NAO_MEDIDO = "nao_medido"
FALA = "fala"
SILENCIO = "silencio"
EQUIPE = "fora das lapelas (provável equipe)"

ASSINATURA = {"regra": "lapela-borda", "versao": 3, "queda": {"db": QUEDA_DB, "s": QUEDA_S, "pico_s": PICO_S},
              "alinhador": {"desvio_inicio_s": _alin.DESVIO_INICIO_S, "folga_fim_s": _alin.FOLGA_FIM_S}, "janela_s": JANELA_S, "acima_do_piso_db": ACIMA_DO_PISO_DB,
              "tolerancia_db": TOLERANCIA_DB, "oclusiva_s": SILENCIO_QUE_ENCERRA_S, "pausa_s": PAUSA_S}
ARQUIVO = "voz.json"


def _db(x):
    return 10 * np.log10(np.maximum(x, 1e-12))


def _fechar(v: np.ndarray, janelas: int) -> np.ndarray:
    """Preenche buracos curtos no meio da voz (a oclusiva). Buraco na ponta não é buraco: é borda."""
    v = v.copy()
    fora = np.flatnonzero(~v)
    if len(fora) == 0:
        return v
    for g in np.split(fora, np.flatnonzero(np.diff(fora) != 1) + 1):
        if len(g) <= janelas and g[0] > 0 and g[-1] < len(v) - 1:
            v[g] = True
    return v


# ── quais canais são lapelas ─────────────────────────────────────────────────

def lapelas_por_nome(trilhas: list[_canais.Trilha], medidos) -> list[int]:
    return sorted(t.canal for t in trilhas if t.e_pessoa and t.canal in medidos)


def lapelas_por_correlacao(envs: dict[int, np.ndarray]) -> list[int]:
    """O par de canais que menos escuta a mesma coisa (o `bordas.py`). `[]` se todos escutam o mesmo."""
    chaves = sorted(envs)
    if len(chaves) < 2:
        return []
    n = min(len(envs[c]) for c in chaves)
    m = np.corrcoef(np.stack([_db(envs[c][:n]) for c in chaves]))
    np.fill_diagonal(m, 2.0)
    # ⛔ Canais iguais são cópias da mistura (medido: correlação 1,00); sem tirá-los o par sai mistura + lapela.
    copias = sorted({int(k) for k in np.argwhere((m >= COPIA) & (m <= 1.0001)).ravel()})
    m[copias, :] = 2.0
    m[:, copias] = 2.0
    i, j = np.unravel_index(np.argmin(m), m.shape)
    return sorted((chaves[int(i)], chaves[int(j)])) if m[i, j] <= CORRELACAO_MAXIMA else []


# ── a máscara de voz ─────────────────────────────────────────────────────────

def mascaras(envs: dict[int, np.ndarray], lapelas: list[int]) -> dict[int, np.ndarray]:
    """lapela → voz (bool) por janela de `JANELA_S`."""
    if not lapelas:
        return {}
    n = min(len(envs[c]) for c in lapelas)
    suave = {c: np.convolve(np.asarray(envs[c][:n], float), np.ones(3) / 3, mode="same") for c in lapelas}
    ref = {c: max(float(np.percentile(suave[c], PERCENTIL_DE_REFERENCIA)), 1e-10) for c in lapelas}
    saida = {}
    for c in lapelas:
        limite = max(float(np.percentile(suave[c], PERCENTIL_DO_PISO)), 1e-10) * 10 ** (ACIMA_DO_PISO_DB / 10)
        voz = suave[c] > limite
        outros = [o for o in lapelas if o != c]
        if outros:
            melhor_outro = np.max(np.stack([_db(suave[o] / ref[o]) for o in outros]), axis=0)
            voz &= _db(suave[c] / ref[c]) >= melhor_outro - TOLERANCIA_DB
        saida[c] = _fechar(voz, int(SILENCIO_QUE_ENCERRA_S / JANELA_S))
    return saida


def niveis(envs: dict[int, np.ndarray], lapelas: list[int]) -> dict[int, np.ndarray]:
    """lapela → nível em dB por janela (o mesmo envelope suavizado da máscara). É o que a QUEDA lê."""
    if not lapelas:
        return {}
    n = min(len(envs[c]) for c in lapelas)
    return {c: _db(np.convolve(np.asarray(envs[c][:n], float), np.ones(3) / 3, mode="same")) for c in lapelas}


def queda(nv: dict[int, np.ndarray], canal: int | None, t: float, z: float, limite: float) -> float | None:
    """O fim pela QUEDA: na lapela de quem fala (`canal`, ou a mais forte dentro da palavra `t`–`z`), o primeiro ponto
    depois de `z` (o fim CRU do alinhador) em que o nível fica `QUEDA_DB` abaixo do pico dos últimos `PICO_S` por
    `QUEDA_S`. Nunca passa de `limite`. `None` sem nível."""
    if not nv:
        return None
    a, k = _janela(t), _janela(z)
    n = min(len(x) for x in nv.values())
    if k >= n or a >= n:
        return None
    c = canal if canal in nv else max(nv, key=lambda c: float(nv[c][a:k + 1].max()) if k >= a else -1e9)
    pico = float(nv[c][max(a, k - int(PICO_S / JANELA_S)):k + 1].max())
    w, fim = max(1, int(round(QUEDA_S / JANELA_S))), min(_janela(limite), n)
    i = k
    while i < fim and not np.all(nv[c][i:i + w] < pico - QUEDA_DB):
        i += 1
    return i * JANELA_S


def procurar(v: np.ndarray, i: int, sentido: int) -> int | None:
    """A borda da voz a partir da janela `i`. `sentido` +1 = o fim; −1 = o início. `None` = sem voz por perto."""
    if len(v) == 0:
        return None
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


def _trechos(v: np.ndarray, valor: bool, minimo_s: float = 0.0) -> list[list[float]]:
    """Os trechos contíguos em que `v == valor`, em segundos, com pelo menos `minimo_s`."""
    if len(v) == 0:
        return []
    d = np.diff(np.concatenate([[False], v == valor, [False]]).astype(int))
    ini, fim = np.flatnonzero(d == 1), np.flatnonzero(d == -1)
    return [[round(float(a) * JANELA_S, 3), round(float(b) * JANELA_S, 3)] for a, b in zip(ini, fim)
            if (b - a) * JANELA_S >= minimo_s - 1e-9]


# ── a medição de um master ───────────────────────────────────────────────────

def _janela(t: float) -> int:
    return int(round(t / JANELA_S))


def medir(falas: list[dict[str, Any]], masks: dict[int, np.ndarray],
          canal_por_fala: list[int | None], alinhadas: list | None = None,
          nv: dict[int, np.ndarray] | None = None) -> dict[str, Any]:
    """Pura: as bordas medidas de cada fala (na lapela dela, ou em qualquer lapela quando não se sabe quem fala),
    as palavras fora das lapelas e os silêncios. Mesma ordem da transcrição.

    ⭐⭐ `alinhadas` (L1: `alinhamento.bordas`, a regra do juiz de ouvido já aplicada) — por fala, por palavra,
    `(inicio, fim)` ou `None`. Com elas a borda PARTE do alinhador, não do Whisper (que erra até ~1 s em fala de set):
    o início é o do alinhador (a energia andava para trás demais, medido de ouvido) e o fim é
    `max(voz na lapela, fim do alinhador)`. Sem lapela, a borda do alinhador vale sozinha.
    ⭐⭐ Com `nv` (`niveis`) e a palavra alinhada, a "voz na lapela" do fim é a QUEDA (`queda`), não a máscara."""
    if not masks and not alinhadas:
        return {"falas": [{} for _ in falas], "silencios": [], "voz": {}}
    n = min(len(m) for m in masks.values()) if masks else 0
    alguma = np.any(np.stack([m[:n] for m in masks.values()]), axis=0) if masks else np.zeros(0, bool)

    def borda(v, t, sentido):
        if len(v) == 0:
            return None
        k = procurar(v, _janela(t), sentido)
        if k is None:
            return None
        return (k + 1) * JANELA_S if sentido > 0 else k * JANELA_S

    saida = []
    for i, (f, canal) in enumerate(zip(falas, canal_por_fala)):
        v = masks[canal][:n] if canal in masks else alguma
        todas = f.get("palavras") or []
        al = alinhadas[i] if alinhadas and i < len(alinhadas) and len(alinhadas[i]) == len(todas) else None
        # ⛔ A posição da palavra na lista ORIGINAL é a chave de `anexar`: a palavra sem `fim` fica, vazia.
        pal = []
        for k, w in enumerate(todas):
            if w.get("fim") is None:
                continue
            r = al[k] if al else None
            pal.append((k, float(r[0]) if r else float(w["t"]), float(r[1]) if r else float(w["fim"]), bool(r)))
        alinhada = any(x[3] for x in pal)
        a = pal[0][1] if pal else float(f.get("inicio") or 0)
        b = pal[-1][2] if pal else float(f.get("fim") or a)
        def fim_de(t, z, tem, proxima):
            """O fim medido de uma palavra que acaba em `z`: a QUEDA quando há nível e alinhador, senão a máscara."""
            if tem and nv:
                cru = z - _alin.FOLGA_FIM_S
                return queda(nv, canal, t, cru, min(cru + ALCANCE_FORA_S, proxima - ANTES_DA_PROXIMA_S))
            return borda(v, z, +1)

        seguinte = _primeira(falas[i + 1], alinhadas[i + 1] if alinhadas and i + 1 < len(alinhadas) else None) \
            if i + 1 < len(falas) else float("inf")
        fim = fim_de(pal[-1][1], b, pal[-1][3], seguinte) if pal else borda(v, b, +1)
        d: dict[str, Any] = {"canal": canal if canal in masks else None}
        if alinhada and pal[0][3]:
            d["voz_inicio"] = round(a, 3)
        elif (ini := borda(v, a, -1)) is not None:
            d["voz_inicio"] = round(ini, 3)
        if fim is not None or (alinhada and pal[-1][3]):
            # ⛔ A trava do juiz de ouvido: o reconhecedor (e o CTC) fecha a palavra cedo; o fim medido nunca fica
            #   antes dele.
            d["voz_fim"] = round(max(fim if fim is not None else b, b), 3)
        if alinhada:
            d["borda_por"] = "alinhamento+lapela" if masks else "alinhamento"
        elif masks:
            d["borda_por"] = "lapela"
        # As palavras: as que encostam numa pausa ganham a borda medida; as sem voz em lapela nenhuma, a marca.
        palavras: list[dict[str, Any]] = [{} for _ in todas]
        for j, (k, t, z, tem) in enumerate(pal):
            p = palavras[k]
            if tem:
                p["t_alinhado"], p["fim_alinhado"] = round(t, 3), round(z, 3)
            if masks:
                a_j, z_j = _janela(t), max(_janela(z), _janela(t) + 1)
                trecho = alguma[a_j:min(z_j, n)]
                if (float(trecho.mean()) if len(trecho) else 0.0) < VOZ_MINIMA:
                    p["fora_das_lapelas"] = True
            antes = t - pal[j - 1][2] if j else PAUSA_S
            depois = pal[j + 1][1] - z if j + 1 < len(pal) else PAUSA_S
            if antes >= PAUSA_S:
                if tem:
                    p["voz_t"] = round(t, 3)
                elif (x := borda(v, t, -1)) is not None:
                    p["voz_t"] = round(x, 3)
            proxima = pal[j + 1][1] if j + 1 < len(pal) else seguinte
            if depois >= PAUSA_S and ((x := fim_de(t, z, tem, proxima)) is not None or tem):
                p["voz_fim"] = round(max(x if x is not None else z, z), 3)
        if pal and all(palavras[k].get("fora_das_lapelas") for k, *_ in pal):
            d["fora_das_lapelas"] = True
        d["palavras"] = palavras
        saida.append(d)
    return {"falas": saida,
            "silencios": _trechos(alguma, False, PAUSA_S) if masks else [],
            "voz": {str(c): _trechos(m[:n], True) for c, m in masks.items()}}


def _primeira(f: dict[str, Any], al) -> float:
    """Onde a fala seguinte começa: a primeira palavra (alinhada, se houver), senão o `inicio` dela."""
    ws = f.get("palavras") or []
    if al and len(al) == len(ws):
        for r in al:
            if r:
                return float(r[0])
    for w in ws:
        if w.get("t") is not None:
            return float(w["t"])
    return float(f.get("inicio") or float("inf"))


def em_fala(dados: dict[str, Any] | None, t: float) -> tuple[str, int | None]:
    """⭐ "O corte cai em fala?" — `("fala", canal)`, `("silencio", None)` ou `("nao_medido", None)`."""
    voz = (dados or {}).get("voz") or {}
    if not voz:
        return NAO_MEDIDO, None
    for c, trechos in voz.items():
        if any(a <= t < b for a, b in trechos):
            return FALA, int(c)
    return SILENCIO, None


# ── o estágio no cache ───────────────────────────────────────────────────────

def _impressao(midia) -> str:
    return _falantes._impressao_da_transcricao(midia)


def ler(midia) -> dict[str, Any]:
    """O `voz.json` SE ainda vale (receita de hoje e a mesma transcrição); senão `{}`."""
    dados = midia._ler_json(midia.arquivo(ARQUIVO))
    if not dados or dados.get("assinatura") != ASSINATURA or dados.get("transcricao") != _impressao(midia):
        return {}
    # ⭐ O alinhamento que chegou (ou mudou) depois desta medição a invalida: a borda passa a partir dele.
    if dados.get("alinhamento", "") != (_alin.impressao(midia) if _alin.ler(midia) else ""):
        return {}
    return dados


def _canal_por_fala(falantes: dict[str, Any] | None, n: int, lapelas: list[int]) -> list[int | None]:
    ats = (falantes or {}).get("falas") or []
    if len(ats) != n:
        return [None] * n
    return [a.get("canal") if a.get("motivo") == _falantes.RESOLVIDA and a.get("canal") in lapelas else None
            for a in ats]


def garantir(midia, arquivos: list[str], trilhas: list[_canais.Trilha], falantes: dict[str, Any] | None = None,
             forcar: bool = False, alinhamento: dict[str, Any] | None = None) -> dict[str, Any]:
    """Deixa `voz.json` no cache e o devolve. Barato quando já está: só lê."""
    if not forcar and (pronto := ler(midia)):
        return pronto
    falas = midia.ler_transcricao()
    envs = {c: np.asarray(e, np.float32) for c, e in _falantes.envelopes([str(a) for a in arquivos], JANELA_S).items()}
    lapelas = lapelas_por_nome(trilhas, envs)
    origem = "nome"
    if not lapelas:
        lapelas, origem = lapelas_por_correlacao(envs), "correlacao"
    if alinhamento is None:
        alinhamento = _alin.ler(midia)
    alinhadas = _alin.bordas(alinhamento, falas)
    dados: dict[str, Any] = {"assinatura": ASSINATURA, "transcricao": _impressao(midia),
                             "alinhamento": _alin.impressao(midia) if alinhadas else "",
                             "lapelas": lapelas, "lapelas_por": origem if lapelas else ""}
    dados.update(medir(falas, mascaras(envs, lapelas), _canal_por_fala(falantes, len(falas), lapelas), alinhadas,
                       niveis(envs, lapelas)))
    from .cache import escrever_atomico  # noqa: PLC0415 — `cache` importa muito; aqui só quando grava
    escrever_atomico(midia.pasta / ARQUIVO, json.dumps(dados, ensure_ascii=False).encode("utf-8"))
    return dados


def anexar(falas: list[dict[str, Any]], dados: dict[str, Any] | None) -> list[dict[str, Any]]:
    """As falas do master com a borda medida (`voz_inicio`/`voz_fim`) e a marca de fora das lapelas, pela POSIÇÃO.

    ⛔ Só se as contagens baterem (`voz.json` de outra transcrição não se cola calado)."""
    medidas = (dados or {}).get("falas") or []
    if not medidas or len(medidas) != len(falas):
        return falas
    saida = []
    for f, m in zip(falas, medidas):
        g = dict(f)
        for k in ("voz_inicio", "voz_fim"):
            if k in m:
                g[k] = m[k]
        pal = f.get("palavras") or []
        if pal and len(m.get("palavras") or []) == len(pal):
            g["palavras"] = [{**w, **p} for w, p in zip(pal, m["palavras"])]
        if m.get("fora_das_lapelas"):
            g["fora_das_lapelas"] = True
            if not g.get("quem"):
                g["quem"] = EQUIPE
        saida.append(g)
    return saida
