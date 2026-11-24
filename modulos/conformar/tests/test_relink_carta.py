"""Relink aos ORIGINAIS no Resolve, ao importar (ADR 0020).

Rodar:

    .venv-win/Scripts/python tests/test_relink_carta.py

- O leitor da Carta procura o nome do ARQUIVO ORIGINAL (`Source File`), e cai no nome do master.
- O casamento é o do relink do Avid (`relink.preparar`, rota `carta`): acha por nome, e um
  empate fica AMBÍGUO para a revisão — relink errado é pior que nenhum.
- ⭐ O original decidido VENCE a gerenciada do Avid, e o som lê o canal que o Avid usava.
- Sem originais, o DRT é o de sempre.
- ⛔ Um original fora das pastas que o colorista escolheu não entra.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"),
                str(RAIZ / "tests")]

from carta_aberta.writer import build_carta_aberta  # noqa: E402
from test_carta_ida_e_volta import ESS, leitura_sintetica, mid  # noqa: E402


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

    import relink
    import sessao_receber as R
    from avb_bin import segmentos as S

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        dados, canal = tmp / "dados", tmp / "magic-cor"
        caixa = canal / "para-cor"
        caixa.mkdir(parents=True)
        dados.mkdir()
        # A mídia GERENCIADA do Avid existe nesta máquina (a do master 1): é o que o Importar
        # usaria hoje.
        avid = tmp / "Avid MediaFiles" / "MXF" / "1"
        avid.mkdir(parents=True)
        gerenciados = {}
        for n in (11, 12, 13):
            (avid / f"A001_C002_{n}.mxf").write_bytes(b"x")
            gerenciados[ESS.format(n)] = str(avid / f"A001_C002_{n}.mxf")
        # Os ORIGINAIS da cor: a câmera do master 1, a fita dos masters 3 e 4, e o B001_C011
        # em DOIS lugares (empate → ambíguo).
        orig = tmp / "RODAGEM"
        (orig / "CAM").mkdir(parents=True)
        (orig / "SOM").mkdir()
        (orig / "COPIA").mkdir()
        for p in (orig / "CAM" / "A001_C002.mov", orig / "SOM" / "FITA1.MXF",
                  orig / "CAM" / "B001_C011.mov", orig / "COPIA" / "B001_C011.mov"):
            p.write_bytes(b"x")
        # ⚠️ o B001_C011 da COPIA é OUTRO arquivo com o mesmo nome (outra câmera/take): com o mesmo conteúdo, os dois
        # seriam cópias idênticas e valeriam como um (regra do autor, 2026-11-22) — e o teste quer o empate de verdade
        (orig / "COPIA" / "B001_C011.mov").write_bytes(b"y")

        id_tl = "11111111-1111-4111-8111-111111111111"
        build_carta_aberta(leitura_sintetica(), [], str(caixa / "SINTETICA__11111111.carta.json"),
                           "SINTETICA", None, envio={"id": id_tl, "tipo": "timeline"})

        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados), \
                mock.patch("media.pmr.indice_de",
                           lambda *_a, **_k: SimpleNamespace(por_arquivo=gerenciados)):
            s = R.SessaoReceber()
            s.caixa({"cor": str(canal)})
            carta = s.carta_do_pedido({"id": id_tl})

            print("── 1. o leitor: masters da Carta ──")
            ms = {m.mob_id: m for m in R.masters_da_carta(carta)}
            ok("um master por master da Carta", len(ms), 4)
            ok("⭐ procura o nome do ARQUIVO ORIGINAL (Source File)", ms[mid(3)].nome, "FITA1")
            ok("sem Source File, o nome do master", ms[mid(1)].nome, "A001_C002")
            ok("conta quantas vezes aparece na timeline", ms[mid(1)].segmentos, 3)
            ok("imagem e som do mesmo master = não é 'só som'", ms[mid(1)].e_audio, False)
            ok("duração e taxa para o veto de duração",
               (ms[mid(3)].duracao_frames, ms[mid(3)].edit_rate), (100, 25.0))

            print("\n── 2. o casamento (o do relink do Avid, rota carta) ──")
            t = relink.Trabalho(rota="carta", carta=carta, pastas=[str(orig)])
            relink.preparar(t)
            por = {c.master.mob_id: c for c in t.casamentos}
            ok("a câmera casa pelo nome", Path(por[mid(1)].arquivo or "").name, "A001_C002.mov")
            ok("os dois masters da mesma fita casam com ela",
               {Path(por[mid(3)].arquivo or "").name, Path(por[mid(4)].arquivo or "").name}, {"FITA1.MXF"})
            ok("⭐ dois arquivos iguais = AMBÍGUO, vai para a revisão",
               (por[mid(2)].arquivo, por[mid(2)].ambiguo), (None, True))
            decididos = t.decididos()
            ok("decididos: os três seguros", sorted(decididos), sorted([mid(1), mid(3), mid(4)]))
            t.escolhas[mid(2)] = str(orig / "CAM" / "B001_C011.mov")
            ok("a revisão resolve o ambíguo", len(t.decididos()), 4)

            print("\n── 3. o DRT com os originais ──")
            p = s.preparar(id_tl, t.decididos(), [str(orig)])
            ok("o DRT foi gerado", Path(p["drt"]).is_file(), True)
            ok("⭐ nenhum clipe ficou na gerenciada (o original vence)", p["na_gerenciada"], 0)
            ok("os clipes de mídia estão nos originais", p["nos_originais"], p["clipes"])
            ok("nada offline", p["offline"], 0)
            sem = s.preparar(id_tl)
            ok("sem originais, o Importar é o de hoje (usa a gerenciada)",
               (sem["na_gerenciada"] > 0, sem["nos_originais"]), (True, 0))

            print("\n── 4. o som do original lê o canal do Avid ──")
            leitura = leitura_sintetica()
            original = str(orig / "CAM" / "A001_C002.mov")
            segs, casados, _m = S.montar_midia(leitura, {}, str(tmp), {}, gerenciados,
                                               preferir={mid(1): original})
            canais = sorted(segs[c["segment_index"]].get("canal_arquivo") for c in casados
                            if segs[c["segment_index"]].get("is_audio"))
            ok("⭐ A1 e A2 continuam nos canais 1 e 2 do original", canais, [1, 2])
            ok("…e apontam para o original", {c["matched_path"] for c in casados
                                             if c["segment_index"] in (6, 7)}, {original})
            segs2, casados2, _m = S.montar_midia(leitura, {}, str(tmp), {}, gerenciados)
            ok("sem preferir, a gerenciada (MXF mono, canal 1)",
               sorted(segs2[c["segment_index"]].get("canal_arquivo") for c in casados2
                      if segs2[c["segment_index"]].get("is_audio")), [1, 1])

            print("\n── 5. a trava das pastas ──")
            fora = tmp / "OUTRO"
            fora.mkdir()
            (fora / "X.mov").write_bytes(b"x")
            v = R.originais_validos({"a": original, "b": str(fora / "X.mov"),
                                     "c": str(orig / "CAM" / "NAO_EXISTE.mov"),
                                     "d": "file://host/x.mov"}, [str(orig)])
            ok("⛔ só fica o que está DENTRO das pastas escolhidas e existe", v, {"a": original})
            ok("sem pastas, nenhum original", R.originais_validos({"a": original}, []), {})

            print("\n── 6. o AMA da Carta só conta DENTRO das pastas (autor, 2026-10-19) ──")
            # tirar uma pasta da lista tem de tirar o que foi achado por ela, também pelo caminho que a timeline grava
            ama = fora / "A001_C002.mov"
            ama.write_bytes(b"x")
            with mock.patch.dict(carta.arquivos, {mid(1): str(ama)}):
                sem_raiz = {m.mob_id: m for m in R.masters_da_carta(carta)}
                ok("sem pastas, o AMA que existe vira caminho conhecido",
                   getattr(sem_raiz[mid(1)], "caminho_conhecido", None), str(ama))
                na_raiz = {m.mob_id: m for m in R.masters_da_carta(carta, [str(fora)])}
                ok("com a pasta dele, também", getattr(na_raiz[mid(1)], "caminho_conhecido", None), str(ama))
                fora_raiz = {m.mob_id: m for m in R.masters_da_carta(carta, [str(orig)])}
                ok("⭐ com outra pasta, não: procura pelo nome nela",
                   getattr(fora_raiz[mid(1)], "caminho_conhecido", None), None)
                t2 = relink.Trabalho(rota="carta", carta=carta, pastas=[str(orig)])
                relink.preparar(t2)
                c1 = {c.master.mob_id: c for c in t2.casamentos}[mid(1)]
                ok("…e casa com o da pasta indicada", c1.arquivo, str(orig / "CAM" / "A001_C002.mov"))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
