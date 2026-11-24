"""Achar um elemento na foto da tela — o `claude -p` olhando, e uma 2ª pergunta que CONFERE.

MEDIDO (`spikes/o_localizador_ve_a_tela.py`, MC 2024.6, 2026-11-01, Sonnet 5.5):
- imagem no stream-json de ENTRADA, `--tools ""`, `--system-prompt` próprio ⇒ **~2 mil tokens,
  US$ 0,01–0,02, 3–6 s por pergunta** (sem o piso de ~40 mil do prompt padrão do CLI);
- menu File com erro ≤ 3 px; monitor e janela de projeto no lugar.

⛔⛔ **A 2ª pergunta CONFERE, não refina.** No spike, "refinar num recorte" PIOROU um acerto: a
área vazia da timeline foi parar no vão entre dois clipes da V1 (clicar ali move a agulha). O
recorte perde o contexto de onde se está. Aqui o recorte leva uma PRODA no ponto e a pergunta
é sim/não — o que o recorte mostra bem.
⛔⛔ **Dúvida = `NaoAchei`, nunca um palpite.** Alvo ambíguo (abas de bin com nome truncado) deu
dois pontos a 185 px um do outro, e o modelo DISSE que tinha deduzido. Por isso a resposta tem
`certeza`, e só "alta" segue para a conferência.
⛔ O modelo é SEMPRE o Claude (`config.PADRAO`), nunca o do seletor do chat: o local do Mac não
foi medido para isto, e um clique não pode depender de qual modelo o editor deixou escolhido.
"""

from __future__ import annotations

import base64
import json
import subprocess
import time
from dataclasses import dataclass, field

from ..motor.claude import _ambiente_do_cli, achar_o_cli
from ..servico import config as _config
from . import tela as _tela

LARGURA = 1366          # a foto vai reduzida a isto (≈1 MP: abaixo do teto de imagem do modelo)
RECORTE = (480, 270)    # o pedaço NATIVO em volta do ponto, para conferir
#: ⛔ Para um VAZIO (a área da timeline, o fundo do painel de bins): o recorte de 480×270 de uma
#: timeline sem sequência é cinza LISO, e a conferência — com razão — não confirma o que não vê
#: (MEDIDO 2026-11-02: "uma área cinza uniforme… não consigo afirmar que é a timeline"). O
#: amplo mostra as bordas do painel; vai reduzido a `LARGURA_DO_AMPLO`.
RECORTE_AMPLO = (1280, 720)
LARGURA_DO_AMPLO = 960
PRAZO_S = 120

#: ⛔⛔ Recorte MENOR que isto ganha margem em volta (centrada, cortada aos limites da foto).
#: MEDIDO (2026-11-02, Sonnet 5.5, o aviso de teclado do MC): no recorte de 518×190 o "Don't warn
#: me again" saiu 29 px ABAIXO (y 582–583 contra ~554), estável — a conferência recusou 45 vezes e
#: o abrir esperou 304 s. Com 150 px de margem (818×490): exato. O x estava certo nos dois.
MINIMO = (800, 480)


