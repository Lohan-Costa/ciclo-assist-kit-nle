"""Abrir e fechar os programas do fluxo — e um projeto neles: o Ciclo Assist fora de todos.

⭐⭐ Pedido do autor (2026-10-29): o editor pode pedir com nenhum programa aberto, e o Ciclo
Assist sobe o programa e o projeto. Ampliado em 2026-11-01: *"mapear logo os comandos básicos
de abrir e fechar os programas, visto que lidamos com o Resolve, com o Premiere e com o Media
Composer — assim já ganhamos a liberdade de conversar cross NLE"*.

O MAPA (cada linha medida; o detalhe mora no módulo de cada programa):

| programa | abrir | abrir/criar projeto | fechar | módulo |
|---|---|---|---|---|
| DaVinci Resolve | processo pelo explorer, espera a porta 1144 | `LoadProject` / `CreateProject` (API) | `SaveProject` + `Quit`, espera o PROCESSO (~12 s) | `cicloassist/resolve.py` |
| Premiere Pro | executável (o ano mais novo), `.prproj` na linha de comando | `app.openDocument` / `app.newProject` (ponte CEP) | `save` + `app.quit`; se ficar, `WM_CLOSE`; à força só salvo | `cicloassist/premiere_app.py` |
| Media Composer | processo pelo explorer | PILOTO: Select Project (lista ou New Project + Format) | PILOTO: File → Exit → Leave | `cicloassist/avid/abrir.py` |

⛔⛔ **A REGRA ESPECIAL, nas palavras do autor:** *"se o usuário não informar no prompt o
programa que deve subir, o Ciclo Assist deve perguntar mesmo que a opção auto esteja ligada"*.
Ela mora no CÓDIGO (`_conferir`), não só na descrição: a conferência roda ANTES do modo
automático (`portao.py`), e lê o que o EDITOR escreveu — nunca o que o modelo entendeu. Abrir
um programa pesa minutos e memória na máquina de quem trabalha; escolher qual é decisão dele.
⭐ Desde 2026-11-01 ela lê a CONVERSA inteira (`turno.da_conversa`), não só a pergunta da vez:
num fluxo de vários turnos, o "abra o Media Composer" está no primeiro e o seguinte diz "pode
seguir".
"""

from __future__ import annotations

import logging
import os
import re
import unicodedata

from ... import premiere_app as _premiere
from ... import resolve as _resolve
from ...avid import abrir as _mc
from ...piloto import falhas as _falhas
from ...servico import turno as _turno
from ..registro import AMBOS, ferramenta

log = logging.getLogger("cicloassist.mcp.programas")

#: Os programas que estas ferramentas conhecem, e as PALAVRAS com que o editor os nomeia
#: (comparadas sem acento, palavra inteira — "mc" não pode casar dentro de "mcp").
PROGRAMAS = {
    "resolve": ("resolve", "davinci"),
    "premiere": ("premiere",),
    "media_composer": ("media composer", "avid", "mc"),
}
NOMES = {"resolve": "DaVinci Resolve", "premiere": "Premiere Pro", "media_composer": "Media Composer"}


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto.casefold())
                   if unicodedata.category(c) != "Mn")


def nomeado_pelo_editor(programa: str, texto: str | None = None) -> bool:
    """O editor escreveu o nome do programa nesta conversa (ou em `texto`, se dado)?

    ⭐ Num passo de FLUXO aprovado vale o clique: o cartão do fluxo listava este passo com o
    programa pelo nome, e o editor disse "pode fazer" (`servico/fluxo.em_fluxo_aprovado`). Sem
    isso a receita rodada por botão — que não tem conversa nenhuma — nunca abriria um programa.
    ⭐⭐ Decisão do autor (2026-11-01, na revisão da F1): dentro de um fluxo — com cartão OU no modo
    automático — abrir é autorizado, e só para os três de `PROGRAMAS` (Premiere Pro, DaVinci
    Resolve, Media Composer); a ferramenta não sabe abrir outro. Fora de fluxo, a regra de antes.
    """
    from ...servico import fluxo as _fluxo
    if texto is None and _fluxo.em_fluxo_aprovado():
        return programa in PROGRAMAS
    if texto is None:
        t = _turno.atual()
        texto = " \n ".join(_turno.da_conversa() + [t.texto_do_editor if t else ""])
    limpo = _sem_acento(texto or "")
    return any(re.search(rf"(?<![a-z0-9]){re.escape(p)}(?![a-z0-9])", limpo)
               for p in PROGRAMAS.get(programa, ()))


