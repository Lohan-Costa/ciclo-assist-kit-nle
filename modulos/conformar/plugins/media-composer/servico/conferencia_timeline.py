"""A conferência pela referência sobre a timeline COMO ELA ESTÁ AGORA no Resolve (autor, 2026-10-19).

Quem não deu o vídeo de referência antes de montar tem dois caminhos, e os dois conferem a timeline atual, não a que
o app entregou:
  1. pôr a referência na timeline à mão, e quantas mudanças quiser (tirar takes que não aparecem, simplificar a
     montagem), e então pedir a conferência — o app ACHA a referência: a regra de ofício (trilha mais alta, um clipe
     do início ao fim; `prproj.leitura._referencia_na_timeline`, banco `operacoes-de-nle.md` J.3b) ou, se ela não
     valer, o vídeo que entrou DEPOIS da nossa entrega (um arquivo que não estava na mídia do DRT);
  2. indicar o vídeo pelo painel: ele entra numa trilha de vídeo nova acima de todas, desligada, do início da
     timeline; o som, se o editor quiser, numa trilha de áudio nova. Nenhuma trilha de áudio do editor sai.

A leitura (`resolve_externo.ler_timeline`) chega aqui como dados: os itens pela API (com o arquivo de cada um) e as
transições pelo DRT exportado (a API não as descreve). Daqui sai o mesmo `contexto` de `prproj_para_drt._conferencia`,
que `conferencia.Conferencias.criar` transforma no plano de sempre.
"""
from __future__ import annotations

import ntpath
import os

from media.safepath import forma_windows
from prproj.leitura import _referencia_na_timeline, frames_para_tc
from tools.conferir_conform import pontos_visiveis

_IMAGENS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".psd", ".bmp", ".gif", ".exr", ".dpx"}


def _norma(p: str) -> str:
    """Para comparar caminhos: pela FORMA do caminho, não pelo sistema que roda (matriz, regra 3) — um `D:\\…`
    ignora a caixa da letra também no Mac (o `os.path.normcase` do Mac não mexe; medido 2026-10-24)."""
    if not p:
        return ""
    if forma_windows(p):
        return ntpath.normcase(ntpath.normpath(p))
    return os.path.normcase(os.path.normpath(p))


def segmentos(leitura: dict) -> list[dict]:
    """Os itens da leitura → os segmentos que o motor da conferência conhece (`timeline_tc_in` desde o INÍCIO da
    timeline, na base nominal). Trilha ou clipe desligado = `disabled` (não é plano do filme); item sem arquivo
    (título, gerador) = `is_effect`; escala, corte ou opacidade = o `params` que o `_cobre` lê."""
    nominal = int(leitura["nominal"])
    inicio = int(leitura.get("inicio") or 0)
    segs = []
    for it in leitura.get("itens") or []:
        q = int(it["start"]) - inicio
        dur = int(it["dur"])
        if dur <= 0 or q < 0:
            continue
        arquivo = it.get("arquivo") or ""
        crop = {k: v for k, v in (it.get("crop") or {}).items() if v}
        segs.append({"timeline_tc_in": frames_para_tc(q, nominal), "duration_frames": dur,
                     "source_start_frames": int(it.get("fonte_in") or 0),
                     "source_fps": float(it.get("fps_fonte") or leitura.get("fps") or nominal),
                     "clip_name": it.get("nome") or os.path.basename(arquivo), "track": int(it["trilha"]),
                     "is_audio": it.get("tipo") == "audio", "is_gap": False, "is_transition": False,
                     "is_effect": not arquivo and not it.get("composto"), "disabled": bool(it.get("desligado")),
                     "media_ref": {"local_path": arquivo},
                     "effects": [{"params": {"scale_x": min(float(it.get("zoom") or 1.0), 1.0)
                                             if float(it.get("opacidade") or 100) >= 99.9 else 0.0,
                                             "crop_frac": crop}}]})
    for t in leitura.get("transicoes") or []:
        letra, n = str(t.get("trilha") or "")[:1], str(t.get("trilha") or "")[1:]
        if not n.isdigit() or int(t.get("start", -1)) < inicio:
            continue
        segs.append({"timeline_tc_in": frames_para_tc(int(t["start"]) - inicio, nominal),
                     "duration_frames": int(t.get("dur") or 0), "track": int(n), "is_audio": letra == "A",
                     "is_transition": True, "is_gap": False, "is_effect": False, "clip_name": t.get("nome") or ""})
    return segs


def _video(s: dict) -> bool:
    if s.get("is_audio") or s.get("is_gap") or s.get("is_transition") or s.get("is_effect"):
        return False
    caminho = (s.get("media_ref") or {}).get("local_path") or ""
    return os.path.splitext(caminho)[1].lower() not in _IMAGENS


