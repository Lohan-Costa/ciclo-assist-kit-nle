"""Editar a timeline do EDITOR — uma cópia ao lado, e prova de que só o pedido mudou.

⭐⭐ **O caminho B** (decisão do editor, 2026-09-13): a IA mexe numa timeline montada à mão,
com efeitos, keyframes, automação, transições — e entrega uma cópia em que **100% do que a
edição não devia tocar continua idêntico**. Não é promessa: `conferir_fidelidade` compara
objeto a objeto, por impressão digital, e a cópia só é gravada se a prova passar.

Por que dá para prometer isso com o pyavb: MEDIDO na `TL EDITADA` (4.277 objetos — 38
transições, `MotionEffect`, `Selector`, keyframes em `ParamClip`/`ControlClip`), a
regravação sai **idêntica byte a byte**, descontada a renumeração, com zero órfãos
(`spikes/a_bin_ama_regravada.py`, `spikes/ler_a_timeline.py`).

## A primeira operação: extrair um trecho

`extrair(seq, a, b)` tira o intervalo `[a, b)` de TODAS as trilhas e cola o resto — o
Extract do Avid com IN/OUT e todas as trilhas ligadas. ⭐ Todas as trilhas, e não só a do
segmento: extrair numa trilha só dessincroniza tudo o que vem depois.

⛔ **Recusa em vez de adivinhar.** O que ainda não sabemos fazer sem estragar volta como
`EdicaoRecusada` com a frase do porquê — transição encostando no corte, keyframe dentro de
um segmento aparado, group clip, clipe cortado no MEIO. Aparar a cabeça de um efeito com
keyframes, por exemplo, exige remapear a curva; fazer sem isso deslizaria a automação.
"""

from __future__ import annotations

import hashlib
import os

from avb.mobid import MobID

from .timeline import PREFIXO_DE_COMPOSICAO


class EdicaoRecusada(Exception):
    """A edição encostaria em algo que ainda não sabemos editar sem estragar."""


# ── impressão digital ────────────────────────────────────────────────────────


def impressao(obj, memo: dict | None = None) -> str:
    """Hash estrutural de um objeto AVB e de tudo que ele referencia.

    ⭐ Por VALOR, não por posição no arquivo: dois objetos com os mesmos campos e os mesmos
    filhos têm a mesma impressão em arquivos diferentes, e qualquer campo trocado muda o
    hash. É o que permite dizer "este efeito é o MESMO de antes", e não só "parecido".
    """
    memo = {} if memo is None else memo
    chave = id(obj)
    # ⛔⛔ O memo guarda o OBJETO junto do hash. MEDIDO na TL EDITADA: com `id(obj)` sozinho
    #    de chave, a prova acusou TODOS os mobs da bin como mudados. O pyavb solta o objeto
    #    lido (cache fraco) e relê sob demanda; um objeto novo herda o `id` de um coletado, e
    #    o memo devolvia o hash do OUTRO. Manter a referência impede o `id` de ser reusado.
    if chave in memo and memo[chave][0] is obj:
        return memo[chave][1]
    h = hashlib.sha1()

    def entra(v):
        v = getattr(v, "value", v) if type(v).__name__ == "AVBObjectRef" else v
        if v is None or isinstance(v, (bool, int, float, str, bytes)):
            h.update(repr(v).encode("utf-8", "replace"))
        elif isinstance(v, MobID):
            h.update(str(v).encode())
        elif isinstance(v, dict):
            for k in v:
                h.update(repr(k).encode())
                entra(v[k])
        elif isinstance(v, (list, tuple)):
            h.update(b"[")
            for x in v:
                entra(x)
            h.update(b"]")
        elif hasattr(v, "property_data") or hasattr(v, "class_id"):
            h.update(impressao(v, memo).encode())
        else:
            h.update(repr(v).encode("utf-8", "replace"))

    h.update(type(obj).__name__.encode())
    if isinstance(obj, dict):
        entra(dict(obj))
    elif hasattr(obj, "property_data"):
        for k in sorted(obj.property_data):
            h.update(k.encode())
            entra(obj.property_data[k])
    else:
        entra(obj)
    memo[chave] = (obj, h.hexdigest())
    return memo[chave][1]


# ── a cópia ──────────────────────────────────────────────────────────────────


