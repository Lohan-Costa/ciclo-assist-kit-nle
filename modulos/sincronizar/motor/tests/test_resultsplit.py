"""
PARTIR UMA DIÁRIA JÁ SINCRONIZADA.

⭐ POR QUE DEPOIS DO SYNC, E NÃO ANTES — foi o usuário que apontou, testando no
Premiere: dividindo antes, "o áudio que deveria acompanhar a câmera RED ficou todo
numa diária e na segunda vieram só alguns áudios de outro gravador".

A razão é estrutural. Antes do sync, o programa **não sabe qual som casa com qual
câmera** — quem descobre isso é a correlação de forma de onda. Cortar ali é cortar
às cegas, e um corte no lugar errado destrói um par que a medição teria achado.

Depois, a TOMADA já existe como unidade, e o corte só pode acontecer ENTRE
tomadas. É isto que estes testes guardam: **nenhuma unidade se parte.**
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync.model import CameraAngle, CameraGroup, Daily, SoundClip, Take
from sync.resultsplit import DAILY_GAP_S, needs_split, span_hours, split_daily_result

FPS = 24.0
H = 3600.0


def _cam(nome: str, inicio_h: float, dur_s: float = 60.0) -> CameraAngle:
    return CameraAngle(
        path=Path(f"/fake/{nome}"), fps=FPS,
        duration_frames=round(dur_s * FPS),
        timeline_start_frames=round(inicio_h * H * FPS),
    )


def _snd(nome: str, inicio_h: float, dur_s: float = 300.0) -> SoundClip:
    return SoundClip(
        path=Path(f"/fake/{nome}"), sample_rate=48000, duration_ms=dur_s * 1000,
        timeline_start_frames=round(inicio_h * H * FPS),
    )


def _p(nome: str) -> str:
    """A mesma string que `_cam`/`_snd` guardam em `path` — `str(Path(...))` usa o
    separador NATIVO do SO (contrabarra no Windows), então os testes comparam
    contra isto em vez de cravar `/fake/...` como se fosse universal."""
    return str(Path(f"/fake/{nome}"))


def _daily(takes=(), orfas_cam=(), orfas_snd=()) -> Daily:
    cams = [c for t in takes for c in t.cameras] + list(orfas_cam)
    return Daily(
        camera_groups=[CameraGroup(cameras=cams, name="CAM A", id="g")],
        takes=list(takes),
        orphan_cameras=list(orfas_cam),
        orphan_sounds=list(orfas_snd),
        fps=FPS,
    )


# ── O corte ──────────────────────────────────────────────────────────────────


def test_duas_captacoes_separadas_por_um_vao_viram_duas_partes():
    t1 = Take(sound=_snd("s1.wav", 0.0), cameras=[_cam("c1.mov", 0.01)])
    t2 = Take(sound=_snd("s2.wav", 21.0), cameras=[_cam("c2.mov", 21.01)])
    partes = split_daily_result(_daily([t1, t2]))
    assert len(partes) == 2
    assert partes[0]["file_count"] == 2 and partes[1]["file_count"] == 2


def test_um_vao_menor_que_o_limiar_nao_corta():
    """Um almoço, uma troca de locação — nada disso é uma diária nova."""
    t1 = Take(sound=_snd("s1.wav", 9.0), cameras=[_cam("c1.mov", 9.01)])
    t2 = Take(sound=_snd("s2.wav", 9.0 + (DAILY_GAP_S - 3600) / H),
              cameras=[_cam("c2.mov", 9.1 + (DAILY_GAP_S - 3600) / H)])
    assert len(split_daily_result(_daily([t1, t2]))) == 1


def test_sem_nada_para_dividir_devolve_UMA_parte():
    """Quem chama não precisa de caso especial: "não dividir" é resposta válida."""
    t = Take(sound=_snd("s.wav", 5.0), cameras=[_cam("c.mov", 5.01)])
    partes = split_daily_result(_daily([t]))
    assert len(partes) == 1 and partes[0]["file_count"] == 2


def test_diaria_vazia_nao_explode():
    assert split_daily_result(_daily()) == []


# ── ⭐ A garantia: a unidade é atômica ───────────────────────────────────────


def test_uma_TOMADA_nunca_se_parte():
    """O som e as câmeras dele saem SEMPRE juntos, mesmo com o som muito mais
    longo que os clipes — é justamente esse par que o corte por metadado quebrava.
    """
    # Um som de 3 h com duas câmeras dentro dele, e outra captação 20 h depois.
    longa = Take(
        sound=_snd("boom.wav", 0.0, dur_s=3 * H),
        cameras=[_cam("c1.mov", 0.5), _cam("c2.mov", 2.5)],
    )
    outra = Take(sound=_snd("s2.wav", 23.0), cameras=[_cam("c3.mov", 23.01)])
    partes = split_daily_result(_daily([longa, outra]))

    assert len(partes) == 2
    primeiro = set(partes[0]["paths"])
    assert primeiro == {_p("boom.wav"), _p("c1.mov"), _p("c2.mov")}, (
        "o som e as duas câmeras dele têm de ficar na MESMA parte"
    )


def test_um_som_longo_nao_deixa_o_vao_aparecer():
    """Se o som atravessa o vão, não há vão: aquilo é uma gravação contínua."""
    longa = Take(sound=_snd("continuo.wav", 0.0, dur_s=22 * H),
                 cameras=[_cam("c1.mov", 0.5)])
    tarde = Take(sound=_snd("s2.wav", 21.0), cameras=[_cam("c2.mov", 21.01)])
    assert len(split_daily_result(_daily([longa, tarde]))) == 1


def test_orfaos_sao_unidades_proprias():
    cam_orfa = _cam("mos.mov", 0.0)
    snd_orfo = _snd("ambiente.wav", 22.0)
    partes = split_daily_result(_daily(orfas_cam=[cam_orfa], orfas_snd=[snd_orfo]))
    assert len(partes) == 2
    assert partes[0]["paths"] == [_p("mos.mov")]
    assert partes[1]["paths"] == [_p("ambiente.wav")]


def test_nenhum_arquivo_se_perde_nem_duplica():
    t1 = Take(sound=_snd("s1.wav", 0.0), cameras=[_cam("c1.mov", 0.01), _cam("c2.mov", 0.02)])
    t2 = Take(sound=_snd("s2.wav", 21.0), cameras=[_cam("c3.mov", 21.01)])
    orfa = _cam("mos.mov", 21.5)
    d = _daily([t1, t2], orfas_cam=[orfa])

    partes = split_daily_result(d)
    todos = [p for parte in partes for p in parte["paths"]]

    esperado = {str(c.path) for c in d.cameras} | {str(s.path) for s in d.all_sounds}
    assert set(todos) == esperado
    assert len(todos) == len(set(todos)), "nenhum arquivo em duas partes"


# ── O que a tela precisa mostrar ─────────────────────────────────────────────


def test_cada_parte_diz_onde_comeca_e_quanto_ocupa():
    t1 = Take(sound=_snd("s1.wav", 1.5), cameras=[_cam("c1.mov", 1.51)])
    t2 = Take(sound=_snd("s2.wav", 23.0), cameras=[_cam("c2.mov", 23.01)])
    partes = split_daily_result(_daily([t1, t2]))
    assert partes[0]["start_tc"] == "01:30"
    assert partes[1]["start_tc"] == "23:00"
    assert partes[0]["take_count"] == 1


def test_o_start_tc_respeita_o_inicio_da_regua():
    """A régua da sequência entregue começa em `start_tc_frames` — a hora que a
    tela mostra tem de ser a que o editor vai ver no Premiere."""
    t = Take(sound=_snd("s.wav", 0.0), cameras=[_cam("c.mov", 0.0)])
    d = _daily([t])
    d.start_tc_frames = round(10 * H * FPS)   # a sequência começa às 10:00
    assert split_daily_result(d)[0]["start_tc"] == "10:00"


def test_needs_split_so_olha_o_limite_do_NLE():
    """Um vão de horas SEM estourar 24 h é informação, não impedimento: uma diária
    com uma pausa longa continua sendo uma diária."""
    t1 = Take(sound=_snd("s1.wav", 0.0), cameras=[_cam("c1.mov", 0.01)])
    t2 = Take(sound=_snd("s2.wav", 21.0), cameras=[_cam("c2.mov", 21.01)])
    d = _daily([t1, t2])
    assert len(split_daily_result(d)) == 2, "há o que dividir…"
    assert not needs_split(d), "…mas cabe em 24 h, então não é obrigatório"
    assert span_hours(d) < 24
