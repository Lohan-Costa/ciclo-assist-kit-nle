# Transcrição por canal — quem fala, pela lapela (2026-11-06)

**Pedido do autor (2026-11-06):** *"pode fazer a transcrição por canal primeiro"* — depois de medir o "Separar falas
sobrepostas" do Premiere 27.1 (1 crédito/s, nuvem) e ver que as vozes que a Adobe separou são as das LAPELAS do
gravador (banco `transversal/ia-embarcada-nos-nles.md` §3e: onde a MIC2 lidera, o `falante_2` domina 97 %; onde a
MIC3 lidera, o `falante_1` domina 88 %). Em ficção com som direto multipista, "quem fala" já vem do set, de graça.

Estado: **APROVADO (2026-11-06)** — decisões no fim; execução por fases.

## O que já se sabe (banco + Assist anterior)

- `bancodedadosnles/transversal/metadado-de-canal-do-som-direto.md`: o nome do canal mora nas colunas `TRK1..n` do
  `_USER` do master (bin) ou no `TRACK_LIST` do iXML do WAV (o canal é o `INTERLEAVE_INDEX`, nunca o `CHANNEL_INDEX`);
  o OP-Atom NÃO carrega o papel (só o sufixo `_A0x` = a posição); a POSIÇÃO não diz o papel (muda dentro da diária);
  o número de canais muda por master; quatro condições (A nome completo · B parcial · C mapa sem nome · D nada).
- Estatística sozinha NÃO separa lapela de boom (§6b) — sem nome, não se adivinha.
- `_ASSIST ANTERIOR/assist_anterior/som/` (abandonado como produto, solução paga): `canais.py` (papéis fechados: mistura ·
  boom · ambiente · sem-nome; o resto é PESSOA), `atribuicao.py` (a regra pura: lapela com mais energia por margem de
  3 dB; mistura e boom nunca disputam; < 2 lapelas = não avaliado), `energia.py` (nível por janela por `seek`, sem ler
  o WAV inteiro; 24 bits com extensão de sinal), `ixml.py`. Medido na D02: 91,9 % atribuído; quem usa lapela domina por
  8–27 dB, a equipe ("Câmera", "Som") fica em 0–3 dB ⇒ a margem separa ATOR de EQUIPE.

## A proposta (recomendada)

**A transcrição continua a da mixagem** (o cache de transcrição sobrevive: nada se re-ouve). Acrescenta-se um estágio
leve, **`falantes`**: para cada fala já transcrita, a energia de cada canal de PESSOA no intervalo dela → o canal que
fala, com margem e procedência. Segundos por take, sem modelo.

1. `midia/canais.py` — o papel de cada canal (porte de `canais.py` + `ixml.py`), de três fontes, nesta ordem: colunas
   `TRK` da bin (Avid) · iXML do WAV (AMA, Premiere, ou o original achado pelo acervo) · nada (= não avaliado).
2. `midia/falantes.py` — a regra (porte de `atribuicao.py`, pura e testável) + a medição por canal (OP-Atom: um arquivo
   por canal, na ordem `_A0x`; WAV: o `INTERLEAVE_INDEX`). Grava `falantes.json` + receita no cache (copiável entre os
   bancos Avid/Premiere, como a transcrição).
3. A fala ganha `falante` (`{"canal": 3, "nome": "MIC2", "margem_db": 14.2, "motivo": "resolvida"}`), com procedência
   (`fonte: heuristica`, `medida` = a margem). `transcrever`, `o_que_acontece`, `separar_falas` e a aba Busca passam a
   mostrar.
4. Conferência no material: o take `C4 P4-T003` do laboratório (MIC2/MIC3/BOOM) contra a separação da Adobe (o gabarito
   de hoje), e a D02 do Assist anterior (91,9 %).

## Perguntas ao autor (decidem o desenho)

1. Atribuir pela ENERGIA das lapelas sobre a transcrição da mixagem (recomendado), ou transcrever CADA lapela?
2. Que nome aparece para quem fala: o da trilha (`MIC2`), ou o personagem (mapa canal → personagem dito pelo editor)?
3. Onde aparece primeiro.
4. A fala AMBÍGUA (empate de lapelas: equipe, fala sobreposta).

## Decisões (autor, 2026-11-06)

1. **Energia das lapelas + Whisper SÓ no ambíguo.** A transcrição da mixagem fica (cache intacto); quem fala sai da
   energia; onde as lapelas empatam (fala sobreposta), as lapelas em disputa são transcritas naquele trecho.
2. **O nome da trilha, e o editor batiza:** `MIC2`/`PESSOA-H` como o técnico nomeou; o editor diz "MIC2 é a Personagem F" e o
   mapa é guardado por POSIÇÃO e nome (a armadilha da condição C do banco).
3. **Aparece no chat (`transcrever`, `o_que_acontece`), no `separar_falas` e na aba Busca.**
4. **Empate = "ambígua" com os candidatos** — nada some calado.

## Fases

- **F1 — o motor:** `midia/canais.py` (papéis + nomes: bin `TRK`, iXML), `midia/falantes.py` (regra pura + medição por
  canal), estágio de cache `falantes` com receita; conferido no `C4 P4-T003` contra o gabarito da Adobe.
