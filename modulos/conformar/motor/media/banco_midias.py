r"""O banco de mídias compartilhado — o mapa que faz o segundo relink ser rápido.

Numa novela o mesmo acervo é relinkado dezenas de vezes, por várias pessoas, durante
meses. Hoje cada relink recomeça do zero: varre as pastas, lê o metadado de **cada**
arquivo e casa tudo de novo — mesmo quando a mídia e os casamentos são os mesmos da
véspera.

⭐ **O que custa é o metadado, e é isso que este módulo elimina.** Medido: **~61 ms por
arquivo** (394 `.mxf` em 24,1 s, exFAT/USB, 2026-08-15) contra **0,04 s** do casamento
inteiro. O `indexer` já evita reler metadado dentro do mesmo processo (`_META_CACHE`);
este módulo é esse cache **persistido e compartilhado pela rede**.

⭐⭐ **E ele é um GUIA, nunca a regra.** O que ele entrega é um candidato já visto por um
humano, que passa por **revalidação 1:1** antes de valer. Se o arquivo sumiu ou mudou, o
app cai na varredura completa de sempre — não existe caminho em que o banco IMPEÇA a
descoberta de uma mídia.

## ⚠️⚠️ A chave é o NOME, e não o `mob_id`

Era a chave óbvia e falharia **em silêncio**. Em mídia **AMA** o Avid casa por arquivo e
o `mob_id` é **gerado fresco a cada link**: medido, **83 de 118 masters ganharam `mob_id`
novo** depois de um relink (banco de NLEs, `protocolos/avb/escrita.md`, `confirmado`).
Como quase toda a mídia de câmera do fluxo é AMA, um banco chaveado por `mob_id` nunca
teria um acerto na segunda vez — e não daria erro nenhum, só nunca serviria para nada.

A chave é o **nome normalizado do master** (`matcher._normalize_name`), que atravessa
projetos e episódios e é o critério que resolve o acervo na prática: *dos 101 casamentos
por nome, 100 foram exatos*. `mob_id` e UMID entram como pistas **secundárias**, úteis em
mídia gerenciada, nunca como a única.

## Em disco

    <pasta do banco>/
      banco.json                    metadados: esquema, produção, raízes declaradas
      fragmentos/<host>-<user>.jsonl   cada máquina escreve SÓ o seu (append-only)
      mapa.json                     consolidado, legível, regravado a partir dos fragmentos

⭐ **Ninguém escreve no arquivo de outra máquina.** É isso que dispensa trava e torna a
escrita simultânea segura em SMB, onde `lock` não é confiável. A regra vem do `_PRODUCAO-V`
(`decupador/sidecar.py`), escrito para exatamente este cenário: *um escritor por
diretório · escrita atômica · leitura defensiva*.

⚠️ **Leitura defensiva não é zelo:** a última linha de um fragmento pode estar sendo
escrita neste instante, e um fragmento vindo da rede é **entrada não confiável**. Linha
que não parseia é pulada, nunca derruba a leitura.

⚠️ `mtime` é gravado em **segundos inteiros**. exFAT e SMB divergem no sub-segundo, e
comparar nanossegundo entre máquinas invalidaria o cache inteiro a cada leitura. É a
mesma escolha do `probecache.py` do Órbita.

## O que este módulo NÃO faz

Não conhece plataforma. O mapeamento `raiz → caminho local` chega pronto de quem chama
(o serviço, via `plataforma.volumes_montados()`), porque `motor/` é embarcado e não pode
depender da camada de plataforma do plugin (ADR 0011).
"""

from __future__ import annotations

import json
import logging
import os
import socket
import time
from pathlib import Path, PureWindowsPath

from .matcher import _duration_ok, _normalize_name
from .safepath import CaminhoInvalido, ensure_local_file, forma_windows

#: Tolerância do portão de duração — **as mesmas do matcher**, de propósito. Duas réguas
#: para a mesma pergunta é como o banco passaria a discordar da varredura em silêncio.
OPCOES_DURACAO = {"duration_tol_secs": 0.3, "duration_tol_rel": 0.01}

log = logging.getLogger("delapraca.media.banco")

