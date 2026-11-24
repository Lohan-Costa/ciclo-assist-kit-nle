"""As colunas dos cards da aba Sincronizar: o que cada clipe É, e o que há de estranho no TC deles.

Plano `docs/plano/2026-11-08-aba-sincronizar.md`. `POST /midia/fichas` lê um lote pequeno por vez (o card se preenche aos
poucos, sem travar o arrasto) e `POST /midia/analise` diz, com as fichas já lidas, quais linhas são um take só de som
monofônico e quais têm conflito de TC. ⭐ A análise mora aqui, e não no JavaScript, por ser a parte que tem conta: o
card tira um item e pergunta de novo, e o custo é uma ida ao localhost.

⛔ Um CLIPE não é um arquivo: no Media Composer um master é um `.mxf` por trilha. O clipe chega com os arquivos dele, a
imagem manda no TC da câmera e os canais são a soma de todos.
⛔ O sondador vai direto ao `inspector.probe`, FORA da trava do motor: sondar durante um sync não pode esperar o sync
acabar (a trava é de um comando por vez, e o sync dura minutos). O `probe` é cacheado em disco e não mexe em estado do motor.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Optional

#: O teto de um lote: um pedido pequeno volta logo e o card anda.
MAXIMO_POR_LOTE = 32
#: Áudio não tem quadro: dois milissegundos cobrem o arredondamento da duração que o MediaInfo devolve.
TOLERANCIA_SOM_S = 0.002

SOBREPOSTO, ZERADO, CONTINUO = "sobreposto", "zerado", "continuo"


def _sondar_de_verdade(caminho: str) -> dict:
    import motor
    motor.carregar()
    from media import inspector  # o motor é uma raiz Python própria, carregada acima
    return inspector.probe(caminho)


def _tc_em_segundos(tc: str, fps: float, drop: bool) -> Optional[float]:
    import motor
    motor.carregar()
    from sync.tcmatch import tc_to_real_seconds
    return tc_to_real_seconds(tc, fps, drop)


def texto_da_duracao(ms: Optional[float], fps: Optional[float]) -> Optional[str]:
    """`00:01:23:12` com taxa, `00:01:23` sem ela (o áudio solto não tem quadro)."""
    if ms is None:
        return None
    total_s = ms / 1000.0
    h, m, s = int(total_s // 3600), int(total_s // 60) % 60, int(total_s) % 60
    if not fps:
        return f"{h:02d}:{m:02d}:{s:02d}"
    q = int((total_s - int(total_s)) * fps + 0.5)
    return f"{h:02d}:{m:02d}:{s:02d}:{min(q, round(fps) - 1):02d}"


def _claquete_do_nome(nome: str):
    import motor
    motor.carregar()
    from media import claquete
    return claquete.ler(nome)


def _com_tc_zerado(tc: Optional[str]) -> bool:
    return bool(tc) and not re.sub(r"[0:;.]", "", tc)


def ficha_da_camera(leituras: list[dict], tc_em_segundos: Callable = _tc_em_segundos) -> dict:
    imagem = next((m for m in leituras if m.get("width")), leituras[0])
    fps = imagem.get("fps")
    tc = imagem.get("tc_start")
    quadros = imagem.get("frame_count")
    ms = imagem.get("duration_ms")
    duracao_s = quadros / fps if (quadros and fps) else (ms / 1000.0 if ms else None)
    inicio = tc_em_segundos(tc, fps, bool(imagem.get("tc_drop_frame"))) if (tc and fps) else None
    largura, altura = imagem.get("width"), imagem.get("height")
    return {
        "tc": tc, "inicio_s": inicio,
        "fim_s": inicio + duracao_s if (inicio is not None and duracao_s) else None,
        "tol_s": 0.5 / fps if fps else TOLERANCIA_SOM_S,
        "zerado": _com_tc_zerado(tc),
        "duracao_ms": duracao_s * 1000.0 if duracao_s else None,
        "duracao": texto_da_duracao(duracao_s * 1000.0 if duracao_s else None, fps),
        "fps": fps,
        "largura": largura, "altura": altura,
        "resolucao": f"{largura}×{altura}" if (largura and altura) else None,
        "codec": imagem.get("codec_label"),
        "canais": sum(int(m.get("total_audio_channels") or 0) for m in leituras),
    }


def ficha_do_som(leituras: list[dict], nome: str = "", ler_nome: Callable = _claquete_do_nome) -> dict:
    """⭐ Cena, plano e take saem do NOME, pela mesma leitura do resto do programa (`media/claquete.py`): a tag que o ffprobe
    lê é a do `bext`, e no Zoom F8 do *PRODUCAO-A* ela só guarda o nome da produção (a cena e o plano estão no iXML). Sem claquete no nome, vale o que a tag traz,
    como está; plano fica vazio. `nome` é o do clipe que o editor vê: no Media Composer o arquivo é um `.mxf` ilegível."""
    lida = ler_nome(nome) if nome else None
    base = next((m for m in leituras if m.get("tc_start_sec") is not None), leituras[0])
    inicio = base.get("tc_start_sec")
    ms = base.get("duration_ms")
    return {
        "tc": None,  # quem escreve o TC do som é o card: a taxa de exibição é a da câmera que está ao lado
        "tc_fps": base.get("tc_sec_fps"),
        "inicio_s": inicio,
        "fim_s": inicio + ms / 1000.0 if (inicio is not None and ms) else None,
        "tol_s": TOLERANCIA_SOM_S,
        "zerado": inicio == 0,
        "duracao_ms": ms,
        "duracao": texto_da_duracao(ms, None),
        "cena": (f"{getattr(lida, 'episodio', '')} {lida.cena}".strip() if lida else (base.get("scene") or None)),
        "plano": lida.plano if lida else None,
        "take": lida.take if lida else (base.get("take") or None),
        "canais": sum(int(m.get("total_audio_channels") or m.get("channels") or 0) for m in leituras),
    }


def _leitor_do_projeto(projeto: str) -> Callable:
    """Como ler o nome neste projeto: a regra da memória da produção primeiro, a claquete depois."""
    if not projeto:
        return _claquete_do_nome
    import motor
    motor.carregar()
    from types import SimpleNamespace

    from media import memoria_da_producao as memoria
    regras = memoria.regras_do_projeto(projeto)

    def ler(nome: str):
        d = memoria.aplicar(regras, nome)
        return SimpleNamespace(cena=d["cena"], plano=d["plano"], take=d["take"], episodio=d["episodio"] or "") if d else _claquete_do_nome(nome)
    return ler


def ficha(clipe: dict, sondar: Callable[[str], dict] = _sondar_de_verdade,
          tc_em_segundos: Callable = _tc_em_segundos, ler_nome: Callable = _claquete_do_nome) -> dict:
    """`{id, arquivos, tipo}` → a ficha da linha. Um arquivo ilegível não derruba o lote: a linha sai com `erro`."""
    resposta = {"id": clipe["id"]}
    try:
        leituras = [sondar(c) for c in clipe["arquivos"]]
        resposta.update(ficha_do_som(leituras, str(clipe.get("nome") or Path(clipe["arquivos"][0]).name), ler_nome)
                        if clipe.get("tipo") == "sound"
                        else ficha_da_camera(leituras, tc_em_segundos))
    except Exception as e:  # o `probe` levanta o que o MediaInfo levantar, e a linha só precisa dizer que não leu
        resposta["erro"] = str(e)
    return resposta


def rota_fichas(corpo: dict, sondar: Callable[[str], dict] = _sondar_de_verdade) -> tuple[int, dict]:
    clipes = corpo.get("clipes")
    if not isinstance(clipes, list):
        return 400, {"error": "faltaram clipes"}
    if len(clipes) > MAXIMO_POR_LOTE:
        return 400, {"error": f"no máximo {MAXIMO_POR_LOTE} clipes por pedido"}
    validos = [c for c in clipes if isinstance(c, dict) and isinstance(c.get("id"), str)
               and isinstance(c.get("arquivos"), list) and c["arquivos"]
               and all(isinstance(a, str) for a in c["arquivos"])]
    if len(validos) != len(clipes):
        return 400, {"error": "clipe sem id ou sem arquivos"}
    projeto = corpo.get("projeto")
    ler_nome = _leitor_do_projeto(projeto if isinstance(projeto, str) else "")
    return 200, {"fichas": [ficha(c, sondar, ler_nome=ler_nome) for c in validos]}


def _sem_o_canal(caminho: str) -> str:
    """O nome sem o último número (`T012_3` → `t012_`): quem separa canais de um take pelo sufixo."""
    return re.sub(r"\d+$", "", Path(caminho).stem).lower()


def grupos_monofonicos(fichas: list[dict]) -> list[list[str]]:
    """Os `.wav` de um canal cada do MESMO take: mesmo TC e mesma duração, dois ou mais.

    ⛔ TC zerado sozinho não prova nada (metade da diária pode ter zero): aí o nome também tem de bater."""
    baldes: dict[tuple, list[str]] = {}
    for f in fichas:
        if f.get("canais") != 1 or f.get("inicio_s") is None or f.get("duracao_ms") is None:
            continue
        extra = _sem_o_canal(f.get("nome") or "") if f.get("zerado") else ""
        baldes.setdefault((round(f["inicio_s"], 3), round(f["duracao_ms"]), extra), []).append(f["id"])
    return [ids for ids in baldes.values() if len(ids) >= 2]


def conflitos(fichas: list[dict], grupos: list[list[str]]) -> dict[str, list[str]]:
    """`{id: [tipos]}` só dos que têm conflito. ⛔ Os grupos monofônicos entram como UMA linha: eles se sobrepõem por
    natureza, e isso não é conflito."""
    no_grupo = {i: g[0] for g in grupos for i in g}
    representantes = [f for f in fichas if no_grupo.get(f["id"], f["id"]) == f["id"]]
    achados: dict[str, set[str]] = {}

    def marcar(i: str, tipo: str) -> None:
        achados.setdefault(i, set()).add(tipo)

    zerados = [f for f in representantes if f.get("zerado")]
    if len(zerados) > 1:
        for f in zerados:
            marcar(f["id"], ZERADO)

    com_tempo = sorted((f for f in representantes if not f.get("zerado")
                        and f.get("inicio_s") is not None and f.get("fim_s") is not None),
                       key=lambda f: (f["inicio_s"], f["fim_s"]))
    anterior = None
    for f in com_tempo:
        if anterior is not None:
            folga = max(f.get("tol_s") or 0, anterior.get("tol_s") or 0)
            if f["inicio_s"] < anterior["fim_s"] - folga:
                marcar(f["id"], SOBREPOSTO)
                marcar(anterior["id"], SOBREPOSTO)
            elif abs(f["inicio_s"] - anterior["fim_s"]) <= folga:
                marcar(f["id"], CONTINUO)
                marcar(anterior["id"], CONTINUO)
        if anterior is None or f["fim_s"] >= anterior["fim_s"]:
            anterior = f

    saida: dict[str, list[str]] = {}
    for g in grupos:  # o que a linha do grupo tem, cada canal dela tem
        for i in g[1:]:
            if g[0] in achados:
                achados[i] = set(achados[g[0]])
    for i, tipos in achados.items():
        saida[i] = sorted(tipos)
    return saida


def _presumidas(fichas_: list[dict]) -> dict:
    """`{cena crua: [cena, plano]}`: a mesma presunção da ferramenta de subclipe, para o card não contradizer a lista dela."""
    sem_plano = [f.get("cena") for f in fichas_ if f.get("cena") and not f.get("plano")]
    if not sem_plano:
        return {}
    import motor
    motor.carregar()
    from media import identidade
    return {k: list(v) for k, v in identidade.presumir_da_forma(sem_plano).items()}


def rota_analise(corpo: dict) -> tuple[int, dict]:
    v = corpo.get("fichas")
    if not isinstance(v, list) or not all(isinstance(f, dict) and isinstance(f.get("id"), str) for f in v):
        return 400, {"error": "faltaram fichas"}
    grupos = grupos_monofonicos(v)
    return 200, {"grupos": grupos, "conflitos": conflitos(v, grupos), "presumidas": _presumidas(v)}


def separar_mono(clips: list) -> tuple[list, dict[str, str]]:
    """Tira do sync os canais de um take mono que não são o primeiro: `(clipes para o motor, {irmão: primeiro})`.

    ⛔ MEDIDO (2026-11-08): com os dois no sync, o 1º casa com a câmera e o 2º é empurrado para DEPOIS do 1º (o motor
    resolve sobreposição de fonte), e no Media Composer os dois iam para a mesma trilha."""
    primeiro_de = {c["path"]: c["mono_de"] for c in clips
                   if isinstance(c, dict) and isinstance(c.get("mono_de"), str) and isinstance(c.get("path"), str)}
    return [c for c in clips if not (isinstance(c, dict) and c.get("path") in primeiro_de)], primeiro_de


def devolver_mono(resultado: dict, primeiro_de: dict[str, str]) -> dict:
    """Devolve ao mapa os canais tirados do sync, na MESMA posição do primeiro, como sons sem câmera."""
    if not primeiro_de or not isinstance(resultado, dict):
        return resultado
    irmaos: dict[str, list[str]] = {}
    for irmao, base in primeiro_de.items():
        irmaos.setdefault(str(Path(base)), []).append(irmao)
    for grupo in resultado.get("groups") or []:
        sons = [t["sound"] for t in grupo.get("takes") or [] if isinstance(t.get("sound"), dict)]
        sons += list(grupo.get("orphan_sounds") or [])
        novos = [{**s, "path": i} for s in sons for i in irmaos.get(str(Path(s["path"])), [])]
        if novos:
            grupo["orphan_sounds"] = list(grupo.get("orphan_sounds") or []) + novos
    return resultado
