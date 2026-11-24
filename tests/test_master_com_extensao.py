"""O master de som com a EXTENSÃO no nome acha os OP-Atom dele.

⛔⛔ Medido em 2026-11-01, no fluxo inteiro pelo chat: desde que o
`som_direto_gerenciado` passou a nomear o master como o MC faz ao linkar
(`M06_SOMDIRETO_T01_WAV-BWF.wav`), o `resolver_take` dizia "não achei mídia no
acervo local" — o arquivo é `M06_SOMDIRETO_T01_WAV-BWF_A01.mxf`, sem `.wav`.
"""

from cicloassist.avid import take


def test_master_com_wav_no_nome_acha_os_canais(tmp_path, monkeypatch):
    pasta = tmp_path / "202611011"
    pasta.mkdir()
    for n in ("A01", "A02"):
        (pasta / f"M06_SOMDIRETO_T01_WAV-BWF_{n}.mxf").write_bytes(b"")
    (pasta / "M06_SOMDIRETO_T02_WAV-BWF_A01.mxf").write_bytes(b"")
    monkeypatch.setattr(take, "raizes_de_midia", lambda: [tmp_path])

    achados = take.arquivos_do_master("M06_SOMDIRETO_T01_WAV-BWF.wav", esperados=2)

    assert [p.name for p in achados] == [
        "M06_SOMDIRETO_T01_WAV-BWF_A01.mxf", "M06_SOMDIRETO_T01_WAV-BWF_A02.mxf"]


def test_sem_extensao_continua_como_antes(tmp_path, monkeypatch):
    (tmp_path / "1").mkdir()
    (tmp_path / "1" / "C001.mxf").write_bytes(b"")
    (tmp_path / "1" / "C001_A01.mxf").write_bytes(b"")
    monkeypatch.setattr(take, "raizes_de_midia", lambda: [tmp_path])

    assert [p.name for p in take.arquivos_do_master("C001")] == ["C001.mxf", "C001_A01.mxf"]
