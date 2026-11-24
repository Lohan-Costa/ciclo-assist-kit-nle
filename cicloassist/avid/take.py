"""A camada de tradução: clipe do Avid (subclipe ou master, gerenciado ou AMA) → endereço
físico do take.

Esta é a peça que faz o Claude parar de precisar entender o Avid. Ela responde **onde
está** e **que pedaço** — não extrai frame, não transcreve, não abre `.mxf`, não toca no
Media Composer. `ver_frames` e `transcrever` são consumidoras dela.

Design completo, com as medições que o sustentam:
`docs/spec/2026-09-10-resolver-take.md`.

## As duas regras que organizam este módulo

⭐ **Para LER, o arquivo; para escrever ou saber o que está aberto, a API.** Ler o `.avb`
com pyavb é instantâneo e não tem efeito visível. A alternativa — `OpenBin` + a API —
custa ~500 ms por chamada e **abre a bin na tela do editor** no meio do trabalho dele.

⚠️⚠️ **Um take não tem UM in/out. Tem um por master.** O subclipe sincronizado mistura o
master da câmera e o do som, e eles entram em pontos diferentes. Medido em
`C07_P02-T004`: imagem em 0, som em **234** frames. Usar um só dessincroniza em 9,8 s, e
o modo de falha é silencioso — a transcrição descreve a cena vizinha com total confiança.
É por isso que `imagem` e `som` são blocos separados aqui, cada um com o seu `inicio`:
não existe lugar onde alguém possa pegar "o offset do take".
"""

from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from fractions import Fraction
from pathlib import Path

import avb

from ..midia import decodificadores as _sdk

log = logging.getLogger("cicloassist.avid.take")


class TakeErro(Exception):
    """Não foi possível traduzir este item num take."""


# ── taxa de quadros ──────────────────────────────────────────────────────────

# O `.avb` guarda a taxa como número (23.976), e contar frame com decimal perde um a cada
# 1001. A fração é a verdade; o decimal serve para o humano ler.
FRACOES = {
    23.976: Fraction(24000, 1001),
    24.0: Fraction(24, 1),
    25.0: Fraction(25, 1),
    29.97: Fraction(30000, 1001),
    30.0: Fraction(30, 1),
    50.0: Fraction(50, 1),
    59.94: Fraction(60000, 1001),
    60.0: Fraction(60, 1),
}


def fracao_da_taxa(edit_rate: float) -> Fraction:
    """Taxa do `.avb` → fração exata.

    ⚠️ Sem tabela, `Fraction(23.976)` vira 3374389/140741 — matematicamente correto e
    inútil: não é a taxa que o material usa, e o erro só aparece depois de milhares de
    frames, como uma deriva que ninguém liga ao arredondamento.
    """
    taxa = round(float(edit_rate), 3)
    if taxa in FRACOES:
        return FRACOES[taxa]
    for conhecida, fracao in FRACOES.items():
        if abs(conhecida - taxa) < 0.01:
            return fracao
    log.warning("taxa %s não está na tabela; usando aproximação", taxa)
    return Fraction(taxa).limit_denominator(1001)


def para_segundos(frames: int, taxa: Fraction) -> float:
    """Frames → segundos, com a divisão exata e a conversão para float **no fim**.

    ⚠️ `frames / Fraction` devolve outra `Fraction`, e `round()` de uma Fraction também é
    Fraction — exata, e não serializável em JSON. A conta fica racional até o último
    passo (é onde a precisão importa) e vira `float` só na saída, que é onde ela precisa
    atravessar a ponte para o modelo.
    """
    return round(float(frames / taxa), 3)


# ── a claquete ───────────────────────────────────────────────────────────────

# ⚠️ Leitor PLUGÁVEL desde o começo: no produto real cada produção nomeia diferente, e
# esta é a peça que mais vai variar. Nome que não casa **não é erro** — é um take com
# cena/plano/take vazios, que o editor aponta à mão (design de 25/08, Camada 1).
#
# ⚠️⚠️ **Não use `\b` como fronteira aqui.** O `_` é caractere de PALAVRA, então `\b` não
# dispara entre `C07` e `_P02` — e o padrão casava em `C7 P1-T001` (separado por espaço,
# vindo do nome do som) e falhava em `C07_P02-T001.1` (o nome do subclipe). Medido em
# 2026-09-10: 9 de 10 takes passavam e o décimo caía em "não reconhecido" sem explicação.
# A fronteira certa é "não seguido de dígito": `(?!\d)`.
PADRAO_CLAQUETE = re.compile(
    r"(?<![A-Za-z0-9])C(?P<cena>\d{1,3})(?!\d)[\s_.\-]*"
    r"P(?P<plano>\d{1,3})(?!\d)[\s_.\-]*"
    r"T(?P<take>\d{1,3})(?!\d)",
    re.IGNORECASE,
)


def ler_claquete(nome: str) -> dict[str, str | None]:
    achado = PADRAO_CLAQUETE.search(nome or "")
    if not achado:
        return {"cena": None, "plano": None, "take": None}
    return {
        "cena": f"C{achado.group('cena')}",
        "plano": f"P{achado.group('plano')}",
        "take": f"T{achado.group('take')}",
    }


