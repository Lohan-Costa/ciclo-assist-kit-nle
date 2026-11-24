"""O subclipe SINCRONIZADO do Avid → MERGED CLIP no `.prproj`, sobre o MOLDE que o próprio Premiere fez (2026-11-14,
26.0.2 Mac; banco `protocolos/prproj/escrita.md` §11l).

O molde: um merged feito pelo autor PELA TIMELINE, aparado (o equivalente do subclipe do Avid: só onde imagem e som se
encontram), câmera OP-Atom + os 5 canais OP-Atom do gravador. Lido no arquivo salvo:

    ClipProjectItem → MasterClip do merged (Clips: AudioClip→AudioSequenceSource, VideoClip→VideoSequenceSource;
                       AudioComponentChains e ClipChannelGroupVector: UM por canal, mono)
                    → Sequence (`BE.Sequence.IsMergedClip`, `MZ.ZeroPoint` = o `Start` da câmera + a entrada dela):
                       V1 com a câmera, A1..AN com um canal cada, um `Link`
    os COMPONENTES (fora da bin): a câmera e cada canal são CÓPIAS do MasterClip importado — `Media` própria (igual à
    importada, `ModificationState` vazio), o nome do merged, `MZ.MergeClipUtils.ComponentMasterClipOriginalName` (+
    `AudioTrackNumberFromOriginalMergedClip` = 0..N−1 no som), a entrada e a saída aparadas, `ClipID` novos.

Na timeline, o clipe que vem do merged aponta o COMPONENTE (a câmera ou o canal), não o MasterClip do merged.

⭐ O merged é montado de DUAS fontes, nunca adivinhado: o que é do merged (47+ objetos) é clonado do molde; o que é da
mídia (Media, streams, logging, grupos de canal) vem do item que o Premiere IMPORTOU daquele arquivo. Canais a menos que
o molde: os do fim saem (trilha, cadeia, grupo e o lugar no Link). Canais a mais: recusado, dito.
"""

from __future__ import annotations

import copy
import uuid
import xml.etree.ElementTree as ET

from .projeto import CartaErro

PARAR = {"Project", "RootProjectItem", "BinProjectItem"}
#: a cor do merged que a Carta escreve (autor, 2026-11-15): Cerulean, a 5ª da lista de rótulos do Premiere — o índice é
#: SEQUENCIAL a partir de 0 (lido no projeto em que o autor pintou os 36: `BE.Prefs.LabelColors.4` nos clipes de vídeo e
#: de som do merged, sem `asl.clip.label.color`)
COR_DO_MERGED = "BE.Prefs.LabelColors.4"
_PROP_NOME = "MZ.MergeClipUtils.ComponentMasterClipOriginalName"
_PROP_TRILHA = "MZ.MergeClipUtils.AudioTrackNumberFromOriginalMergedClip"


def _chave(e: ET.Element) -> str | None:
    return e.get("ObjectID") or e.get("ObjectUID")


def _refs(e: ET.Element):
    for x in e.iter():
        for a in ("ObjectRef", "ObjectURef"):
            if x.get(a):
                yield x, a, x.get(a)


def _e_componente(e: ET.Element) -> bool:
    return e.tag == "MasterClip" and e.find(f"./Node/Properties/{_PROP_NOME}") is not None


def _fecho(inicio: ET.Element, por: dict, parar=lambda e: False) -> list[ET.Element]:
    """Tudo que `inicio` alcança por ObjectRef/ObjectURef, em ordem de descoberta (sem os contêineres do projeto)."""
    vistos, fila, out = set(), [inicio], []
    while fila:
        e = fila.pop(0)
        k = _chave(e)
        if k in vistos:
            continue
        vistos.add(k)
        out.append(e)
        for _x, _a, r in _refs(e):
            t = por.get(r)
            if t is not None and t.tag not in PARAR and _chave(t) not in vistos and not parar(t):
                fila.append(t)
    return out


def molde(R: ET.Element, por: dict) -> dict | None:
    """O merged do projeto com MAIS canais (o molde): {cpi, mc, seq, camera, canais: [MasterClip por trilha]}."""
    melhor = None
    for cpi in R.iter("ClipProjectItem"):
        r = cpi.find("MasterClip")
        mc = por.get(r.get("ObjectURef")) if r is not None else None
        if mc is None:
            continue
        seq = None
        for c in mc.findall("./Clips/Clip"):
            cl = por.get(c.get("ObjectRef") or "")
            s = cl.find("./Clip/Source") if cl is not None else None
            src = por.get(s.get("ObjectRef")) if s is not None else None
            sq = src.find("./SequenceSource/Sequence") if src is not None else None
            if sq is not None:
                seq = por.get(sq.get("ObjectURef"))
        if seq is None or seq.findtext("./Node/Properties/BE.Sequence.IsMergedClip") != "true":
            continue
        comps = [e for e in _fecho(cpi, por) if _e_componente(e)]
        camera = next((e for e in comps if e.find(f"./Node/Properties/{_PROP_TRILHA}") is None), None)
        canais = sorted((e for e in comps if e.find(f"./Node/Properties/{_PROP_TRILHA}") is not None),
                        key=lambda e: int(e.findtext(f"./Node/Properties/{_PROP_TRILHA}")))
        if camera is None or not canais:
            continue
        if melhor is None or len(canais) > len(melhor["canais"]):
            melhor = {"cpi": cpi, "mc": mc, "seq": seq, "camera": camera, "canais": canais}
    return melhor


