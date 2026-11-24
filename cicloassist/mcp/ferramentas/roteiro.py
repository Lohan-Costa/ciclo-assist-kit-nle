"""`conferir_o_mapa` — a escrituração do roteiro, antes de escrever qualquer bin.

⛔⛔ **Nasceu de uma sessão medida (2026-09-12).** O editor mandou montar a C07 por
roteiro e recebeu "falas repetidas, frases cortadas ao meio, corte em J que não fez
nenhuma diferença e diálogo que não seguiu a ordem do roteiro. horrível." O método da casa
foi consultado 16 s depois do turno abrir e tem regra escrita para os quatro sintomas.
Regra que ninguém confere não é regra, é conselho.

⚠️⚠️ **E a escrituração sozinha não pega o defeito.** Rodada contra aqueles 15 cortes, ela
APROVA: as falas declaradas estavam em ordem, 15 de 16, sem repetição. O modelo declarava
a fala certa e apontava o tempo de OUTRO take. Por isso esta ferramenta faz duas coisas, e
a segunda é a que importa: confere a ordem no papel **e** confronta cada corte com o que a
transcrição diz naquele take naquele intervalo.

⭐ Leitura pura, de propósito. Ela não escreve nada e não passa pelo portão: um passo de
conferência que exige clique é um passo que ninguém dá.
"""

from __future__ import annotations

import logging
from fractions import Fraction
from pathlib import Path

from ...avid.mcapi import McApiErro, MediaComposer
from ...avid.take import TakeErro
from ...avid.take import resolver as _resolver_do_avid
from ...midia import asr as _asr
from ...midia import cache as _cache
from ...plano import mapa as _mapa
from ...servico import arrastados as _arrastados
from ... import documento as _documento
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.roteiro")


def _roteiro_do_arquivo(caminho: str) -> tuple[list[_mapa.Fala], str]:
    """As falas do roteiro, ou ([], motivo)."""
    if not _arrastados.autorizado(caminho):
        return [], _arrastados.recusa(caminho)
    p = Path(caminho)
    if not p.is_file():
        return [], f"{p.name} não é um arquivo que eu consiga abrir."
    try:
        texto = _documento.ler(p)
    except _documento.DocumentoIlegivel as e:
        return [], str(e)
    falas = _mapa.estruturar(texto)
    if not falas:
        return [], (f"não achei diálogo em {p.name}. Espero nome de personagem em CAIXA "
                    f"ALTA sozinho na linha, e a fala embaixo.")
    return falas, ""


@ferramenta(
    nome="estruturar_o_roteiro",
    descricao=(
        "Numera as falas de um roteiro que o editor arrastou, na ordem em que estão "
        "escritas. Chame ANTES de montar uma cena por roteiro: os números são o que "
        "conferir_o_mapa usa para garantir que nada saia de ordem nem entre duas vezes. "
        "Devolve quem fala e o texto de cada fala."
    ),
    esquema={
        "type": "object",
        "properties": {
            "arquivo": {"type": "string",
                        "description": "O caminho exato que veio do arrasto."},
        },
        "required": ["arquivo"],
    },
    escreve=False,
    nles=AMBOS,
)
def estruturar_o_roteiro(arquivo: str) -> dict[str, object]:
    falas, erro = _roteiro_do_arquivo(arquivo)
    if erro:
        return {"erro": erro}
    return {
        "arquivo": Path(arquivo).name,
        "falas": [{"n": f.n, "personagem": f.personagem, "texto": f.texto}
                  for f in falas],
        "quantas": len(falas),
        "como_usar": (
            "Estes números são a ORDEM. Monte o mapa fala por fala, do 1 ao "
            f"{len(falas)}, e confira com conferir_o_mapa antes de chamar montar_corte. "
            "Um corte pode cobrir várias falas seguidas, e uma fala longa pode ser "
            "coberta por dois planos colados — o que não pode é voltar atrás."
        ),
        "confianca": "confirmado",
        "fonte": "roteiro",
    }


def falado_no_take(caminho_da_bin: str):
    """Devolve `falado(take, inicio_frames, duracao_frames) -> str | None`."""
    segmentos = segmentos_no_take(caminho_da_bin)

    def falado(nome: str, inicio: int, duracao: int):
        achados = segmentos(nome, inicio, duracao)
        return None if achados is None else " ".join(t for _, _, t in achados)

    return falado


def resolver(caminho_da_bin: str, nome: str):
    """O take pelo NLE do TURNO: no Premiere `caminho_da_bin` é o caminho da bin no projeto
    ("CENAS/C07"), no Avid o `.avb`. ⭐ F3 do plano 2026-11-06-mcp-do-premiere."""
    from ... import nle as _nle
    if _nle.qual() == _nle.PREMIERE:
        return _nle.resolver_take(caminho_da_bin, nome)
    return _resolver_do_avid(caminho_da_bin, nome)


