"""INSERT PARA COR / VFX: quais segmentos o editor escolheu, e a timeline só com eles.

Dois lados do mesmo contrato (a `selecao` da Carta Aberta, `docs/carta-aberta.md`):

- `selecao_da_copia(copia, sequencia)` — no Avid: a coleta grava a cópia do editor numa bin e a
  lê (`avb_bin.segmentos.ler_timeline`); aqui cada pedaço dela é CASADO com o segmento da
  sequência de onde veio. ⭐ A cópia só diz QUAIS segmentos; o que eles SÃO (nome, efeitos,
  velocidade) vem da sequência — a cópia passa por subclipes que o `CreateSubClip` cria
  (`04-04-05.sub.01`), e nada disso pode chegar à Carta (banco,
  `plugins/avid-panel-sdk/copia-da-timeline.md`).
- `filtrar_insert(resultado, selecao)` — em quem recebe: a timeline inteira com o que NÃO foi
  escolhido virando vazio. Mesmo TC de início, mesmas trilhas, cada clipe no seu lugar.

Regras (decididas com o autor em 2026-09-24):

1. Clipe não escolhido → vazio. As posições dos outros não mudam (o writer do DRT posiciona
   cada clipe pelo próprio TC).
2. Transição → só fica se os DOIS lados foram escolhidos inteiros. Senão sai, e o clipe
   escolhido é APARADO no ponto de corte: sem isso o writer faria um fade e mostraria os
   frames que o dissolve escondia.
3. Seleção parcial (IN/OUT no meio de um clipe) → o clipe é aparado ao trecho.
4. ⚠️ Clipe com efeito de velocidade NÃO é aparado — o mapa timeline→fonte não é linear e um
   corte aqui erraria o frame em silêncio. Vai inteiro, com aviso.
"""

from __future__ import annotations

import copy

from aaf.parser import frames_to_tc


