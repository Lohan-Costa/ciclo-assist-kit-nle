"""A sequência ativa do Premiere → os merged a criar (`premiere/tomadas.py`)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from avid import nomear
from premiere.tomadas import ler_registros, nomes_por_caminho, pares

FPS = 24.0
CAM_A = r"D:\diaria\CAM A\A001.mov"
CAM_B = "/Volumes/X/diaria/CAM B/B001.mov"
SOM = r"D:\diaria\SOM\C4 P1-T002.wav"   # nome real de gravador


def linha(kind, track, index, start, in_point, dur, path, sel=False):
    return "\t".join([kind, str(track), str(index), f"{start:.4f}", f"{in_point:.4f}",
                      f"{dur:.4f}", "1" if sel else "0", path])


def sequencia(*linhas):
    return ler_registros("\n".join(linhas))


def som_em_5_canais(start, in_point, dur, cortes=()):
    """O som direto como o builder o põe: 5 trilhas, fatiadas nos limites das câmeras."""
    pontos = [start, *cortes, start + dur]
    out = []
    for canal in range(5):
        for i, (a, b) in enumerate(zip(pontos, pontos[1:])):
            out.append(linha("A", canal, i, a, in_point + (a - start), b - a, SOM))
    return out


def test_um_par_aparado_onde_imagem_e_som_coexistem():
    # Som de 10 s a 20 s; câmera de 15 s a 30 s, com in=3 s dentro do arquivo.
    itens = sequencia(linha("V", 0, 0, 15, 3, 15, CAM_A),
                      *som_em_5_canais(10, 0, 10))
    lista, resumo = pares(itens, FPS)

    assert len(lista) == 1
    p = lista[0]
    assert (p.camera, p.som) == (CAM_A, SOM)
    assert p.corte_in == pytest.approx(3)     # a câmera começa dentro do som
    assert p.corte_out == pytest.approx(8)    # e o som acaba 5 s depois
    assert p.som_no_relogio_da_camera == pytest.approx(10 - 12)
    assert p.tomada.duracao == 5 * 24
    assert p.tomada.duracao_bruta == 15 * 24
    assert p.tomada.aparado == 10 * 24
    assert resumo == {"orfaos_de_camera": 0, "orfaos_de_som": 0, "disputados": 0}


def test_o_som_fatiado_em_canais_e_segmentos_conta_como_um_so():
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A),
                      linha("V", 1, 0, 10, 0, 10, CAM_B),
                      *som_em_5_canais(0, 0, 20, cortes=(10,)))
    lista, resumo = pares(itens, FPS)
    assert [p.camera for p in lista] == [CAM_A, CAM_B]
    assert resumo["orfaos_de_som"] == 0
    assert lista[1].tomada.trechos[0].start == 10 * 24   # o som entra no segundo 10


def test_audio_da_propria_camera_nao_e_som_direto():
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A),
                      linha("A", 5, 0, 0, 0, 10, CAM_A))
    lista, resumo = pares(itens, FPS)
    assert [p.som for p in lista] == [""]      # o áudio da própria câmera não conta como som direto: sai solta
    assert resumo["orfaos_de_camera"] == 1
    assert resumo["orfaos_de_som"] == 0


def test_a_camera_sem_som_vira_um_solto_e_o_som_sem_camera_fica_de_fora():
    itens = sequencia(linha("V", 0, 0, 100, 0, 10, CAM_A),
                      *som_em_5_canais(0, 0, 10))
    lista, resumo = pares(itens, FPS)
    assert [p.som for p in lista] == [""] and lista[0].tomada.orfao is True
    assert resumo["orfaos_de_camera"] == 1
    assert resumo["orfaos_de_som"] == 1


def test_o_solto_presume_a_cena_pelo_vizinho():
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A), *som_em_5_canais(0, 0, 10),
                      linha("V", 0, 1, 50, 0, 10, CAM_B))
    lista, _ = pares(itens, FPS)
    assert [p.som for p in lista] == [SOM, ""]
    assert (lista[1].tomada.cena, lista[1].tomada.plano) == ("C04", "P01")
    assert lista[1].tomada.convencao == "posicao" and lista[1].tomada.take.startswith("T002.")


def test_camera_disputada_fica_com_o_som_que_mais_cobre():
    outro = r"D:\diaria\SOM\C4 P1-T003.wav"
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A),
                      linha("A", 0, 0, -5, 0, 7, SOM),       # cobre 2 s
                      linha("A", 0, 1, 2, 0, 20, outro))      # cobre 8 s
    lista, resumo = pares(itens, FPS)
    assert lista[0].som == outro
    assert resumo["disputados"] == 1
    assert resumo["orfaos_de_som"] == 1


def test_o_mesmo_som_em_duas_posicoes_sao_duas_instancias():
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A),
                      linha("V", 0, 1, 50, 0, 10, CAM_B),
                      linha("A", 0, 0, 0, 0, 10, SOM),
                      linha("A", 0, 1, 50, 30, 10, SOM))
    lista, _ = pares(itens, FPS)
    assert [p.tomada.trechos[0].start for p in lista] == [0, 30 * 24]


def test_so_selecionados():
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A, sel=True),
                      linha("V", 1, 0, 0, 0, 10, CAM_B),
                      *som_em_5_canais(0, 0, 10))
    assert [p.camera for p in pares(itens, FPS, so_selecionados=True)[0]] == [CAM_A]
    assert len(pares(itens, FPS)[0]) == 2


def test_linha_malformada_nao_derruba_e_tab_no_caminho_sobrevive():
    itens = ler_registros("lixo\nV\t0\tx\t0\t0\t1\t0\t/a.mov\n" +
                          linha("V", 0, 0, 0, 0, 1, "/pasta\tcom tab/a.mov"))
    assert [i.path for i in itens] == ["/pasta\tcom tab/a.mov"]


def test_fps_invalido_recusa():
    with pytest.raises(ValueError):
        pares([], 0)


def test_o_motor_de_nomes_do_avid_nomeia_as_tomadas_do_premiere():
    """⭐ A costura: `avid.nomear` não sabe de onde a `Tomada` veio."""
    itens = sequencia(linha("V", 0, 0, 0, 0, 10, CAM_A),
                      linha("V", 1, 0, 0, 0, 10, CAM_B),
                      *som_em_5_canais(0, 0, 10))
    lista, _ = pares(itens, FPS)
    tomadas = [p.tomada for p in lista]
    nomes = nomes_por_caminho(lista)

    padrao = nomear.prever(tomadas, "", {}, nomes)
    assert [l["nome"] for l in padrao["linhas"]] == ["A001.mov", "B001.mov"]

    claquete = nomear.prever(tomadas, "C%{cena}_T%{take2}_%{nomedevideo}", {}, nomes)
    assert not claquete["bloqueado"]
    assert [l["nome"] for l in claquete["linhas"]] == [
        "C04_T002_A001.mov", "C04_T002_B001.mov"]
    assert all(l["repetido"] is False for l in claquete["linhas"])

    # A coluna da bin ganha do nome do arquivo.
    colunas = {"C4 P1-T002.wav": {"Scene": "25", "Take": "7"}}
    lista2, _ = pares(itens, FPS, colunas=colunas)
    r = nomear.prever([p.tomada for p in lista2], "C%{cena}", colunas, nomes)
    assert [l["nome"] for l in r["linhas"]] == ["C25", "C25"]


def test_a_diaria_numero_numero_presume_cena_e_plano_e_o_ambiguo_fica():
    from media.identidade import presumir_da_forma
    cenas = ["18-1", "18-2", "40B-1", "55-3", "18-EXTRA"]
    assert presumir_da_forma(cenas) == {"18-1": ("C18", "P01"), "18-2": ("C18", "P02"), "40B-1": ("C40B", "P01"),
                                        "55-3": ("C55", "P03")}
    assert presumir_da_forma(["18-1", "x", "y", "z", "w"]) == {}      # minoria não autoriza
    assert presumir_da_forma(["18-1", "18-2"]) == {}                  # pouco demais


def test_o_som_sem_claquete_no_nome_usa_as_tags_do_arquivo():
    from premiere.tomadas import completar_colunas
    itens = sequencia(linha("A", 0, 0, 0, 0, 10, r"D:\s\18-1T01.WAV"), linha("A", 1, 0, 0, 0, 10, SOM))
    vistos = []

    def sondar(c):
        vistos.append(c)
        return {"scene": "18-1", "take": "01"}

    col = completar_colunas(itens, {}, sondar)
    assert col == {"18-1T01.WAV": {"Scene": "18-1", "Take": "01"}} and len(vistos) == 1   # o nome com claquete não paga leitura
