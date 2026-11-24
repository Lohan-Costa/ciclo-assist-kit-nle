"""`montar_corte` — o plano vira sequência na bin do editor.

⛔ **É a ferramenta que ESCREVE no projeto, e por isso passa pelo portão** (ADR 0003). O
que o editor aprova não é "posso importar este arquivo?" — é o plano inteiro, corte a
corte, com take, in/out e o porquê de cada escolha.

⚠️ Nenhum preset do Avid é tocado. A sequência é autorada como `.avb` e a bin é aberta com
`OpenBin`, que é rpc tipado. Ver `docs/spec/2026-09-10-corte-zero.md` §2 para a razão —
preset é configuração do usuário, e o nome dele mente.
"""

from __future__ import annotations

import logging
import re
import shutil
import tempfile
from pathlib import Path

from ...avid import timeline as _timeline
from ...avid.atributos import copiar_bin   # copy2 + o estado da bin no Mac
from ...avid.mcapi import TEMPO_DE_ARQUIVO_S, McApiErro, MediaComposer, relativo_ao_projeto
from ...avid.take import TakeErro, resolver
from ...plano import esquema as _plano
from ... import nle as _nle
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.corte")

#: Nome de arquivo de bin a partir do nome da sequência.
_NAO_SERVE = re.compile(r"[^A-Za-z0-9 _.-]+")

#: ⛔ **Nomes de DISPOSITIVO do Windows.** `CON`, `NUL`, `PRN`, `AUX`, `COM1..9` e
#: `LPT1..9` não são arquivos: escrever em `CON.avb` vai para o console, em `NUL.avb`
#: some, e alguns travam o processo. O nome da sequência vem do modelo, que pode
#: perfeitamente propor "CON" para uma cena de conversa — e o defeito seria um arquivo
#: que não existe, sem erro nenhum na escrita.
#:
#: ⚠️ A regra vale com QUALQUER extensão: `CON.avb` é tão reservado quanto `CON`.
_RESERVADOS = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def _nome_de_arquivo(nome: str) -> str:
    limpo = _NAO_SERVE.sub("_", nome).strip(" .") or "CORTE"
    if limpo.split(".")[0].upper() in _RESERVADOS:
        limpo = f"_{limpo}"
    return limpo[:60]


def _conferir_plano(bin: str = "", nome: str = "", cortes: list | None = None,
                    coberturas: list | None = None, **_resto) -> str:
    """A validação do plano, antes do cartão (`registro.conferir`). ⚠️ Só a forma, que não
    precisa do Media Composer: resolver os takes custa uma chamada por corte e continua na
    execução."""
    try:
        _plano.validar({"bin": bin, "nome": nome, "cortes": cortes or [],
                        "coberturas": coberturas or []})
    except _plano.PlanoInvalido as e:
        return f"plano recusado: {e}"
    return ""


