"""A timeline do editor pelo chat: ler em timecode, conferir, e editar uma cópia com prova.

Conferido contra a `TL EDITADA` real em 2026-09-13 (cópia no temp, sem Media Composer): a
extração e o "inserir + abrir espaço" das ferramentas saíram, trilha a trilha, com a MESMA
impressão digital das sequências que o editor aprovou na tela — e o segundo com as operações
em ordem trocada, que é o ponto da regra "todo timecode é da timeline original".
"""

from __future__ import annotations

from pathlib import Path

import avb
import pytest

from cicloassist.avid import edicao as E
from cicloassist.avid import timeline as T
from cicloassist.avid import timeline_do_editor as TE
from cicloassist.avid.mcapi import McApiErro, mob_id_da_api
from cicloassist.mcp.ferramentas import edicao as F
from cicloassist.servico import vocabulario

FPS = 24
FORA = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.000000ff"
AMBOS = (("picture", 1), ("sound", 1))
IMAGEM = (("picture", 1),)


def _subclipe(f, nome, duracao=500, trilhas=AMBOS, visivel=True):
    c = T.montar_timeline(f, nome, [T.Entrada(mob_id=FORA, duracao=duracao, trilhas=trilhas)],
                          FPS)
    c.usage_code = 2
    if not visivel:
        next(i for i in f.content.items if i.mob is c).user_placed = False
    return c


@pytest.fixture
def bin_tl(tmp_path) -> Path:
    """TL: imagem A(0-100) B(100-150) C(150-230); som A(0-100) vazio(100-150) C(150-230).

    Em timecode: A 01:00:00:00, B 01:00:04:04, C 01:00:06:06, fim 01:00:09:14."""
    caminho = tmp_path / "CENA.avb"
    with avb.open() as f:
        take = _subclipe(f, "TAKE", visivel=False)
        _subclipe(f, "MUDO", trilhas=IMAGEM)
        mid = str(take.mob_id)
        T.montar_timeline(f, "TL", [
            T.Entrada(mob_id=mid, duracao=100, trilhas=AMBOS, start_time=10),
            T.Entrada(mob_id=mid, duracao=50, trilhas=IMAGEM, start_time=200),
            T.Entrada(mob_id=mid, duracao=80, trilhas=AMBOS, start_time=300),
        ], FPS)
        f.write(str(caminho))
    return caminho


def _mobs(caminho):
    with avb.open(str(caminho)) as f:
        memo = {}
        return {str(m.mob_id): (m.name, E.impressao(m, memo)) for m in f.content.mobs}


def _trilha(caminho, nome, rotulo):
    with avb.open(str(caminho)) as f:
        seq = TE.achar_sequencia(f, nome)
        n = TE._posicao_da_trilha(seq, rotulo)
        return [(type(c).__name__, c.length, getattr(c, "start_time", None))
                for c in E.segmentos(seq)[n] if c.length]


# ── ler ──────────────────────────────────────────────────────────────────────

def test_ler_devolve_timecode_de_record_e_o_in_de_cada_clipe(bin_tl):
    r = TE.ler(bin_tl, "TL")
    assert r["inicio"] == "01:00:00:00" and r["fim"] == "01:00:09:14"
    assert r["trilhas"]["V1"][1] == "01:00:04:04 → 01:00:06:06 · TAKE (in 200)"
    # ⭐ Vazio não vira linha: o buraco da A1 é o que falta entre as duas.
    assert len(r["trilhas"]["A1"]) == 2


def test_ler_so_o_trecho_e_as_trilhas_pedidas(bin_tl):
    r = TE.ler(bin_tl, "TL", de="01:00:04:10", ate="01:00:05:00", trilhas=["v1"])
    assert list(r["trilhas"]) == ["V1"]
    assert r["trilhas"]["V1"] == ["01:00:04:04 → 01:00:06:06 · TAKE (in 200)"]


