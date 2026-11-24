"""
avid/mcapi.py — fala com o Media Composer aberto.

## O que é isto

O Media Composer hospeda um serviço gRPC (`mcapi.MCAPI`) em **`[::1]:9100`** e —
descoberta do banco de NLEs, confirmada aqui — **o backend não valida token**. Quem
exige credencial é o *gateway* (4920/4930), que serve os painéis `.avpi`; o backend
direto, em loopback, aceita chamadas com o header vazio.

Isso decide a arquitetura da integração com o Avid, e ela é o INVERSO da do
Premiere e da do Resolve: lá um painel dentro do NLE chama o Órbita; aqui o
**Órbita chama o Media Composer**. Não é preciso painel nenhum para o app ler a
seleção de uma bin ou abrir uma timeline.

⚠️ **Só loopback, e isso não é configurável de fora.** Qualquer processo local
dirige o Media Composer sem credencial — é uma propriedade do produto da Avid, não
uma escolha nossa. Não expomos isso em lugar nenhum: o Órbita é o cliente, nunca a
ponte.

## O contrato

Todo request é `{header, body}` e toda response é `{header, body}`. O `header` de
ida carrega a autenticação do gateway (vazia aqui); o de volta traz `task_id`,
`status` e `progress`. Cinco chamadas são *server-streaming*: a resposta vem em
pedaços, um item por mensagem, e o `status` do último diz se terminou.

O `.proto` veio do banco de NLEs, que o extraiu por reflection do próprio MC —
não existe SDK público. Ver `tools/gen_mcapi_stubs.py`.

## ⚠️ O MobID vem em DUAS representações

O que a API devolve **não é** o que o pyavb escreve. Medido nos dois lados do mesmo
clipe:

    API   : 060a2b34…13-000000-1a8edcf31260a306-7860d011e5e7-034e
    pyavb : 060a2b34…13000000 f3dc8e1a 601206a3 7860d011 e5e7034e

Os 16 bytes finais são um GUID de endianness MISTA (campos de 4, 2 e 2 bytes em
little-endian, o resto em big). Em vez de trocar bytes na mão, montamos a forma
URN e deixamos o pyavb interpretá-la — ver `mob_id_para_pyavb`. Passar o hex da API
direto para o writer geraria uma timeline que aponta para mobs inexistentes, e o
Media Composer estoura em `PlayPipe::DoComp()` com "missing mob".
"""

from __future__ import annotations

# ⛔⛔ Antes de QUALQUER `import grpc` (revisão de 2026-11-07, medido): com os "fork handlers" do gRPC ligados (o padrão
#    do grpcio 1.83), um subprocesso aberto (ffmpeg, ffprobe, `claude -p`, o app) enquanto canais de gRPC abrem e
#    fecham para o MC prende o fork por ~62 s SEGURANDO O GIL: o processo inteiro para, a porta não atende, e o
#    supervisor do app o mata ("parou de responder… processo vivo"). Reproduzido 3 de 3 (e no código real do Assist
#    contra o MC); com `0`, 0 de 3 em 40 mil forks. Nenhum filho nosso usa gRPC, então não há o que perder.
import os as _os

_os.environ.setdefault("GRPC_ENABLE_FORK_SUPPORT", "0")

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path, PurePath

log = logging.getLogger("delapraca.avid.mcapi")

BACKEND_PADRAO = "[::1]:9100"

# ⚠️ Teto para as chamadas que fazem o Media Composer LER OU GRAVAR uma bin inteira
# (`OpenBin`, `CloseBin`), e não para as que só perguntam.
#
# Cinco minutos é folgado de propósito: o custo de esperar demais é o editor esperar; o
# de esperar de menos é uma decisão errada tomada com confiança — ver `_chamar`. A
# duração real depende do tamanho da bin e do disco (aqui, um SSD externo exFAT), então
# não há número "certo" a cravar; há um que não corta a operação pela metade.
TEMPO_DE_ARQUIVO_S = 300.0

# Cada chamada é um caminho no serviço. Escritos aqui em vez de virem de um stub
# gerado: são cinco, e assim ficam visíveis e greppáveis.
_SERVICO = "/mcapi.MCAPI/"

# ⛔⛔ **`LoadMobsIntoViewer` → `GetViewerMobs` → `CloseBin`, colados, DERRUBA o Media
# Composer.** MEDIDO pelo Ciclo Assist em 2026-09-13 (MC 2025.6.58781,
# `spikes/fechar_bin_com_monitor.py`, `qual_passo_derruba.py`): `ACCESS_VIOLATION` na
# thread principal, **5 de 5**. Com 3 s de espera depois do carregar antes de
# consultar/fechar: **0 de 11**. Banco: `plugins/avid-panel-sdk/dados/docommand-
# comandos.md`, linha "Carregar SEQUÊNCIA na Record".
#
# O MC não fecha: mostra um diálogo e segue depois do OK, e a API fica MUDA até
# alguém clicar — o que um cliente lê como "ocupado", não como "caiu".
#
# ⇒ Depois de um `LoadMobsIntoViewer`, `GetViewerMobs` e `CloseBin` esperam o monitor
#    assentar. Vale para o PROCESSO inteiro, não para uma conexão: `fechar_bin` e
#    `carregar_no_monitor` podem vir de instâncias de `MediaComposer` diferentes, e a
#    sequência perigosa cruza essas instâncias do mesmo jeito.
ASSENTAR_DEPOIS_DE_CARREGAR_S = 3.0
_ESPERAM_O_MONITOR = frozenset({"GetViewerMobs", "CloseBin"})
_trava_do_monitor = threading.Lock()
_carregou_em: float | None = None


