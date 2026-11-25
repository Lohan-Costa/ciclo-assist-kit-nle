"""Uma sequência do Premiere → DRT do Resolve religado aos ORIGINAIS de câmera.

    python -m tools.prproj_para_drt PROJETO.prproj "SEQUÊNCIA" SAIDA.drt \
        --originais /Volumes/LB_03_T/PRODUCAO_B [--originais …] [--referencia FILME.mp4]

Fluxo aprovado em 2026-10-02 (organograma "Do proxy do Premiere ao ARRIRAW no Resolve"):
  leitor de PRPROJ → casar proxy → original → `drp.writer.build_drt`.
  • plano sem original: entra no PROXY e vai para a lista "refazer";
  • efeito que não traduz e enquadramento animado: lista "conferir";
  • `--referencia`: o export do filme numa trilha acima de todas, a partir do quadro 0.
Grava ao lado do DRT um `.relatorio.json` com as contagens, os marcadores a pôr na timeline e
as composições do Fusion (máscara, blur) a criar depois do import — o DRT não as leva.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from drp.fusion_clipe import agrupar  # noqa: E402
from drp.writer import _media_meta, build_drt  # noqa: E402
from media.sonda import taxa_variavel  # noqa: E402
from prproj.leitura import Leitor, frames_para_tc  # noqa: E402
from prproj.originais import (EXT_PARADA, _chave_recusada, casar, indexar, recusado,  # noqa: E402
                              relocar_sons, sondar)
from prproj.projeto import Projeto  # noqa: E402
from tools.conferir_conform import SEGUNDOS_POR_PONTO, pontos_visiveis  # noqa: E402


def _tc_frames(tc: str, n: int) -> int:
    h, m, s, f = (int(x) for x in tc.split(":"))
    return ((h * 60 + m) * 60 + s) * n + f


#: O que vai para a tela "antes de montar" (organograma de 2026-10-02, atualizado em 2026-10-03).
_MOTIVO = {"incompleto": "o original está vazio, ilegível ou truncado: confira o arquivo",
           "ambiguo": "mais de um original possível: escolher",
           "lento": "o disco não respondeu a tempo ao ler o original (lento ou com defeito?): "
                    "confira o disco e importe de novo",
           "sem_original": "original não encontrado nas pastas (se este arquivo já é o original, "
                           "ignore)"}


def analisar(prproj: str, sequencia: str, originais: list[str], progresso=None,
             confiavel=None) -> dict:
    """A parte demorada, ANTES de montar: ler a sequência e casar cada proxy com o original.
    Devolve `{leitura, casamento, resumo}`; o `montar` reaproveita, sem ler nem sondar de novo.

    `confiavel(caminho) → (seguro | None, motivo)`: a tranca dos caminhos que vêm de DENTRO do
    projeto (`avb_bin.segmentos.caminho_confiavel`). O `.prproj` pode vir de outra produtora: um
    `\\\\host\\x.mov` faria até o `exists()` abrir sessão SMB com o host (ataque V2 do fluxo
    do Avid). O caminho recusado vira vazio ANTES de qualquer toque no disco, e o plano entra com
    marcador "arquivo não encontrado"."""
    projeto = Projeto(prproj)
    leitura = _ler(projeto, sequencia, confiavel)
    # a referência achada na timeline não é plano: não se casa com original
    indice = indexar(originais)
    planos = [x for x in leitura["segmentos"] if not x.get("referencia")]
    casamento = casar(planos, originais, progresso, indice=indice)
    taxas = _taxas_reais(planos, casamento)
    if taxas:
        # a fonte do projeto está em TEMPO; a grade de quadros tem de ser a do arquivo apontado (`Leitor.taxas`)
        leitura = _ler(projeto, sequencia, confiavel, taxas)
        planos = [x for x in leitura["segmentos"] if not x.get("referencia")]
    sons = relocar_sons(planos, indice)
    resumo = resumir(leitura["segmentos"], casamento, leitura.get("declarados"))
    # os sons na MESMA lista (organograma Premiere → Premiere, 2026-10-22): o som direto e a música, provados pela duração
    resumo["midias"] = resumo["midias"] + lista_de_sons(planos, sons)
    resumo["sons_fora_do_lugar"] = {"achados": sum(1 for x in sons.values() if x.get("realocado")),
                                    "faltam": sorted(os.path.basename(p.replace("\\", "/")) for p, x in sons.items()
                                                     if not x.get("realocado"))}
    if taxas:
        resumo["taxa_do_arquivo"] = len(taxas)
    escalas = escalas_de_outra_midia(planos)
    proporcoes = proporcoes_de_outra_midia(planos, casamento)
    resumo["proporcao_de_outra_midia"] = [{"caminho": c, "nome": os.path.basename(c.replace("\\", "/")), **x}
                                          for c, x in sorted(proporcoes.items())]
    resumo["escala_de_outra_midia"] = [{"caminho": c, "nome": os.path.basename(c.replace("\\", "/")), **x}
                                       for c, x in sorted(escalas.items())]
    # A ESTIMATIVA da conferência pela referência, já na tela "antes de montar" (organograma
    # aprovado pelo autor, 2026-10-04): um teto — o ponto coberto por outra trilha some.
    n = len(pontos_visiveis(leitura["segmentos"], round(leitura["fps"])))
    resumo["conferencia"] = {"pontos": n, "segundos": round(n * SEGUNDOS_POR_PONTO)}
    return {"leitura": leitura, "casamento": casamento, "sons": sons, "escalas": escalas, "proporcoes": proporcoes,
            "resumo": resumo}


def _ler(projeto, sequencia: str, confiavel=None, taxas: dict | None = None) -> dict:
    leitura = Leitor(projeto, taxas).ler(sequencia)
    if confiavel is not None:
        for s in leitura["segmentos"]:
            ref = s.get("media_ref")
            if ref and ref.get("local_path"):
                seguro, _motivo = confiavel(ref["local_path"])
                # recusado: a chave inerte guarda só o NOME, para procurá-lo nas pastas indicadas (R04,
                # 2026-10-18: 15 arquivos em \\169.254.100.100\… viravam um item só, sem nome, e offline)
                if not seguro:
                    # o TEXTO declarado fica para a coluna "De onde veio" (mostrar não toca no disco)
                    leitura.setdefault("declarados", {})[_chave_recusada(ref["local_path"])] = ref["local_path"]
                ref["local_path"] = seguro or _chave_recusada(ref["local_path"])
    return leitura


def _taxas_reais(planos: list[dict], casamento: dict) -> dict[str, float]:
    """{FilePath do projeto: taxa do arquivo apontado} onde as duas diferem (a sondagem é a do casamento, em cache).
    A chave é o caminho como o PROJETO o escreve (`prproj.proxy`) — o que o `Leitor` acha no `Media`."""
    taxas: dict[str, float] = {}
    for s in planos:
        bruto = (s.get("prproj") or {}).get("proxy")
        alvo = None if s.get("is_audio") or not bruto else _alvo_de(s, casamento)
        if not alvo:
            continue
        fps = sondar(alvo).get("fps")
        if fps and s.get("source_fps") and abs(fps - float(s["source_fps"])) > 0.01:
            taxas[bruto] = float(fps)
    return taxas


def _resumo_audio(segs: list[dict]) -> dict:
    """O áudio na tela "antes de montar": clipes, trilhas, transições, desligados e os efeitos que
    não traduzem (sem marcador clipe a clipe — decisão do autor, 2026-10-04)."""
    clipes = [s for s in segs if s.get("is_audio") and not (s.get("is_gap") or s.get("is_transition"))]
    efeitos: dict[str, int] = {}
    for s in clipes:
        for e in s.get("effects") or []:
            if e["name"] not in ("Volume", "Channel Volume", "Panner"):
                efeitos[e["name"]] = efeitos.get(e["name"], 0) + 1
    return {"clipes": len(clipes), "trilhas": len({s["track"] for s in clipes}),
            "transicoes": sum(1 for s in segs if s.get("is_audio") and s.get("is_transition")),
            "desligados": sum(1 for s in clipes if s.get("disabled")),
            # o Volume do clipe que MUDA algo (fixo ≠ 0 dB ou com keyframes) — o DRT leva os dois (`drp/writer`
            # `_volume_ba`/`_volume_ba_kf`). Antes contava todo clipe com o componente (quase todos, a 0 dB)
            "volume": sum(1 for s in clipes if s.get("volume_db") is not None or s.get("volume_kf")),
            "efeitos": dict(sorted(efeitos.items(), key=lambda kv: -kv[1]))}


def _anotar_offline(offline: dict, caminho: str, s: dict, fps_tl: float) -> None:
    """Os metadados que o `ffprobe` daria, para o arquivo AUSENTE entrar offline no DRT
    (`build_drt(offline=…)`, o mesmo do caminho do Avid): duração da fonte (a que o projeto declara;
    sem ela, o fim do trecho mais longo pedido), taxa da fonte e, no som, os canais (o maior canal
    lido) a 48 kHz. TC de início: nenhum — o In do Premiere já é contado do início do arquivo
    (`writer`: In = source_start_frames × speed_ratio). ⚠️ O caminho NUNCA é tocado no disco aqui."""
    ref = s.get("media_ref") or {}
    fps = float(ref.get("source_fps") or s.get("source_fps") or fps_tl or 0) or 25.0
    fim = int(s.get("source_start_frames") or 0) + int(round((s.get("duration_frames") or 0)
                                                               * abs(float(s.get("speed_ratio") or 1.0)))) + 1
    m = offline.setdefault(caminho, {"nb": 0, "fps": fps, "tc": None, "audio_sr": 48000, "audio_canais": 1})
    m["nb"] = max(m["nb"], int(ref.get("source_duration_frames") or 0), fim)
    if s.get("is_audio"):
        m["audio_canais"] = max(m["audio_canais"], int(s.get("canal_arquivo") or 1))


def _motion(s: dict) -> dict | None:
    return next((e.get("params") for e in s.get("effects") or [] if e.get("name") == "Motion"), None)


def escalas_de_outra_midia(segmentos: list[dict]) -> dict[str, dict]:
    """{caminho do projeto: {fator, planos}} dos arquivos cuja escala parece digitada para OUTRA mídia.

    R04, 2026-10-18 (banco `prproj/relink-e-geometria.md` §6.4): o .prproj de 2023 tem `Scale 50` em arquivos que o
    próprio projeto declara 1920×1080 — os 50 % eram o encaixe do 4K da câmera, e o projeto foi relinkado a cópias sem
    corrigir; o raster de então não ficou gravado. Decisão do autor: marcar e OFERECER, nunca aplicar sozinho.

    Suspeito = arquivo com algum plano MENOR que o encaixe nos dois eixos. O fator sugerido é 1 ÷ o menor zoom entre os
    suspeitos da mesma câmera (o prefixo do nome: PRJ-, JUL_…) e do mesmo raster declarado: o menor uso é o encaixe que
    o editor digitou, e os planos de um arquivo só herdam dos irmãos. Medido no R04: os 29 planos, ×2 e ×3,75, iguais
    ao projeto resgatado à mão. Um PIP de verdade também aparece aqui — por isso é oferta, com o fator à vista."""
    import re

    por_arquivo: dict[str, dict] = {}
    for s in segmentos:
        if s.get("is_audio") or s.get("is_gap") or s.get("is_transition") or s.get("is_effect") \
                or s.get("referencia") or (s.get("prproj") or {}).get("sintetico"):
            continue
        p, ref = _motion(s), s.get("media_ref") or {}
        caminho = ref.get("local_path")
        if not p or not caminho or os.path.splitext(caminho)[1].lower() in EXT_PARADA:
            continue
        zoom = min(float(p.get("scale_x", 1) or 1), float(p.get("scale_y", 1) or 1))
        a = por_arquivo.setdefault(caminho, {"min": zoom, "planos": 0,
                                             "raster": tuple((s.get("prproj") or {}).get("proxy_px") or ())})
        a["min"], a["planos"] = min(a["min"], zoom), a["planos"] + 1
    suspeitos = {c: a for c, a in por_arquivo.items() if 0 < a["min"] < 0.999}
    familia: dict[tuple, float] = {}
    for c, a in suspeitos.items():
        k = (re.sub(r"\d.*$", "", os.path.basename(c.replace("\\", "/"))).lower(), a["raster"])
        familia[k] = min(familia.get(k, a["min"]), a["min"])
    return {c: {"fator": round(1 / familia[(re.sub(r"\d.*$", "", os.path.basename(c.replace("\\", "/"))).lower(),
                                              a["raster"])], 4), "planos": a["planos"]}
            for c, a in suspeitos.items()}


def _reescalar(s: dict, fator: float) -> None:
    """A escala do plano × `fator` (posição e âncora são normalizadas: não mudam — banco §1)."""
    p = _motion(s)
    if not p:
        return
    for k in ("scale_x", "scale_y"):
        if k in p:
            p[k] *= fator
    kf = p.get("kf") or {}
    for nome in ("zoom", "zoom_y"):
        if nome in kf:
            kf[nome] = [(q, v * fator) for q, v in kf[nome]]
    # A MÁSCARA fica como está: no Premiere ela é presa à FONTE (vértices normalizados nela) e não muda com o Motion.
    # Conferido no R04 (2026-10-18, rodadas I e J pela imagem): no projeto resgatado à mão as máscaras do nest
    # `transicao-poste` (V3/V4) foram REFEITAS (v' = 0,5 + (v − 0,5) ÷ 2) e as da V2 não — não há regra no formato;
    # transformá-las derrubava dois pontos (0,80 → 0,25). Banco `prproj/relink-e-geometria.md` §6.4.


def _proporcao_do_anexado(s: dict, caminho: str) -> bool:
    """O arquivo apontado é o proxy que o Premiere anexou e tem OUTRA proporção que o principal declarado."""
    pr = s.get("prproj") or {}
    decl, anex = pr.get("proxy_px") or [], pr.get("anexado_px") or []
    if len(decl) != 2 or len(anex) != 2 or not all(decl) or not all(anex):
        return False
    info = sondar(caminho)
    w, h = info.get("w") or 0, info.get("h") or 0
    return bool(w and h) and (w, h) == tuple(anex) and abs(w / h - decl[0] / decl[1]) >= 0.005


def _alvo_de(s: dict, casamento: dict) -> str | None:
    """O arquivo que a timeline vai apontar para este plano (original, o próprio, ou o realocado), se existe aqui."""
    ref = s.get("media_ref") or {}
    c = casamento.get(ref.get("local_path"))
    if not c:
        return None
    alvo = c["original"] if c.get("estado") in ("original", "proprio") else no_disco(ref["local_path"], c)
    return alvo if alvo and not recusado(alvo) and os.path.isfile(alvo) else None


def proporcoes_de_outra_midia(planos: list[dict], casamento: dict) -> dict[str, dict]:
    """{caminho do projeto: {de, para, planos}}: arquivos em que o Premiere ESTICARIA o apontado (o proxy anexado) para a
    proporção de um principal que foi RELIGADO a outro arquivo (o histórico do `Media` aponta outro lugar). R04, 2026-10-18:
    o principal dos JUL_7671/72/80 virou um proxy esticado de 1024×540; fiel ao projeto, o .mov 1920×1080 sai a 1,896:1
    com tarja — o resgate à mão o deixa 16:9. Decisão do autor: OFERECER "a proporção do arquivo apontado"."""
    fora: dict[str, dict] = {}
    for s in planos:
        if s.get("is_audio") or s.get("is_gap") or s.get("is_transition") or s.get("is_effect"):
            continue
        pr = s.get("prproj") or {}
        alvo = _alvo_de(s, casamento)
        if not alvo or not pr.get("principal_religado") or not _proporcao_do_anexado(s, alvo):
            continue
        info = sondar(alvo)
        x = fora.setdefault(s["media_ref"]["local_path"], {"de": list(pr["proxy_px"]),
                                                          "para": [info.get("w"), info.get("h")], "planos": 0})
        x["planos"] += 1
    return fora


def _encaixar_no_arquivo(s: dict, caminho: str, quadro: tuple) -> bool:
    """A geometria do plano refeita sobre o ARQUIVO que a timeline aponta, quando ele é o proxy que o Premiere
    anexou ao original e tem OUTRA proporção. O Motion do projeto é relativo ao original (a escala nos pixels dele;
    o leitor a entrega relativa ao encaixe do original), e o Premiere estica o proxy sobre o raster do original.
    O Resolve encaixa o arquivo: o fator é o retângulo do original encaixado ÷ o do arquivo encaixado, por eixo.

    R04, 2026-10-18: o .prproj de 2023 declara os originais da câmera (3840×2160) com proxies de 1024×540 — os
    arquivos da pasta. Sem o fator, 40 planos saíam com a altura 6,7 % curta (o encaixe de 1024×540 deixa tarja),
    e a mesma timeline do projeto resgatado (que aponta direto para os 1024×540) saía certa. Mesma proporção:
    nada muda (o zoom já é relativo ao encaixe). Outra proporção SEM o proxy declarado: o modo da conversão (fit,
    fill, stretch) não está no projeto (banco `prproj/relink-e-geometria.md` §6.2) — fica como está."""
    pr = s.get("prproj") or {}
    qw, qh = quadro if quadro and all(quadro) else (0, 0)
    if not qw or not _proporcao_do_anexado(s, caminho):
        return False
    decl = pr["proxy_px"]
    info = sondar(caminho)
    w, h = info.get("w") or 0, info.get("h") or 0
    e_o, e_f = min(qw / decl[0], qh / decl[1]), min(qw / w, qh / h)
    mx, my = decl[0] * e_o / (w * e_f), decl[1] * e_o / (h * e_f)
    # o Tilt anda em unidades da imagem ENCAIXADA (leitor, `fy`): a posição vertical acompanha a altura
    fy_o = qh / (decl[1] * e_o) if decl[1] * e_o < qh - 0.5 else 1.0
    fy_f = qh / (h * e_f) if h * e_f < qh - 0.5 else 1.0
    py = fy_f / fy_o
    for ef in s.get("effects") or []:
        if ef.get("name") != "Motion":
            continue
        p = ef.get("params") or {}
        if "scale_x" in p:
            p["scale_x"] *= mx
        if "scale_y" in p:
            p["scale_y"] *= my
        if "pos_y" in p:
            p["pos_y"] *= py
        kf = p.get("kf") or {}
        if "zoom" in kf and "zoom_y" not in kf and abs(mx - my) > 1e-9:
            kf["zoom_y"] = list(kf["zoom"])            # "zoom_y ausente = o mesmo zoom": agora os eixos diferem
        for nome, fator in (("zoom", mx), ("zoom_y", my), ("pos_y", py)):
            if nome in kf:
                kf[nome] = [(q, v * fator) for q, v in kf[nome]]
    pr["encaixe_no_arquivo"] = [round(mx, 6), round(my, 6)]
    return True


def _deslocar_trecho(s: dict, trecho: dict | None) -> bool:
    """O arquivo do projeto é um TRECHO do original decidido (o render da cor voltando; `originais._trecho`): o In conta
    desde o início do arquivo do PROJETO; no original, esse início está `desloc_s` adiante. Sem isto o plano saía do
    começo do original no Resolve, calado — o mesmo erro medido no caminho do MC (BL09, 2026-11-23). Na unidade do
    próprio segmento (`source_fps`: a do arquivo do projeto, ou a do original quando o `_ler` releu na taxa dele)."""
    if not trecho or not trecho.get("desloc_s"):
        return False
    fps = float(s.get("source_fps") or (s.get("media_ref") or {}).get("source_fps") or 0)
    if not fps:
        return False
    s["source_start_frames"] = int(s.get("source_start_frames") or 0) + int(trecho["desloc_s"] * fps + 0.5)
    return True


def no_disco(proxy: str, c: dict) -> str:
    """Onde o arquivo do projeto está NESTA máquina: o caminho dele, ou a mesma mídia achada noutra pasta
    (`realocado` do casamento — o .prproj de outra máquina apontando para G:, J:…). O caminho que a tranca
    recusou, sem nada achado, dá vazio: nunca chega a uma função de disco."""
    return c.get("realocado") or ("" if recusado(proxy) else proxy)


def lista_de_midias(casamento: dict, declarados: dict | None = None) -> list[dict]:
    """A "lista de mídias" da tela "antes de montar" (autor, 2026-10-06): cada arquivo de vídeo da
    sequência, com o codec e o estado. `estado`: `original` (casou, ou é imagem parada que já é o
    final), `sem_original` (o proxy existe, o original não veio) ou `nao_encontrado` (nem o proxy).
    O codec sai do cache da sondagem que o casamento JÁ fez (nenhum ffprobe a mais); sem ele (imagem
    parada, arquivo ausente, ARRIRAW `unknown`), a extensão.
    `como`: `original`, `proprio` (o arquivo do projeto já é o final), `mudou` (o arquivo do projeto noutra pasta, PROVADO
    pelo que o projeto registra: conta como encontrado), `realocado` (o do projeto noutra pasta, sem a prova) ou `proxy`; `arquivo`: o que entra na timeline; `origem`: o caminho que o projeto declara — o recusado pela tranca
    vem de `declarados` (o texto, nunca tocado), com `recusado` verdadeiro."""
    from prproj.originais import _SONDA

    fora = []
    for p, c in casamento.items():
        if c["estado"] in ("original", "proprio"):
            estado = "original"
        else:
            estado = "sem_original" if no_disco(p, c) and os.path.isfile(no_disco(p, c)) else "nao_encontrado"
        # o que entra na timeline e por quê — as colunas "Encontrado" e "De onde veio" da tabela do MC (autor,
        # 2026-10-19: a lista do Resolve igual à do MC); o codec é o do arquivo ENCONTRADO
        if estado == "original":
            como = "mudou" if c.get("mudou") else ("proprio" if c["estado"] == "proprio" else "original")
            arquivo = c.get("original") or ""
        elif estado == "sem_original":
            como, arquivo = ("realocado" if c.get("realocado") else "proxy"), no_disco(p, c)
        else:
            como, arquivo = "", ""
        codec = (_SONDA.get(arquivo) or {}).get("codec") if arquivo else None
        if not codec or codec == "unknown":
            codec = os.path.splitext(arquivo or p)[1].lstrip(".").upper() if (arquivo or p) else ""
        fora.append({"caminho": p, "nome": os.path.basename(p.replace("\\", "/")) or "(caminho recusado)",
                     "codec": codec, "estado": estado, "como": como, "arquivo": arquivo,
                     "origem": (declarados or {}).get(p, "") if recusado(p) else p, "recusado": recusado(p),
                     # o arquivo que o projeto declara está no disco: o clipe está ONLINE hoje ("só offline" o deixa)
                     "online": not recusado(p) and os.path.isfile(p),
                     **({"duvida": c["duvida"]} if c.get("duvida") else {})})
    return fora


def lista_de_sons(segmentos: list[dict], sons: dict[str, dict]) -> list[dict]:
    """As linhas dos SONS para a lista de mídias (o som que não é o do vídeo: o direto, a música, os efeitos), no formato de
    `lista_de_midias` com `som` verdadeiro: no lugar → `proprio`; achado noutra pasta pela duração (`relocar_sons`) →
    `mudou`; nada → "nao_encontrado" (entra offline no lugar)."""
    video = {s["media_ref"]["local_path"] for s in segmentos if s.get("media_ref") and not s.get("is_audio")}
    vistos, fora = set(), []
    for s in segmentos:
        p = (s.get("media_ref") or {}).get("local_path") if s.get("is_audio") else None
        if not p or p in video or p in vistos:
            continue
        vistos.add(p)
        x = sons.get(p) or {}
        if x.get("realocado"):
            estado, como, arquivo = "original", "mudou", x["realocado"]
        elif p not in sons and not recusado(p) and os.path.isfile(p):
            estado, como, arquivo = "original", "proprio", p
        else:
            estado, como, arquivo = "nao_encontrado", "", ""
        nome = os.path.basename(p.replace("\\", "/")) or "(caminho recusado)"
        fora.append({"caminho": p, "nome": nome, "codec": os.path.splitext(nome)[1].lstrip(".").upper(),
                     "estado": estado, "como": como, "arquivo": arquivo, "origem": "" if recusado(p) else p,
                     "recusado": recusado(p), "som": True, "online": como == "proprio"})
    return sorted(fora, key=lambda m: m["nome"].lower())


def faltam_sem_ignorados(casamento: dict, ignorar: set[str] | None) -> list[str]:
    """O "no proxy" do relatório, sem os que o editor IGNOROU. ⚠️ O ignorar é só para o original
    ausente: o arquivo que nem o proxy existe continua no relatório (autor, 2026-10-06)."""
    ignorar = ignorar or set()
    return sorted(os.path.basename(p.replace("\\", "/")) or "(caminho recusado)" for p, c in casamento.items()
                  if c["estado"] not in ("original", "proprio")
                  and not (p in ignorar and p and os.path.isfile(no_disco(p, c))))


def resumir(segs: list[dict], casamento: dict, declarados: dict | None = None) -> dict:
    """As contagens da tela "antes de montar": planos, originais, e o que cada efeito vira."""
    video = [s for s in segs if not (s.get("is_gap") or s.get("is_transition") or s.get("is_audio")
                                     or s.get("referencia"))]
    planos = [s for s in video if not s.get("is_effect")]
    ref = next((s for s in segs if s.get("referencia") and not s.get("is_audio")), None)
    # imagem parada ("proprio") conta como resolvida: o arquivo do corte JÁ é o final
    no_original = sum(1 for s in planos
                      if (casamento.get(s["media_ref"]["local_path"]) or {}).get("estado")
                      in ("original", "proprio"))
    estados: dict[str, int] = {}
    for c in casamento.values():
        estados[c["estado"]] = estados.get(c["estado"], 0) + 1
    conta = {"velocidade": 0, "keyframes": 0, "crop_flip": 0, "fusion": 0, "luma_key": 0,
             "graficos": sum(1 for s in video if s.get("is_effect")),
             "nests": len({s["composto"]["id"] for s in video if s.get("composto")})}
    sem_traducao: dict[str, int] = {}
    for s in planos:
        p = ((s.get("effects") or [{}])[0] or {}).get("params") or {}
        conta["velocidade"] += bool(s.get("has_motion_effect"))
        conta["keyframes"] += bool(p.get("kf"))
        conta["crop_flip"] += bool(p.get("crop_frac") or p.get("flip_x") or p.get("flip_y"))
        conta["luma_key"] += p.get("composite") == "screen"
        conta["fusion"] += any(e.get("category") == "fusion" for e in s.get("effects") or [])
        for e in s.get("effects") or []:
            if not e.get("reproducible"):
                sem_traducao[e["name"]] = sem_traducao.get(e["name"], 0) + 1
    faltam = sorted(os.path.basename(p.replace("\\", "/")) or "(caminho recusado)" for p, c in casamento.items()
                    if c["estado"] not in ("original", "proprio"))
    return {"planos": len(planos), "no_original": no_original, "arquivos": len(casamento),
            "midias": lista_de_midias(casamento, declarados),
            "casamento": estados, "faltam": faltam, "efeitos": conta,
            "sem_traducao": dict(sorted(sem_traducao.items(), key=lambda kv: -kv[1])),
            "audio": _resumo_audio([s for s in segs if not s.get("referencia")]),
            "referencia": {"arquivo": ref["clip_name"], "trilha": ref["track"],
                           "com_som": any(s.get("is_audio") and s.get("referencia") for s in segs)}
                          if ref else None}


def montar(prproj: str, sequencia: str, saida: str, originais: list[str],
           referencia: str | None = None, analise: dict | None = None, marcar: bool = False,
           colorir: bool = False, codigo_de_cores: dict | None = None, audio: bool = True,
           som_da_referencia: str | None = "A", compostos: bool = True,
           andamento=None, ignorar: set[str] | None = None, notas: bool = False,
           reescalar: dict[str, float] | None = None, proporcao_do_arquivo: set[str] | None = None) -> dict:
    """O DRT e o `.relatorio.json`. `analise` = o que `analisar` devolveu (senão, analisa aqui).
    `marcar`/`colorir`: os Sinais do Import — um marcador de timeline por plano que pede atenção
    e a cor LOCAL do clipe (memória `marcar-na-timeline-cor-local`).
    `compostos`: cada NEST do Premiere vira um Compound Clip (a casca o cria depois do Fusion);
    desligado, o nest fica aberto em trilhas — o que o manual da CASA-POS-1 pede (decisão do autor,
    2026-10-04: opção no painel, padrão ligado).
    `andamento(feitos, total, atual, detalhe)`: o do `build_drt` (a barra real da etapa "montando").
    `ignorar`: caminhos de proxy que o editor marcou na "lista de mídias" — sem o marcador "REFAZER no
    original" (o arquivo ainda entra pelo proxy). Não vale para "arquivo não encontrado".
    `proporcao_do_arquivo`: caminhos da oferta de `proporcoes_de_outra_midia` que o editor aceitou — o arquivo entra na
    proporção dele, sem o esticamento do Premiere.
    `reescalar`: {caminho do projeto: fator} que o editor ACEITOU na oferta de `escalas_de_outra_midia`; os outros
    suspeitos entram como o projeto diz, com marcador amarelo (decisão do autor, 2026-10-18)."""
    import copy

    ignorar = set(ignorar or ())
    analise = analise or analisar(prproj, sequencia, originais)
    leitura, casamento = analise["leitura"], analise["casamento"]
    segs = copy.deepcopy(leitura["segmentos"])
    fps = leitura["fps"]
    nominal = round(fps)
    segs = _referencia(segs, referencia, som_da_referencia, fps, nominal)
    if not audio and som_da_referencia != "B":
        # a caixa "trazer o áudio" desligada: só a imagem (o caso do colorista)
        segs = [x for x in segs if not x.get("is_audio")]

    match_results, marcas, fusion, luts, cor, vinhetas = [], [], [], [], [], []
    audio_sem_arquivo = 0
    offline: dict[str, dict] = {}     # {caminho ausente: metadados} → `build_drt(offline=…)`
    for i, s in enumerate(segs):
        if s.get("is_gap") or s.get("is_transition"):
            continue
        if s.get("referencia"):
            # o vídeo de referência (e o som dele): o próprio arquivo, sem casamento nem marcador
            caminho = s["media_ref"]["local_path"]
            if caminho and not recusado(caminho) and os.path.isfile(caminho):
                s["arquivo"] = caminho
                match_results.append({"segment_index": i, "matched_path": caminho})
            continue
        if s.get("is_audio"):
            # O som de câmera SEGUE o casamento do vídeo (decisão do autor, 2026-10-04: o proxy
            # nasceu do ARRIRAW com o áudio dele; medido, o ARRIRAW do PRODUCAO_B tem 5 canais): o
            # canal N do proxy → o canal N do original. O som direto (WAV) já é o original. Sem
            # marcador: o áudio não marca clipe a clipe.
            proxy = s["media_ref"]["local_path"]
            c = casamento.get(proxy) or (analise.get("sons") or {}).get(proxy) or {}
            caminho = c["original"] if c.get("estado") == "original" else no_disco(proxy, c)
            if c.get("estado") == "original":
                _deslocar_trecho(s, c.get("trecho"))
            if not caminho or recusado(caminho):
                audio_sem_arquivo += 1        # caminho recusado pela tranca: não há o que apontar
                continue
            if not os.path.isfile(caminho):
                # ⭐ NENHUM SEGMENTO SE PERDE (autor, 2026-10-06): o som ausente entra OFFLINE no mesmo
                # lugar, apontando para o arquivo do projeto — o editor religa no Resolve depois.
                audio_sem_arquivo += 1
                _anotar_offline(offline, caminho, s, fps)
            s["arquivo"] = caminho
            match_results.append({"segment_index": i, "matched_path": caminho})
            continue
        ini = _tc_frames(s["timeline_tc_in"], nominal)
        if s.get("ajuste"):
            # camada de AJUSTE → Adjustment Clip (o writer); com a LUT da Lumetri, ela vai no nó
            # depois do import (`luts` do relatório) e o editor confere. Sem efeito: equivalente exato.
            lut = next((e["params"].get("lut") for e in s.get("effects") or []
                        if e.get("category") == "ajuste"), None)
            if lut:
                luts.append({"trilha": s["track"], "quadro": ini, "arquivo": "Adjustment Clip",
                             "duracao": s["duration_frames"], "segmento": i,
                             "preset": lut.get("preset") or "", "intensidade": lut.get("intensidade"),
                             "itx3_b64": lut["itx3_b64"]})
                marcas.append({"quadro": ini, "cor": "Yellow", "segmento": i,
                               "tipo": "Ajuste com LUT",
                               "nota": "camada de ajuste → Adjustment Clip com a LUT da Lumetri "
                                       f"({os.path.basename((lut.get('preset') or 'LUT').replace(chr(92), '/'))}, "
                                       f"{lut.get('intensidade'):g}%): conferir",
                               "trilha": s["track"], "duracao": s["duration_frames"]})
            continue
        if s.get("is_effect"):
            titulo = any(e.get("category") == "title" for e in s.get("effects") or [])
            nota = ("título do Premiere recriado como Text: conferir cor, corpo e posição"
                    if titulo else "gráfico do Premiere sem tradução: refazer")
            marcas.append({"quadro": ini, "cor": "Yellow", "nota": nota, "segmento": i,
                           "tipo": "Título recriado" if titulo else "Gráfico sem tradução",
                           "trilha": s["track"], "duracao": s["duration_frames"]})
            continue
        proxy = s["media_ref"]["local_path"]
        c = casamento.get(proxy) or {}
        if c.get("estado") in ("original", "proprio"):
            caminho = c["original"]
            if _deslocar_trecho(s, c.get("trecho")):
                marcas.append({"quadro": ini, "cor": "Yellow", "trilha": s["track"], "duracao": s["duration_frames"],
                               "segmento": i, "arquivo": os.path.basename(proxy.replace("\\", "/")),
                               "tipo": "Trecho do original", "nota": f"conferir: {c['trecho']['motivo']}"})
            if c.get("duvida"):
                # o convertido de TC zerado/ausente, a única mídia (2026-10-31): entra, a conferir
                marcas.append({"quadro": ini, "cor": "Yellow", "trilha": s["track"], "duracao": s["duration_frames"],
                               "segmento": i, "arquivo": os.path.basename(proxy.replace("\\", "/")),
                               "tipo": "TC a conferir", "nota": f"conferir: {c['duvida']}"})
        elif os.path.exists(no_disco(proxy, c)):
            caminho = no_disco(proxy, c)
            # IGNORADO pelo editor ("se não tem versão em alta, tudo bem": a máscara de letterbox do
            # PRODUCAO_B): entra pelo proxy, como sempre, mas sem o marcador de falso positivo.
            if proxy not in ignorar:
                motivo = c.get("duvida") or _MOTIVO.get(c.get("estado"), "sem original")
                marcas.append({"quadro": ini, "cor": "Red", "nota": f"REFAZER no original: {motivo}",
                               "tipo": "Sem o original",
                               "trilha": s["track"], "duracao": s["duration_frames"], "segmento": i,
                               "arquivo": os.path.basename(proxy.replace("\\", "/"))})
        else:
            marcas.append({"quadro": ini, "cor": "Red", "nota": "arquivo não encontrado (nem proxy)",
                           "tipo": "Arquivo não encontrado",
                           "trilha": s["track"], "duracao": s["duration_frames"], "segmento": i,
                           "arquivo": os.path.basename(proxy.replace("\\", "/"))})
            if not proxy or recusado(proxy):
                continue                  # caminho recusado pela tranca: não há o que apontar
            # ⭐ NENHUM SEGMENTO SE PERDE (autor, 2026-10-06: o .prproj sem mídia no disco virava timeline
            # VAZIA). O plano entra OFFLINE no mesmo quadro, com o In e a duração do projeto, apontando
            # para o arquivo que o projeto declara, e o item vai ao Media Pool: o editor conecta o HD e
            # religa pelo Resolve. O marcador vermelho acima é complemento, não substituto.
            caminho = proxy
            _anotar_offline(offline, caminho, s, fps)
        s["arquivo"] = caminho
        match_results.append({"segment_index": i, "matched_path": caminho})
        prop = (analise.get("proporcoes") or {}).get(proxy)
        manter = bool(prop) and proxy in (proporcao_do_arquivo or ())
        if os.path.isfile(caminho) and not manter:
            _encaixar_no_arquivo(s, caminho, (leitura.get("largura"), leitura.get("altura")))
        if prop:
            marcas.append({"quadro": ini, "cor": "Yellow", "trilha": s["track"], "duracao": s["duration_frames"],
                           "segmento": i, "arquivo": os.path.basename(proxy.replace("\\", "/")), "tipo": "Proporção de outra mídia",
                           "nota": (f"proporção do próprio arquivo ({prop['para'][0]}×{prop['para'][1]}), não a do projeto "
                                    f"({prop['de'][0]}×{prop['de'][1]}): conferir" if manter else
                                    f"esticado para a proporção do projeto ({prop['de'][0]}×{prop['de'][1]}), que foi religado "
                                    f"a outro arquivo: conferir")})
        oferta = (analise.get("escalas") or {}).get(proxy)
        if oferta:
            aceito = (reescalar or {}).get(proxy)
            if aceito:
                _reescalar(s, aceito)
            marcas.append({"quadro": ini, "cor": "Yellow", "trilha": s["track"], "duracao": s["duration_frames"],
                           "segmento": i, "arquivo": os.path.basename(proxy.replace("\\", "/")), "tipo": "Escala de outra mídia",
                           "nota": (f"escala × {aceito:g} (digitada para outra mídia, ajustada no import): conferir"
                                    if aceito else
                                    f"escala parece digitada para outra mídia (sugerido × {oferta['fator']:g}): conferir")})
        variavel = taxa_variavel(caminho) if os.path.isfile(caminho) else None
        if variavel:
            # O Resolve conta o arquivo pela taxa do cabeçalho; com quadros faltando, ele não garante
            # o quadro exato (medido 2026-10-05 em sintéticos: de 0 a 17 quadros). A entrada já vem
            # convertida pela taxa do Resolve (writer); o plano pede o olho do editor.
            marcas.append({"quadro": ini, "cor": "Yellow", "trilha": s["track"],
                           "duracao": s["duration_frames"], "segmento": i, "tipo": "Taxa variável",
                           "arquivo": os.path.basename(caminho.replace("\\", "/")),
                           "nota": f"conferir o tempo: o arquivo tem taxa variável ({variavel[0]:.3g} q/s no "
                                   f"cabeçalho, {variavel[1]:.3g} de média) e o Resolve pode mostrar outro quadro"})
        if s.get("motion_effect_type") == "reverse":
            # O reverso do Resolve precisa da duração do arquivo (`build_reverse_timemap`); sem ela
            # o writer deixa o clipe tocar PARA FRENTE, a partir do fim do plano — calado até a
            # revisão de código de 2026-10-03. Agora o plano leva o aviso.
            nb, fps_m, _tc = _media_meta(caminho)
            if not (nb and fps_m):
                marcas.append({"quadro": ini, "cor": "Red", "trilha": s["track"],
                               "duracao": s["duration_frames"], "segmento": i,
                               "tipo": "Reverso sem duração",
                               "nota": "REFAZER o reverso: o arquivo não informou a duração, o "
                                       "plano entrou tocando para frente"})
        # vídeo DESLIGADO não entra na timeline (`drp/writer.py`, a regra do Resolve 19): nada a aplicar depois do import
        for e in ([] if s.get("disabled") else s.get("effects", [])):
            if e.get("category") == "fusion":
                fusion.append({"quadro": ini, "trilha": s["track"], "duracao": s["duration_frames"],
                               "arquivo": os.path.basename(caminho.replace("\\", "/")), "nome": e["name"],
                               "receita": e["params"], "segmento": i})
                marcas.append({"quadro": ini, "cor": "Yellow", "segmento": i,
                               "tipo": "Efeito no Fusion",
                               "nota": f"conferir: {e['name']}", "trilha": s["track"],
                               "duracao": s["duration_frames"]})
            if e.get("category") == "lut":
                # a COR da Lumetri (Input LUT do master clip, look e curvas do item) numa LUT no nó 1 do clipe, depois do
                # import — o mesmo caminho da LUT da camada de ajuste (`_gravar_luts` → .cube; casca `aplicarLuts`, `drp.luts`)
                luts.append({"trilha": s["track"], "quadro": ini, "arquivo": os.path.basename(caminho.replace("\\", "/")),
                             "duracao": s["duration_frames"], "segmento": i, "etapas": e["params"]["etapas"]})
            if e.get("category") == "vinheta":
                # a VIGNETTE da página Color (2027) → o nó "Vinheta" (janela circular invertida + Gain) no `.drx` do
                # clipe, ANTES das LUTs (o nó 1 fica vazio para elas): o pedido `vinheta` da `drp.cor_mc`. A janela foi
                # medida em 1920×1080: as medidas em px escalam pela altura da sequência
                k = (leitura.get("altura") or 1080) / 1080.0
                v = e["params"]["vinheta"]
                vinhetas.append({"trilha": s["track"], "quadro": ini,
                                 "arquivo": os.path.basename(caminho.replace("\\", "/")),
                                 "vinheta": {**v, "raio_px": v["raio_px"] * k, "borda_px": v["borda_px"] * k}})
                marcas.append({"quadro": ini, "cor": "Yellow", "segmento": i, "tipo": "Vinheta",
                               "nota": "Vignette → nó Vinheta (janela circular): conferir",
                               "trilha": s["track"], "duracao": s["duration_frames"]})
            if e.get("category") == "cor":
                # Black & White → nó de cor com saturação 0, no clipe, depois do import — o mesmo caminho das LUTs
                # (`relatorio["luts"]`, entrada sem `cube`): casca `aplicarLuts`, Python `drp.luts.aplicar_luts`
                cor.append({"trilha": s["track"], "quadro": ini, "arquivo": os.path.basename(caminho.replace("\\", "/")),
                            "duracao": s["duration_frames"], "segmento": i,
                            "saturacao": float(e["params"].get("saturacao", 0.0))})
                marcas.append({"quadro": ini, "cor": "Yellow", "segmento": i, "tipo": "Preto e branco",
                               "nota": "Black & White → nó de cor com saturação 0: conferir",
                               "trilha": s["track"], "duracao": s["duration_frames"]})
        nao = [e["name"] for e in s.get("effects", []) if not e.get("reproducible")]
        if nao:
            marcas.append({"quadro": ini, "cor": "Yellow", "nota": "conferir: " + ", ".join(nao),
                           "tipo": "Efeito sem tradução",
                           "trilha": s["track"], "duracao": s["duration_frames"], "segmento": i})

    # Plano do Fusion que não se monta (ex.: Crop com máscara depois de outro efeito): o clipe
    # precisa de REFAZER, não de "conferir" (revisão de código, 2026-10-03).
    planos = agrupar(fusion)
    for g in planos:
        if not g.get("plano"):
            marcas.append({"quadro": g["quadro"], "cor": "Red", "trilha": g["trilha"],
                           "duracao": g.get("duracao") or 1, "segmento": g.get("segmento"),
                           "tipo": "Refazer no Fusion",
                           "nota": f"REFAZER à mão no Fusion: {' + '.join(g['nomes'])} ({g['erro']})"})
    grupos = _compostos(segs, match_results, nominal) if compostos else []
    # A TRILHA DE NOTAS (opção "Criar a trilha de notas"): o mesmo `notas.das_notas` do caminho do Avid —
    # ela nunca tinha sido ligada no Premiere (o autor: "a trilha de notas não está sendo gerada",
    # 2026-10-06). O vídeo de referência não é plano da montagem: fica sem nota.
    lista_notas = None
    if notas:
        from notas import das_notas
        lista_notas = [n for n in das_notas({"segments": segs, "timeline_fps": fps, "masters": {}})
                       if n.get("segmento") is None or not segs[n["segmento"]].get("referencia")]
    # o NOME da sequência (o `sequencia` pode ser o ObjectUID que o painel manda)
    res = build_drt(segs, match_results, saida, timeline_name=leitura["nome"], timeline_fps=fps,
                    notas=lista_notas,
                    timeline_size=(leitura["largura"], leitura["altura"]),
                    timeline_start_frames=leitura.get("inicio", 0),
                    sinais=_sinais_das_marcas(marcas), marcar=marcar, colorir=colorir,
                    codigo_de_cores=codigo_de_cores, andamento=andamento, offline=offline)
    relatorio = {
        "prproj": prproj, "premiere": leitura["premiere"], "sequencia": leitura["nome"],
        # os arquivos que entraram OFFLINE (o segmento existe na timeline; falta o arquivo no disco)
        "offline": sorted(offline),
        "sequencia_uid": sequencia if sequencia != leitura["nome"] else None,
        "fps": fps, "quadro": [leitura["largura"], leitura["altura"]],
        "planos": sum(1 for s in segs if not (s.get("is_gap") or s.get("is_transition"))),
        "arquivos": len(casamento), "casamento": analise["resumo"]["casamento"],
        "resumo": analise["resumo"],
        "audio": {"trazido": audio, "sem_arquivo": audio_sem_arquivo},
        "trilha_referencia": next((x["track"] for x in segs if x.get("referencia")
                                   and not x.get("is_audio")), None),
        "avisos": leitura["avisos"], "marcadores": marcas,
        # composições a criar DEPOIS do import, uma por clipe, com o plano pronto (os nós e as
        # ligações): `drp.fusion_clipe.aplicar_relatorio` ou a casca (`aplicarFusion`)
        "fusion": planos,
        # os nests do Premiere a juntar em Compound Clip DEPOIS do Fusion (a casca:
        # `aplicarCompostos`; em Python, `drp.compostos.aplicar_compostos`)
        "compostos": grupos,
        # as LUTs das camadas de ajuste, a aplicar no nó do Adjustment Clip DEPOIS do import (a casca:
        # `aplicarLuts`; em Python, `drp.luts.aplicar_luts`) — o .cube já na intensidade da Lumetri
        "luts": _gravar_luts(luts, saida) + cor,
        # a cor EDITÁVEL na página Color do Resolve (aqui: a Vignette da página Color → o nó "Vinheta"), aplicada pelo
        # `.drx` ANTES das LUTs (`drp.cor_mc.aplicar_cor_mc`, a mesma rota da cor do Avid)
        "cor_mc": vinhetas,
        # A conferência pela referência (organograma de 2026-10-04): os pontos visíveis do filme
        # e onde a referência está — `servico/conferencia.py` os usa depois do import.
        "conferencia": _conferencia(segs, nominal, fps, leitura),
        # o arquivo de cada plano (vídeo, som, referência) — a lista da mídia PRÉ-importada (`sessao_receber._gravar_midias`)
        "casados": match_results,
        "pendentes": {p: {k: c[k] for k in ("estado", "candidatos", "recusados", "duvida") if k in c}
                      for p, c in casamento.items() if c["estado"] not in ("original", "proprio")},
        "drt": res,
    }
    with open(os.path.splitext(saida)[0] + ".relatorio.json", "w", encoding="utf-8") as f:
        json.dump(relatorio, f, ensure_ascii=False, indent=1, default=str)
    return relatorio


def _gravar_luts(luts: list[dict], saida: str) -> list[dict]:
    """Cada LUT vira um .cube ao lado do DRT (`<nome>_LUTs/`): a da camada de ajuste, já na intensidade da Lumetri
    (`prproj.leitura.lut_itx3_para_cube`); a de um plano, as `etapas` compostas (`lut_composta`: Input LUT do master
    clip, look, curvas). Devolve as entradas do relatório, sem o blob."""
    import hashlib
    import json
    from prproj.leitura import lut_composta, lut_itx3_para_cube
    out, feitos = [], {}
    pasta = os.path.splitext(saida)[0] + "_LUTs"
    impressao: dict[str, str] = {}          # o md5 de cada blob ITX3, uma vez só (são ~600 KB cada)

    def _md5(b64: str) -> str:
        if b64 not in impressao:
            impressao[b64] = hashlib.md5(b64.encode()).hexdigest()
        return impressao[b64]
    for x in luts:
        etapas = x.get("etapas") or [{k: x[k] for k in ("preset", "intensidade", "itx3_b64")}]
        so_uma = len(etapas) == 1 and etapas[0].get("itx3_b64")
        if so_uma:              # uma LUT da Lumetri só: o .cube com o nome dela, na intensidade — e a impressão do conteúdo
            nome = os.path.splitext(os.path.basename((etapas[0].get("preset") or "LUT").replace(chr(92), "/")))[0]
            intens = float(etapas[0].get("intensidade") or 100.0)
            # dois blobs diferentes com o mesmo nome de arquivo (ou sem nome) não podem dividir o .cube (revisão 2026-10-10)
            base = f"{nome}_{intens:g}pct_{_md5(etapas[0]['itx3_b64'])[:6]}"
        else:                   # LUT + curvas: o nome é o conteúdo — planos com a mesma cor dividem o .cube
            chave = [{k: (_md5(v) if k == "itx3_b64" else v) for k, v in e.items()} for e in etapas]
            base = "LUMETRI_" + hashlib.md5(json.dumps(chave, sort_keys=True).encode()).hexdigest()[:10]
        arq = os.path.join(pasta, re.sub(r'[<>:"/\\|?*]', "_", base + ".cube"))
        if arq not in feitos:
            os.makedirs(pasta, exist_ok=True)
            with open(arq, "w", encoding="ascii", errors="replace", newline="\n") as f:
                f.write(lut_itx3_para_cube(etapas[0]["itx3_b64"], intens, f"{nome} {intens:g}%") if so_uma
                        else lut_composta(etapas, base))
            feitos[arq] = True
        partes = [os.path.basename((e.get("preset") or ("curvas" if e.get("curvas") else "LUT")).replace(chr(92), "/"))
                  for e in etapas]
        out.append({k: x[k] for k in ("trilha", "quadro", "arquivo", "duracao", "segmento") if k in x}
                   | {"preset": " + ".join(partes), "intensidade": etapas[0].get("intensidade"), "cube": arq})
    return out


def _conferencia(segs: list[dict], nominal: int, fps: float, leitura: dict) -> dict | None:
    """O que a conferência pela referência precisa, ou `None` sem vídeo de referência: os pontos
    (quadro desde o INÍCIO da timeline), o arquivo da referência, a trilha dela e o mapa
    timeline → quadro da referência (início na timeline + entrada no arquivo)."""
    ref = next((x for x in segs if x.get("referencia") and not x.get("is_audio")
                and (x.get("media_ref") or {}).get("local_path")), None)
    if ref is None:
        return None
    return {"referencia": ref["media_ref"]["local_path"], "trilha_referencia": ref["track"],
            "ref_na_timeline": _tc_frames(ref["timeline_tc_in"], nominal),
            "ref_entrada": int(ref.get("source_start_frames") or 0),
            "ref_fps": float(ref.get("source_fps") or fps), "fps": fps, "nominal": nominal,
            "inicio": int(leitura.get("inicio") or 0),
            "quadro_px": [leitura["largura"], leitura["altura"]],
            "pontos": pontos_visiveis(segs, nominal)}


def conferencia_da_analise(analise: dict, referencia: str | None) -> dict | None:
    """O plano da conferência pela referência SEM escrever o DRT — o Premiere → Premiere (2026-10-22): a timeline é a
    cópia da própria sequência, então os pontos são os mesmos que o `montar` daria. `None` sem referência."""
    import copy

    leitura = analise["leitura"]
    fps = leitura["fps"]
    nominal = round(fps)
    segs = _referencia(copy.deepcopy(leitura["segmentos"]), referencia, None, fps, nominal)
    return _conferencia(segs, nominal, fps, leitura)


def _compostos(segs: list[dict], match_results: list[dict], nominal: int) -> list[dict]:
    """Os clipes de VÍDEO de cada nest, como a casca os acha na timeline (trilha, quadro desde o
    início, nome do arquivo — o mesmo endereço do Fusion). Só entra o que o writer pôs na timeline:
    o plano sem arquivo nenhum não existe lá, e o compound se faz com o resto."""
    na_timeline = {m["segment_index"]: m["matched_path"] for m in match_results}
    grupos: dict[str, dict] = {}
    for i, s in enumerate(segs):
        c = s.get("composto")
        if not c or s.get("is_audio") or i not in na_timeline:
            continue
        g = grupos.setdefault(c["id"], {"nome": c["nome"], "clipes": []})
        g["clipes"].append({"trilha": s["track"],
                            "quadro": _tc_frames(s["timeline_tc_in"], nominal),
                            "arquivo": os.path.basename(na_timeline[i])})
    return [g for g in grupos.values() if g["clipes"]]


def _referencia(segs: list[dict], arquivo: str | None, som: str | None, fps: float,
                nominal: int) -> list[dict]:
    """O vídeo de REFERÊNCIA (regra de ofício do autor, 2026-10-03/04; banco `operacoes-de-nle.md`
    J.3b). `arquivo` = a indicada À MÃO: entra numa trilha de vídeo NOVA acima de todas, desligada,
    do quadro 0 (a de notas, se houver, nasce acima dela no writer). Sem `arquivo`, vale a que a
    leitura achou na timeline (`referencia`). O SOM dela, por `som`:
      "A" — numa trilha NOVA abaixo de todo o áudio, com SOLO (`<Flags>32` da trilha, medido);
      "B" — SÓ o som da referência: nenhum outro áudio da timeline (o caso do colorista);
      None — sem o som da referência.
    Estéreo vira dois mono (L e R), como o resto do áudio; a trilha estéreo nativa está por medir."""
    if arquivo:
        for x in segs:                          # a indicada à mão substitui a achada
            x.pop("referencia", None)
            x.pop("trilha_desligada", None)
        r = sondar(arquivo)
        n = round((r.get("dur_s") or 0) * (r.get("fps") or fps))
        topo = max((x["track"] for x in segs if not x.get("is_audio")), default=0) + 1
        nome = os.path.basename(arquivo)
        segs.append({"timeline_tc_in": frames_para_tc(0, nominal),
                     "timeline_tc_out": frames_para_tc(n, nominal), "duration_frames": n,
                     "source_start_frames": 0, "source_fps": r.get("fps") or fps,
                     "clip_name": nome, "track": topo, "referencia": True, "trilha_desligada": True,
                     "media_ref": {"mob_name": nome, "url": "", "local_path": arquivo,
                                   "descriptor_type": "referencia", "source_duration_frames": n,
                                   "source_fps": r.get("fps") or fps},
                     "is_gap": False, "is_transition": False, "is_effect": False,
                     "is_audio": False, "effects": [], "reframe_mode": "pillarbox",
                     "speed_ratio": 1.0, "relative_speed": 1.0, "conform_ratio": 1.0})
        from drp.writer import _audio_meta
        canais = (_audio_meta(arquivo)[3] or 0) if som else 0
        for k in range(min(canais, 2)):
            segs.append({"timeline_tc_in": frames_para_tc(0, nominal),
                         "timeline_tc_out": frames_para_tc(n, nominal), "duration_frames": n,
                         "source_start_frames": 0, "source_fps": fps, "clip_name": nome,
                         "track": 0, "canal_arquivo": k + 1, "referencia": True,
                         "media_ref": {"mob_name": nome, "url": "", "local_path": arquivo,
                                       "descriptor_type": "referencia"},
                         "is_gap": False, "is_transition": False, "is_effect": False,
                         "is_audio": True, "effects": [], "speed_ratio": 1.0,
                         "relative_speed": 1.0, "conform_ratio": 1.0})
    som_ref = [x for x in segs if x.get("is_audio") and x.get("referencia")
               and not (x.get("is_gap") or x.get("is_transition"))]
    resto = [x for x in segs if not (x.get("is_audio") and x.get("referencia"))]
    if som is None or not som_ref:
        return resto
    if som == "B":
        resto = [x for x in resto if not x.get("is_audio")]
        base = 1000
    else:
        base = max((x["track"] for x in resto if x.get("is_audio")), default=999) + 1
    canais = sorted({x.get("canal_arquivo") or 1 for x in som_ref})
    for x in som_ref:
        x["track"] = base + canais.index(x.get("canal_arquivo") or 1)
        x["solo"] = som == "A"                  # o writer grava como `<Flags>32` na trilha
    return resto + som_ref


def trilha_rotulo(trilha, audio: bool = False) -> str:
    """"Trk V1" / "Trk A1": o rótulo de trilha nos marcadores (autor, 2026-10-04: "V1" sozinho não
    se lia de imediato como a trilha de vídeo 1)."""
    return f"Trk {'A' if audio else 'V'}{trilha}"


def _sinais_das_marcas(marcas: list[dict]) -> list[dict]:
    """As marcas → as notas que o writer transforma em Sinais (`drp/writer._sinais`): UMA por
    plano, com todas as linhas, na cor mais forte (refazer > conferir). O NOME do marcador é o
    TIPO do problema mais forte; as observações (todas) vão nas Notes, cada uma com a trilha
    (autor, 2026-10-04: nome e notas diziam a mesma coisa)."""
    por: dict[int, dict] = {}
    for m in marcas:
        if m.get("segmento") is None:
            continue
        n = por.setdefault(m["segmento"], {"inicio": m["quadro"], "dur": m.get("duracao") or 1,
                                           "segmento": m["segmento"], "grupo": "efeito",
                                           "cor": "conferir", "linhas": [], "tipos": []})
        if m["cor"] == "Red":
            n["cor"] = "refazer"
        forte = m["cor"] == "Red"
        n["tipos"].append((not forte, m.get("tipo") or ("Refazer" if forte else "Conferir")))
        # a trilha na frente: no Resolve, os planos que começam juntos dividem UM marcador
        n["linhas"].append([(f"{trilha_rotulo(m['trilha'])} · {m['nota']}", None)])
    for n in por.values():
        # o pedido de REFAZER vem antes do "conferir"
        n["linhas"].sort(key=lambda linha: not linha[0][0].split(" · ", 1)[-1].startswith(("REFAZER", "arquivo")))
        n["tipo"] = sorted(n.pop("tipos"))[0][1]
        n["nome"] = " | ".join(linha[0][0] for linha in n["linhas"])
    return list(por.values())


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Uma sequência do Premiere → DRT do Resolve religado aos ORIGINAIS de câmera.")
    ap.add_argument("prproj")
    ap.add_argument("sequencia")
    ap.add_argument("saida")
    ap.add_argument("--originais", action="append", default=[])
    ap.add_argument("--referencia")
    ap.add_argument("--sem-audio", action="store_true", help="só a imagem")
    ap.add_argument("--som-da-referencia", choices=["A", "B", "nenhum"], default="A",
                    help="A = trilha nova abaixo de tudo, com solo; B = só o som da referência")
    ap.add_argument("--sinais", action="store_true",
                    help="marcador de timeline + cor local nos planos a refazer/conferir")
    ap.add_argument("--nest-aberto", action="store_true",
                    help="não pedir Compound Clip: o nest fica aberto em trilhas")
    a = ap.parse_args(argv)
    r = montar(a.prproj, a.sequencia, a.saida, a.originais, a.referencia,
               marcar=a.sinais, colorir=a.sinais, audio=not a.sem_audio,
               som_da_referencia=None if a.som_da_referencia == "nenhum" else a.som_da_referencia,
               compostos=not a.nest_aberto)
    print(json.dumps({k: r[k] for k in ("sequencia", "planos", "arquivos", "casamento",
                                        "trilha_referencia")}, ensure_ascii=False, indent=1))
    for g in r["compostos"]:
        print(f"compound: {g['nome']} ({len(g['clipes'])} clipes, a partir do quadro "
              f"{min(c['quadro'] for c in g['clipes'])})")
    print(f"marcadores: {len(r['marcadores'])}  avisos: {len(r['avisos'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
