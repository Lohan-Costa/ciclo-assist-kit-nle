"""O .prproj → a sequência do Avid, sobre masters PRONTOS (rota Premiere → Avid; organograma aprovado pelo autor em
2026-10-25, https://claude.ai/artifact/CzvNCD3DH88HHXh5aa8SYj).

A ordem é a de 18/10 (PRODC no MC 24.6), agora como peça do motor em vez de script de rodada:

    analisar (tools.prproj_para_drt) → planejar (aqui) → o MC linka/injeta a mídia (servico/prproj_avid.py)
    → montar_sequencia (aqui): build_avb sobre a bin dos masters

⭐⭐ **Os masters vêm ANTES da sequência, e não o contrário.** No .prproj a posição de cada plano está nos quadros DO
ARQUIVO (25, 60, 100 q/s no PRODC), e o Avid a guarda nas unidades do master. Um master offline nascido à taxa da timeline
e repontado depois (o relink da AAF, que só troca o MobID — `avb_bin/remap.py`) deslocaria o corte. Com o master
linkado pelo MC, a taxa é a do arquivo de verdade.

As três camadas (decisão do autor, 2026-10-25): o que está na Avid MediaFiles, o que está nas pastas indicadas (link) e
o que não foi achado — este vira um master OFFLINE no lugar do plano (`media_bin.build_offline_masters`), nunca um
vazio. ⚠️ O offline nasce à taxa da TIMELINE: num arquivo de outra taxa o trecho declarado é aproximado — ele está
offline de qualquer jeito, e o relink do editor no MC o refaz.

A CHAVE de cada master é o caminho do arquivo achado nesta máquina, ou `offline:<o que o projeto declara>`. Ela vira o
`mob_id` dos segmentos, e o `build_avb` liga chave → master pelo `mob_hex`.
"""

from __future__ import annotations

import os

OFFLINE = "offline:"


def _nome(caminho: str) -> str:
    return os.path.basename(str(caminho).replace("\\", "/"))


def _achado(s: dict, analise: dict) -> str | None:
    """O arquivo DESTA máquina para o plano `s`, ou None."""
    from tools.prproj_para_drt import _alvo_de

    ref = (s.get("media_ref") or {}).get("local_path")
    if not ref:
        return None
    alvo = _alvo_de(s, analise.get("casamento") or {})
    if not alvo and s.get("is_audio"):
        alvo = ((analise.get("sons") or {}).get(ref) or {}).get("realocado")
        if not alvo:
            # ⛔ o som que está NO caminho do projeto: o casamento é só do vídeo e o `relocar_sons` só lista o que está
            #   FORA do lugar — o som no lugar entrava OFFLINE no Avid (medido 2026-11-25, B03 a 23,976: os 3 WAV)
            from prproj.originais import recusado
            if not recusado(ref) and os.path.isfile(ref):
                alvo = ref
    return alvo if alvo and os.path.isfile(alvo) else None


def _so_som(arq: str) -> bool:
    """O arquivo é de SOM (WAV, AIFF…), que o Conformar autora pelo molde. Um MOV/MXF usado só como som (o som de câmera,
    o MOV de pares estéreo) vai pelo LINK do MC, como o vídeo: o molde é de WAV, e o MOV entrava OFFLINE estando no
    disco (medido 2026-11-25, MC 25.12 Mac, B03_PARES)."""
    from prproj.originais import EXT_SOM

    return os.path.splitext(str(arq))[1].lower() in EXT_SOM


def _tamanho(arq: str):
    """(largura, altura) do arquivo pela sondagem do casamento (em cache), ou None."""
    try:
        from prproj.originais import sondar

        r = sondar(arq)
        return (int(r["w"]), int(r["h"])) if r.get("w") and r.get("h") else None
    except Exception:  # noqa: BLE001 — sem o tamanho, a máscara não vai (o resto vai)
        return None


