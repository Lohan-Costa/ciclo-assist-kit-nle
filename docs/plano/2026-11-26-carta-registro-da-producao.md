# A Carta como registro de mídia da produção, o navegador no molde do Job Manager e o conform pelo mapa (2026-11-26)

Conversa de planejamento com o autor (2026-11-26). Página: https://claude.ai/artifact/LXUPmRUfREbnSNv8ETeb6R. Junta e substitui o plano da manhã
(`2026-11-26-conformar-premiere-pela-carta.md`, que vira a etapa 1 daqui). Nada de código até o autor aprovar a ordem.

## A visão (decisão do autor)

Quando o fluxo é nosso do ingest ao online, nós sabemos para onde cada mídia foi convertida, os caminhos e os metadados.
A Carta guarda isso e o conform deixa de varrer pasta de bruto: ele já tem o mapa. O De Lá Pra Cá continua para o que
não passou por fluxo nosso — e, dentro dos projetos nossos, para o clipe que ficou fora do mapa (trilha, arte, arquivo
puxado de fora).

## Decidido

1. **A pasta é a bin.** As pastas do editor, reais no Finder/Explorer, organizam; cada mídia (`.ref.json`) e cada
   timeline/subclipe (`.item.json`) continuam um arquivo pequeno. Sem banco fechado; sem trava (dois assistentes em
   mídias diferentes nunca brigam). Na janela a pasta aparece como bin.
2. **Produção = uma pasta com `.carta/`; sub-projetos dentro dela** (episódio, rolo, entrega, sessão do colorista) com
   a sua `.carta/`, que **enxergam as mídias da produção de cima** (como o MediaFiles do MC: a mídia é da produção, as
   bins são de quem trabalha). Abrir uma pasta mãe mostra todas as Cartas debaixo dela, separadas.
3. **O navegador substitui a janela atual da Carta**, no molde do Job Manager do Baselight e do Finder em colunas:
   lateral com os **Locais** (pastas salvas e volumes, como Favoritos/Localizações); **colunas** que começam onde o
   editor abriu (a raiz de um volume ou uma pasta funda) e andam para a direita; **barra de caminho** embaixo das
   colunas (de onde veio, voltar a um clique); **painel de detalhe** embaixo, do que está selecionado.
4. **Hash em dois níveis:** a impressão rápida (`midia/identidade.impressao`: SHA-256 do tamanho + começo + fim, já
   existe) no dia a dia, para achar cópias movidas fora do nosso controle; o hash completo só no ingest, lido do **MHL**
   do DIT quando houver. O hash reforça a identidade (TC, UMID), não a substitui: proxy e MXF gerenciado têm outro hash
   e são o mesmo material.
5. **Os metadados voltam como anexo por destino** (ALE para o Avid, CSV/XMP para o Premiere, o CSV do Resolve, a lista do
   VFX), **sem regravar a mídia**.
6. **Mapa × casamento discordam:** alerta, e o editor decide (a regra do empate).

## O modelo de dados (o que entra na Carta)

| fato | o que diz | quem grava |
|---|---|---|
| `forma` (existe) | onde está UMA forma (original, trabalho, avid) de UMA mídia, NESTA máquina | anexar, mandar |
| `impressao` (novo) | a impressão rápida e, quando houver, o hash completo (com a origem: MHL ou calculado) | anexar, ingest |
| `relacao` (novo) | o arquivo Y saiu do X com a transformação Z: deslocamento de TC, taxa, enquadramento (escala, tarja, corte), trecho do original, mapa de canais | as conversões do app (`converter_para_proxy`, OP-Atom), JSON manual |
| `sincronia` (novo) | o vídeo A com o áudio B, deslocamento, método (TC, claquete, forma de onda), confiança, quem confirmou | o Preparar (sync, subclipe) |
| `metadado` (novo) | o que o arquivo de câmera diz, cru (ARRI, RED, BRAW…: lente, ISO, câmera…), por plano; o por quadro lido do original quando pedirem | ingest |
| `nota` (novo) | metadado editorial: continuidade, comentários, markers — com máquina, hora e histórico | mandar da timeline/bin |

Tudo no diário que só acrescenta (um arquivo por máquina): mudar é uma linha nova, o histórico fica, conflito aparece.

## As etapas (cada uma útil sozinha)

| # | etapa | o que entrega |
|---|---|---|
| 1 | O Conformar monta no Premiere pelo escritor da Carta | rampa, congelado, transição e título sem marcador (plano da manhã) |
| 2 | A relação entre as formas + a impressão na referência; as conversões do app gravam a relação | o par original ⇄ convertido com a transformação, sem dedução |
| 3 | O conform pelo mapa, clipe a clipe; o De Lá Pra Cá completa o resto | conform sem varrer pasta; alerta quando o mapa não confere |
| 4 | Os fatos de sincronia do Preparar | o casamento som/imagem sobrevive ao projeto perdido |
| 5 | O navegador (Locais, colunas, barra de caminho, painel) e os sub-projetos | várias produções lado a lado, cada uma separada |
| 6 | O metadado de câmera, cru, no ingest | lente e captação guardadas para o VFX |
| 7 | O metadado editorial (markers, comentários) | a continuidade do assistente no registro |
| 8 | Os anexos por destino (ALE, CSV, VFX) | o metadado volta ao convertido sem tocar a mídia |

## Em aberto

- **A tabela de metadados** no navegador: (a) a bin vira tabela (colunas escolhidas e salvas por bin, como a bin do MC
  em texto); (b) o painel de baixo com abas (Identidade · Formas · Relações · Câmera · Editorial · Histórico); (c) os
  dois. Esboço navegável de cada um, com dados reais da PRODUCAO-A, quando chegar a etapa 5.
- **Permissões** de leitura, escrita e visualização por pasta: desejo futuro; o desenho em arquivos e pastas permite.
- **Índice** para consultar rápido com dezenas de milhares de mídias: um SQLite que se reconstrói dos arquivos (nunca a
  verdade).
- **A ordem das etapas**: a proposta acima põe a tradução (1) e o mapa (2–3) antes do navegador (5).
