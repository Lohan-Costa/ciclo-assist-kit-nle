"""Os moldes do "Importar para o Premiere" (`carta/moldes_prproj.py`) e o nome do item da sequência escrita."""

import xml.etree.ElementTree as ET

from cicloassist.carta import entrega_prproj as E
from cicloassist.carta import moldes_prproj as M

NADA = {"som_sem_ganho": False, "som_com_ganho": False, "transicao_V": False, "transicao_A": False, "merged": 0}


def test_a_sequencia_molde_e_sempre_feita_na_copia():
    tudo = {"som_sem_ganho": True, "som_com_ganho": True, "transicao_V": True, "transicao_A": True, "merged": 5}
    pede = {"video": True, "som": True, "ganho": True, "transicao_V": True, "transicao_A": True, "merged": True}
    assert M.faltam(tudo, pede) == ["sequencia"]


def test_so_falta_o_que_a_timeline_pede():
    assert M.faltam(NADA, {"video": True, "som": True}) == ["sequencia", "som"]
    assert M.faltam(NADA, {"som": True, "ganho": True, "transicao_A": True, "merged": True}) == [
        "sequencia", "som", "ganho", "transicao_A", "merged"]


def _projeto(com_mono: bool) -> ET.Element:
    """Um .prproj mínimo: um item de imagem e (talvez) um de som mono, no formato que `midia_do_projeto` lê."""
    R = ET.Element("PremiereData")

    def item(uid_cpi, no, uid_mc, clipes):
        cpi = ET.SubElement(R, "ClipProjectItem", {"ObjectUID": uid_cpi})
        pi = ET.SubElement(cpi, "ProjectItem")
        ET.SubElement(ET.SubElement(pi, "Node"), "ID").text = str(no)
        ET.SubElement(cpi, "MasterClip", {"ObjectURef": uid_mc})
        mc = ET.SubElement(R, "MasterClip", {"ObjectUID": uid_mc})
        cs = ET.SubElement(mc, "Clips")
        for i, (tag, arq, oid) in enumerate(clipes):
            ET.SubElement(cs, "Clip", {"Index": str(i), "ObjectRef": oid})
            cl = ET.SubElement(R, tag, {"ObjectID": oid})
            ET.SubElement(ET.SubElement(cl, "Clip"), "Source", {"ObjectRef": oid + "s"})
            ms = ET.SubElement(R, "VideoMediaSource" if tag == "VideoClip" else "AudioMediaSource", {"ObjectID": oid + "s"})
            ET.SubElement(ET.SubElement(ms, "MediaSource"), "Media", {"ObjectURef": oid + "m"})
            med = ET.SubElement(R, "Media", {"ObjectUID": oid + "m"})
            ET.SubElement(med, "FilePath").text = arq

    item("cpi-v", 1000018, "mc-v", [("VideoClip", "/m/a.mxf", "10")])
    if com_mono:
        item("cpi-a", 1000019, "mc-a", [("AudioClip", "/m/a_A01.mxf", "20")])
    return R


def test_o_plano_usa_o_nodeId_em_hexadecimal_e_monta_so_o_que_falta():
    R = _projeto(com_mono=True)
    plano, nao = M.plano(R, ["sequencia", "som", "ganho", "transicao_V"], ["/m/a.mxf", "/m/a_A01.mxf"])
    linhas = plano.split("\n")
    assert linhas[0] == f"seq\t{M.NOME_DOS_MOLDES}\t{M.BIN_DOS_MOLDES}"
    assert linhas[1].startswith("p\t000f4252\t")                   # 1000018 → 000f4252 (medido)
    assert any(l.startswith("tr\t1\t") for l in linhas)            # dissolve de imagem
    assert not any(l.startswith("tr\t0\t") for l in linhas)        # o de som não foi pedido
    assert any(l.startswith("p\t000f4253\t") and l.count("\t") == 7 for l in linhas)   # o ganho leva o nível
    assert nao == []


