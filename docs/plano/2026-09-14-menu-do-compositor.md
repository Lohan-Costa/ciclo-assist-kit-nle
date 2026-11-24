# Menu de ações do chat: comandos fixos e atalhos de prompt

> **Estado: PARCIAL** (2026-10-21, pedido do autor para a demo de sexta). Feito: o módulo e o arquivo
> `atalhos.json` (§2), `GET /atalhos`, `/atalhos/salvar`, `/atalhos/tirar`, o menu ☰ com a lista, preencher sem
> enviar, tirar, "Salvar como atalho…" (§5) e "Limpar conversa" — `tests/test_atalhos.py`, e VISTO na janela do app
> (aba Assistir) com os dois prompts da demo. ⬜ Falta: "Retomar a última conversa" (§3) e "Carregar prompt de
> arquivo" (§4, seletor e drop no menu). Até lá, um atalho novo nasce de uma pergunta, ou editando o `atalhos.json`
> à mão (lista crua de `{"apelido", "texto"}` também vale).

## Contexto

Hoje o painel não tem por onde acionar nada além de escrever uma pergunta. Limpar a conversa
só acontece se o editor **digitar** `/clear` (`painel.js:1014`) ou se o aviso de fio continuado
aparecer com o botão "começar do zero" (`painel.js:2460-2478`). E a conversa que a decisão de
2026-09-14 passou a jogar fora a cada visita **não tem volta**: o `--resume` existe no CLI, mas
`sessao.recomecar()` descarta o id do fio anterior no mesmo gesto que o substitui
(`motor/sessao.py:232-258, 528-554`) — a frase "quem quiser a conversa de antes pede" não tem
hoje a quem pedir. O `CLAUDE.md` registra isso como `⬜ Falta a válvula`.

Ao mesmo tempo, parte do trabalho é previsível — "separe as falas da cena…", "monte a cena
pelo roteiro…" — e é redigitada toda vez.

O editor pediu um **menu sanduíche (☰) à esquerda da caixa de texto**, com comandos fixos
embaixo (limpar, retomar a conversa anterior), uma divisória, e acima a lista de **atalhos de
prompt**, guardados por apelido. Com duas entradas para criar atalho: carregar de um arquivo
(`.md`/`.txt`/`.json`) e salvar a última pergunta.

Decisões dele, já tomadas:

1. Clicar num atalho **preenche o textarea** (foco no fim), não envia — nada é gasto até ele
   apertar enviar, e assim ele pode arrastar a bin antes.
2. Carregar prompt funciona **pelos dois caminhos**: arrastar o arquivo e o seletor do sistema.
3. Atalhos valem para **todos os projetos** (lista da máquina).
4. Ao salvar, o texto é **editável** antes de virar atalho, e **MobID e caminhos de arquivo
   jamais entram** — um atalho que aponta clipe de outro projeto é pior que nenhum.

---

## 1. O menu — o primeiro componente flutuante deste painel

⚠️ Não existe popover nenhum no painel hoje: o maior `z-index` do CSS é 3 (sticky da tabela de
vetores, `painel.css:513`) e o único fora do fluxo é `body.recebendo::after`. Tudo que "abre"
hoje é inline (`dataset.aberto`, `aria-expanded` + glifo ▾/▸).

### O botão, dentro do compositor

`index.html:228-258`, **entre `<div class="anexos">` (239) e `<textarea id="entrada">` (240)** —
a ordem é layout, porque o form é `display:flex; flex-wrap:wrap; align-items:flex-end`
(`painel.css:1016-1030`) e os anexos usam `flex-basis:100%` para tomar a linha inteira.

- `<button type="button" id="abrirMenu" aria-haspopup="menu" aria-expanded="false"
  aria-controls="menuPop" aria-label="Ações e atalhos">` com SVG de três traços (o painel usa
  SVG inline em tudo; `☰` como texto varia de fonte para fonte).
