"""A transcrição — a parte que não precisa de áudio nem de modelo.

O ASR em si é exercitado contra material real; aqui ficam as regras de janela e de
armazenamento, que são onde o erro seria silencioso.
"""

from __future__ import annotations

from cicloassist.midia import asr as R
from cicloassist.midia import audio as A
from cicloassist.midia import cache as C

MASTER = "urn:smpte:umid:060a2b34.01010105.01010d43.13000000.6505f199.1c930000.060e2b34.7f7f2a80"


def fala(inicio, fim, texto="x"):
    return {"inicio": inicio, "fim": fim, "texto": texto, "certeza": 0.9}


# ── a janela do take ─────────────────────────────────────────────────────────

def test_pega_o_que_esta_dentro():
    falas = [fala(0, 2), fala(10, 12), fala(300, 302)]
    assert R.recortar(falas, 5, 100) == [fala(10, 12)]


def test_inclui_quem_ATRAVESSA_a_borda_de_entrada():
    """⭐ MEDIDO na C07: a claquete cantada ("Cena 7, plano 2, tomada 4") começa em 6,66s
    do master e termina em 10,94s, enquanto o take entra em 9,76s. Ela atravessa o
    in-point — e descartá-la jogaria fora justamente a confirmação de qual take é este."""
    falas = [fala(6.66, 10.94, "Cena 7, plano 2, tomada 4.")]
    assert R.recortar(falas, 9.76, 236.0) == falas


def test_inclui_quem_atravessa_a_borda_de_saida():
    """A fala que o corte interrompe é exatamente a que interessa a quem procura onde
    cortar."""
    assert R.recortar([fala(230, 240)], 9.76, 236.0)


def test_descarta_quem_so_encosta():
    """Terminar exatamente no in-point não é estar dentro."""
    assert R.recortar([fala(0, 9.76)], 9.76, 236.0) == []
    assert R.recortar([fala(236.0, 240)], 9.76, 236.0) == []


def test_janela_vazia_devolve_vazio():
    assert R.recortar([], 0, 100) == []


# ── o armazenamento ──────────────────────────────────────────────────────────

def test_transcricao_e_do_master(tmp_path):
    """⭐ Mesma regra dos quadros: qualquer recorte daquele áudio acha pronto — inclusive
    um groupclipe de multicam montado depois."""
    m = C.Midia(MASTER, tmp_path)
    assert not m.tem_transcricao()
    m.guardar_transcricao([fala(1, 2, "oi")])
    assert m.tem_transcricao()
    assert m.ler_transcricao()[0]["texto"] == "oi"


def test_transcricao_corrompida_vira_vazia_e_nao_excecao(tmp_path):
    m = C.Midia(MASTER, tmp_path)
    m.guardar_transcricao([fala(1, 2)])
    m._transcricao.write_text("{quebrado", encoding="utf-8")
    assert m.ler_transcricao() == []


def test_trocar_de_modelo_invalida_a_transcricao(tmp_path):
    """Mudou o motor ou o modelo, o texto guardado é de outra receita."""
    m = C.Midia(MASTER, tmp_path)
    m.registrar_gerador("transcricao", {"modelo": "small"})
    assert not m.precisa_refazer("transcricao", {"modelo": "small"})
    assert m.precisa_refazer("transcricao", {"modelo": "medium"})


def test_o_wav_de_trabalho_fica_no_cache(tmp_path):
    """Montá-lo custa segundos, e ele serve para refazer com outro modelo sem tocar nos
    `.mxf` de novo."""
    m = C.Midia(MASTER, tmp_path)
    assert m.audio.parent == m.pasta
    assert m.audio.suffix == ".wav"


# ── a mixagem ────────────────────────────────────────────────────────────────

def test_o_asr_recebe_16k_mono():
    """Entregar 48 kHz estéreo faria o Whisper reamostrar por dentro para chegar no mesmo
    lugar, gastando tempo e memória."""
    assert A.TAXA_DO_ASR == 16000
    assert A.ASSINATURA_MIXAGEM["canais"] == 1


def test_a_assinatura_da_mixagem_entra_no_cache():
    """Mudou o jeito de montar o áudio, a transcrição guardada deixa de valer."""
    assert "modo" in A.ASSINATURA_MIXAGEM


# ── a certeza ────────────────────────────────────────────────────────────────

def test_certeza_fica_entre_0_e_1():
    """`avg_logprob` é logaritmo e vai a menos infinito. O editor lê um número de 0 a 1;
    deixar o log vazar faria "-0,42" parecer erro."""
    for logprob in (-10.0, -2.0, -0.1, 0.0):
        certeza = max(0.0, min(1.0, 1.0 + logprob / 2.0))
        assert 0.0 <= certeza <= 1.0


