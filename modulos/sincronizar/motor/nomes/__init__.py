"""Nomes por padrão — o motor de wildcard do app, e de ninguém em particular.

⭐⭐ **Esta camada não sabe o que é Avid, claquete, subclipe ou aba.** É essa
ignorância que a torna reusável: a aba Renomear é o primeiro consumidor, o nome do
subclipe e o da bin de cena vêm depois, e o que vier depois disso não vai precisar
mexer aqui.

- `template` — `padrão + campos → texto`. Função pura, sem I/O.
- `campos`   — de onde vêm os valores (colunas do Avid, o mob, e os derivados).

⚠️ A dependência é de mão única: `campos` importa `template` (para normalizar os nomes
de campo do mesmo jeito), nunca o contrário.
"""
