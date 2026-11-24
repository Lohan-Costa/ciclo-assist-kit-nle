# O alinhador por palavra: a borda da fala no nível do Premiere (proposta, 2026-11-11)

> Estado: **APROVADA com decisões** (§6, autor, 2026-11-11). **L0 feita** (§7): 4 decisões voltam ao autor. Nada no produto ainda.
> Base medida: banco `transversal/transcricao-por-palavra.md` (Resolve 21.1, Premiere 26.0.2 e Beta 27.1, o nosso
> faster-whisper `small`), gabarito sintético e saídas em
> `MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-11 TRANSCRICAO POR PALAVRA/`.

## 1. O problema, em uma linha

O nosso texto é bom; a **borda** de cada palavra não. Em português, 6 % das palavras começam a até 1 quadro do lugar
certo (34 % descontando o desvio fixo), e 9 de 10 fins de frase cortam a voz. A meta é o Premiere 2026: **89 %** sem o
desvio fixo, com o fim de frase protegido.

## 2. O que a medição ensinou (e o desenho segue isto)

1. **Whisper maior não resolve a borda.** Resolve e Premiere Beta usam Whisper large-v3-turbo e ficam em 30 % e 71 %.
2. **O salto vem de um ALINHADOR depois do reconhecimento.** O Resolve em inglês (Whisper + alinhador forçado Kaldi)
   vai a 97 %; em português o alinhador dele não roda.
3. **O nosso erro é espalhado, não um desvio só.** Somar uma constante não nos leva a 89 %.
4. **O silêncio precisa ser um item da lista.** É o que deixa "selecionar a pausa" e saber se um corte cai em fala.
5. **A conversão para In/Out decide o vazamento.** O Resolve corta até 1 quadro da cauda (piso); o Premiere avança
   cada borda até metade do vão para a palavra vizinha, teto 40 ms. A regra do Premiere é a que serve ao editor.

## 3. O desenho: três camadas, cada uma com o seu estágio no cache

```
WAV do master
  │
  ├─ (já existe) ASR faster-whisper ──► TEXTO + tempo aproximado          estágio "transcricao" (intacto)
  │
  ├─ ⭐ ALINHADOR forçado (CTC) ──────► borda de cada PALAVRA             estágio novo "alinhamento"
  │      o texto do Whisper é a resposta dada; o modelo só acha ONDE ela está no som
  │
  └─ ⭐ VOZ × SILÊNCIO (VAD + energia por canal) ─► trechos de silêncio      dentro do mesmo estágio
         e o ajuste fino da borda que encosta numa pausa (o "bordas.py" da edição de cena, portado)
```

- **Estágio próprio no cache**, com assinatura própria: ligar o alinhador NÃO invalida as transcrições já feitas
  (o cache de 120 MB sobrevive, a regra que o `transcrever` já seguiu ao tirar o array de palavras do padrão).
- **Fallback honesto:** sem alinhador (modelo ausente, mídia curta demais), fica o tempo do Whisper e a procedência
  diz `fonte: asr`, `confianca: inferido`. Com ele, `fonte: alinhamento`, com o número que o sustenta.
- **Silêncio explícito:** a lista passa a ter entradas `silencio` com início e fim (como o `(...)` do Resolve).

### 3.1 O alinhador (camada 2)

Alinhamento **CTC** (o mesmo princípio do Kaldi do Resolve, sem o léxico): um modelo acústico que dá, a cada 20 ms, a
probabilidade de cada letra; o texto do Whisper vira uma sequência de letras; um Viterbi em **numpy** (umas 40 linhas)
acha o caminho mais provável e devolve início e fim de cada palavra. Sem torch: o modelo roda em **onnxruntime**, que
já é dependência.

Candidatos (nenhum medido aqui; o tamanho decide ONDE pode rodar, §6-1):

