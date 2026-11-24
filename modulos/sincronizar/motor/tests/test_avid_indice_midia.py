"""
O ÍNDICE DA MÍDIA GERENCIADA do Avid, e por que ele é guardado.

⭐⭐ O número que motiva tudo, medido em 2026-08-18 na máquina do autor:
**457 arquivos `.mxf`, um `ffprobe` cada, 58 ms por arquivo → 26,7 s de varredura.**
Listar os mesmos 457 custa **0,15 s** — 178× mais barato.

Ela roda sempre que um master não tem arquivo de origem, que é o caso de TODA mídia
transcodada pelo Avid (os clipes `.new.01`). Enquanto a entrada era uma leitura de
seleção por sessão, os 26,7 s eram pagos uma vez. **O arrasto mudou isso**: é o gesto
principal e é REPETIDO, uma câmera por vez, então cada arrasto refazia a varredura
inteira — três câmeras viravam 80 s de espera por uma resposta já conhecida.

⚠️ A invalidação é a LISTA DE ARQUIVOS, não um prazo: como conferir é 178× mais
barato que varrer, dá para conferir sempre em vez de apostar num tempo.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import avid.masters as masters


class VarreduraFalsa:
    """Conta quantas vezes a varredura CARA foi chamada."""

    def __init__(self, por_umid=None, so_audio=None):
        self.chamadas = 0
        self.por_umid = por_umid if por_umid is not None else {"mob1": ["/m/V01.mxf"]}
        self.so_audio = so_audio if so_audio is not None else set()

    def __call__(self, raizes, on_progress=None):
        self.chamadas += 1
        return dict(self.por_umid), set(self.so_audio)


def preparar(monkeypatch, arquivos, varredura):
    """Substitui a listagem (barata) e a varredura (cara) por dublês."""
    masters.esquecer_indice_da_midia()
    from media import opatom

    monkeypatch.setattr(opatom, "arquivos_mxf", lambda raizes: list(arquivos))
    monkeypatch.setattr(masters, "varredura_por_umid", varredura)


class TestOIndiceDaMidia:
    def test_a_segunda_chamada_nao_varre_de_novo(self, monkeypatch):
        """⭐ O ganho: o segundo arrasto responde sem pagar os ~27 s."""
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf", "/m/b.mxf"], v)

        primeiro = masters.indice_da_midia_do_avid(["/m"])
        segundo = masters.indice_da_midia_do_avid(["/m"])

        assert v.chamadas == 1, "varreu UMA vez para duas chamadas"
        assert primeiro[0] == segundo[0], "e devolve o mesmo índice"

    def test_arquivo_NOVO_refaz_o_indice(self, monkeypatch):
        """Transcodificar mídia no meio da sessão tem de aparecer — senão o clipe
        novo ficaria "não encontrado no disco" até reiniciar o app."""
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf"], v)
        masters.indice_da_midia_do_avid(["/m"])
        assert v.chamadas == 1

        from media import opatom
        monkeypatch.setattr(opatom, "arquivos_mxf", lambda r: ["/m/a.mxf", "/m/b.mxf"])
        masters.indice_da_midia_do_avid(["/m"])
        assert v.chamadas == 2, "a lista mudou: varre de novo"

    def test_arquivo_REMOVIDO_tambem_refaz(self, monkeypatch):
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf", "/m/b.mxf"], v)
        masters.indice_da_midia_do_avid(["/m"])

        from media import opatom
        monkeypatch.setattr(opatom, "arquivos_mxf", lambda r: ["/m/a.mxf"])
        masters.indice_da_midia_do_avid(["/m"])
        assert v.chamadas == 2

    def test_raizes_diferentes_sao_indices_diferentes(self, monkeypatch):
        """Dois volumes de mídia não podem compartilhar índice — o de um responderia
        pelo outro, e o sintoma seria clipe "sumido" no volume errado."""
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf"], v)
        masters.indice_da_midia_do_avid(["/m1"])
        masters.indice_da_midia_do_avid(["/m2"])
        assert v.chamadas == 2

    def test_a_ordem_das_raizes_nao_cria_indice_novo(self, monkeypatch):
        """Mesmas raízes em outra ordem são a MESMA pergunta."""
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf"], v)
        masters.indice_da_midia_do_avid(["/m1", "/m2"])
        masters.indice_da_midia_do_avid(["/m2", "/m1"])
        assert v.chamadas == 1

    def test_o_so_audio_sobrevive_ao_cache(self, monkeypatch):
        """⚠️ O conjunto de "só áudio" é o que impede um gravador de set de virar
        câmera. Se o cache devolvesse só o mapa de arquivos, o som direto voltaria a
        ser rotulado como CAM na segunda leitura — e só na segunda."""
        v = VarreduraFalsa(por_umid={"mobS": ["/m/A01.mxf"]}, so_audio={"mobS"})
        preparar(monkeypatch, ["/m/A01.mxf"], v)

        masters.indice_da_midia_do_avid(["/m"])
        _por_umid, so_audio = masters.indice_da_midia_do_avid(["/m"])
        assert so_audio == {"mobS"}, "o som continua sendo som na segunda chamada"

    def test_esquecer_forca_a_releitura(self, monkeypatch):
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf"], v)
        masters.indice_da_midia_do_avid(["/m"])
        masters.esquecer_indice_da_midia()
        masters.indice_da_midia_do_avid(["/m"])
        assert v.chamadas == 2

    def test_quem_recebe_o_indice_nao_consegue_corrompe_lo(self, monkeypatch):
        """O chamador mexe no que recebeu (o `resolver_mobs` faz `faltam.remove`).
        Se isso alcançasse o índice guardado, a segunda leitura viria mutilada."""
        v = VarreduraFalsa()
        preparar(monkeypatch, ["/m/a.mxf"], v)

        por_umid, so_audio = masters.indice_da_midia_do_avid(["/m"])
        por_umid["mob_inventado"] = ["/lixo.mxf"]
        so_audio.add("mob_inventado")

        de_novo, audio_de_novo = masters.indice_da_midia_do_avid(["/m"])
        assert "mob_inventado" not in de_novo, "o índice guardado não foi contaminado"
        assert "mob_inventado" not in audio_de_novo


class DirigidaFalsa:
    """Conta as buscas DIRIGIDAS e o que entrou na fila de cada uma."""

    def __init__(self, resposta=None, so_audio=None, esgotada=False,
                 completos=None):
        self.chamadas = 0
        self.filas: list[list[str]] = []
        self.alvos: list[dict] = []
        self.resposta = resposta if resposta is not None else {}
        self.so_audio = so_audio or set()
        self.esgotada = esgotada
        # ⚠️ Por padrão TUDO que a busca devolve é dado como completo — é o caso
        # comum. Os testes de clipe pela metade passam `completos` na mão.
        self.completos = completos

    def __call__(self, raizes, alvos, arquivos, on_progress=None):
        self.chamadas += 1
        self.filas.append(list(arquivos))
        self.alvos.append(dict(alvos))
        completos = (set(self.resposta) if self.completos is None
                     else set(self.completos))
        return (dict(self.resposta), set(self.so_audio), set(arquivos),
                self.esgotada, completos)


class TestOIndiceACUMULADO:
    """⭐ Com `alvos`, o índice deixa de ser COMPLETO e passa a ser ACUMULADO: cada
    arrasto lê o que falta e guarda o que aprendeu.

    ⚠️ Um índice parcial tem uma armadilha própria — responder "não existe" para um
    master que ninguém procurou ainda. Estes testes são sobre isso."""

    def preparar(self, monkeypatch, arquivos, dirigida):
        masters.esquecer_indice_da_midia()
        from media import opatom
        monkeypatch.setattr(opatom, "arquivos_mxf", lambda r: list(arquivos))
        monkeypatch.setattr(masters, "varredura_dirigida", dirigida)

    def test_master_ja_conhecido_nao_manda_buscar(self, monkeypatch):
        d = DirigidaFalsa(resposta={"mobA": ["/m/a.mxf"]})
        self.preparar(monkeypatch, ["/m/a.mxf", "/m/b.mxf"], d)

        alvos = {"mobA": {"nome": "", "arquivos": 1}}
        masters.indice_da_midia_do_avid(["/m"], alvos=alvos)
        masters.indice_da_midia_do_avid(["/m"], alvos=alvos)

        assert d.chamadas == 1, "o 2º arrasto da mesma câmera responde de memória"

    def test_master_NOVO_manda_buscar_de_novo(self, monkeypatch):
        """⛔ A armadilha do índice parcial: perguntar por um master que ninguém
        procurou ainda NÃO pode virar "não encontrado no disco"."""
        d = DirigidaFalsa(resposta={"mobA": ["/m/a.mxf"]})
        self.preparar(monkeypatch, ["/m/a.mxf", "/m/b.mxf"], d)

        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": 1}})
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobB": {"arquivos": 1}})

        assert d.chamadas == 2, "o master que falta manda buscar"

    def test_a_2a_busca_nao_repete_arquivo_ja_LIDO(self, monkeypatch):
        """O cache tem de economizar o TRABALHO, não só a resposta: o `ffprobe` de
        um arquivo já lido não pode ser pago de novo no arrasto seguinte."""
        d = DirigidaFalsa(resposta={"mobA": ["/m/a.mxf"]})
        self.preparar(monkeypatch, ["/m/a.mxf", "/m/b.mxf", "/m/c.mxf"], d)

        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": 1}})
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobB": {"arquivos": 1}})

        assert d.filas[1] == [], "a 2ª fila só teria o que a 1ª não leu"

    def test_resultado_PARCIAL_nao_sobrescreve_o_mais_completo(self, monkeypatch):
        """⛔⛔ A parada devolve, para um clipe que não era o alvo, só os arquivos
        que deu tempo de ler. Trocar a entrada boa por essa tiraria um canal de
        áudio em silêncio."""
        masters.esquecer_indice_da_midia()
        from media import opatom
        monkeypatch.setattr(opatom, "arquivos_mxf",
                            lambda r: ["/m/v.mxf", "/m/a1.mxf", "/m/a2.mxf", "/m/z.mxf"])

        completo = DirigidaFalsa(resposta={"mobA": ["/m/v.mxf", "/m/a1.mxf", "/m/a2.mxf"]})
        monkeypatch.setattr(masters, "varredura_dirigida", completo)
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": 3}})

        parcial = DirigidaFalsa(resposta={"mobA": ["/m/v.mxf"], "mobZ": ["/m/z.mxf"]},
                                completos={"mobZ"})
        monkeypatch.setattr(masters, "varredura_dirigida", parcial)
        por_umid, _ = masters.indice_da_midia_do_avid(["/m"], alvos={"mobZ": {"arquivos": 1}})

        assert por_umid["mobA"] == ["/m/v.mxf", "/m/a1.mxf", "/m/a2.mxf"], \
            "o clipe completo sobreviveu ao resultado parcial"

    def test_arquivo_novo_no_disco_zera_ate_o_que_ja_foi_lido(self, monkeypatch):
        """Transcodificar no meio da sessão invalida o índice inteiro — inclusive a
        lista de arquivos já lidos, senão o material novo ficaria fora da fila."""
        d = DirigidaFalsa(resposta={"mobA": ["/m/a.mxf"]})
        self.preparar(monkeypatch, ["/m/a.mxf"], d)
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": 1}})

        from media import opatom
        monkeypatch.setattr(opatom, "arquivos_mxf", lambda r: ["/m/a.mxf", "/m/novo.mxf"])
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": 1}})

        assert d.chamadas == 2 and d.filas[1] == ["/m/a.mxf", "/m/novo.mxf"]

    def test_fila_esgotada_marca_o_indice_como_completo(self, monkeypatch):
        """Quando a busca leu tudo (nenhum master tinha `Tracks`, por exemplo), o
        índice É completo — e a próxima pergunta não precisa varrer nada."""
        d = DirigidaFalsa(resposta={"mobA": ["/m/a.mxf"]}, esgotada=True)
        self.preparar(monkeypatch, ["/m/a.mxf", "/m/b.mxf"], d)

        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": None}})
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobB": {"arquivos": None}})

        assert d.chamadas == 1, "leu tudo uma vez; não há o que buscar de novo"

    def test_clipe_lido_PELA_METADE_nao_dispensa_a_proxima_busca(self, monkeypatch):
        """⛔⛔ O DEFEITO QUE A RÉGUA PEGOU (2026-08-23, `PRJ/D01`).

        A busca da bin da CAM A lê, de passagem, parte de um clipe da CAM B — e
        para ali, porque os alvos DELA fecharam. Esse clipe fica no índice
        incompleto. No arrasto da CAM B, "o MobID já está no índice" dispensava a
        busca, e o clipe entrava na timeline **com um arquivo a menos**.

        Sintoma medido: 13/13 acertos viraram **12/13 com um erro CALADO**, e a
        contagem de arquivos caiu de 63 para 62. Nada levantou erro."""
        pela_metade = DirigidaFalsa(
            resposta={"mobA": ["/m/a.mxf"], "mobB": ["/m/b1.mxf"]},
            completos={"mobA"})          # o mobB veio pela metade
        self.preparar(monkeypatch, ["/m/a.mxf", "/m/b1.mxf", "/m/b2.mxf"], pela_metade)
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobA": {"arquivos": 1}})

        inteiro = DirigidaFalsa(resposta={"mobB": ["/m/b1.mxf", "/m/b2.mxf"]})
        monkeypatch.setattr(masters, "varredura_dirigida", inteiro)
        por_umid, _ = masters.indice_da_midia_do_avid(["/m"], alvos={"mobB": {"arquivos": 2}})

        assert inteiro.chamadas == 1, "o clipe pela metade TEM de mandar buscar de novo"
        assert por_umid["mobB"] == ["/m/b1.mxf", "/m/b2.mxf"], \
            "e o resultado completo substitui o parcial"

    def test_a_rebusca_de_um_parcial_reve_os_arquivos_ja_lidos(self, monkeypatch):
        """O resto de um clipe lido pela metade está justamente entre os arquivos
        que a busca anterior JÁ passou. Filtrá-los deixaria o clipe mutilado para
        sempre — a economia de não reler mata a correção."""
        pela_metade = DirigidaFalsa(resposta={"mobB": ["/m/b1.mxf"]}, completos=set())
        self.preparar(monkeypatch, ["/m/b1.mxf", "/m/b2.mxf"], pela_metade)
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobB": {"arquivos": 2}})

        de_novo = DirigidaFalsa(resposta={"mobB": ["/m/b1.mxf", "/m/b2.mxf"]})
        monkeypatch.setattr(masters, "varredura_dirigida", de_novo)
        masters.indice_da_midia_do_avid(["/m"], alvos={"mobB": {"arquivos": 2}})

        assert de_novo.filas[0] == ["/m/b1.mxf", "/m/b2.mxf"], \
            "a fila volta inteira quando há parcial em jogo"


class TestRegravadoComOMesmoNome:
    def test_mxf_REGRAVADO_com_o_mesmo_nome_refaz_o_indice(self, monkeypatch, tmp_path):
        """⛔⛔ Ciclo Assist, 2026-11-01: repetir o mesmo fluxo regravou os MXF com OS
        MESMOS NOMES nas MESMAS pastas. Com a assinatura só de caminhos, o índice velho
        valia, os UMIDs novos ficavam "sem arquivo" e o sync dizia "0 fonte(s) com mídia"
        com a mídia online no Media Composer."""
        import os

        arq = tmp_path / "V01.mxf"
        arq.write_bytes(b"x" * 10)
        v = VarreduraFalsa()
        preparar(monkeypatch, [str(arq)], v)
        masters.indice_da_midia_do_avid([str(tmp_path)])
        assert v.chamadas == 1

        arq.write_bytes(b"y" * 20)  # o render de novo: mesmo nome, outro conteúdo
        st = os.stat(arq)
        os.utime(arq, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000_000))
        masters.indice_da_midia_do_avid([str(tmp_path)])
        assert v.chamadas == 2, "o arquivo mudou: o índice não pode valer"
