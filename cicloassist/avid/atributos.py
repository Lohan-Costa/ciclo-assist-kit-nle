"""O que o Media Composer do Mac guarda FORA dos bytes da bin, e que regravar apagava.

⚠️ MEDIDO em 2026-09-14, nas 199 bins reais gravadas pelo MC do Mac (25.12, 25.6, 26.8):
toda `.avb` leva dois atributos estendidos —

- `BINSTATE_RSRC` (57–76 KB, cabeçalho `AObjDoc`): colunas e formatos da bin;
- `com.apple.FinderInfo`: tipo e criador `ATob`/`ATve`.

O `os.replace` do arquivo novo por cima do velho os apaga (APFS e exFAT — no exFAT some o
`._X.avb` junto), e o `shutil.copy2` do Python no macOS NÃO os copia: a promessa "a bin
volta byte a byte" valia para os bytes e não para esse estado.

⚠️ NÃO MEDIDO: o efeito no MC. O provável é a bin reabrir com vista e colunas padrão — bin
sem os atributos abre (banco, `protocolos/avb/escrita.md`). O custo é o layout do editor.

⇒ Copiar os atributos da original para quem vai ocupar o lugar dela, pelo `copyfile(3)` do
sistema (é ele que o Finder usa, e ele sabe gravar no `._` de disco que não é Apple).
Fora do macOS não há o que fazer: no Windows o estado da bin não mora em atributo.
"""

from __future__ import annotations

import ctypes
import logging
import shutil
import sys
from pathlib import Path

log = logging.getLogger("cicloassist.avid.atributos")

#: `copyfile.h`: só os atributos estendidos, sem tocar nos dados do destino.
COPYFILE_XATTR = 1 << 2


def copiar_atributos(de: Path | str, para: Path | str) -> bool:
    """Leva os atributos estendidos de `de` para `para`. Devolve se copiou.

    ⚠️ Falhar aqui NUNCA derruba a escrita da bin: perder a vista é ruim, perder a
    sequência do editor por causa dela seria pior. Fica o aviso no log.
    """
    if sys.platform != "darwin":
        return False
    try:
        libc = ctypes.CDLL("/usr/lib/libSystem.B.dylib", use_errno=True)
        libc.copyfile.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_void_p,
                                  ctypes.c_uint32]
        libc.copyfile.restype = ctypes.c_int
        rc = libc.copyfile(str(de).encode("utf-8"), str(para).encode("utf-8"), None,
                           COPYFILE_XATTR)
    except (OSError, AttributeError) as e:
        log.warning("não consegui copiar os atributos de %s: %s", de, e)
        return False
    if rc != 0:
        log.warning("não consegui copiar os atributos de %s (errno %d)", de, ctypes.get_errno())
        return False
    return True


def copiar_bin(de: Path | str, para: Path | str) -> None:
    """`shutil.copy2` que leva também o estado da bin no Mac. Ver o módulo."""
    shutil.copy2(de, para)
    copiar_atributos(de, para)
