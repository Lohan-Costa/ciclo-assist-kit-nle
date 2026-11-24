"""O aviso de versão nova (organograma aprovado pelo autor em 2026-10-05).

Rodar:

    .venv/bin/python tests/test_versao_nova.py        (Windows: .venv-win/Scripts/python)

Sem rede: o GitHub é simulado. A pasta de dados vai para uma pasta temporária. Confere:
- a comparação de versões (0.1.10 > 0.1.9; tag com e sem "v"; lixo não é versão);
- o link só vale se for a página de uma versão do repositório público (o defeito do Órbita: o `html_url`
  ia direto ao navegador);
- os estados: em dia, nova, erro (rede, JSON, resposta estranha, pré-lançamento) e desligado;
- só consulta quando vence (6 h; o erro em 10 min) ou quando a versão instalada muda; "Conferir agora" força;
- o `versao.json` que a janela do app lê; as rotas e o "Baixar" que nunca abre link de fora.
"""

from __future__ import annotations

import io
import json
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))
sys.path.insert(0, str(RAIZ / "motor"))

import configuracoes  # noqa: E402
import plataforma  # noqa: E402
import versao_nova as V  # noqa: E402

casos, falhas = 0, []


def ok(nome, obtido, esperado):
    global casos
    casos += 1
    if obtido == esperado:
        print(f"  ✓ {nome}")
    else:
        falhas.append(nome)
        print(f"  ✗ {nome}\n      obtido:   {obtido!r}\n      esperado: {esperado!r}")


class GitHub:
    """`urlopen` falso: devolve `resposta` (dict → JSON, bytes, ou exceção) e conta as chamadas."""

    def __init__(self, resposta):
        self.resposta, self.chamadas = resposta, 0

    def __call__(self, pedido, timeout=None):
        self.chamadas += 1
        self.pedido = pedido
        if isinstance(self.resposta, Exception):
            raise self.resposta
        dado = self.resposta if isinstance(self.resposta, bytes) else json.dumps(self.resposta).encode()
        return io.BytesIO(dado)


def release(tag, url=None, **extra):
    return {"tag_name": tag, "html_url": url or f"https://github.com/Lohan-Costa/delapraca/releases/tag/{tag}",
            "draft": False, "prerelease": False, **extra}


