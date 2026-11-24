"""O inventário do cache — a leitura que vira a aba Vetores.

⭐ O que estes testes travam é a regra que surpreende quem olha a tela: **uma linha é um
MASTER**, e um take sincronizado mistura dois. Os quadros de um take e a transcrição do
mesmo take saem em linhas DIFERENTES, uma de espécie `imagem` e outra de espécie `som`.
Quem "consertar" isso juntando as duas está desfazendo a chave do cache.
"""

from __future__ import annotations

import json

from cicloassist.midia import cache as C
from cicloassist.midia import estagios as E
from cicloassist.midia import inventario as I

IMAGEM = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.64cedc20.1dc80000.060e2b34.7f7f2a80"
SOM = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.6505f172.1c710000.060e2b34.7f7f2a80"


def midia_de_imagem(raiz, nome="A001_C003", quadros=3, receita=None):
    m = C.Midia(IMAGEM, raiz_do_cache=raiz)
    m.anotar_fonte({"master": nome, "arquivo": "C:/mxf/a.mxf"})
    for i in range(quadros):
        m.guardar_quadro(1000 + i, b"\xff\xd8fake")
    m.registrar_gerador(E.QUADROS, receita or E.assinatura(E.QUADROS))
    return m


def midia_de_som(raiz, nome="A001_C003_SOM", falas=2, receita=None):
    m = C.Midia(SOM, raiz_do_cache=raiz)
    m.anotar_fonte({"master_de_som": nome, "canais": 2})
    m.guardar_transcricao([{"inicio": i, "fim": i + 1, "texto": "oi", "certeza": 0.9}
                           for i in range(falas)])
    m.registrar_gerador(E.TRANSCRICAO, receita or E.assinatura(E.TRANSCRICAO))
    return m


# ── a leitura ────────────────────────────────────────────────────────────────

def test_cache_que_nao_existe_da_lista_vazia(tmp_path):
    """⚠️ É o caso NORMAL do primeiro dia, não um erro: antes da primeira pergunta não há
    pasta nenhuma. Tratar como falha faria a aba nascer quebrada."""
    assert I.listar(tmp_path / "nunca-existiu") == []


def test_uma_midia_de_imagem_vira_uma_linha(tmp_path):
    midia_de_imagem(tmp_path, quadros=4)
    (linha,) = I.listar(tmp_path)

    assert linha.nome == "A001_C003"
    assert linha.especie == "imagem"
    assert linha.visual.tem and linha.visual.quantos == 4
    assert linha.visual.atualizado
    assert linha.visual.modelo == "ffmpeg"
    assert not linha.fala.tem
    assert linha.bytes > 0


def test_uma_midia_de_som_vira_outra_linha(tmp_path):
    midia_de_som(tmp_path, falas=5)
    (linha,) = I.listar(tmp_path)

    assert linha.especie == "som"
    assert linha.fala.tem and linha.fala.quantos == 5
    assert linha.fala.modelo.startswith("faster-whisper")
    assert not linha.visual.tem


def test_imagem_e_som_do_mesmo_take_sao_duas_linhas(tmp_path):
    """⭐⭐ A regra do módulo. V vem da câmera e A vem do gravador: são masters
    diferentes, e o cache é endereçado pelo master. Juntá-los numa linha só exigiria uma
    chave que não existe."""
    midia_de_imagem(tmp_path)
    midia_de_som(tmp_path)

    linhas = I.listar(tmp_path)
    assert len(linhas) == 2
    assert {l.especie for l in linhas} == {"imagem", "som"}
    assert all(l.visual.tem != l.fala.tem for l in linhas)


# ── o que "atualizado" quer dizer ────────────────────────────────────────────

def test_receita_antiga_marca_para_refazer(tmp_path):
    """⭐ É o mesmo mecanismo que fez a transcrição antiga cair sozinha quando as palavras
    entraram — aqui ele vira uma coluna em vez de um efeito invisível."""
    midia_de_som(tmp_path, receita={"motor": "faster-whisper", "modelo": "tiny"})
    (linha,) = I.listar(tmp_path)

    assert linha.fala.tem
    assert not linha.fala.atualizado
    assert linha.fala.modelo == "faster-whisper tiny"


def test_sem_gerador_gravado_nao_conta_como_atualizado(tmp_path):
    """Cache de uma versão anterior à assinatura: há quadros, mas ninguém sabe de que
    receita. ⚠️ "Não sei" tem de cair no lado de refazer, nunca no de pronto."""
    m = C.Midia(IMAGEM, raiz_do_cache=tmp_path)
    m.anotar_fonte({"master": "A001_C003"})
    m.guardar_quadro(10, b"\xff\xd8fake")

    (linha,) = I.listar(tmp_path)
    assert linha.visual.tem
    assert not linha.visual.atualizado


