# Bins e timeline do editor no Media Composer, e o take

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐ Atualizar a bin do editor: fechar, escrever, abrir

Dá para acrescentar uma sequência numa bin que **já existe**, sem perder o que está lá —
medido em 2026-09-11 e registrado no banco (`protocolos/avb/escrita.md`):

```
CloseBin  →  pyavb (escreve AO LADO, os.replace, UID PRESERVADO)  →  OpenBin
```

⛔⛔ **Sem o `CloseBin` não funciona, e falha em silêncio.** `OpenBin` numa bin já aberta
devolve `Completed` e **não relê o disco**; e o MC salva por cima do nosso arquivo quando
ele mesmo fechar a bin. Não existe "refresh".

⭐ E aqui o `Bin.uid` é **preservado**, ao contrário da regra do resave: randomizar faria o
MC tratar a bin como outra (`.AutoCopy.NN`), e o editor ganharia uma segunda bin em vez da
dele atualizada.

⛔⛔ **A STRING NULA, e o diagnóstico de AMA que estava errado** (2026-09-13,
`spikes/a_bin_ama_regravada.py`). Uma string de `.avb` com tamanho `0xFFFF` é campo que
NÃO EXISTE; o pyavb a lê como `""` e grava `00 00`. Com isso o `OpenBin` recusa a **bin
inteira** com `FILE_OPEN_FAILURE`. Onde estava: `WinFileLocator` AMA com caminho UTF-8 nulo
(a `BIN ORIGEM` tem dois). Mesma bin, uma variável: pyavb cru → recusa; `0xFFFF`
preservado → abre. O conserto é `cicloassist/avid/avb_fiel.py`, aplicado ao importar
`cicloassist.avid`.

⚠️ Em 2026-09-12 eu tinha escrito "mob AMA com `WinFileLocator` condena a bin". **Não
condena:** duas bins AMA do editor, com BRAW, MOV e WAV linkados e 20 locators de caminho
preenchido, regravam e abrem com o pyavb cru. A bisseção tinha achado os mobs certos e
nomeado a característica errada.

⚠️ **`FILE_OPEN_FAILURE` tem três causas conhecidas com a mesma frase** (uid repetido, bin
aberta reescrita por baixo, string nula) — a primeira hipótese testada "explica" o sintoma
e para a investigação. Aconteceu duas vezes: duas rodadas culpando o uid, e depois o AMA.

⭐ **E a rede para a quarta causa, que ninguém mediu ainda:** o `montar_corte` guarda a bin
do editor depois do `CloseBin`; se o `OpenBin` da bin regravada devolver
`FILE_OPEN_FAILURE`, a original volta **byte a byte**, a sequência vai para uma bin NOVA, e
a resposta traz `aviso_para_o_editor` dizendo as duas coisas. Só essa frase conta como
recusa: Media Composer fechado não julga arquivo nenhum.

⛔⛔ **A bin nova leva o FECHO, oculto.** A timeline aponta SUBCLIPES, que não resolvem fora
da bin: uma bin só com a timeline abre, lista, e derruba o MC ao carregar
(`ACCESS_VIOLATION`, banco, 2026-08-30). Até 2026-09-13 o caminho "bin nova" do
`montar_corte` fazia exatamente isso. Agora `escrever_bin(base=…)` copia o fecho com
`user_placed=False` — a saída validada em produção em 2026-08-31.

✅ **Conferido na tela em 2026-09-13:** o editor carregou na Record todas as timelines
desta rodada — AMA (MOV, WAV, BRAW) e gerenciadas, acrescentadas à bin de origem, a OUTRA
bin e a bin nova, e a `BIN ORIGEM` com a string nula consertada. Todas online e tocando.

### ⭐⭐ Editar a timeline DO EDITOR: a cópia prova que só o pedido mudou

**Decisão do editor (2026-09-13): caminho B.** A IA mexe numa timeline montada à mão — com
efeitos, keyframes, automação, transições, group clips — e entrega uma **cópia na mesma
bin**, a original intacta, carregada na Record. Ele escolheu B em vez de reler a timeline
como plano de cortes justamente para não perder nada que trabalhou.

`avid/edicao.py`: `extrair`, `inserir` (e o gap é `inserir` sem conteúdo),
`conferir_fidelidade`. **Conferido na tela** na `TL EDITADA` (4.277 objetos): extrair um
trecho de todas as trilhas, inserir 2 s de um subclipe na V2 com o som em A1–A5, abrir gap
antes do último segmento — tudo em sync, efeitos e volume intactos, zero quedas.

⛔⛔ **A cópia só é gravada se a prova passar**, e a prova é estrita: todo segmento que no
original está inteiro fora do trecho aparece com a MESMA impressão digital na cópia; só pode
faltar um VAZIO (estendido ou colado). A primeira versão tolerava "um diferente de cada
lado" e aprovava um clipe alterado na emenda — há teste para isso.

