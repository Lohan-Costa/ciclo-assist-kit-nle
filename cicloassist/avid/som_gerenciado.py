"""Som direto (WAV do gravador) → MXF OP-Atom GERENCIADO no Media Composer, sem consolidar: as operações 6 e 7 em uma.

Ideia do autor (2026-11-01): *"se conseguirmos gerar mxf op-atom a partir dos wav's, não precisamos passar pela etapa
de consolidação de áudios e conseguimos ser mais precisos"*. MEDIDO no mesmo dia (banco, `protocolos/mxf/README.md`):
o OP-Atom de áudio do ffmpeg + a costura do laboratório entram no MC 2024.6 como mídia gerenciada e TOCAM.

O caminho, por WAV:
1. um OP-Atom por CANAL (`ffmpeg -af pan=mono|c0=cN -c:a pcm_s24le -f mxf_opatom`), na edit rate do PROJETO e com o
   TC lido do bext (`time_reference`) — o mesmo instante que o gravador escreveu;
2. a costura (`midia/opatom_costura.py`, cópia do laboratório): uma identidade de clipe para os canais e o
   MaterialPackage com TODAS as trilhas — sem ela, cada canal seria um clipe;
3. tudo numa pasta NOVA de `Avid MediaFiles\\MXF`, só dígitos, terminando em **1** (o áudio, convenção do autor);
4. a importação de masters (`avid/importar_opatom.py`, a op. 5 provada), com a FITA criada no AAF (o ffmpeg não grava
   pacote de fita; sem ela o Tape saía vazio) e a conferência de online pela API.

⭐⭐ E os metadados do BWF vão COMO O MC FAZ ao linkar (decisão do autor, 2026-11-01): o master se chama `CENA/TAKE`
quando o gravador escreveu cena e take (bext ou iXML), e as colunas da bin recebem Scene, Take, TapeID, Shoot Date,
TRKn, Production e Circled; sem cena, o nome do arquivo COM a extensão. A leitura é a do De Lá Pra Cá
(`midia/bwf.py`, 14/14 contra o MC), aplicada na bin depois da importação (`importar_opatom.aplicar_metadados`). Os
MXF continuam com o nome do arquivo: a barra de `CENA/TAKE` não pode ir para um nome de arquivo.
⛔ Drop-frame (29,97/59,94 DF) não foi medido aqui: recusado, em vez de errar o TC calado.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import tempfile
from fractions import Fraction
from pathlib import Path
from typing import Callable

from ..midia import bwf as _bwf
from ..midia import opatom_costura as _costura
from . import importar_opatom as _imp
from .som_direto import audios_da_pasta


class SomGerenciadoFalhou(RuntimeError):
    """A frase vai ao modelo como está."""


def _ffprobe() -> str:
    from ..binarios import achar
    return achar("ffprobe") or "ffprobe"


def _ffmpeg() -> str:
    from ..binarios import achar
    return achar("ffmpeg") or "ffmpeg"


def ler_wav(caminho: Path) -> dict:
    """{canais, taxa, amostra_inicial} — o `time_reference` do bext é a amostra do TC de início."""
    p = subprocess.run([_ffprobe(), "-v", "error", "-show_entries",
                        "stream=channels,sample_rate:format_tags=time_reference", "-of", "json", str(caminho)],
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=30)
    d = json.loads(p.stdout or "{}")
    s = (d.get("streams") or [{}])[0]
    if not s.get("channels"):
        raise SomGerenciadoFalhou(f"não consegui ler o áudio de {caminho.name}")
    return {"canais": int(s["channels"]), "taxa": int(s.get("sample_rate") or 48000),
            "amostra_inicial": int(((d.get("format") or {}).get("tags") or {}).get("time_reference") or 0)}


def tc_de(amostras: int, taxa: int, fps: Fraction) -> tuple[int, str]:
    """(quadros, "HH:MM:SS:FF") do instante, na base inteira do projeto (25, 24…; 23,976 conta em 24)."""
    base = round(fps)
    quadros = round(amostras * base / taxa)
    return quadros, "%02d:%02d:%02d:%02d" % (quadros // (3600 * base), quadros // (60 * base) % 60,
                                             quadros // base % 60, quadros % base)


def pasta_nova_de_audio(mxf: Path, hoje: datetime.date | None = None) -> Path:
    """AAAAMMDD + (vazio, 1, 2…) + "1": só dígitos e terminando em 1 (o áudio, convenção do autor)."""
    base = (hoje or datetime.date.today()).strftime("%Y%m%d")
    for k in ["", *map(str, range(1, 100))]:
        p = mxf / f"{base}{k}1"
        if not p.exists():
            return p
    raise SomGerenciadoFalhou(f"não achei pasta livre em {mxf} para hoje")


def gerar(wav: Path, destino: Path, fps: Fraction) -> tuple[str, int]:
    """Os OP-Atom de um WAV (um por canal, costurados) em `destino`. Devolve (nome do clipe, quadros do TC)."""
    info = ler_wav(wav)
    quadros, tc = tc_de(info["amostra_inicial"], info["taxa"], fps)
    nome = wav.stem
    tmp = Path(tempfile.mkdtemp(prefix="ciclo_som_"))
    try:
        arquivos = []
        for c in range(info["canais"]):
            out = tmp / f"{nome}_A{c + 1:02d}.mxf"
            r = subprocess.run([_ffmpeg(), "-v", "error", "-y", "-i", str(wav), "-af", f"pan=mono|c0=c{c}",
                                "-c:a", "pcm_s24le", "-f", "mxf_opatom",
                                "-mxf_audio_edit_rate", f"{fps.numerator}/{fps.denominator}", "-timecode", tc,
                                "-metadata", f"material_package_name={nome}", str(out)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               stdin=subprocess.DEVNULL, timeout=600)
            if r.returncode != 0 or not out.is_file():
                raise SomGerenciadoFalhou(f"o ffmpeg não gravou {out.name}: {(r.stderr or '').strip()[-300:]}")
            arquivos.append(str(out))
        _costura.costurar(arquivos, [str(destino / Path(a).name) for a in arquivos], nome)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return nome, quadros


def montar(m, pasta: str | Path, bin_nome: str, mxf: Path, *,
           relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """`m` é a ponte (`mcapi.MediaComposer`, aberta); `mxf` é a `Avid MediaFiles\\MXF` de destino."""
    relatar = relatar or (lambda *_: None)
    audios = audios_da_pasta(pasta)
    if not audios:
        raise SomGerenciadoFalhou(f"não há áudio (.wav/.aif) em {pasta}")
    projeto = m.projeto(recarregar=True)
    if projeto.get("drop_frame"):
        raise SomGerenciadoFalhou("o projeto é drop-frame (29,97/59,94 DF): o TC do som ainda não foi medido "
                                  "nesse caso aqui — use montar_som_direto e consolide")
    fps = Fraction(int(projeto["fps"]["num"]), int(projeto["fps"]["den"] or 1))
    destino = pasta_nova_de_audio(mxf)
    destino.mkdir(parents=True)
    inicios: dict[str, tuple[int, Fraction]] = {}
    metadados: dict[str, dict] = {}
    for i, w in enumerate(audios):
        relatar("gerando o MXF do som direto", i / len(audios), w.name)
        nome, quadros = gerar(w, destino, fps)
        inicios[nome] = (quadros, fps)
        try:
            meta = _bwf.como_o_avid(str(w))
        except Exception:  # noqa: BLE001 — metadado é acessório: o master fica com o nome do arquivo
            meta = None
        if meta:
            metadados[nome] = meta
    r = _imp.importar(m, destino, bin_nome, inicios=inicios, metadados=metadados, relatar=relatar)
    return {**r, "wavs": len(audios), "fps": float(fps)}
