#!/usr/bin/env python3
"""
publish.py — gera o artefato público do De Lá Pra Cá a partir deste repo privado.

Modelo copiado do Órbita (irmão deste projeto) — mesmo mecanismo, adaptado (só
Python aqui, sem Node/Rust). Roda SÓ EM CI, nunca na máquina do desenvolvedor:
rodar localmente exporia o ambiente local (.dev/, segredos, arquivos soltos) ao
mesmo bug de allowlist que este script existe para evitar. O repo público nunca
é editado à mão — ele é sempre a saída deste script.

Uso (em CI): python publish.py --source . --dest /tmp/public-checkout
"""

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# 1. ALLOWLIST — só o que está aqui é copiado para o artefato público.
#    Allowlist, não denylist: esquecer de publicar algo é chato; esquecer de
#    excluir algo é o risco de verdade. Um arquivo novo na raiz do projeto
#    NÃO é público até entrar nesta lista, de propósito.
# ---------------------------------------------------------------------------
ALLOWLIST = [
    "motor",
    "plugins",
    "tests",
    "tools",
    # O aplicativo: código-fonte e interface. `target/` e `gen/` ficam de fora
    # pelo IGNORE_DIR_NAMES abaixo — são 1,3 GB de artefato de compilação.
    "app",
    # ⭐ Regra do autor (2026-10-05): o público recebe SÓ código que funciona. Nenhum documento
    # (ADRs, ARCHITECTURE, revisões, VENDOR, READMEs de pasta — e todo `*.md`, pelo
    # IGNORE_DIR_NAMES); o README é GERADO, mínimo (PUBLIC_README). Comentários e docstrings
    # saem no `sanear.py`. `tests/` é copiado só para o CI rodar contra o artefato, e sai antes
    # do push (`run_tests`).
    "VERSION",
    "LICENSE",
    # o workflow que monta os instaladores (roda SÓ no repo público: `if: github.repository`)
    ".github/workflows/release.yml",
    "dev.sh",
    "dev.ps1",
    "requirements.txt",
    # ⚠️ O lock VAI JUNTO. Publicar só o `requirements.txt`, que usa `>=`, entregaria ao
    # público exatamente o problema que o lock existe para fechar: resolução silenciosa de
    # uma versão mais nova no build. Guia de Desenvolvimento Seguro §4.
    "requirements.lock",
    # o build do instalador (montar o motor: PyInstaller fixo), feito no repo PÚBLICO pelo release
    "requirements-build.txt",
]
# `DECISIONS.md` fica DE FORA de propósito: cita nome de projeto/cliente real e
# caminhos de disco. Vive em `.dev/` (gitignored), nunca teve allowlist. Mesma
# decisão do Órbita para o par DECISIONS.md/VALIDATION.md dele.
#
# `.gitignore` NÃO é copiado do privado — o dele tem entradas que ANUNCIAM o
# esquema privado (`.dev/`). O público recebe um `.gitignore` GERADO e limpo
# (ver PUBLIC_GITIGNORE + write_public_gitignore).

# `.gitignore` do repo PÚBLICO: mínimo, padrão, sem nada que revele o privado.
PUBLIC_GITIGNORE = """\
# Ambiente (um venv por sistema operacional — ver ADR 0011)
.venv/
.venv-win/
__pycache__/
*.py[cod]
build/
dist/
*.spec.bak

# Empacotamento
build.avpi
plugins/*/painel/static/version.js

# Segredos (rede de segurança para quem for contribuir)
.env
.env.*

# Sistema / editor
.DS_Store
Thumbs.db
._*
.vscode/*
!.vscode/extensions.json
.idea/
*.sw?

# Saídas de trabalho e material de teste
saidas/
*.aaf
*.avb
*.log
bench_*.jsonl
"""

