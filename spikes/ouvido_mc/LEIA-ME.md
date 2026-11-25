# Ouvir o canal no Media Composer (2026-11-25, MC 25.12 Mac)

O MC não tem saída de som que o Claude ouça; o export pela API tem. Rodar da pasta `modulos/conformar` com o
`.venv` dela, o Ciclo Assist no ar (o núcleo fala com o MC) e o projeto de laboratório aberto (`LAB COR MC`).

- `ouvido_export.py <saida> <fotos> <entrega>...` — exporta a sequência da `_SEQ` com o preset do laboratório
  `DLPC_LAB_DNXLB` (instala pelo `LoadSetting`). ⚠️ O MXF sai com DUAS trilhas mono iguais = a MISTURA no centro
  (o `iAudioMode` não muda isso: 0–4 medidos).
- `ouvido_medir.py <mxf> <_SEQ.avb> <sequência>` — em cada trecho (os cortes de todas as trilhas), os TONS da mistura ×
  os esperados (lab `verdade.json`: hz por canal; o canal N = a trilha N do master). Tira as CLAQUES do lab (1 ms por
  segundo de TC, picos de 0 dBFS que sujam o espectro).
- `ouvido_trilha.py <saida> <entrega> <sequência> <n>...` — UMA trilha por vez: cópia da `_SEQ` (Bin.uid e MobID
  novos) com só a A<n> habilitada (`_ENBLSTATE`); o preset exporta só as habilitadas (`iUseEnabledTracks`).
- `ouvido_master_trilha.py` — o mesmo para uma trilha de um MASTER.
