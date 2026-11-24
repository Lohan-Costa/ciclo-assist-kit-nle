"""A sessão de trabalho: um relink por vez, observável de fora.

`relink.py` é síncrono e não sabe o que é HTTP. Este módulo o embrulha numa **thread**,
guarda o progresso num lugar que as rotas conseguem ler, e expõe o cancelamento.

## Por que uma sessão só

O painel é de um editor, e o Media Composer é um recurso único: duas preparações
concorrentes disputariam a mesma API de ~500 ms por chamada e o mesmo projeto aberto.
Uma tarefa por vez, e a segunda recebe 409 em vez de entrar numa fila que ninguém pediu.

## Por que o progresso é lido, e não empurrado

O SSE de `/progresso` lê este estado. Se o cliente cair no meio de uma aplicação de 80 s,
o trabalho continua e a próxima leitura reencontra o estado — não há evento perdido,
porque nada é entregue por evento.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from aaf.masters import chave_mob
from relink import Cancelado, Progresso, Trabalho, aplicar, preparar

log = logging.getLogger("delapraca.sessao")


@dataclass
class Estado:
    """O que a UI precisa saber. Um retrato, não um fluxo."""

    fase: str = "ocioso"          # ocioso | preparando | pronto | aplicando | feito | erro
    etapa: str = ""
    feito: int = 0
    total: int = 0
    detalhe: str = ""
    erro: str = ""
    resultado: dict = field(default_factory=dict)
    inicio: float = 0.0

    def to_dict(self) -> dict:
        d = {
            "fase": self.fase, "etapa": self.etapa, "feito": self.feito,
            "total": self.total, "detalhe": self.detalhe, "erro": self.erro,
            "resultado": self.resultado,
        }
        if self.inicio and self.fase in ("preparando", "aplicando"):
            d["decorrido"] = round(time.time() - self.inicio, 1)
        return d


class Sessao:
    """Um trabalho de relink, com o estado observável enquanto ele roda."""

    def __init__(self, servico):
        self.servico = servico
        self.trabalho = Trabalho()
        self.estado = Estado()
        self._thread: threading.Thread | None = None
        self._progresso = Progresso()
        self._lock = threading.Lock()

    # ── estado ──────────────────────────────────────────────────────────────

    @property
    def ocupada(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def instantaneo(self) -> dict:
        """Estado + resumo, num objeto só — é o que a UI desenha."""
        d = self.estado.to_dict()
        d["ocupada"] = self.ocupada
        d["trabalho"] = self.trabalho.resumo() if self.trabalho.casamentos else {}
        d["achatar_subclipes"] = self.trabalho.achatar_subclipes
        d["achatar_group_clips"] = self.trabalho.achatar_group_clips
        d["previa"] = self.trabalho.previa
        return d

    def masters(self, so_revisao: bool = False) -> list[dict]:
        """A lista para a tela de revisão, na ordem em que vale olhar: primeiro o que
        precisa de decisão, depois por número de segmentos afetados."""
        itens = []
        for c in self.trabalho.casamentos:
            d = c.to_dict()
            escolhido = self.trabalho.escolhas.get(c.master.mob_id)
            if escolhido:
                d["arquivo"] = escolhido
                d["metodo"] = "manual"
                d["confianca"] = 1.0
                d["precisa_de_revisao"] = False
            d["ignorado"] = c.master.mob_id in self.trabalho.ignorados
            d["ja_online"] = (None if d.get("arquivo")
                              else self.trabalho.ja_online.get(chave_mob(c.master.mob_id)))
            if so_revisao and not d["precisa_de_revisao"]:
                continue
            itens.append(d)
        itens.sort(key=lambda x: (not x["precisa_de_revisao"], -x["segmentos"]))
        return itens

    def cancelar(self) -> bool:
        if not self.ocupada:
            return False
        self._progresso.cancelar = True
        return True

    # ── as duas metades ─────────────────────────────────────────────────────

    def preparar(self, aaf: str, pastas: list[str], sequence: str = "",
                 rota: str = "aaf", bin_origem: str = "",
                 so_importados: bool = False, so_offline: bool = False,
                 pasta_projeto: str = "", sequence_mob_id: str = "", bin_externa: bool = False,
                 prproj: str = "", so_masters: list | None = None) -> None:
        """Dispara a preparação em thread. Levanta se já houver trabalho rodando.

        `rota` decide o caminho da APLICAÇÃO e o LEITOR da timeline: `"aaf"` (padrão,
        validada em escala) ou `"avb"`, que edita a bin do editor (ADR 0013). Na rota
        `avb`, `bin_origem` é a `.avb` que contém a timeline.
        """
        with self._lock:
            if self.ocupada:
                raise RuntimeError("já há um trabalho em andamento")
            self.trabalho = Trabalho(aaf=aaf, pastas=list(pastas), sequence=sequence,
                                     rota=rota, bin_origem=bin_origem, sequence_mob_id=sequence_mob_id,
                                     bin_externa=bin_externa,
                                     so_importados=so_importados, so_offline=so_offline,
                                     so_masters=list(so_masters or []),
                                     pasta_projeto=pasta_projeto, prproj=prproj)
            self._iniciar("preparando", self._preparar)

    def preparar_carta(self, carta, pastas: list[str], pedido: dict) -> None:
        """Casa os masters de uma Carta com os ORIGINAIS das `pastas` (ADR 0020).

        É o mesmo `preparar` do relink do Avid, com o leitor da Carta: o painel acompanha pelo
        mesmo `/progresso` e revisa pela mesma tela. Quem aplica não é o Media Composer — é o
        Importar do Resolve, com `trabalho.decididos()`.
        """
        with self._lock:
            if self.ocupada:
                raise RuntimeError("já há um trabalho em andamento")
            self.trabalho = Trabalho(rota="carta", carta=carta, pedido=dict(pedido),
                                     pastas=list(pastas), sequence=getattr(carta, "nome", "") or "")
            self._iniciar("preparando", self._preparar)

    def aplicar(self, pasta_projeto: str, nome_bin: str, pasta_trabalho: str) -> None:
        with self._lock:
            if self.ocupada:
                raise RuntimeError("já há um trabalho em andamento")
            if not self.trabalho.decididos():
                ign = len(self.trabalho.ignorados)
                raise ValueError(f"nada a relinkar: {ign} {'arquivo encontrado está' if ign == 1 else 'arquivos encontrados estão'}"
                                 " marcado(s) como “Ignorar” — selecione e clique em “Não ignorar”" if ign
                                 else "nada decidido — não há o que relinkar")
            self._iniciar("aplicando", self._aplicar,
                          pasta_projeto, nome_bin, pasta_trabalho)

    # ── plumbing ────────────────────────────────────────────────────────────

    def _iniciar(self, fase: str, alvo, *args) -> None:
        self.estado = Estado(fase=fase, inicio=time.time())
        self._progresso = Progresso(self._anotar)
        self._thread = threading.Thread(target=self._rodar, args=(alvo, args),
                                        name=f"delapraca-{fase}", daemon=True)
        self._thread.start()

    def _anotar(self, etapa: str, feito: int, total: int, detalhe: str) -> None:
        e = self.estado
        e.etapa, e.feito, e.total, e.detalhe = etapa, feito, total, str(detalhe)

    def _rodar(self, alvo, args) -> None:
        try:
            alvo(*args)
        except Cancelado as e:
            self.estado.fase = "ocioso"
            self.estado.etapa = "cancelado"
            log.info("%s", e)
        except Exception as e:  # noqa: BLE001
            self.estado.fase = "erro"
            self.estado.erro = f"{type(e).__name__}: {e}"
            log.exception("trabalho falhou")

    def _preparar(self) -> None:
        preparar(self.trabalho, self._progresso)
        self.estado.fase = "pronto"
        self.estado.etapa = ""

    def _aplicar(self, pasta_projeto: str, nome_bin: str, pasta_trabalho: str) -> None:
        # Um canal novo por operação: o editor abre e fecha o MC enquanto o painel segue
        # aberto, e um canal que sobreviveu ao processo do outro lado falha de um jeito
        # que não parece "o MC fechou".
        with self.servico.media_composer() as mc:
            if not mc.esta_vivo():
                raise RuntimeError(
                    "o Media Composer não respondeu. Ele está aberto? "
                    "Há alguma janela dele esperando resposta?")
            Path(pasta_trabalho).mkdir(parents=True, exist_ok=True)
            if self.trabalho.rota == "prproj":
                # Premiere → Avid (organograma do autor, 2026-10-25): o MC só RECEBE o .prproj; a lista de mídias
                # decidiu os arquivos (o que não está decidido entra OFFLINE no lugar)
                import prproj_avid

                t = self.trabalho
                resultado = prproj_avid.montar(
                    mc, t.prproj_analise, pasta_projeto, pasta_trabalho, nome_bin,
                    (t.prproj_analise or {}).get("leitura", {}).get("nome") or t.sequence,
                    self._progresso, decididos=t.decididos(), ids=t.prproj_ids, reescalar=t.prproj_reescalar)
                self.estado.resultado = resultado
                self.estado.fase = "feito"
                self.estado.etapa = ""
                return
            if self.trabalho.rota == "avb":
                # A rota do ADR 0013: edita a bin do editor. Sem ExportFile, sem preset,
                # sem ImportFile — e o áudio entra autorado, sem o modal que congela a API.
                import relink_avb

                resultado = relink_avb.aplicar(
                    mc, self.trabalho, self.trabalho.bin_origem, pasta_trabalho,
                    nome_bin, self._progresso,
                    pasta_saida=pasta_projeto if self.trabalho.bin_externa else None)
            else:
                # ⭐ Todo relink no MC injeta o áudio (autor, 2026-10-13): a AAF recebida entra numa bin e segue a
                # rota da bin. A rota antiga (`relink.aplicar`, LinkFile de tudo + ImportFile) não é mais chamada.
                import relink_avb

                resultado = relink_avb.aplicar_aaf(mc, self.trabalho, pasta_projeto, pasta_trabalho,
                                                   nome_bin, self._progresso)

        # ⭐ O relink DEU CERTO — é este o momento em que um casamento vira conhecimento.
        # Antes daqui ele é palpite; depois, é um par que passou pela tela e funcionou.
        # ⚠️ Fora do `with`: alimentar o banco não precisa do Media Composer, e não pode
        # segurar a conexão. E nunca levanta — ver `banco.alimentar`.
        import banco as banco_mod

        resultado["banco_aprendeu"] = banco_mod.alimentar(
            pasta_projeto, self.trabalho, resultado)
        self.estado.resultado = resultado
        self.estado.fase = "feito"
        self.estado.etapa = ""