# O README do repo PÚBLICO: o que é, do que precisa, como rodar, a licença. Nada de desenho.
PUBLIC_README = """# De Lá Pra Cá

Plugin de pós-produção para Avid Media Composer e DaVinci Resolve Studio: leva a timeline de
um programa para o outro e religa a mídia original de câmera.

## Instalar

Baixe o instalador na página de versões (Releases) deste repositório. Ele traz tudo: não é preciso
instalar Python, ffmpeg nem nada mais.

- Windows: o arquivo `.exe`. O instalador não tem assinatura digital, então o Windows mostra o aviso
  do SmartScreen: clique em "Mais informações" e depois em "Executar assim mesmo".
- Mac (Apple Silicon, M1 ou mais novo): o arquivo `.dmg`. Abra-o e arraste o De Lá Pra Cá para Aplicativos.
  O app não tem certificado da Apple, então a primeira abertura é bloqueada ("Não Foi Aberto"): clique
  em OK, abra Ajustes do Sistema › Privacidade e Segurança, role até o fim e clique em "Abrir Mesmo
  Assim". Só na primeira vez.

Depois de instalar, abra o De Lá Pra Cá e instale os plugins em Configurações › Integrações, com o
programa de edição fechado.

Precisa de: Windows 10/11 ou macOS (testado no 15), Avid Media Composer 25.6+ e/ou DaVinci Resolve
Studio 19+.

## Rodar a partir do código

Precisa de Python 3.12+, ffmpeg/ffprobe no PATH e Rust (para compilar o aplicativo em `app/`).

Windows: `.\\dev.ps1` · macOS: `./dev.sh`

Instalar o painel no Media Composer: `python tools/pack.py`

## Licença

GPL-3.0 — ver `LICENSE`.

Idealizado por Lohan Costa, edt. Desenvolvido com Claude Code.
"""

# Prefixos de linha que são removidos dos arquivos publicados. Só o
# explicitamente marcado — nada de heurística ampla, que apagaria docstring e
# comentário de segurança legítimos junto.
INTERNAL_MARKERS = ["INTERNAL:", "dev-note:"]

# Diretórios de build/dependência que NUNCA vão no artefato público, mesmo que
# apareçam dentro de uma pasta allowlisted. Um checkout de CI limpo normalmente
# nem os tem — mas um step de cache pode reintroduzi-los.
IGNORE_DIR_NAMES = shutil.ignore_patterns(
    "__pycache__", ".venv", ".venv-win", "build", "dist", ".pytest_cache",
    "target", "gen",
    "._*", "*.spec",
    "*.md",
)


# Dentro de uma pasta da allowlist, o que fica PRIVADO (decisão do autor, 2026-10-28): o ARO é engenharia reversa do
# Media Composer (e o app instalado não o usa — a dylib só se monta no desenvolvimento); as bancadas e as medições são
# ferramentas do laboratório, com caminhos de produções reais.
PRIVADO = ["tools/aro", "tools/bancada_*", "tools/medicoes"]


def copy_allowlisted(source: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for entry in ALLOWLIST:
        src_path = source / entry
        if not src_path.exists():
            print(f"aviso: caminho da allowlist não encontrado, pulando: {entry}", file=sys.stderr)
            continue
        dest_path = dest / entry
        if src_path.is_dir():
            shutil.copytree(src_path, dest_path, dirs_exist_ok=True, ignore=IGNORE_DIR_NAMES)
        else:
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dest_path)
    for padrao in PRIVADO:
        for p in dest.glob(padrao):
            shutil.rmtree(p) if p.is_dir() else p.unlink()


def write_public_gitignore(dest: Path) -> None:
    """Escreve o `.gitignore` do repo PÚBLICO — gerado, não copiado do privado
    (que revela `.dev/`). Ver PUBLIC_GITIGNORE."""
    (dest / ".gitignore").write_text(PUBLIC_GITIGNORE, encoding="utf-8")


def write_public_readme(dest: Path) -> None:
    (dest / "README.md").write_text(PUBLIC_README, encoding="utf-8")


