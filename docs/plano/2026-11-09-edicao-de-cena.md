# Edição de cena por agentes

Autor e Claude, 2026-11-09. É a fase G do plano `2026-11-08-janela-de-nodes.md` (corte por IA). Material: cena 7 de *PRODUCAO-A*, já sincronizada e com subclipes.

## O pedido do autor

Um fluxo que edita uma cena inteira, com um agente por função: Mídia, Transcrição, Roteiro, Revisor, Diálogo, Diretor, Editor e Continuista. O roteiro é obrigatório: sem ele o fluxo não avança.

## Decisões

- **L/J é característica do agente Editor** (autor, 2026-11-09). O `montar_corte` do chat continua só com corte seco, como decidido em 06 e 07/11. Entendimento a confirmar se o autor corrigir.
- **Decupagem no Mac mini.** Roteiro em `.docx` no teste; PDF fica para depois do spike (exige dependência nova).
- **O corte final do curta é só PLACAR.** Nenhum agente o vê: todo literal do pedido é material de cópia (medido em 2026-09-23).
- **Todos os agentes são conselheiros.** O código prepara a entrada, o agente devolve JSON, o código confere e escreve. Evita o tipo operador (piso medido de ~40 mil tokens).
- **Quem julga no fim é o editor.** Diretor e Continuista dão parecer; não bloqueiam a entrega.

## O fluxo

| # | Etapa | Quem faz | Para quando |
|---|---|---|---|
| 0 | Roteiro presente, bins salvas | código | sem roteiro não avança |
| 1 | Agente de Mídia: classifica e garante quadros, vetores, decupagem | código; IA só no ambíguo | |
| 2 | Agente de Transcrição: garante a fala e o mapa por arquivo | código | |
| 3 | Agente de Roteiro: estrutura, lugar, personagens, beats | código + IA | |
| 4 | Agente Revisor: roteiro × captação | código mede, IA explica | diferença grande: pergunta ao editor |
| 5 | Agente Diálogo: exclui equipe, preserva improviso, mapa por fala e bin de falas | IA propõe, código confere | |
| 6 | Agente Diretor: intenção por beat (quem em quadro, onde segurar, b-roll) | IA | |
| 7 | Agente Editor: mapa de corte com L/J, tempo e silêncio | IA propõe, `conferir_o_mapa` confere | até 2 voltas |
| 8 | Agente Continuista: quadros de cada lado do corte, antes de escrever | IA com imagem | 1 volta ao Editor, sugestão |
| 9 | Parecer do Diretor | IA | 1 volta, depois entrega com ressalvas |
| 10 | `montar_corte` e gerente | código | |

⛔ Teto de voltas e cobertura por código: com recusas seguidas o modelo já foi de 33 para 10 momentos até passar (2026-09-15) e já colapsou 16 cortes num plano só (2026-09-12).

## O que falta construir

- Revisor: matriz fala × take e o critério numérico de parada. Teste negativo: roteiro da cena 4 contra a C07 tem de parar.
- Editor: o mapa precisa trazer pausa disponível antes e depois de cada opção, e a descrição do que se vê.
- Continuista: o turno magro só leva texto; seguir o modelo do decupador.
- L/J: abrir a recusa de `plano/esquema.py` só para este fluxo, e conferir que `conferir_o_mapa` aceita o deslocamento.
- Agente como node: hoje só entra no fluxo embrulhado numa ferramenta (`Peca.agente`).
- b-roll: a C07 não tem; essa parte não é exercitada aqui.

## A régua: a cena 7 no corte final

Fonte: `D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\PRODA_RELINKER_ALTA.aaf`, sequência `PRODA_CORTE.02.Exported.01`. Os subclipes têm outros nomes (`07-03-01`), mas chegam aos mesmos masters (UMID). Para ver: `PRODA_CORTE.02.mov`, de 07:28 a 09:08.

- 99,2 s (2.378 quadros a 23,976), 8 planos, 4 takes: P01-002, P02-002, P02-004, P03-001.
- 7 cortes de imagem, 4 com som deslocado:

| Corte | Imagem (quadro) | Som (quadro) | Diferença |
|---|---|---|---|
| 1 | 11324 | 10994 | som 330 antes |
| 2 | 11518 | 11522 | imagem 4 antes |
| 3 | 11705 | 11705 | junto |
| 4 | 12201 | 12217 | imagem 16 antes |
| 5 | 12616 | 12616 | junto |
| 6 | 12787 | 12800 | imagem 13 antes |
| 7 | 13033 | 13033 | junto |

⚠️ A leitura da trilha de imagem saiu 42 quadros adiantada; descontados, três cortes coincidem exatamente com o som. Leitura de spike.