def _conferir(programa: str = "resolve", projeto: str = "", formato: str = "", versao: str = "", **_) -> str:
    if programa not in PROGRAMAS:
        return f"Ainda não sei abrir '{programa}'. Sei abrir: {', '.join(PROGRAMAS)}."
    if not nomeado_pelo_editor(programa):
        return ("O editor NÃO disse qual programa abrir nesta conversa. Pergunte a ele em uma "
                "frase qual programa deve subir (por exemplo: \"Em qual programa? DaVinci Resolve?\") "
                "e espere a resposta. Não escolha por ele, nem pelo tipo do arquivo — vale mesmo "
                "com o modo automático ligado.")
    projeto = (projeto or "").strip()
    if not projeto:
        return (f"Diga o projeto a abrir ou criar no {NOMES[programa]}. Se o editor não disse, use "
                "o nome do arquivo do projeto arrastado, sem a extensão.")
    if programa == "resolve" and not _resolve.instalado():
        return f"O DaVinci Resolve não está instalado nesta máquina ({_resolve.APLICATIVO})."
    if versao and programa != "premiere":
        return "versao só vale para o Premiere Pro (o ano: 2023, 2026…, ou beta)."
    if programa == "premiere":
        if not _premiere.executavel(versao):
            anos = ", ".join([str(a) for a in sorted(_premiere.instalados())]
                             + (["beta"] if _premiere.beta() else []))
            if versao and anos:
                return f"O Premiere Pro {versao} não está instalado; há: {anos}. Pergunte ao editor qual usar."
            return "O Premiere Pro não está instalado nesta máquina."
        if not projeto.lower().endswith(".prproj") or not os.path.isabs(projeto):
            return ("No Premiere o projeto é um ARQUIVO: passe o caminho completo do .prproj (ex.: "
                    "na pasta da mídia que o editor arrastou, <pasta>\\<nome>.prproj). Se ele não "
                    "existir, é criado ali.")
        if not os.path.isdir(os.path.dirname(projeto)):
            return f"A pasta do projeto não existe: {os.path.dirname(projeto)}"
    if programa == "media_composer":
        if formato:
            try:
                _mc.grupo_do_formato(formato)
            except _mc.McNaoAbre as e:
                return str(e)
    return ""


def _contando(etapa: str, fracao: float | None, detalhe: str = "") -> None:
    _turno.avisar(etapa, fracao, detalhe)


_COMO = {"ja_aberto": "já estava aberto", "aberto": "aberto", "criado": "criado agora"}


@ferramenta(
    nome="abrir_programa",
    descricao=(
        "Abre um programa na máquina do editor e um projeto nele, CRIANDO o projeto se não existir "
        "— para quando o editor pede algo com o programa fechado, ou para passar de um programa ao "
        "outro num fluxo. programa: resolve (projeto = nome) · premiere (projeto = caminho completo "
        "do .prproj; sem versao, o Premiere MAIS NOVO de produção; versao 'beta' só se o editor pediu o beta) · media_composer (projeto = nome; para CRIAR, passe formato no padrão do MC, "
        "ex. '1080p/25', tirado da resolução e da taxa da mídia que vai entrar). No Media Composer "
        "é o piloto que opera a tela (~1 min, alguns centavos); com OUTRO projeto aberto, ele o "
        "fecha antes. ⛔ Só chame se o EDITOR nomeou o programa na conversa; se ele não disse qual, "
        "PERGUNTE — mesmo com o modo automático ligado; não deduza pelo tipo do arquivo."
    ),
    esquema={
        "type": "object",
        "properties": {
            "programa": {"type": "string", "enum": list(PROGRAMAS)},
            "projeto": {"type": "string",
                        "description": "Resolve e Media Composer: o nome. Premiere: o caminho completo do .prproj."},
            "versao": {"type": "string",
                       "description": "Só Premiere, e só se o editor pediu uma versão: o ano (ex. '2023') ou 'beta'. Vazio = a mais nova de produção."},
            "formato": {"type": "string",
                        "description": "Só Media Composer, e só para CRIAR: '1080p/25', '1080p/23.976', '1080i/50', '720p/50'…"},
        },
        "required": ["programa", "projeto"],
    },
    escreve=True,
    conferir=_conferir,
    nles=AMBOS,
)
def abrir_programa(programa: str = "resolve", projeto: str = "", formato: str = "",
                   versao: str = "") -> dict[str, object]:
    marca = _falhas.agora()
    return _com_falhas(_abrir(programa, projeto, formato, versao), programa, marca)