#: ⚠️ Versão do FORMATO **e** dos extratores. Bumpar invalida o metadado guardado.
#: A armadilha que o `probecache.py` documenta: consertar um *extrator* sem bumpar deixa
#: o valor errado sobreviver ao conserto, e o defeito volta calado na leitura do cache.
ESQUEMA = "1"

_BANCO = "banco.json"
_MAPA = "mapa.json"
_FRAGMENTOS = "fragmentos"

#: Teto por linha lida. Um fragmento corrompido não pode virar consumo de memória.
_MAX_LINHA = 64 * 1024


# ── identidade e caminhos ───────────────────────────────────────────────────

def _chave_local(caminho) -> str:
    """A forma de comparar dois caminhos NA MESMA máquina.

    ⚠️ `casefold` no Windows porque o Win32 é insensível à caixa **mesmo em exFAT**
    (medido — é a mesma razão pela qual `.venv` e `.venv-win` são separados). Sem isso
    `E:\\MIDIAS\\a.braw` e `e:\\midias\\A.BRAW` viram duas entradas para um arquivo só.
    """
    s = str(caminho).replace("/", os.sep)
    return s.casefold() if os.name == "nt" else s


def _partes(caminho) -> tuple[str, ...]:
    """Partes do caminho, pela FORMA dele e não pelo SO que roda (matriz, regra 3).

    No macOS, `Path("E:\\MIDIAS\\a.braw").parts` é UMA parte só, e nenhuma raiz do
    Windows casava (medido 2026-10-01, `tests/test_banco_midias.py`).
    """
    s = str(caminho)
    if forma_windows(s):
        return PureWindowsPath(s).parts
    return Path(s.replace("/", os.sep)).parts


def partir(caminho: str, raizes: dict[str, str]) -> tuple[str, str]:
    """`E:\\MIDIAS\\dia 1\\a.braw` → `("V-001", "MIDIAS/dia 1/a.braw")`.

    `raizes` é `{nome: caminho local}`. Vence a raiz de MAIS PARTES — com `E:\\` e
    `E:\\MIDIAS` declaradas, um arquivo dentro de MIDIAS pertence à segunda.

    Devolve `("", "")` quando nenhuma raiz cobre o caminho: aí só o absoluto identifica,
    o que ainda funciona enquanto as letras forem padronizadas na casa.

    ⚠️⚠️ **Compara por PARTES do caminho, nunca por fatia de string.** A primeira versão
    casava com `startswith` e cortava o original pelo `len()` da base em minúsculas — e
    **`casefold()` pode MUDAR O COMPRIMENTO**: `E:\\STRAßE` tem 9 caracteres e 10
    depois de dobrado (`ss`); `İ` idem. Uma pasta com `ß`, `İ` ou ligadura produzia um
    relativo cortado no lugar errado, **em silêncio** — o caminho resultante não existe e
    o banco vira uma entrada inútil que ninguém consegue explicar.

    Comparar componente a componente é imune a isso: quantas partes casaram é um número
    que não depende de quantos caracteres a normalização produziu.
    """
    partes = _partes(caminho)
    chave = tuple(_chave_local(p) for p in partes)
    melhor_nome, melhor_n = "", -1
    for nome, base in (raizes or {}).items():
        if not base:
            continue
        b_partes = _partes(base)
        # Uma raiz é um prefixo de partes do caminho — `("E:\\",)` cobre
        # `("E:\\", "MIDIAS", "a.braw")`.
        if not b_partes or len(b_partes) > len(partes):
            continue
        if chave[:len(b_partes)] == tuple(_chave_local(p) for p in b_partes):
            if len(b_partes) > melhor_n:
                melhor_nome, melhor_n = nome, len(b_partes)
    if melhor_n < 0:
        return "", ""
    # Barra normal na gravação: o arquivo atravessa Windows e macOS.
    return melhor_nome, "/".join(partes[melhor_n:])


def juntar(raiz: str, rel: str, raizes: dict[str, str]) -> str | None:
    """O inverso de `partir`, com o mapeamento DESTA máquina. `None` se não dá."""
    base = (raizes or {}).get(raiz or "")
    if not base or not rel:
        return None
    return str(Path(base) / rel.replace("/", os.sep))


