# Servidor de percepção no Mac mini — o que o Ciclo Assist precisa dele

**Data:** 2026-09-13 · **Estado:** plano; o servidor ainda não existe
**Para quem:** a sessão do Claude que vai montar o servidor no Mac mini. Leia inteiro
antes de instalar — a Seção 3 muda o que parece "o plano padrão de um Ollama na rede".

---

## 1. De onde este documento vem

O **Ciclo Assist** é um painel dentro do Avid Media Composer, no notebook Windows do
editor. Três funções: identificar material visualmente, separar as falas de uma cena e
montar um primeiro corte a partir do roteiro.

⭐ **A inversão que define o produto:** não é o plugin que chama o Claude, é o Claude que
chama o plugin. Um serviço Python no notebook (`127.0.0.1:7824`) expõe ferramentas MCP;
o `claude -p` roda como subprocesso com a **assinatura do editor** e chama essas
ferramentas. Quem paga o modelo é o editor, não nós (ADR 0001).

Na noite de 2026-09-12 o Haiku montou uma cena inteira por ~5% da janela, e isso reabriu a
pergunta do modelo local. Ela foi testada **no notebook** e a resposta foi física:

| medido no notebook (RTX 4050 6 GB, 16 GB RAM, Media Composer aberto) | |
|---|---|
| **telas azuis** rodando modelo local ao lado do MC | **repetidas** — a última em 2026-09-13, com o `gemma3:4b` carregando |
| `qwen2.5vl:7b` (6,7 GB) — onde rodou | **51% CPU / 49% GPU** (não coube na VRAM) |
| primeira mídia com esse modelo | **estourou 600 s** |
| `gemma3:4b` | derrubou a máquina antes de responder |

⇒ **Decisão do editor, 2026-09-13: modelo local nunca mais no notebook.** Tudo o que for
inferência local mora no Mac mini, acessado pela rede. O notebook é do Media Composer.

---

## 2. A estratégia: quem faz o quê

| trabalho | quem | por quê |
|---|---|---|
| conversar com o editor, montar com roteiro, decidir, **escrever no projeto** | **Claude** (assinatura, no notebook) | é o julgamento. E toda escrita passa pelo portão: o editor lê um cartão e clica (ADR 0008) |
| **decupagem visual em lote** (olhar 6 quadros, preencher 5 campos fechados) | ⭐ **Mac** — primeiro candidato | é a única coisa que gasta a assinatura sem o editor pedir |
| transcrição melhor (Whisper large-v3-turbo) | Mac — depois | hoje é `small-int8` em CPU no notebook |
| busca **texto → imagem** (SigLIP/CLIP) | Mac — depois | fecha o maior buraco da busca (Seção 2.2) |
| mover item de bin, operações mecânicas | **nenhum modelo** | é função de dois argumentos, já medida; um botão faz por zero token |

### 2.1 Por que a decupagem vai primeiro — e não pelo dólar

Medido em 2026-09-11 (Haiku 4.5, 6 quadros por mídia, 3 mídias por turno): **16.818
tokens, US$ 0,015 e ~10 s por mídia**. O projeto de teste tem 165 mídias com imagem:
**US$ 2,48**.

O dólar é pequeno. **A janela não:** 165 mídias são **2,8 milhões de tokens** caindo no
mesmo balde de 5 horas que a montagem do editor usa. Decupar o acervo custa a tarde de
edição que vem depois.

E há o argumento que não é custo: `docs/ameacas.md` trata como **risco nº 1** o material do
cliente ir para a nuvem. Para material embargado, tela de consentimento não resolve — o
cliente não instala. Percepção local é a única resposta para *"o meu material não sai
daqui"*.

### 2.2 As três camadas visuais (alinhe com o relatório "IA local e técnicas dos editores")

O relatório do Premiere/Resolve está certo, e cruza assim com o que existe aqui:

| camada | responde | onde | estado |
|---|---|---|---|
| vetor **imagem→imagem** (MobileNetV2, ONNX, 14 MB) | "parecido com este quadro" | notebook | ✅ em produção — **fica** |
| decupagem (VLM escrevendo) | "close noturno no consultório", com julgamento | Claude hoje → Mac | medindo |
| vetor **texto→imagem** (SigLIP/CLIP) | a mesma pergunta, **sem ninguém ter olhado antes** | Mac | por fazer |

