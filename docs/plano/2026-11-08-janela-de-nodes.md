# A janela de nodes

Autor e Claude, 2026-11-08. **Proposta, nada construído.** O autor decidiu trocar os cards em sequência pela tela de nodes e pediu para planejar antes de executar.
Continua `2026-11-08-agentes.md` e substitui as fases B2, B4, D e E de lá. Organograma: ver o artifact "Janela de Nodes" no handoff.

## O desenho escolhido (autor, 2026-11-08)

Protótipo: https://claude.ai/artifact/5SKARWXQQ1nBq6M4dNUeCS. Substitui o desenho do organograma; o visual é o do primeiro mock (`TEyJRqy2YyiWWfWzkzRBDZ`).

- **Lateral em duas metades**, separadas por uma linha: Fluxos de trabalho em cima, Agentes de IA embaixo. Cada uma com a lista e, no limite inferior, dois botões tracejados (Criar e Importar), como o "Adicionar Câmera" do Sincronizar.
- **Todos os painéis redimensionáveis**, inclusive a divisão entre as duas metades.
- **Clique simples seleciona; clique duplo abre** no painel central.
- **Fluxo:** a tela de nodes.
- **Agente:** editor de texto do `.md`, com número de linha e linhas pares e ímpares em cores alternadas. Somente leitura: quem altera é o agente de IA pelo chat, e o botão Editar libera a edição livre.
- O chat fica em espera enquanto o editor edita o texto, para os dois não mexerem no mesmo arquivo (confirmado).
- **Navegação nos nodes:** arrastar no vazio move o quadro (ferramenta de mão); zoom com nível e botões + e − no canto inferior direito.
- **Botão + no canto inferior esquerdo**, com opções; por enquanto "Adicionar Node".
- **Selecionar e apagar:** Delete ou Backspace apaga o node selecionado.
- **Ligação manual:** um nó em cada extremidade do node, visível só com o node selecionado e o mouse em cima; puxa a linha até outro node.
- **Executar fluxo** roda do primeiro node ao último. CORRIGE (autor, 2026-11-08): o "Executar node" saiu; sem a cadeia até ele, não faz sentido.
- **O node cresce na horizontal**, com o texto centrado na altura fixa. Linhas também se selecionam e apagam com Delete.
- **Propriedades do node (proposta):** clique duplo abre os parâmetros na aba Propriedades do painel direito. Cada campo diz de onde vem o valor, e isso já é o que o formato do plano sabe: valor fixo, `{parametro}` (perguntar ao executar) ou `{passo.campo}` (de outro node). O que a operação não deixa mudar aparece travado para a edição manual.
- **Recebe e Entrega (autor, 2026-11-08):** as Propriedades têm, no topo, um card recolhível com o que chega ao node e, no fim, um com o que sai e para onde; cada um lista todas as ligações. Clique duplo num item leva àquele node.
- **"Ajustar no chat" (autor, 2026-11-08; nome provisório):** carrega o node no chat, com a marca dele acima da caixa de texto, para pedir mudanças, inclusive no que está travado. A mudança volta como proposta, com Aceitar e Recusar.
- ⚠️ **O que isso exige no código:** hoje `converter_para_proxy` só aceita projeto, pasta e destino; codec e 1080 são constantes (`resolve_proxy.CODEC`, `ALTURA`) e a conferência reprova o que não for ProRes Proxy. Para o chat poder mudar, a ferramenta precisa receber esses valores e a conferência passar a comparar com o valor pedido. Outro codec ou altura precisa de medição no Resolve antes de valer. O chat só muda o que a operação aceita; o resto ele diz que não dá.
- ⛔ Lição do protótipo: o clique simples não pode redesenhar a lista, senão o botão some antes do segundo clique e o duplo clique nunca chega.

- **A conferência por código fica DENTRO do node do agente** (autor, 2026-11-08): não é peça na tela, e por isso ninguém a apaga sem querer. A peça "Conferência" do organograma sai da biblioteca.
- A marca acima da caixa do chat diz `node:` ou `agente:` antes do nome; a caixa cresce com o texto até um teto (rolagem só vertical); toda mensagem de mudança diz o nome do node ou agente alterado.

As decisões em aberto abaixo foram confirmadas pelo autor: tudo em nodes, peças não executáveis travadas, o chat propõe e o editor aceita, nunca paralelo no mesmo programa.

