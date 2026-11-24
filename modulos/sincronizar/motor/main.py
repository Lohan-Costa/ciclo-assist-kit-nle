"""
Sincronizar — Sidecar Python
Ponto de entrada para comunicação com o backend Rust via stdin/stdout.

Protocolo:
  - Recebe comandos JSON via stdin (uma linha por comando)
  - Responde com JSON via stdout (uma linha por resposta)

Formato do comando:
  {"id": "uuid", "command": "nome_do_comando", "params": {...}}

Formato da resposta:
  {"id": "uuid", "ok": true, "data": {...}}
  {"id": "uuid", "ok": false, "error": "mensagem", "detail": "..."}
"""

from __future__ import annotations

import os
import sys
import json
import time
from pathlib import Path

# O protocolo com o Rust é JSON por stdin/stdout — sempre UTF-8, por contrato.
# Sem isto, no Windows sys.stdout/stdin herdam o codepage do sistema (ex.:
# cp1252 num Windows em português), que não cobre todo o Unicode — um nome de
# cena/arquivo com emoji, CJK ou cirílico (ensure_ascii=False no json.dumps
# preserva o caractere cru) derruba o processo com UnicodeEncodeError na
# escrita. Forçar UTF-8 aqui elimina a dependência do locale da máquina.
#
# ⚠️ `hasattr` porque nem todo `sys.stdout` é um arquivo de verdade: sob o `pytest`
# ele é um capturador sem `reconfigure`, e sem a guarda o simples `import main`
# estourava — o que deixava os comandos do sidecar sem como serem testados.
if (sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8")
        and hasattr(sys.stdout, "reconfigure")):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", newline="\n")
if (sys.stdin.encoding and sys.stdin.encoding.lower() not in ("utf-8", "utf8")
        and hasattr(sys.stdin, "reconfigure")):
    sys.stdin.reconfigure(encoding="utf-8")

# Um dono só para os caminhos do app (`settings.logs_dir`) — a janela de
# configurações precisa apontar o usuário para ESTA pasta, e duas contas
# separadas do mesmo caminho um dia divergem.
import appsettings as app_settings
from media import safepath

# ⛔ O log é de UM dono só (`registro.py`), e ele é o mesmo arquivo para todas as
# execuções — antes era um `sincronizar_<timestamp>.log` novo por vez, e achar o certo
# num relato de campo dependia de acertar o horário. Ver a docstring de lá.
import registro

registro.configurar("sidecar", app_settings.logs_dir())
log = registro.log(__name__)


#: Teto para UMA linha de comando vinda do Rust. O transporte é um pipe, e o teto
#: do servidor HTTP (`MAX_BODY_BYTES`, 8 MB) não vale aqui — são canais diferentes.
#: 16 MB dá folga de sobra para o maior payload real (o `result` de um sync de
#: centenas de clipes) e ainda impede que uma linha absurda custe memória só de
#: chegar. Ver o `except` do laço em `main()`.
MAX_LINHA_BYTES = 16 * 1024 * 1024


def _write_line(payload: str) -> None:
    """
    Escreve uma linha em stdout, com retry.

    No Windows, o transporte é um pipe anônimo (criado pelo Rust). Sob rajada
    de escritas pequenas e rápidas em sequência — um evento de progresso por
    clipe, no laço de sync — a escrita pode falhar transitoriamente com
    `OSError: [Errno 22] Invalid argument` (visto em produção: sync de 50
    clipes, sem nada de anormal nos dados). Tenta de novo antes de desistir;
    se persistir, deixa a exceção subir para o chamador decidir.
    """
    last_err: OSError | None = None
    for attempt in range(5):
        try:
            sys.stdout.write(payload + "\n")
            sys.stdout.flush()
            return
        except OSError as e:
            last_err = e
            log.warning("Falha ao escrever em stdout (tentativa %d/5): %s", attempt + 1, e)
            time.sleep(0.02 * (attempt + 1))
    raise last_err