def _esperar_o_monitor(metodo: str) -> None:
    global _carregou_em
    with _trava_do_monitor:
        if metodo == "LoadMobsIntoViewer":
            return
        if metodo not in _ESPERAM_O_MONITOR or _carregou_em is None:
            return
        falta = ASSENTAR_DEPOIS_DE_CARREGAR_S - (time.monotonic() - _carregou_em)
    if falta > 0:
        log.info("%s espera %.1f s: um monitor acabou de carregar", metodo, falta)
        time.sleep(falta)


def _marcar_carregamento(metodo: str) -> None:
    global _carregou_em
    if metodo == "LoadMobsIntoViewer":
        with _trava_do_monitor:
            _carregou_em = time.monotonic()


class McApiError(Exception):
    """O Media Composer não atendeu, ou atendeu com erro."""


class McApiIndisponivel(McApiError):
    """Não há Media Composer escutando. É o caso normal de 'não está aberto'."""


class McApiNaoImplementado(McApiError):
    """Este Media Composer não tem esse rpc. **Diferença de versão, não defeito.**

    ⭐ Medido: `GetListOfWindows` responde normalmente no MC 25.12 e devolve
    `UNIMPLEMENTED` no **25.6** — a ausência foi confirmada por enumeração dos
    símbolos do binário, não é permissão nem escopo de `usesApi`.

    Merece exceção **própria**, separada de "a chamada falhou", porque a resposta
    certa é diferente: uma falha é defeito e deve aparecer; um rpc que não existe
    naquela build é uma capacidade a menos, e o app tem de seguir sem ela.

    ⚠️ **A armadilha ao degradar** — a que custou caro no Órbita: tratar o rpc
    ausente como *"nenhuma bin está aberta"* **inverte o resultado**. O filtro zera
    a lista e a seleção volta VAZIA, como se o editor não tivesse marcado nada. O
    certo é `None` = *"não dá para saber"*, e não filtrar.

    **Regra geral:** num SDK cuja versão você não controla, todo rpc de conveniência
    precisa de um caminho sem ele — e o caminho sem ele não pode ser mais restritivo
    que o com.
    """


@dataclass
class BinItem:
    name: str
    mob_id: str          # como a API devolve (ver o aviso no topo)
    selected: bool = False


@dataclass
class Master:
    """Um master clip do projeto, já no formato que o writer consome."""

    name: str
    mob_id: str                      # JÁ convertido para o hex do pyavb
    length_frames: int | None = None


def mob_id_valido(mob_id: str) -> bool:
    """É um MobID na representação "de fora"? (API, `ffprobe`, ou payload de arrasto.)

    ⚠️ **NÃO valide pela pontuação.** O mesmo MobID aparece com agrupamentos de hífen
    diferentes conforme a superfície que o entrega:

        `ffprobe`         …0f1013-000000-1a8edcf31260a306-7860d011-e5e7034e   (26-6-16-8-8)
        API e drop        26-6-16-12-4   (o regex do painel do ESION exige este; o `GetBinFromMob` também)

    Os dois somam **64 dígitos hexadecimais**, e é isso que se checa. Um validador que
    crave os hifens recusa MobID legítimo, e o sintoma é o pior possível para o editor:
    *"o clipe que arrastei não é reconhecido"*, sem nada errado com o clipe.
    """
    cru = (mob_id or "").strip()
    if cru[:2].lower() == "0x":
        cru = cru[2:]
    h = [c for c in cru if c in "0123456789abcdefABCDEF"]
    # ⚠️ Contar hexadecimais não basta: `"z" * 64` não tem nenhum, mas
    # `"g0" * 32` tem 32 — o texto tem de ser SÓ hexadecimais e separadores.
    if any(c not in "0123456789abcdefABCDEF-. " for c in cru):
        return False
    return len(h) == 64


def mob_id_para_api(mob_id: str) -> str:
    """MobID "de fora" (qualquer agrupamento, `0x`, URN, maiúsculas) → `26-6-16-12-4`, a forma da pergunta.

    ⛔ O `GetBinFromMob` é sensível ao AGRUPAMENTO (banco `avid-panel-sdk/README.md` §GetBinFromMob, MC 25.6):
    `26-6-16-12-4` acha; 64 hex corridos, `26-6-16-8-8` (o do `ffprobe`), a URN e `0x`+hex devolvem `None`, CALADO.
    Validar aceita qualquer forma (`mob_id_valido`); perguntar normaliza — aqui. Mesma ordem de dígitos: o hex
    `bytes_le` do pyavb NÃO serve (é outra ordem; esse vai por `sessao_export.mob_id_da_api`).
    """
    cru = (mob_id or "").strip().lower()
    # ⚠️ Tirar o prefixo ANTES do filtro: o `e` de `smpte` e o `d` de `umid` passam e o total vira 66.
    if cru.startswith("urn:smpte:umid:"):
        cru = cru[len("urn:smpte:umid:"):]
    elif cru[:2] == "0x":
        cru = cru[2:]
    h = "".join(c for c in cru if c in "0123456789abcdef")
    if len(h) != 64:
        raise McApiError(f"MobID com tamanho inesperado ({len(h)} dígitos): {mob_id!r}")
    return f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"


