# A aba Vetores

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐ A aba Vetores: o que já foi analisado, o que falta, e o trabalho de fundo

Uma linha por **MASTER**: o que o cache tem (quadros, fala, vetor), com que receita foi
feito, e se essa receita ainda é a de hoje. `midia/inventario.py` lê o disco e só roda
quando o editor abre a aba. ⚠️ A ROTA pergunta ao MC **qual é o projeto** (barato, cacheado
— `avid/escopo.py`): sem isso, trocar de projeto deixava a aba mostrando as bins do
anterior e os botões contando mídia que a fila ia recusar.

#### ⭐⭐ "Ler o cache" levava 66 s, e o conserto foi todo de REDUNDÂNCIA (2026-09-23)

Relato do editor: *"a leitura do cache demorou mais do que eu achava aceitável"*. A rota
não registrava a própria duração, e **medir por FORA do serviço deu número errado duas
vezes no mesmo dia** — o primeiro passo foi pôr o relógio dentro dela. Hoje `/vetores` e
`inventario.listar` dizem onde o tempo foi, repartido.

| | frio, antes | depois |
|---|---|---|
| **`/vetores` inteiro** | **66,3 s** | **~0,6 s** |
| `clipes_do_projeto` (Premiere) | 54,4 s | 0,47 s |
| `inventario.listar` | 11,9 s | 0,53 s |

⛔⛔ **`indice.varrer()` rodava uma vez POR ARQUIVO do projeto.** Ele relista a raiz do
cache inteira, e `_clipe_do_arquivo` roda por arquivo: eram 203 relistagens idênticas das
537 pastas — **O(arquivos × pastas)**, com as duas pontas crescendo com o uso. Medido:
`203 itens em 4,12 s — ponte: 0,16 · por arquivo: 3,97`. Quem varre é `clipes_do_projeto`,
UMA vez. ⭐ E paga duas vezes: a vigia refaz essa leitura a cada 60 s pela mesma ponte.

⛔⛔ **O `midia.json` era lido de 3 a 5 vezes por mídia.** `ler_fonte()` o lê, `nome` chama
`ler_fonte()` de novo **e** `manifesto()`, e o filtro de banco chamava `origem`, que o lia
outra vez: ~1.800 leituras do mesmo arquivo pequeno numa listagem de 537. ⇒ `Midia.ficha()`
lê uma vez e devolve manifesto, fonte, nome e origem. ⭐ E a `origem` do filtro sai do
ÍNDICE, que já a leu ao varrer (`_e_midia` guarda `origens`) — abrir o manifesto das 537
só para descartar a maioria era trabalho pago duas vezes.

⚠️ **O que sobrou, medido:** `medir` (o `rglob` de cada pasta) 0,25 s · `transcricao` 0,09 ·
`ficha` 0,05 · `notas+cortes` 0,03. ⬜ E a aba ainda **relê tudo ao voltar para ela** —
`mostrarTela` chama `carregarVetores()` sem guarda nenhuma. Com 66 s era o problema; com
0,6 s é desperdício.

⚠️ **Uma linha é um MASTER, e a tabela surpreende por isso.** Um take sincronizado mistura
dois — V da câmera, A do gravador —, então quadros e transcrição do mesmo take saem em
linhas diferentes. Já uma diária de câmera é UM master com vídeo e áudio, e aí a linha tem
as duas colunas. A espécie fica escrita ao lado do nome para a coluna vazia não se ler como
pendência.

**A varredura** (`midia/acervo.py`) lê uma pasta `Avid MediaFiles` com `ffprobe` e agrupa
os OP-Atom pelo `material_package_umid` — que é **a mesma chave do cache**, então varredura
e cache cruzam sem duplicar linha. Medido aqui: 1.747 arquivos → 358 clipes, 58 s na
primeira passada e **0,7 s na segunda** (a sondagem fica guardada, endereçada por caminho +
tamanho + data). ⭐ Os `._*` do macOS eram **343 dos 1.747** — um quinto da varredura gasto
em ffprobe que falhava.

