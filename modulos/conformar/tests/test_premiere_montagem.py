"""O MODO PREMIERE do Conformar: o ENVIO para o escritor da Carta (plano 2026-11-26, etapa 1).

Rodar:

    .venv/bin/python tests/test_premiere_montagem.py        (Windows: .venv-win/Scripts/python)

Sem Premiere: os segmentos e o casamento sintéticos viram o envio que o núcleo monta pela Carta
(`cicloassist/carta/do_conformar.py`). A montagem antiga pelo ExtendScript (`plano` → `dlpcMontar`) saiu em
2026-11-26; o que ela testava (tempos, velocidade, reverso, offline, transição, título) é da Carta agora e está provado
nas bancadas B34/B32/B30/B33 e n'PRODUCAO-A pelo caminho novo.
- o segmento casado leva o ARQUIVO; o offline (rótulo nos `metas`) leva o `offline` com o rótulo; o rejeitado, nenhum;
- a correção do casamento (`source_offset_correction`) entra na entrada da fonte;
- o TC de início da origem; sem ele, 01:00:00:00 na base nominal;
- os segmentos do leitor seguem inteiros (transição, título, velocidade, efeitos) — quem traduz é a Carta.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

import premiere_montagem as PM  # noqa: E402


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {obtido!r}"[:150])
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    with tempfile.TemporaryDirectory() as tmp:
        a = Path(tmp) / "A.mov"
        a.write_bytes(b"x")
        seg = lambda **k: {"is_gap": False, "is_transition": False, "is_effect": False, "is_audio": False,  # noqa: E731
                           "source_fps": 23.976, "track": 1, **k}
        segs = [seg(timeline_tc_in="00:00:00:00", duration_frames=48, source_start_frames=10, clip_name="A"),
                seg(timeline_tc_in="00:00:02:00", duration_frames=24, source_start_frames=0, clip_name="perdido"),
                seg(timeline_tc_in="00:00:03:00", duration_frames=24, source_start_frames=0, clip_name="rejeitado"),
                seg(timeline_tc_in="00:00:01:20", duration_frames=8, is_transition=True, clip_name="Dissolve"),
                seg(timeline_tc_in="00:00:04:00", duration_frames=24, source_start_frames=5, motion_effect_type="ramp",
                    source_offset_map=[(0.0, 0.0), (12.0, 12.0), (23.0, 34.0)], clip_name="rampa")]
        perdido = str(Path(tmp) / "nao.mov")
        casados = [{"segment_index": 0, "matched_path": str(a), "source_offset_correction": 2},
                   {"segment_index": 1, "matched_path": perdido, "offline": True},
                   {"segment_index": 2, "matched_path": str(a), "rejected": True},
                   {"segment_index": 4, "matched_path": str(a)}]
        metas = {perdido: {"nb": 240, "fps": 23.976, "tc": "04:00:00:00", "reel": "A002", "audio_canais": 2}}
        e = PM.envio_para_a_carta(segs, casados, 23.976, "CORTE", "envio-1", inicio=86400, metas=metas)
        s = e["segmentos"]
        ok("o envio: id, nome, taxa, TC de início", (e["id"], e["nome"], e["fps"], e["tc_inicio_q"]),
           ("envio-1", "CORTE", 23.976, 86400))
        ok("o casado leva o arquivo e a entrada com a correção do casamento (10 + 2)",
           (s[0]["arquivo"], s[0]["source_start_frames"], s[0]["offline"]), (str(a), 12, None))
        ok("o offline leva o rótulo e os dados do original (para a mídia offline no lugar)",
           (s[1]["arquivo"], s[1]["offline"]["rotulo"], s[1]["offline"]["tc"], s[1]["offline"]["nb"]),
           ("", perdido, "04:00:00:00", 240))
        ok("o rejeitado vai sem arquivo e sem offline (a Carta o deixa de fora, dito)",
           (s[2]["arquivo"], s[2]["offline"]), ("", None))
        ok("a transição e a rampa seguem inteiras — quem traduz é a Carta",
           (s[3]["is_transition"], s[4]["motion_effect_type"], s[4]["source_offset_map"][-1]),
           (True, "ramp", (23.0, 34.0)))
        ok("o segmento do leitor não é alterado (cópia)", segs[0]["source_start_frames"], 10)
        e2 = PM.envio_para_a_carta(segs[:1], casados[:1], 25.0, "X", "envio-2")
        ok("sem o TC de início da origem: 01:00:00:00 na base nominal", e2["tc_inicio_q"], 3600 * 25)

    print(f"{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main())
