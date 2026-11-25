"""Spike — dá para achar "planos parecidos com este" no acervo, e com o quê?

    python spikes/busca_visual.py

O editor pediu: arrastar uma imagem (ou apontar o quadro que está no monitor) e o produto
achar **o personagem** ou **planos parecidos**, para match cut. Antes de escolher o motor,
mede-se: é o método da casa, e aqui a diferença entre os candidatos é grande demais para
ser decidida por intuição.

## O que está em jogo

| motor | tamanho | o que promete |
|---|---|---|
| **pHash** | 0 MB — PIL + numpy | assinatura da IMAGEM: enquadramento, composição, luz |
| **embedding ONNX** | ~14 MB (MobileNetV2) | o que a rede "vê": objeto, pessoa, tipo de plano |

⛔ **Nenhum dos dois é torch** (regra da casa). O `onnxruntime` já é dependência — é o
runtime do `sherpa-onnx` — então o segundo caminho não traz peça nova de arquitetura, só
um arquivo de modelo.

## Como se mede acerto, sem inventar verdade

A bin C07 dá o gabarito de graça: são **três planos** da mesma cena — P01 (geral dos
dois), P02 (fechado em Eduardo), P03 (fechado em Personagem F). Então:

> dado um quadro de um plano, os vizinhos mais parecidos deveriam ser **do mesmo plano**.

É precisão em `top-k`, com rótulo que ninguém precisou anotar à mão. ⚠️ E é uma medida de
**enquadramento/pessoa**, não de "match cut bonito" — que é julgamento do editor e não se
mede aqui.
"""

from __future__ import annotations

import sys
import time
import urllib.request
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from cicloassist.avid.take import resolver  # noqa: E402
from cicloassist.midia import cache as _cache  # noqa: E402
from cicloassist.midia import frames as _frames  # noqa: E402
from cicloassist.avid.mcapi import MediaComposer  # noqa: E402

BIN = r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR\CENAS\C07.avb"

#: Os takes, com o plano a que pertencem — o gabarito.
TAKES = [
    ("C07_P01-T001", "P01 geral"), ("C07_P01-T002", "P01 geral"),
    ("C07_P02-T002", "P02 Eduardo"), ("C07_P02-T003", "P02 Eduardo"),
    ("C07_P02-T004", "P02 Eduardo"),
    ("C07_P03-T001", "P03 Personagem F"), ("C07_P03-T002", "P03 Personagem F"),
    ("C07_P03-T003", "P03 Personagem F"),
]

#: Quantos quadros por take. Poucos e espalhados: o que se quer é variar o conteúdo
#: dentro do mesmo enquadramento, não colher quadros quase idênticos.
POR_TAKE = 4

#: MobileNetV2 do zoológico oficial do ONNX. ⚠️ Classificador, usado aqui como EXTRATOR:
#: a penúltima camada vira o vetor. É o truque barato — e é justamente o que este spike
#: precisa descobrir se basta.
URL_DO_MODELO = ("https://github.com/onnx/models/raw/main/validated/vision/"
                 "classification/mobilenet/model/mobilenetv2-12.onnx")


# ── o conjunto ───────────────────────────────────────────────────────────────


