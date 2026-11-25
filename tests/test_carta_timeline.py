"""A timeline do editor na Carta Aberta (`carta/timeline.py`) e a entrega ao Premiere (`carta/entrega_premiere.py`).

O caso real é a `PRODA_CORTE.02.Exported.01` da PRODUCAO-A (o desafio do autor, 2026-11-13); aqui, o que dá para
provar sem bin nem Premiere: os rótulos das trilhas OP-Atom, o ganho, o aparo nas transições e o XML.
"""

from __future__ import annotations

import xml.dom.minidom as md

import pytest

from cicloassist.carta import diario, entrega_premiere as E, itens, projeto, referencias, timeline


@pytest.fixture
def proj(tmp_path):
    raiz = tmp_path / "PROJETO X"
    raiz.mkdir()
    return projeto.novo(raiz, "Projeto X", "24000/1001")


@pytest.mark.parametrize("nome, rotulo", [
    ("a001_03170314_C003.mxf", None),          # ⛔ o rolo `a001` no começo NÃO é a trilha A1 (medido: 38 vídeos perdidos)
    ("a001_03170314_C003_A01.mxf", "A1"),
    ("a001_03170314_C003_A02.mxf", "A2"),
    ("B01A01.E69C4A2B.mxf", "A1"),             # o nome que o Media Composer dá
    ("X.V01.3F2A_1B.mxf", "V1"),
    ("C11 P1-T002_A03.mxf", "A3"),
])
def test_rotulo_da_trilha_op_atom_so_pelo_sufixo(nome, rotulo):
    assert E._rotulo_da_trilha(nome) == rotulo


def test_ganho_do_avid_em_db():
    assert timeline.ganho_db(1 << 29) == 0.0
    assert timeline.ganho_db(850883053) == pytest.approx(4.0, abs=0.01)
    assert timeline.ganho_db(0) is None and timeline.ganho_db(None) is None


def test_aparar_nas_transicoes_poe_os_dois_no_ponto_de_corte():
    # o Avid: A vai até o fim da transição, B começa no início dela (sobrepostos); o corte a 10 quadros do início
    a = {"midia": "a", "inicio_q": 0, "entrada_q": 100, "fim_q": 140}
    b = {"midia": "b", "inicio_q": 100, "entrada_q": 500, "fim_q": 200}
    t = {"inicio_q": 100, "fim_q": 140, "corte_q": 110, "efeito": "EFF2_BLEND_DISSOLVE"}
    (a2, b2), avisos = E.aparar_nas_transicoes([a, b], [t])
    assert avisos == []
    assert a2["fim_q"] == 110 and a2["entrada_q"] == 100                 # A acaba no corte
    assert b2["inicio_q"] == 110 and b2["entrada_q"] == 510              # B começa no corte, 10 quadros adiante na fonte
    assert b2["fim_q"] == 200                                             # ⛔ o fim de B não muda
    assert a["fim_q"] == 140                                              # o item da Carta não é tocado


def test_fade_do_vazio_vai_como_esta_e_dito():
    b = {"midia": "b", "inicio_q": 100, "entrada_q": 0, "fim_q": 200}
    (b2,), avisos = E.aparar_nas_transicoes([b], [{"inicio_q": 100, "fim_q": 120, "corte_q": 110, "efeito": "x"}])
    assert b2["inicio_q"] == 110 and avisos and "sem clipe de saída" in avisos[0]


def _ref_com_op_atom(proj, tmp_path, nome, tipo="video"):
    (proj.raiz / "D").mkdir(exist_ok=True)
    _, r = referencias.criar(proj, "D", nome, {"nome_da_fonte": nome, "tipo": tipo, "quadros": 1000,
                                               "tc": "01:00:00:00"}, {"nle": "avid"})
    arquivos = []
    for suf in ("", "_A01", "_A02"):
        f = tmp_path / f"{nome}{suf}.mxf"
        f.write_bytes(b"x")
        arquivos.append(str(f))
    diario.acrescentar(proj, {"fato": "forma", "midia": r["id"], "forma": "avid", **referencias.onde(arquivos[0]),
                              "arquivos": arquivos, "por": "teste", "medida": None})
    return r


def test_xml_da_timeline_aponta_a_op_atom_e_conta_o_que_ficou_de_fora(proj, tmp_path, monkeypatch):
    monkeypatch.setattr(E, "_dimensoes", lambda _a: (1920, 1080))
    monkeypatch.setattr(E, "_rotulo_pela_sonda", lambda a: "V1")
    cam = _ref_com_op_atom(proj, tmp_path, "a001_03170314_C003")
    _, offline = referencias.criar(proj, "D", "SFX", {"nome_da_fonte": "SFX", "tipo": "audio"}, {})
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 86400, "duracao_q": 300,
            "trilhas": [
                {"tipo": "V", "k": 1, "transicoes": [], "sem_clipe": [{"inicio_q": 0, "fim_q": 10, "efeitos": [
                    {"nome": "Titler", "rotulo": "Título"}]}],
                 "clipes": [{"midia": cam["id"], "inicio_q": 0, "entrada_q": 100, "fim_q": 200,
                             "efeitos": [{"nome": "EFF2_RGB_COLOR_CORRECTION", "categoria": "color", "rotulo": "CC"}]}]},
                {"tipo": "A", "k": 1, "transicoes": [], "sem_clipe": [],
                 "clipes": [{"midia": cam["id"], "inicio_q": 0, "entrada_q": 100, "fim_q": 200, "canal": 2,
                             "ganho_db": -6.0, "desligado": True},
                            {"midia": offline["id"], "inicio_q": 200, "entrada_q": 0, "fim_q": 250, "canal": 1}]}]}
    xml, rel = E.xml_da_timeline(proj, item)
    md.parseString(xml.encode())                                          # bem formado
    assert "a001_03170314_C003.mxf</name>" in xml                        # a imagem: o arquivo sem sufixo
    assert "a001_03170314_C003_A02.mxf" in xml                           # o canal 2 do som: o _A02
    assert "<enabled>FALSE</enabled>" in xml                             # o clipe desligado continua lá, desligado
    assert "<value>0.50119</value>" in xml                               # −6 dB
    assert "<string>01:00:00:00</string>" in xml
    assert rel["clipes"] == 2 and rel["offline"] == {"SFX": 1}
    assert rel["efeitos_fora"] == {"CC": 1, "Título (sem clipe, V1)": 1}
    assert rel["formas"] == {"avid": 2}


