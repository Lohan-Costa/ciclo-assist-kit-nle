"""REESCREVER a timeline do colorista (caminho B do Atualizar), nos DRTs REAIS do caso U01.

Rodar:

    .venv-win/Scripts/python tests/test_reescrever.py

O caso `03 CASOS/ATUALIZAR/U01 VERSOES DO RESOLVE` tem a mesma timeline trabalhada pelo autor no
Resolve 19 (Windows) e no 21 (Mac mini): uma correção, um CORTE INTERNO no plano 2, duas versões e
dois nós no plano 3 e um ADJUSTMENT CLIP na V2 sobre o plano 4.

A montagem nova (feita aqui, de propósito): o plano 2 perde 10 quadros na cabeça e o plano 7 sai,
com ripple. Nas DUAS versões, o arquivo reescrito tem de:
- aparar só a metade do plano 2 que encosta na cabeça; a outra metade só anda;
- apagar o plano 7 e puxar o resto; o adjustment clip anda com a montagem embaixo dele;
- manter byte a byte a correção (`Body`) de cada item que ficou, e o cabeçalho da versão.
"""

from __future__ import annotations

import copy
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import atualizar as A  # noqa: E402
from drp import reescrever as RW  # noqa: E402

from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
U01 = Path(raiz_das_amostras()) \
    / "03 CASOS" / "ATUALIZAR" / "U01 VERSOES DO RESOLVE"


def tc(q: int, fps: int = 24) -> str:
    return f"{q // (3600 * fps):02d}:{q // (60 * fps) % 60:02d}:{q // fps % 60:02d}:{q % fps:02d}"


def carta_da_base(base: str) -> dict:
    """A Carta de partida: os 14 planos da V1 do `base.drt` (o que o colorista recebeu)."""
    segs = [{"timeline_tc_in": tc(i["inicio"]), "duration_frames": i["dur"], "mob_id": i["nome"],
             "source_start_frames": i["fonte_in"], "track": 1, "is_audio": False, "is_gap": False,
             "is_transition": False, "clip_name": i["nome"], "speed_ratio": 1.0}
            for i in RW.itens(base) if i["trilha"] == "V1"]
    return {"timeline_fps": 24, "segments": segs, "masters": {}}


def nova_montagem(partida: dict) -> dict:
    """O plano 2 perde 10 quadros na cabeça; o plano 7 sai; tudo depois anda (ripple)."""
    nova = copy.deepcopy(partida)
    segs = nova["segments"]
    segs[1]["source_start_frames"] += 10
    segs[1]["duration_frames"] -= 10
    del segs[6]
    q = 0
    for s in segs:
        s["timeline_tc_in"] = tc(q)
        q += s["duration_frames"]
    return nova


def bodies(drt: str) -> dict:
    """{nome do item + trilha + ordem: [Body hex]} — a correção de cada item, para comparar."""
    with zipfile.ZipFile(drt) as z:
        s = z.read(next(n for n in z.namelist() if n.startswith("SeqContainer/"))).decode("utf-8")
    fora = []
    for m in re.finditer(r"<Sm2TiVideoClip DbId=\"[^\"]+\">(.*?)</Sm2TiVideoClip>", s, re.S):
        fora.append(re.findall(r"<Body>(\w*)</Body>", m.group(1)))
    return fora


def cabecalho(drt: str) -> str:
    with zipfile.ZipFile(drt) as z:
        return re.search(r"<!--(DbAppVer=[^>]*)-->", z.read("project.xml").decode("utf-8")).group(1)


def _pb_marcadores(px: str) -> list:
    """O protobuf do bloco de marcadores de um `project.xml` (campos do topo)."""
    import zstandard
    from drp.ba_mapa import ler_mapa
    fb = re.search(r"<Sm2SequenceLockableBlob\b.*?<FieldsBlob>(\w+)</FieldsBlob>", px, re.S).group(1)
    raw = ler_mapa(bytes.fromhex(fb))[1][0][1][2]
    pb = zstandard.ZstdDecompressor().decompress(raw[9:], max_output_size=1 << 20) if raw[8:9] == b"\x81" else raw[9:]
    return RW._campos(pb)


