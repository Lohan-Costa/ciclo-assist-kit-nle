"""A conferência pela referência: o conform provado pela IMAGEM, ponto a ponto.

Organograma aprovado pelo autor em 2026-10-04 (artifact "Conferência pela Referência"): depois do
Importar, o Resolve exporta o 1º e o último quadro VISÍVEIS de cada plano e cada um é comparado,
pela forma (não pela cor), com o mesmo quadro do vídeo de referência. Pode ser a última etapa do
Importar (escolhida antes de montar) ou um botão depois. Cancela-se a qualquer momento e continua
de onde parou: os JPEGs e os resultados ficam guardados por conferência.

Quem faz o quê:
- o serviço (aqui) guarda o plano (pontos, TC, referência), compara em SEGUNDO PLANO enquanto a
  casca já exporta o lote seguinte, e diz o andamento;
- a casca (`plugins/resolve/casca`) desliga a referência, exporta os quadros
  (`ExportCurrentFrameAsStill`, só na página Color), marca os pontos que não conferem e devolve
  trilhas, página e agulha como estavam;
- o painel conduz o laço, em lotes: o Cancelar responde entre um lote e outro.

A comparação é `motor/tools/conferir_conform.comparar_um` (memória "conferir-conform-pela-imagem").

A pasta (organograma de cache e logs, aprovado em 2026-10-05) é LEGÍVEL para quem a abre:

    <cache>/Conferências/<timeline> · AAAA-MM-DD HHhMM/
        conferencia.csv                              TC, trilha, plano, ponta, semelhança, confere
        NÃO CONFERE 01_02_52_17 V1 A058C005 início.jpg   (os que não conferem vêm primeiro)
        00_00_38_23 V1 A002C014 início.jpg            (os demais, pelo TC)
        _interno/   plano.json, resultados.json e o `<quadro>.jpg` que a casca acabou de gravar

A casca grava SÓ em `_interno/<quadro>.jpg` (a tranca dela, `imagemConfiavel`); comparado, o
quadro ganha o nome legível. Todos os JPEGs ficam depois de terminada (decisão 2: o teto do cache
cuida do espaço, e a conferência sai INTEIRA, `cache.unidades`).
"""

from __future__ import annotations

import csv
import json
import logging
import os
import queue
import re
import threading
import time
import uuid
from datetime import datetime

import cache
import plataforma

log = logging.getLogger(__name__)

RE_ID = re.compile(r"^[0-9a-f]{32}$")
#: A cor do marcador de "não confere" (autor, 2026-10-04: aprovou a sugestão de uma cor própria;
#: Purple não é usada por nenhum outro sinal). A API não grava palavra-chave em marcador: o
#: "DLPC" vai no nome, e o `customData` deixa a casca apagar só os nossos ao conferir de novo.
COR_MARCADOR = "Purple"
CSV = "conferencia.csv"
DADO_DO_MARCADOR = "dlpc-conferencia"


#: Um ponto usado há menos que isto é de uma conferência EM CURSO: o Limpar espera, o teto pula.
EM_USO_S = 180.0
INTERNO = "_interno"
#: Teto dos pedaços de nome (o caminho inteiro precisa caber nos 260 do Windows sem LongPaths).
_MAX_TIMELINE = 50
_MAX_PLANO = 40
_PONTA = {"entrada": "início", "saída": "fim", "saida": "fim"}


def pasta_raiz() -> str:
    return str(cache.sub(cache.CONFERENCIAS))


def _limpo(texto, maximo: int) -> str:
    """Um pedaço de nome de arquivo que vale no Windows e no macOS: sem `<>:"/|?*` nem controle,
    sem ponto/espaço no fim (o Windows os descarta calado)."""
    t = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "_", str(texto or "")).strip()
    t = re.sub(r"\s+", " ", t)[:maximo].rstrip(" .")
    return t or "sem nome"