def os_merged(R: ET.Element, por: dict) -> list[tuple[ET.Element, ET.Element]]:
    """Todo merged do projeto: [(ClipProjectItem, MasterClip)] — o MasterClip cuja fonte é uma sequência
    `BE.Sequence.IsMergedClip`."""
    out = []
    for cpi in R.iter("ClipProjectItem"):
        r = cpi.find("MasterClip")
        mc = por.get(r.get("ObjectURef")) if r is not None else None
        if mc is None:
            continue
        for c in mc.findall("./Clips/Clip"):
            cl = por.get(c.get("ObjectRef") or "")
            s = cl.find("./Clip/Source") if cl is not None else None
            src = por.get(s.get("ObjectRef")) if s is not None else None
            sq = src.find("./SequenceSource/Sequence") if src is not None else None
            seq = por.get(sq.get("ObjectURef")) if sq is not None else None
            if seq is not None and seq.findtext("./Node/Properties/BE.Sequence.IsMergedClip") == "true":
                out.append((cpi, mc))
                break
    return out


_CLASSE_TRANSCRICAO = "9e0179bb-153c-4884-b34b-eb7082f34384"       # TranscriptClip
_CLASSE_FONTE_DE_DADOS = "ff36343e-4ece-4d37-ab61-e99b758f9d30"    # DataMediaSource


def transcricao_vazia(R: ET.Element, por: dict, mc: ET.Element, ids: "_Ids") -> list[ET.Element]:
    """Põe no merged `mc` um `TranscriptClip` VAZIO (a forma que o Premiere grava para um clipe sem transcrição:
    `DataClip` → `DataMediaSource` → a Media, sem `TranscriptTextSegments`). Devolve os objetos novos (já em `R`).

    ⭐ Por quê (banco `plugins/premiere-cep/subclipe-e-merged-clip.md`, "Por que o importSequences DUPLICA o merged"):
    no 26.0.2 o merged do projeto ABERTO mistura uma transcrição vazia na impressão que o `importSequences` compara, e o
    merged carregado pelo Dynamic Link não; com ela no arquivo, os dois passam a ter a mesma impressão."""
    for c in mc.findall("./Clips/Clip"):
        e = por.get(c.get("ObjectRef") or "")
        if e is not None and e.tag == "TranscriptClip":
            return []
    media = None
    for e in _fecho(mc, por):
        if _e_componente(e) and e.find(f"./Node/Properties/{_PROP_TRILHA}") is not None:
            media = next((x for x in _fecho(e, por) if x.tag == "Media"), None)
            if media is not None:
                break
    if media is None:
        return []
    src = ET.Element("DataMediaSource", {"ObjectID": ids.novo(),
                                         "ClassID": _CLASSE_FONTE_DE_DADOS, "Version": "1"})
    ms = ET.SubElement(src, "MediaSource", {"Version": "4"})
    ET.SubElement(ms, "Content", {"Version": "10"})
    ET.SubElement(ms, "Media", {"ObjectURef": _chave(media)})
    ET.SubElement(src, "OriginalDuration").text = "0"
    tc = ET.Element("TranscriptClip", {"ObjectID": ids.novo(),
                                       "ClassID": _CLASSE_TRANSCRICAO, "Version": "2"})
    cl = ET.SubElement(ET.SubElement(tc, "DataClip", {"Version": "1"}), "Clip", {"Version": "18"})
    ET.SubElement(cl, "Source", {"ObjectRef": _chave(src)})
    ET.SubElement(cl, "ClipID").text = str(uuid.uuid4())
    ET.SubElement(cl, "InUse").text = "false"
    clips = mc.find("Clips")
    ET.SubElement(clips, "Clip", {"Index": str(len(clips)), "ObjectRef": _chave(tc)})
    for e in (tc, src):
        R.append(e)
        por[_chave(e)] = e
    return [tc, src]


