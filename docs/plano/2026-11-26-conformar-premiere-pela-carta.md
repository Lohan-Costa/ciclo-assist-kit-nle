# O Conformar monta no Premiere pelo escritor da Carta (2026-11-26)

Decisão do autor (2026-11-26): "nada de marcador a menos que seja impossível a tradução"; "toda a tradução já
estabelecida deve ser fonte de conhecimento da Carta também"; entre fechar/reabrir o projeto do editor (1) e montar pelo
caminho da Carta (2), **o 2**. Página: https://claude.ai/artifact/6rtGJSxs2N2dSspVpdThwh

## Por que

- O modo Premiere do Conformar monta pelo ExtendScript (`premiere_montagem.plano` → `/premiere/montar` →
  `premiere_host.jsx::dlpcMontar`). O ExtendScript **não alcança o Time Remapping** (medido: um clipe com a curva mostra
  só Opacidade e Movimento), e hoje viram MARCADOR: rampa, congelado, **transições** e **títulos** (o placar do painel
  diz "transições (marcador)", "títulos (marcador)").
- A Carta (`cicloassist/carta`) escreve o `.prproj` e importa só a sequência no projeto do editor
  (`importar_premiere.importar_timeline`): já traduz transição (dissolve e crossfade), título, velocidade constante,
  reverso, Time Shift, **rampa e congelado** (B34: 48/48), offline no lugar, merged, subclipe, cor básica, stretch,
  estabilizador e markers — sem fechar nada do editor.
- A leitura é a MESMA: o `do_avid` da Carta lê os segmentos do leitor do Conformar (`avb_bin.segmentos`); o
  `resultado["segments"]` que o Conformar recebe tem a mesma forma (bin ou AAF).

## O que muda

1. **`carta/timeline.py`**: o laço de `do_avid` vira `trilhas_de_segmentos(segments, fps, chave)` — o mesmo para a bin
   (Carta) e para o `resultado` do Conformar (bin ou AAF). `do_avid` passa a chamá-lo; nada muda para a Carta.
2. **Uma Carta OCULTA por envio** na pasta de trabalho do Conformar (`_recebidos()/<id>/carta`): uma referência por
   arquivo casado, com o arquivo que o **relink do Conformar** decidiu (o online no lugar do offline — a diferença do
   Conformar, que a Carta não faz) anexado na forma `original`. O item `sequencia` sai de `trilhas_de_segmentos` com a
   chave = a referência do arquivo casado. Plano sem arquivo aqui → offline no lugar (como a Carta faz).
3. **`sessao_receber` (destino premiere)**: em vez de devolver o plano do `dlpcMontar`, roda
   `importar_timeline(proj_oculto, item, chamar, forma="original")` pela ponte única (`premiere_ponte.chamar` → núcleo)
   e devolve o relatório da Carta (clipes, transições, velocidades, rampas, o que ficou de fora). O vídeo de referência
   entra como trilha a mais (como hoje).
4. **Painel**: o placar do modo Premiere passa a ler o relatório da Carta (`escrita`, `fora`, `offline_no_lugar`) — o
   "marcador" fica só para o que a Carta diz que ficou de fora.
5. **`dlpcMontar` e `premiere_montagem.plano`** ficam no código até a prova fechar; depois saem (um caminho só).

## Provas (cada uma fecha antes da próxima)

| # | bancada | o que prova | a régua |
|---|---|---|---|
| 1 | testes | `trilhas_de_segmentos` = o `do_avid` de antes (a suíte da Carta igual); a Carta oculta com os arquivos casados | suíte |
| 2 | B32 (12 casos de velocidade) | o Conformar pela Carta = o Premiere original | código de barras, 96/96 por caso |
| 3 | B34 (rampas) | rampa, rampa na curva, congelado pelo Conformar | 48/48 ×3 |
| 4 | B30 (EDL) | dissolve de imagem e de som (o feito à mão), WAV, 25p, nome longo, acento | os tempos das transições e dos clipes |
| 5 | B33 (som) | velocidade e reverso do som | posição da varredura (±2 ms) |
| 6 | PRODUCAO-A (real, Avid → Premiere) | uma timeline de produção inteira | contagem de clipes/transições/títulos; nada de marcador sem motivo |

## Decisões pendentes

- O **vídeo de referência** do Conformar: trilha a mais na mesma sequência (como hoje) — mantida.
- O Conformar recebe também **AAF** de outra máquina: a mesma `trilhas_de_segmentos`; a cor e o merged dependem do que
  o AAF traz (dito no relatório quando não vier).
