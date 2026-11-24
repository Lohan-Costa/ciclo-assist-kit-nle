# A diária no Premiere: converter no Resolve, importar (com ou sem proxy), sincronizar e fazer os merged

Pedido do autor (2026-11-07), antes da F5 no Windows:

> *"conseguimos fazer um processo similar ao resolve e avid, onde o resolve converte uma mídia, nesse caso um prores
> proxy — pro premiere não precisa ser mxf op-atom —, e importa no premiere, faz o sync e os mergedclipes? No
> premiere o proxy pode estar anexado à mídia original, então temos a escolha de trazer o convertido como mídia
> original, ou trazer o material em alta e atachar o proxy."*

É o espelho do fluxo do Avid que já roda (`executar_fluxo`: `converter_para_opatom` → `importar_masters_opatom` →
`som_direto_gerenciado` → `sincronizar_com_o_orbita` com `subclipes: por_cena`). No Premiere a peça equivalente ao
subclipe do Avid é o **merged clip** (banco `plugins/premiere-cep/subclipe-e-merged-clip.md` §1 — o `subclip` do
Premiere é outra coisa).

## 1. Onde estamos (levantado em 2026-11-07)

| etapa | Avid | Premiere | de onde vem |
|---|---|---|---|
| converter no Resolve | ✅ `converter_para_opatom` (DNxHD, MXF OP-Atom) | ⬜ não existe; o motor é o mesmo (`resolve_opatom.py`, processo filho, preset NOSSO, conferência da saída) | este repo |
| importar | ✅ `importar_masters_opatom` | 🟡 a ponte importa (spikes); nenhuma ferramenta de produto | `host.jsx` |
| anexar proxy | — | 🟡 `attachProxy(caminho, 0)` **medido** no 25.6.5: `true`, `hasProxy` vira `true`, **`getMediaPath()` continua o original**; `canProxy()` é `false` em áudio puro | banco `painel-servido-e-identidade.md` §4 |
| sincronizar | ✅ Órbita | ✅ `sincronizar_com_o_orbita` (o Órbita sincroniza; o painel CEP dele monta a sequência; precisa do painel aberto) | `orbita.py`, PONTE §7 |
| merged clip | ✅ (subclipe) | ⛔ **sem API**: nem ExtendScript (estático, 25.6.5: `isMergedClip` existe, verbo de fundir não; `Merge Clips` é diálogo modal), nem nas ferramentas do MCP 27.1 que o banco lista | banco §3; `ia-embarcada-nos-nles.md` §3f |
| merged pelo Órbita | — | 🟡 o Órbita **escreve** merged no `.prproj` (`gerar_merged.py`; abriu no 23.2 do Windows, "parece tudo certo"; a aba Merge em Lote existe). ⛔ A rota `POST /api/v1/merge` do contrato (PONTE §3, decidida em 17/09) **não foi implementada** — o `httpserver.rs` tem só `info`, `montagem`, `avid/sincronizar` e `nlejob` | DRAMASYNC |

⇒ O que falta, em ordem de custo: a conversão (pouco: o motor existe), o import com a escolha (pouco: a chamada está
medida), e o merged (o grosso, e é da sessão do Órbita).

## 2. As duas formas de trazer a mídia

| | **A — convertido como original** | **B — alta + proxy anexado** |
|---|---|---|
| o que o projeto aponta | o ProRes Proxy | o original (BRAW, MOV de câmera…) |
| o editor alterna | não (é a única mídia) | o botão de proxy do Premiere |
| volta para a alta | relink (editor ou De Lá Pra Cá) | não precisa |
| o cache do Assist | ⭐ o convertido casa com o original pelo conteúdo (`identidade.achar`, 202/203 medido) | ⭐ `getMediaPath()` é o original: a identidade não muda |
| quando serve | a alta não está nesta máquina | a alta está (o caso normal) |

⭐ **As duas, escolhidas no pedido** (`modo: original | proxy_anexado`); sem dizer, o modelo PERGUNTA (autor, §4). O som direto (WAV) entra SEMPRE como original — `canProxy()` é `false` em áudio, e o WAV não
precisa de proxy.

