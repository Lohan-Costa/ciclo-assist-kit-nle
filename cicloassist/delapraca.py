"""A ponte com o De Lá Pra Cá: levar uma timeline de um NLE a outro, pelo serviço dele.

⭐⭐ **O Ciclo Assist orquestra; o De Lá Pra Cá processa** — o mesmo desenho da ponte com o
Sincronizar (`sincronizar.py`). Decisão do autor (2026-10-29): *"o DLPC precisa operar exatamente como
o Sincronizar; o Ciclo Assist deve saber que ele tem as ferramentas à disposição e que é para
usá-las"*. O editor arrasta o projeto, o vídeo de referência e a pasta das mídias para o
chat, e a conversa leva a timeline ao Resolve.

⭐ **A sequência de chamadas é a da bancada do DLPC** (`_DeLaPraCa/tools/bancada_resolve/
e2e_prproj.py`, o "gêmeo HTTP" do painel, que levou o R04 ao Resolve 19 com 144/144 pela
referência): abrir → analisar com as pastas → preparar o `.drt` → mídias no Resolve →
importar → Fusion, LUTs e compostos → conferir pela referência. Montar por conta própria
seria a segunda implementação do que o DLPC já mede; aqui só se chama, na ordem dele.

⚠️⚠️ **Os cabeçalhos são os da página do painel.** O porteiro do DLPC (`api/portao.py`) barra
o NAVEGADOR — `Origin` e `Sec-Fetch-Site` são cabeçalhos que página nenhuma forja — e diz com
todas as letras que processo local nenhum é barrado por ele. Esta ponte é um processo local
do mesmo usuário, como a bancada. É TRANSIÇÃO: na importação do DLPC para dentro do Ciclo
Assist (`docs/plano/2026-10-21-assist-standalone.md`) a chamada vira função, sem HTTP.

⚠️ O DLPC **não abre o Resolve**: precisa do Studio aberto, com um projeto, e do servidor de
scripts no ar. `/resolve/projeto` responde isso em ~0,1 s quando está tudo de pé, e em ~4 s
(uma vez) quando não está — o próprio DLPC guarda a falha e responde na hora depois.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Callable

URL = "http://127.0.0.1:7823"

#: Uma pergunta rápida (saúde, projeto do Resolve).
PRAZO_S = 15.0

#: Analisar e preparar leem a mídia inteira (MEDIDO no R04: segundos a minutos); o teto é
#: o da bancada, que já rodou 80 planos e 48 arquivos dentro dele.
PRAZO_LONGO_S = 60 * 30

#: A conferência pela referência vai em lotes de pontos (o roteiro do `conferir()` do painel).
LOTE_DA_CONFERENCIA = 6

_CABECALHOS = {"Origin": URL, "Sec-Fetch-Site": "same-origin", "Content-Type": "application/json"}


class DelaPracaIndisponivel(RuntimeError):
    """O serviço do De Lá Pra Cá não respondeu."""


class DelaPracaFalhou(RuntimeError):
    """Respondeu, mas recusou ou falhou — a frase é DELE e vai inteira.

    `frase` é só a frase dele, sem a rota e o código HTTP: é o que a JANELA mostra ao editor
    (formulário da receita, 2026-11-02 — o `Untitled.prproj` sem sequência saía como
    "recusou /receber/abrir (HTTP 400): …"). O log e o modelo continuam com a mensagem inteira."""

    def __init__(self, mensagem: str, frase: str = "") -> None:
        super().__init__(mensagem)
        self.frase = frase or mensagem


def pedir(caminho: str, corpo: dict | None = None, prazo: float = PRAZO_S) -> dict[str, Any]:
    """Uma chamada ao serviço do DLPC. Stdlib — regra da casa."""
    dados = json.dumps(corpo or {}).encode("utf-8")
    pedido = urllib.request.Request(URL + caminho, data=dados, headers=_CABECALHOS, method="POST")
    try:
        with urllib.request.urlopen(pedido, timeout=prazo) as r:
            bruto = r.read()
    except urllib.error.HTTPError as e:
        detalhe = ""
        try:
            corpo_erro = json.loads(e.read().decode("utf-8", "replace") or "{}")
            detalhe = str(corpo_erro.get("erro") or corpo_erro.get("error") or "")
        except Exception:  # noqa: BLE001 — o corpo do erro é auxiliar
            pass
        raise DelaPracaFalhou(f"o De Lá Pra Cá recusou {caminho} (HTTP {e.code})"
                              + (f": {detalhe}" if detalhe else ""), detalhe) from None
    except (urllib.error.URLError, OSError) as e:
        raise DelaPracaIndisponivel(
            f"o De Lá Pra Cá não respondeu em {URL} ({e}). A janela do Ciclo Assist sobe o "
            f"serviço dele com a aba Conformar; ela está aberta?") from None
    try:
        return json.loads(bruto.decode("utf-8") or "{}")
    except ValueError:
        raise DelaPracaFalhou(f"quem respondeu em {URL} não é o De Lá Pra Cá") from None


def saude() -> dict[str, Any]:
    """Vivo? (⚠️ MEDIDO: `/health` sem os cabeçalhos da página volta 401.)"""
    pedido = urllib.request.Request(URL + "/health", headers=_CABECALHOS, method="GET")
    try:
        with urllib.request.urlopen(pedido, timeout=PRAZO_S) as r:
            return json.loads(r.read().decode("utf-8") or "{}")
    except urllib.error.HTTPError as e:
        raise DelaPracaFalhou(f"o De Lá Pra Cá recusou /health (HTTP {e.code})") from None
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise DelaPracaIndisponivel(
            f"o De Lá Pra Cá não respondeu em {URL} ({e}). A janela do Ciclo Assist sobe o "
            f"serviço dele com a aba Conformar; ela está aberta?") from None


def resolve_aberto() -> str:
    """O nome do projeto aberto no Resolve, ou levanta com a frase do DLPC."""
    r = pedir("/resolve/projeto")
    if r.get("erro"):
        raise DelaPracaFalhou(str(r["erro"]))
    if not r.get("projeto"):
        raise DelaPracaFalhou("o DaVinci Resolve está aberto, mas sem projeto: abra ou crie um "
                              "projeto nele e peça de novo")
    return str(r["projeto"])


def abrir(caminho: str) -> dict[str, Any]:
    """Abre o arquivo da timeline (`.prproj`, `.aaf`, `.avb`): devolve a chave e as sequências."""
    return pedir("/receber/abrir", {"caminho": caminho}, prazo=PRAZO_LONGO_S)


def conformar(chave: str, sequencia: str, pastas: list[str], referencia: str = "",
              aceitar_escalas: bool = True,
              relatar: Callable[[str, float | None, str], None] | None = None) -> dict[str, Any]:
    """Do arquivo aberto até a timeline no Resolve, conferida pela referência.

    Devolve cada etapa como o DLPC respondeu (`analisar`, `preparar`, `midias`, `importar`,
    os pós e `conferencia`) e `tempos` em segundos. Uma etapa que falha PARA a sequência —
    importar sem mídia, ou conferir sem timeline, seria trabalho do editor jogado fora.
    """
    avisar = relatar or (lambda *_: None)
    tempos: dict[str, float] = {}
    saida: dict[str, Any] = {"tempos": tempos}

    def etapa(nome: str, rotulo: str, rota: str, corpo: dict, prazo: float = PRAZO_LONGO_S,
              detalhe: str = "") -> dict[str, Any]:
        avisar(rotulo, None, detalhe)
        t = time.monotonic()
        r = pedir(rota, corpo, prazo=prazo)
        tempos[nome] = round(time.monotonic() - t, 1)
        saida[nome] = r
        return r

    pedido: dict[str, Any] = {"avulso": chave, "mob_id": sequencia, "notas": False,
                              "marcar": True, "colorir": False}
    an = etapa("analisar", "o De Lá Pra Cá está lendo a timeline e achando as mídias",
               "/receber/prproj/analisar", dict(pedido, pastas=pastas),
               detalhe=f"{len(pastas)} pasta(s)")
    if referencia:
        pedido["referencia"] = referencia
    if aceitar_escalas:
        # ⭐ O "Ajustar todos" do painel: a escala digitada para outra mídia e a proporção de
        #   outro arquivo, refeitas pela regra do Resolve (DLPC `a3c0580`).
        pedido["reescalar"] = {x["caminho"]: x["fator"] for x in an.get("escala_de_outra_midia") or []}
        pedido["proporcao"] = [x["caminho"] for x in an.get("proporcao_de_outra_midia") or []]
    p = etapa("preparar", "o De Lá Pra Cá está preparando a timeline do Resolve",
              "/receber/preparar", pedido)
    if not p.get("drt"):
        raise DelaPracaFalhou(str(p.get("erro") or "o De Lá Pra Cá não preparou a timeline"))
    etapa("midias", "levando as mídias ao Resolve", "/resolve/midias",
          {"drt": p["drt"], "nome": p.get("nome")}, detalhe=f"{p.get('midias', '?')} mídia(s)")
    r = etapa("importar", "importando a timeline no Resolve", "/resolve/importar",
              {"drt": p["drt"], "pasta": p.get("pasta_no_resolve"), "nome": p.get("nome")})
    if not r.get("ok"):
        return saida
    for nome, chave_p, campo in (("fusion", "fusion", "clipes"), ("luts", "luts", "clipes"),
                                 ("compostos", "compostos", "grupos")):   # a ordem do painel
        if p.get(chave_p):
            etapa(nome, f"aplicando {nome} no Resolve", f"/resolve/{nome}",
                  {"nome": r["nome"], "uid": r.get("uid", ""), campo: p[chave_p]})
    conf = p.get("conferencia")
    if conf and referencia:
        saida["conferencia"] = _conferir(conf["id"], r, avisar, tempos)
    return saida


def conformar_no_baselight(chave: str, sequencia: str, pastas: list[str], job: str = "", markers: bool = True,
                           relatar: Callable[[str, float | None, str], None] | None = None,
                           atualizar: str = "") -> dict[str, Any]:
    """Do arquivo aberto (`.prproj` ou o xmeml da Carta) até a scene NOVA no Baselight, conferida plano a plano
    (proposta Baselight no app, etapa 4: no fluxo automatizado o JOB vem no pedido — o modelo não pergunta)."""
    avisar = relatar or (lambda *_: None)
    tempos: dict[str, float] = {}
    pedido: dict[str, Any] = {"avulso": chave, "mob_id": sequencia}
    avisar("o De Lá Pra Cá está lendo a timeline e casando com os originais", None, f"{len(pastas)} pasta(s)")
    t = time.monotonic()
    an = pedir("/receber/prproj/analisar", dict(pedido, pastas=pastas), prazo=PRAZO_LONGO_S)
    tempos["analisar"] = round(time.monotonic() - t, 1)
    avisar("o De Lá Pra Cá está conformando no Baselight", None, job or "")
    t = time.monotonic()
    p = pedir("/receber/preparar", dict(pedido, destino="baselight", job=job, markers=markers, atualizar=atualizar),
              prazo=PRAZO_LONGO_S)
    tempos["baselight"] = round(time.monotonic() - t, 1)
    if not p.get("baselight"):
        raise DelaPracaFalhou(str(p.get("erro") or "o De Lá Pra Cá não conformou no Baselight"))
    return {"analisar": an, "baselight": p["baselight"], "tempos": tempos}


def _conferir(id_: str, importada: dict[str, Any],
              avisar: Callable[[str, float | None, str], None], tempos: dict[str, float]) -> dict[str, Any]:
    """Quadro a quadro contra a referência — o roteiro do `conferir()` do painel."""
    t = time.monotonic()
    ini = pedir("/conferencia/iniciar", {"id": id_, "do_comeco": True})
    s = pedir("/resolve/conferirInicio", {"nome": importada["nome"], "uid": importada.get("uid", ""),
                                          "trilhaReferencia": ini.get("trilha_referencia")})
    if not s.get("ok"):
        return {"erro": str(s.get("erro") or "o Resolve não preparou a conferência")}
    estado: dict[str, Any] = {}
    try:
        faltam = ini.get("faltam") or []
        total = len(faltam) or 1
        for i in range(0, len(faltam), LOTE_DA_CONFERENCIA):
            lote = faltam[i:i + LOTE_DA_CONFERENCIA]
            avisar("conferindo pela referência", i / total, f"{i} de {len(faltam)} pontos")
            pedir("/resolve/conferirQuadros", {"pontos": lote}, prazo=PRAZO_LONGO_S)
            pedir("/conferencia/quadros", {"id": id_, "quadros": [x["quadro"] for x in lote]})
    finally:
        # ⚠️ Sempre fecha: a conferência deixa a trilha da referência e o playhead mexidos no
        #   Resolve, e o `conferirFim` é quem os devolve.
        for _ in range(600):
            estado = pedir("/conferencia/estado", {"id": id_})
            if not estado.get("na_fila"):
                break
            time.sleep(0.5)
        marcas = pedir("/conferencia/marcas", {"id": id_})
        pedir("/resolve/conferirFim", marcas)
    tempos["conferencia"] = round(time.monotonic() - t, 1)
    return estado
