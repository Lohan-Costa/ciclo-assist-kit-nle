# 0018 — Magic Link em canais: a edição no meio, um canal por setor

**Status:** decidido com o usuário (2026-09-25) · implementado (Windows), à espera da conferência
no Media Composer e no Resolve · Data: 2026-09-25
**Emenda** o [ADR 0016](0016-magic-link-pasta-combinada.md) (a pasta combinada única vira uma pasta
por canal) e o [ADR 0017](0017-insert-pela-copia-do-editor.md) (o tipo do insert vem do canal).
Organograma aprovado: https://claude.ai/artifact/Hoj4Qfp1MQYhCongGnCnXc (versão 2).

---

## Contexto

O Magic Link nasceu como UMA pasta combinada, e o painel do Resolve o tratava como se fosse o
jeito de importar. O usuário corrigiu os dois pontos:

- *"O Magic link é um terceiro caminho de comunicação e não sinônimo do import tradicional. ele
  entra quando houver uma comunicação entre edição vfx e cor."*
- *"cor e vfx eles nunca trabalham no mesmo caminho. […] o editor conectaria dois caminhos
  diferentes no magic link para cada time, enquanto os times de cor e vfx só conectariam o seu
  respectivo com a edição. […] programar de forma a expandir futuramente caso entre por exemplo
  envio de sonorização ou trilha sonora. Assim os profissionais alimentam a edição com suas
  tarefas específicas sem ter acesso ao trabalho dos outros setores."*

## Decisão

1. **Três caminhos no painel.** (1) A timeline do próprio NLE (relink); (2) um arquivo, importado
   ou exportado onde o editor quiser, sem gerência; (3) o Magic Link. Em De Lá Pra Cá › Importar
   timeline, o arquivo vem em cima e o Magic Link embaixo. Em Daqui Pra Lá, o destino é o botão:
   **Exportar…** (pergunta a pasta na hora) ou **Enviar para <setor>**. O passo "onde salvar" saiu.
2. **Um canal por setor, a edição no meio** (`plugins/media-composer/servico/canais.py`). Nesta
   etapa, Cor e VFX. Setor novo (som, trilha) é UMA entrada em `canais.SETORES`.
3. **Sem papel: a ilha é o que ela CONECTA.** A edição conecta um canal por time; a cor, só o
   da Cor; o VFX, só o do VFX. **As pastas dos canais** seguem o projeto do Avid
   (`.delapraca.json`, `magic_link.canais`); fora dele (o Resolve), ficam na máquina, e só em
   ⚙ Ajustes. A antiga `magic_link.pasta` é ignorada: nenhum canal olha a raiz antiga.

   CORRIGE (2026-09-25, mesmo dia): a primeira versão tinha um PAPEL por máquina (Edição, Cor,
   VFX) que decidia qual caixa ler. No teste do autor, o Avid e o Resolve rodavam na MESMA
   máquina, com o papel "Edição": o Resolve lia `para-edicao` e não via a timeline que o editor
   mandou para a cor, embora ela estivesse em `edit-cor\para-cor`. O autor escolheu tirar o
   papel. Quem recebe vê os DOIS sentidos de cada canal conectado numa tabela única, com
   colunas De, Para, Tipo, Nome e Enviado, ordenável pelo cabeçalho e com filtro (Novos, Da
   Edição, Da Cor, Do VFX, Já importados, Tudo). O Avid envia sempre como Edição.
4. **Uma pasta por canal, com uma caixa para cada lado**: `para-<setor>` (a edição grava, o setor
   lê) e `para-edicao` (o setor grava, a edição lê). Assim quem cuida da rede libera uma pasta
   só por canal. As caixas nascem sozinhas.
5. **A caixa é gerenciada.** Depois de um Trazer que o NLE confirmou, a Carta desce para
   `importado/timelines` ou `importado/inserts` da mesma caixa (nunca sobrescreve: `_2`). Cópias
   pendentes da mesma Carta descem junto. Se a rede recusar o mover, a timeline já entrou: o
   painel avisa e a Carta fica na fila, marcada como trazida nesta máquina. "Já importados" lê as
   subpastas e guarda o "De novo".
6. **O insert pega o tipo do canal**: sai o seletor "para COR / VFX". O envelope (`envio`) passa a
   dizer `canal`, `de` e `para`. O insert **exportado** para um arquivo tem o tipo `insert`, sem
   setor.
7. No Resolve, "do Resolve" (relink dentro do Resolve) e a aba Daqui Pra Lá aparecem com "em
   breve". No Media Composer, as listas de receber aparecem, e trazer para o Avid é a entrega 4.

## Consequências

- **A separação entre setores depende da rede.** O programa só mostra a cada ilha o canal dela.
  Para a cor não abrir a pasta do VFX nem pelo Explorer, as permissões de cada pasta têm de ser
  dadas por quem cuida da rede; o painel lembra disso em Ajustes.
- O script Lua do Resolve (`plugins/resolve/delapraca_receber.lua`, plano B para o Resolve Free)
  ainda fala a língua da pasta única (`/receber/pasta`) e **não funciona mais**. Ele NÃO será
  portado: o autor decidiu (2026-09-25) que o De Lá Pra Cá exige o Resolve **Studio** — *"o fluxo
  é muito avançado para esse tipo de versão"*. **Saiu em 2026-09-25**: do repositório e do
  `test_ataques_magic_link`. A defesa V9 fica na casca (`test_casca_resolve`), e o `tools/pack.py`
  só o tira das máquinas que ainda o têm instalado.
- ⚠️ Descoberto na implementação: o `/receber/estado` ganhou os canais, e sem `nle` o serviço
  perguntava ao Media Composer, o que estourava o teto de 3 s da casca, que concluía "serviço
  fora do ar". Em modo receptor, sem `nle`, o serviço responde como o Resolve (0,01 s, medido).
- Testes: `test_canais` (27), `test_receber` (70), `test_ataques_magic_link` (15 ataques, no
  layout de canais), `test_magic_link` (17), `test_painel_chrome80` (23).
