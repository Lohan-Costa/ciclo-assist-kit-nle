# Corte zero — o plano como dado, e o Media Composer montando

**Data:** 2026-09-10 · **Estado:** implementado e conferido no Media Composer
**Fase:** 5c — a última das três funções, e a primeira que escreve no projeto do editor

---

## 1. O que é

O editor pede *"monta um primeiro corte da cena 7"*. O produto devolve uma sequência na
bin dele, com um take escolhido por fala, e a procedência de cada corte à vista.

⭐ **E o que ele aprova não é "posso importar este arquivo?" — é o plano inteiro**, corte
a corte, com take, in/out e de onde veio a decisão. O editor aprova o resultado que vai
acontecer, não a mecânica (ADR 0003).

---

## 2. A rota: autorar a `.avb` — sem import, sem preset

⛔⛔ **Decisão do autor, 2026-09-10: qualquer caminho que dependa de PRESET do Avid está
descartado.** Preset é configuração do usuário, mora no `Settings.xml` dele, e **o nome
mente**: o banco registra um preset chamado "AAF" que exportava WAVE e fez o Media
Composer renderizar 26 minutos de áudio. Um produto que instala na estação de um cliente
não pode ter o resultado decidido por uma preferência que ele não controla.

Isso derruba a rota `ExportFile` → clonar referência → `ImportFile`, que era o plano
anterior desta spec e que o spike já tinha reprovado por outro motivo (§8).

### O que sobra, e já está provado em produção

**Escrever a `.avb` diretamente com pyavb.** O Assistir antigo faz exatamente isso
(`assist_anterior/modulos/assistir/emissor.py`): autora as timelines e grava um arquivo de bin
novo na pasta do projeto. Nenhum import, nenhum preset, nenhuma configuração de usuário.

⭐ **E o idioma tem round-trip contra um Media Composer real:** a timeline `C04_CORTE`
abriu no MC em 2026-08-30 e validou o trail `Filler`, o `user_placed` e o matchframe.

| | `ExportFile`+`ImportFile` | **autorar `.avb`** |
|---|---|---|
| depende de preset do usuário | **sim** ⛔ | não |
| entra no projeto aberto | sim | a bin aparece; o editor abre (ou `OpenBin`) |
| risco do modal de subclipe | **sim** | não existe: não há import |
| provado nesta casa | não | **sim, em produção** |

O custo é o passo a mais: a bin nova aparece na janela do projeto e alguém a abre. Dá para
adiantar com `OpenBin` — que é rpc tipado, **sem preset nenhum** —, e cujo "efeito visível"
aqui é justamente o que se quer.

⚠️ **`OpenBin` é operação de ARQUIVO, não consulta.** Teto de dezenas de segundos, nunca o
de consulta (`TEMPO_DE_ARQUIVO_S`). Um teto curto demais **não devolve erro honesto —
devolve decisão errada com confiança**.

⛔ **Nunca gravar sobre a bin de origem.** Medido no projeto anterior: o `topen` do pyavb é
preguiçoso e passa a ler offsets de um arquivo já truncado. `3.922 bytes → 119`, bin
destruída. A saída é **sempre** um arquivo novo, e o emissor recusa se o caminho de saída
for igual ao da base.

---

## 3. A timeline aponta para os SUBCLIPES

Sem import, o modal *"Sub clip conflict found"* deixa de existir como risco — ele só
acontece ao **reimportar** um AAF cujos subclipes já estão no projeto. Isso devolve a
liberdade de escolher, e a escolha certa é o subclipe.

**Por quê:**

- É o que o editor **vê na bin**. O matchframe cai no take, não num master de rolo inteiro.
- O subclipe **já carrega o recorte** dentro do master — então `start_time` no `SourceClip`
  é a posição **dentro do take**, que é exatamente a unidade em que a transcrição fala
  (`inicio_no_take`). Nada a converter.
- É o caminho com round-trip contra um MC real (§2).

⚠️⚠️ **O erro de simetria, e ele soma o recorte duas vezes:** usar o offset do MASTER *e*
apontar para o SUBCLIPE. O `resolver_take` devolve `imagem.inicio_frames` — que é offset de
master — e ele **não entra aqui**. É o achatamento ao contrário, e o `subclipes.py` antigo
já avisa disso.

| se o `SourceClip` aponta para | `start_time` é |
|---|---|
| **subclipe** (a nossa escolha) | posição dentro do take — `0` para o take inteiro |
| master | o offset do master, e aí o take precisa ser recortado à mão |

