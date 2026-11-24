"""O que o Media Composer lê de um Broadcast WAV de GRAVADOR ao linkar (bext + iXML) — e como ele grava na bin.

⚠️ CÓPIA de `_DeLaPraCa/motor/media/bwf.py` (commit `9aab180`, 2026-11-01), sem mudança. Lá ela é provada
14/14 contra as bins do MC (`_DeLaPraCa/tests/test_audio_como_o_avid.py`). Mudou lá, traga para cá (e vice-versa):
dois leitores do mesmo formato divergem calados. Aqui ela serve ao som GERENCIADO (`avid/som_gerenciado.py`).

MEDIDO em 2026-10-25 (MC 25.12, Mac; o autor linkou pelo Source Browser três WAV do PRODC gravados num Sound Devices
MixPre-6 — LOCAL-3-001 4 canais, FAIXA-W-C4-002 1 canal, FAIXA-W-C3-003 2 canais):

    nome do master      = sSCENE + "/" + sTAKE           ("FAIXA-W-C4/002": a CENA e o TAKE, não o arquivo — por
                                                           isso o "-" parece virar "/" e a extensão some)
    _USER.UBITS         = sUBITS
    _USER.TapeID        = sFILENAME (o arquivo, com a extensão)
    _USER.Shoot Date    = OriginationDate + OriginationTime do bext ("2022-04-07 16:29:30")
    _USER.Scene / Take  = sSCENE / sTAKE
    _USER.TRK1…n        = os nomes das trilhas na ORDEM do arquivo, renumerados (o MixPre grava sTRK3=BOOM no 1º canal
                          de um mono; o MC escreve TRK1=BOOM) — só do <TRACK_LIST> do iXML, pelo INTERLEAVE_INDEX
                          (laboratório abaixo: sTRK1 no bext sem iXML, e um TRACK_LIST sem INTERLEAVE_INDEX nem
                          TRACK_COUNT, não deram TRK nenhum; qual dos dois o MC exige não está separado)
    _USER.TapeID        = sFILENAME; sem ele (cena/take só no iXML), o nome do arquivo
    _USER.Production    = <PROJECT> do iXML ("04-07-22")
    _USER.Circled       = sCIRCLED (FALSE → "no", TRUE → "yes")
    a fonte de TAPE     = sTAPE ("220407"); a fonte de ARQUIVO = o nome do arquivo

`como_o_avid(caminho)` devolve isso para o áudio que o app INJETA (`avb_bin/audio.autorar_masters`): sem ele, o master
se chamava pelo arquivo e herdava a cena/as trilhas do MOLDE.

WAV SEM cena e take (música, efeito; medido na bin do laboratório abaixo) — o MC grava só três colunas:

    nome do master      = o nome do arquivo COM a extensão, como está
    _USER.TapeID        = o nome do arquivo (com acento: um bloco `00 00 + UTF-8 + 00`, não texto)
    _USER.Shoot Date    = a data + hora do bext; SEM bext, a data de modificação do ARQUIVO, hora local e SEM zeros
                          ("2026-10-25 9:45:19", "2023-9-17 19:0:9" — era isso o "16:4:3" torto dos moldes antigos)
    _USER.Soundroll TC Rate = "25" — em todos (com e sem bext, projeto 23,976); a origem não está medida

Antes (até 2026-10-25) o WAV sem cena devolvia None e o master injetado ficava com o `_USER` do MOLDE: a data do
arquivo de quem foi neutralizado e, nos moldes de gravador (3/4/5 canais), a cena, o take e as trilhas de outro WAV.

LABORATÓRIO (mesmo dia, 11 WAV sintéticos, `laboratorio-de-midia/lab/bancadas/avid/nomes_audio.py`, AMA Management
limpa, link pelo Source Browser): a regra é a CENA + o TAKE (no bext OU só no iXML) — sem eles, o nome do arquivo com a
extensão como está (`.wav` minúsculo fica minúsculo); `;` NÃO é trocado (nem no nome do arquivo, nem na cena: `CENA;6/001`);
take com letra (`3A`) vale; nome longo não trunca; com acento, o nome sai certo e o TapeID vai em UTF-8 (o diálogo de TC
mostrou o acento quebrado). O `;` → `_` que o autor viu no PRODUCAO-A NÃO vem do link no MC 25.12 do Mac.
"""

