"""Troca `clapperboard` por `claquete` nas decupagens que já existem — com o GÊNERO certo.

    python tools/reescrever_claquete.py            # mostra cada frase, antes e depois
    python tools/reescrever_claquete.py --fazer    # grava

⭐ Pedido do editor (2026-09-22). A instrução do decupador já pede "claquete" (ver
`midia/termos.json`) e a busca já acha as duas formas; o que sobrava era o texto antigo —
que é o que vai para a coluna "Descrição" do Premiere. MEDIDO no cache: 39 notas (20 do
Avid, 19 do Premiere), 82 ocorrências.

⚠️ **O português tem gênero, e o inglês não tinha:** "segura UM clapperboard" vira "segura
UMA claquete", "é levantADO" vira "é levantADA". As trocas cobrem os contextos MEDIDOS no
cache (artigo e contração antes; particípio depois); o que sobra é impresso para conferir.

⚠️ Só a descrição e as etiquetas. Na coluna Descrição do Premiere, o texto novo entra
sozinho na próxima sincronização: o campo ainda tem exatamente o que nós gravamos (o
`esperado`), então o compare-and-set deixa trocar. Texto que o editor escreveu não é tocado.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import cache as C  # noqa: E402

PALAVRA = r"clapperboards?|clapboards?"

#: artigo/contração masculino → feminino, ANTES da palavra (na ordem: o mais longo antes).
ARTIGOS = {"um": "uma", "o": "a", "do": "da", "no": "na", "ao": "à", "pelo": "pela",
           "dum": "duma", "num": "numa", "os": "as", "uns": "umas", "dos": "das",
           "nos": "nas", "aos": "às", "pelos": "pelas", "este": "esta", "esse": "essa",
           "aquele": "aquela", "seu": "sua", "outro": "outra"}


def _caixa(modelo: str, texto: str) -> str:
    return texto[:1].upper() + texto[1:] if modelo[:1].isupper() else texto


def reescrever(texto: str) -> str:
    def antes(m: re.Match) -> str:
        artigo, palavra = m.group(1), m.group(2)
        plural = palavra.lower().endswith("s")
        return _caixa(artigo, ARTIGOS[artigo.lower()]) + " " + _caixa(
            palavra, "claquetes" if plural else "claquete")

    padrao_artigo = r"\b(" + "|".join(sorted(ARTIGOS, key=len, reverse=True)) + r")\s+(" \
        + PALAVRA + r")\b"
    texto = re.sub(padrao_artigo, antes, texto, flags=re.I)
    # o particípio que concorda: "a claquete é levantado" → "levantada"
    texto = re.sub(r"\b(claquetes?)(\s+(?:é|foi|está|era|são|foram)\s+)(\w+?)(o)(s?)\b",
                   lambda m: m.group(1) + m.group(2) + m.group(3) + "a" + m.group(5), texto)
    # ⚠️ A concordância que fica LONGE da palavra (medido no cache): "levantada e depois
    #    retirado", "que depois é retirado", "segura uma claquete e o bate". Só nas frases
    #    que falam da claquete, e só estas formas — o resto é impresso para conferir.
    frases = re.split(r"(?<=[.!?])(\s+)", texto)
    for i, f in enumerate(frases):
        if re.search(r"\bclaquetes?\b|" + PALAVRA, f, re.I):
            f = re.sub(r"\b(depois (?:é )?|e )retirado\b", r"\1retirada", f)
            f = re.sub(r"\be o bate\b", "e a bate", f)
            frases[i] = f
    texto = "".join(frases)
    texto = re.sub(r"\b(" + PALAVRA + r")\b",
                   lambda m: _caixa(m.group(1), "claquetes" if m.group(1).lower().endswith("s")
                                    else "claquete"), texto, flags=re.I)
    return texto


def main() -> int:
    fazer = "--fazer" in sys.argv
    mudadas = 0
    for m in C.todas():
        notas = m.ler_notas()
        novas, mudou = [], False
        for n in notas:
            d = dict(n)
            if isinstance(d.get("descricao"), str):
                d["descricao"] = reescrever(d["descricao"])
            if isinstance(d.get("etiquetas"), list):
                d["etiquetas"] = [reescrever(e) if isinstance(e, str) else e
                                  for e in d["etiquetas"]]
            if d != n:
                mudou = True
                mudadas += 1
                if not fazer:
                    for a, b in zip(re.split(r"(?<=[.!?])\s+", str(n.get("descricao") or "")),
                                    re.split(r"(?<=[.!?])\s+", str(d.get("descricao") or ""))):
                        if a != b:
                            print(f"  [{m.origem:8s}] {a}\n  {' ' * 10} → {b}")
            novas.append(d)
        if mudou and fazer:
            C.escrever_atomico(m.pasta / "notas.json",
                               json.dumps({"notas": novas}, ensure_ascii=False, indent=1)
                               .encode("utf-8"))
    print(f"\n{mudadas} nota(s) {'reescritas' if fazer else 'a reescrever (rode com --fazer)'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
