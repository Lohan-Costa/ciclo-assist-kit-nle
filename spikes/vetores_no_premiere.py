"""Spike — a aba Vetores dentro do Premiere: listar e processar a mídia do projeto dele.

    python spikes/vetores_no_premiere.py [--manter-premiere] [--porta 7834]

⭐ O gesto que o editor descreveu (2026-09-21): *"quando eu importo uma mídia no Premiere e
peço para processar, é aí que o cruzamento acontece"*. Este spike faz exatamente isso, sem
ninguém na frente (receita de `spikes/o_painel_no_premiere.py`):

1. o Premiere abre com a extensão de teste invisível, cria um projeto descartável e importa
   três arquivos na bin `CENAS`:
   - um `.mp4` CONVERTIDO cujo original o Avid já processou (quadros, fala, vetores);
   - um `.wav` de efeito que o Avid já transcreveu;
   - um `.mp4` GERADO agora (testsrc do ffmpeg), que ninguém nunca viu;
2. `GET /vetores?nle=premiere` lista os três como FALTA, com a bin `CENAS`, e nenhuma linha
   do banco do Avid (a cópia do cache tem as duas entradas dele);
3. `POST /vetores/analisar` (vetores) no Premiere: o convertido é APROVEITADO (cópia, sem
   processar), o gerado é vetorizado de verdade;
4. a lista seguinte mostra as entradas novas NESTE banco, com vetor.

O cache é uma CÓPIA das duas entradas do Avid (sem o `audio.wav`), numa raiz descartável;
os dados (modelos) apontam para uma pasta temporária com o modelo de imagem copiado. Sai 0
se tudo passou.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))
sys.path.insert(0, str(RAIZ / "spikes"))

# ⚠️ O import define CICLOASSIST_DADOS/CACHE para a pasta de trabalho DELE — é a que se usa.
import o_painel_no_premiere as base  # noqa: E402

CACHE_REAL = base.CACHE_REAL
TRABALHO = base.TRABALHO
CONVERTIDO = (r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\MIDIAS\CONVERTIDOS\D02_230405\01_CAMERAS"
              r"\CAM_A_Blackmagic-4k\A01\A001_03170214_C001.mp4")
SFX = r"D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\MIDIAS\SFX\231018\10 Car Interior B.wav"
DO_AVID = {CONVERTIDO: "a001_03170214_C001_", SFX: "10 Car Interior B.wav_"}

conferir = base.conferir


def preparar() -> Path:
    """Cópia das entradas do Avid (sem `audio.wav`), o modelo, e o arquivo novo."""
    cache = TRABALHO / "cache"
    cache.mkdir(parents=True)
    for prefixo in DO_AVID.values():
        pasta = next(p for p in CACHE_REAL.iterdir() if p.name.startswith(prefixo))
        shutil.copytree(pasta, cache / pasta.name, ignore=shutil.ignore_patterns("audio.wav"))
    modelos = TRABALHO / "dados" / "modelos"
    modelos.mkdir(parents=True)
    shutil.copy2(CACHE_REAL.parent / "modelos" / "mobilenetv2-12.onnx", modelos)
    novo = TRABALHO / "GERADO_AGORA.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    "testsrc2=size=640x360:rate=25:duration=6", "-pix_fmt", "yuv420p",
                    str(novo)], check=True)
    return novo


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manter-premiere", action="store_true")
    ap.add_argument("--prazo", type=int, default=120)
    ap.add_argument("--porta", type=int, default=7834)
    args = ap.parse_args()

    if not base.porta_livre(args.porta):
        print(f"⛔ a porta {args.porta} está ocupada. Use --porta.")
        return 2
    if base.premiere_aberto():
        print("⛔ o Premiere já está aberto. Feche-o (o spike abre o dele) e rode de novo.")
        return 2
    novo = preparar()

    from cicloassist.midia import cache as C
    from cicloassist.nle.premiere import ponte as PT
    from cicloassist.servico import rotas as R
    from cicloassist.servico import tarefas as T
    from cicloassist.servico.http import Pedido, subir

    def cru(expr: str, prazo: float = 60) -> str:
        pedido = PT._Pedido(id=f"cru{time.monotonic_ns()}", expr=expr)
        with PT._trava:
            PT._fila.append(pedido)
            PT._esperando[pedido.id] = pedido
            PT._trava.notify_all()
        if not pedido.pronto.wait(prazo):
            raise TimeoutError(expr[:80])
        return pedido.resposta or ""

    def vetores() -> dict:
        r = R.rota_vetores(Pedido("GET", "/vetores", {}, b"", {"nle": "premiere"}))
        return json.loads(r.corpo.decode("utf-8"))

    def analisar(estagio: str) -> dict:
        r = R.rota_analisar(Pedido("POST", "/vetores/analisar", {}, json.dumps(
            {"estagio": estagio, "nle": "premiere"}).encode("utf-8")))
        corpo = json.loads(r.corpo.decode("utf-8"))
        t0 = time.monotonic()
        while T.ha_tarefa_viva() and time.monotonic() - t0 < 300:
            time.sleep(0.2)
        corpo["resumo"] = (T.atual().resumo if T.atual() else {}) or {}
        corpo["segundos"] = round(time.monotonic() - t0, 1)
        return corpo

    servidor_http = subir(args.porta)
    extensao = base.instalar_extensao(args.porta)
    print(f"serviço em {args.porta} · extensão de teste em {extensao} · trabalho em {TRABALHO}")
    proc = subprocess.Popen([str(base.PREMIERE)])
    t0 = time.monotonic()
    try:
        while not PT.painel_vivo() and time.monotonic() - t0 < args.prazo:
            time.sleep(0.5)
        if not conferir("1. painel vivo no Premiere", PT.painel_vivo(),
                        f"{time.monotonic() - t0:.0f} s"):
            return 1
        prproj = TRABALHO / "teste.prproj"
        conferir("   app.newProject",
                 cru(f"String(app.newProject({json.dumps(str(prproj))}))") == "true")
        arquivos = [CONVERTIDO, SFX, str(novo)]
        cru("(function(){var b=app.project.rootItem.createBin('CENAS');"
            f"return String(app.project.importFiles({json.dumps(arquivos)}, true, b, false));}})()",
            prazo=120)

        # 2. a lista antes de processar
        t = time.perf_counter()
        d = vetores()
        lista_s = time.perf_counter() - t
        linhas = d["midias"]
        texto = json.dumps(d, ensure_ascii=False)
        conferir("2. três linhas, todas do projeto", len(linhas) == 3,
                 f"{lista_s:.1f} s · " + ", ".join(f"{l['nome']}[{','.join(l['bins'])}]"
                                                    for l in linhas))
        conferir("   todas na bin CENAS", all(l["bins"] == ["CENAS"] for l in linhas))
        conferir("   nenhuma linha do banco do Avid",
                 "Avid MediaFiles" not in texto and len(C.chaves_da_origem("avid")) == 2,
                 f"banco do Avid na cópia: {len(C.chaves_da_origem('avid'))} entradas")
        conferir("   nada analisado ainda NESTE banco",
                 not any(l["vetor"]["tem"] or l["fala"]["tem"] for l in linhas))
        pode = {l["nome"]: l["pode"] for l in linhas}
        conferir("   o que dá para processar", pode.get("GERADO_AGORA.mp4", {}).get("vetores")
                 and pode.get("10 Car Interior B.wav", {}).get("transcricao")
                 and not pode.get("10 Car Interior B.wav", {}).get("vetores"), json.dumps(pode))
        conferir("   o projeto é o do Premiere", d["projeto"].get("editor") == "premiere"
                 and d["projeto"].get("caminho", "").endswith("teste.prproj"),
                 json.dumps(d["projeto"], ensure_ascii=False))

        # 3. vetorizar no Premiere
        r = analisar("vetores")
        resumo = r["resumo"]
        conferir("3. vetores: 2 na fila, 1 aproveitado, 1 feito",
                 r.get("na_fila") == 2 and resumo.get("aproveitadas") == 1
                 and resumo.get("feitas") == 1 and not resumo.get("falharam"),
                 f"{r['segundos']} s · {json.dumps(resumo)}")

        # 4. a transcrição do efeito: aproveitada, sem ASR
        r = analisar("transcricao")
        resumo = r["resumo"]
        conferir("4. transcrição: o .wav aproveitado sem ASR",
                 resumo.get("aproveitadas", 0) >= 1 and not resumo.get("falharam"),
                 f"{r['segundos']} s · na fila {r.get('na_fila')} · {json.dumps(resumo)}")

        # 5. a lista depois
        d = vetores()
        por_nome = {l["nome"]: l for l in d["midias"]}
        conferir("5. três linhas ainda (as entradas novas tomaram o lugar das de falta)",
                 len(d["midias"]) == 3, ", ".join(por_nome))
        conferir("   o convertido com vetor e fala copiados",
                 por_nome.get("A001_03170214_C001.mp4", {}).get("vetor", {}).get("tem")
                 and por_nome.get("A001_03170214_C001.mp4", {}).get("fala", {}).get("tem"),
                 json.dumps({k: (v["vetor"]["tem"], v["fala"]["tem"], v["pasta"])
                             for k, v in por_nome.items()}, ensure_ascii=False))
        conferir("   o gerado com vetor feito aqui",
                 por_nome.get("GERADO_AGORA.mp4", {}).get("vetor", {}).get("tem"))
        conferir("   as entradas novas são do banco do Premiere",
                 len(C.chaves_da_origem("premiere")) >= 3
                 and len(C.chaves_da_origem("avid")) == 2,
                 f"premiere {len(C.chaves_da_origem('premiere'))} · "
                 f"avid {len(C.chaves_da_origem('avid'))}")
    finally:
        if not args.manter_premiere:
            try:
                cru("(function(){app.project.closeDocument(0,0);app.quit();return 'ok';})()",
                    prazo=15)
            except Exception as e:  # noqa: BLE001
                print(f"  (fechar pelo ExtendScript falhou: {e})")
            try:
                proc.wait(timeout=40)
            except subprocess.TimeoutExpired:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True)
        time.sleep(2)
        shutil.rmtree(extensao, ignore_errors=True)
        servidor_http.shutdown()
        print(f"extensão de teste removida: {not extensao.exists()} · trabalho em {TRABALHO}")

    criterio = [ok for _, ok, _ in base.resultados]
    return 0 if criterio and all(criterio) else 1


if __name__ == "__main__":
    raise SystemExit(main())
