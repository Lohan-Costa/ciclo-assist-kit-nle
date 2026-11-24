"""
avid/masters.py — a ponte entre o que o Órbita sincronizou e o que existe no Avid.

O writer precisa, por clipe, do **MobID do master** que o Media Composer já tem na
bin. Este módulo o descobre, por dois caminhos que se complementam:

1. **Do próprio arquivo**, quando a mídia é OP-Atom (gerenciada). O `.mxf` carrega
   o `material_package_umid`, que É o MobID do master. Não precisa perguntar nada
   ao Media Composer — nem que ele esteja aberto.
2. **Perguntando ao Media Composer**, quando o Órbita sincronizou os arquivos
   ORIGINAIS (`.mov`, `.wav`) e o editor os importou. Aí a única ligação é o NOME,
   e o Avid acrescenta sufixos ao importar (`X.mov` vira `X.new.01`).

O caminho 1 é exato — casa por identidade. O caminho 2 é por nome, e por isso é o
segundo: nome é frágil (o editor pode renomear na bin), mas é a única ponte quando
o arquivo em disco não é o que está na bin.
"""

from __future__ import annotations

import os
import re
import time
from pathlib import Path

import registro
from avid.mcapi import McApiNaoImplementado

#: ⛔ **ESTE MÓDULO DECIDE ONDE A MÍDIA ESTÁ, e até 2026-08-23 não registrava NADA.**
#: Quando o app dizia "clipes não encontrados no disco", o log inteiro sobre o
#: assunto era a linha `Comando: avid_selection` do `main.py`. Num relato de campo —
#: quem testa no Nexis não tem sessão de desenvolvimento aberta — isso é o mesmo que
#: não ter log. As linhas abaixo existem para responder, sem ninguém por perto:
#: **que volume o Avid disse, a que raiz isso virou (ou por que não virou), quantos
#: arquivos foram lidos, e onde cada master se resolveu.**
log = registro.log(__name__)

# Sufixos que o Avid acrescenta ao NOME do clipe ao importar/transcodar. Não
# existem no arquivo original: `X.mov` na bin vira `X.new.01`.
_SUFIXO_AVID = re.compile(r"\.(new|sync|cds|grp|sub|copy|exported|cpy)\.\d{1,4}$", re.I)


def nome_base(nome: str) -> str:
    """Tira os sufixos do Avid e a extensão de mídia — o que sobra é o que os dois
    lados têm em comum.

        '20260101_CAM0001.new.01'  → '20260101_cam0001'
        '20260101_CAM0001.mov'     → '20260101_cam0001'
    """
    anterior = None
    while nome != anterior:
        anterior = nome
        nome = _SUFIXO_AVID.sub("", nome)
    base = nome.lower()
    for ext in (".mov", ".mxf", ".mp4", ".wav", ".aif", ".aiff", ".mp3", ".m4a"):
        if base.endswith(ext):
            return base[: -len(ext)]
    return base


def arquivos_por_umid(raizes: list[str], on_progress=None) -> dict[str, list[str]]:
    """`{mob_id do pyavb: [arquivos OP-Atom do clipe]}` varrendo pastas de mídia.

    É o CAMINHO DE VOLTA quando o arquivo original já não existe — cartão
    devolvido, projeto movido de máquina. A mídia gerenciada continua no disco, e
    o `material_package_umid` de cada OP-Atom é a mesma identidade que a bin usa.

    Custa um `ffprobe` por arquivo, então só se usa quando `Source File` falhou.
    """
    from media import opatom

    from .mcapi import mob_id_para_pyavb

    return varredura_por_umid(raizes, on_progress=on_progress)[0]


def varredura_por_umid(raizes: list[str], on_progress=None
                       ) -> tuple[dict[str, list[str]], set[str]]:
    """`({mob_id: [arquivos]}, {mob_ids que são SÓ ÁUDIO})` numa varredura só.

    ⭐ **Por que o conjunto de "só áudio" vem junto:** a mídia gerenciada do Avid
    é toda `.mxf`, inclusive a de som — um gravador de set vira OP-Atom `.mxf`
    igual a uma câmera. Quem classificar fonte pela EXTENSÃO do arquivo conclui
    que o som direto é câmera, e o rótulo sai errado na interface (aconteceu: uma
    bin `SOM DIRETO` inteira apareceu como "CAM B").

    O discriminador certo é a ESSÊNCIA, e ela já foi lida nesta varredura: um
    `OpAtomClip` **sem track de vídeo** é som. Devolver junto evita um segundo
    `ffprobe` por arquivo só para descobrir isso.
    """
    from media import opatom

    res = opatom.scan(raizes, on_progress=on_progress)
    # Sem vídeo E com áudio: som. (Sem os dois seria track de dados solta.) A regra
    # mora em `_por_umid_de`, que a busca dirigida usa também — duas cópias dela
    # divergiriam, e a divergência apareceria como som direto rotulado "CAM B".
    return _por_umid_de_clipes(res.clips)


#: Tokens da coluna `Tracks` da bin: `V1`, `A1-5`, `D1`. Um intervalo conta o
#: intervalo inteiro (`A1-5` = 5 arquivos).
_TOKEN_DE_TRACK = re.compile(r"([A-Za-z]+)\s*(\d+)(?:\s*-\s*(\d+))?")

#: Só estas viram ARQUIVO OP-Atom. `TC`/`EC` aparecem em sequências e não são
#: essência — contá-las faria a busca parar antes da hora.
_TRACKS_DE_ESSENCIA = ("V", "A", "D")

#: Prefixo mínimo para o nome de um arquivo "puxar" para um master na fila. Abaixo
#: disso é ruído: dois arquivos quaisquer partilham uma letra ou duas.
_AFINIDADE_MINIMA = 4


def arquivos_previstos(tracks: str | None) -> int | None:
    """Quantos arquivos OP-Atom este master tem, lido da coluna `Tracks` da bin.

        'V1 A1-2' → 3        'A1-5' → 5        'V1' → 1

    ⭐⭐ **É O SINAL DE PARADA, e é o que torna a busca proporcional ao MATERIAL
    PEDIDO em vez de ao tamanho do acervo.** Medido em 2026-08-22: somando o
    `Tracks` dos 50 masters de uma diária dá **198**, exatamente os 198 arquivos
    que a varredura completa encontra depois de ler 1984. Com ele, 109,7 s viram
    ~11 s — e vem de graça, no `GetMobInfo` que já se faz por outro motivo.

    `None` quando não dá para ler: aí **não há parada** para aquele master, e a
    busca vai até o fim da fila. Devolver um palpite seria pior que devolver nada —
    parar cedo demais deixa um clipe sem canal de áudio, calado.
    """
    if not tracks:
        return None
    total = 0
    for tipo, inicio, fim in _TOKEN_DE_TRACK.findall(tracks):
        if tipo.upper() not in _TRACKS_DE_ESSENCIA:
            continue
        total += (int(fim) - int(inicio) + 1) if fim else 1
    return total or None


