"""A Carta Aberta, núcleo da C1 (plano `docs/plano/2026-11-11-carta-aberta.md` §4): projeto, diário, referências,
quarentena, mandar e anexar."""

from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from cicloassist.carta import anexar, diario, projeto, referencias
from cicloassist.carta.projeto import CartaErro


@pytest.fixture
def proj(tmp_path):
    raiz = tmp_path / "PROJETO X"
    raiz.mkdir()
    return projeto.novo(raiz, "Projeto X", "24000/1001")


# ── o projeto ──────────────────────────────────────────────────────────────────

def test_novo_exige_pasta_que_existe_e_nao_cria_outras(tmp_path):
    with pytest.raises(CartaErro, match="não existe"):
        projeto.novo(tmp_path / "nao_existe", "X", "25")
    raiz = tmp_path / "R"
    raiz.mkdir()
    p = projeto.novo(raiz, "X", "25")
    assert sorted(x.name for x in raiz.iterdir()) == [".carta"]          # só a nossa pasta
    assert p.nome == "X" and projeto.abrir(raiz).taxa == "25"
    with pytest.raises(CartaErro, match="já é um projeto"):
        projeto.novo(raiz, "X", "25")


def test_abrir_o_que_nao_e_projeto(tmp_path):
    with pytest.raises(CartaErro, match="não é um projeto"):
        projeto.abrir(tmp_path)


def test_maquina_so_letras_numeros_e_hifen():
    m = projeto.maquina()
    assert m and all(c.isalnum() or c == "-" for c in m) and m == m.upper()


# ── o diário ───────────────────────────────────────────────────────────────────

def test_diario_soma_e_desfaz_com_linha_nova(proj):
    a = diario.acrescentar(proj, {"fato": "forma", "midia": "m1", "forma": "trabalho", "arquivo": "/x/a.mp4"})
    diario.acrescentar(proj, {"fato": "forma", "midia": "m1", "forma": "trabalho", "arquivo": "/x/a.mov"},
                       quem="EDITOR2-WIN")
    assert len(diario.formas(proj)["m1"]) == 2                 # duas formas de trabalho: sem conflito
    diario.acrescentar(proj, {"fato": "tirar", "vinculo": a["id"]})
    vivos = diario.formas(proj)["m1"]
    assert [f["arquivo"] for f in vivos] == ["/x/a.mov"]
    assert len(diario.fatos(proj)) == 3                         # nada foi apagado


def test_diario_pula_linha_cortada(proj):
    diario.acrescentar(proj, {"fato": "forma", "midia": "m1", "forma": "avid", "arquivo": "/a"})
    with open(proj.registro / f"{projeto.maquina()}.jsonl", "a", encoding="utf-8") as f:
        f.write('{"fato": "forma", "midia": "m2", "for')     # outra máquina no meio da escrita
    assert list(diario.formas(proj)) == ["m1"]


def _escrever_muito(raiz: str, quem: str, n: int) -> None:
    p = projeto.abrir(raiz)
    for i in range(n):
        diario.acrescentar(p, {"fato": "forma", "midia": f"{quem}-{i}", "forma": "trabalho",
                               "arquivo": "/" + "x" * 300})


@pytest.mark.parametrize("mesmo_arquivo", [False, True])
def test_dois_processos_ao_mesmo_tempo_nao_perdem_nada(proj, mesmo_arquivo):
    """O pronto da C1: dois processos anexando ao mesmo tempo. Cada máquina tem o seu arquivo; e mesmo dois
    processos no MESMO arquivo (mesma máquina) não misturam linhas — uma linha é um `os.write` em `O_APPEND`."""
    nomes = ("MESMA", "MESMA") if mesmo_arquivo else ("A", "B")
    ps = [multiprocessing.Process(target=_escrever_muito, args=(str(proj.raiz), q, 300)) for q in nomes]
    for p in ps:
        p.start()
    for p in ps:
        p.join(60)
    assert len(diario.fatos(proj)) == 600


# ── as referências ─────────────────────────────────────────────────────────────

IDENT = {"nome_da_fonte": "A002_C003", "tipo": "video", "tc": "03:14:14:17", "fps": "24000/1001", "quadros": 5480}


def test_referencia_idempotente_e_sem_sobrescrever(proj):
    (proj.raiz / "Diarias" / "D01").mkdir(parents=True)
    p1, d1 = referencias.criar(proj, "Diarias/D01", "A002_C003", IDENT, {"nle": "avid", "forma": "avid"})
    p2, d2 = referencias.criar(proj, "Diarias/D01", "A002_C003", IDENT, {"nle": "avid", "forma": "avid"})
    assert p1 == p2 and d1["id"] == d2["id"]
    outro = {**IDENT, "tc": "05:00:00:00"}
    p3, d3 = referencias.criar(proj, "Diarias/D01", "A002_C003", outro, {"nle": "avid", "forma": "avid"})
    assert p3.name == "A002_C003 (2).ref.json" and d3["id"] != d1["id"]


def test_referencia_pede_pasta_existente_e_dentro_do_projeto(proj):
    with pytest.raises(CartaErro, match="não existe"):
        referencias.criar(proj, "Diarias/D09", "x", IDENT, {})
    with pytest.raises(CartaErro, match="fora do projeto"):
        referencias.criar(proj, "..", "x", IDENT, {})


def test_editor_move_a_referencia_e_ela_continua(proj):
    (proj.raiz / "D01").mkdir()
    (proj.raiz / "Outra").mkdir()
    p, d = referencias.criar(proj, "D01", "A002_C003", IDENT, {})
    shutil.move(str(p), str(proj.raiz / "Outra" / "renomeada.ref.json"))
    assert [x["id"] for _, x in referencias.todas(proj)] == [d["id"]]


def test_onde_no_mac(monkeypatch):
    import posixpath
    monkeypatch.setattr(referencias.sys, "platform", "darwin")
    # ⚠️ fingir o Mac por INTEIRO: no Windows o `abspath` faz de `/Volumes/…` um `D:\Volumes\…` (medido, 12/11)
    monkeypatch.setattr(referencias.os.path, "abspath", posixpath.abspath)
    o = referencias.onde("/Volumes/SSD/MIDIAS/x.mp4")
    assert (o["volume"], o["relativo"]) == ("SSD", "MIDIAS/x.mp4")


# ── a quarentena ───────────────────────────────────────────────────────────────

