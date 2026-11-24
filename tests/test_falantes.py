"""Quem fala, pela lapela (plano `docs/plano/2026-11-06-transcricao-por-canal.md`, F1)."""

from __future__ import annotations

import math
import struct
import wave
from pathlib import Path

import numpy as np
import pytest

from cicloassist import binarios
from cicloassist.midia import analise as A
from cicloassist.midia import cache as C
from cicloassist.midia import canais as K
from cicloassist.midia import falantes as F

CHAVE = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.1a8edcf3.1260a306.7860d011.e5e70399"


# ── o papel e os nomes ───────────────────────────────────────────────────────

@pytest.mark.parametrize("nome,papel", [
    ("MIC2", K.PESSOA), ("PESSOA-H", K.PESSOA), ("BOOMER", K.PESSOA), ("Tr2MIC1", K.PESSOA),
    ("BOOM", K.BOOM), ("BOOM 2", K.BOOM), ("Tr1 BOOM", K.BOOM),
    ("MixL", K.MISTURA), ("TrL", K.MISTURA), ("TRR", K.MISTURA),
    ("STEREO MS L", K.AMBIENTE), ("", K.SEM_NOME), ("Tr8", K.SEM_NOME),
])
def test_papel(nome, papel):
    assert K.papel(nome) == papel


def test_colunas_trk_em_ordem_numerica_e_as_ausentes_sem_nome():
    """O laboratório: a bin tem TRK3..5 e não TRK1/2 (o mixdown sem nome)."""
    tr = K.de_colunas({"TRK3": "MIC2", "TRK4": "MIC3", "TRK5": "BOOM"}, canais=5)
    assert [(t.canal, t.nome, t.papel) for t in tr] == [
        (1, "", K.SEM_NOME), (2, "", K.SEM_NOME), (3, "MIC2", K.PESSOA), (4, "MIC3", K.PESSOA), (5, "BOOM", K.BOOM)]
    assert [t.canal for t in K.de_colunas({"TRK10": "A", "TRK2": "B", "TRK1": "C"})][:3] == [1, 2, 3]
    assert K.de_colunas({}) == [] and K.de_colunas({"UBITS": "1"}) == []


def _wav(caminho: Path, canais: list[np.ndarray], ixml: str = "", taxa: int = 48000) -> Path:
    dados = np.stack(canais, axis=1)
    pcm = (np.clip(dados, -1, 1) * 32767).astype("<i2").tobytes()
    with wave.open(str(caminho), "wb") as w:
        w.setnchannels(len(canais)); w.setsampwidth(2); w.setframerate(taxa); w.writeframes(pcm)
    if ixml:
        corpo = ixml.encode()
        chunk = b"iXML" + struct.pack("<I", len(corpo)) + corpo + (b"\0" if len(corpo) & 1 else b"")
        b = bytearray(caminho.read_bytes()) + chunk
        b[4:8] = struct.pack("<I", len(b) - 8)
        caminho.write_bytes(bytes(b))
    return caminho


IXML = ("<BWFXML><TRACK_LIST><TRACK_COUNT>4</TRACK_COUNT>"
        "<TRACK><CHANNEL_INDEX>1</CHANNEL_INDEX><INTERLEAVE_INDEX>1</INTERLEAVE_INDEX></TRACK>"
        "<TRACK><CHANNEL_INDEX>4</CHANNEL_INDEX><INTERLEAVE_INDEX>2</INTERLEAVE_INDEX><NAME>MIC2</NAME></TRACK>"
        "<TRACK><CHANNEL_INDEX>5</CHANNEL_INDEX><INTERLEAVE_INDEX>3</INTERLEAVE_INDEX><NAME>MIC3</NAME></TRACK>"
        "<TRACK><CHANNEL_INDEX>10</CHANNEL_INDEX><INTERLEAVE_INDEX>4</INTERLEAVE_INDEX><NAME>BOOM</NAME></TRACK>"
        "</TRACK_LIST></BWFXML>")


def test_ixml_pelo_interleave_index_nunca_pelo_channel_index(tmp_path):
    z = np.zeros(4800)
    w = _wav(tmp_path / "t.wav", [z, z, z, z], IXML)
    assert [(t.canal, t.nome, t.papel) for t in K.de_ixml(w)] == [
        (1, "", K.SEM_NOME), (2, "MIC2", K.PESSOA), (3, "MIC3", K.PESSOA), (4, "BOOM", K.BOOM)]
    assert K.de_ixml(_wav(tmp_path / "sem.wav", [z])) == []


