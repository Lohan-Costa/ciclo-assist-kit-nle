"""A decupagem MICRO: os cortes (F1) e a nota por trecho (F2) — 2026-09-22.

⭐ Pedido do editor: a micro COMPLEMENTA a macro (nunca a substitui) e atende o montado E o
bruto. O que estes testes travam:

- o detector acha corte seco e dissolve num vídeo gerado com posições CONHECIDAS, e nada
  num plano contínuo (a medição de verdade é `spikes/onde_estao_os_cortes.py`);
- trechos curtos são juntados (a peça da Copa dava 77 trechos em 60 s);
- só o trecho da CABEÇA lê claquete (medido: um trecho do meio "leu" o exemplo);
- a nota de trecho grava posição e não apaga a macro; a claquete lida sobe para a macro;
- a busca prefere a nota com posição.

⚠️ O Mac é simulado aqui.
"""

from __future__ import annotations

import json
import subprocess
import time
from fractions import Fraction
from pathlib import Path

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import cortes as K
from cicloassist.motor import micro as M
from cicloassist.motor import percepcao as P

T25 = Fraction(25)


def _video(caminho: Path, filtro: str, segundos: float) -> Path:
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", filtro,
                    "-t", str(segundos), "-pix_fmt", "yuv420p", str(caminho)], check=True)
    return caminho


@pytest.fixture
def emendado(tmp_path):
    """Três planos de conteúdo diferente: corte seco em 50, dissolve de 12 em ~100."""
    a = _video(tmp_path / "a.mp4", "testsrc2=size=320x180:rate=25", 2)
    b = _video(tmp_path / "b.mp4", "mandelbrot=size=320x180:rate=25", 2)
    c = _video(tmp_path / "c.mp4", "smptebars=size=320x180:rate=25", 2)
    saida = tmp_path / "emendado.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(a), "-i", str(b), "-i", str(c),
                    "-filter_complex",
                    "[0:v][1:v]concat=n=2:v=1:a=0,fps=25[ab];"
                    "[2:v]fps=25[c];[ab][c]xfade=transition=fade:duration=0.48:offset=3.52[x]",
                    "-map", "[x]", "-pix_fmt", "yuv420p", str(saida)], check=True)
    return saida


def test_acha_o_corte_e_o_dissolve(emendado):
    fronteiras, s = K.detectar(emendado, T25)
    cortes = [f["quadro"] for f in fronteiras if f["tipo"] == "corte"]
    graduais = [f for f in fronteiras if f["tipo"] in ("dissolve", "fade")]
    assert any(abs(c - 50) <= 1 for c in cortes), fronteiras
    assert any(88 <= g["quadro"] <= 100 for g in graduais), fronteiras
    assert s["n"] == 138   # 6 s − 0,48 s de sobreposição, a 25 fps


def test_ffmpeg_que_trava_e_morto_e_nao_vira_meia_deteccao(tmp_path, monkeypatch):
    """⛔⛔ Todo outro ffmpeg da casa roda com prazo; este lê em FLUXO e não tinha nenhum.

    O preço de um travamento aqui não é esta mídia: a fila é **uma tarefa por vez**, e o
    editor ficaria sem poder analisar nada, com a barra em "correndo", até reiniciar o
    serviço.

    ⛔ E o teste guarda a ORDEM da conferência: morto no meio, já há quadros lidos e a
    série está PELA METADE. Aceitá-la daria fronteiras plausíveis para meia mídia,
    gravadas no cache como se fossem a mídia inteira — e ninguém as refaria.
    """
    v = _video(tmp_path / "c.mp4", "testsrc2=size=320x180:rate=25", 6)
    monkeypatch.setattr(K, "PRAZO_SEM_QUADRO_S", 0.05)
    lento = K._ler_exato
    estado = {"n": 0}

    def travando(fluxo, n):
        estado["n"] += 1
        if estado["n"] > 3:
            time.sleep(1.0)          # o cão de guarda mata o ffmpeg aqui
        return lento(fluxo, n)

    monkeypatch.setattr(K, "_ler_exato", travando)

    with pytest.raises(K.DeteccaoFalhou) as erro:
        K.detectar(v, T25)
    assert "travou" in str(erro.value)


