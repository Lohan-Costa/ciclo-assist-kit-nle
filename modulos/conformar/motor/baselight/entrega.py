"""O xmeml para o Baselight com o ORIGINAL decidido em cada `<file>` — a correção ANTES de mandar (autor, 2026-11-22).

A posição na fonte segue a "ponte pelo original" (banco, `transversal/tempo-e-timecode.md`): o `<in>` do clipitem conta,
na taxa da TIMELINE, desde o INÍCIO do arquivo; em segundos ele vale para o daily e para o original, e o Baselight o converte
para a taxa que o `<file>` DECLARA. Por isso basta o `<file>` descrever o original de verdade (taxa, TC, duração, raster):
TC zerado na conversão (ou no original) e fps diferente deixam de importar. Medido no laboratório BL08: com a taxa do daily
declarada, o original de 59,94 entrou 1,8 s fora (−107 quadros); com a do original, exato.
"""
from __future__ import annotations

import math
import os
import unicodedata
import urllib.parse
import xml.etree.ElementTree as ET
from fractions import Fraction

PREFIXO_OFFLINE = "OFFLINE_CICLO__"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s or "")


def como_o_disco_lista(caminho: str) -> str:
    """O caminho com cada nome COMO A PASTA O LISTA (no exFAT/HFS+ do Mac: NFD). O Baselight 7.0.3 não acha o nome com
    acento escrito em NFC num exFAT (laboratório BL08, P5); no Windows a pasta lista como foi gravado."""
    partes = os.path.normpath(caminho).split(os.sep)
    atual = os.sep if caminho.startswith(os.sep) else ""
    saida = []
    for nome in partes:
        if not nome:
            continue
        try:
            achado = next((n for n in os.listdir(atual or ".") if _nfc(n) == _nfc(nome)), nome)
        except OSError:
            achado = nome
        saida.append(achado)
        atual = os.path.join(atual, achado)
    return (os.sep if caminho.startswith(os.sep) else "") + os.sep.join(saida)


def _rate(fps: float) -> tuple[int, str]:
    """(timebase, ntsc) do xmeml: 23,976 → (24, TRUE); 25 → (25, FALSE)."""
    nominal = round(fps)
    return nominal, "TRUE" if abs(fps - nominal) > 0.01 else "FALSE"


