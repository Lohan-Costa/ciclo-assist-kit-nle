"""A timeline do EDITOR na língua do chat: ler em timecode, e editar por operações com prova.

`avid/edicao.py` sabe extrair, inserir e provar — em frames desde o início da sequência, com
objetos do pyavb na mão. Isto é a camada que o modelo alcança:

- **ler** devolve a timeline trilha a trilha em TIMECODE DE RECORD, o que o editor vê na
  tela, com o que está pendurado em cada segmento (efeito, keyframes, group clip, transição);
- **aplicar** recebe operações em timecode e devolve a cópia provada — em memória para
  conferir, ou gravada na bin.

⭐⭐ **Todo timecode das operações é da timeline ORIGINAL**, a que o modelo leu. As operações
são aplicadas da última para a primeira, e assim uma não desloca o ponto da outra: pedir
"extraia 01:02:00:00–01:02:10:00 e abra 2 s em 01:04:00:00" funciona como o editor
leria, sem ninguém descontar os 10 s da extração do segundo ponto. O Avid faria em
sequência; um modelo que lê uma vez e pede três edições erraria a conta das duas últimas.

⛔ Operações que se sobrepõem são recusadas: inserir DENTRO de um trecho que outra operação
extrai não tem leitura única.
"""

from __future__ import annotations

import contextlib
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import avb
from avb.mobid import MobID

from . import edicao as E
from .atributos import copiar_atributos
from . import timeline as T
from .take import RECUSAS, _achar, especie, fracao_da_taxa

#: ⚠️ O que a leitura devolve ao modelo tem teto — a mesma lição do `transcrever`
#: (CLAUDE.md, "O que a ferramenta DEVOLVE é orçamento"). MEDIDO na `TL EDITADA`: a leitura
#: inteira em texto são ~15 mil caracteres; uma timeline de longa passa disso com folga.
ORCAMENTO_CHARS = 16_000

TIPOS = ("extrair", "abrir_espaco", "inserir")


class TimelineErro(Exception):
    """O pedido não dá para cumprir, com a frase que diz por quê."""


# ── timecode ─────────────────────────────────────────────────────────────────

_TC = re.compile(r"^\s*(\d{1,2})[:;.](\d{2})[:;.](\d{2})[:;.](\d{2})\s*$")


def tc(frames: int, fps: int) -> str:
    sinal = "-" if frames < 0 else ""
    frames = abs(frames)
    h, r = divmod(frames, fps * 3600)
    m, r = divmod(r, fps * 60)
    s, q = divmod(r, fps)
    return f"{sinal}{h:02d}:{m:02d}:{s:02d}:{q:02d}"


def frames_do_tc(texto: str, fps: int) -> int:
    m = _TC.match(str(texto or ""))
    if not m:
        raise TimelineErro(f"timecode {texto!r} não está no formato HH:MM:SS:FF")
    h, mi, s, q = (int(x) for x in m.groups())
    if mi >= 60 or s >= 60 or q >= fps:
        raise TimelineErro(f"timecode {texto!r} inválido a {fps} fps")
    return ((h * 60 + mi) * 60 + s) * fps + q


def _quadros_pulados(fps: int) -> int:
    """Quantos rótulos o drop-frame pula por minuto: 2 a 29,97, 4 a 59,94."""
    if fps not in (30, 60):
        raise TimelineErro(f"drop-frame só existe a 29,97 e 59,94; esta taxa conta {fps}")
    return 2 if fps == 30 else 4


