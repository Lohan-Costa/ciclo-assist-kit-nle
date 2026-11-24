# ADR 0001 — O backend do modelo é a assinatura do editor, via CLI

**Data:** 2026-09-10 · **Estado:** aceito

## Contexto

O `_ASSIST ANTERIOR` previa LLM local e, como alternativa, chave de API. As duas rotas foram
abandonadas: a local não dá conta do raciocínio pedido e a de API põe custo por token no
nosso P&L, além de exigir que cada cliente gerencie uma chave.

## Decisão

O motor é o **`claude` CLI instalado na máquina do editor**, rodando com a credencial da
**assinatura dele**. Nosso serviço sobe `claude -p` como subprocesso.

Uma interface única (`motor/`) com duas implementações. A de chave de API existe como
fallback documentado para quem não tem plano, mas **não é o caminho principal** e é
decidida agora, não depois.

## A outra rota que existia, e por que não é esta

O pedido de origem dizia *"MCP conectado ao app do Claude na função Cowork **ou** o Claude
Code"*. São dois produtos diferentes, e escolhemos o segundo.

⭐ **Mas a escolha não fecha a porta**, porque o nosso servidor MCP é padrão: ele não sabe
quem está do outro lado. Em tese, o editor poderia conversar **no app** e o app chamar as
mesmas ferramentas — `resolver_take`, `ver_frames`, `transcrever`.

Três coisas quebram nesse desenho, e nenhuma é pequena:

1. **O segredo da rota.** Nossa rota é `/mcp/<segredo>`, sorteado **a cada arranque** do
   serviço (ADR 0005). É o que impede uma página web aberta no navegador do editor de
   chamar as nossas ferramentas — e é exatamente o que inviabiliza uma configuração
   estática no app, porque o endereço muda toda vez. Precisaria de outro porteiro.
2. **O portão mudaria de dono.** A fase 3 inteira desenha a pergunta **dentro do painel**,
   com o argumento legível e o "não" respeitado (ADR 0003). No app, quem pergunta é o app,
   com a UI dele. Não é pior; é outro modelo de permissão, e o ADR 0003 deixaria de
   descrever a realidade.
3. **O painel perderia a conversa.** Viraria, no máximo, um mostrador de estado dentro do
   Media Composer — e o critério da fase 2 era o editor perguntar **sem sair do MC**.

⚠️ **E há o que NÃO foi medido:** como o app registra hoje um servidor MCP por HTTP, e se
aceita esse transporte como o CLI aceita. O `claude_desktop_config.json` desta máquina não
declara servidor nenhum — só `coworkUserFilesPath` e preferências —, o que sugere que a
gestão migrou para a interface do app. **Não presumir que funciona.**

Registrado em 2026-09-10 a partir da pergunta *"se o usuário tiver o app e não o CLI, o app
funciona?"*. A resposta é **não**, e o porquê está no ADR 0006.

## Consequências

- O custo do modelo sai do nosso P&L. Cada cliente traz a própria assinatura.
- ⛔ **Nossa credencial não pode ir no instalador** — quebra os termos e o limite de uso.
  "Traga seu próprio Claude" precisa estar na página de vendas, não na letra miúda.
- O onboarding do não-técnico passa a ser risco de produto de primeira ordem (ADR 0006).

## Evidência

Medido em 2026-09-10, Windows 11, Claude Code **2.1.267**, reprodutível por
`spikes/fase0_subprocesso.py`:

```
claude -p "responda apenas: ok"
  --output-format stream-json --include-partial-messages --verbose
  --restricted --strict-mcp-config

→ apiKeySource: "none"       OAuth da assinatura, sem chave de API
→ 22 ferramentas, 0 mcp      Bash / PowerShell / WebFetch ausentes
→ primeiro token   2,12 s
→ turno completo   2,14 s
→ returncode       0
```

⚠️⚠️ **A primeira medida saiu errada por 3 s, e o erro era nosso.** Sem fechar o stdin do
subprocesso, o CLI espera 3 s por dados que nunca chegam **antes** de começar o turno: o
primeiro token saiu em **4,84 s**. Com `stdin=DEVNULL`, **2,12 s**.

O sintoma engana duas vezes: parece lentidão do modelo, e o único aviso sai no **stderr**,
que num serviço em produção ninguém lê. Se essa medida tivesse sobrevivido, teria levado a
otimizar a coisa errada — provavelmente um pool de processos para esconder uma latência
que não existia.

O evento `rate_limit_event` chega **antes** do `system/init` e traz `utilization` das
janelas de 5 h e 7 dias. É o que o painel usa para avisar o editor antes de ele bater no
limite no meio de um corte.
