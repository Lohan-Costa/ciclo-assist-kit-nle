"""O Premiere pela ponte: fila, take e recorte — sem Premiere, com o painel simulado.

Plano `docs/plano/2026-09-17-premiere.md`, P2–P4. O que só o Premiere de verdade responde
está em `spikes/o_premiere_por_dentro.py`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
from pathlib import Path

import pytest

from cicloassist import nle
from cicloassist.avid import escopo as ESC
from cicloassist.avid.take import TakeErro
from cicloassist.midia import cache as C
from cicloassist.midia import identidade as I
from cicloassist.nle import premiere as P
from cicloassist.nle.premiere import ponte as PT
from cicloassist.servico import rotas  # noqa: F401
from cicloassist.servico.http import ROTAS

TICKS = P.TICKS_POR_SEGUNDO
tem_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="sem ffmpeg nesta máquina")


@pytest.fixture(autouse=True)
def limpo(monkeypatch):
    PT.esquecer()
    P.esquecer()
    I.esquecer()
    C._indices.clear()
    monkeypatch.setattr(nle, "_atual", "premiere")
    yield
    PT.esquecer()
    P.esquecer()


# ── a ponte ──────────────────────────────────────────────────────────────────

def _painel(respostas: dict[str, object], vezes: int = 1):
    """Um painel de mentira: pega o pedido da fila e responde como o `host.jsx`."""
    vistos: list[str] = []

    def rodar():
        for _ in range(vezes):
            p = PT.proximo(espera=5)
            if not p:
                return
            vistos.append(p["expr"])
            funcao = p["expr"].split("(", 1)[0]
            r = respostas[funcao]
            PT.responder(p["id"], r if isinstance(r, str) else json.dumps(r))

    PT.proximo(espera=0)  # a primeira batida: o painel está aberto
    t = threading.Thread(target=rodar, daemon=True)
    t.start()
    return vistos


def test_sem_painel_a_ponte_recusa_na_hora_dizendo_o_que_fazer():
    with pytest.raises(PT.PremiereIndisponivel, match="feche e abra o Premiere|fechar e abrir o Premiere"):
        PT.chamar("cicloProjeto")


def test_a_ida_e_volta_devolve_o_json_do_host():
    vistos = _painel({"cicloItens": {"bin": "CAM A", "itens": []}})
    assert PT.chamar("cicloItens", 'CAM "A"', True) == {"bin": "CAM A", "itens": []}
    # ⛔ Argumento vira LITERAL: aspas e barras não fecham a string do ExtendScript.
    assert vistos == ['cicloItens("CAM \\"A\\"", true)']


def test_o_gesto_do_editor_passa_na_frente_do_trabalho_de_fundo():
    """⛔⛔ A ponte é fila de UM pedido por vez, e é a MESMA do chat. MEDIDO em 2026-09-23
    no Premiere do editor: um pedido do painel esperou **12,94 s na fila**, atrás dos
    pulsos da vigia — trabalho que ninguém pediu segurando a pergunta de quem pediu.

    ⚠️ Sobre a fila em MÃO, e não pela `chamar()`: com threads de verdade, o ajudante
    `_painel` de outro teste pode ter uma thread viva puxando da fila global, e o teste
    falharia por uma corrida que não tem nada a ver com o que ele mede. (Aconteceu: 2 de 4
    rodadas da suíte.)
    """
    def pedido(nome: str, de_fundo: bool) -> PT._Pedido:
        return PT._Pedido(id=nome, expr=f"{nome}()", de_fundo=de_fundo)

    fila: list = []
    PT.enfileirar(pedido("cicloVigia", True), fila)
    PT.enfileirar(pedido("cicloMidias", True), fila)
    PT.enfileirar(pedido("cicloProjeto", False), fila)      # o editor, que chega DEPOIS

    assert [p.id for p in fila] == ["cicloProjeto", "cicloVigia", "cicloMidias"]

    # ⚠️ Entre IGUAIS, a ordem de chegada manda: quem pergunta duas coisas as recebe na
    #   ordem em que pediu, e um pedido de fundo não é ultrapassado por outro de fundo.
    PT.enfileirar(pedido("cicloItem", False), fila)
    PT.enfileirar(pedido("cicloVigia2", True), fila)
    assert [p.id for p in fila] == ["cicloProjeto", "cicloItem",
                                    "cicloVigia", "cicloMidias", "cicloVigia2"]


def test_quem_e_de_fundo_e_a_THREAD():
    """⭐⭐ A vigia e as descrições passam por cinco camadas antes de chegar à ponte;
    levar um parâmetro por toda a corrente significaria esquecer uma delas um dia — e aí
    um pedido de fundo se passaria por gesto do editor."""
    assert PT.sou_de_fundo() is False
    pronto = threading.Event()
    visto = []

    def thread_de_fundo() -> None:
        PT.marcar_de_fundo()
        visto.append(PT.sou_de_fundo())
        pronto.set()

    threading.Thread(target=thread_de_fundo, daemon=True).start()
    assert pronto.wait(5) and visto == [True]
    # ⛔ E não vaza para quem não pediu: a marca é DESTA thread.
    assert PT.sou_de_fundo() is False


def test_a_vigia_recua_quando_o_premiere_esta_ocupado():
    """⛔⛔ MEDIDO em 2026-09-23: `cicloVigia` — que o banco registra em 3 ms e que só lê um
    contador — levou **5,20 s** dentro do Premiere. Com pulso fixo de 3 s, a fila da ponte
    nunca esvazia.

    ⭐ Recuar é a resposta CERTA: Premiere ocupado é exatamente quando processar o que
    acabou de ser importado importa menos que não atrapalhar.
    """
    from cicloassist.servico import vigia as V

    # Premiere saudável: o freio não existe.
    assert V._proximo_pulso(0.003) == V.PULSO_S
    assert V._proximo_pulso(0.3) == V.PULSO_S
    # Premiere ocupado: a vigia nunca toma mais que `OCUPACAO_MAXIMA` da ponte.
    lento = V._proximo_pulso(5.0)
    assert lento > 40
    assert 5.0 / (5.0 + lento) <= V.OCUPACAO_MAXIMA + 0.001


def test_erro_do_host_vira_excecao_com_a_frase_dele():
    _painel({"cicloItem": {"erro": "não achei o item 42"}})
    with pytest.raises(PT.ExtendScriptFalhou, match="não achei o item 42"):
        PT.chamar("cicloItem", "42")


def test_excecao_do_extendscript_manda_recarregar():
    _painel({"cicloBins": "EvalScript error."})
    with pytest.raises(PT.ExtendScriptFalhou, match="Reload"):
        PT.chamar("cicloBins")


def test_premiere_que_PEGOU_o_pedido_e_nao_respondeu_estoura_o_prazo():
    """⚠️ Estourar é só depois de o Premiere receber: um diálogo aberto ali trava tudo."""
    PT.proximo(espera=0)

    def levar():
        PT.proximo(espera=2)  # o painel pega e não responde (o Premiere travou)

    threading.Thread(target=levar, daemon=True).start()
    with pytest.raises(PT.PremiereIndisponivel, match="não respondeu"):
        PT.chamar("cicloBins", prazo=0.4)


@pytest.mark.parametrize("nome", ["alert('x');cicloBins", "a b", "x.y", ""])
def test_so_nome_de_funcao_vira_expressao(nome):
    with pytest.raises(ValueError):
        PT.expressao(nome)


def test_as_rotas_da_ponte_exigem_a_nossa_pagina():
    for chave in (("GET", "/premiere/pedido"), ("POST", "/premiere/resposta")):
        _, exige = ROTAS[chave]
        assert exige, chave


# ── o take ───────────────────────────────────────────────────────────────────

def _fingir(monkeypatch, resposta: dict):
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda funcao, *a, **k: resposta)


def test_sequencia_e_recusada_com_a_frase_certa(monkeypatch):
    _fingir(monkeypatch, {"nome": "CENA 7", "especie": "sequencia", "id": "000f1"})
    with pytest.raises(TakeErro, match="sequência"):
        P.resolver_take("", "000f1")


def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=120)


@tem_ffmpeg
def test_clipe_ja_convertido_ganha_entrada_PROPRIA_e_copia_o_trabalho(monkeypatch, tmp_path):
    """⭐⭐ **A premissa, na forma que o editor decidiu em 2026-09-21.**

    O original no Premiere acha o que já foi processado — e aí **nasce uma entrada dele**,
    no banco dele, que COPIA o trabalho. Não vira apelido da entrada do outro editor.

    ⛔⛔ Era isso que vazava: com apelido, o `.mp4` do Premiere passava a responder pela
    pasta do Avid, e a lista mostrava o nome da bin do Avid e caminhos de
    `Avid MediaFiles`. Medido no projeto dele: `B001_03150112_C001.mp4` caía em
    `B001_03150112_C001`, cujos arquivos são três OP-Atom.

    ⛔ E o aviso não cita o Media Composer: o editor não quer saber de onde veio, quer
    saber que não vai esperar de novo.
    """
    original = tmp_path / "PLANO01.mov"
    conv = tmp_path / "V01.mxf"
    for destino, codec in ((original, "prores_ks"), (conv, "mpeg2video")):
        _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24000/1001", "-t", "3",
                "-c:v", codec, "-timecode", "01:00:00:00", str(destino))
    master = C.Midia("060a2b340101010501010f10130000001a1644631260a3063853d011e5e7034e",
                     rotulo={"nome": "PLANO01.new.01", "tipo": "video", "arquivos": [str(conv)]})
    master.pasta  # noqa: B018
    # ⭐ Com trabalho pronto de verdade: é ELE que tem de atravessar, e é o que o editor
    #   pediu — "a nova entrada não vai processar, vai copiar as informações".
    master.guardar_quadro(36, bytes.fromhex("ffd8") + b"jpeg")
    master.guardar_transcricao([{"texto": "ola", "inicio": 0.0, "fim": 1.0}])
    master.registrar_gerador("transcricao", {"modelo": "de-mentira"})

    _fingir(monkeypatch, {"nome": "PLANO01.mov", "especie": "clipe", "id": "000f2",
                          "bin": "CAM A", "arquivo": str(original), "fps": 23.976,
                          "entrada": "0", "saida": str(3 * TICKS)})
    take = P.resolver_take("CAM A", "000f2")
    assert take.imagem is not None and take.som is None
    assert take.duracao_frames == 72

    # ⛔ A chave é DELE, não a do master do outro banco.
    assert take.imagem.chave != master.chave
    minha = C.Midia(take.imagem.chave)
    assert minha.existe and minha.origem == "premiere"
    assert [Path(a).name for a in minha.manifesto()["arquivos"]] == ["PLANO01.mov"]
    # ⭐ E ela sabe de quem aproveitou, com a medida — procedência em todo item.
    de = minha.manifesto().get("aproveitado_de") or {}
    assert de.get("chave") == master.chave and de.get("origem") == "avid"
    assert float(de.get("medida") or 0) >= I.PISO_IMAGEM

    # ⭐⭐ O trabalho atravessou: quadro e transcrição estão aqui, sem reprocessar nada.
    assert minha.tem_quadro(36) and len(minha.ler_transcricao()) == 1
    assert de.get("copiados")
    # ⛔ E a receita foi junto: sem ela `precisa_refazer` compararia contra {} e a fila
    #   refaria tudo na primeira passada — a cópia não teria servido para nada.
    assert minha.ler_gerador("transcricao") == {"modelo": "de-mentira"}

    assert any("aproveitei o que existia" in a for a in take.avisos)
    assert not any("Media Composer" in a for a in take.avisos)


@tem_ffmpeg
def test_merged_clip_tem_imagem_e_som_de_arquivos_diferentes(monkeypatch, tmp_path):
    cam = tmp_path / "A001.mov"
    wav = tmp_path / "C7 P2-T002.wav"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24000/1001", "-t", "2",
            "-f", "lavfi", "-i", "sine=d=2", "-c:v", "prores_ks", "-c:a", "pcm_s16le",
            "-shortest", str(cam))
    _ffmpeg("-f", "lavfi", "-i", "sine=f=300:d=3", str(wav))
    seg = TICKS // 24000 * 1001  # ticks de um quadro a 23,976
    _fingir(monkeypatch, {
        "nome": "C07_P02-T002", "especie": "merged", "id": "000f9", "bin": "CENAS",
        "pedacos": [
            {"especie": "imagem", "arquivo": str(cam), "nome": "A001.mov",
             "inicio_na_seq": "0", "fim_na_seq": str(24 * seg), "entrada_na_midia": "0"},
            {"especie": "som", "arquivo": str(cam), "nome": "A001.mov",
             "inicio_na_seq": "0", "fim_na_seq": str(24 * seg), "entrada_na_midia": "0"},
            {"especie": "som", "arquivo": str(wav), "nome": "C7 P2-T002.wav",
             "inicio_na_seq": "0", "fim_na_seq": str(24 * seg),
             "entrada_na_midia": str(10 * seg)},
        ]})
    take = P.resolver_take("CENAS", "000f9")
    assert Path(take.imagem.arquivos[0]).name == "A001.mov"
    assert Path(take.som.arquivos[0]).name == "C7 P2-T002.wav"  # o gravador, não o scratch
    assert take.imagem.inicio_frames == 0 and take.som.inicio_frames == 10
    assert take.duracao_frames == 24
    assert (take.cena, take.plano, take.take) == ("C7", "P2", "T002")
    assert take.imagem.chave != take.som.chave


# ── o recorte ────────────────────────────────────────────────────────────────

def test_sem_painel_o_recorte_e_o_BANCO_do_premiere(monkeypatch, tmp_path):
    """⭐⭐ **A regra "não sei ≠ nenhuma" ganhou um TETO** (decisão do editor, 2026-09-21).

    Ela existe para que desconhecer o projeto não esconda o acervo do editor; ela nunca
    autorizou mostrar o acervo de OUTRO editor. Até aqui, o Premiere sem painel caía em
    `chaves=None` — sem filtro — e a busca devolvia as 332 mídias do cache, com nome de
    bin do Avid e caminho de `Avid MediaFiles` na lista.

    ⇒ Sem projeto, a resposta é o banco do Premiere INTEIRO (que pode ser vazio); nunca
    o do Media Composer.
    """
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    C._indices.clear()
    do_avid = C.Midia("a" * 64, rotulo={"nome": "DA BIN DO AVID"})
    do_avid.pasta  # noqa: B018 — nascer é escrever
    recorte = P.escopo_agora()

    assert recorte.chaves is not None, "o banco é um fato, não um palpite"
    assert "a" * 64 not in recorte.chaves, "material do Avid não entra no banco do Premiere"
    assert recorte.origem == "sem-projeto" and recorte.editor == "premiere"
    # ⛔ E o aviso não pode citar o Media Composer.
    assert "Media Composer" not in recorte.aviso


def test_o_recorte_sao_as_chaves_dos_arquivos_do_projeto(monkeypatch, tmp_path):
    a = tmp_path / "a.wav"
    a.write_bytes(b"a" * 100)
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(I, "sondar", lambda arq: {"umid": ""})

    def chamar(funcao, *args, **k):
        if funcao == "cicloProjeto":
            return {"caminho": "D:/proj/X.prproj"}
        return {"arquivos": [str(a), str(tmp_path / "sumiu.mov")]}

    monkeypatch.setattr(PT, "chamar", chamar)
    I.impressao(a)  # ⭐ o recorte usa a chave JÁ CONHECIDA: não lê 8 MB por arquivo
    # ⛔⛔ O projeto estreita DENTRO do banco: um arquivo que só existe como entrada do
    #    AVID não é material deste banco, por mais que o projeto o aponte.
    nascida = C.Midia(I.impressao(a), origem="premiere", rotulo={"nome": a.name})
    nascida.pasta  # noqa: B018
    recorte = P.escopo_agora()
    assert recorte.chaves == {I.impressao(a)}
    assert recorte.origem == "projeto" and recorte.nome_do_projeto == "X.prproj"
    assert nle.escopo_agora() is recorte  # guardado, e é o do editor da conversa


def test_projeto_aberto_segue_o_editor_da_conversa(monkeypatch):
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda *a, **k: {"caminho": "D:/p/Y.prproj"})
    assert nle.projeto_aberto() == "D:/p/Y.prproj"
    monkeypatch.setattr(nle, "_atual", "avid")
    assert nle.projeto_aberto() == ESC.SEM_PROJETO  # o conftest diz: nenhum MC aberto


def test_persona_do_premiere_nao_fala_do_media_composer():
    from cicloassist.motor.claude import PERSONA, persona

    texto = persona("premiere")
    assert "Premiere" in texto and "Media Composer" not in texto
    assert persona("avid") == PERSONA


# ── o subclipe (medido no 23.2 pelo spikes/o_painel_no_premiere.py) ──────────

META_SUBCLIPE = (
    "<premierePrivateProjectMetaData:Column.Intrinsic.MediaStart>23:16:49:10"
    "</premierePrivateProjectMetaData:Column.Intrinsic.MediaStart>"
    "<premierePrivateProjectMetaData:Column.Intrinsic.SubclipStart>23:16:49:10"
    "</premierePrivateProjectMetaData:Column.Intrinsic.SubclipStart>"
    "<premierePrivateProjectMetaData:Column.Intrinsic.SubclipDuration>00:00:02:23"
    "</premierePrivateProjectMetaData:Column.Intrinsic.SubclipDuration>")


def test_o_recorte_do_subclipe_sai_dos_metadados_e_do_tc_do_arquivo():
    from fractions import Fraction

    taxa = Fraction(24000, 1001)
    # O MediaStart do subclipe "hard" é o do subclipe; a base é o TC do ARQUIVO.
    assert P.recorte_do_subclipe(META_SUBCLIPE, "23:16:47:11", taxa) == (47, 71)
    assert P.recorte_do_subclipe("<x/>", "23:16:47:11", taxa) is None
    assert P.tc_em_quadros("01:00:00;00", Fraction(30000, 1001)) is None  # drop-frame


def test_subclipe_do_premiere_vira_take_com_o_recorte(monkeypatch, tmp_path):
    arq = tmp_path / "PANA.mov"
    arq.write_bytes(b"x" * 100)
    monkeypatch.setattr(I, "sondar", lambda a: {"umid": "", "tipo": "video", "tc": "23:16:47:11",
                                                  "quadros": 1236, "pistas_de_som": 0})
    _fingir(monkeypatch, {"nome": "SUB", "especie": "clipe", "id": "000fa", "bin": "CENAS",
                          "arquivo": str(arq), "fps": 23.976, "entrada": "0",
                          "saida": str(13094905824000), "metadados": META_SUBCLIPE})
    take = P.resolver_take("CENAS", "000fa")
    assert take.especie == "subclipe"
    assert take.imagem.inicio_frames == 47 and take.duracao_frames == 71


# ── organizar o projeto (a escrita) ──────────────────────────────────────────

ARVORE = [
    {"nome": "D01_230403", "id": "1", "especie": "bin", "bin": ""},
    {"nome": "B01", "id": "2", "especie": "bin", "bin": "D01_230403"},
    {"nome": "A001.mp4", "id": "3", "especie": "clipe", "bin": "D01_230403/B01"},
    {"nome": "D02_230405", "id": "4", "especie": "bin", "bin": ""},
]


def _arvore(monkeypatch, itens=ARVORE):
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda funcao, *a, **k: {"itens": list(itens)})


def test_o_plano_bom_passa_na_conferencia(monkeypatch):
    _arvore(monkeypatch)
    assert P.conferir_organizacao([
        {"acao": "criar_bin", "nome": "MIDIAS"},
        # ⭐ mover para a bin que o MESMO plano acabou de criar
        {"acao": "mover", "item": "1", "para": "MIDIAS"},
        {"acao": "mover", "item": "4", "para": "MIDIAS"},
        {"acao": "renomear", "item": "3", "nome": "C07_P02-T003"},
    ]) == ""


def test_id_que_nao_existe_volta_ao_modelo_antes_do_cartao(monkeypatch):
    """⭐ O editor nunca aprova algo para ver falhar (`registro.ferramenta(conferir=…)`)."""
    _arvore(monkeypatch)
    recusa = P.conferir_organizacao([{"acao": "mover", "item": "999", "para": "1"}])
    assert "não achei o item '999'" in recusa
    assert "listar_itens_do_premiere" in recusa


def test_bin_dentro_de_si_mesma_e_recusada(monkeypatch):
    """⛔ O Premiere não reclama, e a bin some da árvore do editor."""
    _arvore(monkeypatch)
    assert "não pode ir para dentro de si mesma" in P.conferir_organizacao(
        [{"acao": "mover", "item": "1", "para": "D01_230403/B01"}])
    assert "não pode ir para dentro de si mesma" in P.conferir_organizacao(
        [{"acao": "mover", "item": "1", "para": "1"}])


def test_nome_de_bin_com_barra_e_recusado(monkeypatch):
    _arvore(monkeypatch)
    assert "não leva barra" in P.conferir_organizacao(
        [{"acao": "criar_bin", "nome": "MIDIAS/D01"}])


def test_plano_vazio_ou_gigante_nao_vai_ao_cartao(monkeypatch):
    _arvore(monkeypatch)
    assert "Diga as operações" in P.conferir_organizacao([])
    muitas = [{"acao": "criar_bin", "nome": f"B{n}"} for n in range(P.MAXIMO_DE_OPERACOES + 1)]
    assert "lotes" in P.conferir_organizacao(muitas)


def test_acao_desconhecida_e_recusada(monkeypatch):
    _arvore(monkeypatch)
    assert "a ação tem de ser" in P.conferir_organizacao([{"acao": "apagar", "item": "3"}])


def test_o_plano_vira_linhas_que_nao_quebram_com_nome_esquisito():
    """⛔ Nada do que o modelo escreve vira código: o plano viaja como texto tabulado."""
    linha = P._texto_da_operacao({"acao": "criar_bin", "nome": 'MÍDIAS "A", 1', "dentro_de": ""})
    assert linha == 'criar_bin\tMÍDIAS "A", 1\t'
    assert P._texto_da_operacao({"acao": "mover", "item": "3", "para": "MIDIAS"}) == \
        "mover\t3\tMIDIAS"


def test_organizar_manda_o_plano_e_conta_o_que_falhou(monkeypatch):
    vistos = []

    def chamar(funcao, *args, **k):
        vistos.append((funcao, args))
        if funcao == "cicloOrganizar":
            return {"feitos": [{"acao": "criar_bin", "nome": "MIDIAS", "id": "9"},
                               {"acao": "mover", "erro": "não achei o item 7"}]}
        return {"bins": [{"caminho": "MIDIAS"}]}

    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", chamar)
    # A conferência do clique roda contra a árvore de AGORA; aqui o alvo é o envio.
    monkeypatch.setattr(P, "conferir_organizacao", lambda *a, **k: "")
    from cicloassist.mcp.ferramentas import premiere as FP

    r = FP.organizar_o_projeto([{"acao": "criar_bin", "nome": "MIDIAS"},
                                {"acao": "mover", "item": "7", "para": "MIDIAS"}])
    assert vistos[0] == ("cicloOrganizar", ("criar_bin\tMIDIAS\t\nmover\t7\tMIDIAS",))
    assert r["operacoes"] == 2 and r["feitas"] == 1
    assert r["falharam"][0]["erro"] == "não achei o item 7"
    # ⭐ Como o projeto FICOU, não o que foi pedido.
    assert r["bins_agora"] == ["MIDIAS"]


def test_organizar_so_existe_no_premiere_e_passa_pelo_portao():
    from cicloassist.mcp.registro import FERRAMENTAS

    f = FERRAMENTAS["organizar_o_projeto"]
    assert f.escreve and f.nles == ("premiere",) and f.conferir is not None


def test_o_prazo_conta_de_quando_o_premiere_RECEBE_o_pedido():
    """⛔ O painel roda um pedido por vez. Se o prazo contasse da fila, a segunda chamada
    morreria dizendo "o Premiere não respondeu" sobre um pedido que ele nem tinha visto."""
    PT.proximo(espera=0)  # o painel está aberto
    respostas = {}

    def segundo():
        respostas["r"] = PT.chamar("cicloBins", prazo=0.5)

    t = threading.Thread(target=segundo, daemon=True)
    t.start()
    time.sleep(1.2)  # muito mais que o prazo: ele está ESPERANDO A VEZ, não o Premiere
    p = PT.proximo(espera=2)
    PT.responder(p["id"], json.dumps({"bins": []}))
    t.join(timeout=3)
    assert respostas.get("r") == {"bins": []}


def test_painel_que_some_no_meio_da_fila_nao_deixa_a_chamada_pendurada(monkeypatch):
    """O painel fechou (ou recarregou) com o pedido ainda na fila: a chamada não fica
    pendurada esperando um prazo que nem começou a contar."""
    vivo = {"sim": True}
    monkeypatch.setattr(PT, "painel_vivo", lambda: vivo["sim"])

    def sumir():
        time.sleep(0.3)
        vivo["sim"] = False

    threading.Thread(target=sumir, daemon=True).start()
    with pytest.raises(PT.PremiereIndisponivel, match="parou de responder"):
        PT.chamar("cicloBins", prazo=30)


def test_nome_com_tabulacao_ou_quebra_de_linha_e_recusado(monkeypatch):
    """⛔⛔ O plano viaja tabulado: um nome com \t ou \n viraria uma operação A MAIS, que o
    editor não viu no cartão. É recusado antes dele, e o texto nunca sai sujo daqui."""
    _arvore(monkeypatch)
    recusa = P.conferir_organizacao([
        {"acao": "criar_bin", "nome": "MIDIAS\nrenomear\t1\tHACK"}])
    assert "tabulação ou quebra de linha" in recusa
    assert "nome" in recusa
    # E, mesmo que algo escape, o texto sai higienizado.
    assert P._texto_da_operacao({"acao": "criar_bin", "nome": "A\tB\nC"}) == "criar_bin\tA B C\t"


def test_o_projeto_que_mudou_entre_o_cartao_e_o_clique_nao_executa(monkeypatch):
    """⛔⛔ O cartão espera o tempo que o editor quiser (ADR 0008). Se ele mexer nas bins
    nesse meio, o plano aprovado pode virar outra coisa — aqui, bin dentro de si mesma."""
    _arvore(monkeypatch)
    from cicloassist.mcp.ferramentas import premiere as FP

    r = FP.organizar_o_projeto([{"acao": "mover", "item": "1", "para": "D01_230403/B01"}])
    assert r["nada_foi_feito"] and "o projeto mudou desde que você aprovou" in r["erro"]


def test_projeto_com_midia_e_nenhuma_chave_conhecida_cai_no_banco(monkeypatch, tmp_path):
    """⛔⛔ Volume desmontado, caminhos velhos: não se pode concluir "este projeto está
    vazio". Antes isso virava `None` (sem filtro) e entregava o cache inteiro; agora cai
    no BANCO do Premiere, que é o maior conjunto honesto — e nunca no do Avid."""
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path))
    C._indices.clear()
    minha = C.Midia("b" * 64, origem="premiere", rotulo={"nome": "minha.mp4"})
    minha.pasta  # noqa: B018
    do_avid = C.Midia("c" * 64, rotulo={"nome": "DO AVID"})
    do_avid.pasta  # noqa: B018

    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda funcao, *a, **k: (
        {"caminho": "D:/p/Z.prproj"} if funcao == "cicloProjeto"
        else {"arquivos": ["D:/sumiu/a.mov"]}))
    chaves = P.escopo_agora().chaves
    assert chaves == {"b" * 64}


# ── o pedido real do editor (2026-09-17, 19h): esvaziar as pastas de cartão ──

CARTOES = [
    {"nome": "DIARIA", "id": "d", "especie": "bin", "bin": ""},
    {"nome": "D01", "id": "1", "especie": "bin", "bin": "DIARIA"},
    {"nome": "CAM A", "id": "c", "especie": "bin", "bin": "DIARIA/D01"},
    {"nome": "A01", "id": "a1", "especie": "bin", "bin": "DIARIA/D01/CAM A"},
    {"nome": "clipe1.mov", "id": "x1", "especie": "clipe", "bin": "DIARIA/D01/CAM A/A01"},
    {"nome": "clipe2.mov", "id": "x2", "especie": "clipe", "bin": "DIARIA/D01/CAM A/A01"},
]


def test_tirar_os_clipes_do_cartao_e_apagar_a_pasta_no_MESMO_plano(monkeypatch):
    """⭐⭐ O pedido do editor em campo. Sem simular o plano, "apague a pasta vazia" seria
    recusado — na foto do começo ela ainda está cheia."""
    _arvore(monkeypatch, CARTOES)
    assert P.conferir_organizacao([
        {"acao": "mover", "item": "x1", "para": "DIARIA/D01/CAM A"},
        {"acao": "mover", "item": "x2", "para": "DIARIA/D01/CAM A"},
        {"acao": "apagar_bin_vazia", "item": "DIARIA/D01/CAM A/A01"},
    ]) == ""


def test_apagar_bin_que_ainda_tem_clipe_e_recusado(monkeypatch):
    """⛔ Só VAZIA. Apagar bin com mídia dentro é decisão do editor, no Premiere."""
    _arvore(monkeypatch, CARTOES)
    recusa = P.conferir_organizacao([
        {"acao": "mover", "item": "x1", "para": "DIARIA/D01/CAM A"},
        {"acao": "apagar_bin_vazia", "item": "DIARIA/D01/CAM A/A01"},
    ])
    assert "ainda tem 1 item(ns) quando chegar a vez dela" in recusa


def test_mexer_numa_bin_ja_apagada_pelo_plano_e_recusado(monkeypatch):
    _arvore(monkeypatch, CARTOES)
    recusa = P.conferir_organizacao([
        {"acao": "mover", "item": "x1", "para": "DIARIA/D01/CAM A"},
        {"acao": "mover", "item": "x2", "para": "DIARIA/D01/CAM A"},
        {"acao": "apagar_bin_vazia", "item": "DIARIA/D01/CAM A/A01"},
        {"acao": "mover", "item": "c", "para": "DIARIA/D01/CAM A/A01"},
    ])
    assert "não achei a bin 'DIARIA/D01/CAM A/A01'" in recusa


def test_a_arvore_vem_numa_chamada_so_e_da_para_pedir_um_galho(monkeypatch):
    """⛔⛔ MEDIDO em campo: sem isto o modelo pediu bin a bin, repetiu as mesmas onze
    quatro vezes e gastou 20 minutos sem responder nada ao editor."""
    _arvore(monkeypatch, CARTOES)
    from cicloassist.mcp.ferramentas import premiere as FP

    tudo = FP.arvore_do_premiere()
    assert tudo["total"] == len(CARTOES)
    galho = FP.arvore_do_premiere(bin="DIARIA/D01/CAM A")
    assert {i["nome"] for i in galho["itens"]} == {"A01", "clipe1.mov", "clipe2.mov"}
    so_pastas = FP.arvore_do_premiere(sem_clipes=True)
    assert all(i["especie"] == "bin" for i in so_pastas["itens"])


def test_arvore_grande_diz_quanto_ficou_de_fora(monkeypatch):
    from cicloassist.mcp.ferramentas import premiere as FP

    muitos = [{"nome": f"c{n}.mov", "id": str(n), "especie": "clipe", "bin": "X"}
              for n in range(FP.ITENS_NA_ARVORE + 30)]
    _arvore(monkeypatch, muitos)
    r = FP.arvore_do_premiere()
    assert len(r["itens"]) == FP.ITENS_NA_ARVORE and r["ficaram_de_fora"] == 30
    assert "sem_clipes" in r["aviso"]


def test_nada_selecionado_explica_em_vez_de_devolver_zero_seco(monkeypatch):
    """⛔⛔ O laço de 46 chamadas em campo nasceu de um `quantidade: 0` sem explicação."""
    monkeypatch.setattr(PT, "painel_vivo", lambda: True)
    monkeypatch.setattr(PT, "chamar", lambda funcao, *a, **k: (
        {"bin": "CAM A", "itens": []} if a[1] else {"bin": "CAM A", "itens": [
            {"nome": "clipe1.mov", "id": "x1", "especie": "clipe", "bin": "CAM A"}]}))
    from cicloassist.mcp.ferramentas import premiere as FP

    r = FP.listar_itens_do_premiere(bin="CAM A", apenas_selecionados=True)
    assert r["quantidade"] == 0 and r["itens_na_bin"] == 1
    assert "Não há NADA selecionado" in r["aviso"] and "sem apenas_selecionados" in r["aviso"]
