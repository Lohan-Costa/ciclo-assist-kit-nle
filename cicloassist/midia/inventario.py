"""O inventário do cache: uma linha por MASTER, com o que já se sabe dele.

É o que a aba **Vetores** mostra. Não processa nada e não fala com o Media Composer —
lê o diretório do cache e conta o que encontrou.

## ⭐ Uma linha é um MASTER, e isso tem uma consequência que surpreende

O cache é endereçado pelo UMID do master (ver `cache.py`), e um take sincronizado
**mistura dois masters**: a imagem vem da câmera, o som vem do gravador. Então:

> os quadros de um take e a transcrição do MESMO take moram em **linhas diferentes** —
> uma da espécie `imagem`, outra da espécie `som`.

⚠️ Isso não é defeito da tabela, é o material. Quem listar por take veria a mesma mídia
repetida em cada subclipe que a recorta, e "processar" numa linha processaria as outras
de graça — impossível de explicar ao editor. A tela diz a espécie de cada linha para que
uma coluna vazia se leia como "aqui não há o que transcrever", e não como "falta fazer".

## O que é "atualizado"

`gerador.<estágio>.json` guarda a receita com que o que está em disco foi feito;
`estagios.assinatura()` diz a receita de hoje. Diferente quer dizer **refazer** — é o
mesmo mecanismo que fez a transcrição antiga cair sozinha quando as palavras entraram, e
aqui ele vira uma coluna em vez de um efeito invisível.

## Custo

Uma passada de `rglob` por mídia (bytes e contagem de quadros) mais alguns JSONs
pequenos. ⚠️ A transcrição é o único arquivo grande — dezenas de KB com as palavras —, e
ela é lida só para contar as falas. Com centenas de mídias isso é segundos, e é por isso
que o inventário acontece quando o editor ABRE a aba, nunca dentro de um turno do modelo.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from fractions import Fraction
from pathlib import Path
from typing import Any

from . import cache as _cache
from . import estagios as _estagios
from . import vetores as _vetores

log = logging.getLogger("cicloassist.midia.inventario")


@dataclass
class Estado:
    """O que um estágio tem para uma mídia."""

    #: Há resultado em disco.
    tem: bool = False
    #: O que há foi feito com a receita de HOJE. Sem nada em disco, é `False`.
    atualizado: bool = False
    #: Quadros guardados, ou falas transcritas. ⚠️ Zero com `tem=True` é cache vazio.
    quantos: int = 0
    #: A receita gravada — é daqui que sai o nome do modelo na tela.
    gerador: dict[str, Any] = field(default_factory=dict)

    @property
    def modelo(self) -> str:
        """Como o que foi usado se chama, numa palavra que o editor reconheça."""
        g = self.gerador
        if not g:
            return ""
        if g.get("motor"):
            return f"{g.get('motor')} {g.get('modelo', '')}".strip()
        if g.get("ferramenta"):
            return str(g.get("ferramenta"))
        # O vetor visual grava só o nome do modelo — é ele que o editor precisa ver para
        # saber com que rede o acervo dele foi indexado.
        if g.get("modelo"):
            return str(g.get("modelo"))
        return ""


#: O estágio da decupagem não vive em `estagios.py` (lá são os do CACHE); a fila o trata
#: como um terceiro, e a tela precisa dos três.
DECUPAGEM = "decupagem"
#: ⭐ A decupagem MICRO (`motor/micro.py`): uma nota por trecho, COMPLEMENTAR à macro.
MICRO = "micro"
ESTAGIOS_DA_FILA = (_estagios.TRANSCRICAO, _estagios.VETORES, DECUPAGEM, MICRO)


def arquivos_do_estagio(clipe: dict[str, Any], estagio: str) -> list:
    """Os arquivos que ESTE estágio consome: os OP-Atom de áudio, ou os de imagem.

    ⛔ A varredura guarda por espécie justamente para isto: transcrever pede o ÁUDIO (uma
    track de vídeo no `amix` faz o ffmpeg falhar inteiro), vetorizar e decupar pedem a
    IMAGEM.
    """
    especie = "audio" if estagio == _estagios.TRANSCRICAO else "video"
    return list((clipe.get("por_tipo") or {}).get(especie) or [])


def pode_analisar(clipe: dict[str, Any], estagio: str) -> bool:
    """A FILA conseguiria pegar esta mídia neste estágio?

    ⭐⭐ **Uma conta só, e é por isso que ela mora aqui** (2026-09-20, achado no Assist anterior). A fila (`servico/rotas.rota_analisar`) pulava em silêncio quem não tem arquivo
    da espécie certa — mídia AMA de um volume que ninguém varreu, música importada de outra
    pasta —, e a TELA não sabia disso: o rótulo do botão contava essas mídias e prometia um
    trabalho que a fila nunca faria. O autor viu em 20/09: *"mesmo clicando nas opções elas
    não são processadas"* — 100 de 106 "sem transcrição" não tinham arquivo.
    ⚠️ E no caso da decupagem o PREÇO saía inflado junto, que é o que o produto mais
    promete não fazer.

    ⚠️ Isto responde "dá para processar", nunca "precisa" — quem responde isso é
    `rotas._falta` (a receita de hoje) e a coluna da tabela.
    """
    if not arquivos_do_estagio(clipe, estagio):
        return False
    if estagio != _estagios.TRANSCRICAO and not clipe.get("fps"):
        # Sem a taxa não há como converter tempo em POSIÇÃO de quadro, e chutar 25 fps
        # erraria o quadro em todo material 23,976.
        return False
    return True


@dataclass
class Linha:
    """Uma mídia do cache."""

    chave: str
    nome: str
    #: `imagem`, `som`, `imagem e som` ou `?` — ver o cabeçalho do módulo.
    especie: str
    arquivo: str
    visual: Estado
    fala: Estado
    #: ⭐ O embedding de cada quadro amostrado — o que responde "planos parecidos com
    #: este". É o que dá nome à aba.
    vetor: Estado
    #: Observações que o modelo escreveu sobre trechos deste material.
    notas: int
    bytes: int
    #: A varredura achou a mídia em disco. ⚠️ `False` não quer dizer sumida: quer dizer
    #: que nenhuma varredura passou pela pasta onde ela está.
    no_acervo: bool = False
    #: Tracks do clipe, quando a varredura passou: `{"video": 1, "audio": 2}`.
    tracks: dict[str, int] = field(default_factory=dict)
    #: Quantos arquivos OP-Atom compõem o clipe.
    arquivos: int = 0
    #: ⭐ Tem decupagem do MATERIAL INTEIRO (a nota que a fila de fundo escreve). ⚠️ É
    #: diferente de `notas`: uma nota de take descreve um pedaço, e não dispensa esta.
    decupada: bool = False
    #: ⭐ Em que bins do projeto este master aparece. Vazio quer dizer "a varredura de
    #: bins não passou", **não** "não está no projeto" — a tela precisa da diferença.
    bins: list[str] = field(default_factory=list)
    #: ⭐ O nome da PASTA no cache — o que o editor acha no Explorer. Vazio: não nasceu.
    pasta: str = ""
    #: ⭐⭐ A FILA conseguiria pegar esta mídia, por estágio? Ver `pode_analisar`.
    pode: dict[str, bool] = field(default_factory=dict)
    #: ⭐ A micro: quantos trechos a mídia tem (0 = ainda não detectados), quantos já têm
    #: nota, e se o material é bruto (`None` = ninguém procurou os cortes ainda).
    micro: dict[str, Any] = field(default_factory=dict)
    #: ⭐ Duração em segundos, quando alguém mediu. ⚠️ Zero é **não medido** (mídia que só
    #: aparece na bin, sem arquivo varrido), nunca "mídia de duração zero" — é o que faz a
    #: tela poder dizer *quantas* ficaram de fora da conta de tempo em vez de somar 0.
    duracao_s: float = 0.0

    def como_dicionario(self) -> dict[str, Any]:
        d = asdict(self)
        # `modelo` é propriedade, e `asdict` só leva campos. A tela precisa dele.
        d["visual"]["modelo"] = self.visual.modelo
        d["fala"]["modelo"] = self.fala.modelo
        d["vetor"]["modelo"] = self.vetor.modelo
        return d


def _especie(fonte: dict[str, Any], visual: Estado, fala: Estado,
             tracks: dict[str, int] | None = None) -> str:
    """De que master é esta mídia: o da imagem, o do som, ou os dois?

    ⭐ Três fontes, em ordem de quem sabe mais:

    1. **As tracks do arquivo**, quando a varredura passou — é o que o Avid gravou.
       ⚠️ E aqui está a resposta para a estranheza da tabela: uma diária de câmera é UM
       master com vídeo e áudio (`{"video": 1, "audio": 2}`), então a linha dela pode ter
       as duas colunas; um take sincronizado com som direto são DOIS masters, e aí cada
       um tem a sua.
    2. **O que `anotar_fonte` escreveu** — `master` para imagem, `master_de_som` para som.
    3. O que há em disco no cache, para material processado por uma versão anterior.
    """
    if tracks:
        tem_v, tem_a = tracks.get("video", 0) > 0, tracks.get("audio", 0) > 0
        if tem_v and tem_a:
            return "imagem e som"
        if tem_v:
            return "imagem"
        if tem_a:
            return "som"
    if fonte.get("master"):
        return "imagem"
    if fonte.get("master_de_som"):
        return "som"
    if visual.tem:
        return "imagem"
    if fala.tem:
        return "som"
    return "?"


def _medir(pasta: Path) -> tuple[int, int]:
    """Bytes ocupados e quantos JPEG há, numa passada só.

    Duas passadas seriam duas travessias de diretório: o cache pode estar num
    compartilhamento SMB, onde listar custa ida e volta.
    """
    bytes_ = 0
    quadros = 0
    try:
        for arq in pasta.rglob("*"):
            try:
                # ⛔ MEDIDO no macOS (2026-09-14): em disco exFAT cada arquivo que o Python
                #    grava ganha um `._` ao lado NA HORA (xattr `com.apple.provenance`), e
                #    3 quadros eram contados como 6. Nada daqui é mídia.
                if arq.name.startswith("._") or arq.name == ".DS_Store" or not arq.is_file():
                    continue
                bytes_ += arq.stat().st_size
                if arq.suffix.lower() == ".jpg":
                    quadros += 1
            except OSError:
                continue
    except OSError as e:
        log.warning("não consegui medir %s (%s)", pasta, e)
    return bytes_, quadros


def de_uma(midia: _cache.Midia, clipe: dict[str, Any] | None = None,
           relogio: dict[str, float] | None = None) -> Linha:
    """Tudo que se sabe de uma mídia, sem tocar no Media Composer.

    `clipe` é o que a varredura do acervo achou para esta mesma chave, quando houve
    varredura — é de lá que vêm as tracks e o nome de quem ainda não passou pelo produto.
    """
    # ⭐ UMA leitura do `midia.json` para fonte + nome (ver `cache.Midia.ficha`): pelo
    #   caminho normal o mesmo arquivo era aberto de 3 a 5 vezes por mídia.
    t_ficha = time.monotonic()
    ficha = midia.ficha()
    fonte = ficha.fonte
    achada = midia.achada()
    if relogio is not None:
        relogio["ficha"] = relogio.get("ficha", 0.0) + time.monotonic() - t_ficha
    # ⚠️ `relogio` é opcional e só serve para o LOG saber onde o tempo foi. Medir por fora
    #   deste processo já deu número errado duas vezes em 2026-09-23.
    t0 = time.monotonic()
    bytes_, quantos_quadros = _medir(achada) if achada is not None else (0, 0)
    if relogio is not None:
        relogio["medir"] = relogio.get("medir", 0.0) + time.monotonic() - t0

    gerador_visual = midia.ler_gerador(_estagios.QUADROS)
    visual = Estado(
        tem=quantos_quadros > 0,
        atualizado=bool(gerador_visual)
        and gerador_visual == _estagios.assinatura(_estagios.QUADROS),
        quantos=quantos_quadros,
        gerador=gerador_visual,
    )

    gerador_fala = midia.ler_gerador(_estagios.TRANSCRICAO)
    tem_fala = midia.tem_transcricao()
    # ⚠️ A transcrição é o único arquivo GRANDE do cache (medido: 11,1 MB no total, o maior
    #   com 1,25 MB) e é lida INTEIRA só para contar as falas. O relógio diz se isso pesa.
    t0 = time.monotonic()
    quantas_falas = len(midia.ler_transcricao()) if tem_fala else 0
    if relogio is not None:
        relogio["transcricao"] = (relogio.get("transcricao", 0.0)
                                  + time.monotonic() - t0)
    fala = Estado(
        tem=tem_fala,
        atualizado=bool(gerador_fala)
        and gerador_fala == _estagios.assinatura(_estagios.TRANSCRICAO),
        quantos=quantas_falas,
        gerador=gerador_fala,
    )

    gerador_vetor = midia.ler_gerador(_estagios.VETORES)
    quantos_vetores = _vetores.quantos(midia)
    vetor = Estado(
        tem=quantos_vetores > 0,
        atualizado=bool(gerador_vetor)
        and gerador_vetor == _estagios.assinatura(_estagios.VETORES),
        quantos=quantos_vetores,
        gerador=gerador_vetor,
    )

    clipe = clipe or {}
    tracks = dict(clipe.get("tracks") or {})
    t0 = time.monotonic()
    notas = midia.ler_notas()
    from . import cortes as _cortes
    dos_cortes = _cortes.ler(midia) or {}
    if relogio is not None:
        relogio["notas+cortes"] = (relogio.get("notas+cortes", 0.0)
                                   + time.monotonic() - t0)
    trechos = dos_cortes.get("trechos") or []
    micro = {"trechos": len(trechos),
             "feitos": sum(1 for n in notas if n.get("escopo") == "trecho"),
             # ⭐ Bruto ou montado muda o tempo da micro em ~6× (`motor/micro.py`). Sem
             #   `cortes.json` ninguém sabe qual é: `None`, e a tela mostra a FAIXA.
             "bruto": bool(dos_cortes.get("bruto")) if trechos else None}
    # ⭐ A duração vem da varredura; quando ela não passou, dos cortes, que contaram os
    #   quadros um a um. ⚠️ Nunca inventada: sem as duas, fica zero e a tela conta a mídia
    #   entre as "sem conta de tempo".
    duracao = float(clipe.get("duracao_s") or 0)
    if not duracao and dos_cortes.get("quadros") and dos_cortes.get("taxa"):
        try:
            duracao = dos_cortes["quadros"] / float(Fraction(str(dos_cortes["taxa"])))
        except (ValueError, ZeroDivisionError):
            duracao = 0.0
    return Linha(
        chave=midia.chave,
        # ⭐ O nome do `fonte.json` primeiro: ele foi escrito com a mídia em mãos e é o
        #   que o editor viu na conversa. O da varredura entra quando o produto ainda
        #   não tocou nesta mídia — que é o caso de tudo que "falta analisar".
        nome=str(ficha.nome or clipe.get("nome") or ""),
        especie=_especie(fonte, visual, fala, tracks),
        arquivo=str(fonte.get("arquivo") or ""),
        visual=visual,
        fala=fala,
        vetor=vetor,
        notas=len(notas),
        # ⚠️ Decupada é a MACRO: a micro complementa, não substitui (decisão do editor).
        decupada=any(n.get("escopo") == "midia" for n in notas),
        bytes=bytes_,
        no_acervo=bool(clipe.get("arquivos")),
        tracks=tracks,
        arquivos=len(clipe.get("arquivos") or []),
        bins=list(clipe.get("bins") or []),
        pasta=achada.name if achada is not None else "",
        pode={e: pode_analisar(clipe, e) for e in ESTAGIOS_DA_FILA},
        micro=micro,
        duracao_s=round(duracao, 2),
    )


def listar(raiz: Path | None = None,
           clipes: dict[str, Any] | None = None,
           origem: str | None = None) -> list[Linha]:
    """Todas as mídias — as do cache e as que a varredura achou em disco.

    ⭐⭐ **A união das duas é a tabela.** Sozinho, o cache responde "o que já analisei";
    sozinha, a varredura responde "o que existe". O editor pediu as duas na mesma lista,
    e é a união que faz a coluna vazia significar "falta fazer" em vez de "não sei".

    ⚠️ Pasta inexistente devolve lista vazia, e é o caso NORMAL — antes da primeira
    pergunta não há cache nenhum. Tratar como erro faria a aba parecer quebrada no
    primeiro dia de uso.

    ⛔ Só entram diretórios cujo nome é uma chave válida (`cache.e_chave`). O que mais
    estiver ali — pasta do editor, resto de cópia, arquivo solto — é ignorado em silêncio:
    o inventário lê disco, e disco é entrada não confiável.

    ⛔⛔ `origem` é o BANCO (decisão do editor, 2026-09-21: *cada editor tem o seu*). A aba
    do Premiere não lista entrada do Avid — nem o nome da bin dele, nem um caminho de
    `Avid MediaFiles` — e a do Avid não lista a do Premiere. `None` é sem filtro, o
    comportamento de antes, para quem chama sem saber de banco.
    """
    do_acervo = dict(clipes or {})
    banco = _cache.origem_valida(origem) if origem else ""
    comeco = time.monotonic()
    # ⛔⛔ A `origem` sai do ÍNDICE, que já a leu ao varrer (`_e_midia` guarda `origens`).
    #    Pedindo `midia.origem`, o filtro de banco abria o `midia.json` das 537 mídias só
    #    para descartar a maioria — e ele é o arquivo que `ficha()` já vai ler de quem
    #    ficar. MEDIDO em 2026-09-22: 125 ms só nisso, num inventário que a aba refaz toda
    #    vez que o editor entra nela.
    indice = _cache.indice(raiz)
    relogio: dict[str, float] = {}
    linhas: list[Linha] = []
    for midia in _cache.todas(raiz):
        try:
            if banco and indice.origem_de(midia.chave) != banco:
                continue
            linhas.append(de_uma(midia, do_acervo.pop(midia.chave, None), relogio))
        except (OSError, _cache.ChaveInvalida) as e:
            # Uma pasta ilegível não pode esconder as outras: o editor precisa da lista
            # que dá para montar, não de um erro sobre a pior linha dela.
            log.warning("ignorando %s no inventário (%s)", midia, e)
            continue

    # O que sobrou do acervo é mídia que existe e nunca foi analisada — o "falta" da
    # tabela. Ela não tem pasta de cache, e não é criada uma: gravar diretório vazio por
    # mídia encheria o disco de nada e faria a próxima leitura mentir sobre o que há.
    for chave, clipe in do_acervo.items():
        if not _cache.e_chave(chave):
            continue
        tracks = dict(clipe.get("tracks") or {})
        linhas.append(Linha(
            chave=chave,
            nome=str(clipe.get("nome") or ""),
            especie=_especie({}, Estado(), Estado(), tracks),
            arquivo=(clipe.get("arquivos") or [""])[0],
            visual=Estado(),
            fala=Estado(),
            vetor=Estado(),
            notas=0,
            bytes=0,
            no_acervo=bool(clipe.get("arquivos")),
            tracks=tracks,
            arquivos=len(clipe.get("arquivos") or []),
            bins=list(clipe.get("bins") or []),
            # ⭐ A mesma conta da linha que tem cache: sem ela o botão contaria esta
            #   mídia e a fila a pularia calada (a régua de 2026-09-20).
            pode={e: pode_analisar(clipe, e) for e in ESTAGIOS_DA_FILA},
            # Nunca varrida: não há trecho nenhum, e `bruto` é desconhecido de propósito.
            micro={"trechos": 0, "feitos": 0, "bruto": None},
            duracao_s=round(float(clipe.get("duracao_s") or 0), 2),
        ))

    # Sem nome, a chave. Ordenar por nome é o que o editor procura com o olho; quem não
    # tem nome cai no fim, junto, em vez de se misturar aos que têm.
    linhas.sort(key=lambda linha: (linha.nome == "", linha.nome.lower(), linha.chave))
    # ⚠️ O relógio, para o log saber onde o tempo foi: a aba refaz esta leitura toda vez
    #   que o editor entra nela, e medir por FORA do serviço já deu número errado duas
    #   vezes (2026-09-23). `medir` é o `rglob` de cada pasta; o resto é JSON pequeno.
    log.info("inventário: %d linha(s) em %.2f s%s", len(linhas),
             time.monotonic() - comeco,
             "".join(f" · {o}: {s:.2f}" for o, s in sorted(relogio.items())))
    return linhas


def resumo(linhas: list[Linha]) -> dict[str, Any]:
    """Os números do rodapé da aba."""
    return {
        "midias": len(linhas),
        "com_visual": sum(1 for l in linhas if l.visual.tem),
        "com_fala": sum(1 for l in linhas if l.fala.tem),
        "com_vetor": sum(1 for l in linhas if l.vetor.tem),
        "desatualizadas": sum(
            1 for l in linhas
            if (l.visual.tem and not l.visual.atualizado)
            or (l.fala.tem and not l.fala.atualizado)
            or (l.vetor.tem and not l.vetor.atualizado)
        ),
        # ⭐ O número que o editor quer ver cair: mídia que existe em disco e de que o
        #   produto não sabe nada ainda.
        "sem_analise": sum(1 for l in linhas
                           if not l.visual.tem and not l.fala.tem and not l.vetor.tem),
        "decupadas": sum(1 for l in linhas if l.decupada),
        "no_acervo": sum(1 for l in linhas if l.no_acervo),
        # ⭐ Está na bin e não tem arquivo nas pastas varridas. ⚠️ NÃO é "offline": pode
        #   ser mídia num volume que ninguém mandou varrer, e dizer offline seria afirmar
        #   o que não se mediu.
        "sem_arquivo": sum(1 for l in linhas if l.bins and not l.no_acervo),
        "nas_bins": sum(1 for l in linhas if l.bins),
        "bytes": sum(l.bytes for l in linhas),
    }