from __future__ import annotations

import os
import re
import struct
import time
import unicodedata

#: o quanto ler procurando os blocos — o bext vem no começo; o iXML do MixPre também (antes do `data`)
_LIMITE = 64 * 1024 * 1024


def _blocos(caminho: str) -> dict[str, bytes]:
    """Os blocos `bext` e `iXML` de um RIFF/RF64 WAV (os outros não são lidos: o `data` é pulado pelo tamanho) e
    `WAVE` (vazio) quando o arquivo é WAV — para separar "WAV sem bext" de "não é WAV"."""
    fora: dict[str, bytes] = {}
    with open(caminho, "rb") as f:
        cab = f.read(12)
        if len(cab) < 12 or cab[:4] not in (b"RIFF", b"RF64") or cab[8:12] != b"WAVE":
            return fora
        fora["WAVE"] = b""
        pos = 12
        while pos < _LIMITE:
            f.seek(pos)
            h = f.read(8)
            if len(h) < 8:
                break
            cid, tam = h[:4], struct.unpack("<I", h[4:])[0]
            if cid in (b"bext", b"iXML", b"fmt ") and tam < 4 * 1024 * 1024:
                fora[cid.decode()] = f.read(tam)
            if cid == b"data" and tam == 0xFFFFFFFF:     # RF64: o tamanho de verdade está no ds64 — paramos aqui
                break
            pos += 8 + tam + (tam & 1)
    return fora


def ler(caminho: str) -> dict:
    """`{wav: True, desc: {chave: valor} do texto do bext (sSCENE=…), data, hora, ixml: texto}` — vazio se não for WAV."""
    try:
        b = _blocos(caminho)
    except OSError:
        return {}
    if "WAVE" not in b:
        return {}
    r: dict = {"wav": True}
    bext = b.get("bext")
    if bext and len(bext) >= 346:
        texto = bext[:256].split(b"\x00", 1)[0].decode("latin-1", "replace")
        r["desc"] = dict(m.groups() for m in re.finditer(r"s?([A-Za-z0-9_]+)=([^\r\n]*)", texto))
        r["data"] = bext[320:330].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
        r["hora"] = bext[330:338].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()
    if b.get("iXML"):
        r["ixml"] = b["iXML"].decode("utf-8", "replace")
    return r


def identidade(caminho: str) -> dict:
    """De ONDE veio este áudio, pelo bext — o que sobrevive à troca de nome entre cópias (2026-10-28).

    `{origem, referencia, amostra_inicial, bits, canais}`; vazio se não for WAV. Medido no PRODUCAO-A: o
    `24;23;20 CB.wav` do Pro Tools (24 bits) e o `24_23_20 CB.wav` convertido pelo ffmpeg (16 bits) têm a MESMA
    `referencia` e a MESMA `amostra_inicial` — é o mesmo áudio em duas cópias. Origens diferentes com o mesmo nome =
    áudios diferentes (versão de aprovação × final). Serve para EXPLICAR o empate ao editor, nunca para escolher por
    ele (autor, 2026-09-27: empate no casamento é do editor)."""
    try:
        b = _blocos(caminho)
    except OSError:
        return {}
    if "WAVE" not in b:
        return {}
    r: dict = {}
    fmt = b.get("fmt ")
    if fmt and len(fmt) >= 16:
        r["canais"] = struct.unpack("<H", fmt[2:4])[0]
        r["bits"] = struct.unpack("<H", fmt[14:16])[0]
    bext = b.get("bext")
    if bext and len(bext) >= 346:
        texto = lambda a, z: bext[a:z].split(b"\x00", 1)[0].decode("latin-1", "replace").strip()  # noqa: E731
        r["origem"] = texto(256, 288)
        r["referencia"] = texto(288, 320)
        baixo, alto = struct.unpack("<II", bext[338:346])
        r["amostra_inicial"] = (alto << 32) | baixo
    return r


def _tag(xml: str, nome: str) -> str | None:
    m = re.search(rf"<{nome}>([^<]*)</{nome}>", xml or "")
    return m.group(1).strip() if m else None


