# 0008 — Uma sessão de trabalho por vez; progresso é lido, não empurrado

**Status:** ativa · Data: 2026-08-10

**Contexto:** o painel é de um editor, e o Media Composer é um recurso único — duas
preparações concorrentes disputariam a mesma API gRPC (piso de ~500 ms por chamada) e o
mesmo projeto aberto.

**Decisão:** `sessao.py` embrulha o relink síncrono (`relink.py`) numa thread e guarda o
estado num lugar que as rotas conseguem ler. Uma tarefa por vez: a segunda preparação
recebe `409` em vez de entrar numa fila que ninguém pediu.

O endpoint `/progresso` é SSE, mas cada evento carrega o **estado inteiro** da sessão,
não um delta. Se o painel cair no meio de uma aplicação de 80 s (ex.: reload da webview,
ver o aviso sobre isso na seção de operação da arquitetura), a próxima conexão
reencontra a situação — não há evento perdido, porque nada é entregue *por* evento.

**Medido, exercitado ponta a ponta por HTTP** (do jeito que o painel realmente usa):
preparar → revisar → escolher → aplicar, 106 eventos SSE (um por arquivo do
`LinkFile`), 100/100 masters online.

## Dois defeitos que só o teste por HTTP mostrou (não por script)

- **O SSE emitia a cada 0,4 s mesmo parado.** A guarda "só emite quando muda" comparava
  o estado inteiro, e o campo `decorrido` muda a cada tique — a guarda nunca se aplicava
  de fato. Corrigido: o relógio ficou fora da comparação e viaja de carona no próximo
  evento real (30 eventos → 3 num preparo de 12 s).
- **O motor herdado (`relinker.*`) afogava o log** — uma linha INFO por arquivo
  indexado, 445 linhas numa varredura. Fica em `WARNING`, salvo quando se pede
  `--log debug` de propósito.

**Lição de método:** nenhum dos dois defeitos aparece rodando o motor por script — os
dois só aparecem no primeiro minuto de uso real do painel, porque dependem do ritmo real
de eventos numa conexão HTTP de longa duração, não da lógica em si.