| modelo | idiomas | tamanho (fp32 → int8) | observação |
|---|---|---|---|
| `facebook/mms-300m` + cabeça de alinhamento (o `MMS_FA` do torchaudio) | ~1100, incl. PT | ~1,2 GB → ~320 MB | um modelo para todos os idiomas; texto romanizado |
| `jonatasgrosman/wav2vec2-large-xlsr-53-portuguese` | PT | ~1,2 GB → ~320 MB | treinado em PT, letras com acento direto |
| um wav2vec2 **base** em PT (~95 M parâmetros) | PT | ~360 MB → ~95 MB | ⬜ procurar um bom; cabe no notebook com folga |

⚠️ A exportação para ONNX é passo de DESENVOLVIMENTO (precisa de torch uma vez, numa venv à parte); o produto só
carrega o `.onnx`, como já faz com o MobileNetV2.

### 3.2 Voz × silêncio (camada 3)

- VAD do `sherpa-onnx` (Silero, já dependência) para os trechos de silêncio.
- Ajuste fino de borda que encosta numa pausa, pela **energia da lapela de quem fala** (o `bordas.py` medido na C07,
  §"Edição de cena"). ⛔ Na mistura de canais a energia não serve (medido duas vezes).

### 3.3 A saída para quem corta (camada de uso)

- `transcrever` passa a devolver as falas com borda alinhada e os silêncios; o `separar_falas`, o mapa de corte e a
  edição de cena usam a borda alinhada.
- **Seleção → In/Out na regra do Premiere:** cada borda vai até metade do vão para a palavra vizinha, teto de 40 ms
  (configurável); ao virar quadro, o **In arredonda para baixo e o Out para cima** (nunca cortar a cauda).

## 4. Como saber que chegou lá (a régua)

| prova | material | meta |
|---|---|---|
| gabarito sintético (já existe) | 53 palavras PT, 62 EN, borda à amostra | ≥ 85 % a ≤ 1 quadro; 0 de 10 fins cortando a voz |
| fala HUMANA | ⬜ §6-3 | ≥ o Premiere 2026 no mesmo material |
| sem regressão | a suíte + a C07 da edição de cena | nada pior; a v5 da edição de cena refeita sem vazamento |
| custo | o take de 9 min do PRODUCAO-A | tempo e memória medidos no Mac e no notebook com o MC aberto |

A comparação com o Premiere 2026 em fala real é feita com o leitor do `.prproj` que já existe
(`spikes/transcricao_por_palavra/ler_prproj_transcricao.py`).

## 5. As fases

| fase | o quê | pronto quando |
|---|---|---|
| **L0** spike | Viterbi CTC em numpy + 2 modelos candidatos em ONNX, no Mac; gabarito sintético + o take de 9 min | um modelo passa de 85 % no sintético e a medida de tempo/memória está na mesa |
| **L1** estágio | `midia/alinhamento.py`, estágio `alinhamento` no cache, procedência, fallback | a suíte passa e `transcrever` devolve borda alinhada quando há |
| **L2** silêncio | VAD + energia da lapela; entradas `silencio` na lista | "o corte cai em fala ou em silêncio?" respondido por código |
| **L3** In/Out | a regra do Premiere ao converter seleção em quadros; os consumidores (`separar_falas`, edição de cena) | a C07 remontada sem fala vazando, conferida pelo autor no MC |
| **L4** Windows | medir no notebook com o MC aberto; decidir onde roda (§6-1) | número de memória e tempo no Windows |
| depois | levar a nossa transcrição para dentro do Premiere/Resolve (ideia do autor) | plano próprio |

## 6. Decisões do autor

1. **Onde o alinhador roda.** O notebook proíbe modelo grande (o SigLIP reprovou por memória). Proposta: tentar um
   modelo **pequeno** (≤ ~100 MB int8) no próprio notebook; se não houver um bom em PT, rodar no **Mac**, como o SigLIP.
2. **Um modelo para todos os idiomas (MMS) ou um por idioma** (PT primeiro).
3. **Fala humana para o gabarito:** marcar à mão ~50 bordas num take curto do PRODUCAO-A, gravar uma fala nova com
   lapela no laboratório, ou usar o Premiere 2026 como referência (89 % no sintético).
