"""Separa os bancos: tira os apelidos que faziam uma mídia responder por dois editores.

    python tools/separar_bancos.py            # só mostra o que faria
    python tools/separar_bancos.py --fazer    # remove

⭐⭐ **Por que isto existe** (decisão do editor, 2026-09-21):

    *"O banco do Premiere nunca pré-carrega o material de cache do Avid. A busca no
    Premiere nunca deve mostrar ou se referenciar a alguma coisa do Media Composer, e
    nenhum arquivo da Avid MediaFiles pode ser exibido na lista."*

Até aqui, o casamento por CONTEÚDO criava um **apelido**: as duas mídias viravam UMA
pasta. Com isso o `.mp4` que o Premiere aponta passava a responder pela entrada do Avid —
com o nome da bin do Avid e os caminhos `D:/Avid MediaFiles/…` dentro. MEDIDO no projeto
dele: `B001_03150112_C001.mp4` caía em `B001_03150112_C001`, cujos arquivos são três
OP-Atom. **Recorte nenhum conserta isso**: a entrada ERA a do Avid.

⇒ Hoje o casamento continua valendo, e o que mudou é a consequência: `identidade
.aproveitar()` cria a entrada do banco de quem pediu e **copia** o trabalho. Este script
remove os apelidos da era anterior, que ainda sequestram a chave.

⚠️ **Nada de mídia é apagado.** Sai só o registro do apelido, do manifesto e do índice.
O pior que acontece é o casamento ser medido de novo na próxima vez — segundos.

⚠️ **O critério é ter `medida`**: apelido com medida nasceu do casamento por conteúdo
(`identidade.achar`), que é o que junta dois arquivos DIFERENTES. Os do Avid interno
(`mob_id` de um master AMA, `take.py`) não têm, e ficam. Cada linha é impressa com o
arquivo, para dar para conferir antes de mandar fazer.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.stdout.reconfigure(encoding="utf-8")

from cicloassist.midia import cache as C  # noqa: E402


def cruzados(m: C.Midia) -> list[dict]:
    """Os apelidos desta mídia que vieram do casamento por conteúdo."""
    return [a for a in m.apelidos() if a.get("medida") not in (None, "")]


def main() -> int:
    fazer = "--fazer" in sys.argv
    raiz = C.raiz()
    print(f"cache: {raiz}\n")

    achados: list[tuple[C.Midia, dict]] = []
    for m in C.todas():
        for a in cruzados(m):
            achados.append((m, a))

    if not achados:
        print("nenhum apelido de casamento por conteúdo: os bancos já estão separados.")
        return 0

    print(f"{len(achados)} apelido(s) a remover:\n")
    for m, a in achados:
        arquivo = Path(str(a.get("arquivo") or "")).name or "(sem arquivo registrado)"
        print(f"  {m.nome[:34]:34s} [{m.origem:8s}]  <- {arquivo}")
        print(f"      chave {str(a.get('chave'))[:16]}…  medida {a.get('medida')}  "
              f"fonte {a.get('fonte') or '—'}")

    if not fazer:
        print("\n(nada foi tocado — rode com --fazer para remover)")
        return 0

    tirados = 0
    for m, a in achados:
        if m.desapelidar(str(a.get("chave") or "")):
            tirados += 1
    print(f"\n{tirados} de {len(achados)} removido(s). "
          f"Nenhum quadro, vetor ou transcrição foi tocado.")
    print("⭐ O casamento volta a acontecer sozinho na próxima vez que a mídia for "
          "processada — e aí ele cria a entrada do banco certo, em vez de apelidar.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