⚠️ **O MobID tem duas representações**, e a da API **não** é a do pyavb. Passar o hex cru
para um writer gera *"missing mob"*. O `resolver_take` devolve `mob_id` na forma URN nativa
do arquivo (`urn:smpte:umid:...`), que é a certa para autorar — a conversão só é necessária
no sentido contrário, para perguntar à API.

⚠️ **E o `resolver_take` precisa passar a devolver o mob_id do SUBCLIPE junto**, não só o
dos masters. Ele já tem (`take.mob_id`); é só a timeline usá-lo.

---

## 4. As três regras que outro produto da casa já pagou

Vêm de `motores/delapraca/avb_export/translate.py`, em produção. ⭐ **Foram medidas em AVB,
e a rota agora é AVB — então valem diretamente**, sem a ressalva de tradução que esta spec
carregava enquanto o plano era AAF.

1. ⛔⛔ **Toda track abrange a duração INTEIRA do comp** — `Filler` de rabo. Sem isso o MC
   estoura ao navegar além do fim da track: `PMM_INSUFFICIENT_MEDIA` mais assertion
   `GetVideoFrameOffset < GetGlobalDuration`.
2. ⚠️ **Comp só de áudio ganha uma V1 vazia.** Convenção do Avid.
3. ⚠️⚠️ **`create.Composition(nome, ...)` IGNORA o argumento `nome`** — o `__init__` faz
   `self.name = mob_type`. Atribuir `.name` depois, sempre.

⛔ **Escrever estrutura nova em vez de copiar a que está em produção é o erro que o projeto
anterior cometeu DUAS vezes**, reintroduzindo defeito já medido e documentado. O idioma
vem de lá; só o que for genuinamente diferente é escrito novo.

---

## 5. O plano é a fronteira

```
Claude → PLANO (JSON, esquema fechado) → validador → portão → .avb autorada
             ↑                    ↑            ↑              ↑
      versionável,          recusa ANTES   o editor vê   arquivo NOVO, nunca
      diffável, legível     de tocar no    e decide      por cima da origem
                            projeto
```

### A recusa é ATÔMICA

⛔ Item malformado recusa o **plano inteiro**, nunca só o item. Mesma disciplina do
`allow_pickle=False` do Decupador: entrada malformada não passa "quase certa".

⚠️ E a mensagem diz **qual** item e **o que** falta. Um "plano inválido" sozinho manda o
editor procurar no escuro.

### O item

```json
{
  "fala": "C07_FALA03",
  "take": "C07_P02-T004",
  "bin": "CENAS/C07.avb",
  "inicio_no_take": 32, "duracao_frames": 240,
  "confianca": "hipotese", "fonte": "heuristica",
  "medida": 0.12,
  "porque": "último take da série; a fala aparece em 3 takes"
}
```

### ⭐⭐ O corte em L e em J (2026-09-11)

O item ganhou dois campos, e eles resolvem um defeito visto em campo:

```json
{ "take": "C07_P03-T001", "inicio_no_take": 1038, "duracao_frames": 268,
  "corte_de_som": "antes", "som_frames": 14,
  "porque": "corte em J — o 'sobe comigo' dele entra sob o rosto dela" }
```

| `corte_de_som` | o que acontece | o editor chama de |
|---|---|---|
| `junto` (padrão) | imagem e som cortam no mesmo frame | corte seco |
| `antes` | o som deste plano entra ANTES da imagem dele | **corte em J** |
| `depois` | o som do plano anterior segue sob a imagem deste | **corte em L** |

⛔ **O que forçou isto:** o editor pediu cortes em L e em J, e o plano não tinha onde
dizer isso — `Corte` era um bloco único de imagem+som. O modelo tentou imitar esticando o
plano anterior, e a **mesma fala tocou duas vezes**, uma em cada take. Não era erro de
julgamento dele: era vocabulário que não existia.

⭐ **Palavra, não sinal.** A alternativa era um número com sinal (`-14` = J, `+14` = L).
Mais curta, e com um modo de falha silencioso: sinal trocado vira um L onde se pediu um J,
e nada acusa — o editor só descobre assistindo.

