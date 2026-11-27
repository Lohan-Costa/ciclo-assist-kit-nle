"""O fluxo de relink, de ponta a ponta.

    sequence no MC  →  AAF  →  masters  →  índice das pastas  →  match
                                                                   ↓
    bin nova ONLINE  ←  ImportFile  ←  achatar + remapear  ←  LinkFile

Este módulo é o miolo do plugin: as rotas HTTP e a UI só o dirigem. Nada aqui depende de
HTTP, o que o deixa exercitável por script — é assim que ele foi medido.

## As duas metades, e por que ficam separadas

**Preparar** (`preparar`) lê e casa: não toca no Media Composer além de exportar o AAF, e
pode rodar quantas vezes o editor quiser enquanto ele revisa.

**Aplicar** (`aplicar`) escreve: `LinkFile` em massa, reescreve o AAF e importa. É a parte
lenta e a que muda o projeto, então só roda quando o editor manda.

## O que custa tempo

Toda chamada ao MC tem piso de ~500 ms — não é trabalho, é o laço dele atendendo a fila
do gRPC. Com 100 masters, o `LinkFile` em massa domina o relógio. Por isso há progresso e
cancelamento, e por isso não se chama o MC para nada que dê para saber sozinho.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from aaf.masters import chave_mob, masters_em_uso
from aaf.remap import remapear_masters
from avid.acoes import Acoes
from media.indexer import index_folder
from media.matcher_masters import casar_masters, resumo

log = logging.getLogger("delapraca.relink")


class Cancelado(Exception):
    """O editor pediu para parar."""


@dataclass
class Progresso:
    """Callback de progresso + o pedido de cancelamento, num objeto só."""

    callback: object = None          # callable(etapa, feito, total, detalhe)
    cancelar: bool = False

    def __call__(self, etapa: str, feito: int, total: int, detalhe: str = "") -> None:
        if self.cancelar:
            raise Cancelado(f"cancelado durante {etapa}")
        if self.callback:
            try:
                self.callback(etapa, feito, total, detalhe)
            except Exception:  # noqa: BLE001 — a UI não derruba o motor
                log.debug("callback de progresso falhou", exc_info=True)


@dataclass
class Trabalho:
    """Uma sessão de relink. Um por vez — o painel é de um editor."""

    aaf: str = ""
    sequence: str = ""
    #: o MobID da sequência na bin (rota `avb`): numa bin com várias timelines, é ele que diz QUAL relinkar
    sequence_mob_id: str = ""
    #: a bin veio de FORA (outra máquina, Magic Link): é só lida, e a entrega vai para a pasta do projeto aberto
    bin_externa: bool = False
    # ⭐ A rota de aplicação. `"aaf"` (padrão, validada em escala) pede o AAF ao MC e o
    # devolve por `ImportFile`; `"avb"` edita a bin do editor (ADR 0013) — sem export,
    # sem preset e sem import. `bin_origem` é a `.avb` que contém a timeline, resolvida
    # por `mcapi.bin_do_mob` a partir do MobID que o arrasto entrega.
    rota: str = "aaf"
    bin_origem: str = ""
    # Rota `"carta"` (ADR 0020): quem RECEBE no Resolve relinka aos originais ao importar. Os
    # masters vêm da Carta (`sessao_receber.masters_da_carta`); `pedido` diz de qual envio
    # ela veio, para o Importar conferir que as decisões são DESTA timeline.
    carta: object = None
    pedido: dict = field(default_factory=dict)
    # Rota `"prproj"` (organograma Premiere → Avid, autor 2026-10-25): o projeto do Premiere e a sequência (o
    # `sequence_mob_id` = o uid/nome dela), a análise (`tools.prproj_para_drt.analisar`) e `{mob_id: chave}` dos
    # masters sintéticos (`prproj_avid.masters_do_prproj`). Quem aplica é `prproj_avid.montar`.
    prproj: str = ""
    prproj_analise: object = None
    prproj_ids: dict = field(default_factory=dict)
    #: `{caminho do projeto: fator}` da escala de outra mídia que o editor ACEITOU (o Relinkar manda; como no Resolve)
    prproj_reescalar: dict = field(default_factory=dict)
    pastas: list[str] = field(default_factory=list)
    masters: list = field(default_factory=list)
    casamentos: list = field(default_factory=list)
    # ⭐ A pasta do projeto aberto — é ela que diz QUAL banco de mídias vale, porque a
    # configuração mora lá (`banco.py`). Vazia = sem banco, e o fluxo é o de sempre.
    pasta_projeto: str = ""
    # O que o banco resolveu nesta preparação, para o painel poder contar ao editor.
    do_banco: dict = field(default_factory=dict)
    #: o que o MAPA da Carta resolveu (`mapa_da_carta.consultar`: achados, alertas, quantas Cartas)
    do_mapa: dict = field(default_factory=dict)
    achatar_subclipes: bool = True
    achatar_group_clips: bool = True
    # ⭐ Relink PARCIAL: uma timeline meio relinkada é o caso comum. Independentes e
    # cumulativos. Ver `filtrar_masters`.
    so_importados: bool = False
    so_offline: bool = False
    #: os masters dos clipes SELECIONADOS na timeline (vazio = todos) — ver `filtrar_masters`
    so_masters: list = field(default_factory=list)
    # {mob_id do master → caminho escolhido pelo editor}, sobrepõe o matcher.
    escolhas: dict[str, str] = field(default_factory=dict)
    #: os masters que o editor mandou IGNORAR (autor, 2026-10-13, como no Resolve): o link deles não muda — não entram
    #: no relink nem contam como "ficaram de fora".
    ignorados: set = field(default_factory=set)
    filtrados: dict = field(default_factory=dict)   # quantos os filtros deixaram de fora
    #: {chave do MobID → "gerenciada" | "ama"}: os que NÃO casaram, mas já estão online no MC (`ja_online.py`; autor,
    #: 2026-10-13). A lista os mostra como "já online" e a _SEQ não os deixa à vista (só o offline vai à vista).
    ja_online: dict = field(default_factory=dict)
    #: a preparação foi a PRÉVIA da lista de mídias (o painel a dispara sozinho ao ter timeline e pastas): só lê e
    #: casa. Enquanto for prévia, o painel não pula para a revisão ao recarregar; o "Relinkar" a assume.
    previa: bool = False

    def decididos(self) -> dict[str, str]:
        """{mob_id → arquivo} do que vai virar relink: o que o matcher resolveu, mais
        o que o editor confirmou. Sugestão sem confirmação **não entra**."""
        final = {c.master.mob_id: c.arquivo for c in self.casamentos if c.resolvido}
        final.update(self.escolhas)
        return {k: v for k, v in final.items() if v and k not in self.ignorados}

    def resumo(self) -> dict:
        r = resumo(self.casamentos) if self.casamentos else {}
        r["decididos"] = len(self.decididos())
        r["sequence"] = self.sequence
        r["aaf"] = self.aaf
        r["rota"] = self.rota
        r["bin_origem"] = self.bin_origem
        r["filtrados"] = self.filtrados
        if self.rota == "prproj" and self.prproj_analise:
            # a oferta da escala digitada para outra mídia, a mesma lista do "antes de montar" do Resolve
            r["escala_de_outra_midia"] = (self.prproj_analise.get("resumo") or {}).get("escala_de_outra_midia") or []
        # ⭐ Quanto do casamento veio do banco. Sem isto o editor não tem como distinguir
        # "o banco resolveu 43" de "o banco está de enfeite" — e um acelerador que não se
        # mostra é indistinguível de um que não funciona.
        r["do_banco"] = self.do_banco.get("acertos", 0)
        r["ambiguos_no_banco"] = self.do_banco.get("ambiguos", 0)
        r["do_mapa"] = sum(1 for c in self.casamentos if c.metodo == "mapa")
        r["alertas_do_mapa"] = len(self.do_mapa.get("alertas") or [])
        return r


# ── metade 1: ler e casar ───────────────────────────────────────────────────

def traduzir_progresso_do_indice(info: dict) -> tuple[str, int, int, str]:
    """Payload do `index_folder` → `(etapa, feito, total, detalhe)` para a UI.

    ⚠️⚠️ **As chaves têm de ser as que o `index_folder` REALMENTE emite**, e são duas
    formas, uma por fase (ver o docstring dele):

        {"phase": "scan", "scanned": int, "found": int, "current": str}
        {"phase": "meta", "i": int, "total": int, "current": str, "indexed": int}

    A versão anterior lia `done` e `path`, que **não existem em nenhuma das duas**. O
    efeito não foi um erro: foi uma barra que **nunca saía de 0%** com o rótulo escrito
    `meta` (o fallback caindo no nome da fase), do começo ao fim da varredura — o editor
    via "0% meta" por minutos e a janela seguinte aparecia do nada. E o comentário ao
    lado **documentava o contrato errado**, prova de que foi escrito de memória em vez
    de conferido contra o emissor. Relatado por um editor em 2026-08-16.

    ⚠️ A fase `scan` **não tem total** — não se sabe quantos arquivos existem antes de
    varrer. Ela devolve `total=0`, que a UI trata como indeterminado; inventar um total
    aqui faria a barra andar para trás quando o verdadeiro aparecesse.

    Está fora de `preparar` de propósito: uma função aninhada não se testa, e foi
    exatamente a falta de teste que deixou o contrato divergir sem ninguém notar.
    """
    if info.get("phase") == "scan":
        achados, vistos = info.get("found", 0), info.get("scanned", 0)
        return ("varrendo as pastas", 0, 0, f"{achados} mídia(s) em {vistos} arquivos")
    atual = info.get("current") or ""
    return ("lendo os metadados", info.get("i", 0), info.get("total", 0) or 0,
            # Corta nas DUAS barras: é só texto de tela, e `Path(...).name` no macOS devolvia
            # `E:\...\x.WAV` inteiro (medido 2026-10-01, `tests/test_progresso.py`).
            atual.replace("\\", "/").rsplit("/", 1)[-1] if atual else "")



def exportar_aaf(mc, mob_id_sequence: str, pasta_saida: str, nome: str,
                 preset: str = "AAF") -> str:
    """Exporta a sequence como AAF e devolve o caminho.

    ⚠️ `destination_path` é DIRETÓRIO, e o processo do MC **não escreve em
    `/private/tmp`** (TCC do macOS) — a pasta tem de ser do usuário ou do projeto.

    ⚠️⚠️ **O nome do preset não diz o formato.** Medido em 2026-08-10: neste projeto o
    preset chamado `AAF` estava configurado para **WAVE**, e o export começou a renderizar
    o áudio da timeline inteira, com diálogo de progresso — o editor teve de cancelar na
    mão. Presets são por-projeto e editáveis; por isso conferimos o que **apareceu** em
    vez de confiar no nome, e por isso a UI deixa escolher qual usar.
    """
    Path(pasta_saida).mkdir(parents=True, exist_ok=True)
    saida = Acoes(mc).export_file(mob_id_sequence, pasta_saida, nome, preset=preset)

    if not saida:
        raise RuntimeError(
            f"o preset “{preset}” não produziu arquivo nenhum. "
            f"Escolha outro em opções avançadas, ou ajuste esse preset no Media Composer "
            f"(Export Settings) para exportar AAF."
        )
    if Path(saida).suffix.lower() != ".aaf":
        # O arquivo saiu, mas do formato errado — e é aqui que o WAVE de 26 minutos
        # apareceu. Dizer o que ele produziu é o que faz o editor entender na hora.
        raise RuntimeError(
            f"o preset “{preset}” exportou {Path(saida).name} — não é AAF. "
            f"Presets são por-projeto e o nome não garante o formato: escolha outro em "
            f"opções avançadas, ou ajuste esse no Media Composer."
        )
    return saida


def _hexa(mob_id) -> str:
    """Os 64 hex de um MobID em qualquer grafia (API, arrasto, pyavb). ⚠️ O `urn:smpte:umid:` do pyavb sai antes: o
    "e" de smpte e o "d" de umid passariam por hexadecimais."""
    texto = str(mob_id or "").lower()
    if texto.startswith("urn:smpte:umid:"):
        texto = texto[len("urn:smpte:umid:"):]
    return "".join(c for c in texto if c in "0123456789abcdef")


def filtrar_masters(masters: list, so_importados: bool, so_offline: bool,
                    so_masters=None) -> tuple[list, dict]:
    """Aplica os filtros de relink parcial. Devolve `(mantidos, contagem)`.

    `so_masters`: os MobIDs (qualquer grafia) dos masters dos clipes que o editor SELECIONOU na timeline (o botão
    "Carregar a seleção da timeline", `/mc/selecao`, 2026-10-25) — os outros saem do relink e ficam como estão.

    ⚠️⚠️ **`None` significa "não dá para saber", e o que não se sabe PASSA.** É a mesma
    regra da degradação do [ADR 0011](../../docs/adr/0011-uma-camada-de-plataforma-e-degradacao-por-versao.md):
    *o caminho degradado nunca pode ser mais RESTRITIVO que o completo*. Um master de
    mídia gerenciada não diz pela bin se está offline (isso mora no `msmMMOB.mdb`);
    tratá-lo como "online" o descartaria em silêncio — e o editor veria menos clipes
    relinkados sem nenhuma explicação.

    Por isso os testes são `is not True` / `is not False`, e não `not x`.
    """
    escolhidos = {_hexa(x) for x in so_masters or ()} - {""}
    if not (so_importados or so_offline or escolhidos):
        return masters, {"fora_por_ama": 0, "fora_por_online": 0}

    mantidos, fora_ama, fora_online, fora_sel = [], 0, 0, 0
    for m in masters:
        if escolhidos and _hexa(getattr(m, "mob_id", "")) not in escolhidos:
            fora_sel += 1
            continue
        if so_importados and getattr(m, "e_ama", None) is True:
            fora_ama += 1
            continue
        if so_offline and getattr(m, "esta_offline", None) is False:
            fora_online += 1
            continue
        mantidos.append(m)
    contagem = {"fora_por_ama": fora_ama, "fora_por_online": fora_online}
    if escolhidos:
        contagem["fora_da_selecao"] = fora_sel
    log.info("filtros: %d de %d masters mantidos %s",
             len(mantidos), len(masters), contagem)
    return mantidos, contagem


def preparar(trabalho: Trabalho, progresso: Progresso | None = None) -> Trabalho:
    """Do AAF às decisões: masters, índice das pastas e match."""
    p = progresso or Progresso()

    # ⭐ A ÚNICA diferença entre as duas rotas nesta metade é o LEITOR. O `casar_masters`
    # e todo o `media/` seguem idênticos: eles consomem objetos `Master` e nada neles é de
    # AAF (ver `motor/avb_bin/masters.py`).
    origem = {"avb": trabalho.bin_origem, "prproj": trabalho.prproj}.get(trabalho.rota, trabalho.aaf)
    p("lendo a timeline", 0, 3, Path(origem).name if origem else "")
    t0 = time.time()
    if trabalho.rota == "prproj":
        import prproj_avid
        from avb_bin.segmentos import caminho_confiavel
        from tools.prproj_para_drt import analisar

        trabalho.prproj_analise = analisar(
            trabalho.prproj, trabalho.sequence_mob_id or trabalho.sequence, list(trabalho.pastas),
            progresso=lambda f, t, atual="": p("casando com os originais", f, t, Path(atual).name if atual else ""),
            confiavel=caminho_confiavel)
        trabalho.masters, trabalho.prproj_ids = prproj_avid.masters_do_prproj(trabalho.prproj_analise)
    elif trabalho.rota == "carta":
        from sessao_receber import masters_da_carta

        trabalho.masters = masters_da_carta(trabalho.carta, trabalho.pastas)
    elif trabalho.rota == "avb":
        from avb_bin.masters import masters_de_arquivo

        trabalho.masters = masters_de_arquivo(trabalho.bin_origem, mob_id=trabalho.sequence_mob_id or None)
    else:
        trabalho.masters = masters_em_uso(trabalho.aaf)
    log.info("%d masters em %.1fs", len(trabalho.masters), time.time() - t0)

    trabalho.masters, trabalho.filtrados = filtrar_masters(
        trabalho.masters, trabalho.so_importados, trabalho.so_offline, trabalho.so_masters)
    if not trabalho.masters and trabalho.so_masters:
        raise RuntimeError("nenhum dos clipes selecionados está nesta timeline — carregue a seleção de novo")
    if not trabalho.masters:
        raise RuntimeError(
            "nenhum master sobrou depois dos filtros — desmarque “só importados” ou "
            "“só offline” para relinkar a timeline inteira.")

    # ── o banco de mídias, se houver um conectado ───────────────────────────
    #
    # ⭐ Consultado ANTES da varredura, e é daí que vem o ganho: cada master que o banco
    # reconhece com certeza sai da lista de nomes a procurar, e a varredura deixa de ler
    # metadado dos arquivos que casariam com ele (~61 ms cada, medido). Se ele reconhecer
    # todos, não há varredura nenhuma.
    #
    # ⚠️ E ele nunca IMPEDE uma descoberta: o que o banco não souber segue para a
    # varredura completa, exatamente como antes de ele existir.
    import banco as banco_mod

    do_banco = banco_mod.consultar(trabalho.pasta_projeto, trabalho.masters,
                                   trabalho.pastas)
    trabalho.do_banco = do_banco
    conhecidos = dict(do_banco["arquivos"])

    # ── o MAPA da Carta (plano 2026-11-26, etapa 3): de que ORIGINAL é cada offline, pelo que a Carta registrou ─────
    # ⭐ Depois do banco de propósito: o que o banco (ou a rota) já trouxe e NÃO é o próprio offline, se o mapa disser
    # outro arquivo, é empate do editor (`mapa_da_carta.marcar`). O que o mapa não souber segue o casamento de sempre.
    import mapa_da_carta

    p("consultando o mapa da Carta", 1, 3, "")
    trabalho.do_mapa = mapa_da_carta.consultar(trabalho.masters)
    discordam = mapa_da_carta.aplicar(trabalho.masters, trabalho.do_mapa)
    for caminho in discordam.values():
        conhecidos.setdefault(caminho, "")
    # Um master que JÁ chega com caminho (na rota `carta`: o AMA da Carta que existe nesta
    # máquina) entra no índice pelo mesmo caminho das linhas do banco — o estágio 1 do
    # matcher só o reconhece se ele estiver no índice.
    for m in trabalho.masters:
        c = getattr(m, "caminho_conhecido", None)
        if c:
            conhecidos.setdefault(c, m.nome)
    if conhecidos:
        p("consultando o banco", 1, 3, f"{len(conhecidos)} já conhecido(s)")

    # Só quem o banco NÃO resolveu precisa ser procurado no disco.
    faltam = [m for m in trabalho.masters if not getattr(m, "caminho_conhecido", None)]

    # ⚠️ Sem pasta apontada não há o que varrer — e é um caso legítimo, não um erro: com
    # banco conectado a pasta é opcional (ver `rotas.trabalho_preparar`). O que o banco
    # não souber volta como "sem mídia" na revisão, que é onde o editor decide.
    if faltam and trabalho.pastas:
        p("varrendo as pastas", 1, 3, f"{len(trabalho.pastas)} pasta(s)")
        t0 = time.time()

        def _passo(info):
            p(*traduzir_progresso_do_indice(info))

        # ⭐ O REEL do daily também é nome a procurar (critério de casamento, autor, 2026-11-22): sem ele nas dicas, o
        # original de nome = reel nem entrava no índice (laboratório BL08, P4: `CENA12_T3` → `B001C007.mov`).
        from media.matcher_masters import _reel
        dicas = [m.nome for m in faltam]
        for m in faltam:
            if not m.e_audio:
                try:
                    reel = _reel(m)
                except Exception:  # noqa: BLE001 — o reel é critério a mais; sem ele, vale o nome
                    reel = None
                if reel:
                    dicas.append(reel)
        indice = index_folder(trabalho.pastas, progress=_passo, name_hints=dicas)
        log.info("índice: %d arquivos em %.1fs",
                 len(indice.get("files") or []), time.time() - t0)
    elif not faltam:
        # ⭐ Cobertura total: nem se abre o disco. É o caso que o banco existe para criar.
        log.info("banco cobriu os %d masters — varredura dispensada",
                 len(trabalho.masters))
        indice = {"files": [], "total_files": 0}
    else:
        # Sem pasta e com masters que o banco não conhece: eles voltam "sem mídia", e a
        # tela de revisão diz o motivo e a correção. Não é falha — é o preço do atalho.
        log.info("%d master(s) fora do banco e nenhuma pasta apontada — ficam sem mídia",
                 len(faltam))
        indice = {"files": [], "total_files": 0}

    # As linhas do banco entram no índice para o estágio 1 do matcher poder resolvê-las:
    # ele procura `caminho_conhecido` DENTRO do índice, e um caminho que não está ali
    # seria ignorado em silêncio.
    ja = {a.get("path") for a in indice["files"]}
    for caminho, nome in conhecidos.items():
        if caminho not in ja:
            indice["files"].append({"path": caminho, "filename": Path(caminho).name,
                                    "extension": Path(caminho).suffix.lower()})
    indice["total_files"] = len(indice["files"])

    p("casando", 2, 3, f"{len(trabalho.masters)} masters")
    trabalho.casamentos = casar_masters(
        trabalho.masters, indice,
        progresso=lambda f, t, n: p("casando", f, t, n))
    mapa_da_carta.marcar(trabalho.casamentos, trabalho.do_mapa, discordam)

    # O que não casou pode já estar online (Avid MediaFiles, ou um link AMA feito por fora do app): a lista diz isso
    # e a _SEQ não o põe à vista. Acessório: falhar aqui só deixa tudo como "sem mídia", como antes.
    trabalho.ja_online = {}
    pendentes = [c.master for c in trabalho.casamentos if not c.resolvido]
    if pendentes:
        p("conferindo o que já está online", 2, 3, f"{len(pendentes)} sem casamento")
        try:
            import ja_online
            from plataforma import pasta_trabalho

            projeto = Path(trabalho.pasta_projeto) if trabalho.pasta_projeto else None
            cache = str(pasta_trabalho() / f"ama_{projeto.name or 'projeto'}.json") if projeto else None
            trabalho.ja_online = ja_online.classificar(pendentes, str(projeto or ""), cache)
        except Exception as e:  # noqa: BLE001
            log.warning("não consegui conferir o que já está online (%s)", e)

    p("pronto", 3, 3, "")
    return trabalho


# ── metade 2: aplicar ───────────────────────────────────────────────────────

def aplicar(mc, trabalho: Trabalho, pasta_projeto: str, nome_bin: str,
            pasta_trabalho: str, progresso: Progresso | None = None) -> dict:
    """Traz os originais online, reescreve o AAF e entrega a bin no Media Composer.

    ⚠️ `nome_bin` tem de ser **novo**. `OpenBin` numa bin já aberta devolve `Completed` e
    **não relê o disco**: o editor veria a versão velha enquanto o serviço jura ter
    entregue a nova.
    """
    p = progresso or Progresso()
    acoes = Acoes(mc)
    decididos = trabalho.decididos()
    if not decididos:
        raise ValueError("nada decidido — não há o que relinkar")

    por_mob = {m.mob_id: m for m in trabalho.masters}
    bin_rel = f"{nome_bin}.avb"

    # ── 1) a bin ────────────────────────────────────────────────────────────
    p("criando a bin", 0, 1, nome_bin)
    acoes.criar_bin(nome_bin)

    # ── 2) LinkFile em massa ────────────────────────────────────────────────
    # ⭐ É esta chamada que faz o AVID criar o AMA Management e o amaMMOB.mdb — a peça
    # que só ele sabe criar, e cuja falta é o que impedia o auto-link a partir de um AAF
    # montado por fora.
    #
    # É também o passo lento: ~500 ms de piso por arquivo. Com 100 masters, ~1 min.
    mapa: dict[str, str] = {}
    renomear: dict[str, str] = {}
    falhas: list[dict] = []
    total = len(decididos)
    t0 = time.time()

    for i, (mob_id, caminho) in enumerate(sorted(decididos.items())):
        p("trazendo a mídia", i, total, Path(caminho).name)
        try:
            novo = acoes.link_file(caminho, bin_rel)
        except Exception as e:  # noqa: BLE001
            # Um arquivo que o MC recusa não derruba os outros 99.
            falhas.append({"arquivo": caminho, "erro": str(e)})
            log.warning("LinkFile falhou em %s: %s", caminho, e)
            continue
        if not novo:
            falhas.append({"arquivo": caminho, "erro": "LinkFile não devolveu mob_id"})
            continue
        mapa[mob_id] = novo
        # O Avid mostra o nome do master na bin e na timeline; alinhá-lo ao arquivo
        # evita um clipe online exibindo o nome do transcode que não existe mais.
        renomear[mob_id] = Path(caminho).stem

    log.info("LinkFile: %d/%d em %.1fs (%.0f ms cada)",
             len(mapa), total, time.time() - t0,
             (time.time() - t0) * 1000 / max(total, 1))

    if not mapa:
        raise RuntimeError("nenhum arquivo pôde ser trazido para o Media Composer")

    # ── 3) Save ─────────────────────────────────────────────────────────────
    # Sem isto nada do LinkFile chega ao .avb em disco: não existe SaveBin no mcapi.
    p("salvando", total, total, "")
    acoes.salvar()

    # ── 4) achatar + remapear ───────────────────────────────────────────────
    p("reescrevendo o AAF", 0, 1, "")
    saida = str(Path(pasta_trabalho) / f"{nome_bin}.aaf")
    r = remapear_masters(
        trabalho.aaf, saida, mapa, renomear=renomear,
        achatar_subclipes=trabalho.achatar_subclipes,
        achatar_group_clips=trabalho.achatar_group_clips,
    )

    # ── 5) ImportFile ───────────────────────────────────────────────────────
    p("importando no Media Composer", 0, 1, nome_bin)
    acoes.import_file(saida, bin_rel)

    resultado = {
        "bin": nome_bin,
        "aaf": saida,
        "masters_online": len(mapa),
        "masters_pedidos": total,
        "falhas": falhas,
        "subclipes_achatados": r["subclipes_achatados"],
        "group_clips_achatados": r["group_clips_achatados"],
        "orfaos_removidos": r["orfaos_removidos"],
        "masters_remapeados": r["masters_trocados"],
        "referencias_trocadas": r["referencias_trocadas"],
        "segmentos_cobertos": sum(por_mob[m].segmentos for m in mapa if m in por_mob),
    }
    p("pronto", 1, 1, "")
    log.info("relink aplicado: %s", resultado)
    return resultado
