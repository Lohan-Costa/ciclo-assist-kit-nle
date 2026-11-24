# ADR 0002 — MCP em HTTP no 127.0.0.1, nunca stdio

**Data:** 2026-09-10 · **Estado:** aceito

## Contexto

O `claude -p` aceita servidor MCP por stdio ou por HTTP. Stdio é o padrão da maioria dos
exemplos e o mais simples de configurar.

## Decisão

**HTTP em `127.0.0.1`**, com `--strict-mcp-config`.

## Por quê

Stdio **sobe uma cópia nova do nosso motor por sessão**. Essa cópia nasce sem ponte com o
Media Composer: o cliente gRPC, o estado do projeto aberto e a conexão com o painel vivem
no serviço que já está rodando. Um processo MCP recém-nascido teria de reconstruir tudo
isso a cada conversa — e o gRPC do MC tem piso de ~500 ms por chamada.

Com HTTP, o servidor MCP **é** o serviço que já segura a ponte. Uma peça, um estado.

## A flag estrita não é higiene, é contenção

⚠️ **Medido em 2026-09-10.** Sem `--strict-mcp-config`, a sessão do plugin herda os MCP
servers da conta do usuário. No teste entraram três — Gmail, Google Drive e Adobe — com
**35 ferramentas** que não têm nada a ver com edição. Em ordem de gravidade:

1. O Claude pode agir sobre e-mail e arquivos pessoais do editor a partir de um prompt que
   veio de um **nome de mídia de cliente** (ver ADR 0005).
2. Estoura contexto e degrada a escolha de ferramenta.
3. O comportamento do produto passa a depender do que o cliente instalou na conta dele —
   irreproduzível no suporte.