# ── o disco é entrada não confiável ──────────────────────────────────────────

def test_pasta_que_nao_e_chave_e_ignorada(tmp_path):
    """⛔ Uma pasta estranha largada no cache não pode virar linha da tabela — o mesmo
    critério que valida a escrita vale para a leitura (`cache.e_chave`)."""
    midia_de_imagem(tmp_path)
    (tmp_path / "Nova pasta").mkdir()
    (tmp_path / "cabe-de-tudo.txt").write_text("nada", encoding="utf-8")
    (tmp_path / ("z" * 64)).mkdir()

    linhas = I.listar(tmp_path)
    assert [l.chave for l in linhas] == [C.de_umid(IMAGEM)]


def test_json_corrompido_nao_derruba_o_inventario(tmp_path):
    """Cache pela metade vira "não tenho isso", nunca exceção: a lista que dá para montar
    vale mais que um erro sobre a pior linha dela."""
    # ⚠️ Numa pasta de ANTES do manifesto: é só nela que o `fonte.json` ainda é lido.
    antiga = tmp_path / C.de_umid(IMAGEM)
    (antiga / "quadros").mkdir(parents=True)
    (antiga / "quadros" / "00000010.jpg").write_bytes(b"\xff\xd8fake")
    (antiga / "fonte.json").write_text("{isso não é json", encoding="utf-8")

    (linha,) = I.listar(tmp_path)
    assert linha.nome == ""
    # ⭐ Sem `fonte.json` legível, a espécie é deduzida do que há em disco.
    assert linha.especie == "imagem"


def test_transcricao_ilegivel_conta_zero_falas(tmp_path):
    m = midia_de_som(tmp_path)
    (m.pasta / "transcricao.json").write_text("[", encoding="utf-8")

    (linha,) = I.listar(tmp_path)
    assert linha.fala.tem       # o arquivo existe
    assert linha.fala.quantos == 0


# ── a ordem e o resumo ───────────────────────────────────────────────────────

def test_sem_nome_cai_no_fim(tmp_path):
    """Ordenar pelo nome é o que o olho procura; quem não tem nome fica junto no fim, em
    vez de se misturar aos que têm."""
    midia_de_imagem(tmp_path, nome="ZZZ último")
    m = C.Midia(SOM, raiz_do_cache=tmp_path)
    m.guardar_transcricao([{"texto": "oi"}])

    linhas = I.listar(tmp_path)
    assert [l.nome for l in linhas] == ["ZZZ último", ""]


def test_resumo_conta_o_que_o_rodape_mostra(tmp_path):
    midia_de_imagem(tmp_path, quadros=2)
    midia_de_som(tmp_path, receita={"motor": "faster-whisper", "modelo": "tiny"})

    r = I.resumo(I.listar(tmp_path))
    assert r["midias"] == 2
    assert r["com_visual"] == 1
    assert r["com_fala"] == 1
    assert r["desatualizadas"] == 1
    assert r["bytes"] > 0


def test_como_dicionario_leva_o_modelo(tmp_path):
    """⚠️ `modelo` é propriedade, e `asdict` só leva campos. Sem o acréscimo explícito, a
    tela receberia a receita crua e teria de saber montar o nome — lógica de domínio no
    navegador, que é justamente o que este painel não faz."""
    midia_de_som(tmp_path)
    d = I.listar(tmp_path)[0].como_dicionario()

    assert d["fala"]["modelo"].startswith("faster-whisper")
    assert json.dumps(d)        # atravessa o JSON sem tipo estranho no meio


# ── a união com o acervo ─────────────────────────────────────────────────────

def clipe(chave, nome="A001_C003", tracks=None, arquivos=("a.mxf",)):
    return {chave: {"chave": chave, "nome": nome,
                    "tracks": tracks or {"video": 1, "audio": 2},
                    "arquivos": list(arquivos), "bytes": 999}}


def test_a_duracao_e_o_bruto_chegam_para_a_conta_de_tempo(tmp_path):
    """⭐⭐ O que a tela precisa para dizer QUANTO TEMPO a micro vai levar antes do clique.

    São duas populações: quem já teve os cortes procurados entra pelo número REAL de
    trechos (e o `cortes.json` diz se é bruto ou montado); quem não teve entra pela
    DURAÇÃO, e aí bruto e montado mudam a conta em ~6× — por isso `bruto` é `None`, e não
    `False`. ⚠️ Duração ausente é zero, e a tela conta essa mídia à parte em vez de somar
    zero por ela.
    """
    midia_de_imagem(tmp_path)
    achado = clipe(C.de_umid(IMAGEM))
    achado[C.de_umid(IMAGEM)]["duracao_s"] = 252.0
    (linha,) = I.listar(tmp_path, clipes=achado)

    assert linha.duracao_s == 252.0
    # Sem `cortes.json`: ninguém procurou, e a tela não pode escolher bruto nem montado.
    assert linha.micro == {"trechos": 0, "feitos": 0, "bruto": None}


