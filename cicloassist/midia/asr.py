"""O motor de transcrição — faster-whisper, sem torch.

⚠️ **A regra da stack é herdada e não negociável: nada de torch.** O `openai-whisper`
levaria o pacote de ~2 GB para ~6 GB. O `faster-whisper` roda em CTranslate2 e é o **mesmo
motor que o Media Composer 2025 embarca** (`faster_whisper` + `small-int8`, 243 MB), o que
é uma validação independente de que ele dá conta deste material.

⭐ **A transcrição é do MASTER inteiro, em tempo do MASTER.** Igual aos quadros, e pela
mesma razão: um subclipe é um recorte, e recortar o texto depois é barato. Transcrever por
subclipe faria o mesmo áudio passar pelo ASR uma vez por recorte — e um groupclipe de
multicam montado depois não acharia nada pronto.
"""

from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

log = logging.getLogger("cicloassist.midia.asr")

#: `small` é o que o Media Composer embarca, e é o equilíbrio certo para diária de ficção:
#: 244 MB, rápido em CPU, e bom o suficiente em português. Trocável pela variável de
#: ambiente quando alguém quiser pagar mais por precisão.
MODELO = os.environ.get("CICLOASSIST_MODELO_ASR", "small")

#: `int8` na CPU: metade da memória e cerca do dobro da velocidade, com perda que não
#: aparece em fala gravada de perto.
COMPUTACAO = "int8"

IDIOMA = "pt"

#: ⭐⭐ Tempo por PALAVRA, e não só por frase.
#:
#: O editor pediu: *"transcrever só dá timestamp por frase, não por palavra — limita a
#: precisão de qualquer corte que precise cair no meio de uma frase"*. E era exatamente
#: isso que impedia o corte em J de cair no "sobe comigo" e não na frase inteira.
#:
#: ⚠️ Custa mais: o faster-whisper roda um alinhamento a mais por segmento. Vale, porque
#: o resultado vai para o cache e um take é transcrito uma vez só na vida.
POR_PALAVRA = True

ASSINATURA = {"motor": "faster-whisper", "modelo": MODELO, "computacao": COMPUTACAO,
              "idioma": IDIOMA, "por_palavra": POR_PALAVRA}

_modelo = None


class AsrIndisponivel(RuntimeError):
    """O motor de transcrição não pôde ser carregado."""


def carregar():
    """O modelo, carregado uma vez por processo.

    ⚠️ O primeiro uso **baixa o modelo** (244 MB) e demora. Nas vezes seguintes ele vem do
    cache do Hugging Face no disco. Isso precisa aparecer na interface: sem aviso, a
    primeira transcrição parece travamento.
    """
    global _modelo
    if _modelo is not None:
        return _modelo
    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise AsrIndisponivel(
            "O motor de transcrição não está instalado (faster-whisper)."
        ) from e
    log.info("carregando o modelo %s (%s)…", MODELO, COMPUTACAO)
    _modelo = WhisperModel(MODELO, device="cpu", compute_type=COMPUTACAO)
    return _modelo


@dataclass
class Fala:
    """Um trecho falado, em segundos **do master**."""

    inicio: float
    fim: float
    texto: str
    #: Média de confiança do reconhecedor, de 0 a 1. Vira procedência no plano.
    certeza: float
    #: ⭐ Cada palavra com o tempo dela, em segundos do master: `{t, fim, palavra}`.
    #:
    #: ⚠️ Lista **vazia** numa transcrição antiga, feita antes de isto existir. A
    #: assinatura do estágio (`ASSINATURA`) mudou junto, então o cache velho cai sozinho e
    #: o take é reprocessado na próxima vez — mas quem lê precisa aguentar a lista vazia
    #: até lá, em vez de estourar.
    palavras: list = field(default_factory=list)

    def como_dicionario(self) -> dict:
        return asdict(self)