def _abrir(programa: str, projeto: str, formato: str, versao: str) -> dict[str, object]:
    projeto = (projeto or "").strip()
    try:
        if programa == "resolve":
            a = _resolve.abrir(relatar=_contando)
            _contando("abrindo o projeto no DaVinci Resolve", None, projeto)
            p = _resolve.projeto(projeto)
            situacao = "já estava aberto" if a["ja_estava"] else f"aberto em {a['segundos']} s"
            if a.get("reaberturas"):
                situacao += (f" (fechei e abri de novo {a['reaberturas']} vez[es]: o servidor de "
                             f"scripts dele não tinha ligado)")
            return {"programa": f"DaVinci Resolve {p.get('versao', '')}".strip(),
                    "situacao": situacao,
                    "projeto": p.get("projeto"), "projeto_foi": _COMO.get(str(p.get("como")), p.get("como")),
                    "agora": f"O Resolve está com o projeto '{p.get('projeto')}' aberto. Siga o pedido do editor."}
        if programa == "premiere":
            a = _premiere.abrir(projeto, relatar=_contando, versao=versao)
            return {"programa": "Premiere Pro (Beta)" if _premiere.e_beta(versao) else "Premiere Pro",
                    "situacao": "já estava aberto" if a["ja_estava"] else f"aberto em {a['segundos']} s",
                    "projeto": a["caminho"], "projeto_foi": _COMO.get(a["como"], a["como"]),
                    "agora": "O Premiere está com o projeto aberto. Siga o pedido do editor."}
        if programa == "media_composer":
            a = _mc.abrir(projeto, formato, relatar=_contando)
            return {"programa": "Media Composer", "situacao": f"pronto em {a['segundos']} s",
                    "projeto": projeto, "projeto_foi": _COMO.get(a["como"], a["como"]),
                    "piloto": {"custo_usd": a.get("custo_usd"), "passos": a.get("passos"), **({"agente_do_piloto": a["agente_do_piloto"]} if a.get("agente_do_piloto") else {})},
                    "agora": f"O Media Composer está com o projeto '{projeto}' aberto. Siga o pedido do editor."}
    except (_resolve.ResolveIndisponivel, _premiere.PremiereNaoAbre, _mc.McNaoAbre) as e:
        log.warning("abrir_programa(%s, %r) falhou: %s", programa, projeto, e)
        return {"erro": str(e)}
    return {"erro": f"programa desconhecido: {programa}"}


# ── as falhas do sistema (autor, 2026-11-22) ─────────────────────────────────
#
# ⛔ O macOS mostrou "Relatório de Problemas" na tela do autor durante um fluxo pilotado (o MC abortou ao abrir; o
# Baselight caiu ao sair) e ninguém do nosso lado viu: "mesmo que inofensivas pro usuário algo está errado". Depois de
# abrir e de fechar, o que o sistema registrou de falha DESTE programa vai na resposta, e o modelo conta ao editor.

#: o pedaço do nome do processo nos relatórios de falha (o MC inclui os auxiliares: `AvidIdentityHandler`…)
_PROCESSOS = {"resolve": ["Resolve"], "premiere": ["Premiere"], "media_composer": ["Avid"]}