## O que existe hoje (medido no código, 2026-11-08)

- `servico/fluxo.py` roda uma LISTA de passos, com pausa e retomada; `depois_de` e `se` são recusados em `validar`.
- `{passo.campo}` já liga a saída de um passo à entrada de outro, mas é texto: 52 ferramentas (23 escrevem) declaram entradas e nenhuma declara saída.
- Os agentes declaram entradas e saídas (A2).
- O chat da aba Fluxos (`conversa: "fluxos"`) existe e pode ir para a janela.

## Peças propostas

Entrada · Passo (sem IA) · Agente (usa IA, não escreve; a conferência por código mora dentro dele) · Se (campo de saída, sem expressão) · Perguntar (o cartão da A3).

## Regras

- O formato continua sendo o plano em JSON no `.md` das receitas. As posições ficam à parte: receita antiga abre sem mudar, e sem posição o programa organiza sozinho.
- A tela só oferece o que o executor roda; o resto aparece travado até a fase dele.
- Catálogo curado: portas e programa só das peças em uso, não das 52.
- Cada peça declara o programa que ocupa. Nunca duas ao mesmo tempo no mesmo programa (medido: carregar, consultar e fechar colados derrubam o MC 5 de 5).
- Toda volta tem teto, e o agente na volta sempre passa pela conferência por código embutida nele (medido em 2026-09-12: a conferência sozinha, sem regra contra o degenerado, aprovou 16 cortes no plano aberto).
- `sempre_pergunta` não aparece como peça.
- Fluxo pronto roda pelo ☰, sem abrir a janela.
- Arrastar com pointer events, não com o drag-and-drop HTML: o soltar difere entre WebView2 e WebKit (matriz de plataforma).

## Fases

| fase | o quê | pronto quando |
|---|---|---|
| N0 | Prova da tela: desenhar as 3 receitas, zoom e arrastar, no Windows e no Mac; escolher biblioteca ou fazer a nossa | a receita de 8 passos aparece e move bem nos dois |
| N1 | Formato e catálogo: posições, portas, programa | as receitas antigas abrem sem mudar uma linha |
| N2 | Editar em linha, chat ao lado, Conferir | criar e salvar um fluxo só com o mouse e outro só pelo chat |
| N3 | Executor em grafo: `se`, paralelo seguro, retomar; nodes acendem | um fluxo com ramo roda, para e retoma |
| N4 | Agentes como nodes, Perguntar, volta com teto, preço antes | metadado, dúvida, pergunta e volta rodam e param no teto |
| N5 | Fluxos no ☰, andamento no chat, aba Fluxos sai | um leigo roda um fluxo sem abrir a janela |
| N6 | Importar e exportar | um fluxo vai de uma máquina à outra |
| G | Corte por IA, plano próprio | saber se a volta melhora o corte ou só gasta |

### N0 feita no Windows (Chrome), 2026-11-08; ⬜ falta a janela nativa e o Mac

- **Sem biblioteca, decidido.** O código do protótipo faz tudo o que foi aprovado e a pasta do painel não tem bundler. Nenhuma biblioteca foi medida: o custo próprio medido não deixou motivo. Arrasto: **0,16 ms de CPU por movimento com 9 nodes, 0,22 ms com 120** (script + layout + estilo; `Performance.getMetrics`, não inclui pintura). O teto do executor é 30 passos.
- `servico/grafo_do_fluxo.py` transforma a receita em nodes e ligações, sem mudar uma linha dela: ordem = sequência; dado = `{passo.campo}` (dado do node logo antes vira etiqueta na linha de ordem, não uma segunda linha). O gerente entra como node antes de `PASSOS_REVISADOS`, porque o executor o chama de verdade.
- Organização automática na página (precisa da largura real): linhas da esquerda para a direita; entre zooms a menos de 10% do melhor, mais colunas. Posição só em memória até a N1.
- Só leitura: Propriedades mostra Recebe, Entrega e a origem real de cada campo. Criar, Importar, +, Executar, Compartilhar, Salvar, Editar e o chat aparecem travados até a fase deles. Ainda sem alças de ligação e sem Delete (N2).
- Prova com mouse real por CDP: 31 de 31, nas 3 receitas, a 1280×760 e 900×520.
- ⬜ **Falta para fechar a N0:** ver no WebView2 pelo `ABRIR-APP` e rodar no WebKit do Mac (`svg` com `overflow: visible` e `setPointerCapture` não foram vistos lá).