class _Ids:
    def __init__(self, R: ET.Element, piso: int = 0):
        self.n = max(piso, max(int(k) for k in (e.get("ObjectID") for e in R) if k and k.isdigit()))
        nodes = [int(x.text) for x in R.iter("ID") if x.text and x.text.isdigit() and len(x.text) <= 9]
        self.node = max(nodes or [1000000])

    def objeto(self, velho: ET.Element) -> str:
        if velho.get("ObjectID") is not None:
            self.n += 1
            return str(self.n)
        return str(uuid.uuid4())

    def novo(self) -> str:
        """Um ObjectID numérico novo (objeto que não é cópia de outro)."""
        self.n += 1
        return str(self.n)

    def no(self) -> str:
        self.node += 1
        return str(self.node)


def _clonar_grafo(objs: list[ET.Element], ids: _Ids, mapa: dict) -> list[ET.Element]:
    """Cópias de `objs` com ids NOVOS; toda referência a um objeto do grupo (ou já em `mapa`) é trocada."""
    for e in objs:
        mapa.setdefault(_chave(e), ids.objeto(e))
    novos = []
    for e in objs:
        c = copy.deepcopy(e)
        c.set("ObjectID" if e.get("ObjectID") is not None else "ObjectUID", mapa[_chave(e)])
        for x, a, r in _refs(c):
            if r in mapa:
                x.set(a, mapa[r])
        novos.append(c)
    return novos


def _componente(mc_importado: ET.Element, por: dict, ids: _Ids, nome: str, original: str, trilha: int | None,
                ini_t: int, dur_t: int) -> list[ET.Element]:
    """A cópia do MasterClip importado como COMPONENTE do merged (o que o Premiere faz ao mesclar)."""
    objs = _fecho(mc_importado, por)
    novos = _clonar_grafo(objs, ids, {})
    mc = novos[0]
    node = mc.find("Node")
    if node is None:
        node = ET.Element("Node", {"Version": "1"})
        mc.insert(0, node)
    for x in node.findall("ID"):
        node.remove(x)
    props = node.find("Properties")
    if props is None:
        props = ET.Element("Properties", {"Version": "1"})
        node.insert(0, props)
    if trilha is not None:
        ET.SubElement(props, _PROP_TRILHA).text = str(trilha)
        for x in mc.findall("DefMappingID"):
            mc.remove(x)
    ET.SubElement(props, _PROP_NOME).text = original
    mc.find("Name").text = nome
    for e in novos:
        if e.tag == "ClipLoggingInfo" and e.find("ClipName") is not None:
            e.find("ClipName").text = nome
        if e.tag in ("VideoClip", "AudioClip"):
            cl = e.find("Clip")
            for tag, v in (("InPoint", ini_t), ("OutPoint", ini_t + dur_t)):
                el = cl.find(tag)
                if el is None:
                    el = ET.SubElement(cl, tag)
                el.text = str(v)
            if cl.find("ClipID") is not None:
                cl.find("ClipID").text = str(uuid.uuid4())
        if e.tag == "Media" and e.find("ModificationState") is not None:
            e.find("ModificationState").text = ""
    return novos


def _pintar(mc: ET.Element, por: dict, rotulo: str = COR_DO_MERGED) -> None:
    """O rótulo de cor nos clipes de vídeo e de som do merged (`Clip/Node/Properties/asl.clip.label.name`)."""
    for c in mc.findall("./Clips/Clip"):
        cl = por.get(c.get("ObjectRef"))
        if cl is None or cl.tag not in ("VideoClip", "AudioClip") or cl.find("Clip") is None:
            continue
        clip = cl.find("Clip")
        node = clip.find("Node")
        if node is None:
            node = ET.Element("Node", {"Version": "1"})
            clip.insert(0, node)
        props = node.find("Properties")
        if props is None:
            props = ET.SubElement(node, "Properties", {"Version": "1"})
        for x in props.findall("asl.clip.label.color"):
            props.remove(x)                    # a cor vem da preferência do índice, como o Premiere grava
        nome = props.find("asl.clip.label.name")
        if nome is None:
            nome = ET.SubElement(props, "asl.clip.label.name")
        nome.text = rotulo


def _pintar_item(cpi: ET.Element, rotulo: str = COR_DO_MERGED) -> None:
    """O rótulo do ITEM da bin (`ProjectItem/Node/Properties/Column.PropertyText.Label`) — o que o painel mostra."""
    pi = cpi.find("ProjectItem")
    if pi is None:
        return
    node = pi.find("Node")
    if node is None:
        node = ET.Element("Node", {"Version": "1"})
        pi.insert(0, node)
    props = node.find("Properties")
    if props is None:
        props = ET.Element("Properties", {"Version": "1"})
        node.insert(0, props)
    el = props.find("Column.PropertyText.Label")
    if el is None:
        el = ET.SubElement(props, "Column.PropertyText.Label")
    el.text = rotulo


