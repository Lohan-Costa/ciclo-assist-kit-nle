"""O .prproj de 2023 do R04 PRODUCAO-C no Resolve: o tempo, o encaixe e a escala sobre o ARQUIVO apontado (2026-10-18).

Rodar:

    .venv/bin/python tests/test_relink_r04_premiere.py        (Windows: .venv-win/Scripts/python)

As regras que vieram do caso (banco `prproj/relink-e-geometria.md` §6.3–6.4; bugs-do-mundo-real B024, B074):
- TC acima de 30 qps: o campo de quadros pode estar na base cheia ou na metade; entre taxas diferentes, o proxy
  arredonda o início para a grade dele (`originais._tc_confere`);
- a mídia achada fora do lugar pelo NOME só vale com prova (a duração do som, o raster da imagem);
- a escala digitada para outra mídia é OFERTA: suspeito = arquivo com plano menor que o encaixe, fator = 1 ÷ o menor
  zoom entre os suspeitos da mesma câmera e do mesmo raster (`escalas_de_outra_midia`);
- o principal "religado" só conta quando o ARQUIVO mudou (pasta de cima ou nome), não o disco.

As decisões são testadas com dados fingidos; a parte com o caso real PULA sem o disco.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "tests")]

from prproj import originais as O  # noqa: E402
from prproj.leitura import _religado  # noqa: E402
from tools import prproj_para_drt as P  # noqa: E402
import casos as C  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: veio {obtido!r}, esperava {esperado!r}")


def tc(h, m, s, f, base):
    return ((h * 60 + m) * 60 + s) * base + f


def plano(caminho, zoom, raster=(1920, 1080)):
    return {"track": 1, "media_ref": {"local_path": caminho}, "prproj": {"proxy_px": list(raster)},
            "effects": [{"name": "Motion", "params": {"scale_x": zoom, "scale_y": zoom}}]}


def main() -> int:
    print("── TC acima de 30 qps ──")
    ok("C0296: 100p do projeto em base 50 (…:22) × a conversão do Resolve (…:44): o mesmo instante",
       O._tc_confere(tc(21, 1, 3, 22, 100), 100, tc(21, 1, 3, 44, 100), 100), True)
    ok("JUL_7672: proxy 60p (base 30, …:12) × original 100p (…:42): 0,40 × 0,42 s, um quadro da base grossa",
       O._tc_confere(tc(19, 31, 58, 12, 60), 60, tc(19, 31, 58, 42, 100), 100), True)
    ok("mesma taxa de 25: um quadro de diferença continua recusado",
       O._tc_confere(tc(10, 0, 0, 5, 25), 25, tc(10, 0, 0, 6, 25), 25), False)
    ok("taxas diferentes, meio segundo de diferença: recusado",
       O._tc_confere(tc(19, 31, 58, 0, 60), 60, tc(19, 31, 58, 50, 100), 100), False)

    print("── o nome só ordena: a prova do som e da imagem ──")
    indice = {O._CHAVE_NOME + "local-3-005.wav": ["/B/LOCAL-3-005.WAV"]}
    ok("o som de mesmo nome e mesma duração é achado",
       O.pelo_nome("Y:/x/LOCAL-3-005.WAV", indice, lambda c: True)[0], ["/B/LOCAL-3-005.WAV"])
    ok("⭐ o homônimo de outra duração NÃO é achado",
       O.pelo_nome("Y:/x/LOCAL-3-005.WAV", indice, lambda c: False)[0], [])
    with mock.patch.object(O.sonda, "ler", return_value={"format": {"duration": "68.499542"}}):
        ok("duração do arquivo × a do projeto (±0,1 s)", (O._mesma_duracao("x", 68.4995), O._mesma_duracao("x", 70.0)),
           (True, False))

    print("── escala de outra mídia (oferta) ──")
    segs = [plano("PRJ-0006-156.mov", 0.5), plano("PRJ-0006-156.mov", 0.5), plano("PRJ-0006-195.mov", 0.76),
            plano("PRJ-0006-271.mov", 1.0),
            plano("JUL_7671.mp4", 0.2667, (1024, 540)), plano("JUL_7680.mp4", 0.3467, (1024, 540)),
            plano("JUL_7503.MP4", 1.0, (3840, 2160))]
    e = P.escalas_de_outra_midia(segs)
    ok("suspeitos: só os arquivos com plano menor que o encaixe", sorted(e),
       ["JUL_7671.mp4", "JUL_7680.mp4", "PRJ-0006-156.mov", "PRJ-0006-195.mov"])
    ok("⭐ o arquivo de um plano só herda o fator da câmera (PRJ-195 × 2, não × 1,316)", e["PRJ-0006-195.mov"]["fator"], 2.0)
    ok("JUL de 1024: × 3,75 (o 4K da Sony ÷ 1024)", round(e["JUL_7680.mp4"]["fator"], 2), 3.75)
    ok("o projeto certo (tudo a 100 %) não recebe oferta", P.escalas_de_outra_midia([plano("a.mov", 1.0)]), {})
    s = plano("x.mov", 0.5)
    s["effects"][0]["params"]["kf"] = {"zoom": [(0, 0.5), (10, 0.25)]}
    P._reescalar(s, 2.0)
    ok("aceito: a escala e os keyframes de zoom × fator",
       (s["effects"][0]["params"]["scale_x"], s["effects"][0]["params"]["kf"]["zoom"]), (1.0, [(0, 1.0), (10, 0.5)]))

    print("── principal religado ──")
    ok("o MP4 da câmera virou um Proxies\\…mp4: religado",
       _religado(r"\\h\old\Proxies\JUL_7672.mp4", [r"I:\RUSHS\M4ROOT\CLIP\JUL_7672.MP4"]), True)
    ok("⭐ só o disco mudou (J: → I:): NÃO é religado",
       _religado(r"J:\RUSHS\CLIP\JUL_7503.MP4", [r"I:\OUTRO\CLIP\JUL_7503.MP4"]), False)
    ok("sem histórico: não é religado", _religado(r"J:\a\b.mov", []), False)

    print("── o caso real (R04) ──")
    raiz = C.amostras()                      # subindo de pasta até a MIDIAS DE TESTES (era D:\ fixo: pulava no Mac)
    r04 = raiz / "03 CASOS" / "REAL" / "R04 PRODUCAO-C" if raiz else None
    if not r04 or not (r04 / "ISOLADO" / "MIDIA").is_dir():
        print("  (pulado: o caso R04 não está neste disco)")
    else:
        a = P.analisar(str(r04 / "premiere" / "PRODUCAO_C_Trailer (2023, original intocado).prproj"),
                       "PRODUCAO_C_Trailer_Corte_v02", [str(r04 / "ISOLADO" / "MIDIA")])
        b = P.analisar(str(r04 / "ISOLADO" / "PROJETO" / "PRODC_FINAL_isolado.prproj"), "PRODC_Trailer_v02_RESGATE",
                       [str(r04 / "ISOLADO" / "MIDIA")])

        def entradas(an):
            return {(s["track"], s["timeline_tc_in"]): (s.get("source_fps"), s.get("source_start_frames"))
                    for s in an["leitura"]["segmentos"]
                    if not (s.get("is_audio") or s.get("is_gap") or s.get("is_transition") or s.get("is_effect")
                            or s.get("referencia"))}
        ea, eb = entradas(a), entradas(b)
        ok("⭐ as 80 entradas do 2023 = as do resgatado (taxa do arquivo apontado)",
           sum(1 for k in ea if ea[k] == eb.get(k)), 80)
        ok("todos os 48 arquivos com lugar, 0 sem", sum(1 for c in a["casamento"].values()
                                                      if c["estado"] in ("original", "proprio") or c.get("realocado")), 48)
        ok("os 21 sons achados (e provados pela duração)", a["resumo"]["sons_fora_do_lugar"]["achados"], 21)
        ok("ofertas: 16 de escala e 3 de proporção; o resgatado, nenhuma",
           (len(a["escalas"]), len(a["proporcoes"]), len(b["escalas"]), len(b["proporcoes"])), (16, 3, 0, 0))
        from avb_bin.segmentos import caminho_confiavel
        m = P.analisar(str(r04 / "premiere" / "PRODUCAO_C_Trailer (2023, original intocado).prproj"),
                       "PRODUCAO_C_Trailer_Corte_v02", [str(r04 / "ISOLADO" / "MIDIA")],
                       confiavel=caminho_confiavel)["resumo"]["midias"]
        ok("lista (a tabela do MC): o recusado mostra o TEXTO declarado; nenhuma linha sem origem nem arquivo",
           (sum(x["recusado"] for x in m), all(x["origem"].startswith("\\\\") for x in m if x["recusado"]),
            sum(1 for x in m if not x["origem"] or not x["arquivo"])), (16, True, 0))
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