@ferramenta(
    nome="montar_corte",
    descricao=(
        "Monta um primeiro corte no Avid ou no Premiere a partir de um plano de cortes, e "
        "abre a sequência numa bin do projeto. Cada corte diz o take, onde começar dentro "
        "dele, quantos frames usar, e POR QUE aquele take foi escolhido. Use depois de "
        "ouvir e ver o material, quando já souber que take serve para cada momento. O "
        "editor aprova o plano inteiro antes de qualquer coisa ser escrita.\n"
        "\n"
        "COMECE DEPOIS DA CLAQUETE. O início do take costuma ter claquete, o diretor "
        "gritando 'ação' e conversa de set — nada disso entra no corte. A transcrição "
        "mostra onde a cena começa de verdade; use esse ponto em inicio_no_take.\n"
        "\n"
        "CORTE SECO SEMPRE: corte em L/J fica com o editor. Não mande corte_de_som e não "
        "imite L/J estendendo a duração do plano anterior — a mesma fala tocaria duas vezes. "
        "Se achar que um L/J ajudaria, diga ao editor onde, em texto.\n"
        "\n"
        "ARTES COM ALPHA (os clipes 'Matte Key: ...' da bin — cartela, selo, legenda): vão "
        "em coberturas, nunca em cortes. Cada uma entra por cima da imagem, na V2, sobre o "
        "corte que o roteiro indicar."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {
                "type": "string",
                "description": "Caminho da bin de onde vêm os takes.",
            },
            "nome": {
                "type": "string",
                "description": "Nome da sequência, como vai aparecer na bin.",
            },
            "bin_da_sequencia": {
                "type": "string",
                "description": (
                    "Onde GRAVAR a sequência. Use a mesma bin da cena para as versões "
                    "ficarem juntas, onde o editor já olha — a sequência é acrescentada "
                    "sem apagar nada do que estiver lá. Se a bin estiver aberta no Media "
                    "Composer, ela é fechada e reaberta sozinha. Deixe vazio só quando "
                    "quiser uma bin nova, separada, com o nome da sequência."
                ),
            },
            "cortes": {
                "type": "array",
                "description": "Os cortes, na ordem em que entram na timeline.",
                "items": {
                    "type": "object",
                    "properties": {
                        "take": {"type": "string", "description": (
                            "Nome do clipe: subclipe ou masterclipe, gerenciado ou AMA."
                        )},
                        "inicio_no_take": {
                            "type": "integer",
                            "description": (
                                "Frame DENTRO do take em que o corte começa. 0 é do "
                                "início. É a mesma contagem que transcrever devolve em "
                                "inicio_no_take, convertida de segundos para frames."
                            ),
                            "default": 0,
                        },
                        "duracao_frames": {
                            "type": "integer",
                            "description": "Quantos frames usar. Frames, não segundos.",
                        },
                        "fala": {
                            "type": "string",
                            "description": "Que fala ou momento este corte cobre.",
                        },
                        "confianca": {
                            "type": "string",
                            "enum": list(_plano.CONFIANCAS),
                        },
                        "fonte": {"type": "string", "enum": list(_plano.FONTES)},
                        "medida": {
                            "type": "number",
                            "description": "O número que sustenta, quando houver.",
                        },
                        "porque": {
                            "type": "string",
                            "description": (
                                "Por que ESTE take, em prosa curta. O editor lê isto "
                                "para decidir."
                            ),
                        },
                    },
                    "required": ["take", "duracao_frames", "confianca", "fonte", "porque"],
                },
            },
            "coberturas": {
                "type": "array",
                "description": (
                    "Artes com alpha por cima da imagem (clipes 'Matte Key: ...' da bin). "
                    "Opcional."
                ),
                "items": {
                    "type": "object",
                    "properties": {
                        "arte": {"type": "string", "description": (
                            "Nome do clipe de matte key na bin, como listar_itens_da_bin "
                            "mostrou (tipo effects).")},
                        "sobre_o_corte": {"type": "integer", "description": (
                            "Sobre qual corte do plano ela entra (1 é o primeiro).")},
                        "deslocamento_frames": {"type": "integer", "default": 0,
                                                "description": (
                            "Quantos frames depois do começo daquele corte.")},
                        "duracao_frames": {"type": "integer", "description": (
                            "Quantos frames ela fica. Vazio: a arte inteira.")},
                        "inicio_na_arte": {"type": "integer", "default": 0},
                        "trilha": {"type": "string", "default": "V2"},
                        "confianca": {"type": "string", "enum": list(_plano.CONFIANCAS)},
                        "fonte": {"type": "string", "enum": list(_plano.FONTES)},
                        "porque": {"type": "string", "description": (
                            "Por que ela entra ali — a linha do roteiro, por exemplo.")},
                    },
                    "required": ["arte", "sobre_o_corte", "confianca", "fonte", "porque"],
                },
            },
        },
        "required": ["bin", "nome", "cortes"],
    },
    escreve=True,
    conferir=_conferir_plano,
    nles=AMBOS,
)
def montar_corte(bin: str, nome: str, cortes: list,
                 bin_da_sequencia: str = "", coberturas: list | None = None) -> dict[str, object]:
    # ⛔ A validação vem ANTES de tocar no projeto, e recusa o plano INTEIRO. Um plano
    #    aplicado pela metade deixa o editor com um estado que ninguém pediu.
    try:
        plano = _plano.validar({"bin": bin, "nome": nome, "cortes": cortes,
                                "coberturas": coberturas or []})
    except _plano.PlanoInvalido as e:
        return {"erro": f"plano recusado: {e}"}

    if _nle.qual() == _nle.PREMIERE:
        return _montar_no_premiere(plano, bin_da_sequencia)

    try:
        with MediaComposer() as mc:
            projeto = mc.projeto()
            raiz = Path(projeto["caminho"])
            caminho_da_bin = bin if Path(bin).is_absolute() else str(raiz / bin)

        entradas = []
        for i, c in enumerate(plano.cortes):
            take = resolver(caminho_da_bin, c.take)
            if getattr(take, "especie", "") == "matte":
                # ⛔ Um SourceClip na V1 apontando o efeito da bin NÃO é como o Media
                #    Composer põe um matte key na timeline (medido: `SEQ ANALISE`) — a arte
                #    vai por cima, como `TrackEffect`, pelas coberturas.
                return {"erro": (
                    f"{take.nome!r} é um clipe de matte key (arte com alpha): ele não vai em "
                    f"cortes, vai em coberturas, por cima da imagem.")}

            # ⭐⭐ O corte em L/J, em duas linhas. `desloca` é onde o som troca em relação
            #    à imagem: o que este plano perde no começo, o anterior já ganhou no fim
            #    — e vice-versa. Por isso a duração do som olha os DOIS lados, e as somas
            #    de imagem e som fecham iguais sem ninguém somar nada.
            #
            #    O validador do plano é quem garante que isso não cria buraco nem
            #    sobreposição (`plano/esquema._validar_o_som_entre_cortes`).
            desloca = c.desloca
            proximo = plano.cortes[i + 1].desloca if i + 1 < len(plano.cortes) else 0

            entradas.append(_timeline.Entrada(
                # ⭐ O MobID do SUBCLIPE. O matchframe do editor cai no take, e o
                #    `start_time` é posição DENTRO dele — nunca o offset do master, que
                #    somaria o recorte duas vezes.
                mob_id=take.mob_id,
                duracao=c.duracao_frames,
                trilhas=_timeline.trilhas_do_take(take),
                start_time=c.inicio_no_take,
                duracao_som=c.duracao_frames - desloca + proximo,
                start_som=c.inicio_no_take + desloca,
            ))

        artes = []
        for n, cob in enumerate(plano.coberturas, 1):
            arte = resolver(caminho_da_bin, cob.arte)
            if getattr(arte, "especie", "") != "matte":
                return {"erro": (
                    f"cobertura {n}: {arte.nome!r} não é um clipe de matte key (arte com "
                    f"alpha). Cobertura de vídeo comum ainda não é montada.")}
            duracao = cob.duracao_frames or (arte.duracao_frames - cob.inicio_na_arte)
            posicao = plano.inicio_do_corte(cob.sobre_o_corte) + cob.deslocamento_frames
            if posicao + duracao > plano.duracao_frames:
                return {"erro": (
                    f"cobertura {n} ({arte.nome}): com {duracao} frames ela passa do fim da "
                    f"sequência ({plano.duracao_frames}). Diga duracao_frames.")}
            artes.append(_timeline.Cobertura(mob_id=arte.mob_id, posicao=posicao,
                                             duracao=duracao, inicio=cob.inicio_na_arte,
                                             trilha=cob.trilha))
    except TakeErro as e:
        return {"erro": f"não consegui resolver um take do plano: {e}"}
    except McApiErro as e:
        return {"erro": f"o Media Composer não respondeu: {e}"}

    # ⭐ MEDIDO em 2026-09-13: timeline nascia sempre non-drop, mesmo em projeto drop-frame.
    drop = bool(projeto.get("drop_frame"))

    # ⭐⭐ Onde a sequência vai parar. Sem `bin_da_sequencia`, cada corte nascia numa bin
    #    própria — e um dia de trabalho deixava sete bins de versões espalhadas no
    #    projeto. Com ela, as versões de uma cena ficam ONDE O EDITOR JÁ OLHA.
    escolhida = str(bin_da_sequencia or "").strip()
    if escolhida:
        alvo = Path(escolhida) if Path(escolhida).is_absolute() else raiz / escolhida
        if alvo.suffix.lower() != ".avb":
            alvo = alvo.with_suffix(".avb")
    else:
        alvo = raiz / f"{_nome_de_arquivo(plano.nome)}.avb"
    relativo = relativo_ao_projeto(str(alvo), str(raiz)) or str(alvo)   # ver mcapi

    acrescentou = False
    copia_de_seguranca: Path | None = None
    try:
        if alvo.exists():
            # ⛔⛔ **Fechar ANTES de tocar no arquivo, e não é opcional.** Medido no banco
            #    (`protocolos/avb/escrita.md`, 2026-08-16): com a bin ABERTA no Media
            #    Composer, regravá-la preservando o UID dá `FILE_OPEN_FAILURE` — e pior,
            #    o MC salva por cima do nosso arquivo quando ele mesmo fechar a bin,
            #    desfazendo o trabalho sem erro nenhum.
            #
            # ⭐ O `CloseBin` SALVA a bin ao fechar: o que o editor tinha feito nela até
            #    agora vai para o disco antes de acrescentarmos a sequência.
            try:
                with MediaComposer() as mc:
                    mc._chamar("CloseBin", _timeout=TEMPO_DE_ARQUIVO_S,
                               bin_path=relativo)
            except McApiErro as e:
                # Bin fechada já devolve erro — é o caso normal, e não impede nada.
                log.debug("CloseBin de %s: %s", relativo, e)

            # ⭐ A cópia vem DEPOIS do `CloseBin`, que salva: é a bin como o editor a
            #   deixou, e é ela que volta se o Media Composer recusar a nossa.
            copia_de_seguranca = Path(tempfile.mkdtemp(prefix="cicloassist-")) / alvo.name
            copiar_bin(alvo, copia_de_seguranca)

            _timeline.acrescentar_timeline(alvo, plano.nome, entradas,
                                           projeto["fps_aprox"], base=caminho_da_bin,
                                           drop_frame=drop, coberturas=artes)
            acrescentou = True
        else:
            _escrever_bin_nova(alvo, plano.nome, entradas, projeto["fps_aprox"],
                               caminho_da_bin, drop, artes)
    except (ValueError, OSError) as e:
        if copia_de_seguranca is not None:
            shutil.rmtree(copia_de_seguranca.parent, ignore_errors=True)
        return {"erro": f"não consegui escrever a bin: {e}"}

    aberta, recusa = _abrir(relativo)

    aviso = ""
    if recusa and acrescentou and copia_de_seguranca is not None:
        # ⛔⛔ A bin do editor foi regravada e o Media Composer NÃO a aceita. Deixá-la assim
        #    é trocar a bin de trabalho dele por um arquivo que não abre. Ela volta como
        #    estava, e a sequência vai para uma bin nova — que não regrava nada dele.
        log.warning("o MC recusou %s depois da escrita (%s); devolvendo a original",
                    relativo, recusa)
        try:
            copiar_bin(copia_de_seguranca, alvo)
            _abrir(relativo)
            nova = _caminho_livre(raiz / f"{_nome_de_arquivo(plano.nome)}.avb")
            _escrever_bin_nova(nova, plano.nome, entradas, projeto["fps_aprox"],
                               caminho_da_bin, drop, artes)
        except (ValueError, OSError) as e:
            return {"erro": (
                f"o Media Composer recusou a bin {alvo.stem} depois de receber a sequência, "
                f"e ela foi devolvida como estava; a bin nova também falhou: {e}"
            )}
        relativo = str(nova.relative_to(raiz))
        aberta, _ = _abrir(relativo)
        acrescentou = False
        aviso = (
            f"O Media Composer recusou abrir a bin {alvo.stem} depois de ela receber a "
            f"sequência ({recusa}). A bin {alvo.stem} foi devolvida exatamente como "
            f"estava, e a sequência foi gravada numa bin NOVA, {nova.stem}, com o material "
            f"de que ela precisa guardado dentro, oculto. Diga isso ao editor com estas "
            f"palavras: é a bin dele que ficou intacta, e é na bin nova que está o corte."
        )

    if copia_de_seguranca is not None:
        shutil.rmtree(copia_de_seguranca.parent, ignore_errors=True)

    fps = projeto["fps_aprox"]
    resposta = {
        "ok": True,
        "sequencia": plano.nome,
        "bin": relativo,
        "cortes": len(plano.cortes),
        "coberturas": len(artes),
        "drop_frame": drop,
        "duracao_frames": plano.duracao_frames,
        "duracao_s": round(plano.duracao_frames / fps, 1),
        "aberta_no_avid": aberta,
        "acrescentada_a_bin_existente": acrescentou,
        "resumo": _plano.resumir(plano, fps),
    }
    if aviso:
        resposta["aviso_para_o_editor"] = aviso
    return resposta