def _alinhar_e_enquadrar(seq: ET.Element, por: dict, cam: list[ET.Element], dur_t: int) -> None:
    """Na sequência interna do merged: todo item de trilha (vídeo e som) de 0 a `dur_t`, e o quadro (o `FrameRect` do
    grupo de vídeo e o tamanho da prévia) igual ao da câmera (`VideoStream/FrameRect` dela)."""
    quadro = next((e.findtext("FrameRect") for e in cam if e.tag == "VideoStream" and e.findtext("FrameRect")), None)
    for tg in seq.iter("TrackGroup"):
        s = tg.find("Second")
        g = por.get(s.get("ObjectRef")) if s is not None else None
        if g is None or g.find("./TrackGroup/Tracks") is None:
            continue
        if g.tag == "VideoTrackGroup" and quadro and g.find("FrameRect") is not None:
            g.find("FrameRect").text = quadro
        for x in g.find("./TrackGroup/Tracks"):
            tr = por.get(x.get("ObjectURef"))
            if tr is None:
                continue
            for ti in tr.findall("./ClipTrack/ClipItems/TrackItems/TrackItem"):
                it = por.get(ti.get("ObjectRef"))
                base = it.find("./ClipTrackItem/TrackItem") if it is not None else None
                if base is None:
                    continue
                for x0 in base.findall("Start"):
                    base.remove(x0)                 # sem `Start` = 0, como o som do próprio Premiere
                fim = base.find("End")
                if fim is None:
                    fim = ET.SubElement(base, "End")
                fim.text = str(dur_t)
    props = seq.find("./Node/Properties")
    if props is not None:
        if props.find("MZ.WorkOutPoint") is not None:
            props.find("MZ.WorkOutPoint").text = str(dur_t)
        if quadro:
            w, h = quadro.split(",")[2:4]
            for tag, v in (("MZ.Sequence.PreviewFrameSizeWidth", w), ("MZ.Sequence.PreviewFrameSizeHeight", h)):
                if props.find(tag) is not None:
                    props.find(tag).text = v