def test_leitura_longa_para_no_TEMPO_e_diz_de_onde_continuar(bin_tl, monkeypatch):
    """⛔ Parar pela ordem das trilhas cortaria o áudio inteiro, calado."""
    monkeypatch.setattr(TE, "ORCAMENTO_CHARS", 120)
    r = TE.ler(bin_tl, "TL")
    assert r["trilhas"]["V1"] and r["trilhas"]["A1"]
    assert "de='01:00:04:04'" in r["aviso"]


def test_sequencia_pelo_mobid_da_API_que_o_monitor_devolve(bin_tl):
    with avb.open(str(bin_tl)) as f:
        urn = str(TE.achar_sequencia(f, "TL").mob_id)
    assert TE.ler(bin_tl, mob_id_da_api(urn))["sequencia"] == "TL"


def test_sem_bin_acha_a_bin_da_sequencia_no_projeto(bin_tl, tmp_path):
    outra = tmp_path / "OUTRA.avb"
    with avb.open() as f:
        _subclipe(f, "X")
        f.write(str(outra))
    assert TE.achar_bin_da_sequencia([outra, bin_tl], "TL") == bin_tl


def test_mob_id_da_api_tem_os_cinco_blocos():
    assert [len(x) for x in mob_id_da_api(FORA).split("-")] == [26, 6, 16, 12, 4]


# ── conferir e aplicar ───────────────────────────────────────────────────────

def test_conferir_nao_toca_no_disco(bin_tl):
    antes = bin_tl.read_bytes()
    r = TE.aplicar(bin_tl, "TL", [{"tipo": "extrair", "de": "01:00:04:04",
                                   "ate": "01:00:06:06"}])
    assert r["duracao_depois"].endswith("(180 frames)")
    assert bin_tl.read_bytes() == antes


def test_gravar_poe_a_copia_ao_lado_e_nada_mais_muda(bin_tl):
    antes = _mobs(bin_tl)
    r = TE.aplicar(bin_tl, "TL", [{"tipo": "extrair", "de": "01:00:04:04",
                                   "ate": "01:00:06:06"}], gravar=True)
    depois = _mobs(bin_tl)
    assert {k: v for k, v in depois.items() if k in antes} == antes
    assert [v[0] for k, v in depois.items() if k not in antes] == ["TL - editada"]
    assert r["mob_id_novo"] in depois
    assert _trilha(bin_tl, "TL - editada", "A1") == [("SourceClip", 100, 10),
                                                     ("SourceClip", 80, 300)]


def test_todo_timecode_e_da_timeline_ORIGINAL(bin_tl):
    """⭐⭐ Extrair B e abrir espaço antes de C, os dois nos tempos que o modelo LEU. Em
    sequência, o segundo ponto teria de descontar os 50 frames do primeiro."""
    TE.aplicar(bin_tl, "TL", [
        {"tipo": "extrair", "de": "01:00:04:04", "ate": "01:00:06:06"},
        {"tipo": "abrir_espaco", "em": "01:00:06:06", "duracao_frames": 24},
    ], nome="JUNTAS", gravar=True)
    assert _trilha(bin_tl, "JUNTAS", "V1") == [
        ("SourceClip", 100, 10), ("Filler", 24, None), ("SourceClip", 80, 300)]


def test_operacoes_sobrepostas_sao_recusadas(bin_tl):
    with pytest.raises(TE.TimelineErro, match="DENTRO do trecho"):
        TE.aplicar(bin_tl, "TL", [
            {"tipo": "extrair", "de": "01:00:00:00", "ate": "01:00:06:06"},
            {"tipo": "abrir_espaco", "em": "01:00:04:04", "duracao_frames": 24}])


def test_recusa_diz_a_trilha_como_o_editor_ve(bin_tl):
    with pytest.raises(TE.TimelineErro, match=r"operação 1 .*V1: .*MEIO de um clipe"):
        TE.aplicar(bin_tl, "TL", [{"tipo": "extrair", "de": "01:00:01:00",
                                   "ate": "01:00:02:00"}])


