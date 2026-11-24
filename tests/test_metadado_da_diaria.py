"""O agente de metadado (fase A3): a conferência sem IA, a pergunta que não volta e a escrita que só o editor autoriza."""
from __future__ import annotations

import json
import struct
from pathlib import Path

import pytest

from cicloassist.mcp import ferramentas  # noqa: F401
from cicloassist.mcp.ferramentas import metadado as F
from cicloassist.mcp.ferramentas import portao as P
from cicloassist.mcp.registro import FERRAMENTAS
from cicloassist.midia import metadado_da_diaria as D
from cicloassist.motor import agentes as A
from cicloassist.motor import turno_magro as T
from cicloassist.servico import arrastados, config

M = D.memoria


def wav(caminho: Path, cena=None, take=None, projeto=None, scene_bext=None) -> Path:
    """Um WAV mínimo com bext e iXML. Mídia sintética: nome de produção real não entra no repositório."""
    desc = "".join(f"s{k}={v}\r\n" for k, v in (("SCENE", scene_bext if scene_bext is not None else cena), ("TAKE", take)) if v)
    bext = desc.encode("latin-1").ljust(256, b"\0") + b"\0" * 90
    xml = "<BWFXML>" + "".join(f"<{k}>{v}</{k}>" for k, v in (("SCENE", cena), ("TAKE", take), ("PROJECT", projeto)) if v) + "</BWFXML>"
    miolo = b"WAVE" + b"bext" + struct.pack("<I", len(bext)) + bext
    x = xml.encode()
    miolo += b"iXML" + struct.pack("<I", len(x)) + x + (b"\0" if len(x) & 1 else b"")
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(b"RIFF" + struct.pack("<I", len(miolo)) + miolo)
    return caminho


@pytest.fixture
def diaria(tmp_path):
    pasta = tmp_path / "DIARIA X"
    for c, p, t in ((7, 1, 1), (7, 1, 2), (7, 2, 1)):
        wav(pasta / f"{c}-{p}T{t:02d}.WAV", f"{c}-{p}", f"{t:02d}", "FILME TESTE")
    wav(pasta / "FALSETAKES" / "7-1T03.WAV", "7-1", "03")
    wav(pasta / "E2C5P1T01.WAV", "E2C5P1", "01")
    arrastados.autorizar(pasta)
    yield pasta
    arrastados.esquecer_tudo()


def falso(monkeypatch, resposta):
    chamadas = []

    def chamar(instrucao, pedido, modelo=None, prazo=0):
        chamadas.append((instrucao, pedido))
        return T.Resposta(json.dumps(resposta), {"tokens": 10}, 0.1)
    monkeypatch.setattr(A._turno, "chamar", chamar)
    return chamadas


def proposta(forma="#-#T#", molde="{cena}-{plano}T{take}"):
    return {"forma": forma, "molde": molde, "certeza": "presumida", "por_que": "posição"}


# ── a parte sem IA ───────────────────────────────────────────────────────────────────────────────────────────────

def test_so_o_que_o_programa_nao_le_vai_ao_modelo(diaria):
    arquivos = D.coletar(diaria)
    p = D.particionar(arquivos)
    assert (len(p.descartados), len(p.pelo_programa), len(p.restantes)) == (1, 1, 3)
    entrada, sobra = D.entrada_do_agente("D", p, None)
    assert sobra == 0 and [f["forma"] for f in entrada["formas"]] == ["#-#T#"]
    assert entrada["formas"][0]["quantos"] == 3 and len(entrada["formas"][0]["amostras"]) == 3
    assert "E" in entrada["ja_resolvido"]["rotulos"]["episodio"]


def test_le_bext_e_ixml_separados(tmp_path):
    wav(tmp_path / "x.WAV", "PROD C4 P1", "001", scene_bext="PROD")
    a = D.coletar(tmp_path)[0]
    assert (a.scene_ixml, a.scene_bext, a.take_ixml, a.take_bext) == ("PROD C4 P1", "PROD", "001", "001")


