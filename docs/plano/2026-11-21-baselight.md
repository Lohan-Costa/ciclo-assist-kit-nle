# Baselight: a sequência do MC/Premiere chegando conformada nos originais (proposta, 2026-11-21)

## A missão (autor, 2026-11-21)

O Baselight (FilmLight) é concorrente direto do Resolve, mas para nós ele **só recebe**: a sequência do Media
Composer ou do Premiere tem de chegar **conectada nos originais de câmera e pronta para cor**. Não há volta (nada de
Carta Aberta a partir do Baselight). Interessa agora: como ele **cria e guarda projetos**, **importa mídia** e
**importa timelines**. Correção de cor e operação do programa ficam fora.

Por quê: onde o autor trabalha o conform é feito no MC antes do Baselight só por orçamento (a hora do editor online é
mais barata que a do colorista). Fazer o conform MC → Baselight pela ferramenta fecha uma lacuna real; o Resolve não é
o único programa de cor, só é o que quer ser editor (por isso o fluxo bilateral dele).

O autor não conhece o Baselight: as decisões técnicas ficam com o Claude, medidas; um colorista de Baselight pode
ser trazido depois para o avançado.

## O que já se sabe SEM instalar (estudo de 2026-11-21)

Fontes: o `.dmg` 7.0.3.26500 aberto sem instalar (`8 REFERENCIA/BASELIGHT/instalador-7.0.3-extraido/` — User Guide v7,
Training Manual, a doc da FLAPI em `doc/flapi/python.html`, o `schema.json` da API, o FLESpec, as notas de versão),
as transcrições do vídeo de introdução e do webinar da API, e os repositórios `github.com/FilmLightAPI`
(`enhancements`, `flapi-dev-mcp`, `web`).

**Como ele guarda projetos.** Não há arquivo de projeto: tudo vive num **PostgreSQL** (o instalador traz o
`postgresql-9.3.4`). Hierarquia: *host do banco* (`localhost`) → **job** (= projeto) → pastas → **scene** (= a
timeline; pode ser uma sequência inteira ou um plano só). Salva sozinho a cada mudança. Para levar de uma máquina à
outra: `bl-export` / `bl-import` (arquivo `.blexport`/scene exportada).

**Como ele importa mídia.** Nada é copiado: a scene guarda um ponteiro (a "Layer 0", a *sequence strip*) para o
arquivo no disco — R3D, ARRI, BRAW, MXF, MOV, DPX/EXR (sequência de quadros com a sintaxe `%.7F`). Na mão é o
**FLUX Manage** (Ctrl+B); na API é `SequenceDescriptor.get_for_template[_with_timecode]` + `Scene.insert_sequence`.

**Como ele importa timelines (o conform).** Scene › Conform (Win+E) lê:
- **AAF do Avid**: casa por **Avid UID**, nome de arquivo, tape no caminho/cabeçalho ou só TC; nas notas de versão,
  "conformar um AAF do Avid usa o **Locator** atribuído", reconhece 3D Warp/FrameFlex para o formato, marcadores do
  MC, e transforma em camada (Layer 99) as transformações de imagem.
- **XML do Premiere** (o xmeml, irmão do FCP 7): cortes, dissolves, algumas transições e camadas.
- **CMX 3600**, **DLEDL** do Autodesk e o **FLE** (EDL da FilmLight, que traz o **caminho do arquivo** em cada evento,
  trilhas, fps/reverso/congelado, dissolve, flip/flop e CDL; spec em `doc/FL-GN-TN-0476-FLESpec.txt`).
- Não lê OTIO nem FCPXML (nenhuma menção no manual de 1 000 páginas).
- Conform por **faixa de fonte** (os originais) ou de gravação (cortar um render); diretório de busca (até 7); até
  oferecer as alternativas quando acha mais de uma mídia; relatório de % achado e mídia faltante.
