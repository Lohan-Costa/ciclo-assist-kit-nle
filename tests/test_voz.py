"""A L2 do alinhador: a borda da voz pela lapela (`midia/voz.py`) e o corte que só ESTENDE (`asr.com_respiro`)."""

import numpy as np

from cicloassist.midia import asr, voz

J = voz.JANELA_S
PISO, VOZ, VAZA = 1e-6, 1e-2, 1e-4   # potência: piso de sala, voz na própria lapela, voz vazando na outra (−20 dB)


def _env(dur_s, trechos, nivel):
    e = np.full(int(round(dur_s / J)), PISO)
    for a, b in trechos:
        e[int(round(a / J)):int(round(b / J))] = nivel
    return e


def _duas_lapelas():
    # A fala 1,00–2,00 (com uma oclusiva de 80 ms em 1,50) e 4,00–4,40 não é de ninguém; B fala 2,50–3,00.
    a = _env(6, [(1.0, 1.5), (1.58, 2.0)], VOZ) + _env(6, [(2.5, 3.0)], VAZA)
    b = _env(6, [(2.5, 3.0)], VOZ) + _env(6, [(1.0, 1.5), (1.58, 2.0)], VAZA)   # o vazamento acompanha a voz de A
    return {3: a, 4: b}


def _medido(falas, canais):
    envs = _duas_lapelas()
    return voz.medir(falas, voz.mascaras(envs, [3, 4]), canais)


def test_o_fim_vai_ate_onde_a_voz_acaba_e_a_oclusiva_nao_encerra():
    fala = {"inicio": 1.05, "fim": 1.45, "palavras": [{"t": 1.05, "fim": 1.45, "palavra": "sobe"}]}
    m = _medido([fala], [3])["falas"][0]
    assert abs(m["voz_inicio"] - 1.0) <= 0.02
    assert abs(m["voz_fim"] - 2.0) <= 0.02        # atravessou o buraco de 80 ms em 1,50
    assert m["canal"] == 3


def test_o_fim_medido_nunca_fica_antes_do_asr():
    fala = {"inicio": 1.05, "fim": 2.3, "palavras": [{"t": 1.05, "fim": 2.3, "palavra": "comigo"}]}
    m = _medido([fala], [3])["falas"][0]
    assert m["voz_fim"] == 2.3                      # a trava do juiz de ouvido


def test_a_voz_que_vaza_para_a_outra_lapela_nao_conta_como_dela():
    fala = {"inicio": 2.55, "fim": 2.8, "palavras": [{"t": 2.55, "fim": 2.8, "palavra": "não"}]}
    m = _medido([fala], [3])["falas"][0]            # pedida na lapela errada (A): ali não há voz de A
    assert "voz_fim" not in m or m["voz_fim"] == 2.8


def test_palavra_sem_voz_em_lapela_nenhuma_e_marcada_e_vira_provavel_equipe():
    fala = {"inicio": 4.0, "fim": 4.4, "texto": "ser", "palavras": [{"t": 4.0, "fim": 4.4, "palavra": "ser"}]}
    dados = _medido([fala], [None])
    assert dados["falas"][0]["fora_das_lapelas"] is True
    f = voz.anexar([fala], dados)[0]
    assert f["quem"] == voz.EQUIPE and f["fora_das_lapelas"] is True
    assert f["texto"] == "ser"                      # marcada e mostrada, nunca apagada


def test_silencio_e_item_e_o_corte_pergunta_se_cai_em_fala():
    dados = _medido([], [])
    assert any(a <= 2.1 and b >= 2.4 for a, b in dados["silencios"])
    assert voz.em_fala(dados, 1.7) == (voz.FALA, 3)
    assert voz.em_fala(dados, 2.7) == (voz.FALA, 4)
    assert voz.em_fala(dados, 2.2) == (voz.SILENCIO, None)
    assert voz.em_fala({}, 2.2) == (voz.NAO_MEDIDO, None)


def test_sem_lapela_nada_e_medido():
    d = voz.medir([{"inicio": 1, "fim": 2}], {}, [None])
    assert d["falas"] == [{}] and d["silencios"] == [] and d["voz"] == {}


def test_lapelas_pela_correlacao_tiram_as_copias_da_mistura():
    envs = _duas_lapelas()
    mistura = envs[3] + envs[4]
    envs = {1: mistura, 2: mistura.copy(), 3: envs[3], 4: envs[4]}
    assert voz.lapelas_por_correlacao(envs) == [3, 4]


def test_anexar_nao_cola_medida_de_outra_transcricao():
    falas = [{"inicio": 1, "fim": 2}, {"inicio": 3, "fim": 4}]
    assert voz.anexar(falas, {"falas": [{"voz_fim": 9}]}) == falas


def test_com_respiro_so_estende_pela_voz_medida():
    base = [{"inicio": 10.0, "fim": 11.0}, {"inicio": 15.0, "fim": 16.0}]
    sem = asr.com_respiro(base)
    # a voz real vai além do respiro de 0,40 s: o corte vai até ela
    com = asr.com_respiro([{**base[0], "voz_fim": 11.9, "voz_inicio": 9.6}, base[1]])
    assert com[0]["corte_fim"] == 11.9 and com[0]["corte_inicio"] == 9.6 and com[0]["corte_pela_voz"] is True
    # a voz medida dentro do respiro NÃO encurta o corte
    curto = asr.com_respiro([{**base[0], "voz_fim": 11.05, "voz_inicio": 9.95}, base[1]])
    assert curto[0]["corte_fim"] == sem[0]["corte_fim"] and curto[0]["corte_inicio"] == sem[0]["corte_inicio"]
    assert "corte_pela_voz" not in curto[0]


def test_com_respiro_a_voz_nao_invade_a_fala_vizinha():
    falas = [{"inicio": 10.0, "fim": 11.0, "voz_fim": 12.5}, {"inicio": 12.0, "fim": 13.0}]
    r = asr.com_respiro(falas)
    assert r[0]["corte_fim"] <= 12.0 - asr.VAO_MINIMO_S + 1e-9