⬜ Mudar a escala com a roda do mouse não está no desenho aprovado e não foi feito.

### N1 feita, 2026-11-08

- **Posições:** `servico/posicoes_dos_fluxos.py`, em `<dados>/posicoes_dos_fluxos.json` (`POST /oficina/posicoes`), por fluxo: `{nos: {id: [x, y]}, vista}`. Só grava depois de um gesto do editor. Sem posição de TODOS os nodes, a organização automática refaz. Falha ao gravar aparece no quadro.
- **Catálogo:** `servico/catalogo_de_pecas.py`, 12 peças: programa e saídas. As saídas foram lidas no retorno de cada ferramenta. As ENTRADAS não entram: já são o esquema da ferramenta (a N2 as usa). Um teste exige que toda peça das receitas da casa tenha ficha e todo `{passo.campo}` esteja declarado.
- `sincronizar` ocupa "o NLE que o fluxo abriu por último". Programa dado por `{parametro}` fica vazio, pois só se sabe ao rodar: a N3 precisa resolver isso antes de usar o campo.
- Provado: as 6 receitas desta máquina (3 da casa, 3 do editor, com nome antigo de operação) abrem com ficha completa e sem mudar uma linha; posição e zoom voltam depois de recarregar (mouse real por CDP).
- A N2 trouxe o item "Organizar" no botão +, que resolve o caso de voltar à organização automática.

### N2a feita, 2026-11-08: editar só com o mouse (⬜ N2b, o chat ao lado)

- ⭐ **Decisão do autor: "Executar node" saiu.** Rodar um node solto não faz sentido sem a cadeia até ele. Fica só **Executar fluxo**, que roda tudo (N3).
- Bordas: o node sem nada chegando é verde-água; o último, âmbar. Vêm das ligações de ordem, então durante a montagem os soltos também aparecem marcados.
- Adicionar Node (as peças do catálogo), puxar e apagar ligações, Delete/Backspace, Organizar, renomear (clique duplo no título), Criar Fluxo.
- Propriedades editáveis: entradas do esquema da ferramenta; cada campo é Não usar, Valor fixo, Perguntar ao executar (vira parâmetro da receita) ou De outro node (lista as saídas declaradas). Lista e objeto (`fontes`, `operacoes`) são JSON por enquanto.
- `servico/grafo_do_fluxo.py`: `para_passos` transforma o desenho na lista do executor e `receita_da_janela` monta o `.md`, pelo mesmo escritor e leitor de sempre. Rotas `/oficina/conferir` e `/oficina/salvar`.
- ⛔ Executor ainda roda uma linha: ramificação, node solto ou volta são recusados pelo Conferir, com a frase (até a N3).
- ⛔ O gerente não é passo e não se apaga: sai junto do sync. Reaparece sozinho ao salvar um sync novo.
- Salvar fluxo da casa grava a versão do editor na pasta dele, com o mesmo nome (regra já existente); o arquivo da casa não muda. Descrição e "Quando as condições mudam" são mantidas.
- A linha de dado (verde-água) não se apaga: vem de um campo, e a tela diz para mudar o campo.
- Prova com mouse e teclado reais: criar do zero, ligar, Conferir recusar e aprovar, salvar, reler: 30 de 30.
- O editor de `fontes` em JSON é provisório; o chat é o caminho natural para esse campo.

### N2b feita, 2026-11-08: o chat ao lado (com ela, a N2 está pronta)

