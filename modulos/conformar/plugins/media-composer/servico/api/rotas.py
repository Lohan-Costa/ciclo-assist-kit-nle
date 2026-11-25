"""As rotas do serviço.

Divididas por custo, e isso não é detalhe de organização:

- **baratas** (`/health`) não falam com o Media Composer;
- **sob demanda** (`/mc/*`) falam, e cada chamada custa ~500 ms de piso;
- **longas** (`/trabalho/*`) disparam thread e devolvem na hora, com o andamento em
  `/progresso`.
"""

from __future__ import annotations

import json
import os
import subprocess
import logging
import threading
from pathlib import Path

from media.safepath import CaminhoInvalido

from .portao import ROTA_UI
from .servidor import rota, servir_arquivo_da_ui

log = logging.getLogger("delapraca.rotas")

# O que sabemos ler como timeline. `xml` está aqui de propósito, mesmo antes de haver
# leitor: é o próximo formato previsto, e deixar o filtro pronto evita que o suporte
# chegue e o seletor continue recusando o arquivo.
EXTENSOES_TIMELINE = ("aaf", "avb", "prproj")   # a bin de fora (outra máquina, outro projeto, o Magic Link) — 2026-10-12;
#   o .prproj desde 2026-11-24 (o soltar já o aceitava desde 2026-10-25; o "clique para escolher" recusava)


# ── básicas ─────────────────────────────────────────────────────────────────

@rota("GET", "/health")
def health(ctx):
    """A batida do loader, a cada 4 s. Barata de propósito.

    ⚠️ NÃO fala com o Media Composer aqui. Toda chamada ao MC tem piso de ~500 ms, e
    uma batida de 4 s que gasta meio segundo do laço do MC é um imposto permanente sobre
    o editor. Quem quer saber do MC pergunta em `/mc/info`, sob demanda.
    """
    return 200, {
        "ok": True,
        "app": "De Lá Pra Cá",
        "nle": "avid",
        "versao": ctx.servico.versao,
        "ui": ROTA_UI,
        "ocupada": ctx.servico.sessao.ocupada,
    }


@rota("GET", "/prontidao")
def prontidao(ctx):
    """O motor está PRONTO (não só no ar)? O painel esconde as opções até `ok` (autor, 2026-10-04:
    o Importar inteiro feito com o motor sem ffprobe, e a timeline toda offline no fim). `?forcar=1`
    = o botão "Conferir de novo"."""
    import prontidao as P
    forcar = "forcar=1" in (ctx.query or "")
    return 200, P.conferir(ctx.servico, forcar=forcar)


@rota("POST", "/receber/motor/ceder")
def motor_ceder(ctx):
    """O APP pede a porta: um motor SEM app (o órfão que uma casca antiga subiu) encerra para o app
    subir o dele (autor, 2026-10-04 — memória `app-obrigatorio-ordem-nao-importa`). Um motor do app
    recusa (dois apps abertos não brigam pela porta), e nenhum encerra no meio de um trabalho."""
    import threading
    s = ctx.servico
    if getattr(s, "app_exe", None):
        return 409, {"erro": "este motor é de um aplicativo aberto"}
    if s.sessao.ocupada:
        return 409, {"erro": "o motor está no meio de um trabalho"}
    parar = getattr(s, "parar", None)
    if parar is None:
        return 409, {"erro": "este motor não sabe encerrar"}
    log.info("o aplicativo pediu a porta: este motor (sem app) encerra")
    threading.Timer(0.3, parar.set).start()        # responde antes de encerrar
    return 200, {"ok": True}


@rota("GET", ROTA_UI)
def painel(ctx):
    """Serve a interface. É a única rota de HTML — ver `portao.py` sobre por que ela
    não carrega segredo embutido."""
    return servir_arquivo_da_ui("painel.html")


@rota("GET", "/static/painel.js")
def static_js(ctx):
    return servir_arquivo_da_ui("painel.js")


@rota("GET", "/static/painel.css")
def static_css(ctx):
    return servir_arquivo_da_ui("painel.css")


# ── o Media Composer, sob demanda ───────────────────────────────────────────

@rota("GET", "/mc/info")
def mc_info(ctx):
    """Estado do MC. Custa ~1,5 s (três chamadas) — por isso não vive no `/health`."""
    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 200, {"aberto": False}
        resposta = {"aberto": True}
        for chave, fn in (("app", mc.info), ("projeto", mc.projeto)):
            try:
                resposta[chave] = fn()
            except Exception as e:  # noqa: BLE001
                resposta[f"{chave}_erro"] = str(e)
        return 200, resposta


@rota("GET", "/mc/sequences")
def mc_sequences(ctx):
    """As sequences das bins que o editor **já tem abertas**.

    ⚠️⚠️ **Nunca varra o projeto inteiro aqui.** `OpenBin` tem efeito VISÍVEL: abre a
    bin na tela. Uma varredura atrás de sequences cobre o Media Composer de bins que
    ninguém pediu — foi o que aconteceu na primeira versão desta rota, e é o mesmo
    defeito que o Órbita já teve. O editor clica num seletor e a interface dele explode.

    Por isso a lista sai de `bins_abertas()`: o que está aberto é o que ele está
    olhando, e é de lá que sai a timeline que ele quer relinkar. Uma bin fechada não
    aparece — e está certo assim: para relinká-la, ele a abre, que é o gesto natural.

    A seleção vem marcada (`selecionada`), para o painel já vir com ela escolhida.

    ## ⚠️ Quando o Media Composer não sabe dizer quais bins estão abertas

    `GetListOfWindows` **não existe no MC 25.6** (existe no 25.12). Sem ele, esta rota
    não pode filtrar — e a única resposta errada seria concluir "nenhuma bin aberta",
    que devolveria um seletor VAZIO com o projeto inteiro na tela.

    Então perguntamos a **todas** as bins do projeto. É seguro: `GetListOfBinItems`
    numa bin fechada **falha** com `"Bin is not open."` em vez de abri-la, então a tela
    do editor continua como estava. Custa ~500 ms por bin, e por isso a passada de
    pré-seleção é **pulada** neste modo: perder o destaque é uma conveniência a menos;
    dobrar o tempo de abertura do painel seria um defeito.
    """
    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 200, {"aberto": False, "bins": []}

        # ⚠️ `bins_abertas()` devolve o nome SEM extensão ('RELINK COMPLETO'), e
        # `bin_relative_path` exige COM ('RELINK COMPLETO.avb'). Sem o `.avb` a resposta
        # é `"Bin is not open."` — a mesma mensagem que a bin realmente fechada dá, e
        # que manda depurar o estado quando o problema é a forma do nome.
        nomes_abertos = mc.bins_abertas()
        sabemos = nomes_abertos is not None
        if sabemos:
            candidatas = [n if n.lower().endswith(".avb") else f"{n}.avb"
                          for n in nomes_abertos]
        else:
            log.info("esta versão do MC não lista janelas — perguntando a todas as bins")
            candidatas = [mc.caminho_relativo_da_bin(c) for c in mc.bins()]

        selecionados = set()
        for nome in candidatas if sabemos else ():
            try:
                # `only_selected_flag` filtra DENTRO do MC — é o que o editor destacou.
                for item in mc.itens_da_bin(nome, flags=("sequences",),
                                            apenas_selecionados=True):
                    if item.mob_id:
                        selecionados.add(item.mob_id)
            except Exception as e:  # noqa: BLE001
                log.debug("seleção de %r não veio: %s", nome, e)

        bins = []
        for nome in candidatas:
            try:
                seqs = mc.itens_da_bin(nome, flags=("sequences",))
            except Exception as e:  # noqa: BLE001
                log.debug("bin %r não respondeu: %s", nome, e)
                continue
            if seqs:
                bins.append({
                    "bin": Path(nome).stem,
                    "sequences": [{"nome": s.name, "mob_id": s.mob_id,
                                   "selecionada": s.mob_id in selecionados}
                                  for s in seqs],
                })
        return 200, {"aberto": True, "bins": bins}


@rota("POST", "/mc/mob")
def mc_mob(ctx):
    """Nome e colunas de um mob, pelo MobID. **É o que fecha o arrasto.**

    Quando o editor arrasta uma timeline da bin para o painel, o payload do drop traz
    `id` e `type` — mas **não traz o nome**. E o nome não é enfeite: ele vira o arquivo
    do export e o nome da bin que o relink entrega.

    Uma chamada de `GetMobInfo` (~500 ms) resolve, e o custo é justo: é um gesto
    deliberado do editor, não um laço. Compare com a alternativa que este atalho
    substitui — `/mc/sequences`, que no MC 25.6 (sem `GetListOfWindows`) pergunta a
    **todas** as bins do projeto, a ~500 ms cada.
    """
    from avid.mcapi import mob_id_valido

    mob_id = (ctx.json().get("mob_id") or "").strip()
    if not mob_id_valido(mob_id):
        # ⚠️ A mensagem diz o que se esperava, porque o formato do MobID varia de
        # superfície e essa é exatamente a confusão que se quer evitar aqui.
        return 400, {"erro": "MobID inválido — esperava 64 dígitos hexadecimais"}

    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 409, {"erro": "o Media Composer não respondeu"}
        try:
            colunas = mc.colunas_do_master(mob_id)
        except Exception as e:  # noqa: BLE001
            return 409, {"erro": str(e)}

    # ⚠️ NENHUMA coluna = o mob não existe neste projeto. O `GetMobInfo` **não levanta**
    # nesse caso: ele devolve um fluxo vazio, e um 200 aqui faria o painel seguir para o
    # export de um mob inexistente — erro que só apareceria lá na frente, longe da causa.
    # Medido: um MobID inventado devolve `{}` com o Media Composer aberto e respondendo.
    if not colunas:
        return 404, {"erro": "o Media Composer não conhece esse mob — ele ainda está "
                             "no projeto aberto?"}

    nome = (colunas.get("Name") or "").strip()
    if not nome:
        # Um mob COM colunas mas sem `Name` é outra história: existe, e o nome só decide
        # rótulo e nome de arquivo. Seguir sem ele é melhor que recusar.
        log.info("mob %s não trouxe coluna Name (colunas: %s)", mob_id, list(colunas))
    return 200, {"mob_id": mob_id, "nome": nome, "colunas": colunas}


@rota("POST", "/mc/selecao")
def mc_selecao(ctx):
    """"Carregar a seleção da timeline" (autor, 2026-10-25): os clipes SELECIONADOS na timeline → a sequência do
    Record + os masters deles, para o relink tocar só neles (`relink.filtrar_masters(so_masters=)`).

    A API não lê a seleção nem o arrasto a entrega (no Mac o arrasto da timeline não sai do MC — banco,
    avid-panel-sdk/arrastar.md): a seleção sai pela CÓPIA do editor, a receita medida do Coletar
    (`coleta.capturar`: Cmd+0 → Cmd+C → "Clipboard Contents" → subsequência numa bin → leitura da `.avb`). O clique foi
    na janela do app, então o MC vem para a frente antes (`trazer_mc`). ⚠️ A cópia do Avid é o TRECHO: em cada trilha,
    do primeiro ao último segmento selecionado, com o que houver entre eles.
    """
    import coleta

    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 200, {"ok": False, "erro": "o Media Composer não respondeu"}
        try:
            sequencia, copia, _ = coleta.capturar(mc, trazer_mc=True)
        except coleta.ColetaFalhou as e:
            return 200, {"ok": False, "erro": str(e)}
        try:
            colunas = mc.colunas_do_master(sequencia["mob_id"])
        except Exception:  # noqa: BLE001 — as colunas só enfeitam o cartão
            colunas = {}
    segs = [s for s in copia.get("segments") or [] if s.get("mob_id")]
    masters = list(dict.fromkeys(str(s["mob_id"]) for s in segs))
    if not masters:
        return 200, {"ok": False, "erro": "a seleção copiada não tem clipes — selecione os segmentos na timeline"}
    info = copia.get("masters") or {}
    nomes = sorted({(info.get(m) or {}).get("nome") or "" for m in masters} - {""})
    # o cartão mostra a SELEÇÃO, não a sequência (autor, 2026-10-25: com a duração e as trilhas da sequência inteira
    # "é como se eu tivesse carregado a sequência toda"): o trecho na timeline e as trilhas tocadas
    trilhas = sorted({(1, s["track"] - 999) if s.get("is_audio") else (0, s["track"]) for s in segs})
    return 200, {"ok": True, "mob_id": sequencia["mob_id"], "nome": sequencia.get("nome") or colunas.get("Name", ""),
                 "colunas": colunas, "masters": masters, "nomes": nomes, "clipes": len(segs),
                 "entrada": min(s["timeline_tc_in"] for s in segs), "saida": max(s["timeline_tc_out"] for s in segs),
                 "trilhas": [("A%d" if a else "V%d") % n for a, n in trilhas]}


@rota("POST", "/mc/selecao-aro")
def mc_selecao_aro(ctx):
    """"Carregar a seleção da timeline" pelo ARO — o 2º caminho, SEM flicker (autor não gosta do piscar do Cmd+C).

    A dylib do ARO (`tools/aro/aro_servidor.c`) lê a seleção POR DENTRO do MC e dá o MobID da FONTE de cada segmento
    (`ASourceClip::GetSrcMobID`; `servico/aro.py` converte com o pyavb). Mesma forma de resposta da `/mc/selecao`, para
    o painel usar igual. Se o ARO não estiver presente, devolve `{"ok": False, "aro": False}` e o painel cai na
    `/mc/selecao` (Cmd+C). Só leitura.

    ✅ VERIFICADO (2026-10-25): os `masters` daqui são IGUAIS aos do Caminho A (coleta/.avb) para a mesma seleção, e o
    MobID da sequência bate com a API gRPC. Banco `avid-panel-sdk/arrastar.md` §"IDENTIDADE pelo GetSrcMobID".

    ⭐ AUTO-TESTE (segurança entre versões do MC): a cada chamada, conferimos o MobID da SEQUÊNCIA do ARO contra o da
    API gRPC (`sequencia_no_record`); se não casar, RECUSAMOS (o painel cai no Cmd+C).
    ⚠️ (revisão 2026-10-28) O que ele NÃO cobre: (a) o que roda ANTES dele — o `Timeline` e o `GetSelComponent` só têm
    endereço fixo do 25.12.0; por isso a própria dylib recusa os endereços fixos fora do build medido (`build_medido`
    em `aro_servidor.c`); (b) os MASTERS: a SEQ vem do `AComposition::GetMobID`, os masters do `GetSrcMobID` — o teste
    prova o canal e a versão, não cada master.
    """
    import aro
    import plataforma
    from relink import _hexa

    # MC fechado primeiro: sem isto o editor lia "dylib não instalada?" — a causa errada (revisão 2026-10-28)
    if not plataforma.media_composer_aberto():
        return 200, {"ok": False, "aro": False, "mc_fechado": True,
                     "erro": "o Media Composer está fechado — abra o MC com a sequência no Record e selecione os clipes"}
    sel = aro.ler_selecao()
    if sel is None:
        return 200, {"ok": False, "aro": False, "erro": "o canal ARO não respondeu (dylib não instalada?)"}
    if sel.get("erro"):
        return 200, {"ok": False, "aro": True, "erro": sel["erro"]}
    masters = sel["masters"]
    if not masters:
        return 200, {"ok": False, "aro": True, "erro": "nada selecionado na timeline (ou a seleção não tem master)"}

    nome, colunas = "", {}
    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 200, {"ok": False, "aro": True, "erro": "o Media Composer não respondeu"}
        try:
            rec = mc.sequencia_no_record()
        except Exception as e:  # noqa: BLE001
            return 200, {"ok": False, "aro": True, "erro": f"não consegui conferir a sequência: {e}"}
        # auto-teste: o ARO tem de concordar com a API sobre QUAL é a sequência (prova o formato nesta versão do MC)
        if not rec or not sel.get("mob_id") or _hexa(sel["mob_id"]) != _hexa(rec["mob_id"]):
            return 200, {"ok": False, "aro": True, "validado": False,
                         "erro": "o ARO não casou com a sequência do Record (versão do MC não verificada?) — usando o Cmd+C"}
        try:
            colunas = mc.colunas_do_master(rec["mob_id"])
            nome = (colunas.get("Name") or "").strip()
        except Exception:  # noqa: BLE001 — as colunas só enfeitam o cartão
            colunas = {}
    return 200, {"ok": True, "aro": True, "validado": True, "mob_id": sel["mob_id"], "nome": nome, "colunas": colunas,
                 "masters": masters, "clipes": sel["clipes"]}


@rota("GET", "/mc/record")
def mc_record(ctx):
    """A sequência aberta no monitor Record — o botão "Carregar a sequência aberta".

    Devolve `{"mob_id", "nome"}`; com o Record vazio, `{"vazio": true}`. O nome vem do mesmo `GetMobInfo` do
    `/mc/mob` (o arrasto da bin e o botão terminam no mesmo `adotarSequence` do painel).
    """
    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 409, {"erro": "o Media Composer não respondeu"}
        try:
            rec = mc.sequencia_no_record()
            if rec is None:
                return 200, {"vazio": True}
            colunas = mc.colunas_do_master(rec["mob_id"])
        except Exception as e:  # noqa: BLE001
            return 409, {"erro": str(e)}
    return 200, {"mob_id": rec["mob_id"], "nome": (colunas.get("Name") or "").strip(), "tc": rec.get("tc")}


