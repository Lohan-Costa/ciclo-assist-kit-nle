"""O que existe nas BINS do projeto — a outra metade da pergunta "que material eu tenho".

A varredura do disco (`midia/acervo.py`) responde *o que está gravado*. Esta responde *o
que está no projeto*, e as duas não são a mesma lista. Medido no projeto real em
2026-09-11:

| | quantos | o que é |
|---|---|---|
| nos dois | **306** | o material que o editor usa |
| só no disco | **52** | outra produção, sobra de consolidate, mídia de outro projeto |
| só na bin | **1** | clipe sem arquivo nas pastas varridas |

⚠️ **"Sem arquivo" NÃO é "offline".** A mídia pode estar num volume que ninguém mandou
varrer — nesta máquina há uma segunda `Avid MediaFiles` em `S:`. Chamar de offline seria
afirmar o que não se mediu, e mandaria o editor procurar um problema que talvez não exista.

⭐ **E esta varredura é MUITO mais barata.** Medido: **5.524 mobs em 42 bins, 0,4 s** —
contra 58 s de `ffprobe` no acervo. Ler `.avb` é instantâneo e invisível; é a API do Media
Composer que custa (ver CLAUDE.md).

⭐ E o nome que sai daqui é **o que o editor vê e edita na bin**, que vale mais que o
`material_package_name` do arquivo para falar com ele.

## ⚠️ pyavb é PREGUIÇOSO, e isso morde fora do `with`

As propriedades são lidas do arquivo no momento em que se toca nelas. Guardar um mob para
ler depois do `with avb.open(...)` dá `ValueError: seek of closed file` — medido em
2026-09-11, e o traceback não menciona o `with`, então parece defeito da biblioteca. **Tudo
que interessa tem de virar dado nosso ainda dentro do bloco.**

## ⛔ O `Attic` fica de fora

O Avid guarda ali as versões antigas de cada bin, às centenas. Varrê-lo triplicaria o
trabalho para listar material que o editor já não vê — e faria a lista mostrar clipe que
ele apagou do projeto.
"""

from __future__ import annotations

import logging
import threading
import unicodedata
from pathlib import Path
from typing import Any, Callable

import avb

from ..midia import cache as _cache

log = logging.getLogger("cicloassist.avid.bins")

#: Pastas do projeto que não contêm bin de trabalho. Lista do banco
#: (`protocolos/mxf/README.md`, layout da `Avid MediaFiles`), mais duas.
#:
#: ⭐ **`Trash` é a lixeira do PROJETO, e ela conta como "não está no projeto".** MEDIDO em
#: 2026-09-11: sem excluí-la, 33 dos 36 clipes que a tela mostrava como "na bin, sem
#: arquivo" eram material que o editor já tinha jogado fora — e a lista aparecia como se
#: fosse mídia offline a recuperar.
IGNORAR = {"Attic", "Trash", "Render Files", "WaveformCache", "SearchData", "Statistics"}

#: `picture`/`sound` do pyavb → `video`/`audio` do ffprobe.
#:
#: ⚠️ Um vocabulário só, e ele é o do acervo: a tabela cruza as duas varreduras pela mesma
#: chave, e duas grafias de "é imagem" fariam a mesma mídia parecer de espécies diferentes
#: conforme quem a encontrou primeiro.
ESPECIE = {"picture": "video", "sound": "audio"}


def bins_do_projeto(pasta: Path | str) -> list[Path]:
    """As `.avb` de trabalho do projeto, em ordem."""
    raiz = Path(pasta)
    try:
        return sorted(
            b for b in raiz.rglob("*.avb")
            # ⚠️ `._X.avb`: a sombra do macOS num projeto em exFAT (medido: 47 numa pasta),
            #    que o pyavb recusa com "not a avb file".
            if not (IGNORAR & set(b.parts)) and not b.name.startswith("._")
        )
    except OSError as e:
        log.warning("não consegui listar as bins de %s (%s)", raiz, e)
        return []


def _masters_da_bin(caminho: Path) -> list[dict[str, Any]]:
    """Os masterclipes de UMA bin, já como dados nossos.

    ⚠️ Tudo lido dentro do `with`: ver o cabeçalho do módulo.
    """
    achados: list[dict[str, Any]] = []
    with avb.open(str(caminho)) as f:
        for mob in f.content.mobs:
            if getattr(mob, "mob_type", "") != "MasterMob":
                continue
            try:
                chave = _cache.de_umid(str(mob.mob_id))
            except _cache.ChaveInvalida:
                # MobID que não vira chave é mídia que o cache não sabe endereçar; ela
                # existe para o editor, mas não para nós.
                continue

            tracks: dict[str, int] = {}
            for track in mob.tracks:
                try:
                    especie = ESPECIE.get(track.component.media_kind)
                except Exception:            # noqa: BLE001 — track ilegível é 1 de N
                    continue
                if especie:
                    tracks[especie] = tracks.get(especie, 0) + 1

            achados.append({
                "chave": chave,
                "nome": str(getattr(mob, "name", "") or ""),
                "tracks": tracks,
                "trk": _colunas_trk(mob),
            })
    return achados