- **F2 — o ambíguo:** Whisper nas lapelas em disputa, só no trecho; resultado na mesma fala (`vozes`).
- **F3 — onde aparece:** `transcrever`/`o_que_acontece` (o falante em cada fala), `separar_falas`, aba Busca (rótulo +
  filtro). Nos dois NLEs.
- **F4 — batizar:** ferramenta de chat "MIC2 é a Personagem F" → mapa por produção/diária (posição + nome), e a tela mostra o
  personagem.

## F1 — FEITA (2026-11-06, Mac)

- `midia/canais.py` (papel, `de_colunas`, `de_ixml` pelo INTERLEAVE_INDEX, posição `_A0n`), `midia/falantes.py`
  (regra + envelope em fluxo + `falantes.json`, que cai sozinho com receita nova ou transcrição refeita e atravessa os
  bancos), `analise.quem_fala`/`trilhas_do_som`; a varredura de bins guarda `trk`; o chat lê o `TRK` da bin do take,
  a fila da aba Vetores lê o da última varredura. `transcrever_master` devolve `falantes`.
- ⭐⭐ **Normalizar cada canal pelo PRÓPRIO p95** (não estava no Assist anterior): em dBFS cru, 10 de 19 com a Adobe e a
  EQUIPE saía "MIC2 por 5–8 dB" (ganho da mesa); normalizado, a equipe cai em 0–3 dB (ambígua) e os atores ficam em
  9–21 dB — concordância 9 de 11 nas resolvidas pelos dois; os 2 diferentes são curtos ("E…", "Desculpa" — este com
  19 dB na MIC3 logo depois de uma fala da MIC3: provavelmente a lapela está certa; não ouvido).
- ⚠️ Consequência da normalização, presa num teste: uma lapela que só ouve o VAZAMENTO do outro (ator sem fala no take)
  sobe até empatar ⇒ ambígua. Falha segura (não inventa), mas é um caso a ver em material real.
- 29 testes (`tests/test_falantes.py`); suíte do Mac 1549.
- ⬜ F2 (Whisper no ambíguo — ⚠️ a maioria das ambíguas é EQUIPE: transcrever lapela por lapela ali não acrescenta
  nada; decidir se F2 só roda quando a fala ambígua tiver as lapelas ALTAS, i.e. sobreposição de atores), F3, F4.

## F2 — FEITA (2026-11-06, Mac) — com a regra refinada pelo autor

- Ambígua com DUAS ou mais lapelas acima de −8 dB do próprio p95 (`ALTA_DB`) → cada lapela é recortada no trecho
  (±0,25 s) e passa pelo Whisper do produto; textos parecidos por LETRAS (≥ 0,65) = **a mesma voz** ouvida pelas duas
  (a claquete), diferentes = **sobreposta**, cada texto na sua lapela. Abaixo do limiar = **"provável equipe"**, nada roda.
  Medido: fala do próprio ator −5…+4 dB; equipe ao fundo −24…−11; claquete −4 nas duas.
- ⛔ A 1ª comparação (palavras inteiras) chamou "Será 4, os câmeras?" × "Sena 4, câmera…" de sobreposta (0 palavras
  em comum); por letras dá 0,80 (a mesma voz: 0,80–1,00; vozes diferentes: 0,32–0,50).
- No `C4 P4-T003`: 2 ouvidas (as duas leituras de claquete → mesma voz), 8 provável equipe, 11 resolvidas; 6,9 s.
- ⬜ Falta uma fala SOBREPOSTA de verdade: o autor indicou a cena do CARRO da D04 (atores falando juntos).

## F3 — FEITA no chat e na Busca (2026-11-06, Mac); `separar_falas` parcial

- Chat: cada fala do `transcrever` traz `quem` (completa e enxuta: `seg | s | texto | quem`), a resposta traz
  `quem_fala` (o resumo: de onde vieram os nomes, quantas resolvidas/ambíguas — ou POR QUE não se sabe); o
  `o_que_acontece` mostra `quem` na linha do tempo. Rótulos: `MIC2` · `provável equipe` · `ambígua: MIC2 ou MIC3` ·
  `a mesma voz em MIC2 e MIC3 (…claquete)` · `sobreposta: MIC2 «…» + MIC3 «…»`.
- Busca: `quem` em cada fala do cartão (à direita); o nome RESOLVIDO filtra ao clicar (`falante` na rota
  `/busca/frase`, sozinho já é busca: "tudo o que a MIC3 diz"); o resumo mostra "só falas de MIC3 ✕". A busca só LÊ
  `falantes.json` (nunca mede). ✅ Visto a 400 px (`tools/olhar_painel.py`, Chrome headless): "Personagem F" → a fala do som
  com MIC2, a da câmera sem marca. ⬜ O clique no MIC2 não foi exercitado na tela (a rota foi: MIC3 → 6 falas).
- `separar_falas`: o modelo já VÊ `quem` no `transcrever` enxuto que ele usa. ⬜ Falta a CONFERÊNCIA (o momento X
  apontando, num take, um segmento de outra lapela que nos demais takes) — decidir com o autor.
- ⬜ Quem ainda não tem `falantes.json` (transcrito antes de hoje) só ganha ao ser lido pelo `transcrever` (ou pela
  fila, se refeito): a Busca não mede. Uma passada de fundo pela aba Vetores é decisão do autor.
- ⬜ F4 (batizar: "MIC2 é a Personagem F").
