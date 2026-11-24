r"""Regera o `requirements.lock` a partir do ambiente que roda hoje.

    .venv-win\Scripts\python tools\lock.py

⚠️⚠️ **Existe para o lock NAO ser gerado por redirecionamento do shell**, e as duas razoes
foram pagas com defeito real — a primeira no De La Pra Ca (2026-08-16), a segunda neste
projeto (2026-09-10):

1. **PowerShell 5.1 grava BOM e comeu um caractere.** O `>` produziu um `\r` solto no meio
   de um comentario, que engoliu a letra seguinte: a linha deixou de comecar por `#`, o pip
   tentou le-la como requisito, e o arquivo virou **nao-instalavel**. O defeito so apareceu
   quando alguem tentou usa-lo — o arquivo *parecia* certo.

2. **O pip decodifica requirements com a CODEPAGE DO SISTEMA**, nao UTF-8, quando nao ha
   BOM. Um simbolo de aviso carrega o byte `0x8F`, **indefinido em cp1252** →
   `UnicodeDecodeError` e nenhuma instalacao.

   ⭐ Medido aqui: o `requirements.txt` deste projeto era ilegivel em cp1252 e so instalava
   porque `dev.ps1` e `instalar.ps1` setam `PYTHONUTF8=1`. Quem digitasse
   `pip install -r requirements.txt` a mao nao instalava nada, com um erro que fala de
   codec e nao de dependencia.

⭐ Por isso tudo que este script escreve e **ASCII puro** — inclusive este cabecalho de
docstring, que e prosa para gente e nao vai para o arquivo gerado. Arquivo lido por maquina
nao carrega prosa acentuada.
"""

from __future__ import annotations

import json
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

#: Quanto esperar por cada consulta ao PyPI. Sao ~36 requisicoes; um travamento em uma
#: delas nao pode pendurar a geracao inteira.
TEMPO_PYPI_S = 30

RAIZ = Path(__file__).resolve().parent.parent
LOCK = RAIZ / "requirements.lock"

#: Pacotes que o `pip freeze` lista e que NAO devem entrar no lock: eles vem com o venv,
#: nao sao dependencia declarada, e fixa-los quebra a instalacao numa maquina cujo
#: instalador de Python trouxe outra versao.
IGNORAR = {"pip", "setuptools", "wheel", "pkg-resources", "distribute"}

CABECALHO = """\
# requirements.lock - versoes EXATAS do ambiente que roda hoje.
#
# ASCII PURO de proposito: o pip decodifica este arquivo com a codepage do
# sistema quando nao ha BOM, e um caractere fora do ASCII pode torna-lo
# ILEGIVEL no Windows (UnicodeDecodeError, e nenhuma instalacao). A explicacao
# completa esta em tools/lock.py, que gera este arquivo.
#
# Instalar:  pip install -r requirements.lock
# Regerar :  python tools/lock.py    (NUNCA com `>` do PowerShell - ver o script)
#
# requirements.txt continua sendo a lista LEGIVEL (o que se pediu e por que);
# este e' o que se INSTALA.
#
# ATENCAO ao adotar versao nova: uma publicada ha poucos dias ainda nao passou
# pelo escrutinio da comunidade. Quarentena e' barata; comprometimento de
# cadeia de suprimentos, nao.
"""


CABECALHO_COM_HASH = CABECALHO + """#
# Este lock traz os SHA-256 de cada pacote. O pip entra em modo de verificacao
# de integridade e RECUSA qualquer arquivo cujo hash nao bata -- inclusive
# dependencia nova que apareca sem estar listada aqui.
#
# Por isso um hash PARCIAL nao serve: se faltar um pacote, a instalacao inteira
# falha. O tools/lock.py recusa gerar um lock assim.
#
# Ha varios hashes por pacote (um por wheel publicada). Qualquer um que bata
# serve -- e' o que faz este lock valer em mais de uma versao de Python e em
# mais de um sistema.
"""


