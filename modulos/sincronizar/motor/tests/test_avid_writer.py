"""
O writer de `.avb` — só cortes.

Escreve arquivos de verdade num diretório temporário e os LÊ DE VOLTA com o pyavb.
Não há como testar isto sem escrever: o que se está afirmando é a forma de um
arquivo binário que o Media Composer vai abrir.

O que estes testes protegem são as coisas que **não dão erro** — o arquivo abre,
o MC não reclama, e a timeline está errada:

- o CANAL de cada clipe de som (`track_id`), que já saiu errado uma vez e passou
  por uma validação humana de ouvido;
- a cauda de cada track, cuja ausência faz o MC estourar ao navegar além do fim;
- o clamp do OUT contra a duração do master.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import avb
from avid.adapter import SOUND_TRACK_BASE
from avid.writer import AvbWriteError, write_avb

FPS = 23.976
H_A = "060a2b340101010501010f101300000011111111111111111111111111111111"
H_B = "060a2b340101010501010f101300000022222222222222222222222222222222"
H_S = "060a2b340101010501010f101300000033333333333333333333333333333333"
MASTERS = {"a.mov": H_A, "b.mov": H_B, "s.wav": H_S}
# O MobID como a API do Media Composer o devolve (ver avid/mcapi.py).
API_MOB = "060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011e5e7-034e"


def _seg(nome, track, inicio, dur, *, audio=False, slot=None, origem=0):
    s = {"clip_name": nome, "track": track, "timeline_start_frames": inicio,
         "duration_frames": dur, "source_start_frames": origem, "is_audio": audio,
         "mob_id": nome}
    if audio:
        s["source_slot_id"] = slot or 1
    return s


def _ler(caminho):
    """O .avb de volta: {(media_kind, index): [(pos, len, mob_hex, track_id, start)]}."""
    fora = {}
    with avb.open(str(caminho)) as f:
        comps = [m for m in f.content.mobs if m.property_data.get("mob_type_id") == 1]
        assert len(comps) == 1, "deveria haver exatamente uma CompositionMob"
        for c in comps:
            fora["__nome__"] = c.name
            fora["__len__"] = c.length
            for t in c.tracks:
                seq = getattr(t, "component", None)
                if seq is None or not hasattr(seq, "components"):
                    continue
                pos, itens, fim = 0, [], 0
                for x in seq.components:
                    if type(x).__name__ == "SourceClip":
                        itens.append((pos, x.length, x.mob_id.bytes_le.hex(),
                                      x.track_id, x.start_time))
                    pos += x.length
                    fim = pos
                fora[(t.media_kind, t.index)] = itens
                fora[("__fim__", t.media_kind, t.index)] = fim
    return fora


def _mobs_por_tipo(caminho):
    with avb.open(str(caminho)) as f:
        d = {}
        for m in f.content.mobs:
            t = m.property_data.get("mob_type_id")
            d[t] = d.get(t, 0) + 1
        return d


@pytest.fixture
def saida(tmp_path):
    return tmp_path / "timeline.avb"


class TestOModoSoTimeline:
    def test_a_bin_sai_com_UM_objeto_so_a_composicao(self, saida):
        """⭐ O modo do fluxo do plugin: os masters já vivem nas bins do editor, e o
        Avid resolve pelo MobID no banco de mídia. `Find in Bin` leva ao original."""
        segs = [_seg("a.mov", 1, 0, 100)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        assert _mobs_por_tipo(saida) == {1: 1}   # 1 = CompositionMob, e mais nada

    def test_master_ausente_da_bin_NAO_vira_buraco(self, saida):
        """⭐⭐ A armadilha que apagou uma timeline inteira. O writer do RELINKER
        troca `SourceClip` de mob ausente por FILLER — defesa certa lá, desastre
        aqui: no modo só-timeline o master está ausente POR DEFINIÇÃO. 15 clipes
        viraram buraco e a função reportou sucesso."""
        segs = [_seg("a.mov", 1, 0, 100)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        clipes = _ler(saida)[("picture", 1)]
        assert len(clipes) == 1
        assert clipes[0][2] == H_A

    def test_clipe_sem_master_conhecido_e_ERRO_e_nao_silencio(self, saida):
        with pytest.raises(AvbWriteError, match="sem master"):
            write_avb([_seg("fantasma.mov", 1, 0, 100)], FPS, str(saida), "T", MASTERS)


class TestOCanalDoSom:
    def test_o_track_id_e_o_canal_da_fonte(self, saida):
        """⭐⭐ O bug que passou por uma validação humana: o writer antigo derivava o
        canal de um mapa tirado do AAF e, sem AAF, colapsava o canal 2 no 1 — um
        estéreo tocava o canal 1 nas DUAS tracks, e o canal 4 de uma câmera de 4
        nunca era ouvido. Ninguém percebe de ouvido; só lendo o arquivo."""
        segs = [_seg("s.wav", SOUND_TRACK_BASE, 0, 100, audio=True, slot=1),
                _seg("s.wav", SOUND_TRACK_BASE + 1, 0, 100, audio=True, slot=2),
                _seg("b.mov", SOUND_TRACK_BASE + 2, 0, 100, audio=True, slot=3),
                _seg("b.mov", SOUND_TRACK_BASE + 3, 0, 100, audio=True, slot=4)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        d = _ler(saida)
        assert [d[("sound", i)][0][3] for i in (1, 2, 3, 4)] == [1, 2, 3, 4]

    def test_video_ignora_o_canal(self, saida):
        write_avb([_seg("a.mov", 1, 0, 100)], FPS, str(saida), "T", MASTERS)
        assert _ler(saida)[("picture", 1)][0][3] == 1


class TestAFormaQueOMediaComposerExige:
    def test_toda_track_abrange_a_duracao_TOTAL(self, saida):
        """⭐ Sem a cauda, a track termina no último clipe dela e o MC estoura ao
        navegar além do fim (PMM_INSUFFICIENT_MEDIA)."""
        segs = [_seg("a.mov", 1, 0, 100),           # V1 acaba no frame 100
                _seg("b.mov", 2, 0, 900)]           # V2 acaba no 900
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        d = _ler(saida)
        assert d["__len__"] == 900
        for chave in [k for k in d if isinstance(k, tuple) and k[0] == "__fim__"]:
            assert d[chave] == 900, chave

    def test_a_posicao_vira_gap_antes_do_clipe(self, saida):
        segs = [_seg("a.mov", 1, 240, 100)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        assert _ler(saida)[("picture", 1)][0][0] == 240

    def test_composicao_so_de_audio_ganha_uma_V1_vazia(self, saida):
        """Convenção do Avid: uma timeline sem vídeo mesmo assim tem V1."""
        segs = [_seg("s.wav", SOUND_TRACK_BASE, 0, 100, audio=True, slot=1)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        d = _ler(saida)
        assert ("picture", 1) in d
        assert d[("picture", 1)] == []           # existe e está vazia

    def test_indices_de_track_sao_independentes_por_tipo(self, saida):
        segs = [_seg("a.mov", 1, 0, 100), _seg("b.mov", 2, 0, 100),
                _seg("s.wav", SOUND_TRACK_BASE, 0, 100, audio=True, slot=1),
                _seg("s.wav", SOUND_TRACK_BASE + 1, 0, 100, audio=True, slot=2)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        d = _ler(saida)
        assert ("picture", 1) in d and ("picture", 2) in d
        assert ("sound", 1) in d and ("sound", 2) in d

    def test_a_taxa_23_976_nao_vira_24(self, saida):
        """Arredondar a taxa derivaria ~1,7 s numa timeline de 29 min."""
        write_avb([_seg("a.mov", 1, 0, 100)], FPS, str(saida), "T", MASTERS)
        with avb.open(str(saida)) as f:
            c = [m for m in f.content.mobs if m.property_data.get("mob_type_id") == 1][0]
            assert c.edit_rate == 23.976
            tc = [t for t in c.tracks if t.media_kind == "timecode"][0]
            assert tc.component.fps == 24                 # o TC é NOMINAL
            assert tc.component.start == 3600 * 24        # começa em 01:00:00:00

    @pytest.mark.parametrize("fps,er,tc_fps,fmt", [
        (23.976, 23.976, 24, 9),
        (24.0, 24.0, 24, 7),
        (25.0, 25.0, 25, 16),  # 16 MEDIDO no MC 2024.6 (sequência feita à mão, 2026-10-31); o 13 DERRUBAVA o MC (CompressionManager.c 11276)
        (29.97, 29.97, 30, 22),
    ])
    def test_o_codigo_de_FORMATO_sai_certo_por_taxa(self, tmp_path, fps, er, tc_fps, fmt):
        """⭐ O `SEQUERNCE_FORMAT_TYPE` é o que o Media Composer lê como formato do
        projeto, e ele NÃO é derivável da taxa — é uma tabela.

        Este teste existe porque uma mutação sobreviveu: apagar a tabela e cair no
        cálculo por fração dá o MESMO resultado a 23,976, que era a única taxa que
        eu estava testando. A 29,97 os dois caminhos DIVERGEM (22 contra 9), e é lá
        que a tabela ganha sentido. Testar só o material que se tem à mão é como um
        teste passa a não guardar nada.
        """
        saida = tmp_path / f"tl_{fps}.avb"
        write_avb([_seg("a.mov", 1, 0, 100)], fps, str(saida), "T", MASTERS)
        with avb.open(str(saida)) as f:
            c = [m for m in f.content.mobs if m.property_data.get("mob_type_id") == 1][0]
            assert c.edit_rate == er
            assert c.attributes["SEQUERNCE_FORMAT_TYPE"] == fmt
            tc = [t for t in c.tracks if t.media_kind == "timecode"][0]
            assert tc.component.fps == tc_fps


class TestOClampDoOut:
    def test_clipe_alem_do_fim_do_master_e_aparado(self, saida):
        """O master transcodado pode ser 1-2 frames mais curto que o original.
        Referenciar além do fim estoura PMM_INSUFFICIENT_MEDIA no corte."""
        segs = [_seg("a.mov", 1, 0, 500)]
        write_avb(segs, FPS, str(saida), "T", MASTERS, master_lengths={H_A: 480})
        clipes = _ler(saida)[("picture", 1)]
        assert clipes[0][1] == 480

    def test_o_aparo_nao_desloca_o_que_vem_depois(self, saida):
        """A track é sequencial: aparar sem compensar puxaria tudo para trás."""
        segs = [_seg("a.mov", 1, 0, 500), _seg("b.mov", 1, 600, 100)]
        write_avb(segs, FPS, str(saida), "T", MASTERS, master_lengths={H_A: 480})
        clipes = _ler(saida)[("picture", 1)]
        assert [c[0] for c in clipes] == [0, 600]


class TestNenhumMasterSemDuracao:
    """⚠️⚠️ O clamp só funciona se a duração do master for CONHECIDA — e um clipe
    que passa do fim do master faz o Media Composer recusar a timeline inteira com
    `PMM_INSUFFICIENT_MEDIA`, num diálogo modal que trava até a API.

    O caso é COMUM, não exótico: o arquivo original costuma ser **1 frame mais
    longo** que o transcode do Avid. Medido no material real — 5 de 14 masters
    estouravam por exatamente 1 frame.

    Isto aconteceu de verdade: um atalho que passava os MobIDs prontos (para não
    varrer as bins) esqueceu de passar as DURAÇÕES junto, e o clamp ficou sem
    dados. A timeline saiu, abriu, e o Avid a recusou."""

    def _resolver(self, **kw):
        from avid.masters import resolver

        return resolver(["/m/a.mov"], mc=None,
                        mob_ids={"/m/a.mov": API_MOB}, **kw)

    def test_a_duracao_viaja_junto_com_o_mob_id(self):
        ids, duracoes, faltam = self._resolver(mob_lengths={"/m/a.mov": 1236})
        assert faltam == []
        assert duracoes[ids["a.mov"]] == 1236

    def test_sem_a_duracao_o_master_fica_SEM_clamp(self):
        """O que dá errado quando o atalho esquece a duração: o id resolve, o
        writer escreve, e nada avisa até o Media Composer recusar."""
        ids, duracoes, _ = self._resolver()
        assert ids["a.mov"]                      # o master resolveu…
        assert duracoes == {}                    # …e o clamp ficou cego

    def test_o_clamp_apara_exatamente_o_frame_a_mais(self, tmp_path):
        """O caso real: `.mov` de 1237 frames contra um master de 1236."""
        saida = tmp_path / "t.avb"
        h = MASTERS["a.mov"]
        write_avb([_seg("a.mov", 1, 0, 1237)], FPS, str(saida), "T", MASTERS,
                  master_lengths={h: 1236})
        assert _ler(saida)[("picture", 1)][0][1] == 1236


class TestOsErros:
    def test_sobreposicao_na_mesma_track_e_erro(self, saida):
        """O motor de sync resolve colisão pondo a câmera noutra track. Se algo
        chegar sobreposto aqui, um clipe comeria o outro em silêncio."""
        segs = [_seg("a.mov", 1, 0, 200), _seg("b.mov", 1, 100, 200)]
        with pytest.raises(AvbWriteError, match="sobrepostos"):
            write_avb(segs, FPS, str(saida), "T", MASTERS)

    def test_sem_segmentos_e_erro(self, saida):
        with pytest.raises(AvbWriteError):
            write_avb([], FPS, str(saida), "T", MASTERS)


class TestOResumo:
    def test_conta_o_que_escreveu(self, saida):
        segs = [_seg("a.mov", 1, 0, 100), _seg("b.mov", 2, 0, 100),
                _seg("s.wav", SOUND_TRACK_BASE, 0, 100, audio=True, slot=1)]
        r = write_avb(segs, FPS, str(saida), "MINHA TL", MASTERS)
        assert r["name"] == "MINHA TL"
        assert (r["picture_tracks"], r["sound_tracks"], r["clips"]) == (2, 1, 3)
        assert r["only_timeline"] is True
        assert r["length"] == 100


def _monstate(caminho):
    """`{(media_kind, index): _MONSTATE}` — o botão de *monitoring* da timeline."""
    fora = {}
    with avb.open(str(caminho)) as f:
        for c in f.content.mobs:
            if c.property_data.get("mob_type_id") != 1:
                continue
            for t in c.tracks:
                sa = t.property_data.get("session_attr")
                if sa is not None and "_MONSTATE" in sa:
                    fora[(t.media_kind, t.index)] = sa["_MONSTATE"]
    return fora


class TestOMonitorDaTimeline:
    """⭐ A timeline tem de ABRIR mostrando imagem.

    `_MONSTATE` é o botão de *monitoring* de cada track — o que mostra "desta track
    para baixo". Sem ele, a bin abria com NENHUMA track de vídeo monitorada: o
    Composer ficava preto e o editor ligava na V mais alta na mão, toda vez.

    Os valores vieram de uma bin salva pelo próprio Media Composer 25.12
    (2026-08-09), depois de o editor ligar o monitor na V2 de uma timeline que o
    Órbita havia gerado.
    """

    def test_a_track_de_video_mais_alta_sai_monitorada(self, saida):
        # Duas câmeras: V1 e V2. O monitor tem de estar na V2.
        segs = [_seg("a.mov", 1, 0, 100), _seg("b.mov", 2, 0, 100)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        mon = _monstate(saida)
        assert mon[("picture", 1)] == 0
        assert mon[("picture", 2)] == 1

    def test_a_mais_alta_e_a_ULTIMA_e_nao_a_primeira(self, saida):
        # ⚠️ O monitor do Avid é cumulativo PARA BAIXO. Ligá-lo numa track do meio
        # esconderia as câmeras acima dela — o oposto do que se quer.
        segs = [_seg(n, i + 1, 0, 100) for i, n in enumerate(["a.mov", "b.mov"])]
        segs.append(_seg("s.wav", SOUND_TRACK_BASE, 0, 100, audio=True, slot=1))
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        mon = _monstate(saida)
        ligadas = [k for k, v in mon.items() if k[0] == "picture" and v == 1]
        assert ligadas == [("picture", 2)], f"uma só, e a do topo: {mon}"

    def test_uma_camera_so_tambem_sai_monitorada(self, saida):
        write_avb([_seg("a.mov", 1, 0, 100)], FPS, str(saida), "T", MASTERS)
        assert _monstate(saida)[("picture", 1)] == 1

    def test_o_som_nao_e_confundido_com_video(self, saida):
        # `_MONSTATE = 2` no som é OUTRO estado, não "ligado". Se um dia alguém
        # uniformizar os dois, o áudio do Avid muda de comportamento.
        segs = [_seg("a.mov", 1, 0, 100),
                _seg("s.wav", SOUND_TRACK_BASE, 0, 100, audio=True, slot=1)]
        write_avb(segs, FPS, str(saida), "T", MASTERS)
        mon = _monstate(saida)
        assert mon[("picture", 1)] == 1
        # As tracks de som são renumeradas a partir de 1 na composição.
        assert mon[("sound", 1)] == 2
