"""Os itens que JUNTAM mídias na Carta Aberta: `.item.json` (plano §4.6). Imutáveis, na pasta do editor, como a `.ref.json`.

Um item não aponta arquivo nenhum: aponta os `id` das referências e diz como elas se juntam, em QUADROS do tempo de
cada master.

| tipo | campos | no Avid | no Premiere |
|---|---|---|---|
| `recorte` | `midia`, `entrada_q`, `saida_q` | subclipe de um master | subclipe |
| `sincronizado` | `imagem` {midia, inicio_q}, `som` {midia, inicio_q}, `duracao_q` | subclipe sincronizado | merged clip |
| `grupo` | `fontes` [{midia, deslocamento_q, imagem: bool}], `angulo`, `angulo_do_som` | group clip | multicâmera |

| `sequencia` | `trilhas` [{tipo V/A, k, clipes [{parte, inicio_q, entrada_q, fim_q}]}] | (collapse, na entrega) | nest |

⭐⭐ **Guardar TUDO, camada por camada** (autor, 2026-11-13): onde o modelo acima diz `midia`, a parte pode ser OUTRO
ITEM (`{"item": id}` no lugar de `{"midia": id}`) — a multicâmera feita de um nest que contém um merged clip vira três
itens ligados, nunca achatada nas mídias. Adaptar é tarefa da ENTREGA (no Avid o nest vira collapse). As camadas que
entram só porque outra as usa ficam OCULTAS (`vitrine`), como o fecho da bin do Avid. ⛔ O que não se reconhece recusa
o item DIZENDO o porquê — nunca some calado (o leitor antigo pulava o clipe que não apontava arquivo).

⛔⛔ Cada lado leva o SEU início, nunca "o offset do take" (medido: imagem em 0, som em 234 quadros; `avid/take.py`).
⛔ O grupo guarda as fontes INTEIRAS com o deslocamento (onde o quadro 0 de cada uma cai), não cabeças cortadas: o
Premiere corta a cabeça na multicâmera por ponto de entrada, o Avid não (banco `avb/sincronizacao-e-subclipes.md` §5).
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import referencias
from .projeto import CartaErro, Projeto, arquivos_do_editor, arquivos_ocultos, gravar_json

FORMATO = "item/1"
SUFIXO = ".item.json"
TIPOS = ("recorte", "sincronizado", "grupo", "sequencia")


#: estado de EDIÇÃO, não identidade: o ângulo escolhido e a duração (que o merged do Premiere não diz) não fazem de
#: um grupo/sincronizado OUTRO item (medido 2026-11-12: o G01-GRUPO-SOM lido do Avid e do Premiere, mesmos
#: deslocamentos 72/240/144/0, virava dois itens porque um tinha o ângulo e o outro não).
_ESTADO = ("carta_aberta", "id", "nome", "entrou_por", "angulo", "angulo_do_som", "duracao_q",
           "quadro")   # o quadro do PROJETO do Avid (2026-11-14): a mesma timeline sem ele não vira outra


def _conteudo(d: dict) -> dict:
    return {k: v for k, v in d.items() if k not in _ESTADO}


def criar(proj: Projeto, pasta: str | Path, nome: str, item: dict, entrou_por: dict) -> tuple[Path, dict, bool]:
    """(caminho, dados, novo?). ⭐ Idempotente pelo CONTEÚDO (o mesmo grupo mandado duas vezes não duplica); as mídias
    citadas têm de existir no projeto (uma referência por mídia antes do item que as junta)."""
    if item.get("tipo") not in TIPOS:
        raise CartaErro(f"tipo de item desconhecido: {item.get('tipo')!r}")
    ids = {d["id"] for _, d in referencias.todas(proj)}
    faltam = [m for m in midias_de(item) if m not in ids]
    if faltam:
        raise CartaErro(f"o item {nome!r} usa {len(faltam)} mídia(s) que o projeto não tem — mande as mídias antes")
    ids_itens = {d["id"] for _, d in todos(proj)}
    faltam = [i for k, i in partes(item) if k == "item" and i not in ids_itens]
    if faltam:
        raise CartaErro(f"o item {nome!r} usa {len(faltam)} item(ns) que o projeto não tem")
    for caminho, d in todos(proj):
        if _conteudo(d) == _conteudo(item):
            return caminho, d, False
    destino_dir = (proj.raiz / pasta).resolve()
    if not destino_dir.is_dir() or (proj.raiz.resolve() not in destino_dir.parents
                                    and destino_dir != proj.raiz.resolve()):
        raise CartaErro(f"a pasta {pasta} não existe no projeto")
    base = referencias._nome_de_arquivo(nome)
    n, destino = 1, destino_dir / (base + SUFIXO)
    while destino.exists():
        n += 1
        destino = destino_dir / f"{base} ({n}){SUFIXO}"
    dados = {"carta_aberta": FORMATO, "id": uuid.uuid4().hex, "nome": nome, **item, "entrou_por": entrou_por}
    gravar_json(destino, dados)
    return destino, dados, True


def _lugares(item: dict) -> list[dict]:
    """Os dicionários que apontam uma parte (`midia` ou `item`), em ordem."""
    t = item.get("tipo")
    if t == "recorte":
        return [item]
    if t == "sincronizado":
        return [item["imagem"], item["som"]]
    if t == "grupo":
        return list(item["fontes"])
    if t == "sequencia":
        return [c for tr in item.get("trilhas", []) for c in tr.get("clipes", [])]
    return []


def partes(item: dict) -> list[tuple[str, str]]:
    """O PRIMEIRO nível do que compõe o item: [("midia"|"item", id)], sem repetir, na ordem. É o que o "Selecionar ›
    Referenciados" marca e o que "Mostrar clipes referenciados" revela."""
    out: list[tuple[str, str]] = []
    for lugar in _lugares(item):
        par = ("item", lugar["item"]) if lugar.get("item") else ("midia", lugar.get("midia"))
        if par[1] and par not in out:
            out.append(par)
    return out