- ⭐ **Um terceiro papel, `oficina`** (fio, endereço MCP e persona próprios), separado da aba Fluxos, que executa. Ferramentas: `listar_receitas`, `o_que_quer_dizer`, `propor_fluxo` e `propor_mudanca_no_node` (`mcp/ferramentas/oficina.py`).
- ⭐ **O modelo não grava nem executa.** As duas ferramentas de propor só mostram. Aceitar muda o desenho como edição NÃO salva; quem grava é o botão Salvar. Por isso não há cartão do portão.
- ⛔ A proposta passa pela conferência do executor ANTES de aparecer: a que não roda volta ao modelo com o motivo. O que a operação não aceita (codec e altura do proxy, `sem_supervisao`) é recusado na ferramenta.
- O que está na tela, com o que ainda não foi salvo, vai a cada pergunta (`janela` no corpo do `/conversar`) como dado.
- "Ajustar no chat" põe a marca `node:` acima da caixa. Toda proposta diz o nome do node ou do fluxo; depois de decidida, quem escreve a frase é o programa, não o modelo.
- Provado com turnos REAIS, sem nada do editor tocado (dados temporários): fluxo novo só pelo chat em 8 a 10 s, aceito, conferido e salvo; pedido de codec recusado com a frase, sem proposta; bin de um node trocada, com aviso espontâneo de que o Sincronizar seguia procurando a outra bin.
- ⬜ **Alterar AGENTES pelo chat não foi feito:** os agentes moram na pasta do programa, e alterar pede um lugar para a versão do editor e a regra de agente de fora (fase B4 do plano de agentes). O botão Editar e o chat seguem travados na tela do agente.
- ⬜ "Ajustar no chat" não muda codec e altura: precisa de parâmetros novos na ferramenta e medição no Resolve (seção "O desenho escolhido").

### N3 feita, 2026-11-08: o executor segue o desenho (⬜ falta rodar com os programas de verdade)

- O plano ganhou `depois_de` e `se` (`fluxo.py`). Sem `depois_de`, o passo depende do anterior: as receitas em linha são a mesma lista de sempre, e um teste exige a ida e volta das 3 da casa sem mudar um campo.
- ⭐ **A condição mora na linha:** clique duplo nela e "Só quando…" (uma saída declarada do node de origem: tem conteúdo, está vazio, é igual a). Linha com condição é tracejada em âmbar, como no protótipo. Sem expressão.
- Passo com condição não atendida, ou com todos os antecessores fora, fica `fora`, e o fluxo segue. Junção roda se ao menos um antecessor rodou. Campo que a peça não devolveu PARA o fluxo e diz, em vez de escolher um caminho.
- ⛔ **Sem simultaneidade real, decisão desta fase:** um node de cada vez, em ordem topológica. Dois ramos sem condição rodam um depois do outro. Motivo: abrir o MC e salvar usam o mouse (piloto), e nenhuma receita tem dois caminhos que ganhariam tempo. A regra "nunca dois no mesmo programa" fica cumprida por construção. O campo `programa` do catálogo fica pronto para o dia em que valer.
- **Executar fluxo:** só com o fluxo salvo; abre o formulário (as perguntas, com o diálogo do sistema para caminho) e o clique é o consentimento, sem cartão e sem turno de modelo (`POST /oficina/executar`). Os nodes acendem pelo `/fluxo` a cada 1 s; a faixa diz quem roda e tem Pausar, Cancelar, Retomar, Tentar de novo e Pular.
- O gerente roda dentro do passo que confere: `Passo.revisado` acende o node dele e depois o do sync.
- **Conferir ganhou aviso que não barra:** sync que procura uma bin que nenhum node anterior cria (o risco achado na N2b). Só compara nomes escritos; `{passo.campo}` fica de fora.
- Organização automática: em linha continua em linhas; com ramo, em colunas pela profundidade.
- Prova com mouse real e operações SIMULADAS (`provar_n3`): ramo, pausa, falha, tentar de novo, 29 de 29. Testes do executor com o estado relido do disco.
- ⬜ **Falta rodar pelo botão com os programas de verdade** (Resolve, MC, Premiere): o caminho até `executar` é o mesmo das receitas, mas o botão novo nunca rodou uma operação real.

### N4 feita, 2026-11-08: agente como node, Perguntar, volta com teto, preço antes

