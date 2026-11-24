"""O Resolve pelo lado de fora (`resolve_externo.py`): as trancas herdadas da casca, sem o Resolve aberto.

O que se confere aqui é o que NÃO depende do Resolve: o .drt só da pasta `recebidos` com nome `<uuid>.drt` (ataque V9)
e a lista de mídias ao lado dele, com cada caminho conferido de novo. As chamadas ao Resolve foram medidas na bancada
de 2026-10-18 (Studio 19.1.4.11; banco, resolve-scripting/api-scripting.md).
"""
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico")]

import cache  # noqa: E402
import resolve_externo as RX  # noqa: E402

casos = []


def caso(nome, obtido, esperado):
    ok = obtido == esperado
    casos.append(ok)
    print(f"  {'ok  ' if ok else 'FALHA'} {nome:<62} -> {obtido!r}")


with tempfile.TemporaryDirectory() as tmp:
    raiz_antiga = cache.raiz
    cache.raiz = lambda: Path(tmp)
    try:
        receb = Path(tmp) / cache.RECEBIDOS
        receb.mkdir()
        bom = receb / f"{uuid.uuid4()}.drt"
        bom.write_bytes(b"x")
        caso("o .drt do serviço (recebidos/<uuid>.drt) passa", RX.drt_confiavel(str(bom)), True)
        caso("nome fora do padrão <uuid>.drt é recusado", RX.drt_confiavel(str(receb / "timeline.drt")), False)
        fora = Path(tmp) / f"{uuid.uuid4()}.drt"
        caso("o mesmo nome FORA da pasta recebidos é recusado", RX.drt_confiavel(str(fora)), False)
        caso("compartilhamento de rede é recusado", RX.drt_confiavel(r"\\servidor\x\%s.drt" % uuid.uuid4()), False)
        caso("valor que não é texto é recusado", RX.drt_confiavel(None), False)

        existe = Path(tmp) / "a.mov"
        existe.write_bytes(b"x")
        lista = bom.with_suffix(".midias.json")
        lista.write_text(json.dumps({"midias": [str(existe), str(Path(tmp) / "sumiu.mov"), "relativo.mov", 7],
                                     "depois": [str(existe)]}), "utf-8")
        caso("midias: só os caminhos absolutos que existem", RX.midias_do_drt(str(bom)), [str(existe)])
        caso("depois: a outra chave da mesma lista", RX.midias_do_drt(str(bom), "depois"), [str(existe)])
        caso("sem lista ao lado: nenhuma mídia", RX.midias_do_drt(str(receb / "outro.drt")), [])
    finally:
        cache.raiz = raiz_antiga

# O Resolve MUDO não congela o serviço (2026-10-23): sem o servidor de scripts, a resposta sai na hora e não se tenta
# o `scriptapp` (que segura o GIL ~4 s); depois de uma falha, ninguém tenta de novo até o fim da espera.
import socket  # noqa: E402
import time  # noqa: E402

livre = socket.socket()
livre.bind(("127.0.0.1", 0))
porta_vazia = livre.getsockname()[1]
livre.close()
originais = (RX.PORTA_SCRIPTS, RX._WIN, RX._scriptapp)
tentativas = []
RX._scriptapp = lambda: tentativas.append(1)          # devolve None = o Resolve não respondeu
try:
    RX.PORTA_SCRIPTS, RX._WIN, RX._mudo["ate"] = porta_vazia, True, 0.0
    t = time.perf_counter()
    try:
        RX.conectar()
        motivo = None
    except RuntimeError as e:
        motivo = str(e)
    caso("sem o servidor de scripts: recusa com o motivo", "servidor de scripts" in (motivo or ""), True)
    caso("sem o servidor de scripts: o scriptapp nem é tentado", len(tentativas), 0)
    caso("sem o servidor de scripts: resposta em menos de 1 s", time.perf_counter() - t < 1.0, True)

    # o servidor de scripts no ar (uma porta que escuta) e o scriptapp falha uma vez; a sonda vale nos dois sistemas
    # desde 2026-10-24 (Mac medido: o mesmo `fuscript -s` na 1144)
    no_ar = socket.socket()
    no_ar.bind(("127.0.0.1", 0))
    no_ar.listen(8)
    RX.PORTA_SCRIPTS, RX._mudo["ate"] = no_ar.getsockname()[1], 0.0
    for _ in range(3):
        try:
            RX.conectar()
        except RuntimeError:
            pass
    caso("depois de uma falha, as seguintes respondem sem tentar de novo", len(tentativas), 1)
    RX._mudo["ate"] = 0.0
    try:
        RX.conectar()
    except RuntimeError:
        pass
    caso("passada a espera, tenta de novo", len(tentativas), 2)
    no_ar.close()
finally:
    RX.PORTA_SCRIPTS, RX._WIN, RX._scriptapp = originais
    RX._mudo["ate"] = 0.0

print(f"\n{sum(casos)}/{len(casos)} casos")
sys.exit(0 if all(casos) else 1)
