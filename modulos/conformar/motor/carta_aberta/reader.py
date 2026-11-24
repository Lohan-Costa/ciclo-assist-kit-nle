"""Lê uma Carta Aberta de volta para o que o motor consome. Especificação: `docs/carta-aberta.md`.

É o avesso de `writer.montar`: devolve a leitura CRUA (o `resultado` que `ler_timeline` daria)
e o que o remetente sabia da mídia, para que quem recebe rode o mesmo
`avb_bin.segmentos.montar_midia` → `drp.writer.build_drt` e chegue ao mesmo DRT.

⚠️⚠️ **A Carta é TEXTO DE TERCEIRO.** Chega de outra máquina, por uma pasta de rede que
qualquer um com acesso pode escrever. Por isso este módulo:

- tem teto de tamanho (`LIMITE_BYTES`) e só aceita a versão maior que conhece (`1.x`);
- confere a FORMA (listas, dicts, números) e recusa com `CartaInvalida` em vez de deixar um
  `KeyError` escapar do meio do motor;
- **nunca toca um caminho que venha de dentro dela** — nem `exists()`: num caminho UNC isso
  abre sessão SMB para o host que o autor da Carta escolheu (banco,
  `transversal/matriz-de-plataforma.md` §C). Decidir o que existe NESTA máquina é do receptor,
  com `avb_bin.segmentos.caminho_confiavel`.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from carta_aberta.writer import CAMPOS_DO_MASTER, TIPOS_DE_ENVIO

#: Uma Carta de uma timeline de ~1200 eventos tem ~2–3 MB. 64 MB é folga de 20× e ainda
#: barra um arquivo hostil antes de o `json` montá-lo inteiro na memória.
LIMITE_BYTES = 64 * 1024 * 1024

#: Teto de TRABALHO, não de bytes (ataque V5): 300 mil segmentos cabem em poucos MB e fariam o
#: writer do DRT rodar por minutos com o Resolve travado esperando. A timeline real mais longa
#: medida tem 1.192 segmentos; 100 mil é folga de ~80×.
LIMITE_SEGMENTOS = 100_000
LIMITE_MASTERS = 50_000

#: Chaves que o WRITER acrescenta a cada segmento para quem lê a Carta; não são da leitura.
_DO_WRITER = ("arquivo", "offline")


class CartaInvalida(ValueError):
    """A Carta não pôde ser lida — o texto diz por quê, para o editor."""


@dataclass
class Carta:
    """O que o receptor precisa, já na forma do motor."""

    resultado: dict                      # como `ler_timeline` devolveria
    arquivos: dict[str, str]             # {master: arquivo AMA do REMETENTE}
    gerenciados: dict[str, str]          # {urn da essência: .mxf do REMETENTE}
    colunas_por_mob: dict[str, dict]     # {master: colunas do MC (Source File/Path/Tape)}
    nome: str = ""
    comentario: str | None = None
    envio: dict | None = None
    selecao: list[dict] | None = None
    versao: str = ""
    doc: dict = field(default_factory=dict, repr=False)

    @property
    def tipo(self) -> str:
        return (self.envio or {}).get("tipo") or "timeline"


def ler_carta(origem: str | Path | dict, limite_bytes: int = LIMITE_BYTES) -> Carta:
    """Lê de um caminho (`str`/`Path`) ou de um documento já carregado (`dict`)."""
    if isinstance(origem, dict):
        doc = origem
    else:
        caminho = Path(origem)
        try:
            tamanho = caminho.stat().st_size
        except OSError as e:
            raise CartaInvalida(f"não consegui abrir a carta: {e.strerror or e}") from None
        if tamanho > limite_bytes:
            raise CartaInvalida(f"a carta tem {tamanho // (1024 * 1024)} MB — "
                                f"passa do limite de {limite_bytes // (1024 * 1024)} MB")
        try:
            doc = json.loads(caminho.read_text(encoding="utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as e:
            raise CartaInvalida(f"a carta não é um JSON legível ({e.__class__.__name__})") from None
        except RecursionError:
            # Ataque V4: `[[[[…]]]]` em 400 KB estoura a pilha do parser. Tem de virar
            # "carta inválida", não uma exceção que derruba a caixa inteira.
            raise CartaInvalida("a carta tem aninhamento absurdo — recusada") from None
    return _interpretar(doc)


def _sem_caminhos(s: dict) -> dict:
    """Ataque V3: o `media_ref` de um segmento traz o caminho/URL de mídia da máquina de quem
    ENVIOU. Na leitura crua da bin eles são vazios (`ler_timeline` não resolve arquivo); quem
    os preenche é o `montar_midia` DAQUI. Então um valor aqui só pode ser plantado — some."""
    ref = s.get("media_ref")
    if isinstance(ref, dict):
        s["media_ref"] = {**ref, "local_path": "", "url": ""}
    return s


def _exigir(cond: bool, texto: str) -> None:
    if not cond:
        raise CartaInvalida(texto)


def _numero(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _interpretar(doc) -> Carta:
    _exigir(isinstance(doc, dict), "a carta não é um objeto JSON")
    versao = doc.get("carta_aberta")
    _exigir(isinstance(versao, str) and versao.split(".")[0] == "1",
            f"versão de carta desconhecida: {versao!r} (este De Lá Pra Cá lê 1.x)")
    _exigir(versao != "1.0", "carta 1.0: não traz a leitura completa dos masters — "
                             "gere de novo com este De Lá Pra Cá")

    tempo = doc.get("tempo")
    origem = doc.get("origem")
    segmentos = doc.get("segmentos")
    masters = doc.get("masters")
    _exigir(isinstance(tempo, dict) and _numero(tempo.get("fps")) and tempo["fps"] > 0,
            "a carta não diz a taxa da timeline")
    _exigir(isinstance(origem, dict), "a carta não diz de onde veio")
    _exigir(isinstance(segmentos, list) and all(isinstance(s, dict) for s in segmentos),
            "os segmentos da carta estão malformados")
    _exigir(isinstance(masters, list) and all(isinstance(m, dict) for m in masters),
            "os masters da carta estão malformados")
    _exigir(len(segmentos) <= LIMITE_SEGMENTOS and len(masters) <= LIMITE_MASTERS,
            f"a carta tem {len(segmentos)} segmentos e {len(masters)} masters — passa do limite "
            f"({LIMITE_SEGMENTOS} / {LIMITE_MASTERS})")

    masters_leitura: dict[str, dict] = {}
    arquivos: dict[str, str] = {}
    gerenciados: dict[str, str] = {}
    colunas: dict[str, dict] = {}
    for m in masters:
        chave = m.get("mob_id")
        avid = m.get("avid")
        _exigir(isinstance(chave, str) and chave, "um master da carta não tem mob_id")
        _exigir(isinstance(avid, dict), f"o master {chave} não traz o bloco 'avid'")
        info = {k: avid[k] for k in CAMPOS_DO_MASTER if k in avid}
        info["mob_id"] = chave
        masters_leitura[chave] = info
        if isinstance(avid.get("colunas_mc"), dict):
            colunas[chave] = dict(avid["colunas_mc"])
        if isinstance(m.get("arquivo_ama"), str) and m["arquivo_ama"]:
            arquivos[chave] = m["arquivo_ama"]
        essencias = info.get("essencias") or {}
        for trilha, mxf in (m.get("gerenciadas") or {}).items():
            urn = essencias.get(trilha) if isinstance(essencias, dict) else None
            if isinstance(urn, str) and isinstance(mxf, str) and mxf:
                gerenciados[urn] = mxf

    segs = [_sem_caminhos({k: v for k, v in s.items() if k not in _DO_WRITER}) for s in segmentos]
    resultado = {
        "segments": segs,
        "timeline_fps": tempo["fps"],
        "total_segments": len(segs),
        "has_nested_scope": False,
        "composition_name": origem.get("sequencia") or "",
        "sequence_mob_id": origem.get("mob_id"),
        "timeline_start_frames": tempo.get("tc_inicial_frames"),
        "timeline_drop_frame": bool(tempo.get("drop_frame")),
        "timeline_start_tc": tempo.get("tc_inicial"),
        "markers": list(doc.get("marcadores") or []),
        "masters": masters_leitura,
        "avisos": list(doc.get("avisos") or []),
        "conferencia": list(doc.get("conferencia") or []),
        "fonte": origem.get("leitura") or "avb",
    }

    envio = doc.get("envio")
    if envio is not None:
        _exigir(isinstance(envio, dict) and envio.get("tipo") in TIPOS_DE_ENVIO,
                f"tipo de envio desconhecido: {(envio or {}).get('tipo')!r}")
    selecao = doc.get("selecao")
    if selecao is not None:
        _exigir(isinstance(selecao, list) and all(isinstance(s, dict) for s in selecao),
                "a seleção do insert está malformada")

    comentario = doc.get("comentario")
    return Carta(resultado=resultado, arquivos=arquivos, gerenciados=gerenciados,
                 colunas_por_mob=colunas, nome=str(doc.get("nome") or ""),
                 comentario=comentario if isinstance(comentario, str) else None,
                 envio=envio, selecao=selecao, versao=versao, doc=doc)
