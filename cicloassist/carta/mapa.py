"""O CONFORM PELO MAPA (plano `docs/plano/2026-11-26-carta-registro-da-producao.md`, etapa 3; a visão do autor: "quando o
fluxo é nosso do ingest ao online, nós sabemos para onde cada mídia foi convertida").

O Conformar pergunta, por master da timeline: "este clipe aponta para o arquivo X (o offline: o proxy, a OP-Atom, o
daily) — de que ORIGINAL ele é?". A Carta responde pelo que já registrou:

1. o arquivo X é uma FORMA registrada de uma mídia (pelo caminho; ou, movido fora do nosso controle, pela IMPRESSÃO);
2. a forma `original` dessa mídia existe NESTA máquina e a impressão dela confere com a registrada;
3. a RELAÇÃO (`relacoes.py`), quando houver, diz a transformação (escala, TC, taxa, trecho, canais).

⛔ O mapa é DICA forte, nunca a regra (a família: "o caminho é dica, a identidade é a verdade"; o banco do Conformar, o
mesmo princípio): o que ele não souber com certeza segue para o casamento de sempre (o De Lá Pra Cá: banco + varredura).
⛔ Empate é do editor: duas Cartas (ou dois vínculos) com originais diferentes para o mesmo offline = ALERTA, sem
resposta; impressão que não confere = ALERTA, sem resposta. Nada de desempate automático.

O pedido (`/nucleo/carta/mapa`): `{"masters": [{"chave", "nome", "origem", "arquivos"?, "e_audio"?}]}`.
A resposta: `{"achados": {chave: {"arquivo", "carta", "midia", "por", "forma_do_offline", "transformacao", "frase"}},
"alertas": [{"chave", "nome", "motivo"}], "cartas": n}`.
"""

from __future__ import annotations

import os
from pathlib import Path

from . import diario, projeto, relacoes, vista
from .anexar import _nfc
from .projeto import CartaErro, Projeto


def _chave(caminho: str) -> str:
    return _nfc(os.path.normcase(os.path.abspath(caminho)))


def _existentes(origem: str) -> list[str]:
    """O caminho do offline nesta máquina. ⚠️ O AAF do MC no Mac grava sem o `/Volumes` (`/SSD/…`) — a mesma
    correção do `matcher_masters._daily`."""
    out = []
    for c in (origem, "/Volumes" + origem if origem.startswith("/") and not origem.startswith("/Volumes/") else ""):
        if c and os.path.isfile(c):
            out.append(c)
    return out


def _impressao(arquivo: str) -> str | None:
    from ..midia import identidade as _id
    try:
        return _id.impressao(arquivo)
    except OSError:
        return None


class _Indice:
    """O que UMA Carta sabe, montado uma vez por consulta: caminho → forma, impressão → formas, originais por mídia."""

    def __init__(self, proj: Projeto) -> None:
        self.proj = proj
        self.por_caminho: dict[str, list[dict]] = {}
        self.por_impressao: dict[str, list[dict]] = {}
        self.originais: dict[str, list[dict]] = {}
        letras = vista._letras_por_rotulo() if os.name == "nt" else None
        for midia, fs in diario.formas(proj).items():
            for f in fs:
                caminhos = [vista.traduzir(f, letras)]
                for a in f.get("arquivos") or []:          # a OP-Atom: um arquivo por trilha, gravados no fato
                    caminhos.append(str(a))
                g = {**f, "_local": caminhos[0]}
                for c in caminhos:
                    if c:
                        self.por_caminho.setdefault(_chave(c), []).append(g)
                if f.get("impressao"):
                    self.por_impressao.setdefault(f["impressao"], []).append(g)
                if f.get("forma") == "original":
                    self.originais.setdefault(midia, []).append(g)
        self.relacoes = relacoes.relacoes(proj)

    def transformacao(self, midia: str, offline: str) -> dict | None:
        alvo = _chave(offline)
        for r in self.relacoes.get(midia) or []:
            if _chave(vista.traduzir(r)) == alvo:
                return r.get("transformacao") or {}
        return None