def test_conferencia_campo_por_campo(diaria):
    p = D.particionar(D.coletar(diaria))
    r = D.conferir_regras(p.restantes, [proposta()], p.pelo_programa)[0]
    assert r["aprovada"], r["problemas"]
    assert r["campos"]["cena"] == {"lidos": 3, "confere": 3, "contradiz": 0, "sem_apoio": 0}
    assert r["campos"]["take"]["confere"] == 3
    assert r["exemplo"].endswith("→ C07 · P01 · T01")


def test_cobertura_nao_engana_quando_a_regra_so_le_parte(diaria):
    p = D.particionar(D.coletar(diaria))
    r = D.conferir_regras(p.restantes, [proposta(molde="{cena}-#T{take}")], [])[0]
    assert "plano" not in r["campos"]


def test_take_que_o_metadado_desmente_reprova(tmp_path):
    wav(tmp_path / "7-1T01.WAV", "7-1", "09")
    p = D.particionar(D.coletar(tmp_path))
    r = D.conferir_regras(p.restantes, [proposta()], [])[0]
    assert not r["aprovada"] and "take" in r["problemas"][0]


def test_molde_que_nao_reproduz_a_forma_reprova(diaria):
    p = D.particionar(D.coletar(diaria))
    r = D.conferir_regras(p.restantes, [proposta(molde="{cena}T{take}")], [])[0]
    assert not r["aprovada"] and "não reproduz" in r["problemas"][0]


def test_forma_inventada_e_regra_sem_cena_reprovam(diaria):
    p = D.particionar(D.coletar(diaria))
    r = D.conferir_regras(p.restantes, [proposta(forma="X#", molde="X{cena}"), proposta(molde="#-{plano}T{take}")], [])
    assert not r[0]["aprovada"] and "não existe" in r[0]["problemas"][0]
    assert not r[1]["aprovada"] and "cena" in r[1]["problemas"][0]


def test_dois_takes_com_a_mesma_identidade_reprovam(tmp_path):
    """Sem o sufixo, `7B-1T01` e `7-1T01` se sobrescreveriam na bin."""
    wav(tmp_path / "7B-1T01.WAV", "7B-1", "01")
    wav(tmp_path / "7-1T01.WAV", "7-1", "01")
    p = D.particionar(D.coletar(tmp_path))
    assert len(p.restantes) == 2
    ruins = D.conferir_regras(p.restantes, [proposta("#B-#T#", "{cena}B-{plano}T{take}"), proposta()], [])
    assert not ruins[0]["aprovada"] and "colisão" in ruins[0]["problemas"][0]
    boas = D.conferir_regras(p.restantes, [proposta("#B-#T#", "{cena|B}-{plano}T{take}"), proposta()], [])
    assert all(b["aprovada"] for b in boas), boas


def test_a_memoria_nao_pode_ser_passo_de_fluxo():
    from cicloassist.servico import fluxo
    plano = {"passos": [{"id": "g", "op": "gravar_na_memoria_da_producao", "args": {"producao": "F"}}]}
    assert any("não pode ser passo" in p for p in fluxo.validar(plano))


def test_canais_mono_do_mesmo_take_nao_sao_colisao(tmp_path):
    for canal in (1, 2):
        wav(tmp_path / f"7-1T01_{canal}.WAV", "7-1", "01")
    p = D.particionar(D.coletar(tmp_path))
    r = D.conferir_regras(p.restantes, [proposta("#-#T#_#", "{cena}-{plano}T{take}_#")], [])[0]
    assert r["aprovada"], r["problemas"]


def test_a_pergunta_nao_volta(tmp_path, monkeypatch):
    monkeypatch.setenv("SINCRONIZAR_DADOS", str(tmp_path))
    mem = M.gravar("Teste", glossario=["ab: sabido"], nao_se_sabe=["ct"])
    saida = D.filtrar_perguntas([{"sobre": "ct", "texto": "o que é?"}, {"sobre": "ab", "texto": "e isto?"}, {"sobre": "P", "texto": "P é plano?"},
                                 {"sobre": "zz", "formas": ["A"], "texto": "e zz?"}, {"sobre": "zz", "formas": ["B"], "texto": "de novo"}, "lixo"], mem)
    assert saida == [{"sobre": "zz", "formas": ["A", "B"], "texto": "e zz?", "opcoes": []}]


