"""O som gerenciado nomeia e preenche as colunas COMO O MC faz ao linkar o mesmo BWF (autor, 2026-11-01).

O gabarito é a bin que o PRÓPRIO MC gravou ao linkar 11 WAV sintéticos do laboratório (MC 25.12, 2026-10-25;
`laboratorio-de-midia/saida/bancadas/avid/nomes_audio_bin_mc2512.avb`): cena/take no bext, só no iXML, take com letra,
sem cena, sem bext nenhum, acento, `;` no nome e na cena, nome longo, extensão minúscula. ⛔ É isso que "garante que
uma gravação nova funciona": cada variante de gravador que já vimos, contra o que o MC escreveu.

Sem o laboratório na máquina (outro clone), pula.
"""

from __future__ import annotations

import unicodedata
from pathlib import Path

import pytest

from cicloassist.midia import bwf

def _laboratorio() -> Path | None:
    """SOBE de pasta até achar o `laboratorio-de-midia` (regra da família): o app mora em profundidades diferentes no
    SSD do autor (`2 ATIVOS/<app>`) e no kit aberto (`<kit>/ciclo-assist-kit-nle`)."""
    for p in Path(__file__).resolve().parents:
        if (p / "laboratorio-de-midia").is_dir():
            return p / "laboratorio-de-midia"
    return None


_RAIZ_LAB = _laboratorio()
LAB = (_RAIZ_LAB or Path("laboratorio-de-midia")) / "saida" / "bancadas" / "avid"
WAVS = LAB / "nomes_audio"
GABARITO = LAB / "nomes_audio_bin_mc2512.avb"

pytestmark = pytest.mark.skipif(
    not GABARITO.is_file() or not WAVS.is_dir(),
    reason="o laboratório de mídia não está acima desta pasta" if _RAIZ_LAB is None else
    "falta a saída da bancada de nomes de áudio do laboratório (gerada, não versionada; o gabarito é uma bin do MC 25.12)")


def _do_mc() -> dict[str, dict]:
    import avb
    fora = {}
    with avb.open(str(GABARITO)) as f:
        for m in f.content.mobs:
            if m.property_data.get("mob_type_id") == 2:
                a = m.property_data.get("attributes")
                fora[unicodedata.normalize("NFC", m.name)] = dict(a["_USER"]) if a is not None and "_USER" in a else {}
    return fora


def test_os_onze_wav_como_o_mc_os_nomeou_e_preencheu():
    do_mc = _do_mc()
    nossos = {bwf.como_o_avid(str(w))["nome"]: bwf.como_o_avid(str(w))["user"]
              for w in sorted(WAVS.iterdir()) if w.suffix.lower() == ".wav"}
    assert len(nossos) == 11
    assert set(nossos) == set(do_mc), (sorted(nossos), sorted(do_mc))
    for nome, user in nossos.items():
        esperado = dict(do_mc[nome])
        obtido = dict(user)
        if "LAB_V04" in nome:
            # ⚠️ sem bext, o Shoot Date é a data do ARQUIVO na máquina que linkou (o Mac do laboratório)
            esperado.pop("Shoot Date", None)
            obtido.pop("Shoot Date", None)
        assert obtido == esperado, nome


def test_os_nomes_que_o_sincronizar_vai_ler():
    """Com cena: CENA/TAKE (take com letra vale, o ; da cena fica); sem: o arquivo com a extensão."""
    nomes = {w.name: bwf.como_o_avid(str(w))["nome"] for w in WAVS.iterdir() if w.suffix.lower() == ".wav"}
    assert nomes["LAB_V01-A.WAV"] == "LAB-CENA/001"            # bext
    assert nomes["LAB_V02-A.WAV"] == "LAB-CENA2/002"           # só iXML
    assert nomes["LAB_V10.WAV"] == "CENA10/3A"                 # take com letra
    assert nomes["LAB_V06.WAV"] == "CENA;6/001"                # ; na cena: o MC não troca
    assert nomes["LAB_V08.wav"] == "LAB_V08.wav"               # sem cena: o arquivo, extensão como está
