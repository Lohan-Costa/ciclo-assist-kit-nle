# O mapa de corte, separar falas e o checker degenerado

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ O mapa de corte: a regra que deixou de ser conselho

`conferir_o_mapa` + `estruturar_o_roteiro` (`plano/mapa.py`, `mcp/ferramentas/roteiro.py`).

O método da casa tem regra escrita para os quatro sintomas que o editor nomeou — ordem
(§1), fala repetida (§2), corte no meio de fala (§3), L/J (§4). Em 2026-09-12 ele foi
consultado **16 s depois do turno abrir** e a cena saiu "horrível" assim mesmo. Regra que
ninguém confere não é regra, é conselho.

⚠️⚠️ **E a escrituração sozinha NÃO pega o defeito** — isto é o achado que dá forma ao
módulo. Rodada contra aqueles 15 cortes, ela **APROVA**: as falas declaradas estavam em
ordem, 15 de 16, sem repetição. O modelo declarava a fala certa e apontava o tempo de outro
take. No papel, mapa impecável; o erro só aparecia no play.

⇒ Por isso são duas conferências, e a segunda é a que importa:

| confere | pega |
|---|---|
| a ordem no papel (`conferir`) | diálogo fora de ordem, fala repetida, fala esquecida |
| ⭐ a âncora no material (`ancorar`) | **o corte que declara a fala certa e aponta outro take** |

A âncora compara o texto do roteiro com o que a transcrição diz naquele take naquele
intervalo. **MEDIDO na C07: take certo 100%, com improviso real do ator 90%, take errado
9%.** O piso de 30% fica num abismo, não numa borda — e tem de ser generoso, porque o ator
não diz o que está escrito (4 de 6 falas divergiram).

⚠️ Ordem não é "cada fala uma vez": **N→1** (duas falas num corte só), **1→N** (fala longa
em dois ângulos colados) e **1→0** (sacrificada, mas DITA) são todas legítimas. A regra é
sequência **não-decrescente** com ocorrências **contíguas**.

⭐ Leitura pura de propósito: um passo de conferência que exige clique é um passo que
ninguém dá.

### ⭐⭐ Separar falas: uma timeline por fala (`separar_falas`)

A segunda função do produto (`mcp/ferramentas/falas.py` sobre `plano/falas.py`, método em
`skills/separar-falas.md`). Bin NOVA (`C07 FALAS.avb`) com `C07_FALA03` e `C07_FALA03.02`
(variante = texto distinto do mesmo momento), cada uma com o trecho de cada take que a diz,
apontando o subclipe do editor, fecho oculto. O formato é o que o editor definiu no
`_ASSIST ANTERIOR` (2026-08-30). Com roteiro ou sem: o código confere o mesmo.

O modelo propõe a espinha; o código confere o que é conta — e cada conferência fecha o
gradiente que a anterior abria:

| confere | fecha |
|---|---|
| a fala está no trecho (âncora, 30%) | timestamp de um take aplicado em outro |
| nenhum segmento de OUTRA fala cabe inteiro no trecho | o take inteiro para toda fala, que passa na âncora |
| ordem dos momentos dentro de cada take | fala do fim ocupando o lugar de uma do começo |
| o mesmo trecho em dois momentos | a mesma frase servindo a dois momentos |

**MEDIDO na C07 real** (`spikes/as_falas_conferidas.py`, 10 takes, ~370 falas do ASR):
honesto 0 reprovado, falas juntadas 0, take inteiro 10 de 10 reprovados, tempo trocado
entre takes **167 de 167** pegos.

- ⛔ A primeira régua de "o trecho é a fala" contava PALAVRAS a mais, e numa cena de três
  falas o take inteiro dava 30% — o mesmo que a fala com o respiro. Por SEGMENTO a diferença
  é de natureza.
- ⚠️ E ela reprovava 4 pedidos honestos: o ASR partiu "…flexibilizar **demais.**" em 9
  frames, que o respiro da anterior cobre inteiro. `MARGEM_DE_RESPIRO = 12` frames.
- ⚠️ `transcrever` devolve a fala que ATRAVESSA o in-point (a claquete) com
  `inicio_no_take_frames` negativo, e o modelo copia. A recusa diz o que fazer.

⭐⭐ **A conferência roda ANTES do cartão** (`registro.ferramenta(conferir=…)`): o portão
chama, e um pedido reprovado volta ao modelo como `deny` com `NAO_MOSTRADO` — que diz o
CONTRÁRIO do `AGUARDANDO`: aqui pedir de novo, consertado, é o certo. O editor nunca aprova
algo para ver falhar. Conferência que quebra NÃO barra (o cartão aparece e a ferramenta
confere de novo): defeito nosso não pode parecer pedido errado. Vale para as TRÊS que
escrevem no projeto: `separar_falas` (âncora), `editar_timeline` (a mesma prova do
`conferir_a_edicao`) e `montar_corte` (a forma do plano).