def transcrever(wav: Path | str, aviso=None) -> list[Fala]:
    """O WAV inteiro → falas com tempo.

    ⚠️ `vad_filter` corta silêncio ANTES do reconhecimento. Sem ele, o Whisper alucina em
    trechos mudos — e num set há muito silêncio entre "ação" e a primeira fala. O sintoma
    é texto plausível colado num pedaço onde ninguém falou, que é pior que nenhum texto.

    `aviso(fracao, texto)` é chamado conforme as falas saem, para quem quiser mostrar
    andamento.

    ⭐⭐ **O `transcribe` do faster-whisper devolve um GERADOR**, e o trabalho só acontece
    enquanto ele é consumido. É isso que permite relatar progresso de verdade, fala a
    fala, em vez de uma barra falsa que anda sozinha — e é também por isso que o laço
    abaixo não pode virar um `list(...)` por conveniência.

    ⚠️ Este módulo não conhece painel nem turno: quem chama passa o callback. É o que
    mantém `midia/` utilizável por script, teste e spike sem serviço no ar.
    """
    modelo = carregar()
    segmentos, info = modelo.transcribe(
        str(wav),
        language=IDIOMA,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
        condition_on_previous_text=False,  # evita arrastar erro de um trecho para o outro
        word_timestamps=POR_PALAVRA,
    )

    # A duração que o VAD deixou de pé é o denominador honesto: o que sobrou de FALA.
    # Com a duração bruta, um take com dois minutos de silêncio no fim fecharia em 60%.
    total_s = float(getattr(info, "duration_after_vad", 0)
                    or getattr(info, "duration", 0) or 0)

    falas: list[Fala] = []
    for s in segmentos:
        if aviso is not None and total_s:
            aviso(min(1.0, (s.end or 0) / total_s), (s.text or "").strip()[:60])
        texto = (s.text or "").strip()
        if not texto:
            continue
        # `avg_logprob` é log-probabilidade média; virar 0–1 dá um número que o editor
        # consegue ler sem saber o que é logaritmo.
        certeza = max(0.0, min(1.0, 1.0 + (s.avg_logprob or -1.0) / 2.0))
        # ⭐ As palavras com tempo próprio. É o que deixa um corte cair DENTRO da frase —
        #   pegar só o "sobe comigo" e não a fala inteira em que ele está.
        palavras = [
            {"t": round(w.start, 3), "fim": round(w.end, 3), "palavra": (w.word or "").strip()}
            for w in (getattr(s, "words", None) or [])
            if (w.word or "").strip()
        ]
        falas.append(Fala(round(s.start, 3), round(s.end, 3), texto, round(certeza, 3),
                          palavras))
    return falas


def recortar(falas: list[dict], inicio_s: float, fim_s: float) -> list[dict]:
    """As falas que caem dentro de uma janela do master.

    ⚠️ **Inclui quem ATRAVESSA a borda, não só quem está inteiramente dentro.** Uma fala
    que começa antes do in-point e termina depois dele é justamente o caso que interessa
    a quem procura onde cortar — descartá-la faria a fala sumir do relatório exatamente
    onde ela importa.
    """
    return [
        f for f in falas
        if float(f.get("fim", 0)) > inicio_s and float(f.get("inicio", 0)) < fim_s
    ]


# ── o respiro do corte ───────────────────────────────────────────────────────
#
# ⭐⭐ MEDIDO em 2026-09-11 (`spikes/o_respiro_do_corte.py`), som direto real, sobre as
# falas que o editor apontou em campo:
#
#     voz ANTES do que o ASR diz    mediana   10 ms   pior  300 ms
#     voz DEPOIS do que o ASR diz   mediana  230 ms   pior  350 ms   ← 5,5 frames a 24 fps
#
# ⇒ São DOIS problemas diferentes, e confundi-los produz o conserto errado:
#
# 1. **A cauda é cortada por erro de MEDIDA.** O ASR fecha a palavra cedo — "sobe comigo"
#    vira "sobe co…". Isso é defeito, e o conserto é estender o fim até onde a voz
#    realmente acaba.
# 2. **A entrada colada NÃO é erro de medida** — o ASR acerta o ataque com 10 ms. Cortar
#    exatamente no ataque é uma escolha de MONTAGEM ruim: não sobra ar, e a primeira
#    sílaba parece decepada mesmo estando inteira. O conserto é ofício, não medição.

#: Quanto se abre ANTES da primeira palavra. ⚠️ É respiro de montagem, não correção: o
#: ASR acerta o ataque. Quatro frames a 24 fps é o que dá ar sem trazer a fala anterior.
RESPIRO_ANTES_S = 0.17

#: Quanto se abre DEPOIS da última palavra. ⭐ Cobre o pior caso medido (350 ms) com folga
#: de sobra: sem isto, a última sílaba fica de fora e o corte soa amputado.
RESPIRO_DEPOIS_S = 0.40

#: Abaixo disto, duas falas seguidas do MESMO take são um corte só.
#:
#: ⭐ Corroborado por fora: as skills do Jumper — produto pago, parceiro oficial da Avid —
#: mandam *"if consecutive selected segments from the same source have only a short gap,
#: use one continuous source clip containing that gap"*. A regra é de ofício, não de
#: engenharia: a pausa é atuação, e a ambiência que some no meio denuncia o corte.
VAO_DE_JUNTAR_S = 1.2

#: O vão mínimo que se deixa para a fala vizinha. ⛔ **O respiro nunca invade o vizinho**:
#: trazer a cauda do outro ator para dentro do corte é pior que cortar rente.
VAO_MINIMO_S = 0.08

