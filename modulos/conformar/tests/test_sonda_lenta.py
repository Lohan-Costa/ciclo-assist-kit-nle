"""Disco LENTO não é arquivo ILEGÍVEL (2026-10-04).

Rodar:

    .venv/bin/python tests/test_sonda_lenta.py        (Windows: .venv-win/Scripts/python)

⛔ Medido no PRODB com o disco FRIO e 8 sondagens simultâneas (Windows): 5 ARRIRAW passaram do
limite de 60 s do ffprobe e o casamento os recusou como ilegíveis —
originais perfeitos ficariam no proxy, com marcador de refazer. Em série, com o mesmo disco frio, não
aconteceu. Agora o estouro de tempo não vai para o cache, quem estourou é refeito UM POR VEZ no fim,
e se nem assim responder o motivo diz "o disco não respondeu" (estado `lento`).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import drp.writer as W  # noqa: E402
import prproj.originais as O  # noqa: E402
from media import sonda as S  # noqa: E402 — a leitura única: o ffprobe mora aqui

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


class _Saida:
    def __init__(self, texto):
        self.stdout = texto


def ffprobe_falso(lentos: dict[str, int]):
    """Um `subprocess.run` que estoura o tempo nas `lentos[nome]` primeiras chamadas de cada arquivo
    e depois responde como um vídeo de 10 s a 24 q/s com TC."""
    def run(cmd, *a, **k):
        alvo = cmd[-1]
        nome = os.path.basename(alvo)
        if "orig" in alvo and lentos.get(nome, 0) > 0:      # o ORIGINAL é que demora (o medido)
            lentos[nome] -= 1
            raise subprocess.TimeoutExpired(cmd, k.get("timeout"))
        raster = "1920" if "proxy" in alvo else "2880"
        return _Saida('{"streams":[{"codec_type":"video","codec_name":"x","width":%s,"height":1080,"r_frame_rate":"24/1",'
                      '"duration":"10.0","nb_frames":"240","tags":{"timecode":"01:00:00:00"}}],'
                      '"format":{"duration":"10.0","tags":{"timecode":"01:00:00:00"}}}' % raster)
    return run


def main() -> int:
    with tempfile.TemporaryDirectory() as d:
        proxies, originais = Path(d, "proxy"), Path(d, "orig")
        proxies.mkdir()
        originais.mkdir()
        for n in ("A001", "A002", "A003"):
            (proxies / f"{n}.mov").write_bytes(b"p" * 64)
            (originais / f"{n}.mov").write_bytes(b"o" * 64)
        segs = [{"media_ref": {"local_path": str(proxies / f"{n}.mov")}} for n in ("A001", "A002", "A003")]
        antes = S.subprocess.run

        print("── casamento: lento uma vez (o lote disputado), responde sozinho ──")
        O._SONDA.clear()
        S._CACHE.clear()
        S.subprocess.run = ffprobe_falso({"A002.mov": 1})
        try:
            r = O.casar(segs, [str(originais)])
        finally:
            S.subprocess.run = antes
        ok("os três no original (antes: o lento era recusado como ilegível)",
           sorted(c["estado"] for c in r.values()), ["original"] * 3)
        ok("nada de \"lento\" guardado no cache", any(v.get("lento") for v in O._SONDA.values()), False)

        print("── casamento: não responde nem sozinho ──")
        O._SONDA.clear()
        S._CACHE.clear()
        S.subprocess.run = ffprobe_falso({"A003.mov": 99})
        try:
            r = O.casar(segs, [str(originais)])
        finally:
            S.subprocess.run = antes
        c = r[str(proxies / "A003.mov")]
        ok("estado `lento` — nem \"incompleto\", nem \"sem original\"", c["estado"], "lento")
        ok("o motivo diz que o disco não respondeu", "não respondeu" in c["recusados"][0][1], True)
        ok("os outros seguem no original", r[str(proxies / "A001.mov")]["estado"], "original")
        O._SONDA.clear()
        S._CACHE.clear()

        print("── uma leitura por arquivo ──")
        alvo = str(originais / "A003.mov")
        S._CACHE.clear()
        O._SONDA.clear()
        for cache in (W._META_CACHE, W._FORMATO_CACHE, W._META_CACHE_A):
            cache.pop(alvo, None)
        S.subprocess.run = ffprobe_falso({})
        try:
            antes_n = S.leituras
            O.sondar(alvo)
            W._media_meta(alvo)
            W._formato_meta(alvo)
            W._audio_meta(alvo)
            ok("casamento + TC + formato + som do mesmo arquivo = UMA leitura do ffprobe (antes: quatro)",
               S.leituras - antes_n, 1)
        finally:
            S.subprocess.run = antes
            S._CACHE.clear()
            O._SONDA.clear()
            for cache in (W._META_CACHE, W._FORMATO_CACHE, W._META_CACHE_A):
                cache.pop(alvo, None)

        print("── writer: a sondagem do pool ──")
        alvo = str(originais / "A001.mov")
        W._META_CACHE.pop(alvo, None)
        W._SONDA_LENTA.clear()
        w_antes = S.subprocess.run
        S.subprocess.run = ffprobe_falso({"A001.mov": 1})
        try:
            ok("estourou: sem dado agora", W._media_meta(alvo), (None, None, None))
            ok("…e sem cache (a próxima sonda de novo)", alvo in W._META_CACHE, False)
            ok("…e registrado como lento", alvo in W._SONDA_LENTA, True)
            W._SONDA_LENTA.clear()
            S._CACHE.clear()
            W._META_CACHE.pop(alvo, None)
            W._FORMATO_CACHE.pop(alvo, None)
            W._META_CACHE_A.pop(alvo, None)
            lentos = {"A001.mov": 1}
            S.subprocess.run = ffprobe_falso(lentos)
            sem = W._sondar_em_paralelo([alvo, str(originais / "A002.mov")])
            ok("o lote refaz o lento em série: ninguém fica sem resposta", sem, [])
            ok("…e o TC dele está no cache", W._META_CACHE.get(alvo), (240, 24.0, "01:00:00:00"))
            W._META_CACHE.pop(alvo, None)
            W._SONDA_LENTA.clear()
            S._CACHE.clear()
            S.subprocess.run = ffprobe_falso({"A001.mov": 99})
            ok("não responde nem sozinho: volta para virar aviso", W._sondar_em_paralelo([alvo]), [alvo])
        finally:
            S.subprocess.run = w_antes
            for cache in (W._META_CACHE, W._FORMATO_CACHE, W._META_CACHE_A, W._ARRIRAW_CACHE):
                for n in ("A001", "A002"):
                    cache.pop(str(originais / f"{n}.mov"), None)
            W._SONDA_LENTA.clear()

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
