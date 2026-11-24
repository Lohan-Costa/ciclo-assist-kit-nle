# 0004 — Sem matcher visual no plugin; a confirmação é humana

**Status:** ativa · Data: 2026-08-10 (decisão do usuário)

**Contexto:** o RELINKER (predecessor, app externo) confirma candidatos por pHash contra
um vídeo de referência — faz sentido num app que roda **fora** do editor, onde não há
outra forma de conferir visualmente o resultado.

**Decisão:** dentro do Media Composer isso não se aplica. O editor tem a timeline na
tela; o que dezenas de chamadas de `ffmpeg` produziriam para comparação perceptual, ele
confere de graça, olhando.

**Consequência:** `matcher_masters.py` não abre um único arquivo de mídia — trabalha só
sobre o índice de nomes/metadados. O match roda em ~0,04 s para 118 masters (contra
segundos a minutos de um matcher visual). O módulo `frames/` (extração e pHash) segue
existindo no motor, dormente, para a rota `.avb`/App agnóstico
([ADR 0001](0001-plugin-autonomo-dentro-do-editor.md)), onde a premissa "editor com a
timeline na tela" não vale.

Relink forçado (timecode zerado, fps convertido errado) fica para uma etapa própria, com
opções explícitas — o caminho padrão é o relink normal, apoiado em nome exato
([ADR 0005](0005-nome-normalizado-decide-frouxo-e-sugestao.md)).