def _com_margem(foto: _tela.Foto, regiao: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    e, t, d, b = regiao
    falta_x, falta_y = max(MINIMO[0] - (d - e), 0), max(MINIMO[1] - (b - t), 0)
    return (e - falta_x // 2, t - falta_y // 2, d + falta_x - falta_x // 2, b + falta_y - falta_y // 2)


SISTEMA = ("Você localiza elementos de interface em capturas de tela de programas de edição de vídeo. "
           "Responda SÓ um objeto JSON, sem texto em volta. Se não tiver certeza, diga — "
           "um clique no lugar errado mexe no trabalho de alguém.")


class NaoAchei(RuntimeError):
    """O localizador não achou, ou não teve certeza. A mensagem diz o que ele viu."""


class JanelaCortada(NaoAchei):
    """A janela onde o alvo deveria estar tem parte FORA dos monitores (faixa sem monitor, ou
    fora da tela). ⭐ Decisão do autor (2026-11-02): não se mexe no layout do editor — para e diz."""


def _exigir_inteira(regiao: tuple[int, int, int, int] | None) -> None:
    if regiao and _tela.parte_fora(regiao) > 0:
        raise JanelaCortada(
            "a janela onde preciso agir está com parte fora da tela (numa faixa sem monitor, ou além da "
            "borda) — não mexo no seu layout: traga a janela inteira para dentro de um monitor e tente de novo")


@dataclass
class Achado:
    x: int                       # coordenada de TELA
    y: int
    o_que_vi: str = ""
    segundos: float = 0.0
    custo_usd: float = 0.0
    respostas: list[dict] = field(default_factory=list)


def _json(texto: str) -> dict:
    t = (texto or "").strip()
    i, j = t.find("{"), t.rfind("}")
    if i < 0 or j < i:
        raise NaoAchei(f"o modelo não respondeu JSON: {t[:200]!r}")
    try:
        return json.loads(t[i:j + 1])
    except ValueError as e:
        raise NaoAchei(f"JSON inválido do modelo: {t[i:j + 1][:200]!r}") from e


def perguntar(jpg: bytes, texto: str, modelo: str = "", sistema: str = "") -> tuple[dict, float, float]:
    """Uma pergunta com uma imagem. Devolve (json, segundos, US$). `sistema`: a instrução de quem pergunta (o agente do piloto)."""
    msg = {"type": "user", "message": {"role": "user", "content": [
        {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg",
                                     "data": base64.b64encode(jpg).decode()}},
        {"type": "text", "text": texto}]}}
    comando = [achar_o_cli(), "-p", "--input-format", "stream-json", "--output-format", "stream-json",
               "--verbose", "--model", modelo or _config.PADRAO, "--system-prompt", sistema or SISTEMA,
               # ⛔ as três do produto (CLAUDE.md, "Ao chamar o claude -p"): sem ferramenta nenhuma
               "--tools", "", "--strict-mcp-config", "--restricted"]
    t = time.monotonic()
    try:
        p = subprocess.run(comando, input=json.dumps(msg) + "\n", capture_output=True, text=True,
                           encoding="utf-8", errors="replace", env=_ambiente_do_cli(), timeout=PRAZO_S,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    except subprocess.TimeoutExpired as e:
        raise NaoAchei(f"o modelo não respondeu em {PRAZO_S} s") from e
    resultado, custo = None, 0.0
    for linha in p.stdout.splitlines():
        try:
            ev = json.loads(linha)
        except ValueError:
            continue
        if ev.get("type") == "result":
            if ev.get("is_error"):
                raise NaoAchei(f"o CLI falhou: {str(ev.get('result'))[:200]}")
            resultado, custo = ev.get("result") or "", float(ev.get("total_cost_usd") or 0)
    if resultado is None:
        fim = (p.stderr or "").strip().splitlines()[-3:]
        raise NaoAchei("o CLI terminou sem resposta: " + " | ".join(fim))
    return _json(resultado), time.monotonic() - t, custo


def _pedido_de_lugar(alvo: str, largura: int, altura: int) -> str:
    return (f"A imagem tem {largura}x{altura} px. Onde está: {alvo}?\n"
            'Responda {"achou": true|false, "x": <px>, "y": <px>, "certeza": "alta"|"baixa", '
            '"o_que_vi": "<curto>"} com o CENTRO do elemento, em pixels desta imagem. '
            'Se houver mais de um candidato, ou se você estiver deduzindo, use "certeza": "baixa".')


def _pedido_de_conferencia(alvo: str) -> str:
    return (f"Há uma PRODA VERMELHA desenhada nesta imagem. O centro da cruz está sobre: {alvo}?\n"
            'Responda {"confere": true|false, "sob_a_cruz": "<o que está exatamente sob o centro da cruz>"}.')


def conferir(foto: _tela.Foto, x: int, y: int, alvo: str, modelo: str = "",
             recorte: tuple[int, int] = RECORTE) -> tuple[bool, dict, float, float]:
    """O ponto de TELA (x, y) está sobre `alvo`? Pergunta num recorte nativo com a cruz."""
    fx, fy = foto.da_foto(x, y)
    h, w = foto.img.shape[:2]
    rw, rh = min(recorte[0], w), min(recorte[1], h)
    e, t = min(max(fx - rw // 2, 0), w - rw), min(max(fy - rh // 2, 0), h - rh)
    amplo = recorte[0] > RECORTE[0]
    pedaco = _tela.com_cruz(foto.img[t:t + rh, e:e + rw], fx - e, fy - t, raio=28 if amplo else 14)
    r, s, c = perguntar(_tela.jpeg(pedaco, LARGURA_DO_AMPLO if amplo else None),
                        _pedido_de_conferencia(alvo), modelo)
    return bool(r.get("confere")), r, s, c


def _pedido_de_varios(alvos: dict[str, str], largura: int, altura: int) -> str:
    lista = "\n".join(f'- "{k}": {v}' for k, v in alvos.items())
    return (f"A imagem tem {largura}x{altura} px. Ache CADA um destes elementos:\n{lista}\n"
            'Responda {"<chave>": {"achou": true|false, "x": <px>, "y": <px>, "certeza": "alta"|"baixa", '
            '"texto": "<o texto que aparece NO elemento, se houver>"}, ...} com o CENTRO de cada um, em '
            'pixels desta imagem. Se houver mais de um candidato, ou se você estiver deduzindo, use '
            '"certeza": "baixa". Elemento que não está visível: "achou": false.')


def localizar_varios(foto: _tela.Foto, alvos: dict[str, str],
                     regiao: tuple[int, int, int, int] | None = None,
                     modelo: str = "") -> tuple[dict[str, Achado | NaoAchei], float, float]:
    """Vários alvos numa foto só: UMA pergunta para achar todos, e as conferências EM PARALELO.

    ⭐ Pedido do autor (2026-11-01): a Select Project levava ~10 s por clique (achar + conferir,
    em fila) — 58 s para criar um projeto. Numa tela com vários alvos visíveis ao mesmo tempo,
    uma pergunta acha todos, e a 2ª pergunta de cada ponto (a que CONFERE, nunca dispensada)
    roda ao mesmo tempo que as outras. Cada achado traz o `texto` que está nele: é o que deixa
    pular o que já está certo (o Format que já mostra o formato pedido).

    Devolve ({chave: Achado ou NaoAchei}, segundos, US$)."""
    from concurrent.futures import ThreadPoolExecutor

    _exigir_inteira(regiao)
    parte = foto.recorte(_com_margem(foto, regiao)) if regiao else foto
    h, w = parte.img.shape[:2]
    escala = w / LARGURA if w > LARGURA else 1.0
    lw, lh = round(w / escala), round(h / escala)
    t = time.monotonic()
    r, _s, custo = perguntar(_tela.jpeg(parte.img, LARGURA if escala > 1 else None),
                             _pedido_de_varios(alvos, lw, lh), modelo)
    saida: dict[str, Achado | NaoAchei] = {}
    pontos: dict[str, tuple[int, int, dict]] = {}
    for chave, alvo in alvos.items():
        a = r.get(chave) if isinstance(r.get(chave), dict) else {}
        if not a.get("achou"):
            saida[chave] = NaoAchei(f"não achei {alvo}")
            continue
        if a.get("certeza") != "alta":
            saida[chave] = NaoAchei(f"não tenho certeza de onde está {alvo}")
            continue
        try:
            px, py = float(a["x"]), float(a["y"])
        except (KeyError, TypeError, ValueError):
            saida[chave] = NaoAchei(f"resposta sem coordenada para {alvo}")
            continue
        if not (0 <= px < lw and 0 <= py < lh):
            saida[chave] = NaoAchei(f"o ponto de {alvo} cai fora da imagem")
            continue
        x, y = parte.da_tela(int(px * escala), int(py * escala))
        pontos[chave] = (x, y, a)
    if pontos:
        with ThreadPoolExecutor(max_workers=len(pontos)) as ex:
            conferencias = {k: ex.submit(conferir, foto, x, y, alvos[k], modelo)
                            for k, (x, y, _a) in pontos.items()}
            for k, fut in conferencias.items():
                x, y, a = pontos[k]
                try:
                    ok, b, _s2, c2 = fut.result()
                except NaoAchei as e:
                    saida[k] = e
                    continue
                custo += c2
                saida[k] = (Achado(x, y, str(a.get("texto") or ""), 0.0, 0.0, [a, b]) if ok else
                            NaoAchei(f"a conferência não confirmou {alvos[k]} — sob o ponto há: "
                                     f"{b.get('sob_a_cruz') or '?'}"))
    return saida, time.monotonic() - t, custo


def conferir_varios(foto: _tela.Foto, pontos: dict[str, tuple[int, int, str]],
                    modelo: str = "") -> tuple[dict[str, Achado | NaoAchei], float, float]:
    """Só a CONFERÊNCIA de pontos já conhecidos ({chave: (x, y, alvo)}), todas em paralelo.

    O `o_que_vi` do achado é o que o modelo descreveu sob a cruz — é o que deixa ler o valor
    de um campo (o Format) sem a pergunta de achar."""
    from concurrent.futures import ThreadPoolExecutor

    t = time.monotonic()
    saida: dict[str, Achado | NaoAchei] = {}
    custo = 0.0
    with ThreadPoolExecutor(max_workers=max(len(pontos), 1)) as ex:
        futuros = {k: ex.submit(conferir, foto, x, y, alvo, modelo) for k, (x, y, alvo) in pontos.items()}
        for k, fut in futuros.items():
            x, y, alvo = pontos[k]
            try:
                ok, b, _s, c = fut.result()
            except NaoAchei as e:
                saida[k] = e
                continue
            custo += c
            saida[k] = (Achado(x, y, str(b.get("sob_a_cruz") or ""), 0.0, 0.0, [b]) if ok else
                        NaoAchei(f"o ponto guardado já não está sobre {alvo}"))
    return saida, time.monotonic() - t, custo


def localizar(foto: _tela.Foto, alvo: str, regiao: tuple[int, int, int, int] | None = None,
              modelo: str = "", recorte: tuple[int, int] = RECORTE) -> Achado:
    """Onde está `alvo` (descrição em português), em coordenada de TELA.

    `regiao` (retângulo de tela: esq, topo, dir, base) limita a foto — a janela do programa,
    para o modelo não achar o alvo em outra janela. Levanta `NaoAchei` com o motivo."""
    _exigir_inteira(regiao)
    parte = foto.recorte(_com_margem(foto, regiao)) if regiao else foto
    h, w = parte.img.shape[:2]
    escala = w / LARGURA if w > LARGURA else 1.0
    lw, lh = round(w / escala), round(h / escala)
    a, s1, c1 = perguntar(_tela.jpeg(parte.img, LARGURA if escala > 1 else None),
                          _pedido_de_lugar(alvo, lw, lh), modelo)
    if not a.get("achou"):
        raise NaoAchei(f"não achei {alvo} — vi: {a.get('o_que_vi') or '?'}")
    if a.get("certeza") != "alta":
        raise NaoAchei(f"não tenho certeza de onde está {alvo} — vi: {a.get('o_que_vi') or '?'}")
    try:
        px, py = float(a["x"]), float(a["y"])
    except (KeyError, TypeError, ValueError) as e:
        raise NaoAchei(f"resposta sem coordenada: {a}") from e
    if not (0 <= px < lw and 0 <= py < lh):
        raise NaoAchei(f"o ponto ({px:g}, {py:g}) cai fora da imagem de {lw}x{lh}")
    x, y = parte.da_tela(int(px * escala), int(py * escala))
    ok, b, s2, c2 = conferir(foto, x, y, alvo, modelo, recorte)
    if not ok:
        raise NaoAchei(f"a conferência não confirmou {alvo} — sob o ponto há: {b.get('sob_a_cruz') or '?'}")
    return Achado(x, y, str(a.get("o_que_vi") or ""), s1 + s2, c1 + c2, [a, b])
