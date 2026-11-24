"""O cache com nome de gente: o nome é rótulo, o manifesto é a identidade, e ler não cria nada.

Spec: `docs/spec/2026-09-13-cache-legivel-e-compartilhado.md`.
"""

from __future__ import annotations

import json
import time

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import migracao as M

CAM_A = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.1a8edcf3.1260a306.7860d011.e5e7034e"
CAM_B = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.1a8edcf3.1260a306.7860d011.e5e7034f"
NASCEU = time.mktime((2026, 9, 13, 16, 22, 6, 0, 0, -1))


@pytest.fixture(autouse=True)
def indices_limpos():
    """Cada teste simula um processo novo: o índice é memória de processo."""
    C._indices.clear()
    yield
    C._indices.clear()


# ── o nome ───────────────────────────────────────────────────────────────────

def test_o_nome_da_pasta_tem_o_formato_do_editor():
    nome = C.nome_da_pasta(C.de_umid(CAM_A), {
        "nome": "C001", "fps": "24000/1001", "tipo": "video", "duracao_s": 252.2}, NASCEU)
    assert nome.startswith("C001_23.976_video_04m12s_20260913-162206_")
    assert len(nome.rsplit("_", 1)[1]) == 6


def test_audio_leva_a_amostragem_no_lugar_do_fps_e_clipe_curto_leva_frames():
    audio = C.nome_da_pasta(C.de_umid(CAM_A), {"nome": "17WT02.WAV", "tipo": "audio",
                                                "amostragem": 48000, "duracao_s": 82}, NASCEU)
    assert audio.startswith("17WT02.WAV_48kHz_audio_01m22s_")
    curto = C.nome_da_pasta(C.de_umid(CAM_A), {"nome": "C002", "fps": "24000/1001",
                                                "tipo": "video", "duracao_s": 0.333667}, NASCEU)
    assert "_video_8f_" in curto


def test_duas_cameras_com_o_mesmo_rotulo_nao_dividem_pasta():
    """⛔⛔ A e B gravando C001 no mesmo segundo: sem o sufixo, a decupagem de uma vira a
    da outra, calada."""
    rotulo = {"nome": "C001", "fps": 25, "tipo": "video", "duracao_s": 60}
    a = C.nome_da_pasta(C.de_umid(CAM_A), rotulo, NASCEU)
    b = C.nome_da_pasta(C.de_umid(CAM_B), rotulo, NASCEU)
    assert a != b


def test_nome_hostil_vira_nome_de_pasta_seguro():
    nome = C.nome_da_pasta(C.de_umid(CAM_A), {"nome": 'CON:<a>/"b"|' + "x" * 200}, NASCEU)
    assert not set('<>:"/\\|?*') & set(nome)
    # `CON` sozinho seria dispositivo; com data e sufixo, a pasta nunca é só `CON`.
    assert nome.split(".")[0].upper() != "CON"
    assert len(nome) < 80


# ── nascer, achar, não criar ─────────────────────────────────────────────────

def test_ler_nao_faz_a_pasta_nascer(tmp_path):
    m = C.Midia(CAM_A, tmp_path)
    assert m.ler_notas() == [] and not m.tem_transcricao() and not m.tem_quadro(10)
    assert m.ler_fonte() == {} and m.precisa_refazer("quadros", {"x": 1})
    assert list(tmp_path.iterdir()) == []


def test_a_primeira_escrita_nasce_com_nome_legivel_e_manifesto(tmp_path):
    m = C.Midia(CAM_A, tmp_path, rotulo={"nome": "C001", "fps": {"num": 24000, "den": 1001},
                                         "tipo": "video", "arquivos": ["D:/x/V01.abc.mxf"]})
    m.guardar_quadro(10, b"\xff\xd8jpeg")
    (pasta,) = tmp_path.iterdir()
    assert pasta.name.startswith("C001_23.976_video_")
    manifesto = json.loads((pasta / "midia.json").read_text(encoding="utf-8"))
    assert manifesto["chave"] == C.de_umid(CAM_A)
    assert manifesto["arquivos"] == ["D:/x/V01.abc.mxf"]


def test_outro_processo_acha_a_mesma_pasta_pelo_manifesto(tmp_path):
    C.Midia(CAM_A, tmp_path, rotulo={"nome": "C001"}).guardar_transcricao([{"texto": "oi"}])
    C._indices.clear()                                 # um processo novo
    m = C.Midia(CAM_A, tmp_path)                       # sem rótulo nenhum
    assert m.ler_transcricao() == [{"texto": "oi"}]
    m.anotar({"trecho": "T1", "descricao": "close"})
    assert len(list(tmp_path.iterdir())) == 1          # não nasceu de novo


