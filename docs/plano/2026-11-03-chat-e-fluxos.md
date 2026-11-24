# Chat e Fluxos: duas abas, um motor (2026-11-03)

## A decisão do autor

*"O chat é o local de pedidos mais diretos — 'separe as falas desses clipes baseado no roteiro anexado' é uma ação
imediata, algo que o editor quer resolvido na hora. O fluxo é quando existe um processo com mais etapas, que talvez
demore mais, e é o tipo de ação em que o editor até se ausenta da ilha para fazer outra coisa."*

| | **Chat** (aba Assistir, como hoje) | **Fluxos** (aba nova) |
|---|---|---|
| o pedido | "faça isto agora" | "rode este processo" / "transforme isto num processo" |
| o editor | está olhando | pode sair da ilha |
| o modelo | agente livre: chama as ferramentas uma a uma, se adapta ao que acontece | planejador: escolhe ou monta a RECEITA, preenche os parâmetros, mostra o plano |
| quem executa | o modelo, ferramenta a ferramenta (cada escrita no portão) | o executor (`servico/fluxo.py`), passo a passo, sem o modelo no meio |
| quando falha | o modelo vê o erro e decide na hora | o fluxo PARA e o conselho/o editor decide (`continuar_fluxo`) |
| o que sobra | o trabalho feito e um relato | o trabalho feito **e uma receita reaproveitável** |

## O que os registros mostraram (02/11, 21:46)

O prompt do teste da diária D01, no chat, com Sonnet 5.5. O modelo listou as receitas, conferiu o projeto (MC
fechado) e **parou**, dizendo que não dispararia de novo para não converter duas vezes. Duas causas:

1. ✅ **Consertado (03/11): um recado de outra conversa abriu a conversa nova.** A pergunta chegou com
   *"(entretanto: … rodar o fluxo 'Preparar a diária D01-exibicao' foi feito.)"*: era a aprovação de um fluxo
   anterior, guardada em `pendencias.json`, colhida ANTES da limpeza da visita. Hoje os recados são colhidos depois
   (`rotas._com_recados`) e a conversa que recomeça os descarta (`pendencias.descartar_recados`, na visita nova e
   no "Limpar conversa"). Testes em `tests/test_portao.py`.
2. ⬜ **O chat é empurrado para a receita.** A descrição de `executar_fluxo` diz *"use quando o pedido tem mais de
   um passo… você NÃO chama as operações uma a uma"*, e `listar_receitas` está no chat. Um pedido que nenhuma
   receita cobre exatamente (o do teste pede nome do projeto no Resolve, formato tirado da mídia convertida e a bin
   "subclipes") fica sem saída natural: ou a receita errada, ou nada.

## O levantamento: o chat alcança cada passo sem receita?

Sim, cada passo do prompt do teste tem uma ferramenta solta, com os parâmetros que o pedido usa:

| passo do pedido | ferramenta | o parâmetro que importa |
|---|---|---|
| abrir o Resolve, projeto "TESTE SIMULADO DR" | `abrir_programa` (resolve) / `converter_para_opatom` | `projeto` = nome (abre ou cria) |
| converter para o formato do MC | `converter_para_opatom` | `pasta`; devolve a pasta MXF |
| fechar o Resolve | `fechar_programa` | — |
| abrir o MC, projeto novo com o formato da mídia | `abrir_programa` (media_composer) | `formato` ("1080p/23.976") |
| câmera e som, cada um na sua bin | `importar_masters_opatom` + `som_direto_gerenciado` | `bin` |
| sync + subclipes na bin "subclipes" | `sincronizar_com_o_orbita` | `bins`, `subclipes: uma_bin`, `bin_dos_subclipes` |
| salvar e deixar visível | `salvar_tudo` | — |

⇒ O chat não precisa de receita para este pedido; ele precisava de **licença** para fazer passo a passo.

## Desenho

