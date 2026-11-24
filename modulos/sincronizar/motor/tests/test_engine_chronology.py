"""
A cronologia por FONTE: em quem confiar, câmera a câmera.

O motor tinha uma regra só para todo mundo — o timecode sobrescrevia a ordem sempre
que o relógio andasse. Numa captação organizada isso é o certo; numa falha, é o
motor confiando num relógio que não merece, e o usuário não tinha como discordar.

⚠️ O invariante que estes testes protegem: **campo ausente = comportamento de
antes**. A base só entra quando alguém a declara; sem ela, o motor diagnostica com
a MESMA função que a interface usa para propor.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine
from sync import chronology

FPS = 24.0


def _clip(nome, gid, tc_sec, *, conf=2.0, basis="timecode", dur=240, rec_run=False):
    c = engine._Clip.__new__(engine._Clip)
    c.path = Path(nome)
    c.group_id = gid
    c.group_name = gid
    c.meta = {}
    c.duration_frames = dur
    c.duration_s = dur / FPS
    c.offset_frames = 0
    c.confidence = conf
    c.flagged = False
    c.flag_reason = None
    c.sync_source = "waveform"
    c.pinned = False
    c.basis = basis
    # O TC desta fonte mede DISTÂNCIA (free-run) ou só ordena (rec-run)? Ver
    # `_Clip.tc_rec_run` — a corrente só pode ser travada no primeiro caso.
    c.tc_rec_run = rec_run
    c.implied_delta = None
    c.timeline_start = 0
    c.sound = None
    c.tc_sec = tc_sec
    c.day_index = 0
    c._fps = FPS
    c._tc_fps = FPS
    return c


def _som():
    s = engine._Sound.__new__(engine._Sound)
    s.path = Path("s.wav")
    s.duration_s = 3600.0
    s.clips = []
    s.timeline_start = 0
    s.placed = False
    s.group_id = "grav"
    s.meta = {}
    return s


def _liga(clipes, som, offsets):
    for c, off in zip(clipes, offsets):
        c.sound = som
        c.offset_frames = off
        som.clips.append(c)


# ── O diagnóstico ────────────────────────────────────────────────────────────

def test_propoe_timecode_quando_o_relogio_anda():
    arq = [{"nome": f"A{i}.mov", "tc_sec": 10.0 * i, "tc_frames": 240 * i, "meta": {}}
           for i in range(1, 5)]
    assert chronology.propose("camera", arq) == "timecode"


def test_propoe_nome_quando_o_relogio_esta_parado():
    """O drone real: `00:00:00:00` nos 8 arquivos."""
    arq = [{"nome": f"DJI_{i:04d}.mov", "tc_sec": 0.0, "tc_frames": 0, "meta": {}}
           for i in range(8)]
    assert chronology.propose("camera", arq) == "name"
    tc = next(o for o in chronology.evaluate("camera", arq)["options"]
              if o["basis"] == "timecode")
    assert tc["why"] == "relogio_parado", "o motivo tem de ser exibível"


def test_som_nunca_recebe_a_base_NOME():
    """O nome de um gravador segue cena e tomada, não o relógio."""
    arq = [{"nome": "LOCAL-2-005.wav", "tc_sec": None, "tc_frames": None, "meta": {}}]
    bases = {o["basis"] for o in chronology.evaluate("sound", arq)["options"]}
    assert "name" not in bases
    assert "bwf" in bases


def test_som_com_bwf_completo_propoe_bwf():
    arq = [{"nome": "00-18-57.wav", "tc_sec": None, "tc_frames": None,
            "meta": {"bwf_date": "2024-10-25", "bwf_time": "00:18:57"}}]
    assert chronology.propose("sound", arq) == "bwf"


def test_a_proposta_diz_se_nome_e_timecode_CONCORDAM():
    """O sinal mais útil da tela: quando as duas autoridades divergem, o editor
    precisa saber antes de escolher."""
    arq = [{"nome": "A1.mov", "tc_sec": 30.0, "tc_frames": 720, "meta": {}},
           {"nome": "A2.mov", "tc_sec": 10.0, "tc_frames": 240, "meta": {}}]
    nome = next(o for o in chronology.evaluate("camera", arq)["options"]
                if o["basis"] == "name")
    assert "DISCORDA" in nome["detail"]


# ── A corrente ───────────────────────────────────────────────────────────────

def test_a_corrente_preserva_a_distancia_do_relogio():
    """O ponto todo: numa câmera de relógio bom, a distância entre os clipes é a
    do timecode — uma medição ruim não pode mover um clipe sozinho."""
    som = _som()
    a = _clip("a.mov", "cam", 0.0, conf=4.0)
    b = _clip("b.mov", "cam", 100.0, conf=4.0)
    c = _clip("c.mov", "cam", 200.0, conf=1.2)      # medição fraca
    # `c` foi medido MUITO fora do lugar; a e b concordam com o relógio
    _liga([a, b, c], som, [1000, 1000 + round(100 * FPS), 99999])
    groups, order = {"cam": [a, b, c]}, ["cam"]

    engine._travar_cronologia(groups, order, FPS, lambda *x, **k: None, None)

    d_ab = b.offset_frames - a.offset_frames
    d_bc = c.offset_frames - b.offset_frames
    assert d_ab == round(100 * FPS), "a distância entre a e b é a do relógio"
    assert d_bc == round(100 * FPS), "e o clipe perdido voltou para a corrente"


def test_uma_fonte_de_DOIS_clipes_nao_forma_corrente():
    """
    Com dois, a "mediana dos resíduos" é um dos dois: o motor copiaria o resíduo de
    um clipe no outro e chamaria isso de voto. Não há nada ali que CONFIRME o
    espaçamento do relógio — e com dois clipes nem dá para saber se ele é rec-run.

    Medido no MULTCAM: a CAM A, de dois clipes, era arrastada 38 frames (1,6 s)
    para longe de uma medição de forma de onda confiável.
    """
    som = _som()
    a = _clip("a.mov", "cam", 0.0, conf=4.0)
    b = _clip("b.mov", "cam", 100.0, conf=4.0)
    medido = [1000, 8000]
    _liga([a, b], som, list(medido))

    engine._travar_cronologia({"cam": [a, b]}, ["cam"], FPS, lambda *x, **k: None, None)

    assert [a.offset_frames, b.offset_frames] == medido


def test_uma_camera_REC_RUN_nao_e_travada_na_corrente():
    """
    ⭐ A REGRESSÃO DO MATERIAL MULTCAM, em miniatura.

    Num TC rec-run o relógio só anda gravando: as "distâncias" dele são as DURAÇÕES
    dos clipes, e a pausa entre as tomadas não existe no metadado. Travar a corrente
    por ele COLA as tomadas umas nas outras e destrói as posições que a forma de
    onda já tinha acertado — foi o que embaralhou 11 clipes de uma Panasonic real.

    Aqui a forma de onda pôs os três longe uns dos outros. O motor tem de deixá-los
    exatamente onde estão.
    """
    som = _som()
    a = _clip("a.mov", "cam", 0.0, conf=4.0, rec_run=True)
    b = _clip("b.mov", "cam", 10.0, conf=4.0, rec_run=True)
    c = _clip("c.mov", "cam", 20.0, conf=4.0, rec_run=True)
    medido = [1000, 50000, 120000]
    _liga([a, b, c], som, list(medido))
    groups, order = {"cam": [a, b, c]}, ["cam"]

    engine._travar_cronologia(groups, order, FPS, lambda *x, **k: None, None)

    assert [a.offset_frames, b.offset_frames, c.offset_frames] == medido
    assert not any(x.flagged for x in (a, b, c)), "e ninguém é sinalizado à toa"


def test_a_corrente_desliza_pela_MEDIANA_e_nao_pela_media():
    """Uma medição perdida a 20 minutos puxaria a média e levaria a corrente
    inteira junto. A mediana ignora o grito e ouve o coro."""
    som = _som()
    clipes = [_clip(f"{i}.mov", "cam", 100.0 * i, conf=4.0) for i in range(5)]
    offs = [round(100 * FPS) * i + 500 for i in range(5)]
    offs[4] = 999999                                   # o grito
    _liga(clipes, som, offs)
    engine._travar_cronologia({"cam": clipes}, ["cam"], FPS, lambda *x, **k: None, None)
    assert clipes[0].offset_frames == 500, "o coro (deslize 500) tinha de vencer"


def test_quem_nao_foi_confirmado_pela_onda_SAI_MARCADO():
    """A corrente pode mover, mas não pode disfarçar: um clipe que a forma de onda
    não confirmou é sync de relógio, e a timeline precisa dizer isso."""
    som = _som()
    # TRÊS clipes: a corrente exige corroboração (ver
    # `test_uma_fonte_de_DOIS_clipes_nao_forma_corrente`), então dois deixariam
    # este teste passar pelo motivo errado — nada se moveria.
    a = _clip("a.mov", "cam", 0.0, conf=4.0)
    b = _clip("b.mov", "cam", 50.0, conf=4.0)
    fraco = _clip("fraco.mov", "cam", 100.0, conf=1.2)
    _liga([a, b, fraco], som, [0, round(50 * FPS), 5])
    engine._travar_cronologia({"cam": [a, b, fraco]}, ["cam"], FPS,
                              lambda *x, **k: None, None)
    assert fraco.flagged, "moveu sem confirmação e ficou calado"
    assert fraco.sync_source == "timecode", "não pode se passar por sync de onda"
    assert not a.flagged, "quem já era confiável não vira alarme"


def test_base_NAME_e_FREE_nao_travam_nada():
    """Só `timecode` trava. Nas outras bases cada clipe encontra o seu lugar."""
    for base in ("name", "free"):
        som = _som()
        # TRÊS: com dois, o guarda de corroboração já barraria e o teste passaria
        # sem nunca exercitar a base.
        a = _clip("a.mov", "cam", 0.0, basis=base)
        b = _clip("b.mov", "cam", 50.0, basis=base)
        c = _clip("c.mov", "cam", 100.0, basis=base)
        _liga([a, b, c], som, [0, 1000, 77777])
        engine._travar_cronologia({"cam": [a, b, c]}, ["cam"], FPS,
                                  lambda *x, **k: None, None)
        assert c.offset_frames == 77777, f"a base {base} não podia travar"
