"""As rotas da Carta Aberta (C1: o projeto e o registro; a janela é a C2). Plano `docs/plano/2026-11-11-carta-aberta.md`.

⛔⛔ ADR 0005: caminho que vem da página não abre o disco. A raiz do projeto e a pasta de mídia do "anexar" entram
pelo SELETOR do sistema (o gesto do editor); a raiz escolhida fica autorizada no `estado.json` (`carta_projetos`; memória do serviço, não escolha do editor) e só
ela é aceita depois. A `pasta` de dentro do projeto vem da página, mas é conferida contra a raiz
(`referencias.criar` recusa o que sai dela).
"""

from __future__ import annotations

from pathlib import Path

from ..carta import anexar as _anexar
from ..carta import diario as _diario
from ..carta import projeto as _projeto
from ..carta import referencias as _refs
from . import config as _config
from .http import Pedido, Resposta, rota


def _autorizadas() -> list[str]:
    return [str(p) for p in (_config.ler_estado().get("carta_projetos") or []) if isinstance(p, str)]


def _autorizar(raiz: Path) -> None:
    lista = [p for p in _autorizadas() if p != str(raiz)]
    _config.gravar_estado({"carta_projetos": [str(raiz), *lista][:20]})


def _projeto_do_pedido(corpo: dict) -> _projeto.Projeto:
    raiz = str(corpo.get("raiz") or "")
    if raiz not in _autorizadas():
        raise _projeto.CartaErro("este projeto não foi aberto por aqui — use Abrir projeto e escolha a pasta")
    return _projeto.abrir(raiz)


def _escolher_pasta(titulo: str) -> str | None:
    from . import seletor as _seletor
    pastas = _seletor.escolher("pasta", False, [], titulo)
    return pastas[0] if pastas else None


def _conta(c: _anexar.Conta) -> dict:
    return {"novas": c.novas, "ja_estavam": c.ja_estavam, "vinculos": c.vinculos, "empates": c.empates,
            "sem_par": c.sem_par, "ilegiveis": c.ilegiveis, "fora_da_forma": c.fora_da_forma,
            "homonimos": c.homonimos, "voltaram": c.voltaram}


def _resumo(p: _projeto.Projeto) -> dict:
    return {"raiz": str(p.raiz), "nome": p.nome, "taxa": p.taxa}


@rota("POST", "/carta/novo")
def rota_carta_novo(pedido: Pedido) -> Resposta:
    """Nome e taxa vêm da página; o LOCAL, do seletor (o programa não cria pasta nenhuma sozinho)."""
    corpo = pedido.json() or {}
    try:
        raiz = _escolher_pasta("Escolha a pasta (em rede) que vai ser o projeto da Carta Aberta")
        if raiz is None:
            return Resposta.de_json({"ok": True, "cancelado": True})
        p = _projeto.novo(raiz, str(corpo.get("nome") or ""), str(corpo.get("taxa") or ""))
    except Exception as e:  # noqa: BLE001 — CartaErro, SeletorFalhou, OSError: a frase vai ao editor
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    _autorizar(p.raiz)
    return Resposta.de_json({"ok": True, "projeto": _resumo(p)})


@rota("POST", "/carta/abrir")
def rota_carta_abrir(_: Pedido) -> Resposta:
    try:
        raiz = _escolher_pasta("Escolha a pasta do projeto da Carta Aberta")
        if raiz is None:
            return Resposta.de_json({"ok": True, "cancelado": True})
        p = _projeto.abrir(raiz)
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    _autorizar(p.raiz)
    return Resposta.de_json({"ok": True, "projeto": _resumo(p)})


@rota("GET", "/carta/projetos")
def rota_carta_projetos(_: Pedido) -> Resposta:
    out = []
    for raiz in _autorizadas():
        try:
            out.append(_resumo(_projeto.abrir(raiz)))
        except _projeto.CartaErro as e:            # a rede caiu, a pasta mudou: dito, não escondido
            out.append({"raiz": raiz, "erro": str(e)})
    return Resposta.de_json({"projetos": out})


@rota("POST", "/carta/estado")
def rota_carta_estado(pedido: Pedido) -> Resposta:
    """As referências do projeto, cada uma com as formas que tem (e em que máquina)."""
    try:
        p = _projeto_do_pedido(pedido.json() or {})
    except _projeto.CartaErro as e:
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    formas = _diario.formas(p)
    midias = []
    for caminho, d in _refs.todas(p):
        midias.append({"id": d["id"], "nome": d["nome"], "tipo": d.get("tipo", ""),
                       "pasta": str(caminho.parent.relative_to(p.raiz)), "identidade": d["identidade"],
                       "formas": [{k: f.get(k) for k in ("id", "forma", "arquivo", "volume", "relativo", "maquina",
                                                         "por", "ts")} for f in formas.get(d["id"], [])]})
    return Resposta.de_json({"ok": True, "projeto": _resumo(p), "midias": midias})