@pytest.mark.parametrize("nome,pos", [
    ("PRODUCAO-A - 05-04 C4 P4-T003_A03.mxf", 3), ("A01.E69CCE71_1A1641A164AC2A.mxf", 1),
    ("C4 P4-T003_V01.mxf", None), ("som.wav", None)])
def test_posicao_do_arquivo(nome, pos):
    assert K.posicao_do_arquivo(nome) == pos


# ── a regra ──────────────────────────────────────────────────────────────────

TR = K.de_colunas({"TRK1": "MixL", "TRK2": "", "TRK3": "MIC2", "TRK4": "MIC3", "TRK5": "BOOM"})


def test_a_lapela_mais_forte_ganha_por_margem():
    a = F.atribuir({1: 0, 2: 0, 3: -10, 4: -20, 5: -5}, TR)
    assert (a.motivo, a.canal, a.nome) == (F.RESOLVIDA, 3, "MIC2") and a.margem_db == 10


def test_mistura_e_boom_nunca_disputam_mesmo_mais_altos():
    a = F.atribuir({1: 0, 5: 0, 3: -30, 4: -40}, TR)
    assert a.nome == "MIC2"


def test_empate_e_ambigua_com_os_candidatos():
    a = F.atribuir({3: -20, 4: -21.5, 5: -10}, TR)
    assert a.motivo == F.AMBIGUA and {c["nome"] for c in a.candidatos} == {"MIC2", "MIC3"}
    assert a.canal is None


def test_uma_lapela_so_nao_e_resolvida():
    """⚠️ o falso-verde do Assist anterior: uma lapela só, "100% resolvido"."""
    tr = K.de_colunas({"TRK1": "MixL", "TRK2": "LAP1", "TRK3": "BOOM"})
    a = F.atribuir({1: 0, 2: -10, 3: -5}, tr)
    assert a.motivo == F.SEM_COMPARACAO and a.margem_db is None


def test_lapela_calada_nao_disputa():
    a = F.atribuir({3: -20, 4: -200}, TR)
    assert a.motivo == F.SEM_COMPARACAO


def test_sem_nomes_nao_adivinha_pela_posicao():
    assert F.atribuir({1: -10, 2: -30}, []).motivo == F.SEM_NOMES
    assert F.atribuir({1: -10, 2: -30}, K.de_colunas({"TRK1": "", "TRK2": ""})).motivo == F.SEM_NOMES


# ── de ponta a ponta, num WAV sintético ──────────────────────────────────────

precisa_ffmpeg = pytest.mark.skipif(not (binarios.achar("ffmpeg") and binarios.achar("ffprobe")),
                                    reason="sem ffmpeg/ffprobe")


def _tom(taxa, dur, ini, fim, amp, f=300.0):
    t = np.arange(int(taxa * dur)) / taxa
    s = amp * np.sin(2 * math.pi * f * t)
    s[(t < ini) | (t >= fim)] = 0
    return s


