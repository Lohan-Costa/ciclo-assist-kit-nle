# Os porteiros das rotas e o `escreve` das ferramentas

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### Dois porteiros diferentes

| rota | quem chama | porteiro |
|---|---|---|
| `GET /saude`, `GET /painel` | loader / navegação de topo | nenhum — não agem |
| `POST /conversar`, `/responder`, `GET /pendencias` | a página do painel | `Sec-Fetch-Site: same-origin` |
| `POST /mcp/<segredo>` | o subprocesso do Claude | o segredo no caminho |

⚠️⚠️ **`Sec-Fetch-Site`, NUNCA `Origin`.** Com o painel servido pelo próprio serviço, um
`GET` same-origin **não manda `Origin`**. Quem apostar nele vê o painel **carregar**, os
POSTs **funcionarem**, e todo GET voltar 401 — o sintoma manda depurar o lugar errado. O
`avpi://` vale só para o loader, que é a única peça que faz chamada cross-origin de verdade
(e ela precisa de `Access-Control-Allow-Origin: avpi://` de volta, nunca `*`).


### Ferramentas: `escreve` decide tudo

`mcp/registro.py` exige `escreve=` em toda ferramenta, sem padrão. Ele separa quem entra na
allowlist (**leitura nunca pergunta**) de quem passa pelo portão (**escrita sempre
pergunta**). Um editor que clica "permitir" quinze vezes para listar uma bin para de ler o
que clica.

Ferramenta só existe se o módulo dela for importado em `mcp/ferramentas/__init__.py` — o
registro é efeito colateral de import, e a lista é explícita por isso.
