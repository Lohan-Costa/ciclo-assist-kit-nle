# O ensaio da demonstração de sexta, 2026-10-23 (roteiro do autor, 2026-10-21)

> A interface do guarda-chuva fica como está (autor: "como interface podemos ficar por aqui"). Daqui até sexta, o
> foco é fazer o roteiro abaixo rodar de ponta a ponta, ensaiado, com plano B em cada passo.
> Estado de cada passo conferido no código em 2026-10-21 (noite); ⬜ = ainda não existe ou nunca rodou.

## O roteiro, na ordem do autor

| # | o que ele mostra | onde | estado hoje |
|---|---|---|---|
| 1 | **Órbita standalone**: sync + **subclipe** da D02 da PRODUCAO-A — o caso mais parecido com o do local de trabalho | Órbita (janela própria) + **MC 24.6** (autor, 21/10) | ⬜ sync pelo app no MC (`/avid/mobs` → sync → `/avid/montar`, "pendente para a demo" no handoff do Órbita). ⬜ **subclipe** no MC: existe no painel antigo (`/avid/subclipes/{ler,prever,cena}`, 25.6) e nunca rodou pelo app no 24.6 |
| 2 | a complexidade do **PRODUCAO-C** | Premiere 2023 | só abrir o projeto `%USERPROFILE%\Desktop\WSP-DLPC.prproj` (autor, 22/10: já relinkado nas mídias certas, com a correção de escala, uma timeline só), com a referência `Desktop\PRODC_Trailer_v02.mov` ao lado. Nada a construir |
| 3 | o **import no Resolve** pelo De Lá Pra Cá, para um fluxo de cor | Resolve Studio + DLPC | o MESMO `Desktop\WSP-DLPC.prproj` do passo 2 (autor, 22/10). A ordem ao vivo: mostrar a timeline no Premiere → **fechar o Premiere** → abrir o Resolve → só então abrir o app do DLPC → importar o `.prproj` e ver o conform; o `PRODC_Trailer_v02.mov` (Desktop) é o vídeo de referência. O DLPC opera o Resolve por fora (`resolve_externo.py`, 48/48 chamadas medidas em 10/18–19). ⬜ ensaiar nessa ordem. ⚠️ MC e Resolve nunca abertos juntos |
| 4 | o **Ciclo Assist**: o Órbita e o De Lá Pra Cá vivendo dentro dele | o guarda-chuva | as abas ✅. O agente operando o **Órbita** (passo 5) já mostra a proposta; **o DLPC por comando NÃO entra na demo** (autor, 21/10) |
| 5 | **ressincronizar a D02 pedindo ao Assistir**, no Media Composer | guarda-chuva + MC 24.6 | ✅ código (22/10): `sincronizar_com_o_orbita` no MC chama `POST /api/v1/avid/sincronizar {pasta}` do Órbita (lê, sincroniza e monta a bin num pedido); testado contra Órbita falso. ⬜ rodar pelo chat com o prompt 1 |
| 6 | **bins de cena com subclipes** | MC 24.6 | ⬜ é o "Criar bins por cena" do Órbita (`/avid/subclipes/cena`), pelo app no 24.6 — ou pelo agente |
| 7 | pedir ao Assistir para **separar a cena por fala**: o editor ARRASTA os subclipes da **C07 da PRODUCAO-A** e o roteiro do Explorer (`MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A/ROTEIRO/PRODUCAO-A CENA 7 roteiro.docx`) para o chat | guarda-chuva + MC 24.6 | `separar_falas` ✅ (medido na C07 do `_ASSIST ANTERIOR`, MC 25.6). ⬜ no 24.6 e com a D02: a bin é escrita por `CloseBin` → pyavb → `OpenBin` (o 24.6 salva no `CloseBin`, banco). ⚠️ a transcrição dos takes leva ~1 min cada: **pré-processar** na aba Vetores antes da demo |

## Um NLE aberto por vez (autor, 22/10)

Nenhum programa fica aberto junto de outro: **MC** (passo 1, Órbita) → fecha → **Premiere** (passo 2, PRODC) → fecha →
**Resolve** + app do DLPC (passo 3) → fecha → **MC reaberto** (passos 4–7, o Ciclo Assist) até o fim. ⚠️ Ao reabrir o
MC, conferir que a janela do Assist voltou a falar com o Media Composer (ela troca para o Premiere quando ele abre) e
contar com a partida lenta do MC no tempo da apresentação.

## Os prompts são FIXOS (autor, 21/10)

Para a demo não depender de como a frase saiu na hora, os dois pedidos ao Assistir são textos prontos, colados como
estão: `docs/demo/prompt-1-sincronizar.txt` (passo 5) e `docs/demo/prompt-2-separar-falas.txt` (passo 7). Cada um
nomeia o caminho (o método, as ferramentas), proíbe pergunta antes do cartão, diz o que fazer na falha (parar e dizer)
e fixa o formato da resposta. Para o resultado se repetir também:

