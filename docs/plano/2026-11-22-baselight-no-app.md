# O Baselight no app: o editor envia, o colorista recebe (proposta, 2026-11-22)

**Estado:** proposta, com as decisões do autor de 2026-11-22 e quatro perguntas no fim. Nada de código desta parte ainda.
**Página:** `docs/plano/2026-11-22-baselight-no-app/`, publicada em https://claude.ai/artifact/77EZP3U6VDvfERT2454gqt
**Base medida:** laboratório BL08 (`2026-11-22-lab-casamento-baselight.md`): a entrega (`motor/baselight/entrega.py`), o
xmeml lido do AAF do MC (`do_aaf.py`) e a conferência (`conferencia.py`) já fecham 19 de 19 planos no papel e 18 de 18 com
mídia no render; a janela de conflito existe no religar do app.

## 1. Decisões do autor (2026-11-22)

1. **O editor envia pela aba "Daqui Pra Lá"**: o botão de mandar a timeline para o Baselight fica lá.
2. **O colorista recebe em dois lugares:**
   - **De Lá Pra Cá**: o app reconhece que o programa aberto é o Baselight, como já reconhece Premiere, Resolve e Media
     Composer, e segue o fluxo normal adaptado: conformar, reconectar mídias, conferência visual, notas.
   - **Carta Aberta**: o botão "Importar" (hoje "Importar para o Premiere") se adapta ao Baselight.
3. **A diferença entre os dois:** a Carta não é conform — as mídias apontadas na Carta são as da timeline que chega. O De
   Lá Pra Cá é conform: casa com os originais, confere pela imagem e registra tudo.
4. **Como o Baselight só recebe**, o "Importar" com o Baselight aberto pergunta: **"Importar timeline ou Conformar com De
   Lá Pra Cá?"**. Conformar leva a timeline ao painel De Lá Pra Cá, onde falta o colorista indicar a pasta de mídias e o
   vid ref.
5. **Um job do Baselight por produção.** No Baselight o **job é o projeto** e a **scene é a timeline** (banco,
   `plugins/baselight/README.md`: host → job → pastas → scene). Cada timeline enviada, e cada atualização dela, é uma
   scene dentro do MESMO job da produção — nunca um job por timeline.
6. **Markers** dos planos com problema: um toggle em "opções avançadas". A trilha de notas fica para depois.
7. **O piloto pode abrir e controlar o Baselight** no que precisar.
8. **Atualizar corte** é função importante, do Ciclo Assist inteiro quando conforma, não só do Baselight: manter o trabalho
   da cor e mudar na timeline só o que a montagem mudou (plano entrou, saiu, foi aparado ou trocado).

## 2. O que já existe

| peça | onde | estado |
|---|---|---|
| reconhecer o programa aberto | `cicloassist/servico/rotas.py` `/conexao` | Premiere, MC, Resolve; **Baselight não** |
| Importar da Carta | `cicloassist/painel/carta.js` | só para o Premiere |
| entrega ao Baselight (xmeml com o original certo) | `motor/baselight/entrega.py` | medida no BL08 |
| timeline do MC → xmeml | `motor/baselight/do_aaf.py` | medida no BL08 |
| conferência (arquivo, 1º e último quadro visível) e troca | `motor/baselight/conferencia.py` + `bl-shots -replace` | medida no BL08 |
| markers pela FLAPI | `lab/bancadas/baselight/marcar.py` (laboratório) | provado, fora do app |
| janela de conflito | painel do Conformar, religar | feita em 22/11 |
| motor do "Atualizar timeline" | `motor/atualizar.py` (regras de 27/09) | funciona no Resolve; MC "em breve" |

## 3. O fluxo proposto

**Reconhecer o Baselight.** `/conexao` ganha `baselight`: o processo da interface vivo + a FLAPI respondendo; o detalhe
(versão, job e scene abertos) vem da FLAPI. O topo do app passa a dizer "Baselight 7.0.3 · <job>".

