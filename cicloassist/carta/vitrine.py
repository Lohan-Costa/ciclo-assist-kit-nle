"""A VITRINE da Carta Aberta: o que cada pasta mostra, e os gestos que mexem nela (C2 parte 2, decisões do autor de
2026-11-13 no plano).

⭐ A régua é a bin do Avid: a lista é a vitrine; por baixo, o projeto carrega OCULTO (`proj.ocultas`) o que os itens
precisam para serem recriados.

- **Remover** leva a referência (ou o item) para a área oculta: some da vista, e só. Nenhum arquivo de mídia é tocado,
  e quem a usa continua a usá-la ("Mostrar clipes referenciados" a revela). Sem ninguém que a referencie, ela fica
  inacessível até ser mandada de novo — o "mandar" a reconhece e a traz de volta.
- **Mover** leva entre pastas (e da área oculta para uma pasta, o que a torna visível ali). O vínculo é do `id`.
- **Pastas:** criar (`vista.nova_pasta`), renomear, mover e remover. Remover uma pasta remove da vista o que ela mostra
  (vai para a área oculta, como acima) e leva a pasta, já sem nada da Carta, para a `Quarentena/<data>/` — nada se apaga.
"""

from __future__ import annotations

import datetime
import os
import shutil
from pathlib import Path

from . import itens as _itens
from . import referencias as _refs
from .projeto import QUARENTENA, CartaErro, Projeto
from .vista import pasta_do_projeto


def _todos(proj: Projeto) -> dict[str, tuple[Path, dict, str]]:
    """{id: (caminho, dados, sufixo)} de referências e itens, visíveis e ocultos."""
    out = {d["id"]: (c, d, _refs.SUFIXO) for c, d in _refs.todas(proj)}
    out.update({d["id"]: (c, d, _itens.SUFIXO) for c, d in _itens.todos(proj)})
    return out


def oculta(proj: Projeto, caminho: Path) -> bool:
    return Path(caminho).resolve().parent == proj.ocultas.resolve()


def _livre(pasta: Path, base: str, sufixo: str) -> Path:
    n, destino = 1, pasta / f"{base}{sufixo}"
    while destino.exists():
        n += 1
        destino = pasta / f"{base} ({n}){sufixo}"
    return destino


def esconder(proj: Projeto, caminho: Path, dados: dict, sufixo: str) -> Path:
    """Leva para a área oculta, com o `id` no nome (dois homônimos ocultos nunca se pisam)."""
    proj.ocultas.mkdir(parents=True, exist_ok=True)
    destino = proj.ocultas / f"{dados['id']}{sufixo}"
    if Path(caminho).resolve() != destino.resolve():
        os.replace(caminho, destino)
    return destino


def mostrar_em(proj: Projeto, caminho: Path, dados: dict, sufixo: str, pasta: Path) -> Path:
    """Leva para a pasta do editor `pasta` (absoluta, já conferida), com o nome da mídia/item."""
    if Path(caminho).resolve().parent == pasta.resolve():
        return Path(caminho)
    destino = _livre(pasta, _refs._nome_de_arquivo(dados.get("nome") or dados["id"]), sufixo)
    os.replace(caminho, destino)
    return destino


def remover(proj: Projeto, ids: list[str]) -> dict:
    """Some da vista: cada referência/item vai para a área oculta. Devolve {removidos, nao_achados}."""
    todos = _todos(proj)
    removidos, nao = [], []
    for i in ids:
        if i not in todos:
            nao.append(i)
            continue
        c, d, suf = todos[i]
        if not oculta(proj, c):
            esconder(proj, c, d, suf)
        removidos.append(d.get("nome") or i)
    return {"removidos": removidos, "nao_achados": nao}


def mover(proj: Projeto, ids: list[str], pasta: str) -> dict:
    """Leva as referências/itens para `pasta` (da área oculta também: aí passam a ser vistos). {movidos, ja_estavam}."""
    destino = pasta_do_projeto(proj, pasta)
    if not destino.is_dir():
        raise CartaErro(f"a pasta {pasta or proj.nome} não existe mais (outro editor pode tê-la mudado)")
    todos = _todos(proj)
    movidos, ja = [], []
    for i in ids:
        if i not in todos:
            continue
        c, d, suf = todos[i]
        if Path(c).resolve().parent == destino:
            ja.append(d.get("nome") or i)
            continue
        mostrar_em(proj, c, d, suf, destino)
        movidos.append(d.get("nome") or i)
    return {"movidos": movidos, "ja_estavam": ja}


# ── as pastas ─────────────────────────────────────────────────────────────────

def renomear_pasta(proj: Projeto, pasta: str, nome: str) -> str:
    """Renomeia a pasta (não a raiz). O nome passa pela mesma régua de "+ Nova pasta"."""
    if not pasta:
        raise CartaErro("a raiz do projeto não se renomeia por aqui (é a pasta que você escolheu)")
    atual = pasta_do_projeto(proj, pasta)
    if not atual.is_dir():
        raise CartaErro(f"a pasta {pasta} não existe mais")
    _validar_nome(proj, atual.parent, nome)
    novo = atual.parent / nome.strip()
    os.replace(atual, novo)
    return novo.resolve().relative_to(proj.raiz.resolve()).as_posix()


def mover_pasta(proj: Projeto, pasta: str, para: str) -> str:
    """Leva a pasta (com o que tem dentro) para dentro de `para`."""
    if not pasta:
        raise CartaErro("a raiz do projeto não se move")
    atual = pasta_do_projeto(proj, pasta)
    destino = pasta_do_projeto(proj, para)
    if destino == atual or atual in destino.parents:
        raise CartaErro("uma pasta não vai para dentro dela mesma")
    if destino == atual.parent:
        return pasta
    _validar_nome(proj, destino, atual.name)
    novo = destino / atual.name
    os.replace(atual, novo)
    return novo.resolve().relative_to(proj.raiz.resolve()).as_posix()


def remover_pasta(proj: Projeto, pasta: str, agora: float | None = None) -> dict:
    """Remove da vista tudo o que a pasta (e as de dentro) mostra, e leva a pasta para a Quarentena. Nada se apaga."""
    if not pasta:
        raise CartaErro("a raiz do projeto não se remove")
    alvo = pasta_do_projeto(proj, pasta)
    if not alvo.is_dir():
        raise CartaErro(f"a pasta {pasta} não existe mais")
    dentro = [i for i, (c, _, _) in _todos(proj).items() if alvo in Path(c).resolve().parents]
    conta = remover(proj, dentro)
    data = datetime.date.fromtimestamp(agora if agora is not None else datetime.datetime.now().timestamp()).isoformat()
    destino = _livre(proj.raiz / QUARENTENA / data, alvo.name, "")
    destino.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(alvo), str(destino))
    return {**conta, "quarentena": destino.relative_to(proj.raiz).as_posix()}


def _validar_nome(proj: Projeto, pai: Path, nome: str) -> None:
    import re

    from .projeto import PASTA_INTERNA
    nome = (nome or "").strip()
    if not nome or nome in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', nome) or nome.startswith("."):
        raise CartaErro("nome de pasta inválido (sem / \\ : * ? \" < > | e sem começar por ponto)")
    if pai.resolve() == proj.raiz.resolve() and nome in (PASTA_INTERNA, QUARENTENA):
        raise CartaErro(f"{nome} é um nome reservado da Carta Aberta")
    if (pai / nome).exists():
        raise CartaErro(f"já existe {nome} ali")
