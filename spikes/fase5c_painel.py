"""Fase 5c — o corte zero de ponta a ponta, pelo caminho do painel.

    python spikes/fase5c_painel.py

Finge ser o painel: abre o SSE de `/conversar`, mostra o plano exatamente como o cartão de
aprovação o mostraria, aprova, e confere se a sequência apareceu.

⭐ **O que este spike prova e nenhum outro prova:** que o Claude consegue PROPOR um plano
válido — com take, in/out em frames e o porquê de cada escolha — sem ninguém traduzir para
ele. Se o plano vier recusado pelo validador, o problema é a descrição da ferramenta, não o
modelo.

Exige o serviço no ar (`python -m cicloassist.servico`) e o Media Composer aberto.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

SERVICO = "http://127.0.0.1:7824"
NOME = "C07 ESQUELETO"

PERGUNTA = (
    "Na bin CENAS/C07.avb do projeto aberto, monte um corte zero curto da cena 7 "
    f"chamado '{NOME}'. Use dois takes do plano 3, cerca de 8 segundos de cada, "
    "começando um pouco depois da claquete. O projeto é 23.976, então converta os "
    "segundos para frames. Diga em cada corte por que escolheu aquele take."
)


def postar(rota: str, corpo: dict, fluxo: bool = False):
    req = urllib.request.Request(
        SERVICO + rota,
        data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json", "Sec-Fetch-Site": "same-origin"},
        method="POST",
    )
    r = urllib.request.urlopen(req, timeout=None if fluxo else 20)
    return r if fluxo else json.loads(r.read())


def mostrar_como_o_cartao(dado: dict) -> None:
    """O mesmo desenho do cartão de aprovação do painel — para eu ver o que o editor vê."""
    print(f"\n    ┌─ Posso {dado['ferramenta']}?")
    for k, v in (dado.get("entrada") or {}).items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            print(f"    │  {k}: {len(v)} itens")
            for i, item in enumerate(v, 1):
                curtos, longos = [], []
                for cv in item.values():
                    if cv in (None, ""):
                        continue
                    t = str(cv)
                    (longos if len(t) > 34 else curtos).append(t)
                print(f"    │   {i}. {' · '.join(curtos)}")
                for t in longos:
                    print(f"    │      {t}")
        else:
            print(f"    │  {k}: {str(v)[:70]}")
    print("    └─")


def main() -> int:
    try:
        urllib.request.urlopen(SERVICO + "/saude", timeout=5)
    except (urllib.error.URLError, OSError):
        sys.exit("o serviço não está no ar. Rode `python -m cicloassist.servico`.")

    fluxo = postar("/conversar", {"pergunta": PERGUNTA}, fluxo=True)
    tipo, ferramentas, texto, pedidos = None, [], [], []

    for bruta in fluxo:
        linha = bruta.decode("utf-8", "replace").rstrip("\n")
        if linha.startswith("event: "):
            tipo = linha[7:]
            continue
        if not linha.startswith("data: "):
            continue
        dado = json.loads(linha[6:])

        if tipo == "ferramenta":
            ferramentas.append(dado["nome"])
            print(f"  → {dado['nome']}")
        elif tipo == "texto":
            texto.append(dado["texto"])
        elif tipo == "aprovacao":
            pedidos.append(dado)
            mostrar_como_o_cartao(dado)
            print("\n    ⇠ clicando em PODE FAZER")
            print("      ", postar("/responder", {"id": dado["id"], "permitido": True}))

    print(f"\n--- o que o Claude disse ---\n{''.join(texto).strip()[:900]}")

    # A prova final: a bin existe e o Media Composer a conhece?
    from cicloassist.avid.mcapi import McApiErro, MediaComposer

    arquivo = NOME.replace(" ", "_") if False else NOME  # o nome do arquivo sai do serviço
    print(f"\n  pediu aprovação . {len(pedidos)}x")
    print(f"  ferramentas ..... {ferramentas}")
    try:
        with MediaComposer() as mc:
            raiz = Path(mc.projeto()["caminho"])
            achadas = sorted(p.name for p in raiz.glob("*.avb") if NOME.split()[0] in p.name)
            print(f"  bins no projeto . {achadas}")
            for nome_bin in achadas:
                try:
                    itens = mc.itens_da_bin(nome_bin, tipos=("AllTypes",))
                    print(f"    {nome_bin}: {[i.nome for i in itens]}")
                except McApiErro:
                    print(f"    {nome_bin}: (fechada)")
    except McApiErro as e:
        print(f"  (não consegui conferir: {e})")

    passou = bool(pedidos) and "montar_corte" in ferramentas
    print(f"\n  {'PASSOU ✓' if passou else 'FALHOU ✗'} — o Claude propôs um plano e o "
          f"portão o mostrou corte a corte")
    return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