# ── o acervo gerenciado ──────────────────────────────────────────────────────

#: ⭐ O padrão de nome do OP-Atom, medido: `<master>.mxf` para a imagem (sem sufixo) e
#: `<master>_A<nn>.mxf` para cada canal de áudio. Um arquivo POR TRACK — é o que faz o
#: som de 5 canais virar cinco arquivos.
SUFIXO_DE_AUDIO = re.compile(r"_A(\d{2,3})$", re.IGNORECASE)

#: A extensão do arquivo de ORIGEM que o MC deixa no nome do master de som linkado
#: (`M06 C1 P1-T001.wav`) — e que o `som_direto_gerenciado` copia desde 2026-11-01.
#: O OP-Atom não a tem (`…T001_A01.mxf`).
EXTENSAO_NO_NOME = re.compile(
    r"\.(wav|bwf|aif|aiff|mp3|m4a|mov|mp4|mxf|braw|r3d)$", re.IGNORECASE)

_raizes_em_cache: list[Path] | None = None


def raizes_de_midia() -> list[Path]:
    """As pastas `Avid MediaFiles/MXF` dos volumes locais.

    Cacheado no processo: a varredura de unidades é barata mas repetida, e o acervo não
    aparece no meio de uma conversa.

    ⛔⛔ Pela MESMA lista do acervo (`acervo.pastas_de_midia`), e não por letra de unidade.
    MEDIDO no macOS (2026-09-14): a varredura de `C:` a `Z:` devolvia `[]` com três `Avid
    MediaFiles` montadas, e todo take gerenciado saía sem arquivo — ver quadros,
    transcrever e a âncora do roteiro morriam juntos.
    """
    global _raizes_em_cache
    if _raizes_em_cache is not None:
        return _raizes_em_cache
    from ..midia.acervo import pastas_de_midia   # local: `midia` não pode puxar `avid`
    achadas = []
    for pasta in pastas_de_midia():
        raiz = pasta / "MXF"
        try:
            if raiz.is_dir():
                achadas.append(raiz)
        except OSError:
            continue  # unidade removível sem mídia levanta em vez de responder False
    _raizes_em_cache = achadas
    log.info("acervo: %s", [str(r) for r in achadas] or "nenhuma pasta encontrada")
    return achadas


def arquivos_do_master(nome: str, esperados: int | None = None) -> list[Path]:
    """Os `.mxf` de um master, pelo NOME.

    ⭐ **Por que pelo nome e não pelo MobID.** O banco mediu que em mídia AMA o `mob_id` é
    regerado a cada link — 83 de 118 masters mudaram numa medição real — enquanto o nome
    normalizado acertou 100 de 101 casamentos. O `.pmr` é a autoridade quando houver
    ambiguidade, mas o banco avisa para não fazer dele fundação: em storage de rede
    gerenciado ele não fica na pasta de mídia.

    `esperados` é o número de tracks do master, e serve para **parar de procurar** quando
    o conjunto está completo. O banco mediu o que isso vale numa diária: 109,7 s varrendo
    o acervo inteiro contra 10,9 s com filtro por nome e parada.
    """
    achados: list[Path] = []
    # ⛔⛔ Sem a extensão, nenhum som gerenciado com metadados do BWF era achado
    # (2026-11-01): o master se chama `…T01_WAV-BWF.wav`, o arquivo `…T01_WAV-BWF_A01.mxf`,
    # e o `resolver_take` dizia "não achei mídia no acervo local" com o som online no MC.
    alvos = {nome.casefold(), EXTENSAO_NO_NOME.sub("", nome).casefold()}
    for raiz in raizes_de_midia():
        for pasta in sorted(raiz.iterdir()):
            if not pasta.is_dir():
                continue
            try:
                for arquivo in pasta.glob("*.mxf"):
                    base = arquivo.stem
                    if base.casefold() in alvos or (
                        SUFIXO_DE_AUDIO.sub("", base).casefold() in alvos
                    ):
                        achados.append(arquivo)
            except OSError as e:
                log.warning("não consegui ler %s: %s", pasta, e)
            if esperados and len(achados) >= esperados:
                return ordenar_por_track(achados)
    return ordenar_por_track(achados)


def ordenar_por_track(arquivos: list[Path]) -> list[Path]:
    """Imagem primeiro (sem sufixo), depois os canais em ordem numérica.

    A ordem importa: os `_A01.._A05` do som são os canais 1 a 5, e entregá-los
    embaralhados faria a consumidora misturar quem fala com quem.
    """
    def chave(p: Path) -> tuple[int, int, str]:
        achado = SUFIXO_DE_AUDIO.search(p.stem)
        return (1, int(achado.group(1)), p.name) if achado else (0, 0, p.name)

    return sorted(arquivos, key=chave)


# ── a travessia do subclipe ──────────────────────────────────────────────────


