"""Premiere → Avid: o título volta a aparecer (sintetizado como Avid Titler+), não como buraco.

Rodar:

    .venv/bin/python tests/test_titulo_avid_escrita.py        (Mac)
    .venv-win/Scripts/python tests/test_titulo_avid_escrita.py (Windows)

O critério forte é o do LEITOR já medido (`titulos/avid.py`, banco `titler-plus-mqp.json`): o MQP
que o escritor sintetiza a partir do MODELO NEUTRO tem de ser RELIDO com o mesmo texto, fonte,
corpo, cor e alinhamento. É ida-e-volta pelo leitor confirmado — a prova de que o MC RENDERIZA
fica para a conferência ao vivo (pilotando o MC).

Sem disco externo: o molde do Title+ sai do `templates.json` embarcado.
"""

from __future__ import annotations

import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "motor"))

import avb  # noqa: E402
from avb_export import translate as T  # noqa: E402
from titulos import avid as R  # noqa: E402
from titulos import avid_escrita as W  # noqa: E402


def _molde_mqp() -> str:
    """O texto do MQP do molde do Title+, tirado do CFUserParam do template embarcado."""
    tpl = T.capture_templates()
    spec = tpl[T.TITLE_EID]
    f = avb.open()
    te = T.materialize(f, spec)
    cf = next(it.property_data["value"] for it in te.property_data["param_list"]
              if str(it.property_data.get("uuid")) == T.TITLE_MQP_UUID)
    return bytes(cf.property_data["data"]).decode("utf-8", "replace")


def _bloco(texto, *, familia="Open Sans", estilo="", corpo=0.0833333, cor=(1, 1, 1),
           alinhamento="centro", posicao_resolve=None, posicao=None):
    cx = {"texto": texto, "fonte": {"familia": familia, "estilo": estilo}, "corpo": corpo,
          "cor": list(cor), "alinhamento": alinhamento}
    if posicao_resolve is not None:
        cx["posicao_resolve"] = posicao_resolve
    if posicao is not None:
        cx["posicao"] = posicao
    return {"estilo_lido": True, "caixas": [cx]}


