"""Backend AVB do Relinker: autora timeline .avb (CompositionMob) sobre uma bin de mídia
AMA-online, a partir dos segmentos do parser neutro. Paralelo a aaf/writer, drp/writer,
otio_export/writer. Templates de efeito embutidos (templates.json) — project-neutral."""
import avb_fiel  # noqa: F401 — antes de qualquer leitura: a string nula (0xFFFF) sobrevive à regravação (B005)
from .translate import build_avb, build_avb_from_aaf, build_templates_json, set_remap
__all__ = ["build_avb", "build_avb_from_aaf", "build_templates_json", "set_remap"]
