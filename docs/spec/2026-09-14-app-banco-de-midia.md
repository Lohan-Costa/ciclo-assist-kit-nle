# O app standalone: o banco de mídia do Ciclo Assist

> **Estado: planejamento EM ABERTO (2026-09-15).** Decisões do editor tomadas em sessão de
> perguntas; nada implementado. O editor ainda não decidiu se o app segue este caminho — o spec e
> o canvas estão guardados para revisitar, não aprovados.
>
> **Canvas:** https://claude.ai/artifact/JCuLzQPQNKoZZQmyGkRpLt (12 telas, versão MVP enxuto).
> Fonte em `docs/design/banco-de-midia/` — `python3 gerar.py` regera as pranchas.
> Perguntas abertas no canvas: o nome da segunda busca ("Busca inteligente" é provisório) e se o
> inspetor à direita fica, recolhe ou sai do MVP.

## Contexto

Até aqui o Ciclo Assist é um plugin do Media Composer: um serviço Python (127.0.0.1:7824) que
serve o painel, expõe o MCP e orquestra o `claude -p`. Falta a outra face: um **app standalone**
que abre quando o serviço sobe e cuida de **gerenciar e processar mídia sem depender de NLE** —
watchfolder, todas as mídias processadas independente de projeto ou programa, anotação manual
(pessoas, personagens, locais, características — o que só quem conhece o material sabe), chat
com o modelo à esquerda e pool de mídias no centro. É um **banco de mídia**: conhece material
que ainda não foi importado em NLE nenhum.

Ele serve **dramaturgia, documentário (entrevistas e material de arquivo) e captação bruta**.
Casos que dão a medida da ambição (v2, sobre o banco da v1):

- ingerir todos os capítulos de uma novela e montar o **compilado dos momentos em que um
  personagem diz um bordão**;
- a partir de um **roteiro**, propor imagens que o editor importa no NLE **já organizadas e
  decupadas** — operação parente do Eddie
  (`bancodedadosnles/plugins/premiere-cep/eddie-ai-arquitetura.md`).

⭐ **O formato do banco nasce na v1 pronto para merge, variações e vínculo**, mesmo com essas
telas ficando para depois: identidade por conteúdo, procedência em todo item, histórico em vez
de sobrescrita. Retrofitar isso num banco de 2.000 h já processado é o erro caro.

## Decisões do editor

| # | decisão |
|---|---|
| 1 | **Banco PORTÁTIL**: máquina única, HD copiado para outro editor, ou NAS da equipe. Move-se e **reconecta mídia que mudou de lugar** (nome, extensão, timecode, duração…), numa ação **guiada pelo usuário** — como o relink do Premiere e do Resolve. |
| 2 | **Dois tipos de banco, MESMA estrutura** (modelo Premiere Productions): **LOCAL** — a pasta, sem permissões, copia-se para qualquer lugar sem amarras; **REMOTO** — banco especial com um processo dono que faz valer as permissões. Local **importa-se e soma-se** a um remoto (que guarda a cópia); remoto **exporta-se como local**, cópia livre das regras. |
| 3 | **Um banco remoto serve várias máquinas ao mesmo tempo**, leitura e escrita. **Permissões previstas desde já**: ler / escrever / excluir / administrar, para todos ou por usuário. Como o banco sabe quem é quem: **decidir neste spec, na fase do remoto**. |
| 4 | **Merge de bancos**: somar o que um editor processou ao banco geral **sem perder trabalho**; em conflito, o usuário compara e escolhe qual decupagem/transcrição fica. |
| 5 | **Não é só dramaturgia**: documentário (entrevistas + arquivo) e captação bruta. Capítulos finalizados **e** brutos. |
| 6 | **Avid MediaFiles é um caminho ESPECIAL, separado.** Só o MC tem mídia gerenciada; lá vivem OP-Atom (uma trilha por arquivo) e OP1a (arquivo inteiro), com codecs **previsíveis**. Todo o resto é mídia não gerenciada, com qualquer codec. Os dois cenários não se misturam. |
| 7 | **Proxy e variações**: achar o original e suas versões convertidas. Proxy = mídia 1:1 do original (TC, duração, nº de quadros, imagem), só menor em janela e/ou em codec típico (H.264, ProRes Proxy, DNxHD LB). Pistas: sufixo `_proxy`, pasta `proxy` em algum ponto do caminho — ou só a comparação. |
| 8 | **Vínculo de mídias (futuro, importante)**: casar o vídeo da câmera com o som direto, para a frase vir com a imagem E o som bom. Primeiro a partir dos NLEs (timelines de sync de diárias, subclipes do Órbita = `DRAMASYNC/`) virando **metadado de par** no banco; sync próprio depois. |
| 9 | Personagem: **só anotação e roteiro**. "Nunca pelo rosto" continua, e nada de voz. |
| 10 | Destinos: **Avid, Premiere, Resolve e prévia em MP4**. |
| 11 | **Nasce interno, vira produto** — nada que impeça instalador e licença depois. |
| 12 | **Cada máquina processa conforme aguenta** (perfil); o pesado vai a um processador da rede se houver; sem ele, roda devagar ou é pulado **dizendo a etapa**. |
| 13 | Escala do primeiro caso real: **mais de 2.000 h**. |
| 14 | Tema: **só claro**, guiado pelo MSYNC. |
| 15 | **v1 = o banco em si**: ingerir (watchfolder), identificar, reconectar, anotar, buscar, mandar ao NLE. Os casos da novela vêm em cima. |
| 16 | Decupagem visual **sob demanda** (retrieve then rerank); o que foi decupado fica. |
| 17 | **Claude conversa, Ollama processa.** Chat com Ollama só depois de medido (M2 de `2026-09-13-servidor-de-percepcao-mac.md`). |
| 18 | **O painel do MC lê o mesmo banco** — a aba Busca IA continua no plugin; o app é onde se gerencia, processa e anota. |
| 19 | **As mídias são uma LISTA com a árvore dentro** (estrutura da lista do Premiere): coluna de rótulo de cor antes do nome (pode ficar vazia), pastas que abrem no lugar; toda outra coluna **redimensionável** e **ordenável por clique** (de novo: inverte). Arrastar uma pasta da lista ao chat recorta a busca nela. |
| 20 | **Duas buscas**: (1) filtro de metadados, simples; (2) **busca inteligente** que responde na própria lista, sem ir ao chat — a árvore se reduz ao que casa e cada mídia abre os momentos achados. |
| 21 | **MVP enxuto (2026-09-15)**: saem player, timeline, collect e envio direto pela IA — desenhados e guardados como ideia, fora do MVP. A grade de miniaturas também sai: a lista é a vista. |