- **Agente como node:** `entender_metadados_da_diaria` entra no catálogo com `agente=`; a conferência por código já mora dentro dela. Ela ganhou `respostas`, que chegam ao agente dentro de `memoria`, sem mudar o contrato do `.md`.
- **Perguntar** (`perguntar_ao_editor`): peça do executor. O fluxo vira `perguntando`, a thread sai e a fila fica livre; `POST /fluxo/responder` retoma, mesmo depois de o serviço reiniciar. Sem pergunta nenhuma, não interrompe. O modelo não vê a peça no chat, só a usa ao propor um fluxo.
- **Volta:** linha puxada para trás. `volta: {para, teto, se?}` no passo; teto de 1 a 5, padrão 2. Repete um trecho contínuo da lista, e a saída da rodada anterior fica em `saidas_da_volta`. No teto, para, diz e só oferece Pular ou Cancelar.
- ⛔ **Volta não repete node que grava** (`validar`): é o que impede um sync rodar duas vezes.
- Volta ao PRIMEIRO node: o começo do fluxo passa a ser o primeiro node do desenho (achado na prova).
- **Preço antes do clique:** no formulário de Executar, o pior caso com todas as voltas (`custo_de_ia`).
- Prova: tela com agente simulado e o agente REAL numa diária do editor (`D:\AUDIOS ANALISAR\24Y07M18`, serviço e dados isolados), 20 de 20: 4 a 5 perguntas pertinentes, ~4,2 a 4,8 mil tokens e 10 a 17 s por rodada (a estimativa na tela: 4.840 e 17 s).
- ⬜ **O que o fluxo aprende não fica salvo:** `gravar_na_memoria_da_producao` é `sempre_pergunta` e, por regra, não é peça. As regras aprovadas ficam na saída do node, mas a leitura do sync só muda quando vão para a memória. Precisa de decisão do autor.
- ⬜ Peças de agente: só o de metadado. Outro agente precisa da sua ferramenta com a conferência dentro.
⬜ Fase C (agentes operadores) segue como está no plano de agentes: medir o custo antes.

### N4b feita, 2026-11-08: o node Confirmar na memória

- **`confirmar_na_memoria`:** peça do executor, como o Perguntar. O fluxo vira `perguntando`, a thread sai, e o cartão mostra forma, molde, exemplo, o que ele disse não saber e, sem memória achada, pergunta a produção. Sem nada a confirmar, ninguém é interrompido.
- ⛔ **Só o clique grava** (`POST /fluxo/confirmar`), pela mesma função do chat, com `_conferir_gravacao` de novo nos arquivos. `gravar_na_memoria_da_producao` continua `sempre_pergunta` e proibida como passo; o modo automático não responde pelo editor. Reprovou: o cartão fica, com o motivo.
- ⛔ As regras saem do que está guardado no PASSO, nunca do corpo do pedido. Só entra `aprovada: true`.
- "Não sei" entra pelo `sobre` da pergunta, que o executor guarda ao responder. Node Perguntar fora do caminho não derruba o Confirmar.
- Apelido: se o projeto aberto tem outro nome, um interruptor desligado pergunta se ele é desta produção. Sem isso a regra não vale no sync daquele projeto.
- Volta não repete este node (`escreve=True`).
- Prova: `spikes/janela_de_nodes/provar_n4b.py`, mouse real, agente e gravação de verdade numa diária real em dados temporários. ⭐ Achou que o nome digitado num cartão vazava para a execução seguinte, e por isso a chave do formulário agora leva o id da execução.
- ⬜ Com mais de uma rodada de perguntas, só os "não sei" da última chegam ao cartão.
- ⬜ Nenhuma receita da casa usa o node ainda.

### N5 e N6 feitas, 2026-11-08

- **N5:** a aba Fluxos saiu. Os fluxos salvos ficam no menu ☰ do chat; o formulário mostra os passos e o preço, e o clique em Executar é o consentimento (`/oficina/executar`, sem cartão e sem turno). O quadro do andamento fica acima da conversa, e perguntas e confirmação são respondidas ali, sem abrir a janela. ⛔ Com um cartão à vista o quadro não se redesenha, para não apagar o que o editor digita. Criar e editar fluxos é na janela Fluxos e Agentes; a persona de planejador ficou sem tela, e o código dela não foi removido.
- **N6:** Compartilhar grava `<nome>.md` numa pasta escolhida no diálogo do sistema, com a posição dos nodes numa seção que o leitor ignora. Importar passa pela MESMA conferência do executor: nada roda, não substitui fluxo existente (entra com `-2`), e caminho fixo de outra máquina vira aviso.
- Prova: `spikes/janela_de_nodes/provar_n5n6.py`, mouse real, operações simuladas. ⬜ Diálogo real do sistema não exercitado na prova.

## Decisões em aberto (autor)

1. Fluxo em linha também vira node? (recomendação: sim)
2. Antes de o executor ramificar, peças travadas? (recomendação: sim)
3. O chat propõe e o editor aceita? (recomendação: sim)
4. Paralelo no mesmo programa? (recomendação: nunca)
