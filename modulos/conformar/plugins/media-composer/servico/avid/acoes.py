"""As ações que o relink precisa e que o cliente herdado do Órbita não tinha.

O Órbita só *lê* o Media Composer e entrega uma bin pronta. Aqui precisamos também
exportar o AAF da sequence, trazer os originais online e mandar o MC importar de volta.

Todas partem do `_chamar`/`_fluxo` do `MediaComposer` — o envelope, os enums e a
tradução de erro já estão resolvidos lá.

## O que o banco de NLEs já mediu, e que virou código aqui

* **`DoCommand` é sem parâmetro.** Age sobre o estado atual da interface. Alguns
  comandos abrem diálogo modal — e um diálogo modal **trava a API inteira**, inclusive
  chamadas que nada têm a ver com ele.
* **`DoCommand(1004 Save)` é obrigatório** depois de `LinkFile`. Não existe `SaveBin` no
  mcapi, e sem o Save nenhuma mudança da API chega ao `.avb` em disco: a bin da sessão
  fica adiantada e quem ler o arquivo vê a versão velha.
* **`ExportFile.destination_path` é um DIRETÓRIO**, não um arquivo. E o processo do MC
  **não escreve em `/private/tmp`** (TCC do macOS).
* **Presets são por-projeto.** O preset chamado "AAF" pode estar configurado para outra
  coisa — já exportou `.wav` numa medição. Sempre conferir o que saiu.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from .mcapi import MediaComposer

log = logging.getLogger("delapraca.avid.acoes")

# `File > Save`. Ver `docommand-comandos.md` no banco de NLEs.
CMD_SAVE = 1004

# RAW de câmera que o MC só linka com o plugin AMA do fabricante (ver `link_file`).
_PLUGIN_RAW = {
    ".braw": "de Blackmagic RAW (vem no instalador do Blackmagic RAW)",
    ".r3d": "da RED",
    ".ari": "da ARRI",
    ".arx": "da ARRI",
    ".crm": "da Canon (Cinema RAW Light)",
}


def _corpo(resposta):
    return getattr(resposta, "body", None)


class Acoes:
    """Ações sobre um Media Composer aberto. Envolve um `MediaComposer` já conectado."""

    def __init__(self, mc: MediaComposer):
        self.mc = mc

    # ── comandos ────────────────────────────────────────────────────────────

    def comando(self, command_id: int, prazo: float = 30.0):
        """Dispara um comando da interface pelo id.

        ⚠️ Sem parâmetro, por construção da API: o comando age sobre o estado atual.
        E alguns abrem diálogo modal, que trava toda a API até alguém clicar.

        ⚠️ O `DoCommand` volta ANTES de o comando acabar, e o MC recusa o seguinte enquanto isso ("Can't start more
        than one command on time.", ErrorType 73 — banco, avid-panel-sdk/copia-da-timeline.md). Repete até vagar,
        com prazo. Medido em 2026-10-13: relink com os 48 vídeos reaproveitados = dois Save a 0,3 s um do outro, sem
        LinkFile no meio; o segundo caiu com o 73 e derrubou o relink.
        """
        fim = time.monotonic() + prazo
        while True:
            try:
                return self.mc._chamar("DoCommand", commandId=command_id)
            except Exception as e:  # noqa: BLE001 — só o 73 é repetido
                if "more than one command" not in str(e) or time.monotonic() > fim:
                    raise
                time.sleep(0.2)

    def salvar(self, bin_aberta: str | None = None) -> bool:
        """`File > Save`. Obrigatório para que `LinkFile` chegue ao disco. Devolve se salvou.

        ⚠️ **O MC 2024 (24.6) não tem `DoCommand`** pela API (UNIMPLEMENTED; banco avid-panel-sdk/
        ativar-no-2021-ftf.md §Subconjunto). Lá o que salva é o `CloseBin` — medido em 2026-10-18 (24.6.0, Windows):
        bin com 0 mobs no disco depois do `LinkFile`, 3 depois do `CloseBin`. Então, com `bin_aberta`, salva ESSA bin
        fechando e reabrindo (`salvar_fechando`). Sem ela não há o que fazer: avisa no log e devolve False — quem chama
        e vai fechar a bin logo em seguida (a `_MIDIAS`) já tem o Save de graça.
        """
        from .mcapi import McApiNaoImplementado

        try:
            self.comando(CMD_SAVE)
            return True
        except McApiNaoImplementado:
            if bin_aberta:
                self.salvar_fechando(bin_aberta)
                return True
            log.warning("este Media Composer não salva pela API (sem DoCommand) — o disco fica com o último Save")
            return False

    def salvar_fechando(self, bin_aberta: str) -> None:
        """Salva UMA bin aberta pelo `CloseBin` e a devolve como estava: reaberta e com a timeline de volta ao monitor.

        ⚠️ Medido no MC 24.6 (2026-10-18): fechar a bin TIRA do monitor a timeline que mora nela (Composer e Timeline
        vazios) e reabrir não a devolve. Recarregar volta no MESMO quadro (o MC lembra a posição por sequência). O ciclo
        fechar + abrir + carregar levou 0,21 s.
        ⚠️ No 24.6 o `GetViewerMobs` não preenche o `view_type` (o Record vem como 0, que no 25.x é o Source), e carregar
        um master com `view_type=0` CRIOU uma sequência `.new.01` (Composer de monitor único). Por isso só uma SEQUÊNCIA
        desta bin volta, e sempre para o Record.
        """
        rel = self.mc.caminho_relativo_da_bin(bin_aberta)
        try:
            sequencias = {s.mob_id for s in self.mc.itens_da_bin(rel, flags=("sequences",))}
        except Exception as e:  # noqa: BLE001
            if "not open" in str(e):
                return            # fechada = o disco já é o último Save; reabrir poria uma bin na tela do editor
            raise
        try:
            no_monitor = [m.mob_id for m in self.mc._chamar("GetViewerMobs").body.mobs if m.mob_id in sequencias]
        except Exception as e:  # noqa: BLE001 — sem saber o monitor, ainda dá para salvar
            log.warning("não li o monitor antes de salvar %s (%s)", Path(bin_aberta).name, e)
            no_monitor = []
        self.mc.fechar_bin(bin_aberta)
        self.mc.abrir_bin(bin_aberta)
        if no_monitor:
            self.mc.carregar_no_monitor(no_monitor[:1], "Record")

    # ── bins ────────────────────────────────────────────────────────────────

    def criar_bin(self, nome: str, subpasta: str = "") -> None:
        """Cria uma bin no projeto aberto.

        ⚠️ **`folder_path` é RELATIVO à pasta do projeto**, e vazio significa a raiz.
        Caminho absoluto é **recusado** — com `"Directory not found."` (ErrorType 2),
        mensagem que manda conferir se a pasta existe quando o problema é a FORMA do
        caminho. Medido contra o MC 25.12 em 2026-08-10; é a mesma classe de armadilha
        já documentada para `bin_relative_path`, num campo diferente.

        ⚠️ Entregue **sempre um nome novo**, nunca reaproveite. `OpenBin` numa bin já
        aberta devolve `Completed` e **não relê o disco**: o MC segue servindo a cópia
        em memória, e o editor vê a versão velha enquanto o serviço jura ter entregue a
        nova.

        ⭐ Abre no CONTÊINER de bins (`option=1`, LastActiveBinContainer), não flutuante (pedido do autor, 2026-10-13).
        Medido no MC 25.6: com o padrão (FloatBin) a bin nova vira o contêiner ativo e TODO `OpenBin` seguinte também
        abria solto; com `option=1` ela vira aba do painel de bins, e o `OpenBin` de uma bin escrita no disco (UID
        novo, nunca aberta) também cai lá.
        """
        self.mc._chamar("CreateBin", folder_path=subpasta, bin_name=nome, option=1)

    def nome_de_bin_livre(self, pasta: str, base: str, *, sempre_numerar: bool = False,
                          tambem: tuple[str, ...] = ()) -> str:
        """`base`, `base 2`, `base 3`… — o primeiro que ainda não existe em disco.

        `sempre_numerar=True` começa em `base 1` e nunca devolve o nome pelado. É o que
        vale para o nome AUTOMÁTICO (o do projeto): ali o número não é desempate, é parte
        do nome — `PRODUCAO-A 1`, `PRODUCAO-A 2` lê como uma série de tentativas, e uma
        bin chamada só `PRODUCAO-A` no meio delas pareceria a bin do projeto.

        Quando o editor DIGITA um nome, ele quer aquele nome: o número só aparece se já
        houver outro igual, e aí é desempate mesmo.

        ⚠️ Nunca sobrescreve nem recusa. Duas bins com o mesmo nome no projeto é o que o
        Avid não aceita, mas o remédio não pode ser perder o trabalho de alguém.

        ⛔ Ocupado = a bin `.avb` OU uma PASTA com o nome: a entrega organizada do relink mora em `<nome>/` (só a pasta
        na raiz). Olhando só o `.avb`, o 2º relink reusou o `… 1` e escreveu na `_MIDIAS` da 1ª, aberta no MC
        (2026-10-13).

        ⛔ (revisão 2026-10-28) `tambem` = as outras pastas onde o nome também tem de estar livre. O relink pela bin do
        editor grava a entrega AO LADO da bin de origem (`relink_avb.aplicar`), que pode estar numa subpasta do projeto:
        olhando só a raiz, o 2º relink da mesma bin recebia o mesmo "PROJETO 1" e o `os.replace` gravava POR CIMA da 1ª
        entrega (talvez aberta no MC).
        """
        pastas = [Path(pasta), *(Path(x) for x in tambem if x)]

        def ocupado(nome: str) -> bool:
            return any((p / f"{nome}.avb").exists() or (p / nome).is_dir() for p in pastas)

        if not sempre_numerar and not ocupado(base):
            return base
        n = 1 if sempre_numerar else 2
        while ocupado(f"{base} {n}"):
            n += 1
        return f"{base} {n}"

    # ── trazer mídia para dentro ────────────────────────────────────────────

    def link_file(self, caminho: str, bin_destino: str, preset: str = "") -> str | None:
        """AMA-linka um arquivo, criando um master ONLINE na bin.

        ⭐ É esta chamada que faz o **Avid** criar o AMA Management e o `amaMMOB.mdb` —
        a peça que só ele sabe criar, e cuja falta é o que impedia o auto-link a partir
        de um AAF montado por fora.

        Devolve o `mob_id` do master criado, na representação da API (que **não** é a
        do pyavb — ver `mob_id_para_pyavb`).

        ⛔ Teto de ARQUIVO, não o de consulta (20 s). Medido em 2026-10-13 (MC 25.6, Windows,
        relink pela bin de fora com duas bins do projeto abertas): o 2º `LinkFile` passou dos
        20 s, o cliente desistiu — e o MC TERMINOU o link depois: a bin ficou com um master
        `B14_FUNDO` a mais, órfão, e a timeline sem ele ("1 de 2 mídias online"). Desistir
        cedo aqui não é erro honesto, é decisão errada (o mesmo do `CloseBin`).
        """
        from avid.mcapi import TEMPO_DE_ARQUIVO_S

        from avid.mcapi import McApiError

        campos = {"file_path": caminho, "destination_bin": bin_destino}
        if preset:
            campos["link_settings_name"] = preset
        try:
            r = self.mc._chamar("LinkFile", _timeout=TEMPO_DE_ARQUIVO_S, **campos)
        except McApiError as e:
            # ⛔ Medido no MC 24.6 (2026-10-18, Windows): caminho com acento ou cedilha é recusado ("cannot be linked",
            # ErrorType 66) — o MC lê o UTF-8 como MacRoman ("AÇÃO" → "A√á√ÉO"). O MESMO arquivo com nome sem acento
            # linka. Não há forma que passe: URL file:// e NFD também falham, bytes MacRoman o gRPC recusa, e o exFAT
            # do SSD não tem nome curto 8.3. "cannot be linked" sozinho mandaria o editor procurar defeito no arquivo.
            if "cannot be linked" in str(e) and not caminho.isascii():
                raise McApiError(
                    "o Media Composer não linkou porque o caminho tem acento ou cedilha — esta versão lê esses "
                    "caracteres errado. Renomeie o arquivo e as pastas sem acento, ou use o Media Composer 2025."
                ) from None
            # ⛔ Medido em 2026-10-18 (MC 24.6, Windows recém-formatado, PRODUCAO-A): os 43 `.BRAW` deram o mesmo
            # "cannot be linked" — faltava o plugin AMA de Blackmagic RAW (a pasta `AVX2_Plug-Ins\AMA\BlackmagicRAW`
            # não existia). RAW de câmera depende de plugin do fabricante; dizer qual poupa a caça ao defeito.
            plugin = _PLUGIN_RAW.get(Path(caminho).suffix.lower())
            if "cannot be linked" in str(e) and plugin:
                raise McApiError(
                    f"o Media Composer não abre {Path(caminho).suffix.upper()} — falta o plugin AMA {plugin} "
                    "(instale com o Media Composer fechado e refaça o relink)"
                ) from None
            raise
        corpo = _corpo(r)
        return getattr(corpo, "mob_id", None) or None

    def import_file(self, caminho: str, bin_destino: str, preset: str = "") -> str | None:
        """Importa um arquivo pelo caminho — incluindo, é a hipótese em teste, um AAF.

        `ImportFileRequestBody` é genérico (`file_path`, `import_settings_name`,
        `destination_bin`), sem nada que restrinja o tipo.

        ⚠️ Teto de ARQUIVO, não de consulta: importar um AAF é o Media Composer montar a
        timeline inteira, e uma montagem grande passa dos 20 s do padrão. O `CloseBin`
        já mostrou o que um teto curto faz aqui — devolve uma decisão errada, não um erro
        honesto. Ver `mcapi._chamar`.
        """
        from avid.mcapi import TEMPO_DE_ARQUIVO_S

        campos = {"file_path": caminho, "destination_bin": bin_destino}
        if preset:
            campos["import_settings_name"] = preset
        r = self.mc._chamar("ImportFile", _timeout=TEMPO_DE_ARQUIVO_S, **campos)
        corpo = _corpo(r)
        return getattr(corpo, "mob_id", None) or None

    # ── tirar coisas de dentro ──────────────────────────────────────────────

    def export_file(self, mob_id: str, pasta_destino: str, nome: str,
                    preset: str = "AAF", espera_s: float = 300.0) -> str | None:
        """Exporta um mob com um preset. Devolve o caminho do arquivo que apareceu.

        ⚠️ `pasta_destino` é DIRETÓRIO; a extensão vem do preset. E o processo do MC
        **não escreve em `/private/tmp`** (TCC do macOS).

        ⚠️⚠️ **`ExportFile` é ASSÍNCRONO.** A chamada volta `Completed` em ~0,8 s e o
        Media Composer escreve o arquivo depois — um AAF de 10 MB levou mais que isso.
        Conferir o diretório logo após a chamada acusa "não produziu arquivo nenhum"
        enquanto o export está acontecendo, e a mensagem culpa o preset por um problema
        que é de tempo. (Faz sentido: o `ResponseHeader` do mcapi tem `task_id`,
        `status` e `progress` — é uma tarefa, não uma resposta.)

        Então esperamos o arquivo **aparecer** e **parar de crescer**.
        """
        pasta = Path(pasta_destino)
        antes = {p: p.stat().st_mtime for p in pasta.iterdir()} if pasta.is_dir() else {}

        self.mc._chamar(
            "ExportFile",
            mob_id=mob_id,
            file_name=nome,
            export_settings_name=preset,
            destination_path=str(pasta),
        )
        if not pasta.is_dir():
            return None

        limite = time.monotonic() + espera_s
        saida: Path | None = None
        while time.monotonic() < limite:
            # ⚠️ `._NOME.aaf` é o AppleDouble do macOS em disco exFAT/SMB (matriz de
            # plataforma): aparece JUNTO do export e podia ser o "mais recente" escolhido
            # (revisão ampla, 2026-09-30).
            candidatos = [
                p for p in pasta.iterdir()
                if p.is_file() and not p.name.startswith("._")
                and (p not in antes or p.stat().st_mtime > antes[p])
            ]
            # Preferimos o que tem o nome que pedimos; se o preset renomear, vale o mais
            # recente que apareceu.
            exatos = [p for p in candidatos if p.stem == nome]
            if exatos or candidatos:
                saida = max(exatos or candidatos, key=lambda p: p.stat().st_mtime)
                break
            time.sleep(0.4)

        if saida is None:
            return None

        # Esperar parar de crescer: um AAF grande aparece com 0 bytes e vai enchendo.
        anterior, estavel = -1, 0
        while time.monotonic() < limite and estavel < 3:
            atual = saida.stat().st_size
            estavel = estavel + 1 if atual == anterior and atual > 0 else 0
            anterior = atual
            time.sleep(0.3)

        return str(saida)

    # ── listar presets ──────────────────────────────────────────────────────

    def presets(self, tipo: str) -> list[str]:
        """Nomes dos presets do projeto. `tipo` ∈ export | import | link."""
        metodo = {
            "export": "GetListOfExportSettings",
            "import": "GetListOfImportSettings",
            "link": "GetListOfLinkSettings",
        }[tipo]
        # É server-streaming (uma resposta com a lista, não uma por preset). Chamar
        # como unária estoura o prazo, e o erro parece "o MC não respondeu" — que manda
        # procurar no lugar errado.
        nomes: list[str] = []
        for r in self.mc._fluxo(metodo):
            # O campo é `setting_names`, no singular do prefixo — conferido ao vivo
            # contra o MC 25.12, não deduzido do nome do método.
            nomes.extend(getattr(_corpo(r), "setting_names", None) or [])
        return [n for n in dict.fromkeys(nomes) if n]
