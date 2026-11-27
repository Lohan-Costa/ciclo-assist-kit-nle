"""O CONFORMAR (Avid → Premiere) pelo escritor da Carta, ponta a ponta (plano 2026-11-26, etapa 1).

    .venv/bin/python spikes/conformar_pela_carta.py <bin_SEQ.avb> <sequência> <pasta de saída> <nome do projeto>

Lê a sequência da bin como o Conformar (`segmentos.ler_timeline_de_arquivo` + `montar_midia`, o caminho AMA da bin como
o arquivo casado), monta o envio (`premiere_montagem.envio_para_a_carta`), abre um projeto NOVO e versionado no Premiere
(cópia do vazio 26.0.2), pede ao NÚCLEO (`/nucleo/conformar/premiere`, com o token — o mesmo pedido que a rota
`/premiere/montar` do Conformar faz) e renderiza a sequência que entrou (`<projeto>.mov`), para medir.
Exige: o serviço do Ciclo Assist no ar (com a rota nova), o Premiere aberto com a ponte.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
FAMILIA = RAIZ.parents[1]
SERV = RAIZ / "modulos" / "conformar" / "plugins" / "media-composer" / "servico"
sys.path[:0] = [str(SERV), str(RAIZ / "modulos" / "conformar" / "motor"), str(FAMILIA / "laboratorio-de-midia")]
VAZIO = RAIZ / "modulos" / "conformar" / "motor" / "prproj" / "moldes" / "vazio 26.0.2.prproj"


def main(avb: str, seq: str, pasta: str, nome: str) -> int:
    from avb_bin import segmentos
    import premiere_montagem as PM
    import premiere_ponte
    from lab.bancadas import premiere as pr
    r = segmentos.ler_timeline_de_arquivo(avb, nome=seq)
    arquivos = {k: m["caminho_na_bin"] for k, m in (r.get("masters") or {}).items()
                if m.get("caminho_na_bin") and os.path.isfile(m["caminho_na_bin"])}
    from media import pmr
    gerenciados = pmr.indice_de(pmr.raizes_de_midia()).por_arquivo or {}   # a gerenciada desta máquina, como o Conformar
    segs, casados, metas = segmentos.montar_midia(r, arquivos, pasta, {}, gerenciados)
    envio = PM.envio_para_a_carta(segs, casados, float(r.get("timeline_fps") or 23.976), seq + " CONFORMAR",
                                  f"spike-{nome}", inicio=r.get("timeline_start_frames"), metas=metas)
    print("segmentos:", len(envio["segmentos"]), "com arquivo:", sum(1 for s in envio["segmentos"] if s["arquivo"]))
    n = 1
    while (Path(pasta) / f"{nome} v{n:02d}.prproj").exists():
        n += 1
    proj = Path(pasta) / f"{nome} v{n:02d}.prproj"
    shutil.copyfile(VAZIO, proj)
    print(pr.executar("""(function(p){ for (var x = app.projects.numProjects - 1; x >= 0; x--)
        app.projects[x].closeDocument(true, false); app.openDocument(p, true, true, true, true);
        return app.project.path; })(%s)""" % json.dumps(str(proj)), timeout=120))
    res = premiere_ponte._nucleo("POST", "/nucleo/conformar/premiere", envio, prazo=1800)
    esc = res.get("escrita") or {}
    print(json.dumps({k: res.get(k) for k in ("ok", "motivo", "conformar", "moldes_fora", "midia_recusada")},
                     ensure_ascii=False))
    print(json.dumps({k: esc.get(k) for k in ("clipes", "transicoes", "velocidades", "rampas", "titulos", "fora",
                                              "offline_no_lugar")}, ensure_ascii=False))
    if not res.get("ok"):
        return 1
    if os.environ.get("SEM_RENDER"):                     # a timeline de produção: só montar e salvar
        print(pr.executar("app.project.save(); app.project.path", timeout=120))
        return 0
    out = str(proj.with_suffix(".mov"))
    print(pr.executar("""(function(o, pre, nome){ var P = app.project, s = null;
        for (var i = 0; i < P.sequences.numSequences; i++) if (P.sequences[i].name == nome) s = P.sequences[i];
        if (!s) return "sem sequência"; P.openSequence(s.sequenceID); P.save();
        return s.exportAsMediaDirect(o, pre, 0); })(%s, %s, %s)""" % (
        json.dumps(out), json.dumps(pr.preset_prores("2026")), json.dumps(envio["nome"])), timeout=900), out)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(*sys.argv[1:5]))
