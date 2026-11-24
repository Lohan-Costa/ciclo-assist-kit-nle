"""O merged leva um `TranscriptClip` VAZIO para o `importSequences` do 26.0.2 reconhecer o que o projeto já tem
(2026-11-15: reimportar a PRODA_CORTE.00.2 no `EDITOR SEM MOLDES v04` — sem: 360 → 396 merged; com: 396 → 396)."""

from pathlib import Path

from cicloassist.carta import entrega_prproj as E
from cicloassist.carta import merged_prproj as M
from cicloassist.carta.importar_premiere import transcricao_nos_merged

MODELO = Path(__file__).resolve().parents[1] / "cicloassist" / "carta" / "moldes" / "modelo.prproj"


def _abrir():
    R = E._ler_prproj(str(MODELO))
    return R, {(e.get("ObjectID") or e.get("ObjectUID")): e for e in R}


def test_acha_o_merged_do_modelo():
    R, por = _abrir()
    assert len(M.os_merged(R, por)) == 1


def test_a_forma_e_a_que_o_premiere_grava_para_um_clipe_sem_transcricao():
    R, por = _abrir()
    (_cpi, mc), = M.os_merged(R, por)
    antes = len(mc.find("Clips"))
    novos = M.transcricao_vazia(R, por, mc, M._Ids(R))
    assert [e.tag for e in novos] == ["TranscriptClip", "DataMediaSource"]
    clips = mc.find("Clips")
    assert len(clips) == antes + 1
    ultimo = clips[-1]
    assert ultimo.get("Index") == str(antes) and ultimo.get("ObjectRef") == novos[0].get("ObjectID")
    tc = novos[0]
    assert tc.get("Version") == "2" and tc.find("TranscriptTextSegments") is None     # VAZIO
    fonte = por[tc.find("./DataClip/Clip/Source").get("ObjectRef")]
    media = por[fonte.find("./MediaSource/Media").get("ObjectURef")]
    assert media.tag == "Media"                                                         # uma Media que já existe
    ids = [e.get("ObjectID") for e in R if e.get("ObjectID")]
    assert len(ids) == len(set(ids))


def test_nao_poe_duas_vezes():
    R, por = _abrir()
    (_cpi, mc), = M.os_merged(R, por)
    ids = M._Ids(R)
    assert M.transcricao_vazia(R, por, mc, ids)
    assert M.transcricao_vazia(R, por, mc, ids) == []


def test_so_onde_foi_medida_23_ou_mais_novo():
    assert transcricao_nos_merged("26.0.2")
    assert transcricao_nos_merged("27.1.0")
    assert transcricao_nos_merged("25.6.5")           # medido: sem ela 72 → 108, com ela 108 → 108
    assert transcricao_nos_merged("23.6.0")           # medido: sem ela 72 → 108, com ela 108 → 108
    assert not transcricao_nos_merged("22.6.0")       # ⬜ não medido
    assert not transcricao_nos_merged("")


def test_o_modelo_da_calibragem_e_o_que_o_premiere_abre():
    from cicloassist.carta import moldes_prproj as MO
    assert MO.modelo_para("26.0.2") == MO.MODELO
    assert MO.modelo_para("27.1.0") == MO.MODELO
    assert MO.modelo_para("") == MO.MODELO
    assert MO.modelo_para("25.6.5").name == "modelo 25.prproj"
    assert MO.modelo_para("24.6.0").name == "modelo 23.prproj"      # o 24 abre o do 23
    assert MO.modelo_para("23.6.0").name == "modelo 23.prproj"
    for v in ("23.6.0", "25.6.5", "26.0.2"):
        assert MO.modelo_para(v).is_file()
        R = E._ler_prproj(str(MO.modelo_para(v)))
        assert len(M.os_merged(R, {(e.get("ObjectID") or e.get("ObjectUID")): e for e in R})) == 1


def test_a_copia_do_modelo_aponta_a_midia_onde_ela_esta(tmp_path):
    import re
    import shutil
    from cicloassist.carta import moldes_prproj as MO
    midia = tmp_path / "outro lugar" / "midia & cia"
    shutil.copytree(MO.MIDIA_DO_MODELO, midia, ignore=shutil.ignore_patterns("._*"))
    for v in ("23.6.0", "25.6.5", "26.0.2"):
        original = MO.modelo_para(v).read_bytes()
        destino = tmp_path / f"{v}.prproj"
        r = MO.modelo_no_lugar(MO.modelo_para(v), destino, midia)
        assert MO.modelo_para(v).read_bytes() == original                       # o modelo do app não muda
        assert r["trocados"] >= 34 and r["faltam"] == []                        # câmera + 16 canais, em 2 campos
        R = E._ler_prproj(str(destino))
        caminhos = [e.text for tag in ("FilePath", "ActualMediaFilePath") for e in R.iter(tag)]
        assert caminhos and all(c.startswith(str(midia.resolve())) for c in caminhos)
        assert len(M.os_merged(R, {(e.get("ObjectID") or e.get("ObjectUID")): e for e in R})) == 1