def strip_comments(dest: Path) -> None:
    """Regra do autor (2026-10-05): todo comentário e toda docstring saem — ver `sanear.py`,
    que confere cada arquivo e FALHA a publicação se algo sobrar ou mudar o programa."""
    from sanear import FalhaAoSanear, sanear

    try:
        n = sanear(dest)
    except FalhaAoSanear as e:
        print(f"SANEAR FALHOU — abortando o publish: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"Comentários e docstrings retirados de {n} arquivos.")


def strip_internal_markers(dest: Path) -> None:
    for path in dest.rglob("*"):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        lines = text.splitlines(keepends=True)
        filtered = [
            line for line in lines
            if not any(marker in line for marker in INTERNAL_MARKERS)
        ]
        if len(filtered) != len(lines):
            path.write_text("".join(filtered), encoding="utf-8")


# ⛔ Nomes de produção e de cliente: nenhum vai ao público, em NENHUMA grafia (banco, bugs-do-mundo-real B104: a lista
# por string exata deixava passar "producao_a" e "producao-a"). Compara-se a forma normalizada (sem acento e
# caixa, separadores viram espaço); termo curto só como palavra inteira. Medido em 2026-10-28 no artefato saneado:
# as bancadas de tools/, o molde formas_r19.xml e o preset_aaf.xml ainda levavam nomes reais.
TERMOS_BLOQUEADOS = ["PRODUCAO-A", "PRODUCAO-A", "PRODUCAO-C", "PRODC", "PRODUCAO-B", "PRODUCAO-G", "EMISSORA", "PRODUCAO-V",
                     "MIDIAS DE TESTES"]


def _normalizar(texto: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().upper()
    return re.sub(r"[\s_\-.;:/\\]+", " ", t)


def bloqueados_em(texto: str) -> list[str]:
    """Os termos bloqueados que aparecem em `texto`, em qualquer grafia."""
    t = f" {_normalizar(texto)} "
    achados = []
    for termo in TERMOS_BLOQUEADOS:
        n = _normalizar(termo)
        if (re.search(rf"(?<![A-Z0-9]){re.escape(n)}(?![A-Z0-9])", t) if len(n) <= 4 else n in t):
            achados.append(termo)
    return achados


def run_name_scan(dest: Path) -> None:
    """Trava da publicação, como a de segredos: nome bloqueado no artefato (já saneado) falha o publish."""
    falhas = []
    for path in sorted(dest.rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError):
            continue
        for termo in bloqueados_em(text):
            falhas.append(f"{path.relative_to(dest)}: {termo}")
    if falhas:
        print("NOME DE PRODUÇÃO/CLIENTE NO ARTEFATO PÚBLICO — abortando o publish:", file=sys.stderr)
        for f in falhas:
            print(f"  {f}", file=sys.stderr)
        sys.exit(1)
    print("Varredura de nomes ok.")


def run_secret_scan(dest: Path) -> None:
    """
    Gate obrigatório — falha o pipeline em qualquer achado. Requer gitleaks
    instalado no runner de CI. Não tornar isto opcional nem warn-only.
    """
    result = subprocess.run(
        ["gitleaks", "detect", "--source", str(dest), "--no-git", "-v"],
        capture_output=True,
        text=True,
        errors="replace",
    )
    if result.returncode != 0:
        print("SCAN DE SEGREDOS FALHOU — abortando o publish.", file=sys.stderr)
        print(result.stdout, file=sys.stderr)
        print(result.stderr, file=sys.stderr)
        sys.exit(1)
    print("Scan de segredos ok.")


def run_tests(dest: Path) -> None:
    """
    Roda contra o artefato GERADO, não contra a árvore completa deste repo —
    é isso que prova que o público é instalável e testável sozinho. Pega
    qualquer `tests/test_*.py` (os scripts de bancada em `.dev/` não entram
    aqui: nem estão no artefato, nem casam o padrão de nome).
    """
    result = subprocess.run(
        # ⚠️⚠️ O LOCK, não o `.txt`. O `requirements.txt` é todo `>=`, então instalar por
        # ele deixa o build do release resolver silenciosamente a versão mais nova de
        # cada pacote — que é exatamente o ataque de cadeia de suprimentos que o lock
        # existe para fechar. Ter o lock no repositório e instalar pelo outro arquivo é
        # a pior combinação: parece mitigado e não está.
        [sys.executable, "-m", "pip", "install", "--quiet", "-r", "requirements.lock"],
        cwd=dest,
    )
    if result.returncode != 0:
        print("Falhou: pip install -r requirements.lock — abortando.", file=sys.stderr)
        sys.exit(1)

    for test_file in sorted((dest / "tests").glob("test_*.py")):
        result = subprocess.run([sys.executable, str(test_file)], cwd=dest)
        if result.returncode != 0:
            print(f"Falhou: {test_file.name} — abortando.", file=sys.stderr)
            sys.exit(1)


def drop_tests(dest: Path) -> None:
    """Os testes provam o artefato saneado, mas não vão para o público (decisão do autor,
    2026-10-05: os rótulos dos casos explicam cada regra)."""
    shutil.rmtree(dest / "tests", ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", default=".", type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--skip-tests", action="store_true", help="para depuração local do allowlist")
    args = parser.parse_args()

    if args.dest.exists():
        shutil.rmtree(args.dest)

    copy_allowlisted(args.source, args.dest)
    write_public_gitignore(args.dest)
    write_public_readme(args.dest)
    strip_internal_markers(args.dest)
    strip_comments(args.dest)
    if not args.skip_tests:
        run_tests(args.dest)
    drop_tests(args.dest)
    run_name_scan(args.dest)
    run_secret_scan(args.dest)

    print(f"Artefato público gerado em {args.dest}")
    print("Próximo passo (feito pelo workflow de CI): commit + push pro repo público.")


if __name__ == "__main__":
    main()
