"""O master na camada de tradução — gerenciado ou AMA — e a recusa do que não é mídia.

⭐ Tudo que entra na timeline como mídia é aceito no chat: subclipe e master. O que o Avid
guarda na bin e ainda não é aceito (group clip, preset de efeito, sequência) volta com a
frase que o editor precisa ler, e não com "não é um subclipe" — que fazia o modelo tentar
de novo com outro nome.

A travessia contra bins reais está em `spikes/a_bin_ama_regravada.py` e foi conferida em
2026-09-13 nas bins AMA do editor e nas diárias gerenciadas de `O PRODUCAO-A`.
"""

from __future__ import annotations

from types import SimpleNamespace

import avb

from cicloassist.avid import take as T


def _mob(tipo="MasterMob", uso=None, nome="X", mob_id="m1", tracks=(), locator=None):
    descritor = SimpleNamespace(locator=locator) if locator is not None else None
    return SimpleNamespace(mob_type=tipo, usage=uso, name=nome, mob_id=mob_id,
                           tracks=list(tracks), descriptor=descritor)


def _track(media_kind, aponta_para, indice=1):
    f = avb.file.AVBFile()
    sc = f.create.SourceClip(23.976, media_kind)
    sc.mob_id = avb.mobid.MobID(str(_UMIDS[aponta_para]))
    seq = SimpleNamespace(media_kind=media_kind, components=[sc])
    return SimpleNamespace(component=seq, index=indice)


_UMIDS = {
    nome: f"urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.{i:08x}"
    for i, nome in enumerate(("master", "arquivo", "fisico", "outro"), start=1)
}


def _id(nome):
    return str(avb.mobid.MobID(_UMIDS[nome]))


# ── a espécie ────────────────────────────────────────────────────────────────

def test_master_e_reconhecido_pelo_tipo_e_nao_pelo_usage():
    """⚠️ A bin `PRODE` tem 36 masters com `usage` nulo (medido): quem olhasse o `usage`
    os trataria como sequência."""
    assert T.especie(_mob(uso="mastermob")) == "master"
    assert T.especie(_mob(uso=None)) == "master"


def test_especies_da_bin():
    assert T.especie(_mob("CompositionMob", "subclip")) == "subclipe"
    assert T.especie(_mob("CompositionMob", "group")) == "grupo"
    assert T.especie(_mob("CompositionMob", "effect")) == "efeito"
    assert T.especie(_mob("CompositionMob", None)) == "sequencia"
    assert T.especie(_mob("SourceMob")) == "fonte"


def test_so_midia_e_aceita_e_o_resto_tem_frase():
    # ⭐ `matte` desde 2026-09-13: a arte com alpha que o MC põe na bin (`test_matte_key.py`).
    assert set(T.ESPECIES_ACEITAS) == {"subclipe", "master", "matte"}
    assert "multicâmera" in T.RECUSAS["grupo"]
    assert "preset" in T.RECUSAS["efeito"]


# ── achar pelo nome ──────────────────────────────────────────────────────────

def test_pelo_nome_o_master_ganha_do_mob_de_arquivo_homonimo():
    """⛔ MEDIDO na bin AMA: o master e o mob de arquivo dele têm o MESMO nome, e o
    primeiro na ordem do arquivo ganhava."""
    arquivo = _mob("SourceMob", nome="A003_03170837_C001", mob_id="s")
    master = _mob("MasterMob", nome="A003_03170837_C001", mob_id="m")
    assert T._achar([arquivo, master], "a003_03170837_c001") is master


# ── o caminho do AMA ─────────────────────────────────────────────────────────

def test_caminho_do_avid_vira_caminho_do_windows():
    loc = SimpleNamespace(path="", path_utf8="D//MIDIAS DE TESTES/A/x.mov")
    assert T._caminho_do_locator(_mob(locator=loc)) == "D:/MIDIAS DE TESTES/A/x.mov"


def test_locator_de_midia_gerenciada_tem_caminho_vazio_e_nao_e_ama():
    loc = SimpleNamespace(path="", path_utf8="", path_posix="")
    assert T._caminho_do_locator(_mob(locator=loc)) == ""


def test_a_cadeia_ama_master_arquivo_fisico():
    """master → mob de arquivo (MSMLocator, sem caminho) → mob físico (WinFileLocator)."""
    fisico = _mob("SourceMob", mob_id=_id("fisico"),
                  locator=SimpleNamespace(path_utf8="D//M/clip.mov"))
    arquivo = _mob("SourceMob", mob_id=_id("arquivo"), tracks=[_track("picture", "fisico")],
                   locator=SimpleNamespace(path_utf8=""))
    master = _mob(mob_id=_id("master"), tracks=[_track("picture", "arquivo"),
                                                _track("sound", "arquivo", 1),
                                                _track("sound", "arquivo", 2)])
    por_id = {m.mob_id: m for m in (fisico, arquivo, master)}
    assert T.arquivos_ama(master, "picture", por_id) == ["D:/M/clip.mov"]
    # ⭐ O mesmo arquivo serve às duas espécies — e aparece UMA vez, não uma por track.
    assert T.arquivos_ama(master, "sound", por_id) == ["D:/M/clip.mov"]


def test_master_gerenciado_nao_tem_cadeia_na_bin():
    """Em mídia gerenciada o mob de arquivo não está na bin: a lista volta vazia, e é o
    que manda o resolvedor varrer o acervo OP-Atom."""
    master = _mob(mob_id=_id("master"), tracks=[_track("picture", "outro")])
    assert T.arquivos_ama(master, "picture", {master.mob_id: master}) == []


# ── o master é o master de si mesmo ──────────────────────────────────────────

def test_grupos_do_master_comecam_em_zero_no_tempo_dele():
    tc = SimpleNamespace(component=SimpleNamespace(media_kind="timecode"), index=1)
    master = _mob(mob_id=_id("master"), tracks=[_track("picture", "arquivo"),
                                                _track("sound", "arquivo", 1),
                                                _track("sound", "arquivo", 2), tc])
    grupos = T._grupos_do_master(master)
    assert grupos == {
        ("picture", _id("master")): {"inicio": 0, "tracks": 1, "mob": _id("master")},
        ("sound", _id("master")): {"inicio": 0, "tracks": 2, "mob": _id("master")},
    }