@rota("POST", "/carta/mandar")
def rota_carta_mandar(pedido: Pedido) -> Resposta:
    """Mandar mídia do NLE para uma pasta do projeto.

    - Premiere: a SELEÇÃO da bin, pela ponte (o arrasto da bin não traz dado; banco `arrastar-e-selecao.md` §6f).
    - Avid: os `mob_ids` (do arrasto para a janela, `arrasto_mac`/`arrasto_win`), achados no acervo da `Avid MediaFiles`.
    """
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        pasta, nle = str(corpo.get("pasta") or ""), str(corpo.get("nle") or "")
        if nle == "premiere":
            from ..nle import premiere as _premiere
            itens = _premiere.selecao()
            arquivos = [i["arquivo"] for i in itens if i.get("arquivo")]
            # ⚠️ Merged, multicâmera, sequência: não são UMA mídia (viram `.item.json`, plano §4.6). Ficam de fora
            #    DITOS, nunca calados (medido 2026-11-12: o merged da seleção sumia da conta).
            sem_arquivo = [str(i.get("nome") or "?") for i in itens if not i.get("arquivo")]
            if not itens:
                return Resposta.de_json({"ok": False, "motivo": "nada selecionado na bin do Premiere"})
            # ⭐ merged, multicâmera e SUBCLIPE: lidos do `.prproj` SALVO pelo nome (a API não diz os arquivos das
            #    trilhas nem a janela do subclipe — o `getInPoint()` devolve o master inteiro); os arquivos deles vão
            #    ANTES, e o item depois. ⚠️ O subclipe TEM arquivo na seleção: sem o projeto salvo, ele iria calado
            #    como a mídia inteira.
            from ..carta import itens as _itens
            prproj = _premiere.projeto_aberto()
            if not (prproj and Path(prproj).suffix.lower() == ".prproj" and Path(prproj).is_file()):
                if not arquivos:
                    return Resposta.de_json({"ok": False, "motivo": "salve o projeto no Premiere: merged e "
                                             "multicâmera são lidos do projeto salvo", "sem_arquivo": sem_arquivo})
                conta = _anexar.mandar_arquivos(p, pasta, arquivos, "trabalho", "premiere")
                return Resposta.de_json({"ok": True, "conta": _conta(conta), "sem_arquivo": sem_arquivo, "itens": None})
            nomes = {str(i.get("nome") or "") for i in itens} - {""}
            # ⭐ O que veio SÓ porque um item o usa entra OCULTO (o fecho da bin do Avid, autor 2026-11-13); o que o
            #    editor selecionou, visível. ⚠️ O arquivo do SUBCLIPE está na seleção mas não é dele: é do master.
            subclipes = _itens.nomes_de_subclipes(prproj)
            visiveis = list(dict.fromkeys(str(i["arquivo"]) for i in itens
                                          if i.get("arquivo") and str(i.get("nome") or "") not in subclipes))
            de_item = [a for a in dict.fromkeys(_itens.arquivos_dos_itens(prproj, nomes) + arquivos) if a not in visiveis]
            conta = _anexar.mandar_arquivos(p, pasta, visiveis, "trabalho", "premiere")
            if de_item:
                extra = _anexar.mandar_arquivos(p, pasta, de_item, "trabalho", "premiere", visivel=False)
                for campo, valor in vars(extra).items():
                    if isinstance(valor, dict):
                        getattr(conta, campo).update(valor)
                    else:
                        getattr(conta, campo).extend(valor)
            c = _itens.do_premiere(p, pasta, prproj, nomes)
            lidos = set(c.novos + c.ja_estavam + list(c.sem_referencia) + list(c.recusados) + list(c.repetidas)
                        + list(c.a_decidir))
            for n in sem_arquivo:
                if n not in lidos:
                    c.recusados[n] = "não é merged nem multicâmera no projeto SALVO (salve o projeto no Premiere)"
            for i in itens:
                n, arq = str(i.get("nome") or ""), str(i.get("arquivo") or "")
                if arq and n not in lidos and n.lower() not in {Path(arq).name.lower(), Path(arq).stem.lower()}:
                    c.avisos[n] = ("foi como a mídia inteira: se é um subclipe novo, salve o projeto no Premiere e "
                                   "mande de novo")
            return Resposta.de_json({"ok": True, "conta": _conta(conta), "itens": vars(c)})
        elif nle == "avid":
            return Resposta.de_json({"ok": True, **_mandar_do_avid(p, pasta, list(corpo.get("mob_ids") or []))})
        else:
            return Resposta.de_json({"ok": False, "motivo": f"NLE desconhecido: {nle!r}"})
    except Exception as e:  # noqa: BLE001 — CartaErro, a ponte, o acervo: a frase vai ao editor
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    return Resposta.de_json({"ok": True, "conta": _conta(conta)})


