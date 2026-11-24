"""Escreve uma timeline no formato Carta Aberta (JSON). Especificação: `docs/carta-aberta.md`.

É o formato mais barato da aba Daqui Pra Lá: nenhum blob binário, nenhum esqueleto, nenhum
`ffprobe`. É um retrato fiel do que o motor já leu — os segmentos no mesmo formato de
`aaf/parser.py::Segment.to_dict()` —, com a origem, o comentário do editor e o que ficou de
fora (`avisos`) escritos junto. Quem abre a carta sabe o que ela NÃO traz.

⭐⭐ **Desde a 1.1, a Carta é SEM PERDAS** (regra do autor: *"nada deve ser perdido na carta
aberta"*): ela leva a leitura CRUA do Avid — os segmentos de antes de `montar_midia` e cada
master inteiro, no bloco `avid` — mais o que o remetente sabia da mídia (`arquivo_ama`,
`gerenciadas`). Quem recebe roda o MESMO `montar_midia` com a mídia da máquina dele e chega ao
mesmo DRT. O teste `tests/test_carta_ida_e_volta.py` exige isso: DRT da bin ≡ DRT da Carta.

**1.2 (2026-09-27):** o efeito de título leva o bloco `params.titulo` (texto, fonte, corpo, cor,
alinhamento, posição, contorno, sombra e fundo, no modelo neutro de `motor/titulos/avid.py`, mais
o estilo cru do Avid em `titulo.avid`). Um leitor 1.1 ignora o bloco: o título só não aparece.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from aaf.parser import frames_to_tc

VERSAO_DO_FORMATO = "1.2"

#: O que o receptor precisa de cada master para refazer `montar_midia` — o dict da leitura,
#: tal como `avb_bin.segmentos` o monta, mais as colunas que o Media Composer deu.
CAMPOS_DO_MASTER = ("nome", "caminho_na_bin", "descritor", "fps", "duracao_frames",
                    "identidade", "essencias", "colunas_mc")

#: Os tipos de envio do Magic Link. `timeline` é a sequência inteira; os inserts levam a
#: sequência inteira TAMBÉM, mais a `selecao` — quem recebe filtra (a Carta segue completa).
#: `insert` (sem setor) é o insert EXPORTADO para um arquivo, fora de um canal.
TIPOS_DE_ENVIO = ("timeline", "insert_cor", "insert_vfx", "insert")


def montar(resultado: dict, match_results: list, nome: str, comentario: str | None = None,
           aplicativo: str = "Avid Media Composer", gerado_por: str = "De Lá Pra Cá", *,
           arquivos: dict[str, str] | None = None, gerenciados: dict[str, str] | None = None,
           envio: dict | None = None, selecao: list[dict] | None = None, producao: str | None = None) -> dict:
    """O documento Carta Aberta, sem gravar. `resultado` é o de `ler_timeline`/`parse_aaf`.

    `arquivos` (`{master: arquivo AMA}`) e `gerenciados` (`{urn da essência: .mxf}`) são o
    que o REMETENTE resolveu — os mesmos que ele passou a `montar_midia`. Viajam por master
    para que o receptor os reaproveite quando existirem na máquina dele.
    """
    if envio is not None and envio.get("tipo") not in TIPOS_DE_ENVIO:
        raise ValueError(f"tipo de envio desconhecido: {envio.get('tipo')!r}")
    arquivos = arquivos or {}
    gerenciados = gerenciados or {}
    validos = [m for m in (match_results or []) if m.get("matched_path") and not m.get("rejected")]
    por_segmento = {m["segment_index"]: m["matched_path"] for m in validos}
    offline = {m["segment_index"] for m in validos if m.get("offline")}
    segmentos = []
    for i, s in enumerate(resultado.get("segments") or []):
        item = dict(s)
        item["arquivo"] = por_segmento.get(i)
        item["offline"] = i in offline
        segmentos.append(item)

    # ⭐ Quem é cada original — é por aqui que o lado de lá (o colorista, o nosso plugin no
    # Resolve) casa um clipe offline com o arquivo em alta: reel, TC de origem, duração.
    por_mob: dict[str, dict] = {}
    for s in segmentos:
        if s.get("mob_id") and s["arquivo"] and s["mob_id"] not in por_mob:
            por_mob[s["mob_id"]] = {"arquivo": s["arquivo"], "offline": s["offline"]}
    masters = []
    for chave, m in (resultado.get("masters") or {}).items():
        ident = m.get("identidade") or {}
        inicio, tc_fps = ident.get("tc_inicio"), ident.get("tc_fps")
        essencias = m.get("essencias") or {}
        masters.append({
            "mob_id": chave,
            "nome": m.get("nome"),
            "reel": ident.get("reel") or None,
            "tc_origem": frames_to_tc(inicio, tc_fps) if inicio is not None and tc_fps else None,
            "duracao_frames": m.get("duracao_frames"),
            "fps": ident.get("fps") or m.get("fps"),
            "resolucao": ([ident["largura"], ident["altura"]]
                          if ident.get("largura") and ident.get("altura") else None),
            "arquivo_original": ((m.get("colunas_mc") or {}).get("Source File") or None),
            **por_mob.get(chave, {"arquivo": None, "offline": None}),
            # ── sem perdas (1.1) ─────────────────────────────────────────────────────
            # ⚠️ Os campos de cima são para GENTE e misturam fontes (o `fps` prefere a
            # identidade). O receptor lê SÓ o bloco `avid`: o master exatamente como a
            # leitura o deu, que é o que `montar_midia` consome.
            "avid": {k: m[k] for k in CAMPOS_DO_MASTER if k in m},
            "arquivo_ama": arquivos.get(chave),
            "gerenciadas": {trilha: gerenciados[urn] for trilha, urn in essencias.items()
                            if urn in gerenciados},
        })

    texto = (comentario or "").strip()
    doc = {
        "carta_aberta": VERSAO_DO_FORMATO,
        "gerado_em": datetime.now().astimezone().isoformat(timespec="seconds"),
        "gerado_por": gerado_por,
        "nome": nome,
        "origem": {
            "aplicativo": aplicativo,
            "sequencia": resultado.get("composition_name") or "",
            "mob_id": resultado.get("sequence_mob_id"),
            "leitura": resultado.get("fonte") or "aaf",
        },
        "tempo": {
            "fps": resultado.get("timeline_fps"),
            "drop_frame": bool(resultado.get("timeline_drop_frame")),
            "tc_inicial": resultado.get("timeline_start_tc"),
            "tc_inicial_frames": resultado.get("timeline_start_frames"),
            "base_dos_segmentos": "frames a partir do início da timeline (00:00:00:00), "
                                  "sem o TC inicial somado",
        },
        "comentario": texto or None,
        "marcadores": list(resultado.get("markers") or []),
        "masters": masters,
        "segmentos": segmentos,
        "resumo": {
            "segmentos": len(segmentos),
            "com_arquivo": sum(1 for s in segmentos if s["arquivo"] and not s["offline"]),
            "offline": sum(1 for s in segmentos if s["offline"]),
            "sem_arquivo": sum(1 for s in segmentos
                               if not s["arquivo"] and s.get("mob_id")
                               and not s.get("is_gap") and not s.get("is_transition")),
        },
        "avisos": list(resultado.get("avisos") or []),
        # Trilhas cujo percurso não fechou no comprimento da sequência (`ler_timeline`).
        "conferencia": list(resultado.get("conferencia") or []),
    }
    if envio is not None:
        doc["envio"] = dict(envio)
    if selecao is not None:
        doc["selecao"] = [dict(s) for s in selecao]
    # a PRODUÇÃO (proposta Baselight no app, etapa 4; autor, 2026-11-22): opcional, do Daqui Pra Lá — o nome do projeto
    # aberto, ou o que o editor escreveu. Do outro lado vira o JOB do Baselight (um job por produção). Leitor 1.x ignora.
    if producao:
        doc["producao"] = str(producao)[:100]
    return doc


def build_carta_aberta(resultado: dict, match_results: list, saida: str, nome: str,
                       comentario: str | None = None, **extras) -> dict:
    """Grava a Carta Aberta em `saida` e devolve o resumo. `extras` vão para `montar`
    (`arquivos`, `gerenciados`, `envio`, `selecao`).

    Grava num temporário AO LADO e troca no fim: um JSON pela metade no lugar do arquivo
    de um editor é pior que nenhum — e, na pasta combinada do Magic Link, quem procura do
    outro lado nunca vê um envio pela metade.
    """
    import tempfile

    doc = montar(resultado, match_results, nome, comentario, **extras)
    alvo = Path(saida)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    # ⛔ CORRIGE (2026-09-24, ataque V7): o temporário era `<alvo>.parcial` — nome PREVISÍVEL
    # numa pasta de rede em que outros escrevem. Plantado antes (uma pasta com esse nome, ou
    # um link), o envio quebrava ou escrevia onde o link mandasse. `mkstemp` cria com nome
    # aleatório e O_EXCL, na MESMA pasta (o `os.replace` só é atômico no mesmo volume), e o
    # nome não termina em `.carta.json` — quem procura do outro lado não o vê.
    fd, temporario = tempfile.mkstemp(dir=alvo.parent, prefix=f".{alvo.name}.", suffix=".parcial")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            json.dump(doc, fh, ensure_ascii=False, indent=2)
            fh.write("\n")
        os.replace(temporario, alvo)
    except BaseException:
        Path(temporario).unlink(missing_ok=True)
        raise
    return {"output": str(alvo), **doc["resumo"]}
