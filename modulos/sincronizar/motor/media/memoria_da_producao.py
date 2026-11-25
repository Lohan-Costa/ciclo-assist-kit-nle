"""A MEMÓRIA DA PRODUÇÃO: um `.md` por produção, que o editor lê e corrige, e que muda a leitura sem IA.

Fase A1 do plano `docs/plano/2026-11-08-agentes.md`. Mora em `<dados do Ciclo Assist>/producoes/<produção>/memoria.md`:

    # PRODUCAO_B

    ## Identificação
    - iXML: PRODUCAO_B
    - Premiere: PRODUCAO-B CORTE 3

    ## Padrões de metadado
    ```json
    {"regras": [{"forma": "#-#T#", "regex": "^(?P<cena>\\d+)-(?P<plano>\\d+)T(?P<take>\\d+)$"}]}
    ```

⭐ A produção se acha pelo nome da pasta ou por um apelido da Identificação, comparados sem caixa e sem acento: é o projeto aberto no NLE
quem pergunta, e um projeto pode ter vários nomes ao longo do trabalho. O bloco JSON é o mesmo recurso das receitas: legível
para o editor, preciso para o código.

⛔ O arquivo é entrada não confiável na hora de ler: JSON quebrado ou regex inválida não derrubam a leitura, só deixam de valer, com aviso no log.
Quem não tem memória segue pelas regras de sempre.
"""
from __future__ import annotations

import datetime
import json
import logging
import os
import re
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path

from media import claquete as _claquete

# ⛔ Só biblioteca padrão aqui e em `claquete`: o Assist, em outra venv, importa este arquivo para gravar a memória (fase A3).
# Duas cópias do formato divergiriam caladas.
log = logging.getLogger("sincronizar.media.memoria_da_producao")

ARQUIVO = "memoria.md"
#: Quanto se sobe da bin procurando o `.avp`: a bin pode estar em subpastas do projeto.
_NIVEIS_ATE_O_PROJETO = 8
CAMPOS = ("episodio", "cena", "plano", "take")
_MARCA = re.compile(r"\{([^{}|]*)(?:\|([^{}]*))?\}")
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
_SECOES_NOVAS = ("Identificação", "Padrões de metadado", "Glossário", "Equipe e canais", "Decisões", "Não se sabe")
_IDENTIFICACAO = "Identifica[cç][aã]o"
_PADROES = "Padr[oõ]es de metadado"
_GLOSSARIO = "Gloss[aá]rio"
_NAO_SE_SABE = "N[aã]o se sabe"


@dataclass(frozen=True)
class Regra:
    forma: str
    padrao: re.Pattern


@dataclass(frozen=True)
class Memoria:
    nome: str
    apelidos: tuple[str, ...] = ()
    regras: tuple[Regra, ...] = field(default_factory=tuple)
    caminho: str = ""
    glossario: tuple[str, ...] = ()
    nao_se_sabe: tuple[str, ...] = ()


def raiz() -> Path:
    """`<CicloAssist>/producoes`, ao lado da pasta de cada módulo: a memória é da produção, não do Sincronizar."""
    explicita = os.environ.get("SINCRONIZAR_DADOS")
    if explicita:
        return Path(explicita) / "producoes"
    import appsettings
    return appsettings.app_data_dir().parent / "producoes"


def _chave(texto: str) -> str:
    sem_acento = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[\s_\-]+", " ", sem_acento).strip().casefold()


def _secao(texto: str, titulo: str) -> str:
    m = re.search(rf"^##\s*{titulo}\s*$(.*?)(?=^##\s|\Z)", texto, re.M | re.S | re.I)
    return m.group(1) if m else ""


def _itens(texto: str, titulo: str) -> tuple[str, ...]:
    """As linhas `- …` de uma seção, sem o traço."""
    achados = (re.match(r"^\s*-\s*(.+?)\s*$", ln) for ln in _secao(texto, titulo).splitlines())
    return tuple(m.group(1) for m in achados if m)


def _apelidos(texto: str) -> tuple[str, ...]:
    return tuple(v for v in (item.split(":", 1)[-1].strip() for item in _itens(texto, _IDENTIFICACAO)) if v)