⛔ **Recusa em vez de adivinhar, e antes de mexer em qualquer trilha**: meio de clipe,
transição encostando, keyframe num segmento aparado, group clip no trecho. Edição aplicada
pela metade dessincroniza.

- ⛔⛔ **O memo da impressão segura o objeto.** Com `id()` de chave, o pyavb soltava e relia
  objetos, um novo herdava o `id` de outro, e a prova acusou a bin inteira.
- ⛔ **Uma sequência pode ter três trilhas de timecode** (`86400@24`, `86400@24`,
  `90000@25`): o início é a PRIMEIRA, no `fps` dela. A última adiantou tudo 2 min 30 s.
- ⭐ **Mob oculto é material.** O subclipe inserido só existia oculto na bin da timeline;
  pelo arquivo ele resolve, pela API (`GetListOfBinItems`) nem aparece.
- ⚠️ Toda operação desta seção roda com o editor olhando a tela (ver abaixo).

⭐ **No chat são três ferramentas** (`mcp/ferramentas/edicao.py`, sobre
`avid/timeline_do_editor.py`): `ler_timeline` (timecode de record, o que pende de cada clipe,
vazio fora, teto cortado no TEMPO e não por trilha), `conferir_a_edicao` (leitura: a recusa
chega antes do cartão) e `editar_timeline` (portão: confere, `CloseBin`, grava com prova,
`OpenBin`, carrega na Record; `FILE_OPEN_FAILURE` devolve a bin byte a byte).

- ⭐⭐ **Todo timecode das operações é da timeline ORIGINAL**, a que o modelo leu: elas são
  aplicadas da última posição para a primeira. **MEDIDO na `TL EDITADA`:** extrair, e depois
  "abrir espaço + inserir" com a ordem trocada, saíram com a MESMA impressão digital, trilha
  a trilha, das sequências que o editor aprovou na tela.
- ⛔ **O `inserir` escondia a transição** que vem, na lista, depois do vazio que contém o
  ponto (um `break` ao achar o lugar). A prova barrava, mas com "algo que não é vazio
  atravessa a fronteira" — medido abrindo espaço dentro de um dissolve da V3.
- ⚠️ Observado, não medido: o `CaptureMask` guarda um `Timecode` de 25 fps DENTRO dele, e a
  edição só muda o `length` de fora. Na sequência que o editor carregou e o MC salvou, o de
  dentro também encurtou (516 = 496 × 25/24) — ao que tudo indica o MC recalcula ao salvar.
  A nossa abriu e tocou sem isso.
- ✅ Rodou pelo chat com o editor olhando (2026-09-13): *"funcionou. simples e direto ao
  ponto."* ⬜ Explicar ao usuário que a bin fecha e reabre sozinha.
- ⛔ Revisão de 2026-09-13: depois do `CloseBin`, **qualquer** falha devolve a bin e
  reabre — antes só três tipos de erro eram tratados, e a cópia de segurança falhando
  deixava a bin do editor fechada na tela.
- ⚠️ **NÃO MEDIDO, e é risco:** que mensagem o `CloseBin` devolve para bin que não está
  aberta. Hoje (como no `montar_corte`) todo erro do `CloseBin` é tomado por "já estava
  fechada" e a escrita segue. Se a bin estiver aberta e o fechamento falhar por outro motivo,
  o MC salvaria por cima da edição ao fechar. Medir antes de endurecer: endurecer às cegas
  pode travar o `montar_corte` inteiro.
- ⚠️ Timecode contado SEM drop-frame; sequência 29,97/59,94 nunca passou por aqui. A leitura
  avisa.

### ⛔⛔ Carregar → consultar → fechar, colados, derruba o Media Composer

**MEDIDO em 2026-09-13, com o editor na tela:** `LoadMobsIntoViewer` → `GetViewerMobs` →
`CloseBin` sem pausa deu `ACCESS_VIOLATION` (ponteiro nulo, thread principal) **5 de 5**.
Tirando qualquer um dos três, ou com 3 s depois do carregar, **0 de 11**. A ponte
(`avid/mcapi.py`) agora segura `GetViewerMobs` e `CloseBin` por 3 s depois de qualquer
carregar, no processo inteiro — e com ela o trio passou **3 de 3**.

⚠️⚠️ **O MC não fecha, e a API não conta.** Ele mostra o diálogo e segue depois do OK; até
lá a API fica muda, e o cliente lê "ocupado". Um spike imprimiu ✅ com o MC tendo caído
duas vezes — só os prints do editor revelaram. Spike que mexe em monitor ou bin roda com o
editor olhando, e o veredito sai do `EVENTLOG.LOG` (`Public\Documents\Avid Media
Composer\Avid FatalErrorReports`, linha `FatalExcpt`), não da resposta da API.

### ⭐ Para LER, o arquivo; para escrever ou saber o que está aberto, a API

