"""A curva do Titler+ acompanha o tamanho do título (`translate._curvas_no_comprimento`; 2026-10-29).

Rodar:  .venv/bin/python tests/test_titulo_curva_avb.py        (Windows: .venv-win/Scripts/python)

O molde do Titler+ traz uma curva (`ParamClip`) no tamanho do título capturado: 24 quadros, o último ponto em 2304
(24 × 96, `timescale 4`). Num título de outro tamanho a bin abria, mas o Save All / salvamento automático do MC 24.6
dava "Range specified for Dup is outside range of component" (R04: um título de 26 quadros na V7, achado por bissecção;
com a curva reescalada o R04 inteiro salva limpo). Aqui: o TrackEffect do título montado em memória, sem o MC.
"""
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import avb  # noqa: E402
from avb_export import translate as T  # noqa: E402

casos = 0
falhas: list[str] = []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    passou = obtido == esperado
    print(f"  {'✓' if passou else '✗'} {nome}" + ("" if passou else f": {obtido!r} ≠ {esperado!r}"))
    if not passou:
        falhas.append(nome)


def curvas(length):
    T.ER = 24000 / 1001
    tpl = T.capture_templates()
    with avb.file.AVBFile() as f:
        te = T._build_title(f, None, "Come with me.", length, "picture", tpl)
        out = []
        for p in te.property_data.get("param_list") or []:
            ct = p.property_data.get("control_track")
            if ct is not None:
                out.append((ct.length, [cp.offset[0] for cp in ct.control_points]))
        return te.length, out


def main() -> int:
    print("── a curva do Titler+ no tamanho do título ──")
    n, c = curvas(24)
    ok("no tamanho do molde (24): nada muda", (n, c), (24, [(24, [0, 2304])]))
    n, c = curvas(26)
    ok("26 quadros (o título do R04): a curva vai a 26 e o último ponto a 2496", (n, c), (26, [(26, [0, 2496])]))
    n, c = curvas(3)
    ok("3 quadros (as palavras do R04): a curva encolhe junto", (n, c), (3, [(3, [0, 288])]))
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