def escrever(R: ET.Element, por: dict, m: dict, nome: str, camera_mc: ET.Element, canais_mc: list[ET.Element],
             img_ini_t: int, som_ini_t: int, dur_t: int, bin_alvo: ET.Element | None = None, piso: int = 0) -> dict:
    """Acrescenta a `R` um merged `nome`: a câmera `camera_mc` (o MasterClip importado) a partir de `img_ini_t`, e os
    canais `canais_mc` (um MasterClip importado por canal, em ordem) a partir de `som_ini_t`, por `dur_t` ticks.
    Devolve {"cpi", "camera": (uid, VideoClip id), "canais": [(uid, AudioClip id)], "novos": [...]}.
    ⚠️ Os objetos vão para o fim de `R`; o item entra em `bin_alvo` (ou na raiz)."""
    n = len(canais_mc)
    if n > len(m["canais"]):
        raise CartaErro(f"o merged {nome!r} tem {n} canais e o molde só {len(m['canais'])}")
    ids = _Ids(R, piso)       # ⛔ `piso`: quem chama pode ter objetos numerados AINDA fora de `R` (medido: 84 repetidos)
    nome_molde = m["mc"].findtext("Name")
    # 1. os componentes, das mídias importadas
    cam = _componente(camera_mc, por, ids, nome, camera_mc.findtext("Name") or "", None, img_ini_t, dur_t)
    sons = [_componente(c, por, ids, nome, c.findtext("Name") or "", k, som_ini_t, dur_t)
            for k, c in enumerate(canais_mc)]
    # 2. o par molde ↔ novo de cada componente: o MasterClip e, por clipe, a fonte e os marcadores
    mapa: dict[str, str] = {}

    def parear(velho_mc: ET.Element, novos: list[ET.Element]) -> None:
        novo_mc = novos[0]
        por_novo = {_chave(e): e for e in novos}
        mapa[_chave(velho_mc)] = _chave(novo_mc)
        v_clips = [por[c.get("ObjectRef")] for c in velho_mc.findall("./Clips/Clip")]
        n_clips = [por_novo[c.get("ObjectRef")] for c in novo_mc.findall("./Clips/Clip")]
        for vc, nc in zip(v_clips, n_clips):
            for caminho in ("./Clip/Source", "./Clip/MarkerOwner/Markers"):
                a, b = vc.find(caminho), nc.find(caminho)
                if a is not None and b is not None:
                    mapa[a.get("ObjectRef")] = b.get("ObjectRef")

    parear(m["camera"], cam)
    for k in range(n):
        parear(m["canais"][k], sons[k])
    # 3. o que é DO merged, clonado do molde (sem os componentes e o que é deles)
    deles = set()
    for comp in [m["camera"], *m["canais"]]:
        deles |= {_chave(e) for e in _fecho(comp, por)}
    proprios = [e for e in _fecho(m["cpi"], por, parar=_e_componente) if _chave(e) not in deles]
    novos = _clonar_grafo(proprios, ids, mapa)
    por_novo = {_chave(e): e for e in novos}
    cpi, mc_m = novos[0], por_novo[mapa[_chave(m["mc"])]]
    seq = por_novo[mapa[_chave(m["seq"])]]
    # 4. canais a menos que o molde: a trilha, a cadeia, o grupo de canal e o lugar no Link saem
    tirar_itens: set[str] = set()
    if n < len(m["canais"]):
        for cadeias in mc_m.findall("AudioComponentChains"):
            for x in list(cadeias):
                if int(x.get("Index", "0")) >= n:
                    cadeias.remove(x)
        grupos = por_novo.get(mc_m.find("AudioClipChannelGroups").get("ObjectRef"))
        if grupos is not None:
            vet = grupos.find("ClipChannelVectors")
            for x in list(vet):
                if int(x.get("Index", "0")) >= n:
                    vet.remove(x)
        for tg in seq.iter("TrackGroup"):
            s = tg.find("Second")
            g = por_novo.get(s.get("ObjectRef")) if s is not None else None
            if g is None or g.tag != "AudioTrackGroup":
                continue
            lista = g.find("./TrackGroup/Tracks")
            for x in list(lista):
                if int(x.get("Index", "0")) >= n:
                    tr = por_novo.get(x.get("ObjectURef"))
                    if tr is not None:
                        tirar_itens |= {ti.get("ObjectRef") for ti in tr.findall("./ClipTrack/ClipItems/TrackItems/TrackItem")}
                    lista.remove(x)
        for e in novos:
            if e.tag == "AudioTrackInlet":         # a master do mix lista as trilhas: as que saíram saem daqui também
                fontes = e.find("Sources")
                for x in list(fontes):
                    if int(x.get("Index", "0")) >= n:
                        fontes.remove(x)
            if e.tag == "Link":
                for x in list(e.find("./TrackItemGroup/TrackItems")):
                    if x.get("ObjectRef") in tirar_itens:
                        e.find("./TrackItemGroup/TrackItems").remove(x)
    # 4b. ⛔⛔ a sequência interna NÃO herda do molde a posição das trilhas nem o quadro (autor, 2026-11-15, na
    #     reimportação da PRODA_CORTE.00.2 pelo modelo da calibragem): o merged sintético tem o vídeo em 3,587 s e o som
    #     até 0,959 s (o "Mesclar clipes" por TC alinhou assim) e quadro 320×180 — o merged saía com sobra preta no
    #     começo, "3:14" fora de sincronia em todo clipe e o Source a 600 %. O merged é o subclipe do Avid: imagem e som
    #     cobrem o MESMO trecho, então toda trilha vai de 0 a `dur_t`, e o quadro é o da câmera.
    _alinhar_e_enquadrar(seq, por_novo, cam, dur_t)
    # ⭐ os TRÊS lugares que o Premiere pinta quando o editor troca a cor de um merged (lido no projeto que o autor pintou):
    #   o item da bin (é o que o PAINEL mostra), os clipes do merged e os de cada componente (a câmera e os canais)
    _pintar(mc_m, por_novo)
    _pintar_item(cpi)
    for comp in [cam, *sons]:
        _pintar(comp[0], {_chave(e): e for e in comp})
    # 5. nome, duração, entradas e o TC
    zero = None
    cam_por = {_chave(e): e for e in cam}
    dono_da_fonte: dict[str, str] = {}
    for e in cam + [x for lista in sons for x in lista]:
        if e.tag in ("VideoClip", "AudioClip") and e.find("./Clip/Source") is not None:
            od = e.findtext("./Clip/OriginalDuration")
            if od:
                dono_da_fonte[e.find("./Clip/Source").get("ObjectRef")] = od
    med = next((e for e in cam if e.tag == "Media"), None)
    if med is not None and med.findtext("Start"):
        zero = int(med.findtext("Start")) + img_ini_t
    dur_molde = int(m["seq"].findtext("./Node/Properties/MZ.WorkOutPoint") or 0)
    for e in novos:
        for x in e.iter():
            if x.text == nome_molde:
                x.text = nome
            if dur_molde and x.text == str(dur_molde) and x.tag in ("OriginalDuration", "End", "MZ.WorkOutPoint"):
                x.text = str(dur_t)
        if e.tag in ("VideoClip", "AudioClip") and e.find("./Clip/InPoint") is not None:
            src = e.find("./Clip/Source")
            od = e.find("./Clip/OriginalDuration")
            if od is not None and src is not None and src.get("ObjectRef") in dono_da_fonte:
                od.text = dono_da_fonte[src.get("ObjectRef")]           # a duração do arquivo NOVO, não a do molde
            if src is not None and src.get("ObjectRef") in cam_por:
                e.find("./Clip/InPoint").text = str(img_ini_t)
                e.find("./Clip/OutPoint").text = str(img_ini_t + dur_t)
            else:
                e.find("./Clip/InPoint").text = str(som_ini_t)
                e.find("./Clip/OutPoint").text = str(som_ini_t + dur_t)
            if e.find("./Clip/ClipID") is not None:
                e.find("./Clip/ClipID").text = str(uuid.uuid4())
        if e.tag in ("VideoClipTrackItem", "AudioClipTrackItem") and e.find("ID") is not None:
            e.find("ID").text = str(uuid.uuid4())
        if e.tag == "AudioClipTrack" and e.find("./AudioTrack/ID") is not None:
            e.find("./AudioTrack/ID").text = str(uuid.uuid4())
        for idn in e.findall("./ProjectItem/Node/ID") + e.findall("./Node/ID"):
            if idn.text and idn.text.isdigit():
                idn.text = ids.no()
    props = seq.find("./Node/Properties")
    for tag in ("MZ.InPoint", "MZ.OutPoint"):
        for x in props.findall(tag):
            props.remove(x)
    if zero is not None:
        props.find("MZ.ZeroPoint").text = str(zero)
    mprops = mc_m.find("./Node/Properties")
    if mprops is not None:
        for x in list(mprops):
            if x.tag.startswith("monitor."):
                mprops.remove(x)
    for x in seq.findall("./Node/Properties/*"):
        if x.tag.startswith("monitor.") or x.tag.startswith("MZ.EditLine") or x.tag == "MZ.CTI":
            props.remove(x)
    if seq.find("ID") is not None:
        seq.find("ID").text = str(uuid.uuid4())
    # 6. o que a poda deixou solto sai; o item entra na bin
    alcancados = {_chave(e) for e in _fecho(cpi, {**por, **por_novo}, parar=lambda e: _chave(e) in por)}
    novos = [e for e in novos if _chave(e) in alcancados]
    # ⛔ nada do novo pode apontar a mídia do MOLDE (tocaria o arquivo de outro merged, calado)
    proibidos = deles - set(mapa)
    for e in novos:
        for _x, _a, r in _refs(e):
            if r in proibidos:
                raise CartaErro(f"o merged {nome!r} ficaria apontando um objeto do molde ({por[r].tag} {r}, de {e.tag} {_chave(e)} {_x.tag})")
    destino = bin_alvo if bin_alvo is not None else next(e for e in R if e.tag == "RootProjectItem")
    itens = destino.find(".//Items")
    ET.SubElement(itens, "Item", {"Index": str(len(itens)), "ObjectURef": _chave(cpi)})
    todos = cam + [x for s in sons for x in s] + novos
    for e in todos:
        R.append(e)

    def clipe(lista: list[ET.Element], tag: str) -> str | None:
        mc0 = lista[0]
        for c in mc0.findall("./Clips/Clip"):
            e = next(x for x in lista if _chave(x) == c.get("ObjectRef"))
            if e.tag == tag:
                return _chave(e)
        return None

    return {"maior": ids.n, "cpi": _chave(cpi), "camera": (_chave(cam[0]), clipe(cam, "VideoClip")),
            "canais": [(_chave(s[0]), clipe(s, "AudioClip")) for s in sons], "novos": len(todos)}