def alvos_de_busca(mob_ids: list[str], colunas: dict[str, dict]) -> dict[str, dict]:
    """`{mob_id do pyavb: {"nome", "arquivos"}}` — o que procurar e quando parar.

    A chave é a forma do pyavb porque é ela que a mídia em disco carrega (o
    `material_package_umid` do OP-Atom), e não a forma que a API devolve.
    """
    from .mcapi import mob_id_para_pyavb

    fora: dict[str, dict] = {}
    for mob in mob_ids:
        col = colunas.get(mob) or {}
        try:
            chave = mob_id_para_pyavb(mob)
        except Exception:
            continue          # sem chave não há como casar; a varredura o ignora
        fora[chave] = {
            "nome": (col.get("Name") or "").strip(),
            "arquivos": arquivos_previstos(col.get("Tracks")),
        }
    return fora


def _prefixo_comum(a: str, b: str) -> int:
    n = 0
    for x, y in zip(a, b):
        if x != y:
            break
        n += 1
    return n


def fila_de_busca(arquivos: list[str], alvos: dict[str, dict]) -> list[str]:
    """A fila de arquivos a probar, ORDENADA pela afinidade de nome.

    ⚠️⚠️ **ORDENA, NUNCA EXCLUI — e a diferença não é conservadorismo, é o que a
    medição obriga.** O nome do arquivo OP-Atom aparece em **três** convenções
    diferentes no mesmo acervo de teste (2026-08-23, Windows, MC 25.6):

    | convenção | exemplo | leva o nome? |
    |---|---|---|
    | nome inteiro + track | `PROJETO EXEMPLO - 05-04 C4 P1-T001_A01.mxf` | ✅ inteiro |
    | nome TRUNCADO + hash | `PROJETO EXEA01.6A8AF212609FA.mxf` | ⚠️ 10 caracteres |
    | só track + hash | `V01.E69CCF0F_1A8ED1A8EDCFCV.mxf` | ⛔ **nenhum** |

    Um filtro que EXCLUÍSSE o que não casa com o `Name` da bin perderia o acervo
    inteiro da terceira linha — e perderia calado, com o app dizendo "clipes não
    encontrados no disco" em cima de mídia que está ali.

    ⭐ **O que escala é a PARADA, não o filtro** (`arquivos_previstos`). O filtro
    só decide a ORDEM: no caso feliz os candidatos certos vêm primeiro e a parada
    chega em dezenas de arquivos; no caso da terceira linha ele não ajuda em nada e
    a parada continua valendo, porque ela conta o que foi ACHADO, não o que foi
    lido.

    ⚠️⚠️ **E quando o nome não diz nada, a ordem alfabética é PIOR que aleatória.**
    Medido em 2026-08-23: no acervo da terceira convenção a pasta certa (`…/PRJ`)
    vem por último no alfabeto, atrás de `010020260629` e `BENTIDO-FIELD` — o
    primeiro acerto só aparecia no arquivo 446 de 511, tarde demais para a parada
    servir de alguma coisa. Por isso as pastas SEM afinidade nenhuma são
    **intercaladas** em vez de concatenadas: assim o primeiro acerto chega nos
    primeiros arquivos, seja qual for a pasta, e a afinidade de pasta de
    `varredura_dirigida` assume dali em diante.
    """
    bases = [b for b in (nome_base(a.get("nome") or "") for a in alvos.values())
             if len(b) >= _AFINIDADE_MINIMA]

    def afinidade(caminho: str) -> int:
        if not bases:
            return 0
        alvo = Path(caminho).stem.lower()
        melhor = max(_prefixo_comum(alvo, b) for b in bases)
        return melhor if melhor >= _AFINIDADE_MINIMA else 0

    por_pasta: dict[str, list[str]] = {}
    for q in sorted(arquivos):
        por_pasta.setdefault(str(Path(q).parent), []).append(q)
    for lista in por_pasta.values():
        lista.sort(key=lambda q: (-afinidade(q), q))

    # A pasta vale o melhor arquivo que tem. As que casam com algum `Name` vêm
    # inteiras, na frente — ali o filtro sabe o que está fazendo.
    escore = {p: max(afinidade(q) for q in lista) for p, lista in por_pasta.items()}
    com_pista = sorted((p for p in por_pasta if escore[p]), key=lambda p: -escore[p])
    sem_pista = sorted(p for p in por_pasta if not escore[p])

    fila = [q for p in com_pista for q in por_pasta[p]]
    # Round-robin entre as pastas sem pista: uma amostra de cada uma antes de
    # esgotar qualquer uma.
    restos = [list(por_pasta[p]) for p in sem_pista]
    while restos:
        for lista in restos:
            fila.append(lista.pop(0))
        restos = [lista for lista in restos if lista]
    return fila


