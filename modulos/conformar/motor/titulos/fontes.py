"""As fontes instaladas NESTA máquina: nome PostScript → família, face e ascendente.

O Premiere grava no título o nome PostScript da fonte (`Optima-Regular`, `ArialMT`, `Monaco`); o
Text do Resolve pede a FAMÍLIA e a FACE (`Optima` + `Regular`, `Arial` + `Regular`). A tabela
`name` de cada arquivo de fonte diz as duas coisas (ids 6 = PostScript, 16/17 = família e face
tipográficas, 1/2 = as antigas); a `hhea` dá a ascendente, que posiciona a linha de base quando o
Text é ancorado no topo.

Medido em 2026-10-04 (Mac, Resolve 21.1, PRODB a 2880×1620): o topo da caixa do Text fica a
`ascendente da hhea × corpo` acima da linha de base (Monaco 1,0; Optima 0,92), a menos de 3 px.
No Windows (Resolve 19, medido no mesmo dia) valem as métricas do DirectWrite: `winAscent`, ou a
`typo` quando a fonte liga `USE_TYPO_METRICS` (`_metricas_directwrite`). O índice usa as da
plataforma em que roda, que é a do Resolve que importa o DRT (o motor roda ao lado da casca).

⚠️ A fonte tem de existir na máquina ONDE O RESOLVE ABRE a timeline, não só nesta: o índice daqui
só serve para traduzir o nome; quem recebe precisa da fonte instalada. Um DRT gerado num sistema e
aberto no outro desloca a linha de base em (win − hhea) × corpo nas fontes em que elas divergem.

Banco: `protocolos/drt-drp/dados/text-gerador.json` e a linha "pastas de fontes" da
`transversal/matriz-de-plataforma.md`.
"""

from __future__ import annotations

import glob
import os
import re
import struct
import sys

_EXTENSOES = (".ttf", ".otf", ".ttc", ".otc", ".dfont")


def pasta_adobe_fonts() -> str:
    """Onde o Creative Cloud guarda as fontes ATIVADAS do Adobe Fonts: arquivos ocultos com nome de
    número (no Mac `.1131.otf`; no Windows `1131`, sem extensão — medido 2026-10-04, 18 faces lidas). Valem em qualquer
    programa da máquina enquanto o Creative Cloud está logado; não podem ir para outra máquina."""
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or "", "Adobe", "CoreSync", "plugins", "livetype", "r")
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support", "Adobe", "CoreSync",
                        "plugins", "livetype", ".r")


def pastas_de_fontes() -> list[str]:
    """As pastas de fontes do sistema e do usuário, nas duas plataformas (a do Adobe Fonts no fim)."""
    if sys.platform == "win32":
        win = os.environ.get("WINDIR") or r"C:\Windows"
        local = os.environ.get("LOCALAPPDATA") or ""
        return [os.path.join(win, "Fonts")] + ([os.path.join(local, "Microsoft", "Windows", "Fonts")]
                                                if local else []) + [pasta_adobe_fonts()]
    casa = os.path.expanduser("~")
    pastas = ["/System/Library/Fonts", "/System/Library/Fonts/Supplemental", "/Library/Fonts",
              os.path.join(casa, "Library", "Fonts")]
    # Fontes que o macOS baixa sob demanda (Font Book › "Baixar") moram nos ativos do sistema.
    pastas += glob.glob("/System/Library/AssetsV2/com_apple_MobileAsset_Font*/*/AssetData")
    return pastas + [pasta_adobe_fonts()]


def _faces_do_arquivo(caminho: str):
    """(nomes, ascendente) de cada face do arquivo. Lê só o diretório e as tabelas `name`,
    `head` e `hhea` (uma coleção .ttc pode ter dezenas de MB)."""
    with open(caminho, "rb") as fh:
        def ler(pos: int, n: int) -> bytes:
            fh.seek(pos)
            return fh.read(n)
        cab = ler(0, 12)
        if len(cab) < 12:
            return
        inicios = [0]
        if cab[:4] == b"ttcf":
            n = struct.unpack(">I", cab[8:12])[0]
            if n > 256:
                return
            inicios = list(struct.unpack(">%dI" % n, ler(12, 4 * n)))
        for ini in inicios:
            nt = struct.unpack(">H", ler(ini + 4, 2))[0]
            dire = ler(ini + 12, 16 * nt)
            tabs = {}
            for i in range(nt):
                tag, _soma, pos, tam = struct.unpack(">4sIII", dire[16 * i:16 * i + 16])
                tabs[tag] = (pos, tam)
            if b"name" not in tabs or b"head" not in tabs or b"hhea" not in tabs:
                continue
            pos, tam = tabs[b"name"]
            nome = ler(pos, tam)
            cnt, area = struct.unpack(">HH", nome[2:6])
            nomes: dict[int, str] = {}
            for i in range(cnt):
                pid, _eid, lid, nid, n, off = struct.unpack(">6H", nome[6 + 12 * i:18 + 12 * i])
                bruto = nome[area + off:area + off + n]
                if pid == 3 and lid == 0x409:          # Windows, inglês: o nome que vale
                    nomes[nid] = bruto.decode("utf-16-be", "replace")
                elif pid == 1 and lid == 0 and nid not in nomes:
                    nomes[nid] = bruto.decode("mac_roman", "replace")
            upm = struct.unpack(">H", ler(tabs[b"head"][0] + 18, 2))[0] or 1000
            asc, desc, gap = struct.unpack(">hhh", ler(tabs[b"hhea"][0] + 4, 6))
            os2 = ler(tabs[b"OS/2"][0], 78) if b"OS/2" in tabs else b""
            if sys.platform == "win32" and len(os2) >= 78:
                yield nomes, *_metricas_directwrite(os2, asc, desc, gap, upm)
                continue
            yield nomes, asc / upm, (asc - desc + max(0, gap)) / upm


