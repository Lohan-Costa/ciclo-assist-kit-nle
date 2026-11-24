# `resolver_take` — a camada de tradução entre o Avid e o Claude

**Data:** 2026-09-10 · **Estado:** design aprovado, pronto para implementar
**Fase:** 5, primeira peça — `ver_frames` e `transcrever` dependem desta

---

## 1. O problema, em uma frase

O editor pediu *"analise as cenas da bin C07"* e o Claude não conseguiu, porque tudo que
atravessa a ponte hoje são **nomes**. Não há pixel nem áudio do outro lado.

Entre "o subclipe `C07_P02-T004` existe" e "há um frame para o Claude olhar" existem
quatro traduções que o modelo não tem como fazer — e não deve tentar:

| o Avid tem | o Claude precisa de |
|---|---|
| subclipe com **dois masters** e offsets distintos | um take com começo e fim |
| MobID → SourceMob → MSM → OP-Atom, **um arquivo por track** | um arquivo de vídeo, um de áudio |
| frames a 23,976, drop-frame, TC de fonte | segundos, para casar com a transcrição |
| 5 canais de som direto | a mixagem certa para transcrever |

⭐ **`resolver_take` é a peça que faz essas quatro traduções.** Ela não devolve frame nem
texto: devolve o *endereço físico* do take, já corrigido. `ver_frames` e `transcrever`
são consumidoras dela.

---

## 2. O que foi medido antes de desenhar

Tudo abaixo é `confirmado` contra o material real (MC 2025.6.58781 / Windows 11, projeto
`_Assist anterior`, curta *PRODUCAO-A*), em 2026-09-10.

### 2.1 ⭐ Um subclipe sincronizado mistura DOIS masters

`C07_P02-T004`, lido com pyavb direto do `CENAS/C07.avb`:

```
subclipe C07_P02-T004        edit_rate 23.976   length 5430
  ├─ track[5] picture  → master a003_03170859_C005                start=0    len=5430
  └─ track[0..4] sound → master "PRODUCAO-A - 05-04 C7 P2-T004" start=234  len=5430
                          track_id 1,2,3,4,5
```

Confirma o que o banco já registrava em
[`protocolos/avb/sincronizacao-e-subclipes.md`](../../../bancodedadosnles/protocolos/avb/sincronizacao-e-subclipes.md):
*"um subclipe pode misturar masters — é a forma que o AutoSync produz: V da câmera, A do
som"*.

⭐ **De um único subclipe saem as duas matérias-primas**: o vídeo para os frames e o som
direto para a transcrição. Não é preciso procurar o par; ele já está amarrado ali.

### 2.2 ⚠️⚠️ Os offsets dos dois masters são DIFERENTES

`start=0` na imagem, `start=234` no som. É o sync assado dentro do subclipe.

**Usar um offset para os dois dessincroniza em 234 frames — 9,8 s a 23,976.** E o modo de
falha é o pior possível: uma transcrição alinhada com o offset errado descreve a cena
vizinha, com total confiança e sem nada acusando.

⛔ **Consequência de desenho, não detalhe de implementação:** o take não tem *um* in/out.
Tem um in/out **por master**. A estrutura de retorno precisa refletir isso, ou o erro
volta na primeira consumidora que assumir um só.

### 2.3 O nome do master de som É a claquete

```
"PRODUCAO-A - 05-04 C7 P2-T004"   →  cena C7, plano P2, take T004
```

A procedência que o design de 25/08 pedia (`fonte: claquete`, `confianca: confirmado`)
sai de graça daqui. O nome do master de câmera (`a003_03170859_C005`) não tem nada disso
— rolo, data, clipe. Confirma o achado 1 daquele spec: **a claquete é do som**.

### 2.4 O `SourceMob` NÃO está na bin

Li a `C07.avb` (123 mobs) e a `D02_CAM A.avb` (130 mobs) inteiras: **zero SourceMobs**. O
master aponta para um `SourceMob` por track, e eles vivem no MSM.

```
master a003_03170859_C005
  track[0] Sequence(picture) → Filler + SourceClip(mob …1dc90000, track_id=1) + Filler
  track[1] Sequence(sound)   → SourceClip(mob …1dcb0000, track_id=1)
  track[2] Sequence(sound)   → SourceClip(mob …1dcc0000, track_id=2)
```

⚠️ **Armadilha de travessia:** a track do master é uma `Sequence` cujo primeiro componente
é um **`Filler`**, não o `SourceClip`. Pegar `components[0]` devolve um objeto sem
`mob_id` — e o sintoma é um campo vazio, não uma exceção. Custou uma rodada de
depuração hoje. **Procure o `SourceClip` na sequência; não presuma a posição.**

