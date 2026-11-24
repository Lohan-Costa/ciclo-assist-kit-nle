# Consolidado das revisões e dos pentests — setembro de 2026

Um lugar só para o que as quatro análises acharam e em que pé cada achado está. Os detalhes ficam nos
documentos de origem.

| análise | data | escopo | documento |
|---|---|---|---|
| **Pentest 1** | 24/09 | o Magic Link recém-criado (envio pela pasta combinada, Carta 1.1, receptor, token, script do Resolve) e o portão | `docs/seguranca/2026-09-24-vermelho-azul-magic-link.md` |
| **Revisão de código 1** | 28/09 | **só o código da sessão**: o "Atualizar com dois arquivos" (`c751141`) | `.dev/HANDOFF.md` (seção da revisão de 28/09) |
| **Pentest 2** | 29/09 | a superfície nova depois do pentest 1: casca do Resolve, Atualizar, AAF de terceiros, texto no DRT | `docs/seguranca/2026-09-29-vermelho-azul-atualizar-aaf.md` |
| **Revisão ampla** | 30/09 | **o programa inteiro** (motor, serviço, painel, casca, app, atualizador) | `docs/revisao/2026-09-30-revisao-ampla.md` |

**Resumo:** 15 ataques no pentest 1 e 22 no pentest 2, todos barrados (8 + 1 corrigidos no caminho);
10 achados na revisão 1, todos corrigidos; 3 defeitos corrigidos na revisão ampla, mais 1 decisão do
autor, 3 recomendações de segurança e 4 padrões de falha em aberto. Suíte: 44/44 (30/09).

---

## O que as duas revisões de código ensinam juntas

A revisão 1 olhou só o que a sessão escreveu e achou 10 problemas em código de um dia — quase todos
de **estado e ordem** (registro que trava a fila, reenvio que "dá certo" sem gravar, a timeline que o
Comparar trocava, clique duplo, resposta atrasada sobrescrevendo escolha). A revisão ampla olhou o
programa todo e achou outra família: **o que falha calado** (97 `except` que engolem erro), **o que
nenhum teste exercita** (a escrita da bin do editor, o atualizador, a casca de verdade) e **as
diferenças de plataforma** que só aparecem com um Mac na conversa (o `._` do macOS).

As duas se complementam: a revisão focada acha defeito de lógica recente; a ampla acha dívida que
estava lá antes. **Vale repetir a focada a cada função nova e a ampla a cada mudança de máquina ou de
versão de NLE.**

## Estado de cada achado

### Pentest 1 (24/09) — 15/15 barrados
V1 DNS rebinding · V2 `Source Path` UNC no DRT · V3 caminhos plantados nos segmentos · V4 bomba de
aninhamento · V5 300 mil segmentos · V6 pasta inundada · V7 temporário previsível · V8 tipos errados ·
V9 servidor impostor · V10 HTML no rótulo — **corrigidos e travados por teste**
(`tests/test_ataques_magic_link.py`).
**Aceitos:** autenticidade do remetente (assinatura: `pendente`), impostor na 7823 mostra lista falsa
(desafio/resposta: `pendente`), Carta em claro na rede.

### Revisão de código 1 (28/09) — 10/10 corrigidos em 29/09 (`2a0e17b`)
1 fila de registro travava com um pedido recusado · 2 reenvio após reiniciar não gravava a partida ·
3 sugestão pelo id sozinho · 4 Comparar trocava a timeline aberta · 5 reexportação a cada clique e
`recebidos/` sem limpeza · 6 escolha por arquivo perdida · 7 encaixe e plano com regras diferentes de
"devolvido" · 8 corrida na chave do arquivo · 9 campos mexíveis durante a execução, Comparar duplo ·
10 código morto. Mais um achado da própria correção: um `let` lido antes da declaração, que quebraria o
painel do Resolve ao abrir — pegou-o o `test_painel_carrega`, criado para isso.

### Pentest 2 (29/09) — 22/22 barrados (`e9b02eb`)
A1 AAF com 112 localizadores no host do atacante · A2 `trabalho` em caminho de rede (**corrigido**:
`resolve()` consultava o host antes de recusar) · A3 ids forjados · A4 AAF falso ou cortado · A5 web e
rebinding nas rotas novas. Auditados sem teste novo: injeção de XML no DRT, XSS no painel (160
interpolações), a casca.
**Recomendações abertas:** `sandbox` na casca (testar no Resolve 19 e 21) · trava automática contra XSS
novo (junto da reorganização do painel) · teto de tamanho para AAF.
**Aceito:** um AAF de terceiros pode trazer uma montagem falsa (contido pelas trancas e pela conferência
de encaixe).

### Revisão ampla (30/09, `bb0b0cf`)
- **Corrigidos:** F1 a caixa lia o `._` do macOS como Carta · F2 o export pegava o `._x.aaf` · F3 a casca
  pedia a lista da trilha a cada marcador.
- **Decisão do autor — D1:** o relink ainda cai no `ExportFile` quando não acha a bin, contra a regra
  "vetado, não fallback". Herança do RELINKER; não mexido. Tirar leva junto `relink_aaf` (968 linhas).
- **Padrões em aberto:** P1 97 `except` calados · P2 `relink_avb.aplicar` sem teste · P3 atualizador e
  casca real fora dos testes · P4 oito funções com mais de 150 linhas.
- **Menores:** duas listas de extensões de mídia (`aaf/writer` × `matcher`) · a caixa mexe em estado fora
  da trava · imports e variáveis sem uso.

## O que fica para o Mac

Os dois pentests e a revisão ampla rodaram **só no Windows**. No Mac, conferir: o vigia de disco do
pentest 2 (`nt._getfinalpathname` não existe lá; o teste roda sem ele), o `_local` de `file:///Volumes`,
os `._` (F1/F2) com um envio real de verdade, e o `verificar_plataforma.py --so-pendentes`.