def test_plano_continuo_nao_tem_fronteira(tmp_path):
    v = _video(tmp_path / "c.mp4", "testsrc2=size=320x180:rate=25", 6)
    fronteiras, _ = K.detectar(v, T25)
    assert fronteiras == []


def test_bruto_ganha_cabeca_e_montado_nao(tmp_path, emendado):
    v = _video(tmp_path / "c.mp4", "testsrc2=size=320x180:rate=25", 6)
    fr, s = K.detectar(v, T25)
    assert K.trechos(fr, s, T25)[0].cabeca is True
    fr, s = K.detectar(emendado, T25)
    assert not any(t.cabeca for t in K.trechos(fr, s, T25))


def test_trechos_curtos_sao_juntados_com_os_planos_dentro():
    """⛔ MEDIDO: 77 trechos em 60 s de peça montada — 2 h de Mac para 1 min."""
    taxa = Fraction(30)
    fr = [{"quadro": q, "tipo": "corte"} for q in range(15, 900, 15)]   # plano de 0,5 s
    s = {"n": 900, "d1": __import__("numpy").full(900, 0.001, dtype="float32")}
    lista = K.trechos(fr, s, taxa)
    assert len(lista) < 20
    assert all(len(t.planos) <= K.PLANOS_POR_TRECHO for t in lista)
    assert lista[0].planos[:2] == [0, 15]


# ── a nota por trecho ─────────────────────────────────────────────────────────

@pytest.fixture
def midia_bruta(tmp_path, monkeypatch):
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    v = _video(tmp_path / "A009_03190918_C010.mp4", "testsrc2=size=320x180:rate=25", 24)
    m = C.Midia("a" * 64, origem="premiere", rotulo={"nome": v.name, "arquivos": [str(v)]})
    m.pasta  # noqa: B018
    m.anotar({"trecho": v.name, "escopo": "midia", "descricao": "a macro de sempre",
              "confianca": "inferido", "fonte": "visual"})
    monkeypatch.setattr("cicloassist.mcp.ferramentas.midia.quadros_da_cabeca",
                        lambda chave: ([b"\xff\xd8cab"], [1.0]))
    return m, v


def _mac_que_responde(monkeypatch, respostas):
    pedidos = []

    def pedir(url, caminho, corpo, timeout=0):
        pedidos.append(corpo)
        return {"message": {"content": json.dumps(respostas[len(pedidos) - 1])}}

    monkeypatch.setattr(P, "pedir", pedir)
    return pedidos


def test_a_micro_grava_por_trecho_sem_apagar_a_macro(midia_bruta, monkeypatch):
    m, v = midia_bruta
    lendo = {"descricao": "um homem segura a claquete", "claquete": {
        "rolo": ["A09"], "cena": "16", "plano": "1", "take": "3"}}
    inventando = {"descricao": "o corredor vazio", "claquete": {
        "rolo": ["X07"], "cena": "31", "plano": "8", "take": "5"}}
    dados = K.de_uma(m, v, T25)
    n = len(dados["trechos"])
    pedidos = _mac_que_responde(monkeypatch, [lendo] + [inventando] * (n - 1))
    r = M.processar(m, str(v), T25, v.name, "http://192.168.1.4:11434")

    assert r["feitos"] == n and len(pedidos) == n
    # ⭐ O pedido força JSON, e a cabeça vai PRIMEIRO e diz que é para a claquete.
    assert pedidos[0]["format"] == "json"
    assert "para ler a claquete" in pedidos[0]["messages"][1]["content"]
    notas = m.ler_notas()
    macro = [x for x in notas if x.get("escopo") == "midia"]
    trechos = [x for x in notas if x.get("escopo") == "trecho"]
    assert len(macro) == 1 and len(trechos) == n
    assert all(t.get("inicio_frames") is not None and t.get("fim_s") for t in trechos)
    # ⛔ Só a cabeça lê claquete: a "leitura" do meio (o exemplo) é descartada.
    assert sum(1 for t in trechos if t.get("claquete")) == 1
    # ⭐ E a claquete lida sobe para a macro, conferida pelo rolo do nome do arquivo.
    assert macro[0]["claquete"]["rolo"] == ["A09"] and macro[0]["cena"] == "16"
    assert not M.falta(m)