@rota("POST", "/mc/bin/ler")
def mc_bin_ler(ctx):
    """As sequências de uma bin de FORA (`.avb` de outra máquina ou do Magic Link), sem abri-la no MC.

    Devolve `{"bin", "sequencias": [{mob_id, nome, duracao_frames, trilhas}]}` — o painel mostra no cartão e o editor
    marca qual relinkar quando há mais de uma. Lida com o pyavb, só leitura.
    """
    try:
        caminho = _arquivo_valido((ctx.json().get("caminho") or "").strip(), ".avb")
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}
    from avb_bin import segmentos as S
    from avb_export.reader import topen
    try:
        with topen(caminho) as f:
            seqs = [dict(_resumo_da_sequencia(m), mob_id=str(m.mob_id), nome=m.name or "") for m in S.sequencias(f)]
    except Exception as e:  # noqa: BLE001 — bin de terceiro: o motivo vai para o editor, não um traceback
        return 422, {"erro": f"não consegui ler essa bin ({type(e).__name__}: {e})"}
    if not seqs:
        return 422, {"erro": "essa bin não tem sequência"}
    return 200, {"bin": caminho, "sequencias": seqs}


@rota("POST", "/mc/prproj/ler")
def mc_prproj_ler(ctx):
    """As sequências de um projeto do Premiere solto no modo Media Composer (organograma Premiere → Avid, autor
    2026-10-25: o MC está aberto desde o início e só RECEBE o .prproj; o Premiere nem precisa existir na máquina).

    Devolve `{"prproj", "sequencias": [{mob_id, nome, duracao, planos}], "pastas"}` — o mesmo cartão da bin de fora;
    `mob_id` = o uid da sequência (duas podem ter o mesmo nome); `pastas` = as que este projeto usou da última vez."""
    try:
        caminho = _arquivo_valido((ctx.json().get("caminho") or "").strip(), ".prproj")
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}
    from prproj.leitura import Leitor
    from prproj.projeto import Projeto
    from sessao_receber import pastas_do_projeto

    try:
        seqs = Leitor(Projeto(caminho)).sequencias_de_montagem()
    except Exception as e:  # noqa: BLE001 — arquivo de terceiro: o motivo vai para o editor
        log.warning("prproj ilegível %s: %s: %s", caminho, type(e).__name__, e)
        return 422, {"erro": f"não consegui ler {Path(caminho).name} como projeto do Premiere"}
    if not seqs:
        return 422, {"erro": "esse projeto não tem nenhuma sequência de montagem"}
    return 200, {"prproj": caminho, "pastas": pastas_do_projeto(caminho),
                 "sequencias": [{"mob_id": x["uid"] or x["nome"], "nome": x["nome"], "planos": x["planos"],
                                 "fps": x.get("fps"), "raster": f'{x.get("largura")}×{x.get("altura")}'
                                 if x.get("largura") else "",
                                 # sem a taxa da sequência, o relógio (h:mm:ss) — nunca quadros a 24 inventados (B012)
                                 "duracao": (_duracao_avid(round(x["duracao_s"] * x["fps"]), x["fps"]) if x.get("fps")
                                             else _relogio(x["duracao_s"])) if x.get("duracao_s") else ""}
                                for x in seqs]}


def _faixas_av(nums: list[int], letra: str) -> str:
    """`[1]` → `V1`; `[1, 2]` → `A1-2`; `[1, 3]` → `A1,3` — o jeito do Avid na coluna Tracks."""
    nums = sorted(set(nums))
    if not nums:
        return ""
    if nums == list(range(nums[0], nums[-1] + 1)):
        return f"{letra}{nums[0]}" if len(nums) == 1 else f"{letra}{nums[0]}-{nums[-1]}"
    return letra + ",".join(str(n) for n in nums)


def _relogio(segundos: float) -> str:
    s = int(round(segundos))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def _duracao_avid(quadros: int, fps: float) -> str:
    """Quadros → a duração como a coluna Duration do Avid: `7:07` (s:qq), `1:02:03` (m:ss:qq), `1:00:00:00`."""
    if not fps:                     # sem taxa, quadros — nunca a 24 inventado (B012)
        return f"{int(quadros)} quadros"
    base = max(1, round(fps))
    s, q = divmod(int(quadros), base)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}:{q:02d}"
    if m:
        return f"{m}:{s:02d}:{q:02d}"
    return f"{s}:{q:02d}"


def _resumo_da_sequencia(m) -> dict:
    """Trilhas e duração de uma sequência da bin, sem ler a timeline inteira (a lista de uma bin com 92).

    ⚠️ Só imagem e som contam (autor, 2026-10-12: "11 trilhas" eram 1 de vídeo + 2 de áudio + 8 de TC).
    """
    v, a, quadros, fps = [], [], 0, 0.0
    for t in list(getattr(m, "tracks", []) or []):
        tipo = getattr(t, "media_kind", "")
        comp = getattr(t, "component", None)
        if tipo not in ("picture", "sound") or comp is None:
            continue
        (v if tipo == "picture" else a).append(int(getattr(t, "index", 0) or 0))
        quadros = max(quadros, int(getattr(comp, "length", 0) or 0))
        if not fps:
            try:
                fps = float(getattr(comp, "edit_rate", 0) or 0)
            except (TypeError, ValueError):
                fps = 0.0
    return {"trilhas": " ".join(x for x in (_faixas_av(v, "V"), _faixas_av(a, "A")) if x),
            "duracao_frames": quadros, "duracao": _duracao_avid(quadros, fps) if quadros else "", "fps": fps or None}


@rota("POST", "/mc/bin/sequencia")
def mc_bin_sequencia(ctx):
    """"Carregar sequência" de uma bin de fora: os fatos do cartão (duração, taxa, trilhas, início, formato), lidos
    da sequência marcada — os mesmos que a sequência arrastada da bin mostra pelas colunas do MC."""
    corpo = ctx.json()
    try:
        caminho = _arquivo_valido((corpo.get("caminho") or "").strip(), ".avb")
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}
    from avb_bin import segmentos as S
    from avb_export.reader import topen
    try:
        with topen(caminho) as f:
            alvo = S.escolher_sequencia(f, mob_id=(corpo.get("mob_id") or "").strip() or None)
            if alvo is None:
                return 404, {"erro": "essa sequência não está na bin"}
            resumo = _resumo_da_sequencia(alvo)
            lida = S.ler_timeline(f, alvo)
            fps = lida.get("timeline_fps") or resumo["fps"]
    except Exception as e:  # noqa: BLE001
        return 422, {"erro": f"não consegui ler a sequência ({type(e).__name__}: {e})"}
    return 200, {"mob_id": str(alvo.mob_id), "nome": alvo.name or "", "trilhas": resumo["trilhas"],
                 "duracao": _duracao_avid(resumo["duracao_frames"], fps) if resumo["duracao_frames"] else "",
                 "fps": fps, "inicio": lida.get("timeline_start_tc") or ""}


# ── diagnóstico de arrasto ──────────────────────────────────────────────────
#
# ⭐ Existe porque o arrasto depende de um contrato que a Avid não publica, e a pergunta
# quando algo não funciona é sempre a mesma: **o que exatamente chegou?** Sem isto a
# resposta depende de a pessoa abrir a aba certa e mandar uma foto da tela — um laço
# lento e fácil de errar. Com isto, o painel deposita e quem estiver depurando consulta.
#
# Não sai nada da máquina: é o mesmo loopback do resto, e o corpo é o payload que o
# próprio Media Composer acabou de entregar ao painel.

@rota("POST", "/diag/erro")
def diag_erro(ctx):
    """Erro de script do painel (o do MC não tem console à vista): vai para o log do serviço."""
    corpo = ctx.json()
    log.warning("erro no painel: %s (%s)", str(corpo.get("msg") or "")[:500], str(corpo.get("onde") or "")[:200])
    if corpo.get("pilha"):
        log.debug("pilha: %s", str(corpo.get("pilha"))[:4000])
    return 200, {"ok": True}


@rota("POST", "/diag/arrasto")
def diag_arrasto_gravar(ctx):
    """O painel deposita aqui o que recebeu num `drop`."""
    corpo = ctx.json()
    ctx.servico.arrastos.append(corpo)
    del ctx.servico.arrastos[:-ctx.servico.MAX_ARRASTOS]
    tipos = corpo.get("tipos") or []
    # INFO com o resumo (é raro e é útil no log de quem está rodando o serviço);
    # o payload inteiro fica em DEBUG, para não poluir.
    log.info("arrasto recebido: efeito=%s tipos=%s", corpo.get("efeito"), tipos)
    log.debug("arrasto completo: %s", corpo)

    # ⛔ Houve aqui uma vigia que observava o `.aaf` anexo ao arrasto nascer no disco.
    # Ela respondeu: **ele nunca nasce**. 40 amostras em 10 s, `existiu: False` — o
    # Chromium sintetiza um `File` de 0 bytes a partir do descritor do arrasto e o
    # arquivo não chega a existir, nem para um processo nativo. Ver ADR 0012.

    # ⭐ CLASSIFICAR o que foi arrastado, quando não é o caso trivial.
    #
    # O `type` do payload é o primeiro eixo, mas ele é grosso: o Media Composer separa
    # `masterClips` de `linkedMasterClips` (AMA) na própria API, e o payload não faz essa
    # distinção. O segundo eixo são as COLUNAS do mob — o conjunto delas é impressão
    # digital: uma sequence tem `Tracks`/`Master Dur` e nenhuma `Drive`/`Source File`.
    #
    # ⚠️ Custa ~500 ms por item, então só roda quando há o que aprender: mais de um item,
    # ou um tipo que não seja a sequence que já sabemos tratar. Num arrasto normal (uma
    # timeline) isto não dispara — o painel já pede `/mc/mob` sozinho.
    itens = _itens_do_arrasto(corpo)
    if itens and (len(itens) > 1 or any(i.get("type") != "sequence" for i in itens)):
        threading.Thread(target=_classificar_arrasto, args=(ctx.servico, itens),
                         daemon=True, name="classifica-arrasto").start()
    return 200, {"ok": True}


def _itens_do_arrasto(corpo: dict) -> list[dict]:
    """Os itens do payload `mc-api-asset-list+json`, se vierem legíveis."""
    bruto = (corpo.get("dados") or {}).get("text/x.avid.mc-api-asset-list+json") or ""
    try:
        dados = json.loads(bruto)
    except (ValueError, TypeError):
        return []
    return [i for i in (dados if isinstance(dados, list) else [dados]) if isinstance(i, dict)]


def _classificar_arrasto(servico, itens: list[dict], teto: int = 12) -> None:
    """Para cada item arrastado: o `type` do payload + as colunas que o MC dá.

    É bancada, não produto: existe para **descobrir o vocabulário real** de `type` e o
    que distingue cada espécie de clipe (importado × linkado, group, efeito, precompute).
    """
    from avid.mcapi import mob_id_valido

    fora = []
    try:
        with servico.media_composer() as mc:
            if not mc.esta_vivo():
                return
            for item in itens[:teto]:
                mob_id = (item.get("id") or "").strip()
                registro = {"type": item.get("type"), "campos": sorted(item)}
                if mob_id_valido(mob_id):
                    try:
                        colunas = mc.colunas_do_master(mob_id)
                        registro["nome"] = colunas.get("Name", "")
                        registro["colunas"] = sorted(colunas)
                        # As poucas colunas que costumam separar espécies.
                        registro["pistas"] = {k: colunas[k] for k in
                                              ("Drive", "Source File", "Source Path",
                                               "Tape", "Tracks", "Video", "Offline")
                                              if k in colunas}
                    except Exception as e:  # noqa: BLE001
                        registro["erro"] = str(e)
                fora.append(registro)
    except Exception as e:  # noqa: BLE001
        log.debug("classificação do arrasto falhou: %s", e)
        return

    log.info("arrasto classificado: %s", [(r.get("type"), r.get("nome")) for r in fora])
    # ⚠️ Anota no arrasto que ESTÁ NO FIM da lista, e não num "último" guardado à parte:
    # a classificação roda em thread e chega depois, mas é sempre do arrasto que acabou
    # de ser gravado. Guardar a referência ao entrar seria mais direto — só que ela
    # poderia ter caído fora da janela dos últimos, e aí a anotação sumiria sem sinal.
    if servico.arrastos and isinstance(servico.arrastos[-1], dict):
        servico.arrastos[-1]["classificacao"] = fora


@rota("GET", "/diag/arrasto")
def diag_arrasto_ler(ctx):
    """Os últimos arrastos, do mais recente para o mais antigo.

    A lista existe porque a pergunta de bancada é quase sempre comparativa — *o que muda
    entre arrastar uma pasta e arrastar um arquivo?* —, e comparar exige as duas medições
    vivas ao mesmo tempo.
    """
    recentes = list(reversed(ctx.servico.arrastos))
    if not recentes:
        return 200, {"vazio": True}
    return 200, {"ultimo": recentes[0], "anteriores": recentes[1:],
                 "quantos": len(recentes)}


# ⛔ Houve aqui uma rota `/mc/bin/sequences`, que lia as timelines de UMA bin. Ela foi
# removida quando o arrasto de bin se mostrou impossível (o Media Composer entrega o
# arrasto de uma bin **sem dado nenhum** — medido), e nada mais sabia dizer QUAL bin: o
# `systemID` do payload de arrasto é o sistema de ORIGEM (`mc-api`/`interplay-pam`), não
# a bin. Sem quem a chame, a rota era caminho especulativo baseado num formato nunca
# medido — o tipo de código que apodrece. Está no histórico do git se voltar a fazer
# sentido. Ver ADR 0012.

@rota("GET", "/mc/preset")
def mc_preset(ctx):
    """O estado do preset de export do plugin.

    ⚠️ O editor **não escolhe** o preset: o formato do export é requisito do plugin, não
    preferência. O que ele pode fazer é instalar/consertar o nosso — e isso exige o Media
    Composer fechado, porque ele reescreve as settings ao sair.
    """
    from presets import diagnostico
    return 200, diagnostico()


@rota("POST", "/mc/preset/instalar")
def mc_preset_instalar(ctx):
    """Grava o preset do plugin nas settings, sobrescrevendo o que houver com esse nome."""
    from presets import instalar
    r = instalar(forcar=bool(ctx.json().get("forcar")))
    return (200 if r.get("ok") else 409), r


# ── abrir link externo ──────────────────────────────────────────────────────

# ⚠️ **Lista fechada, e não uma URL vinda do painel.** Quem abre o navegador é este
# processo, que roda como o usuário: uma rota que aceitasse URL arbitrária viraria "abra
# qualquer coisa" para quem alcançasse o painel. O painel pede um DESTINO pelo nome; o
# endereço mora aqui. Mesmo desenho do Órbita (`httpserver.rs`, `wanted_link`).
LINKS = {
    "autor": "https://www.linkedin.com/in/lohan-costa/",
}


@rota("POST", "/link/abrir")
def link_abrir(ctx):
    import plataforma

    destino = LINKS.get(ctx.json().get("qual") or "")
    if not destino:
        return 400, {"erro": "destino desconhecido"}
    try:
        plataforma.abrir_url(destino)
    except Exception as e:  # noqa: BLE001
        return 500, {"erro": str(e)}
    return 200, {"ok": True}


# ── o aplicativo ────────────────────────────────────────────────────────────

# ── O Resolve pelo lado de fora (app unificado, passo 1 — `resolve_externo.py`) ─────────────────────────────────
# As MESMAS funções da ponte `window.delapraca` da casca, para o painel aberto na janela do app. Um erro de conexão
# (Resolve fechado, o Free, sem a API) volta como 409 com o motivo, como as rotas do Media Composer.

def _resolve_externo(fn, *args):
    import aviso_ocupado
    import resolve_externo

    try:
        # ⛔ A chamada segura o GIL enquanto o Resolve trabalha: o supervisor do app é avisado (`aviso_ocupado`).
        with aviso_ocupado.mudo(f"esperando o DaVinci Resolve ({fn})"):
            return 200, getattr(resolve_externo, fn)(*args)
    except RuntimeError as e:
        return 409, {"ok": False, "erro": str(e)}


