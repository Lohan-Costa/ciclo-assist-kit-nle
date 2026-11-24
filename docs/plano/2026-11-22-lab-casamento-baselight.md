# Laboratório de casamento no Baselight — o roteiro da rodada (2026-11-22)

Continuação de `2026-11-22-baselight-quem-casa-a-midia.md` (decisões do autor: depois do PRODUCAO-A ✅; P10 sequência =
vídeo; "entrega com alerta > erro calado"). Este arquivo diz COMO a rodada roda.

## A pergunta
Com mídia que engana de propósito, quem põe o arquivo certo em cada plano: **(A)** o Baselight sozinho, **(B)** o Ciclo
decide e o Baselight obedece, **(C)** B + a conferência pela FLAPI depois do conform? Resultado por pegadinha e por
caminho: **certo** · **alerta** (o editor foi avisado) · **errado calado** (o único inaceitável).

## As peças
1. **Receita `receitas/baselight/BL08_CASAMENTO.json`** (laboratório): ~16 originais em `ORIGINAIS/DIA01`, `DIA02`, e os
   dailies (proxies) que o editor monta em `DAILIES/`. Cada quadro mostra QUEM é (código de barras com o rótulo da
   variante, câmera, quadro) — o render do Baselight diz sozinho qual arquivo entrou.

   | # | o que a receita gera |
   |---|---|
   | P1 | `A001C003` no cartão A (20 s) e no cartão B (12 s), TC 00:00:00:00 nos dois |
   | P2 | `A001C004` em DIA01 e DIA02: mesmo TC e duração, imagem diferente |
   | P3 | original 59,94p e daily 23,976 da mesma tomada (duração em quadros diferente, em segundos igual) |
   | P4 | daily renomeado `CENA12_T3.mov` do original `B001C007` (TC e duração iguais; UMID onde o formato tiver) |
   | P5 | `a001c008.MOV` × `A001C008.mov`; e `CORAÇÃO_01` gravado em NFD |
   | P6 | `PLACA_298.mov` (arquivo de vídeo com número no fim) ao lado de uma sequência `PLACA_0001…` |
   | P7 | 29,97 DF no original, daily rotulado NDF (os rótulos divergem depois do 1º minuto) |
   | P8 | reel/fita vazio num e trocado (o de outro clipe) noutro |
   | P9 | `C001C002` copiado idêntico em `DIA01` e `BACKUP/DIA01` |
   | P10 | sequência DPX (um arquivo por quadro) que é uma tomada de câmera |

2. **A montagem** (~20 planos, 2 por pegadinha, V1 corte seco, montada nos DAILIES):
   - Premiere 2027 pela ponte (API, sem mouse) → `.prproj` → o leitor do Conformar → xmeml (o transporte de produto).
   - Media Composer pela API gRPC (`avid_baselight.py linkar|montar|exportar`, como a BL01) → AAF.
   ⚠️ Com o Baselight FECHADO (a estação só aguenta um programa pesado) e com o "pode pilotar" (o MC pode pedir gesto).
3. **Os três caminhos**, cada um numa scene própria (`LAB_CASA_A/B/C_<nle>`):
   - **A** `bl-conform` com o filtro Filename, depois ClipName, depois None; `--multiples`; nada nosso.
   - **B** o Conformar casa (nome, UMID, TC, duração como veto; ambíguo → o editor) e a entrega leva o caminho resolvido.
     Medir qual forma o `bl-conform` respeita: (i) o modelo de arquivo por fonte (`ft=` com a pasta/nome do evento),
     (ii) um `--src` por pasta resolvida, (iii) nome único por evento. Se nenhuma prender, B = A + C.
   - **C** depois do conform, a FLAPI lê arquivo + TC de cada plano × a decisão do Ciclo; diferente → trocar o arquivo
     do plano ou marker "[Ciclo] …" com o motivo.
