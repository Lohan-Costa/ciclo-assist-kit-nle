"""De um ARQUIVO à mídia do cache: a mesma pergunta vinda do Avid e do Premiere.

O cache é endereçado pela chave do master (`cache.py`). No Avid a chave sai da bin; no
Premiere só existe o arquivo que o item aponta. Este módulo responde "que mídia é esta?"
a partir do arquivo, e é a P1 do plano `docs/plano/2026-09-17-premiere.md`.

## A chave de um arquivo

| o arquivo traz | a chave | por quê |
|---|---|---|
| `material_package_umid` (OP-Atom, MXF de câmera) | o UMID | é o MobID que o Avid copia para a bin (banco, `banco-de-midias-compartilhado.md` §1) |
| nada (MOV, MP4, BRAW, WAV) | **a impressão do conteúdo** | ⛔ o `mob_id` do AMA é GERADO a cada link: a mesma `.mov` em dois projetos seriam duas mídias |

A impressão é o SHA-256 do tamanho + primeiros e últimos 4 MB (spec
`2026-09-13-cache-legivel-e-compartilhado.md` §5): lê 8 MB, mesmo pela rede, e não depende
de NLE nenhum.

## ⭐⭐ O convertido: candidato por metadado, decisão por conteúdo

O Avid processou o OP-Atom de um transcode; o Premiere aponta o original. São dois arquivos
diferentes, e nenhum carrega a identidade do outro. MEDIDO em 2026-09-17
(`spikes/o_convertido_casa.py`, banco §8 da mesma página):

1. **candidato** — nome da fonte + TC + taxa + quadros (vídeo) ou nome + duração (som).
   Os pares verdadeiros bateram em tudo; os impostores (o take vizinho) em nada.
2. **confirmação** — o MESMO conteúdo:
   - imagem: correlação de 5 quadros EXATOS, 32×32 cinza. Verdadeiros 1,000 e 0,992;
     impostores −0,07 e 0,52. Piso `PISO_IMAGEM`.
   - som: correlação cruzada das amostras, com folga de deslocamento — o OP-Atom do Avid
     começa 398 amostras (8 ms) depois do WAV, alinhado ao quadro. Verdadeiro 1,000.

⛔ **Nome + TC + duração nunca decidem sozinhos** (banco §2): reaproveitar errado anexaria a
decupagem de um plano a outro, sem erro nenhum. E o embedding do produto não serve de juiz:
o MobileNet deu 0,909 a um impostor — ele mede "parecido", e a pergunta é "o mesmo".

O resultado é um **apelido** na mídia do cache, com a medida na procedência: o original
passa a achar a pasta do convertido na hora, sem medir de novo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import threading
import unicodedata
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from .. import binarios as _binarios
from . import cache as _cache

log = logging.getLogger("cicloassist.midia.identidade")

PEDACO = 4 * 1024 * 1024
#: Mudou a conta da impressão ou o que se guarda da sonda: tudo é lido de novo.
#: ⚠️ v2 (2026-09-21): `canais_de_som`, quantos CANAIS tem cada pista. Sem isso não havia
#: como comparar som multipista canal a canal — ver `mesmo_som`.
#: ⚠️ v3 (2026-09-21): `reel_name` degenerado deixa de mandar (`_nome_da_fonte`).
#: Reler é só ffprobe.
VERSAO = 3

PISO_IMAGEM = 0.95
PISO_SOM = 0.90
#: O que a comparação devolve quando **não conseguiu comparar** — e que NÃO é "é outro
#: material". ⛔⛔ Confundir os dois é o defeito que este módulo já pagou duas vezes (o
#: clipe de 4 quadros, e o BRAW que não decodifica imagem).
NAO_COMPAREI = -1.0
#: Quantos quadros do começo são decodificados para comparar (~1 min a 23,976).
JANELA_QUADROS = 1440
POSICOES = 5
#: Segundos de som comparados, e a folga de deslocamento entre os dois.
JANELA_SOM_S = 30
FOLGA_SOM_S = 0.5
TAXA_SOM = 8000

EXTENSOES = {"mov", "mp4", "mxf", "wav", "aif", "aiff", "braw", "r3d", "mts", "m4v",
             "avi", "mkv", "bwf"}


class IdentidadeErro(RuntimeError):
    pass


def _sem_janela() -> dict[str, Any]:
    # ⚠️ Sem isto o Windows abre um console por ffprobe (ver `acervo._sondar`).
    return {"creationflags": getattr(subprocess, "CREATE_NO_WINDOW", 0)}


def _exe(nome: str) -> str:
    return _binarios.achar(nome) or nome


# ── o registro: o que já se sabe de cada arquivo ─────────────────────────────


class _Registro:
    """`identidades.json` na raiz do cache: caminho → marca (tamanho:mtime) → o que se leu.

    Mesmo desenho da `acervo.Sondagem`, e pelo mesmo motivo: a mídia não muda depois de
    escrita, e ler 8 MB ou rodar ffprobe a cada pergunta do Premiere seria o gargalo.
    """

    def __init__(self) -> None:
        self.trava = threading.Lock()
        self._dados: dict[str, Any] | None = None
        self._onde: Path | None = None

    def _arquivo(self) -> Path:
        return _cache.raiz() / "identidades.json"

    def _carregar(self) -> dict[str, Any]:
        onde = self._arquivo()
        if self._dados is None or self._onde != onde:
            self._onde = onde
            try:
                dados = json.loads(onde.read_text(encoding="utf-8")) if onde.is_file() else {}
            except (OSError, json.JSONDecodeError, UnicodeDecodeError) as e:
                log.warning("identidades.json ilegível (%s); começando vazio", e)
                dados = {}
            self._dados = dados if isinstance(dados, dict) else {}
        return self._dados

    @staticmethod
    def _chave(arquivo: Path) -> str:
        return unicodedata.normalize("NFC", str(arquivo))

    @staticmethod
    def marca(arquivo: Path) -> str:
        st = arquivo.stat()
        return f"{st.st_size}:{int(st.st_mtime)}"

    def ler(self, arquivo: Path, campo: str) -> Any:
        with self.trava:
            item = self._carregar().get(self._chave(arquivo))
            try:
                marca = self.marca(arquivo)
            except OSError:
                return None
            if isinstance(item, dict) and item.get("marca") == marca \
                    and item.get("versao") == VERSAO:
                return item.get(campo)
            return None

    def guardar(self, arquivo: Path, campo: str, valor: Any) -> None:
        with self.trava:
            dados = self._carregar()
            try:
                marca = self.marca(arquivo)
            except OSError:
                return
            item = dados.get(self._chave(arquivo))
            if not (isinstance(item, dict) and item.get("marca") == marca
                    and item.get("versao") == VERSAO):
                item = {"marca": marca, "versao": VERSAO}
            item[campo] = valor
            dados[self._chave(arquivo)] = item
            try:
                _cache.escrever_atomico(self._arquivo(),
                                        json.dumps(dados, ensure_ascii=False).encode("utf-8"))
            except OSError as e:
                log.warning("não consegui gravar identidades.json (%s)", e)

    def esquecer(self) -> None:
        with self.trava:
            self._dados = None


_registro = _Registro()


def esquecer() -> None:
    """Joga fora o que este processo leu do disco (os testes trocam de raiz)."""
    _registro.esquecer()


# ── o que um arquivo é ───────────────────────────────────────────────────────


def impressao(arquivo: str | Path) -> str:
    """SHA-256 de tamanho + primeiros e últimos `PEDACO` bytes, em 64 hexadecimais."""
    arquivo = Path(arquivo)
    guardada = _registro.ler(arquivo, "impressao")
    if guardada:
        return guardada
    tamanho = arquivo.stat().st_size
    h = hashlib.sha256(b"ciclo-conteudo-v1")
    h.update(tamanho.to_bytes(8, "little"))
    with open(arquivo, "rb") as f:
        h.update(f.read(PEDACO))
        if tamanho > PEDACO:
            f.seek(max(PEDACO, tamanho - PEDACO))
            h.update(f.read(PEDACO))
    valor = h.hexdigest()
    _registro.guardar(arquivo, "impressao", valor)
    return valor


def _fracao(texto: Any) -> Fraction | None:
    try:
        f = Fraction(str(texto))
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def sondar(arquivo: str | Path) -> dict[str, Any]:
    """O que o ffprobe diz do arquivo, reduzido ao que identifica. Guardado por marca.

    Campos: `umid` (64 hex ou ""), `nome_da_fonte`, `tc`, `fps` (fração, do
    `avg_frame_rate`), `quadros`, `duracao_s`, `tipo` (`video`/`audio`), `pistas_de_som`,
    `canais_de_som` (quantos canais em cada pista) e `busca_suspeita`.

    ⚠️ **Pista não é canal**, e a diferença custou um defeito: o WAV de um gravador de som
    direto é **uma** pista com **cinco** canais, e o Avid guarda isso como **cinco**
    OP-Atom de uma pista cada. Quem contar pistas dos dois lados acha 1 contra 5.
    """
    arquivo = Path(arquivo)
    guardada = _registro.ler(arquivo, "sonda")
    if isinstance(guardada, dict):
        return guardada
    try:
        r = subprocess.run([_exe("ffprobe"), "-v", "error", "-show_format", "-show_streams",
                            "-of", "json", str(arquivo)],
                           capture_output=True, timeout=30, **_sem_janela())
    except (OSError, subprocess.TimeoutExpired) as e:
        raise IdentidadeErro(f"não consegui ler {arquivo.name} com o ffprobe ({e})") from e
    if r.returncode != 0:
        raise IdentidadeErro(f"o ffprobe não reconhece {arquivo.name}")
    try:
        dados = json.loads(r.stdout.decode("utf-8", "replace") or "{}")
    except json.JSONDecodeError as e:
        raise IdentidadeErro(f"o ffprobe devolveu lixo para {arquivo.name}") from e

    formato = dados.get("format") or {}
    marcas = formato.get("tags") or {}
    fluxos = dados.get("streams") or []
    video = next((s for s in fluxos if s.get("codec_type") == "video"
                  and (s.get("disposition") or {}).get("attached_pic") != 1), None)
    som = [s for s in fluxos if s.get("codec_type") == "audio"]

    umid = ""
    if marcas.get("material_package_umid"):
        try:
            umid = _cache.de_umid(str(marcas["material_package_umid"]))
        except _cache.ChaveInvalida:
            umid = ""

    tc = str(marcas.get("timecode") or "")
    for s in fluxos:
        tc = tc or str((s.get("tags") or {}).get("timecode") or "")

    try:
        duracao = float(formato.get("duration") or 0)
    except (TypeError, ValueError):
        duracao = 0.0

    # ⚠️ `avg_frame_rate`: no OP-Atom o `r_frame_rate` vem pela metade (banco, mxf).
    fps = _fracao((video or {}).get("avg_frame_rate")) if video else None
    r_fps = _fracao((video or {}).get("r_frame_rate")) if video else None
    quadros = 0
    if video:
        try:
            quadros = int((video or {}).get("nb_frames") or 0)
        except (TypeError, ValueError):
            quadros = 0
        if not quadros and fps:
            quadros = round(duracao * fps)

    nome = _nome_da_fonte(arquivo, marcas, fluxos)

    sonda = {
        "umid": umid,
        "nome_da_fonte": str(nome),
        "tc": tc,
        "fps": str(fps) if fps else "",
        "quadros": quadros,
        "duracao_s": duracao,
        "tipo": "video" if video else ("audio" if som else ""),
        "pistas_de_som": len(som),
        "canais_de_som": [max(1, int(s.get("channels") or 1)) for s in som],
        # ⛔⛔ MEDIDO (banco, mxf): com o `r_frame_rate` pela metade, a busca rápida do
        #    ffmpeg entrega o quadro N/2. Quem extrai quadro precisa saber.
        "busca_suspeita": bool(fps and r_fps and r_fps * 2 == fps),
    }
    _registro.guardar(arquivo, "sonda", sonda)
    return sonda


#: Um `reel_name` que é só número (ou de 1-2 letras) é o ROLO, não o nome do clipe.
#: ⛔⛔ MEDIDO em 2026-09-21: o contêiner BRAW traz `reel_name = "1"` numa tag de stream, e
#: ela vencia o nome do arquivo — `B001_03150115_C003.BRAW` virava a fonte `"1"`. Com isso o
#: BRAW não era candidato do próprio transcode que o Avid já tinha processado (fps, número
#: de quadros e TC IDÊNTICOS), e o editor reprocessaria do zero. ⚠️ Nos 332 masters deste
#: cache, NENHUM OP-Atom tem nome degenerado: a regra só alcança quem ela deve alcançar.
_ROLO = re.compile(r"^\s*(\d{1,4}|.{1,2})\s*$")


def _nome_da_fonte(arquivo: Path, marcas: dict, fluxos: list) -> str:
    """O nome de origem que serve de PISTA — nunca um rótulo de rolo.

    ⭐ A precedência é a de sempre (o `reel_name` do stream manda, depois o do contêiner,
    depois o nome do arquivo); o que muda é que um valor degenerado não entra na disputa.
    """
    candidatos_ = [(s.get("tags") or {}).get("reel_name") for s in reversed(fluxos)]
    candidatos_ += [marcas.get("reel_name"), marcas.get("material_package_name"),
                    marcas.get("comment_TapeID")]
    for c in candidatos_:
        texto = str(c or "").strip()
        if texto and not _ROLO.match(texto):
            return texto
    return arquivo.name


def chave_do_arquivo(arquivo: str | Path) -> tuple[str, str]:
    """(chave, tipo): o UMID do arquivo se ele tiver, senão a impressão do conteúdo."""
    arquivo = Path(arquivo)
    try:
        umid = sondar(arquivo).get("umid") or ""
    except IdentidadeErro:
        umid = ""
    if umid:
        return umid, "umid"
    return impressao(arquivo), "conteudo"


def chave_conhecida(arquivo: str | Path) -> str:
    """A chave do arquivo SEM pagar a impressão: o UMID (ffprobe, guardado) ou a impressão
    que já estiver no registro. Vazio quando não se sabe.

    ⭐ É o que o RECORTE do projeto usa. MEDIDO em 2026-09-17: ler 8 MB por arquivo para
    montar o escopo de um projeto de 300 clipes são ~2,4 GB lidos antes de a primeira busca
    responder, com o painel mostrando "pensando…". E não custa acerto: um arquivo cuja
    impressão ninguém calculou nunca foi analisado — logo não está no cache, e não muda
    recorte nenhum.
    """
    arquivo = Path(arquivo)
    try:
        umid = sondar(arquivo).get("umid") or ""
    except IdentidadeErro:
        umid = ""
    return umid or (_registro.ler(arquivo, "impressao") or "")


def normalizar_nome(nome: str) -> str:
    """O nome como PISTA: sem pasta, extensão de mídia, sufixo `.new.NN` do Avid, caixa, acento.

    ⛔⛔ **E sem o `:<rolo>` que o Avid gruda no `reel_name` do SOM.** MEDIDO em 2026-09-21
    no acervo do editor: o OP-Atom de som diz
    `PRODUCAO-A - 05-04 C14 P1-T010.WAV:2023-04-06` enquanto o arquivo original é
    `PRODUCAO-A - 05-04 C14 P1-T010.WAV`. Como o `.wav` deixava de ser o FIM do nome, a
    extensão não era removida, os dois nomes divergiam, e o par nem chegava a ser
    candidato — com as durações **idênticas** (146,146 s nos dois). **36 das 332 mídias
    deste cache** têm essa forma, e são todas de som: a camada MAIOR do acervo.

    ⚠️ O buraco existia porque os pares medidos no porte (banco, §8) eram os dois de
    IMAGEM. O reel de vídeo não leva o `:data`.

    ⭐ Tirar o qualificador só ALARGA a candidatura, nunca decide: quem decide continua
    sendo a correlação de conteúdo. Errar para mais custa uma comparação; errar para menos
    custa reprocessar uma mídia que já estava pronta.
    """
    n = re.split(r"[\\/]", str(nome))[-1]
    n = unicodedata.normalize("NFKD", n).encode("ascii", "ignore").decode().casefold().strip()
    n = re.sub(r":[^:\\/]*$", "", n) or n
    m = re.match(r"^(.*)\.([a-z0-9]{2,4})$", n)
    if m and m.group(2) in EXTENSOES:
        n = m.group(1)
    return re.sub(r"\.new\.\d+$", "", n)


def e_candidato(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Os metadados permitem que `a` e `b` sejam o mesmo material? Nunca decide sozinho."""
    if not a.get("tipo") or a.get("tipo") != b.get("tipo"):
        return False
    if normalizar_nome(a.get("nome_da_fonte", "")) != normalizar_nome(b.get("nome_da_fonte", "")):
        return False
    if a["tipo"] == "video":
        if not a.get("fps") or a.get("fps") != b.get("fps"):
            return False
        # banco (`avb/escrita.md`): o original costuma ter 1 quadro a mais que o transcode.
        if abs(int(a.get("quadros") or 0) - int(b.get("quadros") or 0)) > 1:
            return False
        if a.get("tc") and b.get("tc") and a["tc"] != b["tc"]:
            return False
        return True
    # Som: o WAV não traz `timecode` como tag, então a régua é a duração — com a folga de
    # um quadro, que é o quanto o Avid arredonda (medido: 53,989 s → 54,012 s).
    return abs(float(a.get("duracao_s") or 0) - float(b.get("duracao_s") or 0)) <= 0.1