def test_quarentena(proj):
    d = proj.raiz / "Diarias"
    d.mkdir()
    (d / "video.mp4").write_bytes(b"x")                      # mídia solta: não é nossa
    (d / "._video.mp4").write_bytes(b"x")                    # sombra do macOS: ignorada
    (d / ".DS_Store").write_bytes(b"x")
    (d / "a.ref.json").write_text("{}")
    (d / "outra.ref.json.parcial").write_text("{")          # outra máquina gravando agora
    velho = d / "abandonado.ref.json.parcial"
    velho.write_text("{")
    os.utime(velho, (time.time() - 3 * 86400,) * 2)
    (proj.raiz / "Vazia").mkdir()
    movidos = {de.name: para for de, para in projeto.quarentena(proj)}
    assert set(movidos) == {"video.mp4", "abandonado.ref.json.parcial"}
    assert movidos["video.mp4"].relative_to(proj.raiz).parts[0] == "Quarentena"
    assert movidos["video.mp4"].parts[-2:] == ("Diarias", "video.mp4")
    assert (d / "._video.mp4").exists() and (d / "a.ref.json").exists() and (d / "outra.ref.json.parcial").exists()
    assert (proj.raiz / "Vazia").is_dir()
    assert not (proj.raiz / ".carta" / "projeto.json").parent.joinpath("x").exists()
    assert projeto.quarentena(proj) == []                     # a quarentena não é varrida de novo


# ── mandar e anexar (mídia de verdade, gerada pelo ffmpeg) ─────────────────────

def _video(caminho, tc, segundos=2, fps="24000/1001"):
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"testsrc2=s=320x180:r={fps}:d={segundos}",
                    "-timecode", tc, "-c:v", "mpeg4", str(caminho)], check=True)


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_mandar_e_anexar(proj, tmp_path):
    (proj.raiz / "D01").mkdir()
    avid, trab, outro = tmp_path / "MXF", tmp_path / "MP4", tmp_path / "MP4B"
    for p in (avid, trab, outro):
        p.mkdir()
    _video(avid / "A001_C001.mov", "10:00:00:00")
    _video(avid / "A001_C002.mov", "11:00:00:00")
    _video(trab / "A001_C001.mp4", "10:00:00:00")
    _video(trab / "A001_C002.mp4", "11:00:00:05")             # TC diferente: não é o mesmo material
    _video(trab / "SOBRA.mp4", "12:00:00:00")
    c = anexar.mandar_arquivos(proj, "D01", sorted(avid.iterdir()), "avid", "avid")
    assert sorted(c.novas) == ["A001_C001", "A001_C002"] and len(c.vinculos) == 2
    c2 = anexar.mandar_arquivos(proj, "D01", sorted(avid.iterdir()), "avid", "avid")
    assert sorted(c2.ja_estavam) == ["A001_C001", "A001_C002"] and c2.vinculos == []   # sem duplicar

    c3 = anexar.anexar(proj, trab, "trabalho")
    assert c3.vinculos == ["A001_C001.mp4 → trabalho"]
    assert sorted(c3.sem_par) == ["A001_C002.mp4", "SOBRA.mp4"]

    # o MESMO nome em duas subpastas (duas conversões) → empate, que é do editor; uma cópia RENOMEADA não é candidata
    for sub in ("v1", "v2"):
        (outro / sub).mkdir()
        _video(outro / sub / "A001_C001.mp4", "10:00:00:00")
    shutil.copy(outro / "v1" / "A001_C001.mp4", outro / "A001_C001_copia.mp4")
    c4 = anexar.anexar(proj, outro, "trabalho")
    assert c4.vinculos == [] and list(c4.empates) == ["A001_C001"]

    formas = diario.formas(proj)
    por_nome = {d["nome"]: formas.get(d["id"], []) for _, d in referencias.todas(proj)}
    assert sorted(f["forma"] for f in por_nome["A001_C001"]) == ["avid", "trabalho"]
    assert [f["forma"] for f in por_nome["A001_C002"]] == ["avid"]
    json.dumps(formas)                                         # tudo serializável


# ── as rotas (C1; a janela é a C2) ─────────────────────────────────────────────

def _post(fn, corpo):
    from cicloassist.servico.http import Pedido
    return json.loads(fn(Pedido("POST", "/carta", {}, json.dumps(corpo).encode())).corpo)


def test_rotas_da_carta(tmp_path, monkeypatch):
    from cicloassist.servico import rotas_carta as R
    from cicloassist.servico import seletor
    from cicloassist.servico.http import ROTAS
    for c in ("/carta/novo", "/carta/abrir", "/carta/estado", "/carta/mandar", "/carta/anexar"):
        assert ROTAS[("POST", c)][1], f"{c}: quem age passa pelo porteiro"
    raiz = tmp_path / "PROJ"
    raiz.mkdir()
    escolha = [str(raiz)]
    monkeypatch.setattr(seletor, "escolher", lambda *a, **k: list(escolha))

    # ⛔ antes de abrir pelo seletor, a raiz não vale — mesmo sendo um projeto
    assert not _post(R.rota_carta_estado, {"raiz": str(raiz)})["ok"]
    r = _post(R.rota_carta_novo, {"nome": "Teste", "taxa": "25"})
    assert r["ok"] and r["projeto"]["raiz"] == str(raiz)
    assert _post(R.rota_carta_estado, {"raiz": str(raiz)}) == {"ok": True, "projeto": r["projeto"], "midias": []}
    assert not _post(R.rota_carta_estado, {"raiz": str(tmp_path)})["ok"]     # outra pasta: recusada

    # mandar do Premiere = a SELEÇÃO da bin, pela ponte (aqui, falsa)
    from cicloassist.nle import premiere
    (raiz / "D01").mkdir()
    monkeypatch.setattr(premiere, "selecao", lambda: [{"arquivo": "/nao/existe.mp4"}, {"nome": "seq"}])
    r = _post(R.rota_carta_mandar, {"raiz": str(raiz), "pasta": "D01", "nle": "premiere"})
    assert r["ok"] and list(r["conta"]["ilegiveis"]) == ["existe.mp4"]
    assert r["sem_arquivo"] == ["seq"]                                          # dito, nunca calado
    assert not _post(R.rota_carta_mandar, {"raiz": str(raiz), "pasta": "D01", "nle": "resolve"})["ok"]

    escolha.clear()                                                          # cancelou o seletor
    assert _post(R.rota_carta_anexar, {"raiz": str(raiz), "forma": "trabalho"}) == {"ok": True, "cancelado": True}
    assert not _post(R.rota_carta_anexar, {"raiz": str(raiz), "forma": "outra"})["ok"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_a_mesma_midia_pelos_dois_nles_e_uma_referencia(proj, tmp_path):
    """Mandar pelo Avid e depois pelo Premiere (ou o contrário) acrescenta a FORMA à referência que já existe."""
    (proj.raiz / "D01").mkdir()
    (proj.raiz / "OUTRA").mkdir()
    _video(tmp_path / "A001_C001.mov", "10:00:00:00")
    _video(tmp_path / "A001_C001.mp4", "10:00:00:00")
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C001.mov"], "avid", "avid")
    c = anexar.mandar_arquivos(proj, "OUTRA", [tmp_path / "A001_C001.mp4"], "trabalho", "premiere")
    assert c.novas == [] and c.ja_estavam == ["A001_C001"]
    (d,) = [d for _, d in referencias.todas(proj)]
    assert sorted(f["forma"] for f in diario.formas(proj)[d["id"]]) == ["avid", "trabalho"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_desempate_pelo_conteudo(proj, tmp_path):
    """Dois candidatos com o MESMO nome, TC, taxa e quadros: o pixel decide contra o arquivo que a referência já tem."""
    (proj.raiz / "D01").mkdir()
    _video(tmp_path / "A001_C001.mov", "10:00:00:00")                      # testsrc2
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C001.mov"], "avid", "avid")
    conv = tmp_path / "CONV"
    for sub, fonte in (("certo", "testsrc2"), ("impostor", "smptebars")):
        (conv / sub).mkdir(parents=True)
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", f"{fonte}=s=320x180:r=24000/1001:d=2",
                        "-timecode", "10:00:00:00", "-c:v", "mpeg4", str(conv / sub / "A001_C001.mp4")], check=True)
    c = anexar.anexar(proj, conv, "trabalho")
    assert c.empates == {} and c.vinculos == ["A001_C001.mp4 → trabalho"]
    (f,) = [f for f in next(iter(diario.formas(proj).values())) if f["forma"] == "trabalho"]
    assert "certo" in f["arquivo"] and f["por"] == "conteúdo (visual)" and f["medida"] >= 0.95