def test_timecode_invalido_volta_com_a_frase(bin_tl):
    with pytest.raises(TE.TimelineErro, match="HH:MM:SS:FF"):
        TE.aplicar(bin_tl, "TL", [{"tipo": "abrir_espaco", "em": "4s", "duracao_frames": 2}])
    with pytest.raises(TE.TimelineErro, match="inválido a 24 fps"):
        TE.aplicar(bin_tl, "TL", [{"tipo": "abrir_espaco", "em": "01:00:00:24",
                                   "duracao_frames": 2}])


# ── inserir ──────────────────────────────────────────────────────────────────

def test_inserir_clipe_OCULTO_da_bin_em_imagem_e_som(bin_tl):
    """⭐ Mob oculto é material — medido na `TL EDITADA`."""
    TE.aplicar(bin_tl, "TL", [{"tipo": "inserir", "em": "01:00:04:04", "clipe": "TAKE",
                               "in_no_clipe": 400, "duracao_frames": 48,
                               "imagem_em": "V1", "som_em": ["A1"]}], nome="INS", gravar=True)
    assert _trilha(bin_tl, "INS", "V1")[1] == ("SourceClip", 48, 400)
    assert _trilha(bin_tl, "INS", "A1")[1] == ("SourceClip", 48, 400)


def test_inserir_recusa_o_que_nao_cabe(bin_tl):
    base = {"tipo": "inserir", "em": "01:00:04:04", "clipe": "TAKE", "duracao_frames": 48}
    casos = [
        ({**base, "imagem_em": "V9"}, "não tem a trilha 'V9'"),
        ({**base, "clipe": "MUDO", "som_em": ["A1"]}, "tem 0 canais"),
        ({**base, "imagem_em": "A1"}, "não é trilha de imagem"),
        ({**base, "in_no_clipe": 480, "imagem_em": "V1"}, "passa do fim"),
        ({**base, "clipe": "TL", "imagem_em": "V1"}, "é uma sequência"),
        ({**base, "clipe": "NAO EXISTE", "imagem_em": "V1"}, "bin_do_clipe"),
    ]
    for op, frase in casos:
        with pytest.raises(TE.TimelineErro, match=frase):
            TE.aplicar(bin_tl, "TL", [op])


def test_clipe_de_OUTRA_bin_leva_o_fecho_oculto(bin_tl, tmp_path):
    """⛔⛔ Subclipe fora da bin derruba o Media Composer ao carregar (banco, 2026-08-30)."""
    outra = tmp_path / "MATERIAL.avb"
    with avb.open() as f:
        _subclipe(f, "DE FORA")
        f.write(str(outra))
    r = TE.aplicar(bin_tl, "TL", [{"tipo": "inserir", "em": "01:00:09:14", "clipe": "DE FORA",
                                   "duracao_frames": 24, "imagem_em": "V1"}],
                   gravar=True, bin_do_clipe=outra)
    assert r["mobs_de_fecho"] == 1
    with avb.open(str(bin_tl)) as f:
        item = next(i for i in f.content.items if i.mob.name == "DE FORA")
        assert not item.user_placed


def test_inserir_ve_a_transicao_que_vem_DEPOIS_do_vazio_na_lista():
    """⛔ MEDIDO na `TL EDITADA`: o vazio que contém o ponto vem antes, na lista, da
    transição que se sobrepõe a ele — e o `break` ao achar o lugar a escondia."""
    f = avb.file.AVBFile()
    seq = T.montar_timeline(f, "TL", [
        T.Entrada(mob_id=FORA, duracao=100, trilhas=IMAGEM),
        T.Entrada(mob_id=FORA, duracao=50, trilhas=(("sound", 1),)),
        T.Entrada(mob_id=FORA, duracao=80, trilhas=IMAGEM),
    ], FPS)
    n = next(i for i, t in enumerate(seq.tracks) if TE.rotulo_da_trilha(t) == "V1")
    comp = seq.tracks[n].component
    lista = list(comp.components)
    trans = f.create.TransitionEffect(FPS, "picture")
    trans.length = 10
    lista.insert(3, trans)                  # entre o vazio (100-150) e o clipe de 80
    comp.components = lista
    with pytest.raises(E.EdicaoRecusada, match="transição"):
        E.inserir(seq, 145, 24)


