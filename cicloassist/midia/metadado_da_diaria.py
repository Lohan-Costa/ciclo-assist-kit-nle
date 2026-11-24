"""O lado SEM IA do agente de metadado (fase A3 do plano `2026-11-08-agentes.md`): resumir a diária e conferir o que ele propõe.

O código prepara a entrada (só o que o programa não resolveu, em formas e contagens) e confere a saída campo por campo. Na A0, "cobre 100%"
enganava: a regra só lia o take. Aqui cada campo tem a sua conta, e a contradição com o metadado reprova.

⛔ O bext e o iXML são lidos à parte: no Zoom F8 os dois trazem SCENE diferentes (banco, `metadado-de-canal-do-som-direto.md` §7a).
"""
from __future__ import annotations

import os
import re
import sys
import unicodedata
import uuid
from collections import Counter, defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path

from . import bwf as _bwf

# ⭐ A memória e o leitor de claquete são do motor do Sincronizar, em outra venv; os dois só usam a biblioteca padrão.
# `append`, nunca `insert`: nada do motor pode encobrir um pacote nosso.
_MOTOR = str(Path(__file__).resolve().parents[2] / "modulos" / "sincronizar" / "motor")
if _MOTOR not in sys.path:
    sys.path.append(_MOTOR)

from media import claquete as _claquete  # noqa: E402
from media import memoria_da_producao as memoria  # noqa: E402

TETO_FORMAS = 30
TETO_REGRAS = 12
TETO_PERGUNTAS = 8
TETO_OPCOES = 4
TAMANHO_DA_OPCAO = 40
_AMOSTRAS = 3
_EXTENSOES = {".wav", ".bwf"}
_FIM_DE_CANAL = re.compile(r"[_-]\d+$")


@dataclass(frozen=True)
class Arquivo:
    nome: str
    pasta: str
    scene_ixml: str | None = None
    take_ixml: str | None = None
    scene_bext: str | None = None
    take_bext: str | None = None
    projeto: str | None = None
    nota: str | None = None
    canais: tuple[str, ...] = ()
    descarte: bool = False


@dataclass(frozen=True)
class Particao:
    descartados: list[Arquivo]
    pela_memoria: list[Arquivo]
    pelo_programa: list[Arquivo]
    restantes: list[Arquivo]
    ninguem_sabe: list[Arquivo] = field(default_factory=list)


def _do_bext(desc: dict) -> dict[str, str]:
    """`sSCENE`/`zSCENE` → `SCENE`: cada gravador prefixa de um jeito."""
    return {re.sub(r"^[a-z](?=[A-Z])", "", k).upper(): v.strip() for k, v in (desc or {}).items()}


def _ler(caminho: Path, raiz: Path) -> Arquivo | None:
    meta = _bwf.ler(str(caminho))
    if not meta:
        return None
    bext, xml = _do_bext(meta.get("desc") or {}), meta.get("ixml") or ""
    relativo = caminho.parent.relative_to(raiz)
    return Arquivo(
        nome=unicodedata.normalize("NFC", caminho.stem), pasta=unicodedata.normalize("NFC", relativo.as_posix()),
        scene_ixml=_bwf._tag(xml, "SCENE") or None, take_ixml=_bwf._tag(xml, "TAKE") or None,
        scene_bext=bext.get("SCENE") or None, take_bext=bext.get("TAKE") or None,
        projeto=_bwf._tag(xml, "PROJECT") or None, nota=_bwf._tag(xml, "NOTE") or bext.get("NOTE") or None,
        canais=tuple(_bwf._trilhas(meta).values()), descarte=bool(_claquete.e_descartado(caminho.relative_to(raiz))))


