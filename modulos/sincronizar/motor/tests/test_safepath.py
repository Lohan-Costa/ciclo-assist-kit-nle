"""
A fronteira entre "uma string que alguém mandou" e "um arquivo no disco".

O caminho de mídia chega, em última instância, do servidor HTTP local — ou seja, de
fora. E as bibliotecas que o recebem não tratam a string como arquivo: o MediaInfo
BUSCA a rede quando há `://` (a libmediainfo embarcada tem o Reader_libcurl), e o
ffmpeg fala http/ftp/concat/subfile. Sem esta fronteira, o app saía fazendo
requisição HTTP a partir da máquina do editor (SSRF) e virava um oráculo do disco.
"""

import pytest

from media.safepath import CaminhoInvalido, ensure_local_file, ff_input


@pytest.mark.parametrize("hostil", [
    "http://10.0.0.5:8080/interno.mov",     # varredura de rede interna
    "https://exemplo.com/x.mov",
    "ftp://exemplo.com/x.mov",
    "concat:a.mov|b.mov",                   # composição de arquivos do ffmpeg
    "subfile:,start,0,end,100,:/etc/passwd",
    "data:audio/wav;base64,AAAA",
    "pipe:0",
])
def test_url_nunca_e_caminho(hostil):
    with pytest.raises(CaminhoInvalido):
        ensure_local_file(hostil)


def test_caminho_do_windows_nao_e_confundido_com_url(tmp_path):
    """`C:\\Users\\…` tem dois-pontos e É um caminho legítimo — a regra é `://`."""
    f = tmp_path / "A001.mov"
    f.write_bytes(b"x")
    # o teste roda no POSIX, então o que se garante aqui é a REGRA, não a plataforma
    from media.safepath import _parece_url
    assert not _parece_url(r"C:\Users\editor\A001.mov")
    assert not _parece_url(str(f))
    assert ensure_local_file(f) == f.resolve()


def test_arquivo_que_nao_existe_e_recusado(tmp_path):
    with pytest.raises(CaminhoInvalido):
        ensure_local_file(tmp_path / "nao_existe.mov")


def test_diretorio_nao_e_arquivo(tmp_path):
    with pytest.raises(CaminhoInvalido):
        ensure_local_file(tmp_path)


@pytest.mark.parametrize("lixo", ["", "   ", None, 42, "x\x00y"])
def test_entrada_degenerada(lixo):
    with pytest.raises(CaminhoInvalido):
        ensure_local_file(lixo)


def test_ff_input_prefixa_file_e_neutraliza_nome_com_hifen(tmp_path):
    """
    Um arquivo chamado `-report.mov` é operando POSICIONAL do ffprobe e seria lido
    como OPÇÃO. O ffmpeg não honra `--` como fim-de-opções; o prefixo `file:` é o
    que resolve, e de quebra fixa o protocolo.
    """
    f = tmp_path / "-report.mov"
    f.write_bytes(b"x")
    saida = ff_input(f)
    # `.startswith("file:/")` era uma suposição só-POSIX: no Windows um caminho
    # absoluto começa com a letra da unidade (`file:C:\...`), sem barra nenhuma
    # depois do prefixo — e é válido: `ffprobe` foi medido lendo esse formato
    # exato (letra de unidade, contrabarra, espaço no caminho, nome com hífen)
    # nesta sessão de Windows. O que importa é o prefixo `file:` em si.
    assert saida.startswith("file:")
    assert not saida.startswith("-")


def test_ff_input_valida_quem_ainda_nao_passou_pelo_portao():
    with pytest.raises(CaminhoInvalido):
        ff_input("http://exemplo.com/x.mov")


# ── Caminhos de SAÍDA ────────────────────────────────────────────────────────
# A validação de entrada cobria só leitura. Os comandos de export recebiam
# `output_path` e escreviam onde mandassem — e um deles ainda criava a árvore de
# diretórios antes. A barreira era o Rust do outro lado; depender só da barreira do
# vizinho é o mesmo erro que deixou o servidor local sem token.

from media.safepath import ensure_output_path


def test_saida_valida_passa(tmp_path):
    alvo = tmp_path / "PROJETO.prproj"
    assert ensure_output_path(alvo, (".prproj",)) == alvo


def test_saida_exige_a_extensao_certa(tmp_path):
    with pytest.raises(CaminhoInvalido):
        ensure_output_path(tmp_path / "PROJETO.drt", (".prproj",))
    # o que a checagem existe para impedir: gravar por cima do que não é export
    for destino in ["settings.json", ".zshrc", "id_rsa", "notas.txt"]:
        with pytest.raises(CaminhoInvalido):
            ensure_output_path(tmp_path / destino, (".prproj",))


def test_saida_exige_pasta_existente(tmp_path):
    # Sem isto, o export FABRICAVA a árvore de diretórios onde mandassem.
    with pytest.raises(CaminhoInvalido):
        ensure_output_path(tmp_path / "nao" / "existe" / "x.prproj", (".prproj",))


def test_saida_precisa_ser_absoluta():
    with pytest.raises(CaminhoInvalido):
        ensure_output_path("relativo/x.prproj", (".prproj",))


@pytest.mark.parametrize("lixo", ["", "   ", None, 42, "http://x/y.prproj", "x\x00.prproj"])
def test_saida_degenerada(lixo):
    with pytest.raises(CaminhoInvalido):
        ensure_output_path(lixo, (".prproj",))


# ── A pegadinha que só um teste com mídia REAL pegou ─────────────────────────
# `ff_input()` (prefixo `file:`) serve ao ffmpeg e QUEBRA o MediaInfo, que trata a
# string inteira como nome de arquivo. Usar o mesmo argumento nos dois derrubou a
# leitura de metadados de TODA mídia — e nenhum teste unitário pegou, porque
# nenhum toca o MediaInfo de verdade. Este teste guarda a REGRA.

def test_ff_input_e_so_para_o_ffmpeg(tmp_path):
    """
    Medido: MediaInfo.parse("file:/x.mov") → FileNotFoundError
            ffprobe          "file:/x.mov" → OK
    Quem chama o MediaInfo passa o caminho CRU; a defesa dele contra SSRF é o
    `ensure_local_file`, não o prefixo.
    """
    import inspect

    from media import inspector

    fonte = inspect.getsource(inspector._probe_uncached)
    assert "MediaInfo.parse(str(fp))" in fonte, (
        "o MediaInfo voltou a receber ff_input() — isso quebra a leitura de "
        "metadados de toda mídia (FileNotFoundError com o caminho prefixado)"
    )
    assert "ensure_local_file" in fonte, "sumiu a validação que protege o MediaInfo"
