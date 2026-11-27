"""A timeline de uma `.avb` como LISTA DE SEGMENTOS — o que os writers de export consomem.

Irmão de `aaf/parser.py::parse_aaf`, e devolve **o mesmo formato** (os dataclasses
`Segment`/`MediaRef` são importados de lá, não copiados). `drp/writer.py::build_drt` e
`otio_export/writer.py::build_otio` não sabem — nem precisam saber — que a lista veio de
uma bin e não de um AAF.

⛔⛔ Existe porque a aba *Daqui Pra Lá* **nunca** pede `ExportFile` ao Media Composer
([ADR 0015](../../docs/adr/0015-export-le-a-bin-nunca-chama-exportfile.md)). Antes deste
módulo não havia leitor `.avb → segmentos` em nenhum app da família.

## O que foi medido para escrevê-lo (2026-09-24, bins reais, MC 25.6 / Windows)

Curta `PRODA_CORTE.02.Exported.01` (23.976, 877 SourceClips, 143 transições, 28
MotionEffects, 33 Selectors) e uma timeline de 2008 com 776 TrackEffects:

- toda trilha é `Sequence[Filler(0), …, Filler(resto)]`, e toda trilha INTERNA de efeito
  também (`Sequence[Filler(0), clipe, Filler(0)]`); efeitos se aninham (cor → adaptador
  espacial → velocidade → clipe);
- ⭐ `MotionEffect.speed_ratio` é racional **timeline ÷ fonte** (`[79, 68]` = 1,1617 num
  clipe a 85%) — a MESMA convenção que `build_drt` espera ("50% slowmo → ~2.0",
  `tools/inspect_drp.py::build_speed_timemap`). Sem conversão;
- o `param_list[1]` do `MotionEffect` é o mapa `(frame de timeline, offset de fonte)` que
  o próprio Avid integrou (`(79, 67.15)` = 79 × 0,85) — o `source_offset_map` do AAF;
- `[1000, 1001]` com curva zerada é CONFORMAÇÃO (24 → 23,976), não velocidade do editor;
  `[251, 1]` com fonte de 1 frame é CONGELAMENTO;
- ⚠️ os `Selector` do curta são `[Filler, clipe]` com `selected=0`: é o **clipe
  desabilitado** — o programa mostra o vazio. Seguir o ramo selecionado é o que o editor vê;
- várias trilhas de timecode (24 e 25 fps, ambas em 01:00:00:00): vale a que casa com a
  taxa da sequência.

## Fora do escopo desta versão (cada um vira aviso, nunca silêncio)

- multicam: `SourceClip` que aponta para `CompositionMob` de grupo;
- parâmetros de efeito geométrico: o NOME do efeito vai para `effects[]`, os valores
  (UUIDs do `param_list`) ainda não foram medidos e ficam `reproducible=False`;
- marcadores e drop-frame do timecode (`flags` só foi visto `0`).
"""

from __future__ import annotations

import logging
import os
import re
from pathlib import Path, PurePath

from aaf.masters import chave_mob
from aaf.parser import (MediaRef, Segment, _categorize_effect, _classify_motion,
                        _frames_to_tc_df, frames_to_tc)

from titulos.avid import e_titulo as _e_titulo
from titulos.avid import ler as _titulo

from .efeitos import enquadramento, informativo, nome_do_plugin, parametros_do_time_shift
from .percurso import e_composicao, e_master, e_subclipe, tipo, track_de

log = logging.getLogger("delapraca.avb_bin.segmentos")

PROFUNDIDADE_MAX = 16

#: Componentes que embrulham OUTRO componente em `tracks` e ocupam o próprio `length`
#: na timeline. O clipe está dentro; o efeito vai para `effects[]`.
_EMBRULHOS = ("TrackEffect", "PanVolumeEffect", "AudioSuitePluginEffect", "EqualizerMultiBand",
              "MotionEffect", "CaptureMask", "StrobeEffect", "Repeat", "TimeWarp",
              "EssenceGroup")


def deref(x):
    """`t.component` às vezes vem como `AVBObjectRef` — o objeto está em `.value`."""
    return getattr(x, "value", x) if type(x).__name__ == "AVBObjectRef" else x


def _lista(valor) -> list:
    if valor is None or callable(valor):
        return []
    try:
        return list(valor)
    except TypeError:
        return []


def _tracks(c) -> list:
    return [deref(getattr(t, "component", t)) for t in _lista(getattr(c, "tracks", None))]


def _racional(v) -> float | None:
    if isinstance(v, (list, tuple)) and len(v) == 2 and v[1]:
        return float(v[0]) / float(v[1])
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _pontos(param) -> list[tuple[float, float]]:
    """`[(offset, value)]` do `control_track` de um item do `param_list`."""
    param = deref(param)
    try:
        ct = deref(param.property_data.get("control_track"))
        pts = _lista(ct.property_data.get("control_points"))
    except AttributeError:
        return []
    fora = []
    for p in pts:
        p = deref(p)
        try:
            t = _racional(p.property_data.get("offset"))
            v = float(p.property_data.get("value"))
        except (AttributeError, TypeError, ValueError):
            continue
        if t is not None:
            fora.append((round(t, 3), round(v, 3)))
    return fora


# ── o arquivo físico de um master, lido da própria bin ─────────────────────────

#: O que o Avid grava num `WinFileLocator`: letra + `//` + barras normais
#: (`D//MIDIAS/x.mov`) — banco, `protocolos/avb/fontes.md`.
_LETRA_DO_AVID = re.compile(r"^([A-Za-z])//")
_LETRA = re.compile(r"^[A-Za-z]:[\\/]")


def caminho_do_locator(mob) -> str:
    """O caminho que o locator do mob carrega, na forma desta máquina — ou `""`.

    ⚠️ Lê o CONTEÚDO de `path_utf8`/`path_posix`/`path`, nunca a existência do locator:
    em mídia gerenciada o `WinFileLocator` existe com `path == ""`, e é o vazio que a
    separa do AMA (banco, `protocolos/avb/dados/entrelacamento-e-locators.json`).

    ⚠️ `nle_model.locator_path` só olha `path_posix` — o campo do `MacFileLocator` —, e
    por isso devolve `None` em TODA bin gravada no Windows (medido em 2026-09-24 em quatro
    bins reais). Este é o leitor das duas plataformas.
    """
    try:
        desc = getattr(mob, "descriptor", None)
    except ValueError as e:        # PCMA real: "unknown ext tag 0x02" (banco, avb/estruturas.md)
        log.debug("descritor ilegível em %r: %s", getattr(mob, "name", "?"), e)
        return ""
    if desc is None:
        return ""
    for cand in [desc] + _lista(getattr(desc, "descriptors", None)):
        locs = [getattr(cand, "locator", None)] + _lista(getattr(cand, "locators", None))
        for loc in locs:
            if loc is None:
                continue
            dados = getattr(loc, "property_data", None) or {}
            for campo in ("path_utf8", "path_posix", "path"):
                valor = dados.get(campo) if hasattr(dados, "get") else None
                valor = valor or getattr(loc, campo, None)
                if valor:
                    return _LETRA_DO_AVID.sub(r"\1:/", str(valor).strip())
    return ""


