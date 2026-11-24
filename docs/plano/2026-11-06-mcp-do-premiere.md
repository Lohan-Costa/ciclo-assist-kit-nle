# O Ciclo Assist falando com o MCP nativo do Premiere (27.1+)

> Plano, 2026-11-06 (Mac mini). Estado: **APROVADO pelo autor em 2026-11-06 (decisões em §7)** — **F0–F4 FEITAS no Mac** (§8–§12); **F5 (Windows) preparada**, falta rodar no notebook.
> Base medida: banco `transversal/ia-embarcada-nos-nles.md` §3f; spike `spikes/o_mcp_do_premiere.py`.

## 1. Por quê

O Premiere 27.1 traz um servidor MCP próprio com 60 ações (25 de leitura, 35 de escrita), e a medição de hoje
mostrou que ele é **rápido** (1–90 ms por ação, contra ~5 s do `evalScript` sob carga — §vigia do CLAUDE.md) e
**alcança o que a ponte CEP não alcança**: montar e editar a timeline, ver o quadro composto da sequência e saber o
que o editor está olhando. Cada escrita vira **um passo do Desfazer nativo** (medido).

**Princípio do autor (2026-11-06):** a via mais nova quando a versão tiver; a conhecida nas antigas; fluxo novo
nas antigas só se for completo. ⇒ Nada que funciona hoje pela ponte CEP é desligado; o MCP entra por
**capacidade detectada**, ação por ação.

## 2. O desenho em uma figura

```
ferramenta do chat / aba / fluxo
        │  pede uma OPERAÇÃO nossa ("itens do projeto", "montar o corte"...)
        ▼
cicloassist/nle/premiere/vias.py      ← escolhe a via por operação, a cada sessão do Premiere
   ├─ via MCP  (mcp_nativo.py)  : se a porta responde E o tools/list tem as ações que a operação usa
   └─ via CEP  (ponte.py + host.jsx): o caminho de hoje, intacto
```

- **Detecção por CAPACIDADE, não por número de versão:** porta + `initialize` + `tools/list`; a operação declara
  quais ações exige (`requer = {"createSequences", "insertClipsToSequence"}`). Faltou uma, ela fica na CEP (se a CEP
  a tiver) ou responde com a frase do gesto ("isto pede o Premiere 27.1+ com o servidor MCP ligado").
- O catálogo é lido UMA vez por processo do Premiere (pid) e relido quando chega `notifications/tools/list_changed`
  ou a conexão cai.
- **O modelo NUNCA vê as 60 ações cruas.** Ele continua vendo as ferramentas do Ciclo Assist (curadas, com
  procedência, conferência antes do cartão e o portão — ADR 0005/0008). O MCP do Premiere é motor, não catálogo.

## 3. A conexão

| item | onde | medido |
|---|---|---|
| porta / caminho / auth ligada | prefs do perfil (`HSL.Prefs.McpPort`, `McpPath`, `McpEnabled`, `McpAuthenticationEnabled`) | Mac ✅ |
| **token** | **Keychain**, serviço `PremierePro.MCP`, conta = Adobe ID | Mac ✅ (só metadado lido) · Windows ⬜ |
| protocolo | MCP Streamable HTTP 2025-06-18, SSE na resposta, `mcp-session-id` | Mac ✅ |

- Cliente em stdlib (regra da casa: sem framework), o do spike promovido a `mcp_nativo.py`, com prazo em toda
  chamada, uma sessão por processo do Premiere e reconexão quando a sessão expira.
- ⛔ O token nunca vai para log, para o modelo nem para a tela.
- Concorrência: o MCP do Premiere atende pedidos em paralelo à ponte CEP? ⬜ medir (F0) — se não, a mesma regra da
  ponte: gesto do editor na frente, fundo recua.

## 4. Operação por operação

