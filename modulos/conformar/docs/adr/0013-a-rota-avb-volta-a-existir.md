# 0013 — A rota `.avb` volta a existir: relink pela bin, sem AAF

**Status:** **implementada no produto** (2026-08-16, a pedido do usuário) · medida e
validada na tela pelos spikes · Data: 2026-08-16
**Emenda o** [ADR 0002](0002-relink-por-aaf-via-linkfile.md), que segue **ativo**.

---

## O que o ADR 0002 comparou, e o que ele não comparou

O 0002 pôs duas rotas na balança:

| | rota AAF | rota `.avb` |
|---|---|---|
| quem monta a timeline | o Media Composer | nós (`build_avb`) |
| efeitos | intactos por construção | Titler+, FrameFlex e Matte Key dropam |

A coluna da direita é **reautoria**: `build_avb` reconstrói a timeline segmento a
segmento, e é por isso que efeito se perde. A conclusão estava certa para o que foi
comparado.

⭐ **Existe uma terceira rota, que ninguém comparou: editar a bin que o Media Composer
escreveu.** Não se reconstrói nada — a composição continua sendo a dele, e só as
referências de MobID mudam. Os efeitos sobrevivem pelo mesmo motivo que na rota AAF:
não passamos perto deles.

Ela não foi avaliada em 2026-08-10 porque o banco de NLEs registrava, como `confirmado`,
que **o MC recusava qualquer `.avb` regravada pelo pyavb** (`FILE_OPEN_FAILURE`) — o que
tornava "editar a bin" impossível por definição.

## Por que ela estava fechada, e não estava

**Esse fato estava errado na atribuição.** O experimento que o gerou mudou duas variáveis
de uma vez: a via de escrita **e** o `Bin.uid` (o resave cru preserva o UID de origem; o
`build_avb`, que funcionava, randomiza). Matriz que separa as causas — MC 25.6/Windows,
bin real de 1,9 MB e 648 mobs:

| | bin original ABERTA | bin original FECHADA |
|---|---|---|
| **UID preservado** | ❌ `FILE_OPEN_FAILURE` | ✅ abre |
| **UID randomizado** | ✅ abre | ✅ abre |

⭐ A prova decisiva: com o resave de mesmo UID aberto, **a bin ORIGINAL passou a ser
recusada** — o arquivo que o próprio MC escreveu. A recusa acompanha a **identidade da
bin**, não o arquivo. É o problema clássico de troca de bins entre editores, não um
defeito do writer. (Hipótese levantada pelo usuário antes da medição.)

## O que foi medido

Curta real, timeline de 26'28" — 1118 clipes, 877 SourceClips, 83 mobs referenciados,
44 subclipes, 80 masters. Originais BRAW + WAV de som direto.

```
1. resave da bin do editor com Bin.uid NOVO        → bin de trabalho
2. OpenBin
3. LinkFile dos originais COM destination_bin = a bin de trabalho   (44/44, 171 s)
4. DoCommand(1004 Save)
5. ACHATAR os subclipes (738 achatados, 44 → 0), DEPOIS repontar (123)
6. resave com OUTRO Bin.uid novo                    → bin final
7. OpenBin
```

**Verificado na tela por um editor:** vídeo **online, sem subclipe, efeitos mantidos**.

⭐ **Contagem cruzada como prova do porte:** o achatamento em AVB deu **738/44** —
exatamente o que o [ADR 0006](0006-achatar-subclipes-antes-do-importfile.md) registra
pela rota AAF na mesma timeline. Dois caminhos independentes, o mesmo número.

## As três condições, cada uma um fracasso antes de virar regra

1. **`Bin.uid` novo em toda gravação.** Sem isso o MC recusa enquanto houver bin de mesmo
   UID aberta.
2. ⭐⭐ **Masters AMA e timeline na MESMA bin.** A 1ª tentativa deixou os masters numa bin
   e a composição noutra, contando que o MC resolvesse por MobID no banco de mídia:
   **timeline 100% offline**, com o `LinkFile` reportando 44/44 online e o `OpenBin`
   reportando OK. Isso vale para mídia **gerenciada**; num master **AMA** o caminho do
   arquivo mora na bin. O `relink.py` da rota AAF **já fazia certo** — `LinkFile` e
   `ImportFile` recebem o mesmo `bin_rel` — e eu separei o que ele mantinha junto.
3. ⭐⭐ **Achatar é obrigatório para o relink, não só contra o diálogo de conflito.**
   Repontar o master **dentro** do subclipe não basta: 60 SourceClips passaram a apontar
   para masters AMA comprovadamente online (imagem no Source monitor) e a timeline
   **continuou vermelha**. O ADR 0006 justifica o achatamento pelo modal de conflito no
   reimport; esta medição acrescenta um segundo motivo, independente e mais duro.

## O que isto muda, e o que não muda

**Passa a ser possível** relinkar sem `ExportFile`, sem preset de export e sem
`ImportFile` — some a dependência do `Settings.xml` do editor
([ADR 0009](0009-preset-de-export-embarcado.md)) e some o passo de import.

**Não muda:** a metade de casamento do motor. `casar_masters` consome objetos `Master`
(`nome`, `mob_id`, `segmentos`, `duracao_frames`, `edit_rate`) e **nada nele é de AAF** —
a rota bin não precisa de matcher próprio, precisa de um `masters_em_uso` que leia `.avb`.
O que muda entre as rotas é só o **leitor**.

