"""Premiere → Avid pelo .prproj (organograma aprovado pelo autor em 2026-10-25,
https://claude.ai/artifact/CzvNCD3DH88HHXh5aa8SYj).

O Media Composer está aberto desde o início e só RECEBE um .prproj — o Premiere nem precisa existir na máquina; não há
troca de NLE no meio. A entrega é a mesma do relink (`relink_avb.aplicar`), organizada numa pasta do projeto:

    <nome>/
      <nome>_MIDIAS.avb   os masters: vídeo linkado pelo MC (um por assinatura) e irmãos injetados, áudio injetado,
                          e o que não foi achado como master OFFLINE (à vista: é o que o editor procura ou ignora)
      <nome>_SEQ.avb      a sequência traduzida e, OCULTOS, os masters que ela usa (sem eles a timeline sai offline —
                          banco, `protocolos/avb/escrita.md`)

A ordem (motor: `avb_export/do_prproj.py`): os masters ANTES da sequência — a posição de cada plano do .prproj está nos
quadros do arquivo, e só o master linkado tem a taxa de verdade.
"""

from __future__ import annotations

import logging
import os
import random
import tempfile
import time
from pathlib import Path

from avid.acoes import Acoes
from relink import Progresso

log = logging.getLogger("delapraca.prproj_avid")


def id_da_chave(chave: str) -> str:
    """Um MobID sintético (32 hex) por chave de master do plano — o relink indexa os masters por MobID
    (`aaf.masters.chave_mob`), e a chave é um caminho."""
    import hashlib

    return hashlib.sha1(str(chave).encode("utf-8")).hexdigest()[:32]


def masters_do_prproj(analise: dict) -> tuple[list, dict]:
    """O plano do .prproj como `aaf.masters.Master` — o LEITOR da rota `prproj` do relink, como `masters_da_carta`:
    um por arquivo da sequência. O achado pela análise entra com `caminho_conhecido` (o degrau "caminho" do matcher);
    o não achado é procurado pelo NOME nas pastas indicadas, como qualquer master. Devolve `(masters, {mob_id: chave})`
    — a chave volta no aplicar (`montar(decididos=…)`)."""
    from collections import Counter

    from aaf.masters import Master
    from avb_export import do_prproj

    plano = do_prproj.planejar(analise)
    usos: Counter = Counter()
    audio: dict[str, bool] = {}
    uso: dict[str, int] = {}
    origem: dict[str, str] = {}
    for s in plano["segmentos"]:
        k = s.get("mob_id")
        if not k or s.get("is_gap") or s.get("is_transition") or s.get("is_effect"):
            continue
        usos[k] += 1
        audio[k] = audio.get(k, True) and bool(s.get("is_audio"))
        uso[k] = max(uso.get(k, 0), int(s.get("source_start_frames") or 0) + int(s.get("duration_frames") or 0))
        origem.setdefault(k, (s.get("media_ref") or {}).get("local_path") or "")
    masters, ids = [], {}
    for k in usos:
        mid = id_da_chave(k)
        achado = not str(k).startswith(do_prproj.OFFLINE)
        arq = k if achado else str(k)[len(do_prproj.OFFLINE):]
        m = Master(nome=Path(arq.replace("\\", "/")).stem, mob_id=mid, mob_id_urn=mid, e_audio=audio[k],
                   segmentos=usos[k], uso_frames=uso[k], usa_imagem=not audio[k])
        m.origem = origem[k][:1024]
        if achado:
            m.caminho_conhecido = k
        masters.append(m)
        ids[mid] = k
    return masters, ids


def _marcar(mc, seq: str, marcas: list[dict]) -> int:
    """Os marcadores amarelos na sequência entregue; devolve quantos entraram. Polimento: o que falha se registra e a
    entrega segue (memória `o-trabalho-caro-nao-pode-morrer-no-acessorio`)."""
    from sessao_export import mob_id_da_api

    n = 0
    for m in marcas:
        try:
            mc.marcar(mob_id_da_api(seq), m["quadro"], m["nota"], "Yellow", m["trilha"])
            n += 1
        except Exception as e:  # noqa: BLE001
            log.warning("o marcador em %s (V%s) não entrou: %s", m["quadro"], m["trilha"], e)
            break
    return n


