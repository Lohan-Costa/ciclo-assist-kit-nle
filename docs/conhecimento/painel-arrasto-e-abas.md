# O painel: arrastar para o chat, as abas, o menu ☰

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ Arrastar para dentro do chat, e a permissão que isso cria

O editor arrasta em vez de digitar: a sequência que quer mexer do Avid, o roteiro que está
no Explorer, uma foto de referência. Duas origens, um gesto:

| origem | o que chega | onde está medido |
|---|---|---|
| Media Composer | MIME `text/x.avid.mc-api-asset-list+json` → **MobID e espécie, sem nome** | banco: `plugins/avid-panel-sdk/arrastar.md` |
| Explorer | `text/uri-list` → `file:///C:/…` | o `File` do Chromium **não** dá o caminho |

⭐ **E as duas origens têm COR própria** (2026-09-12): verde-água o que é do Media Composer,
violeta o que veio de fora. Não é enfeite — o mob do MC o plugin alcança pela ponte gRPC; o
arquivo do Explorer só é legível porque o editor arrastou **aquele** arquivo. O realce do
arrasto segue a MESMA precedência do `aoSoltar` (havendo MIME do Avid, é do Avid), senão
ele prometeria uma origem e o chip entregaria outra. ⚠️ Cor é reforço: quem diz O QUE é
continua sendo o rótulo, e `.ruim` (âmbar) vence a origem — problema antes de procedência.

⛔⛔ **`servico/arrastados.py` é a permissão de ler o disco.** O caminho chega às
ferramentas dentro de texto que o MODELO escreve — sem a lista, "leia este arquivo" seria
a máquina inteira (ADR 0005). **Só é legível o que o editor arrastou**, e o gesto autoriza
aquele arquivo: não a pasta, não o padrão, não o disco.

⛔⛔ **O arrasto entrega o MobID SEM a bin, e numa grafia que o `.avb` não usa**
(2026-09-15): `060a2b34…2013-000000-a9b9…` contra `urn:smpte:umid:060a2b34.01010105…`, os
mesmos 64 hex. Comparando a string, nenhum clipe arrastado era achado, e o modelo
perguntava ao editor "em que bin estão os subclipes?". Hoje `take.hex_do_mob` compara, e o
preâmbulo diz a bin de cada item (`bins.bins_dos_mobs`, só itens VISÍVEIS — a bin de falas
tem o fecho oculto). E o primeiro turno de uma visita não apaga mais a autorização do que
veio anexado àquela pergunta.

⚠️ Quatro armadilhas do drop, todas medidas — e cada uma falha sem apontar para si:
`effectAllowed` do MC é **"move"** (forçar `copy` cancela o drop em silêncio); ouvir na
**captura**, senão o `<textarea>` come o evento; `preventDefault` **incondicional** no
`dragover`, senão soltar um arquivo navega a webview para ele e o painel some; e arrastar
uma **bin inteira não entrega nada** — `types` vem vazio.

### O painel: abas, e o que o editor pode mexer

Três abas — **Claude**, **Busca** e **Vetores** —, e a barra foi feita para crescer: o
Ciclo Assist é o primeiro painel da casa, e os próximos entram ao lado. Acrescentar uma é somar um
`<button data-tela>` e um `<section data-tela>` no `index.html`; o JavaScript não muda (e
um teste garante que toda aba tenha a sua tela).

A engrenagem fica no canto oposto porque não é irmã das abas de produto: é a chave de
fenda. Ela abre uma TELA, nunca um modal — modal em 400 px cobre a conversa inteira e
ainda precisa de um jeito de fechar.

⭐ **Onde o cache mora é escolha do editor**, gravada em
`%LOCALAPPDATA%\CicloAssist\config.json`.
A precedência é `CICLOASSIST_CACHE` → `config.json` → o padrão: o ambiente
ganha porque é o que o desenvolvimento usa para não encostar no cache de quem trabalha na
máquina — e o painel **diz** quando a variável está mandando, em vez de aceitar um valor
que vai ignorar.

⚠️ **Silêncio numa interface parece travamento.** Três lugares usam a mesma reticência
animada (`.reticencias`), e cada um cobre uma espera que já fez alguém clicar duas vezes:
o "pensando" antes do primeiro token, a linha de atividade durante uma transcrição, e o
"fazendo…" enquanto a bin é escrita.

⚠️⚠️ **O painel vem do DISCO; as rotas vivem na MEMÓRIA do processo.** Dar Reload no
painel traz a tela nova para dentro de um serviço velho — e a tela chama rotas que aquele
processo não tem. Em 2026-09-11 isso produziu "rota desconhecida" na engrenagem e "não há
pergunta em andamento" no cartão, e os dois pareciam bug do código novo. Por isso `/saude`
declara `capacidades` — **o caminho INTEIRO de cada rota**, não o primeiro pedaço — e a
tela confere na partida: quando faltar alguma, ela diz para reiniciar o serviço, em vez de
deixar o editor caçar o defeito.

⚠️⚠️ **E o serviço manda `Cache-Control: no-store` no painel e nos estáticos.** MEDIDO em
2026-09-11: sem cabeçalho de cache nenhum, o Reload trouxe a página ANTIGA — a tela voltou
idêntica, sem a mudança recém-escrita, enquanto o `curl` devolvia o HTML novo. O sintoma
diz "o código novo não funcionou". ⚠️ O conserto está no ar mas ainda **não foi visto
funcionando** dentro do MC (ver a nota lá em cima).

⛔⛔ **`hidden` perde para `display`.** O JS troca de tela escrevendo `el.hidden`; o
`hidden` do navegador é um `display:none` de folha padrão, e `.conversa`, `.status` e
`.compositor` são `display:flex`. Abrir a engrenagem deixava a conversa e a caixa de texto
NA TELA, por baixo. A regra `[hidden] { display: none !important }` no topo do CSS é o que
faz a troca de aba funcionar — e há teste para ela.

⛔ **Nada de `confirm()` no painel.** Um diálogo nativo dentro do Media Composer trava a
página até alguém responder, e quem apertou pode nem estar olhando para cá. O que apaga
pergunta no próprio botão ("Apagar mesmo?") e desarma sozinho.

### ⭐ O menu ☰ do compositor: atalhos de prompt (2026-10-21)

À esquerda da caixa de texto. Em cima, os atalhos (`atalhos.json` na pasta de dados, `servico/atalhos.py`, teto de 12);
embaixo, "Salvar como atalho…" e "Limpar conversa". ⛔ Clicar num atalho **preenche e não envia** (o editor arrasta a
bin antes). ⛔ O menu fica FORA do `<form>`: o campo de apelido submeteria a pergunta no Enter. ⛔ Atalho não guarda
anexo nem caminho. Os prompts fixos da demo de sexta moram aí (fonte: `docs/demo/*.txt`). Falta retomar a conversa e
carregar de arquivo — plano `docs/plano/2026-09-14-menu-do-compositor.md`.
