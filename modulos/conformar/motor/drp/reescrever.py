"""REESCREVER a timeline do colorista (o caminho B do "Atualizar timeline", decidido em 2026-09-27).

O arquivo de partida é o DRT que o PRÓPRIO Resolve do colorista exportou. Este módulo só:
- lê os itens das trilhas (`itens`);
- apaga itens inteiros, e muda `Start`, `Duration` e `In` dos que andam ou são aparados (`aplicar`);
- troca TODOS os ids do pacote pelo mesmo mapa, inclusive os UTF-16 dentro dos blobs hex.

Nada mais é tocado: os blobs (a correção no `Body`, o `FieldsBlob`), o cabeçalho com a versão
(`DbPrjVer`) e o resto viajam como vieram. Medido (banco `protocolos/drt-drp/estruturas.md`):
- §"A CORREÇÃO DE COR" (19, 2026-09-27): reescrito assim, a correção de cada plano fica;
  trocar só os ids do texto faz a timeline entrar VAZIA, sem erro;
- §"Resolve 19 × 21" (2026-09-28): o item tem os mesmos 39 campos nas duas versões; o corte
  interno, as versões locais, os nós e o adjustment clip aparecem do mesmo jeito.

Os quadros de `itens`/`acoes` contam do INÍCIO da timeline (como a Carta); o DRT guarda o quadro
absoluto (`Start` = início da timeline + quadro), e `inicio_timeline` faz a ponte.
"""

from __future__ import annotations

from .writer import ler_in as _ler_in  # noqa: E402 — o In com fração (`291|f64`)
import os
import re
import uuid
import zipfile

UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
U16 = re.compile(rb"(?:\x00[0-9a-f]){8}\x00-(?:(?:\x00[0-9a-f]){4}\x00-){3}(?:\x00[0-9a-f]){12}")
#: Os itens de uma trilha: planos de vídeo e de áudio, e os GERADORES (os títulos e as notas; o
#: adjustment clip é um `Sm2TiVideoClip`). A API conta estes três no `GetItemListInTrack`.
_ITEM = re.compile(r"(<Element>\s*<(Sm2TiVideoClip|Sm2TiAudioClip|Sm2TiGenerator) DbId=\"([^\"]+)\">(.*?)</\2>\s*</Element>)", re.S)
#: As transições ficam em cima do corte entre dois itens da mesma trilha (Start/Duration próprios).
_TRANSICAO = re.compile(r"(<Element>\s*<Sm2TiTransition DbId=\"([^\"]+)\">(.*?)</Sm2TiTransition>\s*</Element>)", re.S)


def _seq(z: zipfile.ZipFile) -> str:
    return next(n for n in z.namelist() if n.startswith("SeqContainer/") and n.endswith(".xml"))


def _campo(item: str, nome: str) -> str:
    m = re.search(rf"<{nome}>([^<]*)</{nome}>", item)
    return m.group(1) if m else ""


def _trilhas(s: str):
    """[(\"V\"|\"A\", n, início do bloco da trilha, fim)] na ordem do arquivo (vec[0] = V1 / A1)."""
    fora = []
    for vec, letra in (("VideoTrackVec", "V"), ("AudioTrackVec", "A")):
        m = re.search(rf"<{vec}>(.*?)</{vec}>", s, re.S)
        if not m:
            continue
        for n, t in enumerate(re.finditer(r"<Sm2TiTrack DbId=\"[^\"]+\">.*?</Sm2TiTrack>", m.group(1), re.S), 1):
            fora.append((letra, n, m.start(1) + t.start(), m.start(1) + t.end()))
    return fora


def inicio_timeline(drt: str) -> int:
    """O quadro absoluto do início da timeline: o menor `Start` de vídeo, ou 86400 (01:00:00:00 a 24)."""
    starts = [int(i["start"]) for i in itens(drt, absoluto=True) if i["trilha"].startswith("V")]
    return min(starts) if starts else 86400