def _mandar_do_avid(p, pasta: str, mob_ids: list) -> dict:
    """Masters pelo acervo; subclipes, sincronizados e grupos pela BIN (achada pelo MobID, `bins.bins_dos_mobs`), com os
    masters de que dependem mandados ANTES (um item só nasce sobre referências que existem)."""
    from ..avid import bins as _bins
    from ..avid import escopo as _escopo
    from ..carta import itens as _itens
    from ..midia import cache as _cache

    def chave(m):
        try:
            return _cache.de_umid(str(m)).lower()
        except _cache.ChaveInvalida:
            return ""

    clipes = _clipes_do_avid(mob_ids, exigir=False)
    conta = _anexar.mandar_do_avid(p, pasta, clipes)
    resto = {chave(m) for m in mob_ids} - {c.chave.lower() for c in clipes} - {""}
    out = {"conta": _conta(conta), "itens": None}
    if not resto:
        return out
    projeto_mc = _escopo.projeto_aberto()
    if not projeto_mc or projeto_mc == _escopo.SEM_PROJETO:
        out["itens"] = {"recusados": {"?": "abra o projeto no Media Composer: subclipes, grupos e sequências são "
                                           "lidos da bin, e é o projeto aberto que diz em que bin cada um mora"}}
        return out
    soma = _itens.ContaItens()
    quadro = _quadro_do_mc()
    for h, bins in _bins.bins_dos_mobs(projeto_mc, list(resto)).items():
        mandar_itens_da_bin(p, pasta, Path(projeto_mc) / bins[0], {h}, out["conta"], soma, quadro)
        resto.discard(h)
    for h in resto:
        soma.recusados[h] = "não achei este item em nenhuma bin do projeto aberto (salve a bin)"
    out["itens"] = vars(soma)
    return out


def _quadro_do_mc() -> list[int] | None:
    """[largura, altura] do projeto ABERTO no Media Composer (`GetOpenProjectInfo`) — o quadro da timeline que vem dele
    (a sequência do Avid não guarda o próprio; sem ele o Premiere faria a sequência do tamanho da 1ª câmera)."""
    try:
        from ..avid import mcapi as _mcapi
        with _mcapi.MediaComposer() as mc:
            pj = mc.projeto()
        w, h = int(pj.get("largura") or 0), int(pj.get("altura") or 0)
        return [w, h] if w and h else None
    except Exception:  # noqa: BLE001 — sem o MC, a timeline entra sem o quadro (e o Premiere usa o da 1ª câmera)
        return None


def mandar_itens_da_bin(p, pasta: str, caminho: Path, chaves: set[str], conta: dict, soma,
                        quadro: list[int] | None = None) -> None:
    """Os itens (`chaves`, 64 hex) de UMA bin: os masters de que dependem vão ANTES, ocultos (o fecho da bin, autor
    2026-11-13); o master de uma TIMELINE que continua sem forma (o AMA) entra OFFLINE, dito (plano §4.7)."""
    from ..carta import itens as _itens
    c = _itens.do_avid(p, pasta, caminho, mob_ids=chaves, quadro=quadro)
    if c.sem_referencia:                     # os masters do item ainda não estão no projeto: mandar e refazer
        faltam = {k for v in c.sem_referencia.values() for k in v}
        extra = _anexar.mandar_do_avid(p, pasta, _clipes_do_avid(list(faltam), exigir=False), visivel=False)
        for campo, valor in _conta(extra).items():    # empates e homônimos também: o editor tem de vê-los
            if isinstance(valor, dict):
                conta[campo].update(valor)
            else:
                conta[campo] += valor
        c = _itens.do_avid(p, pasta, caminho, mob_ids=chaves, offline=True, quadro=quadro)
    for campo in ("novos", "ja_estavam", "angulos"):
        getattr(soma, campo).extend(getattr(c, campo))
    soma.sem_referencia.update(c.sem_referencia)
    soma.recusados.update(c.recusados)
    soma.avisos.update(c.avisos)
    soma.repetidas.update(c.repetidas)
    soma.a_decidir.update(c.a_decidir)


def _clipes_do_avid(mob_ids: list, exigir: bool = True) -> list:
    """Os masters do Avid pedidos, como `acervo.Clipe` (os N arquivos OP-Atom de cada um). ⚠️ Master que não está em
    nenhuma `Avid MediaFiles` montada não vira referência — e é DITO (`_projeto.CartaErro`)."""
    from ..midia import acervo as _acervo
    from ..midia import cache as _cache
    chaves = {}
    for m in mob_ids:
        try:
            chaves[_cache.de_umid(str(m))] = str(m)
        except _cache.ChaveInvalida:
            continue
    if not chaves:
        if not exigir:
            return []
        raise _projeto.CartaErro("nenhum master do Media Composer neste pedido")
    achados = {}
    for pasta in _acervo.pastas_de_midia():
        for c in _acervo.varrer(pasta):
            if c.chave in chaves:
                achados[c.chave] = c
    faltam = [chaves[k] for k in chaves if k not in achados]
    if faltam and not achados and exigir:
        raise _projeto.CartaErro(f"não achei a mídia de {len(faltam)} master(s) em nenhuma Avid MediaFiles montada")
    return list(achados.values())