## Arquitetura

### O banco é uma pasta, e a mídia é referenciada por identidade

- Pasta autocontida: manifestos, derivados (quadros, fala, vetores, decupagem), anotações,
  entidades, vínculos, histórico. `cache.Midia` já aceita qualquer chave de 64 hex.
- **Identidade**: UMID quando houver; senão tamanho + hash de 4 MB do início e do fim (fase C3
  de `2026-09-13-cache-legivel-e-compartilhado.md`). **Último lugar visto** = rótulo do volume +
  caminho relativo. Caminho absoluto nunca é identidade.
- **Reconectar**: o usuário aponta uma pasta; o hash decide sozinho; nome, extensão, TC e duração
  só propõem candidatos para ele confirmar (hierarquia de pesos em
  `bancodedadosnles/transversal/banco-de-midias-compartilhado.md`).

### Local × remoto

- Formato em disco único. O **local** é lido e escrito direto na pasta pelo app de quem o abriu —
  um escritor por vez; é o caso "HD mandado a outro editor".
- O **remoto** é a mesma pasta atrás de um **servidor do banco** (NAS ou Mac mini): todas as
  escritas passam por ele, que confere a permissão e registra o autor.
  ⚠️ A pasta do remoto não pode ficar gravável por fora do servidor — quem fecha essa porta é o
  controle de acesso do NAS; sem isso, permissão é etiqueta.
- **Importar local → remoto é o merge**; **exportar remoto → local** é copiar tirando usuários e
  permissões. Mesmo código — por isso o merge fica perto do núcleo.
- No remoto quem serializa é o servidor; a receita de fragmentos por máquina
  (`_banco/fragmentos/<máquina>.jsonl`, fase C4) serve à leitura direta e ao histórico.
- ⬜ Identidade de usuário (cadastro no banco × usuário do sistema × outra) — decidir na F10.

### Merge

- Mídia que só existe num lado entra. A mesma mídia (mesma identidade) nos dois lados funde por
  item: **anotação manual soma**; transcrição e decupagem divergentes viram **conflito para
  revisar lado a lado**, com a procedência de cada uma (receita, modelo, data, máquina, quem).
- ⛔ Nada some: a versão que perde vai para o histórico.

### Duas portas de entrada, um motor

