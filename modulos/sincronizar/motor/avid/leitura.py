"""
avid/leitura.py — abrir uma `.avb` sem estourar em áudio de verdade.

## ⛔⛔ Por que este módulo existe, e a decisão que ele carrega

O **pyavb 1.4.0 estoura** (`unknown ext tag 0x02`) ao ler alguns `PCMADescriptor`
reais — o `u32` que o Media Composer grava em faixas de **música**. Não é um caso
exótico: derruba a leitura de qualquer bin com áudio de trilha, e o `avb.open` cru
falha no meio do percurso, depois de já ter lido parte do arquivo.

O conserto é um **patch no método de leitura do descritor**, vendorizado do
`De Lá Pra Cá` (`motores/delapraca/avb_export/reader.py`), onde roda em produção
desde 2026-07. Ele decodifica a tag antes-desconhecida (`0x02` = `0x47` + `u32`) e
**drena** qualquer outra, em vez de levantar.

⚠️ **Isto é um patch GLOBAL de dependência dentro de um app assinado**, e a decisão
foi tomada com isso à vista, em 2026-09-05. O que a torna aceitável:

- **O pyavb está PINADO** em `1.4.0` (`requirements.txt`, `==` por auditoria). Um
  patch contra uma versão fixa não se desatualiza sozinho — e o dia em que o pin
  subir, o teste abaixo é quem cobra.
- **Só a LEITURA é tocada.** `PCMADescriptor.read` — nada da escrita, que é o que o
  `writer.py` faz. Uma bin escrita pelo Órbita sai idêntica com ou sem o patch.
- **É idempotente e explícito.** Não roda no import: quem quer ler chama `abrir()`,
  e é ali que o patch entra. Um `import` que muda o comportamento de uma biblioteca
  para o processo inteiro seria a versão inaceitável da mesma ideia.
- **A alternativa era pior.** Sem ele, "o Órbita não lê bins com música" — e o
  editor descobriria isso no meio de uma diária, com uma exceção sobre uma tag
  hexadecimal.

⭐ O que o patch aprendeu e o cru não sabe fica em `EXT02_LOG` e `TAGS_DESCONHECIDAS`:
tag nova aparece ali em vez de derrubar a leitura, e é dali que sai o próximo
achado de estrutura.
"""

from __future__ import annotations

import registro

log = registro.log(__name__)

#: Valores do ext `0x02` decodificado (o `u32` das faixas de música).
EXT02_LOG: list[dict] = []

#: Tags de extensão genuinamente novas, drenadas em vez de estourar.
#: ⚠️ Uma entrada aqui é matéria-prima de engenharia reversa, não erro do usuário.
TAGS_DESCONHECIDAS: list[dict] = []

_instalado = False


def _pcma_read_tolerante(self, f):
    """`PCMADescriptor.read` que não morre numa tag de extensão desconhecida.

    Lê todos os campos conhecidos e os ext `0x01`/`0x03`, DECODIFICA o `0x02`
    (`0x47` + `u32`), e drena+registra qualquer outra tag sem levantar.
    """
    from avb.essence import MediaFileDescriptor
    from avb.ioctx import AVBIOContext as IO

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
    for k in ("peak_envelope_version", "peak_envelope_format", "points_per_peak_value",
              "peak_envelope_block_size", "peak_channel_count", "peak_frame_count"):
        setattr(self, k, ctx.read_s32(f))
    self.peak_of_peaks_offset = ctx.read_u64(f)
    self.peak_envelope_timestamp = ctx.read_s32(f)

    # O laço de ext tags — a parte tolerante.
    while True:
        pos = f.tell()
        marcador = IO.read_u8(f)
        if marcador != 0x01:
            f.seek(pos)
            break
        tag = IO.read_u8(f)
        if tag == 0x01:
            ctx.read_assert_tag(f, 77)
            self.ebu_timestamp = ctx.read_s64(f)
        elif tag == 0x03:
            ctx.read_assert_tag(f, 76)
            self.timecode_framerate = ctx.read_string(f)
        elif tag == 0x02:
            # Decodificado em 2026-07-04: `0x47` + `u32` LE, gravado pelo MC em
            # faixas de música. ⚠️ O pyavb não deixa criar atributo não-declarado,
            # então o valor vai para o `property_data`.
            ctx.read_assert_tag(f, 0x47)
            valor = ctx.read_u32(f)
            self.property_data["ext_unknown_0x02"] = valor
            EXT02_LOG.append({"value": valor})
        else:
            # Tag genuinamente nova: registra, drena o resto e devolve o que já leu.
            # ⚠️ Devolver o parcial é melhor que levantar — o descritor de áudio não
            # é o que o subclipador precisa, e derrubar a bin inteira por causa dele
            # trocaria uma diária por uma linha de metadado.
            resto = f.read()
            TAGS_DESCONHECIDAS.append({"class_id": str(self.class_id), "tag": tag,
                                       "payload_hex": bytes(resto[:64]).hex()})
            log.info("tag de extensão desconhecida (0x%02x) num PCMADescriptor — "
                     "drenada, a leitura continua", tag)
            return
    ctx.read_assert_tag(f, 0x03)


def instalar() -> None:
    """Aplica a tolerância. Idempotente."""
    global _instalado
    if _instalado:
        return
    from avb.essence import PCMADescriptor

    PCMADescriptor.read = _pcma_read_tolerante
    _instalado = True
    log.debug("leitura tolerante de PCMADescriptor instalada")


def abrir(caminho: str):
    """`avb.open()` que sobrevive a áudio real. Devolve o mesmo context manager."""
    import avb

    instalar()
    return avb.open(str(caminho))
