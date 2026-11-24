"""Editar a timeline que o EDITOR montou — ler, conferir, e entregar a cópia na Record.

⭐⭐ **O caminho B** (decisão do editor, 2026-09-13): a timeline dele tem efeitos, keyframes,
automação, transições, e nada disso pode se perder. A edição sai numa **cópia na mesma bin**,
a original intacta, e a cópia só é gravada se a prova de `avid/edicao.py` passar — tudo o
que a operação não devia tocar, idêntico por impressão digital.

Três ferramentas, e a do meio é a que evita o clique inútil:

| ferramenta | escreve | por quê |
|---|---|---|
| `ler_timeline` | não | o modelo precisa dos timecodes e do que está pendurado em cada clipe |
| `conferir_a_edicao` | não | a recusa ("cai no meio de um clipe") aparece ANTES do cartão |
| `editar_timeline` | **sim** | fecha a bin, grava com prova, reabre e carrega na Record |

⚠️ Sem a conferência, o editor aprovaria o cartão e leria "recusado" depois do clique — o
mesmo raciocínio do `conferir_o_mapa`: um passo de conferência que exige clique é um passo
que ninguém dá.

⛔ Toda operação que mexe em bin e monitor segue a regra medida em 2026-09-13: carregar →
consultar → fechar colados derruba o Media Composer; a ponte (`avid/mcapi.py`) espera.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from ...avid import timeline_do_editor as TE
from ...avid.atributos import copiar_bin   # copy2 + o estado da bin no Mac
from ...avid.bins import bins_do_projeto
from ...avid.mcapi import TEMPO_DE_ARQUIVO_S, McApiErro, MediaComposer, mob_id_da_api
from ... import nle as _nle
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.edicao")

_OPERACOES = {
    "type": "array",
    "description": (
        "As edições, com os timecodes da timeline ORIGINAL como ler_timeline mostrou — não "
        "desconte o que uma operação anterior tirou ou pôs: isso é feito aqui."
    ),
    "items": {
        "type": "object",
        "properties": {
            "tipo": {"type": "string", "enum": list(TE.TIPOS), "description": (
                "extrair: tira o trecho de TODAS as trilhas e cola o resto (o Extract do "
                "Avid). abrir_espaco: empurra tudo e deixa vazio em todas as trilhas. "
                "inserir: empurra tudo e põe um clipe nas trilhas pedidas."
            )},
            "de": {"type": "string", "description": "extrair: timecode do IN, HH:MM:SS:FF."},
            "ate": {"type": "string", "description": (
                "extrair: timecode do OUT, exclusivo — o primeiro frame que FICA.")},
            "em": {"type": "string", "description": (
                "abrir_espaco e inserir: o timecode onde o espaço abre.")},
            "duracao_frames": {"type": "integer", "description": (
                "abrir_espaco e inserir: quantos frames.")},
            "clipe": {"type": "string", "description": (
                "inserir: nome ou MobID do subclipe ou master.")},
            "in_no_clipe": {"type": "integer", "default": 0, "description": (
                "inserir: frame DENTRO do clipe onde o trecho começa.")},
            "imagem_em": {"type": "string", "description": "inserir: trilha da imagem, ex. V2."},
            "som_em": {"type": "array", "items": {"type": "string"}, "description": (
                "inserir: trilhas do som, na ordem dos canais do clipe, ex. [\"A1\", \"A2\"].")},
        },
        "required": ["tipo"],
    },
}

_BIN = {"type": "string", "description": (
    "Caminho da bin da timeline. Vazio: procura a sequência nas bins do projeto.")}
_SEQUENCIA = {"type": "string", "description": (
    "Nome ou MobID da sequência — o mob_id de o_que_esta_na_tela serve.")}


def _raiz() -> Path:
    with MediaComposer() as mc:
        return Path(mc.projeto()["caminho"])


def _onde(bin: str, sequencia: str) -> Path:
    """A bin, em caminho absoluto; sem bin, a que tem a sequência."""
    if bin and Path(bin).is_absolute():
        return Path(bin)
    if bin:
        return _raiz() / bin
    if not str(sequencia or "").strip():
        raise TE.TimelineErro("diga a bin ou a sequência")
    return TE.achar_bin_da_sequencia(bins_do_projeto(_raiz()), sequencia)


def _bin_do_clipe(bin_do_clipe: str) -> str | None:
    if not str(bin_do_clipe or "").strip():
        return None
    p = Path(bin_do_clipe)
    return str(p if p.is_absolute() else _raiz() / p)


@ferramenta(
    nome="ler_timeline",
    descricao=(
        "Lê uma sequência que o editor montou, trilha a trilha, em timecode de record: cada "
        "clipe com o in dele, e o que está pendurado — efeito, keyframes, group clip, "
        "transição. Vazios não aparecem. Use antes de editar a timeline, e quando o editor "
        "falar de 'esta timeline' (o_que_esta_na_tela dá o MobID). No Media Composer lê o "
        "arquivo da bin (o que o editor mudou e ainda não salvou não aparece); no Premiere lê "
        "a sequência ao vivo. Timeline longa vem por partes — "
        "use de/ate e trilhas para ler só o trecho que importa."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": _BIN,
            "sequencia": _SEQUENCIA,
            "de": {"type": "string", "description": "Timecode de onde começar a ler."},
            "ate": {"type": "string", "description": "Timecode de onde parar."},
            "trilhas": {"type": "array", "items": {"type": "string"},
                        "description": "Só estas trilhas, ex. [\"V1\", \"A1\"]."},
        },
    },
    escreve=False,
    nles=AMBOS,
)
def ler_timeline(bin: str = "", sequencia: str = "", de: str = "", ate: str = "",
                 trilhas: list | None = None) -> dict[str, object]:
    if _nle.qual() == _nle.PREMIERE:
        return _no_premiere(lambda E: E.ler(sequencia, de, ate, trilhas))
    try:
        return TE.ler(_onde(bin, sequencia), sequencia, de, ate, trilhas)
    except TE.TimelineErro as e:
        return {"erro": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer não respondeu: {e}"}


@ferramenta(
    nome="conferir_a_edicao",
    descricao=(
        "Confere, SEM gravar nada, se uma edição na timeline do editor pode ser feita "
        "preservando tudo o mais — e diz o que mudaria. Chame sempre antes de "
        "editar_timeline, com os mesmos argumentos: o que não dá para fazer (cortar no meio "
        "de um clipe, através de uma transição, aparar um clipe com keyframes) volta aqui "
        "com o motivo, e aí ajuste o ponto ou explique ao editor, em vez de mandar um "
        "pedido que ele aprovaria para ver falhar."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": _BIN,
            "sequencia": _SEQUENCIA,
            # ⚠️ Sem repetir o esquema inteiro: o catálogo vai em TODO turno, e o modelo já
            #    lê as operações descritas em `editar_timeline` (medido: ~1.800 caracteres).
            "operacoes": {"type": "array", "items": {"type": "object"}, "description": (
                "Exatamente as operações que irão para editar_timeline.")},
            "bin_do_clipe": {"type": "string", "description": (
                "Só para inserir clipe que está em OUTRA bin: o caminho dela.")},
        },
        "required": ["sequencia", "operacoes"],
    },
    escreve=False,
    nles=AMBOS,
)
def conferir_a_edicao(sequencia: str, operacoes: list, bin: str = "",
                      bin_do_clipe: str = "") -> dict[str, object]:
    if _nle.qual() == _nle.PREMIERE:
        def conf(E):
            motivo = E.conferir(sequencia, operacoes)
            return ({"pode": False, "motivo": motivo} if motivo else
                    {"pode": True, "proximo_passo": "chame editar_timeline com estes mesmos argumentos"})
        return _no_premiere(conf)
    try:
        caminho = _onde(bin, sequencia)
        r = TE.aplicar(caminho, sequencia, operacoes,
                       bin_do_clipe=_bin_do_clipe(bin_do_clipe))
    except TE.TimelineErro as e:
        return {"pode": False, "motivo": str(e)}
    except McApiErro as e:
        return {"erro": f"o Media Composer não respondeu: {e}"}
    return {"pode": True, "bin": str(caminho), **r,
            "proximo_passo": "chame editar_timeline com estes mesmos argumentos"}


def _conferir_edicao(sequencia: str = "", operacoes: list | None = None, bin: str = "",
                     bin_do_clipe: str = "", **_resto) -> str:
    """A conferência que o portão roda antes do cartão — a mesma do `conferir_a_edicao`,
    para que o cartão nunca apareça para uma edição que vai ser recusada depois do clique,
    mesmo quando o modelo esquece de conferir."""
    if _nle.qual() == _nle.PREMIERE:
        from ...nle.premiere import edicao as _E
        return _E.conferir(sequencia, operacoes or [])
    try:
        TE.aplicar(_onde(bin, sequencia), sequencia, operacoes or [],
                   bin_do_clipe=_bin_do_clipe(bin_do_clipe))
    except TE.TimelineErro as e:
        return f"a edição não pode ser feita: {e}"
    except McApiErro as e:
        return f"o Media Composer não respondeu: {e}"
    return ""


@ferramenta(
    nome="editar_timeline",
    descricao=(
        "Aplica edições numa CÓPIA da timeline do editor, na mesma bin, e carrega a cópia na "
        "Record. A original fica intacta, e a cópia só é gravada se a prova passar: tudo que "
        "a edição não toca — efeitos, keyframes, volume, transições — idêntico ao original. "
        "Chame conferir_a_edicao antes, com os mesmos argumentos. O editor aprova antes de "
        "qualquer coisa ser escrita; se a bin estiver aberta, ela é fechada (o Media "
        "Composer salva) e reaberta sozinha."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": _BIN,
            "sequencia": _SEQUENCIA,
            "operacoes": _OPERACOES,
            "nome_da_copia": {"type": "string", "description": (
                "Nome da cópia na bin. Vazio: o nome da original + ' - editada'.")},
            "bin_do_clipe": {"type": "string", "description": (
                "Só para inserir clipe que está em OUTRA bin: o caminho dela.")},
            "porque": {"type": "string", "description": (
                "O que o editor pediu, em uma frase — é o que ele lê no cartão.")},
        },
        "required": ["sequencia", "operacoes", "porque"],
    },
    escreve=True,
    conferir=_conferir_edicao,
    nles=AMBOS,
)
def editar_timeline(sequencia: str, operacoes: list, porque: str = "", bin: str = "",
                    nome_da_copia: str = "", bin_do_clipe: str = "") -> dict[str, object]:
    if _nle.qual() == _nle.PREMIERE:
        return _no_premiere(lambda E: E.editar(sequencia, operacoes, nome_da_copia))
    try:
        caminho = _onde(bin, sequencia)
        outra = _bin_do_clipe(bin_do_clipe)
        # ⭐ Confere ANTES de fechar a bin do editor: uma recusa não deve custar a ele a bin
        #    sumindo e voltando na tela.
        TE.aplicar(caminho, sequencia, operacoes, bin_do_clipe=outra)
        with MediaComposer() as mc:
            relativo = mc.caminho_relativo_da_bin(str(caminho))
    except TE.TimelineErro as e:
        return {"erro": f"a edição não pode ser feita: {e}"}
    except McApiErro as e:
        return {"erro": f"o Media Composer não respondeu: {e}"}

    # ⛔⛔ Fechar ANTES de tocar no arquivo: com a bin aberta, o MC salva por cima do nosso
    #    arquivo quando ele mesmo fechar (banco, `protocolos/avb/escrita.md`). E o `CloseBin`
    #    SALVA: o que o editor fez até agora vai para o disco antes da edição.
    try:
        with MediaComposer() as mc:
            mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=relativo)
    except McApiErro as e:
        log.debug("CloseBin de %s: %s", relativo, e)      # fechada já é o normal

    try:
        guarda = Path(tempfile.mkdtemp(prefix="cicloassist-")) / caminho.name
        copiar_bin(caminho, guarda)
    except OSError as e:
        # ⛔ Revisão de 2026-09-13: fora do `try`, esta cópia falhando (disco cheio) deixava
        #    a bin do editor FECHADA na tela dele, sem ninguém reabrir.
        _abrir(relativo)
        return {"erro": f"não consegui guardar a cópia de segurança da bin, e por isso não "
                        f"editei nada: {e}"}
    try:
        try:
            # ⚠️ De novo, agora sobre o que o CloseBin salvou — pode não ser o que a
            #    conferência leu, se o editor mexeu na timeline sem salvar.
            r = TE.aplicar(caminho, sequencia, operacoes, nome=nome_da_copia, gravar=True,
                           bin_do_clipe=outra)
        except Exception as e:  # noqa: BLE001
            # ⛔ QUALQUER falha, e não só as previstas: um erro inesperado do pyavb depois do
            #    `CloseBin` deixaria a bin fechada e, se veio depois do `os.replace`, trocada.
            #    Devolver a cópia é seguro nos dois casos.
            log.exception("a edição de %s falhou; devolvendo a bin", relativo)
            copiar_bin(guarda, caminho)
            _abrir(relativo)
            motivo = str(e) if isinstance(e, TE.TimelineErro) else f"{type(e).__name__}: {e}"
            return {"erro": f"a edição não foi gravada, e a bin está como estava: {motivo}"}

        aberta, recusa = _abrir(relativo)
        if recusa:
            # ⛔⛔ O MC não aceita a bin regravada: ela volta byte a byte.
            log.warning("o MC recusou %s depois da edição (%s); devolvendo", relativo, recusa)
            copiar_bin(guarda, caminho)
            _abrir(relativo)
            return {"erro": (
                f"O Media Composer recusou abrir a bin {caminho.stem} depois da edição "
                f"({recusa}). Ela foi devolvida exatamente como estava, e nada foi editado. "
                f"Diga isso ao editor com estas palavras.")}
    finally:
        shutil.rmtree(guarda.parent, ignore_errors=True)

    na_record = False
    if aberta:
        try:
            with MediaComposer() as mc:
                mc._chamar("LoadMobsIntoViewer", mob_ids=[mob_id_da_api(r["mob_id_novo"])],
                           view_type=mc._enum("LoadMobsIntoViewer", "view_type", "Record"))
            na_record = True
        except (McApiErro, ValueError) as e:
            log.warning("a cópia foi gravada mas não carregou na Record: %s", e)

    return {"ok": True, "bin": relativo, "aberta_no_avid": aberta,
            "carregada_na_record": na_record, **r}


def _abrir(relativo: str) -> tuple[bool, str]:
    """`OpenBin`. (abriu, a recusa do ARQUIVO) — só `FILE_OPEN_FAILURE` é recusa."""
    try:
        with MediaComposer() as mc:
            mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=relativo)
        return True, ""
    except McApiErro as e:
        log.warning("OpenBin de %s falhou: %s", relativo, e)
        return False, "FILE_OPEN_FAILURE" if "FILE_OPEN_FAILURE" in str(e) else ""


def _no_premiere(fazer) -> dict[str, object]:
    """⭐ F4 do plano 2026-11-06-mcp-do-premiere: a timeline do Premiere pelo MCP nativo."""
    from ...nle.premiere import edicao as E
    from ...nle.premiere import mcp_nativo as M
    from ...nle.premiere import ponte
    # ⭐ F7: sem o MCP nativo (2025/2026), a ponte CEP faz o mesmo (`edicao_cep.py`).
    if M.via("edicao") != "mcp" and not ponte.painel_vivo():
        return {"erro": ("o Premiere não está ligado ao Ciclo Assist: nem o servidor MCP (27.1+) nem a ponte "
                         "do painel respondem. Diga ao editor para abrir o Premiere com o Ciclo Assist.")}
    try:
        return fazer(E)
    except E.EdicaoRecusada as e:
        return {"erro": str(e)}
    except (M.McpIndisponivel, M.McpFalhou) as e:
        return {"erro": f"o Premiere não respondeu: {e}"}