- **Gerenciada (Avid MediaFiles)** — o que existe em `midia/acervo.py`, isolado como módulo
  próprio: varre só `MXF` e `UME` (nunca `MXF-<projeto>`, offline de propósito; caixa ignorada —
  há `Avid Mediafiles` em produção), agrupa OP-Atom pelo `material_package_umid`, trata OP1a
  como arquivo único, resolve pelo `.pmr` quando houver
  (`bancodedadosnles/protocolos/msm/pmr-fmid.md`: 0,3 s contra ~56 s), e conhece a lista fechada
  de codecs do Avid — codec fora dela é sinal de problema, não de variedade.
- **Não gerenciada (todo o resto)** — `ffprobe` genérico, qualquer codec, imagem e som no mesmo
  arquivo com várias pistas (`audio.mixar` já soma), identidade por conteúdo, e aviso honesto
  quando o ffmpeg não decodifica (BRAW: transcreve, não vê quadros).
- Depois da porta — quadros, fala, vetor, decupagem, anotação — é o MESMO motor.

### Família de mídia: original + variações

O proxy tem outro hash, então variação **não é identidade**: é um vínculo com procedência e
confiança.

- Candidatos por pista barata: sufixo `_proxy`, pasta `proxy`, mesmo nome-base.
- Veredito pela comparação 1:1: TC de início, duração, nº de quadros e taxa iguais;
  resolução/codec diferentes; **imagem igual** nos quadros amostrados (MobileNet 99% / pHash 93%,
  `bancodedadosnles/transversal/busca-visual-no-acervo.md`).
- Sem pista de nome, a comparação propõe e o usuário confirma.
- ⭐ **Processa-se a variação mais barata e o resultado vale para a família inteira** (TC 1:1) —
  a lição de "derivado por tarefa" do Eddie sem gerar derivado nenhum. A transcodificação
  gerenciada do Avid de um original de câmera é, ela mesma, uma variação: aqui as duas portas se
  encontram.
- Exportar ao NLE escolhe qual membro da família levar.

### Vínculo de mídias (reservado na v1, feito depois)

O banco guarda o PAR — master de imagem ↔ master de som, deslocamento, origem (bin sincronizada
do Avid, Órbita, manual) — com procedência. A anatomia já está medida
(`bancodedadosnles/protocolos/avb/sincronizacao-e-subclipes.md`: subclipe mistura masters; a
fronteira vem da posição na timeline; o gravador liga 4–12 s antes da câmera) e `avid/take.py`
já separa `imagem` e `som` com offsets próprios.

### Organização sem formato fixo

A produção tem unidades tipadas pelo gênero — capítulo/cena (dramaturgia),
entrevista/entrevistado/tema (documentário), diária/rolo (bruto), acervo/origem (arquivo). Mesmo
motor, rótulos do gênero.

- **Quem fala** no capítulo finalizado = roteiro do capítulo ancorado na transcrição
  (`plano/mapa.py:ancorar` — take certo 100%, errado 9%); nos brutos, roteiro, claquete e canal;
  no documentário, costuma ser uma anotação por mídia (um entrevistado por entrevista).
- Material de arquivo pede campo de **origem/direitos** (proposta, a confirmar com o editor).

### O que a escala impõe

- 2.000 h ≈ 7,2 M s; plano a cada ~4 s ⇒ **~1,8 M planos**. Vetor SigLIP 768 d float16 ⇒
  **~2,7 GB** ⇒ **índice ANN local**, não varredura do `.npy`.
- ~18 M palavras ⇒ **índice de texto local (FTS)**. Os dois índices são derivados e
  reconstruíveis da pasta; a verdade é a pasta.
- SigLIP no Mac, 66 ms/quadro ⇒ ~33 h para o acervo: viável em lote.
- Decupagem por VLM ou Claude em tudo **não fecha** (milhares de horas, ou dezenas de milhares de
  dólares) ⇒ índice barato global (fala + vetor + planos), olho caro só nos candidatos.

### Um serviço, duas faces

O mesmo processo serve o painel do MC e a janela do app (padrão Jumper,
`bancodedadosnles/plugins/avid-panel-sdk/paineis-de-terceiros.md`); o painel já funciona
same-origin em `/painel`. A tecnologia da janela é ADR da F0.

## O que reaproveitar e o que destravar

**Reaproveitar:** `midia/frames.py`, `audio.py`, `asr.py`, `analise.py`, `vetores.py`,
`decupagem.py`, `estagios.py`, `inventario.py`; `servico/tarefas.py`; `motor/percepcao.py`;
`plano/mapa.py`, `plano/falas.py`; `documento.py`; `avid/timeline.py`;
`servidor_mac/siglip_servidor.py`.

