# Transcrição por palavra: medir a borda contra gabarito (2026-11-11, Mac)

Resultado e explicação: banco, `transversal/transcricao-por-palavra.md`. Todos recebem a PASTA DE TRABALHO como 1º argumento
(fora do SSD de preferência; o áudio sintético é pequeno).

1. `gerar.py <pasta>`: `sint/sintetico_{pt,en}.wav` + `sint/gabarito_{pt,en}.json` (a borda de cada palavra, à amostra). Só macOS (`say`).
2. No Resolve: importar os dois WAVs, `transcriptionLanguage` = idioma do clipe, `TranscribeAudio()`, salvar o projeto e copiar o
   `Project.db` para `<pasta>/Project2.db`.
3. `nosso.py <wav> <saida.json>`: o ASR do produto (`midia.asr.transcrever`), com `PYTHONPATH=.`.
4. `avaliar.py <pasta>`: Resolve PT, Resolve EN e o nosso contra o gabarito (lê o `Project.db`: zstd + protobuf; precisa do `zstd`).
5. `comparar.py <pasta> <wav real> nosso.json`: Resolve × nosso num take REAL (precisa de `<pasta>/resolve.json`, tirado da API).
   ⚠️ O juiz de energia daqui é grosseiro (bate no alcance de 0,6 s); vale só como ordem de grandeza.
6. Premiere 2026: `gunzip -c X.prproj`, tirar o base64 de cada `<TranscriptData>` para um `.bin` e rodar
   `ler_prproj_transcricao.py <arquivo.bin>` (a função `palavras()` devolve início, duração, texto, confiança). Leitor heurístico de
   FlatBuffers: acha a tabela de cada palavra pela string que ela aponta.
7. **L0 do alinhador** (`alinhar_l0.py`, modelos em `$MODELOS_L0`, padrão `MIDIAS DE TESTES/…/2026-11-11 TRANSCRICAO POR PALAVRA/modelos_l0`):
   `alinhar_l0.py <w2v_pt|w2v_pt_int8|omni|nemo_pt> <wav> <saida.json> --whisper nosso.json --energia [--lapelas 2,3,4 <wav multicanal>]`
   (ou `--texto gabarito.json`). Mede: `medir_l0.py <gabarito.json> <saidas…>` (sintético) e `medir_real.py <premiere.json> <saidas…>`
   (take real × Premiere 2026). Ajustes por ambiente: `L0_ABAIXO`/`L0_ACIMA` (limiar), `L0_PONTE`/`L0_PAUSA`, `L0_SEM_ARENA`, `L0_THREADS`.
   O int8 do wav2vec2 PT sai de `quantize_dynamic(..., op_types_to_quantize=["MatMul"])` numa venv à parte com `onnx` (não é dependência do app).
8. **Juiz de ouvido da pausa:** `bordas_para_ouvir.py <premiere.json> <nosso.json> <CHAVE.json> 20` escolhe bordas de pausa onde nós e o
   Premiere discordamos (> 1 quadro e < 1,5 s, ≥ 3 s entre elas) e sorteia A/B (cego). As `linhas` da chave vão para a `sincMarcadores`
   (ponte, sequência ativa). Feito em 2026-11-11: `TRANSCRICAO POR PALAVRA v3.prproj`, sequência `OUVIR PAUSAS C4 P1-T001`, 18 bordas;
   chave em `MIDIAS DE TESTES/…/2026-11-11 TRANSCRICAO POR PALAVRA/bordas_para_ouvir_CHAVE.json` (não abrir antes de o autor julgar).
9. **L1 (o código do produto):** `PYTHONPATH=. medir_l1.py <wav> nosso.json <saida.json> [--chave CHAVE.json]` com
   `CICLOASSIST_ALINHADOR=<pasta do Omnilingual>`: mistura como o produto, `alinhamento` + `voz`, palavras no formato do
   `medir_real.py`. Com `--chave`, lista as bordas julgadas de ouvido. ⚠️ Gravar os vereditos do juiz num arquivo (os de 11/11 se perderam).
10. **Segundo juiz de ouvido (L1 × Premiere), 2026-11-11:** `bordas_para_ouvir.py <premiere> l0/take_L1_ouvir.json bordas_para_ouvir_L1_CHAVE.json 20
   --semente 20261112` (17 bordas) + 3 fins onde a L1 já se sabia em dúvida (secretária, Eduardo 257 s, toda), A/B sorteado de novo.
   `TRANSCRICAO POR PALAVRA v4.prproj` › `OUVIR PAUSAS L1 C4 P1-T001`, 40 marcadores. ⭐ Os vereditos vão para `vereditos_L1.json`
   (ao lado da chave) NO MOMENTO em que o autor responder — antes de qualquer conta.