- Caixa de 32×32 como o `#enviar`, mas `background: transparent; color: var(--tinta-2);
  border: 1px solid var(--linha)` — ele não é a ação principal e não pode competir com o botão
  pintado de `--realce`.
- ⛔ Conta de largura no pior caso (painel a 340 px, `#pararConversa` visível): 24 de padding +
  3×7 de gap + 32+32+32 = 141 px; sobram 199 para o `#entrada`, bem acima do `min-width:120px`
  marcado como intocável. Não é preciso tocar em `#entrada` nem em `.compositor`.

### ⛔⛔ O popover fica FORA do `<form>`

`<div class="menu-pop" id="menuPop" hidden>` entra como **irmão do `<form class="compositor">`,
depois dele**. O motivo é duro: o form tem um `submit` que ENVIA A PERGUNTA, e a tela de salvar
atalho (item 5) tem um `<input type="text">` para o apelido — **um form com um único campo de
texto submete no Enter**. O editor digitaria o apelido, apertaria Enter, e o painel mandaria a
pergunta que estava na caixa. Modo de falha silencioso e caro; desaparece inteiro tirando o pop
do form.

Preço: posicionar em JS. `position: fixed` com as coordenadas do `getBoundingClientRect()` do
`#abrirMenu` na abertura — e isso resolve de uma vez os dois riscos de recorte (`body` é
`overflow:hidden`, `painel.css:69`; `.conversa` é `overflow-y:auto`). É a técnica do único
`position:fixed` que já existe no painel.

```
left   = max(8, r.left)
bottom = window.innerHeight - r.top + 6      /* abre PARA CIMA: o compositor é o rodapé */
width  = min(400, window.innerWidth - 16)
max-height: 60vh; overflow-y: auto; z-index: 20
```

Abrir/fechar por `el.hidden` (a regra `[hidden]{display:none!important}`, `painel.css:55`, já
ganha de qualquer `display`, e o teste dela já existe).

### Conteúdo, de cima para baixo

```
┌──────────────────────────────┐
│ Separar falas da cena      × │  ← atalhos (TETO_DE_ATALHOS = 12)
│ Montar pelo roteiro        × │
├──────────────────────────────┤
│ Carregar prompt de arquivo…  │
│ Salvar como atalho…          │
├──────────────────────────────┤
│ Retomar a última conversa    │  ← com o peso: "7 turnos, ~121 mil tokens"
│ Limpar conversa              │  ← .perigo, pergunta em si mesmo
└──────────────────────────────┘
```

- Os fixos ficam **embaixo** (pedido do editor) — e, como o menu abre para cima, é onde o dedo
  já está.
- ⛔ O `×` de cada atalho **não pode ser `<button>` dentro de `<button>`** (o Chromium desmonta
  o aninhamento): cada linha é um `<div role="none">` com dois botões irmãos, o mesmo desenho do
  chip `.anexo` com o `.tirar` (`painel.js:2296-2308`).
- Cada atalho mostra **só o apelido** (decisão do editor) e leva o texto no `title`.
- Lista vazia: um `.menu-vazio` explicando como criar o primeiro — nunca um espaço mudo.
- "Limpar conversa" segue o padrão da casa (⛔ nada de `confirm()`, que trava a webview do MC):
  primeiro clique vira "Limpar mesmo?", ganha `.armado`, `setTimeout(desarmar, 6000)`, e **o
  menu não fecha no primeiro clique**. A ação reusa `limparAConversa()` como está.

### Abrir, fechar, foco

Fecha em quatro caminhos: escolher um item; `Escape` (devolve o foco ao botão); clique fora (UM
ouvinte permanente no `document`, na **bolha**, guardado por `if (menuPop.hidden) return;` e por
`contains()` — a captura é reservada ao arrasto, e o próprio clique que abre não fecha porque o
`#abrirMenu` está no teste); e contexto mudado — `fecharOMenu()` no topo de `mostrarTela()`
(`painel.js:1110`), no `focus`/`input` do `#entrada` (senão o compositor cresce e o pop
desalinha) e reposicionar no `resize` (o editor arrasta a borda entre 340 e 440 px).