def varredura_dirigida(raizes: list[str], alvos: dict[str, dict],
                       arquivos: list[str], on_progress=None
                       ) -> tuple[dict[str, list[str]], set[str], set[str], bool]:
    """Procura SÓ os masters pedidos, e PARA quando todos estiverem completos.

    Devolve `(por_umid, so_audio, arquivos_lidos, fila_esgotada, completos)`.

    ⛔⛔ **`completos` é o campo que impede o defeito mais caro desta função**, e ele
    só existe porque a régua o pegou (2026-08-23, `PRJ/D01`: 13/13 virou 12/13 com
    **um erro CALADO**, e a contagem de arquivos caiu de 63 para 62).

    O mecanismo: a busca de uma bin lê, de passagem, arquivos de clipes de OUTRA
    bin — e para no meio deles. Esses clipes ficam no índice **incompletos**, e o
    arrasto seguinte, vendo o MobID já presente, não vai procurar o resto. O clipe
    chega à timeline sem um canal, sem erro nenhum.

    Só quem bateu o `Tracks` (ou quem apareceu numa fila lida até o fim) entra em
    `completos`. O resto vale como palpite: serve para responder agora, **não** para
    dispensar a próxima busca.

    ⭐⭐ **A diferença para `varredura_por_umid` não é velocidade de leitura — é
    quantos arquivos se lê.** Medido (2026-08-22, HD mecânico, 1984 `.mxf` no
    acervo, 50 masters pedidos):

    | estratégia | tempo | `ffprobe` |
    |---|---|---|
    | varredura completa | 109,67 s | 1984 |
    | **dirigida (esta)** | **10,96 s** | **198** |

    ⚠️ **A contagem de "completo" é por `file_package_umid` DISTINTO, não por
    arquivo lido.** O mesmo clipe existe copiado entre as pastas numeradas da
    `Avid MediaFiles` (`MXF/1`, `MXF/2`), e contar arquivo faria um clipe de 3
    tracks "completar" com o vídeo lido três vezes — parando com o clipe sem áudio
    nenhum, calado.

    ⚠️ Master cujo `Tracks` não se leu (`arquivos=None`) não tem parada: a fila vai
    até o fim por causa dele. É o comportamento de antes, e é o certo — o preço de
    não saber é ler tudo, não é adivinhar.
    """
    from media import opatom

    from .mcapi import mob_id_para_pyavb

    inicio = time.perf_counter()
    fila = fila_de_busca(arquivos, alvos)
    sem_parada = sum(1 for a in alvos.values() if not a.get("arquivos"))
    log.info("Busca dirigida: %d alvo(s), %d arquivo(s) na fila%s",
             len(alvos), len(fila),
             f" — ⚠ {sem_parada} sem 'Tracks' (não têm parada, a fila vai até o fim)"
             if sem_parada else "")
    pendentes = {m: a for m, a in alvos.items()}
    achados: dict[str, set[str]] = {}
    lidos: list = []
    vistos: set[str] = set()
    completos: set[str] = set()
    esgotada = True

    # ⭐⭐ AS PASTAS QUE JÁ DERAM ACERTO vão para a frente da fila.
    #
    # ⛔ **O que isto conserta, medido em 2026-08-23:** no acervo cuja convenção de
    # nome é `A01.E69CCE71_….mxf` (sem nome nenhum no arquivo) o filtro de
    # `fila_de_busca` não ordena nada, e a busca lia a fila INTEIRA — 511 arquivos
    # para achar 63. A parada existia e nunca chegava a tempo, porque o último
    # master pendente caía no fim de uma ordem alfabética.
    #
    # ⭐ O sinal que sobra quando o nome falha é a PASTA: o Avid grava as N tracks
    # de um clipe juntas, e uma diária inteira mora numa pasta só. O primeiro acerto
    # revela onde o material está — e isso é informação que não existia antes de
    # começar a ler, por isso ela entra no meio da leitura e não na ordenação
    # inicial.
    quentes: set[str] = set()
    esfriou = [False]          # só reordena quando a lista de quentes MUDOU

    def reordenar(restantes: list[str]) -> list[str]:
        if not esfriou[0]:
            return restantes
        esfriou[0] = False
        dentro = [q for q in restantes if str(Path(q).parent) in quentes]
        if not dentro or len(dentro) == len(restantes):
            return restantes
        fora = [q for q in restantes if str(Path(q).parent) not in quentes]
        return dentro + fora

    for caminho, doc in opatom.probar_muitos(fila, on_progress=on_progress,
                                             reordenar=reordenar):
        vistos.add(caminho)
        if doc is None:
            continue
        lido = opatom.parse_probe(doc, caminho)
        if isinstance(lido, str):
            continue          # não é OP-Atom; segue como a varredura completa faz
        lidos.append(lido)
        try:
            chave = mob_id_para_pyavb(lido.clip_umid)
        except Exception:
            continue
        alvo = pendentes.get(chave)
        if alvo is None:
            continue
        pasta = str(Path(caminho).parent)
        if pasta not in quentes:
            quentes.add(pasta)
            esfriou[0] = True
        marca = achados.setdefault(chave, set())
        marca.add(lido.file_umid or lido.path)
        previstos = alvo.get("arquivos")
        if previstos and len(marca) >= previstos:
            del pendentes[chave]
            completos.add(chave)
            if not pendentes:
                esgotada = False
                break

    # Ler a fila inteira equivale a uma varredura completa DAQUELES arquivos: aí
    # todo clipe que apareceu apareceu inteiro.
    por_umid, so_audio = _por_umid_de(lidos)
    if esgotada:
        completos.update(por_umid)

    # ⭐ A LINHA QUE RESPONDE "por que a busca demorou tanto / achou de menos".
    # `lidos` contra `fila` é a medida da PARADA — a coisa que faz esta função
    # custar 200 `ffprobe` em vez de 1984 (ver a tabela na docstring). `parou em`
    # separa os dois desfechos que se parecem no resultado e não na causa:
    # completou os alvos, ou acabou a fila sem completar.
    log.info("Busca dirigida: %d/%d arquivo(s) lido(s), %d de %d alvo(s) completo(s), "
             "parou em %s, %.2f s",
             len(vistos), len(fila), len(completos), len(alvos),
             "fila esgotada" if esgotada else "todos os alvos completos",
             time.perf_counter() - inicio)
    if pendentes:
        # Cada nome aqui é um clipe que o editor vai ver como "não encontrado".
        log.warning("Busca dirigida: %d alvo(s) NÃO completaram: %s",
                    len(pendentes),
                    ", ".join(sorted((a.get("nome") or m) for m, a in pendentes.items())))
    return por_umid, so_audio, vistos, esgotada, completos


def _por_umid_de(arquivos) -> tuple[dict[str, list[str]], set[str]]:
    """`OpAtomFile` lidos → `({mob_id: [arquivos]}, {mob_ids só de áudio})`."""
    from media import opatom

    clipes, _duplicatas = opatom.group(arquivos)
    return _por_umid_de_clipes(clipes)


def _por_umid_de_clipes(clipes) -> tuple[dict[str, list[str]], set[str]]:
    """`OpAtomClip` reunidos → o mesmo par. A regra de "isto é som" mora aqui."""
    from .mcapi import mob_id_para_pyavb

    fora: dict[str, list[str]] = {}
    so_audio: set[str] = set()
    for c in clipes:
        if not c.umid:
            continue
        try:
            chave = mob_id_para_pyavb(c.umid)
        except Exception:
            continue          # UMID que não converte não derruba a varredura
        fora[chave] = c.paths
        # Sem vídeo E com áudio: som. (Sem os dois seria track de dados solta.)
        if not c.video and c.audio:
            so_audio.add(chave)
    return fora, so_audio


#: O índice UMID → arquivos da mídia gerenciada, guardado enquanto o sidecar viver.
#: `{raízes: {assinatura, por_umid, so_audio, vistos, completo}}`.
_INDICE_DA_MIDIA: dict = {}


