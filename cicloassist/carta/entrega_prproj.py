"""PUXAR TIMELINE no Premiere sem XML: o ENXERTO (banco `protocolos/prproj/escrita.md` §11g; pedido do autor,
2026-11-13, depois da V1 da PRODA_CORTE travar o importador de XML do Premiere 26.0.2).

O caminho, em três passos, cada um medido antes do seguinte:
1. **A mídia no projeto** — o Premiere importa ELE MESMO cada arquivo que a timeline usa (`cicloImportar`), num projeto
   de entrega NOVO e versionado (nunca o do editor por cima), e salva. Um arquivo por chamada: o que travar fica dito.
2. **A sequência escrita** — numa CÓPIA do `.prproj` salvo, os objetos da sequência apontando os itens que o próprio
   Premiere criou (o Premiere só não duplica quando o objeto de mídia É o do projeto, §11g).
3. **Puxada** — `importSequences(cópia, [uid])` para dentro do projeto aberto.
"""

from __future__ import annotations

from .entrega_premiere import ORDEM_DAS_FORMAS, _forma_aqui, trilhas_do_master
from .projeto import CartaErro, Projeto


def arquivos_da_timeline(proj: Projeto, item: dict, forma: str = "avid",
                         trilhas: set[str] | None = None) -> tuple[list[str], dict[str, int]]:
    """(os arquivos que a timeline usa NESTA máquina, na ordem em que aparecem; {nome: clipes} dos que ficam offline).
    `trilhas`: só estas trilhas da timeline ({"V1", "A3"}); None = todas. Um clipe de som leva o arquivo do CANAL dele."""
    if not item.get("timeline"):
        raise CartaErro("este item não é uma timeline")
    ordem = ORDEM_DAS_FORMAS.get(forma, ORDEM_DAS_FORMAS["avid"])
    cache: dict[str, tuple[str, dict[str, str]] | None] = {}
    saida: dict[str, None] = {}
    offline: dict[str, int] = {}
    for tr in item.get("trilhas", []):
        if trilhas is not None and f"{tr['tipo']}{tr['k']}" not in trilhas:
            continue
        audio = tr["tipo"] == "A"
        for c in tr.get("clipes", []):
            m = c.get("midia") or ""
            if m not in cache:
                achou = _forma_aqui(proj, m, ordem)
                cache[m] = None if achou is None else (achou[0], trilhas_do_master(achou[1]) if achou[0] == "avid"
                                                       else {"V1": achou[1][0], "*": achou[1][0]})
            if cache[m] is None:
                offline[m] = offline.get(m, 0) + 1
                continue
            por = cache[m][1]
            a = por.get(f"A{int(c.get('canal') or 1)}" if audio else "V1") or por.get("*")
            if a:
                saida[a] = None
    # ⭐ o subclipe SINCRONIZADO vira merged, e o merged leva os DOIS lados — a câmera e todos os canais dele —, mesmo
    # o que a timeline não toca (medido: o `11-01-01` da PRODA_CORTE.00.2 só tem o som na timeline)
    if forma == "avid":
        from . import itens as _itens
        usados = {c["item"] for tr in item.get("trilhas", []) for c in tr.get("clipes", []) if c.get("item")}
        for _, it in _itens.todos(proj):
            if it["id"] not in usados or it.get("tipo") != "sincronizado":
                continue
            for lado, chaves in (("imagem", ["V1"]), ("som", [f"A{k}" for k in it["som"].get("canais") or [1]])):
                achou = _forma_aqui(proj, it[lado]["midia"], ordem)
                if achou is not None and achou[0] == "avid":
                    t = trilhas_do_master(achou[1])
                    for k in chaves:
                        if t.get(k):
                            saida[t[k]] = None
    return list(saida), offline


# ── passo 2: a sequência escrita no `.prproj` (o MOLDE do próprio Premiere, medido no 26.0.2 Mac, 2026-11-13) ────────
#
# O que o 26.0.2 grava para um clipe de vídeo na trilha (sequência montada por ele, `cicloMontar`, e salva):
#   VideoClipTrackItem ─ ClipTrackItem{ComponentOwner→VideoComponentChain, TrackItem{Start, End}, SubClip}
#                      ─ FrameRect = o raster da MÍDIA
#   SubClip ─ Clip→VideoClip (NOVO por clipe, ClipID novo), MasterClip→o do item da bin, Name, OrigChGrp 0
#   VideoClip ─ a cópia do VideoClip do master (o mesmo Source e Markers) com InPoint/OutPoint em ticks, contados do
#               INÍCIO DA MÍDIA (não do TC): 254016000000 = 1 s depois do primeiro quadro.
# ⛔ O `Start` some quando é 0. Um tick = 1/254016000000 s; o quadro a 23,976 = 10594584000 ticks.

import copy
import os
import gzip
import uuid
import xml.etree.ElementTree as ET

TICKS_POR_SEGUNDO = 254016000000


def _ticks_por_quadro(fps) -> int:
    from fractions import Fraction
    f = Fraction(str(fps))
    t = Fraction(TICKS_POR_SEGUNDO) / f
    if t.denominator != 1:
        raise CartaErro(f"a taxa {fps} não cai num número inteiro de ticks")
    return int(t)


def _ler_prproj(caminho: str) -> ET.Element:
    with open(caminho, "rb") as f:
        dados = f.read()
    if dados[:2] == b"\x1f\x8b":
        dados = gzip.decompress(dados)
    return ET.fromstring(dados.decode("utf-8"))


def _gravar_prproj(raiz: ET.Element, caminho: str) -> None:
    import struct
    import zlib
    dados = ('<?xml version="1.0" encoding="UTF-8" ?>\n' + ET.tostring(raiz, encoding="unicode")).encode("utf-8")
    co = zlib.compressobj(6, zlib.DEFLATED, -zlib.MAX_WBITS)
    corpo = co.compress(dados) + co.flush()
    with open(caminho, "wb") as f:   # o cabeçalho que o Premiere escreve (banco prproj/relink-e-geometria.md §0)
        f.write(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x13" + corpo
                + struct.pack("<II", zlib.crc32(dados) & 0xFFFFFFFF, len(dados) & 0xFFFFFFFF))


def _chave(e: ET.Element) -> str | None:
    return e.get("ObjectID") or e.get("ObjectUID")


def _refs(e: ET.Element):
    for x in e.iter():
        for a in ("ObjectRef", "ObjectURef"):
            if x.get(a):
                yield x, a, x.get(a)


#: ⛔ O Premiere 26.5 (Windows, medido 2026-11-18) grava o `ActualMediaFilePath` com o prefixo de caminho longo (o
#: `FilePath`, não): sem tirá-lo, nenhum arquivo da timeline "estava no projeto" e o Importar parava antes do molde.
from ..caminhos import sem_prefixo_longo  # noqa: E402


