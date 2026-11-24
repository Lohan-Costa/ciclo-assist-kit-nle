"""Premiere → Premiere (organograma aprovado pelo autor em 2026-10-22).

Rodar:

    .venv/bin/python tests/test_premiere_para_premiere.py        (Windows: .venv-win/Scripts/python)

O que se testa:
- MUDOU DE LUGAR (decisão do autor: "provar e aceitar"): o arquivo do projeto achado noutra pasta com a prova completa
  do que o projeto registra (raster, codec, duração) vale como o próprio ("encontrado"); sem a prova, segue "sem
  original"; o original de câmera continua vencendo;
- os SONS na lista de mídias;
- a CÓPIA relinkada (`prproj/copia.py`): os três caminhos, o Title, o OfflineReason, o FrameRect, vários Media do
  mesmo arquivo, a caixa do caminho; nunca por cima do projeto do editor;
- a conferência dos CAMINHOS depois do `importSequences` (`premiere_copia.executar`, a ponte fingida): o que o Premiere
  religou por conta própria vira marcador.
A parte com o caso real (R04, `WSP-DLPC_2.prproj` no Desktop) PULA sem o arquivo.
"""

from __future__ import annotations

import gzip
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "tests")]

from prproj import copia as C  # noqa: E402
from prproj import originais as O  # noqa: E402
from tools import prproj_para_drt as P  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def casar(proxy, cands: dict, projeto, dentro=True):
    """`cands` = {caminho relativo: o que o ffprobe diria}; `dentro` = os candidatos estão nas pastas indicadas."""
    with tempfile.TemporaryDirectory() as d:
        reais = {}
        for c in cands:
            p = os.path.join(d, c)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            with open(p, "wb") as f:
                f.write(c.encode() * 1000)
            reais[p] = cands[c]
        indice = {}
        for p in reais:
            indice.setdefault(os.path.splitext(os.path.basename(p))[0].lower(), []).append(p)
        O._SONDA.clear()
        with mock.patch.object(O, "sondar", lambda c: reais.get(c, {"ok": False})), \
                mock.patch.object(O, "mxf_completo", lambda c: True):
            r = O.casar_um(proxy, indice, projeto, [d] if dentro else [os.path.join(d, "outra")])
        r["original"] = os.path.relpath(r["original"], d) if r.get("original") else None
        return r


def camera(dur, w=1920, h=1080, codec="h264", fps=25.0):
    return {"ok": True, "w": w, "h": h, "codec": codec, "fps": fps, "dur_s": dur, "tc": None}


