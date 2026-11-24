"""
O GRAVADOR NÃO SE PARTE AO MEIO.

`align_to_window` decide o dia de um arquivo pela DISTÂNCIA até a janela das
câmeras. Isso funciona enquanto os dois relógios estão perto. Mas o Δ entre o
relógio de um gravador e o de uma câmera é LIVRE — pode ser qualquer coisa —, e
quando ele fica grande a distância empata: "ficar" e "voltar um dia" custam quase
o mesmo, e o desempate vira um fio de navalha.

⭐ O CASO REAL (gravador 15 h fora do TC das câmeras): o fio passava
NO MEIO dos 36 WAVs. Os de timecode menor ficavam no dia 0, os maiores pulavam
para o dia −1, e o gravador saía partido em dois blocos a 24 h um do outro. O
resultado: som espalhado por 24h30, 24 câmeras sem candidato de som, e o app
perguntando se aquilo eram duas diárias.

A distância entre os arquivos do MESMO gravador é a única coisa que o material
afirma com certeza — é o próprio relógio dele. Partir isso é destruir o dado bom
para responder a uma pergunta (a volta de 24 h) cuja resposta o `tcmatch` nem
precisa que esteja certa: o Δ livre dele ABSORVE a volta.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sync.daycycle import DAY_S, align_block_to_window, align_to_window


class TestOBlocoAndaJunto:
    def test_um_conjunto_recebe_UMA_resposta(self):
        # Distâncias que empatam de lados opostos: um a um, este conjunto se parte.
        janela = (3033.0, 28176.0)
        tcs = [57287.0, 58375.0, 59044.0, 60000.0, 82413.0]

        um_a_um = {align_to_window(tc, *janela) for tc in tcs}
        assert len(um_a_um) > 1, "o cenário tem de ser mesmo o do fio de navalha"

        # Em bloco: uma resposta só, seja ela qual for.
        k = align_block_to_window(tcs, *janela)
        assert isinstance(k, int)

    def test_os_numeros_REAIS_do_D03(self):
        """36 WAVs de um gravador 15 h fora do TC das câmeras."""
        lo, hi = 3033.0, 28176.0
        tcs = [57287.2, 57785.7, 58375.3, 59044.0, 59171.1, 59983.0,
               60580.0, 68000.0, 75000.0, 82413.0]

        assert len({align_to_window(tc, lo, hi) for tc in tcs}) == 2, \
            "um a um, o gravador era partido em dois dias"

        k = align_block_to_window(tcs, lo, hi)
        # A DISTÂNCIA INTERNA sobrevive — é o que importa, não qual volta venceu.
        movidos = [tc + k * DAY_S for tc in tcs]
        for a, b in zip(tcs, movidos):
            assert b - a == k * DAY_S

    def test_a_escolha_APROXIMA_o_conjunto_da_janela(self):
        # Janela das câmeras 00:00–01:00; bloco de som às 22:00.
        # Ficar deixa o bloco 21 h DEPOIS da janela; voltar um dia o põe 2 h ANTES
        # dela. A resposta certa é a que aproxima — mesmo custando uma volta inteira.
        lo, hi = 0.0, 3600.0
        tcs = [79200.0, 80000.0, 81000.0]
        assert align_block_to_window(tcs, lo, hi) == -1

    def test_um_bloco_ja_dentro_da_janela_nao_se_mexe(self):
        lo, hi = 3600.0, 18000.0
        tcs = [4000.0, 9000.0, 17000.0]
        assert align_block_to_window(tcs, lo, hi) == 0

    def test_conjunto_vazio_nao_quebra(self):
        assert align_block_to_window([], 0.0, 100.0) == 0

    def test_janela_invertida_e_tolerada(self):
        # Mesma defesa que `align_to_window` já tinha.
        tcs = [4000.0, 9000.0]
        assert align_block_to_window(tcs, 18000.0, 3600.0) == 0


# ── O motor: `_unwrap_sounds` não pode partir um gravador ────────────────────

import sync.engine as engine   # noqa: E402


def _som(nome: str, tc: float):
    """Um som com timecode e SEM data de parede — o caminho 2 do `_unwrap_sounds`."""
    s = engine._Sound(Path(nome), {"duration_ms": 60000.0, "tc_start_sec": tc})
    s.group_id = "gravador"
    return s


def _cam(nome: str, tc: float):
    c = engine._Clip.__new__(engine._Clip)
    c.path = Path(nome)
    c.group_id = "cam"
    c.meta = {}
    c.duration_s = 300.0
    c.duration_frames = 7200
    c.day_index = 0
    c.tc_sec = tc
    # `_tc_usable` (que decide se há janela de câmeras) lê os dois.
    c.tc_frames = round(tc * 24)
    c._tc_fps = 24.0
    c._fps = 24.0
    return c


class TestUnwrapSoundsNaoParteOGravador:
    """
    ⭐ A REGRESSÃO DO D03, no motor.

    Um gravador 15 h fora do TC das câmeras, sem data de parede utilizável. Um a
    um, o desempate de distância partia os 36 WAVs em dois blocos a 24 h — e o
    pareamento perdia 24 câmeras.
    """

    def _cenario(self):
        # Câmeras 00:50 → 07:48 (TC que não é hora do dia).
        cams = [_cam(f"A{i}.mp4", tc) for i, tc in
                enumerate([3033.0, 10000.0, 20000.0, 28129.0])]
        # Gravador 09:20 → 22:53 no relógio DELE — de um lado e do outro do fio.
        sons = [_som(f"S{i}.wav", tc) for i, tc in
                enumerate([57287.0, 58375.0, 59044.0, 60000.0, 82413.0])]
        return {"cam": cams}, ["cam"], sons

    def test_todos_os_sons_do_gravador_caem_no_MESMO_dia(self):
        groups, order, sons = self._cenario()
        engine._unwrap_sounds(sons, groups, order)

        dias = {s.day_index for s in sons}
        assert len(dias) == 1, (
            f"o gravador foi partido em {len(dias)} dias ({sorted(dias)}) — "
            "a distância entre os arquivos dele deixou de valer"
        )

    def test_a_distancia_INTERNA_do_gravador_sobrevive(self):
        # É o dado que o material afirma com certeza: o relógio do próprio gravador.
        groups, order, sons = self._cenario()
        antes = [s.tc_sec for s in sons]
        engine._unwrap_sounds(sons, groups, order)
        depois = [s.tc_abs_sec for s in sons]

        for i in range(len(antes) - 1):
            assert depois[i + 1] - depois[i] == antes[i + 1] - antes[i]

    def test_dois_gravadores_decidem_SEPARADO(self):
        # O bloco é quem compartilha um relógio, não "todos os sons".
        groups, order, sons = self._cenario()
        outro = _som("OUTRO.wav", 4000.0)      # já dentro da janela das câmeras
        outro.group_id = "gravador-2"
        sons.append(outro)

        engine._unwrap_sounds(sons, groups, order)
        assert outro.day_index == 0, "um gravador não arrasta o outro"
