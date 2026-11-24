"""O relink Avid → Avid confere o TC do master (B110 no MC, autor 2026-10-31: "pode consertar o relink Avid → Avid").

Rodar:

    .venv-win/Scripts/python tests/test_relink_tc_zerado.py        (Mac: .venv/bin/python)

Medido no lab B110 (MC 25.6): o `media/matcher_masters` casava por nome + duração e o `Master` não tinha TC — o FIT
(TC 00:00:00:00) e o ALEXA (sem TC) eram religados aos .mp4 com confiança 1,0, calados. Agora o master traz o TC de
origem (bin: `segmentos.identidade_na_bin`; AAF: `_tc_do_master`) e o `_portao_tc` aplica a regra do `.prproj`
("depende do disco"): o arquivo do master não está no disco (senão o 1º estágio casaria), então o zerado ENTRA, no
topo da revisão, com o motivo; TCs reais diferentes (> 1 s) = outro arquivo; o que confere vence; o master sem TC
(o fluxo do proxy) e o SOM não mudam.

Os candidatos são entradas do índice com `tc_start` (o caminho não existe: a sondagem de reserva não roda). A parte
real (a bin do lab e o AAF do PRODUCAO-A) PULA sem os arquivos no disco.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor")]

from aaf.masters import Master  # noqa: E402
from media.matcher_masters import casar_masters  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


DEZ = 10 * 3600 * 24          # 10:00:00:00 a 24


def master(nome="B11_FIT_MOV-PRORES", tc=DEZ, audio=False):
    m = Master(nome=nome, mob_id="", mob_id_urn="", e_audio=audio, duracao_frames=96, edit_rate=24.0)
    m.tc_quadros, m.tc_fps = (tc, 24) if tc is not None else (None, None)
    m.caminho_conhecido = None
    return m


def arq(pasta, nome, tc, ext=".mp4"):
    f = nome + ext
    return {"path": os.path.join("X:\\nao_existe", pasta, f), "filename": f, "extension": ext,
            "duration_ms": 4000.0, "frame_rate": 24.0, "tc_start": tc}


def um(m, *arquivos):
    return casar_masters([m], {"files": list(arquivos)})[0]


def main() -> int:
    print("── o master tem TC real (10:00:00:00) e o seu arquivo não está no disco ──")
    r = um(master(), arq("B", "B11_FIT_MOV-PRORES", "00:00:00:00"))
    ok("⭐ candidato com TC 00:00:00:00: entra (a única mídia)…", bool(r.arquivo), True)
    ok("…no topo da revisão (confiança < 0,9)", (r.precisa_de_revisao, r.confianca), (True, 0.85))
    ok("…com o motivo e o TC do master", "TC a conferir" in r.motivo and "10:00:00:00" in r.motivo, True)
    r = um(master(), arq("B", "B11_FIT_MOV-PRORES", None))
    ok("⭐ candidato sem TC: idem", (bool(r.arquivo), r.precisa_de_revisao), (True, True))
    r = um(master(), arq("B", "B11_FIT_MOV-PRORES", "10:00:00:00"))
    ok("candidato com o MESMO TC: limpo", (bool(r.arquivo), r.confianca, r.precisa_de_revisao), (True, 1.0, False))
    r = um(master(), arq("B", "B11_FIT_MOV-PRORES", "10:00:00:02"))
    ok("2 quadros de diferença (o desconto do MC no H.264): limpo", (bool(r.arquivo), r.confianca), (True, 1.0))
    r = um(master(), arq("B", "B11_FIT_MOV-PRORES", "11:00:00:00"))
    ok("⭐ TC real DIFERENTE: recusado (outro arquivo de mesmo nome)", r.arquivo, None)
    ok("…e o motivo diz o timecode", "timecode diferente" in r.motivo, True)
    r = um(master(), arq("A", "B11_FIT_MOV-PRORES", "10:00:00:00", ".mov"), arq("B", "B11_FIT_MOV-PRORES", "00:00:00:00"))
    ok("⭐ um confere e o outro é zerado: o que confere vence (sem empate)",
       (os.path.basename(r.arquivo or ""), r.ambiguo, r.confianca), ("B11_FIT_MOV-PRORES.mov", False, 1.0))
    r = um(master(), arq("A", "B11_FIT_MOV-PRORES", "00:00:00:00", ".mov"), arq("B", "B11_FIT_MOV-PRORES", None))
    ok("dois zerados/sem TC: empate, do editor", (r.arquivo, r.ambiguo), (None, True))

    print("── o que não muda ──")
    r = um(master(tc=None), arq("O", "B11_FIT_MOV-PRORES", "10:00:00:00", ".mov"))
    ok("master SEM TC (o fluxo do proxy) → original com TC: limpo", (bool(r.arquivo), r.confianca), (True, 1.0))
    r = um(master(tc=0), arq("O", "B11_FIT_MOV-PRORES", None, ".mov"))
    ok("master com TC 00:00:00:00 (o DJI): o zero do lado do projeto não opina", (bool(r.arquivo), r.confianca),
       (True, 1.0))
    r = um(master("SOM_DIRETO_T001", tc=11 * 3600 * 24 + 42 * 60 * 24, audio=True),
           arq("S", "SOM_DIRETO_T001", None, ".wav"))
    ok("SOM com TC real e WAV sem TC lido: limpo (o TC do BWF é o time_reference)", (bool(r.arquivo), r.confianca),
       (True, 1.0))

    print("── o TC lido de verdade (pula sem os arquivos) ──")
    bin_lab = Path(r"%USERPROFILE%\Documents\Avid Projects\DLPC B110 24\B110 COM\B110 COM_SEQ.avb")
    if bin_lab.is_file():
        from avb_bin.masters import masters_de_arquivo
        ms = {m.nome: m for m in masters_de_arquivo(str(bin_lab)) if not m.e_audio}
        ok("bin do lab (MC 25.6): o FIT com o TC do .mov, 10:00:00:00 a 24",
           (ms["B11_FIT_MOV-PRORES"].tc_quadros, ms["B11_FIT_MOV-PRORES"].tc_fps), (DEZ, 24))
        ok("…o TC_ZERADO (cujo .mov tem 11:00:00:00)", ms["B11_TC_ZERADO_MOV-PRORES"].tc_quadros, 11 * 3600 * 24)
    else:
        print("  (pulado: a bin do lab B110 não está nesta máquina)")
    aaf = Path(r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar\03 CASOS\EFEITOS\E03 SEQUENCIA COM EFEITOS"
               r"\AAF COM MP4 LINKADO.aaf")
    if aaf.is_file():
        from aaf.masters import masters_em_uso
        ms = {m.nome: m for m in masters_em_uso(str(aaf))}
        a = ms.get("A001_03170256_C002")
        ok("AAF do PRODUCAO-A: o ARRI A001_03170256_C002 = 02:56:44:17 a 24 (o TC de câmera)",
           (a.tc_quadros, a.tc_fps) if a else None, (((2 * 60 + 56) * 60 + 44) * 24 + 17, 24))
        s = next((m for n, m in ms.items() if n.startswith("PRODUCAO-A - 05-04 C4 P1-T002")), None)
        ok("…e o som direto P1-T002 = 11:42:00:00 (a hora do gravador)", s.tc_quadros if s else None,
           (11 * 60 + 42) * 60 * 24)
    else:
        print("  (pulado: o AAF do PRODUCAO-A não está nesta máquina)")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
