"""O motor MONTADO (organograma do instalador, 2026-10-05): as regras que só valem dentro do pacote.

Rodar:

    .venv/bin/python tests/test_motor_montado.py        (Windows: .venv-win/Scripts/python)

Sem montar nada: finge `sys.frozen` e um `sys.executable` numa pasta temporária.
- o ffmpeg/ffprobe vêm de DENTRO da pasta do motor; sem eles lá, nada (nunca o PATH nem o CWD);
- o seletor de pasta moderno roda no PRÓPRIO executável (`--dialogo-win`), não num Python que não existe;
- o `main` atende `--dialogo-win` e `--conferir-pacote` antes de subir qualquer serviço.
O pacote de verdade é conferido por `tools/montar_motor.py` (`--conferir-pacote` no executável montado).
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import escolher  # noqa: E402
from media import fftools  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def main() -> int:
    ext = ".exe" if sys.platform == "win32" else ""
    with tempfile.TemporaryDirectory() as tmp:
        pasta = Path(tmp)
        exe = pasta / f"delapraca-servico{ext}"
        exe.write_bytes(b"")
        ambiente = {k: v for k, v in __import__("os").environ.items()
                    if k not in ("DLPC_FFPROBE", "DLPC_FFMPEG", "ORBITA_FFPROBE", "ORBITA_FFMPEG")}
        with mock.patch.object(sys, "frozen", True, create=True), \
                mock.patch.object(sys, "executable", str(exe)), \
                mock.patch.dict("os.environ", ambiente, clear=True):
            print("ffmpeg e ffprobe do pacote")
            ok("⛔ sem o ffprobe na pasta do motor: nada (o do PATH não vale)", fftools.ffprobe(), None)
            (pasta / f"ffprobe{ext}").write_bytes(b"")
            (pasta / f"ffmpeg{ext}").write_bytes(b"")
            ok("⭐ com ele ao lado do executável: é esse", fftools.ffprobe(), str(pasta / f"ffprobe{ext}"))
            ok("…e o ffmpeg também", fftools.ffmpeg(), str(pasta / f"ffmpeg{ext}"))

            print("o seletor de pasta moderno")
            visto = {}

            def falso_run(cmd, **kw):
                visto["cmd"] = cmd
                return subprocess.CompletedProcess(cmd, 0, stdout="C:\\x\n", stderr="")

            with mock.patch.object(escolher.subprocess, "run", falso_run):
                r = escolher._dialogo_win_moderno("Escolha")
            ok("⭐ montado: o PRÓPRIO executável com --dialogo-win (não um .py)",
               visto["cmd"][:2], [str(exe), "--dialogo-win"])
            ok("…e devolve o que o diálogo escolheu", r, ["C:\\x"])

    print("o main atende as ações de um tiro antes de subir o serviço")
    import main as M

    if sys.platform == "win32":   # o dialogo_win só importa no Windows (`ctypes.oledll`); no Mac é o osascript
        with mock.patch("dialogo_win.main", return_value=7) as dlg:
            ok("--dialogo-win vai para o dialogo_win com o resto dos argumentos",
               (M.main(["--dialogo-win", "--titulo", "X"]), dlg.call_args.args[0]), (7, ["--titulo", "X"]))
    with mock.patch.object(M, "conferir_pacote", return_value=0) as cp:
        ok("--conferir-pacote não sobe serviço", (M.main(["--conferir-pacote"]), cp.called), (0, True))
    with tempfile.TemporaryDirectory() as d:          # B034: existir não é estar
        xsym, vazio, molde = (Path(d) / n for n in ("x.xml", "v.xml", "m.xml"))
        xsym.write_bytes(b"XSym\n0034\n" + b"0" * 32 + b"\n../molde.xml\n")
        vazio.write_bytes(b"")
        molde.write_bytes(b"<molde/>")
        ok("o pacote não aceita atalho XSym nem arquivo vazio como molde",
           [M._arquivo_de_verdade(p) for p in (xsym, vazio, molde)], [False, False, True])

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