def coletar(pasta: str | Path) -> list[Arquivo]:
    """Os WAV da pasta e das subpastas. ⛔ Só o cabeçalho é lido. As pastas com `_` no começo (o que os módulos geram) e os `._` do macOS ficam de fora."""
    raiz = Path(pasta)
    saida: list[Arquivo] = []
    for atual, subpastas, arquivos in os.walk(raiz):
        subpastas[:] = sorted(s for s in subpastas if not s.startswith(("_", ".")))
        for nome in sorted(arquivos):
            caminho = Path(atual) / nome
            if not nome.startswith(".") and caminho.suffix.lower() in _EXTENSOES:
                lido = _ler(caminho, raiz)
                if lido:
                    saida.append(lido)
    return saida


def coletar_arquivos(caminhos) -> list[Arquivo]:
    """Os WAV de uma lista de caminhos (os de uma bin do NLE). Quem está offline fica de fora, porque não há cabeçalho para ler."""
    saida: list[Arquivo] = []
    for caminho in (Path(c) for c in caminhos):
        if caminho.suffix.lower() in _EXTENSOES and not caminho.name.startswith("."):
            # ⭐ Da raiz do disco: a pasta de descarte do técnico pode estar em qualquer nível.
            lido = _ler(caminho, Path(caminho.anchor))
            if lido:
                saida.append(replace(lido, pasta=unicodedata.normalize("NFC", caminho.parent.name)))
    return saida


def _formas_que_ninguem_sabe(nao_se_sabe) -> list[str]:
    """Os trechos com dois números ou mais (`17B-18-1`) apontam formas, mesmo no meio de uma frase: o modelo gravou "17B-18-1 e 18-3-2 (três números)" (teste do autor, 2026-11-08).

    Um trecho só de letras (`ct`) ou um número solto não aponta: a forma pode ter o resto legível, e só a pergunta sobre ele é barrada."""
    trechos = (t for i in nao_se_sabe for t in re.split(r"[\s,;()]+", i.split(":", 1)[0]))
    return [memoria.forma_de(t) for t in trechos if memoria.forma_de(t).count("#") >= 2]


def _ninguem_sabe(forma: str, sem_resposta: list[str]) -> bool:
    """O trecho é o começo da forma, e ela não continua com outro número: `#-#` não pega `#-#-#T#`."""
    return any(re.match(re.escape(s) + r"(?![-_.]#)", forma) for s in sem_resposta)


def particionar(arquivos: list[Arquivo], regras=(), nao_se_sabe=()) -> Particao:
    """Quem o programa já lê não vai ao modelo: na A0 ele gastou pergunta confirmando rótulo que a leitura já conhece.

    ⛔ O que o editor disse não saber também não vai: a pergunta não pode voltar, nem com outras palavras, e a filtragem de texto não pega paráfrase."""
    p = Particao([], [], [], [])
    sem_resposta = _formas_que_ninguem_sabe(nao_se_sabe)
    for a in arquivos:
        if a.descarte:
            p.descartados.append(a)
        elif memoria.aplicar(regras, a.nome):
            p.pela_memoria.append(a)
        elif _claquete.ler(a.nome):
            p.pelo_programa.append(a)
        elif _ninguem_sabe(memoria.forma_de(a.nome), sem_resposta):
            p.ninguem_sabe.append(a)
        else:
            p.restantes.append(a)
    return p


def _agrupar(arquivos: list[Arquivo]) -> dict[str, list[Arquivo]]:
    grupos: dict[str, list[Arquivo]] = defaultdict(list)
    for a in arquivos:
        grupos[memoria.forma_de(a.nome)].append(a)
    return dict(sorted(grupos.items(), key=lambda kv: (-len(kv[1]), kv[0])))


def _amostra(a: Arquivo) -> dict[str, str]:
    campos = {"nome": a.nome, "iXML_SCENE": a.scene_ixml, "iXML_TAKE": a.take_ixml, "bext_SCENE": a.scene_bext, "bext_TAKE": a.take_bext}
    return {k: v for k, v in campos.items() if v}


def _distintos(valores, teto: int, tamanho: int = 80) -> list[str]:
    return [v[:tamanho] for v, _ in Counter(v for v in valores if v).most_common(teto)]


