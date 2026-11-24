"""Os tetos de tempo das chamadas ao Media Composer — travados por regressão.

⚠️⚠️ **Um teto curto demais não devolve erro honesto: devolve uma DECISÃO ERRADA tomada
com confiança.** Foi o que aconteceu em 2026-08-16, e é a razão deste arquivo existir.

O `CloseBin` roda com o teto de CONSULTA (20 s), mas fechar bin **salva a bin** — numa
com dezenas de masters AMA o Avid mostra *"Closing bin window, please wait while the bin
is saved"* por bem mais que isso. O rpc estourou o prazo, o chamador leu a exceção como
*"não consegui fechar essa bin"* e gravou o relink **com outro nome**, enquanto o Media
Composer seguia fechando a bin normalmente. O editor ficou com DUAS bins, a certa não
estava aberta, e nada acusou erro.

⭐ A distinção que o código passou a fazer, e que este teste protege: **perguntar** é
rápido e tem teto curto; **ler ou gravar a bin inteira** é operação de arquivo e tem teto
generoso. Esperar demais custa espera; esperar de menos custa o resultado.

Não precisa do Media Composer: o canal é falso e só anota com que prazo cada chamada
teria ido.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "plugins" / "media-composer" / "servico"))

from avid.mcapi import TEMPO_DE_ARQUIVO_S, MediaComposer  # noqa: E402


class _CanalFalso:
    """Anota o prazo de cada chamada em vez de falar com alguém."""

    def __init__(self):
        self.prazos: list[float] = []

    def unary_unary(self, *_a, **_kw):
        def stub(_req, timeout=None):
            self.prazos.append(timeout)
            return object()
        return stub


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo: str, obtido, esperado) -> None:
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<48} -> {obtido}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    mc = MediaComposer()
    canal = _CanalFalso()
    mc._canal = canal

    print("── operação de ARQUIVO: prazo generoso ──────────────────────")
    mc.abrir_bin(r"D:\projeto\PRODUCAO-A 1.avb")
    ok("OpenBin espera o tempo de ler a bin", canal.prazos[-1], TEMPO_DE_ARQUIVO_S)

    mc.fechar_bin(r"D:\projeto\PRODUCAO-A 1.avb")
    ok("⭐ CloseBin espera o tempo de GRAVAR a bin", canal.prazos[-1], TEMPO_DE_ARQUIVO_S)

    print("\n── consulta: prazo curto, que é o certo para ela ────────────")
    mc._chamar("GetAppInfo")
    ok("uma pergunta não herda o prazo de arquivo", canal.prazos[-1], mc.timeout)
    ok("e o padrão continua sendo o de consulta", mc.timeout, 20.0)

    print("\n── a régua, para quem for mexer nos números ─────────────────")
    ok("⚠️ arquivo é MUITO maior que consulta (não 2x)",
       TEMPO_DE_ARQUIVO_S >= mc.timeout * 10, True)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
