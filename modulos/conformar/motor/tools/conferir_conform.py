"""Confere um conform quadro a quadro: o que o Resolve mostra × o export de referência do editor.

    python -m tools.conferir_conform PASTA_DOS_QUADROS REFERENCIA.mp4 [--fps 24] [--limiar 0.75]

`PASTA_DOS_QUADROS` tem um `<quadro>.png` (ou `.jpg`, 2 MB em vez de 14) por ponto conferido, exportado pelo Resolve
(`Project.ExportCurrentFrameAsStill`, com a trilha de referência DESLIGADA), onde `<quadro>` é
contado do início da timeline (00:00:00:00 = quadro 0). Para cada um, o mesmo quadro do export.

A comparação é de ESTRUTURA, não de cor: o ARRIRAW sem LUT e o export em Rec.709 nunca batem em
cor. Cada imagem vira 160×90 em cinza, normalizada (média 0, desvio 1), e mede-se a correlação
(1 = idênticas na forma). Para separar "lugar errado" de "tempo errado", mede-se também a melhor
correlação deslocando a imagem até ±8 px (na escala 160×90) — se o deslocamento resolve, é posição.
Grava `conferencia.json` na pasta e imprime os piores.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

import numpy as np
import os as _os
import sys as _sys

# rodando como script solto (`python tools/x.py`): o `motor` no caminho, para achar `media`
_sys.path.insert(0, _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))))
from media import fftools  # noqa: E402 — binários embarcados (versao-instalada-embarca-tudo)

W, H = 160, 90


_BUSCA: dict[str, float | None] = {}


def _taxa_se_a_busca_mente(arquivo: str) -> float | None:
    """A taxa (votada) do arquivo quando o `-ss` NÃO é confiável nele; None quando é.

    ⛔ B053 (banco), MEDIDO 2026-10-28 num V01.mxf MPEG-2 gerenciado do Avid: o cabeçalho diz 11,988, a média 23,976, e
    o `-ss` no instante do quadro N entregou o quadro N/2 (diferença 0,00 com o N/2). Cabeçalho ≠ média = busca suspeita:
    o quadro sai decodificando em ORDEM, pelo índice na taxa votada (`opatom._video_rate`)."""
    if arquivo not in _BUSCA:
        from media import sonda
        from media.opatom import _video_rate
        try:
            st = sonda.primeiro(sonda.ler(arquivo), "video")
        except Exception:  # noqa: BLE001 — sem leitura, fica o -ss de sempre
            st = {}
        r, a = sonda._razao(st.get("r_frame_rate")), sonda._razao(st.get("avg_frame_rate"))
        num, den = _video_rate(st) if st else (None, None)
        _BUSCA[arquivo] = (num / den) if (r and a and abs(r - a) > 1e-3 * a and num and den) else None
    return _BUSCA[arquivo]


def _cinza(caminho: str | None = None, ref: str | None = None, quadro: int | None = None,
           fps: float = 24.0) -> np.ndarray | None:
    filtro = f"scale={W}:{H},format=gray"
    if ref is not None:
        taxa = _taxa_se_a_busca_mente(ref)
        if taxa:
            n = int(round(quadro / fps * taxa))
            cmd = [fftools.ffmpeg(), "-v", "error", "-i", ref, "-frames:v", "1", "-vsync", "0"]
            filtro = f"select=eq(n\\,{n})," + filtro
        else:
            cmd = [fftools.ffmpeg(), "-v", "error", "-ss", f"{quadro / fps:.6f}", "-i", ref, "-frames:v", "1"]
    else:
        cmd = [fftools.ffmpeg(), "-v", "error", "-i", caminho]
    cmd += ["-vf", filtro, "-f", "rawvideo", "-"]
    # o stdin fechado (B020: o ffmpeg lê teclas do stdin) e sem a janela de console a cada quadro no Windows
    out = subprocess.run(cmd, capture_output=True, **fftools.SEM_JANELA).stdout
    if len(out) < W * H:
        return None
    a = np.frombuffer(out[:W * H], dtype=np.uint8).astype(np.float64).reshape(H, W)
    return a


def _norm(a: np.ndarray) -> np.ndarray:
    a = a - a.mean()
    d = a.std()
    return a / d if d > 1e-6 else a


def _corr(a: np.ndarray, b: np.ndarray) -> float:
    return float((_norm(a) * _norm(b)).mean())


#: A borda que a comparação ignora (na escala 160×90): o burn-in da referência.
_M = 8


def _melhor_deslocamento(a: np.ndarray, b: np.ndarray, r: int = 8) -> tuple[float, int, int]:
    best = (-2.0, 0, 0)
    m = r
    h, w = a.shape
    ac = a[m:h - m, m:w - m]
    for dy in range(-r, r + 1):
        for dx in range(-r, r + 1):
            bc = b[m + dy:h - m + dy, m + dx:w - m + dx]
            c = _corr(ac, bc)
            if c > best[0]:
                best = (c, dx, dy)
    return best


#: Abaixo disto, o ponto "não confere". Medido no PRODUCAO_B (2026-10-03): 1.141 de 1.142 pontos
#: acima; o único abaixo (0,988 deslocado) era cena escura com burn-in.
LIMIAR = 0.75
#: Segundos por ponto, medidos no filme do PRODUCAO_B (1.142 pontos em 9,5 min, Resolve 19 e 21):
#: a ESTIMATIVA que o painel mostra antes de começar.
SEGUNDOS_POR_PONTO = 0.5


def comparar_um(imagem: str, referencia: str, quadro_ref: int, fps: float = 24.0,
                limiar: float = LIMIAR, quadro_px: tuple[int, int] = (2880, 1620)) -> dict:
    """Um ponto: o quadro exportado pelo Resolve × o quadro `quadro_ref` do vídeo de referência.
    `{corr}` (e, abaixo do limiar, a melhor correlação deslocando até ±8 px na escala 160×90,
    que separa enquadramento de tempo), `{preto: True}` quando os dois são quase pretos, ou
    `{erro}` quando uma das imagens não se lê."""
    a = _cinza(imagem)
    b = _cinza(ref=referencia, quadro=quadro_ref, fps=fps)
    if a is None or b is None:
        return {"erro": "não leu" if a is None else "a referência não tem esse quadro"}
    # ⭐ SEM AS BORDAS (8 de 160 colunas e 8 de 90 linhas de cada lado): é onde mora o burn-in da
    # referência (TC no canto de cima, nome do clipe no de baixo). Numa cena escura o texto branco
    # vira a coisa mais forte da imagem e derruba a semelhança — 5 falsos "não confere" no PRODUCAO_B
    # (2026-10-04), todos de 0,87 a 0,995 sem as bordas; e 2 quadros pretos que só diferiam no TC.
    a, b = a[_M:H - _M, _M:W - _M], b[_M:H - _M, _M:W - _M]
    if a.std() < 6 and b.std() < 6:               # dois quase pretos: a forma não se mede
        return {"corr": 1.0, "preto": True}
    c = _corr(a, b)
    item = {"corr": round(c, 3)}
    if c < limiar:
        cd, dx, dy = _melhor_deslocamento(a, b, r=4)
        item.update(corr_deslocada=round(cd, 3), dx_px=dx * quadro_px[0] // W,
                    dy_px=dy * quadro_px[1] // H)
    return item


def conferir(pasta: str, referencia: str, fps: float = 24.0, limiar: float = LIMIAR) -> list[dict]:
    res = []
    for nome in sorted(os.listdir(pasta), key=lambda n: (len(n), n)):
        base, ext = os.path.splitext(nome)
        if ext.lower() not in (".png", ".jpg") or not base.isdigit():
            continue
        q = int(base)
        res.append({"quadro": q, **comparar_um(os.path.join(pasta, nome), referencia, q, fps, limiar)})
    with open(os.path.join(pasta, "conferencia.json"), "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=1)
    return res


_IMAGENS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".tga", ".exr", ".dpx"}


def _cobre(s: dict) -> bool:
    """Um plano COBRE o de baixo se é imagem opaca de quadro inteiro: não é título, imagem
    parada (a máscara 1.85 é PNG com alfa), nem foi encolhido ou cortado."""
    if s.get("is_gap") or s.get("is_transition") or s.get("is_effect") or s.get("disabled"):
        return False
    ref = (s.get("media_ref") or {}).get("local_path") or ""
    if os.path.splitext(ref)[1].lower() in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd"}:
        return False
    p = ((s.get("effects") or [{}])[0] or {}).get("params") or {}
    if (p.get("scale_x") or 1.0) < 0.999 or any((p.get("crop_frac") or {}).values()):
        return False
    return True


def pontos_visiveis(segmentos: list[dict], fps: int = 24, margem: int = 1) -> list[dict]:
    """Primeiro e último quadro VISÍVEIS de cada plano de vídeo (a regra do trecho visível):
    o que não está coberto por plano opaco de trilha acima nem dentro de transição. `margem`
    afasta o ponto da borda (o quadro exato do corte é o mais sensível a arredondamento)."""
    def tcq(tc):
        h, m, s_, f = (int(x) for x in tc.split(":"))
        return ((h * 60 + m) * 60 + s_) * fps + f
    # a referência e a trilha de notas (desligadas na conferência) não são planos do filme
    planos = [s for s in segmentos if not (s.get("is_gap") or s.get("is_transition")
                                            or s.get("is_audio") or s.get("disabled")
                                            or s.get("referencia") or s.get("trilha_desligada"))]
    trans = [(tcq(s["timeline_tc_in"]), tcq(s["timeline_tc_in"]) + s["duration_frames"], s["track"])
             for s in segmentos if s.get("is_transition") and not s.get("is_audio")]
    out = []
    for s in planos:
        if s.get("is_effect"):
            continue
        # Imagem parada numa trilha ACIMA de outra (a máscara 1.85, um logo): é sobreposição, não
        # plano do filme — os seus "pontos" eram quadros pretos com a máscara (PRODUCAO_B, 2026-10-04).
        a = tcq(s["timeline_tc_in"])
        b = a + s["duration_frames"]
        ref_s = (s.get("media_ref") or {}).get("local_path") or s.get("clip_name") or ""
        if os.path.splitext(ref_s)[1].lower() in _IMAGENS and any(
                o["track"] < s["track"] and not o.get("is_effect")
                and tcq(o["timeline_tc_in"]) < b and tcq(o["timeline_tc_in"]) + o["duration_frames"] > a
                for o in planos):
            continue
        livres = [(a, b)]
        cobertas = [(tcq(o["timeline_tc_in"]), tcq(o["timeline_tc_in"]) + o["duration_frames"])
                    for o in planos if o["track"] > s["track"] and _cobre(o)]
        cobertas += [(x, y) for x, y, tr in trans if tr == s["track"]]
        for x, y in cobertas:
            novo = []
            for u, v in livres:
                if y <= u or x >= v:
                    novo.append((u, v))
                    continue
                if u < x:
                    novo.append((u, x))
                if y < v:
                    novo.append((y, v))
            livres = novo
        livres = [(u, v) for u, v in livres if v - u > 2 * margem]
        if not livres:
            continue
        nome = (s.get("prproj") or {}).get("plano") or s.get("clip_name")
        out.append({"quadro": livres[0][0] + margem, "ponta": "entrada", "plano": nome,
                    "trilha": s["track"], "arquivo": s.get("clip_name")})
        out.append({"quadro": livres[-1][1] - 1 - margem, "ponta": "saída", "plano": nome,
                    "trilha": s["track"], "arquivo": s.get("clip_name")})
    return out


def _tc(q: int, fps: int = 24, base_h: int = 1) -> str:
    q += base_h * 3600 * fps
    s, f = divmod(q, fps)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("pasta")
    ap.add_argument("referencia")
    ap.add_argument("--fps", type=float, default=24.0)
    ap.add_argument("--limiar", type=float, default=0.75)
    a = ap.parse_args(argv)
    res = conferir(a.pasta, a.referencia, a.fps, a.limiar)
    ruins = sorted((r for r in res if r.get("corr", 1) < a.limiar), key=lambda r: r["corr"])
    print(f"{len(res)} pontos, {len(ruins)} abaixo de {a.limiar}")
    for r in ruins[:40]:
        print(f"  {_tc(r['quadro'])}  corr {r['corr']:.2f}  deslocada {r.get('corr_deslocada')} "
              f"({r.get('dx_px')}, {r.get('dy_px')}) px")
    return 0


if __name__ == "__main__":
    sys.exit(main())
