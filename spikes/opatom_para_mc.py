"""⛔ SUPERADO por `cicloassist/avid/importar_opatom.py` (2026-11-01): este spike fecha a bin 0,1 s depois do
`ImportFile` (assíncrono) — na 1ª prova do produto isso gravou a bin VAZIA e derrubou o MC. Use a ferramenta.

F3 (ensaio 6a): OP-Atom feito FORA do MC entra ONLINE numa bin — pasta numérica + AAF de masters + ImportFile.

Banco (`plugins/avid-panel-sdk/windows.md`, MC 2024.6, 2026-10-31): os MXF numa pasta de `Avid MediaFiles\\MXF` só de
dígitos (o MC indexa ao ganhar o foco), um AAF com os masters (`pyaaf2 link_external_mxf`: o MasterMob ganha o
material UMID do MXF; os arquivos V/A do mesmo clipe se juntam) e `ImportFile(import_settings_name="Untitled",
destination_bin=<.avb absoluto>)`. ⭐ O nome do master vem do AAF que NÓS escrevemos: `--nome` troca o do pacote MXF
(o Resolve 19.1.4 pela API, sem o preset aplicado, grava o quadro do TC: "00090250").

Uso:  python spikes/opatom_para_mc.py <mxf> [<mxf> ...] --bin "CICLO ENSAIO 25 CAM" [--nome B06_CAM_MOV-PRORES]
      (MC aberto no projeto; os MXF JÁ na pasta numérica)
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
import time

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, r"D:\PROGRAMAS COM CLAUDE\piloto")


def nao_indexados(mxfs: list[str]) -> list[str]:
    """Os MXF que o MC ainda NÃO indexou: mais novos que o `msmMMOB.mdb` da pasta (ou pasta sem `.mdb`).

    ⛔⛔ MEDIDO em 2026-10-31 (MC 2024.6, B06): MXF copiado para uma pasta JÁ indexada não muda a data da PASTA, e o MC
    não a reescaneia. O `ImportFile` do AAF não acha o arquivo e o mob de arquivo nasce com o descritor do AAF:
    `data_offset = 0`, `frame_index_offset = 0`, locator sem volume. Enquanto a mídia está offline nada acontece;
    quando o MC a acha, ele confia nesses zeros e cai (`CompressionManager.c` line 11276, CORE_CONSISTENCY_CHECK_FAILURE).
    """
    ruins = []
    for m in mxfs:
        mdb = os.path.join(os.path.dirname(os.path.abspath(m)), "msmMMOB.mdb")
        if not os.path.exists(mdb) or os.path.getmtime(m) > os.path.getmtime(mdb):
            ruins.append(m)
    return ruins


def mobs_sem_offset(bin_avb: str, material_umids: set[str]) -> list[str]:
    """Depois do import: os mobs de arquivo de IMAGEM (dos nossos masters) com `data_offset = 0` — o que derruba o MC."""
    import avb
    ruins = []
    with avb.open(bin_avb) as f:
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        for m in f.content.mobs:
            if str(m.mob_id) not in material_umids:
                continue
            for t in m.property_data.get("tracks") or []:
                c = t.property_data.get("component")
                for sc in (c.property_data.get("components") or []) if c is not None else []:
                    fm = por_id.get(str(sc.property_data.get("mob_id", "")))
                    d = fm.property_data.get("descriptor") if fm is not None else None
                    if type(d).__name__ == "CDCIDescriptor" and not d.property_data.get("data_offset"):
                        ruins.append(f"{m.name} → {fm.name}")
    return ruins


def nomear_fitas(f, tape: str = "") -> list[tuple[str, str]]:
    """O TAPE (reel name) de cada master: o mob de FITA que o MXF traz vem SEM nome do Resolve (o pyaaf2 o mostra como
    "Mob", e é isso que a coluna Tape do MC exibia — 2026-10-31). Sem `tape`, o nome do clipe (o arquivo sem extensão,
    o que a opção "reel name = nome do arquivo" do Resolve faria); com `tape`, o rolo dado. Só renomeia fita sem nome:
    um reel que a câmera ou o Resolve gravou de verdade nunca é trocado. Devolve [(master, tape)]."""
    import aaf2

    def referidos(mob):
        for slot in mob.slots:
            seg = slot.segment
            for c in (seg.components if hasattr(seg, "components") else [seg]):
                alvo = getattr(c, "mob", None)
                if alvo is not None:
                    yield alvo

    feitos = []
    for master in [m for m in f.content.mobs if isinstance(m, aaf2.mobs.MasterMob)]:
        for arquivo in referidos(master):
            for fita in referidos(arquivo):
                if type(getattr(fita, "descriptor", None)).__name__ != "TapeDescriptor":
                    continue
                if fita.name in (None, "", "Mob"):
                    fita.name = tape or master.name
                feitos.append((master.name, fita.name))
    return sorted(set(feitos))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mxf", nargs="+")
    ap.add_argument("--bin", required=True)
    ap.add_argument("--nome", default="")
    ap.add_argument("--tape", default="", help="o rolo (reel name); sem ele, o nome do clipe")
    a = ap.parse_args()

    ruins = nao_indexados(a.mxf)
    if ruins:
        print("⛔ o MC ainda não indexou:", *ruins, sep="\n   ")
        print("   Importar agora faria o mob nascer sem offsets e derrubar o MC quando a mídia aparecer.\n"
              "   Gesto: ponha os MXF numa pasta numérica NOVA de Avid MediaFiles\\MXF e traga o MC para a frente\n"
              "   (ele indexa pasta nova ao ganhar o foco); confira que o msmMMOB.mdb nasceu depois dos MXF.")
        return 3

    import aaf2
    aaf = os.path.join(tempfile.mkdtemp(prefix="ciclo_aaf_"), "masters.aaf")
    with aaf2.open(aaf, "w") as f:
        for m in a.mxf:
            f.content.link_external_mxf(m)
        masters = [mob for mob in f.content.mobs if isinstance(mob, aaf2.mobs.MasterMob)]
        if a.nome:
            if len(masters) != 1:
                print(f"⛔ --nome pede UM master; o AAF tem {len(masters)}")
                return 2
            masters[0].name = a.nome
        print("masters:", [(mob.name, str(mob.mob_id)[-16:]) for mob in masters])
        print("tape:", nomear_fitas(f, a.tape))
        umids = {str(mob.mob_id) for mob in masters}

    from piloto import pontes
    with pontes.media_composer() as m:
        pasta = m.projeto(recarregar=True)["path"]
        destino = os.path.join(pasta, a.bin + ".avb")
        if not os.path.exists(destino):
            print("CreateBin:", m._chamar("CreateBin", _timeout=60, folder_path="", bin_name=a.bin).header.status)
        t0 = time.time()
        r = m._chamar("ImportFile", _timeout=120, file_path=aaf, import_settings_name="Untitled",
                      destination_bin=destino)
        print("ImportFile:", r.header.status, round(time.time() - t0, 1), "s")
        print("CloseBin (grava):", m._chamar("CloseBin", _timeout=60, bin_path=destino).header.status)
        print("OpenBin:", m._chamar("OpenBin", _timeout=60, bin_path=destino).header.status)
    print("bin:", destino)
    sem = mobs_sem_offset(destino, umids)
    if sem:
        print("⛔ mob de arquivo SEM offsets (vai derrubar o MC ao ficar online):", *sem, sep="\n   ")
        print("   Conserto no MC: botão direito no master → Modify → Unlink Media, depois Relink → Managed Media.")
        return 4
    return 0


if __name__ == "__main__":
    sys.exit(main())
