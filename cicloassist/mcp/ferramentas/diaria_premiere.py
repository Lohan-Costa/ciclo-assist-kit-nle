"""`importar_no_premiere`: a P2 da diária no Premiere — o proxy como original, ou a alta com o proxy anexado.

Motor: `cicloassist/nle/premiere/diaria.py` (o plano, a conferência do par) + `cicloImportar` no `host.jsx`.

- ⛔ **O modo é do editor, a cada pedido** (decisão do autor, 2026-11-07): sem `modo`, a conferência manda
  PERGUNTAR — nunca escolher por ele.
- ⛔ **A diária é a pasta que o editor arrastou**; a dos proxies, a que ele aprovou no cartão do
  `converter_para_proxy` (fica autorizada quando a conversão termina) ou outra que ele arrastou.
"""

from __future__ import annotations

from pathlib import Path

from ... import laboratorio as _lab
from ...nle.premiere import diaria as _d
from ...nle.premiere import ponte as _ponte
from ...servico import arrastados as _arrastados
from ..registro import ferramenta


def _alcanca(p: Path) -> bool:
    return _arrastados.autorizado(p) or _lab.na_saida(p)


def _conferir(modo: str = "", diaria: str = "", proxies: str = "", bin: str = "", **_) -> str:
    if not modo:
        return ("Falta o modo, e quem escolhe é o editor. Pergunte: o proxy entra como mídia ORIGINAL "
                "(modo 'original'), ou a ALTA entra com o proxy anexado (modo 'proxy_anexado')?")
    if modo not in _d.MODOS:
        return f"Modo {modo!r} não existe: use 'original' ou 'proxy_anexado'."
    d, p = Path(diaria or "."), Path(proxies or ".")
    if not diaria or not d.is_dir():
        return f"'{diaria}' não é uma pasta que eu alcance. Peça ao editor para arrastar a pasta da diária."
    if not _alcanca(d):
        return _arrastados.recusa(d)
    if not proxies or not p.is_dir():
        return f"'{proxies}' não é a pasta dos proxies (a que converter_para_proxy devolveu)."
    if not _alcanca(p):
        return _arrastados.recusa(p)
    if any(c in (bin or "") for c in '\\:*?"<>|\t\n'):
        return "O nome da bin não pode ter barra invertida nem caracteres de arquivo (use / para bin dentro de bin)."
    if not _ponte.painel_vivo():
        return ("A ponte do Ciclo Assist no Premiere não respondeu (ela sobe sozinha com o Premiere). Peça ao "
                "editor para fechar e abrir o Premiere; se não voltar, ⚙ › Integrações › instalar a ponte.")
    plano = _d.planejar(modo, d, p, bin or d.name)
    if plano["problemas"]:
        return "Não dá para importar:\n- " + "\n- ".join(plano["problemas"][:8])
    return ""


@ferramenta(
    nome="importar_no_premiere",
    descricao=(
        "Importa uma diária no projeto aberto do Premiere, numa bin por subpasta (debaixo de uma bin da diária), "
        "de um de DOIS jeitos — e quem escolhe é o editor, PERGUNTE antes: modo 'original' (o proxy ProRes "
        "entra como a mídia do clipe) ou 'proxy_anexado' (a ALTA entra e o proxy fica anexado — o botão de proxy "
        "do Premiere alterna). Cada par é conferido antes de anexar (TC, quadros, canais, proporção); o que não "
        "confere entra sem proxy e vem em sem_proxy com o motivo. O som direto (WAV) entra sempre como original. "
        "Arquivo que já está no projeto não é importado de novo. diaria = a pasta que o editor arrastou; "
        "proxies = a pasta que converter_para_proxy devolveu."
    ),
    esquema={
        "type": "object",
        "properties": {
            "modo": {"type": "string", "enum": list(_d.MODOS), "description": "O que o editor escolheu."},
            "diaria": {"type": "string", "description": "A pasta da diária (originais e som), a que o editor arrastou."},
            "proxies": {"type": "string", "description": "A pasta dos proxies (a de converter_para_proxy)."},
            "bin": {"type": "string", "description": "A bin da diária no projeto (padrão: o nome da pasta)."},
        },
        "required": ["modo", "diaria", "proxies"],
    },
    escreve=True,
    conferir=_conferir,
    nles=("premiere",),
)
def importar_no_premiere(modo: str = "", diaria: str = "", proxies: str = "", bin: str = "") -> dict[str, object]:
    d = Path(diaria)
    plano = _d.planejar(modo, d, Path(proxies), bin or d.name)
    if plano["problemas"]:
        return {"erro": "; ".join(plano["problemas"])}
    try:
        r = _d.importar(plano)
    except (_ponte.PremiereIndisponivel, ValueError) as e:
        return {"erro": str(e)}
    if r.get("erro"):
        return r
    partes = [f"{r['importados']} importado(s)"]
    if r["ja_estavam"]:
        partes.append(f"{r['ja_estavam']} já estavam no projeto")
    if modo == "proxy_anexado":
        partes.append(f"{r['com_proxy']} com proxy anexado")
        if r["sem_proxy"]:
            partes.append(f"{len(r['sem_proxy'])} SEM proxy (o par não conferiu)")
    if r["falharam"]:
        partes.append(f"{len(r['falharam'])} falharam")
    return {**{k: v for k, v in r.items() if k != "detalhe"},
            "manchete": f"{', '.join(partes)} — bins: {', '.join(r['bins'])}",
            "proximo_passo": "Sincronizar câmeras e som pelo Sincronizar (sincronizar) com estas bins."}