def _sanear(v):
    """Troca `NaN`/`Infinity` por `None`, recursivamente.

    ⚠️ TUPLA entra junto com lista. O `json.dumps` serializa tupla como array sem
    reclamar, então uma tupla escapando daqui levaria o `NaN` intacta para a segunda
    serialização — que levanta `ValueError` de novo, agora FORA do `try`, e a
    mensagem se perde. O caminho de salvamento não pode ser o que quebra.
    """
    if isinstance(v, float) and (v != v or v in (float("inf"), float("-inf"))):
        return None
    if isinstance(v, dict):
        return {k: _sanear(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_sanear(x) for x in v]
    return v


def _dump(msg: dict) -> str:
    """Serializa uma mensagem do protocolo — em JSON que o RUST consiga ler.

    ⚠️ `json.dumps` aceita `NaN` e `Infinity` e os escreve como literais nus. Isso
    NÃO é JSON válido: o `serde_json` do outro lado recusa a linha inteira com
    `expected value`, e o comando morre com uma mensagem que não diz nada sobre a
    causa (o Rust ainda corta a linha em 200 caracteres para exibir, então o campo
    culpado nem aparece). Um único `0/0` perdido no meio de um sync de 400
    arquivos derruba o sync todo.

    `allow_nan=False` transforma isso em exceção AQUI, onde ainda se sabe o que
    estava sendo escrito. A mensagem então é saneada e enviada assim mesmo — um
    campo nulo é degradação aceitável, perder a resposta inteira não é — e o
    incidente vai para o log com o payload, que é o que faltava para diagnosticar.
    """
    try:
        return json.dumps(msg, ensure_ascii=False, allow_nan=False)
    except ValueError:
        saneado = _sanear(msg)
        log.error(
            "Payload com NaN/Infinity (saneado antes de enviar) | id=%s %s",
            msg.get("id"),
            json.dumps(saneado, ensure_ascii=False)[:2000],
        )
        return json.dumps(saneado, ensure_ascii=False, allow_nan=False)


def respond(cmd_id: str, data: dict) -> None:
    _write_line(_dump({"id": cmd_id, "ok": True, "data": data}))


def respond_progress(cmd_id: str, data: dict) -> None:
    _write_line(_dump({"id": cmd_id, "event": "progress", "data": data}))


def respond_error(cmd_id: str, message: str, detail: str = "") -> None:
    _write_line(_dump({"id": cmd_id, "ok": False, "error": message, "detail": detail}))
    log.error("Comando %s falhou: %s | %s", cmd_id, message, detail)


def _sync_one_daily(
    cmd_id: str,
    gi: int,
    total_groups: int,
    gid: str,
    gname: str,
    gfiles: list,
    *,
    fps,
    start_tc_frames: int,
    sync_method: str = "hybrid",
    pinned: dict | None = None,
    selected: set | None = None,
) -> dict:
    """
    Sincroniza UMA diária e devolve a entrada de resultado (`{**daily_to_dict(...),
    "id": gid}`) ou de erro (`{"id", "name", "error"}`) — o formato que "sync" e
    "resync" devolvem em `groups`, um por diária.

    `pinned`/`selected` (RE-SYNC PARCIAL, Etapa D) — `None` nos dois é o sync cheio
    de sempre; ver `sync.engine.run` para o que eles fazem.

    Isolado por diária: uma que falha não pode derrubar as outras (ver o
    `try/except` em `handle_command`).
    """
    from sync.engine import run as sync_run
    from sync.serialize import daily_to_dict

    def on_progress(msg: str, cur: int, tot: int, overall: float | None = None) -> None:
        # `current`/`total` são da FASE (o contador "12/77" que a tela mostra).
        # `overall` é a fração do sync INTEIRO, já mapeada na faixa da fase — quem
        # desenha barra usa esta, e é o que impede a barra de voltar a zero a cada
        # troca de fase. Ver `_PHASE_BANDS` em `sync/engine.py`.
        respond_progress(cmd_id, {
            "kind": "status", "message": msg, "current": cur, "total": tot,
            "overall": overall,
            "sync_group_id": gid,
            "group_index": gi, "group_total": total_groups,
        })

    def on_sound(payload: dict) -> None:
        respond_progress(cmd_id, {"kind": "sound", "sync_group_id": gid, **payload})

    def on_clip(payload: dict) -> None:
        respond_progress(cmd_id, {"kind": "clip", "sync_group_id": gid, **payload})

    try:
        daily = sync_run(
            gfiles,
            progress=on_progress,
            project_name=gname,
            on_sound=on_sound,
            on_clip=on_clip,
            fps=fps,
            start_tc_frames=start_tc_frames,
            sync_method=sync_method,
            pinned=pinned,
            selected=selected,
        )
        return {**daily_to_dict(daily), "id": gid}
    except ValueError as e:
        log.warning("Grupo %s falhou: %s", gid, e)
        return {"id": gid, "name": gname, "error": str(e)}
    except Exception as e:
        log.exception("Erro no sync do grupo %s: %s", gid, e)
        return {"id": gid, "name": gname, "error": str(e)}


#: Teto de arquivos por comando.
#:
#: Não é um número técnico, é uma tranca: sem ele, um cliente do servidor local manda
#: cem mil caminhos e o sidecar — que é SERIAL, um comando por vez — fica horas
#: moendo, com o app inteiro travado atrás dele. Uma diária real tem dezenas ou
#: poucas centenas de arquivos; 5000 é folgado o bastante para nunca incomodar quem
#: está trabalhando de verdade.
MAX_ARQUIVOS_POR_COMANDO = 5000

#: O último levantamento da aba Renomear — `{"id", "itens", "quando"}`.
#:
#: ⭐⭐ Ele existe para que o `apply` receba **só o padrão**, nunca a lista de nomes:
#: o plano é recomposto aqui, com o mesmo `prever` que desenhou a tela, e não há
#: janela em que o conferido e o aplicado divirjam.
#:
#: ⚠️ UM, e não um dicionário por id. Isto é cache de correlação, não estado de
#: sessão — e um mapa que cresce sem teto num processo de vida longa é vazamento.
#: O preço é assumido: um segundo arrasto invalida o primeiro, e quem tentar
#: aplicar o antigo ouve "o levantamento expirou" em vez de renomear pelo que não
#: está mais na tela.
_ULTIMO_LEVANTAMENTO: dict = {}

#: A última leitura da aba Subclipar — `{"id", "tomadas", "bin", "colunas", "nomes"}`.
#:
#: ⭐ Mesma razão do `_ULTIMO_LEVANTAMENTO`: o `write` recebe só o `leitura_id` e o
#: padrão, e recompõe os nomes com o mesmo `nomear.aplicar` que desenhou a tela. E
#: guardar as `Tomada` já lidas evita reabrir a `.avb` — a leitura é o passo caro.
_ULTIMAS_TOMADAS: dict = {}


def _contagem_de_trilhas(t) -> dict:
    """`{"picture", "sound"}` — as TRACKS que o subclipe vai ter.

    ⭐⭐ Pergunta ao próprio autor das trilhas (`subclipes.agrupar_por_trilha`) em vez
    de repetir a regra aqui. Contar TRECHOS é outra coisa: uma câmera que parou e
    voltou dá dois trechos e UMA trilha — contando trechos, a coluna V/A anunciava
    `V2` para uma câmera só, ou seja, a multicâmera falsa que ela existe para
    denunciar. Duas contagens da mesma coisa divergem no dia em que uma das duas
    muda, e foi exatamente assim que este defeito nasceu.

    ⭐ Achado no porte do painel para o Assist anterior (2026-08-26) e consertado lá
    primeiro; volta para casa em 2026-09-21.
    """
    from avid import subclipes as _subclipes

    grupos = _subclipes.agrupar_por_trilha(t.trechos)
    return {
        "picture": sum(1 for g in grupos if g[0].media_kind == "picture"),
        "sound": sum(1 for g in grupos if g[0].media_kind == "sound"),
    }


def _tomada_para_tela(t) -> dict:
    """Uma `Tomada` como a tabela do painel a mostra.

    ⚠️ `aparado` e `duracao_bruta` vão JUNTOS de propósito: um take que perdeu 88 s
    de cauda porque a câmera parou cedo continua legítimo, mas o editor precisa ver
    o número antes de abrir a bin — senão descobre o corte olhando o material.

    ⚠️ E `convencao == "posicao"` viaja para a tela poder escrever "presumida": a
    cena veio da POSIÇÃO do órfão na timeline, não de uma claquete. Inferência que
    não se declara é inferência que passa por medição.
    """
    return {
        "nome": t.nome,
        "episodio": getattr(t, "episodio", None),
        "cena": t.cena,
        "plano": t.plano,
        "take": t.take,
        "duracao": t.duracao,
        "duracao_bruta": t.duracao_bruta,
        "aparado": t.aparado,
        # frames → segundos na tela. ⚠️ Os DOIS painéis usam: o do Avid dividia por
        # 24 fixo e mostrava 25% a mais a 29,97 (consertado em 2026-09-21). Sem taxa
        # o painel mostra QUADROS — inventar segundo seria pior que não dizer.
        "edit_rate": t.edit_rate,
        "resolvido": t.resolvido,
        "orfao": t.orfao,
        "convencao": t.convencao,
        "origem": t.origem,
        # ⚠️ TRILHAS, não trechos — ver `_contagem_de_trilhas`.
        "trilhas": _contagem_de_trilhas(t),
    }


def _validar_caminhos(entradas):
    """
    O portão de entrada do sidecar: transforma a lista de strings do cliente numa
    lista de caminhos locais que existem — ou levanta `CaminhoInvalido`.

    ⚠️ POR QUE ISTO EXISTE: as strings chegam, em última instância, do servidor
    HTTP local, e não são confiáveis. `http://…` num "caminho" faz o MediaInfo e o
    ffmpeg BUSCAREM A REDE a partir da máquina do editor. Ver `media/safepath.py`
    para o mecanismo; aqui é só onde ele é aplicado, cedo e uma vez só.
    """
    from media.safepath import CaminhoInvalido, ensure_local_file

    if not isinstance(entradas, list):
        raise CaminhoInvalido("lista de arquivos inválida")
    if len(entradas) > MAX_ARQUIVOS_POR_COMANDO:
        raise CaminhoInvalido(
            f"arquivos demais num pedido só (máximo {MAX_ARQUIVOS_POR_COMANDO})"
        )
    for e in entradas:
        # Uma entrada pode ser a string do caminho ou o dicionário que o painel de
        # NLE manda (`{path, group_id, …}`). Só o caminho interessa aqui.
        alvo = e.get("path") if isinstance(e, dict) else e
        ensure_local_file(alvo)
    # ⚠️ Devolve NADA de propósito: quem chama segue usando as strings ORIGINAIS.
    # Trocar pelo caminho resolvido mudaria o nome exibido quando a mídia está atrás
    # de symlink (comum em fluxo de post), e esta função é de segurança, não de
    # normalização — uma coisa de cada vez.
    return None


def mapa_arquivo_para_nome(caminhos: dict[str, list[str]],
                          colunas: dict[str, dict]) -> dict[str, str]:
    """`{arquivo: NOME DO MASTERCLIPE}` — o nome que o editor vê na bin.

    ⭐ **POR QUE ISTO VIAJA COM AS FONTES** (pedido do autor, 2026-08-23, olhando o
    painel): em mídia gerenciada o nome do ARQUIVO é ilegível — a `Avid MediaFiles`
    guarda `V01.E69CCF0F_1A8ED1A8EDCFCV.mxf`, e um clipe de 1 vídeo + 2 áudios vira
    TRÊS linhas dessas na lista. O editor não reconhece nada ali.

    O `Name` do master é o nome que ele deu ao clipe, e ele já vem de graça no
    `GetMobInfo` que a resolução faz de qualquer jeito — não custa uma chamada a
    mais.
    """
    fora: dict[str, str] = {}
    for mob, lista in caminhos.items():
        nome = ((colunas.get(mob) or {}).get("Name") or "").strip()
        if not nome:
            continue
        for arquivo in lista:
            fora[arquivo] = nome
    return fora


def mapa_arquivo_para_mob(caminhos: dict[str, list[str]]) -> dict[str, str]:
    """`{mob_id: [arquivos]}` → `{arquivo: mob_id}`.

    ⭐ **Este mapa VIAJA COM AS FONTES, e é por isso que ele existe.** Sem ele, na
    hora de montar a bin o Órbita teria de descobrir de novo qual master é cada
    arquivo — e a única forma de descobrir é VARRER as bins do projeto, o que ABRE
    cada uma na tela do editor. A pergunta já foi feita; repeti-la é o que causava
    o estrago.

    ⚠️ Um MobID pode ter VÁRIOS arquivos (OP-Atom: um por track), e cada um deles
    aponta de volta para o mesmo master.
    """
    return {arquivo: mob for mob, lista in caminhos.items() for arquivo in lista}


#: MobID de master: **64 dígitos hexadecimais**, e a pontuação NÃO conta.
#:
#: ⚠️ O agrupamento de hifens MUDA conforme a superfície — `26-6-16-8-8` no exemplo
#: da API e `26-6-16-12-4` no payload do arrasto. Um validador que crave os hifens
#: recusa MobID legítimo, e o sintoma é *"o clipe que arrastei não é reconhecido"*.
#: Medido no De Lá Pra Cá; ver `arrastar.md` §2 na base de conhecimento interna.
_HEX_DO_MOB_ID = 64


def mob_id_plausivel(bruto) -> bool:
    """Isto tem cara de MobID? Filtra os hexadecimais e conta.

    (`string.hexdigits` em vez do literal: o talisman lê uma string com o alfabeto
    hex inteiro como "texto hex-encoded" e aborta o commit. A alternativa era uma
    exceção no `.talismanrc`, que trava o CHECKSUM do arquivo todo — porta aberta
    permanente num arquivo que muda toda semana.)
    """
    import string

    if not isinstance(bruto, str):
        return False
    return len([c for c in bruto if c in string.hexdigits]) == _HEX_DO_MOB_ID


def handle_command(cmd: dict) -> None:
    cmd_id   = cmd.get("id", "unknown")
    command  = cmd.get("command", "")
    params   = cmd.get("params", {})

    log.info("Comando: %s | id=%s", command, cmd_id)

    if command == "ping":
        respond(cmd_id, {"pong": True, "version": "0.1.0"})

    # ── Configurações e cache ────────────────────────────────────────────────
    elif command == "get_settings":
        from media import cachedir
        respond(cmd_id, {
            **app_settings.load(),
            "logs_dir": str(app_settings.logs_dir()),
            "cache": cachedir.stats(),
        })

    elif command == "set_settings":
        from media import cachedir
        saved = app_settings.save(params or {})
        # O teto novo vale AGORA, não no próximo sync: quem acabou de baixar o
        # limite espera ver o cache encolher, não descobrir depois que não fez nada.
        evicted = cachedir.enforce_limit()
        respond(cmd_id, {
            **saved,
            "logs_dir": str(app_settings.logs_dir()),
            "cache": cachedir.stats(),
            "evicted": evicted,
        })

    elif command == "cache_stats":
        from media import cachedir
        respond(cmd_id, cachedir.stats())

    elif command == "cache_clear":
        from media import cachedir
        freed = cachedir.clear()
        respond(cmd_id, {**freed, "cache": cachedir.stats()})

    elif command == "probe_media":
        from media.inspector import probe
        try:
            result = probe(params["path"])
            # ⚠️ O RESULTADO vai para o log, não só o fato de o comando ter chegado.
            #
            # Custou o bug do MXF OP-Atom (2026-08-14): o app leu `00:00:00:00` de
            # 396 arquivos e empilhou a diária toda no mesmo ponto, e o log da
            # sessão dizia apenas `Comando: probe_media | id=N`, 396 vezes. Uma
            # leitura ERRADA não levanta exceção — ela é bem-sucedida e mente. Sem
            # os fatos lidos, o log registra que o app trabalhou e nada sobre o que
            # ele concluiu, que é justamente o que se precisa saber.
            #
            # `tc_source` vem junto porque um TC errado se parece com um TC certo:
            # o que os separa é a procedência.
            log.info(
                "probe_media: %s | fps=%s tc=%s (%s) tc_sec=%s dur_ms=%s ch=%s",
                os.path.basename(result.get("path") or params["path"]),
                result.get("fps"), result.get("tc_start"), result.get("tc_source"),
                result.get("tc_start_sec"), result.get("duration_ms"),
                result.get("total_audio_channels"),
            )
            respond(cmd_id, result)
        except Exception as e:
            respond_error(cmd_id, "Falha ao ler metadados", str(e))

    elif command == "monitor_window":
        # Proxy H.264 all-intra de um TRECHO, para o monitor tocar formato que o
        # WebView não decodifica (ProRes…) frame-exato, sem VLC. Cacheado.
        # Emite o PID do ffmpeg: o monitor MATA uma janela obsoleta (a agulha andou)
        # por ele, liberando o sidecar serial na hora para a janela atual.
        from media import proxy
        try:
            resolution = params.get("resolution") or app_settings.load()["playback_resolution"]

            def on_window_spawn(pid: int) -> None:
                respond_progress(cmd_id, {"kind": "window", "pid": pid})

            out = proxy.window(
                params["path"],
                float(params["start"]),
                float(params["dur"]),
                resolution,
                chroma=params.get("chroma"),
                on_spawn=on_window_spawn,
            )
            respond(cmd_id, {"path": str(out)})
        except Exception as e:
            respond_error(cmd_id, "Falha ao gerar proxy de vídeo", str(e))

    elif command == "monitor_preview":
        # Proxy do CLIPE INTEIRO com áudio, para a prévia do bin tocar no
        # <video controls> nativo o que o WebView não decodifica (ProRes...).
        # OBSERVÁVEL: emite `fraction` (barra 0-100%) e o `pid` do ffmpeg (por ele o
        # `preview_cancel` do Rust aborta — o sidecar está preso no transcode).
        from media import proxy
        try:
            resolution = params.get("resolution") or app_settings.load()["playback_resolution"]
            dur_ms = params.get("duration_ms")
            duration_s = (float(dur_ms) / 1000.0) if dur_ms else None

            def on_preview_progress(frac: float) -> None:
                respond_progress(cmd_id, {"kind": "preview", "fraction": frac})

            def on_preview_spawn(pid: int) -> None:
                respond_progress(cmd_id, {"kind": "preview", "pid": pid})

            out = proxy.preview(
                params["path"],
                resolution,
                duration_s=duration_s,
                chroma=params.get("chroma"),
                on_progress=on_preview_progress,
                on_spawn=on_preview_spawn,
            )
            respond(cmd_id, {"path": str(out)})
        except Exception as e:
            respond_error(cmd_id, "Falha ao gerar prévia de vídeo", str(e))

    elif command == "monitor_preview_hls_plan":
        # Play PROGRESSIVO da prévia (formatos pesados, ex.: ProRes 4444): planeja os
        # caminhos do HLS ao vivo e diz se já está cacheado. O transcode em si roda no
        # RUST (preview_hls_start) — o sidecar serial não pode responder e seguir
        # trabalhando. Aqui só se calcula/limpa caminho (o cache é dono do Python).
        from media import proxy
        try:
            resolution = params.get("resolution") or app_settings.load()["playback_resolution"]
            respond(cmd_id, proxy.preview_hls_plan(params["path"], resolution))
        except Exception as e:
            respond_error(cmd_id, "Falha ao planejar prévia progressiva", str(e))

    elif command == "monitor_preview_hls_cleanup":
        # Limpa o HLS parcial de uma prévia abortada (chamado ao abortar).
        from media import proxy
        try:
            resolution = params.get("resolution") or app_settings.load()["playback_resolution"]
            proxy.preview_hls_cleanup(params["path"], resolution)
            respond(cmd_id, {"ok": True})
        except Exception as e:
            respond_error(cmd_id, "Falha ao limpar prévia progressiva", str(e))

    # ── Em quantas diárias este RESULTADO se divide? ───────────────────────
    #
    # ⭐ Depois do sync, e não antes. Antes do sync o programa não sabe qual som
    # casa com qual câmera — quem descobre isso é a correlação —, então cortar ali
    # é cortar às cegas, e no material real separou o som da câmera que ele
    # acompanhava. Depois, a TOMADA já existe como unidade e o corte só acontece
    # entre tomadas. Ver `sync/resultsplit.py`.
    elif command == "split_result":
        from sync.resultsplit import needs_split, span_hours, split_daily_result
        from sync.serialize import daily_from_dict
        raw = params.get("result")
        if not raw:
            respond_error(cmd_id, "Nenhum resultado para analisar")
            return
        daily = daily_from_dict(raw)
        respond(cmd_id, {
            "parts": split_daily_result(daily),
            "span_hours": round(span_hours(daily), 2),
            "needs_split": needs_split(daily),
            "warning": daily.span_warning(),
        })

    # ── Quantas diárias há aqui? ───────────────────────────────────────────
    #
    # Roda ANTES do `sync` e não muda o contrato dele: o que sai daqui é o array
    # `groups` que o `sync` já aceitava. Um cliente que nunca chame isto continua
    # funcionando exatamente como antes.
    #
    # Precisa ser Python: a divisão depende de METADADO (o `bext` do BWF, a data no
    # nome), e o Rust não lê metadado nenhum por decisão de arquitetura (ADR 0007).
    elif command == "plan_dailies":
        from sync.dailysplit import plan_dailies
        files = params.get("files") or []
        if not files:
            respond_error(cmd_id, "Nenhum arquivo para analisar")
            return
        # Rota alcançável pelo servidor local → valida antes de tocar em metadado.
        try:
            _validar_caminhos(files)
        except Exception as e:
            from media.safepath import mensagem_publica
            respond_error(cmd_id, mensagem_publica(e))
            return
        respond(cmd_id, plan_dailies(files))

    # ── Fase 2: Sync Engine ────────────────────────────────────────────────
    elif command == "sync":
        # Payload NOVO: `groups: [{id, name, fps, files: [...]}]` — uma diária cada.
        # Payload ANTIGO: `files: [...]` solto (uma diária). Aceito porque uma diária
        # só é o caso comum, e porque o frontend migra num passo separado.
        raw_groups = params.get("groups")
        if raw_groups is None:
            raw_groups = [{
                "id": params.get("name", "MULTICAM"),
                "name": params.get("name", "MULTICAM"),
                "fps": params.get("fps"),
                "files": params.get("files", []),
            }]

        project_name = params.get("project_name") or params.get("name") or "PROJETO"
        start_tc_frames = int(params.get("start_tc_frames") or 0)
        default_fps = params.get("fps")
        sync_method = params.get("sync_method") or "hybrid"

        if not raw_groups or not any(g.get("files") for g in raw_groups):
            respond_error(cmd_id, "Nenhum arquivo para sincronizar")
            return

        # Portão: nenhum "caminho" pode ser uma URL, e todos têm de existir. Sem
        # isto, `http://…` chega ao MediaInfo/ffmpeg e o app sai buscando na rede.
        try:
            for g in raw_groups:
                _validar_caminhos(g.get("files") or [])
        except Exception as e:
            from media.safepath import mensagem_publica
            respond_error(cmd_id, mensagem_publica(e))
            return

        total_groups = len(raw_groups)
        # UM GRUPO QUE FALHA NÃO PODE DERRUBAR OS OUTROS. Antes, um `raise` numa
        # diária matava a resposta inteira — e o usuário perdia o sync das cinco que
        # tinham dado certo. `_sync_one_daily` volta com `error` e as outras seguem.
        results = [
            _sync_one_daily(
                cmd_id, gi, total_groups,
                g.get("id") or g.get("name") or f"grupo-{gi}",
                g.get("name") or g.get("id") or f"grupo-{gi}",
                g.get("files") or [],
                fps=g.get("fps", default_fps),
                start_tc_frames=start_tc_frames,
                sync_method=sync_method,
            )
            for gi, g in enumerate(raw_groups)
            if g.get("files")
        ]

        # Este payload volta tal e qual ao sidecar no export — o frontend é a fonte
        # da verdade, e o que está na tela é o que é exportado.
        respond(cmd_id, {"name": project_name, "groups": results})

    # ── Etapa D: RE-SYNC PARCIAL ─────────────────────────────────────────────
    # Mesma diária, mas só os clipes SELECIONADOS passam pela correlação — o
    # resto entra FIXADO (`pinned`) no offset/som que já estava na tela, e serve
    # de âncora para os que foram selecionados (ver sync.engine.run). Um payload
    # por grupo, igual ao "sync", com dois campos a mais.
    elif command == "resync":
        raw_groups = params.get("groups") or []
        start_tc_frames = int(params.get("start_tc_frames") or 0)
        default_fps = params.get("fps")
        sync_method = params.get("sync_method") or "hybrid"

        if not raw_groups or not any(g.get("files") for g in raw_groups):
            respond_error(cmd_id, "Nenhum arquivo para re-sincronizar")
            return

        total_groups = len(raw_groups)
        results = []
        for gi, g in enumerate(raw_groups):
            gid = g.get("id") or f"grupo-{gi}"
            selected = set(g.get("selected_paths") or [])
            pinned = {
                path: (int(p["offset_frames"]), p["sound_path"])
                for path, p in (g.get("pinned") or {}).items()
            }
            results.append(_sync_one_daily(
                cmd_id, gi, total_groups, gid, g.get("name") or gid,
                g.get("files") or [],
                fps=g.get("fps", default_fps),
                start_tc_frames=start_tc_frames,
                sync_method=sync_method,
                pinned=pinned,
                selected=selected,
            ))

        respond(cmd_id, {"groups": results})

    # ── Waveforms das câmeras (segundo plano, depois do sync) ─────────────
    elif command == "compute_peaks":
        # O sync NÃO gera a waveform de uma câmera cara: para desenhá-la é preciso
        # ler o arquivo INTEIRO (o áudio vive interleavado com o vídeo), e é
        # justamente isso que o caminho rápido existe para evitar — 202 GB numa
        # diária de Alexa. A timeline aparece na hora, com os clipes como blocos, e
        # as waveforms chegam depois, uma a uma, por estes eventos de progresso.
        # É o que o próprio Premiere faz (os arquivos .pek).
        #
        # Cancelar é fechar o processo do lado do frontend: cada peak que já chegou
        # está desenhado, e nada fica pela metade.
        from media import peakcache
        from media.audio import extract_pcm, normalize
        from sync.waveform import PEAK_RATE, peaks_u8
        import base64

        paths = params.get("paths", [])
        if not paths:
            respond(cmd_id, {"count": 0})
            return
        try:
            _validar_caminhos(paths)
        except Exception as e:
            from media.safepath import mensagem_publica
            respond_error(cmd_id, mensagem_publica(e))
            return

        done = 0
        cached = 0
        for path in paths:
            try:
                # O cache em disco é o que impede pagar os 10 minutos de leitura de
                # novo a cada reabertura do app (ver media/peakcache.py).
                peaks = peakcache.load(path)
                if peaks is None:
                    peaks = peaks_u8(normalize(extract_pcm(path)))
                    peakcache.store(path, peaks)
                else:
                    cached += 1
                respond_progress(cmd_id, {
                    "kind": "peaks",
                    "path": path,
                    "peak_rate": PEAK_RATE,
                    "peaks": base64.b64encode(peaks.tobytes()).decode("ascii"),
                })
                done += 1
            except Exception as e:
                # Um arquivo que não abre não pode derrubar os outros: a waveform é
                # exibição, não sync.
                log.warning("peaks falhou em %s: %s", path, e)
                respond_progress(cmd_id, {"kind": "peaks", "path": path, "peaks": None})
        respond(cmd_id, {"count": done, "cached": cached})

    # ── Avid Media Composer ───────────────────────────────────────────────
    #
    # O Avid é o INVERSO dos outros dois: no Premiere e no Resolve um painel
    # dentro do NLE chama o Órbita; aqui o Órbita chama o Media Composer, por
    # gRPC em loopback. Por isso não há "enviar ao plugin" — há "enviar ao Media
    # Composer", e quem monta a timeline é o app. Ver `avid/mcapi.py`.
    elif command == "avid_status":
        from avid.mcapi import MediaComposer, McApiError

        try:
            with MediaComposer(timeout=6.0) as mc:
                info = mc.info()
                proj = mc.projeto()
            respond(cmd_id, {"open": True, "app": info.get("app"),
                             "version": info.get("version"),
                             "project": Path(proj["path"].rstrip("/\\")).name,
                             "project_path": proj["path"]})
        except McApiError as e:
            # Fechado NÃO é erro: é o estado normal antes de o editor abrir o
            # Avid, e a interface precisa disso para acender ou apagar o botão.
            respond(cmd_id, {"open": False, "reason": str(e)})

    elif command == "avid_bins":
        # ⭐ A LISTA DE BINS, como AÇÃO e não como consolo.
        #
        # Ela existia só como efeito colateral do `avid_selection`: quando nada
        # estava marcado no Avid, em vez de "não achei nada" o motor devolvia as
        # bins para escolher. Funcionava, mas amarrava duas coisas diferentes num
        # botão — e o editor que QUERIA escolher bins tinha de primeiro pedir a
        # seleção e acertar não ter nada marcado. Agora é um comando próprio.
        #
        # ⚠️ **A lixeira fica de fora** (`bins()` filtra; ver `esta_na_lixeira`):
        # num projeto real medido, 44% das bins estavam nela.
        from avid.mcapi import MediaComposer, McApiError

        try:
            with MediaComposer() as mc:
                arvore = [mc.chave_de_bin(b) for b in mc.bins()]
                projeto = mc.projeto().get("path") or ""
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return
        # A ordenação de VERDADE é da interface (por tipo, depois A-Z pelo
        # `Intl.Collator` do locale). Esta aqui só garante que a lista não chegue
        # em ordem arbitrária do gRPC.
        respond(cmd_id, {"bins": sorted(arvore, key=str.casefold),
                         "name": Path(projeto.rstrip("/\\")).name if projeto else None})

    elif command == "avid_mobs":
        # ⭐⭐ O ARRASTO: o editor arrasta clipes de uma bin e solta no painel.
        #
        # O Media Composer entrega o que foi arrastado à webview como um MIME
        # customizado (`text/x.avid.mc-api-asset-list+json`), e de lá saem os
        # **MobIDs**. Este comando os transforma em arquivos.
        #
        # ⭐ **Por que isto é melhor que ler a seleção da bin**, que é o que ele
        # substitui:
        #  · a seleção do MC atravessa BINS — clipes esquecidos marcados em outra
        #    bin aberta entravam sem querer, e o editor só descobria pelo resultado;
        #  · o MobID vem DE GRAÇA no payload, sem o piso de ~500 ms por bin que o
        #    `GetListOfBinItems` cobra (e sem depender do `GetListOfWindows`, que
        #    não existe no MC 25.6);
        #  · é gesto DELIBERADO, não estado ambíguo que muda sozinho.
        #
        # ⚠️ O payload NÃO traz o nome do clipe nem a bin de origem (`systemID`/
        # `systemType` são o SISTEMA — `mc-api`/`mediacomposer` —, não a bin). Por
        # isso a fonte aqui não pode ser "a bin", como no `avid_selection`: quem
        # separa as fontes é o ESQUELETO DO NOME, e quem aplica essa regra é o Rust
        # (`fs_expand::classify_paths`, uma regra só, num lugar só). Este comando
        # entrega os arquivos e diz quais são SOM — que é o que o Rust não tem como
        # saber, porque a mídia gerenciada do Avid é toda `.mxf`, som inclusive.
        from avid.masters import e_som, resolver_mobs
        from avid.mcapi import MediaComposer, McApiError

        pedidos = params.get("mob_ids") or []
        if not isinstance(pedidos, list):
            respond_error(cmd_id, "mob_ids inválido")
            return
        # ⚠️ Filtra pela FORMA antes de gastar chamada gRPC: um `type` vazio (é
        # assim que um EFEITO chega) ou um id truncado só descobriria o problema
        # dentro do Media Composer, ~500 ms depois.
        mobs = [m for m in pedidos if mob_id_plausivel(m)]
        if not mobs:
            respond_error(cmd_id, "nenhum clipe reconhecido no que foi arrastado")
            return
        if len(mobs) > MAX_ARQUIVOS_POR_COMANDO:
            respond_error(cmd_id, f"clipes demais num arrasto só "
                                  f"(máximo {MAX_ARQUIVOS_POR_COMANDO})")
            return

        def progresso_mobs(fase, feito, total, mensagem):
            lo, hi = {"masters": (0.0, 0.7), "varredura": (0.7, 1.0)}[fase]
            dentro = (feito / total) if total else 0.0
            respond_progress(cmd_id, {
                "kind": "status", "current": feito, "total": total,
                "message": mensagem,
                "overall": lo + min(1.0, max(0.0, dentro)) * (hi - lo),
            })

        try:
            with MediaComposer() as mc:
                r = resolver_mobs(mc, mobs, on_progress=progresso_mobs)
                projeto = mc.projeto().get("path") or ""
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return

        caminhos, so_audio = r["caminhos"], r["so_audio"]
        # Na ORDEM em que o editor selecionou — é ela que decide qual cartão vem
        # primeiro. `arquivos` e `sound` são listas paralelas ao que o Rust recebe.
        arquivos: list[str] = []
        sonoros: list[str] = []
        for mob in r["ordem"]:
            achados = caminhos.get(mob) or []
            arquivos.extend(achados)
            if achados and e_som(mob, caminhos, so_audio):
                sonoros.extend(achados)

        respond(cmd_id, {
            "files": arquivos,
            # Quais desses arquivos são SOM, decidido pela ESSÊNCIA. Vai à parte
            # porque o Rust classificaria por extensão e chamaria de câmera um
            # gravador de set transcodado em `.mxf`.
            "sound": sonoros,
            "missing": len(r["faltam"]),
            "mob_ids": mapa_arquivo_para_mob(caminhos),
            "mob_names": mapa_arquivo_para_nome(caminhos, r["colunas"]),
            "mob_lengths": r["duracoes"],
            "name": Path(projeto.rstrip("/\\")).name if projeto else None,
        })

    elif command == "avid_selection":
        # AS BINS ESCOLHIDAS VIRAM FONTES. Uma bin = uma fonte, que é como o editor
        # já organizou o material — é a resposta certa para "qual é a CAM A", e a
        # pasta em disco não a tem (a mídia gerenciada mora toda junta em
        # `Avid MediaFiles/MXF/1`).
        #
        # ⭐⭐ **UM MODO SÓ, desde 2026-08-23** (decisão do autor, §1.5 do roadmap).
        # Havia um segundo — sem `bins`, ler os CLIPES MARCADOS no Avid — e ele
        # SAIU. Três razões, nesta ordem:
        #
        #  1. **É impreciso.** A seleção do MC atravessa BINS: um clipe esquecido
        #     marcado noutra bin aberta entrava sem que ninguém pedisse, e o editor
        #     só descobria pelo resultado do sync — longe da causa. Foi por isso que
        #     o painel dentro do MC a abandonou em 18/08 (ver DECISIONS 20ª).
        #  2. **App e painel discordavam** sobre o que é "o material selecionado",
        #     e essa é a discordância mais difícil de explicar para quem usa: a
        #     mesma pergunta, duas respostas, conforme a janela.
        #  3. **É caro.** Sem `GetListOfWindows` (o MC 25.6 não tem), descobrir o
        #     que está marcado obriga a perguntar a TODAS as bins do projeto, a
        #     ~500 ms cada — para na maioria das vezes não achar nada.
        #
        # ⚠️ A escolha das bins é feita no ÓRBITA, e não no Avid, porque **a API não
        # diz quais bins estão marcadas no painel lateral**: `GetBinInfo` não tem
        # esse campo, `GetValues` é um eco de brinquedo, e o `active` de
        # `GetListOfWindows` acompanha o foco do SISTEMA — ele apaga no instante em
        # que a pessoa clica no Órbita, que é justamente quando perguntaríamos.
        #
        # Sem `bins`, devolve a ÁRVORE de bins para quem chamou escolher — que é o
        # que `avid_bins` faz, e continua aqui para não quebrar um chamador antigo.
        from avid.masters import e_som, resolver_mobs
        from avid.mcapi import MediaComposer, McApiError

        pedidas = params.get("bins") or []

        # A barra do painel é UMA só e atravessa a leitura inteira de 0 a 1; cada
        # fase ocupa uma FAIXA fixa dela. Sem isso as três fases mandavam cada uma
        # o seu próprio 0-100% e a barra voltava a zero duas vezes numa leitura —
        # que é exatamente o que o usuário lê como "travou e recomeçou". Mesmo
        # desenho do `_PHASE_BANDS` de `sync/engine.py`, e pela mesma razão.
        #
        # Os tamanhos saem do custo real: cada chamada gRPC ao MC tem piso de
        # ~500 ms, e há uma por bin e uma por master. A primeira fase leva a maior
        # fatia porque é a que paga uma chamada por bin escolhida.
        #
        # ⚠️ A `varredura` é o PLANO B: só roda quando algum original sumiu. Na
        # leitura comum a barra vai até 0,85 e o job a fecha em 1,0 — melhor assim
        # do que reservar espaço para um passo que quase nunca acontece.
        _FAIXAS = {
            "bins":      (0.00, 0.50),   # ler os clipes de cada bin escolhida
            "masters":   (0.50, 0.85),   # uma passada de GetMobInfo por master
            "varredura": (0.85, 1.00),   # plano B: procurar por UMID na mídia do Avid
        }

        def progresso(fase, feito, total, mensagem):
            """Um evento de progresso, com a fração GERAL já mapeada na faixa da fase.

            `current`/`total` continuam sendo da FASE (é o contador que a tela
            mostra); quem move a barra é o `overall` — e é ele que a impede de
            andar para trás na troca de fase.
            """
            lo, hi = _FAIXAS[fase]
            dentro = (feito / total) if total else 0.0
            respond_progress(cmd_id, {
                "kind": "status", "current": feito, "total": total,
                "message": mensagem,
                "overall": lo + min(1.0, max(0.0, dentro)) * (hi - lo),
            })

        try:
            with MediaComposer() as mc:
                def passo(feito, total, nome):
                    progresso("bins", feito, total, f"Lendo {nome}…")

                sel = {}
                if pedidas:
                    # A chave é o caminho RELATIVO sem extensão ("MIDIAS DIA 1/CAM A"):
                    # duas bins podem ter o mesmo nome em pastas diferentes, e o nome
                    # sozinho escolheria a errada em silêncio.
                    #
                    # ⚠️ SEMPRE COM BARRA `/`, porque é assim que a chave foi ENVIADA
                    # para a interface (ver a árvore mais abaixo, que faz o mesmo
                    # `replace`). No Windows `caminho_relativo_da_bin` devolve
                    # contrabarra (`DIARIA 01\CAM A`), então sem normalizar aqui a
                    # chave que volta da tela (`DIARIA 01/CAM A`) não casava com
                    # nenhuma bin: o `get` dava `None`, todas as bins eram puladas, a
                    # seleção saía vazia e a interface reabria o seletor — o "loop"
                    # que parecia a janela não funcionar. Só bins na RAIZ do projeto
                    # escapavam, por não terem separador nenhum.
                    caminhos_bins = {mc.chave_de_bin(b): b for b in mc.bins()}
                    for n, chave in enumerate(pedidas, 1):
                        passo(n, len(pedidas), chave.split("/")[-1])
                        alvo = caminhos_bins.get(chave)
                        if not alvo:
                            continue
                        itens = mc.itens_de(alvo)
                        if itens:
                            # O rótulo da FONTE é o nome da bin; a pasta serve para
                            # escolher, não para nomear a câmera.
                            sel[chave.split("/")[-1]] = itens

                if not sel:
                    # Sem bins pedidas (ou nenhuma delas com clipe): devolver a
                    # ÁRVORE para quem chamou escolher, em vez de um "não achei
                    # nada". Devolve o caminho RELATIVO de cada bin, para o Órbita
                    # desenhar a mesma árvore de pastas que o projeto tem.
                    arvore = [mc.chave_de_bin(b) for b in mc.bins()]
                    respond(cmd_id, {"sources": [], "missing": [], "name": None,
                                     "bins": sorted(arvore, key=str.casefold)})
                    return

                # Daqui para frente o trabalho é o MESMO do arrasto (`avid_mobs`):
                # `GetMobInfo` por master, arquivo de cada um, e o plano B por UMID.
                # Ver `resolver_mobs`.
                itens_todos = [(b, i) for b, its in sel.items() for i in its]
                r = resolver_mobs(mc, [i.mob_id for _b, i in itens_todos],
                                  on_progress=progresso)
                caminhos = r["caminhos"]
                so_audio = r["so_audio"]

                projeto = mc.projeto().get("path") or ""
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return

        # ⭐ AQUI a fonte é a BIN: uma bin = uma fonte, que é como o editor já
        # organizou o material. (No arrasto não há bin no payload, e quem separa as
        # fontes é o esqueleto do nome — ver `avid_mobs`.)
        fontes = []
        for nome_bin, itens in sel.items():
            arquivos = [q for i in itens for q in caminhos.get(i.mob_id, [])]
            if not arquivos:
                continue
            com_arquivo = [i for i in itens if caminhos.get(i.mob_id)]
            som = all(e_som(i.mob_id, caminhos, so_audio) for i in com_arquivo)
            # ⭐ `clipes` = os MASTERS com mídia, que é o que o editor vê na bin. `files` são
            # ARQUIVOS: um master OP-Atom de câmera tem 3 (V + A1 + A2), e contar a lista
            # fazia o Ciclo Assist dizer "a câmera tem 12 clipes e só 4 entraram no sync"
            # numa bin de 4 masters — uma perda que não existe (ensaio M06, 2026-10-31/11-01).
            fontes.append({"label": nome_bin, "kind": "sound" if som else "camera",
                           "files": arquivos, "clipes": len(com_arquivo)})

        nao_achados = [i.name for b, its in sel.items() for i in its
                       if not caminhos.get(i.mob_id)]
        respond(cmd_id, {"sources": fontes, "missing": nao_achados, "bins": [],
                         "mob_ids": mapa_arquivo_para_mob(caminhos),
                         "mob_names": mapa_arquivo_para_nome(caminhos, r["colunas"]),
                         "mob_lengths": r["duracoes"],
                         "name": Path(projeto.rstrip("/\\")).name if projeto else None})

    elif command == "export_avid":
        from avid.adapter import daily_to_avb_segments
        from avid.masters import resolver
        from avid.mcapi import MediaComposer, McApiError
        from avid.writer import AvbWriteError, caminho_de_bin_livre, write_avb
        from sync.serialize import project_from_dict

        result = params.get("result")
        if not result:
            respond_error(cmd_id, "Parâmetro 'result' obrigatório")
            return
        opts = params.get("options") or {}
        inc_cam_audio = bool(opts.get("include_camera_audio"))

        try:
            project = project_from_dict(result)
            if not project.groups:
                respond_error(cmd_id, "Nada para enviar (nenhuma diária).")
                return

            with MediaComposer() as mc:
                pasta = mc.projeto()["path"]
                saidas, nomes = [], []
                for daily in project.groups:
                    segs, _ = daily_to_avb_segments(
                        daily, include_camera_audio=inc_cam_audio)
                    if not segs:
                        continue
                    caminhos = [str(c.path) for g in daily.camera_groups
                                for c in g.cameras] + \
                               [str(s.path) for s in daily.all_sounds]
                    ids, duracoes, faltam = resolver(
                        caminhos, mc, mob_ids=params.get("mob_ids") or {},
                        mob_lengths=params.get("mob_lengths") or {})
                    if faltam:
                        # Um clipe sem master viraria um BURACO na timeline. Melhor
                        # não entregar nada do que entregar uma diária furada em
                        # silêncio — e dizer QUAIS faltaram.
                        amostra = ", ".join(faltam[:4])
                        mais = f" (e mais {len(faltam) - 4})" if len(faltam) > 4 else ""
                        respond_error(
                            cmd_id,
                            f"{len(faltam)} clipe(s) não estão no projeto do Media "
                            f"Composer: {amostra}{mais}. Importe-os antes de enviar.")
                        return

                    seguro = "".join(c if c not in '/\\:*?"<>|' else "_" for c in daily.name)
                    saida = caminho_de_bin_livre(pasta, seguro)
                    write_avb(segs, float(daily.fps or 24.0), saida, daily.name,
                              ids, master_lengths=duracoes)
                    mc.abrir_bin(saida)
                    # ⭐ GRAVAR a bin já, pelo MC: a `.avb` escrita por fora só ganha os
                    # masters no disco quando o Avid a salva (ver `salvar_bin_ativa`), e
                    # até lá o Subclipar recusa ("ainda não foi salva") — pilotado no MC
                    # 24.6 em 2026-10-21, logo depois do Sincronizar. Sem `DoCommand` (24.6)
                    # o Save Bin é recusado e o `CloseBin` grava: fecha e reabre.
                    try:
                        if not mc.salvar_bin_ativa():
                            mc.gravar_bin_fechando(saida)
                    except McApiError as e:
                        log.info("a bin montada não foi gravada pelo MC: %s", e)
                    seqs = mc.itens_da_bin(mc.caminho_relativo_da_bin(saida),
                                           flags=("sequences",))
                    if seqs:
                        # Mostrar o resultado é parte de entregá-lo: o editor volta
                        # ao Avid e a timeline já está no monitor.
                        try:
                            mc.carregar_no_monitor([s.mob_id for s in seqs], "Record")
                        except McApiError:
                            pass          # o monitor é cortesia, não o trabalho
                    saidas.append(saida)
                    nomes.append(daily.name)

            if not saidas:
                respond_error(cmd_id, "Nada para enviar (nenhuma diária com clipes).")
                return
            respond(cmd_id, {"path": saidas[0], "paths": saidas,
                             "count": len(saidas), "names": nomes})
        except (McApiError, AvbWriteError, ValueError) as e:
            respond_error(cmd_id, str(e))
        except Exception as e:
            log.exception("Erro ao enviar ao Media Composer: %s", e)
            respond_error(cmd_id, "Erro ao enviar ao Media Composer", str(e))

    # ── Fase 3: Avid AAF ──────────────────────────────────────────────────
    elif command == "export_aaf":
        respond_error(cmd_id, "Não implementado ainda", "AAF writer — Fase 3")

    # ── Fase 4: Premiere PRPROJ ───────────────────────────────────────────
    # Exporta a partir de um resultado de sync JÁ calculado (o que o frontend
    # tem na timeline). É o caminho normal: não re-sincroniza, então exportar é
    # instantâneo, e o que o usuário vê é exatamente o que é exportado.
    elif command == "export_prproj_from_result":
        from prproj.builder import build_prproj, ExportOptions
        from sync.serialize import project_from_dict

        result = params.get("result")
        output_path_str = params.get("output_path", "")

        if not result:
            respond_error(cmd_id, "Parâmetro 'result' obrigatório")
            return
        if not output_path_str:
            respond_error(cmd_id, "Parâmetro 'output_path' obrigatório")
            return

        try:
            # `project_from_dict` aceita o envelope novo (`{groups: [...]}`) e uma
            # diária solta — o que mantém o caminho antigo funcionando.
            project = project_from_dict(result)
            # As OPÇÕES vêm à parte, e não dentro do resultado do sync: o que foi
            # filmado é uma coisa, o que se quer tirar dele é outra. Trocar uma opção
            # de export não pode obrigar a re-sincronizar.
            opts = params.get("options") or {}
            options = ExportOptions(
                include_camera_audio=bool(opts.get("include_camera_audio")),
                merged_clips=bool(opts.get("merged_clips")),
                premiere_alvo="2023" if opts.get("premiere_alvo") == "2023" else "25",
            )
            out = safepath.ensure_output_path(output_path_str, (".prproj",))
            build_prproj(project, out, options)
            # Os avisos são do PROJETO: com quatro diárias, dizer "3 clipes
            # sinalizados" sem dizer de qual dia não ajudaria ninguém.
            flags = [
                {"path": str(c.path), "group_name": cg.name,
                 "daily_name": d.name, "reason": c.flag_reason}
                for d in project.groups
                for cg in d.camera_groups
                for c in cg.cameras
                if c.flagged
            ]
            respond(cmd_id, {"path": str(out), "name": project.name, "flags": flags})
        except ValueError as e:
            respond_error(cmd_id, str(e))
        except Exception as e:
            log.exception("Erro ao gerar PRPROJ: %s", e)
            respond_error(cmd_id, "Erro ao gerar PRPROJ", str(e))

    # ── DaVinci Resolve: DRT ──────────────────────────────────────────────
    # Mesmo resultado de sync do PRPROJ, outro adapter (drt/). Um .drt = UMA
    # timeline, então uma diária = um arquivo: com várias, grava um .drt por
    # diária ao lado, com o nome dela. Ver drt/adapter.py e o ADR do formato.
    elif command == "export_drt":
        from drt.adapter import build_daily_drt
        from sync.serialize import project_from_dict

        result = params.get("result")
        output_path_str = params.get("output_path", "")
        if not result:
            respond_error(cmd_id, "Parâmetro 'result' obrigatório")
            return
        if not output_path_str:
            respond_error(cmd_id, "Parâmetro 'output_path' obrigatório")
            return

        try:
            project = project_from_dict(result)
            if not project.groups:
                respond_error(cmd_id, "Nada para exportar (nenhuma diária).")
                return
            # Opções à parte do resultado, como no PRPROJ. Só `include_camera_audio`
            # se aplica ao DRT por enquanto (o multicam é do Premiere).
            opts = params.get("options") or {}
            inc_cam_audio = bool(opts.get("include_camera_audio"))
            out = safepath.ensure_output_path(output_path_str, (".drt",))
            outputs: list[str] = []
            if len(project.groups) == 1:
                d = project.groups[0]
                build_daily_drt(d, str(out), include_camera_audio=inc_cam_audio)
                outputs.append(str(out))
            else:
                # Um arquivo por diária: "<base> - <Diária>.drt", no mesmo diretório.
                stem = out.with_suffix("")
                for d in project.groups:
                    safe = "".join(c if c not in '/\\:*?"<>|' else "_" for c in d.name)
                    p = Path(f"{stem} - {safe}.drt")
                    build_daily_drt(d, str(p), include_camera_audio=inc_cam_audio)
                    outputs.append(str(p))
            flags = [
                {"path": str(c.path), "group_name": cg.name,
                 "daily_name": d.name, "reason": c.flag_reason}
                for d in project.groups
                for cg in d.camera_groups
                for c in cg.cameras
                if c.flagged
            ]
            respond(cmd_id, {"path": outputs[0], "paths": outputs,
                             "count": len(outputs), "name": project.name, "flags": flags})
        except ValueError as e:
            respond_error(cmd_id, str(e))
        except Exception as e:
            log.exception("Erro ao gerar DRT: %s", e)
            respond_error(cmd_id, "Erro ao gerar DRT", str(e))

    # LEGADO: sincroniza E exporta numa tacada só. Mantido como fallback e para
    # o caminho do AAF (Fase 3), que ainda não tem fluxo de duas etapas.
    elif command == "export_prproj":
        from sync.engine import run as sync_run
        from prproj.builder import build_prproj

        file_paths = params.get("files", [])
        project_name = params.get("name", "MULTICAM")
        output_path_str = params.get("output_path", "")

        if not file_paths:
            respond_error(cmd_id, "Parâmetro 'files' obrigatório")
            return
        if not output_path_str:
            respond_error(cmd_id, "Parâmetro 'output_path' obrigatório")
            return

        def on_progress_prproj(msg: str, cur: int, tot: int) -> None:
            respond_progress(cmd_id, {"kind": "status", "message": msg, "current": cur, "total": tot})

        try:
            group = sync_run(
                file_paths,
                progress=on_progress_prproj,
                project_name=project_name,
            )
            out = safepath.ensure_output_path(output_path_str, (".prproj",))
            build_prproj(group, out)
            flags = [
                {"path": str(c.path), "group_name": cg.name, "reason": c.flag_reason}
                for cg in group.camera_groups
                for c in cg.cameras
                if c.flagged
            ]
            respond(cmd_id, {"path": str(out), "name": project_name, "flags": flags})
        except ValueError as e:
            respond_error(cmd_id, str(e))
        except Exception as e:
            log.exception("Erro ao gerar PRPROJ: %s", e)
            respond_error(cmd_id, "Erro ao gerar PRPROJ", str(e))

    # ── Renomear em lote, dentro do Media Composer ───────────────────────────
    #
    # ⭐⭐ O contrato de segurança destas duas: `avid_rename_scan` lê e devolve as
    # FICHAS; `avid_name_preview` só desenha. Quem escreve é o `avid_rename_apply`
    # (etapa seguinte), e ele recebe **só o padrão** — nunca a lista de nomes —,
    # recalculando o plano com o mesmo `prever` que desenhou a tela. Sem isso
    # existiria uma janela em que o conferido e o aplicado divergem.
    elif command == "avid_rename_scan":
        from avid.mcapi import MediaComposer, McApiError
        from avid import renomear as _renomear

        pedidos = params.get("mob_ids") or []
        if not isinstance(pedidos, list):
            respond_error(cmd_id, "mob_ids inválido")
            return
        # A mesma peneira de forma do `avid_mobs`, e pela mesma razão: um id
        # truncado só se revelaria dentro do MC, ~500 ms depois.
        mobs = [m for m in pedidos if mob_id_plausivel(m)]
        if not mobs:
            respond_error(cmd_id, "nenhum item reconhecido no que foi arrastado")
            return
        if len(mobs) > MAX_ARQUIVOS_POR_COMANDO:
            respond_error(cmd_id, f"itens demais num arrasto só "
                                  f"(máximo {MAX_ARQUIVOS_POR_COMANDO})")
            return

        respond_progress(cmd_id, {"kind": "status", "current": 0, "total": len(mobs),
                                  "message": "lendo a bin…", "overall": 0.05})
        try:
            with MediaComposer() as mc:
                r = _renomear.levantar(
                    mc, mobs,
                    todas_as_colunas=bool(params.get("todas_as_colunas")))
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return

        # ⚠️ O levantamento fica GUARDADO, e um só. É o que permite ao `apply`
        # receber apenas o padrão: ele recompõe o plano a partir daqui. Um por
        # vez de propósito — é cache de correlação, não estado de sessão, e um
        # dicionário que cresce sem teto num processo de vida longa é vazamento.
        global _ULTIMO_LEVANTAMENTO
        _ULTIMO_LEVANTAMENTO = {"id": cmd_id, "itens": r["itens"],
                                "quando": time.time()}
        respond(cmd_id, {"levantamento_id": cmd_id, **r})

    elif command == "avid_name_preview":
        # ⭐⭐ Uma implementação só da gramática. O espelho colorido da caixa de
        # padrão podia ser calculado no JS — era o plano —, mas aí existiriam duas
        # implementações da mesma regra, e a que divergisse seria a do PREVIEW
        # contra a do APLICAR. Mandando os tokens prontos, o que o editor vê
        # pintado é literalmente o que o motor entendeu.
        #
        # ⚠️ É Python puro sobre dicionários em memória: sem gRPC, sem disco. Por
        # isso a rota que o serve é SÍNCRONA — um job com polling de 500 ms por
        # tecla digitada deixaria a caixa engasgada.
        from nomes import preview as _preview

        fichas = params.get("fichas")
        if not isinstance(fichas, list):
            respond_error(cmd_id, "fichas inválidas")
            return
        respond(cmd_id, _preview.prever(str(params.get("padrao") or ""),
                                        [f if isinstance(f, dict) else {} for f in fichas]))

    elif command == "avid_rename_apply":
        # ⭐⭐ RECEBE SÓ O PADRÃO, nunca a lista de nomes. O plano é recomposto
        # aqui, com o MESMO `prever` que desenhou a tela — não existe janela em
        # que o conferido e o aplicado divirjam.
        from avid.mcapi import MediaComposer, McApiError
        from avid import desfazer as _desfazer
        from avid import renomear as _renomear
        from nomes import preview as _preview

        levantamento = _ULTIMO_LEVANTAMENTO
        pedido = str(params.get("levantamento_id") or "")
        if not levantamento or levantamento.get("id") != pedido:
            respond_error(cmd_id, "o levantamento expirou — solte os clipes de novo")
            return
        # ⛔ Um só levantamento guardado para as duas NLEs: um do Premiere tem chaves
        # `premiere:…`, que o Media Composer não sabe o que são.
        if levantamento.get("nle", "avid") != "avid":
            respond_error(cmd_id, "esta lista veio do Premiere — aplique pelo painel dele")
            return
        itens = levantamento.get("itens") or []
        padrao = str(params.get("padrao") or "")

        previsto = _preview.prever(padrao, [i.get("campos") or {} for i in itens])
        if not itens or previsto["bloqueado"]:
            respond_error(cmd_id, "o padrão não passa na validação — nada foi renomeado")
            return

        plano = [{"mob_id": i["mob_id"], "bin": i.get("bin", ""),
                  "tipos": i.get("tipos") or [],
                  "nome_atual": i.get("nome", ""), "nome_novo": l["nome"]}
                 for i, l in zip(itens, previsto["linhas"])]

        try:
            with MediaComposer() as mc:
                projeto = (mc.projeto() or {}).get("path", "")
                info = mc.info() or {}
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return

        # ⚠️⚠️ O JOURNAL É GRAVADO ANTES DE TOCAR NA BIN, e se ele falhar o
        # trabalho é RECUSADO. Renomear sem poder desfazer, tendo prometido
        # desfazer, é pior que não renomear.
        undo_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{cmd_id}"
        try:
            _desfazer.gravar(id_do_lote=undo_id, projeto=projeto, padrao=padrao,
                             mc_info={"app": info.get("app"),
                                      "version": info.get("version")},
                             itens=plano)
        except OSError as e:
            respond_error(cmd_id, "não deu para registrar o desfazer — nada foi "
                                  "renomeado", str(e))
            return

        def progresso_apply(feito, total, nome):
            respond_progress(cmd_id, {"kind": "status", "current": feito,
                                      "total": total, "message": nome,
                                      "overall": (feito / total) if total else 0.0})

        try:
            with MediaComposer() as mc:
                r = _renomear.aplicar(mc, plano, progresso=progresso_apply)
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return

        _desfazer.atualizar(undo_id, aplicados=r["aplicados"], falhas=r["falhas"],
                            confirmado=r["confirmado"])
        respond(cmd_id, {**r, "undo_id": undo_id})

    elif command == "avid_rename_undo":
        from avid.mcapi import MediaComposer, McApiError
        from avid import desfazer as _desfazer
        from avid import renomear as _renomear

        d = _desfazer.lote(params.get("undo_id") or None)
        if not d:
            respond_error(cmd_id, "não há lote de renomeação para desfazer")
            return
        # ⚠️ Só desfaz O LOTE — não há mais "voltar ao original" por aqui.
        #
        # Havia, e o escopo estava errado do lado de quem usa: o autor renomeou
        # 150 itens, trouxe 5 para a tela, pediu a volta e recebeu os 150. O
        # caminho de volta a nomes ESPECÍFICOS virou o campo `%nome_original`,
        # que se aplica ao que está na tela como qualquer outro padrão. Manter a
        # capacidade aqui, sem ninguém chamando, seria deixar a armadilha pronta
        # para quem viesse depois.
        plano = _desfazer.plano_de_volta(d)

        # ⚠️⚠️ ANTES DE ESCREVER, CONFERE. Se alguém renomeou à mão depois, o item
        # sai em `divergentes` e NÃO é tocado: desfazer por cima apagaria o
        # trabalho de uma pessoa para restaurar o de uma máquina.
        divergentes, a_fazer = [], []
        try:
            with MediaComposer() as mc:
                for item in plano:
                    mob = item["mob_id"]
                    try:
                        agora = (mc.colunas_do_master(mob) or {}).get("Name", "")
                    except McApiError as e:
                        divergentes.append({"mob_id": mob, "nome_esperado":
                                            item["nome_atual"], "nome_no_avid": "",
                                            "erro": str(e)})
                        continue
                    if agora and agora != item["nome_atual"]:
                        divergentes.append({"mob_id": mob,
                                            "nome_esperado": item["nome_atual"],
                                            "nome_no_avid": agora})
                        continue
                    # A bin pode ter mudado desde o lote: pergunta de novo em vez
                    # de confiar no que o journal gravou.
                    atual = mc.bin_do_mob(mob)
                    if atual:
                        item["bin"] = atual
                    a_fazer.append(item)

                def progresso_undo(feito, total, nome):
                    respond_progress(cmd_id, {"kind": "status", "current": feito,
                                              "total": total, "message": nome,
                                              "overall": (feito / total) if total else 0.0})

                # ⭐ O MESMO `aplicar` do caminho de ida: mesma falha por item,
                # mesmo Save Bin por bin, mesma releitura do disco. Uma
                # implementação do "escrever nome em lote", não duas.
                r = _renomear.aplicar(mc, a_fazer, progresso=progresso_undo)
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return

        if r["aplicados"]:
            _desfazer.atualizar(d["id"], revertido=True)
        respond(cmd_id, {"revertidos": r["aplicados"],
                         "inalterados": r["inalterados"],
                         "divergentes": divergentes, "falhas": r["falhas"],
                         "confirmado": r["confirmado"], "id": d["id"]})

    # ── Subclipar: a timeline arrastada vira uma bin de subclipes ────────────
    elif command == "avid_timeline":
        # O MobID que o editor arrastou → a `.avb` que o contém. UMA chamada
        # gRPC, contra os ~500 ms × nº de bins que enumerar o projeto custaria.
        from avid.mcapi import MediaComposer, McApiError

        mob = str(params.get("mob_id") or "").strip()
        if not mob_id_plausivel(mob):
            respond_error(cmd_id, "não reconheci o que foi arrastado como uma timeline")
            return
        try:
            with MediaComposer() as mc:
                caminho = mc.bin_do_mob(mob)
                # ⚠️ As três causas de `None` pedem conselhos DIFERENTES, e dar o
                # errado manda o editor depurar o lugar errado.
                if not caminho:
                    respond_error(cmd_id, "o Media Composer não achou a bin dessa "
                                          "timeline. Ela ainda está aberta no projeto?")
                    return
                # ⭐ O NOME é RÓTULO, e o que identifica a timeline é o CAMINHO —
                # que já temos. Recusar o arrasto porque a coluna `Name` não veio
                # seria trocar o essencial pelo enfeite: o editor arrastaria, não
                # entenderia o erro, e tentaria de novo com o mesmo resultado. O
                # mesmo vale para a pasta do projeto, que é conveniência de tela.
                # (Lição do porte para o Assist anterior, 2026-08-26.)
                nome = ""
                try:
                    nome = (mc.colunas_do_master(mob) or {}).get("Name", "") or ""
                except McApiError:
                    log.info("não consegui o nome da timeline %s", mob)
                projeto = ""
                try:
                    projeto = (mc.projeto() or {}).get("path", "") or ""
                except McApiError:
                    log.info("não consegui a pasta do projeto")
        except McApiError as e:
            respond_error(cmd_id, str(e))
            return
        respond(cmd_id, {"bin": caminho, "nome": nome or "timeline",
                         "pasta_projeto": projeto})

    elif command == "avid_subclips_read":
        from avid import takes as _takes
        from avid import nomear as _nomear
        from media import identidade as _identidade
        from media import memoria_da_producao as _memoria

        caminho = str(params.get("bin") or "").strip()
        if not caminho:
            respond_error(cmd_id, "informe a bin sincronizada")
            return

        respond_progress(cmd_id, {"kind": "status", "current": 0, "total": 1,
                                  "message": "lendo a bin…", "overall": 0.1})
        try:
            colunas, nomes_por_mob = _nomear.contexto_da_bin(caminho)
            regras = _memoria.regras_do_projeto(_memoria.projeto_da_bin(caminho))
            with _identidade.com_regras(regras):
                tomadas, forma = _takes.ler(caminho, colunas=colunas)
        except _takes.BinNaoSalva as e:
            # ⛔ Não é erro nosso: é o asterisco no nome da bin. A mensagem já
            # vem com o Ctrl+S dentro.
            respond_error(cmd_id, str(e))
            return
        except _takes.FormaDesconhecida as e:
            respond_error(cmd_id, str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("falha ao ler a bin de subclipes: %s", e)
            respond_error(cmd_id, "não deu para ler essa bin", str(e))
            return

        global _ULTIMAS_TOMADAS
        _ULTIMAS_TOMADAS = {"id": cmd_id, "tomadas": tomadas, "bin": caminho,
                            "colunas": colunas, "nomes": nomes_por_mob}

        # ⚠️ O CATÁLOGO vai (é o que alimenta as sugestões da caixa de padrão); as
        # FICHAS não. Elas iam, o painel as guardava e as devolvia a cada tecla — e
        # envelheciam ao primeiro `avid_subclips_scene`. Quem as calcula agora é
        # `avid_subclips_preview`, do estado guardado aqui.
        respond(cmd_id, {
            "leitura_id": cmd_id,
            "forma": forma,
            "bin": caminho,
            "tomadas": [_tomada_para_tela(t) for t in tomadas],
            "catalogo": _nomear.catalogo(
                _nomear.fichas(tomadas, colunas, nomes_por_mob)),
        })

    elif command == "avid_subclips_scene":
        # ⭐⭐ A CENA EDITADA À MÃO, em LOTE — pedido do autor, 2026-09-05:
        #
        # > *"A coluna CENA deve ser editável, pois caso o programa não
        # > identifique, o usuário pode colocar o valor manualmente. É importante
        # > que ele possa fazer a alteração em lote: seleciona todos os subclipes
        # > da lista que quer adicionar a cena e só escreve uma vez."*
        #
        # ⚠️ Escreve na LEITURA guardada, não na bin: o que o editor corrige aqui
        # vale para os subclipes que ele vai gerar. A bin de origem é dele, e
        # mexer nela seria fazer mais do que ele pediu.
        from dataclasses import replace

        leitura = _ULTIMAS_TOMADAS
        if not leitura or leitura.get("id") != str(params.get("leitura_id") or ""):
            respond_error(cmd_id, "a leitura expirou — arraste a timeline de novo")
            return

        alvos = params.get("indices")
        cena = str(params.get("cena") or "").strip()
        if not isinstance(alvos, list) or not alvos:
            respond_error(cmd_id, "escolha ao menos uma tomada")
            return

        tomadas = list(leitura["tomadas"])
        mexidos = 0
        for i in alvos:
            if not isinstance(i, int) or not (0 <= i < len(tomadas)):
                continue
            # ⚠️ `convencao="manual"` para a tela poder DIZER que a cena foi
            # digitada — pela mesma razão que "presumida" existe: o editor tem de
            # distinguir o que foi lido do que foi posto à mão.
            tomadas[i] = replace(tomadas[i], cena=cena or None,
                                 convencao="manual" if cena else None)
            mexidos += 1

        leitura["tomadas"] = tomadas
        respond(cmd_id, {"alteradas": mexidos,
                         "tomadas": [_tomada_para_tela(t) for t in tomadas]})

    elif command == "avid_subclips_preview":
        # ⭐⭐ O PREVIEW DO SUBCLIPAR VEM DA LEITURA GUARDADA, não das fichas que o
        # painel carrega — e essa diferença é o conserto de um defeito real.
        #
        # ⛔ Antes o painel mandava as `fichas` que recebeu na leitura, e elas
        # ficavam VELHAS: `avid_subclips_scene` devolvia as tomadas com a cena
        # nova e as fichas com a antiga. A tela desenhava `C25-1_T01` e a bin
        # recebia `C25_T02`. O autor viu em 2026-09-06, e notou que só depois de
        # remover itens (que devolve fichas) a tela se corrigia.
        #
        # ⭐ Aqui não há como envelhecer: as fichas são recalculadas do estado que
        # o próprio sidecar guarda, que é o mesmo estado que a escrita vai usar.
        # E o padrão viaja sozinho — a lista inteira deixou de subir a cada tecla.
        from avid import nomear as _nomear

        leitura = _ULTIMAS_TOMADAS
        if not leitura or leitura.get("id") != str(params.get("leitura_id") or ""):
            respond_error(cmd_id, "a leitura expirou — arraste a timeline de novo")
            return
        respond(cmd_id, _nomear.prever(leitura["tomadas"],
                                       str(params.get("padrao") or ""),
                                       leitura["colunas"], leitura["nomes"]))

    elif command == "avid_subclips_drop":
        # ⭐ Tirar tomadas da lista — pedido do autor: *"devemos poder remover
        # subclipes da seleção, com um X à direita, assim como podemos remover
        # clipes do sync, e um botão limpar lista"*.
        #
        # ⚠️ Hoje só se reseta dando refresh no painel, *"ação que não é típica
        # para o usuário"*.
        leitura = _ULTIMAS_TOMADAS
        if not leitura or leitura.get("id") != str(params.get("leitura_id") or ""):
            respond_error(cmd_id, "a leitura expirou — arraste a timeline de novo")
            return

        if params.get("tudo"):
            leitura["tomadas"] = []
        else:
            alvos = {i for i in (params.get("indices") or []) if isinstance(i, int)}
            leitura["tomadas"] = [t for n, t in enumerate(leitura["tomadas"])
                                  if n not in alvos]

        respond(cmd_id, {"tomadas": [_tomada_para_tela(t) for t in leitura["tomadas"]]})

    elif command == "avid_subclips_write":
        from avid.mcapi import MediaComposer, McApiError
        from avid import cenas as _cenas
        from avid import nomear as _nomear
        from avid import subclipes as _subclipes
        from avid.writer import caminho_de_bin_livre

        leitura = _ULTIMAS_TOMADAS
        if not leitura or leitura.get("id") != str(params.get("leitura_id") or ""):
            respond_error(cmd_id, "a leitura expirou — arraste a timeline de novo")
            return

        # ⛔ A leitura guardada é UMA para as duas NLEs (preview, cena e remover a
        # servem igual). Escrever `.avb` a partir de uma sequência do Premiere
        # produziria uma bin apontando para "mob_ids" que são caminhos de arquivo.
        if leitura.get("nle", "avid") != "avid":
            respond_error(cmd_id, "esta lista veio do Premiere — gere pelo painel dele")
            return

        tomadas = leitura["tomadas"]
        padrao = str(params.get("padrao") or "") or _nomear.PADRAO
        try:
            tomadas = _nomear.aplicar(tomadas, padrao, leitura["colunas"],
                                      leitura["nomes"])
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return

        origem = Path(leitura["bin"])
        por_cena = bool(params.get("por_cena"))
        # ⭐ O nome que o editor PEDIU (Ciclo Assist, 2026-11-01: "uma bin chamada
        # subclipes" saía `D01 SUBCLIPES`). Por cena, é o nome da PASTA. Vazio = o de sempre.
        # ⛔ Só o NOME: barra ou `..` viraria caminho fora do projeto.
        nome = str(params.get("nome") or "").strip()
        if nome and (any(c in nome for c in r'\/:*?"<>|') or nome in (".", "..")):
            respond_error(cmd_id, f"nome de bin inválido: {nome!r}")
            return
        try:
            if por_cena:
                pasta = origem.parent / (nome or "CENAS")
                r = _cenas.escrever(tomadas, str(pasta))
                caminhos = [b["caminho"] for b in r.get("bins", [])]
            else:
                saida = caminho_de_bin_livre(origem.parent, nome or f"{origem.stem} SUBCLIPES")
                r = _subclipes.autorar(tomadas, saida)
                caminhos = [r["saida"]]
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("falha ao autorar subclipes: %s", e)
            respond_error(cmd_id, "não deu para escrever a bin de subclipes", str(e))
            return

        # ⚠️ Abrir no Avid é CORTESIA, e falhar aqui não desfaz o trabalho: as
        # bins estão no disco de qualquer jeito. Por isso a exceção é engolida e
        # o resultado diz se abriu.
        abriu = False
        try:
            with MediaComposer() as mc:
                for c in caminhos:
                    mc.abrir_bin(c)
                    # Gravada pelo MC na hora, como a bin do Sincronizar (`export_avid`):
                    # sem isso ela nasce com asterisco e os masters fora do disco.
                    try:
                        if not mc.salvar_bin_ativa():
                            mc.gravar_bin_fechando(c)
                    except McApiError as e:
                        log.info("a bin de subclipes não foi gravada pelo MC: %s", e)
                abriu = True
        except McApiError as e:
            log.info("as bins foram escritas, mas o MC não as abriu: %s", e)

        respond(cmd_id, {**r, "caminhos": caminhos, "aberta": abriu})

    # ── Premiere: a sequência ativa vira a lista de merged clips ─────────────
    elif command == "premiere_merged_read":
        # ⭐ Guarda a leitura NO MESMO LUGAR e no mesmo formato do Subclipar do Avid:
        # `avid_subclips_preview`/`_scene`/`_drop` só mexem nas `Tomada` guardadas, e
        # servem às duas NLEs sem mudar uma linha. O que difere é ler e escrever.
        #
        # ⚠️ Pura aritmética sobre o texto que o host mandou — sem disco, sem probe.
        from avid import nomear as _nomear
        from media import identidade as _identidade
        from media import memoria_da_producao as _memoria
        from premiere import tomadas as _ptomadas

        registros = params.get("registros")
        if not isinstance(registros, str) or not registros.strip():
            respond_error(cmd_id, "a sequência ativa veio vazia")
            return
        try:
            fps = float(params.get("fps") or 0)
        except (TypeError, ValueError):
            fps = 0.0
        colunas = params.get("colunas") or {}
        if not isinstance(colunas, dict):
            colunas = {}
        colunas = {str(k): v for k, v in colunas.items() if isinstance(v, dict)}

        itens = _ptomadas.ler_registros(registros)
        colunas = _ptomadas.completar_colunas(itens, colunas)
        if len(itens) > MAX_ARQUIVOS_POR_COMANDO * 20:
            respond_error(cmd_id, "sequência grande demais para ler de uma vez")
            return
        try:
            with _identidade.com_regras(_memoria.regras_do_projeto(str(params.get("projeto") or ""))):
                pares, resumo = _ptomadas.pares(
                    itens, fps, colunas=colunas,
                    so_selecionados=bool(params.get("so_selecionados")))
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return

        tomadas = [p.tomada for p in pares]
        nomes = _ptomadas.nomes_por_caminho(pares)
        # (o `global _ULTIMAS_TOMADAS` já foi declarado no `avid_subclips_read`, e
        # vale para a função inteira — repeti-lo aqui é SyntaxError)
        _ULTIMAS_TOMADAS = {"id": cmd_id, "nle": "premiere", "tomadas": tomadas,
                            "bin": "", "colunas": colunas, "nomes": nomes}
        respond(cmd_id, {
            "leitura_id": cmd_id,
            "resumo": resumo,
            "tomadas": [_tomada_para_tela(t) for t in tomadas],
            "catalogo": _nomear.catalogo(_nomear.fichas(tomadas, colunas, nomes)),
        })

    elif command == "premiere_merged_write":
        # ⭐ Como no Avid: recebe só o padrão; os nomes saem do MESMO `nomear.aplicar`
        # que desenhou a tela. O caminho de saída vem do Rust (temporário higienizado).
        #
        # ⚠️ Marcadores de tempo por passo: no app o comando levou 15 s e a escrita em
        # si 0,17 s (2026-09-17); fora do app, 1,6 s. O log tem de dizer ONDE.
        _t = [time.perf_counter()]

        def _marca(passo):
            agora = time.perf_counter()
            log.info("merged/tempo: %s %.2f s", passo, agora - _t[0])
            _t[0] = agora

        from avid import nomear as _nomear
        from media import safepath
        from premiere import escrita as _pescrita
        _marca("imports")

        leitura = _ULTIMAS_TOMADAS
        if not leitura or leitura.get("id") != str(params.get("leitura_id") or ""):
            respond_error(cmd_id, "a leitura expirou — leia a sequência de novo")
            return
        if leitura.get("nle") != "premiere":
            respond_error(cmd_id, "esta lista veio do Media Composer")
            return
        if not leitura["tomadas"]:
            respond_error(cmd_id, "a lista está vazia")
            return
        try:
            out = safepath.ensure_output_path(str(params.get("output_path") or ""),
                                              (".prproj",))
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return
        _marca("caminho")

        padrao = str(params.get("padrao") or "") or _nomear.PADRAO
        try:
            tomadas = _nomear.aplicar(leitura["tomadas"], padrao, leitura["colunas"],
                                      leitura["nomes"])
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return

        _marca("nomes")
        nome_da_bin = str(params.get("bin") or "").strip() or "MERGED"
        alvo = "2023" if params.get("premiere_alvo") == "2023" else "25"
        respond_progress(cmd_id, {"kind": "status", "current": 0,
                                  "total": len(tomadas), "message": "lendo a mídia…",
                                  "overall": 0.2})
        _marca("progresso")
        try:
            r = _pescrita.escrever(tomadas, float(tomadas[0].edit_rate), out,
                                   nome_da_bin, alvo=alvo)
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("falha ao escrever os merged: %s", e)
            respond_error(cmd_id, "não deu para escrever os merged clips", str(e))
            return
        respond(cmd_id, r)

    elif command == "premiere_merged_from_sync":
        # ⭐ A rota `POST /api/v1/merge` (Ciclo Assist, P4): do RESULTADO DO SYNC aos
        # merged em bins por cena, com o proxy conferido anexado. Quem importa é o
        # painel (`sincImportMerged`); aqui só se escreve o arquivo.
        from prproj.builder import build_merged_por_cena, ExportOptions
        from media import safepath
        from premiere import merged_cenas
        from sync.serialize import project_from_dict

        result = params.get("result")
        if not isinstance(result, dict):
            respond_error(cmd_id, "faltou o resultado do sync")
            return
        try:
            out = safepath.ensure_output_path(str(params.get("output_path") or ""),
                                              (".prproj",))
            project = project_from_dict(result)
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return
        proxies = params.get("proxies") if isinstance(params.get("proxies"), dict) else {}
        falta = merged_cenas.anexar_proxies(project, proxies)
        raiz = str(params.get("raiz") or "").strip() or "CENAS"
        if any(c in raiz for c in r'\/:*?"<>|'):
            respond_error(cmd_id, f"nome de bin inválido: {raiz!r}")
            return
        alvo = "2023" if params.get("premiere_alvo") == "2023" else "25"
        try:
            bins = build_merged_por_cena(project, out, raiz,
                                         ExportOptions(merged_clips=True, premiere_alvo=alvo))
        except ValueError as e:
            respond_error(cmd_id, str(e))
            return
        except Exception as e:  # noqa: BLE001
            log.exception("falha ao escrever os merged do sync: %s", e)
            respond_error(cmd_id, "não deu para escrever os merged clips", str(e))
            return
        com_proxy = sum(1 for d in project.groups for t in d.takes if t.sound
                        for c in t.cameras if c.proxy_path)
        respond(cmd_id, {"arquivo": str(out), "raiz": raiz, "bins": bins,
                         "merged": sum(bins.values()), "com_proxy": com_proxy, **falta})

    # ── Premiere: a aba Renomear ─────────────────────────────────────────────
    # ⭐ Quem ESCREVE é o painel (ExtendScript). O sidecar lê as fichas, desenha a
    # prévia (a rota genérica `/avid/nome/prever`), monta o plano com o MESMO
    # `prever`, grava o journal ANTES de o painel tocar em nada, e registra o
    # resultado que o painel devolve.
    elif command == "premiere_rename_scan":
        from premiere import renomear as _prenomear

        itens = params.get("itens")
        projeto = str(params.get("projeto") or "")
        if not isinstance(itens, list) or not itens:
            respond_error(cmd_id, "nada selecionado na bin")
            return
        if len(itens) > MAX_ARQUIVOS_POR_COMANDO:
            respond_error(cmd_id, f"itens demais de uma vez (máximo {MAX_ARQUIVOS_POR_COMANDO})")
            return
        r = _prenomear.levantar(projeto, itens)
        # (o `global` já foi declarado no `avid_rename_scan` e vale para a função toda)
        _ULTIMO_LEVANTAMENTO = {"id": cmd_id, "nle": "premiere", "projeto": projeto,
                                "itens": r["itens"], "quando": time.time()}
        respond(cmd_id, {"levantamento_id": cmd_id, **r})

    elif command == "premiere_rename_plan":
        from avid import desfazer as _desfazer
        from nomes import preview as _preview
        from premiere import renomear as _prenomear

        levantamento = _ULTIMO_LEVANTAMENTO
        if (not levantamento or levantamento.get("nle") != "premiere"
                or levantamento.get("id") != str(params.get("levantamento_id") or "")):
            respond_error(cmd_id, "a leitura expirou — leia a seleção de novo")
            return
        itens = levantamento.get("itens") or []
        # O painel pode ter tirado itens da lista: ele manda os ÍNDICES que ficaram.
        quais = params.get("indices")
        if isinstance(quais, list):
            itens = [itens[i] for i in quais if isinstance(i, int) and 0 <= i < len(itens)]
        padrao = str(params.get("padrao") or "")
        previsto = _preview.prever(padrao, [i.get("campos") or {} for i in itens])
        if not itens or previsto["bloqueado"]:
            respond_error(cmd_id, "o padrão não passa na validação — nada foi renomeado")
            return
        plano = [{"mob_id": i["mob_id"], "bin": "", "tipos": i.get("tipos") or [],
                  "nome_atual": i.get("nome", ""), "nome_novo": l["nome"]}
                 for i, l in zip(itens, previsto["linhas"])]
        undo_id = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + f"-{cmd_id}"
        try:
            _desfazer.gravar(id_do_lote=undo_id, projeto=levantamento.get("projeto", ""),
                             padrao=padrao, nle="premiere",
                             mc_info={"app": "Premiere",
                                      "version": str(params.get("versao") or "")},
                             itens=plano)
        except OSError as e:
            respond_error(cmd_id, "não deu para registrar o desfazer — nada foi "
                                  "renomeado", str(e))
            return
        respond(cmd_id, {"undo_id": undo_id, "plano": [
            {"node_id": _prenomear.node_de(p["mob_id"]), "nome_atual": p["nome_atual"],
             "nome_novo": p["nome_novo"]} for p in plano]})

    elif command == "premiere_rename_undo":
        # O plano de volta do último lote do Premiere NESTE projeto. Quem confere se
        # alguém renomeou por cima (e não toca nesse item) é o painel, que lê o nome
        # de agora antes de escrever.
        from avid import desfazer as _desfazer
        from premiere import renomear as _prenomear

        d = _desfazer.lote(None, nle="premiere", projeto=str(params.get("projeto") or ""))
        if not d:
            respond_error(cmd_id, "não há lote de renomeação para desfazer neste projeto")
            return
        respond(cmd_id, {"undo_id": d["id"], "plano": [
            {"node_id": _prenomear.node_de(p["mob_id"]), "nome_atual": p["nome_atual"],
             "nome_novo": p["nome_novo"]} for p in _desfazer.plano_de_volta(d)]})

    elif command == "premiere_rename_done":
        from avid import desfazer as _desfazer

        undo_id = str(params.get("undo_id") or "")
        if not undo_id:
            respond_error(cmd_id, "faltou undo_id")
            return
        campos = {"falhas": params.get("falhas") or []}
        aplicados = int(params.get("aplicados") or 0)
        if params.get("desfeito"):
            if aplicados:
                campos["revertido"] = True
        else:
            campos["aplicados"] = aplicados
        _desfazer.atualizar(undo_id, **campos)
        respond(cmd_id, {"ok": True})

    elif command == "avid_rename_history":
        # Só lê o journal — não fala com o Media Composer.
        from avid import desfazer as _desfazer

        respond(cmd_id, {"lotes": _desfazer.historico()})

    else:
        respond_error(cmd_id, f"Comando desconhecido: {command}")


def main() -> None:
    log.info("Sincronizar: motor iniciado. Aguardando comandos via stdin...")
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            if not line.strip():
                continue      # linha em branco não é comando
            # ⛔ TETO DE LINHA antes do `loads`. Sem ele, uma linha gigante já custa
            # a memória só de chegar até aqui — e o teto do lado do Rust
            # (`MAX_BODY_BYTES`) não cobre este transporte, que é o pipe do sidecar.
            if len(line) > MAX_LINHA_BYTES:
                log.error("Linha de comando grande demais (%d bytes) — descartada",
                          len(line))
                respond_error("parse_error", "Comando grande demais")
                continue
            cmd = json.loads(line)
        # ⚠️ `RecursionError` NÃO é subclasse de `JSONDecodeError`, e um payload
        # `[[[[…]]]]` com dezenas de milhares de níveis levanta exatamente isso.
        # Antes ele escapava deste `except`, escapava do `for line in sys.stdin` e
        # **matava o sidecar inteiro** — sem sync, sem probe, sem export, e sem nem
        # a linha de log abaixo para dizer por quê. Achado na auditoria de
        # 2026-08-23. `ValueError` entra junto porque é a família do `loads`.
        except (json.JSONDecodeError, RecursionError, ValueError) as e:
            log.error("JSON inválido: %s | %s", line[:100], e)
            respond_error("parse_error", "JSON inválido", str(e))
            continue
        try:
            # ⏱️ O FECHAMENTO de cada comando, com o tempo. A abertura já era
            # registrada (`Comando: %s | id=%s`), e só ela deixava um buraco
            # característico: um comando que demora e não volta fica idêntico, no
            # log, a um comando que voltou rápido — porque o que sobra dos dois é a
            # mesma linha de abertura. Num relato de campo, "travou" e "demorou 90 s"
            # são hipóteses diferentes, e separá-las é o mínimo que o log tem de dar.
            _t = time.perf_counter()
            handle_command(cmd)
            log.info("Comando: %s | id=%s | fim em %.2f s",
                     cmd.get("command", ""), cmd.get("id", "unknown"),
                     time.perf_counter() - _t)
        except Exception as e:
            cmd_id = cmd.get("id", "unknown")
            log.exception("Erro inesperado no comando %s: %s", cmd_id, e)
            try:
                # ⚠️ O TEXTO DA EXCEÇÃO NÃO VAI PARA O CLIENTE. Ele quase sempre
                # carrega o caminho absoluto do arquivo que falhou — e este erro
                # sobe até o servidor HTTP, que devolve o JSON a quem chamou. Medido
                # nesta rota: pedir `/etc/passwd` respondia
                # `Erro interno inesperado: file:/private/etc/passwd`, o que entrega
                # o nome de usuário do sistema e, pela DIFERENÇA entre esta mensagem
                # e "arquivo não encontrado", confirma o que existe no disco.
                # O detalhe completo (com stack) já foi para o log em disco na linha
                # acima — que é do dono da máquina, não de quem fez a requisição.
                respond_error(cmd_id, "Erro interno inesperado")
            except OSError:
                # stdout ainda indisponível mesmo após o retry de _write_line —
                # não deixar isso matar o processo inteiro (ver _write_line). O
                # Rust vai estourar o timeout do comando em vez de crashar o
                # sidecar; a próxima linha de stdin ainda tem chance de ir.
                log.critical(
                    "stdout indisponível — não foi possível responder ao comando %s.",
                    cmd_id,
                )

    log.info("Sincronizar: motor encerrado.")


if __name__ == "__main__":
    main()