def main() -> int:
    print("a comparação de versões")
    ok("0.1.82 é mais nova que 0.1.81", V.mais_nova("v0.1.82", "0.1.81"), True)
    ok("⭐ 0.1.10 é mais nova que 0.1.9 (número, não texto)", V.mais_nova("0.1.10", "0.1.9"), True)
    ok("a mesma versão não é nova", V.mais_nova("v0.1.81", "0.1.81"), False)
    ok("uma mais velha não é nova", V.mais_nova("v0.1.80", "0.1.81"), False)
    ok("⛔ lixo não é versão", (V.numeros("v0.1"), V.numeros("0.1.81-beta"), V.numeros(None)), (None, None, None))

    print("o link: só a página de uma versão do repositório público")
    ok("a página da tag", V.url_confiavel("https://github.com/Lohan-Costa/delapraca/releases/tag/v0.1.82"), True)
    for nome, url in (("outro repositório", "https://github.com/outro/delapraca/releases/tag/v0.1.82"),
                      ("outro site com o mesmo começo", "https://github.com.mal.com/Lohan-Costa/delapraca/releases/tag/v1.0.0"),
                      ("um arquivo de download direto", "https://github.com/Lohan-Costa/delapraca/releases/download/v0.1.82/x.exe"),
                      ("http sem TLS", "http://github.com/Lohan-Costa/delapraca/releases/tag/v0.1.82"),
                      ("coisa pendurada no fim", "https://github.com/Lohan-Costa/delapraca/releases/tag/v0.1.82?x=1"),
                      ("javascript:", "javascript:alert(1)")):
        ok(f"⛔ {nome}", V.url_confiavel(url), False)

    with tempfile.TemporaryDirectory() as tmp:
        dados = Path(tmp) / "dados"
        dados.mkdir()
        with mock.patch.object(plataforma, "pasta_dados", lambda: dados), \
                mock.patch.object(plataforma, "versao", lambda: "0.1.81"):
            arquivo = dados / V.ARQUIVO

            def novo():
                V._ultimo = None

            print("os estados")
            novo()
            g = GitHub(release("v0.1.82"))
            e = V.estado(abrir=g)
            ok("⭐ versão nova: estado, número e link", (e["estado"], e["versao"], e["url"], e["atual"]),
               ("nova", "0.1.82", "https://github.com/Lohan-Costa/delapraca/releases/tag/v0.1.82", "0.1.81"))
            ok("o versao.json que a janela do app lê", json.loads(arquivo.read_text(encoding="utf-8")),
               {"estado": "nova", "versao": "0.1.82",
                "url": "https://github.com/Lohan-Costa/delapraca/releases/tag/v0.1.82"})
            ok("a pergunta vai à API do repositório público, com User-Agent",
               (g.pedido.full_url, "delapraca/0.1.81" in g.pedido.get_header("User-agent")),
               ("https://api.github.com/repos/Lohan-Costa/delapraca/releases/latest", True))
            novo()
            ok("em dia", V.estado(abrir=GitHub(release("v0.1.81")))["estado"], "em_dia")
            for nome, resposta in (("sem internet", OSError("rede")), ("JSON quebrado", b"<html>"),
                                   ("link de fora", release("v0.1.82", "https://mal.com/x")),
                                   ("pré-lançamento", release("v0.1.82", prerelease=True)),
                                   ("tag que não é versão", release("vendor-ffmpeg-8.1.2"))):
                novo()
                e = V.estado(abrir=GitHub(resposta))
                ok(f"⛔ {nome}: 'não consegui conferir', sem link", (e["estado"], "url" in e), ("erro", False))

            print("só consulta quando vence")
            novo()
            g = GitHub(release("v0.1.81"))
            V.estado(abrir=g)
            V.estado(abrir=g)
            ok("em dia: a 2ª leitura não vai ao GitHub", g.chamadas, 1)
            V._ultimo["conferido"] -= V.INTERVALO_S
            V.estado(abrir=g)
            ok("depois de 6 h vai de novo", g.chamadas, 2)
            V.estado(forcar=True, abrir=g)
            ok("'Conferir agora' força", g.chamadas, 3)
            novo()
            g = GitHub(OSError("rede"))
            V.estado(abrir=g)
            V._ultimo["conferido"] -= V.REPETIR_ERRO_S
            V.estado(abrir=g)
            ok("o erro tenta de novo em 10 min, não em 6 h", g.chamadas, 2)
            g = GitHub(release("v0.1.82"))
            V.estado(abrir=g)          # ainda dentro dos 10 min do erro
            with mock.patch.object(plataforma, "versao", lambda: "0.1.82"):
                e = V.estado(abrir=GitHub(release("v0.1.82")))
            ok("⭐ a versão instalada mudou (atualizou): confere de novo na hora", (e["estado"], e["atual"]),
               ("em_dia", "0.1.82"))

            print("a caixa que desliga")
            configuracoes.gravar({"avisar_versao_nova": False})
            g = GitHub(release("v0.1.82"))
            e = V.estado(forcar=True, abrir=g)
            ok("desligado: não pergunta nada ao GitHub", (e["estado"], g.chamadas), ("desligado", 0))
            ok("…e a janela do app não mostra a faixa", json.loads(arquivo.read_text(encoding="utf-8"))["estado"],
               "desligado")
            configuracoes.gravar({"avisar_versao_nova": True})
            ok("o padrão é ligado (e lixo no arquivo também liga)",
               (configuracoes._sanear({})["avisar_versao_nova"],
                configuracoes._sanear({"avisar_versao_nova": "não"})["avisar_versao_nova"]), (True, True))

            print("as rotas")
            from api import rotas

            ctx = lambda corpo=None: SimpleNamespace(json=lambda: corpo or {}, servico=None, query="")  # noqa: E731
            abertos = []
            with mock.patch.object(V.urllib.request, "urlopen", GitHub(release("v0.1.82"))), \
                    mock.patch.object(plataforma, "abrir_url", abertos.append):
                novo()
                st, r = rotas.versao_estado(ctx())
                ok("GET /versao", (st, r["estado"], r["versao"]), (200, "nova", "0.1.82"))
                st, r = rotas.versao_baixar(ctx())
                ok("⭐ 'Baixar' abre a página da versão que o motor leu", (st, abertos),
                   (200, ["https://github.com/Lohan-Costa/delapraca/releases/tag/v0.1.82"]))
                st, r = rotas.versao_avisar(ctx({"ligado": "sim"}))
                ok("⛔ /versao/avisar só aceita verdadeiro ou falso", st, 400)
                st, r = rotas.versao_avisar(ctx({"ligado": False}))
                ok("/versao/avisar desliga", (st, r["estado"], configuracoes.ler()["avisar_versao_nova"]),
                   (200, "desligado", False))
                st, r = rotas.versao_baixar(ctx())
                ok("⛔ sem versão nova (desligado), 'Baixar' não abre nada", (st, len(abertos)), (409, 1))
                configuracoes.gravar({"avisar_versao_nova": True})
            with mock.patch.object(V.urllib.request, "urlopen", GitHub(release("v0.1.81"))), \
                    mock.patch.object(plataforma, "abrir_url", abertos.append):
                st, r = rotas.versao_conferir(ctx())
                ok("POST /versao/conferir força e devolve em dia", (st, r["estado"]), (200, "em_dia"))
                st, r = rotas.versao_baixar(ctx())
                ok("⛔ em dia, 'Baixar' não abre nada", (st, len(abertos)), (409, 1))

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