⭐ **Um número por transição, e a conta fecha por telescópio.** Cada corte carrega o
deslocamento do som **no começo dele**; a duração de som sai de
`duração da imagem − desloca(i) + desloca(i+1)`. Os deslocamentos se cancelam na soma, e
a trilha de som fecha exatamente o comprimento da de imagem — sem buraco e sem sobra.
É por isso que o primeiro corte não pode deslocar nada: não há vizinho de quem tomar
emprestado.

⚠️ E um corte em J exige material **antes** do in-point: o som recua dentro do take. Pedir
som antes do frame 0 é pedir mídia que não existe, e o Avid aceita mostrando silêncio, sem
erro nenhum — por isso o validador recusa.

⚠️ `inicio_no_take` é **posição dentro do take**, porque a timeline aponta para o
subclipe (§3). É a mesma unidade que a transcrição devolve em `inicio_no_take`, e é o
que evita a conversão onde se perde frame.

⭐ **`porque` em prosa, e não só o par confiança/fonte.** O editor aprova corte a corte;
`hipotese/heuristica` diz o *grau*, não o *motivo*. Foi lendo o motivo — *"o take foi
abortado, tem um homem gritando"* — que o Claude fez a escolha certa na fase 5b, e é isso
que precisa chegar à tela.

### A confiança diz se HOUVE escolha

Regra herdada do montador antigo, e ela é a única informação que distingue um in/out de um
palpite:

| takes que tinham a fala | confiança |
|---|---|
| um | `inferido` — não houve escolha |
| mais de um | `hipotese` — a regra ELEGEU, e eleger é palpite explicável |

---

## 6. Quem escolhe o take

⭐ **Mudança de desenho em relação ao spec de 25/08, e ela é ganho medido.** Aquele design
escolhia por heurística: descarte do som, último da série, duração coerente, transcrição
não vazia.

Na fase 5b o Claude **leu o motivo** do descarte na própria gravação. Heurística chuta;
isto sabe. Então:

- **O Claude propõe** o plano, com `porque` em prosa, usando transcrição e quadros.
- **A heurística vira rede de proteção**, não decisor: se o modelo não justificar, o item
  cai para `hipotese/heuristica` com a regra do último take.
- **O editor decide**, corte a corte, no portão.

⛔ **Não há julgamento de interpretação.** Isso é skill de narrativa, e ela não existe.

---

## 7. Pronto quando

O editor pede um primeiro corte da cena 7, **vê o plano no painel corte a corte**, aprova,
e a sequência aparece numa bin nova do projeto — **online**, tocando, e com o matchframe
levando ao take certo.

E o **não** continua sendo respeitado: recusado, nada é escrito e nenhum arquivo entra.

### ✅ CUMPRIDO — conferido pelo editor em 2026-09-10

As duas metades foram validadas no Media Composer real, pelo autor:

| o que foi conferido | resultado |
|---|---|
| a timeline abre e toca | ✓ |
| a V1 vem LIGADA, sem exigir clique | ✓ (o desvio deliberado de `MONSTATE`, §4) |
| o recorte parcial cai no frame certo, e o matchframe leva ao take | ✓ |
| o in-point do plano proposto caiu **depois da claquete** | ✓ |

⭐ O último item é o que fecha o círculo das três funções: o Claude posicionou o corte
usando a claquete **cantada no áudio**, que só existe porque a fase 5b transcreve o som
direto. Nada no produto manda fazer isso — caiu da composição das peças.

---

## 8. A ordem de trabalho — spike antes de tudo

O elo mais arriscado não é o plano nem a interface: é **o AAF abrir no MC com os masters
certos**. Nada disso vale se o import criar 10 masterclipes offline.

| # | prova | como se sabe que passou |
|---|---|---|
| 1 | autorar um AAF de **um corte só**, de um master que já existe na bin | `ImportFile` sem modal, sequência na bin |
| 2 | os masters são **reusados**, não duplicados | a bin não ganha master novo; o clipe está online |
| 3 | dois cortes de masters diferentes, com offsets | a emenda cai no frame certo |
| 4 | o plano completo da C07 | corte a corte, aprovado no portão |

⚠️ **Se o passo 1 falhar, a rota AAF cai inteira** e a alternativa é autorar `.avb` como o
Assistir antigo — perdendo a entrada no projeto aberto. É por isso que ele vem primeiro.

### ⛔ Spike 1, rodada 1 — FALHOU, e o banco já dizia por quê (2026-09-10)