**Colorista, pelo De Lá Pra Cá (conform).** Com o Baselight reconhecido, a aba Importar/relinkar troca o destino:
1. a timeline (AAF do MC, xmeml do Premiere, ou a Carta) + a pasta de mídias + o vid ref;
2. casar com os originais (as regras de 22/11), com a janela de conflito abrindo se houver empate;
3. a entrega: o xmeml com o original de cada plano, a taxa e o TC certos (a ponte pelo original);
4. `bl-conform` numa scene nova do **job da produção**;
5. a conferência: arquivo e 1º/último quadro visível de cada plano; o que o Baselight trocou por conta própria é corrigido
   (`bl-shots -replace`), o que não se corrige vira marker (com o toggle ligado) e aparece na lista do app;
6. o resumo no painel: certos, corrigidos, offline com motivo.

**Colorista, pela Carta Aberta.** "Importar" com o Baselight aberto pergunta "Importar timeline ou Conformar com De Lá Pra
Cá?". Importar = a timeline vai como está, com as mídias da Carta (sem casar). Conformar = abre o De Lá Pra Cá com a
timeline carregada.

**Editor, pela aba Daqui Pra Lá.** "Enviar para o Baselight": prepara a timeline aberta para a cor (ver pergunta 1).

**Atualizar corte (depois do fluxo acima).** O motor que compara já existe (`motor/atualizar.py`): compara a Carta de
partida com a nova, nunca com a timeline do colorista; casa planos pelo conteúdo, não pela posição; take trocado = plano
novo. Falta a EXECUÇÃO no Baselight: aplicar só a diferença na scene que já tem cor (inserir o novo, tirar o retirado,
aparar). A medir no Baselight antes de desenhar: o que a FLAPI e o `bl-shots` permitem fazer numa scene existente sem
reconformar.

## 4. Etapas

1. Reconhecer o Baselight (`/conexao` + topo do app).
2. De Lá Pra Cá com o Baselight: a entrega + conferência ligadas ao painel; o job da produção; o toggle de markers.
3. Carta Aberta: o "Importar" com a pergunta.
4. Daqui Pra Lá: "Enviar para o Baselight".
5. Atualizar corte: medir no Baselight o que dá para mudar numa scene com cor; depois a proposta da execução.

Cada etapa fecha com o laboratório BL08 (papel + render) e, a partir da 2, com o PRODUCAO-C.

## 5. Respostas do autor (2026-11-22, noite)

1. **O editor envia pela Carta Aberta**, por enquanto. Um "collect media" no Daqui Pra Lá pode vir depois.
2. **A produção (e o job):** no Daqui Pra Lá, um campo OPCIONAL com o nome da produção — herdado do nome do projeto aberto
   ou indicado pelo editor que envia. Com o Baselight aberto e o colorista importando, o Ciclo confere se a produção é a
   mesma do job aberto: sendo, já importa; não sendo, pergunta **"importar no job aberto ou criar um novo?"**, com uma
   opção pequena **"não perguntar novamente"**. Criar um novo pede um nome ou a escolha de um job que já existe. Num fluxo
   automatizado (a IA operando), **o nome do job vai no prompt gerado**, para a IA saber o que fazer.
3. **Nunca sobrescrever, e sem "V02":** a versão confundiria com uma versão real da montagem. O nome da scene leva
   **"import 02"**, que diz que é uma nova importação, não uma versão intencional (`C07 v2 · import 02`).
4. **O atualizar corte começa pelo Baselight** (o tempo é limitado). Primeiro um **projeto sintético** no laboratório, com
   controle total, simulando os cenários — por exemplo: a edição entrega uma timeline bagunçada, o colorista arruma, e a
   atualização chega: como saber o que manter e o que mudar.

### 5.1 Os cenários do laboratório do atualizar corte (rascunho, a propor)

Uma montagem sintética v1 → conform no Baselight → "trabalho do colorista" simulado na scene (cor por plano, marcada no
quadro para a leitura do render) → a montagem v2 com UMA mudança de cada tipo, isolada e depois combinada:
- plano novo no meio; plano retirado; plano aparado (cabeça e cauda); plano trocado por outro take; plano movido de lugar;
- planos que só andaram porque algo entrou antes (não mudaram);
- **a timeline bagunçada arrumada pelo colorista**: a edição entrega trilhas sobrepostas, planos invisíveis e cortes
  desnecessários no mesmo take; o colorista achata e junta na scene; a v2 da montagem mexe num plano que o colorista juntou.
  A regra a medir: a comparação é contra a Carta de partida (nunca contra a scene do colorista), e a execução aplica a
  diferença sobre o que o colorista fez;
