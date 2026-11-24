"""`transcrever` — o que se fala num take.

⭐ **A transcrição é do MASTER inteiro e fica em tempo do MASTER**, exatamente como os
quadros. Um subclipe é um recorte; recortar a lista de falas depois é conta de lista.
Transcrever por subclipe faria o mesmo áudio passar pelo ASR uma vez por recorte, e um
groupclipe de multicam montado depois não acharia nada pronto.

⚠️ **O offset do som NÃO é o da imagem.** Medido na C07: a imagem entra em 0 e o som em
234 frames — quase 10 segundos. É por isso que a janela desta ferramenta sai de
`take.som.inicio_frames`, e usar o da imagem descreveria a cena vizinha com total
confiança.
"""

from __future__ import annotations

import json
import logging
from fractions import Fraction

from ... import nle as _nle
from ...avid import take as _take
from ...avid.take import TakeErro
from ...midia import analise as _analise
from ...midia import asr as _asr
from ...servico import turno as _turno
from ...midia import cache as _cache
from ...midia import falantes as _falantes
from ...midia import voz as _voz
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.fala")

#: ⚠️⚠️ **O modelo lê a RESPOSTA, não o nosso código.** Sem esta frase ele usa
#: `inicio_no_take` como ponto de corte — que foi exatamente o que fez o editor ouvir a
#: última sílaba sumir em campo (2026-09-11). Ela vai em toda transcrição, de propósito:
#: é no momento de usar o dado que a regra precisa estar na frente dele.
COMO_CORTAR = (
    "Cada fala já vem com o ponto de corte pronto em SEGUNDOS (entrada_do_corte / "
    "saida_do_corte) e em FRAMES (inicio_no_take_frames / saida_no_take_frames / "
    "duracao_frames). Para um corte de uma fala só, copie inicio_no_take_frames e "
    "duracao_frames direto para montar_corte — não converta nada. Para um corte que cobre "
    "as falas A até B, use inicio_no_take_frames de A e "
    "duracao = saida_no_take_frames de B menos inicio_no_take_frames de A. "
    f"Quando duas falas seguidas DESTE take tiverem vao_ate_a_proxima até "
    f"{_asr.VAO_DE_JUNTAR_S:.1f} s, use UM corte contínuo cobrindo as duas: a pausa entre "
    "elas é atuação, e a ambiência que some no meio denuncia o corte. "
    "E nunca emende pedaços de falas diferentes só porque o texto combina. "
    "Para separar_falas não copie frames: aponte o número em segmento."
)

#: ⚠️⚠️ **MEDIDO em 2026-09-12, na sessão da C07**: com o array de palavras, um take real
#: passava de **60 KB e ESTOURAVA o limite de saída do CLI** — 12 de 14 transcrições
#: voltaram truncadas, e o modelo só via as duas primeiras falas de cinquenta mais um
#: caminho de arquivo. O conserto dele foi pior que a doença: 13 Greps nos arquivos
#: persistidos (118 KB, o maior consumidor de saída de ferramenta da sessão), de onde saiu
#: o erro de aplicar o timestamp de um take em outro.
#:
#: ⭐ O ASR continua medindo por palavra e o CACHE continua guardando — o que muda é só o
#: que SAI para o modelo. Por isso a `ASSINATURA` do estágio não muda e o cache sobrevive.
SEM_PALAVRAS = (
    "Esta transcrição vem sem o tempo de cada palavra, que é o padrão. Chame de novo com "
    "por_palavra=true SÓ se precisar cortar no meio de uma frase — a resposta fica cerca "
    "de quatro vezes maior."
)


def em_frames(segundos_no_master: float, inicio_s: float, taxa: Fraction) -> int:
    """Segundos do MASTER → frames contados do início do TAKE.

    ⭐⭐ **MEDIDO em 2026-09-12**: sem isto o modelo multiplicava por 23,976 de cabeça,
    duas vezes por corte, quinze cortes por cena — e `montar_corte` só aceita inteiro.
    Foi um desses trinta cálculos que colocou o timestamp de um take dentro de outro.
    A conta é da máquina; a decisão é do modelo.

    ⚠️ A taxa é `Fraction`, nunca `float`: 24000/1001 não tem representação exata, e
    arredondar duas vezes num take de quatro minutos anda um frame.
    """
    return round((float(segundos_no_master) - inicio_s) * taxa)


