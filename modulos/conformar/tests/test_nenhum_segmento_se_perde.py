"""NENHUM SEGMENTO SE PERDE (regra do autor, 2026-10-06): mídia ausente entra OFFLINE.

Rodar:

    .venv-win/Scripts/python tests/test_nenhum_segmento_se_perde.py      (Mac: .venv/bin/python)

O autor importou um .prproj sem mídia nenhuma no disco e o app criou uma timeline VAZIA: o plano sem
arquivo virava só marcador. "Nenhum segmento da timeline deve ser perdido", em todo protocolo e NLE —
o segmento entra no mesmo lugar, apontando para o arquivo, e o editor religa depois.

- Avid (Carta/AAF/bin, `montar_midia`): o clipe cujo master a leitura NÃO trouxe também entra offline;
- Premiere (`prproj_para_drt.montar`): com o caso real R02 e SEM as pastas, todo plano de vídeo e todo
  clipe de áudio da sequência estão no DRT (offline o que não está no disco) — conta pelo XML do DRT.
"""

from __future__ import annotations

import os
import re
import sys
import tempfile
import zipfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"), str(RAIZ / "tests")]

from avb_bin.segmentos import montar_midia  # noqa: E402
from test_carta_ida_e_volta import leitura_sintetica, mid, seg  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(f"{nome}: obtido {obtido!r}, esperado {esperado!r}")
        print(f"  ✗ {nome}: obtido {obtido!r}, esperado {esperado!r}")


def clipes_no_drt(drt: str) -> tuple[int, int]:
    with zipfile.ZipFile(drt) as z:
        txt = "".join(z.read(n).decode("utf-8", "replace") for n in z.namelist() if n.endswith(".xml"))
    return len(re.findall(r"<Sm2TiVideoClip\b", txt)), len(re.findall(r"<Sm2TiAudioClip\b", txt))


def main() -> int:
    print("Avid: o master que a leitura não trouxe")
    leitura = leitura_sintetica()
    sem_master = mid(77)
    leitura["segments"].append(seg(2, "00:00:00:00", "00:00:01:00", 25, sem_master, src=40, nome="SEM_MASTER"))
    with tempfile.TemporaryDirectory() as tmp:
        segs, casados, metas = montar_midia(leitura, {}, tmp, {}, {})
    com_midia = [i for i, s in enumerate(segs) if s.get("mob_id") and not s.get("is_gap") and not s.get("is_transition")]
    ok("⭐ todo segmento com mídia vira um casado (nenhum some)",
       sorted(c["segment_index"] for c in casados), com_midia)
    alvo = next(c for c in casados if segs[c["segment_index"]]["mob_id"] == sem_master)
    ok("…o sem master entra OFFLINE, pelo nome do clipe",
       (alvo["offline"], os.path.basename(alvo["matched_path"]).startswith("SEM_MASTER")), (True, True))
    ok("…com os metadados para o writer (duração cobre o trecho pedido)",
       (metas.get(alvo["matched_path"]) or {}).get("nb", 0) >= 40 + 25, True)

    print("Premiere: o caso R02 sem as pastas dos originais")
    from test_importar_prproj import achar_caso
    caso = achar_caso()
    if caso is None:
        print("  PULADO — o caso R02 PRODUCAO_B EXEMPLOS não está nesta máquina")
    else:
        from avb_bin.segmentos import caminho_confiavel
        from tools.prproj_para_drt import analisar, montar
        a = analisar(str(caso), "DU exemplos especificos", [], confiavel=caminho_confiavel)
        ss = a["leitura"]["segmentos"]
        com_arquivo = lambda s: (s.get("media_ref") or {}).get("local_path")  # noqa: E731
        video = sum(1 for s in ss if not s.get("is_audio") and not s.get("is_gap") and not s.get("is_transition")
                    and not s.get("is_effect") and com_arquivo(s))
        audio = sum(1 for s in ss if s.get("is_audio") and not s.get("is_gap") and not s.get("is_transition")
                    and com_arquivo(s))
        with tempfile.TemporaryDirectory() as tmp:
            drt = str(Path(tmp) / "r02.drt")
            rel = montar(str(caso), "DU exemplos especificos", drt, [], analise=a)
            v, au = clipes_no_drt(drt)
        ausentes = sum(1 for p in a["casamento"] if p and not os.path.isfile(p))
        print(f"  (nesta máquina: {ausentes} de {len(a['casamento'])} arquivos de vídeo fora do disco)")
        ok("⭐ todo plano de vídeo com arquivo está no DRT (os gráficos à parte)", v >= video, True)
        ok("⭐ todo clipe de áudio está no DRT", au, audio)
        ok("o relatório lista os que entraram offline",
           len(rel["offline"]) >= ausentes, True)

        print("Premiere: a trilha de notas (nunca tinha sido ligada; autor, 2026-10-06)")
        with tempfile.TemporaryDirectory() as tmp:
            sem = montar(str(caso), "DU exemplos especificos", str(Path(tmp) / "s.drt"), [], analise=a)
            com = montar(str(caso), "DU exemplos especificos", str(Path(tmp) / "c.drt"), [], analise=a,
                         notas=True)
        ok("⭐ ligada, o DRT leva notas; desligada, nenhuma",
           ((sem.get("drt") or {}).get("notas"), ((com.get("drt") or {}).get("notas") or 0) > 0), (0, True))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
