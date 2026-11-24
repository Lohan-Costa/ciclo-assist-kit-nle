"""As receitas: o fluxo conhecido num arquivo, que roda por botão, sem modelo."""

from __future__ import annotations

import pytest

from cicloassist.mcp import ferramentas as _todas  # noqa: F401
from cicloassist.servico import fluxo, pendencias, receitas, tarefas


@pytest.fixture(autouse=True)
def limpo():
    fluxo.esquecer(); tarefas.esquecer(); pendencias.esquecer_tudo()
    yield
    fluxo.esquecer(); tarefas.esquecer(); pendencias.esquecer_tudo()


def test_as_receitas_da_casa_passam_no_executor():
    rs = receitas.todas()
    assert {"preparar-diaria-no-mc", "conformar-no-resolve"} <= set(rs)
    for r in rs.values():
        assert r.problemas == [], (r.nome, r.problemas)
        assert r.condicoes, r.nome      # a parte que o modelo lê


def test_dois_fluxos_diferentes_com_o_mesmo_executor():
    """O critério da F1: o segundo fluxo não pede uma linha nova no executor."""
    rs = receitas.todas()
    ops = {r.nome: [p["op"] for p in r.passos] for r in rs.values()}
    # ⛔ O converter exige o Resolve ABERTO: a receita abre antes (achado na prova de 2026-11-01,
    #   a conferência recusou antes do cartão).
    assert ops["preparar-diaria-no-mc"][:2] == ["abrir_programa", "converter_para_opatom"]
    assert ops["conformar-no-resolve"][-1] == "conformar_no_resolve"


def test_plano_da_receita_com_os_valores_do_editor():
    r = receitas.buscar("preparar-diaria-no-mc")
    p = r.plano({"pasta": "C:/D01", "projeto": "FLUXO", "diaria": "D07"})
    assert p["nome"] == "Preparar a diária D07 no Media Composer"
    assert p["parametros"]["formato"] == "1080p/25"         # o padrão
    assert fluxo.validar(p) == []
    with pytest.raises(receitas.ReceitaInvalida, match="falta preencher"):
        r.plano({"diaria": "D07"})
    with pytest.raises(receitas.ReceitaInvalida, match="escolha uma"):
        r.plano({"pasta": "C:/D01", "projeto": "F", "formato": "8K"})


def test_receita_que_chama_o_que_nao_existe_vem_marcada():
    texto = ('---\nname: ruim\ndescription: x\nparametros: {}\n---\n## Passos\n'
             '```json\n[{"id": "a", "op": "rodar_shell", "args": {"cmd": "rm"}}]\n```\n')
    r = receitas.ler_texto(texto, "editor")
    assert any("não existe a operação" in p for p in r.problemas)


def test_receita_sem_bloco_json_e_recusada():
    with pytest.raises(receitas.ReceitaInvalida, match="bloco"):
        receitas.ler_texto("---\nname: x\n---\n## Passos\n1. converter\n")


def test_a_do_editor_ganha_da_casa(tmp_path):
    destino = receitas.pasta_do_editor()
    destino.mkdir(parents=True)
    casa = (receitas.DA_CASA / "conformar-no-resolve.md").read_text(encoding="utf-8")
    (destino / "minha.md").write_text(casa.replace("description: Leva", "description: Minha"), encoding="utf-8")
    r = receitas.buscar("conformar-no-resolve")
    assert r.origem == "editor" and r.descricao.startswith("Minha")


def test_o_botao_abre_o_cartao_do_plano_inteiro():
    from cicloassist.servico import rotas

    class P:
        def json(self):
            return {"nome": "conformar-no-resolve",
                    "parametros": {"timeline": "C:/x.prproj", "sequencia": "S"}}
    import json as _json
    resposta = rotas.rota_receitas_preparar(P())
    corpo = _json.loads(resposta.corpo)
    # Sem o Resolve nesta máquina de teste, a conferência do 1º passo pode recusar — e diz por quê.
    # ⛔ Escolher a receita é o editor nomeando o programa: a regra do abrir_programa ("o
    #   editor NÃO disse qual programa") não pode recusar o botão. Só falta de Resolve recusa.
    if not corpo["ok"]:
        assert "não está instalado" in corpo["motivo"], corpo["motivo"]
        return
    ent = corpo["pendencia"]["entrada"]
    assert ent["plano"]["passos"][1]["op"] == "conformar_no_resolve"
    assert ent["receita_de"] == "conformar-no-resolve"


# ── caminho nunca digitado, timeline escolhida da lista (autor, 2026-11-01) ──