def segmentos_no_take(caminho_da_bin: str):
    """Devolve `segmentos(take, inicio, duracao) -> [(de, ate, texto)] | None`, em frames
    do TAKE — o que o ASR ouviu cruzando aquele intervalo, segmento a segmento.

    ⭐ Só do CACHE: conferir não pode disparar meia hora de ASR. Take ainda não transcrito
    volta `None` e entra na conta de "não conferidos", em vez de virar erro.
    """
    lembrados: dict[str, object] = {}

    def segmentos(nome: str, inicio: int, duracao: int):
        if nome not in lembrados:
            take = resolver(caminho_da_bin, nome)
            som = take.som
            if som is None or not som.arquivos:
                lembrados[nome] = None
            else:
                midia = som.midia()
                falas = midia.ler_transcricao() if midia.tem_transcricao() else []
                lembrados[nome] = (take, falas) if falas else None
        guardado = lembrados[nome]
        if guardado is None:
            return None
        take, falas = guardado
        taxa = Fraction(take.fps["num"], take.fps["den"])
        base = take.som.inicio_s
        de_s = base + float(inicio / taxa)
        ate_s = base + float((inicio + duracao) / taxa)
        dentro = _asr.recortar(falas, de_s, ate_s)
        return [(round((float(f["inicio"]) - base) * taxa),
                 round((float(f["fim"]) - base) * taxa), f["texto"]) for f in dentro]

    return segmentos


@ferramenta(
    nome="conferir_o_mapa",
    descricao=(
        "Confere um mapa de corte contra o roteiro E contra o que os takes realmente "
        "falam, ANTES de montar. Pega diálogo fora da ordem do roteiro, fala repetida, "
        "fala esquecida, e — o mais importante — corte que aponta o tempo de um take "
        "estando a fala em outro. Chame sempre antes de montar_corte numa cena com "
        "roteiro; se ela reprovar, conserte e confira de novo."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "Caminho da bin dos takes."},
            "arquivo": {"type": "string",
                        "description": "O roteiro arrastado, o mesmo de "
                                       "estruturar_o_roteiro."},
            "cortes": {
                "type": "array",
                "description": "O mapa, na ordem em que os cortes entram na timeline.",
                "items": {
                    "type": "object",
                    "properties": {
                        "falas": {
                            "type": "array", "items": {"type": "integer"},
                            "description": "Que falas do roteiro este corte carrega. "
                                           "Quase sempre uma; várias quando um corte só "
                                           "cobre falas seguidas.",
                        },
                        "take": {"type": "string"},
                        "inicio_no_take_frames": {"type": "integer"},
                        "duracao_frames": {"type": "integer"},
                        "porque": {"type": "string"},
                    },
                    "required": ["falas", "take", "inicio_no_take_frames",
                                 "duracao_frames"],
                },
            },
        },
        "required": ["bin", "arquivo", "cortes"],
    },
    escreve=False,
)
def conferir_o_mapa(bin: str, arquivo: str, cortes: list) -> dict[str, object]:
    roteiro, erro = _roteiro_do_arquivo(arquivo)
    if erro:
        return {"erro": erro}

    atribuicoes = []
    for i, c in enumerate(cortes or [], 1):
        if not isinstance(c, dict):
            return {"erro": f"corte {i} não é um objeto."}
        falas = c.get("falas") or []
        if isinstance(falas, int):
            falas = [falas]
        try:
            atribuicoes.append(_mapa.Atribuicao(
                falas=[int(n) for n in falas],
                take=str(c.get("take") or ""),
                inicio_no_take_frames=int(c.get("inicio_no_take_frames") or 0),
                duracao_frames=int(c.get("duracao_frames") or 0),
                porque=str(c.get("porque") or ""),
            ))
        except (TypeError, ValueError):
            return {"erro": f"corte {i}: falas, inicio_no_take_frames e duracao_frames "
                            f"têm de ser números inteiros."}

    conf = _mapa.conferir(roteiro, atribuicoes)

    # ── a âncora no material ────────────────────────────────────────────────
    nao_conferidos = 0
    try:
        caminho = bin
        if not Path(bin).is_absolute():
            with MediaComposer() as mc:
                caminho = str(Path(mc.projeto().get("caminho") or "") / bin)
        falado = falado_no_take(caminho)

        def contando(nome, inicio, duracao):
            nonlocal nao_conferidos
            dito = falado(nome, inicio, duracao)
            if dito is None:
                nao_conferidos += 1
            return dito

        conf.problemas.extend(_mapa.ancorar(roteiro, atribuicoes, contando))
    except (TakeErro, McApiErro, _cache.ChaveInvalida) as e:
        # ⚠️ Não poder conferir não é reprovar — mas tem de ser DITO, senão um "aprovado"
        #    sem âncora vira falsa segurança, que é pior que não ter conferido.
        nao_conferidos = len(atribuicoes)
        log.info("mapa sem âncora: %s", e)

    resposta: dict[str, object] = {
        "fecha": conf.fecha,
        "falas_no_roteiro": len(roteiro),
        "falas_cobertas": len(conf.cobertas),
        "sacrificadas": conf.sacrificadas,
        # ⭐ A cobertura, dita em número antes de qualquer conferência: um mapa de quinze
        #   cortes num plano só se denuncia aqui.
        "planos_usados": conf.planos_usados,
        "problemas": conf.problemas,
        "resumo": _mapa.relatar(roteiro, conf),
        "confianca": "confirmado",
        "fonte": "roteiro",
    }
    if nao_conferidos:
        resposta["nao_conferidos_no_material"] = nao_conferidos
        resposta["atencao"] = (
            f"{nao_conferidos} corte(s) não foram confrontados com a transcrição porque "
            f"aquele take ainda não foi transcrito. Transcreva-os antes de confiar neste "
            f"'fecha'."
        )
    if conf.fecha and not nao_conferidos:
        resposta["agora"] = ("O mapa fecha e bate com o material. Pode chamar "
                             "montar_corte com estes mesmos cortes.")
    return resposta
