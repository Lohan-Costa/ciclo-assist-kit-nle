"""
avid/mcapi.py — fala com o Media Composer aberto.

## O que é isto

O Media Composer hospeda um serviço gRPC (`mcapi.MCAPI`) em **`[::1]:9100`** e —
descoberta da base de conhecimento interna, confirmada aqui — **o backend não valida token**. Quem
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

O `.proto` veio da base de conhecimento interna, que o extraiu por reflection do próprio MC —
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

from dataclasses import dataclass
from pathlib import Path, PurePath

import registro

log = registro.log(__name__)

BACKEND_PADRAO = "[::1]:9100"

# Cada chamada é um caminho no serviço. Escritos aqui em vez de virem de um stub
# gerado: são cinco, e assim ficam visíveis e greppáveis.
_SERVICO = "/mcapi.MCAPI/"


class McApiError(Exception):
    """O Media Composer não atendeu, ou atendeu com erro."""


class McApiIndisponivel(McApiError):
    """Não há Media Composer escutando. É o caso normal de 'não está aberto'."""


class McApiNaoImplementado(McApiError):
    """Este Media Composer não tem esse rpc — versão mais antiga que a nossa.

    ⚠️ **Não é defeito nosso nem do editor: é diferença de versão**, e por isso
    tem classe própria. O MCAPI cresce a cada release, e o que existe no 25.12
    (onde a integração foi medida) pode simplesmente não existir no 25.6.

    MEDIDO (2026-08-15, Windows, MC 25.6.0): `GetListOfWindows` responde
    `UNIMPLEMENTED`. No 25.12 do macOS ele responde normalmente.

    A regra para quem chama: se o rpc era **conveniência** (priorizar bins
    abertas, por exemplo), degrade e siga; se era essencial, aí sim é erro. O
    que não pode é a falta de um rpc opcional derrubar a operação inteira — foi
    exatamente o que acontecia, e o editor via só "Could not reach Órbita".
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

        self._canal = CanalDoNucleo("sincronizar")
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

    def _chamar(self, metodo: str, **campos):
        import grpc

        req = self._pedido(metodo, **campos)
        stub = self._canal.unary_unary(
            _SERVICO + metodo,
            request_serializer=type(req).SerializeToString,
            response_deserializer=self._msg(f"{metodo}Response").FromString,
        )
        try:
            return stub(req, timeout=self.timeout)
        except grpc.RpcError as e:
            raise self._traduzir(e, metodo) from None

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
        if codigo == grpc.StatusCode.UNAVAILABLE:
            return McApiIndisponivel(
                getattr(e, "frase", "")
                or f"o Media Composer não está atendendo em {metodo} — ele está aberto?"
            )
        if codigo == grpc.StatusCode.UNIMPLEMENTED:
            # Versão de MC mais antiga do que aquela em que a chamada foi medida.
            # Quem chama decide se dá para seguir sem ela (ver `McApiNaoImplementado`).
            return McApiNaoImplementado(
                f"{metodo} não existe neste Media Composer — a versão instalada é "
                f"mais antiga que a que a integração usa."
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

    def info(self) -> dict:
        r = self._chamar("GetAppInfo")
        return {"app": r.body.app_name, "version": r.body.app_version,
                "sdk": r.body.sdk_version, "license": r.body.license_type}

    def abrir_bin(self, caminho: str) -> None:
        """Abre uma bin no Media Composer.

        ⚠️ O caminho tem de ser ABSOLUTO ou o nome com extensão (`X.avb`);
        relativo-com-subpasta é recusado. Fato da base de conhecimento interna, medido.
        """
        self._chamar("OpenBin", bin_path=caminho)

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
        import os

        raiz = self.projeto().get("path") or ""
        try:
            rel = os.path.relpath(caminho_absoluto, raiz)
        except ValueError:
            return caminho_absoluto
        return rel if not rel.startswith("..") else caminho_absoluto

    def chave_de_bin(self, caminho_absoluto: str) -> str:
        """A identidade de uma bin como a INTERFACE a conhece: relativo à pasta do
        projeto, sem `.avb`, **sempre com barra `/`**.

        ⭐ **Existe para ter UM lugar só.** Esta string faz uma viagem de ida e
        volta: o app manda a árvore de bins para a tela, a pessoa marca as que
        quer, e a tela devolve as chaves. As duas pontas montavam a chave por
        conta própria e **só uma normalizava o separador** — no Windows, onde
        `caminho_relativo_da_bin` devolve `DIARIA 01\\CAM A`, a ida virava
        `DIARIA 01/CAM A` e a volta não casava com bin nenhuma: a seleção saía
        vazia e a interface reabria o seletor, como se o botão não funcionasse.

        ⚠️ Bins na RAIZ do projeto escapavam (não têm separador), o que deixava o
        bug intermitente conforme a organização do projeto.
        """
        rel = self.caminho_relativo_da_bin(caminho_absoluto)
        if rel.lower().endswith(".avb"):
            rel = rel[:-4]
        return rel.replace("\\", "/")

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

        **A LIXEIRA FICA DE FORA por padrão.** Bin excluída não é bin: ela não deve
        aparecer no seletor nem ser lida. `GetBins` não sabe filtrar — os
        `request_flag` disponíveis são `AllTypes`, `BinType`, `ScriptType`,
        `VolumeType` e `OnlyOpen` (ver `mcapi.proto`), nenhum sobre a lixeira —,
        então quem filtra somos nós, pelo caminho.

        ⚠️ **Não é caso de borda: é quase metade de um projeto real.** Medido em
        `PROJETO EXEMPLO` (2026-08-18): **21 das 48 bins estavam dentro de `Trash/`**.
        Pior que o volume, a AMBIGUIDADE — `PROJETO EXEMPLO Bin.avb` e `D01.avb`
        existiam ao mesmo tempo vivos e na lixeira, então o seletor mostrava o
        mesmo nome duas vezes e nada dizia qual era qual.
        """
        vals = [self._enum("GetBins", "request_flag", f) if isinstance(f, str)
                else f for f in flags]
        caminhos = [r.body.absolute_path
                    for r in self._fluxo("GetBins", request_flag=vals)
                    if r.body.absolute_path]
        if incluir_lixeira:
            return caminhos
        return [c for c in caminhos if not self.esta_na_lixeira(c)]

    #: Nome da pasta de bins excluídas, **como ela existe no DISCO**.
    #:
    #: ⚠️ É em inglês mesmo num Media Composer em português: a interface mostra
    #: "Lixeira", o disco guarda `Trash` (verificado em `PROJETO EXEMPLO`, MC 25.6 /
    #: Windows em português). Traduzir isto seria procurar uma pasta que não existe.
    PASTA_DA_LIXEIRA = "trash"

    def esta_na_lixeira(self, caminho_absoluto: str) -> bool:
        """Esta bin foi excluída (mora sob a lixeira do projeto)?

        Olha só o PRIMEIRO segmento do caminho relativo, porque a lixeira é uma
        pasta na raiz do projeto. Uma bin viva chamada `Trash` dentro de outra
        pasta (`EDICAO/Trash/x.avb`) continua valendo — improvável, mas recusá-la
        seria esconder trabalho de alguém por causa de um nome.

        ⚠️ A lixeira tem SUBPASTAS próprias (medido: `Trash/02_POR DIARIA/D01.avb`,
        `Trash/SYNC/…`), então não basta comparar o pai direto.
        """
        rel = self.caminho_relativo_da_bin(caminho_absoluto)
        primeiro = rel.replace("\\", "/").split("/")[0]
        return primeiro.lower() == self.PASTA_DA_LIXEIRA

    def bins_abertas(self) -> list[str]:
        """Nomes das bins ABERTAS na interface, na ordem em que o MC as reporta.

        Ler a seleção custa uma chamada POR BIN (~500 ms cada, ver o topo), então
        perguntar só às que estão abertas é o que torna a leitura sob demanda
        suportável: bin fechada não tem nada selecionado.
        """
        nomes = []
        for r in self._fluxo("GetListOfWindows"):
            for w in r.body.windows:
                if w.type == "Bins" and w.visibility:
                    # O MC prefixa com "* " a bin com alterações não salvas.
                    nomes.append(w.name[2:] if w.name.startswith("* ") else w.name)
        return nomes

    # ⛔⛔ `selecao()` SAIU em 2026-08-23 — e a ausência dela é uma decisão, não um
    # esquecimento. Ela lia "o que está marcado AGORA nas bins" e era o segundo modo
    # de entrada do Media Composer; o painel a abandonou em 18/08 (DECISIONS 20ª) e
    # a janela do app em 23/08 (§1.5 do roadmap, ADR 0021).
    #
    # Três razões, e a primeira é a que importa: **a seleção do MC atravessa BINS**,
    # então um clipe esquecido marcado noutra bin aberta entrava sem ninguém pedir —
    # e o editor só descobria pelo resultado do sync, longe da causa. As outras
    # duas: app e painel davam respostas DIFERENTES para "qual é o material
    # selecionado"; e sem `GetListOfWindows` (o MC 25.6 não tem) descobrir o que
    # está marcado obriga a perguntar a TODAS as bins do projeto, a ~500 ms cada,
    # para quase sempre não achar nada.
    #
    # ⚠️ Quem for reimplementá-la: o problema não é técnico. Uma versão correta
    # continuaria trazendo material que a pessoa não pediu. A entrada é a BIN.

    def colunas_do_master(self, mob_id_api: str, todas: bool = False) -> dict[str, str]:
        """As colunas de bin de um master, como o Media Composer as mostra.

        `GetMobInfo` é de FLUXO e devolve um par coluna/valor por mensagem.

        ⚠️⚠️ **`todas=True` é caro e quase sempre errado.** Medido em 2026-08-28 sobre
        um master AMA: o padrão devolve **31** colunas — as que têm valor — e
        `includes_empty_columns=True` devolve **191**. Cento e noventa e uma opções num
        autocomplete é inutilizável, então "todas" existe para diagnóstico e para o
        editor que sabe o que procura, nunca como padrão.

        ⭐ E quem abre as comportas é `includes_empty_columns`, **não**
        `only_visible_columns` — medido, porque o nome do segundo sugere o contrário e
        alguém ia "consertar" o padrão trocando o campo errado.
        """
        campos = ({"only_visible_columns": False, "includes_empty_columns": True}
                  if todas else {})
        fora: dict[str, str] = {}
        for r in self._fluxo("GetMobInfo", mob_id=mob_id_api, **campos):
            nome = r.body.column_name.strip()
            if nome:
                fora[nome] = r.body.column_value
        return fora

    def arquivo_do_master(self, mob_id_api: str, colunas: dict | None = None) -> str | None:
        """O ARQUIVO de onde este master veio, se ele ainda existir no disco.

        ⭐ **O Media Composer lembra de onde importou**: as colunas `Source Path` e
        `Source File` guardam a origem (`/Volumes/…/CAM B/` + `20260101_CAM0001.mov`).
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

        # ⛔⛔ `Source File` é NOME DE ARQUIVO, não caminho — e tratá-lo como caminho
        # era um furo real, provado executando: o operador `/` do `pathlib`
        # **descarta o lado esquerdo** quando o direito é absoluto, então
        # `Path("/Volumes/INGEST/CAM") / r"\\atacante\share\x.mov"` devolve
        # `\\atacante\share\x.mov` e o `Source Path` não confina nada.
        #
        # ⚠️ Diferente do irmão em `avid/caminhos.py`, aqui NÃO havia pré-condição
        # nenhuma — nem volume montado, nem rótulo a acertar. Um `.avb` de outra
        # produtora bastava para a máquina do editor bater num host escolhido por
        # quem autorou o projeto (`.exists()` sobre UNC abre sessão SMB no Windows),
        # ou para um arquivo qualquer do disco ser adotado como "o original".
        #
        # As duas colunas são texto livre de um arquivo de terceiro: entrada, não
        # configuração.
        if arquivo:
            so_nome = PurePath(arquivo.replace("\\", "/")).name
            if so_nome != arquivo:
                log.warning("%s: 'Source File' vinha como CAMINHO (%r) — usando só o "
                            "nome (%r)", nome, arquivo, so_nome)
            arquivo = so_nome
        if not arquivo:
            # Caso NORMAL para mídia transcodada pelo Avid — não é erro, é o gatilho
            # do plano B. Fica em DEBUG para não afogar o log com o caso comum.
            log.debug("%s: sem 'Source File' — vai para a mídia gerenciada", nome)
            return None
        caminho = Path(pasta) / arquivo if pasta else Path(arquivo)
        if caminho.exists():
            return str(caminho)

        # §1.3b: o caminho pode ser desta MÁQUINA escrito por OUTRA — um projeto
        # ingerido no Mac abre no Windows com `/Volumes/INGEST/…`, que aqui não
        # existe e lá é o mesmo storage. `traduzir` só usa o nome do volume que o
        # próprio caminho carrega, e só devolve o que existe. Ver `avid/caminhos.py`,
        # que explica em detalhe o que ele deliberadamente NÃO faz.
        from .caminhos import traduzir

        traduzido = traduzir(str(caminho))
        if traduzido is not None:
            return str(traduzido)

        # ⛔⛔ ESTA É A LINHA DO §1.3b DO ROADMAP, e a razão de ela existir é que o
        # descarte aqui é INDISTINGUÍVEL, no resultado, do caso acima: os dois
        # devolvem `None` e caem na mídia gerenciada. A diferença importa muito —
        # aqui o Avid SABE onde o original está e nós é que não sabemos ler o
        # caminho dele (projeto ingerido noutra estação: `/Volumes/INGEST/…` visto
        # do Windows, ou um UNC que aqui é letra mapeada). O app então "funciona"
        # com o transcode e perde o original, calado.
        #
        # Enquanto o §1.3b não tiver tradução de caminho, é ESTA linha que diz a
        # quem lê o log que havia um original, e com que grafia ele estava escrito.
        log.warning("%s: 'Source Path'/'Source File' apontam para «%s», que NÃO existe "
                    "nesta máquina — caindo para a mídia gerenciada", nome, caminho)
        return None

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
                 apenas_selecionados: bool = False,
                 abrir: bool = True) -> list[BinItem]:
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

        ⚠️ **`abrir=False` para VARREDURA.** Quando se percorre o projeto inteiro
        sem o usuário ter pedido bin nenhuma, abrir é efeito colateral puro: o
        editor acaba com a tela coberta de bins que ele não mandou abrir. Nesse
        modo, bin fechada é **pulada** — e pular é a resposta certa, porque uma
        bin fechada não tem nada selecionado, que é o que a varredura procura.
        Só abra quando a pessoa nomeou aquela bin.
        """
        rel = self.caminho_relativo_da_bin(caminho_absoluto)
        try:
            return self.itens_da_bin(rel, flags, apenas_selecionados)
        except McApiError:
            if not abrir:
                return []
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

    def carregar_no_monitor(self, mob_ids: list[str], destino: str = "Record") -> None:
        """Põe mobs no monitor (Source/Record). É o 'mostre isto ao editor'."""
        self._chamar("LoadMobsIntoViewer", mob_ids=list(mob_ids),
                     view_type=self._enum("LoadMobsIntoViewer", "view_type", destino))

    # ── escrever na bin: o nome, e a gravação que o torna real ────────────────
    #
    # ⭐ Tudo abaixo entrou em 2026-09-04 com a aba Renomear, portado do Assist anterior.
    # A ordem importa e é a de uma frase: `renomear_item` muda a SESSÃO, `abrir_bin`
    # escolhe quem salva, `salvar_bin_ativa` leva ao disco. Pular o último deixa a
    # bin com asterisco e o `.avb` com o estado anterior — com toda a cara de sucesso.

    def bin_do_mob(self, mob_id_api: str) -> str | None:
        """O caminho ABSOLUTO da `.avb` onde um mob vive — ou `None` se não der.

        ⭐ É a peça que torna o arrasto transparente: o Media Composer entrega um
        MobID, e daqui sai o arquivo. **Uma** chamada, contra os ~500 ms × nº de bins
        que enumerar o projeto custaria.

        ⚠️ Nunca levanta. `None` tem duas causas que a mensagem de quem chama precisa
        distinguir: o MC respondeu e não conhece o mob (o arrasto veio de outro
        projeto, ou a bin foi fechada), ou o RPC não existe nesta build — o
        `SetPosition`, do mesmo `.proto`, responde `UNIMPLEMENTED` no MC 2025.6.
        """
        try:
            r = self._chamar("GetBinFromMob", mob_id=mob_id_api)
        except McApiError:
            return None
        caminho = getattr(getattr(r, "body", None), "absolute_path", "") or ""
        return caminho or None

    def colunas_da_bin(self, caminho_absoluto: str) -> list[dict]:
        """O catálogo de colunas de uma bin: nome, tipo, e o que é **READONLY**.

        `[{"nome", "tipo", "oculta", "custom", "readonly"}]`, na ordem em que o Media
        Composer as declara.

        ⚠️ **Caminho ABSOLUTO**, ao contrário do `GetListOfBinItems`, que quer o
        relativo à pasta do projeto. Duas chamadas vizinhas querendo formas diferentes
        é do produto da Avid, não escolha nossa — medido em 2026-08-28.

        ⭐ É daqui que sai a lista de campos GRAVÁVEIS. Medido: 192 colunas, com
        `Name`, `Scene`, `Take`, `TapeID`, `Soundroll`, `Camroll`, `Shoot Date` e
        `Production` entre as graváveis; `Duration`, `Tape`, `Tracks`, `Source File` e
        `Source Path` entre as readonly.
        """
        r = self._chamar("GetBinColumnInfo", bin_path=caminho_absoluto)
        return [{"nome": c.column_name, "tipo": c.column_value_type,
                 "oculta": bool(c.column_hidden), "custom": bool(c.column_is_custom),
                 "readonly": bool(c.column_is_readonly)}
                for c in r.body.column]

    def renomear_item(self, mob_id_api: str, nome: str) -> None:
        """Renomeia um item de bin — a coluna `Name`, via `SetMobInfo`.

        ⭐ **Funciona nos quatro tipos**: masterclipe, subclipe, sequência e efeito.
        Medido no spike de 2026-08-28, com ida e volta e restauração conferida.

        ⚠️⚠️ **A mudança fica na SESSÃO até a bin ser salva**, e `Save Bin` é um
        `DoCommand` — assíncrono. Uma leitura do `.avb` logo em seguida devolve o
        estado ANTERIOR, com toda a cara de resposta boa: foi assim que o próprio
        spike concluiu "não persiste" antes de medir de novo com um segundo de folga.
        Quem renomeia em lote **confirma a gravação**, nunca a presume.

        ⚠️ Coluna readonly o Media Composer recusa sozinho (`"Unable to modify column
        data."`, ErrorType 70) — a escrita não passa calada. `Name` não é readonly.
        """
        from avid.proto import mcapi_types_pb2 as pb

        self._chamar("SetMobInfo", mob_id=mob_id_api,
                     column=pb.ColumnInfo(column_name="Name", column_value=nome))

    #: Medido ao vivo com `GetListOfCommands` nesta build (725 comandos).
    _SALVAR_BIN = 1004          # [File] Save Bin

    def _comando(self, command_id: int, tentativas: int = 8) -> None:
        """Um `DoCommand`, respeitando que o Media Composer executa UM DE CADA VEZ.

        ⚠️⚠️ **`DoCommand` é ASSÍNCRONO e SERIALIZADO.** Dois seguidos sem pausa e o
        segundo morre com `"Can't start more than one command on time."` (ErrorType
        73) — medido. Pior: a resposta do primeiro volta ANTES de o efeito acontecer,
        então perguntar o estado logo depois devolve o valor VELHO, e um laço que
        confie nisso conclui "não andou" sobre um comando que andou.
        """
        import time

        for _ in range(tentativas):
            try:
                self._chamar("DoCommand", commandId=command_id)
                time.sleep(0.30)          # deixa o efeito acontecer antes de perguntar
                return
            except McApiError as e:
                if "more than one command" not in str(e):
                    raise
                time.sleep(0.25)

    def salvar_bin_ativa(self) -> bool:
        """Manda o Media Composer SALVAR a bin em foco. `True` se ele aceitou.

        ⛔⛔ **Isto não é conveniência: sem salvar, a bin no disco não tem os masters.**

        Medido em 2026-08-27, comparando uma bin recém-escrita com a mesma bin salva:

            salva  : 299 mobs, 50 masters, 198 SourceClips
            recém  :   1 mob,   0 masters, 198 SourceClips

        A sequência é idêntica no que importa — mesmos 198 clipes, mesmas tracks. O
        que falta são os **master clips**: o Media Composer só os materializa no `.avb`
        quando a bin é salva, e até lá ela fica com o asterisco no nome.

        ⚠️ O preço aparece longe: quem lê essa bin depois não acha master nenhum para
        os `SourceClip` e entrega os takes com o **UMID cru no lugar do nome** —
        `urn:smpte:umid:060a2b34…`. Não é erro; é um leitor honesto sobre uma bin
        incompleta.

        ⚠️ `Save Bin` age sobre a bin ATIVA, e quem a ativa é o `abrir_bin` logo antes.
        Salvar é benigno — grava o que já está lá —, mas ainda é escrita no projeto de
        terceiro: por isso devolve `bool` em vez de levantar, e quem chama decide o que
        dizer ao editor.
        """
        try:
            self._comando(self._SALVAR_BIN)
            return True
        except McApiError as e:
            log.info("o Media Composer não aceitou o Save Bin: %s", e)
            return False

    def gravar_bin_fechando(self, caminho_absoluto: str) -> None:
        """Grava uma bin no disco FECHANDO e REABRINDO — o Save Bin de quem não tem `DoCommand`.

        ⭐ O MC 24.6 não implementa `DoCommand` (47 de 60 RPC; banco
        avid-panel-sdk/ativar-no-2021-ftf.md), mas o `CloseBin` SALVA a bin: o ciclo fechar + abrir custa ~0,2 s,
        medido pelo De Lá Pra Cá em 2026-10-18.

        ⚠️ Fechar a bin TIRA do monitor a timeline que mora nela, e reabrir não a devolve. Por isso: antes de fechar,
        as sequências da bin que estão num monitor; depois de reabrir, elas voltam ao Record. (O 24.6 não preenche o
        `view_type` do `GetViewerMobs`, então "num monitor" é o que dá para saber.) Carregar no SOURCE pendura o MC
        30–60 s — nunca se carrega master por aqui.
        """
        no_monitor: list[str] = []
        try:
            vistos = {m.mob_id for m in self._chamar("GetViewerMobs").body.mobs if m.mob_id}
            seqs = self.itens_da_bin(self.caminho_relativo_da_bin(caminho_absoluto), flags=("sequences",))
            no_monitor = [s.mob_id for s in seqs if s.mob_id in vistos]
        except McApiError as e:
            log.info("não deu para ver o monitor antes de fechar %s: %s", caminho_absoluto, e)
        self._chamar("CloseBin", bin_path=caminho_absoluto)
        self.abrir_bin(caminho_absoluto)
        if no_monitor:
            try:
                self.carregar_no_monitor(no_monitor, "Record")
            except McApiError as e:
                log.info("a timeline não voltou ao Record: %s", e)
