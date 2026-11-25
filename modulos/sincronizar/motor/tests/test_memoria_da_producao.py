"""A memória da produção: a regra escrita à mão muda a leitura, sem IA (fase A1)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main as M
from media import identidade as I
from media import memoria_da_producao as MP

REGRA = r"^(?P<cena>\d+B)-\d+-(?P<plano>\d+)T(?P<take>\d+)$"


def texto(regras):
    return ("# PRODUCAO_B\n\n## Identificação\n- iXML: PRODUCAO_B\n- Premiere: PRODUCAO-B CORTE 3\n\n"
            "## Padrões de metadado\n```json\n" + json.dumps({"regras": regras}) + "\n```\n\n## Glossário\n- ct: não se sabe\n")


@pytest.fixture
def dados(tmp_path, monkeypatch):
    monkeypatch.setenv("SINCRONIZAR_DADOS", str(tmp_path))
    pasta = tmp_path / "producoes" / "PRODUCAO_B"
    pasta.mkdir(parents=True)
    (pasta / MP.ARQUIVO).write_text(texto([{"forma": "#B-#-#T#", "regex": REGRA}]), encoding="utf-8")
    return tmp_path


def test_acha_pelo_apelido_sem_caixa_nem_acento(dados):
    assert MP.achar("producao-b corte 3").nome == "PRODUCAO_B"
    assert MP.achar("PRODUCAO-B").nome == "PRODUCAO_B"
    assert MP.achar("OUTRO PROJETO") is None
    assert MP.achar("") is None


def test_sem_pasta_de_producoes_nao_e_erro(tmp_path, monkeypatch):
    monkeypatch.setenv("SINCRONIZAR_DADOS", str(tmp_path))
    assert MP.achar("x") is None


def test_a_regra_devolve_no_formato_da_claquete(dados):
    r = MP.regras_do_projeto("PRODUCAO_B")
    assert MP.aplicar(r, "17B-18-1T02.WAV") == {"episodio": None, "cena": "C17B", "plano": "P01", "take": "T02"}
    assert MP.aplicar(r, "SEM PADRAO.WAV") is None


def test_a_regra_vence_a_coluna_e_so_dentro_do_contexto(dados):
    r = MP.regras_do_projeto("PRODUCAO_B")
    colunas = {"Scene": "17B-18-1", "Take": "02"}
    assert I.de_clipe("17B-18-1T02.WAV", None, colunas).cena == "17B-18-1"
    with I.com_regras(r):
        i = I.de_clipe("17B-18-1T02.WAV", None, colunas)
    assert (i.cena, i.plano, i.take, i.origem, i.convencao) == ("C17B", "P01", "T02", I.MEMORIA, I.MEMORIA)
    assert I.de_clipe("17B-18-1T02.WAV", None, colunas).cena == "17B-18-1"     # nada fica preso para o próximo


@pytest.mark.parametrize("ruim", [
    "```json\n{nao e json\n```",
    '```json\n{"regras": [{"regex": "("}]}\n```',
    '```json\n{"regras": [{"regex": "^(?P<take>\\\\d+)$"}]}\n```',
    '```json\n[1, 2]\n```',
])
def test_arquivo_ruim_nao_derruba_a_leitura(ruim):
    m = MP.ler_texto("# X\n\n## Padrões de metadado\n" + ruim + "\n")
    assert m.regras == ()


def test_o_projeto_da_bin_e_a_pasta_do_avp(tmp_path):
    proj = tmp_path / "PRODUCAO-A"
    (proj / "CENAS").mkdir(parents=True)
    (proj / "PRODUCAO-A.avp").write_bytes(b"")
    assert MP.projeto_da_bin(str(proj / "CENAS" / "C04.avb")) == "PRODUCAO-A"
    assert MP.projeto_da_bin(str(tmp_path / "nao" / "existe.avb")) == ""


def test_a_leitura_do_premiere_usa_a_memoria_do_projeto(dados, monkeypatch):
    respostas = []
    monkeypatch.setattr(M, "_write_line", lambda s: respostas.append(json.loads(s)))
    registros = "\n".join(["\t".join(["V", "0", "0", "0", "0", "10", "0", "/d/A001.mov"]),
                           "\t".join(["A", "0", "0", "0", "0", "10", "0", "/d/17B-18-1T02.WAV"])])
    M.handle_command({"id": "L", "command": "premiere_merged_read",
                      "params": {"registros": registros, "fps": 24, "projeto": "PRODUCAO-B CORTE 3"}})
    t = [x for x in respostas if "event" not in x][-1]["data"]["tomadas"][0]
    assert (t["cena"], t["plano"], t["take"], t["convencao"]) == ("C17B", "P01", "T02", I.MEMORIA)


# ── a gravação e o molde (fase A3) ──

@pytest.mark.parametrize("molde,nome,esperado", [
    ("{cena}-{plano}T{take}", "18-1T02", {"episodio": None, "cena": "C18", "plano": "P01", "take": "T02"}),
    ("E{episodio}C{cena|ct}P{plano}T{take}", "E5C9ctP3T01", {"episodio": "E05", "cena": "C09CT", "plano": "P03", "take": "T01"}),
    ("{cena|B}-#-{plano}T{take}", "17B-18-1T02", {"episodio": None, "cena": "C17B", "plano": "P01", "take": "T02"}),
])
def test_o_molde_vira_a_regra(molde, nome, esperado):
    r = MP.Regra("", __import__("re").compile(MP.molde_para_regex(molde)))
    assert MP.aplicar([r], nome) == esperado
    assert MP.aplicar([r], nome + " sobra") is None


def test_a_regra_do_arquivo_vale_no_master_do_mc():
    """O MC batiza o WAV linkado como SCENE/TAKE (banco, `avb/estruturas.md`)."""
    r = MP.Regra("", __import__("re").compile(MP.molde_para_regex("{cena}-{plano}T{take}")))
    assert MP.aplicar([r], "18-1/02") == {"episodio": None, "cena": "C18", "plano": "P01", "take": "T02"}
    r2 = MP.Regra("", __import__("re").compile(MP.molde_para_regex("{cena}-#T{take}")))
    assert MP.aplicar([r2], "18-1/02")["take"] == "T02"


@pytest.mark.parametrize("molde", ["{plano}T{take}", "{cena}-{cena}", "{cor}-{cena}"])
def test_molde_invalido(molde):
    with pytest.raises(ValueError):
        MP.molde_para_regex(molde)


def test_forma_do_molde():
    assert MP.forma_do_molde("E{episodio}C{cena|ct}P#T{take}") == "E#C#ctP#T#"
    assert MP.forma_de("E3C2P1T01") == "E#C#P#T#"


@pytest.mark.parametrize("ruim", ["", "..", "   ", "///", "CON", "nul"])
def test_nome_de_producao_ruim(ruim):
    with pytest.raises(ValueError):
        MP.nome_de_pasta(ruim)


def test_nome_de_producao_nao_escolhe_caminho():
    assert MP.nome_de_pasta("../fora") == ".._fora"
    assert MP.nome_de_pasta('a:b*c?"d') == 'a_b_c__d'
    assert MP.nome_de_pasta("Filme.") == "Filme"


def test_gravar_cria_o_arquivo_que_a_leitura_entende(tmp_path, monkeypatch):
    monkeypatch.setenv("SINCRONIZAR_DADOS", str(tmp_path))
    m = MP.gravar("Meu Filme", [{"forma": "#-#T#", "molde": "{cena}-{plano}T{take}"}], ["PROJ X"], ["ct: contra"], ["zz"])
    assert Path(m.caminho) == tmp_path / "producoes" / "Meu Filme" / MP.ARQUIVO
    lido = MP.achar("proj x")
    assert (lido.nome, lido.glossario, lido.nao_se_sabe, len(lido.regras)) == ("Meu Filme", ("ct: contra",), ("zz",), 1)
    assert not list(Path(m.caminho).parent.glob("*.tmp"))


def test_gravar_de_novo_soma_e_nao_apaga_o_que_o_editor_escreveu(dados):
    arquivo = dados / "producoes" / "PRODUCAO_B" / MP.ARQUIVO
    arquivo.write_text(arquivo.read_text(encoding="utf-8") + "\n## Decisões\nescrito à mão\n", encoding="utf-8")
    MP.gravar("PRODUCAO-B", [{"forma": "#-#T#", "molde": "{cena}-{plano}T{take}"}], ["Novo Nome", "producao-b corte 3"], ["ct: outra coisa", "ab: novo"], ["ct2"])
    texto = arquivo.read_text(encoding="utf-8")
    m = MP.achar("novo nome")
    assert "escrito à mão" in texto and len(m.regras) == 2
    assert m.glossario == ("ct: não se sabe", "ab: novo")     # o que já estava não é trocado
    assert m.apelidos == ("PRODUCAO_B", "PRODUCAO-B CORTE 3", "Novo Nome")
    MP.gravar("PRODUCAO_B", [{"forma": "#-#T#", "molde": "{plano}-{cena}T{take}"}])
    assert len(MP.achar("novo nome").regras) == 2             # a mesma forma troca, não duplica


def test_bloco_quebrado_nao_e_sobrescrito(dados):
    arquivo = dados / "producoes" / "PRODUCAO_B" / MP.ARQUIVO
    arquivo.write_text("# X\n\n## Padrões de metadado\n```json\n{quebrado\n```\n", encoding="utf-8")
    with pytest.raises(ValueError, match="quebrado"):
        MP.gravar("X", [{"forma": "#T#", "molde": "{cena}T{take}"}])
    assert "{quebrado" in arquivo.read_text(encoding="utf-8")


def test_a_barra_do_mc_troca_so_o_rotulo_do_take():
    r = [MP.Regra("", __import__("re").compile(MP.molde_para_regex("{cena}-EXTRAT{take}")))]
    assert MP.aplicar(r, "18-EXTRAT01")["take"] == "T01" and MP.aplicar(r, "18-EXTRA/01")["cena"] == "C18"
    assert MP.aplicar(r, "18/01") is None


def test_a_regra_gravada_sai_do_molde_mesmo_com_regex_velha(tmp_path, monkeypatch):
    monkeypatch.setenv("SINCRONIZAR_DADOS", str(tmp_path))
    pasta = tmp_path / "producoes" / "X"
    pasta.mkdir(parents=True)
    velha = {"forma": "#-EXTRAT#", "molde": "{cena}-EXTRAT{take}", "regex": r"^(?P<cena>\d+)(?:\-EXTRAT|/)(?P<take>\d+)$"}
    (pasta / MP.ARQUIVO).write_text(texto([velha]).replace("PRODUCAO_B", "X"), encoding="utf-8")
    assert MP.aplicar(MP.regras_do_projeto("X"), "18/01") is None
