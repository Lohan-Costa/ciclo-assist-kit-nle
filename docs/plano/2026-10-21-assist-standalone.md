# O Ciclo Assist como guarda-chuva de apps — o mapa (autor, 2026-10-21)

> **Só mapa.** Escrito no fim de sessão para a próxima começar daqui; nada foi construído.
> Desenho da família (uma janela, os NLEs por fora): banco `transversal/app-unico-fora-do-nle.md`.
> O passo imediato (a janela para a demo de sexta) está em [2026-10-18-app-sem-painel.md](2026-10-18-app-sem-painel.md).

## O desenho, nas palavras do autor (confirmado em 2026-10-21)

O Ciclo Assist (ou **Assist anterior**, se a versão seguir pelo festival The Brain) é um **guarda-chuva** de quatro
abas, e **cada aba é um app dedicado**:

| aba | módulo | de onde vem |
|---|---|---|
| **Assistir** | o chat com o agente (Claude ou Ollama) | **o único módulo exclusivo do Assist** |
| **Preparar** | Órbita | cópia IMPORTADA do Órbita standalone (`2 ATIVOS/DRAMASYNC`) |
| **Conformar** | De Lá Pra Cá | cópia IMPORTADA do DLPC standalone (`2 ATIVOS/_DeLaPraCa`) |
| **Entregar** | Promo Entrega | o mesmo modelo, quando ele estiver pronto (`2 ATIVOS/Promo Entrega`) |

- **O standalone é a oficina.** Melhoria, correção e função nova se fazem LÁ. Terminado o trabalho, o Assist é
  atualizado para pegar as mudanças — a cópia de dentro **não é desenvolvida**.
- **Todo standalone tem uma porta aberta para ser controlado por um agente de IA** que o usuário quiser. Dentro do
  guarda-chuva, o agente já está a uma aba de distância: é o Assistir, pela mesma porta.
- **O Assist não conversa com os apps standalone**: ele já tem cada um dentro dele.
- ⭐ **Human first.** Os apps são ferramentas para o profissional trabalhar melhor, sem tirar o controle da mão dele.
  O agente é como a skill do piloto: opera o software para executar uma função específica quando pedem.

### ⚠️ O que este desenho corrige

