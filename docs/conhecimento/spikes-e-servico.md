# Spikes, o modelo local, a porta 7824 e o Reload do painel

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

Spikes — cada um prova o elo de uma fase e sai `0` se passou:

```bash
python spikes/fase0_subprocesso.py "responda apenas: ok"
python spikes/fase1_mcp.py         # o Claude alcança o nosso servidor MCP
python spikes/fase1_ponte.py       # o Claude lê o projeto aberto      (exige MC aberto)
python spikes/fase3_permissao.py   # o contrato do permission-prompt-tool
python spikes/fase3_painel.py      # o portão pelo caminho do painel   (exige serviço no ar)
python spikes/fase4_sessao.py      # processo vivo e --resume
python spikes/fase5c_avb.py --abrir  # a .avb autorada abre no MC      (exige MC aberto)
python spikes/fase5c_painel.py     # o corte zero de ponta a ponta     (exige serviço no ar)
python spikes/portao_sem_relogio.py  # o pedido espera sem prazo, e o clique executa
python spikes/corte_em_l_e_j.py --abrir  # V e A desencontrados abrem no MC  (exige MC aberto)
python spikes/o_que_o_cli_conta.py   # modelo, contexto, tokens e limite: os campos reais
python spikes/busca_visual.py        # achar planos parecidos: pHash x ONNX  (exige MC aberto)
python spikes/o_que_e_a_janela.py    # ocupação da janela x gasto do turno: não é a mesma conta
python spikes/o_exemplo_que_o_modelo_copia.py  # o modelo inventa claquete onde não há, e copia o prompt
python spikes/o_respiro_do_corte.py  # quanto de voz o ASR deixa de fora em cada borda
python spikes/o_cli_carrega_skill.py # o --restricted bloqueia skill do CLI?
python spikes/o_que_enche_a_janela.py    # para onde foi o crédito de uma sessão, por ferramenta
python spikes/a_transcricao_magra.py     # o que a transcrição devolvia, e o que devolve hoje
python spikes/mover_entre_bins.py --abrir    # tirar, pôr e levar o fecho entre bins  (exige MC aberto)
python spikes/a_bin_ama_regravada.py SEQ MID ORI --abrir  # a string nula que condenava a bin  (exige MC aberto)
python spikes/o_que_o_restricted_deixa.py  # que ferramentas NATIVAS sobram ao modelo (zero turno)
python spikes/ler_a_timeline.py "<bin>.avb" --entre 01:02:20:00 01:03:00:00  # a timeline trilha a trilha, em TC
python spikes/extrair_da_timeline.py [--na-bin]   # extrair um trecho, cópia provada  (--na-bin: MC e editor na tela)
python spikes/inserir_na_timeline.py [--na-bin]   # inserir 2 s e abrir gap, cópia provada
python spikes/fechar_bin_com_monitor.py --teste5  # carregar→consultar→fechar derruba (EDITOR NA TELA)
python spikes/as_falas_conferidas.py     # a conferência de separar_falas nas transcrições reais da C07
python spikes/a_referencia_do_editor.py "<bin>.avb"  # drop-frame e matte key numa sequência feita À MÃO
python spikes/o_modelo_local_decupa.py --ollama http://<IP do Mac>:11434  # VLM local x gabarito do Haiku
python spikes/busca_por_frase.py [--variante fp|int8|imagem-int8|texto-int8]  # SigLIP 2 na CPU: RAM, tempo, AUC
python spikes/busca_por_frase.py --mac http://192.168.1.4:7825  # o MESMO placar, com os vetores do Mac
python spikes/o_escopo_do_projeto.py   # a busca não sai das bins do projeto  (exige MC aberto)
python spikes/o_convertido_casa.py     # o original casa com o transcode? (candidato + pixel)
python spikes/o_premiere_por_dentro.py # o Premiere por dentro, sem ninguém na frente (26 s)
python servidor_mac/siglip_servidor.py [--baixar]  # SÓ NO MAC: quadro/frase → vetor (docs/spec/2026-09-14-siglip-no-mac.md)
python spikes/o_ollama_como_motor.py   # M2: o claude -p do produto com a inferência no Mac (leitura, portão, contexto)
python spikes/vetores_no_premiere.py   # a aba Vetores no Premiere 23.2: listar, aproveitar e processar (sem ninguém na frente)
python spikes/o_premiere_avisa_import.py  # que nomes de app.bind DISPARAM num import, e o custo de varrer o projeto
python spikes/vigia_no_premiere.py     # a vigia de ponta a ponta: importou, a fila começa sozinha
python spikes/o_source_no_tc.py        # o scrubTo do Source: TC do clipe ou tempo desde o início? (é o segundo)
python spikes/source_e_descricao_no_premiere.py  # a fala leva a agulha; a decupagem vai para a coluna Descrição
```

