"""
O SELETOR DE BINS — a viagem de ida e volta da chave de uma bin.

Quando nada está marcado no Avid, o Órbita devolve a ÁRVORE de bins para a pessoa
escolher; ela marca, e a interface devolve as chaves escolhidas. **São duas
pontas montando a mesma string**, e por isso este arquivo existe.

⭐ O bug que ele tranca (Windows, 2026-08-15): só a ida normalizava o separador.
`caminho_relativo_da_bin` devolve `DIARIA 01\\CAM A` no Windows; a ida virava
`DIARIA 01/CAM A`, a volta chegava com `/` e era procurada num dicionário cujas
chaves tinham `\\`. Nenhuma bin casava, a seleção saía vazia, e a interface
reabria o seletor — parecia que o botão "Use selected" não funcionava, num loop.

⚠️ **Bins na RAIZ do projeto escapavam** (não têm separador), o que tornava o bug
intermitente conforme a organização do projeto — e mais difícil de acreditar.

No macOS nada disso aparece: lá o separador já é `/` e o `replace` é inócuo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid.mcapi import MediaComposer


def McFalso(raiz: str, sep: str) -> MediaComposer:
    """Um MediaComposer que só sabe relativizar — `sep` imita o SO, para que o
    teste valha nos dois independentemente de onde ele roda."""
    mc = MediaComposer()
    mc.caminho_relativo_da_bin = lambda absoluto: absoluto[len(raiz):].lstrip(sep)
    return mc


class TestAChaveDeBin:
    def test_windows_subpasta_vira_barra(self):
        """A chave que VAI para a tela e a que VOLTA dela têm de ser a mesma."""
        mc = McFalso(r"C:\Proj", "\\")
        assert mc.chave_de_bin(r"C:\Proj\DIARIA 01\CAM A.avb") == "DIARIA 01/CAM A"

    def test_mac_subpasta_ja_vem_com_barra(self):
        mc = McFalso("/Proj", "/")
        assert mc.chave_de_bin("/Proj/DIARIA 01/CAM A.avb") == "DIARIA 01/CAM A"

    def test_os_dois_sos_produzem_A_MESMA_chave(self):
        """⭐ O invariante que faltava. A chave é identidade de bin dentro do
        projeto — não pode depender de onde o app está rodando."""
        win = McFalso(r"C:\Proj", "\\").chave_de_bin(r"C:\Proj\DIARIA 01\CAM A.avb")
        mac = McFalso("/Proj", "/").chave_de_bin("/Proj/DIARIA 01/CAM A.avb")
        assert win == mac == "DIARIA 01/CAM A"

    def test_bin_na_raiz_do_projeto(self):
        """O caso que ESCAPAVA do bug (sem separador) e o mascarava."""
        assert McFalso(r"C:\Proj", "\\").chave_de_bin(r"C:\Proj\CAM A.avb") == "CAM A"

    def test_a_extensao_avb_sai_em_qualquer_caixa(self):
        mc = McFalso(r"C:\Proj", "\\")
        assert mc.chave_de_bin(r"C:\Proj\CAM A.AVB") == "CAM A"

    def test_ida_e_volta_casa_no_dicionario(self):
        """A reprodução do bug em si: montar o dicionário como o sidecar monta e
        procurar a chave como a interface a devolve."""
        mc = McFalso(r"C:\Proj", "\\")
        bins = [r"C:\Proj\DIARIA 01\CAM A.avb", r"C:\Proj\DIARIA 01\SOM DIRETO.avb"]
        por_chave = {mc.chave_de_bin(b): b for b in bins}
        # exatamente o que a tela devolve
        assert por_chave.get("DIARIA 01/CAM A") == r"C:\Proj\DIARIA 01\CAM A.avb"
        assert por_chave.get("DIARIA 01/SOM DIRETO") == r"C:\Proj\DIARIA 01\SOM DIRETO.avb"


class TestALixeira:
    """Bin excluída não é bin: não aparece no seletor e não é lida.

    ⚠️ **Não é caso de borda.** Medido em `PROJETO EXEMPLO` (MC 25.6/Windows,
    2026-08-18): **21 das 48 bins do projeto estavam dentro de `Trash/`** — 44%.
    E o que mais dói não é o volume, é a AMBIGUIDADE: `PROJETO EXEMPLO Bin.avb` e
    `D01.avb` existiam ao mesmo tempo vivos e na lixeira, então o seletor
    mostrava o mesmo nome duas vezes sem nada dizer qual era qual.
    """

    def test_bin_na_lixeira_e_reconhecida(self):
        mc = McFalso(r"C:\Proj", "\\")
        assert mc.esta_na_lixeira(r"C:\Proj\Trash\ORIGINAIS.avb")

    def test_a_lixeira_tem_subpastas(self):
        """⚠️ Comparar só o pai direto não bastaria: a lixeira guarda a hierarquia
        que a bin tinha quando foi excluída (medido: `Trash/02_POR DIARIA/D01.avb`,
        `Trash/SYNC/D01 sync.avb`)."""
        mc = McFalso(r"C:\Proj", "\\")
        assert mc.esta_na_lixeira(r"C:\Proj\Trash\02_POR DIARIA\D01.avb")
        assert mc.esta_na_lixeira(r"C:\Proj\Trash\TESTE DE VISUALIZACAO\TESTE DE BIN.avb")

    def test_bin_viva_nao_e_lixeira(self):
        mc = McFalso(r"C:\Proj", "\\")
        assert not mc.esta_na_lixeira(r"C:\Proj\CAPTACAO\D01\D01 AUDIO.avb")
        assert not mc.esta_na_lixeira(r"C:\Proj\PROJETO EXEMPLO Bin.avb")

    def test_o_nome_da_pasta_e_INGLES_mesmo_no_MC_em_portugues(self):
        """A interface mostra "Lixeira"; o disco guarda `Trash`. Procurar a
        traduzida seria procurar uma pasta que não existe."""
        mc = McFalso(r"C:\Proj", "\\")
        assert mc.esta_na_lixeira(r"C:\Proj\Trash\x.avb")
        assert not mc.esta_na_lixeira(r"C:\Proj\Lixeira\x.avb")

    def test_a_caixa_do_nome_nao_importa(self):
        mc = McFalso(r"C:\Proj", "\\")
        assert mc.esta_na_lixeira(r"C:\Proj\TRASH\x.avb")
        assert mc.esta_na_lixeira(r"C:\Proj\trash\x.avb")

    def test_trash_ANINHADA_continua_valendo(self):
        """⭐ Só o PRIMEIRO segmento conta. Uma bin viva numa pasta que por acaso
        se chama `Trash` é trabalho de alguém — esconder seria pior que o problema
        que este filtro resolve."""
        mc = McFalso(r"C:\Proj", "\\")
        assert not mc.esta_na_lixeira(r"C:\Proj\EDICAO\Trash\x.avb")

    def test_o_mesmo_nome_vivo_e_na_lixeira_se_separa(self):
        """⭐ O caso medido que motivou tudo: a chave carrega o caminho, então as
        duas são distinguíveis — mas só uma sobrevive ao filtro."""
        mc = McFalso(r"C:\Proj", "\\")
        viva = r"C:\Proj\PROJETO EXEMPLO Bin.avb"
        morta = r"C:\Proj\Trash\PROJETO EXEMPLO Bin.avb"
        assert mc.chave_de_bin(viva) == "PROJETO EXEMPLO Bin"
        assert mc.chave_de_bin(morta) == "Trash/PROJETO EXEMPLO Bin"
        assert not mc.esta_na_lixeira(viva) and mc.esta_na_lixeira(morta)

    def test_o_filtro_de_bins_deixa_a_lixeira_de_fora(self):
        """O `bins()` inteiro, com o fluxo do gRPC dublado — é este o contrato que
        o seletor e a leitura por bins consomem."""
        mc = McFalso(r"C:\Proj", "\\")
        todas = [r"C:\Proj\CAPTACAO\D01 AUDIO.avb",
                 r"C:\Proj\Trash\ORIGINAIS.avb",
                 r"C:\Proj\Trash\02_POR DIARIA\D01.avb",
                 r"C:\Proj\PROJETO EXEMPLO Bin.avb"]

        class _Corpo:
            def __init__(self, p): self.absolute_path = p

        class _Resp:
            def __init__(self, p): self.body = _Corpo(p)

        mc._enum = lambda *a, **k: 0
        mc._fluxo = lambda *a, **k: [_Resp(p) for p in todas]

        assert mc.bins() == [r"C:\Proj\CAPTACAO\D01 AUDIO.avb",
                             r"C:\Proj\PROJETO EXEMPLO Bin.avb"]
        # E dá para pedir tudo, para quem precisar (nada no app precisa hoje).
        assert mc.bins(incluir_lixeira=True) == todas
