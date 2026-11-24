"""Cliente do Media Composer.

`mcapi.py` fala gRPC com o backend `mcapi.MCAPI` em `[::1]:9100`. `masters.py` acha o
arquivo MXF de um master já importado, casando `material_package_umid` na Avid MediaFiles.

Veio do Órbita (DRAMASYNC), sem o `adapter.py`/`writer.py` — aqueles dependem de
`sync.model.Daily`, que é do domínio de sincronização e não existe aqui. Ver VENDOR.md.
"""

from .mcapi import MediaComposer, McApiError, McApiIndisponivel, mob_id_para_pyavb

__all__ = ["MediaComposer", "McApiError", "McApiIndisponivel", "mob_id_para_pyavb"]