def indice_da_midia_do_avid(raizes: list[str], alvos: dict[str, dict] | None = None,
                            on_progress=None):
    """`({mob_id: [arquivos]}, {mob_ids só de áudio})`, reaproveitando a varredura.

    ⭐⭐ **POR QUE EXISTE, com número.** A varredura é UM `ffprobe` POR ARQUIVO —
    medido em 2026-08-18 na máquina do autor: **457 arquivos, 58 ms cada, 26,7 s**.
    Ela roda sempre que um master não tem arquivo de origem, que é o caso de TODA
    mídia transcodada pelo Avid (os clipes `.new.01`).

    Enquanto a entrada era uma leitura de seleção por sessão, esses 26,7 s eram
    pagos uma vez. **O arrasto mudou isso**: ele é o gesto principal e é REPETIDO —
    uma câmera por arrasto —, então cada arrasto refazia a varredura inteira. Três
    câmeras eram 80 s de espera para uma resposta que já estava na memória.

    ⚠️ **A invalidação é a LISTA DE ARQUIVOS**, não o tempo. Listar custa 0,15 s
    contra 26,7 s de varredura (178× mais barato), então dá para conferir a cada
    chamada em vez de apostar num prazo. Transcodificar mídia nova no meio da sessão
    faz aparecer arquivo novo, a lista muda e o índice se refaz sozinho.

    Não se guarda em disco de propósito: o cache do projeto é para trabalho caro e
    reaproveitável entre sessões, e este índice é barato de refazer e depende do
    estado da pasta de mídia AGORA.

    ⭐ **`alvos` (2026-08-23) muda a natureza do índice: de COMPLETO para
    ACUMULADO.** Com `alvos` (ver `alvos_de_busca`) a leitura é dirigida — lê o que
    precisa e para (`varredura_dirigida`), guardando o que aprendeu. Cada arrasto
    seguinte reaproveita o que já está aqui e só paga pelo que falta. Sem `alvos`,
    o comportamento é o de sempre: varre tudo, uma vez.

    ⚠️ **Um índice acumulado é PARCIAL, e isso é uma armadilha própria:** perguntar
    por um master que nunca foi pedido não pode devolver "não existe" só porque
    ninguém procurou por ele ainda. Por isso `completo` é guardado à parte, e um
    alvo ausente do índice manda buscar em vez de responder de memória.
    """
    from media import opatom

    chave = tuple(sorted(raizes))
    atuais = tuple(opatom.arquivos_mxf(raizes))
    # ⛔⛔ A assinatura leva TAMANHO e DATA de cada arquivo, não só o caminho
    # (Ciclo Assist, 2026-11-01). Repetindo o mesmo fluxo, o Resolve regravou os
    # MXF com OS MESMOS NOMES nas MESMAS pastas: a lista de caminhos não mudou, o
    # índice velho valeu, os UMIDs novos não estavam nele e todo arquivo já
    # constava como "visto" — fila VAZIA, 8 de 8 masters "sem arquivo", e o sync
    # recusado com "0 fonte(s) com mídia" com a mídia online no MC. Num processo
    # novo a mesma leitura dava 8 de 8. O `stat` sai junto da listagem.
    assinatura = _assinatura_dos_arquivos(atuais)
    est = _INDICE_DA_MIDIA.get(chave)
    if est is None or est["assinatura"] != assinatura:
        est = {"assinatura": assinatura, "por_umid": {}, "so_audio": set(),
               "vistos": set(), "completos": set(), "completo": False}
        _INDICE_DA_MIDIA[chave] = est

    # ⛔ "Já está no índice" NÃO basta para dispensar a busca: uma busca anterior
    # pode ter lido esse clipe pela metade, de passagem, e parado. Só `completos`
    # — quem bateu o `Tracks` — responde sem procurar. Ver `varredura_dirigida`.
    se_faltam = [m for m in (alvos or {}) if m not in est["completos"]]

    if alvos is None:
        if not est["completo"]:
            por_umid, so_audio = varredura_por_umid(raizes, on_progress=on_progress)
            # A varredura completa é AUTORITATIVA: ela viu todos os arquivos, então
            # sobrescreve qualquer entrada parcial que uma busca dirigida tenha
            # deixado (um clipe cujo `Tracks` previu menos do que há no disco).
            est["por_umid"].update(por_umid)
            est["so_audio"].update(so_audio)
            est["vistos"] = set(atuais)
            est["completos"].update(por_umid)
            est["completo"] = True
    elif se_faltam and not est["completo"]:
        # ⚠️ Os arquivos já lidos só saem da fila quando o que se procura NÃO está
        # entre os clipes que ficaram pela metade — senão o resto deles nunca seria
        # procurado. Na prática: relê só quando há parcial em jogo.
        parciais = [m for m in se_faltam if m in est["por_umid"]]
        restantes = (list(atuais) if parciais
                     else [q for q in atuais if q not in est["vistos"]])
        por_umid, so_audio, vistos, esgotada, completos = varredura_dirigida(
            raizes, {m: alvos[m] for m in se_faltam}, restantes,
            on_progress=on_progress)
        for mob, arqs in por_umid.items():
            # Quem veio COMPLETO manda; quem veio pela metade só preenche buraco.
            if mob in completos:
                est["por_umid"][mob] = arqs
            else:
                est["por_umid"].setdefault(mob, arqs)
        est["so_audio"].update(so_audio)
        est["vistos"].update(vistos)
        est["completos"].update(completos)
        if esgotada and est["vistos"] >= set(atuais):
            est["completo"] = True

    # ⚠️ CÓPIA, nunca a referência guardada. Quem chama mexe no que recebe, e um
    # `pop`/`append` do chamador chegaria ao índice — a segunda leitura viria
    # mutilada, e o defeito apareceria longe daqui e só na SEGUNDA vez, que é o
    # tipo de bug que custa uma tarde. Copiar ~150 entradas é microssegundos contra
    # os 26,7 s que o cache economiza.
    return ({mob: list(arqs) for mob, arqs in est["por_umid"].items()},
            set(est["so_audio"]))


def _assinatura_dos_arquivos(arquivos) -> tuple:
    """`(caminho, tamanho, mtime_ns)` de cada arquivo — mudou um, o índice cai.

    Arquivo que some entre a listagem e o `stat` entra com `(-1, -1)`: a próxima
    listagem já não o terá, e a assinatura muda de novo, que é o certo.
    """
    saida = []
    for q in arquivos:
        try:
            st = os.stat(q)
            saida.append((q, st.st_size, st.st_mtime_ns))
        except OSError:
            saida.append((q, -1, -1))
    return tuple(saida)


def esquecer_indice_da_midia() -> None:
    """Descarta o índice guardado. Existe para os testes — e para quem precisar
    forçar uma releitura sem reiniciar o sidecar."""
    _INDICE_DA_MIDIA.clear()