def assinatura(caminho) -> tuple[int, int] | None:
    """`(tamanho, mtime em segundos)` — o que decide se o arquivo ainda é o mesmo.

    `None` quando o arquivo não existe (ou o volume não está montado, que aqui dá no
    mesmo: não dá para revalidar, então não se confia).
    """
    try:
        st = os.stat(caminho)
    except OSError:
        return None
    return int(st.st_size), int(st.st_mtime)


# ── o banco ─────────────────────────────────────────────────────────────────

class Banco:
    """Um banco aberto. Leitura em memória; escrita só no fragmento desta máquina."""

    def __init__(self, pasta: Path, raizes: dict[str, str] | None = None,
                 autor: str = "", producao: str = ""):
        self.pasta = Path(pasta)
        self.raizes = dict(raizes or {})
        self.autor = autor or _autor_padrao()
        self.producao = producao
        self.midias: dict[str, dict] = {}
        # ⚠️⚠️ **LISTA por nome, não uma entrada só.** Nome de mídia colide: cartão
        # reaproveitado entre diárias, `Take 1.wav`, um clipe reexportado noutra pasta.
        # Guardar "a" entrada por nome faria a última gravada apagar a outra, e o master
        # legítimo do outro episódio herdaria o arquivo errado — calado, que é o pior
        # jeito de errar. Guardando todas, a duração desempata (ver `decidir`).
        self.casamentos: dict[str, list[dict]] = {}
        self._novas: list[dict] = []             # a gravar no fragmento
        self._fragmentos_lidos = 0

    # ── abrir ───────────────────────────────────────────────────────────────

    @classmethod
    def abrir(cls, pasta, raizes: dict[str, str] | None = None,
              autor: str = "") -> "Banco":
        """Lê `mapa.json` e todos os fragmentos. Nunca levanta por conteúdo ruim."""
        p = Path(pasta)
        meta = _ler_json(p / _BANCO) or {}
        # ⚠️ `producao` mora DENTRO de `_meta` (é o cabeçalho do formato); `raizes` é de
        # topo. Ler do lugar errado devolvia sempre `""` — e o defeito era invisível
        # porque a tela cai no nome da PASTA como reserva. O nome digitado pelo editor se
        # perdia na primeira regravação: `abrir` lia vazio e `consolidar` gravava vazio.
        banco = cls(p, raizes=raizes, autor=autor,
                    producao=str((meta.get("_meta") or {}).get("producao") or ""))
        # As raízes declaradas no banco entram como DICA, sem sobrepor o mapeamento
        # local: quem sabe onde o volume está montado é esta máquina, não o arquivo.
        for nome, dados in (meta.get("raizes") or {}).items():
            banco.raizes.setdefault(nome, str((dados or {}).get("dica") or ""))

        for linha in _ler_jsonl_do_mapa(p / _MAPA):
            banco._absorver(linha)
        frag = p / _FRAGMENTOS
        if frag.is_dir():
            for arquivo in sorted(frag.glob("*.jsonl")):
                banco._fragmentos_lidos += 1
                for linha in _ler_jsonl(arquivo):
                    banco._absorver(linha)
        log.info("banco: %d mídias, %d casamentos, %d fragmento(s) em %s",
                 len(banco.midias), len(banco.casamentos), banco._fragmentos_lidos, p)
        return banco

    def _absorver(self, linha: dict) -> None:
        """Aplica uma linha ao estado. **O carimbo mais novo vence.**"""
        if not isinstance(linha, dict) or linha.get("esquema") != ESQUEMA:
            return
        tipo = linha.get("tipo")
        if tipo == "midia":
            chave = linha.get("chave")
            if chave and _mais_nova(linha, self.midias.get(chave)):
                self.midias[chave] = linha
        elif tipo == "casamento":
            nome = linha.get("nome_norm")
            if not nome:
                return
            lista = self.casamentos.setdefault(nome, [])
            alvo = _alvo(linha)
            for i, velha in enumerate(lista):
                if _alvo(velha) != alvo:
                    continue
                # Mesmo nome E mesmo arquivo: é a MESMA aposta, atualizada.
                if _mais_nova(linha, velha):
                    linha = dict(linha)
                    # ⭐ `vezes` ACUMULA: é a confiança do par, e não deveria zerar só
                    # porque outra máquina reconfirmou depois da nossa.
                    linha["vezes"] = max(int(velha.get("vezes") or 1),
                                         int(linha.get("vezes") or 1))
                    lista[i] = linha
                return
            # Mesmo nome, arquivo DIFERENTE: convive. Quem desempata é a duração.
            lista.append(linha)

    # ── consultar ───────────────────────────────────────────────────────────

    def candidatos_de(self, nome: str) -> list[dict]:
        """Tudo que já foi confirmado para este nome de master. Pode ser mais de um."""
        return list(self.casamentos.get(_normalize_name(nome or "")) or [])

    def decidir(self, master, opcoes: dict | None = None) -> tuple[str, list[dict]]:
        """O que o banco tem a dizer sobre ESTE master. É aqui que ele vira útil.

        Devolve `("acerto", [linha])`, `("ambiguo", linhas)` ou `("nada", [])`.

        ⭐⭐ **Só `acerto` autoriza pular a varredura.** `ambiguo` significa que o banco
        conhece mais de um arquivo com esse nome e não sabe qual é deste master — nesse
        caso ele se cala e deixa o fluxo normal decidir, que é o comportamento correto
        de um guia.

        A cascata, na mesma ordem de severidade do `casar_masters`:

        1. **Espécie** — master de áudio nunca casa com entrada gravada para vídeo.
           Grátis, e corta o erro mais grosseiro.
        2. ⭐ **Duração** — o portão do próprio matcher (`_duration_ok`, mesma
           tolerância: 0,3 s ou 1 %). É o que separa dois clipes de mesmo nome vindos de
           **cartões reaproveitados em diárias diferentes**, que é o caso real que o nome
           sozinho não distingue.
           ⚠️ **Tri-estado, e a preferência importa:** se ALGUM candidato bate na duração
           (`True`), os neutros (`None`) são descartados — havendo prova, palpite não
           compete. Se nenhum tem duração para comparar, todos seguem neutros.
        3. **Revalidação 1:1** do arquivo (existe? tamanho e mtime batem?).

        ⚠️ **Limite honesto:** na rota AAF o `Master.duracao_frames` não é preenchido
        (`aaf/masters.py` não passa o campo), então o portão fica **neutro** e a defesa
        real ali são a espécie e a revalidação. Na rota `.avb` — a preferida hoje — a
        duração existe e o portão morde. Encher `duracao_frames` na rota AAF fecharia
        essa lacuna também no matcher, não só aqui.
        """
        linhas = self.candidatos_de(getattr(master, "nome", "") or "")
        if not linhas:
            return "nada", []

        e_audio = getattr(master, "e_audio", None)
        if e_audio is not None:
            linhas = [x for x in linhas
                      if x.get("e_audio") is None or bool(x.get("e_audio")) == bool(e_audio)]

        aprovados, neutros = [], []
        for linha in linhas:
            veredito = self.confere_duracao(master, linha, opcoes)
            if veredito is True:
                aprovados.append(linha)
            elif veredito is None:
                neutros.append(linha)
            # `False` cai fora: a duração é prova contra, não dúvida.
        candidatos = aprovados or neutros
        if not candidatos:
            return "nada", []

        vivos = [x for x in candidatos if self.revalidar(x)[0] == "ok"]
        if len(vivos) == 1:
            return "acerto", vivos
        if len(vivos) > 1:
            log.info("banco: %d candidatos para %r — deixando para a varredura",
                     len(vivos), getattr(master, "nome", ""))
            return "ambiguo", vivos
        return "nada", []

    def confere_duracao(self, master, linha: dict, opcoes: dict | None = None):
        """`True` / `False` / `None` — o portão do matcher, aplicado ao que foi guardado.

        Compara a duração do master de AGORA com a que estava valendo quando um humano
        confirmou aquele par. Não é a duração do arquivo: a pergunta aqui é *"esta
        entrada é sobre este master?"*, e não *"este arquivo ainda é o mesmo?"* — essa
        segunda é a revalidação por tamanho e mtime.
        """
        agora = _duracao_do_master(master)
        antes = linha.get("dur_s")
        if not agora or not antes:
            return None
        return _duration_ok({"media_ref": {"source_duration_secs": agora}},
                            {"duration_ms": float(antes) * 1000.0},
                            opcoes or OPCOES_DURACAO)

    def caminho_de(self, linha: dict) -> str | None:
        """O caminho DESTA máquina para uma linha do banco.

        Tenta a raiz mapeada primeiro (é o que atravessa máquinas) e cai para o
        absoluto observado — que acerta quando as letras são padronizadas.
        """
        if not linha:
            return None
        return juntar(linha.get("raiz", ""), linha.get("rel", ""), self.raizes) \
            or (linha.get("abs") or None)

    def revalidar(self, linha: dict) -> tuple[str, str | None]:
        """A revalidação 1:1 — o que separa "guia" de "regra".

        Devolve `("ok"|"mudou"|"sumiu", caminho)`:

        - **ok** — existe e a assinatura bate: pode virar `caminho_conhecido`.
        - **mudou** — existe e a assinatura NÃO bate: o arquivo é outro (ou foi
          reexportado). Vira candidato, nunca decisão — o metadado é relido.
        - **sumiu** — não existe, não é arquivo, ou o caminho é inaceitável.

        ⚠️ Caminho vindo do banco é **entrada de rede**, não dado nosso: passa pelo
        mesmo portão de sempre (`safepath.ensure_local_file`), que recusa URL disfarçada
        de caminho antes que ela chegue ao ffmpeg ou ao MediaInfo.
        """
        caminho = self.caminho_de(linha)
        if not caminho:
            return "sumiu", None
        try:
            p = ensure_local_file(caminho)
        except CaminhoInvalido as e:
            log.warning("caminho recusado (%s): %r", e, caminho)
            return "sumiu", None
        atual = assinatura(p)
        if atual is None:
            return "sumiu", None
        if atual == (int(linha.get("size") or -1), int(linha.get("mtime") or -1)):
            return "ok", str(p)
        return "mudou", str(p)

    def midia_de(self, chave: str) -> dict | None:
        return self.midias.get(chave)

    # ── anotar (vai para o fragmento desta máquina) ─────────────────────────

    def anotar_midia(self, caminho: str, meta: dict) -> dict | None:
        """Guarda o metadado de um arquivo — o dict que o `indexer` já produz."""
        sig = assinatura(caminho)
        if sig is None:
            return None
        raiz, rel = partir(caminho, self.raizes)
        linha = {
            "esquema": ESQUEMA, "tipo": "midia",
            "chave": _chave_de_midia(raiz, rel, caminho),
            "raiz": raiz, "rel": rel, "abs": str(caminho),
            "size": sig[0], "mtime": sig[1],
            "meta": dict(meta or {}),
            "carimbo": _agora(), "por": self.autor,
        }
        self._novas.append(linha)
        self._absorver(linha)
        return linha

    def anotar_casamento(self, nome: str, caminho: str, *, metodo: str = "",
                         mob_id: str = "", umid: str = "",
                         dur_s: float | None = None,
                         e_audio: bool | None = None) -> dict | None:
        """Guarda um par master↔arquivo **já confirmado na tela e aplicado**.

        ⭐ Palpite não entra. Só chega aqui o que passou pela revisão e sobreviveu a um
        relink que o Media Composer aceitou — é o que faz o banco acelerar sem propagar
        erro de casamento para as próximas vezes.

        ⭐ `dur_s` e `e_audio` são do MASTER, não do arquivo, e é por isso que existem:
        são o que permite, na próxima vez, responder *"esta entrada é sobre este
        master?"* quando dois masters diferentes têm o mesmo nome. Ver `decidir`.
        """
        nome_norm = _normalize_name(nome or "")
        if not nome_norm or not caminho:
            return None
        raiz, rel = partir(caminho, self.raizes)
        sig = assinatura(caminho) or (0, 0)
        alvo = _alvo({"raiz": raiz, "rel": rel, "abs": str(caminho)})
        # Reconfirmar o MESMO arquivo soma confiança; um alvo novo entra do zero.
        vezes = 1
        for velha in self.casamentos.get(nome_norm) or []:
            if _alvo(velha) == alvo:
                vezes = int(velha.get("vezes") or 1) + 1
                break
        linha = {
            "esquema": ESQUEMA, "tipo": "casamento",
            "nome_norm": nome_norm, "nome": nome,
            "raiz": raiz, "rel": rel, "abs": str(caminho),
            "size": sig[0], "mtime": sig[1],
            "mob_id": mob_id or "", "umid": umid or "",
            "dur_s": round(float(dur_s), 3) if dur_s else None,
            "e_audio": bool(e_audio) if e_audio is not None else None,
            "metodo": metodo or "", "vezes": vezes,
            "carimbo": _agora(), "por": self.autor,
        }
        self._novas.append(linha)
        self._absorver(linha)
        return linha

    def anotar_casamento_de_master(self, master, caminho: str, *,
                                   metodo: str = "") -> dict | None:
        """`anotar_casamento` a partir de um `Master` — que é como o relink chama."""
        return self.anotar_casamento(
            getattr(master, "nome", "") or "", caminho, metodo=metodo,
            mob_id=getattr(master, "mob_id", "") or "",
            dur_s=_duracao_do_master(master),
            e_audio=getattr(master, "e_audio", None))

    # ── gravar ──────────────────────────────────────────────────────────────

    def gravar(self) -> int:
        """Anexa o que foi anotado ao fragmento DESTA máquina. Devolve quantas linhas.

        ⚠️ Falhar aqui **não** pode derrubar um relink que deu certo: o banco é
        aceleração, nunca requisito. Erro vira aviso no log — a mesma regra do
        `probecache` do Órbita.

        ⚠️⚠️ E o `except` pega **`ValueError` junto de `OSError`**, o que não é excesso:
        um caminho com byte nulo levanta `ValueError` no `mkdir`, **não** `OSError`, e
        com um `except OSError` sozinho a promessa acima era falsa. Pego pelo teste.
        """
        if not self._novas:
            return 0
        try:
            frag = self.pasta / _FRAGMENTOS
            frag.mkdir(parents=True, exist_ok=True)
            alvo = frag / f"{_nome_de_arquivo(self.autor)}.jsonl"
            with open(alvo, "a", encoding="utf-8", newline="\n") as fh:
                for linha in self._novas:
                    fh.write(json.dumps(linha, ensure_ascii=False) + "\n")
        except (OSError, ValueError) as e:
            log.warning("não consegui gravar no banco de mídias (%s) — seguindo", e)
            return 0
        n, self._novas = len(self._novas), []
        return n

    def consolidar(self) -> bool:
        """Regrava `mapa.json` com o estado inteiro. Oportunista e opcional.

        ⚠️ **Nunca apaga fragmento.** Se a troca falhar, ou se outra máquina gravar no
        meio, nada se perde — o pior caso é o consolidado ficar velho, e ele é só um
        atalho de leitura. Apagar fragmento seria trocar velocidade por risco de perda.

        ⚠️ Temporário na MESMA pasta, e nome por PID: `os.replace` só é atômico dentro
        do mesmo volume (lição paga nesta base), e dois processos consolidando ao mesmo
        tempo não podem disputar o mesmo temporário.
        """
        try:
            self.pasta.mkdir(parents=True, exist_ok=True)
            alvo = self.pasta / _MAPA
            tmp = self.pasta / f"{_MAPA}.{os.getpid()}.tmp"
            with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
                for linha in list(self.midias.values()) + list(self.casamentos.values()):
                    fh.write(json.dumps(linha, ensure_ascii=False) + "\n")
            os.replace(tmp, alvo)
            self._escrever_meta()
            return True
        except (OSError, ValueError) as e:   # ValueError: byte nulo — ver `gravar`
            log.warning("não consegui consolidar o banco (%s) — os fragmentos ficam", e)
            return False

    def _escrever_meta(self) -> None:
        meta = {
            "_meta": {
                "formato": "delapraca-banco-de-midias",
                "esquema": ESQUEMA,
                "producao": self.producao,
                "atualizado": _agora(),
                "nota": "Mapa de mídias compartilhado. Os fragmentos são a verdade; "
                        "mapa.json é o consolidado de leitura.",
            },
            "raizes": {nome: {"dica": base} for nome, base in self.raizes.items() if base},
        }
        tmp = self.pasta / f"{_BANCO}.{os.getpid()}.tmp"
        tmp.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.pasta / _BANCO)

    # ── estado ──────────────────────────────────────────────────────────────

    def estatisticas(self) -> dict:
        return {
            "pasta": str(self.pasta),
            "producao": self.producao,
            "midias": len(self.midias),
            "casamentos": len(self.casamentos),
            "fragmentos": self._fragmentos_lidos,
            "pendentes": len(self._novas),
            "raizes": dict(self.raizes),
        }


