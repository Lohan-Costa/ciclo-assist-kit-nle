"""Burn-in do Premiere ("Metadata & Timecode Burn-in") → Text+ do Resolve, um clipe "Fusion Title".

O Premiere queima o metadado no quadro; o Resolve não tem esse efeito por clipe. Exceção à regra
"título = Text simples" (memória `titulo-alvo-text-simples`), pedida pelo autor em 2026-10-08: o
Text+ puxa o TC sozinho (modificador TimeCode), então o burn-in continua VIVO no Resolve — o TC
da timeline em cada quadro, sem queimar números na mão.

Medido no Resolve Studio 21.1 (macOS), 2026-10-08, com gabarito do próprio Resolve
(`InsertFusionTitleIntoTimeline("Text+")` + `Export` DRT) e o burn-in do PRODB na referência:

- O clipe é um `Sm2TiVideoClip` "Fusion Title" com a composição em `CompositionTable/CompositionBA`:
  `[u32 BE tamanho]` + zlib de um mapa (o formato dos FieldsBlob: `count`, `0_name`,
  `0_mediaIdList`, `0_data`). ⛔ O `0_data` tem de vir na forma `Compressed = true` do Resolve:
  o cabeçalho em texto + `\\0` + `[u32 LE tamanho]` + zlib do bloco `Tools`. Em texto puro (mesmo
  o texto idêntico ao do `ExportFusionComp`) o título importa e sai PRETO. No bloco interno o nó
  de saída é `MediaOut1 = MediaOut` (o `ExportFusionComp` o reescreve como `Saver`).
- `TimeCode` → `StyledText` (saída `Time`); `StartOffset` em quadros: o tempo 0 da composição é o
  1º quadro do clipe, então o `StartOffset` = o `Start` do clipe na timeline = TC da timeline.
- Calibração pela imagem (1 caso, quadro 2880×1620, `inferido`): o Premiere desenha os dígitos com
  altura `0,00236 × Size × (Size da linha / 100) × altura do quadro` (Size 17 → 65 px) e a caixa
  preta ancorada pela `Position` no canto INFERIOR ESQUERDO (x 2352, y 123 = 0,8168 / 0,0757),
  folga ~0,12 × altura à esquerda e ~0,28 × altura embaixo. O Open Sans Semibold do Text+ tem a
  mesma proporção nos dígitos do TC (7,23 × 7,20 largura/altura); Size 0,1 = dígitos de 124 px
  (o Text+ centra pela caixa dos dígitos). Caixa = elemento 4 (Level 0 = o texto inteiro); o
  Extend escala com o Size: 0,1 de Extend = 0,234 × a altura dos dígitos.
"""
from __future__ import annotations

import struct
import zlib

#: altura dos dígitos do Premiere = K_PREMIERE × Size × altura do quadro (Size da linha 100)
K_PREMIERE = 65 / (17 * 1620)
#: altura dos dígitos do Text+ = K_TEXTPLUS × Size × altura do quadro
K_TEXTPLUS = 124 / (0.1 * 1620)
#: TC (11 caracteres) no Open Sans Semibold: largura = 7,2 × altura dos dígitos
LARGURA_TC = 7.2
#: folgas da caixa do Premiere, em alturas de dígito (medidas na referência). O `FOLGA_BAIXO` já
#: desconta o 1 px que o Text+ desenha acima da conta (sobre o PRODB, a 1ª versão saiu 2 px alta).
FOLGA_ESQ, FOLGA_BAIXO = 0.117, 0.246
#: Extend da caixa do Text+ que dá as folgas do Premiere (horizontal; vertical pela borda de baixo)
EXTEND_H, EXTEND_V = -0.147, -0.043