- **`bl-conform`** (linha de comando, script fechado da FilmLight): conforma um EDL/AAF/XML numa scene NOVA ou
  EXISTENTE, com `--FilenamePrefix`, filtros de busca, LUT/CDL. Uso exato: `bl-conform --help` (só depois de instalar).
  E `bl-mkjob` / `bl-mkscene` criam job e scene pela linha de comando.

**A API (FLAPI).** Cliente/servidor: o Baselight (ou o **flapid**, o serviço que roda sem a interface) é o servidor;
Python 3 por uma roda (`filmlightapi-7.0.3.26500-py3-none-any.whl`, que vem no `.app`). Local sem token; outra máquina da
rede com usuário + token. Faz: `JobManager.create_job`, `Scene.new_scene(caminho, {format, colourspace, frame_rate})`,
`insert_sequence` (no fim, antes/depois/ACIMA/abaixo de um plano), `insert_blank`, ler TC de fonte/gravação de cada
plano, metadados, `save_scene`. Transação = `start_delta`/`end_delta`; todo objeto pego tem de ser `release()`.
**Não tem** um "conformar este AAF" — para isso o caminho é o `bl-conform` (subprocesso) ou montar a timeline plano a
plano pela API. O MCP oficial da FilmLight (`flapi-dev-mcp`) acha a instalação, monta a venv e dá a referência da
versão rodando — serve para NÓS desenvolvermos, não para o produto.

**O que NÃO serve:** Baselight for Avid (Editions) e o BLG para Flame não têm FLAPI.

**Licença.** Ativação online amarrada ao Machine ID (arquivo `licence.flic`); o trial é de 14 dias. ⛔ Não se
investiga como resetar o trial (contornar licença). Para mais tempo: pedir à FilmLight uma licença de avaliação
estendida/desenvolvedor (estamos construindo uma integração) — rascunho no fim.

**Máquina.** Mac mini M4, 16 GB, macOS 15.6.1: dentro do mínimo (macOS 13–15; Apple Silicon 16 GB). Disco interno com
17 GB livres → **o cache do Baselight vai no SSD externo**. 16 GB é apertado: o Resolve já caiu por memória com o
Premiere aberto; **o MC e o Premiere ficam fechados enquanto o Baselight trabalha**.

## O que o Conformar já tem para isso

O Conformar (ex-De Lá Pra Cá) já faz o difícil: lê a sequência do MC (AAF/AVB) e do Premiere (`.prproj`), descobre o
**original de câmera** de cada plano (UMID, nome de fonte, TC) e escreve:
- `motor/aaf/writer.py` — regrava os `URLString` dos locators no AAF apontando para os originais, **sem mexer em mais
  nada** (Selectors, Group Clips, transições, efeitos ficam). Casa com o "usa o Locator" do conform do Baselight.
- `motor/otio_export` (não serve ao Baselight) e a Carta Aberta (o nosso modelo neutro).

## A proposta: três rotas, medidas lado a lado

| rota | o que a ferramenta entrega | quem conforma | vantagem | risco |
|---|---|---|---|---|
| **A. AAF religado** | o AAF do MC com os locators nos originais | o colorista (Conform View) ou o `bl-conform` | reaproveita o writer existente; o Baselight é forte em AAF do Avid | o que o Baselight faz com multicam, subclipe, nested, efeito |
| **B. FLE gerado** | uma EDL FilmLight com o caminho de cada original, por trilha | idem | determinística (caminho + TC, sem busca); fácil de escrever a partir da Carta Aberta; serve ao Premiere também | pouca coisa além de corte/velocidade/dissolve/flip; reposição fica de fora |
| **C. Direto pela FLAPI** | job + scene já criados e montados no Baselight | a ferramenta | "chega conformado" de verdade, sem o colorista abrir o Conform | exige a ferramenta ver o Baselight na rede (token); montar plano a plano é reescrever o conform |