def test_sem_som_mono_e_sem_merged_fica_dito():
    plano, nao = M.plano(_projeto(com_mono=False), ["sequencia", "som", "merged"], ["/m/a.mxf"])
    assert "som: nenhum som MONO da timeline está no projeto" in nao
    assert any(n.startswith("merged:") for n in nao)


def test_o_item_da_sequencia_e_renomeado_junto():
    """O Premiere MOSTRA o nome do item do projeto, não o `Sequence/Name` (medido: entrava "MOLDES (Ciclo Assist)")."""
    R = ET.fromstring("""<PremiereData>
      <Sequence ObjectUID="S"><Name>X</Name></Sequence>
      <VideoSequenceSource ObjectID="1"><SequenceSource><Sequence ObjectURef="S"/></SequenceSource></VideoSequenceSource>
      <VideoClip ObjectID="2"><Clip><Source ObjectRef="1"/></Clip></VideoClip>
      <MasterClip ObjectUID="M"><Name>MOLDES</Name><Clips><Clip Index="0" ObjectRef="2"/></Clips></MasterClip>
      <ClipProjectItem ObjectUID="C"><ProjectItem><Name>MOLDES</Name></ProjectItem><MasterClip ObjectURef="M"/></ClipProjectItem>
      <ClipProjectItem ObjectUID="D"><ProjectItem><Name>outro</Name></ProjectItem><MasterClip ObjectURef="N"/></ClipProjectItem>
    </PremiereData>""")
    seq = R.find("Sequence")
    assert E._renomear_item_da_sequencia(R, seq, "PRODA_CORTE.00.2") == 1
    assert R.find("./ClipProjectItem[@ObjectUID='C']/ProjectItem/Name").text == "PRODA_CORTE.00.2"
    assert R.find("MasterClip/Name").text == "PRODA_CORTE.00.2"
    assert R.find("./ClipProjectItem[@ObjectUID='D']/ProjectItem/Name").text == "outro"


def test_stretch_e_ganho_acima_de_15_db():
    """O stretch do Avid vira escala NÃO uniforme da mídia para o quadro; a mídia do tamanho do quadro não muda nada.
    O plano dos moldes pede o clipe esticado (linha `esc`) quando a timeline tem stretch (2026-11-20)."""
    from cicloassist.carta import entrega_prproj as E
    assert E.escala_do_stretch("0,0,2048,1080", (1920, 1080)) == (93.75, 100.0)
    assert E.escala_do_stretch("0,0,1920,1080", (1920, 1080)) is None
    assert E.escala_do_stretch(None, (1920, 1080)) is None
    assert E.GANHO_MAXIMO_DO_VOLUME_DB == 15.0
    assert M.faltam({**NADA, "esticar": False}, {"video": True, "esticar": True}) == ["sequencia", "esticar"]


def test_stabilize_do_avid_vira_warp_stabilizer():
    """Decisão do autor (2026-11-20): estabilizador → estabilizador. O plano leva o MEIO do segmento (uma transição
    pode mover o começo), Position, Smooth Motion, o filtro × 100 e o Auto-scale quando o Avid tinha Auto-Zoom."""
    from cicloassist.carta import importar_premiere as I
    est = {"nome": "EFF2_STABILIZE", "params": {"auto_zoom": True, "estabilizacao": {"filtro": 0.5, "x": [0.5], "y": [0.5]}}}
    sem = {"nome": "EFF2_STABILIZE", "params": {}}
    assert E.estabilizacao_do_efeito(est) is not None and E.estabilizacao_do_efeito(sem) is None
    item = {"fps": "24000/1001", "trilhas": [
        {"tipo": "V", "k": 2, "clipes": [{"inicio_q": 5710, "fim_q": 5913, "efeitos": [est]}]},
        {"tipo": "V", "k": 1, "clipes": [{"inicio_q": 0, "fim_q": 10, "efeitos": [sem]},
                                         {"inicio_q": 20, "fim_q": 30, "efeitos": [est], "velocidade": {"classe": "x"}}]}]}
    assert I.plano_de_estabilizacao(item) == "1\t242.387979\t0\t0\t50.0\t2\n"


