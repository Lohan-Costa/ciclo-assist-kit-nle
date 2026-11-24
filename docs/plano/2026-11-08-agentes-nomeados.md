# Ideia: agentes com nome, um por função, orquestrados

Autor, 2026-11-08. **Ideia registrada; o desenho proposto está em `2026-11-08-agentes.md`.**

## A ideia

Hoje o Ciclo Assist atua como uma inteligência só. O desenho proposto é criar e dar nomes a agentes, e o pedido do editor
aciona o agente daquela função:

| o editor pede | agente acionado |
|---|---|
| um sync | agente de sync |
| uma separação de falas | agente de decupagem |
| uma organização do projeto | agente de organização |
| … | um por função |

Orquestrar e acionar agentes permite **dividir as tarefas e dar clareza à função de cada etapa**.

## Como se liga ao que já foi decidido

- **O gerente** (mesma data, `2026-11-08-aba-sincronizar.md`, decisão 6): todo fluxo autônomo tem um agente de revisão que
  confere a entrega, ligado por padrão. Ele é um dos papéis deste desenho.
- **O revisor de fontes** das receitas de sync é um caso do gerente.

## A definir quando for desenvolver

- A lista de agentes, os nomes e o que cada um pode fazer (ferramentas, leitura x escrita).
- Quem escolhe o agente: um orquestrador por conversa, ou uma regra pelo pedido.
- Como isso convive com o `claude -p`, o portão de aprovação e o limite de um turno por vez (ver `CLAUDE.md`).
- Quanto custa: cada agente é um turno, e o piso de um turno é alto (medido em ~40 mil tokens, `CLAUDE.md`, "Decupar em lote").
