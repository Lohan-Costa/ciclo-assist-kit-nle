"""O piloto ADAPTATIVO, primeiro elo: o modelo acha um elemento na FOTO da tela — sem clicar.

Pergunta: dá para o Assist achar "onde está o botão X" numa janela que não expõe acessibilidade
(o MC 2024.6 mostra 3 painéis na UI Automation, medido em 2026-11-01), com o `claude -p` da
assinatura olhando a foto, e com que erro em pixels?

Como:
  1. foto da janela pelo GDI (`PrintWindow`, sem Pillow), processo DPI-aware (pixels físicos);
  2. JPEG pelo ffmpeg (stdin rawvideo), reduzida a uma largura conhecida;
  3. `claude -p` com a imagem no stream-json de ENTRADA (sem MCP, sem ferramenta: `--tools ""`);
     resposta JSON {x, y} em pixels DA IMAGEM enviada;
  4. 2ª passada: recorte em resolução nativa em volta do palpite, o modelo refina;
  5. grava a foto com uma cruz em cada ponto achado — o veredito é do OLHO, não do modelo.

Uso:  python spikes/o_localizador_ve_a_tela.py "o menu File" "a timeline" ...
Sai 0 se todos voltaram um ponto dentro da janela (a CONFERÊNCIA é olhar `saida/*.jpg`).
"""

from __future__ import annotations

import base64
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

import numpy as np  # noqa: E402

from cicloassist import janela  # noqa: E402
from cicloassist.motor.claude import _ambiente_do_cli, achar_o_cli  # noqa: E402

ctypes.windll.shcore.SetProcessDpiAwareness(2)
u, g = ctypes.windll.user32, ctypes.windll.gdi32
SAIDA = RAIZ / "spikes" / "saida" / "localizador"
LARGURA = 1366
MODELO = "claude-sonnet-5-5"


def foto(hwnd: int) -> np.ndarray:
    r = wintypes.RECT()
    u.GetWindowRect(hwnd, ctypes.byref(r))
    w, h = r.right - r.left, r.bottom - r.top
    dc_j = u.GetWindowDC(hwnd)
    dc = g.CreateCompatibleDC(dc_j)
    bmp = g.CreateCompatibleBitmap(dc_j, w, h)
    g.SelectObject(dc, bmp)
    u.PrintWindow(hwnd, dc, 2)
    cab = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
    buf = ctypes.create_string_buffer(w * h * 4)
    g.GetDIBits(dc, bmp, 0, h, buf, cab, 0)
    g.DeleteObject(bmp); g.DeleteDC(dc); u.ReleaseDC(hwnd, dc_j)
    return np.frombuffer(buf.raw, np.uint8).reshape(h, w, 4)[:, :, :3].copy()  # BGR


def jpeg(img: np.ndarray, largura: int | None = None) -> bytes:
    h, w = img.shape[:2]
    filtro = ["-vf", f"scale={largura}:-2:flags=area"] if largura else []
    p = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
         "-i", "-", *filtro, "-q:v", "3", "-f", "image2", "-c:v", "mjpeg", "-"],
        input=img.tobytes(), capture_output=True, check=True)
    return p.stdout


def perguntar(jpg: bytes, texto: str) -> tuple[dict, float]:
    msg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(jpg).decode()}},
        {"type": "text", "text": texto}]}}
    t = time.monotonic()
    p = subprocess.run(
        [achar_o_cli(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
         "--verbose", "--model", MODELO, "--tools", "", "--strict-mcp-config", "--restricted",
         "--system-prompt", "Você localiza elementos de interface em capturas de tela. "
                            "Responda SÓ um objeto JSON, sem texto em volta."],
        input=json.dumps(msg) + "\n", capture_output=True, text=True, encoding="utf-8",
        env=_ambiente_do_cli(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=180)
    resultado = ""
    for linha in p.stdout.splitlines():
        try:
            ev = json.loads(linha)
        except ValueError:
            continue
        if ev.get("type") == "result":
            resultado = ev.get("result") or ""
            uso = ev.get("usage") or {}
            print(f"   uso: entrada {uso.get('input_tokens')} · cache lido {uso.get('cache_read_input_tokens')}"
                  f" · cache escrito {uso.get('cache_creation_input_tokens')} · saída {uso.get('output_tokens')}"
                  f" · US$ {ev.get('total_cost_usd')}")
    txt = resultado.strip().strip("`")
    txt = txt[txt.find("{"): txt.rfind("}") + 1]
    if not txt:
        raise RuntimeError(f"sem JSON: {resultado[:300]!r} / stderr {p.stderr[-300:]!r}")
    return json.loads(txt), time.monotonic() - t


def localizar(img: np.ndarray, alvo: str) -> dict:
    h, w = img.shape[:2]
    esc = w / LARGURA
    a, t1 = perguntar(jpeg(img, LARGURA),
        f"A imagem tem {LARGURA} px de largura. Onde está: {alvo}? "
        'Responda {"achou": true|false, "x": <px>, "y": <px>, "o_que_vi": "<curto>"} '
        "com o CENTRO do elemento, em pixels desta imagem.")
    if not a.get("achou"):
        return {"alvo": alvo, "achou": False, "o_que_vi": a.get("o_que_vi"), "s": round(t1, 1)}
    x0, y0 = int(a["x"] * esc), int(a["y"] * esc)
    # 2ª passada: recorte NATIVO 480x270 em volta do palpite
    cx, cy = min(max(x0 - 240, 0), w - 480), min(max(y0 - 135, 0), h - 270)
    b, t2 = perguntar(jpeg(img[cy:cy + 270, cx:cx + 480]),
        f"Recorte de 480x270 px de uma tela. Onde está: {alvo}? "
        'Responda {"achou": true|false, "x": <px>, "y": <px>} com o CENTRO, em pixels deste recorte.')
    x1, y1 = (cx + int(b["x"]), cy + int(b["y"])) if b.get("achou") else (x0, y0)
    return {"alvo": alvo, "achou": True, "palpite": [x0, y0], "refinado": [x1, y1],
            "o_que_vi": a.get("o_que_vi"), "s": round(t1 + t2, 1)}


def marcar(img: np.ndarray, pontos: list[tuple[int, int]]) -> np.ndarray:
    m = img.copy()
    for x, y in pontos:
        m[max(y - 1, 0):y + 2, max(x - 15, 0):x + 16] = (0, 0, 255)
        m[max(y - 15, 0):y + 16, max(x - 1, 0):x + 2] = (0, 0, 255)
    return m


def main() -> int:
    alvos = sys.argv[1:] or ["o menu File da barra de menus", "a área vazia da timeline"]
    hwnd = janela.janela_principal("AvidMediaComposer.exe")
    if not hwnd:
        print("MC não está aberto"); return 2
    img = foto(hwnd)
    SAIDA.mkdir(parents=True, exist_ok=True)
    print(f"foto {img.shape[1]}x{img.shape[0]}")
    achados = []
    for alvo in alvos:
        r = localizar(img, alvo)
        achados.append(r)
        print(json.dumps(r, ensure_ascii=False))
    pts = [tuple(r["refinado"]) for r in achados if r.get("achou")]
    caminho = SAIDA / f"{time.strftime('%H%M%S')}_marcado.jpg"
    caminho.write_bytes(jpeg(marcar(img, pts)))
    print("marcado:", caminho)
    return 0 if all(r.get("achou") for r in achados) else 1


if __name__ == "__main__":
    sys.exit(main())
