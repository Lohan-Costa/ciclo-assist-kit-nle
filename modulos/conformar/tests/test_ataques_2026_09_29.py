"""Time vermelho × time azul, 2ª rodada (2026-09-29) — a superfície que entrou depois de 24/09.

Rodar:

    .venv-win/Scripts/python tests/test_ataques_2026_09_29.py

Cada caso é um ATAQUE; passa = barrado. Relato em `docs/seguranca/2026-09-29-vermelho-azul-atualizar-aaf.md`.

O atacante é o mesmo de 24/09 (escreve na pasta combinada, controla uma página web e o DNS dela) e
mais um: **quem manda um AAF ao colorista** (o editor de outra produtora, um e-mail, um HD) — o
"Atualizar com dois arquivos" aceita AAF de quem não tem o De Lá Pra Cá.

⭐ O vigia: `os.stat`, `os.lstat`, `os.scandir`, `os.listdir`, `open` e `nt._getfinalpathname` são
embrulhados; qualquer chamada com o host do atacante no caminho é registrada. No Windows, TOCAR um
caminho `\\\\host\\share` abre sessão SMB com o host e entrega o hash NTLM do usuário (V2 de 24/09).
"""

from __future__ import annotations

import builtins
import os
import shutil
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

RAIZ = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(RAIZ / "plugins" / "media-composer" / "servico"), str(RAIZ / "motor")]

HOST = "atacante.exemplo"
from casos import raiz_das_amostras  # noqa: E402 (a pasta de testes, nas duas máquinas)
AMOSTRAS = Path(raiz_das_amostras())
AAF_REAL = AMOSTRAS / "03 CASOS" / "ATUALIZAR" / "U03 ATUALIZAR COM AAF" / "avid" / "U03 v01.aaf"

#: as grafias de caminho de rede que um AAF pode carregar no localizador
URLS_DO_ATACANTE = [
    f"file:////{HOST}/coleta/a.mxf",               # vira //host/… (UNC)
    f"file://{HOST}/coleta/b.mxf",                 # o host no lugar do "servidor" da URL
    f"file:///%5C%5C{HOST}%5Ccoleta%5Cc.mxf",      # \\host\… codificado
    rf"\\{HOST}\coleta\d.mxf",                     # UNC cru, sem ser URL
]


