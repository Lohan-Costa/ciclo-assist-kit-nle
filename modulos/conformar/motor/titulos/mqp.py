"""O MQP Blob do Avid Titler+ atual: um banco hierárquico em TEXTO (~50 KB por título).

Medido nas 19 variações T01–T19 (`TITLE PLUS/TITLE EXEMPLOS.avb`, 2026-09-27). Três camadas:

- `PropCache`: uma sequência de valores `Chave = { Value = X }`, numerada a partir de 1. Os
  primeiros são os PADRÕES do estilo (1…319 no T01); depois vêm os valores sobrepostos.
- `List = { Prop = n:Chave … }`, contadas a partir de 1: cada uma junta alguns desses números.
- `Scene › Layer › Flow` (a caixa de texto) e cada `Character` dela apontam para uma lista
  (`PropList = k`). A caixa carrega a posição; o caractere, a fonte, o corpo e a cor.

O valor efetivo de uma chave num objeto é o da sua lista; sem ela, o padrão do `PropCache`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_VALOR = re.compile(r"^\t(\S+) = \{\n\t\tValue = (.*?)\n\t\}", re.MULTILINE)
_LISTA = re.compile(r"^\tList = \{\n(.*?)^\t\}", re.MULTILINE | re.DOTALL)
_PROP = re.compile(r"Prop = (\d+):(\S+)")


@dataclass
class Objeto:
    """Uma caixa de texto (`Flow`) ou um caractere, com a lista de propriedades dela."""
    lista: int = 0
    campos: dict = field(default_factory=dict)


@dataclass
class Mqp:
    valores: list          # [(chave, valor-texto)], posição 0 = número 1
    listas: list           # [{chave: número}], posição 0 = lista 1
    caixas: list           # [dict] uma por Flow: lista, justify, justify_v, caracteres[]
    lista_cena: int = 0    # a lista da CENA: o que vale para o título inteiro (o fundo, `Global.BG.*`)

    def padrao(self, chave: str):
        for k, v in self.valores:
            if k == chave:
                return v
        return None

    def valor(self, lista: int, chave: str):
        """O valor da `chave` para quem aponta a `lista`; sem sobreposição, o padrão.

        ⚠️ O número do `Prop` não bate 1:1 com a posição na sequência (medido: deslocado em 1
        nos valores sobrepostos das T01–T19; alguma entrada não segue o molde `Value =`). Por
        isso a entrada é a de MESMA chave mais perto do número, nunca só o número."""
        if 1 <= lista <= len(self.listas):
            n = self.listas[lista - 1].get(chave)
            if n:
                perto = [i for i, (k, _v) in enumerate(self.valores) if k == chave]
                if perto:
                    return self.valores[min(perto, key=lambda i: abs(i - (n - 1)))][1]
        return self.padrao(chave)


def _bloco(texto: str, nome: str, inicio: int = 0) -> tuple[str, int]:
    """O corpo de `nome = { … }` (chaves balanceadas) a partir de `inicio`."""
    i = texto.find(nome + " = {", inicio)
    if i < 0:
        return "", -1
    j = texto.index("{", i) + 1
    prof = 1
    k = j
    while prof and k < len(texto):
        c = texto[k]
        if c == "{":
            prof += 1
        elif c == "}":
            prof -= 1
        k += 1
    return texto[j:k - 1], k


def ler(texto: str) -> Mqp:
    cache, _ = _bloco(texto, "\nPropCache")
    valores = [(k, v.strip()) for k, v in _VALOR.findall(cache)]
    listas = [{nome: int(n) for n, nome in _PROP.findall(corpo)} for corpo in _LISTA.findall(cache)]
    cena, _ = _bloco(texto, "\nScene")
    caixas = []
    pos = 0
    while True:
        flow, fim = _bloco(cena, "Flow", pos)
        if fim < 0:
            break
        pos = fim
        m = re.search(r"^\t{3}PropList = (\d+)", flow, re.MULTILINE)
        caixa = {
            "lista": int(m.group(1)) if m else 0,
            "justify": (re.search(r"\bJustify = (\w+)", flow) or [None, "Left"])[1],
            "justify_v": (re.search(r"\bJustifyVertical = (\w+)", flow) or [None, "Top"])[1],
            "caracteres": [],
        }
        for corpo in re.findall(r"Character = \{(.*?)\n\t+\}", flow, re.DOTALL):
            lista = re.search(r"PropList = (\d+)", corpo)
            codigo = re.search(r"Code = (.*)", corpo)
            caixa["caracteres"].append({"lista": int(lista.group(1)) if lista else 0,
                                        "codigo": codigo.group(1) if codigo else ""})
        caixas.append(caixa)
    # O fundo em tela cheia (T19 CAIXA) liga-se na própria cena: `PropList` com UM tab.
    m = re.search(r"^\tPropList = (\d+)", cena, re.MULTILINE)
    return Mqp(valores=valores, listas=listas, caixas=caixas, lista_cena=int(m.group(1)) if m else 0)


def texto_da_caixa(caixa: dict) -> str:
    """O texto da caixa pelos `Code` dos caracteres: `{ }` é espaço e `0xA` é nova linha (o
    `_TTEXT` junta as linhas; aqui elas ficam). A quebra no fim da caixa não conta."""
    partes = []
    for c in caixa.get("caracteres") or []:
        cod = c.get("codigo") or ""
        if cod.startswith("0x"):
            try:
                partes.append(chr(int(cod, 16)))
            except ValueError:
                continue
        elif cod.startswith("{") and cod.endswith("}"):
            partes.append(cod[1:-1])
        else:
            partes.append(cod)
    return "".join(partes).rstrip("\n")