- A primeira versão deste mapa (mesmo dia) tratava os núcleos como apps vivos chamados por HTTP (porta, token, "o
  Órbita está fechado"). **Errado.** A `sincronizar_com_o_orbita` de hoje (HTTP para o Órbita standalone, 7817) é
  TRANSIÇÃO; a final fala com o Órbita de dentro.
- A fatia vertical (`2026-09-10-fatia-vertical.md`, l. 8 e 784) dizia *"nada de aba Preparar, Conformar ou
  Entregar… a resposta é outro plugin"*. O autor revê isso: o guarda-chuva volta, mas com a regra que faltou ao
  `_ASSIST ANTERIOR` — **o desenvolvimento de cada módulo mora no standalone dele**, e o guarda-chuva só importa.

## ⭐⭐ A fase de UNIFICAÇÃO de tecnologia (decisão do autor, 2026-10-21)

*"Teremos que unificar as tecnologias onde puder. Originalmente cada app foi criado sem pensar que um dia seriam
compartilhados num mesmo guarda-chuva… é um momento importante de analisar a melhor prática, e caso haja uma mudança
de caminho, dedicar algumas sessões para a fase de adaptação."*

**Ela vem ANTES de importar qualquer módulo.** Importar quatro pilhas diferentes num app só congelaria a diferença.

### O que se sabe hoje de cada pilha (conferir na análise; ⬜ = não olhado)

| | janela | servidor | lógica | interface | NLE |
|---|---|---|---|---|---|
| **Órbita** | Tauri 2 | Rust, `tiny_http` (**uma thread**), 7817 | Rust + sidecar Python (`src-python/`) | React (Studio) + página do painel servida | MC 9100; Premiere ponte invisível; Resolve (Lua → por fora) |
| **De Lá Pra Cá** | Tauri 2 (`app/src-tauri`: sobe o serviço, pino, alargar, `arrasto_win.rs`) | Python, 7823 | Python (`servico/`) | HTML/JS servido | MC 9100; Premiere ponte invisível; Resolve externo |
| **Ciclo Assist** | ❌ nenhuma (painel servido) | Python stdlib `ThreadingHTTPServer`, 7824 | Python (`cicloassist/`) | HTML/JS servido (`painel/`) | MC 9100; Premiere CEP com interface |
| **Promo Entrega** | ⬜ (há uma pasta `janela/`) | Python, 7829 | Python | ⬜ painel `.avpi` | MC 9100 (MC 25.6) |

Primeira leitura (hipótese, não decisão): **Python é o chão comum dos quatro**, e Tauri + página servida é o desenho
que dois já seguem. O ponto fora da curva é o Órbita, com lógica e servidor em Rust e a interface em React.

### O que a análise precisa responder

1. **A forma de um módulo.** O que é "o Órbita" que se importa: um pacote Python + as telas + as ferramentas do
   agente? Como os quatro convivem num processo (ou não) sem colidir — portas, pasta de dados, logs, o `mcapi`.
2. **As peças que cada app escreveu de novo e que viram UMA no guarda-chuva:** a casca Tauri, o arrasto nativo, o
   `mcapi.py` (o `_ASSIST ANTERIOR` já mediu em 2026-08-24: `portao`/`servidor`/`plataforma` quase idênticos, `mcapi`
   divergente — Promo Entrega superconjunto), a ponte invisível do Premiere, o Resolve externo, o cache de mídia.
3. **A porta do agente.** O mesmo contrato no standalone (agente de fora) e dentro do guarda-chuva (o Assistir):
   provavelmente o registro MCP do Assist (`mcp/registro.py`, `escreve=` → portão) generalizado. ⛔ O que o Assist já
   pagou para aprender vale para todos: portão sem prazo (ADR 0008), `--restricted` + `--tools ""`, o que a
   ferramenta devolve tem teto, leitura só do que o editor arrastou (ADR 0005).
4. **Como importar e reimportar.** Vendorizar uma versão do standalone (o Assist anterior já faz isso com o
   `cicloassist/` — ver a memória `assist-anterior-revisa-o-motor`), submódulo, ou pacote versionado. O critério: o
   standalone segue testável sozinho, e o guarda-chuva sabe que versão de cada módulo carrega.
5. **O custo de cada mudança de caminho**, em sessões — o autor aceita dedicar algumas à adaptação, mas quer ver o
   preço antes. ⛔ Regras da casa que entram na conta: Python stdlib para HTTP (framework só com ADR), nada de torch,
   ASCII puro nos `requirements`.

**Entrega da análise:** um ADR da família (no banco, `transversal/`, porque vale para os quatro repos) com a pilha
escolhida e o que muda em cada app, e um organograma (fluxo + telas numa página) para o autor aprovar — regra da família.

## ✅ O guarda-chuva COMPOSTO (2026-10-21, noite — decisão do autor: compor agora, importar na unificação)

`ABRIR-APP.bat` abre UMA janela com as quatro abas, cada uma uma webview filha (`Window::add_child`, feature
`unstable` do Tauri 2.11) com a página do painel do módulo, servida pelo motor dele e subida da pasta do app:

| aba | motor (porta) | subido como | a página |
|---|---|---|---|
| Preparar | Órbita (7817) | `orbita.exe --motor` (o build de desenvolvimento, `%LOCALAPPDATA%\orbita-target`) | `/avid/panel?casca=app` |
| Assistir | Assist (7824) | `python -m cicloassist.servico --app --pai` | `/painel?casca=app` |
| Conformar | De Lá Pra Cá (7823) | `python main.py --app --pai` (venv do DLPC) | `/painel?nle=mc&casca=app` |
| Entregar | — | — | "em breve" (local) |

- Trocar de aba esconde/mostra webviews: nada recarrega. A barra (`ui/abas.html`) é a ÚNICA página com IPC.
- O arrasto nativo vai à webview da aba VISÍVEL, na função que o módulo já tem (`orbitaArrasto`, `cicloArrasto`,
  `delapracaArrasto`), com o y descontado da barra. **Pilotado:** pasta D02 do Premiere → aba Preparar → CAM A (26) +
  SOM DIRETO (24).
- Os recados dos motores chegam pelo `single_instance`: `--fixar`/`--soltar` (Assist), `--fixar-mc`/`--soltar-mc`,
  `--janela-larga`/`--janela-painel` (DLPC, a revisão), `--encerrar`. Motor que já estava de pé (app standalone,
  bancada) é usado como está e não é encerrado.
- Medido: os três motores atendem em 7–8 s; o Órbita sobe sem janela.
- ⬜ Não exercitado: um sync completo e um relink dentro do guarda-chuva; o Studio do Órbita (abre na janela dele);
  o De Lá Pra Cá com o MC (só visto conectado ao Premiere).

### ✅ A moldura única (2026-10-21, pedido do autor)

Topo do guarda-chuva = o estado da conexão com o NLE (a `/conexao` do Assist, com versão e projeto) e o pino; as abas
sem marcador e a engrenagem ÚNICA à direita delas; rodapé ÚNICO com a assinatura e a versão. Cada app, com
`?embutido=1`, esconde a própria moldura e expõe `cicloEmbutido.configuracoes()` (Assist `2f85662`, Órbita
`f565e04`, De Lá Pra Cá `479483a`). ⚠️ O texto dos Ajustes do De Lá Pra Cá ainda fala da janela de Configurações
do app dele, e o do Órbita diz "Finder" no Windows — são dos apps, para corrigir lá.

## As fases

| fase | o quê | onde se trabalha |
|---|---|---|
| **F0** | o Assistir numa janela (demo de sexta, 23/10; depois do Órbita) — `2026-10-18-app-sem-painel.md` | aqui |
| **F1** | a análise de unificação → ADR + organograma | banco + os quatro repos (leitura) |
| **F2** | a adaptação: cada standalone migra para a pilha comum e ganha a porta do agente | nos standalones |
| **F3** | o guarda-chuva: as abas, a importação, o Assistir controlando cada módulo | aqui |
| **F4** | Resolve e Mac (a casca e o arrasto nativo estão `pendente` na família inteira) | todos |

⚠️ **F0 é provisória por natureza:** ela usa a casca do De Lá Pra Cá antes de a F1 decidir a pilha. Não investir
nela além do que a demo pede.

### O que a janela da F0 quebra aqui (conferir no código antes de afirmar)

- `servico/presenca.py` conta a VISITA pelo silêncio do painel — na janela, fechar o painel e fechar o app viram o
  mesmo gesto;
- o `nle` que a página declara em toda pergunta: hoje ela SABE onde está (`__adobe_cep__` ou Avid); na janela não
  está em NLE nenhum (o `/conexao` do Órbita resolve isso);
- o layout pensado para 400 px numa janela que alarga;
- `Sec-Fetch-Site: same-origin` deve continuar valendo (a casca navega para a página do próprio serviço) — medir.

## Decisões abertas do autor

1. **Nome do guarda-chuva**: Ciclo Assist ou Assist anterior (depende do festival The Brain). O `CATALOGO.md` e o
   `CLAUDE.md` ainda dizem "plugin do Media Composer"; renomear pasta é com o zelador.
2. **O motor Ollama sai de avaliação?** (M2, 2026-09-16; limites medidos no `CLAUDE.md`.)
3. **O Promo Entrega entra quando?** Ele ainda é painel `.avpi` no MC e está parado desde 2026-09-07.

## Por onde a próxima sessão começa

1. Demo de sexta ainda pela frente: **F0**, e só depois do Órbita fechar o MC dele.
2. Depois da demo: **F1** — ler os quatro repos e montar a tabela de pilhas de verdade (os ⬜ acima), antes de opinar.

## 2026-10-29 — o De Lá Pra Cá virou ferramenta do chat: `conformar_no_resolve` (`79b3f24`)

Decisão do autor: *"o DLPC precisa operar exatamente como o Órbita; o Ciclo Assist deve saber que ele tem as
ferramentas à disposição e que é para usá-las"*. Cliente `cicloassist/delapraca.py` (a sequência da bancada
`_DeLaPraCa/tools/bancada_resolve/e2e_prproj.py`, pelo serviço 7823), ferramenta `mcp/ferramentas/conformar.py`. Quem
diz o que é cada arrasto é o código (extensão → timeline, vídeo → referência, pasta → mídias); sem nome, a sequência de
mais planos. O preâmbulo do arrasto aponta a ferramenta quando chega um `.prproj`/`.aaf`/`.avb`.

