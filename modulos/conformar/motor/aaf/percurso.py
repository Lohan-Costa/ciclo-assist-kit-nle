"""Descer numa timeline de AAF sem perder nada pelo caminho.

## Por que isto é um módulo, e não três funções parecidas

O mesmo percurso foi escrito três vezes neste projeto — em `masters.py`, `remap.py` e
`denest.py` — e **cada cópia esqueceu um ramo diferente**, com o mesmo sintoma: nenhum
erro, nenhuma exceção, só um resultado silenciosamente incompleto.

- `masters.py` não descia em `NestedScope` → **zero** SourceClips na trilha de imagem,
  que num flat file do Avid é exatamente isso.
- `denest.py` não descia em `Selector.Alternates` → sete subclipes de som ficavam para
  trás, e o log não registrava falha nenhuma porque eles nunca eram visitados.
- `remap.py` não descia em nenhum dos dois → **zero** referências trocadas depois que o
  achatamento mudou a forma da timeline.

Nenhuma dessas falhas aparece como erro. Todas aparecem como um número menor do que
devia, num relatório que diz "concluído". Por isso o percurso mora num lugar só.

## Os ramos, e por que cada um existe

| ramo | onde os filhos moram | por que importa |
|---|---|---|
| `Sequence` | `.components` | a trilha comum |
| `NestedScope` | **`.slots`** | flat file do Avid: V1 base + V2 de efeitos |
| `OperationGroup` | `InputSegments` | efeito, e o "Audio Gain" que envolve o som |
| `Selector` | `Selected` **e `Alternates`** | no áudio multicam o `Selected` é `Filler` e a fonte real está num alternate |
| `Transition` | `InputSegments`, `OperationGroup` | dissolve |
| `EssenceGroup` | `Choices` | multi-resolução |
"""

from __future__ import annotations

# Atributos que expõem filhos como coleção iterável.
_COLECOES = ("components", "segments", "slots", "tracks")
# Propriedades AAF que só se alcançam por nome.
_PROPRIEDADES = ("InputSegments", "Alternates", "Choices")
# Atributos que expõem um filho único.
_UNICOS = ("segment", "selected")


def componentes(raiz):
    """Todo componente sob um segmento, em qualquer profundidade, incluindo a raiz.

    Percurso **iterativo**, com pilha explícita: uma montagem real aninha NestedScope
    dentro de Selector dentro de OperationGroup fundo o bastante para estourar o limite
    de recursão do Python.

    A identidade (`id`) evita revisitar o mesmo objeto quando a estrutura converge.
    """
    pilha = [raiz]
    visto: set[int] = set()
    while pilha:
        atual = pilha.pop()
        if atual is None or id(atual) in visto:
            continue
        visto.add(id(atual))
        yield atual

        for nome in _COLECOES:
            filhos = getattr(atual, nome, None)
            if filhos is None:
                continue
            try:
                pilha.extend(list(filhos))
            except TypeError:
                pass

        for nome in _PROPRIEDADES:
            try:
                valor = atual.get(nome)
            except Exception:
                continue
            if valor is None:
                continue
            try:
                pilha.extend(list(valor))
            except TypeError:
                pilha.append(valor)

        for nome in _UNICOS:
            filho = getattr(atual, nome, None)
            if filho is not None:
                pilha.append(filho)

        # `Selector.Selected` e a `OperationGroup` de uma `Transition` são propriedades
        # que não aparecem como atributo em todas as versões do pyaaf2.
        for nome in ("Selected", "OperationGroup"):
            try:
                valor = atual[nome].value
            except Exception:
                continue
            if valor is not None:
                pilha.append(valor)


def source_clips(raiz):
    """Só os `SourceClip` sob um segmento."""
    for c in componentes(raiz):
        if type(c).__name__ == "SourceClip":
            yield c


def todos_os_source_clips(f):
    """Os `SourceClip` de todos os mobs de um AAF aberto."""
    for mob in list(f.content.mobs):
        for slot in mob.slots:
            yield from source_clips(slot.segment)
