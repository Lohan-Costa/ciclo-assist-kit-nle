"""
Orbita — a fronteira entre "uma string que alguém mandou" e "um arquivo no disco".

⚠️ O PROBLEMA, EM UMA FRASE
───────────────────────────
O código trata caminho de mídia como se fosse sempre um arquivo local. As
bibliotecas que recebem esse caminho não concordam:

* **MediaInfo** — `MediaInfo_Open` roda ANTES de qualquer checagem de existência, e
  o `pymediainfo` pula explicitamente o `os.path.exists` quando a string contém
  `://`. A libmediainfo embarcada traz o `Reader_libcurl` compilado: ela BUSCA a URL.
* **ffmpeg/ffprobe** — falam `http`, `https`, `ftp`, `rtmp`, `concat:`, `subfile:`,
  `data:`. Um "caminho" pode ser qualquer uma dessas coisas.

Consequência prática, antes desta fronteira existir: um cliente do servidor local
mandava `{"clips":[{"path":"http://10.0.0.5:8080/x.mov"}]}` e o app buscava a URL —
varredura da rede interna a partir da máquina do editor (SSRF). Com um caminho local,
a resposta dizia se o arquivo existia e o que havia dentro dele: um oráculo do disco.

E há um segundo problema, mais silencioso: o ffprobe recebe o caminho como operando
POSICIONAL, e um arquivo cujo nome comece com `-` é lido por ele como OPÇÃO (`-report`
grava um log no diretório atual; `-loglevel` muda o comportamento). O ffmpeg **não**
honra `--` como fim-de-opções, então o truque de sempre não serve aqui.

A CORREÇÃO — uma só, que resolve os dois
────────────────────────────────────────
`ff_input()` devolve `"file:" + caminho absoluto`:

* o prefixo `file:` FIXA o protocolo — `http://…` deixa de ser alcançável mesmo que
  a string chegue aqui por outro caminho;
* e a string resultante nunca começa com `-`, então nunca vira flag.

`ensure_local_file()` é a checagem que vem antes: é um arquivo mesmo, existe, e não
é uma URL disfarçada.
"""

from __future__ import annotations

import os
from pathlib import Path

#: Erro de entrada, não erro interno. Quem chama transforma em mensagem para o
#: cliente — sem vazar o caminho recebido (ver `mensagem_publica`).
class CaminhoInvalido(ValueError):
    pass


def forma_windows(caminho) -> bool:
    r"""O caminho tem a FORMA do Windows (`X:\…`, `X:/…` ou UNC `\\host\…`), em qualquer máquina?

    Matriz de plataforma, regra 3: decide-se pela forma, não pelo SO que roda. No macOS, `os.path` trata
    `F:\CARTAO\x.braw` como UM nome relativo (`abspath` → `<cwd>/F:\…`), sem exceção (medido 2026-10-01).
    Uma regra só: era a mesma expressão copiada em três módulos (revisão de código 2026-10-01).
    """
    import re
    return bool(re.match(r"^(?:[A-Za-z]:[\\/]|\\\\)", str(caminho or "")))


def _parece_url(s: str) -> bool:
    """
    `esquema://` no começo, ou um dos protocolos do ffmpeg que usam `:` sem `//`.

    Cuidado com o falso positivo do Windows: `C:\\Users\\x.mov` tem dois-pontos e é
    um caminho legítimo. Por isso a regra é `://` (que `C:\\` não tem) mais uma lista
    curta e explícita dos protocolos de uma letra só que importam.
    """
    baixa = s.strip().lower()
    if "://" in baixa:
        return True
    for proto in ("concat:", "subfile:", "data:", "pipe:", "cache:", "crypto:", "async:"):
        if baixa.startswith(proto):
            return True
    return False


def ensure_local_file(caminho) -> Path:
    """
    Devolve um `Path` absoluto e existente, ou levanta `CaminhoInvalido`.

    É o portão: tudo que vem do cliente (interface, painel de NLE, servidor local)
    passa por aqui antes de virar argumento de ffmpeg/MediaInfo.
    """
    if not isinstance(caminho, (str, os.PathLike)):
        raise CaminhoInvalido("caminho não é texto")
    s = os.fspath(caminho)
    if not s or not s.strip():
        raise CaminhoInvalido("caminho vazio")
    if _parece_url(s):
        raise CaminhoInvalido("o Órbita só abre arquivos locais")
    if "\x00" in s:
        raise CaminhoInvalido("caminho com byte nulo")

    p = Path(s).expanduser()
    try:
        p = p.resolve(strict=False)
    except OSError as e:                      # caminho absurdo (loop de symlink etc.)
        raise CaminhoInvalido("caminho ilegível") from e
    if not p.is_file():
        raise CaminhoInvalido("arquivo não encontrado")
    return p


def ff_input(caminho) -> str:
    """
    O caminho como o ffmpeg/ffprobe/MediaInfo devem recebê-lo: `file:<absoluto>`.

    Aceita o que já foi validado (um `Path`) ou valida na hora. O prefixo é o que
    fixa o protocolo E impede que um nome começando com `-` vire flag.
    """
    p = caminho if isinstance(caminho, Path) else ensure_local_file(caminho)
    return "file:" + str(p)


def ensure_output_path(caminho, extensoes: tuple[str, ...]) -> Path:
    """
    Valida um caminho de SAÍDA (o `.prproj`/`.drt` que o export vai gravar).

    ⚠️ POR QUE PRECISA EXISTIR: a validação de entrada acima cobria só LEITURA. Os
    comandos de export recebiam `output_path` e escreviam onde mandassem — sem
    diretório-base, sem extensão, sem nada. E um deles ainda faz
    `parent.mkdir(parents=True)`, ou seja, **fabricava a árvore de diretórios** antes
    de escrever. A barreira era o Rust do outro lado (o diálogo de salvar do sistema,
    ou o `temp_prproj_path` higienizado do servidor). Depender só da barreira do
    vizinho é o mesmo erro de desenho que deixou o servidor local sem token.

    As regras são de bom senso e não atrapalham ninguém: absoluto, com a extensão
    esperada, e numa pasta que **já existe** — quem escolhe onde salvar é o usuário,
    pelo diálogo do sistema.
    """
    if not isinstance(caminho, (str, os.PathLike)):
        raise CaminhoInvalido("caminho de saída inválido")
    s = os.fspath(caminho)
    if not s.strip() or "\x00" in s or _parece_url(s):
        raise CaminhoInvalido("caminho de saída inválido")

    p = Path(s).expanduser()
    if not p.is_absolute():
        raise CaminhoInvalido("o caminho de saída precisa ser absoluto")
    if p.suffix.lower() not in extensoes:
        esperado = " ou ".join(extensoes)
        raise CaminhoInvalido(f"o arquivo de saída precisa terminar em {esperado}")
    if not p.parent.is_dir():
        raise CaminhoInvalido("a pasta de destino não existe")
    return p


def mensagem_publica(e: Exception) -> str:
    """
    A mensagem que pode ir para o cliente.

    ⚠️ Nunca inclui o caminho recebido. Devolver "arquivo não encontrado: /Users/joao/
    contratos/x.pdf" faz três favores a quem está sondando: confirma a existência (ou
    não) de um caminho arbitrário, entrega o nome de usuário do sistema, e mapeia a
    árvore de diretórios. O detalhe completo vai para o log em disco, que é do dono
    da máquina.
    """
    if isinstance(e, CaminhoInvalido):
        return str(e)
    return "não consegui ler este arquivo"