- e o render que a cor devolveu à montagem voltando dentro da v2 (sai da conta pelo reel + TC).
A medida: o que a cor da v1 preservou, plano a plano, no render da scene atualizada.

## 6. Andamento

- ✅ **Etapa 1 (22/11 noite): o app reconhece o Baselight.** `cicloassist/baselight.py` (aberto = o processo da
  INTERFACE; os serviços ficam no ar com ela fechada; no Windows não há Baselight), `/conexao` com `baselight` e a versão,
  o topo do app ("Baselight 7.0" junto dos outros) e a Carta Aberta o vê (o Importar ainda diz que não existe para ele —
  etapa 3). Provado ao vivo: aberto → `True, 7.0.3`; fechado → `False`; nenhuma falha do sistema. Suíte 2059.
  ⬜ O job e a scene abertos no detalhe (pela FLAPI, na etapa 2).
- ✅ **Etapa 2 (22/11 noite): o De Lá Pra Cá conforma no Baselight.** Com o Baselight aberto o painel vira o do
  colorista (`?nle=baselight`, o `/conexao` do Conformar o reconhece por último, depois dos NLEs de montagem); o mesmo
  Importar de sempre (o `.prproj` com a análise proxy → original, ou o AAF/bin/Carta com o relink por master) e, no fim,
  `destino: "baselight"` → `servico/baselight_conform.py` → `motor/baselight/enviar.py`: o xmeml (do Premiere pela
  leitura, `baselight/do_prproj.py`; do MC pelo `do_aaf`), a entrega com o original decidido, o `bl-conform` numa scene
  NOVA do job (`nome_livre`: "… · import 02"), a conferência, o `bl-shots -replace` e os markers (`marcar_flapi.py`).
  Nas opções avançadas: o **job da produção** (a lista dos jobs do Baselight; vazio = o último usado; um nome novo cria o
  job) e o toggle **"Marcar os planos com problema"**. O resumo diz certos, corrigidos e a conferir, plano a plano.
  Medido no BL08 pelo serviço (as rotas do painel): Premiere **19 ok + 1 offline de propósito (P10)**, 2 corrigidos, 6 s;
  MC **18 ok + 1 fora do ponto (P10, o +7 já conhecido)**; a 2ª importação virou "· import 02". Achado: sem `<duration>`
  a sequência DPX entra parada — a entrega o cria (banco). Testes `modulos/conformar/tests/test_baselight_enviar.py`;
  suíte do Conformar 130/131 arquivos (o `test_aaf_leitura` já falhava antes), a do Assist 2059.
  ⬜ Falta: a pergunta "importar no job aberto ou criar um novo?" (o job ABERTO na interface ainda não é lido — a FLAPI
  não foi medida para isso; hoje o colorista escolhe na lista); o painel visto com os olhos (o Chrome não estava ligado:
  conferido por rota e `node --check`); o vid ref ainda não entra na conferência do Baselight; o PRODC por este caminho.
- ✅ **Etapa 3 (22/11 noite): a Carta Aberta e o Baselight.** Com o Baselight conectado o botão vira "Importar para o
  Baselight" e pergunta (`cicloassist/painel/carta.js`, `perguntarBaselight`): **Importar timeline** (o xmeml da Carta,
  `entrega_premiere.xml_da_timeline`, com cada arquivo descrito como É — `baselight.enviar.decisao_como_esta` — conform,
  conferência e markers no processo do Assist: `cicloassist/carta/entrega_baselight.py`, rota `/carta/baselight/importar`)
  ou **Conformar com De Lá Pra Cá** (o xmeml + o pedido em `<CicloAssist>/conformar/a-conformar.json`; o app reinvocado
  com `--conformar` traz a aba à frente; o painel do Conformar pega o pedido uma vez — `/receber/a-conformar` — e abre a
  timeline; `.xml` é o tipo `xmeml`, lido por `motor/baselight/xmeml.py` e casado pelo casador do Premiere; só o destino
  Baselight o monta). O job: o nome do projeto da Carta (a produção) ou um da lista dos jobs.
  Medido no BL08: Importar **20/20** (2 corrigidos); Conformar **19 ok + 1 offline (P10)**, 2 corrigidos. Fotos e diário:
  `MIDIAS DE TESTES/9 SAIDAS DOS APPS/_BASELIGHT/estudo/fotos/app-integracao/` (para o relatório final, pedido do autor).
  Testes `modulos/conformar/tests/test_baselight_carta.py`; suítes 131/132 arquivos (a antiga) e 2059.
  ⬜ Não provado: a Carta com uma timeline do BL08 de verdade (entrar na Carta pede o MC aberto) e o `--conformar` na
  janela do app (compila; não foi aberto). ⬜ A pergunta "job aberto ou novo?" segue pela lista (sem ler o job aberto).
