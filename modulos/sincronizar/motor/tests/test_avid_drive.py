"""
A coluna `Drive` de uma bin → a pasta de mídia no disco.

⭐ **O QUE ESTE ARQUIVO PROTEGE:** a coluna `Drive` do Media Composer contém o
*RÓTULO* do volume (`MEU-VOLUME`), não a letra da unidade. O código antigo
montava `f"{drive}:\\"` e produzia `MEU-VOLUME:\\Avid MediaFiles` — um caminho
que não existe. O sintoma no Windows foi **"89 clip(s) from the selection were
not found on disk"** com a mídia inteira ali, em `D:\\Avid MediaFiles\\MXF\\…`.

Por que passou despercebido no macOS: lá o sistema **monta por nome**, então
`/Volumes/MEU-VOLUME` é um caminho de verdade e a mesma string funciona. É um
bug que só existe do lado do Windows, e que só aparece quando o ORIGINAL sumiu
do disco e o Órbita cai no plano B (procurar a mídia gerenciada por UMID).

Medido em 2026-08-15: `MEU-VOLUME` → `D:\\`, 394 `.mxf` em
`D:\\Avid MediaFiles\\MXF\\010020260629`.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid.masters import raiz_do_drive

# O que a coluna `Drive` realmente traz, e o mapa rótulo→letra do Windows.
UNIDADES = {"meu-volume": Path("D:\\"), "storage": Path("S:\\")}


class TestOFormatoREALDaColunaDrive:
    """⭐ O formato que o Media Composer realmente devolve no Windows, LIDO da bin
    (não inferido da tela, onde a coluna aparece truncada — foi assim que se
    errou da primeira vez):

        Drive = 'MEU-VOLUME (D:)'

    Rótulo E letra, a letra entre parênteses. Um `f"{drive}:\\"` ingênuo produzia
    `MEU-VOLUME (D:):\\Avid MediaFiles`, que só devolve `is_dir() == False` — e a
    busca seguia em frente reportando "89 clipes não encontrados" com a mídia
    inteira presente."""

    def test_o_formato_real_da_bin(self):
        assert raiz_do_drive("MEU-VOLUME (D:)", "Windows", UNIDADES) == Path("D:\\")

    def test_a_letra_entre_parenteses_MANDA_mesmo_sem_a_tabela_de_volumes(self):
        """⚠️ A letra vem de graça na string: não se deve depender de varrer os
        volumes montados quando a resposta já está ali. Sem `unidades`, e com um
        rótulo que NÃO existe na máquina, ainda tem de resolver."""
        assert raiz_do_drive("VOLUME-DESCONHECIDO (E:)", "Windows", {}) == Path("E:\\")

    def test_letra_minuscula_no_parenteses(self):
        assert raiz_do_drive("MEU-VOLUME (d:)", "Windows", {}) == Path("D:\\")

    def test_rotulo_com_espacos_e_parenteses_no_nome(self):
        """Um volume chamado `ARQUIVO (2024)` não pode ter o `(2024)` confundido
        com letra de unidade — só casa `(X:)` com dois-pontos."""
        assert raiz_do_drive("ARQUIVO (2024) (F:)", "Windows", {}) == Path("F:\\")
        assert raiz_do_drive("ARQUIVO (2024)", "Windows", {}) is None


class TestOWindowsTraduzRotuloParaLetra:
    def test_o_rotulo_sozinho_ainda_e_traduzido(self):
        """Plano B: se alguma versão do MC devolver só o nome, a busca pelos
        volumes montados resolve."""
        assert raiz_do_drive("MEU-VOLUME", "Windows", UNIDADES) == Path("D:\\")

    def test_o_rotulo_nao_diferencia_maiuscula(self):
        """O rótulo é digitado por gente; o Windows não diferencia caixa."""
        assert raiz_do_drive("meu-volume", "Windows", UNIDADES) == Path("D:\\")
        assert raiz_do_drive("Meu-Volume", "Windows", UNIDADES) == Path("D:\\")

    def test_espaco_em_volta_nao_atrapalha(self):
        assert raiz_do_drive("  MEU-VOLUME  ", "Windows", UNIDADES) == Path("D:\\")

    def test_uma_letra_crua_continua_valendo(self):
        """Um volume SEM rótulo pode aparecer como letra. Aceitar as duas formas
        não custa nada e evita um caso de borda sem cobertura."""
        for forma in ("D", "d", "D:", "D:\\", "D:/"):
            assert raiz_do_drive(forma, "Windows", UNIDADES) == Path("D:\\"), forma

    def test_volume_desconhecido_devolve_None_em_vez_de_caminho_falso(self):
        """⚠️ O erro original não era só o caminho errado — era SEGUIR com ele.
        Devolver `None` deixa o chamador pular esse master; devolver um caminho
        inventado faz o `is_dir()` falhar longe da causa, e a mensagem que chega
        na tela é 'não achei a mídia', que manda procurar no lugar errado."""
        assert raiz_do_drive("VOLUME-QUE-NAO-EXISTE", "Windows", UNIDADES) is None

    def test_drive_vazio_nao_vira_raiz(self):
        """Um master sem a coluna preenchida não pode virar `C:\\` nem `/`."""
        assert raiz_do_drive("", "Windows", UNIDADES) is None
        assert raiz_do_drive("   ", "Windows", UNIDADES) is None


class TestOMacContinuaMontandoPorNome:
    def test_no_mac_o_rotulo_e_o_proprio_caminho(self):
        """Não é duplicação do teste do Windows: é o CONTRASTE que explica por
        que o bug existia só de um lado. No macOS o rótulo já é um caminho."""
        assert raiz_do_drive("MEU-VOLUME", "Darwin") == Path("/Volumes/MEU-VOLUME")

    def test_o_sufixo_de_letra_e_removido_tambem_no_mac(self):
        """No macOS não há letra de unidade, então a coluna não deveria trazer o
        sufixo. Limpar assim mesmo é defensivo e barato: se uma versão do MC
        resolver mandá-lo, `/Volumes/MEU-VOLUME (D:)` não existiria e a mídia
        sumiria do mesmo jeito — o bug do Windows, de novo, do outro lado."""
        assert raiz_do_drive("MEU-VOLUME (D:)", "Darwin") == Path("/Volumes/MEU-VOLUME")

    def test_no_mac_nao_se_consulta_a_tabela_de_unidades(self):
        """Um volume que o mapa do Windows não conhece funciona no Mac assim
        mesmo — lá não há tradução a fazer."""
        assert raiz_do_drive("QUALQUER", "Darwin", UNIDADES) == Path("/Volumes/QUALQUER")

    def test_drive_vazio_tambem_e_None_no_mac(self):
        """Senão `/Volumes/` sozinho listaria TODOS os volumes montados."""
        assert raiz_do_drive("", "Darwin") is None