def formatar_fala(f: dict, inicio_s: float, taxa: Fraction,
                  por_palavra: bool = False, segmento: int | None = None) -> dict[str, object]:
    """Uma fala do ASR como o modelo a recebe.

    Função à parte porque é o CONTRATO com o modelo — o que ele vê é isto, e é aqui que
    um campo a mais custa a janela de contexto de uma cena inteira.
    """
    entrada = em_frames(f["corte_inicio"], inicio_s, taxa)
    saida = em_frames(f["corte_fim"], inicio_s, taxa)
    fala: dict[str, object] = {} if segmento is None else {"segmento": segmento}
    fala.update({
        # ⭐⭐ É AQUI que o corte entra e sai. A voz continua depois do que o ASR mede,
        #   e a entrada precisa de ar.
        "entrada_do_corte": round(float(f["corte_inicio"]) - inicio_s, 2),
        "saida_do_corte": round(float(f["corte_fim"]) - inicio_s, 2),
        # ⭐ Os mesmos dois pontos na moeda que `montar_corte` aceita — e com os NOMES
        #   dela, para o modelo copiar em vez de converter.
        "inicio_no_take_frames": entrada,
        "saida_no_take_frames": saida,
        "duracao_frames": saida - entrada,
        "vao_ate_a_proxima": f.get("vao_ate_a_proxima"),
        "texto": f["texto"],
        # ⭐ quem fala, pela lapela (`midia/falantes.py`); ausente = não se sabe (o porquê vai em `quem_fala`)
        **({"quem": f["quem"]} if f.get("quem") else {}),
        "certeza": f.get("certeza"),
        # ⚠️ O relógio do MASTER, que é onde a transcrição guardada vive: é ele que casa
        #    este trecho com qualquer outro recorte da mesma mídia.
        "inicio_no_master": f["inicio"],
    })
    if por_palavra:
        # ⭐ Só sob pedido: é este array que estourava o limite de saída do CLI.
        # ⚠️ SÓ em frames, e não em segundos também. Medido ao construir: dar as duas
        #    moedas por palavra deixou a saída de emergência 57% MAIOR que o formato
        #    antigo que ela veio consertar. Quem corta dentro de uma frase entrega frame
        #    ao `montar_corte`; o segundo, aqui, não serve a ninguém.
        fala["palavras"] = [
            {"palavra": w.get("palavra"),
             "inicio": em_frames(w.get("t", 0), inicio_s, taxa),
             "fim": em_frames(w.get("fim", 0), inicio_s, taxa)}
            for w in (f.get("palavras") or [])
        ]
    return fala


def falas_do_take(take, falas_do_master: list[dict],
                  por_palavra: bool = False) -> list[dict[str, object]]:
    """As falas de UM take, numeradas, exatamente como `transcrever` as mostra.

    ⭐⭐ **`segmento` é o endereço que o `separar_falas` recebe no lugar dos frames.**
    MEDIDO em 2026-09-15 (Haiku, C07): o pedido de 33 falas trazia 237 trechos com início
    e duração copiados à mão, 13 mil tokens de JSON, e 32 deles apontavam outra fala ou
    engoliam a vizinha. O modelo decide QUAL fala do take é a do momento; copiar o número
    de frame é conta da máquina.

    ⛔ Por isso a lista sai daqui e de nenhum outro lugar: se o `separar_falas` numerasse
    por conta própria, o segmento 12 dele poderia não ser o 12 que o modelo leu. A
    numeração é do take INTEIRO, a mesma em qualquer página.
    """
    som = take.som
    taxa = Fraction(take.fps["num"], take.fps["den"])
    inicio_s = som.inicio_s
    fim_s = float((som.inicio_frames + take.duracao_frames) / taxa)
    dentro = _asr.recortar(falas_do_master, inicio_s, fim_s)
    # ⭐⭐ O ponto de corte não é o tempo do ASR. MEDIDO em 2026-09-11
    #   (`spikes/o_respiro_do_corte.py`): a voz continua **230 ms em média** depois do que
    #   o ASR diz — é por isso que "sobe comigo" saía "sobe co…". E cortar exatamente no
    #   ataque, que o ASR acerta, deixa a entrada sem ar. O respiro é limitado pela fala
    #   vizinha, então ele nunca traz a cauda do outro ator para dentro.
    dentro = _asr.com_respiro(dentro, piso_s=inicio_s, teto_s=fim_s)
    return [formatar_fala(f, inicio_s, taxa, por_palavra, segmento=i)
            for i, f in enumerate(dentro, 1)]


