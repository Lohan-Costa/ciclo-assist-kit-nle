# ADR 0003 — A aprovação é um botão no painel, e a leitura nunca pergunta

**Data:** 2026-09-10 · **Estado:** aceito, **alterado pelo [ADR 0008](0008-aprovacao-sem-relogio.md)**

> ⚠️ **O que mudou:** a aprovação deixou de BLOQUEAR a chamada. O portão responde na
> hora, o pedido espera o editor sem prazo nenhum, e quem executa a ferramenta depois
> do clique é o serviço — não o CLI. As duas metades da regra abaixo continuam de pé.

## Decisão

`--permission-prompts host` + `--permission-prompt-tool mcp__ciclo__pedir_confirmacao`.
A pergunta é desenhada **dentro do painel**, no Media Composer, onde o editor já está.

E uma allowlist para tudo que só lê:

```
--allowedTools mcp__ciclo__listar_bins,mcp__ciclo__ler_selecao,
               mcp__ciclo__ver_frames,mcp__ciclo__transcrever
```

## As duas metades da regra

- **Nunca perguntar para ler.** Um editor que clica "permitir" quinze vezes para listar
  uma bin para de ler o que está clicando — e aí a pergunta que importava passa batido.
- **Sempre perguntar para escrever.** Criar subclipe, criar bin, importar AAF na timeline.

## O plano é o que se aprova, não a ação

⭐ A confirmação de uma montagem **não** é "posso importar este arquivo?". É o plano de
ações inteiro, item a item, com a procedência de cada corte — take, in/out, de onde veio a
decisão. O editor aprova o resultado que vai acontecer, não a mecânica.

Nada é escrito no projeto até esse sim. E a fase só está pronta quando o **não** também é
respeitado.
