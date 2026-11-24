# Revisão de segurança — time vermelho × time azul · 2ª rodada · 2026-09-29

Escopo: o que entrou depois da 1ª rodada (`2026-09-24-vermelho-azul-magic-link.md`):

- a casca do Resolve (Electron) e o painel rodando DENTRO dela, com a ponte `window.delapraca`;
- o "Atualizar timeline" (rotas `/receber/partidas|comparar|atualizar|atualizada`, os registros em
  `recebidos/<uuid>.nova.json`, as partidas guardadas, a limpeza de `recebidos/`);
- o "Escolher…" de arquivo do disco (Carta, bin, e o **AAF de terceiros**, `motor/aaf/leitura.py`);
- os Sinais, a trilha de notas e os títulos escritos no DRT.

**Atacante modelado** (o de 24/09, mais um):
- escreve na pasta combinada de rede;
- controla uma página web que o colorista visita, e o DNS dela;
- **manda um AAF ao colorista** (o editor de outra produtora, um e-mail, um HD): o "Atualizar com
  dois arquivos" aceita AAF de quem não tem o De Lá Pra Cá.

**Fora do escopo:** um processo rodando como o usuário (ADR 0007).

**Método:** cada ataque é um teste (`tests/test_ataques_2026_09_29.py`) com um **vigia** que
embrulha `os.stat`, `os.lstat`, `os.scandir`, `os.listdir`, `open` e `nt._getfinalpathname` e registra
qualquer toque num caminho com o host do atacante. No Windows, tocar `\\host\share` já é abrir sessão
SMB e entregar o hash NTLM do usuário. **Resultado: 22/22 barrados** (1 corrigido nesta rodada),
suíte 44/44.

| # | ataque (vermelho) | antes | correção (azul) | onde |
|---|---|---|---|---|
| A1 | **AAF com os 112 localizadores de mídia apontando para o host do atacante**, em 4 grafias (`file:////host/…`, `file://host/…`, `%5C%5Chost…`, `\\host\…` cru), passando por abrir, comparar, achar mídia e importar | ✅ já barrado: o leitor só abre o próprio AAF; o caminho do localizador vira `arquivo_ama`, que só é tocado depois de `caminho_confiavel`; o DRT sai sem o host | — | `aaf/leitura.py`, `caminho_confiavel` |
| A2 | **`trabalho` = `\\host\coleta\<uuid>.drt`** no Comparar/Atualizar | ⛔ o `Path.resolve()` consultava o host (`stat`) ANTES de a comparação com `recebidos/` recusar | o caminho de rede é recusado pela FORMA, antes de qualquer toque | `atualizacao.arquivo_de_trabalho` |
| A3 | ids forjados: `registro=../../token`, `partida=..\..\token`, `avulso=../../../Windows/win.ini`, `envio=../../token` | ✅ já barrado (uuid exato antes de montar caminho) | — | `sessao_receber`, `partidas` |
| A4 | AAF falso (bytes quaisquer) e AAF verdadeiro cortado ao meio | ✅ recusa com motivo, sem 500 | — | `_carta_do_aaf` |
| A5 | página web (cross-site) e DNS rebinding contra as 5 rotas novas; token errado | ✅ barrado pelo portão, que roda antes de qualquer rota | — | `api/portao.py`, `servidor._atender` |

**Conferido sem precisar de teste novo** (lendo o código, com o motivo):
- **Injeção no DRT pelo texto de terceiros** (nome de clipe, comentário, notas, títulos): os nomes
  passam por `_xml_escape`; marcadores, notas e o texto dos títulos entram como blocos binários
  (protobuf em hexadecimal), não como XML. Uma Carta não consegue plantar `MediaFilePath`.
- **XSS no painel** — agora com consequência maior: dentro do Resolve, o painel tem a ponte que
  importa e ATUALIZA timelines. Auditoria de todas as 160 interpolações `${…}` do `painel.js`: todo
  texto de terceiros que vai para HTML passa por `escapar` (que escapa aspas, `test_xss_painel`);
  números vêm do próprio serviço; mensagens usam `textContent`.
- **A casca**: `contextIsolation: true`, `nodeIntegration: false`; a janela não navega para fora do
  serviço (`will-navigate`) nem abre janela nova (`new-window`); a ponte só atende a página servida
  pelo serviço (`doPainel` confere a origem); o DRT que ela importa só pode ser
  `recebidos/<uuid>.drt` (`drtConfiavel`).
- **A lista de mídias que a casca importa** (`<uuid>.midias.json`, com `fs.statSync` no Node, fora do
  vigia do Python): só recebe caminhos que já passaram pela tranca (gerenciada do índice local, AMA
  confirmado por `caminho_confiavel`, ou originais das pastas que o colorista escolheu). O A1 roda o
  import completo sob o vigia.
- **A limpeza de `recebidos/`** apaga só nomes `<uuid>.drt|.midias.json|.nova.json` do próprio serviço.

## Recomendações (não feitas: pedem teste no Resolve ou decisão)

1. **`sandbox: true` na casca.** A ponte só usa `contextBridge` e `ipcRenderer`, que funcionam em
   sandbox; é uma camada a mais se um dia o painel tiver XSS. Precisa ser testado no Electron 8 do
   Resolve 19 (e no 21).
2. **Uma trava automática contra XSS novo.** Hoje a segurança do painel depende de disciplina (todo
   `${…}` com texto de terceiros passar por `escapar`). A reorganização do painel (catálogo de textos,
   um lugar só que monta HTML) é o momento de trocar a disciplina por construção.
3. **AAF gigante trava o serviço enquanto é lido** (`abrir` roda na hora). O arquivo é escolhido pelo
   próprio colorista; aceito como está, mas vale um teto de tamanho com mensagem clara.

## Riscos que ficam (os de 24/09, sem mudança)

- **Autenticidade do remetente** no Magic Link (assinatura com chave da produção: `pendente`).
- **O impostor na porta 7823** pode mostrar uma lista falsa (desafio/resposta: `pendente`).
- **Confidencialidade** da Carta na pasta de rede (como o AAF e o DRT).
- E um novo, no mesmo espírito: **um AAF de terceiros pode empurrar uma montagem falsa**. O dano é
  limitado pelas mesmas trancas (nenhum acesso à rede, nada escrito fora de `recebidos/`) e pela
  conferência de encaixe, que recusa uma versão antiga que não é da timeline de trabalho.

## Lição que vale para a família (registrada no banco)

**`Path.resolve()` / `os.path.realpath` TOCAM o disco.** No Windows, resolver `\\host\share\x` consulta
o host (SMB) — a validação que resolve primeiro e compara depois já vazou o hash NTLM. Recuse o caminho
de rede pela forma (`\`→`/`, começa com `//`) antes de resolver.
