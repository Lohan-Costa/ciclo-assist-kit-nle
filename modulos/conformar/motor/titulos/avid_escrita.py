"""O bloco `titulo` da Carta → o MQP Blob de um `Avid Titler+` atual (o sentido que leva ao Avid).

É o espelho de `avid.py::ler` (que LÊ o MQP) e o par de `resolve.py` (que escreve o "Text" do
Resolve). Em vez de montar o banco de ~324 chaves do zero, EDITA um MQP de MOLDE (o template GOLD
capturado em `avb_export/templates.json`, com o texto "T01 BASE"), que o banco diz ser a forma
estável do Title+ (só ~14 de 324 chaves mudam entre títulos — `titler-plus-mqp.json`):

- **texto:** reescreve a sequência de `Character` do `Flow` (o que o MC RENDERIZA; o `_TTEXT` é só o
  nome do clipe na bin — medido no molde: `Character`s soletram "T01 BASE", `_TTEXT` diz "TITLE").
- **estilo:** sobrescreve EM LUGAR o valor que `mqp.valor(lista, chave)` resolve para a caixa
  (`Transform.Position.*`) e para o caractere (`Text.Font.*`, `Material.Main.Base.*`). Sem cirurgia
  de lista nem contadores (o MQP não tem `Count =`): troca só o texto do `Value`.
- **alinhamento:** direto no `Paragraph.Info.Column.Justify/JustifyVertical` do `Flow`.

Unidades do modelo neutro (como o Avid, ver `avid.py`): `corpo` = fração da ALTURA do quadro
(= `Text.Font.Size`); `cor` RGB 0..1; `posicao` = o centro da caixa em ALTURAS de quadro a partir
do centro, Y para cima. O título do Premiere chega com `posicao_resolve` (coords do Resolve); aqui
se faz a volta (inverso de `resolve.py`) e se avisa para conferir — a calibração fina da posição
pede amostras iguais nos dois programas (ainda `pendente`).
"""

from __future__ import annotations

import re

from . import mqp

#: as mesmas faces que o Avid junta ao nome da família (ver `avid.py::fonte`).
BASE_POR_CORPO = 0.354          # o mesmo fator do `resolve.py` (Y da linha de base ↔ corpo)
_UID_BASE = 402550000000000     # base arbitrária para os `UId` (o banco: "UId do blob é ruído")

_VALOR = re.compile(r"(?m)^\t(\S+) = \{\n\t\tValue = (.*?)\n\t\}")
_CHAR_SEQ = re.compile(r"(?s)\n\t\t\tCharacter = \{.*\n\t\t\t\}\n(?=\n\t\t\})")


def _fmt_float(v: float) -> str:
    """Número como o MQP grava: inteiro sem ponto, senão decimal enxuto (sem zeros à toa)."""
    v = float(v)
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.10g}"


def _codigo(ch: str) -> tuple[str, str]:
    """(Name, Code) de um caractere no `Flow`: espaço = `{ }`, nova linha = `0xA`, resto cru.

    Acento vai CRU, em UTF-8: é como o MC grava (medido 2026-10-28 em 574 bins desta máquina: é, ó, Ç, Ã, Ê, Ũ, ’ no
    `Code`). ⚠️ Caractere de CONTROLE (a tabulação que o leitor do Premiere deixa passar) vai na forma da nova linha
    (`Name 0009`, `Code 0x9`): cru, ele cairia numa linha de um formato que usa tab como recuo. Chave `{ } =` no texto:
    `pendente` (nenhuma amostra)."""
    if ch == " ":
        return "{ }", "{ }"
    if ord(ch) < 0x20 or ord(ch) == 0x7F:
        return f"{ord(ch):04x}", f"0x{ord(ch):X}"
    return ch, ch


def _characters(texto: str, plist: int) -> str:
    """A sequência de `Character` (indentação de 3 tabs) para `texto`, mais um `0xA` final — como o
    molde (o leitor `texto_da_caixa` tira a quebra final)."""
    fora = []
    for i, ch in enumerate(list(texto) + ["\n"]):
        nome, cod = _codigo(ch)
        fora.append(
            f"\n\t\t\tCharacter = {{\n\t\t\t\tName = {nome}\n\t\t\t\tPropList = {plist}\n"
            f"\t\t\t\tUId = {_UID_BASE + i}\n\t\t\t\tCode = {cod}\n\t\t\t}}\n"
        )
    return "".join(fora)


_JUSTIFY = {"esquerda": "Left", "centro": "Center", "direita": "Right", "justificado": "Left"}