#: ⛔⛔ Abaixo disto, o vão entre duas falas NÃO FOI MEDIDO — o faster-whisper encadeou os
#: segmentos e a borda é artefato dele, não silêncio que existiu.
#:
#: ⚠️⚠️ **MEDIDO em 2026-09-12 no cache desta máquina: 169 de 715 bordas (23,6%) são
#: exatamente 0,000 s.** Fala humana não faz isso um quarto das vezes. E o preço de
#: acreditar nelas era alto: `min(fim + RESPIRO, proxima - VAO_MINIMO)` dava um número
#: MENOR que `fim`, o `max(..., fim)` colava o corte no fim do ASR, e **176 de 727 falas
#: (24%) ficavam com respiro ZERO** — entre elas todas as "Sobe comigo." que o editor viu
#: virar "sobe co…" em campo, duas vezes, em dois pareceres seguidos.
#:
#: ⇒ Quando a borda é artefato, o vizinho não manda: a voz desta fala continua 210 ms
#: (pior caso 310 ms) depois do que o ASR diz, e o segmento seguinte começa mais tarde do
#: que ele declara. Num diálogo montado, a fala seguinte vem de OUTRO take — então o que
#: entra aqui é a própria cauda, não a voz do outro ator.
VAO_NAO_MEDIDO_S = 0.02


def com_respiro(falas: list[dict], piso_s: float = 0.0,
                teto_s: float | None = None) -> list[dict]:
    """Acrescenta a cada fala onde o CORTE deve entrar e sair.

    ⭐ Os campos `corte_inicio` e `corte_fim` são os que devem virar in/out — `inicio` e
    `fim` continuam sendo o que o ASR mediu, para quem precisar do dado cru.

    ⛔ O respiro é limitado por três coisas, nesta ordem: a fala vizinha (com um vão
    mínimo), o começo e o fim do material, e o tamanho pedido. Sem os limites, abrir
    400 ms no fim de uma fala rápida engoliria a resposta do outro ator.
    """
    saida = []
    for i, fala in enumerate(falas):
        inicio = float(fala.get("inicio") or 0.0)
        fim = float(fala.get("fim") or inicio)

        anterior = float(falas[i - 1].get("fim") or 0.0) if i else piso_s
        proxima = (float(falas[i + 1].get("inicio") or 0.0)
                   if i + 1 < len(falas) else (teto_s if teto_s is not None else fim + 99))

        corte_inicio = max(inicio - RESPIRO_ANTES_S, anterior + VAO_MINIMO_S, piso_s)
        # ⚠️ Nunca DEPOIS do que já era: com falas coladas, o vão mínimo poderia empurrar
        #    o início para dentro da própria fala e cortar a palavra de verdade.
        corte_inicio = min(corte_inicio, inicio)

        # ⛔⛔ A borda que o ASR encadeou não é borda medida — e acreditar nela decepava a
        #    última sílaba em 24% das falas. Só se limita pelo vizinho quando houve
        #    silêncio de verdade entre os dois.
        if proxima - fim <= VAO_NAO_MEDIDO_S:
            corte_fim = fim + RESPIRO_DEPOIS_S
        else:
            corte_fim = min(fim + RESPIRO_DEPOIS_S, proxima - VAO_MINIMO_S)
        corte_fim = max(corte_fim, fim)

        # ⭐⭐ A voz MEDIDA na lapela (`midia/voz.py`, L2 do plano 2026-11-11) só ESTENDE o corte (decisão do autor):
        #   onde a voz real passa do respiro, o corte vai até ela; nunca fica mais curto que o de antes. E continua sem
        #   invadir o vizinho — voz que passa do início da fala seguinte é sobreposição, não respiro.
        estendido = False
        if fala.get("voz_inicio") is not None:
            alvo = max(float(fala["voz_inicio"]), anterior + VAO_MINIMO_S, piso_s)
            if alvo < corte_inicio:
                corte_inicio, estendido = alvo, True
        if fala.get("voz_fim") is not None:
            limite = (proxima - VAO_MINIMO_S) if proxima - fim > VAO_NAO_MEDIDO_S else float("inf")
            alvo = min(float(fala["voz_fim"]), limite)
            if alvo > corte_fim:
                corte_fim, estendido = alvo, True
        if teto_s is not None:
            corte_fim = min(corte_fim, teto_s)

        saida.append({**fala,
                      "corte_inicio": round(corte_inicio, 3),
                      "corte_fim": round(corte_fim, 3),
                      **({"corte_pela_voz": True} if estendido else {}),
                      # ⭐ O silêncio até a próxima fala DESTE mesmo take. Duas falas
                      #   seguidas separadas por pouco devem virar UM corte contínuo — a
                      #   pausa entre elas é atuação, e a ambiência que some no meio
                      #   denuncia o corte. Quem decide é quem monta; o dado é nosso.
                      "vao_ate_a_proxima": (round(proxima - fim, 2)
                                            if i + 1 < len(falas) else None)})
    return saida