- **conversa limpa** antes de cada um (o fio continuado muda o que o modelo faz);
- **o mesmo modelo** do ensaio que passou, escolhido antes de subir ao palco;
- os takes da C07 **já transcritos** no cache (a aba Vetores), senão o passo 7 leva ~1 min por take e o roteiro do
  turno muda com a espera.

⚠️ No Premiere, "subclipe" na fala do autor quer dizer **merged clip** (o Órbita já sabe fazer). Na demo o passo 1 é no
MC, então isso não muda nada agora; vale para os prompts e as telas futuras.

## O que construir, por prioridade

1. **P0 — o sync + subclipe do Órbita pelo app, no MC 24.6** (passos 1 e 6): o sync pelo caminho `/avid/mobs` →
   sync → `/avid/montar`, e o Subclipar do painel antigo levado à subaba do app (contornos do banco: sem `DoCommand`,
   `CloseBin` salva).
2. ✅ **`sincronizar_com_o_orbita` no Media Composer** (passo 5, 22/10): `nles=AMBOS`; no MC, `bin` é a PASTA do projeto
   (D02) e o Órbita faz tudo pela rota §8. ⬜ Falta a prova pelo chat, com o Órbita e o MC 24.6 na tela.
3. **P1 — bins de cena** (passo 6): "Criar bins por cena" do Órbita (`/avid/subclipes/cena`) no 24.6.
4. **Ensaio**: D02 no MC 24.6; os subclipes da C07 com os takes transcritos; o roteiro no Explorer; os dois prompts
   rodados duas vezes do começo ao fim pelo piloto, com o plano B de cada passo.

## Plano B (para cada passo que pode falhar ao vivo)

- **Sync / subclipe**: uma sequência e uma bin JÁ FEITAS no projeto, para mostrar o resultado.
- **Agente**: a resposta gravada de um ensaio (o diário do serviço guarda cada ferramenta chamada).
- **Resolve**: o projeto já importado, aberto ao lado.
- ⚠️ Esta máquina: o MC mostra `std::exception` nos monitores (erro de hardware de vídeo na partida, não confirmado)
  e o carregar no Source pendura ~30–60 s — conferir antes de sexta, ou não carregar clipe no Source ao vivo.

## Perguntas ao autor — respondidas em 21/10

1. Passo 1: **Media Composer**. (No Premiere, "subclipe" = merged clip.)
2. Passo 4: **não** mostrar o Assist operando o DLPC; o Órbita por comando basta.
3. Passo 7: **Cena 07 da PRODUCAO-A**, método já ensaiado; o editor arrasta os subclipes e o `.docx` do Explorer.

## Ensaio do passo 5 (2026-10-22, manhã, pilotado)