# ── a ferramenta ─────────────────────────────────────────────────────────────

class _MC:
    """Um Media Composer de mentira que anota o que foi pedido."""

    def __init__(self, raiz: Path, recusar_abrir: bool = False):
        self.raiz, self.recusar, self.chamadas = raiz, recusar_abrir, []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def projeto(self):
        return {"caminho": str(self.raiz), "fps_aprox": FPS}

    def caminho_relativo_da_bin(self, absoluto):
        return str(Path(absoluto).relative_to(self.raiz))

    def _enum(self, metodo, campo, nome):
        return 1

    def _chamar(self, metodo, _timeout=None, **campos):
        self.chamadas.append(metodo)
        if metodo == "OpenBin" and self.recusar:
            self.recusar = False
            raise McApiErro('OpenBin falhou: {"ErrorMessage": "FILE_OPEN_FAILURE"}')


EXTRAIR_B = [{"tipo": "extrair", "de": "01:00:04:04", "ate": "01:00:06:06"}]


def test_editar_fecha_grava_abre_e_carrega_na_record(bin_tl, tmp_path, monkeypatch):
    mc = _MC(tmp_path)
    monkeypatch.setattr(F, "MediaComposer", mc)
    r = F.editar_timeline(bin=str(bin_tl), sequencia="TL", operacoes=EXTRAIR_B, porque="teste")
    assert r["ok"] and r["carregada_na_record"], r
    assert mc.chamadas == ["CloseBin", "OpenBin", "LoadMobsIntoViewer"]
    assert "TL - editada" in {v[0] for v in _mobs(bin_tl).values()}


def test_editar_recusado_nao_fecha_a_bin_do_editor(bin_tl, tmp_path, monkeypatch):
    """⭐ A recusa vem antes do `CloseBin`: não custa ao editor a bin sumindo da tela."""
    mc = _MC(tmp_path)
    monkeypatch.setattr(F, "MediaComposer", mc)
    antes = bin_tl.read_bytes()
    r = F.editar_timeline(bin=str(bin_tl), sequencia="TL", porque="teste", operacoes=[
        {"tipo": "extrair", "de": "01:00:01:00", "ate": "01:00:02:00"}])
    assert "MEIO de um clipe" in r["erro"]
    assert "CloseBin" not in mc.chamadas
    assert bin_tl.read_bytes() == antes


def test_bin_recusada_pelo_MC_volta_byte_a_byte(bin_tl, tmp_path, monkeypatch):
    mc = _MC(tmp_path, recusar_abrir=True)
    monkeypatch.setattr(F, "MediaComposer", mc)
    antes = bin_tl.read_bytes()
    r = F.editar_timeline(bin=str(bin_tl), sequencia="TL", operacoes=EXTRAIR_B, porque="t")
    assert "devolvida exatamente como estava" in r["erro"]
    assert bin_tl.read_bytes() == antes
    assert "LoadMobsIntoViewer" not in mc.chamadas