- ✅ **Etapa 4 (22/11 noite): a produção e o job.** Pelas respostas do autor (§5.1–2: o editor envia pela Carta; o
  "collect media" fica para depois). **Daqui Pra Lá:** campo opcional **Produção** (vazio = o nome do projeto aberto),
  gravado na Carta como `producao` (`carta_aberta/writer.py`; leitor 1.x ignora) e lido do outro lado
  (`sessao_receber.py`) como o job sugerido. **O job aberto:** `motor/baselight/enviar.py` `job_aberto()` pelo lock da
  scene no `bl-lsscenes -k` (a FLAPI de fora não sabe; banco `plugins/baselight/README.md`); `/baselight/jobs` devolve
  `aberto`. **A pergunta** (painel do Conformar e Carta Aberta): produção = job aberto → importa direto; diferente →
  "No job aberto" ou "Em '<produção>'" (novo, criado), com "Não perguntar novamente". **Fluxo automatizado:** a
  ferramenta `conformar_no_baselight` (`cicloassist/mcp/ferramentas/conformar.py`) tem `job` OBRIGATÓRIO e a descrição
  manda não perguntar o job no meio do fluxo (o nome vai no prompt). Medido no BL08: "No job aberto" → "BL08 CASAMENTO ·
  import 04" em LAB_BASELIGHT, 19 ok + 1 offline (P10), 2 corrigidos. Fotos e4-01..03. Testes em
  `modulos/conformar/tests/test_baselight_carta.py` (o lock, a galeria pulada, a produção na Carta).
  ⬜ Não provado: a ferramenta `conformar_no_baselight` chamada pelo CHAT; a Carta com produção vinda de um export real
  do MC (o MC não estava aberto).
- ✅ **Etapa 5, a medição (22/11 noite): atualizar corte no Baselight — laboratório BL09.** Bancada
  `laboratorio-de-midia/lab/bancadas/baselight/atualizar_corte.py` (v1 com a cor identificável por CDL; v2 com plano
  novo, movido, aparado, estendido, take trocado, retirado). Placar (FLAPI, 7.0.3): **Multi-Paste arquivo + TC 7/7** e
  **cópia plano a plano pelo BLG 7/7** (scene nova, a do colorista intacta); só pelo nome 5/7 com 2 erros calados;
  `--CopyGrades` 7/7 só por cima de uma CÓPIA da v1 (a v1 fica numa trilha, o rabo dela entra no render, o marker sai do
  lugar); a FLAPI não APARA (editar no lugar está fora). ⚠️ Plano que o colorista DIVIDIU: nenhuma via acerta sozinha.
  Banco `plugins/baselight/README.md` (seção BL09). Proposta da execução e três decisões pendentes (o plano dividido, os
  markers do colorista, quem aplica a cor): https://claude.ai/artifact/C3fHr38DkAKLSMV4u3gi3x
  (`docs/plano/2026-11-22-atualizar-corte-baselight/`). Fotos e5-00..02.