def rotulos_conhecidos() -> dict[str, list[str]]:
    return {"episodio": list(_claquete.ROTULOS_DE_EPISODIO), "cena": list(_claquete.ROTULOS_DE_CENA),
            "plano": list(_claquete.ROTULOS_DE_PLANO), "take": list(_claquete.ROTULOS_DE_TAKE)}


def entrada_do_agente(diaria: str, p: Particao, mem: memoria.Memoria | None) -> tuple[dict, int]:
    """`(entrada, formas que não couberam)`. A entrada é pequena de propósito: formas e amostras, nunca a lista inteira."""
    grupos = _agrupar(p.restantes)
    formas = [{"forma": f, "quantos": len(v), "amostras": [_amostra(a) for a in v[:_AMOSTRAS]]} for f, v in list(grupos.items())[:TETO_FORMAS]]
    resolvidas = Counter(memoria.forma_de(a.nome) for a in p.pelo_programa + p.pela_memoria)
    entrada = {
        "diaria": diaria,
        "formas": formas,
        "ja_resolvido": {"rotulos": rotulos_conhecidos(), "formas": [{"forma": f, "quantos": n} for f, n in resolvidas.most_common(10)]},
        "pastas": _distintos((a.pasta for a in p.restantes if a.pasta != "."), 10),
        "notas": _distintos((a.nota for a in p.restantes), 10),
        "canais": _distintos((c for a in p.restantes for c in a.canais), 12, 30),
        "memoria": {"glossario": list(mem.glossario) if mem else [], "nao_se_sabe": list(mem.nao_se_sabe) if mem else []},
    }
    return entrada, max(0, len(grupos) - TETO_FORMAS)


def _numero(valor: str | None) -> str:
    return re.sub(r"\D", "", str(valor or "")).lstrip("0") or ("0" if re.search(r"\d", str(valor or "")) else "")


def _identidade(a: Arquivo, regras=()) -> tuple | None:
    lido = memoria.aplicar(regras, a.nome)
    if lido:
        return (lido["episodio"], lido["cena"], lido["plano"], lido["take"])
    c = _claquete.ler(a.nome)
    return (c.episodio or None, c.cena, c.plano, c.take) if c else None


def leitura_atual(p: Particao, regras=()) -> list[dict]:
    """Como cada forma já é lida, com um exemplo: "não há o que perguntar" sem isto não diz o que foi entendido (teste do autor, 2026-11-08)."""
    grupos = _agrupar([*p.pela_memoria, *p.pelo_programa])
    saida = []
    for forma, arquivos in list(grupos.items())[:8]:
        primeiro = arquivos[0]
        lido = " · ".join(v for v in (_identidade(primeiro, regras) or ()) if v)
        saida.append({"forma": forma, "quantos": len(arquivos), "exemplo": f"{primeiro.nome} → {lido}",
                      "lido_por": "memória da produção" if memoria.aplicar(regras, primeiro.nome) else "programa"})
    return saida


def _sem_canal(nome: str) -> str:
    return _FIM_DE_CANAL.sub("", nome)


def _contar_campos(arquivos: list[Arquivo], padrao: re.Pattern) -> tuple[dict, int]:
    """Campo por campo: quantos o molde lê, quantos o metadado confirma, quantos ele desmente, e quantos ele não apoia nem desmente."""
    contas: dict[str, dict[str, int]] = {}
    nao_casou = 0
    for a in arquivos:
        m = padrao.match(a.nome)
        if not m:
            nao_casou += 1
            continue
        cenas = [set(_numero(t) for t in re.findall(r"\d+", s)) for s in (a.scene_ixml, a.scene_bext) if s]
        takes = [_numero(t) for t in (a.take_ixml, a.take_bext) if t and _numero(t)]
        for campo, valor in m.groupdict().items():
            c = contas.setdefault(campo, {"lidos": 0, "confere": 0, "contradiz": 0, "sem_apoio": 0})
            c["lidos"] += 1
            numero = _numero(valor)
            if campo == "take":
                if takes:
                    c["confere" if numero in takes else "contradiz"] += 1
                else:
                    c["sem_apoio"] += 1
            elif any(numero in tokens for tokens in cenas):
                c["confere"] += 1
            else:
                c["sem_apoio"] += 1     # ⚠️ o SCENE do F8 pode trazer só a produção: não prova nem desmente
    return contas, nao_casou


