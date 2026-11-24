"""As colunas dos cards e os alertas de TC (`servidor/fichas.py`)."""
from __future__ import annotations

import fichas as F


def _f(i, inicio, fim, canais=2, **k):
    return {"id": i, "nome": k.pop("nome", i), "inicio_s": inicio, "fim_s": fim, "tol_s": 0.02,
            "duracao_ms": None if fim is None else (fim - inicio) * 1000, "canais": canais, **k}


def _segundos(tc, fps, drop):
    h, m, s, q = (int(x) for x in tc.split(":"))
    return h * 3600 + m * 60 + s + q / fps


def test_a_camera_le_a_imagem_e_soma_os_canais_do_op_atom():
    leituras = [{"width": 1920, "height": 1080, "fps": 25.0, "tc_start": "01:00:00:00", "frame_count": 50,
                 "codec_label": "DNx", "total_audio_channels": 0},
                {"total_audio_channels": 1}, {"total_audio_channels": 1}]
    f = F.ficha_da_camera(leituras, _segundos)
    assert f["resolucao"] == "1920×1080" and f["canais"] == 2
    assert f["inicio_s"] == 3600 and f["fim_s"] == 3602
    assert f["duracao"] == "00:00:02:00"


def test_o_som_sem_plano_no_arquivo_fica_vazio_e_nao_chuta():
    f = F.ficha_do_som([{"tc_start_sec": 10.0, "duration_ms": 5000.0, "scene": "4", "take": "2", "channels": 5}])
    assert (f["cena"], f["take"], f["plano"], f["canais"]) == ("4", "2", None, 5)
    assert f["fim_s"] == 15.0


def test_a_claquete_do_nome_vence_a_tag_do_gravador():
    class Lida:
        cena, plano, take = "C04", "P04", "T003"
    tags = [{"tc_start_sec": 10.0, "duration_ms": 5000.0, "scene": "PRODUCAO-A - 05-04", "take": "003", "channels": 5}]
    f = F.ficha_do_som(tags, "PRODUCAO-A - 05-04 C4 P4-T003.WAV", lambda n: Lida)
    assert (f["cena"], f["plano"], f["take"]) == ("C04", "P04", "T003")
    g = F.ficha_do_som(tags, "SEM PADRAO.WAV", lambda n: None)
    assert (g["cena"], g["plano"], g["take"]) == ("PRODUCAO-A - 05-04", None, "003")


def test_um_arquivo_ilegivel_nao_derruba_o_lote():
    def sondar(c):
        raise OSError("sumiu")
    status, r = F.rota_fichas({"clipes": [{"id": "a", "arquivos": ["x"]}]}, sondar)
    assert status == 200 and r["fichas"][0]["erro"] == "sumiu"


def test_a_rota_recusa_lote_grande_e_clipe_sem_arquivo():
    grande = [{"id": str(i), "arquivos": ["x"]} for i in range(F.MAXIMO_POR_LOTE + 1)]
    assert F.rota_fichas({"clipes": grande})[0] == 400
    assert F.rota_fichas({"clipes": [{"id": "a", "arquivos": []}]})[0] == 400


def test_sobreposto_marca_os_dois_lados():
    v = [_f("a", 0.5, 10), _f("b", 9, 20), _f("c", 30, 40)]
    assert F.conflitos(v, []) == {"a": [F.SOBREPOSTO], "b": [F.SOBREPOSTO]}


def test_a_sobreposicao_olha_o_que_termina_mais_tarde():
    # `b` cabe inteiro dentro de `a`; `c` começa depois de `b` acabar, mas ainda dentro de `a`
    v = [_f("a", 1, 100), _f("b", 2, 3), _f("c", 50, 60)]
    assert set(F.conflitos(v, [])) == {"a", "b", "c"}


def test_continuo_e_o_quadro_seguinte_ao_fim():
    v = [_f("a", 1, 10), _f("b", 10.01, 20), _f("c", 21, 30)]
    assert F.conflitos(v, []) == {"a": [F.CONTINUO], "b": [F.CONTINUO]}


def test_um_zerado_so_nao_e_conflito_e_mais_de_um_e():
    assert F.conflitos([_f("a", 0, 5, zerado=True), _f("b", 9, 12)], []) == {}
    r = F.conflitos([_f("a", 0, 5, zerado=True), _f("b", 0, 7, zerado=True)], [])
    assert r == {"a": [F.ZERADO], "b": [F.ZERADO]}


def test_sem_tc_nao_e_conflito():
    assert F.conflitos([_f("a", None, None), _f("b", None, None)], []) == {}


def test_o_mono_do_mesmo_take_vira_um_grupo_e_nao_conflita():
    v = [_f("t1_1", 100, 110, canais=1), _f("t1_2", 100, 110, canais=1), _f("t2", 200, 210, canais=2)]
    grupos = F.grupos_monofonicos(v)
    assert grupos == [["t1_1", "t1_2"]]
    assert F.conflitos(v, grupos) == {}


def test_o_grupo_mono_que_conflita_marca_todos_os_canais():
    v = [_f("t1_1", 100, 110, canais=1), _f("t1_2", 100, 110, canais=1), _f("t2", 105, 120, canais=2)]
    grupos = F.grupos_monofonicos(v)
    assert set(F.conflitos(v, grupos)) == {"t1_1", "t1_2", "t2"}


def test_estereo_com_o_mesmo_tc_e_conflito_nao_grupo():
    v = [_f("a", 100, 110, canais=2), _f("b", 100, 110, canais=2)]
    assert F.grupos_monofonicos(v) == []
    assert F.conflitos(v, []) == {"a": [F.SOBREPOSTO], "b": [F.SOBREPOSTO]}


def test_tc_zerado_so_agrupa_se_o_nome_tambem_bater():
    v = [_f("x", 0, 10, canais=1, zerado=True, nome="ABC_1.wav"),
         _f("y", 0, 10, canais=1, zerado=True, nome="ABC_2.wav"),
         _f("z", 0, 10, canais=1, zerado=True, nome="OUTRO_1.wav")]
    assert F.grupos_monofonicos(v) == [["x", "y"]]


def test_os_canais_extras_saem_do_sync_e_voltam_na_mesma_posicao():
    clips = [{"path": "cam"}, {"path": "a_1", "kind": "sound"}, {"path": "a_2", "kind": "sound", "mono_de": "a_1"}]
    para_o_motor, irmaos = F.separar_mono(clips)
    assert [c["path"] for c in para_o_motor] == ["cam", "a_1"] and irmaos == {"a_2": "a_1"}
    r = {"groups": [{"takes": [{"sound": {"path": "a_1", "timeline_start_frames": 37, "channels": 1}}], "orphan_sounds": []}]}
    F.devolver_mono(r, irmaos)
    assert r["groups"][0]["orphan_sounds"] == [{"path": "a_2", "timeline_start_frames": 37, "channels": 1}]


def test_sem_mono_o_resultado_nao_muda():
    r = {"groups": [{"takes": [], "orphan_sounds": []}]}
    assert F.devolver_mono(r, {}) == {"groups": [{"takes": [], "orphan_sounds": []}]}