def itens(drt: str, absoluto: bool = False, inicio: int | None = None) -> list[dict]:
    """`[{id, trilha: "V1", inicio, dur, fonte_in, nome, tipo, start}]` de todas as trilhas."""
    with zipfile.ZipFile(drt) as z:
        s = z.read(_seq(z)).decode("utf-8")
    fora = []
    for letra, n, a, b in _trilhas(s):
        for m in _ITEM.finditer(s, a, b):
            corpo = m.group(4)
            start = int(_campo(corpo, "Start") or 0)
            fora.append({"id": m.group(3), "trilha": f"{letra}{n}", "start": start,
                         "dur": int(_campo(corpo, "Duration") or 0),
                         "fonte_in": int(_ler_in(_campo(corpo, "In"))),
                         "nome": _campo(corpo, "Name"), "tipo": _campo(corpo, "PrettyType") or m.group(2)})
    if not absoluto:
        base = inicio if inicio is not None else min((i["start"] for i in fora if i["trilha"].startswith("V")),
                                                     default=86400)
        for i in fora:
            i["inicio"] = i["start"] - base
    return fora


def contagem(drt: str) -> dict[str, int]:
    """{"V1": n, "A1": n…}: itens + TRANSIÇÕES de cada trilha — o que o `GetItemListInTrack` da API
    conta (MEDIDO 2026-09-28 na PRODA do autor, Resolve 19: a API soma as transições; só os itens
    dava "timeline diferente" com a timeline certa). É a conferência da exportação e da importação."""
    with zipfile.ZipFile(drt) as z:
        s = z.read(_seq(z)).decode("utf-8")
    fora = {}
    for letra, n, a, b in _trilhas(s):
        bloco = s[a:b]
        c = len(_ITEM.findall(bloco)) + len(_TRANSICAO.findall(bloco))
        if c:
            fora[f"{letra}{n}"] = c
    return fora


def _trocar(item: str, nome: str, valor, obrigatorio: bool = False) -> str:
    """Escreve `<nome>valor</nome>`. Se o campo não existe no item: `obrigatorio` para (um corte
    que se perderia em silêncio — revisão 2026-09-28); senão, deixa o item como está."""
    novo = f"<{nome}>{valor}</{nome}>"
    item, n = re.subn(rf"<{nome}>[^<]*</{nome}>|<{nome}/>", lambda _m: novo, item, count=1)
    if not n and obrigatorio:
        raise ValueError(f"um item da timeline de trabalho não tem o campo <{nome}>: não sei aparar "
                         "esse item sem perder o corte — nada foi alterado")
    return item


