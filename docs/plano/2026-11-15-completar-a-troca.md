# Completar a troca Avid → Premiere da Carta (proposta, 2026-11-15)

Pedido do autor: *"vamos completar a troca entre os softwares, depois voltamos para o arrasto"* — depois de notar que o
título "PRODUCAO-A" e os markers da PRODA_CORTE.00.2 não vieram. Página para análise: ver o artefato no handoff.

## O que ficou de fora na PRODA_CORTE.00.2 (relatório da importação, 27.0)

| o quê | ocorrências | hoje |
|---|---|---|
| título (Titler+, V3) | 1 | fora ("efeito sem mídia, título ou matte") + 2 transições dele |
| markers da timeline | ? | nem lidos: o leitor da bin devolve `markers: []` |
| enquadramento stretch | 9 | vai em tamanho real |
| ganho acima de +15 dB | 12 | cortado em +15 dB |
| Color Correction (V1) | 7 | fora |
| Stabilize (V1/V2) | 2 | fora |
| D-Verb (A5–A10) | 21 | fora |
| transição sem clipe escrito | 4 | fora (3 de som, 1 do título) |

## O que já se sabe (banco)

- Título do Avid LIDO da bin, texto e estilo (`modulos/conformar/motor/titulos/avid.py`; `protocolos/avb/dados/
  titler-plus-mqp.json`). Escrito no Avid e no Resolve. NO PREMIERE NUNCA FOI ESCRITO: o título do Essential Graphics é
  `AE.ADBE Text` com o texto e a fonte num blob FlatBuffers (`Source Text`), lido e conferido no pixel
  (`prproj/relink-e-geometria.md` §10.5); a cor no blob é `pendente`.
- Marker no Premiere pela API: `sequence.markers.createMarker(início, nome, duração)` (`api-extendscript.md`).
- Marker do Avid na bin: NÃO lido (`avb_bin/segmentos.py`, "marcadores … não"); o AAF tem leitor (`aaf/markers.py`).

## A proposta

1. **Markers** — (a) medir onde a bin guarda os markers da sequência (pyavb / REA) e ler nome, comentário, cor, trilha,
   tempo e duração; (b) escrever no Premiere depois do `importSequences` com `createMarker` (cor pelo mapa de cores),
   na sequência importada.
2. **Título** — pelo MOLDE, como o resto da Carta: o Premiere põe um título nativo na CÓPIA de trabalho (`importMGT` do
   "Basic Title" que vem com ele, ou o gráfico de texto), a gente lê como ele fica e escreve cada título do Avid clonando
   esse molde com o texto, a fonte, o corpo e a posição do Titler+. A cor fica `pendente` até ser medida.
3. **Stretch** — escala não uniforme do Motion (Scale Width / altura) em vez do tamanho real.
4. **Ganho acima de +15 dB** — o que passa de +15 vai para o Ganho do clipe (Audio Gain), que vai além.
5. **Efeitos sem equivalente** (Color Correction, Stabilize, D-Verb) — ficam de fora como hoje, mas cada um vira um
   MARKER na timeline do Premiere ("Avid: Color Correction (V1)"), numa cor própria: o editor vê ONDE refazer.

## Perguntas ao autor

1. Título pelo molde (fiel ao texto, fonte, corpo e posição; dá mais trabalho) ou pelo "Basic Title" via API (editável,
   estilo aproximado, rápido)? Recomendo o molde.
2. Efeitos sem par viram markers na timeline (recomendo), só o relatório, ou nada?
3. A ordem: markers → título → stretch/ganho → efeitos-marker? (Recomendo: markers primeiro — eles também servem ao 5.)

## Decisões do autor (2026-11-15)

1. **Título: o "Basic Title" pela API**, e MAPEAR o que falta com o piloto (o mapeamento anterior foi feito à mão, sem o
   piloto; no controle o mapa sai mais completo: fonte, corpo, cor, posição, alinhamento, sombra, fundo…).
2. **Efeitos sem par viram markers só se o editor pedir** — perguntar na importação (encher a timeline de markers de algo
   que o editor já sabe que não vem atrapalha).
3. **A ordem** segue: markers → título → stretch e ganho → os outros, com:
   - **Stabilize: traduzir**, não marcar. O Avid → Resolve já existe (`modulos/conformar/motor/estabilizacao.py`, a
     correção quadro a quadro lida da bin); para o Premiere a mesma correção vira keyframes de posição e escala do Motion
     (banco `prproj/relink-e-geometria.md` §10.5 sabe escrever keyframe).
   - **Cor (Color Correction)**: sessão DEDICADA no Avid, que também completa o De Lá Pra Cá (Conformar).
   - **Efeitos de áudio** (D-Verb etc.): plugin do MC não roda no Premiere nem o contrário (AAX × VST3/AU) — fora volume,
     ganho, transição e pan, informar "sem correspondência".

## Andamento

