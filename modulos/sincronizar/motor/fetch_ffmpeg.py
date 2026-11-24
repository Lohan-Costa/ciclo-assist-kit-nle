#!/usr/bin/env python3
"""
fetch_ffmpeg.py — baixa ffmpeg + ffprobe estáticos para src-tauri/binaries/.

POR QUE EXISTE: o app EMBARCA o ffmpeg/ffprobe (externalBin do Tauri) — o usuário
NÃO pode precisar instalar nada (o sync morria com `[Errno 2] ... 'ffmpeg'`).
`src-tauri/binaries/` é gitignored, então os binários nunca vêm do repo: o CI
(.github/workflows/release.yml) e os `setup.*` chamam este script. O Tauri exige
os arquivos `binaries/<nome>-<triple>[.exe]` em tempo de BUILD — sem eles o build
falha com "resource path ... doesn't exist" —, então rodar isto é pré-requisito de
QUALQUER build (dev inclusive), o mesmo padrão do `build_sidecar.py`.

Uma implementação só (Python, já é dependência de build) reusada pelos três — em
vez de duplicar download frágil em bash/pwsh/batch.

FONTES — VENDORIZADAS: os binários vêm de um release nosso no PRÓPRIO repo público
(`Lohan-Costa/orbita`, tag `vendor-ffmpeg-8.1.2`), re-hospedados UMA vez a partir do
upstream. Assim o build não depende da disponibilidade de terceiros nem de tags que
rolam/são podadas (o BtbN, por exemplo, apaga autobuilds antigos). São builds GPL
LIMPOS (`--enable-gpl` SEM `--enable-nonfree`, redistribuíveis; com libx264, que o
proxy de vídeo futuro vai precisar), verificados por `ffmpeg -version`. Origem:
  - macOS arm64: martin-riedl.de 8.1.2 (zips separados por ferramenta).
  - Windows x64: BtbN autobuild-2026-07-21-13-38, n8.1.2 win64-gpl (um zip com os
    dois .exe). Ambos os SOs em ffmpeg 8.1.2.
Para ATUALIZAR: baixar do upstream, conferir `ffmpeg -version | grep nonfree`,
subir num release vendor NOVO e bumpar `VENDOR` abaixo.

Uso: python fetch_ffmpeg.py <rust-target-triple>
Idempotente: se os dois binários do alvo já existem, não baixa nada.
"""

from __future__ import annotations

import hashlib
import io
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

BIN_DIR = Path(__file__).resolve().parent.parent / "src-tauri" / "binaries"

# Release de VENDOR no nosso repo público (imutável, sob nosso controle).
VENDOR = "https://github.com/Lohan-Costa/orbita/releases/download/vendor-ffmpeg-8.1.2"
WIN_ZIP = f"{VENDOR}/ffmpeg-win64-gpl.zip"          # um zip com ffmpeg.exe + ffprobe.exe
MAC_FFMPEG_ZIP = f"{VENDOR}/ffmpeg-macos-arm64.zip"  # zips separados por ferramenta
MAC_FFPROBE_ZIP = f"{VENDOR}/ffprobe-macos-arm64.zip"

# ⭐ SHA-256 DE CADA ZIP — a tranca da cadeia de suprimentos.
#
# POR QUE ISTO É NECESSÁRIO MESMO COM HTTPS: o modelo de ameaça aqui não é
# interceptação de rede (o TLS cobre isso). É o asset TROCADO NA ORIGEM. Um release
# do GitHub é MUTÁVEL: quem tiver a conta do mantenedor — ou o próprio GitHub, se
# comprometido — substitui `ffmpeg-macos-arm64.zip` sem que a URL mude, e o próximo
# build de release assa um ffmpeg trojanizado dentro do `.dmg`/`.exe` que os usuários
# baixam. Sem checksum, nada detecta: é o padrão xz-utils em miniatura, e o raio de
# alcance é toda a base instalada.
#
# Estes hashes são código VERSIONADO: trocar um deles aparece no diff e passa por
# revisão, que é exatamente a propriedade que falta a um download silencioso.
#
# AO ATUALIZAR o ffmpeg: suba o release vendor novo, rode
#   shasum -a 256 <zip>
# em cada arquivo e cole aqui, no mesmo commit que bumpa o `VENDOR`.
SHA256 = {
    # ⚠️⚠️ HASHES REGERADOS EM 2026-08-24, e a PROCEDÊNCIA MUDOU — leia antes de confiar.
    #
    # O release `vendor-ffmpeg-8.1.2` foi apagado por engano numa purga de tags do
    # repositório público (a purga era legítima; este alvo não era release do produto,
    # era INFRAESTRUTURA DE BUILD, e passou junto). O upstream do Windows não podia
    # mais ser rebaixado: o autobuild da BtbN devolve 404 — exatamente o motivo pelo
    # qual estes binários foram vendorizados um dia.
    #
    # ⭐ O que se recuperou: os binários JÁ EXTRAÍDOS na máquina de desenvolvimento,
    # que são os mesmos que a v0.3.0 e a v0.3.1 embarcaram. O do Windows foi
    # verificado: `n8.1.2-29-g703dcc25b9-20260721`, `--enable-gpl --enable-version3`,
    # **zero ocorrências de `nonfree`** — bate com a origem documentada acima.
    #
    # ⛔ O QUE SE PERDEU, e é o que precisa ficar escrito: os hashes abaixo atestam
    # zips que ESTA MÁQUINA montou, não os artefatos que o upstream publicou. A
    # tranca continua detectando adulteração DAQUI PARA A FRENTE, mas a cadeia até o
    # upstream está cortada. *Um hash prova que nada mudou desde que você o anotou —
    # não prova de onde veio o que você anotou.*
    #
    # PARA RESTAURAR A CADEIA: baixar um build novo do upstream, conferir
    # `ffmpeg -version | grep nonfree`, subir num release vendor NOVO e bumpar
    # `VENDOR`. Isso troca o ffmpeg embarcado, então pede teste — não é conserto de
    # emergência, é manutenção a fazer com calma.
    WIN_ZIP:         "0d5dd2a2c87c57c8578593aaedcaaea8397989e2cb1606b843c5c988a290a651",
    MAC_FFMPEG_ZIP:  "67e5309940f435289e9fc597c097cfa09249813fe07461445305aaff2f4bd2b6",
    MAC_FFPROBE_ZIP: "43a8d0f48b6ab30cc3e0edf5e7b4c537c605017f33338077f0e49547e513fd55",
}


