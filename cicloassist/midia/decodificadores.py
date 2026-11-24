"""RAW de câmera: o que o ffmpeg NÃO decodifica, e quem decodifica no lugar dele.

BRAW, R3D, ARRIRAW, Canon Cinema RAW Light e Sony X-OCN não abrem no ffmpeg. Quem abre é o
SDK do fabricante, e ele entra aqui como um **binário externo opcional**, com o contrato
do RELINKER (`docs/raw-decoders.md` de lá) — de propósito, para que um helper construído
lá sirva aqui:

    ciclo-decodificar-<tipo> --file <X> --frame <N> --out <out.jpg> [--max-width <W>]
        exit 0 → gravou out.jpg          exit ≠0 → motivo no stderr

⛔ **Binário externo, e não um binding.** Licença isolada (nada do fabricante entra no
nosso pacote), um decode que quebra não derruba o serviço — e o serviço é o painel do
editor —, e o build fica num lugar só, por plataforma.

⭐⭐ **A ausência degrada com elegância.** Sem o helper, `SdkIndisponivel` diz o nome do
SDK e o endereço para baixar; tudo o mais do produto segue funcionando, inclusive achar,
transcrever e casar aquele mesmo material. ⚠️ Nunca uma exceção crua: "não consegui
extrair o quadro" manda o editor procurar defeito onde não há.

## ⭐⭐ Antes de pedir SDK, pergunte se há o que reaproveitar

Um BRAW quase sempre é o ORIGINAL de algo que a produção já converteu para editar — e
`midia/identidade.py` casa os dois **pelo som** (medido: 5 de 5, +1,000 contra +0,033 do
impostor). Quando casa, os quadros já estão no cache e nada disto é chamado. Este módulo é
para o RAW que **nunca** foi convertido.

## O estado de cada tipo

| tipo | helper | estado |
|---|---|---|
| **BRAW** | `ciclo-decodificar-braw` | ✅ construído e medido no Windows (2026-09-21) |
| R3D, ARRIRAW, Canon, Sony | — | ⬜ o contrato está de pé; falta construir |

⚠️ **O SDK é preciso no BUILD; o usuário só precisa do RUNTIME** — e o helper acha o
runtime onde ele já estiver na máquina (ver `decodificadores/braw/decodificar_braw.cpp`).
⭐ No Windows do Media Composer ele costuma JÁ estar lá: o plugin AMA de BRAW do próprio
Avid instala o `BlackmagicRawAPI.dll`.
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

log = logging.getLogger("cicloassist.midia.decodificadores")

#: Extensão → tipo de SDK. ⚠️ Sony X-OCN vem em `.mxf` e só se descobre pela ESSÊNCIA
#: (`codec_name == "unknown"` com `width == 0`, banco `protocolos/mxf/codecs-proprietarios.md`)
#: — por isso não está aqui: entra quando houver helper para ele.
TIPOS = {
    ".braw": "braw",
    ".r3d": "r3d",
    ".ari": "arri", ".arx": "arri", ".arriraw": "arri",
    ".crm": "canon", ".rmf": "canon",
}

NOMES = {
    "braw": "Blackmagic RAW",
    "r3d": "RED (R3D)",
    "arri": "ARRI (ARRIRAW)",
    "canon": "Canon Cinema RAW Light",
    "sony": "Sony X-OCN",
}

ENDERECOS = {
    "braw": "https://www.blackmagicdesign.com/support/family/blackmagic-raw",
    "r3d": "https://www.red.com/download/r3d-sdk",
    "arri": "https://www.arri.com/en/learn-help/learn-help-camera-system/pre-postproduction/"
            "file-formats-data-handling/arriraw",
    "canon": "https://www.usa.canon.com/support/software-and-drivers",
    "sony": "https://www.sony.net/Products/RAWViewer/",
}

PROGRAMAS = {tipo: f"ciclo-decodificar-{tipo}" for tipo in NOMES}

#: ⚠️ Generoso: o primeiro quadro de um clipe grande paga a abertura do SDK. Medido no
#: BRAW 4K desta máquina: 0,13–0,18 s por quadro depois de aberto.
PRAZO_S = 180


class SdkIndisponivel(RuntimeError):
    """Este formato precisa do SDK do fabricante, e o decodificador não está instalado."""

    def __init__(self, tipo: str) -> None:
        self.tipo = tipo
        self.nome = NOMES.get(tipo, tipo)
        self.endereco = ENDERECOS.get(tipo, "")
        super().__init__(
            f"{self.nome} não abre no ffmpeg: ele precisa do decodificador próprio, que "
            f"não está instalado nesta máquina."
            + (f" Baixe o SDK em {self.endereco} e rode "
               f"decodificadores\\{tipo}\\construir.ps1." if self.endereco else "")
        )


class DecodificacaoFalhou(RuntimeError):
    """O decodificador rodou e não produziu quadro."""


def tipo_de(arquivo: Path | str) -> str:
    """Que SDK este arquivo exige, ou "" quando o ffmpeg dá conta."""
    return TIPOS.get(Path(arquivo).suffix.lower(), "")


def _pastas() -> list[Path]:
    """Onde procurar o binário, da mais específica para a mais geral."""
    pastas = []
    if getattr(sys, "frozen", False):
        # Empacotado: ao lado do executável do serviço.
        pastas.append(Path(sys.executable).resolve().parent)
    raiz = Path(__file__).resolve().parents[2]
    pastas.append(raiz / "decodificadores" / "bin")
    return pastas


def caminho_do_programa(tipo: str) -> str:
    """O binário deste tipo, se estiver instalado. Senão "" — nunca uma exceção."""
    nome = PROGRAMAS.get(tipo)
    if not nome:
        return ""
    for pasta in _pastas():
        alvo = pasta / f"{nome}.exe"
        if sys.platform == "win32" and alvo.is_file():  # o .exe do SSD não executa no Mac
            return str(alvo)
        alvo = pasta / nome
        if alvo.is_file() and os.access(alvo, os.X_OK):
            return str(alvo)
    return shutil.which(nome) or ""


def temos(tipo: str) -> bool:
    return bool(caminho_do_programa(tipo))


def situacao() -> dict[str, dict]:
    """O que existe e o que falta — para a tela e para o diagnóstico."""
    return {t: {"nome": NOMES[t], "temos": temos(t), "endereco": ENDERECOS.get(t, "")}
            for t in PROGRAMAS}


def decodificar(arquivo: Path | str, frame: int, largura: int,
                tipo: str = "") -> bytes:
    """O quadro `frame` (índice 0-based NO ARQUIVO) em JPEG, pelo SDK do fabricante.

    ⚠️ **O índice é do arquivo, não do master.** Para o RAW de câmera os dois são o mesmo
    — o arquivo É o master —, e é exatamente por isso que a conversão de tempo fica em
    `frames.py` e não aqui.
    """
    tipo = tipo or tipo_de(arquivo)
    if not tipo:
        raise DecodificacaoFalhou(f"{Path(arquivo).name} não é RAW de câmera conhecido")
    programa = caminho_do_programa(tipo)
    if not programa:
        raise SdkIndisponivel(tipo)

    # ⚠️ Arquivo temporário porque o contrato do helper é gravar um JPEG — e é o contrato
    #   do RELINKER, que não vamos divergir por conveniência nossa. O custo é um arquivo
    #   de ~40 KB que morre no fim da chamada.
    with tempfile.TemporaryDirectory(prefix="ciclo-raw-") as pasta:
        saida = Path(pasta) / "quadro.jpg"
        comando = [programa, "--file", str(arquivo), "--frame", str(int(frame)),
                   "--out", str(saida), "--max-width", str(int(largura))]
        try:
            r = subprocess.run(comando, capture_output=True, timeout=PRAZO_S,
                               # ⚠️ Sem isto o Windows abre um console por quadro (a mesma
                               #   razão do `acervo._sondar`) — e a fila extrai aos lotes.
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as e:
            raise DecodificacaoFalhou(
                f"não consegui rodar o decodificador de {NOMES[tipo]} ({e})") from e
        except subprocess.TimeoutExpired as e:
            raise DecodificacaoFalhou(
                f"o decodificador de {NOMES[tipo]} não respondeu em {PRAZO_S}s") from e

        erro = (r.stderr or b"").decode("utf-8", "replace").strip()
        if erro:
            # ⭐ O helper usa o stderr para AVISO também (a gamma que não pôde ser
            #   aplicada). Aviso não é falha: vai para o log, não para a exceção.
            log.info("decodificador de %s: %s", tipo, erro[:300])
        if r.returncode != 0 or not saida.is_file():
            raise DecodificacaoFalhou(
                f"não consegui extrair o quadro {frame} de {Path(arquivo).name}"
                + (f": {erro[:300]}" if erro else ""))
        return saida.read_bytes()
