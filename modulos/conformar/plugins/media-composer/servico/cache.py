"""O cache do De Lá Pra Cá: onde fica, quanto ocupa, e o teto.

Organograma aprovado pelo autor em 2026-10-05 (https://claude.ai/artifact/AJCgkALZDYsuTkabstuThd),
desenho do Órbita (`DRAMASYNC/src-python/media/cachedir.py`). Três lugares, cada um com uma regra:

- **Dados** (`plataforma.pasta_dados`): o que o app NÃO refaz — código de cores, canais, PARTIDAS
  (o Atualizar compara com elas), token. O app nunca apaga.
- **Cache** (aqui): o que o app refaz sozinho — `Conferências/`, as timelines geradas
  (`recebidos/`) e as bins de trabalho (`trabalho/`). Apagar custa tempo, nunca trabalho.
- **Logs** (`plataforma.pasta_logs`, `registro.py`): um arquivo com rotação.

Regras (organograma):
- limpar e o teto só mexem nas SUBPASTAS do app (`SUBPASTAS`): se o editor apontar o cache para
  uma pasta com coisas dele, nada delas é tocado;
- trocar o local não move nada: o novo começa vazio (o painel bloqueia o Limpar até salvar);
- nada se limpa no meio de um Importar ou de uma conferência (quem chama confere, `rotas`);
- o teto é LRU POR UNIDADE: uma conferência sai inteira (metade dela não serve para continuar),
  um DRT sai com o seu `.midias.json`; "usado" = a data mais nova dentro da unidade, e `tocar`
  a renova na leitura (sem isso o mais antigo seria o mais antigo a ser ESCRITO);
- o motor só abre pastas pelo NOME (`pasta_conhecida`), nunca um caminho que venha de fora.

Nada aqui derruba o serviço: arquivo em uso é pulado. Cache é otimização, não requisito.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

import configuracoes
import plataforma

log = logging.getLogger("delapraca.cache")

CONFERENCIAS = "Conferências"
RECEBIDOS = "recebidos"
TRABALHO = "trabalho"
#: As subpastas que o app gerencia. `limpar`, o teto e o uso só olham para ELAS.
SUBPASTAS = (CONFERENCIAS, RECEBIDOS, TRABALHO)
#: O que ficou na pasta de DADOS, das versões até 0.1.76 (decisão 5: não migrar; avisar e oferecer
#: apagar). `partidas/` NÃO está aqui: é dado, e fica.
ANTIGAS = ("conferencia", "recebidos", "trabalho")

_INTERVALO_TETO_S = 30.0
_ultimo_teto = 0.0
_trava = threading.Lock()
_avisados: set[str] = set()


# ── onde ────────────────────────────────────────────────────────────────────────

def _escolhida() -> Path | None:
    c = configuracoes.ler().get("cache_dir")
    return Path(c) if c else None


def indisponivel() -> bool:
    """O local escolhido está num disco que não está aqui (desmontado, outra máquina)?"""
    c = _escolhida()
    return bool(c) and not Path(c.anchor).exists()


def raiz() -> Path:
    """A raiz efetiva: a escolhida pelo editor ou a padrão do sistema.

    ⚠️ Escolhida num disco que não está montado → a padrão, com aviso no log e no painel: o
    Importar não pode parar porque o HD do cache ficou em casa. ⚠️ A casca do Resolve repete esta
    regra (`main.js › pastaCache`)."""
    c = _escolhida()
    if c and not indisponivel():
        return c
    if c and str(c) not in _avisados:
        _avisados.add(str(c))                    # uma vez por local: `raiz()` é chamada a toda hora
        log.warning("o cache escolhido (%s) não está acessível: usando o padrão", c)
    return plataforma.pasta_cache_padrao()


def sub(nome: str) -> Path:
    """Uma subpasta do app, já criada."""
    if nome not in SUBPASTAS:
        raise ValueError(f"subpasta desconhecida: {nome}")
    p = raiz() / nome
    p.mkdir(parents=True, exist_ok=True)
    return p


# ── o que há dentro ─────────────────────────────────────────────────────────────

def _tamanho_da_pasta(pasta: Path) -> tuple[int, float, int]:
    """(bytes, mtime mais novo, arquivos) de uma pasta inteira. Nunca levanta."""
    total, novo, n = 0, 0.0, 0
    try:
        novo = pasta.stat().st_mtime
    except OSError:
        pass
    for dirpath, _dirs, arquivos in os.walk(pasta):
        for a in arquivos:
            try:
                st = os.stat(os.path.join(dirpath, a))
            except OSError:
                continue
            total += st.st_size
            novo = max(novo, st.st_mtime)
            n += 1
    return total, novo, n


def _irmaos(arquivo: Path) -> str:
    """A chave da unidade de um arquivo de `recebidos/`: `<uuid>.drt`, `<uuid>.midias.json` e
    `<uuid>.nova.json` saem juntos."""
    return arquivo.name.split(".", 1)[0]


def unidades(base: Path | None = None) -> list[dict]:
    """O que o teto e o Limpar consideram, uma entrada por unidade:
    `{caminhos: [Path], bytes, usado (mtime), arquivos}`. Nunca levanta."""
    base = base or raiz()
    fora: list[dict] = []
    conf = base / CONFERENCIAS
    try:
        filhos = list(os.scandir(conf))
    except OSError:
        filhos = []
    for e in filhos:
        p = Path(e.path)
        try:
            if e.is_dir():
                b, m, n = _tamanho_da_pasta(p)
            else:
                st = e.stat()
                b, m, n = st.st_size, st.st_mtime, 1
        except OSError:
            continue
        fora.append({"caminhos": [p], "bytes": b, "usado": m, "arquivos": n})
    for nome in (RECEBIDOS, TRABALHO):
        grupos: dict[str, dict] = {}
        try:
            filhos = list(os.scandir(base / nome))
        except OSError:
            continue
        for e in filhos:
            p = Path(e.path)
            try:
                if e.is_dir():
                    b, m, n = _tamanho_da_pasta(p)
                else:
                    st = e.stat()
                    b, m, n = st.st_size, st.st_mtime, 1
            except OSError:
                continue
            chave = f"{nome}/{_irmaos(p) if nome == RECEBIDOS else p.name}"
            g = grupos.setdefault(chave, {"caminhos": [], "bytes": 0, "usado": 0.0, "arquivos": 0})
            g["caminhos"].append(p)
            g["bytes"] += b
            g["usado"] = max(g["usado"], m)
            g["arquivos"] += n
        fora.extend(grupos.values())
    return fora


def estatisticas() -> dict:
    """O que as telas mostram: onde, quanto, e o teto."""
    cfg = configuracoes.ler()
    us = unidades()
    return {
        "dir": str(raiz()),
        "padrao": str(plataforma.pasta_cache_padrao()),
        "escolhida": cfg.get("cache_dir"),
        "indisponivel": indisponivel(),
        "bytes": sum(u["bytes"] for u in us),
        "arquivos": sum(u["arquivos"] for u in us),
        "max_gb": cfg["cache_max_gb"],
        "logs": str(plataforma.pasta_logs()),
    }


def tocar(caminho) -> None:
    """Marca como usado agora — é o que torna o teto um LRU de verdade."""
    try:
        os.utime(caminho, None)
    except OSError:
        pass


# ── apagar ──────────────────────────────────────────────────────────────────────

def _apagar(u: dict) -> bool:
    ok = True
    for p in u["caminhos"]:
        try:
            if p.is_dir():
                plataforma.apagar_arvore(p)
            else:
                plataforma.apagar_arquivo(p)
        except FileNotFoundError:
            continue
        except OSError as e:                 # em uso (o Resolve lendo o DRT, o Explorer aberto)
            log.info("cache: não apaguei %s (%s)", p, e)
            ok = False
    return ok


def _protegida(u: dict, protegidos) -> bool:
    prot = {os.path.normcase(os.path.abspath(p)) for p in protegidos or ()}
    return any(os.path.normcase(os.path.abspath(p)) in prot for p in u["caminhos"])


def limpar(protegidos=()) -> dict:
    """Apaga tudo o que o app gerencia (menos `protegidos`). Devolve o que foi liberado."""
    livres = arquivos = 0
    with _trava:
        for u in unidades():
            if _protegida(u, protegidos):
                continue
            if _apagar(u):
                livres += u["bytes"]
                arquivos += u["arquivos"]
    log.info("cache limpo: %d arquivo(s), %.1f MB", arquivos, livres / 1e6)
    return {"bytes": livres, "arquivos": arquivos}


def aplicar_teto(max_bytes: int | None = None, protegidos=()) -> dict:
    """Despeja as unidades usadas há mais tempo até o cache caber no teto."""
    if max_bytes is None:
        max_bytes = int(configuracoes.ler()["cache_max_gb"]) * 1024 ** 3
    livres = arquivos = 0
    with _trava:
        us = unidades()
        total = sum(u["bytes"] for u in us)
        if total <= max_bytes:
            return {"bytes": 0, "arquivos": 0}
        for u in sorted(us, key=lambda u: u["usado"]):
            if total - livres <= max_bytes:
                break
            if _protegida(u, protegidos):
                continue
            if _apagar(u):
                livres += u["bytes"]
                arquivos += u["arquivos"]
    if arquivos:
        log.info("cache acima do teto: %d arquivo(s) usados há mais tempo saíram (%.1f MB)",
                 arquivos, livres / 1e6)
    return {"bytes": livres, "arquivos": arquivos}


def talvez_aplicar_teto(protegidos=()) -> None:
    """Depois de cada escrita grande (DRT, conferência), com rédea curta: varrer a cada quadro
    seria pagar I/O para economizar disco. Nunca levanta."""
    global _ultimo_teto
    agora = time.monotonic()
    if agora - _ultimo_teto < _INTERVALO_TETO_S:
        return
    _ultimo_teto = agora
    try:
        aplicar_teto(protegidos=protegidos)
    except Exception:  # noqa: BLE001 — o teto é acessório
        log.debug("teto do cache falhou", exc_info=True)


# ── o cache do lugar antigo (decisão 5: avisar e oferecer apagar) ─────────────────

def _antigas() -> list[Path]:
    dados = plataforma.pasta_dados()
    atual = {os.path.normcase(os.path.abspath(raiz() / s)) for s in SUBPASTAS}
    return [dados / n for n in ANTIGAS
            if (dados / n).is_dir() and os.path.normcase(os.path.abspath(dados / n)) not in atual]


def antigo() -> dict | None:
    """O que sobrou na pasta de dados das versões anteriores, ou `None` se nada (ou dispensado)."""
    if configuracoes.ler().get("cache_antigo_dispensado"):
        return None
    total = n = 0
    pastas = []
    for p in _antigas():
        b, _m, k = _tamanho_da_pasta(p)
        if k:
            total += b
            n += k
            pastas.append(str(p))
    return {"bytes": total, "arquivos": n, "pastas": pastas} if n else None


def apagar_antigo() -> dict:
    total = n = 0
    for p in _antigas():
        b, _m, k = _tamanho_da_pasta(p)
        try:
            plataforma.apagar_arvore(p)
        except OSError as e:
            log.info("cache antigo: não apaguei tudo em %s (%s)", p, e)
        if not p.exists():
            total += b
            n += k
    log.info("cache antigo apagado: %d arquivo(s), %.1f MB", n, total / 1e6)
    return {"bytes": total, "arquivos": n}


# ── abrir pastas pelo NOME ────────────────────────────────────────────────────────

def pasta_conhecida(qual: str) -> Path:
    """`cache` ou `logs` → a pasta (criada). Qualquer outro nome levanta: o painel nunca manda
    caminho, e o motor nunca abre um que venha de fora (a trava do Órbita, `/folder/open`)."""
    if qual == "cache":
        p = raiz()
    elif qual == "logs":
        p = plataforma.pasta_logs()
    else:
        raise ValueError("pasta desconhecida")
    p.mkdir(parents=True, exist_ok=True)
    return p
