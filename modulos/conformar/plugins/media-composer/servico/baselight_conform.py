"""O De Lá Pra Cá com o Baselight (proposta do Ciclo Assist `docs/plano/2026-11-22-baselight-no-app.md`, etapa 2): o
MESMO Importar de sempre — o projeto do Premiere (com a análise proxy → original) ou o AAF/bin/Carta do MC (com o relink
dos originais por master) —, e no fim, em vez do DRT ou da cópia do Premiere, a entrega ao Baselight
(`motor/baselight/enviar.py`): o xmeml com o original decidido, o conform numa scene NOVA do job da produção, a conferência
de cada plano, a troca do que o Baselight casou por conta própria e os markers do que não se corrige.

O que não tem original decidido (ambíguo, sem original, mídia gerenciada do Avid, arquivo que não está aqui) vai OFFLINE
de propósito, com marker — o Baselight não pode casar sozinho (BL08: o caminho A errou calado de 1 a 5 planos).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("delapraca.baselight")


def _sondar(caminho: str) -> dict:
    from prproj.originais import sondar

    try:
        return sondar(caminho) or {}
    except OSError:
        return {}


def _inicio_na_timeline(seg: dict, leitura: dict) -> int:
    """O `<start>` que o `do_aaf.escrever` dá ao plano (o quadro da timeline em que ele começa)."""
    from baselight.entrega import _rate, _tc_quadros

    base, _ = _rate(float(leitura.get("timeline_fps") or 25.0))
    return _tc_quadros(seg["timeline_tc_in"], base, bool(leitura.get("timeline_drop_frame")))


def _pasta_offline() -> str:
    import cache

    return str(cache.sub(cache.RECEBIDOS) / "baselight-offline")


def _caminho_offline(seg: dict) -> str:
    """Um caminho que NÃO existe, para o plano sem arquivo entrar no xmeml (nenhum segmento se perde) e sair offline."""
    nome = os.path.basename((seg.get("media_ref") or {}).get("local_path") or "") or (seg.get("clip_name") or "plano")
    return os.path.join(_pasta_offline(), nome)


def _entregar(leitura_aaf: dict, achar, decisao: dict, sinais: dict, pastas: list[str], nome: str, andamento,
              notas: list[tuple[int, str]] | None = None) -> dict:
    """Comum aos dois caminhos: o xmeml da leitura → reescrito com as decisões → `enviar`."""
    import uuid

    import cache
    from baselight import do_aaf, enviar
    from baselight import entrega as E

    pasta = cache.sub(cache.RECEBIDOS)
    pasta.mkdir(parents=True, exist_ok=True)
    rid = uuid.uuid4().hex
    bruto, final = str(pasta / f"{rid}.baselight-montagem.xml"), str(pasta / f"{rid}.baselight.xml")
    andamento("montando", f"escrevendo a timeline para o Baselight (xmeml): {nome}")
    feito = do_aaf.escrever(leitura_aaf, bruto, _sondar, achar)
    reescrito = E.reescrever(bruto, final, decisao, _pasta_offline())
    # a velocidade e o Motion do Premiere (estudo PRODUCAO-C): o quadro exato no xmeml, as camadas depois do conform
    from baselight import efeitos as EF
    planos_ef = EF.planejar(leitura_aaf, decisao, achar)
    if planos_ef:
        EF.no_xmeml(final, planos_ef)
    from baselight import mascaras as MK
    plano_mk = MK.planejar(leitura_aaf, decisao, achar)
    tits = EF.titulos(leitura_aaf)
    trazer = None
    if tits and sinais.get("titulos"):             # a OPÇÃO: o texto narrativo/artístico na scene (autor, 2026-11-23)
        from baselight import titulos as TT
        vid = [(EF._tc_ini(s, leitura_aaf), int(s["duration_frames"])) for s in leitura_aaf["segments"]
               if EF._video(s) and not s.get("disabled") and achar(s)]
        trazer = TT.detalhar(tits, leitura_aaf)
        pretos = TT.pretos(trazer, lambda q: any(i <= q < i + d for i, d in vid))
    marcas_tit = (TT.marcas(trazer) if trazer else EF.marcas_dos_titulos(tits, float(leitura_aaf["timeline_fps"])))
    job = (sinais.get("job") or sinais.get("producao") or nome).strip()
    # o Stabilize do MC → o tracker nativo (laboratório de 2026-11-23); só os planos que o xmeml levou
    w, h = do_aaf.raster(bruto)
    estab = do_aaf.estabilizados(leitura_aaf, achar, w, h)
    r = enviar.enviar(final, job, sinais.get("scene") or nome, float(leitura_aaf["timeline_fps"]), pastas,
                      markers=sinais.get("markers", True) is not False,
                      andamento=lambda etapa, det: andamento("baselight", det),
                      atualizar=(sinais.get("atualizar") or None), notas=E.notas_dos_trechos(bruto, decisao) + list(notas or [])
                      + marcas_tit,
                      estabilizar_planos=estab, estabilizacao_fora=do_aaf.estabilizacao_fora(leitura_aaf),
                      efeitos_planos=planos_ef, mascaras_plano=plano_mk, pasta_trabalho=str(pasta),
                      titulos=trazer, pretos_dos_titulos=pretos if trazer else None)
    log.info("baselight %s → %s:%s — %s", nome, r["job"], r["scene"], r["contagem"])
    return {"baselight": r, "nome": nome, "clipes": feito["planos"], "titulos": len(tits),
            "offline": sum(1 for v in reescrito.values() if v == "offline"),
            "nos_originais": sum(1 for v in reescrito.values() if v not in ("offline", "sem decisão (mantido)")),
            "nao_traduzido": len([x for x in feito["nao_traduzido"] if x["plano"] not in {p["n"] for p in planos_ef} | EF.escondidos(leitura_aaf, achar)])
            + r["estabilizacao"]["nao_traduzidos"], "xmeml": final}


def do_prproj(analise: dict, sinais: dict, pastas: list[str], andamento) -> dict:
    """O projeto do Premiere: a análise já casou cada proxy com o original (`casamento`)."""
    from baselight import do_prproj as P
    from baselight import entrega as E
    from prproj.originais import recusado

    leitura = analise["leitura"]
    fps = float(leitura["fps"])
    decisao: dict[str, dict | None] = {}
    for p, c in analise["casamento"].items():
        o = c.get("original") if c.get("estado") in ("original", "proprio") else None
        if o and not recusado(o) and os.path.isfile(o):
            decisao[p] = E.descrever(o, _sondar(E.como_o_disco_lista(o)), fps_sequencia=fps, trecho=c.get("trecho"))
        else:
            decisao[p] = None

    def achar(seg: dict) -> str | None:
        p = (seg.get("media_ref") or {}).get("local_path") or ""
        if p in decisao:
            return p
        return None                       # sem mídia (título, camada de ajuste): fora do xmeml, como no MC

    return _entregar(P.como_aaf(leitura), achar, decisao, sinais, pastas, leitura["nome"], andamento)


def da_carta(resultado: dict, segs: list, casados: list, preferir: dict, sinais: dict, pastas: list[str], nome: str,
             andamento) -> dict:
    """AAF, bin ou Carta: `montar_midia` já casou cada segmento; só o que caiu num ORIGINAL decidido pelo relink
    (`preferir`, as decisões da revisão) vai online — o resto (o daily, a gerenciada do Avid) vai offline de propósito."""
    from baselight import entrega as E
    from media.matcher import _daily_do_segmento

    fps = float(resultado.get("timeline_fps") or 25.0)
    originais = {os.path.normcase(v) for v in (preferir or {}).values() if v}
    por_indice = {c["segment_index"]: c for c in casados}
    caminho_de: dict[int, str] = {}
    decisao: dict[str, dict | None] = {}
    notas: list[tuple[int, str]] = []
    for i, s in enumerate(segs):
        if s.get("is_audio") or s.get("is_gap") or s.get("is_transition") or s.get("referencia"):
            continue
        c = por_indice.get(i) or {}
        m = c.get("matched_path") if not (c.get("offline") or c.get("rejected")) else None
        # ⭐ o `<file>` de partida é o DAILY (o que a montagem viu: taxa, duração e raster do offline), como no BL08; a
        # decisão troca para o original. Partir do original (uma sequência DPX não tem duração legível) fez o P10 entrar
        # como imagem parada.
        daily = _daily_do_segmento(s) or m or _caminho_offline(s)
        if m and os.path.normcase(m) in originais and os.path.isfile(m):
            caminho_de[id(s)] = daily
            if decisao.get(daily) is None:
                decisao[daily] = E.descrever(m, _sondar(E.como_o_disco_lista(m)), fps_sequencia=fps)
            if s.get("trecho") and not s.get("is_audio"):
                # o ponto já veio deslocado do `montar_midia` (`avb_bin.segmentos._deslocar_trecho`); aqui, só o marker
                notas.append((_inicio_na_timeline(s, resultado), s["trecho"]["motivo"]))
        else:
            caminho_de[id(s)] = daily
            decisao.setdefault(daily, None)
    leitura = {**resultado, "composition_name": nome,
               "segments": [s for s in segs if not s.get("referencia")]}
    return _entregar(leitura, lambda s: caminho_de.get(id(s)), decisao, sinais, pastas, nome, andamento, notas)