def aplicar(drt: str, destino: str, acoes: dict, inicio: int,
            mover_quadro=None, so_definidos: bool = False, ids: str = "",
            cortes: set | None = None, rastro: dict | None = None) -> dict:
    """Aplica `acoes` (`{id: {acao, inicio, dur, fonte_in}}`, a saída de
    `atualizar.plano_de_edicao`) no DRT `drt` e grava `destino` com TODOS os ids novos.
    `apagar` tira o item; `mover`/`aparar`/`conferir`/`manter` escrevem Start/Duration/In
    (`conferir` fica no lugar: quem avisa é a execução). Devolve a contagem por ação.

    `cortes`: `{("A", 1, quadro absoluto)}` onde um plano NOVO vai encostar (a casca o insere depois). A
    transição cujo vizinho sai, mas cujo corte continua por causa dele, FICA (autor, 2026-10-01).
    `rastro` (saída): `{("A1", start antes, dur): start depois | None}` de cada transição — para saber onde
    foi parar cada uma que já estava (o ajuste das transições do editor compara na posição NOVA)."""
    with zipfile.ZipFile(drt) as z:
        arqs = {n: z.read(n) for n in z.namelist()}
        nseq = _seq(z)
    s = arqs[nseq].decode("utf-8")
    conta: dict[str, int] = {}

    def mexer(m):
        bloco, tipo, dbid, corpo = m.group(1), m.group(2), m.group(3), m.group(4)
        a = acoes.get(dbid)
        if not a:
            return bloco
        conta[a["acao"]] = conta.get(a["acao"], 0) + 1
        if a["acao"] == "apagar":
            return ""
        novo = _trocar(corpo, "Start", inicio + int(a["inicio"]), obrigatorio=True)
        if a["acao"] == "aparar":
            novo = _trocar(novo, "Duration", int(a["dur"]), obrigatorio=True)
            novo = _trocar(novo, "In", int(a["fonte_in"]), obrigatorio=True)
        return bloco.replace(corpo, novo, 1)

    apagados = {m.group(3) for m in _ITEM.finditer(s) if (acoes.get(m.group(3)) or {}).get("acao") == "apagar"}
    # Trilha a trilha, de trás para a frente (os índices das trilhas anteriores não mudam): os
    # itens e, depois, as transições, que dependem de onde os dois vizinhos foram parar.
    removidas: list[dict] = []
    for letra, n, a, b in reversed(_trilhas(s)):
        bloco = s[a:b]
        pos = {}                                  # id → ((start, fim) antes, (start, fim) depois | None)
        for m in _ITEM.finditer(bloco):
            corpo = m.group(4)
            st, du = int(_campo(corpo, "Start") or 0), int(_campo(corpo, "Duration") or 0)
            ac = acoes.get(m.group(3))
            if ac and ac["acao"] == "apagar":
                depois = None
            elif ac:
                nst = inicio + int(ac["inicio"])
                depois = (nst, nst + (int(ac["dur"]) if ac["acao"] == "aparar" else du))
            else:
                depois = (st, st + du)
            pos[m.group(3)] = ((st, st + du), depois)
        bloco = _ITEM.sub(mexer, bloco)
        bloco = _TRANSICAO.sub(lambda m: _transicao(m, pos, letra, n, removidas, conta, cortes or set(),
                                                    rastro if rastro is not None else {}), bloco)
        s = s[:a] + bloco + s[b:]
    if removidas:
        conta["transicoes_removidas"] = len(removidas)
    arqs[nseq] = s.encode("utf-8")
    fora_do_lugar: list[dict] = []
    if "project.xml" in arqs:
        px = arqs["project.xml"].decode("utf-8")
        # a cor LOCAL de um plano apagado fica órfã num bloco próprio: sai junto
        px = re.sub(r"<Element>\s*<Sm2TiItemLockableBlob\b(?:(?!</Element>).)*?<BlobOwner>([^<]+)</BlobOwner>"
                    r"(?:(?!</Element>).)*?</Sm2TiItemLockableBlob>\s*</Element>\s*",
                    lambda m: "" if m.group(1) in apagados else m.group(0), px, flags=re.S)
        if mover_quadro is not None:
            px, fora_do_lugar = _mover_marcadores(px, mover_quadro)
        arqs["project.xml"] = px.encode("utf-8")
    _gravar_com_ids_novos(arqs, destino, so_definidos=so_definidos, ids=ids)
    conta["marcadores_fora_do_lugar"] = len(fora_do_lugar)
    return conta


# ── os MARCADORES DE TIMELINE do colorista (medido 2026-09-28, Resolve 19) ─────────────────────
# Moram no `Sm2SequenceLockableBlob` do `project.xml`: `BlobData` = [u32 0x2711][u32 n][0x81 + zstd]
# e dentro o protobuf { 2: { 1: entrada … } }, cada entrada { 1: quadro (do início da timeline),
# 2: [u32 2][u32 n] + o resto (cor, nota, duração, nome, customData no campo 6) }. Só o quadro muda;
# o resto de cada entrada viaja byte a byte.

