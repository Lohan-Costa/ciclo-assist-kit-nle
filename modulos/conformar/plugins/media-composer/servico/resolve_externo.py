"""O Resolve pelo LADO DE FORA: o que a casca (`plugins/resolve/casca/main.js`) faz por dentro, feito pelo serviço
com a API de script externa (organograma do app unificado, quadro 6 — https://claude.ai/artifact/VUZWUF4J9go9FZCB5LF8oT).

O painel não muda: as funções têm os MESMOS nomes e devolvem os MESMOS dicionários que a ponte `window.delapraca`
da casca, e a casca continua valendo quando o painel abre dentro do Resolve. Esta é a ponte quando o painel abre na
janela do app.

Medido em 2026-10-18 (Resolve Studio 19.1.4.11, Windows 11, Python externo): todas as chamadas que a casca faz
funcionam por fora; `Timeline.Export` da timeline NÃO corrente exporta a pedida (banco,
`resolve-scripting/api-scripting.md`, 2026-10-18). Só o Studio: o Free não aceita script externo e não é alvo.

⚠️ Um modal do Resolve (ex.: "A newer version of DaVinci Resolve is needed…") SEGURA a chamada até alguém clicar —
por dentro e por fora. Quem chama precisa de prazo.

Portado: `projeto`, `timelines`, `midias`, `importar` (2026-10-18, 20h) e `fusion`, `luts`, `compostos` (2026-10-18,
23h — os gêmeos Python que a casca já tinha: `drp.fusion_clipe`, `drp.luts`, `drp.compostos`). Depois, a conferência
(`conferirInicio/Quadros/Fim`) e a prova do bypass (`efeitosNoMonitor`). E o Atualizar (`exportarTrabalho`,
`atualizar`, 2026-11-25): a casca saiu na Fase 4 sem ele ter sido portado — ficou sem casa até aqui.
"""
from __future__ import annotations

import json
import logging
import os
import re
import socket
import sys
import threading
import time
from pathlib import Path

log = logging.getLogger("delapraca.resolve_externo")

#: Onde a importação pode cair no pool (a mesma lista fechada da casca).
PASTAS_VALIDAS = {"De Lá Pra Cá", "Inserts"}
_UUID_DRT = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\.drt$")
_WIN = os.name == "nt"


#: O servidor de scripts do Resolve: o filho `fuscript.exe -s` que ele sobe ao abrir, escutando nesta porta. MEDIDO
#: 2026-10-23 (Studio 19.1.4.11, Win11): sem ele, o `scriptapp` falha. Mac (Studio 21.1, 2026-10-24): o MESMO filho
#: (`fuscript -s`, *:1144); derrubado, o `scriptapp` devolve None em 0,01 s (sem prender o GIL, ao contrário do
#: Windows) e o Resolve não o sobe de novo sozinho — a sonda vale nos dois para a mensagem certa ("feche e abra").
PORTA_SCRIPTS = 1144
#: Depois de uma falha, ninguém tenta de novo antes disto (o painel pergunta o estado a cada ~4 s).
ESPERA_DEPOIS_DE_FALHA_S = 15.0
_mudo = {"ate": 0.0, "motivo": ""}
_trava_conexao = threading.Lock()


def _servidor_de_scripts_no_ar() -> bool:
    """Alguém escuta na porta do servidor de scripts? O socket solta o GIL: a sonda não congela o serviço."""
    try:
        with socket.create_connection(("127.0.0.1", PORTA_SCRIPTS), timeout=0.3):
            return True
    except OSError:
        return False


def conectar():
    """O Resolve aberto, pela API externa. Precisa de Preferências → Sistema → Geral → "External scripting using:
    Local" (o Studio vem assim). Caminhos: banco, matriz de plataforma §G3.

    ⛔ O `scriptapp` que não acha o Resolve leva ~4,1 s e SEGURA O GIL nesse tempo (o `fusionscript` não o solta):
    o serviço INTEIRO para, até o `/health`. Com o painel perguntando o estado a cada ~4 s, o serviço vivia parado e
    a leitura de um .prproj de 1 s levava mais de 10 min (MEDIDO 2026-10-23: o `fuscript -s` do Resolve tinha
    morrido; o Resolve não o sobe de novo sozinho). Por isso: a porta primeiro, uma tentativa por vez, e
    depois de uma falha a resposta sai na hora por `ESPERA_DEPOIS_DE_FALHA_S`. A porta vale no Mac também (2026-10-24)."""
    with _trava_conexao:
        if time.monotonic() < _mudo["ate"]:
            raise RuntimeError(_mudo["motivo"])
        if not _servidor_de_scripts_no_ar():
            return _falhou("o servidor de scripts do DaVinci Resolve não está no ar: feche e abra o Resolve")
        r = _scriptapp()
        if not r:
            return _falhou("o DaVinci Resolve não respondeu: está aberto? (o Free não aceita script externo)")
        _mudo["ate"] = 0.0
        return r


def _falhou(motivo: str):
    _mudo["ate"], _mudo["motivo"] = time.monotonic() + ESPERA_DEPOIS_DE_FALHA_S, motivo
    raise RuntimeError(motivo)


def _scriptapp():
    if sys.platform == "darwin":
        api = "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
        lib = "/Applications/DaVinci Resolve/DaVinci Resolve.app/Contents/Libraries/Fusion/fusionscript.so"
    elif _WIN:
        api = os.path.join(os.environ.get("PROGRAMDATA", r"C:\ProgramData"),
                           "Blackmagic Design", "DaVinci Resolve", "Support", "Developer", "Scripting")
        lib = r"C:\Program Files\Blackmagic Design\DaVinci Resolve\fusionscript.dll"
    else:
        api = "/opt/resolve/Developer/Scripting"
        lib = "/opt/resolve/libs/Fusion/fusionscript.so"
    os.environ.setdefault("RESOLVE_SCRIPT_API", api)
    os.environ.setdefault("RESOLVE_SCRIPT_LIB", lib)
    modulos = os.path.join(api, "Modules")
    if modulos not in sys.path:
        sys.path.append(modulos)
    try:
        import DaVinciResolveScript as dvr
    except ImportError as e:
        raise RuntimeError("não achei a API de script do DaVinci Resolve nesta máquina") from e
    return dvr.scriptapp("Resolve")


def _projeto_aberto():
    r = conectar()
    p = r.GetProjectManager().GetCurrentProject()
    return r, p


# ── as trancas (V9, herdadas da casca) ────────────────────────────────────────────────────────────────────────

def drt_confiavel(caminho) -> bool:
    """⛔ Ataque V9: o ÚNICO .drt que se importa é o que o NOSSO serviço escreve em `<cache>/recebidos/<uuid>.drt`.
    Um .drt num compartilhamento de terceiro faria o Resolve abrir sessão SMB com ele."""
    import cache

    if not isinstance(caminho, str) or not caminho:
        return False
    pasta = (cache.raiz() / cache.RECEBIDOS).resolve()
    alvo = Path(caminho).resolve()
    mesmo = (str(alvo.parent).lower() == str(pasta).lower()) if _WIN else alvo.parent == pasta
    return mesmo and bool(_UUID_DRT.match(alvo.name))


def midias_do_drt(drt: str, chave: str = "midias") -> list[str]:
    """A lista que o serviço grava ao lado do .drt (`<uuid>.midias.json`), cada caminho conferido de novo."""
    try:
        dados = json.loads(Path(re.sub(r"\.drt$", ".midias.json", drt, flags=re.I)).read_text("utf-8"))
    except (OSError, ValueError):
        return []
    fora = []
    for p in (dados.get(chave) if isinstance(dados, dict) and isinstance(dados.get(chave), list) else [])[:5000]:
        if isinstance(p, str) and os.path.isabs(p) and "\0" not in p and os.path.isfile(p):
            fora.append(p)
    return fora


# ── o pool ────────────────────────────────────────────────────────────────────────────────────────────────────

def _pasta_no_pool(mp, nome, mae=None):
    raiz = mae or mp.GetRootFolder()
    for f in raiz.GetSubFolderList() or []:
        if f.GetName() == nome:
            return f
    return mp.AddSubFolder(raiz, nome)


def _norma(p: str) -> str:
    return p.lower() if _WIN else p


