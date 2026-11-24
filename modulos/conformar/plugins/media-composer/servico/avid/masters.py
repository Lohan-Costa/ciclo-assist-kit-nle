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

import re
from pathlib import Path

# Sufixos que o Avid acrescenta ao NOME do clipe ao importar/transcodar. Não
# existem no arquivo original: `X.mov` na bin vira `X.new.01`.
_SUFIXO_AVID = re.compile(r"\.(new|sync|cds|grp|sub|copy|exported|cpy)\.\d{1,4}$", re.I)


def nome_base(nome: str) -> str:
    """Tira os sufixos do Avid e a extensão de mídia — o que sobra é o que os dois
    lados têm em comum.

        '20240531_PANA2774.new.01'  → '20240531_pana2774'
        '20240531_PANA2774.mov'     → '20240531_pana2774'
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

    res = opatom.scan(raizes, on_progress=on_progress)
    fora: dict[str, list[str]] = {}
    for c in res.clips:
        if not c.umid:
            continue
        try:
            fora[mob_id_para_pyavb(c.umid)] = c.paths
        except Exception:
            continue          # UMID que não converte não derruba a varredura
    return fora


def pastas_de_midia_do_avid(colunas_por_master: list[dict]) -> list[str]:
    """Onde procurar a mídia gerenciada, a partir da coluna `Drive` das bins.

    O Avid grava em `<volume>/Avid MediaFiles`, e a coluna `Drive` diz o volume de
    cada master. A mídia local do sistema fica **fora** da raiz do volume e é
    tratada à parte pelo chamador.

    ⚠️ **A coluna `Drive` não é uma letra de unidade.** No Windows o Media Composer
    devolve `'SSD (D:)'` — rótulo E letra —, e montar `f"{drive}:\\\\"` a
    partir disso produz um caminho que nunca existe, sem erro nenhum: o resultado é
    o app relatar *"clipes não encontrados"* com a mídia inteira no disco. A
    tradução mora em `plataforma.raiz_do_volume`, com as três formas aceitas.
    """
    import plataforma

    fora: list[str] = []
    for col in colunas_por_master:
        raiz = plataforma.raiz_do_volume((col.get("Drive") or "").strip())
        if raiz is None:
            continue
        alvo = raiz / "Avid MediaFiles"
        if alvo.is_dir() and str(alvo) not in fora:
            fora.append(str(alvo))
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

    # `bins_abertas()` devolve `None` quando o MC não sabe dizer (o rpc não existe no
    # 25.6). Aqui isso só custa a ORDEM da busca — nunca o resultado —, porque as
    # "prioritárias" são só as primeiras da fila, não um filtro. Ver `McApiNaoImplementado`.
    todas = mc.bins()
    abertas = set(mc.bins_abertas() or ())
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
        abertas = set(mc.bins_abertas() or ())
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