@rota("GET", "/conexao")
def conexao(ctx):
    """Com que programa o app está falando (organograma do app unificado, 2026-10-18): o painel aberto na janela do
    app segue o programa CONECTADO, não um seletor. `{programa: "mc"|"resolve"|None, versao, projeto}`.

    O MC pela API (9100); o Resolve pelo processo e, para versão e projeto, pela API externa (0,04 s medido). Os dois
    abertos juntos não é o caso de uso (regra do app); se acontecer, o MC vence e o painel diz qual.
    """
    from pathlib import Path as _P

    import plataforma

    # ⚠️ Perguntar à API do MC FECHADO custa ~2 s (a gRPC espera; medido 2026-10-18): o processo decide antes.
    if plataforma.media_composer_aberto():
        mc_ocupado = _conexao_mc(ctx)
        if mc_ocupado is not None:
            return 200, mc_ocupado
    processos = plataforma.processos()
    nomes = {n.lower().rsplit("/", 1)[-1] for _, _, n in processos}
    # O Premiere pela PONTE (2026-10-19): conectado = a extensão invisível atendendo.
    import premiere_ponte

    premiere = None
    if premiere_ponte.ponte_viva():
        try:
            e = premiere_ponte.chamar("dlpcEstado", prazo=5)
            premiere = {"programa": "premiere", "versao": e.get("versao") or "",
                        "projeto": _P(e["projeto"]).stem if e.get("projeto") else ""}
        except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou):
            pass
    resolve_aberto = bool({"resolve.exe", "resolve"} & nomes)
    # ⭐ Os dois abertos (organograma do modo Premiere, decisão C, 2026-10-19): o painel segue o programa em que o editor
    # clicou por último — a janela da frente, lembrada enquanto ela é a do app ou de outro programa qualquer
    if premiere and resolve_aberto:
        frente = _programa_da_frente(processos)
        if frente in ("premiere", "resolve"):
            _ULTIMO_NLE["v"] = frente
        if _ULTIMO_NLE["v"] != "resolve":
            return 200, {**premiere, "tambem": "DaVinci Resolve"}
    elif premiere:
        return 200, premiere
    if resolve_aberto:
        import aviso_ocupado
        import resolve_externo

        extra = {"tambem": "Premiere Pro"} if premiere else {}
        try:
            with aviso_ocupado.mudo("esperando o DaVinci Resolve (projeto)"):
                r = resolve_externo.projeto()
            return 200, {"programa": "resolve", "versao": r.get("versao") or "", "projeto": r.get("projeto") or "",
                         **extra}
        except RuntimeError as e:
            return 200, {"programa": "resolve", "versao": "", "projeto": "", "erro": str(e), **extra}
    # ⭐ O BASELIGHT (proposta 2026-11-22-baselight-no-app, etapa 2): só RECEBE; o último da fila (os NLEs de montagem
    # vencem). "Aberto" é a interface; o painel vira o do colorista (`?nle=baselight`).
    from baselight import enviar as _bl

    if (bl := _bl.interface_aberta()):
        return 200, {"programa": "baselight", "versao": bl.get("versao") or "", "projeto": ""}
    return 200, {"programa": None, "versao": "", "projeto": ""}


@rota("GET", "/baselight/jobs")
def baselight_jobs(ctx):
    """Os jobs do Baselight desta máquina (a escolha do job da produção no painel): `{disponivel, motivo, jobs}`."""
    from baselight import enviar as _bl

    _tocar_receptor(ctx)
    ok, motivo = _bl.disponivel()
    if not ok:
        return 200, {"disponivel": False, "motivo": motivo, "jobs": []}
    try:
        return 200, {"disponivel": True, "motivo": "", "jobs": _bl.jobs(),
                     # o job em que o colorista está (a scene aberta na interface), para a pergunta da etapa 4
                     "aberto": _bl.job_aberto() if _bl.interface_aberta() else None}
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        return 200, {"disponivel": False, "motivo": f"o banco do Baselight não respondeu: {e}", "jobs": []}


@rota("GET", "/baselight/scenes")
def baselight_scenes(ctx):
    """As scenes de um job do Baselight (`?job=`): a escolha da scene do colorista no "atualizar corte" (etapa 5)."""
    import urllib.parse

    from baselight import enviar as _bl

    _tocar_receptor(ctx)
    job = (urllib.parse.parse_qs(ctx.query or "").get("job") or [""])[0].strip()[:100]
    ok, motivo = _bl.disponivel()
    if not ok or not job:
        return 200, {"scenes": [], "motivo": motivo or "sem job"}
    try:
        return 200, {"scenes": _bl.scenes(_bl.limpar_nome(job)) if _bl.limpar_nome(job) in _bl.jobs() else [],
                     "motivo": ""}
    except (OSError, RuntimeError, subprocess.SubprocessError) as e:
        return 200, {"scenes": [], "motivo": f"o banco do Baselight não respondeu: {e}"}


#: O pedido da CARTA ABERTA (etapa 3 da proposta Baselight no app): "Conformar com De Lá Pra Cá" grava aqui o xmeml da
#: timeline e o job; o painel do De Lá Pra Cá o pega (uma vez) e abre a timeline já carregada. A pasta é a de dados do
#: Ciclo Assist, a MESMA dos dois serviços (`plataforma.pasta_do_ciclo_assist`).
PRAZO_DO_PEDIDO_S = 15 * 60


@rota("POST", "/receber/a-conformar")
def receber_a_conformar(ctx):
    """`{xml, nome, job}` do pedido deixado pela Carta Aberta, ou `{}` — e o pedido é consumido (renomeado `.lido`).
    O `xml` passa pela tranca de caminho; pedido velho (> 15 min) é ignorado (o colorista pode ter desistido)."""
    import time as _t

    import plataforma

    _tocar_receptor(ctx)
    arq = plataforma.pasta_do_ciclo_assist() / "conformar" / "a-conformar.json"
    if not arq.is_file():
        return 200, {}
    try:
        pedido = json.loads(arq.read_text(encoding="utf-8"))
        arq.replace(arq.with_suffix(".lido"))
    except (OSError, ValueError):
        return 200, {}
    if not isinstance(pedido, dict) or _t.time() - float(pedido.get("quando") or 0) > PRAZO_DO_PEDIDO_S:
        return 200, {}
    try:
        xml = _arquivo_valido(str(pedido.get("xml") or ""))
    except CaminhoInvalido:
        return 200, {}
    return 200, {"xml": xml, "nome": str(pedido.get("nome") or "")[:200], "job": str(pedido.get("job") or "")[:100]}


_ULTIMO_NLE = {"v": None}

#: A sonda do MC no `/conexao` (medido 2026-10-24, Mac, MC 25.12): com um diálogo MODAL aberto no MC ("Leave the
#: application?") ou abrindo um projeto, o `GetAppInfo` não responde — e com o prazo padrão de 20 s o `/conexao` levava
#: 20 s, a página ficava "procurando o De Lá Pra Cá…" e, no fim, o painel TROCAVA para o Premiere (o MC "não estava").
#: Prazo curto, e "não respondeu no prazo" ≠ "não está atendendo": ocupado = continua sendo o MC.
PRAZO_SONDA_MC_S = 3.0
#: Depois de uma sonda sem resposta, quanto tempo responder "ocupado" na hora (a página pergunta de poucos em poucos
#: segundos; sem isto as esperas se empilham).
CARENCIA_MC_OCUPADO_S = 8.0
_MC_CONHECIDO = {"versao": "", "projeto": "", "ocupado_ate": 0.0}


def _conexao_mc(ctx) -> dict | None:
    """O MC conectado (`{programa: "mc", versao, projeto}`), ocupado (`… ocupado: True`, com o último conhecido) ou
    `None` quando ele não está atendendo (aberto sem a API, ou ainda subindo) — aí vale o próximo programa."""
    import time

    from avid.mcapi import McApiError, McApiIndisponivel

    if time.monotonic() < _MC_CONHECIDO["ocupado_ate"]:
        return {"programa": "mc", "versao": _MC_CONHECIDO["versao"], "projeto": _MC_CONHECIDO["projeto"],
                "ocupado": True}
    with ctx.servico.media_composer() as mc:
        mc.timeout = PRAZO_SONDA_MC_S
        try:
            info = mc.info()
        except McApiIndisponivel:
            return None
        except McApiError:
            _MC_CONHECIDO["ocupado_ate"] = time.monotonic() + CARENCIA_MC_OCUPADO_S
            log.info("conexão: o Media Composer não respondeu em %.0f s — ocupado (um diálogo aberto?)",
                     PRAZO_SONDA_MC_S)
            return {"programa": "mc", "versao": _MC_CONHECIDO["versao"], "projeto": _MC_CONHECIDO["projeto"],
                    "ocupado": True}
        try:
            caminho = (mc.projeto() or {}).get("path") or ""
        except Exception:  # noqa: BLE001 — sem projeto aberto (a tela de projetos), ou ocupado no meio
            caminho = ""
    _MC_CONHECIDO.update(versao=info.get("version") or "",
                         projeto=Path(caminho.rstrip("\\/")).name if caminho else "")
    return {"programa": "mc", "versao": _MC_CONHECIDO["versao"], "projeto": _MC_CONHECIDO["projeto"]}


def _programa_da_frente(processos) -> str | None:
    """Qual NLE tem a janela da frente agora: "premiere", "resolve" ou None (outro programa, o próprio app, ou fora do
    Windows — no Mac, `pendente`)."""
    import sys

    if sys.platform != "win32":
        return None
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    pid = wintypes.DWORD(0)
    u.GetWindowThreadProcessId(u.GetForegroundWindow(), ctypes.byref(pid))
    nome = next((n.lower().rsplit("\\", 1)[-1] for p, _pp, n in processos if p == pid.value), "")
    if nome.startswith("adobe premiere pro"):
        return "premiere"
    if nome == "resolve.exe":
        return "resolve"
    return None


@rota("POST", "/resolve/projeto")
def resolve_projeto(ctx):
    return _resolve_externo("projeto")


@rota("POST", "/resolve/timelines")
def resolve_timelines(ctx):
    return _resolve_externo("timelines")


@rota("POST", "/resolve/midias")
def resolve_midias(ctx):
    return _resolve_externo("midias", ctx.json() or {})


@rota("POST", "/resolve/importar")
def resolve_importar(ctx):
    return _resolve_externo("importar", ctx.json() or {})


@rota("POST", "/resolve/fusion")
def resolve_fusion(ctx):
    return _resolve_externo("fusion", ctx.json() or {})


@rota("POST", "/resolve/luts")
def resolve_luts(ctx):
    return _resolve_externo("luts", ctx.json() or {})


@rota("POST", "/resolve/cor_mc")
def resolve_cor_mc(ctx):
    return _resolve_externo("cor_mc", ctx.json() or {})


@rota("POST", "/resolve/estabilizar")
def resolve_estabilizar(ctx):
    return _resolve_externo("estabilizar", ctx.json() or {})


@rota("POST", "/resolve/compostos")
def resolve_compostos(ctx):
    return _resolve_externo("compostos", ctx.json() or {})


@rota("POST", "/resolve/efeitosNoMonitor")
def resolve_efeitosNoMonitor(ctx):
    return _resolve_externo("efeitosNoMonitor", ctx.json() or {})


@rota("POST", "/resolve/exportarTrabalho")
def resolve_exportarTrabalho(ctx):
    return _resolve_externo("exportarTrabalho", ctx.json() or {})


@rota("POST", "/resolve/atualizar")
def resolve_atualizar(ctx):
    return _resolve_externo("atualizar", ctx.json() or {})


@rota("POST", "/resolve/conferirInicio")
def resolve_conferirInicio(ctx):
    return _resolve_externo("conferirInicio", ctx.json() or {})


@rota("POST", "/resolve/conferirQuadros")
def resolve_conferirQuadros(ctx):
    return _resolve_externo("conferirQuadros", ctx.json() or {})


@rota("POST", "/resolve/timeline-aberta")
def resolve_timeline_aberta(ctx):
    return _resolve_externo("timeline_aberta", ctx.json() or {})


@rota("POST", "/resolve/selecao-da-timeline")
def resolve_selecao_da_timeline(ctx):
    """Os clipes SELECIONADOS na timeline do Resolve → a conferência roda só neles (igualar as funções do MC/Premiere,
    2026-10-25). Mesma forma de `/resolve/timeline-aberta`, com `so_selecionados: true` e a contagem. Resolve antigo
    sem a seleção, ou nada selecionado → `ok: False` e o painel cai na timeline inteira."""
    return _resolve_externo("selecao_da_timeline", ctx.json() or {})


@rota("POST", "/resolve/conferirFim")
def resolve_conferirFim(ctx):
    return _resolve_externo("conferirFim", ctx.json() or {})


# ── o Premiere pela PONTE ÚNICA do Ciclo Assist (fase 4 do plano um app só, 2026-11-07): `premiere_ponte.chamar` pede
# ao núcleo (7824), que roda as funções `dlpc*` do `premiere_host.jsx`. A ponte própria (`/premiere/ponte`, `pedido`,
# `resposta`, `host.jsx`) saiu com a extensão `com.ciclomedia.delapraca.ppro`. ─────────────────────────────────────

@rota("GET", "/premiere/estado")
def premiere_estado(ctx):
    """O Premiere conectado? `{conectado, versao, projeto, sequencias, sequencia_ativa}` — a ponte responde em ms."""
    import premiere_ponte

    if not premiere_ponte.ponte_viva():
        return 200, {"conectado": False}
    try:
        return 200, {"conectado": True, **premiere_ponte.chamar("dlpcEstado", prazo=10)}
    except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou) as e:
        return 200, {"conectado": False, "erro": str(e)}


@rota("GET", "/premiere/sequencias")
def premiere_sequencias(ctx):
    import premiere_ponte

    try:
        return 200, premiere_ponte.chamar("dlpcSequencias", prazo=20)
    except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/premiere/abrir")
def premiere_abrir(ctx):
    """Abrir um `.prproj` no Premiere pelo app. Projeto de outra versão pede conversão (diálogo): o prazo diz."""
    import os

    import premiere_ponte

    caminho = (ctx.json() or {}).get("caminho")
    if not isinstance(caminho, str) or "\0" in caminho or not caminho.lower().endswith(".prproj") \
            or not os.path.isfile(caminho):
        return 400, {"erro": "aponte um projeto do Premiere (.prproj) deste computador"}
    try:
        return 200, premiere_ponte.chamar("dlpcAbrirProjeto", caminho, prazo=120)
    except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/premiere/sequencia")
def premiere_sequencia(ctx):
    """Ler uma sequência do Premiere pela ponte (`{id}` ou a ativa): os clipes com início, fim e entrada em ticks."""
    import premiere_ponte

    sid = str((ctx.json() or {}).get("id") or "")[:64]
    try:
        return 200, premiere_ponte.chamar("dlpcLerSequencia", sid, prazo=60)
    except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/premiere/montar")
def premiere_montar(ctx):
    """Montar no Premiere (modo Premiere, decisão A do organograma de 2026-10-19): `{plano}` — o que o `/receber/preparar`
    com `destino: "premiere"` devolveu — → a ponte importa a mídia, cria a sequência e põe cada plano no lugar."""
    import os

    import premiere_ponte

    pl = (ctx.json() or {}).get("plano")
    if not isinstance(pl, dict) or not isinstance(pl.get("midias"), list) or not isinstance(pl.get("planos"), list):
        return 400, {"erro": "plano de montagem inválido"}
    midias = [m for m in pl["midias"][:5000] if isinstance(m, str) and "\0" not in m and os.path.isfile(m)]
    if len(midias) != len(pl["midias"]):
        return 400, {"erro": "o plano aponta arquivo que não está neste computador"}
    try:
        plano = {"nome": str(pl.get("nome") or "De Lá Pra Cá")[:120], "tpf": int(pl["tpf"]), "inicio": int(pl["inicio"]),
                 "midias": midias,
                 "planos": [{"m": int(x["m"]), "v": bool(x["v"]), "t": max(1, min(int(x["t"]), 99)), "rec": int(x["rec"]),
                             "dur": int(x["dur"]), "src": int(x["src"]), "ref": bool(x.get("ref")),
                             # o som desligado no Avid entra desligado (`premiere_montagem.plano`)
                             **({"desligado": True} if x.get("desligado") is True and not x.get("v") else {})}
                            for x in pl["planos"][:20000] if 0 <= int(x["m"]) < len(midias)],
                 "marcas": [{"q": int(x["q"]), "nome": str(x.get("nome") or "")[:80], "nota": str(x.get("nota") or "")[:400]}
                            for x in (pl.get("marcas") or [])[:5000]]}
    except (KeyError, TypeError, ValueError):
        return 400, {"erro": "plano de montagem inválido"}
    try:
        return 200, premiere_ponte.chamar("dlpcMontar", plano, prazo=900)
    except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/premiere/copia")
def premiere_copia_rota(ctx):
    """Premiere → Premiere (organograma aprovado em 2026-10-22): `{id}` — a cópia relinkada que o `/receber/preparar`
    com `destino: "premiere"` gravou → a ponte a importa no projeto aberto e o serviço confere o caminho de cada clipe."""
    import premiere_copia

    rid = str((ctx.json() or {}).get("id") or "")
    plano = ctx.servico.receber.relink(rid)
    if not plano:
        return 409, {"erro": "a cópia não está mais preparada — monte de novo"}
    try:
        return 200, premiere_copia.executar(plano)
    except premiere_ponte_erros() as e:
        return 409, {"ok": False, "erro": str(e)}


def premiere_ponte_erros() -> tuple:
    import premiere_ponte

    return (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou)


@rota("POST", "/premiere/sequencia-ativa")
def premiere_sequencia_ativa(ctx):
    """"Carregar a sequência aberta" no modo Premiere: o `.prproj` e a sequência ativa (o app lê o projeto SALVO)."""
    import premiere_copia

    try:
        return 200, premiere_copia.sequencia_ativa()
    except premiere_ponte_erros() as e:
        return 200, {"ok": False, "erro": str(e)}


@rota("POST", "/premiere/selecao-da-timeline")
def premiere_selecao_da_timeline(ctx):
    """Os clipes SELECIONADOS na timeline aberta do Premiere (2026-10-24): o arrasto de clipes da timeline só traz um
    ponteiro (banco premiere-cep/arrastar-e-selecao.md §6e) — o dado vem da seleção. Só lê."""
    import premiere_ponte

    try:
        return 200, premiere_ponte.chamar("dlpcSelecaoDaTimeline")
    except premiere_ponte_erros() as e:
        return 200, {"ok": False, "erro": str(e)}


@rota("POST", "/premiere/conferirInicio")
def premiere_conferir_inicio(ctx):
    import premiere_copia

    try:
        return 200, premiere_copia.conferir_inicio(ctx.json() or {}, ctx.servico.receber._relinks)
    except premiere_ponte_erros() as e:
        return 200, {"ok": False, "erro": str(e)}