def tc_df(frames: int, fps: int) -> str:
    """Frames contínuos → timecode DROP-FRAME (`01;00;00;00`), a conta SMPTE.

    ⚠️ Pronta e testada, e ainda NÃO LIGADA: não se sabe qual `flags` do `Timecode` o Avid
    grava para drop-frame (banco, `entrelacamento-e-locators.json`, "NÃO medida"). O banco
    manda guardar o número cru e AVISAR — uma timeline drop-frame exibida como non-drop
    parece certa e está errada.
    """
    d = _quadros_pulados(fps)
    por_10min = fps * 600 - 9 * d
    por_min = fps * 60 - d
    dezenas, resto = divmod(abs(frames), por_10min)
    ajuste = 9 * d * dezenas + (d * ((resto - d) // por_min) if resto > d else 0)
    rotulo = tc(abs(frames) + ajuste, fps)
    return ("-" if frames < 0 else "") + rotulo.replace(":", ";")


def frames_do_tc_df(texto: str, fps: int) -> int:
    """Timecode DROP-FRAME → frames contínuos. Recusa rótulo que não existe em DF."""
    d = _quadros_pulados(fps)
    m = _TC.match(str(texto or ""))
    if not m:
        raise TimelineErro(f"timecode {texto!r} não está no formato HH;MM;SS;FF")
    h, mi, s, q = (int(x) for x in m.groups())
    if mi >= 60 or s >= 60 or q >= fps:
        raise TimelineErro(f"timecode {texto!r} inválido a {fps} fps")
    if s == 0 and q < d and mi % 10:
        raise TimelineErro(f"{texto!r} não existe em drop-frame: os quadros 00 a {d - 1:02d} "
                           f"do começo de cada minuto (salvo a cada dez) são pulados")
    minutos = h * 60 + mi
    return ((h * 3600 + mi * 60 + s) * fps + q) - d * (minutos - minutos // 10)


def fps_de(seq) -> int:
    return int(round(float(fracao_da_taxa(seq.edit_rate))))


#: ⭐ MEDIDO em 2026-09-13 (`SEQ ANALISE`, MC 2025.6, `spikes/a_referencia_do_editor.py`):
#: a sequência que o editor criou em drop-frame tem `Timecode.flags = 1` e
#: `start = 107892` — a contagem CONTÍNUA de `01;00;00;00`; a non-drop tem `flags = 0` e
#: `start = 108000`. O `start` já é quadro, então só o RÓTULO muda.
FLAG_DROP_FRAME = 1


@dataclass(frozen=True)
class Relogio:
    """Como a sequência conta o tempo: onde começa e se o rótulo é drop-frame."""

    fps: int
    inicio: int
    flags: int

    @property
    def drop(self) -> bool:
        return self.flags == FLAG_DROP_FRAME and self.fps in (30, 60)

    def rotulo(self, frames: int) -> str:
        """Quadros desde o início da SEQUÊNCIA → o timecode que a tela mostra."""
        return (tc_df if self.drop else tc)(self.inicio + frames, self.fps)

    def posicao(self, texto: str) -> int:
        """O timecode que o editor lê na tela → quadros desde o início da sequência."""
        return (frames_do_tc_df if self.drop else frames_do_tc)(texto, self.fps) - self.inicio


def relogio_de(seq) -> Relogio:
    fps = fps_de(seq)
    tcs = [t.component for t in seq.tracks if type(t.component).__name__ == "Timecode"]
    flags = int(getattr(tcs[0], "flags", 0) or 0) if tcs else 0
    return Relogio(fps, inicio_de(seq, fps), flags)


def inicio_de(seq, fps: int) -> int:
    """O timecode de início da sequência, em frames.

    ⛔ MEDIDO na `TL EDITADA`: uma sequência pode ter TRÊS trilhas de timecode (86400@24,
    86400@24, 90000@25). O início é a PRIMEIRA, e o `start` conta na taxa DELA. Pegar a
    última adiantou todo timecode em 2 min 30 s.
    """
    tcs = [t.component for t in seq.tracks if type(t.component).__name__ == "Timecode"]
    return round(tcs[0].start * fps / (tcs[0].fps or fps)) if tcs else 0


# ── achar ────────────────────────────────────────────────────────────────────


def _sequencias_visiveis(f) -> list:
    return [i.mob for i in f.content.items
            if i.user_placed and especie(i.mob) == "sequencia"
            and getattr(i.mob, "mob_type", "") == "CompositionMob"]


def _hex(mob_id) -> str:
    """O MobID nas duas grafias — a do arquivo (`urn:…:060a2b34.0101…`) e a da API
    (`060a2b34…-…`, que o `o_que_esta_na_tela` devolve) — como os mesmos 64 hex."""
    return re.sub(r"[^0-9a-f]", "", str(mob_id).lower().rsplit(":", 1)[-1])


def achar_bin_da_sequencia(bins, sequencia: str) -> Path:
    """Em que bin mora a sequência — para "a timeline que está na Record", que chega com o
    MobID e sem bin nenhuma. Só lê arquivo: medido 42 bins em 0,4 s (`avid/bins.py`)."""
    alvo = _hex(sequencia)
    achadas = []
    for caminho in bins:
        try:
            with avb.open(str(caminho)) as f:
                if any(_hex(s.mob_id) == alvo or (s.name or "").casefold() ==
                       str(sequencia).strip().casefold() for s in _sequencias_visiveis(f)):
                    achadas.append(Path(caminho))
        except Exception:        # noqa: BLE001 — bin ilegível não é a que procuramos
            continue
    if len(achadas) == 1:
        return achadas[0]
    if not achadas:
        raise TimelineErro(f"não achei a sequência {sequencia!r} em nenhuma bin do projeto")
    raise TimelineErro(f"a sequência {sequencia!r} aparece em {len(achadas)} bins "
                       f"({', '.join(b.stem for b in achadas[:10])}); diga qual")


def achar_sequencia(f, sequencia: str):
    """Pelo nome ou pelo MobID. Vazio só serve se a bin tiver uma sequência só."""
    visiveis = _sequencias_visiveis(f)
    alvo = str(sequencia or "").strip()
    if not alvo:
        if len(visiveis) == 1:
            return visiveis[0]
        nomes = ", ".join(repr(s.name) for s in visiveis[:20]) or "nenhuma"
        raise TimelineErro(f"diga qual sequência: a bin tem {len(visiveis)} ({nomes})")
    for s in visiveis:
        if _hex(s.mob_id) == _hex(alvo):
            return s
    iguais = [s for s in visiveis if (s.name or "").casefold() == alvo.casefold()]
    if len(iguais) == 1:
        return iguais[0]
    if iguais:
        # ⚠️ Nome repetido é comum (duplicar a sequência e esquecer de renomear), e escolher
        #    a primeira editaria a versão que o editor talvez não quisesse.
        ids = "; ".join(str(s.mob_id) for s in iguais)
        raise TimelineErro(f"há {len(iguais)} sequências chamadas {alvo!r}; passe o MobID "
                           f"de uma delas: {ids}")
    nomes = ", ".join(repr(s.name) for s in visiveis[:20]) or "nenhuma"
    raise TimelineErro(f"não achei a sequência {alvo!r} na bin. Há: {nomes}")


def rotulo_da_trilha(t) -> str | None:
    """`V1`, `A3` — ou `None` para o que não é trilha de mídia (timecode, edgecode…)."""
    comp = t.component
    letra = {"picture": "V", "sound": "A"}.get(getattr(comp, "media_kind", ""))
    if type(comp).__name__ != "Sequence" or letra is None:
        return None
    return f"{letra}{t.index}"


def _posicao_da_trilha(seq, rotulo: str) -> int:
    for n, t in enumerate(seq.tracks):
        if rotulo_da_trilha(t) == rotulo.strip().upper():
            return n
    existentes = ", ".join(r for r in (rotulo_da_trilha(t) for t in seq.tracks) if r)
    raise TimelineErro(f"a sequência não tem a trilha {rotulo!r} (tem {existentes}). Criar "
                       f"trilha nova ainda não é feito.")


# ── ler ──────────────────────────────────────────────────────────────────────

_ROTULO_DE_EFEITO = {"MotionEffect": "motion effect", "PanVolumeEffect": "volume/pan",
                     "EFF2_BLEND_MATTE_KEY": "matte key"}


def _nome(mob_id, por_id) -> str:
    mob = por_id.get(str(mob_id))
    return (mob.name or "(sem nome)") if mob is not None else "(fora da bin)"


def _descrever(c, por_id) -> tuple[str, list[str]]:
    """(o clipe que se vê, [o que está pendurado nele])."""
    tipo = type(c).__name__
    if tipo == "SourceClip":
        return f"{_nome(c.mob_id, por_id)} (in {c.start_time})", []
    if tipo == "Selector":
        # ⚠️ No pyavb, `Selector.components` é MÉTODO, não lista.
        #    E devolve GERADOR.
        opcoes = list(c.components()) if callable(getattr(c, "components", None)) else []
        sel = getattr(c, "selected", None)
        if isinstance(sel, int) and 0 <= sel < len(opcoes):
            sel = opcoes[sel]
        base = _descrever(sel, por_id)[0] if hasattr(sel, "length") else "?"
        return base, [f"group clip ({len(opcoes)} ângulos)"]
    if hasattr(c, "tracks") and tipo != "Sequence":
        rotulo = (_ROTULO_DE_EFEITO.get(tipo)
                  or _ROTULO_DE_EFEITO.get(str(getattr(c, "effect_id", "") or ""))
                  or f"efeito {getattr(c, 'effect_id', '') or tipo}")
        extras = [rotulo]
        if E._tem_keyframe(c):
            extras.append("keyframes")
        for t in c.tracks or []:
            dentro = t.component
            lista = list(dentro.components) if type(dentro).__name__ == "Sequence" else [dentro]
            for x in lista:
                if type(x).__name__ != "Filler" and x.length:
                    base, mais = _descrever(x, por_id)
                    return base, extras + mais
        return "(efeito sem clipe: título, matte ou gerador)", extras
    return tipo, []


def ler(caminho_da_bin: str | Path, sequencia: str = "", de: str = "", ate: str = "",
        trilhas: list[str] | None = None) -> dict:
    """A timeline em timecode de record. Só lê o ARQUIVO — não fala com o Media Composer."""
    caminho = Path(caminho_da_bin)
    if not caminho.is_file():
        raise TimelineErro(f"não achei a bin {caminho}")
    with avb.open(str(caminho)) as f:
        seq = achar_sequencia(f, sequencia)
        por_id = {str(m.mob_id): m for m in f.content.mobs}
        relogio = relogio_de(seq)
        fps, r = relogio.fps, relogio.rotulo
        janela_a = relogio.posicao(de) if de else 0
        janela_b = relogio.posicao(ate) if ate else seq.length
        so = {r.strip().upper() for r in (trilhas or []) if r.strip()}
        existentes = [r for r in (rotulo_da_trilha(t) for t in seq.tracks) if r]
        if so and not so & set(existentes):
            raise TimelineErro(f"a sequência não tem as trilhas {', '.join(sorted(so))} "
                               f"(tem {', '.join(existentes)})")

        linhas: list[tuple[int, str, str]] = []      # (início, trilha, linha)
        rotulos = []
        for t in seq.tracks:
            rotulo = rotulo_da_trilha(t)
            if rotulo is None or (so and rotulo not in so):
                continue
            rotulos.append(rotulo)
            for s, e, c in E._com_posicao(list(t.component.components)):
                tipo = type(c).__name__
                if tipo == "TransitionEffect":
                    if e <= janela_a or s >= janela_b:
                        continue
                    nome = getattr(c, "effect_id", "") or "transição"
                    linhas.append((s, rotulo, f"{r(s)} → {r(e)} · "
                                              f"transição {nome} ({c.length} frames)"))
                    continue
                if tipo == "Filler" or not c.length or e <= janela_a or s >= janela_b:
                    continue
                base, extras = _descrever(c, por_id)
                linha = f"{r(s)} → {r(e)} · {base}"
                if extras:
                    linha += " · " + " · ".join(extras)
                linhas.append((s, rotulo, linha))

        # ⭐ O corte é no TEMPO, não por trilha: parar no meio da lista cortaria todas as
        #    trilhas de áudio de uma vez, e o modelo acharia que a timeline não tem som.
        linhas.sort(key=lambda x: x[0])
        por_trilha: dict[str, list[str]] = {r: [] for r in rotulos}
        gasto, parou_em = 0, None
        for k, (s, rotulo, linha) in enumerate(linhas):
            gasto += len(linha) + 8
            if gasto > ORCAMENTO_CHARS and k:
                parou_em = s
                break
            por_trilha[rotulo].append(linha)

        resposta = {
            "bin": str(caminho),
            "sequencia": seq.name,
            "mob_id": str(seq.mob_id),
            "fps": fps,
            "inicio": r(0),
            "fim": r(seq.length),
            "drop_frame": relogio.drop,
            "duracao_frames": seq.length,
            "trilhas": por_trilha,
            "confianca": "confirmado",
        }
        if de or ate:
            resposta["janela"] = f"{r(janela_a)} → {r(janela_b)}"
        if relogio.flags not in (0, FLAG_DROP_FRAME):
            # ⚠️ Só 0 (non-drop) e 1 (drop-frame) foram medidos. Outro valor vai CRU, com
            #    aviso — um rótulo errado parece certo e desloca a timeline inteira.
            resposta["timecode_flags"] = relogio.flags
            resposta["atencao"] = (
                f"O timecode desta sequência tem flags={relogio.flags}, que ainda não foi "
                f"medido; contei como non-drop. Confirme um ponto com o editor antes de editar.")
        if parou_em is not None:
            faltam = len(linhas) - sum(len(v) for v in por_trilha.values())
            resposta["aviso"] = (
                f"{faltam} segmentos ficaram de fora por tamanho: a leitura parou em "
                f"{r(parou_em)}. Para o resto, peça de novo com "
                f"de={r(parou_em)!r} — ou só as trilhas que interessam.")
        outras = [s.name for s in _sequencias_visiveis(f) if s is not seq]
        if outras:
            resposta["outras_sequencias_na_bin"] = outras[:20]
        return resposta


# ── operações ────────────────────────────────────────────────────────────────


@dataclass
class Operacao:
    indice: int
    tipo: str
    a: int                      # frames desde o início da sequência
    b: int                      # = a, fora do extrair
    duracao: int = 0
    clipe: str = ""
    in_no_clipe: int = 0
    imagem_em: str = ""
    som_em: tuple = ()
    texto: str = ""
    novos: dict = field(default_factory=dict)      # posição da trilha → SourceClip
    clipe_id: str = ""


def _normalizar(seq, pedidas: list, relogio: Relogio) -> list[Operacao]:
    r = relogio.rotulo
    if not isinstance(pedidas, list) or not pedidas:
        raise TimelineErro("nenhuma operação pedida")
    ops = []
    for i, p in enumerate(pedidas):
        if not isinstance(p, dict):
            raise TimelineErro(f"operação {i + 1} não é um objeto")
        tipo = str(p.get("tipo") or "")
        if tipo not in TIPOS:
            raise TimelineErro(f"operação {i + 1}: tipo {tipo!r}; use um de {', '.join(TIPOS)}")
        rot = f"operação {i + 1} ({tipo})"
        if tipo == "extrair":
            a = relogio.posicao(p.get("de"))
            b = relogio.posicao(p.get("ate"))
            if not 0 <= a < b <= seq.length:
                raise TimelineErro(f"{rot}: {p.get('de')} → {p.get('ate')} não é um trecho "
                                   f"dentro da sequência ({r(0)} → {r(seq.length)})")
            ops.append(Operacao(i, tipo, a, b, texto=(
                f"extrair {r(a)} → {r(b)} ({b - a} frames)")))
            continue
        a = relogio.posicao(p.get("em"))
        duracao = p.get("duracao_frames")
        if not isinstance(duracao, int) or isinstance(duracao, bool) or duracao <= 0:
            raise TimelineErro(f"{rot}: duracao_frames tem de ser um inteiro positivo")
        if not 0 <= a <= seq.length:
            raise TimelineErro(f"{rot}: {p.get('em')} está fora da sequência")
        if tipo == "abrir_espaco":
            ops.append(Operacao(i, tipo, a, a, duracao, texto=(
                f"abrir {duracao} frames de espaço em {r(a)}")))
            continue
        clipe = str(p.get("clipe") or "").strip()
        imagem_em = str(p.get("imagem_em") or "").strip().upper()
        som_em = tuple(str(x).strip().upper() for x in (p.get("som_em") or []) if str(x).strip())
        in_no_clipe = p.get("in_no_clipe", 0)
        if not clipe:
            raise TimelineErro(f"{rot}: diga o clipe")
        if not imagem_em and not som_em:
            raise TimelineErro(f"{rot}: diga em que trilha entra a imagem (imagem_em) e/ou o "
                               f"som (som_em)")
        if not isinstance(in_no_clipe, int) or isinstance(in_no_clipe, bool) or in_no_clipe < 0:
            raise TimelineErro(f"{rot}: in_no_clipe tem de ser um inteiro ≥ 0")
        onde = " + ".join(x for x in [imagem_em, "/".join(som_em)] if x)
        ops.append(Operacao(i, tipo, a, a, duracao, clipe, in_no_clipe, imagem_em, som_em,
                            texto=(f"inserir {duracao} frames de {clipe} (in {in_no_clipe}) "
                                   f"em {r(a)}, em {onde}")))

    # ⛔ Sobreposição: sem leitura única, então recusa.
    for x in ops:
        for y in ops:
            if x is y:
                continue
            if x.tipo == "extrair" and y.tipo == "extrair" and x.indice < y.indice \
                    and x.a < y.b and y.a < x.b:
                raise TimelineErro(f"as operações {x.indice + 1} e {y.indice + 1} extraem "
                                   f"trechos que se sobrepõem")
            if x.tipo == "extrair" and y.tipo != "extrair" and x.a < y.a < x.b:
                raise TimelineErro(f"a operação {y.indice + 1} cai DENTRO do trecho que a "
                                   f"operação {x.indice + 1} extrai")
    return ops


def _clipes_da_insercao(f, seq, op: Operacao, origem) -> None:
    """Resolve o clipe e monta os `SourceClip` de cada trilha em `op.novos`."""
    rot = f"operação {op.indice + 1} (inserir)"
    # ⚠️ Mídia primeiro: um subclipe com o mesmo nome de uma sequência seria recusado como
    #    "é uma sequência" se a sequência aparecesse antes na bin.
    mobs = sorted(origem.content.mobs,
                  key=lambda m: especie(m) not in ("subclipe", "master"))
    clipe = _achar(mobs, op.clipe)
    if clipe is None:
        raise TimelineErro(f"{rot}: não achei o clipe {op.clipe!r} na bin. Se ele está em "
                           f"outra bin, passe bin_do_clipe.")
    e_de_que = especie(clipe)
    if e_de_que not in ("subclipe", "master"):
        raise TimelineErro(f"{rot}: {clipe.name!r} " + RECUSAS.get(
            e_de_que, f"é um item do tipo {e_de_que!r}, que não é mídia aceita."))
    if fracao_da_taxa(clipe.edit_rate) != fracao_da_taxa(seq.edit_rate):
        raise TimelineErro(f"{rot}: {clipe.name!r} tem taxa {float(clipe.edit_rate):.3f} e a "
                           f"sequência {float(seq.edit_rate):.3f}. Misturar taxas ainda não "
                           f"é feito.")
    if op.in_no_clipe + op.duracao > clipe.length:
        raise TimelineErro(f"{rot}: {clipe.name!r} tem {clipe.length} frames; in "
                           f"{op.in_no_clipe} + {op.duracao} passa do fim")
    indices = {"picture": [], "sound": []}
    for t in clipe.tracks:
        kind = getattr(t.component, "media_kind", "")
        if kind in indices:
            indices[kind].append(t.index)
    pedidos = ([("picture", op.imagem_em)] if op.imagem_em else []) + \
        [("sound", r) for r in op.som_em]
    for kind, rotulo in pedidos:
        esperado = "V" if kind == "picture" else "A"
        if not rotulo.startswith(esperado):
            raise TimelineErro(f"{rot}: {rotulo} não é trilha de "
                               f"{'imagem' if kind == 'picture' else 'som'}")
    if op.imagem_em and not indices["picture"]:
        raise TimelineErro(f"{rot}: {clipe.name!r} não tem imagem")
    if len(op.som_em) > len(indices["sound"]):
        raise TimelineErro(f"{rot}: {clipe.name!r} tem {len(indices['sound'])} canais de "
                           f"som, e o pedido põe som em {len(op.som_em)} trilhas")
    fontes = ([("picture", op.imagem_em, sorted(indices["picture"])[0])] if op.imagem_em
              else []) + [("sound", r, i) for r, i in zip(op.som_em, sorted(indices["sound"]))]
    for kind, rotulo, track_id in fontes:
        n = _posicao_da_trilha(seq, rotulo)
        if n in op.novos:
            raise TimelineErro(f"{rot}: a trilha {rotulo} foi pedida duas vezes")
        sc = f.create.SourceClip(seq.edit_rate, kind)
        sc.mob_id = MobID(str(clipe.mob_id))
        sc.track_id = track_id
        sc.start_time = op.in_no_clipe
        sc.length = op.duracao
        op.novos[n] = sc
    op.clipe_id = str(clipe.mob_id)


def _nome_livre(f, desejado: str) -> str:
    usados = {(s.name or "").casefold() for s in _sequencias_visiveis(f)}
    if desejado.casefold() not in usados:
        return desejado
    n = 2
    while f"{desejado} {n}".casefold() in usados:
        n += 1
    return f"{desejado} {n}"


def aplicar(caminho_da_bin: str | Path, sequencia: str, operacoes: list, nome: str = "",
            gravar: bool = False, bin_do_clipe: str | Path | None = None) -> dict:
    """Aplica as operações numa CÓPIA da sequência e prova que só elas mudaram.

    Sem `gravar`, nada toca o disco: é a conferência. Com `gravar`, a bin é regravada ao
    lado e trocada com `os.replace` — ⛔ quem chama garante que ela está FECHADA no Media
    Composer (`CloseBin`) e guarda a cópia de segurança. Levanta `TimelineErro` com a frase
    do porquê; `EdicaoRecusada` vira `TimelineErro` com a operação apontada.
    """
    caminho = Path(caminho_da_bin)
    if not caminho.is_file():
        raise TimelineErro(f"não achei a bin {caminho}")
    outra = Path(bin_do_clipe) if bin_do_clipe else None
    if outra is not None and not outra.is_file():
        raise TimelineErro(f"não achei a bin do clipe {outra}")
    if outra is not None and outra.resolve() == caminho.resolve():
        outra = None
    lado = caminho.with_suffix(caminho.suffix + ".novo")

    with contextlib.ExitStack() as pilha:
        f = pilha.enter_context(avb.open(str(caminho)))
        origem = pilha.enter_context(avb.open(str(outra))) if outra else f
        seq = achar_sequencia(f, sequencia)
        relogio = relogio_de(seq)
        fps = relogio.fps
        ops = _normalizar(seq, operacoes, relogio)
        nome_final = _nome_livre(f, str(nome or "").strip() or f"{seq.name} - editada")

        memo: dict = {}
        antes = {str(m.mob_id): E.impressao(m, memo) for m in f.content.mobs}

        # ⭐ Da última posição para a primeira: a posição de uma operação não é deslocada
        #    pelas que ainda faltam. No empate, o extrair antes do inserir — senão o
        #    extrair levaria embora o que acabou de entrar.
        ordem = sorted(ops, key=lambda o: (-o.a, 0 if o.tipo == "extrair" else 1, -o.indice))
        atual, intermediarias, mudancas = seq, [], []
        for k, op in enumerate(ordem):
            rot = f"operação {op.indice + 1} ({op.texto})"
            if op.tipo == "inserir":
                _clipes_da_insercao(f, seq, op, origem)
            copia = E.copiar_sequencia(f, atual, nome_final)
            try:
                if op.tipo == "extrair":
                    feito = E.extrair(copia, op.a, op.b)
                    trechos = ((op.a, op.b), (op.a, op.a))
                else:
                    feito = E.inserir(copia, op.a, op.duracao, op.novos)
                    trechos = ((op.a, op.a), (op.a, op.a + op.duracao))
            except E.EdicaoRecusada as e:
                raise TimelineErro(f"{rot}: {e}") from None
            problemas = E.conferir_fidelidade(atual, copia, *trechos)
            if problemas:
                raise TimelineErro(f"{rot}: a prova reprovou a cópia — " + "; ".join(problemas[:5]))
            # O `edicao` numera a trilha pela POSIÇÃO na lista; o editor lê V2, A3.
            # ⚠️ E o que acontece com VAZIO fica de fora: MEDIDO na `TL EDITADA`, uma extração
            #    listava 16 "aparado Filler" e 5 linhas que importavam.
            for x in feito["mudancas"]:
                if re.search(r"Filler|\+\d+ de vazio$|colados dois vazios", x):
                    continue
                x = re.sub(r"^trilha (\d+):", lambda m: (
                    rotulo_da_trilha(seq.tracks[int(m.group(1))]) or "trilha") + ":", x)
                x = x.replace("SourceClip", "clipe").replace("PanVolumeEffect", "clipe com "
                                                                             "volume/pan")
                mudancas.append(f"{op.texto}: {x}")
            if atual is not seq:
                intermediarias.append(atual)
            atual = copia
        nova = atual
        # A régua de cada passo não fica na bin: só o resultado.
        for mob in intermediarias:
            f.content.items.remove(next(i for i in f.content.items if i.mob is mob))

        memo = {}
        mexidos = [m.name for m in f.content.mobs
                   if str(m.mob_id) in antes and E.impressao(m, memo) != antes[str(m.mob_id)]]
        if mexidos:
            raise TimelineErro(f"a prova reprovou: mudaria {', '.join(map(repr, mexidos[:5]))} "
                               f"na bin, e só a cópia podia mudar")

        # A mesma linha em cinco trilhas de som vira uma linha com a conta.
        contagem = dict.fromkeys(mudancas, 0)
        for x in mudancas:
            contagem[x] += 1
        mudancas = [x if n == 1 else f"{x} (em {n} trilhas)" for x, n in contagem.items()]

        resposta = {
            "sequencia_original": seq.name,
            "sequencia_nova": nome_final,
            "operacoes": [o.texto for o in ops],
            "duracao_antes": f"{tc(seq.length, fps)} ({seq.length} frames)",
            "duracao_depois": f"{tc(nova.length, fps)} ({nova.length} frames)",
            "mudancas": mudancas[:40],
        }
        if len(mudancas) > 40:
            resposta["mudancas_omitidas"] = len(mudancas) - 40
        if not gravar:
            return resposta

        # ⛔⛔ O clipe de OUTRA bin leva o fecho, oculto: subclipe fora da bin derruba o
        #    Media Composer ao carregar (banco, 2026-08-30).
        fecho_ids: set[str] = set()
        if outra is not None:
            indice = {str(m.mob_id): m for m in origem.content.mobs}
            ids = [o.clipe_id for o in ops if o.tipo == "inserir"]
            for mid, mob in T.fecho(indice, ids).items():
                if mid not in antes:
                    f.content.add_mob(mob.copy(f)).user_placed = False
                    fecho_ids.add(mid)
        id_novo = str(nova.mob_id)
        provado = E.impressao(nova, {})
        try:
            f.write(str(lado))
        except Exception:
            lado.unlink(missing_ok=True)
            raise
    # ⚠️ Fora do `with`: o pyavb lê preguiçoso, e o handle tem de fechar antes da troca.
    # ⚠️ E os atributos da bin do Mac vão junto, senão a troca os apaga (`atributos`).
    copiar_atributos(caminho, lado)
    os.replace(lado, caminho)

    # ⭐ Relido do DISCO: a prova vale para o arquivo gravado, não para a memória.
    with avb.open(str(caminho)) as f:
        depois = {str(m.mob_id): m for m in f.content.mobs}
        memo = {}
        falhas = [f"{m.name!r} mudou no disco" for mid, m in depois.items()
                  if mid in antes and E.impressao(m, memo) != antes[mid]]
        if id_novo not in depois or E.impressao(depois[id_novo], {}) != provado:
            falhas.append("a cópia relida do disco não é a que foi provada em memória")
        sobrando = set(depois) - set(antes) - {id_novo} - fecho_ids
        if sobrando:
            falhas.append(f"{len(sobrando)} mob(s) a mais do que o pedido")
    if falhas:
        raise TimelineErro("a bin gravada não passou na prova: " + "; ".join(falhas[:5]))
    return {**resposta, "mob_id_novo": id_novo, "mobs_de_fecho": len(fecho_ids)}