⚠️ Nosso MobileNetV2 venceu o CLIP **por medida** — mas na pergunta *imagem→imagem*
(99% contra 38% ao acaso). Ele **não tem codificador de texto**; a busca por frase nele não
é pior, é impossível. Hoje a busca responde *"3 mídias decupadas de 23"* porque só alcança
o que alguém já olhou. É isso que o CLIP apaga. Uma camada não substitui a outra: é o
*retrieve-then-rerank* do relatório.

---

## 3. ⛔⛔ Decisão de arquitetura: o Mac é um BACKEND HTTP, não um servidor MCP

O relatório sugere expor as ferramentas do Mac como MCP para o Claude chamá-las direto.
**Não faça isso.** O Mac fala HTTP com o **serviço do notebook**, e o Claude nunca sabe
que o Mac existe:

```
┌──────────── notebook Windows ─────────────┐           ┌──────── Mac mini M4 ────────┐
│ Media Composer                             │           │                             │
│ serviço Ciclo Assist  127.0.0.1:7824       │           │ Ollama   0.0.0.0:11434      │
│   ├─ MCP (rota com segredo por arranque)   │ ── HTTP ─→│  (depois: whisper, SigLIP)  │
│   ├─ valida, carimba procedência, grava    │ ←─ JSON ──│                             │
│   └─ cache por UMID                        │           │ não guarda nada do cliente  │
│ claude -p  (assinatura do editor)          │           │ não chama o notebook        │
└────────────────────────────────────────────┘           └─────────────────────────────┘
```

Por quê, peça por peça — cada uma já custou erro aqui:

1. **Um porteiro só.** A rota MCP é `/mcp/<segredo>`, sorteado a cada arranque, e o CLI
   roda com `--strict-mcp-config` — sem ela a sessão herdou **35 ferramentas** da conta
   pessoal do editor (Gmail, Drive). Um segundo servidor MCP na rede é superfície nova.
2. **O que a ferramenta devolve é orçamento.** 12 de 14 transcrições estouraram o limite
   de saída do CLI até termos paginação e teto (`ORCAMENTO_CHARS`). Resultado cru do Mac
   direto no modelo reabre isso.
3. **Procedência.** Todo item carrega `confianca` / `fonte` / `medida`, carimbados pelo
   serviço. *Item sem procedência é bug, não item.*
4. **O modelo não escreve.** Na decupagem, o modelo responde JSON e **o serviço** valida
   pelo vocabulário fechado e grava. *Chave que ninguém pediu não vira nota* — gravaria
   decupagem na mídia errada e ninguém descobriria.
5. **O cache é do notebook**, endereçado pelo UMID do master. O Mac não guarda quadro,
   áudio nem nota de cliente.

⇒ **Direção única: notebook → Mac.** O Mac nunca abre conexão para o notebook e nunca
monta o compartilhamento de mídia do Avid: quadros e áudio vão **no corpo do pedido**.

---

## 4. As fases no Mac, com o critério de passagem de cada uma

Critério combinado **antes** de medir — critério escolhido depois do número não é critério.

### M0 — O Ollama alcançável da rede

Passa quando, **do notebook**:

```powershell
curl.exe http://<IP-do-Mac>:11434/api/version
curl.exe http://<IP-do-Mac>:11434/api/tags
```

⚠️ No PowerShell 5.1, `curl` é apelido de `Invoke-WebRequest`. Use **`curl.exe`**, ou
`Test-NetConnection <IP> -Port 11434` para só saber se a porta abre.

### M1 — Decupagem: o modelo local acerta o que o Haiku acertou?

```powershell
python spikes/o_modelo_local_decupa.py --ollama http://<IP-do-Mac>:11434 --modelo qwen2.5vl:7b
python spikes/o_modelo_local_decupa.py --ollama http://<IP-do-Mac>:11434 --modelo gemma3:4b
```

O spike manda os **mesmos 6 quadros** que o Claude recebeu e passa a resposta pela
**mesma validação** do produto. Compara os 5 campos fechados contra o gabarito do Haiku.

- ✅ **≥ 70%** dos campos e **nenhum valor fora do vocabulário** → a decupagem em lote vai
  para o Mac.
- ⛔ **< 50%** → o ADR 0001 estava certo; o assunto fecha com medida.
- Entre os dois → ampliar o gabarito antes de decidir.

