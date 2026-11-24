"""O REFRESH do painel lateral de bins do Media Composer — o projeto relido do disco, sem save.

Para que existe: bin ou pasta criada, movida ou renomeada POR FORA (Sincronizar, `organizar_bins`, o
Explorer) só aparece no painel depois de um save ou de um refresh (autor, 2026-11-01). O save só
grava com algo MODIFICADO, e renomear não suja nada; o refresh não depende disso.

⭐⭐ ACHADO pelo REA (2026-11-01, MC 2024.6): o `Refresh` é um item do MENU DE CONTEXTO do painel
lateral (`m_ContextPopup`, `Project/BinContainer.cpp`, ao lado de Reveal File, Add Bin to Favorites,
Delete Selected Items, Close Project), servido pelo `ProjectRefreshCoordinator`
(`requestDirectoryRefreshAsync`). Não há RPC na API gRPC. MEDIDO: bin movida para uma pasta nova
por fora → clique direito num vazio do painel → `Refresh` → a fantasma some, a pasta aparece, e o
`GetBins` passa a listar o caminho novo (em < 1,5 s).

⛔ O item `Refresh` é CONFERIDO antes do clique (o localizador confere sempre): no mesmo menu
estão `Close Project` e `Delete`. ⛔ A prova é a API (`GetBins`) batendo com o DISCO, nunca a foto.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable

from .. import janela
from ..piloto import auxilio as _auxilio
from ..piloto import espaco, localizador, maos, tela
from . import organizar as _organizar
from . import socorro as _socorro

EXE = "AvidMediaComposer.exe"
AVISO = "AvidMediaComposer"
#: ⛔ "Logo abaixo do último nome", e não "um vazio qualquer" (MEDIDO 2026-11-01): a conferência olha um
#:   recorte de 480x270 em volta da cruz, e um ponto fundo no vazio mostrava só cinza — "não dá para saber
#:   se é o painel de bins", recusado. Colado à lista, o recorte mostra os nomes das bins acima da cruz.
ALVO_VAZIO = ("um ponto VAZIO do painel lateral de BINS do Media Composer (a coluna da esquerda com a lista de "
              "bins e pastas do projeto), LOGO ABAIXO do último nome da lista — uma linha abaixo dele, na mesma "
              "coluna dos nomes —, onde não há nome, ícone, barra de rolagem nem campo de busca. Os nomes das "
              "bins aparecem logo acima do ponto")
ALVO_REFRESH = ("o item de menu 'Refresh' do menu de contexto aberto (o menu tem Open Bin, New Bin, New Folder, "
                "Close Project, Hide Sidebar, Refresh, What's This?). O ponto é sobre a palavra 'Refresh', "
                "NUNCA sobre outro item")
PRAZO_S = 6.0

_guardado: dict[tuple, tuple[int, int]] = {}   # (hwnd, retângulo da janela) → ponto vazio do painel


class AtualizarFalhou(RuntimeError):
    pass


class AvisoNaTela(AtualizarFalhou, _auxilio.TelaInesperada):
    """Um aviso do MC no caminho do Refresh: é aqui que o agente do piloto entra."""


def _bins_do_disco(projeto: str | Path) -> set[str]:
    return {c for c, esp in _organizar.arvore(projeto).items() if esp == "bin"}


def _bins_da_api() -> set[str]:
    from .mcapi import MediaComposer  # noqa: PLC0415

    with MediaComposer() as m:
        return {m.caminho_relativo_da_bin(b).replace("\\", "/").removesuffix(".avb").casefold()
                for b in m.bins()}


def em_dia(projeto: str | Path) -> bool:
    """O painel (pela API) lista exatamente as bins que há no disco?"""
    return _bins_da_api() == _bins_do_disco(projeto)


def _ponto_vazio(hwnd: int, foto, relatar) -> tuple[int, int, float]:
    from .salvar import _retangulo  # noqa: PLC0415

    ret = _retangulo(hwnd)
    chave = (hwnd, ret)
    if chave in _guardado:
        x, y = _guardado[chave]
        ok, _r, _s, custo = localizador.conferir(foto, x, y, ALVO_VAZIO, recorte=localizador.RECORTE_AMPLO)
        if ok:
            return x, y, custo
        _guardado.pop(chave, None)
    relatar("procurando um vazio no painel de bins", None, "")
    a = localizador.localizar(foto, ALVO_VAZIO, regiao=ret, recorte=localizador.RECORTE_AMPLO)
    _guardado.clear()
    _guardado[chave] = (a.x, a.y)
    return a.x, a.y, a.custo_usd


def atualizar(projeto: str | Path,
              relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """Refresh do painel lateral, com a janela do app FORA da frente. Devolve se ficou em dia."""
    with espaco.tela_livre():
        return _socorro.com_agente("atualizar o painel de bins do Media Composer (Refresh)", lambda: _atualizar(projeto, relatar), AtualizarFalhou, relatar)


def _atualizar(projeto, relatar) -> dict[str, object]:
    relatar = relatar or (lambda *_: None)
    comeco = time.monotonic()
    try:
        if em_dia(projeto):
            return {"atualizado": True, "ja_estava": True, "segundos": 0.0, "custo_usd": 0.0}
    except Exception:  # noqa: BLE001 — sem a API, o gesto ainda vale; a prova cai no fim
        pass
    hwnd = janela.janela_principal(EXE, "Avid Media Composer")
    if not hwnd:
        raise AtualizarFalhou("o Media Composer não está aberto")
    if janela.existe_aviso(AVISO) or _socorro.inesperada():
        raise AvisoNaTela("há um aviso do Media Composer na tela — responda a ele antes")
    anterior = maos.da_frente()
    custo = 0.0
    try:
        # ⭐ Bins SOLTO (layout livre): a janela "Bins", em qualquer monitor; encaixado, a principal.
        hwnd = janela.do_painel(EXE, "Bins") or hwnd
        if not janela.focar(hwnd):
            raise AtualizarFalhou("o Windows não deixou pôr o Media Composer na frente")
        time.sleep(0.5)
        if janela.existe_aviso(AVISO):
            raise AvisoNaTela("apareceu um aviso do Media Composer ao trazê-lo para a frente — responda a ele antes")
        x, y, c = _ponto_vazio(hwnd, tela.fotografar(), relatar)
        custo += c
        relatar("abrindo o menu do painel de bins", None, "")
        maos.clicar_direito(hwnd, x, y)
        time.sleep(0.7)
        try:
            # o menu de contexto nasce onde se clicou: só aquele monitor
            a = localizador.localizar(tela.fotografar(), ALVO_REFRESH, regiao=tela.monitor_do_ponto(x, y))
        except localizador.NaoAchei:
            maos.tecla(hwnd, maos.VK_ESC)          # ⛔ nunca deixar o menu aberto na tela do editor
            raise
        custo += a.custo_usd
        relatar("Refresh do painel de bins", None, "")
        maos.clicar(hwnd, a.x, a.y)
        fim = time.monotonic() + PRAZO_S
        ok = False
        while time.monotonic() < fim:
            time.sleep(0.5)
            try:
                if em_dia(projeto):
                    ok = True
                    break
            except Exception:  # noqa: BLE001 — o MC ocupado relendo: tenta de novo
                pass
    except (localizador.NaoAchei, tela.SemTela, maos.ForaDeFoco, maos.Parado) as e:
        raise AtualizarFalhou(str(e)) from e
    finally:
        if anterior and anterior != hwnd:
            janela.focar(anterior)
    return {"atualizado": ok, "segundos": round(time.monotonic() - comeco, 1), "custo_usd": round(custo, 4)}