**O bloqueador de áudio existe — e foi CONTORNADO.** `LinkFile` de WAV com start time abre
o modal `Audio Start-Time Options` e **congela a API inteira**; o `OK to All` não segura,
porque a API linka **um arquivo por chamada** (`file_path` é `string`, não repetido) e cada
`LinkFile` é uma operação isolada. Isso atinge as duas rotas igualmente — é limite de
plataforma, não de método.

⭐⭐ **A saída (ideia do usuário, medida e validada na tela em 2026-08-16): autorar os
masters AMA de ÁUDIO por fora e deixar só o VÍDEO com o `LinkFile`.** Áudio tem poucos
formatos — medido neste acervo, **85/85 WAVs em 5 combinações**, todas com template
embarcado em `motor/avb_export/templates/` — enquanto vídeo tem dezenas de codecs. Autora-se
o lado fechado e delega-se o aberto.

Resultado do ciclo completo: **44 BRAW pelo `LinkFile` + 36 WAVs autorados + 738 subclipes
achatados + 738 SourceClips repontados**, tudo numa bin só, **vídeo e áudio ONLINE e nenhum
diálogo em nenhum momento**.

⭐ E o ganho não é só evitar a janela: ela existe porque o start do BWF é um número **sem
base**, e respondê-la na mão **não deixa rastro**. Autorada, a escolha vira um valor
explícito e testável — que é o padrão deste projeto.

As quatro peças que precisaram estar certas ao mesmo tempo (cada uma falha em silêncio) e a
armadilha de medição que invalidou três rodadas estão em
`bancodedadosnles/protocolos/avb/escrita.md` §"ÁUDIO AMA AUTORADO POR FORA". A decisiva é a
**forma do caminho**: o Avid grava caminho de Windows como `E//A/B/x.WAV` (letra + `//` +
barras normais), e o clone gravava `E:\A\B\x.WAV` — arquivo existindo, mtime batendo,
descriptor idêntico ao do MC, e **offline por três caracteres**, porque o clone nasceu no
macOS.

## Custos e limites conhecidos desta rota

- `LinkFile` para dentro de uma bin GRANDE: **3887 ms/arquivo** contra **454 ms** numa bin
  vazia (8,5×). Não medido se dá para linkar numa bin pequena e juntar depois.
- Validado com **vídeo** (44 BRAW). Áudio bloqueado pelo modal; drone (`.mov`/`.mp4`) não
  testado — a instalação de MC usada tem defeito de AMA para mp4.
- Escrito como **spike** (`.dev/spike_c3_achatar.py`), não como código de produto: o
  achatamento em AVB não cobre group clip/multicam, e não há regressão nenhuma sobre ele.
- Os subclipes órfãos **não são removidos** da bin (a rota AAF os remove, pelo motivo do
  ADR 0006). Aqui não há import, então não há conflito — mas eles ficam no arquivo.

## Decisão

**A rota `.avb` passa a ser a preferida quando dá para achar a bin da timeline; a rota AAF
continua inteira como plano B.** (Decisão do usuário, 2026-08-16, depois de ver o ciclo
completo funcionar na tela.)

Quem escolhe é o serviço, não o editor: `POST /trabalho/preparar` com um
`sequence_mob_id` tenta `GetBinFromMob` — **uma** chamada. Achou a `.avb`, usa a rota nova;
não achou, cai na AAF sem avisar ninguém. `{"rota": "aaf"}` no corpo força a antiga.

### Onde isso mora

    motor/avb_bin/            percurso · masters · denest · remap · audio
    servico/relink_avb.py     a aplicação (as 8 etapas acima)
    servico/relink.py         `Trabalho.rota` e `bin_origem`; o leitor despacha em `preparar`
    servico/avid/mcapi.py     `bin_do_mob()` — `GetBinFromMob`
    tests/test_avb_bin.py     29 casos, com dublês: roda sem MC e sem mídia

⭐ **A metade de casamento não mudou uma linha.** `casar_masters` consome objetos `Master`
e nada nele é de AAF — o `motor/avb_bin/masters.py` devolve os mesmos objetos. Entre as
duas rotas muda o **leitor** e o veículo de volta, não o cérebro.

⚠️ **O pacote não pode se chamar `avb`**: esse é o nome do pyavb, e um pacote local com
esse nome o sombreia — `from avb.core import …` dentro de `avb_export/translate.py` passa a
resolver para ele e o `avb_export` inteiro deixa de importar. Daí `avb_bin`.

### O que ainda não foi verificado

O ciclo foi validado **pelos spikes**, com o editor conferindo na tela. O código de
produto que os substitui **não rodou contra o Media Composer** — foi escrito com o MC
fechado. A regressão (160 casos) cobre percurso, masters, achatamento, repontamento e as
conversões do áudio, mas **nenhum teste alcança o `LinkFile`, o `OpenBin` ou o online**.
A primeira execução com o MC aberto é uma verificação real, não uma formalidade.

Pendências herdadas dos spikes: o achatamento em AVB **não cobre group clip/multicam**; o
patch do start do BWF segue atrás de `AVB_AUDIO_TC=1`; e formatos de áudio sem template
embarcado são **pulados de propósito** (um descriptor errado toca deformado, o que é pior
que offline) — eles aparecem em `audio_sem_template` no resultado.