def main() -> int:
    DECL = "Z:/EDICAO/MIDIA/JUL_7503.mp4"                # o caminho do projeto: o disco não existe aqui
    PROJ = {"dur_s": 12.0, "tc_quadros": None, "fps": 25.0, "w": 1920, "h": 1080, "fourcc": "avc1"}

    print("── mudou de lugar: provar e aceitar ──")
    r = casar(DECL, {"MIDIA/JUL_7503.mp4": camera(12.0)}, PROJ)
    ok("⭐ mesmo raster, codec e duração do projeto, dentro das pastas: o próprio (encontrado)",
       (r["estado"], r.get("mudou"), r["original"]), ("proprio", True, os.path.join("MIDIA", "JUL_7503.mp4")))
    r = casar(DECL, {"MIDIA/JUL_7503.mp4": camera(None)}, PROJ)
    ok("o arquivo sem duração legível: prova incompleta → sem original (realocado)",
       (r["estado"], r.get("mudou"), bool(r.get("realocado"))), ("sem_original", None, True))
    r = casar(DECL, {"MIDIA/JUL_7503.mp4": camera(12.0)}, PROJ, dentro=False)
    ok("fora das pastas indicadas: não vale como o próprio", r.get("mudou"), None)
    r = casar(DECL, {"MIDIA/JUL_7503.mp4": camera(12.0), "ORIG/JUL_7503.mov": camera(12.0, 3840, 2160, "prores")}, PROJ)
    ok("o original de câmera (outro raster/codec) continua vencendo",
       (r["estado"], r.get("mudou"), r["original"]), ("original", None, os.path.join("ORIG", "JUL_7503.mov")))
    r = casar(DECL, {"MIDIA/JUL_7503.mp4": camera(14.0)}, PROJ)
    ok("duração diferente: não é o mesmo arquivo", (r["estado"], r.get("mudou")), ("sem_original", None))
    casamento = {DECL: {"estado": "proprio", "original": "D:/M/JUL_7503.mp4", "mudou": True},
                 "Z:/x/LOU.mp4": {"estado": "proprio", "original": "Z:/x/LOU.mp4"}}
    with mock.patch.object(P, "recusado", lambda p: False), mock.patch("os.path.isfile", lambda p: True):
        lista = {m["nome"]: m for m in P.lista_de_midias(casamento)}
    ok("a lista: 'mudou' conta como encontrado", (lista["JUL_7503.mp4"]["estado"], lista["JUL_7503.mp4"]["como"]),
       ("original", "mudou"))
    ok("…e o próprio no lugar continua 'proprio'", lista["LOU.mp4"]["como"], "proprio")
    # "Relinkar só as offline" (autor, 2026-10-24): a lista diz se o arquivo do PROJETO está no disco hoje
    with mock.patch.object(P, "recusado", lambda p: False), \
            mock.patch("os.path.isfile", lambda p: "LOU" in p):
        lista = {m["nome"]: m for m in P.lista_de_midias(casamento)}
    ok("⭐ online = o arquivo que o PROJETO declara existe (não o achado)",
       (lista["JUL_7503.mp4"]["online"], lista["LOU.mp4"]["online"]), (False, True))

    print("── os sons na lista de mídias ──")
    segs = [{"is_audio": True, "media_ref": {"local_path": "Z:/s/A.wav"}},
            {"is_audio": True, "media_ref": {"local_path": "Z:/s/B.wav"}},
            {"is_audio": True, "media_ref": {"local_path": "Z:/s/A.wav"}},
            {"is_audio": False, "media_ref": {"local_path": "Z:/v/C.mp4"}},
            {"is_audio": True, "media_ref": {"local_path": "Z:/v/C.mp4"}}]
    with mock.patch.object(P, "recusado", lambda p: False), mock.patch("os.path.isfile", lambda p: False):
        sons = P.lista_de_sons(segs, {"Z:/s/A.wav": {"realocado": "D:/s/A.wav"}, "Z:/s/B.wav": {"candidatos": []}})
    ok("um por arquivo, sem o som da câmera (vai com o vídeo)", [m["nome"] for m in sons], ["A.wav", "B.wav"])
    ok("achado pela duração = mudou; nada = não encontrado", [(m["estado"], m["como"]) for m in sons],
       [("original", "mudou"), ("nao_encontrado", "")])
    ok("marcado como som", all(m["som"] for m in sons), True)

    print("── a cópia relinkada ──")
    xml = ("<PremiereData>"
           '<Media ObjectUID="m1" ClassID="c" Version="30"><FilePath>Z:\\EDICAO\\JUL_7503.mp4</FilePath>'
           "<ActualMediaFilePath>Z:\\EDICAO\\JUL_7503.mp4</ActualMediaFilePath>"
           "<RelativePath>..\\..\\Z:\\EDICAO\\JUL_7503.mp4</RelativePath><Title>JUL_7503.mp4</Title>"
           '<OfflineReason>1</OfflineReason><VideoStream ObjectRef="7"/></Media>'
           '<Media ObjectUID="m2" ClassID="c" Version="30"><FilePath>z:\\edicao\\jul_7503.mp4</FilePath>'
           "<ActualMediaFilePath>z:\\edicao\\jul_7503.mp4</ActualMediaFilePath></Media>"
           '<Media ObjectUID="m3" ClassID="c" Version="30"><FilePath>Z:\\OUTRO\\X.mp4</FilePath></Media>'
           '<VideoStream ObjectID="7" ClassID="v" Version="23"><FrameRect>0,0,1920,1080</FrameRect></VideoStream>'
           "</PremiereData>")
    novo, conta = C.relinkar(xml, {"Z:\\EDICAO\\JUL_7503.mp4": "D:\\ORIG\\JUL_7503 & cia.mov"},
                             {"D:\\ORIG\\JUL_7503 & cia.mov": (3840, 2160)})
    ok("os dois Media do mesmo arquivo (a caixa não importa), o outro não", (conta["media"], conta["caminhos"]), (2, 1))
    ok("FilePath, ActualMediaFilePath e RelativePath com o caminho novo (escapado)",
       novo.count("D:\\ORIG\\JUL_7503 &amp; cia.mov"), 5)
    ok("o Title acompanha o nome novo", "<Title>JUL_7503 &amp; cia.mov</Title>" in novo, True)
    ok("o OfflineReason sai", "OfflineReason" in novo, False)
    ok("o FrameRect acompanha o raster novo", "<FrameRect>0,0,3840,2160</FrameRect>" in novo, True)
    ok("o arquivo que não está na troca fica igual", "<FilePath>Z:\\OUTRO\\X.mp4</FilePath>" in novo, True)
    with tempfile.TemporaryDirectory() as d:
        orig, saida = os.path.join(d, "editor.prproj"), os.path.join(d, "copia.prproj")
        with gzip.open(orig, "wb") as f:
            f.write(xml.encode("utf-8"))
        C.gravar_copia(orig, saida, {"Z:\\OUTRO\\X.mp4": "D:\\X.mp4"})
        ok("a cópia é um gzip que se lê", "D:\\X.mp4" in C.ler_xml(saida), True)
        ok("o projeto do editor não muda", "D:\\X.mp4" in C.ler_xml(orig), False)
        try:
            C.gravar_copia(orig, orig.upper() if os.name == "nt" else orig, {})
            ok("⛔ nunca por cima do projeto do editor", "gravou", "recusou")
        except ValueError:
            ok("⛔ nunca por cima do projeto do editor", "recusou", "recusou")

    print("── a conferência dos caminhos depois do importSequences ──")
    import premiere_copia as PC
    plano = {"copia": "c.prproj", "seq": "s", "original": "SEQ", "nome": "SEQ · relink", "bin": "De Lá Pra Cá",
             "tpf": 10594584000, "escalas": {},
             "decidido": {"Z:\\A.mp4": "D:\\M\\A.mp4", "Z:\\B.wav": "D:\\M\\B.wav"},
             "marcas": [], "onde": {"c.wav": {"quadro": 24, "trilha": "A3", "plano": "C.wav", "t": 24 * 10594584000}}}
    chamadas = []

    def ponte(funcao, *args, prazo=0):
        chamadas.append((funcao, args))
        if funcao == "dlpcImportarCopia":
            return {"ok": True, "id": "novo", "sequencia": "SEQ · relink", "novas": 2, "escalas": 0,
                    "itens": [{"nome": "A.mp4", "caminho": "d:/m/a.mp4", "offline": False},
                              {"nome": "B.wav", "caminho": "D:\\M\\B.wav", "offline": False},
                              {"nome": "C.wav", "caminho": "D:\\OUTRA\\C.wav", "offline": False},
                              {"nome": "D.mp4", "caminho": "Z:\\D.mp4", "offline": True},
                              {"nome": "Graphic", "caminho": "", "offline": False}]}
        return {"ok": True, "marcadores": len(args[0]["marcas"])}

    with mock.patch.object(PC.premiere_ponte, "chamar", ponte):
        r = PC.executar(plano)
    ok("os da lista (caixa e barras não importam)", (r["clipes"], r["no_lugar"]), (4, 2))
    ok("⭐ o religado pelo Premiere é apontado", r["religados_pelo_premiere"], ["D:\\OUTRA\\C.wav"])
    ok("o offline é contado", r["offline"], ["D.mp4"])
    marcas = next(a[0]["marcas"] for f, a in chamadas if f == "dlpcMarcar")
    ok("…e ganha marcador no lugar dele (amarelo)", [(m["nome"], m["t"], m["cor"]) for m in marcas],
       [("Religado pelo Premiere", str(24 * 10594584000), "Yellow")])
    ok("o plano guarda a sequência criada (a conferência acha a taxa por ela)", plano.get("seq_id"), "novo")

    print("── o caso real (R04, a mídia 'mudada' para um disco que não existe) ──")
    real = r"%USERPROFILE%\Desktop\WSP-DLPC_2.prproj"
    midia = r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar\03 CASOS\REAL\R04 PRODUCAO-C\ISOLADO\MIDIA"
    if not (os.path.isfile(real) and os.path.isdir(midia)):
        print("  PULADO (o projeto ou a mídia do R04 não estão nesta máquina)")
    else:
        with tempfile.TemporaryDirectory() as d:
            movido = os.path.join(d, "movido.prproj")
            C.gravar_xml(movido, C.ler_xml(real).replace(midia, r"Z:\EDICAO_PRODC\MIDIA_ANTIGA"))
            O._SONDA.clear()
            a = P.analisar(movido, "b07964be-839b-44b2-bc11-70cdf22ba9fd", [midia])
            ok("⭐ 47 vídeos 'mudou de lugar' + o logo; nenhum sem original", a["resumo"]["casamento"], {"proprio": 48})
            como = {}
            for m in a["resumo"]["midias"]:
                como[(m.get("som", False), m["como"])] = como.get((m.get("som", False), m["como"]), 0) + 1
            ok("a lista: 47 vídeos e 21 sons 'mudou', o logo achado pelo raster",
               como, {(False, "mudou"): 47, (False, "proprio"): 1, (True, "mudou"): 21})

    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
