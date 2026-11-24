"""As ferramentas MCP. Importar este pacote é o que as registra.

⚠️ O registro acontece por efeito colateral de import. Ferramenta em módulo que ninguém
importa simplesmente não existe, sem erro — por isso a lista abaixo é explícita e não um
varrer de diretório: um `import *` mágico esconde exatamente esse tipo de ausência.
"""

from . import arquivos  # noqa: F401
from . import avid  # noqa: F401
from . import conformar  # noqa: F401
from . import corte  # noqa: F401
from . import edicao  # noqa: F401
from . import fala  # noqa: F401
from . import fluxo  # noqa: F401
from . import glossario  # noqa: F401
from . import laboratorio  # noqa: F401
from . import falas  # noqa: F401
from . import mapa  # noqa: F401
from . import merged  # noqa: F401
from . import masters  # noqa: F401
from . import metadado  # noqa: F401
from . import metodo  # noqa: F401
from . import midia  # noqa: F401
from . import sincronizar  # noqa: F401
from . import organizar_mc  # noqa: F401
from . import monitor  # noqa: F401
from . import opatom  # noqa: F401
from . import proxy  # noqa: F401
from . import diaria_premiere  # noqa: F401
from . import oficina  # noqa: F401
from . import parecidos  # noqa: F401
from . import portao  # noqa: F401
from . import programas  # noqa: F401
from . import premiere  # noqa: F401
from . import roteiro  # noqa: F401
from . import salvar  # noqa: F401
from . import som_direto  # noqa: F401
from . import trama  # noqa: F401
from . import visual  # noqa: F401

__all__ = ["arquivos", "avid", "conformar", "corte", "edicao", "fala", "falas", "fluxo", "glossario", "laboratorio", "mapa", "merged", "masters", "metadado", "metodo", "midia",
           "monitor", "organizar_mc", "parecidos", "portao", "premiere", "programas", "roteiro", "salvar", "sincronizar", "som_direto", "trama", "visual"]