def _source_clip(track) -> "avb.components.SourceClip | None":
    """O `SourceClip` de uma track — procurado, nunca presumido pela posição.

    ⚠️ **Medido em 2026-09-10 e custou uma rodada de depuração.** A track de um master é
    uma `Sequence` cujo PRIMEIRO componente é um `Filler`. Pegar `components[0]` devolve
    um objeto sem `mob_id`, e o sintoma é um campo **vazio**, não uma exceção — o código
    segue adiante achando que o master não aponta para lugar nenhum.

    ⛔ E o som de um subclipe pode vir EMBRULHADO num efeito (medido n'PRODUCAO-A, 2026-11-14: o `04-05-02` tem as 5
    trilhas de som em `Sequence[Filler, PanVolumeEffect[SourceClip], Filler]` — o ganho de clipe dentro do subclipe).
    Sem olhar dentro, o subclipe sincronizado passava por "só imagem" e o som sumia calado.
    """
    comp = track.component
    candidatos = getattr(comp, "components", None) or [comp]
    for c in candidatos:
        if isinstance(c, avb.components.SourceClip):
            return c
        for t in (getattr(c, "tracks", None) or []) if not callable(getattr(c, "tracks", None)) else []:
            dentro = getattr(t, "component", None)
            if isinstance(dentro, avb.components.SourceClip):
                return dentro
    return None


@dataclass
class Fonte:
    """Um master dentro do take, com o SEU ponto de entrada."""

    master: str
    #: ⭐ O UMID do MASTER — e é ele, não o do subclipe, que endereça todo cache
    #: derivado desta mídia (frames, transcrição). Ver `midia/cache.py`: transcreveu
    #: ou extraiu uma vez, e qualquer clipe que use aquele material acha pronto —
    #: masterclipe, subclipe, groupclipe, e subclipe feito DEPOIS.
    mob_id: str
    arquivos: list[str]
    inicio_frames: int
    inicio_s: float
    tracks: int
    faltando_no_disco: bool = False
    #: `gerenciada` (OP-Atom no acervo, um arquivo por track) ou `ama` (o arquivo linkado,
    #: imagem e som podendo morar no mesmo).
    origem: str = "gerenciada"
    #: ⭐ A chave do CACHE desta mídia (P1 do Premiere, 2026-09-17). No gerenciado é o
    #: `mob_id`. No AMA é a do ARQUIVO (UMID dele, ou a impressão do conteúdo): o `mob_id`
    #: do AMA é gerado a cada link, e a mesma `.mov` em dois projetos — ou no Premiere —
    #: seriam duas mídias. Ver `midia/identidade.py`.
    chave: str = ""
    tipo_da_chave: str = "umid"
    #: Outras chaves da mesma mídia, gravadas se ela nascer agora (`{chave: tipo}`).
    apelidos: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.chave:
            self.chave = self.mob_id

    def midia(self, rotulo: dict | None = None):
        """O cache desta mídia. ⛔ Sempre por aqui, nunca `Midia(fonte.mob_id)`."""
        from ..midia import cache as _cache
        return _cache.Midia(self.chave, rotulo=rotulo, tipo=self.tipo_da_chave,
                            apelidos=self.apelidos)


@dataclass
class Take:
    nome: str
    bin: str
    mob_id: str
    cena: str | None
    plano: str | None
    take: str | None
    fonte_da_claquete: str | None
    fps: dict[str, int]
    fps_aprox: float
    duracao_frames: int
    duracao_s: float
    imagem: Fonte | None
    som: Fonte | None
    confianca: str
    fonte: str
    avisos: list[str] = field(default_factory=list)
    #: `subclipe` ou `master` — ver `ESPECIES_ACEITAS`.
    especie: str = "subclipe"

    def rotulo(self, fonte: "Fonte | None") -> dict:
        """O que batiza a pasta de cache do master desta fonte (`cache.Midia(rotulo=…)`).

        ⚠️ O nome é o do MASTER, não o do subclipe: o cache é da mídia, e o subclipe é só
        um recorte dela. A duração do master não está no take; ela vem da varredura do
        acervo, quando houver.
        """
        if fonte is None:
            return {}
        # ⛔ Pelo MASTER, não pelo objeto: um master de câmera tem imagem e som, e `som` e
        #    `imagem` são duas `Fonte` do MESMO mob. Comparar objeto batizaria de "audio" a
        #    diária de câmera que alguém transcreveu antes de olhar os quadros.
        tem_imagem = self.imagem is not None and self.imagem.mob_id == fonte.mob_id
        rotulo = {
            "nome": fonte.master,
            "tipo": "video" if tem_imagem else "audio",
            "arquivos": list(fonte.arquivos),
        }
        if tem_imagem:
            # ⚠️ Só a imagem leva fps. No som, a taxa do take é a da TIMELINE, não do
            #    arquivo — o lugar dela é da amostragem, que vem da varredura.
            rotulo["fps"] = self.fps
        return rotulo

    def como_dicionario(self) -> dict:
        def achatar(f: Fonte | None) -> dict | None:
            if f is None:
                return None
            d = f.__dict__.copy()
            return d

        return {
            "nome": self.nome,
            "especie": self.especie,
            "bin": self.bin,
            "mob_id": self.mob_id,
            "cena": self.cena,
            "plano": self.plano,
            "take": self.take,
            "fonte_da_claquete": self.fonte_da_claquete,
            "fps": self.fps,
            "fps_aprox": self.fps_aprox,
            "duracao_frames": self.duracao_frames,
            "duracao_s": self.duracao_s,
            "imagem": achatar(self.imagem),
            "som": achatar(self.som),
            "confianca": self.confianca,
            "fonte": self.fonte,
            "avisos": self.avisos,
        }