def montar(mc, analise: dict, pasta_projeto: str, pasta_trabalho: str, nome_bin: str, nome_seq: str,
           progresso: Progresso | None = None, decididos: dict | None = None, ids: dict | None = None,
           reescalar: dict | None = None) -> dict:
    """A análise do .prproj (`tools.prproj_para_drt.analisar`) → as duas bins no projeto aberto, a `_SEQ` aberta e a
    timeline no Record. Devolve o resumo.

    `decididos` (`{mob_id: arquivo}` do relink, `Trabalho.decididos()`) + `ids` (`{mob_id: chave}`,
    `masters_do_prproj`): a lista de mídias manda — o arquivo escolhido vira o master; o master que não está nos
    decididos (ignorado, não achado) entra OFFLINE no lugar. Sem eles, vale a análise como está.

    `reescalar` (`{caminho do projeto: fator}`, o que o editor aceitou na oferta da escala de outra mídia): como no
    Resolve — a escala × fator, e todo suspeito com um marcador amarelo (`do_prproj.ajustar_escalas`)."""
    from avb.mobid import MobID
    from avb_bin import audio as avb_audio
    from avb_bin import percurso as avb_percurso
    from avb_bin import visibilidade as avb_vis
    from avb_export import do_prproj, media_bin
    from avb_export.merge import materialize, serialize
    from avb_export.reader import topen
    from relink_avb import (_alcancaveis, _record_pela_api, esperar_bin_estabilizar, juntar_na_midias,
                            trazer_video)

    p = progresso or Progresso()
    acoes = Acoes(mc)
    plano = do_prproj.planejar(analise)
    if ids is not None:
        do_prproj.redirecionar(plano, {ids[mid]: (decididos or {}).get(mid) for mid in ids})
    marcas = do_prproj.ajustar_escalas(plano, analise, reescalar)
    marcas += do_prproj.marcas_de_duvida(plano, analise)
    fps = plano["fps"]
    pedidos = {"video": len(plano["video"]), "audio": len(plano["audio"]), "ausentes": len(plano["ausentes"]),
               # o mesmo arquivo como imagem e som é UM master (a lista de mídias conta assim)
               "arquivos": len(set(plano["video"]) | set(plano["audio"]) | set(plano["ausentes"]))}
    if not (plano["video"] or plano["audio"] or plano["ausentes"]):
        raise ValueError("a sequência não tem plano com mídia — nada a montar")

    raiz = Path(pasta_projeto)
    projeto = Path((mc.projeto() or {}).get("path") or raiz)
    pasta = raiz / nome_bin
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        sub = os.path.relpath(pasta, projeto)
    except ValueError:
        sub = nome_bin
    sub = "" if sub in (".", "") else sub.replace("\\", "/")
    nome_midias, nome_seq_bin = f"{nome_bin}_MIDIAS", f"{nome_bin}_SEQ"
    midias, seq = pasta / f"{nome_midias}.avb", pasta / f"{nome_seq_bin}.avb"

    # ── 1) a _MIDIAS, criada PELO MC (ele precisa conhecê-la para o LinkFile), e o VÍDEO nela ──────────────────
    p("preparando a bin", 0, 1, nome_midias)
    acoes.criar_bin(nome_midias, sub)
    destino = f"{sub}/{midias.name}" if sub else midias.name    # ⛔ relativo ao projeto (relink_avb.aplicar)
    v = trazer_video(mc, acoes, {a: a for a in plano["video"]}, destino, midias, projeto, (str(midias),),
                     pasta_trabalho, nome_bin, fps, p)
    falhas = list(v["falhas"])

    # ── 2) o ÁUDIO injetado (o LinkFile do BWF abre o modal "Audio Start-Time Options") ─────────────────────────
    bin_audio = Path(pasta_trabalho) / f"{nome_bin} (audio).avb"
    r_audio = {"clipes": 0, "mapa": {}, "pulados": [], "sem_template": [], "esticados": [], "curtos_demais": []}
    if plano["audio"]:
        r_audio = avb_audio.autorar_masters(sorted(plano["audio"]), str(bin_audio), fps=fps, minimos=plano["audio"],
                                            progresso=lambda feito, tot, n: p("preparando o áudio", feito, tot, n))
        for nome, erro in r_audio["pulados"]:
            falhas.append({"arquivo": nome, "erro": erro})

    # ── 3) o que não virou master fica OFFLINE no lugar (nunca vazio) ─────────────────────────────────────────
    mapa = {**v["mapa"], **{a: m for a, m in r_audio["mapa"].items() if m}}
    sem = [a for a in list(plano["video"]) + list(plano["audio"]) if a not in mapa]
    do_prproj.sem_master(plano, sem)
    specs, _handle = do_prproj.specs_offline(plano)
    om = media_bin.build_offline_masters(specs, tempfile.mkdtemp(prefix="offline_", dir=pasta_trabalho), fps=fps) \
        if specs else {}

    # ── 4) a _MIDIAS completa (a do MC + o injetado + o offline) ──────────────────────────────────────────────
    p("montando as bins", 0, 1, nome_bin)
    uid_midias, uid_seq = random.getrandbits(63), random.getrandbits(63)
    midias_novo = midias.with_name(midias.name + ".novo")
    with topen(str(midias)) as fm:
        juntar_na_midias(fm, str(bin_audio) if r_audio["clipes"] else None, v["r_video"], v["reaproveitar"],
                         uid_midias, nome_midias)
        tem = {str(m.mob_id) for m in fm.content.mobs}
        for cbin, _nome, _hex in om.values():
            with topen(cbin) as fo:
                for m in fo.content.mobs:
                    if str(m.mob_id) not in tem:
                        fm.content.add_mob(materialize(fm, serialize(m)))
                        tem.add(str(m.mob_id))
        from relink_avb import _bin_ref

        for m in fm.content.mastermobs():
            if m.attributes is not None:
                m.attributes["_ORG_BIN"] = _bin_ref(fm, uid_midias, nome_midias)
        por_texto = {str(m.mob_id): m for m in fm.content.mobs}
        mob_hex = {}
        for chave, novo in mapa.items():
            m = por_texto.get(str(novo))
            if m is not None:
                mob_hex[chave] = m.mob_id.bytes_le.hex()
        online = {str(por_texto[str(n)].mob_id) for n in mapa.values() if str(n) in por_texto}
        # a _MIDIAS mostra os masters (o offline é o que o editor procura)
        for it in fm.content.property_data.get("items") or []:
            it.property_data["user_placed"] = avb_percurso.e_master(getattr(it, "mob", None))
        fm.content.uid = uid_midias
        fm.write(str(midias_novo))
    os.replace(midias_novo, midias)
    offline_hex = {k: h for k, (_c, _n, h) in om.items() if h}

    # ── 5) a sequência, sobre a _MIDIAS; a _SEQ fica só com ela e o que ela usa (oculto) ───────────────────────
    p("traduzindo a sequência", 0, 1, nome_seq)
    bruta = Path(pasta_trabalho) / f"{nome_seq_bin} (bruta).avb"
    r_seq = do_prproj.montar_sequencia(plano, str(midias), str(bruta), nome_seq, mob_hex, offline_hex)
    if r_seq.get("leaks_filled"):   # B009: o plano sem master vira vazio — o painel avisa; o log guarda
        log.warning("%d plano(s) sem master na bin viraram vazio na timeline", r_seq["leaks_filled"])
    seq_novo = seq.with_name(seq.name + ".novo")
    with topen(str(bruta)) as f:
        alvo = next(m for m in f.content.mobs if m.property_data.get("mob_type_id") == 1 and m.name == nome_seq)
        manter = _alcancaveis(f, alvo)
        itens = f.content.property_data.get("items") or []
        f.content.property_data["items"] = [it for it in itens
                                             if str(getattr(getattr(it, "mob", None), "mob_id", "")) in manter]
        if getattr(f.content, "_mob_dict", None):
            f.content._mob_dict = {k: x for k, x in f.content._mob_dict.items() if str(k) in manter}
        alvo.mob_id = MobID.new()
        seq_entregue = str(alvo.mob_id)
        try:
            r_vis = avb_vis.ajustar(f, alvo, online)
            avb_vis.garantir_monitor(f, alvo)
            for it in f.content.property_data.get("items") or []:     # na _SEQ, master online nenhum à vista
                if avb_percurso.e_master(getattr(it, "mob", None)) and str(it.mob.mob_id) in online:
                    it.property_data["user_placed"] = False
        except Exception as e:  # noqa: BLE001 — polimento nunca custa a entrega
            log.warning("não consegui ajustar a visibilidade (%s)", e, exc_info=True)
            r_vis = {"visiveis": 0, "ocultos": 0, "erro": str(e)}
        f.content.uid = uid_seq
        f.write(str(seq_novo))
    os.replace(seq_novo, seq)
    esperar_bin_estabilizar(seq, quietos=2, limite_s=10)

    # ── 6) entregar: a _SEQ aberta, a timeline no Record ───────────────────────────────────────────────────────
    p("abrindo no Media Composer", 0, 1, nome_seq_bin)
    aberta = no_record = no_source = False
    try:
        mc.abrir_bin(str(seq))
        aberta = True
    except Exception as e:  # noqa: BLE001
        log.warning("a bin foi gravada mas não abriu sozinha (%s): %s", e, seq)
    if aberta:
        try:
            from sessao_export import mob_id_da_api

            time.sleep(3)
            monitor = "Record" if _record_pela_api(mc) else "Source"
            mc.carregar_no_monitor([mob_id_da_api(seq_entregue)], monitor)
            no_record, no_source = monitor == "Record", monitor == "Source"
        except Exception as e:  # noqa: BLE001
            log.warning("a timeline entregue não foi para o Record (%s)", e)
    marcados = _marcar(mc, seq_entregue, marcas) if aberta else 0

    resultado = {
        "bin": nome_seq_bin, "bin_midias": nome_midias, "pasta": nome_bin, "avb": str(seq),
        "aberta_no_mc": aberta, "no_record": no_record, "no_source": no_source,
        "pedidos": pedidos,
        # os números que o cartão do relink já mostra
        "masters_pedidos": pedidos["arquivos"],
        "masters_online": len(mapa),
        # os planos da timeline que apontam para um master online (o "N clipes na timeline" do cartão)
        "segmentos_cobertos": sum(1 for x in plano["segmentos"] if x.get("mob_id") in mob_hex
                                  and not (x.get("is_gap") or x.get("is_transition") or x.get("is_effect"))),
        "video_pelo_link": len(v["linkado"]), "video_injetado": len(v["r_video"]["mapa"]),
        "video_reaproveitado": len(v["reaproveitar"]), "audio_autorado": r_audio["clipes"],
        "audio_sem_template": r_audio["sem_template"], "offline": len(om), "offline_planos": sorted(specs),
        "falhas": falhas, "clipes_visiveis": r_vis["visiveis"], "clipes_ocultos": r_vis["ocultos"],
        "sequencia": {k: r_seq.get(k) for k in ("name", "length", "tracks", "leaks_filled")},
        # B009: o que o Premiere tinha e o .avb não leva (o resumo da análise fala do Resolve)
        "efeitos_fora": do_prproj.efeitos_fora_do_avid(plano),
        # B109: escala digitada para outra mídia / proporção de outro arquivo — a tela pede para conferir
        "de_outra_midia": do_prproj.de_outra_midia(plano, analise),
        "reescalados": sum(1 for m in marcas if "ajustada" in m["nota"]), "marcadores": marcados,
    }
    if resultado["efeitos_fora"]:
        log.warning("efeitos do Premiere que não foram para o Avid: %s", resultado["efeitos_fora"])
    p("pronto", 1, 1, "")
    log.info("prproj → Avid montado: %s", resultado)
    return resultado