def _tc_quadros(tc: str, base: int, df: bool) -> int:
    hh, mm, ss, ff = (int(x) for x in tc.replace(";", ":").split(":"))
    total = ((hh * 60 + mm) * 60 + ss) * base + ff
    if df:
        d = base // 15                       # 2 a 29,97; 4 a 59,94
        minutos = hh * 60 + mm
        total -= d * (minutos - minutos // 10)
    return total


#: extensões de quadro de SEQUÊNCIA de imagens (um arquivo por quadro)
_EXT_IMAGEM = (".jpg", ".jpeg", ".png", ".tif", ".tiff", ".psd", ".bmp", ".gif", ".tga", ".exr", ".dpx", ".webp")
_EXT_SEQUENCIA = (".dpx", ".exr", ".tif", ".tiff", ".png", ".jpg", ".jpeg", ".cin", ".ari")


def quadro_de_sequencia(caminho: str) -> tuple[str, int, int, str] | None:
    """`(pasta/base, número do 1º quadro, quantos quadros, o caminho na sintaxe FilmLight)` se `caminho` é um quadro de
    SEQUÊNCIA de imagens (`…/A003C001/A003C001.1641600.dpx`) ou já o padrão (`…/A003C001.%.7F.dpx`), senão `None`.

    ⛔ Laboratório BL08, P10 (2026-11-22): com o caminho de UM quadro no `<file>`, o Baselight conformou a sequência como
    imagem PARADA (o 1º quadro no plano inteiro, embora o `bl-shots` desse in/out em números de quadro). A sintaxe dele é
    `nome.%.7F.dpx` (banco, `plugins/baselight/README.md`)."""
    import re
    pasta, nome = os.path.split(caminho)
    raiz, ext = os.path.splitext(nome)
    if ext.lower() not in _EXT_SEQUENCIA:
        return None
    m = re.match(r"(.*?)([._-]?)(?:(\d{3,})|%\.(\d+)F)$", raiz)
    if not m:
        return None
    base, sep = m.group(1), m.group(2)
    pad = len(m.group(3)) if m.group(3) else int(m.group(4))
    numeros = []
    try:
        for x in os.listdir(pasta):
            r, e = os.path.splitext(x)
            if e.lower() == ext.lower() and r.startswith(base + sep) and r[len(base + sep):].isdigit():
                numeros.append(int(r[len(base + sep):]))
    except OSError:
        pass
    primeiro = min(numeros) if numeros else int(m.group(3) or 0)
    return (os.path.join(pasta, base), primeiro, len(numeros),
            os.path.join(pasta, f"{base}{sep}%.{pad}F{ext}"))


def descrever(original: str, sonda: dict, fps_sequencia: float | None = None, trecho: dict | None = None) -> dict:
    """O que o `<file>` tem de dizer do original, a partir do `sondar` (`prproj/originais.py`).

    `trecho`: o arquivo da montagem é um TRECHO do original (o casador, `originais._trecho`: o render da cor voltando) —
    o `<in>`/`<out>` de cada plano dele se desloca pela diferença de TC (`desloc_s`) e o plano ganha a nota (`nota`).

    ⭐ SEQUÊNCIA de imagens (P10): o DPX não tem taxa (o ffprobe inventa 25) — vale `fps_sequencia`, a taxa da montagem;
    a duração é o número de quadros da sequência."""
    seq = quadro_de_sequencia(original)
    fps = float(fps_sequencia if (seq and fps_sequencia) else sonda["fps"])
    base, ntsc = _rate(fps)
    tc = sonda.get("tc") or "00:00:00:00"
    if seq and not sonda.get("tc"):
        # sequência sem TC no cabeçalho: o número do 1º quadro É o TC (a convenção do DPX/EXR de câmera e de scan)
        q = seq[1]
        tc = f"{q // (base * 3600) % 24:02d}:{q // (base * 60) % 60:02d}:{q // base % 60:02d}:{q % base:02d}"
    df = ";" in tc
    caminho = como_o_disco_lista(original)
    if seq:
        caminho = os.path.join(os.path.dirname(caminho), os.path.basename(seq[3]))   # a sintaxe FilmLight
    return {"caminho": caminho, "fps": fps, "timebase": base, "ntsc": ntsc,
            "tc": tc, "tc_quadros": _tc_quadros(tc, base, df), "df": df,
            "quadros": (seq[2] if seq and seq[2] else
                        int(round(float(sonda["dur_s"]) * fps)) if sonda.get("dur_s") else None),
            "w": sonda.get("w") or None, "h": sonda.get("h") or None,
            **({"desloc_s": float(trecho["desloc_s"]), "nota": trecho.get("motivo") or ""} if trecho else {})}


def _caminho_do_file(f: ET.Element) -> str | None:
    pu = f.find("pathurl")
    if pu is None or not pu.text:
        return None
    return urllib.parse.unquote(pu.text.replace("file://localhost", "").replace("file://", ""))


def reescrever(entrada: str, saida: str, decisao: dict[str, dict | None], pasta_offline: str) -> dict[str, str]:
    """Reescreve o xmeml `entrada` em `saida`. `decisao` = {caminho do daily (qualquer normalização): `descrever(...)` do
    original, ou None (ambíguo / sem original → OFFLINE de propósito, para o Baselight não casar por conta própria)}.
    Devolve {daily: o que foi escrito}. Arquivo do xmeml SEM decisão fica como está (e aparece no retorno)."""
    por_nfc = {_nfc(k): v for k, v in decisao.items()}
    arv = ET.parse(entrada)
    feitos: dict[str, str] = {}
    desloc: dict[str, float] = {}
    for f in arv.getroot().iter("file"):
        daily = _caminho_do_file(f)
        if daily is None:
            continue                         # <file id=…/> repetido: só a 1ª aparição tem o caminho
        if _nfc(daily) not in por_nfc:
            feitos[daily] = "sem decisão (mantido)"
            continue
        o = por_nfc[_nfc(daily)]
        pu = f.find("pathurl")
        if o and o.get("desloc_s") and f.get("id"):
            desloc[f.get("id")] = float(o["desloc_s"])
        if o is None:
            nome = PREFIXO_OFFLINE + os.path.basename(daily)
            pu.text = "file://localhost" + urllib.parse.quote(os.path.join(pasta_offline, nome))
            if f.find("name") is not None:
                f.find("name").text = nome
            feitos[daily] = "offline"
            continue
        pu.text = "file://localhost" + urllib.parse.quote(o["caminho"])
        if f.find("name") is not None:
            f.find("name").text = os.path.basename(o["caminho"])
        for r in (f.find("rate"), f.find("timecode/rate"), f.find("media/video/samplecharacteristics/rate")):
            if r is not None:
                r.find("timebase").text, r.find("ntsc").text = str(o["timebase"]), o["ntsc"]
        if o.get("quadros"):
            # ⛔ sem `<duration>` a SEQUÊNCIA de imagens entrou como imagem PARADA (in = out; o daily que o xmeml
            # descrevia não tinha duração legível — 2026-11-22, P10 pelo caminho do MC no app): cria-se quando falta
            d = f.find("duration")
            if d is None:
                d = ET.Element("duration")
                f.insert(list(f).index(f.find("rate")) + 1 if f.find("rate") is not None else 0, d)
            d.text = str(o["quadros"])
        t = f.find("timecode")
        if t is not None:
            t.find("string").text = o["tc"]
            if t.find("frame") is not None:
                t.find("frame").text = str(o["tc_quadros"])
            if t.find("displayformat") is not None:
                t.find("displayformat").text = "DF" if o["df"] else "NDF"
        sc = f.find("media/video/samplecharacteristics")
        if sc is not None and o.get("w") and o.get("h"):
            sc.find("width").text, sc.find("height").text = str(o["w"]), str(o["h"])
        feitos[daily] = o["caminho"]
    _deslocar_trechos(arv.getroot(), desloc)
    _compensar_taxa_nominal(arv.getroot())
    arv.write(saida, encoding="UTF-8", xml_declaration=True)
    return feitos


def _fps_da_sequencia(raiz: ET.Element) -> float:
    r = raiz.find(".//sequence/rate")
    tb = int(r.findtext("timebase"))
    return tb * 1000 / 1001 if r.findtext("ntsc") == "TRUE" else float(tb)


def _taxa(r: ET.Element) -> tuple[int, float]:
    """(timebase nominal, fps verdadeiro) de um `<rate>`."""
    tb = int(r.findtext("timebase"))
    return tb, (tb * 1000 / 1001 if r.findtext("ntsc") == "TRUE" else float(tb))


def _compensar_taxa_nominal(raiz: ET.Element) -> None:
    """⛔ MEDIDO (PRODUCAO-C pela janela do app, Baselight 7.0.3, 2026-11-23): o `bl-conform` converte o `<in>` do
    clipitem para quadros do arquivo pelas taxas NOMINAIS (`in × tb_arquivo / tb_sequência`), ignorando o `ntsc`. Com
    sequência 23,976 e arquivo 25 (ou 100) o ponto sai 0,1 % antes — 6 quadros aos 4 min do arquivo (56 de 74 planos fora
    do ponto). Quando os dois são NTSC (29,97 numa 23,976: o BL08) ou nenhum é, o fator se cancela e nada muda.
    O `<in>` e o `<out>` andam o MESMO Δ = round(in·(k − 1)), k = (fps/tb do arquivo) / (fps/tb da sequência): o
    out − in tem de continuar igual à duração (senão o Baselight faz do plano uma velocidade)."""
    _tb_s, fps_s = _taxa(raiz.find(".//sequence/rate"))
    k_por_id: dict[str, float] = {}
    for f in raiz.iter("file"):
        r = f.find("rate")
        if f.get("id") and f.find("pathurl") is not None and r is not None:
            tb_f, fps_f = _taxa(r)
            k_por_id[f.get("id")] = (fps_f / tb_f) / (fps_s / _tb_s)
    for ci in raiz.iter("clipitem"):
        f = ci.find("file")
        k = k_por_id.get(f.get("id")) if f is not None else None
        if not k or abs(k - 1.0) < 1e-12 or ci.find("in") is None:
            continue
        d = _arredonda(int(ci.findtext("in")) * (k - 1.0))
        if d:
            for tag in ("in", "out"):
                if ci.find(tag) is not None:
                    ci.find(tag).text = str(int(ci.findtext(tag)) + d)


def _deslocar_trechos(raiz: ET.Element, desloc_s_por_id: dict[str, float]) -> None:
    """O `<in>`/`<out>` dos planos cujo arquivo é um TRECHO do original decidido: o in conta desde o início do ARQUIVO
    da montagem (na taxa da timeline); no original, esse início está `desloc_s` adiante. Pelo `id` do `<file>` DO DAILY
    (só a 1ª aparição tem o caminho): outro plano que use o mesmo original direto não se move."""
    if not desloc_s_por_id:
        return
    fps = _fps_da_sequencia(raiz)
    for ci in raiz.iter("clipitem"):
        f = ci.find("file")
        d = desloc_s_por_id.get(f.get("id")) if f is not None else None
        if d:
            q = _arredonda(d * fps)
            for tag in ("in", "out"):
                if ci.find(tag) is not None:
                    ci.find(tag).text = str(int(ci.findtext(tag)) + q)


def notas_dos_trechos(xmeml_da_montagem: str, decisao: dict) -> list[tuple[int, str]]:
    """(quadro de início, nota) de cada plano que veio de um trecho do original — para o marker "[Ciclo]". Lê o xmeml
    ANTES de reescrito (o caminho de cada `<file>` é o da montagem, a chave da `decisao`)."""
    por_nfc = {_nfc(k): v for k, v in decisao.items() if v and v.get("desloc_s")}
    if not por_nfc:
        return []
    raiz = ET.parse(xmeml_da_montagem).getroot()
    nota_por_id = {f.get("id"): por_nfc[_nfc(_caminho_do_file(f))]["nota"] for f in raiz.iter("file")
                   if f.find("pathurl") is not None and _nfc(_caminho_do_file(f) or "") in por_nfc}
    out = []
    for ci in raiz.iter("clipitem"):
        f = ci.find("file")
        if f is not None and f.get("id") in nota_por_id:
            out.append((int(ci.findtext("start")), nota_por_id[f.get("id")]))
    return out


def _arredonda(x: float) -> int:
    """Metade PARA CIMA (o `round` do Python vai ao par, e 117,5 em ponto flutuante sai 117,4999…): o Baselight leu 118."""
    return int(math.floor(x + 0.5 + 1e-6))


def _coberto(ini: int, fim: int, acima: list[tuple[int, int]]) -> bool:
    """[ini, fim) inteiro sob a união dos intervalos `acima` (ordenados)."""
    t = ini
    for a, b in acima:
        if a > t:
            break
        t = max(t, b)
        if t >= fim:
            return True
    return t >= fim


def esperado(xmeml: str) -> list[dict]:
    """Os planos VISÍVEIS (a trilha de vídeo mais alta que cobre cada quadro: aqui, por trilha) do xmeml JÁ reescrito, com o
    1º e o último quadro visível NO ARQUIVO declarado: in = round(in_s × fps_arquivo); out = in + round(dur_s × fps) − 1."""
    raiz = ET.parse(xmeml).getroot()
    seq = raiz.find(".//sequence")
    tl = seq.find("rate")
    fps_tl = float(Fraction(int(tl.findtext("timebase")) * (1000 if tl.findtext("ntsc") == "TRUE" else 1),
                            1001 if tl.findtext("ntsc") == "TRUE" else 1))
    tb_s = int(tl.findtext("timebase"))
    arquivos: dict[str, ET.Element] = {}
    for f in seq.iter("file"):
        if f.find("pathurl") is not None:
            arquivos[f.get("id")] = f
    trilhas = seq.find("media/video").findall("track")
    #: o que cada trilha cobre (as de CIMA escondem as de baixo)
    cobre = [[(int(ci.findtext("start")), int(ci.findtext("end"))) for ci in t.findall("clipitem")
              if ci.findtext("enabled") != "FALSE"] for t in trilhas]
    out = []
    for n, trilha in enumerate(trilhas, start=1):
        acima = sorted(iv for t in cobre[n:] for iv in t)
        for ci in trilha.findall("clipitem"):
            f = arquivos.get(ci.find("file").get("id"))
            if f is None:
                continue
            # ⛔ MEDIDO (BL09 multitrilha, 7.0.3, 2026-11-22): o bl-conform DEIXA FORA o plano coberto INTEIRO por trilhas de
            # cima (o parcialmente coberto entra inteiro, na trilha dele). Esperá-lo casava com o plano de cima no mesmo
            # quadro de início, e o `-replace` TROCAVA a imagem do plano visível pelo arquivo do escondido.
            if _coberto(int(ci.findtext("start")), int(ci.findtext("end")), acima):
                continue
            tb_f, fps_f = _taxa(f.find("rate"))
            ini, fim, entra = int(ci.findtext("start")), int(ci.findtext("end")), int(ci.findtext("in"))
            # pelas taxas NOMINAIS, como o Baselight conta (`_compensar_taxa_nominal`): igual ao tempo verdadeiro quando
            # sequência e arquivo são os dois NTSC ou nenhum; no misto, o `<in>` já veio compensado
            nominal = tb_f / tb_s
            in_f = _arredonda(entra * nominal)
            # ⭐ SEQUÊNCIA de imagens: o Baselight conta o ponto pelo NÚMERO do quadro no nome (BL08, P10: in 1641624 =
            # o 1º quadro 1641600 + 24), não desde zero
            seq = quadro_de_sequencia(_caminho_do_file(f) or "")
            if seq:
                in_f += seq[1]
            dur_f = _arredonda((fim - ini) * nominal)
            caminho_f = _caminho_do_file(f) or ""
            # ⭐ IMAGEM PARADA (não sequência): o Baselight segura o quadro pelo plano todo e o `bl-shots` dá in/out pelo
            # número do FIM do nome ("…530x298.psd.jpg" → 298–420, PRODC pela janela, 2026-11-23) — só o arquivo se confere
            parada = (not seq and os.path.splitext(caminho_f)[1].lower() in _EXT_IMAGEM)
            out.append({"trilha": n, "inicio": ini, "fim": fim, "arquivo": _caminho_do_file(f), "in": in_f,
                        "out": in_f + dur_f - 1, "fps_arquivo": fps_f, "fps_timeline": fps_tl, "parada": parada})
    return out