#: ⭐ O que entra na timeline como MÍDIA, e por isso o chat aceita.
#:
#: `matte` desde 2026-09-13: o clipe de matte key que o Media Composer põe na bin ao
#: importar arquivo com alpha. ⚠️ Aceito para OLHAR (quadros, identificar); MONTAR ele numa
#: timeline ainda não é feito — a estrutura dele DENTRO de uma sequência não foi medida.
ESPECIES_ACEITAS = ("subclipe", "master", "matte")

#: Os `effect_id` de chave com alpha. MEDIDO na `MAIS VC AUTO` (MC 2025.6, 2026-09-13).
EFEITOS_DE_CHAVE = ("EFF2_BLEND_MATTE_KEY",)

#: ⛔ O que o Avid guarda na bin e NÃO é mídia aceita ainda — cada um com a frase que o
#: editor precisa ler. Recusar com "não é um subclipe" fazia o modelo tentar de novo com
#: outro nome, sem saber que o problema era a espécie do item.
RECUSAS = {
    "grupo": (
        "é um group clip (multicâmera), que ainda não é aceito. Use o master ou o "
        "subclipe de um dos ângulos."
    ),
    # MEDIDO na `BIN ORIGEM` (2026-09-13): `usage_code = 3` é o `Color Correction` que o
    # editor arrastou para a bin — um PRESET, com `TrackEffect` e 36 parâmetros, sem mídia.
    "efeito": (
        "é um efeito salvo na bin (um preset), não mídia. Aplicar preset nos clipes da "
        "timeline ainda não é aceito."
    ),
    "sequencia": (
        "é uma sequência. Monte a partir dos clipes dela — masters ou subclipes."
    ),
    "fonte": (
        "é um mob de arquivo interno do Avid, não um clipe da bin. Use o master que "
        "aponta para ele."
    ),
}


def especie(mob) -> str:
    """O que o item É, na língua do editor.

    ⚠️ `usage` do master é `"mastermob"` (código 7) quase sempre, mas a bin `PRODE` tem 36
    masters com `usage` nulo — medido em 2026-09-13. Por isso o master é reconhecido pelo
    TIPO do mob, e nunca pelo `usage`.
    """
    tipo = getattr(mob, "mob_type", "")
    if tipo == "MasterMob":
        return "master"
    if tipo == "SourceMob":
        return "fonte"
    uso = getattr(mob, "usage", None)
    if uso == "effect" and efeito_de_chave(mob) is not None:
        # ⚠️ O MESMO `usage_code = 3` do preset de Color Correction — o que separa os dois
        #    é haver MÍDIA dentro do efeito. Recusá-lo como preset foi o que impediu o
        #    Haiku de usar as artes da `MAIS VC AUTO` (2026-09-13).
        return "matte"
    return {"subclip": "subclipe", "group": "grupo", "effect": "efeito",
            None: "sequencia"}.get(uso, uso or "desconhecido")


def efeito_de_chave(mob):
    """O `TrackEffect` de matte key de um clipe de efeito da bin, ou `None`.

    MEDIDO na `MAIS VC AUTO Bin` (2026-09-13), `Matte Key: rdp HJ.new.01`:

    ```
    CompositionMob usage=effect (usage_code 3)
      Track 1 → TrackEffect EFF2_BLEND_MATTE_KEY  (keyframes: EffectParamList)
          track 1  Filler                       ← o fundo: o que estiver embaixo
          track 2  SourceClip → master precompute, track_id 1   ← o PREENCHIMENTO (MPGI)
          track 3  SourceClip → master precompute, track_id 2   ← o ALPHA (RGBA)
    ```

    O master `precompute` fica OCULTO na bin, com as duas trilhas de imagem.
    """
    for track in getattr(mob, "tracks", None) or []:
        comp = track.component
        if type(comp).__name__ != "TrackEffect" \
                or str(getattr(comp, "effect_id", "") or "") not in EFEITOS_DE_CHAVE:
            continue
        if any(type(t.component).__name__ == "SourceClip" for t in comp.tracks or []):
            return comp
    return None


def por_que_falta(fonte, tipo: str = "mídia") -> str:
    """Por que esta fonte não tem arquivo — na frase que diz O QUE FAZER.

    ⛔⛔ **MEDIDO em 2026-09-20, e é o caso que fez o produto parecer imprevisível.** O
    editor pediu para separar as falas da C07 às 09:16; os dez takes voltaram
    `não achei a mídia de som de '' no acervo local` — com o nome VAZIO, porque o master
    não estava na bin. O modelo não tinha como saber por quê: deduziu que faltavam
    masterclipes na bin e pediu ao editor que os trouxesse (coisa que no Avid nem faz
    sentido: master de subclipe vive oculto na própria bin). A bin `C07.avb` foi gravada
    às **09:17:12** — um minuto DEPOIS. O arquivo em disco estava mais velho que o que o
    Media Composer tinha na memória.

    ⇒ Quando o master não está no arquivo, a frase tem de dizer a causa provável e o
    gesto: **salvar a bin**. Sem isso, cada modelo inventa a sua explicação — que foi
    exatamente a queixa: *"precisamos ser mais previsíveis"*.

    ⚠️ O nome do master vazio é o SINTOMA de "não achei o mob nesta bin"; com nome, é o
    caso honesto de mídia offline (o arquivo não está no disco).
    """
    if not getattr(fonte, "master", ""):
        return (
            f"o master de {tipo} deste take não está na bin GRAVADA em disco "
            f"(mob {getattr(fonte, 'mob_id', '?')}). A causa mais comum é a bin ter "
            f"alterações ainda não salvas no Media Composer — peça ao editor para salvar "
            f"a bin (Ctrl+S) e tente de novo. Se ela já estiver salva, o master está em "
            f"outra bin do projeto."
        )
    return f"não achei a mídia de {fonte.master!r} no acervo local"