def _caminhos_no_pool(mp) -> set[str]:
    vistos: set[str] = set()

    def andar(pasta, fundo):
        if pasta is None or fundo > 30:
            return
        for c in pasta.GetClipList() or []:
            try:
                p = c.GetClipProperty("File Path")
                if p:
                    vistos.add(_norma(p))
            except Exception:  # noqa: BLE001 — um item estranho não derruba a varredura
                pass
        for f in pasta.GetSubFolderList() or []:
            andar(f, fundo + 1)
    andar(mp.GetRootFolder(), 0)
    return vistos


def _pasta_da_midia(mp, nome):
    """De Lá Pra Cá › Mídia › <nome da timeline> (decisão do autor, 2026-09-26)."""
    casa = _pasta_no_pool(mp, "De Lá Pra Cá")
    midia = casa and _pasta_no_pool(mp, "Mídia", casa)
    titulo = (nome.strip() if isinstance(nome, str) and nome.strip() else "timeline")[:120]
    return midia and _pasta_no_pool(mp, titulo, midia)


def _mover_depois(mp, drt, nome, pasta_da_importacao) -> int:
    """WAV/AIF de 1–2 canais NÃO é pré-importado (o item do import normal não casa com os clipes mono do Avid e o
    Resolve duplicava o arquivo); o item vem do .drt na pasta da importação e vai aqui para a pasta da mídia."""
    depois = midias_do_drt(drt, "depois")
    if not depois or pasta_da_importacao is None:
        return 0
    querer = {_norma(p) for p in depois}
    destino = _pasta_da_midia(mp, nome)
    if destino is None:
        return 0
    casa = _pasta_no_pool(mp, "De Lá Pra Cá")
    midia = casa and _pasta_no_pool(mp, "Mídia", casa)
    achados = []

    def id_(f):
        try:
            return f.GetUniqueId()
        except Exception:  # noqa: BLE001
            return None

    def andar(pasta, fundo):
        if pasta is None or fundo > 30:
            return
        if midia is not None and id_(pasta) and id_(pasta) == id_(midia):
            return
        for c in pasta.GetClipList() or []:
            try:
                p = c.GetClipProperty("File Path")
                if p and _norma(p) in querer:
                    achados.append(c)
            except Exception:  # noqa: BLE001
                pass
        for f in pasta.GetSubFolderList() or []:
            andar(f, fundo + 1)
    andar(pasta_da_importacao, 0)
    if not achados:
        return 0
    ok = bool(mp.MoveClips(achados, destino))
    log.info("áudio de 1–2 canais: %d itens do .drt %s para a pasta da mídia", len(achados),
             "movidos" if ok else "NÃO movidos")
    return len(achados) if ok else 0


def _timelines(projeto) -> list:
    return [projeto.GetTimelineByIndex(i) for i in range(1, (projeto.GetTimelineCount() or 0) + 1)]


def _nome_livre(projeto, tl, nome) -> int:
    """O nome livre é escolhido pela LISTA antes do `SetName` (pela ponte do painel, nome repetido abria um modal —
    2026-09-27); o laço do `nomear` é só a rede."""
    usados = set()
    try:
        for t in _timelines(projeto):
            if t is not None and t.GetUniqueId() != tl.GetUniqueId():
                usados.add(str(t.GetName() or "").lower())
    except Exception:  # noqa: BLE001
        pass
    for i in range(1, 1000):
        if (nome if i == 1 else f"{nome} {i}").lower() not in usados:
            return i
    return 1


def _nomear(projeto, tl, nome) -> None:
    if not isinstance(nome, str) or not nome:
        return
    for i in range(_nome_livre(projeto, tl, nome), 1000):
        try:
            if tl.SetName(nome if i == 1 else f"{nome} {i}"):
                return
        except Exception:  # noqa: BLE001
            return


def _importar_drt(projeto, mp, drt):
    """A timeline importada: a que a chamada devolve, ou a que APARECEU no projeto (a ponte JS já levantou erro com a
    timeline importada — 2026-09-25). Nunca importa duas vezes."""
    def chave(t):
        try:
            return t.GetUniqueId() or t.GetName()
        except Exception:  # noqa: BLE001
            return t.GetName()
    antes = {chave(t) for t in _timelines(projeto)}
    for rotulo, chamar in (("sem opções", lambda: mp.ImportTimelineFromFile(drt)),
                           ("com {}", lambda: mp.ImportTimelineFromFile(drt, {}))):
        tl = None
        try:
            tl = chamar()
        except Exception as e:  # noqa: BLE001
            log.info("ImportTimelineFromFile %s: %s", rotulo, e)
        if tl:
            return tl
        nova = next((t for t in _timelines(projeto) if chave(t) not in antes), None)
        if nova is not None:
            return nova
    return None


# ── as funções da ponte (mesmos nomes e retornos da casca) ──────────────────────────────────────────────────────

def projeto() -> dict:
    r, p = _projeto_aberto()
    return {"versao": r.GetVersionString(), "projeto": p.GetName() if p else ""}


def timelines() -> dict:
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    atual = ""
    try:
        t = p.GetCurrentTimeline()
        atual = (t.GetName() or "") if t else ""
    except Exception:  # noqa: BLE001
        pass
    lista = []
    for t in _timelines(p):
        try:
            nome = t.GetName() or ""
            lista.append({"uid": t.GetUniqueId() or "", "nome": nome, "atual": bool(atual) and nome == atual})
        except Exception:  # noqa: BLE001
            pass
    return {"ok": True, "timelines": lista}


def midias(pedido: dict) -> dict:
    """Mídia primeiro, timeline depois (2026-09-26): o `ImportTimelineFromFile` liga a timeline aos itens que o
    próprio Resolve criou, e o mapeamento de codec fica com ele."""
    drt, nome = (pedido or {}).get("drt"), (pedido or {}).get("nome")
    if not drt_confiavel(drt):
        return {"ok": False, "erro": "arquivo fora da pasta do De Lá Pra Cá — recusado"}
    lista = midias_do_drt(drt)
    if not lista:
        return {"ok": True, "importadas": 0, "ja_estavam": 0}
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    mp = p.GetMediaPool()
    no_pool = _caminhos_no_pool(mp)
    faltam = [x for x in lista if _norma(x) not in no_pool]
    if not faltam:
        return {"ok": True, "importadas": 0, "ja_estavam": len(lista)}
    alvo = _pasta_da_midia(mp, nome)
    if alvo is not None:
        mp.SetCurrentFolder(alvo)
    t0 = time.time()
    itens = mp.ImportMedia(faltam) or []
    log.info("mídia: %d de %d importados (%d já estavam) em %.1f s", len(itens), len(faltam),
             len(lista) - len(faltam), time.time() - t0)
    return {"ok": True, "importadas": len(itens), "ja_estavam": len(lista) - len(faltam),
            "faltaram": max(0, len(faltam) - len(itens))}


def importar(pedido: dict) -> dict:
    drt = (pedido or {}).get("drt")
    pasta, nome = (pedido or {}).get("pasta"), (pedido or {}).get("nome")
    if not drt_confiavel(drt):
        return {"ok": False, "erro": "o serviço respondeu um arquivo fora da pasta do De Lá Pra Cá — recusado"}
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    mp = p.GetMediaPool()
    # ⚠️ `SetCurrentFolder` é estado GLOBAL e decide onde a importação cai (medido).
    alvo = _pasta_no_pool(mp, pasta if pasta in PASTAS_VALIDAS else "De Lá Pra Cá")
    if alvo is not None:
        mp.SetCurrentFolder(alvo)
    t0 = time.time()
    tl = _importar_drt(p, mp, drt)
    if tl is None:
        # B071: o DRT existe — dizer ONDE, para o editor importá-lo à mão (File ▸ Import ▸ Timeline)
        return {"ok": False, "drt": drt, "erro": f"o Resolve não importou a timeline — o DRT está em {drt} (File ▸ Import ▸ Timeline para tentar à mão)"}
    _nomear(p, tl, nome[:200] if isinstance(nome, str) else "")
    try:
        p.SetCurrentTimeline(tl)
    except Exception:  # noqa: BLE001 — abrir é cortesia
        pass
    try:                                     # a agulha no 1º quadro (autor, 2026-10-04)
        tc = tl.GetStartTimecode()
        if tc:
            tl.SetCurrentTimecode(tc)
    except Exception:  # noqa: BLE001
        pass
    final = tl.GetName()
    log.info("importado %s → %r em %.1f s", Path(drt).name, final, time.time() - t0)
    try:
        _recarregar_notas(tl)
    except Exception as e:  # noqa: BLE001 — as notas são acessório; a timeline já existe
        log.warning("recarregar as notas: %s", e)
    movidas = 0
    try:
        movidas = _mover_depois(mp, drt, nome, alvo)
    except Exception as e:  # noqa: BLE001 — o pool é acessório; a timeline já existe
        log.warning("mover depois: %s", e)
    uid = ""
    try:
        uid = tl.GetUniqueId() or ""
    except Exception:  # noqa: BLE001
        pass
    return {"ok": True, "nome": final, "uid": uid, "movidas": movidas}