| operação nossa | hoje (CEP) | com MCP | decisão proposta |
|---|---|---|---|
| projeto aberto, sequência ativa | `cicloProjeto` | `getOpenProjects` + `getEditingContext` (+ agulha, seleção, monitor ativo) | **MCP** (mais rico) |
| bins / itens / árvore | `cicloBins/Itens/Arvore` | `getProjectItems` (1 ms) | **MCP** |
| clipes do projeto (aba Vetores, busca, vigia) | `cicloMidias` (~0,5 ms/item, 5 s sob carga) | `getProjectItems` + `getClipMetadata` (`filePath`, `start`, fps, canais) | **MCP** — e a vigia pode sondar a 1 ms em vez de recuar |
| subclipes (índice de recortes) | `SubclipStart` − TC do arquivo | `getClipMetadata`/`getInOutPoints` — ⬜ medir se dá a janela CERTA do subclipe | depende da F0 |
| resolver um take (`resolver_item_do_premiere`) | `cicloItem` | metadado + caminho | MCP se a F0 confirmar o subclipe |
| carregar no Source + agulha | `openProjectItem` + QE `scrubTo` | **não existe** no MCP | **fica CEP** |
| coluna Descrição | `cicloDescrever` (compare-and-set) | só LEITURA (XMP via `getClipMetadata`) | **fica CEP** |
| organizar o projeto (bins, mover, renomear) | `cicloOrganizar` | `createBins` · `moveOrCopyProjectItems` · `renameProjectItems` (atômicos, desfazíveis) | **MCP** |
| abrir/salvar/sair do projeto | `cicloAbrirProjeto/Salvar/Sair` | não existe | **fica CEP** |
| ⭐ **montar_corte** | só Avid | `createSequences` + `insertClipsToSequence` (3 pontos, trilha alvo, insert/overwrite) | **NOVO no Premiere** |
| ⭐ **separar_falas** (uma timeline por fala) | só Avid | o mesmo + `manageMarkers` (marcador com o texto da fala) | **NOVO no Premiere** |
| ⭐ ler_timeline / editar_timeline | só Avid | `getSequenceStructure` · `razorTrackItems` · `trimTrackItems` · `deleteTrackItems` · `moveOrCopyTrackItems` | **NOVO no Premiere** |
| ⭐ o que está na tela | só Avid | `getEditingContext` + `renderFrame` (o quadro COMPOSTO da sequência, com efeitos) | **NOVO no Premiere** |
| quadros para decupagem / vetores | ffmpeg no cache (por UMID) | `renderFrame` do clipe | **fica ffmpeg** (cache compartilhado com o Avid; `renderFrame` só para a sequência) |
| transcrição | faster-whisper por canal, cache | `createTranscript` local (18 s/92 s), sem falante por canal | **fica a nossa** — ver §7 Q3 |
| busca | decupagem + fala + vetores | agente de transcrição em PT; visual/áudio só inglês e ruidoso | **fica a nossa**; o MCP não entra na v1 |

**Regras que a escrita pelo MCP herda:**
- ⛔ Tempo em segundos de **quadro exato** (`Fraction(n, fps)`): o Premiere arredonda para BAIXO (pedido 2,0 s →
  1,96 s em 23,976). Conferir o que entrou lendo de volta (`insertedItems` traz `sourceInPoint/OutPoint`) e reprovar
  diferença de quadro — o mesmo espírito da prova do `editar_timeline` do Avid.
- ⭐ O cartão do portão diz *"Desfazer (Cmd+Z) no Premiere desfaz isto em um passo"* — medido; vale lote atômico.
- A conferência ANTES do cartão (âncora, cobertura, ordem) é a MESMA do Avid: muda só o executor.

## 5. Fases

| fase | entrega | prova |
|---|---|---|
| **F0** medir o que falta | subclipe pela via MCP; ida-e-volta de quadro exato (23,976 / 25 / 29,97 DF); `insertClipsToSequence` com WAV multicanal (em quantas trilhas cai?) e com **merged clip**; concorrência MCP × CEP; `getProjectItems` num projeto real (centenas de itens); prompt do Keychain na 1ª leitura do token | spike estendido, números no banco |
| **F1** cliente + vias + LEITURA | `mcp_nativo.py`, `vias.py`, operações de leitura pelo MCP com queda para a CEP; `/conexao` diz qual via está ativa | suíte (com servidor falso) + Premiere real com e sem o servidor |
| **F2** organizar pelo MCP | `organizar_o_projeto` com as ações atômicas | cartão → Desfazer nativo desfaz |
| **F3** ⭐ montar_corte e separar_falas no Premiere | as duas ferramentas passam a `AMBOS`, executor por NLE | a C07 (ou a cena do teste) montada no Premiere, conferida a olho e por `getSequenceStructure` |
| **F4** ler/editar timeline + o que está na tela | `ler_timeline`, `editar_timeline`, `o_que_esta_na_tela` no Premiere | edição numa timeline feita à mão pelo autor |
| **F5** Windows | token e prefs no Windows, a suíte lá | rodar F1–F4 no notebook (sem IA local: o MCP não roda modelo) |

