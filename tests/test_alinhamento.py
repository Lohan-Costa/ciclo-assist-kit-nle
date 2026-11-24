"""A L1 do alinhador: o CTC forçado (`midia/alinhamento.py`) e a borda do `voz` partindo dele."""

import numpy as np

from cicloassist.midia import alinhamento as al
from cicloassist.midia import voz


J = voz.JANELA_S


def _duas_lapelas():
    # A mesma cena do test_voz: A fala 1,00–2,00 (oclusiva de 80 ms em 1,50); B fala 2,50–3,00; cada voz vaza −20 dB.
    def env(trechos, nivel):
        e = np.full(int(round(6 / J)), 1e-6)
        for a, b in trechos:
            e[int(round(a / J)):int(round(b / J))] = nivel
        return e
    fa, fb = [(1.0, 1.5), (1.58, 2.0)], [(2.5, 3.0)]
    return {3: env(fa, 1e-2) + env(fb, 1e-4), 4: env(fb, 1e-2) + env(fa, 1e-4)}


class _Falso:
    """Um 'modelo' CTC de mentira: a cada 20 ms emite a letra que o roteiro manda (o resto é branco)."""
    branco = 0
    separador = 1

    def __init__(self, roteiro):            # roteiro: [(inicio_s, fim_s, letra)]
        self.voc = {c: i + 2 for i, c in enumerate("abcdefghijklmnopqrstuvwxyzçãéó")}
        self.roteiro = roteiro

    def tokens(self, w):
        return [self.voc[c] for c in w.lower() if c in self.voc]

    def logprobs(self, x):
        T = len(x) // 320
        lp = np.full((T, 40), -20.0)
        lp[:, 0] = lp[:, 1] = -0.01                  # branco e o separador '|' cabem em qualquer silêncio
        for a, b, c in self.roteiro:
            lp[int(a / 0.02):int(b / 0.02), :] = -20.0
            lp[int(a / 0.02):int(b / 0.02), self.voc[c]] = -0.01
        return lp


def test_o_viterbi_acha_onde_cada_palavra_esta():
    m = _Falso([(0.40, 0.48, "s"), (0.48, 0.60, "o"), (1.20, 1.30, "n"), (1.30, 1.44, "ã"), (1.44, 1.50, "o")])
    r = al.alinhar_trecho(m, np.zeros(2 * al.SR, np.float32), ["So,", "não."])
    assert r[0] == (0.4, 0.6) and r[1] == (1.2, 1.5)


def test_palavra_sem_letra_nenhuma_fica_sem_borda():
    m = _Falso([(0.40, 0.60, "a")])
    assert al.alinhar_trecho(m, np.zeros(al.SR, np.float32), ["a", "123?"])[1] is None


def test_a_janela_leva_o_contexto_das_vizinhas_e_a_longa_e_repartida_no_maior_vao():
    longa = [{"t": 2.0 + k * 0.4, "fim": 2.3 + k * 0.4, "palavra": f"x{k}"} for k in range(10)]   # 2,0 a 5,9
    longa += [{"t": 7.5 + k * 0.4, "fim": 7.8 + k * 0.4, "palavra": f"y{k}"} for k in range(5)]  # vão de 1,6 s
    falas = [{"inicio": 0.5, "fim": 1.8, "palavras": [{"t": 0.5, "fim": 1.8, "palavra": "a"}]},
             {"inicio": 2.0, "fim": 9.4, "palavras": longa}]
    js = al.janelas(falas, 20.0)
    assert len(js) == 3
    seq, p, q, a, b = js[0]
    assert seq == [(0, 0), (1, 0), (1, 1)] and (p, q) == (0, 1)          # "a" + duas palavras da seguinte
    assert a == 0.0 and abs(b - (2.7 + al.MARGEM_S)) < 1e-9
    seq, p, q, *_ = js[1]
    assert seq[p:q] == [(1, k) for k in range(10)] and seq[0] == (0, 0)  # o contexto de trás é a fala anterior
    seq, p, q, *_ = js[2]
    assert seq[p:q] == [(1, k) for k in range(10, 15)] and len(seq) == 5   # o vão de 1,6 s barra o contexto de trás


def test_o_contexto_e_alinhado_mas_descartado():
    m = _Falso([(0.40, 0.60, "a"), (1.00, 1.20, "b")])
    falas = [{"inicio": 0.4, "fim": 0.6, "palavras": [{"t": 0.4, "fim": 0.6, "palavra": "a"}]},
             {"inicio": 0.7, "fim": 1.2, "palavras": [{"t": 0.7, "fim": 1.2, "palavra": "b"}]}]
    r = al.alinhar(falas, np.zeros(2 * al.SR, np.float32), m)
    assert r == [[[0.4, 0.6]], [[1.0, 1.2]]]       # sem o "b" na janela da 1ª, o "a" teria esticado até 1,2


def test_a_regra_do_juiz_e_aplicada_ao_ler_e_so_com_a_mesma_transcricao():
    falas = [{"palavras": [{"t": 1, "fim": 2}, {"t": 3, "fim": 4}]}]
    b = al.bordas({"palavras": [[[1.10, 1.50], None]]}, falas)
    assert b == [[(1.059, 1.56), None]]
    assert al.bordas({"palavras": [[[1.1, 1.5]]]}, falas) is None       # outra transcrição: não se cola calado
    assert al.bordas({}, falas) is None