@precisa_ffmpeg
def test_de_ponta_a_ponta_com_ganho_desigual_e_a_equipe_ambigua(tmp_path):
    """Ator A fala 1–3 s (na MIC2), ator B 4–6 s (na MIC3), a "equipe" 7–9 s chega igual nas duas — e a MIC2 entra
    8 dB mais alta que a MIC3 na mesa (o caso medido no laboratório). A equipe tem de sair AMBÍGUA, não "MIC2"."""
    taxa, dur = 48000, 10.0
    ruido = np.random.default_rng(1).normal(0, 0.0005, int(taxa * dur))
    g2, g3 = 0.5, 0.5 / 10 ** (8 / 20)
    mic2 = g2 * (_tom(taxa, dur, 1, 3, 0.6) + _tom(taxa, dur, 4, 6, 0.03) + _tom(taxa, dur, 7, 9, 0.1)) + ruido
    mic3 = g3 * (_tom(taxa, dur, 1, 3, 0.03) + _tom(taxa, dur, 4, 6, 0.6) + _tom(taxa, dur, 7, 9, 0.1)) + ruido
    boom = 0.3 * (_tom(taxa, dur, 1, 3, 0.5) + _tom(taxa, dur, 4, 6, 0.5) + _tom(taxa, dur, 7, 9, 0.5)) + ruido
    mix = (mic2 + mic3 + boom) / 3
    w = _wav(tmp_path / "take.wav", [mix, mic2, mic3, boom], IXML)

    m = C.Midia(CHAVE, tmp_path / "cache")
    m.guardar_transcricao([{"inicio": 1.0, "fim": 3.0, "texto": "a"}, {"inicio": 4.0, "fim": 6.0, "texto": "b"},
                           {"inicio": 7.0, "fim": 9.0, "texto": "equipe"}])
    tr, fonte = A.trilhas_do_som([str(w)])
    assert fonte == "ixml"
    d = A.quem_fala(m, [str(w)], tr, fonte)
    falas = d["falas"]
    assert (falas[0]["motivo"], falas[0]["nome"]) == (F.RESOLVIDA, "MIC2")
    assert (falas[1]["motivo"], falas[1]["nome"]) == (F.RESOLVIDA, "MIC3")
    assert falas[2]["motivo"] == F.AMBIGUA

    # ⭐ a segunda leitura vem do cache; refeita a transcrição, cai sozinha
    assert F.ler(m) == d
    m.guardar_transcricao([{"inicio": 1.0, "fim": 3.0, "texto": "a refeita"}])
    assert F.ler(m) == {}
    assert len(A.quem_fala(m, [str(w)], tr, fonte)["falas"]) == 1


@precisa_ffmpeg
def test_opatom_um_arquivo_por_canal_na_ordem_do_nome(tmp_path):
    taxa, dur = 48000, 4.0
    a = _tom(taxa, dur, 1, 3, 0.5)
    z = np.random.default_rng(2).normal(0, 0.0005, int(taxa * dur))
    # os arquivos fora de ordem na lista: a posição sai do NOME
    # ⚠️ cada lapela tem a fala do PRÓPRIO ator (aqui 3,2–3,8 s na MIC3): a normalização mede o canal contra o nível
    #    dele, e uma lapela que só ouvisse o vazamento do outro seria "normalizada para cima" até empatar
    b_ = _tom(taxa, dur, 3.2, 3.8, 0.5)
    arqs = [str(_wav(tmp_path / "T_A04.wav", [0.01 * a + b_ + z])), str(_wav(tmp_path / "T_A03.wav", [a + z])),
            str(_wav(tmp_path / "T_A01.wav", [a])), str(_wav(tmp_path / "T_A02.wav", [a])),
            str(_wav(tmp_path / "T_A05.wav", [a]))]
    envs = F.envelopes(arqs)
    assert sorted(envs) == [1, 2, 3, 4, 5]
    tr = K.de_colunas({"TRK3": "MIC2", "TRK4": "MIC3", "TRK5": "BOOM"}, canais=5)
    (r,) = F.atribuir_falas([{"inicio": 1.2, "fim": 2.8}], envs, tr)
    assert r["nome"] == "MIC2"


def test_sem_nomes_grava_a_resposta_e_nao_mede(tmp_path):
    m = C.Midia(CHAVE, tmp_path / "cache")
    m.guardar_transcricao([{"inicio": 0, "fim": 1, "texto": "x"}])
    d = F.garantir(m, ["/nao/existe.mxf"], [])
    assert d["falas"] == [{"motivo": F.SEM_NOMES}]


def test_falantes_atravessa_os_bancos():
    assert "falantes.json" in C.Midia.COPIAVEIS


# ── F2: as ambíguas com lapelas altas são ouvidas ────────────────────────────

def test_ambigua_baixa_e_provavel_equipe_e_alta_vai_para_a_f2():
    envs = {3: [1e-2] * 40 + [1e-6] * 40, 4: [1e-2] * 40 + [1e-6] * 40}      # p95 = 1e-2 nas duas
    tr = K.de_colunas({"TRK3": "MIC2", "TRK4": "MIC3"})
    alta, baixa = F.atribuir_falas([{"inicio": 0.1, "fim": 1.5}, {"inicio": 2.1, "fim": 3.9}], envs, tr)
    assert alta["motivo"] == F.AMBIGUA and alta["altas"] == [3, 4] and "provavel" not in alta
    assert baixa["motivo"] == F.AMBIGUA and baixa["provavel"] == "equipe" and "altas" not in baixa