def _download(url: str) -> bytes:
    # A checagem vem ANTES da rede: uma URL sem hash registrado é uma URL que ninguém
    # revisou, e nem chegamos a falar com ela. Falha FECHADO.
    esperado = SHA256.get(url)
    if not esperado:
        print(f"[ERRO] sem SHA-256 registrado para {url}", file=sys.stderr)
        sys.exit(1)

    print(f"      baixando {url}", flush=True)
    req = urllib.request.Request(url, headers={"User-Agent": "sincronizar-fetch-ffmpeg"})
    with urllib.request.urlopen(req) as r:
        data = r.read()

    digest = hashlib.sha256(data).hexdigest()
    if digest != esperado:
        print(
            "[ERRO] O ARQUIVO BAIXADO NÃO É O ESPERADO — build abortado.\n"
            f"       url:      {url}\n"
            f"       esperado: {esperado}\n"
            f"       recebido: {digest}\n"
            "       Isto significa que o conteúdo no servidor MUDOU. Ou o release\n"
            "       vendor foi atualizado sem atualizar este script (então confira\n"
            "       o binário à mão e atualize o hash), ou alguém trocou o asset.\n"
            "       Não instale nada até saber qual dos dois é.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"      sha256 confere ({digest[:16]}…)", flush=True)
    return data


def _binary_from_zip(zip_bytes: bytes, tool: str) -> bytes:
    """Extrai o binário `tool` (ffmpeg/ffprobe) de um zip, ache ele numa subpasta
    ou não. Se o zip tiver um único arquivo, é ele."""
    with zipfile.ZipFile(io.BytesIO(zip_bytes)) as z:
        wanted = {tool, tool + ".exe"}
        for n in z.namelist():
            if Path(n).name in wanted:
                return z.read(n)
        files = [n for n in z.namelist() if not n.endswith("/")]
        if len(files) == 1:
            return z.read(files[0])
        raise RuntimeError(f"não achei '{tool}' no zip (entradas: {z.namelist()})")


def _write(path: Path, data: bytes, executable: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    if executable:
        path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def fetch(triple: str) -> None:
    win = triple.endswith("windows-msvc")
    ext = ".exe" if win else ""
    ff = BIN_DIR / f"ffmpeg-{triple}{ext}"
    fp = BIN_DIR / f"ffprobe-{triple}{ext}"

    if ff.exists() and fp.exists():
        print(f"      ffmpeg/ffprobe para {triple} já presentes. Ok.")
        return

    if win:
        zip_bytes = _download(WIN_ZIP)
        _write(ff, _binary_from_zip(zip_bytes, "ffmpeg"), executable=False)
        _write(fp, _binary_from_zip(zip_bytes, "ffprobe"), executable=False)
    elif triple == "aarch64-apple-darwin":
        _write(ff, _binary_from_zip(_download(MAC_FFMPEG_ZIP), "ffmpeg"), executable=True)
        _write(fp, _binary_from_zip(_download(MAC_FFPROBE_ZIP), "ffprobe"), executable=True)
    else:
        print(f"[ERRO] alvo sem fonte de ffmpeg mapeada: {triple}", file=sys.stderr)
        sys.exit(1)

    print(f"      ffmpeg/ffprobe para {triple} prontos.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("uso: python fetch_ffmpeg.py <rust-target-triple>", file=sys.stderr)
        sys.exit(2)
    fetch(sys.argv[1])