def copiar_sequencia(f, original, nome: str):
    """Cópia da sequência na MESMA bin, com MobID próprio (medido: `copia_carrega_na_record`).

    ⚠️ O `copy` preserva o MobID por valor — é o mesmo clipe noutra bin. Na mesma bin seriam
    dois itens com o mesmo MobID, e por isso a cópia ganha identidade nova.
    """
    nova = original.copy(f)
    nova.mob_id = MobID(bytes_le=bytes(bytearray(PREFIXO_DE_COMPOSICAO) + os.urandom(16)))
    nova.name = nome
    f.content.add_mob(nova).user_placed = True
    return nova


# ── extrair ──────────────────────────────────────────────────────────────────

_INVOLUCROS = ("PanVolumeEffect", "TrackEffect")
_KEYFRAMES = ("ParamClip", "ControlClip", "Keyframe")


def _tem_keyframe(comp) -> bool:
    from avb.core import walk_references
    return any(type(o).__name__ in _KEYFRAMES for o in walk_references(comp))


def _conferir_aparavel(comp, onde: str) -> None:
    """Levanta `EdicaoRecusada` se o segmento não puder ser aparado sem estragar.

    ⛔ Chamado no PLANEJAMENTO, nunca na aplicação: descobrir no meio que uma trilha não
    pode ser aparada deixaria as outras já aparadas — a timeline dessincronizada.
    """
    tipo = type(comp).__name__
    if tipo in ("Filler", "SourceClip"):
        return
    if tipo in _INVOLUCROS:
        if _tem_keyframe(comp):
            raise EdicaoRecusada(
                f"{onde}: o corte apara um segmento com keyframes ({tipo}). Remapear a curva "
                f"ainda não é feito — aparar sem isso deslizaria a automação.")
        dentro = [t.component for t in (comp.tracks or [])]
        if len(dentro) != 1 or type(dentro[0]).__name__ != "SourceClip":
            raise EdicaoRecusada(
                f"{onde}: o corte apara um {tipo} que não envolve um clipe só. Ainda não.")
        return
    raise EdicaoRecusada(f"{onde}: o corte apara um {tipo}, que ainda não sei aparar.")


def _rotulo(t) -> str:
    """`V2`, `A3` — o nome que o editor vê na timeline, e que a recusa usa."""
    kind = getattr(t.component, "media_kind", "?")
    letra = {"picture": "V", "sound": "A"}.get(kind)
    return f"{letra}{t.index}" if letra else f"trilha {t.index} ({kind})"


def _aparar(comp, cabeca: int, cauda: int) -> None:
    """Tira `cabeca` frames do começo e `cauda` do fim. Só depois de `_conferir_aparavel`."""
    tipo = type(comp).__name__
    if tipo == "Filler":
        comp.length -= cabeca + cauda
        return
    alvo = comp if tipo == "SourceClip" else comp.tracks[0].component
    alvo.start_time += cabeca
    alvo.length -= cabeca + cauda
    if alvo is not comp:
        comp.length -= cabeca + cauda


