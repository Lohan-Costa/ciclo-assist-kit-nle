"""O título de um `TrackEffect` da bin do Avid → o bloco `titulo` da Carta Aberta (modelo neutro).

Medido em 2026-09-27 (banco `avb/dados/titler-plus-mqp.json` e `titler-texto.json`, §leitura_na_bin):

- todo titulador se declara em `attributes['_EFFECT_PLUGIN_CLASS'] == 'Title'`;
- **Titler+ atual** (`E4EEBB07…`): o estilo inteiro no MQP Blob (`mqp.py`);
- **Titler+ Legacy** (`8BA34E51…`, o da PRODA_CORTE): o texto num `CFUserParam` com a string
  pura; o estilo mora num XML "deko" ainda não mapeado. Decisão do autor: o Legacy entra com o
  texto e o estilo padrão, com um aviso, e o XML vai inteiro na Carta para a etapa seguinte.

O modelo neutro mede como o Avid (a Carta não traduz; quem escreve o NLE de destino converte):
- `corpo`: fração da ALTURA do quadro;
- `posicao`: o centro da caixa em ALTURAS de quadro a partir do centro, com Y para cima;
- cores RGB de 0 a 1.
"""

from __future__ import annotations

from . import mqp

EID_TITLER = "E4EEBB07-AFAA-4122-BFA8-0A838BB40A8C"
EID_LEGACY = "8BA34E51-D647-443E-BFB5-30DFCECE5415"
UUID_MQP = "67a614ac-29b6-4afe-b9cc-8107a5dd3468"

#: Faces que o Avid junta ao nome da família ("{Open Sans Bold}"). No Resolve a face é o
#: ESTILO, separado da família — e não um botão de negrito (observação do autor, 2026-09-27).
_FACES = ("Bold Italic", "Semibold Italic", "Light Italic", "Black Italic", "Medium Italic",
          "Extrabold", "ExtraBold", "Semibold", "SemiBold", "Bold", "Italic", "Light", "Medium",
          "Black", "Regular", "Thin", "Oblique")


def _attrs(te) -> dict:
    try:
        return dict(te.property_data.get("attributes") or {})
    except Exception:  # noqa: BLE001 — atributo ilegível não é título
        return {}


def e_titulo(te) -> bool:
    eid = str(getattr(te, "effect_id", "") or "").upper()
    if eid in (EID_TITLER, EID_LEGACY):
        return True
    return _attrs(te).get("_EFFECT_PLUGIN_CLASS") == "Title"


def _blobs(te) -> list[tuple[str, bytes]]:
    """(uuid, bytes) de cada `CFUserParam` da lista de parâmetros."""
    fora = []
    for p in te.property_data.get("param_list") or []:
        pd = getattr(p, "property_data", {}) or {}
        v = pd.get("value")
        if type(v).__name__ == "CFUserParam":
            try:
                fora.append((str(pd.get("uuid") or ""), bytes(v.property_data["data"])))
            except Exception:  # noqa: BLE001
                continue
    return fora


def fonte(nome: str) -> dict:
    """'{Open Sans Bold}' → {'familia': 'Open Sans', 'estilo': 'Bold'}; sem face, estilo vazio."""
    nome = (nome or "").strip().strip("{}").strip()
    for face in _FACES:
        if nome.lower().endswith(" " + face.lower()):
            return {"familia": nome[: -len(face)].strip(), "estilo": face}
    return {"familia": nome, "estilo": ""}


