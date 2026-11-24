"""O clipe de matte key da bin: reconhecido como arte com alpha, não recusado como preset.

MEDIDO na `MAIS VC AUTO` (MC 2025.6, 2026-09-13): o Media Composer põe na bin, para cada
arquivo com alpha, uma `CompositionMob usage=effect` com um `TrackEffect
EFF2_BLEND_MATTE_KEY` — o MESMO `usage_code` do preset de Color Correction. O que separa os
dois é haver mídia dentro do efeito. Recusá-lo como preset impediu o Haiku de usar as artes.
"""

from __future__ import annotations

from types import SimpleNamespace

from cicloassist.avid import take as K


class TrackEffect(SimpleNamespace):
    pass


class SourceClip(SimpleNamespace):
    pass


class Filler(SimpleNamespace):
    pass


def _efeito(effect_id, com_midia=True):
    trilhas = [SimpleNamespace(component=Filler(length=10))]
    if com_midia:
        trilhas += [SimpleNamespace(component=SourceClip(mob_id="urn:pre", track_id=1,
                                                         start_time=0)),
                    SimpleNamespace(component=SourceClip(mob_id="urn:pre", track_id=2,
                                                         start_time=0))]
    return SimpleNamespace(mob_type="CompositionMob", usage="effect", tracks=[
        SimpleNamespace(component=TrackEffect(effect_id=effect_id, tracks=trilhas))])


def test_matte_key_com_midia_e_arte_aceita():
    mob = _efeito("EFF2_BLEND_MATTE_KEY")
    assert K.especie(mob) == "matte" and "matte" in K.ESPECIES_ACEITAS


def test_preset_de_efeito_continua_recusado():
    """⛔ O Color Correction da `BIN ORIGEM` tem o mesmo usage_code e nenhuma mídia."""
    assert K.especie(_efeito("EFF2_COLOR_CORRECTION", com_midia=False)) == "efeito"
    assert K.especie(_efeito("EFF2_BLEND_MATTE_KEY", com_midia=False)) == "efeito"


def test_montar_corte_recusa_matte_key_com_a_frase_certa(monkeypatch, tmp_path):
    from cicloassist.mcp.ferramentas import corte as C

    arte = SimpleNamespace(especie="matte", nome="Matte Key: rdp HJ.new.01")
    monkeypatch.setattr(C, "resolver", lambda *_a, **_k: arte)

    class _MC:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            return None

        def projeto(self):
            return {"caminho": str(tmp_path), "fps_aprox": 29.97}

    monkeypatch.setattr(C, "MediaComposer", _MC)
    r = C.montar_corte(bin=str(tmp_path / "B.avb"), nome="MVC", cortes=[
        {"take": "Matte Key: rdp HJ.new.01", "duracao_frames": 30, "confianca": "inferido",
         "fonte": "roteiro", "porque": "cartela"}])
    assert "matte key" in r["erro"] and "preset" not in r["erro"]
