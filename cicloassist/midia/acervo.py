"""O acervo: que mídia existe em disco, agrupada em CLIPES — sem abrir o Media Composer.

O editor pediu a lista do que já foi analisado **e do que falta**, e o que falta não está
em bin nenhuma: está numa pasta `Avid MediaFiles/MXF/<n>/` com centenas de arquivos.

## ⛔⛔ O nome do arquivo não serve, e é por isso que este módulo existe

O Avid grava **cada track** de um clipe — o vídeo e **cada canal de áudio** — como um
arquivo OP-Atom separado, com nome ilegível (`O CRUZAMENA01.6A8AF212609FA.mxf`). Listar
arquivos daria três linhas `cjehaufgbau.mxf` para o que o editor chama de um clipe só.

⭐ A rota, **confirmada no banco** (`protocolos/mxf/README.md`, medida sobre 540 `.mxf`
= 111 clipes, zero falhas) e reconferida aqui em 2026-09-11:

```
ffprobe -v error -show_format -show_streams -of json ARQUIVO.mxf

format.tags.material_package_umid  → a CHAVE: igual em todas as tracks do clipe
format.tags.material_package_name  → o nome COMO APARECE NA BIN  ← é este que se mostra
stream.codec_type                  → video / audio, para saber de que track é o arquivo
```

⭐⭐ **E a chave é a mesma do cache.** `material_package_umid` é o MobID do MasterMob —
exatamente o que `cache.de_umid()` endereça. Por isso a varredura não é uma segunda
listagem: ela CRUZA com o que a conversa já processou, e o que aparece como "nada
analisado" é mesmo o que falta.

⚠️ `reel_name` e `timecode` não entram aqui: o banco os marca como não confiáveis para
origem, e o segundo pode ser o TC do material em vez do da fonte.

## Custo, medido nesta máquina em 2026-09-11

**~0,08 s por arquivo** (ffprobe frio, disco local). Uma pasta de 1.400 `.mxf` leva perto
de dois minutos — tempo demais para um turno do modelo e para um clique que espera. Por
isso duas coisas:

1. a varredura relata progresso e é interrompível (`parar`);
2. o que já foi sondado fica guardado em `sondagem.json`, endereçado pelo caminho e
   invalidado por tamanho + data. Varrer de novo a mesma pasta custa a listagem, não o
   ffprobe.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .. import binarios as _binarios
from . import cache as _cache

log = logging.getLogger("cicloassist.midia.acervo")

#: Quanto esperamos por UM ffprobe. Passou disso, o arquivo é pulado com aviso: um `.mxf`
#: pela metade (cópia em andamento, disco de rede que caiu) não pode travar a varredura.
PRAZO_DA_SONDA = 20

#: ⭐ A versão do que a sonda GUARDA. Mudou o que se lê de cada arquivo — um campo novo,
#: outra regra —, a sondagem velha deixa de valer sozinha e os arquivos são sondados de
#: novo. Sem isto, um campo acrescentado hoje só apareceria em mídia nova, e a aba diria
#: "não sei a duração" para sempre no acervo que já está em disco.
VERSAO_DA_SONDA = 3

#: ⚠️ `-v error` e nada mais: o ffprobe fala muito em stderr e o Windows entrega isso em
#: cp1252 — texto do console não pode virar exceção no meio de uma varredura.
COMANDO = ["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json"]


class FfprobeAusente(RuntimeError):
    """O ffprobe não está instalado. É pré-requisito do produto, não dependência Python."""


@dataclass
class Clipe:
    """Um clipe do acervo: N arquivos OP-Atom que são a mesma mídia."""

    chave: str
    nome: str
    #: Caminhos das tracks, na ordem em que foram encontrados.
    arquivos: list[str] = field(default_factory=list)
    #: Quantas tracks de cada espécie — `{"video": 1, "audio": 2}`.
    tracks: dict[str, int] = field(default_factory=dict)
    #: A taxa de quadros da imagem, como FRAÇÃO ("24000/1001"). Vazia para som puro.
    fps: str = ""
    #: Duração em segundos, como o ffprobe conta — a da imagem, e a do som quando não há.
    duracao_s: float = 0.0
    #: Taxa de amostragem do som (48000). Zero quando não há som.
    amostragem: int = 0
    #: ⭐ Os arquivos separados por espécie — `{"audio": [...], "video": [...]}`.
    #:
    #: É o que permite analisar um clipe sem passar pelo Media Composer: para transcrever
    #: é preciso entregar ao ffmpeg os OP-Atom de ÁUDIO, e só eles. Misturar a track de
    #: vídeo no `amix` faria o comando falhar inteiro.
    por_tipo: dict[str, list[str]] = field(default_factory=dict)
    bytes: int = 0

    @property
    def tem_imagem(self) -> bool:
        return self.tracks.get("video", 0) > 0

    @property
    def tem_som(self) -> bool:
        return self.tracks.get("audio", 0) > 0

    def como_dicionario(self) -> dict[str, Any]:
        return {
            "chave": self.chave,
            "nome": self.nome,
            "arquivos": list(self.arquivos),
            "tracks": dict(self.tracks),
            "fps": self.fps,
            "duracao_s": self.duracao_s,
            "amostragem": self.amostragem,
            "por_tipo": {k: list(v) for k, v in self.por_tipo.items()},
            "bytes": self.bytes,
            "tem_imagem": self.tem_imagem,
            "tem_som": self.tem_som,
        }


def _sondar(arquivo: Path) -> dict[str, Any] | None:
    """Um `ffprobe`. Devolve `{chave, nome, tipos}` ou `None` se o arquivo não serve."""
    try:
        # ⚠️ O nome em `COMANDO` é resolvido aqui: com o PATH curto de um launcher do Mac,
        #    "ffprobe" puro não é achado (ver `binarios`).
        r = subprocess.run(
            [_binarios.achar(COMANDO[0]) or COMANDO[0], *COMANDO[1:], str(arquivo)],
            capture_output=True,
            timeout=PRAZO_DA_SONDA,
            # ⚠️ Sem isto o Windows abre uma janela de console a cada arquivo — mil e
            #   quatrocentas piscadas na cara de quem está montando.
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError as e:
        raise FfprobeAusente(
            "O ffprobe não está instalado, e é ele que lê a identidade dos arquivos."
        ) from e
    except subprocess.TimeoutExpired:
        log.warning("ffprobe não respondeu a tempo em %s", arquivo)
        return None

    if r.returncode != 0 or not r.stdout:
        return None
    try:
        dados = json.loads(r.stdout.decode("utf-8", errors="replace"))
    except json.JSONDecodeError:
        log.warning("ffprobe devolveu algo que não é JSON em %s", arquivo)
        return None

    marcas = (dados.get("format") or {}).get("tags") or {}
    umid = marcas.get("material_package_umid")
    if not umid:
        # Não é OP-Atom do Avid: `.mxf` de câmera, ou de outro fluxo. Ignorar é o certo —
        # sem MasterMob não há chave, e sem chave não há cache que case.
        return None
    try:
        chave = _cache.de_umid(str(umid))
    except _cache.ChaveInvalida as e:
        log.warning("UMID que não vira chave em %s (%s)", arquivo, e)
        return None

    # ⚠️ Só `video` e `audio`. MEDIDO em 2026-09-11: cada OP-Atom de som desta máquina
    #    traz 1 stream de áudio e **4 de `data`** (timecode e afins). Contá-los faria um
    #    clipe de cinco canais aparecer com vinte e cinco tracks na tela do editor.
    tipos: dict[str, int] = {}
    taxa = ""
    amostragem = 0
    for fluxo in dados.get("streams") or []:
        tipo = str(fluxo.get("codec_type") or "?")
        if tipo in ("video", "audio"):
            tipos[tipo] = tipos.get(tipo, 0) + 1
        if tipo == "video" and not taxa:
            # ⭐ `r_frame_rate` vem como fração ("24000/1001") e é assim que ela tem de
            #   ser guardada: virar float aqui perderia o 23,976 exato, e é dele que sai
            #   a POSIÇÃO do quadro que a gente extrai.
            taxa = str(fluxo.get("r_frame_rate") or "")
        if tipo == "audio" and not amostragem:
            try:
                amostragem = int(fluxo.get("sample_rate") or 0)
            except (TypeError, ValueError):
                amostragem = 0

    sonda = {
        "chave": chave,
        "nome": str(marcas.get("material_package_name") or ""),
        "tipos": tipos,
    }
    # ⚠️ A duração vale para SOM também. Até a versão 2 ela só era lida com imagem, e todo
    #    OP-Atom de áudio ficava com 0 — MEDIDO em 2026-09-13: o ffprobe dá 236,236 s no
    #    `C7 P2-T002`, e o acervo guardava zero.
    try:
        sonda["duracao_s"] = float((dados.get("format") or {}).get("duration") or 0)
    except (TypeError, ValueError):
        sonda["duracao_s"] = 0.0
    if taxa:
        sonda["fps"] = taxa
    if amostragem:
        sonda["amostragem"] = amostragem
    return sonda


class Sondagem:
    """O que já se sabe de cada ARQUIVO, para não sondar duas vezes.

    ⭐ Endereçada pelo caminho e invalidada por tamanho + data de modificação: mídia do
    Avid não muda depois de escrita, então o acerto é praticamente total a partir da
    segunda varredura — que é o que torna a aba utilizável num acervo de verdade.

    ⚠️ Mora na raiz do cache, e não ao lado da mídia: a pasta `Avid MediaFiles` é do
    Avid, e escrever lá é pedir para o Media Composer tropeçar no que não é dele.
    """

    def __init__(self, raiz: Path | None = None):
        self.arquivo = (raiz or _cache.raiz()) / "sondagem.json"
        self._dados: dict[str, Any] = {}
        self._sujo = False
        self._ler()

    def _ler(self) -> None:
        try:
            if self.arquivo.is_file():
                dados = json.loads(self.arquivo.read_text(encoding="utf-8"))
                if isinstance(dados, dict):
                    self._dados = dados
        except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
            # Índice corrompido custa uma varredura, não a conversa do editor.
            log.warning("sondagem ilegível (%s); começando vazia", e)
            self._dados = {}

    @staticmethod
    def _marca(arquivo: Path) -> str:
        try:
            st = arquivo.stat()
            return f"{st.st_size}:{int(st.st_mtime)}"
        except OSError:
            return "?"

    def de(self, arquivo: Path) -> dict[str, Any] | None:
        guardado = self._dados.get(str(arquivo))
        if (isinstance(guardado, dict)
                and guardado.get("marca") == self._marca(arquivo)
                and guardado.get("versao") == VERSAO_DA_SONDA):
            return guardado.get("sonda")
        return None

    def guardar(self, arquivo: Path, sonda: dict[str, Any] | None) -> None:
        # ⚠️ O `None` também é guardado: um arquivo que não é OP-Atom do Avid continua não
        #   sendo na próxima varredura, e re-sondá-lo custaria o mesmo que sondar um bom.
        self._dados[str(arquivo)] = {"marca": self._marca(arquivo),
                                     "versao": VERSAO_DA_SONDA, "sonda": sonda}
        self._sujo = True

    def gravar(self) -> None:
        if not self._sujo:
            return
        try:
            _cache.escrever_atomico(
                self.arquivo,
                json.dumps(self._dados, ensure_ascii=False).encode("utf-8"),
            )
            self._sujo = False
        except OSError as e:
            log.warning("não consegui gravar a sondagem (%s)", e)


def arquivos_de(pasta: Path) -> list[Path]:
    """Os `.mxf` de uma pasta, incluindo as subpastas `MXF/<n>/`.

    ⚠️ Ordenado para que a barra de progresso ande sempre na mesma ordem: uma varredura
    interrompida e retomada aproveita a sondagem das primeiras, e o editor vê a lista
    crescer do mesmo jeito das outras vezes.

    ⭐ **Os `._*` ficam de fora.** MEDIDO nesta máquina em 2026-09-11: **343 de 1.747**
    arquivos são AppleDouble de 4 KB — a sombra que o macOS deixa ao copiar para um disco
    que não é dele. Cada um custava um `ffprobe` que falhava, e eles são um quinto da
    pasta: sondá-los é um quinto da varredura gasto em nada.

    ⛔ **E as pastas ocultas também.** MEDIDO num disco do editor (2026-09-14):
    `Avid MediaFiles/.sync/Archive/` guardava **955 `.mxf`** do Resilio Sync — cópias de
    conflito com o MESMO `material_package_umid` dos originais. Descendo nelas, o clipe
    ganhava tracks em dobro e o `amix` somava uma versão velha da pista junto da atual.
    """
    achados: list[Path] = []

    def falhou(e: OSError) -> None:
        log.warning("não consegui listar %s (%s)", pasta, e)

    for raiz, pastas, arquivos in os.walk(pasta, onerror=falhou):
        pastas[:] = sorted(d for d in pastas if not d.startswith("."))
        achados.extend(Path(raiz) / a for a in arquivos
                       if a.lower().endswith(".mxf") and not a.startswith("._"))
    return sorted(achados)


def varrer(
    pasta: Path | str,
    aviso: Callable[[float, str], None] | None = None,
    parar: threading.Event | None = None,
    sondagem: Sondagem | None = None,
) -> list[Clipe]:
    """Todos os clipes de uma pasta de mídia, agrupados pelo master.

    `aviso(fracao, texto)` conta o andamento; `parar` interrompe e devolve o que já foi
    agrupado — ⭐ devolver o parcial, e não uma lista vazia, é o que faz "cancelar"
    aproveitar o trabalho em vez de jogá-lo fora.
    """
    pasta = Path(pasta)
    arquivos = arquivos_de(pasta)
    indice = sondagem if sondagem is not None else Sondagem()
    clipes: dict[str, Clipe] = {}

    for i, arquivo in enumerate(arquivos):
        if parar is not None and parar.is_set():
            log.info("varredura interrompida em %d de %d", i, len(arquivos))
            break
        if aviso is not None:
            aviso(i / max(1, len(arquivos)), arquivo.name)

        sonda = indice.de(arquivo)
        if sonda is None:
            sonda = _sondar(arquivo)
            indice.guardar(arquivo, sonda)
        if not sonda:
            continue

        clipe = clipes.get(sonda["chave"])
        if clipe is None:
            clipe = clipes[sonda["chave"]] = Clipe(sonda["chave"], sonda.get("nome", ""))
        # ⭐ O nome vem de qualquer track — é o mesmo em todas. Mas o primeiro que aparece
        #   pode estar vazio, e um nome vazio não pode ganhar de um preenchido.
        if not clipe.nome and sonda.get("nome"):
            clipe.nome = sonda["nome"]
        if not clipe.fps and sonda.get("fps"):
            # A duração da IMAGEM ganha: é nela que se contam os quadros.
            clipe.fps = str(sonda["fps"])
            clipe.duracao_s = float(sonda.get("duracao_s") or 0)
        elif not clipe.duracao_s and sonda.get("duracao_s"):
            clipe.duracao_s = float(sonda["duracao_s"])
        if not clipe.amostragem and sonda.get("amostragem"):
            clipe.amostragem = int(sonda["amostragem"])
        clipe.arquivos.append(str(arquivo))
        for tipo, quantos in (sonda.get("tipos") or {}).items():
            clipe.tracks[tipo] = clipe.tracks.get(tipo, 0) + quantos
            clipe.por_tipo.setdefault(tipo, []).append(str(arquivo))
        try:
            clipe.bytes += arquivo.stat().st_size
        except OSError:
            pass

    indice.gravar()
    if aviso is not None:
        aviso(1.0, f"{len(clipes)} clipe(s)")
    return sorted(clipes.values(), key=lambda c: (c.nome.lower(), c.chave))


# ── o resultado guardado ─────────────────────────────────────────────────────
#
# ⭐ A varredura custa um minuto num acervo de verdade, e o editor não pode pagá-lo de
# novo porque trocou de aba ou reiniciou o serviço. O resultado mora ao lado do cache,
# por pasta varrida, e é lido na abertura da aba.


def _arquivo_do_acervo(raiz: Path | None = None) -> Path:
    return (raiz or _cache.raiz()) / "acervo.json"


def guardar(pasta: Path | str, clipes: list[Clipe], raiz: Path | None = None) -> None:
    """Grava o que uma varredura achou, sem apagar o que as outras pastas acharam."""
    destino = _arquivo_do_acervo(raiz)
    tudo: dict[str, Any] = {}
    try:
        if destino.is_file():
            lido = json.loads(destino.read_text(encoding="utf-8"))
            if isinstance(lido, dict):
                tudo = lido
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        tudo = {}

    tudo[str(pasta)] = {
        "quando": int(time.time()),
        "clipes": [c.como_dicionario() for c in clipes],
    }
    try:
        _cache.escrever_atomico(
            destino, json.dumps(tudo, ensure_ascii=False).encode("utf-8")
        )
    except OSError as e:
        log.warning("não consegui guardar o acervo (%s)", e)


def ler(raiz: Path | None = None) -> dict[str, Any]:
    """O que as varreduras já acharam: `{"pastas": {...}, "clipes": {chave: clipe}}`.

    ⚠️ A mesma mídia pode aparecer em duas pastas varridas (uma cópia, um consolidate).
    A chave é o master, então a segunda ocorrência **soma os arquivos** em vez de
    substituir a primeira — senão a tela diria que o clipe tem duas tracks quando tem
    seis, três em cada pasta.
    """
    destino = _arquivo_do_acervo(raiz)
    try:
        if not destino.is_file():
            return {"pastas": {}, "clipes": {}}
        tudo = json.loads(destino.read_text(encoding="utf-8"))
        if not isinstance(tudo, dict):
            return {"pastas": {}, "clipes": {}}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
        log.warning("acervo ilegível (%s); tratando como vazio", e)
        return {"pastas": {}, "clipes": {}}

    pastas: dict[str, Any] = {}
    clipes: dict[str, Any] = {}
    for pasta, dados in tudo.items():
        if not isinstance(dados, dict):
            continue
        lista = dados.get("clipes")
        if not isinstance(lista, list):
            continue
        pastas[pasta] = {"quando": dados.get("quando", 0), "clipes": len(lista)}
        for c in lista:
            if not isinstance(c, dict) or not c.get("chave"):
                continue
            ja = clipes.get(c["chave"])
            if ja is None:
                clipes[c["chave"]] = dict(c)
                continue
            ja["arquivos"] = list(ja.get("arquivos", [])) + list(c.get("arquivos", []))
            ja["bytes"] = ja.get("bytes", 0) + c.get("bytes", 0)
            for tipo, quais in (c.get("por_tipo") or {}).items():
                ja.setdefault("por_tipo", {}).setdefault(tipo, []).extend(quais)
            for tipo, quantos in (c.get("tracks") or {}).items():
                ja["tracks"][tipo] = ja.get("tracks", {}).get(tipo, 0) + quantos
    return {"pastas": pastas, "clipes": clipes}


def pastas_de_midia(raizes: Iterable[str | Path] | None = None) -> list[Path]:
    """Onde procurar `Avid MediaFiles` sem perguntar nada ao editor.

    ⚠️ Só a raiz de cada volume, e sem descer: `Avid MediaFiles` mora na raiz do disco por
    convenção do Avid, e sair varrendo o disco atrás dela custaria minutos e acharia
    cópias velhas que ninguém quer na lista.
    """
    if raizes is None:
        raizes = _raizes_dos_volumes()

    achadas: list[Path] = []
    vistas: set[str] = set()
    for raiz in raizes:
        alvo = Path(raiz) / "Avid MediaFiles"
        try:
            if not alvo.is_dir():
                continue
            # ⚠️ `/Volumes/Macintosh HD` é um atalho para `/`: sem isto o disco de sistema
            #    entraria duas vezes na lista.
            real = os.path.realpath(alvo)
        except OSError:
            continue
        if real not in vistas:
            vistas.add(real)
            achadas.append(alvo)
    return achadas


def _raizes_dos_volumes() -> list[Path]:
    """A raiz de cada volume montado.

    ⛔ No Mac, `/Volumes` é a pasta DOS volumes, não um volume: procurar
    `/Volumes/Avid MediaFiles` nunca achava nada (MEDIDO 2026-09-14, com duas `Avid
    MediaFiles` montadas). E o disco de sistema do Mac guarda a mídia em
    `/Users/Shared/AvidMediaComposer/Avid MediaFiles`, não na raiz.
    """
    if os.name == "nt":
        return [Path(f"{letra}:\\") for letra in "CDEFGHIJKLMNOPQRSTUVWXYZ"]
    raizes = [Path("/Users/Shared/AvidMediaComposer"), Path("/")]
    for pai in (Path("/Volumes"), Path("/media"), Path("/mnt")):
        try:
            filhos = sorted(pai.iterdir())
        except OSError:
            continue
        for filho in filhos:
            try:
                if filho.is_dir():
                    raizes.append(filho)
                    # Linux monta em `/media/<usuário>/<volume>`: um nível a mais.
                    if pai.name == "media":
                        raizes.extend(sorted(n for n in filho.iterdir() if n.is_dir()))
            except OSError:
                continue
    return raizes