- ✅ **Etapa 5, a execução (22/11 noite): as três recomendações aprovadas pelo autor ("ok para as 3").**
  `motor/baselight/atualizar.py` (puro: a impressão da cor pelo BLG sem a camada 0; os cortes do colorista = fonte
  emendada com cores diferentes; `dividir_xmeml` corta a v2 no mesmo quadro de fonte ANTES do conform; `mapear` pelo
  arquivo inteiro e trecho em comum; `mover_marcas` pela fonte) + `cor_flapi.py` (no python da FilmLight: Multi-Paste
  arquivo + TC → a conferência do Ciclo → `delete_all_layers` + `apply_blg_payload` no que discordar → os markers do
  colorista) + `enviar.enviar(..., atualizar=<scene do colorista>)` (os três caminhos: xmeml, prproj, AAF/bin/Carta).
  Painel: Opções avançadas › no Baselight › **Levar a cor de uma scene** (rota `/baselight/scenes?job=`); o resumo diz
  o que veio do colorista. Chat: `conformar_no_baselight(atualizar=…)`. Medido no BL09: pelo motor e pelo painel, **8 de 8**
  (o S4 dividido virou dois planos com S4 e S4b; marker 300 → 96; um perdido, dito); Multi-Paste errado de propósito
  → a conferência corrigiu 2 (7/7). Testes `modulos/conformar/tests/test_baselight_atualizar.py`; suítes 132/133 (a
  antiga) e 2059. ✅ **A scene do colorista ABERTA na interface** (pilotado, 22/11): aberta para edição e salva → 8/8, a
  dela intacta; com mudança NÃO SALVA → o Baselight recusa a leitura de fora, e o Ciclo para ANTES de criar a scene, com
  "peça ao colorista para salvar (⌘S)" (`enviar.ColoristaNaoSalvou`); salvou → 8/8. O "job aberto" com várias scenes
  abertas passa a preferir a de escrita (`enviar.job_aberto`). ✅ **Pelo CHAT** (22/11): arrastar a v2 + os originais e
  pedir "leva para o Baselight… trazendo a cor da scene BL09 V1 dividida" → o cartão com `atualizar` → "Pode fazer" →
  "BL09 V2 · import 06", 8 de 8 (conferido por fora). O cartão do chat ganhou o resultado do Baselight (era "undefined
  cortes"). ⚠️ Conversa retomada repetiu a conclusão velha do modelo (`docs/conhecimento/conversa-visita-e-custo.md`). ⬜
  ✅ **Cor animada e "look" sobre vários planos** (pilotado, 22/11; scene "BL09 V1 look"): o Multi-Paste desloca os
  keyframes pela fonte (S4 aparado: 7/41 → −5/29); a cópia pelo BLG não deslocava → `atualizar.deslocar_keyframes` +
  a conferência compara também o TEMPO dos keyframes (Multi-Paste que não cola nada → a cópia do Ciclo fez 7/7 com −5/29).
  O look (faixa juntada sobre S2+S3) vai por plano: chegou ao S2; o take trocado dentro dele não recebe nada.
  ✅ **Decisão do autor (22/11): o look vai ao plano novo e ao take trocado.** O look = a mesma camada em planos VIZINHOS
  da scene do colorista (`looks_da_scene`); vai ao plano sem cor que SUBSTITUI um plano com o look ou cai entre dois com
  ele (`look_para`); só essa camada (`so_camadas`), conferida pela leitura das camadas; se não entrar, fica sem cor e é
  dito. Marker "[Ciclo] só o look da cena… a cor do plano é do colorista". BL09: take trocado (7/7) e plano novo entre
  S2 e S3 (V2B, 5/5); sem look ("dividida") continua 8/8. ⛔ Achado no caminho: o `bl-conform` numa timeline curta casava
  pela GRAVAÇÃO (5/5 fora do ponto) → `--TimeType Source` fixo em `enviar.conformar`.
  ✅ **O caso real: PRODUCAO-A** (22/11): PRODA_CORTE.02 (a CR03T3, colorida: CDL por plano, look em 3 vizinhos, cor
  animada) → o corte final "PARA COR" de 19/12/2023 (o AAF real, pelo `_entregar` do produto; o relink emulado pelo nome
  do clipe), job "PRODUCAO-A": **99 planos em 12 s, conform 99/99, cor 99/99** (97 Multi-Paste + 2 corrigidos), o
  look nos 3 planos, os keyframes no lugar — conferido por fora com os valores lidos dos dois lados. ⛔ Achado: o
  Multi-Paste com `MaintainTracks=1` não colava NADA na scene do AAF (dizia que colou) → `MaintainTracks=0`. ⚠️ Os 6
  segmentos sem BRAW aqui (títulos, contagem, claquete, 2 drones DJI) ficaram fora do xmeml na emulação; pelo painel
  (relink) os sem original entram offline com marker. Fotos e5-14/15. a Carta
  "Importar timeline" sem a opção; a camada 0 (reposicionamento do colorista) não vai pelo Multi-Paste `StackOnly`.
- ✅ **Etapa 5, o laboratório do que faltava (22/11, noite 8): BL09 parte 2** (bancada `laboratorio-de-midia/lab/bancadas/
  baselight/atualizar_corte_2.py`, banco `plugins/baselight/README.md` seção BL09). Placar pelo produto (`enviar`/
  `entregar_xmeml`, conferido por fora):
  - **Grupos:** o produto PERDIA todos, calado (`PasteGroups=0`); o Multi-Paste com `PasteGroups=1` tira o take trocado do
    grupo. ⇒ os grupos refeitos pelo casamento do Ciclo (`atualizar.levar_grupos`), relidos; o que ficou de fora vai ao
    resumo (painel e chat). BL09: 3 grupos conferidos, o S5 retirado e o S3 trocado ditos. ✅ Decisão do autor (23/11):
    o take trocado / o plano novo entram no grupo como no look (`vizinhos_e_substituidos`): BL09, o C001C004 no "SALA",
    com marker.
  - **Várias trilhas** (plano escondido, inserto sobre meio plano, corte à toa no mesmo take; o colorista achatou e
    juntou; a v2 apara o plano juntado): ⛔ DEFEITO do conform (não só do atualizar): a conferência esperava o plano
    escondido, casava pelo quadro de início com o de cima e o `bl-shots -replace` TROCAVA a imagem do plano visível.
    Consertado (`entrega.esperado` sem o coberto inteiro; `conferencia.conferir` por arquivo/fim no mesmo início): 9/9
    conform e 9/9 cor.
  - **O render da cor voltando:** o render do Baselight traz o TC de fonte e o reel do original; entrava OFFLINE. O casador
    reconhece o TRECHO (`prproj/originais._trecho`) e a entrega desloca o ponto (`entrega._deslocar_trechos`) + marker
    "[Ciclo] um trecho do original…": 7/7, a cor do colorista no original. ✅ **Pelo MC (23/11)**: a v2 montada no MC 25.12
    e o AAF dele (bancada `mc_render.py`); o casador dos masters (`media/matcher_masters`) aceita o trecho pelo reel do
    arquivo (0,85, topo da revisão). ⛔ Erro calado achado e consertado: o `montar_midia` trocava o daily pelo original
    sem deslocar o In (entrou 4–43 em vez de 64–103 e a conferência aprovou) — agora `avb_bin.segmentos._deslocar_trecho`,
    que vale também para o DRT; e o `existe_aqui` do `_montar` tenta o `/Volumes` do AAF do Mac. 7/7, marker no 96.
    ✅ **Outra taxa (23/11)**: o render de um plano de 29,97 DF / 59,94 sai em 23,976 com o TC de fonte no contador CRU do
    `tmcd` na base do original (o ffprobe o perde); `originais.tmcd_cru` + `_trecho` em tempo: 3/3 no quadro de fonte
    (bancada `outra_taxa.py`).
    ✅ **Premiere → Resolve (23/11)**: o `prproj_para_drt` deslocava nada (erro calado, como no MC) → `_deslocar_trecho` +
    marker; empate do trecho em cópias idênticas resolvido; o In com FRAÇÃO no DRT (o Resolve arredondava para baixo na
    fonte de outra taxa) e `writer.ler_in` nos leitores. 4/4 pela imagem (bancada `premiere_outra_taxa.py`).
  - **Reposicionamento** = camada Transform: já ia (7/7). **Camada 0** (espaço de entrada, decode do RAW): SE PERDIA,
    calado → Multi-Paste `LayerZeroAndStack` + a conferência da camada 0 DEPOIS da correção pelo BLG (que mexe no decode).
    BL09 7/7 (pelo Multi-Paste e só pela conferência); PRODUCAO-A com o decode do BRAW mudado em 2 planos: 99/99.
  - Os seis cenários de antes, de novo, depois das mudanças: 7/7, 7/7, 9/9, 8/8, 7/7, 7/7. Suítes: Conformar 132/133
    arquivos (a antiga), Ciclo Assist 2059.
