"""O que o PROJETO já linkou (AMA), lido das bins no disco — para o relink REAPROVEITAR em vez de linkar de novo.

Decisão do autor (2026-10-13), sobre medição: o `LinkFile` do Media Composer fica ~10× mais lento (mediana 0,34 →
3,09 s por arquivo) quando o projeto aberto JÁ tem master AMA do mesmo arquivo, e cada rodada deixava uma cópia a mais
(banco, `plugins/avid-panel-sdk/windows.md` §14). Então, antes de linkar, o relink pergunta aqui se aquele arquivo já
tem master no projeto e, se tiver e estiver online, copia o master (mesmo MobID) em vez de chamar o `LinkFile`.

⭐ A fonte da verdade são as BINS, não um cadastro nosso: um cadastro mentiria quando o editor apaga um clipe, linka à
mão ou recebe bins de outra pessoa. O cache abaixo só evita reler a bin que não mudou (mtime + tamanho).

Custo medido (2026-10-13, Windows, SSD interno): 15 bins / 12,4 MB em 0,81 s; ~0,07 s por MB de bin.

Como se lê (banco, `protocolos/avb/fontes.md`): master com o atributo `_IMPORTED_AMA`; o arquivo no locator da fonte
(`WinFileLocator.path_utf8` no Windows — por isso `segmentos.caminho_do_locator`, nunca `nle_model.locator_path`, que só
lê `path_posix`); online = o arquivo existe E a data dele bate com `_AMA_FILE_DATE_TIME`.
"""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("delapraca.ama_do_projeto")

_VERSAO_DO_CACHE = 1


def chave(caminho: str) -> str:
    """O caminho de um arquivo como chave de comparação (caixa e barras do sistema)."""
    return os.path.normcase(os.path.normpath(caminho))


def da_bin(caminho_bin: str) -> dict[str, list[dict]]:
    """`{chave do arquivo: [{mob_id, nome, caminho, data}]}` dos masters AMA de UMA bin."""
    from avb_export import nle_model as NM
    from avb_export.reader import topen

    from .masters import _atributos
    from .segmentos import caminho_do_locator

    achados: dict[str, list[dict]] = {}
    with topen(caminho_bin) as f:
        indice = {NM._mobid(x.mob_id): x for x in f.content.mobs}
        for m in f.content.mastermobs():
            attrs = _atributos(m)
            if not attrs or "_IMPORTED_AMA" not in attrs:
                continue
            fontes = NM.reachable_sources(m, indice)
            caminho = next((c for c in (caminho_do_locator(sm) for sm in fontes) if c), "")
            if not caminho:
                continue
            data = next((d for d in (NM._attr(sm, "_AMA_FILE_DATE_TIME") for sm in fontes) if d is not None), None)
            achados.setdefault(chave(caminho), []).append({
                "mob_id": str(m.mob_id), "nome": m.name or "", "caminho": caminho,
                "data": int(data) if data is not None else None})
    return achados


def varrer(pasta_projeto: str, arquivo_cache: str | None = None, ignorar: tuple[str, ...] = ()) -> dict[str, list[dict]]:
    """Os masters AMA de TODAS as bins do projeto: `{chave do arquivo: [{mob_id, nome, caminho, data, bin}]}`.

    `arquivo_cache`: JSON onde guardar o que cada bin tinha (relê só a bin cujo mtime/tamanho mudou). `ignorar`: bins
    (caminho completo) a deixar de fora. Bin ilegível não derruba a varredura: registra e segue — o pior caso é
    linkar de novo, como antes.
    """
    cache: dict = {}
    if arquivo_cache and os.path.exists(arquivo_cache):
        try:
            with open(arquivo_cache, encoding="utf-8") as fh:
                dados = json.load(fh)
            if dados.get("versao") == _VERSAO_DO_CACHE:
                cache = dados.get("bins") or {}
        except (OSError, ValueError) as e:
            log.info("cache da varredura ilegível (%s) — relendo tudo", e)
    fora = {chave(x) for x in ignorar}
    novo_cache: dict = {}
    resultado: dict[str, list[dict]] = {}
    lidas = 0
    for raiz, _pastas, nomes in os.walk(pasta_projeto):
        for nome in nomes:
            if not nome.lower().endswith(".avb") or nome.startswith("._"):      # a sombra do exFAT não é bin
                continue
            b = os.path.join(raiz, nome)
            if chave(b) in fora:
                continue
            try:
                st = os.stat(b)
            except OSError:
                continue
            assinatura = [st.st_mtime_ns, st.st_size]
            guardado = cache.get(b)
            if guardado and guardado.get("assinatura") == assinatura:
                itens = guardado.get("itens") or {}
            else:
                try:
                    itens = da_bin(b)
                    lidas += 1
                except Exception as e:  # noqa: BLE001 — uma bin ruim não impede reaproveitar as outras
                    log.warning("não consegui ler %s (%s) — fica de fora da varredura", nome, e)
                    continue
            novo_cache[b] = {"assinatura": assinatura, "itens": itens}
            for k, lista in itens.items():
                resultado.setdefault(k, []).extend(dict(x, bin=b) for x in lista)
    if arquivo_cache:
        try:
            os.makedirs(os.path.dirname(arquivo_cache) or ".", exist_ok=True)
            tmp = arquivo_cache + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump({"versao": _VERSAO_DO_CACHE, "bins": novo_cache}, fh)
            os.replace(tmp, arquivo_cache)
        except OSError as e:
            log.info("não consegui gravar o cache da varredura (%s)", e)
    log.info("varredura do projeto: %d bins (%d relidas), %d arquivos com master AMA",
             len(novo_cache), lidas, len(resultado))
    return resultado


def online(item: dict) -> bool:
    """O master ainda acha o arquivo: ele existe e a data bate com a que o Avid gravou (as duas condições do AMA)."""
    caminho = item.get("caminho") or ""
    if not caminho or not os.path.exists(caminho):
        return False
    if item.get("data") is None:
        return False                      # sem a data o MC mostra offline (banco, nle_model.online_verdict)
    try:
        return int(os.path.getmtime(caminho)) == int(item["data"])
    except OSError:
        return False


def reaproveitavel(indice: dict[str, list[dict]], caminho: str) -> dict | None:
    """O master que o projeto já tem para `caminho`, ONLINE — ou None (aí o relink linka como sempre)."""
    for item in indice.get(chave(caminho)) or []:
        if online(item):
            return item
    return None