def escrever_subclipe(R: ET.Element, por: dict, nome: str, mc_importado: ET.Element, cpi_importado: ET.Element,
                      ini_t: int, fim_t: int, bin_alvo: ET.Element | None = None, piso: int = 0) -> dict:
    """O SUBCLIPE do Premiere (molde `createSubClip(nome, in, out, 1, 1, 1)`, 2026-11-14): a cópia do MasterClip
    importado — `Media` e fontes próprias, `StartBoundary`/`EndBoundary` nas fontes (limites FIXOS, como o subclipe do
    Avid, que não deixa puxar além do recorte), `InPoint`/`OutPoint` nos clipes, o nome — num `ClipProjectItem` novo.
    ⚠️ O `createSubClip` deixou o nome do ITEM igual ao do master e só o do MasterClip novo: aqui os dois levam o nome.
    Devolve {"maior", "cpi", "mc", "video": VideoClip id ou None, "audio": [(AudioClip id, nº de canais)]}."""
    ids = _Ids(R, piso)
    novos = _clonar_grafo(_fecho(mc_importado, por), ids, {})
    mc = novos[0]
    mc.find("Name").text = nome
    node = mc.find("Node")
    if node is None:
        node = ET.Element("Node", {"Version": "1"})
        mc.insert(0, node)
    for x in node.findall("ID"):
        node.remove(x)
    ET.SubElement(node, "ID").text = ids.no()
    for e in novos:
        if e.tag == "ClipLoggingInfo" and e.find("ClipName") is not None:
            e.find("ClipName").text = nome
        if e.tag in ("VideoMediaSource", "AudioMediaSource"):
            # ⛔ DENTRO de `MediaSource/Content`, Start antes de End (o molde). Em `MediaSource` direto o Premiere os
            # descarta CALADO ao regravar, e o subclipe perde os limites (medido na v10, 2026-11-14)
            ct = e.find("./MediaSource/Content")
            for x in ct.findall("StartBoundary") + ct.findall("EndBoundary"):
                ct.remove(x)
            ET.SubElement(ct, "StartBoundary").text = str(ini_t)
            ET.SubElement(ct, "EndBoundary").text = str(fim_t)
        if e.tag in ("VideoClip", "AudioClip"):
            cl = e.find("Clip")
            for tag, v in (("InPoint", ini_t), ("OutPoint", fim_t)):
                el = cl.find(tag)
                if el is None:
                    el = ET.SubElement(cl, tag)
                el.text = str(v)
            if cl.find("ClipID") is not None:
                cl.find("ClipID").text = str(uuid.uuid4())
    cpi = copy.deepcopy(cpi_importado)
    cpi.set("ObjectUID", str(uuid.uuid4()))
    cpi.find("ProjectItem/Name").text = nome
    for idn in cpi.findall("./ProjectItem/Node/ID"):
        idn.text = ids.no()
    cpi.find("MasterClip").set("ObjectURef", _chave(mc))
    destino = bin_alvo if bin_alvo is not None else next(e for e in R if e.tag == "RootProjectItem")
    itens = destino.find(".//Items")
    ET.SubElement(itens, "Item", {"Index": str(len(itens)), "ObjectURef": _chave(cpi)})
    for e in [*novos, cpi]:
        R.append(e)
    por_novo = {_chave(e): e for e in novos}
    video, audio = None, []
    for c in mc.findall("./Clips/Clip"):
        e = por_novo[c.get("ObjectRef")]
        if e.tag == "VideoClip":
            video = _chave(e)
        elif e.tag == "AudioClip":
            audio.append((_chave(e), len(e.findall("./SecondaryContents/SecondaryContentItem")) or 1))
    return {"maior": ids.n, "cpi": _chave(cpi), "mc": _chave(mc), "video": video, "audio": audio}