def test_so_timeline_se_entrega(proj):
    with pytest.raises(projeto.CartaErro):
        E.xml_da_timeline(proj, {"tipo": "sequencia", "trilhas": []})


def test_timeline_troca_as_chaves_de_master_pelos_ids():
    item = {"tipo": "sequencia", "timeline": True, "trilhas": [
        {"tipo": "V", "k": 1, "clipes": [{"midia": "m1", "inicio_q": 0, "entrada_q": 0, "fim_q": 1}],
         "transicoes": [], "sem_clipe": []}]}
    out = itens._trocar_chaves(item, {"m1": "id-1"})
    assert out["trilhas"][0]["clipes"][0]["midia"] == "id-1"
    assert itens.partes(out) == [("midia", "id-1")]


# ── o enxerto (`carta/entrega_prproj.py`): a V1 escrita no .prproj do Premiere ─────────────────────────────────────

_MOLDE = """<?xml version="1.0" encoding="UTF-8" ?>
<PremiereData Version="3">
<Project ObjectRef="1"/>
<Project ObjectID="1" Version="45"><RootProjectItem ObjectURef="r"/></Project>
<RootProjectItem ObjectUID="r"><Items><Item ObjectURef="cpi"/></Items></RootProjectItem>
<ClipProjectItem ObjectUID="cpi"><MasterClip ObjectURef="mc"/></ClipProjectItem>
<MasterClip ObjectUID="mc"><Clips><Clip Index="0" ObjectRef="10"/></Clips><Name>CAM</Name></MasterClip>
<VideoClip ObjectID="10"><Clip><Markers ObjectRef="11"/><Source ObjectRef="12"/><InPoint>0</InPoint><OutPoint>99</OutPoint><ClipID>x</ClipID></Clip></VideoClip>
<Markers ObjectID="11"/>
<VideoMediaSource ObjectID="12"><MediaSource><Media ObjectURef="med"/></MediaSource></VideoMediaSource>
<Media ObjectUID="med"><VideoStream ObjectRef="13"/><FilePath>ARQ</FilePath></Media>
<VideoStream ObjectID="13"><FrameRect>0,0,1920,1080</FrameRect></VideoStream>
<Sequence ObjectUID="seq"><Node><Properties><MZ.WorkOutPoint>0</MZ.WorkOutPoint></Properties></Node>
 <TrackGroups><TrackGroup Index="0"><Second ObjectRef="20"/></TrackGroup></TrackGroups><Name>MOLDE</Name></Sequence>
<VideoTrackGroup ObjectID="20"><TrackGroup><Tracks><Track Index="0" ObjectURef="t1"/></Tracks></TrackGroup><FrameRect>0,0,2048,1080</FrameRect></VideoTrackGroup>
<VideoClipTrack ObjectUID="t1"><ClipTrack><ClipItems><TrackItems><TrackItem Index="0" ObjectRef="30"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
<VideoClipTrackItem ObjectID="30"><ClipTrackItem><ComponentOwner><Components ObjectRef="31"/></ComponentOwner><TrackItem><End>5</End></TrackItem><SubClip ObjectRef="32"/></ClipTrackItem><FrameRect>0,0,2048,1080</FrameRect></VideoClipTrackItem>
<VideoComponentChain ObjectID="31"/>
<SubClip ObjectID="32"><Clip ObjectRef="33"/><MasterClip ObjectURef="mc"/></SubClip>
<VideoClip ObjectID="33"><Clip><Source ObjectRef="12"/><InPoint>0</InPoint><OutPoint>5</OutPoint></Clip></VideoClip>
</PremiereData>"""


