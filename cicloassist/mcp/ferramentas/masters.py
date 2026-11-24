"""`importar_masters_opatom`: a operação 5 do ensaio — MXF feito fora vira master online numa bin.

Motor: `cicloassist/avid/importar_opatom.py` (as duas travas que derrubaram o MC em 31/10).
Aqui: a conferência antes do cartão e o que volta ao modelo.
"""

from __future__ import annotations

from ...avid import importar_opatom as _imp
from ...avid.mcapi import McApiErro, MediaComposer
from ...servico import turno as _turno
from ..registro import ferramenta


def _conferir(pasta: str = "", bin: str = "", **_) -> str:
    motivo = _imp.pasta_valida(pasta)
    if motivo:
        return (f"Não dá para importar: {motivo}. A pasta é a que converter_para_opatom devolveu "
                "(uma diária de 'Avid MediaFiles\\MXF' com nome só de dígitos).")
    if not bin.strip() or any(c in bin for c in '\\/:*?"<>|'):
        return "Diga o nome da bin de destino (sem barra nem caracteres de arquivo)."
    try:
        with MediaComposer() as m:
            if m.info().get("ocupado"):
                return ("O Media Composer está ocupado — provavelmente há um diálogo aberto na tela "
                        "dele. Peça ao editor para fechá-lo.")
            if not m.projeto(recarregar=True).get("caminho"):
                return "O Media Composer não está com um projeto aberto."
    except McApiErro as e:
        return f"O Media Composer não respondeu: {e}"
    return ""


@ferramenta(
    nome="importar_masters_opatom",
    descricao=(
        "Importa no Media Composer, como MASTERS online numa bin, os MXF OP-Atom de uma pasta de "
        "'Avid MediaFiles\\MXF' (a que converter_para_opatom devolveu). Se o MC ainda não indexou "
        "a pasta, põe o MC em foco e espera (é o que o faz indexar); importar antes disso "
        "derrubaria o MC. Cria a bin se não existir. tape = o rolo (reel name); sem ele, o nome "
        "do clipe. Confere depois que nenhum master ficou sem offsets."
    ),
    esquema={
        "type": "object",
        "properties": {
            "pasta": {"type": "string", "description": "A pasta dos MXF (…\\Avid MediaFiles\\MXF\\<dígitos>)."},
            "bin": {"type": "string", "description": "O nome da bin de destino, na raiz do projeto."},
            "tape": {"type": "string", "description": "O rolo (reel name). Vazio = o nome de cada clipe."},
        },
        "required": ["pasta", "bin"],
    },
    escreve=True,
    conferir=_conferir,
)
def importar_masters_opatom(pasta: str = "", bin: str = "", tape: str = "") -> dict[str, object]:
    try:
        with MediaComposer() as m:
            r = _imp.importar(m, pasta, bin.strip(), tape=tape.strip(), relatar=_turno.avisar)
    except _imp.ImportacaoFalhou as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer recusou: {e}"}
    idx = f", indexada em {r['indexar_s']} s" if r["indexar_s"] else ""
    return {**r, "manchete": f"{len(r['masters'])} master(s) na bin {r['bin']} ({r['mxf']} MXF{idx})"}
