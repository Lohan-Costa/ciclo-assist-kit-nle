"""`converter_para_proxy`: a P1 da diária no Premiere — vídeo → ProRes Proxy 1080 pelo Resolve Studio.

Motor: `cicloassist/resolve_proxy.py`. Aqui ficam a conferência ANTES do cartão e as duas permissões:

- ⛔ **A pasta lida é a que o editor ARRASTOU** (ADR 0005), ou a saída do laboratório da família.
- ⛔ **O destino é o que o editor DISSE** (decisão do autor, 2026-11-07: "perguntar no pedido"). Sem padrão:
  sem destino a conferência manda perguntar, e o cartão mostra a pasta antes de qualquer arquivo ser escrito.
"""

from __future__ import annotations

from pathlib import Path

from ... import laboratorio as _lab
from ... import resolve as _resolve
from ... import resolve_proxy as _px
from ...servico import arrastados as _arrastados
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta


def _conferir(projeto: str = "", pasta: str = "", destino: str = "", **_) -> str:
    if not projeto.strip():
        return "Diga o nome do projeto do Resolve onde converter (o editor disse, ou o nome da diária)."
    p = Path(pasta)
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance. Peça ao editor para arrastá-la para o chat."
    if not (_arrastados.autorizado(p) or _lab.na_saida(p)):
        return _arrastados.recusa(p)
    if not destino.strip():
        return ("Falta o destino: pergunte ao editor em que pasta gravar os proxies (não há pasta padrão — "
                "é ele quem escolhe, a cada pedido).")
    d = Path(destino)
    if not d.is_absolute():
        return f"O destino '{destino}' precisa ser o caminho inteiro da pasta."
    videos = _px.videos_da_pasta(p)
    motivo, _ = _px.conferir_videos(videos)
    if motivo:
        return f"Não dá para converter: {motivo}."
    motivo = _px.conferir_destino(d, videos)
    if motivo:
        return f"Não dá para gravar ali: {motivo}."
    if not _resolve.servidor_no_ar():
        return ("O DaVinci Resolve não está aberto. Se o editor nomeou o Resolve no pedido, chame "
                "abrir_programa antes; senão pergunte a ele.")
    return ""


@ferramenta(
    nome="converter_para_proxy",
    descricao=(
        "Gera um PROXY ProRes Proxy 1080 de cada vídeo de uma pasta pelo DaVinci Resolve Studio (que tem de "
        "estar aberto), para editar no Premiere. Cada proxy tem o nome, o timecode, os quadros e os canais de "
        "som do original — e cada par é CONFERIDO; o que não bate vem em problemas. Lê também RAW (BRAW, R3D). "
        "A pasta é a que o editor arrastou (subpastas entram; as que começam com _ não). O DESTINO é o editor "
        "quem diz: se ele não disse, PERGUNTE antes de chamar. Não mexe na fila de render nem nas timelines do "
        "editor: cria timelines novas 'PROXY …'. Depois, a mídia vai ao Premiere de um de dois jeitos — o "
        "proxy como mídia original, ou a alta com o proxy anexado: pergunte ao editor qual."
    ),
    esquema={
        "type": "object",
        "properties": {
            "projeto": {"type": "string", "description": "O projeto do Resolve (abre, ou cria)."},
            "pasta": {"type": "string", "description": "A pasta dos vídeos (a que o editor arrastou)."},
            "destino": {"type": "string",
                        "description": "A pasta onde gravar os proxies, como o editor disse (caminho inteiro)."},
        },
        "required": ["projeto", "pasta", "destino"],
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
)
def converter_para_proxy(projeto: str = "", pasta: str = "", destino: str = "") -> dict[str, object]:
    try:
        r = _px.converter(projeto.strip(), _px.videos_da_pasta(Path(pasta)), Path(destino), relatar=_turno.avisar)
    except _px.ConversaoFalhou as e:
        return {"erro": str(e)}
    # ⭐ O editor aprovou gravar ali no cartão: a pasta passa a ser legível para o importar_no_premiere.
    _arrastados.autorizar(r["pasta"])
    tamanhos = ", ".join(f"{g['clipes']} em {g['tamanho']}" for g in r["grupos"])
    manchete = (f"{r['proxies']} de {len(r['pares'])} proxy(s) ProRes Proxy conferidos ({tamanhos}, "
                f"{r['taxa']} fps) em {r['pasta']}, {r['segundos']} s de render")
    if r["problemas"]:
        manchete += " — ⚠️ " + "; ".join(r["problemas"][:3])
    return {**r, "manchete": manchete,
            "proximo_passo": ("Levar ao Premiere — como mídia ORIGINAL (o proxy) ou a ALTA com o proxy anexado: "
                              "pergunte ao editor qual. Proxy com problema não deve ser anexado.")}