@rota("POST", "/carta/entregar")
def rota_carta_entregar(pedido: Pedido) -> Resposta:
    """PUXAR TIMELINE: a timeline `id` da Carta vai ao NLE aberto (hoje o Premiere: XML de timeline importado numa bin,
    `carta/entrega_premiere.py`), apontando a forma pedida (padrão a OP-Atom). Devolve o relatório (o que foi, o que
    ficou de fora e por quê) e o que o Premiere de fato criou — contado lá, nunca pelo retorno do import."""
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        if str(corpo.get("nle") or "premiere") != "premiere":
            return Resposta.de_json({"ok": False, "motivo": "levar timeline ao Media Composer ainda não existe (C4)"})
        from ..carta import entrega_premiere as _entrega
        from ..nle.premiere import ponte as _ponte_premiere
        import time as _time
        destino, rel = _entrega.gravar(p, str(corpo.get("id") or ""), str(corpo.get("forma") or "avid"))
        bin_ = str(corpo.get("bin") or "Carta Aberta")
        antes = {s["id"] for s in (_ponte_premiere.chamar("cicloSequencias", bin_) or {}).get("sequencias", [])}
        r = _ponte_premiere.chamar("cicloImportarTimeline", str(destino), bin_, prazo=600.0)
        # ⚠️ O import de XML pode terminar DEPOIS de o `importFiles` voltar (medido 2026-11-13, 26.0.2 Mac: `true` em
        #    1,4 s e nenhuma sequência na hora): conferir de novo, por um prazo, antes de dizer que não veio.
        t0 = _time.monotonic()
        while not r.get("novas") and _time.monotonic() - t0 < 90:
            _time.sleep(2)
            agora = _ponte_premiere.chamar("cicloSequencias", bin_) or {}
            novas = [s for s in agora.get("sequencias", []) if s["id"] not in antes]
            if novas:
                r = {**r, "novas": novas, "bin": agora.get("bin"), "apareceu_em_s": round(_time.monotonic() - t0, 1)}
        if not r.get("novas"):
            r["depois"] = _ponte_premiere.chamar("cicloSequencias", bin_)
        return Resposta.de_json({"ok": bool(r.get("novas")), "xml": str(destino), "relatorio": rel, "premiere": r,
                                 **({} if r.get("novas") else {"motivo": r.get("erro") or
                                     "o Premiere não criou sequência nenhuma com o XML"})})
    except Exception as e:  # noqa: BLE001 — a frase vai ao editor
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/anexar")
def rota_carta_anexar(pedido: Pedido) -> Resposta:
    """Anexar um formato: a pasta de mídia vem do seletor; `ids` limita às referências escolhidas."""
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        forma = str(corpo.get("forma") or "")
        if forma not in _anexar.FORMAS:
            return Resposta.de_json({"ok": False, "motivo": f"forma desconhecida: {forma!r}"})
        pasta = _escolher_pasta(f"Escolha a pasta da mídia ({forma})")
        if pasta is None:
            return Resposta.de_json({"ok": True, "cancelado": True})
        ids = set(corpo["ids"]) if isinstance(corpo.get("ids"), list) else None
        conta = _anexar.anexar(p, pasta, forma, ids)
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    return Resposta.de_json({"ok": True, "pasta": pasta, "conta": _conta(conta)})


# ── a JANELA (C2): a página, a árvore, o conteúdo, nova pasta, mostrar no Finder/Explorer ──────────────────────────

@rota("POST", "/app/carta")
def rota_app_carta(_: Pedido) -> Resposta:
    """O botão "Carta Aberta". Sem o app (`{"janela": false}`), a página abre em outra aba do navegador."""
    from . import aplicativo
    return Resposta.de_json(aplicativo.chamar("--carta-aberta"))


@rota("GET", "/carta", exige_painel=False)
def rota_carta_pagina(_: Pedido) -> Resposta:
    """A janela da Carta Aberta: navegação de topo, como `/oficina`. Quem lê dados tem porteiro."""
    from .http import DIR_PAINEL
    return Resposta(200, (DIR_PAINEL / "carta.html").read_bytes(), "text/html; charset=utf-8",
                    {"Cache-Control": "no-store"})


@rota("POST", "/carta/arvore")
def rota_carta_arvore(pedido: Pedido) -> Resposta:
    """As pastas do projeto. `abrindo: true` (a janela acabou de abrir o projeto) roda a quarentena e a DIZ."""
    from ..carta import vista as _vista
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        movidos = _projeto.quarentena(p) if corpo.get("abrindo") else []
        pastas = _vista.arvore(p)
    except Exception as e:  # noqa: BLE001 — a rede caiu, a pasta sumiu: a frase vai ao editor
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    return Resposta.de_json({"ok": True, "projeto": _resumo(p), "pastas": pastas,
                             "quarentena": [str(para.relative_to(p.raiz)) for _, para in movidos]})