def test_caminhos_multiplos_e_o_nome_derivado():
    r = receitas.buscar("conformar-no-resolve")
    p = r.plano({"timeline": "C:/x/WSP-DLPC_2.prproj", "sequencia": "PRODC_CORTE02"})
    assert p["parametros"]["timeline_nome"] == "WSP-DLPC_2"     # o projeto do Resolve sai daqui
    assert p["parametros"]["pastas"] == []                        # vários e opcional: lista vazia
    assert p["parametros"]["referencia"] == ""
    assert p["nome"] == "Conformar PRODC_CORTE02 no DaVinci Resolve"
    p2 = r.plano({"timeline": ["C:/x/a.aaf"], "sequencia": "S", "pastas": ["D:/m1", "D:/m2"]})
    assert p2["parametros"]["pastas"] == ["D:/m1", "D:/m2"]
    assert fluxo.resolver(r.passos[1]["args"], p2["parametros"], {})["pastas"] == ["D:/m1", "D:/m2"]
    with pytest.raises(receitas.ReceitaInvalida, match="falta preencher"):
        r.plano({"timeline": "C:/x/a.aaf"})        # a timeline tem de ser escolhida


def test_timeline_le_de_um_parametro_arquivo():
    texto = ('---\nname: x\nparametros: {"seq": {"tipo": "timeline", "de": "nada"}}\n---\n'
             '## Passos\n```json\n[]\n```\n')
    with pytest.raises(receitas.ReceitaInvalida, match="DE um parâmetro arquivo"):
        receitas.ler_texto(texto)


def test_a_lista_de_timelines_so_le_arquivo_autorizado():
    import json as _json
    from cicloassist.servico import rotas

    class P:
        def json(self):
            return {"arquivo": "C:/Windows/win.ini"}
    corpo = _json.loads(rotas.rota_receitas_timelines(P()).corpo)
    assert corpo["ok"] is False and "escolha o arquivo" in corpo["motivo"]


def test_o_titulo_vai_ao_applescript_por_argv(monkeypatch):
    """⛔ Um `"` no título colado no script viraria AppleScript executado."""
    from cicloassist.servico import seletor
    visto = {}

    class R:
        returncode, stdout, stderr = 0, "/Volumes/A/x.aaf\n", ""

    def rodar(cmd):
        visto["cmd"] = cmd
        return R()
    monkeypatch.setattr(seletor.sys, "platform", "darwin")
    monkeypatch.setattr(seletor, "_rodar", rodar)
    titulo = 'a" & (do shell script "rm -rf ~") & "'
    assert seletor.escolher("arquivo", False, ["aaf", "x;y"], titulo) == [str(__import__("pathlib").Path("/Volumes/A/x.aaf"))]
    assert titulo not in visto["cmd"][2]           # o script é fixo
    assert visto["cmd"][3] == titulo                # o título é argumento
    assert visto["cmd"][-1] == "aaf"                # extensão estranha ("x;y") não passa


def test_seletor_do_windows_monta_sem_abrir():
    """O índice da vtable conferido sem ninguém clicar (o diálogo só é montado)."""
    import subprocess
    import sys
    if sys.platform != "win32":
        pytest.skip("só no Windows")
    from cicloassist.servico import seletor
    from pathlib import Path
    script = Path(seletor.__file__).with_name("seletor_win.py")
    r = subprocess.run([sys.executable, str(script), "--conferir", "--arquivos", "--varios"],
                       capture_output=True, text=True, timeout=30)
    opcoes = int(r.stdout.strip(), 16)
    assert opcoes & 0x200 and opcoes & 0x40 and not opcoes & 0x20      # vários, disco, não-pasta


def test_timelines_recusadas_mostram_so_a_frase_do_dlpc(monkeypatch, tmp_path):
    """O `Untitled.prproj` sem sequência (2026-11-02): a janela mostra a frase dele, sem rota e HTTP."""
    from cicloassist import delapraca
    from cicloassist.servico import arrastados, rotas

    arq = tmp_path / "Untitled.prproj"
    arq.write_text("x")
    arrastados.autorizar(arq)

    def recusa(_a):
        raise delapraca.DelaPracaFalhou("o De Lá Pra Cá recusou /receber/abrir (HTTP 400): sem sequência",
                                        "o projeto Untitled.prproj não tem nenhuma sequência de montagem")

    monkeypatch.setattr(delapraca, "abrir", recusa)

    class P:
        def json(self):
            return {"arquivo": str(arq)}

    import json as _json
    corpo = _json.loads(rotas.rota_receitas_timelines(P()).corpo)
    assert corpo == {"ok": False, "motivo": "o projeto Untitled.prproj não tem nenhuma sequência de montagem"}