TETO_DB = 12.0     # o ganho de clipe do Avid (`ganho_de_clipe`) e a automação (`automacao_de_volume`)


def _level(db: float) -> int:
    from .translate import UNITY_GAIN

    return round(UNITY_GAIN * 10 ** (min(float(db), TETO_DB) / 20))


def automacao_de_volume(s: dict) -> list[tuple[int, int]]:
    """O Volume do clipe COM KEYFRAMES do Premiere → a automação de volume do Avid: `[(quadro desde o início do clipe,
    level)]`, ou `[]`. O leitor já entrega a curva recortada no trecho (`prproj.leitura._volume_no_trecho`: o 1º ponto
    é a entrada do clipe), então o offset é o quadro − o 1º. Linear entre os pontos nos dois lados. Acima de +12 dB vai
    +12 (o `value` é int32 como o `level`), contado na tela."""
    kf = s.get("volume_kf") or []
    if len(kf) < 2:
        return []
    q0 = int(kf[0][0])
    return [(int(q) - q0, _level(db)) for q, db in kf]


def ganho_de_clipe(s: dict) -> dict | None:
    """O Volume FIXO do clipe do Premiere → o ganho de clipe do Avid (decisão do autor, 2026-10-29), ou None.

    Vira o mesmo efeito "Audio Gain" que o AAF traz, e o escritor o embrulha num `PanVolumeEffect`
    (`translate._gain_level`): level = 2^29 × 10^(dB/20), 2^29 = 0 dB (banco `avb/escrita.md`, GANHO). Com keyframes
    vai como automação de volume (`automacao_de_volume`), não como ganho.

    ⚠️ O teto é +12 dB: o `level` é um inteiro de 32 bits (2^31 / 2^29 = 4× = +12,04 dB — a régua do mixer do MC
    para aí), e o Premiere vai a +15. Acima disso vai +12, CONTADO na tela (medido 2026-10-29: +15 estourava a
    gravação da bin)."""
    db = s.get("volume_db")
    if s.get("volume_kf") or db is None or abs(float(db)) <= 0.05:
        return None
    return {"name": "Audio Gain", "category": "gain", "reproducible": True, "params": {"level_num": _level(db)}}


def planejar(analise: dict) -> dict:
    """A análise do .prproj → o que o Avid precisa receber.

    Devolve `{segmentos, fps, video: {arquivo: nome}, audio: {arquivo: quadros pedidos}, ausentes: {chave: nome}}`.
    Os segmentos são CÓPIAS com `mob_id` = a chave do master e, no áudio, `source_slot_id` = o canal do arquivo."""
    leitura = analise["leitura"]
    segs, video, audio, ausentes = [], {}, {}, {}
    for s0 in leitura["segmentos"]:
        s = dict(s0)
        ref = (s.get("media_ref") or {}).get("local_path")
        if ref and not (s.get("is_gap") or s.get("is_transition") or s.get("is_effect")):
            arq = _achado(s, analise)
            chave = arq or OFFLINE + ref
            s["mob_id"], s["clip_name"] = chave, _nome(arq or ref)
            if s.get("is_audio"):
                s["source_slot_id"] = int(s.get("canal_arquivo") or 1)
                ganho = ganho_de_clipe(s)
                if ganho:
                    s["effects"] = list(s.get("effects") or []) + [ganho]
                auto = automacao_de_volume(s)
                if auto:
                    s["volume_auto"] = auto
            if not arq:
                ausentes[chave] = _nome(ref)
            elif s.get("is_audio") and not _so_som(arq):
                video[arq] = _nome(arq)
            elif s.get("is_audio"):
                fim = int(s.get("source_start_frames") or 0) + int(s.get("duration_frames") or 0)
                audio[arq] = max(audio.get(arq, 0), fim)
            else:
                video[arq] = _nome(arq)
                s["fonte_px"] = _tamanho(arq)                  # a máscara do Premiere é presa à FONTE (AniMatte)
        segs.append(s)
    sobrepor_transicoes(segs, leitura["fps"])
    for s in segs:                                     # o quanto a timeline pede inclui a cabeça/cauda da transição
        if s.get("is_audio") and s.get("mob_id") in audio:
            fim = int(s.get("source_start_frames") or 0) + int(s.get("duration_frames") or 0)
            audio[s["mob_id"]] = max(audio[s["mob_id"]], fim)
    return {"segmentos": segs, "fps": leitura["fps"], "video": video, "audio": audio, "ausentes": ausentes,
            "inicio": leitura.get("inicio")}


