"""A receita `preparar-diaria-no-premiere` (P5): proxy no Resolve → Premiere (original ou anexado) → sync."""

from __future__ import annotations

import pytest

from cicloassist.servico import fluxo as F
from cicloassist.servico import receitas as R

PARAMS = {"pasta": "/m/D01", "diaria": "D01", "destino": "/m/PX", "modo": "proxy_anexado", "projeto": "/p/x.prproj"}


def test_a_receita_encadeia_proxy_importar_e_sync():
    p = R.buscar("preparar-diaria-no-premiere").plano(dict(PARAMS))
    assert [s["op"] for s in p["passos"]] == ["abrir_programa", "converter_para_proxy", "fechar_programa",
                                               "abrir_programa", "importar_no_premiere", "sincronizar"]
    assert F.validar(p) == []
    imp = next(s for s in p["passos"] if s["id"] == "importar")
    assert imp["args"]["proxies"] == "{conv.pasta}"        # a pasta que o converter devolveu


def test_o_modo_nao_tem_padrao_e_so_aceita_os_dois():
    """⛔ Decisão do autor (2026-11-07): o editor escolhe o modo a cada diária."""
    r = R.buscar("preparar-diaria-no-premiere")
    assert "padrao" not in r.parametros["modo"] and "padrao" not in r.parametros["destino"]
    with pytest.raises(R.ReceitaInvalida):
        r.plano({**PARAMS, "modo": "os dois"})