⚠️ O gabarito hoje é **7 mídias / 29 campos** (cada campo vale 3,4 pontos): serve para
reprovar, não para aprovar com confiança. A única medida feita até agora é **n = 1**:
4 de 5 campos, 0 inventados, 45 s — **não é resultado**, é prova de que o transporte
funciona.

⚠️ O `gemma3:4b` é o **controle**: sem um segundo modelo, 60% não se distingue de "a
tarefa é difícil".

### M2 — O `claude -p` inteiro contra o Mac (a medida de maior alavanca)

⭐⭐ **Medido em 2026-09-12:** o Ollama 0.33.3 expõe **`/v1/messages`, o protocolo da
Anthropic**, com erro no formato dela (`request_id`, `invalid_request_error`). Não é stub.

Se o CLI aceitar `ANTHROPIC_BASE_URL` apontando para o Mac, o produto mantém **tudo** — o
portão, o `--resume`, o MCP local, o `stream-json`, o `--restricted`. O motor local deixa
de ser ~1.200 linhas reimplementadas e vira variável de ambiente. O CLI continua rodando
**no notebook**; só a inferência vai para o Mac, e as ferramentas continuam sendo chamadas
em `127.0.0.1`. A direção única da Seção 3 se mantém.

O que o Mac precisa ter para esta fase, e **é diferente da M1**:

- ⛔ **Um modelo com `tools`.** O `qwen2.5vl:7b` se declarou `['completion', 'vision']` —
  **sem tools**. Para M2 é outro modelo (Qwen3 ~8B, ou o que `/api/show` confirmar com
  `tools` nas capacidades).
- ⛔⛔ **Contexto do SERVIDOR grande.** Na M1 o nosso cliente manda `num_ctx` por pedido.
  **Na M2 quem pede é o CLI, e ele não manda.** Vale o padrão do servidor — e o piso
  medido de um turno do `claude -p` é **~40 mil tokens** (prompt de sistema + maquinaria).
  Com o padrão de 4096, o prompt seria cortado e o modelo perderia as ferramentas: o
  sintoma seria "o modelo local é burro", e o defeito seria o balde.

Passa quando: `claude -p "liste as bins do projeto"` contra o Mac chama a ferramenta certa,
o portão aparece numa escrita, e a resposta chega sem truncamento. ⚠️ Perde-se no painel:
`costUSD`, `contextWindow` e os eventos de limite — os avisos que existem para a janela da
assinatura. Isto vira ADR antes de virar produto.

✅ **M2 PASSOU em 2026-09-16** (`spikes/o_ollama_como_motor.py`, CLI 2.1.273,
`qwen3-vl:8b-instruct`): tool call de leitura, portão chamado com `deny` respeitado, turno
de ~11 mil tokens contra 40.960 carregados. Detalhe no banco,
`transversal/cli-do-modelo-como-motor.md` §10.5. ⚠️ O piso de ~40 mil acima estava errado
para o nosso comando: com `--tools ""` são ~11 mil.

Entrou no painel **como opção de avaliação** (`🖥 Qwen3-VL (Mac)` no seletor de modelo,
só com o Mac configurado): `config.MODELOS_LOCAIS`, `claude.ambiente_do_modelo`. Trocar
entre Claude e Mac abre conversa nova. Barra: janela do `/api/ps`, sem dólar.
⚠️ Ainda falta: a tarefa real (separar falas da C07) pelo painel, comparada com o Haiku;
o ADR, se a resposta servir. ⚠️ O 8B diz "foi salva" depois de um `deny`.

### M3 — Whisper large-v3-turbo · M4 — busca texto→imagem

Depois de M1/M2. Duas notas para não surpreender:

- M3 **invalida as transcrições em cache** (o modelo entra na assinatura do cache) — é
  reprocessar tudo, dito ao editor antes.
- M4 amostra os **mesmos 12 quadros por master** que a vetorização já guarda; o Mac
  recebe os JPEG e devolve vetores. O índice mora no notebook, ao lado do resto.

---

## 5. Configurar o Ollama no Mac

### 5.1 Variáveis