def test_o_nome_da_varredura_batiza_quando_ninguem_diz(tmp_path):
    """⭐ O `material_package_name` é o nome da bin — o OP-Atom tem nome de arquivo ilegível."""
    (tmp_path / "acervo.json").write_text(json.dumps({"D:/Avid MediaFiles": {"clipes": [{
        "chave": C.de_umid(CAM_A), "nome": "20240531_C0076-040.new.01",
        "fps": "12000/1001", "duracao_s": 1501.5, "tem_imagem": True,
        "arquivos": ["D:/Avid MediaFiles/MXF/PRODE/A01.E69CCF10_1A8ED1A8EDD3FA.mxf"]}]}}),
        encoding="utf-8")
    m = C.Midia(CAM_A, tmp_path)
    m.guardar_quadro(1, b"j")
    assert m.pasta.name.startswith("20240531_C0076-040.new.01_11.988_video_25m02s_")
    assert m.manifesto()["arquivos"][0].endswith("A01.E69CCF10_1A8ED1A8EDD3FA.mxf")


def test_todas_lista_manifesto_e_pasta_antiga_e_ignora_o_resto(tmp_path):
    C.Midia(CAM_A, tmp_path, rotulo={"nome": "C001"}).anotar({"trecho": "x"})
    (tmp_path / C.de_umid(CAM_B)).mkdir()              # pasta de antes da migração
    (tmp_path / "Nova pasta").mkdir()
    (tmp_path / "_antes_da_migracao" / C.de_umid(CAM_A)).mkdir(parents=True)
    assert sorted(m.chave for m in C.todas(tmp_path)) == sorted(
        [C.de_umid(CAM_A), C.de_umid(CAM_B)])
    assert C.estranhas(tmp_path) == 1


def test_pasta_com_manifesto_vence_a_antiga_da_mesma_chave(tmp_path):
    antiga = tmp_path / C.de_umid(CAM_A)
    antiga.mkdir()
    nova = tmp_path / "C001_x"
    nova.mkdir()
    (nova / "midia.json").write_text(json.dumps({"chave": C.de_umid(CAM_A)}),
                                     encoding="utf-8")
    assert C.Midia(CAM_A, tmp_path).achada() == nova


def test_midia_criada_por_outro_processo_dentro_de_pasta_de_projeto_aparece(tmp_path):
    """⛔ Revisão de 2026-09-13: o índice guardava as pastas já vistas e nunca relistava a
    de projeto — a mídia nova de outro processo ficava invisível até reiniciar."""
    projeto = tmp_path / "_Assist anterior"
    (projeto / "C001_x").mkdir(parents=True)
    (projeto / "C001_x" / "midia.json").write_text(
        json.dumps({"chave": C.de_umid(CAM_A)}), encoding="utf-8")
    assert [m.chave for m in C.todas(tmp_path)] == [C.de_umid(CAM_A)]
    (projeto / "C002_y").mkdir()                       # "outro processo" nasce B
    (projeto / "C002_y" / "midia.json").write_text(
        json.dumps({"chave": C.de_umid(CAM_B)}), encoding="utf-8")
    assert len(C.todas(tmp_path)) == 2


def test_pergunta_sobre_midia_inexistente_nao_relista_a_raiz_toda_vez(tmp_path, monkeypatch):
    """⚠️ Extrair 6 quadros de uma mídia nova são dezenas de `tem_quadro`."""
    contagem = {"n": 0}
    original = C._Indice.varrer

    def contando(self):
        contagem["n"] += 1
        return original(self)

    monkeypatch.setattr(C._Indice, "varrer", contando)
    m = C.Midia(CAM_A, tmp_path)
    for posicao in range(30):
        m.tem_quadro(posicao)
    assert contagem["n"] == 1


def test_nascer_confere_de_novo_mesmo_dentro_da_janela_de_releitura(tmp_path):
    """⛔ A economia da leitura não vale para quem cria: pasta duplicada é o pior erro."""
    C.Midia(CAM_A, tmp_path).tem_quadro(1)            # varre agora: nada
    outra = tmp_path / "C001_de_outro_processo"
    outra.mkdir()
    (outra / "midia.json").write_text(json.dumps({"chave": C.de_umid(CAM_A)}),
                                      encoding="utf-8")
    m = C.Midia(CAM_A, tmp_path)
    m.guardar_quadro(1, b"j")
    assert m.pasta == outra and len(list(tmp_path.iterdir())) == 1


