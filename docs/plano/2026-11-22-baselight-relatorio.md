# Baselight: relatório da etapa (21–22/11/2026)

Página: https://claude.ai/artifact/4kanc6RGKvBo9uXkMaTiqr (fonte e imagens em `docs/plano/2026-11-22-baselight-relatorio/`).
Detalhe de cada medida: `MIDIAS DE TESTES/9 SAIDAS DOS APPS/_BASELIGHT/estudo/DIARIO.md` (27 rodadas). Banco:
`bancodedadosnles/plugins/baselight/README.md`.

## Conclusão
O PRODUCAO-C (R04, `ISOLADO/PROJETO/PRODC_FINAL_isolado_1.prproj`, Premiere 26.5) chega ao Baselight 7.0.3 conformado
nos originais, com retime, Motion, máscaras e títulos, **sem clicar**: **132 de 133 pontos** contra o vid ref
(`ISOLADO/REFERENCIA/PRODC_Trailer_v02_RESGATE.mov`), pior quadro ≥ 0,87 nos trechos com máscara. O ponto que falta (08:18,
"THE") é o tracking do título do Premiere, que o Text do Baselight não tem. Cor fica com o colorista (decisão do autor).

## A cadeia (ferramentas em `estudo/ferramentas/`)
1. Leitor do Conformar → `WSD1_leitura.json` (111 segmentos).
2. `xmeml_do_leitor.py --com-velocidade --fonte-na-taxa-da-timeline --com-imagens` (imagem com in 0; desligado fora).
3. `bl-conform --space Video_Full --multiples` (100 % por nome e quadro de fonte).
4. `traduzir_prodc.py aplicar` — retime Time×Time e Motion por BLG (74 planos).
5. `mascaras_prodc.py gerar/gravar` — 10 composições (aninhadas; trechos pela shape), um processo por plano.
6. `titulos_prodc.py inserir/montar` — Text em camada Composite, pelo .blscene editado + `bl-import` (7 títulos).
7. `marcar_e_stills.py` — 5 marcas "[Ciclo]".
8. `render_scene.py` + `conferir_prodc.py` + `conferir_trechos.py`.

## O que não foi (marcas na scene `BL10_WSD24T`)
| quadro | o quê |
|---|---|
| 74 | P&B (Black & White) do LOU_7310, V3 |
| 117 | Gaussian Blur do PRJ-0006-252, V3 |
| 162 | camada de ajuste na V4 (conteúdo não lido) |
| 193 | títulos: sem o tracking do Premiere |
| 535 | P&B do LOU_7310, V4 |
Sem marca, por decisão: a cor do offline (Lumetri, LUTs, a camada de ajuste sobre a sequência).

## Próximos passos e riscos
- Levar a cadeia ao Conformar (saída "Baselight"); o lado do MC no nível do PRODC; blur e camada de ajuste; atualização de corte.
- Riscos: trial até ~05/12; o .blscene editado é formato sem documentação (medido no 7.0.3); fonte do Creative Cloud
  ativa na máquina do Baselight; a referência de 10/10 não tem o ajuste de 6 px na máscara de 01:02 (18/11).