Recomendação: começar por **A e B como arquivo** (funcionam em qualquer Baselight, inclusive o Linux da sala de cor sem
acesso da nossa máquina) e usar o **`bl-conform`/FLAPI para MEDIR** cada rota automaticamente (job, scene, conform,
ler plano a plano o arquivo/TC de fonte e comparar com a Carta Aberta). A rota C vira produto depois, se a A/B provar
o conform e a rede da sala de cor permitir.

## O kit de teste (pronto ANTES de instalar, para os 14 dias serem só medida)

Levantamento de 2026-11-21 em `MIDIAS DE TESTES`: **quase não há sequência montada sobre original de câmera.** O PRODUCAO-G
(Premiere, com um `241023_CHILE.xml` já exportado) usa os PROXIES ProRes dos R3D (os R3D não estão no SSD); o PRODUCAO-A
(MC) foi montado sobre CONVERTIDOS MP4, e só 5 BRAW existem (`SAIDAS/01_DIARIAS/…`); o `PRODA_RELINKER_ALTA.aaf` só tem
locators de ÁUDIO (21 de 21; o vídeo é mídia gerenciada). Originais de verdade, sem sequência: `2 FORMATOS E CAMERAS/ARRI`
(301 `.arx`) e `SONY XOCN` (4 MXF + XML). Por isso o kit tem três partes:

| parte | o que é | para provar |
|---|---|---|
| **K1 sintético** (o principal) | mídia do laboratório (código de barras do quadro e do TC em cada quadro, fita/nome de câmera) como "originais"; no MC: AMA → transcode DNx (o offline) → uma sequência com corte seco em 3 trilhas, velocidade, congelado, reverso, dissolve, Resize/3D Warp, subclipe, multicam, em 23,976 e em 29,97 DF; o mesmo roteiro no Premiere | o conform QUADRO A QUADRO: cada plano no arquivo e no TC de fonte certos (lido pela FLAPI; se preciso, o código de barras num render) |
| **K2 codecs reais** | os 5 BRAW, ARRI `.arx`, SONY XOCN numa sequência curta no MC e no Premiere | o Baselight lê e conforma os formatos de câmera pelas nossas listas |
| **K3 produção real** | PRODA_CORTE (MC, sobre os convertidos como se fossem os originais) e PRODUCAO-G (Premiere, o `.prproj` e o `241023_CHILE.xml`) | o mundo real: mídia misturada, nomes, pastas, áudio |

Para cada sequência: o AAF/XML que o NLE exporta, o AAF religado (rota A), o FLE (rota B) e a lista esperada (a Carta
Aberta: plano, arquivo, TC de fonte in/out, posição). Montar K1/K2 no MC e no Premiere é com o PILOTO e a API (o autor
diz "pode pilotar"); o FLE sai de um escritor novo no laboratório.

## O cenário de projeto (autor, 2026-11-21)

- A conversão (os dailies) foi feita **FORA do MC**, sem metadado nenhum dela. O editor online religa os ORIGINAIS no MC e
  entrega um AAF apontado para eles — e na sala de cor o Baselight pode apontar para OUTRO caminho (cópia local dos
  originais 4K/8K, pela banda). O caminho do AAF é informação; o conform vale por nome/TC/fita.
- "O Baselight se dá bem com o MC" = entende melhor os **EFEITOS** do AAF do MC (não a mídia).
- (Medido) Se o transcode for feito NO MC, o AAF já leva o Locator do original pela cadeia — mas não é o cenário a projetar.
- Kit BL02 (feito): dailies ProRes Proxy HD com o nome e o TC dos originais, AMA no MC, as sequências BL02 e o AAF
  offline, que só conhece os dailies (`saida/bancadas/avid_baselight/aaf_do_mc/BL02_*.aaf`).

## ⭐ O diferencial: conferir o conform contra o VÍDEO DE REFERÊNCIA (autor, 2026-11-21)