_FORMA = """<Sm2TiVideoClip DbId="00000000-0000-0000-0000-000000000000">
       <FieldsBlob>000000020000002a800a150a112205546578742b4a05546578742ba80100200112100000000000000006ffffffffffffffff</FieldsBlob>
       <PrettyType>Fusion Title</PrettyType>
       <Name>Fusion Title</Name>
       <Start>0</Start>
       <Duration>1</Duration>
       <LinkedItemSync/>
       <WasDisbanded>false</WasDisbanded>
       <MarkersBA/>
       <UiMemento>0</UiMemento>
       <Flags>0</Flags>
       <PriorityIndex>0</PriorityIndex>
       <EffectFiltersBA/>
       <ImportExportMetadataBA/>
       <RenderTextEnabled>true</RenderTextEnabled>
       <RenderTextGanged>true</RenderTextGanged>
       <RenderTextPrefixed>true</RenderTextPrefixed>
       <CompositionTable>
        <Sm2TiCompositionTable DbId="00000000-0000-0000-0000-000000000001">
         <FieldsBlob>000000010000000200000016004c006100730074004d006f006400540069006d00650000000400000000033161a1ca0000002c0046007500730069006f006e00530074006100720074004600720061006d0065004f00660066007300650074000000020000000000</FieldsBlob>
         <DbSavedTime>0</DbSavedTime>
         <CompositionBA></CompositionBA>
         <ActiveCompositionIdx>0</ActiveCompositionIdx>
        </Sm2TiCompositionTable>
       </CompositionTable>
       <In/>
       <MixedFrameRateAlignment>0</MixedFrameRateAlignment>
       <MediaStartTime>0</MediaStartTime>
       <MediaFilePath/>
       <MediaReelNumber/>
       <MediaFrameRate></MediaFrameRate>
       <MediaTimemapBA></MediaTimemapBA>
       <LastChangedTime>0</LastChangedTime>
       <LastRenderedTime>0</LastRenderedTime>
       <IsMarkedForCaching>false</IsMarkedForCaching>
       <IsForceConformed>true</IsForceConformed>
       <MatchConflictState>0</MatchConflictState>
       <UseOppositeSrcForLeftEye>false</UseOppositeSrcForLeftEye>
       <UseOppositeSrcForRightEye>false</UseOppositeSrcForRightEye>
       <RenderCacheBA/>
       <CurrentSelectorIdx>0</CurrentSelectorIdx>
       <IsPreConformed>false</IsPreConformed>
       <PreConformMediaExtents>00000100000030c20000010000003042</PreConformMediaExtents>
       <MediaMetadata/>
       <Thumbnail>
        <BtThumnail DbId="00000000-0000-0000-0000-000000000002">
         <FieldsBlob/>
         <ImgWidth>-1</ImgWidth>
         <ImgHeight>-1</ImgHeight>
         <Buffer/>
        </BtThumnail>
       </Thumbnail>
       <ThumbnailDirtyFlag>true</ThumbnailDirtyFlag>
      </Sm2TiVideoClip>"""

_CABECALHO = (
    'Composition {{ CurrentTime = 0, RenderRange = {{ 0, {fim} }}, GlobalRange = {{ 0, {fim} }}, '
    'CurrentID = 4, HiQ = true, PlaybackUpdateMode = 0, StereoMode = false, '
    'Version = "DaVinci Resolve Studio 21.1.0.0014", SavedOutputs = 0, HeldTools = 0, DisabledTools = 0, '
    'LockedTools = 0, AudioOffset = 0, Resumable = true, OutputClips = {{ }}, '
    'CustomData = {{ TEMPLATE_ID = "Text+" }}, Frames = {{ }}, Prefs = {{ Comp = {{ FrameFormat = {{ '
    'Width = {w}, Height = {h}, Rate = {fps}, }}, Unsorted = {{ GlobalEnd = {fim} }}, }} }}, '
    'Compressed = true, }}')


def _n(x: float) -> str:
    t = f"{float(x):.6f}".rstrip("0").rstrip(".")
    return "0" if t in ("-0", "") else t


def _u32(n: int) -> bytes:
    return struct.pack(">I", n)


def _chave(k: str) -> bytes:
    kb = k.encode("utf-16-be")
    return _u32(len(kb)) + kb


def composicao_ba(cabecalho: str, tools: str, nome: str = "Composition 1") -> str:
    """O `CompositionBA` (hex) de uma composição: o mapa do Resolve com o `0_data` comprimido."""
    t = tools.encode("utf-8") + b"\x00"
    dados = cabecalho.encode("utf-8") + b"\x00" + struct.pack("<I", len(t)) + zlib.compress(t, 9)
    nb = nome.encode("utf-16-be")
    corpo = (_u32(1) + _u32(4)
             + _chave("count") + _u32(2) + b"\x00" + _u32(1)
             + _chave("0_name") + _u32(10) + b"\x00" + _u32(len(nb)) + nb
             + _chave("0_mediaIdList") + _u32(11) + b"\x00" + _u32(0)
             + _chave("0_data") + _u32(12) + b"\x00" + _u32(len(dados)) + dados)
    return (_u32(len(corpo)) + zlib.compress(corpo, 9)).hex()


