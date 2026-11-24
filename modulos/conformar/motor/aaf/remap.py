"""Remapear a identidade dos masters de um AAF.

## Por que isto existe

`relink_aaf()` (em `aaf/writer.py`) resolve o relink trocando a `URLString` dos
`SourceMob [ImportDescriptor]`. Isso funciona quando o AAF **aponta para arquivos** —
o caso de uma montagem cujos clipes vieram de import.

Mas o AAF que chega ao editor online costuma ser outro: os clipes de câmera são
**offline por fita** (`TapeDescriptor`, sem locator, sem URL). Medido em material real:
98 `TapeDescriptor` e só 21 locators com URL — e esses 21 são
os efeitos sonoros e as trilhas, não a imagem. Não há `URLString` para reescrever.

O que existe, e é a chave, é o **MobID**. O banco de NLEs confirma o mecanismo:

> o Avid casa o `SourceClip` de uma sequência de AAF a um `MasterMob` AMA online numa
> bin já aberta, **por MobID**

Então o relink, aqui, é: `LinkFile` traz o original online (e faz o **Avid** criar o
`amaMMOB.mdb`, a peça que só ele sabe criar), e este módulo reescreve o AAF para que os
`SourceClip` da composição apontem para o MobID **daquele** master AMA. O MC importa e
casa sozinho.

⚠️ O AAF de entrada nunca é modificado — sempre se escreve numa cópia.
"""

from __future__ import annotations

import logging
import shutil
from pathlib import Path

from origem import marcar_aaf

from .percurso import componentes

log = logging.getLogger("delapraca.aaf.remap")

_HEX = set("0123456789abcdefABCDEF")


def api_para_urn(mob_id: str) -> str:
    """MobID como a API do MC (ou o `ffprobe`) entrega → a forma URN que o AAF usa.

    As duas fontes externas dão a mesma representação, e nenhuma é a interna de
    pyaaf2/pyavb. Montar a URN e deixar a biblioteca interpretar é mais seguro que
    trocar bytes à mão: a endianness dos 16 bytes finais é MISTA (campos de 4, 2 e 2
    em little-endian, os 8 últimos em big-endian).

    ⚠️ O `0x` do ffprobe sai ANTES do filtro de hexadecimais: o `0` sobreviveria ao
    filtro (o `x` não), o valor sairia com 65 dígitos e **todos** os bytes deslocariam.
    """
    cru = mob_id.strip()
    if cru[:2].lower() == "0x":
        cru = cru[2:]
    if cru.lower().startswith("urn:smpte:umid:"):
        cru = cru[len("urn:smpte:umid:"):]
    h = "".join(c for c in cru if c in _HEX).lower()
    if len(h) != 64:
        raise ValueError(f"MobID com tamanho inesperado ({len(h)} dígitos): {mob_id!r}")
    return "urn:smpte:umid:" + ".".join(h[i:i + 8] for i in range(0, 64, 8))


def _chave(mob_id) -> str:
    """Normaliza qualquer representação para os 32 bytes em hex, sem pontuação.

    ⚠️ O prefixo sai ANTES do filtro. `urn:smpte:umid:` contribui com dois dígitos
    hexadecimais válidos — o **e** de `smpt`**e** e o **d** de `umi`**d** — e sem
    removê-lo a chave sai com 66 dígitos, começando por `ed`. É a mesma armadilha que o
    `0x` do ffprobe arma, num prefixo diferente, e ela não estoura: só faz duas
    representações do MESMO MobID compararem como diferentes.
    """
    s = str(mob_id).strip()
    baixo = s.lower()
    if baixo.startswith("urn:smpte:umid:"):
        s = s[len("urn:smpte:umid:"):]
    elif baixo.startswith("0x"):
        s = s[2:]
    return "".join(c for c in s if c in _HEX).lower()