def _recarregar_notas(tl) -> int:
    """Exporta e reimporta a composição de cada nota (Text+ com Character Level Styling). ⛔ No Resolve 21.1 (Mac,
    2026-10-24) a cor por trecho chega no DRT — o `ExportFusionComp` a mostra — mas o Text+ a desenha BRANCA até a
    composição ser recarregada; exportar e importar o mesmo texto, sem mudar nada, a faz aparecer (conferido pela
    imagem). No 19.1.4 (Windows) ela já aparecia: aqui só repete o que já está. Devolve quantas recarregou."""
    import tempfile
    feitas, t0 = 0, time.time()
    with tempfile.TemporaryDirectory(prefix="dlpc-notas-") as tmp:
        for v in range(1, (tl.GetTrackCount("video") or 0) + 1):
            for k, it in enumerate(tl.GetItemListInTrack("video", v) or []):
                if it.GetName() != "Text+" or not it.GetFusionCompCount():
                    continue
                arq = os.path.join(tmp, f"v{v}_{k}.comp")
                if not it.ExportFusionComp(arq, 1):
                    continue
                with open(arq, encoding="utf-8", errors="replace") as f:
                    if "StyledTextCLS" not in f.read():
                        continue
                if it.ImportFusionComp(arq):
                    feitas += 1
    if feitas:
        log.info("notas: %d composições recarregadas (cor por trecho) em %.1f s", feitas, time.time() - t0)
    return feitas


# ── depois de importar: Fusion, cor e compostos (as MESMAS etapas e a mesma ordem da casca) ─────────────────────

def _achar_timeline(projeto, uid, nome):
    """A timeline pelo par uid + nome; senão o nome, se único; senão o uid, se único (`acharTimeline` da casca)."""
    todas = []
    for t in _timelines(projeto):
        try:
            todas.append((t, t.GetUniqueId() or "", t.GetName() or ""))
        except Exception:  # noqa: BLE001
            pass
    par = [t for t, u, n in todas if uid and nome and u == uid and n == nome]
    if par:
        return par[0]
    pelo_nome = [t for t, _u, n in todas if nome and n == nome]
    if len(pelo_nome) == 1:
        return pelo_nome[0]
    pelo_id = [t for t, u, _n in todas if uid and u == uid]
    return pelo_id[0] if len(pelo_id) == 1 else None


