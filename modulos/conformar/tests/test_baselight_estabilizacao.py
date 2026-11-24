"""O Stabilize do MC no tracker nativo do Baselight (`baselight/blg_estab.py`, laboratório de 2026-11-23: PRODUCAO-A
C011/C013 iguais ao render do MC — 0,01/0,01 e 0,22/0,04 px).

    .venv/bin/python -m pytest tests/test_baselight_estabilizacao.py

- O plano limpo (o BLG que o `bl-conform` deixou, C011) ganha as faixas Transform + Tracker do molde: 3 faixas, ids novos,
  a duração do plano; o rastreio, o Motion 0, a escala e a posição por quadro conferem na volta.
- ⛔ A 2ª passada MUDA o que tem de mudar (a regex de curva constante não pegava a animada: o Baselight repetia o render).
- A conta da posição: com o tracker travado no quadro 0 e o deslocamento DEPOIS da escala — o termo (Z − 1).
- `do_aaf.estabilizados` só leva o que se traduz; o resto vira marker (antes ia ao Baselight sem estabilizar, calado).
"""
from __future__ import annotations

import math
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from baselight import blg_estab as B  # noqa: E402
from baselight import do_aaf, enviar  # noqa: E402

FPS = 24000 / 1001
LIMPO = (RAIZ / "tests" / "dados" / "baselight" / "plano_limpo_C011.blg.txt").read_text(encoding="latin1")
MOLDE = Path(B.MOLDE).read_text(encoding="latin1")


def _plano(n=393, zoom=1.0117, amp=40.0):
    px = [700 + amp * math.sin(k / 30) + 3 * math.sin(k * 1.7) for k in range(n)]
    py = [460 + 0.5 * amp * math.cos(k / 25) + 2 * math.sin(k * 2.3) for k in range(n)]
    return {"inicio": 3640, "quadros": n, "clip": "C011", "p_x": px, "p_y": py, "zoom": zoom, "filtro": 0.5,
            "pos": [0.47, -0.21], "w": 1920, "h": 1080}


def test_enxerta_no_plano_limpo_e_confere():
    assert not B.tem_tracker(LIMPO) and LIMPO.count("8:GM_Strip") == 1
    p = _plano()
    t = B.montar(LIMPO, MOLDE, p, FPS)
    assert B.tem_tracker(t) and t.count("8:GM_Strip") == 3
    assert B.conferir(t, p, FPS)
    # a duração do plano nas faixas novas; a imagem em cima (linha 2), Tracker 1, Transform 0
    dur = re.search(r'\(22\)="8:GM_Strip 2:gm 1 1 21 1 o 0 \S+ (\S+) 2 f f 0', t).group(1)
    linhas = sorted(int(m.group(1)) for m in re.finditer(rf'8:GM_Strip 2:gm \d+ 1 \d+ 1 o 0 \S+ {dur} (\d+) f f 0', t))
    assert linhas == [0, 1, 2]
    # os ids são todos únicos e os objetos do plano continuam lá (a mídia do C011, não a do molde)
    ids = re.findall(r'^\s*\((\d+)\)=', t, re.M)
    assert len(ids) == len(set(ids)) and "t 3640 t 4033" in t
    # o rastreio: N pontos, o ponto de referência = o do quadro 0
    tok = re.search(r'TRACK_TrackOutputInterp 5:track (.*?)"', t, re.S).group(1).split()
    assert tok[19] == str(p["quadros"]) and tok[9] == B._h(p["p_x"][0])
    # o payload vai e volta
    assert B.ler(B.gravar(t)) == t


def test_segunda_passada_muda_a_curva_animada():
    p = _plano()
    t = B.montar(LIMPO, MOLDE, p, FPS)
    p2 = {**p, "zoom": 1.05, "pos": [0.0, 0.0]}
    t2 = B.montar(t, MOLDE, p2, FPS)
    assert t2.count("8:GM_Strip") == 3                     # não enxerta de novo
    assert B.conferir(t2, p2, FPS) and not B.conferir(t2, p, FPS)


def test_posicao_trava_no_zero_e_o_termo_do_zoom():
    n = 200
    px = [800.0 + k * 0.1 for k in range(n)]              # um ponto que anda devagar, sem tremor
    py = [500.0] * n
    # sem zoom e sem deslocamento: o lento do MC é o próprio ponto (G de uma reta = a reta, longe das bordas)
    xs, ys = B.posicoes(px, py, 1.0, 0.5, [0.0, 0.0], 1920, 1080)
    assert abs(xs[100] - (960 + (B.gauss_nearest(px, 15)[100] - px[0]))) < 1e-9
    assert all(abs(y - 540) < 1e-9 for y in ys)
    # com zoom: o tracker desloca −(p − p₀) em px de TELA; o MC, −Z·(p − G) ⇒ o Transform leva Z·(G − p₀) − (Z−1)(p − p₀)
    z = 1.04
    xs, _ = B.posicoes(px, py, z, 0.5, [0.0, 0.0], 1920, 1080)
    g = B.gauss_nearest(px, 15)
    for k in (0, 50, 199):
        tela_mc = -z * (px[k] - g[k])                       # o que o MC faz com a imagem
        tela_bl = -(px[k] - px[0]) + (xs[k] - 960)          # o tracker + o Transform
        assert abs(tela_mc - tela_bl) < 1e-9
    # o deslocamento fixo do MC: X troca de sinal, Y não (como no Resolve)
    xs, ys = B.posicoes([800.0] * 3, [500.0] * 3, 1.0, 0.5, [1.0, 2.0], 1920, 1080)
    assert abs(xs[0] - (960 + 1.92)) < 1e-9 and abs(ys[0] - (540 - 2.16)) < 1e-9


