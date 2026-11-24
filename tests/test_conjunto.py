"""O conjunto agora (`servico/conjunto.py`): o que o supervisor do app grava, ou a sonda das portas."""

from __future__ import annotations

import json
import time

from cicloassist.servico import config, conjunto


def test_le_o_supervisor_quando_fresco(monkeypatch):
    (config.pasta()).mkdir(parents=True, exist_ok=True)
    (config.pasta() / "motores.json").write_text(json.dumps({"atualizado": time.time(), "motores": [
        {"modulo": "conformar", "nome": "o De Lá Pra Cá", "porta": 7823, "situacao": "falhou",
         "motivo": "não abriu a porta em 90 s", "tentativas": 3}]}), encoding="utf-8")
    monkeypatch.setattr(conjunto, "programas", lambda: {"DaVinci Resolve": True, "Media Composer": False})
    f = conjunto.frase()
    assert "o De Lá Pra Cá: NÃO subiu (não abriu a porta em 90 s)" in f and "DaVinci Resolve" in f


def test_supervisor_velho_cai_para_a_sonda(monkeypatch):
    config.pasta().mkdir(parents=True, exist_ok=True)
    (config.pasta() / "motores.json").write_text(json.dumps({"atualizado": 1, "motores": []}), encoding="utf-8")
    monkeypatch.setattr(conjunto, "_escuta", lambda porta, host="127.0.0.1": porta == 7823)
    ms = {m["modulo"]: m["situacao"] for m in conjunto.motores()}
    assert ms == {"preparar": "fora", "assistir": "fora", "conformar": "no_ar"}


def test_o_conselho_leva_o_estado_do_conjunto(monkeypatch):
    from cicloassist.motor import conselho

    monkeypatch.setattr(conjunto, "frase", lambda: "Os serviços do conjunto AGORA: o De Lá Pra Cá: no ar.")

    class P:
        id, op, args, tentativas, motivo = "conform", "conformar_no_resolve", {}, 1, "o De Lá Pra Cá não respondeu"

    class F:
        id, nome, estado, atual, passos, origem = "f", "X", "esperando", 0, [P()], "modelo"

    from cicloassist.servico import fluxo
    monkeypatch.setattr(fluxo, "descrever", lambda f: "Fluxo X")
    assert "o De Lá Pra Cá: no ar" in conselho._pedido(F(), "")