def _bins_de_nome(raiz: Path, bin_nome: str) -> list[Path]:
    """As `.avb` que o nome aponta: `C07`, `CENAS/C07`, ou a pasta `CENAS` com as de dentro (como as bins filhas no Premiere)."""
    forma = lambda s: unicodedata.normalize("NFC", s).casefold()  # noqa: E731 — o projeto pode vir em NFD no Mac
    alvo = forma(str(bin_nome).replace("\\", "/").strip("/"))
    alvo = alvo[:-4] if alvo.endswith(".avb") else alvo
    achadas = []
    for b in bins_do_projeto(raiz):
        relativo = forma(b.relative_to(raiz).with_suffix("").as_posix())
        if alvo and (relativo == alvo or forma(b.stem) == alvo or relativo.startswith(alvo + "/")):
            achadas.append(b)
    return achadas


def wavs_linkados(pasta_do_projeto: Path | str, bin_nome: str) -> dict[str, Any]:
    """`{bins, arquivos, gerenciados}`: os arquivos de som que os masters da bin linkam.

    ⭐ Mídia linkada guarda o caminho na bin, como o Premiere e o Resolve. Só a gerenciada não leva ao WAV do gravador, e por isso ela é contada à parte."""
    from . import take as _take   # ⚠️ aqui dentro: `take` importa este módulo

    raiz = Path(pasta_do_projeto)
    bins = _bins_de_nome(raiz, bin_nome)
    arquivos: list[str] = []
    gerenciados = 0
    for caminho in bins:
        try:
            with avb.open(str(caminho)) as f:
                mobs = list(f.content.mobs)
                por_id = {str(m.mob_id): m for m in mobs}
                for mob in mobs:
                    if getattr(mob, "mob_type", "") != "MasterMob" or not any(_take._tipo_da_track(t) == "sound" for t in mob.tracks):
                        continue
                    achados = _take.arquivos_ama(mob, "sound", por_id)
                    gerenciados += not achados
                    arquivos += [a for a in achados if a not in arquivos]
        except (OSError, ValueError, AssertionError) as e:
            log.warning("não consegui ler a bin %s (%s)", caminho, e)
    return {"bins": len(bins), "arquivos": arquivos, "gerenciados": gerenciados}


def _colunas_trk(mob) -> dict[str, str]:
    """As colunas `TRK1..n` do master (o nome de cada canal do som direto, que o Avid importa do iXML).

    ⛔ Moram DENTRO de `_USER`, não em `mob.attributes` direto (banco, `metadado-de-canal-do-som-direto.md` §1): quem
    olha só o primeiro nível conclui, errado, que a bin não tem metadado. ⭐ Plano de 2026-11-06 (transcrição por canal).
    """
    try:
        usuario = dict(dict(getattr(mob, "attributes", None) or {}).get("_USER") or {})
    except Exception:                         # noqa: BLE001 — atributo ilegível não derruba a bin
        return {}
    return {str(k).upper(): str(v or "") for k, v in usuario.items() if str(k).upper().startswith("TRK")}


def colunas_do_master(caminho_bin: Path | str, chave: str) -> dict[str, str]:
    """As colunas `TRK` do master `chave` lidas NESTA bin (instantâneo; a bin não precisa estar aberta)."""
    try:
        for m in _masters_da_bin(Path(caminho_bin)):
            if m["chave"] == chave:
                return m.get("trk") or {}
    except Exception as e:                    # noqa: BLE001
        log.info("não li as colunas TRK de %s em %s: %s", chave, caminho_bin, e)
    return {}


def colunas_da_foto(chave: str) -> dict[str, str]:
    """As colunas `TRK` do master pela última varredura guardada (`bins.json`). `{}` = não sei."""
    m = (ler().get("masters") or {}).get(chave) or {}
    return dict(m.get("trk") or {})


