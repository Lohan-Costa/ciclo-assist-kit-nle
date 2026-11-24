"""Relink manual: a palavra do editor vence, só o impossível é recusado (autor, 2026-10-13).

Rodar:

    .venv/bin/python tests/test_relink_manual.py        (Windows: .venv-win/Scripts/python)

As regras (`relink_manual.validar`) e a sondagem de arquivos gerados aqui (ffmpeg), pequenos. Também o "Ignorar": o
master ignorado sai dos decididos, e a escolha manual vence o casamento automático.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import relink_manual as RM  # noqa: E402
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


VIDEO = {"usa_imagem": True, "e_audio": False, "canais_som": 0, "uso_frames": 2878, "edit_rate": 23.976}  # 2:00
SOM = {"usa_imagem": False, "e_audio": True, "canais_som": 3, "uso_frames": 1439, "edit_rate": 23.976}     # 1:00


def regras():
    print("regras")
    sonda_video = {"tem_video": True, "tem_audio": True, "canais": 2, "duracao_s": 150.0}
    ok("vídeo que cobre o trecho: aceito", RM.validar(VIDEO, sonda_video)[0], True)
    ok("vídeo de 1:00 para um uso de 2:00: recusado", RM.validar(VIDEO, dict(sonda_video, duracao_s=60.0))[0], False)
    ok("o motivo diz os dois tempos", "2:00" in RM.validar(VIDEO, dict(sonda_video, duracao_s=60.0))[1]
       and "1:00" in RM.validar(VIDEO, dict(sonda_video, duracao_s=60.0))[1], True)
    ok("1 frame a menos (guarda do Avid): aceito", RM.validar(VIDEO, dict(sonda_video, duracao_s=2877 / 23.976))[0], True)
    ok("imagem na timeline, arquivo só de som: recusado",
       RM.validar(VIDEO, {"tem_video": False, "tem_audio": True, "canais": 2, "duracao_s": 300.0})[0], False)
    ok("som na timeline, arquivo sem áudio: recusado",
       RM.validar(SOM, {"tem_video": True, "tem_audio": False, "canais": 0, "duracao_s": 300.0})[0], False)
    ok("usa o canal 3, arquivo estéreo: recusado",
       RM.validar(SOM, {"tem_video": False, "tem_audio": True, "canais": 2, "duracao_s": 300.0})[0], False)
    ok("usa o canal 3, arquivo de 6 canais: aceito",
       RM.validar(SOM, {"tem_video": False, "tem_audio": True, "canais": 6, "duracao_s": 300.0})[0], True)
    ok("câmera com som usado na timeline, conversão sem áudio: recusado",
       RM.validar(dict(VIDEO, canais_som=2), {"tem_video": True, "tem_audio": False, "canais": 0,
                                               "duracao_s": 300.0})[0], False)
    ok("trecho desconhecido (subclipe do AAF): não recusa por duração",
       RM.validar(dict(VIDEO, uso_frames=None), dict(sonda_video, duracao_s=1.0))[0], True)
    ok("canais desconhecidos (BRAW): não recusa por canal",
       RM.validar(dict(VIDEO, canais_som=4), {"tem_video": True, "tem_audio": None, "canais": None,
                                               "duracao_s": 300.0})[0], True)
    ok("nada medido: aceita e avisa", RM.validar(VIDEO, {"tem_video": None, "tem_audio": None, "canais": None,
                                                         "duracao_s": None}),
       (True, "não consegui medir o arquivo: se o Media Composer recusar, ele aparece em “Ficaram de fora”"))


def sondagem():
    print("sondagem (arquivos gerados)")
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_manual_"))
    wav = tmp / "som_3canais.wav"
    mov = tmp / "imagem.mov"
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "sine=f=440:d=3",
                    "-ac", "3", "-ar", "48000", str(wav)], check=True, **fftools.SEM_JANELA)
    subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", "testsrc=s=160x90:r=24:d=2",
                    "-c:v", "mpeg4", str(mov)], check=True, **fftools.SEM_JANELA)
    s = RM.sondar(str(wav))
    ok("wav: sem vídeo, com áudio, 3 canais", (s["tem_video"], s["tem_audio"], s["canais"]), (False, True, 3))
    ok("wav: 3 s", round(s["duracao_s"] or 0), 3)
    s = RM.sondar(str(mov))
    ok("mov: vídeo, sem áudio", (s["tem_video"], s["tem_audio"]), (True, False))
    ok("mov: 2 s", round(s["duracao_s"] or 0), 2)
    ok("é mídia (.mov)", RM.e_midia(str(mov)), True)
    ok("não é mídia (.txt)", RM.e_midia(str(tmp / "nota.txt")), False)


def ignorar_e_escolher():
    print("ignorar e escolher")
    from relink import Trabalho

    class C:      # o mínimo de um casamento
        def __init__(self, mob_id, arquivo):
            self.master = type("M", (), {"mob_id": mob_id})()
            self.arquivo, self.resolvido = arquivo, bool(arquivo)

    t = Trabalho()
    t.casamentos = [C("a", "A.mov"), C("b", "B.mov"), C("c", "")]
    ok("decididos sem nada marcado", sorted(t.decididos()), ["a", "b"])
    t.ignorados.add("b")
    ok("o ignorado sai dos decididos", sorted(t.decididos()), ["a"])
    t.escolhas["c"] = "C_manual.mov"
    t.escolhas["a"] = "A_outro.mov"
    ok("a escolha manual entra e vence o casamento", t.decididos(), {"a": "A_outro.mov", "c": "C_manual.mov"})


def rotas_novas():
    print("rotas: /trabalho/ignorar e /trabalho/manual")
    from types import SimpleNamespace

    from api import rotas
    from relink import Trabalho

    class Ctx:
        def __init__(self, servico, corpo):
            self.servico, self._corpo, self.query = servico, corpo, ""

        def json(self):
            return self._corpo

    tmp = Path(tempfile.mkdtemp(prefix="dlpc_rotas_"))
    curto = tmp / "curto.wav"
    longo = tmp / "longo.wav"
    for arq, d in ((curto, 1), (longo, 4)):
        subprocess.run([fftools.ffmpeg(), "-v", "error", "-y", "-f", "lavfi", "-i", f"sine=f=440:d={d}",
                        "-ac", "2", "-ar", "48000", str(arq)], check=True, **fftools.SEM_JANELA)
    master = {"mob_id": "m1", "nome": "SOM_01", "usa_imagem": False, "e_audio": True, "canais_som": 2,
              "uso_frames": 72, "edit_rate": 24.0}                                     # usa 3 s
    sessao = SimpleNamespace(trabalho=Trabalho(), ocupada=False, masters=lambda: [master])
    servico = SimpleNamespace(sessao=sessao)

    st, r = rotas.trabalho_ignorar(Ctx(servico, {"mob_ids": ["m1"]}))
    ok("ignorar: 200", st, 200)
    ok("ignorar: entra nos ignorados", sessao.trabalho.ignorados, {"m1"})
    st, _ = rotas.trabalho_ignorar(Ctx(servico, {"mob_ids": ["m1"], "ignorar": False}))
    ok("não ignorar: sai", sessao.trabalho.ignorados, set())
    st, r = rotas.trabalho_manual(Ctx(servico, {"mob_id": "m1", "arquivo": str(curto)}))
    ok("arquivo de 1 s para um uso de 3 s: 422", st, 422)
    ok("o motivo vem em `recusa`", "o arquivo tem 0:01" in (r.get("recusa") or ""), True)
    ok("a recusa não grava escolha", sessao.trabalho.escolhas, {})
    sessao.trabalho.ignorados.add("m1")
    st, r = rotas.trabalho_manual(Ctx(servico, {"mob_id": "m1", "arquivo": str(longo)}))
    ok("arquivo de 4 s: 200", st, 200)
    ok("a escolha é gravada", Path(sessao.trabalho.escolhas.get("m1") or "").resolve(), longo.resolve())
    ok("escolher desfaz o ignorar", sessao.trabalho.ignorados, set())
    st, _ = rotas.trabalho_manual(Ctx(servico, {"mob_id": "m1", "arquivo": ""}))
    ok("arquivo vazio desfaz a escolha", sessao.trabalho.escolhas, {})
    (tmp / "nota.txt").write_text("x")
    st, r = rotas.trabalho_manual(Ctx(servico, {"mob_id": "m1", "arquivo": str(tmp / "nota.txt")}))
    ok("arquivo que não é mídia: 422", st, 422)
    sessao.ocupada = True
    st, _ = rotas.trabalho_manual(Ctx(servico, {"mob_id": "m1", "arquivo": str(longo)}))
    ok("sessão ocupada: 409", st, 409)


def titulo_do_dialogo():
    print("diálogo: título com aspas curvas (Windows)")
    if sys.platform != "win32":
        print("  (só no Windows)")
        return
    import escolher

    t = escolher._escapar_ps("Relink manual: o arquivo para “DJI_0317” $x `y` \"z\"")
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", f'[Console]::Out.WriteLine("{t}")'],
                       capture_output=True, encoding="utf-8", errors="replace", creationflags=0x08000000)
    ok("o PowerShell aceita o título (sem UnexpectedToken)", (r.returncode, "UnexpectedToken" in r.stderr), (0, False))
    ok("o $ e a crase chegam literais", "$x" in r.stdout and "`y`" in r.stdout, True)


def main() -> int:
    titulo_do_dialogo()
    regras()
    sondagem()
    ignorar_e_escolher()
    rotas_novas()
    print(f"\n{casos - len(falhas)}/{casos} casos")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())