MC 24.6, projeto `ORBITA DEMO D02` limpo (as bins dos testes anteriores foram para
`Documents\Avid Projects - quarentena\`), atalho "Sync + subclipes da D02 (Órbita)", Sonnet 5, conversa nova.
- ✅ **1 min 05 s** do envio à resposta: bin `D02 SYNC ORBITA` (24 takes casados, 2 clipes de câmera sem som) e
  `CENAS/C04` (16 subclipes) + `CENAS/C07` (10), nomes `C07_P02_T002`…, as duas abertas em aba no MC.
- ⛔ A resposta disse "Câmeras: 26": o resumo contava CLIPES como câmeras. Consertado (é 1 câmera, CAM A, 26 clipes).
- ⚠️ O modo estava em **automático**: o cartão de confirmação NÃO apareceu. Para a demo, decidir se o chip fica em
  automático (mais rápido) ou em perguntar (mostra o cartão, que é o que o prompt descreve).
- ⚠️ A pasta **CENAS não aparece no painel de bins** até reabrir o projeto: o Órbita grava as `.avb` direto no disco.
  Saída medida no banco (25.6): `CreateBin(folder_path="CENAS", ...)` cria a pasta na hora — mudança no Órbita.
- ⚠️ Antes do MC abrir: a formatação tinha apagado as exclusões do Defender (trava no `AAFProcessor.avx`); reaplicadas.

- Correção: a pasta CENAS APARECEU no painel do projeto alguns minutos depois (visto às 8h40), sem reabrir. O MC
  relê a pasta do projeto sozinho, com atraso; o `CreateBin(folder_path)` deixa de ser necessário.

## Ensaio do passo 7 (2026-10-22, 8h42, pilotado, Sonnet 5, conversa limpa)

10 subclipes de `CENAS/C07` + o roteiro `.docx` arrastados; atalho "Separar falas da C07". As 10 transcrições já
estavam no cache e em dia (nenhum ASR no turno).
- ⬜ **Feedback do andamento (autor, 8h48):** o painel ficou ~5 min em "raciocinando… sem sinal", e isso se lê
  como "a transcrição travou". Não era o ASR (veio do cache em segundos): era o Sonnet compondo o pedido do
  `separar_falas`. Falta (1) dizer em cada "Ouve o take" que veio do cache e (2) mostrar o pedido sendo escrito
  enquanto o modelo o compõe (o `input_json_delta` do stream), em vez do relógio parado.
- Medido no turno: 67,5 mil tokens de SAÍDA (59% do custo), quase tudo pensamento; o pensamento do Sonnet 5 chega
  SEM texto (só a assinatura), daí o "sem sinal". Barra das 5 h: 18% → 48% nos dois turnos.
- ⛔ Defeito nosso: o guarda de laço comparava só 2.000 caracteres e barrou um pedido corrigido (`fada99b`).
- Resultado: bin `C07 FALAS`, 16 timelines, 114 trechos; o autor ouviu algumas falas e estão no ponto.

### O que mudou depois (2026-10-22, tarde) — falta MEDIR numa rodada nova
- `transcrever(enxuta=true)`: `segmento | segundos | texto`, 142 mil → 27 mil caracteres nos 10 takes; o método pede.
- `separar_falas(corrigir_o_anterior=true)`: depois de reprovado, só os momentos consertados.
- `config.json` → `"esforco": "low|medium|high"` vira `--effort` (só Claude). Sem a chave, o padrão do CLI.
- Painel: "pensando há N" no lugar de "sem sinal" durante o pensamento opaco; "transcrição já guardada" no cache.

### Rodada de medição (2026-10-22, 9h48, esforço low + código novo, conversa nova)
| | rodada 1 (2 turnos, com o defeito do guarda) | rodada 2 (1 turno) |
|---|---|---|
| tempo | ~12 min | **8 min** |
| saída | 83,2 mil | **53,4 mil** (o 1º turno da rodada 1 sozinho: 67,5 mil) |
| cache escrito / lido | 161 mil / 1,03 mi | 147 mil / 519 mil |
| preço de tabela | US$ 2,16 | **US$ 1,51** |
| reenvios do pedido | 13 mil caracteres cada | **3,4 / 2,3 / 3,2 mil** (corrigir_o_anterior usado) |
- ⛔ A forma enxuta NÃO foi usada (o modelo seguiu a descrição da ferramenta, não o método): agora ela está na
  descrição do `transcrever`. Falta medir — é o maior ganho que sobra (~35 mil tokens de contexto por turno).
- Ainda ~5 min de pensamento antes do primeiro pedido. O painel mostrou "pensando há 3 min 47 s" (visto na tela).
- Resultado: `C07 FALAS 2`, 16 falas + 1 variante (FALA06.02, improviso do PERSONAGEM-G no P02_T004), os mesmos 3 de fora.
- ⚠️ A barra das 5 h NÃO mede o turno: é a mesma assinatura da sessão de desenvolvimento (Opus), que gastava junto.

## Ensaio dos passos 4–7 (2026-10-22, 14h50–15h13, pilotado, MC reaberto na tela de projetos)

Projeto limpo antes (as bins dos ensaios foram para `Avid Projects - quarentena\ORBITA DEMO D02 (ensaio 2026-10-22 tarde)`),
gateway da sessão anterior ainda vivo, app aberto por `app\abrir.ps1`.
- ✅ **Conexão**: o app conectou ao MC 24.6 com o gateway velho (o risco do gateway não se confirmou). ⚠️ Nos primeiros
  ~10 s o topo diz "o serviço do Ciclo Assist não respondeu" e o app abre na ÚLTIMA aba usada (Conformar) — abrir o app
  antes de subir ao palco.
- ✅ **Passo 4**: as abas Preparar (Órbita · Subclipar · Renomear) e Assistir na tela.
- ✅/⛔ **Passo 5 pelo Qwen (Mac)**: 3 min 20 s (≈2 min só lendo o pedido, modelo frio), `sincronizar_com_o_orbita`
  certo, bins `D02 SYNC ORBITA 2`, `C04 2` (16) e `C07 2` (10). ⛔ **O Qwen tirou o `C` do padrão** (`%{cena}_P…`):
  os subclipes saíram `07_P03_T002` em vez de `C07_P03_T002`. ⚠️ E respondeu "nada ficou órfão" (leu o contador dos
  subclipes; o sync tem 2 clipes de câmera sem som). ⇒ **Sonnet no passo 5** (1 min 05 s e nomes certos no ensaio da manhã).
- ✅ **Passo 7 pelo Sonnet 5 (esforço low)**: 10 subclipes da `C07 2` + o `.docx` arrastados, atalho "Separar falas da
  C07". **9 min 06 s, 656 mil tokens** (barra das 5 h 16 % → 25 %). Bin `C07 FALAS`, 16 timelines, 0 variantes, 112
  trechos; de fora P02_T001 (só claquete), P02_T001.1 (sem som direto), P03_T002 (abortado na fala 4). A correção
  parcial rodou 5 vezes (16 → 5 → 2 → 1 → 1 → pedido final) antes de passar.
- ⛔ **A transcrição pela aba Vetores NÃO serviu ao chat**: filtrei por `05-04 C7 P` e a fila transcreveu 9 mídias da
  varredura da `Avid MediaFiles` (`C7 P2-T003`, 2 min 29 s); o chat procurou os masters das BINS (`C7 P2/002`, o take
  renomeado) e criou entradas NOVAS no cache — o mesmo som duas vezes. Provável causa do "apaguei o cache e não
  consegui refazer" do autor. ⬜ Investigar depois da demo (a regra "varredura e cache cruzam pelo UMID" não valeu
  aqui). Para a demo: o cache agora tem os masters certos e o passo 5 de amanhã recria subclipes dos MESMOS masters —
  **não apagar o cache até sexta**.
- ⚠️ "Limpar conversa" arma por 6 s: dois cliques seguidos, não um clique-olhar-clique.

**Estado deixado no projeto:** `D02 SYNC ORBITA`, `D02 SYNC ORBITA 2`, `CENAS/C04 2`, `CENAS/C07 2` (nomes sem C) e
`C07 FALAS` (plano B do passo 7). ⬜ Antes da demo: limpar com o MC fechado, conforme o estado de partida que o autor quiser.

## Rodada pilotada de 2026-10-29 (17h23-17h31): Sonnet 5.5, esforço low, projeto NOVO, só pelo chat

Projeto `ASSIST TESTE 29-10` criado na hora (1080p/23,976) com a D02 crua (`CAM A`, `SOM DIRETO`); modo automático;
conversa limpa antes de cada prompt; os mesmos atalhos (prompts fixos). Medido no transcript do CLI
(`spikes/o_que_enche_a_janela.py`); o preço é DERIVADO da tabela, não o que a assinatura cobra.

| | passo 5 (sync + subclipes) | passo 7 (separar falas) | passo 7 em 22/10 (Sonnet 5, rodada 2) |
|---|---|---|---|
| tempo do envio à resposta | 2 min 00 s (quase tudo é o Órbita) | **1 min 55 s** | 8 min |
| chamadas ao modelo | 2 | 6 | — |
| saída (pensamento + texto) | 317 | **15,2 mil** | 53,4 mil |
| cache escrito / lido | 16,2 mil / 15,4 mil | 37,8 mil / 185 mil | 147 mil / 519 mil |
| preço de tabela | US$ 0,07 | **US$ 0,42** | US$ 1,51 |
| reprovações do `separar_falas` | — | 2 (11,8 mil → 1,7 mil → 1,4 mil caracteres) | 5 |

- ✅ Passo 5: 24 de 26 casados, 2 clipes de câmera sem som, `D02 SYNC ORBITA`, `CENAS/C04` 16 e `CENAS/C07` 10, nomes
  `C07_P02_T001` (com o C). O Sonnet 5.5 chamou `sincronizar_com_o_orbita` direto, sem consulta antes.
- ✅ Passo 7: `C07 FALAS`, 18 timelines (17 falas + `C07_FALA14.02`), 121 trechos; de fora os mesmos 3 de 22/10
  (P02_T001 só claquete, P02_T001.1 sem som direto, P03_T002 abortado — falas 1 a 4 entram). A fala 2 do roteiro virou
  três momentos.
- ⭐ A forma enxuta do `transcrever` FOI usada: 10 transcrições = 28,8 mil caracteres (eram 142 mil na forma cheia), os
  10 pedidos num bloco só, em paralelo. Todas do cache (nenhum ASR no turno).
- ⭐ A troca de modelo explica o resto: o "pensando há 3 min" de 22/10 não aconteceu — o pedido começou a ser escrito
  com 1 min 30 s de turno.
- ⚠️ "Limpar mesmo?" arma por 6 s: o segundo clique do piloto veio com 8 s e rearmou. O `/clear` na caixa limpou.
- ⚠️ Montar o projeto: bin copiada para a pasta do projeto aberto não entra na árvore até fechar e reabrir (banco,
  `windows.md`).
⬜ Não conferido: ouvir as falas na bin (o autor ouviu as de 22/10); repetir a rodada para ver a variância.
