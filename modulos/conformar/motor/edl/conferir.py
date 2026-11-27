"""Conferir uma EDL contra a montagem que ela descreve (plano `docs/plano/2026-11-25-edl-para-o-som.md`).

A pergunta é a da casa de som: com SÓ a EDL e os arquivos na mão, cada evento leva ao arquivo, ao trecho e ao canal
certos? A verdade é o plano da montagem (`plano.json` do spike `spikes/edl_som_mc/montar_casos.py`): por evento e por
trilha da sequência, a fonte, o arquivo, a tape (sound roll), o TC de origem e o canal do ARQUIVO.

O veredito por trilha de evento:

- `certo` — o reel leva a UMA fonte, o TC bate, e o canal do arquivo é o número da trilha (a leitura de quem conforma);
- `alerta` — chega-se ao certo, mas não só pelo reel: o reel serve a mais de uma fonte (o mesmo sound roll em dois
  takes, o reel de 8 que corta o nome) e é o TC que desempata;
- `errado calado` — a EDL é bem formada e leva ao lugar errado (ou a lugar nenhum): a trilha não está na lista, o TC
  não é o da fonte, o reel não leva a nenhuma fonte com aquele TC, ou o canal do arquivo NÃO é o da trilha e a EDL não
  diz qual é (o canal da EDL é a TRILHA da timeline — banco `protocolos/edl/README.md`).

    python -m motor.edl.conferir <plano.json> <edl> [<edl> …]      # da pasta do módulo conformar
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .leitura import Edl, ler, quadros

CERTO, ALERTA, ERRADO = "certo", "alerta", "errado calado"


@dataclass
class Linha:
    caso: str
    rec_in: str
    trilha: str             # V1, A1… (a trilha da SEQUÊNCIA)
    veredito: str
    motivo: str
    esperado: str = ""
    lido: str = ""


def _rotulo_edl(trilha: str) -> str:
    """V1 → V; A1 → A; A2 → A2 (a grafia do canal na EDL)."""
    if trilha.startswith("V"):
        return "V" if trilha == "V1" else trilha
    return "A" if trilha == "A1" else trilha


def _candidatas(reel: str, src_in: int, src_out: int, fontes: dict, fps: int, duracao: int) -> tuple[list, list]:
    """(as fontes cujo NOME o reel aponta, as que também têm o trecho src_in–src_out no TC)."""
    pelo_nome = []
    for nome, f in fontes.items():
        tronco = Path(f["arquivo"]).stem
        chaves = {nome, f["arquivo"], tronco, f["arquivo"].upper(), tronco.upper()}
        if f.get("tape"):
            chaves.add(f["tape"])
        if reel in chaves or (len(reel) == 8 and tronco.upper().startswith(reel.upper())):
            pelo_nome.append(nome)
    no_tc = [n for n in pelo_nome
             if quadros(fontes[n]["tc"], fps) <= src_in and src_out <= quadros(fontes[n]["tc"], fps) + duracao]
    return pelo_nome, no_tc


def conferir(edl: Edl, caso: dict, fontes: dict, fps: int = 24, duracao: int = 719) -> list[Linha]:
    out: list[Linha] = []
    nome = caso["sequencia"]
    for ev in caso["eventos"]:
        for trilha, v in ev["trilhas"].items():
            canal = _rotulo_edl(trilha)
            achados = [e for e in edl.eventos if canal in e.canais and e.rec_in == ev["rec_in"]]
            esperado = f'{v["fonte"]} {v["src_in"]}–{v["src_out"]}' + (
                f' canal {v["canal_do_arquivo"]} ({v["microfone"]})' if v.get("canal_do_arquivo") else "")
            if not achados:
                out.append(Linha(nome, ev["rec_in"], trilha, ERRADO, "a trilha não está na EDL", esperado))
                continue
            e = achados[0]
            lido = f"{e.reel} {e.src_in}–{e.src_out} [{e.canal}] {e.clip}".strip()
            if (e.src_in, e.src_out) != (v["src_in"], v["src_out"]):
                out.append(Linha(nome, ev["rec_in"], trilha, ERRADO, "o TC de origem não é o da fonte", esperado, lido))
                continue
            pelo_nome, no_tc = _candidatas(e.reel, quadros(e.src_in, fps), quadros(e.src_out, fps), fontes, fps,
                                           duracao)
            pelo_clip = False
            if v["fonte"] not in no_tc and e.clip:
                # o reel não identifica (o `AX` do Premiere sem tape name): quem conforma ainda pode achar o arquivo pelo
                # FROM CLIP NAME — chega-se, mas não pelo reel (alerta). Multicâmera e nest: nem o nome leva à fonte.
                pelo_nome2, no_tc2 = _candidatas(Path(e.clip).stem if "." in e.clip else e.clip,
                                                 quadros(e.src_in, fps), quadros(e.src_out, fps), fontes, fps, duracao)
                if v["fonte"] in no_tc2:
                    pelo_nome, no_tc, pelo_clip = pelo_nome2, no_tc2, True
            if v["fonte"] not in no_tc:
                motivo = ("o reel não leva a nenhuma fonte" if not pelo_nome
                          else f"o reel leva a {', '.join(pelo_nome)}, não à fonte certa com esse TC")
                if e.clip:
                    motivo += f" (FROM CLIP NAME {e.clip!r})"
                out.append(Linha(nome, ev["rec_in"], trilha, ERRADO, motivo, esperado, lido))
                continue
            numero = 1 if canal in ("A", "V") else int(canal[1:])
            if v.get("canal_do_arquivo") and v["canal_do_arquivo"] != numero:
                out.append(Linha(nome, ev["rec_in"], trilha, ERRADO,
                                 f'a EDL diz {canal} (lido como canal {numero} do arquivo); o usado é o canal '
                                 f'{v["canal_do_arquivo"]} ({v["microfone"]}) — e a EDL não diz', esperado, lido))
                continue
            if pelo_clip:
                out.append(Linha(nome, ev["rec_in"], trilha, ALERTA,
                                 f'o reel {e.reel!r} não identifica a fonte; só o FROM CLIP NAME leva ao arquivo',
                                 esperado, lido))
                continue
            if len(pelo_nome) > 1:
                out.append(Linha(nome, ev["rec_in"], trilha, ALERTA,
                                 f'o reel {e.reel!r} serve a {len(pelo_nome)} fontes ({", ".join(pelo_nome)}); '
                                 f'só o TC desempata', esperado, lido))
                continue
            out.append(Linha(nome, ev["rec_in"], trilha, CERTO, "", esperado, lido))
    return out


def placar(linhas: list[Linha]) -> dict:
    return {v: sum(1 for x in linhas if x.veredito == v) for v in (CERTO, ALERTA, ERRADO)}


def main(argv: list[str]) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    plano = json.loads(Path(argv[0]).read_text(encoding="utf-8"))
    casos = {c["sequencia"]: c for c in plano["casos"]}
    pior = 0
    for caminho in argv[1:]:
        edl = ler(Path(caminho).read_bytes())
        caso = casos.get(edl.titulo.strip())
        if caso is None:
            print(f"⚠️ {Path(caminho).name}: o título {edl.titulo!r} não é de nenhum caso do plano")
            continue
        linhas = conferir(edl, caso, plano["fontes"])
        p = placar(linhas)
        print(f"{Path(caminho).name}: {p[CERTO]} certo · {p[ALERTA]} alerta · {p[ERRADO]} errado calado")
        for x in linhas:
            if x.veredito != CERTO:
                print(f"   {x.veredito:13} {x.rec_in} {x.trilha:3} {x.motivo}")
        pior = max(pior, 2 if p[ERRADO] else 1 if p[ALERTA] else 0)
    return pior


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
