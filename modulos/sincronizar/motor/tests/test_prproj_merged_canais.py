"""
O MAPEAMENTO DE CANAIS DO MERGED CLIP — medido contra um merged NATIVO do Premiere.

Por que existe: o merged clip saía com os canais em **passo 2** — `[A1][A3][A5][A7][A9]`
onde o WAV cru mostra `[A1][A2][A3][A4][A5]`. E o XML *parecia* certo: `NumAdaptiveChannels=1`,
`ChannelType=0` em todas as tracks e no master, o `ClipChannelGroup` na variante que a
regra escrita mandava usar. Quatro campos conferidos, todos certos, e o defeito na tela.

⭐ A resposta veio do A/B: um merged feito à mão (`Clip ▸ Merge Clips…`) e o nosso na
mesma timeline, salvos, e o diff do XML CRU da cadeia inteira — sem escolher campos.
Premiere 25.6.5, som de **5 canais**, 2026-09-06.

O que o nativo faz, e nenhuma regra escrita antes previa:

  1. o MasterClip de BIN do merged usa a variante **per-source** (`SourceClipIndex` varia)
     — ainda que a fonte dele seja uma SEQUÊNCIA, o que contraria a regra "sequência usa
     a outra variante". A escolha não é decidida pelo tipo da fonte;
  2. o MasterClip POR-CANAL declara os N canais mas ocupa **só o seu slot**, numa
     DIAGONAL, com os outros N-1 em `UINT64_MAX` (= não mapeado);
  3. e ele carrega **N clips**, não um — o slot vivo precisa de um clip de mesmo índice
     para resolver.

⚠️ Estes testes NÃO afirmam que o merged clip está inteiro certo — afirmam que a forma
do canal é a MEDIDA, e não a que a gente supôs. É o que faltava: não havia teste nenhum
cobrindo merged, e por isso o defeito só apareceu na tela do autor.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from prproj.builder import _B
from sync.model import CameraAngle, CameraGroup, Daily, Project, SoundClip, Take

FPS = 24.0
N_CANAIS = 5          # o material de referência da medição: gravador de 5 canais
NAO_MAPEADO = "18446744073709551615"


def _projeto(tmp: Path) -> Project:
    """Uma tomada: uma câmera e um som de 5 canais. É o mínimo que rende um merged."""
    cam_p, snd_p = tmp / "cam.mp4", tmp / "som.wav"
    cam_p.write_bytes(b"x")
    snd_p.write_bytes(b"x")

    cam = CameraAngle(path=cam_p, fps=FPS, duration_frames=240,
                      timeline_start_frames=0, sync_offset_frames=30, audio_channels=2)
    snd = SoundClip(path=snd_p, sample_rate=48000, duration_ms=10000,
                    channels=N_CANAIS, timeline_start_frames=0)
    d = Daily(camera_groups=[CameraGroup(cameras=[cam], name="CAM A", id="a")],
              takes=[Take(sound=snd, cameras=[cam])], name="D")
    return Project(name="P", groups=[d]), cam, snd


def _construir(tmp: Path):
    """Roda só a maquinaria de merged e devolve (builder, uids, índice por ObjectID)."""
    projeto, cam, snd = _projeto(tmp)
    b = _B(projeto, None)
    uids = b._build_merged_clip(cam, snd, b._cam_duration_ticks(cam),
                               N_CANAIS, str(b._tpf()))
    raiz = ET.Element("R")
    for el in b._els:
        raiz.append(el)
    por_oid = {e.get("ObjectID"): e for e in raiz.iter() if e.get("ObjectID")}
    por_uid = {e.get("ObjectUID"): e for e in raiz.iter() if e.get("ObjectUID")}
    return uids, por_oid, por_uid


def _mapa(por_oid: dict, mc: ET.Element) -> list[tuple[str, str]]:
    """Os pares (SourceClipIndex, mSourceChannelIndex) de um MasterClip, em ordem."""
    grp = por_oid[mc.find("AudioClipChannelGroups").get("ObjectRef")]
    saida = []
    for item in grp.findall(".//ClipChannelVectorItem"):
        vec = por_oid[item.get("ObjectRef")]
        for ci in vec.findall(".//ClipChannelItem"):
            ccs = por_oid[ci.get("ObjectRef")]
            saida.append((ccs.findtext("SourceClipIndex"),
                          ccs.findtext("mSourceChannelIndex")))
    return saida


def test_o_masterclip_de_bin_usa_a_variante_PER_SOURCE(tmp_path):
    """⚠️ Contraintuitivo: a fonte dele é uma SEQUÊNCIA e mesmo assim é per-source.

    Medido no nativo: `(0,0) (1,0) (2,0) (3,0) (4,0)`. Escrevíamos a variante de
    sequência — `(0,0) (0,1) … (0,4)` —, seguindo a regra "sequência usa esta", e era
    justamente o que a regra não cobria.
    """
    (main_mc_uid, _, _, _, _, _), por_oid, por_uid = _construir(tmp_path)
    mapa = _mapa(por_oid, por_uid[main_mc_uid])
    assert mapa == [(str(i), "0") for i in range(N_CANAIS)]


def test_cada_masterclip_por_canal_ocupa_SO_o_seu_slot(tmp_path):
    """A DIAGONAL. O canal k mapeia o vetor k; os outros N-1 são UINT64_MAX.

    ⛔ Mapear todos em todos é o que punha os canais em passo 2 na timeline: cada
    por-canal expunha os N canais e o merged somava aridade que não tinha.
    """
    (_, per_ch, _, _, _, _), por_oid, por_uid = _construir(tmp_path)
    assert len(per_ch) == N_CANAIS

    for ch, mc_uid in enumerate(per_ch):
        mapa = _mapa(por_oid, por_uid[mc_uid])
        assert len(mapa) == N_CANAIS, f"canal {ch}: aridade errada"
        for i, (clip_idx, canal_idx) in enumerate(mapa):
            if i == ch:
                assert (clip_idx, canal_idx) == (str(ch), "0"), \
                    f"canal {ch}: o slot vivo devia ser ({ch},0), veio {(clip_idx, canal_idx)}"
            else:
                assert clip_idx == NAO_MAPEADO and canal_idx == NAO_MAPEADO, \
                    f"canal {ch}: o slot {i} devia estar VAZIO, veio {(clip_idx, canal_idx)}"


def test_o_masterclip_por_canal_carrega_N_clips_nao_um(tmp_path):
    """O slot vivo aponta para o CLIP de mesmo índice — sem N clips ele não resolve."""
    (_, per_ch, _, _, _, _), _, por_uid = _construir(tmp_path)
    for ch, mc_uid in enumerate(per_ch):
        clips = por_uid[mc_uid].findall("Clips/Clip")
        assert len(clips) == N_CANAIS, f"canal {ch}: {len(clips)} clips, esperado {N_CANAIS}"
        assert [c.get("Index") for c in clips] == [str(i) for i in range(N_CANAIS)]


def test_o_camMC_continua_na_variante_de_sequencia(tmp_path):
    """⭐ O contraste que prova que a regra não é "tudo per-source agora".

    O MasterClip dedicado da câmera (a cópia de mídia que é alvo do SubClip de vídeo)
    já batia com o nativo ANTES do conserto, e tem de continuar batendo: `(0,0) (0,1)`
    para os 2 canais da câmera. Mudar os três de uma vez teria quebrado este.
    """
    (_, _, _, cam_mc_uid, _, _), por_oid, por_uid = _construir(tmp_path)
    assert _mapa(por_oid, por_uid[cam_mc_uid]) == [("0", "0"), ("0", "1")]


# ── §7.1: quem SELECIONA o canal é o StreamNumber ────────────────────────────
#
# ⛔⛔ A regra já existia e já estava implementada no `_make_wav_media` — o caminho da
# mídia crua respeitava desde 2026-07-12. O merged NÃO, porque tinha uma SEGUNDA
# implementação (`_make_extra_wav_ams`) que criava UM Media com o layout dos N canais,
# sem StreamNumber, e com FileKey novo a cada chamada.
#
# ⭐ É a caixa "o que NÃO funciona" da regra, ao pé da letra — e o sintoma foi o mesmo
# que ela descreve. Os testes abaixo existem para que o merged não possa mais divergir.


def _midias_do_merged(por_oid, por_uid, per_ch):
    """Desce por-canal[k] → clip[k] (o slot vivo) → ams → Media."""
    saida = []
    for k, mc_uid in enumerate(per_ch):
        mc = por_uid[mc_uid]
        ac = por_oid[mc.findall("Clips/Clip")[k].get("ObjectRef")]
        ams = por_oid[ac.find(".//Source").get("ObjectRef")]
        media = por_uid[ams.find(".//Media").get("ObjectURef")]
        saida.append((media, ac, por_oid[media.find("AudioStream").get("ObjectRef")]))
    return saida


def test_cada_canal_do_merged_e_selecionado_pelo_StreamNumber(tmp_path):
    """`ausente, 1, 2, … N-1` — ausência significa "o primeiro canal"."""
    (_, per_ch, _, _, _, _), por_oid, por_uid = _construir(tmp_path)
    nums = [m.findtext("StreamNumber") for m, _, _ in
            _midias_do_merged(por_oid, por_uid, per_ch)]
    assert nums == [None] + [str(k) for k in range(1, N_CANAIS)]


def test_o_Media_de_cada_canal_do_merged_e_MONO(tmp_path):
    """Se ele declarasse os N canais, não seria "um canal" — seria o arquivo todo."""
    (_, per_ch, _, _, _, _), por_oid, por_uid = _construir(tmp_path)
    for k, (_, _, astream) in enumerate(_midias_do_merged(por_oid, por_uid, per_ch)):
        assert astream.findtext("AudioChannelLayout") == '[{"channellabel":0}]', \
            f"canal {k}: o AudioStream devia ser MONO"


def test_os_N_canais_do_merged_sao_O_MESMO_ARQUIVO(tmp_path):
    """`FileKey` e `ContentAndMetadataState` identificam o ARQUIVO, não o canal.

    ⛔ Um por canal faria o Premiere ver N arquivos diferentes que por acaso têm o
    mesmo caminho — era o que a implementação duplicada fazia (`new_uid()` a cada
    chamada).
    """
    (_, per_ch, _, _, _, _), por_oid, por_uid = _construir(tmp_path)
    medias = [m for m, _, _ in _midias_do_merged(por_oid, por_uid, per_ch)]
    assert len({m.findtext("FileKey") for m in medias}) == 1
    assert len({m.findtext("ContentAndMetadataState") for m in medias}) == 1


def test_o_ChannelIndex_do_merged_e_sempre_ZERO(tmp_path):
    """§7.2: quando a fonte VIRA o canal, todo índice dentro dela zera.

    ⛔ Pedir `ChannelIndex=N` de uma fonte mono deixa a track MUDA e sem waveform.
    """
    (_, per_ch, _, _, _, _), por_oid, por_uid = _construir(tmp_path)
    for k, (_, ac, _) in enumerate(_midias_do_merged(por_oid, por_uid, per_ch)):
        idx = [por_oid[x.get("ObjectRef")].findtext("ChannelIndex")
               for x in ac.findall(".//SecondaryContentItem")]
        assert idx == ["0"], f"canal {k}: SecondaryContent.ChannelIndex = {idx}"