# ── o conteúdo ───────────────────────────────────────────────────────────────


def _quadros_exatos(arquivo: Path, posicoes: list[int], lado: int = 32):
    """Os quadros N, decodificados EM ORDEM — nunca por busca (ver `sondar.busca_suspeita`)."""
    import numpy as np

    expr = "+".join(f"eq(n\\,{q})" for q in posicoes)
    r = subprocess.run(
        [_exe("ffmpeg"), "-v", "error", "-i", str(arquivo), "-an",
         "-vf", f"select={expr},scale={lado}:{lado},format=gray",
         "-vsync", "0", "-frames:v", str(len(posicoes)), "-f", "rawvideo", "pipe:1"],
        capture_output=True, timeout=600, **_sem_janela())
    bruto = np.frombuffer(r.stdout, dtype=np.uint8).astype(np.float32)
    return bruto[: (len(bruto) // (lado * lado)) * lado * lado].reshape(-1, lado * lado)


def _pearson(x, y) -> float:
    import numpy as np

    x = (x - x.mean()) / (x.std() + 1e-6)
    y = (y - y.mean()) / (y.std() + 1e-6)
    return float(np.mean(x * y))


def mesma_imagem(a: str | Path, b: str | Path, quadros: int) -> float:
    """A menor correlação entre `POSICOES` quadros iguais dos dois arquivos (−1 a 1).

    ⚠️ **Clipe mais curto que `POSICOES` pedia posições REPETIDAS**, e o `select` do ffmpeg
    só entrega cada quadro uma vez: voltavam menos quadros que posições, e a conferência
    devolvia `-1` — que se lê como "não é o mesmo material" quando a verdade é "não
    consegui comparar". MEDIDO em 2026-09-21: `B001_03150154_C017`, de **4 quadros**
    (0,23 s), era o único vídeo do projeto do editor que não casava, com nome, TC, taxa e
    número de quadros idênticos aos do cache. Sem posição repetida ele casa — e comparar
    4 de 4 quadros é mais prova, não menos.
    """
    from . import frames as _frames

    posicoes = sorted({*_frames.distribuir(0, min(int(quadros), JANELA_QUADROS), POSICOES)})
    if not posicoes:
        return -1.0
    qa, qb = _quadros_exatos(Path(a), posicoes), _quadros_exatos(Path(b), posicoes)
    if len(qa) != len(posicoes) or len(qb) != len(posicoes):
        return -1.0
    return min(_pearson(x, y) for x, y in zip(qa, qb))


def _som_por_canal(arquivos: list[Path]):
    """Cada CANAL separado, `(n_canais, n_amostras)` a `TAXA_SOM`.

    ⛔⛔ **Canal, não pista.** O WAV de um gravador de som direto é UMA pista com CINCO
    canais; o Avid guarda o mesmo material como CINCO OP-Atom de uma pista cada. Abrir por
    pista dá 1 contra 5, e a comparação vira mixagem contra mixagem — que é o defeito que
    `mesmo_som` documenta.

    ⭐ Uma chamada de ffmpeg por ARQUIVO, e o `f32le` já sai **intercalado**: o numpy
    desdobra os canais com um `reshape`. Nada de `amerge` — juntar canais de arquivos
    diferentes num grafo só devolveu "nothing was written" com o som do editor, e um
    filtro que falha devolvendo zero byte se lê como "não é o mesmo material".
    """
    import numpy as np

    canais: list = []
    for arq in arquivos:
        try:
            quantos = sum(max(1, int(c or 1)) for c in (sondar(arq).get("canais_de_som") or []))
        except IdentidadeErro:
            quantos = 0
        if quantos <= 0:
            continue
        r = subprocess.run(
            [_exe("ffmpeg"), "-v", "error", "-i", str(arq), "-map", "0:a",
             "-ac", str(quantos), "-ar", str(TAXA_SOM), "-t", str(JANELA_SOM_S),
             "-f", "f32le", "pipe:1"],
            capture_output=True, timeout=600, **_sem_janela())
        if not r.stdout:
            log.warning("não consegui abrir o som de %s (%s)", arq.name,
                        (r.stderr.decode("utf-8", "replace").strip().splitlines() or [""])[-1])
            continue
        cru = np.frombuffer(r.stdout, dtype=np.float32)
        bloco = cru[: (len(cru) // quantos) * quantos].reshape(-1, quantos).T
        canais.extend(bloco)
    if not canais:
        return np.zeros((0, 0), dtype=np.float32)
    # ⚠️ Arquivos podem sair com contagens diferentes de amostras (arredondamento do
    #   resample): apara no menor, que é o que `_pico` faria de qualquer jeito.
    menor = min(len(c) for c in canais)
    return np.stack([c[:menor] for c in canais])


def _pico(xa, xb) -> float:
    """O pico da correlação cruzada normalizada de dois sinais, com `FOLGA_SOM_S` de folga."""
    import numpy as np

    n = min(len(xa), len(xb))
    if n < TAXA_SOM:  # menos de 1 s: não há o que comparar
        return -1.0
    xa = xa[:n] - xa[:n].mean()
    xb = xb[:n] - xb[:n].mean()
    norma = float(np.linalg.norm(xa) * np.linalg.norm(xb))
    if norma <= 0:
        return -1.0  # silêncio digital nos dois não prova nada
    cc = np.fft.ifft(np.fft.fft(xa) * np.conj(np.fft.fft(xb))).real
    folga = int(FOLGA_SOM_S * TAXA_SOM)
    janela = np.concatenate([cc[: folga + 1], cc[-folga:]])
    return float(np.max(janela) / norma)


def mesmo_som(a: list[str | Path], b: list[str | Path]) -> float:
    """É o mesmo material sonoro? Pista a pista, e nunca pela MISTURA.

    ⛔⛔ **A mistura dos dois lados não prova nada quando o som é multipista** — MEDIDO em
    2026-09-21, no `PRODUCAO-A - 05-04 C11 P1-T001` do editor. O WAV do gravador tem 5
    canais e o Avid guardou 5 OP-Atom, e a soma dos cinco de cada lado correlaciona
    **0,876** — abaixo do piso, logo "não é o mesmo material". Canal a canal:

    ```
           A01    A02    A03    A04    A05
    ch1  +0,044 +0,044 +0,037 +0,054 +0,998
    ch2  +1,000 +1,000 +0,807 +0,592 +0,043
    ch3  +0,807 +0,807 +1,000 +0,072 +0,037
    ch4  +0,592 +0,592 +0,072 +1,000 +0,053
    ch5  +0,043 +0,043 +0,037 +0,053 +1,000
    ```

    É **o mesmo som, em outra ordem e com uma pista duplicada** (A01 = A02 = ch2; o mixdown
    do gravador está em ch1/ch5 e em A05). Somar lados que trazem as mesmas pistas em
    proporções diferentes dá um sinal diferente — e o defeito aparece justamente no
    material mais valioso, o som direto de cena, que é a camada transcrita.

    ⇒ A régua é: **canal a canal, e o MELHOR par decide** — com o piso de sempre.

    ⚠️⚠️ **Eu tinha escrito "o PIOR par", e o material me corrigiu no mesmo dia.** Exigir
    que TODO canal de um dos lados achasse o seu reprovou um par verdadeiro:
    `A009_03190845_C003.BRAW` contra o OP-Atom dele deu `ch1 +0,789 · ch2 +1,000` — 547
    quadros, TC e duração idênticos nos dois. O 0,789 é o transcode processando uma das
    pistas, e é **exatamente o que um convertido faz**: pedir que toda pista sobreviva ao
    transcode é pedir que ele seja sem perdas por canal, que ele não é.

    ⛔ **E o melhor par não afrouxa o impostor, porque a porteira é o METADADO.** Só chega
    aqui quem já casou em nome, taxa, número de quadros e TC de início. O que o melhor par
    separa, ele separa por duas ordens de grandeza:

    | | melhor par |
    |---|---|
    | WAV de 5 canais × os 5 OP-Atom dele | **+1,000** (a MISTURA dava 0,876) |
    | idem, contra só 2 das 5 pistas | **+1,000** |
    | BRAW × o OP-Atom dele (uma pista processada) | **+1,000** |
    | impostor: o take vizinho, mesma cena, mesmo gravador | **+0,024** |
    | impostor: outro take da mesma câmera, mesmo dia | **+0,033** |

    ⚠️ Canal em silêncio digital não vota (não há o que correlacionar); se nenhum votar, a
    resposta é "não sei", nunca "é o mesmo".
    """
    pa = _som_por_canal([Path(p) for p in a])
    pb = _som_por_canal([Path(p) for p in b])
    if pa.size == 0 or pb.size == 0:
        return NAO_COMPAREI
    pares = [_pico(x, y) for x in pa for y in pb]
    return max(pares) if pares else NAO_COMPAREI


# ── a pergunta: que mídia do cache é este arquivo? ───────────────────────────


def _quantas_midias(raiz: Path | None = None) -> int:
    """Quantas mídias (e apelidos) o cache tem AGORA — o carimbo do veredito negativo."""
    ind = _cache.indice(raiz)
    ind.varrer()
    with ind.trava:
        return len(ind.mapa) + len(ind.apelidos)


@dataclass
class Achado:
    midia: _cache.Midia | None
    #: `chave` (o arquivo já é a chave ou um apelido dela) · `convertido` (medido agora,
    #: no MESMO banco) · `outro_banco` (medido, mas a entrada é de outro editor — ver
    #: `aproveitar`) · `nada`
    como: str
    chave: str
    tipo: str
    medida: float | None = None
    avisos: list[str] = field(default_factory=list)


def _arquivos_da_midia(m: _cache.Midia) -> tuple[str, list[Path]]:
    manifesto = m.manifesto()
    tipo = str(manifesto.get("tipo") or "")
    arquivos = [Path(a) for a in manifesto.get("arquivos") or []]
    arquivos = [a for a in arquivos if a.is_file()]
    return tipo, arquivos


def _o_da_imagem(arquivos: list[Path]) -> Path | None:
    for a in arquivos:
        try:
            if sondar(a).get("tipo") == "video":
                return a
        except IdentidadeErro:
            continue
    return None


def candidatos(alvo: dict[str, Any], raiz: Path | None = None,
               ampliar: bool = False) -> list[tuple[_cache.Midia, list[Path]]]:
    """As mídias do cache cujo material PODE ser o do alvo. Nome primeiro (sem disco).

    ⭐ O filtro barato é o nome do MANIFESTO — o da bin —, e ele é o certo no caso comum:
    OP-Atom sem `reel_name` responde com o nome ilegível `A01.E69C….mxf`.

    ⛔⛔ **Mas o editor RENOMEIA o take na bin, e aí o filtro barato cega.** MEDIDO em
    2026-09-21: o arquivo é `PRODUCAO-A - 05-04 C14 P1-T010.WAV` e a bin do Avid chama
    o mesmo material de `PRODUCAO-A - 05-04 C14 P1/010` — `-T010` virou `/010`. Os dois
    OP-Atom trazem o `reel_name` certo e a duração idêntica (146,146 s), mas a mídia nem
    chegava a ser candidata: o Premiere reprocessaria uma transcrição que já existia.

    ⇒ `ampliar` refaz a busca pelo nome que está DENTRO do arquivo. Custa uma sondagem por
    mídia do mesmo tipo (ffprobe, guardado para sempre), e por isso só é usado quando a
    passada barata não achou NADA — que é exatamente onde a alternativa é reprocessar.
    """
    nome = normalizar_nome(alvo.get("nome_da_fonte", ""))
    saida = []
    for m in _cache.todas(raiz):
        manifesto = m.manifesto()
        pelo_manifesto = normalizar_nome(str(manifesto.get("nome") or "")) == nome
        if not (pelo_manifesto or ampliar):
            continue
        tipo, arquivos = _arquivos_da_midia(m)
        if not arquivos:
            continue
        referencia = _o_da_imagem(arquivos) if alvo.get("tipo") == "video" else arquivos[0]
        if referencia is None:
            continue
        try:
            dela = dict(sondar(referencia))
        except IdentidadeErro:
            continue
        if pelo_manifesto:
            # O nome já casou pelo manifesto (o da bin): é ele que vale, e não o do arquivo.
            dela["nome_da_fonte"] = str(manifesto.get("nome") or "")
        if e_candidato(alvo, dela):
            saida.append((m, arquivos))
    return saida


def _sons_de(arquivos: list[Path]) -> list[Path]:
    """Os arquivos que TÊM som — um master de câmera traz imagem e som no mesmo arquivo."""
    saida = []
    for a in arquivos:
        try:
            if sondar(a).get("canais_de_som"):
                saida.append(a)
        except IdentidadeErro:
            continue
    return saida


def _conferir(arquivo: Path, alvo: dict[str, Any],
              arquivos: list[Path]) -> tuple[float, float, str]:
    """É o mesmo material? `(medida, piso, fonte da procedência)`.

    ⭐⭐ **Imagem primeiro; SOM quando a imagem não pôde ser comparada.** MEDIDO em
    2026-09-21 no BRAW do editor: o `ffprobe` lê fps (24000/1001), nº de quadros (499) e TC
    (01:15:06:15) do contêiner — todos IDÊNTICOS aos do OP-Atom que o Avid já processou —,
    mas a essência de vídeo não decodifica, e a conferência por pixel devolve `-1`. Pelo
    som do próprio clipe:

    | | medida |
    |---|---|
    | BRAW × o OP-Atom dele (que já tem quadros, fala e vetores) | **+1,000** em 0,4 s |
    | por pixel | **−1,000** (não abre) |
    | impostor: outro take da mesma câmera, no mesmo dia | **+0,033** |

    ⛔⛔ **Só o `-1` cai para o som, nunca um desacordo.** Pixel que diz "é outro material"
    é uma RESPOSTA, e deixá-la ser resgatada pelo som aceitaria um rewrap de imagem
    diferente com o mesmo áudio. O que cai é "não consegui comparar" — que nunca foi um
    veredito.

    ⭐ E a procedência acompanha: `fonte` diz se quem confirmou foi o pixel ou a onda.
    """
    if alvo.get("tipo") != "video":
        return mesmo_som([arquivo], _sons_de(arquivos)), PISO_SOM, "sonora"

    dele = _o_da_imagem(arquivos)
    medida = (mesma_imagem(arquivo, dele, int(alvo.get("quadros") or 0))
              if dele else NAO_COMPAREI)
    if medida > NAO_COMPAREI:
        return medida, PISO_IMAGEM, "visual"

    # A imagem não pôde ser comparada (RAW de câmera que o ffmpeg não decodifica, clipe
    # sem imagem legível). O som do MESMO clipe decide — se houver dos dois lados.
    sons = _sons_de(arquivos)
    if sons and alvo.get("canais_de_som"):
        return mesmo_som([arquivo], sons), PISO_SOM, "sonora"
    return NAO_COMPAREI, PISO_IMAGEM, "visual"


def achar(arquivo: str | Path, medir: bool = True, raiz: Path | None = None,
          relatar: Callable[[str], None] | None = None, origem: str = "") -> Achado:
    """Que mídia do cache é `arquivo`? Pela chave, pelo apelido, e — com `medir` — pelo
    conteúdo de um convertido dela.

    ⚠️ `medir` decodifica até um minuto de cada lado: segundos, não milissegundos. Uma vez
    medido, vira apelido e a próxima pergunta é instantânea.
    """
    arquivo = Path(arquivo)
    chave, tipo = chave_do_arquivo(arquivo)
    m = _cache.Midia(chave, raiz_do_cache=raiz, tipo=tipo)
    if m.existe and (not origem or m.origem == _cache.origem_valida(origem)):
        return Achado(m, "chave", m.chave, tipo)
    if not medir:
        return Achado(None, "nada", chave, tipo)

    # ⭐ "Já medi e não é nada que está aqui" também é resposta, e ela fica guardada. Sem
    #   isto, TODA chamada (ver_frames, transcrever, resolver_item…) sobre um clipe sem par
    #   no cache decodificava de novo um minuto de vídeo dos dois lados — para sempre.
    #   ⚠️ O veredito vale enquanto o cache não mudar: mídia nova pode ser o par que faltava.
    tamanho_do_cache = _quantas_midias(raiz)
    if _registro.ler(arquivo, "sem_par") == tamanho_do_cache:
        return Achado(None, "nada", chave, tipo)

    try:
        alvo = sondar(arquivo)
    except IdentidadeErro as e:
        return Achado(None, "nada", chave, tipo, avisos=[str(e)])

    avisos: list[str] = []
    # ⭐ A passada barata (nome da bin) primeiro; só quando ela não acha NADA vale sondar o
    #   cache atrás do nome que está DENTRO do arquivo (`ampliar`) — ver `candidatos`. A
    #   alternativa, neste ponto exato, é reprocessar uma mídia que já está pronta.
    achados = candidatos(alvo, raiz) or candidatos(alvo, raiz, ampliar=True)
    for cand, arquivos in achados:
        if relatar:
            relatar(f"conferindo se {arquivo.name} é {cand.nome}")
        medida, piso, fonte = _conferir(arquivo, alvo, arquivos)
        if medida >= piso:
            # ⛔⛔ **Entre BANCOS não se apelida** (decisão do editor, 2026-09-21). Apelido
            #    faz as duas mídias virarem UMA — e aí o `.mp4` do Premiere passa a
            #    responder pela entrada do Avid, com o nome da bin dele e os caminhos de
            #    `Avid MediaFiles` dentro. O casamento continua valendo; o que muda é a
            #    CONSEQUÊNCIA: quem cruza bancos é `aproveitar()`, que cria entrada própria
            #    e COPIA o trabalho.
            de_outro_banco = bool(origem) and cand.origem != _cache.origem_valida(origem)
            if not de_outro_banco:
                cand.apelidar(chave, tipo, arquivo=str(arquivo), fonte=fonte,
                              confianca="confirmado", medida=round(medida, 4))
            return Achado(cand, "outro_banco" if de_outro_banco else "convertido",
                          cand.chave, tipo, medida=medida)
        avisos.append(
            f"{cand.nome} tem o mesmo nome e duração, mas "
            + (f"não consegui comparar o conteúdo; tratado como outra mídia"
               if medida <= NAO_COMPAREI
               else f"o conteúdo não bate ({medida:.2f}); tratado como outra mídia"))
    _registro.guardar(arquivo, "sem_par", tamanho_do_cache)
    return Achado(None, "nada", chave, tipo, avisos=avisos)


# ── o cruzamento entre bancos: só ao PROCESSAR ───────────────────────────────


@dataclass
class Aproveitamento:
    """O que o cruzamento produziu: a entrada DESTE banco, e de quem ela aproveitou."""

    midia: _cache.Midia
    #: A entrada de outro editor que casou, ou `None` — e aí é processar do zero mesmo.
    de: _cache.Midia | None = None
    medida: float = 0.0
    fonte: str = ""
    copiados: list[str] = field(default_factory=list)
    avisos: list[str] = field(default_factory=list)

    @property
    def aproveitou(self) -> bool:
        return bool(self.copiados)

    def como_dicionario(self) -> dict[str, Any]:
        return {
            "chave": self.midia.chave,
            "origem": self.midia.origem,
            "aproveitou": self.aproveitou,
            "de": self.de.nome if self.de is not None else "",
            "copiados": list(self.copiados),
            # Procedência em todo item, como manda a casa.
            "confianca": "confirmado" if self.medida else "inferido",
            "fonte": self.fonte or "conteudo",
            "medida": round(self.medida, 4) if self.medida else "",
        }


def aproveitar(arquivo: str | Path, origem: str, rotulo: dict[str, Any] | None = None,
               raiz: Path | None = None,
               relatar: Callable[[str], None] | None = None) -> Aproveitamento:
    """A entrada DESTE banco para `arquivo` — aproveitando o que outro editor já fez.

    ⭐⭐ **É aqui, e só aqui, que os bancos se cruzam** (decisão do editor, 2026-09-21):

        *"Quando eu importo uma mídia no Premiere e peço para processar, é aí que o
        cruzamento acontece. Se houver match, a nova entrada não vai processar os
        arquivos: vai copiar as informações do que já existe."*

    ⛔ O banco do Premiere **nunca pré-carrega** o cache do Avid. A busca de um editor
    nunca mostra material do outro, nem o nome dele, nem um caminho de `Avid MediaFiles`.
    O que atravessa é o TRABALHO, uma vez, no momento de processar.

    ⭐ A prova de que é a mesma mídia é a que já existia e já foi medida: candidato por
    nome + taxa + nº de quadros + TC, decisão por CONTEÚDO — 5 quadros exatos 32×32 em
    correlação de Pearson (⭐ indiferente a nível e ganho, que é boa parte do que um LUT
    faz), ou o som canal a canal. ⚠️ **Burn-in não foi medido**: uma tarja ocupa região e
    pode derrubar a correlação abaixo do piso. Se derrubar, o material é reprocessado —
    que é a falha segura.

    ⚠️ Nunca levanta por causa do cruzamento: não achar par é resposta normal, e significa
    "processe do zero".
    """
    arquivo = Path(arquivo)
    origem = _cache.origem_valida(origem)
    rotulo = dict(rotulo or {})
    rotulo.setdefault("nome", arquivo.stem)
    rotulo.setdefault("arquivos", [str(arquivo)])
    # ⭐ A pasta do cache tem NOME DE GENTE (spec `2026-09-13-cache-legivel-e-compartilhado`),
    #   e o nome sai do rótulo: sem taxa, tipo e duração ele degrada para
    #   `NOME_data_hash`, que é justamente o que a spec veio consertar.
    try:
        sonda = sondar(arquivo)
        rotulo.setdefault("tipo", sonda.get("tipo") or "")
        rotulo.setdefault("duracao_s", sonda.get("duracao_s") or 0)
        if sonda.get("fps"):
            rotulo.setdefault("fps", sonda["fps"])
    except IdentidadeErro:
        pass

    chave, tipo = chave_do_arquivo(arquivo)
    minha = _cache.Midia(chave, raiz_do_cache=raiz, tipo=tipo, origem=origem, rotulo=rotulo)
    # ⛔ Uma entrada de OUTRO banco que responda por esta chave (apelido antigo) não é a
    #   minha: o `separar_bancos.py` limpa esses, e aqui a gente não se deixa enganar.
    if minha.existe and minha.origem == origem:
        return Aproveitamento(midia=minha)

    achado = achar(arquivo, raiz=raiz, relatar=relatar, origem=origem)
    if achado.midia is None or achado.como not in ("convertido", "outro_banco"):
        # Sem par: a entrada nasce vazia e quem chamou processa.
        return Aproveitamento(midia=_nascida(chave, tipo, origem, rotulo, raiz),
                              avisos=list(achado.avisos))
    if achado.como == "convertido":
        # Mesmo banco: o apelido já resolveu, e a entrada é aquela mesma.
        return Aproveitamento(midia=achado.midia, medida=achado.medida or 0.0)

    par = achado.midia
    minha = _nascida(chave, tipo, origem, rotulo, raiz)
    fonte = "sonora" if sondar(arquivo).get("tipo") != "video" else "visual"
    copiados = minha.copiar_de(par, medida=achado.medida or 0.0, fonte=fonte)
    if copiados and relatar:
        relatar(f"aproveitei {', '.join(copiados)} de material já analisado")
    log.info("banco %s: %s aproveitou %s de %s (medida %.4f)", origem, arquivo.name,
             copiados or "nada", par.nome, achado.medida or 0.0)
    return Aproveitamento(midia=minha, de=par, medida=achado.medida or 0.0,
                          fonte=fonte, copiados=copiados, avisos=list(achado.avisos))


def _nascida(chave: str, tipo: str, origem: str, rotulo: dict[str, Any],
             raiz: Path | None) -> _cache.Midia:
    """A entrada deste banco, criada se preciso. ⚠️ `pasta` é o que faz nascer."""
    m = _cache.Midia(chave, raiz_do_cache=raiz, tipo=tipo, origem=origem, rotulo=rotulo)
    m.pasta  # noqa: B018 — nascer é escrever
    return m
