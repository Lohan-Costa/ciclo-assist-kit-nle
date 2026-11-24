"""Leitura (e, futuramente, escrita) de marcadores/locators da timeline do Avid.

No AAF, os marcadores que o Avid chama de **locators** ficam num **EventMobSlot**
do CompositionMob de topo (media_kind "Descriptive Metadata"), cujo segmento é uma
`Sequence` de componentes `DescriptiveMarker`. Cada marcador carrega:

  Position                      → frame na timeline (na edit-rate do slot)
  Comment                       → texto do locator
  CommentMarkerColorExtended    → nome da cor ('Red', 'Green', …)
  CommentMarkerColor            → RGB 16-bit {red, green, blue}
  CommentMarkerUSer             → usuário que criou
  DescribedSlots                → set de slot_ids do CompositionMob a que se aplica
  CommentMarkerAttributeList    → _ATN_CRM_* (user, date, time, id, comentário)

`read_markers()` devolve uma lista de dicts já normalizada. A escrita programática
de marcadores (`add_marker`) será construída sobre o mesmo entendimento.
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger("relinker")


def _attr_map(marker) -> dict:
    """Achata a CommentMarkerAttributeList (_ATN_CRM_*) em {nome: valor}."""
    out: dict = {}
    try:
        for tv in (marker["CommentMarkerAttributeList"].value or []):
            try:
                out[getattr(tv, "name", "")] = tv.value
            except Exception:
                continue
    except Exception:
        pass
    return out


def _prop(marker, key, default=None):
    try:
        if key in marker:
            return marker[key].value
    except Exception:
        pass
    return default


def read_markers(main_comp, fps: float = 0.0) -> list[dict]:
    """Lê todos os locators do CompositionMob de topo.

    Retorna [{position, comment, color, color_rgb, user, date, time,
             described_slots, id, slot_id}], ordenado por posição.
    `position` é o frame na timeline (contínuo, base 0 = início da timeline).
    """
    markers: list[dict] = []
    try:
        slots = list(main_comp.slots)
    except Exception:
        return markers

    for slot in slots:
        if type(slot).__name__ != "EventMobSlot":
            continue
        seg = getattr(slot, "segment", None)
        if seg is None:
            continue
        comps = list(getattr(seg, "components", []) or [seg])
        for c in comps:
            if "Marker" not in type(c).__name__:
                continue
            attrs = _attr_map(c)
            described = _prop(c, "DescribedSlots", set()) or set()
            try:
                described = sorted(int(x) for x in described)
            except Exception:
                described = list(described)
            markers.append({
                "position": int(_prop(c, "Position", 0) or 0),
                "comment": _prop(c, "Comment", "") or attrs.get("_ATN_CRM_COM", "") or "",
                # Nome textual da cor ('Red', 'Green', …) vem da attribute-list; as
                # propriedades CommentMarkerColor/Extended carregam o RGB 16-bit.
                "color": (attrs.get("_ATN_CRM_COLOR_EXTENDED")
                          or attrs.get("_ATN_CRM_COLOR") or ""),
                "color_rgb": _prop(c, "CommentMarkerColor", None),
                "user": _prop(c, "CommentMarkerUSer", attrs.get("_ATN_CRM_USER")) or "",
                "date": attrs.get("_ATN_CRM_DATE", "") or "",
                "time": attrs.get("_ATN_CRM_TIME", "") or "",
                "described_slots": described,
                "id": attrs.get("_ATN_CRM_ID", "") or "",
                "slot_id": getattr(slot, "slot_id", None),
            })

    markers.sort(key=lambda m: m["position"])
    log.info("Locators lidos: %d", len(markers))
    return markers