def test_com_o_alinhador_o_inicio_e_dele_e_o_fim_vai_ate_a_voz():
    # O Whisper errou feio (1,40–1,80); o alinhador diz 1,02–1,70; a voz de A vai de 1,00 a 2,00 (com oclusiva).
    fala = {"inicio": 1.4, "fim": 1.8, "palavras": [{"t": 1.4, "fim": 1.8, "palavra": "sobe"}]}
    d = voz.medir([fala], voz.mascaras(_duas_lapelas(), [3, 4]), [3], [[(1.02, 1.70)]])["falas"][0]
    assert d["voz_inicio"] == 1.02                       # o alinhador, sem a energia andar para trás
    assert abs(d["voz_fim"] - 2.0) <= 0.02               # max(voz, fim do alinhador)
    assert d["borda_por"] == "alinhamento+lapela"
    assert d["palavras"][0]["t_alinhado"] == 1.02


def test_o_fim_do_alinhador_vale_mesmo_quando_a_voz_acaba_antes():
    fala = {"inicio": 1.05, "fim": 1.45, "palavras": [{"t": 1.05, "fim": 1.45, "palavra": "sobe"}]}
    d = voz.medir([fala], voz.mascaras(_duas_lapelas(), [3, 4]), [3], [[(1.0, 2.3)]])["falas"][0]
    assert d["voz_fim"] == 2.3


def test_sem_lapela_a_borda_do_alinhador_vale_sozinha():
    fala = {"inicio": 1.4, "fim": 1.8, "palavras": [{"t": 1.4, "fim": 1.8, "palavra": "a"}, {"t": 1.9, "fim": 2.0}]}
    d = voz.medir([fala], {}, [None], [[(1.02, 1.5), None]])
    f = d["falas"][0]
    assert f["voz_inicio"] == 1.02 and f["borda_por"] == "alinhamento"
    assert "voz_fim" not in f                            # a última palavra não alinhou e não há lapela: não medido
    assert d["silencios"] == [] and d["voz"] == {}
    assert voz.anexar([fala], d)[0]["palavras"][0]["t_alinhado"] == 1.02


def test_no_windows_o_alinhador_nao_roda(monkeypatch):
    monkeypatch.setattr(al.sys, "platform", "win32")
    assert "Mac" in al.motivo_para_nao_rodar()


def test_sem_o_modelo_o_estagio_diz_nao_medido_e_nao_grava(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_ALINHADOR", str(tmp_path / "nada"))
    monkeypatch.setattr(al.sys, "platform", "darwin")
    assert al.NAO_MEDIDO in al.garantir(object.__new__(_SemLer), tmp_path / "x.wav")


def test_a_pasta_do_modelo_pode_vir_do_config(tmp_path, monkeypatch):
    from cicloassist.servico import config
    monkeypatch.delenv("CICLOASSIST_ALINHADOR", raising=False)
    assert al.pasta_do_modelo() == config.pasta() / "modelos" / al.PASTA_DO_MODELO
    config.gravar({"alinhador": str(tmp_path / "no ssd")})
    assert al.pasta_do_modelo() == tmp_path / "no ssd"
    monkeypatch.setenv("CICLOASSIST_ALINHADOR", str(tmp_path / "dev"))
    assert al.pasta_do_modelo() == tmp_path / "dev"          # o ambiente ainda manda


class _SemLer:
    def _ler_json(self, _):
        return None

    def arquivo(self, nome):
        from pathlib import Path
        return Path("/nao/existe") / nome


def _rabo_fraco():
    # A fala forte 1,00–1,50 e depois um RESTO FRACO até 2,10 (sala, respiro): acima do piso, 15 dB abaixo da palavra.
    e = np.full(int(round(6 / J)), 1e-6)
    e[int(1.0 / J):int(1.5 / J)] = 1e-2
    e[int(1.5 / J):int(2.1 / J)] = 3e-4
    outro = np.full_like(e, 1e-6)
    outro[int(3.0 / J):int(4.0 / J)] = 1e-2                     # o outro ator fala depois (dá referência à lapela dele)
    return {3: e, 4: outro}


def test_com_nivel_o_fim_e_a_queda_e_nao_o_resto_fraco():
    fala = {"inicio": 1.0, "fim": 1.5, "palavras": [{"t": 1.0, "fim": 1.5, "palavra": "toda."}]}
    envs = _rabo_fraco()
    pela_mascara = voz.medir([fala], voz.mascaras(envs, [3, 4]), [3], [[(0.959, 1.52)]])["falas"][0]
    assert pela_mascara["voz_fim"] > 2.0                        # o defeito que o ouvido reprovou
    d = voz.medir([fala], voz.mascaras(envs, [3, 4]), [3], [[(0.959, 1.52)]], voz.niveis(envs, [3, 4]))["falas"][0]
    assert abs(d["voz_fim"] - 1.52) <= 0.02                     # o tombo em 1,50, com o piso CTC+60


def test_a_queda_segue_a_voz_forte_e_para_antes_da_proxima():
    e = np.full(int(round(6 / J)), 1e-6)
    e[int(1.0 / J):int(1.9 / J)] = 1e-2                          # a voz segue FORTE depois do fim do CTC ("você")
    e[int(2.0 / J):int(2.5 / J)] = 1e-2                          # e a palavra seguinte começa em 2,00
    envs = {3: e, 4: np.full_like(e, 1e-6)}
    nv = voz.niveis(envs, [3, 4])
    assert abs(voz.queda(nv, 3, 1.0, 1.40, 3.0) - 1.9) <= 0.02
    assert voz.queda(nv, 3, 1.0, 1.95, 1.97) <= 1.97              # nunca passa do limite
