"""A lista de mídias do Media Composer (organograma "Um painel, três NLEs", 2026-10-12) e a PRÉVIA que a enche.

Rodar:

    .venv-win/Scripts/python tests/test_previa_lista_mc.py      (Mac: .venv/bin/python)

- ⛔ NADA exporta (a rota AAF de reserva saiu, autor 2026-10-13); a prévia (`previa: true`), sem a bin, recusa com
  `sem_previa` — o ExportFile é caminho vetado e caro (26 min de WAVE com preset errado);
- o trabalho preparado diz que é prévia (`/trabalho` → `previa`), e o painel não pula para a revisão ao recarregar;
- `/trabalho/assumir` a transforma no trabalho do relink, sem casar de novo; com a sessão ocupada, recusa;
- ⛔ CORRIGE (2026-10-13): os achatamentos do pedido valem no trabalho NOVO (antes iam para o anterior e o
  `preparar` os voltava ao padrão).
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

from api import rotas  # noqa: E402
from relink import Trabalho  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


class Ctx:
    def __init__(self, servico, corpo=None):
        self.servico, self._corpo, self.query = servico, corpo or {}, ""

    def json(self):
        return self._corpo


class McSemBin:
    """O MC vivo, com projeto, mas a timeline fora de qualquer bin salva."""

    exportou = False

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def esta_vivo(self):
        return True

    def projeto(self, **_):
        return {"path": tempfile.gettempdir()}

    def bin_do_mob(self, _):
        return None


class Sessao:
    """A sessão de verdade troca o `trabalho` ao preparar — é o que o defeito dos achatamentos escondia."""

    def __init__(self):
        self.trabalho = Trabalho()
        self.ocupada = False
        self.preparos = 0

    def preparar(self, *a, **k):
        self.preparos += 1
        self.trabalho = Trabalho(rota=k.get("rota", "aaf"))

    def instantaneo(self):
        return {"previa": self.trabalho.previa, "achatar_subclipes": self.trabalho.achatar_subclipes}


def main() -> int:
    pasta = tempfile.mkdtemp()
    sessao = Sessao()
    mc = McSemBin()
    servico = SimpleNamespace(sessao=sessao, media_composer=lambda: mc)

    import relink
    original = relink.exportar_aaf

    def exportar(*a, **k):
        McSemBin.exportou = True
        raise AssertionError("a prévia não pode exportar")
    relink.exportar_aaf = exportar
    try:
        print("── prévia sem bin: recusa, não exporta ──")
        st, r = rotas.trabalho_preparar(Ctx(servico, {"pastas": [pasta], "sequence_mob_id": "x-1", "previa": True}))
        ok("409", st, 409)
        ok("sem_previa", r.get("sem_previa"), True)
        ok("não exportou", McSemBin.exportou, False)
        ok("não preparou", sessao.preparos, 0)

        print("── relink de verdade sem bin: também recusa (a rota AAF de reserva saiu, autor 2026-10-13) ──")
        st, r = rotas.trabalho_preparar(Ctx(servico, {"pastas": [pasta], "sequence_mob_id": "x-1"}))
        ok("409", st, 409)
        ok("não exportou", McSemBin.exportou, False)
        ok("diz o que fazer", "bin salva" in (r.get("erro") or ""), True)
    finally:
        relink.exportar_aaf = original

    print("── prévia de um AAF: o trabalho novo diz que é prévia e leva os achatamentos ──")
    aaf = Path(pasta) / "t.aaf"
    aaf.write_bytes(b"x")
    st, r = rotas.trabalho_preparar(Ctx(servico, {"pastas": [pasta], "aaf": str(aaf), "previa": True,
                                                  "achatar_subclipes": False, "achatar_group_clips": False}))
    ok("200", st, 200)
    ok("preparou uma vez", sessao.preparos, 1)
    ok("é prévia", sessao.trabalho.previa, True)
    ok("⭐ achatar_subclipes do pedido no trabalho NOVO", sessao.trabalho.achatar_subclipes, False)
    ok("⭐ achatar_group_clips do pedido no trabalho NOVO", sessao.trabalho.achatar_group_clips, False)

    print("── assumir: deixa de ser prévia; ocupada, recusa ──")
    sessao.ocupada = True
    st, _ = rotas.trabalho_assumir(Ctx(servico))
    ok("ocupada → 409", st, 409)
    ok("segue prévia", sessao.trabalho.previa, True)
    sessao.ocupada = False
    st, r = rotas.trabalho_assumir(Ctx(servico))
    ok("200", st, 200)
    ok("não é mais prévia", r.get("previa"), False)
    ok("não casou de novo", sessao.preparos, 1)

    print("── relink de verdade: não é prévia ──")
    st, _ = rotas.trabalho_preparar(Ctx(servico, {"pastas": [pasta], "aaf": str(aaf)}))
    ok("200", st, 200)
    ok("não é prévia", sessao.trabalho.previa, False)
    ok("achatar padrão (ligado)", sessao.trabalho.achatar_subclipes, True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