@rota("POST", "/premiere/conferirQuadros")
def premiere_conferir_quadros(ctx):
    import premiere_copia

    try:
        return 200, premiere_copia.conferir_quadros(ctx.json() or {})
    except premiere_ponte_erros() as e:
        return 200, {"ok": False, "erro": str(e)}


@rota("POST", "/premiere/conferirFim")
def premiere_conferir_fim(ctx):
    import premiere_copia

    try:
        return 200, premiere_copia.conferir_fim(ctx.json() or {})
    except premiere_ponte_erros() as e:
        return 200, {"ok": False, "erro": str(e)}


#: as espécies do arrasto do MC pela bin onde o mob mora (`GetListOfBinItems.BinItemFlags`), na ordem de pergunta
_ESPECIES_NA_BIN = (("sequence", ("sequences",)), ("subclip", ("subclips",)), ("group", ("groups",)),
                    ("masterclip", ("masterClips", "linkedMasterClips")))


@rota("POST", "/arrasto/mc")
def arrasto_mc(ctx):
    """O arrasto do MC no MAC (`app/src-tauri/src/arrasto_mac.rs`) → o mesmo payload do Windows.

    No Mac o MC só entrega o XML com os MobIDs (`mobIDDragObjectList`); os JSON com a espécie (`type`) chegam como
    promessa sem dado (banco, avid-panel-sdk/arrastar.md, seção macOS). A espécie sai da API: a bin do mob
    (`GetBinFromMob`) e, nela, em que categoria ele está — a classificação da própria bin, não um palpite pelas
    colunas. ~0,5 s por pergunta; é um gesto deliberado (uma timeline por arrasto). Sem a bin, `type` = "?" e a página
    recusa dizendo que não reconheceu.
    """
    from avid.mcapi import mob_id_valido

    def hexa(m):
        return "".join(c for c in (m or "").lower() if c in "0123456789abcdef")

    ids = [str(m) for m in (ctx.json() or {}).get("mob_ids") or [] if mob_id_valido(str(m))][:12]
    if not ids:
        return 200, {"ok": False, "erro": "o arrasto do Media Composer não trouxe identidade"}
    itens = []
    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 200, {"ok": False, "erro": "o Media Composer não respondeu"}
        for mid in ids:
            especie = "?"
            caminho = mc.bin_do_mob(mid)
            for nome, flags in _ESPECIES_NA_BIN if caminho else ():
                try:
                    if any(hexa(i.mob_id) == hexa(mid) for i in mc.itens_de(caminho, flags=flags)):
                        especie = nome
                        break
                except Exception as e:  # noqa: BLE001 — a bin que não responde deixa a espécie em "?"
                    log.debug("bin %r não respondeu (%s): %s", caminho, flags, e)
                    break
            itens.append({"head": "0", "id": mid, "systemID": "mc-api", "systemType": "mediacomposer",
                          "type": especie})
    return 200, {"ok": True, "itens": itens}


@rota("POST", "/arrasto/nle")
def arrasto_nle(ctx):
    """O que veio arrastado de DENTRO do Resolve ou do Premiere para a janela do app (o alvo nativo,
    `app/src-tauri/src/arrasto_win.rs`) → o objeto. Resolve: `{tipo: "resolve", media_id}` → a timeline. Premiere:
    `{tipo: "premiere", dados}` (o XML do `dynamiclinksourcelist`) → o `.prproj` e a sequência pelo `sequenceID`.
    Uma timeline por arrasto (memória "uma timeline por arrasto")."""
    import os
    import re
    import xml.etree.ElementTree as ET

    corpo = ctx.json() or {}
    tipo = corpo.get("tipo")
    if tipo == "resolve":
        import resolve_externo

        import aviso_ocupado

        try:
            with aviso_ocupado.mudo("esperando o DaVinci Resolve (timeline do arrasto)"):
                return 200, resolve_externo.timeline_do_arrasto(str(corpo.get("media_id") or ""))
        except RuntimeError as e:
            return 200, {"ok": False, "erro": str(e)}
    if tipo == "premiere_item":
        return 200, {"ok": False, "erro": "do Premiere, só uma SEQUÊNCIA vem pelo arrasto — um clipe não traz identidade"}
    if tipo != "premiere":
        return 400, {"erro": "arrasto desconhecido"}
    texto = str(corpo.get("dados") or "")[:200000]
    try:
        raiz = ET.fromstring(re.sub(r"<\?xml[^>]*\?>", "", texto).strip())
    except ET.ParseError:
        return 200, {"ok": False, "erro": "o arrasto do Premiere veio ilegível"}
    fontes = [(f.findtext("ProjectPath") or "", (f.findtext("ID") or "").strip()) for f in raiz.iter("Source")]
    fontes = [x for x in fontes if x[1]]
    if len(fontes) != 1:
        return 200, {"ok": False, "erro": "uma timeline por vez: arraste uma sequência só" if fontes
                     else "o arrasto do Premiere não trouxe sequência"}
    prproj, sid = fontes[0]
    r = {"ok": True, "programa": "premiere", "prproj": prproj, "id": sid, "nome": "", "existe": os.path.isfile(prproj)}
    if r["existe"]:
        # o mesmo aviso do "Carregar a sequência aberta": a hora do salvamento e se o Premiere tem mudança não salva
        import premiere_copia

        r["salvo"] = os.path.getmtime(prproj)
        r["alterado"] = premiere_copia._alterado_no_premiere(prproj)
    import premiere_ponte

    try:
        seqs = premiere_ponte.chamar("dlpcSequencias", prazo=15).get("sequencias") or []
        r["nome"] = next((x.get("nome") or "" for x in seqs if x.get("id") == sid), "")
    except (premiere_ponte.PremiereIndisponivel, premiere_ponte.ExtendScriptFalhou) as e:
        r["aviso"] = str(e)
    return 200, r


@rota("POST", "/app/revisao")
def app_revisao(ctx):
    """Pede ao aplicativo que abra a janela larga de revisão de mídias.

    ## Por que a janela é do aplicativo

    A lista de pendências mostra dois nomes de arquivo lado a lado e precisa de largura;
    o painel dentro do Media Composer é estreito de propósito. A tentativa anterior —
    um **segundo `uiItem` no manifesto** — foi abandonada com medição: o MC 25.6 cria uma
    entrada-PAI morta a partir do `displayName` quando há mais de um item (dois viram
    TRÊS entradas em Tools), e espalhar os itens por menus diferentes **não resolve**,
    porque o 25.6 ignora o `menuName` (medido 2026-08-17).

    ## Como o pedido chega lá — sem rede

    Reinvocando o próprio executável do aplicativo com `--revisao`. O `single_instance`
    do Tauri entrega os argumentos da segunda execução à instância **que já está viva**,
    que é quem tem a janela na mão. Não há socket, porta nem protocolo novo para manter.

    ⚠️ `Popen` e não `run`: a segunda execução só existe para entregar o argumento e
    morrer, mas quem decide isso é o `single_instance` do outro lado. Esperar por ela
    seria pendurar o painel numa decisão que não é nossa.
    A janela aponta para `/painel?vista=revisao` — a UI que já existe —, e por isso é
    same-origin com esta API: o portão a aceita sem nenhuma exceção nova.
    """
    return _chamar_app(ctx, "--revisao")


@rota("POST", "/app/revisao/fechar")
def app_revisao_fechar(ctx):
    """O "Concluir revisão" da janela larga — o simétrico de `app_revisao`.

    ⭐ Não há nada a "enviar" aqui: cada decisão do editor já foi gravada no serviço no
    instante do clique, e o painel dentro do Media Composer relê o estado sozinho. Esta
    rota só fecha a janela. Um endpoint que parecesse "salvar" sugeriria que fechar no X
    perderia o trabalho — e perder trabalho de revisão por causa de um gesto de janela é
    exatamente o que este projeto não faz.
    """
    return _chamar_app(ctx, "--fechar-revisao")


@rota("POST", "/app/janela")
def app_janela(ctx):
    """A revisão de mídias DENTRO da janela única (organograma aprovado em 2026-10-19): `{"larga": true}` alarga a
    janela para a esquerda; `false` a devolve ao tamanho de antes. Pelo mesmo caminho da revisão (o executável)."""
    return _chamar_app(ctx, "--janela-larga" if (ctx.json() or {}).get("larga") is True else "--janela-painel")


@rota("POST", "/app/fechar")
def app_fechar(ctx):
    """Fechar o app (o X da janela única, depois de o painel conferir que nada está em andamento — ou de o editor
    confirmar). Encerra o serviço junto: é o app quem o sobe e quem o desce."""
    return _chamar_app(ctx, "--encerrar")


@rota("GET", "/app/diagnostico")
def app_diagnostico(ctx):
    """⚙ › Diagnóstico: o que a janela antiga do app mostrava ("no ar · porta · processo")."""
    import os

    from .portao import PORTA

    return 200, {"porta": PORTA, "pid": os.getpid(), "app": bool(ctx.servico.app_exe)}


@rota("POST", "/app/liberar-porta")
def app_liberar_porta(ctx):
    """⚙ › Diagnóstico › Liberar a porta do Media Composer: o mesmo `plataforma.liberar_gateway` do
    `--liberar-porta` (o gateway órfão do Panel SDK segurando 4920/4930), agora pela engrenagem do painel."""
    import plataforma

    return 200, plataforma.liberar_gateway(todos=False)


@rota("POST", "/app/fixar")
def app_fixar(ctx):
    """O pino da janela do Media Composer no app: manter na frente das outras (`{"fixar": true}`) ou soltar.

    ⭐ Pedido do autor (2026-10-18): para arrastar da bin do MC, ele clica no Avid — que vem para a frente e esconde a
    janela do De Lá Pra Cá, e ele tinha de reposicionar o MC para ter onde soltar. Fixada, ela fica por cima.
    Mesmo caminho da revisão: a página é remota e não tem ponte com o Tauri (de propósito); quem mexe na janela é o
    executável, pelo `single_instance`.
    """
    fixar = bool((ctx.json() or {}).get("fixar"))
    return _chamar_app(ctx, "--fixar-mc" if fixar else "--soltar-mc")


def _chamar_app(ctx, argumento: str):
    """Reinvoca o executável do aplicativo com um argumento. O `single_instance` do Tauri
    entrega à instância viva; esta segunda execução só existe para carregar o recado.

    ⚠️ `Popen` e não `run`: quem decide que a segunda execução morre logo é o
    `single_instance` do outro lado. Esperar por ela penduraria o painel numa decisão que
    não é nossa.
    """
    import subprocess

    import plataforma

    exe = ctx.servico.app_exe
    if not exe:
        # ⭐ Não é erro, e por isso não é 4xx/5xx: é o serviço rodando sem aplicativo —
        # a bancada (`dev.ps1`) e a instalação só-plugin. O painel resolve as pendências
        # na própria janela, apertado mas inteiro. Recusar a revisão porque a janela
        # bonita não existe seria derrubar o trabalho no acessório.
        return 200, {"janela": False, "motivo": "sem aplicativo"}
    try:
        subprocess.Popen([exe, argumento], **plataforma.SEM_JANELA)
    except OSError as e:
        log.warning("não consegui chamar o aplicativo (%s %s): %s", exe, argumento, e)
        return 200, {"janela": False, "motivo": str(e)}
    return 200, {"janela": True}


# ── seletores nativos ───────────────────────────────────────────────────────

@rota("POST", "/escolher/pasta")
def escolher_pasta_rota(ctx):
    """Abre o seletor de pasta do sistema. Ver `escolher.py` sobre por que não é o
    `<input type=file>` do painel."""
    import escolher as escolher_mod
    from escolher import NaoSuportado, escolher_pastas
    try:
        caminhos = escolher_pastas()
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    # `caminhos` é a lista (o seletor moderno aceita várias de uma vez); `caminho`
    # continua saindo para não quebrar quem só lia o primeiro. Lista vazia = cancelou.
    resposta = {"caminhos": caminhos, "caminho": caminhos[0] if caminhos else None}
    # Se o diálogo moderno caiu para o antigo, o editor merece saber por quê — ele viu
    # duas janelas abrirem e não tem como adivinhar o motivo.
    if escolher_mod.ultimo_erro:
        resposta["aviso"] = ("o seletor moderno falhou e usei o antigo: "
                             + escolher_mod.ultimo_erro)
    return 200, resposta


# ── banco de mídias ─────────────────────────────────────────────────────────
#
# ⭐ A configuração vive na PASTA DO PROJETO, não na máquina — é o que faz o banco seguir
# o projeto sem ninguém configurar nada, e o que desconecta ao trocar de projeto sem uma
# linha de código para isso. Ver `banco.py`.
#
# ⚠️ Todas estas rotas precisam saber QUAL projeto está aberto, e só o Media Composer
# sabe. Sem ele no ar não há o que responder — e é 409, não erro: o editor fechou o Avid,
# não há defeito nenhum.

def _pasta_do_projeto(ctx) -> str:
    from avid.mcapi import McApiIndisponivel

    with ctx.servico.media_composer() as mc:
        if not mc.esta_vivo():
            return ""
        # o gateway vivo com o MC fechado (medido no Mac, 2026-10-05) é o caso comum, não um erro: cada
        # rota já responde "o Media Composer não respondeu" com a pasta vazia
        try:
            return (mc.projeto() or {}).get("path") or ""
        except McApiIndisponivel:
            return ""


@rota("GET", "/banco")
def banco_estado(ctx):
    """Há banco conectado neste projeto? Qual, e com o quê dentro?"""
    import banco

    pasta = _pasta_do_projeto(ctx)
    if not pasta:
        return 409, {"erro": "o Media Composer não respondeu"}
    return 200, banco.estado(pasta)


@rota("POST", "/banco/criar")
def banco_criar(ctx):
    """Diálogo *Salvar como* → cria o banco → conecta este projeto a ele.

    O nome sugerido é o do projeto: é o que o editor ia digitar de qualquer jeito.
    """
    import banco
    from escolher import NaoSuportado, nomear_arquivo

    pasta = _pasta_do_projeto(ctx)
    if not pasta:
        return 409, {"erro": "o Media Composer não respondeu"}
    try:
        escolhido = nomear_arquivo("Onde criar o banco de mídias", Path(pasta).name)
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    if not escolhido:
        return 200, {"cancelado": True, **banco.estado(pasta)}
    try:
        return 200, banco.criar(pasta, escolhido)
    except (ValueError, RuntimeError) as e:
        return 400, {"erro": str(e)}


@rota("POST", "/banco/conectar")
def banco_conectar(ctx):
    """Diálogo de arquivo → aponta para o `banco.json` de um banco existente."""
    import banco
    from escolher import NaoSuportado, escolher_arquivo

    pasta = _pasta_do_projeto(ctx)
    if not pasta:
        return 409, {"erro": "o Media Composer não respondeu"}
    try:
        escolhido = escolher_arquivo("Escolha o banco.json do banco de mídias", ("json",))
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    if not escolhido:
        return 200, {"cancelado": True, **banco.estado(pasta)}
    try:
        return 200, banco.conectar(pasta, escolhido)
    except (ValueError, RuntimeError) as e:
        return 400, {"erro": str(e)}


@rota("POST", "/banco/desconectar")
def banco_desconectar(ctx):
    """Desliga o projeto do banco. ⚠️ Não apaga banco nenhum — só o ponteiro."""
    import banco

    pasta = _pasta_do_projeto(ctx)
    if not pasta:
        return 409, {"erro": "o Media Composer não respondeu"}
    return 200, banco.desconectar(pasta)


@rota("POST", "/escolher/timeline")
def escolher_timeline_rota(ctx):
    """Abre o seletor de arquivo, filtrado nas extensões que sabemos ler."""
    from escolher import NaoSuportado, escolher_arquivo
    try:
        caminho = escolher_arquivo("Escolha a timeline (AAF, bin do Avid ou projeto do Premiere)", EXTENSOES_TIMELINE)
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    if caminho and Path(caminho).suffix.lower().lstrip(".") not in EXTENSOES_TIMELINE:
        return 400, {"erro": f"só sei ler {', '.join(EXTENSOES_TIMELINE)} por enquanto"}
    return 200, {"caminho": caminho}


# ── o trabalho ──────────────────────────────────────────────────────────────

@rota("GET", "/trabalho")
def trabalho_estado(ctx):
    return 200, ctx.servico.sessao.instantaneo()


@rota("GET", "/trabalho/quadro")
def trabalho_quadro(ctx):
    """Um quadro (JPEG, 320 px) do daily ou de um candidato do trabalho ATUAL — a janela de conflito compara o daily com
    cada candidato (autor, 2026-11-22). `?arquivo=<caminho>&t=<segundos>`. ⛔ Só arquivos que o trabalho já conhece
    (daily, candidatos, o escolhido): a rota não lê um caminho qualquer do disco."""
    import subprocess
    import urllib.parse

    from media import fftools

    q = urllib.parse.parse_qs(ctx.query or "")
    arquivo = (q.get("arquivo") or [""])[0]
    try:
        t = max(0.0, float((q.get("t") or ["0"])[0]))
    except ValueError:
        return 400, {"erro": "t inválido"}
    conhecidos = set()
    for m in ctx.servico.sessao.masters():
        conhecidos.update(x for x in (m.get("daily"), m.get("arquivo"), m.get("sugestao")) if x)
        conhecidos.update(c.get("path") for c in m.get("candidatos") or [] if c.get("path"))
    if arquivo not in conhecidos:
        return 404, {"erro": "arquivo fora do trabalho atual"}
    chave = (arquivo, round(t, 2))
    if chave not in _QUADROS:
        try:
            r = subprocess.run([fftools.ffmpeg(), "-v", "error", "-ss", f"{t:.3f}", "-i", arquivo, "-frames:v", "1",
                                "-vf", "scale=320:-2", "-f", "image2", "-c:v", "mjpeg", "-q:v", "4", "pipe:1"],
                               capture_output=True, timeout=30)
        except (OSError, subprocess.SubprocessError) as e:
            return 500, {"erro": f"o quadro não saiu: {e}"}
        if not r.stdout:
            return 500, {"erro": "o quadro não saiu"}
        if len(_QUADROS) > 200:
            _QUADROS.clear()
        _QUADROS[chave] = r.stdout
    return 200, _QUADROS[chave], "image/jpeg"


