# ADR 0011 — Uma camada de plataforma, e degradação explícita por versão do MC

**Data:** 2026-08-15
**Situação:** aceita
**Contexto:** levar o plugin do macOS (MC 25.12) para o Windows (MC 25.6), que passa a
ser a plataforma principal de instalação.

---

## O problema

O plugin nasceu numa máquina só, e no software de NLE isso esconde uma ambiguidade que
não dá para resolver de dentro: **o que é diferença de sistema operacional e o que é
diferença de versão do editor**. Com uma instalação de referência, as duas se parecem —
e a resposta certa para cada uma é diferente.

A segunda instalação mostrou que três coisas que pareciam *"como o Panel SDK é"* eram
*"como aquela versão naquele SO é"*, e uma delas **corrigiu um fato antes tido por
confirmado** (o menu onde o painel aparece não é do SO; é da versão).

E mostrou o modo de falha que domina o assunto: **o silêncio**. Em quase todas as
armadilhas medidas, o artefato existe, é sintaticamente válido, nada levanta exceção — e
o sintoma aparece longe da causa, culpando o disco ou o editor.

---

## Decisão

### 1. Toda diferença de sistema operacional mora em `plataforma.py`

Um módulo só, no serviço, com a medição ao lado de cada constante: pastas (painéis,
settings do Avid, trabalho), enumeração de processos, assinatura do gateway órfão,
tradução da coluna `Drive` e abertura de URL.

**A alternativa rejeitada** foi espalhar `if sys.platform == "darwin"` pelos módulos —
que é como o código estava. O custo não é a repetição: é que cada sítio vira um lugar
onde alguém pode esquecer o outro SO, sem que nada acuse.

**Corolário: cheque se FUNCIONA, não se EXISTE.** Toda função que resolve caminho
devolve `None` quando o alvo não existe de verdade. Num volume compartilhado entre as
duas máquinas, o artefato do outro sistema *está lá* e está errado — `node_modules`,
`.venv`, um caminho montado com rótulo de volume. Testar presença dá um falso
"tudo pronto" e empurra a falha para longe.

### 2. Todo rpc de conveniência do Panel SDK precisa de um caminho sem ele

O SDK é fechado e a versão do Media Composer não é nossa. `GetListOfWindows` — a
**única** forma conhecida de saber quais bins estão abertas — responde normalmente no
25.12 e devolve `UNIMPLEMENTED` no 25.6.

Isso ganhou exceção **própria** (`McApiNaoImplementado`), separada de "a chamada
falhou", porque a resposta certa é outra: falha é defeito e tem de aparecer; rpc
ausente é uma capacidade a menos, e o app segue sem ela.

⭐ **E a degradação é de TRÊS estados, não dois.** `bins_abertas()` devolve `None` para
*"não dá para saber"*, que é diferente de `[]` para *"nenhuma bin aberta"*. Confundir os
dois **inverte o resultado**: o filtro zera a lista e a seleção volta vazia, como se o
editor não tivesse marcado nada.

**A regra que fica:** o caminho degradado nunca pode ser mais *restritivo* que o
completo. Perde-se a otimização, não a função.

⚠️ **Uma degradação pode acordar um efeito colateral que dormia.** Ao deixar de filtrar,
a varredura passa de "só as abertas" para "todas" — e aí um `OpenBin` que era inofensivo
passaria a cobrir a tela do editor de bins que ninguém pediu. Por isso a rota
`/mc/sequences` degradada **não abre bin nenhuma**: `GetListOfBinItems` numa bin fechada
falha, e falhar é a resposta correta ali.

### 3. Um venv por sistema operacional, e uma implementação por ferramenta

**`.venv` (macOS) e `.venv-win` (Windows), separados.** A tentação era um venv só —
`Scripts/`+`Lib/` conviveriam com `bin/`+`lib/`. **Não convivem:** medido nesta máquina,
`Test-Path .venv\Lib` e `.venv\lib` respondem **ambos `True`** — o Windows é insensível
à caixa mesmo em exFAT, então um venv seria escrito dentro do outro. Some-se que o
`pyvenv.cfg` é um só e aponta para o interpretador de quem rodou `venv` por último.

**`pack` e `reload` viraram Python** (`tools/pack.py`, `tools/reload.py`), com os `.sh`
como atalhos. Um `pack.ps1` seria *quase* igual ao `pack.sh`, e "quase igual" é onde as
duas cópias divergem em silêncio — uma ganha uma correção que a outra não recebe.

`dev.sh` e `dev.ps1` continuam separados, e isso é deliberado: eles não compartilham
lógica, compartilham *roteiro*. O que cada um faz é idiomático do seu shell.

---

## Consequências

**Ganhos**

- O serviço sobe, serve o painel, acha o `Settings.xml` do Avid e instala o `.avpi` no
  Windows, sem elevação. Suíte de regressão: **85/85**.
- Os dois erros mais caros deste eixo estão travados por teste (`tests/test_plataforma.py`),
  e nenhum deles precisa do Media Composer aberto para rodar.
- O plugin deixa de assumir uma versão do MC.

**Custos aceitos**

- **Duas árvores de dependência no disco** (`.venv` + `.venv-win`), ~1 GB somadas.
- **No MC 25.6 o painel abre mais devagar**: sem `GetListOfWindows`, `/mc/sequences`
  pergunta a todas as bins do projeto, a ~500 ms cada. É o preço da resposta verdadeira.
- **A pré-seleção da timeline não aparece** nessa mesma versão — pular a passada de
  seleção é o que impede o custo de dobrar.

**O que fica em aberto**

- `path_to_aaf_url` no Windows é `pendente`: usamos `Path.as_uri()`, que é a forma
  canônica e **não foi medida contra um AAF exportado pelo próprio MC no Windows**. Não
  afeta o relink (lá quem cria o AMA-link é o `LinkFile`), só a rota de autoria.
- **A ponte de eventos (`mcapi` do QWebChannel) sobrevive a navegar para `http://`?**
  É o teste de maior valor pendente do Panel SDK: decide se `BinRowSelectionChanged`
  serve a um painel servido pelo nosso próprio serviço.
- Os módulos dormentes (`motor/frames/`, `motor/avb_export/`) ainda têm `open()` de
  texto sem `encoding=` explícito — no Windows isso vira cp1252 e quebra num caminho
  acentuado. Fora do caminho do relink, mas é dívida conhecida.