def _vazio(t: dict, tc: str) -> dict:
    """Um vazio de 0 quadros na trilha de `t` (o escritor só olha o TIPO do vizinho da transição)."""
    return {"track": t["track"], "is_gap": True, "is_transition": False, "is_effect": False, "disabled": False,
            "is_audio": bool(t.get("is_audio")), "timeline_tc_in": tc, "timeline_tc_out": tc, "duration_frames": 0,
            "source_start_frames": 0, "cutpoint": 0, "mob_id": None, "clip_name": "", "media_ref": None}


def sobrepor_transicoes(segs: list[dict], fps: float) -> int:
    """Transição do Premiere → o modelo do Avid. No .prproj os dois planos ENCOSTAM no corte e a transição o atravessa
    (`cutpoint` quadros antes dele); no Avid ela é a SOBREPOSIÇÃO dos dois — o A vai até o fim da transição e o B começa
    no início dela. Sem isto o escritor punha o B no corte e meia transição caía no vazio (PRODC, A3 Samba, 18/10: clipes
    24:09–26:10 e 26:10–31:12, transição 26:06–26:14 com cutpoint 4). A rota AAF não precisa: o AAF já traz a
    sobreposição.

    Cada lado por si (o fade é a transição de um lado só, com o vazio do outro): o plano que ENCOSTA no corte antes
    dela tem a cauda esticada em `dur − cutpoint`; o que encosta depois tem a cabeça recuada em `cutpoint` (na fonte e
    na timeline). Nenhum corte muda de lugar — o que entra é a mídia por baixo da transição, a mesma que o Premiere
    usa. Fica como está (meia transição, como antes) o lado com velocidade, com a fonte noutra taxa ou sem mídia antes
    do início. Devolve quantas transições mudaram."""
    from .translate import _frames_tc, _tc_frames

    def q(s):
        return _tc_frames(s["timeline_tc_in"], fps)

    def simples(s):
        return (not s.get("has_motion_effect") and not s.get("colapso")
                and abs(float(s.get("source_fps") or fps) - float(fps)) < 0.01)

    def clipe(s):
        return s is not None and s.get("mob_id") and s.get("timeline_tc_in") and not (s.get("is_gap") or s.get("is_transition")
                                                          or s.get("is_effect") or s.get("disabled"))

    n = 0
    i = 0
    while i < len(segs):
        t = segs[i]
        if not t.get("is_transition") or not t.get("timeline_tc_in"):
            i += 1
            continue
        dur, cp = int(t["duration_frames"]), int(t.get("cutpoint") or 0)
        corte = q(t) + cp
        a = segs[i - 1] if i > 0 and segs[i - 1].get("track") == t["track"] else None
        b = segs[i + 1] if i + 1 < len(segs) and segs[i + 1].get("track") == t["track"] else None
        mexeu = False
        if clipe(a) and simples(a) and q(a) + int(a["duration_frames"]) == corte and dur > cp:
            a["duration_frames"] = int(a["duration_frames"]) + dur - cp
            mexeu = True
        if clipe(b) and simples(b) and q(b) == corte and 0 < cp <= int(b.get("source_start_frames") or 0):
            b["source_start_frames"] = int(b["source_start_frames"]) - cp
            b["duration_frames"] = int(b["duration_frames"]) + cp
            if b.get("volume_auto"):           # a automação conta do início do clipe: a cabeça nova a empurra
                b["volume_auto"] = [(q + cp, v) for q, v in b["volume_auto"]]
            b["timeline_tc_in"] = _frames_tc(corte - cp, fps)
            mexeu = True
        if clipe(b) and a is None:
            # o mesmo para o fade de ENTRADA no começo da trilha (o escritor pede um vazio antes)
            segs.insert(i, _vazio(t, t["timeline_tc_in"]))
            i += 1
        if clipe(a) and b is None:
            # fade de saída no FIM da trilha: sem um vazio depois, o escritor a toma por órfã e a descarta
            # (`translate._position_row`) — e o A já esticado ficaria à vista sem o fade
            segs.insert(i + 1, _vazio(t, _frames_tc(q(t) + dur, fps)))
        n += mexeu
        i += 1
    return n