class Vigia:
    """Registra toda chamada de disco cujo caminho mencione o host do atacante."""

    def __init__(self):
        self.toques: list[str] = []
        self._orig = {}

    def _embrulhar(self, modulo, nome):
        original = getattr(modulo, nome, None)
        if original is None:
            return
        self._orig[(modulo, nome)] = original
        vigia = self

        def f(*a, **k):
            if a and HOST in str(a[0]).replace("%2E", "."):
                vigia.toques.append(f"{nome}({a[0]!r})")
                raise PermissionError("vigia: caminho do atacante")
            return original(*a, **k)
        setattr(modulo, nome, f)

    def __enter__(self):
        # `nt` (o `_getfinalpathname` do `resolve()`) só existe no Windows; no Mac o vigia roda sem ele
        for modulo, nome in ((os, "stat"), (os, "lstat"), (os, "scandir"), (os, "listdir"),
                             (builtins, "open"), (sys.modules.get("nt"), "_getfinalpathname")):
            if modulo is not None:
                self._embrulhar(modulo, nome)
        return self

    def __exit__(self, *exc):
        for (modulo, nome), original in self._orig.items():
            setattr(modulo, nome, original)
        return False


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def barrado(rotulo, ok_):
        nonlocal casos
        casos += 1
        print(f"  {'BARRADO ' if ok_ else 'PASSOU!!'} {rotulo}")
        if not ok_:
            falhas.append(rotulo)

    import atualizacao
    import sessao_receber as R

    sem_indice = mock.patch("media.pmr.indice_de", lambda *_a, **_k: SimpleNamespace(por_arquivo={}))

    with tempfile.TemporaryDirectory() as tmp, sem_indice, \
            mock.patch.object(R.plataforma, "pasta_dados", lambda: Path(tmp) / "dados"):
        (Path(tmp) / "dados" / "Cache" / "recebidos").mkdir(parents=True)
        recebidos = Path(tmp) / "dados" / "Cache" / "recebidos"

        print("── A1. AAF com o localizador de mídia apontando para o host do atacante ──")
        if not AAF_REAL.is_file():
            print(f"  PULADO — {AAF_REAL} não está neste disco")
        else:
            import aaf2
            mal = Path(tmp) / "malicioso.aaf"
            shutil.copy(AAF_REAL, mal)
            trocados = 0
            with aaf2.open(str(mal), "rw") as f:
                for m in f.content.mobs:
                    d = getattr(m, "descriptor", None)
                    if d is None or "Locator" not in d.keys():
                        continue
                    for loc in d["Locator"].value:
                        loc["URLString"].value = URLS_DO_ATACANTE[trocados % len(URLS_DO_ATACANTE)]
                        trocados += 1
            print(f"     ({trocados} localizadores trocados, em {len(URLS_DO_ATACANTE)} grafias)")
            s = R.SessaoReceber()
            # só as mídias do caso U03 (regra de 2026-10-04: um caso não vê mídia de outro projeto);
            # o isolamento chama PRIMEIRO a tranca de verdade (`caminho_confiavel`), que é o que se testa
            import casos as ilhas
            caso = ilhas.carregar("ATUALIZAR/U03 ATUALIZAR COM AAF")
            with ilhas.isolar_midia(caso), Vigia() as v:
                try:
                    a = s.abrir(str(mal))
                    carta, _f = s.carta_da_versao({"avulso": a["chave"]})
                    s._midia_da_carta(carta, recebidos)
                    s.comparar_versoes({"avulso": a["chave"]}, {"avulso": a["chave"]})
                    drt = s.preparar_avulso(a["chave"])["drt"]
                    erro = ""
                except Exception as e:  # noqa: BLE001
                    drt, erro = "", f"{type(e).__name__}: {e}"
            barrado("abrir, comparar, achar mídia e importar NÃO tocam o host do atacante"
                    + (f" (tocou: {v.toques[:3]})" if v.toques else ""), not v.toques)
            barrado("…e o caminho todo funcionou (não foi barrado por erro)" + (f" [{erro}]" if erro else ""),
                    not erro)
            if drt:
                import zipfile
                with zipfile.ZipFile(drt) as z:
                    texto = b"".join(z.read(n) for n in z.namelist())
                barrado("o host do atacante NÃO aparece no DRT (o Resolve não o abriria)",
                        HOST.encode() not in texto and HOST.encode("utf-16-le") not in texto)

        print("\n── A2. `trabalho` = caminho de rede no Comparar/Atualizar ──")
        for bruto in (rf"\\{HOST}\coleta\12345678-1234-4234-8234-123456789abc.drt",
                      f"//{HOST}/coleta/12345678-1234-4234-8234-123456789abc.drt"):
            with Vigia() as v:
                try:
                    atualizacao.arquivo_de_trabalho(bruto, recebidos)
                    recusou = False
                except ValueError:
                    recusou = True
            barrado(f"{bruto[:34]}…: recusado SEM tocar o host" + (f" (tocou: {v.toques[:2]})" if v.toques else ""),
                    recusou and not v.toques)

        print("\n── A3. ids forjados nas rotas do Atualizar ──")
        s = R.SessaoReceber()
        for rotulo, chamada in (
                ("registro com ../", lambda: s.atualizada({"avulso": "x"}, {}, registro="../../token")),
                ("partida com ..\\", lambda: s.carta_da_versao({"partida": "..\\..\\token"})),
                ("avulso que não é uuid", lambda: s.carta_da_versao({"avulso": "../../../Windows/win.ini"})),
                ("envio com ../", lambda: s.carta_da_versao({"envio": "../../token"})),
        ):
            try:
                chamada()
                barrado(f"{rotulo}: recusado", False)
            except (ValueError, LookupError):
                barrado(f"{rotulo}: recusado", True)

        print("\n── A4. AAF estragado ou falso ──")
        falso = Path(tmp) / "falso.aaf"
        falso.write_bytes(b"isto nao e um AAF " * 100)
        partes = [("bytes quaisquer com extensão .aaf", falso)]
        if AAF_REAL.is_file():
            cortado = Path(tmp) / "cortado.aaf"
            cortado.write_bytes(AAF_REAL.read_bytes()[: 200_000])
            partes.append(("AAF verdadeiro cortado ao meio", cortado))
        for rotulo, arq in partes:
            try:
                R.SessaoReceber().abrir(str(arq))
                barrado(f"{rotulo}: recusado com motivo", False)
            except ValueError as e:
                barrado(f"{rotulo}: recusado com motivo ({str(e)[:50]}…)", True)
            except Exception as e:  # noqa: BLE001 — um 500 com rastro é falha
                barrado(f"{rotulo}: recusado com motivo — veio {type(e).__name__}", False)

    print("\n── A5. uma página web e o DNS rebinding contra as rotas NOVAS ──")
    from api.portao import portao
    novas = ("/receber/abrir", "/receber/partidas", "/receber/comparar", "/receber/atualizar",
             "/receber/atualizada")
    for rota in novas:
        barrado(f"POST {rota} de https://site.exemplo (cross-site)",
                portao("127.0.0.1:7823", "https://site.exemplo", "cross-site", 10, rota) is not None)
        barrado(f"POST {rota} com Host 127.0.0.1.{HOST} (rebinding)",
                portao(f"127.0.0.1.{HOST}:7823", None, "same-origin", 10, rota) is not None)
    barrado("POST /receber/atualizada com o token ERRADO (sem Origin, como a casca)",
            portao("127.0.0.1:7823", None, None, 10, "/receber/atualizada", token="0" * 64,
                   token_esperado="f" * 64) is not None)

    print(f"\n{casos - len(falhas)}/{casos} barrados")
    for f in falhas:
        print(f"  ✗ {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