## 6. O que NÃO entra (v1)

- Expor ações do Premiere que não têm par no Ciclo Assist (efeitos, cor, máscara, auto-reframe, export).
- Usar a busca visual/áudio do Premiere (só inglês; o áudio devolve ruído).
- Ligar o servidor sozinho: a bandeira é da Adobe; o produto detecta e diz o gesto.

## 7. Decisões do autor (2026-11-06)

**Decidido:** (1) token pelo **Keychain**; (2) depois da F1 vem a **F3** (corte e falas), a F2 fica depois;
(3) transcrição **sempre a nossa**; (4) ações sem par **fora da v1**. Ordem das fases: F0 → F1 → F3 → F2 → F4 → F5.

As perguntas, como foram feitas:

1. **Token:** ler do Keychain (o macOS pergunta uma vez "permitir?") · desligar a autenticação no Premiere ·
   o editor colar o token na engrenagem. *Recomendação: Keychain.*
2. **Ordem depois da F1:** montar_corte/separar_falas no Premiere primeiro (F3) · organizar primeiro (F2, menor).
   *Recomendação: F3 — é o ganho que não existe hoje.*
3. **Transcrição:** sempre a nossa · aproveitar a do Premiere quando o clipe já tiver (sem ASR, mas sem falante por
   canal e com cache só daquele projeto). *Recomendação: sempre a nossa.*
4. **Ações do Premiere sem par no Ciclo Assist** (efeitos, cor, máscara…): fora da v1 · um passe controlado já.
   *Recomendação: fora da v1.*

## 8. F0 — resultado (2026-11-06, Mac; banco §3f "F0")

| pergunta | resposta | efeito no desenho |
|---|---|---|
| quadro exato | `n/fps` erra 1/6 em 23,976 e 29,97; `(n+½)/fps` acerta 6/6 nas três taxas (lido na imagem) | todo tempo mandado = `(n+½)/fps`, e lido de volta |
| subclipe | `getClipMetadata` dá a janela direto (`start`/`end`); na timeline o tempo é relativo ao subclipe | o índice de recortes sai do MCP, sem a conta do TC |
| timecode | XMP `xmpDM:altTimecode`/`startTimecode` com o formato (inclui DF) | a TC da fala sem `ffprobe` quando o MCP estiver |
| ⛔ áudio multicanal | `insertClipsToSequence` leva UM canal (nem o 1º) | **montar_corte/separar_falas no Premiere NÃO usam insert para o som**: sequência do clipe + `moveOrCopyTrackItems` (5 de 5 canais) — aparar depois de copiar ⬜ medir no início da F3 |
| merged clip | `type: sequence`; estrutura com o deslocamento de cada componente | tratar como sequência-fonte (a mesma cópia de itens) |
| concorrência MCP × CEP | ~1 ms, sem interferência | sem fila própria para o MCP |
| escala | 613 itens 24 ms; metadados de 583 em 225 ms | a vigia pode sondar pelo MCP |
| token | Keychain pede a **senha de login** do Mac uma vez; "Permitir Sempre" libera o `security` para qualquer processo | ver a pergunta abaixo |

**Pergunta nova ao autor (antes da F1):** o token pelo Keychain exige a senha do Mac na 1ª vez, e o "Permitir
Sempre" vale para qualquer programa que use o `security`. Alternativas: (a) aceitar isso; (b) o Ciclo Assist guardar
o token na pasta de dados dele, lido UMA vez com a senha; (c) desligar a autenticação do servidor (só localhost).