def resolver(bin_absoluta: str, item: str, procurar_arquivos: bool = True) -> Take:
    """Traduz um clipe da bin — subclipe ou master, gerenciado ou AMA — num take com
    endereço físico.

    `item` aceita o NOME ou o MobID — os dois, porque é o que `listar_itens_da_bin`
    mostra ao modelo, e a lição da fase 1 é que **o modelo devolve o que a ferramenta
    anterior lhe mostrou**.
    """
    caminho = Path(com_extensao_de_bin(bin_absoluta))
    if not caminho.is_file():
        raise TakeErro(f"não achei a bin {caminho}")

    with avb.open(str(caminho)) as f:
        mobs = list(f.content.mobs)
        por_id = {str(m.mob_id): m for m in mobs}

        alvo = _achar(mobs, item)
        if alvo is None:
            raise TakeErro(
                f"não achei {item!r} em {caminho.name}. "
                f"Use o nome ou o MobID que listar_itens_da_bin mostrou."
            )

        e_de_que = especie(alvo)
        if e_de_que not in ESPECIES_ACEITAS:
            motivo = RECUSAS.get(e_de_que, f"é um item do tipo {e_de_que!r}, que ainda não "
                                           f"é aceito como mídia.")
            raise TakeErro(f"{alvo.name!r} {motivo}")

        taxa = fracao_da_taxa(alvo.edit_rate)
        avisos: list[str] = []

        if e_de_que == "master":
            grupos = _grupos_do_master(alvo)
        elif e_de_que == "matte":
            # A imagem do matte key é o PREENCHIMENTO: o primeiro SourceClip dentro do
            # efeito (a trilha 2; a 1 é o fundo vazio). O alpha, na trilha seguinte, é do
            # mesmo master `precompute` — não é outra mídia a analisar.
            chave_ = efeito_de_chave(alvo)
            preenchimento = next(t.component for t in chave_.tracks
                                 if type(t.component).__name__ == "SourceClip")
            grupos = {("picture", str(preenchimento.mob_id)): {
                "inicio": preenchimento.start_time, "tracks": 1,
                "mob": str(preenchimento.mob_id)}}
            avisos.append(
                "é um clipe de matte key (arte com alpha): dá para olhar os quadros, mas "
                "montá-lo numa timeline como cobertura ainda não é feito.")
        else:
            grupos = _grupos_do_subclipe(alvo, avisos)

        imagem = _montar(grupos, "picture", por_id, taxa, procurar_arquivos, avisos)
        som = _montar(grupos, "sound", por_id, taxa, procurar_arquivos, avisos)

        mesma_origem = bool(imagem and som and imagem.master and imagem.master == som.master)
        if mesma_origem and e_de_que == "subclipe":
            # ⭐ Take SEM som direto: as tracks de som vêm do mesmo master da imagem, ou
            # seja, é o SCRATCH DA CÂMERA. Medido no `C07_P02-T001.1` — 2 canais, offset
            # 0, e nenhuma claquete para ler.
            #
            # ⚠️ Isto precisa ser dito, não deduzido: transcrever scratch de câmera dá
            # texto ruim, e uma consumidora que não saiba a diferença apresentaria o
            # resultado com a mesma confiança do som do gravador.
            avisos.append(
                "este take não tem som direto sincronizado: o áudio vem do scratch da "
                "câmera. Transcrição terá qualidade menor."
            )
        elif mesma_origem:
            # ⚠️ No MASTER de câmera o som é o do próprio arquivo — e em documentário ele
            #   É o som direto. Chamar de "scratch" diria ao editor que o material é pior
            #   do que é; o que se sabe é só que não há gravador sincronizado nele.
            avisos.append(
                "é um master de câmera: o som é o gravado no próprio arquivo, sem som de "
                "gravador sincronizado."
            )

        if imagem:
            # ⛔ MEDIDO em 2026-09-13: o ffprobe abre o contêiner do BRAW e lê o áudio PCM,
            #   mas o vídeo sai `codec_name=unknown`. Sem decodificador, quadros e vetores
            #   falhariam com "não consegui extrair o quadro", que manda procurar o defeito
            #   no lugar errado.
            # ⭐ 2026-09-21: com o decodificador do fabricante instalado, ver quadros de
            #   BRAW passou a funcionar (`midia/decodificadores.py`) — então o aviso só faz
            #   sentido quando ele FALTA. Aviso que sobrevive ao conserto vira ruído, e
            #   ruído é lido como "este produto não sabe o que está dizendo".
            tipos = {_sdk.tipo_de(a) for a in imagem.arquivos} - {""}
            faltando = sorted(t for t in tipos if not _sdk.temos(t))
            for t in faltando:
                avisos.append(
                    f"a imagem é {_sdk.NOMES[t]}, que o ffmpeg não decodifica e cujo "
                    f"decodificador não está instalado: dá para transcrever o som, mas "
                    f"não para ver quadros deste clipe."
                )

        # ⭐ A claquete é do SOM: só ele tem cena/plano/take anotados no set. O nome do
        # master de câmera é rolo/data/clipe e não sabe de cena nenhuma. Caindo para o
        # nome do subclipe quando o som não resolve.
        nome_da_claquete = som.master if som else None
        campos = ler_claquete(nome_da_claquete or "")
        fonte = "claquete"
        if campos["cena"] is None:
            campos = ler_claquete(alvo.name)
            fonte = f"nome-do-{e_de_que}" if campos["cena"] else "nome-nao-reconhecido"
            nome_da_claquete = alvo.name if campos["cena"] else nome_da_claquete

        return Take(
            nome=alvo.name,
            bin=str(caminho),
            mob_id=str(alvo.mob_id),
            cena=campos["cena"],
            plano=campos["plano"],
            take=campos["take"],
            fonte_da_claquete=nome_da_claquete,
            fps={"num": taxa.numerator, "den": taxa.denominator},
            fps_aprox=round(float(taxa), 3),
            duracao_frames=alvo.length,
            duracao_s=para_segundos(alvo.length, taxa),
            imagem=imagem,
            som=som,
            confianca="confirmado" if fonte == "claquete" else "inferido",
            fonte=fonte,
            avisos=avisos,
            especie=e_de_que,
        )


