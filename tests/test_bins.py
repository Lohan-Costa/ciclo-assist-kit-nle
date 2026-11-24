"""A varredura das BINS do projeto — a outra metade de "que material eu tenho".

⭐ O disco responde *o que está gravado*; a bin responde *o que está no projeto*. Medido em
2026-09-11 no projeto real: **306 nos dois, 52 só no disco, 1 só na bin** — nenhuma das
duas listas sozinha é o material do editor.
"""

from __future__ import annotations

import json

from cicloassist.avid import bins as B
from cicloassist.midia import cache as C

UMID = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.64cedc20.1dc80000.060e2b34.7f7f2a80"
OUTRO = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.6505f172.1c710000.060e2b34.7f7f2a80"


def bin_falsa(pasta, nome):
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / nome
    alvo.write_bytes(b"nao e uma bin de verdade")
    return alvo


# ── quais bins entram ────────────────────────────────────────────────────────

def test_o_attic_fica_de_fora(tmp_path):
    """⛔ O Avid guarda ali as versões antigas de cada bin, às centenas: varrê-lo
    triplicaria o trabalho para listar o que o editor já não vê."""
    bin_falsa(tmp_path, "CENA.avb")
    bin_falsa(tmp_path / "Attic", "CENA.avb.1")
    bin_falsa(tmp_path / "Attic", "CENA.avb")

    achadas = [b.name for b in B.bins_do_projeto(tmp_path)]
    assert achadas == ["CENA.avb"]


def test_a_lixeira_do_projeto_fica_de_fora(tmp_path):
    """⭐ MEDIDO em 2026-09-11: sem excluir o `Trash`, **33 dos 36** clipes que a tela
    mostrava como "na bin, sem arquivo" eram material que o editor tinha jogado fora — e a
    lista parecia mídia offline a recuperar."""
    bin_falsa(tmp_path, "CENA.avb")
    bin_falsa(tmp_path / "Trash", "velha.avb")

    assert [b.name for b in B.bins_do_projeto(tmp_path)] == ["CENA.avb"]


def test_as_pastas_de_sistema_ficam_de_fora(tmp_path):
    bin_falsa(tmp_path, "boa.avb")
    for sistema in ("Render Files", "WaveformCache", "SearchData", "Statistics"):
        bin_falsa(tmp_path / sistema, "x.avb")

    assert len(B.bins_do_projeto(tmp_path)) == 1


def test_bins_em_subpastas_entram(tmp_path):
    """O editor organiza o projeto em pastas — CENAS, DIÁRIAS, MÚSICA."""
    bin_falsa(tmp_path / "CENAS", "C07.avb")
    bin_falsa(tmp_path / "DIARIAS" / "dia 3", "A003.avb")

    assert len(B.bins_do_projeto(tmp_path)) == 2


def test_projeto_que_nao_existe_nao_estoura(tmp_path):
    assert B.bins_do_projeto(tmp_path / "nao existe") == []


# ── o que a varredura monta ──────────────────────────────────────────────────

def masters_falsos(monkeypatch, por_bin):
    """Substitui a leitura do `.avb` — aqui o que se testa é a MONTAGEM, não o pyavb."""
    monkeypatch.setattr(B, "_masters_da_bin",
                        lambda caminho: por_bin.get(caminho.name, []))


def test_o_mesmo_master_em_duas_bins_vira_UMA_linha(tmp_path, monkeypatch):
    """⭐ O mesmo master mora na bin da cena e na do dia. Listar as duas é o que responde
    "onde está isto?" sem abrir o Media Composer."""
    bin_falsa(tmp_path / "CENAS", "C07.avb")
    bin_falsa(tmp_path / "DIARIAS", "A003.avb")
    chave = C.de_umid(UMID)
    masters_falsos(monkeypatch, {
        "C07.avb": [{"chave": chave, "nome": "A003_C001", "tracks": {"video": 1}}],
        "A003.avb": [{"chave": chave, "nome": "A003_C001", "tracks": {"video": 1}}],
    })

    achados = B.varrer(tmp_path)
    assert len(achados) == 1
    assert sorted(achados[chave]["bins"]) == ["CENAS\\C07.avb", "DIARIAS\\A003.avb"] or \
           sorted(achados[chave]["bins"]) == ["CENAS/C07.avb", "DIARIAS/A003.avb"]


def test_uma_bin_ilegivel_nao_derruba_as_outras(tmp_path, monkeypatch):
    """⚠️ Bin de outra versão, corrompida, ou aberta com lock: uma só não pode levar as
    outras 41 junto."""
    bin_falsa(tmp_path, "boa.avb")
    bin_falsa(tmp_path, "ruim.avb")

    def ler(caminho):
        if caminho.name == "ruim.avb":
            raise ValueError("bin de outra versão")
        return [{"chave": C.de_umid(UMID), "nome": "ok", "tracks": {"audio": 2}}]

    monkeypatch.setattr(B, "_masters_da_bin", ler)
    assert len(B.varrer(tmp_path)) == 1


def test_parar_no_meio_devolve_o_que_ja_leu(tmp_path, monkeypatch):
    import threading

    for i in range(4):
        bin_falsa(tmp_path, f"{i}.avb")
    parar = threading.Event()
    lidas = []

    def ler(caminho):
        lidas.append(caminho.name)
        parar.set()
        return [{"chave": C.de_umid(UMID), "nome": "x", "tracks": {}}]

    monkeypatch.setattr(B, "_masters_da_bin", ler)
    achados = B.varrer(tmp_path, parar=parar)
    assert len(lidas) == 1 and len(achados) == 1


def test_o_vocabulario_das_tracks_e_o_do_acervo():
    """⚠️ O pyavb diz `picture`/`sound` e o ffprobe diz `video`/`audio`. Duas grafias de "é
    imagem" fariam a mesma mídia parecer de espécies diferentes conforme quem a encontrou
    primeiro — e a tabela cruza as duas varreduras pela mesma chave."""
    assert B.ESPECIE["picture"] == "video"
    assert B.ESPECIE["sound"] == "audio"


# ── o resultado guardado ─────────────────────────────────────────────────────

def test_guardar_e_ler(tmp_path):
    chave = C.de_umid(UMID)
    B.guardar("D:/projeto", {chave: {"chave": chave, "nome": "x", "tracks": {},
                                     "bins": ["C07.avb"]}}, raiz=tmp_path)

    lido = B.ler(raiz=tmp_path)
    assert lido["projeto"] == "D:/projeto"
    assert lido["masters"][chave]["bins"] == ["C07.avb"]
    assert lido["quando"] > 0


def test_arquivo_corrompido_vira_vazio(tmp_path):
    (tmp_path / "bins.json").write_text("{pela metade", encoding="utf-8")
    assert B.ler(raiz=tmp_path)["masters"] == {}


def test_sem_varredura_nao_e_erro(tmp_path):
    assert B.ler(raiz=tmp_path) == {"projeto": "", "quando": 0, "masters": {}}


def test_o_json_e_legivel_com_acento(tmp_path):
    chave = C.de_umid(OUTRO)
    B.guardar("D:/p", {chave: {"chave": chave, "nome": "MÚSICA ambiente",
                               "tracks": {}, "bins": []}}, raiz=tmp_path)
    bruto = (tmp_path / "bins.json").read_text(encoding="utf-8")
    assert "MÚSICA ambiente" in bruto
    assert json.loads(bruto)