def hashes_do_pypi(nome: str, versao: str) -> list[str]:
    """Todos os sha256 publicados para aquela versao, do sdist e de cada wheel.

    ⭐ **Todos, e nao so o da roda que esta instalada aqui.** O pip aceita qualquer um dos
    hashes listados; com um so, o lock instalaria nesta maquina e falharia na proxima com
    outra versao de Python ou outro sistema — e a mensagem falaria de hash, nao de
    plataforma.

    ⚠️ Sao ~36 consultas. Nao ha cache: o lock e' regerado raramente, e cachear criaria
    uma segunda verdade que envelhece.
    """
    url = f"https://pypi.org/pypi/{nome}/{versao}/json"
    try:
        with urllib.request.urlopen(url, timeout=TEMPO_PYPI_S) as r:
            dados = json.load(r)
    except (urllib.error.URLError, OSError, ValueError):
        return []
    achados = []
    for artefato in dados.get("urls", []):
        h = (artefato.get("digests") or {}).get("sha256")
        if h:
            achados.append(h)
    return sorted(set(achados))


def main() -> int:
    # ⛔ O `pip freeze` so lista o que ESTA instalado, e o `colorama` (dependencia do tqdm e
    # do click) so se instala no Windows. Gerado no Mac, o lock sai sem ele, e no Windows o
    # `--require-hashes` recusa a instalacao INTEIRA. E o `.venv-win` existe no SSD
    # compartilhado, entao o teste de baixo nao barrava o Mac (medido em 2026-09-14).
    if sys.platform != "win32" and "--forcar" not in sys.argv:
        print("O lock e' gerado no WINDOWS: o pip freeze daqui perde pacotes que so o")
        print("Windows instala (colorama), e o lock sem eles nao instala la.")
        print("Passe --forcar se souber o que esta fazendo.")
        return 1

    if not (RAIZ / ".venv-win").exists() and "--forcar" not in sys.argv:
        print("Nao achei o .venv-win. Rode isto COM o python do venv:")
        print(r"    .venv-win\Scripts\python tools\lock.py")
        print("Ou passe --forcar se souber o que esta fazendo.")
        return 1

    r = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if r.returncode != 0:
        print(r.stderr)
        return r.returncode

    linhas = []
    for linha in r.stdout.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#"):
            continue
        nome = linha.split("==")[0].split(" @ ")[0].strip().lower()
        if nome in IGNORAR:
            continue
        # ⚠️ Uma linha sem `==` e' instalacao local ou de URL: fixa-la nao reproduz nada
        # noutra maquina, e deixa-la passar produz um lock que MENTE sobre ser exato.
        if "==" not in linha:
            print(f"  ignorado (nao e' versao fixa): {linha}")
            continue
        linhas.append(linha)

    linhas.sort(key=str.lower)

    if "--sem-hash" in sys.argv:
        print("  (--sem-hash: gerando lock sem verificacao de integridade)")
        texto = CABECALHO + "\n" + "\n".join(linhas) + "\n"
    else:
        blocos, sem_hash = [], []
        for i, linha in enumerate(linhas, 1):
            nome, versao = linha.split("==", 1)
            print(f"  [{i:2}/{len(linhas)}] {nome}=={versao}", end="", flush=True)
            hashes = hashes_do_pypi(nome, versao)
            if not hashes:
                sem_hash.append(linha)
                print("  SEM HASH")
                continue
            print(f"  {len(hashes)} hash(es)")
            # Formato do pip: a barra invertida continua a linha, e cada --hash vai
            # indentado. Qualquer UM dos hashes bate; e por isso que todos entram.
            corpo = " \\\n".join(f"    --hash=sha256:{h}" for h in hashes)
            blocos.append(f"{linha} \\\n{corpo}")

        if sem_hash:
            # ⛔ Um lock com hash PARCIAL e pior que um sem hash nenhum: o pip entra em
            # modo de verificacao e RECUSA tudo que nao tem hash, entao a instalacao
            # falha inteira. Melhor recusar aqui, com o nome do pacote na mao.
            print()
            print("ERRO: sem hash no PyPI para:")
            for l in sem_hash:
                print(f"  {l}")
            print("Um lock com hash parcial nao instala. Resolva ou use --sem-hash.")
            return 1

        texto = CABECALHO_COM_HASH + "\n" + "\n".join(blocos) + "\n"

    if not texto.isascii():
        fora = [c for c in texto if not c.isascii()]
        print(f"ERRO: o lock saiu com caractere nao-ASCII: {fora[:5]!r}")
        return 1

    # ⚠️ `newline=""` com "\n" no texto: sem isso o Python traduz para CRLF no Windows, e
    # o .gitattributes deste repo normaliza para LF de qualquer forma. Um arquivo que muda
    # de fim de linha a cada geracao polui todo diff.
    LOCK.write_text(texto, encoding="ascii", newline="\n")
    print(f"{LOCK.name}: {len(linhas)} pacotes fixados")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
