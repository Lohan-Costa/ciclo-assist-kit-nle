"""O leitor de EDL (`motor/edl/leitura.py`) com o que o Premiere 26.0.2 e o MC 25.12 escrevem.

Rodar:

    .venv/bin/python tests/test_edl_leitura.py

## Por que este teste existe

A EDL é a lista que vai para a equipe de som, e nenhum app nosso a lia. A rodada 1 (2026-11-25, banco
`protocolos/edl/README.md`) mostrou que os dois NLEs escrevem a MESMA sequência de jeitos que quebram um leitor
ingênuo: MacRoman × UTF-8, reel de 8 a 129 colunas, número de 3 ou 6 dígitos, `AA/V`, o par de linhas da transição
(`W000` no Premiere, `D` no MC), o `M2` antes ou depois dos comentários, `* FROM` × `*FROM`.

A parte escrita aqui roda sempre; as cinco EDLs reais ficam em `04 SINTETICOS/EDL RODADA 1` (sem a pasta, pula e diz).
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "tests")]

from edl.leitura import ler, quadros  # noqa: E402
from casos import raiz_das_amostras  # noqa: E402

PASTA = Path(raiz_das_amostras()) / "04 SINTETICOS" / "EDL RODADA 1"

# o Premiere no Mac: MacRoman (Ç = 0x82, Ã = 0xCC), CRLF, o dissolve novo como W000
PREMIERE = (b"TITLE: B30 EDL LAB\r\nFCM: NON-DROP FRAME\r\n\r\n"
            b"002  AX       V     C        01:00:04:12 01:00:04:12 01:00:02:12 01:00:02:12 \r\n"
            b"FCM: NON-DROP FRAME\r\n"
            b"002  AX       V     W000 024 02:00:01:12 02:00:05:00 01:00:02:12 01:00:06:00 \r\n"
            b"EFFECTS NAME IS W000\r\n* FROM CLIP NAME: B30_A_MOV-PRORES.mov\r\n* TO CLIP NAME: B30_B_MOV-PRORES.mov\r\n\r\n"
            b"005  AX       AA/V  C        04:00:02:00 04:00:05:00 01:00:06:00 01:00:09:00 \r\n"
            b"* FROM CLIP NAME: B30_CENA_A\x82\xccO_MOV-PRORES.mov\r\n"
            b"* AUDIO LEVEL AT 04:00:00:00 IS -0.00 DB  (REEL AX A1)\r\n\r\n"
            b"010  AX       V     C        03:00:02:00 03:00:03:12 01:00:16:00 01:00:19:00 \r\n"
            b"* FROM CLIP NAME: B30_LONGO.mov\r\nM2   AX       012.0                      03:00:02:00 \r\n")

# o MC em File_129: UTF-8, reel largo, 6 dígitos, *FROM sem espaço, M2 antes do comentário, A7
MC = ("TITLE:   B30 EDL LAB \r\nFCM: NON-DROP FRAME\r\n"
      "000004  B30_SOM_WAV-BWF.WAV" + " " * 100 + "A7    C        06:00:00:22 06:00:06:22 01:00:00:00 01:00:06:00 \r\n"
      "*FROM CLIP NAME:  B30_SOM_WAV-BWF.WAV\r\n"
      "000008  B30_A_MOV-PRORES" + " " * 100 + "V     C        01:00:04:12 01:00:04:12 01:00:02:12 01:00:02:12 \r\n"
      "000008  B30_B_MOV-PRORES" + " " * 100 + "V     D    024 02:00:01:12 02:00:02:12 01:00:02:12 01:00:03:12 \r\n"
      "*BLEND, DISSOLVE \r\n*FROM CLIP NAME:  B30_A_MOV-PRORES \r\n*TO CLIP NAME:  B30_B_MOV-PRORES\r\n"
      "000019  B30_T25_MOV-PRORES" + " " * 100 + "V     C        05:00:01:24 05:00:05:00 01:00:09:00 01:00:12:00 \r\n"
      "M2      B30_T25_MOV-PRORES" + " " * 100 + "025.0 05:00:01:24 \r\n"
      "*FROM CLIP NAME:  B30_CENA_AÇÃO_MOV-PRORES\r\n").encode("utf-8")


def main() -> int:
    falhas: list[str] = []
    n = 0

    def ok(rotulo, obtido, esperado):
        nonlocal n
        n += 1
        if obtido != esperado:
            falhas.append(f"{rotulo}: {obtido!r} (esperado {esperado!r})")
        print(f"{'ok ' if obtido == esperado else 'XX '} {rotulo}")

    p = ler(PREMIERE)
    ok("premiere: MacRoman", p.codificacao, "mac_roman")
    ok("premiere: 3 eventos (o par da transição vira um)", [e.num for e in p.eventos], [2, 5, 10])
    t = p.eventos[0]
    ok("premiere: W000 de 24 com a fonte que sai", (t.transicao, t.duracao, t.de["src_in"]), ("W000", 24, "01:00:04:12"))
    ok("premiere: FROM/TO da transição", (t.clip_de, t.clip), ("B30_A_MOV-PRORES.mov", "B30_B_MOV-PRORES.mov"))
    ok("premiere: AA/V = A, A2, V", p.eventos[1].canais, ["A", "A2", "V"])
    ok("premiere: acento do MacRoman", p.eventos[1].clip, "B30_CENA_AÇÃO_MOV-PRORES.mov")
    ok("premiere: M2 depois do comentário", p.eventos[2].velocidade, 12.0)

    m = ler(MC)
    ok("mc: UTF-8", m.codificacao, "utf-8")
    ok("mc: título sem os espaços", m.titulo, "B30 EDL LAB")
    ok("mc: reel largo de WAV, canal A7", (m.eventos[0].reel, m.eventos[0].canal), ("B30_SOM_WAV-BWF.WAV", "A7"))
    ok("mc: *FROM sem espaço", m.eventos[0].clip, "B30_SOM_WAV-BWF.WAV")
    d = m.eventos[1]
    ok("mc: D 024, reel que entra e o que sai", (d.transicao, d.duracao, d.reel, d.de["reel"]),
       ("D", 24, "B30_B_MOV-PRORES", "B30_A_MOV-PRORES"))
    ok("mc: M2 antes do comentário", (m.eventos[2].velocidade, m.eventos[2].clip), (25.0, "B30_CENA_AÇÃO_MOV-PRORES"))
    ok("mc: nada sem ler", m.nao_lidas, [])

    ok("TC → quadros (24)", quadros("01:00:02:12", 24), 86460)
    ok("TC → quadros DF (29,97, 00:10:00;00)", quadros("00:10:00;00", 30, True), 17982)
    ok("TC → quadros DF (00:01:00;02)", quadros("00:01:00;02", 30, True), 1800)

    aud = ler("TITLE: X\r\nFCM: NON-DROP FRAME\r\n001  26Y11M25 NONE  C        14:00:03:00 14:00:08:00 01:00:00:00 "
              "01:00:05:00 \r\n* FROM CLIP NAME: S.wav\r\nAUD  3    4\r\n")
    ok("AUD 3 4 (Premiere, 6 canais): o evento NONE leva A3 e A4", (aud.eventos[0].canais, aud.nao_lidas),
       (["A3", "A4"], []))

    if PASTA.is_dir():
        esperado = {"PR01 PADRAO.edl": (11, "mac_roman"), "PR02 NOMES.edl": (11, "mac_roman"),
                    "PR03 NOMES SEM 32.edl": (11, "mac_roman"), "MC01 FILE129 PADRAO.edl": (27, "utf-8"),
                    "MC02 CMX3600 PADRAO.edl": (27, "utf-8")}
        for nome, (eventos, cod) in esperado.items():
            e = ler((PASTA / nome).read_bytes())
            ok(f"{nome}: {eventos} eventos, {cod}, tudo lido",
               (len({x.num for x in e.eventos}), e.codificacao, e.nao_lidas), (eventos, cod, []))
        mc = ler((PASTA / "MC01 FILE129 PADRAO.edl").read_bytes())
        ok("MC01: reel do acento perdeu as letras (U+FFFD)", "�" in mc.eventos[15].reel, True)
        ok("MC01: o som em A7–A10", sorted({x.canal for x in mc.eventos if x.reel.startswith("B30_SOM")}),
           ["A10", "A7", "A8", "A9"])
    else:
        print(f"-- pulou as EDLs reais: {PASTA} não existe nesta máquina")

    print(f"\n{n - len(falhas)}/{n}")
    for f in falhas:
        print("FALHA", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