#: quadros já tirados nesta sessão do serviço ({(arquivo, t): jpeg}); some ao reiniciar
_QUADROS: dict = {}


@rota("GET", "/trabalho/masters")
def trabalho_masters(ctx):
    """A lista da tela de revisão. `?revisao=1` traz só o que precisa de decisão."""
    so_revisao = "revisao=1" in (ctx.query or "")
    return 200, {"masters": ctx.servico.sessao.masters(so_revisao=so_revisao)}


def _depois_de_preparar(sessao, corpo: dict, previa: bool) -> None:
    """O que o pedido diz sobre o trabalho NOVO. ⛔ CORRIGE (2026-10-13): os achatamentos eram gravados no trabalho
    ANTERIOR, logo antes de `sessao.preparar` criar o novo com os padrões — desmarcar "desfazer subclipes" antes de
    relinkar não valia (só o `onchange` depois da preparação chegava)."""
    t = sessao.trabalho
    t.achatar_subclipes = bool(corpo.get("achatar_subclipes", True))
    t.achatar_group_clips = bool(corpo.get("achatar_group_clips", True))
    t.previa = previa


@rota("POST", "/trabalho/preparar")
def trabalho_preparar(ctx):
    """Dispara a leitura + o match. Devolve na hora; o andamento vai por `/progresso`.

    Aceita `aaf` (o arquivo que o editor recebeu) **ou** `sequence_mob_id` (exporta do
    MC). O primeiro é o caso comum do editor online e poupa um export.
    """
    corpo = ctx.json()
    servico = ctx.servico
    # ⭐ A PRÉVIA da lista de mídias (organograma "Um painel, três NLEs": a lista no painel, como no Resolve). O
    # painel a dispara sozinho quando tem timeline e pastas; ela só lê e casa. ⛔ Nunca exporta: sem a bin da
    # timeline, recusa (`sem_previa`) em vez de cair no ExportFile — export é caminho vetado e caro.
    previa = bool(corpo.get("previa"))
    pastas = [p for p in (corpo.get("pastas") or []) if p]
    try:
        pastas = [_pasta_valida(p) for p in pastas]
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}

    # ⭐ Qual projeto está aberto decide QUAL banco de mídias vale — a configuração mora
    # na pasta dele (`banco.py`). Uma chamada de ~500 ms no começo de um trabalho que
    # leva segundos a minutos; sem banco conectado, o custo não compra nada e por isso
    # fica aqui, e não no laço de nada.
    projeto_aberto = _pasta_do_projeto(ctx)

    # ⛔ A pasta de mídia VOLTOU A SER OBRIGATÓRIA (2026-08-17), mesmo com banco conectado.
    #
    # ⚠️⚠️ Dispensá-la deixou o `LinkFile` do Media Composer **muito** mais lento — o
    # editor mediu 3m49s onde antes eram segundos, com a mesma mídia. A hipótese que
    # explica: **a varredura fazia DOIS trabalhos**. Além de casar, ela lê o metadado de
    # cada candidato, e isso puxa os cabeçalhos dos arquivos para o cache do sistema
    # operacional. O `LinkFile` abre os mesmos arquivos logo depois e encontrava tudo
    # quente. Sem varredura, o `LinkFile` passou a ser o PRIMEIRO leitor e pagou a
    # leitura fria — dentro do Avid, onde é mais caro e ainda bloqueia a API.
    #
    # ⭐ Ou seja: o atalho não economizava, **mudava o custo de lugar** — e para um lugar
    # pior. O ganho medido do banco (21%, ADR 0014) foi apurado com as pastas apontadas,
    # e continua valendo: o banco segue acelerando o CASAMENTO. O que sai é só a dispensa
    # da pasta.
    #
    # ⚠️ Hipótese, não fato: falta medir `LinkFile` com e sem varredura prévia sobre a
    # mesma mídia. Enquanto não houver medida, vale a decisão do editor — que é quem
    # pagou os 3m49s. Ver `modelagens/.../ameacas.yaml` T-11 e o ADR 0014.
    if not pastas:
        return 400, {"erro": "aponte ao menos uma pasta de mídia"}

    # ⛔ Dentro da Avid MediaFiles só valem MXF e UME (autor, 2026-10-25; guarda 1 de `media/pmr.py`): outra pasta lá
    # dentro é mídia tirada do Avid de propósito e sai da lista antes de qualquer varredura.
    from media.pmr import tipo_da_pasta

    fora = [p for p in pastas if tipo_da_pasta(p) == "fora"]
    if fora:
        log.info("pastas desconectadas da Avid MediaFiles fora da varredura: %s", fora)
        pastas = [p for p in pastas if p not in fora]
        if not pastas:
            return 400, {"erro": "essa pasta está DENTRO da Avid MediaFiles mas não é MXF nem UME — é mídia tirada do "
                                 "Avid de propósito. Aponte a Avid MediaFiles (ou a MXF/UME) ou uma pasta de link"}

    # ⭐ O projeto do PREMIERE no modo Media Composer (organograma Premiere → Avid, 2026-10-25): a mesma lista de mídias
    # do relink, com um master por arquivo da sequência; o Relinkar monta pelo `prproj_avid.montar`.
    prproj = corpo.get("prproj") or ""
    if prproj:
        try:
            prproj = _arquivo_valido(prproj, ".prproj")
        except CaminhoInvalido as e:
            return 400, {"erro": str(e)}
        seq = (corpo.get("sequence_mob_id") or "").strip()
        if not seq:
            return 400, {"erro": "escolha a sequência do projeto do Premiere"}
        if not projeto_aberto:
            return 409, {"erro": "abra o projeto no Media Composer: a timeline é entregue na pasta dele"}
        # a Avid MediaFiles indicada é mídia GERENCIADA: nunca vira pasta de link (o casamento com o MXF por nome, TC e
        # duração é a camada 1 do organograma — ⏳); só as outras vão para a varredura de link
        de_link = [p for p in pastas if tipo_da_pasta(p) == "link"]
        if not de_link:
            return 400, {"erro": "a Avid MediaFiles indicada ainda não é casada com o projeto do Premiere — aponte também "
                                 "a pasta dos arquivos (MP4, MOV, WAV) que o projeto usa"}
        sessao = servico.sessao
        try:
            sessao.preparar("", de_link, corpo.get("sequence") or seq, rota="prproj", sequence_mob_id=seq,
                            prproj=prproj, pasta_projeto=projeto_aberto)
        except RuntimeError as e:
            return 409, {"erro": str(e)}
        try:
            from sessao_receber import lembrar_pastas

            lembrar_pastas(prproj, pastas)      # o mesmo projeto volta com as mesmas pastas (autor, 2026-10-03)
        except Exception:  # noqa: BLE001 — lembrar é conveniência
            pass
        _depois_de_preparar(sessao, corpo, previa)
        return 200, {"ok": True, "rota": "prproj", "prproj": prproj}

    # ⭐ A bin de FORA (organograma "Um painel, três NLEs", 2026-10-12): outra máquina, outro projeto ou o anexo do
    # Magic Link. Mesma rota `.avb` da bin do editor, mas LIDA no lugar (nunca tocada) e entregue na pasta do
    # projeto aberto — ver `relink_avb.aplicar(pasta_saida=…)`. A sequência vai pelo MobID que `/mc/bin/ler` deu.
    externa = corpo.get("bin_externa") or ""
    if externa:
        try:
            externa = _arquivo_valido(externa, ".avb")
        except CaminhoInvalido as e:
            return 400, {"erro": str(e)}
        mob_id = (corpo.get("sequence_mob_id") or "").strip()
        if not mob_id:
            return 400, {"erro": "escolha a sequência da bin"}
        if not projeto_aberto:
            return 409, {"erro": "abra o projeto no Media Composer: a bin relinkada é entregue na pasta dele"}
        sessao = servico.sessao
        sessao.trabalho.achatar_subclipes = bool(corpo.get("achatar_subclipes", True))
        sessao.trabalho.achatar_group_clips = bool(corpo.get("achatar_group_clips", True))
        try:
            sessao.preparar("", pastas, corpo.get("sequence") or "sequence", rota="avb",
                            bin_origem=externa, sequence_mob_id=mob_id, bin_externa=True,
                            so_importados=bool(corpo.get("so_importados")),
                            so_offline=bool(corpo.get("so_offline")),
                            pasta_projeto=projeto_aberto)
        except RuntimeError as e:
            return 409, {"erro": str(e)}
        _depois_de_preparar(sessao, corpo, previa)
        return 200, {"ok": True, "rota": "avb", "bin": externa, "externa": True}

    aaf = corpo.get("aaf") or ""
    if aaf:
        try:
            aaf = _arquivo_valido(aaf, ".aaf")
        except CaminhoInvalido as e:
            return 400, {"erro": str(e)}
        sequence = corpo.get("sequence") or Path(aaf).stem
    else:
        mob_id = corpo.get("sequence_mob_id")
        if not mob_id:
            return 400, {"erro": "informe `aaf` ou `sequence_mob_id`"}

        # ⭐ ROTA `.avb` (ADR 0013), a ÚNICA: edita a bin que contém a timeline — sem `ExportFile`, sem preset e sem
        # `ImportFile`, e o áudio entra autorado, sem o modal `Audio Start-Time Options` que congela a API.
        # ⛔ CORRIGE (autor, 2026-10-13): havia aqui uma rota AAF de reserva — timeline sem bin achada → ExportFile do
        # MC. Export para extrair timeline é caminho VETADO (memória "nunca ExportFile para extrair timeline"; com preset
        # errado foram 26 min de WAVE). Sem a bin, recusa e diz o que fazer.
        with servico.media_composer() as mc:
            if not mc.esta_vivo():
                return 409, {"erro": "o Media Composer não respondeu"}
            bin_origem = mc.bin_do_mob(mob_id)
            sequence = corpo.get("sequence") or "sequence"
            # ⚠️⚠️ Salvar ANTES de ler: uma bin com alterações não salvas existe só
            # na memória do MC e o arquivo pode ser uma casca de 53 KB com ZERO mobs
            # (medido). Ler dali dá 0 masters — número plausível que levava o fluxo
            # até "nada a decidir", culpando o acervo.
            mobs = 0
            if bin_origem and Path(bin_origem).is_file():
                import relink_avb

                mobs = relink_avb.garantir_bin_no_disco(mc, bin_origem)
                if not mobs:
                    log.warning("a bin %s não tem mobs no disco", bin_origem)
        if not (bin_origem and mobs and Path(bin_origem).is_file()):
            log.info("sem bin no disco para o mob %s — recusado (sem export)", mob_id)
            return 409, {"erro": "não achei a bin desta timeline no disco — ela precisa estar numa bin salva do "
                                 "projeto aberto (salve a bin e tente de novo)",
                         "sem_previa": True}
        sessao = servico.sessao
        try:
            sessao.preparar("", pastas, sequence, rota="avb",
                            bin_origem=bin_origem, sequence_mob_id=mob_id,
                            so_importados=bool(corpo.get("so_importados")),
                            so_offline=bool(corpo.get("so_offline")),
                            # os masters da seleção da timeline (`/mc/selecao`): só eles entram no relink
                            so_masters=[str(m) for m in corpo.get("so_masters") or [] if m][:2000],
                            pasta_projeto=projeto_aberto)
        except RuntimeError as e:
            return 409, {"erro": str(e)}
        _depois_de_preparar(sessao, corpo, previa)
        return 200, {"ok": True, "rota": "avb", "bin": bin_origem}

    sessao = servico.sessao
    sessao.trabalho.achatar_subclipes = bool(corpo.get("achatar_subclipes", True))
    sessao.trabalho.achatar_group_clips = bool(corpo.get("achatar_group_clips", True))
    try:
        # ⚠️ Na rota AAF os filtros são ACEITOS e não descartam nada: o leitor de AAF não
        # sabe dizer se um master é AMA nem se está offline, e `None` sempre passa (ver
        # `relink.filtrar_masters`). Recusar o pedido seria pior — o editor marcaria a
        # caixa e o plugin diria que não dá, sem que ele possa fazer nada a respeito.
        sessao.preparar(aaf, pastas, sequence,
                        so_importados=bool(corpo.get("so_importados")),
                        so_offline=bool(corpo.get("so_offline")),
                        pasta_projeto=projeto_aberto)
    except RuntimeError as e:
        return 409, {"erro": str(e)}
    _depois_de_preparar(sessao, corpo, previa)
    return 200, {"ok": True, "aaf": aaf}


@rota("POST", "/trabalho/assumir")
def trabalho_assumir(ctx):
    """O "Relinkar" aproveita a prévia pronta (mesma timeline, mesmas pastas): ela deixa de ser prévia e vira o
    trabalho da revisão — sem ler e casar de novo."""
    sessao = ctx.servico.sessao
    if sessao.ocupada:
        return 409, {"erro": "a prévia ainda está casando"}
    sessao.trabalho.previa = False
    return 200, sessao.instantaneo()


@rota("POST", "/trabalho/escolher")
def trabalho_escolher(ctx):
    """O editor confirma uma sugestão, troca um candidato ou descarta um master."""
    corpo = ctx.json()
    mob_id = corpo.get("mob_id")
    if not mob_id:
        return 400, {"erro": "informe `mob_id`"}
    escolhas = ctx.servico.sessao.trabalho.escolhas
    arquivo = corpo.get("arquivo")
    if arquivo:
        try:
            escolhas[mob_id] = _arquivo_valido(arquivo)
        except CaminhoInvalido as e:
            return 400, {"erro": str(e)}
    else:
        escolhas.pop(mob_id, None)   # sem arquivo = desfazer a escolha
    return 200, {"ok": True, "decididos": len(ctx.servico.sessao.trabalho.decididos())}


@rota("POST", "/trabalho/ignorar")
def trabalho_ignorar(ctx):
    """Ignorar (autor, 2026-10-13, como no Resolve): o link destes masters não muda. `ignorar: false` desfaz."""
    corpo = ctx.json()
    ids = [i for i in (corpo.get("mob_ids") or []) if i]
    if not ids:
        return 400, {"erro": "informe `mob_ids`"}
    t = ctx.servico.sessao.trabalho
    if corpo.get("ignorar", True):
        t.ignorados.update(ids)
    else:
        t.ignorados.difference_update(ids)
    return 200, {"ok": True, "ignorados": len(t.ignorados), "decididos": len(t.decididos())}


@rota("POST", "/escolher/midia")
def escolher_midia_rota(ctx):
    """O diálogo do relink manual: um arquivo de mídia (as extensões do indexador; "Todos os arquivos" também)."""
    from escolher import NaoSuportado, escolher_arquivo
    from media.indexer import VIDEO_EXTENSIONS

    nome = (ctx.json().get("nome") or "").strip()
    titulo = f"Relink manual: o arquivo para “{nome}”" if nome else "Relink manual: escolha o arquivo"
    try:
        caminho = escolher_arquivo(titulo[:120], tuple(sorted(e.lstrip(".") for e in VIDEO_EXTENSIONS)))
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    return 200, {"caminho": caminho}


@rota("POST", "/trabalho/manual")
def trabalho_manual(ctx):
    """Relink manual: `mob_id` + `arquivo`. A escolha do editor vence toda regra automática; só o impossível é
    recusado (422, com o motivo) — ver `relink_manual.validar`. `arquivo` vazio desfaz a escolha."""
    import relink_manual

    corpo = ctx.json()
    mob_id = (corpo.get("mob_id") or "").strip()
    if not mob_id:
        return 400, {"erro": "informe `mob_id`"}
    sessao = ctx.servico.sessao
    if sessao.ocupada:
        return 409, {"erro": "espere a leitura (ou o relink) terminar"}
    t = sessao.trabalho
    arquivo = (corpo.get("arquivo") or "").strip()
    if not arquivo:
        t.escolhas.pop(mob_id, None)
        return 200, {"ok": True, "desfeito": True}
    try:
        arquivo = _arquivo_valido(arquivo)
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}
    if not relink_manual.e_midia(arquivo):
        return 422, {"recusa": "esse arquivo não é de mídia (vídeo, áudio ou imagem)"}
    master = next((m for m in sessao.masters() if m.get("mob_id") == mob_id), None)
    if master is None:
        return 404, {"erro": "esta mídia não está na leitura atual — leia a sequência de novo"}
    sonda = relink_manual.sondar(arquivo)
    aceito, texto = relink_manual.validar(master, sonda)
    log.info("relink manual %s → %s: %s (%s)", master.get("nome"), arquivo, "aceito" if aceito else "recusado", texto)
    if not aceito:
        return 422, {"recusa": texto, "arquivo": arquivo}
    t.escolhas[mob_id] = arquivo
    t.ignorados.discard(mob_id)       # escolher um arquivo é o contrário de ignorar
    return 200, {"ok": True, "arquivo": arquivo, "texto": texto, "codec": sonda.get("codec") or "",
                 "decididos": len(t.decididos())}