def conferir_regras(restantes: list[Arquivo], propostas: list[dict], ja_lidos: list[Arquivo] | None = None, regras_atuais=()) -> list[dict]:
    """Aplica cada proposta em todos os arquivos da forma. `aprovada` só sem problema nenhum.

    ⛔ A colisão é conferida contra todos os lidos: dois takes diferentes com a mesma identidade se sobrescreveriam na bin, calados."""
    grupos = _agrupar(restantes)
    saida: list[dict] = []
    regras: list[memoria.Regra] = []
    for proposta in propostas[:TETO_REGRAS]:
        forma, molde = str(proposta.get("forma") or ""), str(proposta.get("molde") or "")
        item = {"forma": forma, "molde": molde, "certeza": str(proposta.get("certeza") or "presumida"), "por_que": str(proposta.get("por_que") or ""),
                "arquivos": len(grupos.get(forma, [])), "campos": {}, "exemplo": "", "problemas": []}
        saida.append(item)
        if forma not in grupos:
            item["problemas"].append("esta forma não existe entre os arquivos sem leitura")
            continue
        if memoria.forma_do_molde(molde) != forma:
            item["problemas"].append(f"o molde não reproduz a forma (dá {memoria.forma_do_molde(molde)!r})")
            continue
        try:
            padrao = re.compile(memoria.molde_para_regex(molde))
        except ValueError as e:
            item["problemas"].append(str(e))
            continue
        contas, nao_casou = _contar_campos(grupos[forma], padrao)
        item["campos"] = contas
        if nao_casou:
            item["problemas"].append(f"{nao_casou} arquivo(s) da forma não casam com o molde")
        for campo, c in contas.items():
            if c["contradiz"]:
                item["problemas"].append(f"{campo}: o metadado desmente em {c['contradiz']} arquivo(s)")
        regra = memoria.Regra(forma, padrao)
        regras.append(regra)
        primeiro = grupos[forma][0]
        lido = memoria.aplicar([regra], primeiro.nome) or {}
        item["exemplo"] = f"{primeiro.nome} → " + " · ".join(v for v in lido.values() if v)

    donos: dict[tuple, set[str]] = defaultdict(set)
    formas_por_nome: dict[str, str] = {}
    for a in [*restantes, *(ja_lidos or [])]:
        identidade = _identidade(a, [*regras, *regras_atuais])
        if identidade:
            donos[identidade].add(_sem_canal(a.nome))
            formas_por_nome[_sem_canal(a.nome)] = memoria.forma_de(a.nome)
    for nomes in (n for n in donos.values() if len(n) > 1):
        for item in saida:
            if item["forma"] in {formas_por_nome[n] for n in nomes} and not any(p.startswith("colisão") for p in item["problemas"]):
                # ⭐ Primeiro um nome da própria forma: é o que o editor reconhece ao ler o motivo desta regra.
                a, b = sorted(nomes, key=lambda n: (formas_por_nome[n] != item["forma"], n))[:2]
                item["problemas"].append(f"colisão: {a} e {b} ficariam com a mesma cena, plano e take; falta ler o que os diferencia")
    for item in saida:
        item["aprovada"] = not item["problemas"]
    return saida