def test_efeitos_sem_par_sao_ditos_pelo_nome_inclusive_offline():
    """Decisão do autor (2026-11-15): no som, plugin do MC = "sem correspondência"; e o efeito do clipe OFFLINE também
    é dito (religada a mídia, ele não estará lá). Pan fora do centro: ainda não escrito, dito."""
    ditos = []
    dverb = {"nome": "EFF_AUDIO_AS_PLUG_IN", "categoria": "other", "rotulo": "D-Verb", "params": {}}
    pv = lambda pan: {"nome": "Audio Pan Volume", "categoria": "gain", "params": {"level": 1, "pan": pan}}  # noqa: E731
    E._efeitos_sem_par({"efeitos": [dverb, pv(16384)]}, True, "A7", ditos.append, offline=True)
    E._efeitos_sem_par({"efeitos": [pv(0)]}, True, "A2", ditos.append)
    assert ditos == ["efeito de áudio D-Verb: sem correspondência no Premiere (A7, clipe offline)",
                     "pan fora do centro: ainda não escrito (A2)"]


def test_transicao_de_clipe_offline_e_dita_como_tal():
    ditos = []
    tr = [{"inicio_q": 100, "fim_q": 120, "corte_q": 110, "efeito": "BLEND_AUDIO_DISSOLVE"},
          {"inicio_q": 300, "fim_q": 320, "corte_q": 310, "efeito": "BLEND_AUDIO_DISSOLVE"}]
    moldes = {"A": object()}
    E._transicoes_da_trilha(tr, [], True, moldes, ditos.append, "A6", 1, offline=[(100, 200)])
    assert ditos == ["transição de clipe offline (A6)", "transição sem clipe escrito (A6)"]


def _projeto_com_molde_de_cor(seq_nome: str, brilho: str = "0.") -> ET.Element:
    """Uma sequência com UM clipe de vídeo com ProcAmp → Lumetri (o que o `cicloMontar` faz na linha `cor`)."""
    import base64
    import struct
    blob = b"".join(struct.pack("<II", 7, 0) + b"\0" * 512 for _ in range(4))
    k = lambda v: f"-91445760000000000,{v},0,0,0,0,0,0"  # noqa: E731
    return ET.fromstring(f"""<PremiereData>
      <Sequence ObjectUID="S"><Name>{seq_nome}</Name><TrackGroups><TrackGroup><Second ObjectRef="1"/></TrackGroup></TrackGroups></Sequence>
      <VideoTrackGroup ObjectID="1"><TrackGroup><Tracks><Track Index="0" ObjectURef="T"/></Tracks></TrackGroup></VideoTrackGroup>
      <VideoClipTrack ObjectUID="T"><ClipTrack><ClipItems><TrackItems><TrackItem Index="0" ObjectRef="2"/></TrackItems></ClipItems></ClipTrack></VideoClipTrack>
      <VideoClipTrackItem ObjectID="2"><ClipTrackItem><ComponentOwner><Components ObjectRef="3"/></ComponentOwner></ClipTrackItem></VideoClipTrackItem>
      <VideoComponentChain ObjectID="3"><ComponentChain><Components><Component Index="0" ObjectRef="4"/><Component Index="1" ObjectRef="5"/></Components></ComponentChain></VideoComponentChain>
      <VideoFilterComponent ObjectID="4"><Component><Params><Param Index="0" ObjectRef="41"/><Param Index="1" ObjectRef="42"/><Param Index="2" ObjectRef="43"/><Param Index="3" ObjectRef="44"/></Params></Component><MatchName>AE.ADBE ProcAmp</MatchName></VideoFilterComponent>
      <VideoComponentParam ObjectID="41"><ParameterID>1</ParameterID><StartKeyframe>{k(brilho)}</StartKeyframe></VideoComponentParam>
      <VideoComponentParam ObjectID="42"><ParameterID>2</ParameterID><StartKeyframe>{k("100.")}</StartKeyframe></VideoComponentParam>
      <VideoComponentParam ObjectID="43"><ParameterID>3</ParameterID><StartKeyframe>{k("0.")}</StartKeyframe></VideoComponentParam>
      <VideoComponentParam ObjectID="44"><ParameterID>4</ParameterID><StartKeyframe>{k("100.")}</StartKeyframe></VideoComponentParam>
      <VideoFilterComponent ObjectID="5"><Component><Params><Param Index="0" ObjectRef="51"/></Params></Component><MatchName>AE.ADBE Lumetri</MatchName></VideoFilterComponent>
      <ArbVideoComponentParam ObjectID="51"><ParameterID>39</ParameterID><StartKeyframeValue Encoding="base64" BinaryHash="h">{base64.b64encode(blob).decode()}</StartKeyframeValue></ArbVideoComponentParam>
      <VideoComponentChain ObjectID="9"><ComponentChain><Components/></ComponentChain></VideoComponentChain>
    </PremiereData>""")