def test_nome_do_projeto_como_os_modulos_o_chamam():
    assert D.nome_do_projeto(r"D:\p\FILME CORTE.prproj") == "FILME CORTE"
    assert D.nome_do_projeto("/Volumes/x/Avid Projects/FILME") == "FILME"


# ── o agente ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_o_agente_carrega_e_nao_traz_valor_de_exemplo():
    a = A.buscar(F.AGENTE)
    assert a.tipo == "conselheiro" and set(a.saida) == {"regras", "perguntas", "fora"}
    assert not any(c.isdigit() for c in a.instrucao.replace("12 palavras", "").replace("máximo 12", "").replace("máximo 8", ""))


def test_a_ferramenta_propoe_confere_e_nao_grava(diaria, monkeypatch):
    chamadas = falso(monkeypatch, {"regras": [proposta(), proposta(forma="X#", molde="X{cena}")],
                                   "perguntas": [{"sobre": "qq", "formas": ["#-#T#"], "texto": "É cena-plano?"}], "fora": []})
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    r = F.entender_metadados_da_diaria(str(diaria))
    assert r["resumo"] == {"arquivos": 5, "descartados": 1, "lidos_pela_memoria": 0, "lidos_pelo_programa": 1, "sem_leitura": 3, "editor_disse_nao_saber": 0, "gerenciados_de_fora": 0}
    assert [x["forma"] for x in r["regras_aprovadas"]] == ["#-#T#"] and len(r["regras_reprovadas"]) == 1
    assert r["perguntas"][0]["sobre"] == "qq"
    assert r["producao"]["no_ixml"] == ["FILME TESTE"] and r["producao"]["memoria"] is None
    assert '"E2C5P1T01"' not in chamadas[0][1]
    assert M.todas() == []


def test_diaria_que_o_programa_le_nao_chama_modelo(tmp_path, monkeypatch):
    wav(tmp_path / "E2C5P1T01.WAV", "E2C5P1", "01")
    arrastados.autorizar(tmp_path)
    chamadas = falso(monkeypatch, {})
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    r = F.entender_metadados_da_diaria(str(tmp_path))
    assert not chamadas and "não chamei o agente" in r["manchete"]
    arrastados.esquecer_tudo()


def test_o_que_o_editor_nao_sabe_nao_volta_ao_modelo(tmp_path, monkeypatch):
    wav(tmp_path / "17B-18-1T01.WAV", "17B-18-1", "01")
    wav(tmp_path / "17B-18-2T01.WAV", "17B-18-2", "01")
    arrastados.autorizar(tmp_path)
    M.gravar("Filme", nao_se_sabe=["17B-18-1"])
    chamadas = falso(monkeypatch, {})
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "Filme")
    r = F.entender_metadados_da_diaria(str(tmp_path))
    assert not chamadas and r["resumo"]["editor_disse_nao_saber"] == 2
    arrastados.esquecer_tudo()


def test_o_nao_sei_escrito_em_frase_tira_as_formas(tmp_path):
    """O texto exato que o modelo gravou no teste do autor."""
    for nome, cena in (("17B-18-1T01", "17B-18-1"), ("18-3-2T01", "18-3-2"), ("18-1T01", "18-1"), ("18-EXTRAT01", "18-EXTRA")):
        wav(tmp_path / f"{nome}.WAV", cena, "01")
    p = D.particionar(D.coletar(tmp_path), (), ["17B-18-1 e 18-3-2 (três números)"])
    assert sorted(a.nome for a in p.ninguem_sabe) == ["17B-18-1T01", "18-3-2T01"]
    assert sorted(a.nome for a in p.restantes) == ["18-1T01", "18-EXTRAT01"]


def test_numero_solto_na_frase_nao_tira_a_forma(tmp_path):
    wav(tmp_path / "18-1T01.WAV", "18-1", "01")
    assert D.particionar(D.coletar(tmp_path), (), ["o 1 em cena 18"]).restantes