4. **Conferência**: render de cada scene → código de barras quadro a quadro × a verdade (`verdade.json`).
   Placar P1–P10 × A/B/C, com o "porquê" de cada erro.

## A ordem (cada etapa fecha antes da próxima)
1. Receita + gerar + `verificar` (sem NLE; o Baselight pode ficar aberto).
2. **B no papel:** o Conformar casa a montagem da verdade contra as pastas e diz o que faria em cada plano — já mostra
   onde o nosso casador também erra, antes de qualquer NLE.
3. Montagem no Premiere (Baselight fechado) → xmeml.
4. Montagem no MC (Baselight fechado) → AAF.
5. Baselight aberto: A, B, C nos dois transportes; render; placar.
6. Registro no banco (`plugins/baselight/README.md`), relatório da etapa (página), e o que sobrar para o produto.

## Perguntas ao autor
1. Pode pilotar as etapas 3 e 4 (o Baselight fechado nesse trecho)?
2. Pegadinha AMBÍGUA (P2) na entrega: o plano vai **offline com marker** (o editor escolhe e religa) ou com o **1º
   candidato e marker** "confira"? (A regra "empate é do editor" sugere offline.)
3. Começar pelos dois NLEs, ou só o Premiere primeiro (mais rápido) e o MC depois?

## Andamento

### ✅ Etapa 1 — a mídia (2026-11-22)
`laboratorio-de-midia`: `python3 -m lab.casamento gerar|verificar` (receita `receitas/baselight/BL08_CASAMENTO.json`).
16 originais (um em DPX, 144 quadros numerados a partir do rótulo do TC, 1641600), a cópia do P9 e 16 dailies em
960×540; 2,9 GB em `saida/baselight/BL08_CASAMENTO`; **todos conferem** (ffprobe + código de barras + reel).
Medido: o filtro `fps` do ffmpeg faz o 1º quadro do daily 23,976 de um original 59,94 ser o quadro 1 do original
(1/60 s). O exFAT do Mac lista em NFD até o arquivo criado em NFC (já no banco, matriz "Unicode do nome").

### ✅ Etapa 2 — B no papel (o casador do Premiere, `prproj/originais.casar`)
`lab/bancadas/casamento_papel.py` (`--nfc` = os caminhos do projeto em NFC). **12 certos · 4 alertas · 0 errados.**

| # | resultado | |
|---|---|---|
| P1 | certo | a duração separou os dois `A001C003` (12 s × 20 s) |
| P2 | alerta | ambíguo, os 2 candidatos para o editor |
| P3 | certo | 59,94 × 23,976 pela duração em segundos |
| P4 | **alerta** | o renomeado `CENA12_T3` fica sem original: o casador só procura pelo NOME |
| P5 | certo | caixa e extensão; ⛔ o acento em NFC falhava (defeito, corrigido — abaixo) |
| P6 | certo | `PLACA_297`/`_298` como arquivos |
| P7 | certo | DF × NDF não atrapalhou |
| P8 | certo | o reel não entra na decisão |
| P9 | certo | cópias idênticas valem como uma |
| P10 | **alerta** | a sequência DPX não é vista como um clipe: sem original |

⛔ **Defeito corrigido no Conformar:** o índice (`indexar`) guardava o nome como a pasta lista (NFD no exFAT do Mac) e o
projeto busca em NFC ⇒ `CORAÇÃO_01` sem original. Chave única `_chave()` = NFC + minúsculo; teste
`tests/test_casamento_nome_nfd.py` (falha sem a correção, passa com ela).
⬜ Para o produto (proposta, não feito): P4 — sem candidato pelo nome, procurar pelo TC + duração (único = certo;
mais de um = o editor); P10 — a pasta de uma sequência de imagens como um clipe (o nome da pasta/prefixo, o 1º número
= o TC). O casador do MC (`media/matcher.py`) tem UID, nome e a imagem (pHash) contra o vid ref: medir no AAF.