def test_enxerto_escreve_a_v1_em_ticks_e_deixa_de_fora_o_que_nao_sabe(proj, tmp_path):
    from cicloassist.carta import entrega_prproj as EP
    cam = _ref_com_op_atom(proj, tmp_path, "a001_C003")
    arq = str(tmp_path / "a001_C003.mxf")
    molde = tmp_path / "entrega v01.prproj"
    EP._gravar_prproj(EP.ET.fromstring(_MOLDE.replace("ARQ", arq).split("?>", 1)[1]), str(molde))
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 86400, "trilhas": [
        {"tipo": "V", "k": 1, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": cam["id"], "inicio_q": 0, "entrada_q": 24, "fim_q": 48},
            {"midia": cam["id"], "inicio_q": 60, "entrada_q": 0, "fim_q": 70, "velocidade": {"tipo": "variable", "classe": "creative"}}]}]}
    saida = str(tmp_path / "entrega v02.prproj")
    rel = EP.escrever_trilhas_de_video(proj, item, str(molde), saida, "MOLDE", "CORTE", {"V1"}, quadro=(1920, 1080))
    assert rel["clipes"] == 1 and rel["fora"] == {"velocidade variável (variable) (V1)": 1}
    R = EP._ler_prproj(saida)
    tis = [e for e in R if e.tag == "VideoClipTrackItem"]
    assert len(tis) == 1                                                  # o clipe do molde saiu
    tpf = 10594584000
    assert tis[0].findtext("./ClipTrackItem/TrackItem/Start") is None    # ⛔ o Start some quando é 0
    assert tis[0].findtext("./ClipTrackItem/TrackItem/End") == str(48 * tpf)
    vcs = [e for e in R if e.tag == "VideoClip" and e.findtext("./Clip/InPoint") == str(24 * tpf)]
    assert vcs and vcs[0].findtext("./Clip/OutPoint") == str((24 + 48) * tpf)  # do início da MÍDIA
    seq = next(e for e in R if e.tag == "Sequence")
    assert seq.findtext("Name") == "CORTE" and seq.findtext("./Node/Properties/MZ.ZeroPoint") == str(86400 * tpf)
    assert next(e for e in R if e.tag == "VideoTrackGroup").findtext("FrameRect") == "0,0,1920,1080"
    with pytest.raises(projeto.CartaErro):
        EP.escrever_trilhas_de_video(proj, item, str(molde), str(molde), "MOLDE", "X")


_MOLDE_SOM = _MOLDE.replace("</PremiereData>", """
<ClipProjectItem ObjectUID="cpa"><MasterClip ObjectURef="mca"/></ClipProjectItem>
<MasterClip ObjectUID="mca"><Clips><Clip Index="0" ObjectRef="40"/></Clips><Name>SOM</Name></MasterClip>
<AudioClip ObjectID="40"><Clip><Markers ObjectRef="11"/><Source ObjectRef="41"/><InPoint>0</InPoint><OutPoint>99</OutPoint><ClipID>y</ClipID><InUse>false</InUse></Clip><SecondaryContents><SecondaryContentItem Index="0" ObjectRef="42"/></SecondaryContents><AudioChannelLayout>[{"channellabel":0}]</AudioChannelLayout></AudioClip>
<AudioMediaSource ObjectID="41"><MediaSource><Media ObjectURef="meda"/></MediaSource></AudioMediaSource>
<Media ObjectUID="meda"><FilePath>ARQA</FilePath></Media>
<SecondaryContent ObjectID="42"><Content ObjectRef="41"/><ChannelIndex>0</ChannelIndex></SecondaryContent>
<ClipProjectItem ObjectUID="cpw"><MasterClip ObjectURef="mcw"/></ClipProjectItem>
<MasterClip ObjectUID="mcw"><Clips><Clip Index="0" ObjectRef="50"/></Clips><Name>SFX.wav</Name></MasterClip>
<AudioClip ObjectID="50"><Clip><Source ObjectRef="51"/><InPoint>0</InPoint><OutPoint>99</OutPoint><ClipID>w</ClipID></Clip><SecondaryContents><SecondaryContentItem Index="0" ObjectRef="52"/><SecondaryContentItem Index="1" ObjectRef="53"/></SecondaryContents><AudioChannelLayout>[{"channellabel":100},{"channellabel":101}]</AudioChannelLayout></AudioClip>
<AudioMediaSource ObjectID="51"><MediaSource><Media ObjectURef="medw"/></MediaSource></AudioMediaSource>
<Media ObjectUID="medw"><FilePath>WAV</FilePath></Media>
<SecondaryContent ObjectID="52"><Content ObjectRef="51"/><ChannelIndex>0</ChannelIndex></SecondaryContent>
<SecondaryContent ObjectID="53"><Content ObjectRef="51"/><ChannelIndex>1</ChannelIndex></SecondaryContent>
<AudioTrackGroup ObjectID="21"><TrackGroup><Tracks><Track Index="0" ObjectURef="ta1"/></Tracks><NextTrackID>3</NextTrackID></TrackGroup></AudioTrackGroup>
<AudioClipTrack ObjectUID="ta1"><ClipTrack><Track><ID>2</ID><Index>0</Index></Track><ClipItems><TrackItems><TrackItem Index="0" ObjectRef="60"/><TrackItem Index="1" ObjectRef="61"/></TrackItems><Index>0</Index></ClipItems></ClipTrack><AudioTrack><ComponentOwner><Components ObjectRef="70"/></ComponentOwner><ID>g</ID></AudioTrack></AudioClipTrack>
<AudioComponentChain ObjectID="70"><ComponentChain><Components><Component Index="0" ObjectRef="71"/></Components></ComponentChain></AudioComponentChain>
<AudioFader ObjectID="71"/>
<AudioClipTrackItem ObjectID="60"><ClipTrackItem><ComponentOwner><Components ObjectRef="62"/></ComponentOwner><TrackItem><End>5</End></TrackItem><SubClip ObjectRef="63"/></ClipTrackItem><ID>i60</ID></AudioClipTrackItem>
<AudioComponentChain ObjectID="62"><DefaultVol>true</DefaultVol></AudioComponentChain>
<SubClip ObjectID="63"><Clip ObjectRef="64"/><MasterClip ObjectURef="mca"/></SubClip>
<AudioClip ObjectID="64"><Clip><Source ObjectRef="41"/></Clip><AudioChannelLayout>[{"channellabel":0}]</AudioChannelLayout></AudioClip>
<AudioClipTrackItem ObjectID="61"><ClipTrackItem><ComponentOwner><Components ObjectRef="65"/></ComponentOwner><TrackItem><Start>5</Start><End>9</End></TrackItem><SubClip ObjectRef="69"/></ClipTrackItem><ID>i61</ID></AudioClipTrackItem>
<AudioComponentChain ObjectID="65"><ComponentChain><Components><Component Index="0" ObjectRef="66"/></Components></ComponentChain></AudioComponentChain>
<AudioFilterComponent ObjectID="66"><AudioComponent><Component><Params><Param Index="0" ObjectRef="67"/><Param Index="1" ObjectRef="68"/></Params></Component></AudioComponent><FilterMatchName>Internal Volume Mono</FilterMatchName></AudioFilterComponent>
<AudioComponentParam ObjectID="67"><Name>Silenciado</Name></AudioComponentParam>
<AudioComponentParam ObjectID="68"><StartKeyframe>-91445760000000000,0.5,0,0</StartKeyframe><CurrentValue>0.5</CurrentValue><UnitsString>dB</UnitsString></AudioComponentParam>
<SubClip ObjectID="69"><Clip ObjectRef="59"/><MasterClip ObjectURef="mca"/></SubClip>
<AudioClip ObjectID="59"><Clip><Source ObjectRef="41"/></Clip><AudioChannelLayout>[{"channellabel":0}]</AudioChannelLayout></AudioClip>
</PremiereData>""").replace('<TrackGroup Index="0"><Second ObjectRef="20"/></TrackGroup>',
                            '<TrackGroup Index="0"><Second ObjectRef="20"/></TrackGroup><TrackGroup Index="1"><Second ObjectRef="21"/></TrackGroup>')


