# ADR 0010 — O método do ofício é uma FERRAMENTA nossa, não uma skill do CLI

**Data:** 2026-09-12 · **Estado:** aceito · **Depende de:** [ADR 0005](0005-superficie-de-seguranca.md)

## Decisão

O conhecimento de montagem — como mapear roteiro em material, onde cortar, o que nunca
emendar — mora em **arquivos `.md` versionados no repo** (`cicloassist/skills/`), e chega
ao modelo por uma **ferramenta MCP de leitura** (`consultar_o_metodo`), chamada quando o
trabalho pede.

⛔ **Não** por `.claude/skills/SKILL.md` do Claude Code, que era o caminho óbvio.

## A medida que decidiu

`spikes/o_cli_carrega_skill.py`, 2026-09-12. Uma skill de teste manda o modelo terminar
toda resposta com uma palavra improvável; se ela aparece, a skill foi lida.

| caso | leu? |
|---|---|
| cwd com a skill, `--restricted` | **não** |
| + `--allowedTools` só das nossas | **não** |
| + `--setting-sources project` | **não** |
| **sem `--restricted`** | **SIM** |
| controle: pasta sem skill | não |

⇒ **`--restricted` bloqueia skills.** E `--restricted` é o ADR 0005: sem ela, a caixa de
chat do painel é um shell na estação do cliente. Trocar a contenção do produto pelo
formato de arquivo de outra ferramenta seria péssimo negócio.

## O que se ganha mesmo assim

O valor da skill não é o formato do arquivo — é **carregar por condição em vez de sempre**.
Isso a gente consegue com a nossa própria ferramenta, e de quebra fica melhor em dois
pontos:

- ⭐ **O método é versionado com o código**, no repo, e não na máquina do editor. Duas
  instalações não divergem, e um conserto de regra chega por atualização.
- ⭐ **A lista de assuntos é a descrição da ferramenta**, que o modelo lê em todo turno —
  são ~50 tokens. O corpo, que é longo, só entra quando ele pede.

## Por que não continuar na persona

A persona vai em **todo** turno, sobre qualquer assunto. "Que bins existem neste projeto?"
não precisa saber como se mapeia roteiro em sonora. Hoje ela já carrega regra de decupagem,
regra de corte e regra de busca — e cada regra nova encarece toda pergunta do dia.

⚠️ A persona continua existindo, e continua sendo o lugar do que vale **sempre**: quem ele
é, com quem fala, que dado é dado e não instrução. O que muda de tarefa para tarefa sai de
lá.

## O formato

Copiamos o que o [estudo do Jumper](../../../EDT-ASSIST/pesquisa/jumper/skills-jumper/)
mostrou funcionar num produto de pós-produção que já roda:

- um arquivo por tarefa, com `quando` (a condição de disparo) no topo;
- o método em passos, não em prosa;
- ⭐ **o que NUNCA fazer**, explícito — é a parte que mais salva, e a que um modelo não
  deduz sozinho;
- e, o que é nosso: **procedência**. Toda afirmação do método diz se foi medida, e onde.

## ⚠️ O que fica por medir

Se o CLI um dia separar "skills" de "shell", o caminho nativo volta a ser melhor — ele já
traz disparo automático por descrição, que aqui depende de o modelo lembrar de chamar a
ferramenta. **A medição acima tem data**: `claude` 2.1.x, 2026-09-12.