## 3. Fases

### P0 — medir antes de construir (Mac, Premiere 2025/2026; o 27.1 onde couber)

Material: uma diária com câmera + som direto. Candidatos: `MIDIAS DE TESTES/1 PRODUCOES/PRODUCAO-A` (BRAW do
Windows + `MIDIAS/CONVERTIDOS`) e a `DIARIA MAC01` (`~/Desktop`). Clipes sintéticos (nº do quadro nas barras) para
o que for conta de quadro.

1. **Resolve → ProRes Proxy MOV**, clipe a clipe: o nome sai o do clipe? o TC de início e o `reel_name` vêm do
   original? quantos canais de som (todos)? taxa e duração idênticas? (o `e_candidato` exige mesma taxa, mesmo TC e
   mesmo nº de quadros ±1 — é a mesma régua que o Premiere aplica ao proxy).
2. **`attachProxy` com o ProRes real** — e o que o Premiere RECUSA: canais de som diferentes do original, TC
   diferente, duração diferente, resolução de outra proporção. O banco só mediu o caso feliz (H.264, mesmos 4 canais).
3. **BRAW original + proxy**: o Premiere deste Mac lê BRAW (plugin da Blackmagic)? Sem leitor, B com BRAW é
   inviável aqui e só A serve — dito na recusa.
4. **Merged sobre clipe com proxy anexado** (merged feito à mão pelo menu, para medir): o merged herda o proxy? o
   botão alterna? o `getSequenceStructure` (27.1) / `cicloPedacosDa` mostram o quê?
5. **Trazer merged para o projeto ABERTO**: importar um `.prproj` (`importFiles`) que o Órbita gerou — vira bin? a
   mídia é reimportada (a armadilha do banco)? `consolidateDuplicates` resolve? Isto decide o desenho da P4.
6. Registrar no banco (`plugins/premiere-cep/`, `plugins/resolve-scripting/`) e na matriz de plataforma o que tocar
   caminho.

#### ✅ Resultado da P0 (2026-11-07, Mac: Resolve Studio 21.1 · Premiere 25.6.5) — banco `e474e1f`

| # | resposta |
|---|---|
| 0.1 | ✅ ProRes Proxy **pelo preset** (a dança do OP-Atom, trocando o codec para `mov`/`ProRes422P` depois de conferir o load): nome do clipe, TC, `reel_name`, quadros e taxa iguais; um canal por pista, na ordem (tom por canal, 1,0/0,0). ⛔ Só pela API: nome com sufixo e **4 mono → 2 canais**. ⚠️ Estéreo sai como 2 mono (o Premiere aceita). ⛔ DCI/BRAW (≠ 16:9): a TIMELINE tem de ter o tamanho do proxy (2048×1080), senão tarja. |
| 0.2 | `attachProxy` ~15 ms. **Recusa** (`false`, sem motivo) só canais diferentes e WAV. ⛔ **Aceita calado** outra proporção e **outro material** (outra duração e TC) ⇒ a P2 confere o par ANTES. Anexar de novo troca; `getMediaPath()` fica o original; `setEnableProxies` liga mesmo (quadro em negativo). |
| 0.3 | ✅ BRAW no Premiere do Mac (importador da Blackmagic instalado): importa, aceita proxy, mesmo quadro e mesmo log. |
| 0.4 | ⛔⛔ **O merged do Órbita NÃO usa o proxy** do clipe da bin (proxy em negativo: a bin vira negativo, o merged não) — ele aponta o camMC, a cópia própria da mídia. ✅ **O merged feito pelo MENU herda** (piloto, sincronismo por áudio): no `.prproj` salvo, as fontes do MasterClip próprio do merged têm `Content › ProxyMedia` (vídeo) e `AudioProxies › AudioProxy` (som); no do Órbita, sem `Content`. Molde no banco (`subclipe-e-merged-clip.md` §3c). |
| 0.5 | ✅ No 25.6.5 o `.prproj` de merged importado no projeto aberto **deduplica** (como no 23.2): 5 merged (`isMergedClip` `true`), nenhuma mídia duplicada, 2,1 s, sem queda. |

