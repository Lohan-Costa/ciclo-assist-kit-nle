"""Sincronizar uma diária — pelo Sincronizar, que é quem sabe fazer isso.

⭐⭐ **O Ciclo Assist orquestra; o Sincronizar processa** (plano em
`DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md`). O que esta ferramenta acrescenta é o que falta lá:
**escolher o material pela conversa**. O editor diz "sincroniza a diária 02", e o material
sai das bins que o modelo declarou fonte a fonte (`fontes`: uma por câmera, uma por gravador) e vai
para o motor dele. ⛔ Quem diz o que é câmera é quem pediu (plano `2026-11-08-aba-sincronizar.md`): o palpite pelo nome falhava
sempre que o material fugia do de teste.

⛔ **A montagem da sequência é do painel do Sincronizar** — montar por conta própria seria a
segunda implementação da mesma coisa, e a primeira está validada em produção. Desde
2026-09-18 a ponte ALCANÇA esse painel (`POST /api/v1/nlejob`, escrito do lado de lá):
pedimos o sync, mandamos montar e esperamos o painel dizer que a sequência nasceu. Antes
disso o trabalho parava no mapa, a três cliques do fim.

⚠️⚠️ **O painel do Sincronizar precisa estar ABERTO no Premiere**, e isso é conferido ANTES do
cartão: o CEP só roda com o painel aberto, e é o poll dele que vem buscar o trabalho. Sem
ele, o pedido é recusado com a frase que diz o que fazer — em vez de o editor esperar
minutos por um sync cuja sequência ninguém vai montar.

⭐⭐ **No Media Composer o caminho é outro, e mais curto** (2026-10-22, para a demo de 23/10):
não há painel do Sincronizar dentro do MC. Ele lê as bins pelo 9100, sincroniza e AUTORA a bin
sincronizada no projeto aberto — um pedido só (`POST /api/v1/avid/sincronizar`, contrato em
`DRAMASYNC/.dev/PONTE-CICLO-ASSIST.md` §8). Ali `bin` é a PASTA do projeto do MC que contém
as bins das fontes (uma bin = uma fonte: CAM A, SOM DIRETO…).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from ... import nle as _nle
from ... import sincronizar as _sinc
from ...avid import salvar as _salvar
from ...avid.mcapi import McApiErro, MediaComposer
from ...nle import premiere as _premiere
from ...nle.premiere import ponte as _ponte
from ...servico import pendencias as _pendencias
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.sincronizar")

#: O que segue o sync no MC: nada, os subclipes numa bin só, ou uma bin por cena.
SUBCLIPES = ("nao", "uma_bin", "por_cena")

#: Extensões que o Sincronizar aceita como mídia (espelho de `SINC_MEDIA_EXT` no painel dele).
MIDIA = {".mp4", ".mxf", ".mov", ".avi", ".mkv", ".mts", ".m2ts", ".m2t", ".r3d", ".braw",
         ".wav", ".aac", ".mp3", ".aiff"}


def _arquivos_da_bin(bin: str) -> list[str]:
    """Os arquivos de mídia daquela bin e das filhas dela, sem repetir."""
    from pathlib import Path

    itens = _premiere.arvore()
    if bin:
        itens = [i for i in itens
                 if i.get("bin") == bin or str(i.get("bin") or "").startswith(bin + "/")]
    caminhos: list[str] = []
    for i in itens:
        arquivo = str(i.get("arquivo") or "")
        # ⚠️ Sequência, camada de ajuste e título têm `arquivo` vazio ou não são mídia: o
        #   Sincronizar receberia caminho que não abre, e a diária dele nasceria torta.
        if arquivo and Path(arquivo).suffix.lower() in MIDIA and arquivo not in caminhos:
            caminhos.append(arquivo)
    return caminhos


def _existe(arquivo: str) -> bool:
    """O arquivo está no disco? (Ponto único para os testes, que usam caminhos de mentira.)"""
    return Path(arquivo).exists()


#: O áudio solto: o que entra em fonte de som quando a bin mistura vídeo e WAV. Vídeo com áudio embutido é câmera.
AUDIO_SOLTO = {".wav", ".aiff", ".aif", ".mp3", ".aac"}

#: ⭐ A resposta a um pedido sem fontes. O modelo lê isto antes do cartão, e é por ela que ele vai olhar ou perguntar.
FALTAM_FONTES = ("Diga as fontes em `fontes`: uma por câmera e uma por gravador, cada uma com `tipo` (camera ou som), "
                 "`nome` e as `bins` ou os `arquivos` dela. Clipes de bins diferentes da mesma câmera vão na MESMA fonte. Veja "
                 "os nomes em arvore_do_premiere; se ainda houver dúvida do que é cada coisa, pergunte ao editor. Não adivinhe.")


def _kind(tipo: str) -> str:
    return "sound" if str(tipo).lower() == "som" else "camera"


def fontes_do_pedido(pedidas: list[dict] | None) -> dict[str, object]:
    """As `fontes` do modelo → `{fontes, offline}` ou `{erro}`. Comum a `sincronizar` e `criar_merged`.

    ⭐ Uma mesma bin pode entrar nas duas fontes (câmera e som): cada uma pega só o que é do tipo dela."""
    if not pedidas:
        return {"erro": FALTAM_FONTES}
    fontes: list[dict] = []
    offline: list[str] = []
    vistos: set[str] = set()
    n_cam = n_som = 0
    for pedida in pedidas:
        if not isinstance(pedida, dict) or str(pedida.get("tipo") or "").lower() not in ("camera", "som"):
            return {"erro": "Cada fonte precisa de `tipo`: camera ou som. " + FALTAM_FONTES}
        kind = _kind(pedida["tipo"])
        bins = [str(b) for b in (pedida.get("bins") or []) if str(b).strip()]
        soltos = [str(a) for a in (pedida.get("arquivos") or []) if str(a).strip()]
        if not bins and not soltos:
            return {"erro": f"A fonte '{pedida.get('nome') or kind}' veio sem `bins` e sem `arquivos`."}
        arquivos: list[str] = []
        for b in bins:
            for a in _arquivos_da_bin(b):
                if (kind == "sound") == (Path(a).suffix.lower() in AUDIO_SOLTO) and a not in arquivos:
                    arquivos.append(a)
        arquivos += [a for a in soltos if a not in arquivos]
        repetidos = [a for a in arquivos if a in vistos]
        if repetidos:
            return {"erro": f"{Path(repetidos[0]).name} está em duas fontes. Cada clipe é de uma fonte só."}
        vistos.update(arquivos)
        # ⛔ Item OFFLINE (o arquivo sumiu do disco) derrubava o sync INTEIRO com "arquivo não encontrado", sem
        #   dizer qual (P6 da diária no Premiere, 2026-11-07: 12 offline e 12 bons na mesma bin). Fica de fora,
        #   e é dito.
        fora = [a for a in arquivos if not _existe(a)]
        offline += fora
        arquivos = [a for a in arquivos if a not in fora]
        if kind == "sound":
            n_som += 1
            automatico = "SOM DIRETO" if n_som == 1 else f"SOM DIRETO {n_som}"
        else:
            n_cam += 1
            automatico = "CAM " + chr(64 + n_cam)
        rotulo = str(pedida.get("nome") or "").strip() or automatico
        if rotulo in {f["shape"] for f in fontes}:
            rotulo = f"{rotulo} {len(fontes) + 1}"
        if arquivos:
            fontes.append({"kind": kind, "shape": rotulo, "files": arquivos, "count": len(arquivos)})
    if offline and not fontes:
        return {"erro": f"todos os {len(offline)} arquivo(s) das fontes estão OFFLINE (o arquivo não está no disco): "
                         + ", ".join(Path(a).name for a in offline[:5])}
    if len(fontes) < 2:
        return {"erro": f"O sync precisa de pelo menos duas fontes com mídia (câmera e som), e achei {len(fontes)}. "
                        "Confira as bins em arvore_do_premiere."}
    return {"fontes": fontes, "offline": offline}


def resumo_das(fontes: list[dict]) -> list[dict[str, object]]:
    return [{"tipo": f.get("kind"), "padrao": f.get("shape"), "clipes": f.get("count")} for f in fontes]


def rodar_sync(fontes: list[dict], metodo: str) -> tuple[str, dict, list[dict]]:
    """Manda sincronizar e espera: `(job, resultado, clipes)`. As exceções do Sincronizar sobem."""
    clipes = [{"path": arquivo, "group": str(f.get("shape") or f.get("kind") or "fonte"),
               "kind": f.get("kind")}
              for f in fontes for arquivo in (f.get("files") or [])]
    job = _sinc.sincronizar(clipes, metodo=_sinc.METODOS.get(metodo, "hybrid"))
    log.info("sync do Sincronizar começou (%s, %d clipes)", job, len(clipes))

    def contando(etapa: str, fracao: float | None) -> None:
        _turno.avisar("o Sincronizar está sincronizando", fracao, etapa)

    resultado = _sinc.esperar(job, relatar=contando,
                                conferir=lambda: _pendencias.conferir_cancelamento("o sync do Sincronizar"))
    return job, resultado, clipes


def offline_de_fora(offline: list[str]) -> dict[str, object]:
    return {"quantos": len(offline), "exemplos": [Path(a).name for a in offline[:5]],
            "aviso": f"{len(offline)} item(ns) OFFLINE na bin ficaram fora do sync — diga ao editor"}


def _no_avid() -> bool:
    return _nle.atual() == _nle.AVID


def _chave(texto: str) -> str:
    """A bin como o Sincronizar a conhece: relativa ao projeto, sem `.avb`, com `/`."""
    t = str(texto).replace("\\", "/").strip().strip("/")
    return t[:-4] if t.lower().endswith(".avb") else t


def bins_do_projeto_aberto() -> list[str] | None:
    """As bins do projeto aberto no MC, como o Sincronizar as chama; None se não dá para saber.

    ⚠️ Do DISCO (instantâneo, sem abrir nada na tela do editor). Bin criada agora no MC e ainda
    não salva pode faltar — a recusa diz isso."""
    from ...avid import bins as _bins
    from ...avid import escopo as _escopo
    try:
        caminho = _escopo.projeto_aberto()
    except Exception:  # noqa: BLE001
        return None
    if not caminho or caminho == _escopo.SEM_PROJETO:
        return None
    raiz = Path(caminho)
    chaves = []
    for b in _bins.bins_do_projeto(raiz):
        try:
            chaves.append(_chave(str(b.relative_to(raiz))))
        except ValueError:
            continue
    return chaves or None


def _conferir_bins_no_avid(pasta: str, bins: list[str]) -> str:
    """A pasta ou as bins pedidas existem no projeto? Senão, a lista das que existem.

    ⛔⛔ O caso do autor (2026-11-01): as bins da diária na RAIZ do projeto, e o modelo, só
    com "pasta", mandou o NOME DO PROJETO e depois o caminho dele — duas idas ao Sincronizar, minutos
    de espera e "não há bin na pasta". Aqui a recusa chega antes do cartão, com o que há."""
    existentes = bins_do_projeto_aberto()
    if existentes is None:
        return ""                      # sem como saber: o Sincronizar confere do lado dele
    minusc = {b.lower(): b for b in existentes}
    if bins:
        faltam = [b for b in bins if _chave(b).lower() not in minusc]
        if not faltam:
            return ""
        motivo = f"não achei no projeto aberto a(s) bin(s) {', '.join(faltam)}"
    else:
        alvo = _chave(pasta).lower()
        if any(k == alvo or k.startswith(alvo + "/") for k in minusc):
            return ""
        motivo = f"não há bin dentro da pasta '{pasta}' do projeto aberto"
    lista = ", ".join(sorted(existentes, key=str.casefold)[:40])
    return (f"{motivo}. As bins do projeto são: {lista}. Peça de novo com `bins` = a lista das bins "
            "da diária (as de câmera e as de som, como escritas aqui — as da raiz não têm pasta), "
            "ou com `bin` = a PASTA que as contém. Se uma bin acabou de ser criada no Media "
            "Composer e não aparece aqui, ela ainda não foi salva no disco.")


def _erro_das_fontes_no_avid(fontes: list[dict]) -> str:
    for f in fontes:
        if not isinstance(f, dict) or str(f.get("tipo") or "").lower() not in ("camera", "som") or not f.get("bins"):
            return "No Media Composer cada fonte precisa de `tipo` (camera ou som) e das `bins` dela."
    return ""


def _bins_das_fontes(fontes: list[dict] | None) -> list[str]:
    return [str(b) for f in (fontes or []) if isinstance(f, dict) for b in (f.get("bins") or [])]


def _conferir(bin: str = "", so_preparar: bool = False, subclipes: str = "nao",
              bins: list[str] | None = None, fontes: list[dict] | None = None, **_) -> str:
    """Roda ANTES do cartão: sem Sincronizar, sem material ou com ele ocupado, nem mostra."""
    try:
        saude = _sinc.saude()
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return str(e)
    if saude.get("busy"):
        return ("O Sincronizar está ocupado com outro trabalho (ele atende um por vez). Espere "
                "ele terminar e peça de novo.")
    if so_preparar:
        # ⛔ O Studio (aposentado) (a janela que recebia o material "só preparado") foi aposentado (autor, 2026-11-06;
        #   plano um app só). A conferência do agrupamento é a aba Preparar, e o sync é um passo só.
        return ("Não há mais 'só preparar': a janela do Studio (aposentado) foi aposentada. O agrupamento se "
                "confere na aba Preparar, e daqui o Sincronizar agrupa e sincroniza num passo só. Peça sem "
                "so_preparar.")
    if _no_avid():
        if fontes:
            ruim = _erro_das_fontes_no_avid(fontes)
            if ruim:
                return ruim
            bins = _bins_das_fontes(fontes)
        if not bin.strip() and not bins:
            return ("Diga as `fontes` da diária (uma por câmera, uma por gravador, cada uma com as `bins` dela), as bins "
                    "(`bins`, ex.: [\"D02 CAM\", \"D02 SOM\"]) ou a pasta do "
                    "projeto do Media Composer que as contém (`bin`, ex.: D02).")
        try:
            recusa = _sinc.pode_sincronizar_no_avid()
        except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
            return str(e)
        return recusa or _conferir_bins_no_avid(bin, list(bins or []))
    if subclipes not in ("", "nao"):
        # No Premiere o equivalente é o merged clip, e a ponte ainda não o pede.
        return ("Subclipar pela conversa só existe no Media Composer. No Premiere, peça "
                "sem subclipes e use o Merge do painel do Sincronizar.")
    # ⚠️⚠️ O painel dele é quem monta a sequência, e o sync leva MINUTOS: descobrir a
    #   ausência no fim seria fazer o editor esperar por nada. Aqui a recusa chega antes
    #   do cartão.
    if not so_preparar:
        try:
            if not _sinc.tem_painel("premiere"):
                return ("Não dá para montar a sequência: " + _sinc.FALTA_A_PREPARAR)
        except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
            return str(e)
    try:
        return str(fontes_do_pedido(fontes).get("erro") or "")
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return str(e)


def resumo_para_o_revisor(fontes: list[dict] | None = None, bins: list[str] | None = None, bin: str = "", **_) -> list[dict]:
    """O que o revisor do fluxo olha (`motor/revisor_do_sync.py`): cada fonte, com bins e uma amostra dos nomes."""
    if _no_avid():
        if fontes:
            return [{"tipo": f.get("tipo"), "nome": f.get("nome"), "bins": f.get("bins")} for f in fontes]
        return [{"tipo": "uma bin, uma fonte", "bins": list(bins or []) or [bin]}]
    achado = fontes_do_pedido(fontes)
    if achado.get("erro"):
        raise ValueError(str(achado["erro"]))
    return [{"tipo": "som" if f["kind"] == "sound" else "camera", "nome": f["shape"], "clipes": f["count"],
             "nomes": [Path(a).name for a in f["files"][:15]]} for f in achado["fontes"]]


@ferramenta(
    nome="sincronizar",
    descricao=(
        "Sincroniza uma diária pelo Sincronizar: som direto com imagem, por timecode e forma de "
        "onda. Use quando o editor pedir para sincronizar uma diária; o sync leva minutos. "
        "Declare as `fontes`: uma por câmera e uma por gravador, olhando caminhos e bins; clipes de bins diferentes da "
        "mesma câmera (cartão 1 e cartão 2) vão na MESMA fonte, e na dúvida pergunte ao editor. "
        "No MEDIA COMPOSER: cada fonte traz as `bins` dela, relativas ao projeto (as da RAIZ, como escritas); `bins` "
        "(cada bin, uma fonte) e a PASTA em `bin` (ex.: D02 — nunca o nome do projeto) continuam valendo quando cada "
        "bin é mesmo uma fonte; o Sincronizar lê essas bins, sincroniza e cria uma bin "
        "nova com a sequência sincronizada no projeto aberto. No PREMIERE: cada fonte traz as `bins` ou os `arquivos` "
        "(a mesma bin pode servir à câmera e ao som: cada uma pega só o seu tipo); o Sincronizar "
        "sincroniza, e a aba Preparar monta a sequência no projeto. Devolve os números: "
        "quantas câmeras, quantos takes casaram, o que ficou órfão e o nome do que foi "
        "criado. subclipes (só no Media Composer) "
        "segue o sync no MESMO pedido: cada take da sequência vira um subclipe com o NOME DO VÍDEO "
        "original (cena, plano e take só se o editor pedir: ver padrao), numa bin só ou numa bin por cena "
        "(pasta CENAS). Se o editor deu nome à bin dos subclipes (ou à pasta das cenas), passe-o em "
        "bin_dos_subclipes. Com por_cena, no fim "
        "o projeto é salvo pelo gesto na tela (foco na timeline + Ctrl+S) para a pasta aparecer no "
        "painel de bins — o resultado diz em painel_de_bins se salvou."
    ),
    esquema={
        "type": "object",
        "properties": {
            "fontes": {"type": "array",
                       "description": "As fontes da diária: uma por câmera, uma por gravador. No Premiere é obrigatório.",
                       "items": {"type": "object", "required": ["tipo"], "properties": {
                           "tipo": {"type": "string", "enum": ["camera", "som"]},
                           "nome": {"type": "string", "description": "Como chamar a fonte (CAM A, SOM DIRETO…). Vazio = automático."},
                           "bins": {"type": "array", "items": {"type": "string"},
                                    "description": "As bins desta fonte, como a árvore do projeto mostrou."},
                           "arquivos": {"type": "array", "items": {"type": "string"},
                                        "description": "Só Premiere: caminhos soltos desta fonte."}}}},
            "bin": {"type": "string",
                    "description": "Só Media Composer: a PASTA do projeto com as bins da diária (ex.: D02), quando cada bin é uma fonte."},
            "bins": {"type": "array", "items": {"type": "string"},
                     "description": "Só Media Composer: as bins da diária, relativas ao projeto, sem .avb (ex.: [\"M07 CAM\", \"M07 SOM\"]). Use quando as bins não estão numa pasta própria."},
            "nome": {"type": "string",
                     "description": "Nome da diária. Sem ele, o nome da bin (no Media Composer, '<PASTA> SYNC')."},
            "metodo": {"type": "string", "enum": list(_sinc.METODOS),
                       "default": "hibrido",
                       "description": "hibrido (timecode + forma de onda), timecode ou forma_de_onda."},
            "so_preparar": {"type": "boolean", "default": False,
                            "description": "APOSENTADO (o Studio (aposentado) saiu): não use."},
            "subclipes": {"type": "string", "enum": list(SUBCLIPES), "default": "nao",
                          "description": "Só no Media Composer: nao, uma_bin, ou por_cena (uma bin por cena na pasta CENAS)."},
            "sem_supervisao": {"type": "boolean", "default": False,
                               "description": "Só num fluxo, e só se o editor pedir um fluxo SEM supervisão: tira o revisor de IA que confere as fontes antes do sync."},
            "bin_dos_subclipes": {"type": "string",
                                  "description": "Só no Media Composer: o nome que o editor deu à bin dos subclipes (uma_bin) ou à PASTA das bins por cena (por_cena). Use o nome EXATO do pedido; vazio = '<diária> SUBCLIPES' / 'CENAS'."},
            "padrao": {"type": "string", "default": _sinc.PADRAO_DE_SUBCLIPE,
                       "description": "O nome dos subclipes, nos tokens do Sincronizar: %{nomedevideo} (o nome do vídeo original), %{nomedoaudio}, %{cena}, %{plano}, %{take}, %{take2}. Deixe vazio para o padrão de fábrica, o NOME DO VÍDEO ORIGINAL. Use cena/plano/take (" + _sinc.PADRAO_CENA_PLANO_TAKE + ") SÓ quando o editor pedir esse nome."},
        },
        "required": [],
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
)
def sincronizar(bin: str = "", nome: str = "", metodo: str = "hibrido",
                             so_preparar: bool = False, subclipes: str = "nao",
                             padrao: str = "", bins: list[str] | None = None,
                             bin_dos_subclipes: str = "", fontes: list[dict] | None = None,
                             sem_supervisao: bool = False) -> dict[str, object]:
    if _no_avid():
        return _sincronizar_no_avid(bin, nome, metodo, subclipes,
                                    padrao or _sinc.PADRAO_DE_SUBCLIPE, bins=list(bins or []),
                                    bin_dos_subclipes=bin_dos_subclipes, fontes=fontes)
    rotulo = nome or next((str(b).rsplit("/", 1)[-1] for f in (fontes or []) if isinstance(f, dict)
                           for b in (f.get("bins") or [])), "PROJETO")
    try:
        achado = fontes_do_pedido(fontes)
        if achado.get("erro"):
            return achado
        lidas, offline = achado["fontes"], achado["offline"]
        resumo_das_fontes = resumo_das(lidas)

        if so_preparar:  # o portão já recusa; quem chamar direto recebe a mesma frase
            return {"erro": _conferir(bin=bin, so_preparar=True) or "o Studio (aposentado) foi aposentado"}

        job, resultado, clipes = rodar_sync(lidas, metodo)
        # ⭐ O rótulo de cada arquivo é o que separa as câmeras em trilhas e nomeia as
        #   sub-bins do outro lado. Quem os tem é quem classificou — nós.
        rotulos = {c["path"]: c["group"] for c in clipes}
    except _sinc.SincronizarOcupado as e:
        return {"erro": str(e), "ocupado": True}
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return {"erro": str(e)}
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return {"erro": str(e)}

    resumo = _sinc.resumo_do_mapa(resultado)
    comum: dict[str, object] = {"metodo": metodo, "fontes": resumo_das_fontes, **resumo}
    if offline:
        comum["offline_de_fora"] = offline_de_fora(offline)

    # ⭐⭐ O sync acabou; falta a sequência. Daqui em diante NADA pode apagar o mapa: ele
    #    custou minutos de máquina, e toda saída abaixo o carrega junto com o que houve.
    try:
        montagem = _sinc.mandar_montar(job, nome=rotulo, rotulos=rotulos)
        _turno.avisar("o Sincronizar está montando a sequência", None, rotulo)
        fim = _sinc.esperar_montagem(montagem)
    except _sinc.SincronizarSemPainel as e:
        # ⚠️ O painel fechou ENTRE a conferência e agora. O sync não se perde.
        return {**comum, "feito": f"sync de {rotulo} feito, mas a sequência não foi montada",
                "falta_montar": f"{e} O mapa está pronto: é só pedir de novo com o painel aberto, "
                                f"ou montar por ele (Exportar → Premiere (plugin))."}
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return {**comum, "feito": f"sync de {rotulo} feito, mas a sequência não foi montada",
                "falta_montar": f"{e}"}

    if fim.get("estado") != "feito":
        # ⚠️ O painel tentou e falhou: o motivo é DELE e vai inteiro, sem tradução — quem
        #   vai ler é o editor, que conhece aquelas mensagens do painel.
        return {**comum, "feito": f"sync de {rotulo} feito, mas a montagem falhou",
                "erro_da_montagem": str(fim.get("resumo") or "o painel não disse o motivo")}

    return {
        **comum,
        "feito": f"sync de {rotulo} feito, e a aba Preparar montou a sequência",
        # ⚠️ Dito em palavras, porque o modelo lê a resposta e não o nosso código.
        "agora": (f"A sequência '{rotulo}' está no projeto do Premiere, montada pelo Sincronizar "
                  f"(aba Preparar). Diga ao editor que ela já está lá."),
    }


def nome_das_bins(bins: list[str]) -> str:
    """O nome da diária quando não há pasta: o começo comum das bins ("M07 CAM", "M07 SOM" → "M07")."""
    nomes = [_chave(b).rsplit("/", 1)[-1] for b in bins if b]
    comum = os.path.commonprefix(nomes).strip(" _-") if len(nomes) > 1 else ""
    return f"{comum or 'DIARIA'} SYNC"


def _sincronizar_no_avid(pasta: str, nome: str, metodo: str, subclipes: str = "nao",
                         padrao: str = _sinc.PADRAO_DE_SUBCLIPE,
                         bins: list[str] | None = None,
                         bin_dos_subclipes: str = "", fontes: list[dict] | None = None) -> dict[str, object]:
    """O caminho do Media Composer: um pedido ao Sincronizar, que lê, sincroniza e monta.

    Com `subclipes`, a sequência recém-criada segue para a aba Subclipar dele, no mesmo
    cartão: o editor aprovou o trabalho inteiro, e pedir de novo no meio seria fazê-lo
    esperar o sync para dar o segundo clique.
    """
    pasta = pasta.strip()
    bins_pedidas = [_chave(b) for b in (_bins_das_fontes(fontes) or bins or []) if str(b).strip()]
    if bins_pedidas and not nome:
        nome = nome_das_bins(bins_pedidas)
    origem = f"as bins {', '.join(bins_pedidas)}" if bins_pedidas else f"a pasta {pasta}"
    try:
        _turno.avisar("falando com o Sincronizar", None, f"{origem} do Media Composer")
        job = _sinc.sincronizar_no_avid(
            pasta, metodo=_sinc.METODOS.get(metodo, "hybrid"), nome=nome, bins=bins_pedidas, fontes=fontes)
        log.info("sync do Sincronizar no MC começou (%s, %s)", job, origem)

        def contando(etapa: str, fracao: float | None) -> None:
            _turno.avisar("o Sincronizar está sincronizando", fracao, etapa)

        resultado = _sinc.esperar(job, relatar=contando,
                                   conferir=lambda: _pendencias.conferir_cancelamento("o sync do Sincronizar"))
    except _sinc.SincronizarOcupado as e:
        return {"erro": str(e), "ocupado": True}
    except (_sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        return {"erro": str(e)}

    resumo = _sinc.resumo_do_mapa(resultado.get("mapa") or {})
    montagem = resultado.get("montagem") or {}
    nomes = [str(n) for n in (montagem.get("names") or []) if n]
    sequencia = nomes[0] if nomes else ""
    saida: dict[str, object] = {
        "metodo": metodo,
        "fontes": [{"fonte": f.get("label"), "tipo": f.get("kind"), "clipes": f.get("clipes")}
                   for f in (resultado.get("fontes") or []) if isinstance(f, dict)],
        "bins_lidas": resultado.get("bins") or [],
        **resumo,
        "sequencia": sequencia,
        "feito": f"sync de {origem} feito, com uma bin nova para a sequência no "
                 f"projeto do Media Composer",
        # ⚠️ No 24.6 a timeline fica em branco até o duplo clique na sequência (handoff do
        #   Sincronizar, 21/10): sem a frase, "não apareceu nada" se lê como falha.
        "agora": (f"A sequência '{sequencia or 'sincronizada'}' está numa bin nova do projeto "
                  f"aberto. Para vê-la na timeline, dê duplo clique nela na bin."),
    }
    if resultado.get("faltando"):
        # Clipe que está na bin e não tem mídia: o editor precisa saber, não descobrir.
        saida["sem_midia"] = resultado["faltando"]
    if subclipes not in ("uma_bin", "por_cena"):
        return saida

    # ⭐⭐ Daqui em diante NADA apaga o sync: a sequência já está no projeto, e toda
    #    saída abaixo a carrega junto com o que houve nos subclipes.
    bin_sync = str(montagem.get("path") or "")
    if not bin_sync:
        saida["subclipes_falharam"] = "o Sincronizar não disse onde gravou a bin sincronizada"
        return saida
    try:
        def subclipando(etapa: str, fracao: float | None) -> None:
            _turno.avisar("o Sincronizar está criando os subclipes", fracao, etapa)

        sub = _sinc.subclipar_no_avid(bin_sync, padrao=padrao,
                                        por_cena=subclipes == "por_cena",
                                        nome_da_bin=bin_dos_subclipes, relatar=subclipando)
    except (_sinc.SincronizarOcupado, _sinc.SincronizarIndisponivel, _sinc.SincronizarFalhou) as e:
        saida["subclipes_falharam"] = str(e)
        saida["agora"] = (f"{saida['agora']} Os subclipes NÃO foram criados: {e}. Dá para "
                          f"criá-los pela aba Subclipar do Sincronizar, arrastando a sequência.")
        return saida

    escrita = sub["escrita"]
    bins = [{"cena": b.get("cena"), "subclipes": b.get("takes")}
            for b in (escrita.get("bins") or []) if isinstance(b, dict)]
    saida["subclipes"] = {
        "padrao": padrao,
        "tomadas": len(sub["tomadas"]),
        "total": escrita.get("total", len(sub["tomadas"])),
        # Por cena: uma linha por bin. Numa bin só, o caminho dela.
        "bins_por_cena": bins,
        "bins": [str(c).replace("\\", "/").rsplit("/", 1)[-1] for c in escrita.get("caminhos") or []],
        "nao_resolvidos": escrita.get("nao_resolvidos", 0),
        "orfaos": escrita.get("orfaos", 0),
        "abertas_no_mc": bool(escrita.get("aberta")),
    }
    pasta_das_cenas = bin_dos_subclipes.strip() or "CENAS"
    bin_unica = (saida["subclipes"]["bins"] or [""])[0].removesuffix(".avb")
    if subclipes == "por_cena":
        onde = f"numa bin por cena, na pasta {pasta_das_cenas} do projeto"
    elif bin_unica:
        onde = f"na bin {bin_unica}, ao lado da sincronizada"
    else:
        onde = "numa bin de subclipes ao lado da sincronizada"
    saida["feito"] += f", e os subclipes ({padrao}) {onde}"
    if subclipes == "por_cena":
        saida["painel_de_bins"] = _mostrar_a_pasta_nova(bin_sync)
        if not saida["painel_de_bins"].get("salvou"):
            saida["agora"] = (f"{saida['agora']} Se a pasta {pasta_das_cenas} não aparecer no painel de bins, clique "
                              f"num vazio da timeline e aperte Ctrl+S.")
    return saida


def _mostrar_a_pasta_nova(bin_sync: str) -> dict[str, object]:
    """A pasta CENAS escrita pelo Sincronizar só aparece no painel de bins depois de um save (op. 8).

    ⛔ O Ctrl+S só grava com algo MODIFICADO, e o Sincronizar já salva cada bin pela API — MEDIDO
    pelo chat (2026-11-01): o save não gravou e a CENAS não apareceu. Por isso a bin do sync
    (que nasceu agora, na raiz) é deixada suja antes (`salvar.sujar`). ⛔ Falhar aqui não
    desfaz nada: o sync e as bins estão no disco.
    """
    try:
        with MediaComposer() as m:
            caminho = m.projeto(recarregar=True).get("caminho")
            if bin_sync:
                _turno.avisar("preparando o save (reabrindo a bin do sync)", None, "")
                _salvar.sujar(m, bin_sync)
        if not caminho:
            return {"salvou": False, "erro": "o Media Composer não disse qual é o projeto aberto"}
        _turno.avisar("salvando o projeto para a pasta CENAS aparecer", None, "")
        return _salvar.salvar_tudo(caminho, relatar=_turno.avisar)
    except (_salvar.SalvarFalhou, McApiErro, OSError) as e:
        log.info("a pasta CENAS não foi mostrada pelo save: %s", e)
        return {"salvou": False, "erro": str(e)}