| variável | valor | por quê |
|---|---|---|
| `OLLAMA_HOST` | `0.0.0.0:11434` | ⛔ o padrão é `127.0.0.1`: **funciona no Mac e some da rede** |
| `OLLAMA_MODELS` | pasta no SSD externo | disco interno com pouco espaço (plano do editor) |
| `OLLAMA_KEEP_ALIVE` | `30m` | medido: primeira mídia **151 s** (carregando), seguintes **45 s**. Descarregar entre mídias paga a carga toda vez |
| `OLLAMA_MAX_LOADED_MODELS` | `1` | 16 GB: VLM (~6–7 GB) e LLM de texto **não convivem** |
| `OLLAMA_NUM_PARALLEL` | `1` | a fila do notebook já é uma tarefa por vez; paralelo só multiplica KV cache |
| `OLLAMA_FLASH_ATTENTION` | `1` | pré-requisito do cache de contexto quantizado |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | metade da memória de contexto; é o que torna M2 viável em 16 GB |
| `OLLAMA_CONTEXT_LENGTH` | `32768` ou mais (conferir na versão) | ⛔ **o padrão é 4096** — ver 5.3. Decisivo para M2 |
| `OLLAMA_ORIGINS` | **não definir** | é CORS para navegador. Quem chama é Python no notebook; o painel **nunca** fala com o Mac |

⚠️ **No macOS, o app do Ollama (ícone na barra) ignora variáveis do shell.** Duas saídas,
escolha **uma**:

- **(a) recomendada, casa com os scripts `iniciar`/`parar`/`status` do plano:** o script
  exporta as variáveis e roda `ollama serve`. E **tire o app do Ollama dos itens de
  login** — senão ele sobe primeiro no boot, ocupa a 11434 em `127.0.0.1`, e o
  `ollama serve` do script falha com "address already in use" enquanto o notebook não
  alcança nada.
- **(b)** usar o app, com `launchctl setenv OLLAMA_HOST "0.0.0.0:11434"` (e as demais) e
  reiniciar o app. ⚠️ `launchctl setenv` **não sobrevive a reboot**.

⚠️ Lição do notebook que vale aqui: **dois servidores e uma porta produzem sintoma
enganoso.** Em 2026-09-12 o serviço do notebook ficou com dois processos na mesma porta e
o velho respondendo tudo. No macOS o segundo bind falha de verdade — mas só se alguém ler a
saída do script.

### 5.2 O Mac não pode dormir, e o SSD não pode sumir

- Energia: impedir suspensão (`sudo pmset -a sleep 0 disksleep 0`; conferir com
  `pmset -g`). Mac dormindo = o notebook esperando o prazo inteiro por mídia.
- ⚠️ **SSD externo desmontado = Ollama sobe com a pasta de modelos vazia.** `/api/tags`
  volta lista vazia e o notebook recebe *"o Ollama não tem 'qwen2.5vl:7b'"* — que parece
  modelo apagado. O `iniciar` deve **recusar subir** se o volume não estiver montado.
- Firewall do macOS: na primeira execução ele pergunta se o `ollama` aceita conexões.
  Negado (ou ignorado), o notebook vê só **timeout**, sem erro nenhum.

### 5.3 ⛔⛔ Armadilhas medidas no notebook que valem igual no Mac

1. **Contexto padrão de 4096.** Seis quadros são **6.229 tokens** → `400` com
   `exceed_context_size_error`. Quem não souber conclui que o modelo não dá conta.
2. **Modelo sem visão: confira antes de mandar.** Dos 5 modelos que havia no notebook,
   **nenhum** via imagem. O que um deles faz ao receber imagem **não foi medido** — o spike
   recusa antes. A suposição (`hipotese`) é que aceita calado e inventa uma decupagem
   plausível, e é justamente por isso que a conferência vem primeiro: `/api/show` →
   `capabilities` contém `vision`.
3. **O VLM copia o placeholder.** Com o prompt de envelope `{"<chave da mídia>": {...}}`,
   o `qwen2.5vl:7b` devolveu a chave **literal** `"<chave da mídia>"`. ⇒ Uma mídia por
   pedido, resposta **plana**. (O envelope só existia para amortizar o piso de 40 mil
   tokens do CLI; o Ollama não tem piso.)
4. **O VLM responde um objeto por quadro.** Mesmo com o cabeçalho *"6 quadros da mídia X,
   em ordem"*, veio um **array de seis decupagens**. Precisou de instrução explícita: *"os
   quadros são do MESMO plano; responda UM único objeto"*.
5. **`temperature: 0`** em medição: com amostragem, duas rodadas dão dois placares.

---

## 6. A rede

