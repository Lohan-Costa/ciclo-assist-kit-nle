"""A Carta Aberta e o Baselight (etapa 3 da proposta `docs/plano/2026-11-22-baselight-no-app.md`).

O Baselight só RECEBE (autor, 2026-11-22). Com ele aberto, o "Importar" da Carta pergunta:
- **Importar timeline** — a timeline vai como está, com as mídias que a Carta aponta (a Carta não é conform): o xmeml da
  Carta (`entrega_premiere.xml_da_timeline`), cada arquivo descrito como É (taxa, TC, duração — a Carta declara a da
  timeline), conform numa scene NOVA do job da produção, a conferência de cada plano e os markers "[Ciclo]".
- **Conformar com De Lá Pra Cá** — o mesmo xmeml vai ao painel do Conformar (o pedido em `<dados>/conformar/
  a-conformar.json`, que o painel pega uma vez), onde o colorista aponta as pastas dos originais e o vid ref.

O trabalho do Baselight é o MESMO do Conformar (`modulos/conformar/motor/baselight/`), chamado aqui no processo do Assist.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from . import entrega_premiere as _ep
from .projeto import CartaErro, Projeto


def _motor():
    """O `baselight` do motor do Conformar (o mesmo caminho de `timeline._conformar`)."""
    raiz = Path(__file__).resolve().parents[2] / "modulos" / "conformar" / "motor"
    if str(raiz) not in sys.path:
        sys.path.insert(0, str(raiz))
    from baselight import enviar  # noqa: PLC0415
    return enviar


def jobs() -> dict:
    enviar = _motor()
    ok, motivo = enviar.disponivel()
    if not ok:
        return {"disponivel": False, "motivo": motivo, "jobs": []}
    # o job ABERTO na interface (a scene com lock), para a pergunta da etapa 4
    return {"disponivel": True, "motivo": "", "jobs": enviar.jobs(),
            "aberto": enviar.job_aberto() if enviar.interface_aberta() else None}


def _job(proj: Projeto, job: str | None) -> str:
    """O job da produção: o pedido; senão o nome do projeto da Carta (a produção)."""
    return (job or "").strip() or proj.nome


def importar(proj: Projeto, item_id: str, job: str | None = None, markers: bool = True) -> dict:
    """"Importar timeline": as mídias da Carta, sem casar, numa scene nova do job."""
    from ..servico import config
    enviar = _motor()
    xml, rel = _ep.gravar(proj, item_id)
    decisao = enviar.decisao_como_esta(str(xml))
    r = enviar.entregar_xmeml(str(xml), decisao, _job(proj, job), rel["nome"], [],
                              str(config.pasta() / "carta" / "entregas" / "baselight"), markers=markers)
    return {**r, "fora": {k: v for k, v in rel.items() if k != "nome" and v}}


def pedir_conform(proj: Projeto, item_id: str, job: str | None = None) -> dict:
    """"Conformar com De Lá Pra Cá": grava o xmeml e o PEDIDO que o painel do Conformar pega (a pasta de dados do Ciclo
    Assist é a mesma dos dois serviços)."""
    from ..servico import config
    xml, rel = _ep.gravar(proj, item_id)
    pasta = config.pasta() / "conformar"
    pasta.mkdir(parents=True, exist_ok=True)
    pedido = {"xml": str(xml), "nome": rel["nome"], "job": _job(proj, job), "quando": time.time()}
    tmp = pasta / "a-conformar.json.tmp"
    tmp.write_text(json.dumps(pedido, ensure_ascii=False), encoding="utf-8")
    tmp.replace(pasta / "a-conformar.json")
    return pedido


__all__ = ["jobs", "importar", "pedir_conform", "CartaErro"]
