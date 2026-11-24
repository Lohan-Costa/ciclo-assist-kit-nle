#!/usr/bin/env python3
"""descriptor_patch.py — byte-patch PRECISO da GEOMETRIA de um CDCIDescriptor de vídeo.
(Vendorizado do eng-rev `avb_descriptor_patch.py`.)

Base do clone format-genérico na via BYTE-SURGERY (única provada ONLINE no MC). O clone clona a
cadeia (mob_id/path/data/duração/nome) mas copia o descriptor do template — errado se o formato difere.
Aqui patchamos os campos de geometria do descriptor POR OFFSET EXATO (via offsets), size-neutral,
reproduzindo o que o MC gravaria (validado por golden: patch 1920->2048 == B001 real, e corpus inteiro).

Só ÁUDIO NÃO precisa disto: formatos PCM são discretos -> template por (coding,bits,canais) exato.
Vídeo tem resolução contínua -> geometry patch por clipe.

LAYOUT CDCI (via offsets): âncora = stored_width (3 offsets = stored/sampled/display_width, todos
= largura); stored_height @ âncora-4; aspect_num @ âncora+38, aspect_den = próximo s32; as 3 CAIXAS têm
tag 0x47 (u8=71) antes de CADA valor -> den = PRÓXIMO s32 (pular u8). AVC level mora em ATTR aninhado
(objeto separado) -> não tratado aqui (minor; usar template do mesmo codec-class).
"""
import struct

from . import offsets as O


def _next_s32(log, byoff, off):
    """offset do PRÓXIMO primitivo s32/u32 depois de `off` (pula tags u8 0x47)."""
    i = byoff[off] + 1
    while log[i]["kind"] not in ("read_s32le", "read_u32le"):
        i += 1
    return log[i]["off"]


def plan_video_geometry(log, tpl_pd, target_pd):
    """{offset_no_objeto: valor_novo_int} p/ patchar a geometria: widths, stored_height, aspect,
    e X/W (num+den) das 3 caixas. tpl_pd/target_pd = property_data do template e do ALVO (do gerador
    video_descriptor). Só emite patches p/ campos que MUDAM."""
    byoff = {e["off"]: i for i, e in enumerate(log)}
    P = {}
    # widths (3 offsets, todos = largura do template)
    w_offs = O.find_field(log, tpl_pd["stored_width"])
    if not w_offs:
        raise ValueError("stored_width do template nao localizado no log")
    if target_pd["stored_width"] != tpl_pd["stored_width"]:
        for off in w_offs:
            P[off] = target_pd["stored_width"]
    anchor = min(w_offs)
    # stored_height (@ âncora-4)
    if target_pd["stored_height"] != tpl_pd["stored_height"]:
        P[anchor - 4] = target_pd["stored_height"]
    # aspect (num @ âncora+38 ; den = próximo s32)
    if list(target_pd["aspect_ratio"]) != list(tpl_pd["aspect_ratio"]):
        P[anchor + 38] = target_pd["aspect_ratio"][0]
        P[_next_s32(log, byoff, anchor + 38)] = target_pd["aspect_ratio"][1]
    # caixas: X e W (num @ offset do valor template; den = próximo s32). Y/H ficam (mesma altura).
    for comp in (0, 2):                      # 0=X, 2=W
        tval = tpl_pd["valid_box"][comp]     # [num,den] template
        nval = target_pd["valid_box"][comp]  # [num,den] alvo
        if list(nval) == list(tval):
            continue
        for off in O.find_field(log, tval[0]):        # todas as 3 caixas usam o mesmo num de largura
            P[off] = nval[0]
            P[_next_s32(log, byoff, off)] = nval[1]
    return P


def apply_patches(raw, base, patches):
    """aplica {offset_no_objeto: valor_int} como s32 LE em `raw` (bytearray) a partir de `base`."""
    for off, val in patches.items():
        raw[base + off:base + off + 4] = struct.pack("<i", int(val))
    return raw
