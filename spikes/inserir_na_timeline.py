"""Inserir um trecho e abrir um gap na timeline do editor — cópia descartável primeiro.

    python spikes/inserir_na_timeline.py             # só arquivo, cópia no temp
    python spikes/inserir_na_timeline.py --na-bin    # grava na bin do editor e carrega

O pedido (2026-09-13), sobre a `PRODA_CORTE.02.Exported.01 - sem 07-01-02`:
1. inserir 2 s do `07-01-02` (oculto na bin) no meio da timeline, imagem na V2 e o som em
   todas as trilhas dele (A1–A5), empurrando tudo — escolhido 01:02:33:11, de onde ele saiu,
   e o quadro 2600 do take;
2. abrir um gap entre o último take e o `DJI_0312`, o último segmento — 2 s também.

Cada operação é conferida contra a versão ANTERIOR, e só a última cópia fica na bin.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402
from avb.mobid import MobID  # noqa: E402

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid import edicao as E  # noqa: E402
from cicloassist.avid.take import fracao_da_taxa  # noqa: E402

BIN = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR\TL EDITADA"
           r"\TL EDITADA.avb")
BASE = "PRODA_CORTE.02.Exported.01 - sem 07-01-02"
RESULTADO = "PRODA_CORTE.02.Exported.01 - insert e gap"
TAKE, QUADRO_DO_TAKE, DURACAO = "07-01-02", 2600, 48
PONTO = "01:02:33:11"
DRONE = "DJI_0312"


def frames(tc: str, fps: int) -> int:
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s) * fps + f


def inicio_da_sequencia(seq, fps: int) -> int:
    tcs = [t.component for t in seq.tracks if type(t.component).__name__ == "Timecode"]
    return round(tcs[0].start * fps / (tcs[0].fps or fps)) if tcs else 0


def trilha(seq, kind: str, indice: int) -> int:
    return next(n for n, t in enumerate(seq.tracks)
                if getattr(t.component, "media_kind", "") == kind and t.index == indice)


def onde_comeca(seq, n: int, nome: str, por_id) -> int:
    for s, e, c in E._com_posicao(E.segmentos(seq)[n]):
        mob = por_id.get(str(getattr(c, "mob_id", "")))
        if mob is not None and mob.name == nome:
            return s
    raise SystemExit(f"não achei {nome!r} na trilha {n}")


def fonte(f, seq, kind: str, take, track_id: int):
    sc = f.create.SourceClip(seq.edit_rate, kind)
    sc.mob_id = MobID(str(take.mob_id))
    sc.track_id = track_id
    sc.start_time = QUADRO_DO_TAKE
    sc.length = DURACAO
    return sc


def gravar(origem: Path, destino: Path) -> dict:
    lado = destino.with_suffix(".avb.novo")
    with avb.open(str(origem)) as f:
        memo = {}
        antes = {str(m.mob_id): E.impressao(m, memo) for m in f.content.mobs}
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        base = next(m for m in f.content.mobs if m.name == BASE)
        take = next(m for m in f.content.mobs if m.name == TAKE and m.usage == "subclip")
        fps = int(round(float(fracao_da_taxa(base.edit_rate))))
        p = frames(PONTO, fps) - inicio_da_sequencia(base, fps)
        problemas = []

        # 1. inserir
        um = E.copiar_sequencia(f, base, RESULTADO + " (passo 1)")
        novos = {trilha(um, "picture", 2): fonte(f, um, "picture", take, 1)}
        for canal in range(1, 6):
            novos[trilha(um, "sound", canal)] = fonte(f, um, "sound", take, canal)
        feito1 = E.inserir(um, p, DURACAO, novos)
        problemas += [f"inserir: {x}" for x in E.conferir_fidelidade(base, um, (p, p),
                                                                     (p, p + DURACAO))]

        # 2. o gap, contra o resultado do passo 1
        dois = E.copiar_sequencia(f, um, RESULTADO)
        g = onde_comeca(dois, trilha(dois, "picture", 2), DRONE, por_id)
        feito2 = E.inserir(dois, g, DURACAO)
        problemas += [f"gap: {x}" for x in E.conferir_fidelidade(um, dois, (g, g),
                                                                 (g, g + DURACAO))]
        # O passo 1 serviu de régua; na bin fica só o resultado.
        f.content.items.remove(next(i for i in f.content.items if i.mob is um))

        memo = {}
        problemas += [f"o mob {m.name!r} mudou na bin" for m in f.content.mobs
                      if str(m.mob_id) in antes
                      and E.impressao(m, memo) != antes[str(m.mob_id)]]
        info = {"ponto": p, "gap": g, "feito": [feito1, feito2]}
        if problemas:
            return {"ok": False, "problemas": problemas, **info}
        id_novo = str(dois.mob_id)
        # ⭐ As provas acima foram em MEMÓRIA, passo a passo. A impressão do resultado
        #    amarra a memória ao disco: relido, ele tem de ser exatamente o que foi provado.
        provado = E.impressao(dois, {})
        f.write(str(lado))
    os.replace(lado, destino)

    with avb.open(str(destino)) as f:
        depois = {str(m.mob_id): m for m in f.content.mobs}
        memo = {}
        mudaram = [f"o mob {m.name!r} mudou no disco" for mid, m in depois.items()
                   if mid in antes and E.impressao(m, memo) != antes[mid]]
        if E.impressao(depois[id_novo], {}) != provado:
            mudaram.append("o resultado relido do disco não é o que foi provado em memória")
        novos_mobs = [m.name for mid, m in depois.items() if mid not in antes]
    return {"ok": not mudaram and novos_mobs == [RESULTADO], "problemas": mudaram,
            "novos": novos_mobs, "id_novo": id_novo, **info}


def na_bin() -> int:
    from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer

    seguranca = Path(tempfile.gettempdir()) / f"TL EDITADA - antes do insert {int(time.time())}.avb"
    eventlog = Path(r"C:\Users\Public\Documents\Avid Media Composer\Avid FatalErrorReports"
                    r"\EVENTLOG.LOG")
    quedas0 = eventlog.read_bytes().count(b"FatalExcpt")
    with MediaComposer() as mc:
        rel = mc.caminho_relativo_da_bin(str(BIN))
        try:
            mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        except Exception as e:      # noqa: BLE001
            print(f"CloseBin: {str(e).splitlines()[0][:60]}")
        shutil.copy2(BIN, seguranca)
        print(f"cópia de segurança: {seguranca}")
        r = gravar(BIN, BIN)
        mostrar(r)
        if not r["ok"]:
            shutil.copy2(seguranca, BIN)
            print("a bin voltou da cópia de segurança")
            return 1
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        h = r["id_novo"].rsplit(":", 1)[-1].replace(".", "").lower()
        api = f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"
        mc._chamar("LoadMobsIntoViewer", mob_ids=[api],
                   view_type=mc._enum("LoadMobsIntoViewer", "view_type", "Record"))
        resp = mc._chamar("GetViewerMobs", _timeout=60)
        na_record = any(m.mob_id == api and m.view_type == 1 for m in resp.body.mobs)
        print(f"o resultado está na Record: {na_record}")
    time.sleep(3)
    quedas = eventlog.read_bytes().count(b"FatalExcpt") - quedas0
    print(f"quedas no EVENTLOG durante o gesto: {quedas}")
    return 0 if na_record and not quedas else 1


def mostrar(r: dict) -> None:
    print(f"ok={r['ok']} · ponto {r['ponto']} · gap em {r['gap']} · mobs novos {r.get('novos')}")
    for feito in r["feito"]:
        for m in feito["mudancas"]:
            print("   ", m)
    for p in r["problemas"]:
        print("   ⛔", p)


def main() -> int:
    if "--na-bin" in sys.argv:
        return na_bin()
    trabalho = Path(tempfile.gettempdir()) / "TL EDITADA - insert.avb"
    shutil.copy2(BIN, trabalho)
    r = gravar(trabalho, trabalho)
    mostrar(r)
    print(f"\ncópia de trabalho: {trabalho}")
    return 0 if r["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