def test_enxerto_escreve_o_som_no_canal_certo_com_o_ganho(proj, tmp_path):
    """O som do molde do Premiere (2026-11-14): o canal do OP-Atom é o ARQUIVO (_A02), o do WAV estéreo é o
    ChannelIndex dentro da fonte; o ganho vira o Nível cru 10^((dB−15)/20); trilha que falta é clonada."""
    from cicloassist.carta import entrega_prproj as EP
    cam = _ref_com_op_atom(proj, tmp_path, "S01_T002")
    wav = tmp_path / "SFX.wav"
    wav.write_bytes(b"x")
    _, sfx = referencias.criar(proj, "D", "SFX", {"nome_da_fonte": "SFX", "tipo": "audio"}, {})
    diario.acrescentar(proj, {"fato": "forma", "midia": sfx["id"], "forma": "original", **referencias.onde(str(wav)),
                              "por": "teste", "medida": None})
    molde = tmp_path / "entrega v01.prproj"
    xml = (_MOLDE_SOM.replace("ARQA", str(tmp_path / "S01_T002_A02.mxf")).replace("WAV", str(wav))
           .replace("ARQ", str(tmp_path / "S01_T002.mxf")))
    EP._gravar_prproj(EP.ET.fromstring(xml.split("?>", 1)[1]), str(molde))
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 0, "trilhas": [
        {"tipo": "A", "k": 1, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": cam["id"], "inicio_q": 0, "entrada_q": 10, "fim_q": 20, "canal": 2, "ganho_db": 4.0}]},
        {"tipo": "A", "k": 2, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": sfx["id"], "inicio_q": 30, "entrada_q": 0, "fim_q": 40, "canal": 2}]}]}
    saida = str(tmp_path / "entrega v02.prproj")
    rel = EP.escrever_timeline(proj, item, str(molde), saida, "MOLDE", "CORTE", {"A1", "A2"})
    assert rel["clipes"] == 2 and rel["trilhas_criadas"] == 1 and not rel["fora"] and not rel["sem_item"]
    R = EP._ler_prproj(saida)
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    atg = next(e for e in R if e.tag == "AudioTrackGroup")
    trs = [por[t.get("ObjectURef")] for t in atg.find("./TrackGroup/Tracks")]
    assert len(trs) == 2 and atg.findtext("./TrackGroup/NextTrackID") == "4"
    tpf = 10594584000

    def cadeia_do(tr):
        ti = por[tr.find("./ClipTrack/ClipItems/TrackItems/TrackItem").get("ObjectRef")]
        sub = por[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")]
        return ti, por[ti.find("./ClipTrackItem/ComponentOwner/Components").get("ObjectRef")], sub, por[sub.find("Clip").get("ObjectRef")]

    ti, ch, sub, ac = cadeia_do(trs[0])
    assert sub.find("MasterClip").get("ObjectURef") == "mca"                 # o item do arquivo _A02 (o canal 2)
    assert ac.findtext("./Clip/InPoint") == str(10 * tpf) and ac.find("./Clip/InUse") is None
    fc = por[ch.find("./ComponentChain/Components/Component").get("ObjectRef")]
    nivel = por[fc.findall("./AudioComponent/Component/Params/Param")[1].get("ObjectRef")]
    assert float(nivel.findtext("CurrentValue")) == pytest.approx(10 ** ((4 - 15) / 20))
    assert nivel.findtext("StartKeyframe").split(",")[1] == nivel.findtext("CurrentValue")
    ti, ch, sub, ac = cadeia_do(trs[1])
    assert sub.find("MasterClip").get("ObjectURef") == "mcw" and ch.findtext("DefaultVol") == "true"
    assert ti.findtext("./ClipTrackItem/TrackItem/Start") == str(30 * tpf)
    scs = ac.findall("./SecondaryContents/SecondaryContentItem")
    assert len(scs) == 1 and por[scs[0].get("ObjectRef")].findtext("ChannelIndex") == "1"   # o canal 2 do WAV
    assert ac.findtext("AudioChannelLayout") == '[{"channellabel":0}]'
    assert not any(e.tag == "AudioClipTrackItem" and EP._chave(e) in ("60", "61") for e in R)   # os do molde saíram


def test_enxerto_poe_o_plano_sem_midia_como_offline_no_lugar(proj, tmp_path):
    """O plano sem arquivo NESTA máquina não some (autor, 2026-11-25): entra como o item do "Arquivo offline" do
    Premiere (`prproj.offline`, medido no 26.0.2), com o nome do ORIGINAL (o da bin, com a extensão; o som sem
    extensão ganha `.wav`), o TC (o do som na taxa da timeline) e o canal certo; o editor religa no Premiere."""
    from cicloassist.carta import entrega_prproj as EP
    cam = _ref_com_op_atom(proj, tmp_path, "S01_T002")
    _, plano = referencias.criar(proj, "D", "B001_C021", {"nome_da_fonte": "B001_C021", "tipo": "video",
                                 "fps": "24000/1001", "quadros": 500, "tc": "01:00:00:00"},
                                 {"nle": "avid", "offline": True, "caminho_na_bin": "/Volumes/V-001/B001_C021.braw"})
    _, sfx = referencias.criar(proj, "D", "PATAO DRONE", {"nome_da_fonte": "PATAO DRONE", "tipo": "audio", "fps": "24",
                               "quadros": 100, "tc": "06:14:11:13", "canais_de_som": [2]}, {"nle": "avid", "offline": True})
    molde = tmp_path / "entrega v01.prproj"
    xml = (_MOLDE_SOM.replace("ARQA", str(tmp_path / "S01_T002_A01.mxf")).replace("WAV", str(tmp_path / "x.wav"))
           .replace("ARQ", str(tmp_path / "S01_T002.mxf")))
    EP._gravar_prproj(EP.ET.fromstring(xml.split("?>", 1)[1]), str(molde))
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 0, "trilhas": [
        {"tipo": "V", "k": 1, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": cam["id"], "inicio_q": 0, "entrada_q": 0, "fim_q": 10},
            {"midia": plano["id"], "inicio_q": 10, "entrada_q": 24, "fim_q": 34}]},
        {"tipo": "A", "k": 1, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": sfx["id"], "inicio_q": 10, "entrada_q": 5, "fim_q": 30, "canal": 2}]}]}
    saida = str(tmp_path / "entrega v02.prproj")
    rel = EP.escrever_timeline(proj, item, str(molde), saida, "MOLDE", "CORTE")
    assert rel["clipes"] == 3 and rel["offline_no_lugar"] == 2 and rel["offline"] == 0 and not rel["sem_item"]
    assert rel["itens_offline"] == ["B001_C021.braw", "PATAO DRONE.wav"]
    R = EP._ler_prproj(saida)
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    tpf = 10594584000
    meds = {e.findtext("Title"): e for e in R if e.tag == "Media" and e.findtext("OfflineReason") == "5"}
    assert set(meds) == {"B001_C021.braw", "PATAO DRONE.wav"}
    assert meds["B001_C021.braw"].findtext("Start") == str(86400 * tpf)              # 01:00:00:00 a 23,976
    assert meds["PATAO DRONE.wav"].findtext("Start") == str(((6 * 60 + 14) * 60 + 11) * 24 * tpf + 13 * tpf)
    assert meds["PATAO DRONE.wav"].find("VideoStream") is None                        # só de som
    raiz = next(e for e in R if e.tag == "RootProjectItem")
    na_raiz = {i.get("ObjectURef") for i in raiz.iter("Item")}
    off = {k: v for k, v in EP.midia_do_projeto(R).items() if k.startswith(EP.CHAVE_OFFLINE)}
    assert len(off) == 2 and all(k[len(EP.CHAVE_OFFLINE):] in na_raiz for k in off)    # os dois na bin raiz

    def da_trilha(grupo, inicio):
        g = next(e for e in R if e.tag == grupo)
        tr = por[g.find("./TrackGroup/Tracks/Track").get("ObjectURef")]
        for x in tr.findall("./ClipTrack/ClipItems/TrackItems/TrackItem"):
            ti = por[x.get("ObjectRef")]
            if (ti.findtext("./ClipTrackItem/TrackItem/Start") or "0") == str(inicio * tpf):
                sub = por[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")]
                return sub, por[sub.find("Clip").get("ObjectRef")]
        raise AssertionError(f"nada em {inicio}")

    sub, vc = da_trilha("VideoTrackGroup", 10)
    assert por[sub.find("MasterClip").get("ObjectURef")].findtext("Name") == "B001_C021.braw"
    assert vc.findtext("./Clip/InPoint") == str(24 * tpf)
    sub, ac = da_trilha("AudioTrackGroup", 10)
    assert por[sub.find("MasterClip").get("ObjectURef")].findtext("Name") == "PATAO DRONE.wav"
    scs = ac.findall("./SecondaryContents/SecondaryContentItem")
    assert len(scs) == 1 and por[scs[0].get("ObjectRef")].findtext("ChannelIndex") == "1"   # o canal 2
    ids = [int(e.get("ObjectID")) for e in R if e.get("ObjectID")]
    assert len(ids) == len(set(ids))                                                  # nenhum ObjectID repetido
    # sem o offline (o caminho de antes): os dois ficam de fora, contados
    rel2 = EP.escrever_timeline(proj, item, str(molde), str(tmp_path / "v03.prproj"), "MOLDE", "CORTE", com_offline=False)
    assert rel2["clipes"] == 1 and rel2["offline"] == 2 and rel2["offline_no_lugar"] == 0


def test_offline_de_som_direto_polifonico_leva_cada_canal_ao_seu(proj, tmp_path):
    """Som direto de 5 canais sem arquivo aqui (autor, 2026-11-25: "muitos sons diretos têm mais canais"): o item offline
    tem 5 canais MONO, cada um com a sua mídia (`StreamNumber`), como o 26.0.2 guarda o WAV polifônico importado; o
    clipe do canal N aponta o clipe de som N do item. O nome quebrado pela bin (UTF-8 lido como Latin-1) volta certo."""
    from cicloassist.carta import entrega_prproj as EP
    cam = _ref_com_op_atom(proj, tmp_path, "S01_T002")
    _, sd = referencias.criar(proj, "D", "C4 P1-T001", {"nome_da_fonte": "C4 P1-T001", "tipo": "audio", "fps": "24000/1001",
                              "quadros": 2000, "tc": "10:16:52:00", "canais_de_som": [5]},
                              {"nle": "avid", "offline": True, "caminho_na_bin": "/Volumes/SOM/PAT\u00c3\u0083O C4 P1-T001.WAV"})
    molde = tmp_path / "entrega v01.prproj"
    xml = (_MOLDE_SOM.replace("ARQA", str(tmp_path / "S01_T002_A01.mxf")).replace("WAV", str(tmp_path / "x.wav"))
           .replace("ARQ", str(tmp_path / "S01_T002.mxf")))
    EP._gravar_prproj(EP.ET.fromstring(xml.split("?>", 1)[1]), str(molde))
    som = lambda k, canal: {"tipo": "A", "k": k, "transicoes": [], "sem_clipe": [], "clipes": [  # noqa: E731
        {"midia": sd["id"], "inicio_q": 0, "entrada_q": 100, "fim_q": 50, "canal": canal}]}
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 0, "trilhas": [
        {"tipo": "V", "k": 1, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": cam["id"], "inicio_q": 0, "entrada_q": 0, "fim_q": 50}]}, som(1, 1), som(2, 3), som(3, 5)]}
    saida = str(tmp_path / "entrega v02.prproj")
    rel = EP.escrever_timeline(proj, item, str(molde), saida, "MOLDE", "CORTE")
    assert rel["offline_no_lugar"] == 3 and rel["offline"] == 0 and not rel["fora"], rel["fora"]
    assert rel["itens_offline"] == ["PATÃO C4 P1-T001.WAV"]
    R = EP._ler_prproj(saida)
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    meds = [e for e in R if e.tag == "Media" and e.findtext("OfflineReason") == "5"]
    assert len(meds) == 5 and sorted(e.findtext("StreamNumber") or "0" for e in meds) == ["0", "1", "2", "3", "4"]
    off = next(v for k, v in EP.midia_do_projeto(R).items() if k.startswith(EP.CHAVE_OFFLINE))
    assert EP.canais_do_item(off) == 5
    atg = next(e for e in R if e.tag == "AudioTrackGroup")
    fluxos = []
    for t in atg.find("./TrackGroup/Tracks"):
        tr = por[t.get("ObjectURef")]
        ti = por[tr.find("./ClipTrack/ClipItems/TrackItems/TrackItem").get("ObjectRef")]
        ac = por[por[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")].find("Clip").get("ObjectRef")]
        med = por[por[ac.find("./Clip/Source").get("ObjectRef")].find("./MediaSource/Media").get("ObjectURef")]
        fluxos.append(med.findtext("StreamNumber") or "0")
    assert fluxos == ["0", "2", "4"]                       # os canais 1, 3 e 5
    ids = [int(e.get("ObjectID")) for e in R if e.get("ObjectID")]
    assert len(ids) == len(set(ids))


def test_offline_so_e_estereo_com_a_certeza_de_uma_trilha_de_2_canais(proj, tmp_path):
    """⛔ Medido no 26.0.2 (`spikes/offline_premiere_matriz.py`, 2026-11-25): o offline ESTÉREO religado a um arquivo de
    mais canais deixa o canal 2 MUDO; em N mono religa certo. Sem saber os canais (a referência do Avid), 2 = 2 MONO."""
    from cicloassist.carta import entrega_prproj as EP
    (proj.raiz / "D").mkdir(exist_ok=True)
    _, sem = referencias.criar(proj, "D", "SD", {"nome_da_fonte": "SD.WAV", "tipo": "audio", "fps": "25", "quadros": 100}, {})
    _, est = referencias.criar(proj, "D", "MUS", {"nome_da_fonte": "MUS.wav", "tipo": "audio", "fps": "25", "quadros": 100,
                                                  "canais_de_som": [2]}, {})
    _, duo = referencias.criar(proj, "D", "DUO", {"nome_da_fonte": "DUO.mov", "tipo": "audio", "fps": "25", "quadros": 100,
                                                  "canais_de_som": [1, 1]}, {})
    item = {"fps": "25"}
    clipes = [({"midia": m["id"], "inicio_q": 0, "entrada_q": 0, "fim_q": 10, "canal": 2}, True) for m in (sem, est, duo)]
    a = EP.itens_offline(proj, item, clipes, None)
    assert [a[m["id"]]["mono"] for m in (sem, est, duo)] == [True, False, True]
    off = EP._modulo_offline()
    xml, _, _ = off.item(**a[sem["id"]], proximo_id=10)
    r = EP.ET.fromstring(f"<r>{xml}</r>")
    assert sorted(e.findtext("StreamNumber") or "0" for e in r if e.tag == "Media") == ["0", "1"]   # 2 mono
    xml, _, _ = off.item(**a[est["id"]], proximo_id=10)
    assert sum(1 for e in EP.ET.fromstring(f"<r>{xml}</r>") if e.tag == "Media") == 1                # estéreo


def test_canal_do_wav_polifonico_online_e_o_clipe_do_canal():
    """⛔ O defeito antigo: no item de N clipes mono (WAV polifônico importado) o canal 3 tocava o canal 1."""
    from cicloassist.carta import entrega_prproj as EP
    info = {"audio": [("mc", f"ac{k}", k, 1) for k in range(5)]}
    assert EP.canais_do_item(info) == 5 and EP.clipe_de_som_do_canal(info, 3)[1] == "ac2"
    estereo = {"audio": [("mc", "ac0", 0, 2)]}
    assert EP.canais_do_item(estereo) == 2 and EP.clipe_de_som_do_canal(estereo, 2)[1] == "ac0"


_MOLDE_TR = _MOLDE_SOM.replace("</PremiereData>", """
<AudioTransitionTrackItem ObjectID="80"><TransitionTrackItem><TrackItem><Start>3</Start><End>7</End></TrackItem><Alignment>2</Alignment><DisplayName>Potência constante</DisplayName><MatchName>Constant Power</MatchName><HasOutgoingClip>true</HasOutgoingClip><HasIncomingClip>true</HasIncomingClip></TransitionTrackItem><AudioChannelLayout>[{"channellabel":100},{"channellabel":101}]</AudioChannelLayout></AudioTransitionTrackItem>
</PremiereData>""").replace("<Index>0</Index></ClipItems></ClipTrack>",
                            '<Index>0</Index></ClipItems><TransitionItems><TrackItems><TrackItem Index="0" ObjectRef="80"/>'
                            "</TrackItems><Index>0</Index></TransitionItems></ClipTrack>")


def test_enxerto_passa_a_transicao_do_modelo_do_avid_para_o_do_premiere(proj, tmp_path):
    """Avid: A vai até o FIM da transição, B começa no INÍCIO (sobrepostos). Premiere (molde de 2026-11-14): os dois
    ENCOSTAM no corte, a transição cobre o mesmo trecho com Alignment = corte − início, e os clipes a apontam
    (TailTransition/HeadTransition). Um lado só: o clipe fica, a transição vai na cauda. Sem clipe: fora, dito."""
    from cicloassist.carta import entrega_prproj as EP
    cam = _ref_com_op_atom(proj, tmp_path, "S01_T002")
    molde = tmp_path / "entrega v01.prproj"
    xml = (_MOLDE_TR.replace("ARQA", str(tmp_path / "S01_T002_A01.mxf")).replace("WAV", str(tmp_path / "x.wav"))
           .replace("ARQ", str(tmp_path / "S01_T002.mxf")))
    EP._gravar_prproj(EP.ET.fromstring(xml.split("?>", 1)[1]), str(molde))
    som = lambda ini, ent, fim: {"midia": cam["id"], "inicio_q": ini, "entrada_q": ent, "fim_q": fim, "canal": 1}  # noqa: E731
    dis = lambda ini, fim, corte: {"inicio_q": ini, "fim_q": fim, "corte_q": corte, "efeito": "BLEND_AUDIO_DISSOLVE"}  # noqa: E731
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 0, "trilhas": [
        {"tipo": "A", "k": 1, "sem_clipe": [],
         "clipes": [som(0, 100, 140), som(100, 500, 200)],
         "transicoes": [dis(100, 140, 110), dis(180, 200, 200), dis(300, 310, 305)]}]}
    saida = str(tmp_path / "entrega v02.prproj")
    rel = EP.escrever_timeline(proj, item, str(molde), saida, "MOLDE", "CORTE", {"A1"})
    assert rel["clipes"] == 2 and rel["transicoes"] == 2
    assert rel["fora"] == {"transição sem clipe escrito (A1)": 1}
    R = EP._ler_prproj(saida)
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    tpf = 10594584000
    tr = por[next(e for e in R if e.tag == "AudioTrackGroup").find("./TrackGroup/Tracks/Track").get("ObjectURef")]
    a, b = [por[x.get("ObjectRef")] for x in tr.findall("./ClipTrack/ClipItems/TrackItems/TrackItem")]
    t1, t2 = [por[x.get("ObjectRef")] for x in tr.findall("./ClipTrack/TransitionItems/TrackItems/TrackItem")]
    assert "80" not in por                                                    # a do molde saiu
    assert a.findtext("./ClipTrackItem/TrackItem/End") == str(110 * tpf)     # A acaba no corte
    assert b.findtext("./ClipTrackItem/TrackItem/Start") == str(110 * tpf)   # B começa no corte…
    sub = por[b.find("./ClipTrackItem/SubClip").get("ObjectRef")]
    assert por[sub.find("Clip").get("ObjectRef")].findtext("./Clip/InPoint") == str(510 * tpf)   # …10 adiante na fonte
    x = t1.find("TransitionTrackItem")
    assert (x.findtext("TrackItem/Start"), x.findtext("TrackItem/End"), x.findtext("Alignment")) == (
        str(100 * tpf), str(140 * tpf), str(10 * tpf))
    assert x.findtext("HasOutgoingClip") == x.findtext("HasIncomingClip") == "true"
    assert a.find("./ClipTrackItem/TailTransition").get("ObjectRef") == EP._chave(t1)
    assert b.find("./ClipTrackItem/HeadTransition").get("ObjectRef") == EP._chave(t1)
    y = t2.find("TransitionTrackItem")                                        # o fade de saída de B, na cauda
    assert y.findtext("Alignment") == str(20 * tpf) and y.findtext("HasIncomingClip") == "false"
    assert b.findtext("./ClipTrackItem/TrackItem/End") == str(200 * tpf)
    assert b.find("./ClipTrackItem/TailTransition").get("ObjectRef") == EP._chave(t2)


def test_enxerto_leva_velocidade_conformacao_e_desligado(proj, tmp_path):
    """Molde `MOLDE VELOCIDADE` (2026-11-14): PlaybackSpeed no Clip, InPoint = a entrada na mídia, OutPoint = entrada +
    duração × velocidade, optical flow = TimeInterpolationType 2; `[1000,1001]` nativo = tempo real com a entrada na
    taxa da fonte (24); desligado = IsMuted no ClipTrackItem."""
    from cicloassist.carta import entrega_prproj as EP
    cam = _ref_com_op_atom(proj, tmp_path, "a001_C003")
    molde = tmp_path / "entrega v01.prproj"
    EP._gravar_prproj(EP.ET.fromstring(_MOLDE.replace("ARQ", str(tmp_path / "a001_C003.mxf")).split("?>", 1)[1]), str(molde))
    criativa = {"razao": 79 / 68, "tipo": "constant", "classe": "creative", "mapa": [[0.0, 0.0], [79.0, 67.15]],
                "retime": "optical_flow"}
    nativa = {"razao": 1000 / 1001, "tipo": "constant", "classe": "native", "mapa": [[0.0, 0.0], [370.0, 370.37]]}
    item = {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "tc_inicio_q": 0, "trilhas": [
        {"tipo": "V", "k": 1, "transicoes": [], "sem_clipe": [], "clipes": [
            {"midia": cam["id"], "inicio_q": 0, "entrada_q": 100, "fim_q": 79, "velocidade": criativa},
            {"midia": cam["id"], "inicio_q": 100, "entrada_q": 37, "fim_q": 470, "velocidade": nativa},
            {"midia": cam["id"], "inicio_q": 500, "entrada_q": 0, "fim_q": 510, "desligado": True}]}]}
    saida = str(tmp_path / "entrega v02.prproj")
    rel = EP.escrever_timeline(proj, item, str(molde), saida, "MOLDE", "CORTE", {"V1"})
    assert rel["clipes"] == 3 and rel["velocidades"] == 1 and rel["desligados"] == 1 and not rel["fora"]
    R = EP._ler_prproj(saida)
    por = {EP._chave(e): e for e in R if EP._chave(e)}
    tpf, tps = 10594584000, 254016000000
    tis = sorted((e for e in R if e.tag == "VideoClipTrackItem"), key=lambda e: int(e.findtext("./ClipTrackItem/TrackItem/Start") or 0))

    def clip(ti):
        return por[por[ti.find("./ClipTrackItem/SubClip").get("ObjectRef")].find("Clip").get("ObjectRef")].find("Clip")
    c0, c1, c2 = (clip(t) for t in tis)
    assert c0.findtext("InPoint") == str(100 * tpf)
    assert c0.findtext("OutPoint") == str(100 * tpf + round(79 * tpf * 0.85))
    assert float(c0.findtext("PlaybackSpeed")) == pytest.approx(0.85) and c0.findtext("TimeInterpolationType") == "2"
    assert c1.findtext("InPoint") == str(37 * tps // 24)                      # 37 quadros a 24, em tempo real
    assert c1.findtext("OutPoint") == str(37 * tps // 24 + 370 * tpf) and c1.find("PlaybackSpeed") is None
    assert tis[2].findtext("./ClipTrackItem/IsMuted") == "true" and tis[0].find("./ClipTrackItem/IsMuted") is None


def test_vinculo_e_um_trecho_so():
    """Autor, 2026-11-14: o vínculo é de UM trecho. Os canais do mesmo pedaço (mesmo take, sincronia, início e fim) se
    vinculam entre si mesmo sem imagem; a imagem entra no grupo em sincronia de MAIOR sobreposição; o grupo depois de
    um corte fica só entre si; som de outro take ou fora de sincronia, solto."""
    from cicloassist.carta import entrega_prproj as EP
    seq = EP.ET.fromstring("<Sequence><PersistentGroupContainer><LinkContainer/></PersistentGroupContainer></Sequence>")
    n = [100]

    def novo_id():
        n[0] += 1
        return str(n[0])
    c = lambda ti, audio, ini, fim, chave="take", sinc=5: {"ti": ti, "audio": audio, "ini": ini, "fim": fim,  # noqa: E731
                                                           "chave": chave, "sinc": sinc}
    clipes = [c("v1", False, 0, 100),
              c("a1", True, 10, 80), c("a2", True, 10, 80),          # o grupo da imagem (começa um pouco depois)
              c("b1", True, 85, 130), c("b2", True, 85, 130),        # depois do corte: só entre si
              c("x1", True, 0, 100, chave="outro"), c("y1", True, 0, 100, sinc=9),
              c("s1", True, 300, 400, chave="sem imagem"), c("s2", True, 300, 400, chave="sem imagem")]
    novos, rel = [], {}
    EP._vincular(seq, clipes, novo_id, novos, rel)
    grupos = [[x.get("ObjectRef") for x in lk.find("TrackItemGroup/TrackItems")] for lk in novos]
    assert grupos == [["v1", "a1", "a2"], ["b1", "b2"], ["s1", "s2"]]
    assert rel["vinculos"] == 3 and rel["vinculos_com_imagem"] == 1
