#!/usr/bin/env python3
"""
sanear.py — tira TODO comentário e toda docstring do artefato público (regra do autor, 2026-10-05).

O conhecimento do projeto (o porquê de cada linha) é o diferencial dele: o código vai público e
livre (GPL-3.0), mas só o código que funciona. Este arquivo NÃO é publicado (não está na allowlist
do `publish.py`, que o importa).

Cada tipo de arquivo tem o seu removedor, e cada resultado é CONFERIDO — sanear não pode mudar o
que o programa faz:
- Python: `tokenize` (comentários) + `ast` (docstrings; corpo que fica vazio ganha `pass`). Prova:
  a árvore sintática do resultado é IDÊNTICA à do original sem as docstrings.
- JS (também o `<script>` do HTML), CSS, Rust, proto: um leitor que conhece strings, template
  literals, regex (JS), strings cruas e caracteres (Rust). Prova: `node --check` nos JS e
  idempotência (sanear de novo não acha mais nada).
- HTML/XML/SVG: `<!-- -->` fora de `<script>`/`<style>`; XML conferido pelo ElementTree.
- PowerShell: o PRÓPRIO parser do PowerShell diz onde estão os comentários. Prova: reparse sem erro.
- shell, TOML, requirements: comentário de linha fora de aspas. Prova: `bash -n` / `tomllib`.
- JSON: sai o `_meta` dos templates e a `description` das permissões do app.

Ao fim, `conferir()` varre o artefato: comentário que sobrou, ou arquivo de texto de um tipo que
este módulo não conhece, FALHA a publicação (allowlist de tipos, como a de arquivos).

Uso isolado (para ver o resultado):  python sanear.py <pasta>
"""

from __future__ import annotations

import ast
import io
import json
import re
import shutil
import subprocess
import sys
import tokenize
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path

SENTINELA = "\x00"
BINARIOS = {".png", ".ico", ".bin", ".drt", ".avb", ".aaf", ".mxf", ".wav", ".mov", ".mp4", ".jpg", ".jpeg", ".gif", ".icns", ".webp"}
SEM_COMENTARIO = {".lock"}          # Cargo.lock: gerado, sem conhecimento; o requirements.lock é tratado à parte
NOMES_SEM_COMENTARIO = {"VERSION", "LICENSE", ".gitignore"}


class FalhaAoSanear(Exception):
    pass


# ── a limpeza comum: sentinelas → linhas ───────────────────────────────────────────────────────

def _assentar(texto: str) -> str:
    """Cada trecho removido virou uma SENTINELA. Linha que só tinha comentário sai inteira; o
    espaço antes de um comentário no fim da linha sai junto; e duas linhas em branco que ficaram
    juntas porque um comentário saiu entre elas viram uma. Linha em branco ORIGINAL nunca é tocada
    sozinha (pode estar dentro de uma string de várias linhas)."""
    fora: list[str] = []
    removida = False
    for linha in texto.split("\n"):
        if SENTINELA in linha:
            limpa = linha.replace(SENTINELA, "")
            if not limpa.strip():
                removida = True
                continue
            if linha.rstrip().endswith(SENTINELA):
                limpa = limpa.rstrip()
            linha = limpa
        if not linha.strip() and removida and fora and not fora[-1].strip():
            continue
        if not fora and not linha.strip():
            continue                             # linha em branco no topo (nunca dentro de string)
        fora.append(linha)
        if linha.strip():
            removida = False
    return "\n".join(fora)


# ── Python ─────────────────────────────────────────────────────────────────────────────────────

_CODIFICACAO = re.compile(r"^[ \t\f]*#.*?coding[:=][ \t]*[-\w.]+")


