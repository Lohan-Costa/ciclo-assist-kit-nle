"""Qual passo, exatamente, derruba o Media Composer?

    python spikes/qual_passo_derruba.py        (exige MC aberto E o editor na tela)

⛔⛔ `spikes/copia_carrega_na_record.py` derrubou o MC em 4 de 4 rodadas (10:03, 10:04,
10:22, 10:27 de 2026-09-13), e o `fechar_bin_com_monitor.py`, que isola "Record → fechar",
em 0 de 6. Na rodada das 10:22 a queda veio 1 s depois do início, antes de qualquer coisa
estar na Record. ⇒ O suspeito deixou de ser o monitor.

Este spike refaz o roteiro da cópia passo a passo e, depois de CADA passo — inclusive os
que só mexem em arquivo e não chamam a API —, espera 3 s, confere se a API responde e conta
as linhas `FatalExcpt` do `EVENTLOG.LOG`. Duas hipóteses a separar:
  (a) uma CHAMADA da API derruba;
  (b) o MC VIGIA a pasta e cai sozinho quando o arquivo de uma bin que ele conhece muda
      por baixo dele — o passo que só grava arquivo acusaria a queda.
"""

from __future__ import annotations

import os
import random
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import avb  # noqa: E402
from avb.mobid import MobID  # noqa: E402

import cicloassist.avid  # noqa: E402,F401
from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402
from cicloassist.avid.timeline import PREFIXO_DE_COMPOSICAO  # noqa: E402

PROJETO = Path(r"%USERPROFILE%\Documents\Avid Projects\_Assist anterior")
FIXTURE = PROJETO / "BIN COM SEQUENCIA AMA LINK.avb"      # ⛔ SOMENTE LEITURA
TRABALHO = PROJETO / "_REC COPIA.avb"
ORIGINAL = "TL com AMA"
EVENTLOG = Path(r"C:\Users\Public\Documents\Avid Media Composer\Avid FatalErrorReports"
                r"\EVENTLOG.LOG")


def quedas() -> int:
    return EVENTLOG.read_bytes().count(b"FatalExcpt") if EVENTLOG.exists() else 0


def carimbo(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def api_viva(mc) -> bool:
    try:
        mc._chamar("GetViewerMobs", _timeout=5)
        return True
    except Exception:   # noqa: BLE001
        return False


RESULTADO: list[tuple[str, bool, str]] = []

#: ⭐ `--sem-pausa-apos-closebin`: tira a pausa SÓ depois dos `CloseBin`. A rodada com pausa
#:    em todo passo não caiu (2026-09-13 10:24); sem pausa nenhuma cai 4 de 4. O par
#:    suspeito é "CloseBin → gravar o arquivo daquela bin", que é o que o montar_corte faz.
SEM_PAUSA_APOS_CLOSEBIN = "--sem-pausa-apos-closebin" in sys.argv
#: ⭐ `--sem-pausa-apos-arquivo`: tira a pausa SÓ depois dos passos que GRAVAM a bin — o
#:    `OpenBin` vem colado no `os.replace`, como no `montar_corte`. (A variante do CloseBin
#:    não caiu, 2026-09-13 10:25.)
SEM_PAUSA_APOS_ARQUIVO = "--sem-pausa-apos-arquivo" in sys.argv


def passo(mc, nome: str, acao) -> object:
    antes = quedas()
    t0 = time.monotonic()
    retorno, erro = None, ""
    try:
        retorno = acao()
    except Exception as e:      # noqa: BLE001
        erro = str(e).splitlines()[0][:70]
    rapido = ((SEM_PAUSA_APOS_CLOSEBIN and "CloseBin" in nome and "fixture" not in nome)
              or (SEM_PAUSA_APOS_ARQUIVO and nome.startswith("ARQUIVO")))
    if rapido:
        # Sem pausa E sem consultar a API: qualquer chamada no meio já é uma pausa.
        RESULTADO.append((nome, False, erro))
        carimbo(f"   (sem pausa) {nome:44s} {time.monotonic() - t0:5.1f}s")
        return retorno
    time.sleep(3)
    avisou = False
    while not api_viva(mc):
        if not avisou:
            carimbo("      ⏳ API muda — clique OK no diálogo, se houver")
            avisou = True
        time.sleep(2)
    caiu = quedas() > antes
    RESULTADO.append((nome, caiu, erro))
    carimbo(f"{'⛔ CAIU ' if caiu else '   ok   '} {nome:48s} {time.monotonic() - t0:5.1f}s "
            f"{('· ' + erro) if erro else ''}")
    return retorno


def main() -> int:
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer não está aberto")
        rel_fx = mc.caminho_relativo_da_bin(str(FIXTURE))
        rel = mc.caminho_relativo_da_bin(str(TRABALHO))
        record = mc._enum("LoadMobsIntoViewer", "view_type", "Record")
        carimbo(f"estado: {TRABALHO.name} existe={TRABALHO.exists()} · quedas no log={quedas()}")

        passo(mc, "API CloseBin da fixture (fechada)",
              lambda: mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel_fx))
        passo(mc, "API CloseBin da _REC COPIA",
              lambda: mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel))
        passo(mc, "ARQUIVO copiar fixture por cima da _REC COPIA",
              lambda: shutil.copy2(FIXTURE, TRABALHO))

        def uid_novo():
            lado = TRABALHO.with_suffix(".avb.novo")
            with avb.open(str(TRABALHO)) as f:
                f.content.uid = random.getrandbits(63)
                f.write(str(lado))
            os.replace(lado, TRABALHO)
        passo(mc, "ARQUIVO pyavb: uid novo, os.replace", uid_novo)

        passo(mc, "API OpenBin",
              lambda: mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel))
        itens = passo(mc, "API GetListOfBinItems",
                      lambda: {i.nome: i.mob_id for i in
                               mc.itens_da_bin(rel, tipos=("AllTypes",))}) or {}
        seq = next((v for k, v in itens.items() if k.startswith(ORIGINAL)), "")
        passo(mc, "API LoadMobsIntoViewer(original, Record)",
              lambda: mc._chamar("LoadMobsIntoViewer", mob_ids=[seq], view_type=record))
        passo(mc, "API CloseBin (com a original na Record)",
              lambda: mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel))

        def gravar_copia():
            lado = TRABALHO.with_suffix(".avb.novo")
            with avb.open(str(TRABALHO)) as f:
                orig = next(m for m in f.content.mobs if m.name == ORIGINAL)
                nova = orig.copy(f)
                nova.mob_id = MobID(bytes_le=bytes(bytearray(PREFIXO_DE_COMPOSICAO)
                                                   + os.urandom(16)))
                nova.name = ORIGINAL + " v2"
                f.content.add_mob(nova).user_placed = True
                f.write(str(lado))
            os.replace(lado, TRABALHO)
        passo(mc, "ARQUIVO pyavb: gravar a cópia v2, os.replace", gravar_copia)
        passo(mc, "API OpenBin de novo",
              lambda: mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel))

    print("\n" + "=" * 78)
    for nome, caiu, erro in RESULTADO:
        print(f"{'⛔ CAIU' if caiu else '  ok  '}  {nome}{('  · ' + erro) if erro else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