def test_master_de_camera_transcrito_primeiro_nasce_como_video():
    """⛔ Revisão de 2026-09-13: `som` e `imagem` são duas Fonte do MESMO mob num master de
    câmera; comparar objeto batizava a diária de "audio"."""
    from cicloassist.avid.take import Fonte, Take

    imagem = Fonte("A003_C001", "urn:x", ["a.mov"], 0, 0.0, 1, origem="ama")
    som = Fonte("A003_C001", "urn:x", ["a.mov"], 0, 0.0, 2, origem="ama")
    so_som = Fonte("17WT02.WAV", "urn:y", ["b.mxf"], 0, 0.0, 2)
    take = Take("A003_C001", "b.avb", "urn:x", None, None, None, None,
                {"num": 24000, "den": 1001}, 23.976, 100, 4.1, imagem, som, "inferido", "")
    assert take.rotulo(som)["tipo"] == "video" and "fps" in take.rotulo(som)
    sincronizado = Take("T1", "b.avb", "urn:s", None, None, None, None,
                        {"num": 24000, "den": 1001}, 23.976, 100, 4.1, imagem, so_som,
                        "inferido", "")
    rotulo = sincronizado.rotulo(so_som)
    assert rotulo["tipo"] == "audio" and "fps" not in rotulo


# ── a migração ───────────────────────────────────────────────────────────────


def test_migracao_nao_apaga_pasta_que_ja_existia_no_destino(tmp_path, monkeypatch):
    """⛔⛔ Revisão de 2026-09-13: `FileExistsError` é `OSError`, e o tratamento de falha
    apagava a pasta de destino que JÁ estava lá."""
    antiga = tmp_path / C.de_umid(CAM_A)
    antiga.mkdir()
    (antiga / "fonte.json").write_text(json.dumps({"master": "A003_C001"}), encoding="utf-8")
    (item,) = M.planejar(tmp_path)
    item["nova"].mkdir()
    (item["nova"] / "do_editor.txt").write_text("não apague", encoding="utf-8")
    monkeypatch.setattr(M, "planejar", lambda _raiz=None: [item])
    r = M.migrar(tmp_path)
    assert r["falhas"] and (item["nova"] / "do_editor.txt").is_file() and antiga.is_dir()

def test_migrar_copia_com_nome_legivel_e_guarda_a_antiga(tmp_path):
    antiga = tmp_path / C.de_umid(CAM_A)
    (antiga / "quadros").mkdir(parents=True)
    (antiga / "quadros" / "00000010.jpg").write_bytes(b"jpeg")
    (antiga / "fonte.json").write_text(json.dumps({"master": "A003_C001"}), encoding="utf-8")
    (antiga / "notas.json").write_text(json.dumps({"notas": [{"trecho": "T"}]}),
                                       encoding="utf-8")

    plano = M.planejar(tmp_path)
    assert antiga.exists() and plano[0]["nova"].name.startswith("A003_C001_video_")

    r = M.migrar(tmp_path)
    assert not r["falhas"] and len(r["feitas"]) == 1
    assert not antiga.exists()
    assert (tmp_path / "_antes_da_migracao" / C.de_umid(CAM_A) / "notas.json").is_file()
    C._indices.clear()
    m = C.Midia(CAM_A, tmp_path)
    assert m.achada().name == r["feitas"][0]
    assert m.ler_notas() == [{"trecho": "T"}] and m.tem_quadro(10)
    assert m.ler_fonte()["master"] == "A003_C001"   # o fonte.json foi para o manifesto
    assert M.planejar(tmp_path) == []                # migrar de novo não faz nada


def test_o_indice_nao_ve_duas_pastas_onde_ha_uma_decomposta(tmp_path, caplog):
    """⛔ MEDIDO no macOS (2026-09-14): a pasta nasce com o nome em NFC e o exFAT/HFS+ a
    lista em NFD. Comparando `Path` cru, cada relistagem avisava "a mídia tem duas pastas:
    X e X" para toda mídia nascida no processo."""
    import json
    import logging
    import unicodedata

    nome = "Cenação_23.976_video_04m12s_20260913-162206_a3f9c1"
    no_disco = tmp_path / unicodedata.normalize("NFD", nome)
    no_disco.mkdir()
    chave = "a" * 64
    (no_disco / C.MANIFESTO).write_text(json.dumps({"chave": chave}), encoding="utf-8")

    indice = C._Indice(tmp_path)
    indice.mapa[chave] = tmp_path / unicodedata.normalize("NFC", nome)
    with caplog.at_level(logging.WARNING, logger="cicloassist.midia.cache"):
        indice.varrer()
    assert "duas pastas" not in caplog.text
    assert indice.estranhas == set()