# ── REAPROVEITAR o que o projeto já tem (autor, 2026-11-14: "reimportar uma timeline não deve criar itens repetidos;
#    se já tem os merged, multicam ou seja lá o que for, deve usar o que já tem") ─────────────────────────────────────
# A identidade é a COMPOSIÇÃO, nunca o nome (o editor renomeia): o arquivo de cada lado, a entrada e a duração. Medido
# antes (26.0.2 Mac): reimportar a mesma timeline levava o projeto de 40 a 76 merged.

def _arquivo_de(clip: ET.Element, por: dict) -> str:
    """O arquivo por trás de um VideoClip/AudioClip (Clip/Source → *MediaSource → Media), normalizado."""
    src = clip.find("./Clip/Source")
    ms = por.get(src.get("ObjectRef")) if src is not None else None
    ref = ms.find(".//Media") if ms is not None else None
    med = por.get(ref.get("ObjectURef")) if ref is not None else None
    if med is None:
        return ""
    import unicodedata
    from .entrega_prproj import sem_prefixo_longo
    c = sem_prefixo_longo(med.findtext("ActualMediaFilePath") or med.findtext("FilePath") or "")
    return unicodedata.normalize("NFC", c.replace("\\", "/")).lower()


def _clipe_do(mc: ET.Element, por: dict, tag: str) -> ET.Element | None:
    for c in mc.findall("./Clips/Clip"):
        e = por.get(c.get("ObjectRef") or "")
        if e is not None and e.tag == tag:
            return e
    return None


def _entrada(cl: ET.Element | None) -> tuple[int, int] | None:
    if cl is None or cl.findtext("./Clip/InPoint") is None or cl.findtext("./Clip/OutPoint") is None:
        return None
    a = int(cl.findtext("./Clip/InPoint"))
    return a, int(cl.findtext("./Clip/OutPoint")) - a