def resolver_mobs(mc, mob_ids: list[str], on_progress=None) -> dict:
    """MobIDs de masters → os ARQUIVOS deles em disco, e quais são SOM.

    Existe porque duas entradas do painel fazem a mesma pergunta e chegam por
    caminhos diferentes:

    - **as bins escolhidas** (`avid_selection`), que descobre os MobIDs
      perguntando o conteúdo de cada bin — uma chamada gRPC de ~500 ms por bin;
    - **o ARRASTO** de clipes de uma bin (`avid_mobs`), em que os MobIDs vêm de
      graça no payload do arrasto, sem chamada nenhuma.

    Daqui para frente o trabalho é idêntico, e é o que esta função faz:

    1. uma passada de `GetMobInfo` por master — dela saem o arquivo de origem, o
       volume da mídia gerenciada e a duração do master;
    2. o arquivo de cada master;
    3. **plano B** para quem não tem arquivo de origem (cartão devolvido, projeto
       que trocou de máquina): varre a mídia gerenciada casando pelo UMID, que é
       a mesma identidade que a bin usa.

    Devolve `{caminhos, colunas, so_audio, faltam, duracoes}` — `faltam` são os
    MobIDs que não se resolveram nem no plano B.

    `on_progress(fase, feito, total, mensagem)` recebe `"masters"` e `"varredura"`.

    ⚠️ **Preserva a ORDEM dos `mob_ids` pedidos.** Ela é a ordem em que o editor
    selecionou os clipes, e é ela que decide qual cartão vem primeiro na fonte.
    """
    aviso = on_progress or (lambda *a: None)

    # Um MobID repetido no pedido (o mesmo clipe marcado duas vezes) custaria uma
    # chamada gRPC a mais e entraria duplicado na fonte.
    unicos: list[str] = []
    vistos: set[str] = set()
    for m in mob_ids:
        if m and m not in vistos:
            vistos.add(m)
            unicos.append(m)

    log.info("Resolvendo %d master(s) (%d pedido(s))", len(unicos), len(mob_ids))

    t0 = time.perf_counter()
    colunas: dict[str, dict] = {}
    for n, mob in enumerate(unicos, 1):
        aviso("masters", n, len(unicos), f"Localizando clipe {n} de {len(unicos)}…")
        colunas[mob] = mc.colunas_do_master(mob)
    t_colunas = time.perf_counter() - t0
    # ⚠️ Esta fase é o GARGALO conhecido: 760 ms por master medidos, 38 s numa diária
    # de 50 (ver o roadmap interno). O número por master fica no log porque é ele que diz
    # se uma espera longa no Nexis é latência da API do MC ou lentidão da rede de
    # storage — que é a pergunta que o relato de campo não conseguia responder.
    log.info("Fase A (GetMobInfo): %d master(s) em %.2f s (%.0f ms cada)",
             len(unicos), t_colunas, 1000 * t_colunas / max(1, len(unicos)))

    t0 = time.perf_counter()
    caminhos: dict[str, list[str]] = {}
    faltam: list[str] = []
    for mob in unicos:
        p_arq = mc.arquivo_do_master(mob, colunas.get(mob))
        if p_arq:
            caminhos[mob] = [p_arq]
        else:
            faltam.append(mob)
    por_origem = len(caminhos)
    t_origem = time.perf_counter() - t0
    log.info("Fase B (arquivo de origem): %d de %d resolvido(s) em %.2f s; "
             "%d vão para a mídia gerenciada",
             por_origem, len(unicos), t_origem, len(faltam))

    so_audio: set[str] = set()
    t0 = time.perf_counter()
    if faltam:
        from .mcapi import mob_id_para_pyavb

        raizes = pastas_de_midia_do_avid(list(colunas.values()))
        if raizes:
            # ⚠️ Um evento a cada 10 arquivos, não a cada arquivo: a varredura passa
            # por centenas deles (394 no acervo de teste) e o pipe do Windows já
            # falhou sob rajada de escritas curtas (ver `_write_line` em `main.py`).
            def varrendo(feito, total, _nome=None):
                if feito % 10 and feito != total:
                    return
                aviso("varredura", feito, total, "Procurando na mídia do Avid…")

            aviso("varredura", 0, 0, "Procurando na mídia do Avid…")
            # ⭐ DIRIGIDA, não completa: o `Name` e o `Tracks` que já vieram no
            # `GetMobInfo` dizem o que procurar e QUANDO PARAR. Medido: 1984
            # `ffprobe` em 109,7 s viram 198 em ~11 s. Ver `varredura_dirigida`.
            #
            # Cacheado por sessão porque o arrasto é repetido — uma câmera por vez —
            # e sem isso cada arrasto pagaria a busca de novo.
            por_umid, so_audio = indice_da_midia_do_avid(
                raizes, alvos=alvos_de_busca(faltam, colunas), on_progress=varrendo)
            for mob in list(faltam):
                achado = por_umid.get(mob_id_para_pyavb(mob))
                if achado:
                    caminhos[mob] = achado
                    faltam.remove(mob)
        else:
            # ⛔ Sem raiz nenhuma não há onde procurar, e o plano B nem chega a
            # rodar — todos estes masters saem em `faltam`. É o desfecho do §1.3a
            # (ver `pastas_de_midia_do_avid`, que já registrou o motivo por volume).
            log.warning("Plano B não rodou: nenhuma pasta de mídia do Avid a varrer "
                        "— %d master(s) ficam sem arquivo", len(faltam))

    # ⚠️ A DURAÇÃO DO MASTER não é detalhe: o arquivo original costuma ser 1 frame
    # MAIS LONGO que o transcode do Avid, e um clipe que passa do fim do master faz
    # o Media Composer recusar a timeline inteira com `PMM_INSUFFICIENT_MEDIA` —
    # num diálogo modal que trava até a API. Sai das MESMAS colunas: custo zero.
    duracoes: dict[str, int] = {}
    for mob, col in colunas.items():
        bruto = (col.get("Frame Count Duration") or "").strip()
        if bruto.isdigit():
            for q in caminhos.get(mob, []):
                duracoes[q] = int(bruto)

    # ⭐⭐ **O RESUMO DE UMA LINHA.** É a linha que se procura primeiro num relato de
    # campo: quantos masters entraram, por onde cada um se resolveu, quantos ficaram
    # sem nada, e quanto custou cada fase. Tudo o que vem acima dela é o detalhe de
    # *como* — esta responde *o quê*, e responde sozinha.
    log.info("RESUMO %d master(s): %d por arquivo de origem, %d pela mídia gerenciada, "
             "%d SEM ARQUIVO · %d só de áudio · fases A=%.2fs B=%.2fs C=%.2fs",
             len(unicos), por_origem, len(caminhos) - por_origem, len(faltam),
             len(so_audio), t_colunas, t_origem, time.perf_counter() - t0)
    if faltam:
        # O nome, não o MobID: é o que aparece na bin e o que a pessoa vai conferir.
        nomes = [(colunas.get(m, {}).get("Name") or m) for m in faltam]
        log.warning("SEM ARQUIVO (%d): %s", len(faltam), ", ".join(nomes))

    return {"caminhos": caminhos, "colunas": colunas, "so_audio": so_audio,
            "faltam": faltam, "duracoes": duracoes, "ordem": unicos}


def e_som(mob_id: str, caminhos: dict[str, list[str]], so_audio: set[str]) -> bool:
    """Este master é SOM? Pela ESSÊNCIA quando a mídia é do Avid, pela extensão
    quando é arquivo original.

    ⚠️ A extensão sozinha não serve para mídia GERENCIADA: ela é toda `.mxf`, som
    inclusive. Uma bin `SOM DIRETO` de gravador de set saía rotulada como câmera —
    funcionava, mas com o nome errado na tela.
    """
    from .mcapi import mob_id_para_pyavb

    try:
        if mob_id_para_pyavb(mob_id) in so_audio:
            return True
    except Exception:
        pass
    arqs = caminhos.get(mob_id, [])
    return bool(arqs) and all(Path(q).suffix.lower() in EXTENSOES_DE_SOM for q in arqs)


