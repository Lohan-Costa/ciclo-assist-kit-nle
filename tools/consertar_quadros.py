"""Joga fora os quadros extraídos com busca não confiável — e a decupagem feita sobre eles.

    python tools/consertar_quadros.py            # só lista
    python tools/consertar_quadros.py --fazer    # conserta

⛔⛔ **MEDIDO em 2026-09-17** (banco, `protocolos/mxf/README.md`): num OP-Atom MPEG-2 do
transcode do Media Composer, `ffmpeg -ss t` entrega o quadro **N/2** — o `r_frame_rate` vem
pela metade e os `pts` são inúteis. Até hoje o produto extraía por busca, então os quadros
guardados dessas mídias são de OUTRO ponto do clipe: da primeira metade, na posição errada.

O que este script faz por mídia afetada:

- apaga os `quadros/` e o carimbo de receita (reextrair custa segundos, e agora sai certo);
- move as notas de DECUPAGEM da mídia para `notas_suspeitas.json`, com o motivo. Elas não são
  apagadas: descrevem quadros reais, só que do lugar errado — e quem pagou por elas decide.
  As notas de TAKE (escritas na conversa, sobre um trecho) ficam onde estão.

⚠️ Serviço parado. E vale só para mídia com arquivo à mão: sem o arquivo não dá para saber se
a busca dela era confiável, e mexer no escuro seria pior.

⛔⛔ **E ele só mexe no que é ANTERIOR ao conserto** (`CONSERTO`, revisão de 2026-09-22).
`frames.extrair_varios` decodifica EM ORDEM nesses arquivos desde 17/09, então o que foi
extraído depois está certo — e a mídia continua sendo "de busca não confiável" para sempre.
Sem o corte de data, rodar este script uma segunda vez jogaria fora quadros corretos e,
pior, mandaria para `notas_suspeitas.json` decupagens **certas e pagas com a assinatura do
editor**. Medido nesta máquina em 2026-09-22: ele reencontrava as mesmas 17 mídias, agora com
234 quadros bons e 13 decupagens boas.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from cicloassist.midia import cache as _cache  # noqa: E402
from cicloassist.midia import estagios as _estagios  # noqa: E402
from cicloassist.midia import frames as _frames  # noqa: E402


#: Quando `frames.extrair_varios` passou a decodificar EM ORDEM nestes arquivos. O que
#: nasceu depois disto está certo. ⚠️ Data, e não uma marca no cache, porque o conserto é
#: anterior a qualquer marca que se pudesse inventar agora — e a data é verificável no log
#: do git (`frames.busca_confiavel`, 2026-09-17).
CONSERTO = "2026-09-17"


def afetada(midia: _cache.Midia) -> Path | None:
    """O arquivo de imagem cuja busca não é confiável, se houver."""
    for caminho in midia.manifesto().get("arquivos") or []:
        arquivo = Path(caminho)
        if arquivo.is_file() and not _frames.busca_confiavel(arquivo):
            return arquivo
    return None


def _velho(caminho: Path, corte: float) -> bool:
    try:
        return caminho.stat().st_mtime < corte
    except OSError:
        return False


def consertar(midia: _cache.Midia, fazer: bool, corte: float,
              desde: str) -> dict[str, int]:
    # ⛔ Só o que é ANTERIOR ao conserto: ver o cabeçalho. Um quadro extraído depois saiu
    #   em ORDEM, e a decupagem feita sobre ele é boa — e foi paga.
    quadros = [q for q in sorted(midia.quadros_guardados())
               if _velho(midia.caminho_do_quadro(q), corte)]
    notas = [n for n in midia.ler_notas()
             if n.get("escopo") == "midia" and str(n.get("quando") or "") < desde]
    if not quadros and not notas:
        return {"quadros": 0, "notas": 0}
    if fazer:
        pasta = midia.achada()
        if quadros:
            # ⛔ Um a um, e não a pasta inteira: ela pode ter quadros NOVOS (extraídos em
            #   ordem, corretos) ao lado dos velhos, e `rmtree` levaria os dois.
            for q in quadros:
                midia.caminho_do_quadro(q).unlink(missing_ok=True)
            if not midia.quadros_guardados():
                (pasta / f"gerador.{_estagios.QUADROS}.json").unlink(missing_ok=True)
        if notas:
            suspeitas = pasta / "notas_suspeitas.json"
            de_antes = json.loads(suspeitas.read_text(encoding="utf-8")) if suspeitas.is_file() else []
            for n in notas:
                n["motivo"] = ("feita sobre quadros extraídos por busca não confiável "
                               "(o ffmpeg entregava o quadro N/2 neste arquivo)")
            _cache.escrever_atomico(suspeitas, json.dumps(de_antes + notas, ensure_ascii=False,
                                                          indent=1).encode("utf-8"))
            # ⛔ Tira as SUSPEITAS, não todas as notas de mídia: uma decupagem refeita
            #   depois do conserto é boa, e foi paga com a assinatura do editor.
            restantes = [n for n in midia.ler_notas()
                         if n.get("escopo") != "midia"
                         or str(n.get("quando") or "") >= desde]
            # ⛔⛔ `{"notas": [...]}`, que é o formato que `Midia.anotar` grava. Até
            #    2026-09-20 isto gravava a LISTA crua, e `ler_notas` fazia `.get` nela:
            #    4 das 332 mídias desta máquina derrubavam a aba Vetores INTEIRA (500,
            #    "0 mídias" com o disco cheio). Achado no Assist anterior, que compartilha
            #    este cache. O leitor passou a aceitar os dois formatos; o gravador, não.
            _cache.escrever_atomico(pasta / "notas.json",
                                    json.dumps({"notas": restantes}, ensure_ascii=False,
                                               indent=1).encode("utf-8"))
    return {"quadros": len(quadros), "notas": len(notas)}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--fazer", action="store_true")
    ap.add_argument("--desde", default=CONSERTO, metavar="AAAA-MM-DD",
                    help=f"só o que é anterior a esta data (padrão: {CONSERTO}, quando a "
                         f"extração passou a decodificar em ordem)")
    args = ap.parse_args()

    corte = time.mktime(time.strptime(args.desde, "%Y-%m-%d"))
    print(f"cache: {_cache.raiz()}")
    print(f"mexendo só no que é anterior a {args.desde} — depois disso a extração já saía "
          f"em ordem, e a decupagem feita sobre ela é boa (e foi paga).\n")
    total = {"midias": 0, "quadros": 0, "notas": 0, "intactas": 0}
    for midia in _cache.todas():
        arquivo = afetada(midia)
        if arquivo is None:
            continue
        conta = consertar(midia, args.fazer, corte, args.desde)
        if not conta["quadros"] and not conta["notas"]:
            # ⚠️ Mídia de busca não confiável CONTINUA aparecendo aqui para sempre; o que
            #   muda é não haver nada velho nela. Contar é honesto; listar seria ruído.
            total["intactas"] += 1
            continue
        total["midias"] += 1
        total["quadros"] += conta["quadros"]
        total["notas"] += conta["notas"]
        print(f"  {midia.nome or midia.chave[:12]}: {conta['quadros']} quadro(s), "
              f"{conta['notas']} decupagem(ns)  ({arquivo.name})")
    print(f"\n{total['midias']} mídia(s) a consertar, {total['quadros']} quadro(s), "
          f"{total['notas']} decupagem(ns)"
          + (f"; {total['intactas']} de busca não confiável já estão em dia"
             if total["intactas"] else "")
          + ("" if args.fazer else "  — nada foi tocado; use --fazer"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
