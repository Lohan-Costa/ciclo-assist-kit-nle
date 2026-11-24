"""A lista do INSERT PARA COR/VFX: o botão Coletar e as decisões sobre o que ele trouxe.

O editor seleciona segmentos na timeline e aperta Coletar; a lista só cresce, cada item tem um
X, e "Limpar lista" zera. Dois lados, separados de propósito:

- `capturar(mc)` — conversa com o Media Composer, pelo roteiro MEDIDO em 2026-09-24 (banco,
  `plugins/avid-panel-sdk/copia-da-timeline.md`):

      Ctrl+0 → Ctrl+C (teclado.py)
      → 6292 "Clipboard Contents": a cópia abre no monitor ATIVO (Source ou Record)
      → acha a cópia pelo monitor cujo mob MUDOU
      → CreateSubClip(use_clip_bounds, end_frame=-1) na bin `zMagicLink/coleta`
      → devolve a sequência ao Record, se a cópia a tomou
      → Save → lê a cópia e a sequência pela .avb (ADR 0015: nunca ExportFile)
      → apaga a bin da coleta e a recria VAZIA (sem entrada vermelha no projeto)

- `Coleta.decidir(...)` — lógica pura: nada novo, outra sequência, várias trilhas pedem
  OK | Cancelar, o resto entra na lista. Testada sem Avid (`tests/test_coleta.py`).

⚠️⚠️ A cópia do Avid é o TRECHO do primeiro ao último segmento selecionado em cada trilha, não
a seleção (medido com gabarito do autor). O painel orienta a coletar clipes separados um por
vez; o que sobrar sai no X.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

log = logging.getLogger("delapraca.coleta")

PASTA_NO_PROJETO = "zMagicLink"     # o "z" joga a pasta para o fim da lista do projeto
BIN_DA_COLETA = "coleta"

CONTEUDO_DA_COPIA = 6292            # DoCommand "Clipboard Contents"
ASSENTAR_S = 1.5                    # o 6292 volta antes de o monitor carregar


class ColetaFalhou(RuntimeError):
    """A coleta não aconteceu — o texto diz por quê, para o editor."""


# ── as decisões (puras) ──────────────────────────────────────────────────────────────────


class Coleta:
    """A lista de um insert. Uma sequência por vez."""

    def __init__(self) -> None:
        self.sequencia: dict = {}            # {"mob_id": api, "nome": str}
        self.itens: list[dict] = []
        self.ultima: tuple | None = None     # impressão digital da última cópia coletada
        self.pendente: dict | None = None    # à espera de OK | Cancelar
        self._insistiu: tuple | None = None  # a mesma cópia pedida duas vezes seguidas
        self._lock = threading.Lock()

    def estado(self) -> dict:
        from carta_aberta.insert import trilhas_da_selecao

        return {"sequencia": dict(self.sequencia), "itens": [dict(i) for i in self.itens],
                "trilhas": trilhas_da_selecao(self.itens),
                "pendente": dict(self.pendente) if self.pendente else None}

    def decidir(self, sequencia: dict, itens: list[dict], avisos: list[str]) -> dict:
        """O que fazer com o que a cópia trouxe. Devolve `{"status": …, "texto": …}`.

        status: `adicionado` · `nada_novo` · `outra_sequencia` · `confirmar`.
        """
        from carta_aberta.insert import chave, impressao_digital, trilhas_da_selecao

        with self._lock:
            if not itens:
                self.pendente = None
                texto = ("a última cópia não é desta sequência — selecione na timeline e "
                         "aperte Coletar de novo") if avisos else \
                        "nada selecionado na timeline"
                return {"status": "outra_sequencia" if avisos else "nada_novo", "texto": texto,
                        "avisos": avisos}

            impressao = impressao_digital(itens)
            ja = {chave(i) for i in self.itens} if self.sequencia.get("mob_id") == sequencia.get("mob_id") else set()
            novos = [i for i in itens if chave(i) not in ja]
            self.pendente = None
            if not novos:
                self._insistiu = None
                return {"status": "nada_novo", "avisos": avisos,
                        "texto": "esses clipes já estão na lista"}
            if impressao == self.ultima and self._insistiu != impressao:
                # ⚠️ Sem seleção, o Ctrl+C do Avid MANTÉM a cópia anterior (medido): trazer a
                # mesma coisa de novo é o sinal de que nada foi selecionado. Mas o editor pode
                # ter LIMPADO a lista e selecionado os mesmos clipes de propósito — e as duas
                # coisas são indistinguíveis. Apertar de novo, em seguida, é a insistência.
                self._insistiu = impressao
                return {"status": "nada_novo", "avisos": avisos,
                        "texto": "nada novo selecionado. Se quer os mesmos clipes de novo, "
                                 "aperte Coletar outra vez"}
            self._insistiu = None

            troca = bool(self.itens) and self.sequencia.get("mob_id") != sequencia.get("mob_id")
            trilhas = trilhas_da_selecao(novos)
            if troca or len(trilhas) > 1:
                self.pendente = {"sequencia": dict(sequencia), "itens": novos,
                                 "impressao": impressao, "troca": troca, "trilhas": trilhas,
                                 "avisos": avisos}
                if troca:
                    texto = (f"a lista é de “{self.sequencia.get('nome') or 'outra sequência'}”. "
                             f"Trocar pela seleção de “{sequencia.get('nome') or 'esta sequência'}”?")
                else:
                    texto = (f"a seleção pega {len(trilhas)} trilhas ({', '.join(trilhas)}) — "
                             f"{len(novos)} clipe(s). É isso?")
                return {"status": "confirmar", "texto": texto, "trilhas": trilhas,
                        "itens": novos, "avisos": avisos}

            return self._somar(sequencia, novos, impressao, avisos)

    def confirmar(self, sim: bool) -> dict:
        with self._lock:
            p, self.pendente = self.pendente, None
            if not p:
                return {"status": "nada_pendente", "texto": "não há nada esperando confirmação"}
            if not sim:
                return {"status": "cancelado", "texto": "nada entrou na lista"}
            if p["troca"]:
                self.itens, self.sequencia = [], {}
            return self._somar(p["sequencia"], p["itens"], p["impressao"], p["avisos"])

    def _somar(self, sequencia: dict, novos: list[dict], impressao: tuple, avisos: list) -> dict:
        self.sequencia = dict(sequencia)
        self.itens.extend(novos)
        self.itens.sort(key=lambda i: (int(i["track"]), i["timeline_tc_in"]))
        self.ultima = impressao
        return {"status": "adicionado", "novos": len(novos), "avisos": avisos,
                "texto": f"{len(novos)} clipe(s) na lista"}

    def remover(self, chave_item: list | tuple) -> bool:
        from carta_aberta.insert import chave

        alvo = (int(chave_item[0]), str(chave_item[1]), str(chave_item[2]))
        with self._lock:
            antes = len(self.itens)
            self.itens = [i for i in self.itens if chave(i) != alvo]
            return len(self.itens) < antes

    def limpar(self) -> None:
        with self._lock:
            self.itens, self.pendente = [], None
            # ⚠️ A última impressão FICA: sem ela, apertar Coletar sem seleção logo depois de
            # limpar traria de volta a cópia que o editor acabou de descartar.


# ── a captura (conversa com o Media Composer) ────────────────────────────────────────────


def _comando(mc, command_id: int, limite_s: float = 15.0) -> None:
    """`DoCommand` esperando vaga: o anterior pode não ter acabado (ErrorType 73, medido)."""
    from avid.mcapi import McApiError

    fim = time.monotonic() + limite_s
    while True:
        try:
            mc._chamar("DoCommand", commandId=command_id)
            return
        except McApiError as e:
            if "more than one command" not in str(e) or time.monotonic() > fim:
                raise
            time.sleep(0.25)


def _monitores(mc) -> dict[int, str]:
    """`{tipo do monitor: mob}` — 0 = Source, 1 = Record (enum `ViewerType`)."""
    return {m.view_type: m.mob_id for m in mc._chamar("GetViewerMobs").body.mobs}


def _bin_da_coleta(mc) -> Path:
    """A `.avb` da coleta, VAZIA e ABERTA, pronta para o `CreateSubClip`.

    ⛔ CORRIGE (2026-09-25, primeira coleta com o autor): a versão anterior criava a bin e a
    FECHAVA, e o `CreateSubClip` numa bin fechada é recusado — `"Bin is not open."`
    (ErrorType 50). Nenhuma coleta pelo botão chegou a funcionar. O spike que mediu o ciclo
    gravava numa bin RECÉM-CRIADA, e o `CreateBin` a deixa aberta (flutuante).
    Por isso a receita medida (banco, `avid-panel-sdk/copia-da-timeline.md`): apagar a bin
    vazia que sobrou da coleta anterior e recriá-la — `CreateBin` com o mesmo nome de uma bin
    apagada funciona (medido) e devolve a bin aberta.

    ⚠️ O `CreateBin` exige que a pasta exista no disco (senão "Directory not found."); a pasta
    só aparece no projeto depois de o editor dar Refresh — a coleta não depende disso (medido).
    """
    from avid.acoes import Acoes

    projeto = Path((mc.projeto() or {}).get("path") or "")
    if not projeto.is_dir():
        raise ColetaFalhou("não achei a pasta do projeto aberto no Media Composer")
    pasta = projeto / PASTA_NO_PROJETO
    pasta.mkdir(exist_ok=True)
    caminho = pasta / f"{BIN_DA_COLETA}.avb"
    if caminho.exists():
        _fechar(mc, caminho)
        time.sleep(0.5)
        try:
            os.remove(caminho)
        except OSError as e:
            raise ColetaFalhou(f"não consegui limpar a bin da coleta ({e})") from None
    Acoes(mc).criar_bin(BIN_DA_COLETA, subpasta=PASTA_NO_PROJETO)
    time.sleep(1.0)   # o CreateBin volta antes de a bin estar pronta para receber (spike)
    return caminho


def _fechar(mc, caminho: Path) -> None:
    from avid.mcapi import McApiError

    try:
        mc.fechar_bin(str(caminho))
    except McApiError:
        log.debug("CloseBin %s recusado (já fechada?)", caminho.name)


def _zerar_bin(mc, caminho: Path) -> None:
    """Apaga a bin da coleta e a recria vazia e fechada. Nunca levanta: o resultado já existe
    (a coleta não pode morrer no acessório — memória do projeto)."""
    from avid.acoes import Acoes

    try:
        _fechar(mc, caminho)
        time.sleep(0.5)
        if caminho.exists():
            os.remove(caminho)
        Acoes(mc).criar_bin(BIN_DA_COLETA, subpasta=PASTA_NO_PROJETO)
        time.sleep(1.0)
        _fechar(mc, caminho)
    except Exception:  # noqa: BLE001
        log.warning("não consegui zerar a bin da coleta", exc_info=True)


def capturar(mc, trazer_mc: bool = False) -> tuple[dict, dict, dict]:
    """Copia a seleção e lê a cópia. Devolve `(sequencia, leitura_da_copia, leitura_da_sequencia)`.

    `sequencia` = `{"mob_id": api, "nome": …}` da sequência que estava no Record. `trazer_mc`: o pedido veio da
    janela do APP (o MC não está na frente) — ver `teclado.copiar_selecao`.
    """
    import relink_avb
    import teclado
    from avb_bin import segmentos as S
    from avid.acoes import Acoes
    from avid.mcapi import McApiError
    from relink_avb import esperar_bin_estabilizar

    # ⚠️ Antes de tudo: sem `DoCommand` (MC 2024) não há o "Clipboard Contents", e o `GetViewerMobs` de lá nem diz
    # qual é o Record — seguir daria "não há sequência na timeline" com a timeline na frente do editor.
    if not mc.tem("DoCommand"):
        raise ColetaFalhou("copiar a seleção da timeline precisa do Media Composer 2025 (o 2024 não abre "
                           "esses comandos pela API) — no 2024, envie a sequência inteira")
    antes = _monitores(mc)
    seq_mob = antes.get(1)
    if not seq_mob:
        raise ColetaFalhou("não há sequência na timeline — carregue a sequência no Record")
    bin_seq = mc.bin_do_mob(seq_mob)
    if not bin_seq or not Path(bin_seq).is_file():
        raise ColetaFalhou("a sequência da timeline não está numa bin salva do projeto")

    try:
        teclado.copiar_selecao(trazer_mc=trazer_mc)
    except teclado.TecladoIndisponivel as e:
        raise ColetaFalhou(str(e)) from None

    _comando(mc, CONTEUDO_DA_COPIA)
    time.sleep(ASSENTAR_S)
    depois = _monitores(mc)
    mudou = next((t for t in (0, 1) if depois.get(t) and depois.get(t) != antes.get(t)), None)
    if mudou is None:
        raise ColetaFalhou("não consegui abrir a seleção copiada — clique na timeline e tente "
                           "de novo")
    copia_mob = depois[mudou]

    caminho = _bin_da_coleta(mc)
    try:
        try:
            mc._chamar("CreateSubClip", destination_bin_path=str(caminho), mob_id=copia_mob,
                       use_clip_bounds=True, end_frame=-1, create_new_sequence=True)
        finally:
            if mudou == 1:
                # A cópia tomou a timeline do editor: a sequência volta, no MESMO ponto (o MC
                # lembra a posição por sequência — medido).
                mc.carregar_no_monitor([seq_mob], "Record")
        Acoes(mc).salvar()
        esperar_bin_estabilizar(caminho)
        from avb_export.reader import topen

        with topen(str(caminho)) as f:
            seqs = list(S.sequencias(f))
            if not seqs:
                raise ColetaFalhou("a seleção copiada veio vazia")
            # A bin é recriada vazia a cada coleta, mas o `CreateSubClip` põe nela também um
            # subclipe por clipe (`04-04-05.sub.01`). A cópia é a que o Avid chama
            # "Clipboard Contents…" (medido); sem o nome, a que tem mais trilhas.
            alvo = next((m for m in seqs if (getattr(m, "name", "") or "").lower()
                         .startswith("clipboard contents")), None) or \
                max(seqs, key=lambda m: len(list(getattr(m, "tracks", None) or [])))
            copia = S.ler_timeline(f, alvo)
    except McApiError as e:
        raise ColetaFalhou(f"o Media Composer recusou gravar a seleção: {e}") from None
    finally:
        _zerar_bin(mc, caminho)

    relink_avb.garantir_bin_no_disco(mc, bin_seq)
    sequencia = S.ler_timeline_de_arquivo(bin_seq, mob_id=seq_mob)
    return ({"mob_id": seq_mob, "nome": sequencia.get("composition_name") or ""},
            copia, sequencia)