@rota("POST", "/carta/conteudo")
def rota_carta_conteudo(pedido: Pedido) -> Resposta:
    """As linhas das pastas pedidas (a pasta virtual: várias juntas), só o DIRETO de cada uma."""
    from ..carta import vista as _vista
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        pastas = [str(x) for x in (corpo.get("pastas") or []) if isinstance(x, str)]
        linhas = _vista.conteudo(p, pastas, referenciados=bool(corpo.get("referenciados")))
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    return Resposta.de_json({"ok": True, "linhas": linhas})


@rota("POST", "/carta/pasta")
def rota_carta_pasta(pedido: Pedido) -> Resposta:
    """Nova pasta dentro de `dentro` (o nome é do editor; conferido dentro da raiz)."""
    from ..carta import vista as _vista
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        nova = _vista.nova_pasta(p, str(corpo.get("dentro") or ""), str(corpo.get("nome") or ""))
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    return Resposta.de_json({"ok": True, "pasta": nova})


@rota("POST", "/carta/revelar")
def rota_carta_revelar(pedido: Pedido) -> Resposta:
    """Abre a pasta no Finder/Explorer com os arquivos MARCADOS (`arquivos`: a OP-Atom são N — autor, 2026-11-13: o duplo
    clique marca todos). ⛔ Só caminhos que o DIÁRIO conhece (ADR 0005)."""
    import os
    import subprocess
    import sys

    from ..carta import vista as _vista
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        pedidos = [str(a) for a in (corpo.get("arquivos") or [corpo.get("arquivo") or ""]) if a]
        if not pedidos or not all(_vista.caminho_conhecido(p, a) for a in pedidos):
            return Resposta.de_json({"ok": False, "motivo": "este caminho não é de nenhuma mídia do projeto"})
        existem = [a for a in pedidos if os.path.exists(a)]
        if not existem:
            return Resposta.de_json({"ok": False, "motivo": f"o arquivo não está acessível nesta máquina "
                                     f"(o disco ou a rede pode não estar montado): {pedidos[0]}"})
        if sys.platform == "darwin":
            # ⭐ o Finder marca TODOS (o `open -R` revela um de cada vez); os caminhos vão por argumento, nunca no texto
            script = ('on run argv\nset lista to {}\nrepeat with a in argv\nset end of lista to (POSIX file (a as text)) as alias\n'
                      'end repeat\ntell application "Finder"\nactivate\nreveal lista\nselect lista\nend tell\nend run')
            subprocess.Popen(["osascript", "-e", script, *existem], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif os.name == "nt":
            # ⚠️ o `/select,` marca UM; marcar vários exige `SHOpenFolderAndSelectItems` (matriz, `pendente`)
            subprocess.Popen(f'explorer /select,"{existem[0]}"', stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            subprocess.Popen(["xdg-open", os.path.dirname(existem[0])])
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})
    return Resposta.de_json({"ok": True, "marcados": len(existem)})


# ── C2 parte 2: remover, mover e as pastas (decisões do autor de 2026-11-13; `carta/vitrine.py`) ──────────────────

def _gesto(pedido: Pedido, faz) -> Resposta:
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        return Resposta.de_json({"ok": True, **faz(p, corpo)})
    except Exception as e:  # noqa: BLE001 — CartaErro, OSError (a rede, outro editor mexendo): a frase vai ao editor
        return Resposta.de_json({"ok": False, "motivo": str(e)})


def _ids(corpo: dict) -> list[str]:
    return [str(i) for i in (corpo.get("ids") or []) if isinstance(i, str)]


@rota("POST", "/carta/remover")
def rota_carta_remover(pedido: Pedido) -> Resposta:
    """Some da VISTA (vai para a área oculta). Nenhum arquivo de mídia é tocado; quem usa continua usando."""
    from ..carta import vitrine
    return _gesto(pedido, lambda p, c: vitrine.remover(p, _ids(c)))


@rota("POST", "/carta/mover")
def rota_carta_mover(pedido: Pedido) -> Resposta:
    from ..carta import vitrine
    return _gesto(pedido, lambda p, c: vitrine.mover(p, _ids(c), str(c.get("pasta") or "")))


@rota("POST", "/carta/pasta/renomear")
def rota_carta_pasta_renomear(pedido: Pedido) -> Resposta:
    from ..carta import vitrine
    return _gesto(pedido, lambda p, c: {"pasta": vitrine.renomear_pasta(p, str(c.get("pasta") or ""), str(c.get("nome") or ""))})


@rota("POST", "/carta/pasta/mover")
def rota_carta_pasta_mover(pedido: Pedido) -> Resposta:
    from ..carta import vitrine
    return _gesto(pedido, lambda p, c: {"pasta": vitrine.mover_pasta(p, str(c.get("pasta") or ""), str(c.get("para") or ""))})


