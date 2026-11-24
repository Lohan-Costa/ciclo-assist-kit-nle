"""As referências da Carta Aberta: um `.ref.json` por mídia, na pasta do editor (plano §4.2).

O `.ref.json` é IMUTÁVEL e guarda só a IDENTIDADE da mídia (nome da fonte, TC, taxa, quadros, duração, tipo) e um
`id`; os vínculos (onde está cada forma, em cada máquina) moram no diário, chaveados pelo `id`. ⭐ Por isso o editor
pode mover e renomear as referências no Finder/Explorer à vontade.

⛔⛔ O caminho é DICA; a identidade é a verdade (plano §4.2): `D:\\` no Windows é `/Volumes/SSD` no Mac.
`onde()` guarda o rótulo do volume + o relativo, além do absoluto observado.
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from pathlib import Path

from .projeto import CartaErro, Projeto, arquivos_do_editor, arquivos_ocultos, gravar_json

FORMATO = "ref/1"
SUFIXO = ".ref.json"
#: os campos de `identidade.sondar` que identificam a mídia (o resto da sonda não entra)
CAMPOS = ("nome_da_fonte", "tipo", "tc", "fps", "quadros", "duracao_s", "canais_de_som", "umid")


def identidade_da_sonda(sonda: dict) -> dict:
    return {k: sonda[k] for k in CAMPOS if sonda.get(k) not in (None, "", [])}


def _nome_de_arquivo(nome: str) -> str:
    limpo = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", nome).strip(" .")
    return limpo or "midia"


def criar(proj: Projeto, pasta: str | Path, nome: str, identidade: dict, entrou_por: dict,
          distinta: bool = False) -> tuple[Path, dict]:
    """Cria a referência de UMA mídia em `<raiz>/<pasta>` e devolve (caminho, dados).

    ⭐ Idempotente: se a pasta já tem uma referência com a MESMA identidade, devolve a que existe (mandar a mesma
    diária duas vezes não duplica). Mesmo nome com identidade diferente ganha sufixo — nunca sobrescreve."""
    destino_dir = (proj.raiz / pasta).resolve()
    if proj.raiz.resolve() not in destino_dir.parents and destino_dir != proj.raiz.resolve():
        raise CartaErro(f"{pasta} fica fora do projeto")
    if not destino_dir.is_dir():
        raise CartaErro(f"a pasta {pasta} não existe no projeto — crie-a antes (o programa não cria pastas sozinho)")
    base = _nome_de_arquivo(nome)
    n = 1
    while True:
        destino = destino_dir / (base + (f" ({n})" if n > 1 else "") + SUFIXO)
        if not destino.exists():
            break
        existente = ler(destino)
        if existente and existente.get("identidade") == identidade and not distinta:   # `distinta`: o editor disse "é outra" (C2)
            return destino, existente
        n += 1
    dados = {"carta_aberta": FORMATO, "id": uuid.uuid4().hex, "nome": nome,
             "tipo": identidade.get("tipo", ""), "identidade": identidade, "entrou_por": entrou_por}
    gravar_json(destino, dados)
    return destino, dados


def ler(caminho: Path) -> dict | None:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) and d.get("carta_aberta") == FORMATO and d.get("id") else None


def todas(proj: Projeto) -> list[tuple[Path, dict]]:
    """As referências do projeto, onde estiverem (o editor pode tê-las movido) — as OCULTAS também: elas continuam
    sendo do projeto (o item que as usa as acha; mandar de novo as traz de volta). Quem quer só a vitrine olha a pasta."""
    out = []
    for p in [*arquivos_do_editor(proj), *arquivos_ocultos(proj)]:
        if p.name.endswith(SUFIXO):
            d = ler(p)
            if d:
                out.append((p, d))
    return out


def _rotulo_do_volume_windows(letra: str) -> str | None:
    try:
        import ctypes
        buf = ctypes.create_unicode_buffer(261)
        ok = ctypes.windll.kernel32.GetVolumeInformationW(f"{letra}:\\", buf, 261, None, None, None, None, 0)
        return buf.value if ok and buf.value else None
    except Exception:  # noqa: BLE001
        return None


def onde(arquivo: str | Path) -> dict:
    """{arquivo, volume, relativo}: o absoluto DESTA máquina e o par (rótulo do volume, relativo) que outra máquina
    traduz (`/Volumes/SSD/x` ⇄ a letra cujo volume se chama `SSD`; matriz, "caminho do OUTRO SO")."""
    a = os.path.abspath(str(arquivo))
    volume, relativo = None, None
    if sys.platform == "darwin":
        m = re.match(r"^/Volumes/([^/]+)/(.*)$", a)
        if m:
            volume, relativo = m.group(1), m.group(2)
        else:
            volume, relativo = "/", a.lstrip("/")
    elif os.name == "nt":
        m = re.match(r"^([A-Za-z]):[\\/](.*)$", a)
        if m:
            volume, relativo = _rotulo_do_volume_windows(m.group(1)) or f"{m.group(1).upper()}:", m.group(2)
        relativo = relativo.replace("\\", "/") if relativo else relativo
    return {"arquivo": a, "volume": volume, "relativo": relativo}