- **IP fixo por reserva de DHCP no roteador.** `mac-mini.local` (Bonjour) costuma
  resolver no Windows 11, mas falha em redes com isolamento de cliente e fica lento em
  outras. O notebook guarda a URL; o nome `.local` é conveniência, o IP é o contrato.
  No Mac: `ipconfig getifaddr en0` (cabo) / `en1` (Wi-Fi).
- **Cabo nos dois, se der.** Banda não é o problema (6 quadros ≈ 240 KB em base64 por
  mídia); estabilidade é. Uma queda de Wi-Fi no meio de um lote parece modelo travado.
- ⛔ **O Ollama não tem autenticação.** Só rede confiável. **Nunca** redirecionar a porta
  no roteador, nunca rede de convidados. Um proxy com senha à frente é aceitável, mas muda
  o contrato do nosso cliente — **combine antes**.
- ⚠️ Quando isto entrar no produto, a URL do Mac vai para o `config.json` pela tela de
  configurações — e o serviço **não** vai chamar qualquer endereço que a página mandar
  (seria a página escolhendo para onde o serviço faz requisição, ADR 0005). Faixa privada
  / `.local` apenas, e é tema de ADR.

---

## 7. O contrato que o notebook usa

O Mac não precisa implementar nada além do Ollama. Estes são os pedidos que ele vai
receber; **não mude portas, nomes de modelo ou formato sem avisar este lado**.

| pedido | para quê |
|---|---|
| `GET  /api/version` | saúde; entra no diagnóstico |
| `GET  /api/tags` | quais modelos existem — **o nome exato (tag) é contrato** |
| `POST /api/show` `{"model": …}` | `capabilities`: `vision` (M1), `tools` (M2) |
| `POST /api/chat` | a decupagem (M1) |
| `POST /v1/messages` | o CLI inteiro (M2) |

O pedido da decupagem, como sai do notebook:

```json
{
  "model": "qwen2.5vl:7b",
  "stream": false,
  "options": {"temperature": 0, "num_ctx": 12288},
  "messages": [
    {"role": "system", "content": "<persona do decupador, com o vocabulário fechado>"},
    {"role": "user",
     "content": "6 quadro(s) da mídia <nome>, duração <s>s.\nOs quadros estão em ordem, nos segundos <s1>, <s2>, …\n\nDecupe esta mídia.",
     "images": ["<jpeg base64>", "…6 no total"]}
  ]
}
```

O que o notebook lê da resposta: `message.content` (um objeto JSON plano),
`prompt_eval_count`, `eval_count` e o tempo de parede. O vocabulário fechado:

| campo | valores |
|---|---|
| `enquadramento` | geral · conjunto · médio · americano · close · detalhe |
| `angulo` | normal · plongée · contra-plongée |
| `camera` | parada · pan · tilt · travelling · mão · zoom |
| `local` | interior · exterior |
| `momento` | dia · noite |

⚠️ Campo que o modelo não sabe **fica fora** — omitir é permitido, inventar não. Valor
fora da lista é descartado pelo serviço com aviso.

⚠️ **Prazo:** o notebook espera até 300 s por mídia (a primeira inclui carregar o modelo).
Se o Mac for mais lento que isso com o modelo quente, o número importa mais que o prazo —
nos diga.

---

## 8. O que o script `status` deveria mostrar

Não "está rodando". O que responde as falhas acima:

```
versão do ollama ........ 0.xx
escutando em ............ 0.0.0.0:11434      ← 127.0.0.1 aqui = invisível na rede
IP na rede .............. 192.168.x.y (en0)
teste pelo IP da rede ... ok                 ← curl no IP, NÃO em localhost
volume dos modelos ...... montado · N GB livres
modelos ................. qwen2.5vl:7b [vision] · gemma3:4b [vision] · <texto> [tools]
carregado agora ......... qwen2.5vl:7b · 100% GPU · ctx 12288 · até 00:41
pressão de memória ...... normal
suspensão ............... desligada
```

⭐ **"teste pelo IP da rede"** é a linha que vale o script: `curl localhost` passa com o
servidor preso em `127.0.0.1`, e é exatamente essa a falha que só aparece do notebook.
E **PROCESSOR 100% GPU** no `ollama ps` é a confirmação de que o modelo coube — no
notebook estava **51/49**, e é daí que veio tudo.

---

## 9. O que a sessão do Mac NÃO deve fazer