def hex_do_mob(mob_id) -> str:
    """O MobID como 64 hexadecimais, venha na grafia que vier.

    ⛔⛔ **MEDIDO em 2026-09-15, na C07:** o arquivo grafa
    `urn:smpte:umid:060a2b34.01010105.01010f20.13000000.a9b99375.81c0448d.bc9639bd.e525ea79`,
    e o arrasto do Avid (o que o preâmbulo entrega ao modelo) grafa
    `060a2b340101010501010f2013-000000-a9b9937581c0448d-bc9639bde525-ea79`. São os MESMOS
    64 hex, na mesma ordem. Comparando a string, nenhum clipe arrastado era achado —
    "não achei o MobID em C07.avb", com o clipe lá dentro — e o modelo saía perguntando ao
    editor em que bin estava o que ele tinha acabado de arrastar.
    """
    return re.sub(r"[^0-9a-f]", "", str(mob_id).lower().rsplit(":", 1)[-1])


def com_extensao_de_bin(caminho: str) -> str:
    """`CENAS/C07` → `CENAS/C07.avb`.

    ⚠️ O modelo escreve a bin como o editor fala dela, sem extensão — e acerta a bin. Sem
    isto, `CENAS/C07` dava "não achei a bin" e a bin CERTA era descartada (2026-09-15).
    Não é `Path.suffix`: uma bin chamada `C07 v1.2` tem sufixo `.2`.
    """
    texto = str(caminho).strip()
    return texto if not texto or texto.lower().endswith(".avb") else texto + ".avb"


def _achar(mobs: list, item: str) -> object | None:
    alvo = item.strip()
    alvo_hex = hex_do_mob(alvo)
    if len(alvo_hex) == 64:
        for m in mobs:
            if hex_do_mob(m.mob_id) == alvo_hex:
                return m
    # ⛔⛔ Pelo nome, o SourceMob fica por último. MEDIDO na bin AMA do editor
    #    (2026-09-13): o master `A003_03170837_C001` tem um mob de arquivo com o MESMO
    #    nome, e o primeiro que aparecesse no arquivo ganhava — o editor pediria o clipe e
    #    receberia "é um mob de arquivo interno", ou pior, dependendo da ordem da bin.
    mesmo_nome = [m for m in mobs if (m.name or "").casefold() == alvo.casefold()]
    mesmo_nome.sort(key=lambda m: getattr(m, "mob_type", "") == "SourceMob")
    return mesmo_nome[0] if mesmo_nome else None


def _tipo_da_track(track) -> str | None:
    kind = getattr(track.component, "media_kind", None)
    return kind if kind in ("picture", "sound") else None


def _grupos_do_subclipe(alvo, avisos: list[str]) -> dict[tuple[str, str], dict]:
    """As tracks do subclipe agrupadas por master. Cada grupo guarda o SEU início — é o
    ponto inteiro deste módulo (ver o docstring do arquivo)."""
    grupos: dict[tuple[str, str], dict] = {}
    for track in alvo.tracks:
        sc = _source_clip(track)
        if sc is None:
            continue
        tipo = "picture" if track.component.media_kind == "picture" else "sound"
        chave = (tipo, str(sc.mob_id))
        g = grupos.setdefault(
            chave, {"inicio": sc.start_time, "tracks": 0, "mob": str(sc.mob_id)}
        )
        g["tracks"] += 1
        if sc.start_time != g["inicio"]:
            # Tracks do MESMO master com inícios diferentes seria sync interno, que esta
            # versão não representa. Avisar em vez de escolher em silêncio.
            avisos.append(
                f"tracks do master {sc.mob_id} têm inícios diferentes "
                f"({g['inicio']} e {sc.start_time}); usei o primeiro"
            )
    return grupos