def merged_existentes(R: ET.Element, por: dict) -> dict[tuple, dict]:
    """{assinatura: o mesmo dicionário que `escrever` devolve} para cada merged do projeto. Assinatura: (arquivo da
    câmera, entrada da câmera, (arquivos dos canais, em ordem de trilha), entrada do som, duração)."""
    out: dict[tuple, dict] = {}
    for cpi in R.iter("ClipProjectItem"):
        r = cpi.find("MasterClip")
        mc = por.get(r.get("ObjectURef")) if r is not None else None
        if mc is None:
            continue
        vc = _clipe_do(mc, por, "VideoClip")
        s = vc.find("./Clip/Source") if vc is not None else None
        src = por.get(s.get("ObjectRef")) if s is not None else None
        sq = src.find("./SequenceSource/Sequence") if src is not None else None
        seq = por.get(sq.get("ObjectURef")) if sq is not None else None
        if seq is None or seq.findtext("./Node/Properties/BE.Sequence.IsMergedClip") != "true":
            continue
        comps = [e for e in _fecho(cpi, por) if _e_componente(e)]
        cam = next((e for e in comps if e.find(f"./Node/Properties/{_PROP_TRILHA}") is None), None)
        canais = sorted((e for e in comps if e.find(f"./Node/Properties/{_PROP_TRILHA}") is not None),
                        key=lambda e: int(e.findtext(f"./Node/Properties/{_PROP_TRILHA}")))
        if cam is None or not canais:
            continue
        cv = _clipe_do(cam, por, "VideoClip")
        cas = [_clipe_do(c, por, "AudioClip") for c in canais]
        ec, es = _entrada(cv), _entrada(cas[0])
        if ec is None or es is None or any(a is None for a in cas):
            continue
        chave = (_arquivo_de(cv, por), ec[0], tuple(_arquivo_de(a, por) for a in cas), es[0], ec[1])
        out.setdefault(chave, {"cpi": _chave(cpi), "camera": (_chave(cam), _chave(cv)),
                               "canais": [(_chave(c), _chave(a)) for c, a in zip(canais, cas)], "reaproveitado": True})
    return out


def assinatura_do_merged(camera_mc: ET.Element, canais_mc: list[ET.Element], por: dict, img_ini_t: int,
                         som_ini_t: int, dur_t: int) -> tuple:
    """A assinatura (`merged_existentes`) do merged que `escrever` faria com estes argumentos."""
    cv = _clipe_do(camera_mc, por, "VideoClip")
    cas = [_clipe_do(c, por, "AudioClip") for c in canais_mc]
    return (_arquivo_de(cv, por) if cv is not None else "", img_ini_t,
            tuple(_arquivo_de(a, por) if a is not None else "" for a in cas), som_ini_t, dur_t)


def subclipes_existentes(R: ET.Element, por: dict) -> dict[tuple, dict]:
    """{(arquivo, entrada, saída): o que `escrever_subclipe` devolve} para cada subclipe do projeto (limites fixos nas
    fontes: `StartBoundary`/`EndBoundary`)."""
    out: dict[tuple, dict] = {}
    for cpi in R.iter("ClipProjectItem"):
        r = cpi.find("MasterClip")
        mc = por.get(r.get("ObjectURef")) if r is not None else None
        if mc is None:
            continue
        cl = _clipe_do(mc, por, "VideoClip") or _clipe_do(mc, por, "AudioClip")
        s = cl.find("./Clip/Source") if cl is not None else None
        src = por.get(s.get("ObjectRef")) if s is not None else None
        ct = src.find("./MediaSource/Content") if src is not None else None
        if ct is None or ct.findtext("StartBoundary") is None or ct.findtext("EndBoundary") is None:
            continue
        chave = (_arquivo_de(cl, por), int(ct.findtext("StartBoundary")), int(ct.findtext("EndBoundary")))
        video = _clipe_do(mc, por, "VideoClip")
        audio = [(_chave(e), len(e.findall("./SecondaryContents/SecondaryContentItem")) or 1)
                 for c in mc.findall("./Clips/Clip") for e in [por.get(c.get("ObjectRef") or "")]
                 if e is not None and e.tag == "AudioClip"]
        out.setdefault(chave, {"cpi": _chave(cpi), "mc": _chave(mc), "video": _chave(video) if video is not None else None,
                               "audio": audio, "reaproveitado": True})
    return out


def assinatura_do_subclipe(mc_importado: ET.Element, por: dict, ini_t: int, fim_t: int) -> tuple:
    cl = _clipe_do(mc_importado, por, "VideoClip") or _clipe_do(mc_importado, por, "AudioClip")
    return (_arquivo_de(cl, por) if cl is not None else "", ini_t, fim_t)