4. **A folga do In/Out:** metade do vão com teto de 40 ms (o Premiere) ou outro teto.
5. **Reprocessar o acervo:** o alinhamento roda sozinho em toda mídia já transcrita (fila de fundo, sem gastar
   assinatura) ou só quando uma ferramenta pedir.

### ✅ Decididas pelo autor (2026-11-11)

- **1 → modelo PEQUENO no notebook** (≤ ~100 MB int8); só se nenhum for bom em PT, cair para o Mac. A L0 começa
  procurando e medindo modelos pequenos.
- **3 → o Premiere 2026 é a referência de fala humana** (comparar no mesmo take real pelo leitor do `.prproj`).
- **4 → folga igual à do Premiere:** metade do vão até a vizinha, teto 40 ms; In arredonda para baixo, Out para cima.
- **5 → sob demanda:** alinha quando uma ferramenta precisar daquela mídia; nada de fila de fundo no acervo.
- ⬜ **2 (um modelo para todos os idiomas ou um por idioma)** fica para a L0: depende de existir um pequeno bom.

## 7. Resultado da L0 (2026-11-11, Mac mini) — detalhe no banco, `transcricao-por-palavra.md` §7

Spike `spikes/transcricao_por_palavra/alinhar_l0.py` (+ `medir_l0.py`, `medir_real.py`); saídas em
`MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-11 TRANSCRICAO POR PALAVRA/l0/` e os modelos em `…/modelos_l0/` (fora do Git).

- ✅ **O desenho funciona no sintético:** CTC + energia = **96 % início e 96 % fim a ≤ 1 quadro, 0 de 10 fins cortando a voz** (meta
  era 85 %). Com o texto do NOSSO Whisper, não só com o texto exato. Premiere 2026 na mesma régua: 75 % / 49 % / 5 de 10.
- ⭐ **As duas camadas fazem coisas diferentes:** a energia sozinha (sobre o tempo do Whisper, sem modelo) já zera o "fim de frase
  cortando a voz", mas fica em 49 % por palavra; o CTC é o que dá a palavra no meio da frase. ⇒ a L2 (energia) pode vir ANTES e rodar
  em qualquer máquina.
- ⛔ **Não há modelo pequeno bom (§6-1):** o único ≤ 100 MB em PT (NeMo, passo 80 ms) falha mesmo com a energia. Os bons são
  wav2vec2 PT large (355 MB int8) e Omnilingual 300M (290 MB int8), empatados em PT; ~850 MB de pico com janela ≤ 6 s; 24 s por take de
  9 min no Mac. Pela regra do autor, **cai para o Mac**.
- ⭐ **Questão 2:** o Omnilingual empata em PT e cobre o inglês (74 %/69 % no EN sintético, sem cortar fim de frase) ⇒ proposta: **um
  modelo para todos** (Omnilingual).
- ⚠️ **Fala de set (take C4 P1-T001 × Premiere 2026):** o início concorda 84 % (descontado o desvio fixo de +41 ms, o mesmo do
  sintético). O FIM na pausa depende do limiar de energia, e na MISTURA não serve (+417 ms). Na lapela dominante, 30/15: 32 % a ≤ 1 q do
  Premiere, 59 % depois dele, 9 % antes. O Premiere não é gabarito (corta a voz em 5 de 10 no sintético) ⇒ **a fronteira fala × pausa
  em som de set precisa de ouvido humano** para fechar o limiar.

- ✅ **Decididas (autor, 2026-11-11, noite):** 1 → **Mac**; 2 → **Omnilingual**; 4 → **L2 antes da L1**.
- ✅ **Juiz de ouvido feito (autor, 18 bordas cegas):** regra **início = CTC − 41 ms; fim = max(energia na lapela, CTC + 60 ms)** →
  13 de 17 a ≤ 1 quadro do ouvido e 0 cortando a voz (Premiere 10 de 17). Detalhe no banco §7. A decisão 3 abaixo está fechada.

### ⬜ Decisões que a L0 devolve ao autor

