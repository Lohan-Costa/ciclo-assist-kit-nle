r"""Magic Link — enviar por um CANAL: a Carta Aberta gravada na caixa de entrada do outro lado.

Não há conexão direta entre as máquinas (desenho do autor, 2026-09-24): quem envia grava uma
Carta Aberta numa pasta de rede; quem recebe aperta "Procurar novos" e puxa. Desde 2026-09-25
a pasta é a de um CANAL (edição ⇄ cor, edição ⇄ VFX…), e dentro dela há uma caixa para cada
lado (`canais.py`). A Carta é o envelope completo (`docs/carta-aberta.md`, 1.1): a timeline
inteira, mais o `envio` (id, tipo, canal, de, para, remetente) e, nos inserts, a `selecao`.

## Onde os canais ficam configurados

Na `.delapraca.json` da **pasta do projeto** (o mesmo lugar do banco de mídias, `banco.py`),
em `magic_link.canais = {setor: pasta}`: as pastas são da PRODUÇÃO, não do editor — seguem o
projeto e valem para a equipe. O PAPEL da ilha (edição, cor, vfx) é da máquina (`canais.py`).

## O nome do arquivo

`<sequência>__<8 do id>.carta.json` — o nome diz o que é para quem olha a pasta; o id garante
que dois envios da mesma sequência não se sobrescrevam. ⚠️ Gravação atômica (temporário
`.parcial` ao lado + `os.replace`): quem procura do outro lado nunca vê uma Carta pela metade,
e o temporário não casa com `*.carta.json`.
"""

from __future__ import annotations

import getpass
import logging
import os
import socket
import uuid
from datetime import datetime
from pathlib import Path

import banco
import canais

log = logging.getLogger("delapraca.magic_link")

SUFIXO = ".carta.json"
#: `{setor: tipo do insert}` — derivado da lista de setores (`canais.SETORES`).
TIPOS_INSERT = {k: v["insert"] for k, v in canais.SETORES.items()}
#: O insert exportado para um arquivo (botão Exportar…), fora de qualquer canal.
INSERT_EXPORTADO = "insert"


# ── os canais deste projeto ───────────────────────────────────────────────────────────

def canais_do_projeto(pasta_projeto: str) -> dict[str, str]:
    """`{setor: pasta}` guardados no projeto. ⚠️ A antiga `magic_link.pasta` (pasta única, antes
    dos canais) é ignorada de propósito: nenhum canal olha a raiz antiga."""
    c = ((banco.ler_config(pasta_projeto) or {}).get("magic_link") or {}).get("canais")
    if not isinstance(c, dict):
        return {}
    return {k: v for k, v in c.items() if canais.e_setor(k) and isinstance(v, str)}


def guardar_canal_no_projeto(pasta_projeto: str, setor: str, pasta: str) -> str:
    """Guarda a pasta do canal `setor` no projeto. Levanta `ValueError` com o motivo."""
    if not canais.e_setor(setor):
        raise ValueError(f"canal desconhecido: {setor!r}")
    pasta = canais.validar_pasta(pasta)
    config = banco.ler_config(pasta_projeto)
    ml = dict(config.get("magic_link") or {})
    ml["canais"] = {**canais_do_projeto(pasta_projeto), setor: pasta}
    config["magic_link"] = ml
    if not banco.gravar_config(pasta_projeto, config):
        raise RuntimeError("não consegui guardar o canal na configuração do projeto")
    return pasta


# ── o envelope ────────────────────────────────────────────────────────────────────────

def novo_envio(tipo: str, canal: str | None = None, de: str = canais.EDICAO) -> dict:
    """O bloco `envio` da Carta. `tipo`: timeline · insert_cor · insert_vfx.

    `canal`/`de`/`para` dizem por onde a Carta veio: quem recebe mostra "da Cor", "da Edição".
    """
    try:
        usuario = getpass.getuser()
    except Exception:  # noqa: BLE001 — sem usuário no ambiente, a Carta vai assim mesmo
        usuario = ""
    envio = {"id": str(uuid.uuid4()), "tipo": tipo,
             "remetente": {"maquina": socket.gethostname(), "usuario": usuario},
             "enviado_em": datetime.now().astimezone().isoformat(timespec="seconds")}
    if canal:
        envio.update({"canal": canal, "de": de,
                      "para": canal if de == canais.EDICAO else canais.EDICAO})
    return envio


def caminho_do_envio(pasta: str, nome_sequencia: str, envio: dict) -> str:
    from nomes.export import nome_de_arquivo

    base = nome_de_arquivo(nome_sequencia or "") or "timeline"
    return str(Path(pasta) / f"{base}__{envio['id'][:8]}{SUFIXO}")


def anexo_da_carta(carta: str) -> str:
    """A bin do Avid que viaja ANEXA à Carta de uma timeline (autor, 2026-10-12: "Magic Link Avid → Avid = Carta + a
    bin"): o mesmo nome, `.avb` no lugar de `.carta.json`. Quem recebe no Media Composer relinka pela bin (a
    composição do editor intacta, curva de rampa nativa incluída); quem recebe em outro NLE usa a Carta."""
    p = Path(carta)
    base = p.name[:-len(SUFIXO)] if p.name.endswith(SUFIXO) else p.stem
    return str(p.with_name(base + ".avb"))


