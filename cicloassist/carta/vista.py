"""O que a JANELA da Carta Aberta mostra (C2): a árvore de pastas e o conteúdo delas, já na língua da tela.

Leitura pura: nada aqui grava no projeto (quem grava é `projeto`, `referencias`, `itens`, `anexar` e `diario`).

⭐ A pasta-mãe mostra só o que está DIRETO nela, como a bin do Resolve (autor, 12/11); várias pastas juntas são a
"pasta virtual" — a página pede a lista delas, e cada linha diz de que pasta veio.
⛔ O caminho de OUTRA máquina é traduzido pelo rótulo do volume (`referencias.onde`); o que não existe aqui é dito
(`existe: false`), nunca escondido nem "aberto".
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

from . import diario, itens as _itens, referencias as _refs
from .projeto import PASTA_INTERNA, QUARENTENA, CartaErro, Projeto, maquina

#: o tipo do registro → a palavra da tela (a coluna Tipo; o ícone sai dela). ⭐ A Carta UNIFICA a nomenclatura (autor,
#: 2026-11-13): tudo que recorta ou sincroniza é "subclipe", em três tipos — (A\V) é o sync de um vídeo com um som de
#: outro arquivo (o `.sync` do Avid, o merged do Premiere), (V) o de vídeo (com o som que vier nele), (A) o de som; o
#: group clip do Avid é "multicam". Na ENTREGA cada programa recebe o nome dele.
TIPO = {"video": "vídeo", "audio": "som", "sincronizado": "subclipe (A\\V)", "grupo": "multicam", "sequencia": "nest"}
SUBCLIPE = {"video": "subclipe (V)", "audio": "subclipe (A)"}
NLE = {"avid": "Media Composer", "premiere": "Premiere"}


def _visivel(nome: str) -> bool:
    return not (nome.startswith(".") or nome.startswith("._"))


def pasta_do_projeto(proj: Projeto, rel: str) -> Path:
    """`rel` (com `/`, vindo da página) dentro da raiz — ou `CartaErro`. "" é a raiz."""
    raiz = proj.raiz.resolve()
    alvo = (raiz / rel).resolve() if rel else raiz
    if alvo != raiz and raiz not in alvo.parents:
        raise CartaErro(f"{rel} fica fora do projeto")
    partes = alvo.relative_to(raiz).parts
    if partes and partes[0] in (PASTA_INTERNA, QUARENTENA):
        raise CartaErro(f"{rel} não é uma pasta do editor")
    return alvo


def _rel(proj: Projeto, p: Path) -> str:
    r = p.resolve().relative_to(proj.raiz.resolve()).as_posix()
    return "" if r == "." else r


def arvore(proj: Projeto) -> list[dict]:
    """As pastas do editor em ordem de árvore (a raiz primeiro): `{caminho, nome, nivel, n}`, `n` = referências e
    itens DIRETO na pasta. A `.carta/` e a quarentena não aparecem."""
    out: list[dict] = []

    def descer(pasta: Path, nivel: int) -> None:
        try:
            filhos = sorted(os.scandir(pasta), key=lambda e: e.name.lower())
        except OSError:
            filhos = []
        n = sum(1 for e in filhos if e.is_file() and e.name.endswith((_refs.SUFIXO, _itens.SUFIXO))
                and not e.name.startswith("._"))
        out.append({"caminho": _rel(proj, pasta), "nome": pasta.name if nivel else proj.nome, "nivel": nivel, "n": n})
        for e in filhos:
            if not e.is_dir(follow_symlinks=False) or not _visivel(e.name):
                continue
            if nivel == 0 and e.name in (PASTA_INTERNA, QUARENTENA):
                continue
            descer(Path(e.path), nivel + 1)

    descer(proj.raiz, 0)
    return out


def nova_pasta(proj: Projeto, dentro: str, nome: str) -> str:
    """Cria `nome` dentro de `dentro` (as pastas são do EDITOR: o gesto é dele, o nome é conferido)."""
    nome = (nome or "").strip()
    if not nome or nome in (".", "..") or re.search(r'[<>:"/\\|?*\x00-\x1f]', nome) or nome.startswith("."):
        raise CartaErro("nome de pasta inválido (sem / \\ : * ? \" < > | e sem começar por ponto)")
    pai = pasta_do_projeto(proj, dentro)
    if not pai.is_dir():
        raise CartaErro(f"a pasta {dentro or proj.nome} não existe mais (outro editor pode tê-la mudado)")
    if pai == proj.raiz.resolve() and nome in (PASTA_INTERNA, QUARENTENA):
        raise CartaErro(f"{nome} é um nome reservado da Carta Aberta")
    nova = pai / nome
    if nova.exists():
        raise CartaErro(f"já existe {nome} dentro de {pai.name if dentro else proj.nome}")
    nova.mkdir()
    return _rel(proj, nova)


# ── os caminhos: o desta máquina e o traduzido de outra ──────────────────────

def _letras_por_rotulo() -> dict[str, str]:
    if os.name != "nt":
        return {}
    out = {}
    for letra in "CDEFGHIJKLMNOPQRSTUVWXYZ":
        if os.path.exists(f"{letra}:\\"):
            r = _refs._rotulo_do_volume_windows(letra)
            if r:
                out.setdefault(r, f"{letra}:")
    return out


def traduzir(fato: dict, letras: dict[str, str] | None = None) -> str:
    """O caminho da forma NESTA máquina: o próprio, se foi gravado aqui; senão o volume + relativo."""
    if fato.get("maquina") == maquina() or not (fato.get("volume") and fato.get("relativo")):
        return str(fato.get("arquivo") or "")
    vol, rel = str(fato["volume"]), str(fato["relativo"])
    if sys.platform == "darwin":
        return "/" + rel if vol == "/" else f"/Volumes/{vol}/{rel}"
    if os.name == "nt":
        letra = (letras if letras is not None else _letras_por_rotulo()).get(vol) or (vol if re.fullmatch(r"[A-Z]:", vol) else "")
        return f"{letra}\\{rel.replace('/', chr(92))}" if letra else str(fato.get("arquivo") or "")
    return str(fato.get("arquivo") or "")


# ── o codec: lido do primeiro arquivo que existe, guardado na memória ────────

_CODECS: dict[tuple, str] = {}
_HZ: dict[str, int] = {}          # a amostragem do som (Hz) por arquivo, da mesma sondagem do codec
_NOME_DO_CODEC = {"prores": "ProRes", "dnxhd": "DNxHD/HR", "h264": "H.264", "hevc": "H.265", "mpeg2video": "MPEG-2",
                  "mjpeg": "MJPEG", "braw": "BRAW"}


def codec(arquivo: str, canais: int = 0) -> str:
    """O codec do arquivo, em palavra de editor. `canais`: o total da mídia quando ela é VÁRIOS arquivos (o som
    OP-Atom é um arquivo por canal: o primeiro diria "1 canal")."""
    try:
        st = os.stat(arquivo)
    except OSError:
        return ""
    chave = (arquivo, st.st_size, st.st_mtime_ns)
    chave = (*chave, canais)
    if chave in _CODECS:
        return _CODECS[chave]
    from ..midia.identidade import _exe
    texto = ""
    try:
        r = subprocess.run([_exe("ffprobe"), "-v", "error", "-show_entries",
                            "stream=codec_type,codec_name,profile,sample_rate,channels", "-of", "json", arquivo],
                           capture_output=True, timeout=15)
        import json
        fluxos = (json.loads(r.stdout.decode("utf-8", "replace") or "{}").get("streams") or [])
        v = next((s for s in fluxos if s.get("codec_type") == "video"), None)
        a = [s for s in fluxos if s.get("codec_type") == "audio"]
        if v:
            cru, perfil = str(v.get("codec_name") or ""), str(v.get("profile") or "")
            if cru == "dnxhd":      # o perfil já diz a família: "DNXHR LB", "DNXHD"
                texto = perfil.replace("DNXHR", "DNxHR").replace("DNXHD", "DNxHD") if perfil.upper().startswith("DNX") else "DNxHD"
            else:
                nome = _NOME_DO_CODEC.get(cru, cru.upper())
                texto = f"{nome} {perfil}".strip() if perfil and perfil.lower() not in ("unknown", "main", "high") else nome
        elif a:
            s = a[0]
            canais = canais or sum(int(x.get("channels") or 1) for x in a)
            nome = "PCM" if str(s.get("codec_name", "")).startswith("pcm_") else str(s.get("codec_name") or "").upper()
            khz = f" {int(s['sample_rate']) // 1000} kHz" if s.get("sample_rate") else ""
            if s.get("sample_rate"):
                _HZ[arquivo] = int(s["sample_rate"])
            texto = f"{nome}{khz} · {canais} " + ("canal" if canais == 1 else "canais")
    except (OSError, subprocess.TimeoutExpired, ValueError):
        texto = ""
    _CODECS[chave] = texto
    return texto


def rotulo_hz(arquivo: str) -> str:
    """A taxa do SOM para a coluna FPS (autor, 2026-11-13): "48 kHz"."""
    hz = _HZ.get(arquivo)
    if not hz:
        return ""
    k = hz / 1000
    return (f"{k:g}".replace(".", ",")) + " kHz"


#: o arquivo de SOM de uma OP-Atom (`…_A01.mxf`); o de imagem não tem sufixo de trilha (`…_V01` em alguns casos)
_SOM_OPATOM = re.compile(r"_A\d+\.mxf$", re.I)


def _arquivos_traduzidos(f: dict, principal: str) -> list[str]:
    """Os N arquivos de uma forma OP-Atom, NESTA máquina: os outros vão para onde o principal foi traduzido."""
    lista = [str(a) for a in (f.get("arquivos") or [])]
    if len(lista) < 2:
        return [principal] if principal else []
    orig = str(f.get("arquivo") or "")
    if principal == orig:
        # ⛔ não traduzido (o volume não está nesta máquina): a lista fica COMO VEIO. O `normpath` do Windows reescrevia
        # os outros `/Volumes/…` com `\`, e a mídia ganhava duas "pastas" e abas falsas (medido no Windows, 2026-11-18)
        return lista
    base_o, base_n = os.path.dirname(orig), os.path.dirname(principal)
    out = []
    for a in lista:
        if a == orig or not orig:
            out.append(principal if a == orig else a)
            continue
        try:
            out.append(os.path.normpath(os.path.join(base_n, os.path.relpath(a, base_o))))
        except ValueError:                                 # outra unidade no Windows: fica o de lá
            out.append(a)
    return out


# ── o conteúdo das pastas ─────────────────────────────────────────────────────

def _fps(ident: dict) -> Fraction | None:
    try:
        f = Fraction(str(ident.get("fps") or ""))
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def _canais(ident: dict, fs: list[dict]) -> int:
    """Os canais de som da mídia: a identidade, ou os arquivos da forma OP-Atom (um por canal)."""
    if ident.get("tipo") != "audio":
        return 0
    c = sum(int(x) for x in ident.get("canais_de_som") or [] if isinstance(x, int))
    return max(c, max((len(f.get("arquivos") or []) for f in fs), default=0))


def duracao(segundos: float | None) -> str:
    if not segundos or segundos <= 0:
        return ""
    s = int(round(segundos))
    h, m, s = s // 3600, (s % 3600) // 60, s % 60
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def _quando(ts: str) -> str:
    m = re.match(r"\d{4}-(\d\d)-(\d\d)T(\d\d:\d\d)", ts or "")
    return f"{m.group(2)}/{m.group(1)} {m.group(3)}" if m else ""


def rotulo_da_taxa(f: Fraction | None) -> str:
    """23,976 · 25 · 29,97 (vírgula, como o editor escreve)."""
    if not f:
        return ""
    v = float(f)
    return (f"{v:.3f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))).replace(".", ",")


def _taxa_do_projeto(proj: Projeto) -> Fraction | None:
    try:
        f = Fraction(str(proj.taxa).replace(",", "."))
        return f if f > 0 else None
    except (ValueError, ZeroDivisionError):
        return None


def tc_mais(tc: str, quadros: int, fps: Fraction | None) -> str:
    """O TC `tc` mais N quadros, na taxa `fps` (drop-frame quando o TC vem com `;` a 29,97/59,94)."""
    from ..midia import timecode as _tc
    if not tc or not fps or not _tc.e_timecode(tc):
        return ""
    base = round(float(fps))
    if ";" in tc and base in (30, 60):
        from ..avid import timeline_do_editor as _tl
        try:
            return _tl.tc_df(_tl.frames_do_tc_df(tc, base) + int(quadros), base)
        except Exception:  # noqa: BLE001 — rótulo que não existe em DF: cai na conta non-drop
            pass
    return _tc.de_quadros(_tc.para_quadros(tc, fps) + int(quadros), fps)


def duracao_tc(quadros: int | None, fps: Fraction | None) -> str:
    """A duração em hh:mm:ss:ff (autor, 2026-11-13), contada em quadros (sem drop-frame: é duração, não rótulo)."""
    from ..midia import timecode as _tc
    if not quadros or not fps or quadros <= 0:
        return ""
    base = max(1, round(float(fps)))
    h, r = divmod(int(quadros), base * 3600)
    m, r = divmod(r, base * 60)
    seg, q = divmod(r, base)
    return f"{h:02d}:{m:02d}:{seg:02d}:{q:02d}"


def _relogio(refs: dict, itens_: dict, taxa: Fraction | None):
    """id → (TC de início, duração em quadros, taxa da mídia). ⭐ O item tem o SEU TC (autor, 2026-11-13): o subclipe é
    o TC do clipe + a entrada; o sync, o da imagem + o início dela; a multicam, o da fonte que começa no quadro 0 dela;
    o nest não guarda o TC dele (fica vazio). A taxa do PROJETO conta o som, que não tem quadro próprio."""
    memo: dict[str, tuple] = {}

    def de(i: str) -> tuple:
        if i in memo:
            return memo[i]
        memo[i] = ("", None, None)                       # um ciclo (não deveria existir) não trava a conta
        if i in refs:
            ident = refs[i][1].get("identidade") or {}
            f = _fps(ident)
            fq = f or taxa
            q = ident.get("quadros") or (round(float(ident["duracao_s"]) * float(fq)) if fq and ident.get("duracao_s") else None)
            r = (ident.get("tc", ""), q, f)
        elif i in itens_:
            d = itens_[i][1]
            t = d.get("tipo")
            parte = lambda l: de(l.get("item") or l.get("midia") or "")  # noqa: E731
            if t == "recorte":
                tc0, _, f = parte(d)
                ent, sai = int(d.get("entrada_q") or 0), int(d.get("saida_q") or 0)
                r = (tc_mais(tc0, ent, f or taxa), max(0, sai - ent) or None, f)
            elif t == "sincronizado":
                im = d.get("imagem") or {}
                tc0, q0, f = parte(im)
                ini = int(im.get("inicio_q") or 0)
                dq = d.get("duracao_q") or ((q0 - ini) if q0 else None)
                r = (tc_mais(tc0, ini, f or taxa), dq, f)
            elif t == "grupo":
                fontes = d.get("fontes") or []
                medidas = [(x, parte(x)) for x in fontes]
                if medidas:
                    zero = min(medidas, key=lambda m: int(m[0].get("deslocamento_q") or 0))
                    f = next((m[1][2] for m in medidas if m[0].get("imagem") and m[1][2]), None) or zero[1][2]
                    fim = max((int(x.get("deslocamento_q") or 0) + (m[1] or 0) for x, m in medidas), default=0)
                    r = (tc_mais(zero[1][0], 0, f or taxa), fim or None, f)
                else:
                    r = ("", None, None)
            elif t == "sequencia":
                clipes = [c for tr in d.get("trilhas", []) for c in tr.get("clipes", [])]
                f = next((parte(c)[2] for c in clipes if parte(c)[2]), None)
                fim = max((int(c.get("fim_q") or 0) for c in clipes), default=0)
                r = ("", fim or None, f)
            else:
                r = ("", None, None)
        else:
            r = ("", None, None)
        memo[i] = r
        return r
    return de


def conteudo(proj: Projeto, pastas: list[str], referenciados: bool = False) -> list[dict]:
    """As linhas das pastas pedidas (só o DIRETO de cada uma), na ordem das pastas e, dentro, as mídias e depois os
    itens, por nome. Cada linha: id, nome, tipo, tc, duracao, codec, status, pasta, quem, como, caminhos (+ `partes`
    nos itens).

    ⭐ `referenciados` = o "Mostrar clipes referenciados" (o Show Reference Clips do Avid, autor 2026-11-13): cada item
    da pasta revela o que o compõe, descendo as camadas (a multicam revela os subclipes; os subclipes, as mídias), mesmo
    o que mora em outra pasta ou foi removido da vista. A linha revelada vem com `revelada: true` e `mora_em` (a pasta
    onde mora, ou None se está oculta); é da pasta do item que a revelou enquanto o interruptor estiver ligado."""
    alvos = {}
    for rel in pastas:
        p = pasta_do_projeto(proj, rel)
        alvos[p] = _rel(proj, p)
    formas = diario.formas(proj)
    letras = _letras_por_rotulo()
    refs = {d["id"]: (c, d) for c, d in _refs.todas(proj)}
    linhas: dict[str, list[dict]] = {r: [] for r in alvos.values()}

    def caminhos_da(d: dict) -> list[dict]:
        """Uma linha por FORMA (o OP-Atom é UMA linha: a imagem e os sons são o mesmo material), com `arquivos` = os N
        arquivos dela (o duplo clique marca todos no Finder/Explorer)."""
        out, vistos = [], set()
        for f in formas.get(d["id"], []):
            c = traduzir(f, letras)
            if not c or c in vistos:
                continue
            vistos.add(c)
            arqs = _arquivos_traduzidos(f, c)
            out.append({"arquivo": c, "existe": os.path.exists(c), "arquivos": arqs,
                        "pastas": sorted({os.path.dirname(a) for a in arqs})})
        return out

    def abas_da_midia(caminhos: list[dict]) -> list[dict] | None:
        """⭐ Aba no OP-Atom SÓ quando os arquivos estão em lugares diferentes (autor, 2026-11-13): uma por pasta."""
        opatom = next((c for c in caminhos if len(c["pastas"]) > 1), None)
        if opatom is None:
            return None
        abas = []
        for p in opatom["pastas"]:
            arqs = [a for a in opatom["arquivos"] if os.path.dirname(a) == p]
            abas.append({"titulo": os.path.basename(p) or p, "caminhos": [
                {"arquivo": a, "existe": os.path.exists(a), "arquivos": [a]} for a in arqs]})
        abas[0]["caminhos"] += [c for c in caminhos if c is not opatom]
        return abas

    def linha_da_midia(caminho: Path, d: dict, pasta: str) -> dict:
        ident = d.get("identidade") or {}
        fs = formas.get(d["id"], [])
        caminhos = caminhos_da(d)
        existentes = [c["arquivo"] for c in caminhos if c["existe"]]
        entrada = next((f for f in fs if f.get("por") == "entrou por aqui"), fs[0] if fs else {})
        nle = (d.get("entrou_por") or {}).get("nle", "")
        cod = codec(existentes[0], _canais(ident, fs)) if existentes else ""
        tempos = _tempos(relogio, d["id"], taxa)
        if ident.get("tipo") == "audio" and existentes:
            tempos["fps"] = rotulo_hz(existentes[0])
        # ⭐ OP-Atom: "Itens referenciados" = os arquivos de cada trilha (imagem e sons), não clicáveis
        opatom = next((c for c in caminhos if len(c["arquivos"]) > 1), None)
        refs_lista = [{"nome": os.path.basename(a), "tipo": "audio" if _SOM_OPATOM.search(a) or ident.get("tipo") == "audio"
                       else "video"} for a in opatom["arquivos"]] if opatom else []
        return {
            "id": d["id"], "item": False, "nome": d["nome"], "tipo": TIPO.get(d.get("tipo", ""), d.get("tipo", "")),
            **tempos, "codec": cod,
            "status": "ok" if existentes else "err", "pasta": pasta, "arquivo": caminho.name,
            "quem": " · ".join(x for x in (NLE.get(nle, nle), entrada.get("maquina", ""), _quando(entrada.get("ts", ""))) if x),
            "caminhos": caminhos, "abas": abas_da_midia(caminhos), "referenciados": refs_lista,
        }

    itens_ = {d["id"]: (c, d) for c, d in _itens.todos(proj)}
    taxa = _taxa_do_projeto(proj)
    relogio = _relogio(refs, itens_, taxa)

    for caminho, d in refs.values():
        pasta = alvos.get(caminho.parent.resolve())
        if pasta is not None:
            linhas[pasta].append(linha_da_midia(caminho, d, pasta))


    from . import vitrine as _vitrine

    def mora_em_de(i: str) -> str | None:
        c = (refs.get(i) or itens_.get(i) or (None,))[0]
        if c is None or _vitrine.oculta(proj, c):
            return None
        return _rel(proj, Path(c).parent)

    def nome_de(lugar: dict) -> str:
        if lugar.get("item"):
            return itens_[lugar["item"]][1]["nome"] if lugar["item"] in itens_ else "(item fora do projeto)"
        mid = lugar.get("midia", "")
        return refs[mid][1]["nome"] if mid in refs else "(mídia fora do projeto)"

    def midia_base(lugar: dict, fundo: int = 0) -> dict | None:
        """A referência de mídia por baixo de uma parte (descendo as camadas: o nest, o merged…)."""
        if lugar.get("midia"):
            return refs[lugar["midia"]][1] if lugar["midia"] in refs else None
        d = itens_.get(lugar.get("item", ""), (None, None))[1]
        if d is None or fundo > 8:
            return None
        lugares = _itens._lugares(d)
        return midia_base(lugares[0], fundo + 1) if lugares else None

    def fps_de(lugar: dict) -> Fraction | None:
        m = midia_base(lugar)
        return _fps(m.get("identidade") or {}) if m else None

    for caminho, d in itens_.values():
        pasta = alvos.get(caminho.parent.resolve())
        if pasta is None:
            continue
        l = _linha_do_item(proj, caminho, d, pasta, refs, itens_, nome_de, midia_base, relogio, taxa)
        linhas[pasta].append(_completar_item(l, d, refs, itens_, caminhos_da, mora_em_de))

    if referenciados:
        from . import vitrine as _vit

        def mora_em(c: Path) -> str | None:
            return None if _vit.oculta(proj, c) else _rel(proj, Path(c).parent)

        for pasta, ls in linhas.items():
            ja = {l["id"] for l in ls}
            fila = [i for l in ls if l["item"] for i in l.get("partes", [])]
            while fila:
                i = fila.pop(0)
                if i in ja:
                    continue
                ja.add(i)
                if i in itens_:
                    c, d = itens_[i]
                    l = _completar_item(_linha_do_item(proj, c, d, pasta, refs, itens_, nome_de, midia_base, relogio, taxa),
                                        d, refs, itens_, caminhos_da, mora_em_de)
                    fila.extend(l.get("partes", []))
                elif i in refs:
                    c, d = refs[i]
                    l = linha_da_midia(c, d, pasta)
                else:
                    continue
                ls.append({**l, "revelada": True, "mora_em": mora_em(c)})

    out = []
    for rel in alvos.values():
        out.extend(sorted(linhas[rel], key=lambda x: (x["item"], x["nome"].lower())))
    return out


def _tempos(relogio, i: str, taxa: Fraction | None) -> dict:
    tc, q, f = relogio(i)
    fq = f or taxa
    return {"tc": tc, "duracao": duracao_tc(q, fq), "duracao_s": float(q / fq) if q and fq else 0.0,
            "fps": rotulo_da_taxa(f)}


def _completar_item(l: dict, d: dict, refs: dict, itens_: dict, caminhos_da, mora_em_de) -> dict:
    """O que o DETALHE do item mostra (autor, 2026-11-13): "Itens referenciados" (o 1º nível, vídeo antes do som, em
    ordem alfabética, cada um com onde mora) e "Caminhos conhecidos" por ABA — uma por mídia de baixo. ⛔ O nest (a
    timeline) não ganha abas: perderia o propósito."""
    def tipo_de(k: str, i: str) -> str:
        if k == "midia":
            return "audio" if ((refs.get(i) or (None, {}))[1].get("identidade") or {}).get("tipo") == "audio" else "video"
        base = _midias_de_baixo(i, itens_, set())
        return "video" if any(((refs.get(m) or (None, {}))[1].get("identidade") or {}).get("tipo") != "audio" for m in base) else "audio"
    lista = []
    for k, i in _itens.partes(d):
        nome = ((refs.get(i) or itens_.get(i) or (None, {}))[1]).get("nome", "(fora do projeto)")
        lista.append({"id": i, "nome": nome, "tipo": tipo_de(k, i), "mora_em": mora_em_de(i),
                      "existe": i in refs or i in itens_})
    lista.sort(key=lambda x: (x["tipo"] != "video", x["nome"].lower()))
    l["referenciados"] = lista
    if d.get("tipo") != "sequencia":
        abas = []
        for m in _midias_de_baixo(d["id"], itens_, set()):
            if m in refs:
                abas.append({"titulo": refs[m][1]["nome"], "id": m, "caminhos": caminhos_da(refs[m][1])})
        abas.sort(key=lambda a: (((refs[a["id"]][1].get("identidade") or {}).get("tipo") == "audio"), a["titulo"].lower()))
        l["abas"] = abas
    return l


def _midias_de_baixo(i: str, itens_: dict, vistos: set) -> list[str]:
    """As MÍDIAS por baixo de um item, descendo as camadas, sem repetir."""
    if i in vistos:
        return []
    vistos.add(i)
    if i not in itens_:
        return [i]
    out: list[str] = []
    for k, p in _itens.partes(itens_[i][1]):
        for m in ([p] if k == "midia" else _midias_de_baixo(p, itens_, vistos)):
            if m not in out:
                out.append(m)
    return out


def _linha_do_item(proj, caminho, d, pasta, refs, itens_, nome_de, midia_base, relogio, taxa) -> dict:
    tipo, como = d.get("tipo", ""), ""
    rotulo = TIPO.get(tipo, tipo)
    if tipo == "recorte":
        como = f"recorte {d.get('entrada_q')} a {d.get('saida_q')} de {nome_de(d)}"
        rotulo = SUBCLIPE.get((midia_base(d) or {}).get("tipo", ""), "subclipe")
    elif tipo == "sincronizado":
        im, so = d.get("imagem") or {}, d.get("som") or {}
        como = f"imagem: {nome_de(im)} em {im.get('inicio_q', 0)} · som: {nome_de(so)} em {so.get('inicio_q', 0)}"
    elif tipo == "grupo":
        fontes = d.get("fontes") or []
        ang = d.get("angulo")
        nome_ang = nome_de({"item": ang} if ang in itens_ else {"midia": ang}) if ang else ""
        como = (f"ângulo {nome_ang} · " if ang else "") + " · ".join(f"{nome_de(x)} em {x.get('deslocamento_q', 0)}" for x in fontes)
    elif tipo == "sequencia":
        if d.get("timeline"):          # a timeline do editor (veio como sequência do NLE), não um nest
            rotulo = "timeline"
        clipes = [c for tr in d.get("trilhas", []) for c in tr.get("clipes", [])]
        como = f"{len(d.get('trilhas', []))} trilhas · " + " · ".join(dict.fromkeys(nome_de(c) for c in clipes))
    partes = _itens.partes(d)
    sem = [i for k, i in partes if (k == "midia" and i not in refs) or (k == "item" and i not in itens_)]
    nle = (d.get("entrou_por") or {}).get("nle", "")
    return {"id": d["id"], "item": True, "nome": d["nome"], "tipo": rotulo, **_tempos(relogio, d["id"], taxa),
            "codec": "", "status": "err" if sem else "item", "timeline": bool(d.get("timeline")),
            "pasta": pasta, "arquivo": Path(caminho).name, "quem": NLE.get(nle, nle), "como": como, "caminhos": [],
            "partes": [i for _, i in partes]}


def caminho_conhecido(proj: Projeto, arquivo: str) -> bool:
    """`arquivo` é um caminho que o diário conhece (traduzido para esta máquina; os N arquivos da OP-Atom também)? Só
    esse a página pode mandar revelar no Finder/Explorer (ADR 0005: caminho vindo da página não abre o disco)."""
    letras = _letras_por_rotulo()
    for fs in diario.formas(proj).values():
        for f in fs:
            c = traduzir(f, letras)
            if c == arquivo or arquivo in _arquivos_traduzidos(f, c):
                return True
    return False