@rota("POST", "/carta/pasta/remover")
def rota_carta_pasta_remover(pedido: Pedido) -> Resposta:
    from ..carta import vitrine
    return _gesto(pedido, lambda p, c: vitrine.remover_pasta(p, str(c.get("pasta") or "")))


# ── a lista "A decidir" (empates e homônimos guardados no diário; `carta/decidir.py`) ──────────────────────────────

@rota("POST", "/carta/decidir")
def rota_carta_decidir(pedido: Pedido) -> Resposta:
    from ..carta import decidir
    return _gesto(pedido, lambda p, c: {"casos": [
        {k: x.get(k) for k in ("id", "caso", "nome", "pasta", "candidatos", "porque", "maquina", "ts", "arquivo",
                                       "onde", "versao", "antes", "agora")}
        for x in decidir.pendentes(p)]})


@rota("POST", "/carta/decidir/responder")
def rota_carta_decidir_responder(pedido: Pedido) -> Resposta:
    from ..carta import decidir
    return _gesto(pedido, lambda p, c: decidir.responder(p, str(c.get("pendente") or ""), str(c.get("resposta") or "")))


@rota("GET", "/carta/miniatura")
def rota_carta_miniatura(pedido: Pedido) -> Resposta:
    """A miniatura de uma linha (`?raiz=…&id=…`): o JPEG, ou 404 (a linha fica sem ela). ⛔ Só o `id` de uma referência
    ou item do projeto, e só um arquivo que o DIÁRIO conhece: nada da URL vira caminho (ADR 0005)."""
    from ..carta import miniatura
    try:
        p = _projeto_do_pedido({"raiz": pedido.consulta.get("raiz", "")})
        a = miniatura.alvo(p, pedido.consulta.get("id", ""))
        dados = miniatura.gerar(*a) if a else None
    except Exception:  # noqa: BLE001 — sem miniatura não é erro
        dados = None
    if not dados:
        return Resposta(404, b'{"erro":"sem miniatura"}')
    return Resposta(200, dados, "image/jpeg", {"Cache-Control": "private, max-age=3600"})


@rota("POST", "/carta/premiere/preparar")
def rota_carta_premiere_preparar(pedido: Pedido) -> Resposta:
    """Passo 1 do enxerto (`carta/entrega_prproj.py`): abre (ou cria) o projeto de entrega `prproj` no Premiere e
    importa NELE, um arquivo por chamada, a mídia da timeline `id` (`trilhas`: só estas, ex. ["V1"]). Para no primeiro
    arquivo que não voltar no prazo, e diz qual. ⛔ `prproj` tem de ser um arquivo NOVO ou de entrega: nunca o do editor."""
    import time as _time
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        from ..carta import entrega_prproj as _ep, itens as _itens
        from ..nle.premiere import ponte as _ponte_premiere
        from .. import premiere_app as _app
        item = next((d for _, d in _itens.todos(p) if d["id"] == str(corpo.get("id") or "")), None)
        if item is None:
            return Resposta.de_json({"ok": False, "motivo": "não achei esta timeline no projeto"})
        trilhas = set(corpo["trilhas"]) if isinstance(corpo.get("trilhas"), list) else None
        arquivos, offline = _ep.arquivos_da_timeline(p, item, str(corpo.get("forma") or "avid"), trilhas)
        if isinstance(corpo.get("arquivos"), list):  # desenvolvimento: medir com uma lista curta, só dos da timeline
            pedidos = {str(a) for a in corpo["arquivos"]}
            arquivos = [a for a in arquivos if a in pedidos]
        prproj = str(corpo.get("prproj") or "")
        if not prproj.endswith(".prproj"):
            return Resposta.de_json({"ok": False, "motivo": "falta o caminho do projeto de entrega (.prproj)"})
        Path(prproj).parent.mkdir(parents=True, exist_ok=True)
        aberto = _app.abrir(prproj)
        bin_ = str(corpo.get("bin") or "Carta Aberta/Mídia")
        prazo = float(corpo.get("prazo") or 180)
        feitos = []
        for a in arquivos:
            t0 = _time.monotonic()
            try:
                r = _ponte_premiere.chamar("cicloImportar", f"bin\t{bin_}\narq\t{a}\t\n", prazo=prazo)
                f = (r or {}).get("feitos") or [{}]
                feitos.append({"arquivo": a, "s": round(_time.monotonic() - t0, 1), **f[0]})
            except Exception as e:  # noqa: BLE001 — o arquivo que travou é a resposta
                feitos.append({"arquivo": a, "s": round(_time.monotonic() - t0, 1), "travou": str(e)})
                break
        salvo = None
        if not any("travou" in f for f in feitos):
            salvo = _ponte_premiere.chamar("cicloSalvar", prazo=120.0)
        return Resposta.de_json({"ok": all("erro" not in f and "travou" not in f for f in feitos)
                                 and len(feitos) == len(arquivos),
                                 "premiere": aberto, "arquivos": len(arquivos), "feitos": feitos,
                                 "offline": offline, "salvo": salvo})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/premiere/molde")
