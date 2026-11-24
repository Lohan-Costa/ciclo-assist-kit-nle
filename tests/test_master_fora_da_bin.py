"""Master fora da bin GRAVADA: a frase tem de dizer o que fazer, não sumir com o nome.

⛔⛔ MEDIDO em 2026-09-20, no material do autor. Ele pediu "separa as falas da C07" às
09:16; os dez takes voltaram `não achei a mídia de som de '' no acervo local` — nome
VAZIO, porque o master não estava na bin lida do disco. O modelo (Sonnet) não tinha como
saber o motivo: deduziu que faltavam masterclipes na bin e pediu ao editor que os
trouxesse, coisa que no Avid nem faz sentido (o master do subclipe vive oculto na própria
bin). A `C07.avb` foi gravada às **09:17:12**, um minuto DEPOIS: o arquivo em disco estava
mais velho que o que o Media Composer tinha na memória.

⭐ A queixa do autor é o que este teste tranca: *"cada modelo está interpretando a sua
forma de execução… precisamos ser mais previsíveis"*. Erro que não diz o gesto vira
adivinhação — e cada modelo adivinha diferente.
"""

from __future__ import annotations

from cicloassist.avid import take as T


class _Fonte:
    def __init__(self, master, mob_id="060a2b34…-1234", arquivos=()):
        self.master = master
        self.mob_id = mob_id
        self.arquivos = list(arquivos)


def test_sem_master_a_frase_manda_salvar_a_bin():
    frase = T.por_que_falta(_Fonte(""), "som")
    assert "salvar" in frase and "bin" in frase
    assert "Ctrl+S" in frase, "o gesto tem de estar escrito, não subentendido"
    assert "060a2b34" in frase, "o mob ajuda quem for investigar"


def test_com_master_continua_sendo_o_caso_de_midia_offline():
    """⚠️ A outra causa é diferente e o conserto também: o arquivo não está no disco."""
    frase = T.por_que_falta(_Fonte("PRODUCAO-A - 05-04 C7 P1-T001"), "som")
    assert "acervo local" in frase and "PRODUCAO-A" in frase
    assert "Ctrl+S" not in frase


def test_a_ferramenta_de_transcrever_usa_a_frase_e_leva_os_avisos(monkeypatch):
    from cicloassist.mcp.ferramentas import fala as F

    class _Take:
        som = _Fonte("")
        avisos = ["o master 060a2b34…-1234 não está nesta bin; fica sem nome e sem arquivo"]

    monkeypatch.setattr(F._nle, "resolver_take", lambda bin, item: _Take())
    r = F.transcrever(bin="CENAS/C07.avb", item="C07_P01-T001")

    assert "Ctrl+S" in r["erro"], r
    assert r["avisos"] == _Take.avisos, "o aviso do resolvedor tem de chegar ao modelo"


def test_a_ferramenta_de_ver_quadros_diz_o_mesmo(monkeypatch):
    from cicloassist.mcp.ferramentas import visual as V

    class _Take:
        imagem = _Fonte("")
        avisos = []

    monkeypatch.setattr(V._nle, "resolver_take", lambda bin, item: _Take())
    saida = V.ver_frames(bin="CENAS/C07.avb", item="C07_P01-T001", quantos=1)

    assert "Ctrl+S" in saida[0]["text"], saida
