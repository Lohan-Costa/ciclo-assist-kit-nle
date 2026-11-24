"""Organizar o projeto do Media Composer: criar pasta, mover e renomear bin ou pasta.

⭐⭐ **No MC, a organização do painel lateral É o disco** (banco,
`plugins/avid-panel-sdk/arrastar.md`, Frida, MC 24.6): criar pasta é `CreateDirectoryW`,
renomear e mover bin ou pasta é `MoveFileExW`. Então quem organiza por fora mexe nos
arquivos da pasta do projeto, e o MC passa a mostrar o estado novo depois de um SAVE ou de um
REFRESH do painel lateral (autor, 2026-11-01). Não é preciso reabrir o projeto.

⛔⛔ **Bin ABERTA se fecha antes** (`CloseBin`, que também a grava). Mover o `.avb` de uma bin
aberta deixaria o MC gravar a cópia da memória no caminho velho ao fechá-la, e a bin voltaria
a existir onde estava (banco, `protocolos/avb/escrita.md`: o MC salva por cima ao fechar).

⚠️ MEDIDO (MC 2024.6, 2026-11-01): até o save, o MC continua listando o nome VELHO
(`GetBins` e o painel). Uma bin renomeada aparece duas vezes, a velha como fantasma. O save
acerta a lista, mas o Ctrl+S só grava com algo MODIFICADO: renomear não suja nada, e o save
sozinho não acontece. Quem chama diz ao editor o gesto que falta.

Os caminhos são RELATIVOS à pasta do projeto, com `/`, e a bin vai SEM `.avb` (`D01/D01 CAM`):
é como o modelo já os lê em `listar_bins`.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

ACOES = ("criar_pasta", "mover", "renomear")

#: O que o editor consegue revisar num cartão (o mesmo teto da organização do Premiere).
MAXIMO_DE_OPERACOES = 60

#: Proibidos num nome de bin ou pasta (Windows) — e a barra, que faria do nome um caminho.
_PROIBIDOS = set('\\/:*?"<>|')

#: Arquivos e pastas do projeto que NÃO são bin nem pasta de bins.
_DO_SISTEMA = {"searchdata", "statistics", "waveformcache", "trash"}


class OrganizarFalhou(RuntimeError):
    """Uma operação não pôde ser feita — com o motivo, e o que já foi feito antes dela."""


def _limpo(caminho: str) -> str:
    c = str(caminho or "").replace("\\", "/").strip().strip("/")
    if c.lower().endswith(".avb"):
        c = c[:-4]
    return c


def _nome_ruim(nome: str) -> str:
    n = str(nome or "").strip()
    if not n:
        return "o nome está vazio"
    if n in (".", "..") or any(c in _PROIBIDOS for c in n):
        return f"o nome {nome!r} tem caractere que não pode (\\ / : * ? \" < > |)"
    if n.lower().endswith(".avb"):
        return f"o nome {nome!r} não leva .avb"
    return ""


def arvore(projeto: str | Path) -> dict[str, str]:
    """`{caminho relativo em minúsculas: "bin" | "pasta"}` do que há na pasta do projeto."""
    raiz = Path(projeto)
    saida: dict[str, str] = {}
    for atual, pastas, arquivos in os.walk(raiz):
        rel = Path(atual).relative_to(raiz).as_posix()
        if rel == ".":
            rel = ""
        pastas[:] = [p for p in pastas
                     if not p.startswith(".") and not (rel == "" and p.lower() in _DO_SISTEMA)]
        for p in pastas:
            saida[f"{rel}/{p}".strip("/").casefold()] = "pasta"
        for a in arquivos:
            if a.lower().endswith(".avb") and not a.startswith("._"):
                saida[f"{rel}/{a[:-4]}".strip("/").casefold()] = "bin"
    return saida


def _destino(op: dict) -> tuple[str, str]:
    """`(origem, destino)` relativos de uma operação de mover ou renomear."""
    item = _limpo(op.get("item", ""))
    nome_atual = item.rsplit("/", 1)[-1]
    mae = item.rsplit("/", 1)[0] if "/" in item else ""
    if op.get("acao") == "renomear":
        return item, f"{mae}/{str(op.get('nome') or '').strip()}".strip("/")
    para = _limpo(op.get("para", ""))
    return item, f"{para}/{nome_atual}".strip("/")


def conferir(projeto: str | Path, operacoes) -> str:
    """O que está errado no plano, ou vazio. Roda ANTES do cartão.

    ⭐ Simula o plano inteiro sobre a árvore do disco: uma pasta criada no começo pode
    receber bins logo depois, e uma bin renomeada é achada pelo nome novo adiante.
    """
    if not isinstance(operacoes, list) or not operacoes:
        return f"Diga as operações: uma lista de {', '.join(ACOES)}."
    if len(operacoes) > MAXIMO_DE_OPERACOES:
        return (f"{len(operacoes)} operações é mais do que o editor consegue revisar num cartão. "
                f"Faça em lotes de até {MAXIMO_DE_OPERACOES}.")
    if not Path(projeto).is_dir():
        return f"não achei a pasta do projeto: {projeto}"
    estado = arvore(projeto)
    problemas: list[str] = []
    for n, op in enumerate(operacoes, 1):
        if not isinstance(op, dict) or op.get("acao") not in ACOES:
            problemas.append(f"{n}: a ação tem de ser uma de {', '.join(ACOES)}")
            continue
        acao = op["acao"]
        if acao == "criar_pasta":
            ruim = _nome_ruim(op.get("nome", ""))
            dentro = _limpo(op.get("dentro_de", ""))
            if ruim:
                problemas.append(f"{n}: {ruim}")
                continue
            if dentro and estado.get(dentro.casefold()) != "pasta":
                problemas.append(f"{n}: não há pasta {dentro!r} para criar dentro")
                continue
            novo = f"{dentro}/{op['nome'].strip()}".strip("/")
            if novo.casefold() in estado:
                problemas.append(f"{n}: já existe {novo!r}")
                continue
            estado[novo.casefold()] = "pasta"
            continue
        if acao == "renomear":
            ruim = _nome_ruim(op.get("nome", ""))
            if ruim:
                problemas.append(f"{n}: {ruim}")
                continue
        origem, destino = _destino(op)
        especie = estado.get(origem.casefold())
        if not origem or especie is None:
            problemas.append(f"{n}: não há bin nem pasta {origem!r} no projeto")
            continue
        if acao == "mover":
            para = _limpo(op.get("para", ""))
            if para and estado.get(para.casefold()) != "pasta":
                problemas.append(f"{n}: não há pasta {para!r} (crie-a antes, no mesmo plano)")
                continue
            if especie == "pasta" and (para.casefold() + "/").startswith(origem.casefold() + "/"):
                problemas.append(f"{n}: a pasta {origem!r} não pode ir para dentro dela mesma")
                continue
        if destino.casefold() == origem.casefold():
            if destino == origem:
                problemas.append(f"{n}: {origem!r} já está assim")
                continue
        elif destino.casefold() in estado:
            problemas.append(f"{n}: já existe {destino!r}")
            continue
        # aplica na simulação: a pasta leva tudo o que tem dentro
        prefixo = origem.casefold()
        for chave in [c for c in estado if c == prefixo or c.startswith(prefixo + "/")]:
            estado[destino.casefold() + chave[len(prefixo):]] = estado.pop(chave)
    return "; ".join(problemas)


def bins_dentro(projeto: str | Path, relativo: str) -> list[Path]:
    """Os `.avb` que uma operação carrega junto: a própria bin, ou todas as de uma pasta."""
    alvo = Path(projeto) / _limpo(relativo)
    if alvo.with_suffix(".avb").is_file() and not alvo.is_dir():
        return [alvo.with_suffix(".avb")]
    if alvo.is_dir():
        return sorted(p for p in alvo.rglob("*.avb") if not p.name.startswith("._"))
    return []


def executar(projeto: str | Path, operacoes: list[dict],
             fechar_bin: Callable[[Path], None] | None = None) -> list[dict]:
    """Faz o plano, na ordem. `fechar_bin(caminho_absoluto)` fecha a bin no MC antes de mexer.

    Devolve uma linha por operação feita. ⛔ Uma falha no meio levanta `OrganizarFalhou`
    dizendo o que JÁ foi feito: desfazer às cegas seria mexer de novo no projeto do editor.
    """
    raiz = Path(projeto)
    feitas: list[dict] = []
    for n, op in enumerate(operacoes, 1):
        acao = op.get("acao")
        try:
            if acao == "criar_pasta":
                dentro = _limpo(op.get("dentro_de", ""))
                nova = raiz / dentro / str(op["nome"]).strip()
                nova.mkdir(parents=False, exist_ok=False)
                feitas.append({"acao": acao, "pasta": f"{dentro}/{nova.name}".strip("/")})
                continue
            origem, destino = _destino(op)
            for b in bins_dentro(raiz, origem):
                if fechar_bin:
                    fechar_bin(b)
            a = raiz / origem
            de = a if a.is_dir() else a.with_suffix(".avb")
            para = (raiz / destino) if a.is_dir() else (raiz / destino).with_suffix(".avb")
            if para.exists() and not os.path.samefile(para, de):
                raise OrganizarFalhou(f"já existe {destino!r}")
            os.replace(de, para)
            feitas.append({"acao": acao, "de": origem, "para": destino,
                           "especie": "pasta" if para.is_dir() else "bin"})
        except (OSError, KeyError, OrganizarFalhou) as e:
            ja = "; ".join(f"{f.get('de', '')}→{f.get('para', f.get('pasta', ''))}" for f in feitas)
            raise OrganizarFalhou(
                f"a operação {n} ({acao}) falhou: {e}"
                + (f". Já feitas antes dela: {ja}" if ja else ". Nada foi mudado antes dela")) from e
    return feitas