def test_as_opcoes_do_agente_viram_atalhos():
    saida = D.filtrar_perguntas([{"sobre": "a", "texto": "?", "formas": [], "opcoes": ["é o plano", "faz parte do nome", "Não sei", "x" * 60, 3, "c", "d", "e", "f"]}], None)
    assert saida[0]["opcoes"] == ["é o plano", "faz parte do nome", "c", "d"]
    assert D.filtrar_perguntas([{"sobre": "a", "texto": "?", "opcoes": "solto"}], None)[0]["opcoes"] == []
    assert D.cartao_de_perguntas(saida, {"memoria": "X"}, [])["perguntas"][0]["opcoes"][0] == "é o plano"


def test_item_so_de_letras_nao_tira_a_forma_inteira(tmp_path):
    wav(tmp_path / "7xx-1T01.WAV", "7xx-1", "01")
    p = D.particionar(D.coletar(tmp_path), (), ["xx"])
    assert len(p.restantes) == 1 and not p.ninguem_sabe


def test_pasta_nao_arrastada_e_recusada(tmp_path):
    wav(tmp_path / "7-1T01.WAV", "7-1", "01")
    assert "erro" in F.entender_metadados_da_diaria(str(tmp_path))


def test_sem_ia_a_ferramenta_diz_e_nao_quebra(diaria, monkeypatch):
    def sem(*a, **k):
        raise T.TurnoFalhou("sem conta")
    monkeypatch.setattr(A._turno, "chamar", sem)
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    r = F.entender_metadados_da_diaria(str(diaria))
    assert "sem conta" in r["erro"] and r["resumo"]["sem_leitura"] == 3


def test_a_bin_do_premiere_entra_sem_arrastar_pasta(diaria, monkeypatch):
    """O caso do teste do autor: arrastou a bin de dentro do Premiere."""
    wavs = [str(p) for p in sorted(diaria.rglob("*.WAV"))]
    monkeypatch.setattr(F._nle, "qual", lambda nle=None: F._nle.PREMIERE)
    monkeypatch.setattr(F, "_arquivos_da_bin", lambda b: wavs if b == "DIARIA/SOM" else [])
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    arrastados.esquecer_tudo()      # ⭐ nenhuma pasta autorizada: quem manda é a bin do projeto
    chamadas = falso(monkeypatch, {"regras": [proposta()], "perguntas": [], "fora": []})
    r = F.entender_metadados_da_diaria(bin="DIARIA/SOM")
    assert r["resumo"]["arquivos"] == 5 and r["resumo"]["descartados"] == 1 and r["regras_aprovadas"]
    assert chamadas[0][1].startswith("diaria: SOM")
    assert F._conferir_gravacao("F", regras=[REGRA], bin="DIARIA/SOM") == ""
    assert "não tem WAV" in F.entender_metadados_da_diaria(bin="OUTRA")["erro"]


def _avid(monkeypatch, resposta):
    monkeypatch.setattr(F._nle, "qual", lambda nle=None: F._nle.AVID)
    monkeypatch.setattr(F._nle, "projeto_aberto", lambda recarregar=False, nle=None: "D:/P/FILME")
    monkeypatch.setattr(F._bins, "wavs_linkados", lambda projeto, b: resposta)
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")


def test_bin_so_gerenciada_do_avid_pede_a_pasta(monkeypatch):
    _avid(monkeypatch, {"bins": 1, "arquivos": [], "gerenciados": 7})
    erro = F.entender_metadados_da_diaria(bin="X")["erro"]
    assert "GERENCIADA" in erro and "arrastar a pasta" in erro


def test_bin_linkada_do_avid_le_como_o_premiere_e_conta_o_que_ficou_de_fora(diaria, monkeypatch):
    _avid(monkeypatch, {"bins": 1, "arquivos": [str(p) for p in diaria.rglob("*.WAV")], "gerenciados": 2})
    falso(monkeypatch, {"regras": [], "perguntas": [], "fora": []})
    arrastados.esquecer_tudo()
    r = F.entender_metadados_da_diaria(bin="X")
    assert r["resumo"]["arquivos"] == 5 and r["resumo"]["gerenciados_de_fora"] == 2


