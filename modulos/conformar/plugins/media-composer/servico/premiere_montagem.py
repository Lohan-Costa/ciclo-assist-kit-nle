"""O plano de MONTAGEM no Premiere (organograma do modo Premiere, aprovado pelo autor em 2026-10-19: decisão A).

Os mesmos segmentos e o mesmo casamento que viram o DRT do Resolve (`sessao_receber._montar`) viram aqui uma lista de
planos que a ponte executa em ExtendScript (`ui/premiere_host.jsx` › `dlpcMontar`): a mídia importada numa bin
`De Lá Pra Cá › Mídia › <nome>`, a sequência nova e cada plano no tempo e na trilha certos. Começa pelos CORTES de vídeo
e áudio; o que ainda não traduz (velocidade, transição, título, efeito, mídia que não está aqui) vai como marcador no
lugar — nenhum plano some calado (memória "nenhum segmento se perde").

Os tempos vão em TICKS exatos (254.016.000.000 por segundo): no 23.2 o in/out em SEGUNDOS arredonda e o plano sai com
um quadro a mais ou a menos (banco, premiere-cep/api-extendscript.md, laboratório B14/B16).

A entrada no arquivo é a do escritor do DRT (`drp/writer._make_timeline_clip`): `source_start_frames` (na taxa NATIVA
do clipe) + a correção de offset do casamento.
"""
from __future__ import annotations

import os
from fractions import Fraction

TICKS_POR_SEGUNDO = 254016000000


def _taxa(fps: float) -> Fraction:
    """23.976 → 24000/1001 (a taxa NTSC exata); o resto, como vem."""
    for n in (24, 30, 48, 60, 120):
        if abs(fps - n * 1000 / 1001) < 0.002:
            return Fraction(n * 1000, 1001)
    return Fraction(fps).limit_denominator(1001)


def ticks_por_quadro(fps: float) -> int:
    return round(Fraction(TICKS_POR_SEGUNDO) / _taxa(fps))