def _alvo(pedido: dict, chave: str, teto: int):
    """(projeto, timeline, lista) do pedido do painel, ou o erro no formato da casca."""
    _r, p = _projeto_aberto()
    if p is None:
        return None, {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    nome, uid = (pedido or {}).get("nome"), (pedido or {}).get("uid")
    tl = _achar_timeline(p, uid if isinstance(uid, str) else "", nome if isinstance(nome, str) else "")
    if tl is None:
        return None, {"ok": False, "erro": f'a timeline "{nome or ""}" não está neste projeto'}
    lista = (pedido or {}).get(chave)
    return (p, tl, [x for x in lista[:teto] if isinstance(x, dict)] if isinstance(lista, list) else []), None


def _clipe_valido(c: dict) -> bool:
    return (isinstance(c.get("trilha"), int) and 1 <= c["trilha"] <= 999 and isinstance(c.get("quadro"), int)
            and c["quadro"] >= 0 and isinstance(c.get("arquivo"), str))


def fusion(pedido: dict) -> dict:
    """`{nome, uid, clipes: [{trilha, quadro, arquivo, plano}]}` → uma composição por clipe (`drp.fusion_clipe.executar`,
    o gêmeo de `executarPlano`). Um clipe que falha é registrado e os outros seguem."""
    from drp import fusion_clipe

    alvo, erro = _alvo(pedido, "clipes", 2000)
    if erro:
        return erro
    _p, tl, clipes = alvo
    inicio = tl.GetStartFrame()
    fora = []
    for c in clipes:
        base = {k: c.get(k) for k in ("trilha", "quadro", "arquivo")}
        if not _clipe_valido(c) or not isinstance(c.get("plano"), dict):
            fora.append({**base, "ok": False, "erro": "pedido inválido"})
            continue
        item = next((it for it in tl.GetItemListInTrack("video", c["trilha"]) or []
                     if it.GetStart() - inicio == c["quadro"] and it.GetName() == c["arquivo"]), None)
        if item is None:
            fora.append({**base, "ok": False, "erro": "clipe não encontrado na timeline"})
            continue
        try:
            fora.append({**base, **fusion_clipe.executar(item, c["plano"])})
        except Exception as e:  # noqa: BLE001 — registra e segue
            fora.append({**base, "ok": False, "erro": f"{type(e).__name__}: {e}"})
    ok = sum(1 for x in fora if x.get("ok"))
    log.info("fusion: %d de %d composições criadas em %r%s", ok, len(fora), tl.GetName(),
             "".join(f" · {x['arquivo']}@{x['quadro']}: {x.get('erro')}" for x in fora if not x.get("ok")))
    return {"ok": True, "criadas": ok, "clipes": fora}


def _cube_confiavel(caminho) -> bool:
    """⛔ Só o .cube que o NOSSO serviço gravou ao lado do .drt (`<cache>/recebidos/<uuid>_LUTs/…`): o pedido vem do
    painel, e copiar um arquivo qualquer para a pasta de LUTs do Resolve seria abrir a porta."""
    import cache

    if not isinstance(caminho, str) or not caminho.lower().endswith(".cube") or "\0" in caminho:
        return False
    pasta = (cache.raiz() / cache.RECEBIDOS).resolve()
    alvo = Path(caminho).resolve()
    dentro = str(alvo.parent.parent).lower() == str(pasta).lower() if _WIN else alvo.parent.parent == pasta
    return dentro and alvo.parent.name.endswith("_LUTs") and alvo.is_file()


def luts(pedido: dict) -> dict:
    """`{nome, uid, clipes: [{trilha, quadro, arquivo, cube?, saturacao?}]}` → a LUT e/ou a saturação no nó 1
    (`drp.luts.aplicar_luts`, o gêmeo de `aplicarLuts`)."""
    from drp.luts import aplicar_luts

    alvo, erro = _alvo(pedido, "clipes", 500)
    if erro:
        return erro
    p, tl, clipes = alvo
    validos, fora = [], []
    for c in clipes:
        base = {k: c.get(k) for k in ("trilha", "quadro", "arquivo")}
        if not _clipe_valido(c) or (c.get("cube") and not _cube_confiavel(c["cube"])):
            fora.append({**base, "ok": False, "erro": "pedido inválido"})
            continue
        validos.append({k: c[k] for k in ("trilha", "quadro", "arquivo", "cube", "saturacao") if k in c})
    try:
        fora += aplicar_luts(p, tl, {"luts": validos})
    except OSError as e:
        return {"ok": False, "erro": f"não consegui copiar a LUT para a pasta de LUTs do Resolve ({e})"}
    ok = sum(1 for x in fora if x.get("ok"))
    log.info("luts: %d de %d nós de cor (LUT/saturação) em %r%s", ok, len(fora), tl.GetName(),
             "".join(f" · V{x['trilha']}@{x['quadro']}: {x.get('erro')}" for x in fora if not x.get("ok")))
    return {"ok": True, "aplicadas": ok, "clipes": fora}


def cor_mc(pedido: dict) -> dict:
    """`{nome, uid, clipes: [{trilha, quadro, arquivo, sat?, curva?}]}` → o Color Correction do Avid nos 2 nós de cada
    clipe ("MC Master" → "MC Curva", `drp.cor_mc.aplicar_cor_mc`), ANTES das LUTs e da estabilização: o `.drx` troca a
    grade inteira do clipe. A casca ainda não tem o gêmeo: só pelo app."""
    import cache
    from drp.cor_mc import aplicar_cor_mc

    alvo, erro = _alvo(pedido, "clipes", 2000)
    if erro:
        return erro
    _p, tl, clipes = alvo
    pasta = cache.raiz() / cache.RECEBIDOS / "cor_mc"
    fora = aplicar_cor_mc(tl, clipes, str(pasta))
    ok = sum(1 for x in fora if x.get("ok"))
    log.info("cor_mc: %d de %d clipes com a cor do Avid em %r%s", ok, len(fora), tl.GetName(),
             "".join(f" · V{x['trilha']}@{x['quadro']}: {x.get('erro')}" for x in fora if not x.get("ok")))
    return {"ok": True, "aplicadas": ok, "clipes": fora}


def estabilizar(pedido: dict) -> dict:
    """`{nome, uid, clipes: [{trilha, quadro, arquivo, inicio, zoom, u}]}` → o Stabilize do Avid no estabilizador de
    cada clipe (`drp.estabilizador.aplicar_estabilizacao`), DEPOIS da cor e ANTES dos compounds (o clipe de dentro de um
    compound a API não alcança). A casca ainda não tem o gêmeo: só pelo app."""
    import cache
    from drp.estabilizador import aplicar_estabilizacao

    alvo, erro = _alvo(pedido, "clipes", 500)
    if erro:
        return erro
    _p, tl, clipes = alvo
    pasta = cache.raiz() / cache.RECEBIDOS / "estabilizar"
    fora = aplicar_estabilizacao(conectar(), tl, {"estabilizar": clipes}, str(pasta))
    ok = sum(1 for x in fora if x.get("ok"))
    log.info("estabilizar: %d de %d clipes no estabilizador em %r%s", ok, len(fora), tl.GetName(),
             "".join(f" · V{x['trilha']}@{x['quadro']}: {x.get('erro')}" for x in fora if not x.get("ok")))
    return {"ok": True, "aplicadas": ok, "clipes": fora}


def compostos(pedido: dict) -> dict:
    """`{nome, uid, grupos: [{nome, clipes: [{trilha, quadro, arquivo}]}]}` → um Compound Clip por nest, DEPOIS do
    Fusion (`drp.compostos.aplicar_compostos`, o gêmeo de `aplicarCompostos`); a agulha volta ao início."""
    from drp.compostos import aplicar_compostos

    alvo, erro = _alvo(pedido, "grupos", 500)
    if erro:
        return erro
    _p, tl, grupos = alvo
    limpos = []
    for g in grupos:
        clipes = g.get("clipes") if isinstance(g.get("clipes"), list) else []
        limpos.append({"nome": str(g.get("nome") or "Compound Clip")[:200],
                       "clipes": [c for c in clipes[:200] if isinstance(c, dict) and _clipe_valido(c)]
                       if all(isinstance(c, dict) and _clipe_valido(c) for c in clipes[:200]) else []})
    fora = aplicar_compostos(tl, {"compostos": limpos})
    ok = sum(1 for x in fora if x.get("ok"))
    log.info("compostos: %d de %d Compound Clips em %r%s", ok, len(fora), tl.GetName(),
             "".join(f" · {x['nome']}: {x.get('erro')}" for x in fora if not x.get("ok")))
    try:
        tc = tl.GetStartTimecode()
        if tc:
            tl.SetCurrentTimecode(tc)
    except Exception:  # noqa: BLE001 — a agulha é cortesia
        pass
    return {"ok": True, "criados": ok, "grupos": fora}


# ── a conferência pela referência e a prova do bypass (os gêmeos de `conferir*` e `efeitosNoMonitor` da casca) ──

_CONF: dict | None = None        # {tl, pagina, trilhas, ultimo} enquanto a conferência roda
_RE_TC = re.compile(r"^\d\d:\d\d:\d\d[:;]\d\d$")
_RE_JPG = re.compile(r"^\d{1,9}\.jpg$")


def _imagem_confiavel(caminho) -> bool:
    """Só `<cache>/Conferências/<uma conferência>/_interno/<quadro>.jpg` (`imagemConfiavel` da casca)."""
    import conferencia

    if not isinstance(caminho, str) or "\0" in caminho:
        return False
    alvo = Path(caminho).resolve()
    interno, raiz = alvo.parent, Path(conferencia.pasta_raiz()).resolve()
    mesma = (str(interno.parent.parent).lower() == str(raiz).lower()) if _WIN else interno.parent.parent == raiz
    return (mesma and interno.name == conferencia.INTERNO and interno.parent.name not in ("", ".", "..")
            and bool(_RE_JPG.match(alvo.name)))


def _tc_de(q: int, fps: int) -> str:
    s, f = divmod(int(q), fps)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def _provar_bypass(projeto, tl, item):
    """Um clipe: o quadro com a composição dele × com uma vazia por cima. True iguais (bypass ligado), False
    diferentes, None não deu para provar. A vazia sempre sai e a dele volta a ser a ativa (`provarBypass`)."""
    import tempfile
    import uuid

    nossa = (item.GetFusionCompNameList() or [None])[0]
    a = os.path.join(tempfile.gettempdir(), f"dlpc_bypass_{uuid.uuid4()}.jpg")
    b = os.path.join(tempfile.gettempdir(), f"dlpc_bypass_{uuid.uuid4()}.jpg")
    vazia = None
    try:
        meio = item.GetStart() + item.GetDuration() // 2
        tl.SetCurrentTimecode(_tc_de(meio, round(float(tl.GetSetting("timelineFrameRate") or 24))))
        if not projeto.ExportCurrentFrameAsStill(a):
            return None
        item.AddFusionComp()
        nomes = item.GetFusionCompNameList() or []
        if len(nomes) != 2:
            return None
        vazia = nomes[1]
        item.LoadFusionCompByName(vazia)
        if not projeto.ExportCurrentFrameAsStill(b):
            return None
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except Exception as e:  # noqa: BLE001
        log.info("prova do bypass: %s", e)
        return None
    finally:
        try:
            if vazia:
                item.LoadFusionCompByName(nossa)
                item.DeleteFusionCompByName(vazia)
        except Exception as e:  # noqa: BLE001
            log.info("prova do bypass (devolver a composição): %s", e)
        for x in (a, b):
            try:
                os.remove(x)
            except OSError:
                pass


def _efeitos_desligados(projeto, tl):
    """`efeitosDesligadosNoMonitor`: até 3 clipes com UMA composição; um que muda basta para "desligado"."""
    alvos = []
    try:
        for t in range(1, (tl.GetTrackCount("video") or 0) + 1):
            if len(alvos) >= 3:
                break
            if not tl.GetIsTrackEnabled("video", t):
                continue
            for it in tl.GetItemListInTrack("video", t) or []:
                if len(it.GetFusionCompNameList() or []) == 1:
                    alvos.append(it)
                if len(alvos) >= 3:
                    break
    except Exception:  # noqa: BLE001
        return None
    antes = ""
    try:
        antes = tl.GetCurrentTimecode()
    except Exception:  # noqa: BLE001
        pass
    iguais = 0
    try:
        for it in alvos:
            r = _provar_bypass(projeto, tl, it)
            if r is False:
                return False
            if r is True:
                iguais += 1
    finally:
        try:
            if antes:
                tl.SetCurrentTimecode(antes)
        except Exception:  # noqa: BLE001
            pass
    return True if iguais else None


AVISO_BYPASS = ("o monitor do Resolve está com “Bypass Color Grades and Fusion Effects” ligado (o ícone vermelho "
                "riscado no canto do monitor, ou Shift+D): as composições do Fusion — máscara, desfoque, Basic 3D — "
                "não aparecem nem nos quadros exportados. Desligue e confira de novo.")


#: ⛔ MEDIDO no Resolve 21.1 (2026-10-28, banco B050): com um modal aberto (o Project Settings) a API NÃO trava, mas as
#: ESCRITAS voltam None e não fazem nada (SetCurrentTimeline) e o GetCurrentPage volta None — o sinal do diálogo. Antes,
#: o `or "edit"` o escondia e a conferência seguia calada.
_DIALOGO_ABERTO = "há uma janela aberta no Resolve (Project Settings ou um aviso) — feche-a e tente de novo"


def efeitosNoMonitor(pedido: dict) -> dict:  # noqa: N802 — o nome da ponte
    r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    pedido = pedido or {}
    tl = _achar_timeline(p, pedido.get("uid") or "", pedido.get("nome") or "")
    if tl is None:
        return {"ok": False, "erro": f'a timeline "{pedido.get("nome") or ""}" não está neste projeto'}
    pagina = r.GetCurrentPage()
    if pagina is None:
        return {"ok": False, "erro": _DIALOGO_ABERTO}
    ref = pedido.get("trilhaReferencia")
    ref = ref if isinstance(ref, int) else 0
    ref_ligada = 1 <= ref <= (tl.GetTrackCount("video") or 0) and bool(tl.GetIsTrackEnabled("video", ref))
    ligado = None
    try:
        if ref_ligada:
            tl.SetTrackEnable("video", ref, False)
        r.OpenPage("color")
        ligado = _efeitos_desligados(p, tl)
    finally:
        try:
            if ref_ligada:
                tl.SetTrackEnable("video", ref, True)
        except Exception:  # noqa: BLE001
            pass
        try:
            r.OpenPage(pagina)
        except Exception:  # noqa: BLE001
            pass
    log.info("bypass de efeitos no monitor: %s",
             "não deu para provar" if ligado is None else ("LIGADO" if ligado else "desligado"))
    return {"ok": True, "ligado": ligado}


def _conf_devolver() -> None:
    global _CONF
    if not _CONF:
        return
    c, _CONF = _CONF, None
    tl = c["tl"]
    for i, ligada in enumerate(c["trilhas"]):
        try:
            if bool(tl.GetIsTrackEnabled("video", i + 1)) != ligada:
                tl.SetTrackEnable("video", i + 1, ligada)
        except Exception:  # noqa: BLE001
            pass
    try:
        conectar().OpenPage(c["pagina"] or "edit")
    except Exception:  # noqa: BLE001
        pass
    # a régua da Edit fica no último ponto se a agulha for ao início logo depois do OpenPage (casca, 2026-10-04):
    # vai ao último ponto e volta ao início, com a página acordada
    try:
        time.sleep(0.4)
        if c.get("ultimo"):
            tl.SetCurrentTimecode(c["ultimo"])
        time.sleep(0.15)
        tc = tl.GetStartTimecode()
        if tc:
            tl.SetCurrentTimecode(tc)
    except Exception:  # noqa: BLE001
        pass


def conferirInicio(pedido: dict) -> dict:  # noqa: N802
    global _CONF
    r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    pedido = pedido or {}
    tl = _achar_timeline(p, pedido.get("uid") or "", pedido.get("nome") or "")
    if tl is None:
        return {"ok": False, "erro": f'a timeline "{pedido.get("nome") or ""}" não está neste projeto'}
    if _CONF:
        _conf_devolver()                      # uma anterior que ficou pela metade
    pagina = r.GetCurrentPage()
    if pagina is None:
        return {"ok": False, "erro": _DIALOGO_ABERTO}
    p.SetCurrentTimeline(tl)
    n = tl.GetTrackCount("video") or 0
    _CONF = {"tl": tl, "pagina": pagina, "trilhas": [bool(tl.GetIsTrackEnabled("video", t)) for t in range(1, n + 1)]}
    ref = pedido.get("trilhaReferencia")
    if isinstance(ref, int) and 1 <= ref <= n:
        tl.SetTrackEnable("video", ref, False)
    r.OpenPage("color")                         # só na Color o ExportCurrentFrameAsStill funciona (medido)
    if _efeitos_desligados(p, tl) is True:
        _conf_devolver()
        log.info("conferência: parada antes de começar — bypass de efeitos ligado em %r", tl.GetName())
        return {"ok": False, "bypass": True, "erro": AVISO_BYPASS}
    log.info("conferência: começou em %r (referência na V%s)", tl.GetName(), ref or "?")
    return {"ok": True, "nome": tl.GetName()}


def conferirQuadros(pedido: dict) -> dict:  # noqa: N802
    if not _CONF:
        return {"ok": False, "erro": "a conferência não foi iniciada"}
    _r, p = _projeto_aberto()
    tl = _CONF["tl"]
    pontos = (pedido or {}).get("pontos")
    fora = []
    for pt in (pontos if isinstance(pontos, list) else [])[:50]:
        if not isinstance(pt, dict) or not isinstance(pt.get("tc"), str) or not _RE_TC.match(pt["tc"]) \
                or not _imagem_confiavel(pt.get("imagem")):
            fora.append({"quadro": pt.get("quadro") if isinstance(pt, dict) else None, "ok": False,
                         "erro": "ponto recusado"})
            continue
        # logo depois de trocar de página, o 1º SetCurrentTimecode às vezes não pega (casca, 2026-10-04)
        chegou = False
        for i in range(5):
            try:
                tl.SetCurrentTimecode(pt["tc"])
            except Exception:  # noqa: BLE001
                pass
            time.sleep(0.25 if i else 0.06)
            try:
                chegou = tl.GetCurrentTimecode() == pt["tc"]
            except Exception:  # noqa: BLE001
                chegou = False
            if chegou:
                break
        ok = False
        if chegou:
            try:
                ok = bool(p.ExportCurrentFrameAsStill(str(Path(pt["imagem"]).resolve())))
            except Exception as e:  # noqa: BLE001
                log.info("still: %s", e)
            _CONF["ultimo"] = pt["tc"]
        fora.append({"quadro": pt.get("quadro"), "ok": ok,
                     "erro": "" if ok else ("o Resolve não exportou o quadro" if chegou else "a agulha não chegou ao ponto")})
    return {"ok": True, "quadros": fora}


def conferirFim(pedido: dict) -> dict:  # noqa: N802
    tl = _CONF["tl"] if _CONF else None
    pedido = pedido or {}
    marcas, cor, dado = pedido.get("marcas"), pedido.get("cor"), pedido.get("dado")
    postos = 0
    try:
        if tl is not None and isinstance(dado, str) and re.fullmatch(r"[a-z-]{1,40}", dado):
            # conferir de novo: os marcadores da conferência anterior saem (só os nossos, pelo customData)
            for _ in range(5000):
                try:
                    if not tl.DeleteMarkerByCustomData(dado):
                        break
                except Exception:  # noqa: BLE001
                    break
            for m in (marcas if isinstance(marcas, list) else [])[:5000]:
                q = m.get("quadro") if isinstance(m, dict) else None
                if not isinstance(q, int) or q < 0:
                    continue
                try:
                    if tl.AddMarker(q, str(cor or "Purple"), str(m.get("nome") or "DLPC")[:120],
                                    str(m.get("nota") or "")[:500], 1, dado):
                        postos += 1
                except Exception:  # noqa: BLE001
                    pass
    finally:
        _conf_devolver()
    log.info("conferência: %d marcadores; trilhas, página e agulha devolvidas", postos)
    return {"ok": True, "marcadores": postos}


# ── a conferência sobre a timeline COMO ELA ESTÁ (autor, 2026-10-19; `conferencia_timeline.py`) ─────────────────


# ── o ATUALIZAR (portado da casca em 2026-11-25: a casca saiu na Fase 4, `07e2e6e9`, e ele ficou sem casa) ──────────
# O mesmo roteiro de `aplicarAtualizacao` da casca (`plugins/resolve/casca/main.js` no histórico): exportar a timeline
# de trabalho; importar a reescrita; conferir a contagem (senão APAGA a importada e a do colorista fica como estava);
# inserir os planos novos no quadro; conferir o tamanho; a anterior vai para De Lá Pra Cá › Backup (nunca é apagada).
# ⭐ Novo: os planos novos SEM mídia nesta máquina entram OFFLINE no lugar — o serviço escreve o DRT dos rótulos
# (`atualizacao._drt_dos_offline`); importá-lo faz os itens offline nascerem no pool, e o `AppendToTimeline` aceita o
# item offline (medido no Studio 21.1, Mac, 2026-11-25).

def _contar_itens(tl) -> dict:
    fora = {}
    for tipo, letra in (("video", "V"), ("audio", "A")):
        for i in range(1, (tl.GetTrackCount(tipo) or 0) + 1):
            n = len(tl.GetItemListInTrack(tipo, i) or [])
            if n:
                fora[f"{letra}{i}"] = n
    return fora


def _mesma_contagem(a: dict, b: dict) -> bool:
    ka = {k: int(v) for k, v in (a or {}).items() if v}
    kb = {k: int(v) for k, v in (b or {}).items() if v}
    return ka == kb


def _itens_do_pool_por_arquivo(mp) -> dict:
    fora: dict = {}

    def andar(pasta, fundo):
        if pasta is None or fundo > 30:
            return
        for c in pasta.GetClipList() or []:
            try:
                p = c.GetClipProperty("File Path")
                if p and _norma(p) not in fora:
                    fora[_norma(p)] = c
            except Exception:  # noqa: BLE001
                pass
        for f in pasta.GetSubFolderList() or []:
            andar(f, fundo + 1)
    andar(mp.GetRootFolder(), 0)
    return fora


def _item_de_timeline_no_pool(mp, nome):
    achado = []

    def andar(pasta, fundo):
        if pasta is None or fundo > 30 or achado:
            return
        for c in pasta.GetClipList() or []:
            try:
                if c.GetClipProperty("Type") == "Timeline" and c.GetName() == nome:
                    achado.append(c)
                    return
            except Exception:  # noqa: BLE001
                pass
        for f in pasta.GetSubFolderList() or []:
            andar(f, fundo + 1)
    andar(mp.GetRootFolder(), 0)
    return achado[0] if achado else None


def _carimbo() -> str:
    return time.strftime("%d-%m %Hh%M")


def exportarTrabalho(pedido: dict) -> dict:  # noqa: N802 — o nome da ponte
    """A timeline de trabalho do colorista exportada em DRT para `recebidos/<uuid>.drt` (o Comparar e o Atualizar).
    `Timeline.Export` exporta a pedida mesmo sem ser a corrente (medido no 19.1.4, 2026-10-18)."""
    import uuid

    import cache

    uid, nome = (pedido or {}).get("uid"), (pedido or {}).get("nome")
    r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    tl = _achar_timeline(p, uid if isinstance(uid, str) else "", nome if isinstance(nome, str) else "")
    if tl is None:
        return {"ok": False, "erro": f'a timeline "{nome or ""}" não está neste projeto — nada foi alterado'}
    tipo = getattr(r, "EXPORT_DRT", 1)
    destino = cache.sub(cache.RECEBIDOS) / f"{uuid.uuid4()}.drt"
    ok = False
    try:
        ok = bool(tl.Export(str(destino), tipo))
    except Exception as e:  # noqa: BLE001
        log.info("Export: %s", e)
    if not ok or not destino.is_file():
        return {"ok": False, "erro": "o Resolve não exportou a timeline de trabalho"}
    inicio = None                                  # None = não sei (o serviço usa o da Carta); 0 é um início válido
    try:
        q = tl.GetStartFrame()
        if isinstance(q, (int, float)):
            inicio = int(q)
    except Exception:  # noqa: BLE001
        pass
    log.info("exportou a timeline de trabalho %r → %s", tl.GetName(), destino.name)
    return {"ok": True, "drt": str(destino), "contagem": _contar_itens(tl), "inicio": inicio, "nome": tl.GetName()}


def _importar_offline(p, mp, drt: str, nome) -> int:
    """Importa o DRT dos rótulos offline (os itens nascem no pool, na pasta da mídia da timeline) e tira a timeline
    auxiliar dele. Devolve quantos itens offline o pool ganhou."""
    try:
        aux = json.loads(Path(re.sub(r"\.drt$", ".midias.json", drt, flags=re.I)).read_text("utf-8")).get("offline_drt")
    except (OSError, ValueError, AttributeError):
        return 0
    if not isinstance(aux, str) or not aux:
        return 0
    caminho = str(Path(drt).parent / aux)
    if not drt_confiavel(caminho):
        log.warning("DRT dos offline recusado: %s", aux)
        return 0
    antes = len(_itens_do_pool_por_arquivo(mp))
    alvo = _pasta_da_midia(mp, nome)
    if alvo is not None:
        mp.SetCurrentFolder(alvo)
    tl = _importar_drt(p, mp, caminho)
    if tl is None:
        return 0
    try:
        mp.DeleteTimelines([tl])                 # a timeline auxiliar sai; os itens offline ficam no pool
    except Exception as e:  # noqa: BLE001
        log.info("DeleteTimelines (auxiliar dos offline): %s", e)
    return len(_itens_do_pool_por_arquivo(mp)) - antes


def atualizar(pedido: dict) -> dict:
    """`aplicarAtualizacao` da casca, pela API externa (mesmos campos de entrada e de saída)."""
    pedido = pedido or {}
    drt, esperado, antiga = pedido.get("drt"), pedido.get("esperado"), pedido.get("antiga") or {}
    inserir, marcas, nome = pedido.get("inserir"), pedido.get("marcas"), pedido.get("nome")
    marcar, colorir = bool(pedido.get("marcar")), bool(pedido.get("colorir"))
    if not drt_confiavel(drt):
        return {"ok": False, "erro": "arquivo fora da pasta do De Lá Pra Cá — recusado"}
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    mp = p.GetMediaPool()
    velha = _achar_timeline(p, str(antiga.get("uid") or ""), str(antiga.get("nome") or ""))
    if velha is None:
        return {"ok": False, "erro": "a timeline de trabalho sumiu do projeto — nada foi alterado"}
    pedidos = [x for x in inserir[:5000] if isinstance(x, dict)] if isinstance(inserir, list) else []
    offline_novos = _importar_offline(p, mp, drt, nome) if any(x.get("offline") for x in pedidos) else 0
    casa = _pasta_no_pool(mp, "De Lá Pra Cá")
    if casa is not None:
        mp.SetCurrentFolder(casa)
    nova = _importar_drt(p, mp, drt)
    if nova is None:
        return {"ok": False, "erro": "o Resolve não importou a timeline atualizada — nada foi alterado"}
    # ⭐ A conferência depois de importar: a contagem por trilha tem de ser a prevista (um id num formato novo faz a
    # timeline entrar VAZIA, sem erro). Não bateu: apaga a importada.
    contada = _contar_itens(nova)
    if not _mesma_contagem(contada, esperado):
        try:
            mp.DeleteTimelines([nova])
        except Exception as e:  # noqa: BLE001
            log.info("DeleteTimelines: %s", e)
        log.warning("atualizar: contagem %s ≠ prevista %s", contada, esperado)
        return {"ok": False, "erro": "a timeline atualizada não entrou como devia; ela foi descartada e a sua "
                                     "timeline de trabalho ficou como estava"}
    p.SetCurrentTimeline(nova)
    pool = _itens_do_pool_por_arquivo(mp)
    infos, origem, faltaram = [], [], []
    for x in pedidos:
        item = pool.get(_norma(x["arquivo"])) if isinstance(x.get("arquivo"), str) else None
        if item is None:
            faltaram.append(x.get("nome") or x.get("arquivo"))
            continue
        tipo = "audio" if x.get("tipo") == "A" else "video"
        while (nova.GetTrackCount(tipo) or 0) < int(x["trilha"]):
            try:
                if not nova.AddTrack(tipo):
                    break
            except Exception:  # noqa: BLE001
                break
        infos.append({"mediaPoolItem": item, "startFrame": int(x["inicio_fonte"]), "endFrame": int(x["fim_fonte"]),
                      "mediaType": 2 if tipo == "audio" else 1, "trackIndex": int(x["trilha"]),
                      "recordFrame": int(x["quadro"])})
        origem.append(x)
    inseridos = []
    if infos:
        try:
            inseridos = mp.AppendToTimeline(infos) or []
        except Exception as e:  # noqa: BLE001
            log.info("AppendToTimeline: %s", e)
    if faltaram or len(inseridos) < len(infos):
        # Nunca "✓ atualizada" com um buraco onde devia haver um plano: desfaz e a do colorista fica como estava.
        try:
            mp.DeleteTimelines([nova])
        except Exception as e:  # noqa: BLE001
            log.info("DeleteTimelines: %s", e)
        try:
            p.SetCurrentTimeline(velha)
        except Exception:  # noqa: BLE001
            pass
        log.warning("atualizar: %d de %d inseridos, %d sem item no pool — desfeito", len(inseridos), len(infos),
                    len(faltaram))
        return {"ok": False, "erro": f"{len(infos) - len(inseridos) + len(faltaram)} plano(s) novo(s) não entraram "
                f"({', '.join(map(str, faltaram[:5])) or 'o Resolve recusou'}); a atualização foi desfeita e a sua "
                "timeline de trabalho ficou como estava"}
    # O TAMANHO de cada plano que entrou, achado NA TRILHA pelo início (o objeto devolvido para as trilhas 2…n de um
    # grupo de áudio não responde — medido no 21). Nada aqui desfaz: o diferente vai para o editor conferir.
    conferir, da_trilha = [], {}
    for x in origem:
        tipo = "audio" if x.get("tipo") == "A" else "video"
        chave, pedido_q = f"{tipo}{x['trilha']}", int(x["fim_fonte"]) - int(x["inicio_fonte"])
        veio = None
        try:
            if chave not in da_trilha:
                da_trilha[chave] = nova.GetItemListInTrack(tipo, int(x["trilha"])) or []
            achado = next((t for t in da_trilha[chave] if int(t.GetStart()) == int(x["quadro"])), None)
            veio = int(achado.GetDuration()) if achado is not None else None
        except Exception:  # noqa: BLE001
            pass
        rot = f"{x.get('nome') or 'plano novo'} ({x.get('tipo')}{x['trilha']})"
        if veio is None:
            conferir.append(f"{rot}: não achei o plano na trilha depois de inserir — conferir")
        elif veio != pedido_q:
            conferir.append(f"{rot}: entrou com {veio} quadro(s), o Avid tem {pedido_q} — conferir")
    # O backup: a antiga ganha a data no nome e vai para De Lá Pra Cá › Backup. Nunca é apagada.
    nome_velho = velha.GetName()
    _nomear(p, velha, f"{nome_velho} (backup {_carimbo()})")
    backup = velha.GetName()
    pasta_backup = _pasta_no_pool(mp, "Backup", casa) if casa is not None else None
    item_velho = _item_de_timeline_no_pool(mp, backup)
    na_pasta = False
    if pasta_backup is not None and item_velho is not None:
        try:
            na_pasta = bool(mp.MoveClips([item_velho], pasta_backup))
        except Exception as e:  # noqa: BLE001
            log.info("MoveClips backup: %s", e)
    _nomear(p, nova, nome.strip()[:200] if isinstance(nome, str) and nome.strip() else nome_velho)
    p.SetCurrentTimeline(nova)
    # Os Sinais: marcador (a palavra-chave no customData) e a cor LOCAL do item, achado pela trilha e pelo início.
    n_marcas = n_cores = 0
    da_trilha_v: dict = {}
    for m in (marcas[:5000] if (marcar or colorir) and isinstance(marcas, list) else []):
        if not isinstance(m, dict):
            continue
        if marcar:
            try:
                if nova.AddMarker(int(m["quadro"]), m.get("cor_marcador"), m.get("nome") or "", "",
                                  max(1, int(m.get("dur") or 1)), m.get("palavra") or "DLPC"):
                    n_marcas += 1
            except Exception:  # noqa: BLE001 — um marcador que falha não derruba a entrega
                pass
        if colorir:
            try:
                t = int(m["trilha"])
                if t not in da_trilha_v:
                    da_trilha_v[t] = nova.GetItemListInTrack("video", t) or []
                alvo = next((it for it in da_trilha_v[t] if int(it.GetStart()) == int(m["quadro_abs"])), None)
                if alvo is not None and alvo.SetClipColor(m.get("cor_clipe")):
                    n_cores += 1
            except Exception:  # noqa: BLE001
                pass
    uid = ""
    try:
        uid = nova.GetUniqueId() or ""
    except Exception:  # noqa: BLE001
        pass
    n_off = sum(1 for x in origem if x.get("offline"))
    log.info("atualizado: %r (backup %r), %d inseridos (%d offline; %d itens offline novos no pool)", nova.GetName(),
             backup, len(inseridos), n_off, offline_novos)
    return {"ok": True, "nome": nova.GetName(), "uid": uid, "backup": backup, "backup_na_pasta": na_pasta,
            "inseridos": len(inseridos), "pedidos": len(infos), "offline": n_off, "faltaram": faltaram,
            "conferir": conferir, "marcadores": n_marcas, "cores": n_cores}


def _numero(v, padrao=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return padrao


def ler_timeline(pedido: dict) -> dict:
    """A timeline atual como dados: os itens pela API (trilha, início absoluto, duração, entrada na fonte, arquivo,
    desligado, escala/corte/opacidade) e as transições pelo DRT exportado (a API não as descreve). Nada muda nela; a
    timeline aberta antes volta a ser a aberta."""
    import uuid

    from drp import reescrever as RW
    from sessao_receber import _recebidos

    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    pedido = pedido or {}
    tl = _achar_timeline(p, pedido.get("uid") or "", pedido.get("nome") or "")
    if tl is None:
        return {"ok": False, "erro": f'a timeline "{pedido.get("nome") or ""}" não está neste projeto'}
    # ⛔ MEDIDO (Resolve 19.1.4, API externa, 2026-10-19): `GetIsTrackEnabled` devolve False para TODA trilha de uma
    # timeline que não é a aberta (LAB_CORTES_01: [False, False] fechada × [True, False] aberta). Abre-se a timeline
    # antes de ler; a do editor volta no fim (o `finally` abaixo).
    aberta = None
    try:
        aberta = p.GetCurrentTimeline()
    except Exception:  # noqa: BLE001
        pass
    p.SetCurrentTimeline(tl)
    fps = _numero(tl.GetSetting("timelineFrameRate"), 24.0) or 24.0
    leitura = {"ok": True, "nome": tl.GetName(), "uid": tl.GetUniqueId() or "", "inicio": int(tl.GetStartFrame() or 0),
               "fps": fps, "nominal": round(fps),
               "largura": int(_numero(tl.GetSetting("timelineResolutionWidth"), 1920)),
               "altura": int(_numero(tl.GetSetting("timelineResolutionHeight"), 1080)),
               "itens": [], "transicoes": []}
    # Seleção da timeline (igualar as funções do MC/Premiere, 2026-10-25): `so_selecionados` deixa só os clipes que o
    # editor SELECIONOU (`Timeline.GetSelectedClips`, API externa). Casa pela chave (início, duração, nome) — a mesma
    # que o laço monta abaixo (a API não diz a trilha de um item da seleção, então a chave não a inclui). Resolve antigo
    # pode não expor a seleção (marca `selecao_indisponivel`); nada selecionado fica com a lista vazia (o chamador decide).
    # ⚠️ MEDIDO (Resolve 21.1, 2026-10-25): dois itens com MESMO início+duração+nome (ex. par estéreo de áudio em A1/A2)
    #   têm a MESMA chave — selecionar um inclui o gêmeo. É over-inclusão benigna (a conferência confere VÍDEO; nunca
    #   EXCLUI um selecionado) e cobre o caso real (selecionar poucos clipes de vídeo, que não colidem).
    chaves_sel = None
    ref_norma = ""
    if pedido.get("so_selecionados"):
        import conferencia_timeline as CT

        ref_norma = CT._norma(pedido.get("referencia") or "")  # a referência SEMPRE fica, mesmo sem estar selecionada
        try:
            sel = tl.GetSelectedClips()
        except Exception:  # noqa: BLE001 — versão do Resolve sem GetSelectedClips
            sel = None
        if sel is None:
            leitura["selecao_indisponivel"] = True
        else:
            chaves_sel = {(int(c.GetStart()), int(c.GetDuration()), c.GetName() or "") for c in sel}
            leitura["so_selecionados"] = True
            leitura["n_selecionados"] = len(chaves_sel)
    for tipo in ("video", "audio"):
        for t in range(1, (tl.GetTrackCount(tipo) or 0) + 1):
            ligada = bool(tl.GetIsTrackEnabled(tipo, t))
            for it in tl.GetItemListInTrack(tipo, t) or []:
                try:
                    mpi = it.GetMediaPoolItem()
                    arquivo = (mpi.GetClipProperty("File Path") or "") if mpi else ""
                    # só os selecionados — mas a REFERÊNCIA (que a conferência anexa) sempre fica
                    if (chaves_sel is not None
                            and (int(it.GetStart()), int(it.GetDuration()), it.GetName() or "") not in chaves_sel
                            and not (ref_norma and arquivo and CT._norma(arquivo) == ref_norma)):
                        continue
                    # ⚠️ `hasattr` diz sim para QUALQUER nome no objeto da API (é um proxy): chamar e aceitar None
                    clipe_ligado = it.GetClipEnabled()
                    x = {"tipo": tipo, "trilha": t, "start": int(it.GetStart()), "dur": int(it.GetDuration()),
                         "fonte_in": int(it.GetLeftOffset() or 0), "nome": it.GetName() or "", "arquivo": arquivo,
                         "desligado": not ligada or clipe_ligado is False}
                    # um item do pool SEM arquivo é timeline aninhada / composto (medido: o "B22" dentro da
                    # LAB_CORTES_01.Exported.01 2, 2026-10-19): é imagem do filme, não título
                    if mpi and not arquivo:
                        x["composto"] = True
                    if tipo == "video" and arquivo:
                        x["zoom"] = _numero(it.GetProperty("ZoomX"), 1.0)
                        x["opacidade"] = _numero(it.GetProperty("Opacity"), 100.0)
                        x["crop"] = {k: _numero(it.GetProperty(f"Crop{k}"), 0.0)
                                     for k in ("Left", "Right", "Top", "Bottom")}
                        if mpi:
                            x["fps_fonte"] = _numero(mpi.GetClipProperty("FPS"), fps) or fps
                    leitura["itens"].append(x)
                except Exception as e:  # noqa: BLE001 — um item estranho não derruba a leitura
                    log.info("ler_timeline: item ignorado na %s%d: %s", tipo[0].upper(), t, e)
    # as transições: só o DRT exportado as tem (o Export pede a timeline aberta, que já é ela)
    destino = _recebidos() / f"{uuid.uuid4()}.drt"
    try:
        destino.parent.mkdir(parents=True, exist_ok=True)
        r = conectar()
        if tl.Export(str(destino), getattr(r, "EXPORT_DRT", 1) or 1) and destino.is_file():
            leitura["transicoes"] = RW.transicoes(str(destino))
        else:
            log.info("ler_timeline: o Export do DRT falhou — a conferência segue sem as transições")
    except Exception as e:  # noqa: BLE001
        log.info("ler_timeline: transições não lidas (%s)", e)
    finally:
        try:
            if aberta is not None and aberta.GetUniqueId() != tl.GetUniqueId():
                p.SetCurrentTimeline(aberta)
        except Exception:  # noqa: BLE001
            pass
        try:
            destino.unlink()
        except OSError:
            pass
    return leitura


def anexar_referencia(pedido: dict) -> dict:
    """O vídeo de referência indicado pelo painel → uma trilha de vídeo NOVA acima de todas, desligada, do início da
    timeline (o lugar em que ela entraria no import); com `som`, o áudio numa trilha NOVA abaixo de todas, sem solo
    (a API não liga solo: banco `drt-drp/estruturas.md`). Nenhuma trilha do editor é tocada."""
    import conferencia_timeline as CT

    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    pedido = pedido or {}
    arquivo = pedido.get("arquivo")
    if not isinstance(arquivo, str) or "\0" in arquivo or not os.path.isfile(arquivo):
        return {"ok": False, "erro": "o vídeo de referência não está neste computador"}
    tl = _achar_timeline(p, pedido.get("uid") or "", pedido.get("nome") or "")
    if tl is None:
        return {"ok": False, "erro": f'a timeline "{pedido.get("nome") or ""}" não está neste projeto'}
    mp = p.GetMediaPool()
    pasta = _pasta_da_midia(mp, tl.GetName())
    alvo = CT._norma(arquivo)
    mpi = next((c for c in (pasta.GetClipList() or []) if CT._norma(c.GetClipProperty("File Path") or "") == alvo),
               None) if pasta else None
    if mpi is None:
        if pasta:
            mp.SetCurrentFolder(pasta)
        novos = mp.ImportMedia([arquivo]) or []
        mpi = novos[0] if novos else None
    if mpi is None:
        return {"ok": False, "erro": "o Resolve não importou o vídeo de referência"}
    quadros = int(_numero(mpi.GetClipProperty("Frames"), 0))
    if quadros <= 0:
        return {"ok": False, "erro": "o Resolve não informou a duração do vídeo de referência"}
    p.SetCurrentTimeline(tl)
    if not tl.AddTrack("video"):
        return {"ok": False, "erro": "o Resolve não criou a trilha da referência"}
    v = tl.GetTrackCount("video")
    base = {"mediaPoolItem": mpi, "startFrame": 0, "endFrame": quadros, "recordFrame": int(tl.GetStartFrame() or 0)}
    if not mp.AppendToTimeline([{**base, "trackIndex": v, "mediaType": 1}]):
        tl.DeleteTrack("video", v)
        return {"ok": False, "erro": "o Resolve não pôs a referência na timeline"}
    try:
        tl.SetTrackName("video", v, "Referência")
    except Exception:  # noqa: BLE001 — o nome é cortesia
        pass
    tl.SetTrackEnable("video", v, False)
    a = None
    canais = int(_numero(mpi.GetClipProperty("Audio Ch"), 0))
    if pedido.get("som") and canais:
        if tl.AddTrack("audio", "stereo" if canais >= 2 else "mono"):
            a = tl.GetTrackCount("audio")
            if not mp.AppendToTimeline([{**base, "trackIndex": a, "mediaType": 2}]):
                tl.DeleteTrack("audio", a)
                a = None
    log.info("referência anexada a %r: V%d%s", tl.GetName(), v, f" + A{a}" if a else " (sem o som)")
    return {"ok": True, "trilha": v, "trilha_som": a}


# ── o arrasto do Media Pool para a janela do app (2026-10-19) ──────────────────────────────────────────────────────

def timeline_do_arrasto(media_id: str) -> dict:
    """O `MEDIA_ID` que o arrasto do Media Pool carrega (`MediaPool/FusionMedia`) → a timeline. O id é o
    `MediaPoolItem.GetMediaId()` do item da timeline, não o `GetUniqueId()` dela (banco, resolve-scripting/api-scripting.md
    §"Arrastar do Media Pool"); do item à `Timeline`, pelo nome (único no projeto)."""
    if not isinstance(media_id, str) or not re.fullmatch(r"[0-9a-fA-F-]{36}", media_id.strip()):
        return {"ok": False, "erro": "o arrasto não trouxe a identidade do Media Pool"}
    alvo = media_id.strip().lower()
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    achado = None

    def andar(pasta, fundo):
        nonlocal achado
        if pasta is None or fundo > 30 or achado is not None:
            return
        for c in pasta.GetClipList() or []:
            try:
                if (c.GetMediaId() or "").lower() == alvo:
                    achado = c
                    return
            except Exception:  # noqa: BLE001
                pass
        for f in pasta.GetSubFolderList() or []:
            andar(f, fundo + 1)

    andar(p.GetMediaPool().GetRootFolder(), 0)
    if achado is None:
        return {"ok": False, "erro": "não achei no projeto aberto o item arrastado (outro projeto?)"}
    nome = achado.GetName() or ""
    tipo = achado.GetClipProperty("Type") or ""
    tl = next((t for t in _timelines(p) if (t.GetName() or "") == nome), None)
    if tl is None:
        return {"ok": False, "erro": f'"{nome}" não é uma timeline ({tipo or "item do Media Pool"}): arraste uma timeline',
                "nome": nome}
    return {"ok": True, "programa": "resolve", "nome": nome, "uid": tl.GetUniqueId() or "", "projeto": p.GetName() or ""}


def timeline_aberta(pedido: dict | None = None) -> dict:
    """A timeline aberta no Resolve (o "Carregar a sequência aberta" do painel): o mesmo destino do arrasto."""
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    tl = p.GetCurrentTimeline()
    if tl is None:
        return {"ok": False, "erro": "nenhuma timeline aberta no Resolve"}
    return {"ok": True, "programa": "resolve", "nome": tl.GetName() or "", "uid": tl.GetUniqueId() or "",
            "projeto": p.GetName() or ""}


def selecao_da_timeline(pedido: dict | None = None) -> dict:
    """Os clipes SELECIONADOS na timeline aberta do Resolve (igualar as funções do MC/Premiere, 2026-10-25).

    Como `timeline_aberta`, mas confirma que HÁ seleção (`Timeline.GetSelectedClips`, API externa) — a conferência
    depois roda SÓ nesses clipes (`ler_timeline` com `so_selecionados`). Resolve antigo que não expõe a seleção →
    `{ok: False, selecao_indisponivel: True}`; nada selecionado → `{ok: False}` com o motivo. Em ambos o painel cai
    na timeline inteira (`/resolve/timeline-aberta`). Só lê."""
    _r, p = _projeto_aberto()
    if p is None:
        return {"ok": False, "erro": "nenhum projeto aberto no Resolve"}
    tl = p.GetCurrentTimeline()
    if tl is None:
        return {"ok": False, "erro": "nenhuma timeline aberta no Resolve"}
    try:
        sel = tl.GetSelectedClips()
    except Exception:  # noqa: BLE001 — versão do Resolve sem GetSelectedClips
        return {"ok": False, "selecao_indisponivel": True,
                "erro": "esta versão do Resolve não expõe a seleção da timeline"}
    n = len(sel or [])
    if n == 0:
        return {"ok": False, "erro": "nada selecionado na timeline do Resolve — selecione os clipes e tente de novo"}
    return {"ok": True, "programa": "resolve", "nome": tl.GetName() or "", "uid": tl.GetUniqueId() or "",
            "projeto": p.GetName() or "", "so_selecionados": True, "clipes": n}
