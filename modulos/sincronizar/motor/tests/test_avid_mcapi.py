"""
O cliente gRPC do Media Composer.

Sem MC aberto não há como exercitar a conversa — mas as partes que MAIS erram não
precisam dele: a conversão de MobID, a resolução de enums pelo descriptor, o
caminho relativo da bin e a tradução de erro. É o que este arquivo cobre.

Os valores de MobID são REAIS, medidos nos dois lados do mesmo clipe do projeto de
teste (a API de um lado, o pyavb do outro).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from avid.mcapi import (
    BinItem,
    McApiError,
    McApiNaoImplementado,
    MediaComposer,
    mob_id_para_pyavb,
)
from avid.writer import caminho_de_bin_livre

# `20260101_C0076-040.new.01`, medido nos dois lados.
API = "060a2b340101010501010f1013-000000-1a8edcf31260a306-7860d011e5e7-034e"
PYAVB = "060a2b340101010501010f1013000000f3dc8e1a601206a37860d011e5e7034e"


class TestOMobID:
    def test_converte_a_forma_da_api_para_a_do_pyavb(self):
        """⭐ As duas representações do MESMO MobID. Os 16 bytes finais são um GUID
        de endianness MISTA. Passar o hex da API direto para o writer geraria uma
        timeline apontando para mobs inexistentes, e o MC estoura em
        `PlayPipe::DoComp()` com 'missing mob'."""
        assert mob_id_para_pyavb(API) == PYAVB

    def test_os_separadores_nao_importam(self):
        assert mob_id_para_pyavb(API.replace("-", "")) == PYAVB
        assert mob_id_para_pyavb(API.replace("-", ".")) == PYAVB
        assert mob_id_para_pyavb(API.upper()) == PYAVB

    def test_aceita_a_forma_do_ffprobe_com_prefixo_0x(self):
        """⭐ A SEGUNDA fonte de MobID, e a mais interessante: o próprio arquivo
        OP-Atom carrega o `material_package_umid` do master. Com ele dá para
        autorar a timeline sem perguntar nada ao Media Composer.

        ⚠️ O `0x` tinha de ser tirado antes do filtro de hexadecimais: o `0`
        sobrevive ao filtro (o `x` não), o valor sai com 65 dígitos e TODOS os
        bytes deslocam. Valores reais, medidos dos dois lados do mesmo clipe."""
        ff = "0x060A2B340101010501010F10130000001A1644631260A3063853D011E5E7034E"
        esperado = "060a2b340101010501010f10130000006344161a601206a33853d011e5e7034e"
        assert mob_id_para_pyavb(ff) == esperado

    def test_a_conversao_nao_e_simetrica(self):
        """Guarda contra 'converter duas vezes': aplicar de novo NÃO devolve o
        original, e um valor já convertido não deve passar por aqui."""
        assert mob_id_para_pyavb(PYAVB) != PYAVB

    def test_tamanho_errado_e_erro_explicito(self):
        with pytest.raises(McApiError, match="tamanho inesperado"):
            mob_id_para_pyavb("060a2b34")


class TestOsEnums:
    """Os enums do MCAPI são quase todos ANINHADOS no RequestBody a que pertencem.
    Resolver pelo descriptor do campo cobre aninhados e globais sem escrever nome
    de enum nenhum no nosso código."""

    def test_resolve_enum_aninhado(self):
        mc = MediaComposer()
        assert mc._enum("GetListOfBinItems", "bin_flags", "masterClips") == 1
        assert mc._enum("GetListOfBinItems", "bin_flags", "AllTypes") == 0

    def test_resolve_enum_de_outro_metodo(self):
        mc = MediaComposer()
        assert isinstance(mc._enum("GetBins", "request_flag", "BinType"), int)
        assert isinstance(mc._enum("LoadMobsIntoViewer", "view_type", "Record"), int)

    def test_valor_invalido_lista_os_validos(self):
        mc = MediaComposer()
        with pytest.raises(McApiError, match="masterClips"):
            mc._enum("GetListOfBinItems", "bin_flags", "naoExiste")

    def test_campo_que_nao_e_enum_e_erro(self):
        mc = MediaComposer()
        with pytest.raises(McApiError, match="não é um campo de enum"):
            mc._enum("GetListOfBinItems", "bin_relative_path", "x")


class TestOCaminhoDaBin:
    """⚠️ `bin_relative_path` é relativo À PASTA DO PROJETO, subpasta incluída.
    Nem o nome puro nem o absoluto funcionam para uma bin em subpasta — e o erro
    que o MC devolve nos três casos é o MESMO ('Bin is not open'), que manda
    procurar o problema no lugar errado."""

    def _mc(self, raiz):
        mc = MediaComposer()
        mc.projeto = lambda: {"path": raiz}
        return mc

    def test_bin_em_subpasta_vira_caminho_relativo_com_a_subpasta(self):
        # `os.path.relpath` devolve o separador NATIVO do SO (barra no macOS,
        # contrabarra no Windows) — e o MC aceita os dois (ver o docstring de
        # `caminho_relativo_da_bin`). Cravar "/" aqui derrubava o teste no Windows
        # por uma diferença sem efeito nenhum no comportamento real.
        import os
        mc = self._mc("/p/PROJ/")
        assert mc.caminho_relativo_da_bin("/p/PROJ/MIDIAS/CAM A.avb") == os.path.join("MIDIAS", "CAM A.avb")

    def test_bin_na_raiz_vira_so_o_nome(self):
        mc = self._mc("/p/PROJ")
        assert mc.caminho_relativo_da_bin("/p/PROJ/X.avb") == "X.avb"

    def test_bin_fora_do_projeto_fica_absoluta(self):
        """Se não dá para relativizar, devolver o absoluto é melhor que devolver
        um `../../..` que o MC não entenderia."""
        mc = self._mc("/p/PROJ")
        assert mc.caminho_relativo_da_bin("/outro/Y.avb") == "/outro/Y.avb"


class TestOsErros:
    def test_indisponivel_e_diferente_de_falhou(self):
        """A distinção que a interface precisa: 'o MC não está aberto' é rotina e
        vira aviso; 'a chamada falhou' é defeito."""
        import grpc

        from avid.mcapi import McApiIndisponivel

        class FalsoErro(grpc.RpcError):
            def __init__(self, c):
                self._c = c

            def code(self):
                return self._c

            def details(self):
                return "detalhe"

        assert isinstance(
            MediaComposer._traduzir(FalsoErro(grpc.StatusCode.UNAVAILABLE), "X"),
            McApiIndisponivel)
        outro = MediaComposer._traduzir(FalsoErro(grpc.StatusCode.INTERNAL), "X")
        assert isinstance(outro, McApiError) and not isinstance(outro, McApiIndisponivel)

    def test_prazo_esgotado_NAO_diz_que_o_MC_esta_fechado(self):
        """⭐ Eu tinha juntado os dois. Na primeira vez que este erro apareceu, o
        Media Composer estava ABERTO: a chamada é que era de fluxo e foi feita como
        unária. Dizer 'ele está aberto?' manda depurar o lugar errado."""
        import grpc

        from avid.mcapi import McApiIndisponivel

        class FalsoErro(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.DEADLINE_EXCEEDED

            def details(self):
                return ""

        e = MediaComposer._traduzir(FalsoErro(), "GetMobInfo")
        assert not isinstance(e, McApiIndisponivel)
        assert "fluxo" in str(e)


class TestOCustoDaLeituraDeSelecao:
    """⚠️ Cada chamada ao Media Composer custa ~500 ms de PISO — medido em sete
    métodos diferentes, e independente do que se pede (`GetAppInfo`, que devolve
    quatro strings, custa o mesmo que listar uma bin). É por isso que o Órbita lê
    a seleção SOB DEMANDA em vez de ficar observando: cada bin aberta é uma
    chamada, e o editor costuma ter várias abertas."""

    def test_o_caminho_do_projeto_e_perguntado_UMA_vez(self):
        """Sem cache, `caminho_relativo_da_bin` perguntava a cada bin — 6,5 s
        jogados fora numa leitura de 13 bins, só para reconfirmar uma pasta que
        não muda durante a sessão."""
        mc = MediaComposer()
        chamadas = []

        def falso(metodo, **campos):
            chamadas.append(metodo)

            class R:
                class body:
                    path, project_type, raster_width, raster_height = "/p", "Film", 1920, 1080
            return R()

        mc._chamar = falso
        for _ in range(5):
            mc.projeto()
        assert chamadas == ["GetOpenProjectInfo"]
        assert mc.projeto()["path"] == "/p"

    def test_recarregar_pergunta_de_novo(self):
        mc = MediaComposer()
        mc._projeto = {"path": "/velho"}
        chamou = []

        def falso(metodo, **campos):
            chamou.append(metodo)

            class R:
                class body:
                    path, project_type, raster_width, raster_height = "/novo", "F", 1, 1
            return R()

        mc._chamar = falso
        assert mc.projeto()["path"] == "/velho"
        assert mc.projeto(recarregar=True)["path"] == "/novo"
        assert chamou == ["GetOpenProjectInfo"]

    def test_o_prefixo_de_bin_nao_salva_sai_do_nome(self):
        """O MC marca com `* ` a bin com alterações não salvas — o asterisco não é
        parte do nome e não pode entrar na comparação com o arquivo."""
        mc = MediaComposer()
        janelas = [("Bins", "* CAM A", True), ("Bins", "AUDIO", True),
                   ("Tool", "Composer", True), ("Bins", "fechada", False)]

        class W:
            def __init__(self, t, n, v):
                self.type, self.name, self.visibility = t, n, v

        class R:
            class body:
                windows = [W(*j) for j in janelas]

        mc._fluxo = lambda metodo, **c: [R()]
        assert mc.bins_abertas() == ["CAM A", "AUDIO"]


class TestMcMaisAntigoSemGetListOfWindows:
    """⭐ MEDIDO no Windows com MC 25.6.0 (2026-08-15): `GetListOfWindows`
    responde `UNIMPLEMENTED` — o rpc só existe em versões mais novas (o Mac roda
    25.12). O editor via apenas "Could not reach Órbita: GetListOfWindows falhou:
    UNIMPLEMENTED", e NADA funcionava: nem enviar a seleção, nem pedir a lista de
    bins.

    A regra que estes testes trancam: a falta de um rpc de CONVENIÊNCIA degrada,
    nunca derruba.

    ⚠️ O `active` de `GetListOfWindows` nunca foi bom para saber o que o editor
    marcou — ele acompanha o foco do SISTEMA, e apaga no instante em que a pessoa
    clica no Órbita. Hoje o rpc só serve para ORDENAR a busca de masters."""

    def test_sem_o_rpc_a_busca_de_masters_PERDE_A_ORDEM_e_nao_a_busca(self):
        """⚠️ O erro sutil que este teste existe para impedir: tratar o rpc ausente
        como "nenhuma bin aberta" e usar isso para FILTRAR. O filtro zeraria a lista
        e o material voltaria como "não encontrado" — o editor teria o clipe na bin
        e o Órbita diria que não existe.

        `bins_abertas` só ORDENA (bin aberta primeiro, para não abrir bin fechada na
        tela do editor). Sem o rpc, perde-se a ordem preferencial, nunca a busca.

        ⚠️ Este teste mudou de casa em 2026-08-23: ele guardava a mesma regra dentro
        de `MediaComposer.selecao()`, que SAIU (ver o comentário no lugar dela em
        `mcapi.py`). A regra continua valendo — só que agora o seu único dono é a
        busca de masters por nome."""
        import avid.masters as masters

        class McFalso:
            def bins(self):
                return ["/p/PROJ/CAM A.avb", "/p/PROJ/CAM B.avb"]

            def bins_abertas(self):
                raise McApiNaoImplementado("GetListOfWindows não existe")

            def __init__(self):
                self.perguntadas = []

            def masters(self, caminhos, com_duracao=True):
                self.perguntadas.extend(caminhos)
                if "CAM B" in caminhos[0]:
                    from avid.mcapi import Master
                    return [Master(name="clipe.new.01", mob_id="abc", length_frames=10)]
                return []

        mc = McFalso()
        ids, duracoes, faltam = masters.resolver(["/midia/clipe.mov"], mc=mc)

        assert mc.perguntadas == ["/p/PROJ/CAM A.avb", "/p/PROJ/CAM B.avb"], (
            "sem saber quais estão abertas, TODAS as bins têm de ser perguntadas"
        )
        assert ids == {"clipe.mov": "abc"} and not faltam
        assert duracoes == {"abc": 10}

    def test_com_o_rpc_disponivel_a_bin_ABERTA_e_perguntada_primeiro(self):
        """O contraste: sabendo quais estão abertas, elas vêm na frente — e a busca
        PARA assim que não falta ninguém, então a bin fechada nem chega a ser
        visitada (e portanto não é aberta na tela do editor)."""
        import avid.masters as masters

        class McFalso:
            def __init__(self):
                self.perguntadas = []

            def bins(self):
                return ["/p/PROJ/FECHADA.avb", "/p/PROJ/CAM B.avb"]

            def bins_abertas(self):
                return ["CAM B"]

            def masters(self, caminhos, com_duracao=True):
                self.perguntadas.extend(caminhos)
                if "CAM B" in caminhos[0]:
                    from avid.mcapi import Master
                    return [Master(name="clipe.new.01", mob_id="abc", length_frames=10)]
                return []

        mc = McFalso()
        ids, _d, faltam = masters.resolver(["/midia/clipe.mov"], mc=mc)

        assert mc.perguntadas == ["/p/PROJ/CAM B.avb"], (
            "a bin aberta resolveu tudo; a fechada não devia ser aberta à toa"
        )
        assert ids == {"clipe.mov": "abc"} and not faltam

    def test_um_rpc_que_falta_nao_e_erro_generico(self):
        """`UNIMPLEMENTED` tem de virar `McApiNaoImplementado`, e não um
        `McApiError` cru: é o que deixa quem chama decidir entre degradar e
        falhar. Se virar erro genérico, o `except` do `selecao` não pega e o
        sintoma volta."""
        import grpc

        class ErroFalso(grpc.RpcError):
            def code(self):
                return grpc.StatusCode.UNIMPLEMENTED

            def details(self):
                return ""

        erro = MediaComposer._traduzir(ErroFalso(), "GetListOfWindows")
        assert isinstance(erro, McApiNaoImplementado)
        assert isinstance(erro, McApiError), "tem de continuar sendo um McApiError"
        # A mensagem precisa apontar para VERSÃO, senão manda depurar o lugar errado.
        assert "mais antiga" in str(erro), erro


class TestDaSelecaoParaOArquivo:
    """⭐ A seleção de uma bin traz NOMES e MobIDs — o motor precisa de ARQUIVOS.
    A ponte são as colunas `Source Path`/`Source File`: o Media Composer lembra de
    onde importou cada master."""

    def test_monta_o_caminho_e_confirma_que_ele_existe(self, tmp_path):
        arquivo = tmp_path / "20260101_CAM0001.mov"
        arquivo.write_bytes(b"")
        mc = MediaComposer()
        col = {"Source Path": str(tmp_path) + "/", "Source File": arquivo.name}
        assert mc.arquivo_do_master("x", col) == str(arquivo)

    def test_arquivo_que_nao_esta_mais_no_disco_devolve_None(self, tmp_path):
        """Cartão devolvido, projeto que mudou de máquina. Devolver o caminho
        assim mesmo faria o motor falhar lá na frente, longe da causa — e o plano
        B (casar pelo UMID contra a mídia gerenciada) nunca seria acionado."""
        mc = MediaComposer()
        col = {"Source Path": str(tmp_path) + "/", "Source File": "sumiu.mov"}
        assert mc.arquivo_do_master("x", col) is None

    def test_sem_a_coluna_de_arquivo_devolve_None(self):
        mc = MediaComposer()
        assert mc.arquivo_do_master("x", {"Source Path": "/algum/lugar/"}) is None
        assert mc.arquivo_do_master("x", {}) is None

    def test_caminho_de_OUTRA_estacao_e_traduzido_antes_de_desistir(
            self, tmp_path, monkeypatch):
        """§1.3b — o original está aqui, montado com outra letra.

        Um projeto ingerido no Mac grava `/Volumes/INGEST/…`. Aberto no Windows esse
        caminho não existe, e até 2026-08-23 a função desistia e o app caía para a
        mídia gerenciada — **perdendo o original em silêncio**, com ele no disco.

        A tradução usa o nome do volume que o próprio caminho carrega (ver
        `avid/caminhos.py`), e nunca devolve o que não existe.
        """
        raiz = tmp_path / "montado_como_letra"
        (raiz / "PROJ").mkdir(parents=True)
        original = raiz / "PROJ" / "A001_C003.mov"
        original.write_bytes(b"")

        # ⚠️ A costura é `volumes_montados`, não `unidades_por_rotulo`: aquela é a
        # que existe nos DOIS sistemas. Trocar a do Windows daria um teste que passa
        # aqui e falha no Mac — o SSD deste projeto troca de máquina.
        monkeypatch.setattr("avid.caminhos.volumes_montados",
                            lambda: {"ingest": raiz})
        mc = MediaComposer()
        col = {"Source Path": "/Volumes/INGEST/PROJ/", "Source File": original.name}
        assert mc.arquivo_do_master("x", col) == str(original)


class TestOsDoisNomesDoMesmoClipe:
    """O Órbita conhece o ARQUIVO (`X.mov`); o Avid conhece o MASTER (`X.new.01`).
    `nome_base` é o que os dois têm em comum."""

    def test_tira_o_sufixo_do_avid_e_a_extensao(self):
        from avid.masters import nome_base

        assert nome_base("20260101_CAM0001.new.01") == "20260101_cam0001"
        assert nome_base("20260101_CAM0001.mov") == "20260101_cam0001"
        assert nome_base("20260101_CAM0001.new.01") == nome_base("20260101_CAM0001.mov")

    def test_sufixos_empilhados_saem_todos(self):
        """O Avid empilha: um clipe reimportado vira `X.new.01.new.02`."""
        from avid.masters import nome_base

        assert nome_base("A.new.01.sync.02") == "a"

    def test_a_extensao_de_som_tambem_sai(self):
        from avid.masters import nome_base

        assert nome_base("REC0034_Tr12.WAV.new.01") == "rec0034_tr12"
        assert nome_base("REC0034_Tr12.WAV") == "rec0034_tr12"

    def test_nao_come_ponto_que_faz_parte_do_nome(self):
        """`.02` sozinho não é sufixo do Avid — só as palavras conhecidas são."""
        from avid.masters import nome_base

        assert nome_base("CENA.02.mov") == "cena.02"

    def test_a_lista_de_sufixos_e_FECHADA(self):
        """⭐ Este teste existe porque uma mutação sobreviveu: trocar a lista
        (`new|sync|cds|…`) por um padrão genérico `.palavra.NN` passava em tudo que
        eu tinha escrito. E não é equivalente — um clipe chamado
        `ENTREVISTA.parte.02.mov` seria mutilado até `entrevista`, e o casamento com
        o master do Avid falharia sem que nada acusasse. Palavra que o Avid não
        escreve não é sufixo do Avid."""
        from avid.masters import nome_base

        # O par real: o master na bin (o editor renomeou) e o arquivo em disco.
        # Com a lista fechada os dois convergem; com um padrão genérico o master
        # viraria só "entrevista" e o casamento falharia.
        assert nome_base("ENTREVISTA.parte.02") == "entrevista.parte.02"
        assert nome_base("ENTREVISTA.parte.02.mov") == "entrevista.parte.02"
        # E o sufixo de VERDADE continua saindo.
        assert nome_base("ENTREVISTA.parte.02.new.01") == "entrevista.parte.02"


class TestNaoSobrescreverBinAberta:
    def test_nome_livre_desvia_do_que_ja_existe(self, tmp_path):
        """⚠️ O `OpenBin` de uma bin JÁ ABERTA devolve Completed e NÃO relê o
        disco: o MC segue servindo a cópia em memória. Sobrescrever faz o editor
        ver a timeline VELHA enquanto o app jura ter entregue a nova."""
        assert caminho_de_bin_livre(tmp_path, "SYNC") == str(tmp_path / "SYNC.avb")
        (tmp_path / "SYNC.avb").write_bytes(b"")
        assert caminho_de_bin_livre(tmp_path, "SYNC") == str(tmp_path / "SYNC 2.avb")
        (tmp_path / "SYNC 2.avb").write_bytes(b"")
        assert caminho_de_bin_livre(tmp_path, "SYNC") == str(tmp_path / "SYNC 3.avb")


class TestEscreverONomeNaBin:
    """A aba Renomear escreve UMA coluna, e só ela: `Name`.

    ⚠️ O que estes testes protegem não é a chamada — é o que ela NÃO faz. Um
    `SetMobInfo` com o campo errado grava em silêncio na coluna errada, e o
    editor descobre pela bin, não por uma exceção.
    """

    def test_renomear_escreve_a_coluna_Name_e_mais_nenhuma(self):
        mc = MediaComposer()
        vistas = []

        def falso(metodo, **campos):
            vistas.append((metodo, campos))
            return object()

        mc._chamar = falso
        mc.renomear_item("urn:smpte:umid:060a2b34", "C04_P01_T002")

        assert len(vistas) == 1, "uma escrita por item, nunca duas"
        metodo, campos = vistas[0]
        assert metodo == "SetMobInfo"
        assert campos["mob_id"] == "urn:smpte:umid:060a2b34"
        assert campos["column"].column_name == "Name"
        assert campos["column"].column_value == "C04_P01_T002"

    def test_colunas_do_master_pede_o_MINIMO_por_padrao(self):
        """⚠️ 31 colunas contra 191 — a diferença entre um autocomplete e uma
        lista telefônica. O padrão não pode ser o caro."""
        mc = MediaComposer()
        vistos = []

        def fluxo(metodo, **campos):
            vistos.append(campos)
            return iter(())

        mc._fluxo = fluxo
        mc.colunas_do_master("x")
        assert vistos[-1] == {"mob_id": "x"}, "nada além do mob_id"

    def test_todas_as_colunas_liga_o_campo_CERTO(self):
        """⭐ Quem abre as comportas é `includes_empty_columns`. O nome de
        `only_visible_columns` sugere o contrário, e alguém ia 'consertar' o
        padrão trocando o campo — daí o teste afirmar os DOIS."""
        mc = MediaComposer()
        vistos = []

        def fluxo(metodo, **campos):
            vistos.append(campos)
            return iter(())

        mc._fluxo = fluxo
        mc.colunas_do_master("x", todas=True)
        assert vistos[-1]["includes_empty_columns"] is True
        assert vistos[-1]["only_visible_columns"] is False


class TestOSaveBinEOFimDaFrase:
    def test_salvar_devolve_False_em_vez_de_derrubar_o_trabalho(self):
        """⚠️ A bin já foi escrita e aberta quando o Save Bin é tentado. Estourar
        aqui trocaria 'salve à mão' por 'o app falhou' — e o segundo é mentira."""
        mc = MediaComposer()

        def recusa(metodo, **campos):
            raise McApiError("o comando não foi aceito")

        mc._chamar = recusa
        assert mc.salvar_bin_ativa() is False

    def test_o_DoCommand_espera_o_efeito_acontecer(self, monkeypatch):
        """⚠️⚠️ A resposta do DoCommand volta ANTES do efeito. Sem a pausa, quem
        ler a bin em seguida lê o estado velho e conclui que não salvou."""
        mc = MediaComposer()
        dormidas = []
        monkeypatch.setattr("time.sleep", lambda s: dormidas.append(s))
        mc._chamar = lambda metodo, **campos: object()

        assert mc.salvar_bin_ativa() is True
        assert dormidas, "sem pausa, a confirmação seguinte lê o estado anterior"

    def test_comando_recusado_por_CONCORRENCIA_e_retentado(self, monkeypatch):
        """O MC executa um comando de cada vez: 'Can't start more than one
        command on time.' é fila, não falha — e só esse erro é retentado."""
        mc = MediaComposer()
        monkeypatch.setattr("time.sleep", lambda s: None)
        tentativas = []

        def ocupado_uma_vez(metodo, **campos):
            tentativas.append(metodo)
            if len(tentativas) == 1:
                raise McApiError("Can't start more than one command on time.")
            return object()

        mc._chamar = ocupado_uma_vez
        assert mc.salvar_bin_ativa() is True
        assert len(tentativas) == 2

    def test_outro_erro_NAO_e_retentado(self, monkeypatch):
        mc = MediaComposer()
        monkeypatch.setattr("time.sleep", lambda s: None)
        tentativas = []

        def sempre_falha(metodo, **campos):
            tentativas.append(metodo)
            raise McApiError("Unable to modify column data.")

        mc._chamar = sempre_falha
        assert mc.salvar_bin_ativa() is False
        assert len(tentativas) == 1, "retentar erro que não é de fila é só demora"