Ao abrir, foco no primeiro `[role="menuitem"]`. ⬜ Navegação por setas fica de fora da v1 — Tab
já anda, porque os itens são botões de verdade.

---

## 2. Onde os atalhos moram

⭐ **Arquivo próprio: `atalhos.json`, na pasta de `config.pasta()`**, ao lado do `config.json` e
do `estado.json`, com módulo novo `cicloassist/servico/atalhos.py` (no espírito de
`arrastados.py`).

Por que não nos dois que já existem: `config.json` tem lista fechada e escalar
(`CHAVES = ("cache","modelo","auto","ollama")`, e `ler()` descarta o resto — um `atalhos` lá
sumiria em silêncio); `estado.json` é declaradamente "memória interna do produto"
(`config.py:140-145`), e atalho é **texto que o editor escreveu**, que ele vai querer abrir,
editar à mão e levar para a outra máquina. E é o mesmo formato do `.json` que ele pode carregar
— então **exportar é copiar o arquivo**.
_(Alternativa considerada: `estado.json["atalhos"]`, seguindo `pastas_de_midia`. Reusaria
`gravar_estado`, mas herda a doutrina errada e não serve de formato de troca.)_

```jsonc
{ "atalhos": [
  { "id": "9f3c1a7b",
    "apelido": "Separar falas da cena",
    "texto": "Separe as falas desta cena…",
    "criado_em": 1789400000,
    "de": "pergunta",            // "pergunta" | "arquivo" | "digitado" — procedência
    "arquivo": "prompt-falas.md" // ⛔ só Path(x).name, NUNCA o caminho
  }
]}
```

Limites, no módulo e não na rota:

```
TETO_DE_ATALHOS = 12      # "para não virar algo gigante"
TETO_DO_TEXTO   = 8000    # caracteres — acima disso é documento, e documento se ARRASTA
TETO_DO_APELIDO = 40      # o que cabe em 400 px
PROMPT = {".md", ".txt", ".json"}
```

- Arquivo ilegível vira lista vazia, item torto é descartado, **nunca exceção** (doutrina do
  cache e do `config.ler()`).
- Apelido vazio nasce da primeira linha do texto (quebras viram espaço, corte em 40 com
  reticência); repetido ganha sufixo `" (2)"` — dois itens com o mesmo nome tornam o menu inútil.
- ⛔ **Lista cheia RECUSA com o número; nunca descarta o mais velho em silêncio.** Perder texto
  que o editor escreveu é a classe de falha que este repo trata como inaceitável.
- ⛔ `Path(arquivo).name`: guardar caminho faria nascer uma lista durável de caminhos de disco
  fora da lista de `arrastados` (ADR 0005) — e um atalho que aponta arquivo de outra máquina é
  pior que nenhum.

**Rotas novas** (caminho EXATO, porteiro padrão do painel):

| método | caminho | corpo | devolve |
|---|---|---|---|
| GET | `/atalhos` | — | `{ok, atalhos, anteriores, teto, teto_do_texto}` |
| POST | `/atalhos/salvar` | `{apelido, texto, de, arquivo}` | `{ok, atalhos, erro}` |
| POST | `/atalhos/tirar` | `{id}` | `{ok, atalhos}` |
| POST | `/atalhos/carregar` | `{}` ou `{caminho}` | `{ok, texto, nome, importados, atalhos, aviso}` |
| POST | `/retomar` | `{}` | ver item 3 |

- `GET /atalhos` leva `anteriores` junto **de propósito**: o menu abre num gesto, e duas idas ao
  serviço fazem a lista piscar na webview.
- ⚠️ **Toda rota que grava devolve a lista RELIDA do disco.** Motivo concreto: `gravar_estado`
  engole `OSError` e só loga (`config.py:161-173`) — uma gravação que falhou responde "ok" hoje.
  Relendo, um atalho que não aparece é o sintoma honesto.
