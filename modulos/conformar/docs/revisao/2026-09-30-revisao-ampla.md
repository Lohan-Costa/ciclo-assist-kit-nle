# Revisão ampla do programa — 2026-09-30

Escopo: o De Lá Pra Cá inteiro (motor, serviço, painel, casca do Resolve, app, atualizador), feita de
forma autônoma com o autor ausente. Complementa a revisão do Atualizar (2026-09-28) e o pentest
(`docs/seguranca/2026-09-29-vermelho-azul-atualizar-aaf.md`).

**Método, em três camadas:**
1. varreduras do código todo: `pyflakes`, o `verificar_plataforma.py` do banco, os módulos que nenhum
   teste cita, os `except` que calam erro e as funções mais longas;
2. leitura dos pontos que as varreduras apontaram e dos que mais mudaram;
3. o que é defeito claro e seguro foi corrigido COM teste que o reproduz; o resto está abaixo, para decidir.

**Estado:** suíte 44/44 depois das correções. Nada foi testado no Resolve ou no Avid nesta revisão.

---

## 1. Para o autor decidir

### D1 — O relink ainda cai no `ExportFile` (a regra diz que é caminho vetado)

`api/rotas.py::trabalho_preparar`: quando não acha a bin da timeline (`bin_do_mob`) ou a bin não tem
mobs no disco, o relink EXPORTA um AAF pelo Media Composer (`relink.exportar_aaf` →
`acoes.export_file` → `ExportFile`) e segue pela rota AAF. A regra do autor (memória
`nunca-exportfile-para-extrair-timeline`, ADR 0015) diz: *"tratar `ExportFile` como caminho vetado, não
como fallback"*.

Mas esse caminho é **anterior** à regra: é a rota do RELINKER, documentada no ADR 0013 como "a rota AAF,
que segue inteira e validada em escala". Tirá-la muda o que o editor vê quando a bin não é achada (um
erro claro, em vez de um relink pela rota antiga). **Não foi mexido.**

Se a decisão for tirar: some a rota inteira do AAF exportado — inclusive a maior função do programa,
`motor/aaf/writer.py::relink_aaf` (**968 linhas numa função só**), e o preset de export embarcado.

### D2 — O `sandbox` da casca do Resolve (do pentest)
Uma camada a mais contra XSS futuro; precisa de teste no Resolve 19 e 21.

### D3 — Onde a reorganização do painel entra na fila
É onde duas recomendações se resolvem juntas: a trava automática contra XSS (hoje depende de disciplina
em 160 interpolações do `painel.js`) e a facilidade de mexer no visual que o autor pediu.

---

## 2. Corrigido nesta revisão (com teste)

| # | defeito | onde | teste |
|---|---|---|---|
| F1 | a caixa do Magic Link lia o `._NOME.carta.json` que o macOS grava ao lado de cada arquivo em pasta de rede e exFAT: cada envio de um Mac virava mais um "arquivo ilegível" na caixa do Windows | `sessao_receber._ler_pasta` | `test_receber` (falha sem a correção) |
| F2 | o export pelo Avid escolhe "o arquivo mais recente" da pasta, e o `._x.aaf` do macOS podia ser o escolhido | `avid/acoes.py::export_file` | leitura (o caminho depende do MC) |
| F3 | ao aplicar os Sinais, a casca pedia ao Resolve a lista inteira de itens da trilha A CADA marcador — no passo que o autor já achava lento | `casca/main.js::aplicarAtualizacao` | `test_casca_resolve` 36/36 |

---

## 3. Onde estamos falhando (padrões, não casos isolados)

### P1 — O domínio falha em silêncio, e o código herdado cala erro
**97 `except` que pegam tudo e seguem calados; 88 sem comentário de motivo**, quase todos no código que
veio do RELINKER: `aaf/parser.py` (27), `aaf/writer.py` (15), `avb_export/` (21), `aaf/denest.py` (8),
`aaf/speedcurve.py` (5). É o padrão que produziu o defeito de 29/09: o canal do som dentro de efeitos
sumia sem erro nenhum (34 de 304 planos). A memória do autor já diz: "este domínio falha em silêncio".

