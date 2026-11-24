"""Separar as falas de uma cena: a forma, as conferências, a bin, e o portão que confere antes.

Cada conferência de `plano/falas.py` fecha um defeito que uma verificação ingênua premiaria —
os testes abaixo são, cada um, o pedido degenerado que tem de REPROVAR.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import avb
import pytest

from cicloassist.avid import timeline as T
from cicloassist.mcp import registro
from cicloassist.mcp.ferramentas import falas as F
from cicloassist.mcp.ferramentas import portao as P
from cicloassist.plano import falas as PF
from cicloassist.servico import pendencias as _pend
from cicloassist.servico import arrastados as _arrastados
from cicloassist.servico import vocabulario

FPS = 23.976
FORA = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.00000000.00000000.00000000.000000ff"

#: O que cada take DIZ, por intervalo de frames. T1 e T2 dizem a cena igual; T2 improvisa
#: o fim.
DITO = {
    "T1": [(0, 50, "Boa tarde, doutora."), (60, 120, "Sinceramente? Não."),
           (130, 200, "Eu não vim aqui para falar disso.")],
    "T2": [(10, 55, "Boa tarde, doutora."), (70, 125, "Não… sinceramente, não sei."),
           (140, 210, "Eu não vim aqui para falar disso.")],
}


def segmentos(take, inicio, duracao):
    if take not in DITO:
        return None
    fim = inicio + duracao
    return [(a, b, t) for a, b, t in DITO[take] if a < fim and b > inicio]


def fala(n, texto, trechos, variante=1):
    return {"fala": n, "variante": variante, "texto": texto, "confianca": "inferido",
            "fonte": "transcricao",
            "trechos": [{"take": t, "inicio_no_take_frames": a, "duracao_frames": d}
                        for t, a, d in trechos]}


BOA = [
    fala(1, "Boa tarde, doutora.", [("T1", 0, 50), ("T2", 10, 45)]),
    fala(2, "Sinceramente? Não.", [("T1", 60, 60)]),
    fala(2, "Não… sinceramente, não sei.", [("T2", 70, 55)], variante=2),
    fala(3, "Eu não vim aqui para falar disso.", [("T1", 130, 70), ("T2", 140, 70)]),
]


def conferir(pedido):
    return PF.conferir(PF.validar(pedido), segmentos, lambda take: 400)


def segmentos_do_take(take):
    """O que `transcrever` mostra, na moeda que `trechos_por_segmento` lê."""
    return [(a, b) for a, b, _ in DITO[take]] if take in DITO else None


def fala_seg(n, texto, trechos, variante=1):
    """Um momento como o MODELO o pede: take e número de segmento, sem frame nenhum."""
    return {"fala": n, "variante": variante, "texto": texto, "confianca": "inferido",
            "fonte": "transcricao",
            "trechos": [{"take": t, "do_segmento": de, **({"ate_o_segmento": ate} if ate else {})}
                        for t, de, ate in trechos]}


#: A mesma cena de `BOA`, pedida como o modelo pede.
BOA_SEG = [
    fala_seg(1, "Boa tarde, doutora.", [("T1", 1, None), ("T2", 1, None)]),
    fala_seg(2, "Sinceramente? Não.", [("T1", 2, None)]),
    fala_seg(2, "Não… sinceramente, não sei.", [("T2", 2, None)], variante=2),
    fala_seg(3, "Eu não vim aqui para falar disso.", [("T1", 3, None), ("T2", 3, None)]),
]


# ── o segmento no lugar do frame ─────────────────────────────────────────────

def test_o_segmento_vira_os_frames_da_transcricao():
    traduzido = PF.trechos_por_segmento(BOA_SEG, segmentos_do_take)
    assert traduzido[0]["trechos"] == [
        {"take": "T1", "inicio_no_take_frames": 0, "duracao_frames": 50},
        {"take": "T2", "inicio_no_take_frames": 10, "duracao_frames": 45}]
    assert conferir(traduzido).fecha


def test_ate_o_segmento_vai_da_entrada_do_primeiro_a_saida_do_ultimo():
    t = PF.trechos_por_segmento([fala_seg(1, "a", [("T1", 2, 3)])], segmentos_do_take)
    assert t[0]["trechos"] == [{"take": "T1", "inicio_no_take_frames": 60,
                                "duracao_frames": 140}]


def test_trecho_em_frames_e_recusado_e_diz_o_que_mandar():
    """⛔ MEDIDO em 2026-09-15: 32 de 237 trechos copiados à mão apontavam outra fala. Aceitar
    frames "também" deixaria vivo o jeito que errava."""
    with pytest.raises(PF.FalasInvalidas, match="do_segmento"):
        PF.trechos_por_segmento(BOA, segmentos_do_take)


def test_as_recusas_vem_todas_de_uma_vez():
    """⚠️ Parar na primeira custaria uma rodada inteira — 13 mil tokens — por trecho."""
    with pytest.raises(PF.FalasInvalidas) as e:
        PF.trechos_por_segmento([fala_seg(1, "a", [("T1", 9, None), ("T2", 3, 1),
                                                  ("T9", 1, None)])], segmentos_do_take)
    msg = str(e.value)
    assert "vai do 1 ao 3" in msg and "vem depois" in msg and "Transcreva" in msg


def test_segmento_que_atravessa_o_inicio_do_take_comeca_no_zero(monkeypatch):
    """⚠️ MEDIDO na C07: a claquete cantada atravessa o in-point e sai com início negativo."""
    monkeypatch.setitem(DITO, "T4", [(-48, 13, "Cena 7, plano 2, tomada 2.")])
    t = PF.trechos_por_segmento([fala_seg(1, "a", [("T4", 1, None)])], segmentos_do_take)
    assert t[0]["trechos"][0] == {"take": "T4", "inicio_no_take_frames": 0,
                                  "duracao_frames": 13}


# ── nomes ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("bruto", ["7", "C7", "07", "c07", "C 07"])
def test_a_cena_ganha_dois_digitos(bruto):
    assert PF.cena_normalizada(bruto) == "C07"


def test_o_nome_da_timeline_diz_momento_variante_e_texto():
    falas = PF.validar(BOA)
    assert PF.nome_da_timeline("7", falas[0]) == "C07_FALA01 - Boa tarde, doutora."
    assert PF.nome_da_timeline("7", falas[2]).startswith("C07_FALA02.02 - Não…")
    longa = PF.validar([fala(4, "palavra " * 20, [("T1", 0, 50)])])[0]
    assert PF.nome_da_timeline("7", longa).endswith("…")


# ── a forma ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("pedido, frase", [
    ([fala(1, "a", [("T1", 0, 50)]), fala(1, "b", [("T2", 0, 50)])], "duas vezes"),
    ([fala(1, "a", [("T1", 0, 50)], variante=2)], "variante 1"),
    ([fala(1, "a", [])], "sem trechos"),
    ([fala(1, "a", [("T1", 0, 1)])], "segundo no lugar de frame"),
    ([{**fala(1, "a", [("T1", 0, 50)]), "fonte": "rosto"}], "fonte"),
    ([fala(1, "", [("T1", 0, 50)])], "sem texto"),
])
def test_forma_errada_recusa_o_pedido_inteiro(pedido, frase):
    with pytest.raises(PF.FalasInvalidas, match=frase):
        PF.validar(pedido)


# ── as conferências ──────────────────────────────────────────────────────────

def test_a_cena_bem_separada_fecha():
    conf = conferir(BOA)
    assert conf.fecha, conf.problemas


def test_timestamp_de_um_take_aplicado_em_outro_reprova():
    """⛔⛔ O defeito de 2026-09-12: a fala certa, o tempo do take errado."""
    conf = conferir([fala(1, "Boa tarde, doutora.", [("T1", 0, 50)]),
                     fala(3, "Eu não vim aqui para falar disso.", [("T2", 70, 55)])])
    assert any("nesse trecho o take diz" in p for p in conf.problemas)


def test_o_take_inteiro_para_uma_fala_curta_reprova():
    """⛔⛔ O gradiente degenerado: o take todo CONTÉM a fala, e passaria na âncora."""
    conf = conferir([fala(1, "Boa tarde, doutora.", [("T1", 0, 200)])])
    assert any("engole" in p for p in conf.problemas)


def test_vizinho_curto_na_borda_do_respiro_nao_reprova(monkeypatch):
    """⚠️ MEDIDO na C07: o ASR partiu "…flexibilizar demais." e o segmento de 9 frames cai
    inteiro no respiro da fala anterior. Os dois pedidos honestos reprovavam."""
    monkeypatch.setitem(DITO, "T3", [(0, 100, "Mas eu não posso flexibilizar"),
                                     (102, 111, "demais.")])
    conf = conferir([fala(1, "Mas eu não posso flexibilizar", [("T3", 0, 112)]),
                     fala(2, "demais.", [("T3", 100, 20)])])
    assert conf.fecha, conf.problemas


def test_momento_fora_de_ordem_dentro_do_take_reprova():
    conf = conferir([fala(1, "Eu não vim aqui para falar disso.", [("T1", 130, 70)]),
                     fala(2, "Boa tarde, doutora.", [("T1", 0, 50)])])
    assert any("fora da ordem da cena" in p for p in conf.problemas)


def test_o_mesmo_trecho_em_dois_momentos_reprova():
    conf = conferir([fala(1, "Sinceramente? Não.", [("T1", 60, 60)]),
                     fala(2, "Sinceramente? Não.", [("T1", 62, 58)])])
    assert any("MESMO trecho" in p for p in conf.problemas)


def test_trecho_alem_do_fim_do_take_reprova():
    conf = PF.conferir(PF.validar([fala(1, "Boa tarde, doutora.", [("T1", 0, 50)])]),
                       segmentos, lambda take: 40)
    assert any("o take tem 40" in p for p in conf.problemas)


def test_take_sem_transcricao_nao_fecha_e_diz_qual():
    conf = conferir([fala(1, "Boa tarde, doutora.", [("T9", 0, 50)])])
    assert not conf.fecha and conf.nao_conferidos == ["T9"]
    assert "Transcreva" in PF.relatar(conf)


# ── a ferramenta ─────────────────────────────────────────────────────────────

class _MC:
    def __init__(self, raiz):
        self.raiz, self.chamadas = raiz, []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return None

    def projeto(self):
        return {"caminho": str(self.raiz), "fps_aprox": FPS}

    def _chamar(self, metodo, _timeout=None, **campos):
        self.chamadas.append((metodo, campos.get("bin_path")))


@pytest.fixture
def cena(tmp_path, monkeypatch):
    """Uma bin com dois "takes" subclipe, ocultos, apontando para fora."""
    base = tmp_path / "CENA.avb"
    with avb.open() as f:
        for nome in ("T1", "T2"):
            c = T.montar_timeline(f, nome, [T.Entrada(mob_id=FORA, duracao=400,
                                                      trilhas=(("picture", 1), ("sound", 1)))],
                                  FPS)
            c.usage_code = 2
        f.write(str(base))
    with avb.open(str(base)) as f:
        ids = {m.name: str(m.mob_id) for m in f.content.mobs}

    def resolver(_bin, nome):
        if nome not in ids:
            from cicloassist.avid.take import TakeErro
            raise TakeErro(f"não achei {nome!r}")
        return SimpleNamespace(mob_id=ids[nome], duracao_frames=400,
                               imagem=SimpleNamespace(tracks=1), som=SimpleNamespace(tracks=1))

    mc = _MC(tmp_path)
    # ⚠️ A lista de arrastados é do processo: um roteiro de outro teste viraria o roteiro
    #    desta cena e reprovaria por falas que ela não tem.
    _arrastados.esquecer_tudo()
    F._recusados.clear()
    F._ultimos.clear()
    monkeypatch.setattr(F, "resolver", resolver)
    monkeypatch.setattr(F, "segmentos_no_take", lambda _caminho: segmentos)
    monkeypatch.setattr(F, "_segmentos_do_take", lambda _caminho: segmentos_do_take)
    monkeypatch.setattr(F, "MediaComposer", mc)
    monkeypatch.setattr("cicloassist.mcp.ferramentas.corte.MediaComposer", mc)
    return base, mc


def test_separar_grava_uma_timeline_por_fala_numa_bin_nova(cena, tmp_path):
    base, mc = cena
    antes = base.read_bytes()
    r = F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG)
    assert r["ok"], r
    assert r["bin"] == "C07 FALAS.avb" and r["timelines"] == 4 and r["variantes"] == 1
    with avb.open(str(tmp_path / "C07 FALAS.avb")) as f:
        visiveis = sorted(i.mob.name for i in f.content.items if i.user_placed)
        ocultos = sorted(i.mob.name for i in f.content.items if not i.user_placed)
        um = next(i.mob for i in f.content.items if i.mob.name.startswith("C07_FALA01"))
        v1 = next(t.component for t in um.tracks
                  if getattr(t.component, "media_kind", "") == "picture")
        clipes = [(c.start_time, c.length) for c in v1.components
                  if type(c).__name__ == "SourceClip"]
    assert visiveis[0] == "C07_FALA01 - Boa tarde, doutora." and len(visiveis) == 4
    # ⛔ O fecho vai junto, oculto: subclipe fora da bin derruba o MC ao carregar.
    assert ocultos == ["T1", "T2"]
    # ⭐ Os trechos dos dois takes, na ordem, com o in de cada um.
    assert clipes == [(0, 50), (10, 45)]
    assert base.read_bytes() == antes
    assert ("OpenBin", "C07 FALAS.avb") in mc.chamadas


def test_separar_de_novo_nao_cai_por_cima(cena, tmp_path):
    base, _ = cena
    F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG)
    r = F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG)
    assert r["bin"] == "C07 FALAS 2.avb"


def test_separar_reprovado_nao_escreve_nada(cena, tmp_path):
    base, _ = cena
    r = F.separar_falas(bin=str(base), cena="7",
                        falas=[fala_seg(1, "Boa tarde, doutora.", [("T1", 1, 3)])])
    assert "não passaram na conferência" in r["erro"]
    assert not (tmp_path / "C07 FALAS.avb").exists()


# ── o portão confere antes do cartão ─────────────────────────────────────────

@pytest.fixture
def portao_limpo(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_DADOS", str(tmp_path / "CicloAssist"))
    monkeypatch.setattr(_pend, "arquivo", lambda: tmp_path / "pendencias.json")
    _pend.esquecer_tudo()
    yield
    _pend.esquecer_tudo()


def test_pedido_reprovado_volta_ao_modelo_sem_virar_cartao(cena, portao_limpo):
    """⭐ O editor não aprova o que a própria ferramenta recusaria."""
    base, _ = cena
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__separar_falas", input={
        "bin": str(base), "cena": "7",
        "falas": [fala_seg(1, "Boa tarde, doutora.", [("T1", 1, 3)])]})
    assert r["behavior"] == "deny"
    assert "NÃO foi mostrado ao editor" in r["message"]
    assert "engole" in r["message"]
    assert _pend.abertas() == []


def test_pedido_que_passa_vira_cartao_como_sempre(cena, portao_limpo):
    base, _ = cena
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__separar_falas",
                            input={"bin": str(base), "cena": "7", "falas": BOA_SEG})
    assert r["message"] == P.AGUARDANDO
    assert len(_pend.abertas()) == 1


def test_conferencia_que_quebra_nao_barra_o_pedido(portao_limpo, monkeypatch):
    """⚠️ Defeito nosso não pode parecer ao modelo um pedido errado."""
    def explode(**_):
        raise RuntimeError("bug")

    monkeypatch.setitem(registro.FERRAMENTAS, "montar_corte", registro.Ferramenta(
        "montar_corte", "", {}, lambda **_: {}, True, conferir=explode))
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte", input={})
    assert r["message"] == P.AGUARDANDO


def test_montar_corte_e_editar_timeline_tambem_conferem_antes_do_cartao(portao_limpo):
    """⭐ Revisão de 2026-09-13: o gancho só valia para `separar_falas`, e os outros dois
    deixavam o editor aprovar um pedido que a própria ferramenta recusaria."""
    assert registro.FERRAMENTAS["montar_corte"].conferir is not None
    assert registro.FERRAMENTAS["editar_timeline"].conferir is not None
    r = P.pedir_confirmacao(tool_name="mcp__ciclo__montar_corte",
                            input={"bin": "X.avb", "nome": "C07", "cortes": []})
    assert "NÃO foi mostrado" in r["message"] and _pend.abertas() == []


def test_o_editor_le_a_separacao_em_portugues():
    assert vocabulario.resumir("mcp__ciclo__separar_falas", {"cena": "7", "falas": BOA}) \
        == "Separa as falas da cena 7 — 3 falas"


# ── o que ficou de fora (2026-09-15) ─────────────────────────────────────────
#
# ⛔⛔ MEDIDO: o Haiku mandou 33 momentos, levou 32 apontamentos, e "consertou" tirando
# falas — 33 → 20 → 10 — até passar. O editor recebeu 10 das 16 falas do roteiro.

def _roteiro(*falas):
    from cicloassist.plano import mapa
    return [mapa.Fala(n, "PERSONAGEM-F", texto) for n, texto in enumerate(falas, 1)]


ROTEIRO = _roteiro("Boa tarde, doutora.", "Sinceramente? Não.",
                   "Eu não vim aqui para falar disso.", "Então por que você voltou ontem?")


def test_fala_do_roteiro_que_sumiu_reprova_e_diz_qual():
    problemas = PF.conferir_cobertura(PF.validar(BOA), [], roteiro=ROTEIRO)
    assert len(problemas) == 1 and problemas[0].startswith("roteiro 4")


def test_fala_do_roteiro_dita_em_deixadas_de_fora_passa():
    de_fora = PF.validar_de_fora([{"roteiro": 4, "porque": "nenhum take diz"}])
    assert PF.conferir_cobertura(PF.validar(BOA), de_fora, roteiro=ROTEIRO) == []


def test_fala_do_roteiro_quebrada_em_varios_momentos_conta_como_coberta():
    """⭐ O modelo quebra a fala do roteiro em frases: 16 falas viraram 33 momentos."""
    roteiro = _roteiro("Boa tarde, doutora. Sinceramente? Não.")
    assert PF.conferir_cobertura(PF.validar(BOA), [], roteiro=roteiro) == []


def test_o_que_ja_esta_na_bin_cobre_pelo_comeco_do_nome():
    """⚠️ Da bin só se lê o nome da timeline, cortado em 40 caracteres."""
    so_a_primeira = [fala(1, "Boa tarde, doutora.", [("T1", 0, 50)])]
    roteiro = _roteiro("Boa tarde, doutora.",
                       "Eu não vim aqui para falar disso, e você sabe muito bem por que razão")
    na_bin = ["Eu não vim aqui para falar disso, e você"]
    assert PF.conferir_cobertura(PF.validar(so_a_primeira), [], roteiro=roteiro,
                                 textos_ja_na_bin=na_bin) == []


def test_take_da_cena_sem_trecho_reprova_a_menos_que_dito():
    falas = PF.validar(BOA)
    assert any(p.startswith("T3:") for p in
               PF.conferir_cobertura(falas, [], takes_da_cena=["T1", "T2", "T3"]))
    de_fora = PF.validar_de_fora([{"take": "t3", "porque": "abortado no set"}])
    assert PF.conferir_cobertura(falas, de_fora, takes_da_cena=["T1", "T2", "T3"]) == []


def test_encolher_depois_de_uma_recusa_reprova():
    """⛔⛔ O gradiente: tirar trecho é mais barato que consertar."""
    menor = PF.validar([fala(1, "Boa tarde, doutora.", [("T1", 0, 50)])])
    problemas = PF.conferir_cobertura(menor, [], anterior={"T1": 3, "T2": 3})
    assert any("T1: tinha 3 trechos" in p for p in problemas)
    assert any("T2: tinha 3 trechos no pedido recusado e agora tem 0" in p for p in problemas)


def test_deixadas_de_fora_sem_porque_e_recusado():
    with pytest.raises(PF.FalasInvalidas, match="porque"):
        PF.validar_de_fora([{"take": "T3"}])
    with pytest.raises(PF.FalasInvalidas, match="diga a fala do roteiro"):
        PF.validar_de_fora([{"porque": "x"}])


def test_a_ferramenta_lembra_do_pedido_recusado_mais_cheio(cena):
    """O segundo pedido tira o T2 da fala 1 para "consertar" o segmento errado do T1."""
    base, _ = cena
    errado = [fala_seg(1, "Boa tarde, doutora.", [("T1", 2, None), ("T2", 1, None)])]
    assert "nesse trecho o take diz" in F._conferir_pedido(bin=str(base), cena="7", falas=errado)
    encolhido = [fala_seg(1, "Sinceramente? Não.", [("T1", 2, None)])]
    msg = F._conferir_pedido(bin=str(base), cena="7", falas=encolhido)
    assert "T2: tinha 1 trechos no pedido recusado e agora tem 0" in msg
    dito = F._conferir_pedido(bin=str(base), cena="7", falas=encolhido,
                              deixadas_de_fora=[{"take": "T2", "porque": "o editor pediu só o T1"}])
    assert dito == ""


def test_corrigir_o_anterior_manda_so_o_momento_consertado(cena, tmp_path):
    """⭐⭐ Ensaio da C07 (2026-10-22): cada reprovação fazia o Sonnet reescrever as 16 falas
    (~13 mil caracteres e minutos de pensamento) para mudar dois trechos."""
    base, _ = cena
    errado = [fala_seg(1, "Boa tarde, doutora.", [("T1", 2, None), ("T2", 1, None)])] + BOA_SEG[1:]
    msg = F._conferir_pedido(bin=str(base), cena="7", falas=errado)
    assert "nesse trecho o take diz" in msg and "corrigir_o_anterior" in msg

    consertado = [BOA_SEG[0]]
    assert F._conferir_pedido(bin=str(base), cena="7", falas=consertado,
                              corrigir_o_anterior=True) == ""
    # O portão e a execução preparam o MESMO pedido: reencaixar não muda nada.
    r = F.separar_falas(bin=str(base), cena="7", falas=consertado, corrigir_o_anterior=True)
    assert r["ok"] and r["timelines"] == 4, r


def test_corrigir_sem_pedido_anterior_pede_o_inteiro(cena):
    base, _ = cena
    msg = F._conferir_pedido(bin=str(base), cena="7", falas=[BOA_SEG[0]],
                             corrigir_o_anterior=True)
    assert "Mande o pedido inteiro" in msg


def test_o_unico_roteiro_arrastado_vale_sem_ser_passado(cena, tmp_path):
    base, _ = cena
    roteiro = tmp_path / "roteiro.txt"
    roteiro.write_text("PERSONAGEM-F\n\nBoa tarde, doutora.\n\nPERSONAGEM-G\n\nSinceramente? Não.\n\n"
                       "PERSONAGEM-F\n\nEu não vim aqui para falar disso.\n\n"
                       "PERSONAGEM-G\n\nEntão por que você voltou ontem?\n", encoding="utf-8")
    _arrastados.autorizar(roteiro)
    msg = F._conferir_pedido(bin=str(base), cena="7", falas=BOA_SEG)
    assert msg.startswith("- roteiro 4 (PERSONAGEM-G)")
    r = F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG,
                        deixadas_de_fora=[{"roteiro": 4, "porque": "nenhum take diz"}])
    assert r["ok"] and r["roteiro_conferido"] == "roteiro.txt (4 falas)"
    assert r["deixadas_de_fora"] == [{"roteiro": 4, "take": "", "porque": "nenhum take diz"}]


def test_os_takes_da_cena_saem_da_claquete_dos_clipes_visiveis(tmp_path):
    caminho = tmp_path / "DIARIA.avb"
    with avb.open() as f:
        for nome in ("C07_P01-T001", "C07_P02-T001.1", "C08_P01-T001", "SEM CLAQUETE"):
            c = T.montar_timeline(f, nome, [T.Entrada(mob_id=FORA, duracao=100,
                                                      trilhas=(("picture", 1),))], FPS)
            c.usage_code = 2
        f.write(str(caminho))
    assert F._takes_da_cena(str(caminho), "7") == ["C07_P01-T001", "C07_P02-T001.1"]


# ── completar a bin de falas que já existe ───────────────────────────────────

def test_acrescentar_em_completa_a_bin_de_falas(cena, tmp_path):
    """⭐ Pedido do editor (2026-09-15): "adicione na mesma bin, não crie bin nova"."""
    base, mc = cena
    primeira = F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG[:3])
    assert primeira["bin"] == "C07 FALAS.avb"
    r = F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG[3:],
                        acrescentar_em="C07 FALAS")
    assert r["ok"] and r["acrescentada_a_bin_existente"] and r["bin"] == "C07 FALAS.avb"
    assert not (tmp_path / "C07 FALAS 2.avb").exists()
    with avb.open(str(tmp_path / "C07 FALAS.avb")) as f:
        visiveis = sorted(i.mob.name for i in f.content.items if i.user_placed)
        ocultos = sorted(i.mob.name for i in f.content.items if not i.user_placed)
    assert [v[:13] for v in visiveis] == ["C07_FALA01 - ", "C07_FALA02 - ", "C07_FALA02.02",
                                          "C07_FALA03 - "]
    # ⛔ O fecho não duplica: os takes já estavam ocultos na bin.
    assert ocultos == ["T1", "T2"]
    # ⛔⛔ Fechar ANTES de gravar, abrir depois.
    nomes = [m for m, _ in mc.chamadas]
    assert nomes.index("CloseBin") < len(nomes) - 1 and nomes[-1] == "OpenBin"


def test_acrescentar_um_momento_que_a_bin_ja_tem_e_recusado(cena):
    base, _ = cena
    F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG)
    r = F.separar_falas(bin=str(base), cena="7", falas=BOA_SEG[:1], acrescentar_em="C07 FALAS")
    assert "FALA01 já existe" in r["erro"] and "vai até a FALA03" in r["erro"]


def test_os_takes_arrastados_sao_o_escopo_da_cobertura(cena, tmp_path, monkeypatch):
    """⭐ Quem arrasta só o T1 está dizendo "este": o T2 da bin não reprova (2026-10-22, o
    caso do Qwen com 1 fala e 1 clipe)."""
    base, _ = cena
    monkeypatch.setattr(F, "_takes_da_cena", lambda _c, _cena: ["T1", "T2"])
    so_t1 = [fala_seg(1, "Boa tarde, doutora.", [("T1", 1, None)])]
    assert "T2" in F._conferir_pedido(bin=str(base), cena="7", falas=so_t1)
    F._recusados.clear()
    _arrastados.lembrar_clipes(["T1"])
    assert F._conferir_pedido(bin=str(base), cena="7", falas=so_t1) == ""


def test_fala_partida_em_dois_segmentos_a_reprova_diz_o_gesto(monkeypatch):
    """⭐ Ensaio do Qwen (2026-10-22): o ASR partiu a fala em dois segmentos, o modelo
    apontou só o primeiro, ouviu "confira o segmento" e desistiu com 0 trechos."""
    partida = {"T9": [(0, 30, "Antes de surpreender os dois,"),
                      (40, 120, "você nunca imaginou que pudesse estar acontecendo alguma coisa"),
                      (130, 160, "Sinceramente?")]}

    def segs(take, inicio, duracao):
        fim = inicio + duracao
        return [(a, b, t) for a, b, t in partida[take] if a < fim and b > inicio]

    pedido = [fala(1, "Antes de surpreender os dois, você nunca imaginou que pudesse estar "
                      "acontecendo alguma coisa", [("T9", 0, 32)])]
    conf = PF.conferir(PF.validar(pedido), segs, lambda take: 400)
    assert not conf.fecha
    msg = PF.relatar(conf)
    assert "continua em o segmento seguinte" in msg or "segmento seguinte" in msg
    assert "ate_o_segmento" in msg and "você nunca imaginou" in msg
