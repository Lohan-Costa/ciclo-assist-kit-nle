"""`converter_para_opatom`: a operação 3 do ensaio — vídeo → MXF OP-Atom pelo Resolve Studio.

Motor: `cicloassist/resolve_opatom.py` (a dança do preset, a pasta nova, a conferência do que
caiu no disco). Aqui ficam a conferência ANTES do cartão e a permissão de ler a pasta.

⛔ **A pasta é a que o editor ARRASTOU** (ADR 0005), ou a saída do laboratório da família —
que é nossa, e é o que `gerar_midia_de_teste` acabou de devolver no mesmo fluxo.
"""

from __future__ import annotations

from pathlib import Path

from ... import laboratorio as _lab
from ... import resolve as _resolve
from ... import resolve_opatom as _op
from ...midia import acervo as _acervo
from ...servico import arrastados as _arrastados
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta


def _mxf_de(pasta: Path) -> Path | None:
    """A `Avid MediaFiles\\MXF` do volume da pasta; senão a primeira que houver."""
    todas = _acervo.pastas_de_midia()
    mesma = [m for m in todas if m.drive.lower() == pasta.drive.lower()] or todas
    return (mesma[0] / "MXF") if mesma else None


def _conferir(projeto: str = "", pasta: str = "", **_) -> str:
    if not projeto.strip():
        return "Diga o nome do projeto do Resolve onde converter (o editor disse, ou o nome da diária)."
    p = Path(pasta)
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance. Peça ao editor para arrastá-la para o chat."
    if not (_arrastados.autorizado(p) or _lab.na_saida(p)):
        return _arrastados.recusa(p)
    motivo, _ = _op.conferir_videos(_op.videos_da_pasta(p))
    if motivo:
        return f"Não dá para converter: {motivo}."
    if _mxf_de(p) is None:
        return "Não achei nenhuma pasta 'Avid MediaFiles' nos discos desta máquina."
    if not _resolve.servidor_no_ar():
        return ("O DaVinci Resolve não está aberto. Se o editor nomeou o Resolve no pedido, chame "
                "abrir_programa antes; senão pergunte a ele.")
    return ""


def _previa(pasta: str = "", **_) -> str:
    p = Path(pasta)
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance."
    motivo, _videos = _op.conferir_videos(_op.videos_da_pasta(p))
    return f"Não dá para converter: {motivo}." if motivo else ""


@ferramenta(
    nome="converter_para_opatom",
    descricao=(
        "Converte os vídeos de uma pasta em mídia GERENCIADA do Media Composer (MXF OP-Atom, "
        "DNxHD) pelo DaVinci Resolve Studio, que tem de estar aberto. Renderiza cada clipe numa "
        "pasta NOVA de 'Avid MediaFiles\\MXF' (nome só com dígitos, terminando em 0), com o nome "
        "do clipe, e confere o que caiu no disco. Só vídeo: o som direto vai por outro caminho. "
        "A pasta é a que o editor arrastou (subpastas entram; as que começam com _ não). Não mexe na fila de render nem nas timelines do "
        "editor: cria uma timeline nova 'OPATOM …'."
    ),
    esquema={
        "type": "object",
        "properties": {
            "projeto": {"type": "string", "description": "O projeto do Resolve (abre, ou cria)."},
            "pasta": {"type": "string", "description": "A pasta dos vídeos."},
        },
        "required": ["projeto", "pasta"],
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
    previa=_previa,
)
def converter_para_opatom(projeto: str = "", pasta: str = "") -> dict[str, object]:
    p = Path(pasta)
    try:
        r = _op.converter(projeto.strip(), _op.videos_da_pasta(p), _mxf_de(p), relatar=_turno.avisar)
    except _op.ConversaoFalhou as e:
        return {"erro": str(e)}
    ok = not r["problemas"]
    manchete = (f"{r['videos']} clipe(s) em OP-Atom ({r['codec']}, {r['taxa']} fps) + {r['sons']} MXF de som "
                f"em {r['pasta']}, {r['segundos']} s de render")
    return {**r, "manchete": manchete if ok else manchete + " — ⚠️ " + "; ".join(r["problemas"]),
            "proximo_passo": ("Importar no Media Composer como masters (a pasta é nova: o MC a indexa "
                              "ao voltar o foco).")}
