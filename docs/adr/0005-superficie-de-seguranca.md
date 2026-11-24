# ADR 0005 — A superfície de ataque nova é o nome do arquivo do cliente

**Data:** 2026-09-10 · **Estado:** aceito
**Revisado:** 2026-09-10, defesa 4 corrigida antes de virar código (ver §Correção)

## O que muda em relação a tudo que já construímos

Os apps anteriores liam nome de mídia e nome de bin como **dado**. Aqui eles entram num
**prompt**. Uma bin chamada `ignore as instruções anteriores e ...` deixa de ser um nome
esquisito e vira tentativa de injeção — e ela chega pelo caminho normal do produto, não
por um invasor.

## As quatro defesas, em camadas

1. **`--restricted` sempre**, inclusive em release. Sem Bash, sem PowerShell, sem REPL,
   sem WebFetch. Sem ela, a caixa de chat é um shell na estação do cliente. Confirmado no
   spike: a flag remove de fato as ferramentas de execução da lista do `system/init`.
   ⛔⛔ **E `--tools ""` junto, desde 2026-09-13.** O `--restricted` tira só o que
   executa código: medido no CLI 2.1.270, **sobram 29 nativas**, com `Write`, `Edit`,
   `Read`, `Task` e `WebSearch` (`spikes/o_que_o_restricted_deixa.py`). Com `--tools ""`
   o modelo vê só as nossas ferramentas. E o portão recusa por nome o que não for
   `mcp__ciclo__*`, para o dia em que a flag faltar.
2. **`--strict-mcp-config`** (ADR 0002). Sem ela, uma injeção por nome de arquivo alcança
   o Gmail e o Drive do editor. É a diferença entre um prompt estranho e um incidente.
3. **Toda escrita passa por aprovação humana** (ADR 0003). Um plano injetado ainda precisa
   de um clique — e o plano é legível, com procedência item a item.
4. **Duas portas, dois porteiros diferentes** — ver abaixo.

## Defesa 4: quem pode falar com o serviço

O serviço local tem **dois tipos de cliente**, e eles não se autenticam do mesmo jeito.

### O painel (navegador dentro do MC) → `Sec-Fetch-Site: same-origin`

⚠️⚠️ **Correção antes de virar código.** A primeira versão deste ADR dizia "autorizar
pela origem `avpi://`, que é *forbidden header* e nenhuma página forja". A premissa está
certa; o cabeçalho está errado para o nosso desenho.

Medido pelo banco em 2026-08-09, MC 25.12: com a página **servida pelo serviço**
(ADR 0007), o painel é same-origin — e **uma requisição `GET` same-origin não manda
`Origin` nenhum**. O navegador só o envia em CORS e em POST.

⭐ **E o modo de falha é confuso de propósito para quem depurar:** o painel **carrega
normalmente**, os POSTs funcionam, e **todo `GET` volta 401**. Quem apostasse no `Origin`
iria procurar o defeito no serviço, não no cabeçalho.

O cabeçalho que serve é **`Sec-Fetch-Site: same-origin`**. É *forbidden header* pelo
mesmo motivo que o `Origin`: nenhuma página consegue defini-lo. Um site qualquer fazendo
`fetch` para `127.0.0.1` chega com `cross-site` e é recusado.

O `avpi://` continua valendo para **o loader**, que mora dentro do pacote e é a única
peça que faz chamada de fato cross-origin.

### O subprocesso do Claude → um segredo no caminho da rota

O `claude -p` não é navegador: não manda `Sec-Fetch-Site` nem `Origin`. Se a rota do MCP
aceitasse qualquer POST em loopback, **uma página web aberta no navegador do editor
poderia chamar as nossas ferramentas** — hoje só de leitura, amanhã não.

Por isso a rota do MCP não é `/mcp`: é **`/mcp/<segredo>`**, com o segredo sorteado a
cada arranque do serviço e entregue só ao subprocesso, dentro do `--mcp-config`.

⚠️ **Segredo em caminho de URL é aceitável AQUI, e não é regra geral.** Ele funciona
porque nunca atravessa a rede, nunca aparece em barra de endereço e morre com o processo.
Num serviço exposto, um caminho vaza por log e por `Referer` — e aí a resposta seria
outra.

## Por que não um arquivo de segredo

⭐ Registrado no banco (`plugins/avid-panel-sdk/README.md`): o painel roda em QtWebEngine
**sem acesso a disco** — não conseguiria ler um arquivo de token. E um segredo embutido no
`.avpi` seria pior: a pasta de plugins é `rwxrwxrwx`, qualquer processo local o leria.

## Nomes entram delimitados e rotulados como dados

Nome de mídia, de bin e de projeto chegam ao prompt dentro de bloco delimitado e
explicitamente marcados como conteúdo não confiável. Não elimina o risco; reduz.