def test_arquivo_que_falta_na_pasta_e_dito_e_nao_trocado(tmp_path):
    from cicloassist.carta import moldes_prproj as MO
    vazia = tmp_path / "vazia"
    vazia.mkdir()
    r = MO.modelo_no_lugar(MO.MODELO, tmp_path / "m.prproj", vazia)
    assert r["trocados"] == 0 and "MOLDE_CAMERA.mov" in r["faltam"]


def test_o_merged_escrito_e_alinhado_e_tem_o_quadro_da_camera():
    """⛔ autor, 2026-11-15: o merged herdava do modelo da calibragem o vídeo em 3,587 s, o som até 0,959 s e o quadro
    320×180 — sobra preta no começo, "3:14" fora de sincronia em todo clipe e o Source a 600 %."""
    R, por = _abrir()
    m = M.molde(R, por)
    soltos = {mc.findtext("Name"): mc for mc in R.iter("MasterClip") if not M._e_componente(mc)
              and mc.findtext("Name", "").startswith("MOLDE_")}
    cam = soltos["MOLDE_CAMERA.mov"]
    for e in M._fecho(cam, por):
        if e.tag == "VideoStream" and e.find("FrameRect") is not None:
            e.find("FrameRect").text = "0,0,1920,1080"          # a câmera de verdade
    canais = [soltos[f"MOLDE_SOM_A{k:02d}.mxf"] for k in range(1, 6)]
    dur = 20 * 10594584000                                       # 20 quadros a 23,976
    r = M.escrever(R, por, m, "TESTE", cam, canais, 0, 0, dur)
    por = {(e.get("ObjectID") or e.get("ObjectUID")): e for e in R}
    mc = next(mc for cpi, mc in M.os_merged(R, por) if mc.findtext("Name") == "TESTE")
    seq = next(por[por[por[c.get("ObjectRef")].find("./Clip/Source").get("ObjectRef")]
                   .find("./SequenceSource/Sequence").get("ObjectURef")]
               for c in mc.findall("./Clips/Clip")
               if por[c.get("ObjectRef")].tag == "VideoClip")
    itens = 0
    for tg in seq.iter("TrackGroup"):
        g = por.get(tg.find("Second").get("ObjectRef"))
        if g is None or g.find("./TrackGroup/Tracks") is None:
            continue
        if g.tag == "VideoTrackGroup":
            assert g.findtext("FrameRect") == "0,0,1920,1080"
        for x in g.find("./TrackGroup/Tracks"):
            for ti in por[x.get("ObjectURef")].findall("./ClipTrack/ClipItems/TrackItems/TrackItem"):
                base = por[ti.get("ObjectRef")].find("./ClipTrackItem/TrackItem")
                assert int(base.findtext("Start") or 0) == 0
                assert int(base.findtext("End")) == dur
                itens += 1
    assert itens == 6                                            # a câmera e os 5 canais
    props = seq.find("./Node/Properties")
    assert props.findtext("MZ.Sequence.PreviewFrameSizeWidth") == "1920"
    assert props.findtext("MZ.WorkOutPoint") == str(dur)


def test_o_merged_escrito_e_cerulean():
    R, por = _abrir()
    m = M.molde(R, por)
    soltos = {mc.findtext("Name"): mc for mc in R.iter("MasterClip") if not M._e_componente(mc)
              and mc.findtext("Name", "").startswith("MOLDE_")}
    M.escrever(R, por, m, "PINTADO", soltos["MOLDE_CAMERA.mov"], [soltos["MOLDE_SOM_A01.mxf"]], 0, 0, 10594584000)
    por = {(e.get("ObjectID") or e.get("ObjectUID")): e for e in R}
    mc = next(mc for _c, mc in M.os_merged(R, por) if mc.findtext("Name") == "PINTADO")
    rotulos = [por[c.get("ObjectRef")].findtext("./Clip/Node/Properties/asl.clip.label.name")
               for c in mc.findall("./Clips/Clip") if por[c.get("ObjectRef")].tag in ("VideoClip", "AudioClip")]
    assert rotulos == ["BE.Prefs.LabelColors.4"] * 2
    cpi = next(c for c, m in M.os_merged(R, por) if m is mc)
    assert cpi.findtext("./ProjectItem/Node/Properties/Column.PropertyText.Label") == "BE.Prefs.LabelColors.4"   # o painel
    comps = [e for e in M._fecho(mc, por) if M._e_componente(e)]
    assert len(comps) == 2 and all(
        por[c.get("ObjectRef")].findtext("./Clip/Node/Properties/asl.clip.label.name") == "BE.Prefs.LabelColors.4"
        for comp in comps for c in comp.findall("./Clips/Clip") if por[c.get("ObjectRef")].tag in ("VideoClip", "AudioClip"))