def test_no_formato_da_scene():
    # o xmeml declarou o raster do 1º arquivo (4128×2176); a scene trabalha em HD: o rastreio vai em px de HD
    p = {**_plano(n=3), "w": 4128, "h": 2176, "p_x": [4128 * 0.4] * 3, "p_y": [2176 * 0.5] * 3}
    q = B.no_formato(p, 1920, 1080)
    assert (q["w"], q["h"]) == (1920, 1080) and abs(q["p_x"][0] - 768) < 1e-9 and abs(q["p_y"][0] - 540) < 1e-9
    assert B.no_formato(q, 1920, 1080) is q
    # e o cabeçalho do rastreio normaliza por 1/LARGURA (HD: os mesmos bytes do molde; UHD: 1/3840 — com 1/1920 o
    # tracker deslocou o dobro, medido)
    cab = lambda t: re.search(r'TRACK_TrackOutputInterp 5:track (.*?)"', t, re.S).group(1).split()[5:7]  # noqa: E731
    assert cab(B.montar(LIMPO, MOLDE, _plano(), FPS)) == ["3f41111111111111"] * 2
    uhd = B.no_formato(_plano(), 3840, 2160)
    assert cab(B.montar(LIMPO, MOLDE, uhd, FPS)) == ["3f31111111111111"] * 2


def test_curva_constante_e_animada():
    t = '  (7)="17:GM_Bezier1dInterp 2:gm 1 0 0 f 3ff0000000000000 21:6 0 0 0 0 -1 0.001 1  ",'
    a = B.curva(t, 7, B.chaves([0.5, 0.6], FPS))
    assert '1 0 0 t 0000000000000000' in a and a.endswith(' ",')
    c = B.curva(a, 7, B.constante(0.7))                      # a animada volta a constante, sem resto
    assert c == '  (7)="17:GM_Bezier1dInterp 2:gm 1 0 0 f 3fe6666666666666 42:6 0 0 0 0 -1 0.001 0.69999999999999995559  ",'  # o que a interface grava


def _seg(tc, efeitos, n=10, **extra):
    return {"track": 1, "timeline_tc_in": tc, "duration_frames": n, "source_start_frames": 0, "clip_name": "A001C011",
            "media_ref": {"local_path": "/x/A001C011.mov"}, "effects": efeitos, **extra}


def _stab(n=10):
    return [{"name": "Stabilize", "params": {"estabilizacao": {"x": [0.4] * n, "y": [0.5] * n, "zoom": 1.02,
                                                                "filtro": 0.5, "pos": [0.1, -0.2]}}}]


def test_do_aaf_leva_so_o_que_se_traduz():
    leitura = {"timeline_fps": FPS, "segments": [
        _seg("00:00:01:00", _stab()),
        _seg("00:00:02:00", _stab(), speed_ratio=0.5, relative_speed=0.5),          # com velocidade: não se traduz
        _seg("00:00:03:00", [{"name": "Stabilize", "params": {}}]),                 # tracker ilegível
        _seg("00:00:04:00", []),
        _seg("00:00:05:00", _stab(), media_ref={"local_path": "/x/outro.mov"}),     # fora do xmeml (sem daily)
    ]}
    achar = lambda s: None if "outro" in s["media_ref"]["local_path"] else s["media_ref"]["local_path"]  # noqa: E731
    est = do_aaf.estabilizados(leitura, achar, 1920, 1080)
    assert [e["inicio"] for e in est] == [24] and est[0]["p_x"][0] == 0.4 * 1920 and est[0]["w"] == 1920
    fora = do_aaf.estabilizacao_fora(leitura)
    assert [f["inicio"] for f in fora] == [48, 72]


def test_markers_da_estabilizacao_juntam_no_mesmo_quadro():
    est = {"feitos": [{"quadro": 10, "clip": "a"}], "falhas": [{"quadro": 20, "clip": "b", "motivo": "x"}],
           "ja_tinha": [{"quadro": 30, "clip": "c"}]}
    m = enviar.marcas_da_estabilizacao(est, [{"inicio": 40}])
    assert [q for q, _ in m] == [10, 20, 30, 40] and "Motion 0" in m[0][1] and "NÃO aplicada: x" in m[1][1]
    j = enviar._juntar([(10, "fora do ponto")], m)
    assert j[0] == (10, "fora do ponto · " + enviar.MARCA_ESTAB) and len(j) == 4


if __name__ == "__main__":
    for nome, f in list(globals().items()):
        if nome.startswith("test_") and callable(f):
            f()
            print("ok", nome)