def _regras(texto: str, origem: str) -> tuple[Regra, ...]:
    m = re.search(r"```json\s*(.*?)```", _secao(texto, _PADROES), re.S)
    if not m:
        return ()
    try:
        dados = json.loads(m.group(1))
    except ValueError as e:
        log.warning("memória %s: o bloco de regras não é JSON válido (%s); as regras não valem", origem, e)
        return ()
    saida: list[Regra] = []
    for r in dados.get("regras") or [] if isinstance(dados, dict) else []:
        if not isinstance(r, dict) or not isinstance(r.get("molde") or r.get("regex"), str):
            continue
        try:
            # ⭐ O molde é a fonte: a regex sai dele a cada leitura, e um conserto do gerador vale para o que já está gravado.
            padrao = re.compile(molde_para_regex(r["molde"]) if r.get("molde") else r["regex"])
        except (re.error, ValueError) as e:
            log.warning("memória %s: regra inválida %r (%s); ignorada", origem, r.get("molde") or r["regex"], e)
            continue
        if "cena" not in padrao.groupindex:
            log.warning("memória %s: a regra %r não tem o grupo `cena`; ignorada", origem, r["regex"])
            continue
        saida.append(Regra(forma=str(r.get("forma") or ""), padrao=padrao))
    return tuple(saida)


def ler_texto(texto: str, nome_da_pasta: str = "", caminho: str = "") -> Memoria:
    m = re.search(r"^#\s+(.+?)\s*$", texto, re.M)
    return Memoria(nome=m.group(1) if m else nome_da_pasta, apelidos=_apelidos(texto),
                   regras=_regras(texto, nome_da_pasta or caminho), caminho=caminho,
                   glossario=_itens(texto, _GLOSSARIO), nao_se_sabe=_itens(texto, _NAO_SE_SABE))


def todas() -> list[Memoria]:
    """As memórias que existem, cada uma com o nome da pasta guardado em `caminho`."""
    pasta = raiz()
    if not pasta.is_dir():
        return []
    saida: list[Memoria] = []
    for sub in sorted(p for p in pasta.iterdir() if p.is_dir()):
        arquivo = sub / ARQUIVO
        if not arquivo.is_file():
            continue
        try:
            saida.append(ler_texto(arquivo.read_text(encoding="utf-8"), sub.name, str(arquivo)))
        except (OSError, UnicodeDecodeError) as e:
            log.warning("memória %s ilegível: %s", arquivo, e)
    return saida


def achar(projeto: str) -> Memoria | None:
    """A memória da produção deste projeto; `None` quando não há (que é o caso comum, e não é erro)."""
    alvo = _chave(projeto or "")
    if not alvo:
        return None
    for memoria in todas():
        if alvo in {_chave(n) for n in (Path(memoria.caminho).parent.name, memoria.nome, *memoria.apelidos)}:
            return memoria
    return None


def forma_de(nome: str) -> str:
    """O nome com cada número trocado por `#`: é assim que uma diária se resume sem mandar a lista inteira."""
    return re.sub(r"\d+", "#", nome)


def forma_do_molde(molde: str) -> str:
    return _MARCA.sub(lambda m: "#" + (m.group(2) or ""), molde)


def _literal(texto: str) -> str:
    return r"\d+".join(re.escape(p) for p in texto.split("#"))


def _antes_do_take(antes: str) -> str:
    """O texto antes do take, aceitando a `/` do master do MC no lugar do RÓTULO. ⛔ Só do rótulo: o resto é a SCENE (`18-EXTRAT01` no MC é `18-EXTRA/01`, nunca `18/01`)."""
    corte = antes.rfind("#") + 1
    cabeca, cauda = antes[:corte], antes[corte:]
    rotulo = re.search("(?:" + "|".join(sorted(map(re.escape, _claquete.ROTULOS_DE_TAKE), key=len, reverse=True)) + ")$", cauda, re.I)
    if rotulo:
        return _literal(cabeca) + re.escape(cauda[:rotulo.start()]) + "(?:" + re.escape(rotulo.group(0)) + "|/)"
    # Separador puro (`#-{take}`) também vira barra; palavra que não é rótulo fica como está.
    if cauda and not re.search(r"[^\W\d_]", cauda):
        return _literal(cabeca) + "(?:" + re.escape(cauda) + "|/)"
    return _literal(antes)


