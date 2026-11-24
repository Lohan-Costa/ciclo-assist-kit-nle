r"""O caminho que sai de um arrasto do Explorer, travado por regressão.

(Docstring crua, com o prefixo `r` — ela cita caminhos UNC do Windows, e sem isso o
`\SERVIDOR` abaixo vira erro de escape na leitura do arquivo.)

⭐ `uriParaCaminho` (em `ui/painel.js`) é onde o gesto vira caminho de disco, e cada
forma que ele precisa aceitar já custou caro em algum app deste conjunto:

* **percent-encoding** — `MIDIAS%20VALENDO`. Uma pasta de produção tem espaço no nome
  quase sempre; sem decodificar, o caminho simplesmente "não existe" e o app diz "pasta
  vazia". Falha silenciosa clássica deste domínio.
* **a barra da frente** — `file:///E:/a` traz `/E:/a`, e `/E:\a` não é caminho válido.
* **UNC** — diária em share de rede é a regra, não a exceção: `file://SERVIDOR/share/x`
  tem de virar `\\SERVIDOR\share\x`, e não `/share/x` (que apontaria para o disco local).
* **POSIX** — o mesmo painel roda no macOS, onde nada disso se aplica.

## Por que este teste chama o `node`

A função é JavaScript e vive na UI. Reimplementá-la em Python para testar seria testar a
CÓPIA — e a cópia é justamente o que diverge em silêncio da original (a mesma razão pela
qual `pack.sh` virou `pack.py` e `motor/requirements.txt` virou um `-r`). Então o teste
extrai a função do arquivo real e a executa.

Sem `node` na máquina o teste se declara PULADO e sai com 0: um vermelho por ferramenta
ausente só ensina a ignorar vermelho.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PAINEL_JS = RAIZ / "plugins" / "media-composer" / "servico" / "ui" / "painel.js"

# (uri, caminho esperado) — `None` = a função deve recusar, devolvendo string vazia.
CASOS = [
    # ⭐ O arrasto real que abriu esta rota (medido 2026-08-16, MC 25.6/Windows 11).
    ("file:///E:/MIDIAS%20DE%20TESTES/_PROJETOS%20EM%20ANDAMENTO/47_PRODUCAO-A/MIDIAS/MIDIAS%20VALENDO",
     r"E:\MIDIAS DE TESTES\_PROJETOS EM ANDAMENTO\47_PRODUCAO-A\MIDIAS\MIDIAS VALENDO"),
    # O mesmo caminho como o `text/plain` do arrasto entrega: sem encoding.
    ("file:///E:/MIDIAS DE TESTES/MIDIAS VALENDO",
     r"E:\MIDIAS DE TESTES\MIDIAS VALENDO"),
    ("file:///D:/diaria", r"D:\diaria"),
    ("file:///C:/", "C:\\"),
    # Acento: o outro lado da mesma moeda do encoding.
    ("file:///D:/GRAVA%C3%87%C3%95ES/dia%201", r"D:\GRAVAÇÕES\dia 1"),
    # ⭐ UNC — diária em share de rede.
    ("file://SERVIDOR/producao/47_PRODA/dia%2003",
     r"\\SERVIDOR\producao\47_PRODA\dia 03"),
    # POSIX (o painel também roda no macOS).
    ("file:///Volumes/SSD/diaria", "/Volumes/SSD/diaria"),
    ("file://localhost/Volumes/X/y", "/Volumes/X/y"),
    # Recusas: não é `file:`, ou não é URI nenhuma.
    ("http://exemplo.com/pasta", None),
    ("D:\\ja e um caminho", None),
    ("", None),
    ("file://", None),
]

# (tipos do arrasto, espécie esperada). ⭐ É esta função que decide para qual ZONA o
# arrasto vale, e ela roda no `dragover`, quando só `types` está disponível.
_MC = "text/x.avid.mc-api-asset-list+json"
ESPECIES = [
    # ⚠️⚠️ O ARRASTO DO MC TAMBÉM TRAZ `text/uri-list` E `Files` (o .aaf de zero bytes).
    # Se a ordem dos testes inverter, uma timeline da bin passa a ser lida como arquivo
    # de disco — e o editor arrasta a timeline e o painel oferece adicionar uma pasta.
    (["text/plain", "text/uri-list", "text/x.avid.asset-list-extended+json", _MC, "Files"],
     "timeline"),
    ([_MC], "timeline"),
    (["text/x.avid.panel-sdk-plugin-asset-list+json"], "timeline"),
    # Explorer: pasta ou arquivo, os dois chegam assim.
    (["text/plain", "text/uri-list", "Files"], "caminho"),
    (["Files"], "caminho"),
    # Nem uma coisa nem outra: texto selecionado, ou arrasto sem dado (o de uma BIN).
    (["text/plain"], ""),
    ([], ""),
]

# (caminho, é arquivo de timeline?) — decide o que o bloco 2 recusa e o bloco 1 aceita.
EXTENSOES = [
    (r"D:\montagem\CORTE.aaf", True),
    (r"D:\montagem\CORTE.AAF", True),      # o Windows não distingue caixa
    (r"D:\montagem\corte.drt", True),      # reconhecido para RECUSAR com precisão
    (r"D:\montagem\corte.fcpxml", True),
    (r"D:\MIDIAS VALENDO", False),         # a pasta do arrasto real
    (r"D:\MIDIAS\A001_C004.braw", False),
    (r"D:\MIDIAS\som.wav", False),
    # ⚠️ Pasta cujo NOME termina em algo parecido: só a extensão do fim conta, e
    # `AAF ENTREGUES` não é `.aaf`.
    (r"D:\PROJETO\AAF ENTREGUES", False),
]

# (text/uri-list, text/plain, quantos caminhos deve extrair).
#
# ⚠️⚠️ O CASO QUE DEU ORIGEM A ISTO, medido 2026-08-16 arrastando duas pastas juntas:
# **o QtWebEngine trunca o `text/uri-list` na PRIMEIRA URI** e é o `text/plain` que traz
# a seleção inteira. O tipo canônico é o incompleto. Preferir o `uri-list` — que é o que
# a especificação manda — fazia o editor selecionar cinco diárias, arrastar, e o painel
# adicionar UMA, sem erro nenhum.
_SFX = "file:///E:/MIDIAS%20DE%20TESTES/MIDIAS%20VALENDO/SFX"
_SFX_PLANO = "file:///E:/MIDIAS DE TESTES/MIDIAS VALENDO/SFX"
_TRILHAS_PLANO = "file:///E:/MIDIAS DE TESTES/MIDIAS VALENDO/TRILHAS"
LISTAS = [
    # ⭐ O arrasto real: uri-list truncado, text/plain completo.
    (_SFX, f"{_SFX_PLANO}\n{_TRILHAS_PLANO}\n", 2),
    # ⚠️ E o mesmo caminho nas duas formas (com e sem encoding) é UM só, não dois —
    # senão a mesma pasta entraria duplicada na lista a cada arrasto.
    (_SFX, _SFX_PLANO, 1),
    ("file:///D:/a\r\nfile:///D:/b", "", 2),
    ("# comentario\r\nfile:///D:/a", "", 1),     # `#` é comentário, não caminho
    ("file:///D:/a\n\nfile:///D:/b\n", "", 2),   # linhas vazias não contam
    ("", "file:///D:/so-no-plano", 1),           # só o text/plain veio
    ("", "", 0),
]


# O arquivo SOLTO no painel do Resolve (2026-10-05, Resolve 19 no Windows: "esse arrasto não trouxe
# caminho"): o Electron entrega só `Files`. (rótulo, o arrasto, os caminhos esperados).
SOLTOS = [
    ("Electron 8 (Resolve 19): File.path",
     {"arquivo": {"name": "a.aaf", "path": r"D:\X\a.aaf"}}, [r"D:\X\a.aaf"]),
    ("Electron 32+ (Resolve 21): a casca, webUtils",
     {"arquivo": {"name": "b.aaf"}, "casca": r"D:\Y\b.aaf"}, [r"D:\Y\b.aaf"]),
    ("sem caminho nenhum: nada (o painel avisa)",
     {"arquivo": {"name": "c.aaf"}}, []),
    ("com uri-list, ela vale e o File não entra",
     {"arquivo": {"name": "d.aaf", "path": r"D:\OUTRO\d.aaf"}, "uri": "file:///E:/U/d.aaf"}, [r"E:\U\d.aaf"]),
]


def main() -> int:
    if not shutil.which("node"):
        print("PULADO: `node` não está no PATH (a função testada é JavaScript)")
        return 0

    fonte = PAINEL_JS.read_text(encoding="utf-8")

    # Extrai do arquivo REAL. Se alguém renomear, o teste falha aqui — que é o aviso
    # certo, e não um falso verde.
    trechos = []
    for nome in ("const MIME_MC_ASSETS", "const MIME_PLUGIN_ASSETS",
                 "const EXT_LEIO_HOJE", "const EXT_TIMELINE_FUTURA",
                 "function tiposDoArrasto", "function temNossoMime",
                 "function especieDoArrasto", "function eArquivoDeTimeline",
                 "function uriParaCaminho", "function _lerTipo", "function _urisDe",
                 "function caminhosDoArrasto"):
        i = fonte.find(nome)
        if i < 0:
            print(f"FALHA: não achei `{nome}` em {PAINEL_JS.name}")
            return 1
        if nome.startswith("const "):
            fim = re.search(r"\n", fonte[i:])           # uma linha (pode ter comentário depois do `;`)
        else:
            fim = re.search(r"\n\}\n", fonte[i:])       # até fechar na coluna 0
        if not fim:
            print(f"FALHA: não consegui delimitar `{nome}`")
            return 1
        trechos.append(fonte[i:i + fim.end()])

    # A entrada vai por STDIN, não por argumento: um caminho de teste com espaço e
    # acento atravessando a linha de comando do Windows é atrito sem ganho nenhum.
    programa = "\n".join(trechos) + """
