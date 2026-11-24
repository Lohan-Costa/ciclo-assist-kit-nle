# Decisões de arquitetura

Uma decisão por arquivo, numerada, com a evidência que a sustenta. Decisão sem evidência
medida diz isso na cara — ver os `⚠️ por medir` espalhados.

| # | decisão | resumo |
|---|---|---|
| [0001](0001-backend-do-modelo.md) | Backend do modelo | a assinatura do editor, via `claude` CLI — e por que não o app |
| [0002](0002-transporte-do-mcp.md) | Transporte do MCP | HTTP em 127.0.0.1 + `--strict-mcp-config` |
| [0003](0003-modelo-de-permissao.md) | Permissão | botão no painel; leitura nunca pergunta |
| [0004](0004-identidade-de-sessao.md) | Sessão | uma por projeto, processo vivo, `--resume` |
| [0005](0005-superficie-de-seguranca.md) | Segurança | o nome do arquivo do cliente é a superfície nova |
| [0006](0006-onboarding.md) | Onboarding | três estados a distinguir; ter o app **não** é ter o CLI |
| [0007](0007-painel-servido-pelo-servico.md) | Painel | o `.avpi` só carrega um loader; a UI vem do serviço |
| [0008](0008-aprovacao-sem-relogio.md) | Aprovação sem relógio | o pedido espera para sempre; quem executa é o clique |
| [0009](0009-modo-automatico.md) | Modo automático | um toggle do editor dispensa a confirmação — e nunca o registro |
| [0010](0010-o-metodo-do-oficio.md) | O método do ofício | `--restricted` bloqueia skill do CLI (medido); o ofício vira ferramenta nossa |
