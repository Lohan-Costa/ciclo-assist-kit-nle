"""O arquivo de log — e a decisão do que NÃO entra nele.

## Por que existe

Sem arquivo, um defeito na estação do editor é invisível: o serviço sobe pelo `.vbs` da
Inicialização, sem console, e a saída vai para lugar nenhum. O relato que chega é *"não
funcionou"*, e não há o que olhar.

⭐ **E a casa já pagou por não registrar.** O `mcapi.py` do projeto anterior carrega o
aviso: *"ESTE MÓDULO DECIDE ONDE A MÍDIA ESTÁ, e até 2026-08-27 não registrava NADA.
Quando o app diz 'clipes não encontrados no disco', o log precisa responder — sem ninguém
por perto, num relato de campo de quem testa no Nexis — que caminho o Avid disse, e por que
ele não serviu."*

⇒ **Caminho de mídia e nome de bin ENTRAM.** São material do cliente, e são exatamente o
que torna um defeito de campo diagnosticável. A troca é consciente.

## ⛔ O que NÃO entra, e é o mais sensível

**O texto da conversa** — nem a pergunta do editor, nem a resposta do Claude. Ele não é
necessário para diagnosticar (para isso bastam "houve turno", "que ferramenta rodou", "o
que falhou"), e é o que mais expõe o trabalho de quem está editando: uma pergunta carrega
a intenção criativa, não só o nome do arquivo.

⚠️ `CICLOASSIST_LOG=debug` **liga** o conteúdo. É deliberado e o docstring do campo diz
isso: quem liga sabe o que está fazendo, e desligar é voltar ao padrão.

## Retenção

**7 dias.** Rotação à meia-noite mais uma varredura no arranque, porque a rotação sozinha
não basta: ela só acontece quando o processo está de pé, e um serviço que passou o mês
desligado nunca rolaria. A varredura fecha esse buraco.
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import time
from pathlib import Path

#: Quantos dias de log ficam no disco. É o compromisso do documento de ameaças.
DIAS = 7

#: Teto por arquivo. A rotação é por DIA; isto existe para um dia muito falante não
#: encher o disco do editor.
MAX_BYTES = 8 * 1024 * 1024

FORMATO = "%(asctime)s  %(levelname)-7s %(name)-28s %(message)s"


def pasta() -> Path:
    """Onde os logs vivem. Ao lado do cache, e **nunca** na pasta do projeto do editor."""
    do_ambiente = os.environ.get("CICLOASSIST_LOGS")
    if do_ambiente:
        return Path(do_ambiente)
    from .config import pasta as pasta_de_dados   # a conta é UMA, e mora lá
    return pasta_de_dados() / "logs"


def _limpar_antigos(destino: Path) -> int:
    """Apaga o que passou da retenção.

    ⚠️ **A rotação sozinha não cumpre a promessa.** O `TimedRotatingFileHandler` só rola
    quando o processo está rodando; um serviço desligado por um mês guardaria o log do mês
    passado intacto. Varrer no arranque é o que faz "7 dias" ser verdade, e não intenção.
    """
    limite = time.time() - DIAS * 86400
    apagados = 0
    try:
        for arquivo in destino.glob("cicloassist.log*"):
            try:
                if arquivo.stat().st_mtime < limite:
                    arquivo.unlink()
                    apagados += 1
            except OSError:
                continue
    except OSError:
        pass
    return apagados


class _RotacaoDiariaComTeto(logging.handlers.TimedRotatingFileHandler):
    """Rola à meia-noite **ou** quando o arquivo passa do teto.

    A stdlib traz as duas políticas separadas, e nenhuma sozinha serve: só por tempo, um
    dia ruim enche o disco; só por tamanho, a promessa de "7 dias" não tem como ser feita.
    """

    def shouldRollover(self, record: logging.LogRecord) -> int:  # noqa: N802
        if super().shouldRollover(record):
            return 1
        try:
            if self.stream and self.stream.tell() >= MAX_BYTES:
                return 1
        except (OSError, ValueError):
            pass
        return 0


def configurar(nivel: str = "info") -> Path | None:
    """Liga o log em arquivo e no console. Devolve o caminho do arquivo, ou `None`.

    ⚠️ **Nunca deixa a falta de log derrubar o serviço.** Disco cheio, pasta sem
    permissão, antivírus segurando o arquivo — nada disso pode impedir o editor de
    trabalhar. Sem arquivo, o console continua recebendo.
    """
    nivel_real = getattr(logging, nivel.upper(), logging.INFO)
    raiz = logging.getLogger()
    raiz.setLevel(nivel_real)
    for h in list(raiz.handlers):
        raiz.removeHandler(h)

    console = logging.StreamHandler()
    console.setFormatter(logging.Formatter(FORMATO, datefmt="%H:%M:%S"))
    raiz.addHandler(console)

    destino = pasta()
    try:
        destino.mkdir(parents=True, exist_ok=True)
        apagados = _limpar_antigos(destino)
        arquivo = destino / "cicloassist.log"
        em_arquivo = _RotacaoDiariaComTeto(
            arquivo, when="midnight", backupCount=DIAS, encoding="utf-8", delay=True
        )
        em_arquivo.setFormatter(logging.Formatter(FORMATO))
        raiz.addHandler(em_arquivo)
    except OSError as e:
        logging.getLogger("cicloassist").warning(
            "sem arquivo de log (%s); só console", e
        )
        return None

    log = logging.getLogger("cicloassist")
    log.info("log em %s (retenção de %d dias)", arquivo, DIAS)
    if apagados:
        log.info("%d arquivo(s) de log fora da retenção apagados", apagados)
    if nivel_real <= logging.DEBUG:
        # ⚠️ Quem liga o debug precisa ver na cara que passou a gravar conteúdo.
        log.warning(
            "modo debug: o TEXTO das conversas passa a ir para o log. "
            "Desligue quando terminar (CICLOASSIST_LOG=info)."
        )
    return arquivo
