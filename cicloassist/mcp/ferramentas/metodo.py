"""`consultar_o_metodo` — o ofício de montagem, carregado quando o trabalho pede.

⭐⭐ É a nossa versão de "skill", e ela existe por uma medida: **`--restricted` bloqueia as
skills do Claude Code** (`spikes/o_cli_carrega_skill.py`, 2026-09-12 — sem a flag a skill
carrega, com ela nunca). E `--restricted` é o ADR 0005: sem ela, a caixa de chat do painel
é um shell na estação do cliente. Ver `docs/adr/0010-o-metodo-do-oficio.md`.

## O que se ganha fazendo do nosso jeito

O valor de uma skill não é o formato do arquivo — é **carregar por condição, em vez de
sempre**. A persona vai em todo turno, sobre qualquer assunto; "que bins existem neste
projeto?" não precisa saber como se mapeia roteiro em sonora.

Aqui, a lista de assuntos é a **descrição** desta ferramenta (~50 tokens, lidos sempre) e o
corpo só entra quando o modelo pede.

⚠️ **O preço disso é o disparo.** A skill do CLI carrega sozinha pela descrição; esta
depende de o modelo lembrar de chamar — e é por isso que a persona manda consultar antes de
montar, e que a descrição abaixo diz *quando*, não *o que*.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.metodo")

#: ⭐ Os métodos moram em arquivos versionados no REPO, e não na máquina do editor: duas
#: instalações não divergem, e um conserto de regra chega por atualização do produto.
PASTA = Path(__file__).resolve().parent.parent.parent / "skills"

#: ⚠️ Lista fechada, com a CONDIÇÃO de cada um — é ela que o modelo lê em todo turno. O
#: texto aqui é caro (vai sempre); o texto do arquivo é barato (vai quando serve).
ASSUNTOS = {
    "montar-por-roteiro": (
        "montar uma cena a partir de um roteiro, lista de falas ou ordem aprovada de "
        "sonoras — inclui como casar roteiro com transcrição, escolher take e onde cortar"
    ),
    "separar-falas": (
        "separar as falas de uma cena, com ou sem roteiro — uma timeline por fala com os "
        "takes que a dizem"
    ),
}


@ferramenta(
    nome="consultar_o_metodo",
    descricao=(
        "O método da casa para um tipo de trabalho de edição, com o que foi MEDIDO em "
        "material real e o que nunca se deve fazer. Consulte ANTES de começar, não depois "
        "de errar. Assuntos: "
        + " · ".join(f"{nome} ({quando})" for nome, quando in ASSUNTOS.items())
    ),
    esquema={
        "type": "object",
        "properties": {
            "assunto": {
                "type": "string",
                "enum": sorted(ASSUNTOS),
                "description": "Qual método você quer.",
            },
        },
        "required": ["assunto"],
    },
    escreve=False,
    nles=AMBOS,
)
def consultar_o_metodo(assunto: str) -> dict[str, object]:
    chave = (assunto or "").strip().lower()
    if chave not in ASSUNTOS:
        # ⛔ Lista fechada: o nome vira caminho de arquivo. Sem isto, um assunto inventado
        #    pelo modelo leria qualquer `.md` do disco (ADR 0005).
        return {"erro": f"não tenho método para {assunto!r}. Tenho: "
                        f"{', '.join(sorted(ASSUNTOS))}."}

    alvo = PASTA / f"{chave}.md"
    try:
        texto = alvo.read_text(encoding="utf-8")
    except OSError as e:
        # ⚠️ Faltar o arquivo é defeito de empacotamento, não do projeto do editor — e o
        #    modelo precisa saber que o método não veio, em vez de improvisar um.
        log.error("método %s ilegível em %s: %s", chave, alvo, e)
        return {"erro": f"o método {chave} não veio nesta instalação"}

    log.info("método consultado: %s (%d caracteres)", chave, len(texto))
    return {
        "assunto": chave,
        "metodo": texto,
        "confianca": "confirmado",
        "fonte": "heuristica",
    }
