r"""Magic Link em CANAIS: a edição no meio, um canal para cada setor.

Decisão do autor (2026-09-25, organograma "Três caminhos do De Lá Pra Cá"): cor e VFX nunca
trabalham no mesmo caminho. A edição conecta um canal para cada time; a cor conecta só o dela,
o VFX só o dele — um setor não enxerga o trabalho do outro PORQUE não conecta a pasta dele.
Setor novo (som, trilha) é UMA entrada em `SETORES`, e nada mais muda.

## Sem papel (autor, 2026-09-25, depois do primeiro teste)

A primeira versão tinha um PAPEL por máquina (edição, cor, vfx) que decidia qual caixa ler. No
teste do autor, o Avid e o Resolve rodavam na MESMA máquina, com o papel "edição": o Resolve lia
`para-edicao` e não via a timeline que o editor mandou para a cor. Saiu o papel: quem recebe vê
os DOIS sentidos de cada canal conectado, numa tabela com filtro (Da Edição, Da Cor…), e o Avid
envia sempre como edição. A separação entre setores continua: é a CONEXÃO (e a permissão de rede
da pasta) que decide o que cada ilha vê.

## A pasta de um canal

Uma pasta por canal (é ela que quem cuida da rede libera só para a edição e aquele setor), com
uma CAIXA DE ENTRADA para cada lado. Quem envia grava na caixa do outro lado:

    S:\_TRANSFER\magic-cor\
        para-cor\                  ← a edição grava, a cor lê
            X__1111.carta.json     ← pendente
            importado\timelines\   ← já entrou (o "De novo" lê daqui)
            importado\inserts\
        para-edicao\               ← a cor grava, a edição lê
            importado\timelines\
            importado\inserts\

As subpastas nascem sozinhas (`garantir_pastas`), na primeira vez que alguém conecta, envia ou
procura. As PASTAS dos canais seguem o projeto do Avid quando há um (`.delapraca.json` da pasta do
projeto — é da produção, vale para a equipe), e a máquina fora dele (o Resolve). Quem escolhe a
origem é `api/rotas.py`; este módulo só recebe o dict `{setor: pasta}`.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

import plataforma

log = logging.getLogger("delapraca.canais")

EDICAO = "edicao"

#: ⭐ A lista que cresce. `insert` é o tipo de envio de um insert mandado PARA o setor (ele entra
#: na Carta, `envio.tipo`); `de`/`para` são os rótulos do painel.
SETORES: dict[str, dict] = {
    "cor": {"rotulo": "Cor", "de": "da Cor", "para": "para a Cor", "insert": "insert_cor"},
    "vfx": {"rotulo": "VFX", "de": "do VFX", "para": "para o VFX", "insert": "insert_vfx"},
}
ROTULO_LADO = {EDICAO: "Edição", **{k: v["rotulo"] for k, v in SETORES.items()}}

IMPORTADO = "importado"
#: A subpasta de `importado` pelo tipo do envio.
SUBPASTA = {"timeline": "timelines", "insert": "inserts",
            **{v["insert"]: "inserts" for v in SETORES.values()}}
CONFIG = "magic_link.json"


def caixa_nome(lado: str) -> str:
    """A caixa de entrada de um lado: `para-edicao`, `para-cor`…"""
    return f"para-{lado}"


def e_setor(setor) -> bool:
    return isinstance(setor, str) and setor in SETORES


# ── os canais desta máquina (o Resolve, que não tem pasta de projeto) ────────────────────

def _config_maquina() -> dict:
    try:
        d = json.loads((plataforma.pasta_dados() / CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _gravar_maquina(d: dict) -> None:
    pasta = plataforma.pasta_dados()
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / CONFIG
    tmp = alvo.with_name(f"{CONFIG}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, alvo)


def canais_da_maquina() -> dict[str, str]:
    """`{setor: pasta}` guardados nesta máquina. (Um `papel` antigo no arquivo é ignorado.)"""
    c = _config_maquina().get("canais")
    return {k: v for k, v in c.items() if e_setor(k) and isinstance(v, str)} if isinstance(c, dict) else {}


def guardar_canal_na_maquina(setor: str, pasta: str) -> None:
    d = _config_maquina()
    d.pop("papel", None)
    d["canais"] = {**canais_da_maquina(), setor: pasta}
    _gravar_maquina(d)


# ── a pasta do canal ─────────────────────────────────────────────────────────────────────

def pasta_do_canal(canais: dict, setor: str) -> str | None:
    """A pasta do canal, se estiver configurada E alcançável agora."""
    p = canais.get(setor) if e_setor(setor) else None
    return p if isinstance(p, str) and p and Path(p).is_dir() else None


def validar_pasta(pasta: str) -> str:
    p = Path(pasta or "")
    if not p.is_absolute():
        raise ValueError("escolha uma pasta (caminho completo)")
    if not p.is_dir():
        raise ValueError("essa pasta não existe ou não está acessível agora")
    return str(p)


def lados(setor: str) -> tuple[str, str]:
    """Os dois lados de um canal: `(edicao, setor)`."""
    return EDICAO, setor


def garantir_pastas(pasta_canal: str, setor: str) -> None:
    """As duas caixas do canal, cada uma com `importado/timelines` e `importado/inserts`."""
    for lado in lados(setor):
        for sub in set(SUBPASTA.values()):
            (Path(pasta_canal) / caixa_nome(lado) / IMPORTADO / sub).mkdir(parents=True, exist_ok=True)


def caixa_de_saida(canais: dict, setor: str) -> str:
    """Onde a EDIÇÃO grava um envio para o setor: a caixa `para-<setor>` do canal.

    Levanta ValueError com o motivo. (Enviar de um setor de volta para a edição é a entrega 3.)
    """
    if not e_setor(setor):
        raise ValueError(f"canal desconhecido: {setor!r}")
    pasta = pasta_do_canal(canais, setor)
    if not pasta:
        raise ValueError(f"conecte o canal {SETORES[setor]['rotulo']} em Ajustes antes de enviar")
    garantir_pastas(pasta, setor)
    return str(Path(pasta) / caixa_nome(setor))


def tipo_do_insert(setor: str) -> str:
    """O insert pega o tipo do CANAL: mandado pelo canal VFX, é um insert de VFX."""
    return SETORES[setor]["insert"]


# ── arquivar o que já entrou ─────────────────────────────────────────────────────────────

def arquivar(carta: str, tipo: str) -> str:
    """Move a Carta pendente para `importado/<timelines|inserts>` da MESMA caixa.

    Nunca sobrescreve: `X.carta.json` já existe → `X_2.carta.json`. Devolve o caminho novo.
    Levanta OSError se a rede recusar — quem chama registra e segue (a timeline já entrou).
    """
    p = Path(carta)
    destino = p.parent / IMPORTADO / SUBPASTA.get(tipo, "timelines")
    destino.mkdir(parents=True, exist_ok=True)
    base = p.name[:-len(".carta.json")] if p.name.endswith(".carta.json") else p.stem
    alvo = destino / p.name
    n = 2
    while alvo.exists():
        alvo = destino / f"{base}_{n}.carta.json"
        n += 1
    os.replace(p, alvo)
    # A bin anexa (Magic Link de timeline, `magic_link.anexo_da_carta`) vai junto, com o MESMO nome da Carta.
    # Acessório: se a rede recusar, a Carta já desceu e a bin fica na fila — não derruba nada.
    anexo = p.with_name(base + ".avb")
    if anexo.is_file():
        try:
            os.replace(anexo, alvo.with_name(alvo.name[:-len(".carta.json")] + ".avb"))
        except OSError:
            pass
    return str(alvo)


def e_pendente(carta: str) -> bool:
    """A Carta está na caixa (fila), e não dentro de `importado`?"""
    return Path(carta).parent.name.startswith("para-")