Ler a `.avb` com pyavb é instantâneo e invisível. A API custa **~500 ms por chamada** e
`OpenBin` **abre a bin na tela do editor** no meio do trabalho dele. Bin fechada devolve
`"Bin is not open."` de verdade.

### `avid/take.py` é a camada de tradução

É o que faz o Claude parar de precisar entender o Avid. Um subclipe sincronizado **mistura
dois masters** — V da câmera, A do som — e **os offsets são diferentes** (medido: imagem em
0, som em 234 frames). Por isso `imagem` e `som` são blocos separados, cada um com o seu
`inicio`: não existe lugar onde alguém pegue "o offset do take". Um valor único
dessincroniza a transcrição em ~10 s, em silêncio.

⭐⭐ **Tudo que entra na timeline como mídia é aceito no chat** (decisão do editor,
2026-09-13): **subclipe** e **master**, gerenciado ou AMA. O master é o master de si mesmo
— início 0 no tempo dele —, e por isso a regra do cache continua de pé sem caso especial.
O que não é aceito ainda volta com a frase certa (`take.RECUSAS`): **group clip**
(multicâmera), **efeito salvo na bin** (`usage_code = 3`, o preset — medido um `Color
Correction` na `BIN ORIGEM`) e **sequência**. ⚠️ Matte key de arte com alpha: nenhuma
bin do projeto tem, e ninguém mediu como ele mora na bin. A próxima fronteira declarada é
aplicar preset de efeito da bin nos clipes da timeline.

⭐ **Matte key MEDIDO na bin em 2026-09-13** (projeto `MAIS VC AUTO`, artes `.mov` com
alpha): `CompositionMob usage=effect` — o MESMO `usage_code 3` do preset — com um
`TrackEffect EFF2_BLEND_MATTE_KEY` de 3 trilhas (fundo vazio, preenchimento, alpha) apontando
um master oculto `usage=precompute`. **O que o separa do preset é haver mídia dentro**
(`take.efeito_de_chave`). Nas timelines, a arte vai em **`coberturas`** do `montar_corte`
(ancorada num corte: `sobre_o_corte` + `deslocamento_frames`), nunca em `cortes`.

⭐⭐ **Medido na timeline com uma referência feita À MÃO pelo editor** (`SEQ ANALISE`,
`spikes/a_referencia_do_editor.py`): o matte key na V2 é o MESMO `TrackEffect` do clipe da
bin. `timeline.Cobertura` copia esse efeito da bin, apara (fundo, preenchimento e alpha), põe
a V2 logo depois da V1, e leva oculto o clipe de matte key e o `precompute` — que é o que o MC
guardou. Conferido campo a campo contra a referência: igual, fora `_MATCH`, os caches de
reprodução e o XML de enquadramento que o MC acrescenta ao editar. ⛔ **Ainda não carregado
no MC.** ⚠️ Só a forma simples (preenchimento como `SourceClip` direto); efeito aninhado é
recusado. ⚠️ Arte AMA a 30p numa sequência 29,97 é recusada ("misturar taxas").

⭐⭐ **Drop-frame MEDIDO** na mesma referência: `Timecode.flags = 1` com `start = 107892`;
non-drop é `flags = 0` com `start = 108000`. O `start` já é quadro contínuo, só o rótulo muda.
Ligado: `ler_timeline`/`editar_timeline` falam `01;00;00;00` (`timeline_do_editor.Relogio`),
e as timelines que o produto grava seguem o `drop_frame` do PROJETO (`mcapi.projeto()`).
Antes, toda timeline daqui nascia non-drop.

- ⭐ **AMA: o caminho está na BIN.** Master → mob de arquivo → mob físico com
  `WinFileLocator` (`D//pasta/x.mov` → `D:/pasta/x.mov`). Só sem ele o acervo OP-Atom é
  varrido. E o arquivo AMA tem imagem e som juntos, então não há filtro de sufixo `_A01`.
- ⛔ **Pelo nome, o master ganha do mob de arquivo** — MEDIDO: os dois têm o mesmo nome.
- ⛔⛔ **Um `.mov` AMA pode ter várias pistas de áudio**, e sem `-map` o ffmpeg ouve a
  primeira. MEDIDO no RED: 4 streams mono. `midia/audio.mixar` soma todas, como já somava
  os canais OP-Atom; a saída do caminho gerenciado não mudou, e o cache sobrevive.
- ⚠️ **BRAW não decodifica no ffmpeg** (vídeo `codec_name=unknown`; o áudio sim). O take
  avisa: transcrever funciona, ver quadros não. O banco aponta o SDK Blackmagic.
- ⛔⛔ **`acrescentar_timeline` em OUTRA bin leva o fecho que falta.** MEDIDO: com
  `bin_da_sequencia` numa bin sem os masters do corte, a timeline ia pelada — e a bin abria.
