"""Garantir que um MASTER está analisado — o caminho que a ferramenta e a aba dividem.

Até a aba Vetores existir, analisar era uma coisa só: o modelo chamava `transcrever`, a
ferramenta resolvia o take no Media Composer e processava. Agora a mesma análise começa
por dois lados — o turno e a fila de fundo —, e o que os dois têm em comum é exatamente o
que importa:

> dado o MASTER e os arquivos dele, deixar o resultado no cache com a assinatura da
> receita de hoje.

⛔⛔ **Uma conta só, e ela mora aqui.** Se a aba tivesse a própria cópia do "mixar, ouvir,
guardar", as duas divergiriam na primeira mudança de receita — e o modo de falha seria o
pior possível: o cache pareceria pronto para um lado e velho para o outro, sem erro
nenhum. É o mesmo defeito que `cache.raiz()` documenta, com outro nome.

⭐ **E é aqui que o cache do produto vira trabalho adiantado.** A transcrição é do master
inteiro, em tempo do master: transcrever pela aba, no fundo, deixa `transcrever` pronto
para qualquer take daquela mídia — masterclipe, subclipe, ou groupclipe criado depois.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

from . import alinhamento as _alin
from . import asr as _asr
from . import audio as _audio
from . import cache as _cache
from . import canais as _canais
from . import estagios as _estagios
from . import falantes as _falantes
from . import voz as _voz

log = logging.getLogger("cicloassist.midia.analise")

#: `aviso(o_que, fracao, trecho)` — a mesma forma de `turno.avisar()`, para que a
#: ferramenta possa passar o relator do turno sem embrulhar nada.
Aviso = Callable[[str, float | None, str], None]


class AnaliseFalhou(RuntimeError):
    """O que impediu a análise, em português, para ir direto à tela ou ao modelo."""


def _nada(o_que: str, fracao: float | None, trecho: str) -> None:
    return None


def transcrever_master(
    midia: _cache.Midia,
    arquivos: list[str],
    nome: str = "",
    aviso: Aviso | None = None,
    forcar: bool = False,
    trilhas: list | None = None,
    fonte_dos_nomes: str = "",
) -> dict[str, Any]:
    """Deixa a transcrição deste master no cache, e devolve as falas (e quem fala cada uma: `falantes`).

    `trilhas` — os nomes dos canais (`midia.canais.Trilha`), de quem os conhece (a bin do take); `None` = procurar
    no próprio arquivo (iXML).

    `arquivos` são os OP-Atom de **áudio** do master — só eles: uma track de vídeo no
    `amix` faz o ffmpeg falhar inteiro.

    `forcar` refaz mesmo com cache válido; é o "re-analisar" da aba.
    """
    aviso = aviso or _nada
    if not arquivos:
        raise AnaliseFalhou("essa mídia não tem som para transcrever")

    receita = _estagios.assinatura(_estagios.TRANSCRICAO)
    em_dia = (not midia.precisa_refazer(_estagios.TRANSCRICAO, receita)
              and midia.tem_transcricao())
    if em_dia and not forcar:
        quem = quem_fala(midia, arquivos, trilhas, fonte_dos_nomes, aviso)
        alin = alinhar(midia, arquivos, aviso)
        return {"falas": midia.ler_transcricao(), "do_cache": True, "falantes": quem, "alinhamento": _resumo(alin),
                "voz": medir_voz(midia, arquivos, trilhas, quem, aviso, alinhamento=alin)}

    try:
        log.info("transcrevendo %s (%d canal(is))", nome or midia.chave, len(arquivos))
        # ⭐ As duas etapas lentas do produto, e as duas contam o que estão fazendo. Sem
        #   isto o painel fica parado por mais de um minuto num take de quatro — tempo
        #   suficiente para o editor achar que travou.
        aviso("mixando o áudio", None, nome)
        wav = _audio.mixar(arquivos, midia.audio)

        def andando(fracao: float, trecho: str) -> None:
            aviso("ouvindo", fracao, trecho)

        falas = [f.como_dicionario() for f in _asr.transcrever(wav, aviso=andando)]
    except (_audio.FfmpegAusente, _audio.ExtracaoFalhou, _asr.AsrIndisponivel) as e:
        raise AnaliseFalhou(str(e)) from e

    midia.guardar_transcricao(falas)
    midia.registrar_gerador(_estagios.TRANSCRICAO, receita)
    # O nome e os canais vão para o manifesto (`fonte`), junto da identidade.
    if nome:
        midia.anotar_fonte({"master_de_som": nome, "canais": len(arquivos)})
    quem = quem_fala(midia, arquivos, trilhas, fonte_dos_nomes, aviso, forcar=True)
    alin = alinhar(midia, arquivos, aviso, forcar=True)
    return {"falas": falas, "do_cache": False, "falantes": quem, "alinhamento": _resumo(alin),
            "voz": medir_voz(midia, arquivos, trilhas, quem, aviso, forcar=True, alinhamento=alin)}


def trilhas_do_som(arquivos: list[str], colunas: dict | None = None,
                   fonte: str = "") -> tuple[list[_canais.Trilha], str]:
    """Os nomes dos canais: as colunas `TRK` (bin) se houver; senão o iXML do arquivo (BWF de um arquivo só).

    ⛔ Nunca pela posição (banco: o canal 3 é `BOOM 2` num take e `BOOM 1` noutro). Sem nenhum: `([], "")`."""
    tr = _canais.de_colunas(colunas, canais=len(arquivos) if len(arquivos) > 1 else 0)
    if tr:
        return tr, fonte or "bin"
    if len(arquivos) == 1:
        tr = _canais.de_ixml(arquivos[0])
        if tr:
            return tr, "ixml"
    return [], ""


def quem_fala(midia: _cache.Midia, arquivos: list[str], trilhas=None, fonte_dos_nomes: str = "",
              aviso: Aviso | None = None, forcar: bool = False) -> dict[str, Any]:
    """⭐ Quem fala cada fala, pela lapela (plano `2026-11-06-transcricao-por-canal.md`). Barato com cache.

    ⚠️ Falhar aqui NUNCA tira a transcrição de quem pediu: devolve `{"erro": …}` e a fala segue sem falante."""
    if trilhas is None:
        trilhas, fonte_dos_nomes = trilhas_do_som(arquivos)
    try:
        if aviso and (forcar or not _falantes.ler(midia)):
            aviso("vendo quem fala em cada lapela", None, "")
        dados = _falantes.garantir(midia, arquivos, trilhas, fonte_dos_nomes, forcar=forcar)
    except (_falantes.MedicaoFalhou, OSError, ValueError) as e:
        log.warning("não consegui ver quem fala em %s: %s", midia.chave, e)
        return {"erro": str(e)}
    log.info("quem fala em %s: %s (%s)", midia.chave, _falantes.contagem(dados),
             _canais.resumo([_canais.Trilha(**t) for t in dados.get("trilhas") or []]))
    return dados


def alinhar(midia: _cache.Midia, arquivos: list[str], aviso: Aviso | None = None,
            forcar: bool = False) -> dict[str, Any]:
    """⭐ A borda de cada palavra pelo alinhador CTC (L1 do plano 2026-11-11-alinhador-por-palavra.md). Barato com cache.

    Só no Mac (`alinhamento.motivo_para_nao_rodar`): fora dele devolve `{"nao_medido": motivo}` e a borda segue a do
    Whisper. ⚠️ Como `quem_fala`: falhar aqui NUNCA tira a transcrição — devolve `{"erro": …}`."""
    try:
        if not forcar and (pronto := _alin.ler(midia)):
            return pronto
        if motivo := _alin.motivo_para_nao_rodar():
            return {_alin.NAO_MEDIDO: motivo}
        wav = midia.audio
        if not wav.is_file():
            # O `audio.wav` é arquivo de trabalho (a cópia entre bancos não o leva): refazer é a mesma mistura do ASR.
            if aviso:
                aviso("mixando o áudio", None, "")
            wav = _audio.mixar(arquivos, midia.audio)
        if aviso:
            aviso("alinhando as palavras", 0.0, "")
        return _alin.garantir(midia, wav, forcar=True,
                              andando=(lambda fr: aviso("alinhando as palavras", fr, "")) if aviso else None)
    except Exception as e:  # noqa: BLE001 — onnxruntime e ffmpeg levantam de tudo; a transcrição não pode cair por isto
        log.warning("não consegui alinhar as palavras de %s: %s", midia.chave, e)
        return {"erro": str(e)}


def _resumo(alin: dict[str, Any]) -> dict[str, Any]:
    """O que a ferramenta conta do alinhamento (a lista crua fica no cache)."""
    if "palavras" in alin:
        return {"alinhadas": alin.get("alinhadas"), "total": alin.get("total")}
    return {k: v for k, v in alin.items() if k in (_alin.NAO_MEDIDO, "erro")}


def medir_voz(midia: _cache.Midia, arquivos: list[str], trilhas=None, falantes: dict[str, Any] | None = None,
              aviso: Aviso | None = None, forcar: bool = False, alinhamento: dict[str, Any] | None = None) -> dict[str, Any]:
    """⭐ A borda real da voz, na lapela de quem fala (L2 do plano 2026-11-11-alinhador-por-palavra.md). Barato com cache.

    ⚠️ Como `quem_fala`: falhar aqui NUNCA tira a transcrição de quem pediu — devolve `{"erro": …}` e o corte segue
    com o respiro de sempre."""
    if trilhas is None:
        trilhas, _ = trilhas_do_som(arquivos)
    try:
        if aviso and (forcar or not _voz.ler(midia)):
            aviso("medindo a voz em cada lapela", None, "")
        dados = _voz.garantir(midia, arquivos, trilhas, falantes if isinstance(falantes, dict) else None, forcar=forcar,
                              alinhamento=alinhamento if alinhamento and "palavras" in alinhamento else None)
    except (_falantes.MedicaoFalhou, OSError, ValueError) as e:
        log.warning("não consegui medir a voz em %s: %s", midia.chave, e)
        return {"erro": str(e)}
    log.info("voz em %s: lapelas %s (%s), %d silêncio(s)", midia.chave, dados.get("lapelas"),
             dados.get("lapelas_por"), len(dados.get("silencios") or []))
    return dados
