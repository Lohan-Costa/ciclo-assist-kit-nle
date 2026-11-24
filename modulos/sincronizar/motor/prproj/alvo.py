"""O `.prproj` para um Premiere mais VELHO — hoje, o 2023 (23.x).

O builder escreve o formato do 25.6.5 (`Project Version=43`). O Premiere recusa
versão de formato maior que a dele, e o 23.2 só aceita até 41 — decisão do autor em
2026-09-16: *"é um ponto importante ele funcionar na versão 2023"*.

## De onde saiu cada regra

De uma comparação classe a classe entre um projeto salvo pelo **23.2** (com bins,
merged clips nativos, multicam e sequência) e um export do builder. Detalhe e tabela
no banco de NLEs, `protocolos/prproj/escrita.md` §11b.

- 10 classes têm versão maior no builder → rebaixadas ao número do 23.2;
- 5 classes carregam campos que o 23.2 nunca escreve (recursos de cor e de render
  mais novos) → removidos;
- `DummyCaptureSettings` é o nome NOVO de uma classe que o 23.2 conhece como
  `CaptureSettings` v10 (mesma ClassID) → trocada pelo bloco que o 23.2 grava.

⚠️ `inferido` até alguém abrir o resultado num 23.2: os campos que o 23.2 escreve e o
builder não (cor de `VideoStream`, `TimeDisplay`…) ficam ausentes, na aposta de que o
Premiere preenche o padrão — é o que o 25 já faz com os arquivos do builder.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET

ALVOS = ("25", "2023")

#: classe → versão que o 23.2 grava.
_VERSOES_2023 = {
    "Project": "41",
    "ProjectSettings": "18",
    "Media": "27",
    "VideoStream": "19",
    "MasterClip": "11",
    "ClipLoggingInfo": "8",
    "IngestSettings": "1",
    "SubClip": "5",
    "VideoClipTrackItem": "6",
    "AudioClipTrackItem": "6",
}

#: classe → campos-filho que o 23.2 não escreve.
_CAMPOS_NOVOS = {
    "ProjectSettings": ("ColorAwareEffectsEnabled",),
    "VideoStream": ("OriginalColorSpace",),
    "VideoClipTrackItem": ("ToneMapSettings",),
    "AudioClipTrackItem": ("PreRenderComponentChainHashVersion",),
    "VideoTrackGroup": ("AutoInputGamutCompressionEnabled",
                        "IsColorAwareEffectsEnabledSameAsProject",
                        "IsGraphicsWhiteSameAsProject", "OutputColorSpace",
                        "ToneMappingDesaturation"),
}

#: O `CaptureSettings` que o 23.2 grava num projeto novo (copiado do projeto medido).
_CAPTURA_2023 = (
    ("RecordModuleDisplayName", "DV"),
    ("SupportedFileExtension", "avi"),
    ("RecorderID", "0ae2b9b7-6efc-424f-aadf-1a2dedd5e8ff"),
    ("VideoFrameRate", "8475667200"),
    ("VideoFrameSize", "0,0,720,480"),
    ("VideoCompressorFourCC", "0"),
    ("AudioCompressorFourCC", "1380013856"),
    ("AudioCompressorDisplayName", "Uncompressed"),
    ("AudioFrameRate", "7938000"),
    ("AudioSampleType", "3"),
    ("AudioChannelType", "1"),
    ("AbortCaptureOnDroppedFrames", "false"),
)

_CABECALHO = '<?xml version="1.0" encoding="UTF-8"?>'


def adaptar(xml: str, alvo: str) -> str:
    """O XML do builder, reescrito para o Premiere `alvo`. `"25"` devolve intacto."""
    if alvo not in ALVOS:
        raise ValueError(f"alvo de Premiere desconhecido: {alvo!r}")
    if alvo == "25":
        return xml
    corpo = xml[len(_CABECALHO):] if xml.startswith(_CABECALHO) else xml
    raiz = ET.fromstring(corpo)
    for i, obj in enumerate(list(raiz)):
        if obj.tag == "DummyCaptureSettings":
            novo = ET.Element("CaptureSettings", {
                "ObjectID": obj.get("ObjectID"), "ClassID": obj.get("ClassID"),
                "Version": "10"})
            for tag, valor in _CAPTURA_2023:
                ET.SubElement(novo, tag).text = valor
            raiz.remove(obj)
            raiz.insert(i, novo)
            continue
        if obj.tag in _VERSOES_2023:
            obj.set("Version", _VERSOES_2023[obj.tag])
        for tag in _CAMPOS_NOVOS.get(obj.tag, ()):
            for filho in obj.findall(tag):
                obj.remove(filho)
    return _CABECALHO + ET.tostring(raiz, encoding="unicode")
