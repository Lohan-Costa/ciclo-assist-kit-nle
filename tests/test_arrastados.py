"""O que o editor arrastou — e a porta que isso abre no disco dele.

⛔⛔ **Este é um teste de SEGURANÇA, não de conveniência.** `ler_arquivo` e `ver_imagem`
recebem um caminho escrito pelo modelo; sem a lista de autorizados, elas seriam acesso ao
disco do cliente por uma frase de texto (ADR 0005). O gesto do editor é a permissão, e
ela vale para o arquivo que ele arrastou — não para a pasta, não para o padrão, não para
o disco.
"""

from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

import pytest

from cicloassist.mcp.ferramentas import arquivos as F
from cicloassist.servico import arrastados as A


@pytest.fixture(autouse=True)
def lista_limpa():
    A.esquecer_tudo()
    yield
    A.esquecer_tudo()


@pytest.fixture
def roteiro(tmp_path):
    p = tmp_path / "cena07.txt"
    p.write_text("CENA 7 — CONSULTÓRIO\n\nPERSONAGEM-F\nSobe comigo.\n", encoding="utf-8")
    return p


# ── a porta fechada ──────────────────────────────────────────────────────────

def test_sem_arrastar_nao_le(roteiro):
    """⛔ O caminho existe, o formato é legível, e mesmo assim não passa."""
    r = F.ler_arquivo(caminho=str(roteiro))
    assert "erro" in r
    assert "arrastou" in r["erro"]


def test_a_recusa_ensina_o_modelo_a_parar(roteiro):
    """⭐ Um "acesso negado" seco faria o modelo tentar outra grafia, outra pasta — e cada
    tentativa é um turno da assinatura do editor gasto numa porta que não vai abrir."""
    erro = F.ler_arquivo(caminho=str(roteiro))["erro"]
    assert "Não tente outros caminhos" in erro


def test_arrastar_um_nao_abre_a_pasta(tmp_path, roteiro):
    """⛔ Uma autorização não é recursiva: o vizinho de pasta continua fechado."""
    vizinho = tmp_path / "outro.txt"
    vizinho.write_text("segredo", encoding="utf-8")
    A.autorizar(roteiro)

    assert "erro" not in F.ler_arquivo(caminho=str(roteiro))
    assert "erro" in F.ler_arquivo(caminho=str(vizinho))


def test_a_pasta_arrastada_nao_autoriza_o_conteudo(tmp_path, roteiro):
    A.autorizar(tmp_path)
    assert "erro" in F.ler_arquivo(caminho=str(roteiro))


def test_nao_escapa_por_caminho_relativo(tmp_path, roteiro):
    """⚠️ `pasta/../cena07.txt` é o mesmo arquivo, e `resolve()` é quem garante isso nos
    dois sentidos — inclusive para não deixar passar o que não foi autorizado."""
    A.autorizar(roteiro)
    disfarcado = tmp_path / "sub" / ".." / "cena07.txt"
    assert A.autorizado(disfarcado)

    outro = tmp_path / "sub" / ".." / "nao-arrastado.txt"
    assert not A.autorizado(outro)


def test_maiusculas_e_barras_nao_enganam(tmp_path, roteiro):
    """⚠️ No Windows `D:\\X` e `d:/x` são o mesmo arquivo. Sem normalizar, o editor
    arrastaria e a ferramenta recusaria o que ele acabou de autorizar."""
    A.autorizar(roteiro)
    assert A.autorizado(str(roteiro).upper().replace("\\", "/"))


# ── a porta aberta ───────────────────────────────────────────────────────────

def test_o_que_foi_arrastado_e_lido(roteiro):
    A.autorizar(roteiro)
    r = F.ler_arquivo(caminho=str(roteiro))
    assert "Sobe comigo" in r["texto"]
    assert r["arquivo"] == "cena07.txt"
    assert r["fonte"] == "roteiro"


def test_formato_que_nao_se_le_diz_o_que_fazer(tmp_path):
    pdf = tmp_path / "roteiro.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    A.autorizar(pdf)
    erro = F.ler_arquivo(caminho=str(pdf))["erro"]
    assert "versão em texto" in erro     # o caminho de saída, não só a recusa


def test_arquivo_grande_demais_e_recusado(tmp_path, monkeypatch):
    grande = tmp_path / "coisa.txt"
    grande.write_text("x" * 500, encoding="utf-8")
    A.autorizar(grande)
    monkeypatch.setattr(A, "TETO_DE_TEXTO", 100)
    assert "grande demais" in F.ler_arquivo(caminho=str(grande))["erro"]