def caminho_confiavel(caminho: str) -> tuple[str | None, str]:
    """`(caminho que pode ser tocado no disco, motivo)` — ou `(None, motivo)`.

    ⛔⛔ O locator é texto de um arquivo que pode ter vindo de OUTRA produtora. No Windows
    um `.exists()` sobre um caminho UNC (`\\\\host\\share\\x.mov`) **abre sessão SMB com o
    host**, com a credencial da máquina do editor — a mesma classe de furo corrigida em
    `mcapi.arquivo_do_master` (banco, `transversal/matriz-de-plataforma.md` §C, linha
    "caminho UNC"). Por isso a recusa vem ANTES de qualquer toque no disco.
    """
    c = (caminho or "").strip()
    if not c:
        return None, "sem caminho na bin"
    barras = c.replace("\\", "/")
    if barras.startswith("//"):
        return None, "caminho de rede (UNC) — não verificado, por segurança"
    if any(p == ".." for p in barras.split("/")):
        # O Premiere grava caminhos com `..` resolvidos pela metade (medido 2026-10-03 no PRODUCAO_B:
        # `…/24Y07M23/../../../../../08_20240724/…/27A-1T05.WAV` — 55 clipes de áudio do filme, que
        # entravam OFFLINE). Absoluto com `..` não abre nada que o mesmo caminho sem `..` não abriria:
        # resolve-se pelo TEXTO (sem tocar no disco), pela forma (matriz, regra 3), e as checagens
        # valem sobre o resultado. Relativo, acima da raiz ou virando UNC: recusado.
        c = _resolver_pontos(c)
        if c is None:
            return None, "caminho com '..' relativo ou acima da raiz — recusado"
    if os.name != "nt" and _LETRA.match(c):
        # Não achado num volume daqui: segue como veio, como o gêmeo do Windows abaixo (`D:\x` no Mac nunca
        # vira rede) — até 2026-10-24 virava RECUSADO e a lista do R04 mostrava 69 recusados em vez dos 16 UNC.
        return _no_disco_desta_maquina(c)[0] or c, ""
    if os.name == "nt" and _VOLUME_MAC.match(c):
        # Não achado num disco daqui: segue como veio (é só nome — `/Volumes/x` no Windows nunca
        # vira rede), e o arquivo entra offline com o nome certo para o relink.
        return _no_volume_desta_maquina(c) or c, ""
    return c, ""


def _resolver_pontos(c: str) -> str | None:
    """`..` resolvido pelo TEXTO, numa pilha: `None` se o caminho é relativo ou sobe acima da raiz
    (o `normpath` engoliria isso calado). O separador fica o do original — a mesma mídia não pode
    aparecer com duas grafias, porque o casamento é por caminho (revisão de código 2026-10-03)."""
    if _LETRA.match(c):
        raiz, resto, sep = c[:3], c[3:], "\\" if "\\" in c else "/"
    elif c.startswith("/"):
        raiz, resto, sep = "/", c[1:], "/"
    else:
        return None
    pilha: list[str] = []
    for parte in re.split(r"[\\/]+", resto):
        if parte in ("", "."):
            continue
        if parte == "..":
            if not pilha:
                return None
            pilha.pop()
        else:
            pilha.append(parte)
    return raiz + sep.join(pilha)


_VOLUME_MAC = re.compile(r"^/Volumes/[^/]+/.")
_VOLUMES_CACHE: list = [0.0, {}, {}]        # [quando, {letra: rótulo}, {(rótulo, resto): achado}]


def _volumes_windows() -> dict[str, str]:
    """`{letra: rótulo}` dos discos LOCAIS e PRONTOS (cache de 10 s: um projeto traz milhares de caminhos).

    O mesmo cuidado de `plataforma.volumes_montados` (o motor não importa o serviço): sem
    `SEM_FAILCRITICALERRORS`, um leitor de cartão vazio abre um diálogo modal que ninguém vê. Só entram
    os discos que respondem a `GetVolumeInformationW` (o leitor vazio, não) e que não são de REDE: uma
    unidade mapeada e caída custa um timeout de reconexão por sonda (revisão de código 2026-10-03).
    """
    import ctypes
    import time

    if time.monotonic() - _VOLUMES_CACHE[0] < 10:
        return _VOLUMES_CACHE[1]
    k32 = ctypes.windll.kernel32
    anterior = k32.SetErrorMode(0x0001)
    try:
        montadas, buf, fora = k32.GetLogicalDrives(), ctypes.create_unicode_buffer(261), {}
        for i in range(26):
            if montadas & (1 << i):
                letra = chr(ord("A") + i)
                raiz = ctypes.c_wchar_p(f"{letra}:\\")
                if k32.GetDriveTypeW(raiz) not in (2, 3):        # REMOVABLE, FIXED
                    continue
                if k32.GetVolumeInformationW(raiz, buf, 261, None, None, None, None, 0):
                    fora[letra] = buf.value
    finally:
        k32.SetErrorMode(anterior)
    _VOLUMES_CACHE[:] = [time.monotonic(), fora, {}]
    return fora


def _no_volume_desta_maquina(caminho: str, volumes: dict[str, str] | None = None) -> str | None:
    """`/Volumes/PRODUCAO_B/x.mov` (projeto salvo no Mac) lido no Windows: o mesmo arquivo numa letra.

    Gêmeo de `_no_disco_desta_maquina` (matriz de plataforma, linha "caminho do OUTRO SO dentro de
    dado"). Medido 2026-10-03: o HD `PRODUCAO_B` do Mac monta no Windows como `F:` com o MESMO rótulo.
    Primeiro os discos com o rótulo do volume; se o rótulo não decide (renomeado, ou dois discos com
    ele), vale só se `<letra>:\\<resto>` existir em EXATAMENTE um disco — dois seriam palpite.
    """
    _, _vol, nome, *resto = caminho.split("/")
    if not resto:
        return None
    vols = _volumes_windows() if volumes is None else volumes
    sub = "\\".join(resto)
    memo = _VOLUMES_CACHE[2] if volumes is None else {}
    if (nome, sub) in memo:
        return memo[(nome, sub)]

    def achados(letras):
        return [f"{l}:\\{sub}" for l in letras if os.path.isfile(f"{l}:\\{sub}")]

    rotulo = [l for l, r in vols.items() if r and r.casefold() == nome.casefold()]
    pelo_rotulo = achados(rotulo)
    if len(pelo_rotulo) == 1:
        achado = pelo_rotulo[0]
    else:
        # o rótulo não decidiu: só os OUTROS discos (os do rótulo já foram sondados)
        todos = pelo_rotulo + achados(l for l in vols if l not in rotulo)
        achado = todos[0] if len(todos) == 1 else None
    memo[(nome, sub)] = achado
    return achado


def _no_disco_desta_maquina(caminho: str, volumes: Path = Path("/Volumes")) -> tuple[str | None, str]:
    """`D:/MIDIAS/x.mov` lido num Mac: o mesmo arquivo num volume montado.

    Porte de `Ciclo Assist/cicloassist/avid/take.py::_no_disco_desta_maquina` (medido em
    2026-09-14): a letra não diz qual volume é; só vale se `/Volumes/*/<resto>` existir em
    EXATAMENTE um volume. Dois candidatos seriam palpite, e palpite aqui é linkar o arquivo
    errado.
    """
    resto = re.sub(r"^[A-Za-z]:[\\/]", "", caminho).replace("\\", "/")
    try:
        candidatos = [v / resto for v in volumes.iterdir() if (v / resto).is_file()]
    except OSError:
        return None, "não consegui listar /Volumes"
    if len(candidatos) == 1:
        return str(candidatos[0]), ""
    return None, ("nenhum volume tem esse caminho" if not candidatos
                  else "mais de um volume tem esse caminho — ambíguo")


def arquivo_na_bin(master, por_id: dict) -> tuple[str, str]:
    """`(caminho bruto, descritor)` do arquivo que o master aponta, pela cadeia DENTRO da bin.

    Medido (banco, `protocolos/avb/fontes.md`): master → mob de arquivo (`MSMLocator`) →
    mob físico (`MediaDescriptor`, `WinFileLocator` com o caminho). Em mídia gerenciada o
    mob físico não tem caminho (ou nem existe na bin) e a resposta é `("", …)` — quem
    chama pergunta ao Media Composer.
    """
    vistos: set[str] = set()
    fila = [master]
    while fila:
        mob = fila.pop(0)
        chave = str(getattr(mob, "mob_id", ""))
        if chave in vistos or len(vistos) > 24:
            continue
        vistos.add(chave)
        caminho = caminho_do_locator(mob)
        if caminho:
            try:
                desc = type(getattr(mob, "descriptor", None)).__name__
            except ValueError:
                desc = "?"
            return caminho, desc
        for comp in _tracks(mob):
            for sc in _source_clips(comp):
                prox = por_id.get(str(sc.mob_id))
                if prox is not None:
                    fila.append(prox)
    return "", ""


