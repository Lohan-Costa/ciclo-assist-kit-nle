"""O Premiere visto pelo Ciclo Assist: projeto, itens, take e recorte — tudo pela ponte.

A diferença de fundo para o Avid (plano `docs/plano/2026-09-17-premiere.md`): no Premiere o
item aponta um ARQUIVO, e não um master com UMID. A mídia do cache é achada pelo arquivo
(`midia/identidade.py`) — pela chave dele, por um apelido, ou pelo convertido que o Avid já
processou. É isso que faz o material analisado no Media Composer chegar pronto aqui.

## O que cada espécie de item vira

| espécie (`host.jsx`) | take |
|---|---|
| `clipe` | uma mídia; imagem e/ou som do MESMO arquivo, a partir do quadro 0 |
| `merged` | a imagem de um arquivo e o som de outro, cada um com a sua entrada — o subclipe sincronizado do Avid |
| `sequencia`, `multicam`, `ajuste`, `bin` | recusado, com a frase certa |

⭐ **Subclipe:** `getInPoint/OutPoint` devolvem o master INTEIRO (medido no 23.2). O recorte
mora nos metadados do projeto — `Column.Intrinsic.SubclipStart` e `SubclipDuration`, em
timecode —, e o início no arquivo é `SubclipStart − TC do arquivo`. MEDIDO
(`spikes/o_painel_no_premiere.py`): subclipe de 2 s a 5 s num clipe que começa em
23:16:47:11 → `SubclipStart 23:16:49:10`, `SubclipDuration 00:00:02:23`; o Premiere arredonda
os 2 s (47,95 quadros) para BAIXO. Com "hard boundaries" o `MediaStart` passa a ser o do
subclipe, e por isso a conta usa o TC do ARQUIVO, nunca o `MediaStart`.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from fractions import Fraction
from pathlib import Path
from typing import Any, Callable

from ...avid import escopo as _escopo
from ...avid.take import Fonte, Take, TakeErro, fracao_da_taxa, ler_claquete, para_segundos
from ...midia import cache as _cache
from ...midia import identidade as _identidade
from ...midia import timecode as _timecode
from . import mcp_nativo, ponte

log = logging.getLogger("cicloassist.nle.premiere")

TICKS_POR_SEGUNDO = 254016000000
HOST_JSX = Path(__file__).with_name("host.jsx")

#: ⭐ Fase 4 do plano um app só (2026-11-07): a ponte do Assist é a ÚNICA no Premiere, e ela carrega o ExtendScript dos
#: três módulos. Cada um tem o seu prefixo — `ciclo*` (este), `sinc*` (Sincronizar), `dlpc*` (Conformar) —, medido sem
#: nenhum nome de topo em comum: num ExtendScript global o último a declarar ganharia CALADO.
_RAIZ = Path(__file__).resolve().parents[3]
HOSTS_DOS_MODULOS = (
    _RAIZ / "modulos" / "sincronizar" / "pagina" / "host.jsx",
    _RAIZ / "modulos" / "conformar" / "plugins" / "media-composer" / "servico" / "ui" / "premiere_host.jsx",
)


def host_jsx_inteiro() -> bytes:
    """O `host.jsx` que a ponte avalia: o do Assist e os dos módulos, em bytes (o fim de linha de cada um fica)."""
    partes = [HOST_JSX.read_bytes()]
    for p in HOSTS_DOS_MODULOS:
        if p.is_file():
            partes.append(b"\n// ---- " + p.name.encode() + b" (" + p.parent.parent.name.encode() + b") ----\n"
                          + p.read_bytes())
        else:
            log.warning("o ExtendScript do módulo não está em %s: as funções dele não vão existir no Premiere", p)
    return b"\n;\n".join(partes)

#: O recorte do projeto vale por isto. Ler o projeto custa milissegundos pela ponte, mas a
#: chave de cada arquivo novo custa ler 8 MB dele.
VALIDADE_DO_RECORTE_S = 30.0

RECUSAS = {
    "sequencia": "é uma sequência, não um clipe. Aponte os clipes que estão nela.",
    "multicam": "é um clipe multicâmera, que ainda não é aceito. Aponte o clipe de uma câmera.",
    "ajuste": "é uma camada de ajuste — não tem mídia.",
    "bin": "é uma bin. Liste os itens dela e aponte um clipe.",
    "arquivo": "não é mídia de vídeo ou som.",
    "outro": "não tem mídia que o Ciclo Assist saiba abrir (título, cor, still?).",
}


def _pelo_mcp(operacao: str, leitura: Callable[[], Any]) -> tuple[bool, Any]:
    """`(True, resultado)` se a operação foi atendida pelo MCP nativo; `(False, None)` = use a CEP.

    ⭐ Plano `docs/plano/2026-11-06-mcp-do-premiere.md`: a via mais nova quando o Premiere aberto
    a tiver. ⛔ Uma falha do MCP NUNCA vira erro para o editor enquanto a CEP puder responder: ela
    é registrada e a mesma pergunta vai pela ponte.
    """
    if mcp_nativo.via(operacao) != "mcp":
        return False, None
    try:
        return True, leitura()
    except (mcp_nativo.McpIndisponivel, mcp_nativo.McpFalhou, KeyError, TypeError, ValueError) as e:
        if mcp_nativo.via_forcada() == "mcp":
            raise
        log.warning("MCP do Premiere falhou em '%s' (%s); vou pela ponte CEP", operacao, e)
        return False, None


def alcancavel() -> bool:
    """O Premiere responde por ALGUMA via (o MCP nativo ou o painel CEP vivo)."""
    return mcp_nativo.disponivel() or ponte.painel_vivo()


def projeto_aberto(recarregar: bool = False) -> str:  # noqa: ARG001 — mesma assinatura do Avid
    feito, p = _pelo_mcp("projeto", mcp_nativo.projeto_ativo)
    if feito:
        return str((p or {}).get("path") or "") or _escopo.SEM_PROJETO
    if not ponte.painel_vivo():
        return _escopo.SEM_PROJETO
    try:
        caminho = ponte.chamar("cicloProjeto", prazo=5).get("caminho") or ""
    except (ponte.PremiereIndisponivel, ponte.ExtendScriptFalhou) as e:
        log.info("sem projeto do Premiere (%s)", e)
        return _escopo.SEM_PROJETO
    return caminho or _escopo.SEM_PROJETO


def estado() -> dict[str, Any]:
    feito, r = _pelo_mcp("projeto", mcp_nativo.estado)
    if feito:
        return r
    return ponte.chamar("cicloProjeto")


def _midias(prazo: float = 60) -> dict[str, Any]:
    """`{arquivos, itens}` do projeto aberto — pelo MCP quando houver, senão `cicloMidias`."""
    feito, r = _pelo_mcp("midias", mcp_nativo.midias)
    if feito:
        return r
    return ponte.chamar("cicloMidias", prazo=prazo) or {}


def contador_da_vigia() -> Any:
    """Algo que MUDA quando o projeto ganha item — a vigia só varre quando muda.

    Pelo MCP é a assinatura dos clipes (~1 ms); pela CEP, o contador de imports (`cicloVigia`).
    """
    feito, r = _pelo_mcp("midias", mcp_nativo.assinatura_dos_itens)
    if feito:
        return r
    return ponte.chamar("cicloVigia", prazo=5)


def bins() -> list[dict[str, Any]]:
    feito, r = _pelo_mcp("itens", mcp_nativo.bins)
    if feito:
        return r
    return ponte.chamar("cicloBins").get("bins") or []


def itens(bin: str = "", apenas_selecionados: bool = False) -> dict[str, Any]:
    feito, r = _pelo_mcp("itens", lambda: mcp_nativo.itens(bin or "", bool(apenas_selecionados)))
    if feito:
        return r
    return ponte.chamar("cicloItens", _ref_para_cep(bin or ""), bool(apenas_selecionados))


def selecao() -> list[dict[str, Any]]:
    feito, r = _pelo_mcp("itens", mcp_nativo.selecao)
    if feito:
        return r
    return ponte.chamar("cicloSelecao").get("itens") or []


def _ref_para_cep(ref: str) -> str:
    """⛔ O id que o modelo leu pode ser do MCP (F2): a CEP não o conhece, mas conhece o CAMINHO
    "BIN/NOME" — a tradução acontece aqui, em todo comando que vai pela ponte com uma referência."""
    if not ref or not mcp_nativo.disponivel():
        return str(ref or "")
    return mcp_nativo.caminho_do_item(str(ref)) or str(ref)


# ── o take ───────────────────────────────────────────────────────────────────


def _taxa(fps: Any) -> Fraction:
    try:
        valor = float(fps or 0)
    except (TypeError, ValueError):
        valor = 0.0
    # ⚠️ Áudio puro devolve 2,75e-8 (medido): não é quadro. O tempo do som é contado na
    #    taxa do projeto de vídeo mais comum da casa até haver uma imagem que diga outra.
    if valor < 1:
        return Fraction(24000, 1001)
    return fracao_da_taxa(valor)


def _quadros(ticks: Any, taxa: Fraction) -> int:
    try:
        return round(Fraction(int(ticks), TICKS_POR_SEGUNDO) * taxa)
    except (TypeError, ValueError):
        return 0


def _fonte(nome: str, arquivos: list[str], inicio: int, taxa: Fraction,
           relatar: Callable[[str], None] | None, avisos: list[str]) -> Fonte:
    """Uma `Fonte` cuja chave é a da mídia do cache — inclusive a de um convertido."""
    existentes = [a for a in arquivos if a and Path(a).is_file()]
    chave, tipo, apelidos = "", "conteudo", {}
    if existentes:
        # ⭐⭐ **É aqui que os bancos se cruzam, e só aqui** (decisão do editor,
        #   2026-09-21): a entrada deste clipe nasce no banco do PREMIERE e, se casar por
        #   conteúdo com algo já analisado, copia o trabalho em vez de refazê-lo.
        # ⛔ E a frase NÃO cita o Media Composer: o editor não quer saber de onde veio —
        #   ele quer saber que não vai esperar de novo.
        aproveitado = _identidade.aproveitar(existentes[0], "premiere", relatar=relatar)
        avisos.extend(aproveitado.avisos)
        chave, tipo = aproveitado.midia.chave, _identidade.chave_do_arquivo(existentes[0])[1]
        if aproveitado.aproveitou:
            avisos.append(
                f"{Path(existentes[0]).name} já tinha sido analisado: aproveitei o que "
                f"existia em vez de processar de novo (conteúdo conferido: "
                f"{aproveitado.medida:.3f}).")
    elif arquivos:
        avisos.append(f"o arquivo de {nome!r} não está no disco: {arquivos[0]}")
    return Fonte(master=nome, mob_id=chave or nome, arquivos=existentes,
                 inicio_frames=inicio, inicio_s=para_segundos(inicio, taxa),
                 tracks=len(existentes), faltando_no_disco=not existentes,
                 origem="premiere", chave=chave, tipo_da_chave=tipo, apelidos=apelidos)


def _campo(metadados: str, nome: str) -> str:
    achado = re.search(rf"Column\.Intrinsic\.{nome}>([^<]*)<", metadados or "")
    return achado.group(1).strip() if achado else ""


def tc_em_quadros(tc: str, taxa: Fraction) -> int | None:
    """`HH:MM:SS:FF` → quadros, na base inteira da taxa (24 para 23,976). ⚠️ Sem drop-frame:
    `;` é recusado, porque contar 29,97 DF como NDF erra 18 quadros a cada 10 minutos."""
    achado = re.fullmatch(r"(\d+):(\d+):(\d+):(\d+)", (tc or "").strip())
    if not achado:
        return None
    h, m, s, f = (int(x) for x in achado.groups())
    return ((h * 60 + m) * 60 + s) * round(taxa) + f


def recorte_do_subclipe(metadados: str, tc_do_arquivo: str,
                        taxa: Fraction) -> tuple[int, int] | None:
    """(início no arquivo, duração) em quadros, ou `None` se não der para ler."""
    inicio = tc_em_quadros(_campo(metadados, "SubclipStart"), taxa)
    base = tc_em_quadros(tc_do_arquivo, taxa) if tc_do_arquivo else 0
    duracao = tc_em_quadros(_campo(metadados, "SubclipDuration"), taxa)
    if inicio is None or base is None or duracao is None:
        return None
    return max(0, inicio - base), duracao


def _do_clipe(d: dict[str, Any], taxa: Fraction, relatar, avisos) -> tuple[Fonte | None, Fonte | None, int]:
    arquivo = str(d.get("arquivo") or "")
    try:
        sonda = _identidade.sondar(arquivo) if arquivo else {}
    except _identidade.IdentidadeErro as e:
        raise TakeErro(str(e)) from e
    inicio = _quadros(d.get("entrada") or 0, taxa)
    fim = _quadros(d.get("saida") or 0, taxa)
    duracao = max(0, fim - inicio) or int(sonda.get("quadros") or 0) \
        or round(float(sonda.get("duracao_s") or 0) * taxa)
    metadados = str(d.get("metadados") or "")
    if _campo(metadados, "SubclipStart"):
        recorte = recorte_do_subclipe(metadados, str(sonda.get("tc") or ""), taxa)
        if recorte is None:
            avisos.append("não consegui ler o recorte deste subclipe (timecode drop-frame?); "
                          "tratei como o clipe inteiro")
        else:
            inicio, duracao = recorte
            if not sonda.get("tc"):
                avisos.append("o arquivo não tem timecode: o recorte do subclipe foi contado "
                              "a partir do zero")
    fonte = _fonte(str(d.get("nome") or ""), [arquivo], inicio, taxa, relatar, avisos)
    imagem = fonte if sonda.get("tipo") == "video" else None
    som = fonte if int(sonda.get("pistas_de_som") or 0) > 0 else None
    return imagem, som, duracao


def _do_merged(d: dict[str, Any], taxa: Fraction, relatar, avisos) -> tuple[Fonte | None, Fonte | None, int]:
    pedacos = d.get("pedacos") or []
    de_imagem = [p for p in pedacos if p.get("especie") == "imagem" and p.get("arquivo")]
    de_som = [p for p in pedacos if p.get("especie") == "som" and p.get("arquivo")]
    if not pedacos:
        raise TakeErro("não consegui ler as trilhas deste merged clip no Premiere.")

    imagem = som = None
    duracao = 0
    if de_imagem:
        p = de_imagem[0]
        imagem = _fonte(str(p.get("nome") or d.get("nome")), [p["arquivo"]],
                        _quadros(p.get("entrada_na_midia"), taxa), taxa, relatar, avisos)
        duracao = _quadros(int(p.get("fim_na_seq") or 0) - int(p.get("inicio_na_seq") or 0), taxa)
    externos = [p for p in de_som if not de_imagem or p["arquivo"] != de_imagem[0]["arquivo"]]
    escolhidos = externos or de_som
    if escolhidos:
        arquivos = list(dict.fromkeys(p["arquivo"] for p in escolhidos))
        if len(arquivos) > 1:
            avisos.append(f"o som vem de {len(arquivos)} arquivos; esta versão usa o primeiro")
        p = escolhidos[0]
        som = _fonte(str(p.get("nome") or d.get("nome")), arquivos[:1],
                     _quadros(p.get("entrada_na_midia"), taxa), taxa, relatar, avisos)
        duracao = duracao or _quadros(
            int(p.get("fim_na_seq") or 0) - int(p.get("inicio_na_seq") or 0), taxa)
        if not externos:
            avisos.append("este merged clip não tem som de gravador: o áudio é o da câmera.")
    return imagem, som, duracao


def resolver_take(bin: str, item: str, relatar: Callable[[str], None] | None = None) -> Take:
    """Um item do Premiere → `Take`, com a chave de cache de cada lado."""
    try:
        d = ponte.chamar("cicloItem", _ref_para_cep(str(item)), str(bin or ""))
    except (ponte.PremiereIndisponivel, ponte.ExtendScriptFalhou) as e:
        raise TakeErro(str(e)) from e

    especie = str(d.get("especie") or "outro")
    avisos: list[str] = []
    if especie == "clipe":
        taxa = _taxa(d.get("fps"))
        imagem, som, duracao = _do_clipe(d, taxa, relatar, avisos)
    elif especie == "merged":
        taxa = _taxa(_fps_da_imagem(d) or d.get("fps"))
        imagem, som, duracao = _do_merged(d, taxa, relatar, avisos)
    else:
        raise TakeErro(f"{d.get('nome')!r} {RECUSAS.get(especie, RECUSAS['outro'])}")

    nome_da_claquete = som.master if som else ""
    campos = ler_claquete(Path(nome_da_claquete).stem)
    fonte = "claquete"
    if campos["cena"] is None:
        campos = ler_claquete(str(d.get("nome") or ""))
        fonte = "nome-do-item" if campos["cena"] else "nome-nao-reconhecido"

    return Take(
        nome=str(d.get("nome") or ""),
        bin=str(d.get("bin") or bin or ""),
        mob_id=str(d.get("id") or item),
        cena=campos["cena"], plano=campos["plano"], take=campos["take"],
        fonte_da_claquete=nome_da_claquete or None,
        fps={"num": taxa.numerator, "den": taxa.denominator},
        fps_aprox=round(float(taxa), 3),
        duracao_frames=duracao,
        duracao_s=para_segundos(duracao, taxa),
        imagem=imagem, som=som,
        confianca="confirmado" if fonte == "claquete" else "inferido",
        fonte=fonte, avisos=avisos,
        especie=("subclipe" if especie == "merged"
                 or _campo(str(d.get("metadados") or ""), "SubclipStart") else "master"),
    )


def _fps_da_imagem(d: dict[str, Any]) -> float | None:
    for p in d.get("pedacos") or []:
        if p.get("especie") == "imagem" and p.get("arquivo"):
            try:
                fps = _identidade.sondar(p["arquivo"]).get("fps")
                return float(Fraction(fps)) if fps else None
            except (_identidade.IdentidadeErro, ValueError, ZeroDivisionError):
                return None
    return None


# ── o recorte ────────────────────────────────────────────────────────────────

_recorte: _escopo.Escopo | None = None
_trava_do_recorte = threading.Lock()

def _banco() -> frozenset[str]:
    """Toda chave do banco do PREMIERE. É o limite de qualquer resposta daqui."""
    return _cache.chaves_da_origem("premiere")


def _so_o_banco(motivo: str) -> _escopo.Escopo:
    """"Não sei de que projeto é" — mas o BANCO ainda é um fato.

    ⛔⛔ **A regra "não sei ≠ nenhuma" continua de pé, e ganha um teto.** Ela existe para
    que desconhecer o projeto não esconda o acervo do editor; ela nunca autorizou mostrar
    o acervo de OUTRO editor. Até 2026-09-21 o Premiere sem projeto caía em `chaves=None`
    — sem filtro — e a busca devolvia as 332 mídias do cache, com nome de bin do Avid e
    caminho de `Avid MediaFiles` na lista. ⇒ Sem projeto, a resposta é o banco do Premiere
    INTEIRO, que pode ser vazio; nunca o do Media Composer.
    """
    return _escopo.Escopo(chaves=_banco(), origem=motivo, editor="premiere",
                          lido_em=time.time())

#: ⭐ O caminho do arquivo de cada chave que este projeto usa — o caminho de volta.
#:
#: ⛔⛔ No Avid o cache guarda o MobID e o Media Composer acha o mob por ele. No Premiere a
#: identidade do item é o ARQUIVO: sem este mapa, "carregue esta mídia no Source" não teria
#: como sair de uma chave de cache e chegar num `projectItem`. Ele nasce de graça — a
#: varredura do recorte já abre arquivo por arquivo.
_arquivos: dict[str, str] = {}


def escopo_agora() -> _escopo.Escopo:
    """As chaves de cache de todo arquivo que o projeto aberto usa.

    ⛔ Sem painel, "não sei" (`chaves=None`) — nunca "nenhuma mídia" (a regra da casa em
    `avid/escopo.py`).
    """
    global _recorte
    with _trava_do_recorte:
        projeto = projeto_aberto()
        if projeto == _escopo.SEM_PROJETO:
            return _so_o_banco("sem-projeto")
        if (_recorte is not None and _recorte.projeto == projeto
                and time.time() - _recorte.lido_em < VALIDADE_DO_RECORTE_S):
            return _recorte
        try:
            arquivos = _midias().get("arquivos") or []
        except (ponte.PremiereIndisponivel, ponte.ExtendScriptFalhou) as e:
            log.warning("não consegui listar a mídia do projeto (%s)", e)
            return _so_o_banco("sem-projeto")
        chaves = set()
        mapa: dict[str, str] = {}
        for a in arquivos:
            try:
                if Path(a).is_file():
                    conhecida = _identidade.chave_conhecida(a)
                    if conhecida:
                        chaves.add(conhecida)
                        # ⚠️ O PRIMEIRO arquivo de cada chave: dois caminhos para a mesma
                        #   mídia (uma cópia, um proxy) dariam dois itens, e carregar "o
                        #   outro" no Source é pior que não carregar — o editor veria um
                        #   clipe parecido e acharia que a busca errou.
                        mapa.setdefault(conhecida, a)
            except OSError:
                continue
        # ⛔⛔ Projeto COM mídia e nenhuma chave resolvida (volume desmontado, caminhos
        #    velhos) é "não sei", nunca "nenhuma mídia": `frozenset()` esconderia todo o
        #    cache do editor, com a frase do recorte por cima dizendo que é o projeto dele.
        if arquivos and not chaves:
            log.warning("o projeto tem %d arquivo(s) e nenhuma chave conhecida; fico no banco",
                        len(arquivos))
            return _so_o_banco("sem-projeto")
        _arquivos.clear()
        _arquivos.update(mapa)
        # ⛔⛔ O projeto estreita DENTRO do banco, nunca para fora dele: um arquivo do
        #    Premiere cuja chave só existe como entrada do Avid não é material deste banco.
        _recorte = _escopo.Escopo(chaves=_cache.com_apelidos(chaves) & _banco(),
                                  projeto=projeto, quando=int(time.time()),
                                  origem="projeto", lido_em=time.time(), editor="premiere")
        return _recorte


def arquivo_da_chave(chave: str) -> str:
    """O arquivo do projeto que corresponde a esta chave de cache, ou "".

    ⚠️ Monta o recorte se ainda não houver: quem pergunta isto acabou de clicar num
    resultado, e "não sei ainda" seria um duplo clique que não faz nada.
    """
    if not chave:
        return ""
    escopo_agora()
    with _trava_do_recorte:
        direto = _arquivos.get(chave)
        if direto:
            return direto
        # ⭐ A mídia pode estar guardada sob a impressão do conteúdo com a chave do arquivo
        #   como APELIDO (ou o contrário) — a mesma tradução que `cache.com_apelidos` faz
        #   para o recorte. Sem ela, o convertido que a busca achou não voltaria ao item.
        for candidata, arquivo in _arquivos.items():
            if chave in _cache.com_apelidos({candidata}):
                return arquivo
    return ""


def tc_no_source(arquivo: str, segundos: float) -> str:
    """O `tc` que o `scrubTo` do Source quer para `segundos` desde o início deste arquivo.

    ⭐⭐ MEDIDO no 23.2 (`spikes/o_source_no_tc.py`, banco `api-extendscript.md`): é TEMPO
    DESDE O INÍCIO DO CLIPE, nunca o TC dele; a 23,976 os quadros vão na base 24
    (`00:00:04:00` → 4,004 s). ⛔ E o Premiere não limita: 3604 s num clipe de 10 s foi
    aceito — por isso a duração do arquivo é o teto aqui.

    ⭐ A fala vem em segundos do MASTER, e no Premiere o master é o próprio arquivo.
    ⚠️ Sem taxa (som puro) a conta é por SEGUNDO inteiro (`SS:00`): o campo de quadro de
    um clipe de áudio no Source não foi medido, e o segundo não depende dele.
    """
    try:
        sonda = _identidade.sondar(arquivo)
    except _identidade.IdentidadeErro:
        sonda = {}
    s = max(0.0, float(segundos or 0))
    duracao = float(sonda.get("duracao_s") or 0)
    try:
        taxa = Fraction(str(sonda.get("fps"))) if sonda.get("fps") else None
    except (ValueError, ZeroDivisionError):
        taxa = None
    if taxa:
        # ⚠️ Fração exata, não float: 3603,6 s × 24000/1001 é 86400 quadros EXATOS, e em
        #    ponto flutuante dá 86399,99… — o `int` cairia um quadro para trás.
        quadros = int(Fraction(str(round(s, 6))) * taxa)
        teto = int(sonda.get("quadros") or duracao * taxa or 0) - 1
        if teto >= 0:
            quadros = min(quadros, teto)
        return _timecode.de_quadros(quadros, taxa)
    if duracao:
        s = min(s, max(0.0, duracao - 1))
    return _timecode.de_quadros(int(s), Fraction(1))


def carregar_no_source(ref: str = "", arquivo: str = "", tc: str = "") -> dict[str, Any]:
    """Põe um item do projeto no monitor **Source** (`cicloCarregarNoSource`).

    ⛔ **Não importa nada.** `openProjectItem`, nunca `openFilePath` — o segundo traria o
    arquivo para dentro do projeto do editor, que é ESCRITA, e este é um gesto de leitura
    que de propósito não passa pelo portão (a régua da casa: o portão separa quem lê de
    quem escreve).

    ✅ `openProjectItem` MEDIDO no 23.2 (2026-09-22). Com `tc` (ver `tc_no_source`) a agulha
    vai ao ponto pelo QE, e a resposta traz `posicao_s` LIDA DE VOLTA.
    """
    return ponte.chamar("cicloCarregarNoSource", _ref_para_cep(str(ref or "")), str(arquivo or ""),
                        str(tc or ""), prazo=30) or {}


def esquecer() -> None:
    global _recorte, _clipes
    mcp_nativo.esquecer()   # Premiere aberto/fechado: a sessão MCP e o catálogo também
    with _trava_do_recorte:
        _recorte = None
        _arquivos.clear()
        _clipes = None


# ── a aba Vetores: o material do projeto, como linhas ────────────────────────

#: A bin de um item que está na raiz do projeto. ⚠️ Vazio quer dizer outra coisa na tabela
#: ("ninguém leu as bins"), e por isso a raiz tem nome.
RAIZ = "(raiz do projeto)"

_clipes: tuple[str, float, dict[str, dict[str, Any]]] | None = None


# ── a decupagem na coluna "Descrição" ────────────────────────────────────────

#: O que o Ciclo Assist gravou da última vez na Descrição do item — é o `esperado` do
#: compare-and-set. Mora no manifesto da entrada DESTE banco.
CAMPO_DA_DESCRICAO = "descricao_no_premiere"
_descrevendo = threading.Lock()


def descricao_da_entrada(midia: _cache.Midia) -> str:
    """A descrição do MATERIAL INTEIRO (a nota `escopo: midia`), ou "".

    ⛔ Nunca uma nota de take: ela descreve um pedaço, e a coluna é do clipe inteiro.
    """
    for n in midia.ler_notas():
        if n.get("escopo") == "midia" and str(n.get("descricao") or "").strip():
            return str(n["descricao"]).strip()
    return ""


def sincronizar_descricoes(clipes: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """A decupagem de cada clipe do projeto na coluna "Descrição" dele — sozinho, e sem
    nunca escrever por cima do texto do editor (decisão dele, 2026-09-22).

    ⭐ Um único `evalScript` para o projeto inteiro (`cicloDescrever`). ⚠️ Mexe no projeto
    aberto: o Premiere passa a ter alterações por salvar, como qualquer edição de coluna.
    ⚠️ Uma por vez: duas ao mesmo tempo gravariam o mesmo `esperado` duas vezes.
    """
    if not _descrevendo.acquire(blocking=False):
        return {"ocupado": True}
    try:
        if clipes is None:
            _, clipes, erro = clipes_do_projeto()
            if erro and not clipes:
                return {"erro": erro}
        plano, por_arquivo = [], {}
        for chave, clipe in clipes.items():
            arquivo = clipe.get("arquivo_premiere")
            if clipe.get("provisoria") or not arquivo:
                continue
            midia = _cache.Midia(chave)
            texto = descricao_da_entrada(midia)
            if not texto:
                continue
            esperado = str(midia.manifesto().get(CAMPO_DA_DESCRICAO) or "")
            plano.append({"arquivo": arquivo, "esperado": esperado, "novo": texto})
            por_arquivo[arquivo] = (midia, texto)
        if not plano:
            return {"escritos": 0, "do_editor": 0, "iguais": 0}
        try:
            r = ponte.chamar("cicloDescrever", plano, prazo=60) or {}
        except (ponte.PremiereIndisponivel, ponte.ExtendScriptFalhou) as e:
            log.warning("não consegui escrever as descrições (%s)", e)
            return {"erro": str(e)}
        for arquivo in set(r.get("escritos") or []):
            if arquivo in por_arquivo:
                midia, texto = por_arquivo[arquivo]
                midia.marcar_no_manifesto(CAMPO_DA_DESCRICAO, texto)
        resumo = {"escritos": len(set(r.get("escritos") or [])),
                  "do_editor": len(set(r.get("do_editor") or [])),
                  "iguais": int(r.get("iguais") or 0)}
        if resumo["escritos"] or resumo["do_editor"]:
            log.info("descrições no Premiere: %s", resumo)
        return resumo
    finally:
        _descrevendo.release()


def sincronizar_descricoes_no_fundo() -> None:
    """Sem segurar quem chamou (a lista da aba, o fim de uma tarefa, a vigia)."""
    def correr() -> None:
        # ⭐⭐ Trabalho de FUNDO, e aqui isso pesa: `cicloDescrever` leva as 118 descrições
        #   num `evalScript` só, na thread principal do Premiere, e ele sai pela MESMA
        #   ponte de um pedido por vez que o painel e o chat usam. Sem ceder a vez, a
        #   escrita de uma coluna que ninguém pediu segura a pergunta que alguém pediu.
        ponte.marcar_de_fundo()
        sincronizar_descricoes()

    threading.Thread(target=correr, name="descricoes-premiere", daemon=True).start()


def chave_provisoria(arquivo: str) -> str:
    """A chave da LINHA de um arquivo que este banco ainda não conhece.

    ⛔⛔ **Não é chave de cache, e nunca vira pasta.** A chave de verdade de um `.mp4` é a
    impressão do conteúdo — 8 MB lidos por arquivo, ~1,6 GB num projeto de 200 clipes
    antes de a aba mostrar a primeira linha (a mesma conta que fez o recorte usar só a
    chave JÁ conhecida). E mesmo uma chave conhecida pode ser a de uma entrada do OUTRO
    banco — usá-la faria a fila olhar o trabalho do Avid e responder "já está pronto".
    ⇒ A linha leva um nome estável derivado do CAMINHO; quem descobre a chave de verdade
    é `identidade.aproveitar()`, dentro da fila, quando o editor manda processar.
    """
    import hashlib
    texto = str(arquivo).replace("\\", "/").lower()
    return hashlib.sha256(b"ciclo-premiere-linha-v1\0" + texto.encode("utf-8")).hexdigest()


def _clipe_do_arquivo(arquivo: str, nome: str, bins: list[str]) -> tuple[str, dict[str, Any]]:
    """A linha de um arquivo do projeto, no MESMO formato da varredura do acervo
    (`midia/acervo.Clipe`) — é o que deixa `inventario` e a fila não saberem de NLE."""
    bins = [b or RAIZ for b in bins] or [RAIZ]
    clipe: dict[str, Any] = {"nome": nome or Path(arquivo).stem, "bins": bins,
                             "arquivo_premiere": arquivo, "arquivos": [],
                             "por_tipo": {}, "tracks": {}}
    caminho = Path(arquivo)
    try:
        existe = caminho.is_file()
    except OSError:
        existe = False
    if not existe:
        # ⚠️ Offline não some da tabela: a linha fica, sem arquivo, e a coluna diz isso.
        return chave_provisoria(arquivo), {**clipe, "provisoria": True}

    clipe["arquivos"] = [arquivo]
    try:
        sonda = _identidade.sondar(caminho)
    except _identidade.IdentidadeErro as e:
        log.info("não consegui sondar %s (%s)", caminho.name, e)
        sonda = {}
    canais = [c for c in (sonda.get("canais_de_som") or []) if c]
    if sonda.get("tipo") == "video":
        clipe["por_tipo"]["video"] = [arquivo]
        clipe["tracks"]["video"] = 1
    if canais or sonda.get("tipo") == "audio":
        clipe["por_tipo"]["audio"] = [arquivo]
        clipe["tracks"]["audio"] = max(1, len(canais))
    if sonda.get("fps"):
        clipe["fps"] = sonda["fps"]
    if sonda.get("duracao_s"):
        clipe["duracao_s"] = sonda["duracao_s"]

    # ⭐ Já tem entrada NESTE banco? Então a linha é ela — e o inventário junta o que o
    #   cache sabe (quadros, fala, vetor) com o que o projeto diz (nome, bins).
    conhecida = _identidade.chave_conhecida(caminho)
    if conhecida:
        # ⛔⛔ **Sem `varrer()` aqui.** Ele relista a raiz do cache INTEIRA, e esta função
        #    roda uma vez por arquivo do projeto: eram 203 relistagens idênticas das 537
        #    pastas, O(arquivos × pastas). MEDIDO em 2026-09-23: `clipes_do_projeto` levava
        #    4,12 s, dos quais **3,97 s eram este laço** e só 0,15 s a ponte. Quem varre é
        #    `clipes_do_projeto`, UMA vez, antes de chamar isto.
        ind = _cache.indice()
        dona = ind.primaria(conhecida, "premiere")
        if ind.origem_de(dona) == "premiere" and _cache.Midia(dona).existe:
            return dona, clipe
    return chave_provisoria(arquivo), {**clipe, "provisoria": True}


def clipes_do_projeto(forcar: bool = False) -> tuple[str, dict[str, dict[str, Any]], str]:
    """`(projeto, {chave da linha: clipe}, erro)` — o material do projeto aberto.

    ⭐⭐ É a terceira fonte da aba Vetores, e a única que conhece um `.mp4` na pasta do
    editor: a `Avid MediaFiles` e as bins do Media Composer nunca o viram. Sem ela, o gesto
    que o editor descreveu — *"importo a mídia no Premiere e peço para processar"* — não
    tinha onde acontecer.

    ⚠️ Custa um `ffprobe` por arquivo NOVO (guardado para sempre pela `identidade`), e o
    resultado vale `VALIDADE_DO_RECORTE_S`, como o recorte. `forcar` relê — é o que a
    vigia usa depois de o Premiere avisar que algo foi importado.
    """
    global _clipes
    projeto = projeto_aberto()
    if projeto == _escopo.SEM_PROJETO:
        return projeto, {}, "não há projeto aberto no Premiere"
    with _trava_do_recorte:
        if (not forcar and _clipes is not None and _clipes[0] == projeto
                and time.time() - _clipes[1] < VALIDADE_DO_RECORTE_S):
            return projeto, dict(_clipes[2]), ""
    # ⭐ O relógio POR DENTRO (2026-09-23): a rota mediu 43,8 s nesta fase com o cache
    #   quente, contra 3,7 s que o laço por arquivo custa medido à parte. A diferença tem
    #   de estar na PONTE ou no laço, e adivinhar já errou uma vez.
    t0 = time.monotonic()
    try:
        resposta = _midias()
    except (ponte.PremiereIndisponivel, ponte.ExtendScriptFalhou) as e:
        log.warning("não consegui listar a mídia do projeto (%s)", e)
        return projeto, {}, f"não consegui ler o projeto do Premiere: {e}"
    t_ponte = time.monotonic() - t0
    itens = resposta.get("itens")
    if not isinstance(itens, list):
        # ⚠️ `host.jsx` de antes de 2026-09-22 (painel sem Reload): só os caminhos.
        itens = [{"arquivo": a} for a in resposta.get("arquivos") or []]

    # ⭐ A varredura do índice do cache, UMA vez para o projeto inteiro. Ela é o que
    #   `_clipe_do_arquivo` precisa ter em mãos, e fazê-la por arquivo era o custo desta
    #   fase inteira (ver o comentário lá).
    _cache.indice().varrer()
    clipes: dict[str, dict[str, Any]] = {}
    for item in itens:
        if not isinstance(item, dict) or not item.get("arquivo"):
            continue
        bins = [str(b) for b in item.get("bins") or [] if isinstance(b, str)]
        chave, clipe = _clipe_do_arquivo(str(item["arquivo"]), str(item.get("nome") or ""),
                                         bins)
        if chave in clipes:
            # Dois arquivos que já são a MESMA entrada (um proxy, uma cópia): uma linha.
            clipes[chave]["bins"] = sorted(set(clipes[chave]["bins"]) | set(clipe["bins"]))
            continue
        clipes[chave] = clipe
    with _trava_do_recorte:
        _clipes = (projeto, time.time(), clipes)
    log.info("clipes do Premiere: %d item(ns) em %.2f s — ponte: %.2f · por arquivo: %.2f",
             len(itens), time.monotonic() - t0, t_ponte,
             time.monotonic() - t0 - t_ponte)
    return projeto, dict(clipes), ""


# ── organizar o projeto (escrita) ────────────────────────────────────────────

ACOES = ("criar_bin", "mover", "renomear", "apagar_bin_vazia")
#: Teto de operações num plano. Um plano de 200 linhas não é revisável num cartão — e o
#: portão existe para o editor LER o que aprova (ADR 0008).
MAXIMO_DE_OPERACOES = 60


def arvore() -> list[dict[str, Any]]:
    """Todo item do projeto: nome, id, espécie e a bin em que está."""
    feito, r = _pelo_mcp("itens", mcp_nativo.arvore)
    if feito:
        return r
    return ponte.chamar("cicloArvore", prazo=60).get("itens") or []


#: ⛔⛔ O plano viaja como texto TABULADO, uma operação por linha. Um nome com tabulação ou
#: quebra de linha viraria OUTRA operação — uma que o cartão não mostrou ao editor. Não é
#: execução de código (nada aqui vira ExtendScript); é pior de perceber: ele aprova três
#: linhas e acontecem quatro.
_SEPARADORES = re.compile(r"[\t\r\n]")


def _campo_do_plano(valor: Any) -> str:
    return _SEPARADORES.sub(" ", str(valor or "")).strip()


def _texto_da_operacao(op: dict[str, Any]) -> str:
    """Uma operação → `acao\talvo\tdestino`. ⛔ Formato burro: nome com vírgula, aspas ou
    acento não quebra nada, e nada do que o modelo escreve vira código (ADR 0005)."""
    acao = str(op.get("acao") or "")
    if acao == "criar_bin":
        return (f"criar_bin\t{_campo_do_plano(op.get('nome'))}"
                f"\t{_campo_do_plano(op.get('dentro_de'))}")
    if acao == "mover":
        return (f"mover\t{_campo_do_plano(op.get('item'))}"
                f"\t{_campo_do_plano(op.get('para'))}")
    if acao == "apagar_bin_vazia":
        return f"apagar_bin_vazia\t{_campo_do_plano(op.get('item'))}\t"
    return (f"renomear\t{_campo_do_plano(op.get('item'))}"
            f"\t{_campo_do_plano(op.get('nome'))}")


def conferir_organizacao(operacoes: Any) -> str:
    """O que está errado no plano, ou vazio. Roda ANTES do cartão (`registro.ferramenta`).

    ⭐ O editor nunca aprova algo para ver falhar: um plano com item que não existe, bin
    dentro dela mesma ou nome vazio volta ao modelo com o motivo, e ele corrige.
    """
    if not isinstance(operacoes, list) or not operacoes:
        return f"Diga as operações: uma lista de {', '.join(ACOES)}."
    if len(operacoes) > MAXIMO_DE_OPERACOES:
        return (f"{len(operacoes)} operações é mais do que o editor consegue revisar num "
                f"cartão. Faça em lotes de até {MAXIMO_DE_OPERACOES}.")
    # ⛔⛔ E a ponte que FALHA aqui não vira "plano ruim": o portão trata qualquer texto como
    #    recusa, e o modelo leria `NAO_MOSTRADO` ("conserte e peça de novo") por um painel
    #    recarregado — que ele não tem como consertar, e o cartão nunca chegaria ao editor.
    #    Conferência que quebra deixa passar (regra da casa); quem barra é o plano errado.
    itens = arvore()

    por_id = {str(i.get("id")): i for i in itens}
    caminhos = {(f"{i['bin']}/{i['nome']}" if i.get("bin") else str(i.get("nome"))): i
                for i in itens if i.get("especie") == "bin"}
    #: Bins que o próprio plano cria — mover para elas é legítimo.
    nascendo: set[str] = set()
    #: ⭐⭐ Quantos itens cada bin tem **depois das operações anteriores DESTE plano**, e
    #: onde cada item está. Sem simular, "tire os clipes da pasta do cartão e apague a
    #: pasta" seria impossível num plano só: na foto do começo a pasta ainda está cheia.
    quantos: dict[str, int] = {}
    onde: dict[str, str] = {}
    apagadas: set[str] = set()
    problemas: list[str] = []

    for i in itens:
        mae = str(i.get("bin") or "")
        quantos[mae] = quantos.get(mae, 0) + 1
        caminho = f"{mae}/{i['nome']}" if mae else str(i.get("nome"))
        quantos.setdefault(caminho if i.get("especie") == "bin" else mae, 0)
        onde[str(i.get("id"))] = mae
        if i.get("especie") == "bin":
            onde[caminho] = mae

    def bin_existe(ref: str) -> bool:
        if ref in apagadas:
            return False
        return (not ref or ref in nascendo or ref in caminhos
                or (ref in por_id and por_id[ref].get("especie") == "bin"))

    def caminho_de(ref: str) -> str:
        item = por_id.get(ref) or caminhos.get(ref)
        if not item:
            return ref
        return f"{item['bin']}/{item['nome']}" if item.get("bin") else str(item.get("nome"))

    for n, op in enumerate(operacoes, 1):
        if not isinstance(op, dict) or str(op.get("acao")) not in ACOES:
            problemas.append(f"{n}: a ação tem de ser {', '.join(ACOES)}")
            continue
        acao = str(op["acao"])
        # ⛔ Recusado ANTES do cartão: com tabulação ou quebra de linha, o plano ganharia
        #   uma operação a mais na hora de executar — e o editor teria aprovado outra coisa.
        sujos = [c for c in ("nome", "dentro_de", "item", "para")
                 if op.get(c) and _SEPARADORES.search(str(op[c]))]
        if sujos:
            problemas.append(f"{n}: {', '.join(sujos)} tem tabulação ou quebra de linha; "
                             f"escreva o nome numa linha só")
            continue
        if acao == "criar_bin":
            nome = str(op.get("nome") or "").strip()
            dentro = str(op.get("dentro_de") or "")
            if not nome:
                problemas.append(f"{n}: criar_bin sem nome")
            elif "/" in nome:
                problemas.append(f"{n}: nome de bin não leva barra ({nome!r}); "
                                 f"crie uma bin por vez e use dentro_de")
            elif not bin_existe(dentro):
                problemas.append(f"{n}: não achei a bin {dentro!r} para criar {nome!r} dentro")
            else:
                pai = caminho_de(dentro) if dentro else ""
                novo = f"{pai}/{nome}" if pai else nome
                nascendo.add(novo)
                quantos[novo] = 0
                quantos[pai] = quantos.get(pai, 0) + 1
                onde[novo] = pai
        elif acao == "mover":
            item = str(op.get("item") or "")
            para = str(op.get("para") or "")
            if item not in por_id and item not in caminhos:
                problemas.append(f"{n}: não achei o item {item!r} para mover")
            elif not bin_existe(para):
                problemas.append(f"{n}: não achei a bin {para!r} para mover {item!r} para dentro")
            else:
                de = caminho_de(item)
                destino = caminho_de(para) if para else ""
                # ⛔ Mover uma bin para dentro dela mesma (ou de uma filha) some com ela da
                #   árvore. O Premiere não reclama; o editor perde a bin.
                if destino == de or destino.startswith(de + "/"):
                    problemas.append(f"{n}: {de!r} não pode ir para dentro de si mesma")
                else:
                    saiu = onde.get(item, "")
                    quantos[saiu] = max(0, quantos.get(saiu, 0) - 1)
                    quantos[destino] = quantos.get(destino, 0) + 1
                    onde[item] = destino
        elif acao == "apagar_bin_vazia":
            item = str(op.get("item") or "")
            alvo = caminho_de(item) if (item in por_id or item in caminhos) else item
            if not bin_existe(item):
                problemas.append(f"{n}: não achei a bin {item!r} para apagar")
            elif quantos.get(alvo, 0) > 0:
                # ⭐ Depois das operações anteriores DESTE plano: tirar os clipes e apagar a
                #   pasta na mesma lista é o caso comum, e tem de ser possível.
                problemas.append(f"{n}: a bin {alvo!r} ainda tem {quantos[alvo]} item(ns) "
                                 f"quando chegar a vez dela; tire-os antes, na mesma lista")
            else:
                apagadas.add(alvo)
                apagadas.add(item)
                mae = onde.get(alvo, "")
                quantos[mae] = max(0, quantos.get(mae, 0) - 1)
        else:
            item = str(op.get("item") or "")
            nome = str(op.get("nome") or "").strip()
            if item not in por_id and item not in caminhos:
                problemas.append(f"{n}: não achei o item {item!r} para renomear")
            elif not nome:
                problemas.append(f"{n}: renomear sem nome novo")

    if not problemas:
        return ""
    return ("Esse plano não dá para executar:\n- " + "\n- ".join(problemas)
            + "\nConfira os ids em listar_itens_do_premiere e refaça.")


def organizar(operacoes: list[dict[str, Any]]) -> dict[str, Any]:
    """Executa o plano no Premiere. Devolve o que aconteceu, operação a operação."""
    feito_mcp, feito = _pelo_mcp("itens", lambda: mcp_nativo.organizar(operacoes))
    if not feito_mcp:
        traduzidas = [dict(op, **{c: _ref_para_cep(op[c]) for c in ("item", "para", "dentro_de") if op.get(c)})
                      for op in operacoes]
        plano = "\n".join(_texto_da_operacao(op) for op in traduzidas)
        feito = ponte.chamar("cicloOrganizar", plano, prazo=120)
    feitos = feito.get("feitos") or []
    falharam = [f for f in feitos if f.get("erro")]
    return {"operacoes": len(operacoes), "feitas": len(feitos) - len(falharam),
            "detalhe": feitos, "falharam": falharam}
