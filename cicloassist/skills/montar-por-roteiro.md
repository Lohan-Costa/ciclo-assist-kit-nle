# Montar por roteiro

**quando:** o editor entrega um roteiro, uma lista de falas, uma ordem aprovada de sonoras
— e quer a cena montada com o material que existe. Também vale quando ele diz "monta essa
cena", "faz o primeiro corte", "cola isso na ordem do roteiro".

**não vale para:** montar sem roteiro (aí a ordem sai do material, e a pergunta é outra),
nem para mexer numa sequência que já existe.

---

## 1. O roteiro manda na ORDEM. O material manda no TEXTO.

⛔⛔ **O ator não diz o que está escrito, e isso está medido.** Em 4 de 6 falas de uma cena
real o texto divergiu do roteiro ("Boa noite" → "Boa tarde"), e em 7 de 11 tomadas houve
improviso que não está no papel — de 0,67 a 3,96 s de material dito que um motor fiel ao
roteiro **descarta**.

⇒ Use o roteiro para saber **que fala vem depois de qual**. Use a transcrição para saber
**o que foi dito e quando**. Quando os dois divergem, quem tem razão é o material.

⭐⭐ **Não faça isso de cabeça: chame `estruturar_o_roteiro`.** Ele numera as falas na
ordem em que estão escritas, e esses números são a espinha do trabalho inteiro. MEDIDO em
2026-09-12: sem eles, quinze cortes de uma cena foram montados guardando de cabeça os
tempos de cinco takes — e o timestamp de um take entrou em outro.
- Case cada fala do roteiro com a transcrição por **sentido**, não por igualdade de
  string. "Sinceramente? Não!" e "Sinceramente, não." são a mesma fala.
- Fala do roteiro que não aparece em take nenhum: **diga qual**, não invente um lugar para
  ela.
- Fala dita que não está no roteiro: decida e **diga que decidiu** — improviso costuma ser
  o melhor material da cena.

## 2. Escolha o take antes de escolher o corte

- Transcreva **todos** os takes candidatos antes de montar. Montar com o primeiro que você
  transcreveu é escolher por ordem de arquivo, não por performance.
- Um take pode ter a cena inteira e outro só um pedaço. Cobertura não é redundância.
- ⚠️ Nem todo take é a cena: teste de câmera, conversa de bastidores e ensaio aparecem no
  meio. Se a transcrição não bate com nenhuma fala do roteiro, provavelmente é isso — diga
  e deixe de fora.
- Alternar takes entre as falas é normal e desejável. Repetir a **mesma fala** em dois
  cortes é defeito.

## 3. O ponto de corte não é o tempo do reconhecedor

⭐⭐ Use `entrada_do_corte` e `saida_do_corte` de cada fala. Eles já trazem o respiro.

**MEDIDO** (`spikes/o_respiro_do_corte.py`, som direto real): a voz continua **230 ms em
média** depois do que o ASR diz — pior caso 350 ms, 5,5 frames a 24 fps. Cortar em
`fim_no_take` decepa a última sílaba: foi assim que "sobe comigo" virou "sobe co…" na tela
do editor.

⚠️ E a entrada é o contrário: o ASR acerta o ataque com 10 ms. A entrada colada **não é
erro de medida** — é falta de ar. Cortar rente no ataque soa amputado mesmo com a sílaba
inteira.

- Duas falas seguidas **do mesmo take** com `vao_ate_a_proxima` curto: **um corte só**,
  cobrindo o vão. A pausa é atuação, e a ambiência que some no meio denuncia o corte.
- ⛔ **Nunca emende pedaços de falas diferentes** porque o texto combina. Se o trecho que
  você quer começa ou termina no meio de uma fala, diga que o ponto é aproximado.

## 4. Som antes de imagem, quando eles discordam

- ⛔ Corte em **L** ou em **J** fica com o EDITOR (decisão do autor, 2026-11-07): o `montar_corte`
  monta só corte seco e recusa `corte_de_som`. Quando a reação pedir um L/J, **diga ao editor onde**,
  na resposta — a escolha de onde o som troca é dele.
- ⚠️ O offset de imagem e som de um take sincronizado **é diferente** (medido: imagem em 0,
  som em 234 frames). Nunca calcule um a partir do outro.

## 4.1 Artes com alpha: cartela, selo, legenda

⭐ Arquivo com alpha que o editor importou vira, na bin, um clipe **`Matte Key: <nome>`**.
Ele **não** aparece em `listar_itens_da_bin` com o tipo padrão: peça `tipos: ["effects"]`.
MEDIDO em 2026-09-13 (`MAIS VC AUTO`): sem isso, o corte saiu só com a vinheta e o vídeo, e
nenhuma das cartelas do roteiro.

- A arte vai em **`coberturas`** do `montar_corte`, nunca em `cortes`: ela fica POR CIMA da
  imagem, na V2, e a imagem de baixo continua passando.
- Ancore no corte: `sobre_o_corte` é o número do corte do plano, e `deslocamento_frames` o
  quanto depois do começo dele. Não some durações de cabeça.
- Roteiro de TV costuma dizer onde a arte entra na coluna de ilustração, ao lado da fala
  ("CARTÃO: 10:35", "BATER CARTELA DO PGM"). O `porque` da cobertura é essa linha.
- Sem `duracao_frames`, a arte entra inteira. Se passar do fim da sequência, diga a duração.

## 5. Antes de escrever, CONFIRA — e não é com os olhos

⛔⛔ **`conferir_o_mapa` antes de `montar_corte`. Sempre, em cena com roteiro.**

Monte a lista inteira primeiro — corte por corte, com o número da fala do roteiro, o take,
`inicio_no_take_frames` e `duracao_frames` — e passe nela. Escrever enquanto decide produz
sequência que ninguém consegue revisar.

O que ela pega, e que ler de novo não pega:

- diálogo fora da ordem do roteiro, e fala que entra duas vezes;
- fala do roteiro esquecida (sacrificar é legítimo; esquecer calado não é);
- ⭐⭐ **corte que declara a fala certa e aponta o tempo de OUTRO take.** Foi este o
  defeito de 2026-09-12, e é o único que nenhuma releitura acha: no papel o mapa estava
  perfeito — 15 falas de 16, em ordem, sem repetir. O erro só aparecia no play;
- ⛔⛔ **cortar de um plano para ele mesmo**, e o mesmo trecho entrando duas vezes.

⛔⛔ **Não resolva uma reprovação jogando tudo num plano só.** Um master que cobre a cena
inteira faz TODA fala bater, então ele passa na conferência de material — e o que sai não é
montagem, é o take tocado de ponta a ponta com as pausas tiradas. Aconteceu em campo
(2026-09-12): depois de duas reprovações legítimas, um modelo colapsou os dezesseis cortes
no plano aberto e entregou uma cena sem um corte de verdade. Quando reprovar, **conserte o
corte que ela apontou** — não troque de estratégia.

Um corte pode cobrir várias falas seguidas, e uma fala longa pode ser coberta por dois
planos colados. O que não pode é voltar atrás.

⚠️ Se ela disser `nao_conferidos_no_material`, aquele take ainda não foi transcrito e o
"fecha" não vale para ele. Transcreva antes de confiar.
- Diga o que você **sacrificou** e por quê. Fala cortada por sobreposição entre takes é
  decisão editorial, e o editor precisa saber que foi tomada.
- ⛔ **Nunca escreva por cima da sequência do editor.** Bin nova, ou sequência nova na bin
  dele — o `montar_corte` já faz isso.
- Depois de escrever, diga em uma linha o que ele vai ver: quantos cortes, que duração,
  onde está.
