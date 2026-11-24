"""Quem escreveu o arquivo de intercâmbio (`motor/origem.py`), e a marca do De Lá Pra Cá no AAF.

Rodar:

    .venv-win/Scripts/python tests/test_origem.py

## Por que este teste existe

O Receber Avid → Avid só vale para o que saiu do Avid, e a origem de um AAF/XML/OTIO solto numa pasta não está no
nome. Medido em 2026-10-12 (banco: `transversal/assinatura-de-origem.md`), com um export de cada NLE no caso
`03 CASOS/ATUALIZAR/O01 ASSINATURA DE ORIGEM` (MC 25.6, Premiere 23.2, Resolve 19.0, todos no Windows).

⛔ O achado que motivou a marca: o pyaaf2 em `rw` não acrescenta Identification, e o AAF que o app relinkava
continuava dizendo "Avid Media Composer" — igual ao que sai do Avid. Aqui se confere que a marca entra DEPOIS da do
Avid, sem tirá-la, e que a origem continua "avid".

A parte de texto roda sempre (amostras mínimas escritas aqui); sem a pasta do caso, o resto diz que pulou.
"""

from __future__ import annotations

import json
import logging
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico")]
logging.disable(logging.INFO)

from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
CASO = Path(raiz_das_amostras()) / "03 CASOS" / "ATUALIZAR" / "O01 ASSINATURA DE ORIGEM"


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    from origem import origem, marcar_aaf, PRODUTO

    print("── texto (amostras mínimas) ──")
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_origem_"))
    try:
        (tmp / "pr.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">\n'
                                    '\t<sequence id="sequence-1" TL.SQHideShyTracks="0"><name>S</name></sequence>\n'
                                    '</xmeml>\n', encoding="utf-8")
        (tmp / "rv.xml").write_text('<?xml version="1.0" encoding="UTF-8"?>\r\n<!DOCTYPE xmeml>\r\n<xmeml version="5">\r\n'
                                    '    <sequence>\r\n        <name>S (Resolve)</name>\r\n    </sequence>\r\n</xmeml>\r\n',
                                    encoding="utf-8")
        (tmp / "rv.otio").write_text(json.dumps({"OTIO_SCHEMA": "Timeline.1", "metadata": {
            "Resolve_OTIO": {"Resolve OTIO Meta Version": "1.0"}}}), encoding="utf-8")
        (tmp / "dl.otio").write_text(json.dumps({"OTIO_SCHEMA": "Timeline.1", "metadata": {
            "DeLaPraCa": {"versao": "0.1.99", "origem": "avid"}}}), encoding="utf-8")
        (tmp / "x.edl").write_text("TITLE: S\nFCM: NON-DROP FRAME\n", encoding="utf-8")
        (tmp / "pacote.fcpxml").mkdir()
        (tmp / "pacote.fcpxml" / "Info.fcpxml").write_text(
            '<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE fcpxml>\n<fcpxml version="1.10">\n'
            '<project name="S (Resolve)"/></fcpxml>\n', encoding="utf-8")
        ok("xmeml v4 com TL.SQ → premiere", origem(tmp / "pr.xml")["nle"], "premiere")
        ok("xmeml v5 limpo → resolve", origem(tmp / "rv.xml")["nle"], "resolve")
        ok("OTIO com Resolve_OTIO → resolve", origem(tmp / "rv.otio")["nle"], "resolve")
        d = origem(tmp / "dl.otio")
        ok("OTIO do app → a origem que ele declarou, marcado", (d["nle"], d["tratado_pelo_dlpc"]), ("avid", True))
        ok("EDL não tem origem → desconhecida", origem(tmp / "x.edl")["nle"], "desconhecida")
        ok("FCPXML 1.10 é PASTA: lê o Info.fcpxml dentro", origem(tmp / "pacote.fcpxml")["formato"], "fcpxml")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    if not CASO.is_dir():
        print(f"  PULADO — {CASO} não está neste disco")
        print(f"\n{casos - len(falhas)}/{casos} casos")
        return 1 if falhas else 0

    print("\n── os exports reais (um de cada NLE) ──")
    esperados = {
        "avid-25.6-win/AVID256_SEQ_LAB_CORTES_01.aaf": ("aaf", "avid", "25.6"),
        "premiere-2023-win/PREMIERE23_AAF.aaf": ("aaf", "premiere", "23.2.0"),
        "premiere-2023-win/PREMIERE23_FCP7.xml": ("xmeml", "premiere", None),
        "resolve-19.0-win/RESOLVE19_AAF_novo.aaf": ("aaf", "resolve", "19.0.0"),
        "resolve-19.0-win/RESOLVE19_FCP7.xml": ("xmeml", "resolve", None),
        "resolve-19.0-win/RESOLVE19_FCPXML_1_8.fcpxml": ("fcpxml", "resolve", None),
        "resolve-19.0-win/RESOLVE19_FCPXML_1_10.fcpxml": ("fcpxml", "resolve", None),
        "resolve-19.0-win/RESOLVE19_OTIO.otio": ("otio", "resolve", None),
        "resolve-19.0-win/RESOLVE19_EDL.edl": ("edl", "desconhecida", None),
    }
    for rel, (fmt, nle, versao) in esperados.items():
        d = origem(CASO / rel)
        ok(f"{rel.split('/')[-1]}", (d["formato"], d["nle"], d["versao"]), (fmt, nle, versao))

    print("\n── a marca do De Lá Pra Cá num AAF do Avid ──")
    import aaf2
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_marca_"))
    try:
        copia = tmp / "marcado.aaf"
        shutil.copy2(CASO / "avid-25.6-win" / "AVID256_SEQ_LAB_CORTES_01.aaf", copia)
        ok("antes: 1 Identification, não tratado", (len(origem(copia)["cadeia"]),
                                                     origem(copia)["tratado_pelo_dlpc"]), (1, False))
        with aaf2.open(str(copia), "rw") as f:
            ok("marcar_aaf devolve True", marcar_aaf(f), True)
        d = origem(copia)
        ok("depois: 2 Identifications", len(d["cadeia"]), 2)
        ok("…a do Avid continua a PRIMEIRA", d["cadeia"][0].get("CompanyName"), "Avid Technology, Inc.")
        ok("…a do app é a última", d["cadeia"][-1].get("ProductName"), PRODUTO)
        ok("⭐ a origem continua avid (o app só tratou), marcado", (d["nle"], d["versao"], d["tratado_pelo_dlpc"]),
           ("avid", "25.6", True))
        with aaf2.open(str(copia), "r") as f:
            ok("…e o AAF continua legível, com as mesmas mobs", len(list(f.content.mobs)) > 0, True)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