**Decidido (autor, 2026-11-06):** no DESENVOLVIMENTO, a autenticação do servidor fica DESLIGADA, de forma
permanente, nas máquinas de dev (feito no Mac mini: `setPreferences({authenticationMode: 0})` pelo Test Host Plugin;
gravado em `HSL.Prefs.McpAuthenticationEnabled = 0` ao sair; conferido depois de reabrir — 200 sem token). O servidor
continua só em `[::1]:3000` (pela rede não conecta). **Como PRODUTO a forma de obter a senha está em aberto** — a F1
deixa o cliente aceitar os dois (sem senha, ou token de uma fonte a decidir) e não escolhe a fonte.

## 9. F1 — feita (2026-11-06, Mac)

- `cicloassist/nle/premiere/mcp_nativo.py`: cliente stdlib (sessão, SSE, prazo, senha opcional por
  `CICLOASSIST_PREMIERE_MCP_TOKEN`), catálogo sondado no máximo a cada 10 s, `via(operacao)` por CAPACIDADE
  (`OPERACOES`), `CICLOASSIST_PREMIERE_VIA=cep|mcp|auto` para comparar.
- Pela via MCP com queda para a CEP (`premiere._pelo_mcp`): `projeto_aberto`, `estado` (fps exato: 23,976 →
  24000/1001), `_midias` (o `cicloMidias`: aba Vetores, escopo da busca, vigia) e `contador_da_vigia`. A vigia não
  depende mais do painel CEP vivo (`premiere.alcancavel`). `/conexao` diz `detalhe.premiere.mcp.vias`.
- ⛔ Ficaram na CEP de propósito: tudo que devolve `nodeId` do ExtendScript para outra operação da CEP (bins, itens,
  árvore, seleção, resolver item, organizar) — os ids do MCP são outros, e misturar quebraria o fluxo no meio.
  Índice de subclipes: depois (a F0 mostrou que o MCP o dá direto).
- Testes: `tests/test_mcp_do_premiere.py` (servidor MCP falso), o conftest isola o MCP real da máquina
  (`sem_mcp_do_premiere`). ⛔ Achado: `monkeypatch.undo()` desfaz o isolamento — o teste da vigia passou a ler o
  Premiere REAL e falhou; reaplicado no próprio teste. Suíte do Mac: **1571 passed, 31 skipped**.
- **No Premiere real, pelo serviço** (projeto de teste, 10 mídias): a lista da aba Vetores é IGUAL nas duas vias
  (nome, arquivo, bins); `/vetores?nle=premiere` 53 ms (CEP) → 8 ms (MCP); `/projeto` 123 → 10 ms. Com o
  Premiere ocioso — o ganho grande é sob carga (a CEP mediu 5 s por `evalScript`).
- ⬜ Vigia de ponta a ponta pelo MCP (importar com ela ligada) não exercitada no Premiere real.

## 10. F3 — montar_corte e separar_falas no Premiere (feita, 2026-11-06)

- `nle/premiere/montagem.py`: sequência-fonte por pedaço (o take inteiro, todos os canais) → navalha
  (imagem e som separados: L/J) → cópia do pedaço do meio → apaga as fontes → LÊ DE VOLTA e confere
  cada pedaço no quadro. Falhou no meio: a sequência incompleta também é apagada.
- ⛔ Achado: `trimTrackItems` NÃO está no catálogo; e a navalha NÃO encaixa no som (`(n+½)/fps` cortou o
  áudio em 195,5 quadros e a imagem em 201) ⇒ todo tempo vai como `n/fps + 1 µs` (195 e 200 exatos).
- `montar_corte` (mesma conta de L/J do Avid, `corte.pedacos_do_plano`) e `separar_falas` (mesmas
  conferências: âncora, cobertura dos takes da cena, fala repetida em `acrescentar_em`) passam a valer no
  Premiere. Take só de som (WAV): a sequência nasce vazia na taxa do take. Coberturas (alpha) e mistura de
  taxas: recusadas com a frase. Sem MCP: a frase com a versão e o gesto.
- Medido no Premiere real: 3 pedaços (corte em J + WAV 5 canais) em 0,19 s, quadro conferido na imagem e os
  5 tons no export; `montar_corte` 4/4 pedaços em 0,14 s; `separar_falas` da C04 (WAV do gravador): bin
  `C04 FALAS`, 3 timelines a 23,976 com os 5 canais, a entrada da FALA01 no quadro 620 da transcrição.
- `spikes/no_servico.py`: roda um roteiro DENTRO do serviço (a ponte CEP só fala com o processo da 7824).