def achar_referencia(segs: list[dict], nominal: int, entregues: set[str] | None = None,
                     arquivo: str | None = None) -> tuple[dict | None, str]:
    """A referência na timeline: `(segmento, como)` ou `(None, por que não)`.

    `arquivo` = a indicada pelo painel (já posta na timeline); senão a regra de ofício; senão o vídeo que não estava
    na nossa entrega (`entregues` = os arquivos do DRT). Mais de um arquivo novo = o editor indica qual."""
    if arquivo:
        alvo = _norma(arquivo)
        achados = [s for s in segs if _video(s) and _norma((s.get("media_ref") or {}).get("local_path")) == alvo]
        if not achados:
            return None, "o vídeo indicado não está na timeline"
        return max(achados, key=lambda s: (s["track"], s["duration_frames"])), "indicada"
    # a trilha desligada também vale: é como a referência costuma ficar (a nossa nasce desligada). Título e texto
    # (sem arquivo) não contam para a "trilha mais alta": a trilha de notas nasce ACIMA da referência
    sem_texto = [s for s in segs if not s.get("is_effect")]
    regra = _referencia_na_timeline(sem_texto, nominal)
    if regra is not None:
        return regra, "achada na timeline"
    # O render de referência costuma terminar uns quadros ANTES da timeline (o MXF do Avid no lab: 172 de 175 quadros,
    # 2026-10-19). Até 1 s de folga vale; os pontos depois do fim dela só não conferem.
    regra = _referencia_na_timeline(sem_texto, nominal, tolerancia=nominal)
    if regra is not None:
        return regra, "achada na timeline"
    if entregues is None:
        return None, "não achei a referência na timeline"
    nossos = {_norma(p) for p in entregues}
    novos: dict[str, list[dict]] = {}
    for s in segs:
        c = (s.get("media_ref") or {}).get("local_path") or ""
        if c and _video(s) and _norma(c) not in nossos:          # o composto (sem arquivo) nunca é a referência
            novos.setdefault(_norma(c), []).append(s)
    if len(novos) > 1:
        return None, (f"{len(novos)} vídeos entraram na timeline depois da entrega — indique qual é a referência")
    if not novos:
        return None, "não achei a referência na timeline"
    ref = max(next(iter(novos.values())), key=lambda s: s["duration_frames"])
    return ref, "entrou depois da entrega"


def contexto(leitura: dict, entregues: set[str] | None = None, arquivo: str | None = None) -> dict:
    """`{ok, contexto, como, referencia, trilha_referencia}` para `Conferencias.criar`, ou `{ok: False, erro,
    sem_referencia}`. A trilha da referência é desligada durante a exportação dos quadros: ela tem de ser SÓ dela."""
    nominal = int(leitura["nominal"])
    segs = segmentos(leitura)
    ref, como = achar_referencia(segs, nominal, entregues, arquivo)
    if ref is None:
        return {"ok": False, "sem_referencia": True, "erro": como}
    vizinhos = [s for s in segs if s is not ref and not s.get("is_audio") and not s.get("is_transition")
                and s["track"] == ref["track"]]
    if vizinhos:
        return {"ok": False, "erro": f"a referência divide a trilha V{ref['track']} com outros clipes: ponha-a numa "
                                     "trilha só dela (a conferência desliga essa trilha para exportar os quadros)"}
    caminho = ref["media_ref"]["local_path"]
    for s in segs:
        if s is ref or (s.get("is_audio") and _norma((s.get("media_ref") or {}).get("local_path")) == _norma(caminho)):
            s["referencia"] = True
    pontos = pontos_visiveis(segs, nominal)
    if not pontos:
        return {"ok": False, "erro": "a timeline não tem planos de vídeo visíveis para conferir"}
    ctx = {"referencia": caminho, "trilha_referencia": ref["track"],
           "ref_na_timeline": _quadro(ref["timeline_tc_in"], nominal),
           "ref_entrada": int(ref.get("source_start_frames") or 0),
           "ref_fps": float(ref.get("source_fps") or leitura.get("fps") or nominal),
           "fps": float(leitura.get("fps") or nominal), "nominal": nominal,
           "inicio": int(leitura.get("inicio") or 0),
           "quadro_px": [int(leitura.get("largura") or 1920), int(leitura.get("altura") or 1080)],
           "pontos": pontos}
    return {"ok": True, "contexto": ctx, "como": como, "referencia": os.path.basename(caminho),
            "trilha_referencia": ref["track"]}


def _quadro(tc: str, nominal: int) -> int:
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s) * nominal + f