def molde_para_regex(molde: str) -> str:
    r"""`E{episodio}C{cena|ct}P{plano}T{take}` → a regex da regra. `ValueError` com o motivo.

    ⭐ O agente propõe o molde, nunca a regex: a regra fica gravada e roda em toda listagem, e padrão escrito por modelo pode
    travar a leitura ou casar além do que ele disse. `{cena|ct}` guarda o sufixo no valor, sem interpretá-lo; `#` é número que ninguém leu.

    ⭐ O que vem antes do take também aceita `/`: o Media Composer batiza o master de um WAV linkado como `SCENE/TAKE`
    (banco, `protocolos/avb/estruturas.md`), e a regra feita sobre o arquivo não valeria na bin."""
    marcas = list(_MARCA.finditer(molde))
    vistos: set[str] = set()
    saida: list[str] = []
    pos = 0
    for i, m in enumerate(marcas):
        campo, sufixo = m.group(1), m.group(2) or ""
        if campo not in CAMPOS:
            raise ValueError(f"o campo {campo!r} não existe; os campos são {', '.join(CAMPOS)}")
        if campo in vistos:
            raise ValueError(f"o campo {campo!r} aparece duas vezes")
        vistos.add(campo)
        antes = molde[pos:m.start()]
        saida.append(_antes_do_take(antes) if campo == "take" and i == len(marcas) - 1 and m.end() == len(molde) else _literal(antes))
        saida.append(f"(?P<{campo}>\\d+{re.escape(sufixo)})")
        pos = m.end()
    if "cena" not in vistos:
        raise ValueError("a regra não diz qual é a cena, e sem cena ela não vale na leitura")
    saida.append(_literal(molde[pos:]))
    return "^" + "".join(saida) + "$"


def nome_de_pasta(producao: str) -> str:
    """A pasta de uma produção: o nome vem de texto escrito por gente ou pelo modelo. `ValueError` se não sobrar nome.

    Os caracteres proibidos são os da matriz de plataforma (`:*?"<>|`), mais as barras: nome de produção não escolhe caminho."""
    limpo = re.sub(r'[\x00-\x1f:*?"<>|/\\]', "_", unicodedata.normalize("NFC", str(producao or ""))).strip().rstrip(". ")
    if not limpo or set(limpo) <= {"_", "."} or limpo.upper() in _RESERVADOS:
        raise ValueError(f"{producao!r} não serve de nome de produção")
    return limpo[:80].rstrip(". ")


def _uma_linha(texto: str) -> str:
    return " ".join(str(texto).split())


def _acrescentar(texto: str, titulo_re: str, titulo: str, itens, chave) -> str:
    """Acrescenta linhas `- …` a uma seção, sem repetir e sem tocar no que o editor escreveu."""
    achado = re.search(rf"^##\s*{titulo_re}[ \t]*$", texto, re.M | re.I)
    if not achado:
        texto = texto.rstrip() + f"\n\n## {titulo}\n"
        achado = re.search(rf"^##\s*{titulo_re}[ \t]*$", texto, re.M | re.I)
    proxima = re.search(r"^##\s", texto[achado.end():], re.M)
    fim = achado.end() + proxima.start() if proxima else len(texto)
    corpo = texto[achado.end():fim]
    vistos = {chave(i) for i in _itens(texto, titulo_re)}
    novos: list[str] = []
    for item in (_uma_linha(i) for i in itens):
        if item and chave(item) not in vistos:
            vistos.add(chave(item))
            novos.append(f"- {item}")
    if not novos:
        return texto
    return texto[:achado.end()] + corpo.rstrip("\n") + "\n" + "\n".join(novos) + "\n\n" + texto[fim:].lstrip("\n")


def _com_regras(texto: str, novas: list[dict]) -> str:
    """Põe as regras no bloco JSON, trocando só as da mesma forma. ⛔ Bloco quebrado não é sobrescrito: o editor pode estar no meio de uma correção."""
    achado = re.search(rf"^##\s*{_PADROES}[ \t]*$", texto, re.M | re.I)
    proxima = re.search(r"^##\s", texto[achado.end():], re.M)
    fim = achado.end() + proxima.start() if proxima else len(texto)
    corpo = texto[achado.end():fim]
    bloco = re.search(r"```json\s*(.*?)```", corpo, re.S)
    dados: dict = {}
    if bloco:
        try:
            dados = json.loads(bloco.group(1))
        except ValueError as e:
            raise ValueError(f"o bloco de regras da memória está quebrado ({e}); conserte o arquivo antes") from e
    atuais = [r for r in (dados.get("regras") or []) if isinstance(r, dict)] if isinstance(dados, dict) else []
    por_forma = {str(r.get("forma")): r for r in atuais}
    por_forma.update({r["forma"]: r for r in novas})
    linhas = ",\n".join("  " + json.dumps(r, ensure_ascii=False) for r in por_forma.values())
    novo = '```json\n{"regras": [\n' + linhas + "\n]}\n```"
    corpo = corpo[:bloco.start()] + novo + corpo[bloco.end():] if bloco else corpo.rstrip("\n") + "\n" + novo + "\n\n"
    return texto[:achado.end()] + corpo + texto[fim:]