O placar compara escolhas, não igualdade: duração, número de planos, takes usados, quanto L/J, onde a reação entra.

## Primeira metade no papel (2026-11-09, Sonnet 5.5, `spikes/edicao_de_cena/no_papel.py`)

Saídas em `D:\MIDIAS DE TESTES\9 SAIDAS DOS APPS\_CICLO ASSIST\2026-11-09 EDICAO C07`.

| Etapa | Tempo | Custo | Resultado |
|---|---|---|---|
| Roteiro | 8 s | US$ 0,023 | estrutura e beats |
| Revisor, C07 | 13 s | US$ 0,041 | segue: 16 de 16 falas; separou P02-001, P02-001.1 e P03-002 |
| Revisor, roteiro da cena 4 contra a C07 (negativo) | 19 s | US$ 0,063 | para: cobertura 0 pelo código e pelo agente, com a pergunta certa |
| Diálogo | ~3,5 min | não anotado | 20 momentos (29 com variantes), conferência de `separar_falas` fechou na primeira, sem volta; 44 segmentos excluídos |

⚠️ **Limite da linha de comando:** o pedido vai como argumento do `claude -p`, e o Windows corta em 32.767 caracteres. O teste negativo chegou a 30.752 antes do teto na amostra. Na versão de produto, medir o pedido ou enviar por outro caminho.

⚠️ **Conflito de regras achado:** o autor quer preservar erros de ator, e a conferência de `separar_falas` exige ordem dentro do take. Em C07_P02-003 os segmentos 30 a 32 são uma fala interrompida e refeita; o agente deixou de fora e avisou em `deixadas_de_fora`.

## Segunda metade no papel (2026-11-09)

Decupagem micro da C07 no Mac: 39 trechos, 0 falhas, 36,8 min, 12 vetores por take.

| Etapa | Tempo | Custo | Resultado |
|---|---|---|---|
| Diretor (intenção) | 14 s | US$ 0,047 | leitura da cena e intenção por beat |
| Editor | 95 s | US$ 0,180 | 15 planos, conferência fechou de primeira |
| Continuista | 14 s | US$ 0,083 | 0 problemas em 14 cortes, por imagens enviadas pelo stdin |
| Parecer do Diretor | 33 s | US$ 0,075 | não aprovou: 4 pontos |
| Editor, revisão | 69 s | US$ 0,156 | 15 planos, 3 L/J; conferência fechou |

Placar, 220,1 s e 15 planos contra 99,2 s e 8 planos no corte final. L/J: 3 (24, 30, 36 quadros) contra 4 (até 330 quadros).

**O que a comparação mostrou:**
- ⛔ O corte final tira boa parte do diálogo: as falas 5, 6, 7, 8, 12 e 13 ficam entre 25% e 50% das palavras do roteiro, e várias outras são encurtadas. Nenhum agente tem autoridade para cortar fala, então o fluxo entrega uma montagem completa, não um corte fino.
- ⛔ O Editor faz campo e contracampo fala a fala, com planos de 10 a 20 s. O próprio Diretor apontou. O corte final segura planos longos sobre várias falas e usa uma reação de 330 quadros.
- ⛔ **Erro da decupagem virou decisão.** A decupagem de P02-002 diz "mulher de costas com casaco vermelho", que é a Personagem F em primeiro plano, de costas (conferido no quadro). O Diretor levantou a dúvida e o Editor trocou o take por causa dela. P02-002 é justamente o take mais usado no corte final.
- ⚠️ O Continuista não roda de novo depois da revisão do Diretor: sua nota é da versão anterior. Quadros de cada corte conferidos a olho em dois pares: pessoa e lado corretos.
- ⚠️ A régua não pode entrar no pedido: dar 99 s como tempo-alvo seria vazar o corte final.

## Versão 2 (2026-11-09, depois das decisões do autor: o Diretor pode cortar fala; sem tempo-alvo)

Saídas em `...\2026-11-09 EDICAO C07 v2`. Mudanças: Diretor com `cortes_de_fala`; só ele corta fala (o código reprova corte do Editor); a decupagem deixou de ser motivo para descartar take; o Editor prefere planos sobre várias falas; o Continuista roda por último, na versão entregue.

| | v1 | v2 | corte final |
|---|---|---|---|
| Duração | 220,1 s | 176,3 s | 99,2 s |
| Planos | 15 | 7 | 8 |
| L/J | 3 (até 36 q) | 3 (até 30 q) | 4 (até 330 q) |
| Falas retiradas inteiras | 0 | 1 (a 13) | ver abaixo |

Custo da v2: ~US$ 0,44, ~3 min.

