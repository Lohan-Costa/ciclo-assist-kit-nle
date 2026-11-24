"""MXF OP-Atom feito FORA do MC → masters ONLINE numa bin: a operação 5 do ensaio.

Plano: `docs/plano/2026-10-31-operacoes-do-ensaio.md`. Vem do `spikes/opatom_para_mc.py`,
provado no ensaio de 31/10 (MC 2024.6). Banco: `plugins/avid-panel-sdk/windows.md` (OP-Atom
feito fora), `protocolos/msm/README.md` (pasta numérica, indexação ao ganhar o foco).

O caminho: os MXF já numa pasta numérica de `Avid MediaFiles\\MXF` → o MC a indexa → um AAF
com os MASTERS (`pyaaf2 link_external_mxf`: o master ganha o material UMID do MXF, e os
arquivos V/A do mesmo clipe se juntam num master só) → `ImportFile` para a bin.

⛔⛔ **As duas travas, cada uma paga com um crash do MC em 31/10:**
1. **MXF ainda não indexado** (mais novo que o `msmMMOB.mdb` da pasta, ou pasta sem ele): o
   mob de arquivo nasceria com `data_offset = 0`, e o MC cai (`CompressionManager.c` 11276)
   quando a mídia aparece. ⇒ Antes do import, o MC é posto em FOCO (é o que o faz indexar) e
   a operação espera o `.mdb` nascer; não nasceu, recusa.
2. **Depois do import**, todo mob de arquivo de imagem dos nossos masters tem de ter
   `data_offset`; sem ele, a operação diz o conserto (Unlink + Relink Managed) em vez de
   deixar o editor descobrir pelo crash.

⭐ O TAPE (reel name): o Resolve grava a fita SEM nome, e a coluna Tape mostrava "Mob". Sem
`tape`, o nome do clipe; com `tape`, o rolo. Só fita sem nome é renomeada.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Callable

from .. import janela as _janela
from .atributos import copiar_atributos

#: O processo do Media Composer no Windows (`piloto.apps`).
EXE_DO_MC = "AvidMediaComposer.exe"

#: Quanto esperar o MC indexar a pasta depois do foco. Medido: no 2º ciclo de foco, ~20 s.
PRAZO_DE_INDEXAR_S = 60.0
#: ⭐ MEDIDO (2026-11-01, teste do autor): com ciclo de 15 s o som indexou em 17,2 s — no 2º
#:   ganho de foco. O que indexa é o GANHO, não o tempo em foco: ciclo curto, ganho mais cedo.
CICLO_DE_FOCO_S = 5.0


def _janela_de_fora(antes: int | None, mc: int) -> int | None:
    """Uma janela que NÃO é o MC, para lhe tirar o foco e devolver (o ganho é o que indexa).

    ⛔⛔ MEDIDO (2026-11-01, teste do autor): logo depois de o piloto criar o projeto, a janela da
    frente ERA o MC — o "tira e põe" alternava MC com MC, nenhum ganho de foco acontecia, e o som
    esperou 60 s em vão (a 2ª chamada, refazendo tudo, passou). Fora do MC: a de antes, senão a
    janela do Ciclo Assist, senão a barra de tarefas."""
    if antes and antes != mc and _janela.exe_da_janela(antes).lower() != EXE_DO_MC.lower():
        return antes
    try:
        from ..piloto import espaco as _espaco
        nossas = [h for h, _f in _espaco._nossas()]
        if nossas:
            return nossas[0]
    except Exception:  # noqa: BLE001
        pass
    if sys.platform == "win32":
        import ctypes
        return ctypes.windll.user32.FindWindowW("Shell_TrayWnd", None) or None
    return None


class ImportacaoFalhou(RuntimeError):
    """A frase vai ao modelo como está — e diz o gesto quando há um."""


def mxfs_da_pasta(pasta: str | Path) -> list[Path]:
    return sorted(p for p in Path(pasta).glob("*.mxf") if not p.name.startswith("._"))


def pasta_valida(pasta: str | Path) -> str:
    """"" se a pasta é uma diária de `Avid MediaFiles\\MXF\\<só dígitos>`; senão o motivo."""
    p = Path(pasta)
    partes = [x.lower() for x in p.parts]
    if len(partes) < 3 or partes[-2] != "mxf" or partes[-3] != "avid mediafiles":
        return f"{p} não é uma pasta de 'Avid MediaFiles\\MXF'"
    if not re.fullmatch(r"\d+", p.name):
        return f"a pasta '{p.name}' não é só de dígitos — o MC não indexa (banco, msm)"
    if not mxfs_da_pasta(p):
        return f"não há MXF em {p}"
    return ""


def nao_indexados(mxfs: list[Path]) -> list[Path]:
    """Os MXF mais novos que o `msmMMOB.mdb` da pasta (ou todos, sem `.mdb`)."""
    ruins = []
    for m in mxfs:
        mdb = m.parent / "msmMMOB.mdb"
        if not mdb.exists() or m.stat().st_mtime > mdb.stat().st_mtime:
            ruins.append(m)
    return ruins


def esperar_indexar(mxfs: list[Path], relatar: Callable, prazo: float = PRAZO_DE_INDEXAR_S) -> float:
    """Põe o MC em foco (e o tira e põe de novo a cada ciclo) até a pasta estar indexada. Devolve os
    segundos; levanta `ImportacaoFalhou` com o gesto. O foco volta à janela que o tinha."""
    if _no_mac():
        return _indexar_no_mac(mxfs, relatar, prazo)
    antes = _janela.da_frente()
    mc = _janela.janela_principal(EXE_DO_MC, "Avid Media Composer")
    if mc is None:
        raise ImportacaoFalhou(
            "Os MXF ainda não foram indexados pelo Media Composer, e não consegui pôr o MC em foco "
            "para isso. Peça ao editor para clicar uma vez na janela do Media Composer e repetir.")
    fora = _janela_de_fora(antes, mc)
    t0 = time.monotonic()
    # ⭐ A borda verde-água (autor, 2026-11-01): o foco vai e volta sozinho entre o MC e o app, e
    #   sem aviso na tela o editor não sabe se pode mexer.
    from ..piloto import borda as _borda
    aviso_na_tela = "CICLO ASSIST  ·  o Media Composer está indexando a mídia nova  ·  não mexa"
    with _borda.acesa(aviso_na_tela):
        return _ciclos_de_foco(mxfs, relatar, prazo, antes, mc, fora, t0, _borda, aviso_na_tela)


def _no_mac() -> bool:
    return sys.platform == "darwin"


#: O MC do Mac (25.12) e quem estava na frente, para devolver.
_MC_NO_MAC = "com.avid.mediacomposer"


def _app_da_frente_no_mac() -> str:
    r = subprocess.run("lsappinfo info -only bundleid `lsappinfo front`", shell=True,
                       capture_output=True, text=True, timeout=10)
    partes = (r.stdout or "").split('"')
    return partes[-2] if len(partes) >= 3 else ""


def _ativar_no_mac(bundle: str) -> None:
    subprocess.run(["osascript", "-e", f'tell application id "{bundle}" to activate'],
                   capture_output=True, text=True, timeout=15)


def _indexar_no_mac(mxfs: list[Path], relatar: Callable, prazo: float) -> float:
    """macOS: o mesmo GANHO de foco do Windows, por `activate` (AppleScript — sem tecla, sem clique).
    MEDIDO (2026-11-05, MC 25.12, Mac mini): índice 0,3 s depois do `activate`; uma pasta sem ele ficou
    3 min sem índice. (Os índices que pareceram "sozinhos" coincidiram com o MC ganhando a frente: o
    Resolve fechando, o meu `activate`.) A frente volta a quem a tinha."""
    antes = _app_da_frente_no_mac()
    t0 = time.monotonic()
    try:
        while time.monotonic() - t0 < prazo:
            if antes and antes != _MC_NO_MAC and _app_da_frente_no_mac() == _MC_NO_MAC:
                _ativar_no_mac(antes)          # sem sair do MC não há GANHO de foco
                time.sleep(0.5)
            _ativar_no_mac(_MC_NO_MAC)
            fim_do_ciclo = time.monotonic() + CICLO_DE_FOCO_S
            while time.monotonic() < fim_do_ciclo:
                if not nao_indexados(mxfs):
                    return round(time.monotonic() - t0, 1)
                relatar("o Media Composer está indexando a pasta nova", None, f"{int(time.monotonic() - t0)} s")
                time.sleep(0.25)
            if antes and antes != _MC_NO_MAC:
                _ativar_no_mac(antes)
                time.sleep(0.5)
    finally:
        if antes and antes != _MC_NO_MAC:
            _ativar_no_mac(antes)
    raise ImportacaoFalhou(
        f"O Media Composer não indexou {mxfs[0].parent} em {int(prazo)} s. Importar agora faria o "
        "master nascer sem offsets e derrubar o MC. Gesto: clicar no MC, esperar uns segundos e repetir.")


def _ciclos_de_foco(mxfs, relatar, prazo, antes, mc, fora, t0, _borda, aviso_na_tela) -> float:
    try:
        while time.monotonic() - t0 < prazo:
            if fora and _janela.da_frente() == mc:
                _janela.focar(fora)           # sem sair do MC não há GANHO de foco
                time.sleep(0.5)
            _janela.focar(mc)
            fim_do_ciclo = time.monotonic() + CICLO_DE_FOCO_S
            while time.monotonic() < fim_do_ciclo:
                relatar("o Media Composer está indexando a pasta nova", None,
                        f"{int(time.monotonic() - t0)} s")
                _borda.mudar_texto(f"{aviso_na_tela}  ·  {int(time.monotonic() - t0)} s")
                if _janela.existe_aviso("AvidMediaComposer"):
                    raise ImportacaoFalhou(
                        "O Media Composer abriu um aviso ao ganhar o foco (provavelmente o do layout do "
                        "teclado). Peça ao editor para clicar em \"Don't warn me again\" e repetir.")
                if not nao_indexados(mxfs):
                    return round(time.monotonic() - t0, 1)
                time.sleep(0.5)
            if fora:                        # o 2º ganho de foco é o que costuma indexar
                _janela.focar(fora)
                time.sleep(0.5)
    finally:
        if antes:
            _janela.focar(antes)
    raise ImportacaoFalhou(
        f"O Media Composer não indexou {mxfs[0].parent} em {int(prazo)} s. Importar agora faria o "
        "master nascer sem offsets e derrubar o MC. Gesto: clicar no MC, esperar uns segundos e repetir.")


def nomear_fitas(f, tape: str = "") -> list[tuple[str, str]]:
    """O TAPE de cada master no AAF (só fita SEM nome). Devolve [(master, tape)]."""
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


def criar_fitas(f, inicios: dict[str, tuple[int, int]], tape: str = "",
                fitas_por_master: dict[str, str] | None = None) -> list[tuple[str, str]]:
    """A FITA de cada master que não tem nenhuma (o OP-Atom do ffmpeg não grava pacote de fita, e o Tape
    saía vazio no MC — 2026-11-01). Uma fita por master, com o nome do rolo (`tape`) ou o do clipe, uma
    trilha de som por mob de arquivo e a trilha de TC no início do clipe; cada mob de arquivo passa a
    apontá-la. `inicios` = {nome do master: (quadros do TC de início, na base do TC; edit rate exata, ex. Fraction(24000, 1001))}. Devolve [(master, tape)]."""
    import aaf2

    def clipes(seg):          # o pyaaf2 embrulha cada trilha numa Sequence
        return list(seg.components) if type(seg).__name__ == "Sequence" else [seg]

    def de_essencia(slot):
        return str(slot.media_kind).lower() in ("sound", "picture")

    feitos = []
    for master in [m for m in f.content.mobs if isinstance(m, aaf2.mobs.MasterMob)]:
        arquivos = []
        for slot in master.slots:
            for c in clipes(slot.segment):
                alvo = getattr(c, "mob", None)
                if alvo is not None and alvo not in arquivos:
                    arquivos.append(alvo)
        def tem_fita(fm):
            return any(getattr(c, "mob", None) is not None
                       for s in fm.slots if de_essencia(s) for c in clipes(s.segment))
        if not arquivos or any(tem_fita(fm) for fm in arquivos) or master.name not in inicios:
            continue
        quadros, fps = inicios[master.name]
        base = round(float(fps))          # a base do TC (23,976 conta em 24); `fps` é a edit rate exata
        # ⛔ MEDIDO (2026-11-01): o nome da fita tem de nascer AQUI, no AAF — renomeá-la depois na bin muda o
        #   arquivo e NÃO a coluna Tape do MC (mostrou o nome do AAF). O sTAPE do gravador vem por `fitas_por_master`.
        nome = (fitas_por_master or {}).get(master.name) or tape or master.name
        fita = f.create.SourceMob()
        f.content.mobs.append(fita)
        kinds = {str(s.media_kind).lower() for fm in arquivos for s in fm.slots if de_essencia(s)}
        som = "sound" if kinds == {"sound"} else "picture"
        fita.create_tape_slots(nome, fps, base, media_kind=som)
        comprimento = fita.slots[0].segment.length
        ids = [1]                     # o create_tape_slots usa 1 (essência) e 2 (TC): os canais seguintes, 3, 4…
        for _ in range(2, len(arquivos) + 1):
            novo_id = max(s.slot_id for s in fita.slots) + 1
            fita.create_empty_slot(fps, som, slot_id=novo_id).segment.length = comprimento
            ids.append(novo_id)
        for s in fita.slots:
            for c in clipes(s.segment):
                if type(c).__name__ == "Timecode":
                    c.start = quadros
        for k, fm in enumerate(arquivos, 1):
            slot = next(s for s in fm.slots if de_essencia(s))
            velho = clipes(slot.segment)[0]
            # ⛔ start = 0: a fita JÁ começa no TC do clipe (a trilha de TC acima). Apontar o instante do TC aqui
            #    soma duas vezes — medido 2026-11-01: Start 20:00:06:00 para um clipe de 10:00:03:00.
            novo = fita.create_source_clip(slot_id=ids[k - 1], start=0,
                                           length=velho.length, media_kind=str(slot.media_kind).lower())
            if type(slot.segment).__name__ == "Sequence":
                slot.segment.components.pop(0)
                slot.segment.components.insert(0, novo)
            else:
                slot.segment = novo
        feitos.append((master.name, nome))
    return feitos


def escrever_aaf(mxfs: list[Path], tape: str = "",
                 inicios: dict[str, tuple[int, int]] | None = None,
                 fitas_por_master: dict[str, str] | None = None) -> tuple[Path, list[dict], list[tuple[str, str]]]:
    """O AAF de masters. Devolve (caminho, [{nome, umid}], fitas). `inicios` liga a criação da fita
    para quem não tem (ver `criar_fitas`)."""
    import aaf2
    aaf = Path(tempfile.mkdtemp(prefix="ciclo_aaf_")) / "masters.aaf"
    with aaf2.open(str(aaf), "w") as f:
        for m in mxfs:
            f.content.link_external_mxf(str(m))
        masters = [{"nome": mob.name, "umid": str(mob.mob_id)}
                   for mob in f.content.mobs if isinstance(mob, aaf2.mobs.MasterMob)]
        fitas = nomear_fitas(f, tape)
        if inicios:
            fitas += criar_fitas(f, inicios, tape, fitas_por_master)
    return aaf, masters, fitas


def hex_do_umid(texto: str) -> str:
    """Os 64 hex do UMID, em qualquer grafia (API `060a2b34…-…`, pyavb/pyaaf2 `urn:smpte:umid:…`)."""
    return re.sub(r"[^0-9a-f]", "", str(texto).lower().replace("urn:smpte:umid:", ""))[-64:]


def mobs_sem_offset(bin_avb: Path, umids: set[str]) -> list[str]:
    """Os mobs de arquivo de IMAGEM dos nossos masters com `data_offset = 0` — o que derruba o MC.

    ⛔ Master que NÃO está na bin também é problema (devolvido como tal): uma conferência que
    só olha o que achou "passa" sobre uma bin vazia — foi o que aconteceu na 1ª prova
    (2026-11-01), com a importação ainda em curso e a bin gravada vazia."""
    import avb
    ruins = []
    alvo = {hex_do_umid(u) for u in umids}
    with avb.open(str(bin_avb)) as f:
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        presentes = {hex_do_umid(m.mob_id) for m in f.content.mobs}
        ruins += [f"master {u[-8:]} não está na bin gravada" for u in sorted(alvo - presentes)]
        for m in f.content.mobs:
            if hex_do_umid(m.mob_id) not in alvo:
                continue
            for t in m.property_data.get("tracks") or []:
                c = t.property_data.get("component")
                for sc in (c.property_data.get("components") or []) if c is not None else []:
                    fm = por_id.get(str(sc.property_data.get("mob_id", "")))
                    d = fm.property_data.get("descriptor") if fm is not None else None
                    if type(d).__name__ == "CDCIDescriptor" and not d.property_data.get("data_offset"):
                        ruins.append(f"{m.name} → {fm.name}")
    return ruins


def _fontes_de(m, por: dict, prof: int = 0) -> list:
    """As fontes (SourceMob) que a cadeia de `m` alcança, em profundidade (o mesmo do De Lá Pra Cá)."""
    fora = []
    if prof > 4:
        return fora
    for t in m.property_data.get("tracks") or []:
        c = t.property_data.get("component")
        for x in (c.property_data.get("components") or []) if type(c).__name__ == "Sequence" else [c]:
            alvo = por.get(str(getattr(x, "mob_id", ""))) if x is not None else None
            if alvo is not None and alvo is not m and alvo not in fora:
                fora.append(alvo)
                fora += [y for y in _fontes_de(alvo, por, prof + 1) if y not in fora]
    return fora


def aplicar_metadados(bin_avb: Path, por_umid: dict[str, dict]) -> int:
    """O nome, as colunas (`_USER`) e a fita de cada master COMO O MC GRAVA ao linkar o mesmo BWF.

    ⭐ Decisão do autor (2026-11-01): *"prefiro seguir como o MC faz"*. `por_umid` = {umid do master:
    `bwf.como_o_avid(wav)`} — `CENA/TAKE` e Scene, Take, TapeID, Shoot Date, TRKn, Production, Circled;
    sem cena, o nome do arquivo com a extensão. O mesmo que o De Lá Pra Cá aplica (`avb_bin/audio._como_o_avid`).
    ⛔ Só com a bin FECHADA (quem chama a fecha antes e reabre depois); escreve ao lado e troca (`os.replace`),
    preservando o `uid` (banco, `protocolos/avb/escrita.md`). Devolve quantos masters mudaram."""
    import avb

    alvo = {hex_do_umid(u): meta for u, meta in por_umid.items() if meta}
    if not alvo:
        return 0
    novo = bin_avb.with_name(bin_avb.name + ".novo")      # extensão que o MC não enxerga
    n = 0
    with avb.open(str(bin_avb)) as f:
        por = {str(m.mob_id): m for m in f.content.mobs}
        for m in list(f.content.mobs):
            meta = alvo.get(hex_do_umid(m.mob_id))
            if not meta:
                continue
            m.name = meta["nome"]
            attrs = m.property_data.get("attributes")
            if attrs is None:
                attrs = f.create.Attributes()
                m.property_data["attributes"] = attrs
            user = f.create.Attributes()
            for k, v in meta["user"].items():
                user[k] = v
            attrs["_USER"] = user
            # A fita: o sTAPE do gravador; sem cena, o nome do arquivo (o MC põe uma fonte de MÍDIA com ele).
            tape = meta.get("tape") or (meta["nome"] if "Scene" not in meta["user"] else None)
            if tape:
                for fonte in _fontes_de(m, por):
                    d = fonte.property_data.get("descriptor")
                    if d is not None and "Tape" in type(d).__name__:
                        fonte.name = tape
            n += 1
        if n:
            f.write(str(novo))
    if n:
        copiar_atributos(bin_avb, novo)      # o `os.replace` levaria embora o estado da bin no Mac (colunas, vista)
        os.replace(novo, bin_avb)
    return n


#: Quanto esperar os masters aparecerem na bin depois do `ImportFile` (banco: 529 mobs em ~10 s).
PRAZO_DOS_MASTERS_S = 60.0
#: Folga depois de os masters aparecerem, antes do `CloseBin` (a bin pode ainda estar sendo escrita).
PAUSA_ANTES_DE_FECHAR_S = 3.0


def esperar_masters(m, relativo: str, umids: set[str], relatar: Callable,
                    prazo: float = PRAZO_DOS_MASTERS_S) -> None:
    """Até todo master do AAF estar na bin (pela API). Não chegou = o "Completed sem efeito" do banco."""
    alvo = {hex_do_umid(u) for u in umids}
    t0 = time.monotonic()
    vistos: set[str] = set()
    while time.monotonic() - t0 < prazo:
        try:
            vistos = {hex_do_umid(i.mob_id) for i in m.itens_da_bin(relativo)}
        except Exception:                     # a bin pode não responder no meio da importação
            vistos = set()
        relatar("esperando os masters chegarem à bin", len(alvo & vistos) / max(len(alvo), 1),
                f"{len(alvo & vistos)} de {len(alvo)}")
        if alvo <= vistos:
            return
        time.sleep(2)
    raise ImportacaoFalhou(
        f"O Media Composer disse que importou, mas só {len(alvo & vistos)} de {len(alvo)} masters "
        f"apareceram na bin em {int(prazo)} s. Não fechei a bin (fechar no meio da importação a grava "
        "vazia). Confira a bin na tela.")


def offline(m, relativo: str, umids: set[str]) -> list[str]:
    """Os masters (dos `umids`) que o MC diz OFFLINE: a coluna `Offline` da bin, pelo `GetMobInfo` com as
    colunas ocultas. Vazia = online (medido 2026-11-01 nos 12 masters online; ⚠️ nenhum offline de
    verdade foi visto ainda — `inferido`). Não depende de foto nem de layout."""
    alvo = {hex_do_umid(u) for u in umids}
    fora = []
    for item in m.itens_da_bin(relativo):
        if hex_do_umid(item.mob_id) not in alvo:
            continue
        colunas = {r.body.column_name: r.body.column_value
                   for r in m._fluxo("GetMobInfo", mob_id=item.mob_id, only_visible_columns=False,
                                     includes_empty_columns=True)}
        if colunas.get("Offline", "").strip():
            fora.append(f"{item.nome} ({colunas['Offline']})")
    return fora


def importar(m, pasta: str | Path, bin_nome: str, *, tape: str = "",
             inicios: dict[str, tuple[int, int]] | None = None,
             metadados: dict[str, dict] | None = None,
             relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """`m` é a ponte (`mcapi.MediaComposer`, aberta). Devolve a bin, os masters e as fitas.

    `metadados` = {nome do master no AAF: `bwf.como_o_avid(wav)`} — aplicados com a bin fechada
    (`aplicar_metadados`), entre o `CloseBin` e o `OpenBin` que a importação já faz."""
    relatar = relatar or (lambda *_: None)
    motivo = pasta_valida(pasta)
    if motivo:
        raise ImportacaoFalhou(motivo)
    mxfs = mxfs_da_pasta(pasta)
    indexar_s = 0.0
    if nao_indexados(mxfs):
        indexar_s = esperar_indexar(mxfs, relatar)
    relatar("escrevendo o AAF dos masters", None, f"{len(mxfs)} MXF")
    # A fita como o MC a nomeia ao linkar: o sTAPE do gravador; sem cena, o nome do arquivo.
    fitas_por_master = {nome: meta.get("tape") or (meta["nome"] if "Scene" not in meta["user"] else "")
                        for nome, meta in (metadados or {}).items() if meta}
    aaf, masters, fitas = escrever_aaf(mxfs, tape, inicios, {k: v for k, v in fitas_por_master.items() if v})
    projeto = m.projeto(recarregar=True)["caminho"]
    destino = Path(projeto) / f"{bin_nome}.avb"
    if not destino.exists():
        m._chamar("CreateBin", _timeout=60, folder_path="", bin_name=bin_nome)
    relatar("importando os masters no Media Composer", None, bin_nome)
    relativo = m.caminho_relativo_da_bin(str(destino))           # Close/Open/List querem o relativo
    t0 = time.monotonic()
    m._chamar("ImportFile", _timeout=180, file_path=str(aaf), import_settings_name="Untitled",
              destination_bin=str(destino))
    # ⛔⛔ O `ImportFile` é ASSÍNCRONO: volta "Completed" antes de os mobs chegarem à bin (banco,
    #    `plugins/avid-panel-sdk/windows.md`: Save colado 0,1 s depois = a importação nunca chegou).
    #    Na 1ª prova deste código (2026-11-01) o `CloseBin` 0,1 s depois gravou a bin VAZIA e o MC
    #    caiu logo em seguida. ⇒ esperar cada master aparecer na bin pela API; só então fechar.
    esperar_masters(m, relativo, {x["umid"] for x in masters}, relatar)
    importar_s = round(time.monotonic() - t0, 1)
    time.sleep(PAUSA_ANTES_DE_FECHAR_S)
    m._chamar("CloseBin", _timeout=60, bin_path=relativo)        # grava a bin no disco
    renomeados = 0
    if metadados:
        por_umid = {x["umid"]: metadados.get(x["nome"]) for x in masters}
        original = destino.read_bytes()
        try:
            renomeados = aplicar_metadados(destino, por_umid)
        except Exception as e:  # noqa: BLE001  — metadado é acessório: a bin volta como o MC a gravou
            destino.write_bytes(original)
            log_aviso = f"os metadados do BWF não foram aplicados ({e}); a bin ficou como o MC a gravou"
            relatar(log_aviso, None, "")
    try:
        m._chamar("OpenBin", _timeout=60, bin_path=relativo)
    except Exception:
        if renomeados:
            # ⛔ A bin regravada foi recusada: a do MC volta byte a byte, e reabre.
            destino.write_bytes(original)
            m._chamar("OpenBin", _timeout=60, bin_path=relativo)
            renomeados = 0
        else:
            raise
    try:
        os.unlink(aaf)
        os.rmdir(aaf.parent)
    except OSError:
        pass
    sem = mobs_sem_offset(destino, {x["umid"] for x in masters})
    if sem:
        raise ImportacaoFalhou(
            "Importei, mas estes masters ficaram com o arquivo de imagem SEM offsets e vão derrubar o "
            "Media Composer quando ficarem online: " + "; ".join(sem) + ". Conserto no MC: botão direito "
            "no master → Modify → Unlink Media, depois Relink → Managed Media.")
    fora = offline(m, relativo, {x["umid"] for x in masters})
    if fora:
        raise ImportacaoFalhou("Importei, mas o Media Composer diz que estes masters estão OFFLINE: "
                               + "; ".join(fora) + ". Os MXF estão em " + str(pasta) + ".")
    nomes = [(metadados or {}).get(x["nome"], {}).get("nome") or x["nome"] for x in masters] \
        if renomeados else [x["nome"] for x in masters]
    return {"bin": bin_nome, "bin_caminho": str(destino), "pasta": str(pasta), "mxf": len(mxfs),
            "masters": nomes, "fitas": dict(fitas), "online": len(masters),
            "indexar_s": indexar_s, "importar_s": importar_s,
            **({"com_metadados_do_bwf": renomeados} if metadados else {})}