## 11. F2 — organizar pelo MCP (feita)

- Árvore, bins, itens, seleção (`getEditingContext.projectPanelSelection`) e `organizar_o_projeto`
  mudaram JUNTOS para o MCP: os ids que o modelo lê são os que ele manda. Merged reconhecido pela estrutura
  (todos os pedaços com o nome dele). Quem continua na CEP (`resolver_item`, carregar no Source) traduz id do
  MCP → caminho "BIN/NOME" (`premiere._ref_para_cep`).
- Medido: árvore igual nas duas vias (35 itens) fora o clipe "(Aprimorado)" (composto, sem arquivo: CEP
  "clipe", MCP "outro" — mantido); organizar criou, moveu, renomeou e apagou a bin vazia com ids do MCP; a
  conferência barrou "bin dentro de si mesma"; `resolver_take` da CEP aceitou um id do MCP.
- ⚠️ Mover para a RAIZ do projeto pelo MCP: recusado com a frase (o `parentId` é obrigatório e a raiz não
  tem id) — pela CEP continua possível.

## 12. F4 — a timeline do editor e a tela (feita)

- `nle/premiere/edicao.py`: `ler` (trilha a trilha, TC desde 00:00:00:00 da sequência), `editar` numa CÓPIA
  com PROVA (extrair = navalha + apagar + puxar; abrir_espaco = navalha + empurrar; inserir = abrir + o
  caminho da montagem, canais nas trilhas pedidas), operações da última posição para a primeira.
  `ler_timeline`, `conferir_a_edicao`, `editar_timeline` e `o_que_esta_na_tela` valem no Premiere.
- Medido: extrair + abrir + inserir numa chamada, 0,08 s, 9 pedaços provados, quadro a quadro certo na
  imagem; edição malformada barrada antes do cartão.
- ⚠️ Fora da prova: efeitos e transições (uma chamada por item); TC de início da sequência ≠ 0 não lido.

## F5 — Windows (preparada)

`tools/premiere_mcp/LEIA-ME.md`: os scripts do Test Host Plugin e os passos. Falta: rodar no notebook,
medir a porta/prefs/Debug Database de lá, a suíte e os spikes. ⬜ Matriz de plataforma: linha nova.

## 13. Versões e o teste PELO CHAT (2026-11-06, noite)

**Em que versão funciona:** só no Premiere **27.1 (Beta)**. Conferido nos executáveis deste Mac: 25.6.5 (2025)
e 26.0.2 (2026) não têm o servidor (`PPro.MCP.EnableMCPServer`, `premiere/mcp`, `mcp::*Tool`: zero); o plugin
"Assistant" deles é a geração anterior, sem MCP. ⇒ Nos 2025/2026 o Ciclo Assist continua com as leituras e o
organizar pela CEP; montar, separar falas, ler/editar a timeline e "o que está na tela" respondem com a frase
da versão. ⬜ Possível fluxo novo para as antigas (princípio do autor, "se for completo"): o ExtendScript tem
`insertClip`/`overwriteClip` e a navalha do QE — NÃO medido (canais de áudio e precisão de quadro por lá
ainda são pergunta aberta).

**Pelo chat, com o modelo (Sonnet 5.5, via `/conversar` com `nle: premiere`, cartões aprovados por
`/responder`):**
| pedido do editor | o que o modelo fez | resultado |
|---|---|---|
| o que está na tela e a timeline | `o_que_esta_na_tela` + `ler_timeline` | descreveu a C04_FALA03 certo (5 trilhas do WAV, entrada 858), 11 s, US$ 0,11 |
| separar as próximas duas falas da C04 | `consultar_o_metodo`, listar, `transcrever`, `ler_timeline` | NÃO inventou: viu que depois da FALA03 só há conversa de set, e perguntou |
| "separe o 'Não.' como FALA04" | `separar_falas` com `acrescentar_em` | cartão → aprovado → C04_FALA04 na bin em 0,2 s |
| 8 s da câmera a partir de "Eu sou Personagem F" | `transcrever` + `montar_corte` | cartão → 2 de 2 pedaços no quadro, 0,1 s |
| tirar a pausa entre as duas falas, numa cópia | `ler_timeline` + `conferir_a_edicao` + `editar_timeline` | tirou 12 de 22 quadros (deixou respiro); cópia certa (8 s → 7 s 12 q, sem salto de material) |

