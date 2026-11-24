"""A sequência do Premiere, lida pelo leitor do Conformar (`tools.prproj_para_drt.analisar` → `leitura`), na forma da
leitura do AAF — para passar pelo MESMO `do_aaf.escrever` e daí pela mesma entrega do MC (etapa 2 da proposta
`docs/plano/2026-11-22-baselight-no-app.md`).

No laboratório BL08 o xmeml do Premiere saiu do PRÓPRIO Premiere (exportado pela ponte); no produto o colorista abre o
`.prproj` sem o Premiere, então o xmeml nasce da leitura. Duas diferenças de unidade:

- `source_start_frames` do leitor do Premiere conta quadros da FONTE (o daily); o `<in>` do xmeml (e o do AAF) conta na
  taxa da TIMELINE desde o início do arquivo ⇒ `in = round(início × fps_timeline / fps_fonte)` (o plano de 29,97 do
  BL08 começa no quadro 359 da fonte = 287 da timeline, o mesmo número que o AAF do MC traz).
- a velocidade: o leitor dá `speed_ratio` como quadros da fonte por quadro da timeline (0,8 para um 29,97 numa timeline
  23,976 a 100 %); a velocidade DE VERDADE é `relative_speed`.

O que o xmeml não leva (velocidade ≠ 100 %, Motion que não é o neutro) sai marcado `nao_traduzido`, como no AAF.
⛔ Clipe DESLIGADO no Premiere fica de fora (PRODC, 25ª rodada); a trilha do vídeo de referência também.
"""
from __future__ import annotations


def _motion_neutro(seg: dict) -> bool:
    for e in seg.get("effects") or []:
        if e.get("name") != "Motion":
            continue
        p = e.get("params") or {}
        if (abs(p.get("scale_x", 1) - 1) > 1e-6 or abs(p.get("scale_y", 1) - 1) > 1e-6 or abs(p.get("pos_x", 0)) > 1e-6
                or abs(p.get("pos_y", 0)) > 1e-6 or abs(p.get("rot_z", 0)) > 1e-6):
            return False
    return True


def como_aaf(leitura: dict) -> dict:
    """A `leitura` do `.prproj` → `{timeline_fps, composition_name, timeline_start_tc/frames, segments}` (a do AAF)."""
    fps = float(leitura["fps"])
    segs = []
    for s in leitura.get("segmentos") or []:
        if s.get("disabled") or s.get("referencia") or s.get("is_never_visible"):
            continue
        x = dict(s)
        if not (s.get("is_audio") or s.get("is_gap") or s.get("is_transition")):
            fonte = float(s.get("source_fps") or fps)
            # o quadro EXATO da fonte, antes de virar a taxa da timeline: o Retime do Baselight (`efeitos.planejar`)
            x["_premiere"] = {"ent": float(s.get("source_start_frames") or 0), "fps": fonte,
                              "vel": float(s.get("speed_ratio") or 1.0)}
            x["source_start_frames"] = round(float(s.get("source_start_frames") or 0) * fps / fonte)
            x["speed_ratio"] = float(s.get("relative_speed") or 1.0)
            x["has_reframe"] = not _motion_neutro(s)
            x["has_motion_effect"] = bool(s.get("speed_curve")) or bool(s.get("speed_keyframes"))
            x["media_ref"] = {k: v for k, v in (s.get("media_ref") or {}).items() if k != "source_duration_frames"}
        segs.append(x)
    inicio = int(leitura.get("inicio") or 0)
    base = round(fps)
    tc = f"{inicio // (base * 3600) % 24:02d}:{inicio // (base * 60) % 60:02d}:{inicio // base % 60:02d}:{inicio % base:02d}"
    return {"timeline_fps": fps, "composition_name": leitura.get("nome") or "Premiere", "timeline_start_tc": tc,
            "timeline_start_frames": inicio, "timeline_drop_frame": False, "segments": segs}
