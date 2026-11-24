"""A sessão da aba *Daqui Pra Lá*: ler a timeline da bin e escrever o arquivo de saída.

Mesmo desenho da `sessao.Sessao` (uma tarefa por vez, numa thread, estado LIDO pelo SSE
e nunca empurrado), com domínio próprio: aqui não há casamento por semelhança nem tela de
revisão — cada master já aponta UM arquivo, e a pergunta é só *onde ele está*.

    arrasto (MobID) ─► preparar: acha a bin, SALVA, lê (avb_bin.segmentos), resolve arquivos
                   ─► gerar:    Carta Aberta (JSON) ou DRT (drp.writer.build_drt)

⛔⛔ Nenhum caminho aqui chama `ExportFile` — ADR 0015.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from pathlib import Path

from sessao import Estado

log = logging.getLogger("delapraca.sessao_export")

#: Formatos que GERAM arquivo nesta versão, e a extensão de cada um. Os demais aparecem
#: no painel como "em breve" — e a rota os recusa por conta própria (ver `formato_valido`).
FORMATOS = {"carta_aberta": ".json", "drt": ".drt"}
EM_BREVE = ("prproj", "aaf", "xml", "otio")


class Cancelado(Exception):
    pass


def formato_valido(formato: str) -> str:
    if formato in FORMATOS:
        return formato
    if formato in EM_BREVE:
        raise ValueError(f"o formato {formato.upper()} ainda não está pronto — em breve")
    raise ValueError(f"formato desconhecido: {formato!r}")


def com_extensao(caminho: str, formato: str) -> str:
    """Garante a extensão do formato no nome que o diálogo devolveu.

    ⚠️ O diálogo de salvar é o genérico do app (`escolher.nomear_arquivo`), sem filtro de
    tipo — de propósito: mexer na vtable do `IFileSaveDialog` por um filtro é risco
    desproporcional (ver `dialogo_win.py`). Quem sabe a extensão é o formato escolhido.
    """
    ext = FORMATOS[formato]
    p = Path(caminho)
    return str(p) if p.suffix.lower() == ext else str(p.with_name(p.name + ext))


def mob_id_da_api(urn: str) -> str:
    """URN do pyavb → a forma que o arrasto entrega e que `GetMobInfo` aceita (26-6-16-12-4).

    Os 64 dígitos são os MESMOS, na mesma ordem — é o que `mcapi.mob_id_para_pyavb`
    pressupõe no caminho inverso. Só o agrupamento muda.
    """
    from aaf.masters import chave_mob

    h = chave_mob(urn)
    return f"{h[:26]}-{h[26:32]}-{h[32:48]}-{h[48:60]}-{h[60:]}"


def resolver_midia(mc, leitura: dict, anotar=lambda *a, **k: None,
                   so_masters: set[str] | None = None) -> dict:
    """O arquivo de cada master da `leitura`. Anota em cada master `origem_do_arquivo` e,
    quando pergunta ao MC, `colunas_mc`. Devolve `{arquivos, gerenciados, na_gerenciada,
    offline, indice}`.

    Ordem (regra do autor, banco `protocolos/msm/pmr-fmid.md`: *"a mídia que vale é a
    gerenciada"*):

    1. ⭐ a MÍDIA GERENCIADA, pelo índice do próprio Avid (`msmFMID.pmr`): o `.mxf` EXATO de
       cada trilha, sem abrir arquivo nenhum (0,03 s para 1429 arquivos, medido). É o que o
       Resolve liga quando importa o AAF;
    2. o que a BIN diz (AMA — barato);
    3. o que o MEDIA COMPOSER lembra (colunas Source Path / Source File, ~500 ms por master).

    ⭐ Master SEM arquivo aqui NÃO sai do DRT: é o caso normal de quem edita offline com mídia
    gerenciada e manda para o colorista, que tem os originais. Ele entra como referência ao
    original (`referencia_offline`), e as colunas do MC ficam guardadas porque são elas que
    trazem a EXTENSÃO do arquivo de câmera.

    `so_masters` limita a pergunta ao MC (a parte cara) a esses masters — o insert só precisa
    dos que o editor escolheu.
    """
    from avb_bin.segmentos import caminho_confiavel
    from media import pmr

    masters = leitura["masters"]
    arquivos: dict[str, str] = {}
    offline: list[dict] = []

    anotar("lendo o índice da mídia gerenciada")
    indice = pmr.indice_de(pmr.raizes_de_midia())
    gerenciados = indice.por_arquivo or {}
    na_gerenciada = {k for k, m in masters.items()
                     if any(e in gerenciados for e in (m.get("essencias") or {}).values())}

    alvos = [(k, m) for k, m in masters.items() if so_masters is None or k in so_masters]
    for i, (chave, m) in enumerate(alvos, 1):
        anotar("identificando os originais", i, len(alvos), m["nome"])
        if chave in na_gerenciada:
            m["origem_do_arquivo"] = "gerenciada"
            continue
        caminho, _motivo = caminho_confiavel(m["caminho_na_bin"])
        if caminho and os.path.isfile(caminho):
            arquivos[chave], m["origem_do_arquivo"] = caminho, "bin"
            continue
        colunas: dict = {}
        try:
            colunas = mc.colunas_do_master(mob_id_da_api(chave)) or {}
        except Exception as e:  # noqa: BLE001
            log.info("MC não deu as colunas de %s: %s", m["nome"], e)
        m["colunas_mc"] = {k: (colunas.get(k) or "").strip()
                           for k in ("Source File", "Source Path", "Tape")}
        pelo_mc = None
        if colunas:
            try:
                pelo_mc = mc.arquivo_do_master(mob_id_da_api(chave), colunas=colunas)
            except Exception as e:  # noqa: BLE001
                log.info("MC não disse o arquivo de %s: %s", m["nome"], e)
        if pelo_mc:
            arquivos[chave], m["origem_do_arquivo"] = pelo_mc, "media composer"
        else:
            m["origem_do_arquivo"] = "offline"
            ident = m.get("identidade") or {}
            offline.append({"nome": m["nome"],
                            "reel": ident.get("reel") or "",
                            "tem_tc": ident.get("tc_inicio") is not None,
                            "arquivo": m["colunas_mc"]["Source File"]})
    return {"arquivos": arquivos, "gerenciados": gerenciados, "na_gerenciada": na_gerenciada,
            "offline": offline, "indice": indice}


class SessaoExport:
    def __init__(self, servico):
        self.servico = servico
        self.estado = Estado()
        self.leitura: dict | None = None
        self.casamentos: list = []
        self.arquivos: dict[str, str] = {}
        self.gerenciados: dict[str, str] = {}
        self.arrastado: dict = {}
        self.projeto = ""
        #: a produção que o editor indicou no Daqui Pra Lá (vazio = o nome do projeto aberto) — vai na Carta (etapa 4)
        self.producao = ""
        self.bin_origem = ""
        #: (largura, altura) do projeto aberto no MC — o raster da timeline do DRT (ver `_gerar`)
        self.raster: tuple[int, int] | None = None
        self._thread: threading.Thread | None = None
        self._cancelar = False
        self._lock = threading.Lock()

    @property
    def ocupada(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def instantaneo(self) -> dict:
        d = self.estado.to_dict()
        d["ocupada"] = self.ocupada
        d["sequencia"] = self.arrastado
        return d

    def nome_da_sequencia(self) -> str:
        """O que o editor vê: o nome que o arrasto resolveu, senão o que a bin diz."""
        return (self.arrastado.get("nome")
                or (self.leitura or {}).get("composition_name") or "")

    def cancelar(self) -> bool:
        if not self.ocupada:
            return False
        self._cancelar = True
        return True

    # ── as duas metades ─────────────────────────────────────────────────────

    def preparar(self, mob_id: str, nome: str) -> None:
        with self._lock:
            if self.ocupada:
                raise RuntimeError("já há uma exportação em andamento")
            self.leitura, self.casamentos, self.arquivos = None, [], {}
            self.arrastado = {"mob_id": mob_id, "nome": nome}
            self._iniciar("preparando", self._preparar, mob_id)

    def gerar(self, formato: str, caminho: str, nome: str, comentario: str) -> None:
        with self._lock:
            if self.ocupada:
                raise RuntimeError("já há uma exportação em andamento")
            if self.leitura is None:
                raise ValueError("arraste uma timeline antes de exportar")
            self._iniciar("gerando", self._gerar, formato, caminho, nome, comentario)

    # ── plumbing ────────────────────────────────────────────────────────────

    def _iniciar(self, fase, alvo, *args) -> None:
        resumo_anterior = self.estado.resultado if fase == "gerando" else {}
        self.estado = Estado(fase=fase, inicio=time.time())
        self.estado.resultado = dict(resumo_anterior)
        self._cancelar = False
        self._thread = threading.Thread(target=self._rodar, args=(alvo, args),
                                        name=f"delapraca-export-{fase}", daemon=True)
        self._thread.start()

    def _anotar(self, etapa: str, feito: int = 0, total: int = 0, detalhe: str = "") -> None:
        if self._cancelar:
            raise Cancelado("cancelado pelo editor")
        e = self.estado
        e.etapa, e.feito, e.total, e.detalhe = etapa, feito, total, str(detalhe)

    def _rodar(self, alvo, args) -> None:
        try:
            alvo(*args)
        except Cancelado:
            self.estado.fase = "ocioso"
            self.estado.etapa = "cancelado"
        except Exception as e:  # noqa: BLE001
            self.estado.fase = "erro"
            self.estado.erro = str(e) if isinstance(e, (LookupError, ValueError, RuntimeError)) \
                else f"{type(e).__name__}: {e}"
            log.exception("exportação falhou")

    def _preparar(self, mob_id: str) -> None:
        import relink_avb
        from avb_bin.segmentos import casamentos, ler_timeline_de_arquivo

        with self.servico.media_composer() as mc:
            self._anotar("procurando a bin da timeline")
            if not mc.esta_vivo():
                raise RuntimeError("o Media Composer não respondeu — ele está aberto?")
            info = mc.projeto() or {}
            self.projeto = Path(info.get("path") or "").name
            self.raster = ((int(info["width"]), int(info["height"]))
                           if info.get("width") and info.get("height") else None)
            bin_origem = mc.bin_do_mob(mob_id)
            if not bin_origem or not Path(bin_origem).is_file():
                raise LookupError("não achei a bin desta timeline no disco — ela está numa "
                                  "bin salva do projeto aberto?")
            self._anotar("salvando a bin antes de ler", detalhe=Path(bin_origem).name)
            if not relink_avb.garantir_bin_no_disco(mc, bin_origem):
                raise LookupError("a bin está vazia no disco — salve a bin no Media Composer "
                                  "e arraste de novo")

            self._anotar("lendo a timeline", detalhe=Path(bin_origem).name)
            leitura = ler_timeline_de_arquivo(bin_origem, mob_id=mob_id)

            midia = resolver_midia(mc, leitura, self._anotar)
            arquivos, offline = midia["arquivos"], midia["offline"]
            na_gerenciada, indice = midia["na_gerenciada"], midia["indice"]
            self.gerenciados = midia["gerenciados"]
            total = len(leitura["masters"])

        self.leitura = leitura
        self.bin_origem = bin_origem
        self.arquivos = arquivos
        self.casamentos = casamentos(leitura, arquivos)
        segs = leitura["segments"]
        eventos = [s for s in segs if not s["is_gap"] and not s["is_transition"]]
        self.estado.resultado = {
            "sequencia": leitura["composition_name"],
            "bin": Path(bin_origem).name,
            "fps": leitura["timeline_fps"],
            "tc_inicial": leitura["timeline_start_tc"],
            "trilhas_video": len({s["track"] for s in segs if not s["is_audio"]}),
            "trilhas_audio": len({s["track"] for s in segs if s["is_audio"]}),
            "eventos": len(eventos),
            "masters": total,
            "masters_na_gerenciada": len(na_gerenciada),
            "indices_lidos": indice.indices_lidos,
            "pastas_sem_indice": indice.pastas_sem_indice,
            "masters_com_arquivo": len(arquivos) + len(na_gerenciada),
            "masters_offline": offline[:30],
            "masters_offline_total": len(offline),
            "offline_sem_tc": sum(1 for o in offline if not o["tem_tc"]),
            "avisos": leitura["avisos"],
        }
        self.estado.fase = "pronto"
        self.estado.etapa = ""

    def enviar(self, pasta: str, comentario: str, nome: str | None = None,
               canal: str | None = None) -> str:
        """Magic Link: a Carta da timeline completa na caixa `pasta` do canal. Devolve o caminho.

        É o mesmo `_gerar` da Carta Aberta, com o bloco `envio`. `nome` é o que o editor
        compôs no painel (vira o nome da timeline do outro lado); sem ele, o da sequência. O
        arquivo leva esse nome e o id do envio (`magic_link.caminho_do_envio`).
        """
        import magic_link

        with self._lock:
            if self.ocupada:
                raise RuntimeError("já há uma exportação em andamento")
            if self.leitura is None:
                raise ValueError("arraste uma timeline antes de enviar")
            envio = magic_link.novo_envio("timeline", canal)
            nome = (nome or "").strip() or self.nome_da_sequencia()
            caminho = magic_link.caminho_do_envio(pasta, nome, envio)
            self._iniciar("gerando", self._gerar, "carta_aberta", caminho,
                          nome, comentario, envio)
            return caminho

    def _gerar(self, formato: str, caminho: str, nome: str, comentario: str,
               envio: dict | None = None) -> None:
        from avb_bin.segmentos import montar_midia

        leitura = self.leitura
        self._anotar("escrevendo o arquivo", detalhe=Path(caminho).name)

        # Por clipe: a `.mxf` gerenciada da trilha → o arquivo AMA → e, sem nenhum dos dois,
        # a REFERÊNCIA ao original (nome de câmera, TC de origem, duração, lidos da bin; a
        # extensão, se o MC sabia). A pasta padrão da referência é a do próprio export — é só
        # referência; quem recebe religa no Resolve.
        segmentos, casados, metadados = montar_midia(
            leitura, self.arquivos, str(Path(caminho).parent),
            {k: m.get("colunas_mc") or {} for k, m in leitura["masters"].items()},
            self.gerenciados)

        if formato == "carta_aberta":
            from carta_aberta.writer import build_carta_aberta

            # ⭐ Magic Link de uma TIMELINE: a bin dela vai ANEXA, antes da Carta (autor, 2026-10-12). Quem recebe no
            # Media Composer relinka pela bin de fora. É acessório: se a rede recusar, a Carta vai assim mesmo e o
            # envio não diz que tem bin (memória "o trabalho caro não pode morrer no acessório").
            if envio and envio.get("tipo") == "timeline" and self.bin_origem:
                import magic_link

                try:
                    envio["bin_anexa"] = Path(magic_link.anexar_bin(self.bin_origem, caminho)).name
                except OSError as e:
                    log.warning("a bin não foi anexada ao envio (%s) — a Carta vai sem ela", e)

            # ⭐ Sem perdas (Carta 1.1): o que ESTA máquina resolveu da mídia viaja por master,
            # para quem recebe refazer `montar_midia` e chegar ao mesmo DRT
            # (`tests/test_carta_ida_e_volta.py`). O índice inteiro não vai: o writer só
            # grava as `.mxf` das essências dos masters desta timeline.
            saida = build_carta_aberta(leitura, casados, caminho, nome, comentario,
                                       arquivos=self.arquivos, gerenciados=self.gerenciados,
                                       envio=envio, producao=(self.producao or self.projeto or "").strip())
        else:
            from drp.writer import build_drt

            if not casados:
                raise ValueError("a timeline não tem nenhum clipe de mídia — o DRT sairia vazio")
            # ⚠️ O comentário ainda NÃO vira marcador no DRT: escrever o marcador do Resolve
            # é engenharia reversa por fazer. Ele vai na Carta Aberta; aqui fica registrado.
            # ⛔ O raster do projeto vai como `timeline_size`: é ele que liga, no writer, a taxa da
            # timeline (`SequenceSetup`) e o início dela (`MediaExtents`). Sem isso a timeline do Avid
            # nascia a 23,976 em qualquer taxa e, a 24, começava em 01:00:03:14, engolindo o 1º corte
            # (laboratório A01, 2026-10-11, Resolve 19 Windows). O Premiere já passava.
            saida = build_drt(segmentos, casados, caminho,
                              timeline_name=nome, timeline_fps=leitura["timeline_fps"],
                              offline=metadados, timeline_start_frames=leitura.get("timeline_start_frames"),
                              # medido de novo no Resolve 21.1 (2026-10-28): Avid a 25 sem o tamanho → timeline 23,976, TC
                              # 00:59:56:09. Sem o raster do projeto (MC sem resposta), o do esqueleto: a taxa vai assim mesmo
                              timeline_size=self.raster or (1920, 1080))
            saida["clipes_offline"] = sum(1 for c in casados if c.get("offline"))
            saida = {k: v for k, v in saida.items() if k != "clips"}
            if (comentario or "").strip():
                saida["comentario_ignorado"] = True
        self.estado.resultado = {**self.estado.resultado, "arquivo": caminho,
                                 "formato": formato, "saida": saida}
        self.estado.fase = "feito"
        self.estado.etapa = ""