def tools_tc(*, size: float, centro: tuple[float, float], inicio: int, fps: float, fim: int,
             quadro: tuple[int, int], fundo_opacidade: float, drop: bool = False) -> str:
    """O bloco `Tools` de um Text+ com o TC (modificador TimeCode) e a caixa preta de fundo."""
    w, h = quadro
    fundo = ""
    if fundo_opacidade > 0:
        fundo = (f"Enabled4 = Input {{ Value = 1, }}, ElementShape4 = Input {{ Value = 2, }}, "
                 f"Level4 = Input {{ Value = 0, }}, ExtendHorizontal4 = Input {{ Value = {_n(EXTEND_H)}, }}, "
                 f"ExtendVertical4 = Input {{ Value = {_n(EXTEND_V)}, }}, Red4 = Input {{ Value = 0, }}, "
                 f"Green4 = Input {{ Value = 0, }}, Blue4 = Input {{ Value = 0, }}, "
                 f"Opacity4 = Input {{ Value = {_n(fundo_opacidade)}, }}, Softness4 = Input {{ Value = 0, }}, ")
    return ("{ Template = TextPlus { Inputs = { "
            f"GlobalOut = Input {{ Value = {fim}, }}, Width = Input {{ Value = {w}, }}, "
            f"Height = Input {{ Value = {h}, }}, UseFrameFormatSettings = Input {{ Value = 1, }}, "
            'StyledText = Input { SourceOp = "TimeCode1", Source = "Time", }, '
            'Font = Input { Value = "Open Sans", }, Style = Input { Value = "Semibold", }, '
            f"Size = Input {{ Value = {_n(size)}, }}, "
            f"Center = Input {{ Value = {{ {_n(centro[0])}, {_n(centro[1])} }}, }}, {fundo}"
            "VerticalJustificationNew = Input { Value = 3, }, HorizontalJustificationNew = Input { Value = 3, } }, "
            "ViewInfo = OperatorInfo { Pos = { 220, 49.5 } }, Version = 1 }, "
            "TimeCode1 = TimeCode { CtrlWZoom = false, Inputs = { "
            f"StartOffset = Input {{ Value = {int(inicio)}, }}, FramesPerSecond = Input {{ Value = {_n(fps)}, }}, "
            f"DropFrame = Input {{ Value = {1 if drop else 0}, }}, }}, }}, "
            'MediaOut1 = MediaOut { Inputs = { Index = Input { Value = "0", }, '
            'Input = Input { SourceOp = "Template", Source = "Output", } }, '
            "ViewInfo = OperatorInfo { Pos = { 440, 49.5 } }, } }")


def geometria(posicao: tuple[float, float], size: float, size_linha: float,
              quadro: tuple[int, int]) -> tuple[float, tuple[float, float]]:
    """(Size do Text+, Center do Text+) de uma linha de TC do burn-in do Premiere.
    `posicao` = a Position da linha (fração do quadro, Y para baixo: o canto inferior esquerdo da
    caixa); `size` = o Size do efeito; `size_linha` = o Size da linha (%)."""
    w, h = quadro
    digito = K_PREMIERE * size * (size_linha / 100.0) * h
    cx = posicao[0] + (FOLGA_ESQ + LARGURA_TC / 2) * digito / w
    cy = 1.0 - posicao[1] + (FOLGA_BAIXO + 0.5) * digito / h          # Fusion: Y para cima
    return digito / (K_TEXTPLUS * h), (cx, cy)


def clipe_tc(*, start: int, duracao: int, fps: float, quadro: tuple[int, int],
             posicao: tuple[float, float], size: float, size_linha: float,
             opacidade_fundo: float, drop: bool = False, nome: str = "Burn-in TC") -> str:
    """O `Sm2TiVideoClip` (sem DbIds próprios: o writer os troca) de um Text+ com o TC da
    timeline. `start` = o `Start` do clipe na timeline (é também o TC do 1º quadro)."""
    tam, centro = geometria(posicao, size, size_linha, quadro)
    fim = max(0, int(duracao) - 1)
    w, h = quadro
    cab = _CABECALHO.format(fim=fim, w=w, h=h, fps=_n(fps))
    tools = tools_tc(size=tam, centro=centro, inicio=start, fps=fps, fim=fim, quadro=quadro,
                     fundo_opacidade=opacidade_fundo, drop=drop)
    b = _FORMA
    b = b.replace("<Name>Fusion Title</Name>", f"<Name>{nome}</Name>")
    b = b.replace("<Start>0</Start>", f"<Start>{int(start)}</Start>")
    b = b.replace("<Duration>1</Duration>", f"<Duration>{int(duracao)}</Duration>")
    b = b.replace("<CompositionBA></CompositionBA>", f"<CompositionBA>{composicao_ba(cab, tools)}</CompositionBA>")
    b = b.replace("<MediaFrameRate></MediaFrameRate>",
                  f"<MediaFrameRate>{(struct.pack('<d', float(fps)) + bytes(8)).hex()}</MediaFrameRate>")
    # a extensão do título: (duração − 1) / fps, como no gabarito (119 quadros a 24 → 4,9583 s)
    b = b.replace("<MediaTimemapBA></MediaTimemapBA>",
                  f"<MediaTimemapBA>02{struct.pack('>d', fim / float(fps)).hex()}</MediaTimemapBA>")
    return b


def ler_composicao(ba_hex: str) -> tuple[str, str]:
    """(cabeçalho, Tools) de um `CompositionBA` — para os testes e para inspecionar gabaritos."""
    corpo = zlib.decompress(bytes.fromhex(ba_hex)[4:])
    i = corpo.find(b"Composition {")
    dados = corpo[i:]
    j = dados.find(b"\x00")
    tools = zlib.decompress(dados[j + 5:]).rstrip(b"\x00")
    return dados[:j].decode("utf-8"), tools.decode("utf-8")
