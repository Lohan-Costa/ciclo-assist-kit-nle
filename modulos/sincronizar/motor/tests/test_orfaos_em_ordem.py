"""
CLIPE ÓRFÃO ENTRA NA TIMELINE, E NA ORDEM — nunca reordenado, nunca omitido.

⭐ A REGRA, ditada pelo autor em 2026-08-22 (editor):

    "Clipes órfãos entram na TL sim. Se não houver TC para fazer o deslocamento em
    âncora, minimamente eles entram após o último clipe de sync, SEM mudar a ordem.
    Exemplo A B C D E: A B e D E encontraram sync, C não. Se não houver TC para
    presumir a distância entre B e D, o C fica colado no B. O mesmo se C e D não
    acharem sync mas B e E encontrarem: o C vai colado após o B e o D colado após o
    C. Dessa forma garantimos que todos os clipes estão na ordem, e o editor faz uma
    revisão pontual sabendo que o clipe só pode existir dentro de um espaço de tempo
    — que são os clipes anteriores e posteriores que acharam sync."

⭐⭐ O RACIOCÍNIO, que é o que vale preservar: um órfão não é um clipe sem
informação. Ele é um clipe cuja posição está **limitada pelos vizinhos que
sincronizaram**. Manter a ordem converte "não sei onde isto vai" em "isto vai
entre B e D" — que é uma revisão de segundos em vez de uma busca.

⚠️ POR QUE ISTO GANHOU TESTE AGORA: o conserto da 28ª (par sem âncora é desfeito)
tornou o órfão MUITO mais comum — na D03 foram de 2 para 13 de uma vez. O que
antes era caso de borda virou caminho normal, e a ordem deles passou a ser parte
do que se entrega.

Sem mídia: constrói-se `_Clip`/`_Sound` à mão para isolar o POSICIONAMENTO da
correlação.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import sync.engine as engine

FPS = 24.0
DUR_MS = 10_000.0                      # 10 s = 240 frames a 24 fps
DUR_FRAMES = 240


def _clip(nome: str, ordem: int, *, tc_sec: float | None = None) -> "engine._Clip":
    c = engine._Clip(Path(f"/fake/{nome}.mov"), {
        "duration_ms": DUR_MS, "has_audio": True, "fps": FPS,
        "tc_start": None, "tc_drop_frame": False, "size_bytes": 1000, "channels": 2,
    }, "CAM A", ordem, FPS)
    c.tc_sec = tc_sec
    c.tc_frames = None if tc_sec is None else round(tc_sec * FPS)
    return c


def _som(nome: str, tc_sec: float | None = None) -> "engine._Sound":
    s = engine._Sound(Path(f"/fake/{nome}.wav"), {
        "duration_ms": 60_000.0, "sample_rate": 48000, "channels": 2,
        "tc_start_sec": tc_sec,
    })
    s.pcm = np.zeros(8, dtype=np.float32)
    return s


def _parear(c: "engine._Clip", s: "engine._Sound", offset: int) -> None:
    """Liga clipe e som dos DOIS lados — como `_pair_by_waveform` faz."""
    c.sound = s
    c.offset_frames = offset
    c.confidence = 5.0
    c.sync_source = "waveform"
    s.clips.append(c)


def _posicionar(clips, sons):
    engine._place_on_timeline({"CAM A": clips}, ["CAM A"], sons, FPS)
    return [c.timeline_start for c in clips]


# ═══════════════════════════════════════════════════════════════════════════
# O caso ditado: A B C D E, com C órfão e SEM timecode nenhum
# ═══════════════════════════════════════════════════════════════════════════

def test_orfao_no_meio_sem_tc_fica_colado_no_anterior():
    """A B [C órfão] D E — o C entra entre o B e o D, colado no B.

    Sem TC não há como presumir a distância; inventar um buraco seria mentir, e
    mandá-lo para o fim quebraria a ordem que o editor usa para revisar.
    """
    a, b, c, d, e = [_clip(n, i) for i, n in enumerate("ABCDE")]
    s1, s2 = _som("S1"), _som("S2")
    _parear(a, s1, 0)
    _parear(b, s1, DUR_FRAMES)
    _parear(d, s2, 0)
    _parear(e, s2, DUR_FRAMES)

    pos = _posicionar([a, b, c, d, e], [s1, s2])

    assert pos == sorted(pos), f"a ordem da câmera foi quebrada: {pos}"
    assert pos[2] >= pos[1] + DUR_FRAMES, (
        f"o órfão C ficou ANTES do fim do B (C={pos[2]}, B termina em {pos[1] + DUR_FRAMES})"
    )
    assert pos[2] <= pos[3], f"o órfão C passou do D (C={pos[2]}, D={pos[3]})"


def test_dois_orfaos_seguidos_encadeiam_sem_reordenar():
    """A B [C D órfãos] E — o C cola depois do B, e o D cola depois do C.

    É o segundo exemplo do autor, e o que prova que a regra ENCADEIA: o segundo
    órfão se apoia no primeiro, não volta ao último clipe sincronizado.
    """
    a, b, c, d, e = [_clip(n, i) for i, n in enumerate("ABCDE")]
    s1, s2 = _som("S1"), _som("S2")
    _parear(a, s1, 0)
    _parear(b, s1, DUR_FRAMES)
    _parear(e, s2, 0)

    pos = _posicionar([a, b, c, d, e], [s1, s2])

    assert pos == sorted(pos), f"a ordem da câmera foi quebrada: {pos}"
    assert pos[2] >= pos[1] + DUR_FRAMES, "o C não respeitou o fim do B"
    assert pos[3] >= pos[2] + DUR_FRAMES, "o D não se apoiou no C — a cadeia quebrou"


def test_nenhum_clipe_some_da_timeline():
    """Órfão NÃO é clipe descartado. Todos entram, sempre.

    ⚠️ A trava contra a tentação de 'simplificar' escondendo o que não
    sincronizou: um clipe ausente da timeline é material que o editor não sabe
    que existe.
    """
    clips = [_clip(n, i) for i, n in enumerate("ABCDE")]
    s1 = _som("S1")
    _parear(clips[0], s1, 0)

    pos = _posicionar(clips, [s1])

    assert len(pos) == 5
    assert all(p is not None for p in pos)
    assert pos == sorted(pos)


def test_orfao_no_fim_entra_depois_do_ultimo_sync():
    """A B C [D E órfãos] — os dois entram no fim, na ordem, sem buraco inventado."""
    a, b, c, d, e = [_clip(n, i) for i, n in enumerate("ABCDE")]
    s1 = _som("S1")
    _parear(a, s1, 0)
    _parear(b, s1, DUR_FRAMES)
    _parear(c, s1, DUR_FRAMES * 2)

    pos = _posicionar([a, b, c, d, e], [s1])

    assert pos == sorted(pos), f"a ordem foi quebrada: {pos}"
    assert pos[3] >= pos[2] + DUR_FRAMES
    assert pos[4] >= pos[3] + DUR_FRAMES


def test_com_timecode_o_orfao_usa_o_PROPRIO_relogio():
    """Havendo TC, ele manda — a colagem é o piso, não a regra.

    Contrapeso dos testes acima: se o clipe sabe as horas, a distância real é
    melhor que a colagem. Medido na D03 (2026-08-22): o `a005_C025`, órfão por
    `too_short`, caiu exatamente entre o C024 e o C026 pelo próprio TC.
    """
    a, b, c = (_clip("A", 0, tc_sec=0.0), _clip("B", 1, tc_sec=100.0),
               _clip("C", 2, tc_sec=200.0))
    s1 = _som("S1", tc_sec=0.0)
    _parear(a, s1, 0)
    _parear(c, s1, round(200.0 * FPS))

    pos = _posicionar([a, b, c], [s1])

    assert pos == sorted(pos)
    # O B tem TC próprio e cai perto dele — não colado no A.
    assert pos[1] > pos[0] + DUR_FRAMES, (
        "o órfão com TC foi colado no anterior em vez de usar o próprio relógio"
    )


# ═══════════════════════════════════════════════════════════════════════════
# O RELÓGIO DA DIÁRIA É O DO GRAVADOR — e o órfão emenda na PRÓPRIA câmera
# ═══════════════════════════════════════════════════════════════════════════

def test_o_som_ancora_a_ilha__nao_a_camera():
    """⛔ O defeito da D03 (2026-08-22): os áudios tinham TC a partir de 15h44 e
    caíam no COMEÇO da timeline.

    Havia dois relógios na mesma sequência: as ilhas eram ancoradas pelo TC da
    CÂMERA e os sons sem câmera pelo TC DELES. Quando os aparelhos não
    compartilham relógio — câmera em rec-run começando perto do zero, gravador em
    hora-do-dia — as duas metades ficam a horas uma da outra.

    ⭐ O gravador é quem tem RELÓGIO DE PAREDE. É a leitura que o `autosequence`
    do Media Composer entrega, e a que o editor espera.
    """
    cam = _clip("CAM", 0, tc_sec=50.0 * 60)          # câmera diz 00:50
    som = _som("SOM", tc_sec=15 * 3600 + 54 * 60)    # gravador diz 15:54
    _parear(cam, som, 0)

    engine._place_on_timeline({"CAM A": [cam]}, ["CAM A"], [som], FPS)

    # A ilha tem de pousar no relógio do SOM, não no da câmera.
    assert som.timeline_start == round(som.tc_abs_sec * FPS), (
        "o som não caiu no próprio TC — a ilha foi ancorada pela câmera"
    )
    assert abs(cam.timeline_start - som.timeline_start) < FPS, (
        "a câmera deveria acompanhar o som pelo offset medido"
    )


def test_orfao_sem_relogio_emenda_no_vizinho_DA_CAMERA():
    """⛔ O terceiro defeito da D03: os órfãos emendavam corretamente ENTRE SI,
    mas a cadeia começava 4h23 depois do fim da diária.

    A emenda usava o `cursor` do laço de ilhas — "o fim do que já foi posicionado
    na ordem das ILHAS", que não é a ordem da câmera. ⭐ "Colado no B" é uma
    afirmação sobre a CÂMERA, não sobre o dia.

    Aqui o som está a 10 h de distância no relógio, o que empurraria o cursor
    para longe; o órfão tem de ignorar isso e colar no vizinho dele.
    """
    a = _clip("A", 0, tc_sec=0.0)
    b = _clip("B", 1)                       # órfão, sem TC
    som = _som("SOM", tc_sec=10 * 3600)     # gravador 10 h à frente
    _parear(a, som, 0)

    engine._place_on_timeline({"CAM A": [a, b]}, ["CAM A"], [som], FPS)

    assert b.timeline_start == a.timeline_start + a.duration_frames, (
        f"o órfão não colou no vizinho da própria câmera "
        f"(A termina em {a.timeline_start + a.duration_frames}, B em {b.timeline_start})"
    )


# ═══════════════════════════════════════════════════════════════════════════
# EMPATE DE SOBREPOSIÇÃO NÃO SE RESOLVE POR ORDEM DE LISTA
# ═══════════════════════════════════════════════════════════════════════════

def test_dois_sons_que_empatam_vao_AMBOS_para_a_waveform():
    """⛔ O único erro CALADO de todas as medições contra o gabarito (2026-08-23).

    Na D03 de `PROJETO EXEMPLO`, o clipe `a005_…C008` era coberto por dois sons com
    **201,8 s cada — empate exato**. `candidate_sounds` guardava só o de maior
    sobreposição, e `>` num empate significa "fica o primeiro da lista": a escolha
    era a ORDEM DOS ARQUIVOS, não uma medida. Deu no som errado, e sem aviso.

    ⭐ A waveform separava os dois com folga (5,28 contra 1,13). Empate se resolve
    perguntando a quem sabe — é o que o cabeçalho do `tcmatch` sempre disse.

    ⚠️ O piso é ALTO de propósito (`_EMPATE_RELATIVO`). Uma versão anterior usou
    25% "para dar mais opções" e empatou o placar: consertou um clipe e quebrou
    outro, porque deixou entrar candidato que não era empate nenhum.
    """
    from sync.tcmatch import ClockOffset, Interval, candidate_sounds

    cam = Interval("cam", 100.0, 300.0)
    empatado_a = Interval("A", 50.0, 300.0)     # cobre os 200 s inteiros
    empatado_b = Interval("B", 100.0, 350.0)    # idem, por outro lado
    longe = Interval("C", 290.0, 400.0)         # só encosta

    cands = candidate_sounds(cam, [empatado_a, empatado_b, longe],
                             [ClockOffset(delta=0.0, coverage=1.0)])
    chaves = {k for k, _ in cands}
    assert {"A", "B"} <= chaves, (
        f"os dois sons que empatam têm de ir à waveform (foram {chaves})"
    )
    assert "C" not in chaves, "mas quem só encosta NÃO entra — o piso é de empate"


def test_sem_empate_continua_UM_candidato():
    """O caso comum não muda: cada correlação a mais é cara.

    Medido na D03: com o piso de empate, 6 de 37 clipes ganham um segundo
    candidato (média 1,16). Se este teste passar a falhar, alguém afrouxou o piso
    e o sync ficou mais lento sem pedir licença.
    """
    from sync.tcmatch import ClockOffset, Interval, candidate_sounds

    cam = Interval("cam", 100.0, 300.0)
    bom = Interval("A", 50.0, 400.0)      # cobre tudo
    fraco = Interval("B", 280.0, 400.0)   # cobre 20 s de 200

    cands = candidate_sounds(cam, [bom, fraco],
                             [ClockOffset(delta=0.0, coverage=1.0)])
    assert [k for k, _ in cands] == ["A"], (
        "um som que cobre 10% do clipe não é empate com quem cobre 100%"
    )
