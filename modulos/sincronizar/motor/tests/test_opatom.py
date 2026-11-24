"""
O leitor de MXF OP-Atom — a mídia GERENCIADA do Avid.

Este teste tem duas metades, e a divisão é de propósito:

1. **Unitária**, com documentos do `ffprobe` escritos à mão — mas COPIADOS de
   saída real, não inventados. Guarda as regras.
2. **Regressão sobre 540 arquivos REAIS** (`fixtures/opatom_probes.json`), que são
   os probes de uma `Avid MediaFiles` de verdade, enxutos e congelados. Rodam as
   funções PURAS, sem tocar em disco de mídia — então valem no Windows e no Ubuntu
   do pipeline, onde aquele volume não existe. Gerado por
   `tools/opatom_inventario.py --fixture`.

O que estes testes protegem, acima de tudo: **o agrupamento não pode nunca
depender do NOME do arquivo**, e **um TC que mente não pode passar por TC bom**.
As duas coisas foram medidas quebrando em mídia real antes de virarem código.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from media import opatom
from media.opatom import OpAtomClip, group, is_op_atom, parse_probe, timecode_report

FIXTURE = Path(__file__).parent / "fixtures" / "opatom_probes.json"

# A mídia real que gerou a fixture. Quando existe, o teste ao vivo roda; quando não,
# ele é pulado — nunca falha por ausência de disco.
#
# O caminho vem de env var, e NÃO cravado no arquivo: o valor é a pasta `Avid MediaFiles`
# na máquina de quem rodou, e cravá-lo publica o layout do disco do autor num repositório
# público. Mesma regra do `SINC_I18N_DIR` nos testes de painel e do conserto que a
# fixture de `hlsUrl.test.ts` já tinha recebido.
#
#     SINC_MEDIA_OPATOM="/caminho/para/Avid MediaFiles" pytest tests/test_opatom.py
#
# ⚠️ `None` quando a env não vem, e NÃO `Path("")`: o pathlib normaliza a string vazia
# para `Path('.')`, que existe — o `skipif` não dispararia e o teste ao vivo rodaria
# contra o diretório atual.
_MIDIA_ENV = os.environ.get("SINC_MEDIA_OPATOM", "").strip()
MIDIA_REAL = Path(_MIDIA_ENV) if _MIDIA_ENV else None

UL_OP_ATOM = "060e2b34.04010102.0d010201.10030000"


# ── Ajudantes: documentos do ffprobe no formato real ─────────────────────────


def doc(umid, nome, streams, ul=UL_OP_ATOM):
    return {
        "format": {"tags": {
            "material_package_umid": umid,
            "material_package_name": nome,
            "operational_pattern_ul": ul,
        }},
        "streams": streams,
    }


def s_video(file_umid, tc="04:51:48:01", rate="24000/1001", tb="1001/24000", dur_ts=649):
    return {"index": 0, "codec_type": "video", "r_frame_rate": rate,
            "time_base": tb, "duration": "27.068708", "duration_ts": dur_ts,
            "tags": {"file_package_umid": file_umid, "timecode": tc,
                     "reel_name": "A001_03170452_C012"}}


def s_audio(idx, file_umid, tc="04:51:48:01"):
    return {"index": idx, "codec_type": "audio", "sample_rate": "48000",
            "channels": 1, "duration": "27.068708",
            "tags": {"file_package_umid": file_umid, "timecode": tc}}


def s_vazia(idx):
    """Uma track IRMÃ, como o ffprobe a mostra: existe, e está vazia."""
    return {"index": idx, "codec_type": "data"}


# ── O portão: isto é OP-Atom? ────────────────────────────────────────────────


def test_reconhece_os_tres_uls_vistos_no_material():
    """O byte 13 = 0x10 é a família OP-Atom. Os qualificadores variam e NÃO
    entram na decisão — o significado deles ainda é desconhecido."""
    for ul in ("060e2b34.04010102.0d010201.10000000",
               "060e2b34.04010102.0d010201.10020000",
               "060e2b34.04010102.0d010201.10030000"):
        assert is_op_atom(ul), ul


def test_recusa_o_que_nao_e_op_atom():
    assert not is_op_atom("060e2b34.04010101.0d010201.01010900")  # OP1a
    assert not is_op_atom("060e2b34.04010102.0d010201.01020000")  # byte 13 != 0x10
    assert not is_op_atom(None)
    assert not is_op_atom("")
    assert not is_op_atom("lixo")
    assert not is_op_atom("060e2b34.04010102.10030000")  # grupos de menos


def test_arquivo_sem_chave_de_agrupamento_e_recusado_com_motivo():
    """Sem `material_package_umid` não há agrupamento possível — e chutar pelo
    nome seria pior que recusar (a rota por nome cobre ~7% do acervo real)."""
    d = doc("x", "n", [s_video("f1")])
    del d["format"]["tags"]["material_package_umid"]
    motivo = parse_probe(d, "/x/V01.mxf")
    assert isinstance(motivo, str) and "material_package_umid" in motivo


def test_recusa_traz_o_motivo_em_vez_de_sumir_calada():
    d = doc("u1", "n", [s_video("f1")], ul="060e2b34.04010101.0d010201.01010900")
    motivo = parse_probe(d, "/x/V01.mxf")
    assert isinstance(motivo, str) and "OP-Atom" in motivo


# ── A ordem dos canais vem da POSIÇÃO da track, não do nome ──────────────────


def test_indice_da_track_vem_da_posicao_da_essencia():
    """No `V01` a essência está na posição 0; no `A01`, na 1; no `A02`, na 2.
    É daqui que sai a ordem dos canais."""
    v = parse_probe(doc("u1", "CLIPE", [s_video("fv"), s_vazia(1), s_vazia(2)]), "/x/V01.mxf")
    a1 = parse_probe(doc("u1", "CLIPE", [s_vazia(0), s_audio(1, "fa1"), s_vazia(2)]), "/x/A01.mxf")
    a2 = parse_probe(doc("u1", "CLIPE", [s_vazia(0), s_vazia(1), s_audio(2, "fa2")]), "/x/A02.mxf")
    assert (v.kind, v.track_index) == ("video", 0)
    assert (a1.kind, a1.track_index) == ("audio", 1)
    assert (a2.kind, a2.track_index) == ("audio", 2)


def test_ordem_dos_canais_ignora_o_nome_do_arquivo():
    """⭐ A armadilha nº 3 virada em teste. Os nomes aqui ordenam ao CONTRÁRIO das
    tracks: se o agrupador olhasse para o nome, os canais sairiam trocados — e um
    canal trocado num app de sync é o pior lugar possível para esse erro."""
    a2 = parse_probe(doc("u1", "C", [s_vazia(0), s_vazia(1), s_audio(2, "fa2")]), "/x/AAA.mxf")
    a1 = parse_probe(doc("u1", "C", [s_vazia(0), s_audio(1, "fa1"), s_vazia(2)]), "/x/ZZZ.mxf")
    v = parse_probe(doc("u1", "C", [s_video("fv"), s_vazia(1), s_vazia(2)]), "/x/MMM.mxf")

    clipes, _ = group([a2, a1, v])
    assert len(clipes) == 1
    # ZZZ é a track 1 e AAA é a track 2 — a ordem alfabética diria o contrário.
    assert clipes[0].audio == ["/x/ZZZ.mxf", "/x/AAA.mxf"]
    assert clipes[0].video == "/x/MMM.mxf"


def test_agrupa_por_umid_mesmo_com_nomes_de_arquivo_sem_relacao():
    """A nomenclatura real (`A01.<hash>.mxf`) não compartilha nada entre as tracks
    do mesmo clipe. O UMID compartilha."""
    fs = [
        parse_probe(doc("u1", "C", [s_video("fv"), s_vazia(1)]), "/x/V01.E52BE67B_30AF.mxf"),
        parse_probe(doc("u1", "C", [s_vazia(0), s_audio(1, "fa1")]), "/x/A01.E52BE67C_9982.mxf"),
    ]
    clipes, _ = group(fs)
    assert len(clipes) == 1 and len(clipes[0].paths) == 2


def test_nao_funde_clipes_diferentes_que_compartilham_o_nome():
    """Dois imports do MESMO clipe de câmera são DOIS clipes: mesmo nome de bin,
    UMIDs diferentes. Existe no material real (ver a fixture)."""
    fs = [
        parse_probe(doc("u1", "A002_C004", [s_video("fv1")]), "/x/a.mxf"),
        parse_probe(doc("u2", "A002_C004", [s_video("fv2")]), "/y/b.mxf"),
    ]
    clipes, _ = group(fs)
    assert len(clipes) == 2


# ── Duplicatas e tracks de dados ─────────────────────────────────────────────


def test_duplicata_e_descartada_e_reportada():
    """A mesma track copiada noutra pasta numerada. Contá-la duas vezes inflaria
    a contagem de canais do clipe."""
    a = parse_probe(doc("u1", "C", [s_vazia(0), s_audio(1, "MESMA")]), "/1/A01.mxf")
    b = parse_probe(doc("u1", "C", [s_vazia(0), s_audio(1, "MESMA")]), "/2/A01.mxf")
    clipes, dups = group([a, b])
    assert len(clipes) == 1
    assert clipes[0].audio == ["/1/A01.mxf"]
    assert clipes[0].channels_total == 1
    assert dups == ["/2/A01.mxf"]


def test_track_de_dados_entra_como_dado_e_nao_como_essencia():
    """`D01.*` pertence ao clipe mas não é mídia. Fica no inventário e fora de
    qualquer tratamento de essência."""
    d = parse_probe(doc("u1", "C", [s_vazia(0), s_vazia(1)]), "/x/D01.mxf")
    assert d.kind == "data" and d.track_index is None
    clipes, _ = group([d])
    assert clipes[0].data == ["/x/D01.mxf"]
    assert clipes[0].audio == [] and clipes[0].video is None


# ── A taxa de quadros: votação, nunca uma fonte só ───────────────────────────


def test_r_frame_rate_mentindo_pela_metade_nao_ganha():
    """⭐ Medido em mídia real: `r_frame_rate` veio `12000/1001` num clipe de
    23,976. O `avg_frame_rate` e o inverso do `time_base` concordam entre si e
    vencem a votação. Sem isto a timeline sairia com o dobro da duração."""
    v = parse_probe(doc("u1", "C", [{
        "index": 0, "codec_type": "video",
        "r_frame_rate": "12000/1001", "avg_frame_rate": "24000/1001",
        "time_base": "1001/24000", "duration": "65.565500", "duration_ts": 1572,
        "tags": {"file_package_umid": "f"},
    }]), "/x/V01.mxf")
    assert (v.fps_num, v.fps_den) == (24000, 1001)
    assert v.duration_frames == 1572


def test_avg_frame_rate_invalido_nao_atrapalha():
    """No outro acervo o `avg_frame_rate` vem `0/0`; sobram `r_frame_rate` e o
    `time_base`, que concordam."""
    v = parse_probe(doc("u1", "C", [{
        "index": 0, "codec_type": "video",
        "r_frame_rate": "24000/1001", "avg_frame_rate": "0/0",
        "time_base": "1001/24000", "duration": "27.068708", "duration_ts": 649,
        "tags": {"file_package_umid": "f"},
    }]), "/x/V01.mxf")
    assert (v.fps_num, v.fps_den) == (24000, 1001)
    assert v.duration_frames == 649


def test_a_taxa_fica_guardada_como_FRACAO():
    """23,976 arredondado para 24 derivaria ~1,7 s numa timeline de 29 min."""
    v = parse_probe(doc("u1", "C", [s_video("f")]), "/x/V01.mxf")
    assert (v.fps_num, v.fps_den) == (24000, 1001)
    assert v.fps == pytest.approx(23.976, abs=0.001)


# ── O timecode que mente ─────────────────────────────────────────────────────


def clipe_tc(tc, umid="u"):
    return OpAtomClip(umid=umid, name=None, tc_start=tc,
                      tc_is_avid_default=(tc == opatom.AVID_DEFAULT_TC))


def test_todos_no_mesmo_tc_e_suspeito():
    """⭐ A armadilha nº 1. Tomadas diferentes começam em instantes diferentes:
    um relógio de FONTE não repete valor ao frame. Todos iguais = TC do material."""
    clipes = [clipe_tc("01:00:00:00", f"u{i}") for i in range(4)]
    r = timecode_report(clipes)
    assert r["veredicto"] == "suspeito_material"
    assert r["em_padrao_avid"] == 4


def test_tc_variado_e_utilizavel():
    clipes = [clipe_tc(tc, tc) for tc in
              ("02:14:47:09", "02:56:44:17", "03:14:14:17", "03:34:40:08")]
    assert timecode_report(clipes)["veredicto"] == "utilizavel"


def test_conjunto_misto_nao_passa_por_bom():
    """⭐ O caso mais traiçoeiro, e o que me escapou na primeira versão: metade da
    mídia com TC real e metade em `01:00:00:00`. A variação da metade boa faria
    uma checagem ingênua aprovar o conjunto inteiro."""
    clipes = [clipe_tc("02:14:47:09", "a"), clipe_tc("02:56:44:17", "b"),
              clipe_tc("01:00:00:00", "c"), clipe_tc("01:00:00:00", "d")]
    r = timecode_report(clipes)
    assert r["veredicto"] == "misto_suspeito"
    assert r["repetidos"] == ["01:00:00:00"]


def test_zero_repetido_tambem_e_sentinela():
    """`00:00:00:00` é a outra forma de "não sei" com cara de resposta — os
    drones do material real chegam assim."""
    clipes = [clipe_tc("02:14:47:09", "a"), clipe_tc("02:56:44:17", "b"),
              clipe_tc("00:00:00:00", "c"), clipe_tc("00:00:00:00", "d")]
    assert timecode_report(clipes)["veredicto"] == "misto_suspeito"


def test_o_MESMO_material_importado_duas_vezes_nao_e_alarme():
    """⭐ O FALSO POSITIVO que a mídia real revelou. `X` e `X.new.01` convivendo
    na pasta compartilham o TC porque compartilham a FONTE — o relógio está
    certo, o que se repetiu foi o clipe. Acusar isso seria alarme falso sobre
    material bom, e alarme falso é como um aviso deixa de ser lido.

    A repetição continua REPORTADA; só não muda o veredicto."""
    clipes = [clipe_tc("08:12:41:20", "a"), clipe_tc("08:12:41:20", "b"),
              clipe_tc("09:17:25:00", "c"), clipe_tc("02:56:44:17", "d")]
    r = timecode_report(clipes)
    assert r["veredicto"] == "utilizavel"
    assert r["repetidos"] == ["08:12:41:20"]      # a evidência não some
    assert r["sentinelas_repetidos"] == []


def test_sem_tc_e_ausente_e_um_clipe_so_e_indeterminado():
    """Com um clipe só não há variação para observar. Dizer 'utilizável' ali
    seria chute — e o chute é justamente o que este módulo evita."""
    assert timecode_report([clipe_tc(None)])["veredicto"] == "ausente"
    assert timecode_report([clipe_tc("04:51:48:01")])["veredicto"] == "indeterminado"
    assert timecode_report([])["veredicto"] == "ausente"


# ── Regressão sobre 540 arquivos reais ───────────────────────────────────────


@pytest.fixture(scope="module")
def acervo():
    """Os 540 probes reais → clipes. Roda as funções puras, sem tocar em mídia."""
    docs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    arquivos, ignorados = [], []
    for item in docs:
        lido = parse_probe(item["doc"], item["path"])
        (ignorados if isinstance(lido, str) else arquivos).append(lido)
    clipes, dups = group(arquivos)
    return {"docs": docs, "clipes": clipes, "ignorados": ignorados, "dups": dups}


def test_acervo_real_540_arquivos_viram_111_clipes(acervo):
    """O número que abriu esta frente: cobertura TOTAL, sem um arquivo perdido."""
    assert len(acervo["docs"]) == 540
    assert len(acervo["clipes"]) == 111
    assert acervo["ignorados"] == []
    assert acervo["dups"] == ["MXF--/1/HMDQ_01_cpC36.9S3T8CEVG575W.mxf"]


def test_acervo_real_nenhum_arquivo_se_perde_na_contagem(acervo):
    """Todo arquivo lido está em ALGUM clipe. É a checagem que pega um bug de
    agrupamento que 'some' com material em silêncio."""
    em_clipes = sum(len(c.paths) for c in acervo["clipes"])
    assert em_clipes + len(acervo["dups"]) + len(acervo["ignorados"]) == 540


def test_acervo_real_formas_de_clipe(acervo):
    """`clipe = 1 vídeo + N áudios` NÃO é invariante: há clipes de 1, 2, 3, 5 e 10
    tracks (WAV importado de 5 canais, câmera de 4, etc.)."""
    formas: dict[int, int] = {}
    for c in acervo["clipes"]:
        formas[len(c.paths)] = formas.get(len(c.paths), 0) + 1
    assert formas == {1: 6, 2: 3, 3: 49, 5: 30, 10: 23}
    assert sum(1 for c in acervo["clipes"] if not c.has_video) == 29


def test_acervo_real_todo_clipe_com_video_tem_taxa(acervo):
    """Nenhum vídeo sem fps, e nenhuma taxa absurda — é aqui que a mentira do
    `r_frame_rate` apareceria de novo."""
    taxas = set()
    for c in acervo["clipes"]:
        if c.has_video:
            assert c.fps is not None, c.name
            assert 20.0 < c.fps < 61.0, (c.name, c.fps)
            taxas.add((c.fps_num, c.fps_den))
    assert (24000, 1001) in taxas


def test_acervo_real_o_tc_e_denunciado(acervo):
    """O acervo mistura mídia com TC de fonte e mídia em `01:00:00:00`."""
    r = timecode_report(acervo["clipes"])
    assert r["veredicto"] == "misto_suspeito"
    assert r["em_padrao_avid"] == 12
    assert opatom.AVID_DEFAULT_TC in r["repetidos"]


def test_acervo_real_a_rota_por_NOME_DE_ARQUIVO_falharia(acervo):
    """⭐ O contra-exemplo, congelado. Agrupar pelo sufixo de track (`_A01$`) — a
    rota de custo zero que existe no ecossistema — só reconhece 40 dos 540 nomes
    deste acervo, porque a track vem no PREFIXO (`A01.<hash>.mxf`). Este teste
    existe para que ninguém 'otimize' o agrupador de volta para o nome."""
    import re
    sufixo = re.compile(r"(?i)_[AV]\d+$")
    nomes = [Path(d["path"]).stem for d in acervo["docs"]]
    com_sufixo = sum(1 for n in nomes if sufixo.search(n))
    com_prefixo = sum(1 for n in nomes if re.match(r"(?i)^[AV]\d+\.", n))
    assert com_sufixo == 40
    assert com_prefixo == 444
    assert com_sufixo / len(nomes) < 0.10


def test_acervo_real_nomes_de_bin_repetem_entre_clipes_distintos(acervo):
    """Dois imports do mesmo clipe de câmera = dois UMIDs, um nome só. Prova que
    o nome não serve de identidade nem no acervo real."""
    nomes = [c.name for c in acervo["clipes"] if c.name]
    assert len(set(nomes)) < len(nomes)


# ── Ao vivo (pulado quando a mídia não está montada) ─────────────────────────


@pytest.mark.skipif(
    MIDIA_REAL is None or not MIDIA_REAL.exists(),
    reason="defina SINC_MEDIA_OPATOM apontando para a pasta Avid MediaFiles da fixture",
)
def test_ao_vivo_o_scan_bate_com_a_fixture():
    """A ponte entre as duas metades: prova que o `ffprobe` de verdade ainda
    produz o que a fixture congelou. Se a fixture envelhecer, é aqui que aparece."""
    res = opatom.scan([MIDIA_REAL / "MXF-original"])
    assert len(res.clips) == 65
    assert res.ignored == []
    # `misto_suspeito` e não `utilizavel`: 61 clipes têm TC de fonte de verdade,
    # mas os drones (DJI_001/DJI_002) chegam em `00:00:00:00`. O veredicto é do
    # CONJUNTO, e o conjunto realmente não é confiável inteiro.
    r = timecode_report(res.clips)
    assert r["veredicto"] == "misto_suspeito"
    assert r["sentinelas_repetidos"] == ["00:00:00:00"]
