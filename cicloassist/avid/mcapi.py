"""A ponte com o Media Composer aberto — cliente gRPC do serviço `mcapi.MCAPI`.

O Media Composer hospeda um serviço gRPC em **`[::1]:9100`** e **o backend não valida
token**. Quem exige credencial é o *gateway* (4920/4930), que serve os painéis `.avpi`;
o backend direto, em loopback, aceita chamada com header vazio.

⚠️ **Isso é propriedade do produto da Avid, não escolha nossa.** Qualquer processo local
dirige o Media Composer sem credencial. Não expomos isso em lugar nenhum: somos cliente,
nunca ponte — nada aqui escuta na rede.

O `.proto` é reconstrução de um SDK fechado, extraída por reflection e guardada no banco.
Os stubs saem de `tools/gerar_stubs.py`.

## O contrato, em uma frase

Todo request é `{header, body}` e toda response é `{header, body}`. Cinco chamadas são
server-streaming: a resposta vem em pedaços, um item por mensagem.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import PurePosixPath, PureWindowsPath

import grpc

from .proto import mcapi_tipos_pb2 as pb

log = logging.getLogger("cicloassist.avid")

BACKEND = "[::1]:9100"
SERVICO = "/mcapi.MCAPI/"

# ⚠️⚠️ **Dois tetos, porque são dois tipos de chamada.** Consulta (`GetMobInfo`,
# `GetListOf*`) custa centenas de ms; operação de arquivo (`OpenBin`, `CloseBin`) faz o
# MC ler ou gravar a bin inteira e passa de meio minuto numa bin com dezenas de masters.
#
# ⭐ O modo de falha de um teto curto demais não é "demorou" — é **silencioso e
# destrutivo de resultado**. Medido em 2026-08-16: o `CloseBin` estourou 20 s, o chamador
# concluiu que não conseguiu fechar e gravou o trabalho com OUTRO NOME, enquanto o MC
# seguia fechando a bin normalmente. O editor ficou com duas bins e nada acusou erro.
#
# A lição não é sobre bin: **prazo curto demais não devolve erro honesto, devolve uma
# decisão errada tomada com confiança.**
TEMPO_DE_CONSULTA_S = 20.0
TEMPO_DE_ARQUIVO_S = 300.0

# Nome da pasta de bins excluídas **como ela existe no DISCO**.
# ⚠️ É em inglês mesmo num Media Composer em português: a interface mostra "Lixeira", o
# disco guarda `Trash`. Traduzir seria procurar uma pasta que não existe.
PASTA_DA_LIXEIRA = "trash"


def relativo_ao_projeto(absoluto: str, raiz: str) -> str | None:
    """O caminho da bin relativo à pasta do projeto, ou `None` se ela está fora dele.

    ⭐ UMA conta para as três ferramentas que precisam dela (a ponte, `montar_corte` e
    `separar_falas`), e ela compara como o DISCO compara, não como a string:

    - ⛔ **Sem maiúsculas.** NTFS, APFS e exFAT não distinguem — mas `os.path.relpath`
      no Mac sim: `/USERS/x` contra `/Users/x` dava `../../../users/...`.
    - ⛔ **Sem NFC × NFD.** MEDIDO (2026-09-14): o exFAT do macOS lista nomes decompostos, e
      49 caminhos das bins reais do MC do Mac vinham em NFD. Comparando a string, o
      "relativo" saía absoluto, e o `GetListOfBinItems` respondia "Bin is not open" — a
      mensagem que manda procurar o estado da bin quando o problema é o caminho.
    - ⭐ A forma do caminho decide as regras (`C:\\…` é Windows em qualquer máquina), e
      a resposta leva as partes como vieram, com o separador daquela forma.
    """
    windows = bool(re.match(r"^([A-Za-z]:|\\\\|//)", raiz or ""))
    tipo = PureWindowsPath if windows else PurePosixPath
    partes_raiz = tipo(raiz).parts
    partes = tipo(absoluto).parts

    def igual(p: str) -> str:
        return unicodedata.normalize("NFC", p).casefold()

    n = len(partes_raiz)
    if not raiz or len(partes) <= n or \
            [igual(p) for p in partes[:n]] != [igual(p) for p in partes_raiz]:
        return None
    return str(tipo(*partes[n:]))

# ⛔⛔ **Carregar num monitor, consultar os monitores e fechar a bin, colados, DERRUBA o
# Media Composer.** MEDIDO em 2026-09-13 (MC 2025.6.58781, `spikes/fechar_bin_com_monitor.py`
# e `qual_passo_derruba.py`): `LoadMobsIntoViewer` → `GetViewerMobs` → `CloseBin` sem pausa
# deu `ACCESS_VIOLATION` em 0x0 na thread principal **5 vezes em 5**. Tirando qualquer um
# dos três, ou pondo 3 s de pausa depois do carregar, **0 em 11**:
#
#     carregar → fechar                          0 de 3
#     carregar → consultar (sem fechar)          0 de 2
#     carregar → 3 s → consultar → fechar        0 de 6
#
# O MC não fecha: mostra um diálogo e segue depois do OK — e a API fica MUDA até alguém
# clicar, o que um cliente lê como "ocupado". Quem chama pela API não vê o diálogo.
#
# ⇒ Depois de um `LoadMobsIntoViewer`, `GetViewerMobs` e `CloseBin` esperam o monitor
#    assentar. Vale para o PROCESSO inteiro, e não para uma sessão: o serviço abre uma
#    `MediaComposer` por ferramenta, e a sequência perigosa cruza ferramentas.
ASSENTAR_DEPOIS_DE_CARREGAR_S = 3.0
_ESPERAM_O_MONITOR = frozenset({"GetViewerMobs", "CloseBin"})
_trava_do_monitor = threading.Condition()
_carregou_em: float | None = None
#: Carregamentos AINDA dentro do MC. ⛔ Revisão de 2026-11-07: a pausa só contava a partir do FIM do carregar, e com o
#  núcleo (os três módulos pela mesma ponte) um `CloseBin` de outro módulo chegando enquanto o `LoadMobsIntoViewer`
#  ainda corria passava sem esperar nada — a sequência que derruba o MC. Agora ele espera o carregar voltar E os 3 s.
_carregando = 0
#: Teto da espera por um carregar em curso: um carregar preso não pode segurar o fechar de bin para sempre.
ESPERA_MAXIMA_POR_CARREGAR_S = 120.0


def _esperar_o_monitor(metodo: str) -> None:
    global _carregando
    with _trava_do_monitor:
        if metodo == "LoadMobsIntoViewer":
            _carregando += 1
            return
        if metodo not in _ESPERAM_O_MONITOR:
            return
        if _carregando > 0:
            log.info("%s espera: um monitor está carregando agora", metodo)
            if not _trava_do_monitor.wait_for(lambda: _carregando == 0, timeout=ESPERA_MAXIMA_POR_CARREGAR_S):
                log.warning("%s seguiu sem o carregar voltar (%.0f s)", metodo, ESPERA_MAXIMA_POR_CARREGAR_S)
        if _carregou_em is None:
            return
        falta = ASSENTAR_DEPOIS_DE_CARREGAR_S - (time.monotonic() - _carregou_em)
    if falta > 0:
        log.info("%s espera %.1f s: um monitor acabou de carregar", metodo, falta)
        time.sleep(falta)


def _marcar_carregamento(metodo: str) -> None:
    global _carregou_em, _carregando
    if metodo == "LoadMobsIntoViewer":
        with _trava_do_monitor:
            _carregou_em = time.monotonic()
            _carregando = max(0, _carregando - 1)
            _trava_do_monitor.notify_all()


# ── o NÚCLEO: os outros módulos falam com o MC por aqui (fase 4 do plano um app só, passo 4, 2026-11-07) ──────────
#
# ⭐ Decisão do autor: SÓ o Assist fala com o Media Composer. O Sincronizar e o Conformar montam o pedido do jeito de
#    sempre, serializado, e o mandam a `POST /nucleo/avid/chamar` (`avid/canal_do_nucleo.py` deles); a chamada sai DAQUI,
#    com a pausa do monitor deste processo — que passa a valer para o app inteiro. Os bytes voltam crus: cada módulo
#    lê com o próprio `pb2` (o MESMO `.proto`, conferido byte a byte).

#: O caminho da reflection do servidor gRPC (o `rpcs()` do Conformar): só ela, além do serviço do MC.
REFLEXAO = "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo"
_ROTA_DO_MC = re.compile(r"^/mcapi\.MCAPI/([A-Z][A-Za-z0-9]{1,80})$")


def chamar_cru(rota: str, pedido: bytes, tipo: str, prazo: float = TEMPO_DE_CONSULTA_S,
               endereco: str = BACKEND) -> list[bytes]:
    """Uma chamada ao MC com o pedido JÁ serializado; devolve as respostas serializadas (uma, se `unario`).

    `tipo`: `unario`, `fluxo` (server-streaming) ou `reflexao` (só a `REFLEXAO`; devolve a primeira resposta).
    ⛔ Só rotas do serviço do MC (`/mcapi.MCAPI/<Metodo>`) ou a reflection — nunca um caminho qualquer. Erro do gRPC
    SOBE (`grpc.RpcError`): quem chama devolve o código, e o `_traduzir` do módulo diz a frase dele."""
    if tipo == "reflexao":
        if rota != REFLEXAO:
            raise ValueError(f"reflection só pela rota dela, não {rota!r}")
        metodo = ""
    else:
        casou = _ROTA_DO_MC.match(rota)
        if not casou or tipo not in ("unario", "fluxo"):
            raise ValueError(f"rota ou tipo inválido: {rota!r} ({tipo!r})")
        metodo = casou.group(1)
        if not hasattr(pb, f"{metodo}Request"):
            raise ValueError(f"{metodo} não existe no contrato do Media Composer")
    cru = lambda b: b  # noqa: E731 — os bytes passam como vieram
    canal = grpc.insecure_channel(endereco)
    try:
        if tipo == "reflexao":
            fluxo = canal.stream_stream(rota, request_serializer=cru, response_deserializer=cru)
            return [next(iter(fluxo(iter([pedido]), timeout=prazo)))]
        fabrica = canal.unary_stream if tipo == "fluxo" else canal.unary_unary
        stub = fabrica(rota, request_serializer=cru, response_deserializer=cru)
        _esperar_o_monitor(metodo)
        try:
            r = stub(pedido, timeout=prazo)
            return list(r) if tipo == "fluxo" else [r]
        finally:
            _marcar_carregamento(metodo)
    finally:
        canal.close()


def mob_id_da_api(urn: str) -> str:
    """`urn:smpte:umid:060a2b34.01010105…` (o do arquivo) → a forma que a API aceita.

    MEDIDO em 2026-09-13 (`spikes/extrair_da_timeline.py`): o `LoadMobsIntoViewer` quer os
    64 hex em cinco blocos, `26-6-16-12-4`, e é assim que o `GetViewerMobs` devolve.
    """
    h = urn.rsplit(":", 1)[-1].replace(".", "").replace("-", "").lower()
    if len(h) != 64:
        raise ValueError(f"MobID {urn!r} não tem 64 dígitos hexadecimais")
    return f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"


def _dialogo_na_tela() -> bool:
    """⛔⛔ MEDIDO (2026-11-09, MC 2024.6): com um diálogo aberto a API não responde, e cada ferramenta dizia "não respondeu no prazo". Olhar a tela é só para enriquecer o erro: se falhar, fica o erro de sempre."""
    try:
        from . import socorro  # noqa: PLC0415 — o socorro carrega o piloto inteiro, e isto só roda quando a chamada já falhou
        return socorro.inesperada()
    except Exception:  # noqa: BLE001
        return False


class McApiErro(Exception):
    """O Media Composer não atendeu, ou atendeu com erro."""


class McApiFechado(McApiErro):
    """Não há Media Composer escutando. É o caso NORMAL de não estar aberto."""


class McApiNaoImplementado(McApiErro):
    """Este Media Composer não tem esse rpc — **diferença de VERSÃO, não defeito**.

    Medido: `GetListOfWindows` responde no MC 25.12 e devolve `UNIMPLEMENTED` no 25.6.
    """


@dataclass(frozen=True)
class ItemDeBin:
    nome: str
    mob_id: str
    selecionado: bool


class MediaComposer:
    """Sessão com o Media Composer aberto. Use como context manager."""

    def __init__(self, endereco: str = BACKEND, timeout: float = TEMPO_DE_CONSULTA_S):
        self.endereco = endereco
        self.timeout = timeout
        self._canal: grpc.Channel | None = None
        self._projeto: dict | None = None

    def __enter__(self) -> "MediaComposer":
        # `insecure` é o único modo que o backend oferece: plaintext em loopback.
        self._canal = grpc.insecure_channel(self.endereco)
        return self

    def __exit__(self, *_) -> None:
        if self._canal is not None:
            self._canal.close()
            self._canal = None

    # ── encanamento ──────────────────────────────────────────────────────────

    def _tipo(self, nome: str):
        try:
            return getattr(pb, nome)
        except AttributeError:
            raise McApiErro(
                f"{nome} não existe nos stubs. Rode tools/gerar_stubs.py."
            ) from None

    def _enum(self, metodo: str, campo: str, nome: str) -> int:
        """Valor de enum resolvido pelo DESCRIPTOR do campo, não pelo nome do enum.

        Os enums do MCAPI são quase todos ANINHADOS no RequestBody a que pertencem
        (`GetBinsRequestBody.GetBinsFlag`), e uns poucos são globais. Perguntar ao campo
        resolve os dois casos e sobrevive a uma regeração de stub que mude a estrutura.
        """
        corpo = self._tipo(f"{metodo}RequestBody")
        fd = corpo.DESCRIPTOR.fields_by_name.get(campo)
        if fd is None or fd.enum_type is None:
            raise McApiErro(f"{metodo}.{campo} não é campo de enum")
        valor = fd.enum_type.values_by_name.get(nome)
        if valor is None:
            validos = ", ".join(fd.enum_type.values_by_name)
            raise McApiErro(
                f"{nome!r} inválido para {metodo}.{campo} — use um de: {validos}"
            )
        return valor.number

    def _pedido(self, metodo: str, **campos):
        req = self._tipo(f"{metodo}Request")()
        req.body.CopyFrom(self._tipo(f"{metodo}RequestBody")(**campos))
        # Header VAZIO de propósito: o backend não valida token. Preencher
        # company_id/access_token com palpite só criaria a ilusão de autenticação.
        req.header.SetInParent()
        return req

    def _stub(self, metodo: str, req, fluxo: bool):
        assert self._canal is not None, "use MediaComposer como context manager"
        fabrica = self._canal.unary_stream if fluxo else self._canal.unary_unary
        return fabrica(
            SERVICO + metodo,
            request_serializer=type(req).SerializeToString,
            response_deserializer=self._tipo(f"{metodo}Response").FromString,
        )

    def _chamar(self, metodo: str, _timeout: float | None = None, **campos):
        req = self._pedido(metodo, **campos)
        _esperar_o_monitor(metodo)
        try:
            return self._stub(metodo, req, fluxo=False)(
                req, timeout=_timeout or self.timeout
            )
        except grpc.RpcError as e:
            raise self._traduzir(e, metodo) from None
        finally:
            # ⚠️ Marca mesmo quando o carregar devolve erro: "Some mobs was skipped" também
            #    sai quando PARTE dos mobs carregou, e o monitor pode estar se mexendo.
            _marcar_carregamento(metodo)

    def _fluxo(self, metodo: str, _timeout: float | None = None, **campos) -> list:
        req = self._pedido(metodo, **campos)
        try:
            return list(
                self._stub(metodo, req, fluxo=True)(req, timeout=_timeout or self.timeout)
            )
        except grpc.RpcError as e:
            raise self._traduzir(e, metodo) from None

    @staticmethod
    def _traduzir(e: grpc.RpcError, metodo: str) -> McApiErro:
        """Erro do gRPC → erro nosso, preservando a distinção que muda o que a UI diz.

        "O Media Composer não está aberto" é rotina e vira aviso; "a chamada falhou" é
        defeito. Achatar os dois num só faz o editor procurar o problema no lugar errado.
        """
        codigo = e.code()
        if codigo == grpc.StatusCode.UNIMPLEMENTED:
            return McApiNaoImplementado(
                f"{metodo} não existe nesta versão do Media Composer"
            )
        if codigo == grpc.StatusCode.UNAVAILABLE:
            return McApiFechado(
                f"o Media Composer não atendeu em {metodo} — ele está aberto?"
            )
        if codigo == grpc.StatusCode.DEADLINE_EXCEEDED:
            # ⚠️ NÃO é "fechado". O MC pode estar aberto e ocupado — ou a chamada é
            # SERVER-STREAMING e foi feita como unária, que é como este erro apareceu na
            # primeira vez. Dizer "está aberto?" mandaria depurar o lugar errado.
            if _dialogo_na_tela():
                return McApiErro(f"{metodo} não respondeu porque há um diálogo do Media Composer na tela, e a API dele fica muda enquanto ele estiver aberto. Resolva o diálogo e tente de novo.")
            return McApiErro(
                f"{metodo} não respondeu no prazo. O Media Composer pode estar ocupado — "
                f"ou a chamada é de fluxo e foi feita como unária."
            )
        return McApiErro(f"{metodo} falhou: {codigo.name} — {e.details()}")

    # ── as chamadas ──────────────────────────────────────────────────────────

    def esta_vivo(self) -> bool:
        """Há um Media Composer atendendo? Nunca levanta — é pergunta, não ação."""
        try:
            self._chamar("GetAppInfo", _timeout=3.0)
            return True
        except McApiErro:
            return False

    def info(self) -> dict:
        """Identidade do Media Composer que está atendendo.

        ⭐ `ocupado` vem do `app_busy_status` e vale mais do que parece: **qualquer
        diálogo modal trava a API inteira**, inclusive um erro que o próprio MC
        levantou. Perguntar antes de uma operação longa distingue "o app não responde"
        de "há um modal na tela esperando o editor" — que é a causa comum e a única com
        conserto do lado de cá.
        """
        c = self._chamar("GetAppInfo").body
        return {
            "nome": c.app_name,
            "versao": c.app_version,
            "sdk": c.sdk_version,
            "licenca": c.license_type,
            "ocupado": c.app_busy_status,
        }

    def projeto(self, recarregar: bool = False) -> dict:
        """O projeto aberto. O `caminho` é a PASTA, e é ele que torna uma bin relativa.

        ⚠️ **Cacheado na conexão.** Cada chamada custa o piso de ~500 ms, e o cálculo do
        caminho relativo precisa disto uma vez POR BIN: sem cache, ler 13 bins gastava
        6,5 s só perguntando de novo onde fica um projeto que não mudou.
        """
        if self._projeto is not None and not recarregar:
            return self._projeto
        c = self._chamar("GetOpenProjectInfo").body
        self._projeto = {
            "caminho": c.path,
            "tipo": c.project_type,
            "largura": c.raster_width,
            "altura": c.raster_height,
            # ⚠️ `frame_rate` e `drop_frame` não são enfeite de relatório: todo in/out
            # que este produto calcula é timecode, e timecode sem a taxa e sem saber se
            # é drop-frame é um número que parece certo e cai no lugar errado.
            #
            # ⚠️ O campo vem como MENSAGEM `{num, den}`, não escalar — 24000/1001, não
            # 23.976. Guardamos a fração exata E o decimal: a fração é o que serve para
            # contar frame, o decimal é o que serve para o humano ler. Arredondar cedo
            # é como se perde um frame a cada 1001.
            "fps": {"num": c.frame_rate.num, "den": c.frame_rate.den},
            "fps_aprox": round(c.frame_rate.num / c.frame_rate.den, 3)
            if c.frame_rate.den
            else None,
            "drop_frame": bool(c.drop_frame),
        }
        return self._projeto

    def caminho_relativo_da_bin(self, absoluto: str) -> str:
        """Caminho absoluto de bin → a forma que o `GetListOfBinItems` aceita.

        ⚠️ Três formas testadas, só UMA funciona para bin em subpasta. Só o nome do
        arquivo e o caminho absoluto devolvem "Bin is not open"; o que funciona é o
        caminho relativo À PASTA DO PROJETO, subpasta incluída.

        Os três erros devolvem a MESMA mensagem, que manda procurar o estado da bin
        quando o problema é o caminho.
        """
        # ⚠️ Sem `.avb` a API responde o mesmo "Bin is not open" (medido com `CENAS/C07`).
        absoluto = absoluto if absoluto.lower().endswith(".avb") else absoluto + ".avb"
        return relativo_ao_projeto(absoluto, self.projeto().get("caminho") or "") or absoluto

    def esta_na_lixeira(self, absoluto: str) -> bool:
        partes = absoluto.replace("\\", "/").lower().split("/")
        return PASTA_DA_LIXEIRA in partes[:-1]

    def bins(self, incluir_lixeira: bool = False) -> list[str]:
        """Caminhos absolutos das bins do projeto aberto.

        ⚠️ Sem `request_flag` a resposta vem VAZIA — e isso não significa projeto sem
        bins.

        ⚠️ **A lixeira fica de fora por padrão, e não é caso de borda:** medido num
        projeto real, **21 das 48 bins** estavam dentro de `Trash/`. Pior que o volume é
        a AMBIGUIDADE — o mesmo nome existindo vivo e na lixeira ao mesmo tempo, sem
        nada dizendo qual é qual. O `GetBins` não sabe filtrar isso; quem filtra somos
        nós, pelo caminho.
        """
        flag = self._enum("GetBins", "request_flag", "AllTypes")
        caminhos = [
            r.body.absolute_path
            for r in self._fluxo("GetBins", request_flag=[flag])
            if r.body.absolute_path
        ]
        if incluir_lixeira:
            return caminhos
        return [c for c in caminhos if not self.esta_na_lixeira(c)]

    def colunas_do_mob(self, mob_id: str) -> dict[str, str]:
        """As colunas da bin para um MobID — `Name`, `Tracks`, `Start`, o que houver.

        ⚠️⚠️ **`GetMobInfo` é rpc de FLUXO, e cada parte traz UMA coluna** (um par
        `column_name`/`column_value`, não duas listas). Chamada como unária, ela estoura o
        prazo com uma mensagem que culpa o Media Composer por estar ocupado — e quem lê
        `column_name` como lista itera os CARACTERES do nome da coluna, obtendo
        `C`, `o`, `l`, `o`, `r` sem erro nenhum. Os dois enganos foram cometidos aqui
        antes de esta função existir.

        ⭐ É o que dá NOME ao que o editor arrastou: o payload do arrasto traz o MobID e
        nada mais (ver `plugins/avid-panel-sdk/arrastar.md` no banco).
        """
        return {
            parte.body.column_name: parte.body.column_value
            for parte in self._fluxo("GetMobInfo", mob_id=mob_id,
                                     only_visible_columns=True)
        }

    def itens_da_bin(
        self,
        bin_relativa: str,
        tipos: tuple[str, ...] = ("masterClips",),
        apenas_selecionados: bool = False,
    ) -> list[ItemDeBin]:
        """Lista o conteúdo de uma bin. `bin_relativa` é relativa à pasta do projeto.

        ⚠️ **Bin ABERTA na interface não precisa de `OpenBin`** — medido. O
        "Bin is not open" é quase sempre sobre a FORMA DO CAMINHO, não sobre o estado
        da bin, e a mensagem manda depurar o lugar errado.

        `apenas_selecionados` filtra DENTRO do Media Composer: a chamada custa o mesmo
        (é o piso de latência), mas uma bin com centenas de clipes não atravessa inteira
        a ponte só para o app descartar quase tudo.
        """
        flags = [self._enum("GetListOfBinItems", "bin_flags", t) for t in tipos]
        respostas = self._fluxo(
            "GetListOfBinItems",
            bin_relative_path=bin_relativa,
            bin_flags=flags,
            only_selected_flag=apenas_selecionados,
        )
        return [
            ItemDeBin(
                nome=r.body.mob_name,
                mob_id=r.body.mob_id,
                selecionado=bool(r.body.mob_selected),
            )
            for r in respostas
            if r.body.mob_name or r.body.mob_id
        ]