def test_a_cor_do_avid_vira_procamp_e_lumetri():
    """O CC do Avid (Sat + curva Master) → ProcAmp Saturation + Lumetri com a curva em R, G e B (2026-11-20). O molde só
    vem da sequência de MOLDES e com o ProcAmp neutro (um clipe do editor já graduado não serve)."""
    import base64
    import struct
    assert M.faltam({**NADA, "cor": False}, {"video": True, "cor": True}) == ["sequencia", "cor"]
    plano, _ = M.plano(_projeto(com_mono=False), ["sequencia", "cor"], ["/m/a.mxf"])
    assert "cor\t1\t0\t14" in plano.split("\n")
    assert E.molde_de_cor(*_por(_projeto_com_molde_de_cor("do editor"))) is None
    assert E.molde_de_cor(*_por(_projeto_com_molde_de_cor(M.NOME_DOS_MOLDES, brilho="20."))) is None
    R, por = _por(_projeto_com_molde_de_cor(M.NOME_DOS_MOLDES))
    molde = E.molde_de_cor(R, por)
    assert [c.findtext("MatchName") for c in molde] == ["AE.ADBE ProcAmp", "AE.ADBE Lumetri"]
    cruz = [[0.0, 0.0], [0.308107, 0.333824], [0.565271, 0.725999], [1.0, 1.0]]
    ids = iter(range(100, 1000))
    novos: list = []
    cadeia = por["9"]
    E._cor_na_cadeia(R, por, molde, cadeia, {"sat": 87.5, "curva": cruz}, lambda: str(next(ids)), novos)
    refs = [c.get("ObjectRef") for c in cadeia.iter("Component")]
    comps = [next(x for x in novos if x.get("ObjectID") == r) for r in refs]
    assert [c.findtext("MatchName") for c in comps] == ["AE.ADBE ProcAmp", "AE.ADBE Lumetri"]
    sat = next(x for x in novos if x.findtext("ParameterID") == "4")
    assert sat.findtext("StartKeyframe").split(",")[1] == "87.5"
    blob = base64.b64decode(next(x for x in novos if x.findtext("ParameterID") == "39").findtext("StartKeyframeValue"))
    n = [struct.unpack("<II", blob[b * 520:b * 520 + 8]) for b in range(4)]
    assert n[0] == (7, 0) and n[1] == n[2] == n[3] and n[1][0] == 7 and n[1][1] > 4    # a mestra intacta; R=G=B
    assert por["51"].findtext("StartKeyframeValue") != blob                              # o molde não mudou
    # só a curva: o ProcAmp não entra
    cad2 = ET.fromstring('<VideoComponentChain ObjectID="8"><ComponentChain><Components/></ComponentChain></VideoComponentChain>')
    E._cor_na_cadeia(R, por, molde, cad2, {"sat": None, "curva": cruz}, lambda: str(next(ids)), [])
    assert len(list(cad2.iter("Component"))) == 1


def _por(R):
    return R, {E._chave(e): e for e in R if E._chave(e)}