**Um motor.** Mesmo serviço, mesmo portão, mesmas ferramentas, mesmo executor de fluxo. O que muda por aba é a
persona, a lista de ferramentas e a conversa.

### Chat (aba Assistir)
- ⛔ Sai do chat: `listar_receitas`, `executar_fluxo`. Fica `continuar_fluxo` só enquanto houver fluxo parado que
  nasceu do chat? ⇒ Não: fluxo é da aba Fluxos; o recado do fluxo parado (`fluxo.recado()`) também sai do chat.
- A persona ganha uma linha: pedido de vários passos se faz passo a passo, conferindo o resultado de cada um antes
  do seguinte; nada de procurar receita.
- ⚠️ O portão continua: no chat cada escrita é um cartão (ou nenhum, no modo automático). Um pedido de 7 passos são
  7 cartões com o automático desligado — é o preço de "estou olhando", e é o argumento para mandar à aba Fluxos.
- ⭐ Ponte de mão única: terminado um trabalho de vários passos no chat, o painel oferece **"transformar em fluxo"**
  — leva para a aba Fluxos a sequência de ferramentas que rodou (com os argumentos), como rascunho de receita.

### Fluxos (aba nova, ao lado de Assistir)
- Em cima: as receitas (da casa e do editor), cada uma com o formulário dela — o caminho SEM IA que já existe
  (`POST /receitas/preparar`, o menu ☰ de hoje), agora com tela própria.
- No meio: o quadro do fluxo em andamento/parado (o `fluxo.js` de hoje, que sai da conversa).
- Embaixo: um chat de fluxos, com conversa PRÓPRIA (`CONVERSA_DOS_FLUXOS`, outra chave de sessão):
  persona de planejador, ferramentas `listar_receitas`, `executar_fluxo`, `continuar_fluxo`, as de LEITURA
  (estado do projeto, bins, ler_arquivo) e as novas de receita: `salvar_receita` (escreve — portão) e
  `conferir_receita` (lê). ⛔ Sem as ferramentas de ESCRITA soltas: aqui quem executa é o executor.
- O mesmo prompt do teste aqui vira: "a receita mais próxima é `preparar-diaria-no-mc`; faltam o nome do projeto
  no Resolve, o formato do MC tirado da conversão e a bin 'subclipes'. Montei a receita nova com esses três
  parâmetros — salvar e rodar?" → cartão do plano → o editor sai da ilha → o quadro conta o fim.
- O conselho (`motor/conselho.py`) e o modo automático continuam valendo só aqui.

### O que separa as duas conversas
- ⛔⛔ Recados não atravessam: aprovação de fluxo vai para a conversa de Fluxos; aprovação de cartão do chat, para
  o chat. Hoje `pendencias` tem uma fila só — a pendência precisa saber de que conversa nasceu (`conversa=`).
