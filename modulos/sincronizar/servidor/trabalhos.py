"""O estado ao vivo do Sincronizar: os TRABALHOS (jobs), a fila do painel e as montagens pedidas pela ponte.

Porte das partes de estado do `httpserver.rs` do Órbita (`d57904e`). Três coisas, cada uma com o seu porquê:

- **Trabalho (job):** sincronizar 50 clipes leva minutos; sem estado o painel fica num "Sincronizando…" mudo. Roda
  numa thread, o painel pergunta em `/prproj/status?id=`. ⭐ UM por vez: `reservar` devolve 409 com o id do outro
  (antes disso o usuário empilhou 6 syncs seguidos, 2026-08-04). O `waiting` separa "esperando a vez" de "travado".
  ⚠️ A poda conta do FIM (`terminado`), nunca do início: um sync de dez minutos nasceria vencido.
- **A fila do painel (`/nlejob`):** o trabalho que o app deixa para o painel do NLE buscar (montar a sequência). Quem
  bate ali marca presença (`ouvindo`) — é o que o Assist confere antes do cartão.
- **Montagens:** o pedido de montar que veio pela `/api/v1` não tem janela para olhar; o resultado fica guardado
  10 min para quem pediu perguntar (`/api/v1/montagem?id=`).
"""
from __future__ import annotations

import itertools
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

#: Resultado de job terminado é podado depois disto (do fim, não do início).
JOB_TTL = 120.0
#: O painel que bateu há menos que isto está "ouvindo".
NLE_LISTEN_TTL = 15.0
MONTAGEM_TTL = 600.0

#: O contador dos ids (`job_…`, `ponte-…`) — um só, como o `JOB_COUNTER` do Rust.
_contador = itertools.count()


def _agora_ms() -> int:
    return int(time.time() * 1000)


def proximo_numero() -> int:
    return next(_contador)


class Ocupado(Exception):
    def __init__(self, outro: str):
        super().__init__("ocupado")
        self.outro = outro


@dataclass
class Job:
    stage: str
    fraction: float = 0.0
    done: bool = False
    started_ms: int = field(default_factory=_agora_ms)
    terminado: Optional[float] = None
    result: Any = None
    error: Optional[str] = None
    waiting: bool = True


_jobs: dict[str, Job] = {}
_jobs_trava = threading.Lock()


def _zerar() -> None:
    with _jobs_trava:
        _jobs.clear()
    with _nle_trava:
        _pendentes.clear()
        _ultimo_poll.clear()
    with _mont_trava:
        _montagens.clear()


def em_curso() -> Optional[str]:
    with _jobs_trava:
        for i, j in _jobs.items():
            if not j.done:
                return i
    return None


def reservar(stage: str) -> str:
    """Reserva o lugar do próximo job, ou `Ocupado(outro)`. Checar e inserir sob a MESMA trava: duas requisições
    simultâneas não podem passar as duas pela checagem (o servidor do Rust tinha uma thread; este tem várias)."""
    with _jobs_trava:
        for i, j in _jobs.items():
            if not j.done:
                raise Ocupado(i)
        agora = time.monotonic()
        for i in [i for i, j in _jobs.items() if j.terminado is not None and agora - j.terminado >= JOB_TTL]:
            del _jobs[i]
        jid = f"job_{_agora_ms()}_{proximo_numero()}"
        _jobs[jid] = Job(stage=stage)
        return jid


def obter(jid: str) -> Optional[Job]:
    with _jobs_trava:
        j = _jobs.get(jid)
        return None if j is None else Job(**j.__dict__)


def etapa(jid: str, fracao: float, stage: str) -> None:
    with _jobs_trava:
        j = _jobs.get(jid)
        if j:
            j.fraction, j.stage, j.waiting = fracao, stage, False


def terminou_bem(jid: str, resultado: Any) -> None:
    with _jobs_trava:
        j = _jobs.get(jid)
        if j:
            j.fraction, j.stage, j.done, j.waiting = 1.0, "concluído", True, False
            j.terminado, j.result = time.monotonic(), resultado


def terminou_mal(jid: str, erro: str) -> None:
    with _jobs_trava:
        j = _jobs.get(jid)
        if j:
            j.done, j.waiting, j.terminado, j.error = True, False, time.monotonic(), erro