# ── o que SAI para o modelo ──────────────────────────────────────────────────
#
# ⚠️⚠️ MEDIDO em 2026-09-12 (sessão da C07): com o array de palavras, 12 de 14
# transcrições ESTOURARAM o limite de saída do CLI. O modelo via as duas primeiras falas
# de cinquenta mais um caminho de arquivo, e remontava o resto por Grep — foi daí que saiu
# o timestamp de um take aplicado em outro.

from fractions import Fraction  # noqa: E402

from cicloassist.mcp.ferramentas import fala as F  # noqa: E402

#: 23,976 — a taxa do material da C07.
TAXA = Fraction(24000, 1001)


def crua(inicio, fim, texto="x", palavras=2):
    """Uma fala como `com_respiro` a devolve, já com os campos de corte."""
    return {"inicio": inicio, "fim": fim, "texto": texto, "certeza": 0.9,
            "corte_inicio": inicio - 0.17, "corte_fim": fim + 0.40,
            "vao_ate_a_proxima": 1.0,
            "palavras": [{"t": inicio + i, "fim": inicio + i + 0.3, "palavra": f"p{i}"}
                         for i in range(palavras)]}


def test_cada_fala_do_take_tem_o_numero_do_segmento_que_o_separar_falas_recebe():
    """⭐ A numeração é do take INTEIRO: é o endereço que `separar_falas` recebe, e ele
    tem de ser o mesmo em qualquer página da transcrição."""
    from fractions import Fraction
    from types import SimpleNamespace
    take = SimpleNamespace(fps={"num": 24000, "den": 1001}, duracao_frames=2400,
                           som=SimpleNamespace(inicio_s=5.0, inicio_frames=120))
    do_master = [fala(1, 2), fala(6, 7, "a"), fala(9, 10, "b"), fala(200, 201)]
    lista = F.falas_do_take(take, do_master)
    assert [f["segmento"] for f in lista] == [1, 2]
    assert [f["texto"] for f in lista] == ["a", "b"]
    assert list(lista[0])[0] == "segmento"
    pagina, proxima = F.paginar(lista, 1)
    assert pagina[0]["segmento"] == 2 and proxima == 0


def test_por_padrao_NAO_vem_o_tempo_de_cada_palavra():
    f = F.formatar_fala(crua(10.0, 12.0), inicio_s=0.0, taxa=TAXA)
    assert "palavras" not in f


def test_sob_pedido_o_tempo_de_cada_palavra_volta():
    f = F.formatar_fala(crua(10.0, 12.0), inicio_s=0.0, taxa=TAXA, por_palavra=True)
    assert len(f["palavras"]) == 2
    # ⚠️ Só em frames: dar as duas moedas por palavra deixou a saída de emergência 57%
    #    MAIOR que o formato que ela veio consertar.
    assert f["palavras"][0] == {"palavra": "p0", "inicio": round(10.0 * TAXA),
                                "fim": round(10.3 * TAXA)}


def test_o_tempo_CRU_do_reconhecedor_nao_sai():
    """⛔ `inicio_no_take`/`fim_no_take` só existiam para NÃO serem usados — e viravam
    ponto de corte assim mesmo. Campo que existe para não ser usado um dia é usado."""
    f = F.formatar_fala(crua(10.0, 12.0), inicio_s=0.0, taxa=TAXA)
    assert "inicio_no_take" not in f and "fim_no_take" not in f


def test_os_frames_batem_com_os_segundos():
    """⭐ A ponte do conserto de 2026-09-12: o modelo copia, não multiplica."""
    f = F.formatar_fala(crua(10.0, 12.0), inicio_s=2.0, taxa=TAXA)
    assert f["inicio_no_take_frames"] == round((10.0 - 0.17 - 2.0) * TAXA)
    assert f["saida_no_take_frames"] == round((12.0 + 0.40 - 2.0) * TAXA)
    assert f["duracao_frames"] == f["saida_no_take_frames"] - f["inicio_no_take_frames"]


def test_o_offset_do_take_desconta_dos_frames():
    """⚠️ O som de um take sincronizado entra depois da imagem (medido: 234 frames). Os
    frames são do TAKE, não do master — senão a sequência nasce dessincronizada."""
    zero = F.formatar_fala(crua(10.0, 12.0), inicio_s=0.0, taxa=TAXA)
    tarde = F.formatar_fala(crua(10.0, 12.0), inicio_s=9.76, taxa=TAXA)
    assert tarde["inicio_no_take_frames"] < zero["inicio_no_take_frames"]
    assert tarde["duracao_frames"] == zero["duracao_frames"]