def _resposta_de_uma_carta(ind: _Indice, offline: str) -> tuple[dict | None, str | None]:
    """(achado, alerta) desta Carta para o arquivo `offline`; (None, None) = a Carta não conhece o arquivo."""
    formas = ind.por_caminho.get(_chave(offline)) or []
    por = "caminho"
    imp_agora = None
    if formas:
        registradas = {f.get("impressao") for f in formas if f.get("impressao")}
        if registradas:
            imp_agora = _impressao(offline)
            if imp_agora and imp_agora not in registradas:
                return None, (f"{Path(offline).name}: o arquivo no lugar não é o registrado na Carta "
                              f"{ind.proj.nome} (a impressão não confere) — vai pelo casamento")
    elif ind.por_impressao:
        imp_agora = _impressao(offline)
        formas = ind.por_impressao.get(imp_agora or "") or []
        por = "impressao"
    if not formas:
        return None, None
    midias = {f["midia"] for f in formas}
    if len(midias) > 1:
        return None, f"{Path(offline).name}: a Carta {ind.proj.nome} o liga a {len(midias)} mídias — o editor decide"
    midia = midias.pop()
    forma_do_offline = formas[0].get("forma")
    if forma_do_offline == "original":
        return {"arquivo": offline, "midia": midia, "por": por, "forma_do_offline": "original",
                "transformacao": None}, None
    vivos, trocados = [], []
    for o in ind.originais.get(midia) or []:
        c = o["_local"]
        if not c or not os.path.isfile(c):
            continue
        if o.get("impressao") and _impressao(c) != o["impressao"]:
            trocados.append(Path(c).name)
            continue
        vivos.append(c)
    distintos = sorted({_chave(c): c for c in vivos}.values())
    if len(distintos) > 1:
        return None, (f"{Path(offline).name}: a Carta {ind.proj.nome} tem {len(distintos)} originais para a mesma "
                      f"mídia ({', '.join(Path(c).name for c in distintos)}) — o editor decide")
    if not distintos:
        if trocados:
            return None, (f"{Path(offline).name}: o original registrado ({trocados[0]}) mudou desde o registro "
                          f"(a impressão não confere) — vai pelo casamento")
        return None, None                                   # o original não está nesta máquina: segue o casamento
    return {"arquivo": distintos[0], "midia": midia, "por": por, "forma_do_offline": forma_do_offline,
            "transformacao": ind.transformacao(midia, offline)}, None


def consultar(raizes: list[str], masters: list[dict]) -> dict:
    """O mapa de TODAS as Cartas `raizes` para os `masters` (ver o docstring do módulo)."""
    indices: list[_Indice] = []
    for r in raizes:
        try:
            indices.append(_Indice(projeto.abrir(r)))
        except (CartaErro, OSError, ValueError):
            continue                                        # Carta que sumiu ou não abre: as outras seguem
    achados: dict[str, dict] = {}
    alertas: list[dict] = []
    if not indices:
        return {"achados": achados, "alertas": alertas, "cartas": 0}
    for m in masters:
        chave, nome = str(m.get("chave") or ""), str(m.get("nome") or "")
        if not chave:
            continue
        locais = []
        for o in [str(m.get("origem") or ""), *[str(a) for a in m.get("arquivos") or []]]:
            locais += _existentes(o) if o else []
        if not locais:
            continue
        respostas: dict[str, tuple[_Indice, dict]] = {}
        motivos = []
        for ind in indices:
            for offline in locais:
                achado, alerta = _resposta_de_uma_carta(ind, offline)
                if alerta:
                    motivos.append(alerta)
                if achado:
                    respostas.setdefault(_chave(achado["arquivo"]), (ind, achado))
                    break
        if len(respostas) > 1:
            alertas.append({"chave": chave, "nome": nome, "motivo": "as Cartas discordam do original: " + " × ".join(
                f"{Path(a['arquivo']).name} ({i.proj.nome})" for i, a in respostas.values()) + " — o editor decide"})
            continue
        if respostas:
            ind, achado = next(iter(respostas.values()))
            achados[chave] = {**achado, "carta": ind.proj.nome, "raiz": str(ind.proj.raiz)}
            achados[chave]["frase"] = explicar(achados[chave])
        elif motivos:
            alertas.append({"chave": chave, "nome": nome, "motivo": motivos[0]})
    return {"achados": achados, "alertas": alertas, "cartas": len(indices)}


def explicar(achado: dict) -> str:
    """A frase da revisão: de onde veio o original e com que transformação."""
    t = achado.get("transformacao") or {}
    partes = []
    e = t.get("enquadramento") or {}
    if e.get("tipo"):
        partes.append(f"{e['tipo']} {e.get('fator')}" if e.get("fator") else e["tipo"])
    if isinstance(t.get("taxa"), dict):
        partes.append(f"taxa {t['taxa'].get('de')} → {t['taxa'].get('para')}")
    if t.get("tc"):
        partes.append(f"TC {t['tc'].get('de')} → {t['tc'].get('para')}")
    if t.get("trecho"):
        partes.append("trecho do original")
    forma = {"trabalho": "o arquivo de trabalho (proxy)", "avid": "a mídia do Avid",
             "original": "é o próprio original"}.get(achado.get("forma_do_offline") or "", "a forma registrada")
    pela = ", achado pela impressão (foi movido)" if achado.get("por") == "impressao" else ""
    seta = "" if achado.get("forma_do_offline") == "original" else " → o original"
    base = f"pelo mapa da Carta {achado.get('carta')}: {forma}{pela}{seta}"
    return base + (f" ({', '.join(partes)})" if partes else "")