def test_o_umid_igual_e_prova_e_o_diferente_nao():
    refs = [{"id": "a", "identidade": {"umid": "AB" * 32}}, {"id": "b", "identidade": {}}]
    assert [d["id"] for d in anexar._pela_chave(refs, {"umid": "ab" * 32})] == ["a"]
    assert anexar._pela_chave(refs, {"umid": "cd" * 32}) == []      # cai para a régua, não reprova
    assert anexar._pela_chave(refs, {"umid": ""}) == []


# ── os itens que juntam mídias (.item.json, §4.6) ──────────────────────────────

def test_item_idempotente_e_so_com_midias_do_projeto(proj):
    from cicloassist.carta import itens
    (proj.raiz / "D01").mkdir()
    _, a = referencias.criar(proj, "D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    _, s = referencias.criar(proj, "D01", "SOM", {"nome_da_fonte": "SOM", "tipo": "audio", "duracao_s": 10.0}, {})
    sync = {"tipo": "sincronizado", "duracao_q": 100, "imagem": {"midia": a["id"], "inicio_q": 0},
            "som": {"midia": s["id"], "inicio_q": 234}}
    p1, d1, novo1 = itens.criar(proj, "D01", "CAM.sync.01", sync, {"nle": "avid"})
    p2, d2, novo2 = itens.criar(proj, "D01", "outro nome", sync, {"nle": "premiere"})   # o MESMO conteúdo
    assert novo1 and not novo2 and p1 == p2 and d1["id"] == d2["id"]
    assert d1["imagem"]["inicio_q"] == 0 and d1["som"]["inicio_q"] == 234             # cada lado o SEU início
    with pytest.raises(CartaErro, match="mande as mídias antes"):
        itens.criar(proj, "D01", "x", {"tipo": "recorte", "midia": "nao-existe", "entrada_q": 0, "saida_q": 1}, {})
    with pytest.raises(CartaErro, match="tipo de item"):
        itens.criar(proj, "D01", "x", {"tipo": "efeito"}, {})
    assert [d["nome"] for _, d in itens.todos(proj)] == ["CAM.sync.01"]


def test_grupo_troca_as_chaves_de_master_pelos_ids():
    from cicloassist.carta import itens
    g = {"tipo": "grupo", "fontes": [{"midia": "m1", "deslocamento_q": 72, "imagem": True},
                                     {"midia": "m2", "deslocamento_q": 0, "imagem": False}],
         "angulo": "m1", "angulo_do_som": "m2"}
    t = itens._trocar_chaves(g, {"m1": "R1", "m2": "R2"})
    assert [f["midia"] for f in t["fontes"]] == ["R1", "R2"] and (t["angulo"], t["angulo_do_som"]) == ("R1", "R2")
    assert itens.midias_de(t) == ["R1", "R2"]


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_mandar_nao_aceita_homonimo(proj, tmp_path):
    """Mesmo nome, TC e duração, OUTRO conteúdo (o caso da G01_CANAIS): o mandar não junta nem cria — é do EDITOR, como
    o empate (decisão do autor, 2026-11-12), com a medida dita."""
    (proj.raiz / "D01").mkdir()
    (tmp_path / "a").mkdir()
    (tmp_path / "b").mkdir()
    _video(tmp_path / "a" / "A001_C001.mov", "10:00:00:00")                 # testsrc2
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "smptebars=s=320x180:r=24000/1001:d=2",
                    "-timecode", "10:00:00:00", "-c:v", "mpeg4", str(tmp_path / "b" / "A001_C001.mp4")], check=True)
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "a" / "A001_C001.mov"], "avid", "avid")
    c = anexar.mandar_arquivos(proj, "D01", [tmp_path / "b" / "A001_C001.mp4"], "trabalho", "premiere")
    assert c.novas == [] and c.ja_estavam == [] and c.vinculos == []
    assert list(c.homonimos) == ["A001_C001"] and list(c.empates) == ["A001_C001"]
    assert "abaixo do piso" in c.empates["A001_C001"][0]
    assert len(referencias.todas(proj)) == 1
    _video(tmp_path / "A001_C001.mp4", "10:00:00:00")                         # o MESMO conteúdo: junta
    c = anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C001.mp4"], "trabalho", "premiere")
    assert c.ja_estavam == ["A001_C001"] and c.homonimos == {}


def _g01_do_premiere(nome="G01 PREMIERE DO EDITOR v02.prproj"):
    """Um `.prproj` do laboratório G01 (o v02 tem um subclipe feito pela API, `G01_CAM3.sub.01`): subindo de pasta até a
    `MIDIAS DE TESTES` (Windows `D:\\`, Mac `/Volumes/SSD/`, a mesma árvore)."""
    from pathlib import Path
    for d in Path(__file__).resolve().parents:
        f = (d / "MIDIAS DE TESTES" / "3 CONJUNTOS DOS APPS" / "_CICLO ASSIST" / "carta_aberta" / nome)
        if f.is_file():
            return f
    return None


