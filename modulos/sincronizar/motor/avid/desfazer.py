"""
avid/desfazer.py — o registro do que foi renomeado, e o caminho de volta.

## Por que ele existe, e por que FORA da bin

O Assist anterior tentou guardar o nome antigo numa coluna custom da bin
(`CreateCustomColumn`) e removeu a tentativa inteira, por dois defeitos medidos em
2026-08-28:

1. **`CreateCustomColumn` cria uma coluna NOVA a cada chamada**, sem reaproveitar a
   que já existe — nove colunas `GA Nome Original` lado a lado na bin de teste, uma
   por aplicação. A bin do editor virava um pente, e o MCAPI **não tem rpc de apagar
   coluna**: quem criou por engano não desfaz pelo app.
2. **Ela guardava o nome ANTERIOR, não o original.** Renomeando duas vezes, o que a
   coluna promete no nome não é o que ela entrega.

Decisão do autor em 2026-09-04: o desfazer mora **do lado do Órbita**. A bin do
editor não ganha coluna nenhuma — e é isso que este módulo protege.

## O que ele NÃO consegue garantir, e a tela precisa dizer

- **Não é o Undo do Media Composer.** Repõe o nome; não desfaz o que o editor fez no
  meio.
- **É local à máquina e ao perfil.** `%APPDATA%` não viaja com o projeto — de
  propósito: a alternativa era escrever no projeto de terceiro, que é justamente o
  que foi rejeitado. Um lote aplicado no notebook não se desfaz na estação.
- **Não sobrevive a limpar a pasta de dados** do app.
- **Não prova o disco.** Herda o `confirmado` do `aplicar`: reverteu na sessão, não
  necessariamente na `.avb`.
- **Não desfaz o que falhou** no lote original — o que não foi aplicado não volta.
- **Não protege contra o editor ter renomeado por cima.** Protege contra
  *sobrescrever* isso, que é diferente e é o que dá para prometer.
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import appsettings as app_settings
import registro

log = registro.log(__name__)

#: Quantos lotes ficam guardados. Além disso, o mais velho sai.
#:
#: ⚠️ Não é um número técnico: é quanto histórico vale a pena carregar num arquivo
#: por lote. Vinte cobre uma semana de trabalho pesado e mantém a varredura de
#: `nome_original` (linear sobre os lotes) em milissegundos.
RETENCAO = 20

#: A versão do formato. Um lote gravado por uma versão futura é IGNORADO na leitura,
#: nunca interpretado pela metade — meio-desfazer é pior que não desfazer.
VERSAO = 1


def pasta() -> Path:
    return app_settings.rename_journal_dir()


def _arquivos() -> list[Path]:
    """Os lotes, do mais NOVO para o mais velho. Nunca levanta."""
    try:
        return sorted(pasta().glob("*.json"), reverse=True)
    except OSError:
        return []


def _ler(caminho: Path) -> dict | None:
    """Um lote, ou `None` se ilegível.

    ⚠️ Um journal corrompido não pode derrubar a aba: perder o histórico é ruim,
    mas mostrar uma tela de erro no lugar do trabalho é pior. Mesma postura de
    `appsettings.load`.
    """
    try:
        d = json.loads(caminho.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        log.info("lote de renomeação ilegível (%s): %s", caminho.name, e)
        return None
    if not isinstance(d, dict) or d.get("versao") != VERSAO:
        return None
    return d


def _da_nle(d: dict, nle: str) -> bool:
    """O lote é desta NLE? Lote sem o campo é do Avid — é anterior ao Premiere."""
    return str(d.get("nle") or "avid") == nle


def historico(limite: int = RETENCAO, nle: str = "avid") -> list[dict]:
    """O resumo dos lotes, do mais novo para o mais velho — sem os itens."""
    fora = []
    for caminho in _arquivos():
        if len(fora) >= limite:
            break
        d = _ler(caminho)
        if not d or not _da_nle(d, nle):
            continue
        fora.append({
            "id": d.get("id", ""),
            "quando": d.get("quando", ""),
            "projeto": d.get("projeto", ""),
            "padrao": d.get("padrao", ""),
            "bins": d.get("bins", []),
            "itens": len(d.get("itens") or []),
            "aplicados": d.get("aplicados", 0),
            "confirmado": bool(d.get("confirmado")),
            "revertido": bool(d.get("revertido")),
        })
    return fora


def lote(id_do_lote: str | None = None, nle: str = "avid",
         projeto: str | None = None) -> dict | None:
    """Um lote pelo id — ou o mais recente AINDA NÃO REVERTIDO, se `id` for `None`.

    ⚠️ `nle` filtra SEMPRE: o journal é um só para o Avid e o Premiere, e o "desfazer"
    de um painel nunca pode pegar o lote do outro (os ids dos itens nem são do mesmo
    tipo). `projeto`, quando dado, filtra também — o Premiere só desfaz no projeto
    que está aberto.

    ⚠️ "Ainda não revertido" e não "o último": desfazer duas vezes seguidas sem isto
    tentaria reverter o mesmo lote de novo, e o segundo desfazer não faria nada
    enquanto o lote anterior — o que o editor de fato quer — ficaria parado atrás.
    """
    for caminho in _arquivos():
        d = _ler(caminho)
        if not d or not _da_nle(d, nle):
            continue
        if projeto is not None and str(d.get("projeto") or "") != projeto:
            continue
        if id_do_lote is None:
            if not d.get("revertido"):
                return d
        elif d.get("id") == id_do_lote:
            return d
    return None


def _nome_original_conhecido(mob_id: str) -> str | None:
    """O nome ORIGINAL de um mob, procurado do lote mais velho para o mais novo.

    ⭐⭐ É isto que separa *desfazer o último lote* de *voltar ao nome original* —
    e é o conserto do defeito nº 2 da coluna `GA Nome Original`, que guardava o
    nome ANTERIOR e prometia o original.
    """
    for caminho in reversed(_arquivos()):
        d = _ler(caminho)
        if not d:
            continue
        for item in d.get("itens") or []:
            if item.get("mob_id") == mob_id and item.get("nome_original"):
                return str(item["nome_original"])
    return None


def gravar(*, id_do_lote: str, projeto: str, padrao: str, mc_info: dict,
           itens: list[dict], nle: str = "avid") -> Path:
    """Grava o lote e devolve o caminho. **Levanta** se não conseguir.

    ⚠️⚠️ **Levantar aqui é o ponto.** Quem chama grava ANTES de tocar na bin e
    recusa o trabalho se isto falhar: renomear sem poder desfazer, tendo prometido
    desfazer, é pior que não renomear.

    Cada item entra com `nome_original` **e** `nome_antes`, separados. Na segunda
    renomeação do mesmo mob, `nome_antes` é o nome intermediário e `nome_original` é
    copiado do lote mais antigo que conhece aquele mob.
    """
    completos = []
    for i in itens:
        mob = str(i.get("mob_id") or "")
        antes = str(i.get("nome_atual") or "")
        completos.append({
            "mob_id": mob,
            "bin": str(i.get("bin") or ""),
            "tipos": list(i.get("tipos") or []),
            "nome_original": _nome_original_conhecido(mob) or antes,
            "nome_antes": antes,
            "nome_depois": str(i.get("nome_novo") or ""),
        })

    d = {
        "id": id_do_lote,
        "versao": VERSAO,
        "nle": nle,
        "quando": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "projeto": projeto,
        "mc": dict(mc_info or {}),
        "padrao": padrao,
        "bins": sorted({i["bin"] for i in completos if i["bin"]}),
        "itens": completos,
        "aplicados": 0,
        "falhas": [],
        "confirmado": False,
        "revertido": False,
    }

    alvo = pasta() / f"{id_do_lote}.json"
    alvo.parent.mkdir(parents=True, exist_ok=True)
    # Escrita atômica, como `appsettings.save`: um `.part` que vira o arquivo final
    # de uma vez. Um journal escrito pela metade seria pior que nenhum.
    parcial = alvo.with_suffix(".part")
    parcial.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    parcial.replace(alvo)
    _podar()
    return alvo


def atualizar(id_do_lote: str, **campos) -> None:
    """Grava o resultado sobre o lote (aplicados, falhas, confirmado, revertido).

    ⚠️ Nunca levanta: o trabalho JÁ aconteceu quando isto roda, e falhar aqui não
    pode transformar um renomeamento bem-sucedido em erro na tela.
    """
    alvo = pasta() / f"{id_do_lote}.json"
    d = _ler(alvo)
    if not d:
        return
    d.update(campos)
    try:
        parcial = alvo.with_suffix(".part")
        parcial.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
        parcial.replace(alvo)
    except OSError as e:
        log.warning("não deu para atualizar o lote %s: %s", id_do_lote, e)


def _podar() -> None:
    """Mantém os `RETENCAO` mais recentes.

    ⚠️⚠️ **A poda PROPAGA os `nome_original` órfãos.** Antes de apagar o lote mais
    velho, os originais que só ele conhecia são copiados para o lote retido mais
    antigo que menciona o mesmo mob. Sem isso, podar apagaria em silêncio a única
    cópia de um nome original — e o "voltar ao original" passaria a mentir.
    """
    arquivos = _arquivos()
    if len(arquivos) <= RETENCAO:
        return

    sobrando = arquivos[:RETENCAO]
    saindo = arquivos[RETENCAO:]

    # O lote retido mais ANTIGO é quem herda: ele é o próximo a ser podado, e o
    # próximo herdeiro depois dele.
    herdeiro_caminho = sobrando[-1] if sobrando else None
    herdeiro = _ler(herdeiro_caminho) if herdeiro_caminho else None

    if herdeiro:
        conhecidos = {i.get("mob_id"): i for i in herdeiro.get("itens") or []}
        mudou = False
        for caminho in saindo:
            d = _ler(caminho)
            if not d:
                continue
            for item in d.get("itens") or []:
                mob = item.get("mob_id")
                if mob and mob in conhecidos and item.get("nome_original"):
                    # O do lote mais velho é o mais original dos dois.
                    conhecidos[mob]["nome_original"] = item["nome_original"]
                    mudou = True
        if mudou:
            try:
                parcial = herdeiro_caminho.with_suffix(".part")
                parcial.write_text(json.dumps(herdeiro, ensure_ascii=False, indent=2),
                                   encoding="utf-8")
                parcial.replace(herdeiro_caminho)
            except OSError as e:
                log.warning("não deu para propagar os nomes originais: %s", e)

    for caminho in saindo:
        try:
            caminho.unlink()
        except OSError:
            pass


def plano_de_volta(d: dict) -> list[dict]:
    """O plano invertido: `[{mob_id, bin, nome_atual, nome_novo, tipos}]`.

    `nome_atual` é o que o lote escreveu (`nome_depois`) e `nome_novo` é para onde
    se volta: `nome_antes`.

    ⚠️ **Não há variante "ao original" aqui, e a ausência é decisão.** Ela existiu,
    com o escopo do LOTE, e isso não é o que a mão de quem usa espera: renomear
    150, trazer 5 e pedir a volta devolvia os 150. Voltar a nomes específicos é o
    campo `%nome_original`, cujo escopo é o da tela.

    ⚠️⚠️ **Aqui o plano vem de NOMES LITERAIS, não de um padrão — e esta é a
    exceção declarada ao contrato "o aplicar recebe só o padrão".** Ela se justifica
    porque a lista **não vem do cliente**: vem de um arquivo que o próprio sidecar
    escreveu, no diretório de dados do app. O painel manda um `undo_id` e nada mais.
    """
    fora = []
    for i in d.get("itens") or []:
        fora.append({
            "mob_id": i.get("mob_id"),
            "bin": i.get("bin", ""),
            "tipos": list(i.get("tipos") or []),
            "nome_atual": i.get("nome_depois", ""),
            "nome_novo": i.get("nome_antes", ""),
        })
    return fora


def originais_de(mob_ids) -> dict[str, str]:
    """`{mob_id: nome_original}` para os mobs pedidos, do histórico inteiro.

    ⭐⭐ **Escopo de CLIPE, não de lote — e a distinção veio do uso.** O autor
    renomeou 150 itens, depois trouxe 5 para a tela e pediu "voltar ao nome
    original": voltaram os 150. Estava certo do ponto de vista do journal (o
    lote era aquele) e errado do ponto de vista de quem usa — *voltar ao
    original* é uma coisa que se faz com **estes clipes**, enquanto *desfazer o
    lote* é uma coisa que se faz com **aquela operação**.

    ⚠️ Varre do lote mais VELHO para o mais novo e para no primeiro que conhece
    o mob: o original é o primeiro nome que vimos, não o mais recente.

    ⚠️ Mob sem histórico nenhum simplesmente não aparece no resultado — nunca se
    inventa um "original" para quem este app nunca renomeou.
    """
    querido = {str(m) for m in (mob_ids or []) if m}
    fora: dict[str, str] = {}
    if not querido:
        return fora
    for caminho in reversed(_arquivos()):
        d = _ler(caminho)
        if not d:
            continue
        for item in d.get("itens") or []:
            mob = item.get("mob_id")
            if mob in querido and mob not in fora and item.get("nome_original"):
                fora[mob] = str(item["nome_original"])
        if len(fora) == len(querido):
            break
    return fora
