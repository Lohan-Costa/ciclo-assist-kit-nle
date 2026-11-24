"""A Carta Aberta: a pasta de trabalho de um projeto, compartilhada entre editores e NLEs (plano
`docs/plano/2026-11-11-carta-aberta.md`).

A mídia nunca é copiada nem movida: a Carta guarda REFERÊNCIAS (`.ref.json`, imutáveis, na pasta que o editor
escolheu) e um DIÁRIO de fatos por máquina (`.carta/registro/<máquina>.jsonl`, só acrescenta) com os caminhos de
cada forma da mídia (original, OP-Atom, versão de trabalho) em cada máquina. O estado é a soma dos diários.

- `projeto`: novo/abrir, a máquina, a quarentena.
- `diario`: acrescentar fato, ler todos, somar o estado.
- `referencias`: criar e listar `.ref.json`.
- `anexar`: casar os arquivos de uma pasta com as referências (nome + taxa + TC + quadros).
"""