#: O que o escritor de `.avb` APROVEITA de um plano do Premiere (`translate`): o Motion (escala, posição, rotação,
#: espelho, keyframes → Resize/PIP/3D Warp), a máscara de opacidade não invertida (AniMatte), o título, a velocidade
#: e o ganho de clipe (o Volume fixo, `ganho_de_clipe`).
_NO_AVID = {"Motion", "Máscara de opacidade (Fusion)", "Audio Gain"}


def efeitos_fora_do_avid(plano: dict) -> dict[str, int]:
    """`{efeito: nº de planos}` do que o Premiere tem e o `.avb` NÃO leva — para a tela dizer, nunca calar (B009).

    O `reproducible` do leitor fala do RESOLVE: um Lumetri que lá vira LUT, um crop ou um blur do Fusion somem no Avid.
    Plano desligado não conta (B108: não existe na imagem)."""
    fora: dict[str, int] = {}

    def conta(nome: str) -> None:
        fora[nome] = fora.get(nome, 0) + 1

    for s in plano["segmentos"]:
        if s.get("is_gap") or s.get("is_transition") or s.get("disabled"):
            continue
        for e in s.get("effects") or []:
            nome, p = e.get("name") or "?", e.get("params") or {}
            if e.get("category") == "title":
                continue
            if nome == "Motion":
                if p.get("crop_frac"):
                    conta("Crop")
                if p.get("composite"):
                    conta("Luma Key")
            elif nome == "Máscara de opacidade (Fusion)":
                if any(m.get("invertida") for m in p.get("mascaras") or []):
                    conta("máscara de opacidade invertida")
            elif nome not in _NO_AVID:
                conta(nome)
        # o fixo vai como ganho de clipe (`ganho_de_clipe`); com keyframes, como automação (`automacao_de_volume`)
        if s.get("is_audio") and max([float(s.get("volume_db") or 0.0)]
                                     + [float(db) for _q, db in s.get("volume_kf") or []]) > TETO_DB + 0.05:
            conta("Volume do clipe acima de +12 dB (vai a +12)")
    return dict(sorted(fora.items(), key=lambda kv: -kv[1]))


def de_outra_midia(plano: dict, analise: dict) -> dict[str, int]:
    """`{"escala": n, "proporcao": n}` planos cuja escala parece digitada para outra mídia, ou cujo arquivo tem outra
    proporção que a do projeto (`prproj_para_drt.escalas_de_outra_midia`/`proporcoes_de_outra_midia`; B109).

    A escala vira oferta e marcador como no Resolve (`ajustar_escalas`); a proporção, só a CONTA — a geometria do
    `.avb` já sai do arquivo apontado (`fonte_px`)."""
    conta = {"escala": 0, "proporcao": 0}
    for s in plano["segmentos"]:
        if s.get("is_gap") or s.get("is_transition") or s.get("is_audio") or s.get("disabled"):
            continue
        ref = (s.get("media_ref") or {}).get("local_path")
        conta["escala"] += ref in (analise.get("escalas") or {})
        conta["proporcao"] += ref in (analise.get("proporcoes") or {})
    return conta