def mob_id_para_pyavb(mob_id_api: str) -> str:
    """MobID "de fora" → o hex `bytes_le` que o writer usa.

    Serve às DUAS fontes que entregam a mesma representação, e nenhuma delas é a
    do pyavb:
      - a **API do Media Composer** (`GetListOfBinItems`), separada por hífens;
      - o **próprio arquivo OP-Atom** (`material_package_umid` do `ffprobe`), com
        prefixo `0x`. Este é o mais interessante: o arquivo de mídia carrega o
        MobID do master, então dá para autorar a timeline sem perguntar nada ao
        Media Composer.

    Monta a forma URN (oito grupos de 4 bytes) e deixa o **pyavb** fazer a
    conversão de endianness. Trocar os bytes à mão aqui seria reimplementar — com
    chance de errar — algo que a biblioteca já sabe fazer.
    """
    from avb.mobid import MobID

    cru = mob_id_api.strip()
    # ⚠️ O `0x` do ffprobe: sem tirá-lo, o `0` sobrevive ao filtro de hexadecimais
    # (o `x` não) e o valor sai com 65 dígitos e todos os bytes deslocados.
    if cru[:2].lower() == "0x":
        cru = cru[2:]
    h = "".join(c for c in cru if c in "0123456789abcdefABCDEF").lower()
    if len(h) != 64:
        raise McApiError(f"MobID com tamanho inesperado ({len(h)} dígitos): {mob_id_api!r}")
    urn = "urn:smpte:umid:" + ".".join(h[i:i + 8] for i in range(0, 64, 8))
    return MobID(mobid=urn).bytes_le.hex()


_RPCS: dict[str, tuple[float, frozenset[str] | None]] = {}   # endereço → (quando, RPC da reflection); ver `rpcs`


def _varint(dados: bytes, i: int) -> tuple[int, int]:
    """Um varint do formato de fio do protobuf: (valor, próxima posição)."""
    valor, desloc = 0, 0
    while True:
        b = dados[i]
        i += 1
        valor |= (b & 0x7F) << desloc
        if not b & 0x80:
            return valor, i
        desloc += 7