⛔⛔ **E a conferência que só olhava o que ESTAVA no pedido premiava cortar** (2026-09-15,
Haiku, roteiro arrastado): 33 momentos e 237 trechos, 32 trechos errados, e a cada recusa
ele tirou falas — 33 → 20 → 10 — até passar. O editor recebeu 10 das 16 falas. Três
mudanças, cada uma com teste:

- ⭐ **O trecho aponta o SEGMENTO, não frames.** `transcrever` numera as falas do take
  (`segmento`, numeração do take inteiro) e o `separar_falas` recebe
  `{"take", "do_segmento", "ate_o_segmento"}`; a lista sai de `fala.falas_do_take` nos dois
  lados. Pedido em frames é recusado.
- ⛔ **Cobertura** (`plano/falas.conferir_cobertura`): toda fala do roteiro (o passado ou o
  ÚNICO arrastado) e todo take da cena na bin (pela claquete) entram, ou vão em
  `deixadas_de_fora` com o porquê — que o cartão mostra. E um pedido com menos trechos por
  take que o recusado mais cheio reprova. MEDIDO nos pedidos reais: falas do roteiro
  presentes 75–100% das palavras, ausentes 8–50% ⇒ `COBERTURA_MINIMA = 0.6`. Repassado o
  pedido de 10 momentos que tinha passado: agora reprova com as falas 6–16 e 4 takes.
- ⭐ **`acrescentar_em`**: completa uma bin de falas que existe (lotes), pela dança do
  `montar_corte`; momento repetido é recusado. Antes, cada lote criava `C07 FALAS N`.

⛔⛔ **A bin GRAVADA em disco, e o erro que não dizia isso** (2026-09-20, Assist anterior,
material real). Ele pediu "separa as falas da C07" às 09:16 e os dez takes voltaram
`não achei a mídia de som de '' no acervo local` — **nome vazio**, porque o master não
estava na bin lida do disco: a `C07.avb` foi gravada às **09:17:12**, um minuto depois. O
modelo não tinha como saber, deduziu que faltavam masterclipes e pediu ao editor que os
trouxesse — coisa que no Avid nem faz sentido (master de subclipe vive oculto na própria
bin). ⇒ `take.por_que_falta` diz a causa e **o gesto** (salvar a bin, Ctrl+S), os avisos do
resolvedor chegam junto do erro, e a skill ganhou "quando a transcrição falha em TODOS os
takes". A queixa que isto fecha: *"cada modelo está interpretando a sua forma de
execução… precisamos ser mais previsíveis"* — **erro que não diz o gesto vira adivinhação, e
cada modelo adivinha diferente.**

⚠️ Falta: rodar pelo chat com o Media Composer aberto; transcrição por canal (lapela =
falante); decidir se há espaço entre os trechos de uma timeline (hoje colados). ⚠️ O efeito
do segmento sobre a TAXA de erro do Haiku não está medido — só uma rodada nova diz.

### ⛔⛔ O checker que premiava o degenerado

⚠️⚠️ **MEDIDO em 2026-09-12, e é uma regressão que o `conferir_o_mapa` criou.** Ele
validava ordem, repetição e a âncora no material. Um modelo fraco mandou 16 cortes em 5
takes, levou **duas reprovações legítimas** da âncora (parecença 12% e 15%), reenviou o
mapa idêntico, e então **colapsou os 16 cortes no plano aberto que contém a cena inteira** —
onde toda fala bate 100%. O checker aprovou.

⇒ Validar *"a fala está mesmo aqui"* é satisfeito por um master de cena inteira para
TODAS as falas. Eu tinha trocado "não aponte material errado" por "aponte tudo para o take
que sempre passa".

⭐ A regra que fecha isso **não é cota de cobertura** — ritmo é ofício e é do editor. É que
**cortar de um plano para ele mesmo é jump cut**: dezesseis emendas invisíveis são o take
inteiro com as pausas tiradas. Plano-sequência legítimo se monta com **um** corte, e esse
passa. Junto veio a conferência de **trechos sobrepostos** do mesmo take, que nem o
`plano/esquema.py` pegava (medido: os cortes 9 e 10 começavam os dois no frame 2613).

⚠️ E a reprova é CURTA de propósito: a primeira versão devolvia **21 linhas** para esse
mapa, e cada linha é contexto que o editor paga num turno que já deu errado.