**Proposta:** não mexer nos 88 de uma vez. Toda vez que um arquivo desses for tocado, trocar o
`except Exception: pass` por (a) a exceção específica que o pyaaf2/pyavb levantam, ou (b) um contador
que vira aviso no resultado ("N efeitos não lidos"), como a leitura da bin já faz com `avisos`.

### P2 — O caminho que escreve a bin do editor não tem teste
`relink_avb.aplicar` reescreve a `.avb` do editor: é chamado pelo relink, pelo Magic Link, pelo export e
pela coleta do insert, e o banco registra nele o pior acidente já medido (bin corrompida, Media Composer
fechando ao abri-la). Nenhum teste o cita. O `LinkFile` depende do Avid vivo, mas **o resto não**:
achatar, repontar, ajustar visibilidade e gravar ao lado com `os.replace`.

**Proposta:** um teste de integridade sobre a cópia de uma bin real (a `U03 referencia.avb` serve):
achatar + repontar para masters conhecidos + gravar → reabrir com o pyavb → conferir que a timeline
tem os mesmos planos, apontando para os masters novos, e que o UID mudou.

### P3 — Os testes não enxergavam o que o usuário roda
Até 29/09 nenhum teste executava o `painel.js` (o `test_painel_carrega` nasceu ao pegar um erro que
teria quebrado o painel do Resolve ao abrir), e o atualizador deixou o serviço antigo na porta por
causa de barras misturadas — os dois só apareceram nas mãos do autor. O que ainda está nesse ponto
cego:
- o **atualizador** (`atualizar.ps1`/`ATUALIZAR.bat`) — nenhum teste o executa;
- a **casca no Electron de verdade** (o teste usa um Resolve de mentira no Node).

**Proposta:** um teste que rode o trecho do `atualizar.ps1` que acha o serviço antigo contra linhas de
comando reais (as três grafias medidas), e anotar no handoff, a cada mudança na casca, o que só o
autor pode conferir.

### P4 — Funções gigantes onde o risco é maior
8 funções com mais de 150 linhas: `aaf/writer.relink_aaf` (968), `drp/writer._build_drt` (301),
`aaf/parser._parse_sequence` (268), `relink_avb.aplicar` (264), `otio_export/writer.build_otio` (218),
`matcher._match_one` (201), `matcher.match_segments` (182), `frames/extractor.extract_frame` (164). As
quatro primeiras escrevem ou leem timeline — onde um erro é perda de trabalho. Sem pressa de quebrar;
quebrar quando uma mudança de verdade passar por elas.

---

## 4. Menores

- `aaf/writer.py:480` usa `_MEDIA_EXT_RE`, que só existe em `media/matcher.py`; um `in globals()` protege
  e cai numa SEGUNDA lista de extensões escrita à mão. Duas listas que já podem divergir (o `pyflakes`
  aponta como nome indefinido).
- `SessaoReceber.caixa` mexe no índice por id e na lista de cópias fora da trava. Duas procuras ao
  mesmo tempo (o painel bate a cada 4 s; o registro agora procura sozinho) podem perder a lista de
  "cópias duplicadas" de uma Carta, que então não é arquivada. Não quebra nada.
- Código não usado apontado pelo `pyflakes`: 14 imports, 2 variáveis (`aaf/writer.py:879 mobs`,
  `drp/reescrever.py:121 tipo`) e um `global` sem efeito (`avid/mcapi.py:92`).
- O `verificar_plataforma.py` aponta 119 ocorrências "sem sinal de tratamento"; a maior parte é falso
  alarme (`Path(__file__).parent`, textos de documentação). As reais para o Mac eram o F1 e o F2. Rodar
  de novo, com `--so-pendentes`, antes de levar o app ao Mac.

## 5. Conferido e descartado (para não reinvestigar)

- **O serviço roda com o Python do sistema?** Não: no Windows o `python.exe` do venv é um lançador que
  sobe o Python base com a configuração do venv. Por isso aparecem dois processos (e o `atualizar.ps1`
  acha os dois).
- **Um venv por sistema?** Sim: `.venv-win` no Windows, `.venv` no Mac (`dev.sh`, `app/src-tauri/src/lib.rs`).
- **O portão cobre as rotas novas?** Sim, roda antes de qualquer rota (`servidor._atender`); provado
  rota a rota no pentest (A5).