def _varint(b: bytes, i: int) -> tuple[int, int]:
    n = s = 0
    while True:
        c = b[i]
        n |= (c & 0x7F) << s
        i += 1
        if not c & 0x80:
            return n, i
        s += 7


def _campos(b: bytes) -> list[tuple[int, int, bytes | int]]:
    fora, i = [], 0
    while i < len(b):
        chave, i = _varint(b, i)
        num, tipo = chave >> 3, chave & 7
        if tipo == 0:
            v, i = _varint(b, i)
        elif tipo == 2:
            n, i = _varint(b, i)
            v, i = b[i:i + n], i + n
        elif tipo == 5:
            v, i = b[i:i + 4], i + 4
        elif tipo == 1:
            v, i = b[i:i + 8], i + 8
        else:
            raise ValueError(f"protobuf com tipo {tipo} nos marcadores")
        fora.append((num, tipo, v))
    return fora


def _escrever(campos) -> bytes:
    from drp.sinais import _varint as vi
    fora = b""
    for num, tipo, v in campos:
        fora += vi((num << 3) | tipo)
        if tipo == 0:
            fora += vi(v)
        elif tipo == 2:
            fora += vi(len(v)) + v
        else:
            fora += v
    return fora


def quadros_dos_marcadores(drt: str) -> list[int]:
    """Os quadros dos marcadores de timeline de um DRT (do início da timeline), nas duas formas
    (19 e 21). Lê pelo MESMO caminho que os move: o que este não vê, o Atualizar não move."""
    with zipfile.ZipFile(drt) as z:
        px = z.read("project.xml").decode("utf-8") if "project.xml" in z.namelist() else ""
    vistos: list[int] = []
    _mover_marcadores(px, lambda q: (vistos.append(q) or q, True))
    return sorted(vistos)


def _mover_marcadores(px: str, mover_quadro) -> tuple[str, list[dict]]:
    import zstandard

    from drp import sinais
    from drp.ba_mapa import ler_mapa

    m = re.search(r"(<Sm2SequenceLockableBlob\b.*?<FieldsBlob>)(\w+)(</FieldsBlob>)", px, re.S)
    if not m:
        return px, []
    _v, itens_mapa, _r = ler_mapa(bytes.fromhex(m.group(2)))
    if len(itens_mapa) != 1:
        # forma não medida (o mapa só com "BlobData" é o que conhecemos): não mexe, e avisa
        return px, [{"quadro": None, "novo": None, "erro": "bloco de marcadores com forma desconhecida"}]
    raw = itens_mapa[0][1][2]
    comprimido = raw[8:9] == b"\x81"
    pb = zstandard.ZstdDecompressor().decompress(raw[9:], max_output_size=1 << 24) if comprimido else raw[9:]
    fora_do_lugar = []
    topo = []
    vistos = 0
    for num, tipo, v in _campos(pb):
        if num == 2 and tipo == 2:
            entradas = []
            for n1, t1, e in _campos(v):
                # ⚠️ DUAS FORMAS, por versão do Resolve (medido 2026-10-01, Studio 21.1 × 19.0.0b):
                #   19: { 2: { 1: entrada } }, entrada { 1: QUADRO (varint), 2: … }
                #   21: { 2: { 2: entrada } }, entrada { 1: { 1: MEIO-QUADRO (varint) }, 2: … }
                # O 21 LÊ a forma do 19 (os Sinais do writer entram certos), mas EXPORTA a dele: quadro
                # × 2 a 23,976 (7 → 14, 101 → 202, 333 → 666). Só esta forma andava; no 21 nenhum
                # marcador se movia, em silêncio (o autor viu o da velocidade 855 quadros fora do plano).
                # ⭐ Medido 2026-10-01: o meio-quadro é × 2 em QUALQUER taxa (24, 23,976, 25, 29,97: 7 → 14,
                # 101 → 202, 333 → 666). Cada forma só no SEU campo (revisão de código): o 19 no 1 com o
                # quadro direto, o 21 no 2 com a submensagem — nada de reinterpretar outro campo como quadro.
                if n1 in (1, 2) and t1 == 2:
                    campos = _campos(e)
                    for k, (n2, t2, q) in enumerate(campos):
                        if n2 != 1 or (n1 == 1 and t2 != 0) or (n1 == 2 and t2 != 2):
                            continue
                        if t2 == 0:                                   # forma do 19
                            vistos += 1
                            novo, ok = mover_quadro(q)
                            campos[k] = (1, 0, max(0, int(novo)))
                        elif t2 == 2:                                 # forma do 21
                            sub = _campos(q)
                            j = next((j for j, (n3, t3, _m) in enumerate(sub) if n3 == 1 and t3 == 0), None)
                            if j is None:
                                continue
                            meio = sub[j][2]
                            vistos += 1
                            q = meio // 2
                            novo, ok = mover_quadro(q)
                            sub[j] = (1, 0, max(0, int(novo)) * 2 + meio % 2)   # o subquadro fica
                            campos[k] = (1, 2, _escrever(sub))
                        else:
                            continue
                        if not ok:
                            fora_do_lugar.append({"quadro": q, "novo": novo})
                    e = _escrever(campos)
                entradas.append((n1, t1, e))
            v = _escrever(entradas)
        topo.append((num, tipo, v))
    if not vistos and any(n == 2 and t == 2 and v for n, t, v in _campos(pb)):
        # ⛔ havia marcadores e nenhum foi reconhecido: forma nova de outra versão. Avisar, não calar.
        return px, [{"quadro": None, "novo": None, "erro": "bloco de marcadores com forma desconhecida"}]
    novo_blob = sinais._fields_blob(sinais._blob_data(_escrever(topo), comprimir=comprimido))
    return px[:m.start(2)] + novo_blob + px[m.end(2):], fora_do_lugar