def _grupos_do_master(alvo) -> dict[tuple[str, str], dict]:
    """O master é o próprio master de si mesmo: início 0, no tempo DELE.

    ⭐ É o que mantém a regra do cache de pé sem caso especial: quadro e fala continuam
    numerados no tempo do master, e o que for analisado aqui serve ao subclipe feito dele
    depois — e vice-versa.
    """
    grupos: dict[tuple[str, str], dict] = {}
    for track in alvo.tracks:
        tipo = _tipo_da_track(track)
        if tipo is None:
            continue    # timecode, edgecode: não são mídia
        g = grupos.setdefault((tipo, str(alvo.mob_id)),
                              {"inicio": 0, "tracks": 0, "mob": str(alvo.mob_id)})
        g["tracks"] += 1
    return grupos


#: O caminho que o Avid grava num `WinFileLocator`: letra + `//` + barras normais
#: (`D//MIDIAS/x.mov`) — banco, `protocolos/avb/fontes.md`.
_LETRA_DO_AVID = re.compile(r"^([A-Za-z])//")


def _caminho_do_locator(mob) -> str:
    try:
        loc = getattr(getattr(mob, "descriptor", None), "locator", None)
    except ValueError as e:
        # ⚠️ MEDIDO nas bins do MC 25.12 do Mac (2026-09-14): 61 de 4.167 clipes de WAV
        #    linkado levantam `b'PCMA': unknown ext tag 0x02` no parser do pyavb (banco,
        #    `avb/estruturas.md`). Sem isto a ferramenta devolvia ao modelo o erro cru do
        #    parser; com isto o take segue, e o arquivo aparece como não achado.
        log.warning("não consegui ler o descritor de %r: %s", getattr(mob, "name", "?"), e)
        return ""
    if loc is None:
        return ""
    # ⚠️ Ler só `path` engana: em AMA ele pode vir vazio com o caminho em `path_utf8`
    #    (banco, `protocolos/avb/estruturas.md`). E mídia gerenciada tem locator com
    #    caminho VAZIO — é o vazio que a separa do AMA, não a ausência do locator.
    for campo in ("path_utf8", "path_posix", "path"):
        valor = getattr(loc, campo, None)
        if valor:
            return _no_disco_desta_maquina(_LETRA_DO_AVID.sub(r"\1:/", str(valor)))
    return ""


def _no_disco_desta_maquina(caminho: str, volumes: Path = Path("/Volumes")) -> str:
    """Um caminho de Windows (`D:/MIDIAS/x.mov`) lido num Mac: o mesmo arquivo num volume.

    ⚠️ MEDIDO (2026-09-14): bins do projeto trazem `D//…` e `E:\\…` dentro de
    `MacFileLocator` — material linkado no Windows e aberto no Mac. A letra não diz qual
    volume é; só se aceita o caminho se `/Volumes/*/<resto>` existir em EXATAMENTE um
    volume. Dois candidatos seriam um palpite, e palpite aqui é transcrever o take errado.
    """
    if os.name == "nt":
        return caminho
    forma = re.match(r"^[A-Za-z]:[\\/](.+)$", caminho)
    if not forma:
        return caminho
    resto = forma.group(1).replace("\\", "/")
    try:
        candidatos = [v / resto for v in volumes.iterdir() if (v / resto).is_file()]
    except OSError:
        return caminho
    return str(candidatos[0]) if len(candidatos) == 1 else caminho


def arquivos_ama(master, tipo: str, por_id: dict) -> list[str]:
    """Os arquivos que um master AMA linka, pela cadeia dentro da BIN.

    ⭐ MEDIDO na `BIN COM MIDIA AMA LINK` (2026-09-13): master → mob de arquivo
    (`MultiDescriptor`/`PCMADescriptor`, `MSMLocator`) → mob físico (`MediaDescriptor` ou
    `TapeDescriptor`, `WinFileLocator` com o caminho). Em AMA os três moram na bin; em
    mídia gerenciada a cadeia sai da bin no primeiro passo, e a lista volta vazia.

    ⚠️ Um arquivo AMA costuma ter imagem e som JUNTOS (um `.mov` com o vídeo e 4 pistas de
    áudio), então aqui não há o filtro por sufixo do OP-Atom: o mesmo arquivo serve às
    duas espécies.
    """
    achados: list[str] = []
    for track in master.tracks:
        if _tipo_da_track(track) != tipo:
            continue
        atual, visitados = master, set()
        sc = _source_clip(track)
        while sc is not None and str(sc.mob_id) not in visitados:
            visitados.add(str(sc.mob_id))
            atual = por_id.get(str(sc.mob_id))
            if atual is None:
                break
            caminho = _caminho_do_locator(atual)
            if caminho:
                if caminho not in achados:
                    achados.append(caminho)
                break
            proximas = [t for t in getattr(atual, "tracks", []) if _source_clip(t)]
            sc = _source_clip(proximas[0]) if proximas else None
    return achados