### 2.5 A resolução para arquivo: OP-Atom, um por track

Mídia **gerenciada** (`D:\Avid MediaFiles\MXF\<pasta>\`), com `msmFMID.pmr` e
`msmMMOB.mdb` em todas as 10 pastas do acervo desta máquina. Os dois masters do take
estão na **mesma pasta**, `0200230405`:

```
a003_03170859_C005.mxf              ← imagem (sem sufixo)
a003_03170859_C005_A01.mxf  _A02    ← scratch da câmera
PRODUCAO-A - 05-04 C7 P2-T004_A01.mxf … _A05   ← os 5 canais do som direto
```

⭐ **O padrão de nome é `<nome do master>[_A<nn>].mxf`** — vídeo sem sufixo, cada canal de
áudio com o seu. E os cinco `_A01.._A05` do som batem exatamente com as cinco tracks de
som do subclipe.

---

## 3. Como resolver master → arquivo: a decisão, e por que

Três rotas possíveis. A escolha não é óbvia e o banco tem opinião nas três.

| rota | custo | quando falha |
|---|---|---|
| **nome do master → varredura das pastas** | leitura de diretório | nomes iguais em projetos diferentes |
| `.pmr` (MobID → arquivo) | parser próprio | ⚠ em storage de rede gerenciado o `.pmr` **não fica na pasta de mídia** |
| `GetMobInfo` do MC (`Source Path`) | ~500 ms/master, exige MC aberto | bin fechada; qualquer modal trava a API |

**Decisão: nome primeiro, `.pmr` como autoridade no desempate.**

O banco é explícito em
[`transversal/banco-de-midias-compartilhado.md`](../../../bancodedadosnles/transversal/banco-de-midias-compartilhado.md):
*"a chave estável é o NOME NORMALIZADO do master … dos 101 casamentos por nome de uma
medição real, 100 foram exatos"*. E o `.pmr` traz a ressalva de não servir de fundação.

⭐ **E há um freio de mão que vem de graça:** o banco registra que a coluna `Tracks` do
`GetMobInfo` (`V1 A1-2`, `A1-5`) diz **quantos arquivos aquele master tem** — o que
permite **parar de procurar** quando o conjunto está completo. Medido lá: 109,7 s varrendo
tudo contra 10,9 s com filtro por nome e parada. Na v1 usamos a contagem de tracks do
próprio mob (que já temos, sem custo de API); a coluna fica como conferência futura.

### ⚠️ Ler bin fechada pela API não serve — medido hoje

As 13 bins de câmera e som devolveram `"Bin is not open."` **de verdade** (a bin está
fechada mesmo, não é a armadilha do caminho). E `OpenBin` **tem efeito visível**: abre a
bin na tela do editor, no meio do trabalho dele.

⭐ **Regra que sai daí, e vale para todo o produto:**

> **Para LER, o arquivo. Para saber o que está aberto ou selecionado, e para ESCREVER, a
> API.**

Ler o `.avb` com pyavb resolveu na hora, sem tocar no Media Composer e sem o piso de
500 ms por chamada.

---

## 4. A interface

```
resolver_take(bin, item) -> Take
```

`bin` e `item` são exatamente o que `listar_itens_da_bin` acabou de mostrar ao modelo —
caminho da bin e nome (ou MobID) do subclipe.

⚠️ **Por que não `resolver_take(mob_id)` sozinho.** Faltaria descobrir em que bin o mob
vive, e a única rota é `GetBinFromMob`, que o banco documenta com **duas armadilhas que
falham em silêncio**: é sensível ao agrupamento do texto do MobID (`26-6-16-12-4` acha, 64
hexadecimais corridos devolve `None`) e **não localiza todo masterclipe** (respondeu para
10 de 10 subclipes e 1 de 19 masters). Passar a bin é grátis para o modelo e apaga a
classe inteira de problema.

⭐ E aceitar **nome OU MobID** segue a lição da fase 1: *o modelo devolve o que a
ferramenta anterior mostrou a ele*, e `listar_itens_da_bin` mostra os dois.

### A forma do retorno

```json
{
  "nome": "C07_P02-T004",
  "cena": "C7", "plano": "P2", "take": "T004",
  "fonte_da_claquete": "PRODUCAO-A - 05-04 C7 P2-T004",
  "fps": {"num": 24000, "den": 1001}, "fps_aprox": 23.976,
  "duracao_frames": 5430, "duracao_s": 226.48,

  "imagem": {
    "master": "a003_03170859_C005",
    "arquivo": "D:\\Avid MediaFiles\\MXF\\0200230405\\a003_03170859_C005.mxf",
    "inicio_frames": 0, "inicio_s": 0.0
  },
  "som": {
    "master": "PRODUCAO-A - 05-04 C7 P2-T004",
    "canais": ["…_A01.mxf", "…_A02.mxf", "…_A03.mxf", "…_A04.mxf", "…_A05.mxf"],
    "inicio_frames": 234, "inicio_s": 9.76
  },

  "confianca": "confirmado", "fonte": "claquete"
}
```

Decisões embutidas na forma, cada uma com um porquê:

- **`imagem` e `som` são blocos separados, cada um com o próprio `inicio`.** É §2.2 virando
  estrutura: não existe lugar onde alguém possa pegar "o offset do take".
- **Segundos vêm calculados, junto com os frames.** A conversão usa `edit_rate` e é onde o
  erro de 1/1001 mora. Fazer uma vez aqui é melhor que três vezes nas consumidoras.
- **Cena, plano e take vêm partidos**, com o nome de origem ao lado. O modelo não deveria
  reparsear claquete — e quando o padrão não casar, os campos vêm nulos e
  `fonte` vira `"nome-nao-reconhecido"`, que **não é erro** (design de 25/08, §Camada 1: a
  convenção de nome muda a cada produção e o leitor é plugável).
- **Procedência sempre** (ADR: item sem procedência é bug, não item).

### O que ela NÃO faz

Não extrai frame, não transcreve, não abre `.mxf`, não toca no Media Composer. Ela
responde *onde está* e *que pedaço*. Quem lê pixel é `ver_frames`; quem lê áudio é
`transcrever`.

---

## 5. Armadilhas a respeitar na implementação

Todas do banco ou medidas hoje. Cada uma já custou tempo de alguém.

| # | armadilha | onde está registrado |
|---|---|---|
| 1 | O `SourceClip` **não** é `components[0]` da track do master — há `Filler` antes | §2.4, medido hoje |
| 2 | Imagem e som têm **offsets diferentes** dentro do subclipe | §2.2, medido hoje |
| 3 | OP-Atom = **um arquivo por track**; vídeo sem sufixo, áudio `_A<nn>` | §2.5, medido hoje |
| 4 | TC de fonte do OP-Atom vive em `stream.tags`, **não** em `format.tags` — e a essência **não é necessariamente a stream 0** | `protocolos/mxf/timecode.md` |
| 5 | **pymediainfo mente** sobre TC de OP-Atom: devolve o TC de sistema (120 h) e ainda diz `"Source Package"` | `protocolos/mxf/timecode.md` §2 |
| 6 | `mob_id` de mídia **AMA** é regerado a cada link (83 de 118 mudaram numa medição) — nome é a chave estável | `transversal/banco-de-midias-compartilhado.md` |
| 7 | `GetBinFromMob` é sensível ao agrupamento do MobID e não acha todo master | `plugins/avid-panel-sdk/README.md` |
| 8 | Ao converter a URN do pyavb, tirar o prefixo **antes** de filtrar hexadecimais — o `e` de `smpte` e o `d` de `umid` passam pelo filtro e o total vira 66 dígitos | idem |

---

## 6. Pronto quando

O editor pergunta *"o que tem no take C07_P02-T004?"* e o Claude devolve o caminho do
arquivo de vídeo, os cinco canais de som e o intervalo correto de cada um — **com o
offset de 234 frames aplicado no som e não na imagem**.

E o teste que prova isso não pode ser "não deu erro": o gabarito é lido por nós do
`.avb` e comparado campo a campo, como na fase 1.

---

## 7. Escopo desta peça

**Dentro:** subclipe sincronizado, mídia gerenciada (OP-Atom em `Avid MediaFiles`),
masters na mesma bin do subclipe.

**Fora, e declarado:**

- **Mídia AMA.** Outro caminho de resolução (`AMA Metadata Folders`, um `.aaf` por
  arquivo). O banco documenta em `protocolos/msm/ama-management.md`; entra quando aparecer
  material assim.
- **Masterclipe solto** (sem subclipe). Cabe depois, e é caso mais simples — sem offset.
- **Storage de rede.** ⚠ O banco avisa que lá o `.pmr` não fica na pasta de mídia. Não foi
  medido e **não se deve presumir que funciona**.
- **Timecode de fonte.** A v1 trabalha em frames relativos ao master, que é o que as
  consumidoras precisam. Ler o TC do `.mxf` (armadilhas 4 e 5) entra quando houver
  necessidade real de casar com algo externo.