class MediaComposer:
    """Conexão com um Media Composer aberto. Use como context manager."""

    def __init__(self, endereco: str = BACKEND_PADRAO, timeout: float = 20.0):
        self.endereco = endereco
        self.timeout = timeout
        self._canal = None
        self._projeto: dict | None = None

    # ── ciclo de vida ────────────────────────────────────────────────────────

    def __enter__(self) -> "MediaComposer":
        # ⭐ Fase 4 do plano um app só, passo 4 (2026-11-07): este módulo NÃO abre conexão com o MC — fala pelo
        #   núcleo do Ciclo Assist (`canal_do_nucleo.py`), e a pausa do monitor dele vale para o app inteiro.
        from .canal_do_nucleo import CanalDoNucleo

        self._canal = CanalDoNucleo("conformar")
        return self

    def __exit__(self, *exc) -> None:
        if self._canal is not None:
            self._canal.close()
            self._canal = None

    # ── plumbing ─────────────────────────────────────────────────────────────

    def _msg(self, nome: str):
        from avid.proto import mcapi_types_pb2 as pb

        return getattr(pb, nome)

    def _enum(self, metodo: str, campo: str, nome: str) -> int:
        """Valor de um enum, resolvido pelo DESCRIPTOR do campo.

        Os enums do MCAPI são quase todos ANINHADOS dentro do RequestBody a que
        pertencem (`GetListOfBinItemsRequestBody.BinItemFlags`,
        `GetBinsRequestBody.GetBinsFlag`), e uns poucos são globais (`ViewerType`).
        Perguntar ao campo em vez de escrever o nome do enum resolve os dois casos
        e sobrevive a uma regeração do stub que mude a estrutura.
        """
        corpo = self._msg(f"{metodo}RequestBody")
        fd = corpo.DESCRIPTOR.fields_by_name.get(campo)
        if fd is None or fd.enum_type is None:
            raise McApiError(f"{metodo}.{campo} não é um campo de enum")
        valor = fd.enum_type.values_by_name.get(nome)
        if valor is None:
            validos = ", ".join(fd.enum_type.values_by_name)
            raise McApiError(f"{nome!r} não é válido para {metodo}.{campo} ({validos})")
        return valor.number

    def _pedido(self, metodo: str, **campos):
        req = self._msg(f"{metodo}Request")()
        corpo = self._msg(f"{metodo}RequestBody")(**campos)
        req.body.CopyFrom(corpo)
        # O header vai VAZIO de propósito: o backend não valida token. Preencher
        # `company_id`/`access_token` com palpite só criaria a ilusão de auth.
        req.header.SetInParent()
        return req

    def _chamar(self, metodo: str, _timeout: float | None = None, **campos):
        """Chamada unária. `_timeout` sobrepõe o teto padrão para ESTA chamada.

        ⚠️⚠️ **O teto padrão vale para CONSULTA; operação de ARQUIVO precisa de outro.**
        O padrão de 20 s foi dimensionado para perguntas (`GetMobInfo`, `GetListOf*`),
        que custam centenas de milissegundos. `CloseBin` e `OpenBin` não perguntam nada:
        eles fazem o Media Composer **gravar ou ler a bin inteira**, e numa bin com
        dezenas de masters AMA isso passa de meio minuto com o editor olhando um modal
        *"Closing bin window, please wait while the bin is saved"*.

        ⭐ E o modo de falha não é "demorou": é **silencioso e destrutivo de resultado**.
        Medido em 2026-08-16 — o `CloseBin` estourou os 20 s, o chamador concluiu *"não
        consegui fechar"* e gravou o relink **com outro nome**, enquanto o MC seguia
        fechando a bin normalmente. O editor ficou com DUAS bins, a certa não estava
        aberta, e nada acusou erro. Prazo curto demais não devolve erro honesto: devolve
        uma decisão errada tomada com confiança.
        """
        import grpc

        req = self._pedido(metodo, **campos)
        stub = self._canal.unary_unary(
            _SERVICO + metodo,
            request_serializer=type(req).SerializeToString,
            response_deserializer=self._msg(f"{metodo}Response").FromString,
        )
        _esperar_o_monitor(metodo)
        try:
            return stub(req, timeout=_timeout or self.timeout)
        except grpc.RpcError as e:
            raise self._traduzir(e, metodo) from None
        finally:
            # ⚠️ Marca mesmo quando o carregar devolve erro: "Some mobs was skipped"
            # também sai quando PARTE dos mobs carregou, e o monitor pode estar se
            # mexendo do mesmo jeito.
            _marcar_carregamento(metodo)

    def _fluxo(self, metodo: str, **campos):
        """Chamada server-streaming: devolve a lista de respostas."""
        import grpc

        req = self._pedido(metodo, **campos)
        stub = self._canal.unary_stream(
            _SERVICO + metodo,
            request_serializer=type(req).SerializeToString,
            response_deserializer=self._msg(f"{metodo}Response").FromString,
        )
        try:
            return list(stub(req, timeout=self.timeout))
        except grpc.RpcError as e:
            raise self._traduzir(e, metodo) from None

    @staticmethod
    def _traduzir(e, metodo: str) -> McApiError:
        """Erro do gRPC → erro nosso, com a distinção que importa para a UI:
        'o Media Composer não está aberto' NÃO é a mesma coisa que 'a chamada
        falhou'. A primeira é rotina e vira aviso; a segunda é defeito."""
        import grpc

        codigo = e.code()
        if codigo == grpc.StatusCode.UNIMPLEMENTED:
            # Versão do MC sem esse rpc. Ver `McApiNaoImplementado`.
            return McApiNaoImplementado(
                f"{metodo} não existe nesta versão do Media Composer"
            )
        if codigo == grpc.StatusCode.UNAVAILABLE:
            return McApiIndisponivel(
                getattr(e, "frase", "")
                or f"o Media Composer não está atendendo em {metodo} — ele está aberto?"
            )
        if codigo == grpc.StatusCode.DEADLINE_EXCEEDED:
            # ⚠️ NÃO confundir com "fechado". O MC pode estar aberto e ocupado —
            # ou a chamada pode ser SERVER-STREAMING e ter sido feita como unária,
            # que é como este erro apareceu na primeira vez: o app estava vivo, a
            # chamada é que estava errada. Dizer "está aberto?" mandaria procurar
            # o problema no lugar errado.
            return McApiError(
                f"{metodo} não respondeu no prazo. O Media Composer pode estar "
                f"ocupado — ou a chamada é de fluxo e foi feita como unária."
            )
        return McApiError(f"{metodo} falhou: {codigo.name} — {e.details()}")

    # ── as chamadas que a integração usa ─────────────────────────────────────

    def esta_vivo(self) -> bool:
        """Há um Media Composer atendendo? Nunca levanta — é uma pergunta."""
        try:
            self.info()
            return True
        except McApiError:
            return False

    def rpcs(self) -> frozenset[str] | None:
        """Os RPC que ESTE Media Composer implementa, pela reflection do 9100 — ou None se ela não respondeu.

        ⭐ Zero efeito colateral (é o próprio servidor descrevendo o serviço). O MC 24.6 implementa 47 dos 60 RPC do
        contrato 25.12: faltam `DoCommand`/`GetListOfCommands`/`IsCommandsEnabled`, o transporte (`StartPlay`,
        `SetPosition`…), as janelas (`GetListOfWindows`, `ShowWindow`…), `DeleteMarkers` e `GetListOfJobQueues`
        (banco avid-panel-sdk/ativar-no-2021-ftf.md §Subconjunto; medido de novo em 2026-10-18). Saber ANTES deixa a
        rota avisar com a razão certa — no 24.6 a coleta caía em "não há sequência na timeline" porque o
        `GetViewerMobs` de lá não preenche o `view_type`.

        ⚠️ Sem o pacote `grpcio-reflection`: um pedido (`file_containing_symbol`) montado e lido à mão no formato de
        fio do protobuf, e o `FileDescriptorProto` que volta é lido pelo `protobuf` que já temos. Guardado por 30 s
        por endereço — o painel abre uma conexão por pedido, e o editor pode trocar de versão sem fechar o app.
        """
        guardado = _RPCS.get(self.endereco)
        if guardado and time.monotonic() - guardado[0] < 30:
            return guardado[1]
        import grpc
        from google.protobuf import descriptor_pb2

        def campos(dados: bytes):
            i = 0
            while i < len(dados):
                chave, i = _varint(dados, i)
                numero, tipo = chave >> 3, chave & 7
                if tipo == 2:
                    n, i = _varint(dados, i)
                    yield numero, dados[i:i + n]
                    i += n
                elif tipo == 0:
                    _, i = _varint(dados, i)
                else:                       # a resposta da reflection só tem varint e LEN
                    return

        alvo = b"mcapi.MCAPI"
        pedido = b"\x22" + bytes([len(alvo)]) + alvo        # campo 4: file_containing_symbol
        fluxo = self._canal.stream_stream(
            "/grpc.reflection.v1alpha.ServerReflection/ServerReflectionInfo",
            request_serializer=lambda b: b, response_deserializer=lambda b: b)
        try:
            resposta = next(iter(fluxo(iter([pedido]), timeout=self.timeout)))
        except (grpc.RpcError, StopIteration) as e:
            log.info("a reflection do Media Composer não respondeu: %s", e)
            return None
        nomes: set[str] = set()
        for numero, corpo in campos(resposta):
            if numero != 4:                  # file_descriptor_response
                continue
            for n2, proto in campos(corpo):
                if n2 == 1:
                    fd = descriptor_pb2.FileDescriptorProto.FromString(proto)
                    for s in fd.service:
                        if s.name == "MCAPI":
                            nomes.update(m.name for m in s.method)
        resultado = frozenset(nomes) or None
        _RPCS[self.endereco] = (time.monotonic(), resultado)
        return resultado

    def tem(self, metodo: str) -> bool:
        """Este MC implementa `metodo`? Sem reflection, supõe que sim (o erro do próprio RPC diz o resto)."""
        r = self.rpcs()
        return r is None or metodo in r

    def info(self) -> dict:
        r = self._chamar("GetAppInfo")
        return {"app": r.body.app_name, "version": r.body.app_version,
                "sdk": r.body.sdk_version, "license": r.body.license_type}

    def sequencia_no_record(self) -> dict | None:
        """A sequência aberta no monitor RECORD — `{"mob_id", "quadro", "tc"}` —, ou None se o Record está vazio.

        ⭐ É a timeline "de dentro" do botão "Carregar a sequência aberta" (organograma "Um painel, três NLEs",
        2026-10-12): só há UMA no Record, então não há ambiguidade de seleção. `GetViewerMobs` traz um item por
        monitor; o do Source vem sem `view_type` (é o 0 do enum, banco avid-panel-sdk/copia-da-timeline.md), o do
        Record é `view_type = 1`.
        """
        from avid.proto import mcapi_types_pb2 as pb
        r = self._chamar("GetViewerMobs")
        for m in r.body.mobs:
            if m.view_type == pb.Record and m.mob_id:
                return {"mob_id": m.mob_id, "quadro": m.current_frame, "tc": m.current_timecode}
        if self.tem("MakeViewerActive"):
            return None
        # ⚠️ MC 2024 (24.6, medido em 2026-10-18): o `GetViewerMobs` NÃO preenche o `view_type` — a timeline no
        # Record vem como 0, que no 25.x é o Source. Lá vale o mob do monitor que for SEQUÊNCIA (conferida na bin
        # dele); mais de uma é ambíguo e o editor decide pelo arrasto ou pelo seletor.
        sequencias = []
        for m in r.body.mobs:
            caminho = m.mob_id and self.bin_do_mob(m.mob_id)
            if not caminho:
                continue
            try:
                # sem abrir: a bin de quem está no monitor está aberta (fechá-la tira a timeline do monitor — medido)
                rel = self.caminho_relativo_da_bin(caminho)
                if any(s.mob_id == m.mob_id for s in self.itens_da_bin(rel, flags=("sequences",))):
                    sequencias.append(m)
            except McApiError:
                continue
        if len(sequencias) > 1:
            raise McApiError("há mais de uma sequência nos monitores — arraste a timeline para o painel")
        if sequencias:
            m = sequencias[0]
            return {"mob_id": m.mob_id, "quadro": m.current_frame, "tc": m.current_timecode}
        return None

    def abrir_bin(self, caminho: str) -> None:
        """Abre uma bin no Media Composer.

        ⚠️ O caminho tem de ser ABSOLUTO ou o nome com extensão (`X.avb`);
        relativo-com-subpasta é recusado. Fato do banco de NLEs, medido.
        """
        self._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=caminho)

    def fechar_bin(self, caminho: str) -> None:
        """Fecha uma bin no Media Composer, esperando o tempo que a GRAVAÇÃO leva.

        ⚠️ Fechar bin **salva** a bin: numa com dezenas de masters AMA o Avid mostra
        *"Closing bin window, please wait while the bin is saved"* por dezenas de
        segundos. Com o teto de consulta isso vira `DEADLINE_EXCEEDED` — ver `_chamar`.
        """
        self._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=caminho)

    def projeto(self, recarregar: bool = False) -> dict:
        """Dados do projeto aberto — o `path` é a pasta, e é ele que torna um
        caminho de bin relativo.

        ⚠️ CACHEADO na conexão. Cada chamada custa o piso de ~500 ms, e
        `caminho_relativo_da_bin` precisa disto uma vez POR BIN: sem o cache, ler a
        seleção de 13 bins gastava 6,5 s só perguntando de novo onde fica o projeto
        que não mudou.
        """
        if self._projeto is not None and not recarregar:
            return self._projeto
        r = self._chamar("GetOpenProjectInfo")
        self._projeto = {"path": r.body.path, "type": r.body.project_type,
                         "width": r.body.raster_width, "height": r.body.raster_height}
        return self._projeto

    def caminho_relativo_da_bin(self, caminho_absoluto: str) -> str:
        """Caminho absoluto de bin → a forma que o `GetListOfBinItems` aceita.

        ⚠️ Três formas foram testadas contra o MC 25.12, e só UMA funciona para
        uma bin em subpasta:

            'CAM A.avb'                       → "Bin is not open"
            '/Users/…/projeto/X/CAM A.avb'    → "Bin is not open"
            'X/CAM A.avb'                     → ✅   (barra ou contrabarra)

        Ou seja: relativo À PASTA DO PROJETO, subpasta incluída. O erro é sempre o
        mesmo "Bin is not open", que manda procurar no lugar errado — parece que
        faltou abrir a bin quando na verdade o caminho é que não foi entendido.
        """
        import ntpath
        import os

        raiz = self.projeto().get("path") or ""
        # Pela FORMA do caminho, não pelo SO (matriz de plataforma, regra 3): no macOS o
        # `os.path.relpath` trata `D:\projeto\Trash\x.avb` como um nome só, e a lixeira
        # escapava do filtro (medido 2026-10-01, `tests/test_seguranca_mcapi.py`).
        from media.safepath import forma_windows
        win = forma_windows(raiz)
        try:
            rel = (ntpath if win else os.path).relpath(caminho_absoluto, raiz)
        except ValueError:
            return caminho_absoluto
        return rel if not rel.startswith("..") else caminho_absoluto

    def itens_da_bin(self, bin_relativo: str, flags=("masterClips",),
                     apenas_selecionados: bool = False) -> list[BinItem]:
        """Lista o conteúdo de uma bin.

        `bin_relativo` é relativo à pasta do projeto (ver `caminho_relativo_da_bin`).

        ⚠️ **Uma bin ABERTA NA INTERFACE não precisa de `abrir_bin`** — medido. O
        `"Bin is not open"` que o Media Composer devolve é quase sempre sobre a
        FORMA DO CAMINHO, não sobre o estado da bin, e essa mensagem manda depurar
        o lugar errado. Só bins fechadas precisam do `abrir_bin`, e pular a chamada
        onde ela não é necessária vale metade do tempo de uma leitura de seleção.

        `apenas_selecionados` filtra NO Media Composer: o custo da chamada é o
        mesmo (o piso de latência), mas uma bin com centenas de clipes não
        atravessa inteira a ponte só para o app descartar quase tudo.

        É daqui que sai a ponte nome→MobID que o writer precisa: o Órbita não
        precisa saber onde as bins moram, ele pergunta ao Media Composer.
        """
        vals = [self._enum("GetListOfBinItems", "bin_flags", f) if isinstance(f, str)
                else f for f in flags]
        respostas = self._fluxo("GetListOfBinItems",
                                bin_relative_path=bin_relativo, bin_flags=vals,
                                only_selected_flag=apenas_selecionados)
        itens = []
        for r in respostas:
            if r.body.mob_name or r.body.mob_id:
                itens.append(BinItem(name=r.body.mob_name, mob_id=r.body.mob_id,
                                     selected=bool(r.body.mob_selected)))
        return itens

    def bins(self, flags=("AllTypes",), incluir_lixeira: bool = False) -> list[str]:
        """Caminhos absolutos das bins do projeto aberto.

        ⚠️ Sem `request_flag` a resposta vem VAZIA — não é 'projeto sem bins'.

        **A LIXEIRA FICA DE FORA por padrão.** Bin excluída não é bin: não deve
        aparecer num seletor nem ser lida atrás de master. `GetBins` não sabe
        filtrar isso (os `request_flag` são `AllTypes`/`BinType`/`ScriptType`/
        `VolumeType`/`OnlyOpen`), então quem filtra somos nós, pelo caminho — ver
        `esta_na_lixeira`.

        ⚠️ **Não é caso de borda.** Medido num projeto real (fork Órbita/Assist anterior, 2026-08-18): 21 de 48 bins estavam sob `Trash/`, e algumas com o
        MESMO nome de uma bin viva — sem filtrar, `masters()` por bin pode devolver
        master de material que o editor já jogou fora. Quem precisar de tudo mesmo
        assim pede `incluir_lixeira=True`.
        """
        vals = [self._enum("GetBins", "request_flag", f) if isinstance(f, str)
                else f for f in flags]
        caminhos = [r.body.absolute_path
                    for r in self._fluxo("GetBins", request_flag=vals)
                    if r.body.absolute_path]
        if incluir_lixeira:
            return caminhos
        return [c for c in caminhos if not self.esta_na_lixeira(c)]

    #: Nome da pasta de bins excluídas, como ela existe NO DISCO — em inglês mesmo
    #: com o Media Composer em português (a interface mostra "Lixeira", medido).
    PASTA_DA_LIXEIRA = "trash"

    def esta_na_lixeira(self, caminho_absoluto: str) -> bool:
        """Esta bin foi excluída (mora sob a lixeira do projeto)?

        Olha só o PRIMEIRO segmento do caminho relativo à raiz do projeto — a
        lixeira tem subpastas próprias (`Trash/SYNC/…`), então não basta comparar
        o pai direto.
        """
        rel = self.caminho_relativo_da_bin(caminho_absoluto)
        primeiro = rel.replace("\\", "/").split("/")[0]
        return primeiro.lower() == self.PASTA_DA_LIXEIRA

    def bins_abertas(self) -> list[str] | None:
        """Nomes das bins ABERTAS na interface — ou **`None` quando não dá para saber**.

        Ler a seleção custa uma chamada POR BIN (~500 ms cada, ver o topo), então
        perguntar só às que estão abertas é o que torna a leitura sob demanda
        suportável: bin fechada não tem nada selecionado.

        ⚠️ **`GetListOfWindows` não existe no MC 25.6** (`UNIMPLEMENTED`; ele responde
        normalmente no 25.12). É a **única** forma conhecida de saber quais bins estão
        abertas, então nessa versão perde-se a otimização — não a função.

        ⭐ **Por isso a resposta é de três estados, e não duas.** `None` significa *não
        dá para saber*, que é diferente de `[]` (*nenhuma bin aberta*). Confundir os
        dois inverte o comportamento: o filtro zera a lista de bins a visitar e a
        seleção volta vazia, como se o editor não tivesse marcado nada — sem erro
        nenhum. Ver `McApiNaoImplementado`.
        """
        try:
            respostas = self._fluxo("GetListOfWindows")
        except McApiNaoImplementado:
            return None
        nomes = []
        for r in respostas:
            for w in r.body.windows:
                if w.type == "Bins" and w.visibility:
                    # O MC prefixa com "* " a bin com alterações não salvas.
                    nomes.append(w.name[2:] if w.name.startswith("* ") else w.name)
        return nomes

    def selecao(self, on_progress=None, apenas_abertas: bool = True) -> dict[str, list[BinItem]]:
        """O que está selecionado AGORA, por bin. `{nome da bin: [itens]}`.

        ⚠️ **Isto é caro e é sob demanda de propósito.** Cada bin custa ~500 ms —
        o piso de latência da API do Media Composer, que não depende do que se
        pede (`GetAppInfo`, que devolve quatro strings, custa o mesmo). Um projeto
        com dez bins abertas leva uns cinco segundos.

        Por isso o Órbita **não fica observando** a seleção como o painel do
        Premiere faz: lá o painel vive dentro do NLE e a leitura é instantânea;
        aqui quem pergunta é o app, de fora. A leitura acontece quando a pessoa
        pede, e o `on_progress(feito, total, bin)` existe para que uma espera de
        alguns segundos tenha barra — processo longo sem barra é inaceitável aqui.
        """
        caminhos = self.bins()
        abertas = self.bins_abertas() if apenas_abertas else None
        if abertas is not None:
            # ⚠️ `abertas is None` = *o MC não sabe dizer* (rpc ausente nesta versão),
            # e aí NÃO se filtra: perguntar a todas é mais lento e verdadeiro. Tratar
            # a ausência como lista vazia devolveria "nada selecionado" com a bin
            # cheia de clipes marcados.
            nomes = set(abertas)
            caminhos = [c for c in caminhos
                        if Path(c).stem in nomes or Path(c).name in nomes]

        fora: dict[str, list[BinItem]] = {}
        total = len(caminhos)
        for i, caminho in enumerate(caminhos, 1):
            nome = Path(caminho).stem
            if on_progress:
                on_progress(i, total, nome)
            try:
                # `only_selected_flag` filtra NO Media Composer: uma bin com
                # centenas de clipes não atravessa a ponte inteira só para o app
                # descartar quase tudo. Ver `itens_de` para a regra do `OpenBin`.
                selecionados = self.itens_de(caminho, apenas_selecionados=True)
            except McApiError:
                # Uma bin que não abre não pode derrubar a leitura das outras.
                continue
            if selecionados:
                fora[nome] = selecionados
        return fora

    def colunas_do_master(self, mob_id_api: str) -> dict[str, str]:
        """As colunas de bin de um master, como o Media Composer as mostra.

        `GetMobInfo` é de FLUXO e devolve um par coluna/valor por mensagem.
        """
        fora: dict[str, str] = {}
        for r in self._fluxo("GetMobInfo", mob_id=mob_id_api):
            nome = r.body.column_name.strip()
            if nome:
                fora[nome] = r.body.column_value
        return fora

    def arquivo_do_master(self, mob_id_api: str, colunas: dict | None = None) -> str | None:
        """O ARQUIVO de onde este master veio, se ele ainda existir no disco.

        ⭐ **O Media Composer lembra de onde importou**: as colunas `Source Path` e
        `Source File` guardam a origem (`/Volumes/…/CAM B/` + `20240531_PANA2774.mov`).
        É por aqui que uma seleção de bin — que só tem nomes e MobIDs — vira
        caminhos de arquivo para o motor de sync.

        Devolve `None` quando o original não está mais no disco (cartão devolvido,
        projeto movido de máquina). Nesse caso o caminho é a mídia GERENCIADA:
        casar o `material_package_umid` dos OP-Atom contra a `Avid MediaFiles` —
        ver `media/opatom.py`.
        """
        col = colunas if colunas is not None else self.colunas_do_master(mob_id_api)
        pasta = (col.get("Source Path") or "").strip()
        arquivo = (col.get("Source File") or "").strip()
        nome = (col.get("Name") or mob_id_api).strip()

        # ⛔⛔ `Source File` é NOME DE ARQUIVO, não caminho — tratá-lo como caminho é um
        # furo real: o `/` do pathlib DESCARTA `pasta` quando `arquivo` é absoluto, e
        # as duas colunas são texto livre de um `.avb`/AAF de TERCEIRO. Um `Source
        # File` = `\\atacante\share\x.mov` faz `caminho.exists()` logo abaixo abrir
        # sessão SMB no Windows para o host que o autor do projeto escolheu — a
        # credencial da máquina do editor, sem o editor pedir nada. Medido e corrigido
        # no fork Órbita/Assist anterior (2026-08-27); aqui só normaliza para o nome.
        if arquivo:
            so_nome = PurePath(arquivo.replace("\\", "/")).name
            if so_nome != arquivo:
                log.warning("%s: 'Source File' vinha como CAMINHO (%r) — usando só o "
                            "nome (%r)", nome, arquivo, so_nome)
            arquivo = so_nome
        if not arquivo:
            # Caso normal para mídia transcodada pelo Avid — dispara o plano B (casar
            # UMID contra a `Avid MediaFiles`), não é erro.
            log.debug("%s: sem 'Source File' — vai para a mídia gerenciada", nome)
            return None
        caminho = Path(pasta) / arquivo if pasta else Path(arquivo)
        return str(caminho) if caminho.exists() else None

    def duracao_do_master(self, mob_id_api: str) -> int | None:
        """Duração do master EM FRAMES, ou `None` se o Media Composer não disser.

        ⚠️ O writer precisa dela para o clamp do OUT — e a falta dela não é
        cosmética: sem clamp, um clipe que passa 1 frame do fim do master faz o MC
        recusar a timeline inteira com `PMM_INSUFFICIENT_MEDIA`. Aconteceu; um
        `.mov` de 1237 frames vira um master de 1236 no transcode do Avid.

        `GetMobInfo` é de FLUXO e devolve pares coluna/valor. A coluna útil é
        `Frame Count Duration` — as outras de duração vêm em timecode.
        """
        for r in self._fluxo("GetMobInfo", mob_id=mob_id_api):
            if r.body.column_name.strip() == "Frame Count Duration":
                try:
                    return int(r.body.column_value.strip())
                except (TypeError, ValueError):
                    return None
        return None

    def itens_de(self, caminho_absoluto: str, flags=("masterClips",),
                 apenas_selecionados: bool = False) -> list[BinItem]:
        """Itens de uma bin pelo caminho ABSOLUTO, abrindo-a só se for preciso.

        ⭐ A REGRA, num lugar só (ela já se repetiu em três):
        **tenta ler sem abrir; abre e repete só se falhar.**

        Os dois lados custam:
        - uma bin ABERTA na interface responde sem `OpenBin`, e chamá-lo assim
          mesmo desperdiça ~500 ms por bin;
        - uma bin FECHADA devolve `"Bin is not open"` — e aí abrir é obrigatório.

        E `OpenBin` tem efeito VISÍVEL: ele abre a bin na tela do editor. Varrer um
        projeto atrás de masters deixava o Media Composer coberto de bins que
        ninguém pediu. Por isso a ordem é essa, e não a inversa.
        """
        rel = self.caminho_relativo_da_bin(caminho_absoluto)
        try:
            return self.itens_da_bin(rel, flags, apenas_selecionados)
        except McApiError:
            self.abrir_bin(caminho_absoluto)
            return self.itens_da_bin(rel, flags, apenas_selecionados)

    def masters(self, bins_absolutas: list[str], com_duracao: bool = True) -> list[Master]:
        """Os master clips das bins dadas, prontos para o writer.

        É a ponte que a integração precisa, e ela vem do PRÓPRIO Media Composer: o
        Órbita não abre `.avb` por fora nem precisa saber onde as bins moram.
        Já converte o MobID (ver `mob_id_para_pyavb`).

        `com_duracao=False` pula um `GetMobInfo` por master — mais rápido, mas o
        writer fica sem o clamp.
        """
        achados: list[Master] = []
        for caminho in bins_absolutas:
            for item in self.itens_de(caminho):
                if not (item.name and item.mob_id):
                    continue
                achados.append(Master(
                    name=item.name,
                    mob_id=mob_id_para_pyavb(item.mob_id),
                    length_frames=self.duracao_do_master(item.mob_id) if com_duracao else None,
                ))
        return achados

    def bin_do_mob(self, mob_id_api: str) -> str | None:
        """O caminho ABSOLUTO da `.avb` onde um mob vive — ou `None` se não der.

        ⭐ É a peça que torna a rota `.avb` transparente para o editor: o arrasto entrega
        um MobID, e daqui sai o arquivo a editar. Uma chamada, contra as ~500 ms × nº de
        bins que enumerar o projeto custaria.

        Nunca levanta: sem a bin, o serviço cai na rota AAF, que não precisa dela.
        """
        try:
            r = self._chamar("GetBinFromMob", mob_id=mob_id_para_api(mob_id_api))
        except McApiError:
            return None
        caminho = getattr(getattr(r, "body", None), "absolute_path", "") or ""
        return caminho or None

    def carregar_no_monitor(self, mob_ids: list[str], destino: str = "Record") -> None:
        """Põe mobs no monitor (Source/Record). É o 'mostre isto ao editor'."""
        self._chamar("LoadMobsIntoViewer", mob_ids=list(mob_ids),
                     view_type=self._enum("LoadMobsIntoViewer", "view_type", destino))

    def marcar(self, mob_id_api: str, quadro: int, comentario: str, cor: str = "Yellow", video: int = 1) -> None:
        """Um marcador na trilha de vídeo `video` da sequência, `quadro` desde o início dela. Pelo MobID: não precisa
        estar no Record (banco `avid-panel-sdk/ativar-no-2021-ftf.md`: `AddMarker` medido no 24.6 na TC1)."""
        rotulo = self._msg("TrackLabel")
        tipo = rotulo.DESCRIPTOR.fields_by_name["type"].enum_type.values_by_name["TRACKTYPE_PICTURE"].number
        self._chamar("AddMarker", mob_id=mob_id_api, offset=int(quadro), length=1, comment=comentario[:250],
                     color=self._enum("AddMarker", "color", cor), track_label=rotulo(type=tipo, number=int(video)))