def test_bin_que_nao_existe_no_avid(monkeypatch):
    _avid(monkeypatch, {"bins": 0, "arquivos": [], "gerenciados": 0})
    assert "Não achei a bin" in F.entender_metadados_da_diaria(bin="X")["erro"]


def test_o_resolve_le_o_media_pool_de_qualquer_conversa(diaria, monkeypatch):
    wavs = [str(p) for p in diaria.rglob("*.WAV")]
    monkeypatch.setattr(F._resolve, "arquivos_do_pool", lambda pasta="": wavs if pasta == "SOM" else [])
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    falso(monkeypatch, {"regras": [], "perguntas": [], "fora": []})
    arrastados.esquecer_tudo()
    assert F.entender_metadados_da_diaria(bin="SOM", programa="resolve")["resumo"]["arquivos"] == 5


def test_resolve_fechado_diz_e_programa_invalido_recusa(monkeypatch):
    def fechado(pasta=""):
        raise F._resolve.ResolveIndisponivel("não está aberto")
    monkeypatch.setattr(F._resolve, "arquivos_do_pool", fechado)
    assert "não está aberto" in F.entender_metadados_da_diaria(programa="resolve")["erro"]
    assert "tem de ser um de" in F.entender_metadados_da_diaria(bin="X", programa="fcp")["erro"]


def test_o_codigo_que_roda_no_python_do_resolve_compila():
    compile(F._resolve._CODIGO, "<resolve>", "exec")


def test_bin_do_avid_pelo_nome_pelo_caminho_e_pela_pasta(tmp_path):
    from cicloassist.avid import bins as B
    for rel in ("C07.avb", "CENAS/C08.avb", "CENAS/C09.avb", "Attic/C07.avb"):
        (tmp_path / rel).parent.mkdir(exist_ok=True)
        (tmp_path / rel).write_bytes(b"x")
    nomes = lambda alvo: [b.name for b in B._bins_de_nome(tmp_path, alvo)]  # noqa: E731
    assert nomes("c07") == ["C07.avb"] and nomes("CENAS/C08.avb") == ["C08.avb"]
    assert nomes("cenas") == ["C08.avb", "C09.avb"] and nomes("") == []


def test_quando_nao_ha_o_que_perguntar_mostra_o_que_entendeu(tmp_path, monkeypatch):
    for t in (1, 2):
        wav(tmp_path / f"E2C5P1T0{t}.WAV", "E2C5P1", f"0{t}")
    arrastados.autorizar(tmp_path)
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    r = F.entender_metadados_da_diaria(str(tmp_path))
    assert r["como_cada_forma_e_lida"] == [{"forma": "E#C#P#T#", "quantos": 2, "exemplo": "E2C5P1T01 → E02 · C05 · P01 · T01", "lido_por": "programa"}]
    assert "Não ofereça gravar" in r["o_que_fazer"]
    arrastados.esquecer_tudo()


def test_o_cartao_traz_uma_caixa_por_pergunta_e_a_producao(diaria, monkeypatch):
    from cicloassist.servico import historico, turno as Tn
    falso(monkeypatch, {"regras": [proposta()], "perguntas": [{"sobre": "qq", "formas": ["#-#T#"], "texto": "É cena-plano?"}], "fora": []})
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "CORTE")
    t = Tn.Turno()
    t.registro = historico.Registro(t.id, "x")
    monkeypatch.setattr(F._turno, "atual", lambda: t)
    r = F.entender_metadados_da_diaria(str(diaria))
    tipo, cartao = t.fila.get_nowait()
    while tipo != "perguntas":
        tipo, cartao = t.fila.get_nowait()
    assert [p["sobre"] for p in cartao["perguntas"]] == ["qq", "produção"]
    assert cartao["perguntas"][0]["exemplo"] == "7-1T01 (3 arquivos)" and cartao["perguntas"][0]["nao_sei"]
    assert cartao["perguntas"][1]["opcoes"] == ["FILME TESTE", "CORTE"] and not cartao["perguntas"][1]["nao_sei"]
    assert "NÃO as repita" in r["o_que_fazer"]
    assert historico.ler()[-1]["perguntas"]["id"] == cartao["id"]     # sobrevive ao Reload