def test_texto_em_outra_codificacao_nao_derruba(tmp_path):
    """⚠️ Um roteiro exportado de Windows antigo vem em cp1252. Um acento torto é melhor
    que a ferramenta inteira falhando."""
    velho = tmp_path / "antigo.txt"
    velho.write_bytes("CENA 7 — CONSULTÓRIO".encode("cp1252"))
    A.autorizar(velho)
    r = F.ler_arquivo(caminho=str(velho))
    assert "erro" not in r
    assert "CENA 7" in r["texto"]


# ── a imagem ─────────────────────────────────────────────────────────────────

def test_imagem_nao_arrastada_nao_e_vista(tmp_path):
    foto = tmp_path / "personagem f.jpg"
    foto.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 100)
    blocos = F.ver_imagem(caminho=str(foto))
    assert blocos[0]["type"] == "text"
    assert "permissão" in blocos[0]["text"]


def test_imagem_arrastada_vira_bloco_de_imagem(tmp_path):
    foto = tmp_path / "personagem f.jpg"
    foto.write_bytes(b"\xff\xd8\xff\xe0" + b"0" * 100)
    A.autorizar(foto)
    blocos = F.ver_imagem(caminho=str(foto))
    # ⚠️ O texto vem ANTES da imagem: sem ele o modelo recebe uma foto solta e não sabe
    #    de onde veio nem por que está olhando para ela.
    assert blocos[0]["type"] == "text"
    assert "personagem f.jpg" in blocos[0]["text"]
    assert blocos[1]["type"] == "image"
    assert blocos[1]["mimeType"] == "image/jpeg"


# ── o que o painel recebe de volta ───────────────────────────────────────────

def test_o_arrasto_diz_na_hora_o_que_serve(tmp_path, roteiro):
    """⭐ O problema aparece no chip, no gesto — não depois de um turno gasto."""
    assert A.autorizar(roteiro)["legivel"] is True
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF")
    assert A.autorizar(pdf)["legivel"] is False
    assert A.autorizar(tmp_path)["pasta"] is True
    assert A.autorizar(tmp_path / "sumiu.txt")["existe"] is False


def test_o_material_do_conform_leva_o_papel_e_nao_o_defeito(tmp_path):
    """⭐ Pilotado em 2026-10-29: o `.prproj`, o `.mov` e a pasta das mídias saíam em âmbar
    ("não sei ler este formato", "é uma pasta") — e eram o que `conformar_no_resolve` usa."""
    for nome, esperado in (("corte.prproj", "projeto"), ("x.AAF", "projeto"),
                           ("ref.mov", "referência"), ("roteiro.txt", ""), ("x.pdf", "")):
        (tmp_path / nome).write_bytes(b"x")
        assert A.autorizar(tmp_path / nome)["papel"] == esperado, nome
    assert A.autorizar(tmp_path)["papel"] == "mídias"
    assert A.autorizar(tmp_path / "sumiu.prproj")["papel"] == ""


def test_arquivo_protegido_do_windows_nao_derruba_a_rota():
    """⚠️⚠️ MEDIDO: `Path.exists()` LEVANTA `PermissionError` em
    `C:\\Windows\\System32\\config\\SAM` — não devolve `False`. Sem tratar, arrastar um
    arquivo de sistema derrubava a rota inteira com 500, e o painel dizia "não consegui
    falar com o serviço" para algo cuja resposta certa era "não sei ler isso"."""
    r = A.autorizar(r"C:\Windows\System32\config\SAM")
    assert r["existe"] is False
    assert r["legivel"] is False


# ── o anexo que chega pelo CONTEÚDO (o arrasto de fora no Premiere) ──────────

def test_anexo_pelo_conteudo_fica_legivel_e_autorizado(tmp_path):
    """⛔⛔ No CEP não há caminho: sem isto, o editor arrastava o roteiro e lia
    "não veio nada nesse arrasto" (medido em 2026-09-17)."""
    from cicloassist.servico import arrastados as A

    anexo = A.guardar_conteudo("roteiro cena 7.txt", "PERSONAGEM-F\nSobe comigo.".encode("utf-8"))
    assert anexo["legivel"] and anexo["existe"] and not anexo["pasta"]
    assert A.autorizado(anexo["caminho"])
    assert Path(anexo["caminho"]).read_text(encoding="utf-8").startswith("PERSONAGEM-F")
    assert Path(anexo["caminho"]).parent == A.pasta_dos_anexos()


