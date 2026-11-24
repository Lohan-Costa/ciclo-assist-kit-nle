"""Vídeo INJETADO: o Media Composer linka UM arquivo por assinatura (o molde) e os irmãos saem clonados dele.

Ideia do autor (2026-10-18): "linka o primeiro, injeta os irmãos". Medido no MC 24.6 / Windows 11 no mesmo dia
(banco, `protocolos/avb/escrita.md` §"Linka o primeiro, injeta os irmãos"): 40 clones de 6 famílias iguais ao
`LinkFile` do próprio MC — colunas, descritores e cada componente de cada trilha —, e a imagem conferida no Source.

⭐ O MOTOR de leitura (a coluna `Plug-in`) vem do molde: o clone abre pelo mesmo plugin. É o caminho para o formato
que o autodetect erra (X-OCN × MXF nativo): o editor linka um pelo `Link with` certo e os irmãos o herdam.

⛔ Só clona o que foi medido; o resto volta ao `LinkFile` de quem chama, que é o caminho de sempre:

* o motor do molde está em `MOTORES_MEDIDOS` (o `descriptor.uuid` da fonte);
* o nome do molde é único na bin (o `clone_generic` acha o clipe pelo NOME);
* o clone conferido aponta para o arquivo novo e tem a duração esperada.

A assinatura inclui o DISCO: o molde grava o volume ("SSD (D:)"), e um irmão em outro disco sairia com o
volume errado.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

log = logging.getLogger("delapraca.avb_bin.video")

#: `descriptor.uuid` da fonte → o motor (coluna `Plug-in`). Medidos em 2026-10-18 (MC 24.6, Windows).
MOTORES_MEDIDOS = {
    "87a0584d-cafa-41f5-9a68-f0cadefdbb71": "UME Link",
    "bd449ccc-ff06-4f38-a2de-011870df8480": "Blackmagic RAW",
}


def assinatura(caminho: str) -> tuple | None:
    """(disco, extensão, codec, perfil, raster, taxa, pix_fmt, SAR, ordem de campo, áudio, tmcd?, XMP?) — o que faz
    dois arquivos saírem do MESMO molde. None se o ffprobe não ler (o arquivo vai sozinho)."""
    from media import fftools

    try:
        o = subprocess.run([fftools.ffprobe_exe(), "-v", "error", "-show_streams", "-of", "json", caminho],
                           capture_output=True, text=True, encoding="utf-8", timeout=60).stdout
        streams = json.loads(o or "{}").get("streams") or []
    except Exception:  # noqa: BLE001
        return None
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        return None
    audio = "+".join(f'{s.get("codec_name")}/{s.get("channels")}/{s.get("sample_rate")}'
                     for s in streams if s.get("codec_type") == "audio") or "-"
    tmcd = any(s.get("codec_tag_string") == "tmcd" or (s.get("tags") or {}).get("timecode") for s in streams)
    try:
        with open(caminho, "rb") as fh:
            xmp = b"startTimecode" in fh.read(8 * 1024 * 1024)
    except OSError:
        xmp = False
    disco = os.path.splitdrive(os.path.abspath(caminho))[0].upper() or "/"
    return (disco, Path(caminho).suffix.lower(), v.get("codec_name"), v.get("profile"),
            f'{v.get("width")}x{v.get("height")}', v.get("r_frame_rate"), v.get("pix_fmt"),
            v.get("sample_aspect_ratio"), v.get("field_order"), audio, tmcd, xmp)


def agrupar(caminhos: list[str]) -> list[list[str]]:
    """Os arquivos por assinatura, na ordem em que vieram; sem assinatura = um grupo de um."""
    grupos: dict[object, list[str]] = {}
    for i, c in enumerate(caminhos):
        chave = assinatura(c)
        grupos.setdefault(chave if chave is not None else ("sozinho", i), []).append(c)
    return list(grupos.values())


def _molde_na_bin(f, mob_id: str):
    """(nome, motor) do master `mob_id` na bin, ou (None, motivo) se não serve de molde."""
    masters = {str(m.mob_id): m for m in f.content.mobs if str(getattr(m, "mob_type", "")) == "MasterMob"}
    m = masters.get(str(mob_id))
    if m is None:
        return None, "o molde não está na bin"
    nome = m.name
    if sum(1 for x in masters.values() if x.name == nome) != 1:
        return None, f"há mais de um master chamado {nome!r} na bin"
    uuids = set()
    for x in f.content.mobs:
        d = x.property_data.get("descriptor") if x.name == nome else None
        if d is not None and d.property_data.get("uuid") is not None:
            uuids.add(str(d.property_data.get("uuid")))
    motor = next((MOTORES_MEDIDOS[u] for u in uuids if u in MOTORES_MEDIDOS), None)
    if motor is None:
        return None, "motor de leitura ainda não medido para injeção (" + ", ".join(sorted(uuids)) + ")"
    return nome, motor


def _conferir(alvo: Path, nome: str, caminho: str, ids_do_molde: set[str]) -> str | None:
    """O MobID do master clonado, se o clone aponta para `caminho`; None se não confere."""
    from avb_export.clone_generic import _forma_avid
    from avb_export.reader import topen

    esperado = _forma_avid(os.path.abspath(caminho))
    master = None
    caminho_ok = False
    with topen(str(alvo)) as f:
        for m in f.content.mobs:
            if m.name != nome or str(m.mob_id) in ids_do_molde:
                continue
            if str(getattr(m, "mob_type", "")) == "MasterMob":
                master = str(m.mob_id)
            d = m.property_data.get("descriptor")
            ph = d.property_data.get("physical_media") if d is not None else None
            loc = ph.property_data.get("locator") if ph is not None else None
            if loc is not None:
                p = loc.property_data.get("path") or loc.property_data.get("path_posix") or ""
                caminho_ok = caminho_ok or p == esperado or p == os.path.abspath(caminho)
    return master if master and caminho_ok else None


def injetar_irmaos(bin_moldes: str, grupos: list[tuple[str, list[str]]], saida: str, fps=None,
                   progresso=None) -> dict:
    """Clona cada irmão do seu molde (já linkado pelo MC em `bin_moldes`).

    Args:
        grupos: `[(mob_id do molde (str do pyavb), [arquivos irmãos])]`.
        saida: a bin com TODOS os clones (merge numa passada, como o áudio).

    Returns:
        `{"saida", "mapa": {arquivo → str(mob_id) do master}, "falhas": [(arquivo, motivo)], "motores": {..}}` — o
        arquivo em `falhas` não foi clonado e deve passar pelo `LinkFile`.
    """
    from avb_export.clone_generic import clone_generic
    from avb_export.merge import materialize, serialize
    from avb_export.reader import topen
    import random

    mapa: dict[str, str] = {}
    falhas: list[tuple[str, str]] = []
    motores: dict[str, str] = {}
    clones: list[Path] = []
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_video_"))
    with topen(bin_moldes) as f:
        ids_do_molde = {str(m.mob_id) for m in f.content.mobs}
        moldes = {mid: _molde_na_bin(f, mid) for mid, _ in grupos}
    total = sum(len(irmaos) for _, irmaos in grupos)
    feito = 0
    for mid, irmaos in grupos:
        nome, motor = moldes[mid]
        if nome is None:
            falhas += [(c, motor) for c in irmaos]
            feito += len(irmaos)
            continue
        for caminho in irmaos:
            if progresso:
                progresso(feito, total, Path(caminho).name)
            feito += 1
            alvo = tmp / f"clone_{feito}.avb"
            try:
                clone_generic(bin_moldes, nome, caminho, str(alvo), kind="video", fps=fps, mesma_geometria=True)
                novo = _conferir(alvo, Path(caminho).stem, caminho, ids_do_molde)
            except BaseException as e:  # noqa: BLE001 — o clone_one sai por SystemExit; um arquivo não derruba os outros
                if isinstance(e, KeyboardInterrupt):
                    raise
                falhas.append((caminho, " ".join(str(e).split())[:160] or type(e).__name__))
                log.warning("não clonei %s: %s", Path(caminho).name, e)
                continue
            if not novo:
                falhas.append((caminho, "o clone não conferiu (caminho ou master)"))
                continue
            mapa[caminho] = novo
            motores[caminho] = motor
            clones.append(alvo)
    if progresso:
        progresso(total, total, "")
    if clones:
        # Merge numa passada (como o áudio): só os mobs NOVOS de cada clone — o resto da cópia é a bin dos moldes.
        Path(saida).parent.mkdir(parents=True, exist_ok=True)
        with topen(str(clones[0])) as base:
            tem = {str(m.mob_id) for m in base.content.mobs}
            for outro in clones[1:]:
                with topen(str(outro)) as f:
                    for m in f.content.mobs:
                        if str(m.mob_id) not in tem and str(m.mob_id) not in ids_do_molde:
                            base.content.add_mob(materialize(base, serialize(m)))
                            tem.add(str(m.mob_id))
            base.content.uid = random.getrandbits(63)
            base.write(str(saida))
    shutil.rmtree(tmp, ignore_errors=True)
    log.info("vídeo injetado: %d clones, %d de volta ao LinkFile", len(mapa), len(falhas))
    return {"saida": saida if clones else None, "mapa": mapa, "falhas": falhas, "motores": motores,
            "ids_do_molde": ids_do_molde}