- Não expor MCP para o Claude (Seção 3).
- Não montar compartilhamento de mídia do Avid nem gravar material de cliente.
- Não usar modelo sem `vision` para decupagem, nem sem `tools` para M2.
- Não rodar LLM de texto e VLM ao mesmo tempo. MoE ~30B e `gpt-oss-20b` não cabem de forma
  estável em 16 GB (plano do editor).
- Não abrir a porta para fora da rede local.
- Não trocar a tag de um modelo em uso (`qwen2.5vl:7b` → outro nome) sem avisar: o notebook
  pede por nome.

---

## 10. O que devolver para o notebook quando M0 estiver pronto

1. O **IP** reservado e se é cabo ou Wi-Fi.
2. A saída do **`status`** (Seção 8).
3. `ollama --version` e a lista de **tags** instaladas com as capacidades de cada uma.
4. Se `OLLAMA_CONTEXT_LENGTH` existe na versão instalada, e o valor que ficou.
5. Qualquer coisa que tenha falhado e como apareceu — o sintoma exato vale mais que o
   conserto.

Daqui, o próximo passo é rodar M1 com esse IP.

---

## ⭐ Resultado da M1 (2026-09-13, Mac mini, Ollama 0.33.3, 7 mídias / 29 campos)

| modelo | acerto | inventados | não viraram nota | s/mídia (mediana) |
|---|---|---|---|---|
| `qwen3-vl:8b-instruct` | **90%** (26/29) | 0 | 0 | 62 |
| `qwen2.5vl:7b` | **86%** (25/29) | 0 | 0 | 59 |
| `gemma3:4b` (controle) | **79%** (23/29) | 0 | 0 | 26 |

⇒ Pelo critério combinado antes (≥ 70% e nada inventado), **os três passam**. ⚠️ Mas o
controle passar diz que este gabarito **discrimina pouco**: quase todo erro está em
`enquadramento` (o gemma responde `médio` para tudo e troca `dia` por `noite` duas vezes),
e `local`/`angulo` acertam em todos. Os 12 campos `+` (o modelo local preencheu o que o
Haiku omitiu) não entram no placar e **não foram conferidos**. A prosa também não.
⚠️ Tempo: ~60 s por mídia contra ~10 s do Haiku — 165 mídias são ~2 h 45 no Mac.

## ⭐ A decupagem em lote foi para o Mac (2026-09-13, noite)

Decisão do editor. `cicloassist/motor/percepcao.py` + a fila de `rotas.py`: com `ollama`
no `config.json`, o botão "Decupar a imagem" manda uma mídia por pedido ao
`qwen3-vl:8b-instruct`. Primeira mídia real pelo serviço: **68 s** (frio), 6.723 tokens de
entrada, 142 de saída, nota com os 5 campos. Soltas as outras **164** em seguida (~2 h 50
estimadas). ⬜ Conferir de manhã: `feitas`/`falharam` no andamento e uma amostra das notas.

## Medidas que sustentam este documento

| medida | valor | quando | onde |
|---|---|---|---|
| decupagem pelo Claude (Haiku 4.5, 3 por turno) | 16.818 tokens · US$ 0,015 · ~10 s por mídia | 2026-09-11 | `motor/decupador.py` |
| piso de um turno do `claude -p` | ~40 mil tokens | 2026-09-11 | idem |
| notebook: telas azuis com modelo local + MC | repetidas; a última com `gemma3:4b` | 2026-09-13 | relato do editor |
| `qwen2.5vl:7b` na RTX 4050 | 6,7 GB · 51% CPU / 49% GPU · timeout 600 s | 2026-09-12 | `spikes/o_modelo_local_decupa.py` |
| 6 quadros no Ollama | 6.229 tokens de prompt; padrão 4096 recusa | 2026-09-12 | idem |
| primeira mídia fria / quente | 151 s / 45 s | 2026-09-12 | idem |
| placar parcial (n = 1) | 4 de 5 campos · 0 inventados | 2026-09-12 | idem — **não é resultado** |
| gabarito utilizável | 7 mídias · 29 campos | 2026-09-12 | idem |
| Ollama 0.33.3 expõe `/v1/messages` | sim, formato Anthropic | 2026-09-12 | endpoint existe; **CLI não testado** |
| ASR atual | `faster-whisper` `small-int8`, CPU, 243 MB | — | `midia/asr.py` |