def _chave_ama(mob_id: str, arquivo: str) -> dict:
    """A chave de cache de um master AMA, conciliando o que o cache já tem.

    Três casos, e o terceiro é o que a P1 existe para resolver:

    1. o arquivo já tem pasta (pela chave dele, ou como apelido) → ela, e este `mob_id`
       vira apelido — o link DESTE projeto passa a achar a mesma mídia;
    2. a mídia foi processada antes, sob o `mob_id` → a pasta antiga continua a dona, e a
       chave do arquivo vira apelido dela. Nada é reprocessado;
    3. nada ainda → nasce pela chave do arquivo, com o `mob_id` de apelido.

    ⚠️ Falha ao ler o arquivo nunca impede o take: cai para o `mob_id`, como antes.
    """
    from ..midia import cache as _cache
    from ..midia import identidade as _identidade

    try:
        chave, tipo = _identidade.chave_do_arquivo(arquivo)
        mob = _cache.de_umid(mob_id)
    except (OSError, _cache.ChaveInvalida) as e:
        log.warning("sem chave de conteúdo para %s (%s); fico com o mob_id", arquivo, e)
        return {}
    if chave == mob:
        return {}
    try:
        pela_chave = _cache.Midia(chave, tipo=tipo)
        if pela_chave.existe:
            pela_chave.apelidar(mob, "mob_id")
            return {"chave": pela_chave.chave, "tipo_da_chave": tipo}
        pelo_mob = _cache.Midia(mob)
        if pelo_mob.existe:
            pelo_mob.apelidar(chave, tipo, arquivo=arquivo)
            return {}
    except OSError as e:
        log.warning("não consegui conciliar a chave de %s (%s)", arquivo, e)
        return {}
    return {"chave": chave, "tipo_da_chave": tipo, "apelidos": {mob: "mob_id"}}


def _montar(grupos, tipo, por_id, taxa, procurar, avisos) -> Fonte | None:
    dos_meus = [(k, v) for k, v in grupos.items() if k[0] == tipo]
    if not dos_meus:
        return None
    if len(dos_meus) > 1:
        avisos.append(
            f"o subclipe usa {len(dos_meus)} masters de {tipo}; "
            f"esta versão resolve o primeiro"
        )
    (_, mob_id), dados = dos_meus[0]

    master = por_id.get(mob_id)
    nome = (master.name if master else None) or ""
    if master is None:
        avisos.append(f"o master {mob_id} não está nesta bin; fica sem nome e sem arquivo")

    # O nº de tracks do master diz quantos arquivos OP-Atom procurar — e é o que permite
    # PARAR de varrer o acervo quando o conjunto fecha.
    tracks_do_master = len(master.tracks) if master else dados["tracks"]

    # ⭐ AMA primeiro: o caminho está na bin, e custa nada. Só sem ele o acervo gerenciado
    #   é varrido — e varrê-lo por um master AMA gastaria segundos para achar zero.
    ama = arquivos_ama(master, tipo, por_id) if master is not None else []
    if ama:
        existentes = [a for a in ama if Path(a).is_file()]
        if not existentes:
            avisos.append(f"o arquivo AMA de {nome!r} não está no disco: {ama[0]}")
        chave = _chave_ama(mob_id, existentes[0]) if (procurar and existentes) else {}
        return Fonte(
            **chave,
            master=nome,
            mob_id=mob_id,
            arquivos=existentes if procurar else [],
            inicio_frames=dados["inicio"],
            inicio_s=para_segundos(dados["inicio"], taxa),
            tracks=dados["tracks"],
            faltando_no_disco=not existentes,
            origem="ama",
        )

    arquivos: list[Path] = []
    if procurar and nome:
        arquivos = arquivos_do_master(nome, esperados=tracks_do_master)
        if not arquivos:
            avisos.append(f"não achei mídia de {nome!r} no acervo local")

    # ⭐ Cada bloco devolve SÓ a sua espécie de mídia, e a simetria é o que torna o
    # resultado previsível para quem consome: `imagem.arquivos` é o vídeo, ponto;
    # `som.arquivos` são os canais, em ordem.
    #
    # ⚠️ Sem isto, o master da câmera entrega três arquivos — o vídeo e DOIS canais de
    # scratch (`_A01`, `_A02`) —, e a consumidora que pegasse `arquivos[0]` funcionaria
    # por acidente de ordenação. O scratch da câmera não é o som do take: o som é o do
    # gravador, que está no outro master. Quem precisar do scratch um dia pede explícito.
    if tipo == "sound":
        so_meus = [a for a in arquivos if SUFIXO_DE_AUDIO.search(a.stem)]
    else:
        so_meus = [a for a in arquivos if not SUFIXO_DE_AUDIO.search(a.stem)]
    if arquivos and not so_meus:
        avisos.append(
            f"achei mídia de {nome!r} mas nenhum arquivo de {tipo}; devolvendo o que há"
        )
    arquivos = so_meus or arquivos

    return Fonte(
        master=nome,
        mob_id=mob_id,
        arquivos=[str(a) for a in arquivos],
        inicio_frames=dados["inicio"],
        inicio_s=para_segundos(dados["inicio"], taxa),
        tracks=dados["tracks"],
        faltando_no_disco=bool(nome) and not arquivos,
    )