def _metricas_directwrite(os2: bytes, asc: int, desc: int, gap: int, upm: int) -> tuple[float, float]:
    """(ascendente, linha) como o Resolve do WINDOWS posiciona o Text: as métricas do DirectWrite.

    MEDIDO 2026-10-04 (Resolve Studio 19.0.0b.59, Win11), Text de Size 200/150, topo fixo, pela imagem:
      - sem `USE_TYPO_METRICS` (bit 7 do `fsSelection`): ascendente = `usWinAscent` — Palatino
        Linotype, base em 426 px (win 1,050; a `hhea`, 0,732, daria 362); Arial (iguais) 396/397;
      - com a marca: `sTypoAscender` — Gabriola 354 (typo 0,684 → 353; win daria 454), Sitka 366/367;
      - linha natural: com a marca, `typo` asc − desc + gap (Gabriola 1,700, Sitka 1,253 medidos);
        sem, `win` asc + desc + a sobra do intervalo da `hhea` (Palatino 1,349 medido).
    No Mac (Resolve 21.1) vale a `hhea` (Monaco 1,0, Optima 0,92 — conferido pela imagem)."""
    fs = struct.unpack(">H", os2[62:64])[0]
    t_asc, t_desc, t_gap = struct.unpack(">hhh", os2[68:74])
    w_asc, w_desc = struct.unpack(">HH", os2[74:78])
    if fs & 0x80:
        return t_asc / upm, (t_asc - t_desc + max(0, t_gap)) / upm
    sobra = max(0, gap - ((w_asc + w_desc) - (asc - desc)))
    return w_asc / upm, (w_asc + w_desc + sobra) / upm


_INDICE: dict[str, dict] | None = None


def indice() -> dict[str, dict]:
    """`{postscript (minúsculo): {familia, face, ascendente, linha, adobe, arquivo}}`, montado uma vez.
    `linha` = altura natural da linha (ascendente + descendente + intervalo da `hhea`), em corpos."""
    global _INDICE
    if _INDICE is not None:
        return _INDICE
    idx: dict[str, dict] = {}
    adobe = os.path.normcase(pasta_adobe_fonts())
    for pasta in pastas_de_fontes():
        da_adobe = os.path.normcase(pasta) == adobe
        for raiz, _dirs, arquivos in os.walk(pasta):
            for a in arquivos:
                if not da_adobe and not a.lower().endswith(_EXTENSOES):
                    continue
                caminho = os.path.join(raiz, a)
                try:
                    for nomes, asc, linha in _faces_do_arquivo(caminho):
                        ps = nomes.get(6)
                        if not ps:
                            continue
                        idx.setdefault(ps.lower(), {
                            "familia": nomes.get(16) or nomes.get(1) or ps,
                            "face": nomes.get(17) or nomes.get(2) or "Regular",
                            "ascendente": asc, "linha": linha, "adobe": da_adobe,
                            "arquivo": caminho})
                except (OSError, struct.error, ValueError):
                    continue          # arquivo de fonte ilegível: as outras seguem
    _INDICE = idx
    return idx


#: Sufixos que o nome PostScript acrescenta à família (Adobe/Monotype).
_SUFIXOS_PS = re.compile(r"(MT|PS|Std|Pro)$")


def traduzir(postscript: str) -> dict:
    """`{familia, face, ascendente, instalada}` do nome PostScript. Fora do índice, a dedução
    pelo nome (`Familia-Face`, sem os sufixos `MT`/`PS`) e a ascendente típica (0,9)."""
    if not postscript:
        return {"familia": "Open Sans", "face": "", "ascendente": 1.069, "linha": 1.362,
                "adobe": False, "instalada": False}
    achada = indice().get(postscript.lower())
    if achada:
        return {**achada, "instalada": True}
    familia, _, face = postscript.partition("-")
    familia = _SUFIXOS_PS.sub("", familia) or familia
    # "HelveticaNeue" → "Helvetica Neue": as minúsculas seguidas de maiúscula separam palavras.
    familia = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", familia)
    face = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", _SUFIXOS_PS.sub("", face)) or "Regular"
    return {"familia": familia, "face": face, "ascendente": 0.9, "linha": 1.2, "adobe": False,
            "instalada": False}