let casca = null;   // o preload da casca do Resolve (`window.delapraca`), quando o caso pede
function ponte() { return casca; }
const entrada = JSON.parse(require("fs").readFileSync(0, "utf8"));
const saida = {
  caminhos: entrada.uris.map(uriParaCaminho),
  listas: entrada.listas.map((par) => caminhosDoArrasto({ getData: (t) =>
    (t === "text/uri-list" ? par[0] : (t === "text/plain" ? par[1] : "")) }).length),
  especies: entrada.especies.map((tipos) => especieDoArrasto({ types: tipos })),
  extensoes: entrada.extensoes.map(eArquivoDeTimeline),
  // O arquivo SOLTO no Resolve (Electron): só `Files`, sem uri-list nem texto (2026-10-05).
  soltos: entrada.soltos.map((c) => {
    casca = c.casca ? { caminhoDoArquivo: () => c.casca } : null;
    return caminhosDoArrasto({ getData: (t) => (t === "text/uri-list" ? c.uri || "" : ""),
                               files: [c.arquivo] });
  }),
};
process.stdout.write(JSON.stringify(saida));
"""
    entrada = json.dumps({"uris": [u for u, _ in CASOS],
                          "listas": [[u, p] for u, p, _ in LISTAS],
                          "especies": [t for t, _ in ESPECIES],
                          "extensoes": [c for c, _ in EXTENSOES],
                          "soltos": [c for _, c, _ in SOLTOS]})
    r = subprocess.run(["node", "-e", programa], input=entrada,
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=60)
    if r.returncode != 0:
        print("FALHA ao rodar o node:")
        print(r.stderr)
        return 1
    obtido = json.loads(r.stdout)

    falhas: list[str] = []
    print("── URI de arrasto → caminho de disco ────────────────────────")
    for (uri, esperado), veio in zip(CASOS, obtido["caminhos"]):
        alvo = esperado if esperado is not None else ""
        ok = veio == alvo
        rotulo = (uri[:44] + "…") if len(uri) > 45 else uri
        print(f"  {'ok  ' if ok else 'FALHA'} {rotulo:<46} -> {veio!r}")
        if not ok:
            falhas.append(f"{uri}: veio {veio!r}, esperava {alvo!r}")

    print("\n── vários caminhos: uri-list TRUNCA, text/plain completa ────")
    for (uri, plano, esperado), veio in zip(LISTAS, obtido["listas"]):
        ok = veio == esperado
        rotulo = f"uri={len(uri.split()) if uri else 0} plain={len(plano.split()) if plano else 0}"
        print(f"  {'ok  ' if ok else 'FALHA'} {rotulo:<16} -> {veio} caminho(s)"
              f"   {(uri or plano or '(vazios)')[:44]}")
        if not ok:
            falhas.append(f"uri={uri!r} plain={plano!r}: veio {veio}, esperava {esperado}")

    print("\n── espécie do arrasto (decide a ZONA, e roda no dragover) ───")
    for (tipos, esperado), veio in zip(ESPECIES, obtido["especies"]):
        ok = veio == esperado
        rotulo = ", ".join(t.replace("text/x.avid.", "avid:") for t in tipos) or "(sem tipos)"
        if len(rotulo) > 44:
            rotulo = rotulo[:43] + "…"
        print(f"  {'ok  ' if ok else 'FALHA'} {rotulo:<46} -> {veio or '(nenhuma)'!s}")
        if not ok:
            falhas.append(f"espécie de {tipos}: veio {veio!r}, esperava {esperado!r}")

    print("\n── é arquivo de timeline? (o que o bloco 2 recusa) ──────────")
    for (caminho, esperado), veio in zip(EXTENSOES, obtido["extensoes"]):
        ok = veio == esperado
        print(f"  {'ok  ' if ok else 'FALHA'} {caminho:<40} -> {veio}")
        if not ok:
            falhas.append(f"{caminho}: veio {veio}, esperava {esperado}")

    print("\n── arquivo solto no Resolve: só `Files` (Electron) ──────────")
    for (rotulo, _, esperado), veio in zip(SOLTOS, obtido["soltos"]):
        ok = veio == esperado
        print(f"  {'ok  ' if ok else 'FALHA'} {rotulo:<46} -> {veio}")
        if not ok:
            falhas.append(f"{rotulo}: veio {veio}, esperava {esperado}")

    total = len(CASOS) + len(LISTAS) + len(ESPECIES) + len(EXTENSOES) + len(SOLTOS)
    print(f"\n{total - len(falhas)}/{total} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
