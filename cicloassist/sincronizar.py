"""A ponte com o Sincronizar (DRAMASYNC): quem sincroniza diária é ele, não a gente.

Plano: `DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md` (decisões do editor, 2026-09-17). O Ciclo
Assist **orquestra**; o Sincronizar **processa**. Um lugar só sabe sincronizar material — o motor
dele, validado em produção —, e a segunda implementação da mesma pergunta é a forma de bug
que esta casa já pagou várias vezes.

## O que existe do outro lado, hoje (Sincronizar 0.3.1)

| rota | faz |
|---|---|
| `GET /health` | vivo? ocupado? versão |
| `POST /sources` `{paths, sound?}` | classifica os caminhos em fontes (câmera × som) pelo esqueleto de nome |
| `POST /syncmap` `{clips, method, fps}` | sincroniza; devolve `{job_id}` |
| `GET /prproj/status?id=` | `waiting`/`running`/`done`/`error`, fração, etapa, resultado |
| `POST /open` `{name, sources}` | entrega o material À JANELA do app, já agrupado, e a traz para a frente |

## ⭐⭐ E o que fecha o ciclo, escrito no Sincronizar em 2026-09-18

| rota | faz |
|---|---|
| `GET /api/v1/info` | versão, `busy` e **que painéis de NLE estão escutando** |
| `POST /api/v1/nlejob` `{job_id, nle, nome?, labels?}` | enfileira a MONTAGEM daquele sync |
| `GET /api/v1/montagem?id=` | `na_fila` → `montando` → `feito` \\| `erro`, com o resumo |

Até aqui o Ciclo Assist chegava ao MAPA e parava: a sequência era montada à mão, pelo
painel do Sincronizar (Exportar → Premiere (plugin)). O trabalho terminava a três cliques do
fim — e o modelo, corretamente, mandava o editor dar esses cliques.

⛔⛔ **Nunca `GET /nlejob`.** Essa é a fila que o PAINEL do Sincronizar consome para montar a
sequência dentro do NLE: quem busca ali TIRA o trabalho da fila. Se o Ciclo Assist a lesse,
o painel do Sincronizar nunca receberia a montagem — e o sintoma seria "o Sincronizar disse que
terminou e nada apareceu no projeto". A rota da ponte só ESCREVE na fila.

⛔ **Quem monta continua sendo o painel dele**, e por isso ele precisa estar ABERTO no NLE:
o CEP só roda com o painel aberto. Sem painel, o pedido é recusado na porta (412) com a
frase que diz o que fazer — aceitar deixaria o job numa fila sem dono, morrendo em silêncio
depois de o editor ter esperado minutos pelo sync.

⛔ **E o mapa não viaja daqui para lá.** Vai o `job_id` do sync que o próprio Sincronizar rodou:
o formato do job do painel (`map.groups`, `labels`) é assunto interno dele, e a ponte não
quebra quando ele mudar.

## A autenticação

O arquivo `plugin-token` na pasta de dados do Sincronizar — o mesmo que os painéis dele usam. É
uma assimetria honesta: uma página web não lê arquivo do disco, e o Ciclo Assist roda como o
mesmo usuário. ⚠️ O app sorteia um token novo a cada arranque, então um `401` manda **reler
o arquivo** e tentar de novo, uma vez.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger("cicloassist.sincronizar")

URL = "http://127.0.0.1:7817"
#: Uma batida curta: o Sincronizar responde na hora ou não está lá.
PRAZO_S = 8.0
#: O sync de uma diária leva minutos; o polling é barato e o prazo é do EDITOR, não nosso.
PRAZO_DO_SYNC_S = 60 * 30
#: Montar é rápido — o que se espera aqui é o painel VIR BUSCAR, na batida dele (~4 s).
PRAZO_DA_MONTAGEM_S = 60 * 5
INTERVALO_S = 1.0

METODOS = {"hibrido": "hybrid", "timecode": "timecode", "forma_de_onda": "waveform"}


class SincronizarIndisponivel(RuntimeError):
    """O Sincronizar não está aberto, ou não respondeu."""


class SincronizarOcupado(RuntimeError):
    """O motor dele atende UM trabalho por vez, e já tem um. Resposta normal, não erro."""


class SincronizarFalhou(RuntimeError):
    """O trabalho rodou e deu errado, com o motivo dele."""

    def __init__(self, mensagem: str, codigo: int = 0) -> None:
        super().__init__(mensagem)
        #: O HTTP que ele devolveu, quando houve um. Zero = nem chegou a responder.
        self.codigo = codigo


#: ⭐ Quem escreve no Premiere é a aba PREPARAR do guarda-chuva (o Sincronizar embutido), pela ponte invisível dele
#: (`com.orbita.ponte` — o id da extensão instalada; sai na fase 4, com a ponte única): ela pergunta pela fila na batida dela, e é isso que a `/api/v1` conta como "escutando".
#: O painel CEP antigo (`com.orbita.sync`) sai quando a ponte é instalada (decisão do autor, 2026-11-06: só a Preparar).
FALTA_A_PREPARAR = ("o Sincronizar não está ligado ao Premiere. Quem monta é a aba Preparar do Ciclo Assist, pela "
                    "ponte do Sincronizar no Premiere: abra a aba Preparar uma vez e confira se ela mostra o Premiere "
                    "conectado (sem a ponte, instale-a na ⚙ da Preparar e reabra o Premiere). Depois peça de novo.")


class SincronizarSemPainel(RuntimeError):
    """O painel do Sincronizar não está aberto no NLE — e é ELE quem monta a sequência."""


def pasta_de_dados() -> Path:
    """Onde o módulo Sincronizar guarda os dados — e o `plugin-token`: `<pasta do Ciclo Assist>/sincronizar`, a mesma
    conta do servidor do módulo (`modulos/sincronizar/motor/appsettings.py::app_data_dir`; era `…/Orbita` até a
    fase 3, 2026-11-07). `SINCRONIZAR_DADOS` manda, como lá."""
    explicita = os.environ.get("SINCRONIZAR_DADOS")
    if explicita:
        return Path(explicita)
    from cicloassist.servico import config
    return config.pasta() / "sincronizar"


def arquivo_do_token() -> Path:
    """⭐ Passo 2 da fase 4 (2026-11-07): o token ÚNICO do Ciclo Assist (`<dados>/plugin-token`, publicado pelo
    núcleo, `servico/nucleo.py`) — o servidor do Sincronizar confere este."""
    from cicloassist.servico import nucleo
    return nucleo.caminho()


_token = ""
_trava = threading.Lock()


def token(reler: bool = False) -> str:
    global _token
    with _trava:
        if _token and not reler:
            return _token
        try:
            _token = arquivo_do_token().read_text(encoding="utf-8").strip()
        except OSError as e:
            raise SincronizarIndisponivel(
                f"não achei o token do Sincronizar em {pasta_de_dados()} ({e}). Ele já foi aberto "
                f"nesta máquina?") from None
        return _token


def pedir(caminho: str, corpo: dict | None = None, metodo: str = "",
          prazo: float = PRAZO_S, _repetiu: bool = False) -> dict[str, Any]:
    """Uma chamada ao Sincronizar, com o token. Stdlib — regra da casa."""
    dados = json.dumps(corpo).encode("utf-8") if corpo is not None else None
    pedido = urllib.request.Request(
        URL + caminho, data=dados,
        headers={"Content-Type": "application/json", "X-Ciclo-Token": token()},
        method=metodo or ("POST" if dados is not None else "GET"))
    try:
        with urllib.request.urlopen(pedido, timeout=prazo) as r:
            bruto = r.read()
    except urllib.error.HTTPError as e:
        if e.code == 401 and not _repetiu:
            # ⚠️ Token novo a cada arranque do app: reler o arquivo é o conserto, e ele
            #   custa nada. Sem isto, reiniciar o Sincronizar quebrava a ponte até o serviço
            #   reiniciar também.
            token(reler=True)
            return pedir(caminho, corpo, metodo, prazo, _repetiu=True)
        if e.code == 409:
            raise SincronizarOcupado(
                "O Sincronizar está ocupado com outro trabalho (ele atende um por vez). "
                "Espere ele terminar e peça de novo.") from None
        detalhe = ""
        try:
            detalhe = json.loads(e.read().decode("utf-8")).get("error", "")
        except Exception:  # noqa: BLE001 — o corpo do erro é auxiliar
            pass
        raise SincronizarFalhou(f"o Sincronizar respondeu HTTP {e.code}"
                           + (f": {detalhe}" if detalhe else ""), codigo=e.code) from None
    except (urllib.error.URLError, OSError) as e:
        raise SincronizarIndisponivel(
            f"o Sincronizar não respondeu em {URL} ({e}). Ele está aberto? Ele vive na bandeja "
            f"do sistema quando a janela é fechada.") from None
    try:
        return json.loads(bruto.decode("utf-8"))
    except ValueError:
        raise SincronizarFalhou(f"quem respondeu em {URL} não é o Sincronizar") from None


def saude() -> dict[str, Any]:
    """Vivo? ocupado? que versão?

    ⚠️ Sem `?nle=`: esse parâmetro MARCA PRESENÇA de painel no app, e o Ciclo Assist não é
    um painel do Sincronizar. Dizer que é faria o botão "Enviar" dele prometer um painel que não
    existe.
    """
    return pedir("/health")


def sincronizar(clipes: list[dict[str, Any]], metodo: str = "hybrid",
                fps: float | None = None) -> str:
    """Começa o sync e devolve o `job_id`. Cada clipe: `{path, group, kind?, group_order?}`."""
    corpo: dict[str, Any] = {"clips": clipes, "method": metodo}
    if fps:
        corpo["fps"] = fps
    resposta = pedir("/syncmap", corpo, prazo=30)
    job = resposta.get("job_id") or resposta.get("id") or ""
    if not job:
        raise SincronizarFalhou(f"o Sincronizar não devolveu um job: {str(resposta)[:200]}")
    return str(job)


def andamento(job_id: str) -> dict[str, Any]:
    return pedir(f"/prproj/status?id={urllib.parse.quote(job_id)}")


def esperar(job_id: str, relatar: Callable[[str, float | None], None] | None = None,
            prazo: float = PRAZO_DO_SYNC_S, conferir: Callable[[], None] | None = None) -> dict[str, Any]:
    """Acompanha até acabar. Devolve o resultado; levanta com o motivo se falhar.

    `conferir` roda a cada volta e pode LEVANTAR para parar de esperar (o editor cancelou o fluxo).
    ⚠️ Parar de esperar não para o Sincronizar: ele não tem como cancelar um sync em curso (o "Abortar"
    do painel dele também só para de acompanhar — `httpserver.rs`)."""
    limite = time.monotonic() + prazo
    ultimo = ""
    while True:
        if conferir is not None:
            conferir()
        estado = andamento(job_id)
        etapa = str(estado.get("stage") or "")
        fracao = estado.get("fraction")
        if relatar and etapa and etapa != ultimo:
            relatar(etapa, fracao if isinstance(fracao, (int, float)) else None)
            ultimo = etapa
        situacao = str(estado.get("state") or "")
        if situacao == "done":
            return estado.get("result") or {}
        if situacao == "error":
            raise SincronizarFalhou(str(estado.get("error") or "o sync falhou sem dizer por quê"))
        if time.monotonic() > limite:
            raise SincronizarIndisponivel(
                f"o sync passou de {prazo / 60:.0f} minutos sem terminar; veja o Sincronizar.")
        time.sleep(INTERVALO_S)


def info() -> dict[str, Any]:
    """`/api/v1/info`: versão, ocupado, e **que painéis de NLE estão escutando**.

    ⭐ É o que se pergunta ANTES de pedir um sync de minutos: sem painel do Sincronizar aberto
    no NLE, ninguém monta a sequência no fim — e descobrir isso depois da espera é o
    mesmo que não ter sincronizado.
    """
    try:
        return pedir("/api/v1/info")
    except SincronizarFalhou as e:
        if e.codigo == 404:
            raise SincronizarFalhou(
                "este Sincronizar é antigo demais para a ponte: ele não tem /api/v1. "
                "Atualize o Sincronizar (a montagem pela conversa entrou na 0.3.2).") from None
        raise


def tem_painel(nle: str = "premiere") -> bool:
    """Tem painel do Sincronizar escutando naquele NLE? (Falha de rede não é "não".)"""
    return bool((info().get("paineis") or {}).get(nle))


def mandar_montar(job_id: str, nome: str = "", nle: str = "premiere",
                  rotulos: dict[str, str] | None = None) -> str:
    """Enfileira a MONTAGEM da sequência daquele sync. Devolve o id da montagem.

    ⛔⛔ **Nunca `GET /nlejob`**: quem lê aquela fila TIRA o trabalho do painel do Sincronizar,
    e a sequência nunca seria montada — com o sintoma "ele disse que terminou e nada
    apareceu no projeto". Esta rota só ESCREVE na fila.

    ⚠️ O mapa não viaja daqui: vai o `job_id` do sync que o próprio Sincronizar rodou. O
    formato do job do painel é assunto dele.
    """
    corpo: dict[str, Any] = {"job_id": job_id, "nle": nle}
    if nome:
        corpo["nome"] = nome
    if rotulos:
        corpo["labels"] = rotulos
    try:
        resposta = pedir("/api/v1/nlejob", corpo, prazo=30)
    except SincronizarFalhou as e:
        if e.codigo == 412:
            raise SincronizarSemPainel(
                FALTA_A_PREPARAR) from None
        if e.codigo == 404:
            raise SincronizarFalhou(
                "este Sincronizar é antigo demais para montar pela conversa (sem /api/v1). "
                "O mapa do sync está pronto; monte pelo painel dele.") from None
        raise
    montagem = str(resposta.get("montagem_id") or "")
    if not montagem:
        raise SincronizarFalhou(f"o Sincronizar aceitou e não disse o id: {str(resposta)[:200]}")
    return montagem


def esperar_montagem(montagem_id: str, relatar: Callable[[str, float | None], None] | None = None,
                     prazo: float = PRAZO_DA_MONTAGEM_S) -> dict[str, Any]:
    """Acompanha a montagem até o painel devolver o resultado.

    ⚠️ O prazo é curto perto do sync: montar é rápido (o material já está medido). O que
    demora aqui é o painel VIR BUSCAR — ele pergunta na batida dele —, e por isso um
    estouro de prazo não é "deu errado": é "não sei", e tem de ser dito assim.
    """
    limite = time.monotonic() + prazo
    ultimo = ""
    while True:
        estado = pedir(f"/api/v1/montagem?id={urllib.parse.quote(montagem_id)}")
        situacao = str(estado.get("estado") or "")
        if relatar and situacao and situacao != ultimo:
            relatar(situacao, None)
            ultimo = situacao
        if situacao in ("feito", "erro"):
            return estado
        if time.monotonic() > limite:
            raise SincronizarIndisponivel(
                f"o painel do Sincronizar não deu notícia da montagem em {prazo:.0f}s. O sync "
                f"está pronto; veja o painel dele no NLE.")
        time.sleep(INTERVALO_S)


def faz_merged() -> bool:
    """Este Sincronizar sabe fazer os merged de um sync (`POST /api/v1/merge`, 06/11)?"""
    return "merged" in (info().get("capacidades") or [])


def fazer_merged(job_id: str, proxies: dict[str, str] | None = None, nome: str = "",
                 premiere_alvo: str = "25") -> dict[str, Any]:
    """Pede os merged clips daquele sync: o Sincronizar escreve o `.prproj` (`CENAS/<cena>`, com o
    proxy de cada câmera anexado) e o painel dele o importa no projeto aberto.

    Devolve o que o Sincronizar respondeu: `{montagem_id, bins, merged, com_proxy, sem_proxy,
    proxy_ausente, arquivo}`; o fim da importação é `esperar_montagem(montagem_id)`.
    Contrato: `DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md` §9.

    ⚠️ `proxies` são só os pares que JÁ conferiram (`resolve_proxy.conferir_par`): o
    Sincronizar só exige que o arquivo exista.
    """
    corpo: dict[str, Any] = {"job_id": job_id, "proxies": dict(proxies or {}),
                             "premiere_alvo": "2023" if premiere_alvo == "2023" else "25"}
    if nome:
        corpo["nome"] = nome
    try:
        resposta = pedir("/api/v1/merge", corpo, prazo=120)
    except SincronizarFalhou as e:
        if e.codigo == 412:
            raise SincronizarSemPainel(
                FALTA_A_PREPARAR) from None
        if e.codigo == 404:
            raise SincronizarFalhou(
                "este Sincronizar é antigo demais para fazer merged pela conversa (sem /api/v1/merge). "
                "Atualize o Sincronizar.") from None
        raise
    if not resposta.get("montagem_id"):
        raise SincronizarFalhou(f"o Sincronizar aceitou e não disse o id: {str(resposta)[:200]}")
    return resposta


def pode_sincronizar_no_avid() -> str:
    """Vazio se dá para sincronizar no Media Composer agora; senão, a frase do porquê não.

    ⭐ No MC não há painel a esperar: quem monta a bin é o próprio Sincronizar (autora a `.avb`
    e a abre pelo 9100). O que se confere aqui é a CAPACIDADE (Sincronizar de 21/10 em diante)
    e o MC no ar — a mesma recusa que o 412 da rota daria, só que antes do cartão.
    """
    dados = info()
    if "avid_sincronizar" not in (dados.get("capacidades") or []):
        return ("este Sincronizar é antigo demais para sincronizar no Media Composer (sem "
                "/api/v1/avid/sincronizar). Atualize o Sincronizar.")
    if not (dados.get("nles") or {}).get("avid"):
        return ("o Media Composer não está aberto (ou está sem projeto): o Sincronizar não o "
                "alcançou pela porta 9100.")
    return ""


def sincronizar_no_avid(pasta: str = "", metodo: str = "hybrid", nome: str = "",
                        bins: list[str] | None = None, fontes: list[dict[str, Any]] | None = None) -> str:
    """`POST /api/v1/avid/sincronizar`: a pasta do projeto do MC — ou as `bins` — vira bin sincronizada.

    Um pedido, três passos do lado de lá (ler as bins, sincronizar, montar a bin no
    projeto aberto), acompanhados pelo `esperar` de sempre. Contrato:
    `DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md` §8. Devolve o `job_id`.

    ⭐ `bins` (2026-11-01): a lista explícita, relativa ao projeto, sem `.avb`, com `/` — a chave
    do Sincronizar (`chave_de_bin`). É o caminho das bins na RAIZ do projeto, que não estão em pasta
    nenhuma: no teste do autor o modelo, só com "pasta", mandou o nome do projeto e o Sincronizar
    respondeu "não há bin na pasta". O endpoint dele já aceitava as duas formas.
    """
    corpo: dict[str, Any] = {"metodo": metodo}
    if fontes:
        # ⭐ As fontes declaradas: uma câmera em duas bins (cartão 1 e cartão 2) é UMA câmera (plano de 2026-11-08).
        corpo["fontes"] = [{"tipo": f.get("tipo"), "nome": f.get("nome") or "",
                            "bins": [str(b).replace("\\", "/").strip("/") for b in (f.get("bins") or [])]}
                           for f in fontes]
    elif bins:
        corpo["bins"] = [b.replace("\\", "/").strip("/") for b in bins]
    else:
        corpo["pasta"] = pasta
    if nome:
        corpo["nome"] = nome
    try:
        resposta = pedir("/api/v1/avid/sincronizar", corpo, prazo=30)
    except SincronizarFalhou as e:
        if e.codigo == 412:
            raise SincronizarFalhou(
                "o Media Composer não está aberto (ou está sem projeto): o Sincronizar não o "
                "alcançou pela porta 9100.", codigo=412) from None
        if e.codigo == 404:
            raise SincronizarFalhou(
                "este Sincronizar é antigo demais para sincronizar no Media Composer. "
                "Atualize o Sincronizar.", codigo=404) from None
        raise
    job = str(resposta.get("job_id") or "")
    if not job:
        raise SincronizarFalhou(f"o Sincronizar não devolveu um job: {str(resposta)[:200]}")
    return job


#: ⭐ O padrão de FÁBRICA: o nome do vídeo original (autor, 2026-11-01) — *"só renomeamos
#: os subclipes para cena, plano e take caso pedido no prompt"*. O padrão de cena saía
#: `C_P_T` em material sem claquete, quatro subclipes com o mesmo nome.
PADRAO_DE_SUBCLIPE = "%{nomedevideo}"

#: Cena, plano e take — o padrão pilotado no Renomear do Sincronizar (`C04_P01_T001`, 21/10).
#: Só quando o editor PEDE esse nome. Sem a informação no material, o Sincronizar cai no nome
#: do vídeo original.
PADRAO_CENA_PLANO_TAKE = "C%{cena}_P%{plano}_T%{take2}"


def subclipar_no_avid(bin_sincronizada: str, padrao: str = PADRAO_DE_SUBCLIPE,
                      por_cena: bool = True, nome_da_bin: str = "",
                      relatar: Callable[[str, float | None], None] | None = None,
                      ) -> dict[str, Any]:
    """A aba Subclipar do Sincronizar, pela ponte: a sequência sincronizada vira subclipes.

    Dois jobs, os mesmos que o painel dele dispara (`/avid/subclipes/ler` e `/gerar`).
    `bin_sincronizada` é o `.avb` que o sync acabou de criar (`montagem.path`). Com
    `por_cena`, cada cena ganha a sua bin na pasta CENAS do projeto. Devolve
    `{"tomadas": [...], "escrita": {bins, total, caminhos, ...}}`.

    ⚠️ Os nomes são recompostos DO LADO DE LÁ pelo mesmo código que desenha a prévia
    dele: daqui vão só a leitura e o padrão, nunca uma lista de nomes.
    """
    leitura = esperar(pedir("/avid/subclipes/ler", {"bin": bin_sincronizada},
                            prazo=30).get("job_id") or "", relatar=relatar)
    leitura_id = str(leitura.get("leitura_id") or "")
    if not leitura_id:
        raise SincronizarFalhou(f"o Sincronizar leu a bin e não devolveu a leitura: {str(leitura)[:200]}")
    tomadas = leitura.get("tomadas") or []
    if not tomadas:
        raise SincronizarFalhou("a sequência sincronizada não tem tomada para subclipar")
    escrita = esperar(pedir("/avid/subclipes/gerar",
                            {"leitura_id": leitura_id, "padrao": padrao, "por_cena": por_cena,
                             # ⭐ o nome que o editor pediu (por cena, o da PASTA); vazio = o do Sincronizar
                             "nome": nome_da_bin.strip()},
                            prazo=30).get("job_id") or "", relatar=relatar)
    return {"tomadas": tomadas, "escrita": escrita}


def resumo_do_mapa(resultado: dict[str, Any]) -> dict[str, Any]:
    """O mapa do sync em números que o editor lê — e o que ficou de fora.

    ⚠️ Órfão não é erro: câmera sem som (ou som sem câmera) acontece em diária real. Mas
    tem de ser DITO, senão o editor descobre na timeline.
    """
    grupos = resultado.get("groups")
    diarias = grupos if isinstance(grupos, list) else [resultado]
    saida = []
    for d in diarias:
        if not isinstance(d, dict):
            continue
        # ⛔ Cada `camera_group` é uma câmera FÍSICA (uma trilha de vídeo, no modelo do
        #   Sincronizar); o `cameras` de dentro dela são os CLIPES. Somar os de dentro dizia
        #   "26 câmeras" para a CAM A da D02 (2026-10-22, no ensaio da demo).
        fisicas = [g for g in (d.get("camera_groups") or [])
                   if isinstance(g, dict) and g.get("cameras")]
        saida.append({
            "diaria": d.get("name") or "",
            "fps": d.get("fps"),
            "cameras": len(fisicas),
            "nomes_das_cameras": [str(g.get("name") or "") for g in fisicas if g.get("name")],
            "clipes_de_camera": sum(len(g["cameras"]) for g in fisicas),
            "takes_sincronizados": len(d.get("takes") or []),
            "cameras_sem_som": len(d.get("orphan_paths") or []),
            "sons_sem_camera": len(d.get("orphan_sounds") or []),
        })
    return {"diarias": saida, "quantas": len(saida)}
