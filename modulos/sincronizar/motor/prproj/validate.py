"""
Sincronizar — validador estrutural do PRPROJ.

Cada regra aqui é um bug que já custou uma sessão inteira de debug, e todas são
INVISÍVEIS ao abrir o arquivo: o Premiere ou crasha sem mensagem, ou abre e mente em
silêncio (áudio mudo, clipe que não seleciona, clipes numa pasta "Recovered Clips").

Rodar isto num `.prproj` gerado custa milissegundos e responde "o Premiere vai
engasgar?" sem precisar do Premiere. Não substitui abrir no NLE — nenhum validador
substitui —, mas pega de graça a classe de erro que a gente já cometeu.

As regras estão documentadas em
a base de conhecimento interna.
"""

from __future__ import annotations

import gzip
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


def validate(path: str | Path) -> list[str]:
    """Devolve a lista de problemas. Vazia = passou."""
    raw = gzip.open(str(path), "rt", encoding="utf-8").read()
    root = ET.fromstring(raw)
    return validate_root(root)


def validate_root(root: ET.Element) -> list[str]:
    problems: list[str] = []
    by_oid = {e.get("ObjectID"): e for e in root.iter() if e.get("ObjectID")}
    oids = set(by_oid)

    # ── UUIDs duplicados ─────────────────────────────────────────────────────
    # ObjectID repetido é NORMAL (os ids vivem em espaços de nome separados; o
    # template do Premiere tem 60). Quem precisa ser único é o ObjectUID.
    uids = [e.get("ObjectUID") for e in root.iter() if e.get("ObjectUID")]
    for uid, n in Counter(uids).items():
        if n > 1:
            problems.append(f"ObjectUID duplicado ({n}×): {uid}")

    # ── Referências penduradas ───────────────────────────────────────────────
    # <First> de um TrackGroup é o UUID do TIPO de mídia, não um ObjectRef: seria
    # falso positivo. Ele não usa ObjectRef, então não entra aqui de qualquer forma.
    for e in root.iter():
        ref = e.get("ObjectRef")
        if ref and ref not in oids:
            problems.append(f"<{e.tag}> aponta para um ObjectRef inexistente: {ref}")

    # ── Posições negativas ───────────────────────────────────────────────────
    # Nenhum NLE aceita. É o sintoma de uma origem que não foi normalizada.
    for s in root.iter("Start"):
        if s.text and s.text.lstrip("-").isdigit() and int(s.text) < 0:
            problems.append(f"TrackItem com Start negativo: {s.text}")

    # ── <InUse> em clip de TRACK ─────────────────────────────────────────────
    # Só clip de MASTER tem <InUse>. Num clip de track, ele torna o clipe de vídeo
    # não-selecionável com clique direto no corpo.
    sub_refs = {
        sc.find("Clip").get("ObjectRef")
        for sc in root.iter("SubClip")
        if sc.find("Clip") is not None
    }
    for tag in ("AudioClip", "VideoClip"):
        for c in root.iter(tag):
            if c.get("ObjectID") in sub_refs and c.find(".//InUse") is not None:
                problems.append(f"<{tag} oid={c.get('ObjectID')}> de TRACK tem <InUse>")

    # ── Link de vídeo SOLO ───────────────────────────────────────────────────
    # Cada Link agrupa o vídeo com o áudio que ocupa o MESMO tempo. Um vídeo sozinho
    # num Link não é selecionável com clique direto.
    video_tis = {e.get("ObjectID") for e in root.iter("VideoClipTrackItem")}
    for lk in root.iter("Link"):
        items = [i.get("ObjectRef") for i in lk.iter("TrackItem")]
        if len(items) == 1 and items[0] in video_tis:
            problems.append(f"Link com um vídeo SOLO (sem áudio): TrackItem {items[0]}")

    # ── Mídia bruta sem entrada na bin ───────────────────────────────────────
    # Um MasterClip alcançável só por um SubClip é despejado pelo Premiere numa pasta
    # automática "Recovered Clips".
    #
    # ⚠️ EXCEÇÃO: os MasterClips INTERNOS de um merged clip (a cópia da câmera e os
    # por-canal do som) não vão para a bin — nem no merged nativo. Eles se declaram
    # com as propriedades `MZ.MergeClipUtils.*`.
    in_bin = {
        cpi.find("MasterClip").get("ObjectURef")
        for cpi in root.iter("ClipProjectItem")
        if cpi.find("MasterClip") is not None
    }
    merged_internal = {
        mc.get("ObjectUID")
        for mc in root.iter("MasterClip")
        if any(p.tag.startswith("MZ.MergeClipUtils.")
               for p in mc.findall("./Node/Properties/*"))
    }
    for sc in root.iter("SubClip"):
        mc = sc.find("MasterClip")
        if mc is None:
            continue
        uid = mc.get("ObjectURef")
        if uid and uid not in in_bin and uid not in merged_internal:
            problems.append(
                f"MasterClip {uid} é usado por um SubClip mas não está na bin "
                "→ vira 'Recovered Clips'"
            )
            break   # um aviso basta; senão são dezenas iguais

    # ── Merged clip em CICLO — FECHA o Premiere ao abrir ─────────────────────
    # O MasterClip de bin de um merged tem como fonte a própria sequência merged. Um
    # SubClip que o use como alvo (em vez da cópia dedicada da câmera) fecha o ciclo
    # Sequence → SubClip → MasterClip → SequenceSource → Sequence, e o 25.6.5 morre
    # em AR::AudioPrefetch sem diálogo. Medido no 25.6.5, com projeto real.
    merged_seqs = {
        s.get("ObjectUID") for s in root.iter("Sequence")
        if s.get("ObjectUID") and s.findtext(".//BE.Sequence.IsMergedClip") == "true"
    }
    if merged_seqs:
        seq_sources = {
            obj.get("ObjectID") for obj in root
            if obj.get("ObjectID") and any(
                ref.get("ObjectURef") in merged_seqs
                for ref in obj.iter("Sequence"))
        }
        clips_on_merged = {
            c.get("ObjectID") for tag in ("AudioClip", "VideoClip")
            for c in root.iter(tag)
            if c.find("./Clip/Source") is not None
            and c.find("./Clip/Source").get("ObjectRef") in seq_sources
        }
        merged_bin_mcs = {
            mc.get("ObjectUID") for mc in root.iter("MasterClip")
            if any(cl.get("ObjectRef") in clips_on_merged
                   for cl in mc.findall("./Clips/Clip"))
        }
        for sc in root.iter("SubClip"):
            mc = sc.find("MasterClip")
            if mc is not None and mc.get("ObjectURef") in merged_bin_mcs:
                problems.append(
                    f"SubClip aponta para o MasterClip de um merged clip "
                    f"({mc.get('ObjectURef')}) → ciclo que FECHA o Premiere")
                break

    # ── A sequência é MULTICAM? ──────────────────────────────────────────────
    # Sem estes dois campos ela abre como sequência COMUM, fora do monitor multicam —
    # e a promessa do app some sem nenhum erro visível.
    for mc in root.iter("MasterClip"):
        enabled = mc.findtext(".//Source.Monitor.Multicam.Enabled")
        if enabled is None:
            continue
        if enabled == "true" and mc.findtext(".//Source.Monitor.Multicam.TrackIndex") is None:
            problems.append(
                f"sequência '{mc.findtext('Name')}': Multicam.Enabled=true sem "
                "Multicam.TrackIndex"
            )

    return problems