**Destravar:**
- `acervo._sondar` descarta arquivo sem UMID — `.mov/.mp4/.wav` nunca entram.
- `mcp/ferramentas/midia.quadros_de` depende de `acervo.ler()`.
- `motor/claude.PERSONA` fala de "painel estreito dentro do Avid"; `sessao.id_do_projeto` deriva
  do caminho do projeto Avid.
- `asr.IDIOMA = "pt"` fixo; fila só em memória; nenhuma rota serve miniatura; `rotas.py` importa
  grpc; `percepcao` recusa loopback (rever para o app rodando no Mac).
- Exportar: `timeline.escrever_bin` só aponta mob que já existe numa bin. No banco: AMA por
  byte-surgery `confirmado`, `.prproj` do zero `confirmado`, `.drt` parcial, FCPXML/EDL sem
  writer.
- Watchfolder e janela/webview **sem linha na matriz de plataforma** — entram com os dois lados.

## A interface (canvas)

Tema claro do MSYNC (`MSYNC/frontend/src/style.css`): fundos `#ffffff/#f5f5f3/#ececea`, texto
`#1f2023/#56585c/#9a9c9f`, bordas 0,5 px `#e6e6e3/#d2d2cd`, destaque `#378add`, corpo 13 px fonte
do sistema, ícones Tabler 12–14 px ao lado do texto, botões vazados, rótulo de seção 10 px
maiúsculo. Conceitos de busca das pranchas `docs/design/busca-ia/` (motivo do resultado,
cobertura, momentos ‹ 1 de 3 ›), traduzidos para o claro.

1. Janela principal — banco aberto na barra; chat à esquerda; lista com árvore no centro; inspetor à direita.
2. Busca inteligente respondendo na lista, e o caso sem resultado com a cobertura dita.
3. Detalhe da mídia/momento — quadros, transcrição, anotações e entidades, "decupar este trecho"
   (custo dito), procedência.
4. Família da mídia — original, proxies, transcodes, a pista que ligou cada um.
5. Entidades — personagens, pessoas, locais, bordões por produção; confirmado × inferido.
6. Watchfolders e fila — etapas por pasta, perfil da máquina, etapas puladas e por quê.
7. Reconectar — offline, pasta apontada, candidatos com critério e peso.
8. Bancos — local × remoto, importar/exportar, quem está conectado.
9. Usuários e permissões do remoto.
10. Somar bancos — o que entra, o que funde, conflitos lado a lado.
11. Levar ao NLE — Avid / Premiere / Resolve / MP4.
12. Chat com resultado — cartões de momentos na conversa.
12b. Lista com árvore, colunas redimensionáveis e ordenáveis, filtro + busca inteligente na lista.
13. Vínculo (esboço) — "som direto casado", só para reservar o lugar.
14. Estados vazios e cobertura incompleta.

## Fases (esboço — aprovar depois do canvas)

- **F0 spikes**: identidade por conteúdo em arquivos soltos (Win/Mac, exFAT, NAS); FTS + ANN com
  ~2 M vetores (RAM, tempo, reconstrução); arquivo "estável" no watchfolder; comparação 1:1 em
  proxy real (4K × HD H.264); janela nativa abrindo com o serviço (ADR).
- **F1 banco portátil**: formato da pasta, manifesto com identidades e lugar relativo, histórico.
- **F2 ingestão, duas portas** + watchfolder, fila persistente, perfil de máquina.
- **F2b família de mídia**.
- **F3 pool + detalhe + anotação/entidades**.
- **F4 reconectar guiado**.
- **F5 busca**: fala tolerante, visual, decupagem sob demanda; recorte por pasta.
- **F6 chat do app**: persona e ferramentas do banco; sessão por banco, não por projeto Avid.
- **F7 levar ao NLE**: MP4 → Avid (AMA) → Premiere → Resolve.
- **F8 painel do MC lê o banco**.
- **F9 somar bancos** — pode subir: é o que torna o HD mandado seguro e a base do local → remoto.
- **F10 banco remoto**: servidor, usuários, permissões, exportar como local.
- **Futuro: vínculo de mídias** — pares das bins sincronizadas e do Órbita; depois sync próprio.

Em todas: `bancodedadosnles/transversal/matriz-de-plataforma.md` antes de caminho, processo ou
diálogo; registrar no banco o que for medido.

## Fora da v1 (dito para não virar promessa)

Player, timeline e collect · envio direto pela IA · grade de miniaturas · reconhecimento de rosto ou voz · chat com Ollama · sync próprio de câmera × som · decupagem em
lote do acervo inteiro · tema escuro.