def essencias_do_master(master) -> dict[str, str]:
    """`{"picture:1": urn, "sound:1": urn, "sound:2": urn…}` — a essência de cada trilha.

    ⭐ É a chave do arquivo EXATO de cada canal na mídia gerenciada: o índice do Avid
    (`msmFMID.pmr`) diz qual `.mxf` é de qual essência (`media/pmr.py`, `por_arquivo`).
    """
    fora: dict[str, str] = {}
    for tr in _lista(getattr(master, "tracks", None)):
        mk = str(getattr(tr, "media_kind", "") or "")
        if mk not in ("picture", "sound"):
            continue
        scs = _source_clips(getattr(tr, "component", None))
        if scs:
            fora[f"{mk}:{int(getattr(tr, 'index', 1) or 1)}"] = str(scs[0].mob_id)
    return fora


def _timecode_do_mob(mob) -> tuple[int, int, int] | None:
    """`(início do TC, fps do TC, posição do componente Timecode)` do mob, ou `None`."""
    for tr in _lista(getattr(mob, "tracks", None)):
        comp = deref(getattr(tr, "component", None))
        pos = 0
        for c in ([comp] if tipo(comp) == "Timecode" else _lista(getattr(comp, "components", None))):
            c = deref(c)
            if tipo(c) == "Timecode":
                return int(getattr(c, "start", 0) or 0), int(getattr(c, "fps", 0) or 0), pos
            pos += int(getattr(c, "length", 0) or 0)
    return None


def identidade_na_bin(master, por_id: dict) -> dict:
    """Quem é o ORIGINAL por trás de um master — o que o colorista usa para religar.

    ⭐ Vale também para mídia GERENCIADA, que é o caso normal de quem edita offline (medido
    em 2026-09-24): a cadeia master → mob de essência (`CDCI`/`MPGI`/`PCMA`) → mob FÍSICO
    (`TapeDescriptor` ou `MediaDescriptor`) mora inteira na bin, e o mob físico carrega:

      - o NOME do arquivo de câmera, sem extensão (`B001_03150131_C011`) — o **reel**;
      - uma trilha de timecode. O TC de origem do 1º frame do master é
        `início do TC + soma dos offsets da cadeia − posição do Timecode`:
        no curta, 0 + 132203 a 24 fps = 01:31:48:11, o TC de câmera.

    A imagem manda (a trilha de som chega ao mesmo mob físico, mas é o caminho de reserva).
    Devolve `{}` campo a campo quando não acha — nunca inventa.
    """
    fora: dict = {"reel": "", "tc_inicio": None, "tc_fps": None,
                  "largura": None, "altura": None, "fps": None,
                  "audio_sr": None,
                  "audio_canais": sum(1 for t in _lista(getattr(master, "tracks", None))
                                      if str(getattr(t, "media_kind", "")) == "sound")}
    # A taxa do áudio mora no descritor da essência de SOM (PCMA), um passo abaixo da trilha.
    for t in _lista(getattr(master, "tracks", None)):
        if str(getattr(t, "media_kind", "")) != "sound":
            continue
        for sc in _source_clips(getattr(t, "component", None))[:1]:
            essencia = por_id.get(str(sc.mob_id))
            try:
                sr = getattr(getattr(essencia, "descriptor", None), "sample_rate", None)
            except ValueError:
                sr = None
            if sr:
                fora["audio_sr"] = int(float(sr))
        break
    trilhas = sorted(_lista(getattr(master, "tracks", None)),
                     key=lambda t: 0 if str(getattr(t, "media_kind", "")) == "picture" else 1)
    for tr in trilhas:
        if str(getattr(tr, "media_kind", "")) not in ("picture", "sound"):
            continue
        # A cadeia inteira, do master ao mob mais fundo: `[(mob, offset acumulado)]`.
        cadeia: list = [(master, 0)]
        offset, vistos = 0, set()
        scs = _source_clips(getattr(tr, "component", None))
        while scs:
            sc = scs[0]
            prox = por_id.get(str(sc.mob_id))
            if prox is None or str(prox.mob_id) in vistos or len(vistos) > 8:
                break
            vistos.add(str(prox.mob_id))
            offset += int(getattr(sc, "start_time", 0) or 0)
            cadeia.append((prox, offset))
            try:
                desc = getattr(prox, "descriptor", None)
            except ValueError:
                desc = None
            if desc is not None and fora["largura"] is None and getattr(desc, "stored_width", None):
                fora["largura"] = int(desc.stored_width)
                altura = int(getattr(desc, "stored_height", 0) or 0) or None
                # ⚠️ Entrelaçado: a bin guarda a altura de UM CAMPO (1920×540 medido num
                # 1080i). `frame_layout` 0 = quadro inteiro; os demais são por campo.
                if altura and int(getattr(desc, "frame_layout", 0) or 0) != 0:
                    altura *= 2
                fora["altura"] = altura
                er = getattr(desc, "edit_rate", None)
                fora["fps"] = float(er) if er else None
            proximas = [sc2 for t in _tracks(prox)
                        for sc2 in _source_clips(t)]
            scs = proximas[:1]

        # ⚠️⚠️ O TC e o NOME podem morar em mobs DIFERENTES da cadeia (medido no som direto
        # do curta): a FITA no fundo tem o timecode certo (11:42:00:00, hora do gravador),
        # mas um nome gerado pelo import — `msmMMOB.02`, que se REPETE entre arquivos
        # diferentes —, enquanto o nome real do arquivo está na essência e no master.
        # Parar no primeiro mob com timecode (a 1ª versão disto) juntava 16 grupos de
        # masters distintos sob o mesmo "reel", cada um sobrescrevendo o TC do outro.
        for mob, desloc in reversed(cadeia):
            tc = _timecode_do_mob(mob)
            if tc is not None and tc[1] > 0:
                inicio, tfps, pos = tc
                fora["tc_inicio"], fora["tc_fps"] = inicio + desloc - pos, tfps
                break
        for mob, _desloc in reversed(cadeia):
            nome = (getattr(mob, "name", "") or "").strip()
            if nome and not _NOME_INTERNO.match(nome):
                fora["reel"] = nome
                break
        if fora["reel"] or fora["tc_inicio"] is not None:
            return fora
    return fora


#: Nomes que o Media Composer GERA para arquivos de mídia gerenciada (`msmMMOB.02`) — não
#: dizem nada do original e se repetem entre arquivos diferentes.
_NOME_INTERNO = re.compile(r"^msmMMOB\.\d+$", re.I)


def _source_clips(c, prof: int = 0) -> list:
    c = deref(c)
    if c is None or prof > PROFUNDIDADE_MAX:
        return []
    if tipo(c) == "SourceClip":
        return [c]
    fora = []
    for filho in _lista(getattr(c, "components", None)) + _tracks(c):
        fora.extend(_source_clips(filho, prof + 1))
    return fora


def _taxa_nativa(master, media_kind: str | None) -> float | None:
    alvo = str(media_kind or "").lower()
    melhor = None
    for tr in _lista(getattr(master, "tracks", None)):
        comp = deref(getattr(tr, "component", None))
        er = getattr(comp, "edit_rate", None)
        if not er:
            continue
        if str(getattr(comp, "media_kind", "") or "").lower() == alvo:
            return float(er)
        melhor = melhor or float(er)
    return melhor


def _comprimento(mob) -> int | None:
    for tr in _lista(getattr(mob, "tracks", None)):
        n = getattr(deref(getattr(tr, "component", None)), "length", None)
        if n:
            return int(n)
    return None


# ── o percurso ──────────────────────────────────────────────────────────────────

