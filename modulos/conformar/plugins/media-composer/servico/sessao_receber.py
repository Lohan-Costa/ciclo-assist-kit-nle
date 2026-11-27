"""Magic Link, lado de quem RECEBE: a caixa de cada canal e o DRT temporário para o Resolve.

A casca do NLE (`plugins/resolve/casca/`) é fina: o painel lista, pede e ela importa. O trabalho
mora aqui, porque o writer do DRT e o `ffprobe` são Python. Os canais (um por setor, a edição
no meio) estão em `canais.py`:

    Procurar novos → caixa(canais)       os DOIS sentidos de cada canal conectado, numa lista:
                                         pendentes e já importados (o painel filtra)
    Trazer         → preparar(id)        Carta → mídia DESTA máquina → (filtro do insert) → .drt
                   → (a casca) ImportTimelineFromFile(drt)   — medido no Resolve 19
                   → trazido(id)         anotado SÓ nesta máquina (recebidos.jsonl), e a Carta
                                         desce para `importado/<timelines|inserts>`

    Abrir arquivo… → abrir(caminho)      uma Carta solta, ou as sequências de uma bin `.avb`
                   → preparar_avulso(chave, mob_id)   a bin vira Carta em memória, e daí o
                                         MESMO caminho do Trazer (`_montar`)

⚠️⚠️ **A pasta do canal é de rede e a Carta é texto de terceiro** (ameaças do Magic Link, ADR
0016): só o nível de cima da pasta, só `*.carta.json`, teto de tamanho, `ler_carta` confere a
forma, e **nenhum caminho de dentro da Carta é usado sem passar por `caminho_confiavel`**
(recusa UNC e `..` ANTES de tocar o disco — um `exists()` num UNC abre sessão SMB para o host
que o autor da Carta escolheu). O nome do DRT sai do `id` validado, nunca da Carta.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import re
import threading
from xml.etree.ElementTree import ParseError as ET_ParseError
from datetime import datetime
from pathlib import Path

import canais
import plataforma

log = logging.getLogger("delapraca.receber")

SUFIXO = ".carta.json"
REGISTRO = "recebidos.jsonl"
#: Ataque V6: uma pasta inundada com milhares de `.carta.json` faria cada "Procurar novos" ler
#: todos (até 64 MB cada) com o Resolve travado esperando. Lê-se os MAIS RECENTES, e a caixa
#: diz que cortou.
MAX_ARQUIVOS = 500
#: Quantos arquivos abertos por "Abrir arquivo…" a sessão lembra (a lista de sequências de uma
#: bin fica na tela; o editor pode trazer uma, depois outra).
MAX_AVULSOS = 20
RE_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
#: `{tipo do insert: rótulo}` — da lista de setores (`canais.SETORES`): setor novo entra sozinho.
ROTULO_INSERT = {s["insert"]: s["rotulo"].upper() for s in canais.SETORES.values()}
ROTULO_INSERT["insert"] = "INSERT"          # o insert exportado, sem canal
#: O "mesmo formato" do Atualizar: a Carta e a bin do Avid são a MESMA leitura
#: (`test_carta_ida_e_volta`: DRT(bin) ≡ DRT(Carta)), então uma serve de antiga para a outra.
FAMILIA = {"carta": "avid", "avb": "avid", "aaf": "aaf"}
ROTULO_FAMILIA = {"avid": "uma Carta ou bin do Avid", "aaf": "um AAF"}
#: Os formatos de timeline que o "Escolher…" do Resolve mostra: os que o app lê e os que VAI ler
#: (autor, 2026-09-29). Os que ainda não lê são recusados em `abrir`, com o motivo.
EXTENSOES_RECEBER = ("json", "avb", "aaf", "xml", "fcpxml", "otio", "drt", "edl", "prproj")


def _dados() -> Path:
    """A pasta de DADOS (o registro dos trazidos, as pastas lembradas): o app nunca a apaga."""
    p = plataforma.pasta_dados()
    p.mkdir(parents=True, exist_ok=True)
    return p


def _recebidos() -> Path:
    """As timelines geradas, de passagem (DRT, `.midias.json`, `.nova.json`): no CACHE (organograma
    de 2026-10-05, `cache.py`). ⚠️ A casca do Resolve só importa DRT DESTA pasta (`drtConfiavel`)."""
    import cache

    return cache.sub(cache.RECEBIDOS)


def _abrir_espaco(drt: Path) -> None:
    """Antes de escrever uma timeline nova, o teto do cache (LRU): sai o que foi usado há mais
    tempo — nunca uma conferência em curso."""
    import cache
    from conferencia import conferencias

    cache.talvez_aplicar_teto(protegidos=[drt, *conferencias().em_uso()])


class Cancelado(Exception):
    """O editor apertou Cancelar enquanto o Trazer preparava."""


#: As etapas do Trazer, na ordem em que o painel as mostra. A última ("importando") é da
#: casca do NLE, não daqui — o painel a acrescenta.
#: `baselight`: o conform no Baselight (job, bl-conform, conferência, markers — `baselight_conform.py`)
ETAPAS = ("lendo", "indexando", "casando", "midia", "montando", "baselight")


def nome_do_projeto(p: Path) -> str:
    """O nome do PROJETO de um arquivo de timeline: o `.prproj` é o projeto (o nome dele); a bin do Avid mora na pasta do
    projeto do MC (a que tem o `.avp`, subindo no máximo 3 níveis — bins em subpastas); AAF e xmeml não dizem o projeto:
    o nome do arquivo."""
    if p.suffix.lower() == ".avb":
        d = p.parent
        for _ in range(3):
            try:
                if any(x.suffix.lower() == ".avp" for x in d.iterdir()):
                    return d.name
            except OSError:
                break
            d = d.parent
        return p.parent.name
    return p.stem


class SessaoReceber:
    def __init__(self) -> None:
        self._cache: dict[str, tuple[tuple, dict]] = {}    # caminho → (assinatura, resumo)
        self._por_id: dict[str, str] = {}                  # id do envio → caminho
        self._tipo_por_id: dict[str, str] = {}             # id do envio → tipo (para arquivar)
        self._copias: dict[str, list[str]] = {}            # id → outras cópias PENDENTES dele
        self._ultima_procura: dict = {}
        self._avulsos: dict[str, tuple[str, str]] = {}     # chave → ("carta"|"avb", caminho)
        # A análise do `.prproj` (ler + casar com os originais) que a tela "antes de montar"
        # mostrou: o `preparar_avulso` monta A PARTIR DELA, sem sondar tudo de novo.
        self._analise: tuple | None = None                 # (chave, sequência, pastas, análise)
        # Premiere → Premiere: o plano de cada cópia relinkada preparada (id → plano), que `/premiere/copia` executa
        self._relinks: dict[str, dict] = {}
        #: o envio para a CARTA (plano 2026-11-26, etapa 1): o que o `/premiere/montar` repassa ao núcleo
        self._cartas_premiere: dict[str, dict] = {}
        self._lock = threading.Lock()
        # O andamento do Trazer. Lido por `GET /receber/progresso` enquanto o `preparar` corre
        # noutra thread do servidor (ThreadingHTTPServer), por isso é trocado inteiro, nunca
        # editado no lugar.
        self._progresso: dict = {"ativo": False}
        self._cancelar = threading.Event()

    # ── andamento ──────────────────────────────────────────────────────────────

    def progresso(self) -> dict:
        return dict(self._progresso)

    def cancelar(self) -> bool:
        if not self._progresso.get("ativo"):
            return False
        self._cancelar.set()
        return True

    def _etapa(self, etapa: str, feitos: int = 0, total: int = 0, atual: str = "",
               detalhe: str = "", **extra) -> None:
        """`atual` = o arquivo em que o motor está (o painel mostra o nome e a pasta); `detalhe` =
        o que está sendo feito, em palavras, quando não há arquivo (pedido do autor, 2026-10-04:
        "o que está acontecendo? quais arquivos estão sendo lidos? o que está sendo escrito?")."""
        if self._cancelar.is_set():
            raise Cancelado("cancelado")
        self._progresso = {"ativo": True, "etapa": etapa, "indice": ETAPAS.index(etapa) + 1,
                           "etapas": len(ETAPAS) + 1, "feitos": feitos, "total": total,
                           "atual": os.path.basename(atual) if atual else "",
                           "pasta": os.path.dirname(atual) if atual else "", "detalhe": detalhe,
                           **extra}

    # ── o que já foi trazido (só nesta máquina) ────────────────────────────────

    def trazidos(self) -> dict[str, str]:
        fora: dict[str, str] = {}
        try:
            for linha in (_dados() / REGISTRO).read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(linha)
                except ValueError:
                    continue
                if isinstance(r, dict) and r.get("ok") and isinstance(r.get("id"), str):
                    fora[r["id"]] = str(r.get("em") or "")
        except OSError:
            pass
        return fora

    def trazido(self, id_envio: str, ok: bool, detalhe: str = "",
                timeline: dict | None = None, substitui: str = "") -> dict:
        """Anota o resultado (só nesta máquina) e, se entrou, ARQUIVA a Carta pendente.

        ⭐ Arquivar é polimento: a timeline já está no NLE. Se a rede recusar o mover, a Carta
        fica na fila, marcada como trazida aqui, e o painel diz por quê — nunca derruba o Trazer.
        """
        if not RE_ID.match(id_envio or ""):
            raise ValueError("envio inválido")
        linha = json.dumps({"id": id_envio, "ok": bool(ok), "detalhe": str(detalhe)[:300],
                            "em": datetime.now().astimezone().isoformat(timespec="seconds")},
                           ensure_ascii=False)
        with self._lock, open(_dados() / REGISTRO, "a", encoding="utf-8") as fh:
            fh.write(linha + "\n")
        caminho = self._por_id.get(id_envio)
        if not caminho:
            # Revisão 2026-09-28: o registro reenviado logo depois de o serviço reiniciar chegava
            # antes do "Procurar novos", com `_por_id` vazio — e a partida não era guardada, calada.
            self.caixa()
            caminho = self._por_id.get(id_envio)
        tipo = self._tipo_por_id.get(id_envio, "timeline")
        partida = None
        if ok and caminho and tipo == "timeline":
            # ⭐ A Carta de PARTIDA do "Atualizar timeline": copiada ANTES de arquivar (o arquivar
            # muda o caminho). Guardar é acessório: se falhar, a timeline já entrou.
            try:
                import partidas
                resumo = (self._cache.get(caminho) or (None, {}))[1] or {}
                partida = partidas.guardar(id_envio, caminho, resumo, timeline)
                if substitui and substitui != id_envio:
                    partidas.aposentar(substitui)     # a timeline dela foi para o Backup
            except (OSError, ValueError) as e:
                log.warning("não consegui guardar a partida de %s: %s", id_envio, e)
        if not ok or not caminho or not canais.e_pendente(caminho):
            return {"arquivado": None, "partida": partida}
        try:
            novo = canais.arquivar(caminho, tipo)
        except OSError as e:
            log.warning("não consegui arquivar %s: %s", caminho, e)
            return {"arquivado": None,
                    "aviso": "a timeline entrou, mas não consegui mover a Carta para "
                             f"'importado' ({e.strerror or e}) — ela fica na fila"}
        self._por_id[id_envio] = novo
        if caminho in self._cache:
            self._cache[novo] = self._cache[caminho]
        for copia in self._copias.pop(id_envio, []):
            try:
                canais.arquivar(copia, tipo)
            except OSError as e:
                log.warning("não consegui arquivar a cópia %s: %s", copia, e)
        return {"arquivado": novo, "partida": partida}

    # ── Atualizar timeline ──────────────────────────────────────────────────────

    def partidas_para(self, id_envio: str = "", timeline: dict | None = None) -> dict:
        """As versões ANTIGAS sugeridas, a mais provável primeiro. Quem escolhe é quem recebe.

        Com a `timeline` de trabalho (`{uid, nome}`), a sugestão é a partida DELA (organograma de
        2026-09-28). Sem ela, a Carta nova `id_envio` sugere pela sequência e pelo nome."""
        import partidas
        t = timeline if isinstance(timeline, dict) else {}
        dela = partidas.da_timeline(str(t.get("uid") or ""), str(t.get("nome") or "")) if t else []
        resto: list[dict] = []
        if id_envio:
            caminho = self._caminho(id_envio)
            resumo = (self._cache.get(caminho) or (None, {}))[1] or {}
            resto = partidas.sugerir({**resumo, "id": id_envio})
        elif not dela:
            resto = [{**x, "motivo": "recente"} for x in partidas.listar()]
        vistos = {x["id"] for x in dela}
        return {"partidas": dela + [x for x in resto if x["id"] not in vistos]}

    # ── as duas versões do Atualizar (organograma de 2026-09-28: dois arquivos) ────────────────
    #
    # Uma versão é `{envio}` (a Carta do canal), `{partida}` (a cópia guardada nesta máquina) ou
    # `{avulso, mob_id}` (um arquivo aberto por "Escolher…": Carta ou bin). Não importa se a
    # timeline de trabalho entrou pelo De Lá Pra Cá, nem se quem enviou tem o programa.

    def carta_da_versao(self, versao) -> tuple:
        """`(carta, familia)`. A `familia` é o "mesmo formato" das duas versões."""
        import partidas
        from carta_aberta.reader import ler_carta

        v = versao if isinstance(versao, dict) else {}
        if v.get("partida"):
            pid = str(v["partida"])
            return ler_carta(partidas.carta(pid)), partidas.familia(pid)
        if v.get("avulso"):
            chave = str(v["avulso"])
            if not RE_ID.match(chave):
                raise ValueError("arquivo inválido")
            # o tipo e o caminho lidos UMA vez, sob a trava: outro "Escolher…" pode tirar esta chave
            # da lista no meio (MAX_AVULSOS) — revisão 2026-09-28
            with self._lock:
                guardado = self._avulsos.get(chave)
            if guardado is None:
                raise LookupError("escolha o arquivo de novo (o serviço foi reiniciado ou abriu muitos)")
            tipo, caminho = guardado
            carta = _carta_avulsa(tipo, caminho, str(v.get("mob_id") or ""))
            return carta, FAMILIA[tipo]
        if v.get("envio"):
            return ler_carta(self._caminho(str(v["envio"]))), "avid"
        raise ValueError("escolha a versão antiga e a nova")

    def _duas_versoes(self, antiga, nova) -> tuple:
        velha, fam_a = self.carta_da_versao(antiga)
        nova_c, fam_n = self.carta_da_versao(nova)
        if fam_a != fam_n:
            raise ValueError(f"a versão antiga é {ROTULO_FAMILIA.get(fam_a, fam_a)} e a nova é "
                             f"{ROTULO_FAMILIA.get(fam_n, fam_n)}: use o mesmo formato nas duas")
        return velha, nova_c, fam_n

    def comparar_versoes(self, antiga, nova, contar_audio: bool = False, trabalho: str = "",
                         contagem_api: dict | None = None, inicio: int | None = None) -> dict:
        """O resumo que decide antes de mexer (`motor/atualizar.py`). Com a timeline de `trabalho`
        (o DRT que a casca exportou, sem mudar nada), vem junto o `encaixe`: se a versão antiga não
        bate, o painel mostra por quê e não deixa atualizar."""
        import atualizacao
        import atualizar
        import partidas

        velha, nova_c, _familia = self._duas_versoes(antiga, nova)
        # a MESMA regra da execução (`atualizacao.devolvido_por`): o resumo que se aprova descreve o
        # que se aplica (revisão 2026-09-28)
        devolvido = atualizacao.devolvido_por({**velha.arquivos, **nova_c.arquivos})
        r = atualizar.comparar(velha.resultado, nova_c.resultado, contar_audio=contar_audio,
                               devolvido=devolvido, faixas=partidas.faixas())
        mudados = [p for p in r["planos"] if p["classe"] not in (atualizar.IGUAL, atualizar.DESLOCADO)]
        fora = {**{k: v for k, v in r.items() if k != "planos"}, "mudados": mudados[:500],
                "faixas": list(partidas.faixas()), "nome": _nome_da_timeline(nova_c, nova_c.tipo)}
        if trabalho:
            recebidos = _recebidos()
            arq = atualizacao.arquivo_de_trabalho(trabalho, recebidos)
            _ini, _itens, _no, itens_c = atualizacao.ler_trabalho(velha, arq, contagem_api or {}, inicio)
            e = atualizacao.encaixe(velha, itens_c, {**velha.arquivos, **nova_c.arquivos})
            fora["encaixe"] = {**e, "texto": "" if e["bate"] else atualizacao.texto_nao_bate(e)}
        return fora

    def preparar_versoes(self, antiga, nova, trabalho: str, contagem_api: dict,
                         sinais: dict | None = None, inicio: int | None = None) -> dict:
        """A execução do Atualizar, lado do serviço (`atualizacao.py`): confere o arquivo que a
        casca exportou, reescreve a timeline do colorista e diz o que inserir e sinalizar."""
        import atualizacao
        import codigo_de_cores

        recebidos = _recebidos()
        recebidos.mkdir(exist_ok=True)
        trabalho = atualizacao.arquivo_de_trabalho(trabalho, recebidos)
        velha, nova_c, familia = self._duas_versoes(antiga, nova)
        plano = atualizacao.preparar(velha, nova_c, trabalho, contagem_api, recebidos,
                                     lambda carta: self._midia_da_carta(carta, recebidos, com_metas=True),
                                     sinais=sinais, codigo=codigo_de_cores.ler(), inicio=inicio)
        # A timeline atualizada leva o nome que o editor deu à versão NOVA, como no Trazer
        # (`_nome_da_timeline`). Antes ela herdava o da antiga: a v03 chegava como "…-v01"
        # (autor, 2026-09-28).
        fora = {**plano, "nome": _nome_da_timeline(nova_c, nova_c.tipo)}
        if not (isinstance(nova, dict) and nova.get("envio")):
            # ⭐ A versão nova de um arquivo do disco só existe na memória do serviço (a `chave`): se
            # ele reiniciar antes do registro, o reenvio falharia para sempre (revisão 2026-09-28).
            # A Carta dela fica em disco, ao lado do DRT, e o registro aponta para cá.
            registro = Path(plano["drt"]).stem
            (recebidos / f"{registro}.nova.json").write_text(json.dumps(
                {"doc": nova_c.doc, "familia": familia,
                 "resumo": {"nome": fora["nome"],
                            "sequencia": nova_c.resultado.get("composition_name") or "",
                            "mob_id": str(nova_c.resultado.get("sequence_mob_id") or "")}},
                ensure_ascii=False), encoding="utf-8")
            fora["registro"] = registro
        return fora

    def atualizada(self, nova, timeline: dict | None, substitui: str = "", registro: str = "") -> dict:
        """A casca atualizou: a versão NOVA passa a ser a partida da timeline (a próxima atualização
        a sugere sozinha). Do canal, é o `trazido` de sempre (que também arquiva a Carta); de um
        arquivo do disco, a Carta que o `preparar_versoes` deixou em `recebidos/<registro>.nova.json`."""
        import partidas

        v = nova if isinstance(nova, dict) else {}
        if v.get("envio"):
            r = self.trazido(str(v["envio"]), True, "atualizar", timeline=timeline,
                             substitui=substitui)
            if r.get("partida") is None:
                raise LookupError("a timeline foi atualizada, mas a Carta nova não está mais na pasta "
                                  "do canal: esta máquina não guardou de onde ela veio")
            return r
        if not RE_ID.match(registro or ""):
            raise ValueError("registro inválido")
        guardado = _recebidos() / f"{registro}.nova.json"
        try:
            d = json.loads(guardado.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raise LookupError("a Carta da versão nova não está mais nesta máquina") from None
        partida = partidas.guardar_doc(d["doc"], d.get("resumo") or {}, timeline, d.get("familia") or "avid")
        if substitui and substitui != partida["id"]:
            partidas.aposentar(substitui)
        return {"arquivado": None, "partida": partida}

    def _midia_da_carta(self, carta, pasta: Path, com_metas: bool = False) -> tuple:
        """A mídia DESTA máquina para cada plano da Carta: o mesmo caminho do Importar (a
        gerenciada daqui, depois o AMA do remetente, se passar pela tranca e existir aqui).
        `com_metas`: devolve também os metadados dos rótulos OFFLINE (o Atualizar os insere no lugar)."""
        from avb_bin.segmentos import caminho_confiavel, montar_midia
        from media import pmr

        def existe_aqui(c: str) -> str | None:
            seguro, _motivo = caminho_confiavel(c or "")
            if seguro and not os.path.isfile(seguro) and sys.platform == "darwin" and seguro.startswith("/") \
                    and not seguro.startswith("/Volumes/"):
                # ⚠️ o AAF do MC no Mac grava o caminho SEM o `/Volumes` (`/SSD/…`): sem isto o arquivo do
                # master nunca "existia aqui" (BL09 pelo MC, 2026-11-23; o mesmo de `media.matcher._daily_do_segmento`)
                seguro = "/Volumes" + seguro
            return seguro if seguro and os.path.isfile(seguro) else None

        gerenciados = dict(pmr.indice_de(pmr.raizes_de_midia()).por_arquivo or {})
        for urn, mxf in carta.gerenciados.items():
            if urn not in gerenciados and (aqui := existe_aqui(mxf)):
                gerenciados[urn] = aqui
        arquivos = {k: aqui for k, c in carta.arquivos.items() if (aqui := existe_aqui(c))}
        colunas = {k: {**c, "Source Path": _pasta_de_referencia(c.get("Source Path"))}
                   for k, c in carta.colunas_por_mob.items() if isinstance(c, dict)}
        segs, casados, metas = montar_midia(carta.resultado, arquivos, str(pasta), colunas, gerenciados)
        return (segs, casados, metas) if com_metas else (segs, casados)

    def _caminho(self, id_envio: str) -> str:
        if not RE_ID.match(id_envio or ""):
            raise ValueError("envio inválido")
        caminho = self._por_id.get(id_envio)
        if not caminho:
            self.caixa()
            caminho = self._por_id.get(id_envio)
        if not caminho:
            raise LookupError("esse envio não está mais na pasta do canal — procure de novo")
        return caminho

    # ── Procurar novos ─────────────────────────────────────────────────────────

    def caixa(self, canais_cfg: dict | None = None) -> dict:
        """Tudo o que está nos canais conectados, nos DOIS sentidos, numa lista só.

        `{canais: [{setor, rotulo, pasta, conectado, erro?}], envios: [linha], invalidas,
        cortado}`. Cada linha é o resumo da Carta mais `canal`, `de`, `para` (`edicao` ou o
        setor) e `importado`. Quem filtra (Da Edição, Da Cor, Já importados…) é o painel. Sem
        argumento, repete a última procura (o `preparar` usa isso para achar um id que sumiu).
        """
        if canais_cfg is None:
            # Sem procura nesta sessão (o serviço acabou de subir): os canais DESTA máquina, os do
            # receptor. Revisão 2026-09-28: o registro reenviado logo após reiniciar procurava numa
            # lista vazia e a partida não era guardada.
            canais_cfg = self._ultima_procura or canais.canais_da_maquina()
        self._ultima_procura = dict(canais_cfg)
        self._copias = {}
        trazidos = self.trazidos()
        canais_fora, envios, invalidas, cortado = [], [], [], False
        vistos: set[str] = set()
        for setor, s in canais.SETORES.items():
            item = {"setor": setor, "rotulo": s["rotulo"], "de": s["de"],
                    "pasta": canais_cfg.get(setor), "conectado": False}
            canais_fora.append(item)
            pasta = canais.pasta_do_canal(canais_cfg, setor)
            if not pasta:
                continue
            try:
                canais.garantir_pastas(pasta, setor)
            except OSError as e:
                item["erro"] = f"não consegui preparar a pasta do canal: {e.strerror or e}"
                continue
            item["conectado"] = True
            # A caixa `para-X` guarda o que foi PARA X — então veio do outro lado.
            for para in canais.lados(setor):
                de = setor if para == canais.EDICAO else canais.EDICAO
                caixa = Path(pasta) / canais.caixa_nome(para)
                try:
                    pendentes, ruins, cortou = self._ler_pasta(caixa)
                    importados: list[tuple[dict, str]] = []
                    for sub in sorted(set(canais.SUBPASTA.values())):
                        lidos, ruins2, _c = self._ler_pasta(caixa / canais.IMPORTADO / sub)
                        importados += lidos
                        ruins += ruins2
                except RuntimeError as e:
                    item["erro"] = str(e)
                    continue
                invalidas += ruins
                cortado = cortado or cortou
                for resumo, caminho in pendentes + importados:
                    if resumo["id"] in vistos:          # a mesma Carta copiada duas vezes
                        if canais.e_pendente(caminho):  # …arquiva junto com a primeira
                            self._copias.setdefault(resumo["id"], []).append(caminho)
                        continue
                    vistos.add(resumo["id"])
                    self._por_id[resumo["id"]] = caminho
                    self._tipo_por_id[resumo["id"]] = resumo["tipo"]
                    anexo = Path(caminho).with_name(Path(caminho).name[:-len(SUFIXO)] + ".avb") \
                        if Path(caminho).name.endswith(SUFIXO) else None
                    envios.append({**resumo, "canal": setor, "de": de, "para": para,
                                   "importado": not canais.e_pendente(caminho),
                                   "trazido_em": trazidos.get(resumo["id"]),
                                   # a bin do Avid que veio junto (Magic Link Avid → Avid): o MC relinka por ela
                                   "bin_anexa": str(anexo) if anexo is not None and anexo.is_file() else ""})
        envios.sort(key=lambda r: r.get("enviado_em") or "", reverse=True)
        return {"canais": canais_fora, "envios": envios, "invalidas": invalidas,
                "cortado": cortado, "lados": canais.ROTULO_LADO}

    def _ler_pasta(self, pasta: Path) -> tuple[list[tuple[dict, str]], list[dict], bool]:
        """`([(resumo, caminho)], invalidas, cortado)` das Cartas de UM nível de `pasta`."""
        from carta_aberta.reader import LIMITE_BYTES, CartaInvalida, ler_carta

        validas, invalidas = [], []
        with self._lock:
            try:
                candidatos = []
                for p in pasta.iterdir():
                    # ⚠️ `._NOME.carta.json`: o AppleDouble que o macOS grava ao lado de todo
                    # arquivo em pasta de rede (SMB) e exFAT (matriz de plataforma, linha
                    # "appledouble"). Não é Carta: cada envio de um Mac virava mais um "arquivo
                    # ilegível" na caixa do Windows (revisão ampla, 2026-09-30).
                    if not p.name.endswith(SUFIXO) or p.name.startswith("._"):
                        continue
                    try:
                        if p.is_symlink() or not p.is_file():
                            continue
                        candidatos.append((p, p.stat()))
                    except OSError:
                        continue
            except FileNotFoundError:
                return [], [], False
            except OSError as e:
                raise RuntimeError(f"não consegui ler a pasta do canal: {e.strerror or e}") from None
            candidatos.sort(key=lambda x: x[1].st_mtime_ns, reverse=True)
            cortado = len(candidatos) > MAX_ARQUIVOS
            for p, st in candidatos[:MAX_ARQUIVOS]:
                assinatura = (st.st_size, st.st_mtime_ns)
                guardado = self._cache.get(str(p))
                if guardado and guardado[0] == assinatura:
                    resumo = guardado[1]
                else:
                    if st.st_size > LIMITE_BYTES:
                        resumo = {"arquivo": p.name, "erro": "carta grande demais"}
                    else:
                        try:
                            resumo = _resumir(ler_carta(p), p.name)
                        except CartaInvalida as e:
                            resumo = {"arquivo": p.name, "erro": str(e)}
                        except Exception:  # noqa: BLE001 — ataque V4: UM arquivo não derruba a caixa
                            log.warning("carta ilegível no canal: %s", p.name, exc_info=True)
                            resumo = {"arquivo": p.name, "erro": "carta ilegível"}
                    self._cache[str(p)] = (assinatura, resumo)
                if resumo.get("erro"):
                    invalidas.append(resumo)
                else:
                    validas.append((resumo, str(p)))
        return validas, invalidas, cortado

    # ── Trazer ─────────────────────────────────────────────────────────────────

    def carta_do_pedido(self, pedido: dict):
        """A Carta de um Importar: `{id}` (um envio de canal) ou `{avulso, mob_id}` (um arquivo
        aberto). É o que o casamento com os originais lê ANTES do Trazer (ADR 0020)."""
        from carta_aberta.reader import ler_carta

        if pedido.get("avulso"):
            chave = str(pedido.get("avulso") or "")
            if not RE_ID.match(chave):
                raise ValueError("arquivo inválido")
            guardado = self._avulsos.get(chave)
            if guardado is None:
                raise LookupError("abra o arquivo de novo")
            tipo, caminho = guardado
            return _carta_avulsa(tipo, caminho, str(pedido.get("mob_id") or ""))
        id_envio = str(pedido.get("id") or "")
        if not RE_ID.match(id_envio):
            raise ValueError("envio inválido")
        caminho = self._por_id.get(id_envio)
        if not caminho:
            self.caixa()
            caminho = self._por_id.get(id_envio)
        if not caminho:
            raise LookupError("esse envio não está mais no canal — procure de novo")
        return ler_carta(caminho)

    def preparar(self, id_envio: str, originais: dict | None = None,
                 raizes: list[str] | None = None, notas: bool = False,
                 sinais: dict | None = None) -> dict:
        """A Carta `id_envio` → um DRT temporário com a mídia DESTA máquina.

        Um Trazer por vez: um segundo pedido enquanto o primeiro corre é recusado, e o
        andamento fica em `progresso()` até o fim (sucesso, erro ou cancelamento).
        `originais` (`{master: arquivo}`) são os que o colorista decidiu relinkar ao
        importar, dentro das pastas `raizes` que ele escolheu (ADR 0020).
        """
        if not RE_ID.match(id_envio or ""):
            raise ValueError("envio inválido")
        with self._lock:
            if self._progresso.get("ativo"):
                raise RuntimeError("já estou trazendo outra timeline — espere ela terminar")
            self._cancelar.clear()
            self._progresso = {"ativo": True, "etapa": "lendo", "indice": 1,
                               "etapas": len(ETAPAS) + 1, "feitos": 0, "total": 0}
        try:
            return self._preparar(id_envio, originais, raizes, notas, sinais)
        finally:
            self._progresso = {"ativo": False}
            self._cancelar.clear()

    def _preparar(self, id_envio: str, originais: dict | None = None,
                  raizes: list[str] | None = None, notas: bool = False,
                  sinais: dict | None = None) -> dict:
        from carta_aberta.reader import ler_carta

        self._etapa("lendo")
        caminho = self._por_id.get(id_envio)
        if not caminho:
            self.caixa()
            caminho = self._por_id.get(id_envio)
        if not caminho:
            raise LookupError("esse envio não está mais no canal — procure de novo")
        carta = ler_carta(caminho)
        if (carta.envio or {}).get("id") != id_envio:
            raise LookupError("a carta mudou desde a última procura — procure de novo")
        return self._montar(carta, id_envio, originais, raizes, notas=notas, sinais=sinais)

    # ── Abrir arquivo… (fora do Magic Link) ─────────────────────────────────────

    def abrir(self, caminho: str) -> dict:
        """`_abrir_arquivo` + o `projeto`: o nome que o Baselight usa de job quando a Carta não traz a produção (autor,
        2026-11-23: "pode usar o nome do projeto no job" — antes o job do envio ANTERIOR ficava, e o PRODC ia para o job
        do PRODUCAO-A)."""
        r = self._abrir_arquivo(caminho)
        if isinstance(r, dict) and not r.get("cancelado"):
            r.setdefault("projeto", nome_do_projeto(Path(caminho or "")))
        return r

    def _abrir_arquivo(self, caminho: str) -> dict:
        """O que há no arquivo que o editor escolheu: uma Carta, ou as sequências de uma bin.

        Não prepara nada: devolve uma `chave` que o `preparar_avulso` usa. ⚠️ O arquivo é
        texto de terceiro como a Carta de um canal — ele passa pelo MESMO `_montar`, e
        nenhum caminho de dentro dele é tocado sem `caminho_confiavel`.
        """
        from carta_aberta.reader import CartaInvalida, ler_carta

        p = Path(caminho or "")
        if not p.is_absolute() or not p.is_file():
            raise ValueError("esse arquivo não existe ou não está acessível agora")
        nome = p.name.lower()
        if nome.endswith(".avb"):
            seqs = _sequencias_da_bin(p)
            if not seqs:
                raise ValueError(f"a bin {p.name} não tem nenhuma sequência")
            return {"tipo": "avb", "arquivo": p.name,
                    "chave": self._guardar_avulso("avb", p), "sequencias": seqs}
        if nome.endswith(".aaf"):
            # Organograma de 2026-09-28: o AAF do editor que não tem o De Lá Pra Cá. Uma composição
            # por AAF (a que o Media Composer exporta); a leitura é a da bin (`aaf/leitura.py`).
            carta = _carta_do_aaf(str(p))
            return {"tipo": "aaf", "arquivo": p.name, "chave": self._guardar_avulso("aaf", p),
                    "nome": _nome_da_timeline(carta, carta.tipo), **_leitura_rapida(carta)}
        if nome.endswith(".prproj"):
            # Organograma de 2026-10-02 (atualizado em 2026-10-03): o projeto do Premiere, lido
            # direto, sem abrir o Premiere. As sequências de montagem (sem merged, sem take).
            from prproj.leitura import Leitor
            from prproj.projeto import Projeto
            try:
                seqs = Leitor(Projeto(str(p))).sequencias_de_montagem()
            except Exception as e:                    # noqa: BLE001 — arquivo de terceiro
                log.warning("prproj ilegível %s: %s: %s", p, type(e).__name__, e)
                raise ValueError(f"não consegui ler {p.name} como projeto do Premiere") from None
            if not seqs:
                raise ValueError(f"o projeto {p.name} não tem nenhuma sequência de montagem")
            return {"tipo": "prproj", "arquivo": p.name, "chave": self._guardar_avulso("prproj", p),
                    # `mob_id` = o ObjectUID: duas sequências podem ter o mesmo nome
                    "sequencias": [{"mob_id": x["uid"] or x["nome"], "nome": x["nome"],
                                    "duracao": _duracao(x.get("duracao_s") or 0),
                                    "planos": x["planos"]} for x in seqs],
                    # decisão do autor (2026-10-03): o mesmo projeto volta com as mesmas pastas
                    "pastas": pastas_do_projeto(str(p))}
        if nome.endswith(".xml"):
            # ⭐ O xmeml da CARTA ABERTA para o Baselight (etapa 3 da proposta 2026-11-22-baselight-no-app): o
            # "Conformar com De Lá Pra Cá" da Carta chega aqui. Só o destino Baselight o monta (`_baselight_xmeml`).
            from baselight import xmeml

            if not xmeml.e_xmeml(str(p)):
                raise ValueError(f"{p.name} não é um xmeml (FCP7) — o XML que abro é o da Carta Aberta")
            try:
                le = xmeml.ler(str(p))
            except (ET_ParseError, ValueError) as e:
                raise ValueError(f"não consegui ler {p.name}: {e}") from None
            fim = max((_frames_do_tc(x["timeline_tc_in"], round(le["fps"])) + x["duration_frames"]
                       for x in le["segmentos"]), default=0)
            return {"tipo": "xmeml", "arquivo": p.name, "chave": self._guardar_avulso("xmeml", p),
                    "sequencias": [{"mob_id": le["nome"], "nome": le["nome"],
                                    "duracao": _duracao(fim / (le["fps"] or 25)), "planos": len(le["segmentos"])}],
                    "pastas": pastas_do_projeto(str(p))}
        if nome.endswith(".json"):
            try:
                carta = ler_carta(p)
            except CartaInvalida as e:
                raise ValueError(f"{p.name}: {e}") from None
            return {"tipo": "carta", "arquivo": p.name, "chave": self._guardar_avulso("carta", p),
                    "nome": _nome_da_timeline(carta, carta.tipo), "envio": carta.tipo,
                    "producao": str((carta.doc or {}).get("producao") or "")[:100],
                    **_leitura_rapida(carta)}
        ext = p.suffix.lower().lstrip(".")
        if ext in EXTENSOES_RECEBER:
            raise ValueError(f"o {ext.upper()} ainda não — por enquanto abro a Carta Aberta (.json), a bin "
                             "do Avid (.avb), o AAF e o projeto do Premiere (.prproj)")
        raise ValueError("abro a Carta Aberta (.json), a bin do Avid (.avb), o AAF e o projeto do "
                         "Premiere (.prproj)")

    def _guardar_avulso(self, tipo: str, caminho: Path) -> str:
        import uuid

        chave = str(uuid.uuid4())
        with self._lock:
            self._avulsos[chave] = (tipo, str(caminho))
            while len(self._avulsos) > MAX_AVULSOS:      # o dict guarda a ordem de entrada
                self._avulsos.pop(next(iter(self._avulsos)))
        return chave

    def analisar_carta(self, pedido: dict) -> dict:
        """AAF, bin e Carta na tela "antes de montar" (organograma de 2026-10-19: um fluxo para todo protocolo): o
        resumo da leitura. O casamento com os originais é o do relink do Avid (`/receber/originais`), por master."""
        carta = self.carta_do_pedido(pedido)
        return {"sequencia": _nome_da_timeline(carta, carta.tipo), **resumo_da_carta(carta)}

    # ── o projeto do Premiere: analisar (a tela "antes de montar") e montar ──────

    def analisar_prproj(self, chave: str, sequencia: str, pastas: list[str]) -> dict:
        """Ler a sequência e casar cada proxy com o original nas `pastas` (uma ou várias). É a
        etapa lenta (um ffprobe por candidato); o resumo vai para a tela "antes de montar"."""
        from avb_bin.segmentos import caminho_confiavel
        from tools.prproj_para_drt import analisar

        if not RE_ID.match(chave or ""):
            raise ValueError("arquivo inválido")
        with self._lock:
            guardado = self._avulsos.get(chave)
            if guardado is None or guardado[0] not in ("prproj", "xmeml"):
                raise LookupError("abra o projeto de novo")
            if self._progresso.get("ativo"):
                raise RuntimeError("já estou trazendo outra timeline — espere ela terminar")
            self._cancelar.clear()
            self._progresso = {"ativo": True, "etapa": "lendo", "indice": 1,
                               "etapas": len(ETAPAS) + 1, "feitos": 0, "total": 0}
        try:
            self._etapa("lendo", sequencia=sequencia, atual=guardado[1],
                        detalhe=f"lendo a sequência “{sequencia}” do projeto do Premiere")
            if guardado[0] == "xmeml":
                return self._analisar_xmeml(chave, guardado[1], sequencia, list(pastas))
            try:
                a = analisar(guardado[1], sequencia, list(pastas),
                             progresso=lambda f, t, atual="": self._etapa(
                                 "casando", f, t, sequencia=sequencia, atual=atual,
                                 detalhe="procurando o original deste proxy nas pastas escolhidas"),
                             confiavel=caminho_confiavel)
            except KeyError:
                raise ValueError("essa sequência não está mais no projeto — abra-o de novo") from None
            with self._lock:
                self._analise = (chave, sequencia, tuple(pastas), a)
            # os ignorados que este projeto lembra, só os que estão nesta sequência
            presentes = set(a["casamento"])
            return {"sequencia": a["leitura"]["nome"], "pastas": list(pastas), **a["resumo"],
                    "ignorados": [x for x in ignorados_do_projeto(guardado[1]) if x in presentes]}
        finally:
            self._progresso = {"ativo": False}
            self._cancelar.clear()

    def _montar_prproj(self, chave: str, caminho: str, sequencia: str,
                       sinais: dict | None, notas: bool = False) -> dict:
        import uuid

        import codigo_de_cores
        from drp.writer import _audio_meta, _media_meta
        from tools.prproj_para_drt import faltam_sem_ignorados, montar, no_disco

        with self._lock:
            a = self._analise
        if not a or a[0] != chave or a[1] != sequencia:
            raise LookupError("analise a sequência de novo antes de montar")
        _chave, _seq, pastas, analise = a
        # A leitura dos arquivos ANTES do writer, contando (o writer só consulta o cache).
        arquivos = sorted({c["original"] for c in analise["casamento"].values()
                           if c.get("estado") == "original" and c.get("original")}
                          | {no_disco(p, c) for p, c in analise["casamento"].items()
                             if p and os.path.isfile(no_disco(p, c))})
        sons: list[str] = []
        if (sinais or {}).get("audio", True) is not False:
            # o som direto também é lido antes do writer (um ffprobe por WAV), contando
            fora = analise.get("sons") or {}
            sons = sorted({no_disco(x["media_ref"]["local_path"], fora.get(x["media_ref"]["local_path"]) or {})
                           for x in analise["leitura"]["segmentos"]
                           if x.get("is_audio") and x.get("media_ref")
                           and x["media_ref"].get("local_path")} - set(arquivos))
        # UMA contagem: a barra da etapa não volta
        fila = [(f, _audio_meta) for f in sons if os.path.isfile(f)] + [(f, _media_meta) for f in arquivos]
        lidos = self._ler_em_paralelo(fila, sequencia)
        travar_se_o_motor_nao_le([(f, m) for f, ler, m in lidos if ler is _media_meta])
        res0 = analise["resumo"]
        self._etapa("montando", sequencia=sequencia,
                    detalhe=f"escrevendo a timeline do Resolve (DRT): {res0.get('planos', 0)} planos de "
                            f"vídeo{', o áudio' if (sinais or {}).get('audio', True) is not False else ''}"
                            f", efeitos, marcadores e títulos")
        saida = _recebidos()
        saida.mkdir(exist_ok=True)
        drt = saida / f"{uuid.uuid4()}.drt"
        _abrir_espaco(drt)
        sinais = sinais or {}
        # só os que são desta sequência: o painel não decide sobre arquivo que a análise não viu
        ignorar = {x for x in (sinais.get("ignorar") or []) if x in analise["casamento"]}
        # só o que a análise OFERECEU, e com o fator dela (o painel diz quais aceitou, não inventa fator)
        oferta = analise.get("escalas") or {}
        reescalar = {c: oferta[c]["fator"] for c in (sinais.get("reescalar") or {}) if c in oferta}
        proporcao = {c for c in (sinais.get("proporcao") or []) if c in (analise.get("proporcoes") or {})}
        r = montar(caminho, sequencia, str(drt), list(pastas), analise=analise,
                   marcar=bool(sinais.get("marcar")), colorir=bool(sinais.get("colorir")),
                   codigo_de_cores=codigo_de_cores.ler(), audio=sinais.get("audio", True) is not False,
                   referencia=sinais.get("referencia"),
                   som_da_referencia=None if sinais.get("som_referencia") == "nenhum"
                   else (sinais.get("som_referencia") or "A"),
                   compostos=sinais.get("compound", True) is not False,
                   andamento=lambda f, t, a, det: self._etapa("montando", feitos=f, total=t, atual=a,
                                                           detalhe=det, sequencia=sequencia),
                   ignorar=ignorar, notas=notas, reescalar=reescalar,
                   proporcao_do_arquivo=proporcao)
        lembrar_pastas(caminho, list(pastas))
        # A lista do projeto passa a ser a desta sequência + o que ele lembrava de OUTRAS sequências.
        de_outras = [x for x in ignorados_do_projeto(caminho) if x not in analise["casamento"]]
        lembrar_ignorados(caminho, de_outras + sorted(ignorar))
        res = analise["resumo"]
        # mídia primeiro, timeline depois: a mesma pré-importação da rota do Avid (autor, 2026-10-19: o pool em
        # Mídia › <timeline>, não solto em "De Lá Pra Cá")
        midias = _gravar_midias(drt, r.get("casados") or [], som_depois=True)
        self._etapa("montando", sequencia=sequencia, feitos=1, total=1)
        log.info("prproj %s › %s: %s — %d planos, %d no original, %d composições do Fusion",
                 os.path.basename(caminho), sequencia, drt, res["planos"], res["no_original"],
                 len(r["fusion"]))
        return {"drt": str(drt), "nome": analise["leitura"]["nome"], "tipo": "prproj",
                "pasta_no_resolve": "De Lá Pra Cá", "clipes": res["planos"],
                # os arquivos que entraram OFFLINE (nenhum segmento se perde: autor, 2026-10-06)
                "offline": len(r.get("offline") or []), "midias": midias, "nos_originais": res["no_original"],
                "na_gerenciada": 0, "titulos": 0, "notas": (r.get("drt") or {}).get("notas") or 0,
                "marcadores": (r.get("drt") or {}).get("marcadores") or 0,
                "segmentos_coloridos": (r.get("drt") or {}).get("segmentos_coloridos") or 0,
                # sem os ignorados (o "arquivo não encontrado" fica, ignorado ou não)
                "faltam": faltam_sem_ignorados(analise["casamento"], ignorar),
                "ignorados": len(ignorar),
                "reescalados": len(reescalar),
                "proporcao_do_arquivo": len(proporcao),
                "audio": {**(res.get("audio") or {}), **(r.get("audio") or {})},
                "referencia": (os.path.basename(sinais["referencia"]) if sinais.get("referencia")
                               else (res.get("referencia") or {}).get("arquivo")),
                # as composições do Fusion, uma por clipe, com o plano pronto (a casca executa)
                "fusion": [{k: g[k] for k in ("trilha", "quadro", "arquivo", "plano")}
                           for g in r["fusion"] if g.get("plano")],
                "fusion_recusadas": [f'{g["arquivo"]} ({g.get("erro") or "não montou"})'
                                     for g in r["fusion"] if not g.get("plano")],
                # os nests do Premiere a juntar em Compound Clip, DEPOIS do Fusion (a casca)
                "compostos": r.get("compostos") or [],
                # a cor no nó 1 do clipe (a casca, antes dos compounds): a LUT das camadas de ajuste e o Black & White
                # do Premiere como saturação 0
                "luts": [{k: x[k] for k in ("trilha", "quadro", "arquivo", "cube", "saturacao") if k in x}
                         for x in (r.get("luts") or [])],
                # a trilha do vídeo de referência (cobre tudo: a prova do bypass a desliga)
                "trilha_referencia": r.get("trilha_referencia"),
                # a conferência pela referência (organograma de 2026-10-04): o plano pronto; o
                # painel a dispara no fim do Importar (caixa marcada) ou pelo botão, depois
                "conferencia": _conferencia_de(r, analise["leitura"]["nome"]),
                # os do writer primeiro (a taxa da timeline, os títulos): mudam o que o editor vê
                "avisos": ((r.get("drt") or {}).get("avisos") or [])
                          + [x["texto"] for x in (r.get("avisos") or [])][:20]}

    def _copia_para_premiere(self, chave: str, caminho: str, sequencia: str, sinais: dict | None) -> dict:
        """PREMIERE → PREMIERE (organograma aprovado pelo autor em 2026-10-22): a cópia do `.prproj` com cada mídia
        apontando para o arquivo que a análise decidiu → o plano que `/premiere/copia` executa (a ponte importa a
        sequência dela no projeto ABERTO, numa bin do De Lá Pra Cá; a original fica intacta).

        O que a lista mostrou é o que vai: o original casado, o próprio arquivo (no lugar ou "mudou de lugar"), o do
        projeto achado noutra pasta sem prova (sem original), o som achado pela duração. O que nada achou fica com o
        caminho do projeto (entra offline no lugar: "nenhum segmento se perde"). O raster novo vai no `FrameRect`; a
        escala, a ponte corrige depois (o Premiere não a acompanha — banco, api-extendscript §RELINK)."""
        import uuid

        from prproj.copia import gravar_copia
        from prproj.originais import recusado, sondar
        from tools.prproj_para_drt import _proporcao_do_anexado, conferencia_da_analise, no_disco

        with self._lock:
            a = self._analise
        if not a or a[0] != chave or a[1] != sequencia:
            raise LookupError("analise a sequência de novo antes de montar")
        _chave, _seq, pastas, analise = a
        leitura = analise["leitura"]
        sinais = sinais or {}
        self._etapa("montando", sequencia=sequencia, detalhe="gravando a cópia relinkada do projeto")
        declarados = leitura.get("declarados") or {}
        fps = leitura["fps"]
        tpf = round(TICKS_POR_SEGUNDO / fps)
        # o que o PROJETO diz de cada arquivo de vídeo (o raster declarado) e onde cada um aparece na timeline
        no_projeto: dict[str, dict] = {}
        onde: dict[str, list[dict]] = {}
        for s in leitura["segmentos"]:
            ref = s.get("media_ref") or {}
            p = ref.get("local_path")
            if not p or s.get("is_gap") or s.get("is_transition") or s.get("referencia"):
                continue
            m = (s.get("prproj") or {}).get("midia")
            if m and not s.get("is_audio"):
                no_projeto.setdefault(p, m)
            onde.setdefault(p, []).append({"quadro": _frames_do_tc(s["timeline_tc_in"], round(fps)),
                                           "trilha": ("A" if s.get("is_audio") else "V") + str(s.get("track")),
                                           "plano": s.get("clip_name") or os.path.basename(p)})
        troca: dict[str, str] = {}
        decidido: dict[str, str] = {}          # caminho declarado → o arquivo que a timeline deve apontar
        raster: dict[str, tuple[int, int]] = {}
        escalas: dict[str, float | list[float]] = {}         # uniforme, ou [largura, altura] (o esticado)
        from prproj.leitura import Leitor
        from prproj.projeto import Projeto
        ao_quadro = Leitor(Projeto(caminho)).escalar_ao_quadro_por_midia()   # {FilePath: (com a política, sem)}
        video_de = {}                                          # caminho do projeto → um plano de vídeo dele
        for s in leitura["segmentos"]:
            q = (s.get("media_ref") or {}).get("local_path")
            if q and not (s.get("is_audio") or s.get("is_gap") or s.get("is_transition")):
                video_de.setdefault(q, s)
        marcas: list[dict] = []
        sem_escala: list[str] = []
        ignorar = {x for x in (sinais.get("ignorar") or []) if x in analise["casamento"]}

        def texto(p: str) -> str:              # o caminho como está ESCRITO no projeto (o recusado pela tranca também)
            return declarados.get(p, p) if recusado(p) else p

        def marcar(p: str, nome: str, nota: str) -> None:
            for x in onde.get(p, [])[:1]:
                marcas.append({**x, "nome": nome, "nota": nota})

        # só o que a análise OFERECEU, e com o fator dela (como na rota do Resolve: o painel diz o que aceitou)
        oferta = analise.get("escalas") or {}
        reescalar = {x: oferta[x]["fator"] for x in (sinais.get("reescalar") or {}) if x in oferta}
        proporcao = {x for x in (sinais.get("proporcao") or []) if x in (analise.get("proporcoes") or {})}
        so_offline = bool(sinais.get("so_offline"))
        for p, c in analise["casamento"].items():
            if so_offline and not recusado(p) and os.path.isfile(p):
                decidido[p] = p                     # online no projeto: o editor pediu "só offline", fica como está
                continue
            alvo = c["original"] if c.get("estado") in ("original", "proprio") else no_disco(p, c)
            if not alvo or recusado(alvo) or not os.path.isfile(alvo):
                marcar(p, "Arquivo não encontrado",
                       f"{os.path.basename(texto(p))}: entrou offline no lugar; religue no Premiere")
                continue
            decidido[texto(p)] = alvo
            if alvo != texto(p):
                troca[texto(p)] = alvo
            if c.get("estado") not in ("original", "proprio") and p not in ignorar:
                marcar(p, "Sem original", f"{os.path.basename(alvo)}: o arquivo do projeto, sem o original de câmera"
                                          + (f" ({c['duvida']})" if c.get("duvida") else ""))
            elif c.get("estado") == "original" and c.get("duvida"):
                # o convertido de TC zerado/ausente, a única mídia (2026-10-31): entra, a conferir
                marcar(p, "TC a conferir", f"{os.path.basename(alvo)}: {c['duvida']}")
            m = no_projeto.get(p) or {}
            if c.get("estado") in ("original", "proprio") and m.get("w") and m.get("h"):
                # A REGRA DO RESOLVE (`prproj_para_drt._encaixar_no_arquivo`, 144/144 no R04 de 2023), na unidade do
                # Premiere, cuja escala conta os pixels do ARQUIVO (autor, 2026-10-29: a cópia dava 14/143 sem ela).
                # Mesma proporção ou "proporção do arquivo" aceita: uniforme, encaixe do arquivo ÷ encaixe do original.
                # Outra proporção com o proxy que o Premiere anexou: ele o esticava sobre o raster declarado → por eixo.
                # Outra proporção sem o proxy anexado: o modo da conversão não está no projeto → marcador, como antes.
                # A escala digitada para outra mídia (a oferta aceita) multiplica por cima.
                info = sondar(alvo)
                w, h = info.get("w") or 0, info.get("h") or 0
                fator = float(reescalar.get(p) or 1.0)
                if w and h and ((w, h) != (m["w"], m["h"]) or fator != 1.0):
                    if (w, h) != (m["w"], m["h"]):
                        raster[alvo] = (w, h)
                    qw, qh = leitura.get("largura") or m["w"], leitura.get("altura") or m["h"]
                    e_o, e_f = min(qw / m["w"], qh / m["h"]), min(qw / w, qh / h)
                    seg = video_de.get(p)
                    # "Scale to Frame Size" (ScaleToFramePolicy=1): o Premiere reencaixa SOZINHO o arquivo novo (lab
                    # B24) — fator nenhum. Misturado no mesmo arquivo: o fator vale para todos os usos (a ponte escala
                    # por arquivo), então os com a política saem a conferir.
                    com, sem = ao_quadro.get(texto(p), (0, 0))
                    if com and sem:
                        marcar(p, "Escala a conferir", f"{os.path.basename(alvo)}: {com} uso(s) com Scale to Frame "
                                                       f"Size (o Premiere reencaixa) e {sem} sem (escala ajustada)")
                    if com and not sem:
                        pass
                    elif abs(w / h - m["w"] / m["h"]) < 0.005 or p in proporcao:
                        escalas[alvo] = e_f / e_o * fator
                    elif seg is not None and _proporcao_do_anexado(seg, alvo):
                        escalas[alvo] = [m["w"] / w * fator, m["h"] / h * fator]
                    else:
                        sem_escala.append(os.path.basename(alvo))
                        marcar(p, "Escala a conferir",
                               f"{os.path.basename(alvo)} tem outra proporção que o arquivo do projeto")
        for p, x in (analise.get("sons") or {}).items():
            if x.get("realocado") and os.path.isfile(x["realocado"]):
                troca[texto(p)] = decidido[texto(p)] = x["realocado"]
            else:
                marcar(p, "Arquivo não encontrado",
                       f"{os.path.basename(texto(p))}: entrou offline no lugar; religue no Premiere")
        for s in leitura["segmentos"]:            # o som no lugar: também é decisão (a conferência dos caminhos o vê)
            p = (s.get("media_ref") or {}).get("local_path")
            if s.get("is_audio") and p and p not in decidido and not recusado(p) and os.path.isfile(p):
                decidido[p] = p
        rid = str(uuid.uuid4())
        saida = _recebidos()
        saida.mkdir(exist_ok=True)
        # nome que NUNCA se repete: o Premiere lembra o caminho e a 2ª importação do mesmo arquivo pode não criar nada
        copia = saida / f"{rid}.prproj"
        conta = gravar_copia(caminho, str(copia), troca, raster)
        agora = datetime.now()
        nome_copia = str(sinais.get("nome_copia") or "").strip()[:120] or \
            f"{leitura['nome']} · relink {agora:%d-%m %Hh%M}"
        conf = None
        if sinais.get("referencia"):
            try:
                ctx = conferencia_da_analise(analise, sinais["referencia"])
                if ctx and ctx.get("pontos"):
                    from conferencia import conferencias
                    conf = conferencias().criar(ctx, nome_copia)
            except Exception as e:                       # noqa: BLE001 — acessório: a cópia vale sem a conferência
                log.warning("conferência do Premiere não preparada: %s", e)
        # o `importSequences` só aceita o ObjectUID: pedida pelo NOME (a linha de comando), a cópia não entrava (2026-10-29)
        plano = {"id": rid, "copia": str(copia), "seq": leitura.get("uid") or sequencia, "original": leitura["nome"],
                 "nome": nome_copia,
                 "bin": "De Lá Pra Cá", "tpf": tpf, "decidido": decidido, "escalas": escalas,
                 "marcas": [{**x, "t": x["quadro"] * tpf} for x in marcas],
                 # o 1º lugar de cada arquivo na timeline, pelo NOME (o marcador do "religado pelo Premiere")
                 "onde": {os.path.basename(alvo.replace("\\", "/")).lower(): {**onde[p][0], "t": onde[p][0]["quadro"] * tpf}
                          for p, alvo in [(p, decidido.get(texto(p)) or texto(p)) for p in onde] if onde[p]}}
        with self._lock:
            self._relinks = dict(list(self._relinks.items())[-9:])
            self._relinks[rid] = plano
        lembrar_pastas(caminho, list(pastas))
        de_outras = [x for x in ignorados_do_projeto(caminho) if x not in analise["casamento"]]
        lembrar_ignorados(caminho, de_outras + sorted(ignorar))
        res = analise["resumo"]
        self._etapa("montando", sequencia=sequencia, feitos=1, total=1)
        log.info("prproj %s › %s: cópia relinkada %s — %d caminhos trocados em %d Media, %d com escala",
                 os.path.basename(caminho), sequencia, copia.name, conta["caminhos"], conta["media"], len(escalas))
        return {"premiere_copia": {"id": rid, "nome": nome_copia}, "nome": leitura["nome"], "tipo": "prproj",
                "clipes": res["planos"], "nos_originais": res["no_original"], "trocados": conta["caminhos"],
                "escalas": len(escalas), "sem_escala": sem_escala, "marcadores": len(marcas),
                "faltam": sorted({os.path.basename(texto(p)) for p in analise["casamento"]
                                  if texto(p) not in decidido}),
                "referencia": os.path.basename(sinais["referencia"]) if sinais.get("referencia") else None,
                "conferencia": conf}

    def _analisar_xmeml(self, chave: str, caminho: str, sequencia: str, pastas: list[str]) -> dict:
        """O xmeml da Carta: os planos de vídeo → o MESMO casador do Premiere (proxy → original, só pelo arquivo) → a
        tela "antes de montar" (o resumo da análise do `.prproj`)."""
        from baselight import xmeml
        from prproj.originais import casar, indexar
        from tools.prproj_para_drt import resumir

        self._etapa("lendo", sequencia=sequencia, atual=caminho, detalhe=f"lendo a timeline “{sequencia}” da Carta")
        leitura = xmeml.ler(caminho)
        planos = [x for x in leitura["segmentos"] if not x.get("disabled")]
        casamento = casar(planos, pastas, lambda f, t, atual="": self._etapa(
            "casando", f, t, sequencia=sequencia, atual=atual,
            detalhe="procurando o original deste arquivo nas pastas escolhidas"), indice=indexar(pastas))
        resumo = resumir(leitura["segmentos"], casamento, None)
        with self._lock:
            self._analise = (chave, sequencia, tuple(pastas), {"leitura": leitura, "casamento": casamento,
                                                               "resumo": resumo, "xmeml": caminho})
        return {"sequencia": leitura["nome"], "pastas": list(pastas), **resumo, "ignorados": []}

    def _baselight_xmeml(self, chave: str, sequencia: str, sinais: dict | None) -> dict:
        """CARTA → BASELIGHT pelo De Lá Pra Cá: o xmeml da Carta reescrito com o ORIGINAL que a análise casou (o que não
        casou vai offline de propósito, com marker) → conform, conferência, troca e markers."""
        import cache
        from baselight import entrega as E
        from baselight import enviar

        with self._lock:
            a = self._analise
        if not a or a[0] != chave or a[1] != sequencia:
            raise LookupError("analise a timeline de novo antes de montar")
        _chave, _seq, pastas, analise = a
        fps = analise["leitura"]["fps"]
        decisao: dict = {}
        for p, c in analise["casamento"].items():
            o = c.get("original") if c.get("estado") in ("original", "proprio") else None
            decisao[p] = (E.descrever(o, enviar._sondar(E.como_o_disco_lista(o)), fps_sequencia=fps,
                                      trecho=c.get("trecho")) if o and os.path.isfile(o) else None)
        sinais = sinais or {}
        andar = self._andamento_baselight(sequencia)
        andar("montando", f"escrevendo a timeline para o Baselight (xmeml): {sequencia}")
        r = enviar.entregar_xmeml(analise["xmeml"], decisao, (sinais.get("job") or sequencia).strip(),
                                  sinais.get("scene") or sequencia, list(pastas),
                                  str(cache.sub(cache.RECEBIDOS)), markers=sinais.get("markers", True) is not False,
                                  andamento=lambda etapa, det: andar("baselight", det),
                                  atualizar=(sinais.get("atualizar") or None))
        lembrar_pastas(analise["xmeml"], list(pastas))
        return {"baselight": r, "nome": sequencia, "tipo": "xmeml", "clipes": r["planos"],
                "offline": r["offline_de_proposito"], "nao_traduzido": 0}

    def _baselight_prproj(self, chave: str, sequencia: str, sinais: dict | None) -> dict:
        """PREMIERE → BASELIGHT (proposta 2026-11-22-baselight-no-app, etapa 2): a análise (proxy → original) vira a
        entrega ao Baselight — conform numa scene nova do job da produção, conferência, troca e markers."""
        import baselight_conform

        with self._lock:
            a = self._analise
        if not a or a[0] != chave or a[1] != sequencia:
            raise LookupError("analise a sequência de novo antes de montar")
        _chave, _seq, pastas, analise = a
        r = baselight_conform.do_prproj(analise, sinais or {}, list(pastas), self._andamento_baselight(sequencia))
        lembrar_pastas(self._avulsos[chave][1], list(pastas))
        return {**r, "tipo": "prproj"}

    def _andamento_baselight(self, sequencia: str):
        return lambda etapa, detalhe: self._etapa(etapa if etapa in ETAPAS else "baselight", detalhe=detalhe,
                                                  sequencia=sequencia)

    def relink(self, rid: str) -> dict | None:
        with self._lock:
            return self._relinks.get(rid)

    def carta_premiere(self, cid: str) -> dict | None:
        with self._lock:
            return self._cartas_premiere.get(cid)

    def preparar_avulso(self, chave: str, mob_id: str = "", originais: dict | None = None,
                        raizes: list[str] | None = None, notas: bool = False,
                        sinais: dict | None = None) -> dict:
        """O arquivo aberto em `abrir` → o DRT, pelo MESMO caminho do Trazer da pasta."""
        if not RE_ID.match(chave or ""):
            raise ValueError("arquivo inválido")
        with self._lock:
            guardado = self._avulsos.get(chave)
            if guardado is None:
                raise LookupError("abra o arquivo de novo")
            if self._progresso.get("ativo"):
                raise RuntimeError("já estou trazendo outra timeline — espere ela terminar")
            self._cancelar.clear()
            self._progresso = {"ativo": True, "etapa": "lendo", "indice": 1,
                               "etapas": len(ETAPAS) + 1, "feitos": 0, "total": 0}
        try:
            self._etapa("lendo")
            tipo, caminho = guardado
            if tipo == "xmeml":
                if (sinais or {}).get("destino") != "baselight":
                    raise ValueError("a timeline da Carta vem para o Baselight: abra o De Lá Pra Cá com ele aberto")
                return self._baselight_xmeml(chave, mob_id, sinais)
            if tipo == "prproj":
                if (sinais or {}).get("destino") == "premiere":
                    return self._copia_para_premiere(chave, caminho, mob_id, sinais)
                if (sinais or {}).get("destino") == "baselight":
                    return self._baselight_prproj(chave, mob_id, sinais)
                return self._montar_prproj(chave, caminho, mob_id, sinais, notas=notas)
            carta = _carta_avulsa(tipo, caminho, mob_id)
            # Cada Trazer é um DRT novo: o id do envio (se houver) não nomeia arquivo aqui.
            import uuid
            return self._montar(carta, str(uuid.uuid4()), originais, raizes, notas=notas,
                                sinais=sinais)
        finally:
            self._progresso = {"ativo": False}
            self._cancelar.clear()

    # ── a Carta → o DRT (comum aos dois caminhos) ──────────────────────────────

    def _montar(self, carta, id_saida: str, originais: dict | None = None,
                raizes: list[str] | None = None, notas: bool = False,
                sinais: dict | None = None) -> dict:
        from avb_bin.segmentos import caminho_confiavel, montar_midia
        from carta_aberta.insert import filtrar_insert
        from drp.writer import build_drt
        from media import pmr

        def existe_aqui(c: str) -> str | None:
            seguro, _motivo = caminho_confiavel(c or "")
            if seguro and not os.path.isfile(seguro) and sys.platform == "darwin" and seguro.startswith("/") \
                    and not seguro.startswith("/Volumes/"):
                # ⚠️ o AAF do MC no Mac grava o caminho SEM o `/Volumes` (`/SSD/…`): sem isto o arquivo do
                # master nunca "existia aqui" (BL09 pelo MC, 2026-11-23; o mesmo de `media.matcher._daily_do_segmento`)
                seguro = "/Volumes" + seguro
            return seguro if seguro and os.path.isfile(seguro) else None

        # Mídia DESTA máquina: o índice do Avid daqui primeiro (a gerenciada daqui), depois o
        # que o remetente apontou — só se o caminho passar pela tranca e existir aqui.
        self._etapa("indexando", sequencia=carta.nome or "",
                    detalhe="procurando nesta máquina a mídia do Avid (índice das pastas Avid MediaFiles)")
        locais = pmr.indice_de(pmr.raizes_de_midia()).por_arquivo or {}
        gerenciados = dict(locais)
        for urn, mxf in carta.gerenciados.items():
            if urn not in gerenciados and (aqui := existe_aqui(mxf)):
                gerenciados[urn] = aqui
        arquivos = {k: aqui for k, c in carta.arquivos.items() if (aqui := existe_aqui(c))}
        # ⛔ Ataque V2: o `Source Path` da Carta vira a PASTA da referência offline — e essa
        # referência é escrita no DRT como `MediaFilePath`. Um `\\atacante\x` ali faz o
        # RESOLVE, ao importar, abrir sessão SMB com o host do atacante (e entregar o hash da
        # credencial do colorista). Só fica um caminho local seguro; senão a referência cai
        # na pasta local (é só referência: o colorista religa aos originais).
        colunas = {k: {**c, "Source Path": _pasta_de_referencia(c.get("Source Path"))}
                   for k, c in carta.colunas_por_mob.items() if isinstance(c, dict)}
        preferir = originais_validos(originais, raizes)

        saida = _recebidos()
        saida.mkdir(exist_ok=True)
        drt = saida / f"{id_saida}.drt"
        _abrir_espaco(drt)
        tipo = carta.tipo
        try:
            resultado = carta.resultado
            if tipo in ROTULO_INSERT:
                resultado = filtrar_insert(resultado, carta.selecao or [])
            nome = _nome_da_timeline(carta, tipo)
            # ⭐ O VÍDEO DE REFERÊNCIA, como no projeto do Premiere (organograma de 2026-10-19, "um fluxo para todo
            # protocolo"): a mesma trilha nova, desligada, acima de todas, e o som dele pela mesma escolha. Entra ANTES
            # do casamento, que não mexe no que não tem master: os índices dos segmentos ficam estáveis.
            ref = (sinais or {}).get("referencia")
            fps_tl = float(resultado.get("timeline_fps") or 25.0)
            if ref:
                import copy

                from tools.prproj_para_drt import _referencia
                som = None if (sinais or {}).get("som_referencia") == "nenhum" else \
                    ((sinais or {}).get("som_referencia") or "A")
                resultado = {**resultado, "segments": _referencia(copy.deepcopy(resultado.get("segments") or []),
                                                                  ref, som, fps_tl, round(fps_tl))}
            self._etapa("casando", sequencia=nome,
                        detalhe="casando cada clipe da timeline com um arquivo desta máquina")
            segs, casados, metas = montar_midia(resultado, arquivos, str(saida), colunas,
                                                gerenciados, preferir=preferir)
            if ref:
                casados += [{"segment_index": i, "matched_path": ref, "rejected": False,
                             "source_offset_correction": 0, "offline": False, "gerenciada": False}
                            for i, x in enumerate(segs) if x.get("referencia")]
            if not casados:
                raise ValueError("a timeline não tem nenhum clipe de mídia — nada a trazer")
            self._ler_midia(segs, casados, nome)
            if (sinais or {}).get("destino") == "baselight":
                # ⭐ AAF/bin/Carta → BASELIGHT (etapa 2): só o que caiu num original DECIDIDO pelo relink vai online
                import baselight_conform

                r = baselight_conform.da_carta(resultado, segs, casados, preferir, sinais or {}, list(raizes or []),
                                               nome, self._andamento_baselight(nome))
                return {**r, "tipo": tipo}
            if (sinais or {}).get("destino") == "premiere":
                # ⭐ O MODO PREMIERE (organograma aprovado em 2026-10-19): os mesmos segmentos e o mesmo casamento viram
                # o envio para a Carta (`premiere_montagem.envio_para_a_carta`), no lugar do DRT
                import premiere_montagem

                self._etapa("montando", sequencia=nome, detalhe="preparando a montagem no Premiere")
                # ⭐ a montagem vai pelo ESCRITOR DA CARTA (plano 2026-11-26, etapa 1; decisão do autor: "nada de
                #   marcador a menos que seja impossível"): o envio fica no serviço e o painel só diz qual (`carta_id`)
                envio = premiere_montagem.envio_para_a_carta(segs, casados, fps_tl, nome, id_saida,
                                                             inicio=resultado.get("timeline_start_frames"),
                                                             drop=bool(resultado.get("timeline_drop_frame")), metas=metas)
                with self._lock:
                    self._cartas_premiere = dict(list(self._cartas_premiere.items())[-9:])
                    self._cartas_premiere[id_saida] = envio
                clipes = [x for x in envio["segmentos"]
                          if not (x.get("is_gap") or x.get("is_transition") or x.get("is_effect"))]
                pl = {"carta_id": id_saida, "nome": nome, "planos_n": len(clipes),
                      "conta": {"offline_no_lugar": sum(1 for x in clipes if x.get("offline")),
                                "offline": sum(1 for x in clipes if not x.get("arquivo") and not x.get("offline"))}}
                nos_originais = sum(1 for c in casados if c.get("matched_path") in set(preferir.values()))
                self._etapa("montando", sequencia=nome, feitos=1, total=1)
                return {"premiere": pl, "nome": nome, "tipo": tipo, "clipes": len(casados),
                        "offline": pl["conta"]["offline"], "offline_no_lugar": pl["conta"]["offline_no_lugar"], "nos_originais": nos_originais,
                        "na_gerenciada": sum(1 for c in casados if c.get("gerenciada")),
                        "referencia": os.path.basename(ref) if ref else None,
                        "avisos": [a.get("texto") for a in (resultado.get("avisos") or [])][:20]}
            self._etapa("montando", sequencia=nome,
                        detalhe=f"escrevendo a timeline do Resolve (DRT): {len(segs)} segmentos, "
                                "efeitos, títulos e marcadores")
            # A trilha de notas (Sinais do Import) lê a leitura CRUA da Carta: os keyframes, o
            # estabilizador e o mapa da rampa estão nela (`motor/notas.py`).
            # E os Sinais do Import: marcador de timeline e cor LOCAL do segmento (`sinais` =
            # {"marcar": bool, "colorir": bool}); os três leem a mesma lista.
            sinais = sinais or {}
            lista, codigo = None, None
            if notas or sinais.get("marcar") or sinais.get("colorir"):
                import codigo_de_cores
                from notas import das_notas
                lista = das_notas(resultado)
                codigo = codigo_de_cores.ler()      # o código de cores da equipe (Ajustes)
            r = build_drt(segs, casados, str(drt), timeline_name=nome,
                          timeline_fps=float(resultado.get("timeline_fps") or 25.0), offline=metas,
                          timeline_start_frames=resultado.get("timeline_start_frames"),
                          # a TAXA da timeline vai no SequenceSetup só com um tamanho: sem ele a timeline nascia a 23,976 (medido no Resolve 21.1,
                          # 2026-10-28: Avid a 25 → timeline 23,976, TC 00:59:56:09). O raster da SEQUÊNCIA não vem do leitor: fica o do
                          # esqueleto (1920×1080), como sempre foi — ⏳ o raster do projeto do MC
                          timeline_size=(1920, 1080),
                          notas=lista if notas else None, sinais=lista,
                          marcar=bool(sinais.get("marcar")), colorir=bool(sinais.get("colorir")),
                          codigo_de_cores=codigo,
                          andamento=lambda f, t, a, det: self._etapa("montando", feitos=f, total=t,
                                                                  atual=a, detalhe=det, sequencia=nome))
        except ValueError:
            raise
        except (TypeError, KeyError, AttributeError, IndexError, OverflowError) as e:
            # Ataque V8: a forma de FORA foi conferida pelo reader, mas o miolo de um segmento
            # pode trazer tipo errado. Isso é "carta inválida", não um 500 com rastro interno.
            log.warning("carta %s com dados inválidos: %s: %s", id_saida, type(e).__name__, e)
            raise ValueError("a carta tem dados inválidos — peça para enviar de novo") from None
        midias = _gravar_midias(drt, casados)
        conferencia = None
        if ref:
            # o mesmo plano do projeto do Premiere; a timeline começa onde o WRITER a pôs: o TC da origem
            # (`timeline_start_frames`, desde f8f80c8) e, sem ele, 01:00:00:00 na base nominal. ⛔ Fixar 01:00:00:00
            # aqui (como era) deixou o AAF do Premiere que começa em 0 com a agulha uma hora fora: 0/6 "não exportou
            # o quadro" (B22, 2026-11-19). Acessório: sem plano, só não se oferece a conferência.
            from tools.prproj_para_drt import _conferencia
            nominal = round(fps_tl)
            inicio = _inicio_da_timeline(resultado, nominal)
            ctx = _conferencia(segs, nominal, fps_tl, {"inicio": inicio, "largura": 1920, "altura": 1080})
            conferencia = _conferencia_de({"conferencia": ctx}, nome) if ctx else None
        offline = sum(1 for c in casados if c.get("offline"))
        nos_originais = sum(1 for c in casados if c.get("matched_path") in set(preferir.values()))
        na_gerenciada = sum(1 for c in casados if c.get("gerenciada"))
        log.info("recebido %s (%s): %s — %d clipes, %d nos originais, %d na gerenciada, "
                 "%d offline", id_saida, tipo, drt, len(casados), nos_originais, na_gerenciada,
                 offline)
        self._etapa("montando", sequencia=nome, feitos=1, total=1)
        return {"drt": str(drt), "nome": nome, "tipo": tipo,
                "pasta_no_resolve": "Inserts" if tipo in ROTULO_INSERT else "De Lá Pra Cá",
                "clipes": len(casados), "offline": offline, "midias": midias,
                "nos_originais": nos_originais, "na_gerenciada": na_gerenciada,
                "clipes_video": r.get("clips_generated"), "clipes_audio": r.get("audio_clips"),
                "titulos": r.get("titulos") or 0,
                "notas": r.get("notas") or 0,
                "marcadores": r.get("marcadores") or 0,
                "segmentos_coloridos": r.get("segmentos_coloridos") or 0,
                # o Stabilize do Avid, para o estabilizador do Resolve DEPOIS do import (`/resolve/estabilizar`)
                "estabilizar": r.get("estabilizar") or [],
                # o Color Correction do Avid, nos 2 nós do Resolve DEPOIS do import (`/resolve/cor_mc`)
                "cor_mc": r.get("cor_mc") or [],
                "referencia": os.path.basename(ref) if ref else None,
                "trilha_referencia": next((x["track"] for x in segs if x.get("referencia") and not x.get("is_audio")),
                                          None),
                "conferencia": conferencia,
                # Os avisos dos títulos primeiro: são os que o editor precisa ler nesta tela.
                "avisos": ((r.get("avisos") or [])
                           + [a.get("texto") for a in (resultado.get("avisos") or [])])[:20]}


    def _ler_midia(self, segs: list, casados: list, nome: str) -> None:
        """Lê os metadados de cada arquivo ONLINE antes do writer, um por um, contando.

        É a etapa lenta do Trazer (um `ffprobe` por arquivo — ~1 min na PRODA_CORTE). Feita
        aqui, ela dá contagem real à barra e um ponto de Cancelar entre um arquivo e outro;
        o writer depois só consulta o cache (`_media_meta`/`_audio_meta` olham o cache ANTES
        do `ffprobe`). Offline não entra: o writer semeia esses com os metadados do Avid.
        """
        from drp.writer import _audio_meta, _media_meta

        video: set[str] = set()
        audio: set[str] = set()
        for c in casados:
            p = c.get("matched_path") if c else None
            if not p or c.get("offline") or c.get("rejected"):
                continue
            i = c.get("segment_index")
            s = segs[i] if isinstance(i, int) and 0 <= i < len(segs) else {}
            (audio if (s or {}).get("is_audio") else video).add(p)
        fila = [(p, _media_meta) for p in sorted(video)] + [(p, _audio_meta) for p in sorted(audio)]
        lidos = self._ler_em_paralelo(fila, nome)
        travar_se_o_motor_nao_le([(p, m) for p, ler, m in lidos if ler is _media_meta])

    def _ler_em_paralelo(self, fila: list, nome: str) -> list:
        """`[(arquivo, leitor)]` → `[(arquivo, leitor, metadados)]`, lidos EM PARALELO (2026-10-04:
        um ffprobe por arquivo, em série, era a espera; são processos esperando disco). A barra conta
        os que terminam; o Cancelar (`_etapa` lança) descarta os que faltam."""
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from drp.writer import SONDAGENS_SIMULTANEAS, _media_meta

        def detalhe(ler) -> str:
            return ("lendo o timecode, a taxa e o quadro do arquivo" if ler is _media_meta
                    else "lendo os canais e a duração do som")

        fora: list = []
        if fila:
            self._etapa("midia", feitos=0, total=len(fila), sequencia=nome, atual=fila[0][0],
                        detalhe=detalhe(fila[0][1]))
            ex = ThreadPoolExecutor(max_workers=min(SONDAGENS_SIMULTANEAS, len(fila)))
            try:
                futuros = {ex.submit(ler, p): (p, ler) for p, ler in fila}
                for fut in as_completed(futuros):
                    p, ler = futuros[fut]
                    fora.append((p, ler, fut.result()))
                    self._etapa("midia", feitos=len(fora), total=len(fila), sequencia=nome, atual=p,
                                detalhe=detalhe(ler))
            finally:
                ex.shutdown(wait=True, cancel_futures=True)
        self._etapa("midia", feitos=len(fila), total=len(fila), sequencia=nome)
        return fora


#: Ticks por segundo do Premiere (banco `prproj/estruturas.md`).
TICKS_POR_SEGUNDO = 254016000000


def _inicio_da_timeline(resultado: dict, nominal: int) -> int:
    """O quadro em que o `build_drt` começa a timeline — a MESMA regra de `drp.writer` (o TC da origem; ausente,
    01:00:00:00). A conferência que fixava 01:00:00:00 errou o lugar dos pontos de toda origem que começa noutro TC."""
    v = resultado.get("timeline_start_frames")
    return 3600 * nominal if v is None else max(0, int(v))


def _frames_do_tc(tc: str, nominal: int) -> int:
    h, m, s, f = (int(x) for x in str(tc).replace(";", ":").split(":"))
    return ((h * 60 + m) * 60 + s) * nominal + f


def _conferencia_de(relatorio: dict, timeline: str) -> dict | None:
    """O plano da conferência (`conferencia.py`) da timeline montada, ou `None` sem referência.
    Acessório: falhar aqui não derruba a timeline (memória "o trabalho caro não pode morrer no
    acessório") — só não oferece a conferência."""
    ctx = relatorio.get("conferencia")
    if not ctx or not ctx.get("pontos"):
        return None
    try:
        from conferencia import conferencias
        return conferencias().criar(ctx, timeline)
    except Exception as e:                       # noqa: BLE001
        log.warning("conferência não preparada: %s", e)
        return None


def travar_se_o_motor_nao_le(lidos: list[tuple[str, tuple]]) -> None:
    """Para ANTES do writer se o motor não está lendo as mídias de vídeo (`(caminho, (nb, fps, tc))`).

    ⛔ 2026-10-04 (autor, Mac): o serviço sem ffprobe montou o PRODUCAO_B inteiro — cada leitura falhou
    calada, todo clipe herdou o TC da forma do esqueleto e a timeline entrou toda offline no Resolve,
    depois de o editor fazer o processo inteiro. Arquivo quebrado é um ou outro; METADE sem TC nem
    duração com o motor NÃO pronto é o motor, e importar assim só entrega retrabalho (memória
    `sem-perda-nem-retrabalho`)."""
    if not lidos:
        return
    falhos = [c for c, (nb, fps, _tc) in lidos if not nb or not fps]
    if len(falhos) < 3 or len(falhos) * 2 < len(lidos):
        return
    # ⚠️ Só trava quando a PRONTIDÃO confirma que é o motor. BRAW, R3D e ARRIRAW o ffprobe não lê, e o
    # writer tem caminho próprio para eles: um projeto todo em BRAW tem TODA leitura "falha" com o motor
    # bom (o `test_relink_carta` pegou isso no primeiro desenho desta trava).
    import prontidao
    pr = prontidao.conferir(forcar=True)
    ruins = [i for i in pr["itens"] if not i["ok"]]
    if not ruins:
        log.info("%d de %d mídias sem TC/duração pelo ffprobe, com o motor pronto: formato que ele não "
                 "lê (BRAW/R3D/ARRIRAW?) — segue", len(falhos), len(lidos))
        return
    raise RuntimeError(f"O motor não conseguiu ler {len(falhos)} de {len(lidos)} mídias (TC e duração): "
                       f"{'; '.join(i['erro'] for i in ruins)}. Nada foi importado — a timeline sairia "
                       f"offline. {ruins[0].get('gesto') or ''}".rstrip())


#: Os arquivos de `recebidos/` são de PASSAGEM: o DRT que o Resolve importou vira timeline no
#: projeto (ele copia), o exportado para comparar só serve àquela comparação. Sem limpeza a pasta
#: crescia a cada Comparar (revisão 2026-09-28). Uma semana cobre um registro pendente
#: (`<uuid>.nova.json`) que espera o serviço voltar.
RECEBIDOS_DIAS = 7
_DE_PASSAGEM = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
                          r"\.(drt|midias\.json|nova\.json|relatorio\.json)$")


