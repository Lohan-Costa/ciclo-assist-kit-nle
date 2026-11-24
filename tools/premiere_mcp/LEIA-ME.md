# Ligar o servidor MCP do Premiere (27.1+) numa máquina de DESENVOLVIMENTO

Plano `docs/plano/2026-11-06-mcp-do-premiere.md`; banco `transversal/ia-embarcada-nos-nles.md` §3f.
Medido no Mac mini (2026-11-06) e no Windows (27.1.0 Beta, 2026-11-18).

## ⭐ Atalho medido no Windows: SEM o Test Host Plugin (Premiere FECHADO)

1. `%APPDATA%\Adobe\Premiere Pro (Beta)\27.0\Debug Database.txt`: acrescentar a linha
   `dvaappsupport.feature.PPro.MCP.EnableMCPServer<TAB>1<TAB>-1` (fim de linha CR CR LF, como as outras).
   O Premiere a lê (aparece em azul no Console) e a bandeira fica `true`.
2. `Documentos\Adobe\Premiere Pro (Beta)\27.0\Profile-<usuário>\Adobe Premiere Pro (Beta) Prefs`, dentro de
   `<Properties Version="1">`: `<HSL.Prefs.McpEnabled>true</HSL.Prefs.McpEnabled>` e (só no desenvolvimento)
   `<HSL.Prefs.McpAuthenticationEnabled>0</HSL.Prefs.McpAuthenticationEnabled>`. ⛔ `McpEnabled` com `1` NÃO liga
   (medido: o servidor ficou desligado até o `setPreferences`; ao sair o Premiere gravou `true`).
3. Abrir o Premiere: a porta 3000 escuta em `127.0.0.1` E `[::1]` (no Mac, só `[::1]`).
⚠️ O `path` do projeto no `getOpenProjects` vem `\\?\D:\…` no Windows (`cicloassist/caminhos.py`).

## O caminho do Test Host Plugin (o do Mac; no Windows também funciona)


1. Premiere (Beta) 27.1+ aberto e logado. **Ctrl+F12** (Mac: Cmd+F12) abre o **Console**.
2. Menu ☰ do Console ▸ **Open Test Host Plugin**. Na 1ª vez: pasta de testes = ESTA pasta
   (`tools/premiere_mcp`), pasta de assets = qualquer pasta vazia. ⚠️ Antes de rodar, acrescente
   `outputDirectory: <pasta vazia>` em `Documentos/Adobe/test-host-plugin/config.yaml` — sem ele a
   tela do plugin quebra calada ao rodar e só volta reiniciando o Premiere. ⚠️ Windows: o Test Host CHECA O TIPO — os
   scripts declaram `__dirname` (sem isso, TS2304 e nada roda), e sem `__dirname` em tempo de execução os `.json`
   vão para a pasta de onde o Premiere foi lançado, não para cá.
3. **Run** ▸ `liga_mcp.test.ts`: liga a beta feature `PPro.MCP.EnableMCPServer` (override no
   `Debug Database.txt`), liga o servidor e grava `tools_*.json` / `relatorio.json` aqui.
4. **Feche e reabra o Premiere** (a beta feature só vale depois de reabrir). Conferir:
   porta 3000 escutando em `[::1]` (Windows: `netstat -ano | findstr :3000`).
5. Só no DESENVOLVIMENTO (decisão do autor): **Run** ▸ `sem_senha.test.ts` — vale na hora; vai
   para as prefs ao FECHAR o Premiere.
6. `python spikes/o_mcp_do_premiere.py --saida <pasta>` (sem token) — tem de responder.
7. A suíte e os spikes F0/F3/F4 nesta máquina (`spikes/o_mcp_do_premiere_f0.py`,
   `spikes/no_servico.py`).

⛔ Desfazer: Premiere FECHADO, apagar a linha `dvaappsupport.feature.PPro.MCP.EnableMCPServer` do
`Debug Database.txt` das preferências do Premiere.
⛔ Os `.json` que os scripts gravam aqui têm o catálogo da Adobe e (no relatório) o token: NÃO
versionar (`.gitignore` desta pasta).