def _transicao(m, pos: dict, letra: str, n: int, removidas: list, conta: dict, cortes: set = frozenset(),
               rastro: dict | None = None) -> str:
    """Uma transição anda com o CORTE em que está: acha os vizinhos (o item que termina e o que
    começa dentro dela) e vê onde eles foram parar. Se o corte deixou de existir (um vizinho saiu,
    ou os dois não estão mais colados), a transição sai e é contada — nada some sem aviso."""
    bloco, corpo = m.group(1), m.group(3)
    ts, td = int(_campo(corpo, "Start") or 0), int(_campo(corpo, "Duration") or 0)
    esq = next((d for (a0, f0), d in pos.values() if ts <= f0 <= ts + td and not (ts < a0 < ts + td)), "x")
    dir_ = next((d for (a0, f0), d in pos.values() if ts <= a0 <= ts + td and not (ts < f0 < ts + td)), "x")
    tem_esq, tem_dir = esq != "x", dir_ != "x"
    antes_dir = next(((a0, f0) for (a0, f0), d in pos.values() if ts <= a0 <= ts + td and d is dir_), None)
    antes_esq = next(((a0, f0) for (a0, f0), d in pos.values() if ts <= f0 <= ts + td and d is esq), None)
    novo_ts = None
    if tem_esq and tem_dir:
        if esq is not None and dir_ is not None and esq[1] == dir_[0]:
            novo_ts = dir_[0] - (antes_dir[0] - ts)
        # Um vizinho sai, mas um plano NOVO entra encostado no MESMO corte (o take trocado): a transição
        # do editor fica, no corte do vizinho que continua. Medido no Resolve 21 (2026-10-01): ela
        # sobrevive à importação sem o vizinho, e o plano inserido depois pela API encosta nela.
        elif esq is None and dir_ is not None and (letra, n, dir_[0]) in cortes:
            novo_ts = dir_[0] - (antes_dir[0] - ts)
        elif dir_ is None and esq is not None and (letra, n, esq[1]) in cortes:
            novo_ts = esq[1] - (antes_esq[1] - ts)
    elif tem_dir and dir_ is not None:
        novo_ts = ts + (dir_[0] - antes_dir[0])
    elif tem_esq and esq is not None:
        novo_ts = ts + (esq[1] - antes_esq[1])
    if rastro is not None:
        rastro[(f"{letra}{n}", ts, td)] = novo_ts
    if novo_ts is None:
        removidas.append({"trilha": f"{letra}{n}", "start": ts, "dur": td, "tipo": _campo(corpo, "PrettyType")})
        return ""
    if novo_ts != ts:
        conta["transicoes_movidas"] = conta.get("transicoes_movidas", 0) + 1
        return bloco.replace(corpo, _trocar(corpo, "Start", novo_ts), 1)
    return bloco


