"""
Sequências de imagem (1 arquivo = 1 frame): detecção do padrão de numeração e
resolução "frame N → arquivo certo da sequência".

EXR/DPX/CinemaDNG/ARRIRAW costumam vir como `shot.0001.exr`, `shot.0002.exr`… Cada
arquivo é UM frame. O indexer agrupa os irmãos num único entry com um dict `sequence`
(ver media/indexer.py::_group_sequences); o extractor usa `resolve_frame_file` para
descobrir qual arquivo decodificar para o frame pedido.
"""

import re
from pathlib import Path

# nome = <base><sep><dígitos>, sep ∈ {'', '.', '_', '-'}. Captura a numeração FINAL.
_SEQ_RE = re.compile(r"^(?P<base>.*?)(?P<sep>[._-]?)(?P<num>\d+)$")


def parse_sequence_name(stem: str):
    """'shot_0001' → (base='shot', sep='_', num='0001', pad=4). None se não termina em dígitos."""
    m = _SEQ_RE.match(stem)
    if not m or not m.group("num"):
        return None
    return m.group("base"), m.group("sep"), m.group("num"), len(m.group("num"))


def resolve_frame_file(sequence: dict, frame_index: int) -> str:
    """Caminho do arquivo da sequência p/ `frame_index` (0-based a partir do 1º frame).

    O número do arquivo = sequence['first'] + frame_index, zero-pad em `pad` dígitos.
    Clampa ao range conhecido [first, last] (frames fora caem na borda — evita pedir
    arquivo inexistente ao navegar além da sequência).
    """
    n = int(sequence["first"]) + max(0, int(frame_index))
    last = int(sequence.get("last", n))
    n = min(n, last)
    name = f"{sequence['base']}{sequence['sep']}{n:0{int(sequence['pad'])}d}{sequence['ext']}"
    return str(Path(sequence["dir"]) / name)