⇒ **Para a P4:** o builder do Órbita escreve, nas fontes do camMC de cada merged, o mesmo `Content` do merged
nativo (`ProxyMedia` no vídeo, um `AudioProxy` por canal) apontando o `Media` do proxy (`IsProxy` true) — molde
no banco. A P4 começa por gerar UM merged assim e conferir o negativo com o botão ligado.

### P1 — `converter_para_proxy` (Resolve)

- Generalizar o `resolve_opatom.py` em vez de copiar: mesma dança do preset (apagar → importar → carregar →
  CONFERIR → só então o codec; divergiu, PARAR), timeline NOVA, fila do editor intocada, processo filho.
- Preset novo versionado (`resolve/presets/CICLO-PRORES-PROXY.xml`): MOV, ProRes Proxy, clipes individuais, nome do
  clipe, todos os canais de som, TC do original.
- Destino: o editor diz no pedido (§4), sem padrão.
- ⛔ Agrupar por proporção: cada grupo numa timeline do tamanho do proxy (largura = 1080 × proporção, par). Pasta NOVA a cada conversão (como no OP-Atom), nunca por cima.
- Conferência da saída pelo `ffprobe` contra o original (taxa, quadros, TC, canais) — o que não bate vai em
  `problemas`, e o modo B recusa aquele clipe antes do Premiere.

#### ✅ P1 feita (2026-11-07, Mac, Studio 21.1)

`cicloassist/resolve_proxy.py` + a ferramenta `converter_para_proxy(projeto, pasta, destino)`
(`mcp/ferramentas/proxy.py`, escreve, os dois NLEs; também no `executar_fluxo`). O processo filho do
`resolve_opatom.py` passou a aceitar GRUPOS (uma timeline e um render por grupo, com o tamanho dele) e o formato
de saída; o OP-Atom manda um grupo só, como antes.
- **Medido no Resolve real, pela função do produto:** 6 vídeos a 23,976 (ProRes 1080 de 2 e 4 canais, UHD, DCI,
  BRAW 4K, sintético de 4 mono) → **6 de 6 proxies conferidos**, 2 grupos (4 em 1920×1080, 2 em 2048×1080),
  17 s; DCI e BRAW sem tarja (olhado). O OP-Atom depois da refatoração: 2 vídeos + 6 MXF de som, sem problemas.
- A conferência de cada par (taxa, quadros, TC, total de canais, tamanho, ProRes Proxy) é a que a P2 vai exigir
  antes de anexar. Recusas antes do cartão: sem destino (pergunte ao editor), destino relativo, pasta dos próprios
  originais, proxy com o mesmo nome já lá, dois clipes de mesmo nome, taxas misturadas.
- Suíte do Mac **1606 passed / 31 skipped**. ⬜ Pelo chat (com a pasta arrastada) fica para a P6.

### P2 — `importar_no_premiere` (ponte CEP; via MCP no 27.1 se ele tiver)

- `modo: original` → importa os convertidos numa bin.
- `modo: proxy_anexado` → importa os originais e anexa a cada um o seu proxy. O par sai pelo nome do clipe e é
  CONFERIDO por taxa + TC + nº de quadros + proporção + nº de canais (`identidade.e_candidato` e mais) — nunca
  pelo nome sozinho: o Premiere só confere os canais (P0.2) e aceita calado o resto.
- Funções novas no `host.jsx` (`cicloImportar`, `cicloAnexarProxy`), plano em texto tabulado, nunca código.
- Devolve o que entrou, o que ganhou proxy e o que foi recusado (com o porquê). Passa pelo portão (escreve).
- O som direto vai junto, como original, na bin do som.

#### ✅ P2 feita (2026-11-07, Mac, Premiere 25.6.5)