#: ⛔⛔ O teto que faltava. Enxugar campo reduz por um FATOR; lista sem limite não tem
#: teto nenhum — uma diária de entrevista com 257 falas estoura mesmo no formato magro.
#: MEDIDO: 20.201 chars passaram inteiros na sessão real e 55.844 estouraram, então o
#: orçamento fica com folga abaixo da borda de baixo.
#:
#: ⚠️ Truncar calado seria pior que estourar: o modelo montaria a cena com metade do
#: diálogo achando que viu tudo. Por isso a resposta diz quantas ficaram de fora e por
#: onde continuar.
ORCAMENTO_CHARS = 18_000


def _serializado(falas: list[dict]) -> int:
    """O tamanho que a LISTA vai ter, não a soma das falas soltas.

    ⚠️ Não é a mesma conta: dentro de uma lista com `indent=2` cada linha ganha dois
    espaços a mais, e ainda entram colchetes e vírgulas. Medir fala a fala subestima, e
    foi assim que a primeira versão desta paginação deixou passar 18,6 KB num orçamento
    de 18 KB.
    """
    return len(json.dumps(falas, ensure_ascii=False, indent=2))


def paginar(falas: list[dict], a_partir: int) -> tuple[list[dict], int]:
    """As falas que cabem no orçamento, a partir de um índice. Devolve (falas, próxima).

    `próxima` é 0 quando acabou — o modelo não deve precisar de conta para saber que
    terminou.
    """
    inicio = max(a_partir, 0)
    escolhidas: list[dict] = []
    gasto = 0
    for i in range(inicio, len(falas)):
        # Estimativa barata para não serializar a lista inteira a cada passo; o ajuste
        # fino vem depois, e só encosta nas últimas.
        gasto += len(json.dumps(falas[i], ensure_ascii=False, indent=2)) + 2 * 12
        if escolhidas and gasto > ORCAMENTO_CHARS:
            break
        escolhidas.append(falas[i])

    # ⛔ Uma fala sozinha pode passar do orçamento (texto enorme, ou por_palavra num
    #    monólogo). Devolver lista vazia faria o modelo pedir a MESMA página para sempre.
    while len(escolhidas) > 1 and _serializado(escolhidas) > ORCAMENTO_CHARS:
        escolhidas.pop()

    proxima = inicio + len(escolhidas)
    return escolhidas, (proxima if proxima < len(falas) else 0)