def _abrir(relativo: str) -> tuple[bool, str]:
    """`OpenBin`. Devolve (abriu, a recusa do ARQUIVO — vazia se não for isso).

    ⚠️ Só `FILE_OPEN_FAILURE` conta como recusa: é o Media Composer dizendo que não aceita
    o arquivo. Media Composer fechado ou ponte fora do ar não julgam nada, e desfazer a
    escrita por isso jogaria fora uma bin boa.
    """
    try:
        with MediaComposer() as mc:
            # ⚠️ Operação de ARQUIVO, não consulta: teto de dezenas de segundos.
            mc._chamar("OpenBin", _timeout=TEMPO_DE_ARQUIVO_S, bin_path=relativo)
        return True, ""
    except McApiErro as e:
        # A bin está no disco e aparece na janela do projeto; só não abriu sozinha.
        log.warning("bin escrita mas OpenBin falhou: %s", e)
        return False, "FILE_OPEN_FAILURE" if "FILE_OPEN_FAILURE" in str(e) else ""


def _escrever_bin_nova(alvo: Path, nome: str, entradas, fps: float,
                       caminho_da_bin: str, drop_frame: bool = False,
                       coberturas=()) -> None:
    # ⚠️ Escreve no temporário e só depois copia: o nome da bin nova vem do modelo, e uma
    #    escrita pela metade dentro do projeto seria uma bin corrompida na janela do editor.
    temporario = Path(tempfile.gettempdir()) / alvo.name
    _timeline.escrever_bin(temporario, [(nome, entradas, list(coberturas))], fps,
                           base=caminho_da_bin, drop_frame=drop_frame)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(temporario.read_bytes())
    temporario.unlink(missing_ok=True)