`importar_no_premiere(modo, diaria, proxies, bin)` (`mcp/ferramentas/diaria_premiere.py`, Premiere, escreve) sobre
`nle/premiere/diaria.py` + `cicloImportar` no `host.jsx` (ponte CEP: vale em todas as versões, o `attachProxy` é
ExtendScript). Sem `modo`, a conferência manda PERGUNTAR. Uma bin por subpasta debaixo da bin da diária. O par é
conferido antes (`resolve_proxy.conferir_par`); reprovado = a alta entra sem proxy, dito em `sem_proxy`. Arquivo
que já está no projeto (mesmo caminho de mídia) não é reimportado. A pasta de saída do `converter_para_proxy`
fica autorizada ao terminar (o editor aprovou gravar ali).
- **Medido no 2025 real:** `proxy_anexado` 7 itens em 0,7 s (6 vídeos com o proxy anexado e LIDO DE VOLTA,
  BRAW incluído; o WAV como original); `original` 6 proxies como mídia; repetir = 0 importados, 7 já estavam.
- Suíte **1614 passed / 31 skipped**.

### P3 — sincronizar (já existe)

`sincronizar_com_o_orbita` com a bin que a P2 criou. Conferir que, no modo B, o Órbita lê o ORIGINAL (o
`getMediaPath` diz isso) e que a sequência montada mostra o proxy quando o botão está ligado.

#### ✅ P3 feita (2026-11-07, Mac, Premiere 25.6.5 + Órbita 0.4.0 em modo motor)

A cadeia com a diária REAL (PRODE CAM B, 11 clipes de 4 canais + o ZOOM): `converter_para_proxy` 11/11 conferidos
(35 s) → `importar_no_premiere` `proxy_anexado` 12 importados, 11 com proxy (1,7 s) → `sincronizar_com_o_orbita`
(12 s): 1 câmera, 11 clipes, 1 take; o painel do Órbita montou a sequência `PRODE D01` — V1 com as 11 câmeras,
**todas com o proxy anexado** (o botão vale na sequência), A1 o som direto, A2–A5 o som da câmera.
- ⛔⛔ **Defeito achado e consertado:** nas versões sem o MCP nativo o `sincronizar_com_o_orbita` NUNCA achava
  arquivo — o `cicloArvore` da ponte não trazia o `arquivo` (o do MCP traz) e a ferramenta juntava zero
  ("o Órbita não reconheceu nenhuma fonte"). Agora o item vem do `cicloResumo`. Teste.
- Como o Órbita rodou neste Mac (sem app instalado): `cargo build` do `src-tauri` com o target em
  `~/Library/Caches/orbita-target` (30 s), `orbita --motor`, a `venv-mac` na frente do PATH e o
  `orbita-python` VELHO (julho) renomeado para `orbita-python.julho-antigo` — senão o sidecar o usaria (a venv
  de dev do SSD é a do Windows). O painel do Órbita aberto pelo menu Window ▸ Extensions ▸ Órbita Sync.

### P4 — merged (sessão do Órbita + uma ferramenta aqui)

- **No Órbita** (sessão dele, não esta): implementar `POST /api/v1/merge` — um tipo de trabalho novo na fila
  `/nlejob`, escrito pelo painel do Órbita, como o contrato de 17/09 manda (PONTE §5a). O desenho da escrita sai da
  P0.5.
- **Aqui:** `merged_pelo_orbita` (escreve; Premiere) + o passo no fluxo. Mesmo modelo da montagem: conferir o painel
  vivo no `/api/v1/info` ANTES do cartão; progresso no Ciclo Assist; o resultado lido de volta.
- Decisões do autor que já valem (DRAMASYNC, HANDOFF-WINDOWS): tomadas da **sequência ativa**, merged **aparado**.

#### 🟡 P4: o merged COM proxy feito no Órbita; falta a rota (2026-11-07)

- ✅ **No builder do Órbita** (`ea75984` no DRAMASYNC): `CameraAngle.proxy_path`/`proxy_size`;
  `_make_camera_media` escreve o `Media` do proxy (`IsProxy`) e o aponta em `Content › ProxyMedia` e
  `AudioProxies › AudioProxy`, a forma do merged nativo. Teste `test_prproj_merged_proxy.py`; a suíte Python do
  Órbita 937 passed. `gerar_merged.py --proxies`.
