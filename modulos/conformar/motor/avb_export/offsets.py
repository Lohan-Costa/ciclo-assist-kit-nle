#!/usr/bin/env python3
"""offsets.py — mapeador de OFFSET de campo (vendorizado do eng-rev `avb_offsets.py`).

Instrumenta os primitivos de leitura do pyavb (AVBIOContext) durante o read de UM objeto e registra,
p/ cada primitivo lido, o (offset dentro do objeto, tamanho, tipo, valor). Dá o BYTE EXATO de cada
campo — base p/ byte-surgery PRECISA (patch por offset, sem region-replace às cegas que colide).

O offset é relativo ao início dos DADOS do objeto (= object_positions[iid] + 8, cabeçalho de 8B):
offset_no_arquivo = f.object_positions[iid] + 8 + offset_no_objeto.
"""
from avb.ioctx import AVBIOContext

from . import reader as avb_read

# primitivos que carregam campos patcháveis (tamanho fixo). ATENÇÃO: o pyavb liga read_u32=read_u32le
# como atributo de INSTÂNCIA no __init__ (por byte-order), sombreando patch de classe -> wrappar os
# *le (que de fato executam em bins little-endian) + read_u8/read_bool (não são aliased).
_PRIMS = {"read_u8": 1, "read_bool": 1, "read_u16le": 2, "read_u32le": 4,
          "read_s16le": 2, "read_s32le": 4, "read_u64le": 8, "read_s64le": 8}


def map_object(path, instance_id):
    """[{off,size,kind,value}] de todos os primitivos lidos no objeto `instance_id` (offset no objeto)."""
    log = []
    recording = {"on": False}
    orig = {}       # name -> descriptor ORIGINAL de __dict__ (preserva staticmethod)

    def wrap(name, size, raw_fn, is_static):
        def w(f, *a, **k):
            pos = f.tell()
            v = raw_fn(f, *a, **k)
            if recording["on"]:
                log.append({"off": pos, "size": size, "kind": name, "value": v})
            return v
        return staticmethod(w) if is_static else w

    for name, size in _PRIMS.items():
        desc = AVBIOContext.__dict__.get(name)
        if desc is None:
            continue
        orig[name] = desc                              # o descriptor real (staticmethod/func)
        is_static = isinstance(desc, staticmethod)
        raw_fn = desc.__func__ if is_static else desc
        setattr(AVBIOContext, name, wrap(name, size, raw_fn, is_static))
    try:
        with avb_read.topen(path) as f:
            f.object_cache.pop(instance_id, None)     # força re-leitura instrumentada
            recording["on"] = True
            f.read_object(instance_id)
            recording["on"] = False
    finally:
        for name, desc in orig.items():
            setattr(AVBIOContext, name, desc)          # restaura o descriptor original (não desembrulhado)
    return log


def find_field(log, value, kind=None):
    """offsets (no objeto) onde um primitivo leu exatamente `value` (opcional filtrar por tipo)."""
    return [e["off"] for e in log if e["value"] == value and (kind is None or e["kind"] == kind)]


def file_offset(f, instance_id, off_in_obj):
    """offset ABSOLUTO no arquivo de um offset relativo ao objeto."""
    return f.object_positions[instance_id] + 8 + off_in_obj
