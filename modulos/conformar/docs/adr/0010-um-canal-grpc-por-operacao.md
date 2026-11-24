# 0010 — Um canal gRPC por operação, nunca guardado

**Status:** ativa · Data: 2026-08-10

**Contexto:** `MediaComposer` (`avid/mcapi.py`) fala gRPC insecure com o backend do
Media Composer em `[::1]:9100`. A primeira versão guardava a instância do canal no
serviço, para reaproveitar entre chamadas.

**O que deu errado:** o editor abre e fecha o Media Composer enquanto o painel do
plugin segue aberto. Um canal gRPC que sobreviveu ao processo do outro lado falha com
`AttributeError: 'NoneType' object has no attribute 'unary_unary'` — um erro que não
parece, de forma nenhuma, "o MC fechou".

**Decisão:** `MediaComposer` é um *context manager*, e o canal só existe dentro do
`with`. Cada operação abre e fecha o seu.

**Por quê:** a correção óbvia (abrir um canal e mantê-lo vivo com retry) trocaria um bug
raro por um sintoma enganoso toda vez que o MC reiniciar. O canal é barato de abrir; a
confusão de diagnosticar um erro que não parece o que realmente é, não. Consistente com
[ADR 0008](0008-uma-sessao-por-vez-progresso-lido-por-sse.md): o serviço nunca assume
que o estado do lado de fora (MC aberto, sessão em andamento) continua o mesmo entre uma
leitura e a próxima.