@ferramenta(
    nome="transcrever",
    descricao=(
        "Devolve o que é falado num take (Avid ou Premiere), com o tempo de cada fala. "
        "⭐ Para separar_falas, e para só ler o que se diz, peça enxuta=true: seis vezes "
        "menor, com o mesmo número de segmento. Transcreve o "
        "som direto com reconhecimento local. Use para saber o que se diz numa cena, "
        "achar uma fala específica, comparar takes, ou preparar um corte por diálogo. "
        "Cada fala traz `quem` quando se sabe quem fala: a LAPELA do som direto mais forte "
        "(o nome da trilha, ex. MIC2), 'provável equipe' ou 'ambígua'; o resumo do take vai "
        "em quem_fala. Só "
        "LÊ: chame direto, sem pedir licença ao editor. O que já foi transcrito vem do "
        "cache na hora; só um material nunca ouvido demora. Cada fala já traz o ponto "
        "de corte pronto: entrada_do_corte e saida_do_corte em segundos, e os mesmos dois "
        "em frames como inicio_no_take_frames, saida_no_take_frames e duracao_frames — "
        "copie os frames direto para montar_corte, sem converter. O tempo de cada palavra "
        "fica de fora por padrão; peça por_palavra=true só para cortar no meio de uma "
        "frase."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "Caminho da bin."},
            "item": {"type": "string", "description": "O clipe: nome ou o identificador que a listagem mostrou (MobID no Avid, id no Premiere)."},
            "por_palavra": {
                "type": "boolean",
                "description": (
                    "Traz o tempo de cada palavra, para cortar DENTRO de uma frase. "
                    "Deixa a resposta cerca de quatro vezes maior; peça um take de cada "
                    "vez quando usar."
                ),
            },
            "enxuta": {
                "type": "boolean",
                "description": (
                    "Só segmento, segundo e texto de cada fala, sem os pontos de corte. "
                    "É a forma para separar_falas (que aponta o segmento) e para ler o que "
                    "se diz; para montar_corte, peça a completa."
                ),
            },
            "a_partir_da_fala": {
                "type": "integer",
                "description": (
                    "Continua uma transcrição longa de onde ela parou. Use o número que "
                    "veio em continuar_em; não chute."
                ),
            },
        },
        "required": ["bin", "item"],
    },
    escreve=False,
    nles=AMBOS,
)
def transcrever(bin: str, item: str, por_palavra: bool = False,
                a_partir_da_fala: int = 0, enxuta: bool = False) -> dict[str, object]:
    try:
        take = _nle.resolver_take(bin, item)
    except TakeErro as e:
        return {"erro": str(e)}

    som = take.som
    if som is None or not som.arquivos:
        # ⚠️ "Não tem som" só quando não TEM: som que existe e não foi achado no disco é
        #    outra frase, senão o editor ouve que o take é mudo (como em `visual.py`).
        if som is None:
            return {"erro": "esse take não tem som para transcrever"}
        # ⭐ A frase que diz O QUE FAZER (master fora da bin gravada = salvar a bin), e os
        #   avisos do resolvedor junto: sem eles o modelo inventa a explicação que lhe
        #   parecer plausível — foi o que aconteceu em 2026-09-20 (ver `take.por_que_falta`).
        return {"erro": _take.por_que_falta(som, "som"), "avisos": take.avisos}

    try:
        midia = som.midia(rotulo=take.rotulo(som))
    except _cache.ChaveInvalida as e:
        return {"erro": f"não consigo endereçar o cache deste áudio: {e}"}

    # ⭐ Mixar, ouvir e guardar moram em `midia/analise.py`, e não aqui: a aba Vetores
    #   transcreve o mesmo master pela fila de fundo. Duas cópias do caminho divergiriam
    #   na primeira mudança de receita, e o cache pareceria pronto para um lado e velho
    #   para o outro — sem erro nenhum.
    def contando(o_que: str, fracao, trecho: str) -> None:
        _turno.avisar(f"{o_que} do take", fracao, trecho or take.nome)

    try:
        # ⭐ Os nomes dos canais saem da BIN do take (colunas `TRK`): é a fonte que conhece o master gerenciado,
        #   cujo OP-Atom não carrega nome nenhum (plano 2026-11-06, transcrição por canal).
        trilhas, fonte_dos_nomes = _analise.trilhas_do_som(som.arquivos, _colunas_do_som(take, som))
        feito = _analise.transcrever_master(midia, som.arquivos, som.master,
                                            aviso=contando, trilhas=trilhas,
                                            fonte_dos_nomes=fonte_dos_nomes)
    except _analise.AnaliseFalhou as e:
        return {"erro": str(e)}
    falas, do_cache = feito["falas"], feito["do_cache"]
    # ⭐ quem fala cada fala (plano 2026-11-06): `quem` em cada uma, e a linha do take em `quem_fala`
    falas = _falantes.anexar(falas, feito.get("falantes"))
    # ⭐ a borda da voz medida na lapela (L2, `midia/voz.py`): o `com_respiro` só ESTENDE o corte até ela
    falas = _voz.anexar(falas, feito.get("voz"))
    if do_cache:
        # ⭐ Pedido do editor (2026-10-22): sem isto a transcrição guardada não deixava
        #   rastro na tela, e o silêncio do resto do turno parecia o ASR parado.
        _turno.avisar("transcrição já guardada, sem ouvir de novo", None, take.nome)

    todas = falas_do_take(take, falas, por_palavra and not enxuta)
    if enxuta:
        # ⭐⭐ MEDIDO no ensaio da C07 (2026-10-22): as 10 transcrições completas eram 155
        #    mil caracteres no contexto, relidos a cada ida ao modelo — e separar_falas só
        #    usa o NÚMERO do segmento e o texto. Cada fala completa tem ~330 caracteres;
        #    esta, ~50. O segmento é o MESMO das duas formas (sai de `falas_do_take`).
        #    ⚠️ Uma LINHA de texto por fala, e não uma lista: a resposta é serializada com
        #    indentação, e `[seg, s, texto]` virava cinco linhas por fala.
        todas = [f"{f.get('segmento')} | {float(f.get('entrada_do_corte') or 0):.1f} | "
                 f"{f.get('texto')}" + (f" | {f['quem']}" if f.get("quem") else "") for f in todas]
    pagina, proxima = paginar(todas, a_partir_da_fala)

    resposta: dict[str, object] = {
        "take": take.nome,
        "cena": take.cena,
        "plano": take.plano,
        "master_de_som": som.master,
        "canais": len(som.arquivos),
        "do_cache": do_cache,
        "fps": take.fps,
        # ⛔⛔ O tempo CRU do reconhecedor (`inicio_no_take`/`fim_no_take`) saiu daqui de
        # propósito em 2026-09-12. Ele só existia para NÃO ser usado: a regra escrita
        # mandava ignorá-lo, e mesmo assim ele virava ponto de corte e decepava a sílaba.
        # Campo que existe para não ser usado é campo que um dia vai ser usado.
        "falas": pagina,
        "quem_fala": _falantes.resumo(feito.get("falantes")),
        "falas_no_take": len(todas),
        "falas_fora_da_janela": len(falas) - len(todas),
        "confianca": "inferido",
        "fonte": "transcricao",
        "avisos": take.avisos,
    }
    if proxima:
        resposta["continuar_em"] = proxima
        resposta["falta"] = (
            f"Este take tem {len(todas)} falas e couberam {len(pagina)}. As outras NÃO "
            f"estão aqui — não monte a cena achando que viu o take inteiro. Chame de novo "
            f"com a_partir_da_fala={proxima}."
        )
    if enxuta:
        resposta["formato_das_falas"] = "segmento | segundos desde o início do take | texto [| quem fala]"
        return resposta
    # ⚠️ Dito em palavras, porque o modelo lê a resposta e não o nosso código.
    resposta["como_cortar"] = COMO_CORTAR
    if not por_palavra:
        resposta["sem_palavras"] = SEM_PALAVRAS
    return resposta


def _colunas_do_som(take, som) -> dict:
    """As colunas `TRK` do master de som, lidas na bin do take (e, sem ela, na última varredura do projeto)."""
    from ...avid import bins as _bins  # noqa: PLC0415
    mob = str(getattr(som, "mob_id", "") or "")
    if not mob:
        return {}
    try:
        chave = _cache.de_umid(mob)
    except _cache.ChaveInvalida:
        return {}
    return (_bins.colunas_do_master(take.bin, chave) if getattr(take, "bin", "") else {}) \
        or _bins.colunas_da_foto(chave)
