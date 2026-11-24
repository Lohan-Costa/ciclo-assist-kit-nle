# PRODUCAO-H — a cor de um trabalho real contra os testes sintéticos (proposta, 2026-11-20, Mac)

## 1. A máscara retangular do Premiere (a tarefa que vinha do Windows)

- O projeto é `laboratorio-de-midia/saida/bancadas/premiere-26.5.2/B24_COR_MC/LAB MASCARA LUMETRI 26.prproj`
  (salvo pelo 26.5.2 do Windows às 22:54, antes de a placa cair).
- ✅ Ele JÁ TEM a máscara: um `AE.ADBE AEMask2` (Mask2 "01") pendurado em `SubComponents` da Lumetri, `Type` = 2
  (retângulo), 4 vértices de canto em x 0,278–0,713 · y 0,262–0,733, Feather 0, Expansion 0, Opacity 100, Position =
  Anchor = (0,495; 0,498). Isso responde o `pendente` do banco: **no 26.5.2 o "Unassigned Masks" grava no mesmo formato
  do 26.0** (a máscara como SubComponent do efeito).
- No Mac: o Premiere 2026 instalado é o **26.0.2** (a interface antiga, com os botões de máscara na Lumetri) e há o 2027.
  Proposta: seguir daqui variando feather, posição e rotação no XML e renderizando no Mac, sem abrir a máscara na
  interface do Windows.

## 2. O PRODUCAO-H (Resolve Studio 21.1, Mac), lido pela API sem mexer em nada

- 6 timelines 1920×1080 a 23,976; YRGB Color Managed v2, timeline e saída Rec.709 (Scene).
- A última, `20260224_MTFR_CORTE_03_COLOR_v05`: 188 itens em 9 trilhas, 360 nós, 91 itens com mais de um nó,
  dois grupos (BLACK MAGIC 34, PRORES 33). 177 itens offline (a mídia não está nesta máquina).
- As ferramentas usadas nos nós (contagem em uso): Custom Curves 196, Primary Balance 93, OFX Halation 80, Lum vs Sat 36,
  Sat/Hue/Lum Mix 29, Log Grade 22, Hue vs Sat 17, Sat vs Sat 15, ColorSlice 15, **Power Windows 12**, Primary Offset 10,
  Noise Reduction 9, Hue vs Lum 8, HSL Qualifier 5, Qualifier Shrink 5, Qualifier Blur 4, **Tracking 2**, Auto Color 2,
  OFX NTSC-rs 2.
- 82 mídias distintas, com resolução, taxa, TC de início, duração e espaço de cor de entrada guardados no projeto:
  BRAW 6048×3200 e 6144×3456 e 4096×2160 (BMD Film Gen 5), ProRes 3840×2160 (RWG/Log3G10, uma REDlogFilm), Sony
  3840×2160 (S-Log3), H.264 1080 (Rec.709 e Rec.2100 HLG), 720, 640×480, anamórficos (PAR 0,8654, 1,322, 1,33,
  0,9677) e um PNG `MÁSCARA_235.png` (letterbox 2.35).

## 3. O plano

**A. O que o banco não conhece (sem mídia nenhuma).** Ler o Body da grade de cada item de uma CÓPIA do `Project.db`
(as ferramentas de 2026-11-20: `resolve_cor.bodies_do_projeto` + `tools.inspect_drp.pb_decode`) e conferir contra
`drt-drp/estruturas.md`: tipos de corrector, ids das janelas, qualificadores, OFX (Halation, NTSC-rs), tracking, grupos
(pre/post-clip) e a grade de timeline. Sai uma lista "conhecido / novo" — é o que os testes sintéticos não cobriram.

**B. Os charts no lugar da mídia (numa CÓPIA do projeto).**
1. Exportar o PRODUCAO-H para `.drp` e importar como `PRODUCAO-H LAB` na pasta LABORATORIO. O original não é tocado.
2. Uma receita no `laboratorio-de-midia` gera, por mídia, um chart com a MESMA resolução, PAR, taxa, TC de início e
   duração: patches de cor, rampa de cinza, rampas horizontal e vertical (para as janelas aparecerem), grade com
   coordenadas e o número do quadro da fonte queimado (prova de que o quadro bate depois da troca).
3. Trocar pela API (`MediaPoolItem.ReplaceClip`), repor o espaço de cor de entrada de cada clipe pelo inventário e
   conferir que a grade ficou (nós antes = depois) e que o quadro queimado é o esperado.
4. Renderizar os itens da v05 e medir, nó a nó, o que cada correção faz no chart; comparar com o que o Conformar
   e o banco preveem.
- ⚠️ No BRAW o chart chega já "revelado" (em Gen 5): o que o Camera Raw do BRAW (ISO, balanço) fazia fica de fora.
- Formato dos charts: HEVC 10 bits (um quadro parado comprime a quase nada, até nos 65 mil quadros do RET013_…C025)
  ou ProRes só no trecho usado. Recomendado: HEVC 10 bits 4:2:2 (o Resolve do Mac decodifica pelo VideoToolbox).

## Perguntas ao autor

1. Pode trabalhar numa cópia (`PRODUCAO-H LAB`, pasta LABORATORIO), sem tocar o original?
2. A timeline de referência é a v05?
3. HEVC 10 bits na duração inteira, ou ProRes só no trecho usado?
4. A máscara do Premiere segue no Mac (26.0.2 / 2027) em paralelo, ou primeiro o PRODUCAO-H?