- ⛔ Um turno por vez continua sendo regra do SERVIÇO (a chamada de `pedir_confirmacao` não diz de que turno é).
  ⇒ Com as duas abas, um turno no chat e um no Fluxos ao mesmo tempo é recusado ("estou respondendo na outra
  aba"). O FLUXO rodando no fundo não é turno — o chat continua livre enquanto ele roda.
- `registro.ferramenta(...)` ganha a dimensão da aba (como já tem `nles=`), e o filtro de ferramentas por sessão
  passa a ser `(nle, aba)`.

## Fases

- **F0 ✅** o recado da conversa anterior (feito, 03/11).
- **F1 ✅ (03/11, provada na máquina: o prompt da D01 no chat, Sonnet, passo a passo até o relatório final)** o chat livre (`servidor.FORA_DO_CHAT`; `listar_receitas`
  diz para sugerir o menu ☰ → Fluxos prontos até a aba existir): `listar_receitas`/`executar_fluxo` e o recado do fluxo fora do chat; a linha da persona.
  Provar: o prompt do teste no chat, Sonnet, MIDIAS SIMULADAS → o modelo faz os 7 passos sozinho (automático
  ligado) e relata o que entrou, sincronizou e ficou de fora. E "separe as falas destes clipes pelo roteiro"
  continua igual.
- **F2 ✅ (03/11)** a aba Fluxos (sub-aba ao lado de Assistir, `fluxo.js`; o ponto na aba acende com fluxo
  correndo/parado/pausado/interrompido; o cartão de fluxo vai para a aba; o menu ☰ voltou a ser só de atalhos): receitas com formulário + quadro do fluxo (mover o que já existe), sem chat ainda.
- **F3 ✅ no código (03/11), ⬜ reprovar com o modelo** o chat de fluxos: conversa própria
  (`CONVERSA_DOS_FLUXOS`), persona de planejador (`claude.PERSONA_DOS_FLUXOS`), MCP com papel pelo ENDEREÇO
  (`…/mcp/<segredo>/fluxos`, `servidor.com_papel`, `DOS_FLUXOS`), pendências e recados com a conversa de origem,
  `salvar_receita` (conferida antes do cartão), o palco do painel trocando com a aba (nunca no meio de um turno).
  Prova de 03/11 (Sonnet, o prompt da D01): listar_receitas → plano próprio; a conferência barrou o 1º; o 2º chegou
  ao cartão com três defeitos que falhariam ao rodar (`media composer`, `{conv.formato}` inexistente, `bins` texto)
  e sem oferecer a receita — os três consertados na origem e a persona ajustada. ⬜ Rodar de novo o mesmo prompt
  (a assinatura estava em 99% do limite semanal; parei os testes com o modelo).
  Original: conversa própria, persona de planejador, `salvar_receita`/`conferir_receita`,
  pendências com a conversa de origem.
  ✅ **Provada em 04/11** (Sonnet, o mesmo prompt, aba Fluxos, automático desligado): o 1º plano barrado
  (argumentos inventados: `criar`, `diaria`, `media composer`), o 2º no cartão SEM os três defeitos
  (`media_composer`, `{conv.formato}` que agora existe, `bins` lista `["{camera.bin}", "{som.bin}"]`,
  `subclipes: uma_bin` + `bin_dos_subclipes: subclipes`). Montou à mão (a receita não nomeia o projeto do
  Resolve nem a bin dos subclipes) e ofereceu guardar. ⬜ Alavanca: `listar_receitas` mostrar os
  ARGUMENTOS de cada operação (a 1ª tentativa erra por não vê-los).
- **F3b ✅ (04/11, autor) o botão "Salvar" no cartão de plano feito à mão** — *"para o usuário que não
  conhece o app pode não saber que isso é possível"*: Não · Pode fazer · Salvar. Sem turno do modelo:
  `POST /receitas/salvar-plano {id}` → `receitas.do_plano` (caminho vira campo SEM o valor de hoje;
  texto fica com o de hoje como padrão; valor que contém o de outro parâmetro SEGUE ele — "CAMERA D01"
  vira "CAMERA {diaria}" no passo; título com `{param}`; nunca substitui receita existente, `-2`).
  Salvar não decide o cartão. Plano vindo de receita (`receita_de`) não mostra o botão. A persona aponta
  o botão; `salvar_receita` fica para receita com outro formato, quando o editor pedir.
  ✅ Provado no app: Salvar → receita "seu" na lista → formulário → D02 → cartão → **fluxo 8 de 8**
  (Resolve abrir 41,9 s · conv 8,7 s · fechar 13,7 s · MC abrir 65,4 s · câmera · som 8,0 s · sync 15,3 s,
  4 de 4 takes · salvar 13,6 s). Os subclipes foram para "subclipes 2" (a "subclipes" da D01 existia; o
  Órbita não escreve por cima).
- **F3c ✅ (04/11, autor) a aba Fluxos refeita** — *"perdemos o progresso de cada etapa… falta pausar e
  cancelar… barra de progresso… um card preso como memória… fluxos prontos está bem ruim"*. A causa era
  de LAYOUT: o quadro (✓, passo em curso, Pausar/Cancelar) já existia, mas morava no alto de uma tela que
  rola, e o cartão aprovado descia a tela. Agora: o quadro PRESO no topo (`position: sticky`); o cartão
  aprovado SAI e o quadro assume; o passo em curso em destaque; a BARRA quando o passo informa fração
  (sync do Órbita: "Procurando na mídia do Avid… 17%", visto); fluxo terminado em outra sessão não volta
  (`vistosVivos`); a aba abre como o Assistir — "Fluxos de trabalho salvos", 3 atalhos (os do editor
  primeiro) + "ver todos"; clicar pergunta **Carregar** (formulário) ou **Editar** (preenche a caixa para o
  planejador). ✅ Provado no app com a D03 (8 de 8; a receita salva, só a diária trocada).
  ✅ (04/11, mais tarde) **Cancelar NO MEIO** de um passo que ESPERA um programa de fora (o sync do
  Órbita, o conform do De Lá Pra Cá): `pendencias.conferir_cancelamento`, chamado só nesses laços — nunca
  no relato geral, que também roda no meio de CloseBin → gravar → OpenBin. Provado com a D04: parou 4 s
  depois do pedido, passo ■ "cancelado no meio… o Órbita termina do lado dele" — e terminou (a `D04.avb`
  apareceu 14 s depois; o Órbita não tem como cancelar um sync, nem pelo Abortar do painel dele). Nos
  outros passos, Cancelar e Pausar valem ao fim do passo, e o botão diz isso.
  ✅ `listar_receitas` com os passos INTEIROS e `operacoes` (os argumentos de cada uma, numa linha):
  provado — o mesmo prompt da D01 usou a receita salva direto, 2 chamadas, ZERO recusas (antes: 1 recusa).
  ✅ Atalhos com a origem ("seu"/"da casa") e uma linha da descrição (títulos iguais se distinguem).
  ✅ Defeito achado na prova: `executar_fluxo` por RECEITA chegava ao cartão em JSON cru; o portão agora
  o transforma no plano inteiro (`portao._plano_da_receita`).
- **F4 ✅ (04/11, provada no app)** a ponte "transformar em fluxo" a partir do chat. O serviço anota cada ESCRITA
  que rodou no chat e deu certo (`historico.anotar_feito`, nos dois caminhos: o MCP no automático e o clique no
  cartão); com duas ou mais, o painel oferece no fim do turno (e do cartão) **Transformar em fluxo** →
  `POST /receitas/do-chat` → `receitas.do_chat` (um passo por escrita; texto igual à SAÍDA de um passo anterior vira
  `{passo.campo}`; caminho e texto livre viram parâmetro, um por valor; valor de enum fica fixo; objeto aninhado
  fica literal) → `do_plano` (o mesmo do Salvar) → receita do editor, que abre PRIMEIRA e aberta na aba Fluxos
  (Carregar · Editar). Sem turno do modelo. Provado: "crie a pasta F4 TESTE e salve tudo" (organizar_bins +
  salvar_tudo, automático) → oferta → receita → aba Fluxos. Na sequência da diária (teste), a pasta MXF da
  conversão e as bins do sync saem ligadas às saídas dos passos.
  ✅ Provada numa diária (04/11): D05 passo a passo no chat → receita → D06 pelo formulário, 8/8. O título passou
  a ser a 1ª frase do PRIMEIRO pedido da conversa; parâmetro com sufixo volta ao nome-base.

## Para decidir com o autor
- ✅ DECIDIDO (autor, 03/11): o chat SUGERE o fluxo pronto, sem disparar.
- ✅ DECIDIDO (autor, 03/11): um turno por vez no serviço — o segundo, na outra aba, é recusado; fluxo no fundo
  não ocupa o chat.
- ✅ A persona dizia "painel na lateral do Media Composer, ~400 px": hoje "janela estreita (~600 px), ao lado do
  programa de edição" (a janela do app tem 600 px, `app.json`).
