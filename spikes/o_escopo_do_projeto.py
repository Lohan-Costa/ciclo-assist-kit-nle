r"""O recorte da busca com o Media Composer ABERTO: é o projeto dele, e custa quanto?

    python spikes/o_escopo_do_projeto.py            (exige MC aberto)
    python spikes/o_escopo_do_projeto.py --termo close

Sai `0` se o escopo vier do PROJETO ABERTO e nenhum resultado de busca escapar dele.

## O que este spike prova, e por que não dá para provar sem o MC

`avid/escopo.py` tem dois caminhos, e só um deles é o certo:

| origem | quando acontece | vale? |
|---|---|---|
| `projeto` | o MC respondeu: as bins lidas são as do projeto ABERTO | ⭐ é este |
| `foto` | o MC não respondeu: a última varredura, que pode ser de OUTRO projeto | só como recurso |

Na máquina de desenvolvimento, com o Media Composer fechado, a suíte inteira exercita o
segundo — e o primeiro, que é o que o editor usa, nunca roda. ⚠️ **Teste que só cobre o
caminho de recurso é teste que aprova o produto pela metade.**

## ⚠️ Isto NÃO abre bin nenhuma

Uma consulta ao projeto (`GetOpenProjectInfo`) e leitura de `.avb` pelo pyavb, que é
instantânea e invisível — nada de `OpenBin`, nada de monitor, nada que mexa na tela de
quem está montando (CLAUDE.md, "para LER, o arquivo").
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.avid import escopo as _escopo           # noqa: E402
from cicloassist.avid.mcapi import McApiErro, MediaComposer  # noqa: E402
from cicloassist.midia import cache as _cache            # noqa: E402
from cicloassist.mcp.ferramentas.mapa import procurar_no_material  # noqa: E402


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--termo", default="close",
                   help="o que procurar na decupagem (padrão: close)")
    args = p.parse_args()

    print("1. O PROJETO, pela API")
    try:
        with MediaComposer() as mc:
            projeto = mc.projeto()
    except McApiErro as e:
        print(f"   ⛔ o Media Composer não respondeu ({e}).")
        print("   Este spike precisa dele ABERTO: é o caminho que ele prova.")
        return 1
    print(f"   {projeto['caminho']}")
    print(f"   {projeto['fps_aprox']} fps · drop_frame={projeto['drop_frame']}")

    print("2. O ESCOPO")
    _escopo.esquecer()
    t0 = time.time()
    escopo = _escopo.agora()
    primeira = time.time() - t0
    t0 = time.time()
    _escopo.agora()
    segunda = time.time() - t0
    print(f"   origem={escopo.origem} · {len(escopo.chaves or ())} masterclipe(s) "
          f"de {escopo.nome_do_projeto}")
    print(f"   primeira leitura {primeira:.2f} s · segunda {segunda:.4f} s (cache)")

    if escopo.origem != "projeto":
        print("   ⛔ o escopo NÃO veio do projeto aberto — é este o defeito a caçar.")
        return 1
    if Path(escopo.projeto) != Path(projeto["caminho"]):
        print(f"   ⛔ o escopo é de {escopo.projeto}, e o projeto aberto é outro.")
        return 1

    print("3. O CACHE, dentro e fora")
    todas = [m.chave for m in _cache.todas()]
    dentro = [c for c in todas if escopo.cobre(c)]
    print(f"   {len(todas)} mídia(s) no cache · {len(dentro)} no projeto · "
          f"{len(todas) - len(dentro)} de fora")

    print(f"4. A BUSCA (termo: {args.termo!r})")
    achados = procurar_no_material(termos=[args.termo], quantos=20)
    fugiram = [a for a in achados.get("achados", []) if not escopo.cobre(a["chave"])]
    print(f"   {achados['quantos']} achado(s) · "
          f"{achados['material_decupado']} decupadas de {achados['material_no_cache']} "
          f"no recorte")
    # ⭐ A prova: a promessa da ferramenta é que NADA de fora do projeto sai na resposta.
    if fugiram:
        print(f"   ⛔ {len(fugiram)} achado(s) fora do projeto escaparam do filtro:")
        for a in fugiram[:3]:
            print(f"      {a['midia']} ({a['chave'][:12]})")
        return 1
    print("   nenhum achado fora do projeto")

    print("5. O QUE A RESPOSTA DIZ AO MODELO")
    print(f"   {achados['escopo']}")
    print(f"   {escopo.aviso}")
    print("\n✅ o recorte é o projeto aberto, e a busca não sai dele")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