@rota("POST", "/trabalho/opcoes")
def trabalho_opcoes(ctx):
    """Os dois checkboxes de achatamento."""
    corpo = ctx.json()
    t = ctx.servico.sessao.trabalho
    if "achatar_subclipes" in corpo:
        t.achatar_subclipes = bool(corpo["achatar_subclipes"])
    if "achatar_group_clips" in corpo:
        t.achatar_group_clips = bool(corpo["achatar_group_clips"])
    return 200, {"achatar_subclipes": t.achatar_subclipes,
                 "achatar_group_clips": t.achatar_group_clips}


@rota("POST", "/trabalho/aplicar")
def trabalho_aplicar(ctx):
    """Traz os originais online e entrega a bin. É o passo lento — ~750 ms por arquivo."""
    servico = ctx.servico
    with servico.media_composer() as mc:
        if not mc.esta_vivo():
            return 409, {"erro": "o Media Composer não respondeu"}
        projeto = (mc.projeto() or {}).get("path") or ""
        from avid.acoes import Acoes
        pedido = (ctx.json().get("nome_bin") or "").strip()
        # ⭐ Nome VAZIO é o caso comum, não o excepcional: o editor que não se importa com
        # o nome não deveria ter de inventar um. O padrão é o nome do PROJETO numerado —
        # `PRODUCAO-A 1`, `PRODUCAO-A 2` —, que diz de onde a bin veio e em que tentativa,
        # sem o editor digitar nada. (Antes era o literal "RELINK", igual em todo projeto:
        # com dois projetos abertos na semana, as bins não se distinguiam pelo nome.)
        automatico = not pedido
        base = pedido or Path(projeto).name or "RELINK"
        # ⚠️ Sempre um nome NOVO: `OpenBin` numa bin já aberta devolve `Completed` e não
        # relê o disco — o editor veria a versão velha.
        # a entrega da bin do EDITOR mora ao lado dela (`relink_avb.aplicar`), talvez numa subpasta: o nome tem de
        # estar livre lá também (revisão 2026-10-28 — senão o 2º relink gravava por cima do 1º)
        t = getattr(servico.sessao, "trabalho", None)
        ao_lado = (str(Path(t.bin_origem).parent),) if (t is not None and getattr(t, "rota", "") == "avb"
                                                         and getattr(t, "bin_origem", None)
                                                         and not getattr(t, "bin_externa", None)) else ()
        nome_bin = Acoes(mc).nome_de_bin_livre(
            projeto, _nome_de_arquivo(base), sempre_numerar=automatico, tambem=ao_lado)

    if t is not None and getattr(t, "rota", "") == "prproj":
        # só o que a análise OFERECEU, e com o fator dela (o painel diz quais aceitou, não inventa fator)
        oferta = (t.prproj_analise or {}).get("escalas") or {}
        t.prproj_reescalar = {c: oferta[c]["fator"] for c in (ctx.json().get("reescalar") or []) if c in oferta}
    try:
        servico.sessao.aplicar(projeto, nome_bin, str(servico.pasta_trabalho))
    except (RuntimeError, ValueError) as e:
        return 409, {"erro": str(e)}
    return 200, {"ok": True, "bin": nome_bin}


@rota("POST", "/trabalho/cancelar")
def trabalho_cancelar(ctx):
    return 200, {"cancelado": ctx.servico.sessao.cancelar()}


@rota("GET", "/progresso")
def progresso(ctx):
    """SSE: o estado da sessão enquanto ela roda.

    O evento carrega o estado INTEIRO, não um delta. Se o cliente cair no meio de uma
    aplicação de 80 s, a próxima conexão reencontra o estado — não há evento perdido,
    porque nada é entregue por evento.
    """
    return ("sse", ctx.servico.sessao.instantaneo)


# ── Daqui Pra Lá: a timeline sai do Avid ────────────────────────────────────
#
# ⛔⛔ Nada aqui chama `ExportFile` (ADR 0015): a timeline é lida da BIN. O ciclo é o mesmo
# do relink — dispara, devolve na hora, o andamento vai por SSE —, numa sessão própria
# (`sessao_export.py`), porque não há casamento por semelhança nem revisão nesta direção.

@rota("POST", "/export/preparar")
def export_preparar(ctx):
    """O arrasto trouxe uma sequência: acha a bin, salva, lê, resolve os arquivos."""
    from avid.mcapi import mob_id_valido

    corpo = ctx.json()
    mob_id = (corpo.get("mob_id") or "").strip()
    if not mob_id_valido(mob_id):
        return 400, {"erro": "MobID inválido — esperava 64 dígitos hexadecimais"}
    try:
        ctx.servico.sessao_export.preparar(mob_id, (corpo.get("sequence") or "").strip())
    except RuntimeError as e:
        return 409, {"erro": str(e)}
    return 200, {"ok": True}


@rota("GET", "/export")
def export_estado(ctx):
    return 200, ctx.servico.sessao_export.instantaneo()


@rota("GET", "/export/progresso")
def export_progresso(ctx):
    return ("sse", ctx.servico.sessao_export.instantaneo)


@rota("POST", "/export/nome")
def export_nome(ctx):
    """O padrão do campo de nome → o nome final (ou o erro), a cada tecla.

    ⭐ Renderizado AQUI, não no JavaScript: é a mesma gramática que vai gravar o arquivo, e
    um preview que calcula diferente do que grava é mentira com boa aparência (a mesma
    decisão do Órbita, banco `transversal/nomes-por-padrao-wildcard.md`).
    """
    from nomes import export as nomes_export

    corpo = ctx.json()
    modo, campos = _campos_do_nome(ctx, corpo.get("modo"), corpo.get("tipo"))
    r = nomes_export.analisar(corpo.get("padrao") or "", campos)
    r["campos"] = [{"campo": c, "rotulo": rot, "valor": campos[c]}
                   for c, rot in nomes_export.CAMPOS
                   if modo == "insert" or c not in nomes_export.SO_INSERT]
    return 200, r


def _campos_do_nome(ctx, modo, tipo) -> tuple[str, dict]:
    """Os valores dos campos do nome: a sequência do EXPORT (timeline completa) ou a da
    COLETA (insert), e o `%tipo` COR/VFX só no insert."""
    import magic_link
    from nomes import export as nomes_export

    s = ctx.servico.sessao_export
    if modo == "insert":
        seq = (ctx.servico.coleta.sequencia or {}).get("nome") or ""
        rotulo = {"insert_cor": "COR", "insert_vfx": "VFX"}.get(
            magic_link.TIPOS_INSERT.get(str(tipo or "")), "")
        return "insert", nomes_export.valores(seq, s.projeto, tipo=rotulo)
    return "timeline", nomes_export.valores(s.nome_da_sequencia(), s.projeto)


def _nome_do_envio(ctx, corpo: dict, modo: str) -> str:
    """O nome que o EDITOR compôs no painel (`padrao`), renderizado com a MESMA gramática da
    prévia. Sem padrão (painel antigo), o nome da sequência. Levanta ValueError com o motivo."""
    from nomes import export as nomes_export

    # `%tipo` (COR/VFX) vem do CANAL pelo qual o insert vai.
    _modo, campos = _campos_do_nome(ctx, modo, corpo.get("canal") or corpo.get("tipo"))
    padrao = str(corpo.get("padrao") or "")
    if not padrao.strip():
        return campos["sequencia"]
    r = nomes_export.analisar(padrao, campos)
    if r["erro"]:
        raise ValueError("nome: " + r["erro"])
    return r["nome"]


@rota("POST", "/escolher/referencia")
def escolher_referencia_rota(ctx):
    """O vídeo de referência do corte (Importar .prproj, organograma de 2026-10-04)."""
    from escolher import NaoSuportado, escolher_arquivo
    try:
        caminho = escolher_arquivo("Escolha o vídeo de referência", ("mp4", "mov", "mxf"))
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    return 200, {"caminho": caminho}


@rota("POST", "/escolher/destino")
def escolher_destino_rota(ctx):
    """Onde salvar o arquivo exportado: um seletor de PASTA. O nome é o do campo do painel."""
    from escolher import NaoSuportado, escolher_pasta
    try:
        pasta = escolher_pasta("Onde salvar a timeline exportada")
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    return 200, {"caminho": pasta}


@rota("POST", "/export/gerar")
def export_gerar(ctx):
    """`{formato, pasta, padrao, comentario}` → grava o arquivo em `pasta/nome.ext`."""
    from nomes import export as nomes_export
    from sessao_export import com_extensao, formato_valido

    corpo = ctx.json()
    s = ctx.servico.sessao_export
    try:
        formato = formato_valido((corpo.get("formato") or "").strip())
    except ValueError as e:
        return 400, {"erro": str(e)}
    try:
        pasta = _pasta_valida(corpo.get("pasta") or "")
    except CaminhoInvalido as e:
        return 400, {"erro": "escolha onde salvar — " + str(e)}

    r = nomes_export.analisar(corpo.get("padrao") or "",
                              nomes_export.valores(s.nome_da_sequencia(), s.projeto))
    if r["erro"]:
        return 400, {"erro": "nome: " + r["erro"]}
    caminho = _arquivo_livre(com_extensao(str(Path(pasta) / r["nome"]), formato))
    s.producao = str(corpo.get("producao") or "").replace("\0", "")[:100]     # vai na Carta (etapa 4 do Baselight)
    try:
        s.gerar(formato, caminho, Path(caminho).stem, corpo.get("comentario") or "")
    except (RuntimeError, ValueError) as e:
        return 409, {"erro": str(e)}
    return 200, {"ok": True, "arquivo": caminho}


@rota("POST", "/export/cancelar")
def export_cancelar(ctx):
    return 200, {"cancelado": ctx.servico.sessao_export.cancelar()}


# ── Magic Link: enviar pela pasta combinada ─────────────────────────────────
#
# Timeline completa ou INSERT PARA COR/VFX, gravada como Carta Aberta na pasta que o outro lado
# procura (`magic_link.py`). A coleta do insert digita no Media Composer (`coleta.py`, roteiro
# medido em 2026-09-24): coletar e enviar nunca rodam juntos (`trava_magic`).

def _nle(ctx) -> str:
    """Em que NLE o painel está (`?nle=` ou `{nle}` do corpo). Decide de onde vêm os canais.

    ⚠️ Sem `nle`, o serviço em modo RECEPTOR responde como o Resolve: perguntar ao Media
    Composer (que não está lá) estourava o teto de 3 s da casca no `/receber/estado`.
    """
    from urllib.parse import parse_qs

    valor = (parse_qs(ctx.query or "").get("nle") or [""])[0]
    if not valor and ctx.metodo == "POST":
        try:
            valor = str(ctx.json().get("nle") or "")
        except Exception:  # noqa: BLE001 — corpo vazio
            valor = ""
    if not valor and getattr(ctx.servico, "receptor", False):
        return "resolve"
    # o Premiere (2026-10-19) recebe como o Resolve: fora do Media Composer, canais na máquina
    return "resolve" if valor in ("resolve", "premiere") else "mc"


def _canais_cfg(ctx, projeto: str | None = None) -> tuple[dict, str]:
    """`({setor: pasta}, projeto)`. No Media Composer os canais seguem o PROJETO (a produção);
    fora dele (o Resolve), ficam na máquina. Sem MC respondendo, não há canais do projeto."""
    import canais
    import magic_link

    if _nle(ctx) == "resolve":
        return canais.canais_da_maquina(), ""
    if projeto is None:
        try:
            projeto = _pasta_do_projeto(ctx)
        except Exception:  # noqa: BLE001 — sem MC, o painel ainda mostra o resto
            projeto = ""
    return (magic_link.canais_do_projeto(projeto) if projeto else {}), projeto


def _estado_canais(ctx, projeto: str | None = None) -> dict:
    """Os canais (todos os setores), conectados ou não, com o rótulo de cada botão do painel.

    Sem papel (autor, 2026-09-25): a ilha é o que ela CONECTA. A cor conecta só o canal Cor.
    """
    import canais

    cfg, _projeto = _canais_cfg(ctx, projeto)
    lista = []
    for setor, s in canais.SETORES.items():
        lista.append({"setor": setor, "rotulo": s["rotulo"], "de": s["de"], "para": s["para"],
                      "pasta": cfg.get(setor), "conectado": bool(canais.pasta_do_canal(cfg, setor))})
    return {"canais": lista, "lados": canais.ROTULO_LADO}


def _estado_magic(ctx, projeto: str | None = None) -> dict:
    return {**_estado_canais(ctx, projeto),
            "coleta": ctx.servico.coleta.estado(),
            "ultimo_envio": ctx.servico.ultimo_envio}


@rota("GET", "/magic")
def magic_estado(ctx):
    return 200, _estado_magic(ctx)


@rota("GET", "/canais")
def canais_estado(ctx):
    """Os canais (Ajustes, os botões "Enviar para…", a tabela de receber)."""
    return 200, _estado_canais(ctx)


@rota("POST", "/canais/conectar")
def canais_conectar(ctx):
    """`{setor, nle}`: escolhe a pasta do canal (seletor nativo), cria as caixas e guarda."""
    import canais
    import magic_link
    from escolher import NaoSuportado, escolher_pasta

    setor = str(ctx.json().get("setor") or "")
    if not canais.e_setor(setor):
        return 400, {"erro": "canal desconhecido"}
    rotulo = canais.SETORES[setor]["rotulo"]
    try:
        pasta = escolher_pasta(f"Pasta do canal {rotulo} do Magic Link (edição ⇄ {rotulo.lower()})")
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    if not pasta:
        return 200, {"cancelado": True, **_estado_canais(ctx)}
    try:
        pasta = canais.validar_pasta(pasta)
        canais.garantir_pastas(pasta, setor)
        if _nle(ctx) == "resolve":
            canais.guardar_canal_na_maquina(setor, pasta)
            projeto = None
        else:
            projeto = _pasta_do_projeto(ctx)
            if not projeto:
                return 503, {"erro": "o Media Composer não respondeu — o canal fica no projeto"}
            magic_link.guardar_canal_no_projeto(projeto, setor, pasta)
    except (ValueError, RuntimeError) as e:
        return 400, {"erro": str(e)}
    except OSError as e:
        return 400, {"erro": f"não consegui criar as caixas do canal: {e.strerror or e}"}
    return 200, _estado_canais(ctx, projeto)


@rota("GET", "/ajustes/sinais")
def ajustes_sinais(ctx):
    """O código de cores dos Sinais do Import (Ajustes): o desta máquina, o de fábrica, as
    tabelas do Resolve e os avisos de cor repetida."""
    import codigo_de_cores

    return 200, codigo_de_cores.estado()


@rota("POST", "/ajustes/sinais")
def ajustes_sinais_gravar(ctx):
    """`{codigo}` grava o código da equipe; `{fabrica: true}` volta ao de fábrica. Nome que não
    existe nas tabelas volta ao de fábrica (`drp.sinais.validar_codigo`), sem erro."""
    import codigo_de_cores
    from drp import sinais

    corpo = ctx.json()
    novo = sinais.de_fabrica() if corpo.get("fabrica") is True else corpo.get("codigo")
    try:
        return 200, codigo_de_cores.estado(codigo_de_cores.gravar(novo))
    except OSError as e:
        return 500, {"erro": f"não consegui guardar o código de cores: {e.strerror or e}"}


@rota("POST", "/insert/coletar")
def insert_coletar(ctx):
    """O botão Coletar: copia a seleção da timeline e decide o que entra na lista.

    Síncrono de propósito (~8 s, medido): o painel mostra "coletando…" e recebe a decisão —
    inclusive o pedido de OK | Cancelar quando a seleção pega mais de uma trilha.
    """
    from carta_aberta.insert import selecao_da_copia
    from coleta import ColetaFalhou, capturar

    if not ctx.servico.trava_magic.acquire(blocking=False):
        return 409, {"erro": "já há uma coleta ou um envio em andamento"}
    try:
        with ctx.servico.media_composer() as mc:
            if not mc.esta_vivo():
                return 503, {"erro": "o Media Composer não respondeu — ele está aberto?"}
            sequencia, copia, leitura = capturar(mc)
        itens, avisos = selecao_da_copia(copia, leitura)
        decisao = ctx.servico.coleta.decidir(sequencia, itens, avisos)
    except ColetaFalhou as e:
        return 409, {"erro": str(e)}
    finally:
        ctx.servico.trava_magic.release()
    return 200, {"decisao": decisao, **_estado_magic(ctx)}


@rota("POST", "/insert/confirmar")
def insert_confirmar(ctx):
    """A resposta ao OK | Cancelar: `{ok: true|false}`."""
    decisao = ctx.servico.coleta.confirmar(bool(ctx.json().get("ok")))
    return 200, {"decisao": decisao, **_estado_magic(ctx)}


@rota("POST", "/insert/remover")
def insert_remover(ctx):
    """O X de um item: `{chave: [trilha, tc_in, mob_id]}`."""
    chave = ctx.json().get("chave")
    if not isinstance(chave, list) or len(chave) != 3:
        return 400, {"erro": "item inválido"}
    try:
        removido = ctx.servico.coleta.remover(chave)
    except (TypeError, ValueError):
        return 400, {"erro": "item inválido"}
    return 200, {"removido": removido, **_estado_magic(ctx)}


@rota("POST", "/insert/limpar")
def insert_limpar(ctx):
    ctx.servico.coleta.limpar()
    return 200, _estado_magic(ctx)


