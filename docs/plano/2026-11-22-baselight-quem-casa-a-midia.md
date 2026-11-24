# Baselight: quem casa a mídia? — proposta de laboratório com pegadinhas (2026-11-22)

## A resposta curta
**Hoje quem casa é o Baselight**, nos dois casos. O Ciclo Assist só entrega a montagem:
- **PRODUCAO-C:** o nosso xmeml leva o caminho completo de cada arquivo, mas o `bl-conform` procura pelo NOME do
  arquivo (filtro "Filename") dentro das pastas que passamos; o caminho que escrevemos não decide nada.
- **PRODUCAO-A:** o AAF do MC não tem caminho nenhum; o Baselight casou pelo nome do clipe / da fita (100 %).

A inteligência do Conformar — **duração como veto** (o seu critério: o proxy/offline acompanha a duração do original),
identidade de essência (UMID), TC drop-frame lido certo, e o **empate vai para o editor** em vez de um palpite — **não
participou**. Funcionou porque os nomes dos dois casos são únicos.

## Onde o Baselight sozinho já tropeçou (medido)
- PRODC (18ª rodada): com o in fora do arquivo, a variante do `--multiples` casou pelo tempo de GRAVAÇÃO (91 %) e trocou
  arquivos — calado.
- O filtro "None" desiste com "More than 20 events with massive ambiguity".
- Ele escolhe a melhor variante pela % de eventos achados; não diz, evento a evento, por que escolheu aquele arquivo.
- AAF com Locator: ele tira o prefixo do Locator e procura o resto do caminho nas pastas; pelo UID da Avid casou 0 %.

## Como garantir que os arquivos certos cheguem
"Quem decide é o Ciclo; o Baselight obedece; depois a gente confere":
1. **O Conformar casa** (o matcher de sempre: nome, UMID, TC, duração como veto; ambíguo → o editor decide).
2. **Entrega sem margem de escolha**: cada evento com o CAMINHO exato. Candidatos a medir no laboratório: o modelo de
   arquivo por fonte do `bl-conform` (`ft=` com `%D`/`%W`, a pasta e o nome do PRÓPRIO evento), um `--src` por pasta
   resolvida, ou nomes únicos por evento.
3. **Conferência depois do conform**: pela FLAPI, o arquivo de cada plano × o que o Conformar decidiu. Diferente →
   trocar (o fundo já é trocado por BLG) ou marca "[Ciclo]" + o editor.

## A rodada de laboratório (mídia sintética, cada caso é uma ilha)
Receitas no `laboratorio-de-midia` — cada clipe mostra no quadro QUEM é (nome, câmera, duração, quadro) — e uma montagem
no MC e outra no Premiere com as pegadinhas. Mede-se: **Baselight sozinho × Ciclo decide + Baselight obedece + conferência**.

| # | pegadinha | o que se espera do Ciclo |
|---|---|---|
| P1 | mesmo nome, TC zerado, durações diferentes (cartão A × B) | a duração separa |
| P2 | mesmo nome, mesmo TC, mesma duração, conteúdo diferente | AMBÍGUO → o editor (nada de palpite) |
| P3 | proxy com outra taxa (60p × 23,976) e duração arredondada | a duração em SEGUNDOS, com tolerância |
| P4 | daily renomeado (nome ≠ do original) | UMID / TC + duração |
| P5 | nome igual com caixa, acento NFD ou extensão diferentes | normalização do nome |
| P6 | número no fim do nome ("…_298.mov") | arquivo, não sequência |
| P7 | rótulo DF × NDF | TC certo |
| P8 | reel/tape vazio ou trocado | não depender da fita |
| P9 | o mesmo clipe em duas pastas de dia (cópia idêntica) | qualquer uma serve — dizer qual |
| P10 | sequência de imagens que é VÍDEO (DPX/EXR/TIFF, um arquivo por quadro) | um clipe só, não N imagens (autor, 22/11) |

## Perguntas ao autor
1. A rodada entra AGORA (antes de fechar o PRODUCAO-A) ou depois do relatório final?
2. As pegadinhas da tabela cobrem o que você já viu em produção? Falta alguma (ex.: troca de câmera no meio do cartão)?
3. Se o Ciclo não conseguir forçar o caminho no `bl-conform`, aceitamos "Baselight casa + Ciclo confere e corrige depois"?

## Decisões do autor (22/11)
1. A rodada de laboratório entra DEPOIS do PRODUCAO-A, para o relatório final sair completo.
2. Pegadinha a mais: sequência de imagens que é vídeo (P10).
3. "Entrega com alerta é melhor do que entrega com erro calado": se o caminho não puder ser forçado, o Baselight casa e
   o Ciclo confere e corrige/marca depois.