1. **Onde roda:** no Mac (como o SigLIP), ou também no notebook com o MC FECHADO (850 MB cabem fora do MC)?
2. **Modelo:** Omnilingual (um para todos) — proposta.
3. **Juiz da pausa:** ouvir ~20 bordas onde nós e o Premiere discordamos (uma sequência com marcadores nos dois candidatos), para fixar
   o limiar da lapela.
4. **Ordem:** L2 (energia, sem modelo) antes da L1 (estágio do CTC), porque é a que conserta o vazamento no corte e roda em toda máquina.

## 8. A L2: voz × silêncio pela lapela, sem modelo (desenho, 2026-11-11)

**De onde parte:** o produto já mede a energia de cada canal (`midia/falantes.py`, janela de 50 ms), sabe pelo nome qual trilha é
PESSOA, boom ou mistura (`midia/canais.py`) e diz de que lapela é cada fala (`analise.quem_fala`). O `spikes/edicao_de_cena/bordas.py`
já achou a borda real da voz na lapela da C07 (voz = 10 dB acima do piso da lapela E sem perder da outra lapela por mais de 3 dB;
oclusiva de até 120 ms não encerra a voz), validado contra as emendas do editor.

**O estágio `voz`** (`midia/voz.py`, `voz.json` no cache, assinatura própria, depende da transcrição e do `falantes.json`):
- envelope de 10 ms de cada trilha PESSOA (o mesmo leitor em fluxo do `falantes`, com a janela como parâmetro);
- a máscara de voz de cada lapela (a regra do `bordas.py`);
- por fala: `voz_inicio`/`voz_fim` medidos na lapela de quem fala (a da atribuição), com `medido: sim/não` e o canal; e o mesmo para cada
  palavra que encosta numa pausa (≥ 0,3 s). Fim nunca antes do fim do ASR (a trava: o ASR erra para DENTRO da palavra);
- `silencios`: os trechos em que NENHUMA lapela tem voz (≥ 0,3 s), como itens da lista, igual ao `(...)` do Resolve;
- `em_fala(t)` → `fala` (de quem) · `silencio` · `nao_medido`: a pergunta "o corte cai em fala?" respondida por código.
- Sem lapela de pessoa (sem nomes, uma lapela só, mistura pura): `nao_medido`, e tudo segue como hoje. Nada some calado.
- Palavra sem voz em lapela nenhuma (o "ser" da equipe, item 01 do juiz): marcada `fora_das_lapelas` — fala de equipe, não diálogo.

**Onde entra:** `transcrever` devolve os campos novos; `com_respiro` passa a partir da borda MEDIDA (⬜ decisão abaixo); o
`conferir_o_mapa` e a edição de cena avisam corte que cai em fala (o "vazamento").

⬜ **Decisão:** a borda medida (a) só ESTENDE o corte de hoje (nunca encurta: zero risco, cortes iguais ou mais folgados) ou
(b) SUBSTITUI a do ASR, e o respiro fixo de 0,40 s depois da fala (que existia para cobrir o erro do ASR) cai para o respiro de
ofício (~0,10–0,17 s) — cortes mais justos.

✅ **Decidido (autor):** a borda medida **só estende**; fala sem voz em lapela nenhuma é **marcada e mostrada**.

### 8.1 Feito (2026-11-11, noite) e o que o take real mostrou

- `cicloassist/midia/voz.py` (estágio `voz`, `voz.json`): lapelas pelo nome (`canais.PESSOA`) ou pela correlação; máscara de voz da
  regra do `bordas.py`; por fala `voz_inicio`/`voz_fim` (fim nunca antes do ASR); por palavra que encosta em pausa `voz_t`/`voz_fim`;
  `fora_das_lapelas`; `silencios`; `em_fala(t)`. Ligado em `analise.transcrever_master` (`medir_voz`; falha não tira a transcrição),
  no `transcrever` (fala.py), no `separar_falas` e na trama (só do cache). `asr.com_respiro` só ESTENDE (`corte_pela_voz`) e não
  invade o vizinho. `tests/test_voz.py` (10). Suíte no Mac 1936/38.
