# ADR 0006 — O editor nunca vê um terminal

**Data:** 2026-09-10 · **Estado:** aceito e implementado (`instalar.ps1`)

## Decisão

O instalador detecta o Claude Code, conduz o login **uma vez**, e some. É aqui que o
produto ganha ou perde o usuário não-técnico — um editor não abre PowerShell.

⭐ **Correção de 2026-09-10: o caminho é `claude auth`, não `setup-token`.** Medido:

```
claude auth status   → JSON com loggedIn, authMethod, subscriptionType, email
claude auth login    → conduz o login
```

O `auth status` é **instantâneo e não gasta nada da assinatura** — diferente de mandar
uma pergunta qualquer só para descobrir se há login, que era a alternativa óbvia e cara.
E ele responde de quebra qual é o plano, o que permite avisar quem está numa conta de
chave de API que vai pagar por token.

⚠️ Isto também **apaga o risco em aberto abaixo**: a validade do `setup-token` deixa de
importar, porque não é mais o mecanismo. O que resta é o comportamento do login normal,
que é o mesmo de qualquer sessão do Claude Code.

## ~~O risco do `setup-token`~~ — resolvido por não usá-lo

O `--help` descreve o `setup-token` apenas como *"long-lived"* e *"requires Claude
subscription"*, sem dizer quanto tempo — e esta seção existia para lembrar de medir isso
antes da fase 6.

✅ **Deixou de importar:** o instalador usa `claude auth`, que é o login normal do Claude
Code. A credencial vive onde o CLI a guarda, e renová-la é o mesmo gesto de sempre.

## ✅ O fluxo de primeira vez, exercitado sem deslogar ninguém

⭐ **`CLAUDE_CONFIG_DIR` isola o armazenamento de credencial.** Apontando-o para uma pasta
temporária, `claude auth status` responde `loggedIn: false` — o estado exato de uma máquina
nova — **sem tocar na credencial real**.

Isso importa porque a alternativa era `claude auth logout`, que desloga o CLI de verdade.
Numa máquina onde o próprio Claude Code está trabalhando, isso derruba a sessão em curso.

Rodado em 2026-09-10, com `instalar.ps1 -Conferir`:

| credencial | o instalador diz |
|---|---|
| isolada (máquina nova) | *"está instalado mas você ainda não entrou na sua conta"* + oferece o login |
| real | *"Conta conectada — <email> · pro"* |

⚠️ **O que continua sem exercício:** a tela de login em si (`claude auth login` abre o
navegador). É fluxo do próprio Claude Code, não nosso — o que era nosso, a **detecção e a
condução**, está conferido nos dois estados.

## ⚠️⚠️ "Tenho o Claude instalado" não quer dizer que temos motor

**Confirmado em 2026-09-10, nesta máquina.** O app de desktop e o CLI são **dois
instaladores diferentes**, e ter um não dá o outro:

```
app desktop   %LOCALAPPDATA%\AnthropicClaude        (com Cowork configurado)
CLI           %USERPROFILE%\.local\bin\claude.exe   (220 MB, instalador próprio)
```

⭐ **É a armadilha de onboarding mais provável do produto**, e ela não parece um erro:
quem instalou o app tem o Claude aberto na tela, paga a assinatura, e razoavelmente
conclui que está pronto. Só que `shutil.which("claude")` devolve `None`, e o painel abre,
conversa e não responde nada.

O que o editor vê hoje, e está correto mas é insuficiente:

> *"O Claude Code não foi encontrado nesta máquina. Instale-o e faça login uma vez para o
> Ciclo Assist funcionar."*

⛔ **O instalador precisa distinguir TRÊS estados, não dois.** Tratá-los como um só manda
a pessoa pelo caminho errado:

| estado | o que dizer |
|---|---|
| nenhum Claude na máquina | instale o Claude Code, e o que é a assinatura |
| **app instalado, CLI ausente** | você já tem conta; falta **este** programa — e ele é outro download |
| CLI presente, sem login | rode o login uma vez; não precisa instalar nada |

O `dev.ps1` já detecta a ausência do CLI e avisa. Ele **não** distingue o caso do meio —
e é justamente o que mais vai acontecer com cliente.

## Fallback

Quem não tem assinatura entra por chave de API (ADR 0001), com o custo explicitamente
dele. A interface do motor é a mesma; muda a implementação por trás.

## ✅ 2026-10-31 — o login lançado pelo APP, sem console, numa pasta própria (F0 do Assist operador)

`spikes/a_conta_do_app.py`, CLI 2.1.316, Windows 11: `claude auth login --claudeai` com
`CLAUDE_CONFIG_DIR` descartável, `CREATE_NO_WINDOW`, `stdin=DEVNULL` e sem nenhuma variável de
credencial no ambiente.

- abre o navegador em **0,2 s** e imprime a URL de reserva; o prompt `Paste code here if prompted >`
  aparece, mas **não foi preciso colar nada**: o editor entrou no navegador e o CLI concluiu sozinho
  (`Login successful.`, rc 0, **5,9 s** com o navegador já logado no claude.ai);
- `auth status` depois: `loggedIn: true`, `authMethod: claude.ai`, `subscriptionType: pro`;
- a credencial fica em `<CLAUDE_CONFIG_DIR>\.credentials.json` — **o app nunca o lê** (regra da
  Anthropic, plano 2026-10-31); só o `auth status` diz se há conta.
- ⚠️ Não medido: o navegador SEM sessão no claude.ai (o editor digita e-mail/código — deve só demorar
  mais), e o caminho de reserva quando o navegador não abre (aí o código colado seria o único caminho,
  e o app não pode intermediá-lo: dizer ao editor para usar o navegador padrão).
- ⚠️ macOS: `pendente`.

⇒ O desenho da conta do plano se sustenta: Entrar = este comando; Sair = `claude auth logout` na mesma pasta.