def main() -> int:
    falhas: list[str] = []
    casos = 0

    def ok(rotulo, obtido, esperado):
        nonlocal casos
        casos += 1
        certo = obtido == esperado
        mostra = repr(obtido) if len(repr(obtido)) < 60 else f"{repr(obtido)[:57]}..."
        print(f"  {'ok  ' if certo else 'FALHA'} {rotulo:<66} -> {mostra}")
        if not certo:
            falhas.append(f"{rotulo}: veio {obtido!r}, esperava {esperado!r}")

    molde = _molde_mqp()

    def relê(bloco):
        """Sintetiza e relê o MQP pelo leitor confirmado -> a 1ª caixa do bloco neutro."""
        mqp_txt, avisos = W.sintetizar(molde, bloco)
        # balanço de chaves: não corrompeu a estrutura do DB
        assert mqp_txt.count("{") == mqp_txt.count("}"), "chaves desbalanceadas"
        lido = R.bloco(R.EID_TITLER, "", [], mqp_txt)
        return lido["caixas"][0], avisos, mqp_txt

    print("── 1. ida-e-volta pelo leitor confirmado (texto, fonte, corpo, cor, alinhamento) ──")
    cx, _av, _ = relê(_bloco("PRODUCAO-C", familia="Courier", estilo="Bold",
                             corpo=0.12, cor=[1, 0, 0], alinhamento="direita"))
    ok("o texto renderizado vem dos Character", cx["texto"], "PRODUCAO-C")
    ok("fonte família + face", cx["fonte"], {"familia": "Courier", "estilo": "Bold"})
    ok("corpo = fração da altura (Text.Font.Size)", cx["corpo"], 0.12)
    ok("cor RGB 0..1 (Material.Main.Base)", cx["cor"], [1.0, 0.0, 0.0])
    ok("alinhamento (Justify do Paragraph)", cx["alinhamento"], "direita")

    print("── 2. acento, multi-linha, e o padrão ──")
    cx, _av, _ = relê(_bloco("AÇÃO É ótimo"))
    ok("acento preservado (UTF-8 no DB)", cx["texto"], "AÇÃO É ótimo")
    cx, _av, _ = relê(_bloco("LINHA UM\nLINHA DOIS"))
    ok("multi-linha: a quebra chega como 0xA", cx["texto"], "LINHA UM\nLINHA DOIS")
    novo, _ = W.sintetizar(_molde_mqp(), _bloco("A\tB"))
    ok("tabulação vai como 0x9 (nunca crua no MQP)", ("Code = 0x9" in novo, "Code = \t" in novo), (True, False))
    cx, _av, _ = relê(_bloco("A\tB"))
    ok("…e relê como tabulação", cx["texto"], "A\tB")
    cx, _av, _ = relê(_bloco("SIMPLES"))
    ok("sem face, estilo vazio", cx["fonte"]["estilo"], "")
    ok("centro é o padrão", cx["alinhamento"], "centro")

    print("── 3. posição: Avid direto; e a volta do Premiere com aviso ──")
    cx, _av, _ = relê(_bloco("POS", posicao={"x": -0.3, "y": 0.2}))
    ok("posição do Avid (alturas do centro, Y p/ cima) ida-e-volta",
       (round(cx["posicao"]["x"], 3), round(cx["posicao"]["y"], 3)), (-0.3, 0.2))
    cx, avisos, _ = relê(_bloco("POS", posicao_resolve=(0.5, 0.5)))
    ok("posicao_resolve avisa para conferir", any("conferir" in a for a in avisos), True)

    print("── 4. ponta a ponta: segmento de título do Premiere -> TrackEffect Title+ (não gap) ──")
    tpl = T.capture_templates()
    titulo = _bloco("TÍTULO PRODC", cor=[0, 0, 1])
    seg = {"is_effect": True, "duration_frames": 90, "disabled": False, "is_gap": False,
           "is_transition": False, "colapso": None, "mob_id": None,
           "effects": [{"name": "Text", "category": "title", "params": {"titulo": titulo}}]}
    entry = T._title_entry(seg)
    ok("_title_entry reconhece o título do Premiere", entry[0], "title")
    ok("o estilo leva o bloco neutro (não mqp_hex)", "bloco" in entry[1], True)
    f = avb.open()
    te = T._build_title(f, entry[1], entry[2], entry[3], "picture", tpl)
    ok("virou TrackEffect", type(te).__name__, "TrackEffect")
    ok("effect_id do Avid Titler+ atual", str(te.effect_id), T.TITLE_EID)
    ok("length = duração do segmento", te.length, 90)
    cf = next(it.property_data["value"] for it in te.property_data["param_list"]
              if str(it.property_data.get("uuid")) == T.TITLE_MQP_UUID)
    lido = R.bloco(R.EID_TITLER, "", [], bytes(cf.property_data["data"]).decode("utf-8", "replace"))
    ok("o MQP do efeito relê com o texto certo", lido["caixas"][0]["texto"], "TÍTULO PRODC")
    ok("o _TTEXT (nome do clipe) leva o texto", bytes(te.property_data["attributes"]["_TTEXT"]),
       b"\x00\x00T+: T\xc3\x8dTULO PRODC \x00")

    print("── 5. guarda de regressão: o título do Premiere NÃO cai em gap ──")
    seg2 = {**seg, "duration_frames": 50}
    e = T._seg_to_entry_base(seg2, {}, {}, "picture")
    ok("⭐ _seg_to_entry_base devolve 'title', não 'gap'", e[0], "title")

    print("── 6. o caminho do AAF (mqp_hex) continua intacto ──")
    # um AVUP mínimo com o MQP do molde como `data`
    import uuid as _uuid
    data = molde.encode("utf-8")
    uid = _uuid.UUID(T.TITLE_MQP_UUID)
    avup = (b"XXXXXXXXXXXXXXXX" + b"PUVA" + b"\x00" * 8 + uid.bytes_le
            + len(data).to_bytes(4, "little") + len(data).to_bytes(4, "little") + data)
    seg3 = {"is_effect": True, "duration_frames": 30, "disabled": False, "is_gap": False,
            "mob_id": None, "effects": [{"name": "Avid Titler+", "category": "title",
                                         "params": {"mqp_hex": avup.hex(), "text": "DO AAF"}}]}
    entry3 = T._title_entry(seg3)
    ok("AAF: estilo leva mqp_hex", "mqp_hex" in entry3[1], True)
    te3 = T._build_title(avb.open(), entry3[1], entry3[2], entry3[3], "picture", tpl)
    ok("AAF: vira TrackEffect Title+", str(te3.effect_id), T.TITLE_EID)

    print(f"\n{casos - len(falhas)}/{casos} casos")
    for fl in falhas:
        print(f"  ✗ {fl}")
    return 1 if falhas else 0


if __name__ == "__main__":
    raise SystemExit(main())
