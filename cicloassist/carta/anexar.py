"""Mandar mídia e anexar formato (plano §4.2 e §4.3).

- `mandar_arquivos`: cada arquivo (o que o NLE diz que a bin tem) vira uma `.ref.json` na pasta do editor, e a forma
  pela qual entrou vira um fato no diário (o caminho NESTA máquina).
- `anexar`: varre uma pasta, e cada arquivo que CASA com uma referência (a régua do `identidade.e_candidato`: nome da
  fonte, taxa, TC, quadros ±1; no som, a duração) vira um fato `forma`. ⛔ Dois candidatos para a mesma referência =
  empate, que é do editor: nada é gravado para ela, e o empate volta na conta.

⭐ Antes da régua, o UMID: os dois lados com o MESMO `material_package_umid` são a mesma mídia (uma cópia da mesma
OP-Atom, o MXF de câmera visto pelos dois NLEs). UMID DIFERENTE não prova nada (o AMA ganha MobID novo a cada link).
⚠️ Na D01 o WAV NÃO tem UMID (conferido; um registro meu dizia o contrário) — ali casa pela régua.
⭐ Depois da régua, o CONTEÚDO desempata (`identidade._conferir`: pixel com piso 0,95; o som, piso 0,90, quando a imagem
não pôde ser comparada), contra um arquivo que a referência JÁ tem nesta máquina. Só um passando = vínculo, com a medida;
senão o empate fica com o editor, com as medidas ditas.
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from ..midia import identidade as _id
from . import diario, referencias
from .projeto import Projeto

FORMAS = ("avid", "trabalho", "original")
EXTENSOES = {".mov", ".mp4", ".mxf", ".wav", ".aif", ".aiff", ".braw", ".r3d", ".ari", ".mts", ".m4v", ".bwf"}


@dataclass
class Conta:
    """O que aconteceu, dito ao editor (nunca um número só): o que entrou, o que já estava, o que ficou de fora."""
    novas: list[str] = field(default_factory=list)
    ja_estavam: list[str] = field(default_factory=list)
    vinculos: list[str] = field(default_factory=list)
    empates: dict[str, list[str]] = field(default_factory=dict)
    sem_par: list[str] = field(default_factory=list)
    ilegiveis: dict[str, str] = field(default_factory=dict)
    #: arquivos que não são da forma pedida (OP-Atom anexada como `trabalho`, ou o contrário)
    fora_da_forma: list[str] = field(default_factory=list)
    #: mesmo nome e duração de uma referência, OUTRO conteúdo: o porquê do empate (decisão do autor, 2026-11-12: o
    #: homônimo é do EDITOR, como o empate — nada é gravado; a medida pode errar no convertido com burn-in/LUT)
    homonimos: dict[str, str] = field(default_factory=dict)
    #: estavam REMOVIDAS da vista (na área oculta) e voltaram à pasta porque o editor as mandou de novo
    voltaram: list[str] = field(default_factory=list)


#: o padrão operacional OP-Atom no MXF (`operational_pattern_ul` …0d010201.10…): UM arquivo por trilha
_OP_ATOM = ".0d010201.10"


def _e_op_atom(arq: Path) -> bool:
    """A OP-Atom do Avid (um arquivo por trilha), distinta do MXF OP1a de câmera (Sony, ARRI), que é mídia inteira."""
    if arq.suffix.lower() != ".mxf":
        return False
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format_tags=operational_pattern_ul",
                            "-of", "json", str(arq)], capture_output=True, timeout=30)
        tags = (json.loads(r.stdout or b"{}").get("format") or {}).get("tags") or {}
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return False
    return _OP_ATOM in str(tags.get("operational_pattern_ul", "")).lower()


def _sondar(arq: Path, conta: Conta) -> dict | None:
    try:
        return _id.sondar(arq)
    except _id.IdentidadeErro as e:
        conta.ilegiveis[arq.name] = str(e)
        return None


def _ident(d: dict) -> dict:
    return {**d["identidade"], "tipo": d["identidade"].get("tipo", d.get("tipo"))}


def _pela_chave(refs: list[dict], sonda: dict) -> list[dict]:
    """As referências com o MESMO UMID da sonda (prova); vazio quando não há UMID dos dois lados."""
    u = str(sonda.get("umid") or "").lower()
    return [d for d in refs if u and str(d["identidade"].get("umid") or "").lower() == u]


def _meus_arquivos(formas_da_ref: list[dict]) -> list[Path]:
    """Os arquivos que a referência já tem NESTA máquina e que existem: a base de toda conferência de conteúdo."""
    return [Path(a) for f in formas_da_ref if f.get("maquina") == diario.maquina()
            for a in (f.get("arquivos") or [f.get("arquivo")]) if a and Path(a).exists()]


def _referencia(proj: Projeto, pasta: str, nome: str, ident: dict, entrou_por: dict, conta: Conta,
                arquivo: Path | None = None, visivel: bool = True, arquivos: list[str] | None = None) -> dict | None:
    """A referência da mídia: a que JÁ existe no projeto (o UMID, senão a mesma régua do anexar: a mesma mídia
    mandada pelo OUTRO NLE, ou de novo), ou uma nova. ⛔ Duas que servem = empate, que é do editor: nada é criado nem
    vinculado.

    ⛔⛔ A régua sozinha aceitava um HOMÔNIMO (medido 2026-11-12: o WAV da `G01_CANAIS`, outra cópia com os canais
    trocados, tem o mesmo nome e a mesma duração do som do G01). Por isso, achada UMA pela régua e havendo arquivo dela
    nesta máquina, o CONTEÚDO decide: concordou → a mesma; discordou → HOMÔNIMO, que é do editor como o empate (decisão
    do autor, 2026-11-12): nada é criado nem vinculado, e a conta diz a medida; não deu para comparar → vale a régua.
    ⚠️ Discordar não prova outra mídia: burn-in e LUT no convertido nunca foram medidos contra o piso."""
    refs = [d for _, d in referencias.todas(proj)]
    pela_chave = _pela_chave(refs, ident)
    existentes = pela_chave or [
        d for d in refs if _id.e_candidato(_ident(d), {**ident, "nome_da_fonte": ident.get("nome_da_fonte") or nome})]
    if len(existentes) > 1 and arquivo is not None:
        # várias pela régua (o homônimo já registrado, por exemplo): fica a que o CONTEÚDO confirmar, se for uma só
        formas = diario.formas(proj)
        confirmadas = []
        for d in existentes:
            meus = _meus_arquivos(formas.get(d["id"], []))
            try:
                medida, piso, _ = _id._conferir(Path(arquivo), _ident(d), meus) if meus else (_id.NAO_COMPAREI, 1, "")
            except Exception:  # noqa: BLE001
                medida, piso = _id.NAO_COMPAREI, 1.0
            if medida >= piso:
                confirmadas.append(d)
        if len(confirmadas) == 1:
            conta.ja_estavam.append(nome)
            return confirmadas[0]
    if len(existentes) > 1:
        conta.empates[nome] = [d["nome"] for d in existentes]
        if arquivo is not None:                    # ⭐ guardado: a lista "A decidir" (`decidir.py`)
            from . import decidir
            decidir.guardar(proj, "empate", nome, pasta, visivel, ident, entrou_por, Path(arquivo), arquivos,
                            [{"id": d["id"], "nome": d["nome"], "medida": None} for d in existentes],
                            f"{len(existentes)} referências do projeto servem para este arquivo")
        return None
    if existentes and not pela_chave and arquivo is not None:
        meus = _meus_arquivos(diario.formas(proj).get(existentes[0]["id"], []))
        if meus and Path(arquivo).resolve() not in {m.resolve() for m in meus}:
            try:
                medida, piso, fonte = _id._conferir(Path(arquivo), _ident(existentes[0]), meus)
            except Exception:  # noqa: BLE001 — conferência que quebra não decide nada
                medida, piso, fonte = _id.NAO_COMPAREI, 1.0, ""
            if _id.NAO_COMPAREI < medida < piso:
                porque = f"mesmo nome e duração de {existentes[0]['nome']}, outro conteúdo ({fonte} {medida:+.3f})"
                conta.homonimos[nome] = porque
                conta.empates[nome] = [f"{existentes[0]['nome']} ({fonte} {medida:+.3f}, abaixo do piso {piso:.2f})"]
                from . import decidir
                decidir.guardar(proj, "homonimo", nome, pasta, visivel, ident, entrou_por, Path(arquivo), arquivos,
                                [{"id": existentes[0]["id"], "nome": existentes[0]["nome"], "medida": round(medida, 3)}],
                                f"mesmo nome e duração de {existentes[0]['nome']}, mas o conteúdo não confere "
                                f"({fonte} {medida:+.3f}, abaixo do piso {piso:.2f}) — pode ser outro material, ou o mesmo com LUT ou tarja")
                return None
    if existentes:
        ref = existentes[0]
        if visivel and _trazer_de_volta(proj, pasta, ref):
            conta.voltaram.append(nome)
        else:
            conta.ja_estavam.append(nome)
        return ref
    if visivel:
        _, ref = referencias.criar(proj, pasta, nome, ident, entrou_por)
    else:
        # ⭐ Entrou só porque um ITEM a usa (o master de um subclipe que o editor mandou): oculta, como o fecho da bin do
        #    Avid (autor, 2026-11-13). "Mostrar clipes referenciados" a revela.
        from . import vitrine
        proj.ocultas.mkdir(parents=True, exist_ok=True)
        caminho, ref = referencias.criar(proj, proj.ocultas, nome, ident, entrou_por)
        vitrine.esconder(proj, caminho, ref, referencias.SUFIXO)
    conta.novas.append(nome)
    return ref


def _trazer_de_volta(proj: Projeto, pasta: str, ref: dict) -> bool:
    """A referência estava REMOVIDA da vista (oculta) e o editor a mandou de novo: volta para `pasta`."""
    from . import vitrine
    from .vista import pasta_do_projeto
    for caminho, d in referencias.todas(proj):
        if d["id"] == ref["id"] and vitrine.oculta(proj, caminho):
            vitrine.mostrar_em(proj, caminho, d, referencias.SUFIXO, pasta_do_projeto(proj, pasta))
            return True
    return False


def mandar_arquivos(proj: Projeto, pasta: str, arquivos: list[str | Path], forma: str, nle: str,
                    visivel: bool = True) -> Conta:
    if forma not in FORMAS:
        raise ValueError(f"forma desconhecida: {forma}")
    conta = Conta()
    for a in map(Path, arquivos):
        s = _sondar(a, conta)
        if s is None:
            continue
        ident = referencias.identidade_da_sonda(s)
        nome = s.get("nome_da_fonte") or a.stem
        if nome.lower() == a.name.lower():       # sem nome de material embutido, o ffprobe devolve o do arquivo
            nome = a.stem
        ref = _referencia(proj, pasta, nome, ident, {"nle": nle, "forma": forma, "arquivo": a.name}, conta, a, visivel)
        if ref is None:
            continue
        _vincular(proj, ref["id"], forma, a, "entrou por aqui", conta)
    return conta


def mandar_do_avid(proj: Projeto, pasta: str, clipes, visivel: bool = True) -> Conta:
    """Os masters do Avid (`acervo.Clipe`: os N arquivos OP-Atom de UM master, uma trilha por arquivo) viram UMA
    referência cada, com a forma `avid` apontando os N arquivos.

    ⭐ A identidade sai da SONDA de um arquivo do master, nunca do nome da bin: o editor renomeia o take na bin
    (`…PRAIA 03-04/001`), e o nome de dentro da OP-Atom é o do arquivo do gravador (`…PRAIA 03-04-T001.WAV`) — o que
    casa com a versão de trabalho (banco `transversal/banco-de-midias-compartilhado.md` §8b, defeito 3)."""
    conta = Conta()
    for c in clipes:
        arquivos = [Path(a) for a in c.arquivos]
        principal = Path((c.por_tipo.get("video") or c.por_tipo.get("audio") or c.arquivos)[0])
        s = _sondar(principal, conta)
        if s is None:
            continue
        ident = referencias.identidade_da_sonda(s)
        ident["tipo"] = "video" if c.tem_imagem else "audio"
        if c.fps:
            ident["fps"] = c.fps
        ident["duracao_s"] = round(c.duracao_s, 3)
        ident["trilhas"] = dict(c.tracks)
        ref = _referencia(proj, pasta, c.nome.replace("/", " "), ident,
                          {"nle": "avid", "forma": "avid", "master": c.chave}, conta, principal, visivel,
                          [str(a) for a in arquivos])
        if ref is None:
            continue
        _vincular(proj, ref["id"], "avid", principal, "entrou por aqui", conta,
                  arquivos=[str(a) for a in arquivos])
    return conta


def _nfc(caminho: str) -> str:
    import unicodedata
    return unicodedata.normalize("NFC", str(caminho))


def _vincular(proj: Projeto, midia: str, forma: str, arquivo: Path, por: str, conta: Conta,
              medida: float | None = None, arquivos: list[str] | None = None) -> None:
    lugar = referencias.onde(arquivo)
    if arquivos:
        lugar["arquivos"] = arquivos            # a OP-Atom: um arquivo por trilha
    # ⛔ o MESMO caminho em duas normalizações (o caminho AMA da bin vem NFC; o `rglob` no exFAT do Mac devolve NFD):
    #   sem normalizar, a forma de um arquivo com acento entrava DUAS vezes (B30 `CENA_AÇÃO`, 2026-11-26)
    alvo = _nfc(lugar["arquivo"])
    ja = any(f["forma"] == forma and _nfc(f.get("arquivo") or "") == alvo and f["maquina"] == diario.maquina()
             for f in diario.formas(proj).get(midia, []))
    if ja:
        return
    # ⭐ a IMPRESSÃO do arquivo (plano 2026-11-26: o hash em dois níveis — a rápida aqui; tamanho + começo + fim) acha a
    #   cópia movida fora do nosso controle. Arquivo que não se lê agora fica sem ela (não barra o vínculo).
    try:
        from ..midia import identidade as _id
        imp = _id.impressao(arquivo)
    except OSError:
        imp = None
    diario.acrescentar(proj, {"fato": "forma", "midia": midia, "forma": forma, **lugar, "por": por, "medida": medida,
                              **({"impressao": imp} if imp else {})})
    conta.vinculos.append(f"{arquivo.name} → {forma}")


def anexar(proj: Projeto, pasta_de_midia: str | Path, forma: str, ids: set[str] | None = None) -> Conta:
    """Casa os arquivos de `pasta_de_midia` (recursivo) com as referências (`ids` = só estas; None = todas)."""
    if forma not in FORMAS:
        raise ValueError(f"forma desconhecida: {forma}")
    conta = Conta()
    refs = [(p, d) for p, d in referencias.todas(proj) if ids is None or d["id"] in ids]
    # ⭐ Os arquivos de UMA OP-Atom (o mesmo UMID de material, uma trilha cada) são UM candidato — medido na D01
    #    da PRODUCAO-A (2026-11-12): `…-T001_A01/A02/A03.mxf` ao lado do WAV davam empate de 4 com 1 mídia.
    #    E a forma decide o que entra: `avid` só OP-Atom; `trabalho`/`original` nunca OP-Atom.
    grupos: dict[str, list[tuple[Path, dict]]] = {}
    for a in sorted(Path(pasta_de_midia).rglob("*")):
        if not a.is_file() or a.name.startswith("._") or a.suffix.lower() not in EXTENSOES:
            continue
        if _e_op_atom(a) != (forma == "avid"):
            conta.fora_da_forma.append(a.name)
            continue
        s = _sondar(a, conta)
        if s is None:
            continue
        chave = f"umid:{s['umid']}" if forma == "avid" and s.get("umid") else f"arq:{a}"
        grupos.setdefault(chave, []).append((a, s))
    candidatos: dict[str, list[list[Path]]] = {d["id"]: [] for _, d in refs}
    por_umid: set[str] = set()
    for membros in grupos.values():
        a, s = membros[0]
        if len(membros) > 1:      # a duração do som e a imagem vêm do arquivo que tiver imagem, se houver
            a, s = next(((x, y) for x, y in membros if y.get("tipo") == "video"), membros[0])
            s = {**s, "tipo": "video" if any(y.get("tipo") == "video" for _, y in membros) else "audio"}
        pela_chave = _pela_chave([d for _, d in refs], s)
        alvo = pela_chave or [d for _, d in refs if _id.e_candidato(_ident(d), s)]
        for d in alvo:
            candidatos[d["id"]].append([x for x, _ in membros])
            if pela_chave:
                por_umid.add(d["id"])
        if not alvo:
            conta.sem_par.extend(x.name for x, _ in membros)
    formas_vivas = diario.formas(proj)
    for _, d in refs:
        achados = candidatos[d["id"]]
        por, medida = ("umid" if d["id"] in por_umid else "nome+taxa+tc+quadros"), None
        if len(achados) > 1:
            achados, por, medida, medidas = _desempatar(d, achados, formas_vivas.get(d["id"], []))
            if len(achados) != 1:
                conta.empates[d["nome"]] = medidas
                continue
        if len(achados) == 1:
            arqs = achados[0]
            _vincular(proj, d["id"], forma, arqs[0], por, conta, medida=medida,
                      arquivos=[str(x) for x in arqs] if len(arqs) > 1 else None)
    # ⭐ o MANIFESTO da conversão (plano 2026-11-26, etapa 2): o par original ⇄ convertido com a transformação, gravado
    #   por quem converteu — vira o fato `relacao` no diário (`relacoes.py`)
    if forma != "avid":
        from . import relacoes
        for nome in relacoes.registrar_do_manifesto(proj, pasta_de_midia, forma, conta):
            conta.vinculos.append(f"{nome}: a relação com o original (manifesto)")
    return conta


def _desempatar(ref: dict, grupos: list[list[Path]], formas_da_ref: list[dict]):
    """(grupos que sobram, por, medida, [descrição de cada candidato]) — pelo CONTEÚDO, contra os arquivos que a
    referência já tem nesta máquina. Sem arquivo conhecido aqui, não há com que comparar: o empate fica."""
    meus = _meus_arquivos(formas_da_ref)
    if not meus:
        return grupos, "", None, [" + ".join(x.name for x in g) + " (sem arquivo conhecido aqui para comparar)"
                                  for g in grupos]
    medidos = []
    for g in grupos:
        try:
            medida, piso, fonte = _id._conferir(g[0], _ident(ref), meus)
        except Exception as e:  # noqa: BLE001 — conferência que quebra não decide nada
            medida, piso, fonte = -1.0, 1.0, f"erro: {e}"
        medidos.append((g, medida, piso, fonte))
    passam = [m for m in medidos if m[1] >= m[2]]
    descricao = [f"{' + '.join(x.name for x in g)} ({fonte} {medida:+.3f})" for g, medida, _, fonte in medidos]
    if len(passam) == 1:
        g, medida, _, fonte = passam[0]
        return [g], f"conteúdo ({fonte})", round(medida, 4), descricao
    return [m[0] for m in passam] or grupos, "", None, descricao
