"""
A BUSCA DIRIGIDA da mídia gerenciada: ler o que se pediu, e PARAR.

⭐⭐ O número que motiva tudo, medido em 2026-08-23 (Windows, MC 25.6, HD mecânico
`V-001 (E:)` com 1404 `.mxf`, 50 masters da diária D02 de `PROJETO EXEMPLO`):

| estratégia | tempo | `ffprobe` |
|---|---|---|
| varredura completa, em série (o que havia) | 80,98 s | 1404 |
| varredura completa, 8 trabalhadores | 58,44 s | 1404 |
| **dirigida (filtro + parada + afinidade de pasta)** | **1,13 s** | **200** |

As três resolvem os MESMOS 50 masters, com os MESMOS 198 arquivos e os mesmos 24
só-áudio. O que muda é quantos arquivos se lê para chegar lá — e `Tracks` previa
198, então 200 é praticamente o piso.

⚠️ **O que este arquivo protege são as três formas de a parada chegar CEDO DEMAIS**,
que é o modo de falha caro: um clipe que "completa" sem um canal de áudio não
levanta erro nenhum — ele só chega à timeline mudo de um lado.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import avid.masters as masters
from media import opatom
from media.opatom import OpAtomFile


def umid(n: int) -> str:
    """Um UMID de 64 hexadecimais, que é o que `mob_id_para_pyavb` exige."""
    return f"{n:064x}"


def arquivo(caminho: str, clipe: int, kind: str = "audio", track: int = 1,
            file_umid: str | None = None) -> OpAtomFile:
    return OpAtomFile(
        path=caminho, clip_umid=umid(clipe), clip_name=f"clipe{clipe}",
        file_umid=file_umid if file_umid is not None else caminho,
        kind=kind, track_index=track, channels=1,
    )


def falsear_leitura(monkeypatch, mapa: dict[str, OpAtomFile]):
    """O `ffprobe` some: cada caminho conhecido vira o `OpAtomFile` da tabela.

    Devolve a lista dos caminhos LIDOS, na ordem — é ela que prova a parada.
    """
    lidos: list[str] = []

    def probe(caminho, timeout=30):
        lidos.append(caminho)
        return {"caminho": caminho}

    def parse(doc, caminho):
        item = mapa.get(caminho)
        return item if item is not None else "não é OP-Atom"

    monkeypatch.setattr(opatom, "probe_file", probe)
    monkeypatch.setattr(opatom, "parse_probe", parse)
    # Um trabalhador só: com lote paralelo a parada tem overshoot de até 8
    # arquivos, e o que se quer provar aqui é ONDE ela acontece, não o overshoot.
    monkeypatch.setattr(opatom, "trabalhadores", lambda pedido=None: 1)
    return lidos


class TestArquivosPrevistos:
    """A coluna `Tracks` da bin diz quantos arquivos OP-Atom o master tem."""

    def test_video_mais_estereo(self):
        assert masters.arquivos_previstos("V1 A1-2") == 3

    def test_intervalo_conta_o_intervalo_inteiro(self):
        assert masters.arquivos_previstos("A1-5") == 5

    def test_so_video(self):
        assert masters.arquivos_previstos("V1") == 1

    def test_tracks_de_sequencia_nao_sao_essencia(self):
        """⚠️ `TC1`/`EC1` aparecem em SEQUÊNCIAS e não viram arquivo de mídia.
        Contá-las faria a busca parar antes de achar o material."""
        assert masters.arquivos_previstos("V1 A1-2 TC1") == 3

    def test_sem_tracks_nao_ha_parada(self):
        """`None` é a resposta honesta de "não sei" — e sem saber, lê-se tudo.
        Um palpite aqui deixaria clipe sem canal, calado."""
        assert masters.arquivos_previstos(None) is None
        assert masters.arquivos_previstos("") is None
        assert masters.arquivos_previstos("???") is None


class TestFilaDeBusca:
    """A ordem da fila. ⚠️ Ela ORDENA — nunca EXCLUI."""

    def test_nenhum_arquivo_e_descartado(self):
        """⛔ O caso que obriga a isto: a convenção `V01.E69CCF0F_….mxf` não
        carrega nome NENHUM. Um filtro que excluísse o que não casa com o `Name`
        da bin perderia o acervo inteiro — e perderia calado."""
        arquivos = ["/m/A/V01.E69CCF0F_1A8ED.mxf", "/m/A/A01.E69CCF10_1A8ED.mxf"]
        alvos = {umid(1): {"nome": "20260101_C0076-040.new.01", "arquivos": 3}}
        assert sorted(masters.fila_de_busca(arquivos, alvos)) == sorted(arquivos)

    def test_o_nome_da_bin_puxa_o_arquivo_para_a_frente(self):
        arquivos = ["/m/B/zzz.mxf", "/m/A/PROJETO EXEMPLO - T001_A01.mxf"]
        alvos = {umid(1): {"nome": "PROJETO EXEMPLO - T001", "arquivos": 1}}
        assert masters.fila_de_busca(arquivos, alvos)[0].endswith("T001_A01.mxf")

    def test_o_nome_TRUNCADO_do_avid_ainda_puxa(self):
        """⚠️ A 2ª convenção corta o nome num orçamento fixo de caracteres:
        `PROJETO EXEMPLO - …` vira `PROJETO EXEA01.6A8AF212609FA.mxf`. Casar só nome
        inteiro perderia isto."""
        arquivos = ["/m/B/zzz.mxf", "/m/A/PROJETO EXEA01.6A8AF212609FA.mxf"]
        alvos = {umid(1): {"nome": "PROJETO EXEMPLO - 05-04 C4 P1-T001", "arquivos": 1}}
        assert masters.fila_de_busca(arquivos, alvos)[0].endswith("6A8AF212609FA.mxf")

    def test_sem_pista_as_pastas_sao_INTERCALADAS(self):
        """⛔⛔ O conserto medido em 2026-08-23: com nome que não diz nada, a ordem
        ALFABÉTICA é pior que aleatória — a pasta certa (`PRJ`) vinha depois de
        `010020260629` e `BENTIDO-FIELD`, e o 1º acerto caía no arquivo 446 de 511.
        Intercalando, o 1º acerto chega nos primeiros arquivos venha de onde vier.
        Medido: 511 → 72 `ffprobe`."""
        arquivos = ([f"/m/000/{i}.mxf" for i in range(4)]
                    + [f"/m/zzz/{i}.mxf" for i in range(4)])
        alvos = {umid(1): {"nome": "", "arquivos": 2}}
        fila = masters.fila_de_busca(arquivos, alvos)
        assert "/m/zzz/" in fila[1], "a 2ª pasta é provada no 2º arquivo, não no 5º"

    def test_a_pasta_COM_pista_vem_inteira_antes(self):
        """Onde o filtro sabe o que está fazendo, não se intercala: a pasta que
        casou com o `Name` vem em bloco. Foi o que manteve a D02 em 200 leituras."""
        arquivos = ["/m/certa/T001_A01.mxf", "/m/certa/T001_A02.mxf",
                    "/m/outra/a.mxf", "/m/outra/b.mxf"]
        alvos = {umid(1): {"nome": "T001", "arquivos": 2}}
        fila = masters.fila_de_busca(arquivos, alvos)
        assert all("/m/certa/" in q for q in fila[:2])


class TestVarreduraDirigida:
    """A parada. É aqui que mora o modo de falha caro."""

    def test_para_quando_o_pedido_esta_completo(self, monkeypatch):
        """⭐ O ganho inteiro: não se lê o acervo, lê-se o material pedido."""
        mapa = {"/m/A/v.mxf": arquivo("/m/A/v.mxf", 1, "video"),
                "/m/A/a.mxf": arquivo("/m/A/a.mxf", 1, "audio")}
        for i in range(50):
            mapa[f"/m/Z/{i:03d}.mxf"] = arquivo(f"/m/Z/{i:03d}.mxf", 9)
        lidos = falsear_leitura(monkeypatch, mapa)

        alvos = {umid(1): {"nome": "", "arquivos": 2}}
        por_umid, _so_audio, _vistos, esgotada, _c = masters.varredura_dirigida(
            ["/m"], alvos, sorted(mapa))

        assert len(por_umid) >= 1, "achou o clipe pedido"
        assert not esgotada, "parou antes do fim da fila"
        assert len(lidos) < 52, f"leu {len(lidos)} de 52 — a parada não pegou"

    def test_arquivo_DUPLICADO_nao_completa_o_clipe(self, monkeypatch):
        """⛔⛔ A armadilha nº 1 da parada. O mesmo clipe existe copiado entre as
        pastas numeradas da `Avid MediaFiles` (`MXF/1`, `MXF/2`). Contar ARQUIVO
        faria um clipe de 3 tracks completar com o vídeo lido três vezes — e o
        clipe chegaria à timeline SEM ÁUDIO NENHUM, sem erro nenhum.

        A contagem é por `file_package_umid` DISTINTO, e é isso que este teste
        prende."""
        mapa = {
            "/m/1/v.mxf": arquivo("/m/1/v.mxf", 1, "video", file_umid="fv"),
            "/m/2/v.mxf": arquivo("/m/2/v.mxf", 1, "video", file_umid="fv"),
            "/m/3/v.mxf": arquivo("/m/3/v.mxf", 1, "video", file_umid="fv"),
            "/m/1/a.mxf": arquivo("/m/1/a.mxf", 1, "audio", file_umid="fa"),
        }
        falsear_leitura(monkeypatch, mapa)

        alvos = {umid(1): {"nome": "", "arquivos": 2}}
        por_umid, _so, _v, _e, _c = masters.varredura_dirigida(["/m"], alvos, sorted(mapa))

        from avid.mcapi import mob_id_para_pyavb
        achado = por_umid[mob_id_para_pyavb(umid(1))]
        assert any(q.endswith("a.mxf") for q in achado), \
            "o áudio entrou: três cópias do vídeo não fecharam o clipe"

    def test_sem_Tracks_a_fila_vai_ate_o_fim(self, monkeypatch):
        """Não saber quantos arquivos o master tem custa ler tudo — e é o preço
        certo. Parar por palpite é o que deixa clipe mutilado."""
        mapa = {f"/m/A/{i}.mxf": arquivo(f"/m/A/{i}.mxf", 1) for i in range(6)}
        lidos = falsear_leitura(monkeypatch, mapa)

        alvos = {umid(1): {"nome": "", "arquivos": None}}
        _p, _s, _v, esgotada, _c = masters.varredura_dirigida(["/m"], alvos, sorted(mapa))

        assert esgotada and len(lidos) == 6

    def test_a_pasta_que_ACERTOU_vai_para_a_frente(self, monkeypatch):
        """⭐ O sinal que sobra quando o nome não diz nada: o Avid grava as N
        tracks de um clipe na MESMA pasta. O 1º acerto revela onde o material
        está — informação que não existia antes de começar a ler."""
        mapa = {}
        for i in range(20):
            mapa[f"/m/lixo/{i:03d}.mxf"] = arquivo(f"/m/lixo/{i:03d}.mxf", 9)
        for i in range(4):
            mapa[f"/m/util/{i:03d}.mxf"] = arquivo(f"/m/util/{i:03d}.mxf", 1)
        # Um trabalhador só nunca reordena (não há "entre lotes"): aqui o paralelo
        # é o que se quer exercitar.
        lidos: list[str] = []
        monkeypatch.setattr(opatom, "probe_file",
                            lambda c, timeout=30: (lidos.append(c), {"c": c})[1])
        monkeypatch.setattr(opatom, "parse_probe",
                            lambda doc, c: mapa.get(c, "não é OP-Atom"))
        monkeypatch.setattr(opatom, "trabalhadores", lambda pedido=None: 2)

        alvos = {umid(1): {"nome": "", "arquivos": 4}}
        _p, _s, _v, esgotada, _c = masters.varredura_dirigida(["/m"], alvos, sorted(mapa))

        assert not esgotada
        assert len(lidos) < 24, f"leu {len(lidos)} de 24 — a afinidade de pasta não pegou"


class TestProbarMuitos:
    """O probe em lotes paralelos."""

    def test_a_ordem_de_saida_e_a_da_FILA(self, monkeypatch):
        """⚠️ Não a de término. Quem chama ordenou a fila por um motivo, e devolver
        na ordem em que o `ffprobe` respondeu jogaria esse trabalho fora."""
        monkeypatch.setattr(opatom, "probe_file", lambda c, timeout=30: {"c": c})
        fila = [f"/m/{i:03d}.mxf" for i in range(25)]
        saida = [c for c, _doc in opatom.probar_muitos(fila, workers=4)]
        assert saida == fila

    def test_parar_no_meio_nao_le_o_resto(self, monkeypatch):
        """⭐ É o que a parada antecipada precisa: abandonar o gerador derruba o
        pool, e nenhum `ffprobe` segue rodando atrás de resposta que ninguém lê."""
        lidos: list[str] = []
        monkeypatch.setattr(opatom, "probe_file",
                            lambda c, timeout=30: (lidos.append(c), {"c": c})[1])
        fila = [f"/m/{i:03d}.mxf" for i in range(100)]
        for _c, _doc in opatom.probar_muitos(fila, workers=4):
            if len(lidos) >= 4:
                break
        assert len(lidos) <= 8, f"leu {len(lidos)} depois de parar no 4º"

    def test_reordenar_e_chamado_entre_lotes(self, monkeypatch):
        monkeypatch.setattr(opatom, "probe_file", lambda c, timeout=30: {"c": c})
        fila = [f"/m/{i:03d}.mxf" for i in range(12)]
        chamadas = []

        def reordenar(restantes):
            chamadas.append(len(restantes))
            return restantes

        list(opatom.probar_muitos(fila, workers=4, reordenar=reordenar))
        assert chamadas == [8, 4], "chamado depois de cada lote, menos o último"
