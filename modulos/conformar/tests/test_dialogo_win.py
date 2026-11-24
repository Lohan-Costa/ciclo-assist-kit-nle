"""O seletor de pasta moderno do Windows, travado por regressão — sem ninguém clicar.

⭐ O que este teste protege é a parte que **falha em silêncio**: os índices da vtable do
`IFileOpenDialog`. Errar um índice não dá erro nenhum na hora de escrever — chama-se
outro método, com outra assinatura, e o processo morre com violação de acesso ou devolve
lixo. E o trecho só roda com alguém clicando, que foi exatamente o que tornou a primeira
tentativa (em PowerShell) cara demais de depurar.

Não abre janela: `dialogo_win.conferir()` monta o diálogo, grava as opções e as lê de
volta. Se `FOS_PICKFOLDERS` sobreviver à ida e à volta, a interface está encaixada.

Fora do Windows o teste se declara PULADO e sai com 0 — o macOS não tem o que testar
aqui, e um teste vermelho por plataforma errada só ensina a ignorar teste vermelho.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
SERVICO = RAIZ / "plugins" / "media-composer" / "servico"
sys.path.insert(0, str(SERVICO))

FOS_PICKFOLDERS = 0x00000020
FOS_FORCEFILESYSTEM = 0x00000040
FOS_ALLOWMULTISELECT = 0x00000200
FOS_PATHMUSTEXIST = 0x00000800


def main() -> int:
    if sys.platform != "win32":
        print("PULADO: o seletor moderno é do Windows (aqui: %s)" % sys.platform)
        return 0

    falhas: list[str] = []

    def ok(rotulo: str, condicao: bool, detalhe: str = "") -> None:
        marca = "ok  " if condicao else "FALHA"
        print(f"  {marca} {rotulo}" + (f"  ({detalhe})" if detalhe else ""))
        if not condicao:
            falhas.append(rotulo)

    import dialogo_win

    print("── a interface COM responde (sem abrir janela) ──────────────")
    try:
        opcoes = dialogo_win.conferir()
    except OSError as e:
        print(f"  FALHA CoCreateInstance/SetOptions: {e}")
        return 1

    ok("escolher pasta, não arquivo (FOS_PICKFOLDERS)",
       bool(opcoes & FOS_PICKFOLDERS), "0x%x" % opcoes)
    # ⚠️ Sem FORCEFILESYSTEM o editor pode escolher uma pasta VIRTUAL da shell (uma
    # biblioteca, "Este Computador"): existe na tela e não existe para o `os.scandir`.
    ok("só pasta com caminho de disco (FOS_FORCEFILESYSTEM)",
       bool(opcoes & FOS_FORCEFILESYSTEM))
    ok("⭐ várias diárias numa passada (FOS_ALLOWMULTISELECT)",
       bool(opcoes & FOS_ALLOWMULTISELECT))
    ok("a pasta tem de existir (FOS_PATHMUSTEXIST)",
       bool(opcoes & FOS_PATHMUSTEXIST))

    print("\n── o programa filho obedece ao contrato ─────────────────────")
    script = SERVICO / "dialogo_win.py"
    r = subprocess.run([sys.executable, str(script), "--conferir"],
                       capture_output=True, encoding="utf-8", errors="replace",
                       timeout=60)
    ok("roda como processo à parte (é assim que o serviço o chama)",
       r.returncode == 0, f"saiu {r.returncode}")
    ok("imprime as opções em hexadecimal",
       (r.stdout or "").strip().startswith("0x"), (r.stdout or "").strip())

    print("\n── o serviço sabe cair para a reserva ───────────────────────")
    import escolher

    # ⚠️ O que se testa aqui NÃO é o diálogo: é a promessa de que uma falha do moderno
    # vira MENSAGEM. Cair calado para a árvore antiga é o pior desfecho — o editor vê o
    # diálogo velho, conclui que nada mudou, e quem depura procura no lugar errado.
    chamadas: list[str] = []
    moderno, antigo = escolher._dialogo_win_moderno, escolher._dialogo_win_antigo
    try:
        def falhar(_titulo):
            raise RuntimeError("simulado: o seletor moderno falhou")

        def reserva(_titulo):
            chamadas.append("antigo")
            return ["D:\\FALSA"]

        escolher._dialogo_win_moderno, escolher._dialogo_win_antigo = falhar, reserva
        pastas = escolher.escolher_pastas("t")
        ok("a reserva foi chamada", chamadas == ["antigo"])
        ok("e devolveu a pasta assim mesmo", pastas == ["D:\\FALSA"], str(pastas))
        ok("⭐ o motivo fica registrado, não engolido",
           bool(escolher.ultimo_erro) and "simulado" in escolher.ultimo_erro,
           repr(escolher.ultimo_erro))

        # E o caminho feliz não deixa aviso velho para trás.
        escolher._dialogo_win_moderno = lambda _t: ["D:\\BOA"]
        pastas = escolher.escolher_pastas("t")
        ok("no caminho feliz não sobra aviso", escolher.ultimo_erro is None)
        ok("e a pasta vem do moderno", pastas == ["D:\\BOA"], str(pastas))
    finally:
        escolher._dialogo_win_moderno, escolher._dialogo_win_antigo = moderno, antigo
        escolher.ultimo_erro = None

    total = 10
    print(f"\n{total - len(falhas)}/{total} casos")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