def test_subclipe_do_premiere_vira_recorte_com_a_janela_do_avid(proj):
    """MEDIDO (2026-11-12): o subclipe do Premiere é o `StartBoundary`/`EndBoundary` do `MediaSource`, em ticks desde o
    1º quadro do arquivo — 200–400 q no G01, o MESMO recorte do subclipe do Avid (`CARTA ABERTA G01 AVID v01`)."""
    from cicloassist.carta import itens
    prproj = _g01_do_premiere()
    if prproj is None:
        pytest.skip("sem o G01 do laboratório (MIDIAS DE TESTES)")
    p, _, _int = itens._leitor_do_prproj(prproj)
    subs = itens._subclipes(p, _int)
    assert list(subs) == ["G01_CAM3.sub.01"]                       # nenhum master, merged ou multicâmera
    arq = subs["G01_CAM3.sub.01"]["arquivo"]
    assert arq.endswith("G01_CAM3_T01_MOV-PRORES.mov")
    assert itens.arquivos_dos_itens(prproj, {"G01_CAM3.sub.01"}) == [arq]
    (proj.raiz / "G01").mkdir()
    c = itens.do_premiere(proj, "G01", prproj, {"G01_CAM3.sub.01"})
    assert c.sem_referencia == {"G01_CAM3.sub.01": ["G01_CAM3_T01_MOV-PRORES.mov"]}   # a mídia antes do item
    _, ref = referencias.criar(proj, "G01", "G01_CAM3", {"tipo": "video"}, {"nle": "premiere"})
    diario.acrescentar(proj, {"fato": "forma", "midia": ref["id"], "forma": "trabalho", "arquivo": arq,
                              "maquina": diario.maquina(), "por": "teste"})
    c = itens.do_premiere(proj, "G01", prproj, {"G01_CAM3.sub.01"})
    assert c.novos == ["G01_CAM3.sub.01"]
    (_, d), = itens.todos(proj)
    assert (d["tipo"], d["midia"], d["entrada_q"], d["saida_q"]) == ("recorte", ref["id"], 200, 400)
    assert itens.do_premiere(proj, "G01", prproj, {"G01_CAM3.sub.01"}).ja_estavam == ["G01_CAM3.sub.01"]


def test_ticks_por_quadro_da_taxa_do_projeto():
    from cicloassist.carta import itens
    assert itens._ticks_por_quadro("24000/1001") == 10594584000       # o MediaFrameRate do G01 (a forma gravada)
    assert itens._ticks_por_quadro("23.976") == 10594584000
    assert itens._ticks_por_quadro("25") == 10160640000
    assert itens._ticks_por_quadro("x") == 0


@pytest.mark.parametrize("nome,angulo", [("G01 SUBCLIPE v01.prproj", "CAM1"), ("G01 ANGULO v01.prproj", "CAM2")])
def test_angulo_ativo_da_multicamera_do_premiere(proj, nome, angulo):
    """MEDIDO (2026-11-12, 26.0.2 Mac, pilotado): a borda amarela do mosaico no Origem levada ao 2º ângulo e o projeto
    salvo → `Source.Monitor.Multicam.TrackIndex` de 0 para 1 no MasterClip da multicâmera. O ângulo = a fonte da
    trilha de vídeo `TrackIndex + 1`."""
    from cicloassist.carta import itens
    prproj = _g01_do_premiere(nome)
    if prproj is None:
        pytest.skip("sem o G01 do laboratório (MIDIAS DE TESTES)")
    (proj.raiz / "G01").mkdir()
    ids = {}
    arquivos = itens.arquivos_dos_itens(prproj, {"G01-GRUPO-SOM"})
    assert len(arquivos) == len(set(arquivos)) == 4          # A1 e A2 do mesmo WAV: uma vez só
    for a in arquivos:
        _, ref = referencias.criar(proj, "G01", a.rsplit("/", 1)[-1], {"tipo": "x", "arq": a}, {"nle": "premiere"})
        diario.acrescentar(proj, {"fato": "forma", "midia": ref["id"], "forma": "trabalho", "arquivo": a,
                                  "maquina": diario.maquina(), "por": "teste"})
        ids[ref["id"]] = a
    c = itens.do_premiere(proj, "G01", prproj, {"G01-GRUPO-SOM"})
    assert c.novos == ["G01-GRUPO-SOM"]
    (_, d), = itens.todos(proj)
    assert f"G01_{angulo}_" in ids[d["angulo"]] and d["angulo_do_som"] is None
    assert sorted(f["deslocamento_q"] for f in d["fontes"]) == [0, 72, 144, 240]


def test_o_angulo_vigente_e_o_do_ultimo_mandar(proj):
    """Decisão do autor (2026-11-12, b): o grupo já registrado mandado de novo com OUTRO ângulo não vira outro item —
    o ângulo dele passa a ser o novo (um fato `angulo` no diário); `None` (o som da multicâmera do Premiere) mantém."""
    from cicloassist.carta import itens
    (proj.raiz / "G01").mkdir()
    r = [referencias.criar(proj, "G01", f"CAM{i}", {"tipo": "video", "n": i}, {})[1]["id"] for i in (1, 2)]
    grupo = {"tipo": "grupo", "fontes": [{"midia": r[0], "deslocamento_q": 72, "imagem": True},
                                         {"midia": r[1], "deslocamento_q": 0, "imagem": True}]}
    c = itens.ContaItens()
    itens.registrar(proj, "G01", "G", {**grupo, "angulo": r[0], "angulo_do_som": r[0]}, {"nle": "avid"}, c)
    itens.registrar(proj, "G01", "G", {**grupo, "angulo": r[0], "angulo_do_som": None}, {"nle": "premiere"}, c)
    assert c.novos == ["G"] and c.ja_estavam == ["G"] and c.angulos == []          # o mesmo: nenhum fato
    itens.registrar(proj, "G01", "G", {**grupo, "angulo": r[1], "angulo_do_som": None}, {"nle": "premiere"}, c)
    assert c.angulos == ["G"]
    (_, d), = itens.todos(proj)
    assert (d["angulo"], d["angulo_do_som"]) == (r[1], r[0])                        # o som não dito ficou
    itens.registrar(proj, "G01", "G", {**grupo, "angulo": r[0], "angulo_do_som": r[0]}, {"nle": "avid"}, c)
    (_, d), = itens.todos(proj)
    assert d["angulo"] == r[0] and c.angulos == ["G", "G"]
    assert sum(f["fato"] == "angulo" for f in diario.fatos(proj)) == 2


# ── a janela (C2): árvore, conteúdo, nova pasta, revelar ───────────────────────

