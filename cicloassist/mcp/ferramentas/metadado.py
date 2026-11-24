"""O agente de metadado no chat (fase A3): `entender_metadados_da_diaria` lê e propõe; `gravar_na_memoria_da_producao` guarda o que o editor confirmou.

⭐ A proposta sai do turno magro (~2 mil tokens por diária, medido na A0), e só com o que o programa não leu. Diária que o programa já lê inteira não chama modelo nenhum.

⛔ A escrita tem `sempre_pergunta`: no modo automático ninguém confirmaria, e dedução do agente não vira memória.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ... import laboratorio as _lab
from ... import nle as _nle
from ... import resolve as _resolve
from ...avid import bins as _bins
from ...avid import escopo as _escopo
from ...midia import metadado_da_diaria as _diaria
from ...motor import agentes as _agentes
from ...motor import turno_magro as _magro
from ...nle.premiere import ponte as _ponte
from ...servico import arrastados as _arrastados
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta
from .sincronizar import _arquivos_da_bin

AGENTE = "agente-de-metadado"
PROGRAMAS = ("premiere", "resolve", "avid")
_memoria = _diaria.memoria


def _projeto_aberto() -> str:
    """Sem NLE aberto a resposta é "", e isso não impede o trabalho: a diária está na pasta."""
    try:
        caminho = _nle.projeto_aberto()
    except Exception:  # noqa: BLE001 — perguntar o projeto é conveniência aqui
        return ""
    return "" if not caminho or caminho == _escopo.SEM_PROJETO else _diaria.nome_do_projeto(caminho)


def _recusa_da_pasta(pasta: str) -> str:
    p = Path(pasta or "")
    if not pasta or not p.is_dir():
        return f"'{pasta}' não é uma pasta que eu alcance. Peça ao editor para arrastá-la para o chat."
    return "" if _arrastados.autorizado(p) or _lab.na_saida(p) else _arrastados.recusa(p)


def _caminhos_no_programa(bin: str, programa: str) -> tuple[list[str], int, str]:
    """`(caminhos, gerenciados, recusa)`. ⭐ O caminho está no próprio programa: no Premiere, no Resolve e na mídia linkada do Avid (autor, 2026-11-08)."""
    try:
        if programa == "resolve":
            return _resolve.arquivos_do_pool(bin), 0, ""
        if programa == "premiere":
            return _arquivos_da_bin(bin), 0, ""
    except _resolve.ResolveIndisponivel as e:
        return [], 0, f"O DaVinci Resolve não respondeu: {e}"
    except (_ponte.PremiereIndisponivel, _ponte.ExtendScriptFalhou) as e:
        return [], 0, f"O Premiere não respondeu: {e}"
    if not bin:
        return [], 0, "Diga qual é a bin do Media Composer."
    projeto = _nle.projeto_aberto(nle=_nle.AVID)
    if not projeto or projeto == _escopo.SEM_PROJETO:
        return [], 0, "O Media Composer não está com um projeto aberto."
    r = _bins.wavs_linkados(projeto, bin)
    if not r["bins"]:
        return [], 0, f"Não achei a bin '{bin}' no projeto aberto do Media Composer."
    return r["arquivos"], r["gerenciados"], ""


def _carregar(pasta: str, bin: str, programa: str = "") -> tuple[list[_diaria.Arquivo], str, int]:
    """`(arquivos, recusa, gerenciados deixados de fora)`.

    ⛔ A bin não abre o disco: os caminhos vêm do próprio projeto, e o modelo só escolhe a bin, como no `sincronizar`. A pasta arrastada é o caminho do que o programa não alcança."""
    bin = bin.strip()
    if not (bin or programa):
        recusa = _recusa_da_pasta(pasta)
        if recusa:
            return [], recusa, 0
        arquivos = _diaria.coletar(pasta)
        return arquivos, "" if arquivos else f"Não há WAV com cabeçalho legível em {pasta}.", 0
    programa = programa or _nle.qual()
    if programa not in PROGRAMAS:
        return [], f"`programa` tem de ser um de: {', '.join(PROGRAMAS)}.", 0
    caminhos, gerenciados, recusa = _caminhos_no_programa(bin, programa)
    if recusa:
        return [], recusa, 0
    arquivos = _diaria.coletar_arquivos(caminhos)
    if arquivos:
        return arquivos, "", gerenciados
    if gerenciados:
        return [], (f"A bin '{bin}' só tem mídia GERENCIADA ({gerenciados} master(s) de som): ela não guarda o caminho do WAV do gravador. "
                    "Só neste caso peça ao editor para arrastar a pasta dos WAV pelo Explorer ou Finder."), 0
    return [], f"'{bin or 'o Media Pool'}' não tem WAV com cabeçalho legível ({len(caminhos)} arquivo(s) de mídia; o WAV pode estar offline). Confira o nome da bin.", 0


@ferramenta(
    nome="entender_metadados_da_diaria",
    descricao=(
        "Entende como uma produção nomeia o SOM DIRETO: acha os WAV pelo próprio programa (bin do Premiere, pasta do Media Pool do Resolve, bin do Media Composer "
        "com mídia linkada) ou na PASTA que o editor arrastou, lê nome, bext e iXML, separa o que o programa já lê e chama o agente de metadado só para o resto. "
        "Devolve como cada forma já é lida, as regras propostas, conferidas campo por campo contra o metadado, e as perguntas para o editor. "
        "Use quando ele pedir para entender os metadados de uma diária. Não peça a pasta quando a bin resolve. Não grava nada."
    ),
    esquema={
        "type": "object",
        "properties": {
            "bin": {"type": "string", "description": "A bin (ou pasta do Media Pool), com as filhas, como o programa a mostra."},
            "programa": {"type": "string", "enum": list(PROGRAMAS), "description": "De que programa é a bin. Vazio = o editor desta conversa."},
            "pasta": {"type": "string", "description": "A pasta dos WAV que o editor arrastou, em vez da bin."},
            "respostas": {"type": "array", "description": "Num fluxo com volta: o que o editor já respondeu nesta diária. O agente não pergunta de novo."},
        },
    },
    escreve=False,
    nles=AMBOS,
)
def entender_metadados_da_diaria(pasta: str = "", bin: str = "", programa: str = "", respostas: list | str | None = None) -> dict[str, Any]:
    arquivos, recusa, gerenciados = _carregar(pasta, bin, programa)
    if recusa:
        return {"erro": recusa}
    mem, producao = _diaria.identificar(arquivos, _projeto_aberto())
    p = _diaria.particionar(arquivos, mem.regras if mem else (), mem.nao_se_sabe if mem else ())
    resumo = {"arquivos": len(arquivos), "descartados": len(p.descartados), "lidos_pela_memoria": len(p.pela_memoria),
              "lidos_pelo_programa": len(p.pelo_programa), "sem_leitura": len(p.restantes), "editor_disse_nao_saber": len(p.ninguem_sabe), "gerenciados_de_fora": gerenciados}
    leitura = _diaria.leitura_atual(p, mem.regras if mem else ())
    if not p.restantes:
        return {"producao": producao, "resumo": resumo, "como_cada_forma_e_lida": leitura,
                "manchete": ("Não há o que perguntar nesta diária, e não chamei o agente: o programa lê os arquivos, "
                             f"menos {len(p.ninguem_sabe)} que o editor já disse não saber."),
                "o_que_fazer": "Mostre ao editor como cada forma foi lida, com o exemplo, para ele conferir. Não ofereça gravar nada: não há regra nova."}
    entrada, sem_lugar = _diaria.entrada_do_agente(bin.strip().rsplit("/", 1)[-1] or Path(pasta).name, p, mem)
    if isinstance(respostas, list) and respostas:
        entrada["memoria"] = {**entrada["memoria"], "respostas_do_editor": respostas}
    _turno.avisar(f"o agente de metadado está olhando {len(entrada['formas'])} forma(s) de nome…")
    try:
        r = _agentes.rodar(AGENTE, entrada)
    except (_agentes.AgenteFalhou, _magro.TurnoFalhou) as e:
        return {"producao": producao, "resumo": resumo, "erro": f"O agente de metadado não respondeu: {e}. A leitura sem IA continua valendo."}
    resposta = r["resposta"]
    regras = _diaria.conferir_regras(p.restantes, [x for x in resposta["regras"] if isinstance(x, dict)],
                                     [*p.pelo_programa, *p.pela_memoria], mem.regras if mem else ())
    perguntas = _diaria.filtrar_perguntas(resposta["perguntas"], mem)
    cartao = _diaria.cartao_de_perguntas(perguntas, producao, p.restantes, any(x["aprovada"] for x in regras))
    turno = _turno.atual()
    if cartao and turno is not None:
        turno.mostrar_perguntas(cartao)
    no_cartao = bool(cartao) and turno is not None
    return {
        "producao": producao,
        "resumo": resumo,
        "como_cada_forma_e_lida": leitura,
        "regras_aprovadas": [x for x in regras if x["aprovada"]],
        "regras_reprovadas": [x for x in regras if not x["aprovada"]],
        "perguntas": perguntas,
        "formas_sem_regra": [str(f) for f in resposta["fora"]],
        "formas_que_nao_couberam": sem_lugar,
        "uso": {**r["uso"], "segundos": r["segundos"]},
        "o_que_fazer": (
            ("As perguntas JÁ estão na tela do editor, num cartão com uma caixa de resposta para cada uma. NÃO as repita nem liste os padrões: escreva no máximo "
             "duas frases, dizendo quantos arquivos o programa já leu e pedindo para responder no cartão. As respostas chegam na próxima mensagem. "
             if no_cartao else
             "Mostre ao editor as perguntas, agrupadas, em linguagem de montagem, e pergunte de que produção é a diária se `producao.memoria` for null. ")
            + "Nada disto é fato ainda: é proposta. Só depois das respostas chame gravar_na_memoria_da_producao, só com o que ele confirmou; 'não sei' vai em "
              "nao_se_sabe; pergunta sem resposta não é 'não sei' e não entra. Regra reprovada não é para gravar como veio: com a resposta dele, refaça o molde. "
              "Se o projeto aberto for desta produção, ponha o nome dele em apelidos."
        ),
    }


def _conferir_gravacao(producao: str = "", pasta: str = "", regras: list | None = None, apelidos: list | None = None, glossario: list | None = None,
                       nao_se_sabe: list | None = None, bin: str = "", programa: str = "", **_: Any) -> str:
    try:
        _memoria.nome_de_pasta(producao)
    except ValueError as e:
        return str(e)
    if not (regras or apelidos or glossario or nao_se_sabe):
        return "Não há nada para gravar."
    for g in glossario or []:
        if not isinstance(g, dict) or not str(g.get("termo") or "").strip() or not str(g.get("significado") or "").strip():
            return "Cada item de glossario precisa de `termo` e `significado`."
    if not regras:
        return ""
    if any(not isinstance(r, dict) or set(r) != {"forma", "molde"} for r in regras):
        return "Cada regra leva exatamente `forma` e `molde`, que é o que o editor vai ler no cartão."
    arquivos, recusa, _gerenciados = _carregar(pasta, bin, programa)
    if recusa:
        return recusa
    # ⛔ Confere de novo no disco: quem manda as regras é o modelo, e a conferência é o que protege a leitura (regra errada na memória vence tudo).
    mem = _memoria.achar(producao)
    regras_atuais = [r for r in (mem.regras if mem else ()) if r.forma not in {x["forma"] for x in regras}]
    p = _diaria.particionar(arquivos, regras_atuais)
    conferidas = _diaria.conferir_regras(p.restantes, regras, [*p.pelo_programa, *p.pela_memoria], regras_atuais)
    problemas = [f"{c['forma']}: {'; '.join(c['problemas'])}" for c in conferidas if not c["aprovada"]]
    return "Estas regras não passaram na conferência:\n" + "\n".join(problemas) if problemas else ""


@ferramenta(
    nome="gravar_na_memoria_da_producao",
    descricao=(
        "Guarda na memória da produção o que o EDITOR confirmou sobre os nomes do som direto: as regras (forma e molde, como vieram de "
        "entender_metadados_da_diaria), nomes da produção, glossário e o que ele disse não saber (não volta a ser perguntado). Vale a partir da "
        "próxima leitura, sem IA. Nunca grave dedução sua. Mesmo no modo automático o editor confirma."
    ),
    esquema={
        "type": "object",
        "properties": {
            "producao": {"type": "string", "description": "O nome da produção, como o editor disse."},
            "pasta": {"type": "string", "description": "A pasta da diária. Quando há regras, passe a pasta ou a bin: elas são conferidas nos arquivos."},
            "bin": {"type": "string", "description": "A bin da diária, a mesma passada na leitura, em vez da pasta."},
            "programa": {"type": "string", "enum": list(PROGRAMAS), "description": "De que programa é a bin, como na leitura."},
            "regras": {"type": "array",
                       "description": ("`forma`: o nome com os números como #, igual à devolvida na leitura. `molde`: a forma com cada # que o editor explicou trocado por "
                                       "{episodio}, {cena}, {plano} ou {take}; # sem explicação continua #; letras que fazem parte do valor entram como {cena|letras}."),
                       "items": {"type": "object", "properties": {"forma": {"type": "string"}, "molde": {"type": "string"}},
                                 "required": ["forma", "molde"], "additionalProperties": False}},
            "apelidos": {"type": "array", "items": {"type": "string"}, "description": "Outros nomes dela, como o projeto aberto no NLE, se o editor confirmou que é esta produção."},
            "glossario": {"type": "array", "items": {"type": "object", "properties": {"termo": {"type": "string"}, "significado": {"type": "string"}}, "required": ["termo", "significado"]}},
            "nao_se_sabe": {"type": "array", "items": {"type": "string"}, "description": "Um item por trecho de nome, escrito como aparece no arquivo, sobre o qual o editor respondeu que não sabe."},
        },
        "required": ["producao"],
    },
    escreve=True,
    conferir=_conferir_gravacao,
    nles=AMBOS,
    sempre_pergunta=True,
)
def gravar_na_memoria_da_producao(producao: str = "", pasta: str = "", regras: list | None = None, apelidos: list | None = None,
                                  glossario: list | None = None, nao_se_sabe: list | None = None, bin: str = "", programa: str = "") -> dict[str, Any]:
    # ⭐ O clique pode vir dias depois do cartão: os arquivos podem ter mudado.
    motivo = _conferir_gravacao(producao, pasta, regras, apelidos, glossario, nao_se_sabe, bin, programa)
    if motivo:
        return {"erro": motivo}
    try:
        m = _memoria.gravar(producao, regras or (), apelidos or (), [f"{g['termo']}: {g['significado']}" for g in glossario or []], nao_se_sabe or ())
    except (ValueError, OSError) as e:
        return {"erro": f"Não consegui gravar a memória: {e}"}
    projeto = _projeto_aberto()
    vale = not projeto or _memoria.achar(projeto) is not None and _memoria.achar(projeto).caminho == m.caminho
    aviso = "" if vale else f" ⚠️ O projeto aberto ('{projeto}') não é um nome desta produção: a regra não vale nele até o editor confirmar e ele entrar nos apelidos."
    return {"producao": m.nome, "arquivo": m.caminho, "regras": len(m.regras), "vale_no_projeto_aberto": bool(projeto) and vale,
            "manchete": f"Memória de {m.nome} gravada, com {len(m.regras)} regra(s).{aviso}"}
