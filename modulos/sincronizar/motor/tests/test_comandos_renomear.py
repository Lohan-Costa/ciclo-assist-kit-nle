"""Os comandos do sidecar que a aba Renomear usa, exercitados pelo despachante.

⭐ Estes testes entram pela porta da frente — `handle_command`, o mesmo `if/elif`
que o Rust alcança — em vez de chamar `avid.renomear` direto. O que eles medem é
justamente o que o teste de unidade não vê: a peneira de entrada, a mensagem de
recusa, e o levantamento que fica guardado para o `apply` da etapa seguinte.

⚠️ Nenhum deles abre o Media Composer. O `MediaComposer` é substituído por um
duplo, e o que sobra é o que o sidecar faz **antes e depois** de falar com ele.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

import main as M


@pytest.fixture
def respostas(monkeypatch):
    """Captura o que o sidecar escreveria no stdout, já desserializado."""
    linhas: list[dict] = []
    monkeypatch.setattr(M, "_write_line", lambda s: linhas.append(json.loads(s)))
    return linhas


def _resposta(linhas: list[dict]) -> dict:
    """A resposta FINAL — as de `event: progress` não são resposta."""
    finais = [l for l in linhas if "event" not in l]
    assert finais, f"o comando não respondeu: {linhas}"
    return finais[-1]


# ── a peneira de entrada, antes de gastar gRPC ───────────────────────────────

def test_arrasto_sem_id_plausivel_e_recusado_ANTES_de_abrir_o_MC(respostas, monkeypatch):
    """⚠️ Um `type` vazio (é assim que um EFEITO chega) ou um id truncado só se
    revelaria dentro do Media Composer, ~500 ms depois. E se o MC estiver
    fechado, a mensagem que o editor veria seria sobre conexão — mandando-o
    depurar o lugar errado."""
    def explode(*a, **k):                                  # pragma: no cover
        raise AssertionError("não devia ter chegado ao Media Composer")

    monkeypatch.setattr("avid.mcapi.MediaComposer", explode)
    M.handle_command({"id": "1", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["", "curto", None]}})

    r = _resposta(respostas)
    assert r["ok"] is False
    assert "arrastado" in r["error"]


def test_mob_ids_que_nao_e_lista_e_recusado(respostas):
    M.handle_command({"id": "1", "command": "avid_rename_scan",
                      "params": {"mob_ids": "060a2b34"}})
    assert _resposta(respostas)["ok"] is False


def test_arrasto_grande_demais_e_recusado_com_o_NUMERO(respostas):
    """⚠️ Recusar antes é infinitamente melhor que estourar no meio: o teto tem
    de aparecer na mensagem, senão o editor não sabe o que reduzir."""
    demais = ["0" * 64] * (M.MAX_ARQUIVOS_POR_COMANDO + 1)
    M.handle_command({"id": "1", "command": "avid_rename_scan",
                      "params": {"mob_ids": demais}})

    r = _resposta(respostas)
    assert r["ok"] is False
    assert str(M.MAX_ARQUIVOS_POR_COMANDO) in r["error"]


# ── o levantamento ───────────────────────────────────────────────────────────

class _McFalso:
    """O mínimo que `renomear.levantar` chama do Media Composer."""

    def __init__(self):
        self.todas_pedidas = []

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def bin_do_mob(self, mob_id):
        return r"C:\Proj\BIN.avb"

    def caminho_relativo_da_bin(self, absoluto):
        return "BIN.avb"

    def itens_da_bin(self, rel, flags=("masterClips",), apenas_selecionados=False):
        if flags[0] != "masterClips":
            return []

        class _I:
            def __init__(self, nome, mob):
                self.name, self.mob_id, self.selected = nome, mob, False

        return [_I("A001_C003", "a" * 64), _I("A002_C004", "b" * 64)]

    def colunas_do_master(self, mob_id, todas=False):
        self.todas_pedidas.append(todas)
        return {"Scene": "PROJETO A - 05-04 C4 P6", "Take": "003",
                "Shoot Date": "2026-06-29"}


def test_o_levantamento_devolve_itens_catalogo_e_o_ID(respostas, monkeypatch):
    mc = _McFalso()
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)
    M.handle_command({"id": "7", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64, "b" * 64]}})

    d = _resposta(respostas)["data"]
    assert d["levantamento_id"] == "7"
    assert [i["nome"] for i in d["itens"]] == ["A001_C003", "A002_C004"]
    assert {c["nome"] for c in d["catalogo"]} >= {"scene", "take", "shoot_date"}
    # ⭐ A claquete entrou como DERIVADA, sem apagar o que foi medido.
    assert d["itens"][0]["campos"]["cena"] == "04"
    assert d["itens"][0]["campos"]["scene"] == "PROJETO A - 05-04 C4 P6"


def test_o_levantamento_fica_GUARDADO_para_o_apply(respostas, monkeypatch):
    """⭐⭐ É isto que permite ao `apply` receber só o PADRÃO. Sem o guardado,
    ele precisaria da lista de nomes vinda do cliente — e aí o conferido e o
    aplicado poderiam divergir."""
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: _McFalso())
    monkeypatch.setattr(M, "_ULTIMO_LEVANTAMENTO", {})
    M.handle_command({"id": "9", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64]}})

    assert M._ULTIMO_LEVANTAMENTO["id"] == "9"
    # ⭐ UM item, e não os dois da bin: o guardado é o que o editor ARRASTOU, não
    # o que a bin tem. Aplicar sobre a bin inteira renomearia o que ninguém pediu.
    assert [i["nome"] for i in M._ULTIMO_LEVANTAMENTO["itens"]] == ["A001_C003"]


def test_as_colunas_VAZIAS_so_vem_quando_pedidas(respostas, monkeypatch):
    """⚠️ 31 colunas contra 191 — o padrão não pode ser o caro."""
    mc = _McFalso()
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)

    M.handle_command({"id": "1", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64]}})
    assert mc.todas_pedidas and not any(mc.todas_pedidas)

    mc.todas_pedidas.clear()
    M.handle_command({"id": "2", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64], "todas_as_colunas": True}})
    assert all(mc.todas_pedidas)


def test_o_MC_fechado_vira_mensagem_e_nao_stacktrace(respostas, monkeypatch):
    from avid.mcapi import McApiIndisponivel

    def fechado(*a, **k):
        raise McApiIndisponivel("o Media Composer não está aberto")

    monkeypatch.setattr("avid.mcapi.MediaComposer", fechado)
    M.handle_command({"id": "1", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64]}})

    r = _resposta(respostas)
    assert r["ok"] is False and "Media Composer" in r["error"]


def test_a_barra_ANDA_antes_da_chamada_lenta(respostas, monkeypatch):
    """⚠️ 'Sem feedback' e 'travado' são indistinguíveis. O levantamento custa
    ~500 ms por item; o primeiro sinal tem de sair antes dele, não depois."""
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: _McFalso())
    M.handle_command({"id": "1", "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64]}})

    progressos = [l for l in respostas if l.get("event") == "progress"]
    assert progressos, "nenhum progresso emitido"
    assert progressos[0]["data"]["kind"] == "status"


# ── o preview ────────────────────────────────────────────────────────────────

def test_o_preview_nao_fala_com_o_Media_Composer(respostas, monkeypatch):
    """⭐ É Python puro sobre dicionários — e é por isso que a rota que o serve
    pode ser síncrona, respondendo a cada tecla sem polling."""
    def explode(*a, **k):                                  # pragma: no cover
        raise AssertionError("o preview não pode abrir o Media Composer")

    monkeypatch.setattr("avid.mcapi.MediaComposer", explode)
    M.handle_command({"id": "1", "command": "avid_name_preview",
                      "params": {"padrao": "C%cena_T%take2",
                                 "fichas": [{"cena": "04", "take2": "02"}]}})

    d = _resposta(respostas)["data"]
    assert d["bloqueado"] is False
    assert d["linhas"][0]["nome"] == "C04_T02"


def test_o_preview_devolve_os_TOKENS_para_o_painel_pintar(respostas):
    M.handle_command({"id": "1", "command": "avid_name_preview",
                      "params": {"padrao": "C%cena_P%plano",
                                 "fichas": [{"cena": "04", "plano": "01"}]}})

    d = _resposta(respostas)["data"]
    #                                        ↓ o recuo devolveu `_P` ao literal
    assert [(t["campo"], t["cauda"]) for t in d["tokens"]] == [("cena", "_P"),
                                                               ("plano", "")]


def test_fichas_que_nao_sao_lista_e_recusado(respostas):
    M.handle_command({"id": "1", "command": "avid_name_preview",
                      "params": {"padrao": "%cena", "fichas": "nao"}})
    assert _resposta(respostas)["ok"] is False


# ══════════════════════════════════════════════════════════════════════════════
#  Aplicar e desfazer — os comandos que ESCREVEM
# ══════════════════════════════════════════════════════════════════════════════

class _McQueEscreve(_McFalso):
    """O duplo do levantamento, mais o que o aplicar/desfazer precisam."""

    def __init__(self, nomes_no_avid=None):
        super().__init__()
        self.renomeados = []
        self.salvamentos = 0
        # O que o MC diz que cada mob se chama AGORA (para o desfazer conferir).
        self._nomes = dict(nomes_no_avid or {})

    def info(self):
        return {"app": "Media Composer", "version": "2025.6"}

    def projeto(self, recarregar=False):
        return {"path": r"C:\Proj"}

    def renomear_item(self, mob_id, nome):
        self.renomeados.append((mob_id, nome))
        self._nomes[mob_id] = nome
        _NOMES_ESCRITOS.append((mob_id, nome))

    def abrir_bin(self, caminho):
        pass

    def salvar_bin_ativa(self):
        self.salvamentos += 1
        return True

    def colunas_do_master(self, mob_id, todas=False):
        # No desfazer, o que importa é o `Name` de agora.
        if mob_id in self._nomes:
            return {"Name": self._nomes[mob_id]}
        return super().colunas_do_master(mob_id, todas)


@pytest.fixture
def diario(monkeypatch, tmp_path):
    """O journal numa pasta descartável — e o disco da bin, respondendo na hora.

    ⚠️ Sem o segundo `monkeypatch` cada teste destes esperava 10 s: o `aplicar`
    relê a `.avb` até os nomes aparecerem (20 tentativas × 0,5 s), e num teste o
    arquivo não existe. Isso é o comportamento CERTO em produção — o `Save Bin`
    é assíncrono — e seria tempo morto aqui. O que se troca é o relógio, nunca a
    regra: quem quer medir a espera de verdade usa `test_avid_aplicar.py`, onde
    ela é exercitada com um leitor controlado.
    """
    import appsettings
    from avid import renomear

    monkeypatch.setattr(appsettings, "app_data_dir", lambda: tmp_path)
    monkeypatch.setattr(renomear, "_nomes_no_disco",
                        lambda _bin: [n for _, n in _NOMES_ESCRITOS])
    return tmp_path / "renomeacoes"


#: Compartilhado entre o duplo e o leitor de disco falso: o que "chegou ao disco".
_NOMES_ESCRITOS: list = []


def _levantar(monkeypatch, mc, respostas, cmd_id="7"):
    _NOMES_ESCRITOS.clear()
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)
    M.handle_command({"id": cmd_id, "command": "avid_rename_scan",
                      "params": {"mob_ids": ["a" * 64, "b" * 64]}})
    return _resposta(respostas)["data"]["levantamento_id"]


def test_o_apply_recusa_um_levantamento_QUE_EXPIROU(respostas, monkeypatch, diario):
    """⭐⭐ O contrato: o apply recompõe o plano do levantamento guardado. Se ele
    não é mais o mesmo, aplicar seria renomear pelo que NÃO está na tela."""
    mc = _McQueEscreve()
    _levantar(monkeypatch, mc, respostas, cmd_id="7")
    respostas.clear()

    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": "outro", "padrao": "%name"}})
    r = _resposta(respostas)
    assert r["ok"] is False and "expirou" in r["error"]
    assert mc.renomeados == [], "e nada foi escrito"


def test_o_apply_RECUSA_padrao_bloqueado_sem_escrever_nada(respostas, monkeypatch, diario):
    """⚠️ Aplicar metade é pior que não aplicar: basta um item com padrão inválido
    para o lote inteiro ser recusado."""
    mc = _McQueEscreve()
    lid = _levantar(monkeypatch, mc, respostas)
    respostas.clear()

    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": lid, "padrao": "%naoexiste"}})
    r = _resposta(respostas)
    assert r["ok"] is False
    assert mc.renomeados == []


def test_o_apply_MANTEM_o_nome_do_item_que_sairia_vazio(respostas, monkeypatch, diario):
    """⭐ Decisão do autor, 2026-09-17: o metadado vazio não trava o lote. O item sem
    cena fica com o nome que tem — e, como não muda, não é escrito."""
    # o `b` só responde `Name`: sem Scene/Take, a cena dele sai vazia
    mc = _McQueEscreve(nomes_no_avid={"b" * 64: "A002_C004"})
    lid = _levantar(monkeypatch, mc, respostas)
    respostas.clear()

    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": lid, "padrao": "%cena"}})
    r = _resposta(respostas)
    assert r["ok"] is True
    assert [m for m, _ in mc.renomeados] == ["a" * 64]
    assert mc._nomes["b" * 64] == "A002_C004"


def test_o_apply_escreve_e_deixa_o_lote_no_journal(respostas, monkeypatch, diario):
    mc = _McQueEscreve()
    lid = _levantar(monkeypatch, mc, respostas)
    respostas.clear()

    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": lid,
                                 "padrao": "C%cena_T%take2"}})
    d = _resposta(respostas)["data"]
    assert d["aplicados"] == 2
    assert d["undo_id"]
    # ⭐ Com o disco respondendo, a confirmação fecha — é o que a tela mostra
    # como "gravado", em vez do aviso de salvar à mão.
    assert d["confirmado"] is True
    assert [n for _, n in mc.renomeados] == ["C04_T003", "C04_T003"]

    from avid import desfazer
    lote = desfazer.lote(d["undo_id"])
    assert lote["itens"][0]["nome_antes"] == "A001_C003"
    assert lote["itens"][0]["nome_depois"] == "C04_T003"


def test_o_apply_RECUSA_se_o_journal_nao_puder_ser_GRAVADO(respostas, monkeypatch, diario):
    """⚠️⚠️ Renomear sem poder desfazer, tendo prometido desfazer, é pior que não
    renomear. O journal é gravado ANTES de tocar na bin."""
    mc = _McQueEscreve()
    lid = _levantar(monkeypatch, mc, respostas)
    respostas.clear()

    from avid import desfazer

    def sem_disco(**k):
        raise OSError("disco cheio")

    monkeypatch.setattr(desfazer, "gravar", sem_disco)
    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": lid, "padrao": "C%cena"}})

    r = _resposta(respostas)
    assert r["ok"] is False and "desfazer" in r["error"]
    assert mc.renomeados == [], "⛔ nada pode ter sido escrito"


def test_o_desfazer_devolve_os_nomes(respostas, monkeypatch, diario):
    mc = _McQueEscreve()
    lid = _levantar(monkeypatch, mc, respostas)
    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": lid, "padrao": "C%cena_T%take2"}})
    respostas.clear()

    M.handle_command({"id": "10", "command": "avid_rename_undo", "params": {}})
    d = _resposta(respostas)["data"]
    assert d["revertidos"] == 2
    assert d["divergentes"] == []
    assert [n for _, n in mc.renomeados[-2:]] == ["A001_C003", "A002_C004"]


def test_o_desfazer_NAO_TOCA_no_que_alguem_renomeou_a_mao(respostas, monkeypatch, diario):
    """⛔⛔ Desfazer por cima apagaria o trabalho de uma PESSOA para restaurar o
    de uma máquina."""
    mc = _McQueEscreve()
    lid = _levantar(monkeypatch, mc, respostas)
    M.handle_command({"id": "9", "command": "avid_rename_apply",
                      "params": {"levantamento_id": lid, "padrao": "C%cena_T%take2"}})
    respostas.clear()

    # O editor renomeou um deles à mão, depois do lote.
    mc._nomes["a" * 64] = "O QUE O EDITOR ESCREVEU"
    antes = len(mc.renomeados)

    M.handle_command({"id": "10", "command": "avid_rename_undo", "params": {}})
    d = _resposta(respostas)["data"]

    assert len(d["divergentes"]) == 1
    assert d["divergentes"][0]["nome_no_avid"] == "O QUE O EDITOR ESCREVEU"
    assert d["revertidos"] == 1, "o outro voltou normalmente"
    escritos = [m for m, _ in mc.renomeados[antes:]]
    assert "a" * 64 not in escritos, "o item divergente NÃO foi escrito"


def test_desfazer_sem_lote_nenhum_avisa_em_vez_de_estourar(respostas, monkeypatch, diario):
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: _McQueEscreve())
    M.handle_command({"id": "1", "command": "avid_rename_undo", "params": {}})
    r = _resposta(respostas)
    assert r["ok"] is False and "desfazer" in r["error"]


def test_o_historico_nao_fala_com_o_Media_Composer(respostas, monkeypatch, diario):
    def explode(*a, **k):                                  # pragma: no cover
        raise AssertionError("o histórico só lê o journal")

    monkeypatch.setattr("avid.mcapi.MediaComposer", explode)
    M.handle_command({"id": "1", "command": "avid_rename_history", "params": {}})
    assert _resposta(respostas)["data"]["lotes"] == []


def test_o_campo_nome_original_respeita_A_SELECAO(respostas, monkeypatch, diario):
    """⭐⭐ O caso do autor, ponta a ponta.

    Renomeou 150, trouxe 5 e pediu a volta: voltavam os 150. Agora a volta é um
    CAMPO — `%nome_original` — e o padrão só alcança o que está na tela.
    """
    from avid import desfazer

    # Um lote grande, já aplicado no passado.
    grandes = [{"mob_id": f"{n:064d}", "bin": r"C:\Proj\BIN.avb",
                "tipos": ["masterClips"],
                "nome_atual": f"ORIG{n}", "nome_novo": f"C04_T{n}"}
               for n in range(150)]
    desfazer.gravar(id_do_lote="L1", projeto="C:/Proj", padrao="C%cena",
                    mc_info={}, itens=grandes)

    # Agora o editor traz DOIS deles para a tela.
    class _McDois(_McQueEscreve):
        def itens_da_bin(self, rel, flags=("masterClips",), apenas_selecionados=False):
            if flags[0] != "masterClips":
                return []

            class _I:
                def __init__(self, nome, mob):
                    self.name, self.mob_id, self.selected = nome, mob, False

            return [_I("C04_T7", f"{7:064d}"), _I("C04_T42", f"{42:064d}")]

    mc = _McDois()
    monkeypatch.setattr("avid.mcapi.MediaComposer", lambda *a, **k: mc)
    M.handle_command({"id": "20", "command": "avid_rename_scan",
                      "params": {"mob_ids": [f"{7:064d}", f"{42:064d}"]}})
    d = _resposta(respostas)["data"]

    # ⭐ O campo veio, e com o valor de CADA um.
    assert d["itens"][0]["campos"]["nome_original"] == "ORIG7"
    assert d["itens"][1]["campos"]["nome_original"] == "ORIG42"
    # ⭐ E ele aparece no catálogo marcado como vindo do NOSSO histórico.
    hist = [c for c in d["catalogo"] if c["nome"] == "nome_original"]
    assert hist and hist[0]["procedencia"] == "historico"

    respostas.clear()
    M.handle_command({"id": "21", "command": "avid_rename_apply",
                      "params": {"levantamento_id": d["levantamento_id"],
                                 "padrao": "%nome_original"}})
    r = _resposta(respostas)["data"]

    # ⛔ DOIS, e não 150.
    assert r["aplicados"] == 2
    assert sorted(n for _, n in mc.renomeados) == ["ORIG42", "ORIG7"]


def test_item_SEM_historico_recebe_o_nome_de_agora(respostas, monkeypatch, diario):
    """⚠️ Vazio bloquearia o lote inteiro (é a regra do preview) — um clipe que
    este app nunca renomeou viraria impedimento para os outros. "Voltar ao
    original" de quem nunca mudou é ficar como está."""
    mc = _McQueEscreve()
    _levantar(monkeypatch, mc, respostas)
    d = _resposta(respostas)["data"]

    assert d["itens"][0]["campos"]["nome_original"] == "A001_C003"
    respostas.clear()

    M.handle_command({"id": "9", "command": "avid_name_preview",
                      "params": {"padrao": "%nome_original",
                                 "fichas": [i["campos"] for i in d["itens"]]}})
    p = _resposta(respostas)["data"]
    assert p["bloqueado"] is False, "não pode bloquear por falta de histórico"
    assert p["linhas"][0]["nome"] == "A001_C003"
