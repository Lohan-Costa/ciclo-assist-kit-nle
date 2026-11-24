"""O `dev.ps1` precisa de BOM, e um teste é o que impede o BOM de sumir.

⚠️⚠️ **A regressão que isto trava.** O Windows PowerShell 5.1 lê um `.ps1` **sem BOM**
como ANSI (cp1252), não como UTF-8. Um traço longo (`—`, `E2 80 94`) chega ao parser como
`â€"`, e o `0x94` do cp1252 é `”` — que o PowerShell aceita como **aspas de fechamento**.
A string termina onde não devia, o resto da linha vira código, e o script morre com
`Missing closing '}'` apontando para uma chave que está lá.

⭐ **A mensagem acusa o lugar errado**: o erro aparece dezenas de linhas depois do acento
que o causou. Medido no De Lá Pra Cá em 2026-08-15, e por isso o teste existe: qualquer
editor que grave UTF-8 sem BOM quebra o script em silêncio, e a suspeita cai na sintaxe.
"""

from __future__ import annotations

from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parent.parent
SCRIPTS = sorted(RAIZ.glob("*.ps1"))


def test_existe_pelo_menos_um_script():
    """Se o `dev.ps1` for renomeado ou movido, este arquivo inteiro passaria vazio e
    ninguém notaria que a proteção sumiu junto."""
    assert SCRIPTS, "não achei nenhum .ps1 na raiz do repo"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_tem_bom_utf8(script: Path):
    assert script.read_bytes()[:3] == b"\xef\xbb\xbf", (
        f"{script.name} perdeu o BOM. O PowerShell 5.1 vai lê-lo como cp1252 e morrer "
        f"com um erro de sintaxe que aponta para o lugar errado. Regrave com BOM."
    )


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_e_utf8_valido(script: Path):
    script.read_bytes().decode("utf-8")


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_usa_crlf(script: Path):
    """`.gitattributes` marca `*.ps1 eol=crlf`. Um LF solto indica que alguém gravou
    passando por cima da normalização."""
    dados = script.read_bytes()
    assert dados.count(b"\n") == dados.count(b"\r\n"), f"{script.name} tem LF solto"


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_nao_usa_sintaxe_que_o_powershell_5_1_nao_tem(script: Path):
    """⚠️ O alvo é o **Windows PowerShell 5.1**, que vem no Windows — não o PowerShell 7.

    Nele não existem `&&`/`||` (erro de parser), nem ternário `? :`, nem `??`. O script
    roda na estação do editor, onde só há o 5.1.
    """
    texto = script.read_text(encoding="utf-8")
    # Fora de comentário: linhas de comentário podem citar os operadores ao explicá-los.
    codigo = "\n".join(
        l for l in texto.splitlines() if not l.lstrip().startswith("#")
    )
    for proibido in ("&&", "||", "??"):
        assert proibido not in codigo, (
            f"{script.name} usa {proibido!r}, que o Windows PowerShell 5.1 não tem"
        )


def test_o_vbs_gerado_nao_leva_bom():
    """`Set-Content -Encoding UTF8` grava BOM no PowerShell 5.1, e o wscript recusa com "Invalid character" (800A0408)."""
    texto = (Path(__file__).resolve().parents[1] / "instalar.ps1").read_text(encoding="utf-8-sig")
    linha = next(l for l in texto.splitlines() if "Set-Content -Path $iniciar" in l)
    assert "-Encoding Default" in linha


@pytest.mark.parametrize("script", SCRIPTS, ids=lambda p: p.name)
def test_param_e_a_primeira_instrucao(script: Path):
    """⛔⛔ **`param()` fora do topo vira um COMANDO chamado `param`, e falha calado.**

    Medido em 2026-09-10 no `instalar.ps1`: com o `param()` depois de
    `$ErrorActionPreference`, o parser ACEITOU o arquivo, apareceu um
    `CommandNotFoundException` no meio da saída, **o script continuou rodando**, e o
    parâmetro simplesmente não existia — `-Conferir` foi ignorado e o instalador seguiu
    para a tela de consentimento como se nada tivesse sido pedido.

    O parser não pega isto (`ParseFile` devolve zero erros), então o teste é o único lugar
    onde a regra cabe.
    """
    linhas = script.read_text(encoding="utf-8-sig").splitlines()
    executaveis = [
        (i, l.strip()) for i, l in enumerate(linhas, 1)
        if l.strip() and not l.strip().startswith("#")
    ]
    if not executaveis:
        return
    primeira_linha, primeira = executaveis[0]
    tem_param = any(l.startswith("param(") for _, l in executaveis)
    if not tem_param:
        return
    assert primeira.startswith("param("), (
        f"{script.name}: a primeira instrucao executavel e a linha {primeira_linha} "
        f"({primeira[:40]!r}), nao o param(). Fora do topo ele vira um comando e o "
        f"parametro nao existe — sem erro que pare o script."
    )