def juntar_quadros() -> list[tuple[Path, str, str]]:
    """`(arquivo do quadro, take, plano)` — usando o cache, que já tem muita coisa."""
    with MediaComposer() as mc:
        fps = mc.projeto()["fps_aprox"]

    conjunto = []
    for nome, plano in TAKES:
        try:
            take = resolver(BIN, nome)
        except Exception as e:  # noqa: BLE001 - um take faltando não derruba a medição
            print(f"  ⚠️ {nome}: {e}")
            continue
        imagem = take.imagem
        if imagem is None or not imagem.arquivos:
            print(f"  ⚠️ {nome}: sem imagem")
            continue

        midia = _cache.Midia(imagem.mob_id)
        passo = max(1, take.duracao_frames // (POR_TAKE + 1))
        for i in range(1, POR_TAKE + 1):
            posicao = imagem.inicio_frames + i * passo
            caminho = midia.caminho_do_quadro(posicao)
            if not caminho.exists():
                try:
                    jpeg = _frames.extrair(imagem.arquivos[0], posicao, fps)
                    midia.guardar_quadro(posicao, jpeg)
                except Exception as e:  # noqa: BLE001
                    print(f"  ⚠️ {nome}@{posicao}: {e}")
                    continue
            conjunto.append((caminho, nome, plano))
    return conjunto


# ── motor 1: pHash ───────────────────────────────────────────────────────────


def phash(caminho: Path, lado: int = 32) -> np.ndarray:
    """A assinatura perceptual clássica: DCT da imagem em cinza, bits do canto de baixa
    frequência. Sem dependência nenhuma além de PIL e numpy."""
    img = Image.open(caminho).convert("L").resize((lado, lado), Image.LANCZOS)
    a = np.asarray(img, dtype=np.float32)
    # DCT-II separável, feita com FFT para não trazer scipy.
    def dct(m):
        n = m.shape[0]
        estendido = np.concatenate([m, m[::-1]], axis=0)
        return np.real(np.fft.fft(estendido, axis=0)[:n]) * 2
    d = dct(dct(a).T).T
    baixa = d[:8, :8].flatten()
    return (baixa > np.median(baixa)).astype(np.uint8)


def parecenca_phash(a: np.ndarray, b: np.ndarray) -> float:
    return 1.0 - float(np.count_nonzero(a != b)) / a.size


# ── motor 2: embedding ONNX ──────────────────────────────────────────────────


def baixar_o_modelo(destino: Path) -> bool:
    if destino.exists() and destino.stat().st_size > 1_000_000:
        return True
    destino.parent.mkdir(parents=True, exist_ok=True)
    print(f"  baixando o modelo (uma vez) → {destino.name}…")
    try:
        urllib.request.urlretrieve(URL_DO_MODELO, destino)
    except Exception as e:  # noqa: BLE001
        print(f"  ⚠️ não consegui baixar: {e}")
        return False
    return destino.exists()


def vetores_onnx(caminhos: list[Path]) -> tuple[list[np.ndarray], float, float]:
    """Um vetor por quadro. Devolve `(vetores, segundos, MB do modelo)`."""
    import onnxruntime as ort

    modelo = _cache.raiz().parent / "modelos" / "mobilenetv2-12.onnx"
    if not baixar_o_modelo(modelo):
        return [], 0.0, 0.0

    sessao = ort.InferenceSession(str(modelo), providers=["CPUExecutionProvider"])
    entrada = sessao.get_inputs()[0].name
    # ⚠️ A penúltima saída seria o ideal; o grafo exporta só a final. Para SEMELHANÇA o
    #    vetor de logits ainda serve — é o que este spike está medindo.
    saida = sessao.get_outputs()[0].name

    media = np.array([0.485, 0.456, 0.406], dtype=np.float32).reshape(3, 1, 1)
    desvio = np.array([0.229, 0.224, 0.225], dtype=np.float32).reshape(3, 1, 1)

    comeco = time.monotonic()
    vetores = []
    for c in caminhos:
        img = Image.open(c).convert("RGB").resize((224, 224), Image.BILINEAR)
        a = np.asarray(img, dtype=np.float32).transpose(2, 0, 1) / 255.0
        a = (a - media) / desvio
        v = sessao.run([saida], {entrada: a[None, ...]})[0].flatten()
        vetores.append(v / (np.linalg.norm(v) + 1e-9))
    return vetores, time.monotonic() - comeco, modelo.stat().st_size / 1e6


# ── a medição ────────────────────────────────────────────────────────────────


def medir(nome: str, parecencas, conjunto, k: int = 3) -> float:
    """Para cada quadro, os `k` vizinhos mais parecidos são do MESMO plano?

    ⚠️⚠️ **Os quadros do MESMO TAKE ficam de fora da busca, e isto muda tudo.** Quatro
    quadros de um take são quase a mesma imagem: com eles no páreo, os três vizinhos mais
    próximos são sempre os irmãos, e a medida vira "acha o mesmo arquivo" — 100% para
    qualquer motor, inclusive um que só comparasse o tamanho em bytes.

    A pergunta que o editor faz é outra: *"onde mais eu tenho um plano assim?"*. Ela só
    aparece quando o take de origem sai do conjunto — e aí o acerto tem de vir de OUTRO
    take do mesmo plano.

    ⭐ Instrumento também precisa de revisão: a primeira versão deste spike media o caso
    fácil e teria mandado escolher motor por um número que não queria dizer nada.
    """
    acertos = total = 0
    por_plano = defaultdict(lambda: [0, 0])
    for i, (_, take, plano) in enumerate(conjunto):
        ordem = sorted(
            (j for j in range(len(conjunto)) if conjunto[j][1] != take),
            key=lambda j: -parecencas[i][j],
        )[:k]
        for j in ordem:
            acertos += conjunto[j][2] == plano
            total += 1
            por_plano[plano][0] += conjunto[j][2] == plano
            por_plano[plano][1] += 1

    print(f"\n  {nome}")
    for plano, (a, t) in sorted(por_plano.items()):
        print(f"    {plano:14} {a}/{t}  {a / t:.0%}")
    print(f"    {'TOTAL':14} {acertos}/{total}  {acertos / total:.0%}")
    return acertos / total


def main() -> int:
    print("=" * 74)
    print("O CONJUNTO — quadros da C07, rotulados pelo plano de onde saíram")
    print("=" * 74)
    conjunto = juntar_quadros()
    if len(conjunto) < 6:
        print("  ✗ quadros de menos para medir")
        return 1
    contagem = defaultdict(int)
    for _, _, plano in conjunto:
        contagem[plano] += 1
    print(f"  {len(conjunto)} quadros · " +
          " · ".join(f"{p}: {n}" for p, n in sorted(contagem.items())))

    caminhos = [c for c, _, _ in conjunto]

    print()
    print("=" * 74)
    print("MOTOR 1 — pHash (0 MB, PIL + numpy)")
    print("=" * 74)
    comeco = time.monotonic()
    assinaturas = [phash(c) for c in caminhos]
    tempo_hash = time.monotonic() - comeco
    p_hash = [[parecenca_phash(a, b) for b in assinaturas] for a in assinaturas]
    acerto_hash = medir("pHash", p_hash, conjunto)
    print(f"    tempo          {tempo_hash * 1000 / len(caminhos):.0f} ms por quadro")

    print()
    print("=" * 74)
    print("MOTOR 2 — embedding ONNX (MobileNetV2)")
    print("=" * 74)
    vetores, tempo_onnx, mb = vetores_onnx(caminhos)
    acerto_onnx = 0.0
    if vetores:
        p_onnx = [[float(a @ b) for b in vetores] for a in vetores]
        acerto_onnx = medir("ONNX", p_onnx, conjunto)
        print(f"    tempo          {tempo_onnx * 1000 / len(caminhos):.0f} ms por quadro")
        print(f"    modelo         {mb:.0f} MB")
    else:
        print("  ⚠️ não medido (modelo indisponível)")

    print()
    print("=" * 74)
    ao_acaso = max(contagem.values()) / len(conjunto)
    print(f"  ao acaso ....... {ao_acaso:.0%}  (chutar sempre o plano mais comum)")
    print(f"  pHash .......... {acerto_hash:.0%}")
    print(f"  ONNX ........... {acerto_onnx:.0%}" if vetores else "  ONNX ........... —")
    print()
    print("  ⇒ o que decide não é só o acerto: é o acerto que sobra DEPOIS de descontar")
    print("    o acaso, e quanto custa em MB e em ms por quadro do acervo.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