class TestABinDeUmMob:
    def test_devolve_o_caminho_absoluto(self):
        mc = MediaComposer()

        class R:
            class body:
                absolute_path = r"C:\Proj\MIDIAS\D02_SYNC.avb"

        mc._chamar = lambda metodo, **campos: R()
        assert mc.bin_do_mob("x") == r"C:\Proj\MIDIAS\D02_SYNC.avb"

    def test_rpc_que_falta_devolve_None_em_vez_de_estourar(self):
        """⚠️ O `SetPosition`, do MESMO .proto, responde UNIMPLEMENTED nesta
        build do MC. Não presumir que os vizinhos existem."""
        mc = MediaComposer()

        def indisponivel(metodo, **campos):
            raise McApiNaoImplementado("esta build não tem GetBinFromMob")

        mc._chamar = indisponivel
        assert mc.bin_do_mob("x") is None

    def test_caminho_vazio_tambem_e_None(self):
        """Resposta boa com corpo vazio é 'não sei', não string vazia — que
        viraria um `Path("")` apontando para o diretório atual."""
        mc = MediaComposer()

        class R:
            class body:
                absolute_path = ""

        mc._chamar = lambda metodo, **campos: R()
        assert mc.bin_do_mob("x") is None


class TestOSourceFileQueVemComoCaminho:
    r"""⛔⛔ O conserto de `arquivo_do_master` estava VIVO no código e SEM TESTE.

    ⚠️⚠️ E a razão de ele ter passado despercebido é um caso de escola: os testes
    que existiam afirmavam `arquivo_do_master(...) is None`, e o código FURADO
    devolveria `None` do mesmo jeito — porque o UNC do atacante não existe nesta
    máquina. Resultado certo, razão errada, e o dano já consumado no caminho.

    O dano não é o valor devolvido: é o `.exists()` ter sido CHAMADO sobre
    `\\atacante\share\…`, porque no Windows isso abre sessão SMB — a máquina de
    quem monta batendo num host escolhido por quem autorou o `.avb`. As duas
    colunas são texto livre de um arquivo de terceiro: entrada, não configuração.

    Portanto o teste espiona o disco e afirma sobre o que foi TOCADO.
    """

    UNC_DO_ATACANTE = "\\" * 2 + "atacante\\share\\roubado.mov"

    def test_o_caminho_de_fora_nunca_e_TOCADO_no_disco(self, tmp_path, monkeypatch):
        # ⚠️ O nome desta função NÃO contém a palavra do host hostil de propósito:
        # o pytest batiza o `tmp_path` com o nome do teste, e a palavra apareceria
        # no caminho LEGÍTIMO — reprovando um código correto. Custou uma rodada.
        tocados: list[str] = []
        exists_real = Path.exists

        def exists_espiao(self, *a, **k):
            tocados.append(str(self))
            return exists_real(self, *a, **k)

        monkeypatch.setattr(Path, "exists", exists_espiao)

        mc = MediaComposer()
        mc.arquivo_do_master("mob", {"Source Path": str(tmp_path) + "/",
                                     "Source File": self.UNC_DO_ATACANTE,
                                     "Name": "CAM_A_001"})

        # A afirmação é sobre a FORMA do que foi tocado: nada de UNC, nada fora da
        # pasta que o `Source Path` autorizou.
        fora = [t for t in tocados
                if t.startswith("\\" * 2) or t.startswith("//") or "share" in t]
        assert not fora, f"o 'Source File' absoluto foi consultado no disco: {fora}"
        assert all(str(tmp_path) in t for t in tocados), (
            f"tocou fora da pasta autorizada pelo 'Source Path': {tocados}")

    def test_so_o_NOME_sobrevive_e_ele_resolve_na_pasta_legitima(self, tmp_path):
        """E quando um arquivo de mesmo nome existe na pasta legítima, é ELE que
        sai — a peneira reduz ao nome, não descarta o item."""
        legitimo = tmp_path / "roubado.mov"
        legitimo.write_bytes(b"x")
        mc = MediaComposer()
        assert mc.arquivo_do_master("mob", {
            "Source Path": str(tmp_path) + "/",
            "Source File": self.UNC_DO_ATACANTE,
            "Name": "CAM_A_001"}) == str(legitimo)

    def test_travessia_com_pontos_cai_na_mesma_peneira(self, tmp_path):
        """`..` não é o mesmo ataque, mas passa pelo mesmo filtro: só o nome fica."""
        mc = MediaComposer()
        obtido = mc.arquivo_do_master("mob", {
            "Source Path": str(tmp_path) + "/",
            "Source File": "../../../Windows/System32/calc.exe",
            "Name": "CAM_A_002"})
        assert obtido is None or ".." not in str(obtido)

    def test_o_caminho_ILEGIVEL_vira_aviso_no_log(self, caplog):
        """⭐ Descartar calado é o modo de falha caro aqui.

        Um `Source Path` que não existe NESTA máquina é indistinguível, no
        resultado, de 'não havia original': os dois devolvem `None` e caem na
        mídia gerenciada. Mas a diferença importa — aqui o Avid SABE onde o
        original está e nós é que não sabemos ler o caminho dele (projeto
        ingerido noutra estação). Sem o aviso, o app usa o transcode e perde o
        original, sem dizer nada.
        """
        import logging

        mc = MediaComposer()
        with caplog.at_level(logging.WARNING):
            assert mc.arquivo_do_master("mob", {
                "Source Path": "/Volumes/INGEST/CAM A/",
                "Source File": "A001.mov", "Name": "A001"}) is None

        # ⚠️ `getMessage()`, não `.message`: o logging guarda formato e args
        # separados, e interpolar à mão erra quando há `%` no caminho.
        assert any("INGEST" in r.getMessage() for r in caplog.records), (
            "o caminho ilegível tem de aparecer no log — é a única pista de que "
            f"havia original: {[r.getMessage() for r in caplog.records]}")
