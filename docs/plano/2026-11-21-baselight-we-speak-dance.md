# Baselight: o PRODUCAO-C (proposta, 2026-11-21, noite)

Continua `2026-11-21-baselight-mascara-e-entrega.md`. Escrita com o autor ausente ("siga o máximo que puder"), depois dos
cinco passos da máscara no laboratório. Página: ver o handoff.

## O que o laboratório já provou (B14, scenes BL07_MASCARA / BL07_MASCARA_V; diário, rodadas 9–13)
| passo | resultado |
|---|---|
| in do fundo | offset do `GR_SequenceRop` em s, `(in + 0,5)/fps`: exato em 16 planos |
| suavidade | raio = a·F/W, borda da shape b·F px para fora; erro máximo de alfa 0,010–0,033 de F10 a F500 |
| animada | um keyframe por quadro em TODOS os cantos (só o 1º ponto decide se a curva anda): ≤ 1,0 px |
| frente dentro | `GR_ShapeRop … Z 3 t f t` inverte; ⛔ a 1ª bandeira do `BEZ_FilledShapeInterp` derruba o `flapid` |
| espaço de trabalho | a mistura é no espaço da scene: T-Log entorta a curva (0,548/0,458), vídeo é simétrico (0,50) — constantes por modo em `modos.json` |
| markers e stills | `add_mark` (nota "[Ciclo] …", GMMA_RED) e `do_export_still` dos quadros marcados (JPEG, cor certa) |

## O PRODUCAO-C em números (leitor do Conformar, `ISOLADO/PROJETO/PRODC_FINAL_isolado.prproj`, `PRODC_Trailer_v02_RESGATE`)
89 planos de vídeo: V1 63 · V2 10 · V3 11 · V4 3 · V6 1 · V7 1. Taxas: 60 qps 34, 25 qps 32, 100 qps 14, 23,976 9 (tempo
real numa timeline de 23,976). Motion em 89, 10 rampas, 7 títulos, 3 Gaussian Blur, 68 Lumetri (fora da v1: decisão do
autor). **11 máscaras de opacidade** (leitura em `estudo/conform/PRODC_leitura.json`), todas com a FRENTE DENTRO e animadas
quadro a quadro, curtas (1–50 quadros):

| trilha | clipe | quadros | vértices (com alça) | F / E | embaixo |
|---|---|---|---|---|---|
| V2 | LOU_7310 | 4 | 6 (3) | 201 / 0 | 1 clipe |
| V2 | JUL_7671 | 5 | 4 (0) | 10 / 0 | 1 |
| V2 | JUL_7644 | 25 | 4 (0) | 10 / 0 | 1 |
| V2 | C0296 | 8 | 10 (1) | 50 / 0 | 1 |
| V3 | LOU_7310 | 6 | 4 (0) | 50 / 0 | 3 (V1+V2) |
| V3 | PRJ-0006-252 | 5 | 11 (6) | 50 / 16 | 2 (V1+V2) |
| V3 | PRJ-0006-252 | 1 | 11 (8) | 50 / 16 | 1 (V2) |
| V3 | PRJ-0006-252 | 1 | 11 (8) | 50 / 16 | 1 (V2) |
| V3 | LOU_7237 | 50 | 4 (0) | 10 / 0 | 2 (V1+V2) |
| V4 | PRJ-0006-308 | 7 | 6 (5) | 50 / 0 | 2 (V1+V2) |
| V4 | LOU_7310 | 6 | 4 (0) | 50 / 0 | 3 (V1+V2+V3) |

## Os três problemas novos (o laboratório não tinha)
1. **A montagem.** O `bl-conform` recusa o nosso FLE; o XML do Premiere perde as rampas (BL06). Proposta: um xmeml GERADO
   pelo nosso leitor só como transporte da montagem (corte, trilha, in/out, taxa) — como a bancada da B14 já faz — e
   tudo o que o XML perde (retime, Motion, máscara) pelos BLGs, que já estão provados. Alternativas: FLE pela interface
   (pilotado) ou o REA no `bl-conform`.
2. **O fundo de várias trilhas.** Em 6 das 11 o que fica atrás da máscara são 2 ou 3 trilhas EMPILHADAS; o Background
   Replacement pega UMA sequência. Opções: (a) uma camada de Background Replacement por trilha de baixo, cada uma com a
   matte do plano dela (a pilha refaz a composição); (b) dividir o plano mascarado nos cortes de baixo — resolve corte em
   sequência, não empilhamento; (c) achatar só o trecho de baixo num plate renderizado (perde o online daquele trecho).
   Recomendo estudar (a) no laboratório (B14 com V1+V2 atrás) e usar (b) onde bastar.
3. **Forma qualquer, com alças.** Converter vértice + alças do Premiere (fração da fonte, ANTES do Motion) para os pontos
   do Baselight (x, y em fração da largura + ângulo/comprimento de tangente, no espaço do quadro?), e recuar a curva
   b·F px para DENTRO (a suavidade do Baselight sai toda para fora: 17–175 px nos F do PRODC). Antes do offset de curva:
   ver na interface se a shape tem suavidade INTERNA (há `shape_inner_outer_gang` escondido nas preferências) — se
   tiver, o recuo não é preciso.

## Ordem proposta
1. **Pilotar ~15 min** numa scene do lab: (i) a suavidade interna existe? (ii) uma shape Bézier com alças feita à mão,
   para ler o formato das tangentes no `.blscene`; (iii) a shape segue o Motion do plano ou o quadro?
2. **Laboratório B14b**: uma máscara com alças, uma sobre clipe com Motion (escala/posição) e o fundo de 2 trilhas.
3. **PRODC sem máscaras**: montagem por xmeml + BLGs (retime, Motion), conferida pelos 133 pontos × vid ref e stills.
4. **As 11 máscaras do PRODC**, markers só nos planos com aviso, relatório.

## Perguntas ao autor
1. Aceita o xmeml GERADO por nós como transporte da montagem enquanto o FLE não passa no `bl-conform`?
2. Fundo de várias trilhas: estudar (a) — camadas por trilha — antes de recorrer a (c)?
3. Espaço de trabalho: traduzir sempre para o da scene que o colorista abrir (T-Log é o padrão), ou propor que o
   conform crie a scene em vídeo?
4. O render ProRes sai com os patamares esticados (o still não): investigar o deliverable ou conferir só por stills?

## Decisões do autor (2026-11-21, noite)
1. Sim: o xmeml GERADO por nós como transporte da montagem enquanto o FLE não passa.
2. Sim: estudar primeiro uma camada de Background Replacement por trilha de baixo.
3. Manter o espaço de cor da MONTAGEM (scene em vídeo no conform); a troca para T-Log fica com o colorista, que domina o
   ajuste. Do offline direto ao online haverá variação de cor natural; quando o editor já trouxe a timeline para o online,
   a visualização fica mais próxima. ⇒ a tradução da máscara usa o modo `video_*`.
4. Investigar: o export (render) e os stills têm de sair IGUAIS.