def transicoes(drt: str) -> list[dict]:
    """`[{trilha: "A1", start, dur, nome}]` das transições de um DRT (quadros absolutos)."""
    with zipfile.ZipFile(drt) as z:
        s = z.read(_seq(z)).decode("utf-8")
    fora = []
    for letra, n, a, b in _trilhas(s):
        for m in _TRANSICAO.finditer(s, a, b):
            corpo = m.group(3)
            fora.append({"trilha": f"{letra}{n}", "start": int(_campo(corpo, "Start") or 0),
                         "dur": int(_campo(corpo, "Duration") or 0), "nome": _campo(corpo, "PrettyType")})
    return fora


def ajustar_transicoes(drt: str, acrescentar: list[dict], tirar: set) -> dict:
    """Escreve as transições NOVAS do editor e tira as que ele tirou, no DRT já reescrito (no lugar).

    `acrescentar`: `[{trilha: "A1", start, dur, align, audio}]` — o bloco é o do writer do Trazer
    (`writer._make_transition`: Cross Dissolve no vídeo, Cross Fade 0DB no áudio), na ordem de Start.
    `tirar`: `{("A1", start, dur)}`. Autor, 2026-10-01: "a atualização deve manter transição, nada deve
    ser perdido" — a API do Resolve 19 não cria transição; no DRT ela entra como as do Trazer."""
    from drp.writer import _make_transition

    with zipfile.ZipFile(drt) as z:
        arqs = {n: z.read(n) for n in z.namelist()}
        nseq = _seq(z)
    s = arqs[nseq].decode("utf-8")
    conta = {"transicoes_novas": 0, "transicoes_tiradas": 0}
    por_trilha: dict[str, list[dict]] = {}
    for t in acrescentar:
        por_trilha.setdefault(t["trilha"], []).append(t)
    for letra, n, a, b in reversed(_trilhas(s)):
        nome = f"{letra}{n}"
        bloco = s[a:b]
        if tirar:
            def fora(m):
                corpo = m.group(3)
                chave = (nome, int(_campo(corpo, "Start") or 0), int(_campo(corpo, "Duration") or 0))
                if chave in tirar:
                    conta["transicoes_tiradas"] += 1
                    return ""
                return m.group(1)
            bloco = _TRANSICAO.sub(fora, bloco)
        for t in sorted(por_trilha.get(nome) or [], key=lambda t: -int(t["start"])):
            novo = "<Element>" + _make_transition(int(t["start"]), int(t["dur"]), int(t["align"]),
                                                  kind="audio" if t.get("audio") else "video") + "</Element>"
            # antes do primeiro item (clipe ou transição) que começa DEPOIS dela; senão no fim da lista
            itens = [m for rx in (_ITEM, _TRANSICAO) for m in rx.finditer(bloco)]
            depois = sorted((m.start() for m in itens if int(_campo(m.group(0), "Start") or 0) >= int(t["start"])))
            if depois:
                pos = depois[0]
            else:
                fim = bloco.rfind("</Items>")
                if fim < 0:
                    continue                      # trilha sem lista de itens: não se inventa
                pos = fim
            bloco = bloco[:pos] + novo + bloco[pos:]
            conta["transicoes_novas"] += 1
        s = s[:a] + bloco + s[b:]
    arqs[nseq] = s.encode("utf-8")
    tmp = drt + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        for n, v in arqs.items():
            z.writestr(n, v)
    os.replace(tmp, drt)
    return conta


