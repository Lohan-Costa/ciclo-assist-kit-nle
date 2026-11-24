# 0017 — INSERT PARA COR/VFX: o botão Coletar lê a cópia do editor

**Status:** decidido com o usuário (2026-09-24) · implementado (Windows) · Data: 2026-09-24
**Relaciona-se com** o [ADR 0016](0016-magic-link-pasta-combinada.md) e o
[ADR 0015](0015-export-le-a-bin-nunca-chama-exportfile.md).

---

## Contexto

O editor precisa mandar **só alguns clipes** para a cor ou o VFX, cada um na posição exata de
TC e trilha, com uma lista **aditiva** (X por item, Limpar lista). Mas a API do Media Composer
**não lê a seleção de segmentos nem as marcas IN/OUT**. Foi medido com o usuário em 2026-09-24
(banco, `plugins/avid-panel-sdk/copia-da-timeline.md`).

Alternativas descartadas pelo usuário:
- **Cursor:** não escolhe um V1 embaixo de um filtro na V2.
- **Marcadores:** caminho muito específico, e marcador serve a muitas outras coisas.

## Decisão

**O botão Coletar é um coletor do que estiver selecionado** (desenho do usuário). Por dentro,
o roteiro medido:

1. **`Ctrl+0` → `Ctrl+C`** por teclado (`teclado.py`, `SendInput`; `Cmd` no Mac por `osascript`,
   `pendente`), só com o Media Composer em primeiro plano. O `DoCommand(6224)` não copiou.
2. **`DoCommand(6292 "Clipboard Contents")`**. A cópia abre no **monitor ativo**. O painel acha a
   cópia pelo mob que **mudou** e devolve a sequência ao Record se ela foi tomada, e a
   sequência volta no mesmo ponto.
3. **`CreateSubClip(use_clip_bounds=True, end_frame=-1, create_new_sequence=True)`** numa bin do
   painel, `zMagicLink/coleta`, seguido de Save e da leitura da `.avb` (ADR 0015). Resultado:
   125 de 125 entradas iguais à subsequência arrastada à mão.
4. A bin é **apagada e recriada vazia** a cada coleta. Não há refresh do projeto pela API, e isso
   evita que ela fique vermelha.
5. A cópia diz **quais** segmentos. Nome, master, efeitos e velocidade vêm da **sequência**
   (`carta_aberta.insert.selecao_da_copia`).

Regras da lista (`coleta.Coleta`):
- **Mais de uma trilha:** OK | Cancelar, dentro do painel.
- **A mesma cópia de novo:** "nada novo". Sem seleção, o Avid mantém a cópia anterior (medido).
  Apertar de novo em seguida insiste.
- **Cópia de outra sequência:** recusada.
- **Lista de outra sequência:** pergunta antes de trocar.

No Resolve, o insert tem importação própria: a timeline inteira, com o não escolhido virando
**vazio**, o **mesmo TC** e as **mesmas trilhas**. Transição só entre escolhidos (ou fade de um
escolhido); aparo no corte ou no trecho. **Clipe com velocidade nunca é aparado** e vai com
aviso. Tudo isso fica em `filtrar_insert`. O nome é `INSERT PARA COR|VFX — seq — data`, na
pasta **Inserts**.

## Consequências

- ⚠️ **A cópia do Avid é o TRECHO** do primeiro ao último segmento selecionado em cada trilha,
  confirmado com um gabarito do usuário. Clipes separados se coletam um por vez; a sobra sai no X.
  O painel diz isso.
- A timeline **pisca** durante a coleta (~8 s medidos), e o monitor Source pode mudar.
- O teclado é o **último recurso**: a tecla vai para a janela da frente, e o painel confere
  antes de digitar.
- Handles (margem de mídia) ficam para depois. O `CreateSubClip` tem `add_frames_at_head/end`.