- O Diretor propôs cortar as falas 3, 9 e 13. Ao ler a montagem, viu que tirar a 3 e a 9 quebrava a lógica e voltou atrás. ⛔ O código só deixava acrescentar corte; a lista do parecer passou a substituir a anterior.
- ⛔ **Limite:** o Editor só retira fala inteira. O corte final encurta por dentro das falas e emenda o som dentro do mesmo take, com a imagem cobrindo. Falta granularidade por segmento.
- ⚠️ Correção exagerada: há planos de 45,7 s e 33 s. Reações longas por L/J continuam tímidas.

## O que o autor ouviu na v2, e a v3 (2026-11-09)

O autor assistiu no MC: "…fissional" repetido em 01:00:40:15, "comigo" em 01:01:00:16, "é você que ainda mostra muita resistência" em 01:01:28:02; e a cena deveria abrir em plano aberto.

⛔ **Causa (defeito do spike):** a pausa disponível só via o vizinho que terminava antes do ponto de corte. Fala encostada saía da conta, a pausa parecia enorme e a folga pegava a voz do vizinho. Medido nos três pontos; achou um quarto (fim do plano 6 com "Não é tão simples, Personagem F", fala cortada).

Conserto: pausa pela voz dos vizinhos, palavra a palavra (`VOZ_DEPOIS` 8 q, `VOZ_ANTES` 3 q); entrada e saída recuam para fugir da voz vizinha; `vazamentos` reprova voz de outro segmento dentro do plano. Regra do autor no Diretor e no Editor: abrir no plano mais aberto.

v3: 200,1 s, 8 planos, abre em P01-001, L/J de 48 e 48 q. ⚠️ O Diretor cortou as falas 3 e 13 e desfez as duas no parecer: nenhuma fala cortada.

`ouvir_o_corte.py` junta o som real e transcreve. Na v2 pegou 1 das 3 repetições apontadas (mais o "Não é tão simples"): fragmento de palavra o ASR não ouve. Na v3: nenhuma repetição real (o único aviso, "drama", é a réplica do Personagem G). ⚠️ Ele não substitui ouvir.

⬜ **Precisão por palavra:** o ASR guarda início e fim de cada palavra, mas 77% das 2.531 palavras da C07 estão coladas à seguinte (a borda é estimada) e 106 duram mais de 0,8 s. Próximo passo proposto: refinar a borda pela energia do WAV, por canal quando houver.

## v4: a borda medida na lapela (2026-11-09)

`spikes/edicao_de_cena/bordas.py`: início e fim da voz medidos no envelope da lapela de quem fala. Números no banco, `decupagem-por-transcricao.md` §8.7.

- 627 de 660 bordas medidas. Emendas do editor humano dentro de voz: ASR 5/20, lapela 2/20.
- A conferência `vazamentos`, rodada sobre as versões anteriores: **v2, 4** (as 3 que o autor ouviu e o "Não é tão simples, Personagem F"); v3, 1; v4, 0. ⚠️ Corrige o que foi dito da v3: o aviso de "drama" era vazamento real, somado à réplica.
- v4: 177,1 s, 8 planos, abre em P01-002, fecha em P01-001, L/J de 30 e 40 q. Só a fala 3 saiu. ~US$ 0,84.
- ⚠️ Sem a fala 3, o "O que você está pedindo" perde o pedido: o Diretor apontou isso na v2 e aceitou na v4.
- ⚠️ O Continuista marcou 6 de 7 cortes em `atencao`: os dois atores olham para o mesmo lado da tela. Os takes são os mesmos do corte final, então parece vir da captação; o autor confere.
- ⬜ Falta levar ao produto: a borda medida como estágio de cache (`midia/`), e o pedido por stdin no `turno_magro`.

## v5 (2026-11-09): a fala 3 de volta, por decisão do autor

Bin `C07 CORTE AGENTES v5`: 192,9 s, 11 planos, L de 36 e 40 q, nenhuma fala retirada, conferência sem vazamentos. ~US$ 0,30 (revisão e Continuista). `no_papel.py --devolver 3` tira a fala da lista de cortes.
⚠️ O Editor refez mais do que o pedido: de 8 para 11 planos. ⚠️ O Continuista não repetiu a nota de olhar da v4 (6 de 7 em `atencao`, agora 0): falta validá-lo.

## Ordem de construção

1. Decupagem e vetores da C07 (`spikes/edicao_de_cena/preparar_c07.py`).
2. Spike no papel, do Roteiro ao mapa de corte: sem nodes e sem escrever em bin.
3. Levar ao MC uma vez e o autor olhar.
4. Só então virar nodes.