@rota("POST", "/magic/enviar")
def magic_enviar(ctx):
    """`{tipo: timeline|insert, canal, padrao, comentario, so_video}` → a Carta na caixa de
    entrada do outro lado do CANAL (`canais.py`). O insert pega o tipo do canal.

    `padrao` é o nome que o editor compôs (campos `%sequencia`, `%tipo`…): ele vira o nome da
    Carta e, do outro lado, o nome da timeline. O programa não inventa nome de envio.
    """
    import canais
    import magic_link

    corpo = ctx.json()
    tipo = (corpo.get("tipo") or "").strip()
    canal = str(corpo.get("canal") or "").strip()
    if tipo in magic_link.TIPOS_INSERT:          # painel antigo: {tipo: cor|vfx}
        tipo, canal = "insert", canal or tipo
    comentario = str(corpo.get("comentario") or "")
    if tipo not in ("timeline", "insert"):
        return 400, {"erro": f"tipo de envio desconhecido: {tipo!r}"}
    if not canais.e_setor(canal):
        return 400, {"erro": "escolha para qual canal enviar"}
    try:
        projeto = _pasta_do_projeto(ctx)
    except Exception:  # noqa: BLE001
        projeto = ""
    if not projeto:
        return 503, {"erro": "o Media Composer não respondeu — ele está aberto?"}
    cfg, _p = _canais_cfg(ctx, projeto)
    try:
        pasta = canais.caixa_de_saida(cfg, canal)
        tipo_insert = canais.tipo_do_insert(canal) if tipo == "insert" else None
    except ValueError as e:
        return 400, {"erro": str(e)}
    except OSError as e:
        return 503, {"erro": f"não consegui preparar a pasta do canal: {e.strerror or e}"}

    try:
        nome = _nome_do_envio(ctx, {**corpo, "canal": canal}, tipo)
    except ValueError as e:
        return 400, {"erro": str(e)}

    if tipo == "timeline":
        ctx.servico.sessao_export.producao = str(corpo.get("producao") or "").replace("\0", "")[:100]
        try:
            caminho = ctx.servico.sessao_export.enviar(pasta, comentario, nome=nome,
                                                        canal=canal)
        except (RuntimeError, ValueError) as e:
            return 409, {"erro": str(e)}
        ctx.servico.ultimo_envio = {"tipo": "timeline", "canal": canal, "arquivo": caminho}
        return 200, {"ok": True, "canal": canal, "arquivo": caminho}

    if not ctx.servico.trava_magic.acquire(blocking=False):
        return 409, {"erro": "já há uma coleta ou um envio em andamento"}
    try:
        with ctx.servico.media_composer() as mc:
            resumo = magic_link.enviar_insert(mc, ctx.servico.coleta, tipo_insert, pasta,
                                              comentario, so_video=bool(corpo.get("so_video")),
                                              nome=nome, canal=canal)
    except (LookupError, ValueError, RuntimeError) as e:
        return 409, {"erro": str(e)}
    finally:
        ctx.servico.trava_magic.release()
    ctx.servico.ultimo_envio = {**resumo, "canal": canal}
    return 200, {"ok": True, "canal": canal, **resumo}


@rota("POST", "/insert/exportar")
def insert_exportar(ctx):
    """`{padrao, comentario, so_video}` → a Carta do insert numa pasta que o editor escolhe
    agora (seletor nativo). Fora de canal: o tipo é `insert`, sem setor."""
    import magic_link
    from escolher import NaoSuportado, escolher_pasta

    corpo = ctx.json()
    try:
        nome = _nome_do_envio(ctx, corpo, "insert")
    except ValueError as e:
        return 400, {"erro": str(e)}
    try:
        pasta = escolher_pasta("Onde salvar a Carta do insert")
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    if not pasta:
        return 200, {"cancelado": True}
    if not ctx.servico.trava_magic.acquire(blocking=False):
        return 409, {"erro": "já há uma coleta ou um envio em andamento"}
    try:
        with ctx.servico.media_composer() as mc:
            resumo = magic_link.enviar_insert(mc, ctx.servico.coleta, magic_link.INSERT_EXPORTADO,
                                              pasta, str(corpo.get("comentario") or ""),
                                              so_video=bool(corpo.get("so_video")), nome=nome)
    except (LookupError, ValueError, RuntimeError) as e:
        return 409, {"erro": str(e)}
    finally:
        ctx.servico.trava_magic.release()
    return 200, {"ok": True, **resumo}


# ── Magic Link: RECEBER (a casca do Resolve) ────────────────────────────────
#
# ⚠️ Estas rotas são as ÚNICAS que aceitam o token do arquivo (`X-DeLaPraCa-Token`, ADR 0016):
# o script fala por `curl`, sem `Origin`. Ver `api/portao.py` e `sessao_receber.py`.

def _tocar_receptor(ctx) -> None:
    import time as _t

    ctx.servico.ultimo_uso_receptor = _t.monotonic()


@rota("GET", "/receber/estado")
def receber_estado(ctx):
    """O "estou vivo" da casca, já autenticado: versão e canais."""
    _tocar_receptor(ctx)
    return 200, {"versao": ctx.servico.versao, **_estado_canais(ctx)}


@rota("GET", "/receber/caixa")
def receber_caixa(ctx):
    """Procurar novos: os dois sentidos de cada canal conectado (pendentes e importados)."""
    _tocar_receptor(ctx)
    cfg, _p = _canais_cfg(ctx)
    return 200, ctx.servico.receber.caixa(cfg)


@rota("POST", "/receber/abrir")
def receber_abrir(ctx):
    """Abrir arquivo…: o seletor nativo, e o que há no arquivo (uma Carta, ou as sequências
    de uma bin). Devolve a `chave` que o `POST /receber/preparar` usa como `{avulso}`."""
    from escolher import NaoSuportado, escolher_arquivo
    from sessao_receber import EXTENSOES_RECEBER

    _tocar_receptor(ctx)
    # O arquivo SOLTO na área do bloco 1 (redesenho de 2026-10-05) chega com `caminho`: o mesmo
    # `abrir`, sem o seletor. O que ainda não abre é recusado lá, com o motivo.
    solto = str((ctx.json() or {}).get("caminho") or "")
    if solto:
        try:
            caminho = _arquivo_valido(solto)
        except CaminhoInvalido as e:
            return 400, {"erro": str(e)}
        try:
            return 200, ctx.servico.receber.abrir(caminho)
        except ValueError as e:
            return 400, {"erro": str(e)}
    try:
        # Todos os formatos de timeline que o app vai ler, mesmo os que ainda não lê (autor,
        # 2026-09-29): o que ainda não abre é recusado DEPOIS, com o motivo (`abrir`), em vez de
        # ficar invisível no diálogo.
        caminho = escolher_arquivo("Abrir uma timeline", EXTENSOES_RECEBER)
    except NaoSuportado as e:
        return 501, {"erro": str(e)}
    except RuntimeError as e:
        return 500, {"erro": str(e)}
    if not caminho:
        return 200, {"cancelado": True}
    try:
        return 200, ctx.servico.receber.abrir(caminho)
    except ValueError as e:
        return 400, {"erro": str(e)}


def _pedido_de(corpo: dict) -> dict:
    """A identidade de um Importar: `{id}` (envio de canal) ou `{avulso, mob_id}` (arquivo)."""
    if corpo.get("avulso"):
        return {"avulso": str(corpo.get("avulso") or ""), "mob_id": str(corpo.get("mob_id") or "")}
    return {"id": str(corpo.get("id") or "")}


@rota("POST", "/receber/originais")
def receber_originais(ctx):
    """Casar a timeline com os ORIGINAIS das pastas do colorista, antes de importar (ADR 0020).

    `{id | avulso+mob_id, pastas}` → dispara o MESMO casamento do relink do Avid (rota
    `carta`). Devolve na hora; o andamento vai por `/progresso` e as decisões pela revisão
    (`/trabalho*`). O Importar depois chama `/receber/preparar` com `originais: true`.
    """
    from carta_aberta.reader import CartaInvalida

    _tocar_receptor(ctx)
    corpo = ctx.json()
    try:
        pastas = [_pasta_valida(p) for p in (corpo.get("pastas") or []) if p]
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}
    if not pastas:
        return 400, {"erro": "aponte ao menos uma pasta dos originais"}
    pedido = _pedido_de(corpo)
    try:
        carta = ctx.servico.receber.carta_do_pedido(pedido)
        ctx.servico.sessao.preparar_carta(carta, pastas, pedido)
    except (CartaInvalida, LookupError, ValueError) as e:
        return 409, {"erro": str(e)}
    except RuntimeError as e:
        return 409, {"erro": str(e)}
    return 200, {"ok": True}