- Recusas em 400 **com o número na frase**: *"você já tem 12 atalhos; tire um antes de salvar
  outro"* é acionável, "erro ao salvar" não é.
- `PRECISO_DE` (`painel.js:41-46`) ganha as cinco rotas, e o teste que já existe
  (`tests/test_servico.py:190`) passa a cobri-las de graça — um serviço velho com a tela nova
  acusa na partida em vez de responder "rota desconhecida" no clique.

---

## 3. Retomar a última conversa

**Em `motor/sessao.py`**, chave nova em `estado.json`:

```json
"fios_anteriores": { "<chave do projeto>": [
  {"id":"…","em":1789…,"turnos":7,"contexto":121000,"fracao":0.6,"modelo":"claude-sonnet-5"}
]}
```

- `_empilhar_anterior(chave, id_antigo)` nos **dois** pontos que hoje jogam o id fora
  (`Sessao.recomecar()` e `recomecar()` do módulo), lendo o peso de `ler_estado()["fio"]`.
  **Só empilha se houver `turnos` ou `contexto`** — senão a pilha enche de fios vazios e o item
  oferece nada.
- `TETO_DE_FIOS_ANTERIORES = 5` por projeto, mais novo primeiro. Cinco e não um: cada troca de
  visita empilha, e uma reabertura acidental do MC apagaria o alvo.
- `retomar(caminho, id_)`: confere que o id **está na pilha daquele projeto** (⛔ id vindo da
  página não pode chegar a um `--resume`), empilha o fio atual se tiver peso, `_gravar_fio`, e
  mata a `Sessao` viva para o próximo turno subir com `--resume`.

**`POST /retomar`**, irmã de `/limpar`: recusa com turno em andamento (trocar o fio no meio
deixaria a resposta corrente num fio e a próxima em outro); chama `retomar`; grava o `fio` no
estado; devolve o peso.

⛔⛔ **O risco nº 1 do plano inteiro, e ele é 100% silencioso:** `_conversa_desta_visita()`
(`rotas.py:127-158`) roda antes de subir o CLI e joga o fio fora quando a visita não bate — e
`_visita_do_fio` nasce vazio a cada reinício do serviço. Sem marcar `_visita_do_fio[chave] =
_presenca.atual()` **dentro da rota `/retomar`**, o primeiro turno depois do clique joga fora
exatamente o fio que acabou de voltar, sem erro nenhum. Uma linha, com teste próprio.
⚠️ Isso não afrouxa a decisão de 2026-09-14: a visita nova continua limpando sozinha; o que
passa a existir é a válvula, e ela exige um pedido explícito.

⚠️ **E quando o `--resume` não encontra nada:** hoje o CLI responde `no conversation found` e a
sessão cai para `--session-id` seguindo em frente (`sessao.py:391-416`) — certo em geral, e
exatamente errado depois de um "retomar". Um flag `Sessao.pedido_de_retomar` faz o ramo emitir
*"a conversa anterior não está mais no histórico do Claude; comecei uma nova"* antes do
fallback. Segue criando (o editor já digitou a pergunta), mas **diz**.

**Na tela, sem mentir:** o item carrega o peso (*"7 turnos, ~121 mil tokens, hoje 14:32"*), e
sem pilha aparece desabilitado com o motivo escrito (`--tinta-3`, nunca `opacity`). Depois do
clique, um bloco de sistema: *"Vou retomar a conversa anterior na **próxima pergunta**. Ela só
volta de verdade quando o Claude responder — se o histórico dele já tiver sido apagado, eu aviso
aqui."* E chama `mostrarOFio()`, que já existe.

---

## 4. Carregar prompt de arquivo (os dois caminhos)

**a) Seletor do sistema** — não existe nada de escolher ARQUIVO no repo (só
`FolderBrowserDialog`/`choose folder`, `rotas.py:717-787`). `_arquivo_escolhido()` entra logo
abaixo de `_pasta_escolhida()`, copiando a estrutura inteira:

- **Windows:** PowerShell `-STA` (sem apartamento STA o `ShowDialog` levanta e o editor vê "não
  deu" sem motivo) com `System.Windows.Forms.OpenFileDialog`, `Filter` de `.md;.txt;.json`,
  `Multiselect = $false`, e o `Form` vazio `TopMost` como **dono** — sem ele o diálogo nasce
  atrás do Media Composer e parece travamento. Sem `&&`, sem `??`, sem ternário: o alvo é o
  PowerShell 5.1.
- **macOS:** `osascript` `choose file` com `activate`, pasta inicial por `argv` (nunca colada no
  script). ⛔ Cancelar sai com **erro −128** e a frase vem TRADUZIDA: decidir pelo **número**.
  ⚠️ **Sem `of type`**: em macOS moderno ele espera UTIs, o comportamento com extensões cruas é
  inconsistente e não há Mac nesta sessão para medir — a validação de sufixo fica do nosso lado,
  que precisa existir de qualquer jeito.
- ⭐ Escolher no seletor **autoriza** o arquivo (`_arrastados.autorizar`), como já faz
  `/vetores/pasta`: o gesto do editor é a permissão.

**b) Arrastado** — não mexer no arrasto existente (arrastar um `.md` hoje quer dizer "anexa o
roteiro", e sequestrar o gesto quebraria o que funciona). O que muda: **soltar sobre o menu
aberto** carrega como prompt. O `aoSoltar` (`painel.js:2380-2418`) já é ouvinte de **captura** no
documento, então basta olhar `e.target` no começo: `if (menuPop && !menuPop.hidden &&
menuPop.contains(e.target))`. Dali segue o `POST /arrastados` (que autoriza) e o
`/atalhos/carregar {caminho}`.

**O que a rota faz:**

1. Com `caminho`: **exige `arrastados.autorizado()`** — a rota nova não é uma porta nova para o
   disco (ADR 0005).
2. Sufixo em `atalhos.PROMPT` — **mais estreita que `arrastados.TEXTO`**, que tem `.docx`,
   `.srt`, `.edl`, `.fdx`: prompt é escrito por gente, o resto é material.
3. Tamanho: recusa pelo `st_size` **antes de ler** (`TETO_DO_TEXTO * 4`, por multibyte), depois
   confere os caracteres decodificados.
4. ⚠️ Decodificação: tira BOM, tenta `utf-8`, cai para `cp1252` com `errors="replace"` e um
   `aviso` no JSON. Um `.txt` do Bloco de Notas com acento derrubaria a rota com
   `UnicodeDecodeError`, que **não é** `OSError` nem `JSONDecodeError` e escapa do `except` óbvio.

**O `.json` aceita três formas** — `{"atalhos":[…]}` (canônica), lista crua, ou um objeto só:

- reconhecido → os itens são acrescentados respeitando o teto, e os excedentes vêm **recusados
  pelo nome** na resposta, nunca descartados calados;
- ⛔ não reconhecido → **não vira texto de prompt em silêncio**: *"este .json não tem
  apelido/texto; se ele é o texto do prompt, salve como .txt"*. Colar um JSON de configuração na
  caixa do editor sem explicação é o pior desfecho possível.
- `.md`/`.txt` → o texto vai para o `#entrada` e **não envia**: `ajustarAltura()`, `focus()`,
  `setSelectionRange(len, len)` nessa ordem (invertida, o textarea fica com uma linha). E a
  conversa oferece um "salvar como atalho" já com o nome do arquivo sugerido de apelido.

⭐⭐ **Regra da casa:** acrescentar a linha **"escolher arquivo"** em
`bancodedadosnles/transversal/matriz-de-plataforma.md` (seção F) **e no `.json` gêmeo**, com os
dois lados — Windows `confirmado` depois de rodar, macOS `pendente`.

---

## 5. Salvar a última pergunta como atalho

⭐ **A garantia da decisão 4 é ESTRUTURAL, não um filtro.** O texto que o painel tem em mãos
nunca contém anexo: o preâmbulo com MobID e caminho é montado no SERVIÇO
(`_preambulo_do_arrasto`, `rotas.py:422-455`) a partir do array `referencias`, que viaja separado
no corpo do `POST /conversar`. O que o painel guarda é o que o editor **digitou**.
Isso é melhor que um regex: um filtro que recusasse caminhos absolutos recusaria prompts
legítimos que citam uma letra de disco — recusar as palavras do editor é pior que o problema.

- `var ultimaPergunta = ""` preenchida em `enviarAgora()` (`painel.js:1040`), depois do desvio do
  `/clear` (comando não é pergunta). Fica na memória: um Reload repinta a conversa em branco, e
  uma "última pergunta" sobrevivente apontaria para uma tela que não mostra nada.
- Precedência do item: `entrada.value` se houver (cobre "carreguei um prompt e quero guardá-lo")
  → `ultimaPergunta` → **desabilitado com o motivo escrito** (item desabilitado e mudo se lê
  como quebrado).
- A edição acontece num **segundo modo do próprio popover** (`data-modo="forma"`): apelido
  (`maxlength=40`), texto (5 linhas, editável), Cancelar / Salvar. ⛔ Nada de `window.prompt`
  para o apelido — é diálogo nativo igual ao `confirm()` e trava a webview dentro do MC.
- Enter no apelido salva (e não envia pergunta nenhuma, porque o pop está fora do form).
- **Clicar num atalho:** se o `#entrada` estiver vazio, substitui; se tiver texto, **acrescenta
  depois de uma linha em branco** — nunca destruir o que o editor digitou.

---

## 6. Testes

**`tests/test_atalhos.py` (novo)** — o `conftest.py` já isola `CICLOASSIST_DADOS` no `tmp_path`:

ida e volta pelo disco · teto que recusa com o número (o 13º barrado, os 12 intactos) · texto
grande demais · apelido vazio nasce da primeira linha e é uma linha só · apelido repetido ganha
sufixo · arquivo ilegível vira lista vazia (string, lista de inteiros, item sem `texto`) ·
**o atalho não guarda caminho nenhum** (salvar com `D:\…\prompt.md` guarda `prompt.md`, e o
arquivo serializado não contém o caminho — é o teste da decisão 4) · tirar tira só aquele.

**`tests/test_servico.py`** — interface por regex, no estilo dos que já existem:

o botão está entre `#anexos` e `#entrada` dentro do form (a ordem é layout) · o botão declara
`aria-haspopup`/`aria-expanded`/`aria-controls` · **o `#menuPop` aparece DEPOIS do `</form>`**
(guarda a razão: Enter no apelido enviaria a pergunta) · **todo `<button>` do compositor que não
seja o `#enviar` tem `type="button"`** · o menu abre para cima (`bottom:`, não `top:`) e com
`z-index` > 3 · cabe em 340 px · fecha com `Escape` e com clique fora guardado por `contains` ·
**o atalho preenche e NÃO envia** (o trecho tem `entrada.value` e não tem `perguntar(`) ·
**o `fetch("/atalhos/salvar")` não menciona `referencias`, `mob_id` nem `caminho`** ·
**`painel.js` não chama `confirm|alert|prompt`** (hoje não chama, e `prompt()` é o atalho óbvio
de quem for escrever o campo de apelido).

E as rotas, chamadas direto (padrão do arquivo, sem servidor): devolve o que gravou · recusa
vazio e gigante com 400 · **carregar só lê o que foi autorizado** (ADR 0005) · recusa `.docx`
dizendo a lista · o `.json` nas três formas · `.json` desconhecido não vira prompt calado ·
`.txt` em cp1252 não derruba a rota · o seletor do Windows tem `-STA`, `TopMost` e
`ShowDialog($topo)` e nada de `&&`/`??` · o cancelar do Mac é decidido pelo **número** −128.

**`tests/test_sessao.py`**: o fio anterior sobrevive ao `recomecar` · a pilha tem teto e o mais
novo vem primeiro · fio vazio não entra · `retomar` põe o fio de volta · **id que nunca foi
nosso é recusado** · retomar mata a sessão viva.

**E o teste do pior modo de falha:** depois de `/retomar`, `_visita_do_fio[chave]` está marcado e
`_conversa_desta_visita()` devolve `False`. Sem ele, "retomar" é um botão que não faz nada e não
diz nada.

---

## Ordem de execução

1. `servico/atalhos.py` + testes (isolado: sem rota, sem tela).
2. `GET /atalhos`, `/atalhos/salvar`, `/atalhos/tirar` + testes de rota.
3. O popover: HTML, CSS, JS — lista, preencher, tirar, "Limpar conversa" (reuso puro).
4. O modo "forma" + "Salvar como atalho…".
5. Pilha em `sessao.py`, `POST /retomar`, o item do menu, **a marcação de visita**, o aviso de
   `no conversation found`.
6. `_arquivo_escolhido` + `/atalhos/carregar` (seletor primeiro, drop no menu depois).
7. A linha "escolher arquivo" na matriz de plataforma (`.md` e `.json`).
8. `CLAUDE.md`: fechar o `⬜ Falta a válvula` da seção "Uma conversa por VISITA" e descrever o
   menu do compositor.

## Verificação de ponta a ponta

1. `python -m pytest` (745 hoje + os novos) e `node --check cicloassist/painel/painel.js`.
2. **Reiniciar o serviço** (mexeu em rota) e dar **Reload** no painel.
3. Criar um atalho a partir de uma pergunta; fechar e reabrir o painel; ele continua lá.
4. Clicar no atalho: o texto entra na caixa **sem enviar**, com o caret no fim.
5. Arrastar um `.md` sobre o menu aberto; depois o mesmo pelo "Carregar prompt de arquivo…" — o
   diálogo tem de nascer **à frente** do Media Composer.
6. Limpar pelo menu; em seguida "Retomar a última conversa" **e uma pergunta curta** — a resposta
   mostra que o fio voltou, ou diz que não foi possível.
7. Abrir o `atalhos.json` na pasta de dados: legível e editável à mão.

## Riscos, em ordem de dano

1. **`_conversa_desta_visita` jogando fora o fio recém-retomado** depois de um reinício do
   serviço — falha 100% silenciosa; conserto de uma linha, com teste.
2. **`gravar_estado`/escrita engolindo `OSError`** — salvar responde "ok" e o atalho não existe.
   Mitigado devolvendo sempre a lista relida.
3. **Botão sem `type="button"`, ou o popover dentro do `<form>`** — Enter manda a pergunta.
4. **`--resume` num id que o CLI já não tem** — hoje cria conversa vazia sem avisar.
5. **`.txt` em cp1252** derrubando a rota com `UnicodeDecodeError`.
6. **`.json` desconhecido virando prompt** na caixa sem explicação.
7. **`choose file of type` no macOS** com extensões em vez de UTIs — não medido, fora da v1.
8. **Erro de sintaxe no `painel.js`** não aparece como erro: aparece como painel que não faz
   nada. Rodar a suíte a cada passo da interface.

## Fora da primeira versão

Tela de gerenciamento (renomear, reordenar, exportar) · navegação por setas dentro do menu ·
atalhos com variáveis (`{bin}`, `{take}`) · listar as 5 conversas anteriores (guardar 5, oferecer
1) · última pergunta sobrevivendo ao Reload (exigiria gravar texto do editor em disco, e o painel
não manda nem para o log, de propósito) · ordenar por uso (menu que troca de lugar sozinho não se
aprende com o dedo) · `.docx` como fonte de prompt · atalhos que enviam direto (a decisão foi
"preenche"; mudar depois é uma marca no item, não um redesenho).
