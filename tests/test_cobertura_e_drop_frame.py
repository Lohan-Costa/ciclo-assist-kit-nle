"""Arte com alpha na V2 e timecode drop-frame — as duas coisas da `MAIS VC AUTO`.

MEDIDO em 2026-09-13 na `SEQ ANALISE` (sequências feitas à mão pelo editor, MC 2025.6):

- drop-frame: `Timecode.flags = 1`, `start = 107892` (a contagem contínua de `01;00;00;00`);
  non-drop: `flags = 0`, `start = 108000`;
- matte key na V2: o MESMO `TrackEffect EFF2_BLEND_MATTE_KEY` do clipe da bin, e o MC
  guarda oculto na bin o clipe de matte key e o master `precompute`. Comparado campo a campo
  com o que o produto grava: igual, fora `_MATCH` e caches de reprodução.

O clipe de matte key daqui é SINTÉTICO, montado com os campos medidos.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import avb
import pytest
from avb.mobid import MobID

from cicloassist.avid import timeline as T
from cicloassist.avid import timeline_do_editor as TE
from cicloassist.avid.take import efeito_de_chave, especie
from cicloassist.plano import esquema as P

FORA = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.000000ff"
R = 29.97


def _clipe_de_matte_key(f, nome="ARTE.new.01", duracao=120, taxa=R):
    """O que o MC põe na bin ao importar um arquivo com alpha (`take.efeito_de_chave`)."""
    pre = T.montar_timeline(f, nome, [T.Entrada(mob_id=FORA, duracao=duracao,
                                                trilhas=(("picture", 1), ("picture", 2)))], taxa)
    next(i for i in f.content.items if i.mob is pre).user_placed = False
    mk = f.create.Composition(f"Matte Key: {nome}", "CompositionMob")
    mk.name = f"Matte Key: {nome}"
    mk.mob_id = MobID(bytes_le=bytes(bytearray(T.PREFIXO_DE_COMPOSICAO) + bytes(range(16))))
    mk.edit_rate, mk.usage_code, mk.length = taxa, 3, duracao
    mk.attributes, mk.mc_mode, mk.num_scalars, mk.param_list = T._atributos(f), 0, 0, None
    te = f.create.TrackEffect(taxa, "picture")
    te.effect_id, te.length, te.left_length, te.right_length = "EFF2_BLEND_MATTE_KEY", \
        duracao, 0, duracao + 1
    te.attributes = T._atributos(f, _BORDER_FIXED=0, _IGNORE_TRACKING=0)
    for k, v in dict(mc_mode=0, num_scalars=0, info_version=2, info_current=0, info_smooth=0,
                     info_color_item=1, info_quality=1, info_is_reversed=0,
                     info_aspect_on=True, info_force_software=False, info_never_hardware=False,
                     trackman=None, keyframes=None, param_list=None, session_attrs=None,
                     precomputed=None).items():
        setattr(te, k, v)
    fundo = f.create.Track()
    fundo.index = 1
    fundo.component = f.create.Sequence(taxa, "picture")
    fundo.component.components = [T._filler(f, taxa, duracao, "picture")]
    fundo.filler_proxy = T._referencia_de_track(f, taxa, "picture")
    fundo.filler_proxy.relative_scope = 1
    trilhas = [fundo]
    for i in (1, 2):
        t = f.create.Track()
        t.index = i + 1
        t.component = f.create.SourceClip(taxa, "picture")
        t.component.mob_id, t.component.track_id = pre.mob_id, i
        t.component.start_time, t.component.length = 0, duracao
        trilhas.append(t)
    te.tracks = trilhas
    tk = f.create.Track()
    tk.index, tk.component = 1, te
    mk.tracks = [tk]
    f.content.add_mob(mk).user_placed = True
    return mk


@pytest.fixture
def base(tmp_path) -> tuple[Path, str]:
    caminho = tmp_path / "ARTES.avb"
    with avb.open() as f:
        _clipe_de_matte_key(f)
        f.write(str(caminho))
    with avb.open(str(caminho)) as f:
        mid = str(next(m.mob_id for m in f.content.mobs if (m.name or "").startswith("Matte")))
    return caminho, mid


def _sequencia(caminho):
    f = avb.open(str(caminho))
    return f, next(i.mob for i in f.content.items if i.user_placed)


# ── drop-frame ───────────────────────────────────────────────────────────────

def test_timeline_de_projeto_drop_frame_nasce_drop_frame():
    f = avb.file.AVBFile()
    df = T.montar_timeline(f, "DF", [T.Entrada(mob_id=FORA, duracao=10,
                                                trilhas=(("picture", 1),))], R, drop_frame=True)
    tc = next(t.component for t in df.tracks if type(t.component).__name__ == "Timecode")
    assert (tc.flags, tc.start) == (1, 107892)
    nd = T.montar_timeline(f, "25", [T.Entrada(mob_id=FORA, duracao=10,
                                                trilhas=(("picture", 1),))], 25, drop_frame=True)
    tc = next(t.component for t in nd.tracks if type(t.component).__name__ == "Timecode")
    assert (tc.flags, tc.start) == (0, 90000)       # 25 fps não tem drop-frame


def test_ler_e_editar_sequencia_drop_frame_falam_com_ponto_e_virgula(tmp_path):
    caminho = tmp_path / "DF.avb"
    with avb.open() as f:
        T.montar_timeline(f, "DF", [
            T.Entrada(mob_id=FORA, duracao=1800, trilhas=(("picture", 1),)),
            T.Entrada(mob_id=FORA, duracao=600, trilhas=(("picture", 1),), start_time=5000),
        ], R, drop_frame=True)
        f.write(str(caminho))
    r = TE.ler(caminho, "DF")
    assert r["drop_frame"] and r["inicio"] == "01;00;00;00"
    assert r["trilhas"]["V1"][1].startswith("01;01;00;02 → ")   # 1800 quadros depois
    feito = TE.aplicar(caminho, "DF", [{"tipo": "extrair", "de": "01;01;00;02",
                                        "ate": "01;01;20;02"}])
    assert "01;01;00;02 → 01;01;20;02" in feito["operacoes"][0]


# ── a arte na V2 ─────────────────────────────────────────────────────────────

def test_clipe_sintetico_e_reconhecido_como_matte(base):
    with avb.open(str(base[0])) as f:
        mk = next(m for m in f.content.mobs if (m.name or "").startswith("Matte"))
        assert especie(mk) == "matte" and efeito_de_chave(mk) is not None


def test_cobertura_vai_na_v2_aparada_e_leva_o_fecho_oculto(base, tmp_path):
    caminho, mid = base
    saida = tmp_path / "TL.avb"
    T.escrever_bin(saida, [("TL", [T.Entrada(mob_id=FORA, duracao=300, trilhas=(
        ("picture", 1), ("sound", 1)))], [T.Cobertura(mob_id=mid, posicao=50, duracao=60,
                                                       inicio=10)])], R, base=caminho)
    f, tl = _sequencia(saida)
    with f:
        ordem = [(getattr(t.component, "media_kind", ""), t.index) for t in tl.tracks]
        assert ordem[:3] == [("picture", 1), ("picture", 2), ("sound", 1)]   # V2 antes do som
        v2 = next(t.component for t in tl.tracks
                  if getattr(t.component, "media_kind", "") == "picture" and t.index == 2)
        assert [(type(c).__name__, c.length) for c in v2.components] == [
            ("Filler", 50), ("TrackEffect", 60), ("Filler", 190)]
        te = v2.components[1]
        fundo, preenchimento, alpha = (t.component for t in te.tracks)
        assert [c.length for c in fundo.components] == [60]
        assert (preenchimento.start_time, preenchimento.length, preenchimento.track_id) == \
            (10, 60, 1)
        assert (alpha.start_time, alpha.track_id) == (10, 2)
        assert te.right_length == 61                     # a folga da bin preservada
        ocultos = sorted(i.mob.name for i in f.content.items if not i.user_placed)
        assert ocultos == ["ARTE.new.01", "Matte Key: ARTE.new.01"]
    assert "matte key" in " ".join(TE.ler(saida, "TL")["trilhas"]["V2"])


@pytest.mark.parametrize("coberturas, frase", [
    ([T.Cobertura("X", 0, 10), T.Cobertura("X", 5, 10)], "sobrepõem"),
    ([T.Cobertura("X", 280, 60)], "passa do fim"),
    ([T.Cobertura("X", 0, 10, trilha=1)], "V1 já é da imagem"),
    ([T.Cobertura("X", 0, 200, inicio=0)], "não cabe"),
])
def test_cobertura_que_nao_cabe_e_recusada(base, tmp_path, coberturas, frase):
    caminho, mid = base
    coberturas = [T.Cobertura(mid, c.posicao, c.duracao, c.inicio, c.trilha) for c in coberturas]
    with pytest.raises(ValueError, match=frase):
        T.escrever_bin(tmp_path / "TL.avb", [("TL", [T.Entrada(mob_id=FORA, duracao=300,
                                                               trilhas=(("picture", 1),))],
                                              coberturas)], R, base=caminho)


def test_arte_de_outra_taxa_e_recusada(tmp_path):
    caminho = tmp_path / "AMA.avb"
    with avb.open() as f:
        _clipe_de_matte_key(f, taxa=30.0)            # a arte AMA a 30p da MIDAS LINK
        f.write(str(caminho))
    with avb.open(str(caminho)) as f:
        mid = str(next(m.mob_id for m in f.content.mobs if (m.name or "").startswith("Matte")))
    with pytest.raises(ValueError, match="misturar taxas"):
        T.escrever_bin(tmp_path / "TL.avb", [("TL", [T.Entrada(mob_id=FORA, duracao=300,
                                                               trilhas=(("picture", 1),))],
                                              [T.Cobertura(mid, 0, 30)])], R, base=caminho)


# ── o plano ──────────────────────────────────────────────────────────────────

CORTES = [{"take": "A", "duracao_frames": 100, "confianca": "inferido", "fonte": "roteiro",
           "porque": "abre"},
          {"take": "B", "duracao_frames": 200, "confianca": "inferido", "fonte": "roteiro",
           "porque": "fecha"}]


def _cob(**k):
    return {"arte": "Matte Key: ARTE.new.01", "sobre_o_corte": 2, "confianca": "inferido",
            "fonte": "roteiro", "porque": "CARTÃO: 10:35", **k}


def test_plano_ancora_a_arte_no_corte():
    plano = P.validar({"bin": "B", "nome": "MVC", "cortes": CORTES,
                       "coberturas": [_cob(deslocamento_frames=30, trilha="V3")]})
    cob = plano.coberturas[0]
    assert plano.inicio_do_corte(cob.sobre_o_corte) + cob.deslocamento_frames == 130
    assert cob.trilha == 3
    assert "V3: Matte Key: ARTE.new.01 sobre o corte 2 +30f" in P.resumir(plano, R)


@pytest.mark.parametrize("cob, frase", [
    (_cob(sobre_o_corte=3), "cortes 1 a 2"),
    (_cob(trilha="V1"), "V1 é da imagem"),
    (_cob(porque=""), "sem `porque`"),
    (_cob(deslocamento_frames=250), "depois do fim"),
])
def test_plano_recusa_cobertura_malformada(cob, frase):
    with pytest.raises(P.PlanoInvalido, match=frase):
        P.validar({"bin": "B", "nome": "MVC", "cortes": CORTES, "coberturas": [cob]})


def test_montar_corte_poe_a_arte_na_v2_e_segue_o_drop_frame_do_projeto(base, tmp_path,
                                                                       monkeypatch):
    from cicloassist.mcp.ferramentas import corte as C

    caminho, mid = base
    take = SimpleNamespace(mob_id=FORA, especie="master", nome="A", duracao_frames=500,
                           imagem=SimpleNamespace(tracks=1), som=None)
    arte = SimpleNamespace(mob_id=mid, especie="matte", nome="Matte Key: ARTE.new.01",
                           duracao_frames=120)
    monkeypatch.setattr(C, "resolver", lambda _b, nome: arte if nome.startswith("Matte")
                        else take)

    class _MC:
        def __call__(self):
            return self

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def projeto(self):
            return {"caminho": str(tmp_path), "fps_aprox": R, "drop_frame": True}

        def _chamar(self, *_a, **_k):
            return None

    monkeypatch.setattr(C, "MediaComposer", _MC())
    r = C.montar_corte(bin=str(caminho), nome="MVC 9 6", cortes=CORTES,
                       coberturas=[_cob(deslocamento_frames=30)])
    assert r["ok"] and r["coberturas"] == 1 and r["drop_frame"], r
    leitura = TE.ler(tmp_path / "MVC 9 6.avb", "MVC 9 6")
    assert leitura["inicio"] == "01;00;00;00"
    assert leitura["trilhas"]["V2"][0].startswith("01;00;04;10 → ")   # 130 quadros
