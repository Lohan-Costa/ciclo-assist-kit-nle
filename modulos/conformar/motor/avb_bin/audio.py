r"""Masters AMA de ÁUDIO autorados por fora — sem `LinkFile`, sem diálogo.

## Por que isto existe

`LinkFile` de um WAV com start time abre o modal **`Audio Start-Time Options`** e
**congela a API inteira** do Media Composer. O `OK to All` não segura, porque a API linka
**um arquivo por chamada** (`LinkFileRequestBody.file_path` é `string`, não repetido) e
cada chamada é uma operação isolada — na prática, o editor clica uma vez por WAV. Isso
atinge **as duas rotas** de relink; é limite de plataforma, não de método.

⭐ **A divisão que resolve:** o áudio tem poucos formatos e o banco de NLEs já os mapeou —
medido num acervo real, **85/85 WAVs caem em 5 combinações** `(coding_format, bits,
canais)`, todas com template embarcado. O vídeo tem dezenas de codecs. Autora-se o lado
fechado e delega-se o aberto ao Media Composer.

⭐⭐ **E o ganho maior não é evitar a janela.** Ela existe porque o start time do BWF é um
número **sem base** — o Avid precisa saber em que taxa contá-lo. Respondida na mão, a
escolha **não deixa rastro nenhum**. Autorada, vira um valor explícito, gravado e
testável.

## As três correções que o `clone_generic` não fazia

Validadas por golden-diff contra um `LinkFile` oficial (MC 25.6/Windows, 2026-08-16), com
os 36 masters resultantes **ONLINE** na tela:

| peça | valor certo | o que o clone fazia |
|---|---|---|
| forma do caminho | `E//A/B/x.WAV` | `E:\\A\\B\\x.WAV` |
| volume | `V-001 (E:)` — rótulo **+** letra | `AVB-MEDIA` (do template) |
| `_AMD_SOURCE_LENGTH` | u64 LE = nº de samples | valor do template |

⭐⭐ **A decisiva é a forma do caminho.** O Avid grava caminho de Windows como
**letra + `//` + barras normais**. Com `E:\...` o clipe fica com o arquivo existindo, o
mtime batendo, o descriptor **idêntico ao do MC em todos os campos comparados** — e
**offline**. A causa é cross-platform: o clone nasceu e foi validado no macOS, onde o
caminho POSIX já vem com barra normal, e ninguém converteu ao portar.

⚠️ Todas as três são **size-neutral**, logo byte-surgery pura — que é o exigido: editar
mob AMA pelo *writer* do pyavb traz o clipe offline (regra do banco de NLEs).
"""

from __future__ import annotations

import logging
import math
import os
import struct
import tempfile
from pathlib import Path

from avb_export import clone_generic as CG
from avb_export import media_bin as MB
from avb_export.relink import replace_field

log = logging.getLogger("delapraca.avb_bin.audio")

# `<u16 18>_AMD_SOURCE_LENGTH<u32 8>` — o cabeçalho do atributo; os 8 bytes seguintes são
# o u64 que precisa valer o nº de samples do arquivo.
_MARCA_AMD = struct.pack("<H", 18) + b"_AMD_SOURCE_LENGTH" + struct.pack("<I", 8)

# O volume gravado nos templates embarcados. Trocado pelo volume REAL do destino.
VOLUME_TEMPLATE = b"AVB-MEDIA"

EXTENSOES = {".wav", ".aif", ".aiff"}


def forma_avid(caminho: str) -> str:
    r"""Caminho do Windows na forma que o Media Composer GRAVA: `E:\A\B` → `E//A/B`.

    Em caminhos que já são POSIX (macOS/Linux) devolve o mesmo caminho.

    ⚠️ Size-neutral: `E:\` e `E//` têm 3 caracteres e `\`→`/` é 1:1.
    """
    if len(caminho) > 2 and caminho[1] == ":" and caminho[2] in "\\/":
        return caminho[0] + "//" + caminho[3:].replace("\\", "/")
    return caminho.replace("\\", "/")


def rotulo_do_volume(caminho: str) -> str | None:
    r"""O volume como o Avid o grava: `RÓTULO (LETRA:)` — ex.: `V-001 (E:)`.

    ⚠️⚠️ **Rótulo E letra, na mesma string.** O banco de NLEs ensina que a coluna `Drive`
    de uma bin é o RÓTULO e não a letra — isso vale para **LER** (não monte `V-001:\`).
    O campo GRAVADO carrega os dois, e escrever só o rótulo deixa o clipe offline com o
    `Drive` mostrando um volume que o MC não resolve para disco nenhum.

    Fora do Windows não há letra e o conceito não se aplica: devolve `None`.
    """
    if os.name != "nt" or len(caminho) < 2 or caminho[1] != ":":
        return None
    import ctypes

    letra = caminho[0].upper()
    buf = ctypes.create_unicode_buffer(261)
    fs = ctypes.create_unicode_buffer(261)
    sn, ml, fl = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_ulong()
    ok = ctypes.windll.kernel32.GetVolumeInformationW(
        f"{letra}:\\", buf, 261, ctypes.byref(sn), ctypes.byref(ml),
        ctypes.byref(fl), fs, 261)
    if not ok or not buf.value:
        return None
    return f"{buf.value} ({letra}:)"