def filtrar_perguntas(perguntas: list, mem: memoria.Memoria | None) -> list[dict]:
    """Junta por assunto e tira o que não pode voltar: o que o editor já respondeu, o que disse não saber e rótulo que o programa conhece."""
    chave = memoria._chave
    proibidas = {chave(i.split(":", 1)[0]) for i in [*(mem.glossario if mem else ()), *(mem.nao_se_sabe if mem else ())]}
    rotulos = {chave(r) for lista in rotulos_conhecidos().values() for r in lista}
    juntas: dict[str, dict] = {}
    for p in perguntas:
        if not isinstance(p, dict) or not str(p.get("texto") or "").strip():
            continue
        sobre = str(p.get("sobre") or p["texto"]).strip()
        if chave(sobre) in proibidas or chave(sobre) in rotulos:
            continue
        item = juntas.setdefault(chave(sobre), {"sobre": sobre, "formas": [], "texto": str(p["texto"]).strip(), "opcoes": []})
        item["formas"] += [str(f) for f in (p.get("formas") or []) if str(f) not in item["formas"]]
        item["opcoes"] += [o for o in _opcoes(p.get("opcoes")) if o not in item["opcoes"]]
        item["opcoes"] = item["opcoes"][:TETO_OPCOES]
    return list(juntas.values())[:TETO_PERGUNTAS]


def _opcoes(valores) -> list[str]:
    """Os atalhos da pergunta: texto curto. O "não sei" já vem de nós, em toda pergunta."""
    if not isinstance(valores, list):
        return []
    limpas = (" ".join(str(v).split()) for v in valores if isinstance(v, str))
    return [v for v in limpas if v and len(v) <= TAMANHO_DA_OPCAO and memoria._chave(v) not in {"nao sei", "nao se sabe"}]


def _exemplo(formas: list[str], grupos: dict[str, list[Arquivo]]) -> str:
    """`18-1T01 (31 arquivos)`: forma com `#` é vocabulário nosso, e o editor reconhece o nome do arquivo."""
    partes = [f"{grupos[f][0].nome} ({len(grupos[f])} arquivo{'s' if len(grupos[f]) > 1 else ''})" for f in formas if f in grupos]
    return " · ".join(partes[:3])


def cartao_de_perguntas(perguntas: list[dict], producao: dict, restantes: list[Arquivo], ha_regra: bool = False) -> dict | None:
    """O cartão do chat, uma caixa por pergunta. `None` quando não há o que perguntar."""
    grupos = _agrupar(restantes)
    itens = [{"sobre": p["sobre"], "texto": p["texto"], "exemplo": _exemplo(p["formas"], grupos), "opcoes": p.get("opcoes") or [], "nao_sei": True} for p in perguntas]
    if producao.get("memoria") is None and (itens or ha_regra):
        nomes = [*producao.get("no_ixml", []), *producao.get("memorias_existentes", []), producao.get("projeto_aberto") or ""]
        opcoes = list(dict.fromkeys(n for n in nomes if n))[:5]
        itens.append({"sobre": "produção", "texto": "De que produção é esta diária? Se for nova, escreva o nome dela.", "exemplo": "", "opcoes": opcoes, "nao_sei": False})
    if not itens:
        return None
    return {"id": uuid.uuid4().hex[:8], "titulo": "Preciso de umas respostas sobre os nomes do som", "perguntas": itens}


def nome_do_projeto(caminho: str) -> str:
    """O nome que os módulos usam para achar a memória: a pasta do projeto no MC, o `.prproj` sem extensão no Premiere."""
    p = Path(str(caminho or "").replace("\\", "/"))
    return p.stem if p.suffix.lower() == ".prproj" else p.name


def identificar(arquivos: list[Arquivo], projeto_aberto: str) -> tuple[memoria.Memoria | None, dict]:
    """De que produção é esta diária: o projeto aberto primeiro, o `PROJECT` do iXML depois. ⚠️ O PROJECT pode ser só uma data (medido no MixPre): é sugestão, não identidade."""
    no_ixml = _distintos((a.projeto for a in arquivos), 5)
    achada, por = None, ""
    for candidato, origem in [(projeto_aberto, "projeto aberto"), *((n, "iXML") for n in no_ixml)]:
        achada = memoria.achar(candidato)
        if achada:
            por = origem
            break
    return achada, {"memoria": achada.nome if achada else None, "achada_por": por, "projeto_aberto": projeto_aberto, "no_ixml": no_ixml,
                    "memorias_existentes": [m.nome for m in memoria.todas()]}