class _Leitor:
    def __init__(self, f, fps: float):
        self.por_id = {str(m.mob_id): m for m in f.content.mobs}
        self.fps = fps
        self.avisos: dict[str, int] = {}
        self.subclipe = None
        self.masters: dict[str, dict] = {}

    def avisar(self, texto: str) -> None:
        self.avisos[texto] = self.avisos.get(texto, 0) + 1

    # Resolve o SourceClip da timeline até o MASTER.
    def resolver(self, sc) -> tuple:
        """`(master | None, início na fonte, nome do clipe, trilha do master)`. O SUBCLIPE por onde passou fica em
        `self.subclipe` (mob_id, início dentro dele) — a Carta guarda essa camada (plano da Carta §4.6)."""
        inicio = int(getattr(sc, "start_time", 0) or 0)
        self.subclipe = None
        ref = self.por_id.get(str(sc.mob_id))
        if ref is None:
            self.avisar("clipe aponta para um mob que não está na bin")
            return None, inicio, "(mob ausente)", getattr(sc, "track_id", None)
        nome = getattr(ref, "name", None) or ""
        if e_master(ref):
            return ref, inicio, nome, getattr(sc, "track_id", None)
        if e_subclipe(ref):
            self.subclipe = (str(ref.mob_id), inicio)
            tr = track_de(ref, getattr(sc, "track_id", None), getattr(sc, "media_kind", None))
            seq = deref(getattr(tr, "component", None)) if tr is not None else None
            pos = 0
            for comp in _lista(getattr(seq, "components", None)) or ([seq] if seq is not None else []):
                comp = deref(comp)
                n = int(getattr(comp, "length", 0) or 0)
                if tipo(comp) != "Filler" and pos <= inicio < pos + max(n, 1):
                    # ⚠️ O som de um subclipe pode vir EMBRULHADO: medido no curta,
                    # `Sequence[Filler, PanVolumeEffect[SourceClip], Filler]` (ganho de clipe
                    # dentro do subclipe). Exigir SourceClip direto perdia 7 clipes da A1/A2
                    # que o Resolve 19 importa do AAF da mesma timeline.
                    dentro = comp if tipo(comp) == "SourceClip" else next(iter(_source_clips(comp)), None)
                    if tipo(comp) == "PanVolumeEffect":     # o ganho DENTRO do subclipe toca junto (a Carta soma)
                        self.subclipe = (*self.subclipe[:2], comp.property_data.get("level"))
                    destino = self.por_id.get(str(dentro.mob_id)) if dentro is not None else None
                    if destino is not None and e_master(destino):
                        fonte = int(getattr(dentro, "start_time", 0) or 0) + (inicio - pos)
                        return destino, fonte, nome, getattr(dentro, "track_id", None)
                pos += n
            self.avisar("subclipe sem clipe de master na posição pedida")
            return None, inicio, nome, getattr(sc, "track_id", None)
        if e_composicao(ref):
            self.avisar("multicam/grupo (fora do escopo desta versão) — clipe exportado sem mídia")
            return None, inicio, nome, getattr(sc, "track_id", None)
        return None, inicio, nome, getattr(sc, "track_id", None)

    def media_ref(self, master, media_kind) -> MediaRef:
        chave = str(master.mob_id)
        info = self.masters.get(chave)
        if info is None:
            bruto, desc = arquivo_na_bin(master, self.por_id)
            info = {
                "nome": getattr(master, "name", "") or "",
                "mob_id": chave,
                "caminho_na_bin": bruto,
                "descritor": desc,
                "fps": _taxa_nativa(master, media_kind),
                "duracao_frames": _comprimento(master),
                "identidade": identidade_na_bin(master, self.por_id),
                "essencias": essencias_do_master(master),
            }
            self.masters[chave] = info
        return MediaRef(
            mob_name=info["nome"], url="", local_path="",
            descriptor_type=info["descritor"] or "",
            source_duration_frames=info["duracao_frames"],
            source_fps=_taxa_nativa(master, media_kind) or info["fps"],
        )

    # Desce num embrulho de efeito até o clipe, colhendo efeitos e velocidade.
    def desembrulhar(self, c, efeitos: list, movimento: dict, prof: int = 0,
                     extra: dict | None = None):
        """`(SourceClip | None, posição dele dentro do embrulho)`. `extra` recolhe o que vira
        campo do segmento e não é efeito (o modo de reformat do FrameFlex)."""
        c = deref(c)
        if c is None or prof > PROFUNDIDADE_MAX:
            return None, 0
        k = tipo(c)
        if k == "SourceClip":
            return c, 0
        if k == "Sequence":
            pos = 0
            for comp in _lista(getattr(c, "components", None)):
                comp = deref(comp)
                achado, sub = self.desembrulhar(comp, efeitos, movimento, prof + 1, extra)
                if achado is not None:
                    return achado, pos + sub
                pos += int(getattr(comp, "length", 0) or 0)
            return None, 0
        if k == "Selector":
            return self.desembrulhar(self._ramo(c), efeitos, movimento, prof + 1, extra)
        if k in _EMBRULHOS or getattr(c, "tracks", None) is not None:
            if k == "MotionEffect" and not movimento:
                movimento.update(self._velocidade(c))
            elif k == "PanVolumeEffect":
                pd = c.property_data
                efeitos.append({"name": "Audio Pan Volume", "category": "gain",
                                "reproducible": False,
                                "params": {"level": pd.get("level"), "pan": pd.get("pan")}})
            elif k != "MotionEffect" and getattr(c, "effect_id", None) and _e_titulo(c):
                # ⭐ Título (Carta 1.2): texto e estilo vão no bloco `titulo`, no modelo neutro
                # de `motor/titulos/avid.py`. Antes ia só o effect_id, e o título da PRODA_CORTE
                # chegava ao Resolve como um buraco na V3.
                efeitos.append({"name": str(c.effect_id), "category": "title",
                                "reproducible": True, "params": {"titulo": _titulo(c)}})
            elif k != "MotionEffect" and getattr(c, "effect_id", None):
                eid = str(c.effect_id)
                ts = parametros_do_time_shift(c) if k == "AudioSuitePluginEffect" else None
                vel = ts["velocidade"] if ts else None
                if k == "AudioSuitePluginEffect" and nome_do_plugin(c) == "Reverse" and not movimento:
                    # ⭐ o AudioSuite REVERSE (2026-11-26, B33): o som de trás para a frente sobre o clipe de dentro — o
                    #   mesmo modelo do reverso da imagem (o mapa DESCE: o 1º quadro mostrado é o último do clipe)
                    n = int(getattr(c, "length", 0) or 0)
                    movimento.update({"speed_ratio": 1.0, "motion_effect_type": "constant",
                                      "source_offset_map": [(0.0, float(n - 1)), (float(n - 1), 0.0)],
                                      "speed_curve": [], "retime": None, "phase_offset": 0})
                if vel is not None and abs(vel - 1.0) > 1e-6 and not movimento:
                    # ⭐ o AudioSuite TIME SHIFT é a velocidade do SOM que o editor escolhe no MC (autor, 2026-11-26).
                    #   Antes ia só como efeito não reproduzível, e o som chegava ao Premiere a 100 % com o DOBRO da fonte,
                    #   sem marcador. A fonte começa no mesmo ponto e anda `vel` por quadro (o MC ouve só a 1ª parte do
                    #   clipe de dentro, que tem a duração do de fora): o mesmo modelo de uma velocidade constante.
                    comprimento = int(getattr(c, "length", 0) or 0)
                    movimento.update({"speed_ratio": vel, "motion_effect_type": "constant",          # = a imagem (0,5 a 50 %)
                                      "source_offset_map": [(0.0, 0.0), (float(comprimento), round(comprimento * vel, 3))],
                                      "speed_curve": [], "retime": None, "phase_offset": 0})
                # ⭐ Enquadramento (3D Warp, Resize, PIP, Pan&Scan, FrameFlex): os parâmetros
                # saem da bin com os nomes do AAF (`efeitos.py`) e vão ao writer do DRT.
                efeito, modo, avisos = enquadramento(c)
                if modo and extra is not None and extra.get("reframe_mode") in (None, "pillarbox"):
                    extra["reframe_mode"] = modo   # o que pede revisão tem prioridade
                for a in avisos:
                    self.avisar(a)
                if efeito is not None:
                    efeitos.append(efeito)
                elif not modo:
                    categoria, _ = _categorize_effect(eid)
                    info = informativo(c)
                    if ts:                 # o Time Shift: a velocidade e o tom (a carta os leva ao Premiere)
                        info = {**info, "time_shift": ts}
                    efeitos.append({"name": eid, "category": categoria,
                                    # o CC que se traduz inteiro vai aos 2 nós do Resolve (`drp/cor_mc.py`)
                                    "reproducible": "cor_mc" in info, "params": info,
                                    "label": nome_do_plugin(c)})
            for filho in _tracks(c):
                achado, sub = self.desembrulhar(filho, efeitos, movimento, prof + 1, extra)
                if achado is not None:
                    return achado, sub
        return None, 0

    def _ramo(self, sel):
        """O ramo que o `Selector` TOCA — nunca os outros (banco, `sincronizacao-e-subclipes.md`)."""
        ramos = _tracks(sel)
        i = int(sel.property_data.get("selected", 0) or 0)
        return ramos[i] if 0 <= i < len(ramos) else None

    def _velocidade(self, me) -> dict:
        pd = me.property_data
        sr = _racional(pd.get("speed_ratio")) or 1.0
        pl = _lista(pd.get("param_list"))
        attrs = dict(pd.get("attributes") or {})
        curva = _pontos(pl[0]) if pl else []
        offmap = _pontos(pl[1]) if len(pl) > 1 else []
        if attrs.get("_MFX_GRAPH_ENABLED") == 2 and curva:
            # ⛔ gráfico de POSIÇÃO (presets Speed Boost/Speed Bump/Trim To Fill; a rampa quadro a quadro escrita pelo
            # tradutor): o p0 JÁ é a posição da fonte por quadro e o p1 tem um ponto só — o mapa é o p0 (banco,
            # avb/estruturas.md §"Rampa (Timewarp)", 2026-10-12)
            offmap, curva = curva, []
            if len({round(b - a, 6) for (_, a), (_, b) in zip(offmap, offmap[1:])}) > 1:
                curva = [(0.0, 0.0), (1.0, 1.0)]                # marca de rampa: a velocidade muda
            try:
                interp = deref(deref(pl[0]).property_data.get("control_track")).property_data.get("interp_kind")
            except AttributeError:
                interp = None
            if interp not in (3, None) and len(offmap) > 2:
                # Linear (3) = exato; Spline (6) / Bezier (5) / Shelf (2) entre keyframes ESPARSOS ainda não foram
                # medidos — o mapa liga os keyframes em reta (pendente no banco)
                self.avisar("velocidade pelo gráfico de posição com curva (não linear) entre keyframes: "
                            "levada em reta entre eles — conferir")
        dentro = _source_clips(_tracks(me)[0]) if _tracks(me) else []
        fonte_len = int(getattr(dentro[0], "length", 0) or 0) if dentro else 0
        comprimento = int(getattr(me, "length", 0) or 0)

        if sr < 0:
            tipo_me = "reverse"
        elif fonte_len <= 1 or (offmap and len({v for _, v in offmap}) == 1 and comprimento > 1):
            tipo_me = "freeze"
        elif len({v for _, v in curva}) > 1:
            tipo_me = "ramp"
        else:
            tipo_me = "constant"
        if not offmap and comprimento:
            offmap = [(0.0, 0.0), (float(comprimento), round(comprimento / abs(sr), 3))]
        # a RAMPA foi conferida no Resolve (laboratório B22, 2026-10-12: 48/48); o CONGELADO e o REVERSO também, pela
        # imagem (Resolve 21.1, 2026-10-28: render casado quadro a quadro com a fonte — tests/test_congelado_drt.py)
        retime = "optical_flow" if attrs.get("_SFX_RENDER") in (6, 7) else None
        return {"speed_ratio": abs(sr), "motion_effect_type": tipo_me,
                "source_offset_map": offmap, "speed_curve": curva, "retime": retime,
                "phase_offset": int(pd.get("phase_offset", 0) or 0)}

    # Uma trilha.
    def sequencia(self, seq, trilha: int, e_audio: bool, fora: list) -> int:
        """Percorre a `Sequence` de uma trilha; devolve a posição final (para conferir)."""
        pos = 0
        for comp in _lista(getattr(seq, "components", None)):
            comp = deref(comp)
            k = tipo(comp)
            n = int(getattr(comp, "length", 0) or 0)

            if k == "Filler":
                if n > 0:
                    fora.append(self._vazio(pos, n, trilha, e_audio, "(gap)"))
                pos += n
                continue

            if k == "TransitionEffect":
                # Mesma semântica do AAF (`_parse_sequence`): a transição é a SOBREPOSIÇÃO
                # entre o clipe anterior e o seguinte, e recua o cursor.
                t_in = max(0, pos - n)
                s = Segment(timeline_tc_in=frames_to_tc(t_in, self.fps),
                            timeline_tc_out=frames_to_tc(pos, self.fps),
                            duration_frames=n, source_start_frames=0, source_fps=self.fps,
                            clip_name="(transition)", track=trilha, is_transition=True,
                            cutpoint=int(getattr(comp, "cutpoint", 0) or 0), is_audio=e_audio)
                s.effects = [{"name": str(getattr(comp, "effect_id", "") or ""),
                              "category": "transition", "reproducible": False, "params": {}}]
                fora.append(s)
                pos -= n
                continue

            if k in ("TrackRef", "Timecode", "Edgecode") or n == 0 and k != "SourceClip":
                pos += n
                continue

            desabilitado = False
            if k == "Selector":
                ramo = self._ramo(comp)
                if ramo is None or tipo(ramo) == "Filler":
                    # ⚠️⚠️ Ramo selecionado VAZIO = clipe DESABILITADO no Avid: o programa
                    # mostra o vazio, mas o clipe continua lá, no outro ramo. O Resolve 19,
                    # importando o AAF da mesma timeline, o traz como clipe DESLIGADO
                    # (`Flags=2`) — medido em 2026-09-24. Exportar vazio (a 1ª versão disto)
                    # jogava fora material que o editor só tinha desligado.
                    outro = next((r for r in _tracks(comp) if r is not None and tipo(r) != "Filler"),
                                 None)
                    if outro is None:
                        s = self._vazio(pos, n, trilha, e_audio, "(desabilitado)")
                        s.disabled = True
                        fora.append(s)
                        pos += n
                        continue
                    comp_efetivo, desabilitado = outro, True
                else:
                    comp_efetivo = ramo
            else:
                comp_efetivo = comp

            if k == "Sequence":
                # Sequence aninhada ocupa o próprio comprimento; os filhos se posicionam dentro.
                sub: list = []
                self.sequencia(comp, trilha, e_audio, sub)
                for s in sub:
                    s.timeline_tc_in = frames_to_tc(_tc(s.timeline_tc_in, self.fps) + pos, self.fps)
                    s.timeline_tc_out = frames_to_tc(_tc(s.timeline_tc_out, self.fps) + pos, self.fps)
                fora.extend(sub)
                pos += n
                continue

            efeitos: list = []
            movimento: dict = {}
            extra: dict = {}
            sc, dentro = self.desembrulhar(comp_efetivo, efeitos, movimento, extra=extra)
            if sc is None:
                s = self._vazio(pos, n, trilha, e_audio,
                                str(getattr(comp_efetivo, "effect_id", "") or k))
                s.is_gap = False
                s.is_effect = True
                s.effects = efeitos
                fora.append(s)
                pos += n
                continue

            master, fonte, nome, canal = self.resolver(sc)
            subclipe = self.subclipe
            if movimento:
                inicio, duracao = pos, n              # a velocidade ocupa o embrulho inteiro
            else:
                inicio = pos + dentro
                duracao = max(0, min(int(getattr(sc, "length", 0) or 0), n - dentro))
            s = Segment(timeline_tc_in=frames_to_tc(inicio, self.fps),
                        timeline_tc_out=frames_to_tc(inicio + duracao, self.fps),
                        duration_frames=duracao, source_start_frames=fonte,
                        source_fps=self.fps, clip_name=nome or "(sem nome)", track=trilha,
                        mob_id=str(master.mob_id) if master is not None else None,
                        source_slot_id=canal, is_audio=e_audio)
            s.effects = efeitos
            s.disabled = desabilitado
            s._subclipe = subclipe
            if extra.get("reframe_mode"):
                s.has_reframe = True
                s.reframe_mode = extra["reframe_mode"]
                # O writer do DRT escreve o modo como o Scaling por clipe do Resolve (Fit, Fill,
                # Crop, Stretch — `drp/writer.py::_ESCALA_DO_REFORMAT`, medido no caso E06).
            if master is not None:
                s.media_ref = self.media_ref(master, "sound" if e_audio else "picture")
            if movimento:
                s.has_motion_effect = True
                s.speed_ratio = movimento["speed_ratio"]
                s.motion_effect_type = movimento["motion_effect_type"]
                s.source_offset_map = movimento["source_offset_map"]
                s.speed_curve = movimento["speed_curve"]
                s.phase_offset = movimento["phase_offset"]
                s.retime = movimento.get("retime")
            s.motion_class, s.conform_ratio, s.relative_speed = _classify_motion(
                s.speed_ratio, s.motion_effect_type if movimento else None,
                s.media_ref.source_fps if s.media_ref else None, self.fps)
            fora.append(s)
            pos += n
        return pos

    def _vazio(self, pos: int, n: int, trilha: int, e_audio: bool, nome: str) -> Segment:
        return Segment(timeline_tc_in=frames_to_tc(pos, self.fps),
                       timeline_tc_out=frames_to_tc(pos + n, self.fps),
                       duration_frames=n, source_start_frames=0, source_fps=self.fps,
                       clip_name=nome, track=trilha, is_gap=True, is_audio=e_audio)


