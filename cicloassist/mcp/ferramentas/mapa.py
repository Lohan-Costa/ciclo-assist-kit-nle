"""O mapa do material: guardar e reler o que já se sabe de cada take.

⭐ **É o que faz "olhar" virar "conhecer".** Sem isto, cada pergunta sobre a mesma cena
paga de novo a extração dos quadros E o raciocínio do modelo sobre eles. Com isto, a
segunda pergunta lê o que a primeira aprendeu.

⚠️ A nota é guardada no cache do **master** (ver `midia/cache.py`), não do subclipe: um
groupclipe de multicam montado depois encontra a descrição pronta, e refazer um subclipe
não apaga o que já se sabia daquela mídia.

⛔ **`anotar_o_que_vi` ESCREVE, e por isso passa pelo portão** (ADR 0003). É a primeira
ferramenta do produto que grava alguma coisa, e é ela que exercita o mecanismo inteiro.
"""

from __future__ import annotations

import logging
import time

from ... import nle as _nle
from ...avid.mcapi import McApiErro
from ...avid.take import TakeErro
from ...midia import cache as _cache
from ...midia import decupagem as _decupagem
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.mapa")


def _take(bin: str, item: str):
    return _nle.resolver_take(bin, item)


@ferramenta(
    nome="anotar_o_que_vi",
    descricao=(
        "Guarda a sua decupagem de um take, para não precisar olhar os quadros de novo "
        "na próxima pergunta — e para que ela possa ser PROCURADA depois. Use depois de "
        "ver_frames, quando tiver formado uma descrição do plano. Escreva como um "
        "assistente de edição escreveria: quem aparece, o que acontece, cenário, luz, "
        "figurino, e o que o take tem de particular. Preencha também os campos de "
        "enquadramento, ângulo, câmera, local e momento — são eles que fazem "
        "procurar_no_material responder a 'todos os closes noturnos'."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "Caminho da bin."},
            "item": {"type": "string", "description": "Nome do clipe (subclipe ou master), ou o MobID."},
            "descricao": {
                "type": "string",
                "description": "O que há no take, em prosa.",
            },
            "etiquetas": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Palavras livres que ajudam a achar depois: quem aparece, ação, "
                    "objetos, figurino, clima. Ex.: Personagem F, blusa vermelha, discussão, "
                    "abajur, escuta."
                ),
            },
            "enquadramento": {
                "type": "string",
                "enum": list(_decupagem.ENQUADRAMENTOS),
                "description": "O tamanho do plano.",
            },
            "angulo": {
                "type": "string",
                "enum": list(_decupagem.ANGULOS),
                "description": "A altura da câmera em relação ao olhar.",
            },
            "camera": {
                "type": "string",
                "enum": list(_decupagem.CAMERAS),
                "description": "O que a câmera faz. 'parada' é resposta, não ausência.",
            },
            "local": {
                "type": "string",
                "enum": list(_decupagem.LOCAIS),
                "description": "Interior ou exterior.",
            },
            "momento": {
                "type": "string",
                "enum": list(_decupagem.MOMENTOS),
                "description": "Dia ou noite, pelo que se vê.",
            },
        },
        "required": ["bin", "item", "descricao"],
    },
    escreve=True,
    nles=AMBOS,
)
def anotar_o_que_vi(
    bin: str, item: str, descricao: str, etiquetas: list[str] | None = None,
    enquadramento: str = "", angulo: str = "", camera: str = "",
    local: str = "", momento: str = "",
) -> dict[str, object]:
    # ⭐ O vocabulário é conferido ANTES de abrir a bin: é a checagem barata, não precisa
    #   do Media Composer, e devolve a lista certa em vez de "não achei a bin" quando as
    #   duas coisas estão erradas ao mesmo tempo.
    try:
        campos = _decupagem.normalizar_campos({
            "enquadramento": enquadramento, "angulo": angulo, "camera": camera,
            "local": local, "momento": momento,
        })
    except _decupagem.ValorForaDoVocabulario as e:
        return {"erro": str(e)}

    try:
        take = _take(bin, item)
    except (TakeErro, McApiErro) as e:
        return {"erro": str(e)}

    imagem = take.imagem
    if imagem is None or not imagem.mob_id:
        return {"erro": "esse take não tem trilha de imagem para anotar"}

    try:
        midia = imagem.midia(rotulo=take.rotulo(imagem))
    except _cache.ChaveInvalida as e:
        return {"erro": f"não consigo endereçar o cache deste material: {e}"}

    midia.anotar_fonte({"master": imagem.master, "mob_id": imagem.mob_id})
    midia.anotar({
        "trecho": take.nome,
        "cena": take.cena,
        "plano": take.plano,
        "take": take.take,
        "inicio_frames": imagem.inicio_frames,
        "duracao_frames": take.duracao_frames,
        "descricao": descricao.strip(),
        "etiquetas": [e.strip() for e in (etiquetas or []) if e.strip()],
        **campos,
        "quando": time.strftime("%Y-%m-%dT%H:%M:%S"),
        # Procedência, como em todo item do produto: isto é leitura de IA sobre quadros,
        # não dado que alguém anotou no set.
        "confianca": "inferido",
        "fonte": "visual",
    })
    return {
        "ok": True,
        "guardado_em": take.nome,
        "master": imagem.master,
        "campos": campos,
        "total_de_notas": len(midia.ler_notas()),
    }


