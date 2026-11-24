"""A mídia da Carta entra no Premiere em LOTE, e o que não é mídia não vai (2026-11-15, medido no 27.0: um PDF na lista
abre "File Import Failure", que segura a resposta até o OK; a sombra `._` é recusada calada)."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from cicloassist.carta import importar_premiere as IP
from cicloassist.carta.projeto import CartaErro

HOST = Path(__file__).resolve().parents[1] / "cicloassist" / "nle" / "premiere" / "host.jsx"


def _funcao(nome: str) -> str:
    t = HOST.read_text(encoding="utf-8")
    m = re.search(r"function %s\(.*?\n}\n" % nome, t, re.S) or re.search(r"function %s\(.*?}\n" % nome, t)
    return m.group(0)


@pytest.mark.skipif(not shutil.which("node"), reason="sem node")
def test_o_host_barra_sombra_e_documento_e_deixa_a_midia():
    js = _funcao("cicloSombra") + _funcao("cicloNaoMidia") + """
const casos = ["/V/MXF/1/._A01.mxf", "D:\\\\Avid\\\\._A01.mxf", "/V/ROTEIRO/PRODUCAO-A_2.pdf", "/V/a/Notas.DOCX",
               "/V/a/.DS_Store", "/V/a/B001_C003.braw", "/V/a/A01.mxf", "/V/a/som.WAV", "/V/a/a._b.mov"];
console.log(JSON.stringify(casos.map(c => [cicloSombra(c), cicloNaoMidia(c)])));"""
    out = subprocess.run(["node", "-e", js], capture_output=True, text=True, check=True).stdout
    import json
    r = json.loads(out)
    assert [s for s, _ in r] == [True, True, False, False, False, False, False, False, False]
    assert [d for _, d in r] == ["", "", "pdf", "docx", "ds_store", "", "", "", ""]   # ⛔ o BRAW PASSA: é mídia


def test_a_midia_vai_num_pedido_so(monkeypatch):
    chamadas = []

    def chamar(funcao, *args, prazo=0.0):
        chamadas.append((funcao, args))
        if funcao == "cicloProjetosAbertos":
            return {"ativo": "/x/editor.prproj"}
        if funcao == "cicloImportar":
            raise RuntimeError("fim do teste")
        return {}

    monkeypatch.setattr(IP._ep, "arquivos_da_timeline", lambda *a, **k: (["/m/a.mxf", "/m/b.mxf", "/m/c.mxf"], {}))
    monkeypatch.setattr(IP._ep, "_ler_prproj", lambda c: None)
    monkeypatch.setattr(IP._ep, "midia_do_projeto", lambda R: {})
    with pytest.raises(RuntimeError):
        IP.importar_timeline(None, {"nome": "t"}, chamar)
    imp = [a for f, a in chamadas if f == "cicloImportar"]
    assert len(imp) == 1 and imp[0][0].count("\narq\t") == 3


def test_sem_resposta_na_importacao_diz_o_aviso_e_o_gesto(monkeypatch):
    def chamar(funcao, *args, prazo=0.0):
        if funcao == "cicloProjetosAbertos":
            return {"ativo": "/x/editor.prproj"}
        if funcao == "cicloImportar":
            raise RuntimeError(f"O Premiere não respondeu em {prazo:.0f} s. Ele pode estar com um diálogo aberto.")
        return {}

    monkeypatch.setattr(IP._ep, "arquivos_da_timeline", lambda *a, **k: (["/m/a.braw"], {}))
    monkeypatch.setattr(IP._ep, "_ler_prproj", lambda c: None)
    monkeypatch.setattr(IP._ep, "midia_do_projeto", lambda R: {})
    with pytest.raises(CartaErro) as e:
        IP.importar_timeline(None, {"nome": "t"}, chamar)
    assert "File Import Failure" in str(e.value) and "OK" in str(e.value) and "não se repete" in str(e.value)