def test_a_duracao_serve_direto_ao_montar_corte():
    """⭐ Os nomes são os de `montar_corte` de propósito: o modelo copia o par."""
    from cicloassist.plano import esquema as E

    f = F.formatar_fala(crua(10.0, 14.0), inicio_s=0.0, taxa=TAXA)
    plano = E.validar({"bin": "b.avb", "nome": "s", "cortes": [{
        "take": "T", "inicio_no_take": f["inicio_no_take_frames"],
        "duracao_frames": f["duracao_frames"],
        "confianca": "inferido", "fonte": "transcricao", "porque": "a fala inteira"}]})
    assert plano.cortes[0].duracao_frames == f["duracao_frames"]


def test_uma_transcricao_inteira_cabe_na_janela():
    """⛔⛔ O teto que faltava. Um take real da C07 tem ~50 falas; com palavras isso dava
    mais de 60 KB e o CLI truncava a resposta inteira."""
    import json

    falas = [F.formatar_fala(crua(i * 4.0, i * 4.0 + 2.5, "uma fala de tamanho normal", 6),
                             inicio_s=0.0, taxa=TAXA) for i in range(55)]
    tamanho = len(json.dumps(falas, ensure_ascii=False, indent=2))
    assert tamanho < 24_000, f"{tamanho:,} chars — voltou a crescer"


def test_uma_transcricao_LONGA_e_paginada_e_diz_isso():
    """⛔⛔ Enxugar campo reduz por um FATOR; lista sem limite não tem teto. Uma diária de
    entrevista com 257 falas estourava o limite do CLI mesmo no formato magro."""
    falas = [F.formatar_fala(crua(i * 4.0, i * 4.0 + 2.5, "uma fala de tamanho normal"),
                             inicio_s=0.0, taxa=TAXA) for i in range(400)]
    pagina, proxima = F.paginar(falas, 0)
    assert proxima and proxima < 400, "uma lista de 400 falas tinha de ser paginada"
    import json
    assert len(json.dumps(pagina, ensure_ascii=False, indent=2)) <= F.ORCAMENTO_CHARS


def test_a_ultima_pagina_avisa_que_acabou():
    """⭐ `continuar_em` zerado é o fim — o modelo não deve precisar de conta para saber."""
    falas = [F.formatar_fala(crua(i * 4.0, i * 4.0 + 2.5), inicio_s=0.0, taxa=TAXA)
             for i in range(3)]
    pagina, proxima = F.paginar(falas, 0)
    assert len(pagina) == 3 and proxima == 0


def test_uma_fala_gigante_sozinha_nao_trava_a_paginacao():
    """⚠️ Se a primeira fala já estourar o orçamento, devolver lista vazia faria o modelo
    pedir a mesma página para sempre."""
    enorme = F.formatar_fala(crua(0.0, 300.0, "x" * (F.ORCAMENTO_CHARS * 2)),
                             inicio_s=0.0, taxa=TAXA)
    pagina, proxima = F.paginar([enorme, enorme], 0)
    assert len(pagina) == 1 and proxima == 1


def test_a_forma_enxuta_tem_o_mesmo_segmento_e_cabe_em_bem_menos(monkeypatch):
    """⭐⭐ Ensaio da C07 (2026-10-22): 10 transcrições completas eram 155 mil caracteres no
    contexto do turno, e `separar_falas` só usa o segmento e o texto."""
    import json
    from types import SimpleNamespace
    som = SimpleNamespace(inicio_s=0.0, inicio_frames=0, arquivos=["x.wav"], master="M",
                          midia=lambda rotulo=None: object())
    take = SimpleNamespace(nome="T1", cena="C07", plano="P01", fps={"num": 24000, "den": 1001},
                           duracao_frames=24000, som=som, avisos=[], rotulo=lambda s: {})
    do_master = [crua(1.0 + 3 * i, 2.5 + 3 * i, f"fala número {i}") for i in range(30)]
    monkeypatch.setattr(F._nle, "resolver_take", lambda b, i: take)
    monkeypatch.setattr(F._analise, "transcrever_master",
                        lambda *a, **k: {"falas": do_master, "do_cache": True})

    completa = F.transcrever(bin="B", item="T1")
    enxuta = F.transcrever(bin="B", item="T1", enxuta=True)
    assert [int(f.split(" | ")[0]) for f in enxuta["falas"]] ==         [f["segmento"] for f in completa["falas"]]
    assert enxuta["falas"][2].endswith(" | fala número 2")
    assert "como_cortar" not in enxuta and "formato_das_falas" in enxuta
    assert len(json.dumps(enxuta, ensure_ascii=False)) * 3 < len(json.dumps(completa, ensure_ascii=False))
