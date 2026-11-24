"""Fechar a bin cuja sequência está num monitor: é CORRIDA ou é regra?

    python spikes/fechar_bin_com_monitor.py        (exige MC aberto E o editor na tela)

⛔⛔ Em 2026-09-13, `LoadMobsIntoViewer(Record)` seguido de `CloseBin` daquela bin derrubou o
Media Composer duas vezes (`ACCESS_VIOLATION` em 0x0, thread principal; ver
`spikes/copia_carrega_na_record.py`). Um controle não caiu: com vários passos entre carregar
e fechar. E o `montar_corte` faz `CloseBin` na bin da cena, que pode estar com a sequência
do editor na Record — o risco é do produto, não só do spike.

Três testes, uma variável cada:
  1. carregar → ESPERAR 10 s → fechar           (se não cair, a queda de antes era corrida)
  2. carregar → Clear Monitor (6290) → fechar    (esvaziar o monitor antes protege?)
  3. o EDITOR carrega à mão → fechar pela API     (o caso real do montar_corte)

⭐ Não depende de ler a tela: o MC grava `FatalExcpt` no `EVENTLOG.LOG` no instante da
exceção, e a API fica muda enquanto o diálogo está aberto. O spike confere as duas coisas
depois de cada `CloseBin`, e ESPERA a API voltar (o editor clicando OK) antes do próximo.

Trabalha numa cópia da bin do editor, com uid novo.

    python spikes/fechar_bin_com_monitor.py --teste4   # carregar → fechar, sem pausa
    python spikes/fechar_bin_com_monitor.py --teste5   # carregar → consultar → fechar; bin apagada
    python spikes/fechar_bin_com_monitor.py --teste6   # carregar → consultar, sem fechar

## O QUE ISTO MEDIU (2026-09-13, MC 2025.6.58781, o editor na tela)

| sequência | quedas |
|---|---|
| carregar → **consultar** → **fechar**, colados (5a, e as 4 do `copia_carrega_na_record`) | ⛔ **5 de 5** |
| carregar → fechar, colados (4) | 0 de 3 |
| carregar → consultar, sem fechar (6) | 0 de 2 |
| carregar → 10 s / 5 s → consultar → fechar (1, 2) | 0 de 2 |
| o editor carrega na interface → fechar pela API (3) | 0 de 1 |
| `CloseBin` numa bin apagada que o projeto lista (5b) | 0 de 2 |
| **5a com a espera de 3 s da ponte** | ✅ **0 de 3** |

⚠️ O Clear Monitor (6290) foi aceito e **não esvaziou** a Record: nenhum monitor estava ativo.
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

import cicloassist.avid  # noqa: E402,F401 — a string nula
from cicloassist.avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402

PROJETO = Path(r"%USERPROFILE%\Documents\Avid Projects\_Assist anterior")
FIXTURE = PROJETO / "BIN COM SEQUENCIA AMA LINK.avb"      # ⛔ SOMENTE LEITURA
TRABALHO = PROJETO / "_MON TESTE.avb"
SEQUENCIA = "TL com AMA"
EVENTLOG = Path(r"C:\Users\Public\Documents\Avid Media Composer\Avid FatalErrorReports"
                r"\EVENTLOG.LOG")
CLEAR_MONITOR = 6290


def carimbo(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')}  {msg}", flush=True)


def tamanho_do_log() -> int:
    return EVENTLOG.stat().st_size if EVENTLOG.exists() else 0


def quedas_desde(posicao: int) -> list[str]:
    if not EVENTLOG.exists():
        return []
    with open(EVENTLOG, "rb") as f:
        f.seek(posicao)
        novo = f.read().decode("utf-8", "replace")
    return [l.strip()[:140] for l in novo.splitlines() if "FatalExcpt" in l]


def monitores(mc, prazo: float = 5) -> list[tuple[str, str, bool]] | None:
    """`None` = a API não respondeu no prazo (diálogo aberto, provavelmente)."""
    try:
        r = mc._chamar("GetViewerMobs", _timeout=prazo)
    except Exception:   # noqa: BLE001
        return None
    tipo = r.body.DESCRIPTOR.fields_by_name["mobs"].message_type.fields_by_name["view_type"]
    nomes = {v.number: v.name for v in tipo.enum_type.values}
    return [(m.mob_id, nomes.get(m.view_type, "?"), bool(m.active)) for m in r.body.mobs]


def esperar_a_api(mc, ate: float = 600) -> float:
    """Espera a API responder de novo. Devolve quantos segundos ficou muda."""
    t0 = time.monotonic()
    avisou = False
    while time.monotonic() - t0 < ate:
        if monitores(mc, prazo=5) is not None:
            return time.monotonic() - t0
        if not avisou:
            carimbo("   ⏳ API muda — se houver diálogo de erro na tela, clique OK")
            avisou = True
        time.sleep(2)
    raise SystemExit("a API não voltou em 10 min; parando")


def preparar() -> None:
    shutil.copy2(FIXTURE, TRABALHO)
    lado = TRABALHO.with_suffix(".avb.novo")
    with avb.open(str(TRABALHO)) as f:
        f.content.uid = random.getrandbits(63)
        f.write(str(lado))
    os.replace(lado, TRABALHO)


def abrir(mc, rel: str) -> str:
    mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
    # ⚠️ Pelo COMEÇO do nome: com o mesmo MobID visível noutra bin aberta, o MC renomeia
    #    para `… .AutoCopy.NN` (medido na primeira tentativa deste spike).
    itens = mc.itens_da_bin(rel, tipos=("AllTypes",))
    return next(i.mob_id for i in itens if i.nome.startswith(SEQUENCIA))


def fechar_e_julgar(mc, rel: str, rotulo: str) -> dict:
    antes = monitores(mc)
    log0 = tamanho_do_log()
    carimbo(f"   monitores antes do CloseBin: {antes}")
    carimbo("   CloseBin…")
    try:
        mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
        carimbo("   CloseBin respondeu")
    except Exception as e:      # noqa: BLE001
        carimbo(f"   CloseBin: {str(e)[:80]}")
    time.sleep(3)
    muda = esperar_a_api(mc)
    time.sleep(1)
    quedas = quedas_desde(log0)
    veredito = "⛔ CAIU" if quedas else "✅ não caiu"
    carimbo(f"   {veredito} · API muda por {muda:.0f} s · {quedas or ''}")
    return {"teste": rotulo, "caiu": bool(quedas), "api_muda_s": round(muda),
            "depois": monitores(mc)}


def main() -> int:
    placar = []
    with MediaComposer() as mc:
        if not mc.esta_vivo():
            sys.exit("o Media Composer não está aberto")
        rel = mc.caminho_relativo_da_bin(str(TRABALHO))
        outras = [FIXTURE, PROJETO / "_REC COPIA.avb"]
        for r in [mc.caminho_relativo_da_bin(str(b)) for b in outras] + [rel]:
            try:
                mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=r)
            except Exception:   # noqa: BLE001
                pass
        esperar_a_api(mc)
        preparar()
        record = mc._enum("LoadMobsIntoViewer", "view_type", "Record")

        if "--teste6" in sys.argv:
            # 6 — o CloseBin faz parte do gatilho? Carregar e consultar colados, SEM fechar.
            #     O 5a caiu com os três colados; o `carregar_na_record.py` consultou colado e
            #     não caiu, mas não fechava logo depois.
            for tentativa in range(1, 3):
                carimbo(f"TESTE 6.{tentativa} — carregar → GetViewerMobs colados, SEM CloseBin")
                seq = abrir(mc, rel)
                time.sleep(2)
                log0 = tamanho_do_log()
                mc._chamar("LoadMobsIntoViewer", mob_ids=[seq], view_type=record)
                monitores(mc, prazo=60)
                time.sleep(8)
                muda = esperar_a_api(mc)
                q = quedas_desde(log0)
                carimbo(f"   {'⛔ CAIU' if q else '✅ não caiu'} · API muda {muda:.0f} s")
                placar.append({"teste": f"6.{tentativa} sem fechar", "caiu": bool(q),
                               "api_muda_s": round(muda), "depois": None})
                time.sleep(4)
                mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
                time.sleep(4)
                if q:
                    break
            print("\n" + "=" * 70)
            for p in placar:
                print(f"{'⛔ CAIU    ' if p['caiu'] else '✅ não caiu'}  {p['teste']:20s} "
                      f"API muda {p['api_muda_s']} s")
            return 0

        if "--teste5" in sys.argv:
            # 5a — o padrão exato das quedas das 10:03/10:04: carregar, CONSULTAR o monitor
            #      e fechar, tudo colado. O teste 4 não tinha a consulta no meio.
            for tentativa in range(1, 4):
                carimbo(f"TESTE 5a.{tentativa} — carregar → GetViewerMobs → CloseBin, colados")
                seq = abrir(mc, rel)
                time.sleep(2)
                log0 = tamanho_do_log()
                mc._chamar("LoadMobsIntoViewer", mob_ids=[seq], view_type=record)
                visto = monitores(mc, prazo=60)
                try:
                    mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
                except Exception as e:      # noqa: BLE001
                    carimbo(f"   CloseBin: {str(e)[:80]}")
                time.sleep(3)
                muda = esperar_a_api(mc)
                time.sleep(1)
                q = quedas_desde(log0)
                carimbo(f"   {'⛔ CAIU' if q else '✅ não caiu'} · na Record antes: "
                        f"{any(x[1] == 'Record' for x in (visto or []))} · API muda {muda:.0f} s")
                placar.append({"teste": f"5a.{tentativa}", "caiu": bool(q),
                               "api_muda_s": round(muda), "depois": None})
                if q:
                    break
                time.sleep(5)

            # 5b — a queda do primeiro segundo da rodada A (10:22:09): CloseBin numa bin que
            #      o projeto LISTA mas cujo arquivo foi apagado.
            carimbo("TESTE 5b — CloseBin numa bin apagada do disco que o projeto ainda lista")
            apagada = PROJETO / "_DEL TESTE.avb"
            shutil.copy2(TRABALHO, apagada)
            lado = apagada.with_suffix(".avb.novo")
            with avb.open(str(apagada)) as f:
                f.content.uid = random.getrandbits(63)
                f.write(str(lado))
            os.replace(lado, apagada)
            rel_del = mc.caminho_relativo_da_bin(str(apagada))
            mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel_del)
            time.sleep(2)
            mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel_del)
            time.sleep(3)
            apagada.unlink()
            carimbo(f"   arquivo apagado; existe={apagada.exists()}")
            time.sleep(2)
            log0 = tamanho_do_log()
            try:
                mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel_del)
                carimbo("   CloseBin respondeu")
            except Exception as e:      # noqa: BLE001
                carimbo(f"   CloseBin: {str(e)[:80]}")
            time.sleep(3)
            muda = esperar_a_api(mc)
            time.sleep(1)
            q = quedas_desde(log0)
            carimbo(f"   {'⛔ CAIU' if q else '✅ não caiu'} · API muda {muda:.0f} s")
            placar.append({"teste": "5b bin apagada", "caiu": bool(q),
                           "api_muda_s": round(muda), "depois": None})
            print("\n" + "=" * 70)
            for p in placar:
                print(f"{'⛔ CAIU    ' if p['caiu'] else '✅ não caiu'}  {p['teste']:20s} "
                      f"API muda {p['api_muda_s']} s")
            return 0

        if "--teste4" in sys.argv:
            # ⛔ O teste que DEVE derrubar o MC, se a queda for corrida: carregar e fechar
            #    sem intervalo nenhum — o padrão exato das duas quedas das 10:03 e 10:04.
            #    Até 3 tentativas, porque corrida nem sempre ganha; para na primeira queda.
            for tentativa in range(1, 4):
                carimbo(f"TESTE 4.{tentativa} — carregar na Record e fechar SEM esperar")
                seq = abrir(mc, rel)
                time.sleep(2)   # a bin assentar; o que se mede é o intervalo carregar→fechar
                log0 = tamanho_do_log()
                mc._chamar("LoadMobsIntoViewer", mob_ids=[seq], view_type=record)
                try:
                    mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=rel)
                    carimbo("   CloseBin respondeu")
                except Exception as e:      # noqa: BLE001
                    carimbo(f"   CloseBin: {str(e)[:80]}")
                time.sleep(3)
                muda = esperar_a_api(mc)
                time.sleep(1)
                quedas = quedas_desde(log0)
                carimbo(f"   {'⛔ CAIU' if quedas else '✅ não caiu'} · API muda por "
                        f"{muda:.0f} s · {quedas or ''}")
                placar.append({"teste": f"4.{tentativa} sem esperar", "caiu": bool(quedas),
                               "api_muda_s": round(muda), "depois": monitores(mc)})
                if quedas:
                    break
                time.sleep(5)
            print("\n" + "=" * 70)
            for p in placar:
                print(f"{'⛔ CAIU    ' if p['caiu'] else '✅ não caiu'}  {p['teste']:20s} "
                      f"API muda {p['api_muda_s']} s")
            return 0

        carimbo("TESTE 1 — carregar na Record, esperar 10 s, fechar")
        seq = abrir(mc, rel)
        mc._chamar("LoadMobsIntoViewer", mob_ids=[seq], view_type=record)
        time.sleep(10)
        placar.append(fechar_e_julgar(mc, rel, "1 esperar 10 s"))
        time.sleep(5)

        carimbo("TESTE 2 — carregar na Record, Clear Monitor, fechar")
        seq = abrir(mc, rel)
        mc._chamar("LoadMobsIntoViewer", mob_ids=[seq], view_type=record)
        time.sleep(3)
        carimbo(f"   monitores (qual está ativo?): {monitores(mc)}")
        try:
            mc._chamar("DoCommand", commandId=CLEAR_MONITOR)
            carimbo("   Clear Monitor aceito")
        except Exception as e:      # noqa: BLE001
            carimbo(f"   Clear Monitor: {str(e)[:80]}")
        time.sleep(2)
        placar.append(fechar_e_julgar(mc, rel, "2 clear monitor"))
        time.sleep(5)

        carimbo("TESTE 3 — o EDITOR arrasta a sequência para a Record; eu espero")
        seq = abrir(mc, rel)
        carimbo(f"   >>> arraste '{SEQUENCIA}' da bin '{TRABALHO.stem}' para o monitor da DIREITA")
        t0 = time.monotonic()
        while time.monotonic() - t0 < 600:
            m = monitores(mc) or []
            if (seq, "Record", True) in m or any(x[0] == seq and x[1] == "Record" for x in m):
                break
            time.sleep(2)
        else:
            carimbo("   ninguém carregou em 10 min; teste 3 pulado")
            m = None
        if m is not None:
            carimbo("   carregada pelo editor; esperando 10 s e fechando pela API")
            time.sleep(10)
            placar.append(fechar_e_julgar(mc, rel, "3 editor carregou"))

    print("\n" + "=" * 70)
    for p in placar:
        print(f"{'⛔ CAIU    ' if p['caiu'] else '✅ não caiu'}  {p['teste']:20s} "
              f"API muda {p['api_muda_s']} s · monitores depois: {p['depois']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