### Decisões do autor (22/11, depois da etapa 2)
1. Pode pilotar as montagens. 2. Plano AMBÍGUO na entrega: **offline com marker** (o editor escolhe e religa).
3. **Só o Premiere primeiro**; o MC depois, com o mesmo placar.

### ✅ Etapas 3 e 5 — o Premiere 2027 → Baselight (2026-11-22), conferido pelo RENDER
Montagem pela ponte (`lab/bancadas/premiere_casamento.py rodar`, 18 planos, 9 s); conform e conferência
(`lab/bancadas/baselight_casamento.py a|b|c|render <scene>`). Placar (certo / alerta / errado calado):

| caminho | certo | alerta | errado calado | os errados |
|---|---|---|---|---|
| A Filename (dailies na mesma árvore dos originais) | 15 | 2 | 1 | P3 (−1,8 s) |
| A Filename (dailies numa pasta plana) | 12 | 3 | 3 | P1, P2, P3 |
| A ClipName | 13 | 2 | 3 | P1, P2, P3 |
| A None | 12 | 1 | 5 | P1, P2, P3, P6, P7 (2 quadros) |
| B o original decidido pelo Ciclo no xmeml | 12 | 5 | 1 | P1 (o Baselight não obedece ao caminho) |
| **C B + conferência + `bl-shots -replace` + markers** | **14** | **4** | **0** | — |

Os 4 alertas do C são os offline de propósito, cada um com marker "[Ciclo]" e o motivo: P2 ×2 (ambíguo), P4 (renomeado),
P10 (sequência DPX). Achados (banco `plugins/baselight/README.md`): o Baselight escolhe pelo NOME e ignora o caminho; o
`<file>` tem de levar a taxa/TC/duração do ORIGINAL (senão o in de um 59,94 vira quadro do daily); o nome no xmeml vai como
o disco lista (NFD no exFAT do Mac); `bl-shots -replace` troca um plano sem reconformar.
⬜ Para o PRODUTO (Conformar → saída Baselight): (1) xmeml com o `<file>` do original decidido; (2) a conferência C depois
do `bl-conform`; (3) o casador achar o renomeado pelo TC + duração (P4) e a sequência de imagens como um clipe (P10).
⬜ O MC (AAF) com o mesmo placar; depois o relatório final dos dois casos + o lab.

### ✅ Etapa 4 + 5 do MC (2026-11-22, noite) — AAF do MC 25.12 Mac, conferido pelo render
Montagem pela API (`lab/bancadas/avid_casamento.py`; o daily com acento NÃO linka no 25.12 Mac ⇒ o E09 virou buraco),
casador do MC no papel com a regra do ambíguo aplicada por fora (`lab/bancadas/baselight_casamento_mc.py papel`: 11/4/0) e
os caminhos no Baselight. Render: A Filename 13/2/3 · A ClipName 11/2/5 · A None 10/2/6 · **C 10/5/3**.
- P1/P2 resolvidos no C. ⛔ **P3 errado até no C** (−1,8 s): o AAF religado leva a taxa do daily; a conferência C não
  confere o PONTO. ⚠️ P7: a confirmar com o vid ref do MC (pode ser a bancada: o in gravado na taxa da timeline num master
  de 29,97).
- ⛔⛔ **Defeito do Conformar (produto), NÃO corrigido — para decidir:** `media/matcher.match_segments` devolve o AMBÍGUO
  com `matched_path` = o 1º candidato (`ambiguous=True`), e NINGUÉM lê o `ambiguous`: o `build_url_map` só pula o `None`.
  No religar do MC, o P2 do DIA01 iria para o DIA02 CALADO — contra a regra "empate é do editor". E as cópias idênticas
  (P9) também saem `ambiguous=True` (o casador do Premiere as junta).
- ⛔ A mensagem do `acoes.link_file` ("use o Media Composer 2025") está errada no Mac: o 25.12 também falha com acento.
⬜ Próximo: (1) o vid ref do MC para fechar o P7; (2) a conferência C checar o PONTO e corrigir pelo `bl-shots` (três
números) ou reescrever a taxa no AAF; (3) decidir o conserto do ambíguo no `matcher.py`; (4) o relatório final.