def test_arvore_so_pastas_do_editor_e_a_contagem_do_direto(proj):
    from cicloassist.carta import vista
    (proj.raiz / "Diarias" / "D01").mkdir(parents=True)
    (proj.raiz / "Diarias" / "D02").mkdir()
    (proj.raiz / "Quarentena" / "2026-11-13").mkdir(parents=True)
    (proj.raiz / ".escondida").mkdir()
    referencias.criar(proj, "Diarias/D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    a = vista.arvore(proj)
    assert [(p["caminho"], p["nivel"], p["n"]) for p in a] == [
        ("", 0, 0), ("Diarias", 1, 0), ("Diarias/D01", 2, 1), ("Diarias/D02", 2, 0)]   # a mãe conta só o DIRETO
    assert a[0]["nome"] == "Projeto X"


def test_nova_pasta_conferida_dentro_do_projeto(proj):
    from cicloassist.carta import vista
    assert vista.nova_pasta(proj, "", "Diarias") == "Diarias"
    assert vista.nova_pasta(proj, "Diarias", "D01") == "Diarias/D01"
    for dentro, nome in (("", "../fora"), ("", "a/b"), ("", ".oculta"), ("", "Quarentena"), ("", "Diarias"),
                         ("../..", "x"), (".carta", "x"), ("", "")):
        with pytest.raises(CartaErro):
            vista.nova_pasta(proj, dentro, nome)
    assert not (proj.raiz.parent / "fora").exists()


def test_conteudo_da_pasta_virtual_e_o_status(proj, tmp_path):
    from cicloassist.carta import itens, vista
    for p in ("Cam", "Som"):
        (proj.raiz / p).mkdir()
    arq = tmp_path / "CAM.mov"
    arq.write_bytes(b"x")
    _, cam = referencias.criar(proj, "Cam", "CAM", {**IDENT, "nome_da_fonte": "CAM", "tc": "10:00:00:00"}, {"nle": "avid"})
    _, som = referencias.criar(proj, "Som", "SOM", {"nome_da_fonte": "SOM", "tipo": "audio", "duracao_s": 125.0}, {})
    diario.acrescentar(proj, {"fato": "forma", "midia": cam["id"], "forma": "trabalho", **referencias.onde(arq),
                              "por": "entrou por aqui"})
    diario.acrescentar(proj, {"fato": "forma", "midia": som["id"], "forma": "trabalho", "arquivo": "/nao/existe.wav",
                              "volume": "DISCO-QUE-NAO-ESTA", "relativo": "x.wav", "maquina": "OUTRA-MAQUINA"})
    itens.criar(proj, "Cam", "CAM.sub.01", {"tipo": "recorte", "midia": cam["id"], "entrada_q": 0, "saida_q": 240}, {})
    linhas = vista.conteudo(proj, ["Cam", "Som"])
    assert [(l["nome"], l["pasta"], l["status"]) for l in linhas] == [
        ("CAM", "Cam", "ok"), ("CAM.sub.01", "Cam", "item"), ("SOM", "Som", "err")]
    cam_l, sub_l, som_l = linhas
    assert cam_l["tipo"] == "vídeo" and cam_l["tc"] == "10:00:00:00" and cam_l["caminhos"][0]["existe"]
    # ⭐ o item tem o SEU TC; duração em hh:mm:ss:ff; a taxa ao lado (autor, 2026-11-13)
    assert sub_l["tipo"] == "subclipe (V)" and sub_l["tc"] == "10:00:00:00" and sub_l["duracao"] == "00:00:10:00"
    assert sub_l["fps"] == "23,976"
    assert som_l["tipo"] == "som" and som_l["duracao"] == "00:02:04:21" and som_l["fps"] == ""   # o som: a taxa do projeto
    assert not som_l["caminhos"][0]["existe"]
    assert vista.conteudo(proj, ["Cam"])[0]["nome"] == "CAM"              # só a pasta pedida
    with pytest.raises(CartaErro):
        vista.conteudo(proj, ["../.."])
    assert vista.caminho_conhecido(proj, str(arq.resolve())) or vista.caminho_conhecido(proj, os.path.abspath(arq))
    assert not vista.caminho_conhecido(proj, "/etc/passwd")


def test_caminho_de_outra_maquina_pelo_rotulo_do_volume(monkeypatch):
    from cicloassist.carta import vista
    monkeypatch.setattr(vista.sys, "platform", "darwin")
    f = {"maquina": "EDITOR2-WIN", "arquivo": "D:\\x\\a.mp4", "volume": "SSD", "relativo": "x/a.mp4"}
    assert vista.traduzir(f) == "/Volumes/SSD/x/a.mp4"
    assert vista.traduzir({**f, "maquina": projeto.maquina()}) == "D:\\x\\a.mp4"     # o desta máquina, como foi visto


def test_rotas_da_janela(tmp_path, monkeypatch):
    from cicloassist.servico import rotas_carta as R
    from cicloassist.servico import seletor
    from cicloassist.servico.http import ROTAS
    for c in ("/carta/arvore", "/carta/conteudo", "/carta/pasta", "/carta/revelar"):
        assert ROTAS[("POST", c)][1], f"{c}: quem age passa pelo porteiro"
    assert not ROTAS[("GET", "/carta")][1]                                   # a página é navegação de topo
    raiz = tmp_path / "PROJ"
    raiz.mkdir()
    monkeypatch.setattr(seletor, "escolher", lambda *a, **k: [str(raiz)])
    _post(R.rota_carta_novo, {"nome": "Teste", "taxa": "25"})
    (raiz / "solto.txt").write_text("x")
    r = _post(R.rota_carta_arvore, {"raiz": str(raiz), "abrindo": True})
    assert r["ok"] and r["quarentena"] and r["quarentena"][0].endswith("solto.txt")     # a quarentena é DITA
    assert _post(R.rota_carta_pasta, {"raiz": str(raiz), "dentro": "", "nome": "D01"}) == {"ok": True, "pasta": "D01"}
    assert not _post(R.rota_carta_pasta, {"raiz": str(raiz), "dentro": "", "nome": "../x"})["ok"]
    assert _post(R.rota_carta_conteudo, {"raiz": str(raiz), "pastas": ["D01"]}) == {"ok": True, "linhas": []}
    assert not _post(R.rota_carta_conteudo, {"raiz": str(tmp_path), "pastas": [""]})["ok"]   # raiz não aberta por aqui
    r = _post(R.rota_carta_revelar, {"raiz": str(raiz), "arquivo": "/etc/hosts"})
    assert not r["ok"] and "não é de nenhuma mídia" in r["motivo"]                   # ⛔ ADR 0005


# ── C2 parte 2: a vitrine (remover = sumir da VISTA; o oculto da bin do Avid) ──

def _nomes_na(proj, pasta):
    from cicloassist.carta import vista
    return [l["nome"] for l in vista.conteudo(proj, [pasta])]


def test_remover_some_da_vista_e_o_item_continua_achando(proj):
    from cicloassist.carta import itens, vitrine
    (proj.raiz / "D01").mkdir()
    c, cam = referencias.criar(proj, "D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    _, sub, _ = itens.criar(proj, "D01", "CAM.sub.01", {"tipo": "recorte", "midia": cam["id"], "entrada_q": 0, "saida_q": 24}, {})
    r = vitrine.remover(proj, [cam["id"], "nao-existe"])
    assert r == {"removidos": ["CAM"], "nao_achados": ["nao-existe"]}
    assert not c.exists() and (proj.ocultas / f"{cam['id']}.ref.json").exists()     # nada apagado: foi para a área oculta
    assert _nomes_na(proj, "D01") == ["CAM.sub.01"]                                 # some da vitrine…
    assert cam["id"] in {d["id"] for _, d in referencias.todas(proj)}               # …e continua do projeto
    itens.criar(proj, "D01", "CAM.sub.02", {"tipo": "recorte", "midia": cam["id"], "entrada_q": 0, "saida_q": 48}, {})


def test_mover_e_trazer_da_area_oculta(proj):
    from cicloassist.carta import vitrine
    for p in ("D01", "D02"):
        (proj.raiz / p).mkdir()
    _, cam = referencias.criar(proj, "D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    assert vitrine.mover(proj, [cam["id"]], "D02") == {"movidos": ["CAM"], "ja_estavam": []}
    assert _nomes_na(proj, "D01") == [] and _nomes_na(proj, "D02") == ["CAM"]
    assert vitrine.mover(proj, [cam["id"]], "D02")["ja_estavam"] == ["CAM"]
    vitrine.remover(proj, [cam["id"]])
    vitrine.mover(proj, [cam["id"]], "D01")                                         # a linha revelada, movida
    assert _nomes_na(proj, "D01") == ["CAM"] and not list(proj.ocultas.iterdir())
    with pytest.raises(CartaErro):
        vitrine.mover(proj, [cam["id"]], "../fora")


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_mandar_de_novo_traz_de_volta_e_o_de_item_entra_oculto(proj, tmp_path):
    from cicloassist.carta import vitrine
    (proj.raiz / "D01").mkdir()
    _video(tmp_path / "A001_C001.mov", "10:00:00:00")
    _video(tmp_path / "A001_C002.mov", "11:00:00:00")
    c = anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C001.mov"], "avid", "avid")
    rid = next(d["id"] for _, d in referencias.todas(proj) if d["nome"] == "A001_C001")
    vitrine.remover(proj, [rid])
    c = anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C001.mov"], "avid", "avid")
    assert c.voltaram == ["A001_C001"] and _nomes_na(proj, "D01") == ["A001_C001"]
    c = anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C002.mov"], "avid", "avid", visivel=False)
    assert c.novas == ["A001_C002"] and _nomes_na(proj, "D01") == ["A001_C001"]   # o que veio por um item: oculto
    assert len(list(proj.ocultas.glob("*.ref.json"))) == 1


def test_as_pastas_renomear_mover_remover(proj):
    from cicloassist.carta import vista, vitrine
    vista.nova_pasta(proj, "", "Diarias")
    vista.nova_pasta(proj, "Diarias", "D01")
    vista.nova_pasta(proj, "", "Cenas")
    _, cam = referencias.criar(proj, "Diarias/D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    assert vitrine.renomear_pasta(proj, "Diarias/D01", "D01_230403") == "Diarias/D01_230403"
    assert _nomes_na(proj, "Diarias/D01_230403") == ["CAM"]
    with pytest.raises(CartaErro):
        vitrine.renomear_pasta(proj, "Diarias", "Cenas/x")
    with pytest.raises(CartaErro):
        vitrine.mover_pasta(proj, "Diarias", "Diarias/D01_230403")                 # para dentro de si mesma
    assert vitrine.mover_pasta(proj, "Diarias/D01_230403", "Cenas") == "Cenas/D01_230403"
    r = vitrine.remover_pasta(proj, "Cenas", agora=time.mktime((2026, 11, 13, 12, 0, 0, 0, 0, -1)))
    assert r["removidos"] == ["CAM"] and r["quarentena"] == "Quarentena/2026-11-13/Cenas"
    assert cam["id"] in {d["id"] for _, d in referencias.todas(proj)}               # a referência foi para o oculto
    assert [p["caminho"] for p in vista.arvore(proj)] == ["", "Diarias"]
    with pytest.raises(CartaErro):
        vitrine.remover_pasta(proj, "")


def test_camadas_item_feito_de_item_e_os_referenciados(proj):
    """⭐ Guardar TUDO (autor, 2026-11-13): a multicam feita de um nest que contém um merged = três itens ligados."""
    from cicloassist.carta import itens, vista
    (proj.raiz / "D01").mkdir()
    _, cam = referencias.criar(proj, "D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    _, som = referencias.criar(proj, "D01", "SOM", {"nome_da_fonte": "SOM", "tipo": "audio", "duracao_s": 10.0}, {})
    conta = itens.ContaItens()
    merged = itens.registrar(proj, "D01", "CAM.merged", {"tipo": "sincronizado", "duracao_q": None,
        "imagem": {"midia": cam["id"], "inicio_q": 0}, "som": {"midia": som["id"], "inicio_q": 240}}, {}, conta, visivel=False)
    nest = itens.registrar(proj, "D01", "NEST", {"tipo": "sequencia", "trilhas": [{"tipo": "V", "k": 1, "clipes": [
        {"item": merged["id"], "inicio_q": 0, "entrada_q": 0, "fim_q": 100}]}]}, {}, conta, visivel=False)
    multi = itens.registrar(proj, "D01", "MULTI", {"tipo": "grupo", "angulo": nest["id"], "angulo_do_som": None,
        "fontes": [{"item": nest["id"], "deslocamento_q": 0, "imagem": True}]}, {}, conta)
    assert conta.novos == ["MULTI"]                                       # as camadas de dentro entram OCULTAS
    assert itens.partes(multi) == [("item", nest["id"])]                  # um nível
    assert itens.partes(nest) == [("item", merged["id"])]
    linhas = vista.conteudo(proj, ["D01"])
    assert [(l["nome"], l["tipo"]) for l in linhas] == [("CAM", "vídeo"), ("SOM", "som"), ("MULTI", "multicam")]
    com = vista.conteudo(proj, ["D01"], referenciados=True)
    reveladas = {l["nome"]: l["mora_em"] for l in com if l.get("revelada")}
    assert reveladas == {"NEST": None, "CAM.merged": None}                # desce as camadas; CAM e SOM já estavam
    assert {l["nome"]: l["tipo"] for l in com}["CAM.merged"] == "subclipe (A\\V)"
    with pytest.raises(CartaErro, match="item"):
        itens.criar(proj, "D01", "X", {"tipo": "grupo", "fontes": [{"item": "nao-existe", "deslocamento_q": 0}]}, {})


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_a_decidir_guardado_e_respondido(proj, tmp_path):
    """O homônimo do "mandar" fica GUARDADO (a lista "A decidir"); "é outra" cria uma referência distinta, "é a mesma"
    liga o arquivo à que existe — e o caso some da lista para todos."""
    from cicloassist.carta import decidir, vista
    (proj.raiz / "D01").mkdir()
    for p in ("a", "b", "c"):
        (tmp_path / p).mkdir()
    _video(tmp_path / "a" / "A001_C001.mov", "10:00:00:00")
    for p in ("b", "c"):
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "smptebars=s=320x180:r=24000/1001:d=2",
                        "-timecode", "10:00:00:00", "-c:v", "mpeg4", str(tmp_path / p / "A001_C001.mp4")], check=True)
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "a" / "A001_C001.mov"], "avid", "avid")
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "b" / "A001_C001.mp4"], "trabalho", "premiere")
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "b" / "A001_C001.mp4"], "trabalho", "premiere")   # de novo: um caso só
    casos = decidir.pendentes(proj)
    assert [(c["caso"], c["nome"], c["pasta"]) for c in casos] == [("homonimo", "A001_C001", "D01")]
    assert casos[0]["candidatos"][0]["medida"] is not None and "conteúdo não confere" in casos[0]["porque"]
    with pytest.raises(CartaErro, match="candidatos"):
        decidir.responder(proj, casos[0]["id"], "nao-e-candidato")
    r = decidir.responder(proj, casos[0]["id"], "outra")
    assert decidir.pendentes(proj) == [] and r["ref"] != casos[0]["candidatos"][0]["id"]
    assert sorted(l["nome"] for l in vista.conteudo(proj, ["D01"])) == ["A001_C001", "A001_C001"]   # duas mídias
    with pytest.raises(CartaErro, match="respondido"):
        decidir.responder(proj, casos[0]["id"], "outra")

    # o MESMO conteúdo da que o editor disse ser outra: reconhecida sozinha, sem caso novo
    c = anexar.mandar_arquivos(proj, "D01", [tmp_path / "c" / "A001_C001.mp4"], "trabalho", "premiere")
    assert c.ja_estavam == ["A001_C001"] and decidir.pendentes(proj) == []

    # um TERCEIRO conteúdo: as duas servem pela régua e nenhuma confere → empate guardado; "é a mesma que…" o liga
    (tmp_path / "d").mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "rgbtestsrc=s=320x180:r=24000/1001:d=2",
                    "-timecode", "10:00:00:00", "-c:v", "mpeg4", str(tmp_path / "d" / "A001_C001.mp4")], check=True)
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "d" / "A001_C001.mp4"], "trabalho", "premiere")
    caso = decidir.pendentes(proj)[0]
    assert caso["caso"] == "empate" and len(caso["candidatos"]) == 2
    alvo = caso["candidatos"][0]["id"]
    decidir.responder(proj, caso["id"], alvo)
    assert decidir.pendentes(proj) == []
    assert any(Path(f["arquivo"]).as_posix().endswith("d/A001_C001.mp4") and f["por"].startswith("o editor disse")
               for f in diario.formas(proj)[alvo])


