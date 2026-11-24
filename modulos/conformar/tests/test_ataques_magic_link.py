"""Time vermelho × time azul — os ataques ao Magic Link, cada um provado como teste.

Rodar:

    .venv-win/Scripts/python tests/test_ataques_magic_link.py

Cada caso é um ATAQUE escrito pelo time vermelho (2026-09-24). Passa = o ataque foi barrado.
Ver `docs/seguranca/2026-09-24-vermelho-azul-magic-link.md` para o relato completo.

O atacante modelado:
- escreve na PASTA COMBINADA de rede (qualquer um com acesso ao compartilhamento);
- controla uma página web que o editor visita (e o DNS do domínio dela);
- NÃO roda código na máquina do editor (se rodasse, já dirigiria o MC sem credencial — ADR 0007).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor"),
                str(RAIZ / "tests")]

from api.portao import portao  # noqa: E402
from carta_aberta.writer import build_carta_aberta, montar  # noqa: E402
from test_carta_ida_e_volta import leitura_sintetica, mid  # noqa: E402

UNC = r"\\atacante.exemplo\coleta"
ID = "55555555-5555-4555-8555-555555555555"


def carta_base(**extras) -> dict:
    env = {"id": ID, "tipo": "timeline", "remetente": {"maquina": "X"},
           "enviado_em": "2026-09-24T10:00:00-03:00"}
    return montar(leitura_sintetica(), [], "SINTETICA", envio=env, **extras)


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def barrado(rotulo, ok_):
        nonlocal casos
        casos += 1
        print(f"  {'BARRADO ' if ok_ else 'PASSOU!!'} {rotulo}")
        if not ok_:
            falhas.append(rotulo)

    import sessao_receber as R

    def receptor(tmp: Path, docs: dict[str, object]):
        """A caixa de entrada da COR no canal Cor, cheia de `docs` (nome → dict ou bytes).

        Devolve `(dados, caixa)`; a pasta do canal é `caixa.parent`."""
        dados, pasta = tmp / "dados", tmp / "canal-cor" / "para-cor"
        dados.mkdir(exist_ok=True)
        pasta.mkdir(parents=True, exist_ok=True)
        for nome, doc in docs.items():
            corpo = doc if isinstance(doc, bytes) else json.dumps(doc).encode("utf-8")
            (pasta / nome).write_bytes(corpo)
        return dados, pasta

    sem_indice = mock.patch("media.pmr.indice_de", lambda *_a, **_k: SimpleNamespace(por_arquivo={}))

    print("── V1. DNS rebinding: página em 127.0.0.1.atacante.com lê o serviço ──")
    # A página do atacante resolve para 127.0.0.1: o navegador manda Host com o domínio dela
    # e, num GET para a própria origem, Sec-Fetch-Site: same-origin — sem Origin.
    for rota in ("/receber/caixa", "/magic", "/export"):
        r = portao("127.0.0.1.atacante.com:7823", None, "same-origin", None, rota)
        barrado(f"GET {rota} com Host 127.0.0.1.atacante.com", r is not None)
    r = portao("localhost.atacante.com:7823", None, "same-origin", None, "/magic")
    barrado("GET /magic com Host localhost.atacante.com", r is not None)

    print("\n── V2. Carta com 'Source Path' UNC → o DRT manda o Resolve ao host do atacante ──")
    with tempfile.TemporaryDirectory() as tmp:
        doc = carta_base()
        for m in doc["masters"]:
            if (m["avid"].get("colunas_mc") or {}).get("Source File"):
                m["avid"]["colunas_mc"]["Source Path"] = UNC
        dados, pasta = receptor(Path(tmp), {"A__55555555.carta.json": doc})
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados), sem_indice:
            s = R.SessaoReceber()
            s.caixa({"cor": str(pasta.parent)})
            p = s.preparar(ID)
            drt = Path(p["drt"]).read_bytes()
            # O .drt é um zip de XML; basta procurar o host em qualquer entrada.
            import zipfile
            with zipfile.ZipFile(p["drt"]) as z:
                texto = b"".join(z.read(n) for n in z.namelist())
            barrado("o host do atacante NÃO aparece no DRT (MediaFilePath)",
                    b"atacante" not in texto and b"atacante" not in drt)

    print("\n── V3. media_ref.local_path UNC dentro dos segmentos da Carta ──")
    from carta_aberta.reader import ler_carta
    doc = carta_base()
    for sg in doc["segmentos"]:
        if sg.get("media_ref"):
            sg["media_ref"]["local_path"] = UNC + r"\x.mov"
            sg["media_ref"]["url"] = "file://atacante.exemplo/coleta/x.mov"
    c = ler_carta(doc)
    barrado("o reader descarta caminho/URL de mídia vindos da Carta",
            "atacante" not in json.dumps(c.resultado["segments"]))

    print("\n── V4. Bomba de aninhamento: um arquivo derruba a caixa inteira ──")
    with tempfile.TemporaryDirectory() as tmp:
        bomba = b"[" * 200_000 + b"]" * 200_000
        dados, pasta = receptor(Path(tmp), {"bomba.carta.json": bomba,
                                            "boa__55555555.carta.json": carta_base()})
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados):
            s = R.SessaoReceber()
            try:
                cx = s.caixa({"cor": str(pasta.parent)})
                barrado("a caixa sobrevive e ainda lista a Carta boa",
                        len(cx["envios"]) == 1 and len(cx["invalidas"]) == 1)
            except Exception as e:  # noqa: BLE001
                barrado(f"a caixa sobrevive (caiu com {type(e).__name__})", False)

    print("\n── V5. Bomba de trabalho: Carta pequena com segmentos demais ──")
    doc = carta_base()
    modelo = next(sg for sg in doc["segmentos"] if sg.get("mob_id"))
    doc["segmentos"] = [dict(modelo) for _ in range(300_000)]
    from carta_aberta.reader import CartaInvalida
    try:
        ler_carta(doc)
        barrado("300 mil segmentos são recusados antes do writer", False)
    except CartaInvalida:
        barrado("300 mil segmentos são recusados antes do writer", True)

    print("\n── V6. Caixa inundada: milhares de arquivos na caixa do canal ──")
    with tempfile.TemporaryDirectory() as tmp:
        dados, pasta = receptor(Path(tmp), {})
        for i in range(2500):
            (pasta / f"lixo{i:05d}.carta.json").write_bytes(b"{}")
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados):
            s = R.SessaoReceber()
            cx = s.caixa({"cor": str(pasta.parent)})
            barrado("a caixa lê um número LIMITADO de arquivos e diz que cortou",
                    len(cx["invalidas"]) <= R.MAX_ARQUIVOS and cx.get("cortado") is True)

    print("\n── V7. Temporário previsível do envio (.parcial) plantado na pasta combinada ──")
    with tempfile.TemporaryDirectory() as tmp:
        alvo = Path(tmp) / "SEQ__abcdef12.carta.json"
        # O atacante sabe o nome (sequência + id no nome) e planta o temporário antes.
        (Path(tmp) / (alvo.name + ".parcial")).mkdir()
        try:
            build_carta_aberta(leitura_sintetica(), [], str(alvo), "SEQ")
            barrado("o envio não depende de um temporário de nome previsível", alvo.is_file())
        except OSError:
            barrado("o envio não depende de um temporário de nome previsível", False)

    print("\n── V8. Tipos errados dentro da Carta viram 500 com rastro interno ──")
    with tempfile.TemporaryDirectory() as tmp:
        doc = carta_base()
        for sg in doc["segmentos"]:
            sg["track"] = {"x": 1}
        dados, pasta = receptor(Path(tmp), {"T__55555555.carta.json": doc})
        with mock.patch.object(R.plataforma, "pasta_dados", lambda: dados), sem_indice:
            s = R.SessaoReceber()
            s.caixa({"cor": str(pasta.parent)})
            try:
                s.preparar(ID)
                barrado("dados de tipo errado são recusados com erro legível", False)
            except (CartaInvalida, ValueError):
                barrado("dados de tipo errado são recusados com erro legível", True)
            except Exception as e:  # noqa: BLE001
                barrado(f"dados de tipo errado são recusados (escapou {type(e).__name__})", False)

    # V9/V10 eram do script Lua do Resolve, que SAIU (autor, 2026-09-25: o De Lá Pra Cá exige o
    # Resolve Studio, e o painel da Workflow Integration é o único caminho). A defesa V9 (só
    # importar `<dados>/recebidos/<uuid>.drt`) mora na casca (`drtConfiavel`) e é testada em
    # `tests/test_casca_resolve.py`. O V10 (texto rico no rótulo do Qt) deixou de existir com o
    # script: o painel escapa todo texto do serviço (`escapar`).

    print(f"\n{casos - len(falhas)}/{casos} ataques barrados")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