def _caminho_livre(desejado: Path) -> Path:
    """Nunca por cima de uma bin que já existe: `NOME.avb`, `NOME 2.avb`, `NOME 3.avb`…"""
    if not desejado.exists():
        return desejado
    n = 2
    while (candidato := desejado.with_name(f"{desejado.stem} {n}.avb")).exists():
        n += 1
    return candidato


def pedacos_do_plano(plano, achar) -> list:
    """O plano → os pedaços da montagem do Premiere, com a MESMA conta de L/J do Avid.

    `achar(nome)` devolve `(item_id, tem_video, tem_audio)`. Imagem e som andam juntos na
    timeline; `desloca` é onde o som troca em relação à imagem (ver `montar_corte`).
    """
    from ...nle.premiere.montagem import Pedaco
    pedacos, pos = [], 0
    for i, c in enumerate(plano.cortes):
        desloca = c.desloca
        proximo = plano.cortes[i + 1].desloca if i + 1 < len(plano.cortes) else 0
        item_id, tem_v, tem_a = achar(c.take)
        pedacos.append(Pedaco(item_id=item_id, nome=c.take,
                              v_in=c.inicio_no_take, v_dur=c.duracao_frames,
                              a_in=c.inicio_no_take + desloca, a_dur=c.duracao_frames - desloca + proximo,
                              pos_v=pos, pos_a=pos + desloca, tem_video=tem_v, tem_audio=tem_a))
        pos += c.duracao_frames
    return pedacos