def _livre(pasta: str, nome: str, ext: str = "") -> str:
    """`nome` + `ext` em `pasta`; se já existe, `nome (2)`, `(3)`…"""
    alvo, n = os.path.join(pasta, nome + ext), 2
    while os.path.exists(alvo):
        alvo = os.path.join(pasta, f"{nome} ({n}){ext}")
        n += 1
    return alvo


def _nome_do_quadro(p: dict, confere: bool) -> str:
    partes = [p["tc"].replace(":", "_").replace(";", "_"), f"V{p.get('trilha') or '?'}",
              _limpo(p.get("plano") or p.get("arquivo") or "", _MAX_PLANO),
              _PONTA.get(p.get("ponta") or "", p.get("ponta") or "ponto")]
    return ("" if confere else "NÃO CONFERE ") + " ".join(partes)


def _tc(q: int, nominal: int) -> str:
    s, f = divmod(max(0, int(q)), nominal)
    return f"{s // 3600:02d}:{s // 60 % 60:02d}:{s % 60:02d}:{f:02d}"


def _gravar(caminho: str, dado) -> None:
    tmp = f"{caminho}.{os.getpid()}.tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(dado, fh, ensure_ascii=False)
    os.replace(tmp, caminho)


class Conferencias:
    """As conferências desta máquina. Uma de cada vez compara (a fila é uma só)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._fila: queue.Queue = queue.Queue()
        self._resultados: dict[str, dict[str, dict]] = {}     # id → {quadro: resultado}
        self._planos: dict[str, dict] = {}
        self._pendentes: dict[str, int] = {}                  # id → quadros na fila
        self._pastas: dict[str, str] = {}                     # id → a pasta legível
        self._uso: dict[str, float] = {}                      # id → último uso (monotonic)
        threading.Thread(target=self._trabalhar, name="conferencia", daemon=True).start()

    # ── o plano ───────────────────────────────────────────────────────────────

    def criar(self, contexto: dict, timeline: str) -> dict:
        """O plano de uma timeline recém-montada (`prproj_para_drt._conferencia`) → `{id, pontos,
        segundos}`. Nada é exportado ainda: isso só começa quando o editor pede (ou já pediu)."""
        from tools.conferir_conform import SEGUNDOS_POR_PONTO

        cid = uuid.uuid4().hex
        rotulo = f"{_limpo(timeline, _MAX_TIMELINE)} · {datetime.now().strftime('%Y-%m-%d %Hh%M')}"
        pasta = _livre(pasta_raiz(), rotulo)
        os.makedirs(os.path.join(pasta, INTERNO), exist_ok=True)
        nominal = int(contexto.get("nominal") or round(contexto.get("fps") or 24))
        inicio = int(contexto.get("inicio") or 0)
        pontos = []
        for p in contexto.get("pontos") or []:
            q = int(p["quadro"])
            pontos.append({"quadro": q, "tc": _tc(inicio + q, nominal), "ponta": p.get("ponta"),
                           "plano": p.get("plano"), "trilha": p.get("trilha"),
                           "arquivo": p.get("arquivo")})
        plano = {"id": cid, "timeline": timeline, "referencia": contexto["referencia"],
                 "trilha_referencia": contexto.get("trilha_referencia"),
                 "ref_na_timeline": int(contexto.get("ref_na_timeline") or 0),
                 "ref_entrada": int(contexto.get("ref_entrada") or 0),
                 "ref_fps": float(contexto.get("ref_fps") or contexto.get("fps") or 24),
                 "quadro_px": contexto.get("quadro_px") or [1920, 1080], "pontos": pontos}
        _gravar(os.path.join(pasta, INTERNO, "plano.json"), plano)
        with self._lock:
            self._planos[cid] = plano
            self._pastas[cid] = pasta
            self._resultados[cid] = {}
            self._uso[cid] = time.monotonic()
        return {"id": cid, "pontos": len(pontos), "segundos": round(len(pontos) * SEGUNDOS_POR_PONTO)}

    def _achar(self, cid: str) -> str | None:
        """A pasta legível de uma conferência que não está na memória (o serviço reiniciou): a
        que tem `_interno/plano.json` com este id."""
        raiz = pasta_raiz()
        try:
            nomes = os.listdir(raiz)
        except OSError:
            return None
        for nome in nomes:
            plano = os.path.join(raiz, nome, INTERNO, "plano.json")
            try:
                with open(plano, encoding="utf-8") as fh:
                    if json.load(fh).get("id") == cid:
                        return os.path.join(raiz, nome)
            except (OSError, ValueError, AttributeError):
                continue
        return None

    def _plano(self, cid: str) -> dict:
        if not RE_ID.match(cid or ""):
            raise ValueError("conferência inválida")
        with self._lock:
            if cid in self._planos and os.path.isdir(self._pastas.get(cid, "")):
                self._uso[cid] = time.monotonic()
                return self._planos[cid]
        pasta = self._achar(cid)
        if not pasta:
            # o Limpar ou o teto do cache a levaram
            with self._lock:
                self._planos.pop(cid, None)
                self._pastas.pop(cid, None)
            raise LookupError("essa conferência não está mais nesta máquina — monte de novo")
        interno = os.path.join(pasta, INTERNO)
        try:
            with open(os.path.join(interno, "plano.json"), encoding="utf-8") as fh:
                plano = json.load(fh)
        except (OSError, ValueError):
            raise LookupError("essa conferência não está mais nesta máquina — monte de novo") from None
        try:
            with open(os.path.join(interno, "resultados.json"), encoding="utf-8") as fh:
                res = json.load(fh)
        except (OSError, ValueError):
            res = {}
        with self._lock:
            self._planos[cid] = plano
            self._pastas[cid] = pasta
            self._resultados[cid] = res if isinstance(res, dict) else {}
            self._uso[cid] = time.monotonic()
        return plano

    def pasta(self, cid: str) -> str:
        """A pasta legível (para o "Abrir a pasta desta conferência")."""
        self._plano(cid)
        with self._lock:
            return self._pastas[cid]

    def em_uso(self) -> list[str]:
        """As pastas das conferências em curso (fila não vazia, ou usadas há pouco): o Limpar
        espera por elas e o teto do cache as pula."""
        agora = time.monotonic()
        with self._lock:
            return [self._pastas[c] for c in self._pastas
                    if self._pendentes.get(c, 0) or agora - self._uso.get(c, 0) < EM_USO_S]

    # ── começar / continuar ───────────────────────────────────────────────────

    def iniciar(self, cid: str, do_comeco: bool = False) -> dict:
        """Os pontos que FALTAM, com o caminho do JPEG de cada um (a casca só grava ali).
        `do_comeco` apaga os resultados e os quadros de antes."""
        plano = self._plano(cid)
        pasta = self.pasta(cid)
        interno = os.path.join(pasta, INTERNO)
        cache.tocar(pasta)
        if do_comeco:
            with self._lock:
                self._resultados[cid] = {}
            for d in (pasta, interno):
                for nome in os.listdir(d):
                    if nome.endswith(".jpg") or nome in ("resultados.json", CSV):
                        try:
                            os.remove(os.path.join(d, nome))
                        except OSError:
                            pass
        with self._lock:
            feitos = set(self._resultados.get(cid, {}))
        faltam = [{"quadro": p["quadro"], "tc": p["tc"], "plano": p.get("plano"),
                   "trilha": p.get("trilha"), "ponta": p.get("ponta"),
                   "imagem": os.path.join(interno, f"{p['quadro']}.jpg")}
                  for p in plano["pontos"] if str(p["quadro"]) not in feitos]
        return {"id": cid, "timeline": plano["timeline"], "total": len(plano["pontos"]),
                "trilha_referencia": plano.get("trilha_referencia"), "faltam": faltam,
                "pasta": pasta, **self._placar(cid)}

    # ── comparar (em segundo plano) ───────────────────────────────────────────

    def comparar(self, cid: str, quadros: list) -> int:
        """Põe na fila os pontos cujo JPEG a casca acabou de gravar. Volta na hora."""
        plano = self._plano(cid)
        validos = {p["quadro"] for p in plano["pontos"]}
        n = 0
        for q in quadros or []:
            try:
                q = int(q)
            except (TypeError, ValueError):
                continue
            if q in validos:
                with self._lock:
                    self._pendentes[cid] = self._pendentes.get(cid, 0) + 1
                self._fila.put((cid, q))
                n += 1
        return n

    def _trabalhar(self) -> None:
        from tools.conferir_conform import comparar_um

        while True:
            cid, q = self._fila.get()
            pasta = plano = None
            try:
                plano = self._plano(cid)
                pasta = self.pasta(cid)
                img = os.path.join(pasta, INTERNO, f"{q}.jpg")
                if os.path.isfile(img):
                    ref_q = plano["ref_entrada"] + (q - plano["ref_na_timeline"])
                    r = comparar_um(img, plano["referencia"], ref_q, plano["ref_fps"],
                                    quadro_px=tuple(plano.get("quadro_px") or (1920, 1080)))
                    self._batizar(plano, pasta, q, img, r)
                else:
                    # dois pontos no MESMO quadro (trilhas diferentes, R04 22:08 V3/V4 na cópia do Premiere): o 1º já
                    # comparou e batizou o arquivo; o 2º não o acha e rebaixava o resultado bom a erro (2026-10-29)
                    with self._lock:
                        antes = (self._resultados.get(cid) or {}).get(str(q))
                    r = antes if antes and not antes.get("erro") else {"erro": "o programa não exportou o quadro"}
            except Exception as e:                       # um ponto nunca derruba a fila
                log.warning("conferência %s, quadro %s: %s", cid, q, e)
                r = {"erro": str(e)[:200]}
            with self._lock:
                self._resultados.setdefault(cid, {})[str(q)] = r
                self._pendentes[cid] = max(0, self._pendentes.get(cid, 1) - 1)
                fim = self._pendentes[cid] == 0
                copia = dict(self._resultados[cid])
            if pasta and plano and (fim or len(copia) % 25 == 0):
                try:
                    _gravar(os.path.join(pasta, INTERNO, "resultados.json"), copia)
                    self._planilha(plano, pasta, copia)
                except OSError as e:
                    log.warning("conferência %s: não gravou os resultados (%s)", cid, e)
            if fim:
                cache.talvez_aplicar_teto(protegidos=self.em_uso())

    def _batizar(self, plano: dict, pasta: str, q: int, img: str, r: dict) -> None:
        """O quadro comparado sai de `_interno/` com o nome legível. Se não der (o Explorer com o
        arquivo aberto), fica onde está: o nome é cortesia, o resultado já existe."""
        from tools.conferir_conform import LIMIAR

        p = next((x for x in plano["pontos"] if x["quadro"] == q), None)
        if p is None:
            return
        confere = not r.get("erro") and r.get("corr", 1.0) >= LIMIAR
        try:
            destino = _livre(pasta, _nome_do_quadro(p, confere), ".jpg")
            os.replace(img, destino)
            r["imagem"] = os.path.basename(destino)
        except OSError as e:
            log.info("conferência: o quadro %s ficou em _interno (%s)", q, e)

    def _planilha(self, plano: dict, pasta: str, res: dict) -> None:
        """`conferencia.csv` ao lado dos JPEGs (decisão 3; o relatório vem depois). `;` e vírgula
        decimal, com BOM: é como o Excel em português abre sem perguntar."""
        from tools.conferir_conform import LIMIAR

        tmp = os.path.join(pasta, f"{CSV}.{os.getpid()}.tmp")
        with open(tmp, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh, delimiter=";")
            w.writerow(["TC", "trilha", "plano", "ponta", "semelhança", "confere", "imagem"])
            for p in plano["pontos"]:
                r = res.get(str(p["quadro"]))
                if not r:
                    continue
                if r.get("erro"):
                    sem, conf = "", f"erro: {r['erro']}"
                else:
                    sem = f"{r.get('corr', 0):.3f}".replace(".", ",")
                    conf = "sim" if r.get("corr", 1.0) >= LIMIAR else "não"
                w.writerow([p["tc"], f"V{p.get('trilha') or '?'}",
                            p.get("plano") or p.get("arquivo") or "",
                            _PONTA.get(p.get("ponta") or "", p.get("ponta") or ""), sem, conf,
                            r.get("imagem") or ""])
        os.replace(tmp, os.path.join(pasta, CSV))

    # ── o andamento e o resultado ─────────────────────────────────────────────

    def _placar(self, cid: str) -> dict:
        from tools.conferir_conform import LIMIAR

        with self._lock:
            res = dict(self._resultados.get(cid, {}))
            na_fila = self._pendentes.get(cid, 0)
        ruins = {k: v for k, v in res.items() if v.get("erro") or (v.get("corr", 1.0) < LIMIAR)}
        return {"comparados": len(res), "na_fila": na_fila, "conferem": len(res) - len(ruins),
                "nao_conferem": len(ruins)}

    def estado(self, cid: str) -> dict:
        plano = self._plano(cid)
        return {"id": cid, "total": len(plano["pontos"]), **self._placar(cid)}

    def marcas(self, cid: str) -> dict:
        """Os marcadores dos pontos que não conferem (quadro desde o início da timeline), para a
        casca. Um ponto sem resultado (cancelado antes) não vira marcador."""
        from tools.conferir_conform import LIMIAR

        plano = self._plano(cid)
        with self._lock:
            res = dict(self._resultados.get(cid, {}))
        fora = []
        for p in plano["pontos"]:
            r = res.get(str(p["quadro"]))
            if not r:
                continue
            trk = f"Trk V{p.get('trilha')}"
            quem = p.get("plano") or p.get("arquivo") or ""
            if r.get("erro"):
                tipo, nota = "Não deu para conferir", r["erro"]
            elif r.get("corr", 1.0) < LIMIAR:
                desloca = (r.get("dx_px") or r.get("dy_px")) and r.get("corr_deslocada", 0) >= LIMIAR
                tipo = "Enquadramento diferente da referência" if desloca else "Não confere com a referência"
                nota = f"semelhança {r['corr']:.2f}".replace(".", ",")
                if desloca:
                    nota += f"; deslocada {r['dx_px']}×{r['dy_px']} px confere ({r['corr_deslocada']:.2f})".replace(".", ",")
            else:
                continue
            # NOME = o tipo; NOTES = as observações (autor, 2026-10-04)
            fora.append({"quadro": p["quadro"], "tc": p["tc"], "nome": tipo,
                         "nota": f"{trk} · {quem} · {p.get('ponta') or 'ponto'} em {p['tc']} · {nota}"})
        return {"cor": COR_MARCADOR, "dado": DADO_DO_MARCADOR, "marcas": fora,
                "trilha_referencia": plano.get("trilha_referencia")}

    def apagar(self, cid: str) -> None:
        """Apaga uma conferência inteira."""
        pasta = self.pasta(cid)
        try:
            plataforma.apagar_arvore(pasta)
        except OSError as e:
            log.info("conferência %s: não apaguei tudo (%s)", cid, e)
        with self._lock:
            self._planos.pop(cid, None)
            self._pastas.pop(cid, None)
            self._resultados.pop(cid, None)


_UNICA: Conferencias | None = None


def conferencias() -> Conferencias:
    global _UNICA
    if _UNICA is None:
        _UNICA = Conferencias()
    return _UNICA
