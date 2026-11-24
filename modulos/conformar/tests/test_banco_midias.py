r"""O banco de mídias compartilhado — travado por regressão, sem MC e sem mídia real.

O que este teste protege é o que falha em SILÊNCIO, que é o modo de falha deste domínio:

* **a revalidação 1:1** — se ela deixar passar um arquivo trocado, o banco vira "regra"
  em vez de "guia" e o app relinka para a mídia errada sem avisar ninguém;
* **a leitura defensiva** — uma linha meio escrita por outra máquina não pode custar as
  outras dez mil;
* **o merge** — dois editores gravando o mesmo nome, e o carimbo decidindo;
* **caminho como entrada de rede** — uma URL disfarçada de caminho não pode chegar ao
  ffmpeg nem ao MediaInfo;
* **raiz + relativo** — é o que faz a entrada de uma máquina servir à outra.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from media import banco_midias as bm  # noqa: E402


class MasterFalso:
    """O mínimo que o banco lê de um `aaf.masters.Master`."""

    def __init__(self, nome, duracao_frames=None, edit_rate=None, e_audio=False,
                 mob_id=""):
        self.nome = nome
        self.duracao_frames = duracao_frames
        self.edit_rate = edit_rate
        self.e_audio = e_audio
        self.mob_id = mob_id


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo: str, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<50} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        pasta_banco = base / "banco"
        midias = base / "MIDIAS"
        (midias / "01_DIARIAS").mkdir(parents=True)
        arquivo = midias / "01_DIARIAS" / "A001_C004.braw"
        arquivo.write_bytes(b"conteudo de camera")
        raizes = {"V-001": str(midias)}

        print("── raiz + relativo (é o que atravessa máquinas) ─────────────")
        raiz, rel = bm.partir(str(arquivo), raizes)
        ok("acha a raiz declarada", raiz, "V-001")
        ok("relativo com barra normal", rel, "01_DIARIAS/A001_C004.braw")
        ok("volta ao caminho local", bm.juntar(raiz, rel, raizes), str(arquivo))
        # ⚠️ Outra máquina, outra montagem: a MESMA linha tem de resolver.
        ok("⭐ resolve noutra montagem",
           bm.juntar(raiz, rel, {"V-001": r"\\SERVIDOR\midias"}),
           str(Path(r"\\SERVIDOR\midias") / "01_DIARIAS" / "A001_C004.braw"))
        # ⚠️ Vence a raiz mais longa, senão um arquivo cai na raiz errada.
        ok("a raiz mais LONGA vence",
           bm.partir(str(arquivo), {"disco": str(base), "V-001": str(midias)})[0],
           "V-001")
        ok("fora de qualquer raiz não inventa", bm.partir(r"D:\outro\x.mov", raizes),
           ("", ""))
        # ⚠️⚠️ `casefold()` MUDA O COMPRIMENTO: `STRAßE` tem 6 letras e 7 dobrado (`ss`).
        # A primeira versão cortava o caminho original pelo `len()` da base em minúsculas
        # e produzia um relativo picado no lugar errado — em silêncio. Comparar por
        # PARTES é imune: quantas casaram não depende de quantos caracteres saíram.
        ok("⭐ raiz com ß (casefold cresce) não corta errado",
           bm.partir("E:\\STRAßE\\dia 1\\a.braw", {"ALEMA": "E:\\STRAßE"}),
           ("ALEMA", "dia 1/a.braw"))
        ok("⭐ e com İ turco também",
           bm.partir("E:\\İLHA\\x.mov", {"ILHA": "E:\\İLHA"}), ("ILHA", "x.mov"))
        # E a insensibilidade à caixa continua valendo onde ela é real (Windows).
        if os.name == "nt":
            ok("caixa diferente ainda casa",
               bm.partir(str(arquivo).upper(), raizes)[0], "V-001")

        print("\n── anotar e reabrir (o ciclo inteiro) ───────────────────────")
        banco = bm.Banco(pasta_banco, raizes=raizes, autor="MAQ-A/lohan")
        banco.anotar_midia(str(arquivo), {"filename": "A001_C004.braw", "uid": "abc"})
        banco.anotar_casamento("A001_03170334_C004", str(arquivo), metodo="manual")
        ok("gravou as duas linhas", banco.gravar(), 2)

        lido = bm.Banco.abrir(pasta_banco, raizes=raizes)
        ok("reabriu com 1 mídia", len(lido.midias), 1)
        c = (lido.candidatos_de("A001_03170334_C004") or [None])[0]
        ok("acha o casamento pelo nome", bool(c), True)
        # ⭐ O nome NORMALIZADO é a chave: sufixo do Avid e caixa não podem separar.
        ok("⭐ acha com sufixo do Avid e outra caixa",
           len(lido.candidatos_de("a001_03170334_c004.new.01")), 1)
        ok("primeira confirmação conta 1", c.get("vezes"), 1)

        print("\n── revalidação 1:1 (o que separa GUIA de regra) ─────────────")
        ok("arquivo intacto: ok", lido.revalidar(c)[0], "ok")

        # ⚠️ Mesmo TAMANHO, conteúdo trocado: só o mtime denuncia. É o caso real de uma
        # diária reexportada por cima — e o que impede o app de relinkar para o arquivo
        # errado com cara de acerto.
        time.sleep(1.1)                      # mtime tem granularidade de segundo
        arquivo.write_bytes(b"OUTRO conteudo!!")
        ok("⭐ mesmo tamanho, mtime novo: mudou", lido.revalidar(c)[0], "mudou")

        sumido = dict(c, rel="01_DIARIAS/NAO_EXISTE.braw", abs=str(midias / "x.braw"))
        ok("arquivo que sumiu: sumiu", lido.revalidar(sumido)[0], "sumiu")

        # ⚠️ Caminho vindo da rede é ENTRADA NÃO CONFIÁVEL. Uma URL não pode virar
        # argumento de ffmpeg/MediaInfo — o banco de NLEs registra isso como SSRF real.
        url = dict(c, raiz="", rel="", abs="http://10.0.0.5:8080/x.mov")
        ok("⭐ URL disfarçada de caminho é recusada", lido.revalidar(url)[0], "sumiu")
        unc_falso = dict(c, raiz="", rel="", abs="concat:/etc/passwd")
        ok("protocolo do ffmpeg também", lido.revalidar(unc_falso)[0], "sumiu")

        print("\n── merge entre máquinas (o carimbo decide) ──────────────────")
        frag = pasta_banco / "fragmentos"
        outra = {
            "esquema": bm.ESQUEMA, "tipo": "casamento",
            "nome_norm": "a001 03170334 c004", "nome": "A001_03170334_C004",
            "raiz": "V-001", "rel": "02_OUTRA/A001_C004.braw", "abs": "",
            "size": 1, "mtime": 1, "metodo": "manual", "vezes": 1,
            "carimbo": "2099-01-01T00:00:00Z", "por": "MAQ-B/assistente",
        }
        (frag / "MAQ-B-assistente.jsonl").write_text(
            json.dumps(outra, ensure_ascii=False) + "\n", encoding="utf-8")
        depois = bm.Banco.abrir(pasta_banco, raizes=raizes)
        # ⚠️ Arquivo DIFERENTE com o mesmo nome não sobrescreve — convive, e quem
        # desempata é a duração. Sobrescrever aqui era o buraco da primeira versão.
        rels = sorted(x.get("rel") for x in depois.candidatos_de("A001_03170334_C004"))
        ok("⭐ os dois alvos convivem sob o mesmo nome",
           rels, ["01_DIARIAS/A001_C004.braw", "02_OUTRA/A001_C004.braw"])
        ok("leu os dois fragmentos", depois.estatisticas()["fragmentos"], 2)

        print("\n── leitura defensiva (linha meio escrita, lixo, tamanho) ────")
        with open(frag / "MAQ-C.jsonl", "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "esquema": bm.ESQUEMA, "tipo": "midia", "chave": "V-001/bom.braw",
                "raiz": "V-001", "rel": "bom.braw", "abs": "", "size": 1, "mtime": 1,
                "meta": {}, "carimbo": "2030-01-01T00:00:00Z", "por": "MAQ-C",
            }, ensure_ascii=False) + "\n")
            fh.write('{"tipo": "midia", "chave": "quebrada"\n')   # sem fechar
            fh.write("\n")
            fh.write("isto nao e json\n")
            fh.write('{"x": "' + "A" * 70000 + '"}\n')            # linha gigante
        resistente = bm.Banco.abrir(pasta_banco, raizes=raizes)
        ok("⭐ a linha boa sobrevive ao lixo",
           bool(resistente.midia_de("V-001/bom.braw")), True)
        ok("e a quebrada não entrou",
           resistente.midia_de("quebrada") is None, True)

        # ⚠️ Esquema diferente = extrator diferente. Aceitar seria deixar metadado
        # velho sobreviver ao conserto do extrator — a armadilha do probecache.
        (frag / "MAQ-D.jsonl").write_text(json.dumps({
            "esquema": "0", "tipo": "midia", "chave": "V-001/velha.braw",
            "carimbo": "2099-01-01T00:00:00Z"}) + "\n", encoding="utf-8")
        ok("⭐ esquema antigo é ignorado",
           bm.Banco.abrir(pasta_banco, raizes=raizes).midia_de("V-001/velha.braw") is None,
           True)

        print("\n── consolidar (e nunca perder fragmento) ────────────────────")
        antes = sorted(p.name for p in frag.glob("*.jsonl"))
        consolidado = bm.Banco.abrir(pasta_banco, raizes=raizes)
        ok("consolidou", consolidado.consolidar(), True)
        ok("⚠️ nenhum fragmento foi apagado",
           sorted(p.name for p in frag.glob("*.jsonl")), antes)
        ok("mapa.json existe", (pasta_banco / "mapa.json").is_file(), True)
        ok("banco.json existe", (pasta_banco / "banco.json").is_file(), True)
        # Reabrir depois de consolidar não pode duplicar nem perder nada.
        depois_c = bm.Banco.abrir(pasta_banco, raizes=raizes)
        ok("o estado sobrevive ao consolidado",
           (len(depois_c.midias), len(depois_c.casamentos)),
           (len(consolidado.midias), len(consolidado.casamentos)))

        print("\n── ⭐ mesmo NOME, mídias diferentes: quem decide é a duração ──")
        # O caso real: cartão A001 reaproveitado em duas diárias. Mesmo nome de clipe,
        # conteúdos diferentes. O nome sozinho não distingue — e sem a duração o master
        # do episódio 5 herdaria o arquivo do episódio 1, calado.
        colisao = base / "COLISAO"
        (colisao / "dia1").mkdir(parents=True)
        (colisao / "dia30").mkdir(parents=True)
        curto = colisao / "dia1" / "A001_C004.braw"
        longo = colisao / "dia30" / "A001_C004.braw"
        curto.write_bytes(b"dia 1")
        longo.write_bytes(b"dia 30 - outro take")
        raizes_c = {"COL": str(colisao)}

        bc = bm.Banco(base / "banco2", raizes=raizes_c, autor="MAQ-A/lohan")
        # 240 frames a 24 = 10 s · 1200 frames a 24 = 50 s
        m_curto = MasterFalso("A001_C004", duracao_frames=240, edit_rate=24.0)
        m_longo = MasterFalso("A001_C004", duracao_frames=1200, edit_rate=24.0)
        bc.anotar_casamento_de_master(m_curto, str(curto), metodo="manual")
        bc.anotar_casamento_de_master(m_longo, str(longo), metodo="manual")
        ok("os dois casamentos coexistem", len(bc.candidatos_de("A001_C004")), 2)

        situacao, achados = bc.decidir(m_curto)
        ok("⭐⭐ a duração escolhe o certo (curto)", situacao, "acerto")
        ok("e é mesmo o arquivo do dia 1", achados[0].get("rel"), "dia1/A001_C004.braw")
        situacao, achados = bc.decidir(m_longo)
        ok("⭐⭐ e o certo do outro lado (longo)", achados[0].get("rel"),
           "dia30/A001_C004.braw")

        # ⚠️ Duração que não bate com NENHUM: o banco se cala em vez de chutar.
        m_outro = MasterFalso("A001_C004", duracao_frames=9999, edit_rate=24.0)
        ok("⚠️ duração de ninguém: o banco não chuta", bc.decidir(m_outro)[0], "nada")

        # ⚠️ Sem duração (é a rota AAF): o portão fica NEUTRO, e com dois candidatos
        # vivos o banco declara ambíguo — não escolhe um por sorte.
        m_sem_dur = MasterFalso("A001_C004")
        ok("⚠️ sem duração e com colisão: ambíguo, não sorteio",
           bc.decidir(m_sem_dur)[0], "ambiguo")

        # Espécie: um master de áudio não pode herdar entrada gravada para vídeo.
        m_audio = MasterFalso("A001_C004", duracao_frames=240, edit_rate=24.0,
                              e_audio=True)
        ok("⭐ áudio não casa com entrada de vídeo", bc.decidir(m_audio)[0], "nada")

        # E a revalidação continua valendo por cima de tudo.
        longo.unlink()
        ok("candidato cujo arquivo sumiu sai da disputa",
           bc.decidir(m_longo)[0], "nada")
        ok("e o outro segue decidindo sozinho", bc.decidir(m_curto)[0], "acerto")

        print("\n── confiança acumulada ──────────────────────────────────────")
        b2 = bm.Banco.abrir(pasta_banco, raizes=raizes, autor="MAQ-A/lohan")
        arq2 = midias / "01_DIARIAS" / "B002_C001.braw"
        arq2.write_bytes(b"outra camera")
        def vezes_de(banco, nome, rel_esperado=None):
            for x in banco.candidatos_de(nome):
                if rel_esperado is None or x.get("rel") == rel_esperado:
                    return x.get("vezes")
            return None

        b2.anotar_casamento("B002_C001", str(arq2), metodo="nome_exato")
        ok("primeira vez", vezes_de(b2, "B002_C001"), 1)
        b2.anotar_casamento("B002_C001", str(arq2), metodo="nome_exato")
        ok("⭐ reconfirmar o MESMO arquivo soma", vezes_de(b2, "B002_C001"), 2)
        arq3 = midias / "01_DIARIAS" / "B002_C001_v2.braw"
        arq3.write_bytes(b"corrigida")
        b2.anotar_casamento("B002_C001", str(arq3), metodo="manual")
        ok("⚠️ o alvo NOVO entra do zero",
           vezes_de(b2, "B002_C001", "01_DIARIAS/B002_C001_v2.braw"), 1)
        ok("⚠️ e não apaga a confiança do alvo antigo",
           vezes_de(b2, "B002_C001", "01_DIARIAS/B002_C001.braw"), 2)

        print("\n── o banco nunca derruba quem o usa ─────────────────────────")
        impossivel = bm.Banco(Path(base / "nao" / "existe" / "\0ruim"), raizes=raizes)
        impossivel.anotar_casamento("X", str(arquivo))
        ok("gravar em pasta impossível devolve 0, não levanta", impossivel.gravar(), 0)
        ok("consolidar idem", impossivel.consolidar(), False)
        ok("abrir pasta inexistente devolve banco vazio",
           len(bm.Banco.abrir(base / "nem" / "existe").casamentos), 0)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
