# O projeto-modelo da calibragem (Carta Aberta → "Importar para o Premiere")

`modelo.prproj` tem UM merged clip feito pelo próprio Premiere (Clipe ▸ Mesclar clipes…, sincronizar por Timecode) a
partir da mídia sintética de `midia/`: uma câmera (`MOLDE_CAMERA.mov`, H.264 320×180, 1 s, TC 01:00:00:00) e 16 canais
mono OP-Atom (`MOLDE_SOM_A01…A16.mxf`, PCM 48 kHz, 1 s, TC 01:00:00:00). Quando o projeto do editor não tem merged de
onde tirar o molde, ele é importado na CÓPIA de trabalho (`carta/importar_premiere.py`, a "calibragem", calada — decisão
do autor, 2026-11-14) e o merged dele vira o molde dos merged da timeline. 16 canais: o molde precisa de canais de sobra
(os que faltam saem; a mais é recusado).

- Feito no Premiere **26.0.2** (Mac, 2026-11-14) — `modelo 26.0.2 v02.prproj` é o original; `modelo.prproj` serve o 26+.
- ⭐ **Um modelo por Premiere** (um Premiere antigo não abre projeto novo; `moldes_prproj.modelo_para(versão)` escolhe):
  `modelo 25.prproj` (25.x) e `modelo 23.prproj` (23.x e 24.x) — o do 26 rebaixado por
  `laboratorio-de-midia/lab/prproj_downgrade.py` (para "25.6.5" e "23.2"), e PROVADOS em 2026-11-15 no Mac: importados
  num projeto aberto no **23.6** e no **25.6.5**, o merged entra (108 → 109 merged, +17 clipes: a câmera e os 16 canais).
- ⭐ Os modelos guardam o caminho ABSOLUTO de quando foram feitos (`/Volumes/SSD/…/moldes/midia/`, nos campos
  `FilePath` e `ActualMediaFilePath`). A calibragem NÃO importa o modelo daqui: importa uma CÓPIA, na pasta de trabalho da
  Carta (`premiere/calibragem/`), com esses campos apontando para a `midia/` ao lado dos modelos onde o app estiver
  (`moldes_prproj.modelo_no_lugar`). Provado no 25.6.5 (2026-11-15): com a mídia copiada para outra pasta, o projeto
  salvo aponta 68 de 68 caminhos para ela. ⬜ No Windows (o caminho sai com `\` e letra de unidade): não medido.
- ⛔ A câmera em OP-Atom do ffmpeg (DNxHR 320×180 e DNxHD 1080p 36) foi RECUSADA pelo Premiere ("Formato não suportado
  ou arquivo danificado"); o som OP-Atom do ffmpeg entra. Por isso a câmera é MOV — o formato dela não muda a estrutura
  copiada (o que é da mídia vem do item que o Premiere importou do arquivo real).
- Refazer: a mídia (abaixo) → `cicloImportarJuntos` (os 17 numa chamada: ficam selecionados)
  → menu Clipe ▸ "Mesclar clipes…" pelo NOME (System Events no Mac; `WM_COMMAND 11591` no Windows) → OK → salvar.

```bash
ffmpeg -f lavfi -i "color=c=gray:s=320x180:r=24000/1001:d=1" -c:v libx264 -pix_fmt yuv420p -timecode 01:00:00:00 midia/MOLDE_CAMERA.mov
for i in $(seq -w 1 16); do ffmpeg -f lavfi -i "sine=frequency=$((200+i*50)):sample_rate=48000:duration=1" \
  -c:a pcm_s24le -ac 1 -timecode 01:00:00:00 -f mxf_opatom midia/MOLDE_SOM_A$i.mxf; done
```

# O molde do TÍTULO (`titulo 26.prproj`, 2026-11-20)

Um projeto SEM mídia, com a sequência `MOLDE TITULO` (HD 1080p 23,976) e UM gráfico com uma camada de texto, feito pelo
próprio Premiere **26.5.2** (Windows): `qe.project.newSequence(nome, preset)` + menu Graphics and Titles › New Layer ›
Text (`maos.comando_menu`). Quando a timeline tem título (Titler+) e o projeto do editor não tem um gráfico de texto, ele
é importado na CÓPIA de trabalho (`importar_premiere`, passo `molde_do_titulo`) e cada título vira um CLONE dele, com o
texto e o estilo do Avid escritos no blob do `Source Text` (`carta/titulo_prproj.py`, `entrega_prproj._escrever_titulo`).

- ⛔ No 26 o `importMGT` do `Basic Title.mogrt` põe um gráfico VAZIO — por isso o molde, e não o `.mogrt`.
- ⛔ A camada nova HERDA o último estilo usado na sessão do Premiere: o 1º molde saiu com o fundo verde e o itálico de
  um título de teste. O `Source Text` deste arquivo foi trocado pelo da camada que o Premiere fez LIMPA na mesma versão
  (`MIDIAS DE TESTES/…/2026-11-20 TITULO NO PREMIERE 2026 WINDOWS/passos/00_new_text_layer.prproj`), e a composição
  zera todo campo de estilo antes de escrever (`titulo_prproj._ESTILO_CONHECIDO`/`_DOC_CONHECIDO`).
- ⚠️ Importado noutro projeto, o "Vector Motion" (`AE.ADBE Graphic Group`) some da cadeia do gráfico (só fica o
  `AE.ADBE Text`) — e o título escrito sai igual. O detector do molde exige só a camada de texto.
- ⬜ 23 e 25: sem molde (`MOLDES_DE_TITULO`); a timeline vai sem o título, dito em `moldes_fora`. ⬜ O 26.0.2 do Mac
  abrir este molde feito no 26.5: não medido.
