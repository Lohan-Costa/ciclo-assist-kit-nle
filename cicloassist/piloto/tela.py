"""A foto da tela e o JPEG — sem Pillow (o produto não o leva).

⭐ O processo se declara ciente de DPI (por monitor) ao importar este módulo: sem isso, numa
escala de 125 % o Windows devolve retângulos e cliques VIRTUALIZADOS e o clique erra o lugar
calado (banco, `skills/piloto/SKILL.md`). Vale para o processo inteiro — o serviço não tem GUI
própria, então não há o que desalinhar.
"""

from __future__ import annotations

import ctypes
import subprocess
import sys
from dataclasses import dataclass

import numpy as np

from .. import binarios

if sys.platform == "win32":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except OSError:  # já declarado (o processo só aceita uma vez)
        pass
    _u, _g = ctypes.windll.user32, ctypes.windll.gdi32


class SemTela(RuntimeError):
    pass


@dataclass(frozen=True)
class Foto:
    """BGR (altura × largura × 3) e onde o pixel (0, 0) fica na área de trabalho VIRTUAL."""
    img: np.ndarray
    x0: int
    y0: int

    def da_tela(self, x: int, y: int) -> tuple[int, int]:
        """Pixel da foto → coordenada da tela (o que o clique usa)."""
        return self.x0 + x, self.y0 + y

    def da_foto(self, x: int, y: int) -> tuple[int, int]:
        return x - self.x0, y - self.y0

    def recorte(self, ret: tuple[int, int, int, int]) -> "Foto":
        """O pedaço de um retângulo DE TELA (esq, topo, dir, base), cortado aos limites da foto."""
        h, w = self.img.shape[:2]
        e, t = self.da_foto(ret[0], ret[1])
        d, b = self.da_foto(ret[2], ret[3])
        e, t, d, b = max(e, 0), max(t, 0), min(d, w), min(b, h)
        if d <= e or b <= t:
            raise SemTela("o retângulo pedido está fora da tela")
        return Foto(self.img[t:b, e:d], self.x0 + e, self.y0 + t)


def fotografar() -> Foto:
    """A área de trabalho virtual inteira (todos os monitores), como o editor a vê."""
    if sys.platform != "win32":
        raise SemTela("a foto da tela ainda não existe fora do Windows")
    x, y, w, h = (_u.GetSystemMetrics(i) for i in (76, 77, 78, 79))
    dc_t = _u.GetDC(0)
    dc = _g.CreateCompatibleDC(dc_t)
    bmp = _g.CreateCompatibleBitmap(dc_t, w, h)
    try:
        _g.SelectObject(dc, bmp)
        _g.BitBlt(dc, 0, 0, w, h, dc_t, x, y, 0x00CC0020 | 0x40000000)  # SRCCOPY | CAPTUREBLT
        cab = (ctypes.c_uint32 * 10)(40, w, (-h) & 0xFFFFFFFF, 1 | (32 << 16), 0, 0, 0, 0, 0, 0)
        buf = ctypes.create_string_buffer(w * h * 4)
        if not _g.GetDIBits(dc, bmp, 0, h, buf, cab, 0):
            raise SemTela("o Windows não entregou a foto da tela")
    finally:
        _g.DeleteObject(bmp)
        _g.DeleteDC(dc)
        _u.ReleaseDC(0, dc_t)
    img = np.frombuffer(buf.raw, np.uint8).reshape(h, w, 4)[:, :, :3].copy()
    return Foto(img, x, y)


def _monitor(hmon: int) -> tuple[int, int, int, int]:
    class _MI(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_uint32), ("rc", ctypes.c_long * 4), ("work", ctypes.c_long * 4),
                    ("flags", ctypes.c_uint32)]
    m = _MI()
    m.cb = ctypes.sizeof(_MI)
    if not hmon or not _u.GetMonitorInfoW(ctypes.c_void_p(hmon), ctypes.byref(m)):
        raise SemTela("o Windows não disse em que monitor está")
    return tuple(m.rc)  # type: ignore[return-value]