def test_sem_turno_o_modelo_pergunta_em_texto(diaria, monkeypatch):
    falso(monkeypatch, {"regras": [], "perguntas": [{"sobre": "qq", "formas": [], "texto": "?"}], "fora": []})
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "")
    monkeypatch.setattr(F._turno, "atual", lambda: None)
    assert "Mostre ao editor as perguntas" in F.entender_metadados_da_diaria(str(diaria))["o_que_fazer"]


def test_sem_pergunta_e_sem_regra_nao_ha_cartao():
    assert D.cartao_de_perguntas([], {"memoria": None}, []) is None
    assert D.cartao_de_perguntas([], {"memoria": "X"}, [], True) is None


# ── a escrita ────────────────────────────────────────────────────────────────────────────────────────────────────

REGRA = {"forma": "#-#T#", "molde": "{cena}-{plano}T{take}"}


def test_gravar_cria_a_memoria_e_a_leitura_muda_sem_ia(diaria, monkeypatch):
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "FILME CORTE")
    r = F.gravar_na_memoria_da_producao("Filme Teste", str(diaria), [REGRA], ["FILME CORTE"], [{"termo": "ct", "significado": "contra"}], ["zz"])
    assert r["regras"] == 1 and r["vale_no_projeto_aberto"] is True
    mem = M.achar("filme corte")
    assert M.aplicar(mem.regras, "7-1T02.WAV") == {"episodio": None, "cena": "C07", "plano": "P01", "take": "T02"}
    assert D.particionar(D.coletar(diaria), mem.regras).restantes == []
    assert mem.glossario == ("ct: contra",) and mem.nao_se_sabe == ("zz",)


def test_gravar_avisa_quando_o_projeto_aberto_nao_e_da_producao(diaria, monkeypatch):
    monkeypatch.setattr(F, "_projeto_aberto", lambda: "OUTRO")
    r = F.gravar_na_memoria_da_producao("Filme Teste", str(diaria), [REGRA])
    assert r["vale_no_projeto_aberto"] is False and "OUTRO" in r["manchete"]


@pytest.mark.parametrize("kw,trecho", [
    ({"producao": ".."}, "não serve"),
    ({"producao": "F"}, "nada para gravar"),
    ({"producao": "F", "regras": [{"forma": "#-#T#", "molde": "{plano}-{cena}T", "exemplo": "x"}]}, "exatamente"),
    ({"producao": "F", "glossario": [{"termo": "a"}]}, "significado"),
])
def test_conferencia_antes_do_cartao(kw, trecho):
    assert trecho in F._conferir_gravacao(**kw)


def test_conferencia_le_o_disco(diaria):
    desmente = {"forma": "#-#T#", "molde": "{plano}-{take}T{cena}"}
    assert "desmente" in F._conferir_gravacao("F", str(diaria), [desmente])
    assert F._conferir_gravacao("F", str(diaria), [REGRA]) == ""


def test_modo_automatico_nao_dispensa_o_cartao(diaria, monkeypatch):
    monkeypatch.setattr(config, "ler", lambda: {"auto": True})
    monkeypatch.setattr(P._pendencias, "abrir", lambda c, r, e: type("Pend", (), {"id": "1", "rotulo": r})())
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__gravar_na_memoria_da_producao", input={"producao": "F", "nao_se_sabe": ["x"]})
    assert r["behavior"] == "deny" and r["message"] == P.AGUARDANDO
    assert FERRAMENTAS["gravar_na_memoria_da_producao"].sempre_pergunta


def test_leitura_nao_passa_pelo_portao():
    assert not FERRAMENTAS["entender_metadados_da_diaria"].escreve
    assert FERRAMENTAS["gravar_na_memoria_da_producao"].escreve
