"""O writer da Carta Aberta — só serialização, sem MC e sem mídia.

Rodar:

    .venv-win/Scripts/python tests/test_carta_aberta.py
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

from carta_aberta.writer import VERSAO_DO_FORMATO, build_carta_aberta  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<56} -> {obtido!r}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    resultado = {
        "composition_name": "MINHA TL", "sequence_mob_id": "urn:x", "fonte": "avb",
        "timeline_fps": 23.976, "timeline_start_tc": "01:00:00:00", "timeline_start_frames": 86400,
        "timeline_drop_frame": False,
        "segments": [
            {"clip_name": "CAM_A", "mob_id": "urn:a", "is_gap": False, "is_transition": False},
            {"clip_name": "(gap)", "mob_id": None, "is_gap": True, "is_transition": False},
            {"clip_name": "CAM_B", "mob_id": "urn:b", "is_gap": False, "is_transition": False},
        ],
        "avisos": [{"texto": "algo", "vezes": 2}],
    }
    matches = [{"segment_index": 0, "matched_path": "D:/a.mov", "rejected": False},
               {"segment_index": 2, "matched_path": "D:/b.mov", "rejected": True}]

    with tempfile.TemporaryDirectory() as pasta:
        saida = Path(pasta) / "sub" / "carta.json"
        resumo = build_carta_aberta(resultado, matches, str(saida), "NOME_240924",
                                    comentario="  corte aprovado pela direção  ")
        doc = json.loads(saida.read_text(encoding="utf-8"))
        ok("versão do formato", doc["carta_aberta"], VERSAO_DO_FORMATO)
        ok("o nome escolhido e a sequência de origem", (doc["nome"], doc["origem"]["sequencia"]),
           ("NOME_240924", "MINHA TL"))
        ok("comentário aparado", doc["comentario"], "corte aprovado pela direção")
        ok("arquivo casado vai no segmento", doc["segmentos"][0]["arquivo"], "D:/a.mov")
        ok("⭐ match REJEITADO não vira arquivo", doc["segmentos"][2]["arquivo"], None)
        ok("resumo conta o que ficou sem arquivo (gap não conta)",
           (doc["resumo"]["com_arquivo"], doc["resumo"]["sem_arquivo"]), (1, 1))
        ok("avisos viajam junto", doc["avisos"], [{"texto": "algo", "vezes": 2}])
        ok("não sobra o temporário", [p.name for p in saida.parent.iterdir()], ["carta.json"])
        ok("o resumo devolvido aponta o arquivo", resumo["output"], str(saida))
        ok("UTF-8 sem escapar acento", "direção" in saida.read_text(encoding="utf-8"), True)

        vazio = build_carta_aberta(resultado, [], str(Path(pasta) / "c2.json"), "X", comentario="   ")
        doc2 = json.loads((Path(pasta) / "c2.json").read_text(encoding="utf-8"))
        ok("comentário só de espaços vira null", doc2["comentario"], None)
        ok("sem matches, ninguém tem arquivo", vazio["com_arquivo"], 0)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
