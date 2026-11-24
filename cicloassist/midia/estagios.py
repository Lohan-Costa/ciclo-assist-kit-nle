"""Os estágios do cache: o nome de cada um e a RECEITA atual dele.

⛔⛔ **Uma conta só, e ela mora aqui.** A assinatura de um estágio já vivia em dois
lugares — `mcp/ferramentas/visual.py` conhecia a dos quadros, `mcp/ferramentas/fala.py`
montava a da transcrição —, e isso bastava enquanto só quem PROCESSA precisava dela.
A aba Vetores precisa da mesma conta para dizer "atualizado", e uma terceira cópia é
exatamente o defeito que o `cache.raiz()` documenta: cópias que divergem sem nada acusar,
e o sintoma é um cache que *parece* velho (ou *parece* novo) sem erro nenhum.

⭐ A assinatura é o que faz o cache cair sozinho quando a receita muda. Mudou a largura do
quadro, o modelo do ASR ou a mixagem do áudio, `Midia.precisa_refazer()` responde `True` e
o material é refeito na próxima vez que alguém pedir.
"""

from __future__ import annotations

from typing import Any

from . import asr as _asr
from . import audio as _audio
from . import frames as _frames

#: Quadros JPEG extraídos da imagem, numerados em tempo do MASTER.
QUADROS = "quadros"

#: As falas do master inteiro, em segundos do master, com as palavras.
TRANSCRICAO = "transcricao"

#: ⭐ O vetor visual de cada quadro amostrado — o que responde "planos parecidos com
#: este". Ver `midia/vetores.py`.
VETORES = "vetores"

#: A ordem em que aparecem na tela do editor.
TODOS = (QUADROS, TRANSCRICAO, VETORES)

#: ⭐ As fronteiras de plano e os trechos da decupagem MICRO (`midia/cortes.py`). Fora de
#: `TODOS` de propósito: a aba mostra a micro pela contagem de trechos, não por receita.
CORTES = "cortes"


def assinatura(estagio: str) -> dict[str, Any]:
    """A receita com que este estágio é feito HOJE.

    ⚠️ A da transcrição é a soma de duas: o ASR e a mixagem que o alimenta. Mudar a taxa
    de amostragem sem invalidar a transcrição entregaria texto feito de outro áudio.
    """
    if estagio == QUADROS:
        return dict(_frames.ASSINATURA)
    if estagio == TRANSCRICAO:
        return {**_asr.ASSINATURA, **_audio.ASSINATURA_MIXAGEM}
    if estagio == VETORES:
        # ⚠️ Import local: `vetores` importa `frames`, que importa daqui em tempo de
        #   execução. No topo, os dois se importariam em círculo na partida.
        from . import vetores as _vetores
        return dict(_vetores.ASSINATURA)
    if estagio == CORTES:
        from . import cortes as _cortes
        return dict(_cortes.ASSINATURA)
    raise KeyError(f"estágio desconhecido: {estagio!r}")