`spikes/fase5c_aaf.py`. Autorei um AAF com **`MasterMob` de esboço** — MobID correto, nome,
e **nenhum slot** — mais um `CompositionMob` de topo com dois cortes de 240 frames.

```
ImportFile  →  task_id devolvido, sem modal, sem erro
bin _TESTE_CICLO  →  0 itens
masters no projeto  →  x1 cada (nenhum duplicado)
```

⭐ **O modo de falha é o pior tipo: silencioso e com aparência de sucesso.** A chamada
volta com `task_id`, nada reclama, e a bin fica vazia. Quem confiar no retorno da API
conclui que importou.

**A causa está registrada no banco desde antes, em
[`protocolos/aaf/geracao.md`](../../../bancodedadosnles/protocolos/aaf/geracao.md), e eu
tentei encurtar o caminho:**

> **Princípio: clonar a referência, não recriar o grafo de mobs.** O relink do Avid se
> ancora no MobID do MasterMob. **Recriar source/master mobs do zero arrisca quebrar o
> relink.**

Um `MasterMob` sem slots não tem para onde apontar: os `SourceClip`s da composição não
resolvem, e o MC descarta em silêncio. Não basta ter o MobID certo.

### ⛔ E a rota que esse resultado sugeria foi DESCARTADA pelo autor

A saída natural da falha acima era a do banco: **clonar um AAF de referência** exportado
pelo próprio Avid (`ExportFile` aceita `mob_id`), remover só o `CompositionMob` de topo, e
pôr o nosso no lugar.

**Descartada em 2026-09-10, e a razão vale mais que a rota:** `ExportFile` depende de um
**preset**, que é configuração do usuário. O banco documenta o acidente — um preset
chamado **"AAF"** que exportava WAVE e fez o MC renderizar 26 minutos de áudio, porque quem
decide o formato é o atributo `_EXPORTFORMAT` e **não o nome**. Um produto instalado na
estação de um cliente não pode ter o resultado decidido por uma preferência que ele não
controla, e que ele pode mudar sem saber o que quebrou.

⇒ A rota passou a ser **autorar a `.avb`** (§2), que não depende de configuração nenhuma e
já roda em produção nesta casa.

### O plano de spike refeito

| # | prova | como se sabe que passou |
|---|---|---|
| 1 | autorar uma `.avb` com **um corte só**, apontando para um subclipe da C07 | a bin abre no MC e a timeline toca |
| 2 | dois cortes, de takes diferentes | a emenda cai no frame certo, matchframe leva ao take |
| 3 | recorte parcial (`start_time` dentro do take) | o in/out bate com a transcrição |
| 4 | o plano completo da C07 | corte a corte, aprovado no portão |

⚠️ O passo 1 continua sendo o elo mais arriscado, mas o risco mudou de natureza: já não é
*"o MC aceita o que autoramos?"* (o idioma tem round-trip), e sim *"portamos o idioma sem
reintroduzir defeito já pago?"*.

⚠️ **Refinamento da regra "para LER, o arquivo":** logo depois de um `ImportFile`, a `.avb`
no disco tem **zero mobs** — o MC segura a bin suja em memória e só grava ao fechar. Para
conferir o resultado de uma escrita, perguntar à API; o arquivo só é autoridade sobre bin
que o MC não está segurando.

⚠️ **Achado de pyaaf2:** `Sequence.length` **não se calcula sozinho**. Com dois
`SourceClip` de 240 frames dentro, `seq.length` continua **0** — e uma track que não cobre
o comp faz o MC estourar com `PMM_INSUFFICIENT_MEDIA`. Tem de ser atribuído, e o spike
agora confere.

---

## 9. Fora de escopo, e declarado

- **Transições.** Nada de dissolve, fade ou efeito: todo corte é seco *na imagem*. O nome
  é "corte zero".
  ⚠️ **Corte em L e em J NÃO são transições** e entraram no escopo em 2026-09-11 — são
  cortes secos com o som trocando alguns frames antes ou depois da imagem. A distinção
  não é jurídica: dissolve é efeito renderizado, L/J é posição de corte, e o editor
  pediu os dois com a mesma frase ("sem transição, mas com corte em L").
- **Áudio além do take.** Nada de mixagem, ducking, música.
- **Skills por produção.** O plano diz que existem (`--plugin-dir`); o carregamento entra
  quando houver uma skill real para carregar.
- **Multicam / groupclip.** O `resolver_take` v1 resolve subclipe sincronizado; groupclip
  tem caminho próprio.