@pytest.mark.skipif(not shutil.which("ffmpeg"), reason="sem ffmpeg")
def test_miniatura_da_midia_e_do_item(proj, tmp_path, monkeypatch):
    from cicloassist.carta import itens, miniatura
    from cicloassist.servico import rotas_carta as R
    from cicloassist.servico.http import Pedido
    (proj.raiz / "D01").mkdir()
    _video(tmp_path / "A001_C001.mov", "10:00:00:00")
    anexar.mandar_arquivos(proj, "D01", [tmp_path / "A001_C001.mov"], "avid", "avid")
    rid = next(d["id"] for _, d in referencias.todas(proj))
    _, sub, _ = itens.criar(proj, "D01", "A001_C001.sub.01", {"tipo": "recorte", "midia": rid, "entrada_q": 10, "saida_q": 20}, {})
    a = miniatura.alvo(proj, sub["id"])
    assert a[1] == 10 and a[2] == "video"                                  # o item: a mídia de baixo, onde ele começa
    jpg = miniatura.gerar(*miniatura.alvo(proj, rid))
    assert jpg[:2] == b"\xff\xd8" and miniatura.gerar(*miniatura.alvo(proj, rid)) == jpg   # a 2ª vem do cache
    assert miniatura.alvo(proj, "nao-existe") is None
    R._autorizar(proj.raiz)
    pede = lambda i: R.rota_carta_miniatura(Pedido("GET", "/carta/miniatura", {}, b"", {"raiz": str(proj.raiz), "id": i}))  # noqa: E731
    assert pede(rid).status == 200 and pede("../../etc/passwd").status == 404


