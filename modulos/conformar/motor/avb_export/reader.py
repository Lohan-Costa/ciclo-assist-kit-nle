#!/usr/bin/env python3
"""reader.py — leitor TOLERANTE de .avb (vendorizado do eng-rev `avb_read.py`).

O pyavb 1.4.0 ESTOURA (`unknown ext tag 0x02`) ao ler alguns PCMADescriptor reais (o u32 que o
MC 25.12 grava em faixas de MÚSICA). Isso derruba qualquer leitura de bin com áudio real. Aqui, em
vez de só drenar, DECODIFICAMOS a tag antes-desconhecida (0x02 = `read_assert_tag 0x47` + u32) e
REGISTRAMOS qualquer tag realmente-desconhecida (bytes crus) p/ mineração de estrutura nova.

Uso:
    from .reader import topen
    with topen(path) as f:
        ...            # avb.open() normal, mas PCMA não crasha
"""
import avb
from avb.essence import PCMADescriptor, MediaFileDescriptor
from avb.ioctx import AVBIOContext as IO

UNKNOWN_LOG = []          # tags ext realmente desconhecidas (p/ RE): {class_id, tag, payload_hex}
EXT02_LOG = []            # valores do ext 0x02 decodificado (PCMA de música): {value}
_installed = False


def _pcma_read(self, f):
    """PCMADescriptor.read tolerante: lê todos os campos conhecidos + os ext 0x01/0x03, DECODIFICA
    o 0x02 (0x47 + u32) e drena+registra qualquer outra tag desconhecida sem estourar."""
    MediaFileDescriptor.read(self, f)
    ctx = self.root.ictx
    ctx.read_assert_tag(f, 0x02)
    ctx.read_assert_tag(f, 0x01)
    self.channels = ctx.read_u16(f)
    self.quantization_bits = ctx.read_u16(f)
    self.sample_rate = ctx.read_exp10_encoded_float(f)
    self.locked = ctx.read_bool(f)
    self.audio_ref_level = ctx.read_s16(f)
    self.electro_spatial_formulation = ctx.read_s32(f)
    self.dial_norm = ctx.read_u16(f)
    self.coding_format = ctx.read_u32(f)
    self.block_align = ctx.read_u32(f)
    self.sequence_offset = ctx.read_u16(f)
    self.average_bps = ctx.read_u32(f)
    self.has_peak_envelope_data = ctx.read_bool(f)
    for k in ('peak_envelope_version', 'peak_envelope_format', 'points_per_peak_value',
              'peak_envelope_block_size', 'peak_channel_count', 'peak_frame_count'):
        setattr(self, k, ctx.read_s32(f))
    self.peak_of_peaks_offset = ctx.read_u64(f)
    self.peak_envelope_timestamp = ctx.read_s32(f)
    # laço de ext tags (tolerante)
    while True:
        pos = f.tell()
        mk = IO.read_u8(f)
        if mk != 0x01:
            f.seek(pos)
            break
        tag = IO.read_u8(f)
        if tag == 0x01:
            ctx.read_assert_tag(f, 77); self.ebu_timestamp = ctx.read_s64(f)
        elif tag == 0x03:
            ctx.read_assert_tag(f, 76); self.timecode_framerate = ctx.read_string(f)
        elif tag == 0x02:
            # DECODIFICADO (2026-07-04): 0x47 + u32 LE. Gravado pelo MC em faixas de música.
            # pyavb não deixa setar atributo não-declarado -> guarda no property_data.
            ctx.read_assert_tag(f, 0x47)
            val = ctx.read_u32(f)
            self.property_data["ext_unknown_0x02"] = val
            EXT02_LOG.append({"value": val})
        else:
            # tag genuinamente nova: registra e drena o resto (não estoura)
            rest = f.read()
            UNKNOWN_LOG.append({"class_id": str(self.class_id), "tag": tag,
                                "payload_hex": bytes(rest[:64]).hex()})
            return
    ctx.read_assert_tag(f, 0x03)


def install():
    """Aplica os patches de tolerância (idempotente). Chame antes de abrir bins com áudio real."""
    global _installed
    if _installed:
        return
    PCMADescriptor.read = _pcma_read
    _installed = True


def topen(path):
    """avb.open() tolerante (PCMA não crasha). Retorna o mesmo context manager do pyavb.

    ⛔ O arquivo é aberto AQUI, e fechado se o pyavb falhar ao ler o cabeçalho. O `AVBFile`
    abre o arquivo no `__init__` e, se a leitura falha ali (bin estragada, arquivo que não é
    `.avb`), levanta sem fechar — e o `with` nunca chega a existir para fechar. No Windows
    isso deixa a `.avb` TRANCADA enquanto o serviço viver (WinError 32: medido 2026-09-25,
    `tests/test_receber.py`, "Abrir arquivo…" com uma bin inválida). O `close()` do pyavb
    fecha também o objeto de arquivo passado, então o caminho normal não muda.
    """
    import io

    install()
    fh = io.open(path, "rb", buffering=io.DEFAULT_BUFFER_SIZE)
    try:
        return avb.open(fh)
    except BaseException:
        fh.close()
        raise