def _tc(tc: str | None, fps: float) -> int:
    h, m, s, f = (int(x) for x in (tc or "00:00:00:00").replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * round(fps) + f


def _e_clipe(s: dict) -> bool:
    return bool(s.get("mob_id")) and not s.get("is_gap") and not s.get("is_transition")


def _trilha(track: int) -> str:
    return f"V{track}" if track < 1000 else f"A{track - 999}"


def chave(item: dict) -> tuple:
    """A identidade de um item da lista: trilha, início na timeline e master."""
    return (int(item["track"]), item["timeline_tc_in"], item["mob_id"])


# ── 1. a cópia do editor → itens da seleção ─────────────────────────────────────────────


def selecao_da_copia(copia: dict, sequencia: dict) -> tuple[list[dict], list[str]]:
    """Casa cada pedaço da cópia com o segmento da sequência. Devolve `(itens, avisos)`.

    `copia` e `sequencia` são leituras (`ler_timeline`). A posição de um pedaço da cópia na
    sequência é `início da cópia − início da sequência + deslocamento dele na cópia` — a cópia
    começa no TC da timeline onde a seleção começa (medido, banco `copia-da-timeline.md`).

    Um pedaço que não casa com nada (outra sequência, timeline editada depois da cópia) vira
    aviso, nunca item.
    """
    fps = float(sequencia.get("timeline_fps") or 0) or 25.0
    fps_copia = float(copia.get("timeline_fps") or 0) or fps
    if abs(fps_copia - fps) > 0.001:
        return [], [f"a cópia é de outra taxa ({fps_copia:g} × {fps:g}) — não é desta sequência"]
    deslocamento = int(copia.get("timeline_start_frames") or 0) - \
        int(sequencia.get("timeline_start_frames") or 0)

    por_trilha: dict[int, list[dict]] = {}
    for s in sequencia.get("segments") or []:
        if _e_clipe(s):
            por_trilha.setdefault(int(s["track"]), []).append(s)

    itens: list[dict] = []
    avisos: list[str] = []
    vistos: set[tuple] = set()
    for p in copia.get("segments") or []:
        if not _e_clipe(p):
            continue
        track = int(p["track"])
        ini = deslocamento + _tc(p["timeline_tc_in"], fps)
        fim = deslocamento + _tc(p["timeline_tc_out"], fps)
        alvo = None
        for s in por_trilha.get(track, []):
            s_ini, s_fim = _tc(s["timeline_tc_in"], fps), _tc(s["timeline_tc_out"], fps)
            if s.get("mob_id") != p.get("mob_id") or not (s_ini <= ini and fim <= s_fim):
                continue
            # O ponto na fonte tem de bater: o mesmo master pode aparecer duas vezes na mesma
            # trilha (outro trecho do take). Com velocidade o mapa não é linear — aí só a
            # posição decide.
            if not s.get("has_motion_effect"):
                esperado = int(s.get("source_start_frames") or 0) + (ini - s_ini)
                if int(p.get("source_start_frames") or 0) != esperado:
                    continue
            alvo = (s, s_ini, s_fim)
            break
        if alvo is None:
            avisos.append(f"{_trilha(track)} {frames_to_tc(ini, fps)}: "
                          f"“{p.get('clip_name') or '?'}” não está nesta sequência")
            continue
        s, s_ini, s_fim = alvo
        item = {"track": track,
                "timeline_tc_in": frames_to_tc(ini, fps),
                "timeline_tc_out": frames_to_tc(fim, fps),
                "mob_id": s["mob_id"],
                "clip_name": s.get("clip_name") or "",
                "inteiro": ini == s_ini and fim == s_fim}
        if chave(item) not in vistos:
            vistos.add(chave(item))
            itens.append(item)
    itens.sort(key=lambda i: (i["track"], _tc(i["timeline_tc_in"], fps)))
    return itens, avisos


def trilhas_da_selecao(itens: list[dict]) -> list[str]:
    """As trilhas envolvidas, na ordem do Avid (V antes de A) — para o aviso de várias trilhas."""
    return [_trilha(t) for t in sorted({int(i["track"]) for i in itens})]


def impressao_digital(itens: list[dict]) -> tuple:
    """Iguais ⇔ mesma seleção. É o que diz "nada novo": sem seleção, o Ctrl+C do Avid mantém
    a cópia anterior (medido) e a coleta traria a mesma coisa de novo."""
    return tuple(sorted((chave(i), i["timeline_tc_out"]) for i in itens))


# ── 2. a timeline inteira → só o insert ─────────────────────────────────────────────────


def _vazio(s: dict) -> dict:
    return {**s, "mob_id": None, "clip_name": "(gap)", "media_ref": None, "is_gap": True,
            "is_transition": False, "is_effect": False, "has_motion_effect": False,
            "effects": [], "source_start_frames": 0, "cutpoint": None}


def _aparar(s: dict, ini: int, fim: int, fps: float) -> dict:
    """O clipe `s` só entre `ini` e `fim` (frames da timeline). Só para clipe SEM velocidade."""
    s_ini = _tc(s["timeline_tc_in"], fps)
    avanco = ini - s_ini
    # O ponto na fonte anda na taxa da FONTE (um take 24 numa timeline 23,976 anda igual; um
    # 50 numa 25 anda o dobro).
    razao = (float(s.get("source_fps") or 0) or fps) / fps
    return {**s,
            "timeline_tc_in": frames_to_tc(ini, fps),
            "timeline_tc_out": frames_to_tc(fim, fps),
            "duration_frames": fim - ini,
            "source_start_frames": int(s.get("source_start_frames") or 0) + round(avanco * razao)}


def filtrar_insert(resultado: dict, selecao: list[dict]) -> dict:
    """A leitura com só os segmentos da `selecao` — o resto vira vazio (ver o topo do módulo).

    Não altera `resultado`. Os avisos do que não pôde ser feito exatamente vão para
    `avisos`, como em toda leitura.
    """
    fps = float(resultado.get("timeline_fps") or 0) or 25.0
    fora = copy.deepcopy(resultado)
    segs = fora.get("segments") or []
    avisos: list[str] = []

    # Qual trecho de cada segmento foi escolhido (índice → (ini, fim)).
    faixas: dict[tuple, list[tuple[int, int]]] = {}
    for it in selecao:
        faixas.setdefault((int(it["track"]), it["mob_id"]), []).append(
            (_tc(it["timeline_tc_in"], fps), _tc(it["timeline_tc_out"], fps)))
    escolhido: dict[int, tuple[int, int]] = {}
    for i, s in enumerate(segs):
        if not _e_clipe(s):
            continue
        s_ini, s_fim = _tc(s["timeline_tc_in"], fps), _tc(s["timeline_tc_out"], fps)
        dentro = [(max(a, s_ini), min(b, s_fim))
                  for a, b in faixas.get((int(s["track"]), s["mob_id"]), []) if a < s_fim and b > s_ini]
        if dentro:
            escolhido[i] = (min(a for a, _ in dentro), max(b for _, b in dentro))

    # Transições: vizinhos na MESMA trilha, pela contabilidade de sobreposição da leitura
    # (a transição vai de B.início a A.fim).
    cortes: dict[int, dict] = {}          # índice do clipe → {"ini": corte} / {"fim": corte}
    remover: set[int] = set()
    for i, s in enumerate(segs):
        if not s.get("is_transition"):
            continue
        t_ini, t_fim = _tc(s["timeline_tc_in"], fps), _tc(s["timeline_tc_out"], fps)
        corte = t_ini + int(s.get("cutpoint") if s.get("cutpoint") is not None
                            else (t_fim - t_ini) // 2)
        mesma = [(j, x) for j, x in enumerate(segs) if j != i and int(x.get("track") or 0)
                 == int(s.get("track") or 0) and _e_clipe(x)]
        a = next((j for j, x in mesma if _tc(x["timeline_tc_out"], fps) == t_fim), None)
        b = next((j for j, x in mesma if _tc(x["timeline_tc_in"], fps) == t_ini), None)

        def inteiro(j):
            return j is not None and j in escolhido and escolhido[j] == (
                _tc(segs[j]["timeline_tc_in"], fps), _tc(segs[j]["timeline_tc_out"], fps))

        # Um lado que JÁ era vazio no original (fade-in/fade-out do editor) conta como aceito;
        # sem nenhum lado escolhido, a transição não tem o que fazer na timeline do insert.
        algum = (a is not None and a in escolhido) or (b is not None and b in escolhido)
        if algum and (a is None or inteiro(a)) and (b is None or inteiro(b)):
            continue                       # dissolve entre escolhidos, ou fade de um escolhido
        remover.add(i)
        if not algum:
            continue
        remover.add(i)
        if a is not None and a in escolhido:
            cortes.setdefault(a, {})["fim"] = corte
        if b is not None and b in escolhido:
            cortes.setdefault(b, {})["ini"] = corte

    novos = []
    for i, s in enumerate(segs):
        if i in remover:
            continue
        if not _e_clipe(s):
            novos.append(s)
            continue
        if i not in escolhido:
            novos.append(_vazio(s))
            continue
        s_ini, s_fim = _tc(s["timeline_tc_in"], fps), _tc(s["timeline_tc_out"], fps)
        ini, fim = escolhido[i]
        ini = max(ini, cortes.get(i, {}).get("ini", ini))
        fim = min(fim, cortes.get(i, {}).get("fim", fim))
        if (ini, fim) == (s_ini, s_fim):
            novos.append(s)
        elif s.get("has_motion_effect"):
            avisos.append(f"{_trilha(int(s['track']))} {s['timeline_tc_in']} “{s.get('clip_name')}”: "
                          "tem velocidade — foi inteiro, sem aparar ao corte/trecho")
            novos.append(s)
        else:
            novos.append(_aparar(s, ini, fim, fps))

    fora["segments"] = novos
    fora["total_segments"] = len(novos)
    fora["avisos"] = list(fora.get("avisos") or []) + [{"texto": t, "vezes": 1} for t in avisos]
    return fora
