r"""Conectar o projeto do Avid a um banco de mídias — criar, conectar, desconectar.

O motor (`media/banco_midias.py`) sabe o FORMATO do banco. Este módulo sabe o resto: onde
mora a configuração, como o projeto aberto decide qual banco vale, e como as raízes de
mídia desta máquina são declaradas.

## Onde a configuração vive, e por que na pasta do PROJETO

`<pasta do projeto>/.delapraca.json`, com o **caminho** do banco — nunca o banco.

⭐ **É isso que faz o banco "seguir o projeto" sem ninguém configurar nada.** Abrir o
projeto no Media Composer é o gesto que já diz em que produção se está trabalhando; o
serviço lê a pasta do projeto pela API e acha a configuração ali. Guardá-la na máquina
(em `pasta_dados()`) daria o efeito errado: o banco da novela seguiria o EDITOR para
dentro do projeto de outro cliente.

⭐ E cai de graça o que o usuário pediu: **trocar de projeto desconecta o banco**. Não há
código para isso — a configuração simplesmente é outra, porque a pasta é outra.

⭐ Também funciona para a EQUIPE: a pasta do projeto costuma ser compartilhada, então o
assistente que abrir o mesmo projeto já encontra o banco conectado, sem repetir o gesto.

⚠️ O caminho é guardado nas DUAS formas — absoluto e relativo à pasta do projeto. O
relativo só existe quando os dois estão no mesmo volume, e é o que sobrevive a montagens
diferentes; o absoluto é o que funciona quando o banco está noutro disco. Ler tenta o
relativo primeiro, porque é o portátil.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import plataforma

log = logging.getLogger("delapraca.banco")

#: Discreto por convenção. ⚠️ No Windows um nome iniciado por ponto **não** é oculto de
#: verdade — some do `ls` do POSIX, não do Explorer. É o suficiente: quem precisar mexer
#: à mão (inclusive nós, depurando) acha; quem não precisar, não tropeça.
CONFIG = ".delapraca.json"


def caminho_da_config(pasta_projeto: str) -> Path:
    return Path(pasta_projeto) / CONFIG


# ── configuração no projeto ─────────────────────────────────────────────────

def ler_config(pasta_projeto: str) -> dict:
    """O que está configurado para ESTE projeto. `{}` quando não há nada."""
    if not pasta_projeto:
        return {}
    try:
        dados = json.loads(caminho_da_config(pasta_projeto).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dados if isinstance(dados, dict) else {}


def gravar_config(pasta_projeto: str, dados: dict) -> bool:
    """Grava a configuração do projeto. Atômica, e nunca levanta.

    ⚠️ Temporário na MESMA pasta: `os.replace` só é atômico dentro do mesmo volume — a
    lição que este projeto pagou com uma bin corrompida.
    """
    if not pasta_projeto:
        return False
    alvo = caminho_da_config(pasta_projeto)
    tmp = alvo.with_name(f"{CONFIG}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, alvo)
        return True
    except (OSError, ValueError) as e:
        log.warning("não consegui gravar %s (%s)", alvo, e)
        return False


def _guardar_caminho(pasta_projeto: str, pasta_banco: str) -> dict:
    """O par absoluto+relativo. O relativo só nasce se couber."""
    entrada = {"abs": str(pasta_banco)}
    try:
        p_proj, p_banco = Path(pasta_projeto).resolve(), Path(pasta_banco).resolve()
        if p_proj.anchor and p_proj.anchor == p_banco.anchor:
            entrada["rel"] = os.path.relpath(p_banco, p_proj).replace(os.sep, "/")
    except (OSError, ValueError):
        pass
    return entrada


def _resolver_caminho(pasta_projeto: str, entrada: dict) -> str | None:
    """Do que está guardado ao caminho desta máquina. Relativo primeiro: é o portátil."""
    rel = (entrada or {}).get("rel")
    if rel and pasta_projeto:
        candidato = Path(pasta_projeto) / rel.replace("/", os.sep)
        if (candidato / "banco.json").is_file():
            return str(candidato)
    absoluto = (entrada or {}).get("abs")
    if absoluto and (Path(absoluto) / "banco.json").is_file():
        return absoluto
    return None


# ── raízes de mídia desta máquina ───────────────────────────────────────────

def raizes_locais(pastas: list[str] | None = None) -> dict[str, str]:
    """`{rótulo do volume: raiz}` — o que traduz um caminho entre máquinas.

    ⭐ O rótulo é a mesma identidade que o Avid usa na coluna `Drive` da bin, e é o que
    sobrevive a montar o mesmo acervo com outra letra. Vem do sistema
    (`plataforma.volumes_montados`), não de configuração.

    ⚠️ Volume sem rótulo não vira raiz: um nome vazio casaria com tudo. Nesse caso o
    banco guarda só o caminho absoluto, que ainda funciona onde as letras são
    padronizadas — que é o caso desta casa.
    """
    fora: dict[str, str] = {}
    for letra, rotulo in (plataforma.volumes_montados() or {}).items():
        if rotulo:
            fora.setdefault(rotulo, f"{letra}:\\")
    # As pastas de mídia em UNC não têm letra nem rótulo: a raiz é o próprio
    # compartilhamento (`\\SERVIDOR\share`), que é estável entre máquinas.
    for pasta in pastas or []:
        p = Path(pasta)
        if str(p).startswith("\\\\") and len(p.parts) >= 1:
            raiz = p.parts[0]
            fora.setdefault(raiz.strip("\\").replace("\\", "-"), raiz)
    return fora


# ── as três ações do painel ─────────────────────────────────────────────────

def estado(pasta_projeto: str, pastas: list[str] | None = None) -> dict:
    """O que o painel precisa saber: há banco? qual? com o quê dentro?"""
    entrada = (ler_config(pasta_projeto) or {}).get("banco") or {}
    caminho = _resolver_caminho(pasta_projeto, entrada)
    if not caminho:
        # ⚠️ Config apontando para um banco inalcançável (rede fora, pasta movida) NÃO é
        # erro: é "desconectado", com o motivo. Levantar aqui bloquearia o relink inteiro
        # por causa de um acelerador opcional.
        return {"conectado": False,
                "aviso": ("o banco configurado neste projeto não foi encontrado"
                          if entrada else "")}

    from media import banco_midias

    banco = banco_midias.Banco.abrir(caminho, raizes=raizes_locais(pastas))
    est = banco.estatisticas()
    est.update({"conectado": True, "nome": banco.producao or Path(caminho).name})
    return est


def criar(pasta_projeto: str, caminho_escolhido: str) -> dict:
    """Cria um banco no caminho que o editor compôs no diálogo de salvar.

    ⭐ O que ele digitou vira o NOME da pasta do banco, não um arquivo: um banco é uma
    pasta (`banco.json` + `fragmentos/` + `mapa.json`). Assim o que ele vê no Explorer é
    uma pasta com o nome que escolheu, em vez de um `.json` solto cujo nome não explica
    nada.
    """
    from media import banco_midias

    escolhido = Path(caminho_escolhido)
    # O diálogo de salvar devolve um "arquivo"; o nome dele é o do banco. Tirar uma
    # extensão que o editor tenha digitado por hábito evita "NOVELA X.json" como nome.
    nome = escolhido.stem if escolhido.suffix.lower() == ".json" else escolhido.name
    nome = _nome_limpo(nome)
    if not nome:
        raise ValueError("dê um nome ao banco")

    pasta = escolhido.parent / nome
    if (pasta / "banco.json").is_file():
        raise ValueError(f"já existe um banco chamado “{nome}” nessa pasta")

    banco = banco_midias.Banco(pasta, raizes=raizes_locais(), producao=nome)
    if not banco.consolidar():          # cria a pasta e escreve banco.json + mapa.json
        raise RuntimeError("não consegui criar o banco nesse lugar")
    log.info("banco criado: %s", pasta)
    return conectar(pasta_projeto, str(pasta))


def conectar(pasta_projeto: str, caminho: str) -> dict:
    """Liga este projeto a um banco existente. `caminho` é a pasta ou o `banco.json`."""
    p = Path(caminho)
    if p.name.lower() == "banco.json":
        p = p.parent
    if not (p / "banco.json").is_file():
        raise ValueError("essa pasta não é um banco de mídias (falta o banco.json)")

    config = ler_config(pasta_projeto)
    config["banco"] = _guardar_caminho(pasta_projeto, str(p))
    if not gravar_config(pasta_projeto, config):
        raise RuntimeError("não consegui guardar a configuração na pasta do projeto")
    return estado(pasta_projeto)


def desconectar(pasta_projeto: str) -> dict:
    """Desliga o projeto do banco. ⚠️ Não apaga banco nenhum — só o ponteiro."""
    config = ler_config(pasta_projeto)
    config.pop("banco", None)
    gravar_config(pasta_projeto, config)
    return estado(pasta_projeto)


# ── usar o banco: consultar antes, alimentar depois ─────────────────────────

def abrir(pasta_projeto: str, pastas: list[str] | None = None):
    """O banco conectado a este projeto, ou `None`. Nunca levanta."""
    try:
        entrada = (ler_config(pasta_projeto) or {}).get("banco") or {}
        caminho = _resolver_caminho(pasta_projeto, entrada)
        if not caminho:
            return None
        from media import banco_midias

        return banco_midias.Banco.abrir(caminho, raizes=raizes_locais(pastas))
    except Exception:  # noqa: BLE001 — acelerador nunca derruba o trabalho
        log.warning("não consegui abrir o banco deste projeto", exc_info=True)
        return None


def consultar(pasta_projeto: str, masters: list, pastas: list[str] | None = None) -> dict:
    """Preenche `caminho_conhecido` nos masters que o banco reconhece **com certeza**.

    ⭐ `caminho_conhecido` é o estágio 1 da cascata do `casar_masters` — confiança 1.00,
    e o mais forte depois da escolha manual. Ele existia e **nunca era preenchido por
    ninguém**; é exatamente o encaixe que o banco procurava.

    ⚠️ Só entra o que o banco classifica como `acerto`: nome, espécie e duração batendo,
    **e** o arquivo revalidado 1:1 no disco. `ambiguo` é deixado de fora de propósito —
    ali o banco sabe que não sabe, e a varredura decide melhor que um palpite.

    Devolve `{"acertos": n, "ambiguos": n, "arquivos": {caminho: nome do master}}`.
    """
    vazio = {"acertos": 0, "ambiguos": 0, "arquivos": {}}
    if not masters:
        return vazio
    banco = abrir(pasta_projeto, pastas)
    if banco is None:
        return vazio

    arquivos: dict[str, str] = {}
    ambiguos = 0
    for master in masters:
        try:
            situacao, linhas = banco.decidir(master)
        except Exception:  # noqa: BLE001
            log.debug("banco não soube decidir %r", getattr(master, "nome", ""),
                      exc_info=True)
            continue
        if situacao == "ambiguo":
            ambiguos += 1
            continue
        if situacao != "acerto":
            continue
        caminho = banco.caminho_de(linhas[0])
        if not caminho:
            continue
        # É este atributo que o matcher lê. Ver `matcher_masters._casar_um`.
        master.caminho_conhecido = caminho
        arquivos[caminho] = getattr(master, "nome", "")

    log.info("banco: %d master(s) já conhecidos, %d ambíguo(s)", len(arquivos), ambiguos)
    return {"acertos": len(arquivos), "ambiguos": ambiguos, "arquivos": arquivos}


def alimentar(pasta_projeto: str, trabalho, resultado: dict | None = None) -> int:
    """Guarda os casamentos que **sobreviveram a um relink aplicado**. Devolve quantos.

    ⭐ Palpite não entra: `decididos()` já é só o que foi resolvido ou escolhido à mão, e
    aqui ainda se descarta o que o Media Composer recusou. O que fica é o par que passou
    pela tela **e** funcionou.

    ⚠️ Nunca levanta. Um relink que deu certo não pode virar erro porque o acelerador
    falhou ao anotar — a rede em `banco_midias.gravar` é a mesma, esta é a de fora.
    """
    try:
        banco = abrir(pasta_projeto, getattr(trabalho, "pastas", None))
        if banco is None:
            return 0
        decididos = trabalho.decididos()
        if not decididos:
            return 0
        # Arquivos que o MC recusou não viram conhecimento — seria ensinar o erro.
        recusados = {f.get("arquivo") for f in ((resultado or {}).get("falhas") or [])}
        escolhas = getattr(trabalho, "escolhas", {}) or {}

        n = 0
        for master in getattr(trabalho, "masters", []) or []:
            caminho = decididos.get(getattr(master, "mob_id", ""))
            if not caminho or caminho in recusados:
                continue
            metodo = "manual" if master.mob_id in escolhas else "relink"
            if banco.anotar_casamento_de_master(master, caminho, metodo=metodo):
                n += 1
        gravadas = banco.gravar()
        # Consolidar aqui é oportunista: já estamos com tudo em memória, e o próximo a
        # ler encontra o `mapa.json` pronto em vez de somar fragmentos.
        banco.consolidar()
        log.info("banco alimentado: %d casamento(s), %d linha(s) gravadas", n, gravadas)
        return n
    except Exception:  # noqa: BLE001
        log.warning("não consegui alimentar o banco — o relink não é afetado",
                    exc_info=True)
        return 0


def _nome_limpo(nome: str) -> str:
    """Nome de banco que também serve de nome de pasta."""
    limpo = "".join(c for c in (nome or "") if c.isalnum() or c in " -_.").strip()
    return limpo[:60]