def extrair(seq, a: int, b: int) -> dict:
    """Tira `[a, b)` (frames desde o início da sequência) de todas as trilhas, e cola.

    Devolve o que mudou, trilha a trilha, para o editor ler. Levanta `EdicaoRecusada` ANTES
    de mexer em qualquer trilha se alguma não puder ser editada: uma extração aplicada pela
    metade dessincroniza a timeline.
    """
    if not 0 <= a < b <= seq.length:
        raise EdicaoRecusada(f"intervalo [{a}, {b}) fora da sequência de {seq.length} frames")
    tirar = b - a
    planos = []

    for n, t in enumerate(seq.tracks):
        comp = t.component
        rotulo = _rotulo(t)
        if type(comp).__name__ != "Sequence":
            planos.append((comp, None))          # Timecode, Edgecode: só o comprimento
            continue
        acoes, pos = [], 0
        for k, c in enumerate(list(comp.components)):
            tipo = type(c).__name__
            if tipo == "TransitionEffect":
                ini = pos - c.length
                if ini <= b and pos >= a:
                    raise EdicaoRecusada(
                        f"{rotulo}: há uma transição encostando no trecho. Extrair através "
                        f"dela ainda não é feito.")
                pos = ini
                continue
            s, e = pos, pos + c.length
            pos = e
            if e <= a or s >= b or c.length == 0:
                continue
            if tipo == "Selector":
                raise EdicaoRecusada(f"{rotulo}: há um group clip no trecho. Ainda não.")
            if s >= a and e <= b:
                acoes.append((k, "remover", 0, 0))
            elif s < a and e > b:
                if tipo != "Filler":
                    raise EdicaoRecusada(
                        f"{rotulo}: o trecho cai no MEIO de um clipe ({tipo}). Extrair de "
                        f"dentro de um segmento ainda não é feito.")
                acoes.append((k, "aparar", 0, tirar))
            elif s < a:
                _conferir_aparavel(c, rotulo)
                acoes.append((k, "aparar", 0, e - a))
            else:
                _conferir_aparavel(c, rotulo)
                acoes.append((k, "aparar", b - s, 0))
        planos.append((comp, acoes))

    # ── só agora mexe: todas as trilhas passaram ────────────────────────────
    resumo = []
    for comp, acoes in planos:
        if acoes is None:
            # ⚠️ Só o que NÃO é Sequence tem comprimento gravado (Timecode, Edgecode). O da
            #    Sequence o pyavb calcula pela soma dos componentes — e recusa atribuição.
            comp.length -= tirar
            continue
        lista = list(comp.components)
        removidos = {k for k, acao, _, _ in acoes if acao == "remover"}
        # As emendas: quem fica imediatamente antes e depois de cada bloco removido.
        emendas = set()
        for k in removidos:
            esq, dir_ = k - 1, k + 1
            while esq in removidos:
                esq -= 1
            while dir_ in removidos:
                dir_ += 1
            if esq >= 0 and dir_ < len(lista):
                emendas.add((id(lista[esq]), id(lista[dir_])))
        for k, acao, cabeca, cauda in sorted(acoes, key=lambda x: -x[0]):
            if acao == "remover":
                resumo.append(f"removido {type(lista[k]).__name__} de {lista[k].length}")
                del lista[k]
            else:
                _aparar(lista[k], cabeca, cauda)
                resumo.append(f"aparado {type(lista[k]).__name__}: -{cabeca} cabeça "
                              f"-{cauda} cauda")
        # ⭐ Os dois vazios que a remoção deixou colados viram um só — e SÓ esses: juntar
        #    vazios vizinhos em outro ponto da trilha seria mexer fora do trecho pedido.
        colada = []
        for c in lista:
            if colada and (id(colada[-1]), id(c)) in emendas \
                    and type(c).__name__ == "Filler" and type(colada[-1]).__name__ == "Filler":
                colada[-1].length += c.length
                resumo.append(f"colados dois vazios na emenda ({colada[-1].length})")
                continue
            colada.append(c)
        comp.components = colada
    seq.length -= tirar
    return {"frames_tirados": tirar, "mudancas": resumo}


# ── a prova ──────────────────────────────────────────────────────────────────


def segmentos(seq) -> list[list]:
    """Os componentes de cada trilha, na ordem."""
    saida = []
    for t in seq.tracks:
        c = t.component
        saida.append(list(c.components) if type(c).__name__ == "Sequence" else [c])
    return saida


def _com_posicao(lista) -> list[tuple[int, int, object]]:
    """`(início, fim, componente)`; a transição ocupa o trecho em que se sobrepõe."""
    saida, pos = [], 0
    for c in lista:
        if type(c).__name__ == "TransitionEffect":
            saida.append((pos - c.length, pos, c))
            pos -= c.length
            continue
        saida.append((pos, pos + c.length, c))
        pos += c.length
    return saida


def _prefixo_comum(x: list, y: list) -> int:
    n = 0
    while n < len(x) and n < len(y) and x[n] == y[n]:
        n += 1
    return n


