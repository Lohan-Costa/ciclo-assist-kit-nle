"""O CONFORM PELO MAPA, do lado do Conformar (plano `docs/plano/2026-11-26-carta-registro-da-producao.md`, etapa 3).

Antes do banco e da varredura, o relink pergunta ao núcleo (`/nucleo/carta/mapa`, `cicloassist/carta/mapa.py`) de que
ORIGINAL é cada offline da timeline. O que a Carta souber com certeza vira `caminho_conhecido` (o degrau 1 do
`casar_masters`) e sai da lista de nomes a procurar no disco; o resto segue o De Lá Pra Cá de sempre.

⛔ Acelerador e GUIA, nunca a regra: sem o Ciclo Assist no ar, sem Carta, ou com erro, a resposta é vazia e o relink é o
de antes. ⛔ Mapa × casamento discordando (o banco, ou o caminho que o master já trazia, apontam OUTRO arquivo que não o
próprio offline) = empate: os dois vão ao editor, nada se escolhe sozinho (a regra do empate, plano §6).
"""
from __future__ import annotations

import logging
import os

log = logging.getLogger("delapraca.mapa")

VAZIO = {"achados": {}, "alertas": [], "cartas": 0}


def consultar(masters: list) -> dict:
    """A resposta do núcleo para os `masters` (objetos `Master`), ou `VAZIO`. Nunca levanta."""
    pedido = [{"chave": m.mob_id, "nome": getattr(m, "nome", ""), "origem": getattr(m, "origem", "") or "",
               "e_audio": bool(getattr(m, "e_audio", False))}
              for m in masters if getattr(m, "mob_id", None) and getattr(m, "origem", None)]
    if not pedido:
        return dict(VAZIO)
    try:
        import premiere_ponte
        r = premiere_ponte._nucleo("POST", "/nucleo/carta/mapa", {"masters": pedido}, prazo=120)
    except Exception as e:  # noqa: BLE001 — sem o núcleo, o relink de sempre
        log.info("mapa da Carta indisponível (%s): segue o casamento de sempre", e)
        return dict(VAZIO)
    if not r.get("ok"):
        log.warning("o mapa da Carta falhou: %s", r.get("motivo"))
        return dict(VAZIO)
    return {"achados": r.get("achados") or {}, "alertas": r.get("alertas") or [], "cartas": r.get("cartas") or 0}


def _mesmo(a: str, b: str) -> bool:
    import unicodedata
    n = lambda c: unicodedata.normalize("NFC", os.path.normcase(os.path.abspath(c)))  # noqa: E731
    return bool(a and b) and n(a) == n(b)


def aplicar(masters: list, mapa: dict) -> dict[str, str]:
    """Põe o original do mapa em `caminho_conhecido`. Devolve `{mob_id: o OUTRO caminho}` dos que discordam (o
    caminho que o master já tinha — pelo banco ou pela rota — e não é o próprio offline): esses não recebem o mapa;
    `marcar` os põe em empate depois do casamento."""
    discordam: dict[str, str] = {}
    for m in masters:
        a = (mapa.get("achados") or {}).get(m.mob_id)
        if not a or not a.get("arquivo"):
            continue
        antes = getattr(m, "caminho_conhecido", None)
        origem = getattr(m, "origem", "") or ""
        if antes and not _mesmo(antes, a["arquivo"]) and not _mesmo(antes, origem) \
                and not _mesmo(antes, "/Volumes" + origem):
            discordam[m.mob_id] = antes
            m.caminho_conhecido = None
            continue
        m.caminho_conhecido = a["arquivo"]
    return discordam


def marcar(casamentos: list, mapa: dict, discordam: dict[str, str]) -> None:
    """Depois do `casar_masters`: o casado pelo mapa diz que foi pelo mapa (método `mapa` e a frase da transformação);
    o que discorda vira EMPATE com os dois candidatos; o alerta do mapa vai ao motivo de quem não casou por ele."""
    achados = mapa.get("achados") or {}
    alertas = {a.get("chave"): a.get("motivo") for a in mapa.get("alertas") or []}
    for c in casamentos:
        k = c.master.mob_id
        a = achados.get(k)
        if k in discordam and a:
            outro = discordam[k]
            c.arquivo, c.sugestao, c.ambiguo, c.metodo, c.confianca = None, None, True, "mapa_discorda", 0.0
            c.candidatos = [{"path": a["arquivo"], "filename": os.path.basename(a["arquivo"]), "score": 1.0,
                             "metodo": "mapa"},
                            {"path": outro, "filename": os.path.basename(outro), "score": 1.0, "metodo": "banco"}]
            c.motivo = (f"o mapa da Carta {a.get('carta')} diz {os.path.basename(a['arquivo'])}, o casamento diz "
                        f"{os.path.basename(outro)} — o editor decide")
            continue
        if a and c.arquivo and _mesmo(c.arquivo, a["arquivo"]):
            c.metodo, c.confianca = "mapa", 1.0
            c.motivo = a.get("frase") or f"pelo mapa da Carta {a.get('carta')}"
        elif k in alertas and not c.arquivo:
            c.motivo = "; ".join(x for x in (c.motivo, alertas[k]) if x)
        elif k in alertas:
            c.motivo = "; ".join(x for x in (c.motivo, "mapa: " + alertas[k]) if x)

