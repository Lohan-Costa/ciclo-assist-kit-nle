# 0009 — O preset de export AAF vem embarcado; o plugin não confia no nome escolhido pelo editor

**Status:** ativa · Data: 2026-08-10

**Contexto:** o relink lendo a timeline direto do Media Composer (em vez de a partir de
um AAF já exportado) precisa que o MC exporte um AAF sozinho, via `ExportFile` com um
preset. **Medido:** o preset chamado `"AAF"` neste projeto na verdade disparava um
**WAVE Export** — o MC começou a renderizar o áudio da timeline inteira, com diálogo de
progresso, e o editor teve que cancelar na mão. O banco de NLEs já avisava que "presets
são por-projeto; o nome não garante o formato" — mas escrever o aviso no docstring não é
tratá-lo: o código continuava passando `"AAF"` como padrão e confiando no nome.

**Investigação:** os presets vivem em `<usuário> Settings.xml` (não no projeto), como
blocos `<AvClass id="EXst">`. Uma primeira varredura não achou nenhum campo que
distinguisse AAF de WAVE nos atributos de primeiro nível. Comparando um preset de AAF
**correto** (criado pelo editor) contra o de WAV, apareceu o campo real: um atributo
nomeado `_EXPORTFORMAT` (não um `AvProp` comum), com valores tabelados por formato
(20 = AAF, 9 = WAV, 23 = XDCAM, 24 = QuickTime/MP4, 25 = Pro Tools, 8 = sequência de
imagens) — medido no MC 25.12.

**Decisão:** o plugin não oferece ao editor escolher entre presets existentes. Um preset
correto (`AAF-DLPC`, AAF puro sem mídia) vem **embarcado** em
`servico/recursos/preset_aaf.xml`. O painel mostra o **estado** (instalado e correto,
ausente, ou divergente) com um botão que instala/repara, em vez de uma lista de opções.
A saída também é **conferida pela extensão do arquivo**, não pelo nome do preset — se
sair `.wav`, o erro diz o que de fato saiu, não apenas "nada foi produzido".

**Consequências e armadilhas medidas:**

- `ExportFile` é **assíncrono**: a chamada volta `Completed` em ~0,8 s e o MC escreve o
  arquivo depois (é uma tarefa com `task_id`/`progress`, não uma resposta). O código
  espera o arquivo aparecer **e parar de crescer**, não só aparecer.
- Instalar o preset embarcado exige o **MC fechado** — ele reescreve o `Settings.xml`
  inteiro (todas as preferências do usuário) ao sair, a partir da memória; escrever com
  o MC aberto seria descartado sem aviso. `instalar()` recusa nesse caso e faz cópia de
  segurança do arquivo antes de tocar nele.
- Um preset recém-criado não existe no disco enquanto o MC está aberto — a API já o
  lista, o arquivo só aparece depois que o editor salva.
