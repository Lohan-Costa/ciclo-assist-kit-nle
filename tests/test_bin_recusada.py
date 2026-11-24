"""Quando o Media Composer recusa a bin que acabou de receber a sequência.

⛔⛔ O `montar_corte` REGRAVA a bin do editor. Se o arquivo que sai não abre
(`FILE_OPEN_FAILURE`), deixar como está é trocar a bin de trabalho dele por um arquivo morto.
Em 2026-09-12 isso aconteceu com uma string nula que o pyavb não preservava
(`cicloassist/avid/avb_fiel.py`); o conserto fecha AQUELE caso, e esta rede é para o
próximo que ninguém mediu ainda.

⭐ E a bin nova leva o fecho, oculto: a timeline aponta SUBCLIPES, que não resolvem fora da
bin — uma bin só com a timeline abre e derruba o Media Composer ao carregar (banco,
2026-08-30).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import avb
import pytest

from cicloassist.avid import timeline as T
from cicloassist.avid.mcapi import McApiErro
from cicloassist.mcp.ferramentas import corte as C

FPS = 23.976
FORA = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.000000ff"


def _mob_ids(caminho: Path) -> dict[str, tuple[str, bool]]:
    with avb.open(str(caminho)) as f:
        return {str(i.mob.mob_id): (i.mob.name, bool(i.user_placed)) for i in f.content.items}


@pytest.fixture
def bin_da_cena(tmp_path):
    """Uma bin com um "subclipe" que aponta um "master", que aponta algo fora da bin."""
    caminho = tmp_path / "CENA.avb"
    with avb.open() as f:
        master = T.montar_timeline(
            f, "MASTER", [T.Entrada(mob_id=FORA, duracao=500, trilhas=(("picture", 1),))], FPS)
        T.montar_timeline(
            f, "TAKE", [T.Entrada(mob_id=str(master.mob_id), duracao=400,
                                  trilhas=(("picture", 1),))], FPS)
        f.write(str(caminho))
    ids = {nome: mid for mid, (nome, _) in _mob_ids(caminho).items()}
    return caminho, ids


# ── o fecho ──────────────────────────────────────────────────────────────────

def test_bin_nova_leva_o_fecho_oculto_e_so_a_timeline_visivel(tmp_path, bin_da_cena):
    base, ids = bin_da_cena
    saida = tmp_path / "NOVA.avb"
    T.escrever_bin(saida, [("CORTE", [T.Entrada(mob_id=ids["TAKE"], duracao=48,
                                                trilhas=(("picture", 1),))])],
                   FPS, base=base)
    itens = _mob_ids(saida)
    visiveis = sorted(nome for nome, vis in itens.values() if vis)
    ocultos = sorted(nome for nome, vis in itens.values() if not vis)
    assert visiveis == ["CORTE"]
    # ⭐ O MASTER vem pelo TAKE, transitivamente — o walk do pyavb não atravessaria MobID.
    assert ocultos == ["MASTER", "TAKE"]
    # ⭐ O mesmo clipe, não um parecido: o MobID viaja por valor.
    assert ids["TAKE"] in itens and ids["MASTER"] in itens


def test_acrescentar_em_OUTRA_bin_leva_o_fecho_que_falta(tmp_path, bin_da_cena):
    """⛔ MEDIDO em 2026-09-13: `bin_da_sequencia` numa bin sem os masters do corte gravou a
    timeline pelada — e a bin abriu normalmente, que é o que esconde o defeito."""
    base, ids = bin_da_cena
    destino = tmp_path / "OUTRA.avb"
    with avb.open() as f:
        T.montar_timeline(f, "JA ESTAVA", [T.Entrada(mob_id=FORA, duracao=10,
                                                      trilhas=(("picture", 1),))], FPS)
        f.write(str(destino))
    entrada = T.Entrada(mob_id=ids["TAKE"], duracao=48, trilhas=(("picture", 1),))
    T.acrescentar_timeline(destino, "CORTE", [entrada], FPS, base=base)
    itens = _mob_ids(destino)
    assert sorted(n for n, vis in itens.values() if vis) == ["CORTE", "JA ESTAVA"]
    assert sorted(n for n, vis in itens.values() if not vis) == ["MASTER", "TAKE"]


def test_acrescentar_na_PROPRIA_bin_nao_duplica_nada(bin_da_cena):
    base, ids = bin_da_cena
    entrada = T.Entrada(mob_id=ids["TAKE"], duracao=48, trilhas=(("picture", 1),))
    T.acrescentar_timeline(base, "CORTE", [entrada], FPS, base=base)
    with avb.open(str(base)) as f:
        nomes = sorted(i.mob.name for i in f.content.items)
    assert nomes == ["CORTE", "MASTER", "TAKE"]


def test_fecho_ignora_o_que_nao_esta_na_bin(bin_da_cena):
    base, ids = bin_da_cena
    with avb.open(str(base)) as f:
        indice = {str(m.mob_id): m for m in f.content.mobs}
        achados = T.fecho(indice, [ids["TAKE"]])
        assert set(achados) == {ids["TAKE"], ids["MASTER"]}


# ── a recusa ─────────────────────────────────────────────────────────────────

class _MCQueRecusa:
    """Recusa `OpenBin` da bin da cena UMA vez (a regravada); aceita o resto."""

    def __init__(self, raiz: Path, recusar: str):
        self.raiz, self.recusar, self.abertas = raiz, recusar, []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def projeto(self):
        return {"caminho": str(self.raiz), "fps_aprox": FPS}

    def _chamar(self, metodo, _timeout=None, **campos):
        if metodo == "OpenBin":
            caminho = campos["bin_path"]
            if caminho == self.recusar:
                self.recusar = None
                raise McApiErro('OpenBin falhou: {"ErrorMessage": "FILE_OPEN_FAILURE"}')
            self.abertas.append(caminho)


@pytest.fixture
def cenario(monkeypatch, tmp_path, bin_da_cena):
    base, ids = bin_da_cena
    antes = base.read_bytes()
    take = SimpleNamespace(mob_id=ids["TAKE"], imagem=SimpleNamespace(tracks=1), som=None)
    monkeypatch.setattr(C, "resolver", lambda *_a, **_k: take)
    mc = _MCQueRecusa(tmp_path, recusar="CENA.avb")
    monkeypatch.setattr(C, "MediaComposer", mc)
    plano = {
        "bin": str(base), "nome": "C99 CORTE", "bin_da_sequencia": "CENA.avb",
        "cortes": [{"take": "TAKE", "duracao_frames": 48, "confianca": "hipotese",
                    "fonte": "heuristica", "porque": "teste"}],
    }
    return base, antes, mc, plano


def test_bin_recusada_volta_intacta_e_a_sequencia_vai_para_bin_nova(tmp_path, cenario):
    base, antes, mc, plano = cenario
    r = C.montar_corte(**plano)

    assert r.get("ok"), r
    assert base.read_bytes() == antes, "a bin do editor tem de voltar EXATAMENTE como estava"
    assert r["bin"] == "C99 CORTE.avb"
    assert r["acrescentada_a_bin_existente"] is False
    assert "intacta" in r["aviso_para_o_editor"]
    assert "C99 CORTE" in r["aviso_para_o_editor"]
    nova = _mob_ids(tmp_path / "C99 CORTE.avb")
    assert sorted(n for n, vis in nova.values() if vis) == ["C99 CORTE"]
    # A original reaberta, e a nova aberta.
    assert mc.abertas == ["CENA.avb", "C99 CORTE.avb"]


def test_bin_nova_nao_cai_por_cima_de_uma_que_ja_existe(tmp_path, cenario):
    _, _, _, plano = cenario
    ocupada = tmp_path / "C99 CORTE.avb"
    ocupada.write_bytes(b"do editor")
    r = C.montar_corte(**plano)
    assert r["bin"] == "C99 CORTE 2.avb"
    assert ocupada.read_bytes() == b"do editor"


def test_mc_fora_do_ar_nao_desfaz_a_escrita(monkeypatch, cenario):
    """⚠️ Só `FILE_OPEN_FAILURE` é recusa do ARQUIVO. Ponte fora do ar não julga nada."""
    base, antes, mc, plano = cenario

    def _sem_ponte(metodo, _timeout=None, **campos):
        if metodo == "OpenBin":
            raise McApiErro("o Media Composer não está aberto")

    monkeypatch.setattr(mc, "_chamar", _sem_ponte)
    r = C.montar_corte(**plano)
    assert r["acrescentada_a_bin_existente"] is True
    assert "aviso_para_o_editor" not in r
    assert base.read_bytes() != antes


def _xattr(*args):
    import subprocess
    return subprocess.run(["xattr", *args], capture_output=True, text=True)


@pytest.mark.skipif(__import__("sys").platform != "darwin", reason="atributo da bin só no Mac")
def test_regravar_a_bin_nao_apaga_o_estado_que_o_MC_do_Mac_guarda_nela(bin_da_cena, tmp_path):
    """⚠️ MEDIDO em 2026-09-14: as bins reais do MC do Mac levam `BINSTATE_RSRC` (colunas e
    formatos da bin) em atributo estendido. O `os.replace` o apagava, e o `shutil.copy2` da
    cópia de segurança não o levava — "a bin volta byte a byte" valia só para os bytes."""
    from cicloassist.avid.atributos import copiar_bin

    base, ids = bin_da_cena
    assert _xattr("-w", "BINSTATE_RSRC", "colunas do editor", str(base)).returncode == 0
    entrada = T.Entrada(mob_id=ids["TAKE"], duracao=48, trilhas=(("picture", 1),))
    T.acrescentar_timeline(base, "CORTE", [entrada], FPS, base=base)
    assert _xattr("-p", "BINSTATE_RSRC", str(base)).stdout.strip() == "colunas do editor"

    guarda = tmp_path / "guarda.avb"
    copiar_bin(base, guarda)
    assert _xattr("-p", "BINSTATE_RSRC", str(guarda)).stdout.strip() == "colunas do editor"