Consertos que o teste pelo chat mostrou: o cartão dizia "montar este corte **no Avid**" e "numa bin **nova**"
num turno do Premiere (rótulos neutros agora); a prova da edição contava pedaços que a edição tocou como
"conferidos" (agora conta só os conferidos e DIZ quando não sobrou nada para provar); corte só de som no
Premiere usa a taxa da sequência ativa.

## 14. O ExtendScript nas versões antigas — MEDIDO (2026-11-06)

Premiere 2026 (26.0.2) e 2025 (25.6.5), resultados idênticos (banco `plugins/premiere-cep/api-extendscript.md`,
seção nova; `spikes/extendscript_nas_versoes_antigas.py`):
- 3 pontos (`setInPoint/OutPoint` + `overwriteClip`) com `n/fps + 1 µs`: **12/12 no quadro, na imagem**.
- **Som multicanal INTEIRO** (5 de 5 canais) — melhor que o `insertClipsToSequence` do MCP.
- Navalha do QE por timecode: sempre no quadro. Trilha alvo e ripple (`insertClip`) funcionam.
⇒ **Há caminho para montar_corte e separar_falas nas versões antigas pela ponte CEP** (o princípio do autor:
fluxo novo nas antigas se for completo). Faltam medir antes de construir: som SÓ numa trilha (L/J), devolver as
marcas de entrada/saída do clipe do editor, `sequence.clone()`/`trackItem.move` (para editar_timeline) e o 23.x
do Windows. Proposta: **F6** — o executor da montagem com duas implementações (MCP no 27.1+, ExtendScript nas
antigas), a mesma conferência e a mesma prova.

## 15. F6 — montar_corte e separar_falas nas versões ANTIGAS, pela ponte CEP (feita, 2026-11-06)

Decisão do autor: **corte em L/J fica com o editor** (subjetivo) — o caminho novo RECUSA L/J com a frase; nada de
L/J foi medido. As outras integrações, sim:
- `host.jsx` `cicloMontar(plano)` — plano em TEXTO tabulado (nunca código): cria a sequência a partir do 1º take
  com imagem, esvazia, e para cada pedaço `setInPoint/OutPoint` (+1 µs) + `overwriteClip` na V1 (ou A1 se só som);
  cria a bin de destino se faltar; DEVOLVE as marcas de entrada/saída do clipe do editor; lê a sequência de volta
  (ticks). ⛔ Achado: o ExtendScript dá um OBJETO NOVO a cada acesso ao mesmo item — `===` não reconhece; as
  marcas voltavam erradas (as do 1º pedaço) até a deduplicação passar a ser pelo `nodeId`.
- `nle/premiere/montagem_cep.py` — a mesma prova da via MCP (cada trilha de cada pedaço no quadro pedido).
- `montar_corte` e `separar_falas`: MCP quando o Premiere aberto tiver; senão a ponte. A bin "(raiz do projeto)"
  vale como a raiz. A cobertura de takes do `separar_falas` usa a árvore com escolha de via.
- **Medido no Premiere 2026 (26.0.2), pelas ferramentas de produto:** `montar_corte` (2 cortes de imagem + 1 trecho
  só de som do WAV 5.0): 9/9 pedaços no quadro, imagem 50/74/200/224 exata, os 5 tons no export, marcas do clipe
  4–5 s antes e depois, 0,22 s; `separar_falas` da C04: 2 timelines com as 5 trilhas do WAV, 0,31 s.
- ⬜ Faltam nas antigas: `ler_timeline`/`editar_timeline`/`o_que_esta_na_tela` (medir `sequence.clone()`,
  `trackItem.move`, `remove(ripple)`); o 2025 pela ferramenta (a medição de base foi idêntica ao 2026); o Windows 23.x;
  pelo chat no 2026.

## 16. F7 — ler/editar a timeline e "o que está na tela" nas versões ANTIGAS, pela ponte CEP (feita, 2026-11-07)

