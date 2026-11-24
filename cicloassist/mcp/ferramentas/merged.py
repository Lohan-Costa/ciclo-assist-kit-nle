"""`criar_merged`: a P4 da diária no Premiere — os merged clips, um por câmera de cada take.

Plano `docs/plano/2026-11-07-premiere-proxy-e-merged.md` (P4); contrato do lado de lá
`DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md` §9 (`POST /api/v1/merge`, medido no 25.6.5 em 06/11).

⭐ **O Sincronizar faz, nós escolhemos.** Como no `sincronizar`: o material sai da bin,
o Sincronizar agrupa e sincroniza, e ELE escreve os merged (o builder dele é o que já foi medido no
Premiere) em bins por cena, `CENAS/<cena>` (decisão do autor, 07/11; a cena é a da claquete do
som, sem claquete → `NAO RESOLVIDO`). O painel dele importa no projeto aberto.

⛔ **O sync roda de novo aqui, no mesmo pedido.** O Sincronizar guarda o resultado de um sync por
2 minutos (`JOB_TTL_MS`): depender do sync anterior seria um merged que funciona ou não
conforme o editor demorou para pedir.

⛔⛔ **Só proxy CONFERIDO vai junto** (`resolve_proxy.conferir_par`, a mesma do
`importar_no_premiere`): o Sincronizar só exige que o arquivo exista, e um proxy de outro material
seria anexado calado. Par reprovado = o merged sai sem proxy, e a resposta diz por quê.

⚠️ O import JUNTA com uma bin `CENAS` que o projeto já tenha (medido, banco
`plugins/premiere-cep/subclipe-e-merged-clip.md` §3d) — dito ao editor na resposta.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ... import laboratorio as _lab
from ... import sincronizar as _sinc
from ... import resolve_proxy as _px
from ...nle import premiere as _premiere
from ...nle.premiere import ponte as _ponte
from ...servico import arrastados as _arrastados
from ...servico import turno as _turno
from ..registro import ferramenta
from . import sincronizar as _fo

log = logging.getLogger("cicloassist.mcp.merged")


def _alcanca(p: Path) -> bool:
    return _arrastados.autorizado(p) or _lab.na_saida(p)


def _conferir(fontes: list[dict] | None = None, proxies: str = "", **_) -> str:
    """ANTES do cartão: sem Sincronizar que faça merged, sem painel dele, sem material ou sem a pasta dos proxies."""
    try:
        saude = _sinc.saude()
        if saude.get("busy"):
            return ("O Sincronizar está ocupado com outro trabalho (ele atende um por vez). Espere "
                    "ele terminar e peça de novo.")
        if not _sinc.faz_merged():
            return ("Este Sincronizar não faz merged pela conversa (falta o /api/v1/merge, que entrou em "
                    "06/11/2026). Atualize o Sincronizar.")
        if not _sinc.tem_painel("premiere"):
            return ("Não dá para importar os merged: " + _sinc.FALTA_A_PREPARAR)
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return str(e)
    if proxies:
        p = Path(proxies)
        if not p.is_dir():
            return f"'{proxies}' não é a pasta dos proxies (a que converter_para_proxy devolveu)."
        if not _alcanca(p):
            return _arrastados.recusa(p)
    try:
        return str(_fo.fontes_do_pedido(fontes).get("erro") or "")
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return str(e)


def pares_de_proxy(cameras: list[str], proxies: Path | None, *, sondar=None) -> tuple[dict[str, str], list[dict]]:
    """`{câmera: proxy}` dos pares que conferem, e `[{arquivo, motivo}]` dos que ficam sem proxy.

    O proxy é o de MESMO NOME na pasta (`<nome do clipe>.mov`), o que o `converter_para_proxy` escreve.
    """
    if proxies is None:
        return {}, []
    sondar = sondar or _px.sondar
    pares, sem = {}, []
    for c in cameras:
        o = Path(c)
        # O nome pelas DUAS barras: o caminho vem do NLE, e o do Windows lido no Mac não se parte no `\\`.
        nome = re.split(r"[\\/]", c)[-1]
        p = proxies / (nome.rsplit(".", 1)[0] + ".mov")
        if not p.exists():
            sem.append({"arquivo": nome, "motivo": "não há proxy com esse nome"})
            continue
        problemas = _px.conferir_par(sondar(o), sondar(p))
        if problemas:
            sem.append({"arquivo": nome, "motivo": "o proxy não confere: " + "; ".join(problemas)})
        else:
            pares[c] = str(p)
    return pares, sem


def _alvo_do_premiere() -> str:
    """O `.prproj` do Sincronizar é escrito para o 25 ou para o 2023 (o 2023 recusa o formato 43)."""
    try:
        versao = str((_premiere.estado() or {}).get("versao") or "")
        maior = int(versao.split(".")[0])
    except (ValueError, TypeError, _ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou):
        return "25"
    return "2023" if maior < 25 else "25"


@ferramenta(
    nome="criar_merged",
    descricao=(
        "Cria os MERGED CLIPS de uma diária no Premiere pelo Sincronizar: um merged (câmera + som direto, já "
        "sincronizados) por câmera de cada take, em bins por cena (CENAS/<cena>, pela claquete do nome do "
        "som; sem claquete, CENAS/NAO RESOLVIDO). O Sincronizar sincroniza a bin de novo (leva o mesmo tempo do "
        "sync) e o painel dele importa os merged no projeto aberto. Use quando o editor pedir merged / merge "
        "clips da diária. bin = a bin da diária (como arvore_do_premiere mostrou). proxies = a pasta que "
        "converter_para_proxy devolveu, quando a diária entrou com o proxy anexado: cada merged leva o proxy "
        "da sua câmera (o botão de proxy do Premiere alterna) — só os pares que conferem (TC, quadros, "
        "canais); o que não confere sai sem proxy e vem em sem_proxy com o motivo."
    ),
    esquema={
        "type": "object",
        "properties": {
            "fontes": {"type": "array", "description": "As fontes da diária, como em sincronizar: uma por câmera, uma por gravador.",
                       "items": {"type": "object", "required": ["tipo"], "properties": {
                           "tipo": {"type": "string", "enum": ["camera", "som"]},
                           "nome": {"type": "string"},
                           "bins": {"type": "array", "items": {"type": "string"}},
                           "arquivos": {"type": "array", "items": {"type": "string"}}}}},
            "sem_supervisao": {"type": "boolean", "default": False,
                               "description": "Só num fluxo, e só se o editor pedir um fluxo SEM supervisão."},
            "proxies": {"type": "string", "description": "A pasta dos proxies (a de converter_para_proxy). Vazio = merged sem proxy."},
            "nome": {"type": "string", "description": "Nome da diária (padrão: o nome da bin)."},
            "metodo": {"type": "string", "enum": list(_sinc.METODOS), "default": "hibrido",
                       "description": "hibrido (timecode + forma de onda), timecode ou forma_de_onda."},
        },
        "required": [],
    },
    escreve=True,
    conferir=_conferir,
    nles=("premiere",),
)
def criar_merged(fontes: list[dict] | None = None, proxies: str = "", nome: str = "",
                       metodo: str = "hibrido", sem_supervisao: bool = False) -> dict[str, object]:
    rotulo = nome or next((str(b).rsplit("/", 1)[-1] for f in (fontes or []) if isinstance(f, dict)
                           for b in (f.get("bins") or [])), "PROJETO")
    try:
        achado = _fo.fontes_do_pedido(fontes)
        if achado.get("erro"):
            return achado
        lidas, offline = achado["fontes"], achado["offline"]
        cameras = [a for f in lidas if f.get("kind") != "sound" for a in (f.get("files") or [])]
        _turno.avisar("conferindo os proxies", None, f"{len(cameras)} câmera(s)")
        pares, sem_proxy = pares_de_proxy(cameras, Path(proxies) if proxies else None)
        job, resultado, _clipes = _fo.rodar_sync(lidas, metodo)
    except _sinc.SincronizarOcupado as e:
        return {"erro": str(e), "ocupado": True}
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return {"erro": str(e)}
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return {"erro": str(e)}

    comum: dict[str, object] = {"metodo": metodo, "fontes": _fo.resumo_das(lidas),
                                **_sinc.resumo_do_mapa(resultado)}
    if offline:
        comum["offline_de_fora"] = _fo.offline_de_fora(offline)
    if sem_proxy:
        comum["sem_proxy"] = sem_proxy

    try:
        _turno.avisar("o Sincronizar está escrevendo os merged", None, rotulo)
        pedido = _sinc.fazer_merged(job, pares, nome=rotulo, premiere_alvo=_alvo_do_premiere())
        _turno.avisar("o Sincronizar (aba Preparar) está importando os merged", None, rotulo)
        fim = _sinc.esperar_montagem(str(pedido["montagem_id"]))
    except _sinc.SincronizarSemPainel as e:
        return {**comum, "feito": f"sync de {rotulo} feito, mas os merged não foram feitos",
                "falta": f"{e}"}
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return {**comum, "feito": f"sync de {rotulo} feito, mas os merged não foram feitos",
                "falta": f"{e}"}

    bins = pedido.get("bins") or {}
    raiz = str(pedido.get("raiz") or "CENAS")
    ausentes = pedido.get("proxy_ausente") or []
    if ausentes:
        comum["proxy_sumiu"] = ausentes
    if fim.get("estado") != "feito":
        return {**comum, "feito": f"o Sincronizar escreveu os merged de {rotulo}, mas a importação falhou",
                "erro_da_importacao": str(fim.get("resumo") or "o painel não disse o motivo")}
    return {
        **comum,
        "feito": f"{pedido.get('merged', 0)} merged de {rotulo} no projeto, {pedido.get('com_proxy', 0)} com proxy",
        "bins": {f"{raiz}/{k}": v for k, v in bins.items()},
        "importacao": str(fim.get("resumo") or ""),
        "agora": (f"Os merged estão no projeto do Premiere, na bin {raiz} (uma bin por cena). Se o projeto "
                  f"já tinha uma bin {raiz}, eles entraram nela. Diga ao editor onde estão e quantos "
                  f"ficaram sem proxy."),
    }
