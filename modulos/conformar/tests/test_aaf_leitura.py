"""O AAF lido como a bin (`motor/aaf/leitura.py`) — o caminho do "Atualizar com dois AAF".

Rodar:

    .venv-win/Scripts/python tests/test_aaf_leitura.py

## Por que este teste existe

O colorista pode receber AAF de um editor sem o De Lá Pra Cá (organograma de 2026-09-28). O AAF
vira Carta pela MESMA leitura da bin, e o gabarito é a própria bin: o caso
`03 CASOS/ATUALIZAR/U03 ATUALIZAR COM AAF` tem o começo da PRODA exportado pelo Media Composer 25.6
como AAF (v01 e v02) e a bin das duas sequências (`U03 referencia.avb`). Medido em 2026-09-29:

- no AAF o plano aponta para o SUBCLIPE sincronizado, e o master fica um nível abaixo, com o MESMO
  id que tem na bin — sem descer, os ids não batiam em 54 de 57 planos de vídeo;
- o clipe de som COM EFEITO (ganho, EQ) perdia o canal no `parse_aaf` (34 de 304);
- o AAF só traz caminho de arquivo para 2 dos 21 clipes: o resto é mídia gerenciada, achada pelas
  essências do master (e o caminho que vem sai como `/D:/…` do `url_to_local_path`).

Sem a pasta de amostras, o teste diz que pulou e sai 0.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "plugins" / "media-composer" / "servico")]
logging.disable(logging.INFO)

from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
AMOSTRAS = Path(raiz_das_amostras())
CASO = AMOSTRAS / "03 CASOS" / "ATUALIZAR" / "U03 ATUALIZAR COM AAF" / "avid"


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    from aaf.leitura import _local
    ok("file:///D:/x vira D:/x (a 3ª barra não é a raiz no Windows)",
       _local("file:///D%3A/Avid%20MediaFiles/MXF/a.mxf"), "D:/Avid MediaFiles/MXF/a.mxf")
    ok("file:///Volumes/x continua /Volumes/x", _local("file:///Volumes/SSD/a.mov"), "/Volumes/SSD/a.mov")

    referencia = CASO / "U03 referencia.avb"
    if not referencia.is_file():
        print(f"  PULADO — {referencia} não está neste disco")
        print(f"\n{casos - len(falhas)}/{casos} casos")
        return 1 if falhas else 0

    from aaf.leitura import ler_timeline_aaf
    from avb_bin import segmentos as S
    from avb_export.reader import topen

    def chave(s):
        return (s["track"], s["timeline_tc_in"], s["duration_frames"])

    for versao, seq in (("v01", "PRODA_EDT_01"), ("v02", "PRODA_EDT_02")):
        print(f"\n── {versao}: o AAF contra a bin ──")
        with topen(str(referencia)) as f:
            bin_ = S.ler_timeline(f, next(m for m in S.sequencias(f) if m.name == seq))
        aaf = ler_timeline_aaf(str(CASO / f"U03 {versao}.aaf"))
        for audio in (False, True):
            b = {chave(s): s for s in bin_["segments"] if bool(s["is_audio"]) == audio
                 and not s["is_gap"] and not s.get("is_transition")}
            a = {chave(s): s for s in aaf["segments"] if bool(s["is_audio"]) == audio
                 and not s["is_gap"] and not s.get("is_transition")}
            nome = "som" if audio else "imagem"
            ok(f"{nome}: os mesmos planos, nas mesmas posições", sorted(a), sorted(b))
            comuns = set(a) & set(b)
            campos = ("mob_id", "source_start_frames") + (("canal_arquivo",) if audio else ())
            ok(f"⭐ {nome}: o mesmo master, a mesma entrada na fonte" + (" e o mesmo canal" if audio else ""),
               [x for x in comuns if any(a[x].get(c) != b[x].get(c) for c in campos)], [])
        ok("os mesmos masters", sorted(aaf["masters"]), sorted(bin_["masters"]))
        for campo in ("nome", "identidade", "essencias", "duracao_frames", "fps"):
            ok(f"⭐ masters: {campo} igual ao da bin" if campo in ("identidade", "essencias")
               else f"masters: {campo} igual ao da bin",
               [m for m in aaf["masters"] if aaf["masters"][m].get(campo) != bin_["masters"].get(m, {}).get(campo)], [])

    # B082: no subclipe sincronizado a imagem entra no quadro 0 do master da câmera e o som 133–218
    # quadros depois no master do gravador. O som tem de sair do master de SOM, com o in-point DELE —
    # na leitura (Resolve, Premiere) e no achatamento do relink (MC). Com o AAF igual à bin acima,
    # a prova vale para as duas rotas.
    print("\n── B082: o som do subclipe sincronizado sai do master de som ──")
    from avb_bin import denest
    from avb_bin.percurso import e_subclipe, por_mob_id, track_de
    with topen(str(referencia)) as f:
        por = por_mob_id(f)
        seq = next(m for m in S.sequencias(f) if m.name == "PRODA_EDT_01")
        leitor = S._Leitor(f, 24.0)
        leitor.por_id = por
        esperados, lidos = {}, {}
        for i, sc in enumerate(S._source_clips(seq)):
            sub = por.get(str(sc.mob_id))
            if not e_subclipe(sub) or sc.media_kind != "sound":
                continue
            imagem = track_de(sub, 1, "picture")
            som = S._source_clips(S.deref(track_de(sub, sc.track_id, "sound").component))[0]
            cam = S._source_clips(S.deref(imagem.component))[0] if imagem is not None else None
            if cam is None or str(cam.mob_id) == str(som.mob_id) or cam.start_time == som.start_time:
                continue
            esperados[i] = (str(som.mob_id), (som.start_time or 0) + (sc.start_time or 0))
            master, fonte, _, _ = leitor.resolver(sc)
            lidos[i] = (str(master.mob_id), fonte)
        ok("há sons sincronizados com in-point de imagem ≠ som", len(esperados) > 100, True)
        ok("⭐ leitura: master de SOM e o in-point dele",
           [k for k in esperados if lidos[k] != esperados[k]], [])
        denest.achatar(f, seq)
        achatados = {i: (str(sc.mob_id), sc.start_time) for i, sc in enumerate(S._source_clips(seq))}
        ok("⭐ achatamento do relink: master de SOM e o in-point dele",
           [k for k in esperados if achatados.get(k) != esperados[k]], [])

    print("\n── o serviço: abrir, comparar e achar a mídia ──")
    import tempfile
    from unittest import mock

    import sessao_receber as R
    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(R.plataforma, "pasta_dados", lambda: Path(tmp)):
        s = R.SessaoReceber()
        v1, v2 = s.abrir(str(CASO / "U03 v01.aaf")), s.abrir(str(CASO / "U03 v02.aaf"))
        ok("o Escolher… abre o AAF, com o nome da timeline", (v1["tipo"], v2["nome"]),
           ("aaf", "PRODA_EDT_02.Exported.02"))
        r = s.comparar_versoes({"avulso": v1["chave"]}, {"avulso": v2["chave"]})
        bn = s.abrir(str(referencia))
        seqs = {x["nome"]: x["mob_id"] for x in bn["sequencias"]}
        rb = s.comparar_versoes({"avulso": bn["chave"], "mob_id": seqs["PRODA_EDT_01"]},
                                {"avulso": bn["chave"], "mob_id": seqs["PRODA_EDT_02"]})
        ok("⭐ v01 × v02 pelo AAF = pela bin (o mesmo resumo)",
           (r["pct_imagem"], r["contagem"]), (rb["pct_imagem"], rb["contagem"]))
        try:
            s.comparar_versoes({"avulso": v1["chave"]}, {"avulso": bn["chave"], "mob_id": seqs["PRODA_EDT_02"]})
            veio = ""
        except ValueError as e:
            veio = str(e)
        ok("AAF com bin: recusado (o mesmo formato nas duas)", "mesmo formato" in veio, True)
        # ⭐ O título da PRODA ("PRODUCAO-A", Titler+ Legacy na V3): pelo AAF ele sumia calado (autor, Mac,
        # 2026-10-01). A Carta do AAF tem de trazer o MESMO bloco `titulo` que a bin, e o DRT, o título.
        def titulos(v):
            c, _f = s.carta_da_versao(v)
            return [{k: x for k, x in e["params"]["titulo"].items() if k != "avid"}
                    for sg in c.resultado["segments"] for e in sg.get("effects") or []
                    if e.get("category") == "title" and (e.get("params") or {}).get("titulo")]
        ok("⭐ o título da PRODA pelo AAF = pela bin", titulos({"avulso": v1["chave"]}),
           titulos({"avulso": bn["chave"], "mob_id": seqs["PRODA_EDT_01"]}))
        ok("…e é o “PRODUCAO-A”", [t["caixas"][0]["texto"] for t in titulos({"avulso": v1["chave"]})], ["PRODUCAO-A"])
        # ⭐ A mídia SÓ do caso (o `caso.json`): antes o receptor varria todo `Avid MediaFiles`
        # montado e todo volume, e o número mudava com os HDs plugados (regra do autor, 2026-10-04:
        # um projeto não acha mídia de outro). As expectativas são as do caso, com o porquê.
        import casos as ilhas                  # tests/casos.py (o `casos` daqui é o contador)
        caso = ilhas.carregar("ATUALIZAR/U03 ATUALIZAR COM AAF")
        esp = caso["expectativas"]["v02_midia"]
        carta, _familia = s.carta_da_versao({"avulso": v2["chave"]})
        if caso["faltando"]:
            print(f"     PULADO — mídia do caso fora desta máquina: {', '.join(caso['faltando'])}")
        else:
            with ilhas.isolar_midia(caso):
                _segs, casados = s._midia_da_carta(carta, Path(tmp))
            online = sum(1 for c in casados if not c.get("offline"))
            print(f"     (mídia do caso: {online} de {len(casados)} clipes online)")
            ok("⭐ a mídia gerenciada é achada pelas essências do master (SÓ nas pastas do caso)",
               (len(casados), online), (esp["clipes"], esp["online"]))
            ok("…e o que falta é o que o caso declara: " + esp["offline_motivo"][:60] + "…",
               len(casados) - online, esp["offline"])

        # ⭐ O que a casca vai inserir: `fim_fonte` é EXCLUSIVO, o `endFrame` do `AppendToTimeline`
        # (medido 2026-10-01 no Resolve 21: 100→147 dá 47 quadros). Com o `- 1` de antes, o take
        # trocado da U03 entrava com 447 de 448 quadros. A timeline de trabalho é a que o PRÓPRIO
        # Resolve 21 exportou da v01 importada (com correção, cor de clipe e marcador do colorista).
        trabalho = CASO.parent / "resolve" / "U03 v01 trabalho - Resolve 21 Mac.drt"
        if trabalho.is_file():
            import shutil
            import uuid

            from drp import reescrever as RW
            rec = Path(tmp) / "Cache" / "recebidos"   # o cache vai junto dos dados desviados
            rec.mkdir(parents=True, exist_ok=True)
            copia = rec / f"{uuid.uuid4()}.drt"
            shutil.copyfile(trabalho, copia)
            pe = s.preparar_versoes({"avulso": v1["chave"]}, {"avulso": v2["chave"]}, str(copia),
                                    RW.contagem(str(copia)), inicio=86400)
            ok("⭐ o encaixe da v01 com a timeline do Resolve 21", pe["encaixe"]["pct"], 97.7)
            ok("⭐ cada plano novo pede EXATAMENTE a duração do Avid (fim exclusivo)",
               [(x["nome"], x["fim_fonte"] - x["inicio_fonte"], x["dur"]) for x in pe["inserir"]
                if x["fim_fonte"] - x["inicio_fonte"] != x["dur"]], [])
            ok("o take trocado: 2281 → 2729 (448 quadros)",
               [(x["inicio_fonte"], x["fim_fonte"]) for x in pe["inserir"] if x["tipo"] == "V"], [(2281, 2729)])
            ok("⭐ o áudio do take trocado vai até o CORTE (448), não sobre o cross-fade (488)",
               sorted({(x["inicio_fonte"], x["fim_fonte"]) for x in pe["inserir"] if x["tipo"] == "A"}), [(2420, 2868)])
            ok("⭐ os 5 cross-fades do editor no corte do take trocado FICAM (autor, 2026-10-01)",
               sorted(t["trilha"] for t in RW.transicoes(pe["drt"]) if t["start"] == 93070), ["A1", "A2", "A3", "A4", "A5"])
            ok("nenhuma transição perdida em silêncio: os 2 fades do título (V3), que o Importar antigo não trouxe, são avisados",
               len([a for a in pe["avisos"] if "transição" in a]), 2)
            # A timeline de trabalho SEM uma transição que as DUAS versões têm (o cross-fade de 20 da A1 em 87324,
            # tirado à mão = o colorista a tirou): NÃO volta, mas avisa (revisão de código 2026-10-01).
            import re as _re  # noqa: F401
            import zipfile as _zip
            with _zip.ZipFile(copia) as z:   # fechado: no Windows o zip aberto trava a limpeza da pasta
                arqs = {n: z.read(n) for n in z.namelist()}
                nseq = RW._seq(z)
            sq = arqs[nseq].decode("utf-8")
            m = next(m for m in RW._TRANSICAO.finditer(sq) if RW._campo(m.group(3), "Start") == "87324"
                     and m.start() < sq.find("</Sm2TiTrack>", sq.find("<AudioTrackVec>")))
            arqs[nseq] = (sq[:m.start()] + sq[m.end():]).encode("utf-8")
            sem = rec / f"{uuid.uuid4()}.drt"
            with _zip.ZipFile(sem, "w") as zo:
                for n, v in arqs.items():
                    zo.writestr(n, v)
            pe2 = s.preparar_versoes({"avulso": v1["chave"]}, {"avulso": v2["chave"]}, str(sem),
                                     RW.contagem(str(sem)), inicio=86400)
            ok("⭐ a transição que o COLORISTA tirou não volta…", pe2["acoes"].get("transicoes_novas"), None)
            ok("…mas é avisada (nada some calado)",
               any("A1 em 01:00:38:12" in a and "não foi reposta" in a for a in pe2["avisos"]), True)

            # Uma transição NOVA do editor (está na versão nova e não na antiga) é ESCRITA, com o alinhamento da
            # geometria (aqui o plano da esquerda falta nesta máquina: fade de entrada = 1).
            import atualizacao as AT
            import types
            nova_fake = types.SimpleNamespace(resultado={"timeline_fps": 23.976, "segments": [
                {"is_transition": True, "is_audio": True, "track": 1000, "timeline_tc_in": "00:00:38:12",
                 "duration_frames": 20, "cutpoint": 10, "clip_name": "(transition)", "effects": []}]})
            usadas = {"A": [1000], "V": [1]}
            c3, av3 = AT.ajustar_transicoes(nova_fake, str(sem), usadas, 86400)
            with _zip.ZipFile(str(sem)) as z:
                z3 = z.read(RW._seq(z)).decode("utf-8")
            ok("⭐ a transição NOVA do editor é ESCRITA", (c3.get("transicoes_novas"), av3), (1, []))
            ok("…com o alinhamento da geometria (fade de entrada: 1)",
               [RW._campo(m.group(3), "AlignmentType") for m in RW._TRANSICAO.finditer(z3)
                if RW._campo(m.group(3), "Start") == "87324"][:1], ["1"])
            ok("…e a timeline volta a ter a contagem original", RW.contagem(str(sem)), RW.contagem(str(copia)))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