def test_parecenca():
    assert F.parecenca("Cena 4, plano 4, tomada 3.", "cena quatro plano 4 tomada 3") >= F.MESMA_VOZ
    assert F.parecenca("Você não me ouviu.", "Eu já disse que não vou") < F.MESMA_VOZ
    # ⛔ o caso que a 1ª versão (palavras inteiras) chamou de sobreposta: a mesma voz, o ASR errando diferente
    assert F.parecenca("Será 4, os câmeras?", "Sena 4, câmera...") >= F.MESMA_VOZ
    assert F.parecenca("Eu sou Personagem F, a terapeuta.", "Ah, então não era você no telefone.") < F.MESMA_VOZ


@precisa_ffmpeg
def test_f2_sobreposta_e_mesma_voz(tmp_path):
    taxa, dur = 48000, 4.0
    a = _tom(taxa, dur, 1, 3, 0.5)
    w = _wav(tmp_path / "t.wav", [a, a, a, a], IXML)
    tr = K.de_ixml(w)
    falas = [{"inicio": 1.0, "fim": 3.0}, {"inicio": 1.0, "fim": 3.0}]
    ats = [{"motivo": F.AMBIGUA, "altas": [2, 3]}, {"motivo": F.AMBIGUA, "altas": [2, 3]}]
    textos = iter(["Você não me ouviu.", "Eu já disse que não vou.", "Cena 4, plano 4", "cena 4 plano 4"])
    assert F.ouvir_ambiguas(falas, ats, [str(w)], tr, ouvir=lambda _w: next(textos)) == 2
    assert ats[0]["motivo"] == F.SOBREPOSTA
    assert [(v["nome"], v["texto"]) for v in ats[0]["vozes"]] == [("MIC2", "Você não me ouviu."),
                                                                  ("MIC3", "Eu já disse que não vou.")]
    assert ats[1]["motivo"] == F.AMBIGUA and ats[1]["mesma_voz"] is True


# ── F3: o que o modelo e a tela leem ─────────────────────────────────────────

def test_rotulos():
    assert F.rotulo({"motivo": F.RESOLVIDA, "nome": "MIC2"}) == "MIC2"
    assert F.rotulo({"motivo": F.AMBIGUA, "provavel": "equipe",
                     "candidatos": [{"nome": "MIC2"}, {"nome": "MIC3"}]}) == "provável equipe"
    assert F.rotulo({"motivo": F.AMBIGUA, "candidatos": [{"nome": "MIC2"}, {"nome": "MIC3"}]}) == "ambígua: MIC2 ou MIC3"
    assert "mesma voz em MIC2 e MIC3" in F.rotulo({"motivo": F.AMBIGUA, "mesma_voz": True,
                                                  "candidatos": [{"nome": "MIC2"}, {"nome": "MIC3"}]})
    assert F.rotulo({"motivo": F.SOBREPOSTA, "vozes": [{"nome": "MIC2", "texto": "a"}, {"nome": "MIC3", "texto": "b"}]}) \
        == "sobreposta: MIC2 «a» + MIC3 «b»"
    assert F.rotulo({"motivo": F.SEM_NOMES}) == "" and F.rotulo({"motivo": F.SEM_COMPARACAO}) == ""


def test_anexar_so_com_a_mesma_contagem():
    falas = [{"texto": "a"}, {"texto": "b"}]
    dados = {"falas": [{"motivo": F.RESOLVIDA, "nome": "MIC2"}, {"motivo": F.SEM_NOMES}]}
    assert F.anexar(falas, dados) == [{"texto": "a", "quem": "MIC2"}, {"texto": "b"}]
    assert F.anexar(falas, {"falas": [{"motivo": F.RESOLVIDA, "nome": "MIC2"}]}) == falas    # outra transcrição


def test_resumo_diz_por_que_nao_sabe():
    assert "não têm nome" in F.resumo({"trilhas": [], "falas": []})
    um = {"trilhas": [t.como_dicionario() for t in K.de_colunas({"TRK1": "LAP1", "TRK2": "BOOM"})], "falas": []}
    assert "uma lapela só" in F.resumo(um)
    dois = {"trilhas": [t.como_dicionario() for t in TR], "fonte_dos_nomes": "bin",
            "falas": [{"motivo": F.RESOLVIDA}, {"motivo": F.AMBIGUA}]}
    r = F.resumo(dois)
    assert "MIC2, MIC3" in r and "colunas da bin" in r and "1 resolvidas" in r