#: Extensões de arquivo de SOM — usadas só quando a mídia NÃO é gerenciada pelo
#: Avid (aí a essência decide; ver `e_som`).
EXTENSOES_DE_SOM = {".wav", ".aif", ".aiff", ".mp3", ".m4a", ".bwf"}


def unidades_por_rotulo() -> dict[str, Path]:
    """`{rótulo em minúsculas: raiz}` das unidades montadas no Windows.

    Usa `GetVolumeInformationW` via `ctypes` — sem dependência nova e sem
    subprocesso (que no app empacotado ainda piscaria um console).

    `SetErrorMode` é obrigatório: sem ele, consultar um leitor de cartão VAZIO
    abre aquele diálogo modal "Insira um disco na unidade", e o sidecar
    congelaria esperando alguém clicar num aviso que ninguém vê.
    """
    import ctypes

    fora: dict[str, Path] = {}
    k32 = ctypes.windll.kernel32
    anterior = k32.SetErrorMode(0x0001)  # SEM_FAILCRITICALERRORS
    try:
        montadas = k32.GetLogicalDrives()  # bitmask: bit 0 = A:, bit 1 = B: …
        rotulo = ctypes.create_unicode_buffer(261)
        for i in range(26):
            if not montadas & (1 << i):
                continue
            raiz = f"{chr(ord('A') + i)}:\\"
            ok = k32.GetVolumeInformationW(
                ctypes.c_wchar_p(raiz), rotulo, 261, None, None, None, None, 0
            )
            if ok and rotulo.value.strip():
                fora.setdefault(rotulo.value.strip().casefold(), Path(raiz))
    finally:
        k32.SetErrorMode(anterior)
    return fora


#: `\\SERVIDOR\share` — dois separadores, host, separador, share. O resto do caminho
#: (se vier) é preservado: um workspace pode ser servidor+share+subpasta, e reduzir a
#: servidor+share transformaria dois storages diferentes no mesmo (medido: `P:` →
#: `\\servidor-ingest\ingest\projeto_exemplo`).
_UNC = re.compile(r"^[\\/]{2}([^\\/]+)[\\/]+([^\\/]+.*)$")

#: A mesma coisa entre parênteses, por analogia com `RÓTULO (D:)`: se uma versão do
#: MC escrever `projeto_exemplo (\\SERVIDOR-NEXIS\projeto_exemplo)`, o miolo é o que vale.
_UNC_ENTRE_PARENTESES = re.compile(r"\(\s*([\\/]{2}[^)]+?)\s*\)\s*$")


def _partes_unc(drive: str) -> tuple[str, list[str]] | None:
    """`(servidor, [share, …])` de uma coluna `Drive` UNC. `None` se não for UNC.

    ⚠️ **Devolve as PARTES, não um `Path`** — e isso não é preferência de estilo. Um
    `Path("\\\\\\\\srv\\\\share")` construído no macOS é um `PosixPath` cujo nome inteiro é a
    string com barras invertidas dentro; `.name` ali devolve a coisa errada, e no
    Windows o mesmo `Path` é um ANCHOR, cujo `.name` é vazio. Os dois erros são
    silenciosos e opostos. Quem sabe montar o caminho é quem sabe o sistema.

    Aceita barra normal porque o mesmo storage aparece com as duas grafias no corpus
    medido (`file://SERVIDOR-NEXIS/projeto_exemplo/…` no AAF real).
    """
    m = _UNC_ENTRE_PARENTESES.search(drive)
    bruto = (m.group(1) if m else drive).strip()
    m2 = _UNC.match(bruto)
    if m2 is None:
        return None
    partes = [p for p in m2.group(2).replace("\\", "/").split("/") if p]
    # ⛔ `..` numa coluna `Drive` não tem uso legítimo — e tem uso ILEGÍTIMO: a raiz
    # devolvida daqui vira alvo de `.is_dir()` e `iterdir()` em
    # `pastas_de_midia_do_avid`, então um `..` faz a varredura subir para fora do
    # share que o projeto nomeou. A coluna vem de um `.avb` que pode ter sido
    # autorado noutro lugar; ela é entrada, não configuração.
    if any(p == ".." for p in partes):
        log.warning("Coluna Drive «%s» tem '..' — recusada", drive)
        return None
    return (m2.group(1), partes) if partes else None


def raiz_do_drive(drive: str, sistema: str, unidades: dict[str, Path] | None = None) -> Path | None:
    """A coluna `Drive` de uma bin → a raiz do volume no disco. `None` se não der.

    ⭐ **NO WINDOWS A COLUNA VEM COMO `RÓTULO (LETRA:)`** — medido na bin real:

        Drive = 'MEU-VOLUME (D:)'      ← e NÃO 'D', nem 'MEU-VOLUME'

    O código antigo montava `f"{drive}:\\"` e produzia
    `MEU-VOLUME (D:):\\Avid MediaFiles`. Como `is_dir()` só dá `False`, a busca
    seguia em frente e o app dizia **"89 clipes não encontrados no disco"** com a
    mídia inteira ali. Falha silenciosa: nada levanta erro, e o sintoma culpa o
    disco.

    ⚠️ **A letra vem de graça entre parênteses — use-a.** Traduzir o rótulo
    consultando os volumes montados também funciona, mas é trabalho a mais e
    falha se dois volumes tiverem o mesmo nome. O parêntese é a resposta direta;
    a busca por rótulo fica como plano B, para o caso de uma versão do MC
    devolver só o nome.

    No macOS a coluna não tem letra (não existe letra de unidade) e o sistema
    **monta por nome**, então `/Volumes/<rótulo>` já é um caminho de verdade —
    por isso este bug não existe daquele lado.

    Aceitar uma letra crua (`D`, `D:`) cobre volume sem rótulo.
    """
    drive = (drive or "").strip()
    if not drive:
        return None

    # ⛔ UNC VEM ANTES DE TUDO — §1.3a do roadmap. `\\SERVIDOR-NEXIS\projeto_exemplo` não
    # tem rótulo nem letra a extrair, e as expressões abaixo o mutilariam: ele cairia
    # na busca por rótulo, não casaria com volume nenhum e devolveria `None` — o
    # master sumia da busca e o app dizia "clipes não encontrados no disco" com a
    # mídia inteira lá.
    #
    # ⭐ Que a mídia gerenciada de produção MORA em UNC é medido, não suposto:
    # `\\SERVIDOR-NEXIS\<projeto>\avid mediafiles\mxf\<estação>.<n>\` está em
    # a base de conhecimento interna §2.1
    # (`confirmado`, um ambiente de produção real). O que ainda NÃO se mediu é se a coluna `Drive`
    # do MC mostra o UNC ou o nome do workspace — por isso o caminho por rótulo
    # continua abaixo, intacto, e este ramo apenas acrescenta.
    unc = _partes_unc(drive)
    if unc is not None:
        servidor, partes = unc
        # No macOS o mesmo share é montado por NOME, em `/Volumes/<share>` — a UNC
        # não existe como caminho ali. Traduzir é mais útil que devolver nada, e o
        # chamador confere a existência de `Avid MediaFiles` de qualquer jeito.
        if sistema == "Darwin":
            return Path("/Volumes", partes[0])
        if sistema != "Windows":
            return None
        return Path("\\\\" + servidor, *partes)

    # `MEU-VOLUME (D:)` → rótulo `MEU-VOLUME`, letra `D`. O sufixo é do
    # Windows; tirá-lo também no macOS é inofensivo e evita depender do SO para
    # limpar a string.
    m = re.search(r"\(([A-Za-z]):\)\s*$", drive)
    letra = m.group(1) if m else None
    rotulo = re.sub(r"\s*\([A-Za-z]:\)\s*$", "", drive).strip()

    if sistema == "Darwin":
        if not rotulo:
            return None
        # Um RÓTULO de volume não tem separador dentro. Se tem, isto não é rótulo —
        # é caminho, e colar `/Volumes/` na frente produz lixo que existe menos ainda
        # que a string original. Absoluto passa como está; o resto não passa.
        if rotulo.startswith("/"):
            return Path(rotulo)
        if "/" in rotulo or "\\" in rotulo:
            return None
        return Path("/Volumes", rotulo)
    if sistema != "Windows":
        return None

    if letra:
        return Path(f"{letra.upper()}:\\")
    if re.fullmatch(r"[A-Za-z]:?[\\/]?", rotulo):
        return Path(f"{rotulo[0].upper()}:\\")
    if unidades is None:
        unidades = unidades_por_rotulo()
    return unidades.get(rotulo.casefold())