def remapear_masters(
    aaf_entrada: str,
    aaf_saida: str,
    mapa: dict[str, str],
    *,
    renomear: dict[str, str] | None = None,
    achatar_subclipes: bool = True,
    achatar_group_clips: bool = True,
) -> dict:
    """Reescreve `aaf_entrada` em `aaf_saida` trocando a identidade dos masters.

    Args:
        mapa: `{mob_id_no_aaf → mob_id_do_master_online}`. Qualquer representação
            serve dos dois lados (URN, hífens da API, `0x` do ffprobe): a comparação é
            por hex normalizado.
        renomear: opcional, `{mob_id_no_aaf → nome novo}`. O Avid mostra o nome do
            master na bin e na timeline; alinhá-lo ao arquivo evita um clipe online
            exibindo o nome do transcode que não existe mais.
        achatar_subclipes: entrega a timeline com os clipes originais em vez dos
            subclipes (*decompose subclip*). **Ligado por padrão.**
        achatar_group_clips: substitui cada group clip pela câmera selecionada
            (*commit multicam*). **Ligado por padrão.**

    Returns:
        Contagens do que foi tocado, e a lista do que não foi encontrado.

    ⚠️ O achatamento roda **antes** do remap: depois dele os `SourceClip` apontam
    direto para os `MasterMob`, e a troca deixa de precisar atravessar subclipe.

    ⚠️ Troca-se o MobID do `MasterMob` **e** o `mob_id` de todo `SourceClip` que
    apontava para ele. Trocar só um dos lados produz uma composição que referencia um
    mob inexistente — e o Media Composer estoura em `PlayPipe::DoComp()`, um erro que
    não diz nada sobre a causa.
    """
    import aaf2
    from aaf2.mobid import MobID

    entrada, saida = Path(aaf_entrada), Path(aaf_saida)
    if entrada.resolve() == saida.resolve():
        raise ValueError("entrada e saída devem ser arquivos diferentes — o AAF de "
                         "origem nunca é modificado no lugar")
    if not entrada.is_file():
        raise FileNotFoundError(f"AAF não encontrado: {aaf_entrada}")
    if not mapa and not (achatar_subclipes or achatar_group_clips):
        raise ValueError("nada a fazer: mapa vazio e achatamento desligado")

    # {hex antigo → MobID novo}, e o mesmo para nomes. Mapa vazio é uso legítimo —
    # achatar a timeline sem relinkar nada.
    alvos = {_chave(velho): MobID(mobid=api_para_urn(novo)) for velho, novo in mapa.items()}
    nomes = {_chave(k): v for k, v in (renomear or {}).items()}

    saida.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(entrada, saida)

    mobs_trocados: list[dict] = []
    clips_trocados = 0
    vistos: set[str] = set()

    achatamento = {"subclipes": 0, "group_clips": 0, "orfaos_removidos": 0}

    with aaf2.open(str(saida), "rw") as f:
        # ⭐ Achatar PRIMEIRO. Depois disto os SourceClip apontam direto para os
        # MasterMob, e a troca abaixo vira uma substituição direta — sem atravessar
        # subclipe. E o AAF que o Media Composer vai importar não tem mais subclipes,
        # o que elimina o diálogo modal de conflito. Ver `denest.py`.
        if achatar_subclipes or achatar_group_clips:
            from .denest import achatar
            achatamento = achatar(f, subclipes=achatar_subclipes,
                                  group_clips=achatar_group_clips)

        # ⚠️ `f.content.mobs` é uma VISTA sobre um dicionário chaveado pelo MobID.
        # Trocar `mob.mob_id` rechaveia esse dicionário, e o pyaaf2 estoura com
        # "dictionary keys changed during iteration" — erro que fala do laço e não da
        # causa. Materializar a lista antes desacopla a leitura da escrita.
        todos = list(f.content.mobs)

        # 1) as referências primeiro, enquanto os MobIDs antigos ainda são os do AAF.
        #    Um SourceClip pode estar em qualquer profundidade (Sequence, NestedScope,
        #    Selector, OperationGroup, Transition), então varremos os componentes em vez
        #    de descer pela estrutura — imune a uma forma de aninhamento não prevista.
        for mob in todos:
            for slot in mob.slots:
                for comp in componentes(slot.segment):
                    ref = getattr(comp, "mob_id", None)
                    if ref is None:
                        continue
                    k = _chave(ref)
                    if k in alvos:
                        comp.mob_id = alvos[k]
                        clips_trocados += 1

        # 2) e só então a identidade dos próprios MasterMobs.
        for mob in todos:
            k = _chave(mob.mob_id)
            if k not in alvos:
                continue
            vistos.add(k)
            antes = mob.name
            mob.mob_id = alvos[k]
            if k in nomes:
                mob.name = nomes[k]
            mobs_trocados.append({
                "nome": antes, "nome_novo": mob.name,
                "de": k, "para": _chave(alvos[k]),
            })
        marcar_aaf(f)   # quem tratou fica registrado (origem.py)

    nao_achados = [m for m in alvos if m not in vistos]
    resultado = {
        "saida": str(saida),
        "masters_trocados": len(mobs_trocados),
        "referencias_trocadas": clips_trocados,
        "pedidos": len(alvos),
        "nao_encontrados": nao_achados,
        "subclipes_achatados": achatamento["subclipes"],
        "group_clips_achatados": achatamento["group_clips"],
        "orfaos_removidos": achatamento["orfaos_removidos"],
        "detalhe": mobs_trocados,
    }
    log.info("remap: %d/%d masters, %d referências (achatados: %d subclipes, %d grupos)",
             len(mobs_trocados), len(alvos), clips_trocados,
             achatamento["subclipes"], achatamento["group_clips"])
    return resultado
