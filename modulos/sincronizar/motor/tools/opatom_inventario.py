"""
Inventário de uma `Avid MediaFiles` — e o gerador da fixture de regressão.

Dois usos:

    python tools/opatom_inventario.py "<pasta>"                 # olhar
    python tools/opatom_inventario.py "<pasta>" --fixture X.json # congelar

O `--fixture` grava os documentos do `ffprobe` **enxutos** (só os campos que o
`media/opatom.py` lê) num JSON. É com ele que `tests/test_opatom.py` roda o
agrupamento sobre centenas de arquivos REAIS **sem tocar na mídia** — o teste
continua valendo no Windows e no Ubuntu do pipeline, onde o disco do usuário não
existe. Ver o cabeçalho do teste.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from media import opatom  # noqa: E402

# Só o que o parser consome. Guardar o documento inteiro incharia a fixture com
# índices e disposições que nenhum teste olha.
CAMPOS_FORMATO = (
    "material_package_umid", "material_package_name", "operational_pattern_ul",
)
CAMPOS_STREAM = ("index", "codec_type", "r_frame_rate", "avg_frame_rate", "time_base",
                 "duration", "duration_ts", "sample_rate", "channels")
CAMPOS_STREAM_TAGS = ("file_package_umid", "timecode", "reel_name")


def enxugar(doc: dict) -> dict:
    ftags = (doc.get("format") or {}).get("tags") or {}
    streams = []
    for s in doc.get("streams") or []:
        # As streams NÃO-essência (as tracks irmãs, que vêm vazias) só precisam
        # existir e estar na ordem certa: é a POSIÇÃO delas que dá o número da
        # track. Guardar duração e base de tempo delas triplicaria a fixture sem
        # que nenhum teste olhasse.
        essencia = s.get("codec_type") in ("video", "audio")
        campos = CAMPOS_STREAM if essencia else ("index", "codec_type")
        st = {k: s[k] for k in campos if k in s}
        if essencia:
            tags = s.get("tags") or {}
            t = {k: tags[k] for k in CAMPOS_STREAM_TAGS if k in tags}
            if t:
                st["tags"] = t
        streams.append(st)
    return {
        "format": {"tags": {k: ftags[k] for k in CAMPOS_FORMATO if k in ftags}},
        "streams": streams,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Inventário de MXF OP-Atom do Avid.")
    ap.add_argument("raiz", nargs="+", help="pasta(s) ou arquivo(s) .mxf")
    ap.add_argument("--fixture", help="grava os probes enxutos neste JSON")
    args = ap.parse_args()

    docs: list[dict] = []

    def progresso(feito, total, caminho):
        print(f"\r  {feito}/{total}", end="", file=sys.stderr, flush=True)

    if args.fixture:
        # Precisamos dos documentos crus, então repetimos o laço do `scan` aqui —
        # de propósito: o `scan` não devolve os probes, e não vamos alargar a API
        # dele só para servir a esta ferramenta.
        caminhos = opatom._mxf_files(args.raiz)
        arquivos = []
        ignorados = []
        for i, caminho in enumerate(caminhos, 1):
            progresso(i, len(caminhos), caminho)
            doc = opatom.probe_file(caminho)
            if doc is None:
                ignorados.append((caminho, "ffprobe não leu o arquivo"))
                continue
            # Os três últimos componentes bastam para o caminho ser único na
            # fixture (pasta-de-mídia/subpasta-numerada/arquivo) e não carregam o
            # caminho absoluto do disco de quem gerou.
            rel = "/".join(Path(caminho).parts[-3:])
            docs.append({"path": rel, "doc": enxugar(doc)})
            lido = opatom.parse_probe(doc, caminho)
            if isinstance(lido, str):
                ignorados.append((caminho, lido))
            else:
                arquivos.append(lido)
        clipes, duplicatas = opatom.group(arquivos)
        res = opatom.ScanResult(clips=clipes, ignored=ignorados, duplicates=duplicatas)
    else:
        res = opatom.scan(args.raiz, on_progress=progresso)
    print(file=sys.stderr)

    total_arquivos = sum(len(c.paths) for c in res.clips) + len(res.ignored) + len(res.duplicates)
    print(f"arquivos vistos     : {total_arquivos}")
    print(f"clipes              : {len(res.clips)}")
    print(f"ignorados           : {len(res.ignored)}")
    print(f"duplicatas          : {len(res.duplicates)}")
    tc = opatom.timecode_report(res.clips)
    print(f"veredicto do TC     : {tc['veredicto']}  "
          f"(com={tc['com_tc']} sem={tc['sem_tc']} distintos={tc['distintos']} "
          f"repetidos={len(tc['repetidos'])} em {opatom.AVID_DEFAULT_TC}={tc['em_padrao_avid']})")

    formas: dict[int, int] = {}
    for c in res.clips:
        formas[len(c.paths)] = formas.get(len(c.paths), 0) + 1
    print(f"tracks por clipe    : {dict(sorted(formas.items()))}")
    print(f"clipes sem vídeo    : {sum(1 for c in res.clips if not c.has_video)}")
    print(f"clipes em {opatom.AVID_DEFAULT_TC}: {sum(1 for c in res.clips if c.tc_is_avid_default)}")

    for motivo in sorted({m for _, m in res.ignored}):
        quantos = sum(1 for _, m in res.ignored if m == motivo)
        print(f"  ignorado ({quantos}×): {motivo}")

    print("\nprimeiros clipes:")
    for c in res.clips[:5]:
        fps = f"{c.fps:.3f}" if c.fps else "—"
        print(f"  {c.name!r:42} v={1 if c.video else 0} a={len(c.audio)} d={len(c.data)} "
              f"fps={fps} tc={c.tc_start} ch={c.channels_total}")

    if args.fixture:
        Path(args.fixture).write_text(
            json.dumps(docs, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        print(f"\nfixture: {len(docs)} probes → {args.fixture}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