def ajustar_escalas(plano: dict, analise: dict, reescalar: dict | None) -> list[dict]:
    """A escala digitada para outra mídia, COMO NO RESOLVE (decisão do autor, 2026-10-29): o que o editor aceitou na
    oferta (`reescalar` = `{caminho do projeto: fator}`, só o que a análise ofereceu) tem a escala × fator
    (`prproj_para_drt._reescalar`); os outros suspeitos entram como o projeto diz. Todos ganham um marcador amarelo.

    Devolve as marcas `{quadro, trilha, nota}` (quadro desde o início da timeline; trilha = V do Avid) para o
    `AddMarker` depois que a sequência existe no MC."""
    import copy

    from tools.prproj_para_drt import _reescalar

    from .translate import _tc_frames

    oferta = analise.get("escalas") or {}
    marcas = []
    for s in plano["segmentos"]:
        if s.get("is_gap") or s.get("is_transition") or s.get("is_audio") or s.get("disabled") \
                or not s.get("timeline_tc_in"):
            continue
        ref = (s.get("media_ref") or {}).get("local_path")
        if ref not in oferta:
            continue
        aceito = (reescalar or {}).get(ref)
        if aceito:
            s["effects"] = copy.deepcopy(s.get("effects") or [])     # a análise não é tocada (o plano é cópia rasa)
            _reescalar(s, float(aceito))
        marcas.append({"quadro": _tc_frames(s["timeline_tc_in"], plano["fps"]), "trilha": int(s.get("track") or 1),
                       "nota": (f"DLPC escala x {float(aceito):g} (digitada para outra mídia, ajustada): conferir"
                                if aceito else
                                f"DLPC escala parece digitada para outra mídia (sugerido x {oferta[ref]['fator']:g}): "
                                "conferir")})
    return marcas



def marcas_de_duvida(plano: dict, analise: dict) -> list[dict]:
    """O convertido de TC zerado/ausente que entrou por ser a ÚNICA mídia (B110, autor 2026-10-31: "depende do disco"):
    um marcador amarelo por plano, como no Resolve e no Premiere (`originais.casar_um` → `duvida`). Lab B110 no MC 25.6:
    a rota do Avid entregava os 4 convertidos sem aviso nenhum."""
    from .translate import _tc_frames

    casamento = analise.get("casamento") or {}
    marcas = []
    for s in plano["segmentos"]:
        if s.get("is_gap") or s.get("is_transition") or s.get("is_audio") or s.get("disabled")                 or not s.get("timeline_tc_in"):
            continue
        c = casamento.get((s.get("media_ref") or {}).get("local_path")) or {}
        if c.get("duvida") and c.get("estado") == "original":
            marcas.append({"quadro": _tc_frames(s["timeline_tc_in"], plano["fps"]), "trilha": int(s.get("track") or 1),
                           "nota": f"DLPC TC a conferir: {c['duvida']}"})
    return marcas

def sem_master(plano: dict, arquivos) -> int:
    """Os `arquivos` achados que NÃO viraram master (o MC recusou o link, áudio sem molde) passam a OFFLINE no lugar:
    sem isto o plano viraria vazio (PRODC, 18/10: os 5 .mov recusados e 2 WAV sem molde). Devolve quantos planos mudaram."""
    fora = set(arquivos or ())
    n = 0
    for s in plano["segmentos"]:
        if s.get("mob_id") in fora:
            ref = (s.get("media_ref") or {}).get("local_path") or s["mob_id"]
            s["mob_id"] = OFFLINE + ref
            plano["ausentes"][s["mob_id"]] = _nome(ref)
            n += 1
    for arq in fora:
        plano["video"].pop(arq, None)
        plano["audio"].pop(arq, None)
    return n


