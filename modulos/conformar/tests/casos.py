"""Os casos de teste como ILHAS: cada um com o seu projeto, as suas mídias e as suas expectativas.

Regra do autor (2026-10-04): "não podemos misturar projetos". Um teste não pode achar mídia de
outro projeto só porque ela está montada na máquina — o PRODUCAO-A é laboratório, o PRODB é
filme real, e o resultado de um não pode depender do que o outro deixou no disco. Antes, o teste do
caso U03 (PRODA) varria TODO `Avid MediaFiles` montado (`pmr.raizes_de_midia`) e todo volume (o
`existe_aqui` do receptor): a contagem de "mídia online" mudava com os HDs plugados.

Cada caso declara, no `caso.json` ao lado do `CASO.md`:

    {"projeto": "PRODUCAO-A",
     "midia": {"gerenciada": [{"disco": "SSD", "caminho": "Avid MediaFiles/MXF/0200230405"}, …],
               "arquivos":   [{"disco": …, "caminho": …}]},          # pastas de AMA/originais
     "fontes": {"prproj": {"disco": …, "caminho": …}},               # arquivos nomeados do caso
     "expectativas": {…}}                                             # números, com o porquê

`isolar_midia(caso)` faz o receptor enxergar SÓ essas pastas. Pasta declarada que não existe nesta
máquina → `faltando` (o teste PULA a parte de mídia, com o motivo; nunca acha "em outro lugar").
"""

from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path
from unittest import mock

#: Onde mora a pasta de testes, nas duas máquinas (o SSD tem letra variável no Windows). Desde a
#: arrumação do SSD (2026-10-06) ela é `MIDIAS DE TESTES/3 CONJUNTOS DOS APPS/_CICLO ASSIST/conformar`, na raiz do SSD: achada
#: SUBINDO de pasta a partir daqui (vale para qualquer letra); a variável `DLPC_AMOSTRAS` vem antes de
#: tudo, e os lugares antigos ficam como reserva.
_SUBINDO = next((str(p / "MIDIAS DE TESTES" / "3 CONJUNTOS DOS APPS" / "_CICLO ASSIST" / "conformar") for p in Path(__file__).resolve().parents
                 if (p / "MIDIAS DE TESTES" / "3 CONJUNTOS DOS APPS" / "_CICLO ASSIST" / "conformar").is_dir()), None)
CANDIDATAS_AMOSTRAS = (os.environ.get("DLPC_AMOSTRAS"), _SUBINDO,
                       r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar",
                       r"D:\DeLaPraCa_MIDIAS E PROJETOS DE TESTE",
                       "/Volumes/SSD/DeLaPraCa_MIDIAS E PROJETOS DE TESTE")


def raiz_das_amostras() -> str:
    """A primeira candidata que existe nesta máquina; senão o lugar de sempre no Windows (o teste então
    PULA, mostrando o caminho que procurou)."""
    return next((c for c in CANDIDATAS_AMOSTRAS if c and os.path.isdir(c)),
                r"D:\MIDIAS DE TESTES\3 CONJUNTOS DOS APPS\_CICLO ASSIST\conformar")


def amostras() -> Path | None:
    for c in CANDIDATAS_AMOSTRAS:
        if c and os.path.isdir(c):
            return Path(c)
    return None


def no_disco(disco: str, caminho: str) -> Path | None:
    """`(rótulo do disco, caminho dentro dele)` → o caminho nesta máquina, ou None. Pelo RÓTULO, nas
    duas plataformas: no Mac `/Volumes/<rótulo>`, no Windows a letra de mesmo rótulo.

    ⛔ Medido 2026-10-04 (Windows): antes valia "a primeira letra onde o caminho existe". O PROJ-X_D
    (`E:`) tem uma CÓPIA de `PRODUCAO-B/PROJETOS`, então o `.prproj` do caso R03 era achado lá com o
    PRODB desplugado, e o teste falhava em vez de pular (o áudio só mora no PRODB)."""
    rel = caminho.replace("\\", "/").strip("/")
    if os.name == "nt":
        motor = str(Path(__file__).resolve().parent.parent / "motor")
        if motor not in sys.path:
            sys.path.insert(0, motor)
        from avb_bin.segmentos import _volumes_windows    # a mesma sonda de discos do motor
        for letra, rotulo in sorted(_volumes_windows().items()):
            p = Path(f"{letra}:/") / rel
            if rotulo and rotulo.casefold() == disco.casefold() and p.exists():
                return p
        return None
    p = Path("/Volumes") / disco / rel
    return p if p.exists() else None


def carregar(relativo: str) -> dict | None:
    """O `caso.json` de `03 CASOS/<relativo>`, com as pastas resolvidas nesta máquina. None se a
    pasta de testes não está aqui."""
    base = amostras()
    if base is None:
        return None
    pasta = base / "03 CASOS" / relativo
    arq = pasta / "caso.json"
    if not arq.is_file():
        raise FileNotFoundError(f"o caso {relativo} não tem caso.json (regra: todo caso declara as mídias)")
    c = json.loads(arq.read_text(encoding="utf-8"))
    c["pasta"] = pasta
    c["faltando"] = []
    for tipo in ("gerenciada", "arquivos"):
        achadas = []
        for d in (c.get("midia") or {}).get(tipo) or []:
            p = no_disco(d["disco"], d["caminho"])
            (achadas.append(p) if p else c["faltando"].append(f'{d["disco"]}:{d["caminho"]}'))
        c[f"raizes_{tipo}"] = achadas
    # Arquivos NOMEADOS do caso (o `.prproj`, um WAV de amostra): `{"nome": {"disco", "caminho"}}`.
    c["arquivo"] = {}
    for nome, d in (c.get("fontes") or {}).items():
        p = no_disco(d["disco"], d["caminho"])
        c["arquivo"][nome] = p
        if p is None:
            c["faltando"].append(f'{d["disco"]}:{d["caminho"]}')
    return c


@contextlib.contextmanager
def isolar_midia(caso: dict):
    """O receptor enxerga SÓ as pastas do caso: a gerenciada (as pastas numeradas declaradas, nada
    mais do `Avid MediaFiles`) e os arquivos (só dentro das pastas declaradas). Tudo o que vier de
    fora — outro projeto no mesmo disco, outro HD montado — some."""
    from avb_bin import segmentos
    from media import pmr

    numeradas = list(caso.get("raizes_gerenciada") or [])
    permitidas = [str(p) for p in numeradas + list(caso.get("raizes_arquivos") or [])]
    original = segmentos.caminho_confiavel

    def so_do_caso(c):
        seguro, motivo = original(c)
        if seguro and any(os.path.abspath(seguro).startswith(os.path.abspath(r) + os.sep) for r in permitidas):
            return seguro, motivo
        return None, "fora das pastas do caso (teste isolado)"

    with mock.patch.object(pmr, "raizes_de_midia", lambda: ["<caso>"] if numeradas else []), \
            mock.patch.object(pmr, "pastas_de_midia", lambda _raiz: (list(numeradas), [])), \
            mock.patch.object(segmentos, "caminho_confiavel", so_do_caso):
        yield