### ✅ O P7 fechado pelo vid ref do MC (2026-11-22, noite)
`lab/bancadas/avid_casamento.py vidref` (o preset DNxHR LB do laboratório + `ExportFile`, 18 s). O vid ref é a verdade do
lado do MC: E01–E11 exatos, e o **P3 dá 178 no MC** (o −107 é do Baselight). **P7:** o MC começa o plano de 29,97 no quadro
359 do original (o in convertido de tempo) e toca quadro a quadro; o Baselight, com o mesmo AAF, começa no 287 (−2,4 s,
calado), e os planos seguintes ficam 12 quadros fora do MC. ⇒ o P7 é ERRO DO BASELIGHT, não da bancada.
⚠️ Ao sair do MC depois do export, a barra "Exporting Files…" ficou presa na tela com o MC a ~100 % de CPU e a barra de menus
inacessível (a esperar; nada clicado).

### ✅ Decisão 2 feita: o Conformar corrige ANTES e a conferência olha o 1º E o último quadro visível (2026-11-22)
- `modulos/conformar/motor/baselight/entrega.py` — `reescrever` (o `<file>` de cada daily → o original decidido: caminho
  como o disco lista, taxa, TC, duração, raster; sem decisão = offline de propósito) e `esperado` (in/out no ARQUIVO pela
  ponte pelo original). `conferencia.py` — `ler_bl_shots`, `conferir` (ok · arquivo_diferente · fora_do_ponto · sem_midia
  · offline_de_proposito; tolerância = 1 quadro da timeline na taxa da fonte), `motivo` (texto do marker) e
  `linhas_de_troca` (`bl-shots -replace`). Teste `tests/test_baselight_frame_visivel.py`.
- Laboratório (`lab/bancadas/baselight_produto.py`, 20 planos do Premiere): 15 ok + 1 arquivo diferente (P1) + 4 offline →
  troca → **16 ok + 4 offline com motivo**. Sobre o caminho A, a conferência ACUSA o P3 (in 47 × 118, out 94 × 237).
- P11 (original com TC, daily zerado) e P12 (o contrário): certos nos dois caminhos (o in conta desde o início do arquivo).
  ⛔ O casador do Premiere recusava o P12 (a regra de 31/10 contra a conversão que perdeu o TC): agora o candidato de TC
  zerado MAIOR nas duas medidas que o arquivo do projeto entra como original, COM a dúvida à vista; o menor segue recusado
  (`tests/test_original_tc_zerado_maior.py`). Suíte do Conformar 124/125 (a falha antiga).
⬜ Falta: ligar a entrega + conferência ao fluxo do app (Conformar → "saída Baselight", markers pela FLAPI); o lado do MC
pela MESMA entrega (xmeml gerado da leitura do AAF, em vez do AAF religado); o P11/P12 no MC.

### Decisões do autor sobre a janela de conflito (22/11, noite)
1. **Janela PRÓPRIA**, que abre quando houver conflito a resolver.
2. **Com confirmação VISUAL, o empate pode ser resolvido; sem confirmação visual, NUNCA decidimos sozinhos.**
3. **Reel e tape name são critério** (metadados muito usados pelos editores online).
- ✅ (2) e (3) feitos no casador do Premiere: o REEL é critério (P4 casa) e o empate só se resolve com confirmação visual
  (quadro do daily × candidatos; P2: 0,999 × 0,897). Papel: 17 certos, 1 alerta (P10), 0 errados. Baselight pelo produto:
  19 ok + 1 offline. Suíte 125/126. ⬜ O mesmo no casador do MC (`media/matcher.py`: hoje só desempata com vid ref) e o
  reel no AAF (tape name); ⬜ a janela PRÓPRIA de conflito (decisão 1); ⬜ P10 (sequência de imagens como clipe).
