# Baselight: a máscara e a entrega conferida (proposta, 2026-11-21)

Página: https://claude.ai/artifact/J1fx5LC4cmRuuozhqo381y. Continua `2026-11-21-baselight.md`.

## Respostas ao autor
- **Exportar o quadro do Baselight e comparar com o vid ref:** sim. Hoje: render da scene inteira pela FLAPI (ProRes,
  ~90 qps) e comparação QUADRO A QUADRO com o vid ref (código de barras no laboratório; em produção real, pela imagem,
  como os 133 pontos do R04). Para a entrega: stills por plano (`do_export_still`, ainda não usado) lado a lado com o ref.
- **Markers com comentário:** sim, `Scene.add_mark(quadro, categoria, nota)` pela FLAPI (ainda não testado).
- **O tutorial (Look #10):** é o caminho. A máscara no Baselight é uma camada de SHAPE com dentro/fora; o painel de blend
  escolhe o que entra de cada lado. A FLAPI insere shape por SVG (`insert_shape_layer_from_svg`, estática); a animada
  vai pelo BLG, a decifrar como o Transform e o Retime.

## PRODUCAO-C × PRODUCAO-A
| | PRODUCAO-C (R04, Premiere) | PRODUCAO-A (PRODA_CORTE.00.2, MC) |
|---|---|---|
| tamanho | 89 planos, 6 trilhas, nests | 771 clipes, 116 transições, 36 merged |
| máscara | 12 de OPACIDADE, animadas (83 keyframes) | nenhuma conhecida |
| velocidade | 9 rampas | a levantar |
| cor | 72 Lumetri + 2 camadas de ajuste com LUT | 7 Color Correction |
| pronto | leitor do Conformar (máscaras animadas, rampas, nests, escala X≠Y); mídia, projeto e vid ref ISOLADOS no SSD; BLG de retime e transform | a rota AAF inteira (provada no sintético) |
| falta | a rota prproj → Baselight; Motion do Premiere → Transform (unidades); máscara de opacidade = composição ENTRE TRILHAS; shape animada no BLG; nests achatados | originais (só convertidos MP4 e 5 BRAW); não testa máscara |

## Recomendação
1. **Máscara no laboratório primeiro** (B14_MASCARA, sintético): shape estática por SVG → uma feita na interface
   (pilotada) para ler o BLG → shape animada → a máscara de OPACIDADE como composição entre trilhas → render × render do
   Premiere.
2. **PRODUCAO-C**: o primeiro "Daqui pra Lá → Baselight" a partir do .prproj (lista de cortes do leitor; FLE pela
   interface enquanto o CLI recusa — REA), BLG por plano (retime, transform, máscara), markers nos planos a conferir,
   render × vid ref e o relatório visual (still Baselight × ref por plano).
3. **PRODUCAO-A** pelo AAF se o PRODC travar na composição de trilhas (mesma entrega conferida + markers, sem máscara).

## Perguntas
1. Começar pela máscara no laboratório antes do PRODC?
2. Markers: só nos planos com problema/aviso, ou um por plano (com o resultado da conferência)?
3. A cor do PRODC (Lumetri, LUT): só aviso no marker, como Halation/NR — o colorista refaz?

## Decisões do autor (2026-11-21)
1. Sim: a máscara no laboratório primeiro, depois o PRODUCAO-C (PRODUCAO-A de reserva).
2. Markers SÓ nos planos com problema.
3. A 1ª versão DESCARTA a correção de cor: é o trabalho do colorista. Motivo: a cor do offline foi feita sobre o
   CONVERTIDO (que pode ter LUT aplicada); no Baselight, com a mídia online, o material pode estar em log — a correção não
   casaria. Manter a cor (para apresentar as pontuações artísticas) fica para uma versão futura.