def bins_dos_mobs(pasta_do_projeto: Path | str, mob_ids) -> dict[str, list[str]]:
    """Em que bins, relativas ao projeto, cada MobID está À VISTA do editor.

    ⭐⭐ **O arrasto do Avid entrega o MobID e NÃO a bin** (banco,
    `plugins/avid-panel-sdk/arrastar.md` §3), e toda ferramenta de mídia pede a bin. Sem
    ela o modelo adivinhava — `PRODUCAO-A/Cena 7`, `ANTIGOS/C07_FALAS` —, errava e
    perguntava ao editor onde estava o que ele tinha acabado de arrastar (sessão de
    2026-09-15). A API não cruza as duas; o arquivo cruza, a 0,4 s o projeto inteiro.

    ⛔ **Só item VISÍVEL conta.** Uma bin de falas leva o fecho OCULTO (`user_placed=False`)
    com os mesmos subclipes: contado, todo take da C07 "estaria" em três bins, e a
    resposta viraria "diga qual" para um arrasto que não tem ambiguidade nenhuma.

    Devolve por MobID em 64 hex (`take.hex_do_mob`), só os que foram achados.
    """
    from .take import hex_do_mob   # take não importa bins; a volta criaria o ciclo

    alvos = {hex_do_mob(m) for m in mob_ids} - {""}
    raiz = Path(pasta_do_projeto)
    achados: dict[str, list[str]] = {}
    if not alvos:
        return achados
    for caminho in bins_do_projeto(raiz):
        try:
            with avb.open(str(caminho)) as f:
                aqui = {hex_do_mob(i.mob.mob_id) for i in f.content.items if i.user_placed}
        except Exception as e:                # noqa: BLE001 — uma bin ilegível é 1 de N
            log.warning("não consegui ler %s (%s: %s)", caminho.name, type(e).__name__, e)
            continue
        try:
            onde = str(caminho.relative_to(raiz))
        except ValueError:
            onde = caminho.name
        for h in alvos & aqui:
            achados.setdefault(h, []).append(onde)
    return achados


def varrer(
    pasta_do_projeto: Path | str,
    aviso: Callable[[float, str], None] | None = None,
    parar: threading.Event | None = None,
) -> dict[str, dict[str, Any]]:
    """Todos os masterclipes do projeto, por chave.

    Cada entrada traz o nome como está na bin, as tracks, e **em que bins ele aparece** —
    ⭐ que é o que responde "onde está isto?" sem abrir o Media Composer.
    """
    bins = bins_do_projeto(pasta_do_projeto)
    raiz = Path(pasta_do_projeto)
    por_chave: dict[str, dict[str, Any]] = {}

    for i, caminho in enumerate(bins):
        if parar is not None and parar.is_set():
            log.info("varredura de bins interrompida em %d de %d", i, len(bins))
            break
        if aviso is not None:
            aviso(i / max(1, len(bins)), caminho.name)

        try:
            masters = _masters_da_bin(caminho)
        except Exception as e:                # noqa: BLE001
            # ⚠️ Bin de outra versão, bin corrompida, bin aberta com lock: uma só não pode
            #   derrubar a varredura das outras 41.
            log.warning("não consegui ler %s (%s: %s)", caminho.name, type(e).__name__, e)
            continue

        try:
            onde = str(caminho.relative_to(raiz))
        except ValueError:
            onde = caminho.name

        for m in masters:
            ja = por_chave.get(m["chave"])
            if ja is None:
                por_chave[m["chave"]] = {**m, "bins": [onde]}
                continue
            # ⭐ O mesmo master costuma estar em várias bins — a bin da cena e a do dia.
            #   Listar todas é o que permite ao editor achar onde o clipe mora.
            if onde not in ja["bins"]:
                ja["bins"].append(onde)
            if not ja.get("nome") and m.get("nome"):
                ja["nome"] = m["nome"]
            if not ja.get("trk") and m.get("trk"):
                ja["trk"] = m["trk"]
            for especie, quantos in (m.get("tracks") or {}).items():
                ja["tracks"][especie] = max(ja["tracks"].get(especie, 0), quantos)

    if aviso is not None:
        aviso(1.0, f"{len(por_chave)} masterclipe(s)")
    return por_chave


# ── o resultado guardado ─────────────────────────────────────────────────────
#
# ⭐ Mora ao lado do cache, como o `acervo.json`, e pelo mesmo motivo: a aba abre sabendo
# o que a última varredura achou, sem refazer nada. Aqui refazer custa meio segundo — mas
# o painel não pode depender do Media Composer estar aberto para mostrar a lista.


def _arquivo(raiz: Path | None = None) -> Path:
    return (raiz or _cache.raiz()) / "bins.json"


def guardar(projeto: Path | str, por_chave: dict[str, dict[str, Any]],
            raiz: Path | None = None) -> None:
    import json
    import time

    try:
        _cache.escrever_atomico(_arquivo(raiz), json.dumps({
            "projeto": str(projeto),
            "quando": int(time.time()),
            "masters": por_chave,
        }, ensure_ascii=False).encode("utf-8"))
    except OSError as e:
        log.warning("não consegui guardar a varredura das bins (%s)", e)


def ler(raiz: Path | None = None) -> dict[str, Any]:
    """`{"projeto": ..., "quando": ..., "masters": {chave: {...}}}`.

    ⚠️ Leitura defensiva como todo o resto do cache: arquivo pela metade vira "não tenho",
    nunca exceção.
    """
    import json

    vazio: dict[str, Any] = {"projeto": "", "quando": 0, "masters": {}}
    alvo = _arquivo(raiz)
    try:
        if not alvo.is_file():
            return vazio
        lido = json.loads(alvo.read_text(encoding="utf-8"))
        if not isinstance(lido, dict) or not isinstance(lido.get("masters"), dict):
            return vazio
        return lido
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning("varredura de bins ilegível (%s); tratando como vazia", e)
        return vazio