#: As ÚNICAS pastas de essência que o Media Composer enxerga dentro de uma
#: `Avid MediaFiles`. `UME` é bem menos usada que `MXF`, mas existe.
#:
#: ⛔⛔ **QUALQUER IRMÃ DELAS É MÍDIA ESTACIONADA, E VARRÊ-LA É BUG.** Renomear
#: `MXF` para `MXF-<projeto>` é como editores de Media Composer guardam o
#: material de um projeto para trabalhar noutro **no mesmo disco** sem misturar
#: mídia, render e import: a pasta renomeada fica invisível para o Avid, e volta
#: a valer quando é renomeada de volta para `MXF`.
#:
#: Ou seja, é uma pasta que o editor DELIBERADAMENTE pôs offline. Ler dela é
#: entregar mídia que o Media Composer não enxerga — e pior, em silêncio: os
#: MobIDs são os mesmos, então o clipe "resolve" e ninguém percebe que veio da
#: cópia errada.
#:
#: Medido em 2026-08-22 (relatado pelo autor, editor de MC): num acervo de teste,
#: `MXF-projetoexemplo-tbm` guardava **738 dos 2327 arquivos** — 32% do que
#: varríamos era material aposentado, e o sync desta sessão usou justamente essa
#: cópia.
PASTAS_DE_ESSENCIA = ("MXF", "UME")


def _subpasta(raiz: Path, nome: str) -> Path | None:
    """`raiz/nome` sem depender da caixa. `None` se não houver.

    ⚠️ A caixa varia no mundo real: o disco do autor tem `Avid Mediafiles` (com
    `f` minúsculo) e a Avid documenta `Avid MediaFiles`. No Windows e no exFAT
    isso não dói, porque o sistema de arquivos ignora a caixa — **no macOS com
    volume sensível a maiúsculas, dói**, e o sintoma seria a mídia inteira
    "não encontrada". Comparar por `casefold` custa uma listagem e fecha a porta.
    """
    direto = raiz / nome
    if direto.is_dir():
        return direto
    alvo = nome.casefold()
    try:
        for q in raiz.iterdir():
            if q.name.casefold() == alvo and q.is_dir():
                return q
    except OSError:
        pass
    return None


def pastas_de_midia_do_avid(colunas_por_master: list[dict]) -> list[str]:
    """Onde procurar a mídia gerenciada, a partir da coluna `Drive` das bins.

    O Avid grava em `<volume>/Avid MediaFiles/MXF` (ou `/UME`), e a coluna `Drive`
    diz o volume de cada master — pelo RÓTULO, ver `raiz_do_drive`. A mídia local
    do sistema fica fora da raiz do volume e é tratada à parte pelo chamador.

    ⛔ **Devolve as pastas de ESSÊNCIA, nunca a `Avid MediaFiles` inteira** — ver
    `PASTAS_DE_ESSENCIA` para o porquê, que não é de performance: é de correção.
    """
    import platform

    sistema = platform.system()
    # Uma varredura só de unidades para todos os masters: a lista costuma trazer
    # dezenas de clipes do MESMO volume.
    unidades = unidades_por_rotulo() if sistema == "Windows" else {}

    fora: list[str] = []
    # ⛔ O registro é por `Drive` DISTINTO, não por master: uma diária traz dezenas
    # de clipes do mesmo volume, e uma linha por clipe afogaria o log justamente no
    # comando em que ele mais importa. Distinto é o que interessa — a pergunta é
    # "que volumes o Avid nomeou", não "quantas vezes".
    vistos: dict[str, str] = {}
    for col in colunas_por_master:
        bruto = col.get("Drive") or ""
        raiz = raiz_do_drive(bruto, sistema, unidades)
        if bruto not in vistos:
            vistos[bruto] = "" if raiz is None else str(raiz)
        if raiz is None:
            continue
        base = _subpasta(raiz, "Avid MediaFiles")
        if base is None:
            if vistos.get(bruto) == str(raiz):
                vistos[bruto] = f"{raiz} (sem 'Avid MediaFiles')"
            continue
        for nome in PASTAS_DE_ESSENCIA:
            alvo = _subpasta(base, nome)
            if alvo is not None and str(alvo) not in fora:
                fora.append(str(alvo))

    for bruto, virou in vistos.items():
        if virou:
            log.info("Drive «%s» -> %s", bruto, virou)
        else:
            # ⛔ ESTA É A LINHA DO §1.3a DO ROADMAP. Storage sem letra de unidade
            # (`\\SERVIDOR\projeto`, um Nexis) cai aqui, e ANTES caía calada: o
            # master era pulado, a busca não acontecia, e o app dizia que a mídia não
            # estava no disco — com a mídia inteira lá. O motivo tem de estar escrito.
            log.warning(
                "Drive «%s» NÃO virou raiz de volume (%s) — os masters deste volume "
                "ficam de fora da busca de mídia gerenciada", bruto, sistema)
    log.info("Mídia gerenciada: %d pasta(s) de essência a varrer: %s",
             len(fora), fora or "(nenhuma)")
    return fora


