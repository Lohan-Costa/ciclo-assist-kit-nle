"""O gesto da missão, inteiro: cópia da timeline na MESMA bin, e ela carrega sozinha.

    python spikes/copia_carrega_na_record.py       (exige MC aberto)

A missão do editor (2026-09-13): editar uma timeline já montada — a cópia modificada ao
lado, a original intacta, e **a cópia carregando sozinha na Record**.

Medido antes, em `spikes/carregar_na_record.py`:
- `LoadMobsIntoViewer` com `Record` carrega a sequência na Record (e em `Center`);
- ⛔ o MobID tem de vir na forma da API (`060a2b34…13-000000-…`), a URN do pyavb é recusada;
- ⛔ `CloseBin` TIRA a sequência dos monitores, e bin fechada não carrega.

⇒ A ordem do gesto sai daí: fechar (a Record esvazia) → gravar a cópia → abrir → carregar.

## ⛔⛔ O QUE ISTO CAUSOU (2026-09-13): o Media Composer caiu nas DUAS rodadas

`ACCESS_VIOLATION` em `0x0`, thread principal, no passo "a original na Record → `CloseBin`"
(10:03:12 e 10:04:18). O MC não fecha — mostra o diálogo e segue depois do OK —, e
enquanto o diálogo está aberto a API não responde. A primeira rodada estourou o prazo ali;
a segunda tinha 90 s de prazo, o editor clicou OK dentro dele, e o spike imprimiu ✅.
⇒ **Um spike que só lê a API não vê o diálogo.** O ✅ desta rodada foi falso até o editor
mandar os prints.

✅ **Causa isolada no mesmo dia** (`fechar_bin_com_monitor.py`, `qual_passo_derruba.py`): é o
trio `LoadMobsIntoViewer` → `GetViewerMobs` → `CloseBin` sem pausa (5 de 5), que este spike
fazia sem querer ao imprimir os monitores entre carregar e fechar. A ponte
(`cicloassist/avid/mcapi.py`) agora espera 3 s depois de carregar; com ela, 3 de 3 sem queda.

Trabalha numa CÓPIA da bin do editor, com uid novo; a fixture não é escrita.
"""

from __future__ import annotations

import os
import random
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402
from avb.mobid import MobID  # noqa: E402

import cicloassist.avid  # noqa: E402,F401 — a string nula
from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402
from cicloassist.avid.timeline import PREFIXO_DE_COMPOSICAO  # noqa: E402

PROJETO = Path(r"%USERPROFILE%\Documents\Avid Projects\_ASSIST ANTERIOR")
FIXTURE = PROJETO / "BIN COM SEQUENCIA AMA LINK.avb"      # ⛔ SOMENTE LEITURA
TRABALHO = PROJETO / "_REC COPIA.avb"
ORIGINAL = "TL com AMA"
COPIA = "TL com AMA v2"


def para_api(urn: str) -> str:
    """URN do pyavb → a forma que a API aceita. MEDIDO: 13-3-8-6-2 bytes, em hex."""
    h = str(urn).rsplit(":", 1)[-1].replace(".", "").lower()
    assert len(h) == 64, h
    return f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"


def monitores(mc) -> list[tuple[str, str]]:
    # ⚠️ MEDIDO: logo depois de um CloseBin com a sequência na Record, o MC fica ~15 s
    #    sem responder consulta — o prazo de consulta estourava e parecia travamento.
    r = mc._chamar("GetViewerMobs", _timeout=90)
    tipo = r.body.DESCRIPTOR.fields_by_name["mobs"].message_type.fields_by_name["view_type"]
    nomes = {v.number: v.name for v in tipo.enum_type.values}
    return [(m.mob_id, nomes.get(m.view_type, "?")) for m in r.body.mobs]


def main() -> int:
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer não está aberto")
        rel_fx, rel = (mc.caminho_relativo_da_bin(str(p)) for p in (FIXTURE, TRABALHO))
        for r in (rel_fx, rel):
            try:
                mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=r)
            except Exception:   # noqa: BLE001
                pass

        # A bin de trabalho: cópia com uid NOVO (é bin derivada, não a do editor).
        shutil.copy2(FIXTURE, TRABALHO)
        lado = TRABALHO.with_suffix(".avb.novo")
        with avb.open(str(TRABALHO)) as f:
            f.content.uid = random.getrandbits(63)
            f.write(str(lado))
        os.replace(lado, TRABALHO)

        # O estado do editor: a original aberta na Record.
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        itens = {i.nome: i.mob_id for i in mc.itens_da_bin(rel, tipos=("AllTypes",))}
        mc._chamar("LoadMobsIntoViewer", mob_ids=[itens[ORIGINAL]],
                   view_type=mc._enum("LoadMobsIntoViewer", "view_type", "Record"))
        print("editor com a original na Record ....", monitores(mc))

        # 1. fechar
        mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        print("depois do CloseBin .................", monitores(mc))

        # 2. gravar a CÓPIA ao lado da original, na mesma bin
        with avb.open(str(TRABALHO)) as f:
            orig = next(m for m in f.content.mobs if m.name == ORIGINAL)
            nova = orig.copy(f)
            # ⚠️ O `copy` preserva o MobID por valor (é o MESMO clipe noutra bin, medido em
            #    `mover_entre_bins.py`). Na MESMA bin isso seria dois itens com o mesmo
            #    MobID — a cópia precisa de identidade própria.
            nova.mob_id = MobID(bytes_le=bytes(bytearray(PREFIXO_DE_COMPOSICAO) + os.urandom(16)))
            nova.name = COPIA
            f.content.add_mob(nova).user_placed = True
            id_novo = str(nova.mob_id)
            f.write(str(lado))
        os.replace(lado, TRABALHO)
        with avb.open(str(TRABALHO)) as f:
            nomes = sorted(i.mob.name for i in f.content.items if i.user_placed)
            ids = [str(m.mob_id) for m in f.content.mobs]
        print(f"gravada ............................ visíveis={nomes}, "
              f"MobID repetido={len(ids) != len(set(ids))}")

        # 3. abrir
        mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        na_janela = {i.nome: i.mob_id for i in mc.itens_da_bin(rel, tipos=("AllTypes",))}
        print("aberta, na janela ..................", sorted(na_janela))
        print(f"MobID da cópia: pyavb→api {para_api(id_novo)}")
        print(f"                pela API  {na_janela.get(COPIA)}")

        # 4. carregar a cópia
        try:
            mc._chamar("LoadMobsIntoViewer", mob_ids=[para_api(id_novo)],
                       view_type=mc._enum("LoadMobsIntoViewer", "view_type", "Record"))
            print("LoadMobsIntoViewer ................. aceitou")
        except Exception as e:      # noqa: BLE001
            print(f"LoadMobsIntoViewer ................. recusou: {str(e)[:100]}")
        agora = monitores(mc)
        print("monitores ..........................", agora)
        ok = (para_api(id_novo), "Record") in agora
        print(f"\n{'✅' if ok else '⛔'} a cópia está na Record: {ok}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