def _montar_no_premiere(plano, bin_da_sequencia: str) -> dict[str, object]:
    """⭐ F3 do plano `2026-11-06-mcp-do-premiere`: o plano vira sequência pelo MCP nativo."""
    from ...nle.premiere import mcp_nativo as M
    from ...nle.premiere import montagem as G
    if plano.coberturas:
        return {"erro": ("artes com alpha (coberturas) ainda não são montadas no Premiere: mande o "
                         "plano sem coberturas e diga ao editor que a arte entra à mão.")}
    if M.via("montagem") != "mcp":
        return _montar_pela_ponte(plano, bin_da_sequencia)
    try:
        p = M.projeto_ativo()
        if not p:
            return {"erro": "não há projeto aberto no Premiere"}
        pid = p["agentProjectId"]
        itens = G.itens_do_projeto(pid)
        cache: dict[str, tuple] = {}

        def achar(nome: str):
            if nome not in cache:
                item = G.achar_take(itens, nome, _bin_do_premiere(plano.bin))
                if item.get("type") == "sequence":
                    cache[nome] = (item["itemId"], True, True)   # merged: imagem e som
                else:
                    md = M.chamar("getClipMetadata", {"agentProjectId": pid, "itemIds": [item["itemId"]],
                                                      "fields": ["hasVideo", "hasAudio"]})
                    v = {x["field"]: x.get("value") for x in md["results"][0].get("values") or []}
                    cache[nome] = (item["itemId"], bool(v.get("hasVideo")), bool(v.get("hasAudio", True)))
            return cache[nome]

        pedacos = pedacos_do_plano(plano, achar)
        destino = _bin_do_premiere(bin_da_sequencia or plano.bin)
        # ⭐ Plano só de som (WAV do gravador): a taxa é a da sequência ativa, a mesma que o
        #   `transcrever` usou para dar os quadros que o modelo mandou.
        fps_ativa = None
        if not any(pc.tem_video for pc in pedacos):
            from fractions import Fraction as _F
            f = (M.estado() or {}).get("fps") or {}
            fps_ativa = _F(int(f["num"]), int(f["den"])) if f.get("num") else None
        r = G.montar(plano.nome, pedacos, bin_da_sequencia=destino, pid=pid, fps_sem_imagem=fps_ativa)
        com_imagem = next((pc.item_id for pc in pedacos if pc.tem_video), None)
        fps = float(G.taxa_do_item(pid, next(i for i in itens if i["itemId"] == com_imagem))) if com_imagem \
            else float(fps_ativa or 0) or 24.0
    except G.MontagemFalhou as e:
        return {"erro": f"não consegui montar no Premiere: {e}"}
    except (M.McpIndisponivel, M.McpFalhou) as e:
        return {"erro": f"o Premiere não respondeu à montagem: {e}"}
    resposta: dict[str, object] = {
        "ok": not r.divergencias, "sequencia": plano.nome, "bin": destino or "(raiz do projeto)",
        "cortes": len(plano.cortes), "duracao_frames": plano.duracao_frames,
        "duracao_s": round(plano.duracao_frames / fps, 1),
        "conferidos": f"{r.conferidos} de {r.itens} pedaços de trilha no quadro pedido",
        "desfazer": ("no Premiere cada passo da montagem é um Desfazer; para tirar a sequência inteira, "
                     "apague-a do projeto"),
        "resumo": _plano.resumir(plano, fps),
    }
    if r.divergencias:
        resposta["erro"] = "a sequência foi montada mas NÃO confere: " + "; ".join(r.divergencias[:6])
    if r.avisos:
        resposta["avisos"] = r.avisos
    return resposta