def resolver(paths: list[str], mc=None,
             mob_ids: dict[str, str] | None = None,
             mob_lengths: dict[str, int] | None = None
             ) -> tuple[dict[str, str], dict[str, int], list[str]]:
    """`(master_ids, master_lengths, nao_resolvidos)` para os caminhos dados.

    `master_ids` é `{nome do arquivo: mob_id do pyavb}` — a chave é o nome do
    arquivo porque é isso que o adapter põe em `clip_name`.

    `mc` é uma conexão com o Media Composer, opcional: sem ela, só a mídia OP-Atom
    é resolvida. **Os não resolvidos são DEVOLVIDOS, nunca engolidos** — um clipe
    sem master viraria um buraco na timeline, e quem chama tem de poder dizer isso
    à pessoa antes de escrever qualquer coisa.
    """
    from media import opatom

    from .mcapi import mob_id_para_pyavb

    ids: dict[str, str] = {}
    duracoes: dict[str, int] = {}
    faltam: list[str] = []

    # ── 0. O mapa que veio da SELEÇÃO ────────────────────────────────────────
    #
    # ⭐ Quando o material entrou pelo botão "Adicionar seleção", o Órbita JÁ
    # perguntou ao Media Composer qual master é cada arquivo. Reaproveitar essa
    # resposta evita a busca — e a busca tem um efeito colateral visível: ela ABRE
    # cada bin na tela do editor. Ao enviar um sync, o Avid ficava coberto de bins
    # que ninguém pediu.
    dados = mob_ids or {}
    tamanhos = mob_lengths or {}
    for p in paths:
        cru = dados.get(p) or dados.get(Path(p).name)
        if cru:
            try:
                h = mob_id_para_pyavb(cru)
            except Exception:
                continue
            ids[Path(p).name] = h
            L = tamanhos.get(p) or tamanhos.get(Path(p).name)
            if L:
                duracoes[h] = int(L)

    # ── 1. Mídia gerenciada: o arquivo já diz quem é o master ────────────────
    restantes: list[str] = []
    for p in paths:
        nome = Path(p).name
        if nome in ids:
            continue
        if Path(p).suffix.lower() == ".mxf":
            doc = opatom.probe_file(p)
            lido = opatom.parse_probe(doc, p) if doc is not None else "sem probe"
            if not isinstance(lido, str) and lido.clip_umid:
                h = mob_id_para_pyavb(lido.clip_umid)
                ids[nome] = h
                if lido.duration_frames:
                    duracoes[h] = lido.duration_frames
                continue
        restantes.append(p)

    if not restantes:
        return ids, duracoes, faltam

    # ── 2. O resto, pelo nome, perguntando ao Media Composer ─────────────────
    if mc is None:
        return ids, duracoes, [Path(p).name for p in restantes]

    # ⚠️ AS BINS ABERTAS PRIMEIRO, e as outras só se sobrar quem procurar.
    #
    # Varrer o projeto inteiro tem um efeito colateral VISÍVEL: `OpenBin` abre a
    # bin na tela do editor. Ao enviar um sync, o Media Composer ficava coberto de
    # bins que ninguém pediu — inclusive as de sequência, que não têm master nenhum.
    # Como o material que se acabou de sincronizar veio das bins que o editor tem
    # abertas, elas quase sempre bastam.
    def procurar(caminhos, alvos):
        """Uma bin POR VEZ, parando assim que não falta mais ninguém.

        ⚠️ Buscar bin a bin em vez de varrer tudo de uma vez não é otimização de
        velocidade: cada bin visitada pode ser ABERTA na tela do editor, e parar
        cedo é a diferença entre abrir uma e abrir o projeto inteiro.
        """
        for caminho in caminhos:
            if not alvos:
                return []
            por_base: dict[str, object] = {}
            for m in mc.masters([caminho]):
                por_base.setdefault(nome_base(m.name), m)
            sobraram = []
            for q in alvos:
                m = por_base.get(nome_base(Path(q).name))
                if m is None:
                    sobraram.append(q)
                    continue
                ids[Path(q).name] = m.mob_id
                if m.length_frames:
                    duracoes[m.mob_id] = m.length_frames
            alvos = sobraram
        return alvos

    todas = mc.bins()
    # Só ORDENA a busca (bins abertas primeiro, para não abrir bin fechada na
    # tela do editor à toa). Num MC sem `GetListOfWindows` perde-se a ordem
    # preferencial, não a busca: `prioritarias` fica vazia e `resto` vira tudo.
    # Ver `McApiNaoImplementado`; o mesmo cuidado já existia em
    # `_completar_duracoes` logo abaixo.
    try:
        abertas = set(mc.bins_abertas())
    except McApiNaoImplementado:
        abertas = set()
    prioritarias = [b for b in todas if Path(b).stem in abertas]
    resto = [b for b in todas if b not in prioritarias]

    sobraram = procurar(prioritarias, restantes)
    sobraram = procurar(resto, sobraram)
    faltam.extend(Path(q).name for q in sobraram)
    _completar_duracoes(ids, duracoes, mc)
    return ids, duracoes, faltam


def _completar_duracoes(ids: dict[str, str], duracoes: dict[str, int], mc) -> None:
    """⚠️ NENHUM master pode ficar sem duração — é o que alimenta o clamp.

    Um clipe que referencia além do fim do master faz o Media Composer recusar a
    timeline inteira com `PMM_INSUFFICIENT_MEDIA`, num diálogo modal que trava até
    a API. E o caso é comum, não exótico: o arquivo ORIGINAL costuma ser 1 frame
    mais longo que o transcode do Avid.

    Custa um `GetMobInfo` (~500 ms) por master que ainda não tem duração — e vale
    cada um: o preço de não pagar é uma timeline que não abre.
    """
    if mc is None:
        return
    faltando = {h for h in ids.values() if h not in duracoes}
    if not faltando:
        return
    # ⚠️ AS BINS ABERTAS PRIMEIRO, pelo mesmo motivo da busca de masters: visitar
    # uma bin fechada a ABRE na tela do editor. Esta rede existe para casos de
    # borda (um master de ÁUDIO OP-Atom não traz duração no arquivo), e não pode
    # cobrar o preço de encher a tela de quem caiu neles.
    try:
        abertas = set(mc.bins_abertas())
    except Exception:
        abertas = set()
    todas = mc.bins()
    ordem = ([b for b in todas if Path(b).stem in abertas]
             + [b for b in todas if Path(b).stem not in abertas])
    for caminho in ordem:
        if not faltando:
            return
        try:
            for m in mc.masters([caminho]):
                if m.mob_id in faltando and m.length_frames:
                    duracoes[m.mob_id] = m.length_frames
                    faltando.discard(m.mob_id)
        except Exception:
            continue
