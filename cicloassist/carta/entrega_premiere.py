"""PUXAR TIMELINE no Premiere: a timeline da Carta (`timeline.py`) vira um XML de timeline (FCP7 `xmeml` 4), que o
Premiere importa sozinho (`importFiles`), apontando a forma pedida de cada mídia — por padrão a OP-Atom do Avid
(o desafio da timeline real, autor 2026-11-13).

⭐ Por que XML e não `.prproj` escrito à mão: o XML é a porta de importação de timeline que o próprio Premiere mantém
(cortes, trilhas, TC, dissolves, volume de clipe, clipe desligado), e ele cria os clipes de mídia sozinho a partir do
caminho. O escritor de `.prproj` do Sincronizar é de DIÁRIA (câmeras + som sincronizados), não de timeline editada.
⚠️ O XML DUPLICA a mídia que o projeto já tem (o enxerto sem duplicar, banco `prproj/escrita.md` §11g, fica para
depois) — o relatório diz.

⛔ Não alterar um quadro (regra do De Lá Pra Cá): o corte vai exato, em quadros; o que o XML não leva fica DE FORA e
DITO no relatório (efeito de cor, estabilização, AudioSuite, título, reformat), nunca "aproximado". A mídia sem forma
nesta máquina (offline) fica de fora com o lugar dito: um caminho que não existe abriria o diálogo "Link Media" e
travaria a ponte (banco `premiere-cep/api-extendscript.md`).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from fractions import Fraction
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from . import diario, itens as _itens, referencias as _refs
from .projeto import CartaErro, Projeto

ORDEM_DAS_FORMAS = {"avid": ("avid", "original", "trabalho"), "original": ("original", "trabalho", "avid"),
                    "trabalho": ("trabalho", "original", "avid")}
#: o nome do efeito do Avid → a transição do XML (o que o Premiere traduz para Cross Dissolve / Constant Power)
_DISSOLVE_V = ("EFF2_BLEND_DISSOLVE", "BLEND_DISSOLVE")
_DISSOLVE_A = ("BLEND_AUDIO_DISSOLVE",)


def _rotulo_da_trilha(arquivo: str) -> str | None:
    """`V1`/`A2` do arquivo OP-Atom pelo nome (`X_A02.mxf`, `XA01.E69C….mxf`, `X.V01….mxf`); None se o nome não diz."""
    # ⛔ Só o SUFIXO do fim: o rolo da câmera no começo (`a001_03170314_C003`) não é a trilha A1 (medido na PRODA_CORTE:
    #    38 vídeos ficavam sem arquivo).
    m = re.search(r"(?:^|[._ ]|(?<=[a-z0-9]))([AV])(\d{2})(?:\.[0-9A-F]+(?:_[0-9A-F]+)*)?$", Path(arquivo).stem, re.I)
    return f"{m.group(1).upper()}{int(m.group(2))}" if m else None


def _rotulo_pela_sonda(arquivo: str) -> str | None:
    """O `track_name` da trilha que MORA no arquivo (a que tem `file_package_name`): `…_A02` → A2."""
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type:stream_tags", "-of", "json",
                            arquivo], capture_output=True, timeout=30)
        streams = json.loads(r.stdout or b"{}").get("streams") or []
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError):
        return None
    for s in streams:
        tags = s.get("tags") or {}
        if tags.get("file_package_name") or tags.get("timecode"):
            m = re.search(r"_([AV])0*(\d+)$", str(tags.get("track_name") or ""), re.I)
            if m:
                return f"{m.group(1).upper()}{int(m.group(2))}"
            return "V1" if s.get("codec_type") == "video" else None
    return None


def trilhas_do_master(arquivos: list[str]) -> dict[str, str]:
    """{"V1": arquivo, "A1": arquivo, …} dos N arquivos OP-Atom de um master. O vídeo sem sufixo é a V1."""
    out: dict[str, str] = {}
    for a in arquivos:
        r = _rotulo_da_trilha(a) or _rotulo_pela_sonda(a)
        if r is None and not re.search(r"_A\d+$", Path(a).stem, re.I):
            r = "V1"
        if r and r not in out:
            out[r] = a
    return out


def _forma_aqui(proj: Projeto, midia: str, ordem: tuple[str, ...]) -> tuple[str, list[str]] | None:
    """(forma, [arquivos NESTA máquina]) da primeira forma de `ordem` que existe aqui."""
    from .vista import _arquivos_traduzidos, traduzir
    fs = diario.formas(proj).get(midia, [])
    for forma in ordem:
        for f in fs:
            if f.get("forma") != forma:
                continue
            principal = traduzir(f)
            # ⛔ os N arquivos da OP-Atom vão para onde o PRINCIPAL foi traduzido. Antes só o principal mudava: no Windows
            #   (registro do Mac) o som de 5 canais chegava com o A01 só, e nenhum merged era feito (medido 2026-11-18)
            arquivos = _arquivos_traduzidos(f, principal) if f.get("arquivos") else [principal]
            arquivos = [a for a in arquivos if a and os.path.exists(a)]
            if arquivos:
                return forma, arquivos
    return None


def _url(caminho: str) -> str:
    return "file://localhost" + quote(os.path.abspath(caminho))


def _rate(taxa: Fraction) -> str:
    base = round(float(taxa))
    ntsc = "TRUE" if taxa.denominator == 1001 else "FALSE"
    return f"<rate><timebase>{base}</timebase><ntsc>{ntsc}</ntsc></rate>"


def _tc(q: int, base: int) -> str:
    s, f = divmod(q, base)
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    return f"{h:02d}:{m:02d}:{s:02d}:{f:02d}"


def _dimensoes(arquivo: str) -> tuple[int, int]:
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                            "stream=width,height", "-of", "json", arquivo], capture_output=True, timeout=30)
        s = (json.loads(r.stdout or b"{}").get("streams") or [{}])[0]
        return int(s.get("width") or 1920), int(s.get("height") or 1080)
    except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
        return 1920, 1080


class _Relatorio:
    def __init__(self):
        self.clipes = 0
        self.offline: dict[str, int] = {}          # nome da mídia → clipes que ficaram de fora
        self.sem_trilha: dict[str, str] = {}       # nome → a trilha do master que não tem arquivo
        self.efeitos_fora: dict[str, int] = {}     # efeito → vezes
        self.transicoes = 0
        self.transicoes_fora: dict[str, int] = {}
        self.velocidades: list[str] = []
        self.formas: dict[str, int] = {}
        self.avisos: list[str] = []

    def contar(self, d: dict, chave: str, n: int = 1) -> None:
        d[chave] = d.get(chave, 0) + n

    def como_dict(self) -> dict:
        return {k: v for k, v in vars(self).items()}


def _transicao(t: dict, audio: bool, base: int, taxa: Fraction) -> str:
    """O dissolve do Avid: a sobreposição [inicio, fim) com o CORTE em `corte_q` (o `cutpoint`). O XML põe a transição
    em volta do ponto de edição; `alignment` center quando o corte é o meio, senão o início/fim do trecho dizem."""
    meio = (t["inicio_q"] + t["fim_q"]) / 2
    alinhamento = "center" if abs(t["corte_q"] - meio) < 1 else ("start" if t["corte_q"] <= t["inicio_q"] else
                                                                  "end" if t["corte_q"] >= t["fim_q"] else "center")
    if audio:
        efeito = ("<effect><name>Cross Fade (+3dB)</name><effectid>KGAudioTransCrossFade3dB</effectid>"
                  "<effecttype>transition</effecttype><mediatype>audio</mediatype></effect>")
    else:
        efeito = ("<effect><name>Cross Dissolve</name><effectid>Cross Dissolve</effectid>"
                  "<effectcategory>Dissolve</effectcategory><effecttype>transition</effecttype>"
                  "<mediatype>video</mediatype></effect>")
    return (f"<transitionitem>{_rate(taxa)}<start>{t['inicio_q']}</start><end>{t['fim_q']}</end>"
            f"<alignment>{alinhamento}</alignment>{efeito}</transitionitem>")


def aparar_nas_transicoes(clipes: list[dict], transicoes: list[dict]) -> tuple[list[dict], list[str]]:
    """No Avid os dois clipes de uma transição se SOBREPÕEM na trilha (o de saída vai até o fim dela, o de entrada
    começa no início dela); no XML cada clipe acaba/começa no PONTO DE CORTE (`corte_q`, o `cutpoint`) e a transição
    usa a sobra de mídia. Devolve (os clipes aparados, avisos). ⛔ Nenhum quadro do corte muda: o ponto de corte é o
    do Avid; só a representação da sobreposição muda."""
    out = [dict(c) for c in clipes]
    avisos = []
    for t in transicoes:
        a = next((c for c in out if int(c["fim_q"]) == int(t["fim_q"]) and int(c["inicio_q"]) < int(t["inicio_q"])),
                 None)
        b = next((c for c in out if int(c["inicio_q"]) == int(t["inicio_q"]) and int(c["fim_q"]) > int(t["fim_q"])),
                 None)
        corte = int(t["corte_q"])
        if a is not None:
            a["fim_q"] = corte
        if b is not None:
            delta = corte - int(b["inicio_q"])
            vel = b.get("velocidade") or {}
            rel = float(vel.get("relativa") or 1.0) if vel.get("classe") not in (None, "conform", "native") else 1.0
            if abs(rel - 1) > 1e-3 and delta % 1:
                avisos.append(f"transição em {t['inicio_q']}: o clipe de entrada tem velocidade; a entrada foi arredondada")
            b["entrada_q"] = int(b["entrada_q"]) + round(delta / rel)
            b["inicio_q"] = corte
        if a is None or b is None:
            avisos.append(f"transição em {t['inicio_q']}–{t['fim_q']} sem clipe {'de saída' if a is None else 'de entrada'}"
                          " encostado (vai como está)")
    return out, avisos


def xml_da_timeline(proj: Projeto, item: dict, forma: str = "avid", nome: str | None = None) -> tuple[str, dict]:
    """(o XML, o relatório) da timeline `item` da Carta. `forma`: a que cada clipe aponta (e as outras, nesta ordem,
    quando a pedida não existe nesta máquina — e o relatório conta)."""
    if not item.get("timeline"):
        raise CartaErro("este item não é uma timeline")
    taxa = Fraction(str(item.get("fps") or "25"))
    base = round(float(taxa))
    refs = {d["id"]: d for _, d in _refs.todas(proj)}
    rel = _Relatorio()
    ordem = ORDEM_DAS_FORMAS.get(forma, ORDEM_DAS_FORMAS["avid"])
    arquivos_por_midia: dict[str, tuple[str, dict[str, str]] | None] = {}
    ids_de_arquivo: dict[str, str] = {}
    escritos: set[str] = set()
    dimensoes = None

    def arquivos(midia: str):
        if midia not in arquivos_por_midia:
            achou = _forma_aqui(proj, midia, ordem)
            if achou is None:
                arquivos_por_midia[midia] = None
            else:
                f, lista = achou
                arquivos_por_midia[midia] = (f, trilhas_do_master(lista) if f == "avid" else
                                             {"V1": lista[0], **{f"A{i}": lista[0] for i in range(1, 33)}})
        return arquivos_por_midia[midia]

    def file_el(caminho: str, ref: dict, audio: bool) -> str:
        if caminho in ids_de_arquivo and caminho in escritos:
            return f'<file id="{ids_de_arquivo[caminho]}"/>'
        fid = ids_de_arquivo.setdefault(caminho, f"file-{len(ids_de_arquivo) + 1}")
        escritos.add(caminho)
        ident = ref.get("identidade") or {}
        dur = int(ident.get("quadros") or round(float(ident.get("duracao_s") or 0) * float(taxa)))
        tc = ""
        if ident.get("tc"):
            tc = (f"<timecode>{_rate(taxa)}<string>{escape(str(ident['tc']))}</string>"
                  f"<displayformat>NDF</displayformat></timecode>")
        midia = ("<media><audio><samplecharacteristics><depth>24</depth><samplerate>48000</samplerate>"
                 "</samplecharacteristics><channelcount>1</channelcount></audio></media>") if audio else (
                 "<media><video><samplecharacteristics>" + _rate(taxa) + "</samplecharacteristics></video></media>")
        return (f'<file id="{fid}"><name>{escape(Path(caminho).name)}</name><pathurl>{escape(_url(caminho))}</pathurl>'
                f"{_rate(taxa)}<duration>{dur}</duration>{tc}{midia}</file>")

    trilhas_xml = {"V": [], "A": []}
    cid = 0
    for tr in item.get("trilhas", []):
        audio = tr["tipo"] == "A"
        pedacos: list[tuple[int, str]] = []
        clipes_da_trilha, av = aparar_nas_transicoes(tr.get("clipes", []), tr.get("transicoes", []))
        rel.avisos.extend(av)
        for c in sorted(clipes_da_trilha, key=lambda x: int(x["inicio_q"])):
            ref = refs.get(c.get("midia") or "")
            nome_m = (ref or {}).get("nome") or c.get("midia") or "?"
            achou = arquivos(c["midia"]) if ref else None
            if achou is None:
                rel.contar(rel.offline, nome_m)
                continue
            f, por_trilha = achou
            rotulo = f"A{int(c.get('canal') or 1)}" if audio else "V1"
            caminho = por_trilha.get(rotulo)
            if caminho is None:
                rel.sem_trilha[nome_m] = rotulo
                continue
            if not audio and dimensoes is None:
                dimensoes = _dimensoes(caminho)
            rel.contar(rel.formas, f)
            entrada = int(c["entrada_q"])
            dur = int(c["fim_q"]) - int(c["inicio_q"])
            filtros = ""
            dur_fonte = dur
            vel = c.get("velocidade")
            if vel:
                classe = str(vel.get("classe") or "")
                relativa = float(vel.get("relativa") or vel.get("razao") or 1.0)
                if classe in ("conform", "native") or abs(relativa - 1) < 1e-3:
                    rel.velocidades.append(f"{tr['tipo']}{tr['k']} {_tc(int(c['inicio_q']) + int(item.get('tc_inicio_q') or 0), base)}"
                                           f" {nome_m}: conformação de taxa ({vel.get('razao')}), levada a 100%")
                elif vel.get("tipo") == "constant":
                    pct = round(100 / relativa, 3)
                    filtros += ("<filter><effect><name>Time Remap</name><effectid>timeremap</effectid>"
                                "<effectcategory>motion</effectcategory><effecttype>motion</effecttype>"
                                "<mediatype>video</mediatype>"
                                "<parameter><parameterid>variablespeed</parameterid><name>variablespeed</name>"
                                "<valuemin>0</valuemin><valuemax>1</valuemax><value>0</value></parameter>"
                                f"<parameter><parameterid>speed</parameterid><name>speed</name><valuemin>-100000</valuemin>"
                                f"<valuemax>100000</valuemax><value>{pct}</value></parameter>"
                                "<parameter><parameterid>reverse</parameterid><name>reverse</name><value>FALSE</value>"
                                "</parameter><parameter><parameterid>frameblending</parameterid><name>frameblending</name>"
                                "<value>FALSE</value></parameter></effect></filter>")
                    rel.velocidades.append(f"{tr['tipo']}{tr['k']} {nome_m}: {pct}% (constante)")
                    dur_fonte = max(1, round(dur / relativa))
                else:
                    rel.velocidades.append(f"{tr['tipo']}{tr['k']} {nome_m}: {vel.get('tipo')} — NÃO levada (clipe a 100%)")
            if audio and c.get("ganho_db") is not None:
                lin = round(10 ** (float(c["ganho_db"]) / 20), 5)
                filtros += ("<filter><effect><name>Audio Levels</name><effectid>audiolevels</effectid>"
                            "<effectcategory>audiolevels</effectcategory><effecttype>audiolevels</effecttype>"
                            "<mediatype>audio</mediatype><parameter><parameterid>level</parameterid><name>Level</name>"
                            f"<valuemin>0</valuemin><valuemax>3.98109</valuemax><value>{lin}</value></parameter>"
                            "</effect></filter>")
            for e in c.get("efeitos") or []:
                if e.get("categoria") != "gain":
                    rel.contar(rel.efeitos_fora, str(e.get("rotulo") or e.get("nome")))
            if c.get("enquadramento"):
                rel.contar(rel.efeitos_fora, f"reformat ({c['enquadramento']})")
            cid += 1
            fonte_trilha = (f"<sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>"
                            if audio else "")
            pedacos.append((int(c["inicio_q"]),
                            f'<clipitem id="clipitem-{cid}"><name>{escape(nome_m)}</name>'
                            f"<enabled>{'FALSE' if c.get('desligado') else 'TRUE'}</enabled>"
                            f"<duration>{int((ref.get('identidade') or {}).get('quadros') or entrada + dur_fonte)}</duration>"
                            f"{_rate(taxa)}<start>{c['inicio_q']}</start><end>{c['fim_q']}</end>"
                            f"<in>{entrada}</in><out>{entrada + dur_fonte}</out>"
                            f"{file_el(caminho, ref, audio)}{fonte_trilha}{filtros}</clipitem>"))
            rel.clipes += 1
        for t in tr.get("transicoes", []):
            ef = str(t.get("efeito") or "")
            if (audio and ef in _DISSOLVE_A) or (not audio and ef in _DISSOLVE_V):
                pedacos.append((int(t["inicio_q"]), _transicao(t, audio, base, taxa)))
                rel.transicoes += 1
            else:
                rel.contar(rel.transicoes_fora, ef or "?")
        for s in tr.get("sem_clipe", []):
            for e in s.get("efeitos") or [{"nome": s.get("nome")}]:
                rel.contar(rel.efeitos_fora, f"{e.get('rotulo') or e.get('nome')} (sem clipe, {tr['tipo']}{tr['k']})")
        pedacos.sort(key=lambda x: x[0])
        trilhas_xml[tr["tipo"]].append("<track>" + "".join(p for _, p in pedacos) + "</track>")
    w, h = dimensoes or (1920, 1080)
    nome = nome or item.get("nome") or "timeline"
    tc0 = int(item.get("tc_inicio_q") or 0)
    xml = ('<?xml version="1.0" encoding="UTF-8"?>\n<!DOCTYPE xmeml>\n<xmeml version="4">'
           f'<sequence id="sequence-1"><name>{escape(nome)}</name><duration>{int(item.get("duracao_q") or 0)}</duration>'
           f"{_rate(taxa)}<timecode>{_rate(taxa)}<string>{_tc(tc0, base)}</string><frame>{tc0}</frame>"
           f"<displayformat>{'DF' if item.get('drop_frame') else 'NDF'}</displayformat></timecode>"
           "<media><video><format><samplecharacteristics>"
           f"{_rate(taxa)}<width>{w}</width><height>{h}</height><pixelaspectratio>square</pixelaspectratio>"
           "</samplecharacteristics></format>" + "".join(trilhas_xml["V"]) + "</video>"
           "<audio><numOutputChannels>2</numOutputChannels>" + "".join(trilhas_xml["A"]) + "</audio>"
           "</media></sequence></xmeml>\n")
    return xml, rel.como_dict()


def gravar(proj: Projeto, item_id: str, forma: str = "avid") -> tuple[Path, dict]:
    """Grava o XML em `<dados desta máquina>/carta/entregas/<nome> <AAAA-MM-DD HHMMSS>.xml` (nunca por cima: um arquivo
    por entrega). Fora do projeto: é o que ESTA máquina entregou, como a miniatura."""
    import datetime
    item = next((d for _, d in _itens.todos(proj) if d["id"] == item_id), None)
    if item is None:
        raise CartaErro("não achei esta timeline no projeto")
    xml, rel = xml_da_timeline(proj, item, forma)
    from ..servico import config
    pasta = config.pasta() / "carta" / "entregas"
    pasta.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.datetime.now().strftime("%Y-%m-%d %H%M%S")
    destino = pasta / f"{_refs._nome_de_arquivo(item['nome'])} {carimbo}.xml"
    destino.write_text(xml, encoding="utf-8")
    return destino, {**rel, "nome": item["nome"]}
