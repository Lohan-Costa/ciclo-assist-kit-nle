"""
Clipe de VÁRIOS ARQUIVOS — a mídia gerenciada do Avid entrando no motor.

Até aqui um clipe era um arquivo. No MXF OP-Atom o vídeo e cada canal de áudio são
arquivos SEPARADOS, e a suposição quebrava em silêncio: a regra que separa câmera
de som é "tem fps → câmera", e um arquivo de áudio OP-Atom não tem fps — cada canal
de cada câmera entraria como um gravador de som direto próprio. Nada falha; a
diária sai errada.

O que estes testes guardam:

- o AGRUPAMENTO acontece antes de o motor ver a lista, e é IDEMPOTENTE;
- os fatos de ÁUDIO vêm do arquivo de áudio, e os de VÍDEO continuam vindo do
  arquivo de vídeo — em especial fps e timecode, que NÃO podem ser sobrescritos;
- um clipe sem `audio_path` continua exatamente como sempre foi.

A parte que toca disco usa a fixture de 540 probes reais (a mesma de
`test_opatom.py`), servida no lugar do `ffprobe`.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from media import opatom
from sync.engine import _com_audio_de

FIXTURE = Path(__file__).parent / "fixtures" / "opatom_probes.json"


@pytest.fixture
def probes_reais(monkeypatch):
    """Serve os probes congelados no lugar do `ffprobe`. Devolve os caminhos."""
    docs = json.loads(FIXTURE.read_text(encoding="utf-8"))
    por_caminho = {d["path"]: d["doc"] for d in docs}
    monkeypatch.setattr(opatom, "probe_file", lambda p, timeout=30: por_caminho.get(p))
    return list(por_caminho)


class TestOAgrupamentoAntesDoMotor:
    def test_arquivos_soltos_viram_um_clipe_por_grupo(self, probes_reais):
        entradas = [{"path": p, "group_id": "CAM", "group_order": i}
                    for i, p in enumerate(probes_reais)]
        saida = opatom.colapsar_entradas(entradas)
        assert len(entradas) == 540
        assert len(saida) == 111

    def test_o_clipe_aponta_para_o_VIDEO_e_o_audio_para_o_irmao(self, probes_reais):
        """`path` é o arquivo de vídeo — é ele que tem fps, timecode e duração, e é
        ele que o NLE referencia. `audio_path` é o guia de sync."""
        entradas = [{"path": p, "group_id": "CAM"} for p in probes_reais]
        saida = opatom.colapsar_entradas(entradas)
        com_video = [e for e in saida if "V01" in Path(e["path"]).name]
        assert com_video, "nenhum clipe de vídeo reunido"
        for e in com_video[:5]:
            assert e["audio_path"] != e["path"]
            assert "A0" in Path(e["audio_path"]).name

    def test_clipe_sem_video_e_marcado_como_SOM(self, probes_reais):
        entradas = [{"path": p, "group_id": "X"} for p in probes_reais]
        saida = opatom.colapsar_entradas(entradas)
        sons = [e for e in saida if e.get("kind") == "sound"]
        assert sons
        for e in sons:
            assert "V01" not in Path(e["path"]).name

    def test_o_grupo_declarado_por_quem_chamou_e_PRESERVADO(self, probes_reais):
        """Quem agrupa câmeras é a interface, não este módulo — ele não tem
        opinião sobre isso."""
        entradas = [{"path": p, "group_id": "MINHA CAM", "group_order": 7}
                    for p in probes_reais]
        saida = opatom.colapsar_entradas(entradas)
        assert all(e["group_id"] == "MINHA CAM" for e in saida)

    def test_COLAPSAR_DUAS_VEZES_NAO_MUDA_NADA(self, probes_reais):
        """⭐ O motor colapsa por conta própria. Se quem chamou já tinha colapsado,
        a segunda volta veria UM arquivo por clipe e devolveria um som estéreo como
        MONO — sem erro nenhum, só com um canal a menos na timeline. Aconteceu."""
        entradas = [{"path": p, "group_id": "X"} for p in probes_reais]
        uma = opatom.colapsar_entradas(entradas)
        duas = opatom.colapsar_entradas(uma)
        assert uma == duas

    def test_o_que_nao_e_mxf_passa_intacto(self, probes_reais):
        entradas = [{"path": "/m/camera.mov", "group_id": "A"},
                    {"path": "/m/som.wav", "group_id": "B", "kind": "sound"}]
        assert opatom.colapsar_entradas(entradas) == entradas

    def test_mxf_que_NAO_e_opatom_segue_como_arquivo_solto(self, monkeypatch):
        """Um `.mxf` de câmera (XDCAM, X-OCN) não é OP-Atom e não deve ser tocado."""
        monkeypatch.setattr(opatom, "probe_file", lambda p, timeout=30: {
            "format": {"tags": {"operational_pattern_ul":
                                "060e2b34.04010101.0d010201.01010900"}},
            "streams": [{"index": 0, "codec_type": "video"}]})
        e = [{"path": "/m/sony.mxf", "group_id": "A"}]
        assert opatom.colapsar_entradas(e) == e

    def test_a_contagem_de_canais_e_a_do_CLIPE_e_nao_a_do_arquivo(self, probes_reais):
        """Cada arquivo OP-Atom de áudio é MONO. O que importa para a timeline é
        quantos canais o clipe tem — 4, numa câmera de 4 canais."""
        entradas = [{"path": p, "group_id": "X"} for p in probes_reais]
        saida = opatom.colapsar_entradas(entradas)
        canais = {e.get("audio_channels") for e in saida if e.get("audio_channels")}
        assert canais - {1} , "nenhum clipe multicanal reunido"
        assert max(canais) >= 4


class TestOsMetadadosCompostos:
    """`_com_audio_de` — o probe do arquivo de vídeo não sabe nada de som."""

    VIDEO = {"fps": 23.976, "tc_start": "23:16:47:11", "duration_ms": 51000.0,
             "has_audio": False, "width": 1920}
    AUDIO = {"fps": None, "tc_start": "01:00:00:00", "duration_ms": 51000.0,
             "has_audio": True, "sample_rate": 48000, "channels": 1,
             "total_audio_channels": 1}

    def test_o_audio_deixa_de_ser_falso(self):
        """⭐ Sem isto o clipe seria recusado como não-sincronizável, EM SILÊNCIO —
        porque um vídeo mudo é uma coisa perfeitamente possível."""
        m = _com_audio_de(self.VIDEO, self.AUDIO)
        assert m["has_audio"] is True
        assert m["sample_rate"] == 48000

    def test_o_RELOGIO_do_video_NAO_e_sobrescrito(self):
        """⭐⭐ Um OP-Atom de áudio traz timecode PRÓPRIO. Deixá-lo entrar trocaria
        o relógio do clipe por outro — a classe de erro mais cara deste projeto."""
        m = _com_audio_de(self.VIDEO, self.AUDIO)
        assert m["tc_start"] == "23:16:47:11"
        assert m["fps"] == 23.976

    def test_o_que_descreve_o_video_fica(self):
        m = _com_audio_de(self.VIDEO, self.AUDIO)
        assert m["width"] == 1920
        assert m["duration_ms"] == 51000.0

    def test_o_total_de_canais_pode_ser_declarado_por_quem_chamou(self):
        """O probe do arquivo de áudio só enxerga o canal DELE; quem sabe quantos
        arquivos formam o clipe é quem os reuniu."""
        m = _com_audio_de(self.VIDEO, self.AUDIO, canais=4)
        assert m["channels"] == 4
        assert m["total_audio_channels"] == 4

    def test_nao_muta_a_entrada(self):
        v = dict(self.VIDEO)
        _com_audio_de(v, self.AUDIO, canais=4)
        assert v == self.VIDEO


class TestOClipeDeUmArquivoSoContinuaIgual:
    def test_sem_audio_path_o_audio_vem_do_proprio_arquivo(self):
        """O caso de sempre — 99% da mídia — não pode ter mudado."""
        from sync.engine import _Clip, _Sound

        c = _Clip(Path("/m/a.mov"), {"fps": 24.0, "duration_ms": 1000},
                  "g", 0, 24.0)
        assert c.audio_path == c.path
        s = _Sound(Path("/m/s.wav"), {"duration_ms": 1000})
        assert s.audio_path == s.path

    def test_com_audio_path_o_clipe_continua_sendo_o_video(self):
        from sync.engine import _Clip

        c = _Clip(Path("/m/V01.mxf"), {"fps": 24.0, "duration_ms": 1000},
                  "g", 0, 24.0, audio_path=Path("/m/A01.mxf"))
        assert c.path == Path("/m/V01.mxf")        # é o que o NLE referencia
        assert c.audio_path == Path("/m/A01.mxf")  # é de onde se lê a onda
