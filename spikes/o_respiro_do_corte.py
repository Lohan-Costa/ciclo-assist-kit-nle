"""Spike — o tempo do ASR não é a borda da VOZ, e o corte cola na fala.

    python spikes/o_respiro_do_corte.py

## O que motivou

Parecer de campo, 2026-09-11, sobre um corte montado pelo produto:

> *"a primeira fala do Personagem G 'sinceramente, não' sempre é colada na entrada da fala, quase
> cortando a primeira sílaba; e a frase final é cortada, 'sobe comigo' vira 'sobe co…'.
> Dá a impressão de que o programa trata o TC da transcrição muito literal."*

Ele está certo, e a pergunta é **de quanto** — porque um respiro chutado é tão arbitrário
quanto não ter nenhum.

## Como se mede

O WAV de trabalho já está no cache (16 kHz mono, o mesmo que alimentou o ASR). Para cada
palavra de borda:

1. varre a energia em janelas de 10 ms em volta do tempo que o ASR deu;
2. acha o **piso de ruído** local (percentil baixo de uma janela de 2 s antes/depois);
3. anda para trás a partir do início da palavra enquanto a energia estiver acima do piso —
   o primeiro instante em que ela sobe é a **entrada real da voz**;
4. o mesmo para o fim, andando para a frente.

A diferença entre a borda real e o tempo do ASR é o respiro que falta.

⚠️ Isto mede a VOZ, não a intenção do editor. Respiro de montagem — o silêncio que o ator
deixa antes de responder — é outra coisa, e é escolha dele. Aqui se mede só o que está
sendo cortado fora sem ninguém pedir.
"""

from __future__ import annotations

import struct
import sys
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.midia import cache as _cache  # noqa: E402

#: Janela de análise. 10 ms é fino o bastante para achar o ataque de uma consoante e
#: grosso o bastante para não tropeçar em ruído de amostra.
JANELA_S = 0.010

#: Quanto se olha em volta para achar o piso de ruído e a borda.
VIZINHANCA_S = 1.5

#: A voz "começou" quando a energia passa disto acima do piso local. ⚠️ Fator, não valor
#: absoluto: o piso de um som direto de set não é o de um estúdio.
FATOR_DO_PISO = 3.0


def ler_wav(caminho: Path) -> tuple[list[float], int]:
    with wave.open(str(caminho), "rb") as w:
        taxa = w.getframerate()
        canais = w.getnchannels()
        largura = w.getsampwidth()
        bruto = w.readframes(w.getnframes())
    if largura != 2:
        raise SystemExit(f"esperava 16 bits, veio {largura * 8}")
    amostras = struct.unpack(f"<{len(bruto) // 2}h", bruto)
    if canais > 1:
        amostras = amostras[::canais]
    return [a / 32768.0 for a in amostras], taxa


def energia_por_janela(amostras: list[float], taxa: int) -> tuple[list[float], float]:
    passo = max(1, int(taxa * JANELA_S))
    energias = []
    for i in range(0, len(amostras) - passo, passo):
        pedaco = amostras[i:i + passo]
        energias.append(sum(a * a for a in pedaco) / passo)
    return energias, passo / taxa


def borda_da_voz(energias: list[float], dt: float, segundo: float, para_tras: bool) -> float:
    """O instante em que a voz realmente começa (ou acaba), perto de `segundo`."""
    centro = int(segundo / dt)
    volta = int(VIZINHANCA_S / dt)
    inicio = max(0, centro - volta)
    fim = min(len(energias), centro + volta)
    if fim <= inicio:
        return segundo

    vizinhos = sorted(energias[inicio:fim])
    piso = vizinhos[max(0, int(len(vizinhos) * 0.15))] or 1e-9
    limite = piso * FATOR_DO_PISO

    if para_tras:
        i = min(centro, len(energias) - 1)
        # Anda para trás enquanto ainda há voz — a borda é onde ela some.
        while i > inicio and energias[i] > limite:
            i -= 1
        return i * dt
    i = min(centro, len(energias) - 1)
    while i < fim - 1 and energias[i] > limite:
        i += 1
    return i * dt


def main() -> int:
    raiz = _cache.raiz()
    alvos = []
    for pasta in sorted(raiz.iterdir()):
        if not pasta.is_dir() or not (pasta / "audio.wav").is_file():
            continue
        midia = _cache.Midia(pasta.name)
        falas = midia.ler_transcricao()
        if not falas:
            continue
        nome = midia.ler_fonte().get("master_de_som") or pasta.name[:12]
        alvos.append((nome, midia, falas))

    if not alvos:
        print("⚠️ nenhuma mídia com transcrição E áudio no cache")
        return 1

    print(f"{'take':<34}{'palavra':<16}{'ASR':>8}{'voz':>8}{'falta':>8}")
    print("-" * 74)

    antes_de_todos = []
    depois_de_todos = []

    for nome, midia, falas in alvos[:6]:
        amostras, taxa = ler_wav(midia.audio)
        energias, dt = energia_por_janela(amostras, taxa)

        for fala in falas:
            palavras = fala.get("palavras") or []
            if not palavras:
                continue
            texto = (fala.get("texto") or "").strip()
            # As duas falas que o editor citou pelo nome.
            if not ("incera" in texto or "obe comigo" in texto):
                continue

            primeira = palavras[0]
            ultima = palavras[-1]
            t0 = float(primeira.get("t") or fala["inicio"])
            t1 = float(ultima.get("fim") or fala["fim"])

            voz0 = borda_da_voz(energias, dt, t0, para_tras=True)
            voz1 = borda_da_voz(energias, dt, t1, para_tras=False)
            falta0 = t0 - voz0
            falta1 = voz1 - t1
            antes_de_todos.append(falta0)
            depois_de_todos.append(falta1)

            print(f"{nome[:33]:<34}{str(primeira.get('palavra'))[:15]:<16}"
                  f"{t0:>8.2f}{voz0:>8.2f}{falta0:>8.3f}")
            print(f"{'':<34}{('…' + str(ultima.get('palavra'))[:14]):<16}"
                  f"{t1:>8.2f}{voz1:>8.2f}{falta1:>8.3f}")

    if not antes_de_todos:
        print("\n⚠️ não achei as falas de referência nesta máquina")
        return 1

    def resume(valores, rotulo):
        ordenados = sorted(valores)
        meio = ordenados[len(ordenados) // 2]
        print(f"{rotulo:<28}mediana {meio * 1000:>6.0f} ms   "
              f"pior {max(ordenados) * 1000:>6.0f} ms   "
              f"({meio * 24:.1f} frames a 24 fps)")

    print()
    resume(antes_de_todos, "voz ANTES do ASR dizer")
    resume(depois_de_todos, "voz DEPOIS do ASR dizer")
    print("\n⇒ É este o respiro que falta em cada borda do corte.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