# ── auxiliares ──────────────────────────────────────────────────────────────

def _chave_de_midia(raiz: str, rel: str, caminho: str) -> str:
    """Identidade de um arquivo no banco.

    `raiz/rel` quando há raiz — é a forma que atravessa máquinas. Sem raiz, o absoluto
    normalizado, que só vale onde os caminhos são iguais.
    """
    return f"{raiz}/{rel}" if raiz and rel else _chave_local(caminho)


def _alvo(linha: dict) -> str:
    """Que ARQUIVO uma linha aponta — a identidade que distingue dois casamentos."""
    raiz, rel = linha.get("raiz") or "", linha.get("rel") or ""
    return f"{raiz}/{rel}" if raiz and rel else _chave_local(linha.get("abs") or "")


def _duracao_do_master(master) -> float | None:
    """Duração do master em segundos. Mesma conta do `matcher_masters`.

    ⚠️ Devolve `None` na rota AAF, onde `duracao_frames` não é preenchido — o portão
    fica neutro e a defesa passa a ser a espécie e a revalidação. Ver `Banco.decidir`.
    """
    frames = getattr(master, "duracao_frames", None)
    taxa = getattr(master, "edit_rate", None)
    if frames and taxa:
        return frames / taxa
    return None


def _mais_nova(nova: dict, velha: dict | None) -> bool:
    if velha is None:
        return True
    return str(nova.get("carimbo") or "") >= str(velha.get("carimbo") or "")


