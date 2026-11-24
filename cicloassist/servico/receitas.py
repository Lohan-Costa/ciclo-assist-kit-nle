"""As RECEITAS: um fluxo conhecido, num arquivo, que roda por botão — sem modelo (F1).

Decisão do autor (2026-10-31): *"será que podemos criar no formato de skill? assim ele pode ser
compartilhado com outros editores e se adaptar a diferentes condições"*. E (2026-11-01) os passos
num bloco JSON — a mesma lista que o modelo manda ao `executar_fluxo`, sem parser novo.

```
---
name: preparar-diaria-mc
description: Quando usar (uma frase).
parametros: {"pasta": {"tipo": "pasta", "rotulo": "A pasta da diária"}, "diaria": {"tipo": "texto"}}
---
## Passos                       ← o EXECUTOR lê: um bloco ```json com a lista de passos
## Quando as condições mudam    ← o MODELO lê, só quando um passo falha
```

⭐⭐ **Automação conhecida roda SEM IA.** O botão enche os parâmetros, o cartão mostra o plano
inteiro, o clique o executa: sem turno, sem assinatura, sempre igual.

⛔⛔ **Receita de fora é entrada não confiável.** Ela só consegue chamar as nossas operações com
nome (o executor valida contra o registro) e toda escrita passa pelo cartão; a prosa chega ao
modelo como DADO. ⛔ E nada da máquina de quem fez: caminho e nome de projeto são PARÂMETROS.

Onde moram: as da casa em `cicloassist/receitas/`, as do editor em `<dados>/receitas/`
(a do editor ganha da casa com o mesmo `name` — é a versão que ele ajustou).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import fluxo as _fluxo

log = logging.getLogger("cicloassist.servico.receitas")

DA_CASA = Path(__file__).resolve().parent.parent / "receitas"
TIPOS = ("texto", "pasta", "arquivo", "escolha", "numero", "sim_nao", "timeline")

#: ⭐ Caminho nunca é digitado (autor, 2026-11-01): `pasta` e `arquivo` se escolhem pelo diálogo do
#: sistema (`servico/seletor.py`) ou por arrasto. Com `multiplos`, o valor é uma LISTA.
CAMINHOS = ("pasta", "arquivo")


def derivados(parametros: dict[str, dict[str, Any]]) -> list[str]:
    """Os nomes que a receita ganha de graça: `<p>_nome` para cada caminho — o nome do (primeiro)
    arquivo ou pasta, sem extensão. É o que deixa um título ou um projeto nascer do arquivo, sem
    pedir ao editor um "nome curto" que ele teria de digitar."""
    return [f"{k}_nome" for k, spec in parametros.items() if spec.get("tipo") in CAMINHOS]
_NOME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
_BLOCO = re.compile(r"```json\s*\n(.*?)\n```", re.S)


class ReceitaInvalida(ValueError):
    pass


@dataclass
class Receita:
    nome: str
    descricao: str
    parametros: dict[str, dict[str, Any]]
    passos: list[dict[str, Any]]
    condicoes: str = ""
    titulo: str = ""
    origem: str = "casa"
    arquivo: str = ""
    problemas: list[str] = field(default_factory=list)

    def para_a_janela(self) -> dict[str, Any]:
        return {"nome": self.nome, "titulo": self.titulo or self.nome, "descricao": self.descricao,
                "parametros": self.parametros, "origem": self.origem,
                "passos": [{"id": p.get("id"), "op": p.get("op"), "args": p.get("args") or {}} for p in self.passos],
                "problemas": self.problemas}

    def plano(self, valores: dict[str, Any]) -> dict[str, Any]:
        """O plano do executor com os valores do editor. Levanta com o que falta."""
        params: dict[str, Any] = {}
        faltam = []
        for nome, spec in self.parametros.items():
            v = valores.get(nome, spec.get("padrao"))
            if isinstance(v, str):
                v = v.strip()
            if spec.get("tipo") in CAMINHOS:
                lista = [str(x).strip() for x in (v if isinstance(v, list) else [v]) if x and str(x).strip()]
                if not lista and not spec.get("opcional"):
                    faltam.append(spec.get("rotulo") or nome)
                    continue
                # ⭐ Vários = lista (vazia quando opcional e nada escolhido); um = o texto.
                params[nome] = lista if spec.get("multiplos") else (lista[0] if lista else "")
                params[f"{nome}_nome"] = Path(lista[0]).stem if lista else ""
                continue
            if v in (None, "") and not spec.get("opcional"):
                faltam.append(spec.get("rotulo") or nome)
                continue
            if spec.get("tipo") == "escolha" and v not in (spec.get("opcoes") or []) and v not in (None, ""):
                raise ReceitaInvalida(f"{spec.get('rotulo') or nome}: escolha uma de {spec.get('opcoes')}")
            params[nome] = "" if v is None else v
        if faltam:
            raise ReceitaInvalida("falta preencher: " + ", ".join(faltam))
        titulo = self.titulo or self.nome
        try:
            titulo = _fluxo.resolver(titulo, params, {})
        except _fluxo.PlanoInvalido:
            pass
        return {"nome": titulo, "parametros": params, "passos": self.passos}


def _cabecalho(texto: str) -> tuple[dict[str, str], str]:
    if not texto.startswith("---"):
        raise ReceitaInvalida("falta o cabeçalho (--- name / description / parametros ---)")
    fim = texto.find("\n---", 3)
    if fim < 0:
        raise ReceitaInvalida("o cabeçalho não fecha (---)")
    campos: dict[str, str] = {}
    for linha in texto[3:fim].strip().splitlines():
        if ":" in linha:
            k, v = linha.split(":", 1)
            campos[k.strip()] = v.strip()
    return campos, texto[fim + 4:]


def _secao(corpo: str, titulo: str) -> str:
    m = re.search(rf"^##\s+{re.escape(titulo)}\s*$(.*?)(?=^##\s|\Z)", corpo, re.M | re.S | re.I)
    return m.group(1).strip() if m else ""


def ler_texto(texto: str, origem: str = "casa", arquivo: str = "") -> Receita:
    campos, corpo = _cabecalho(texto.replace("\r\n", "\n"))
    nome = campos.get("name", "")
    if not _NOME.match(nome):
        raise ReceitaInvalida(f"name inválido: {nome!r} (minúsculas, dígitos e -)")
    try:
        params = json.loads(campos.get("parametros") or "{}")
    except ValueError as e:
        raise ReceitaInvalida(f"parametros não é JSON: {e}") from None
    if not isinstance(params, dict):
        raise ReceitaInvalida("parametros tem de ser um objeto")
    for k, spec in params.items():
        if not isinstance(spec, dict) or spec.get("tipo", "texto") not in TIPOS:
            raise ReceitaInvalida(f"parâmetro {k!r}: tipo tem de ser um de {', '.join(TIPOS)}")
        spec.setdefault("tipo", "texto")
        if spec["tipo"] == "timeline" and params.get(str(spec.get("de") or ""), {}).get("tipo") != "arquivo":
            raise ReceitaInvalida(f"parâmetro {k!r}: uma timeline se lê DE um parâmetro arquivo ('de')")
    passos_md = _secao(corpo, "Passos")
    bloco = _BLOCO.search(passos_md)
    if not bloco:
        raise ReceitaInvalida("a seção '## Passos' precisa de um bloco ```json com a lista de passos")
    try:
        passos = json.loads(bloco.group(1))
    except ValueError as e:
        raise ReceitaInvalida(f"o bloco de passos não é JSON: {e}") from None
    if isinstance(passos, dict):
        passos = passos.get("passos")
    if not isinstance(passos, list):
        raise ReceitaInvalida("o bloco de passos tem de ser uma lista")
    r = Receita(nome=nome, descricao=campos.get("description", ""), parametros=params, passos=passos,
                condicoes=_secao(corpo, "Quando as condições mudam"), titulo=campos.get("titulo", ""),
                origem=origem, arquivo=arquivo)
    # A mesma conferência do executor, com parâmetros de mentira: o que ela pega aqui é
    # ESTRUTURA (operação que não existe, referência que aponta para frente).
    nomes = list(params) + derivados(params)
    r.problemas = _fluxo.validar({"parametros": {k: "x" for k in nomes}, "passos": passos})
    return r


def pasta_do_editor() -> Path:
    from .config import pasta
    return pasta() / "receitas"


def _da_pasta(origem: str, raiz: Path) -> list[Receita]:
    if not raiz.is_dir():
        return []
    achadas = []
    for arq in sorted(raiz.glob("*.md")):
        if arq.name.startswith(("_", ".")):
            continue
        try:
            achadas.append(ler_texto(arq.read_text(encoding="utf-8"), origem, str(arq)))
        except (OSError, ReceitaInvalida) as e:
            log.warning("receita %s ignorada: %s", arq.name, e)
    return achadas


def _arquivo_das_excluidas() -> Path:
    from .config import pasta
    return pasta() / "receitas_excluidas.json"


def excluidas_da_casa() -> set[str]:
    """Os fluxos do programa que o editor tirou desta máquina. ⛔ O arquivo deles é do programa e não se apaga: o que muda é a lista dele."""
    try:
        d = json.loads(_arquivo_das_excluidas().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {n for n in d if isinstance(n, str)} if isinstance(d, list) else set()


def todas() -> dict[str, Receita]:
    excluidas = excluidas_da_casa()
    achadas = {r.nome: r for r in _da_pasta("casa", DA_CASA) if r.nome not in excluidas}
    achadas.update({r.nome: r for r in _da_pasta("editor", pasta_do_editor())})
    return achadas


def buscar(nome: str) -> Receita | None:
    return todas().get(nome)


def excluir(nome: str) -> None:
    """Tira o fluxo da lista do editor. ⭐ Quem exclui a própria versão de um fluxo do programa quer que ele suma, e não que o original volte no lugar."""
    atual = todas().get(nome)
    if atual is None:
        raise ReceitaInvalida("este fluxo não existe mais")
    if atual.origem == "editor":
        Path(atual.arquivo).unlink(missing_ok=True)
    if nome in {r.nome for r in _da_pasta("casa", DA_CASA)}:
        from ..midia.cache import escrever_atomico
        destino = _arquivo_das_excluidas()
        destino.parent.mkdir(parents=True, exist_ok=True)
        escrever_atomico(destino, json.dumps(sorted(excluidas_da_casa() | {nome}), ensure_ascii=False).encode("utf-8"))
    log.info("fluxo excluído pelo editor: %s", nome)


def restaurar_da_casa() -> None:
    _arquivo_das_excluidas().unlink(missing_ok=True)


def distintivos(receitas: list[Receita]) -> dict[str, str]:
    """O que separa fluxos de MESMO título nas listas. ⭐ No teste pilotado, abrir o "Preparar a diária" errado passou sem ninguém notar: os campos eram outros."""
    grupos: dict[str, list[Receita]] = {}
    for r in receitas:
        grupos.setdefault(" ".join(re.sub(r"\{[^}]*\}\s*", "", r.titulo or r.nome).split()).casefold(), []).append(r)
    saida: dict[str, str] = {}
    for grupo in grupos.values():
        if len(grupo) < 2:
            continue
        do_editor = [r for r in grupo if r.origem == "editor"]
        for r in grupo:
            saida[r.nome] = "do programa" if r.origem != "editor" else "seu" if len(do_editor) == 1 else r.nome
    return saida


# ── a receita do EDITOR, escrita pela conversa da aba Fluxos (F3, 2026-11-03) ──


def texto_de(nome: str, descricao: str, parametros: dict[str, Any], passos: list[dict[str, Any]],
             titulo: str = "", condicoes: str = "") -> str:
    """O arquivo `.md` de uma receita, no MESMO formato das da casa (o leitor é um só)."""
    linhas = ["---", f"name: {nome}"]
    if titulo:
        linhas.append(f"titulo: {' '.join(str(titulo).split())}")
    linhas += [f"description: {' '.join(str(descricao).split())}",
               "parametros: " + json.dumps(parametros, ensure_ascii=False), "---", "",
               "## Passos", "", "```json", "["]
    linhas.append(",\n".join("  " + json.dumps(p, ensure_ascii=False) for p in passos))
    linhas += ["]", "```", ""]
    if condicoes.strip():
        linhas += ["## Quando as condições mudam", "", condicoes.strip(), ""]
    return "\n".join(linhas)


#: Rótulos dos parâmetros que os planos costumam usar; o resto sai do próprio nome ("projeto_mc").
_ROTULOS = {"pasta": "A pasta da diária (vídeos e WAV)", "diaria": "Nome da diária",
            "projeto": "Projeto", "formato": "Formato do projeto", "subclipes": "Subclipes"}


def _slug(texto: str) -> str:
    import unicodedata
    s = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")[:56].strip("-")
    return s or "fluxo"


def _textos_com(x: Any, marca: str) -> list[str]:
    """Os textos dentro dos passos que citam `marca`."""
    if isinstance(x, str):
        return [x] if marca in x else []
    if isinstance(x, dict):
        return [s for v in x.values() for s in _textos_com(v, marca)]
    if isinstance(x, list):
        return [s for v in x for s in _textos_com(v, marca)]
    return []


def _trocar_nos_passos(x: Any, marca: str, por: str) -> Any:
    if isinstance(x, str):
        return por if x == marca else x
    if isinstance(x, dict):
        return {k: _trocar_nos_passos(v, marca, por) for k, v in x.items()}
    if isinstance(x, list):
        return [_trocar_nos_passos(v, marca, por) for v in x]
    return x


def _renomear_marcador(x: Any, de: str, para: str) -> Any:
    """`{de}` → `{para}` dentro de qualquer texto dos passos (e só o marcador inteiro do parâmetro)."""
    if isinstance(x, str):
        return x.replace("{" + de + "}", "{" + para + "}")
    if isinstance(x, dict):
        return {k: _renomear_marcador(v, de, para) for k, v in x.items()}
    if isinstance(x, list):
        return [_renomear_marcador(v, de, para) for v in x]
    return x


def titulo_legivel(titulo: str) -> str:
    """O título para LER (o aviso do botão): "{diaria}" vira "‹diária›", nunca a chave crua."""
    return re.sub(r"\{([^}.]+)\}", lambda m: "‹" + m.group(1).replace("_", " ") + "›", titulo)


def do_plano(plano: dict[str, Any], hoje: str = "", de: str = "um plano da aba Fluxos") -> str:
    """⭐⭐ O botão "Salvar como receita" do cartão (autor, 2026-11-04): o plano que o editor está
    lendo vira uma receita dele, SEM turno do modelo — o editor que não sabe que isso existe vê o
    botão; pedir ao modelo era um recurso escondido.

    - Cada parâmetro do plano vira campo do formulário. Caminho (o que existe no disco) vira
      `pasta`/`arquivo`, SEM o valor de hoje: a pasta de amanhã é outra. O texto fica com o de hoje
      como padrão, editável ("TESTE SIMULADO MC" pré-preenchido é útil; trocar é um clique).
    - O título troca o valor de hoje pelo parâmetro ("…diária D01…" → "…diária {diaria}…").
    - ⛔ Nunca substitui uma receita existente (da casa ou do editor): nome repetido ganha `-2`.
    """
    params_do_plano = dict(plano.get("parametros") or {})
    caminhos = {k for k, v in params_do_plano.items()
                if isinstance(v, str) and v and (Path(v).is_dir() or Path(v).is_file())}
    parametros: dict[str, dict[str, Any]] = {}
    for k, v in params_do_plano.items():
        # `<caminho>_nome` é derivado: a receita o ganha de graça (`derivados`).
        if k.endswith("_nome") and k[:-5] in caminhos:
            continue
        rotulo = _ROTULOS.get(k) or k.replace("_", " ").capitalize()
        if k in caminhos:
            parametros[k] = {"tipo": "pasta" if Path(v).is_dir() else "arquivo", "rotulo": rotulo}
        elif isinstance(v, bool):
            parametros[k] = {"tipo": "sim_nao", "rotulo": rotulo, "padrao": v}
        elif isinstance(v, (int, float)):
            parametros[k] = {"tipo": "numero", "rotulo": rotulo, "padrao": v}
        else:
            parametros[k] = {"tipo": "texto", "rotulo": rotulo, "padrao": "" if v is None else str(v)}

    textos = {k: str(params_do_plano[k]) for k, s in parametros.items()
              if s.get("tipo") == "texto" and len(str(params_do_plano[k]).strip()) >= 2}
    trocas = sorted(((v, k) for k, v in textos.items()), key=lambda t: -len(t[0]))

    def _modelo(texto: str, sem: str = "") -> str:
        for valor, k in trocas:
            if k != sem:
                texto = re.sub(rf"(?<![\w]){re.escape(valor)}(?![\w])", "{" + k + "}", texto)
        return texto

    # ⭐ O valor que CONTÉM o de outro parâmetro segue esse parâmetro (prova de 04/11: a bin
    #   "CAMERA D01" vinha fixa no formulário, e a D02 exigiu trocar três campos à mão). O campo sai
    #   e o passo passa a dizer "CAMERA {diaria}" — o jeito da receita da casa.
    passos = list(plano.get("passos") or [])
    for k in list(textos):
        modelo = _modelo(textos[k], sem=k)
        usado_inteiro = all(f"{{{k}}}" == s for s in _textos_com(passos, f"{{{k}}}"))
        # ⚠️ Só quando o passo usa o parâmetro INTEIRO ("{bin_camera}"); dentro de um texto maior, fica.
        if modelo != textos[k] and usado_inteiro:
            passos = _trocar_nos_passos(passos, f"{{{k}}}", modelo)
            del parametros[k]
            trocas = [t for t in trocas if t[1] != k]

    # ⭐ O parâmetro que ganhou sufixo porque o nome-base estava ocupado ("projeto_2") volta ao nome-base
    #   quando a dobra o liberou — visto na D05 pelo chat (04/11): "Projeto 2" no formulário, sem "Projeto".
    for k in list(parametros):
        m = re.fullmatch(r"(.+)_\d+", k)
        if m and m.group(1) not in parametros:
            base = m.group(1)
            parametros = {(base if c == k else c): v for c, v in parametros.items()}
            parametros[base]["rotulo"] = _ROTULOS.get(base) or base.replace("_", " ").capitalize()
            passos = _renomear_marcador(passos, k, base)
            trocas = [(v, base if c == k else c) for v, c in trocas]

    titulo = _modelo(str(plano.get("nome") or "Fluxo"))

    # O nome do arquivo sai do TÍTULO já com os parâmetros (sem o "d01" de hoje dentro).
    base = _slug(re.sub(r"\{[^}]*\}", " ", titulo))
    existentes = set(todas())
    nome, n = base, 2
    while nome in existentes:
        nome, n = f"{base}-{n}", n + 1
    # ⚠️ Sem a lista de operações: a janela já mostra os passos em português logo abaixo.
    descricao = f"Guardada de {de}" + (f" em {hoje}" if hoje else "") + "."
    return texto_de(nome, descricao, parametros, passos, titulo)


def _id_do_passo(op: str, usados: set[str]) -> str:
    base = re.sub(r"[^a-z0-9_]", "_", op.lower())[:28].strip("_") or "passo"
    if not base[0].isalpha():
        base = "p_" + base
    pid, n = base, 2
    while pid in usados:
        pid, n = f"{base}_{n}", n + 1
    usados.add(pid)
    return pid


def do_chat(feitos: list[dict[str, Any]], titulo: str) -> dict[str, Any]:
    """⭐⭐ F4, "transformar em fluxo" (2026-11-04): as escritas que o chat FEZ viram um PLANO, que
    `do_plano` transforma em receita (o mesmo caminho do botão Salvar do cartão).

    - Um passo por escrita, na ordem, com os argumentos que rodaram.
    - ⭐ Texto que é a SAÍDA de um passo anterior vira `{passo.campo}` — a pasta MXF que a conversão
      devolveu e a importação usou é a ligação que faz a receita servir amanhã, com outra pasta.
    - Caminho que existe e texto livre viram parâmetros (o mesmo valor, o mesmo parâmetro); `do_plano`
      decide o tipo do campo e dobra "CAMERA D02" em "CAMERA {nome}". ⚠️ Valor da LISTA FECHADA do
      esquema (`programa: resolve`) fica fixo: trocar o programa é outra receita.
    - ⚠️ Objetos aninhados (as operações do `organizar_bins`) ficam literais: não se adivinha o que neles
      é da diária de hoje.
    """
    from ..mcp import ferramentas as _registrar  # noqa: F401 — o import registra
    from ..mcp.registro import FERRAMENTAS

    usados: set[str] = set()
    parametros: dict[str, Any] = {}
    por_valor: dict[str, str] = {}
    saidas: list[tuple[str, dict[str, Any]]] = []
    passos: list[dict[str, Any]] = []

    def _param(chave: str, valor: str) -> str:
        if valor in por_valor:
            return por_valor[valor]
        base = re.sub(r"[^a-z0-9_]", "_", chave.lower()).strip("_")[:24] or "valor"
        if not base[0].isalpha():
            base = "v_" + base
        nome, n = base, 2
        while nome in parametros or nome in usados:
            nome, n = f"{base}_{n}", n + 1
        parametros[nome] = valor
        por_valor[valor] = nome
        return nome

    def _trocar(chave: str, valor: Any, enum: list | None) -> Any:
        if isinstance(valor, list):
            return [_trocar(chave, v, None) for v in valor]
        if not isinstance(valor, str) or not valor.strip() or (enum and valor in enum):
            return valor
        for pid, saida in reversed(saidas):
            for campo, v in saida.items():
                if isinstance(v, str) and len(v) >= 3 and v == valor:
                    return "{" + pid + "." + campo + "}"
        return "{" + _param(chave, valor) + "}"

    for f in feitos:
        op = str(f.get("op") or "")
        if op not in FERRAMENTAS:
            continue
        props = (FERRAMENTAS[op].esquema or {}).get("properties") or {}
        args = {k: _trocar(k, v, (props.get(k) or {}).get("enum")) if not isinstance(v, dict) else v
                for k, v in (f.get("args") or {}).items()}
        pid = _id_do_passo(op, usados | set(parametros))
        usados.add(pid)
        passos.append({"id": pid, "op": op, "args": args})
        saidas.append((pid, dict(f.get("saida") or {})))
    return {"nome": titulo, "parametros": parametros, "passos": passos}


def conferir_texto(texto: str) -> Receita:
    """Lê como a janela leria; levanta `ReceitaInvalida` com o que não passa (estrutura incluída)."""
    r = ler_texto(texto, "editor")
    if r.problemas:
        raise ReceitaInvalida("os passos não passam:\n- " + "\n- ".join(r.problemas))
    return r


def salvar(texto: str) -> Path:
    """Grava na pasta do EDITOR (a da casa nunca se escreve). ⚠️ Mesmo nome = a versão dele, que ganha
    da da casa em `todas()` — é o "ajustei a receita" do autor."""
    r = conferir_texto(texto)
    pasta = pasta_do_editor()
    pasta.mkdir(parents=True, exist_ok=True)
    destino = pasta / f"{r.nome}.md"
    tmp = destino.with_suffix(".md.tmp")
    tmp.write_text(texto, encoding="utf-8")
    tmp.replace(destino)
    log.info("receita do editor gravada: %s", destino)
    return destino


# ── levar um fluxo de uma máquina à outra (N6) ─────────────────────────────────

TETO_DO_ARQUIVO = 256 * 1024
_SECAO_POSICOES = "Posições do desenho"
_CAMINHO_FIXO = re.compile(r"^(?:[A-Za-z]:[\\/]|/Volumes/|/Users/|\\\\)")


def _strings(x: Any):
    if isinstance(x, str):
        yield x
    elif isinstance(x, list):
        for v in x:
            yield from _strings(v)
    elif isinstance(x, dict):
        for v in x.values():
            yield from _strings(v)


def para_exportar(r: Receita, posicoes: dict[str, Any] | None) -> str:
    """O arquivo que viaja: a receita, e onde os nodes estavam, numa seção que o leitor das receitas ignora."""
    texto = texto_de(r.nome, r.descricao, r.parametros, r.passos, r.titulo, r.condicoes)
    return texto + (f"\n## {_SECAO_POSICOES}\n\n```json\n{json.dumps(posicoes, ensure_ascii=False)}\n```\n" if posicoes else "")


def nome_de_arquivo_livre(pasta: Path, nome: str) -> Path:
    """⛔ Nunca escreve por cima de algo que já está na pasta que o editor escolheu."""
    n, destino = 1, pasta / f"{nome}.md"
    while destino.exists():
        n += 1
        destino = pasta / f"{nome} ({n}).md"
    return destino


def importar(texto: str) -> tuple[Receita, dict[str, Any] | None, list[str]]:
    """`(receita gravada, posições, avisos)`. ⛔ Arquivo de fora é entrada não confiável: passa pela MESMA conferência do executor, nada roda aqui, e o editor vê os nodes antes de executar."""
    if len(texto.encode("utf-8")) > TETO_DO_ARQUIVO:
        raise ReceitaInvalida("o arquivo é grande demais para ser um fluxo")
    r = conferir_texto(texto)
    avisos = []
    fixos = sorted({s for s in _strings([r.passos, r.parametros]) if _CAMINHO_FIXO.match(s)})
    if fixos:
        avisos.append("Este fluxo tem caminho fixo de outra máquina: " + ", ".join(fixos[:3]) + ". Confira nas Propriedades antes de executar.")
    existentes = todas()
    if r.nome in existentes and existentes[r.nome].passos == r.passos and existentes[r.nome].parametros == r.parametros:
        return existentes[r.nome], None, ["Este fluxo já estava aqui, igual."]
    nome, n = r.nome, 1
    while nome in existentes:      # ⛔ Importar nunca substitui um fluxo daqui.
        n += 1
        sufixo = f"-{n}"
        nome = r.nome[:64 - len(sufixo)] + sufixo
    if nome != r.nome:
        avisos.append(f"Já havia um fluxo com este nome: este entrou como {nome}.")
    try:
        posicoes = json.loads(_BLOCO.search(_secao(_cabecalho(texto.replace("\r\n", "\n"))[1], _SECAO_POSICOES)).group(1))
    except (AttributeError, ValueError):
        posicoes = None
    salvar(texto_de(nome, r.descricao, r.parametros, r.passos, r.titulo, r.condicoes))
    return buscar(nome), posicoes, avisos