def _trilhas(meta: dict) -> dict[int, str]:
    """`{n: nome}` das trilhas como o MC as numera: o <TRACK_LIST> do iXML pelo INTERLEAVE_INDEX (a posição no
    arquivo; o CHANNEL_INDEX é o canal do gravador). Trilha sem INTERLEAVE_INDEX e os sTRKn do bext não contam (ver o
    cabeçalho)."""
    fora: dict[int, str] = {}
    for t in re.findall(r"<TRACK>(.*?)</TRACK>", meta.get("ixml") or "", re.S):
        idx, nome = _tag(t, "INTERLEAVE_INDEX"), _tag(t, "NAME")
        if idx and idx.isdigit() and nome:
            fora[int(idx)] = nome
    return dict(sorted(fora.items()))


def _data_do_arquivo(caminho: str) -> str:
    """A data de modificação do arquivo como o MC a grava no Shoot Date de um WAV sem bext: hora local, sem zeros."""
    t = time.localtime(os.stat(caminho).st_mtime)
    return f"{t.tm_year}-{t.tm_mon}-{t.tm_mday} {t.tm_hour}:{t.tm_min}:{t.tm_sec}"


def _texto_do_avid(valor: str) -> str | bytearray:
    """Texto ASCII vai como texto; com acento o MC grava um bloco `00 00 + UTF-8 + 00` (medido no TapeID)."""
    return valor if valor.isascii() else bytearray(b"\x00\x00" + valor.encode("utf-8") + b"\x00")


def _sem_cena(caminho: str, meta: dict) -> dict:
    """O WAV sem cena e take: o nome do arquivo, o TapeID, o Shoot Date e o Soundroll TC Rate (ver o cabeçalho)."""
    arquivo = unicodedata.normalize("NFC", os.path.basename(caminho))   # o MC grava em NFC; o exFAT lista em NFD
    if meta.get("data"):
        data = re.sub(r"[^0-9]", "-", meta["data"])
        hora = re.sub(r"[^0-9]", ":", meta.get("hora") or "")
        quando = f"{data} {hora}".strip()
    else:
        quando = _data_do_arquivo(caminho)
    user = {"TapeID": _texto_do_avid(arquivo), "Shoot Date": quando, "Soundroll TC Rate": "25"}
    return {"nome": arquivo, "user": user, "tape": None}


def como_o_avid(caminho: str) -> dict | None:
    """`{nome, user, tape}` como o MC grava este WAV ao linkar (ver o cabeçalho), ou None (não é WAV)."""
    meta = ler(caminho)
    if not meta:
        return None
    desc = {k.upper(): v for k, v in (meta.get("desc") or {}).items()}
    xml = meta.get("ixml") or ""
    cena = desc.get("SCENE") or _tag(xml, "SCENE")
    take = desc.get("TAKE") or _tag(xml, "TAKE")
    if not cena or not take:
        return _sem_cena(caminho, meta)
    user: dict[str, str] = {}
    if desc.get("UBITS"):
        user["UBITS"] = desc["UBITS"]
    user["TapeID"] = desc.get("FILENAME") or _texto_do_avid(unicodedata.normalize("NFC", os.path.basename(caminho)))
    if meta.get("data"):
        # o bext grava "aaaa-mm-dd" e "hh:mm:ss" (a norma aceita outros separadores; o MC escreve com - e :)
        data = re.sub(r"[^0-9]", "-", meta["data"])
        hora = re.sub(r"[^0-9]", ":", meta.get("hora") or "")
        user["Shoot Date"] = f"{data} {hora}".strip()
    user["Scene"], user["Take"] = cena, take
    for i, nome in _trilhas(meta).items():
        user[f"TRK{i}"] = nome
    projeto = _tag(xml, "PROJECT")
    if projeto:
        user["Production"] = projeto
    circ = (desc.get("CIRCLED") or _tag(xml, "CIRCLED") or "").upper()
    if circ in ("TRUE", "FALSE"):
        user["Circled"] = "yes" if circ == "TRUE" else "no"
    return {"nome": f"{cena}/{take}", "user": user, "tape": desc.get("TAPE") or _tag(xml, "TAPE")}