- ✅ Frente 1, MARKERS (2026-11-15, `f595f7e`): 23/23 na PRODA_CORTE.
- ✅ Frente 2, TÍTULO — o 1º caminho de ponta a ponta (2026-11-20, Windows, Premiere 26.5.2): o mapa do `Source Text` vale
  no 26 (o blob é o mesmo do 23.6), ESCRITO e reaberto com 22 valores conferidos no painel; o "Importar para o Premiere"
  leva o título do Avid como clone de um gráfico-molde do app (`carta/moldes/titulo 26.prproj`). PRODA_CORTE.00.2 no
  `EDITOR TITULO v03` (`9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-20 CARTA TITULO NO PREMIERE 2026 WINDOWS/`): "PRODUCAO-A"
  na V3, quadros 735–934, com os DOIS dissolves (772 clipes, 118 transições, nada da V3 de fora), 18 s.
  ⚠️ Mudança de decisão, dita: a decisão era "o Basic Title pela API" — no 26 o `importMGT` dele vem VAZIO, então o
  título nasce do molde (como o merged).
  ✅ O Titler+ LEGACY com o ESTILO (2026-11-20): o JSON em UTF-32 do efeito (fonte, corpo, cores, borda, sombra, fundo)
  + a escala (0,85) e a linha de base (0,5278) de params sem nome — `modulos/conformar/motor/titulos/avid.py`
  (`estilo_legacy`), que serve também o Resolve. Medido contra o export do Avid (`PRODA_CORTE.02.mov`, 35 s): o Premiere
  (`EDITOR TITULO v05`) põe "PRODUCAO-A" em x 551–1367 (Avid 551–1368) e o centro das maiúsculas em 532,5 (Avid 532,5).
  ⚠️ As letras do Premiere saem ~2 px maiores de cada lado com o MESMO espaçamento (motor de texto; contorno e fundo
  desligados no painel, conferido). ⬜ A escala e a linha de base vêm de UMA amostra (`hipotese`); a sombra (6) e a
  borda na unidade do Avid, sem medida no Premiere (preta sobre preto: invisível neste título). ⬜ Títulos com estilo lido (Titler+ atual, MQP): o código converte corpo, cor, alinhamento, posição,
  contorno e sombra, mas sem nenhum caso real ainda — as unidades de contorno, sombra e posição são `hipotese`.
  ⬜ Moldes para o 23/25; o 26.0.2 (Mac) abrindo o molde do 26.5.
- ✅ STRETCH (2026-11-20, 26.5 Windows): a escala NÃO uniforme da mídia para o quadro (B001 2K DCI 2048×1080 →
  largura 93,75 %, altura 100 %), no Motion de um molde feito pelo Premiere na cópia (`cicloMontar`, linha `esc`;
  `entrega_prproj.molde_de_esticar`). Mídia do tamanho do quadro: nada muda e nada é dito. PRODA: os 9 esticados, o
  enquadramento conferido no quadro 300 contra o export do Avid (a diferença que sobra é a cor: Color Correction, fora).
- ✅ GANHO > +15 dB (2026-11-20): o Volume vai até +15 dB e o RESTO vai no Audio Gain do clipe — `<Gain>` no
  `AudioClip`, fator linear (medido pilotando Clip › Audio Options › Audio Gain…: 9 dB → 2,818). PRODA: os 12 clipes de
  +24 dB (12 do clipe + 12 do subclipe) saem com Level +15 e Audio Gain 9 dB (lido pela API).
- ✅ STABILIZE → WARP STABILIZER (2026-11-20, decisão do autor: "estabilizador → estabilizador"; se não der, um efeito
  Transform à parte, NUNCA o Motion do clipe). Depois do `importSequences`, na sequência do editor (o QE pede o projeto à
  frente): `cicloEstabilizar` — Method Position (o Avid rastreia um ponto), Result Smooth Motion, Smoothness = filtro × 100
  (`hipotese`), Framing Stabilize-Crop-Auto-scale (o Auto-Zoom). O Premiere analisa sozinho. PRODA: os 2 aplicados e
  analisados (`EDITOR TITULO v08`).
  ⚠️ PARECIDO, NÃO IGUAL (medido contra a correção do Avid recalculada pela conta do lab — resíduo 0,1 px contra o render
  do MC — porque o export `PRODA_CORTE.02.mov` é de outra versão do corte e não serve de referência ali): V1 (quase não
  treme) ±2 px e −0,2 % de escala; V2, onde o Avid corrige ±12 px, o Warp fica a 4–10 px dele e amplia 1,2 % a mais.
  ⬜ Para igualar: INJETAR o rastreio do Avid na análise do Warp (`PremiereFilterPrivateData`, zlib, os cantos por quadro
  no `Mesh` — lab B19, ainda não decifrado inteiro) ou o Transform com keyframes (exato, a conta do lab). Decisão do autor.
- ✅ ÁUDIO SEM CORRESPONDÊNCIA (2026-11-20): todo efeito de som que não é volume/ganho/transição/pan é dito pelo nome —
  "efeito de áudio D-Verb: sem correspondência no Premiere (A7)" — INCLUSIVE no clipe OFFLINE (antes o efeito do clipe
  offline sumia do relatório: os 21 D-Verb da PRODA estão em efeitos sonoros que não estão nesta máquina). As transições
  desses clipes passam a dizer "transição de clipe offline" (eram "sem clipe escrito": as 43 da PRODA, A5–A16).
  ⚠️ Pan: lido (`PanVolumeEffect.pan`, 16384 = centro — `hipotese`, os 153 da PRODA no centro) e AINDA NÃO ESCRITO: fora
  do centro, é dito. ⬜ Ideia, não medida: o AudioSuite do Avid RENDERIZA o efeito em mídia própria (precompute) — levar
  esse arquivo no lugar do original preservaria o som do D-Verb.
- ⬜ Depois: cor (sessão no Avid).
