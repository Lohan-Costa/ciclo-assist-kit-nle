"""As `Tomada` da aba de merged → um `.prproj` só com merged, e o aparo de cada um.

⭐ **O par é reconstruído da própria `Tomada`**, não de uma lista paralela: remover da
lista e editar cena mexem só nas tomadas guardadas no sidecar. Cada tomada do Premiere
tem exatamente dois `Trecho` (`premiere/tomadas.py`): o de imagem e o de som, ambos
começando no MESMO instante da timeline. Então:

    câmera     = trecho de imagem · mob_id (o caminho)
    som        = trecho de som    · mob_id
    corte_in   = imagem.start                 (frames no arquivo de câmera)
    corte_out  = imagem.start + duração
    sync       = som.start − imagem.start     (onde o frame 0 da câmera cai no som)

O `sync` é o `sync_offset_frames` que o builder espera: *"positivo → a câmera começa
depois do som"*.

## O aparo NÃO vai no arquivo

O merged sai do tamanho inteiro da câmera (a forma validada na GUI) e o painel aplica
in/out depois de importar — `setInPoint/setOutPoint` existem na tabela de
`ProjectItem`. ⚠️ Não medido num merged ainda: é o primeiro uso real.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import registro

from prproj.builder import ExportOptions, build_merged_only
from sync.model import (CameraAngle, CameraGroup, Daily, Project, SoundClip, Take,
                        duration_frames as _duration_frames)

log = registro.log(__name__)

TICKS_POR_SEGUNDO = 254016000000


@dataclass(frozen=True)
class Aparo:
    """O in/out de UM merged, em segundos desde o primeiro frame da câmera."""
    nome: str
    entrada: float
    saida: float


def _trechos(tomada):
    img = next((t for t in tomada.trechos if t.media_kind == "picture"), None)
    som = next((t for t in tomada.trechos if t.media_kind == "sound"), None)
    return img, som


def _tc_ticks(meta: dict, fps: float) -> int | None:
    from sync.tcmatch import tc_to_real_seconds

    seg = tc_to_real_seconds(meta.get("tc_start") or "", meta.get("fps") or fps,
                             bool(meta.get("tc_drop_frame")))
    if seg is None:
        return None
    tpf = round(TICKS_POR_SEGUNDO / fps)
    return round(seg * fps) * tpf


def soltos_de(tomadas, fps: float) -> list[dict]:
    """As tomadas sem som direto: o que o painel transforma em subclipe, com o in/out em segundos do arquivo."""
    saida = []
    for t in tomadas:
        img, som = _trechos(t)
        if img is not None and som is None and t.duracao > 0:
            saida.append({"caminho": img.mob_id, "nome": t.nome, "in": img.start / fps, "out": (img.start + t.duracao) / fps})
    return saida


def montar(tomadas, fps: float, probe=None) -> tuple[Daily, list[Aparo], list[str]]:
    """`(diária, aparos, ignoradas)` — a diária tem uma `Take` por tomada.

    `ignoradas` lista, pelo nome, as tomadas que não dá para escrever (sem imagem ou
    sem som, arquivo que o probe não lê).
    """
    if probe is None:
        from media.inspector import probe
    if fps <= 0:
        raise ValueError("fps da sequência inválido")

    metas: dict[str, dict] = {}

    def meta_de(caminho: str) -> dict:
        if caminho not in metas:
            metas[caminho] = probe(caminho) or {}
        return metas[caminho]

    takes: list[Take] = []
    cameras: list[CameraAngle] = []
    aparos: list[Aparo] = []
    ignoradas: list[str] = []
    for tomada in tomadas:
        img, som = _trechos(tomada)
        if img is not None and som is None and tomada.duracao > 0:
            continue                       # é um solto (`soltos_de`): vira subclipe, não merged
        if img is None or som is None or tomada.duracao <= 0:
            ignoradas.append(tomada.nome)
            continue
        try:
            mc, ms = meta_de(img.mob_id), meta_de(som.mob_id)
        except Exception as e:  # noqa: BLE001
            log.warning("probe falhou para %r: %s", tomada.nome, e)
            ignoradas.append(tomada.nome)
            continue
        if not mc.get("duration_ms") or not ms.get("duration_ms"):
            ignoradas.append(tomada.nome)
            continue

        cam = CameraAngle(
            path=Path(img.mob_id), fps=fps,
            # a MESMA conta do motor — um frame a mais aqui é um frame preto no fim
            duration_frames=_duration_frames(mc["duration_ms"], fps,
                                             mc.get("frame_count"), mc.get("fps")),
            sync_offset_frames=som.start - img.start,
            alternate_start_ticks=_tc_ticks(mc, fps),
            audio_channels=int(mc.get("total_audio_channels") or mc.get("channels") or 2),
        )
        snd = SoundClip(
            path=Path(som.mob_id),
            sample_rate=int(ms.get("sample_rate") or 48000),
            duration_ms=float(ms["duration_ms"]),
            channels=int(ms.get("channels") or 2),
        )
        takes.append(Take(sound=snd, cameras=[cam]))
        cameras.append(cam)
        # ⚠️ O out nunca passa do fim REAL da câmera: uma sequência exportada antes da
        # correção do frame a mais (2026-09-17) tem o item 1 frame mais longo que o
        # arquivo, e o aparo herdaria o frame preto.
        fim = min(img.start + tomada.duracao, cam.duration_frames)
        aparos.append(Aparo(nome=tomada.nome, entrada=img.start / fps, saida=fim / fps))

    daily = Daily(camera_groups=[CameraGroup(cameras=cameras, name="MERGED", id="merged")],
                  takes=takes, name="MERGED", fps=fps)
    return daily, aparos, ignoradas


def escrever(tomadas, fps: float, saida: Path, nome_da_bin: str, alvo: str = "25",
             probe=None) -> dict:
    """Escreve o `.prproj` só-merged e devolve o que o painel precisa para importar."""
    import time

    t0 = time.perf_counter()
    daily, aparos, ignoradas = montar(tomadas, fps, probe=probe)
    t1 = time.perf_counter()
    soltos = soltos_de(tomadas, fps)
    if not daily.takes:
        if soltos:      # só clipes soltos: não há `.prproj` a escrever, o painel faz os subclipes
            return {"arquivo": "", "bin": nome_da_bin, "aparos": [], "ignoradas": ignoradas, "soltos": soltos}
        raise ValueError("nenhuma tomada pôde ser escrita")
    nomes = {id(t.cameras[0]): a.nome for t, a in zip(daily.takes, aparos)}
    build_merged_only(
        Project(name=nome_da_bin, groups=[daily]), saida, nome_da_bin,
        ExportOptions(merged_clips=True, premiere_alvo=alvo),
        nome_de=lambda take, cam: nomes.get(id(cam), ""))
    # A 1ª rodada no app levou 15 s contra 0,2 s fora dele — o log diz onde está.
    log.info("merged: %d tomada(s) · mídia %.2f s · .prproj %.2f s", len(daily.takes),
             t1 - t0, time.perf_counter() - t1)
    # ⚠️ O Premiere NÃO usa o nome da linha da bin ao importar: o merged chega com o
    # nome do MasterClip interno, `<arquivo> - Merged` (medido no 23.2, 2026-09-17). Por
    # isso vai junto o nome com que ele CHEGA — o host o acha por ele e o renomeia.
    return {"arquivo": str(saida), "bin": nome_da_bin,
            "aparos": [{"nome": a.nome, "chega_como": t.cameras[0].path.name + " - Merged",
                        "in": a.entrada, "out": a.saida}
                       for t, a in zip(daily.takes, aparos)],
            "ignoradas": ignoradas, "soltos": soltos}