def _norm(p: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", sem_prefixo_longo(str(p))).replace("\\", "/").lower()


def _midia_de(por: dict, clip: ET.Element) -> tuple[ET.Element | None, str]:
    """(o Media, o caminho) por trás de um VideoClip/AudioClip: Clip/Source → *MediaSource → Media."""
    src = clip.find("./Clip/Source")
    ms = por.get(src.get("ObjectRef")) if src is not None else None
    med_ref = ms.find(".//Media") if ms is not None else None
    med = por.get(med_ref.get("ObjectURef")) if med_ref is not None else None
    if med is None:
        return None, ""
    return med, med.findtext("ActualMediaFilePath") or med.findtext("FilePath") or ""


def midia_do_projeto(raiz: ET.Element) -> dict[str, dict]:
    """{arquivo (normalizado): {mc, video_clip, frame_rect, audio: [(mc, audio_clip, índice do clipe de som no master,
    nº de canais)]}} — os itens de mídia que o Premiere criou no projeto.
    ⚠️ Medido no 26.0.2 Mac (2026-11-14): o OP-Atom de IMAGEM junta os `_A0N` irmãos num item só, mas cada `_A0N`
    importado sozinho (master só de som, ou o canal de um master com imagem) vira um item MONO à parte; o WAV estéreo
    vira UM clipe de som com 2 canais."""
    por = {_chave(e): e for e in raiz if _chave(e)}
    out: dict[str, dict] = {}
    for cpi in raiz.iter("ClipProjectItem"):
        r = cpi.find(".//MasterClip")
        mc = por.get(r.get("ObjectURef")) if r is not None else None
        if mc is None:
            continue
        n_audio = 0
        for c in mc.findall("./Clips/Clip"):
            cl = por.get(c.get("ObjectRef") or "")
            if cl is None:
                continue
            med, arq = _midia_de(por, cl)
            if cl.tag == "VideoClip" and med is not None:
                vs_ref = med.find("VideoStream")
                vs = por.get(vs_ref.get("ObjectRef") or "") if vs_ref is not None else None
                d = out.setdefault(_norm(arq), {})
                d.update({"mc": mc.get("ObjectUID"), "cpi": cpi.get("ObjectUID"), "video_clip": _chave(cl),
                          "frame_rect": (vs.findtext("FrameRect") if vs is not None else None)})
            elif cl.tag == "AudioClip":
                if med is not None:
                    canais = len(cl.findall("./SecondaryContents/SecondaryContentItem")) or 1
                    out.setdefault(_norm(arq), {}).setdefault("audio", []).append(
                        (mc.get("ObjectUID"), _chave(cl), n_audio, canais))
                n_audio += 1
    return out


# O que o 26.0.2 grava para um clipe de SOM (moldes "MOLDE SOM" e "MOLDE GANHO", montados por ele, 2026-11-14):
#   AudioClipTrackItem ─ ClipTrackItem{ComponentOwner→AudioComponentChain, TrackItem{Start, End}, SubClip}
#   SubClip ─ Clip→AudioClip NOVO (a cópia do do master, sem InUse), MasterClip, Name, OrigChGrp = o nº do clipe de som
#   AudioClip ─ SecondaryContents com UM SecondaryContent{Content = o AudioMediaSource, ChannelIndex = o canal DENTRO da
#               fonte}, layout mono — é assim que o canal 2 de um master de 2 canais é escolhido (o mesmo Source).
#   AudioComponentChain sem ganho: DefaultVol; com ganho: um AudioFilterComponent "Internal Volume Mono" com o "Nível"
#   CRU = 10^((dB−15)/20) (0 dB = 0,1778; o teto 1 = +15 dB — medido pela API: o padrão lido foi 0,17782793939114).

#: nada mais que isto se escreve no Nível (o Premiere corta em 1 = +15 dB)
TETO_DO_NIVEL = 1.0
#: o teto do Volume do clipe no Premiere (o Level 1,0 = +15 dB); acima, o resto vai no Audio Gain (`<Gain>`)
GANHO_MAXIMO_DO_VOLUME_DB = 15.0


def nivel_do_volume(db: float) -> float:
    return min(TETO_DO_NIVEL, 10 ** ((float(db) - 15.0) / 20.0))


def molde_de_esticar(R: ET.Element, por: dict) -> ET.Element | None:
    """A cadeia (`VideoComponentChain`) de um clipe de vídeo com o Motion em escala NÃO uniforme — o molde do stretch,
    feito pelo Premiere (`cicloMontar`, linha `esc`). Reconhecido pelo Uniform Scale DESLIGADO (o param de nome em
    branco, ou "Uniform Scale", com `false`). ⚠️ O 23.2 renomeia "Scale" → "Scale Height" ao salvar (banco
    `prproj/estruturas.md`); o 26.5 NÃO (medido 2026-11-20): a altura é "Scale" ou "Scale Height"."""
    for e in R:
        if e.tag != "VideoClipTrackItem" or e.find("./ClipTrackItem/ComponentOwner/Components") is None:
            continue
        cad = por.get(e.find("./ClipTrackItem/ComponentOwner/Components").get("ObjectRef"))
        if cad is None:
            continue
        for c in cad.iter("Component"):
            comp = por.get(c.get("ObjectRef"))
            if comp is None or comp.findtext("MatchName") != "AE.ADBE Motion":
                continue
            pars = [por[p.get("ObjectRef")] for p in comp.iter("Param") if p.get("ObjectRef") in por]
            uniforme = next((x for x in pars if (x.findtext("Name") or "").strip() in ("", "Uniform Scale")
                             and ",false," in (x.findtext("StartKeyframe") or "") + ","), None)
            if uniforme is not None and any(x.findtext("Name") == "Scale Width" for x in pars):
                return cad
    return None


def _primeiro_cc(c: dict) -> dict | None:
    from .cor_prproj import cor_do_efeito
    return next((e for e in c.get("efeitos") or [] if cor_do_efeito(e)), None)


def cor_do_clipe(c: dict) -> dict | None:
    """O Color Correction do Avid que se traduz INTEIRO (`{sat, curva}`, `cor_prproj.cor_do_efeito`) — o 1º do clipe."""
    from .cor_prproj import cor_do_efeito
    return next((cc for cc in (cor_do_efeito(e) for e in c.get("efeitos") or []) if cc), None)


#: o ProcAmp neutro (ParameterID → valor): o molde só serve se os outros controles estiverem no padrão
_PROCAMP_NEUTRO = {"1": 0.0, "2": 100.0, "3": 0.0}


def molde_de_cor(R: ET.Element, por: dict) -> list[ET.Element] | None:
    """Os componentes ProcAmp e Lumetri, NA ORDEM da cadeia, de um clipe da sequência de MOLDES da Carta (`cicloMontar`,
    linha `cor`) — ou None. ⛔ Só da sequência de moldes: um clipe do editor com ProcAmp + Lumetri já graduados levaria a
    grade dele para todo clipe com CC. E o ProcAmp tem de estar neutro (Brightness 0, Contrast 100, Hue 0)."""
    from .moldes_prproj import NOME_DOS_MOLDES
    for seq in R:
        if seq.tag != "Sequence" or seq.findtext("Name") != NOME_DOS_MOLDES:
            continue
        for tg in seq.iter("TrackGroup"):
            s = tg.find("Second")
            vtg = por.get(s.get("ObjectRef")) if s is not None else None
            if vtg is None or vtg.tag != "VideoTrackGroup":
                continue
            tracks = vtg.find("./TrackGroup/Tracks")
            for tref in (list(tracks) if tracks is not None else []):
                tr = por.get(tref.get("ObjectURef"))
                tis = tr.find("./ClipTrack/ClipItems/TrackItems") if tr is not None else None
                for ti in (list(tis) if tis is not None else []):
                    e = por.get(ti.get("ObjectRef"))
                    if e is None or e.find("./ClipTrackItem/ComponentOwner/Components") is None:
                        continue
                    comps = [c for c in _componentes(por, e) if c.findtext("MatchName") in ("AE.ADBE ProcAmp", "AE.ADBE Lumetri")]
                    nomes = [c.findtext("MatchName") for c in comps]
                    if sorted(nomes) != ["AE.ADBE Lumetri", "AE.ADBE ProcAmp"]:
                        continue
                    pa = comps[nomes.index("AE.ADBE ProcAmp")]
                    vals = {}
                    for p in pa.iter("Param"):
                        par = por.get(p.get("ObjectRef"))
                        sk = (par.findtext("StartKeyframe") or "").split(",") if par is not None else []
                        if par is not None and len(sk) > 1:
                            vals[par.findtext("ParameterID")] = sk[1]
                    try:
                        if all(abs(float(vals.get(k, "nan")) - v) < 1e-6 for k, v in _PROCAMP_NEUTRO.items()):
                            return comps
                    except ValueError:
                        continue
    return None


def _cor_na_cadeia(R: ET.Element, por: dict, molde: list[ET.Element], cadeia: ET.Element, cc: dict, novo_id,
                   novos: list) -> None:
    """ProcAmp (com a Saturation do Avid) e/ou Lumetri (com a curva do Avid em R, G e B) clonados do molde e pendurados
    no FIM da cadeia do clipe, na ordem do molde (a da bancada medida)."""
    from .cor_prproj import PARAM_CURVA, blob_com_a_curva, curva_lumetri_do_mc
    import base64 as _b64
    lista = cadeia.find("./ComponentChain/Components")
    if lista is None:
        cc_el = cadeia.find("ComponentChain")
        if cc_el is None:
            cc_el = ET.SubElement(cadeia, "ComponentChain", {"Version": "3"})
        lista = ET.SubElement(cc_el, "Components", {"Version": "1"})
    for comp in molde:
        mn = comp.findtext("MatchName")
        if (mn == "AE.ADBE ProcAmp" and cc.get("sat") is None) or (mn == "AE.ADBE Lumetri" and not cc.get("curva")):
            continue
        ini = len(novos)
        novo = _clonar(comp, por, novo_id, novos)
        pars = {x.findtext("ParameterID"): x for x in novos[ini:] if x is not novo}
        if mn == "AE.ADBE ProcAmp":
            _valor_do_param(pars["4"], repr(float(cc["sat"])))
        else:
            el = pars[PARAM_CURVA].find("StartKeyframeValue")
            pontos, _erro = curva_lumetri_do_mc([tuple(p) for p in cc["curva"]])
            b64 = _b64.b64encode(blob_com_a_curva(_b64.b64decode(_valor_binario(R, el)), pontos)).decode()
            el.text = b64
            el.set("BinaryHash", _hash_binario(b64))
        ET.SubElement(lista, "Component", {"Index": str(len(lista)), "ObjectRef": novo.get("ObjectID")})


def _valor_do_param(par: ET.Element, valor: str) -> None:
    """O valor ESTÁTICO de um param do Motion: o 2º campo do `StartKeyframe` (e o `CurrentValue`, se houver)."""
    sk = par.find("StartKeyframe")
    if sk is not None and sk.text:
        campos = sk.text.split(",")
        campos[1] = valor
        sk.text = ",".join(campos)
    cv = par.find("CurrentValue")
    if cv is not None:
        cv.text = valor


def estabilizacao_do_efeito(e: dict) -> dict | None:
    """O rastreio do Stabilize do Avid (o `params.estabilizacao` que a bin dá: um ponto, remover tremor) — ou None."""
    if str(e.get("nome") or e.get("name") or "") != "EFF2_STABILIZE":
        return None
    d = (e.get("params") or {}).get("estabilizacao")
    return d if isinstance(d, dict) and d.get("x") else None


#: o PanVolumeEffect: o pan no CENTRO (0 = esquerda, 32768 = direita — `hipotese` pelos 153 clipes da PRODA, todos 16384)
PAN_CENTRO = 16384


def _efeitos_sem_par(c: dict, audio: bool, rot: str, fora, offline: bool = False, cor_vai: bool = False) -> None:
    """O que o clipe tem e o Premiere não recebe, dito pelo nome. Decisão do autor (2026-11-15): no SOM, volume, ganho,
    transição e pan têm par; plugin do MC (AudioSuite: D-Verb…) não roda no Premiere nem o contrário (AAX × VST3/AU) —
    "sem correspondência". O pan fora do centro ainda não é escrito (nenhum caso medido): dito, nunca calado."""
    sufixo = f"({rot}{', clipe offline' if offline else ''})"
    for e in c.get("efeitos") or []:
        nome = e.get("rotulo") or e.get("nome")
        if e.get("categoria") == "gain":
            pan = (e.get("params") or {}).get("pan")
            if audio and pan is not None and int(pan) != PAN_CENTRO:
                fora(f"pan fora do centro: ainda não escrito {sufixo}")
        elif cor_vai and not audio and not offline and e is _primeiro_cc(c):
            continue                       # o Color Correction vai: ProcAmp + Lumetri (`_cor_na_cadeia`)
        elif estabilizacao_do_efeito(e) is not None and not audio:
            if offline:
                fora(f"efeito {nome} {sufixo}")
        elif audio:
            fora(f"efeito de áudio {nome}: sem correspondência no Premiere {sufixo}")
        elif offline:
            fora(f"efeito {nome} {sufixo}")
        else:
            fora(f"efeito {nome} ({rot})")


def escala_do_stretch(midia: str | None, quadro: tuple[int, int]) -> tuple[float, float] | None:
    """(largura %, altura %) do stretch do Avid — a imagem inteira deformada para o quadro da sequência; None se a
    mídia já tem o tamanho do quadro (o stretch não muda nada) ou se o tamanho dela não é conhecido."""
    try:
        _x, _y, w, h = (int(float(v)) for v in str(midia).split(","))
    except (TypeError, ValueError):
        return None
    if (w, h) == tuple(quadro) or not w or not h:
        return None
    return round(quadro[0] / w * 100, 6), round(quadro[1] / h * 100, 6)


def _moldes_de_som(R: ET.Element, por: dict) -> dict[str, ET.Element]:
    """{"sem_ganho": track item, "com_ganho": track item} — clipes de som MONO que o próprio Premiere pôs numa
    sequência deste projeto (qualquer uma)."""
    achados: dict[str, ET.Element] = {}
    def ref(e: ET.Element | None, caminho: str) -> ET.Element | None:
        x = e.find(caminho) if e is not None else None   # ⛔ nunca `find(...) or`: elemento sem filhos é falso
        return por.get(x.get("ObjectRef") or "") if x is not None else None

    for ti in R.iter("AudioClipTrackItem"):
        if _chave(ti) not in por:
            continue
        ch, sub = ref(ti, "./ClipTrackItem/ComponentOwner/Components"), ref(ti, "./ClipTrackItem/SubClip")
        if ch is None or sub is None:
            continue
        ac = ref(sub, "Clip")
        if ac is None or ac.findtext("AudioChannelLayout") != '[{"channellabel":0}]':
            continue
        comps = [por.get(c.get("ObjectRef")) for c in ch.findall("./ComponentChain/Components/Component")]
        if not comps and ch.findtext("DefaultVol") == "true":
            achados.setdefault("sem_ganho", ti)
        elif len(comps) == 1 and comps[0] is not None and comps[0].findtext("FilterMatchName") == "Internal Volume Mono":
            achados.setdefault("com_ganho", ti)
    return achados


#: a transição do Avid → a do Premiere que faz o mesmo (o molde, achado pelo MatchName, que não muda com o idioma)
TRANSICAO_DO_AVID = {"EFF2_BLEND_DISSOLVE": ("V", "AE.AE_Impact_Dissolve"),
                     "BLEND_AUDIO_DISSOLVE": ("A", "Constant Power")}


def _moldes_de_transicao(R: ET.Element) -> dict[str, ET.Element]:
    """{"V": Cross Dissolve, "A": Potência constante} — transições de DOIS lados que o próprio Premiere pôs numa
    sequência deste projeto (o molde: `cicloMontar` com a linha `tr`)."""
    achados: dict[str, ET.Element] = {}
    for e in R:
        if e.tag not in ("VideoTransitionTrackItem", "AudioTransitionTrackItem"):
            continue
        tti = e.find("TransitionTrackItem")
        if tti is None or tti.findtext("HasOutgoingClip") != "true" or tti.findtext("HasIncomingClip") != "true":
            continue
        for lado, mn in TRANSICAO_DO_AVID.values():
            if tti.findtext("MatchName") == mn and (e.tag[0] == "V") == (lado == "V"):
                achados.setdefault(lado, e)
    return achados


def _transicoes_da_trilha(transicoes: list[dict], escritos: list[dict], audio: bool, moldes: dict, fora,
                          rot: str, tpf: int = 1, offline: list[tuple[int, int]] | None = None) -> list[dict]:
    """Pareia cada transição do Avid com os clipes ESCRITOS e acerta o tempo deles no modelo do Premiere.

    Avid: A vai até o FIM da transição e B começa no INÍCIO dela (sobrepostos). Premiere: A acaba no corte, B começa
    no corte (com a entrada atrasada no mesmo tanto) e a transição cobre o mesmo trecho, `Alignment` = corte − início.
    Um lado só (o fade do/para o vazio): o clipe fica como está e a transição vai na cabeça ou na cauda dele.
    Devolve [{"x", "a", "b", "corte"}] em ordem de tempo. O que não dá para levar fica de FORA, dito."""
    lado = "A" if audio else "V"
    out = []
    for x in sorted(transicoes, key=lambda x: int(x["inicio_q"])):
        ini, fim, corte = int(x["inicio_q"]), int(x["fim_q"]), int(x["corte_q"])
        tipo = TRANSICAO_DO_AVID.get(x.get("efeito") or "")
        if tipo is None or tipo[0] != lado:
            fora(f"transição {x.get('efeito') or '?'} ({rot})")
            continue
        if lado not in moldes:
            fora(f"transição (sem molde) ({rot})")
            continue
        a = next((w for w in escritos if w["fim"] == fim and w["ini"] < ini and w["cauda"] is None), None)
        b = next((w for w in escritos if w["ini"] == ini and w["fim"] > fim and w["cabeca"] is None), None)
        if a is None and b is None:
            # o clipe dela existe e está OFFLINE (a mídia não está nesta máquina) — é outra coisa que "sem clipe"
            de_offline = any(o_fim == fim or o_ini == ini for o_ini, o_fim in (offline or []))
            fora(f"transição de clipe offline ({rot})" if de_offline else f"transição sem clipe escrito ({rot})")
            continue
        if a is not None and b is not None:
            if not (a["ini"] < corte < b["fim"]):
                fora(f"transição com o corte fora dos clipes ({rot})")
                continue
            a["fim"] = corte
            b["in_t"] += round((corte - b["ini"]) * tpf * (b["vel"] or 1.0))   # a mídia anda na velocidade do clipe
            b["ini"] = corte
            a["cauda"] = b["cabeca"] = "?"
            out.append({"x": x, "a": a, "b": b, "corte": corte})
        elif b is not None:      # do vazio para B: B já começa no início da transição
            b["cabeca"] = "?"
            out.append({"x": x, "a": None, "b": b, "corte": ini})
        else:                    # de A para o vazio: A já acaba no fim dela
            a["cauda"] = "?"
            out.append({"x": x, "a": a, "b": None, "corte": fim})
    return out


TICKS_POR_SEGUNDO = 254016000000


def velocidade_do_clipe(c: dict, fps) -> dict:
    """O que o MotionEffect do Avid vira no Premiere (molde `MOLDE VELOCIDADE`, 2026-11-14):
    {"vel": PlaybackSpeed ou None, "fonte_fps": a taxa em que `entrada_q` conta, "interp": TimeInterpolationType ou None}
    ou {"fora": motivo}. Leitor do Conformar: `[1000, 1001]` com a curva zerada é CONFORMAÇÃO de taxa (fonte a 24 numa
    sequência 23,976: tempo REAL, não velocidade); o resto, a curva que o Avid integrou (`mapa`)."""
    from fractions import Fraction
    v = c.get("velocidade")
    taxa = Fraction(str(fps))
    if not v:
        return {"vel": None, "fonte_fps": taxa, "interp": None}
    if v.get("classe") == "native":
        razao = Fraction(float(v.get("razao") or 1)).limit_denominator(100000)
        if razao <= 0:
            return {"fora": "velocidade (conformação sem razão)"}
        return {"vel": None, "fonte_fps": taxa / razao, "interp": None}
    if v.get("tipo") != "constant":
        return {"fora": f"velocidade variável ({v.get('tipo')})"}
    mapa = v.get("mapa") or []
    if len(mapa) < 2 or not mapa[-1][0]:
        return {"fora": "velocidade sem mapa"}
    vel = (float(mapa[-1][1]) - float(mapa[0][1])) / (float(mapa[-1][0]) - float(mapa[0][0]))
    if vel <= 0:
        return {"fora": "velocidade ao contrário ou congelada"}
    interp = {"optical_flow": "2", "blend": "1"}.get(str(v.get("retime") or ""))
    return {"vel": vel, "fonte_fps": taxa, "interp": interp}


def _clonar(e: ET.Element, por: dict, novo_id, novos: list) -> ET.Element:
    """Cópia de `e` e de TUDO que ele aponta por ObjectRef (ids novos); ObjectURef (MasterClip, trilha) fica igual."""
    c = copy.deepcopy(e)
    if c.get("ObjectID"):
        c.set("ObjectID", novo_id())
    for x in c.iter():
        r = x.get("ObjectRef")
        if r and r in por:
            x.set("ObjectRef", _chave(_clonar(por[r], por, novo_id, novos)))
    novos.append(c)
    return c


def _vincular(seq: ET.Element, clipes: list[dict], novo_id, novos: list, rel: dict) -> None:
    """O VÍNCULO (`Link`, molde: o merged posto na timeline pelo próprio Premiere), um TRECHO por vínculo (autor,
    2026-11-14: "se houver corte, o trecho perde o link"):
    1. o GRUPO de som = os canais do mesmo take, em sincronia, que começam e terminam JUNTOS (um pedaço de edição) —
       vinculado entre si mesmo sem imagem;
    2. a imagem entra em UM grupo só: o do mesmo merged/master, em sincronia, com a MAIOR sobreposição a ela (o som que
       começa um pouco depois ou vai um pouco além continua dela). Os outros grupos debaixo dela ficam só entre si.
    Banco `prproj/escrita.md` §3: casar por TEMPO, nunca um Link gigante (deixa o vídeo inselecionável)."""
    grupos: dict[tuple, list[dict]] = {}
    for a in (x for x in clipes if x["audio"]):
        grupos.setdefault((a["chave"], a["sinc"], a["ini"], a["fim"]), []).append(a)
    da_imagem: dict[tuple, dict] = {}
    for v in sorted((x for x in clipes if not x["audio"]), key=lambda x: x["ini"]):
        cand = [(min(v["fim"], k[3]) - max(v["ini"], k[2]), -k[2], k) for k in grupos
                if k[0] == v["chave"] and k[1] == v["sinc"] and k[2] < v["fim"] and v["ini"] < k[3]
                and k not in da_imagem]
        if cand:
            da_imagem[max(cand)[2]] = v
    links = []
    for k in sorted(grupos, key=lambda k: (k[2], k[3])):
        membros = ([da_imagem[k]] if k in da_imagem else []) + sorted(grupos[k], key=lambda a: a["ti"])
        if len(membros) < 2:
            continue
        lk = ET.Element("Link", {"ObjectID": novo_id(), "ClassID": "149d4ea5-a7d4-4b34-9bb7-16d783904bf2",
                                 "Version": "1"})
        tis = ET.SubElement(ET.SubElement(lk, "TrackItemGroup", {"Version": "1"}), "TrackItems", {"Version": "1"})
        for i, x in enumerate(membros):
            ET.SubElement(tis, "TrackItem", {"Index": str(i), "ObjectRef": x["ti"]})
        links.append((lk, len(membros)))
    if not links:
        return
    lc = seq.find("./PersistentGroupContainer/LinkContainer")
    if lc is None:
        pgc = seq.find("PersistentGroupContainer")
        if pgc is None:
            pgc = ET.SubElement(seq, "PersistentGroupContainer", {"Version": "1"})
        lc = ET.SubElement(pgc, "LinkContainer", {"Version": "1"})
    lista = lc.find("Links")
    if lista is None:
        lista = ET.SubElement(lc, "Links", {"Version": "1"})
    for lk, _n in links:
        ET.SubElement(lista, "Link", {"Index": str(len(lista)), "ObjectRef": lk.get("ObjectID")})
        novos.append(lk)
    rel["vinculos"] = len(links)
    rel["vinculados"] = sum(n for _lk, n in links)
    rel["vinculos_com_imagem"] = len(da_imagem)


def _os_merged(proj: Projeto, R: ET.Element, por: dict, item: dict, trilhas: list[dict], midia: dict, arquivos_de,
               tpf: int, rel: dict, prox: list | None = None) -> dict[str, dict]:
    """Um MERGED (`merged_prproj`) por subclipe SINCRONIZADO que a timeline usa. Devolve {id do item: {"V": info,
    "A": {canal: info}}} no formato de `midia_do_projeto`, apontando os COMPONENTES. Sem molde, ou sem a mídia de um
    lado no projeto: o clipe vai pela mídia nativa, e é dito (`merged_fora`)."""
    from . import itens as _itens
    from . import merged_prproj as _mp
    usados = {c["item"] for t in trilhas for c in t.get("clipes", []) if c.get("item")}
    if not usados:
        return {}
    todos = {d["id"]: d for _, d in _itens.todos(proj)}
    out: dict[str, dict] = {}
    # ⭐ o que o projeto JÁ tem (o do editor, copiado): reimportar não repete merged nem subclipe (autor, 2026-11-14)
    subs_ja = _mp.subclipes_existentes(R, por)
    merged_ja = _mp.merged_existentes(R, por)
    # os RECORTES (subclipe de UM master) → subclipe do Premiere (autor: n'PRODUCAO-A, a diária 01 na praia, sem som
    # direto — o Premiere não faz merged sem casamento, e o subclipe leva o nome que veio do Avid)
    for iid, it in sorted(((i, todos[i]) for i in usados if i in todos and todos[i].get("tipo") == "recorte"),
                          key=lambda x: x[1].get("nome") or ""):
        nome = it.get("nome") or iid
        achou = arquivos_de(it["midia"])
        arq = achou[1].get("V1") if achou and achou[0] == "avid" else None
        info = midia.get(_norm(arq or "")) or {}
        if not info.get("mc") or not info.get("cpi"):
            rel["subclipes_fora"][nome] = "a imagem do master não está no projeto (vai pela mídia nativa)"
            continue
        ini_t, fim_t = int(it["entrada_q"]) * tpf, int(it["saida_q"]) * tpf
        r = subs_ja.get(_mp.assinatura_do_subclipe(por[info["mc"]], por, ini_t, fim_t))
        if r is not None:                      # ⭐ o projeto já tem este recorte: usa o dele (autor, 2026-11-14)
            rel["subclipes_reaproveitados"] = rel.get("subclipes_reaproveitados", 0) + 1
        else:
            r = _mp.escrever_subclipe(R, por, nome, por[info["mc"]], por[info["cpi"]], ini_t, fim_t,
                                      piso=prox[0] if prox else 0)
            por.update({_chave(e): e for e in R if _chave(e) and _chave(e) not in por})
            if prox:
                prox[0] = max(prox[0], r["maior"])
        a = {"audio": [(r["mc"], ac, k, n) for k, (ac, n) in enumerate(r["audio"])]} if r["audio"] else None
        out[iid] = {"V": {"mc": r["mc"], "video_clip": r["video"], "frame_rect": info.get("frame_rect")},
                    "A": {k: a for k in range(1, 1 + sum(n for _ac, n in r["audio"]))} if a else {}}
        rel["subclipes"] += 1
    sinc = {i: todos[i] for i in usados if i in todos and todos[i].get("tipo") == "sincronizado"}
    if not sinc:
        return out
    m = _mp.molde(R, por)
    if m is None:
        rel["merged_fora"]["sem molde de merged no projeto"] = len(sinc)
        return out
    for iid, it in sorted(sinc.items(), key=lambda x: x[1].get("nome") or ""):
        nome = it.get("nome") or iid
        cam, som = arquivos_de(it["imagem"]["midia"]), arquivos_de(it["som"]["midia"])
        canais = list(it["som"].get("canais") or [1])
        arq_cam = cam[1].get("V1") if cam and cam[0] == "avid" else None
        arqs_som = [som[1].get(f"A{k}") for k in canais] if som and som[0] == "avid" else []
        info_cam = midia.get(_norm(arq_cam or "")) or {}
        infos_som = [(midia.get(_norm(a or "")) or {}).get("audio") for a in arqs_som]
        if not info_cam.get("mc") or not arqs_som or not all(infos_som):
            rel["merged_fora"][nome] = "a mídia de um dos lados não está no projeto (vai pela mídia nativa)"
            continue
        cam_mc, canais_mc = por[info_cam["mc"]], [por[a[0][0]] for a in infos_som]
        img_t, som_t, dur_t = int(it["imagem"]["inicio_q"]) * tpf, int(it["som"]["inicio_q"]) * tpf, int(it["duracao_q"]) * tpf
        r = merged_ja.get(_mp.assinatura_do_merged(cam_mc, canais_mc, por, img_t, som_t, dur_t))
        if r is not None:                      # ⭐ o projeto já tem este merged: usa o dele (autor, 2026-11-14)
            rel["merged_reaproveitados"] = rel.get("merged_reaproveitados", 0) + 1
        else:
            try:
                r = _mp.escrever(R, por, m, nome, cam_mc, canais_mc, img_t, som_t, dur_t, piso=prox[0] if prox else 0)
            except CartaErro as e:
                rel["merged_fora"][nome] = str(e)
                continue
            por.update({_chave(e): e for e in R if _chave(e) and _chave(e) not in por})
            if prox:
                prox[0] = max(prox[0], r["maior"])
        out[iid] = {"V": {"mc": r["camera"][0], "video_clip": r["camera"][1], "frame_rect": info_cam.get("frame_rect")},
                    "A": {k: {"audio": [(uid, ac, 0, 1)]} for k, (uid, ac) in zip(canais, r["canais"])}}
        rel["merged"] += 1
    return out


def _renomear_item_da_sequencia(R: ET.Element, seq: ET.Element, nome: str) -> int:
    """O nome que o Premiere MOSTRA é o do item do projeto, não o `Sequence/Name` (medido no 26.0.2 Mac, 2026-11-14: a
    timeline entrou no projeto do editor como "MOLDES (Ciclo Assist)"). A cadeia: Sequence ← *SequenceSource ←
    VideoClip/AudioClip (`Clip/Source`) ← MasterClip (`Clips`) ← ClipProjectItem. Renomeia o master e o item; devolve
    quantos itens."""
    uid = seq.get("ObjectUID")
    fontes = {_chave(e) for e in R if e.tag.endswith("SequenceSource")
              and any(x.get("ObjectURef") == uid for x in e.iter("Sequence"))}
    clipes = {_chave(e) for e in R if e.tag in ("VideoClip", "AudioClip")
              and any(x.get("ObjectRef") in fontes for x in e.iter("Source"))}
    masters = [e for e in R if e.tag == "MasterClip"
               and any(c.get("ObjectRef") in clipes for c in e.findall("./Clips/Clip"))]
    n = 0
    for mc in masters:
        if mc.find("Name") is not None:
            mc.find("Name").text = nome
        for cpi in R.iter("ClipProjectItem"):
            r = cpi.find("MasterClip")
            if r is not None and r.get("ObjectURef") == mc.get("ObjectUID"):
                x = cpi.find("./ProjectItem/Name")
                if x is not None:
                    x.text = nome
                    n += 1
    return n


# ── o TÍTULO (2026-11-20): o gráfico de texto que o Premiere fez, clonado com o texto do Avid ──────────────────────
#
# ⛔ No 26 o `importMGT` do Basic Title põe um gráfico VAZIO (banco `prproj/titulo-essential-graphics.md`): o molde é
# um gráfico com camada de texto feito pelo próprio Premiere (`carta/moldes/titulo 26.prproj`, importado na CÓPIA).
# Cada título ganha o SEU master e a SUA mídia sintética, como o Premiere faz ao criar um gráfico.

def titulo_do_trecho(s: dict) -> dict | None:
    """O bloco `titulo` de um trecho `sem_clipe` da timeline (o efeito de categoria título), ou None."""
    for e in s.get("efeitos") or []:
        if (e.get("category") or e.get("categoria")) == "title":
            t = (e.get("params") or {}).get("titulo")
            if t and any((c.get("texto") or "").strip() for c in t.get("caixas") or []):
                return t
    return None


def _componentes(por: dict, ti: ET.Element) -> list[ET.Element]:
    cad = por.get(ti.find("./ClipTrackItem/ComponentOwner/Components").get("ObjectRef"))
    return [por[c.get("ObjectRef")] for c in (cad.iter("Component") if cad is not None else [])
            if c.get("ObjectRef") in por]


def molde_de_titulo(R: ET.Element, por: dict) -> ET.Element | None:
    """O `VideoClipTrackItem` de um gráfico com UMA camada de texto (`AE.ADBE Text`)."""
    for e in R:
        if e.tag != "VideoClipTrackItem" or e.find("./ClipTrackItem/ComponentOwner/Components") is None:
            continue
        nomes = [c.findtext("MatchName") for c in _componentes(por, e)]
        # ⚠️ só a camada de texto: o "Vector Motion" (`AE.ADBE Graphic Group`) some da cadeia quando o projeto do
        #   molde é IMPORTADO noutro (medido no 26.5, 2026-11-20) — exigi-lo deixava o título "sem molde"
        if nomes.count("AE.ADBE Text") == 1:
            return e
    return None


def _valor_binario(R: ET.Element, el: ET.Element) -> str:
    """O base64 de um valor binário — o do próprio elemento, ou (deduplicado) o do elemento de mesmo `BinaryHash`."""
    if (el.text or "").strip():
        return el.text.strip()
    h = el.get("BinaryHash")
    for x in R.iter(el.tag):
        if x.get("BinaryHash") == h and (x.text or "").strip():
            return x.text.strip()
    raise CartaErro("o valor do Source Text do molde não está no arquivo")


def _hash_binario(b64: str) -> str:
    """12 bytes aleatórios + o tamanho (u32, tamanho + 12): o Premiere não confere os 12 e, ao salvar, põe o dele."""
    import base64 as _b64
    h = os.urandom(12).hex()
    tam = len(_b64.b64decode(b64)) + 12
    return f"{h[:8]}-{h[8:12]}-{h[12:16]}-{h[16:20]}-{h[20:24]}{tam:08x}"


def _clonar_grafico(R: ET.Element, por: dict, molde: ET.Element, novo_id, novos: list) -> tuple:
    """(TrackItem, cadeia, SubClip, o param Source Text, o param Position, os clones por id) — com MasterClip e Media
    NOVOS (ObjectUID), e tudo o que eles apontam."""
    ini = len(novos)
    cadeia = _clonar(por[molde.find("./ClipTrackItem/ComponentOwner/Components").get("ObjectRef")], por, novo_id, novos)
    sub = _clonar(por[molde.find("./ClipTrackItem/SubClip").get("ObjectRef")], por, novo_id, novos)
    trocas: dict[str, str] = {}

    def novo_uid(uref: str) -> None:
        el = copy.deepcopy(por[uref])
        el.set("ObjectUID", str(uuid.uuid4()))
        trocas[uref] = el.get("ObjectUID")
        for x in el.iter():
            r = x.get("ObjectRef")
            if r and r in por:
                x.set("ObjectRef", _chave(_clonar(por[r], por, novo_id, novos)))
        novos.append(el)

    novo_uid(sub.find("MasterClip").get("ObjectURef"))
    for e in list(novos[ini:]):                          # a mídia sintética do gráfico: uma por título
        m = e.find("./MediaSource/Media") if e.tag == "VideoMediaSource" else None
        if m is not None and m.get("ObjectURef") not in trocas and m.get("ObjectURef") in por:
            novo_uid(m.get("ObjectURef"))
    for e in novos[ini:]:
        for x in e.iter():
            if x.get("ObjectURef") in trocas:
                x.set("ObjectURef", trocas[x.get("ObjectURef")])
        cid = e.find("./Clip/ClipID")
        if cid is not None:
            cid.text = str(uuid.uuid4())
    nv = {_chave(e): e for e in novos[ini:]}
    texto = posicao = None
    for c in cadeia.iter("Component"):
        comp = nv.get(c.get("ObjectRef"))
        if comp is not None and comp.findtext("MatchName") == "AE.ADBE Text":
            for prm in comp.iter("Param"):
                q = nv.get(prm.get("ObjectRef"))
                if q is not None and q.findtext("Name") == "Source Text":
                    texto = q
                elif q is not None and q.findtext("Name") == "Position":
                    posicao = q
    if texto is None:
        raise CartaErro("o molde do título não tem o Source Text")
    return copy.deepcopy(molde), cadeia, sub, texto, posicao, nv


def _escrever_titulo(R, por, molde, titulo: dict, dur_t: int, quadro: tuple, novo_id, novos: list,
                     avisos: list) -> tuple:
    """Um título do Avid como clone do gráfico-molde: o texto e o estilo no blob, a posição na camada, a duração no
    clipe do gráfico. Várias caixas: só a 1ª (dito)."""
    from . import titulo_prproj as _tp
    ti, cadeia, sub, texto, posicao, nv = _clonar_grafico(R, por, molde, novo_id, novos)
    caixas = [c for c in titulo.get("caixas") or [] if (c.get("texto") or "").strip()]
    if len(caixas) > 1:
        avisos.append(f"título com {len(caixas)} caixas: foi a 1ª")
    sk = texto.find("StartKeyframeValue")
    arv = _tp.ler(_valor_binario(R, sk))
    arv, pos, av = _tp.compor_do_avid(arv, titulo, caixas[0], int(quadro[0]), int(quadro[1]))
    avisos += [a for a in av if a not in avisos]
    b64 = _tp.escrever(arv)
    sk.text = b64 + "\n"
    sk.set("BinaryHash", _hash_binario(b64))
    for k in texto.findall("Keyframes"):
        texto.remove(k)
    if pos is not None and posicao is not None and posicao.find("StartKeyframe") is not None:
        campos = posicao.find("StartKeyframe").text.split(",")
        campos[1] = f"{pos[0]}:{pos[1]}"
        posicao.find("StartKeyframe").text = ",".join(campos)
    vc = nv.get(sub.find("Clip").get("ObjectRef"))
    if vc is not None and vc.find("./Clip/InPoint") is not None and vc.find("./Clip/OutPoint") is not None:
        ent = int(vc.find("./Clip/InPoint").text)
        vc.find("./Clip/OutPoint").text = str(ent + dur_t)
    return ti, cadeia, sub


def escrever_timeline(proj: Projeto, item: dict, prproj: str, saida: str, sequencia: str,
                      nome: str, trilhas: set[str] | None = None, forma: str = "avid",
                      quadro: tuple[int, int] | None = None, transcricao_vazia: bool = False) -> dict:
    """Numa CÓPIA de `prproj` (o projeto de entrega, com a mídia já importada por ele e a sequência-molde `sequencia`
    feita por ele), as trilhas da timeline `item` (`trilhas`: {"V1", "A3"}; None = todas) no lugar dos clipes do
    molde, e a sequência renomeada `nome`. Trilhas de som que faltam no molde são clonadas da 2ª dele.
    Transição: dissolve e crossfade, clonados do molde que o Premiere fez (`_moldes_de_transicao`), com os planos
    passados do modelo do Avid (sobrepostos) para o do Premiere (encostados no corte) — `_transicoes_da_trilha`.
    Velocidade constante (`PlaybackSpeed`, optical flow = `TimeInterpolationType 2`) e conformação de taxa (tempo real)
    por `velocidade_do_clipe`; desligado = `IsMuted`.
    ⛔ O que este passo ainda não escreve fica de FORA e dito (velocidade variável, congelamento, efeito que não seja o
    ganho, outra transição): nunca um clipe com o tempo errado.
    `transcricao_vazia` (Premiere 26+): todo merged da saída leva um `TranscriptClip` vazio — sem ele o
    `importSequences` não reconhece o merged que o projeto do editor já tem e o REPETE (+36 por reimportação, medido;
    com ele, 0 — `merged_prproj.transcricao_vazia`)."""
    import os
    from pathlib import Path as _P
    if _norm(prproj) == _norm(saida):
        raise CartaErro("a saída não pode ser o mesmo arquivo do projeto")
    R = _ler_prproj(prproj)
    por = {_chave(e): e for e in R if _chave(e)}
    seq = next((e for e in R if e.tag == "Sequence" and e.findtext("Name") == sequencia), None)
    if seq is None:
        raise CartaErro(f"o projeto não tem a sequência-molde {sequencia!r}")
    midia = midia_do_projeto(R)
    tpf = _ticks_por_quadro(item.get("fps") or "25")
    ordem = ORDEM_DAS_FORMAS.get(forma, ORDEM_DAS_FORMAS["avid"])
    maior = max(int(k) for k in (e.get("ObjectID") for e in R) if k and k.isdigit())
    prox = [maior]

    def novo_id() -> str:
        prox[0] += 1
        return str(prox[0])

    grupos = {}
    for tg in seq.iter("TrackGroup"):
        s = tg.find("Second")
        if s is not None and s.get("ObjectRef") in por:
            grupos[por[s.get("ObjectRef")].tag] = por[s.get("ObjectRef")]
    vtg, atg = grupos["VideoTrackGroup"], grupos.get("AudioTrackGroup")
    v_trilhas = [por[t.get("ObjectURef")] for t in vtg.find("./TrackGroup/Tracks")]
    a_lista = atg.find("./TrackGroup/Tracks") if atg is not None else None
    a_trilhas = [por[t.get("ObjectURef")] for t in a_lista] if a_lista is not None else []
    da_timeline = [t for t in item.get("trilhas", []) if trilhas is None or f"{t['tipo']}{t['k']}" in trilhas]
    v_da_timeline = [t for t in da_timeline if t["tipo"] == "V"]
    a_da_timeline = [t for t in da_timeline if t["tipo"] == "A"]
    # o molde dos objetos do clipe de vídeo: o primeiro clipe de vídeo do molde
    molde_ti = None
    for tr in v_trilhas:
        tis = tr.find("./ClipTrack/ClipItems/TrackItems")
        for ti in (list(tis) if tis is not None else []):
            molde_ti = por[ti.get("ObjectRef")]
            break
        if molde_ti is not None:
            break
    if molde_ti is None and v_da_timeline:
        raise CartaErro("a sequência-molde não tem clipe de vídeo")
    molde_cadeia = por[molde_ti.find("./ClipTrackItem/ComponentOwner/Components").get("ObjectRef")] if molde_ti is not None else None
    moldes_som = _moldes_de_som(R, por)
    if a_da_timeline and "sem_ganho" not in moldes_som:
        raise CartaErro("o projeto não tem um clipe de som mono montado pelo Premiere (o molde do som)")
    moldes_tr = _moldes_de_transicao(R)
    removidos: set[str] = set()
    # ⛔ ANTES de esvaziar: a sequência de moldes É a que vira a timeline, e o molde da cor é achado pelas trilhas dela
    #   (medido 2026-11-20, PRODA no 26.5.2: lido depois, "Color Correction (sem molde)" nos 7 com o molde na cópia)
    molde_cor = molde_de_cor(R, por)

    def esvaziar(tr: ET.Element) -> None:
        tis = tr.find("./ClipTrack/ClipItems/TrackItems")
        if tis is None:
            return
        for ti in list(tis):
            removidos.add(ti.get("ObjectRef"))
            tis.remove(ti)
        ttis = tr.find("./ClipTrack/TransitionItems/TrackItems")
        for ti in (list(ttis) if ttis is not None else []):
            removidos.add(ti.get("ObjectRef"))
            ttis.remove(ti)

    for tr in v_trilhas + a_trilhas:
        esvaziar(tr)
    lc = seq.find("./PersistentGroupContainer/LinkContainer/Links")
    if lc is not None:
        for l in list(lc):
            removidos.add(l.get("ObjectRef"))
            lc.remove(l)

    rel = {"clipes": 0, "transicoes": 0, "velocidades": 0, "desligados": 0, "fora": {}, "offline": 0, "sem_item": [], "trilhas": [], "trilhas_criadas": 0,
           "merged": 0, "merged_fora": {}, "subclipes": 0, "subclipes_fora": {}, "titulos": 0, "titulos_avisos": [],
           "esticados": 0, "ganho_no_clipe": 0, "estabilizar": 0, "cor_do_avid": 0}
    molde_esc = molde_de_esticar(R, por)
    molde_tit = molde_de_titulo(R, por)
    _fr = (vtg.findtext("FrameRect") or "0,0,1920,1080").split(",")
    quadro_tit = tuple(quadro) if quadro else (int(_fr[2]), int(_fr[3]))

    def fora(motivo: str) -> None:
        rel["fora"][motivo] = rel["fora"].get(motivo, 0) + 1

    novos: list[ET.Element] = []
    if len(v_da_timeline) and max(t["k"] for t in v_da_timeline) > len(v_trilhas):
        raise CartaErro(f"a sequência-molde tem {len(v_trilhas)} trilhas de vídeo; a timeline pede V{max(t['k'] for t in v_da_timeline)}")
    # as trilhas de som que faltam: clones da 2ª do molde (a 1ª leva MZ.TrackTargeted/SourceTrackNumber de índice 0)
    precisa = max((t["k"] for t in a_da_timeline), default=0)
    if precisa > len(a_trilhas):
        if not a_trilhas:
            raise CartaErro("a sequência-molde não tem trilha de som para clonar")
        base = a_trilhas[1] if len(a_trilhas) > 1 else a_trilhas[0]
        prox_trilha = int(atg.findtext("./TrackGroup/NextTrackID") or 0)
        for i in range(len(a_trilhas), precisa):
            tr = copy.deepcopy(base)
            tr.set("ObjectUID", str(uuid.uuid4()))
            for x in tr.iter():
                r = x.get("ObjectRef")
                if r and r in por:
                    x.set("ObjectRef", _chave(_clonar(por[r], por, novo_id, novos)))
            tr.find("./ClipTrack/Track/ID").text = str(prox_trilha)
            prox_trilha += 1
            for idx in tr.iterfind(".//Index"):
                idx.text = str(i)
            tr.find("./AudioTrack/ID").text = str(uuid.uuid4())
            tis = tr.find("./ClipTrack/ClipItems/TrackItems")
            if tis is not None:
                tr.find("./ClipTrack/ClipItems").remove(tis)
            ET.SubElement(a_lista, "Track", {"Index": str(i), "ObjectURef": tr.get("ObjectUID")})
            # ⛔ e na master do mix (`AudioTrackInlet/Sources`): sem isto a trilha existe e fica MUDA — medido nas
            # entregas de 2026-11-14 (v04–v08): 4 de 16 na lista, e o Premiere regravou assim, sem reclamar
            mix = atg.find("MasterTrack")
            mixt = por.get(mix.get("ObjectRef") or mix.get("ObjectURef") or "") if mix is not None else None
            inl = por.get(mixt.find("Inlet").get("ObjectRef")) if mixt is not None and mixt.find("Inlet") is not None else None
            if inl is not None and inl.find("Sources") is not None:
                ET.SubElement(inl.find("Sources"), "Source", {"Index": str(len(inl.find("Sources"))),
                                                              "ObjectURef": tr.get("ObjectUID")})
            a_trilhas.append(tr)
            novos.append(tr)
            rel["trilhas_criadas"] += 1
        atg.find("./TrackGroup/NextTrackID").text = str(prox_trilha)

    cache: dict[str, tuple[str, dict[str, str]] | None] = {}

    def arquivos_de(m: str):
        if m not in cache:
            achou = _forma_aqui(proj, m, ordem)
            cache[m] = None if achou is None else (achou[0], trilhas_do_master(achou[1]) if achou[0] == "avid"
                                                   else {"V1": achou[1][0], "*": achou[1][0]})
        return cache[m]

    def tempos(tri: ET.Element, ini: int, fim: int) -> None:
        for x in list(tri):
            if x.tag in ("Start", "End"):
                tri.remove(x)
        if ini:
            ET.SubElement(tri, "Start").text = str(ini * tpf)
        ET.SubElement(tri, "End").text = str(fim * tpf)

    def em_ticks(cl: ET.Element, w: dict) -> None:
        """InPoint = a entrada na MÍDIA; OutPoint = entrada + duração × velocidade (o molde); PlaybackSpeed e o
        TimeInterpolationType (2 = optical flow, banco) quando há velocidade."""
        dur_t = round((w["fim"] - w["ini"]) * tpf * (w["vel"] or 1.0))
        for tag, v in (("InPoint", w["in_t"]), ("OutPoint", w["in_t"] + dur_t)):
            el = cl.find(tag)
            if el is None:
                el = ET.SubElement(cl, tag)
            el.text = str(v)
        for x in cl.findall("InUse"):
            cl.remove(x)
        cid = cl.find("ClipID")
        if cid is not None:
            cid.text = str(uuid.uuid4())
        for tag in ("PlaybackSpeed", "TimeInterpolationType"):
            for x in cl.findall(tag):
                cl.remove(x)
        if w["vel"] is not None:
            ET.SubElement(cl, "PlaybackSpeed").text = repr(w["vel"])
            if w["interp"]:
                ET.SubElement(cl, "TimeInterpolationType").text = w["interp"]

    def subclipe(clip_id: str, mc: str, grupo: int) -> ET.Element:
        sub = ET.Element("SubClip", {"ObjectID": novo_id(), "ClassID": "e0c58dc9-dbdd-4166-aef7-5db7e3f22e84",
                                     "Version": "6"})
        ET.SubElement(sub, "Clip", {"ObjectRef": clip_id})
        ET.SubElement(sub, "MasterClip", {"ObjectURef": mc})
        ET.SubElement(sub, "Name").text = por[mc].findtext("Name") or ""
        ET.SubElement(sub, "OrigChGrp").text = str(grupo)
        return sub

    merged = _os_merged(proj, R, por, item, da_timeline, midia, arquivos_de, tpf, rel, prox)
    from . import itens as _itens
    _por_item = {d["id"]: d for _, d in _itens.todos(proj)} if merged else {}
    para_vincular: list[dict] = []
    # ⛔ os merged numeraram objetos acima do `maior` de antes: o contador anda até depois deles (medido: sem isto,
    # 4466 ObjectID repetidos e "Não foi possível carregar o projeto" no 26.0.2)
    prox[0] = max(prox[0], max(int(k) for k in (e.get("ObjectID") for e in R) if k and k.isdigit()))
    fim_seq = 0
    for t in v_da_timeline + a_da_timeline:
        rot = f"{t['tipo']}{t['k']}"
        audio = t["tipo"] == "A"
        tr_alvo = (a_trilhas if audio else v_trilhas)[t["k"] - 1]
        alvo = tr_alvo.find("./ClipTrack/ClipItems/TrackItems")
        if alvo is None:
            alvo = ET.Element("TrackItems", {"Version": "1"})
            tr_alvo.find("./ClipTrack/ClipItems").insert(0, alvo)
        # 1ª fase: quem será escrito (o tempo é o do Avid: os planos de uma transição SE SOBREPÕEM)
        escritos: list[dict] = []
        offline_da_trilha: list[tuple[int, int]] = []
        for sc in t.get("sem_clipe") or []:
            tit = None if audio else titulo_do_trecho(sc)
            if tit is None:
                fora(f"efeito sem mídia, título ou matte ({rot})")
            elif molde_tit is None:
                fora(f"título (sem molde) ({rot})")
            else:      # ⭐ o título entra na trilha como um clipe: as transições dele se prendem pela mesma regra
                escritos.append({"c": {"inicio_q": sc["inicio_q"], "fim_q": sc["fim_q"]}, "info": None,
                                 "titulo": tit, "ini": int(sc["inicio_q"]), "fim": int(sc["fim_q"]), "in_t": 0,
                                 "vel": None, "interp": None, "cabeca": None, "cauda": None})
        for c in sorted(t.get("clipes", []), key=lambda x: int(x["inicio_q"])):
            ve = velocidade_do_clipe(c, item.get("fps") or "25")
            if "fora" in ve:
                fora(f"{ve['fora']} ({rot})")
                continue
            do_merged = merged.get(c.get("item") or "")
            if do_merged is not None and (do_merged["A"].get(int(c.get("canal") or 1)) if audio else do_merged["V"]):
                # ⭐ o clipe que veio do subclipe SINCRONIZADO aponta o componente do merged (o molde do Premiere)
                info = do_merged["A"][int(c.get("canal") or 1)] if audio else do_merged["V"]
                arq = "merged"
            else:
                achou = arquivos_de(c.get("midia") or "")
                arq = None
                if achou is not None:
                    arq = (achou[1].get(f"A{int(c.get('canal') or 1)}" if audio else "V1") or achou[1].get("*"))
                if arq is None:
                    rel["offline"] += 1
                    offline_da_trilha.append((int(c["inicio_q"]), int(c["fim_q"])))
                    # ⛔ o efeito do clipe OFFLINE também é dito: religada a mídia depois, ele não estará lá (PRODA: os 21
                    #   D-Verb estão em efeitos sonoros que não estão nesta máquina, e sumiam do relatório)
                    _efeitos_sem_par(c, audio, rot, fora, offline=True)
                    continue
                info = midia.get(_norm(arq)) or {}
            if (audio and not info.get("audio")) or (not audio and "video_clip" not in info):
                rel["sem_item"].append(os.path.basename(arq))
                continue
            if audio:
                canais = info["audio"][0][3]
                if canais != 1 and int(c.get("canal") or 1) > canais:
                    fora(f"canal {int(c.get('canal') or 1)} que o arquivo não tem ({rot})")
                    continue
            escritos.append({"c": c, "info": info, "ini": int(c["inicio_q"]), "fim": int(c["fim_q"]),
                             "in_t": round(int(c["entrada_q"]) * TICKS_POR_SEGUNDO / ve["fonte_fps"]),
                             "vel": ve["vel"], "interp": ve["interp"], "cabeca": None, "cauda": None})
            if ve["vel"] is not None:
                rel["velocidades"] += 1
            if c.get("desligado"):
                rel["desligados"] += 1
        escritos.sort(key=lambda w: w["ini"])
        _offline_da_trilha = list(offline_da_trilha)
        # 2ª fase: as transições, no modelo do Premiere (os planos ENCOSTAM no corte; a transição o atravessa e mistura
        # a mídia por baixo — a mesma que o Avid usa). Nenhum corte muda de lugar.
        pares = _transicoes_da_trilha(t.get("transicoes") or [], escritos, audio, moldes_tr, fora, rot, tpf,
                                      _offline_da_trilha)
        for p in pares:
            rel["transicoes"] += 1
            x = p["x"]
            tri = _clonar(moldes_tr["A" if audio else "V"], por, novo_id, novos)
            tti = tri.find("TransitionTrackItem")
            tempos(tti.find("TrackItem"), x["inicio_q"], x["fim_q"])
            tti.find("Alignment").text = str((p["corte"] - x["inicio_q"]) * tpf)
            tti.find("HasOutgoingClip").text = "true" if p["a"] is not None else "false"
            tti.find("HasIncomingClip").text = "true" if p["b"] is not None else "false"
            if p["a"] is not None:
                p["a"]["cauda"] = tri.get("ObjectID")
            if p["b"] is not None:
                p["b"]["cabeca"] = tri.get("ObjectID")
            tits = tr_alvo.find("./ClipTrack/TransitionItems")
            if tits is None:          # o lugar como o do ClipItems ao lado (mesmo MediaType e Index)
                tits = copy.deepcopy(tr_alvo.find("./ClipTrack/ClipItems"))
                tits.tag = "TransitionItems"
                for x in tits.findall("TrackItems"):
                    tits.remove(x)
                tr_alvo.find("ClipTrack").append(tits)
            ttis = tits.find("TrackItems")
            if ttis is None:
                ttis = ET.Element("TrackItems", {"Version": "1"})
                tits.insert(0, ttis)
            ET.SubElement(ttis, "TrackItem", {"Index": str(len(ttis)), "ObjectRef": tri.get("ObjectID")})
        for a, b in zip(escritos, escritos[1:]):
            if b["ini"] < a["fim"]:
                fora(f"clipes sobrepostos sem transição ({rot})")
        n_trilha = 0
        for w in escritos:
            c, info = w["c"], w["info"]
            for e in c.get("efeitos") or []:
                if estabilizacao_do_efeito(e) is not None and not audio:
                    rel["estabilizar"] += 1          # vira Warp Stabilizer DEPOIS da importação (`importar_premiere`)
            cor = None if (audio or w.get("titulo")) else cor_do_clipe(c)
            _efeitos_sem_par(c, audio, rot, fora, cor_vai=bool(cor and molde_cor))
            if cor and molde_cor is None:
                fora(f"Color Correction (sem molde) ({rot})")
            ini, fim = w["ini"], w["fim"]
            if w.get("titulo"):
                ti, cadeia, sub = _escrever_titulo(R, por, molde_tit, w["titulo"], (fim - ini) * tpf,
                                                   quadro_tit, novo_id, novos, rel["titulos_avisos"])
                rel["titulos"] += 1
            elif audio:
                # o canal DENTRO do arquivo: o OP-Atom é mono (canal 0); o WAV/AIFF da forma original, o canal do clipe
                mc, ac_id, grupo, canais = info["audio"][0]
                canal = 0 if canais == 1 else int(c.get("canal") or 1) - 1
                ac = copy.deepcopy(por[ac_id])
                ac.set("ObjectID", novo_id())
                em_ticks(ac.find("Clip"), w)
                scs = ac.find("SecondaryContents")
                escolhido = None
                if scs is not None:
                    itens_sc = scs.findall("SecondaryContentItem")
                    if canal < len(itens_sc):
                        escolhido = por.get(itens_sc[canal].get("ObjectRef"))
                    for x in itens_sc:
                        scs.remove(x)
                if escolhido is not None:
                    sc = copy.deepcopy(escolhido)
                    sc.set("ObjectID", novo_id())
                    sc.find("ChannelIndex").text = str(canal)
                    ET.SubElement(scs, "SecondaryContentItem", {"Index": "0", "ObjectRef": sc.get("ObjectID")})
                    novos.append(sc)
                lay = ac.find("AudioChannelLayout")
                if lay is not None:
                    lay.text = '[{"channellabel":0}]'
                sub = subclipe(ac.get("ObjectID"), mc, grupo)
                g = c.get("ganho_db")
                if c.get("ganho_no_item_db"):                # o ganho de DENTRO do subclipe toca junto no Avid
                    g = round(float(g or 0) + float(c["ganho_no_item_db"]), 2)
                molde = moldes_som["com_ganho"] if (g not in (None, 0, 0.0) and "com_ganho" in moldes_som) else moldes_som["sem_ganho"]
                if g not in (None, 0, 0.0) and "com_ganho" not in moldes_som:
                    fora(f"ganho (sem molde) ({rot})")
                cadeia = _clonar(por[molde.find("./ClipTrackItem/ComponentOwner/Components").get("ObjectRef")],
                                 por, novo_id, novos)
                if molde is moldes_som.get("com_ganho"):
                    v = nivel_do_volume(g)
                    if float(g) > GANHO_MAXIMO_DO_VOLUME_DB:
                        # ⭐ o que passa de +15 dB (o teto do Volume do clipe) vai para o AUDIO GAIN do clipe: `<Gain>`
                        #   no AudioClip, o fator LINEAR (medido no 26.5: 9 dB → 2,818…; 2026-11-20)
                        for x in ac.findall("Gain"):
                            ac.remove(x)
                        ET.SubElement(ac, "Gain").text = repr(10 ** ((float(g) - GANHO_MAXIMO_DO_VOLUME_DB) / 20.0))
                        rel["ganho_no_clipe"] += 1
                    for comp in cadeia.findall("./ComponentChain/Components/Component"):
                        fc = next(x for x in novos if _chave(x) == comp.get("ObjectRef"))
                        for pr in fc.findall("./AudioComponent/Component/Params/Param"):
                            par = next(x for x in novos if _chave(x) == pr.get("ObjectRef"))
                            if par.findtext("UnitsString") == "dB":
                                par.find("CurrentValue").text = repr(round(v, 12))
                                sk = par.find("StartKeyframe")
                                if sk is not None:
                                    campos = sk.text.split(",")
                                    campos[1] = repr(round(v, 12))
                                    sk.text = ",".join(campos)
                ti = copy.deepcopy(molde)
                novos += [ac, sub]
            else:
                esticar = None
                if c.get("enquadramento") == "stretch":
                    esticar = escala_do_stretch(info.get("frame_rect"), quadro_tit)
                    if esticar is not None and molde_esc is None:
                        fora(f"enquadramento stretch (sem molde, vai em tamanho real) ({rot})")
                        esticar = None
                elif c.get("enquadramento"):
                    fora(f"enquadramento {c['enquadramento']} (vai em tamanho real)")
                vc = copy.deepcopy(por[info["video_clip"]])
                vc.set("ObjectID", novo_id())
                em_ticks(vc.find("Clip"), w)
                sub = subclipe(vc.get("ObjectID"), info["mc"], 0)
                if esticar is not None:
                    # ⭐ o STRETCH do Avid (2026-11-20): o Motion do molde, com a escala não uniforme da mídia para o
                    #   quadro (2K DCI 2048×1080 num 1920×1080: largura 93,75 %, altura 100 %)
                    ini_n = len(novos)
                    cadeia = _clonar(molde_esc, por, novo_id, novos)
                    for par in novos[ini_n:]:
                        if par.findtext("Name") in ("Scale Height", "Scale"):
                            _valor_do_param(par, repr(float(esticar[1])))
                        elif par.findtext("Name") == "Scale Width":
                            _valor_do_param(par, repr(float(esticar[0])))
                    rel["esticados"] += 1
                else:
                    cadeia = copy.deepcopy(molde_cadeia)
                    cadeia.set("ObjectID", novo_id())
                if cor and molde_cor is not None:
                    # ⭐ a COR do Avid (2026-11-20): ProcAmp (Sat) → Lumetri (a curva em R, G e B), editáveis
                    _cor_na_cadeia(R, por, molde_cor, cadeia, cor, novo_id, novos)
                    rel["cor_do_avid"] += 1
                ti = copy.deepcopy(molde_ti)
                if info.get("frame_rect") and ti.find("FrameRect") is not None:
                    ti.find("FrameRect").text = info["frame_rect"]
                novos += [cadeia, sub, vc]
            ti.set("ObjectID", novo_id())
            if ti.find("ID") is not None:
                ti.find("ID").text = str(uuid.uuid4())
            cti = ti.find("ClipTrackItem")
            cti.find("./ComponentOwner/Components").set("ObjectRef", cadeia.get("ObjectID"))
            cti.find("SubClip").set("ObjectRef", sub.get("ObjectID"))
            for x in cti.findall("HeadTransition") + cti.findall("TailTransition"):   # as do molde
                cti.remove(x)
            for tag in ("cabeca", "cauda"):
                if w[tag]:
                    ET.SubElement(cti, "HeadTransition" if tag == "cabeca" else "TailTransition",
                                  {"ObjectRef": w[tag]})
            for x in cti.findall("IsMuted"):
                cti.remove(x)
            if c.get("desligado"):                 # o Selector do Avid no ramo vazio = desligado (molde: IsMuted)
                ET.SubElement(cti, "IsMuted").text = "true"
            tempos(cti.find("TrackItem"), ini, fim)
            ET.SubElement(alvo, "TrackItem", {"Index": str(n_trilha), "ObjectRef": ti.get("ObjectID")})
            n_trilha += 1
            novos.append(ti)
            rel["clipes"] += 1
            if w.get("titulo"):                  # o título não se vincula a nada
                fim_seq = max(fim_seq, fim)
                continue
            # para o VÍNCULO: de onde veio e a sincronia (o quadro da fonte que cai no quadro 0 da timeline)
            it_m = _por_item.get(c.get("item") or "") if c.get("item") in merged else None
            lado = None
            if it_m and it_m.get("tipo") == "sincronizado":
                lado = it_m["som"] if audio else it_m["imagem"]
            elif it_m:                                   # o recorte: imagem e som do MESMO master
                lado = {"inicio_q": it_m["entrada_q"]}
            if w["vel"] is None and not (c.get("velocidade") or {}).get("classe"):
                para_vincular.append({"ti": ti.get("ObjectID"), "audio": audio, "ini": w["ini"], "fim": w["fim"],
                                      "chave": c.get("item") if it_m else c.get("midia"),
                                      "sinc": w["in_t"] - (int(lado["inicio_q"]) * tpf if lado else 0) - w["ini"] * tpf})
            fim_seq = max(fim_seq, fim)
        rel["trilhas"].append({"trilha": rot, "clipes": n_trilha})
    _vincular(seq, para_vincular, novo_id, novos, rel)
    # o que só os clipes removidos usavam sai do arquivo (o fecho deles que ninguém mais aponta)
    vivos: set[str] = set()
    fila = [_chave(e) for e in R if e.tag in ("Project",) and _chave(e)]
    novos_por = {_chave(e): e for e in novos}
    alcance = {**por, **novos_por}
    for k in removidos:
        alcance.pop(k, None)
    while fila:
        k = fila.pop()
        if k in vivos or k not in alcance:
            continue
        vivos.add(k)
        fila += [v for _x, _a, v in _refs(alcance[k])]
    tirar = {k for k in por if k not in vivos and por[k].tag in (
        "VideoClipTrackItem", "AudioClipTrackItem", "SubClip", "VideoClip", "AudioClip", "VideoComponentChain",
        "AudioComponentChain", "Link", "SecondaryContent", "ClipChannelVectorSerializer", "ClipChannelSerializer",
        "AudioComponentParam", "VideoComponentParam", "AudioFilterComponent", "VideoTransitionTrackItem",
        "AudioTransitionTrackItem", "VideoFilterComponent", "ArbVideoComponentParam")}
    for e in list(R):
        if _chave(e) in tirar:
            R.remove(e)
    for e in novos:
        R.append(e)
    seq.find("Name").text = nome
    rel["item_renomeado"] = _renomear_item_da_sequencia(R, seq, nome)
    rel["uid"] = seq.get("ObjectUID")   # ⛔ pelo NOME acharia uma homônima que o projeto do editor já tenha
    if quadro:
        w, h = quadro
        vtg.find("FrameRect").text = f"0,0,{w},{h}"
        for tag, v in (("MZ.Sequence.PreviewFrameSizeWidth", w), ("MZ.Sequence.PreviewFrameSizeHeight", h)):
            el = seq.find(f"./Node/Properties/{tag}")
            if el is not None:
                el.text = str(v)
    props = seq.find("./Node/Properties")
    if props is not None:
        for tag, v in (("MZ.WorkOutPoint", fim_seq * tpf), ("Monitor.ProgramZoomOut", fim_seq * tpf),
                       ("MZ.ZeroPoint", int(item.get("tc_inicio_q") or 0) * tpf)):
            el = props.find(tag)
            if el is None:
                el = ET.SubElement(props, tag)
            el.text = str(v)
    if transcricao_vazia:
        from . import merged_prproj as _mp
        por_t = {_chave(e): e for e in R}
        ids_t = _mp._Ids(R)
        rel["transcricao_vazia"] = sum(bool(_mp.transcricao_vazia(R, por_t, mc, ids_t))
                                       for _c, mc in _mp.os_merged(R, por_t))
    _P(saida).parent.mkdir(parents=True, exist_ok=True)
    _gravar_prproj(R, saida)
    rel["tirados_do_molde"] = len(tirar)
    rel["saida"] = saida
    return rel


#: o nome de antes (só vídeo); hoje as trilhas pedidas dizem o que entra
escrever_trilhas_de_video = escrever_timeline