def conferir_fidelidade(original, copia, trecho_original: tuple[int, int],
                        trecho_copia: tuple[int, int]) -> list[str]:
    """Tudo que está fora do trecho editado é idêntico ao original? Devolve as violações.

    `trecho_original` é o que a edição consumiu no original e `trecho_copia` o que ela
    ocupa na cópia: extrair `[a, b)` é `(a, b)` → `(a, a)`; inserir `d` frames em `p` é
    `(p, p)` → `(p, p + d)`.

    ⭐⭐ É a garantia do caminho B em código. Em cada trilha:

    - o que no original TERMINA até o trecho aparece igual, na mesma ordem, na cópia;
    - o que no original COMEÇA depois do trecho aparece igual, na mesma ordem, na cópia;
    - de cada lado pode diferir **um** segmento só — o aparado, o vazio partido ou colado —,
      o que cruza a fronteira na cópia tem de ser vazio, e o que está dentro do trecho da
      cópia é o que a edição pôs. Um efeito com um campo trocado muda a impressão e reprova.

    E fora das trilhas: todo campo da sequência e de cada `Track` igual, menos o que a
    edição tem de mudar (`length`, `name`, `mob_id`).
    """
    memo_o, memo_c = {}, {}
    problemas: list[str] = []
    ao, bo = trecho_original
    ac, bc = trecho_copia
    delta = (bc - ac) - (bo - ao)

    for campo in original.property_data:
        if campo in ("length", "name", "mob_id", "tracks"):
            continue
        if impressao([original.property_data[campo]], memo_o) != \
                impressao([copia.property_data.get(campo)], memo_c):
            problemas.append(f"a sequência mudou no campo {campo!r}")
    if copia.length != original.length + delta:
        problemas.append(f"comprimento {copia.length}, esperado {original.length + delta}")

    if len(original.tracks) != len(copia.tracks):
        return problemas + [f"número de trilhas mudou: {len(original.tracks)} → "
                            f"{len(copia.tracks)}"]
    for n, (to, tc) in enumerate(zip(original.tracks, copia.tracks)):
        for campo in ("index", "attributes", "session_attr", "filler_proxy", "lock_number"):
            if impressao([getattr(to, campo, None)], memo_o) != \
                    impressao([getattr(tc, campo, None)], memo_c):
                problemas.append(f"trilha {n}: campo {campo!r} da trilha mudou")
        co, cc = to.component, tc.component
        if type(co).__name__ != "Sequence":
            # ⭐ MEDIDO na TL EDITADA: 9 das 28 trilhas não são de mídia — 3 `Timecode`,
            #    5 `CaptureMask`, 1 `Edgecode` —, um componente só, do tamanho da sequência.
            #    Para elas a edição só muda o comprimento, e exatamente em `delta`.
            if type(co) is not type(cc):
                problemas.append(f"trilha {n}: {type(co).__name__} virou {type(cc).__name__}")
                continue
            for campo in co.property_data:
                if campo == "length":
                    continue
                if impressao([co.property_data[campo]], memo_o) != \
                        impressao([cc.property_data.get(campo)], memo_c):
                    problemas.append(f"trilha {n}: {type(co).__name__}.{campo} mudou")
            if cc.length != co.length + delta:
                problemas.append(f"trilha {n}: {type(co).__name__} com {cc.length} frames, "
                                 f"esperado {co.length + delta}")
            continue
        po = _com_posicao(segmentos(original)[n])
        pc = _com_posicao(segmentos(copia)[n])
        antes_o = [(impressao(c, memo_o), type(c).__name__) for s, e, c in po if e <= ao]
        depois_o = [(impressao(c, memo_o), type(c).__name__) for s, e, c in po if s >= bo]
        antes_c = [(impressao(c, memo_c), type(c).__name__) for s, e, c in pc if e <= ac]
        depois_c = [(impressao(c, memo_c), type(c).__name__) for s, e, c in pc if s >= bc]
        cruzam = {id(c): c for s, e, c in pc if s < ac < e or s < bc < e}

        # ⛔⛔ Estrito, e o teste que reprovou a primeira versão está em `test_edicao.py`:
        #    TODO segmento que no original está INTEIRO de um lado do trecho tem de estar
        #    idêntico na cópia. A única ausência tolerada é de um VAZIO — o que a edição
        #    estendeu ou colou, e que por isso agora cruza a fronteira. A cópia pode ter um
        #    segmento a mais de cada lado: a sobra do que, no original, cruzava a fronteira.
        #    A versão com "um diferente de cada lado" aprovava um CLIPE alterado na emenda.
        p = _prefixo_comum(antes_o, antes_c)
        falta = antes_o[p:]
        if len(falta) > 1 or (falta and falta[0][1] != "Filler") or len(antes_c) - p > 1:
            problemas.append(f"trilha {n}: mudou algo ANTES do trecho "
                             f"({len(falta)} segmento(s) diferentes)")
        q = _prefixo_comum(depois_o[::-1], depois_c[::-1])
        falta = depois_o[:len(depois_o) - q]
        if len(falta) > 1 or (falta and falta[0][1] != "Filler") or len(depois_c) - q > 1:
            problemas.append(f"trilha {n}: mudou algo DEPOIS do trecho "
                             f"({len(falta)} segmento(s) diferentes)")
        if any(type(c).__name__ != "Filler" for c in cruzam.values()):
            problemas.append(f"trilha {n}: algo que não é vazio atravessa a fronteira do trecho")
    return problemas