def gravar(producao: str, moldes=(), apelidos=(), glossario=(), nao_se_sabe=()) -> Memoria:
    """Cria ou completa a memória (fase A3). `moldes`: `[{"forma", "molde"}]`. ⛔ Quem chama garante que o editor confirmou: dedução não entra aqui.

    Acrescenta sem apagar: o arquivo é do editor, e o que ele escreveu à mão continua lá."""
    existente = achar(producao)
    if existente:
        arquivo = Path(existente.caminho)
        texto = arquivo.read_text(encoding="utf-8")
    else:
        arquivo = raiz() / nome_de_pasta(producao) / ARQUIVO
        titulo = _uma_linha(producao)
        texto = f"# {titulo}\n\n" + "\n\n".join(f"## {s}\n" for s in _SECOES_NOVAS)
    hoje = datetime.date.today().isoformat()
    regras = []
    for r in moldes:
        molde = str(r["molde"])
        if forma_do_molde(molde) != r["forma"]:
            raise ValueError(f"o molde {molde!r} não corresponde à forma {r['forma']!r}")
        molde_para_regex(molde)     # recusa o que não vale antes de tocar no arquivo
        regras.append({"forma": r["forma"], "molde": molde, "fonte": "editor", "confirmada_em": hoje})
    if regras:
        if not re.search(rf"^##\s*{_PADROES}[ \t]*$", texto, re.M | re.I):
            texto = texto.rstrip() + "\n\n## Padrões de metadado\n"
        texto = _com_regras(texto, regras)
    do_item = lambda i: _chave(i.split(":", 1)[0])  # noqa: E731
    texto = _acrescentar(texto, _IDENTIFICACAO, "Identificação", [f"nome: {a}" for a in apelidos], lambda i: _chave(i.split(":", 1)[-1]))
    texto = _acrescentar(texto, _GLOSSARIO, "Glossário", glossario, do_item)
    texto = _acrescentar(texto, _NAO_SE_SABE, "Não se sabe", nao_se_sabe, do_item)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    temporario = arquivo.with_name(f"{ARQUIVO}.{os.getpid()}.tmp")
    try:
        temporario.write_text(texto, encoding="utf-8", newline="\n")
        os.replace(temporario, arquivo)   # ⭐ o motor pode estar lendo: nunca vê o arquivo pela metade
    finally:
        temporario.unlink(missing_ok=True)
    return ler_texto(texto, arquivo.parent.name, str(arquivo))


def regras_do_projeto(projeto: str) -> tuple[Regra, ...]:
    memoria = achar(projeto)
    return memoria.regras if memoria else ()


def projeto_da_bin(caminho_da_bin: str) -> str:
    """O nome do projeto do Media Composer de uma `.avb`: a pasta que tem o `.avp`. Vazio se não achar."""
    try:
        atual = Path(caminho_da_bin).parent
        for _ in range(_NIVEIS_ATE_O_PROJETO):
            if any(a.suffix.lower() == ".avp" and not a.name.startswith("._") for a in atual.iterdir()):
                return atual.name
            if atual.parent == atual:
                break
            atual = atual.parent
    except OSError as e:
        log.debug("sem projeto para %r: %s", caminho_da_bin, e)
    return ""


def aplicar(regras, nome: str) -> dict | None:
    """`{episodio, cena, plano, take}` já no formato da claquete (`E03`, `C04`, `P01`, `T002`), ou `None` se nenhuma regra casa."""
    if not nome or not regras:
        return None
    limpo = Path(str(nome).strip()).stem if "." in str(nome) else str(nome).strip()
    for regra in regras:
        m = regra.padrao.search(limpo)
        if not m or not m.groupdict().get("cena"):
            continue
        g = m.groupdict()

        def campo(chave: str, prefixo: str):
            return prefixo + _claquete.dois_digitos(g[chave]) if g.get(chave) else None

        return {"episodio": campo("episodio", "E"), "cena": campo("cena", "C"), "plano": campo("plano", "P"), "take": campo("take", "T")}
    return None
