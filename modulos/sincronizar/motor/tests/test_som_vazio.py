"""
O WAV de 44 bytes — o arquivo que existe e não tem áudio.

Um gravador de campo que começa e para no mesmo instante deixa em disco um WAV só
com o cabeçalho: `data` de tamanho zero. É um arquivo VÁLIDO — o probe lê sample
rate e canais —, então ele passava por todos os filtros do motor. A extração
devolvia zero amostras e o `np.max` derrubava o sync inteiro com

    ValueError: zero-size array to reduction operation maximum which has no identity

que é verdadeira e inútil: numa pasta com dezenas de arquivos, o editor não tinha
como saber qual era o culpado. Visto em material real (`hl-2024-10-25/08-37-20.wav`).
"""

import struct

import numpy as np
import pytest

from media.audio import normalize, peak_abs


def wav_vazio(destino):
    """Um WAV de 44 bytes: cabeçalho válido, chunk `data` com tamanho ZERO.
    É byte a byte o que o gravador de campo produziu no material real."""
    destino.write_bytes(
        b"RIFF" + struct.pack("<I", 36) + b"WAVEfmt " + struct.pack("<I", 16)
        + struct.pack("<HHIIHH", 1, 1, 48000, 144000, 3, 24)
        + b"data" + struct.pack("<I", 0)
    )
    return destino


def test_o_arquivo_de_teste_tem_mesmo_44_bytes(tmp_path):
    assert wav_vazio(tmp_path / "08-37-20.wav").stat().st_size == 44


def test_normalize_nao_explode_com_array_vazia():
    vazio = np.array([], dtype=np.float32)
    out = normalize(vazio)          # antes: ValueError do numpy
    assert out.size == 0


def test_peak_de_array_vazia_e_zero():
    assert peak_abs(np.array([], dtype=np.float32)) == 0.0


def test_normalize_continua_normalizando_de_verdade():
    # A guarda não pode ter mudado o comportamento no caso normal.
    pcm = np.array([0.0, 0.25, -0.5], dtype=np.float32)
    assert np.isclose(peak_abs(normalize(pcm)), 1.0)
    # E silêncio continua virando zeros do mesmo tamanho.
    silencio = np.zeros(10, dtype=np.float32)
    assert normalize(silencio).shape == silencio.shape


def _probe_falso(mapa):
    """Substitui o probe: devolve o metadado que o teste declarar, sem tocar em disco."""
    def _p(path):
        return mapa[str(path)]
    return _p


def test_motor_recusa_com_MENSAGEM_LEGIVEL_quando_todo_som_e_vazio(monkeypatch):
    """
    Era aqui que o sync morria com o texto do numpy. Agora tem de morrer dizendo
    QUAL arquivo está vazio — que é a única informação que resolve o problema.
    """
    from sync import engine

    cam = "/x/A005_A001.mov"
    som = "/x/hl-2024-10-25/08-37-20.wav"
    monkeypatch.setattr(engine, "probe", _probe_falso({
        cam: {"fps": 23.976, "duration_ms": 60000.0, "has_audio": True, "total_audio_channels": 2},
        # o WAV de 44 bytes: canais e sample rate lidos, duração NENHUMA
        som: {"fps": None, "duration_ms": None, "has_audio": True, "sample_rate": 48000,
              "total_audio_channels": 1},
    }))

    with pytest.raises(ValueError) as e:
        engine.run([
            {"path": cam, "group_id": "cam", "group_order": 0},
            {"path": som, "kind": "sound"},
        ])

    msg = str(e.value)
    assert "zero-size" not in msg, "voltou a vazar o jargão do numpy"
    assert "08-37-20.wav" in msg, "a mensagem tem de NOMEAR o arquivo culpado"
    assert "não têm áudio gravado" in msg


def test_som_vazio_e_apenas_IGNORADO_quando_ha_outro_som_bom(monkeypatch):
    """Um arquivo vazio no meio de dezenas não pode derrubar a diária: ele sai da
    lista, o motor avisa qual foi, e o sync continua com o resto."""
    from sync import engine

    cam, bom, vazio = "/x/A005.mov", "/x/09-02-38.wav", "/x/08-37-20.wav"
    monkeypatch.setattr(engine, "probe", _probe_falso({
        cam:   {"fps": 23.976, "duration_ms": 60000.0, "has_audio": True, "total_audio_channels": 2},
        bom:   {"fps": None, "duration_ms": 540000.0, "has_audio": True, "sample_rate": 48000,
                "total_audio_channels": 2},
        vazio: {"fps": None, "duration_ms": None, "has_audio": True, "sample_rate": 48000,
                "total_audio_channels": 1},
    }))
    msgs = []
    # O sync de verdade vai adiante e falha ao ler os arquivos (que não existem);
    # o que se garante aqui é o AVISO, emitido antes de qualquer leitura.
    with pytest.raises(Exception):
        engine.run(
            [{"path": cam, "group_id": "cam", "group_order": 0},
             {"path": bom, "kind": "sound"},
             {"path": vazio, "kind": "sound"}],
            progress=lambda msg, *a, **k: msgs.append(msg),
        )

    aviso = [m for m in msgs if "sem áudio gravado" in m]
    assert aviso, f"nenhum aviso sobre o som vazio. Mensagens: {msgs[:6]}"
    assert "08-37-20.wav" in aviso[0]
    assert "09-02-38.wav" not in aviso[0], "o som BOM não podia ser descartado junto"