def anexar_bin(bin_origem: str, carta: str) -> str:
    """Copia a bin da timeline para o lado da Carta, ANTES dela (quem procura vê a Carta já com a bin no lugar).
    Atômico (`.parcial` + `os.replace`), como a Carta. Devolve o caminho; levanta OSError se a rede recusar."""
    import shutil

    alvo = anexo_da_carta(carta)
    parcial = alvo + ".parcial"
    shutil.copyfile(bin_origem, parcial)
    os.replace(parcial, alvo)
    return alvo


# ── o insert ──────────────────────────────────────────────────────────────────────────

def conferir_itens(itens: list[dict], sequencia: dict) -> tuple[list[dict], list[dict]]:
    """`(valem, mudaram)`: cada item ainda está na sequência como foi coletado?

    A timeline pode ter sido editada entre a coleta e o envio. Um item vale se, na MESMA
    trilha, um segmento do MESMO master ainda cobre o trecho coletado; senão ele "mudou" e
    NÃO vai — o painel mostra, o editor coleta de novo.
    """
    from carta_aberta.insert import _tc

    fps = float(sequencia.get("timeline_fps") or 0) or 25.0
    por = {}
    for s in sequencia.get("segments") or []:
        if s.get("mob_id") and not s.get("is_gap") and not s.get("is_transition"):
            por.setdefault((int(s["track"]), s["mob_id"]), []).append(
                (_tc(s["timeline_tc_in"], fps), _tc(s["timeline_tc_out"], fps)))
    valem, mudaram = [], []
    for it in itens:
        a, b = _tc(it["timeline_tc_in"], fps), _tc(it["timeline_tc_out"], fps)
        cobre = any(x <= a and b <= y for x, y in por.get((int(it["track"]), it["mob_id"]), []))
        (valem if cobre else mudaram).append(it)
    return valem, mudaram


def enviar_insert(mc, coleta, tipo: str, pasta: str, comentario: str = "",
                  so_video: bool = False, anotar=lambda *a, **k: None,
                  nome: str | None = None, canal: str | None = None) -> dict:
    """Grava a Carta do insert na caixa `pasta` do canal. Devolve o resumo para o painel.

    ⭐ A Carta leva a timeline INTEIRA e a `selecao` à parte — quem recebe filtra
    (`carta_aberta.insert.filtrar_insert`). O que o remetente resolve de mídia é só dos masters
    escolhidos (a pergunta ao MC é a parte cara: ~0,5 s por master).
    """
    import relink_avb
    from avb_bin.segmentos import ler_timeline_de_arquivo, montar_midia
    from carta_aberta.writer import build_carta_aberta
    from sessao_export import resolver_midia

    if tipo not in (*TIPOS_INSERT.values(), INSERT_EXPORTADO):
        raise ValueError(f"tipo de insert desconhecido: {tipo!r}")
    seq_mob = (coleta.sequencia or {}).get("mob_id")
    itens = [i for i in coleta.itens if not (so_video and int(i["track"]) >= 1000)]
    if not seq_mob or not itens:
        raise ValueError("a lista está vazia — colete clipes antes de enviar")

    anotar("salvando a bin da sequência")
    bin_seq = mc.bin_do_mob(seq_mob)
    if not bin_seq or not Path(bin_seq).is_file():
        raise LookupError("não achei a bin da sequência — ela está numa bin salva do projeto?")
    relink_avb.garantir_bin_no_disco(mc, bin_seq)
    anotar("lendo a timeline")
    leitura = ler_timeline_de_arquivo(bin_seq, mob_id=seq_mob)

    valem, mudaram = conferir_itens(itens, leitura)
    if not valem:
        raise ValueError("nenhum clipe da lista está mais na timeline como foi coletado — "
                         "colete de novo")
    midia = resolver_midia(mc, leitura, anotar, so_masters={i["mob_id"] for i in valem})

    envio = novo_envio(tipo, canal)
    # O nome é o que o editor compôs no painel (`%tipo`, `%sequencia`…); sem ele, o da sequência.
    nome = (nome or "").strip() or leitura.get("composition_name") or ""
    caminho = caminho_do_envio(pasta, nome, envio)
    selecao = [{k: i[k] for k in ("track", "timeline_tc_in", "timeline_tc_out", "mob_id",
                                  "clip_name")} for i in valem]
    anotar("escrevendo a carta na pasta combinada")
    _segs, casados, _metas = montar_midia(
        leitura, midia["arquivos"], pasta,
        {k: m.get("colunas_mc") or {} for k, m in leitura["masters"].items()},
        midia["gerenciados"])
    resumo = build_carta_aberta(leitura, casados, caminho, nome,
                                comentario, arquivos=midia["arquivos"],
                                gerenciados=midia["gerenciados"], envio=envio, selecao=selecao)
    log.info("insert %s enviado: %s (%d clipe(s), %d mudaram)", tipo, caminho, len(valem),
             len(mudaram))
    return {"arquivo": caminho, "tipo": tipo, "id": envio["id"], "clipes": len(valem),
            "mudaram": mudaram, "saida": {k: v for k, v in resumo.items() if k != "output"}}