@ferramenta(
    nome="ler_o_que_ja_sabemos",
    descricao=(
        "Devolve o que já foi observado e guardado sobre um take — descrição, "
        "etiquetas e quando foi anotado. Consulte ANTES de pedir quadros: se a "
        "descrição já existe, não é preciso olhar de novo."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "Caminho da bin."},
            "item": {"type": "string", "description": "Nome do clipe (subclipe ou master), ou o MobID."},
        },
        "required": ["bin", "item"],
    },
    escreve=False,
    nles=AMBOS,
)
def ler_o_que_ja_sabemos(bin: str, item: str) -> dict[str, object]:
    try:
        take = _take(bin, item)
    except (TakeErro, McApiErro) as e:
        return {"erro": str(e)}

    imagem = take.imagem
    if imagem is None or not imagem.mob_id:
        return {"take": take.nome, "notas": []}

    try:
        midia = imagem.midia()
    except _cache.ChaveInvalida:
        return {"take": take.nome, "notas": []}

    todas = midia.ler_notas()
    # ⭐ Devolve TUDO o que se sabe do master, marcando qual nota é deste take. As outras
    # são de trechos vizinhos da mesma mídia, e é justamente isso que um assistente quer
    # saber — "o que mais existe nesta diária?".
    return {
        "take": take.nome,
        "master": imagem.master,
        "deste_take": [n for n in todas if n.get("trecho") == take.nome],
        "outros_trechos_do_mesmo_material": [
            n for n in todas if n.get("trecho") != take.nome
        ],
    }


@ferramenta(
    nome="procurar_no_material",
    descricao=(
        "Procura em TUDO que já foi decupado: 'onde tem close noturno no consultório?', "
        "'em que takes a Personagem F aparece de blusa vermelha?', 'que planos têm o abajur ao "
        "fundo?'. Busca na descrição, nas etiquetas e nos campos (enquadramento, ângulo, "
        "câmera, local, momento) de todas as mídias, sem abrir o Media Composer. "
        "Os termos somam: 'close noite' devolve o que tem os dois. "
        "⚠️ Só encontra material que alguém já OLHOU e que está em alguma bin do projeto "
        "ABERTO — a resposta diz quantas mídias estão decupadas do total e de que projeto "
        "é o recorte; se o número for baixo, diga isso ao editor em vez de afirmar que o "
        "material não existe."
    ),
    esquema={
        "type": "object",
        "properties": {
            "termos": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Palavras que precisam aparecer TODAS. Acento não importa. "
                    "Ex.: ['personagem f', 'blusa vermelha']."
                ),
            },
            "enquadramento": {"type": "string", "enum": list(_decupagem.ENQUADRAMENTOS)},
            "angulo": {"type": "string", "enum": list(_decupagem.ANGULOS)},
            "camera": {"type": "string", "enum": list(_decupagem.CAMERAS)},
            "local": {"type": "string", "enum": list(_decupagem.LOCAIS)},
            "momento": {"type": "string", "enum": list(_decupagem.MOMENTOS)},
            "quantos": {
                "type": "integer",
                "description": "Teto de resultados. Padrão 20.",
                "default": 20,
            },
        },
        "required": [],
    },
    escreve=False,
    nles=AMBOS,
)
def procurar_no_material(
    termos: list[str] | None = None, enquadramento: str = "", angulo: str = "",
    camera: str = "", local: str = "", momento: str = "", quantos: int = 20,
) -> dict[str, object]:
    try:
        campos = _decupagem.normalizar_campos({
            "enquadramento": enquadramento, "angulo": angulo, "camera": camera,
            "local": local, "momento": momento,
        })
    except _decupagem.ValorForaDoVocabulario as e:
        return {"erro": str(e)}

    if not termos and not campos:
        return {"erro": "diga o que procurar: termos, ou um dos campos."}

    # ⭐⭐ O recorte vem das BINS do projeto aberto (`avid/escopo.py`), não do cache: o
    #   cache atravessa projetos de propósito, e material de outra produção é resposta
    #   errada que parece certa — o editor carrega o clipe e descobre que não é dali.
    recorte = _nle.escopo_agora()
    cortes: dict[str, int] = {}
    achados = _decupagem.procurar(termos, campos,
                                  limite=max(1, min(int(quantos or 20), 60)),
                                  chaves=recorte.chaves, contador=cortes)
    decupadas, no_cache = _decupagem.quantas_decupadas(chaves=recorte.chaves)
    # ⚠️ O que ficou de fora é DITO. Uma peça decupada em trechos tem uma nota por plano, e
    #   sem a frase o modelo leria "achei 3 nesta peça" como "só há 3" — e contaria isso ao
    #   editor com a confiança de quem varreu tudo.
    de_fora = []
    if cortes.get("por_midia"):
        de_fora.append(f"{cortes['por_midia']} nota(s) de trecho da MESMA mídia ficaram de "
                       f"fora (até {_decupagem.NOTAS_POR_MIDIA} por mídia, para uma peça "
                       f"não ocupar a lista inteira); peça o_que_acontece para a linha do "
                       f"tempo dela")
    if cortes.get("alem_do_limite"):
        de_fora.append(f"{cortes['alem_do_limite']} achado(s) além do limite de {quantos}")

    return {
        "achados": achados,
        "quantos": len(achados),
        "escopo": recorte.como_dicionario(),
        **({"de_fora": de_fora} if de_fora else {}),
        # ⭐⭐ O tamanho do que foi procurado vai SEMPRE junto. Sem isto, "não achei" se
        #   confunde com "não existe" — e a diferença é o produto inteiro: uma coisa é o
        #   material não ter o que se procura, outra é ninguém ter olhado para ele ainda.
        "material_decupado": decupadas,
        "material_no_cache": no_cache,
        "aviso": (
            f"A busca cobre as {decupadas} mídia(s) já decupadas de {no_cache} no recorte. "
            f"Material que ninguém olhou ainda não aparece aqui — para decupar um take, "
            f"use ver_frames e depois anotar_o_que_vi. "
            + ("; ".join(de_fora) + ". " if de_fora else "")
            + recorte.aviso
        ),
    }