def _agora() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _autor_padrao() -> str:
    maquina = ""
    try:
        maquina = socket.gethostname()
    except OSError:
        pass
    usuario = os.environ.get("USERNAME") or os.environ.get("USER") or "editor"
    return f"{maquina or 'maquina'}/{usuario}"


def _nome_de_arquivo(texto: str) -> str:
    """Nome de fragmento seguro a partir de `<host>/<usuário>`."""
    limpo = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in texto or "")
    return limpo.strip("-")[:80] or "maquina"


def _ler_json(caminho: Path) -> dict | None:
    try:
        dados = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # ⚠️ Um JSON válido pode ser uma lista, um número, `null`. Quem chama faz `.get`.
    return dados if isinstance(dados, dict) else None


def _ler_jsonl(caminho: Path):
    """Uma linha por vez, **pulando o que não parseia**.

    ⚠️ Não é tolerância decorativa: a última linha pode estar sendo escrita por outra
    máquina neste instante, e um arquivo vindo da rede é entrada não confiável. Uma
    linha ruim não pode custar as outras dez mil.
    """
    try:
        with open(caminho, encoding="utf-8") as fh:
            for n, linha in enumerate(fh, 1):
                if not linha.strip() or len(linha) > _MAX_LINHA:
                    continue
                try:
                    yield json.loads(linha)
                except ValueError:
                    log.debug("linha %d ilegível em %s — pulando", n, caminho.name)
    except OSError as e:
        log.warning("não consegui ler %s (%s)", caminho, e)


def _ler_jsonl_do_mapa(caminho: Path):
    """O consolidado é JSONL como os fragmentos — mesma leitura, mesma tolerância."""
    if caminho.is_file():
        yield from _ler_jsonl(caminho)