**Rodada pilotada do zero** (nenhum app aberto, 18h28): Resolve Studio 19 → projeto novo `PRODC ASSIST 29-10` → janela do
Assist → arrastar `WSP-DLPC_2.prproj` + `PRODC_Trailer_v02.mov` (Desktop) e a pasta `R04 …\ISOLADO\MIDIA` → "Leve este
projeto para o Resolve." (Sonnet 5.5, automático).

| | tempo |
|---|---|
| abrir o Resolve e criar o projeto | 56 s |
| abrir a janela do Assist | ~30 s |
| os três arrastos (piloto, com um gesto errado) | ~1 min 20 s |
| **o turno** (envio → resposta) | **1 min 57 s** — DLPC 109 s: analisar 1,9 · preparar 13,4 · mídias 0,8 · importar 2,5 · Fusion/LUTs/compostos 2,1 · **conferência 88,2** |
| total | **~5 min 07 s** |

Modelo: **2 chamadas, 762 de saída, 17,5 mil cache escrito / 16,3 mil lido, US$ 0,08** de tabela; a ferramenta devolveu
2,3 mil caracteres. Resultado: `PRODC_CORTE02` no Resolve, 80 planos, 48 arquivos, nada faltando, 11 Fusion, 75 LUTs,
8 compostos, 17 marcadores; **conferência 144 de 144**.

