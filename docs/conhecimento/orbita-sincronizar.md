# A ponte com o Órbita (módulo Sincronizar)

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

## ⭐⭐ A ponte com o Órbita: ele sincroniza, nós escolhemos o material

`sincronizar` (até 2026-11-07, `sincronizar_com_o_orbita`; escreve; **Premiere E Media Composer** — no MC recebe a PASTA do projeto com as bins da diária, e `subclipes: por_cena` faz as bins `CENAS/` no mesmo pedido; corrigido em 2026-10-31, esta frase dizia "só no Premiere") + `cicloassist/sincronizar.py` (era `orbita.py`; o módulo Sincronizar, ex-Órbita, desde a fase 3 do plano um app só). O Ciclo
Assist pega os arquivos da bin que o editor nomeou, o **Órbita** agrupa em câmeras e som
(heurística dele) e sincroniza; o progresso vem do `/prproj/status` para o painel daqui.

- Autenticação: o `plugin-token` na pasta de dados do Órbita — o mesmo dos painéis dele.
  ⚠️ O app sorteia um a cada arranque, então `401` manda **reler o arquivo** e repetir uma vez.
- `409` é **resposta normal**: ele atende um trabalho por vez.
- ⛔⛔ **Nunca `GET /nlejob`.** Aquela fila é do PAINEL do Órbita, e quem lê TIRA o trabalho
  dela: o painel nunca receberia a montagem, e o sintoma seria "o Órbita disse que terminou e
  nada apareceu no projeto". A rota que usamos só ESCREVE nela.
- ⛔ **A montagem da sequência é dele** — fazer a nossa seria a segunda implementação de algo
  validado em produção. O que mudou em 2026-09-18 é que agora nós ALCANÇAMOS o painel dele:
  `POST /api/v1/nlejob` (escrito no Órbita, `.dev/PONTE-CICLO-ASSIST.md` §7) enfileira a
  montagem daquele sync, e `GET /api/v1/montagem?id=` conta o fim. O editor pede no chat e
  recebe a timeline; antes o trabalho parava no mapa, a três cliques do fim.
- ⚠️⚠️ **O painel do Órbita precisa estar ABERTO no Premiere** (o CEP só roda com o painel
  aberto, e é o poll dele que vem buscar). Isso é conferido no `/api/v1/info` **antes do
  cartão**: o sync leva minutos, e descobrir a ausência no fim é fazer o editor esperar por
  nada. Se ele fechar o painel no meio, o mapa volta inteiro com o que houve — nunca se
  perde um sync por causa da montagem.
- ⛔ **E o mapa não viaja daqui para lá:** vai o `job_id` do sync que o próprio Órbita rodou.
  O formato do job do painel é assunto dele, e a ponte não quebra quando ele mudar.