def rota_carta_premiere_molde(pedido: Pedido) -> Resposta:
    """DESENVOLVIMENTO do enxerto: o Premiere monta uma sequência curta (`plano` do `cicloMontar`) no projeto aberto e
    salva — o MOLDE de como o 26.x guarda sequência, trilha e clipe, lido de volta no `.prproj` (nunca adivinhado)."""
    corpo = pedido.json() or {}
    try:
        from ..nle.premiere import ponte as _ponte_premiere
        r = _ponte_premiere.chamar("cicloMontar", str(corpo.get("plano") or ""), prazo=120.0)
        s = _ponte_premiere.chamar("cicloSalvar", prazo=120.0)
        return Resposta.de_json({"ok": "erro" not in (r or {}), "montar": r, "salvo": s})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/premiere/bin")
def rota_carta_premiere_bin(pedido: Pedido) -> Resposta:
    """A bin em que o Premiere poria um item novo — o DESTINO do "Importar" (a selecionada, ou a aberta por último)."""
    try:
        from ..nle.premiere import ponte as _ponte_premiere
        return Resposta.de_json({"ok": True, **(_ponte_premiere.chamar("cicloBinDeInsercao", prazo=30.0) or {})})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/premiere/importar")
def rota_carta_premiere_importar(pedido: Pedido) -> Resposta:
    """O "Importar para o Premiere" de uma TIMELINE (`id`) no projeto ABERTO do editor (`carta/importar_premiere.py`).
    `quadro`: [largura, altura] da sequência (sem ele, o do 1º clipe de imagem)."""
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        from ..carta import importar_premiere as _imp, itens as _itens
        from ..nle.premiere import ponte as _ponte_premiere
        item = next((d for _, d in _itens.todos(p) if d["id"] == str(corpo.get("id") or "")), None)
        if item is None or not item.get("timeline"):
            return Resposta.de_json({"ok": False, "motivo": "não achei esta timeline no projeto"})
        q = corpo.get("quadro") or item.get("quadro")      # o do pedido (bancada) ou o do projeto do Avid
        quadro = (int(q[0]), int(q[1])) if isinstance(q, list) and len(q) == 2 else None
        rel = _imp.importar_timeline(p, item, _ponte_premiere.chamar, quadro=quadro,
                                     forma=str(corpo.get("forma") or "avid"),
                                     modelo=str(corpo["modelo"]) if corpo.get("modelo") else None,  # desenvolvimento
                                     transcricao=(bool(corpo["transcricao_vazia"])        # desenvolvimento: força
                                                  if "transcricao_vazia" in corpo else None))
        # ⭐ "o que ficou de fora vai no REGISTRO, não num diálogo" (autor, 2026-11-14): o diário do projeto
        esc = rel.get("escrita") or {}
        _diario.acrescentar(p, {"fato": "importado", "item": item["id"], "nle": "premiere",
                                "projeto_nle": rel.get("editor"), "bin": rel.get("bin"),
                                "clipes": esc.get("clipes"), "transicoes": esc.get("transicoes"),
                                "merged": esc.get("merged"), "subclipes": esc.get("subclipes"),
                                "offline": esc.get("offline"), "fora": esc.get("fora"),
                                "merged_fora": esc.get("merged_fora"), "moldes_fora": rel.get("moldes_fora"),
                                "midia_recusada": rel.get("midia_recusada"), "marcadores": rel.get("marcadores")})
        return Resposta.de_json({"ok": True, **rel})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


# ── o BASELIGHT (etapa 3 da proposta 2026-11-22-baselight-no-app): ele só recebe ──────────────────────────────────

@rota("POST", "/carta/baselight/jobs")
def rota_carta_baselight_jobs(pedido: Pedido) -> Resposta:
    """Os jobs do Baselight desta máquina (a escolha do job da produção) e o job sugerido (o nome do projeto)."""
    corpo = pedido.json() or {}
    try:
        from ..carta import entrega_baselight as _bl
        r = _bl.jobs()
        try:
            r["sugerido"] = _projeto_do_pedido(corpo).nome
        except _projeto.CartaErro:
            r["sugerido"] = ""
        return Resposta.de_json({"ok": True, **r})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


def _item_timeline(p, corpo: dict) -> dict:
    from ..carta import itens as _itens
    item = next((d for _, d in _itens.todos(p) if d["id"] == str(corpo.get("id") or "")), None)
    if item is None or not item.get("timeline"):
        raise _projeto.CartaErro("não achei esta timeline no projeto")
    return item


