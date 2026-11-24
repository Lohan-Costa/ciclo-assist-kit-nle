"""Escala do Motion do Premiere: não uniforme e o valor que vale (2026-10-10, caso real R04 PRODUCAO-C).

Rodar:

    .venv/bin/python tests/test_escala_nao_uniforme.py        (Windows: .venv-win/Scripts/python)

Três defeitos do leitor `prproj/leitura.py`, achados ao levar o trailer resgatado para outros NLEs:
1. Escala NÃO uniforme (Uniform Scale desligado) virava a MÉDIA de largura e altura — os proxies 1024×540
   de um UHD (largura × 3,75, altura × 4) sairiam ~6 % deformados no Resolve. Agora a `Geo` leva a
   proporção (`asp`) e o Motion sai com `scale_x` ≠ `scale_y` (e os keyframes `zoom` = largura, `zoom_y`).
2. Com o Uniform Scale desligado, o parâmetro 2 do Motion se chama "Scale Height" (o 23.2 renomeia ao
   salvar): o leitor procurava "Scale" e usava 100.
3. SEM keyframe vale o `StartKeyframe`; o `CurrentValue` pode ficar velho (8 escalas do original de 2023:
   28 e 54,7 no CurrentValue, 50 no StartKeyframe — a API do Premiere e a imagem dão 50).

A parte do projeto real PULA sem o caso no disco.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "motor"), str(RAIZ / "tests"), str(RAIZ / "plugins" / "media-composer" / "servico")]

from prproj import leitura as L  # noqa: E402
import casos as C  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}: veio {obtido!r}, esperava {esperado!r}")


class _Proj:
    """Só o `campo` que o `_valor` usa."""
    def __init__(self, campos):
        self.campos = campos

    def campo(self, _obj, nome):
        return self.campos.get(nome)


def main() -> int:
    print("── o valor de um parâmetro ──")
    sem_kf = _Proj({"StartKeyframe": "-91445760000000000,50.,0,0,0,0,0,0", "CurrentValue": "28"})
    ok("sem keyframe: vale o StartKeyframe (o CurrentValue velho não)", L._valor(sem_kf, None, None), ("50.", False))
    com_kf = _Proj({"StartKeyframe": "-91445760000000000,58.,0,0,0,0,0,0", "CurrentValue": "88",
                    "Keyframes": "2097727632000,88.,0,0,0,0.16,-102.7,0.16;2171889720000,58.,5,0,9.2,1,-51.3,0.33;"})
    ok("com keyframe e sem instante: o CurrentValue (como antes)", L._valor(com_kf, None, None), ("88", True))
    ok("com keyframe num instante: o do keyframe", L._valor(com_kf, None, 2097727632000), ("88.", True))

    print("── a geometria não uniforme ──")
    g = L._geo_do_item({"Scale": "400", "Scale Width": "375", " ": "false"}, (1024, 540), (1920, 1080), False)
    ok("proxy 1024×540 a 375 × 400: altura 4,0 e proporção 0,9375", (round(g.esc, 4), round(g.asp, 4)), (4.0, 0.9375))
    ok("…enche o quadro HD nos dois eixos", (round(1024 * g.esc * g.asp), round(540 * g.esc)), (3840, 2160))
    u = L._geo_do_item({"Scale": "50", "Scale Width": "100", " ": "true"}, (3840, 2160), (1920, 1080), False)
    ok("uniforme: o Scale Width não conta", (u.esc, u.asp), (0.5, 1.0))
    composta = L.Geo(1.0, 0.0, 0.0, 0.0, 2.0).apos(L.Geo(0.5, 0.0, 10.0, 0.0, 0.5))
    ok("nest: as proporções se multiplicam e o deslocamento X segue a largura", (composta.asp, composta.tx), (1.0, 20.0))

    print("── o caso real R04 (trailer resgatado) ──")
    raiz = C.amostras()
    prproj = raiz / "03 CASOS" / "REAL" / "R04 PRODUCAO-C" / "ISOLADO" / "PROJETO" / "PRODC_FINAL_isolado.prproj" if raiz else None
    if not prproj or not prproj.exists():
        print(f"  — PULA: {prproj or 'pasta de testes'} não está nesta máquina")
    else:
        r = L.ler_sequencia(str(prproj), "PRODC_Trailer_v02_RESGATE")
        V = [s for s in r["segmentos"] if not s["is_audio"] and not s["is_gap"]]
        mot = [next(e for e in s["effects"] if e["name"] == "Motion")["params"] for s in V]
        razoes = sorted({round(m["scale_x"] / m["scale_y"], 4) for m in mot if abs(m["scale_x"] - m["scale_y"]) > 1e-6})
        ok("⭐ os 40 planos não uniformes saem com a razão 0,9375 (3,75 ÷ 4)",
           (sum(1 for m in mot if abs(m["scale_x"] - m["scale_y"]) > 1e-6), razoes), (40, [0.9375]))
        ok("⭐ nenhum plano menor que o quadro (o CurrentValue velho dava 0,28)", min(round(m["scale_y"], 3) for m in mot) >= 1.0, True)
        ok("o aviso de \"usada a média\" sumiu", [a["texto"] for a in r["avisos"] if "uniforme" in a["texto"]], [])
        lou = next(m for s, m in zip(V, mot) if s["clip_name"].startswith("LOU_7237"))
        ok("zoom animado não uniforme: largura e altura com keyframes, razão constante",
           sorted({round(x / y, 4) for (_q, x), (_q2, y) in zip(lou["kf"]["zoom"], lou["kf"]["zoom_y"])}), [0.9375])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print("  ✗", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
