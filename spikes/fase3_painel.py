"""Fase 3 — o portão pelo caminho REAL do painel.

    python spikes/fase3_painel.py

Este spike **finge ser o painel**: abre o SSE de `/conversar`, espera o evento
`aprovacao` aparecer no meio da resposta, e responde por `/responder` — exatamente o que
os botões fazem. Exige o serviço no ar (`python -m cicloassist.servico`).

⭐ **O critério da fase é o NÃO, não o sim.** Uma aprovação que o modelo contorna é pior
que não ter aprovação nenhuma, porque dá a impressão de controle. Por isso as duas
rodadas, e por isso a segunda confere se a nota **não** foi gravada.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.avid.take import resolver  # noqa: E402
from cicloassist.midia import cache as _cache  # noqa: E402

SERVICO = "http://127.0.0.1:7824"
BIN = r"%USERPROFILE%\Documents\Avid Projects\_Assist anterior\CENAS\C07.avb"
TAKE = "C07_P03-T002"

PERGUNTA = (
    f"Olhe 2 quadros do take {TAKE} da bin {BIN} e depois "
    f"guarde a sua descrição dele com a ferramenta de anotar."
)


def postar(rota: str, corpo: dict, fluxo: bool = False):
    """POST como o painel faz — inclusive o cabeçalho que o porteiro exige."""
    req = urllib.request.Request(
        SERVICO + rota,
        data=json.dumps(corpo, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            # ⚠️ Sem isto o porteiro recusa com 403 (ADR 0005). É o cabeçalho que o
            # QtWebEngine manda sozinho e que nenhuma página web consegue forjar.
            "Sec-Fetch-Site": "same-origin",
        },
        method="POST",
    )
    resposta = urllib.request.urlopen(req, timeout=None if fluxo else 20)
    return resposta if fluxo else json.loads(resposta.read())


def notas_do_take() -> list[dict]:
    take = resolver(BIN, TAKE)
    try:
        return _cache.Midia(take.imagem.mob_id).ler_notas()
    except Exception:
        return []


def rodada(permitir: bool) -> dict:
    antes = len(notas_do_take())
    fluxo = postar("/conversar", {"pergunta": PERGUNTA}, fluxo=True)

    ferramentas, pedidos, texto = [], [], []
    tipo = None
    for linha_bruta in fluxo:
        linha = linha_bruta.decode("utf-8", "replace").rstrip("\n")
        if linha.startswith("event: "):
            tipo = linha[7:]
            continue
        if not linha.startswith("data: "):
            continue
        dado = json.loads(linha[6:])

        if tipo == "ferramenta":
            ferramentas.append(dado["nome"])
        elif tipo == "texto":
            texto.append(dado["texto"])
        elif tipo == "aprovacao":
            pedidos.append(dado)
            print(f"    ⇢ o painel mostrou: \"Posso {dado['ferramenta']}?\"")
            for k, v in (dado.get("entrada") or {}).items():
                print(f"        {k}: {str(v)[:90]}")
            print(f"    ⇠ clicando em {'PODE FAZER' if permitir else 'NÃO'}")
            print("      ", postar("/responder", {"id": dado["id"], "permitido": permitir}))

    depois = len(notas_do_take())
    return {
        "pedidos": len(pedidos),
        "ferramentas": ferramentas,
        "notas_antes": antes,
        "notas_depois": depois,
        "gravou": depois > antes,
        "resposta": "".join(texto).strip(),
    }


def main() -> int:
    try:
        urllib.request.urlopen(SERVICO + "/saude", timeout=5)
    except (urllib.error.URLError, OSError):
        sys.exit(
            "o serviço não está no ar.\n"
            "Rode `python -m cicloassist.servico` noutro terminal."
        )

    print("=" * 72)
    print(f"RODADA 1 — o editor recusa   (take {TAKE})")
    print("=" * 72)
    nao = rodada(permitir=False)
    print(f"\n  pediu aprovação . {nao['pedidos']}x")
    print(f"  gravou .......... {nao['gravou']}   ← precisa ser False")
    print(f"  notas ........... {nao['notas_antes']} → {nao['notas_depois']}")
    print(f"  o Claude disse .. {nao['resposta'][:260]}")

    time.sleep(1)

    print()
    print("=" * 72)
    print("RODADA 2 — o editor permite")
    print("=" * 72)
    sim = rodada(permitir=True)
    print(f"\n  pediu aprovação . {sim['pedidos']}x")
    print(f"  gravou .......... {sim['gravou']}   ← precisa ser True")
    print(f"  notas ........... {sim['notas_antes']} → {sim['notas_depois']}")
    print(f"  o Claude disse .. {sim['resposta'][:260]}")

    passou = (
        nao["pedidos"] >= 1 and not nao["gravou"]
        and sim["pedidos"] >= 1 and sim["gravou"]
    )
    print()
    print(f"  {'PASSOU ✓' if passou else 'FALHOU ✗'} — "
          + ("o botão aparece no painel e o NÃO é respeitado"
             if passou else "ver acima"))
    return 0 if passou else 1


if __name__ == "__main__":
    raise SystemExit(main())
