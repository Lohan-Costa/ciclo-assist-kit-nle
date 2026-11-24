# O cache (UMID do master) e o quadro N/2 da busca rápida

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### ⭐ O cache é endereçado pelo UMID do MASTER

Regra herdada de um módulo que rodou em produção, e ela vale para quadros **e** transcrição:

> O hash do arquivo exige ter o arquivo; **o UMID vem de dentro do clipe**. Processou uma
> vez, e qualquer clipe que use aquele material acha pronto — masterclipe, subclipe,
> **groupclipe (multicam)**, e subclipe criado DEPOIS.

E o segundo lado: **quadro e fala são numerados no tempo do MASTER**, nunca no do subclipe.
Numerar em tempo de subclipe faria o mesmo quadro ser extraído uma vez por recorte — o
cache *pareceria* funcionar sem nunca acertar.

⭐⭐ **Desde 2026-09-13 a PASTA tem nome de gente** (spec
`docs/spec/2026-09-13-cache-legivel-e-compartilhado.md`, fase C1 feita):
`C001_23.976_video_04m12s_20260913-162206_a3f9c1` — o `material_package_name` (o nome da
bin; os `A01.<hash>.mxf` do OP-Atom vão para o manifesto), a taxa (`48kHz` no áudio), o
tipo, a duração (`8f` abaixo de 1 s), quando o cache nasceu, e 6 hex do hash da chave.

- ⛔⛔ **O nome é RÓTULO; a identidade é o `midia.json`.** Câmeras A e B com `C001` no
  mesmo segundo teriam o mesmo nome. Quem acha a mídia é o índice (`cache.indice`), que lê
  manifestos; `cache.todas()` é a ÚNICA forma de listar o cache (eram seis `iterdir` com
  seis critérios de "é mídia").
- ⛔ **Ler nunca cria pasta.** `Midia.arquivo(nome)` é para ler; `Midia.pasta` faz nascer
  e é só para escrever. `Midia(…, rotulo=take.rotulo(fonte))` batiza; sem rótulo, o
  acervo batiza.
- ⚠️ A sonda do acervo (v3) passou a ler duração e amostragem do ÁUDIO: até a v2 todo
  OP-Atom de som tinha duração ZERO (medido: 236,236 s no `C7 P2-T002`).
- Migração: `python tools/migrar_cache.py [--fazer]`, serviço parado. **Feita em
  2026-09-13: 27 de 27**, sem reprocessar; as antigas em `_antes_da_migracao\`. Conferido
  depois: aba Vetores com os mesmos números, busca, parecidos e as transcrições da C07.
- ⬜ C2 (pasta por projeto), C3 (impressão de conteúdo para AMA), C4 (NAS).
- ⛔ Revisão de 2026-09-13, três defeitos do C1 achados antes de alguém usar:
  (1) o índice nunca relistava pasta de projeto já vista — mídia de outro processo ficava
  invisível até reiniciar; (2) `Take.rotulo` comparava a `Fonte` por OBJETO, e a diária de
  câmera transcrita antes de olhada nasceria `…_audio_`; (3) a migração, ao falhar com
  `FileExistsError` (que é `OSError`), apagava a pasta que JÁ existia no destino.
- ⚠️ Mídia que ainda não existe relistava a raiz a cada pergunta; agora a leitura relista
  no máximo a cada `RELISTAR_S` (2 s), e o NASCIMENTO confere sempre (pasta duplicada é o
  pior erro).

```
%LOCALAPPDATA%\CicloAssist\midia\<nome legível>\
    midia.json ← o MANIFESTO: chave, identidades, nome, arquivos, fonte
    notas.json · transcricao.json · audio.wav
    vetores.npy · vetores.json ← o embedding de cada quadro amostrado, e as posições
    gerador.<estágio>.json     ← assinatura; mudou a receita, o cache velho cai sozinho
    quadros\00001357.jpg       ← posição em tempo do MASTER

%LOCALAPPDATA%\CicloAssist\midia\sondagem.json  ← o que o ffprobe já leu de cada arquivo
%LOCALAPPDATA%\CicloAssist\midia\acervo.json    ← os clipes que cada varredura achou
%LOCALAPPDATA%\CicloAssist\modelos\             ← o modelo de imagem; FORA do cache
```

Cache corrompido vira "não tenho isso", nunca exceção: reprocessar custa segundos, estourar
custa a conversa do editor.

⛔⛔ **E uma `notas.json` em LISTA crua derrubava a aba Vetores inteira.** O nosso
`tools/consertar_quadros.py` a regravou assim em 17/09 (em vez de `{"notas": [...]}`), e
`ler_notas` fazia `.get` na lista: 500, "0 mídias" com o disco cheio. Achado do lado do
**Assist anterior**, que compartilha este cache (17 de 172 lá); reproduzido aqui em 20/09,
**4 de 332**. Consertados os DOIS lados — o leitor aceita os dois formatos (nenhum arquivo
do cache foi tocado) e o gravador voltou ao formato de sempre. ⚠️ A lição é a do módulo:
quem grava no cache grava pelo caminho de `Midia`, não por um `json.dumps` à parte.


## ⛔⛔ O quadro que a busca rápida entregava era o N/2

MEDIDO em 2026-09-17, nos OP-Atom **MPEG-2** que o transcode do Media Composer gera: o
`r_frame_rate` vem pela METADE do `avg_frame_rate`, metade dos quadros não tem `pts`, e
`ffmpeg -ss t` entrega **o quadro N/2** — de outro ponto do clipe, sem erro nenhum. Dobrar o
tempo não conserta (erra perto do fim).

`frames.busca_confiavel()` reconhece o arquivo e `frames.extrair_varios()` decodifica em
ORDEM, numa passada só para todas as posições pedidas (0,9 s num clipe de 51 s). Quem pede
vários quadros passou a pedir de uma vez — um `extrair` por quadro decodificaria o clipe
inteiro a cada um. `tools/consertar_quadros.py` limpou o que já estava errado nesta máquina:
**17 mídias, 102 quadros**, e as 17 decupagens feitas sobre eles foram para
`notas_suspeitas.json` (não apagadas: descrevem quadros reais, do lugar errado).

⛔⛔ **E rodar essa ferramenta DE NOVO jogava fora trabalho certo** (revisão de 2026-09-22).
Ela marca a mídia cujo ARQUIVO tem busca não confiável — e isso não muda nunca —, mas o que
foi extraído depois do conserto sai EM ORDEM, e a decupagem feita sobre ele foi paga com a
assinatura do editor. MEDIDO hoje: as mesmas 17 mídias, agora com **234 quadros bons e 13
decupagens boas**, e `--fazer` teria levado os dois. Ela passou a só mexer no que é anterior
a `CONSERTO` (2026-09-17, com `--desde` para mudar), a apagar os quadros **um a um** (a
pasta pode ter novos ao lado dos velhos) e a preservar as notas posteriores. Hoje ela diz
*"0 mídias a consertar; 17 de busca não confiável já estão em dia"*.
⚠️ A lição é da classe: **ferramenta de conserto único parece idempotente e não é** — o
critério dela é uma propriedade do ARQUIVO, e o defeito era do CÓDIGO que já foi consertado.
