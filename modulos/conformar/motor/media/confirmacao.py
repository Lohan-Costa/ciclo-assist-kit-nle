"""A confirmação pelo DAILY, comum aos dois casadores (Premiere: `prproj/originais`; AAF/MC: `media/matcher`).

⭐⭐ Regras do autor (2026-11-22):
- **Empate só se resolve com confirmação visual**; sem ela, nunca decidimos sozinhos — o plano vai para o editor.
- **Reel e tape name são CRITÉRIO** de casamento (não pista): "metadados bastante usados pelos editores online".

A imagem: semelhança em cor 64×36 do quadro do daily × o de cada candidato nos pontos de 25/50/75 % da duração do daily,
em SEGUNDOS desde o início do arquivo (a ponte pelo original: o daily e o original começam no mesmo instante, qualquer
que seja o TC). Vale o PIOR dos três. Escolhe só se o melhor passa do piso E fica à frente de todos os outros pela margem.
Medido no laboratório BL08, P2 (mesmo nome, TC e duração; outra câmera): certo 1,00, errado 0,89.
⚠️ Limiares iniciais, do laboratório: material real ajusta.
"""
from __future__ import annotations

import subprocess

PISO_IMAGEM = 0.95
MARGEM_IMAGEM = 0.05


def quadro_rgb(caminho: str, t: float) -> bytes | None:
    from media import fftools
    try:
        r = subprocess.run([fftools.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", caminho, "-frames:v", "1",
                            "-vf", "scale=64:36", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                           capture_output=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout if len(r.stdout) == 64 * 36 * 3 else None


def semelhanca(a: bytes, b: bytes) -> float:
    return 1 - sum(abs(x - y) for x, y in zip(a, b)) / len(a) / 255


def confirmar_pela_imagem(daily: str, candidatos: list[str], dur_s: float | None,
                          quadro=quadro_rgb) -> tuple[str | None, dict | None]:
    """(o candidato confirmado pela imagem ou None, as notas {candidato: nota}). `quadro` existe para os testes."""
    if not dur_s:
        return None, None
    pontos = [dur_s * f for f in (0.25, 0.5, 0.75)]
    ref = [quadro(daily, t) for t in pontos]
    if any(q is None for q in ref):
        return None, None
    notas = {}
    for c in candidatos:
        qs = [quadro(c, t) for t in pontos]
        notas[c] = round(min(semelhanca(a, b) for a, b in zip(ref, qs)), 3) if all(qs) else 0.0
    ordem = sorted(notas.items(), key=lambda kv: kv[1], reverse=True)
    (melhor, nota), segunda = ordem[0], (ordem[1][1] if len(ordem) > 1 else 0.0)
    if nota >= PISO_IMAGEM and nota - segunda >= MARGEM_IMAGEM:
        return melhor, notas
    return None, notas


def reel_do_arquivo(caminho: str) -> str | None:
    """O reel / tape name gravado no arquivo: o do mov fica na trilha de TC (`reel_name`); o MXF pode trazer `tape_name`
    no formato. ⛔ O MC 25.12 (Mac, AMA) NÃO leva o `reel_name` do QuickTime para o AAF (laboratório BL08, P4): no lado
    do MC o reel do daily vem do ARQUIVO dele."""
    from media import sonda
    try:
        j = sonda.ler(caminho)
    except subprocess.TimeoutExpired:
        return None
    fmt = (j.get("format") or {}).get("tags") or {}
    return (next((t.get("reel_name") for t in [(x.get("tags") or {}) for x in j.get("streams") or []]
                  if t.get("reel_name")), None)
            or fmt.get("reel_name") or fmt.get("tape_name") or None)
