"""
TIMECODE REC-RUN — o relógio que ordena mas não mede.

Uma câmera *free-run* marca a HORA: o intervalo entre dois clipes é o tempo real
que passou entre eles. Uma câmera *rec-run* marca o METRO DE FITA: cada clipe
começa exatamente onde o anterior terminou, e o tempo em que ela ficou parada não
é registrado em lugar nenhum.

Os dois passam em `tc_usable` — todo clipe tem TC, todos distintos, monotônicos. A
diferença só aparece quando se pergunta uma DISTÂNCIA, e foi exatamente aí que o
motor tropeçou: `_travar_cronologia` travava os clipes numa corrente com as
distâncias do relógio, colando as tomadas umas nas outras.

⭐ O CASO REAL que gerou este arquivo (material MULTCAM, Panasonic, 11 clipes): os
DEZ intervalos de timecode batiam com a duração do clipe anterior ao frame. A
forma de onda tinha acertado as onze posições, em ordem e sem um aviso; a corrente
embaralhou tudo e sinalizou 10.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync import chronology


class TestDetectarRecRun:
    def test_clipes_contiguos_no_TC_sao_rec_run(self):
        # Cada clipe começa onde o anterior acabou: 0+100=100, 100+250=350…
        tc = [0, 100, 350, 500]
        dur = [100, 250, 150, 90]
        assert chronology.rec_run(tc, dur) is True

    def test_os_numeros_REAIS_da_Panasonic(self):
        # Medidos no material MULTCAM. Se este teste cair, a detecção deixou de
        # pegar o caso que motivou a feature.
        tc = [2011379, 2012615, 2015327, 2016959, 2018771, 2020211,
              2021915, 2026367, 2026835, 2032403, 2045267]
        dur = [1236, 2712, 1632, 1812, 1440, 1704, 4452, 468, 5568, 12864, 4092]
        assert chronology.rec_run(tc, dur) is True

    def test_free_run_NAO_e_rec_run(self):
        # Free-run: entre as tomadas há pausa do operador, e ela aparece no TC.
        tc = [0, 5000, 20000, 41000]
        dur = [100, 250, 150, 90]
        assert chronology.rec_run(tc, dur) is False

    def test_um_par_contiguo_nao_basta(self):
        # Duas tomadas seguidas sem pausa acontecem numa câmera free-run. A
        # afirmação precisa do PADRÃO, não de um caso.
        tc = [0, 100]
        dur = [100, 50]
        assert chronology.rec_run(tc, dur) is False

    def test_uma_pausa_de_verdade_derruba_a_conclusao(self):
        tc = [0, 100, 350, 90000]
        dur = [100, 250, 150, 90]
        assert chronology.rec_run(tc, dur) is False

    def test_tolera_o_arredondamento_de_ms_para_frames(self):
        # A duração vem de `duration_ms`; 1 ou 2 frames de folga é arredondamento,
        # não intervalo — a menor pausa de operador é de segundos.
        tc = [0, 101, 352]
        dur = [100, 250, 150]
        assert chronology.rec_run(tc, dur) is True

    def test_sem_timecode_ou_sem_duracao_nao_conclui_nada(self):
        assert chronology.rec_run([None, None, None], [10, 10, 10]) is False
        assert chronology.rec_run([0, 100, 350], [None, None, None]) is False
        assert chronology.rec_run([], []) is False

    def test_rec_run_NAO_derruba_a_base_timecode(self):
        # A ORDEM é o que o rec-run sabe, e ela continua valendo: um TC rec-run é
        # monotônico e ordena a câmera certo. Só a DISTÂNCIA é que não existe.
        arquivos = [
            {"nome": f"PANA{i}.mov", "tc_sec": t / 24, "tc_frames": t, "meta": {}}
            for i, t in enumerate([0, 100, 350, 500])
        ]
        assert chronology.propose("camera", arquivos) == "timecode"
