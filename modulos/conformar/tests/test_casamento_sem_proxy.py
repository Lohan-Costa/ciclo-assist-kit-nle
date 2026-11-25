"""Casar proxy → original quando o PROXY não está nesta máquina (2026-10-09).

Rodar:

    .venv/bin/python tests/test_casamento_sem_proxy.py        (Windows: .venv-win/Scripts/python)

O colorista recebe o .prproj e os originais, não os proxies. Até 2026-10-09 as provas do casamento
(`prproj/originais.casar_um`: cópia do proxy, duração, TC) só rodavam se o proxy abrisse; sem ele, o
arquivo de MESMO NOME virava original só pelo nome (no R02, o insert extra e os 2 packs de VFX:
"original" sem o HD dos proxies, "sem original" com ele). Agora a prova vem do PROJETO
(`leitura._midia_no_projeto`: Duration, Start/AlternateStart, FrameRect, CodecType). Regra do banco:
o nome só ORDENA a busca (bugs-do-mundo-real B024, B107); empate é do editor (B088).

Os candidatos são fingidos (`sondar` trocado): o que importa é a decisão, não o ffprobe. A parte do
projeto real (o R02) PULA sem o caso no disco.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "tests")]

from prproj import originais as O  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def casar(proxy, cands: dict, projeto, conteudo=None):
    """`cands` = {caminho: o que o ffprobe diria}. Os arquivos existem de verdade (a impressão das
    cópias lê bytes); `conteudo` = {caminho: bytes}."""
    with tempfile.TemporaryDirectory() as d:
        reais = {}
        for c in cands:
            p = os.path.join(d, c)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write((conteudo or {}).get(c, c.encode() * 1000))
            reais[p] = cands[c]
        indice = {}
        for p in reais:
            indice.setdefault(os.path.splitext(os.path.basename(p))[0].lower(), []).append(p)
        O._SONDA.clear()
        # o MXF fingido não tem o RIP de verdade: a prova de "truncado" é de outro teste
        with mock.patch.object(O, "sondar", lambda c: reais.get(c, {"ok": False})),                 mock.patch.object(O, "mxf_completo", lambda c: True):
            r = O.casar_um(proxy, indice, projeto)
        r["original"] = os.path.relpath(r["original"], d) if r.get("original") else None
        return r


def drone(dur, w=3840, h=2160, codec="hevc", tc=None):
    return {"ok": True, "w": w, "h": h, "codec": codec, "fps": 29.97, "dur_s": dur, "tc": tc}


def main() -> int:
    PROXY = "/Volumes/HD_PROXIES/DRONE/DJI_0001.MOV"          # não existe nesta máquina
    # o que o .prproj sabe do proxy: 10 s, ProRes 1080 — sem TC (o DJI não grava)
    PROJ = {"dur_s": 10.0, "tc_quadros": None, "fps": 29.97, "w": 1920, "h": 1080, "fourcc": "apcn"}

    print("── dois drones, o mesmo nome (DJI_0001), sem o proxy ──")
    r = casar(PROXY, {"drone_B/DJI_0001.MP4": drone(14.0)}, PROJ)
    ok("⭐ um DJI_0001 só, do OUTRO drone (14 s × 10 s do projeto): não vira original",
       (r["estado"], r["conferido_por"]), ("sem_original", "projeto"))
    ok("…e o motivo diz a duração", "duração diferente" in (r["recusados"] or [("", "")])[0][1], True)
    r = casar(PROXY, {"drone_A/DJI_0001.MP4": drone(10.0)}, PROJ)
    ok("o certo (mesma duração do projeto) casa, conferido pelo PROJETO",
       (r["estado"], r["original"], r["conferido_por"]), ("original", os.path.join("drone_A", "DJI_0001.MP4"), "projeto"))
    r = casar(PROXY, {"drone_A/DJI_0001.MP4": drone(10.0), "drone_B/DJI_0001.MP4": drone(14.0)}, PROJ)
    ok("os dois na pasta: a duração separa, fica o certo",
       (r["estado"], r["original"]), ("original", os.path.join("drone_A", "DJI_0001.MP4")))
    r = casar(PROXY, {"drone_A/DJI_0001.MP4": drone(10.0), "drone_B/DJI_0001.MP4": drone(10.0)}, PROJ)
    ok("⭐ os dois com a mesma duração e sem TC: AMBÍGUO, o editor escolhe (nunca o 1º da lista)",
       (r["estado"], r["original"], len(r["candidatos"])), ("ambiguo", None, 2))
    r = casar(PROXY, {"drone_A/DJI_0001.MP4": drone(10.0), "drone_A_copia/DJI_0001.MP4": drone(10.0)}, PROJ,
              conteudo={"drone_A/DJI_0001.MP4": b"x" * 5000, "drone_A_copia/DJI_0001.MP4": b"x" * 5000})
    ok("…mas duas cópias idênticas do mesmo arquivo valem como um original só",
       (r["estado"], len(r["copias"])), ("original", 1))

    print("── o arquivo do projeto DENTRO das pastas indicadas (um fluxo para todo protocolo, 2026-10-19) ──")
    with tempfile.TemporaryDirectory() as d:
        pasta = os.path.join(d, "MIDIA")
        os.makedirs(pasta)
        arq = os.path.join(pasta, "B02_2398_MOV-PRORES.mov")
        open(arq, "wb").write(b"x" * 1000)
        info = {"ok": True, "w": 1920, "h": 1080, "codec": "prores", "fps": 23.976, "dur_s": 10.0, "tc": "01:00:00:00"}
        O._SONDA.clear()
        with mock.patch.object(O, "sondar", lambda c: info if c == arq else {"ok": False}):
            dentro = O.casar_um(arq, {"b02_2398_mov-prores": [arq]}, None, [pasta])
            fora = O.casar_um(arq, {"b02_2398_mov-prores": [arq]}, None, [os.path.join(d, "OUTRA")])
    ok("⭐ o próprio arquivo, na pasta indicada: encontrado (como o master pelo AAF)",
       (dentro["estado"], dentro["original"]), ("proprio", arq))
    ok("…fora das pastas indicadas continua sem original", fora["estado"], "sem_original")

    print("── TC e cópia do proxy, pelo projeto ──")
    ARRI = "/Volumes/PRODUCAO_B/BRUTO/A044C013_240725_R1X0.mov"
    PA = {"dur_s": 39.958333, "tc_quadros": 1345158, "fps": 24.0, "w": 2880, "h": 1620, "fourcc": "apco"}
    arri = {"ok": True, "w": 0, "h": 0, "codec": None, "fps": 24.0, "dur_s": 39.958333}
    r = casar(ARRI, {"PROJ-X/A044C013_240725_R1X0.mxf": {**arri, "tc": "15:34:08:06"}}, PA)
    ok("ARRIRAW com o TC do projeto (Start 56048,25 s × 24 = 15:34:08:06): original",
       (r["estado"], r["conferido_por"]), ("original", "projeto"))
    r = casar(ARRI, {"PROJ-X/A044C013_240725_R1X0.mxf": {**arri, "tc": "15:34:09:06"}}, PA)
    ok("mesmo nome e duração, TC 1 s adiante: recusado pelo timecode",
       (r["estado"], "timecode diferente" in (r["recusados"] or [("", "")])[0][1]), ("sem_original", True))
    r = casar(ARRI, {"PROJ-X/A044C013_240725_R1X0.mov": {"ok": True, "w": 2880, "h": 1620, "codec": "prores",
                                                         "fps": 24.0, "dur_s": 39.958333, "tc": "15:34:08:06"}}, PA)
    ok("outra cópia do PROXY (mesmo raster e codec que o projeto declara): não é o original",
       (r["estado"], "cópia do proxy" in (r["recusados"] or [("", "")])[0][1]), ("sem_original", True))

    print("── sem proxy e sem o que o projeto diria ──")
    r = casar(PROXY, {"drone_B/DJI_0001.MP4": drone(14.0)}, None)
    ok("só o nome: o resultado diz que foi SÓ pelo nome (conferido_por)", r["conferido_por"], "nome")

    print("── o projeto real (R02) ──")
    from casos import CANDIDATAS_AMOSTRAS
    caso = next((Path(x) / "03 CASOS" / "REAL" / "R02 PRODUCAO_B EXEMPLOS" / "premiere" / "DU exemplos especificos.prproj"
                 for x in CANDIDATAS_AMOSTRAS if x and (Path(x) / "03 CASOS" / "REAL" / "R02 PRODUCAO_B EXEMPLOS").is_dir()), None)
    if caso is None or not caso.is_file():
        print("  PULADO — o caso R02 não está nesta máquina")
    else:
        from prproj.leitura import Leitor
        from prproj.projeto import Projeto
        lt = Leitor(Projeto(str(caso)))
        segs = lt.ler("DU exemplos especificos")["segmentos"]
        midia = {os.path.basename(s["media_ref"]["local_path"]): s["prproj"]["midia"]
                 for s in segs if s.get("prproj") and s["prproj"].get("midia")}
        a = midia.get("A044C013_240725_R1X0.mov") or {}
        ok("A044C013: o projeto dá o TC da fonte (1.345.158 = 15:34:08:06) e o codec do proxy (apco, ProRes Proxy)",
           (a.get("tc_quadros"), a.get("fourcc"), round(a.get("dur_s") or 0, 3)), (1345158, "apco", 39.958))
        i = midia.get("87-INSERT-EXTRA-1.MOV") or {}
        ok("o MOV do celular: sem TC no projeto, codec HEVC", (i.get("tc_quadros"), i.get("fourcc")), (None, "HEVC"))
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