def redirecionar(plano: dict, decisoes: dict) -> int:
    """As decisões da LISTA DE MÍDIAS do relink (`{chave: arquivo | None}`): o arquivo que o casamento ou o editor
    escolheu passa a ser o master do plano (pode ser outro que não o da análise: o relink manual); None = fica OFFLINE
    no lugar (ignorado, ou não achado). Chave fora de `decisoes` fica como estava. Devolve quantos planos mudaram."""
    n = 0
    for s in plano["segmentos"]:
        k = s.get("mob_id")
        if not k or k not in decisoes:
            continue
        arq = decisoes[k]
        ref = (s.get("media_ref") or {}).get("local_path") or str(k)
        novo = arq if arq else (k if str(k).startswith(OFFLINE) else OFFLINE + ref)
        if novo == k:
            continue
        s["mob_id"], s["clip_name"] = novo, _nome(arq or ref)
        if arq and not s.get("is_audio"):
            s["fonte_px"] = _tamanho(arq)
        n += 1
    # os pedidos refeitos a partir dos planos (o mesmo cálculo do `planejar`)
    video, audio, ausentes = {}, {}, {}
    for s in plano["segmentos"]:
        k = s.get("mob_id")
        if not k or s.get("is_gap") or s.get("is_transition") or s.get("is_effect"):
            continue
        if str(k).startswith(OFFLINE):
            ausentes[k] = plano["ausentes"].get(k) or _nome(str(k)[len(OFFLINE):])
        elif s.get("is_audio") and _so_som(str(k)):
            fim = int(s.get("source_start_frames") or 0) + int(s.get("duration_frames") or 0)
            audio[k] = max(audio.get(k, 0), fim)
        else:
            video[k] = _nome(k)
    plano["video"], plano["audio"], plano["ausentes"] = video, audio, ausentes
    return n


def specs_offline(plano: dict) -> tuple[dict, int]:
    """`({chave: {name, master_len, kind}}, handle)` dos masters OFFLINE — o mecanismo do PRODUCAO-A
    (`media_bin._offline_specs`): a folga `handle` nos dois lados dá às transições a cabeça e a cauda que pedem."""
    from .media_bin import _offline_specs
    from .translate import offline_handle_frames

    handle = offline_handle_frames(plano["segmentos"])
    faltam = [i for i, s in enumerate(plano["segmentos"]) if s.get("mob_id") not in plano["ausentes"]]
    specs = _offline_specs(plano["segmentos"], [{"segment_index": i, "matched_path": "x"} for i in faltam], handle)
    for chave, d in specs.items():
        d["name"] = plano["ausentes"].get(chave, d["name"])
    # o som offline com TODOS os canais que a timeline usa (aqui o `source_slot_id` é o canal do arquivo, 1…N): sem isto
    # o master offline tinha 2 trilhas e o canal 3+ apontava para trilha inexistente no MC (2026-11-25)
    for s in plano["segmentos"]:
        d = specs.get(s.get("mob_id"))
        if d is not None and s.get("is_audio") and not (s.get("is_gap") or s.get("is_transition")):
            d["canais"] = max(int(d.get("canais") or 1), int(s.get("source_slot_id") or 1))
    return specs, handle


def montar_sequencia(plano: dict, media_bin: str, saida: str, nome: str, mob_hex: dict, offline_hex: dict) -> dict:
    """Escreve a sequência `nome` em `saida`, sobre a bin `media_bin` (que já tem TODOS os masters).

    `mob_hex`: `{chave → hex do master}` dos linkados/injetados; `offline_hex`: o mesmo dos offline (eles levam a folga
    de transição — `translate.set_offline_handles`)."""
    from .translate import build_avb

    media_map = {chave: {"name": plano["ausentes"].get(chave, ""), "mob_id": h} for chave, h in offline_hex.items()}
    return build_avb(plano["segmentos"], plano["fps"], media_bin, saida, nome, media_map=media_map,
                     origem="premiere", mob_hex={**mob_hex, **offline_hex}, inicio=plano.get("inicio"))
