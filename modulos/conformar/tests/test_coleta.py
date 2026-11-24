"""A lista do insert: as decisões do botão Coletar — sem Media Composer.

Rodar:

    .venv-win/Scripts/python tests/test_coleta.py

Regras combinadas com o autor em 2026-09-24:
- a lista só cresce; X remove um; Limpar zera;
- a MESMA cópia de novo (o Ctrl+C sem seleção mantém a anterior — medido) = "nada novo";
- tudo já na lista = "nada novo";
- cópia que não casa com a sequência = recusada;
- mais de uma trilha = OK | Cancelar; Cancelar não põe nada;
- outra sequência com lista cheia = pergunta antes de trocar.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

from coleta import Coleta  # noqa: E402


def item(track, tc_in, tc_out, n):
    return {"track": track, "timeline_tc_in": tc_in, "timeline_tc_out": tc_out,
            "mob_id": f"urn:m{n}", "clip_name": f"C{n}", "inteiro": True}


SEQ = {"mob_id": "seq-A", "nome": "PRODA_CORTE"}
OUTRA = {"mob_id": "seq-B", "nome": "OUTRO_CORTE"}


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<60} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    c = Coleta()
    a = [item(1, "00:01:00:00", "00:01:05:00", 1)]
    r = c.decidir(SEQ, a, [])
    ok("1ª coleta, uma trilha: entra direto", (r["status"], len(c.itens)), ("adicionado", 1))

    r = c.decidir(SEQ, a, [])
    ok("⭐ a MESMA cópia de novo (Ctrl+C sem seleção) = nada novo", (r["status"], len(c.itens)),
       ("nada_novo", 1))

    b = [item(1, "00:02:00:00", "00:02:03:00", 2)]
    r = c.decidir(SEQ, b, [])
    ok("outra seleção soma", (r["status"], len(c.itens)), ("adicionado", 2))

    r = c.decidir(SEQ, a + b, [])
    ok("tudo já na lista = nada novo", (r["status"], len(c.itens)), ("nada_novo", 2))

    r = c.decidir(SEQ, [], ["V1 01:00:00:00: “X” não está nesta sequência"])
    ok("cópia que não casa com a sequência = recusada", (r["status"], len(c.itens)),
       ("outra_sequencia", 2))
    r = c.decidir(SEQ, [], [])
    ok("cópia vazia = nada selecionado", r["status"], "nada_novo")

    duas = [item(1, "00:03:00:00", "00:03:02:00", 3), item(2, "00:03:00:00", "00:03:02:00", 4)]
    r = c.decidir(SEQ, duas, [])
    ok("⭐ duas trilhas → pede OK | Cancelar", (r["status"], r["trilhas"]), ("confirmar", ["V1", "V2"]))
    ok("…e nada entrou ainda", len(c.itens), 2)
    ok("o estado mostra o pendente", c.estado()["pendente"]["trilhas"], ["V1", "V2"])
    r = c.confirmar(False)
    ok("Cancelar: nada entra", (r["status"], len(c.itens), c.pendente), ("cancelado", 2, None))
    c.decidir(SEQ, duas, [])
    r = c.confirmar(True)
    ok("OK: tudo o que veio entra", (r["status"], len(c.itens)), ("adicionado", 4))
    ok("confirmar sem pendente não faz nada", c.confirmar(True)["status"], "nada_pendente")

    ok("X remove UM item", c.remover([2, "00:03:00:00", "urn:m4"]), True)
    ok("…e só ele", [i["mob_id"] for i in c.itens], ["urn:m1", "urn:m2", "urn:m3"])
    ok("X de item que não existe", c.remover([9, "00:00:00:00", "x"]), False)

    r = c.decidir(OUTRA, [item(1, "00:00:10:00", "00:00:12:00", 9)], [])
    ok("⭐ outra sequência com lista cheia → pergunta antes de trocar",
       (r["status"], len(c.itens)), ("confirmar", 3))
    r = c.confirmar(True)
    ok("trocar: a lista passa a ser da outra sequência",
       (r["status"], c.sequencia["mob_id"], [i["mob_id"] for i in c.itens]),
       ("adicionado", "seq-B", ["urn:m9"]))

    c.limpar()
    ok("Limpar lista zera", (c.itens, c.pendente), ([], None))
    r = c.decidir(OUTRA, [item(1, "00:00:10:00", "00:00:12:00", 9)], [])
    ok("⭐ depois de limpar, a MESMA cópia não volta sozinha", r["status"], "nada_novo")
    ok("…e o texto diz como insistir", "outra vez" in r["texto"], True)
    r = c.decidir(OUTRA, [item(1, "00:00:10:00", "00:00:12:00", 9)], [])
    ok("⭐ apertar de novo em seguida (insistir) põe os mesmos clipes", (r["status"], len(c.itens)),
       ("adicionado", 1))
    r = c.decidir(OUTRA, [item(1, "00:00:10:00", "00:00:12:00", 9)], [])
    ok("já na lista continua recusado, mesmo insistindo", (r["status"], len(c.itens)),
       ("nada_novo", 1))

    print("\n── a bin da coleta chega ABERTA ao CreateSubClip ──")
    # ⛔ Regressão de 2026-09-25: a bin era criada e FECHADA, e o `CreateSubClip` numa bin
    # fechada é recusado ("Bin is not open.", ErrorType 50) — nenhuma coleta funcionou.
    import tempfile
    from unittest import mock

    import coleta as C

    class McDeMentira:
        def __init__(self, projeto):
            self.path, self.ordem = projeto, []

        def projeto(self):
            return {"path": self.path}

        def fechar_bin(self, caminho):
            self.ordem.append("fechar")

        def _chamar(self, nome, **k):
            self.ordem.append({"CreateBin": "criar"}.get(nome, nome))
            if nome == "CreateBin":   # o MC grava a .avb nova
                (Path(self.path) / k["folder_path"] / f"{k['bin_name']}.avb").write_bytes(b"x")

    with tempfile.TemporaryDirectory() as tmp, mock.patch.object(C.time, "sleep", lambda *_: None):
        mc = McDeMentira(tmp)
        caminho = C._bin_da_coleta(mc)
        ok("primeira coleta: a bin é criada e fica aberta", mc.ordem, ["criar"])
        mc.ordem.clear()
        C._zerar_bin(mc, caminho)
        ok("no fim, a bin fica vazia e FECHADA (sem entrada vermelha)", mc.ordem[-1], "fechar")
        mc.ordem.clear()
        C._bin_da_coleta(mc)
        ok("⭐ coleta seguinte: fecha, apaga, recria — e a última palavra é criar (aberta)",
           mc.ordem, ["fechar", "criar"])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