def _com_falhas(r: dict[str, object], programa: str, marca: float) -> dict[str, object]:
    try:
        achadas = _falhas.desde(marca, _PROCESSOS.get(programa))
    except Exception as e:      # noqa: BLE001 — conferir as falhas nunca derruba a ferramenta
        log.warning("falhas do sistema ilegíveis: %s", e)
        return r
    if achadas:
        frases = [_falhas.frase(f) for f in achadas]
        log.warning("falhas do sistema em %s: %s", programa, frases)
        r = {**r, "falhas_do_sistema": frases,
             "agora": (str(r.get("agora") or "") + " ⚠️ O sistema registrou falha(s) deste programa enquanto ele "
                       "abria/fechava (o editor pode ter visto um aviso do sistema na tela): conte a ele, com a hora e "
                       "o motivo de `falhas_do_sistema`, antes de seguir.").strip()}
    return r


# ── fechar ───────────────────────────────────────────────────────────────────
#
# ⭐ Pedido do autor (2026-11-01), no fluxo de ponta a ponta: "ao terminar o render, feche o
# Resolve, e depois abra o Media Composer". Sem esta ferramenta o modelo parava ali e devolvia
# o gesto ao editor.
#
# ⚠️ Diferente de ABRIR, fechar NÃO exige o nome do programa: o que protege o trabalho do editor
# é o código — salva antes, recusa no meio de um render, e só encerra à força o que está salvo.

def _conferir_fechar(programa: str = "resolve", **_) -> str:
    if programa not in PROGRAMAS:
        return f"Ainda não sei fechar '{programa}'. Sei fechar: {', '.join(PROGRAMAS)}."
    return ""


@ferramenta(
    nome="fechar_programa",
    descricao=(
        "Salva o projeto aberto e fecha um programa na máquina do editor — para liberar a máquina "
        "entre etapas de um fluxo (ex.: converter no Resolve e depois seguir no Media Composer). "
        "programa: resolve · premiere · media_composer (no MC o piloto faz File → Exit → Leave; "
        "as bins o MC salva ao sair). Espera o programa sair de verdade; o Resolve recusa se "
        "estiver renderizando. Só feche quando o editor pediu, ou quando o fluxo que ele pediu exige."
    ),
    esquema={
        "type": "object",
        "properties": {"programa": {"type": "string", "enum": list(PROGRAMAS)}},
        "required": ["programa"],
    },
    escreve=True,
    conferir=_conferir_fechar,
    nles=AMBOS,
)
def fechar_programa(programa: str = "resolve") -> dict[str, object]:
    marca = _falhas.agora()
    return _com_falhas(_fechar(programa), programa, marca)


def _fechar(programa: str) -> dict[str, object]:
    nome = NOMES.get(programa, programa)
    try:
        if programa == "resolve":
            f = _resolve.fechar(relatar=_contando)
            projeto = f.get("projeto") or ""
        elif programa == "premiere":
            f = _premiere.fechar(relatar=_contando)
            projeto = f.get("caminho") or ""
        elif programa == "media_composer":
            f = _mc.fechar(relatar=_contando)
            projeto = f.get("projeto") or ""
            f.setdefault("salvo", bool(projeto))     # o MC salva as bins ao sair (Leave)
        else:
            return {"erro": f"programa desconhecido: {programa}"}
    except (_resolve.ResolveIndisponivel, _premiere.PremiereNaoAbre, _mc.McNaoAbre) as e:
        log.warning("fechar_programa(%s) falhou: %s", programa, e)
        return {"erro": str(e)}
    if f["ja_estava_fechado"]:
        return {"programa": nome, "situacao": "já estava fechado", "agora": "Siga o pedido do editor."}
    r = {
        "programa": nome,
        "situacao": f"fechado em {f['segundos']} s",
        "projeto_salvo": (f"'{os.path.basename(projeto)}' salvo" if f.get("salvo")
                          else f"'{os.path.basename(projeto)}' NÃO foi salvo" if projeto
                          else "nenhum projeto aberto"),
        "agora": f"O {nome} está fechado. Siga o pedido do editor.",
    }
    if f.get("como") and f["como"] != "quit":
        r["como_fechou"] = {"wm_close": "pela janela (o pedido de sair não bastou)",
                            "forcado": "à força, com o projeto já salvo"}.get(f["como"], f["como"])
    if f.get("custo_usd"):
        r["piloto"] = {"custo_usd": f["custo_usd"], "passos": f.get("passos"), **({"agente_do_piloto": f["agente_do_piloto"]} if f.get("agente_do_piloto") else {})}
    return r
