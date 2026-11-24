"""Cada editor tem o SEU banco, e eles só se cruzam ao processar.

⭐⭐ **Decisão do editor, 2026-09-21**, depois de usar a busca dentro do Premiere:

    *"O banco do Premiere nunca pré-carrega o material de cache do Avid. Quando eu
    importo uma mídia no Premiere e peço para processar, é aí que o cruzamento acontece:
    se houver match, a nova entrada não vai processar os arquivos, vai copiar as
    informações do que já existe. A busca no Premiere nunca deve mostrar ou se referenciar
    a alguma coisa do Media Composer, e nenhum arquivo da Avid MediaFiles pode ser exibido
    na lista."*

⛔⛔ **O que vazava, e por que filtro nenhum resolvia.** O casamento por conteúdo criava um
APELIDO: as duas mídias viravam UMA pasta. MEDIDO no projeto dele —
`B001_03150112_C001.mp4` resolvia para a entrada `B001_03150112_C001`, cujo nome é o da
bin do Avid e cujos arquivos são três OP-Atom em `D:/Avid MediaFiles/…`. **A entrada ERA a
do Avid**, e nenhum recorte por projeto muda isso.

⭐ O casamento continua valendo — o que mudou é a consequência dele.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cicloassist.avid import escopo as ESC
from cicloassist.midia import cache as C
from cicloassist.midia import identidade as I

JPEG = bytes.fromhex("ffd8") + b"jpeg"


@pytest.fixture(autouse=True)
def cache_limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    C._indices.clear()
    I.esquecer()
    yield
    C._indices.clear()
    I.esquecer()


def _nascer(chave: str, origem: str = "", **rotulo) -> C.Midia:
    m = C.Midia(chave, origem=origem, rotulo=rotulo)
    m.pasta  # noqa: B018 — nascer é escrever
    return m


# ── a entrada declara de que editor é ────────────────────────────────────────

def test_entrada_sem_origem_declarada_e_do_avid():
    """⚠️ As 332 mídias desta máquina nasceram todas no Avid, e nenhuma tem o campo.
    Inventar "desconhecido" faria a busca do Avid perder o próprio acervo."""
    m = _nascer("a" * 64, nome="veio de antes")
    assert m.origem == "avid"
    assert "origem" in m.manifesto(), "quem nasce agora declara"


@pytest.mark.parametrize("pedida,esperada", [
    ("premiere", "premiere"), ("avid", "avid"),
    ("PREMIERE", "premiere"), ("resolve", "avid"), ("", "avid"), (None, "avid"),
])
def test_a_origem_e_normalizada(pedida, esperada):
    assert C.origem_valida(pedida) == esperada


def test_chaves_da_origem_separa_os_bancos_e_leva_os_apelidos():
    do_avid = _nascer("a" * 64, nome="DA BIN")
    minha = _nascer("b" * 64, origem="premiere", nome="meu.mp4")
    # ⚠️ Apelido DENTRO do banco continua valendo: é o `mob_id` que o Avid gera a cada
    #    link, e a impressão do conteúdo do mesmo arquivo.
    minha.apelidar("c" * 64, "conteudo")
    do_avid.apelidar("d" * 64, "mob_id")

    assert C.chaves_da_origem("premiere") == {"b" * 64, "c" * 64}
    assert C.chaves_da_origem("avid") == {"a" * 64, "d" * 64}


# ── o apelido não atravessa banco ────────────────────────────────────────────

def test_apelido_de_outro_banco_nao_sequestra_a_chave():
    """⛔⛔ Era isto que fazia a entrada "nova" do Premiere cair na pasta do Avid — e
    `copiar_de` copiar a pasta sobre si mesma (`WinError 32` em cada quadro, medido)."""
    do_avid = _nascer("a" * 64, nome="DA BIN")
    do_avid.apelidar("e" * 64, "conteudo", medida=0.99)

    # Sem pedir banco, o apelido resolve — é o comportamento de sempre, dentro do Avid.
    assert C.Midia("e" * 64).chave == "a" * 64
    # ⛔ Pedindo o banco do Premiere, a chave continua CRUA.
    minha = C.Midia("e" * 64, origem="premiere")
    assert minha.chave == "e" * 64 and not minha.existe


def test_desapelidar_tira_do_manifesto_e_do_indice():
    """⚠️ Tirar apelido não apaga quadro, vetor nem transcrição: o pior que acontece é o
    casamento ser medido de novo, e isso custa segundos."""
    m = _nascer("a" * 64, nome="X")
    m.guardar_quadro(10, JPEG)
    m.apelidar("f" * 64, "conteudo", medida=0.99)
    assert C.Midia("f" * 64).chave == "a" * 64

    assert m.desapelidar("f" * 64) is True
    assert m.desapelidar("f" * 64) is False, "tirar duas vezes não é erro, é nada"
    C._indices.clear()
    assert C.Midia("f" * 64).chave == "f" * 64
    assert m.tem_quadro(10), "o trabalho fica"


# ── o cruzamento: cria entrada própria e COPIA ──────────────────────────────

def _com_trabalho(chave: str, **rotulo) -> C.Midia:
    m = _nascer(chave, nome=rotulo.pop("nome", "DO AVID"), **rotulo)
    m.guardar_quadro(36, JPEG)
    m.guardar_transcricao([{"texto": "ola", "inicio": 0.0, "fim": 1.0}])
    # ⭐ A nota do MATERIAL INTEIRO (a que atravessa) e uma de take, escrita numa conversa
    #   do Avid sobre um SUBCLIPE dele (a que não atravessa).
    m.anotar({"descricao": "um plano", "escopo": "midia", "trecho": "a002_03170703_c003",
              "confianca": "inferido", "fonte": "visual"})
    m.anotar({"descricao": "close de Personagem F", "trecho": "C07_P03-T001",
              "inicio_frames": 100, "confianca": "inferido", "fonte": "visual"})
    # ⭐ E a decupagem MICRO: nota de TRECHO do master, a coisa mais cara do cache em tempo
    #   de gente (~50 s de Mac cada). Ela atravessa, com a chave reescrita.
    m.anotar({"descricao": "ela abre a porta", "escopo": "trecho", "inicio_frames": 480,
              "inicio_s": 20.0, "fim_s": 30.0, "trecho": "DO AVID · trecho 480",
              "confianca": "inferido", "fonte": "visual"})
    m.arquivo("cortes.json").write_text('{"trechos": [{"inicio": 480, "fim": 720}]}',
                                        encoding="utf-8")
    m.registrar_gerador("cortes", {"versao": 1})
    m.arquivo("vetores.npy").write_bytes(b"vetor")
    m.arquivo("vetores.json").write_text('{"posicoes": [36]}', encoding="utf-8")
    m.registrar_gerador("quadros", {"largura": 768})
    m.registrar_gerador("transcricao", {"modelo": "de-mentira"})
    m.registrar_gerador("vetores", {"modelo": "mobilenet"})
    # ⛔ O `audio.wav` é 96% do cache e é REGENERÁVEL: não atravessa.
    m.audio.write_bytes(b"RIFF" + b"\0" * 2000)
    return m


def test_aproveitar_cria_entrada_propria_e_copia_o_trabalho(tmp_path, monkeypatch):
    arquivo = tmp_path / "meu.mp4"
    arquivo.write_bytes(b"x" * 100)
    par = _com_trabalho("a" * 64, nome="DA BIN DO AVID")

    monkeypatch.setattr(I, "achar", lambda *a, **k: I.Achado(
        par, "outro_banco", par.chave, "umid", medida=0.998))
    monkeypatch.setattr(I, "sondar", lambda a: {"tipo": "video", "duracao_s": 3.0,
                                                "fps": "24000/1001"})

    r = I.aproveitar(arquivo, "premiere")
    minha = r.midia

    assert minha.chave != par.chave and minha.origem == "premiere"
    assert [Path(a).name for a in minha.manifesto()["arquivos"]] == ["meu.mp4"]
    assert r.aproveitou and r.de is par

    # ⭐ O trabalho atravessou, inteiro.
    assert minha.tem_quadro(36)
    assert len(minha.ler_transcricao()) == 1
    # ⛔⛔ Só o master atravessa (decisão do editor, 2026-09-22): subclipe e multicam são
    #    de cada software. E o título do cartão sai do `trecho`: com o nome da bin do Avid
    #    ali, a busca do Premiere mostrava `a002_03170703_C003` e `C07_P03-T001`.
    notas = minha.ler_notas()
    (nota,) = [n for n in notas if n["escopo"] == "midia"]
    assert nota["trecho"] == minha.nome and nota["copiada_de"] == "avid"
    assert "C07_P03-T001" not in json.dumps(notas, ensure_ascii=False)
    # ⭐⭐ A decupagem MICRO atravessa: ela descreve o MASTER, em quadros do master, e cada
    #    nota custou ~50 s de Mac. Sem isto o banco novo refazia horas em silêncio.
    (micro,) = [n for n in notas if n["escopo"] == "trecho"]
    assert micro["inicio_frames"] == 480
    # ⛔ E com a chave reescrita no formato de `micro.chave_do_trecho`: com o nome do outro
    #   banco, uma micro refeita aqui gravaria uma SEGUNDA nota do mesmo trecho.
    assert micro["trecho"] == f"{minha.nome} · trecho 480"
    # ⛔ Os cortes vão junto (e a receita deles): são eles que dizem quais são os trechos.
    assert "cortes.json" in minha.manifesto()["aproveitado_de"]["copiados"]
    assert not minha.precisa_refazer("cortes", {"versao": 1})
    assert minha.arquivo("vetores.npy").read_bytes() == b"vetor"
    # ⛔ E a RECEITA junto: sem ela `precisa_refazer` compara contra {} e a fila refaz tudo.
    assert minha.ler_gerador("transcricao") == {"modelo": "de-mentira"}
    assert not minha.precisa_refazer("quadros", {"largura": 768})

    # ⛔⛔ O `audio.wav` NÃO atravessa: 1.994 MB de 2.079 no cache real (96%), e é
    #    regenerável do arquivo deste banco.
    assert not minha.audio.is_file()

    # ⭐ E a procedência diz de quem veio, com a medida — regra da casa.
    de = minha.manifesto()["aproveitado_de"]
    assert de["chave"] == par.chave and de["origem"] == "avid"
    assert de["confianca"] == "confirmado" and float(de["medida"]) == 0.998
    assert "quadros" in de["copiados"] and "transcricao.json" in de["copiados"]


def test_o_casamento_e_registrado_mesmo_sem_nada_a_copiar(tmp_path, monkeypatch):
    """⚠️ Gravar só quando copia esconderia POR QUE esta entrada nasceu — que é a
    pergunta de quem for auditar."""
    arquivo = tmp_path / "meu.mp4"
    arquivo.write_bytes(b"x" * 100)
    par = _nascer("a" * 64, nome="SEM TRABALHO")

    monkeypatch.setattr(I, "achar", lambda *a, **k: I.Achado(
        par, "outro_banco", par.chave, "umid", medida=0.97))
    monkeypatch.setattr(I, "sondar", lambda a: {"tipo": "video"})

    r = I.aproveitar(arquivo, "premiere")
    assert not r.aproveitou
    de = r.midia.manifesto()["aproveitado_de"]
    assert de["chave"] == par.chave and de["copiados"] == []


def test_aproveitar_duas_vezes_nao_duplica(tmp_path, monkeypatch):
    arquivo = tmp_path / "meu.mp4"
    arquivo.write_bytes(b"x" * 100)
    par = _com_trabalho("a" * 64)
    monkeypatch.setattr(I, "sondar", lambda a: {"tipo": "video"})
    monkeypatch.setattr(I, "achar", lambda *a, **k: I.Achado(
        par, "outro_banco", par.chave, "umid", medida=0.99))

    primeira = I.aproveitar(arquivo, "premiere").midia
    # ⭐ Na segunda a entrada já existe: nem mede, nem copia de novo.
    monkeypatch.setattr(I, "achar", lambda *a, **k: pytest.fail("não devia medir de novo"))
    segunda = I.aproveitar(arquivo, "premiere")
    assert segunda.midia.chave == primeira.chave and not segunda.aproveitou
    assert len([m for m in C.todas() if m.origem == "premiere"]) == 1


def test_achar_nao_apelida_entre_bancos(tmp_path, monkeypatch):
    """⛔⛔ O apelido faz as duas mídias virarem UMA — e é exatamente o vazamento."""
    arquivo = tmp_path / "meu.mp4"
    arquivo.write_bytes(b"x" * 100)
    par = _nascer("a" * 64, nome="DO AVID")

    monkeypatch.setattr(I, "chave_do_arquivo", lambda a: ("b" * 64, "conteudo"))
    monkeypatch.setattr(I, "sondar", lambda a: {"tipo": "video"})
    monkeypatch.setattr(I, "candidatos", lambda *a, **k: [(par, [arquivo])])
    monkeypatch.setattr(I, "_conferir", lambda *a: (0.99, 0.95, "visual"))

    achado = I.achar(arquivo, origem="premiere")
    assert achado.como == "outro_banco"
    assert par.apelidos() == [], "nada de apelido atravessando banco"

    # ⭐ E dentro do MESMO banco o apelido continua sendo criado: é o que faz o AMA do
    #   Avid achar o próprio transcode sem remedir.
    achado = I.achar(arquivo, origem="avid")
    assert achado.como == "convertido"
    assert [a["chave"] for a in par.apelidos()] == ["b" * 64]


# ── o que a tela NUNCA pode dizer ────────────────────────────────────────────

def test_nenhum_aviso_do_premiere_cita_o_media_composer():
    """⛔ Pedido do editor, textual: *"nenhuma mensagem 'esse processo foi feito/está no
    media composer' pode aparecer"*."""
    casos = [
        ESC.Escopo(chaves=frozenset({"a" * 64}), projeto="D:/p/X.prproj",
                   origem="projeto", editor="premiere"),
        ESC.Escopo(chaves=frozenset({"a" * 64}), origem="sem-projeto", editor="premiere"),
        ESC.Escopo(chaves=frozenset(), origem="sem-projeto", editor="premiere"),
    ]
    for e in casos:
        assert "Media Composer" not in e.aviso
        assert "Avid" not in e.aviso


def test_banco_vazio_diz_que_falta_processar_e_nao_que_nao_achou():
    """⛔⛔ "Não achei" sobre um banco vazio se lê como "seu material não tem isso" — é o
    defeito que este produto mais persegue."""
    vazio = ESC.Escopo(chaves=frozenset(), origem="sem-projeto", editor="premiere")
    assert "Importe a mídia" in vazio.aviso and "processar" in vazio.aviso