def _ids_da_timeline(arqs: dict) -> set[str]:
    """Os DbIds que são DA TIMELINE: tudo o que a sequência define (trilhas, itens, versões de
    correção), o bloco `Sm2MpTimelineClip` do pool (com a `Sm2Timeline` e a `Sm2Sequence`) e os
    blocos do `project.xml`. Ficam de fora os clipes de MÍDIA do pool e a pasta Master."""
    fora: set[str] = set()
    for n, b in arqs.items():
        if not n.endswith(".xml"):
            continue
        t = b.decode("utf-8")
        if n.startswith("SeqContainer/") or n == "project.xml":
            fora |= set(re.findall(r'DbId="([0-9a-f-]{36})"', t))
        else:
            for m in re.finditer(r"<Sm2MpTimelineClip DbId=.*?</Sm2MpTimelineClip>", t, re.S):
                fora |= set(re.findall(r'DbId="([0-9a-f-]{36})"', m.group(0)))
    return fora


def _gravar_com_ids_novos(arqs: dict, destino: str, so_definidos: bool = False, ids: str = "") -> None:
    """O MESMO mapa velho → novo no texto e nos UTF-16 dentro dos blobs hex (medido: sem os blobs,
    a timeline entra vazia). O nome do arquivo da sequência leva o id dela: troca junto.

    `ids` (U02, 2026-09-28, medindo a queda do Resolve 19 ao importar o reescrito da PRODA):
    - `"todos"`: todo uuid do pacote (o jeito do U01) — na PRODA, TRAVOU o Resolve sem edição nenhuma;
    - `"definidos"`: só os `DbId` definidos no pacote — na PRODA, DERRUBOU o Resolve;
    - `"timeline"`: só os da timeline (`_ids_da_timeline`); a mídia e a pasta ficam;
    - `"nenhum"`: nenhum (o exportado como veio importou na cópia do projeto)."""
    ids = ids or ("definidos" if so_definidos else "timeline")
    mapa: dict[str, str] = {}
    trocar: set[str] | None = None
    if ids == "definidos":
        trocar = set()
        for n, b in arqs.items():
            if n.endswith(".xml"):
                trocar |= set(re.findall(r'DbId="([0-9a-f-]{36})"', b.decode("utf-8")))
    elif ids == "timeline":
        trocar = _ids_da_timeline(arqs)
    elif ids == "nenhum":
        trocar = set()

    def novo(velho: str) -> str:
        if trocar is not None and velho not in trocar:
            return velho
        return mapa.setdefault(velho, str(uuid.uuid4()))

    def blob(m):
        raw = bytes.fromhex(m.group(1))
        return ">" + U16.sub(lambda q: novo(q.group(0).decode("utf-16-be")).encode("utf-16-be"), raw).hex() + "<"

    # Só o XML é texto; qualquer outra parte do pacote passa intacta, em bytes (revisão 2026-09-28).
    saida = {}
    for n, b in arqs.items():
        if n.endswith(".xml"):
            t = UUID.sub(lambda m: novo(m.group(0)), b.decode("utf-8"))
            saida[n] = re.sub(r">([0-9a-f]{40,})<", blob, t).encode("utf-8")
        else:
            saida[n] = b
    with zipfile.ZipFile(destino, "w", zipfile.ZIP_DEFLATED) as z:
        for n, b in saida.items():
            z.writestr(UUID.sub(lambda m: mapa.get(m.group(0), m.group(0)), n), b)