def sink_na_faixa(jid: str, lo: float, hi: float) -> Callable[[Any], None]:
    """O progresso do motor (`kind: status`, com `overall` ou `current/total`) na faixa [lo, hi] do job."""
    teto = hi - lo

    def sink(data: Any) -> None:
        if not isinstance(data, dict) or data.get("kind") != "status":
            return
        overall = data.get("overall")
        cur = data.get("current") or 0
        tot = data.get("total") or 0
        msg = data.get("message") or ""
        with _jobs_trava:
            j = _jobs.get(jid)
            if not j:
                return
            j.waiting = False
            if isinstance(overall, (int, float)):
                j.fraction = lo + min(max(float(overall) * teto, 0.0), teto)
            elif isinstance(tot, (int, float)) and tot > 0:
                j.fraction = lo + min(max(float(cur) / float(tot) * teto, 0.0), teto)
            if msg:
                j.stage = str(msg)
    return sink


def status(jid: str) -> Optional[dict]:
    j = obter(jid)
    if j is None:
        return None
    state = "error" if j.error is not None else "done" if j.done else "waiting" if j.waiting else "running"
    return {"state": state, "fraction": j.fraction, "stage": j.stage,
            "elapsed_ms": max(0, _agora_ms() - j.started_ms), "result": j.result, "error": j.error}


def rodar_no_fundo(jid: str, trabalho: Callable[[], Any]) -> None:
    """O trabalho numa thread; o que ele devolver é o resultado, o que levantar é o erro (com a mensagem dele se for
    erro do motor ou nosso — `ValueError`/`RuntimeError` —, "erro interno" no resto, como o `catch_unwind`)."""
    from motor import ErroDoMotor

    def corpo() -> None:
        try:
            terminou_bem(jid, trabalho())
        except (ErroDoMotor, ValueError, RuntimeError) as e:
            terminou_mal(jid, str(e))
        except Exception:
            import logging
            logging.getLogger("sincronizar").exception("pânico no job %s", jid)
            terminou_mal(jid, "erro interno")

    threading.Thread(target=corpo, name=f"job-{jid}", daemon=True).start()


# ── a fila do painel do NLE ───────────────────────────────────────────────────────────────────────────────────────

_pendentes: list[dict] = []
_ultimo_poll: dict[str, float] = {}
_nle_trava = threading.Lock()


def nle_de(v: Any) -> str:
    return v if v in ("resolve", "avid") else "premiere"


def enfileirar_nle(jobs: list[dict], alvo: str) -> int:
    alvo = nle_de(alvo)
    with _nle_trava:
        for j in jobs:
            j["nle"] = alvo
            _pendentes.append(j)
    return len(jobs)


def ouvindo(alvo: str) -> bool:
    with _nle_trava:
        t = _ultimo_poll.get(nle_de(alvo))
        return t is not None and time.monotonic() - t < NLE_LISTEN_TTL


def marcar_presenca(alvo: str) -> None:
    with _nle_trava:
        _ultimo_poll[nle_de(alvo)] = time.monotonic()


def pegar_job(alvo: str) -> Optional[dict]:
    alvo = nle_de(alvo)
    with _nle_trava:
        _ultimo_poll[alvo] = time.monotonic()
        job = None
        for i, j in enumerate(_pendentes):
            if nle_de(j.get("nle")) == alvo:
                job = _pendentes.pop(i)
                break
    if job is not None and isinstance(job.get("id"), str):
        montagem_pega(job["id"])
    return job


# ── as montagens pedidas pela ponte ─────────────────────────────────────────────────────────────────────────────

@dataclass
class Montagem:
    nle: str
    nome: str
    estado: str = "na_fila"
    resumo: str = ""
    terminada: Optional[float] = None


_montagens: dict[str, Montagem] = {}
_mont_trava = threading.Lock()


def registrar_montagem(mid: str, nle: str, nome: str) -> None:
    with _mont_trava:
        agora = time.monotonic()
        for k in [k for k, v in _montagens.items() if v.terminada is not None and agora - v.terminada >= MONTAGEM_TTL]:
            del _montagens[k]
        _montagens[mid] = Montagem(nle=nle, nome=nome)


def montagem_pega(mid: str) -> None:
    with _mont_trava:
        v = _montagens.get(mid)
        if v and v.estado == "na_fila":
            v.estado = "montando"


def montagem_terminou(mid: str, ok: bool, resumo: str) -> None:
    with _mont_trava:
        v = _montagens.get(mid)
        if v:
            v.estado, v.resumo, v.terminada = ("feito" if ok else "erro"), resumo, time.monotonic()


def montagem(mid: str) -> Optional[dict]:
    with _mont_trava:
        v = _montagens.get(mid)
        return None if v is None else {"estado": v.estado, "nome": v.nome, "nle": v.nle, "resumo": v.resumo}
