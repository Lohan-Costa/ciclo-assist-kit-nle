"""Gera os ícones da janela do app (`app/src-tauri/icons/`) a partir do SVG do produto.

    python tools/gerar_icone_do_app.py

O traço do `app/icone.svg` (a claquete que é balão de fala) sobre um quadrado
escuro arredondado, fotografado pelo Chrome headless (o mesmo de `olhar_painel.py`) e
reduzido pelo ffmpeg — sem Pillow, que o produto não usa. ⚠️ O ffmpeg desta máquina LISTA o
SVG em `-codecs` mas não tem o decodificador (medido 2026-10-21: "no decoder found for: svg"). O `.ico` é um contêiner com o PNG dentro (aceito desde o Windows Vista).
"""

from __future__ import annotations

import re
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SVG = RAIZ / "app" / "icone.svg"
SAIDA = RAIZ / "app" / "src-tauri" / "icons"


def svg_do_app() -> str:
    tracos = "".join(re.findall(r"<path[^>]*/>", SVG.read_text(encoding="utf-8")))
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" width="512" height="512" style="display:block">'
            '<rect x="0.5" y="0.5" width="23" height="23" rx="5" fill="#1f2a30"/>'
            '<g transform="translate(2.4 2.4) scale(0.8)" fill="none" stroke="#5fd3c4" '
            'stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">'
            f"{tracos}</g></svg>")


def fotografar(svg: Path, destino: Path) -> None:
    sys.path.insert(0, str(RAIZ / "tools"))
    from olhar_painel import achar_chrome

    chrome = achar_chrome()
    if not chrome:
        raise SystemExit("não achei o Chrome para rasterizar o SVG")
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--hide-scrollbars",
                    "--default-background-color=00000000", "--force-device-scale-factor=1", "--window-size=640,640",
                    f"--screenshot={destino}", svg.as_uri()], check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=60)


def png(origem: Path, lado: int, destino: Path) -> None:
    subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(origem),
                    "-vf", f"crop=512:512:0:0,scale={lado}:{lado}:flags=lanczos", "-frames:v", "1", str(destino)],
                   check=True)


def ico(png_256: bytes, destino: Path) -> None:
    # ICONDIR + uma ICONDIRENTRY (0 = 256 px) apontando para o PNG logo depois.
    cabeca = struct.pack("<HHH", 0, 1, 1)
    entrada = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png_256), 6 + 16)
    destino.write_bytes(cabeca + entrada + png_256)


def main() -> int:
    SAIDA.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        # ⚠️ Num HTML sem margem, e não o `.svg` direto: aberto sozinho, o Chrome o deslocou e
        #   o traço da direita saiu cortado (visto no PNG). E a janela é MAIOR que o ícone, com
    #   recorte depois: na `--window-size` exata o headless corta a borda de baixo e a direita.
        svg = Path(tmp) / "icone.html"
        svg.write_text("<!doctype html><html><body style='margin:0;overflow:hidden;"
                       "background:transparent'>" + svg_do_app() + "</body></html>",
                       encoding="utf-8")
        grande = Path(tmp) / "grande.png"
        fotografar(svg, grande)
        for lado, nome in ((512, "icon.png"), (256, "256x256.png"), (32, "32x32.png")):
            png(grande, lado, SAIDA / nome)
    ico((SAIDA / "256x256.png").read_bytes(), SAIDA / "icon.ico")
    print("ícones em", SAIDA)
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