@rota("POST", "/carta/baselight/importar")
def rota_carta_baselight_importar(pedido: Pedido) -> Resposta:
    """"Importar timeline" no Baselight: as mídias da Carta (sem casar), numa scene NOVA do job, conferida plano a plano."""
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        item = _item_timeline(p, corpo)
        from ..carta import entrega_baselight as _bl
        r = _bl.importar(p, item["id"], str(corpo.get("job") or ""), markers=corpo.get("markers") is not False)
        _diario.acrescentar(p, {"fato": "importado", "item": item["id"], "nle": "baselight", "job": r.get("job"),
                                "scene": r.get("scene"), "contagem": r.get("contagem"), "trocados": r.get("trocados"),
                                "markers": r.get("markers")})
        return Resposta.de_json({"ok": True, **{k: v for k, v in r.items() if k != "xmeml"}})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/baselight/conformar")
def rota_carta_baselight_conformar(pedido: Pedido) -> Resposta:
    """"Conformar com De Lá Pra Cá": o pedido para o painel do Conformar e o app trocando para a aba dele."""
    corpo = pedido.json() or {}
    try:
        p = _projeto_do_pedido(corpo)
        item = _item_timeline(p, corpo)
        from ..carta import entrega_baselight as _bl
        from . import aplicativo
        r = _bl.pedir_conform(p, item["id"], str(corpo.get("job") or ""))
        return Resposta.de_json({"ok": True, "nome": r["nome"], "job": r["job"],
                                 "janela": aplicativo.chamar("--conformar")})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


#: acao → (função do host.jsx, leva o caminho?)
_ACOES_DE_PROJETO = {"listar": ("cicloProjetosAbertos", False), "abrir": ("cicloAbrirProjeto", True),
                     "fechar": ("cicloFecharProjeto", True), "ativar": ("cicloAtivarProjeto", True),
                     "salvar": ("cicloSalvar", False), "importar_juntos": ("cicloImportarJuntos", True),
                     "importar_projeto": ("cicloImportarProjeto", True),   # bancada: provar um projeto-modelo
                     "importar_plano": ("cicloImportar", True),   # bancada: o `caminho` é o PLANO (bin/arq tabulado)
                     "carregar_no_source": ("cicloCarregarNoSource", True),   # bancada: o `caminho` é o NOME do item
                     "abrir_sequencia": ("cicloAbrirSequencia", True),   # bancada: o `caminho` é o id ou o nome
                     "tipos_de_midia": ("cicloTiposDeMidia", True)}   # bancada: o `caminho` é a bin ("" = tudo)


@rota("POST", "/carta/premiere/projetos")
def rota_carta_premiere_projetos(pedido: Pedido) -> Resposta:
    """Os projetos ABERTOS no Premiere (`acao`: listar · abrir · fechar · ativar · salvar o ativo) — o "Importar para o
    Premiere" abre a cópia de trabalho ao lado do projeto do editor e volta a ele no fim."""
    corpo = pedido.json() or {}
    acao = str(corpo.get("acao") or "listar")
    if acao not in _ACOES_DE_PROJETO:
        return Resposta.de_json({"ok": False, "motivo": f"ação desconhecida: {acao}"})
    funcao, com_caminho = _ACOES_DE_PROJETO[acao]
    try:
        from ..nle.premiere import ponte as _ponte_premiere
        args = (str(corpo.get("caminho") or ""),) if com_caminho else ()
        return Resposta.de_json({"ok": True, **(_ponte_premiere.chamar(funcao, *args, prazo=180.0) or {})})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/premiere/importar_sequencias")
def rota_carta_premiere_importar_sequencias(pedido: Pedido) -> Resposta:
    """Traz as sequências `uids` do `.prproj` `prproj` (o enxerto) para o projeto aberto, e conta o projeto antes e depois."""
    corpo = pedido.json() or {}
    try:
        from ..nle.premiere import ponte as _ponte_premiere
        return Resposta.de_json({"ok": True, **(_ponte_premiere.chamar(
            "cicloImportarSequencias", str(corpo.get("prproj") or ""), ",".join(corpo.get("uids") or []),
            prazo=600.0) or {})})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})


@rota("POST", "/carta/premiere/ler")
def rota_carta_premiere_ler(pedido: Pedido) -> Resposta:
    """A sequência `ref` (id ou nome) do projeto aberto no Premiere, clipe a clipe em ticks — a conferência da entrega
    é o que o Premiere LÊ, nunca o arquivo que escrevemos."""
    corpo = pedido.json() or {}
    try:
        from ..nle.premiere import ponte as _ponte_premiere
        return Resposta.de_json({"ok": True, **(_ponte_premiere.chamar(
            "cicloLerSequencia", str(corpo.get("ref") or ""), "1" if corpo.get("detalhe") else "0",
            prazo=600.0 if corpo.get("detalhe") else 120.0) or {})})
    except Exception as e:  # noqa: BLE001
        return Resposta.de_json({"ok": False, "motivo": str(e)})