@rota("POST", "/receber/analisar")
def receber_analisar(ctx):
    """AAF, bin e Carta na tela "antes de montar" (organograma aprovado pelo autor em 2026-10-19: um fluxo para todo
    protocolo): `{id | avulso+mob_id}` → o resumo da leitura (planos, efeitos, áudio, estimativa da conferência). O
    casamento com os originais segue por `/receber/originais`; a lista, por `/trabalho/masters`."""
    from carta_aberta.reader import CartaInvalida

    _tocar_receptor(ctx)
    try:
        return 200, ctx.servico.receber.analisar_carta(_pedido_de(ctx.json()))
    except (CartaInvalida, LookupError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/receber/prproj/analisar")
def receber_prproj_analisar(ctx):
    """O projeto do Premiere, ANTES de montar (organograma de 2026-10-02/03): `{avulso, mob_id,
    pastas}` → ler a sequência (`mob_id` = o nome dela) e casar cada proxy com o original nas
    pastas. Devolve o resumo da tela "antes de montar"; o andamento vai por `/receber/progresso`.
    Depois, o `/receber/preparar` com o mesmo `{avulso, mob_id}` monta a partir desta análise."""
    from sessao_receber import Cancelado

    _tocar_receptor(ctx)
    corpo = ctx.json()
    try:
        pastas = [_pasta_valida(p) for p in (corpo.get("pastas") or []) if p]
    except CaminhoInvalido as e:
        return 400, {"erro": str(e)}
    try:
        return 200, ctx.servico.receber.analisar_prproj(str(corpo.get("avulso") or ""),
                                                        str(corpo.get("mob_id") or ""), pastas)
    except Cancelado:
        return 409, {"erro": "cancelado", "cancelado": True}
    except (LookupError, ValueError, RuntimeError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/receber/preparar")
def receber_preparar(ctx):
    """Trazer: `{id}` (um envio da pasta combinada) ou `{avulso, mob_id}` (um arquivo aberto
    por `/receber/abrir`) → o DRT temporário com a mídia desta máquina (a casca o importa)."""
    from carta_aberta.reader import CartaInvalida
    from sessao_receber import Cancelado

    _tocar_receptor(ctx)
    corpo = ctx.json()
    originais, raizes = None, None
    if corpo.get("originais"):
        # As decisões do casamento com os originais (`/receber/originais` + revisão) — só se
        # forem DESTA timeline: trocar de linha na tabela no meio não pode misturar.
        s = ctx.servico.sessao
        t = s.trabalho
        if s.ocupada or t.rota != "carta" or t.pedido != _pedido_de(corpo):
            return 409, {"erro": "o casamento com os originais não é desta timeline — "
                                 "aponte as pastas e importe de novo"}
        originais, raizes = t.decididos(), list(t.pastas)
    notas = corpo.get("notas") is True       # a trilha de notas (Sinais do Import)
    sinais = {"marcar": corpo.get("marcar") is True, "colorir": corpo.get("colorir") is True,
              # projeto do Premiere: a caixa "trazer o áudio" (ligada por padrão, 2026-10-04)
              "audio": corpo.get("audio") is not False,
              # e a caixa "nest como Compound Clip" (ligada por padrão, autor 2026-10-04)
              "compound": corpo.get("compound") is not False,
              # e o vídeo de referência indicado à mão + o que fazer com o som dele (A/B/nenhum)
              "som_referencia": corpo.get("som_referencia") if corpo.get("som_referencia")
              in ("A", "B", "nenhum") else "A"}
    # o modo Premiere (2026-10-19): o mesmo Importar, com o plano de montagem no lugar do DRT
    if corpo.get("destino") == "premiere":
        sinais["destino"] = "premiere"
        # Premiere → Premiere (2026-10-22): o nome da cópia, sugerido e editável no painel
        if isinstance(corpo.get("nome_copia"), str):
            sinais["nome_copia"] = corpo["nome_copia"].replace("\0", "")[:120]
        # e o "só offline" da lista de mídias (autor, 2026-10-24): o que está online no projeto fica como está
        sinais["so_offline"] = corpo.get("so_offline") is True
    # o BASELIGHT (proposta 2026-11-22-baselight-no-app, etapa 2): o conform numa scene NOVA do job da produção. Só texto
    # com teto; o nome vira job/scene em `baselight.enviar.limpar_nome` (o `:` separaria host:job:scene).
    if corpo.get("destino") == "baselight":
        sinais["destino"] = "baselight"
        for k in ("job", "scene", "atualizar"):
            if isinstance(corpo.get(k), str) and corpo[k].strip():
                sinais[k] = corpo[k].replace("\0", "")[:100]
        # `atualizar` = a scene do COLORISTA cuja cor vai para a scene nova (atualizar corte, etapa 5)
        # os markers "[Ciclo]" dos planos com problema: o toggle das opções avançadas, ligado por padrão
        sinais["markers"] = corpo.get("markers") is not False
        # a OPÇÃO de trazer os títulos para a scene (texto narrativo/artístico; desligada por padrão — autor, 2026-11-23)
        sinais["titulos"] = corpo.get("titulos") is True
    # Os IGNORADOS da "lista de mídias" (2026-10-06): só identificadores, comparados com o casamento da
    # análise (nada no disco é tocado por eles). Lista de texto, com teto.
    ign = corpo.get("ignorar")
    if isinstance(ign, list):
        sinais["ignorar"] = [x for x in ign[:5000] if isinstance(x, str) and len(x) < 4096]
    # A escala digitada para OUTRA mídia que o editor ACEITOU ajustar (oferta da análise; autor, 2026-10-18):
    # {caminho do projeto: fator}. Só identificadores e números com teto; o serviço confere contra a oferta.
    esc = corpo.get("reescalar")
    if isinstance(esc, dict):
        sinais["reescalar"] = {k: float(v) for k, v in list(esc.items())[:5000]
                               if isinstance(k, str) and len(k) < 4096 and isinstance(v, (int, float))
                               and not isinstance(v, bool) and 0.05 <= v <= 20}
    # e a PROPORÇÃO do próprio arquivo, aceita na mesma oferta (autor, 2026-10-18): só caminhos
    prop = corpo.get("proporcao")
    if isinstance(prop, list):
        sinais["proporcao"] = [x for x in prop[:5000] if isinstance(x, str) and len(x) < 4096]
    if corpo.get("referencia"):
        try:
            sinais["referencia"] = _arquivo_valido(str(corpo.get("referencia")))
        except CaminhoInvalido as e:
            return 400, {"erro": str(e)}
    try:
        if corpo.get("avulso"):
            return 200, ctx.servico.receber.preparar_avulso(str(corpo.get("avulso") or ""),
                                                            str(corpo.get("mob_id") or ""),
                                                            originais, raizes, notas=notas,
                                                            sinais=sinais)
        return 200, ctx.servico.receber.preparar(str(corpo.get("id") or ""), originais, raizes,
                                                 notas=notas, sinais=sinais)
    except Cancelado:
        return 409, {"erro": "cancelado", "cancelado": True}
    except (CartaInvalida, LookupError, ValueError, RuntimeError) as e:
        return 409, {"erro": str(e)}


@rota("GET", "/receber/progresso")
def receber_progresso(ctx):
    """O andamento do Trazer: `{ativo, etapa, indice, etapas, feitos, total, sequencia}`.

    Lido pelo painel enquanto o `POST /receber/preparar` corre noutra thread.
    """
    _tocar_receptor(ctx)
    return 200, ctx.servico.receber.progresso()


@rota("POST", "/receber/cancelar")
def receber_cancelar(ctx):
    """Cancelar o Trazer em curso. Vale entre um arquivo de mídia e outro."""
    _tocar_receptor(ctx)
    return 200, {"ok": ctx.servico.receber.cancelar()}


# ── a conferência pela referência (organograma aprovado pelo autor, 2026-10-04) ──────────────
# O painel conduz: `iniciar` dá os pontos que faltam (com o JPEG de cada um); a casca exporta um
# lote; `quadros` põe o lote na fila de comparação (volta na hora); `estado` dá o placar; `marcas`
# dá os marcadores dos pontos que não conferem, para a casca pôr na timeline.

@rota("POST", "/conferencia/iniciar")
def conferencia_iniciar(ctx):
    from conferencia import conferencias

    _tocar_receptor(ctx)
    corpo = ctx.json()
    try:
        return 200, conferencias().iniciar(str(corpo.get("id") or ""), corpo.get("do_comeco") is True)
    except (LookupError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/conferencia/timeline")
def conferencia_timeline(ctx):
    """A conferência sobre a timeline COMO ELA ESTÁ no Resolve (autor, 2026-10-19): `{uid, nome, drt?, referencia?,
    som?}` → o plano de sempre (`{conferencia: {id, pontos, segundos}, …}`), para o painel conduzir como a de antes.

    Sem `referencia`, o app ACHA a que o editor pôs na timeline (a regra de ofício, ou o vídeo que não estava na mídia
    do `drt` que entregamos). Com ela, se ainda não está na timeline, entra numa trilha nova acima de todas, desligada
    (`som`: o áudio numa trilha nova, sem solo). `{ok: False, sem_referencia}` = o painel pede o vídeo."""
    import os

    import conferencia_timeline as CT
    import resolve_externo as X
    from conferencia import conferencias

    _tocar_receptor(ctx)
    corpo = ctx.json() or {}
    alvo = {"uid": str(corpo.get("uid") or ""), "nome": str(corpo.get("nome") or ""),
            "so_selecionados": corpo.get("so_selecionados") is True}
    arquivo = corpo.get("referencia")
    arquivo = arquivo if isinstance(arquivo, str) and arquivo and "\0" not in arquivo else None
    if arquivo and not os.path.isfile(arquivo):
        return 409, {"ok": False, "erro": "o vídeo de referência não está neste computador"}
    import aviso_ocupado

    try:
        with aviso_ocupado.mudo("esperando o DaVinci Resolve (ler a timeline)"):
            leitura = X.ler_timeline(alvo)
            if not leitura.get("ok"):
                return 409, leitura
            anexada = False
            if arquivo and not any(i.get("tipo") == "video" and CT._norma(i.get("arquivo") or "") == CT._norma(arquivo)
                                   for i in leitura["itens"]):
                r = X.anexar_referencia({**alvo, "arquivo": arquivo, "som": corpo.get("som") is True})
                if not r.get("ok"):
                    return 409, r
                anexada = True
                leitura = X.ler_timeline(alvo)
                if not leitura.get("ok"):
                    return 409, leitura
    except RuntimeError as e:
        return 409, {"ok": False, "erro": str(e)}
    drt = corpo.get("drt")
    entregues = None
    if isinstance(drt, str) and drt and X.drt_confiavel(drt):     # só o DRT que nós gravamos em `recebidos`
        entregues = set(X.midias_do_drt(drt, "midias")) | set(X.midias_do_drt(drt, "depois"))
    c = CT.contexto(leitura, entregues, arquivo)
    if not c.get("ok"):
        return 200, {**c, "anexada": anexada}
    conf = conferencias().criar(c["contexto"], leitura["nome"])
    return 200, {"ok": True, "conferencia": conf, "nome": leitura["nome"], "uid": leitura.get("uid") or alvo["uid"],
                 "referencia": c["referencia"], "trilha_referencia": c["trilha_referencia"], "como": c["como"],
                 "anexada": anexada}


@rota("POST", "/conferencia/quadros")
def conferencia_quadros(ctx):
    from conferencia import conferencias

    _tocar_receptor(ctx)
    corpo = ctx.json()
    q = corpo.get("quadros")
    try:
        return 200, {"na_fila": conferencias().comparar(str(corpo.get("id") or ""),
                                                        q[:500] if isinstance(q, list) else [])}
    except (LookupError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/conferencia/estado")
def conferencia_estado(ctx):
    from conferencia import conferencias

    _tocar_receptor(ctx)
    try:
        return 200, conferencias().estado(str(ctx.json().get("id") or ""))
    except (LookupError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/conferencia/marcas")
def conferencia_marcas(ctx):
    from conferencia import conferencias

    _tocar_receptor(ctx)
    try:
        return 200, conferencias().marcas(str(ctx.json().get("id") or ""))
    except (LookupError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/receber/trazido")
def receber_trazido(ctx):
    """A casca conta como foi: `{id, ok, detalhe}`. Anotado só nesta máquina e, se entrou, a
    Carta desce para `importado` do canal (`{arquivado}`, ou `{aviso}` se a rede recusar)."""
    _tocar_receptor(ctx)
    corpo = ctx.json()
    try:
        tl = corpo.get("timeline") if isinstance(corpo.get("timeline"), dict) else None
        r = ctx.servico.receber.trazido(str(corpo.get("id") or ""), bool(corpo.get("ok")),
                                        str(corpo.get("detalhe") or ""), timeline=tl,
                                        substitui=str(corpo.get("substitui") or ""))
    except (OSError, ValueError) as e:
        return 400, {"erro": str(e)}
    return 200, {"ok": True, **r}


# ── Atualizar timeline (organograma aprovado em 2026-09-27) ─────────────────────
# Sob /receber/ como o resto do receptor: a casca e o painel do NLE que RECEBE.

@rota("POST", "/receber/partidas")
def receber_partidas(ctx):
    """`{id?, timeline?: {uid, nome}}` → as versões ANTIGAS sugeridas (a mais provável 1º): a
    partida da timeline de trabalho, e as que a Carta nova `id` pode atualizar."""
    _tocar_receptor(ctx)
    corpo = ctx.json()
    tl = corpo.get("timeline") if isinstance(corpo.get("timeline"), dict) else None
    try:
        return 200, ctx.servico.receber.partidas_para(str(corpo.get("id") or ""), timeline=tl)
    except (LookupError, ValueError) as e:
        return 409, {"erro": str(e)}


def _versoes(corpo: dict) -> tuple[dict, dict]:
    """As duas versões do Atualizar (organograma de 2026-09-28): `{antiga, nova}`, cada uma
    `{envio}`, `{partida}` ou `{avulso, mob_id}`. O pedido de antes (`{id, partida}`) vale igual."""
    def uma(v) -> dict:
        v = v if isinstance(v, dict) else {}
        for k in ("envio", "partida", "avulso"):
            if v.get(k):
                return {k: str(v[k]), **({"mob_id": str(v.get("mob_id") or "")} if k == "avulso" else {})}
        return {}
    antiga = uma(corpo.get("antiga")) or ({"partida": str(corpo["partida"])} if corpo.get("partida") else {})
    nova = uma(corpo.get("nova")) or ({"envio": str(corpo["id"])} if corpo.get("id") else {})
    return antiga, nova


def _inicio(corpo: dict) -> int | None:
    v = corpo.get("inicio")
    return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None


@rota("POST", "/receber/comparar")
def receber_comparar(ctx):
    """`{antiga, nova, audio, trabalho?, contagem?, inicio?}` → o resumo da atualização (nada muda
    no NLE). Com a timeline de trabalho exportada, vem o `encaixe` da versão antiga com ela."""
    from carta_aberta.reader import CartaInvalida

    _tocar_receptor(ctx)
    corpo = ctx.json()
    antiga, nova = _versoes(corpo)
    contagem = corpo.get("contagem") if isinstance(corpo.get("contagem"), dict) else {}
    try:
        return 200, ctx.servico.receber.comparar_versoes(
            antiga, nova, contar_audio=corpo.get("audio") is True,
            trabalho=str(corpo.get("trabalho") or ""), contagem_api=contagem, inicio=_inicio(corpo))
    except (CartaInvalida, LookupError, OSError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/receber/atualizar")
def receber_atualizar(ctx):
    """`{antiga, nova, trabalho, contagem, marcar, colorir}`: a casca já exportou a timeline de
    trabalho (`trabalho`, em `recebidos/`) e contou os planos (`contagem`). Devolve o DRT reescrito,
    a contagem que a importação tem de bater, o que inserir e os Sinais (`atualizacao.py`)."""
    from carta_aberta.reader import CartaInvalida

    _tocar_receptor(ctx)
    corpo = ctx.json()
    antiga, nova = _versoes(corpo)
    contagem = corpo.get("contagem") if isinstance(corpo.get("contagem"), dict) else {}
    try:
        return 200, ctx.servico.receber.preparar_versoes(
            antiga, nova, str(corpo.get("trabalho") or ""), contagem,
            sinais={"marcar": corpo.get("marcar") is True, "colorir": corpo.get("colorir") is True},
            inicio=_inicio(corpo))
    except (CartaInvalida, LookupError, OSError, ValueError) as e:
        return 409, {"erro": str(e)}


@rota("POST", "/receber/atualizada")
def receber_atualizada(ctx):
    """`{nova, timeline: {uid, nome}, substitui, registro}`: a casca atualizou. A versão nova vira a partida da
    timeline (do canal: o `trazido` de sempre; de um arquivo do disco: a Carta montada dele)."""
    from carta_aberta.reader import CartaInvalida

    _tocar_receptor(ctx)
    corpo = ctx.json()
    _antiga, nova = _versoes(corpo)
    tl = corpo.get("timeline") if isinstance(corpo.get("timeline"), dict) else None
    try:
        r = ctx.servico.receber.atualizada(nova, tl, substitui=str(corpo.get("substitui") or ""),
                                           registro=str(corpo.get("registro") or ""))
    except (CartaInvalida, LookupError, OSError, ValueError) as e:
        return 409, {"erro": str(e)}
    return 200, {"ok": True, **r}


@rota("GET", "/ajustes/atualizar")
def ajustes_atualizar(ctx):
    import partidas

    return 200, {"faixas": list(partidas.faixas()), "fabrica": list(partidas.FAIXAS_DE_FABRICA)}


@rota("POST", "/ajustes/atualizar")
def ajustes_atualizar_gravar(ctx):
    """`{faixas: [a, b]}` ou `{fabrica: true}`. Fora de 0 < a < b ≤ 100 volta o de fábrica."""
    import partidas

    corpo = ctx.json()
    f = corpo.get("faixas") if isinstance(corpo.get("faixas"), list) and len(corpo["faixas"]) == 2         else partidas.FAIXAS_DE_FABRICA
    if corpo.get("fabrica") is True:
        f = partidas.FAIXAS_DE_FABRICA
    try:
        return 200, {"faixas": list(partidas.gravar_faixas(*f)), "fabrica": list(partidas.FAIXAS_DE_FABRICA)}
    except OSError as e:
        return 500, {"erro": f"não consegui guardar as faixas: {e.strerror or e}"}


# ── cache e logs (organograma aprovado pelo autor em 2026-10-05) ──────────────────────────
# O app (⚙ Configurações, a vista `?vista=configuracoes` desta mesma UI) lê, salva, limpa e abre;
# o painel (⚙ Ajustes, MC e Resolve) lê, limpa e abre. Pastas se abrem pelo NOME (`qual`), nunca
# por um caminho vindo de fora — a trava do `/folder/open` do Órbita.

def _ocupado(servico) -> str:
    """Por que não dá para limpar agora ("" = dá): nada se limpa no meio de um trabalho."""
    from conferencia import conferencias

    if servico.sessao.ocupada or servico.sessao_export.ocupada:
        return "o De Lá Pra Cá está no meio de um trabalho no Media Composer"
    if servico.receber.progresso().get("ativo"):
        return "o De Lá Pra Cá está no meio de um Importar"
    if conferencias().em_uso():
        return "há uma conferência em curso (ou que acabou de parar)"
    return ""


def _estado_do_cache(servico) -> dict:
    import cache

    return {**cache.estatisticas(), "antigo": cache.antigo(), "ocupado": _ocupado(servico)}


@rota("GET", "/cache")
def cache_estado(ctx):
    return 200, _estado_do_cache(ctx.servico)


@rota("POST", "/cache/configurar")
def cache_configurar(ctx):
    """`{dir: caminho | null, max_gb}`. Trocar o local NÃO move nada: o novo começa vazio (o
    antigo fica onde está, e o Limpar do painel só alcança o atual)."""
    import cache
    import configuracoes

    corpo = ctx.json()
    mudancas = {}
    if "dir" in corpo:
        bruto = corpo.get("dir")
        escolhida = configuracoes.pasta_aceitavel(bruto) if bruto else None
        if bruto and not escolhida:
            return 400, {"erro": "escolha uma pasta deste computador (caminho de rede não vale)"}
        if escolhida:
            try:
                Path(escolhida).mkdir(parents=True, exist_ok=True)
                teste = Path(escolhida) / f".dlpc-{threading.get_ident()}.tmp"
                teste.write_bytes(b"ok")
                teste.unlink()
            except OSError as e:
                return 409, {"erro": f"não consigo gravar nessa pasta ({e.strerror or e})"}
        mudancas["cache_dir"] = escolhida
    if "max_gb" in corpo:
        mudancas["cache_max_gb"] = corpo.get("max_gb")
    try:
        configuracoes.gravar(mudancas)
    except OSError as e:
        return 500, {"erro": f"não consegui guardar as configurações: {e.strerror or e}"}
    log.info("cache: configurado em %s (teto %s GB)", cache.raiz(), configuracoes.ler()["cache_max_gb"])
    return 200, _estado_do_cache(ctx.servico)


@rota("POST", "/cache/limpar")
def cache_limpar(ctx):
    import cache

    motivo = _ocupado(ctx.servico)
    if motivo:
        return 409, {"erro": f"agora não: {motivo}. Tente quando terminar."}
    return 200, {"liberado": cache.limpar(), **_estado_do_cache(ctx.servico)}


@rota("POST", "/cache/antigo")
def cache_antigo(ctx):
    """`{acao: "apagar" | "manter"}` — o cache das versões anteriores, na pasta de dados."""
    import cache
    import configuracoes

    acao = ctx.json().get("acao")
    if acao == "apagar":
        motivo = _ocupado(ctx.servico)
        if motivo:
            return 409, {"erro": f"agora não: {motivo}"}
        liberado = cache.apagar_antigo()
    elif acao == "manter":
        configuracoes.gravar({"cache_antigo_dispensado": True})
        liberado = None
    else:
        return 400, {"erro": "ação desconhecida"}
    return 200, {"liberado": liberado, **_estado_do_cache(ctx.servico)}


@rota("POST", "/pasta/abrir")
def pasta_abrir(ctx):
    """`{qual: "cache" | "logs"}` ou `{qual: "conferencia", id}`. Nunca um caminho."""
    import cache
    import plataforma
    from conferencia import conferencias

    corpo = ctx.json()
    qual = corpo.get("qual")
    try:
        if qual == "conferencia":
            pasta = Path(conferencias().pasta(str(corpo.get("id") or "")))
        else:
            pasta = cache.pasta_conhecida(str(qual or ""))
        plataforma.abrir_pasta(pasta)
    except (LookupError, ValueError) as e:
        return 409, {"erro": str(e)}
    except OSError as e:
        return 500, {"erro": f"não consegui abrir a pasta: {e.strerror or e}"}
    return 200, {"ok": True}


# ── versão nova (organograma aprovado pelo autor em 2026-10-05, `versao_nova.py`) ─────────────────────
# O link nunca vem do painel: o motor abre só a página de versão que ELE leu e conferiu.

@rota("GET", "/versao")
def versao_estado(ctx):
    import versao_nova

    return 200, versao_nova.estado()


@rota("POST", "/versao/conferir")
def versao_conferir(ctx):
    import versao_nova

    return 200, versao_nova.estado(forcar=True)


@rota("POST", "/versao/avisar")
def versao_avisar(ctx):
    """`{ligado: bool}` — a caixa "Avisar quando houver versão nova"."""
    import configuracoes
    import versao_nova

    ligado = ctx.json().get("ligado")
    if not isinstance(ligado, bool):
        return 400, {"erro": "ligado tem de ser verdadeiro ou falso"}
    try:
        configuracoes.gravar({"avisar_versao_nova": ligado})
    except OSError as e:
        return 500, {"erro": f"não consegui guardar as configurações: {e.strerror or e}"}
    return 200, versao_nova.estado()


@rota("POST", "/versao/baixar")
def versao_baixar(ctx):
    import plataforma
    import versao_nova

    e = versao_nova.estado()
    if e["estado"] != "nova" or not versao_nova.url_confiavel(e.get("url")):
        return 409, {"erro": "não há versão nova para baixar", **e}
    plataforma.abrir_url(e["url"])
    return 200, e


def _arquivo_livre(caminho: str) -> str:
    """Nunca sobrescreve: `NOME.drt` já existe → `NOME_2.drt`, `NOME_3.drt`…

    O nome final vai no resultado e o painel o mostra — o editor vê que numerou.
    """
    p = Path(caminho)
    n = 2
    while p.exists():
        p = p.with_name(f"{Path(caminho).stem}_{n}{p.suffix}")
        n += 1
    return str(p)


# ── fronteira de caminho ────────────────────────────────────────────────────
#
# Todo caminho que vem do painel passa por aqui. `media/safepath` existe porque o
# `pymediainfo` **busca URLs** (pula `os.path.exists` quando a string tem `://`, e a
# libmediainfo traz `Reader_libcurl` compilado) e porque o ffprobe lê um arquivo
# começado em `-` como opção.

def _pasta_valida(caminho: str) -> str:
    p = Path(caminho).expanduser()
    if not p.is_absolute():
        raise CaminhoInvalido(f"o caminho precisa ser absoluto: {caminho!r}")
    if "://" in caminho:
        raise CaminhoInvalido("URL não é pasta de mídia")
    p = p.resolve()
    if not p.is_dir():
        raise CaminhoInvalido(f"pasta não encontrada: {caminho!r}")
    return str(p)


def _arquivo_valido(caminho: str, extensao: str = "") -> str:
    p = Path(caminho).expanduser()
    if not p.is_absolute() or "://" in caminho:
        raise CaminhoInvalido(f"caminho de arquivo inválido: {caminho!r}")
    p = p.resolve()
    if not p.is_file():
        raise CaminhoInvalido(f"arquivo não encontrado: {caminho!r}")
    if extensao and p.suffix.lower() != extensao:
        raise CaminhoInvalido(f"esperava um {extensao}: {p.name!r}")
    return str(p)


def _nome_de_arquivo(nome: str) -> str:
    """Um nome de bin que o sistema de arquivos aceite, vindo de texto arbitrário."""
    # sem pontos nas pontas: ".." viraria a pasta ACIMA do projeto (revisão 2026-10-28)
    limpo = "".join(c for c in (nome or "") if c.isalnum() or c in " -_.").strip(" .")
    return (limpo or "RELINK")[:60]