def _tc(tc: str, fps: float) -> int:
    h, m, s, f = (int(x) for x in tc.replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * round(fps) + f


def _inicio(seq, fps: float) -> tuple[int, bool]:
    """TC inicial da sequência: a trilha de timecode cuja taxa casa com a da sequência.

    ⚠️ Medido: o curta tem trilhas de 24 E de 25 fps (ambas 01:00:00:00). Pegar a primeira
    que aparecer poderia devolver o início na taxa errada. Drop-frame: `flags` só foi visto
    `0` — `pendente`, devolve sempre `False`.
    """
    nominal = round(fps) or 25
    alternativa = None
    for tr in sorted(_lista(getattr(seq, "tracks", None)), key=lambda t: getattr(t, "index", 0) or 0):
        comp = deref(getattr(tr, "component", None))
        if tipo(comp) != "Timecode":
            continue
        tfps = int(getattr(comp, "fps", 0) or 0)
        inicio = int(getattr(comp, "start", 0) or 0)
        if tfps == nominal:
            return inicio, False
        if tfps > 0 and alternativa is None:
            alternativa = (round(inicio * nominal / tfps), False)
    return alternativa or (0, False)


def sequencias(f) -> list:
    """As timelines de uma bin: `CompositionMob` com `usage_code == 0`."""
    return [m for m in f.content.mobs
            if e_composicao(m) and int(getattr(m, "usage_code", 0) or 0) == 0]


def escolher_sequencia(f, mob_id: str | None = None, nome: str | None = None):
    """A sequência pedida: por MobID (o do arrasto), senão por nome, senão a única."""
    candidatas = sequencias(f)
    if mob_id:
        alvo = chave_mob(mob_id)
        for m in candidatas:
            if chave_mob(str(m.mob_id)) == alvo:
                return m
    if nome:
        for m in candidatas:
            if (getattr(m, "name", "") or "") == nome:
                return m
    if mob_id or nome:
        return None
    return candidatas[0] if len(candidatas) == 1 else None


def ler_timeline(f, alvo) -> dict:
    """A sequência `alvo` (uma `CompositionMob` de `f`) no formato de `parse_aaf`.

    ⚠️ Tudo sai daqui como DADO nosso: o pyavb é preguiçoso e um mob tocado fora do `with`
    que abriu a bin levanta "seek of closed file" (banco, `protocolos/avb/README.md`).

    Além das chaves de `parse_aaf`, devolve:
      - `masters`: `{mob_id: {nome, caminho_na_bin, descritor, fps, duracao_frames}}` —
        quem chama decide o arquivo (bin, Media Composer, nada);
      - `avisos`: `[{texto, vezes}]` — tudo que ficou de fora ou não foi conferido;
      - `conferencia`: trilhas cujo percurso não fechou no comprimento da sequência.
    """
    fps = float(getattr(alvo, "edit_rate", 0) or 0) or 25.0
    leitor = _Leitor(f, fps)
    segmentos: list[Segment] = []
    comprimento = int(getattr(alvo, "length", 0) or 0)
    nao_fecharam = []

    trilhas = sorted(_lista(getattr(alvo, "tracks", None)),
                     key=lambda t: (str(getattr(t, "media_kind", "")), getattr(t, "index", 0) or 0))
    for tr in trilhas:
        kind = str(getattr(tr, "media_kind", "") or "").lower()
        if kind not in ("picture", "sound"):
            continue
        idx = int(getattr(tr, "index", 1) or 1)
        numero = idx if kind == "picture" else 1000 + idx - 1
        seq = deref(getattr(tr, "component", None))
        fim = leitor.sequencia(seq, numero, kind == "sound", segmentos)
        # ⭐ Conferência gratuita: toda trilha do Avid cobre a sequência inteira (Filler de
        # preenchimento no fim, banco `avb/escrita.md`). Se o percurso não fechar no
        # comprimento, a semântica de algum componente foi lida errado — e os tempos de
        # tudo que vem depois dele também.
        if comprimento and fim != comprimento:
            nao_fecharam.append({"trilha": ("V%d" if kind == "picture" else "A%d") % idx,
                                 "fim": fim, "esperado": comprimento})

    inicio, drop = _inicio(alvo, fps)
    for s in nao_fecharam:
        leitor.avisar("trilha %s não fechou no comprimento da sequência (%d de %d)"
                      % (s["trilha"], s["fim"], s["esperado"]))

    log.info("timeline %r: %d segmentos, %d masters, %d avisos",
             getattr(alvo, "name", ""), len(segmentos), len(leitor.masters), len(leitor.avisos))
    dicts = []
    for s in segmentos:
        d = s.to_dict()
        # O canal que o clipe de som LÊ do master (a trilha que o SourceClip pede). O writer
        # do DRT prefere isto ao palpite pela ordem das tracks.
        if s.is_audio and s.mob_id and s.source_slot_id:
            d["canal_arquivo"] = int(s.source_slot_id)
        sub = getattr(s, "_subclipe", None)
        if sub:                                    # o clipe veio de um SUBCLIPE: qual, e onde dentro dele
            d["subclipe_mob_id"], d["subclipe_inicio_frames"] = sub[0], int(sub[1])
            if len(sub) > 2 and sub[2] is not None:
                d["subclipe_ganho_level"] = sub[2]
        dicts.append(d)
    return {
        "segments": dicts,
        "timeline_fps": fps,
        "total_segments": len(segmentos),
        "has_nested_scope": False,
        "composition_name": getattr(alvo, "name", "") or "",
        "sequence_mob_id": str(alvo.mob_id),
        "timeline_start_frames": inicio,
        "timeline_drop_frame": drop,
        "timeline_start_tc": _frames_to_tc_df(inicio, fps, drop),
        "markers": [],
        "masters": leitor.masters,
        "avisos": [{"texto": t, "vezes": n} for t, n in leitor.avisos.items()],
        "conferencia": nao_fecharam,
        "fonte": "avb",
    }


def ler_timeline_de_arquivo(caminho_avb: str, mob_id: str | None = None,
                            nome: str | None = None) -> dict:
    """`ler_timeline` a partir do caminho da `.avb`, escolhendo a sequência."""
    from avb_export.reader import topen

    with topen(caminho_avb) as f:
        alvo = escolher_sequencia(f, mob_id, nome)
        if alvo is None:
            raise LookupError("a sequência não está nesta bin (salve a bin no Media Composer "
                              "e tente de novo)")
        return ler_timeline(f, alvo)


#: ⭐ A pasta do RÓTULO offline (autor, 2026-11-24): o caminho de um original que não está nesta máquina é só nome — ele
#: nunca existiu ali. Dentro da pasta de passagem (`recebidos/`, apagada por semana) ele parecia "mídia apagada do
#: cache" (48 trechos dos DLPC PRODA 21 MAC, 23/11); com o nome explícito, quem abre o projeto lê o que é.
PASTA_OFFLINE = "OFFLINE - religar"

#: As extensões que já dizem que o nome é de um arquivo de SOM (o resto — `PSEF.135`, nome sem extensão — não é extensão).
EXT_SOM = {".wav", ".wave", ".bwf", ".aif", ".aiff", ".aifc", ".mp3", ".m4a", ".aac", ".flac", ".ogg"}


def so_de_som(info: dict) -> bool:
    """O master só tem trilhas de som (um efeito, uma música, o som direto importado) — pelas essências que a bin diz."""
    ess = info.get("essencias") or {}
    return bool(ess) and all(str(k).startswith("sound") for k in ess)


_TRACK_E_HASH = re.compile(r"(?i)[AV]\d{2}\.[0-9A-F]{6,}[0-9A-F_]*[A-Z]?\.mxf$")


def essencia_gerenciada(caminho: str) -> bool:
    """O arquivo é ESSÊNCIA do Avid (OP-Atom em `Avid MediaFiles/MXF/<n>/`, ou o nome com track + hash), não um
    original de câmera ou de som — um original MXF (XAVC, câmera Sony) mora fora do `Avid MediaFiles`."""
    c = (caminho or "").replace("\\", "/")
    return "/avid mediafiles/" in c.lower() or bool(_TRACK_E_HASH.search(PurePath(c).name))


def referencia_offline(info: dict, pasta: str, source_path: str = "",
                       source_file: str = "", fps_projeto: float | None = None) -> tuple[str, dict]:
    """O ORIGINAL de um master sem arquivo neste disco: `(caminho de referência, metadados)`.

    ⭐ É o caso NORMAL do export, não a exceção: quem edita offline tem só a mídia
    gerenciada, e a timeline vai para um colorista que tem os originais. O clipe precisa
    chegar ao Resolve dizendo QUEM é — nome do arquivo de câmera, TC de origem, duração —
    para ser religado lá. Sem isto ele sumia do DRT.

    - nome: o `Source File` do Media Composer (tem a EXTENSÃO) quando ele sabe; senão o NOME
      do arquivo que o master AMA guarda na bin (`caminho_na_bin`, também com a extensão); só
      então o reel (o nome de câmera, SEM extensão);
    - pasta: o `Source Path` do Media Composer quando ele sabe; senão `<pasta>/OFFLINE - religar`
      (`PASTA_OFFLINE`). É só referência — o Resolve mostra offline até o colorista religar.

    ⚠️ Medido em 2026-09-27 (caso E06, bin feita no Mac): sem o `Source File` — a bin aberta
    fora do Media Composer ("Abrir arquivo…") não tem as colunas dele —, o clipe ia como
    "RELINKER_TESTCHART_3840x2160", sem `.mov`, e o Resolve não o reconectava sozinho quando o
    autor importava os mesmos arquivos. Do `caminho_na_bin` vem SÓ o nome: a pasta é de outra
    máquina (`/Volumes/…`) e um caminho de fora escrito no DRT é o ataque V2.
    """
    from nomes.export import nome_de_arquivo

    ident = info.get("identidade") or {}
    arquivo = PurePath((source_file or "").replace("\\", "/")).name
    if not arquivo:
        na_bin = (info.get("caminho_na_bin") or "").replace("\\", "/")
        arquivo = PurePath(na_bin).name
        if "." not in arquivo or essencia_gerenciada(na_bin):
            # sem extensão, não ganha do reel; e o MXF GERENCIADO não é o original — o nome dele é o do clipe inteiro,
            # truncado com hash ou só hash (banco `protocolos/mxf/README.md`, armadilha 4): o room tone do PRODUCAO-A
            # (U03, pelo AAF) chegava ao Resolve como `129442__jmA01.6ABBB663AA0CA.mxf.wav` (2026-11-25)
            arquivo = ""
    nome = nome_de_arquivo(arquivo or ident.get("reel") or info.get("nome") or "") or "offline"
    som = so_de_som(info)
    if som and os.path.splitext(nome)[1].lower() not in EXT_SOM:
        # ⭐ O `RelinkClips` do Resolve procura o nome EXATO, com a extensão (Resolve 21.1, 2026-11-24: 0 de 16 religados
        # sem ela, 11 de 16 com ela — banco `plugins/resolve-scripting/api-scripting.md`). Do reel (sem extensão) não se
        # sabe a do original; `.wav` é o caso comum de som importado, e quem tinha `.aif`/`.mp3` fica como estava.
        nome += ".wav"
    caminho = os.path.join((source_path or "").strip() or os.path.join(pasta, PASTA_OFFLINE), nome)

    fps = float(ident.get("fps") or info.get("fps") or 0) or None
    tc_fps = int(ident.get("tc_fps") or (round(fps) if fps else 0))
    inicio = ident.get("tc_inicio")
    # ⭐ O TC de um master SÓ DE SOM conta na taxa do PROJETO: o master diz 24, o projeto é 23,976, e `início / 24` punha
    # o `PATÃO DRONE` (06:14:11:13 no MC) em 06:13:49:02 no Resolve (PRODUCAO-A, 2026-11-24). Imagem: a taxa dela.
    fps_tc = fps_projeto if (som and fps_projeto and tc_fps and round(fps_projeto) == tc_fps) else fps
    return caminho, {
        "nb": info.get("duracao_frames"),
        "fps": fps,
        "fps_tc": fps_tc,
        "tc": frames_to_tc(int(inicio), tc_fps) if inicio is not None and tc_fps else None,
        "tc_segundos": (int(inicio) / fps_tc) if inicio is not None and fps_tc else 0.0,
        "audio_sr": ident.get("audio_sr"),
        "audio_canais": ident.get("audio_canais"),
        "reel": ident.get("reel") or "",
    }


def montar_midia(resultado: dict, arquivos: dict[str, str], pasta: str,
                 colunas_por_mob: dict[str, dict] | None = None,
                 gerenciados: dict[str, str] | None = None,
                 preferir: dict[str, str] | None = None) -> tuple[list, list, dict]:
    """`(segmentos para o writer, match_results, metadados offline)` — o arquivo de CADA
    clipe, na ordem que o banco manda (`protocolos/msm/pmr-fmid.md` §9, regra do autor:
    *"a mídia que vale é a gerenciada"*):

    1. **gerenciada** (`gerenciados` = `{urn da essência: .mxf}`, do `.pmr`): o arquivo EXATO
       da trilha — imagem num `.mxf`, cada canal de som no seu `_A0n.mxf` MONO (lido no canal
       1). É como o Resolve liga ao importar o AAF, e é o que deixa o clipe ONLINE aqui;
    2. **AMA** (`arquivos` = `{master: arquivo}`, da bin ou do Media Composer);
    3. **referência ao original** (offline) — para quem recebe e tem os originais.

    ⭐ `preferir` (`{master: arquivo}`) passa na frente de TUDO: são os ORIGINAIS que quem
    recebe (a cor) escolheu relinkar ao importar (ADR 0020). A cor quer a alta, não o DNx
    gerenciado. O som de um original é o arquivo polifônico da câmera ou do gravador, e
    lê o canal que o Avid usava (`canal_arquivo` intacto). Sem `preferir`, a ordem é a de
    sempre — `test_carta_ida_e_volta` exige DRT(bin) ≡ DRT(Carta).
    """
    import copy

    gerenciados = gerenciados or {}
    preferir = preferir or {}
    masters = resultado.get("masters") or {}
    segmentos = copy.deepcopy(resultado.get("segments") or [])

    por_segmento: dict[int, str] = {}
    na_gerenciada: set[int] = set()
    precisa_ref: set[str] = set()
    for i, s in enumerate(segmentos):
        chave = s.get("mob_id")
        if not chave or s.get("is_gap") or s.get("is_transition"):
            continue
        tipo_m = "sound" if s.get("is_audio") else "picture"
        canal = int(s.get("canal_arquivo") or s.get("source_slot_id") or 1)
        essencia = ((masters.get(chave) or {}).get("essencias") or {}).get(f"{tipo_m}:{canal}")
        mxf = gerenciados.get(essencia) if essencia else None
        if chave in preferir:
            por_segmento[i] = preferir[chave]
        elif mxf:
            por_segmento[i] = mxf
            na_gerenciada.add(i)
            if s.get("is_audio"):
                s["canal_arquivo"] = 1       # o `.mxf` de um canal é MONO
        elif chave in arquivos:
            por_segmento[i] = arquivos[chave]
        else:
            precisa_ref.add(chave)

    # ⭐ NENHUM SEGMENTO SE PERDE (autor, 2026-10-06): o clipe cujo master a leitura não trouxe também
    # entra offline — um master mínimo pelo próprio segmento (nome do clipe, taxa, a ponta pedida), em
    # vez do `continue` mais abaixo, que o tirava da timeline.
    sem_master = {k for k in precisa_ref if k not in masters}
    masters_ref = {k: m for k, m in masters.items() if k in precisa_ref}
    for s in segmentos:
        k = s.get("mob_id")
        if k in sem_master:
            ponta = int(s.get("source_start_frames") or 0) + int(s.get("duration_frames") or 0) + 1
            m = masters_ref.setdefault(k, {"nome": s.get("clip_name") or str(k), "caminho_na_bin": "",
                                           "descritor": "", "fps": float(s.get("source_fps") or 0) or 25.0,
                                           "duracao_frames": 0, "essencias": {}})
            m["duracao_frames"] = max(m["duracao_frames"], ponta)
    metadados, offline_por_mob, deslocamento = _referencias_offline(
        masters_ref, pasta, colunas_por_mob or {}, float(resultado.get("timeline_fps") or 0) or None)

    casados = []
    for i, s in enumerate(segmentos):
        chave = s.get("mob_id")
        if not chave or s.get("is_gap") or s.get("is_transition"):
            continue
        if i in por_segmento:
            caminho, e_offline = por_segmento[i], False
            if chave in preferir and i not in na_gerenciada:
                _deslocar_trecho(s, caminho, float(resultado.get("timeline_fps") or 0) or None, arquivos.get(chave))
        elif chave in offline_por_mob:
            caminho, e_offline = offline_por_mob[chave], True
            d = deslocamento.get(chave)
            if d:
                s["source_start_frames"] = int(s.get("source_start_frames") or 0) + d
        else:
            continue
        if s.get("media_ref") is not None:
            s["media_ref"]["local_path"] = caminho
        casados.append({"segment_index": i, "matched_path": caminho, "rejected": False,
                        "source_offset_correction": 0, "offline": e_offline,
                        "gerenciada": i in na_gerenciada})
    return segmentos, casados, metadados


def _deslocar_trecho(s: dict, original: str, fps_tl: float | None, do_master: str | None = None) -> None:
    """O arquivo do master (o daily) é um TRECHO do `original` que o substitui — o render da cor voltando, a mídia
    consolidada (BL09 pelo MC, 2026-11-23)? O `source_start_frames` conta desde o início do DAILY; no original, esse
    início está `desloc_s` adiante. Sem isto o plano saía do começo do original — e a conferência do Baselight o
    aprovava, porque o xmeml esperado tinha o mesmo erro (medido: C001C003 4–43 em vez de 64–103). O DRT do Resolve
    lê o mesmo `In` desde o início do arquivo. A regra é a do casador do Premiere (`prproj.originais._trecho`).
    `do_master`: o arquivo do master nesta máquina (o AMA da Carta/AAF: o segmento da Carta não traz `local_path`)."""
    from media.matcher import _daily_do_segmento
    from prproj.originais import _trecho, sondar

    daily = _daily_do_segmento(s) or (do_master if do_master and os.path.isfile(do_master) else None)
    if not daily or os.path.normcase(daily) == os.path.normcase(original or ""):
        return
    try:
        d, o = sondar(daily), sondar(original)
    except OSError:
        return
    t = _trecho(d, o) if d.get("ok") and o.get("ok") else None
    if not t:
        return
    fps = float((s.get("media_ref") or {}).get("source_fps") or s.get("source_fps") or 0) or fps_tl or d["fps"]
    s["source_start_frames"] = int(s.get("source_start_frames") or 0) + int(t["desloc_s"] * fps + 0.5)
    s["trecho"] = t


def montar_offline(resultado: dict, arquivos: dict[str, str], pasta: str,
                   colunas_por_mob: dict[str, dict] | None = None) -> tuple[list, list, dict]:
    """`montar_midia` sem mídia gerenciada: AMA onde houver, referência offline no resto."""
    return montar_midia(resultado, arquivos, pasta, colunas_por_mob)


def _referencias_offline(masters: dict, pasta: str, colunas_por_mob: dict,
                         fps_projeto: float | None = None) -> tuple:
    """`(metadados, {master: caminho}, {master: deslocamento do In})` para os sem arquivo.

    ⚠️⚠️ **Um original, um clipe no pool — e o In medido a partir DELE.** Masters diferentes
    podem ser o mesmo arquivo de origem (trechos do mesmo take, fitas que se chamam todas
    "1"): medido no curta, 16 grupos. O pool do Resolve tem UM clipe por arquivo, com UM TC
    de início; se cada master levasse o próprio, um sobrescreveria o outro e o In de todos os
    demais apontaria o frame errado depois de religar. Então, por original:

        início = o MENOR TC de início entre os masters; fim = a maior ponta;
        In de cada clipe += (TC de início do master − início do original)

    e `TC de início + In` = o TC de câmera exato do ponto de entrada, que é o que o colorista
    usa para religar.
    """
    grupos: dict[tuple, dict] = {}
    for chave, m in masters.items():
        col = colunas_por_mob.get(chave) or {}
        ref, meta = referencia_offline(m, pasta, col.get("Source Path", ""),
                                       col.get("Source File", ""), fps_projeto)
        ident = m.get("identidade") or {}
        # Mesmo nome com taxa diferente não é o mesmo arquivo: vira outro caminho.
        chave_grupo = (ref, meta["fps"], ident.get("tc_fps"))
        g = grupos.setdefault(chave_grupo, {"meta": meta, "membros": {}})
        g["membros"][chave] = (ident.get("tc_inicio"), int(m.get("duracao_frames") or 0))

    offline_por_mob: dict[str, str] = {}
    metadados: dict[str, dict] = {}
    deslocamento: dict[str, int] = {}
    usados: dict[str, int] = {}
    for (ref, fps, tc_fps), g in grupos.items():
        n = usados.get(ref, 0)
        usados[ref] = n + 1
        caminho = ref if not n else f"{os.path.splitext(ref)[0]} ({n + 1}){os.path.splitext(ref)[1]}"
        meta = dict(g["meta"])
        com_tc = [(tc, nb) for tc, nb in g["membros"].values() if tc is not None]
        if com_tc and tc_fps:
            inicio = min(tc for tc, _ in com_tc)
            fim = max(tc + nb for tc, nb in com_tc)
            meta["nb"] = fim - inicio
            meta["tc"] = frames_to_tc(inicio, tc_fps)
            fps_tc = meta.get("fps_tc") or fps
            meta["tc_segundos"] = inicio / fps_tc if fps_tc else 0.0
            for chave, (tc, _nb) in g["membros"].items():
                if tc is not None and tc != inicio:
                    deslocamento[chave] = tc - inicio
        for chave in g["membros"]:
            offline_por_mob[chave] = caminho
        metadados[caminho] = meta
    return metadados, offline_por_mob, deslocamento


def casamentos(resultado: dict, arquivos: dict[str, str],
               offline: dict[str, str] | None = None) -> list[dict]:
    """`match_results` no formato que `build_drt`/`build_otio` consomem.

    `arquivos` = `{mob_id do master: caminho que EXISTE}`; `offline` = `{mob_id: caminho de
    REFERÊNCIA ao original}` (ver `referencia_offline`), marcado `offline: True`. Não há
    "casamento ambíguo" nesta direção: o master já aponta UM arquivo — por isso `rejected`
    é sempre `False` e não há correção de offset visual.
    """
    offline = offline or {}
    fora = []
    for i, s in enumerate(resultado.get("segments") or []):
        chave = s.get("mob_id") or ""
        caminho = arquivos.get(chave) or offline.get(chave)
        if not caminho or s.get("is_gap") or s.get("is_transition"):
            continue
        e_offline = chave not in arquivos
        if s.get("media_ref") is not None:
            s["media_ref"]["local_path"] = caminho
            s["media_ref"]["url"] = (Path(caminho).as_uri()
                                     if not e_offline and Path(caminho).is_absolute() else "")
        fora.append({"segment_index": i, "matched_path": caminho, "rejected": False,
                     "source_offset_correction": 0, "offline": e_offline})
    return fora
