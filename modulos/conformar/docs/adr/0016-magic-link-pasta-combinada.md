# 0016 — Magic Link: a timeline vai por uma pasta combinada, e o Resolve a puxa

**Status:** decidido com o usuário (2026-09-24) · implementado (Windows) · Data: 2026-09-24
**Relaciona-se com** o [ADR 0007](0007-portao-sem-token-defesa-por-origem.md) (emendado), o
[ADR 0015](0015-export-le-a-bin-nunca-chama-exportfile.md) e o [ADR 0017](0017-insert-pela-copia-do-editor.md).

---

## Contexto

A aba **Daqui Pra Lá** já gerava um DRT que o Resolve 19 abre com a mídia online. Faltava o
gesto: o editor mandar do Avid e o outro lado (colorista, VFX, ou ele mesmo) receber sem
caçar arquivo. O usuário descartou conexão direta entre as máquinas: *"uma pasta em rede onde
seria salvo o envio e do lado de quem recebe um botão de scan"*.

## Decisão

1. **O envelope é a Carta Aberta 1.1** (`docs/carta-aberta.md`), que passou a ser **sem perdas**:
   leva a leitura crua da bin e o que o remetente sabia da mídia. Regra do usuário: *"nada deve
   ser perdido na carta aberta"*. Critério medido: DRT da bin ≡ DRT da Carta em 80 sequências
   reais (`tests/test_carta_ida_e_volta.py`).
2. **Quem envia** grava `<sequência>__<id8>.carta.json` na **pasta combinada**, com gravação atômica
   (`.parcial` + `os.replace`). A pasta é escolhida uma vez e guardada na `.delapraca.json` **do
   projeto** (segue a produção, como o banco de mídias).
3. **Quem recebe** é um **script Lua** no Resolve (Workspace › Scripts, `plugins/resolve/`), fino:
   lista, pede e importa. O trabalho fica no **serviço do De Lá Pra Cá** da máquina do Resolve
   (modo `--receptor`, sem vigia do Media Composer, encerra ocioso):
   - `GET /receber/caixa` lista;
   - `POST /receber/preparar` resolve a mídia **desta** máquina e escreve um **DRT temporário**
     (inserts filtrados);
   - o script importa com `MediaPool:ImportTimelineFromFile`, medido no Studio 19;
   - `POST /receber/trazido` anota, só nesta máquina.
4. **Emenda ao ADR 0007 — o token existe para quem lê disco.** O script fala por `curl`, sem
   `Origin`. Ele prova quem é com um token de 256 bits que o serviço grava em
   `pasta_dados()/token` a cada início (`token_local.py`, porte do Órbita), mandado em
   `X-DeLaPraCa-Token` e comparado em tempo constante. Vale **só** em `/receber/*`. Página web
   continua barrada antes; o painel do Avid continua sem token.

## Consequências

- A Carta vem de outra máquina por uma pasta que qualquer um com acesso escreve. Ela é **texto
  de terceiro**: teto de 64 MB, só `1.x`, forma conferida (`ler_carta`), só o nível de cima
  da pasta. **Nenhum caminho de dentro dela é tocado sem `caminho_confiavel`** (UNC e `..`
  recusados antes do disco). O DRT é nomeado pelo `id` validado. Ameaças T-15, T-16 e T-17 em
  `modelagens/…/ameacas.yaml`.
- O script sobe o serviço pelo comando que a **instalação** grava em `receptor.json`
  (`tools/pack.py`). A instalação do aplicativo gravar o seu próprio: `pendente`.
- ⚠️ `io.popen` do Lua abre janela de console no Windows? `pendente` (spike c do plano).
  O `curl` do script **bloqueia a interface do Resolve** enquanto o serviço prepara o DRT
  (o script roda no processo do Resolve).
- macOS: tudo `pendente`, inclusive a versão do Resolve de lá e se o esqueleto R19 abre.