def _meios(px: str) -> list[int]:
    """Os valores CRUS da forma do 21 (meio-quadro), sem dividir."""
    fora = []
    for _n, _t, v in _pb_marcadores(px):
        for n1, _t1, e in RW._campos(v):
            for n2, t2, q in RW._campos(e):
                if n1 == 2 and n2 == 1 and t2 == 2:
                    fora += [m for n3, t3, m in RW._campos(q) if n3 == 1 and t3 == 0]
    return fora


def _desconhecida(pb: bytes) -> str:
    """O aviso do reescritor para um bloco de marcadores com a forma `pb` (nenhuma medida)."""
    from drp import sinais
    px = ('<Sm2SequenceLockableBlob DbId="x"><FieldsBlob>'
          + sinais._fields_blob(sinais._blob_data(pb, comprimir=True)) + "</FieldsBlob>")
    _px, fora = RW._mover_marcadores(px, lambda q: (q, True))
    return (fora[0].get("erro") or "") if fora else ""


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<62} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    if not (U01 / "base.drt").is_file():
        print(f"PULADO — {U01} não está neste disco")
        return 0
    partida = carta_da_base(str(U01 / "base.drt"))
    nova = nova_montagem(partida)
    for versao in ("resolve19.drt", "resolve21.drt"):
        drt = U01 / versao
        if not drt.is_file():
            print(f"── {versao}: PULADO (não está na pasta)")
            continue
        print(f"\n── {versao} ({cabecalho(str(drt))}) ──")
        ini = RW.inicio_timeline(str(drt))
        itens = RW.itens(str(drt), inicio=ini)
        v1 = [i for i in itens if i["trilha"] == "V1"]
        ajuste = next(i for i in itens if i["tipo"] == "Adjustment Clip")
        pe = A.plano_de_edicao(partida, nova, itens)
        acao = lambda i: pe["itens"][i["id"]]  # noqa: E731
        # V1 do colorista: [p1, p2a, p2b, p3, p4, p5, p6, p7, p8…p14] (o p2 cortado no meio)
        p2a, p2b, p7 = v1[1], v1[2], v1[7]
        ok("⭐ a cabeça do corte interno é aparada em 10 quadros",
           (acao(p2a)["acao"], acao(p2a)["inicio"], acao(p2a)["dur"], acao(p2a)["fonte_in"]),
           ("aparar", 120, p2a["dur"] - 10, 10))
        ok("⭐ a outra metade só anda 10", (acao(p2b)["acao"], acao(p2b)["inicio"], acao(p2b)["dur"]),
           ("mover", p2b["inicio"] - 10, p2b["dur"]))
        ok("o plano 7 sai", acao(p7)["acao"], "apagar")
        ok("⭐ o adjustment clip anda com a montagem embaixo dele", (acao(ajuste)["acao"], acao(ajuste)["inicio"]),
           ("mover", ajuste["inicio"] - 10))
        ok("o plano 14 anda 130 (10 + o plano 7)", acao(v1[-1])["inicio"], v1[-1]["inicio"] - 130)

        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "atualizado.drt")
            conta = RW.aplicar(str(drt), saida, pe["itens"], ini)
            ok("contagem das ações", (conta.get("apagar"), conta.get("aparar")), (1, 1))
            depois = RW.itens(saida, inicio=ini)
            dv1 = [i for i in depois if i["trilha"] == "V1"]
            ok("a V1 ficou com um item a menos", len(dv1), len(v1) - 1)
            ok("⭐ as posições saem sem buraco nem sobreposição",
               all(a["inicio"] + a["dur"] == b["inicio"] for a, b in zip(dv1, dv1[1:])), True)
            ok("o In do adjustment clip não muda (é o tempo do gerador)",
               next(i for i in depois if i["tipo"] == "Adjustment Clip")["fonte_in"], ajuste["fonte_in"])
            antes_b, depois_b = bodies(str(drt)), bodies(saida)
            del antes_b[7]                                    # o plano 7 saiu
            ok("⭐ a correção de CADA item que ficou é a mesma, byte a byte (inclusive as 2 versões)",
               antes_b == depois_b, True)
            ok("⭐ o cabeçalho da versão do colorista fica", cabecalho(saida), cabecalho(str(drt)))
            # U02 (2026-09-28): trocar TODOS os ids (ou todos os definidos) DERRUBA o Resolve 19 ao
            # importar a PRODA reescrita; trocar só os DA TIMELINE importou. A mídia e a pasta ficam.
            with zipfile.ZipFile(str(drt)) as z1, zipfile.ZipFile(saida) as z2:
                a1 = {n: z1.read(n) for n in z1.namelist()}
                da_tl = RW._ids_da_timeline(a1)
                novos = set(RW.UUID.findall(" ".join(z2.read(n).decode() for n in z2.namelist())))
                midia = set(re.findall(r'<Sm2Mp(?:Video|Audio)Clip DbId="([^"]+)"',
                                       a1["MediaPool/Master/MpFolder.xml"].decode()))
            ok("⭐ nenhum id DA TIMELINE antigo sobra (reimporta no mesmo projeto)", da_tl & novos, set())
            ok("⭐ os ids da MÍDIA do pool ficam (trocá-los derrubava o Resolve)", midia <= novos, True)

    print("\n── revisão de código (2026-09-28) ──")
    with tempfile.TemporaryDirectory() as d:
        com_bin = os.path.join(d, "bin.drt")
        with zipfile.ZipFile(str(U01 / "resolve19.drt")) as z1, zipfile.ZipFile(com_bin, "w") as z2:
            for n in z1.namelist():
                z2.writestr(n, z1.read(n))
            z2.writestr("Thumbs/miniatura.bin", bytes(range(256)))
        saida = os.path.join(d, "s.drt")
        RW.aplicar(com_bin, saida, {}, 86400)
        with zipfile.ZipFile(saida) as z:
            ok("⭐ uma parte BINÁRIA do pacote passa intacta, em bytes", z.read("Thumbs/miniatura.bin"), bytes(range(256)))
        # B025 (banco, bugs-do-mundo-real), 2026-10-09: o `nome` do aplicar trocava o <Name> com o dado
        # no MOLDE do re.sub e procurava `<Sm2Sequence DbId=` no arquivo da sequência, onde a tag é
        # `Sm2SequenceContainer`: nunca casou, o nome era ignorado calado. Saiu — o nome da timeline é
        # do writer (função + escape) e do SetName da casca.
        try:
            RW.aplicar(com_bin, os.path.join(d, "n.drt"), {}, 86400, nome="x")
            ok("o aplicar não aceita mais um nome que ele ignorava", "aceitou", "recusou")
        except TypeError:
            ok("o aplicar não aceita mais um nome que ele ignorava", "recusou", "recusou")
    hostil = r"D:\MIDIAS\x \1 \g<0>"
    ok("B025: o valor escrito pelo _trocar sai literal (barra do Windows e \\g<0> não se expandem)",
       RW._trocar("<Name>a</Name>", "Name", hostil), f"<Name>{hostil}</Name>")
    try:
        RW._trocar("<Start>1</Start>", "In", 10, obrigatorio=True)
        ok("⭐ aparar um item sem <In>: para (o corte não se perde em silêncio)", "não parou", "parou")
    except ValueError:
        ok("⭐ aparar um item sem <In>: para (o corte não se perde em silêncio)", "parou", "parou")

    print("\n── marcadores de timeline e cor local (resolve19 marcadores e cor.drt) ──")
    marc = U01 / "resolve19 marcadores e cor.drt"
    if not marc.is_file():
        print("  PULADO")
    else:
        # o mesmo base.drt com: plano 1 Pink (cor LOCAL pela API), marcador A no quadro 24 (plano 1)
        # e B no 500 (plano 5, com customData DLPC)
        ok("quadro_novo: dentro de um trecho que continua, anda", A.quadro_novo([(0, 100, 0), (100, 200, -10)], 150),
           (140, True))
        ok("⭐ quadro_novo: num trecho que saiu, vai para o ponto do corte e pede conferência",
           A.quadro_novo([(0, 100, 0), (200, 300, -100)], 150), (100, False))
        ini = RW.inicio_timeline(str(marc))
        itens = RW.itens(str(marc), inicio=ini)
        pe = A.plano_de_edicao(partida, nova, itens)
        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "m.drt")
            conta = RW.aplicar(str(marc), saida, pe["itens"], ini,
                               mover_quadro=lambda q: A.quadro_novo(pe["mapa"], q))
            with zipfile.ZipFile(saida) as z:
                px = z.read("project.xml").decode("utf-8")
            import zstandard
            from drp.ba_mapa import ler_mapa
            fb = re.search(r"<Sm2SequenceLockableBlob\b.*?<FieldsBlob>(\w+)</FieldsBlob>", px, re.S).group(1)
            raw = ler_mapa(bytes.fromhex(fb))[1][0][1][2]
            pb = zstandard.ZstdDecompressor().decompress(raw[9:], max_output_size=1 << 20)
            quadros = sorted(q for n, t, e in RW._campos(RW._campos(pb)[0][2]) if n == 1
                             for n2, t2, q in RW._campos(e) if n2 == 1 and t2 == 0)
            ok("⭐ os marcadores do colorista andam com a montagem (24 fica; 500 → 490)", quadros, [24, 490])
            ok("…nome, nota e customData viajam intactos", all(x in pb for x in (b"MARCA A", b"MARCA B", b"nota b", b"DLPC")),
               True)
            ok("nenhum marcador fora do lugar nesta montagem", conta["marcadores_fora_do_lugar"], 0)
            ok("⭐ a cor LOCAL do plano 1 (que ficou) continua", px.count("<Sm2TiItemLockableBlob"), 1)
        # agora o plano 1 SAI: a cor local dele não pode ficar órfã, e o marcador A vai para o corte
        sem1 = copy.deepcopy(partida)
        del sem1["segments"][0]
        q = 0
        for s in sem1["segments"]:
            s["timeline_tc_in"] = tc(q)
            q += s["duration_frames"]
        pe = A.plano_de_edicao(partida, sem1, itens)
        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "m2.drt")
            conta = RW.aplicar(str(marc), saida, pe["itens"], ini,
                               mover_quadro=lambda q: A.quadro_novo(pe["mapa"], q))
            with zipfile.ZipFile(saida) as z:
                px = z.read("project.xml").decode("utf-8")
            ok("⭐ o plano 1 saiu: a cor local dele sai junto (nada órfão)", px.count("<Sm2TiItemLockableBlob"), 0)
            ok("⭐ o marcador A (no trecho que saiu) fica no ponto do corte e é contado", conta["marcadores_fora_do_lugar"], 1)

    print("\n── marcadores na forma do RESOLVE 21 (U03 v01 com Sinais - Resolve 21 Mac.drt) ──")
    # O 21 exporta { 2: { 2: entrada } } com o quadro × 2 numa submensagem (medido 2026-10-01). Antes,
    # só a forma do 19 andava: no U03 o marcador da VELOCIDADE ficou 855 quadros fora do plano (autor).
    m21 = U01.parent / "U03 ATUALIZAR COM AAF" / "resolve" / "U03 v01 com Sinais - Resolve 21 Mac.drt"
    if not m21.is_file():
        print("  PULADO")
    else:
        ok("⭐ os 7 marcadores do 21 são LIDOS (os quadros da API)", RW.quadros_dos_marcadores(str(m21)),
           [1, 266, 456, 627, 3640, 5780, 10552])
        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "m21.drt")
            # a v02 do U03 tirou 855 quadros antes do plano da velocidade (10552 → 9697)
            conta = RW.aplicar(str(m21), saida, {}, 86400,
                               mover_quadro=lambda q: (q - 855 if q >= 9697 + 855 else q, True))
            ok("⭐ …e ANDAM com a montagem: o da velocidade vai junto com o plano (10552 → 9697)",
               RW.quadros_dos_marcadores(saida), [1, 266, 456, 627, 3640, 5780, 9697])
            ok("nenhum fora do lugar", conta["marcadores_fora_do_lugar"], 0)
            with zipfile.ZipFile(saida) as z:
                px = z.read("project.xml").decode("utf-8")
            ok("…e continuam na forma do 21: { 2: { 2: … } }, meio-quadro 9697 × 2",
               [n for n, _t, _v in RW._campos(_pb_marcadores(px)[0][2])][:1] + [19394 in _meios(px)], [2, True])
        # ⭐ A TRANSIÇÃO do editor no take trocado (autor, 2026-10-01: "nada deve ser perdido"): o plano
        # antigo da A1 (92622–93070) sai; um plano NOVO vai encostar no corte de 93070. Com o corte
        # informado, o cross-fade fica; sem ele (o código de antes), sai.
        velho = next(i for i in RW.itens(str(m21), absoluto=True) if i["trilha"] == "A1" and i["start"] == 92622)
        with tempfile.TemporaryDirectory() as d:
            sem = os.path.join(d, "sem.drt"); com = os.path.join(d, "com.drt")
            c1 = RW.aplicar(str(m21), sem, {velho["id"]: {"acao": "apagar"}}, 86400)
            c2 = RW.aplicar(str(m21), com, {velho["id"]: {"acao": "apagar"}}, 86400, cortes={("A", 1, 93070)})
            na = lambda f: [(t["trilha"], t["start"], t["dur"]) for t in RW.transicoes(f) if t["start"] == 93070 and t["trilha"] == "A1"]  # noqa: E731
            ok("sem o corte do plano novo, a transição sai (e é contada)", (na(sem), c1.get("transicoes_removidas")), ([], 1))
            ok("⭐ com o corte do plano novo, o cross-fade do editor FICA", (na(com), c2.get("transicoes_removidas")),
               ([("A1", 93070, 40)], None))
        # ⭐ ESCREVER e TIRAR transições (autor, 2026-10-01: "nada deve ser perdido"): a transição sai e volta,
        # com o bloco do Trazer e o alinhamento que o Resolve exige (1 = começa no corte/fade de entrada).
        with tempfile.TemporaryDirectory() as d:
            f = os.path.join(d, "t.drt")
            shutil.copyfile(m21, f)
            antes = sorted((t["trilha"], t["start"], t["dur"]) for t in RW.transicoes(f))
            c = RW.ajustar_transicoes(f, [], {("A1", 87324, 20)})
            ok("tirar: a transição da A1 em 87324 sai", (c["transicoes_tiradas"],
               ("A1", 87324, 20) in [(t["trilha"], t["start"], t["dur"]) for t in RW.transicoes(f)]), (1, False))
            c = RW.ajustar_transicoes(f, [{"trilha": "A1", "start": 87324, "dur": 20, "align": 1, "audio": True}], set())
            ok("⭐ escrever: ela volta, e a timeline tem as MESMAS transições de antes",
               (c["transicoes_novas"], sorted((t["trilha"], t["start"], t["dur"]) for t in RW.transicoes(f))), (1, antes))
            ok("…com a contagem do arquivo original (o que a casca confere)", RW.contagem(f), RW.contagem(str(m21)))
            with zipfile.ZipFile(f) as z:   # fechado: no Windows o zip aberto trava a limpeza da pasta
                blk = next(m.group(3) for m in RW._TRANSICAO.finditer(z.read(RW._seq(z)).decode("utf-8"))
                           if RW._campo(m.group(3), "Start") == "87324")
            ok("…Cross Fade 0DB, alinhamento 1", (RW._campo(blk, "PrettyType"), RW._campo(blk, "AlignmentType")),
               ("Cross Fade 0DB", "1"))
    # ⛔ forma que ninguém mediu: não move e AVISA (antes, o 21 passava calado com 0 "fora do lugar")
    estranho = RW._escrever([(2, 2, RW._escrever([(3, 2, RW._escrever([(1, 0, 10)]))]))])
    ok("⛔ marcadores numa forma desconhecida: avisa em vez de calar",
       bool(_desconhecida(estranho)), True)

    print("\n── a PRODA inteira: transições, títulos e áudio (o DRT 'SINAIS COMPLETOS' como trabalho) ──")
    raiz = U01.parent.parent
    cruz = raiz.parent / "02 PROJETOS AVID" / "PRODUCAO-A" / "03_OC_EDIT VALENDO.avb"
    trab = raiz / "REAL" / "R01 PRODA_CORTE" / "saida" / "PRODA_CORTE.02 SINAIS COMPLETOS (De La Pra Ca).drt"
    if not (cruz.is_file() and trab.is_file()):
        print("  PULADO")
    else:
        from avb_bin import segmentos as S
        from avb_export.reader import topen
        with topen(str(cruz)) as f:
            leitura = S.ler_timeline(f, next(iter(S.sequencias(f))))
        v1 = [i for i, s in enumerate(leitura["segments"]) if not s["is_audio"] and not s["is_gap"]
              and not s.get("is_transition") and s["track"] == 1 and not s.get("disabled")]
        alvo = leitura["segments"][v1[5]]
        q0, dur = A._quadros(alvo["timeline_tc_in"], 24), alvo["duration_frames"]
        nova = copy.deepcopy(leitura)
        nova["segments"] = [s for i, s in enumerate(nova["segments"]) if i != v1[5]]
        for s in nova["segments"]:
            q = A._quadros(s["timeline_tc_in"], 24)
            if q >= q0 + dur:
                s["timeline_tc_in"] = tc(q - dur)
        ini = int(leitura["timeline_start_frames"])      # o início da timeline, não o 1º plano
        itens = RW.itens(str(trab), inicio=ini)
        ok("os títulos e as notas (geradores) agora são itens", sum(1 for i in itens if i["tipo"] != "Sm2TiVideoClip"
                                                                  and i["trilha"][0] == "V" and "Clip" not in i["tipo"]) > 0, True)
        pe = A.plano_de_edicao(leitura, nova, A.trilhas_da_carta(itens, A.trilhas_usadas(leitura)))
        with tempfile.TemporaryDirectory() as d:
            saida = os.path.join(d, "cruz.drt")
            conta = RW.aplicar(str(trab), saida, pe["itens"], ini,
                               mover_quadro=lambda q: A.quadro_novo(pe["mapa"], q))
            print(f"     ações: {conta}")
            ok("⭐ um plano de vídeo sai; nada é inserido", (conta.get("apagar"), len(pe["inserir"])), (1, 0))
            ok("⭐ as transições andam com os cortes", conta.get("transicoes_movidas", 0) > 100, True)
            ok("…e no máximo as duas do corte que sumiu saem", conta.get("transicoes_removidas", 0) <= 2, True)
            depois = RW.itens(saida, inicio=ini)
            with zipfile.ZipFile(saida) as z:
                s = z.read(next(n for n in z.namelist() if n.startswith("SeqContainer/"))).decode("utf-8")
            # toda transição que ficou está sobre um corte de verdade: um item termina e outro começa
            # dentro dela, na mesma trilha
            ruins = 0
            for letra, n, a, b in RW._trilhas(s):
                bloco = s[a:b]
                ivs = [(int(RW._campo(m.group(4), "Start")), int(RW._campo(m.group(4), "Duration")))
                       for m in RW._ITEM.finditer(bloco)]
                for m in RW._TRANSICAO.finditer(bloco):
                    ts, td = int(RW._campo(m.group(3), "Start")), int(RW._campo(m.group(3), "Duration"))
                    if not any(ts <= st <= ts + td or ts <= st + du <= ts + td for st, du in ivs):
                        ruins += 1
            ok("⭐ nenhuma transição ficou longe de um corte", ruins, 0)
            v_antes = sum(1 for i in itens if i["trilha"] == "V1")
            ok("a V1 perdeu exatamente um item", sum(1 for i in depois if i["trilha"] == "V1"), v_antes - 1)
        # a contagem que a API faz: itens + transições (medido na PRODA do autor, 2026-09-28)
        c = RW.contagem(str(trab))
        so_itens = {}
        for i in itens:
            so_itens[i["trilha"]] = so_itens.get(i["trilha"], 0) + 1
        ok("⭐ a contagem soma as transições (a A1 da PRODA tem mais que só os planos)",
           c["A1"] > so_itens["A1"] and c["V1"] >= so_itens["V1"], True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