- ✅ **Medido no 25.6.5:** 11 merged da diária da P3 com proxy, o `.prproj` importado no projeto aberto (só os
  merged entraram, sem mídia duplicada), e o da PANA2774 com proxy em NEGATIVO vira negativo com o botão ligado.
- ✅ **Feito em 2026-11-06 (sessão do Órbita, Mac):** a rota `POST /api/v1/merge` no Órbita (`5241b5e`) e, aqui, a ferramenta `merged_pelo_orbita` (`mcp/ferramentas/merged_orbita.py`: sincroniza de novo — o Órbita guarda o sync só 2 min —, confere cada par com `conferir_par` e manda só os aprovados). Medido no 25.6.5 com a PRODE D06 num projeto vazio: 11 merged em `CENAS/NAO RESOLVIDO`, 11 com proxy, 8,6 s. O import JUNTA com uma `CENAS` que já exista e não cria bin com o nome do arquivo. ⬜ Pelo CHAT (com o painel do Ciclo Assist lendo a bin). ⬜ Passo fixo na receita: decisão do autor (dobra o sync). (Texto anterior:)
- ⬜ **Falta (sessão do Órbita):** `POST /api/v1/merge` (PONTE §9 do Órbita: job do sync + proxies conferidos →
  `.prproj` de merged por câmera de cada take, em bins por cena → o painel importa no projeto aberto) e, aqui, a
  ferramenta que a chama e o passo na receita.

#### ✅ P5 feita: a receita `preparar-diaria-no-premiere` (2026-11-07)

`cicloassist/receitas/preparar-diaria-no-premiere.md`: abrir o Resolve → `converter_para_proxy` → fechar o Resolve
→ abrir o Premiere → `importar_no_premiere` → `sincronizar_com_o_orbita`. `modo` e `destino` SEM padrão (o
editor escolhe a cada diária). **Rodada pelo executor do fluxo** com a PRODE (11 câmeras + ZOOM): 6 de 6 passos,
**54 s**, 11/11 proxies conferidos, 11 com proxy anexado, sequência montada pelo Órbita. O merged entra quando a
rota da P4 existir (dito na seção "Quando as condições mudam").

### P5 — a receita

`diaria_no_premiere`: converter → (fechar Resolve / abrir Premiere) → importar (modo) → sincronizar → merged, um
cartão só (`executar_fluxo`), parando em `esperando` quando um passo falha.

### P6 — conferir

Pelas ferramentas e pelo chat no 2025 e no 2026 (Mac); depois no Windows junto da F5, com o 23.x do notebook.


#### ✅ P6 feita pelo chat (2026-11-07, Sonnet 5.5, Premiere 25.6.5, mídia no SSD EXTERNO)

Diária em `MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-07 P6 DIARIA NO PREMIERE/` (cópia da PRODE CAM B
+ ZOOM; o exFAT não aceita hard link), proxies na mesma pasta.
- Pedido SEM modo e destino → o modelo **perguntou os dois** (e o projeto do Resolve) antes de qualquer cartão.
- Pedido completo, com a pasta em `referencias` → foi **passo a passo**, um cartão por turno (abrir o Resolve →
  `converter_para_proxy` 11/11 em 62 s → `importar_no_premiere` 12 itens, 11 com proxy → `sincronizar_com_o_orbita`
  → sequência montada). ⚠️ Não usou a receita nem o `executar_fluxo`: funciona, mas pede um "continue" por passo.
  ⬜ Avaliar se a persona deve sugerir a receita quando o pedido casa com uma.
- ⛔⛔ **Defeito achado e consertado:** item OFFLINE na bin (o arquivo sumiu do disco) derrubava o sync INTEIRO com
  "arquivo não encontrado", sem dizer qual. Agora fica de fora e vem em `offline_de_fora` (quantos, exemplos,
  aviso); todos offline = erro que diz isso. Teste.
