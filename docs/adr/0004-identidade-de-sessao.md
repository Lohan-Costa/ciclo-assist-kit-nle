# ADR 0004 — Uma sessão por projeto do Avid, que sobrevive ao fechamento

**Data:** 2026-09-10 · **Estado:** aceito

## Decisão

`--session-id <uuid derivado do projeto>` e `--resume` na reabertura.

O UUID é derivado de forma determinística do caminho do projeto do Media Composer, então
abrir o mesmo projeto amanhã recupera a mesma conversa sem guardar mapa nenhum.

## E um processo vivo, não um por mensagem

`--input-format stream-json` mantém **um processo por sessão**, alimentado por stdin, em
vez de subir um processo por mensagem.

⚠️ O spike de 2026-09-10 mediu **1,6 s até o primeiro token**, e isso inclui subir o
processo. Num turno de conversa é tolerável; o que não é tolerável é pagar de novo a
montagem de contexto a cada mensagem. Logo o processo vivo entra como **requisito**, não
como otimização posterior.

## O que ainda não se sabe

⚠️ Quanto tempo o processo pode ficar ocioso antes de o CLI encerrar sozinho, e o que
acontece com a sessão quando o Media Composer trava. **Medir na fase 4**, não presumir.
