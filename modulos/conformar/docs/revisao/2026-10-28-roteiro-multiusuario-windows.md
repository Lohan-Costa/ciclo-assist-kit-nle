# Roteiro — teste MULTIUSUÁRIO no Windows (preparado no Mac, 2026-10-28)

Requisito do autor (28/10): **a instalação serve a TODOS os usuários da máquina.** Este roteiro é para a sessão do
Windows executar sem reler o código. Origem: relatório `2026-10-28-revisao-e-pentest-mac.md` §A7.

## O que o código faz hoje (lido no Mac — é o que o teste confirma ou derruba)

| Peça | Onde mora no Windows | De quem é | Risco com 2+ usuários |
|---|---|---|---|
| Serviço (porta do painel) | `127.0.0.1:7823`, literal | **da MÁQUINA** | o 2º usuário a abrir o app não consegue a porta — ou, pior, o app dele fala com o serviço do 1º (dados, token e logs de OUTRO usuário) |
| Dados, cache, logs, token do receptor | `%LOCALAPPDATA%\DeLaPraCa` (`plataforma.pasta_dados`) | do usuário | o token do receptor é do usuário; se o serviço que atende é o do outro, o Resolve lê um token que não bate |
| Painel do MC (`.avpi`) | `%PROGRAMDATA%\Avid\PanelSDKPlugins` | da máquina | instalar com o usuário A pede admin? o B vê? |
| Integração do Resolve (WI) | `%PROGRAMDATA%\Blackmagic Design\DaVinci Resolve\Support\…` | da máquina | idem |
| Extensão do Premiere (CEP) | `%APPDATA%\Adobe\CEP\extensions\<id>` (`integracoes.py:222`) | **do USUÁRIO** | ⚠️ instalada por A, **não existe para B** — quebra o requisito; candidata a ir para a pasta CEP da máquina (`%PROGRAMFILES(X86)%\Common Files\Adobe\CEP\extensions`, pede admin) |
| MC (API gRPC) | `[::1]:9100` | da máquina | dois MCs abertos (A e B) disputam a 9100? |
| ARO (seleção sem Cmd+C, porta 17890) | — | — | **não existe no Windows ainda** (só a dylib do Mac). Fora deste teste; volta quando houver a `.dll` |

## Preparação

- Três contas locais: A (administrador, a de sempre), B (padrão), C (padrão, opcional).
- O app instalado pela conta A. Anotar a versão (`VERSION`).
- Em cada passo: foto da tela + `netstat -ano | findstr "7823 9100"` + `tasklist /fi "PID eq <pid>" /v` (o usuário
  dono do processo).

## Passos

1. **A instala** tudo pelas Configurações do app (MC, Resolve, Premiere). Anotar: pediu admin? Onde gravou cada peça?
2. **A abre o app.** Quem escuta a 7823 (PID, usuário).
3. **Trocar para B sem sair de A** (Iniciar → trocar de usuário). B abre o app.
   - Abriu? Deu erro de porta? A janela de B mostra o quê (o estado de A?)
   - `netstat`: a 7823 continua do processo de A?
   - Em B: o painel do MC aparece? A integração do Resolve aparece? **A extensão do Premiere aparece?** (esperado hoje: NÃO)
4. **B abre o MC** (A não tem MC aberto). O app de B enxerga o MC de B?
5. **A abre o MC também** (voltar para A; os dois com MC). Quem segura a 9100? O app de cada um fala com o MC de quem?
6. **B faz um relink curto** (caso de lab descartável). Onde foram os logs e o cache — `%LOCALAPPDATA%` de B ou de A?
7. **Sair de A** (encerrar a sessão). A 7823 fica livre? O app de B passa a funcionar sozinho?
8. **C** (se houver): só repetir 3 com A e B logados.

## O que decidir com o resultado

- **Porta da máquina:** se o 2º usuário cai no serviço do 1º, o app precisa de uma porta POR USUÁRIO (ou recusar com
  mensagem clara: "o De Lá Pra Cá já está aberto por <usuário> nesta máquina"). Decisão do autor.
- **Premiere:** confirmar e mover a extensão para a pasta da máquina (com admin uma vez), como o MC e o Resolve.
- **A7 (Mac):** o mesmo teste no Mac antes de decidir o dono de `/Library/Application Support/Avid Internal`.
- Registrar no banco (`transversal/matriz-de-plataforma.md`): linha "app servido a vários usuários da mesma máquina",
  os dois lados (o Mac `pendente` até medir).