def midias_de(item: dict) -> list[str]:
    return [i for k, i in partes(item) if k == "midia"]


def ler(caminho: Path) -> dict | None:
    try:
        d = json.loads(Path(caminho).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return d if isinstance(d, dict) and d.get("carta_aberta") == FORMATO and d.get("id") else None


def todos(proj: Projeto) -> list[tuple[Path, dict]]:
    """Os itens do projeto, com o ÂNGULO VIGENTE do grupo (o do último "mandar", `angulos`)."""
    vigentes = angulos(proj)
    out = []
    for p in [*arquivos_do_editor(proj), *arquivos_ocultos(proj)]:
        if p.name.endswith(SUFIXO):
            d = ler(p)
            if d:
                out.append((p, {**d, **vigentes.get(d["id"], {})}))
    return out


# ── o ângulo do grupo: ESTADO, no diário ──────────────────────────────────────
#
# ⭐ Decisão do autor (2026-11-12, opção b): vale o ângulo do ÚLTIMO "mandar". O `.item.json` é imutável e o ângulo não
# é identidade (o grupo do Avid e a multicâmera do Premiere são o mesmo item com ângulos diferentes); por isso cada
# mudança é um fato `angulo` no diário — como as formas: só se acrescenta, e vale o mais recente.

_CAMPOS_DO_ANGULO = ("angulo", "angulo_do_som")


def angulos(proj: Projeto) -> dict[str, dict]:
    """{id do item: {angulo, angulo_do_som}} pelo fato `angulo` mais recente de cada item (todos os diários)."""
    from . import diario
    out: dict[str, dict] = {}
    for f in diario.fatos(proj):                         # em ordem de `ts`: o último sobrescreve
        if f["fato"] == "angulo" and f.get("item"):
            out[f["item"]] = {k: f.get(k) for k in _CAMPOS_DO_ANGULO}
    return out


def _seguir_o_angulo(proj: Projeto, existente: dict, item: dict, nle: str) -> bool:
    """O grupo JÁ registrado mandado de novo: o ângulo que ele traz passa a valer (um fato), se mudou. `None` = o NLE
    não diz (o som da multicâmera do Premiere) e mantém o vigente. Devolve se mudou."""
    if item.get("tipo") != "grupo":
        return False
    atual = {k: existente.get(k) for k in _CAMPOS_DO_ANGULO}
    novo = {k: (item.get(k) if item.get(k) is not None else atual[k]) for k in _CAMPOS_DO_ANGULO}
    if novo == atual:
        return False
    from . import diario
    diario.acrescentar(proj, {"fato": "angulo", "item": existente["id"], **novo, "nle": nle})
    return True


def registrar(proj: Projeto, pasta: str | Path, nome: str, item: dict, entrou_por: dict, conta: "ContaItens",
              visivel: bool = True) -> dict | None:
    """`criar` + a conta + o ângulo do último "mandar" (o grupo que já existia). `visivel=False`: a CAMADA que entrou
    só porque outro item a usa — fica oculta (e não entra na conta: quem conta é o item que o editor mandou).
    Devolve os dados do item (ou None se recusado)."""
    from . import vitrine
    if visivel and item.get("tipo") == "sequencia":
        hom = homonima(proj, nome)
        if hom and not vitrine.oculta(proj, hom[0]):
            c_hom, d_hom = hom
            if _conteudo(d_hom) == _conteudo(item):
                conta.repetidas[nome] = (f"já há uma cópia salva desta timeline na Carta, igual "
                                         f"({onde_esta(proj, c_hom)}): nada foi gravado")
                return d_hom
            from . import decidir
            decidir.guardar_timeline(proj, nome, str(pasta), item, entrou_por, c_hom, d_hom)
            conta.a_decidir[nome] = ("já há uma timeline com este nome na Carta, com outro conteúdo: atualizar, "
                                     "versionar ou cancelar (em A decidir)")
            return None
    try:
        caminho, dados, novo = (criar(proj, pasta, nome, item, entrou_por) if visivel
                                else _criar_oculto(proj, nome, item, entrou_por))
    except CartaErro as e:
        conta.recusados[nome] = str(e)
        return None
    if novo:
        if visivel:
            conta.novos.append(nome)
        return dados
    if visivel and vitrine.oculta(proj, caminho):            # estava oculto (removido, ou camada) e o editor o mandou
        from .vista import pasta_do_projeto
        vitrine.mostrar_em(proj, caminho, dados, SUFIXO, pasta_do_projeto(proj, str(pasta)))
        conta.novos.append(nome)
    elif visivel:
        conta.ja_estavam.append(nome)
    vigente = {**dados, **angulos(proj).get(dados["id"], {})}
    if _seguir_o_angulo(proj, vigente, item, entrou_por.get("nle", "")):
        conta.angulos.append(nome)
    return dados


# ── a timeline com o MESMO NOME (decisão do autor, 2026-11-20) ─────────────────
#
# ⭐ Mandar de novo uma timeline que já está na Carta: o NOME diz que é "a mesma timeline", o CONTEÚDO diz se mudou.
#   - igual: recusada, dito ("já há uma cópia salva") — nada se grava;
#   - diferente: o editor escolhe ATUALIZAR (o item conserva o id; o conteúdo anterior fica em `.carta/substituidos/`),
#     VERSIONAR ("NOME v02", um item novo ao lado) ou CANCELAR. A pergunta vai para a lista "A decidir"
#     (`decidir.guardar_timeline`): sobrevive a fechar a janela e os outros editores a veem.
# Antes (até 2026-11-20) o igual virava "já estava" calado e o diferente virava "NOME (2)" sem perguntar.

def homonima(proj: Projeto, nome: str) -> tuple[Path, dict] | None:
    """A timeline (item `sequencia`) já registrada com o mesmo nome, sem distinguir maiúsculas."""
    alvo = nome.strip().casefold()
    for c, d in todos(proj):
        if d.get("tipo") == "sequencia" and str(d.get("nome") or "").strip().casefold() == alvo:
            return c, d
    return None


def onde_esta(proj: Projeto, caminho: Path) -> str:
    try:
        rel = Path(caminho).resolve().parent.relative_to(proj.raiz.resolve())
    except ValueError:
        return "na pasta do projeto"
    return f"na pasta {rel.as_posix()}" if str(rel) not in ("", ".") else "na raiz do projeto"


_VERSAO = re.compile(r"^(.*?)\s+v(\d+)$", re.IGNORECASE)


def proximo_nome(proj: Projeto, nome: str) -> str:
    """`NOME v02` (ou o número seguinte livre; `NOME v03` se já se chama `… v02`)."""
    m = _VERSAO.match(nome.strip())
    base, n = (m.group(1), int(m.group(2))) if m else (nome.strip(), 1)
    usados = {str(d.get("nome") or "").strip().casefold() for _, d in todos(proj)}
    k = max(n, 1) + 1
    while f"{base} v{k:02d}".casefold() in usados:
        k += 1
    return f"{base} v{k:02d}"


def resumo(item: dict) -> dict:
    """O que a pergunta mostra para o editor comparar: trilhas, clipes e duração."""
    trilhas = item.get("trilhas") or []
    return {"trilhas": len(trilhas), "clipes": sum(len(t.get("clipes") or []) for t in trilhas),
            "duracao_q": item.get("duracao_q"), "fps": item.get("fps")}


def _criar_oculto(proj: Projeto, nome: str, item: dict, entrou_por: dict) -> tuple[Path, dict, bool]:
    from . import vitrine
    proj.ocultas.mkdir(parents=True, exist_ok=True)
    caminho, dados, novo = criar(proj, proj.ocultas, nome, item, entrou_por)
    if novo:
        caminho = vitrine.esconder(proj, caminho, dados, SUFIXO)
    return caminho, dados, novo


# ── do Avid: a bin ────────────────────────────────────────────────────────────

@dataclass
class ContaItens:
    novos: list[str] = field(default_factory=list)
    ja_estavam: list[str] = field(default_factory=list)
    #: item cujo master não tem referência no projeto: mande a mídia antes (dito, nunca calado)
    sem_referencia: dict[str, list[str]] = field(default_factory=dict)
    recusados: dict[str, str] = field(default_factory=dict)
    #: grupos já registrados cujo ângulo passou a ser o deste "mandar" (opção b do autor)
    angulos: list[str] = field(default_factory=list)
    #: o que entrou, mas talvez não como o editor pensou (o subclipe ainda não salvo foi como a mídia inteira)
    avisos: dict[str, str] = field(default_factory=dict)
    #: timeline com o mesmo nome e o MESMO conteúdo de uma que já está na Carta: recusada, dito
    repetidas: dict[str, str] = field(default_factory=dict)
    #: timeline com o mesmo nome e OUTRO conteúdo: a pergunta (atualizar/versionar/cancelar) foi para "A decidir"
    a_decidir: dict[str, str] = field(default_factory=dict)


def _ref_dos_masters(proj: Projeto) -> dict[str, str]:
    """{chave do master (64 hex): id da referência} — o que o `mandar_do_avid` gravou em `entrou_por.master`."""
    out = {}
    for _, d in referencias.todas(proj):
        m = (d.get("entrou_por") or {}).get("master")
        if m:
            out[str(m).lower()] = d["id"]
    return out


def do_avid(proj: Projeto, pasta: str, bin_avb: str | Path, nomes: set[str] | None = None,
            mob_ids: set[str] | None = None, offline: bool = False, quadro: list[int] | None = None) -> ContaItens:
    """Os subclipes, subclipes sincronizados, group clips e SEQUÊNCIAS (a timeline do editor, `timeline.py`) VISÍVEIS da
    bin viram `.item.json` (`nomes`/`mob_ids` (64 hex) = só estes). O master que falta no projeto volta em
    `sem_referencia` (a chave), para quem chama mandá-lo antes. `offline=True`: o master de uma TIMELINE que continua
    faltando (sem forma nesta máquina: o AMA) entra OFFLINE pelo que a bin diz (plano §4.7), e a conta o diz."""
    import avb

    from ..avid import take as _take
    from ..midia import cache as _cache
    from . import timeline as _timeline

    def chave(mob_id) -> str:
        try:
            return _cache.de_umid(str(mob_id)).lower()
        except _cache.ChaveInvalida:
            return ""

    refs = _ref_dos_masters(proj)
    conta = ContaItens()
    masters_das_timelines: dict[str, dict] = {}
    with avb.open(str(bin_avb)) as f:
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        alvos = [(i.mob.name, i.mob, _take.especie(i.mob)) for i in f.content.items
                 if i.user_placed and (nomes is None or i.mob.name in nomes)
                 and (mob_ids is None or chave(i.mob.mob_id) in mob_ids)]
        lidos = []
        for nome, mob, esp in alvos:
            if esp == "grupo":
                try:
                    lidos.append((nome, _grupo(mob, por_id, chave)))
                except CartaErro as e:                  # um grupo ilegível é 1 de N: dito, e os outros seguem
                    conta.recusados[nome] = str(e)
            elif esp == "subclipe":
                lidos.append((nome, None))
            elif esp == "sequencia":
                try:
                    item, masters = _timeline.do_avid(f, mob, chave)
                    if quadro:                           # o quadro do PROJETO do Avid (a sequência não guarda o seu)
                        item["quadro"] = list(quadro)
                    lidos.append((nome, item))
                    masters_das_timelines.update(masters)
                except Exception as e:  # noqa: BLE001 — uma timeline ilegível é 1 de N, e o motivo é dito
                    conta.recusados[nome] = f"a timeline não foi lida: {e}"
            elif esp not in ("master", "fonte") and (nomes is not None or mob_ids is not None):
                conta.recusados[nome] = f"{esp}: ainda não entra na Carta"
    for nome, grupo in lidos:
        try:
            item = grupo if grupo is not None else _subclipe(str(bin_avb), nome, chave)
        except Exception as e:  # noqa: BLE001 — um item ilegível é 1 de N, e o motivo é dito
            conta.recusados[nome] = str(e)
            continue
        subs: dict[str, tuple[str, dict]] = {}
        if item.get("timeline"):
            # a camada do SUBCLIPE: cada um que a timeline usa vira item OCULTO (o fecho da bin, como no Avid)
            for mob in sorted({c["subclipe"] for t in item["trilhas"] for c in t["clipes"] if c.get("subclipe")}):
                try:
                    subs[mob] = (_nome_do_mob(str(bin_avb), mob), _subclipe(str(bin_avb), mob, chave))
                except Exception as e:  # noqa: BLE001 — o clipe continua pelo master; o motivo é dito
                    conta.avisos[mob] = f"o subclipe não foi lido (o clipe vai pelo master): {e}"
        faltam = [m for m in midias_de(item) + [x for _n, si in subs.values() for x in midias_de(si)] if m not in refs]
        faltam = list(dict.fromkeys(faltam))
        if faltam and offline and item.get("timeline"):
            feitos = _timeline.referencias_offline(proj, faltam, masters_das_timelines)
            for k, n in feitos.items():
                conta.avisos[n] = f"entrou OFFLINE (sem mídia achada nesta máquina; usada pela timeline {nome})"
            refs = _ref_dos_masters(proj)
            faltam = [m for m in midias_de(item) if m not in refs]
        if faltam:
            conta.sem_referencia[nome] = faltam
            continue
        if subs:
            ids_subs = {}
            for mob, (nome_sub, si) in subs.items():
                d = registrar(proj, pasta, nome_sub, _trocar_chaves(si, refs),
                              {"nle": "avid", "bin": Path(bin_avb).name, "camada_de": nome}, conta, visivel=False)
                if d is not None:
                    ids_subs[mob] = d["id"]
            for t in item["trilhas"]:
                for c in t["clipes"]:
                    mob = c.pop("subclipe", None)
                    if mob in ids_subs:
                        c["item"] = ids_subs[mob]
                    else:
                        c.pop("entrada_no_item_q", None)
        item = _trocar_chaves(item, refs)
        registrar(proj, pasta, nome, item, {"nle": "avid", "bin": Path(bin_avb).name}, conta)
    return conta


def _nome_do_mob(bin_avb: str, mob_id: str) -> str:
    import avb
    with avb.open(bin_avb) as f:
        for m in f.content.mobs:
            if str(m.mob_id) == mob_id:
                return m.name or mob_id
    return mob_id


def _subclipe(bin_avb: str, nome: str, chave) -> dict:
    from ..avid import take as _take
    t = _take.resolver(bin_avb, nome, procurar_arquivos=False)
    img, som = t.imagem, t.som
    if img and som and chave(img.mob_id) != chave(som.mob_id):
        lado_som = {"midia": chave(som.mob_id), "inicio_q": som.inicio_frames}
        canais = _canais_do_subclipe(bin_avb, nome)
        if canais:
            lado_som["canais"] = canais
        return {"tipo": "sincronizado", "duracao_q": t.duracao_frames,
                "imagem": {"midia": chave(img.mob_id), "inicio_q": img.inicio_frames}, "som": lado_som}
    f = img or som
    if f is None:
        raise CartaErro(f"o subclipe {nome!r} não aponta master nenhum")
    return {"tipo": "recorte", "midia": chave(f.mob_id), "entrada_q": f.inicio_frames,
            "saida_q": f.inicio_frames + t.duracao_frames}


def _canais_do_subclipe(bin_avb: str, nome_ou_id: str) -> list[int]:
    """As trilhas do master de SOM que o subclipe usa, em ordem (o canal do OP-Atom: `_A01` = 1). O merged do Premiere
    leva estes, e só estes (medido n'PRODUCAO-A: gravador de 10 canais com subclipe de 5; de 4 com subclipe de 3)."""
    import avb

    from ..avid.take import _source_clip
    with avb.open(bin_avb) as f:
        for m in f.content.mobs:
            if str(m.mob_id) != nome_ou_id and m.name != nome_ou_id:
                continue
            if _take_especie(m) != "subclipe":
                continue
            out = []
            for tr in m.tracks:
                if str(getattr(tr, "media_kind", "")) != "sound":
                    continue
                sc = _source_clip(tr)
                if sc is not None and getattr(sc, "track_id", None):
                    out.append(int(sc.track_id))
            return out
    return []


def _take_especie(mob) -> str:
    from ..avid import take as _take
    return _take.especie(mob)


def _grupo(mob, por_id: dict, chave) -> dict:
    """O group clip (banco `avb/sincronizacao-e-subclipes.md` §5): o mob de ALINHAMENTO tem uma trilha por trilha de cada
    fonte, `Filler(deslocamento) · SourceClip(master) · Filler`; os `Selector` do grupo dizem o ângulo escolhido."""
    seletores = [(t.component.media_kind, t.component) for t in mob.tracks
                 if type(t.component).__name__ == "Selector"]
    if not seletores:
        raise CartaErro("group clip sem Selector")
    alin_id = str(seletores[0][1].tracks[0].component.mob_id)
    alin = por_id.get(alin_id)
    if alin is None:
        raise CartaErro("o mob de alinhamento do grupo não está na bin")
    trilhas = {}                                   # (kind, índice no alinhamento) → (master, deslocamento)
    contagem = {"picture": 0, "sound": 0}
    for t in alin.tracks:
        kind = t.component.media_kind
        if kind not in contagem:
            continue
        contagem[kind] += 1
        desl, master = 0, None
        for c in getattr(t.component, "components", []):
            nome_c = type(c).__name__
            if nome_c == "Filler" and master is None:
                desl += int(c.length)
            elif nome_c == "SourceClip":
                # ⛔⛔ "Guardar tudo" (autor, 2026-11-13): se a fonte do ângulo NÃO é um master (o grupo feito de
                #    subclipes ou de sincronizados), achatá-la no master perderia a camada. Isso nunca foi MEDIDO numa
                #    bin real (o G01 é agrupado direto dos masters): recusa dizendo, até haver um group clip assim.
                fonte = por_id.get(str(c.mob_id))
                if fonte is not None and _take_especie(fonte) not in ("master", "fonte"):
                    raise CartaErro(f"o ângulo vem de um {_take_especie(fonte)} ({fonte.name!r}), não de um master: "
                                    "o grupo feito de subclipes/sincronizados ainda não é lido (falta medir num real)")
                master = chave(c.mob_id)
                break
        if master:
            trilhas[(kind, contagem[kind])] = (master, desl)
    fontes: dict[str, dict] = {}
    for (kind, _), (master, desl) in sorted(trilhas.items()):
        f = fontes.setdefault(master, {"midia": master, "deslocamento_q": desl, "imagem": False})
        f["imagem"] = f["imagem"] or kind == "picture"
    def escolhido(kind):
        sel = next((s for k, s in seletores if k == kind), None)
        if sel is None:
            return None
        alvo = sel.tracks[int(sel.selected)].component
        return trilhas.get((kind, int(alvo.track_id)), (None, 0))[0]
    return {"tipo": "grupo", "fontes": list(fontes.values()),
            "angulo": escolhido("picture"), "angulo_do_som": escolhido("sound")}


def _trocar_chaves(item: dict, refs: dict[str, str]) -> dict:
    """As chaves de master viram os `id` das referências do projeto."""
    r = lambda k: refs.get(k, k) if k else k  # noqa: E731
    if item["tipo"] == "sequencia":
        return {**item, "trilhas": [{**t, "clipes": [{**c, "midia": r(c["midia"])} if c.get("midia") else c
                                                     for c in t["clipes"]]} for t in item["trilhas"]]}
    if item["tipo"] == "recorte":
        return {**item, "midia": r(item["midia"])}
    if item["tipo"] == "sincronizado":
        return {**item, "imagem": {**item["imagem"], "midia": r(item["imagem"]["midia"])},
                "som": {**item["som"], "midia": r(item["som"]["midia"])}}
    return {**item, "fontes": [{**f, "midia": r(f["midia"])} for f in item["fontes"]],
            "angulo": r(item.get("angulo")), "angulo_do_som": r(item.get("angulo_do_som"))}


# ── do Premiere: o .prproj SALVO ──────────────────────────────────────────────

_CANAL_OPATOM = re.compile(r"_A(\d+)\.mxf$", re.I)


def _canais_opatom(sons: list[dict], parte) -> list[int]:
    """Os canais do som de um merged feito da OP-Atom: um arquivo por canal (`…_A03.mxf` = canal 3), todos da MESMA mídia.
    ⭐ É a mesma noção do `canais` do subclipe sincronizado do Avid (as trilhas A1…An do master): sem ela, o merged que
    o Carta levou ao Premiere e voltou por arrasto virava um SEGUNDO item igual (medido no Windows, 2026-11-18,
    `11-01-01`). Fora da OP-Atom (WAV multicanal) devolve [] e nada muda."""
    if not sons or any("arquivo" not in t for t in sons):
        return []
    if len({str(parte(t)) for t in sons}) != 1:
        return []
    ks = [_CANAL_OPATOM.search(str(t["arquivo"])) for t in sons]
    return sorted({int(m.group(1)) for m in ks}) if all(ks) else []


def _leitor_do_prproj(prproj: str | Path):
    import sys as _sys
    raiz = Path(__file__).resolve().parents[2] / "modulos" / "conformar"
    if str(raiz) not in _sys.path:
        _sys.path.insert(0, str(raiz))
    from motor.prproj.leitura import Leitor, _int  # noqa: PLC0415
    from motor.prproj.projeto import Projeto as _Prproj  # noqa: PLC0415
    p = _Prproj(str(prproj))
    return p, Leitor(p), _int


def _trilhas_da_sequencia(p, le, _int, s) -> list[dict]:
    """[{tipo V/A, k, inicio_q, entrada_q, fim_q} + {arquivo} | {sequencia (ObjectUID), nome_seq} | {desconhecido}].

    `TrackItem › SubClip › Clip › Source`: a fonte é `Media.FilePath` (um arquivo) ou `Sequence` (o clipe vem de uma
    sequência aninhada — `VideoSequenceSource`/`AudioSequenceSource`, banco `prproj/audio-adaptativo.md`: nest, merged
    ou multicâmera usados como clipe). ⛔ Antes o clipe sem arquivo era PULADO calado — e a camada se perdia."""
    _, tpq = le.quadro(s)
    q = (lambda t: round(_int(t) / tpq)) if tpq else (lambda t: _int(t))
    out = []
    for tipo in ("Video", "Audio"):
        for k, (_, its) in enumerate(le.trilhas(s, tipo), 1):
            for it in its:
                sc = p.ref(it, "SubClip")
                clip = p.ref(sc, "Clip") if sc is not None else None
                fonte = p.ref(clip, "Source") if clip is not None else None
                if fonte is None:
                    continue                                   # vazio, transição: não é parte de nada
                c = {"tipo": tipo[0], "k": k, "inicio_q": q(p.campo(it, "Start")), "fim_q": q(p.campo(it, "End")),
                     "entrada_q": q(p.campo(clip, "InPoint"))}
                media = p.ref(fonte, "Media")
                arq = p.campo(media, "FilePath") if media is not None else None
                seq = p.ref(fonte, "Sequence")
                if arq:
                    c["arquivo"] = arq
                elif seq is not None and seq.uid:
                    c["sequencia"], c["nome_seq"] = seq.uid, p.nome_da_sequencia(seq)
                else:
                    c["desconhecido"] = getattr(fonte, "tipo", None) or "fonte sem arquivo nem sequência"
                out.append(c)
    return out


def _sequencias_multicam(p) -> dict[str, int | None]:
    """{`ObjectUID` da sequência multicâmera: `TrackIndex`}. ⚠️ A multicâmera RECÉM-CRIADA (26.0.2 Mac, 2026-11-12) não
    tem o `Source.Monitor.Multicam.SwitchOnMulticamName` que o Conformar procura; a marca está no MASTERCLIP que a
    representa na bin (`<Source.Monitor.Multicam.Enabled>true`), que leva à sequência por `Clip › VideoSequenceSource`.
    O `Source.Monitor.Multicam.TrackIndex` do mesmo MasterClip é o ângulo do Source (a trilha de vídeo, do 0)."""
    import re
    out: dict[str, int | None] = {}
    for mc in p.de_tipo("MasterClip"):
        corpo = p.corpo(mc)
        if "<Source.Monitor.Multicam.Enabled>true" not in corpo:
            continue
        ti = re.search(r"<Source.Monitor.Multicam.TrackIndex>(\d+)<", corpo)
        for oid in re.findall(r'<Clip Index="\d+" ObjectRef="(\d+)"/>', corpo):
            clip = p.obj(oid)
            fonte = p.ref(clip, "Source") if clip is not None else None
            seq = p.ref(fonte, "Sequence") if fonte is not None else None
            if seq is not None and seq.uid:
                out[seq.uid] = int(ti.group(1)) if ti else None
    return out


TICKS_POR_SEGUNDO = 254016000000


def _ticks_por_quadro(taxa: str) -> int:
    """A taxa do projeto da Carta ("24000/1001", "23.976", "25") em ticks do Premiere por quadro; 0 se ilegível."""
    from fractions import Fraction

    from ..avid.take import fracao_da_taxa
    t = str(taxa).strip().replace(",", ".")
    try:
        f = Fraction(t) if "/" in t else fracao_da_taxa(float(t))
    except (TypeError, ValueError, ZeroDivisionError):
        return 0
    return round(TICKS_POR_SEGUNDO / f) if f else 0


def _subclipes(p, _int) -> dict[str, dict]:
    """{nome: {arquivo, inicio_t, fim_t, tpq}} dos SUBCLIPES da bin no `.prproj` SALVO.

    ⭐ MEDIDO (2026-11-12, Premiere 26.0.2 Mac, `G01 PREMIERE DO EDITOR v02`): o subclipe é um `MasterClip` cujo
    `Clip › Source` (`MediaSource › Content`) tem `StartBoundary`/`EndBoundary` — em ticks contados do 1º quadro do
    ARQUIVO, não do TC (o `LoggingInfo.MediaInPoint` é que leva o TC: 9157873652928000 = o início do arquivo + 200 q).
    Nenhum master comum, merged ou multicâmera tem a marca. `G01_CAM3.sub.01` = 200–400 q, o MESMO recorte do Avid.
    ⛔ Nunca o `getInPoint()` da API: devolve o master inteiro (banco `premiere-cep/subclipe-e-merged-clip.md`)."""
    import re
    out: dict[str, dict] = {}
    for mc in p.de_tipo("MasterClip"):
        corpo = p.corpo(mc)
        nome = re.search(r"<Name>([^<]*)</Name>", corpo)
        clips = re.findall(r'<Clip Index="\d+" ObjectRef="(\d+)"/>', corpo)
        if not nome or not clips:
            continue
        clip = p.obj(clips[0])
        fonte = p.ref(clip, "Source") if clip is not None else None
        if fonte is None:
            continue
        b = re.search(r"<StartBoundary>(-?\d+)</StartBoundary>\s*<EndBoundary>(-?\d+)</EndBoundary>", p.corpo(fonte))
        media = p.ref(fonte, "Media")
        arq = p.campo(media, "FilePath") if media is not None else None
        if not b or not arq:
            continue
        tpq = 0
        log = re.search(r'<LoggingInfo ObjectRef="(\d+)"', corpo)
        if log and "<VideoStream " in p.corpo(media):        # no som, o "quadro" do arquivo não é o do projeto
            tpq = _int(p.campo(p.obj(log.group(1)), "MediaFrameRate") or 0)
        out[nome.group(1)] = {"arquivo": arq, "inicio_t": int(b.group(1)), "fim_t": int(b.group(2)), "tpq": tpq}
    return out


def do_premiere(proj: Projeto, pasta: str, prproj: str | Path, nomes: set[str] | None = None) -> ContaItens:
    """Os merged clips (→ `sincronizado`), as sequências multicâmera (→ `grupo`) e os subclipes (→ `recorte`) do
    `.prproj` SALVO viram `.item.json`. O arquivo de cada trilha vira o `id` da referência pelo caminho que o diário
    guarda NESTA máquina."""
    from . import diario
    por_arquivo = {f["arquivo"]: mid for mid, fs in diario.formas(proj).items() for f in fs
                   if f.get("maquina") == diario.maquina()}
    p, le, _int = _leitor_do_prproj(prproj)
    multicam = _sequencias_multicam(p)
    conta = ContaItens()
    for nome, sc in _subclipes(p, _int).items():
        if nomes is not None and nome not in nomes:
            continue
        if sc["arquivo"] not in por_arquivo:
            conta.sem_referencia[nome] = [Path(sc["arquivo"]).name]
            continue
        tpq = sc["tpq"] if 0 < sc["tpq"] and 1 <= TICKS_POR_SEGUNDO / sc["tpq"] <= 300 else _ticks_por_quadro(proj.taxa)
        if not tpq:
            conta.recusados[nome] = "sem taxa para contar o recorte em quadros (a taxa do projeto da Carta)"
            continue
        item = {"tipo": "recorte", "midia": por_arquivo[sc["arquivo"]],
                "entrada_q": round(sc["inicio_t"] / tpq), "saida_q": round(sc["fim_t"] / tpq)}
        registrar(proj, pasta, nome, item, {"nle": "premiere", "prproj": Path(prproj).name}, conta)
    por_uid = {sq.uid: sq for sq in p.de_tipo("Sequence") if sq.uid}
    feitos: dict[str, str] = {}                 # ObjectUID → id do item (cada camada uma vez por "mandar")
    entrou = {"nle": "premiere", "prproj": Path(prproj).name}

    def camada(s, visivel: bool) -> str | None:
        """O item de uma sequência (merged → sincronizado, multicâmera → grupo, outra → sequencia/nest), com as camadas
        de dentro ANTES (ocultas). Devolve o id, ou None (recusado, dito na conta)."""
        if s.uid in feitos:
            return feitos[s.uid]
        nome = p.nome_da_sequencia(s)
        tr = _trilhas_da_sequencia(p, le, _int, s)
        estranho = [t for t in tr if "desconhecido" in t]
        if estranho:
            conta.recusados[nome] = f"um clipe de dentro não aponta arquivo nem sequência ({estranho[0]['desconhecido']})"
            return None
        faltam = sorted({t["arquivo"] for t in tr if "arquivo" in t and t["arquivo"] not in por_arquivo})
        if faltam:
            conta.sem_referencia[nome] = [Path(a).name for a in faltam]
            return None
        for t in tr:                                          # as camadas de dentro primeiro
            if "sequencia" in t:
                de_dentro = por_uid.get(t["sequencia"])
                iid = camada(de_dentro, False) if de_dentro is not None else None
                if iid is None:
                    conta.recusados.setdefault(nome, f"a camada {t.get('nome_seq')!r} de dentro não entrou")
                    return None
                t["item"] = iid
        parte = lambda t: {"item": t["item"]} if "item" in t else {"midia": por_arquivo[t["arquivo"]]}  # noqa: E731
        chave = lambda t: t.get("item") or t.get("arquivo")  # noqa: E731
        if le.eh_merged(s):
            imagem = next((t for t in tr if t["tipo"] == "V"), None)
            sons = [t for t in tr if t["tipo"] == "A" and (imagem is None or chave(t) != chave(imagem))]
            if imagem is None or not sons:
                conta.recusados[nome] = "merged sem imagem ou sem som de outra fonte"
                return None
            item = {"tipo": "sincronizado", "duracao_q": None,
                    "imagem": {**parte(imagem), "inicio_q": imagem["entrada_q"]},
                    "som": {**parte(sons[0]), "inicio_q": sons[0]["entrada_q"]}}
            canais = _canais_opatom(sons, parte)
            if canais:
                item["som"]["canais"] = canais
        elif le.eh_multicam(s) or s.uid in multicam:
            # ⭐ início na sequência − entrada na fonte = onde o quadro 0 da fonte cai (banco, "O caminho de VOLTA")
            fontes: dict[str, dict] = {}
            for t in tr:
                f = fontes.setdefault(chave(t), {**parte(t), "deslocamento_q": t["inicio_q"] - t["entrada_q"],
                                                 "imagem": False})
                f["imagem"] = f["imagem"] or t["tipo"] == "V"
            minimo = min(f["deslocamento_q"] for f in fontes.values())
            for f in fontes.values():
                f["deslocamento_q"] -= minimo
            # o ângulo: a fonte da trilha de vídeo `TrackIndex` (do 0). ⚠️ O som do Premiere não tem "ângulo" medido.
            idx = multicam.get(s.uid)
            v = next((t for t in tr if t["tipo"] == "V" and idx is not None and t["k"] == idx + 1), None)
            angulo = (v.get("item") or por_arquivo[v["arquivo"]]) if v else None
            item = {"tipo": "grupo", "fontes": list(fontes.values()), "angulo": angulo, "angulo_do_som": None}
        else:
            trilhas: dict[tuple, list] = {}
            for t in tr:
                trilhas.setdefault((t["tipo"], t["k"]), []).append(
                    {**parte(t), "inicio_q": t["inicio_q"], "entrada_q": t["entrada_q"], "fim_q": t["fim_q"]})
            item = {"tipo": "sequencia",
                    "trilhas": [{"tipo": tp, "k": k, "clipes": cl} for (tp, k), cl in sorted(trilhas.items())]}
        dados = registrar(proj, pasta, nome, item, {**entrou, "uid": s.uid}, conta, visivel=visivel)
        if dados is None:
            return None
        feitos[s.uid] = dados["id"]
        return dados["id"]

    for s in p.de_tipo("Sequence"):
        nome = p.nome_da_sequencia(s)
        if nomes is not None and nome not in nomes:
            continue
        if not (le.eh_merged(s) or le.eh_multicam(s) or s.uid in multicam):
            continue                                        # a timeline do editor é da C3
        camada(s, True)
    return conta


def nomes_de_subclipes(prproj: str | Path) -> set[str]:
    """Os nomes dos subclipes da bin no `.prproj` salvo: o arquivo deles é do MASTER, que entra oculto."""
    p, _, _int = _leitor_do_prproj(prproj)
    return set(_subclipes(p, _int))


def arquivos_dos_itens(prproj: str | Path, nomes: set[str]) -> list[str]:
    """Os arquivos das trilhas dos merged/multicâmera (e do subclipe) de nome `nomes` no `.prproj` — para mandá-los
    ANTES dos itens."""
    p, le, _int = _leitor_do_prproj(prproj)
    multicam = _sequencias_multicam(p)
    out: list[str] = [sc["arquivo"] for n, sc in _subclipes(p, _int).items() if n in nomes]
    out = list(dict.fromkeys(out))
    por_uid = {sq.uid: sq for sq in p.de_tipo("Sequence") if sq.uid}
    vistas: set[str] = set()

    def descer(s) -> None:                      # as camadas de dentro (nest, merged) também: tudo é guardado
        if s is None or s.uid in vistas:
            return
        vistas.add(s.uid)
        for t in _trilhas_da_sequencia(p, le, _int, s):
            if "arquivo" in t:
                out.append(t["arquivo"])
            elif "sequencia" in t:
                descer(por_uid.get(t["sequencia"]))

    for s in p.de_tipo("Sequence"):
        if p.nome_da_sequencia(s) in nomes and (le.eh_merged(s) or le.eh_multicam(s) or s.uid in multicam):
            descer(s)
    return list(dict.fromkeys(out))      # ⛔ A1 e A2 do MESMO WAV: o filtro dentro da compreensão não via o par
