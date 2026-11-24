"""Escolher arquivo(s) ou pasta(s) pelo diálogo do SISTEMA — nunca digitando caminho.

Pedido do autor (2026-11-01), sobre o formulário das receitas: *"os campos que indiquem caminho não
podem ser só escrita por extenso… devemos ter um botão para o usuário navegar até o item ou os itens
desejados. Podemos aceitar drag and drop também, mas escrever caminho na mão é a pior experiência de
usuário possível."*

| | Windows | macOS |
|---|---|---|
| diálogo | `IFileOpenDialog` (`seletor_win.py`, processo filho) | `osascript` `choose file` / `choose folder` |
| vários | `FOS_ALLOWMULTISELECT` (arquivos E pastas) | `with multiple selections allowed` |
| filtro | `SetFileTypes` + "Todos os arquivos" | `of type {…}`; recusado → sem filtro (De Lá Pra Cá) |
| cancelar | nada impresso | erro −128 (pelo NÚMERO, a frase vem traduzida) |

⛔ O título e as extensões chegam ao AppleScript por `argv`, nunca colados no texto: um `"` viraria
código executado. macOS medido em 2026-11-05 (15.6, exFAT): cancelar = [], pasta e arquivo com filtro
voltam POSIX; o diálogo é do System Events para ter o foco do teclado. ⚠️ Empacotado (PyInstaller) o
`sys.executable` não é um Python: o ramo do Windows precisa de uma opção do executável — `pendente`.
"""

from __future__ import annotations

import logging
import subprocess
import sys
from pathlib import Path

log = logging.getLogger("cicloassist.servico.seletor")

PRAZO_S = 900     # o editor navegando pela rede; o teto só solta a thread se a janela morrer


class SeletorFalhou(RuntimeError):
    pass


_MAC = """
on run argv
  set titulo to item 1 of argv
  set modo to item 2 of argv
  set varios to (item 3 of argv) is "1"
  set tipos to {}
  if (count of argv) > 3 then set tipos to items 4 thru -1 of argv
  -- O diálogo é do System Events, que vai à frente: aberto pelo osascript (processo de fundo),
  -- ele aparecia sem o foco do teclado (medido 2026-11-05).
  tell application "System Events"
    activate
    if modo is "pasta" then
      set r to choose folder with prompt titulo multiple selections allowed varios
    else if tipos is {} then
      set r to choose file with prompt titulo multiple selections allowed varios
    else
      set r to choose file with prompt titulo of type tipos multiple selections allowed varios
    end if
  end tell
  if class of r is not list then set r to {r}
  set saida to ""
  repeat with x in r
    set saida to saida & POSIX path of x & linefeed
  end repeat
  return saida
end run
"""


def _rodar(comando: list[str]) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(comando, capture_output=True, encoding="utf-8", errors="replace",
                              timeout=PRAZO_S, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired:
        raise SeletorFalhou("o seletor ficou aberto tempo demais") from None
    except OSError as e:
        raise SeletorFalhou(f"não consegui abrir o seletor ({e})") from None


def escolher(tipo: str = "arquivo", varios: bool = False, extensoes: list[str] | None = None,
             titulo: str = "Escolha") -> list[str]:
    """Os caminhos escolhidos. Lista vazia = o editor cancelou."""
    if tipo not in ("arquivo", "pasta"):
        raise ValueError(tipo)
    extensoes = [e.lstrip(".").lower() for e in (extensoes or []) if e and e.isascii() and e.strip(".").isalnum()]
    titulo = (titulo or "Escolha")[:120]
    if sys.platform == "win32":
        # Pelo CAMINHO do arquivo, não `-m`: ele não importa nada do pacote, e assim não depende
        # do diretório de trabalho de quem subiu o serviço.
        comando = [sys.executable, str(Path(__file__).with_name("seletor_win.py")), "--titulo", titulo]
        if tipo == "arquivo":
            comando.append("--arquivos")
        if varios:
            comando.append("--varios")
        for e in extensoes:
            comando += ["--ext", e]
        r = _rodar(comando)
        if r.returncode != 0:
            linhas = (r.stderr or "").strip().splitlines()
            raise SeletorFalhou(linhas[-1] if linhas else "o seletor falhou")
    elif sys.platform == "darwin":
        base = ["osascript", "-e", _MAC, titulo, tipo, "1" if varios else "0"]
        r = _rodar(base + extensoes)
        if r.returncode != 0 and "-128" not in (r.stderr or "") and extensoes:
            log.info("filtro recusado pelo choose file (%s); abrindo sem filtro", (r.stderr or "").strip())
            r = _rodar(base)
        if r.returncode != 0:
            if "-128" in (r.stderr or ""):
                return []
            raise SeletorFalhou((r.stderr or "o seletor falhou").strip().splitlines()[-1])
    else:
        raise SeletorFalhou("não há seletor nativo neste sistema")
    caminhos = [str(Path(linha.strip())) for linha in (r.stdout or "").splitlines() if linha.strip()]
    return caminhos if varios else caminhos[:1]
