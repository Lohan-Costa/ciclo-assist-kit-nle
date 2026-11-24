"""As duas armadilhas de plataforma que já custaram caro — travadas por regressão.

Rodar:

    PYTHONPATH=plugins/media-composer/servico .venv-win/Scripts/python tests/test_plataforma.py   (Windows)
    PYTHONPATH=plugins/media-composer/servico .venv/bin/python tests/test_plataforma.py            (macOS)

## Por que estes dois casos, e não outros

Os dois falham **em silêncio**, que é o modo de falha caro do desenvolvimento
cross-platform: em nenhum dos dois há exceção, log ou mensagem — o app segue em frente
e o sintoma aparece longe da causa, apontando para o disco ou para o editor.

1. **A coluna `Drive` da bin** vem `'SSD (D:)'` no Windows. Montar
   `f"{drive}:\\"` a partir disso dá um caminho sintaticamente válido que **nunca
   existe**, e o app relata *"89 clipes não encontrados"* com a mídia inteira no disco.
   ⚠️ A primeira correção deste bug foi escrita olhando um print onde a coluna estava
   truncada (`CICLO-MED…`), o que escondia o ` (D:)`: ela compilou, passou nos testes
   escritos com o valor imaginado e não consertou nada. **Estes casos vêm do valor lido
   pela API, não da tela.**

2. **`bins_abertas()` é de TRÊS estados.** `GetListOfWindows` não existe no MC 25.6, e
   tratar a ausência como "nenhuma bin aberta" **inverte o resultado**: o filtro zera a
   lista e a seleção volta vazia, como se o editor não tivesse marcado nada.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

import plataforma  # noqa: E402
from avid.mcapi import McApiNaoImplementado, MediaComposer  # noqa: E402

# (valor da coluna `Drive`, letra esperada) — `None` = "não há letra nesta string"
DRIVES = [
    # O formato REAL, lido da API no Windows.
    ("SSD (D:)", "D"),
    ("STORAGE (S:)", "S"),
    ("Windows (C:)", "C"),
    # Espaço sobrando dos dois lados, que a coluna às vezes traz.
    ("  SSD (D:)  ", "D"),
    # Volume SEM rótulo: a coluna vem só com a letra. Aceitar é barato e cobre o caso.
    ("D", "D"),
    ("D:", "D"),
    ("D:\\", "D"),
    ("d:", "D"),
    # ⚠️ Rótulo com parênteses NÃO é letra de unidade. É por isso que a expressão
    #    exige os dois-pontos: sem eles, um volume chamado 'ARQUIVO (2024)' viraria
    #    a unidade '2'.
    ("ARQUIVO (2024)", None),
    ("CAM A (backup)", None),
    # Só o rótulo — é o que o macOS devolve. No Windows cabe ao plano B (procurar
    # entre os volumes montados), não a esta função.
    ("SSD", None),
    ("", None),
    ("   ", None),
]

# (valor da coluna, rótulo esperado sem o sufixo de letra)
ROTULOS = [
    ("SSD (D:)", "SSD"),
    ("STORAGE (S:)", "STORAGE"),
    ("SSD", "SSD"),
    ("ARQUIVO (2024)", "ARQUIVO (2024)"),
    ("", ""),
]


class _McFalso(MediaComposer):
    """Um Media Composer de mentira, para exercitar a DEGRADAÇÃO sem abrir o editor.

    `sem_janelas=True` imita o MC 25.6, onde `GetListOfWindows` responde
    `UNIMPLEMENTED`.
    """

    def __init__(self, sem_janelas: bool, selecionados: dict):
        super().__init__()
        self.sem_janelas = sem_janelas
        self._selecionados = selecionados
        self.visitadas: list[str] = []

    def bins(self, flags=("AllTypes",)):
        return ["/proj/ABERTA.avb", "/proj/FECHADA.avb"]

    def bins_abertas(self):
        if self.sem_janelas:
            # É exatamente o que o cliente real faz ao receber UNIMPLEMENTED.
            try:
                raise McApiNaoImplementado("GetListOfWindows")
            except McApiNaoImplementado:
                return None
        return ["ABERTA"]

    def itens_de(self, caminho_absoluto, flags=("masterClips",),
                 apenas_selecionados=False):
        self.visitadas.append(caminho_absoluto)
        return self._selecionados.get(Path(caminho_absoluto).stem, [])


def main() -> int:
    falhas = []

    print("── coluna `Drive` da bin → letra de unidade ─────────────────")
    for valor, esperado in DRIVES:
        obtido = plataforma.letra_do_drive(valor)
        ok = obtido == esperado
        print(f"{'  ok  ' if ok else ' FALHA'} {valor!r:24} -> {obtido!r}")
        if not ok:
            falhas.append(f"letra_do_drive({valor!r}): {obtido!r} != {esperado!r}")

    print("\n── coluna `Drive` → rótulo do volume ────────────────────────")
    for valor, esperado in ROTULOS:
        obtido = plataforma.rotulo_do_drive(valor)
        ok = obtido == esperado
        print(f"{'  ok  ' if ok else ' FALHA'} {valor!r:24} -> {obtido!r}")
        if not ok:
            falhas.append(f"rotulo_do_drive({valor!r}): {obtido!r} != {esperado!r}")

    print("\n── seleção quando o MC NÃO sabe quais bins estão abertas ────")
    itens = {"ABERTA": [object()], "FECHADA": [object()]}

    mc = _McFalso(sem_janelas=False, selecionados=itens)
    r = mc.selecao()
    ok = list(r) == ["ABERTA"]
    print(f"{'  ok  ' if ok else ' FALHA'} MC que lista janelas: pergunta só à aberta -> {list(r)}")
    if not ok:
        falhas.append(f"com GetListOfWindows: esperava ['ABERTA'], veio {list(r)}")

    # ⭐ O CASO QUE INVERTE: sem o rpc, a resposta certa é perguntar a TODAS.
    # Uma implementação que tratasse `None` como lista vazia devolveria `{}` aqui —
    # "nada selecionado" com a bin cheia de clipes marcados, e sem erro nenhum.
    mc = _McFalso(sem_janelas=True, selecionados=itens)
    r = mc.selecao()
    ok = set(r) == {"ABERTA", "FECHADA"}
    print(f"{'  ok  ' if ok else ' FALHA'} MC sem GetListOfWindows: NÃO filtra -> {sorted(r)}")
    if not ok:
        falhas.append(f"sem GetListOfWindows: esperava as duas bins, veio {sorted(r)}")

    ok = bool(r)
    print(f"{'  ok  ' if ok else ' FALHA'} a seleção NÃO volta vazia (a falha invertida)")
    if not ok:
        falhas.append("a degradação zerou a seleção — é exatamente o bug que este teste trava")

    # ⛔ O PATH do serviço subido por `.app` no macOS (a casca do Resolve, 2026-10-04): sem o Homebrew,
    # o ffprobe some e a timeline inteira do PRODB entrou offline. Com sistema e pastas de mentira.
    import os
    from unittest import mock

    import plataforma as P
    minimo = "/usr/bin:/bin:/usr/sbin:/sbin"
    # O separador também é o do macOS: no Windows o `os.pathsep` é `;` (a simulação falhava aqui).
    with mock.patch.object(P, "E_MACOS", True), mock.patch.dict(os.environ, {"PATH": minimo}), \
            mock.patch.object(os, "pathsep", ":"), \
            mock.patch("os.path.isdir", lambda p: p == "/opt/homebrew/bin"):
        novas = P.completar_path()
        caminho = os.environ["PATH"]
        de_novo = P.completar_path()
    ok = (novas, caminho, de_novo) == (["/opt/homebrew/bin"], minimo + ":/opt/homebrew/bin", [])
    print(f"{'  ok  ' if ok else ' FALHA'} macOS: PATH mínimo de .app ganha o Homebrew que existe, uma vez -> {caminho}")
    if not ok:
        falhas.append(f"completar_path: {(novas, caminho, de_novo)}")
    with mock.patch.object(P, "E_MACOS", False), mock.patch.dict(os.environ, {"PATH": minimo}):
        ok = P.completar_path() == [] and os.environ["PATH"] == minimo
    print(f"{'  ok  ' if ok else ' FALHA'} Windows: o PATH não muda")
    if not ok:
        falhas.append("completar_path mexeu no PATH fora do macOS")

    total = len(DRIVES) + len(ROTULOS) + 5
    print(f"\n{total - len(falhas)}/{total} casos")
    for f in falhas:
        print("  !", f)
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