def _montar_pela_ponte(plano, bin_da_sequencia: str) -> dict[str, object]:
    """⭐ F6 (plano 2026-11-06-mcp-do-premiere §14): o Premiere SEM o MCP nativo (2025/2026) monta pelo
    ExtendScript (`cicloMontar`) — quadro exato e som multicanal inteiro, medidos. ⛔ Sem L/J (autor)."""
    from fractions import Fraction

    from ...nle import premiere as P
    from ...nle.premiere import montagem as G
    from ...nle.premiere import montagem_cep as C
    from ...nle.premiere import ponte
    from ...avid.take import TakeErro
    if not ponte.painel_vivo():
        return {"erro": ("o Premiere não está ligado ao Ciclo Assist: nem o servidor MCP (27.1+) nem a ponte "
                         "do painel respondem. Diga ao editor para abrir o Premiere com o Ciclo Assist.")}
    if any(c.desloca for c in plano.cortes):
        return {"erro": ("corte em L/J não é montado pelo Ciclo Assist nesta versão do Premiere: a escolha de "
                         "onde o som troca fica com o editor. Mande o plano com cortes secos.")}
    takes: dict[str, object] = {}
    try:
        def achar(nome: str):
            if nome not in takes:
                takes[nome] = P.resolver_take(_bin_do_premiere(plano.bin), nome)
            t = takes[nome]
            return t.mob_id, t.imagem is not None, t.som is not None
        pedacos = pedacos_do_plano(plano, achar)
        com_imagem = next((takes[c.take] for c in plano.cortes if takes[c.take].imagem is not None), None)
        if com_imagem is not None:
            fps = Fraction(com_imagem.fps["num"], com_imagem.fps["den"])
        else:
            f = (P.estado() or {}).get("fps") or {}
            if not f.get("num"):
                return {"erro": "plano só de som sem sequência ativa: não sei a taxa. Peça ao editor para abrir uma."}
            fps = Fraction(int(f["num"]), int(f["den"]))
        destino = _bin_do_premiere(bin_da_sequencia or plano.bin)
        r = C.montar(plano.nome, pedacos, fps, destino)
    except TakeErro as e:
        return {"erro": f"não consegui resolver um take do plano: {e}"}
    except G.MontagemFalhou as e:
        return {"erro": f"não consegui montar no Premiere: {e}"}
    resposta: dict[str, object] = {
        "ok": not r.divergencias, "sequencia": r.nome, "bin": destino or "(raiz do projeto)",
        "cortes": len(plano.cortes), "duracao_frames": plano.duracao_frames,
        "duracao_s": round(plano.duracao_frames / float(fps), 1),
        "conferidos": f"{r.conferidos} de {r.itens} pedaços de trilha no quadro pedido",
        "via": "ponte do painel (ExtendScript) — esta versão do Premiere não tem o servidor MCP",
        "resumo": _plano.resumir(plano, float(fps)),
    }
    if r.divergencias:
        resposta["erro"] = "a sequência foi montada mas NÃO confere: " + "; ".join(r.divergencias[:6])
    return resposta


def _bin_do_premiere(bin_: str) -> str:
    """A bin do plano no Premiere: "(raiz do projeto)" (o nome que a aba Vetores mostra) ou "/" é a raiz."""
    from ...nle.premiere import RAIZ
    b = str(bin_ or "").strip()
    return "" if b in ("/", RAIZ, "(raiz)") else b.strip("/")
