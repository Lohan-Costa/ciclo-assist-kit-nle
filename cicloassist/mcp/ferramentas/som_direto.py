"""`montar_som_direto`: a operação 6 do ensaio — o som do gravador vira masters numa bin nova do MC.

Motor: `cicloassist/avid/som_direto.py` (o `autorar_masters` do De Lá Pra Cá). Aqui: a
conferência antes do cartão e a permissão de ler a pasta (arrastada, ou a saída do laboratório).
"""

from __future__ import annotations

from pathlib import Path

from ... import laboratorio as _lab
from ...avid import som_direto as _som
from ...avid.mcapi import McApiErro, MediaComposer
from ...servico import arrastados as _arrastados
from ...servico import turno as _turno
from ..registro import ferramenta


def _conferir(pasta: str = "", bin: str = "", **_) -> str:
    p = Path(pasta)
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance. Peça ao editor para arrastá-la para o chat."
    if not (_arrastados.autorizado(p) or _lab.na_saida(p)):
        return _arrastados.recusa(p)
    if not _som.audios_da_pasta(p):
        return f"Não há áudio (.wav/.aif) em {p} (pastas que começam com _ ficam de fora)."
    if not bin.strip() or any(c in bin for c in '\\/:*?"<>|'):
        return "Diga o nome da bin NOVA (sem barra nem caracteres de arquivo)."
    if _som.raiz_do_dlpc() is None:
        return "O De Lá Pra Cá não está nesta máquina — é ele quem monta o som direto."
    try:
        with MediaComposer() as m:
            if m.info().get("ocupado"):
                return "O Media Composer está ocupado — provavelmente há um diálogo na tela dele."
            caminho = m.projeto(recarregar=True).get("caminho")
            if not caminho:
                return "O Media Composer não está com um projeto aberto."
            if (Path(caminho) / f"{bin.strip()}.avb").exists():
                return f"Já existe a bin '{bin.strip()}' no projeto. Esta operação só cria bin nova: use outro nome."
    except McApiErro as e:
        return f"O Media Composer não respondeu: {e}"
    return ""


@ferramenta(
    nome="montar_som_direto",
    descricao=(
        "Põe o SOM DIRETO (os WAV do gravador) no Media Composer como masters de áudio numa bin "
        "NOVA do projeto aberto, na taxa do projeto — sem o diálogo de início de áudio que o link "
        "abre a cada arquivo. Os masters apontam para CÓPIAS dos WAV (na subpasta _para_consolidar); "
        "o passo seguinte do fluxo é consolidar. A pasta é a que o editor arrastou."
    ),
    esquema={
        "type": "object",
        "properties": {
            "pasta": {"type": "string", "description": "A pasta dos WAV (subpastas entram; as que começam com _ não)."},
            "bin": {"type": "string", "description": "O nome da bin NOVA."},
        },
        "required": ["pasta", "bin"],
    },
    escreve=True,
    conferir=_conferir,
)
def montar_som_direto(pasta: str = "", bin: str = "") -> dict[str, object]:
    try:
        with MediaComposer() as m:
            r = _som.montar(m, pasta, bin.strip(), relatar=_turno.avisar)
    except _som.SomDiretoFalhou as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer recusou: {e}"}
    avisos = f" ⚠️ {'; '.join(r['avisos'])}" if r["avisos"] else ""
    return {**r, "manchete": f"{len(r['masters'])} master(s) de som na bin {r['bin']} a {r['fps']:g} fps.{avisos}"}


# ── as operações 6 e 7 em uma: o som direto já como mídia GERENCIADA (sem consolidar) ─────────────────────────

from ...avid import importar_opatom as _imp  # noqa: E402
from ...avid import som_gerenciado as _ger  # noqa: E402
from .opatom import _mxf_de  # noqa: E402


def _previa(pasta: str = "", **_) -> str:
    p = Path(pasta)
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance."
    return "" if _som.audios_da_pasta(p) else f"Não há áudio (.wav/.aif) em {p} (pastas que começam com _ ficam de fora)."


def _conferir_gerenciado(pasta: str = "", bin: str = "", **_) -> str:
    p = Path(pasta)
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance. Peça ao editor para arrastá-la para o chat."
    if not (_arrastados.autorizado(p) or _lab.na_saida(p)):
        return _arrastados.recusa(p)
    if not _som.audios_da_pasta(p):
        return f"Não há áudio (.wav/.aif) em {p} (pastas que começam com _ ficam de fora)."
    if not bin.strip() or any(c in bin for c in '\\/:*?"<>|'):
        return "Diga o nome da bin (sem barra nem caracteres de arquivo)."
    if _mxf_de(p) is None:
        return "Não achei nenhuma pasta 'Avid MediaFiles' nos discos desta máquina."
    try:
        with MediaComposer() as m:
            if m.info().get("ocupado"):
                return "O Media Composer está ocupado — provavelmente há um diálogo na tela dele."
            pr = m.projeto(recarregar=True)
            if not pr.get("caminho"):
                return "O Media Composer não está com um projeto aberto."
            if pr.get("drop_frame"):
                return ("O projeto é drop-frame: este caminho ainda não foi medido com DF. Use montar_som_direto "
                        "e consolide no Media Composer.")
    except McApiErro as e:
        return f"O Media Composer não respondeu: {e}"
    return ""


@ferramenta(
    nome="som_direto_gerenciado",
    descricao=(
        "Põe o SOM DIRETO (os WAV do gravador) no Media Composer já como mídia GERENCIADA (MXF OP-Atom), sem "
        "consolidar: gera um MXF por canal com o timecode do gravador, grava numa pasta NOVA de "
        "'Avid MediaFiles\\MXF' (só dígitos, terminando em 1) e importa os masters na bin (que é criada se não "
        "existir), com o Tape = o nome do WAV. Confere pela API que ficaram online. Prefira esta a "
        "montar_som_direto quando o fluxo pede o som consolidado. A pasta é a que o editor arrastou."
    ),
    esquema={
        "type": "object",
        "properties": {
            "pasta": {"type": "string", "description": "A pasta dos WAV (subpastas entram; as que começam com _ não)."},
            "bin": {"type": "string", "description": "O nome da bin de destino."},
        },
        "required": ["pasta", "bin"],
    },
    escreve=True,
    conferir=_conferir_gerenciado,
    previa=_previa,
)
def som_direto_gerenciado(pasta: str = "", bin: str = "") -> dict[str, object]:
    try:
        with MediaComposer() as m:
            r = _ger.montar(m, pasta, bin.strip(), _mxf_de(Path(pasta)), relatar=_turno.avisar)
    except (_ger.SomGerenciadoFalhou, _imp.ImportacaoFalhou) as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer recusou: {e}"}
    return {**r, "manchete": f"{len(r['masters'])} master(s) de som GERENCIADOS e online na bin {r['bin']} "
                             f"({r['mxf']} MXF em {r['pasta']}), sem consolidar"}