def test_a_midia_so_com_micro_conta_no_alcance_da_busca(tmp_path, monkeypatch):
    """⚠️ A frase do alcance é *"onde eu procurei"*, e a busca lê as DUAS camadas de
    imagem. Contando só a macro, uma mídia decupada em trechos ficava fora do número — e a
    frase prometia menos material do que a busca varre."""
    from cicloassist.midia import busca as B
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    m = C.Midia("c" * 64, origem="avid", rotulo={"nome": "SÓ MICRO"})
    m.pasta  # noqa: B018
    m.anotar({"trecho": "SÓ MICRO · trecho 0", "escopo": "trecho", "inicio_frames": 0,
              "inicio_s": 0.0, "fim_s": 10.0, "descricao": "alguém abre a porta",
              "confianca": "inferido", "fonte": "visual"})

    assert B.medir_alcance().decupadas == 1
    # E ela é mesmo achável — o número não pode prometer o que a busca não entrega.
    assert [a.chave for a in B.procurar(["porta"])] == [m.chave]


def test_sem_mac_a_micro_diz_por_que():
    with pytest.raises(M.MicroIndisponivel):
        M.processar(None, "", T25, "x", "")


# ── o preço, que aqui é tempo ─────────────────────────────────────────────────

def test_os_dois_numeros_do_preco_dizem_a_mesma_coisa():
    """⭐⭐ `segundos por trecho` e `trechos por minuto` são a MESMA medição, ditas de dois
    jeitos: multiplicadas, elas têm de devolver os minutos de Mac por minuto de material
    que estão escritos no `CLAUDE.md` (~2,5 no bruto, ~16 no montado).

    ⚠️ Sem este teste, recalibrar um e esquecer o outro faz a tela mentir sobre HORAS de
    trabalho — e a mentira é plausível, que é o pior tipo neste produto.
    """
    bruto = M.SEGUNDOS_POR_TRECHO["bruto"] * M.TRECHOS_POR_MINUTO["bruto"] / 60
    montado = M.SEGUNDOS_POR_TRECHO["montado"] * M.TRECHOS_POR_MINUTO["montado"] / 60
    assert 2.0 <= bruto <= 3.0, bruto
    assert 14.0 <= montado <= 18.0, montado
    # ⛔ E a distância entre os dois é o motivo de a tela mostrar FAIXA em vez de escolher:
    #   se um dia ela encolher, a faixa deixa de fazer sentido e o texto precisa mudar junto.
    assert montado / bruto > 3


def test_a_busca_prefere_o_trecho_que_tem_posicao(tmp_path, monkeypatch):
    from cicloassist.midia import busca as B
    monkeypatch.setenv("CICLOASSIST_CACHE", str(tmp_path / "cache"))
    m = C.Midia("b" * 64, origem="avid", rotulo={"nome": "X"})
    m.pasta  # noqa: B018
    m.anotar({"trecho": "X", "escopo": "midia", "descricao": "Personagem F na porta",
              "confianca": "inferido", "fonte": "visual"})
    m.anotar({"trecho": "X · trecho 480", "escopo": "trecho", "inicio_frames": 480,
              "inicio_s": 20.0, "fim_s": 30.0, "descricao": "Personagem F abre a porta",
              "confianca": "inferido", "fonte": "visual"})
    achado, = B.procurar(["porta"], {})
    d = achado.como_dicionario()
    assert d["inicio_frames"] == 480 and d["escopo"] == "trecho" and d["inicio_s"] == 20.0
    # O título do cartão não é a chave interna do trecho.
    assert d["take"] == ""