def test_sem_varredura_a_duracao_sai_dos_cortes(tmp_path):
    """⭐ A mídia que o produto processou mas nenhuma varredura de disco alcançou: os
    cortes contaram os quadros um a um, e é de lá que a duração sai."""
    m = midia_de_imagem(tmp_path)
    from cicloassist.midia import cortes as K
    (m.pasta / K.ARQUIVO).write_text(json.dumps({
        "quadros": 600, "taxa": "24000/1001", "bruto": True,
        "trechos": [{"inicio": 0, "fim": 600, "entrada": "inicio", "movimento": 1.0}],
    }), encoding="utf-8")
    m.registrar_gerador("cortes", K.ASSINATURA)

    (linha,) = I.listar(tmp_path)
    assert 25.0 < linha.duracao_s < 25.1        # 600 / 23,976
    assert linha.micro == {"trechos": 1, "feitos": 0, "bruto": True}


def test_midia_do_acervo_sem_cache_entra_como_falta(tmp_path):
    """⭐⭐ A união é a tabela: sozinho, o cache responde "o que já analisei"; sozinha, a
    varredura responde "o que existe". É a soma que faz a coluna vazia querer dizer
    "falta fazer" em vez de "não sei"."""
    linhas = I.listar(tmp_path, clipes=clipe(C.de_umid(IMAGEM), "SEM CACHE"))

    (linha,) = linhas
    assert linha.nome == "SEM CACHE"
    assert linha.no_acervo and linha.arquivos == 1
    assert not linha.visual.tem and not linha.fala.tem
    assert linha.especie == "imagem e som"


def test_o_nome_do_cache_ganha_do_nome_da_varredura(tmp_path):
    """O `fonte.json` foi escrito com a mídia em mãos e é o nome que o editor viu na
    conversa; o da varredura entra quando o produto ainda não tocou nesta mídia."""
    midia_de_imagem(tmp_path, nome="O QUE O PRODUTO VIU")
    linhas = I.listar(tmp_path, clipes=clipe(C.de_umid(IMAGEM), "o que o ffprobe leu"))
    assert linhas[0].nome == "O QUE O PRODUTO VIU"


def test_as_tracks_do_arquivo_decidem_a_especie(tmp_path):
    """⭐ Aqui está a resposta para a estranheza da tabela: uma diária de câmera é UM
    master com vídeo e áudio; um take sincronizado são DOIS masters."""
    midia_de_som(tmp_path)
    linhas = I.listar(tmp_path, clipes=clipe(C.de_umid(SOM), tracks={"audio": 2}))
    assert linhas[0].especie == "som"


def test_resumo_conta_o_que_falta(tmp_path):
    midia_de_imagem(tmp_path)
    linhas = I.listar(tmp_path, clipes=clipe(C.de_umid(SOM), "nunca analisada"))

    r = I.resumo(linhas)
    assert r["midias"] == 2
    assert r["sem_analise"] == 1
    assert r["no_acervo"] == 1


def test_chave_torta_vinda_do_acervo_e_ignorada(tmp_path):
    """⛔ O que vem de um JSON em disco é entrada não confiável como qualquer outra."""
    assert I.listar(tmp_path, clipes={"nao-e-chave": {"nome": "x"}}) == []


# ── as receitas ──────────────────────────────────────────────────────────────

def test_a_assinatura_da_transcricao_soma_asr_e_mixagem(tmp_path):
    """⛔ Mudar a taxa de amostragem sem invalidar a transcrição entregaria texto feito de
    outro áudio. As duas receitas somam numa só."""
    a = E.assinatura(E.TRANSCRICAO)
    assert a["motor"] == "faster-whisper"
    assert a["taxa"] == 16000


def test_estagio_desconhecido_e_erro(tmp_path):
    """Estágio inventado não pode devolver `{}` — isso faria tudo parecer atualizado."""
    try:
        E.assinatura("astrologia")
    except KeyError:
        return
    raise AssertionError("estágio desconhecido devia estourar")


def test_a_sombra_do_macos_nao_conta_como_quadro(tmp_path):
    """⛔ MEDIDO no macOS (2026-09-14): em exFAT cada arquivo gravado ganha um `._` ao lado
    na hora, e 3 quadros apareciam como 6 na aba Vetores."""
    from cicloassist.midia import inventario

    for nome in ("00000100.jpg", "00000200.jpg"):
        (tmp_path / nome).write_bytes(b"12345")
        (tmp_path / f"._{nome}").write_bytes(b"x" * 4096)
    (tmp_path / ".DS_Store").write_bytes(b"x" * 100)
    assert inventario._medir(tmp_path) == (10, 2)
