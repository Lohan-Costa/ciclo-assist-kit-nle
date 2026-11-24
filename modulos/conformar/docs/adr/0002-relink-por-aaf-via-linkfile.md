# 0002 — Relink por AAF via `LinkFile`, não reautoria por `.avb`

**Status:** ativa · Data: 2026-08-10 · **emendada pelo [ADR 0013](0013-a-rota-avb-volta-a-existir.md)**
(2026-08-16): a coluna "rota `.avb`" desta tabela é a de **reautoria** (`build_avb`).
Existe uma terceira rota — **editar a bin que o próprio MC escreveu** —, medida e
validada na tela, em que os efeitos sobrevivem. A troca de rota segue em aberto.

**Contexto:** a limitação histórica registrada no banco de NLEs dizia que "auto-link
100% sem toque é inviável porque o `amaMMOB.mdb` só o Avid cria" — e foi por isso que a
v1 do RELINKER entregava um AAF preparado e deixava o relink manual com o editor. **Essa
frase vale para quem está fora do Avid.** Dentro do Media Composer, `LinkFile` faz o
próprio Avid criar o AMA Management e o `amaMMOB.mdb`. A condição que faltava passou a
existir assim que o produto entrou para dentro do editor ([ADR 0001](0001-plugin-autonomo-dentro-do-editor.md)).

Duas rotas foram avaliadas, e um spike decidiu entre elas antes de qualquer outra parte
do plugin, porque a escolha determina a fase de aplicação inteira:

| | rota AAF | rota `.avb` |
|---|---|---|
| quem monta a timeline | o Media Composer | nós (`build_avb`) |
| efeitos | intactos por construção | Titler+, FrameFlex e Matte Key dropam |

**Decisão:** relink por `LinkFile` (mídia original) → remap de MobID no AAF → `ImportFile`.

**Medido** (AAF de produção, 1172 segmentos, 118 masters): os masters
relinkados passaram do codec de transcode offline para o do arquivo original, com a
procedência preenchida; o Media Composer **reusou** os masters AMA criados pelo
`LinkFile` em vez de recriar offline (a bin ficou com 119 masters, não 122); o automatch
por MobID funcionou e **quem montou a timeline foi o MC**. Em escala real (100 masters,
841 referências, 1121 segmentos): timewarp e estabilizadores confirmados intactos na
tela pelo editor — são justamente os efeitos que a rota `.avb` reproduziria mal.

**Consequência:** `avb_export`/`build_avb` deixa de ser o caminho do plugin dentro do MC
e vira o backend do App agnóstico, para quem não tem o Media Composer. `LinkFile` em
massa é ~92% do tempo de aplicação (piso de ~500 ms por chamada do MC) — a barra de
progresso não é enfeite, é requisito (ver [ADR 0008](0008-uma-sessao-por-vez-progresso-lido-por-sse.md)).
Uma falha de `LinkFile` não derruba as outras: o arquivo entra em `falhas` e o fluxo
segue — um acervo real tem arquivo corrompido ou volume desmontado, e perder todo o
trabalho por causa de um seria pior que relinkar os demais.

Esta decisão também **corrige** o registro do banco de NLEs
(`protocolos/aaf/escrita.md`): o limite do auto-link vale para quem está fora do Avid,
não dentro dele.