- ⚠️ No caminho: o disco INTERNO encheu (33 GB de teste no scratchpad) — regra nova: mídia de teste no SSD externo
  (memória `arquivos-pesados-no-ssd-externo`). E o cartão VELHO de antes do disco cheio continuava aberto
  (ADR 0008: o cartão espera o editor) — o condutor de teste passou a aprovar só cartão do turno.

#### ✅ P6 com o Órbita EMBUTIDO (aba Preparar), pelo chat no Premiere 26.0.2 (2026-11-06, noite, Mac mini)

O app inteiro no ar (guarda-chuva; os três motores subidos por ele; o Órbita em `--motor` achou a `venv-mac` sozinho).
Projeto novo `MIDIAS DE TESTES/9 SAIDAS DOS APPS/_CICLO ASSIST/2026-11-06 P6 ORBITA EMBUTIDO/P6 ORBITA EMBUTIDO.prproj`,
proxies na `PROXY/` de lá, mídia lida da PRODE D06 da rodada anterior.
- Cartões: criar o projeto 0,6 s → (fechar/reabrir o Premiere para carregar a ponte do Órbita) → abrir o Resolve 9 s →
  `converter_para_proxy` 11/11 em 68 s → `importar_no_premiere` 12, 11 com proxy, 2,9 s → `sincronizar_com_o_orbita`
  15 s, **sequência montada pela Preparar** → `merged_pelo_orbita` 11 merged com proxy em `CENAS/NAO RESOLVIDO`, 14 s.
  Árvore: 29 itens, nenhum clipe repetido.
- ⛔⛔ **O que faltava:** a `/api/v1/nlejob` e a `/api/v1/merge` deixavam o trabalho na fila do painel CEP do Órbita, que
  a Preparar não lia — o sync parava em 412 ("painel não aberto"). Órbita `55808e4`: a Preparar lê a fila e executa
  pela ponte dela. O painel CEP não é mais usado (decisão do autor, 06/11).
- ⚠️ No chat: "continue" mandou importar sem ter gerado os proxies (a pasta PROXY vazia não foi anexada); com as duas
  pastas anexadas e "gere primeiro" ele seguiu certo. E segue um cartão por turno (não usa a receita).
- ⬜ Logo depois de abrir o app, a Preparar só atendeu quando a aba foi MOSTRADA uma vez (escondida desde o início, a
  presença ficou falsa); depois de carregada, escondida ela atende. ⬜ O Resolve tem um render velho parado na fila do
  projeto `PRODE D06` (destino no scratchpad, que não existe mais): não dar "Render All" ali.

## 4. Decisões do autor (2026-11-07)

| pergunta | resposta |
|---|---|
| padrão quando o pedido não diz A ou B | **perguntar sempre** — o modelo pergunta qual das duas formas antes do cartão |
| resolução do proxy | **1080 fixo** (1920×1080, ou a proporção do original nessa altura) |
| onde gravar os proxies | **perguntar no pedido** — o editor diz o destino a cada vez |
| merged | **um por câmera de cada take, em bins por cena** (`CENAS/C04`), como os subclipes do Avid |

⬜ Em aberto: abrir a sessão do Órbita para a `/api/v1/merge` depois da P0 (o desenho da escrita sai da P0.5).
⇒ Consequências: `importar_no_premiere` não tem `modo` padrão (sem ele, a conferência recusa dizendo para perguntar);
`converter_para_proxy` exige `destino` (sem padrão); o preset do proxy é 1080.

## 5. Riscos

- O `attachProxy` pode recusar em silêncio (devolver `false` sem motivo): cada recusa medida na P0.2 vira frase.
- Merged trazido por `.prproj` pode reimportar a mídia e duplicar itens: se a P0.5 não achar caminho limpo, a P4
  vira "o Órbita gera o projeto da diária inteiro" (em vez de escrever no projeto aberto), e isso é decisão do autor.
- BRAW sem leitor no Premiere desta máquina limita o modo B no Mac.
