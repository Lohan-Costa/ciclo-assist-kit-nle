"""Som direto (WAV do gravador) → masters de áudio numa bin NOVA do Media Composer: a operação 6 do ensaio.

Plano: `docs/plano/2026-10-31-operacoes-do-ensaio.md`. Quem autora é o MOTOR do De Lá Pra Cá
(`_DeLaPraCa/motor/avb_bin/audio.py::autorar_masters`) — um master AMA de áudio por arquivo,
escrito direto na `.avb`. Aqui só se chama, pelo Python DELE, num processo filho: é o mesmo
desenho da ponte do `conformar` (o Assist orquestra, o DLPC processa) até a unificação.

Do banco (`protocolos/avb/escrita.md` §A TAXA DO PROJETO; `transversal/operacoes.md`):

- ⛔⛔ **Nunca `LinkFile`** para som direto: o diálogo "Audio Start-Time Options" volta a cada WAV.
- ⛔⛔ **`fps` e `drop` do PROJETO, sempre.** Sem eles a cadeia sai na taxa do molde (23,976) e
  um projeto 25 recebe masters errados, calado (o B001). Lidos do MC aberto, nunca chutados.
- ⚠️ `variante_trocada`: o motor não tem o molde da variante do arquivo (ex.: WAV sem cena) e
  usa outro. Funcionou no ensaio de 31/10, mas é DITO na resposta, não escondido.
- ⭐ O motor gera MobIDs NOVOS a cada chamada — o MC serve mob pela SESSÃO, e reautorar com o
  mesmo MobID faria o editor ver a versão velha.

⭐ **Sobre CÓPIAS** (plano, op. 6): os WAV vão para `<pasta>/_para_consolidar/`, e é deles que os
masters apontam. O consolidar (op. 7) troca o elo para a mídia gerenciada; os originais ficam
intocados. Cópia que já existe com o mesmo tamanho é reaproveitada.

⛔ **Bin NOVA, só.** Escrever numa bin que existe exigiria `CloseBin` → mesclar → `OpenBin`
(`protocolos/avb/escrita.md`); para o ensaio não há por que arriscar a bin do editor. Grava
ao lado (`.avb.novo`, invisível ao MC) e troca com `os.replace` (mesmo volume, atômico).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable

AUDIOS = {".wav", ".aif", ".aiff", ".bwf"}

#: Onde ficam as cópias que os masters apontam (começa com _ — os listadores de mídia a pulam).
PASTA_DAS_COPIAS = "_para_consolidar"

MARCA = "##RESULTADO##"


class SomDiretoFalhou(RuntimeError):
    """A frase vai ao modelo como está."""


def raiz_do_dlpc(inicio: Path | None = None) -> Path | None:
    """O De Lá Pra Cá: o MÓDULO deste repo (`modulos/conformar`, fase 2 do plano um app só, 2026-11-07), achado a
    partir de `inicio` (padrão: este arquivo) SUBINDO de pasta (regra da família).

    ⛔ Revisão de 2026-11-07: a reserva antiga procurava a pasta `_DeLaPraCa` vizinha — que desde a fase 6 é a cópia
    ARQUIVADA (`9 ARQUIVADOS/`). Achá-la seria rodar código parado, calado; sem o módulo, a resposta é "não achei"."""
    aqui = (inicio or Path(__file__)).resolve()
    for p in [aqui, *aqui.parents]:
        modulo = p / "modulos" / "conformar"
        if (modulo / "motor" / "avb_bin" / "audio.py").is_file():
            return modulo
    return None


def python_do_dlpc(raiz: Path) -> Path | None:
    candidatos = [raiz / ".venv-win" / "Scripts" / "python.exe", raiz / ".venv" / "bin" / "python",
                  raiz / ".venv" / "Scripts" / "python.exe"]
    # A venv do OUTRO sistema está no mesmo SSD e não executa aqui (Exec format error · WinError 193).
    candidatos = [c for c in candidatos if (c.suffix == ".exe") == (sys.platform == "win32")]
    for c in candidatos:
        if c.is_file():
            return c
    return None


def audios_da_pasta(pasta: str | Path) -> list[Path]:
    """Os áudios da pasta e subpastas, em ordem; pula pasta de trabalho (`_…`, `.…`) e `._*`."""
    raiz = Path(pasta)
    achados = []
    for p in sorted(raiz.rglob("*")):
        partes = p.relative_to(raiz).parts
        if any(x.startswith(("_", ".")) for x in partes):
            continue
        if p.is_file() and p.suffix.lower() in AUDIOS:
            achados.append(p)
    return achados


def copiar(audios: list[Path], destino: Path) -> list[Path]:
    destino.mkdir(parents=True, exist_ok=True)
    copias = []
    for a in audios:
        c = destino / a.name
        if not (c.is_file() and c.stat().st_size == a.stat().st_size):
            shutil.copy2(a, c)
        copias.append(c)
    return copias


_FILHO = r"""
import json, sys
sys.path.insert(0, sys.argv[1])
from avb_bin import audio as A
p = json.loads(sys.argv[2])
r = A.autorar_masters(p["arquivos"], p["saida"], fps=p["fps"], drop=p["drop"])
r["mapa"] = {k: str(v) for k, v in (r.get("mapa") or {}).items()}
print("##RESULTADO##" + json.dumps(r, ensure_ascii=False, default=str), flush=True)
"""


def autorar(arquivos: list[Path], saida: Path, fps: float, drop: bool) -> dict:
    """O `autorar_masters` do DLPC, pelo Python dele."""
    raiz = raiz_do_dlpc()
    if raiz is None:
        raise SomDiretoFalhou("O De Lá Pra Cá não está nesta máquina — é ele quem monta o som direto.")
    py = python_do_dlpc(raiz)
    if py is None:
        raise SomDiretoFalhou(f"O De Lá Pra Cá está em {raiz}, mas sem o ambiente Python dele (.venv-win).")
    opcoes: dict = {}
    if sys.platform == "win32":
        opcoes["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
    pedido = {"arquivos": [str(a) for a in arquivos], "saida": str(saida), "fps": fps, "drop": drop}
    try:
        p = subprocess.run([str(py), "-c", _FILHO, str(raiz / "motor"), json.dumps(pedido)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace",
                           stdin=subprocess.DEVNULL, timeout=600, cwd=str(raiz),
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"}, **opcoes)
    except subprocess.TimeoutExpired:
        raise SomDiretoFalhou("o motor do De Lá Pra Cá não terminou em 10 min") from None
    linha = next((l for l in reversed((p.stdout or "").splitlines()) if l.startswith(MARCA)), None)
    if linha is None:
        fim = ((p.stderr or "") + (p.stdout or "")).strip().splitlines()[-3:]
        raise SomDiretoFalhou("o motor do De Lá Pra Cá falhou: " + " | ".join(fim or ["sem mensagem"]))
    return json.loads(linha[len(MARCA):])


def montar(m, pasta: str | Path, bin_nome: str, *,
           relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, object]:
    """`m` é a ponte (`mcapi.MediaComposer`, aberta)."""
    relatar = relatar or (lambda *_: None)
    audios = audios_da_pasta(pasta)
    if not audios:
        raise SomDiretoFalhou(f"não há áudio (.wav/.aif) em {pasta}")
    projeto = m.projeto(recarregar=True)
    destino = Path(projeto["caminho"]) / f"{bin_nome}.avb"
    if destino.exists():
        raise SomDiretoFalhou(f"já existe a bin '{bin_nome}' no projeto — escolha outro nome (esta operação só "
                              "cria bin nova, para nunca regravar uma bin do editor)")
    fps, drop = float(projeto["fps_aprox"]), bool(projeto["drop_frame"])
    relatar("copiando o som direto", None, f"{len(audios)} arquivo(s)")
    copias = copiar(audios, Path(pasta) / PASTA_DAS_COPIAS)
    relatar("montando os masters de áudio (De Lá Pra Cá)", None, f"{fps:g} fps")
    novo = destino.with_name(destino.name + ".novo")       # extensão que o MC não enxerga
    r = autorar(copias, novo, fps, drop)
    if not r.get("clipes"):
        novo.unlink(missing_ok=True)
        raise SomDiretoFalhou("o motor não montou nenhum master: " + json.dumps(r.get("pulados"), ensure_ascii=False))
    os.replace(novo, destino)
    relativo = m.caminho_relativo_da_bin(str(destino))
    m._chamar("OpenBin", _timeout=60, bin_path=relativo)
    nomes = [i.nome for i in m.itens_da_bin(relativo)]
    if len(nomes) < int(r["clipes"]):
        raise SomDiretoFalhou(f"a bin '{bin_nome}' abriu com {len(nomes)} de {r['clipes']} masters — confira na tela")
    avisos = []
    if r.get("variante_trocada"):
        avisos.append(f"{len(r['variante_trocada'])} arquivo(s) montados com o molde de outra variante "
                      "(o motor não tem o molde exato; funcionou assim no ensaio de 31/10)")
    return {"bin": bin_nome, "masters": nomes, "fps": fps, "drop": drop, "copias": str(Path(pasta) / PASTA_DAS_COPIAS),
            "pulados": r.get("pulados") or [], "avisos": avisos}
