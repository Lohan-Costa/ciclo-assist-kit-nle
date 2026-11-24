"""O job do Baselight vem do nome do PROJETO quando a Carta não traz a produção (autor, 2026-11-23) — antes o job do
envio anterior ficava no campo e o PRODUCAO-C ia para o job do PRODUCAO-A.

    .venv/bin/python tests/test_baselight_job_do_projeto.py
"""
from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"), str(RAIZ)]

from sessao_receber import nome_do_projeto  # noqa: E402


def test_prproj_aaf_e_xmeml_pelo_nome_do_arquivo():
    assert nome_do_projeto(Path("/x/PRODC_FINAL_isolado_1.prproj")) == "PRODC_FINAL_isolado_1"
    assert nome_do_projeto(Path("/x/PRODA_RELINKER_ALTA.aaf")) == "PRODA_RELINKER_ALTA"
    assert nome_do_projeto(Path("/x/BL09 V2.xml")) == "BL09 V2"


def test_bin_pela_pasta_do_projeto_do_mc():
    d = Path(tempfile.mkdtemp())
    (d / "LAB X" / "CENAS").mkdir(parents=True)
    (d / "LAB X" / "LAB X.avp").write_text("")
    assert nome_do_projeto(d / "LAB X" / "bin.avb") == "LAB X"
    assert nome_do_projeto(d / "LAB X" / "CENAS" / "bin.avb") == "LAB X"     # bin em subpasta
    (d / "solta").mkdir()
    assert nome_do_projeto(d / "solta" / "bin.avb") == "solta"               # sem .avp por perto: a pasta da bin


def test_o_painel_poe_o_projeto_no_job_e_a_carta_vence():
    js = (RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.js").read_text(encoding="utf-8")
    assert 'el("rcBlJob").value = r.producao || r.projeto' in js
    i, j = js.index("await abrirArquivo(r.xml);"), js.index('if (r.job && el("rcBlJob")) el("rcBlJob").value = r.job;')
    assert i < j                                       # o job da Carta DEPOIS de carregar (senão o nome do xmeml vence)


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and callable(f):
            f()
            print("ok", nome)