def _quadros(tc: str, nominal: int) -> int:
    h, m, s, f = (int(x) for x in str(tc).replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * nominal + f


def plano(segs: list[dict], casados: list[dict], fps: float, nome: str, inicio: int | None = None,
          metas: dict | None = None) -> dict:
    """`segs`/`casados` do `montar_midia` → `{nome, fps, tpf, inicio, midias, offline, planos, marcas, conta}`.

    `planos`: `{m: índice em midias | o: índice em offline, v: vídeo?, t: trilha, rec: quadro na timeline, dur: quadros,
    src: ticks no arquivo, ref: é a referência}`. `marcas`: `{q: quadro, nome, nota}`.
    ⭐ `metas` (o 3º retorno do `montar_midia`: `{rótulo: {nb, fps, fps_tc, tc, audio_canais, reel}}`): o plano sem
    mídia nesta máquina entra como MÍDIA OFFLINE no lugar (`offline`: os itens que `prproj.offline` escreve; autor,
    2026-11-25, "nada some da timeline"). Sem os dados do Avid ele segue como marcador."""
    nominal = round(fps)
    tpf = ticks_por_quadro(fps)
    por_seg = {c.get("segment_index"): c for c in casados if isinstance(c, dict)}
    midias: list[str] = []
    indice: dict[str, int] = {}
    offline: list[dict] = []
    indice_off: dict[str, int] = {}
    planos: list[dict] = []
    marcas: list[dict] = []
    conta = {"video": 0, "audio": 0, "offline": 0, "offline_no_lugar": 0, "velocidade": 0, "transicoes": 0, "transicoes_audio": 0,
             "titulos": 0, "audio_juntado": 0, "desligados": 0, "audio_desligado": 0}
    vistos_audio: dict = {}
    for i, s in enumerate(segs):
        if s.get("is_gap"):
            continue
        # B015/B108: o VÍDEO desligado no Avid (Mute Clips) não existe na imagem — não entra (entrava LIGADO, um vídeo
        # calado no Avid por cima da imagem). Como o DRT faz; contado, sem marcador. O SOM desligado entra como CLIPE
        # DESLIGADO, como no Resolve (Flags=2): o editor o religa se quiser (decisão do autor, 2026-10-29).
        desligado = bool(s.get("disabled")) and not s.get("is_transition")
        if desligado and not s.get("is_audio"):
            conta["desligados"] += 1
            continue
        rec = _quadros(s.get("timeline_tc_in") or "00:00:00:00", nominal)
        dur = int(s.get("duration_frames") or 0)
        if s.get("is_transition"):
            # a de áudio (crossfade) vira corte seco no lugar certo: o plano seguinte entra por cima do rabo do anterior
            # (medido no PRODUCAO-A, 2026-10-19). Contada, sem marcador: são centenas num filme.
            if s.get("is_audio"):
                conta["transicoes_audio"] += 1
            else:
                conta["transicoes"] += 1
                marcas.append({"q": rec, "nome": "Transição", "nota": f"{s.get('clip_name') or 'transição'} · "
                               f"{dur} quadros · V{s.get('track')} — refazer"})
            continue
        if dur <= 0:
            continue
        c = por_seg.get(i)
        arquivo = (c or {}).get("matched_path")
        if s.get("is_effect") or not c:
            if not s.get("is_audio") and s.get("is_effect"):
                conta["titulos"] += 1
                marcas.append({"q": rec, "nome": "Título / gerador",
                               "nota": f"{s.get('clip_name') or ''} · V{s.get('track')} — refazer"})
            continue
        sem_midia = c.get("offline") or c.get("rejected") or not arquivo or not os.path.isfile(arquivo)
        meta = (metas or {}).get(arquivo) if sem_midia and c.get("offline") and not c.get("rejected") else None
        if meta and int(meta.get("nb") or 0) > 0:
            conta["offline_no_lugar"] += 1
            sem_midia = False                      # entra como plano, de um item OFFLINE (o rótulo do Avid)
        if sem_midia:
            conta["offline"] += 1
            marcas.append({"q": rec, "nome": "OFFLINE",
                           "nota": f"{s.get('clip_name') or os.path.basename(arquivo or '')} · "
                                   f"{'A' if s.get('is_audio') else 'V'}{s.get('track')} — a mídia não está nesta máquina"})
            continue
        fonte = float(s.get("source_fps") or fps)
        src_q = int(s.get("source_start_frames") or 0) + int(c.get("source_offset_correction") or 0)
        src = round(src_q * Fraction(TICKS_POR_SEGUNDO) / _taxa(fonte))
        vel = float(s.get("relative_speed") or s.get("speed_ratio") or 1.0)
        if s.get("motion_effect_type") or abs(float(s.get("relative_speed") or 1.0) - 1) > 1e-3:
            conta["velocidade"] += 1
            marcas.append({"q": rec, "nome": "Velocidade",
                           "nota": f"{s.get('clip_name') or ''} · entrou a 100 % (no Avid {vel * 100:.0f} %) — refazer"})
        video = not s.get("is_audio")
        if meta:
            if arquivo not in indice_off:
                indice_off[arquivo] = len(offline)
                offline.append(_item_offline(arquivo, meta))
            k = indice_off[arquivo]
            offline[k]["video"] = offline[k]["video"] or video
            m = ("o", k)
        else:
            if arquivo not in indice:
                indice[arquivo] = len(midias)
                midias.append(arquivo)
            m = indice[arquivo]
        if not video:
            # dois mono do MESMO arquivo no mesmo trecho (A1/A2 do Avid): o Premiere põe o arquivo com os canais dele numa
            # trilha só — um plano, não dois (o som não dobra)
            # — e o juntado fica LIGADO se um dos dois estava ligado (desligar o par calaria o canal que toca)
            chave = (m, rec, dur, src)
            if chave in vistos_audio:
                conta["audio_juntado"] += 1
                par = vistos_audio[chave]
                # ⭐ o canal juntado vai junto: num item de VÁRIOS canais mono (o polifônico de 3+ canais) a ponte põe
                #   cada canal na SUA trilha; no mono/estéreo, o item inteiro numa trilha só, como antes
                par.setdefault("juntos", []).append({"t": int(s.get("track") or 1), "c": _canal(s)})
                if par.get("desligado") and not desligado:
                    del par["desligado"]
                    conta["audio_desligado"] -= 1
                continue
        planos.append({**({"o": m[1]} if isinstance(m, tuple) else {"m": m}), "v": video, "t": int(s.get("track") or 1), "rec": rec, "dur": dur, "src": src,
                       "ref": bool(s.get("referencia")), **({} if video else {"c": _canal(s)}),
                       **({"desligado": True} if desligado else {})})
        if not video:
            vistos_audio[(m, rec, dur, src)] = planos[-1]
        conta["video" if video else "audio"] += 1
        conta["audio_desligado"] += desligado
    # a trilha N da origem continua N — a vazia entra vazia (banco, B051: antes elas eram renumeradas de 1 a n, e a A3
    # de um corte com a A2 vazia descia para A2). Só a referência, que mora em 1000+ no DRT, vem logo abaixo das outras.
    # ⛔ A REFERÊNCIA é pela MARCA (`ref`), não pelo número: a leitura da BIN do Avid numera o som 1000 + trilha (A1 = 1000,
    #   a convenção do DRT) — "≥ 1000 = referência" tratava TODO o som de uma bin como referência, renumerado em sequência,
    #   e a trilha vazia do Avid sumia (medido 2026-11-25, a ida e volta da B03). O som 1000+ volta a ser A1, A2…
    def _a(t: int) -> int:
        return t - 999 if t >= 1000 else t

    for x in planos:
        if not x["v"] and not x["ref"]:
            x["t"] = _a(x["t"])
            for j in x.get("juntos", []):
                j["t"] = _a(j["t"])
    normais = sorted({x["t"] for x in planos if not x["v"] and not x["ref"]} |
                     {j["t"] for x in planos if not x["ref"] for j in x.get("juntos", [])})
    refs = sorted({x["t"] for x in planos if not x["v"] and x["ref"]})
    ordem_ref = {t: (max(normais) if normais else 0) + k + 1 for k, t in enumerate(refs)}
    for x in planos:
        if not x["v"] and x["ref"]:
            x["t"] = ordem_ref[x["t"]]
    # o TC de início da ORIGEM (quadros na base nominal); sem ele, 01:00:00:00. Antes era sempre 01:00:00:00, e a
    # sequência que começa em 00:59:50:00 ou 10:00:00:00 no Avid ganhava outro TC no Premiere (banco, B062)
    return {"nome": nome, "fps": fps, "nominal": nominal, "tpf": tpf,
            "inicio": int(inicio) if inicio is not None and int(inicio) >= 0 else 3600 * nominal,
            "midias": midias, "offline": offline, "planos": planos, "marcas": marcas, "conta": conta}


def _canal(s: dict) -> int:
    """O canal do ARQUIVO que o clipe de som lê (1…N): o `canal_arquivo` do Avid (o `.mxf` gerenciado de um canal = 1)."""
    return int(s.get("canal_arquivo") or s.get("source_slot_id") or 1)


def _item_offline(arquivo: str, meta: dict) -> dict:
    """O item offline de um rótulo (`segmentos.referencia_offline`), nos termos de `prproj.offline.item`. `inicio_ticks`
    é o TC na taxa do TC (`fps_tc`, a do projeto num master só de som) — como o diálogo do Premiere grava (04:53:47:11 a
    23,976 = 423059 × 10594584000). O trecho que o plano usa conta do INÍCIO DO ARQUIVO, não do TC (medido: o mesmo
    plano declarado com TC 0 e religado ao arquivo de TC 04:53:47:11 manteve a mesma entrada)."""
    fps = float(meta.get("fps") or 0) or 24000 / 1001
    fps_tc = float(meta.get("fps_tc") or 0) or fps
    inicio = _quadros(meta["tc"], round(fps_tc)) * ticks_por_quadro(fps_tc) if meta.get("tc") else 0
    # os canais do MASTER do Avid (= os do arquivo que ele importou): 1 mono, 2 estéreo, 3+ N mono. ⛔ Antes, 3+ ia
    # ESTÉREO — e o offline estéreo religado a um arquivo de mais canais deixa o canal 2 mudo (medido no 26.0.2, a
    # matriz da B03 — `spikes/offline_premiere_matriz.py`)
    canais = max(1, int(meta.get("audio_canais") or 2))
    return {"nome": os.path.basename(arquivo), "fita": str(meta.get("reel") or ""), "inicio_ticks": inicio,
            "dur_ticks": int(meta["nb"]) * ticks_por_quadro(fps), "fps_video": fps, "canais": canais,
            "video": False}


def escrever_offline(itens: list[dict], pasta) -> str:
    """O `.prproj` AUXILIAR com os itens offline (`prproj.offline`, sobre o projeto vazio que o Premiere 26.0.2 gravou),
    em `pasta/<uuid>.prproj` — a ponte o importa na bin da montagem. ⚠️ Premiere mais antigo que o molde não o importa:
    a ponte devolve esses planos ao marcador (nada some calado). Devolve o caminho, ou "" se não deu para escrever."""
    import uuid
    from pathlib import Path

    from prproj import offline as off

    molde = Path(off.__file__).resolve().parent / "moldes" / "vazio 26.0.2.prproj"
    destino = Path(pasta) / f"{uuid.uuid4()}.prproj"
    try:
        off.projeto_com_offline(str(molde), str(destino),
                                [{k: v for k, v in x.items() if k != "video"} |
                                 ({"video": {"largura": 1920, "altura": 1080}} if x.get("video") else {})
                                 for x in itens])
    except (OSError, ValueError):
        return ""
    return str(destino)