def test_tc_do_item_e_a_conta_de_quadros():
    from fractions import Fraction

    from cicloassist.carta import vista
    f = Fraction(24000, 1001)
    assert vista.tc_mais("10:00:08:00", 200, f) == "10:00:16:08"            # o G01_CAM3.sub.01: o quadro escrito na imagem
    assert vista.duracao_tc(200, f) == "00:00:08:08"
    assert vista.tc_mais("01;00;59;29", 1, Fraction(30000, 1001)) == "01;01;00;02"   # drop-frame pula 00 e 01
    assert vista.rotulo_da_taxa(f) == "23,976" and vista.rotulo_da_taxa(Fraction(25)) == "25"
    assert vista.tc_mais("", 10, f) == "" and vista.duracao_tc(None, f) == ""


def test_opatom_uma_linha_com_os_n_arquivos_e_o_detalhe_do_item(proj, tmp_path):
    """⭐ O OP-Atom é UMA linha dos caminhos (a imagem e os sons são o mesmo material); os N arquivos vão juntos para o
    Finder, e cada um é um caminho conhecido. O item lista os referenciados (vídeo antes do som) e uma aba por mídia."""
    from cicloassist.carta import itens, vista
    (proj.raiz / "D01").mkdir()
    pasta = tmp_path / "MXF"
    pasta.mkdir()
    arqs = [pasta / n for n in ("CAM.mxf", "CAM_A01.mxf", "CAM_A02.mxf")]
    for a in arqs:
        a.write_bytes(b"x")
    _, cam = referencias.criar(proj, "D01", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    _, som = referencias.criar(proj, "D01", "SOM", {"nome_da_fonte": "SOM", "tipo": "audio", "duracao_s": 10.0}, {})
    diario.acrescentar(proj, {"fato": "forma", "midia": cam["id"], "forma": "avid", **referencias.onde(arqs[0]),
                              "arquivos": [str(a) for a in arqs], "por": "entrou por aqui"})
    itens.criar(proj, "D01", "CAM.sync.01", {"tipo": "sincronizado", "duracao_q": 48,
                "imagem": {"midia": cam["id"], "inicio_q": 0}, "som": {"midia": som["id"], "inicio_q": 0}}, {})
    linhas = {l["nome"]: l for l in vista.conteudo(proj, ["D01"])}
    c = linhas["CAM"]["caminhos"]
    assert len(c) == 1 and len(c[0]["arquivos"]) == 3 and linhas["CAM"]["abas"] is None    # mesma pasta: sem aba
    assert [(r["nome"], r["tipo"]) for r in linhas["CAM"]["referenciados"]] == [
        ("CAM.mxf", "video"), ("CAM_A01.mxf", "audio"), ("CAM_A02.mxf", "audio")]
    assert all(vista.caminho_conhecido(proj, str(a.resolve())) or vista.caminho_conhecido(proj, str(a)) for a in arqs)
    sync = linhas["CAM.sync.01"]
    assert [(r["nome"], r["tipo"]) for r in sync["referenciados"]] == [("CAM", "video"), ("SOM", "audio")]
    assert [a["titulo"] for a in sync["abas"]] == ["CAM", "SOM"]


def test_opatom_de_volume_ausente_fica_como_veio():
    """Volume de outra máquina que não está aqui: os N arquivos não podem ganhar o separador desta (medido no Windows)."""
    from cicloassist.carta import vista
    f = {"arquivo": "/Volumes/x/MXF/1/a_A01.mxf", "arquivos": ["/Volumes/x/MXF/1/a_A01.mxf", "/Volumes/x/MXF/1/a_A02.mxf"]}
    assert vista._arquivos_traduzidos(f, "/Volumes/x/MXF/1/a_A01.mxf") == f["arquivos"]


def test_canais_do_merged_opatom():
    from cicloassist.carta import itens
    parte = lambda t: {"midia": "m1"}  # noqa: E731
    sons = [{"arquivo": f"D:/Avid MediaFiles/MXF/1/T002_A0{k}.mxf"} for k in (1, 2, 3, 4, 5)]
    assert itens._canais_opatom(sons, parte) == [1, 2, 3, 4, 5]
    assert itens._canais_opatom([{"arquivo": "D:/som/T002.wav"}], parte) == []


# ── a timeline com o mesmo nome (decisão do autor, 2026-11-20) ────────────────

def _timeline(cam_id: str, fim: int) -> dict:
    return {"tipo": "sequencia", "timeline": True, "fps": "24000/1001", "duracao_q": fim, "trilhas": [
        {"tipo": "V", "k": 1, "clipes": [{"midia": cam_id, "inicio_q": 0, "entrada_q": 0, "fim_q": fim}]}]}


def _carta_com_timeline(proj):
    from cicloassist.carta import itens
    (proj.raiz / "Cortes").mkdir()
    _, cam = referencias.criar(proj, "Cortes", "CAM", {**IDENT, "nome_da_fonte": "CAM"}, {})
    conta = itens.ContaItens()
    tl = itens.registrar(proj, "Cortes", "CORTE 01", _timeline(cam["id"], 100), {"nle": "avid"}, conta)
    assert conta.novos == ["CORTE 01"]
    return cam, tl


def test_timeline_igual_com_o_mesmo_nome_e_recusada_e_dita(proj):
    from cicloassist.carta import decidir, itens
    cam, tl = _carta_com_timeline(proj)
    conta = itens.ContaItens()
    d = itens.registrar(proj, "Cortes", "corte 01", _timeline(cam["id"], 100), {"nle": "avid"}, conta)
    assert d["id"] == tl["id"] and not conta.novos and not conta.ja_estavam
    assert "já há uma cópia salva" in conta.repetidas["corte 01"] and "Cortes" in conta.repetidas["corte 01"]
    assert decidir.pendentes(proj) == []
    assert len([1 for _, x in itens.todos(proj) if x["tipo"] == "sequencia"]) == 1


def test_timeline_diferente_com_o_mesmo_nome_pergunta(proj):
    from cicloassist.carta import decidir, itens
    cam, tl = _carta_com_timeline(proj)
    conta = itens.ContaItens()
    assert itens.registrar(proj, "Cortes", "CORTE 01", _timeline(cam["id"], 150), {"nle": "avid"}, conta) is None
    assert "CORTE 01" in conta.a_decidir and not conta.novos
    [caso] = decidir.pendentes(proj)
    assert caso["caso"] == "timeline" and caso["versao"] == "CORTE 01 v02"
    assert caso["antes"]["duracao_q"] == 100 and caso["agora"]["duracao_q"] == 150
    # mandar de novo antes de responder: continua UMA pergunta, com o conteúdo mais recente
    itens.registrar(proj, "Cortes", "CORTE 01", _timeline(cam["id"], 175), {"nle": "avid"}, itens.ContaItens())
    assert len(decidir.pendentes(proj)) == 1
    assert len([1 for _, x in itens.todos(proj) if x["tipo"] == "sequencia"]) == 1     # nada gravado ainda


def test_timeline_atualizar_conserva_o_id_e_guarda_a_anterior(proj):
    from cicloassist.carta import decidir, itens
    cam, tl = _carta_com_timeline(proj)
    itens.registrar(proj, "Cortes", "CORTE 01", _timeline(cam["id"], 150), {"nle": "avid"}, itens.ContaItens())
    [caso] = decidir.pendentes(proj)
    r = decidir.responder(proj, caso["id"], "atualizar")
    assert r["item"] == tl["id"] and "atualizada" in r["mensagem"]
    [(c, d)] = [(c, x) for c, x in itens.todos(proj) if x["tipo"] == "sequencia"]
    assert d["id"] == tl["id"] and d["duracao_q"] == 150 and d["nome"] == "CORTE 01"
    [velho] = list((proj.interna / decidir.SUBSTITUIDOS).glob("*.item.json"))
    assert json.loads(velho.read_text(encoding="utf-8"))["duracao_q"] == 100
    assert decidir.pendentes(proj) == [] and not list((proj.interna / decidir.PENDENTES).iterdir())


def test_timeline_versionar_e_cancelar(proj):
    from cicloassist.carta import decidir, itens
    cam, tl = _carta_com_timeline(proj)
    itens.registrar(proj, "Cortes", "CORTE 01", _timeline(cam["id"], 150), {"nle": "avid"}, itens.ContaItens())
    r = decidir.responder(proj, decidir.pendentes(proj)[0]["id"], "versionar")
    assert r["mensagem"] == "CORTE 01: versionada como CORTE 01 v02"
    seqs = {x["nome"]: x for _, x in itens.todos(proj) if x["tipo"] == "sequencia"}
    assert seqs["CORTE 01"]["duracao_q"] == 100 and seqs["CORTE 01 v02"]["duracao_q"] == 150
    assert (proj.raiz / "Cortes" / "CORTE 01 v02.item.json").is_file()
    # a v02 mandada de novo com outro conteúdo vira a v03; cancelar deixa tudo como estava
    itens.registrar(proj, "Cortes", "CORTE 01 v02", _timeline(cam["id"], 200), {"nle": "avid"}, itens.ContaItens())
    caso = decidir.pendentes(proj)[0]
    assert caso["versao"] == "CORTE 01 v03"
    r = decidir.responder(proj, caso["id"], "cancelar")
    assert "cancelado" in r["mensagem"] and decidir.pendentes(proj) == []
    assert {x["nome"] for _, x in itens.todos(proj) if x["tipo"] == "sequencia"} == {"CORTE 01", "CORTE 01 v02"}
    with pytest.raises(CartaErro):
        decidir.responder(proj, caso["id"], "atualizar")                     # já respondido