⛔⛔ **Modelo local NUNCA neste notebook** — nem LLM, nem VLM, nem SigLIP. Telas azuis
repetidas com o Media Composer aberto — a última em 2026-09-13, com o `gemma3:4b` carregando.
O SigLIP 2 foi TESTADO aqui só na CPU e reprovou (2026-09-14, 172 mídias): AUC 0,79 pt /
0,84 en, mas **169 MB livres, carga 98%** ao carregar o codificador de imagem (o MC segura
11 GB privados). int8 cabe e não serve (AUC 0,58). ⇒ **A busca por frase mora no Mac**
(`servidor_mac/`, decisão do editor); o notebook só manda JPEG e frase. O servidor é o Mac mini na rede — `docs/spec/2026-09-13-servidor-de-percepcao-mac.md`
— e o spike recusa `localhost` de propósito.

⛔⛔ **E "reinicie o serviço" podia não reiniciar nada.** MEDIDO em 2026-09-12: dois
serviços escutando a **mesma porta 7824**, um de 15:32 e outro de 17:26, com o novo
logando `serviço em http://127.0.0.1:7824` e o **VELHO respondendo tudo**. No Windows,
`allow_reuse_address` (que o `HTTPServer` traz ligado) não é "reaproveitar socket em
TIME_WAIT" como no Unix: é deixar um segundo processo bindar por cima, em silêncio.

O sintoma é **indistinguível de painel desatualizado** — a tela nova pedindo rotas que o
processo de trás não tem. O `__main__` já tratava porta ocupada com a mensagem certa desde
sempre; o que anulava o tratamento era o bind PASSAR, então o `OSError` nunca acontecia.
Agora o segundo processo morre falando.

⚠️ **Instalar o painel exige uma ordem:** feche o Media Composer → mate o
`avid-api-gateway` → instale → abra. O gateway sobrevive ao fechamento do MC e pode servir
uma **lista de plugins velha**: o menu Tools aparece completo, com todos os painéis menos o
que você acabou de instalar. Compare o `StartTime` dele com a data do `.avpi`.

⭐ **Para iterar na interface, não reinstale:** botão direito numa área vazia do painel →
**Reload**.

⚠️ **MEDIDO em 2026-09-11: o Reload trouxe a página ANTIGA** — a aba nova não apareceu,
enquanto um `curl` no mesmo endereço devolvia o HTML novo. O serviço servia o painel **sem
cabeçalho de cache nenhum**; agora manda `Cache-Control: no-store` no `/painel` e no
`/static`. ⚠️ **Falta confirmar com os olhos**: o cabeçalho está no ar (conferido por
`curl`), mas a reconferência pelo painel foi tentada com clique sintético, que
provadamente não chega a algumas webviews. **Na próxima vez que der Reload, veja se a
mudança aparece** — e se não aparecer, o problema é outro.

⚠️ **Mas Reload traz a tela nova para dentro do serviço VELHO.** Mexeu em rota, reinicie o
serviço; mexeu só em HTML/CSS/JS, Reload basta. O painel avisa quando a tela é mais nova
que o processo.

## O `claude -p` não recebe o lembrete de andamento (medido 2026-11-22, CLI 2.1.330, Mac)

O Claude Code INTERATIVO manda ao modelo, em turnos longos, um lembrete ("o usuário não tem notícias suas…") e o modelo
responde com frases de andamento — o autor as viu na sessão e perguntou se o produto as geraria. Medido: um `claude -p`
(stream-json, Haiku, US$ 0,003) com três esperas de 100 s seguidas (5 min) — **nenhum lembrete e nenhum texto entre as
ferramentas**, só o "OK" do fim. ⇒ O painel não recebe esse texto pelo motor. Na mesma medição apareceram eventos que o
motor não conhecia (`tool_progress`, `system/task_started`, `system/task_notification`): `motor/claude._traduzir` só
traduz os tipos que conhece, então passam calados (sem erro). ⚠️ O `claude -p` também BLOQUEIA o `sleep` sozinho no Bash
("Blocked: standalone sleep") — para esperar num spike, `python3 -c "import time; time.sleep(N)"`.

