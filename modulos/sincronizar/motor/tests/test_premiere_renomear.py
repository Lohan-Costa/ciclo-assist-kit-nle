"""A aba Renomear do Premiere: `premiere/renomear.py` e os comandos do sidecar."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import appsettings
import main as M
from avid import desfazer
from premiere import renomear

# As colunas como o Premiere 23.2 as devolveu (sonda §6), resumidas.
COLUNAS_T001 = json.dumps([
    {"ColumnID": "Column.PropertyText.Label", "ColumnName": "Label", "ColumnValue": "Caribbean"},
    {"ColumnID": "Column.Intrinsic.Name", "ColumnName": "Name",
     "ColumnValue": "PROJETO A - 05-04 C4 P1-T001.WAV"},
    {"ColumnID": "Column.Intrinsic.MediaStart", "ColumnName": "Media Start",
     "ColumnValue": "10443123827136000"},
    {"ColumnID": "Column.Intrinsic.LogNote", "ColumnName": "Log Note", "ColumnValue": "Good Take"},
    {"ColumnID": "Column.PropertyText.Scene", "ColumnName": "Scene",
     "ColumnValue": "PROJETO A - 05-04 C4 P1"},
    {"ColumnID": "Column.PropertyText.Shot", "ColumnName": "Shot", "ColumnValue": ""},
    {"ColumnID": "Column.PropertyBool.Good", "ColumnName": "Good", "ColumnValue": "false"},
])
BEXT = "SPEED=23.976ND\r\nTAKE=001\r\nSCENE=PROJETO A - 05-04\r\nNOTE=Good Take\r\n"


def _item(node, nome, colunas=COLUNAS_T001, bext=BEXT, tipo="CLIP"):
    return {"node_id": node, "nome": nome, "tipo": tipo, "colunas_json": colunas,
            "xmp": {"scene": "PROJETO A - 05-04 C4 P1", "take": "001", "bext": bext}}


@pytest.fixture
def diario(monkeypatch, tmp_path):
    monkeypatch.setattr(appsettings, "app_data_dir", lambda: tmp_path)
    return tmp_path


def test_colunas_filtram_o_ruido_e_trazem_o_take_do_arquivo():
    c = renomear.colunas_do_item(_item("000f4241", "T001.WAV"))
    assert c["Scene"] == "PROJETO A - 05-04 C4 P1"
    assert c["Take"] == "001"               # do bext — nenhuma coluna o traz
    assert c["Log Note"] == "Good Take"
    for ruido in ("Label", "Media Start", "Good"):
        assert ruido not in c, ruido
    # coluna VAZIA fica, como campo vazio (autor, 2026-09-17)
    assert c["Shot"] == ""


def test_levantar_deriva_a_claquete_e_usa_a_chave_do_projeto(diario):
    r = renomear.levantar("D:/P/X.prproj", [_item("000f4241", "PROJETO A - 05-04 C4 P1-T001.WAV")])
    item = r["itens"][0]
    assert item["mob_id"] == "premiere:D:/P/X.prproj|000f4241"
    assert item["node_id"] == "000f4241"
    campos = item["campos"]
    # cena e plano DERIVADOS da claquete; o take vem da coluna (do bext), que ganha
    # do derivado — a mesma precedência do Avid.
    assert (campos["cena"], campos["plano"], campos["take"]) == ("04", "01", "001")
    assert campos["take2"] == "001"
    assert campos["nome_original"] == "PROJETO A - 05-04 C4 P1-T001.WAV"
    nomes = {c["nome"] for c in r["catalogo"]}
    assert {"cena", "take", "scene", "log_note", "nome_original"} <= nomes


def test_colunas_json_quebrado_nao_derruba():
    c = renomear.colunas_do_item({"node_id": "1", "nome": "x", "colunas_json": "{lixo"})
    assert c == {"Name": "x"}


# ── os comandos ───────────────────────────────────────────────────────────────

@pytest.fixture
def respostas(monkeypatch, diario):
    linhas: list[dict] = []
    monkeypatch.setattr(M, "_write_line", lambda s: linhas.append(json.loads(s)))
    return linhas


def _final(linhas):
    return [l for l in linhas if "event" not in l][-1]


def _ler(respostas, projeto="D:/P/X.prproj"):
    M.handle_command({"id": "S1", "command": "premiere_rename_scan", "params": {
        "projeto": projeto,
        "itens": [_item("000f4241", "PROJETO A - 05-04 C4 P1-T001.WAV"),
                  _item("000f4242", "PROJETO A - 05-04 C4 P1-T002.WAV",
                        bext=BEXT.replace("TAKE=001", "TAKE=002"))]}})
    return _final(respostas)


def test_ler_planejar_desfazer(respostas):
    r = _ler(respostas)
    assert r["ok"] and len(r["data"]["itens"]) == 2

    M.handle_command({"id": "P1", "command": "premiere_rename_plan", "params": {
        "levantamento_id": "S1", "padrao": "C%{cena}_T%{take2}", "versao": "23.2.0"}})
    p = _final(respostas)
    assert p["ok"], p
    plano = p["data"]["plano"]
    assert [x["node_id"] for x in plano] == ["000f4241", "000f4242"]
    assert [x["nome_novo"] for x in plano] == ["C04_T001", "C04_T002"]

    # o journal existe ANTES de o painel tocar em nada, marcado como do Premiere
    lote = desfazer.lote(p["data"]["undo_id"], nle="premiere")
    assert lote and lote["nle"] == "premiere" and lote["projeto"] == "D:/P/X.prproj"
    assert desfazer.lote(p["data"]["undo_id"]) is None, "o desfazer do Avid não pode vê-lo"

    M.handle_command({"id": "D1", "command": "premiere_rename_done", "params": {
        "undo_id": p["data"]["undo_id"], "aplicados": 2}})
    assert _final(respostas)["ok"]

    # desfazer: só neste projeto
    M.handle_command({"id": "U0", "command": "premiere_rename_undo",
                      "params": {"projeto": "D:/OUTRO.prproj"}})
    assert _final(respostas)["ok"] is False
    M.handle_command({"id": "U1", "command": "premiere_rename_undo",
                      "params": {"projeto": "D:/P/X.prproj"}})
    u = _final(respostas)["data"]
    assert [(x["nome_atual"], x["nome_novo"]) for x in u["plano"]] == [
        ("C04_T001", "PROJETO A - 05-04 C4 P1-T001.WAV"),
        ("C04_T002", "PROJETO A - 05-04 C4 P1-T002.WAV")]
    M.handle_command({"id": "D2", "command": "premiere_rename_done", "params": {
        "undo_id": u["undo_id"], "aplicados": 2, "desfeito": True}})
    assert desfazer.lote(u["undo_id"], nle="premiere")["revertido"] is True

    # e a próxima leitura conhece o nome ORIGINAL
    _ler(respostas)
    M.handle_command({"id": "P2", "command": "premiere_rename_plan", "params": {
        "levantamento_id": "S1", "padrao": "BKP_%{nome_original}", "indices": [1]}})
    p2 = _final(respostas)["data"]["plano"]
    assert p2 == [{"node_id": "000f4242", "nome_atual": "PROJETO A - 05-04 C4 P1-T002.WAV",
                   "nome_novo": "BKP_PROJETO A - 05-04 C4 P1-T002.WAV"}]


def test_padrao_invalido_nao_grava_journal(respostas, diario):
    _ler(respostas)
    M.handle_command({"id": "P", "command": "premiere_rename_plan", "params": {
        "levantamento_id": "S1", "padrao": "%{naoexiste}"}})
    assert _final(respostas)["ok"] is False
    assert desfazer.historico(nle="premiere") == []


def test_o_aplicar_do_avid_recusa_a_leitura_do_premiere(respostas):
    _ler(respostas)
    M.handle_command({"id": "A", "command": "avid_rename_apply", "params": {
        "levantamento_id": "S1", "padrao": "X"}})
    r = _final(respostas)
    assert r["ok"] is False and "Premiere" in r["error"]


def test_scan_vazio_recusa(respostas):
    M.handle_command({"id": "S", "command": "premiere_rename_scan", "params": {"itens": []}})
    assert _final(respostas)["ok"] is False


# ── o metadado vazio não trava (autor, 2026-09-17) ───────────────────────────

def _sem_cena(node, nome):
    return {"node_id": node, "nome": nome, "tipo": "clip", "colunas_json": SEM_CENA,
            "xmp": {"scene": "", "take": "", "bext": ""}}


SEM_CENA = json.dumps([
    {"ColumnName": "Name", "ColumnValue": "20260101_CAM0002.mov"},
    {"ColumnName": "Frame Rate", "ColumnValue": "23.98 fps"},
    {"ColumnName": "Scene", "ColumnValue": ""},
])


def test_material_sem_cena_ainda_oferece_cena_vazia(diario):
    r = renomear.levantar("P", [_sem_cena("1", "20260101_CAM0002.mov")])
    campos = r["itens"][0]["campos"]
    assert campos["cena"] == "" and campos["take2"] == "" and campos["scene"] == ""
    assert "cena" in {c["nome"] for c in r["catalogo"]}


def test_padrao_com_campo_vazio_nao_bloqueia_e_o_vazio_total_mantem_o_nome(respostas):
    M.handle_command({"id": "S", "command": "premiere_rename_scan", "params": {
        "projeto": "P", "itens": [_sem_cena("1", "20260101_CAM0002.mov")]}})
    fichas = [i["campos"] for i in _final(respostas)["data"]["itens"]]

    M.handle_command({"id": "V1", "command": "avid_name_preview", "params": {
        "padrao": "%{cena} %{frame_rate}", "fichas": fichas}})
    r = _final(respostas)["data"]
    assert r["bloqueado"] is False
    assert r["linhas"][0]["nome"] == "23.98 fps"          # nada no lugar da cena
    assert r["linhas"][0]["vazios"] == ["cena"]

    M.handle_command({"id": "V2", "command": "avid_name_preview", "params": {
        "padrao": "%{cena}", "fichas": fichas}})
    r = _final(respostas)["data"]
    assert r["bloqueado"] is False
    assert r["linhas"][0] == {**r["linhas"][0], "nome": "20260101_CAM0002.mov",
                              "de_origem": True}

    M.handle_command({"id": "P", "command": "premiere_rename_plan", "params": {
        "levantamento_id": "S", "padrao": "%{cena}"}})
    plano = _final(respostas)["data"]["plano"]
    assert plano[0]["nome_novo"] == "20260101_CAM0002.mov"
