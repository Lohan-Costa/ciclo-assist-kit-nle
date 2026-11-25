"""Importar no Resolve um projeto do Premiere (.prproj): abrir → analisar → montar (2026-10-03).

Rodar:

    .venv/bin/python tests/test_importar_prproj.py        (Windows: .venv-win/Scripts/python)

O fluxo do organograma "Do proxy do Premiere ao ARRIRAW no Resolve" (aprovado em 2026-10-02,
atualizado em 2026-10-03) no SERVIÇO: o `abrir` lista as sequências de montagem e devolve as
pastas lembradas daquele projeto; o `analisar_prproj` lê e casa (a tela "antes de montar"); o
`preparar_avulso` monta a partir da análise, com os marcadores e o plano do Fusion por clipe.

Precisa do caso `03 CASOS/REAL/R02 PRODUCAO_B EXEMPLOS` (`DLPC_AMOSTRAS`); sem ele, PULA e sai 0.
Os HDs dos originais não são precisos: sem eles tudo fica "sem original", o que também é caso.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import sessao_receber as R  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


#: Os proxies que o `.prproj` do R02 aponta moram no HD PRODUCAO_B (`caso.json`, `proxy_amostra`).
#: Sem ele, o que depende de abrir a mídia PULA (medido no Windows, 2026-10-04, PRODUCAO_B fora).
COM_PROXIES = True


def ok_proxy(nome, obter, esperado):
    """`ok` que só confere com os proxies do caso nesta máquina (`obter` é chamado só então)."""
    if COM_PROXIES:
        ok(nome, obter(), esperado)
    else:
        print(f"  PULADO (proxies no HD PRODUCAO_B, fora desta máquina) — {nome}")


def achar_caso() -> Path | None:
    from casos import CANDIDATAS_AMOSTRAS  # noqa: E402 (a pasta de testes, nas duas máquinas)
    for raiz in CANDIDATAS_AMOSTRAS:
        p = Path(raiz or "") / "03 CASOS" / "REAL" / "R02 PRODUCAO_B EXEMPLOS" / "premiere" / \
            "DU exemplos especificos.prproj"
        if raiz and p.is_file():
            return p
    return None


def taxas() -> None:
    """O código de taxa no `SequenceSetup` (medido no Resolve 21.1, 2026-10-03) — sem o caso."""
    import re
    import struct
    import zipfile

    from drp.writer import _patch_sequence_setup
    print("── a taxa da timeline no SequenceSetup ──")
    with zipfile.ZipFile(RAIZ / "motor" / "drp" / "skeleton_r19.drt") as z:
        for n in z.namelist():
            m = re.search(r"<Sm2MpTimelineClip\b.*?</Sm2MpTimelineClip>", z.read(n).decode("utf-8", "replace"), re.S)
            if m:
                break
    blob = bytes.fromhex(re.findall(r"<FieldsBlob>([0-9a-fA-F]+)</FieldsBlob>", m.group(0))[1])

    def codigo(fps):
        novo, ok = _patch_sequence_setup(blob, 2880, 1620, fps)
        k = "SequenceSetup".encode("utf-16-be")
        i = novo.find(k) + len(k)
        ss = novo[i + 9:]
        j = ss.find(struct.pack(">QQ", 2880, 1620))
        return ok, struct.unpack(">Q", ss[j + 36:j + 44])[0]
    ok("medidas: 23,976 → 23 · 25 → 25 · 29,97 → 29 · 59,94 → 59",
       [codigo(f) for f in (24000 / 1001, 25.0, 30000 / 1001, 60000 / 1001)],
       [(True, 23), (True, 25), (True, 29), (True, 59)])
    ok("taxa fora da tabela devolve 'não conhecida' (vira aviso), código do esqueleto",
       codigo(12.0), (False, 23))


def main() -> int:
    taxas()
    caso = achar_caso()
    if caso is None:
        print("R02 PRODUCAO_B EXEMPLOS não está no disco — o resto PULADO")
        return 1 if falhas else 0
    with tempfile.TemporaryDirectory() as tmp:
        dados = Path(tmp)
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados):
            s = R.SessaoReceber()

            print("── abrir ──")
            r = s.abrir(str(caso))
            nomes = [x["nome"] for x in r["sequencias"]]
            ok("tipo prproj, com a sequência de montagem do caso", (r["tipo"], "DU exemplos especificos" in nomes),
               ("prproj", True))
            ok("os takes (sequências de um plano só) ficam de fora", "66-1-9" in nomes, False)
            ok("projeto novo: nenhuma pasta lembrada", r["pastas"], [])
            seq = next(x for x in r["sequencias"] if x["nome"] == "DU exemplos especificos")
            ok("a sequência vai pelo ObjectUID, não pelo nome", seq["mob_id"] != seq["nome"], True)
            uid = seq["mob_id"]

            print("── analisar (a tela antes de montar) ──")
            # As pastas dos originais são as do CASO (`caso.json`), não uma lista de HDs escrita aqui
            # (regra do autor, 2026-10-04: cada caso é uma ilha). Sem o HD do caso: uma pasta vazia.
            import casos as ilhas
            manifesto = ilhas.carregar("REAL/R02 PRODUCAO_B EXEMPLOS")
            esp = manifesto["expectativas"]["analise"]
            pastas = [str(p) for p in manifesto["raizes_arquivos"]]
            com_o_hd = not manifesto["faltando"]
            global COM_PROXIES
            COM_PROXIES = manifesto["arquivo"].get("proxy_amostra") is not None
            pastas = pastas or [tmp]
            a = s.analisar_prproj(r["chave"], uid, pastas)
            ok("o resumo conta os 16 planos e as 3 composições do Fusion",
               (a["planos"], a["efeitos"]["fusion"]), (esp["planos"], 3))
            if com_o_hd:
                ok("com o HD do caso: os planos no original e os que faltam são os que o caso declara",
                   (a["no_original"], sorted(a["faltam"])), (esp["no_original"], sorted(esp["sem_original"])))
            else:
                print(f"  PULADO — originais do caso fora desta máquina: {', '.join(manifesto['faltando'])}")
            ok("o VR Chromatic Aberrations aparece como sem tradução", a["sem_traducao"].get("VR Chromatic Aberrations"), 1)
            ok("o andamento volta a inativo", s.progresso()["ativo"], False)
            ok_proxy("a máscara 1.85 (PNG) é o próprio arquivo final: não fica 'no proxy'",
                     lambda: "ASPECT_RATIO_MASK_1-85-1.png" in a["faltam"], False)
            ok_proxy("…e entra como ela mesma, sem marcador de refazer",
                     lambda: a["casamento"].get("proprio"), 1)

            print("── montar ──")
            try:
                s.preparar_avulso(r["chave"], "outra sequência", sinais={"marcar": True})
                ok("montar outra sequência sem análise é recusado", "passou", "LookupError")
            except LookupError:
                ok("montar outra sequência sem análise é recusado", "LookupError", "LookupError")
            p = s.preparar_avulso(r["chave"], uid, sinais={"marcar": True, "colorir": True})
            ok("a timeline leva o NOME da sequência, não o ObjectUID", p["nome"], "DU exemplos especificos")
            drt = Path(p["drt"])
            ok("o DRT nasce em recebidos/<uuid>.drt (a casca só importa de lá)",
               (drt.parent == dados / "Cache" / "recebidos", R.RE_ID.match(drt.stem) is not None, drt.is_file()),
               (True, True, True))
            ok_proxy("três clipes com plano do Fusion, nenhum recusado",
                     lambda: (len(p["fusion"]), p["fusion_recusadas"]), (3, []))
            ok_proxy("cada plano leva trilha, quadro e arquivo (para a casca achar o clipe)",
                     lambda: sorted((f["trilha"], f["quadro"]) for f in p["fusion"]), [(1, 372), (3, 0), (3, 255)])
            # o Resolve guarda UM marcador de timeline por quadro (medido 2026-10-03): os avisos do
            # caso caem em 6 quadros, então são 6 marcadores, cada um com as notas de todos
            rel = json.loads(drt.with_suffix(".relatorio.json").read_text(encoding="utf-8"))
            quadros = {m["quadro"] for m in rel["marcadores"]}
            ok("um marcador por QUADRO (o Resolve descartava os do mesmo quadro)",
               p["marcadores"], len(quadros))
            ok("as pastas ficam lembradas para este projeto", R.pastas_do_projeto(str(caso)), pastas)
            ok("o relatório ao lado do DRT é de passagem (a limpeza o apaga)",
               R._DE_PASSAGEM.match(drt.stem + ".relatorio.json") is not None, True)
            r2 = s.abrir(str(caso))
            ok("abrir o mesmo projeto de novo traz as pastas", r2["pastas"], pastas)

        print("── sequências com o mesmo nome ──")
        import gzip
        texto = gzip.open(caso, "rb").read().decode("utf-8")
        trocado = texto.replace("\n\t\t<Name>66-1-9</Name>", "\n\t\t<Name>DU exemplos especificos</Name>", 1)
        ok("(a cópia do caso tem um take com o nome da montagem)", trocado != texto, True)
        copia = Path(tmp) / "homonimas.prproj"
        with gzip.open(copia, "wb") as fh:
            fh.write(trocado.encode("utf-8"))
        from prproj.leitura import Leitor
        from prproj.projeto import Projeto
        lt = Leitor(Projeto(str(copia)))
        mont = [x for x in lt.sequencias_de_montagem() if x["nome"] == "DU exemplos especificos"]
        ok("a lista mostra a montagem uma vez (o take homônimo não é de montagem)", len(mont), 1)
        ok("pelo nome, vale a de montagem — não a última indexada",
           len([x for x in lt.ler("DU exemplos especificos")["segmentos"] if not x.get("is_audio")]) > 1, True)
        dois = trocado.replace("\n\t\t<Name>84-3-6</Name>", "\n\t\t<Name>DU exemplos especificos</Name>", 1)
        with gzip.open(copia, "wb") as fh:
            fh.write(dois.encode("utf-8"))
        try:
            Leitor(Projeto(str(copia))).ler("DU exemplos especificos")
            ok("dois takes + a montagem com o mesmo nome: só a montagem é de montagem", "passou", "passou")
        except ValueError as e:
            ok("dois takes + a montagem com o mesmo nome: só a montagem é de montagem", str(e), "passou")

        print("── plano do Fusion que não se monta ──")
        from avb_bin.segmentos import caminho_confiavel
        from tools.prproj_para_drt import analisar as _analisar, montar as _montar
        a = _analisar(str(caso), "DU exemplos especificos", [], confiavel=caminho_confiavel)
        for seg in a["leitura"]["segmentos"]:
            fx = [e for e in seg.get("effects") or [] if e.get("category") == "fusion"]
            if [e["params"]["efeito"] for e in fx] == ["recorte", "basic3d"]:
                outros = [e for e in seg["effects"] if e.get("category") != "fusion"]
                seg["effects"] = outros + fx[::-1]          # Basic 3D ANTES do recorte: recusado
        rel = _montar(str(caso), "DU exemplos especificos", str(Path(tmp) / "x.drt"), [], analise=a)
        recusados = [g for g in rel["fusion"] if not g.get("plano")]
        ok_proxy("o plano invertido é recusado, com o motivo",
                 lambda: [g["erro"] for g in recusados], ["Crop com máscara depois de outro efeito"])
        ok_proxy("…e vira marcador VERMELHO de refazer no clipe (não só 'conferir')",
                 lambda: any(m["cor"] == "Red" and m["nota"].startswith("REFAZER à mão no Fusion") for m in rel["marcadores"]), True)

        print("── ignorar na lista de mídias (2026-10-06) ──")
        # Sem pastas dos originais, todo proxy que existe fica "sem_original" e ganha "REFAZER no original".
        import tools.prproj_para_drt as _T
        sem = [m for m in _T.lista_de_midias(a["casamento"]) if m["estado"] == "sem_original"]
        if sem and COM_PROXIES:
            alvo_ign = sem[0]
            rel_i = _montar(str(caso), "DU exemplos especificos", str(Path(tmp) / "i.drt"), [], analise=a,
                            ignorar={alvo_ign["caminho"]})
            sem_orig = lambda r: [m for m in r["marcadores"] if m.get("tipo") == "Sem o original"  # noqa: E731
                                  and m.get("arquivo") == alvo_ign["nome"]]
            ok("⭐ o arquivo ignorado não ganha o marcador 'REFAZER no original'", sem_orig(rel_i), [])
            ok("…e os outros sem original continuam marcados",
               any(m.get("tipo") == "Sem o original" for m in rel_i["marcadores"]) or len(sem) == 1, True)
            ok("…e sai do 'no proxy' do relatório",
               alvo_ign["nome"] in _T.faltam_sem_ignorados(a["casamento"], {alvo_ign["caminho"]}), False)
        else:
            print("  PULADO (proxies no HD PRODUCAO_B, fora desta máquina) — o marcador do ignorado")

        print("── o TC de início que veio da origem (MZ.ZeroPoint) ──")
        # "Respeitar o TC que veio da origem" (autor, 2026-10-04). O início do R02 é o que o CASO
        # declara (hoje 0); o caso de início ≠ 0 não depende de versão do projeto: uma cópia
        # temporária com o ZeroPoint trocado para 03:00:00:00 (259.200 quadros a 24).
        import gzip as _gz
        import re as _re
        import struct as _struct
        import zipfile as _zip
        from tools.prproj_para_drt import analisar as _an, montar as _mo
        import casos as _ilhas
        esperado = _ilhas.carregar("REAL/R02 PRODUCAO_B EXEMPLOS")["expectativas"]["inicio_quadros"]
        ok("a leitura devolve o início que o caso declara", a["leitura"]["inicio"], esperado)

        def inicio_no_drt(drt_path):
            with _zip.ZipFile(str(drt_path)) as z:
                txt = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
            tlc = _re.search(r"<Sm2MpTimelineClip\b.*?</Sm2MpTimelineClip>", txt, _re.S).group(0)
            ext = _struct.unpack("<dd", bytes.fromhex(_re.search(r"<MediaExtents>([0-9a-f]+)<", tlc).group(1)))[0]
            starts = [int(x) for x in _re.findall(r"<Sm2TiVideoClip\b.*?<Start>(\d+)</Start>", txt, _re.S)]
            return ext, min(starts)
        ok_proxy("…e o DRT começa nele (MediaExtents e o 1º clipe)", lambda: inicio_no_drt(Path(tmp) / "x.drt"),
                 (esperado / 24, esperado))
        with _gz.open(str(caso), "rb") as fh:
            xml = fh.read().decode("utf-8")
        tres_h = str(259200 * 10584000000)
        xml2, trocas = _re.subn(r"<MZ\.ZeroPoint>-?\d+</MZ\.ZeroPoint>", f"<MZ.ZeroPoint>{tres_h}</MZ.ZeroPoint>", xml)
        if not trocas:          # sequência sem a chave: põe na primeira <Properties> dela
            xml2 = xml.replace("<MZ.EditLine>", f"<MZ.ZeroPoint>{tres_h}</MZ.ZeroPoint><MZ.EditLine>")
        copia = Path(tmp) / "zero_tres_horas.prproj"
        with _gz.open(str(copia), "wb") as fh:
            fh.write(xml2.encode("utf-8"))
        a3 = _an(str(copia), "DU exemplos especificos", [], confiavel=caminho_confiavel)
        ok("início ≠ 0 (cópia com 03:00:00:00): a leitura o devolve", a3["leitura"]["inicio"], 259200)
        _mo(str(copia), "DU exemplos especificos", str(Path(tmp) / "tres.drt"), [], analise=a3)
        ok_proxy("…e o DRT começa em 03:00:00:00, não em 01:00:00:00", lambda: inicio_no_drt(Path(tmp) / "tres.drt"),
                 (259200 / 24, 259200))

        print("── reverso sem a duração do arquivo ──")
        import tools.prproj_para_drt as T
        a = _analisar(str(caso), "DU exemplos especificos", [], confiavel=caminho_confiavel)
        alvo = next(seg for seg in a["leitura"]["segmentos"]
                    if seg.get("media_ref") and not seg.get("is_effect") and not seg.get("is_audio"))
        alvo["motion_effect_type"] = "reverse"
        with mock.patch.object(T, "_media_meta", lambda p: (None, None, None)):
            rel = _montar(str(caso), "DU exemplos especificos", str(Path(tmp) / "r.drt"), [], analise=a)
        ok_proxy("reverso que o arquivo não deixa montar vira marcador VERMELHO",
                 lambda: any(m["nota"].startswith("REFAZER o reverso") for m in rel["marcadores"]), True)

        print("── a tranca dos caminhos de dentro do projeto ──")
        from tools.prproj_para_drt import analisar
        tocados = []

        def confiavel(c):
            tocados.append(c)
            return None, "recusado no teste"
        with mock.patch("os.path.exists", side_effect=lambda c: tocados.append(("exists", c)) or False):
            a = analisar(str(caso), "DU exemplos especificos", [], confiavel=confiavel)
        ok("todo caminho de mídia passa pela tranca", len(tocados) > 0 and all(isinstance(x, str) for x in tocados[:5]), True)
        ok("caminho recusado não é tocado no disco (nenhum exists de caminho do projeto)",
           [x for x in tocados if isinstance(x, tuple) and x[1]], [])
        ok("com tudo recusado, nada casa com original", a["resumo"]["no_original"], 0)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