def test_erro_inesperado_na_gravacao_devolve_a_bin_e_reabre(bin_tl, tmp_path, monkeypatch):
    """⛔ Revisão de 2026-09-13: só três tipos de erro eram tratados. Um erro do pyavb depois
    do `CloseBin` deixava a bin do editor fechada na tela dele."""
    mc = _MC(tmp_path)
    monkeypatch.setattr(F, "MediaComposer", mc)
    antes = bin_tl.read_bytes()
    original = TE.aplicar

    def quebra_ao_gravar(*a, **k):
        if k.get("gravar"):
            bin_tl.write_bytes(b"meio escrito")
            raise KeyError("objeto que o pyavb não conhece")
        return original(*a, **k)

    monkeypatch.setattr(F.TE, "aplicar", quebra_ao_gravar)
    r = F.editar_timeline(bin=str(bin_tl), sequencia="TL", operacoes=EXTRAIR_B, porque="t")
    assert "KeyError" in r["erro"] and "como estava" in r["erro"]
    assert bin_tl.read_bytes() == antes
    assert mc.chamadas == ["CloseBin", "OpenBin"]


def test_copia_de_seguranca_que_falha_reabre_a_bin_sem_editar(bin_tl, tmp_path, monkeypatch):
    mc = _MC(tmp_path)
    monkeypatch.setattr(F, "MediaComposer", mc)

    def disco_cheio(*_a, **_k):
        raise OSError("disco cheio")

    monkeypatch.setattr(F.shutil, "copy2", disco_cheio)
    r = F.editar_timeline(bin=str(bin_tl), sequencia="TL", operacoes=EXTRAIR_B, porque="t")
    assert "cópia de segurança" in r["erro"]
    assert mc.chamadas == ["CloseBin", "OpenBin"]


@pytest.mark.parametrize("frames, rotulo", [
    (0, "00;00;00;00"), (1799, "00;00;59;29"), (1800, "00;01;00;02"),
    (17981, "00;09;59;29"), (17982, "00;10;00;00"), (107892, "01;00;00;00"),
])
def test_drop_frame_29_97_ida_e_volta(frames, rotulo):
    """A conta SMPTE: 2 rótulos pulados por minuto, salvo a cada dez. 01;00;00;00 são
    107.892 quadros, não 108.000 — é essa diferença que desloca uma timeline inteira."""
    assert TE.tc_df(frames, 30) == rotulo
    assert TE.frames_do_tc_df(rotulo, 30) == frames


def test_drop_frame_recusa_rotulo_que_nao_existe_e_taxa_sem_drop():
    with pytest.raises(TE.TimelineErro, match="não existe em drop-frame"):
        TE.frames_do_tc_df("00;01;00;00", 30)
    assert TE.frames_do_tc_df("00;10;00;00", 30) == 17982     # a cada dez não pula
    with pytest.raises(TE.TimelineErro, match="29,97 e 59,94"):
        TE.tc_df(10, 24)
    assert TE.tc_df(215784, 60) == "01;00;00;00"             # 59,94: pula 4


def test_ler_trilha_que_nao_existe_diz_quais_existem(bin_tl):
    with pytest.raises(TE.TimelineErro, match="tem V1, A1"):
        TE.ler(bin_tl, "TL", trilhas=["V9"])


def test_conferir_a_edicao_e_leitura_e_diz_o_motivo(bin_tl):
    from cicloassist.mcp import registro
    assert not registro.FERRAMENTAS["conferir_a_edicao"].escreve
    assert not registro.FERRAMENTAS["ler_timeline"].escreve
    assert registro.FERRAMENTAS["editar_timeline"].escreve
    r = F.conferir_a_edicao(bin=str(bin_tl), sequencia="TL", operacoes=[
        {"tipo": "abrir_espaco", "em": "01:00:01:00", "duracao_frames": 5}])
    assert r["pode"] is False and "MEIO de um clipe" in r["motivo"]


def test_o_editor_le_a_edicao_em_portugues():
    assert vocabulario.resumir("mcp__ciclo__editar_timeline", {
        "sequencia": "C07 v3", "operacoes": [{}, {}]}) == "Edita uma cópia de “C07 v3” — 2 edições"
    assert vocabulario.resumir("mcp__ciclo__ler_timeline", {
        "sequencia": "060a2b340101010501010f1013-000000-69c2b95212968306-c4c504bf1b65-d319"}) \
        == "Lê a timeline"