# ── inserir ──────────────────────────────────────────────────────────────────


def _novo_vazio(comp, media_kind: str, comprimento: int):
    fl = comp.root.create.Filler(comp.edit_rate, media_kind)
    fl.length = comprimento
    return fl


def inserir(seq, pos: int, duracao: int, novos: dict | None = None) -> dict:
    """Abre `duracao` frames em `pos` em TODAS as trilhas e empurra o resto — o Insert do Avid.

    `novos` diz o que entra em cada trilha, pela posição dela em `seq.tracks`: um componente
    com exatamente `duracao` frames. Trilha que não está em `novos` ganha VAZIO — é o que
    mantém a sincronia; e sem `novos` nenhum, é abrir um gap.

    ⛔ Recusa em vez de adivinhar, e ANTES de mexer: `pos` no meio de um clipe (seria preciso
    partir o clipe — com efeito e keyframes, ainda não), ou transição encostando em `pos`.
    """
    novos = dict(novos or {})
    if not 0 <= pos <= seq.length or duracao <= 0:
        raise EdicaoRecusada(f"posição {pos} ou duração {duracao} inválida")
    for n, comp in novos.items():
        if comp.length != duracao:
            raise EdicaoRecusada(f"o que entra na trilha {n} tem {comp.length} frames, "
                                 f"e o espaço aberto tem {duracao}")
    planos = []
    for n, t in enumerate(seq.tracks):
        comp = t.component
        rotulo = _rotulo(t)
        if type(comp).__name__ != "Sequence":
            if n in novos:
                raise EdicaoRecusada(f"{rotulo} não é trilha de mídia")
            planos.append((comp, None))
            continue
        onde = None
        # ⛔ SEM `break` ao achar o lugar. MEDIDO na `TL EDITADA` (2026-09-13): um vazio que
        #    contém o ponto vem ANTES, na lista, da transição que se sobrepõe a ele — e com
        #    o `break` a transição nunca era vista. Quem barrava era a prova, no fim, com
        #    "algo que não é vazio atravessa a fronteira", que não diz o que fazer.
        for k, (s, e, c) in enumerate(_com_posicao(list(comp.components))):
            if type(c).__name__ == "TransitionEffect":
                if s <= pos <= e:
                    raise EdicaoRecusada(f"{rotulo}: há uma transição encostando no ponto "
                                         f"de inserção. Ainda não.")
                continue
            if s < pos < e:
                if type(c).__name__ != "Filler":
                    raise EdicaoRecusada(
                        f"{rotulo}: o ponto de inserção cai no MEIO de um clipe "
                        f"({type(c).__name__}). Partir clipe ainda não é feito.")
                onde = onde or ("dentro", k, pos - s)
            elif s == pos and c.length:
                onde = onde or ("antes", k, 0)
        planos.append((comp, onde if onde else ("fim", None, 0)))

    resumo = []
    for n, (comp, onde) in enumerate(planos):
        if onde is None:
            comp.length += duracao
            continue
        lista = list(comp.components)
        kind = comp.media_kind
        modo, k, dentro = onde
        k = len(lista) if modo == "fim" else k
        novo = novos.get(n)
        if novo is None:
            # Gap nesta trilha: se já há vazio ali, ele cresce; senão, um vazio novo.
            if modo == "dentro":
                lista[k].length += duracao
            elif modo == "antes" and type(lista[k]).__name__ == "Filler":
                # ⚠️ MEDIDO no gap da TL EDITADA: um take terminando onde começa um vazio.
                #    Sem este caso nascia um vazio NOVO colado no que já existia.
                lista[k].length += duracao
            elif k > 0 and type(lista[k - 1]).__name__ == "Filler":
                lista[k - 1].length += duracao
            else:
                lista.insert(k, _novo_vazio(comp, kind, duracao))
            resumo.append(f"trilha {n}: +{duracao} de vazio")
        elif modo == "dentro":
            direita = _novo_vazio(comp, kind, lista[k].length - dentro)
            lista[k].length = dentro
            lista[k + 1:k + 1] = [novo, direita]
            resumo.append(f"trilha {n}: {type(novo).__name__} partindo um vazio")
        else:
            lista.insert(k, novo)
            resumo.append(f"trilha {n}: {type(novo).__name__} num corte")
        comp.components = lista
    seq.length += duracao
    return {"frames_abertos": duracao, "mudancas": resumo}