Medido no Premiere 2026 (26.0.2) antes de construir (banco `plugins/premiere-cep/api-extendscript.md`, seção de
2026-11-07): `sequence.clone()`, navalha do QE trilha a trilha, `remove`/`move` só no item, `overwriteClip` por
índice de trilha (imagem em V(k), som a partir de A(k)), `inPoint`/`outPoint` graváveis no item (slip).
- `host.jsx`: `cicloLerSequencia`, `cicloEditar` (plano em texto tabulado, tempos em TICKS inteiros; clonar, levar
  a cópia para a bin da original, navalha, tirar, empurrar, inserir, tirar o "acompanhante" não pedido),
  `cicloApagarSequencia`, `cicloTemClipe`, `cicloTela`.
- `nle/premiere/edicao_cep.py`: a MESMA validação e a MESMA prova do `edicao.py` (via MCP), mais a grade em ticks.
  `M.via("edicao")` e `M.via("tela")` escolhem; `ler_timeline`, `conferir_a_edicao`, `editar_timeline` e
  `o_que_esta_na_tela` deixaram de responder "precisa do 27.1".
- ⚠️ Diferença da via MCP: `som_em` só em trilhas SEGUIDAS (recusado antes do cartão, com a frase); a tela não diz
  qual monitor o editor tocou por último.
- **Conferido no 2026 real pelas ferramentas:** 4 operações numa chamada (extrair, abrir espaço, inserir V2/A2,
  inserir WAV 5.0 em A3–A5), 0,18 s, **100 de 100 quadros certos NA IMAGEM**, ticks na grade; a cópia que falha é
  apagada e a original volta a ser a ativa.
- ⛔⛔ Dois defeitos achados no caminho: (1) `move` por `Time.seconds` deixava o pedaço movido 1 tick depois do
  quadro — o Premiere mostrava o quadro anterior em TODOS, e a prova (que arredonda) aprovava; agora tempos por
  ticks e a prova confere a grade. (2) **Da F6:** `setInPoint` arredonda na grade do CLIPE — WAV de gravador com TC
  entrava um quadro antes em 3 de 4 trechos só de som (a prova pegava: o `separar_falas` pela ponte falharia em som
  direto real). Conserto: slip no item depois do `overwriteClip` (`cicloAcertarEntrada`) → 20/20.
- ✅ **Pelo chat no 2026** (Sonnet 5.5, `/conversar` com `nle: premiere`, cartões aprovados por `/responder`): o que
  está na tela + a timeline; separar a FALA03 da C04 acrescentando à bin (0,3 s); montar a CHAT CORTE (4/4 no
  quadro, 0,2 s); editar numa cópia (extrair 5 + inserir 10 na V1/A1, 0,1 s); ler a cópia de volta (20+10+25 certo).
  Três consertos que o chat mostrou: (1) `acrescentar_em` lia a bin de falas SÓ pelo MCP — passava no cartão e
  falhava depois do clique; agora pela `premiere.arvore` (escolhe a via). (2) A descrição de `ler_timeline` dizia
  "lê o arquivo da bin, o não salvo não aparece" também no Premiere (falso: lê ao vivo; vinha do 27.1 também).
  (3) O modelo subtraía timecodes como decimais e acusava "10 frames, mas ocupa 15" num clipe certo; a leitura
  traz agora `de_quadro`/`ate_quadro` já contados.
- ✅ **O 2025 (25.6.5) pelas ferramentas**, o mesmo roteiro do 2026: F6 com o WAV 20/20; edição de 4 operações
  0,17 s, **100 de 100 quadros na imagem**, recusas e apagar-a-cópia iguais (a cópia nasce com nome em inglês —
  achada pelo `sequenceID`, não pelo nome).
- ✅ **Pelo chat no 2025** (2026-11-07, Sonnet 5.5, o mesmo condutor do 2026): tela + timeline (8 s); `separar_falas`
  numa bin NOVA `C04 FALAS` a partir do único take (o projeto do 2025 não tinha bin de falas), 2 timelines em 0,4 s;
  `CHAT CORTE` 4 de 4 no quadro; edição na cópia (prova: 2 pedaços intocados) e a leitura de volta 20+10+25. E o
  pedido de corte em J saiu como corte SECO, com o J explicado ao editor (L/J fora de todos os NLEs desde 07/11).
- ⬜ Falta: o Windows 23.x (notebook).
