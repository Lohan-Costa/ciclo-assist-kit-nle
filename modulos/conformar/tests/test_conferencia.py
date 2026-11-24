"""A conferência pela referência, do lado do serviço (organograma aprovado pelo autor, 2026-10-04).

Rodar:

    .venv/bin/python tests/test_conferencia.py        (Windows: .venv-win/Scripts/python)

Sem Resolve: um vídeo de referência sintético (ffmpeg, `testsrc2` com o número do quadro), e os
"quadros exportados pelo Resolve" tirados dele — um do quadro CERTO, um de OUTRO quadro e um que
falta. Confere o plano (TC a partir do início da timeline), a fila em segundo plano, o placar,
os marcadores só dos que não conferem, e o continuar de onde parou / do começo.

A pasta de dados vai para uma pasta temporária (e o cache vai junto, `plataforma._dados_desviados`):
o teste não toca a do usuário.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import plataforma  # noqa: E402
from media import fftools  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def _quadro(ref: str, n: int, destino: str) -> None:
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-ss", f"{n / 24:.6f}", "-i", ref,
                    "-frames:v", "1", "-q:v", "3", destino], check=True)


def _esperar(c, cid, s=30):
    t = time.time()
    while time.time() - t < s:
        e = c.estado(cid)
        if not e["na_fila"]:
            return e
        time.sleep(0.1)
    return c.estado(cid)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        plataforma.pasta_dados = lambda: Path(tmp)          # nada na pasta real do usuário
        import conferencia

        ref = os.path.join(tmp, "ref.mp4")
        subprocess.run([fftools.ffmpeg(), "-v", "error", "-f", "lavfi", "-i",
                        "testsrc2=size=640x360:rate=24:duration=6", "-pix_fmt", "yuv420p", ref], check=True)
        # a referência começa no quadro 0 da timeline, que começa em 01:00:00:00
        ctx = {"referencia": ref, "trilha_referencia": 7, "ref_na_timeline": 0, "ref_entrada": 0,
               "ref_fps": 24.0, "fps": 24.0, "nominal": 24, "inicio": 86400, "quadro_px": [640, 360],
               "pontos": [{"quadro": 10, "ponta": "entrada", "plano": "1-1-1", "trilha": 1, "arquivo": "A.mov"},
                          {"quadro": 50, "ponta": "saída", "plano": "1-1-1", "trilha": 1, "arquivo": "A.mov"},
                          {"quadro": 90, "ponta": "entrada", "plano": "2-1-1", "trilha": 2, "arquivo": "B.mov"}]}
        c = conferencia.Conferencias()
        print("o plano")
        p = c.criar(ctx, "FILME")
        ok("três pontos e a estimativa (0,5 s cada)", (p["pontos"], p["segundos"]), (3, 2))
        ini = c.iniciar(p["id"])
        ok("TC = início da timeline + quadro", [x["tc"] for x in ini["faltam"]],
           ["01:00:00:10", "01:00:02:02", "01:00:03:18"])
        pasta = Path(c.pasta(p["id"]))
        ok("⭐ a pasta é legível: Cache/Conferências/<timeline> · AAAA-MM-DD HHhMM",
           (pasta.parent == Path(tmp, "Cache", "Conferências"), bool(__import__("re").fullmatch(
            r"FILME · \d{4}-\d\d-\d\d \d\dh\d\d", pasta.name))), (True, True))
        ok("a casca grava só em _interno/<quadro>.jpg",
           all(Path(x["imagem"]).parent == pasta / "_interno" for x in ini["faltam"]), True)
        ok("a trilha da referência vai para a casca desligar", ini["trilha_referencia"], 7)

        print("comparar em segundo plano")
        a, b, _c = ini["faltam"]
        _quadro(ref, 10, a["imagem"])          # o quadro certo
        # uma imagem de OUTRO plano (o testsrc2 muda pouco de um quadro a outro: a forma confere)
        subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i",
                        "smptehdbars=size=640x360", "-frames:v", "1", b["imagem"]], check=True)
        # o terceiro: o Resolve não exportou
        ok("a fila aceita na hora", c.comparar(p["id"], [10, 50, 90, 999]), 3)
        e = _esperar(c, p["id"])
        ok("placar: 1 confere, 2 não", (e["comparados"], e["conferem"], e["nao_conferem"]), (3, 1, 2))
        m = c.marcas(p["id"])
        ok("marcadores só dos que não conferem", [x["quadro"] for x in m["marcas"]], [50, 90])
        ok("marcador roxo; o NOME é o tipo do problema",
           (m["cor"], m["marcas"][0]["nome"], m["marcas"][1]["nome"]),
           ("Purple", "Não confere com a referência", "Não deu para conferir"))
        ok("as Notes dizem a trilha (Trk V2), o plano e o TC",
           m["marcas"][1]["nota"].startswith("Trk V2 · 2-1-1 · entrada em 01:00:03:18"), True)

        print("a pasta para quem a abre (organograma de cache e logs, 2026-10-05)")
        jpgs = sorted(x.name for x in pasta.glob("*.jpg"))
        ok("⭐ comparado, o quadro sai de _interno com o nome de TC, trilha, plano e ponta; os que "
           "não conferem vêm primeiro", jpgs,
           ["01_00_00_10 V1 1-1-1 início.jpg", "NÃO CONFERE 01_00_02_02 V1 1-1-1 fim.jpg"])
        ok("_interno fica só com o plano e os resultados",
           sorted(x.name for x in (pasta / "_interno").iterdir()), ["plano.json", "resultados.json"])
        linhas = (pasta / "conferencia.csv").read_text(encoding="utf-8-sig").splitlines()
        ok("⭐ conferencia.csv: cabeçalho e uma linha por ponto comparado, ; e vírgula decimal",
           (linhas[0], len(linhas)), ("TC;trilha;plano;ponta;semelhança;confere;imagem", 4))
        ok("…com o confere e o nome do JPEG",
           (linhas[1].split(";")[5], linhas[1].split(";")[6], linhas[2].split(";")[5],
            linhas[3].split(";")[5].startswith("erro:"), "," in linhas[1].split(";")[4]),
           ("sim", "01_00_00_10 V1 1-1-1 início.jpg", "não", True, True))
        ok("a conferência recém-usada está EM USO (o Limpar espera, o teto pula)",
           c.em_uso(), [str(pasta)])

        print("dois pontos no MESMO quadro (R04 22:08, V3 e V4 na cópia do Premiere, 2026-10-29)")
        ctx2 = dict(ctx, pontos=[{"quadro": 30, "ponta": "entrada", "plano": "3-1-1", "trilha": 3, "arquivo": "C.mov"},
                                 {"quadro": 30, "ponta": "entrada", "plano": "nest", "trilha": 4, "arquivo": "nest"}])
        p2 = c.criar(ctx2, "DUPLO")
        ini2 = c.iniciar(p2["id"])
        _quadro(ref, 30, ini2["faltam"][0]["imagem"])
        c.comparar(p2["id"], [30, 30])                       # o painel manda o quadro uma vez por ponto
        e2 = _esperar(c, p2["id"])
        ok("⭐ o 2º não rebaixa a erro o quadro que o 1º já comparou", (e2["conferem"], e2["nao_conferem"]), (1, 0))

        print("continuar e recomeçar")
        c2 = conferencia.Conferencias()                     # o serviço reiniciou: lê do disco
        ok("continuar: nada falta (os 3 têm resultado)", len(c2.iniciar(p["id"])["faltam"]), 0)
        r = c2.iniciar(p["id"], do_comeco=True)
        ok("do começo: os 3 de novo, sem os JPEGs antigos (nem os de nome legível) e sem o CSV",
           (len(r["faltam"]), os.path.exists(a["imagem"]), r["comparados"], list(pasta.glob("*.jpg")),
            (pasta / "conferencia.csv").exists()), (3, False, 0, [], False))
        import shutil
        shutil.rmtree(pasta)
        ok("⭐ o Limpar levou a pasta: a conferência diz que não está mais aqui",
           _erro(lambda: c2.iniciar(p["id"])), "LookupError")
        q = conferencia.Conferencias()
        ok("id inválido é recusado", _erro(lambda: q.iniciar("../../etc")), "ValueError")
        ok("conferência que não existe", _erro(lambda: q.iniciar("0" * 32)), "LookupError")

    print("marcadores do Importar: nome = tipo, Notes = observações (autor, 2026-10-04)")
    from tools.prproj_para_drt import _sinais_das_marcas, trilha_rotulo
    n = _sinais_das_marcas([
        {"quadro": 48, "cor": "Yellow", "nota": "conferir: Crop com máscara (Fusion)", "tipo": "Efeito no Fusion",
         "trilha": 5, "segmento": 3},
        {"quadro": 48, "cor": "Red", "nota": "REFAZER no original: original não encontrado", "tipo": "Sem o original",
         "trilha": 5, "segmento": 3}])[0]
    ok("o tipo do marcador é o do problema mais forte (refazer)", n["tipo"], "Sem o original")
    ok("cada observação começa pela trilha (Trk V5), o refazer primeiro",
       [linha[0][0][:22] for linha in n["linhas"]], ["Trk V5 · REFAZER no or", "Trk V5 · conferir: Cro"])
    ok("rótulo de trilha de áudio", trilha_rotulo(2, audio=True), "Trk A2")

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


def _erro(f):
    try:
        f()
    except Exception as e:                # noqa: BLE001
        return type(e).__name__
    return None


if __name__ == "__main__":
    raise SystemExit(main())