def _docstrings(arvore) -> list:
    fora = []
    for no in ast.walk(arvore):
        if isinstance(no, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and no.body:
            p = no.body[0]
            if isinstance(p, ast.Expr) and isinstance(p.value, ast.Constant) and isinstance(p.value.value, str):
                fora.append((no, p))
    return fora


def _sem_docstrings(arvore):
    for no, p in _docstrings(arvore):
        no.body.remove(p)
        if not no.body:
            no.body.append(ast.Pass())
    return arvore


def sanear_python(texto: str) -> str:
    original = ast.parse(texto)
    linhas = texto.split("\n")

    def coluna(lin: int, col_bytes: int) -> int:
        return len(linhas[lin - 1].encode("utf-8")[:col_bytes].decode("utf-8"))

    trechos = []                                 # ((lin, col), (lin, col), troca)
    for t in tokenize.generate_tokens(io.StringIO(texto).readline):
        if t.type != tokenize.COMMENT:
            continue
        if t.start[0] == 1 and t.string.startswith("#!"):
            continue
        if t.start[0] <= 2 and _CODIFICACAO.match(t.line):
            continue
        trechos.append((t.start, t.end, SENTINELA))
    for no, p in _docstrings(original):
        troca = "pass" if len(no.body) == 1 else SENTINELA
        trechos.append(((p.lineno, coluna(p.lineno, p.col_offset)),
                        (p.end_lineno, coluna(p.end_lineno, p.end_col_offset)), troca))

    inicio = [0]
    for linha in linhas:
        inicio.append(inicio[-1] + len(linha) + 1)
    pos = lambda lc: inicio[lc[0] - 1] + lc[1]   # noqa: E731
    novo = texto
    for a, b, troca in sorted(trechos, key=lambda x: pos(x[0]), reverse=True):
        novo = novo[:pos(a)] + troca + novo[pos(b):]
    novo = _assentar(novo)

    try:
        resultado = ast.parse(novo)
    except SyntaxError as e:
        raise FalhaAoSanear(f"o Python saneado não compila: {e}") from None
    if ast.dump(_sem_docstrings(ast.parse(texto))) != ast.dump(resultado):
        raise FalhaAoSanear("o Python saneado mudou o programa (a árvore sintática difere)")
    return novo


# ── JS, CSS, Rust, proto: o leitor de código com strings ───────────────────────────────────────

_PALAVRAS_ANTES_DE_REGEX = {"return", "typeof", "instanceof", "in", "of", "new", "delete", "void",
                            "throw", "case", "do", "else", "yield", "await"}


def _sanear_c(texto: str, linguagem: str) -> str:
    """`linguagem`: "js", "css", "rs" ou "proto"."""
    js, rs, css = linguagem == "js", linguagem == "rs", linguagem == "css"
    fora: list[str] = []
    i, n = 0, len(texto)
    pilha: list[str] = []                        # "tpl" = dentro de `...`; "{" = chaves de ${ }
    ultimo = ""                                  # o último pedaço significativo (para a regex)

    def regex_permitida() -> bool:
        if not ultimo:
            return True
        if ultimo[-1] in "(,=:[!&|?{};+-*%<>~^":
            return True
        return ultimo in _PALAVRAS_ANTES_DE_REGEX

    def ler_string(i: int, aspa: str) -> int:
        j = i + 1
        while j < n:
            c = texto[j]
            if c == "\\":
                j += 2
                continue
            if c == aspa:
                return j + 1
            if c == "\n" and not (rs or aspa == "`"):
                return j + 1                     # string sem fechar: o compilador acusa, não nós
            j += 1
        return n

    while i < n:
        c = texto[i]
        dois = texto[i:i + 2]
        if pilha and pilha[-1] == "tpl":
            if c == "\\":
                fora.append(texto[i:i + 2])
                i += 2
                continue
            if c == "`":
                pilha.pop()
                fora.append(c)
                i += 1
                ultimo = "`"
                continue
            if dois == "${":
                pilha.append("{")
                fora.append(dois)
                i += 2
                ultimo = "{"
                continue
            fora.append(c)
            i += 1
            continue
        if dois == "//" and not css:
            j = texto.find("\n", i)
            j = n if j < 0 else j
            fora.append(SENTINELA)
            i = j
            continue
        if dois == "/*":
            profundidade, j = 1, i + 2
            while j < n and profundidade:
                if rs and texto.startswith("/*", j):
                    profundidade += 1
                    j += 2
                elif texto.startswith("*/", j):
                    profundidade -= 1
                    j += 2
                else:
                    j += 1
            if profundidade:
                raise FalhaAoSanear("comentário de bloco sem fim")
            fora.append(SENTINELA)
            i = j
            continue
        if rs and re.match(r"b?r#*\"", texto[i:i + 40]) and not re.match(r"[A-Za-z0-9_]", texto[i - 1:i] or " "):
            m = re.match(r"b?r(#*)\"", texto[i:])
            fecho = "\"" + m.group(1)
            j = texto.find(fecho, i + m.end())
            j = n if j < 0 else j + len(fecho)
            fora.append(texto[i:j])
            i, ultimo = j, "s"
            continue
        if rs and c == "'":
            m = re.match(r"'(\\u\{[0-9A-Fa-f]+\}|\\.|[^\\'\n])'", texto[i:])
            if m:
                fora.append(m.group(0))
                i += m.end()
                ultimo = "s"
                continue
            fora.append(c)                       # lifetime ('a)
            i += 1
            continue
        if c in "\"'" or (js and c == "`"):
            if c == "`":
                pilha.append("tpl")
                fora.append(c)
                i += 1
                continue
            j = ler_string(i, c)
            fora.append(texto[i:j])
            i, ultimo = j, "s"
            continue
        if js and c == "/" and regex_permitida():
            j, classe = i + 1, False
            while j < n:
                d = texto[j]
                if d == "\\":
                    j += 2
                    continue
                if d == "[":
                    classe = True
                elif d == "]":
                    classe = False
                elif d == "/" and not classe:
                    break
                elif d == "\n":
                    raise FalhaAoSanear(f"regex sem fim perto de: {texto[i:i + 40]!r}")
                j += 1
            j += 1
            while j < n and texto[j].isalpha():
                j += 1
            fora.append(texto[i:j])
            i, ultimo = j, "s"
            continue
        if js and c == "{":
            pilha.append("{")
        elif js and c == "}" and pilha and pilha[-1] == "{":
            pilha.pop()
            if pilha and pilha[-1] == "tpl":       # o `}` que fecha um ${ }: volta ao template
                fora.append(c)
                i += 1
                ultimo = "}"
                continue
        if c.isalnum() or c in "_$":
            m = re.match(r"[\w$]+", texto[i:])
            fora.append(m.group(0))
            i += m.end()
            ultimo = m.group(0)
            continue
        fora.append(c)
        if not c.isspace():
            ultimo = c
        i += 1
    return _assentar("".join(fora))


def sanear_codigo(texto: str, linguagem: str) -> str:
    novo = _sanear_c(texto, linguagem)
    if _sanear_c(novo, linguagem) != novo:
        raise FalhaAoSanear("sanear não é estável (a leitura das strings se perdeu)")
    return novo


# ── HTML / XML ─────────────────────────────────────────────────────────────────────────────────

def _sem_comentarios_xml(texto: str) -> str:
    return _assentar(re.sub(r"<!--.*?-->", SENTINELA, texto, flags=re.S))


def sanear_html(texto: str) -> str:
    partes = re.split(r"(<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>)", texto,
                      flags=re.S | re.I)
    fora = []
    for k, parte in enumerate(partes):
        if k % 2 == 0:
            fora.append(re.sub(r"<!--.*?-->", SENTINELA, parte, flags=re.S))
            continue
        m = re.match(r"(<(script|style)\b[^>]*>)(.*?)(</\2>)", parte, flags=re.S | re.I)
        abre, tipo, corpo, fecha = m.group(1), m.group(2).lower(), m.group(3), m.group(4)
        if tipo == "script" and "src=" not in abre and corpo.strip():
            corpo = _sanear_c(corpo, "js")
        elif tipo == "style" and corpo.strip():
            corpo = _sanear_c(corpo, "css")
        fora.append(abre + corpo + fecha)
    return _assentar("".join(fora))


def _forma_xml(texto: str) -> list:
    """A árvore como lista comparável; o espaço entre elementos (onde estava o comentário) não conta."""
    return [(e.tag, sorted(e.attrib.items()), (e.text or "").strip(), (e.tail or "").strip())
            for e in ET.fromstring(texto.encode("utf-8")).iter()]


def sanear_xml(texto: str) -> str:
    novo = _sem_comentarios_xml(texto)
    if _forma_xml(texto) != _forma_xml(novo):
        raise FalhaAoSanear("o XML saneado difere do original")
    return novo


# ── linha com # (shell, TOML, requirements) ────────────────────────────────────────────────────

def _comentario_de_linha(linha: str, shell: bool) -> int:
    """Onde começa o comentário (`-1` = não há). Fora de aspas; no shell, `#` só depois de espaço
    (`$#`, `${#x}` e `a#b` não são comentário)."""
    aspa, k = "", 0
    while k < len(linha):
        c = linha[k]
        if aspa:
            if c == "\\" and aspa == '"':
                k += 2
                continue
            if c == aspa:
                aspa = ""
        elif c in "\"'":
            aspa = c
        elif c == "\\" and shell:
            k += 2
            continue
        elif c == "#" and (k == 0 or linha[k - 1] in " \t" or not shell):
            return k
        k += 1
    return -1


def sanear_hash(texto: str, tipo: str) -> str:
    fora = []
    for n, linha in enumerate(texto.split("\n")):
        if n == 0 and linha.startswith("#!"):
            fora.append(linha)
            continue
        if n <= 1 and _CODIFICACAO.match(linha):
            fora.append(linha)
            continue
        k = _comentario_de_linha(linha, shell=tipo in ("sh", "yml"))
        fora.append(linha if k < 0 else linha[:k] + SENTINELA)
    novo = _assentar("\n".join(fora))
    if tipo == "toml" and tomllib.loads(novo) != tomllib.loads(texto):
        raise FalhaAoSanear("o TOML saneado difere do original")
    if tipo == "yml":
        try:
            import yaml
        except ImportError:
            yaml = None
        if yaml is not None and yaml.safe_load(novo) != yaml.safe_load(texto):
            raise FalhaAoSanear("o YAML saneado difere do original")
    return novo


# ── PowerShell: o parser dele ──────────────────────────────────────────────────────────────────

_PS_COMENTARIOS = (
    "$t=$null;$e=$null;"
    "[void][System.Management.Automation.Language.Parser]::ParseFile($args[0],[ref]$t,[ref]$e);"
    "if($e.Count){'ERRO '+$e[0].Message;exit 1};"
    "$t|?{$_.Kind -eq 'Comment' -and $_.Text -notmatch '^#requires'}|%{''+$_.Extent.StartOffset+' '+$_.Extent.EndOffset}"
)


def _powershell() -> str:
    for exe in ("pwsh", "powershell"):
        if shutil.which(exe):
            return exe
    raise FalhaAoSanear("sem PowerShell para ler o .ps1 (instale o pwsh)")


def _ps_comentarios(caminho: Path) -> list[tuple[int, int]]:
    r = subprocess.run([_powershell(), "-NoProfile", "-NonInteractive", "-Command",
                        f"& {{{_PS_COMENTARIOS}}} '{caminho}'"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise FalhaAoSanear(f"o PowerShell não leu {caminho.name}: {r.stdout.strip()} {r.stderr.strip()}")
    return [tuple(map(int, l.split())) for l in r.stdout.split("\n") if l.strip()]


def sanear_ps1(caminho: Path) -> str:
    texto = caminho.read_text(encoding="utf-8-sig")
    for a, b in sorted(_ps_comentarios(caminho), reverse=True):
        texto = texto[:a] + SENTINELA + texto[b:]
    novo = _assentar(texto)
    tmp = caminho.with_name(caminho.stem + ".saneado.ps1")
    tmp.write_text(novo, encoding="utf-8-sig")
    try:
        if _ps_comentarios(tmp):
            raise FalhaAoSanear(f"sobrou comentário em {caminho.name}")
    finally:
        tmp.unlink()
    return novo


# ── JSON ───────────────────────────────────────────────────────────────────────────────────────

def sanear_json(caminho: Path, texto: str) -> str:
    dado = json.loads(texto)
    tirar = {"_meta"} if "capabilities" not in caminho.parts else {"_meta", "description"}
    if not isinstance(dado, dict) or not (tirar & dado.keys()):
        return texto
    for k in tirar:
        dado.pop(k, None)
    recuo = 2 if "\n" in texto.strip() else None
    return json.dumps(dado, ensure_ascii=False, indent=recuo) + ("\n" if texto.endswith("\n") else "")


# ── o artefato inteiro ─────────────────────────────────────────────────────────────────────────

def _tipo(p: Path) -> str | None:
    s = p.suffix.lower()
    if p.name in NOMES_SEM_COMENTARIO or s in BINARIOS or s in SEM_COMENTARIO and p.name != "requirements.lock":
        return None
    if p.name.startswith("requirements") and s in (".txt", ".lock"):
        return "req"
    return {".py": "py", ".js": "js", ".jsx": "js", ".css": "css", ".rs": "rs", ".proto": "proto",
            ".html": "html", ".xml": "xml", ".svg": "xml", ".ps1": "ps1", ".sh": "sh",
            ".toml": "toml", ".json": "json", ".yml": "yml", ".yaml": "yml"}.get(s, "?")


def sanear_arquivo(p: Path) -> bool:
    """Saneia `p` no lugar. Devolve se mudou."""
    tipo = _tipo(p)
    if tipo is None:
        return False
    if tipo == "?":
        raise FalhaAoSanear(f"tipo de arquivo que o sanear não conhece: {p} (ensine-o ou tire da allowlist)")
    if tipo == "ps1":
        novo = sanear_ps1(p)
        texto = p.read_text(encoding="utf-8-sig")
    else:
        texto = p.read_text(encoding="utf-8")
        if SENTINELA in texto:
            raise FalhaAoSanear(f"{p} tem um caractere NUL")
        novo = {"py": lambda: sanear_python(texto),
                "js": lambda: sanear_codigo(texto, "js"),
                "css": lambda: sanear_codigo(texto, "css"),
                "rs": lambda: sanear_codigo(texto, "rs"),
                "proto": lambda: sanear_codigo(texto, "proto"),
                "html": lambda: sanear_html(texto),
                "xml": lambda: sanear_xml(texto),
                "sh": lambda: sanear_hash(texto, "sh"),
                "toml": lambda: sanear_hash(texto, "toml"),
                "req": lambda: sanear_hash(texto, "req"),
                "yml": lambda: sanear_hash(texto, "yml"),
                "json": lambda: sanear_json(p, texto)}[tipo]()
    if novo == texto:
        return False
    if tipo == "ps1":
        p.write_text(novo, encoding="utf-8-sig")
    else:
        p.write_bytes(novo.encode("utf-8"))
    return True


def _conferir_externo(dest: Path) -> None:
    """O que o próprio interpretador confere: `node --check` nos JS e `bash -n` nos .sh."""
    node, bash = shutil.which("node"), shutil.which("bash")
    for p in sorted(dest.rglob("*")):
        if p.suffix == ".js" and node:
            r = subprocess.run([node, "--check", str(p)], capture_output=True, text=True)
            if r.returncode:
                raise FalhaAoSanear(f"node --check reprovou {p}: {r.stderr.strip()[:300]}")
        if p.suffix == ".sh" and bash and sys.platform != "win32":
            r = subprocess.run([bash, "-n", str(p)], capture_output=True, text=True)
            if r.returncode:
                raise FalhaAoSanear(f"bash -n reprovou {p}: {r.stderr.strip()[:300]}")


def sanear(dest: Path) -> int:
    mudados = 0
    for p in sorted(dest.rglob("*")):
        if p.is_file() and p != dest / "README.md":          # o README gerado pelo publish
            try:
                mudados += sanear_arquivo(p)
            except FalhaAoSanear as e:
                raise FalhaAoSanear(f"{p.relative_to(dest)}: {e}") from None
    _conferir_externo(dest)
    conferir(dest)
    return mudados


def conferir(dest: Path) -> None:
    """A rede de segurança: depois de sanear, nada pode ter sobrado."""
    sobras = []
    for p in sorted(dest.rglob("*")):
        if not p.is_file() or p == dest / "README.md":
            continue
        tipo = _tipo(p)
        if tipo is None:
            continue
        if tipo == "py":
            texto = p.read_text(encoding="utf-8")
            com = [t for t in tokenize.generate_tokens(io.StringIO(texto).readline)
                   if t.type == tokenize.COMMENT and not (t.start[0] == 1 and t.string.startswith("#!"))
                   and not (t.start[0] <= 2 and _CODIFICACAO.match(t.line))]
            if com or _docstrings(ast.parse(texto)):
                sobras.append(str(p.relative_to(dest)))
        elif tipo in ("js", "css", "rs", "proto"):
            texto = p.read_text(encoding="utf-8")
            if SENTINELA in _sanear_c(texto, tipo):
                sobras.append(str(p.relative_to(dest)))
        elif tipo in ("html", "xml"):
            if "<!--" in p.read_text(encoding="utf-8"):
                sobras.append(str(p.relative_to(dest)))
    if sobras:
        raise FalhaAoSanear("sobrou comentário em: " + ", ".join(sobras[:20]))


if __name__ == "__main__":
    alvo = Path(sys.argv[1])
    try:
        print(f"{sanear(alvo)} arquivos saneados em {alvo}")
    except FalhaAoSanear as e:
        print(f"FALHOU: {e}", file=sys.stderr)
        sys.exit(1)
