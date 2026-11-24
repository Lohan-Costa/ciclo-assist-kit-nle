# Separar as falas de uma cena

**quando:** o editor quer as falas de uma cena separadas — "separa as falas da 7", "quero
ver todos os takes de cada fala", "faz as sequências de fala", "organiza o material por
fala". Com roteiro ou sem.

**não vale para:** montar a cena (isso é `montar-por-roteiro`), nem mexer numa sequência
que já existe.

---

## 1. O que o editor recebe

Uma bin nova com **uma timeline por fala**. Em cada uma, o trecho de cada take em que aquela
fala é dita, um atrás do outro. É o que um assistente de montagem faz à mão: o editor abre
a `C07_FALA03`, dá play e compara as leituras daquele momento.

```
C07_FALA01     - Boa tarde, doutora.
C07_FALA02     - Sinceramente? Não.
C07_FALA02.02  - Não… sinceramente, não sei.
```

- `FALA03` é o **momento** na cena, contado na ordem em que acontece.
- `.02` é **texto distinto** do mesmo momento: o ator improvisou outra coisa ali. Takes
  que improvisam **igual** são a mesma variante. A variante 1 é o texto que mais takes dizem
  — não "o do roteiro".
- Nenhum clipe é criado: cada trecho aponta o subclipe que o editor já tem.

## 2. Transcreva TODOS os takes da cena antes de começar

Uma fala que você não viu num take é uma fala que falta na timeline dele. Separar com metade
dos takes transcritos entrega uma bin que parece completa e não é.

⭐ Peça `transcrever` com **`enxuta: true`**, todos os takes numa leva só. Cada fala vem como
`segmento | segundos | texto`, que é tudo o que `separar_falas` usa: o pedido aponta o
segmento, nunca frames. A forma completa é seis vezes maior e fica relida a cada passo.

### Quando a transcrição falha em TODOS os takes

⛔ **Não invente teoria sobre a bin.** No Avid, o master de um subclipe (e o de uma timeline
ou de um groupclipe) vive **oculto dentro da própria bin** — pedir ao editor que "traga os
masterclipes para a bin" não faz sentido e o deixa sem saída. Aconteceu em 2026-09-20.

O que a mensagem de erro diz é o que vale:

- **"o master … não está na bin GRAVADA em disco"** — a bin tem alterações que o Media
  Composer ainda não salvou (o app lê o arquivo, não a memória do MC). Peça **uma coisa
  só**: salvar a bin (Ctrl+S) e dizer quando terminar. Depois transcreva de novo.
- **"não achei a mídia de … no acervo local"** — a mídia existe e o arquivo não está no
  disco varrido. Diga o nome do master; quem resolve é o editor (mídia offline, ou volume
  que ninguém varreu).

⚠️ Em qualquer dos dois: **não monte nada**. Sem transcrição, marcar trecho é chute, e um
chute aqui põe a fala errada na timeline — o erro mais caro que esta ferramenta pode
cometer.

## 3. A espinha: que momentos a cena tem

⭐⭐ **O material manda.** O que o editor precisa é do que foi GRAVADO.

- **Com roteiro:** `estruturar_o_roteiro` dá a ordem, quem fala e o NÚMERO de cada fala.
  Cada fala do roteiro que aparece em algum take vira um momento (uma fala longa pode virar
  vários). Improviso que nenhuma fala do roteiro explica, dito
  em vários takes, também vira momento — no lugar em que acontece.
- **Sem roteiro:** comece pelo take com mais material (o que cobre a cena inteira), e use
  as falas dele como espinha. Depois case os outros takes contra ela: quase sempre são
  quase-duplicatas do mesmo texto. O que só os outros takes dizem entra no lugar em que é
  dito.
- Personagem vem do roteiro ou da claquete. ⛔ Nunca do rosto. Sem fonte, deixe vazio.

## 4. Os trechos

- Cada trecho é `{"take", "do_segmento"}`: o número `segmento` da fala na transcrição
  **daquele** take. ⛔ Nunca frames — o código converte, e pedido em frames volta recusado.
  Copiando frames à mão, 32 de 237 trechos apontaram outra fala (2026-09-15).
- Falas seguidas do mesmo ator que o ASR partiu em dois segmentos com vão curto: um trecho
  só, `do_segmento` da primeira e `ate_o_segmento` da segunda.
- ⛔ **Fora da timeline de fala:** claquete, "ação", "corta", conversa de set, e o take
  abortado no meio da fala (use só se a fala chegou a ser dita inteira).
- O mesmo trecho não serve a dois momentos. Se o ASR juntou duas falas de atores diferentes
  num segmento, diga no `porque` que o ponto é aproximado.
- Ordem dos trechos numa timeline: a ordem dos takes (T001, T002…).

## 5. Nada fica de fora calado

O código confere que **toda fala do roteiro** está em algum momento e que **todo take da
cena** tem algum trecho. O que ficar de fora de propósito vai em `deixadas_de_fora`, com o
porquê — `{"roteiro": 11, "porque": "nenhum take diz"}`, `{"take": "C07_P03-T002",
"porque": "abortado no set"}` — e o editor lê isso no cartão antes de aprovar.

Cena grande: separe em lotes. O primeiro cria a bin; os seguintes passam
`acrescentar_em` com a bin criada e continuam a numeração dela. ⛔ Nunca uma bin por lote.

## 6. A conferência, e o que fazer quando reprova

O pedido é conferido contra as transcrições **antes** de chegar ao editor. Se voltar:

- *"nesse trecho o take diz …"* — o tempo aponta outra fala. Releia a transcrição **deste**
  take e copie de novo.
- *"o trecho engole fala(s) que não são esta"* — você apontou um pedaço do take que contém
  outra fala inteira. Aponte só esta.
- *"fora da ordem da cena"* — num take, um momento posterior começa antes de um anterior.
  Se o ator repetiu a fala, use só uma das vezes.
- *"sem transcrição para conferir"* — transcreva esse take.
- *"roteiro N … não está em momento nenhum"* — separe essa fala, ou diga em
  `deixadas_de_fora` por que ela não entra.
- *"tinha N trechos no pedido recusado e agora tem M"* — você tirou trecho em vez de
  consertar. Devolva e corrija só o segmento apontado.

⭐ **Mande SÓ os momentos consertados, com `corrigir_o_anterior: true`.** O serviço guarda o
último pedido desta cena e encaixa os momentos que você mandar (mesma fala e variante trocam
o anterior). Reescrever as 16 falas para mudar dois trechos custa minutos e repete os erros.

⛔ **Conserte SÓ o que foi apontado.** Não tire fala nem take para
passar: em 2026-09-15 um pedido de 33 momentos virou 10 assim, e o editor recebeu 10 das 16
falas. Tirar é decisão editorial, e vai em `deixadas_de_fora`.

## 7. Depois

Diga em duas linhas: quantos momentos, quantas variantes, onde está a bin. E o que ficou de
fora, se ficou: fala do roteiro que nenhum take diz, take que você deixou de fora.
