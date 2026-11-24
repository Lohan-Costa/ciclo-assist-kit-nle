"""Enquanto o painel está aberto é a MESMA visita; depois do silêncio, é outra.

⭐⭐ **Decisão do editor (2026-09-14): abrir o Media Composer é começar do zero.** A
assistência aqui é pontual por operação — ela não precisa lembrar de ontem —, e o preço de
lembrar é cobrado em token sem ninguém pedir: *"é melhor o usuário pedir um `--resume`
para voltar a uma sessão anterior do que abrir o Media Composer, fazer um pedido e só
depois perceber que está gastando com uma sessão que não é zerada."*

⛔⛔ **O caso real que ele descreve foi medido (2026-09-12).** Ele fechou o Media Composer
sem `/clear`, reabriu, viu a tela em branco — e a conversa seguia inteira do outro lado.
O teste seguinte leu **10,8× mais contexto** que a mesma tarefa numa conversa limpa:
6,5 milhões de tokens contra 690 mil. **Tela em branco, contexto cheio** é o defeito que
esta peça fecha; o aviso de fio continuado avisava, mas avisar não é impedir.

## O que conta como "outra visita"

| aconteceu | vira visita nova? | por quê |
|---|---|---|
| Reload no painel (dev) | **não** | volta em ~1 s: silêncio curto demais |
| trocar de aba, mexer no MC | não | o painel continua batendo |
| fechar o painel e reabrir | sim | ninguém bate nesse meio-tempo |
| fechar o Media Composer | sim | o painel morre com ele |
| reiniciar o serviço | sim | a visita mora na MEMÓRIA deste processo |
| o serviço CAIU e o supervisor o religou | **não** | cair não é gesto do editor (abaixo) |

⭐ **De propósito a visita NÃO é gravada em disco.** Um `visita_id` persistido sobreviveria
ao reinício do serviço, e "reiniciei o Ciclo Assist" é o gesto mais parecido com "quero
começar de novo" que existe aqui.

⭐⭐ **A exceção: o serviço que CAIU** (2026-11-04). A borda do piloto derrubou o processo no
meio de um `organizar_bins` (access violation), o supervisor do app o religou, e a conversa
do editor sumiu com a operação pela metade — sem ele ter pedido nada. Agora a visita (e os
fios dela) vão para `visita.json`, e SÓ um serviço subido com `CICLOASSIST_RELIGADO=1` (o
supervisor religando, nunca o app abrindo) os retoma — e só dentro de `SILENCIO_S`, a mesma
régua de sempre. Fechar e abrir o app continua sendo começar do zero.

⚠️ E o silêncio precisa de quem faça barulho: o painel bate de tempos em tempos
(`PULSO_MS` no `painel.js`). Sem o pulso, qualquer pausa de conversa seria lida como
ausência — por isso o limite daqui é **maior que o pulso de lá**, com folga para uma
batida perdida.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid

log = logging.getLogger("cicloassist.servico.presenca")

#: Silêncio maior que isto quer dizer que o painel foi embora (ou o Media Composer).
#:
#: ⚠️ O painel bate a cada 20 s, também quando está escondido — e webview **estrangula
#: timer de página escondida**, até cerca de um por minuto. Com 180 s cabem três pulsos
#: mesmo estrangulados: o painel atrás da janela do Media Composer, que é onde ele passa o
#: dia enquanto o editor monta, nunca é confundido com painel fechado.
#:
#: ⚠️ O preço de ser generoso aqui é baixo: fechar o MC e reabrir em menos de três minutos
#: mantém a conversa. O caso que importa — voltar no dia seguinte — está muito além disso.
SILENCIO_S = 180

_trava = threading.Lock()
_visita: str = ""
_visto_em: float = 0.0
_fios: dict[str, str] = {}


def _arquivo():
    from .config import pasta
    return pasta() / "visita.json"


def _gravar() -> None:
    """A visita e os fios dela, para um serviço RELIGADO retomar. ⚠️ Nunca levanta: é chamado no pulso."""
    try:
        destino = _arquivo()
        destino.parent.mkdir(parents=True, exist_ok=True)
        tmp = destino.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"visita": _visita, "visto_em": _visto_em, "fios": _fios}), encoding="utf-8")
        tmp.replace(destino)
    except Exception:  # noqa: BLE001
        log.debug("não consegui gravar a visita", exc_info=True)


def guardar_fios(fios: dict[str, str]) -> None:
    """O mapa conversa → visita de `rotas` mudou: vai junto para o disco."""
    with _trava:
        _fios.clear()
        _fios.update(fios)
        _gravar()


def retomar() -> dict[str, str]:
    """⭐ Só num serviço RELIGADO pelo supervisor (`CICLOASSIST_RELIGADO=1`): devolve os fios da visita
    gravada e a continua, se ela calou há menos de `SILENCIO_S`. Em qualquer outro caso, `{}`."""
    global _visita, _visto_em
    if os.environ.get("CICLOASSIST_RELIGADO") != "1":
        return {}
    try:
        dado = json.loads(_arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    silencio = time.time() - float(dado.get("visto_em") or 0)
    if not dado.get("visita") or silencio > SILENCIO_S:
        log.info("religado, mas a visita gravada calou há %.0f s: conversa nova", silencio)
        return {}
    with _trava:
        _visita, _visto_em = str(dado["visita"]), float(dado["visto_em"])
        _fios.clear()
        _fios.update(dado.get("fios") or {})
    log.info("religado pelo supervisor: a visita %s continua (%d conversa[s])", _visita, len(_fios))
    return dict(_fios)


def bater() -> str:
    """O painel falou. Devolve a visita a que esta fala pertence.

    Se o silêncio anterior passou de `SILENCIO_S`, começa uma visita NOVA aqui.
    """
    global _visita, _visto_em
    agora = time.time()
    with _trava:
        if not _visita or agora - _visto_em > SILENCIO_S:
            anterior, _visita = _visita, uuid.uuid4().hex[:12]
            if anterior:
                log.info("visita nova (%.0f s de silêncio): %s → %s",
                         agora - _visto_em, anterior, _visita)
        _visto_em = agora
        _gravar()
        return _visita


def atual() -> str:
    """A visita de agora, sem contar como batida. Vazio antes da primeira."""
    return _visita


def silencio_s() -> float:
    """Há quanto tempo o painel não fala. `0` se ele nunca falou."""
    return (time.time() - _visto_em) if _visto_em else 0.0


def esquecer() -> None:
    global _visita, _visto_em
    with _trava:
        _visita = ""
        _visto_em = 0.0
