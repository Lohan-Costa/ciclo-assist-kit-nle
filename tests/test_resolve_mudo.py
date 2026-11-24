"""⛔⛔ O Resolve com o servidor de scripts MUDO (2026-11-04).

Pelo chat: o Resolve aberto pela ferramenta levou 44 s até `Started script server`, o servidor desistiu
(`Failed to connect to script server`) e terminou 0,3 s depois de abrir a porta. O `abrir()` viu a porta
naquele instante e deu por pronto; o `scriptapp` voltou None com uma frase sugerindo "o Free".
Agora: pronto é a API responder; mudo é o LOG do Resolve dizer; mudo sem projeto é fechado e reaberto.
"""

from __future__ import annotations

import pytest

from cicloassist import resolve


class Resolve:
    """Um Resolve de mentira: `sessoes` diz, por abertura, se o servidor de scripts liga."""

    def __init__(self, sessoes, vivo=False, projeto=False, mudo=False):
        self.sessoes = list(sessoes)
        self.vivo, self.projeto, self.mudo = vivo, projeto, mudo
        self.ok = False
        self.lancou = 0
        self.fechou = 0

    def instalar(self, mp):
        mp.setattr(resolve, "instalado", lambda: True)
        mp.setattr(resolve, "processo_vivo", lambda: self.vivo)
        mp.setattr(resolve, "servidor_no_ar", lambda: self.ok)
        mp.setattr(resolve, "_api_responde", lambda prazo=0: {"versao": "19"} if self.ok else None)
        mp.setattr(resolve, "servidor_desistiu", lambda desde=0.0: self.vivo and self.mudo)
        mp.setattr(resolve, "sem_projeto_aberto", lambda: not self.projeto)
        mp.setattr(resolve, "_lancar", self._lancar)
        mp.setattr(resolve, "_fechar_mudo", self._fechar)
        mp.setattr(resolve.time, "sleep", lambda s: None)

    def _lancar(self):
        self.lancou += 1
        self.vivo = True
        liga = self.sessoes.pop(0)
        self.ok, self.mudo = liga, not liga

    def _fechar(self, prazo=0):
        self.fechou += 1
        self.vivo = self.ok = self.mudo = False


def test_abertura_muda_e_reaberta_sozinha(monkeypatch):
    r = Resolve([False, True])
    r.instalar(monkeypatch)
    a = resolve.abrir()
    assert (r.lancou, r.fechou, a["reaberturas"], a["ja_estava"]) == (2, 1, 1, False)


def test_desiste_depois_das_reaberturas(monkeypatch):
    r = Resolve([False] * (resolve.REABERTURAS + 1))
    r.instalar(monkeypatch)
    with pytest.raises(resolve.ResolveIndisponivel, match="não é o Free"):
        resolve.abrir()
    assert r.lancou == resolve.REABERTURAS + 1
    assert r.fechou == resolve.REABERTURAS


def test_ja_aberto_mudo_sem_projeto_e_reaberto(monkeypatch):
    # o caso da tela do autor: Resolve vivo na janela de projetos, servidor desistido, porta fechada
    r = Resolve([True], vivo=True, mudo=True)
    r.instalar(monkeypatch)
    a = resolve.abrir()
    assert (r.fechou, r.lancou, a["reaberturas"]) == (1, 1, 1)


def test_mudo_com_projeto_nunca_e_fechado(monkeypatch):
    r = Resolve([], vivo=True, mudo=True, projeto=True)
    r.instalar(monkeypatch)
    with pytest.raises(resolve.ResolveIndisponivel, match="não o fechei"):
        resolve.abrir()
    assert (r.fechou, r.lancou) == (0, 0)


def test_porta_aberta_sem_api_nao_e_pronto(monkeypatch):
    # ⛔ a porta pisca: sem a API responder, abrir() não pode voltar como pronto
    r = Resolve([True])
    r.instalar(monkeypatch)
    monkeypatch.setattr(resolve, "servidor_no_ar", lambda: True)
    chamadas = []

    def api(prazo=0):
        chamadas.append(1)
        return {"versao": "19"} if len(chamadas) > 1 else None
    monkeypatch.setattr(resolve, "_api_responde", api)
    assert resolve.abrir()["ja_estava"] is False
    assert len(chamadas) == 2


def test_o_log_do_resolve(tmp_path, monkeypatch):
    log = tmp_path / "ResolveDebug.txt"
    monkeypatch.setattr(resolve, "_LOG_DO_RESOLVE", str(log))
    assert resolve.servidor_desistiu() is False                       # sem log
    log.write_text("Started script server: 1\nFailed to connect to script server, retrying\n",
                   encoding="utf-8")
    assert resolve.servidor_desistiu() is False                       # ainda tentando
    log.write_text(log.read_text(encoding="utf-8") + "Failed to connect to script server\n",
                   encoding="utf-8")
    assert resolve.servidor_desistiu() is True
    assert resolve.servidor_desistiu(desde=log.stat().st_mtime + 60) is False   # log de outra sessão