- ⚠️⚠️ **Take real (C4 P1-T001, as 17 bordas julgadas de ouvido):** a L2 sobre o tempo do WHISPER acerta 4/17 a ≤ 1 q (Whisper cru
  0/17) e corta voz/ataque em 3 (Whisper cru 9). Em fala real o Whisper erra a palavra em até ~1 s (no sintético, ~130 ms), e a energia
  parte do lugar errado. ⇒ **a L2 sozinha melhora mas não basta: o estágio `voz` precisa partir da borda do CTC (L1)**; com ela, a
  regra do juiz dá 13/17 e 0 cortes. A L2 fica como a base (lapelas, máscara, silêncios, `em_fala`, o corte que só estende) e o
  caminho sem o Mac.
- ⬜ O "ser" da equipe (item 01) NÃO saiu `fora_das_lapelas`: a voz distante entra igual nas duas lapelas. Falta a regra de fala
  distante (o mesmo nível nas lapelas e bem abaixo da referência de voz delas; a pista do "mesma voz" do `falantes`).
- ⬜ **Próximo: L1** — o CTC (Omnilingual, no Mac) dá a borda de partida do `voz`; início = CTC − 41 ms, fim = max(voz, CTC + 60 ms).

## 9. A L1 feita (2026-11-11, noite, Mac mini)

- `cicloassist/midia/alinhamento.py`: estágio `alinhamento.json` (assinatura própria; guarda o CTC CRU, a regra −41/+60 ms é
  aplicada ao ler, em `bordas`). Omnilingual int8 no onnxruntime, sem prepack nem arena, sessão de UM master (carga ~0,3–0,8 s).
  Janela por fala ≤ 6 s (a longa repartida no maior vão) + **2 palavras de contexto** de cada vizinha a até 1 s (alinhadas e
  descartadas). ⛔ Só no Mac: no Windows `nao_medido` (L4 leva o pedido ao Mac). Modelo: `tools/instalar_alinhador.py --de <pasta>`,
  ou `CICLOASSIST_ALINHADOR` apontando a pasta (desenvolvimento).
- `voz.py` v2: com alinhamento, o início é o do alinhador (sem busca de energia) e o fim é `max(voz na lapela, CTC + 60 ms)`;
  sem lapela, a borda do alinhador vale sozinha (`borda_por`). `t_alinhado`/`fim_alinhado` por palavra. O `voz.json` refaz
  sozinho quando o alinhamento chega ou muda. `analise.alinhar` entre `quem_fala` e `medir_voz`; falha nunca tira a transcrição.
- `tests/test_alinhamento.py` (10). Suíte no Mac **1946/38**. Prova de ponta a ponta pelo cache (dados temporários, take C4
  P1-T001): 1ª vez 39,6 s, 2ª instantânea, 649/649 palavras, corte estendido pela voz em 23 de 91 falas.
- **Take real × Premiere 2026** (`spikes/transcricao_por_palavra/medir_l1.py`, o código do produto): início ≤ 1 q **86 %** (Whisper
  cru 43 %); nas pausas o fim fica **antes** do Premiere em 1 % (Whisper cru 75 %) e depois dele em 74 % (o lado conservador que o
  autor prefere). Custo: **33 s, 1,35 GB de pico** para 9 min (o pico inclui o som inteiro e os envelopes, não só o modelo).
- ⚠️⚠️ **Os vereditos de ouvido da sessão anterior não foram gravados** (só a chave A/B e o resumo no banco). Reconstruídos pelo
  resumo (quem ganhou cada borda), a L1 dá **9/17 a ≤ 1 q e 3 cortando** — mas a reconstrução é CIRCULAR: nos 5 fins em que "o
  nosso ganhou", o ouvido estimado É o valor da régua antiga (lapela 30/15), que por isso leva o crédito de graça. Onde a L1
  discorda: "Eduardo." −130 ms e "aqui." −300 ms (a régua do `voz.py` — 10 dB acima do piso — encerra a voz antes da 30/15),
  "secretária." +650 ms e "toda." +120 ms (o CTC estica a última letra; o contexto das vizinhas não mudou isso).