def _num(v, padrao: float = 0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return padrao


def _sim(v) -> bool:
    return str(v).strip().lower() in ("true", "1")


def _cor(m: mqp.Mqp, lista: int, prefixo: str) -> list:
    return [round(min(1.0, max(0.0, _num(m.valor(lista, f"{prefixo}.{c}")))), 4)
            for c in ("Red", "Green", "Blue")]


_ALINHA = {"Left": "esquerda", "Center": "centro", "Right": "direita"}


def _caixa(m: mqp.Mqp, cx: dict) -> dict:
    letra = next((c["lista"] for c in cx["caracteres"] if c.get("lista")), 0)
    caixa = {
        "texto": mqp.texto_da_caixa(cx),
        "fonte": fonte(m.valor(letra, "Text.Font.Name") or ""),
        "corpo": round(_num(m.valor(letra, "Text.Font.Size"), 0.0833333), 6),
        "cor": _cor(m, letra, "Material.Main.Base"),
        "alinhamento": _ALINHA.get(cx.get("justify") or "Left", "esquerda"),
        "posicao": {"x": round(_num(m.valor(cx["lista"], "Transform.Position.X")), 6),
                    "y": round(_num(m.valor(cx["lista"], "Transform.Position.Y")), 6)},
        "contorno": None,
        "sombra": None,
    }
    if _sim(m.valor(letra, "Material.Profile.Outline.Enable")):
        caixa["contorno"] = {"cor": _cor(m, letra, "Material.Profile.Outline.Solid"),
                             "espessura": _num(m.valor(letra, "Effect.ProfileScale"), 1.0)}
    if _sim(m.valor(letra, "Shadow.Enable")):
        caixa["sombra"] = {"cor": _cor(m, letra, "Shadow.Color"),
                           "deslocamento": [_num(m.valor(letra, "Shadow.Offset.X")),
                                            _num(m.valor(letra, "Shadow.Offset.Y"))],
                           "suavidade": _num(m.valor(letra, "Shadow.Softness"))}
    return caixa


def ler(te) -> dict | None:
    """O bloco `titulo` do efeito, ou `None` se não é título."""
    if not e_titulo(te):
        return None
    eid = str(getattr(te, "effect_id", "") or "").upper()
    attrs = _attrs(te)
    blobs = _blobs(te)
    mqp_txt = next((b.decode("utf-8", "replace") for u, b in blobs if u.lower() == UUID_MQP), None)

    if mqp_txt:
        return bloco(eid, "", [], mqp_txt)

    # Legacy: o texto é a string pura de um CFUserParam; o estilo, um XML "deko" + um JSON.
    textos, deko, estilo_json = [], None, None
    for _u, b in blobs:
        if _u.lower() == UUID_JSON_LEGACY:
            estilo_json = _json_utf32(b)
            continue
        if b.startswith(b"<deko>"):
            deko = b.decode("utf-8", "replace")
        elif b.endswith(b"\x00") and 1 < len(b) < 4096 and b"\x00" not in b[:-1]:
            try:
                textos.append(b[:-1].decode("utf-8"))
            except UnicodeDecodeError:
                continue
    if not textos:
        tt = attrs.get("_TTEXT")
        if tt:
            textos = [bytes(tt).split(b"T+: ", 1)[-1].strip(b" \x00").decode("utf-8", "replace")]
    t = bloco(eid, attrs.get("_EFFECT_PLUGIN_NAME") or "", textos, deko=deko)
    if estilo_json:
        estilo_legacy(t, estilo_json, _escalares(te), deko)
    return t


# ── o ESTILO do Titler+ LEGACY (2026-11-20) ─────────────────────────────────────
#
# Medido na PRODA_CORTE.00.2 (bin `03_OC_EDIT VALENDO.avb`) contra o export do Avid (`PRODA_CORTE.02.mov`, quadro em 35 s):
# o estilo LEGÍVEL está num CFUserParam com um JSON em UTF-32 LE (`FontName`, `FontSize`, `FaceColor`, `Edge*`,
# `Shadow*`, `Background*`…). O XML "deko" (315 KB) traz as cores por letra mas NÃO a fonte (`FSTRING` vazio), e a
# cor da face dele (EBEBEB) não é a do título — o export mostra 255, a do JSON.
# ⭐ O corpo: as maiúsculas retas medem 73 px = Arial de 102 px de corpo = `FontSize` 120 × 0,85, e 0,85 é o valor de
# dois parâmetros numéricos SEM nome (os uuids abaixo, ao que tudo indica a escala X/Y da camada). `hipotese` forte
# (uma amostra só, mas a conta fecha em 0,1 px).

UUID_JSON_LEGACY = "c6219ca9-820a-4468-8545-285fc46d5236"
UUID_ESCALA_LEGACY = ("19443b8e-3fb9-4fa3-8775-12cf342b51fb", "732f3ce2-8cff-41fe-ae5a-0ec86338a933")
#: a LINHA DE BASE do texto, em fração da altura a partir do TOPO (o par valor/assinatura de um param sem nome):
#: 0,52776 × 1080 = 570,0 = o pé das maiúsculas no export do Avid (medido 570). `hipotese` (uma amostra)
UUID_BASE_LEGACY = ("b16d164d-fc1d-46eb-9b5b-c51b237c7a91", "7022f0f7-69e0-4f65-9e71-808f3ffbb3a0")
#: `FEjust_x` do deko → alinhamento (`hipotese`: só o 1 = centro foi visto, na PRODA)
_JUST_LEGACY = {"0": "esquerda", "1": "centro", "2": "direita"}


def _json_utf32(b: bytes) -> dict | None:
    import json
    for enc in ("utf-32-le", "utf-8"):
        try:
            d = json.loads(b.decode(enc).rstrip("\x00").strip())
            return d if isinstance(d, dict) else None
        except (UnicodeDecodeError, ValueError):
            continue
    return None


def _escalares(te) -> dict[str, float]:
    """{uuid: valor} dos parâmetros numéricos do efeito (os do Legacy não têm nome na bin)."""
    fora = {}
    for p in te.property_data.get("param_list") or []:
        pd = getattr(p, "property_data", {}) or {}
        v = pd.get("value")
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            fora[str(pd.get("uuid") or "").lower()] = float(v)
    return fora


def _hex_rgb(h) -> list | None:
    h = str(h or "").lstrip("#")
    if len(h) == 8:                        # #AARRGGBB
        h = h[2:]
    try:
        return [round(int(h[i:i + 2], 16) / 255, 4) for i in (0, 2, 4)]
    except ValueError:
        return None


def estilo_legacy(titulo: dict, js: dict, escalares: dict, deko: str | None = None) -> dict:
    """Põe no bloco `titulo` (o do Legacy, sem estilo) o estilo do JSON — em TODAS as caixas (o Legacy tem um estilo
    só por título)."""
    import math
    import re as _re
    vt = 1080.0
    m = _re.search(r'attribut="vt_res" value="(\d+)"', deko or "")
    if m:
        vt = float(m.group(1))
    esc = [escalares[u] for u in UUID_ESCALA_LEGACY if u in escalares]
    escala = sum(esc) / len(esc) if esc else 1.0
    just = None
    m = _re.search(r'attribut="FEjust_x" value="(\d+)"', deko or "")
    if m:
        just = _JUST_LEGACY.get(m.group(1))
    face = ("Bold Italic" if js.get("FontBold") and js.get("FontItalic") else
            "Bold" if js.get("FontBold") else "Italic" if js.get("FontItalic") else "")
    for cx in titulo.get("caixas") or []:
        cx["fonte"] = {"familia": str(js.get("FontName") or ""), "estilo": face}
        if js.get("FontSize"):
            cx["corpo"] = round(float(js["FontSize"]) * escala / vt, 6)
        if js.get("FaceVisible", True):
            cx["cor"] = _hex_rgb(js.get("FaceColor"))
        if just:
            cx["alinhamento"] = just
        base = next((escalares[u] for u in UUID_BASE_LEGACY if u in escalares), None)
        if base is not None:
            cx["linha_de_base_y"] = round(base, 6)       # quem não sabe usar (o Resolve) ignora e centraliza
        if js.get("EdgeVisible"):
            cx["contorno"] = {"cor": _hex_rgb(js.get("EdgeColor")) or [0, 0, 0],
                              "espessura": float(js.get("EdgeSize") or 1.0)}
        if js.get("ShadowVisible"):
            # o ângulo é de onde vem a LUZ (convenção Adobe/Avid: 135° = luz de cima-esquerda, sombra para baixo-direita)
            d = float(js.get("ShadowDistance") or 0) / vt
            a = math.radians(float(js.get("ShadowAngle") or 135) + 180)
            cx["sombra"] = {"cor": _hex_rgb(js.get("ShadowColor")) or [0, 0, 0],
                            "deslocamento": [round(d * math.cos(a), 6), round(d * math.sin(a), 6)],
                            "suavidade": float(js.get("ShadowSoftness") or 0),
                            "opacidade": float(js.get("ShadowOpacity") or 100) / 100}
    if js.get("BackgroundVisible"):
        titulo["fundo"] = {"cor": _hex_rgb(js.get("BackgroundColor")) or [0, 0, 0],
                           "opacidade": float(js.get("BackgroundOpacity") or 100) / 100, "tela_cheia": None}
    titulo["estilo_lido"] = True
    titulo["avid"]["estilo_json"] = js
    titulo["avid"]["escala"] = escala
    return titulo


def bloco(eid: str, nome: str, textos: list[str], mqp_txt: str | None = None,
          deko: str | None = None, titulador: str | None = None) -> dict:
    """O bloco `titulo` a partir do que se leu — da BIN (`ler`) ou do AAF (`do_aaf`), pela mesma
    regra: com o MQP, o estilo inteiro; sem ele (Legacy), o texto com o estilo padrão."""
    if mqp_txt:
        m = mqp.ler(mqp_txt)
        caixas = [_caixa(m, cx) for cx in m.caixas if cx["caracteres"]]
        if not caixas and any((t or "").strip() for t in textos):
            # o MQP não rendeu caixas, mas o texto foi lido: ele entra com o estilo padrão em vez de o título
            # sumir (revisão de código 2026-10-01)
            return bloco(eid, nome, textos, None, deko, titulador)
        fundo = None
        if _sim(m.valor(m.lista_cena, "Global.BG.Enable")):
            fundo = {"cor": _cor(m, m.lista_cena, "Global.BG.Color"),
                     "opacidade": _num(m.valor(m.lista_cena, "Global.BG.Color.Opacity"), 1.0),
                     "tela_cheia": True}
        return {"titulador": "Avid Titler+", "estilo_lido": True, "caixas": caixas,
                "fundo": fundo, "avid": {"effect_id": eid, "mqp": mqp_txt}}
    # A PRODA tem DUAS caixas com o mesmo texto (banco `titler-texto.json`): uma só basta.
    vistos: list[str] = []
    for t in textos:
        if t not in vistos:
            vistos.append(t)
    caixas = [{"texto": t, "fonte": {"familia": "", "estilo": ""}, "corpo": None, "cor": None,
               "alinhamento": "centro", "posicao": None, "contorno": None, "sombra": None}
              for t in vistos]
    return {"titulador": titulador or (f"{nome} Legacy" if eid == EID_LEGACY else (nome or "título do Avid")),
            "estilo_lido": False, "caixas": caixas, "fundo": None,
            "avid": {"effect_id": eid, "deko": deko}}


def do_aaf(operacao: str, textos: list[str], mqp_txt: str | None = None) -> dict | None:
    """O bloco `titulo` de um título lido do AAF (`aaf/parser.py::_extract_title_params`).

    ⛔ Medido 2026-10-01 (U03 do autor no Mac): pelo AAF o título da PRODA ("PRODUCAO-A", Titler+
    Legacy na V3) chegava à Carta só com `params.text`, sem este bloco — e o writer do DRT o
    descartava EM SILÊNCIO. Pela bin, o mesmo título entrava. Agora os dois caminhos dão o mesmo bloco."""
    if not mqp_txt and not any((t or "").strip() for t in textos):
        return None
    legado = "legacy" in (operacao or "").lower() or "title tool" in (operacao or "").lower()
    eid = EID_LEGACY if legado else EID_TITLER
    # o titulador é o NOME da operação do AAF ("Avid Title Tool" não vira "Avid Title Tool Legacy")
    return bloco(eid, (operacao or "").replace(" Legacy", ""), textos, mqp_txt,
                 titulador=None if mqp_txt else (operacao or None))
