r"""Caminho de arquivo que vem de FORA (o NLE, o `.prproj`, o MCP do Premiere), no formato de comparar.

⛔ O Premiere no Windows devolve caminhos com o prefixo de caminho LONGO (`\\?\D:\…`), e não em todo lugar — medido
em 2026-11-18 (Windows 11, Premiere 26.5.2 e 27.1 Beta): o `ActualMediaFilePath` do `.prproj` tem, o `FilePath` não; o
`path` do projeto no `getOpenProjects` do MCP tem, o `filePath` do `getClipMetadata` não. Comparado como veio, o mesmo
arquivo vira dois. Banco: `transversal/matriz-de-plataforma.md` (linha do prefixo de caminho longo).
"""

from __future__ import annotations


def sem_prefixo_longo(p: str) -> str:
    r"""`\\?\D:\x` → `D:\x`, `\\?\UNC\srv\x` → `\\srv\x`, `\\.\…` → `…`; o resto volta como veio."""
    s = str(p)
    for pre in ("\\\\?\\", "//?/", "\\\\.\\"):
        if s.startswith(pre):
            s = s[len(pre):]
            if s[:4].upper() in ("UNC\\", "UNC/"):
                s = "\\\\" + s[4:]
            break
    return s