def _por_lista(m: mqp.Mqp, lista: int, chave: str) -> int | None:
    """O índice (base 0 em `m.valores`) da entrada que `m.valor(lista, chave)` resolve — para
    sobrescrever EXATAMENTE aquela. Espelha a regra do leitor (entrada de mesma chave mais perto do
    número do `Prop`; sem `Prop`, a primeira = o padrão)."""
    if 1 <= lista <= len(m.listas):
        n = m.listas[lista - 1].get(chave)
        if n:
            perto = [i for i, (k, _v) in enumerate(m.valores) if k == chave]
            if perto:
                return min(perto, key=lambda i: abs(i - (n - 1)))
    for i, (k, _v) in enumerate(m.valores):
        if k == chave:
            return i
    return None


def _primeira_caixa(bloco: dict) -> dict | None:
    caixas = bloco.get("caixas") or []
    return caixas[0] if caixas else None


def _posicao_avid(cx: dict, largura: int, altura: int) -> tuple[float, float] | None:
    """(x, y) na convenção do Avid (alturas de quadro a partir do centro, Y para cima). Usa
    `posicao` (já do Avid) quando houver; senão faz a volta do `posicao_resolve` (inverso do
    `resolve.py`), aproximada."""
    p = cx.get("posicao")
    if p:
        return float(p.get("x") or 0), float(p.get("y") or 0)
    pr = cx.get("posicao_resolve")
    if pr:
        xr, yr = pr
        corpo = float(cx.get("corpo") or 0.0833333)
        return (float(xr) - 0.5) * largura / altura, float(yr) - 0.5 - corpo * BASE_POR_CORPO
    return None


def sintetizar(template_mqp: str, bloco: dict, largura: int = 1920, altura: int = 1080) -> tuple[str, list[str]]:
    """O MQP (texto do DB) de um Title+ com o texto e o estilo de `bloco` (a 1ª caixa), editando
    `template_mqp`. Devolve `(mqp, avisos)`."""
    avisos: list[str] = []
    cx = _primeira_caixa(bloco)
    if cx is None:
        return template_mqp, ["título sem caixa de texto: nada a escrever"]
    caixas = bloco.get("caixas") or []
    if len(caixas) > 1:
        avisos.append(f"{len(caixas) - 1} caixa(s) de texto a mais ficaram só na Carta")

    m = mqp.ler(template_mqp)
    if not m.caixas or not m.caixas[0]["caracteres"]:
        return template_mqp, ["molde de Title+ sem caixa/caractere: não dá para escrever"]
    molde = m.caixas[0]
    plist_char = next((c["lista"] for c in molde["caracteres"] if c.get("lista")), 3)
    lista_caixa = molde["lista"]

    # 1) o estilo: (lista, chave) → valor, sobrescrevendo a entrada que o leitor resolve.
    fonte = cx.get("fonte") or {}
    familia = (fonte.get("familia") or "Open Sans").strip()
    estilo = (fonte.get("estilo") or "").strip()
    nome_fonte = "{" + familia + (" " + estilo if estilo else "") + "}"
    cor = (cx.get("cor") or [1, 1, 1])[:3]
    corpo = float(cx.get("corpo") or 0.0833333)

    destinos: dict[int, str] = {}

    def poe(lista: int, chave: str, valor: str) -> None:
        i = _por_lista(m, lista, chave)
        if i is None:
            avisos.append(f"chave {chave} ausente no molde: não escrita")
            return
        destinos[i] = valor

    poe(plist_char, "Text.Font.Name", nome_fonte)
    poe(plist_char, "Text.Font.Size", _fmt_float(corpo))
    for c, canal in zip(cor, ("Red", "Green", "Blue")):
        poe(plist_char, f"Material.Main.Base.{canal}", _fmt_float(c))
    pos = _posicao_avid(cx, largura, altura)
    if pos is not None:
        poe(lista_caixa, "Transform.Position.X", _fmt_float(round(pos[0], 7)))
        poe(lista_caixa, "Transform.Position.Y", _fmt_float(round(pos[1], 7)))
        if not cx.get("posicao"):
            avisos.append("posição do título convertida do Premiere: conferir no Avid")

    # aplica as sobrescritas numa passada (contando as entradas, como o leitor as enumera)
    contador = {"i": -1}

    def troca(mo: re.Match) -> str:
        contador["i"] += 1
        novo = destinos.get(contador["i"])
        if novo is None:
            return mo.group(0)
        return f"\t{mo.group(1)} = {{\n\t\tValue = {novo}\n\t}}"

    novo_mqp = _VALOR.sub(troca, template_mqp)

    # 2) o texto: troca a sequência de `Character` da 1ª caixa.
    chars = _characters(cx.get("texto") or "", plist_char)
    novo_mqp, n = _CHAR_SEQ.subn(lambda _m: chars, novo_mqp, count=1)
    if not n:
        avisos.append("não achei a sequência de Character no molde: texto não escrito")

    # 3) o alinhamento, direto no Paragraph do Flow.
    just = _JUSTIFY.get(cx.get("alinhamento") or "esquerda", "Left")
    novo_mqp = re.sub(r"(\bJustify = )\w+", rf"\g<1>{just}", novo_mqp, count=1)

    return novo_mqp, avisos