O que a experiência pede (⬜):
- O topo da janela diz **"nenhum editor aberto"** com o Resolve aberto: a janela não conhece o Resolve.
- Os chips em âmbar mentem: `.prproj`/`.mov` "não sei ler este formato", a pasta "é uma pasta" — e é exatamente o
  material que a ferramenta usa. O chip deveria dizer o PAPEL (projeto · referência · mídias), não o defeito.
- A resposta é longa e o resultado da conferência rola para fora da tela: pedir que ela comece por "144 de 144".
- Abrir/criar o projeto no Resolve ainda é do editor (o DLPC não abre o Resolve): a ferramenta poderia criar o projeto
  com o nome da sequência quando o Resolve está no "Untitled Project".
- A lista de sequências diz 88 planos e a análise 80 (contagens diferentes do DLPC): não confundiu, mas vale alinhar.

## 2026-10-29 (noite) — o Ciclo Assist abre o programa: `abrir_programa` (`3589d83`)

Pedido do autor: com o Assist desconectado de tudo, ele sobe o programa e o projeto; e a REGRA: *"se o usuário não
informar no prompt o programa que deve subir, o Ciclo Assist deve perguntar mesmo que a opção auto esteja ligada"*.
`cicloassist/resolve.py` (Resolve aberto DESTACADO pelo `explorer.exe`/`open -a` sem `LANG`, a porta 1144 antes do
`scriptapp`, `LoadProject` senão `CreateProject` num processo filho) + `mcp/ferramentas/programas.py`. A regra mora na
conferência, que roda antes do automático, e lê `turno.texto_do_editor` (o que ele ESCREVEU, sem o preâmbulo).

Pilotado (Resolve fechado, Assist aberto, os mesmos três arrastos, automático):
- "Leve este projeto para o programa de cor." → **6,1 s**, nada aberto: *"Você pediu 'programa de cor', mas não disse
  qual. É o DaVinci Resolve?"*
- "Sim, no DaVinci Resolve." → `abrir_programa` (Resolve no ar em **11,8 s**, projeto `WSP-DLPC_2` **criado**) →
  `conformar_no_resolve` (analisar 1,4 · preparar 13,8 · importar 7,5 · conferência 90,1) → **144 de 144**. Turno 2 min 17 s.
- Os dois turnos: 5 chamadas, 1,2 mil de saída, 18,7 mil cache escrito / 68,7 mil lido (~US$ 0,10 de tabela).

⚠️ Achado à parte: a janela do Assist da rodada anterior ficou TRAVADA ("não respondendo" pelo `IsHungAppWindow`)
depois da conferência e do fechamento do Resolve; fechar pelo X não respondia. O `abrir.ps1` a encerrou. Causa não
investigada (⬜ — a webview? o pino TOPMOST que o piloto pôs e tirou?).
