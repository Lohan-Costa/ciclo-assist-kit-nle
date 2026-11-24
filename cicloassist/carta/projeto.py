"""O projeto da Carta Aberta: a raiz que o editor escolheu, a pasta `.carta/` e a quarentena.

⛔ O programa não cria pasta nenhuma sozinho (decisão do autor, plano §1.10): "novo projeto" recebe uma raiz que o
editor escolheu e só acrescenta a `.carta/` dentro dela. As pastas de dentro são do editor.
⛔ Na raiz só moram arquivos nossos; o resto vai para a `Quarentena/<data>/<de onde veio>` (plano §4.1). Nada é
apagado. Sombras e arquivos do sistema são só ignorados; o temporário de OUTRA máquina escrevendo agora (`*.parcial`)
só vai para a quarentena parado há mais de um dia.
"""

from __future__ import annotations

import datetime
import getpass
import json
import os
import re
import shutil
import socket
import time
from dataclasses import dataclass
from pathlib import Path

PASTA_INTERNA = ".carta"
QUARENTENA = "Quarentena"
#: dentro da `.carta/`: o que foi REMOVIDO da vista (ou entrou só porque um item o usa) — o fecho oculto da bin do Avid
OCULTAS = "ocultas"
FORMATO = "projeto/1"
#: os arquivos NOSSOS que podem morar nas pastas do editor
SUFIXOS_NOSSOS = (".ref.json", ".item.json", ".carta.json")
#: o sistema recria sozinho a cada gravação: ignorar, nunca pôr na quarentena
DO_SISTEMA = {".DS_Store", "Thumbs.db", "desktop.ini", "Icon\r"}
PARCIAL = ".parcial"
PARCIAL_VELHO_S = 24 * 3600


class CartaErro(Exception):
    """O pedido não cabe num projeto da Carta Aberta — a mensagem diz o porquê ao editor."""


def maquina() -> str:
    """`USUARIO-MAQUINA`, só letras, números e hífen: o nome do diário desta máquina (um arquivo por máquina e
    usuário, plano §4.5). O nome do computador sem `.local` (macOS) nem domínio."""
    host = socket.gethostname().split(".")[0]
    try:
        usuario = getpass.getuser()
    except Exception:  # noqa: BLE001 — sem usuário legível, a máquina basta
        usuario = "editor"
    return re.sub(r"[^A-Za-z0-9]+", "-", f"{usuario}-{host}").strip("-").upper() or "MAQUINA"


@dataclass(frozen=True)
class Projeto:
    raiz: Path
    nome: str
    taxa: str
    nasceu: str

    @property
    def interna(self) -> Path:
        return self.raiz / PASTA_INTERNA

    @property
    def registro(self) -> Path:
        return self.interna / "registro"

    @property
    def ocultas(self) -> Path:
        """⭐ A régua é a bin do Avid (autor, 2026-11-13): o que a lista mostra é a vitrine; por baixo, o projeto carrega
        OCULTO o que os itens precisam. Remover leva para cá (nada do disco é tocado); mover ou mandar de novo traz de
        volta. Fora das pastas do editor de propósito: uma pasta esvaziada pode sair sem levar o que outro item usa."""
        return self.interna / OCULTAS


def gravar_json(destino: Path, dados: dict) -> None:
    """Grava ao lado (`.parcial`) e troca: quem lê nunca vê meio arquivo, nem por SMB."""
    tmp = destino.with_name(destino.name + PARCIAL)
    tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, destino)


def novo(raiz: str | Path, nome: str, taxa: str) -> Projeto:
    """Faz da pasta `raiz` (que o editor escolheu e que já existe) um projeto da Carta Aberta."""
    raiz = Path(raiz)
    if not raiz.is_dir():
        raise CartaErro(f"a pasta {raiz} não existe — escolha uma pasta que já exista para ser a raiz do projeto")
    if (raiz / PASTA_INTERNA / "projeto.json").exists():
        raise CartaErro(f"{raiz} já é um projeto da Carta Aberta — use Abrir projeto")
    if not nome.strip():
        raise CartaErro("o projeto precisa de um nome")
    (raiz / PASTA_INTERNA / "registro").mkdir(parents=True, exist_ok=True)
    dados = {"carta_aberta": FORMATO, "nome": nome.strip(), "taxa": taxa,
             "nasceu": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "por": maquina()}
    gravar_json(raiz / PASTA_INTERNA / "projeto.json", dados)
    return abrir(raiz)


def abrir(raiz: str | Path) -> Projeto:
    raiz = Path(raiz)
    arq = raiz / PASTA_INTERNA / "projeto.json"
    try:
        d = json.loads(arq.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CartaErro(f"{raiz} não é um projeto da Carta Aberta (falta {PASTA_INTERNA}/projeto.json)") from None
    except (OSError, json.JSONDecodeError) as e:
        raise CartaErro(f"não consegui ler {arq}: {e}") from e
    if d.get("carta_aberta") != FORMATO:
        raise CartaErro(f"{arq} é de uma versão que este programa não conhece ({d.get('carta_aberta')!r})")
    (raiz / PASTA_INTERNA / "registro").mkdir(parents=True, exist_ok=True)
    return Projeto(raiz=raiz, nome=d["nome"], taxa=d.get("taxa", ""), nasceu=d.get("nasceu", ""))


def _ignorado(p: Path) -> bool:
    return p.name in DO_SISTEMA or p.name.startswith("._")


def e_nosso(p: Path) -> bool:
    return p.name.endswith(SUFIXOS_NOSSOS)


def arquivos_ocultos(proj: Projeto):
    """Os `.ref.json`/`.item.json` da área escondida (`proj.ocultas`)."""
    try:
        for p in sorted(proj.ocultas.iterdir()):
            if p.is_file() and not _ignorado(p) and e_nosso(p):
                yield p
    except OSError:
        return


def arquivos_do_editor(proj: Projeto):
    """Os arquivos nas pastas do editor (fora da `.carta/` e da quarentena), sem sombras do sistema."""
    for pasta, subpastas, arquivos in os.walk(proj.raiz):
        atual = Path(pasta)
        if atual == proj.raiz:
            subpastas[:] = [s for s in subpastas if s not in (PASTA_INTERNA, QUARENTENA)]
        subpastas[:] = [s for s in subpastas if not s.startswith("._")]
        for a in arquivos:
            p = atual / a
            if not _ignorado(p):
                yield p


def quarentena(proj: Projeto, agora: float | None = None) -> list[tuple[Path, Path]]:
    """Leva para `Quarentena/<data>/<caminho relativo>` todo arquivo que não é nosso. Devolve (de, para).

    Nada é apagado; se o destino existir, ganha um sufixo. O `.parcial` recente (outra máquina gravando) fica."""
    agora = time.time() if agora is None else agora
    data = datetime.date.fromtimestamp(agora).isoformat()
    movidos = []
    for p in list(arquivos_do_editor(proj)):
        if e_nosso(p):
            continue
        if p.name.endswith(PARCIAL):
            try:
                if agora - p.stat().st_mtime < PARCIAL_VELHO_S:
                    continue
            except OSError:
                continue
        rel = p.relative_to(proj.raiz)
        destino = proj.raiz / QUARENTENA / data / rel
        n = 2
        while destino.exists():
            destino = destino.with_name(f"{rel.stem} ({n}){rel.suffix}")
            n += 1
        destino.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(p), str(destino))
        except FileNotFoundError:  # outra máquina levou antes: nada a fazer
            continue
        movidos.append((p, destino))
    return movidos
