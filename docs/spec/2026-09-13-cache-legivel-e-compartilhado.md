# O cache legível, por projeto, e que pode morar na rede

**Data:** 2026-09-13 · **Estado:** decisões da Seção 9 aprovadas pelo editor; **C1 feita e
migrada** (27 de 27). C2–C4 por fazer.

> ⭐ Ajuste do editor ao aprovar: o nome é o **`material_package_name`** — o OP-Atom parte o
> clipe em vários arquivos e troca o nome deles; o nome do arquivo vai para o manifesto.
> Confirmado no banco (`protocolos/mxf/README.md`: é o nome como está na bin, editável).
> E no áudio, que não tem quadro, o lugar do fps leva a amostragem (`48kHz`).

## 1. O pedido

O editor abriu `%LOCALAPPDATA%\CicloAssist\midia` e viu 30 pastas chamadas
`060a2b3401010105…`. Ninguém administra o que não consegue ler. O pedido:

1. pasta com nome humano: `<nome>_<fps>_<tipo>_<duração>_<data-hhmmss>`;
2. uma pasta por **projeto**, para os projetos não se misturarem;
3. a inteligência de reconhecer, no projeto B, a mídia que já foi processada no projeto A;
4. um formato que possa morar na **rede** (um NAS QNAP) com **vários editores** lendo e
   escrevendo a mesma fonte. Quem lê é o app, não o Media Composer.

Refazer o cache é aceitável.

## 2. O que NÃO muda, porque cada item já custou erro

- **A identidade é da MÍDIA, não do clipe.** Processou uma vez, e masterclipe, subclipe e
  group clip acham pronto.
- **Quadro e fala no tempo do MASTER.**
- **Escrita atômica, leitura defensiva, cache corrompido vira "não tenho".**
- **O cache é guia, nunca regra** (banco, `banco-de-midias-compartilhado.md` §7): nenhuma
  rota em que ele impeça trabalho, e nunca reaproveitar na dúvida.

## 3. ⛔ O nome humano é RÓTULO, não CHAVE

O formato pedido é ótimo para ler, e insuficiente para identificar:

| o que acontece | com o nome como chave |
|---|---|
| multicâmera: câmera A e câmera B gravam `C001` no mesmo segundo, mesma taxa, mesma duração | **as duas mídias caem na mesma pasta** — a decupagem de uma vira a da outra |
| o editor renomeia o master na bin | a pasta deixa de ser achada, e tudo é reprocessado |
| nome de efeito sonoro com 150+ caracteres (medido no cache) | o caminho estoura o limite do Windows |

⇒ **A pasta ganha o nome legível no nascimento, mais um sufixo curto da identidade**, e quem
acha a mídia é o **índice** (Seção 5), nunca o nome da pasta:

```
C001_23.976_video_04m12s_20260913-162206_a3f9c1
17WT02_23.976_audio_03m46s_20260910-213402_7be210
FOTO-SET_foto_20260913-101500_c04d9e
```

- `nome`: o do master, limpo para Windows e cortado em 40 caracteres.
- `fps`: a taxa do master (`23.976`, `25`, `29.97`). Foto não tem.
- `tipo`: `video` (imagem, com ou sem som) · `audio` · `foto`.
- `duração`: `04m12s`, `1h02m03s`.
- `data`: **quando o cache daquela mídia nasceu**. ⚠️ MEDIDO: o MXF gerenciado não traz
  data de gravação (só UMIDs, `reel_name`, `timecode`, `project_name`). Onde o arquivo trouxer
  (`creation_time` do MOV), a data dele entra no manifesto, mas o nome da pasta segue uma
  regra só.
- `a3f9c1`: 6 hexadecimais da identidade. É o que separa a câmera A da B.

O nome é fixado no nascimento. Renomear na bin atualiza o manifesto, não move pasta de rede.

## 4. Pasta por projeto, e a mídia que atravessa projetos

```
<raiz do cache>\
  _ASSIST ANTERIOR\                      ← o nome da pasta do projeto do Avid
    projeto.json                      ← as mídias que ESTE projeto usa, inclusive as de fora
    C001_23.976_video_04m12s_…_a3f9c1\
      midia.json                      ← o manifesto (substitui o fonte.json)
      transcricao.json · notas.json · vetores.npy · quadros\ · gerador.*.json
  SERIE EP 12\
    projeto.json                      ← referencia _ASSIST ANTERIOR\C001_…_a3f9c1
  _banco\                             ← só com vários editores (Seção 6)
```

⭐ **A mídia mora na pasta do projeto que a processou primeiro; os outros a referenciam.**
Copiar duplicaria gigabytes (um `audio.wav` tem dezenas de MB). A aba Vetores diz
"processada em _ASSIST ANTERIOR".

⚠️ **Apagar o cache de um projeto** não apaga mídia que outro projeto usa: ela é movida para
a pasta desse outro projeto, e a tela diz quantas foram.

## 5. ⭐⭐ A inteligência: reconhecer a mídia em qualquer projeto

A pergunta é *"essa mídia já foi processada, em qualquer lugar?"*. O manifesto de cada
mídia guarda **todas as identidades** dela, e cada uma tem um peso diferente:

| identidade | vale para | decide sozinha? |
|---|---|---|
| `umid` do material, **vindo do arquivo** | mídia gerenciada (OP-Atom) e MXF profissional | ✔ sim |
| **impressão do conteúdo**: tamanho + hash dos primeiros e últimos 4 MB | AMA (MOV, BRAW, WAV) | ✔ sim |
| arquivo: rótulo do volume + caminho relativo + tamanho + `mtime` em segundos | todas | só junto de outra |
| nome normalizado + duração + espécie | todas | ✘ **nunca** — só candidato |

⛔⛔ **Por que o UMID sozinho não basta, e é um defeito que o cache de hoje TEM:** em mídia
AMA sem UMID no arquivo, o Avid **gera o `mob_id` a cada link** — o banco mediu **83 de 118
masters** com `mob_id` novo depois de um relink. O cache de hoje é endereçado por esse id
nos AMA: a mesma `.mov` linkada noutro projeto é **outra pasta**, reprocessada sem aviso.
(A pasta `000057415645…` do cache atual, fora do prefixo SMPTE, tem cara de ser um desses —
confirmar na fase C3.) A impressão do conteúdo lê 8 MB por arquivo, mesmo pela rede, e não
depende do Avid.

⚠️ **Nome + duração nunca reaproveita sozinho.** Um reaproveitamento errado anexa a
decupagem de uma mídia a outra, e a busca aponta o plano errado para sempre, sem erro
nenhum. Havendo só essa pista, a mídia é processada de novo.

## 6. Na rede, com vários editores

⛔ **Nada de banco SQLite (nem LanceDB ou sqlite-vec) como FONTE DA VERDADE numa pasta de
rede.** O próprio SQLite avisa que o travamento de arquivo em sistemas de rede é
não confiável e corrompe o banco. O tópico 6 do documento de IA local sugere esses bancos
**no Mac mini**, como índice local de uma máquina — e aí servem bem.

O desenho, que já funcionou no De Lá Pra Cá (banco §4):

| peça | onde | quem escreve |
|---|---|---|
| **manifesto e resultados por mídia** (a verdade) | NAS, na pasta da mídia | uma máquina por vez, escrita atômica |
| **fragmento de anúncio** `_banco\fragmentos\<máquina>.jsonl` | NAS | cada máquina só o seu, só acrescenta |
| **índice de busca** (identidades → pasta, e os vetores) | disco LOCAL de cada máquina | derivado; reconstruído varrendo manifestos e fragmentos |
| **marcador `trabalhando.json`** (máquina + hora, expira em 30 min) | NAS, na pasta da mídia | quem começou a processar |

- Dois editores pedindo a mesma mídia: o segundo vê o marcador e espera ou pula. Se o
  marcador falhar (SMB), o pior caso é trabalho dobrado — a escrita é atômica e o resultado
  é equivalente.
- O temporário da escrita atômica leva **máquina + PID** no nome e nasce na pasta de
  destino (`os.replace` só é atômico no mesmo volume).
- `mtime` em segundos inteiros: exFAT e SMB divergem no sub-segundo.
- ⚠️ Caminho lido do NAS é entrada de rede: validado antes de chegar ao ffmpeg.
- **Quando houver muitos editores escrevendo ao mesmo tempo**, o banco de verdade é um
  PostgreSQL com pgvector no próprio QNAP (Container Station). É aí que ele se paga, e vira
  ADR quando chegar.

## 7. Migrar, não refazer

O cache de hoje tem **27 mídias e 149 MB**, com transcrições e 7 decupagens do Claude. A
migração não reprocessa nada: lê `fonte.json` e `gerador.*.json`, calcula o nome, move a
pasta para `_ASSIST ANTERIOR\`, grava o manifesto com a identidade que já existe. A pasta
antiga fica até o editor conferir.

⭐ **E ela vem ANTES do lote de decupagem no Mac.** As 165 decupagens nascem na estrutura
nova, em vez de serem migradas depois.

## 8. Fases, cada uma com o critério de passagem

| fase | entrega | passa quando |
|---|---|---|
| **C1** | manifesto `midia.json`, nome legível, índice local; ainda sem projeto | todo o produto funciona igual (suíte verde) e as 27 migradas abrem na aba Vetores com nome legível |
| **C2** | pasta por projeto + `projeto.json` + referência entre projetos | mídia de A pedida em B é achada sem reprocessar; apagar A preserva o que B usa |
| **C3** | impressão do conteúdo para AMA | MEDIR antes: o mesmo `.mov` linkado em dois projetos ganha `mob_id` diferente? Se sim, o cache novo acha; o velho não |
| **C4** | NAS: fragmentos, marcador de trabalho, índice reconstruído | dois processos no mesmo cache em rede, a mesma mídia pedida pelos dois: processada uma vez |

## 9. Decisões para o editor

1. **Nome legível + sufixo curto da identidade** (Seção 3), em vez do nome puro.
2. **A data é de quando o cache nasceu**, porque o MXF gerenciado não traz a de gravação.
3. **Mídia de dois projetos fica na pasta do primeiro**, e o segundo referencia (sem cópia).
4. **Arquivos na rede + índice local por máquina**, sem SQLite no NAS.
5. **Migrar as 27 mídias** e só depois disparar o lote do Mac.