- ✅ O mesmo no casador do MC (`media/matcher.py`, a regra comum em `media/confirmacao.py`): empate confirmado pelo
  quadro do DAILY que o AAF aponta (antes, só com vid ref); reel do arquivo do daily, porque o MC 25.12 não leva o
  `reel_name` do QuickTime ao AAF (medido: a string não está no arquivo). Papel do MC: **14 certos, 1 alerta (P10), 0
  errados** (antes 11/4/0): P2 pela imagem, P4 pelo reel. Testes `test_matcher_reel_e_daily.py`, `test_empate_sem_caminho.py`.

### ✅ O lado do MC pela mesma entrega (2026-11-22, noite) — conferido pelo render
`baselight/do_aaf.escrever` gera o xmeml da leitura do AAF; daí é a entrega do Premiere (`lab.bancadas.baselight_produto mc`).
Conform 13 ok + 3 trocados pelo Baselight + 1 offline → conferência corrige → **16 ok + 1 offline (P10)**. Render: **16/16
certos**, P3 e P7 no ponto (pelo AAF religado o Baselight errava os dois). Os 4 alertas do render são planos que o AAF do MC
não tem com mídia: E09 (P5, acento: o MC do Mac não linka), E16 (P10, de propósito), E19/E20 (P11/P12: a montagem do MC é
anterior a eles). ⬜ P11/P12 no MC pedem remontar no MC (com o Baselight fechado).
- ✅ P11/P12 no MC (22/11, 18h): montagem "BL08 CASAMENTO 3" (20 planos) → AAF → papel 16/1/0 → Baselight 18 ok + 1 offline →
  **render 18/18**. ⛔ No caminho, relatórios de falha do macOS (ver o handoff): o MC abortou ao abrir às 17:58 (títulos/Deko,
  depois de uma sessão fechada à força); o autor reabriu e daí tudo saiu limpo (MC fechou em 6 s, Baselight sem falha).

### ✅ A janela própria de conflito (decisão 1, 22/11 noite) — no fluxo de religar do app
⛔ Achado: o religar do app usa um TERCEIRO casador, `media/matcher_masters.py` (por master), e não o `media/matcher.py`.
Ele ganhou as mesmas regras: reel do daily como critério (e o reel nas dicas de nome do índice — sem isso o original nem era
indexado), cópias idênticas valem como uma, empate só pela imagem do daily, e o MESMO rótulo de TC com e sem drop-frame é o
mesmo TC (P7 era recusado: `16:58:50;00` × `16:58:50:00`). Cada candidato traz as provas (duração, TC, imagem). O serviço
entrega o quadro (`GET /trabalho/quadro`, só arquivos do trabalho). A vista larga da revisão mostra o quadro do DAILY ao lado
do de cada candidato, com o que bateu e o que não bateu, "em uso" ou "Usar este", e o motivo também nos casados; ela se
ABRE SOZINHA quando a preparação termina com empate. Pelo serviço, o BL08 do MC: **16 de 17 casados** (falta só o P10).
⬜ Ver na janela do app de verdade (a foto foi do Chrome sem janela, motor da bancada) e um empate SEM separação visual.

### ✅/⚠️ P10, a sequência de imagens (22/11 noite)
Os casadores comparam o NOME-BASE da sequência (`media/matcher._nome_do_arquivo`) e o índice com dicas não a descarta: papel
do MC **17 certos, 0 alerta, 0 errados**. A entrega escreve a sequência na sintaxe FilmLight (`%.7F`), com a taxa da montagem,
a duração em quadros e o 1º número como TC; a conferência soma o 1º número. Render: a sequência anda, câmera certa, mas
**7 quadros adiante** (30 × 23), um deslocamento constante do Baselight de causa não achada (banco, `plugins/baselight`) —
a conferência o acusa ("fora do ponto" → marker). ⬜ Achar a causa do +7 (DPX com TC no cabeçalho? `-replace` de três
números para corrigir a posição?).