def _patch_amd_source_length(caminho_bin: Path, samples: int) -> int:
    """Grava `samples` em todo `_AMD_SOURCE_LENGTH` da bin. Size-neutral.

    ⚠️ Só é seguro numa bin de **um clipe** — por isso é chamado logo após o clone, antes
    de qualquer merge. Numa bin com vários, não há como saber qual valor é de qual.
    """
    d = bytearray(caminho_bin.read_bytes())
    n = i = 0
    while True:
        i = d.find(_MARCA_AMD, i)
        if i < 0:
            break
        struct.pack_into("<Q", d, i + len(_MARCA_AMD), samples)
        n += 1
        i += len(_MARCA_AMD) + 8
    if n:
        caminho_bin.write_bytes(bytes(d))
    return n


def _patch_caminho(caminho_bin: Path, original: str) -> int:
    """Reescreve o caminho do arquivo na forma do Avid. Size-neutral."""
    alvo = forma_avid(original)
    if alvo == original:
        return 0
    d = caminho_bin.read_bytes()
    agulha = original.encode("latin-1", "replace")
    n = d.count(agulha)
    if n:
        caminho_bin.write_bytes(d.replace(agulha, alvo.encode("latin-1", "replace")))
    return n


def _patch_volume(caminho_bin: Path, volume: str) -> int:
    """Troca o volume do template pelo do destino, nas DUAS variantes do campo.

    ⚠️ São dois campos por arquivo: o `MSMLocator` (prefixo `u16`) e uma variante utf8
    (`01 03 4C`) cujo campo inclui **dois bytes nulos** — `len=11` para 9 caracteres. Um
    `replace_field` que procure só a primeira troca **metade** e o clipe segue offline.
    """
    d = caminho_bin.read_bytes()
    novo = volume.encode("latin-1", "replace")
    d, n1 = replace_field(d, VOLUME_TEMPLATE, novo)
    d, n2 = replace_field(d, b"\x00\x00" + VOLUME_TEMPLATE, b"\x00\x00" + novo)
    caminho_bin.write_bytes(d)
    return n1 + n2


def e_audio(caminho: str) -> bool:
    return Path(caminho).suffix.lower() in EXTENSOES


# Até quantos frames de diferença se aceita preencher. 1–2 é o frame de guarda que o
# próprio Avid declara (medido); além disso o arquivo é OUTRO — take errado, versão
# diferente — e preencher com silêncio esconderia um erro de acervo.
TOLERANCIA_FRAMES = 2


def _como_o_avid(base, mapa: dict) -> int:
    """O nome, o `_USER` e a fonte de tape de cada master injetado como o MC grava ao LINKAR o mesmo BWF
    (`media/bwf.como_o_avid`; medido 2026-10-25, MC 25.12): `CENA/TAKE`, as colunas do gravador e o tape dele. Sem
    isto o master se chamava pelo arquivo e herdava a cena e os nomes de trilha do MOLDE. WAV sem cena e take também:
    o nome do arquivo, o TapeID, o Shoot Date e o Soundroll TC Rate — e nada do `_USER` do molde fica. Devolve quantos
    masters mudaram."""
    from media import bwf

    por = {str(m.mob_id): m for m in base.content.mobs}
    n = 0
    for caminho, mid in mapa.items():
        m = por.get(str(mid))
        try:
            meta = bwf.como_o_avid(caminho) if m is not None else None
        except Exception:  # noqa: BLE001 — metadado é acessório: o master continua como veio do molde
            log.debug("BWF ilegível %s", caminho, exc_info=True)
            meta = None
        if not meta:
            continue
        m.name = meta["nome"]
        attrs = m.property_data.get("attributes")
        if attrs is not None:
            user = base.create.Attributes()
            for k, v in meta["user"].items():
                user[k] = v
            attrs["_USER"] = user
        # sem cena, a fonte de baixo do MC leva o nome do arquivo; num molde de gravador (fonte de tape) ficaria o
        # "AVBTAP"/"TEMPLATE" do molde na coluna Tape
        tape = meta.get("tape") or (meta["nome"] if "Scene" not in meta["user"] else None)
        if tape:
            for fonte in _fontes_de(m, por):
                d = fonte.property_data.get("descriptor")
                if d is not None and "Tape" in type(d).__name__:
                    fonte.name = tape
        n += 1
    return n