#: As pastas dos originais por projeto do Premiere (decisão do autor, 2026-10-03: "lembrar por
#: projeto"). O mesmo `.prproj` volta com as mesmas pastas; o editor tira ou põe outra.
PASTAS_POR_PROJETO = 50


def _arquivo_pastas() -> Path:
    return _dados() / "prproj_pastas.json"


def pastas_do_projeto(prproj: str) -> list[str]:
    try:
        d = json.loads(_arquivo_pastas().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lista = d.get(os.path.normcase(os.path.abspath(prproj))) if isinstance(d, dict) else None
    return [x for x in lista if isinstance(x, str)] if isinstance(lista, list) else []


def lembrar_pastas(prproj: str, pastas: list[str]) -> None:
    """Grava (acessório: falhar aqui não derruba a timeline, memória "o trabalho caro não pode
    morrer no acessório")."""
    try:
        try:
            d = json.loads(_arquivo_pastas().read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        chave = os.path.normcase(os.path.abspath(prproj))
        d.pop(chave, None)
        d[chave] = list(pastas)
        while len(d) > PASTAS_POR_PROJETO:
            d.pop(next(iter(d)))
        _arquivo_pastas().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("não gravei as pastas do projeto: %s", e)


#: Os arquivos IGNORADOS na "lista de mídias", por projeto do Premiere (autor, 2026-10-06: "lembrado
#: por projeto", como as pastas). Ignorar = "sem versão em alta, tudo bem" (a máscara de letterbox).
def _arquivo_ignorados() -> Path:
    return _dados() / "prproj_ignorados.json"


def ignorados_do_projeto(prproj: str) -> list[str]:
    try:
        d = json.loads(_arquivo_ignorados().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    lista = d.get(os.path.normcase(os.path.abspath(prproj))) if isinstance(d, dict) else None
    return [x for x in lista if isinstance(x, str)] if isinstance(lista, list) else []


def lembrar_ignorados(prproj: str, ignorados: list[str]) -> None:
    """Grava a lista INTEIRA deste projeto (desfazer um ignorar some daqui). Acessório: falhar não
    derruba a timeline."""
    try:
        try:
            d = json.loads(_arquivo_ignorados().read_text(encoding="utf-8"))
            d = d if isinstance(d, dict) else {}
        except (OSError, ValueError):
            d = {}
        chave = os.path.normcase(os.path.abspath(prproj))
        d.pop(chave, None)
        if ignorados:
            d[chave] = sorted(set(ignorados))
        while len(d) > PASTAS_POR_PROJETO:
            d.pop(next(iter(d)))
        _arquivo_ignorados().write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError as e:
        log.warning("não gravei os ignorados do projeto: %s", e)


def _duracao(segundos: float) -> str:
    s = int(round(segundos))
    return f"{s // 3600}:{s // 60 % 60:02d}:{s % 60:02d}"


def resumo_da_carta(carta) -> dict:
    """As contagens da tela "antes de montar" para a Carta, na forma do `resumir` do projeto do Premiere: planos, o
    que cada efeito vira, o áudio e a estimativa da conferência pela referência. ⚠️ Texto de terceiro (ataque V8):
    segmento de forma estranha é pulado, nunca levanta."""
    from tools.conferir_conform import SEGUNDOS_POR_PONTO, pontos_visiveis

    r = carta.resultado if isinstance(carta.resultado, dict) else {}
    segs = [x for x in (r.get("segments") or []) if isinstance(x, dict)]
    video = [x for x in segs if not (x.get("is_gap") or x.get("is_transition") or x.get("is_audio"))]
    planos = [x for x in video if not x.get("is_effect")]
    sem: dict[str, int] = {}
    titulos = 0
    for x in video:
        efs = [e for e in (x.get("effects") or []) if isinstance(e, dict)]
        titulos += x.get("is_effect") and any(e.get("category") == "title" for e in efs)
        for e in efs:
            if e.get("reproducible") is False:
                nome = str(e.get("name") or "?")[:80]
                sem[nome] = sem.get(nome, 0) + 1
    audio = [x for x in segs if x.get("is_audio") and not (x.get("is_gap") or x.get("is_transition"))]
    try:
        fps = float(r.get("timeline_fps") or 25.0)
        pontos = len(pontos_visiveis(segs, round(fps)))
    except (TypeError, ValueError, KeyError, AttributeError):
        pontos = 0
    return {"planos": len(planos), "no_original": 0,
            "efeitos": {"velocidade": sum(1 for x in planos if x.get("has_motion_effect")),
                        "reframe": sum(1 for x in planos if x.get("has_reframe")),
                        "titulos": titulos, "graficos": sum(1 for x in video if x.get("is_effect")) - titulos,
                        "transicoes": sum(1 for x in segs if x.get("is_transition") and not x.get("is_audio")),
                        "fusion": 0, "nests": 0},
            "sem_traducao": dict(sorted(sem.items(), key=lambda kv: -kv[1])),
            "audio": {"clipes": len(audio), "trilhas": len({x.get("track") for x in audio}),
                      "transicoes": sum(1 for x in segs if x.get("is_audio") and x.get("is_transition"))},
            "conferencia": {"pontos": pontos, "segundos": round(pontos * SEGUNDOS_POR_PONTO)}}


def _leitura_rapida(carta) -> dict:
    """O que o cartão do arquivo carregado mostra ANTES do Importar (redesenho do painel aprovado pelo
    autor, 2026-10-05: "carregar não é importar"): duração, taxa, trilhas e planos. Sai da Carta que o
    `abrir` já leu — nenhuma leitura a mais (AAF real de 78 segmentos: 0,25 s a Carta inteira).

    A duração é a da trilha mais longa (a soma dos segmentos, sem as transições, que se sobrepõem);
    planos = os segmentos de vídeo com mídia (sem vazio, transição ou efeito solto).

    ⚠️ A Carta é texto de terceiro (ataque V8): um campo de tipo errado PULA o segmento, nunca
    levanta. Esta leitura é acessória — ela não pode decidir se a Carta entra na caixa."""
    from aaf.parser import frames_to_tc

    r = carta.resultado if isinstance(carta.resultado, dict) else {}
    try:
        fps = float(r.get("timeline_fps") or 0) or 25.0
    except (TypeError, ValueError):
        fps = 25.0
    if not 1.0 <= fps <= 1000.0:   # NaN e infinito também caem aqui (o `round` estouraria)
        fps = 25.0
    por_trilha: dict[int, int] = {}
    planos = 0
    segmentos = r.get("segments")
    for s in segmentos if isinstance(segmentos, list) else []:
        try:
            if not isinstance(s, dict) or s.get("is_transition"):
                continue
            t = int(s.get("track") or 0)
            por_trilha[t] = por_trilha.get(t, 0) + max(0, int(s.get("duration_frames") or 0))
        except (TypeError, ValueError):
            continue
        if not s.get("is_audio") and not s.get("is_gap") and not s.get("is_effect"):
            planos += 1
    n = max(por_trilha.values(), default=0)
    return {"duracao": frames_to_tc(n, round(fps)) if n > 0 else "",
            "fps": round(fps, 3),
            "video": sum(1 for t in por_trilha if t < 1000),
            "audio": sum(1 for t in por_trilha if t >= 1000),
            "planos": planos}


def limpar_recebidos(dias: float = RECEBIDOS_DIAS, agora: float | None = None) -> int:
    """Apaga de `recebidos/` só o que o serviço escreveu (nome `<uuid>.drt|.midias.json|.nova.json`)
    e tem mais de `dias`. Devolve quantos apagou."""
    import time

    pasta = _recebidos()
    if not pasta.is_dir():
        return 0
    limite = (agora if agora is not None else time.time()) - dias * 86400
    n = 0
    for p in pasta.iterdir():
        try:
            if _DE_PASSAGEM.match(p.name) and p.is_file() and p.stat().st_mtime < limite:
                p.unlink()
                n += 1
        except OSError:
            continue
    return n


def _sequencias_da_bin(caminho: Path) -> list[dict]:
    """As sequências de uma `.avb`: `[{mob_id, nome, duracao}]`, pela ordem do nome.

    ⚠️ Tudo sai de dentro do `with`: o pyavb é preguiçoso (banco, `protocolos/avb/README.md`).
    """
    from aaf.parser import frames_to_tc
    from avb_bin.segmentos import sequencias
    from avb_export.reader import topen

    fora = []
    try:
        with topen(str(caminho)) as f:
            for m in sequencias(f):
                fps = float(getattr(m, "edit_rate", 0) or 0) or 25.0
                n = int(getattr(m, "length", 0) or 0)
                fora.append({"mob_id": str(m.mob_id), "nome": getattr(m, "name", "") or "",
                             "duracao": frames_to_tc(n, round(fps)) if n > 0 else ""})
    except Exception:  # noqa: BLE001 — uma bin estragada é recusa, não 500
        log.warning("bin ilegível: %s", caminho, exc_info=True)
        raise ValueError(f"não consegui ler a bin {caminho.name} — ela é do Media Composer?") from None
    return sorted(fora, key=lambda s: s["nome"].casefold())


def _carta_avulsa(tipo: str, caminho: str, mob_id: str = ""):
    """O arquivo aberto por "Escolher…" → a Carta, pelo leitor do formato."""
    if tipo == "avb":
        return _carta_da_bin(caminho, mob_id)
    if tipo == "aaf":
        return _carta_do_aaf(caminho)
    return _ler_carta_avulsa(caminho)


def _carta_do_aaf(caminho: str):
    """O AAF → a MESMA Carta que a bin daria (`aaf/leitura.py`, conferido contra a bin no caso U03:
    planos, masters, canais, identidade e essências iguais). O arquivo que o AAF aponta vai como
    `arquivo_ama`, e só vale se passar pela tranca e existir aqui, como o da bin."""
    from aaf.leitura import ler_timeline_aaf
    from carta_aberta.reader import ler_carta
    from carta_aberta.writer import montar

    try:
        leitura = ler_timeline_aaf(caminho)
    except Exception:  # noqa: BLE001 — um AAF estragado é recusa, não 500
        log.warning("AAF ilegível: %s", caminho, exc_info=True)
        raise ValueError(f"não consegui ler o AAF {Path(caminho).name} — ele é do Media Composer?") from None
    if not any(not s.get("is_gap") for s in leitura.get("segments") or []):
        raise ValueError(f"o AAF {Path(caminho).name} não tem nenhum clipe")
    arquivos = {k: m["caminho_na_bin"] for k, m in (leitura.get("masters") or {}).items()
                if m.get("caminho_na_bin")}
    doc = montar(leitura, [], leitura.get("composition_name") or "", arquivos=arquivos)
    doc["origem"]["leitura"] = "aaf (Abrir arquivo)"
    return ler_carta(doc)


def _carta_da_bin(caminho: str, mob_id: str):
    """A sequência `mob_id` da bin → a MESMA Carta que o Avid mandaria (em memória).

    ⭐ Passar pela Carta, e não direto ao DRT, é o que garante o mesmo resultado dos dois
    caminhos: `test_carta_ida_e_volta` prova DRT(bin) ≡ DRT(Carta), e o `ler_carta` confere a
    forma e apaga os caminhos plantados nos segmentos. O AMA que a bin aponta vai como
    `arquivo_ama` e, como o da Carta, só vale se passar por `caminho_confiavel` e existir aqui.
    Sem o Media Composer não há colunas (Source File/Path): o offline cai na pasta local.
    """
    from avb_bin.segmentos import ler_timeline_de_arquivo
    from carta_aberta.reader import ler_carta
    from carta_aberta.writer import montar

    try:
        leitura = ler_timeline_de_arquivo(caminho, mob_id=mob_id or None)
    except LookupError:
        raise LookupError("essa sequência não está mais na bin — abra o arquivo de novo") from None
    except Exception:  # noqa: BLE001
        log.warning("bin ilegível: %s", caminho, exc_info=True)
        raise ValueError(f"não consegui ler a bin {Path(caminho).name}") from None
    arquivos = {k: m["caminho_na_bin"] for k, m in (leitura.get("masters") or {}).items()
                if m.get("caminho_na_bin")}
    doc = montar(leitura, [], leitura.get("composition_name") or "", arquivos=arquivos)
    doc["origem"]["leitura"] = "avb (Abrir arquivo)"
    return ler_carta(doc)


def _ler_carta_avulsa(caminho: str):
    from carta_aberta.reader import CartaInvalida, ler_carta

    try:
        return ler_carta(caminho)
    except CartaInvalida as e:
        raise ValueError(f"{Path(caminho).name}: {e}") from None


def _gravar_midias(drt: Path, casados: list, som_depois: bool = False) -> int:
    """Grava `<uuid>.midias.json` ao lado do DRT: os arquivos DESTA máquina que a timeline usa.

    ⭐ Mídia primeiro, timeline depois (2026-09-26, decisão do autor; banco `drt-drp/estruturas.md`
    §"Mídia PRÉ-importada"): a casca do Resolve importa estes arquivos pelo import normal ANTES
    do DRT, e o Resolve liga a timeline aos itens que ele mesmo criou. O mapeamento de codec
    fica com ele. A casca só lê esta lista da pasta `recebidos` (a mesma tranca do DRT) e
    confere cada caminho de novo. Offline não entra: não existe aqui.

    ⛔ Exceção, `depois`: o WAV/AIF de 1 e 2 canais NÃO é pré-importado. O item que o import
    normal cria para ele não casa com os clipes mono do Avid, e o Resolve o duplicava no pool
    (medido 2026-09-26/27; banco `resolve-scripting/README.md` §"Áudio: o reaproveitamento…").
    O item do DRT fica sendo o único, e a casca o move para a mesma pasta depois de importar.
    `som_depois` (a rota do `.prproj`): TODO som puro vai depois — o de 3 e 4 canais também duplicou ali (R04 PRODUCAO-C, Resolve 19.1.4, 2026-10-19: os 3 WAV do som direto, um item pré-importado e um do DRT).
    """
    vistos: list[str] = []
    depois: list[str] = []
    for c in casados:
        p = (c or {}).get("matched_path")
        if not p or c.get("offline") or c.get("rejected"):
            continue
        p = os.path.abspath(p)
        if p in vistos or p in depois or not os.path.isfile(p):
            continue
        canais = _canais_de_audio(p)
        (depois if canais in (1, 2) or (som_depois and canais) else vistos).append(p)
    lista = drt.with_suffix(".midias.json")
    lista.write_text(json.dumps({"drt": drt.name, "midias": vistos, "depois": depois},
                                ensure_ascii=False), encoding="utf-8")
    return len(vistos)


def _canais_de_audio(caminho: str) -> int | None:
    """Canais de um WAV/BWF/RF64 ou AIF pelo cabeçalho; `None` para o resto (vídeo, MXF) ou
    quando não dá para ler. Percorre os blocos: o `bext` e o `iXML` do som direto vêm antes do
    `fmt ` e podem passar de alguns KB."""
    import struct

    ext = os.path.splitext(caminho)[1].lower()
    if ext not in (".wav", ".bwf", ".aif", ".aiff"):
        return None
    try:
        with open(caminho, "rb") as f:
            cab = f.read(12)
            riff = cab[:4] in (b"RIFF", b"RF64", b"BW64") and cab[8:12] == b"WAVE"
            if not riff and not (cab[:4] == b"FORM" and cab[8:12] in (b"AIFF", b"AIFC")):
                return None
            for _ in range(64):
                bloco = f.read(8)
                if len(bloco) < 8:
                    return None
                nome = bloco[:4]
                tam = struct.unpack("<I" if riff else ">I", bloco[4:])[0]
                if nome == (b"fmt " if riff else b"COMM"):
                    d = f.read(4)
                    return struct.unpack("<H", d[2:4])[0] if riff else struct.unpack(">h", d[:2])[0]
                f.seek(tam + (tam & 1), 1)
    except (OSError, struct.error):
        return None
    return None


def masters_da_carta(carta, raizes: list[str] | None = None) -> list:
    """Os masters da Carta como `aaf.masters.Master` — o LEITOR da rota `carta` do relink.

    O casamento com os originais (ADR 0020) é o MESMO do relink do Avid
    (`matcher_masters.casar_masters`); só o leitor muda. O nome procurado é o do ARQUIVO
    ORIGINAL (`Source File`, a coluna do Avid: o nome do arquivo de câmera), e cai no nome
    do master quando a Carta não o tem (bin lida sem o Media Composer). O AMA da Carta que
    existe NESTA máquina vira `caminho_conhecido` — o degrau "caminho" do matcher.

    Com `raizes` (as pastas dos originais), só o AMA que está DENTRO delas: tirar uma pasta da lista tem de tirar o que
    foi achado por ela (autor, 2026-10-19). A mesma regra do `prproj/originais.casar_um`: o arquivo do projeto conta
    como encontrado quando mora nas pastas indicadas; fora delas, o casamento procura pelo nome como os outros.
    """
    from collections import Counter

    from aaf.masters import Master
    from avb_bin.segmentos import caminho_confiavel

    resultado = carta.resultado or {}
    usos: Counter = Counter()
    audio: dict[str, bool] = {}
    for s in resultado.get("segments") or []:
        chave = s.get("mob_id")
        if not chave or s.get("is_gap") or s.get("is_transition"):
            continue
        usos[chave] += 1
        audio[chave] = audio.get(chave, True) and bool(s.get("is_audio"))

    bases = [os.path.normcase(os.path.abspath(r)).rstrip("\\/") + os.sep for r in (raizes or []) if r]
    fora = []
    for chave, m in (resultado.get("masters") or {}).items():
        if not isinstance(m, dict):
            continue
        colunas = carta.colunas_por_mob.get(chave) or m.get("colunas_mc") or {}
        arquivo_original = str(colunas.get("Source File") or "").strip()
        nome = (Path(arquivo_original.replace("\\", "/")).stem if arquivo_original
                else str(m.get("nome") or ""))
        fps = m.get("fps") or (m.get("identidade") or {}).get("fps")
        master = Master(nome=nome or chave, mob_id=chave, mob_id_urn=chave,
                        e_audio=audio.get(chave, False), segmentos=usos.get(chave, 0),
                        duracao_frames=m.get("duracao_frames"),
                        edit_rate=float(fps) if fps else None)
        ama = carta.arquivos.get(chave)
        # a coluna "De onde veio" da lista (um fluxo para todo protocolo, 2026-10-19): o caminho que a timeline grava,
        # como TEXTO — a tranca abaixo decide o que se toca no disco, não o que se mostra
        pasta_orig = str(colunas.get("Source Path") or "").strip()
        master.origem = (ama or str(m.get("caminho_na_bin") or "")
                         or (os.path.join(pasta_orig, arquivo_original) if pasta_orig and arquivo_original
                             else arquivo_original))[:1024]
        seguro, _motivo = caminho_confiavel(ama or "")
        dentro = not bases or any(os.path.normcase(os.path.abspath(seguro or "")).startswith(b) for b in bases)
        if seguro and dentro and os.path.isfile(seguro):
            master.caminho_conhecido = seguro
        fora.append(master)
    return fora


def originais_validos(originais: dict | None, raizes: list[str] | None) -> dict[str, str]:
    """Só os originais que existem E estão DENTRO das pastas que o colorista escolheu.

    ⚠️ Por que não `caminho_confiavel`: ela recusa caminho de rede (`\\\\servidor\\…`), e
    é comum a cor ter os originais num NAS. Aqui os caminhos vêm do ÍNDICE das pastas que o
    próprio colorista apontou — não da Carta. A trava certa é a origem: um arquivo fora
    dessas pastas (uma escolha forjada na revisão, por exemplo) não entra.
    """
    if not originais or not raizes:
        return {}
    bases = [os.path.normcase(os.path.abspath(r)).rstrip("\\/") + os.sep for r in raizes if r]
    fora: dict[str, str] = {}
    for chave, caminho in originais.items():
        if not isinstance(caminho, str) or not caminho or "://" in caminho:
            continue
        absoluto = os.path.normcase(os.path.abspath(caminho))
        if any(absoluto.startswith(b) for b in bases) and os.path.isfile(caminho):
            fora[chave] = caminho
    return fora


def _pasta_de_referencia(valor) -> str:
    """`Source Path` da Carta que pode virar pasta de referência no DRT — ou `""`."""
    from avb_bin.segmentos import caminho_confiavel

    texto = valor.strip() if isinstance(valor, str) else ""
    if not texto or "://" in texto:
        return ""
    seguro, _motivo = caminho_confiavel(texto)
    return texto if seguro else ""


def _resumir(carta, arquivo: str) -> dict:
    envio = carta.envio or {}
    doc = carta.doc
    return {"id": str(envio.get("id") or ""), "tipo": carta.tipo, "arquivo": arquivo,
            "nome": carta.nome, "sequencia": carta.resultado.get("composition_name") or "",
            "mob_id": str(carta.resultado.get("sequence_mob_id") or ""),
            "comentario": carta.comentario,
            "aplicativo": str((doc.get("origem") or {}).get("aplicativo") or ""),
            "remetente": envio.get("remetente") or {},
            "enviado_em": str(envio.get("enviado_em") or doc.get("gerado_em") or ""),
            "segmentos": (doc.get("resumo") or {}).get("segmentos"),
            "clipes_insert": len(carta.selecao or []),
            "avisos": len(doc.get("avisos") or []), **_leitura_rapida(carta)} if envio.get("id") else \
        {"arquivo": arquivo, "erro": "não é um envio do Magic Link (sem 'envio')"}


def _nome_da_timeline(carta, tipo: str) -> str:
    """O nome da timeline do outro lado é o que o EDITOR deu ao enviar (`carta.nome`).

    ⭐ Decisão do autor (2026-09-25): nome é convenção da equipe, não regra do programa. Quem
    envia compõe o nome no painel (campos `%sequencia`, `%tipo`, prefixos); quem recebe não
    inventa nada. Antes daqui saía "INSERT PARA VFX — seq — 24-09 23h19", com a hora do envio
    que ninguém reconhecia. Nome repetido o NLE resolve ("<nome> 2").
    """
    return carta.nome or carta.resultado.get("composition_name") or "timeline"
