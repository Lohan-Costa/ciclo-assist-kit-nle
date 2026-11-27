"""O conferidor de EDL (`motor/edl/conferir.py`): com SÓ a EDL e os arquivos, cada evento leva ao certo?

Rodar:

    .venv/bin/python tests/test_edl_conferir.py

## Por que este teste existe

"EDLs exportadas para a equipe de som chegam erradas e ninguém sabe dizer exatamente" (autor, 2026-11-25). A rodada
EDL PARA O SOM no MC 25.12 Mac (plano `docs/plano/2026-11-25-edl-para-o-som.md`) mediu três jeitos de a lista sair
bem formada e levar ao lugar errado, que é o que este conferidor tem de pegar:

- o canal do ARQUIVO não está na EDL: A1/A2 tocando os canais 3/5 de um WAV de 6 saem `A`/`A2` (S10);
- o mesmo sound roll em dois takes dá o MESMO reel — só o TC desempata (S11, e todo som com tape);
- o List Tool LEMBRA as trilhas marcadas da sequência anterior: carregada depois de uma de 2 trilhas, a de 6 sai só com
  A1/A2, calada (S6/S7 "TRILHAS HERDADAS").

A parte escrita aqui roda sempre; as EDLs reais ficam em `04 SINTETICOS/EDL SOM MC` (sem a pasta, pula e diz).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "tests")]

from edl.conferir import ALERTA, CERTO, ERRADO, conferir, placar  # noqa: E402
from edl.leitura import ler  # noqa: E402
from casos import raiz_das_amostras  # noqa: E402

PASTA = Path(raiz_das_amostras()) / "04 SINTETICOS" / "EDL SOM MC"

FONTES = {"CAM": {"arquivo": "A001C003_MOV-PRORES.mov", "tape": None, "tc": "14:00:00:00"},
          "12/1": {"arquivo": "26Y11M25_T001_WAV-BWF.wav", "tape": "26Y11M25", "tc": "13:59:58:00"},
          "12/2": {"arquivo": "26Y11M25_T002_WAV-BWF.wav", "tape": "26Y11M25", "tc": "14:59:59:00"}}


def _trilha(fonte, src_in, src_out, canal=None):
    return {"fonte": fonte, "src_in": src_in, "src_out": src_out, "canal_do_arquivo": canal,
            "microfone": {3: "BOOM"}.get(canal)}


CASO = {"sequencia": "T", "eventos": [{"rec_in": "01:00:00:00", "trilhas": {
    "V1": _trilha("CAM", "14:00:04:00", "14:00:06:00"),
    "A1": _trilha("12/1", "14:00:04:00", "14:00:06:00", 1),
    "A2": _trilha("12/1", "14:00:04:00", "14:00:06:00", 3),
    "A3": _trilha("12/1", "14:00:04:00", "14:00:06:00", 3)}}]}

EDL = ("TITLE:   T \r\nFCM: NON-DROP FRAME\r\n"
       "001  A001C003 V     C        14:00:04:00 14:00:06:00 01:00:00:00 01:00:02:00 \r\n"
       "002  26Y11M25 A     C        14:00:04:00 14:00:06:00 01:00:00:00 01:00:02:00 \r\n"
       "003  26Y11M25 A2    C        14:00:04:00 14:00:06:00 01:00:00:00 01:00:02:00 \r\n")


def main() -> int:
    falhas, n = [], 0

    def ok(rotulo, obtido, esperado):
        nonlocal n
        n += 1
        if obtido != esperado:
            falhas.append(f"{rotulo}: {obtido!r} ≠ {esperado!r}")
        print(f"{'ok ' if obtido == esperado else 'XX '} {rotulo}")

    v = {x.trilha: x for x in conferir(ler(EDL), CASO, FONTES)}
    ok("V1: o reel de 8 leva à câmera e o TC bate", v["V1"].veredito, CERTO)
    ok("A1: o sound roll serve a dois takes — alerta", v["A1"].veredito, ALERTA)
    ok("A2: canal 3 do arquivo numa trilha A2 — errado calado", v["A2"].veredito, ERRADO)
    ok("A3: a trilha não está na lista — errado calado", (v["A3"].veredito, v["A3"].motivo),
       (ERRADO, "a trilha não está na EDL"))
    torto = EDL.replace("002  26Y11M25 A     C        14:00:04:00 14:00:06:00",
                        "002  26Y11M25 A     C        14:00:04:01 14:00:06:01")
    a1 = [x for x in conferir(ler(torto), CASO, FONTES) if x.trilha == "A1"][0]
    ok("A1 um quadro fora — errado calado", (a1.veredito, a1.motivo), (ERRADO, "o TC de origem não é o da fonte"))

    if PASTA.is_dir():
        casos, fontes = {}, None
        for pj in sorted(PASTA.glob("plano*.json")):      # plano, plano v02, plano_s8 v02, plano so audio
            plano = json.loads(pj.read_text(encoding="utf-8"))
            fontes = plano["fontes"]
            casos.update({c["sequencia"]: c for c in plano["casos"]})
        esperado = {  # (certo, alerta, errado calado) — o MC 25.12 Mac, 2026-11-25; CMX_3600 e File_129 iguais
            "S1": (6, 0, 0), "S6": (2, 12, 0), "S7": (1, 6, 0), "S10": (2, 0, 4), "S11": (2, 4, 0),
            "S6 TRILHAS HERDADAS": (2, 4, 8), "S7 TRILHAS HERDADAS": (1, 2, 4),
            # o group na forma do MC (cópia do Selector) e a troca de ângulo pelo gesto do editor
            "S7 v02": (1, 6, 0), "S8": (3, 18, 0),
            # a MESMA montagem sem vídeo nenhum (autor: o AAF do Premiere com merged só sai certo assim) — no MC, igual
            "S1 SO AUDIO": (4, 0, 0), "S6 SO AUDIO": (0, 12, 0), "S7 SO AUDIO": (0, 6, 0), "S10 SO AUDIO": (0, 0, 4),
            "S11 SO AUDIO": (0, 4, 0)}
        for formato in ("CMX3600", "FILE129"):
            for chave, conta in esperado.items():
                caso, _, resto = chave.partition(" ")
                if resto.startswith("TRILHAS"):
                    nome = f"MC {caso} {formato} {resto}.edl"
                else:
                    nome = f"MC {chave} {formato}.edl"
                if not (PASTA / nome).exists():
                    continue
                edl = ler((PASTA / nome).read_bytes())
                p = placar(conferir(edl, casos[edl.titulo.strip()], fontes))
                ok(f"{nome}: {conta}", (p[CERTO], p[ALERTA], p[ERRADO]), conta)
    else:
        print(f"-- pulou as EDLs reais: {PASTA} não existe nesta máquina")

    # o PREMIERE 26.0.2 Mac (mesma B31; merged, multicâmera "Todas as câmeras" e nest pelo menu; o diálogo no padrão)
    pp = PASTA.parent / "EDL SOM PREMIERE"
    if pp.is_dir():
        plano = json.loads((pp / "plano_premiere.json").read_text(encoding="utf-8"))
        casos = {c["sequencia"]: c for c in plano["casos"]}
        esperado = {  # (certo, alerta, errado calado) — o vídeo junto ou não, o SOM sai igual
            "PR S1 PADRAO": (0, 6, 0), "PR S1 SO AUDIO PADRAO": (0, 4, 0),        # reel AX: só o nome do clipe
            "PR S2 PADRAO": (0, 10, 4), "PR S2 SO AUDIO PADRAO": (0, 8, 4),        # 4 canais: A5/A6 somem
            "PR S3B PADRAO": (0, 1, 6), "PR S3B SO AUDIO PADRAO": (0, 0, 6),      # merged por In: som 1 quadro antes
            # sem "Usar timecode de áudio do clipe" (o jeito do autor): a MESMA EDL — a opção só muda o TC do merged
            "PR S2C PADRAO": (0, 10, 4), "PR S2C SO AUDIO PADRAO": (0, 8, 4),
            "PR S3C PADRAO": (0, 1, 6), "PR S3C SO AUDIO PADRAO": (0, 0, 6),
            "PR S4 PADRAO": (0, 0, 4), "PR S4 SO AUDIO PADRAO": (0, 0, 2),        # multicâmera: TC dela, sem fonte
            "PR S5 PADRAO": (0, 0, 4), "PR S5 SO AUDIO PADRAO": (0, 0, 2)}        # nest: TC dele, sem fonte
        for nome, conta in esperado.items():
            edl = ler((pp / f"{nome}.edl").read_bytes())
            p = placar(conferir(edl, casos[edl.titulo.strip()], plano["fontes"]))
            ok(f"{nome}: {conta}", (p[CERTO], p[ALERTA], p[ERRADO]), conta)
    else:
        print(f"-- pulou as EDLs do Premiere: {pp} não existe nesta máquina")

    print(f"\n{n - len(falhas)}/{n}")
    for f in falhas:
        print("FALHA", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