def _variante(caminho: str) -> str:
    """'cena' ou 'semcena': a variante do molde de áudio para este arquivo (ver `autorar_masters`)."""
    from media import bwf

    try:
        meta = bwf.como_o_avid(caminho)
    except Exception:  # noqa: BLE001 — sem a leitura, o molde de sempre
        return ""
    return "cena" if meta and "Scene" in meta["user"] else "semcena"


def _fontes_de(m, por: dict, prof: int = 0) -> list:
    """As fontes (SourceMob) que a cadeia de `m` alcança, em profundidade."""
    fora = []
    if prof > 4:
        return fora
    for t in m.property_data.get("tracks") or []:
        c = t.property_data.get("component")
        for x in (c.property_data.get("components") or []) if type(c).__name__ == "Sequence" else [c]:
            alvo = por.get(str(getattr(x, "mob_id", ""))) if x is not None else None
            if alvo is not None and alvo is not m and alvo not in fora:
                fora.append(alvo)
                fora += [y for y in _fontes_de(alvo, por, prof + 1) if y not in fora]
    return fora


def autorar_masters(arquivos, saida: str, fps: float | None = None,
                    minimos: dict[str, int] | None = None, progresso=None, drop: bool = False) -> dict:
    """Autora uma bin com um master AMA de áudio por arquivo. Não fala com o MC.

    Args:
        arquivos: caminhos dos originais (`.wav`/`.aif`).
        saida: a `.avb` a escrever.
        fps: edit_rate da TIMELINE de destino. ⚠️ Passe sempre — sem ele a taxa vem do
            template (todos os embarcados têm 23,976) e um projeto a 25 sai errado calado.
            ⛔ E até 2026-10-31 passar NÃO bastava: só o start usava o `fps` (B001, ver
            `clone_generic._patch_taxa_da_cadeia`); hoje a cadeia inteira sai na taxa e é PROVADA
            contra a regra dos gabaritos do MC (`conferir_taxa_do_audio`).
        drop: o projeto é 29,97/59,94 DROP-FRAME — vai para o `Timecode` da fonte de mídia
            (`flags = 1`, medido); os quadros não mudam.
        minimos: `{arquivo → frames}` que a timeline PEDE de cada master (de
            `avb_bin.masters.uso_maximo`). O master é declarado com pelo menos isso.
            ⚠️ **Nenhum frame da edição muda**: start, duração e conteúdo de cada corte
            ficam idênticos; muda só a duração DECLARADA do master. Diferenças acima de
            `TOLERANCIA_FRAMES` **recusam** o arquivo em vez de preencher.
        progresso: `callable(feito, total, nome)`.

    Returns:
        `{"saida", "clipes", "pulados", "sem_template", "corrigidos", "mapa"}` —
        `mapa` é `{arquivo → str(mob_id) do master criado}`, capturado clone a clone.

    ⭐ Cada chamada gera **MobIDs novos** (o `clone_generic` randomiza). Isso não é
    detalhe: o Media Composer serve mob por MobID a partir da **sessão**, não do arquivo —
    duas bins com o mesmo MobID no mesmo boot e a primeira carregada ganha. Reautorar é o
    que garante que o editor veja o que acabamos de escrever.
    """
    from avb_export.merge import materialize, serialize
    from avb_export.reader import topen
    import random

    arquivos = [str(a) for a in arquivos if e_audio(str(a))]
    if not arquivos:
        return {"saida": saida, "clipes": 0, "pulados": [], "sem_template": [],
                "corrigidos": {}, "mapa": {}, "esticados": [], "curtos_demais": [], "variante_trocada": []}

    templates = MB.load_bundled_templates()
    tmp = Path(tempfile.mkdtemp(prefix="dlpc_audio_"))
    clones: list[Path] = []
    mapa: dict[str, str] = {}          # {arquivo → str(mob_id) do master}
    pulados: list[tuple[str, str]] = []
    sem_template: list[str] = []
    contagem = {"amd": 0, "caminho": 0, "volume": 0}
    minimos = minimos or {}
    esticados: list[tuple[str, int]] = []      # (nome, frames a mais)
    curtos_demais: list[tuple[str, int]] = []  # (nome, frames que faltam)
    variante_trocada: list[str] = []           # WAV autorado com molde de outra variante (cena × sem cena)
    total = len(arquivos)

    for i, caminho in enumerate(arquivos, 1):
        nome = Path(caminho).name
        if progresso:
            progresso(i - 1, total, nome)
        try:
            chave = MB._probe_key(caminho)
        except Exception as e:  # noqa: BLE001
            pulados.append((nome, f"ffprobe falhou: {e}"))
            continue
        # ⭐ O MC monta a cadeia conforme o WAV: com cena/take a fonte de baixo é de TAPE (nome = sTAPE); sem, é de
        # MÍDIA (nome = o arquivo). O molde carrega a do WAV de onde saiu — a variante certa primeiro, e o de sempre
        # se ela não existir (o `_como_o_avid` corrige o nome da fonte).
        variante = _variante(caminho)
        tpl = templates.get(chave + (variante,)) or templates.get(chave)
        if tpl is not None and variante and chave + (variante,) not in templates:
            # ⚠️ Sem molde da variante deste WAV, o de sempre entra — e a cadeia sai de OUTRA forma (medido
            # 2026-10-31: WAV de 4 canais sem cena → molde de TAPE, onde o MC faz fonte de MÍDIA). Dito, nunca calado.
            variante_trocada.append(f"{nome} {chave} sem molde '{variante}'")
            log.warning("%s: sem molde da variante %r para %s — usando o de sempre", nome, variante, chave)
        if tpl is None:
            # Formato sem template: NÃO se inventa um parecido — um descriptor de áudio
            # errado é mídia que toca deformada, o que é pior que mídia offline.
            sem_template.append(f"{nome} {chave}")
            continue

        template_bin, clip, kind = tpl
        alvo = tmp / f"clone_{i}.avb"

        # ⭐ Quanto a timeline pede × quanto o arquivo tem. A diferença separa o frame de
        # guarda do Avid (preenche) de mídia diferente (recusa) — ver TOLERANCIA_FRAMES.
        minimo = int(minimos.get(caminho) or 0)
        if minimo and fps:
            try:
                amostras, taxa = CG._audio_samples(caminho)
                real = math.ceil(amostras / taxa * float(fps))
                falta = minimo - real
                if falta > TOLERANCIA_FRAMES:
                    curtos_demais.append((nome, falta))
                    log.warning("%s é %d frames mais curto que a timeline pede — recusado",
                                nome, falta)
                    continue
                if falta > 0:
                    esticados.append((nome, falta))
            except Exception:  # noqa: BLE001 — sem a conta, segue sem mínimo
                minimo = 0

        try:
            CG.clone_generic(template_bin, clip, caminho, str(alvo), kind=kind, fps=fps, drop=drop,
                             master_len_min=minimo or None)
            samples, _sr = CG._audio_samples(caminho)
            contagem["amd"] += _patch_amd_source_length(alvo, samples)
            contagem["caminho"] += _patch_caminho(alvo, caminho)
            volume = rotulo_do_volume(caminho)
            if volume:
                contagem["volume"] += _patch_volume(alvo, volume)
        except Exception as e:  # noqa: BLE001
            # Um arquivo que falha não derruba os outros 35.
            pulados.append((nome, " ".join(str(e).split())[:160]))
            log.warning("falhou ao autorar %s: %s", nome, e)
            continue
        clones.append(alvo)
        # ⭐ Guarda o MobID do master recém-criado JÁ AQUI, com o clone de um clipe só.
        # Depois do merge não haveria como dizer qual master veio de qual arquivo sem
        # cair no casamento por nome — que é exatamente a armadilha do `remap.py`.
        try:
            with topen(str(alvo)) as f:
                for m in f.content.mobs:
                    if str(getattr(m, "mob_type", "")) == "MasterMob":
                        mapa[caminho] = str(m.mob_id)
                        break
        except Exception:  # noqa: BLE001
            log.debug("não consegui ler o MobID do clone de %s", nome, exc_info=True)

    if progresso:
        progresso(total, total, "")
    if not clones:
        return {"saida": saida, "clipes": 0, "pulados": pulados, "mapa": {},
                "sem_template": sem_template, "corrigidos": contagem,
                "esticados": esticados, "curtos_demais": curtos_demais, "variante_trocada": variante_trocada}

    # Merge numa passada só — reabrir e reescrever depois estoura no writer do pyavb.
    Path(saida).parent.mkdir(parents=True, exist_ok=True)
    with topen(str(clones[0])) as base:
        tem = {m.mob_id for m in base.content.mobs}
        for outro in clones[1:]:
            with topen(str(outro)) as f:
                for m in f.content.mobs:
                    if m.mob_id in tem:
                        continue
                    base.content.add_mob(materialize(base, serialize(m)))
                    tem.add(m.mob_id)
        for item in base.content.property_data["items"]:
            item.property_data["user_placed"] = (
                getattr(item.mob, "mob_type_id", None) == 2)
        contagem["como_o_avid"] = _como_o_avid(base, mapa)
        base.content.uid = random.getrandbits(63)
        base.write(str(saida))

    resultado = {"saida": saida, "clipes": len(clones), "pulados": pulados,
                 "sem_template": sem_template, "corrigidos": contagem, "mapa": mapa,
                 "esticados": esticados, "curtos_demais": curtos_demais, "variante_trocada": variante_trocada}
    log.info("áudio autorado: %s", resultado)
    return resultado