**As bins** (`avid/bins.py`) respondem a outra pergunta: *o que está no PROJETO*. Medido:
**5.524 mobs em 42 bins, 0,4 s** — a fonte mais barata daqui, e o nome que sai dela é o que
o editor vê e edita. Cruzando as duas varreduras no projeto real: **306 nos dois, 52 só no
disco, 1 só na bin**. ⚠️ "Sem arquivo" **não** é "offline" — pode ser um volume que
ninguém mandou varrer. ⛔ E a pasta `Trash` fica de fora: com ela dentro, 33 de 36 "sem
arquivo" eram material que o editor já tinha jogado no lixo.

⚠️⚠️ **`pyavb` é preguiçoso:** as propriedades são lidas ao serem tocadas, e guardar um mob
para ler depois do `with avb.open(...)` dá `ValueError: seek of closed file` — sem
mencionar o `with`. Tudo que interessa vira dado nosso dentro do bloco.

**A fila** (`servico/tarefas.py`) é trabalho FORA de um turno: o editor manda analisar e
volta a montar. **Uma tarefa por vez**, e não é simplificação — o que roda no fundo disputa
a máquina com o ASR do turno. Parar aproveita o que já foi feito, e o pedido de parada
chega **dentro** do laço do ASR pelo relator de progresso: conferindo só entre as mídias,
o botão levava 2 min para fazer efeito.

⭐ **A lista é TABELA, não cartão** (decisão do editor, 2026-09-13): colunas ordenáveis
(nome, tipo, quadros, vetor, fala, decupagem, bin, arquivo, tamanho), etiquetas que somam na
mesma família e filtram entre famílias, busca por nome ou bin. Rola nos dois sentidos dentro
da própria caixa, nome preso à esquerda, e a altura da caixa é calculada para a **barra
horizontal ficar à vista** — conferido em print a 440 e a 340 px. ⛔ E **nenhum texto abaixo
de `#a3a3a3`** no painel inteiro (`--tinta-3`); desabilitado muda de tinta, nunca de
`opacity`, que escurece o texto abaixo do piso.

⭐ **Os botões agem no que a lista MOSTRA** — filtrou, é daquelas que ele fala, e o rótulo
diz a conta. E o interruptor "refazer o pronto" arma os botões e **desarma sozinho ao
disparar**, pelo mesmo motivo do botão que apaga.

⛔⛔ **E a conta do botão é a MESMA da fila** (`inventario.pode_analisar`, 2026-09-20). A
fila exige arquivo da espécie certa (e taxa, na imagem) e pulava o resto **em silêncio**;
a tela contava tudo. Medido no cache do editor: **100 de 106** "sem transcrição" não tinham
arquivo — música importada de outra pasta, mídia AMA de um volume que ninguém varreu. O
relato foi *"mesmo clicando nas opções elas não são processadas"*, e na decupagem o **preço
antes do clique saía inflado junto** — que é a promessa central da aba. Hoje a linha da
tabela carrega `pode` por estágio; serviço velho (sem o campo) cai no comportamento de antes
em vez de sumir com o botão.

⭐ **Reconectar** é `POST /cache/olhar`: antes de trocar a pasta do cache, o painel diz o
que há na pasta de destino (N mídias analisadas · pasta vazia · não parece um cache · ainda
não existe). Apontar às cegas não falha na hora — falha reprocessando tudo em silêncio.

⛔⛔ **A página não escolhe caminho, escolhe da LISTA.** Varrer o caminho que viesse no
corpo do POST seria "leia esta máquina inteira" dito por uma frase (ADR 0005) — e a
varredura devolve nomes de arquivo. A lista são as `Avid MediaFiles` dos volumes mais as
pastas que o editor apontou no seletor do Windows: o mesmo gesto que autoriza o arrasto.
