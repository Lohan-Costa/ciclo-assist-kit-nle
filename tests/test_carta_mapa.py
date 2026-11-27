"""O CONFORM PELO MAPA (plano 2026-11-26, etapa 3): o Conformar pergunta de que ORIGINAL é cada offline, e a Carta
responde pelo que registrou — sem varrer pasta; o que ela não souber com certeza segue o casamento de sempre.

O lado do núcleo (`cicloassist/carta/mapa.py`); o do Conformar (o encaixe no relink) está em
`modulos/conformar/tests/test_mapa_da_carta.py`."""
from __future__ import annotations

from cicloassist.carta import anexar, mapa, projeto, referencias, relacoes
from cicloassist.midia import identidade as _id

def _carta(tmp_path, nome="PROD"):
    raiz = tmp_path / nome
    raiz.mkdir()
    return projeto.novo(raiz, nome, "24000/1001")


def _par(tmp_path, proj, nome="A001", tam_o=1000, tam_p=500):
    """Original + proxy com o manifesto da conversão, registrados como o anexar os registra."""
    orig = tmp_path / f"ORIG_{proj.nome}" / f"{nome}.mov"
    orig.parent.mkdir(exist_ok=True)
    orig.write_bytes(b"o" * tam_o)
    _, ref = referencias.criar(proj, "", nome, {"nome_da_fonte": nome, "tipo": "video"}, {"nle": "teste"})
    anexar._vincular(proj, ref["id"], "original", orig, "teste", anexar.Conta())
    pasta = tmp_path / f"PROXY_{proj.nome}"
    pasta.mkdir(exist_ok=True)
    conv = pasta / f"{nome}_proxy.mov"
    conv.write_bytes(b"p" * tam_p)
    relacoes.escrever_manifesto(pasta, [{"original": {"arquivo": str(orig), "largura": 3840, "altura": 2160,
                                                      "impressao": _id.impressao(orig)},
                                         "convertido": {"arquivo": str(conv), "largura": 1920, "altura": 1080,
                                                        "impressao": _id.impressao(conv)}}], "resolve_proxy")
    relacoes.registrar_do_manifesto(proj, pasta, "trabalho")
    return ref["id"], orig, conv


def test_o_proxy_da_timeline_acha_o_original_pelo_mapa(tmp_path):
    proj = _carta(tmp_path)
    midia, orig, conv = _par(tmp_path, proj)
    r = mapa.consultar([str(proj.raiz)], [{"chave": "M1", "nome": "A001", "origem": str(conv)},
                                          {"chave": "M2", "nome": "X", "origem": str(tmp_path / "nao_existe.mov")}])
    a = r["achados"]["M1"]
    assert (a["arquivo"], a["midia"], a["forma_do_offline"], a["por"]) == (str(orig), midia, "trabalho", "caminho")
    assert a["transformacao"]["enquadramento"]["fator"] == 0.5 and "escala 0.5" in a["frase"]
    assert "M2" not in r["achados"] and r["alertas"] == [] and r["cartas"] == 1


def test_o_proxy_movido_fora_do_nosso_controle_vai_pela_impressao(tmp_path):
    proj = _carta(tmp_path)
    _, orig, conv = _par(tmp_path, proj)
    movido = tmp_path / "OUTRA PASTA" / "renomeado.mov"
    movido.parent.mkdir()
    conv.rename(movido)
    a = mapa.consultar([str(proj.raiz)], [{"chave": "M1", "origem": str(movido)}])["achados"]["M1"]
    assert a["arquivo"] == str(orig) and a["por"] == "impressao" and "impressão" in a["frase"]


def test_o_arquivo_trocado_no_lugar_nao_vale_e_e_dito(tmp_path):
    proj = _carta(tmp_path)
    _, orig, conv = _par(tmp_path, proj)
    conv.write_bytes(b"x" * 777)                                       # outro conteúdo (outro tamanho) no mesmo caminho
    r = mapa.consultar([str(proj.raiz)], [{"chave": "M1", "nome": "A001", "origem": str(conv)}])
    assert r["achados"] == {} and "impressão não confere" in r["alertas"][0]["motivo"]
    _, orig2, conv2 = _par(tmp_path, proj, "B001")
    orig2.write_bytes(b"y" * 1234)                                     # o ORIGINAL mudou desde o registro
    r = mapa.consultar([str(proj.raiz)], [{"chave": "M2", "origem": str(conv2)}])
    assert r["achados"] == {} and "mudou desde o registro" in r["alertas"][0]["motivo"]


def test_duas_cartas_com_originais_diferentes_e_empate_do_editor(tmp_path):
    p1, p2 = _carta(tmp_path, "UM"), _carta(tmp_path, "DOIS")
    _, _, conv = _par(tmp_path, p1)
    # a segunda Carta registrou o MESMO proxy como forma de trabalho de outro original
    orig_b = tmp_path / "ORIG_B" / "A001.mov"
    orig_b.parent.mkdir()
    orig_b.write_bytes(b"b" * 900)
    _, ref = referencias.criar(p2, "", "A001", {"nome_da_fonte": "A001", "tipo": "video"}, {"nle": "teste"})
    anexar._vincular(p2, ref["id"], "original", orig_b, "teste", anexar.Conta())
    anexar._vincular(p2, ref["id"], "trabalho", conv, "teste", anexar.Conta())
    r = mapa.consultar([str(p1.raiz), str(p2.raiz)], [{"chave": "M1", "nome": "A001", "origem": str(conv)}])
    assert r["achados"] == {} and "discordam" in r["alertas"][0]["motivo"]