def monitor_da_janela(hwnd: int) -> tuple[int, int, int, int]:
    """O retângulo de TELA (esq, topo, dir, base) do monitor onde a janela mais está.

    ⭐ Com dois monitores a área virtual tem 3840 px (ou mais), e a foto reduzida a `LARGURA`
    do localizador ficava com ~2,8 px reais por px — botão pequeno no limite. Recortar pelo
    monitor do programa volta à condição de um monitor só (MEDIDO, 2026-11-02: área virtual
    (0, −549) 3840×1629, um terço dela preto)."""
    if sys.platform != "win32":
        raise SemTela("monitor só no Windows por enquanto")
    _u.MonitorFromWindow.restype = ctypes.c_void_p
    _u.MonitorFromWindow.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    return _monitor(_u.MonitorFromWindow(ctypes.c_void_p(hwnd), 2))  # MONITOR_DEFAULTTONEAREST


def monitor_do_ponto(x: int, y: int) -> tuple[int, int, int, int]:
    """O monitor de um ponto de TELA — para o que nasce onde se clicou (menu de contexto)."""
    if sys.platform != "win32":
        raise SemTela("monitor só no Windows por enquanto")

    class _P(ctypes.Structure):
        _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
    _u.MonitorFromPoint.restype = ctypes.c_void_p
    _u.MonitorFromPoint.argtypes = [_P, ctypes.c_uint32]
    return _monitor(_u.MonitorFromPoint(_P(x, y), 2))


def monitores() -> list[tuple[int, int, int, int]]:
    """Os retângulos de TELA de todos os monitores."""
    if sys.platform != "win32":
        return []
    achados: list[tuple[int, int, int, int]] = []
    _PROC = ctypes.WINFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ssize_t)

    def cada(h, _dc, _r, _l):
        achados.append(_monitor(h))
        return 1
    _u.EnumDisplayMonitors.argtypes = [ctypes.c_void_p, ctypes.c_void_p, _PROC, ctypes.c_ssize_t]
    _u.EnumDisplayMonitors(None, None, _PROC(cada), 0)
    return achados


#: A janela maximizada pelo Windows passa ~9 px de cada borda do monitor (medido: (−9, −9)).
FOLGA_DA_BORDA = 16


def parte_fora(ret: tuple[int, int, int, int], telas: list[tuple[int, int, int, int]] | None = None,
               folga: int = FOLGA_DA_BORDA) -> int:
    """Quantos px² do retângulo `ret` NÃO estão em monitor nenhum (já descontada a `folga` nas bordas).

    ⭐ Decisão do autor (2026-11-02): janela com parte na faixa sem monitor, ou cortada fora da tela,
    NÃO é arrumada pelo produto — o layout é do editor. A operação para e diz por quê."""
    e, t, d, b = ret[0] + folga, ret[1] + folga, ret[2] - folga, ret[3] - folga
    if d <= e or b <= t:
        return 0
    telas = monitores() if telas is None else telas
    area = (d - e) * (b - t)
    coberta = 0
    # os monitores não se sobrepõem: somar as interseções é exato
    for me, mt, md, mb in telas:
        ie, it, id_, ib = max(e, me), max(t, mt), min(d, md), min(b, mb)
        if id_ > ie and ib > it:
            coberta += (id_ - ie) * (ib - it)
    return max(area - coberta, 0)


def jpeg(img: np.ndarray, largura: int | None = None) -> bytes:
    """JPEG pelo ffmpeg (rawvideo no stdin). `largura` reduz mantendo a proporção."""
    ffmpeg = binarios.achar("ffmpeg")
    if not ffmpeg:
        raise SemTela("ffmpeg não encontrado")
    h, w = img.shape[:2]
    filtro = ["-vf", f"scale={largura}:-2:flags=area"] if largura and largura < w else []
    p = subprocess.run(
        [ffmpeg, "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}", "-i", "-",
         *filtro, "-q:v", "3", "-frames:v", "1", "-f", "image2", "-c:v", "mjpeg", "-"],
        input=np.ascontiguousarray(img).tobytes(), capture_output=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if p.returncode != 0 or not p.stdout:
        raise SemTela(f"ffmpeg não fez o JPEG: {p.stderr[-200:]!r}")
    return p.stdout


def com_cruz(img: np.ndarray, x: int, y: int, raio: int = 14) -> np.ndarray:
    """Uma cruz vermelha de 3 px em (x, y) — para o modelo CONFERIR o ponto, e para o olho."""
    m = img.copy()
    h, w = m.shape[:2]
    m[max(y - 1, 0):min(y + 2, h), max(x - raio, 0):min(x + raio + 1, w)] = (0, 0, 255)
    m[max(y - raio, 0):min(y + raio + 1, h), max(x - 1, 0):min(x + 2, w)] = (0, 0, 255)
    return m