def test_dois_anexos_de_mesmo_nome_e_conteudo_diferente_convivem():
    from cicloassist.servico import arrastados as A

    um = A.guardar_conteudo("roteiro.txt", b"versao 1")
    dois = A.guardar_conteudo("roteiro.txt", b"versao 2 - outra")
    assert um["caminho"] != dois["caminho"]
    assert A.autorizado(um["caminho"]) and A.autorizado(dois["caminho"])
    # O mesmo conteúdo de novo não cria um terceiro arquivo.
    assert A.guardar_conteudo("roteiro.txt", b"versao 1")["caminho"] == um["caminho"]


@pytest.mark.parametrize("nome, dados, erro", [
    ("take.mxf", b"x", "não sei ler"),
    ("foto.pdf", b"x", "não sei ler"),
    ("sem_extensao", b"x", "não sei ler"),
])
def test_anexo_que_o_produto_nao_le_e_recusado_antes_de_gravar(nome, dados, erro):
    from cicloassist.servico import arrastados as A

    with pytest.raises(ValueError, match=erro):
        A.guardar_conteudo(nome, dados)
    assert not A.pasta_dos_anexos().exists() or not list(A.pasta_dos_anexos().iterdir())


def test_nome_hostil_nao_escreve_fora_da_pasta_de_anexos():
    """⛔ O nome vem do drop, que é texto de fora."""
    from cicloassist.servico import arrastados as A

    anexo = A.guardar_conteudo(r"..\..\..\roteiro.txt", b"oi")
    assert Path(anexo["caminho"]).parent == A.pasta_dos_anexos()


def test_anexo_grande_demais_e_recusado():
    from cicloassist.servico import arrastados as A

    with pytest.raises(ValueError, match="teto"):
        A.guardar_conteudo("foto.png", b"\0" * (A.TETO_DE_ANEXO + 1))


def test_nome_comprido_nao_perde_a_extensao_e_continua_legivel():
    """⚠️ O saneador corta em 40 caracteres: com a extensão vindo do nome cortado, um
    roteiro de nome comprido voltava como "não sei ler arquivo sem extensão"."""
    from cicloassist.servico import arrastados as A

    anexo = A.guardar_conteudo("ROTEIRO " + "MUITO COMPRIDO " * 6 + ".txt", b"PERSONAGEM-F")
    assert anexo["legivel"] and anexo["caminho"].endswith(".txt")
    assert A.autorizado(anexo["caminho"])


# ── a rota do anexo pelo conteúdo ────────────────────────────────────────────

def test_a_rota_do_anexo_decodifica_o_nome_e_exige_o_painel():
    from cicloassist.servico import rotas as R
    from cicloassist.servico.http import ROTAS, Pedido

    manipulador, exige_painel = ROTAS[("POST", "/arrastados/conteudo")]
    assert exige_painel  # ⛔ só a nossa página anexa arquivo

    nome = "roteiro cena 7 — açaí.txt"
    pedido = Pedido("POST", "/arrastados/conteudo",
                    {"x-ciclo-nome": quote(nome)}, "PERSONAGEM-F\nOi.".encode("utf-8"))
    resposta = manipulador(pedido)
    dados = json.loads(resposta.corpo)
    assert dados["ok"] and dados["arquivo"]["nome"].endswith("acai.txt") is False
    assert "açaí" in dados["arquivo"]["nome"]
    assert A.autorizado(dados["arquivo"]["caminho"])


def test_a_rota_recusa_sem_nome_ou_sem_conteudo():
    from cicloassist.servico.http import ROTAS, Pedido

    manipulador, _ = ROTAS[("POST", "/arrastados/conteudo")]
    for cabecalhos, corpo in (({}, b"x"), ({"x-ciclo-nome": "a.txt"}, b"")):
        resposta = manipulador(Pedido("POST", "/arrastados/conteudo", cabecalhos, corpo))
        assert resposta.status == 400


def test_a_rota_conta_o_motivo_em_200_para_o_chip_pintar():
    """⚠️ Um 4xx viraria "não consegui falar com o serviço" no painel — e o editor
    procuraria o defeito no lugar errado."""
    from cicloassist.servico.http import ROTAS, Pedido

    manipulador, _ = ROTAS[("POST", "/arrastados/conteudo")]
    resposta = manipulador(Pedido("POST", "/arrastados/conteudo",
                                  {"x-ciclo-nome": "take.mxf"}, b"x"))
    dados = json.loads(resposta.corpo)
    assert resposta.status == 200 and not dados["ok"] and "não sei ler" in dados["erro"]