O Baselight só confere à mão (manual, pág. 349: o filme de referência numa scene à parte, cursores "ganged" e o wipe, a
olho). Nós comparamos **quadros extraídos da timeline com o vid ref anexado**, plano a plano, e dizemos qual plano
diverge e por quanto (quadro deslocado, plano trocado, reposição). Dois momentos:
1. **Antes do Baselight (sem ele):** para cada evento, o quadro do ORIGINAL no TC de fonte × o quadro do vid ref na mesma
   posição — prova que a lista que entregamos (AAF/FLE) monta o corte da referência. Só depende do Conformar.
2. **Depois do Baselight:** stills da scene conformada (FLAPI/`bl-render`) × o vid ref — prova o conform dele.
No laboratório a mídia traz o número do quadro e o TC em código de barras: a conferência é EXATA (o quadro lido), e
serve para calibrar a comparação por imagem que valerá nas produções reais.

## As etapas

1. **Hoje (sem instalar):** este plano; registro no banco (`bancodedadosnles` ganha o Baselight: projetos, mídia,
   conform, FLAPI, FLE); o e-mail à FilmLight; o kit de teste montado; um escritor de FLE no laboratório.
2. **Dia 1 instalado:** instalar com o cache no SSD; ativar o trial; `bl-conform --help`, `bl-mkjob -i`,
   `bl-mkscene -i`, onde o Postgres guarda os jobs; a FLAPI conectando pela roda; criar job/scene pela API.
3. **Dias 2–6:** conformar o kit pelas rotas A e B (pelo `bl-conform`, e uma vez à mão pela Conform View para ver o
   que o colorista vê); ler cada scene pela FLAPI e comparar com a lista esperada, quadro a quadro; anotar no banco
   cada diferença (o que ele perde, o que ele erra).
4. **Dias 7–10:** fechar a rota (ou a combinação: AAF para o MC, FLE para o Premiere?) e levar ao **produto**: o
   Conformar ganha o destino "Baselight" (mesma tela que hoje leva ao Resolve), com o relatório do que não viaja.
5. **Dias 11–14:** a rota C (FLAPI criando a scene) se der tempo; `bl-export` da scene como entregável alternativo.

## Decidido pelo autor (2026-11-21)

1. ✅ O Baselight é uma **nova saída do Conformar**, não um app novo.
2. ✅ **Arquivo primeiro** (rotas A e B); a FLAPI criando a scene depois.
3. ✅ **Sem e-mail agora**: vamos até o fim do trial; se faltar tempo, contato com a FilmLight.
4. ✅ **Instalar depois do kit pronto.**
5. ⭐ **A estação do Baselight só tem o Baselight** (autor): ele é separado da montagem e operado por quem só faz cor
   (diferente do Resolve, que convive com o Premiere na mesma máquina). Regra: o Baselight **nunca abre com outro NLE
   aberto**; se precisar abrir, fecha os outros antes, **com force quit se for preciso**. Vale para o laboratório e para o
   produto (quem abrir o Baselight pela ferramenta fecha MC/Premiere/Resolve primeiro).

## Etapa futura (não agora): a atualização de corte

Quando uma timeline já conformada no Baselight muda na montagem (plano novo, removido, trocado, trim), como levar só a
mudança sem perder a cor já feita, com o Ciclo Assist ajudando. Primeiro vem a prova inicial do caminho.

## Rascunho do e-mail à FilmLight (o autor manda da conta dele)

> Hello FilmLight team, we are a post-production tools developer in Brazil building an integration that delivers
> Avid Media Composer and Adobe Premiere sequences to Baselight already conformed to the camera originals (AAF / FLE,
> and FLAPI). We have downloaded Baselight 7.0.3 for Mac and would like to ask whether an extended evaluation or
> developer licence is available, since the 14-day trial is short for testing conform across our real production
> cases. We would also be glad to share our findings on AAF conform with your team. Thank you, …
