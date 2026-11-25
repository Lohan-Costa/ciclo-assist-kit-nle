# O escopo do projeto aberto e o vetor visual

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐⭐ Toda busca só alcança as bins do projeto ABERTO (`avid/escopo.py`)

Decisão do editor (2026-09-13). A `Avid MediaFiles` pura não é escopo: tem mídia de outras
produções e mídia que ele tirou da bin e ficou no disco — resultado de lá é **resposta
errada que parece certa**. ⭐ O produto da Avid traça a mesma linha: o PhraseFind AI procura
*"audible dialogue throughout bins in a single project"* (banco, `ia-embarcada-nos-nles.md`).

⭐ **O ÍNDICE continua global, por UMID do master** — cache que atravessa projetos é o que
faz reanalisar nunca acontecer duas vezes. Quem se estreita é a RESPOSTA.

| quem | como |
|---|---|
| `procurar_no_material` | `decupagem.procurar(chaves=…)`, e o total dito ("3 de 23") é do MESMO recorte |
| `planos_parecidos` | `vetores.procurar(chaves=…)` |
| a fila da aba Vetores | só o do projeto — **a menos que o editor tenha filtrado a tabela** |

⛔⛔ **`bins.ler()` é uma FOTO do último projeto varrido, e não serve de filtro.** Em
2026-09-13 ela era do `_ASSIST ANTERIOR`, de dois dias antes, com o editor noutro projeto:
filtrar por ela esconderia o material de hoje e deixaria passar o de ontem. O escopo lê as
bins do projeto **aberto agora** (0,4 s, 42 bins) e só reaproveita a lista enquanto for
dele; sem MC, cai para a foto **dizendo que é foto**.

⛔ **"Não sei qual é o projeto" é SEM FILTRO, nunca "nenhuma mídia".** `chaves=None` e
`chaves=frozenset()` são coisas diferentes: quem as tratar igual faz o acervo sumir da tela
de um editor que está com o Media Composer fechado.

⚠️ **E filtro calado é pior que filtro nenhum:** toda resposta estreitada leva a frase do
recorte (projeto, quantos masters, de quando), e a fila devolve `fora_do_projeto` — sem
isso, "não achei" vira "não existe" e o editor acredita.

⛔ **Na fila, quem escolheu manda.** Sem filtro na tabela, o painel não manda `chaves` e o
serviço recorta pelo projeto; com filtro, as chaves vêm da tela e o recorte sai de cena —
o rótulo do botão diz a conta, e um filtro escondido por baixo o faria mentir. Por isso o
`alvosDe()` do painel aplica o mesmo corte ao contar.

⛔⛔ **Trocar de projeto NÃO emite evento**, e o preço de não notar é responder com o
material do projeto anterior. O banco tem o catálogo de `onEvent` (sniffer de 2026-08-07):
`BinRowSelectionChanged`, `MobAdded/Deleted`, `MobLoadedInViewer`, `ActiveMonitorChanged`,
`PlayPosition…` — e ampliar o `usesApi` aos cinco canais não acrescenta tipo nenhum.
Sondar custa **0,5–0,75 s** por chamada (medido nos dois modos: conexão nova e
reaproveitada — o piso é da API). ⇒ `GET /projeto` é chamada **no gesto** (a aba Vetores
abriu, a janela voltou ao foco) mais uma sondagem de 30 s **só com a aba à vista**; trocou,
a lista do projeto anterior cai na hora e a tela se relê dizendo o nome novo.

⛔ **MEDIDO em 2026-09-14: com o MC fechado, perguntar o projeto custa 2,0 s** (o gRPC
desistindo), e custava isso *a cada busca*. Agora a AUSÊNCIA também é cacheada — 30 s, curto
de propósito: quem acabou de abrir o Media Composer não pode esperar cinco minutos pelo
próprio projeto.

⛔⛔ **E ela era guardada só em `agora()`, não em `projeto_aberto()`** (revisão de
2026-09-22). O caminho da busca passa pela segunda **quatro vezes** — os recortes, "dá para
indexar", "estão prontos" e a taxa do projeto (`nle.taxa_do_projeto`, que abria o MC
direto). MEDIDO com o MC fechado: **8,47 s por busca**, quatro idas de 2 s para descobrir a
MESMA ausência, contra os 0,3–0,4 s de uma busca quente. Depois: **2,34 s na primeira,
0,19 s nas seguintes**. ⚠️ E isso vazava para a SUÍTE — o `conftest` isola o MC trocando
`escopo.projeto_aberto`, e `taxa_do_projeto` não passava por lá: **a suíte caiu de 67 s para
31 s**.

⛔⛔ **Sem projeto E sem foto, o recorte é o BANCO do editor** (2026-09-22). Antes era
`chaves=None` — sem filtro —, e a busca do Avid devolvia entradas do banco do Premiere, com
o nome de arquivo delas. A regra *"não sei ≠ nenhuma"* existe para que desconhecer o projeto
não esconda o acervo do editor; ela nunca autorizou mostrar o do OUTRO (é o mesmo teto que o
Premiere já tinha em `_so_o_banco`). ⚠️ Banco vazio continua sendo `None`: no primeiro dia
não há entrada nenhuma, e filtrar por um conjunto vazio faria a busca dizer "não achei"
sobre um cache que ela nem olhou.

⚠️ E isso é estado da MÁQUINA de quem roda a suíte: `tests/conftest.py` responde
"sem projeto" por padrão. Sem isso, um teste passava ou falhava conforme o autor ter o
Media Composer aberto — medido no dia em que a fila ganhou o filtro (a suíte foi de 12 s
para 40 s e um teste começou a falhar com as bins REAIS do editor).

⭐ A varredura que a busca faz **fica guardada**: quem procurou já deixou a coluna de bins
pronta para a aba Vetores. ⛔ Mas nunca uma varredura VAZIA por cima da última boa.

### ⭐ O vetor visual, e o que ele não promete

`midia/vetores.py` guarda um embedding por quadro amostrado (12 por master) em
`vetores.npy`, e `planos_parecidos` põe a busca na mão do modelo. O motor foi escolhido por
medida (`spikes/busca_visual.py`): **MobileNetV2 em ONNX, 14 MB, 99% contra 38% ao acaso** —
sem CLIP de 350 MB e sem torch.

- **Sem Pillow:** o ffmpeg decodifica e redimensiona numa chamada, entregando RGB cru que o
  numpy lê do buffer.
- O modelo mora na pasta `modelos\` do produto, **fora** da pasta de mídia: "apagar tudo"
  apaga o cache do cliente, não a peça do produto. É a única coisa aqui que precisa de
  internet.
- ⭐⭐ **O próprio plano fica FORA da busca.** Trazê-lo de volta faz qualquer motor acertar
  100%, inclusive um que comparasse o tamanho em bytes — foi o erro da primeira versão do
  spike. E uma linha por mídia, a do melhor quadro.
- ⚠️ A medida foi em **cena fechada**. "Ache a Personagem F em outra cena" continua por medir, e a
  descrição da ferramenta manda o modelo dizer isso ao editor.

Medido: vetorizar ~1,6 s por clipe; procurar 4–6 ms.