- ⬜ **Decisão do autor:** a régua do FIM — a do `voz.py` (validada nas emendas do editor na C07) ou a 30/15 da L0 (a que ele
  julgou de ouvido) — sai de um **segundo juiz de ouvido**, cego, com a L1 contra o Premiere nas bordas de pausa onde discordam,
  e desta vez com os vereditos GRAVADOS num arquivo ao lado da chave.

- ⭐⭐ **2º juiz de ouvido (autor, 2026-11-11, cego, L1 × Premiere, 19 de 20 respondidas; vereditos em `vereditos_L1.json`):**
  **Premiere 14, L1 5.** Inícios: Premiere 4 de 5 (a L1 erra por 42–80 ms nos dois sentidos). ⛔⛔ **Fins: o que alonga é a LAPELA,
  não o CTC** — nos 7 fins que a L1 perdeu por +120 a +680 ms, o CTC+60 sozinho ficava a −88…+71 ms do Premiere (02 +46, 05 +45,
  10 +18, 14 +71, 15 +26; 07 −61, 16 −88); a voz na lapela (`voz.py`, 10 dB sobre o percentil 20, tolerância 3 dB) estende até
  +400…+680 ms. A lapela acertou em 2 (09 "e" +260 contra CTC +95; 20 "você" +500 contra CTC −104) e o CTC estica sozinho em 2
  (11 "um" +531, 17 "Personagem F." +320). ⇒ a regra `fim = max(voz, CTC+60)` está REPROVADA pelo ouvido; o fim conservador da lapela
  passa da conta na maioria. ⬜ Decisão do autor: fim = CTC+60 (e a lapela só onde o CTC não mediu?), ou investigar por que a máscara
  segue a voz depois do fim (respiro, vazamento do outro).
- ⭐⭐ **Por que a lapela alonga o fim (2026-11-11, o sinal dos 14 fins julgados):** a palavra acaba num TOMBO (de +15…+27 dB sobre o
  limiar para −1…+9) e a máscara (piso global +10 dB, buraco de 120 ms preenchido, alcance 0,6 s) segue acesa nesse RESTO FRACO — sala,
  respiro, ou a OUTRA lapela (no `medir_l1.py` a fala vai sem dono e o fim procura em qualquer lapela). Onde a L1 acertou ("e", "você")
  a voz segue FORTE (+13…+19) até o fim marcado. ⛔ E o fim chegava a passar do início da palavra seguinte ("apartamento," "de").
  ⭐ **Régua candidata — a QUEDA:** na lapela mais forte NA palavra, o fim é onde o nível fica 10 dB abaixo do pico dos últimos 300 ms
  por 50 ms; teto 0,6 s e 30 ms antes da próxima palavra; piso CTC+60. ⇒ **10 de 14 fins com o ouvido** (a L1 de hoje: 4; D de 10 a
  20 dB dá o mesmo placar, 10 é o que não erra "apartamento"). Os 4 que sobram: "um" e "Personagem F." (o CTC estica a palavra: +531, +320),
  "ler?" (o piso +60 passa do Premiere) e "telefone." (por 1 quadro). ⚠️ AJUSTADA nos mesmos 14 casos ⇒ `hipotese` até um 2º take.
  Scripts: `spikes/transcricao_por_palavra/olhar_fins.py`, `regua_da_queda.py`.
- ✅ **A QUEDA no produto (2026-11-11):** `voz.niveis` + `voz.queda`; `medir(..., nv)` usa a queda no fim de palavra ALINHADA (fala e
  palavra antes de pausa), limitada a 0,6 s e a 30 ms antes da palavra seguinte, piso CTC+60; sem nível, a máscara de antes.
  `voz.json` v3 (a queda na assinatura: o cache velho refaz sozinho). Conferido pelo `medir_l1.py`: **10 de 14 fins** com o ouvido
  (eram 4); inícios iguais. Suíte Mac 1949/38. ⬜ Conferir num 2º take (rodada curta de ouvido, vereditos em arquivo); ⬜ o CTC que
  estica a palavra ("um", "Personagem F."); ⬜ os inícios (Premiere 4 de 5).
