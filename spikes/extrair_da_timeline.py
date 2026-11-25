"""Extrair um trecho da timeline do editor — primeiro numa cópia DESCARTÁVEL, sem o MC.

    python spikes/extrair_da_timeline.py                 # só arquivo, cópia no temp
    python spikes/extrair_da_timeline.py --na-bin        # grava a cópia na bin do editor

O pedido (2026-09-13): na `TL EDITADA`, tirar o `07-01-02` da V3 que entra em 01:02:33:11,
colando o que vem depois no `07-03-01` da V1 — extração bruta, como o Extract do Avid com
todas as trilhas: sobram os 16 frames do áudio do `07-01-02` que passavam da imagem.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid import edicao as E  # noqa: E402
from cicloassist.avid.take import fracao_da_taxa  # noqa: E402

BIN = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR\TL EDITADA"
           r"\TL EDITADA.avb")
IN, OUT = "01:02:33:11", "01:02:54:03"
SUFIXO = " - sem 07-01-02"


def frames(tc: str, fps: int) -> int:
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s) * fps + f


def inicio_da_sequencia(seq, fps: int) -> int:
    """⛔ A PRIMEIRA trilha de timecode (a TL EDITADA tem três; a última é 25 fps)."""
    tcs = [t.component for t in seq.tracks if type(t.component).__name__ == "Timecode"]
    return round(tcs[0].start * fps / (tcs[0].fps or fps)) if tcs else 0


def trecho(seq) -> tuple[int, int]:
    fps = int(round(float(fracao_da_taxa(seq.edit_rate))))
    base = inicio_da_sequencia(seq, fps)
    return frames(IN, fps) - base, frames(OUT, fps) - base


def gravar(origem: Path, destino: Path) -> dict:
    """Lê `origem`, acrescenta a cópia editada, confere, grava em `destino` e relê."""
    lado = destino.with_suffix(".avb.novo")
    with avb.open(str(origem)) as f:
        memo = {}
        antes = {str(m.mob_id): E.impressao(m, memo) for m in f.content.mobs}
        seq = next(i.mob for i in f.content.items if i.user_placed
                   and i.mob.mob_type == "CompositionMob" and i.mob.usage is None)
        id_original = str(seq.mob_id)
        a, b = trecho(seq)
        nova = E.copiar_sequencia(f, seq, seq.name + SUFIXO)
        feito = E.extrair(nova, a, b)
        problemas = E.conferir_fidelidade(seq, nova, (a, b), (a, a))
        memo = {}
        problemas += [f"o mob {m.name!r} mudou na bin" for m in f.content.mobs
                      if str(m.mob_id) in antes
                      and E.impressao(m, memo) != antes[str(m.mob_id)]]
        if problemas:
            return {"ok": False, "problemas": problemas, "feito": feito}
        id_novo = str(nova.mob_id)
        f.write(str(lado))
    os.replace(lado, destino)

    # ⭐ Relido do DISCO: a prova vale para o arquivo gravado, não para a memória.
    with avb.open(str(destino)) as f:
        depois = {str(m.mob_id): m for m in f.content.mobs}
        seq, nova = depois[id_original], depois[id_novo]
        problemas = E.conferir_fidelidade(seq, nova, (a, b), (a, a))
        memo = {}
        problemas += [f"o mob {m.name!r} mudou no disco" for mid, m in depois.items()
                      if mid in antes and E.impressao(m, memo) != antes[mid]]
        novos = [m.name for mid, m in depois.items() if mid not in antes]
    return {"ok": not problemas and novos == [nova.name], "problemas": problemas,
            "feito": feito, "id_novo": id_novo, "trecho": (a, b), "novos": novos}


def na_bin() -> int:
    """O gesto do produto na bin do EDITOR: guardar, fechar, gravar com prova, abrir, carregar.

    ⚠️ Com o editor olhando a tela: a API não vê diálogo (ver `fechar_bin_com_monitor.py`).
    """
    import time
    from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer

    seguranca = Path(tempfile.gettempdir()) / f"TL EDITADA - antes da extracao {int(time.time())}.avb"
    eventlog = Path(r"C:\Users\Public\Documents\Avid Media Composer\Avid FatalErrorReports"
                    r"\EVENTLOG.LOG")
    quedas0 = eventlog.read_bytes().count(b"FatalExcpt")
    with MediaComposer() as mc:
        rel = mc.caminho_relativo_da_bin(str(BIN))
        try:
            mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        except Exception as e:      # noqa: BLE001 — fechada já é o normal
            print(f"CloseBin: {str(e).splitlines()[0][:60]}")
        shutil.copy2(BIN, seguranca)
        print(f"cópia de segurança: {seguranca}")
        r = gravar(BIN, BIN)
        print(f"gravado ok={r['ok']} · mobs novos {r.get('novos')}")
        for p in r["problemas"]:
            print("   ⛔", p)
        if not r["ok"]:
            shutil.copy2(seguranca, BIN)
            print("a bin voltou da cópia de segurança")
            return 1
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        h = r["id_novo"].rsplit(":", 1)[-1].replace(".", "").lower()
        api = f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"
        mc._chamar("LoadMobsIntoViewer", mob_ids=[api],
                   view_type=mc._enum("LoadMobsIntoViewer", "view_type", "Record"))
        resp = mc._chamar("GetViewerMobs", _timeout=60)      # a ponte espera os 3 s
        na_record = any(m.mob_id == api and m.view_type == 1 for m in resp.body.mobs)
        print(f"a cópia está na Record: {na_record}")
    time.sleep(3)
    quedas = eventlog.read_bytes().count(b"FatalExcpt") - quedas0
    print(f"quedas no EVENTLOG durante o gesto: {quedas}")
    return 0 if na_record and not quedas else 1


def main() -> int:
    if "--na-bin" in sys.argv:
        return na_bin()
    trabalho = Path(tempfile.gettempdir()) / "TL EDITADA - extracao.avb"
    shutil.copy2(BIN, trabalho)
    r = gravar(trabalho, trabalho)
    print(f"ok={r['ok']} · trecho {r.get('trecho')} · "
          f"tirados {r['feito']['frames_tirados']} frames · mobs novos {r.get('novos')}")
    for m in r["feito"]["mudancas"]:
        print("   ", m)
    for p in r["problemas"]:
        print("   ⛔", p)
    print(f"\ncópia de trabalho: {trabalho}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
