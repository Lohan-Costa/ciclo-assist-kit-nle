"""De um arquivo à mídia do cache: chave, apelido, e o convertido medido pelo conteúdo.

Plano `docs/plano/2026-09-17-premiere.md`, P1. Os números dos pisos vêm de pares reais
(`spikes/o_convertido_casa.py`); aqui a mídia é sintética, gerada pelo ffmpeg.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from cicloassist.midia import cache as C
from cicloassist.midia import identidade as I

UMID_A = "060a2b340101010501010f10130000001a1644631260a3063853d011e5e7034e"
UMID_B = "060a2b340101010501010f10130000001a1bf8691260a306dd43d011e5e7034e"

tem_ffmpeg = pytest.mark.skipif(not (shutil.which("ffmpeg") and shutil.which("ffprobe")),
                                reason="sem ffmpeg nesta máquina")


@pytest.fixture(autouse=True)
def processo_novo():
    C._indices.clear()
    I.esquecer()
    yield
    C._indices.clear()
    I.esquecer()


def _nascer(chave: str, **rotulo) -> C.Midia:
    m = C.Midia(chave, rotulo=rotulo)
    m.pasta  # noqa: B018 — nascer é escrever
    return m


# ── a impressão ──────────────────────────────────────────────────────────────

def test_a_impressao_e_do_conteudo_e_nao_do_caminho(tmp_path):
    dados = bytes(range(256)) * 50_000  # 12,8 MB: o começo e o fim são pedaços diferentes
    a, b = tmp_path / "a.mov", tmp_path / "outra pasta" / "b.mov"
    b.parent.mkdir()
    a.write_bytes(dados)
    b.write_bytes(dados)
    assert I.impressao(a) == I.impressao(b)
    assert len(I.impressao(a)) == 64

    c = tmp_path / "c.mov"
    c.write_bytes(dados[:-1] + b"\x00")  # só o último byte
    assert I.impressao(c) != I.impressao(a)


def test_a_impressao_fica_guardada_e_cai_quando_o_arquivo_muda(tmp_path):
    arq = tmp_path / "x.wav"
    arq.write_bytes(b"1" * 1000)
    primeira = I.impressao(arq)
    guardado = json.loads((C.raiz() / "identidades.json").read_text(encoding="utf-8"))
    assert any(v.get("impressao") == primeira for v in guardado.values())

    arq.write_bytes(b"2" * 2000)  # tamanho novo = marca nova
    assert I.impressao(arq) != primeira


# ── a pista ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("nome, esperado", [
    ("20240531_PANA2774.mov", "20240531_pana2774"),
    ("20240531_PANA2774.new.01", "20240531_pana2774"),
    ("a001_03170214_C001", "a001_03170214_c001"),
    ("A001_03170214_C001.mp4", "a001_03170214_c001"),
    ("10 Car Interior B.wav", "10 car interior b"),
    (r"D:\x\Açaí.MOV", "acai"),
    ("C07_P02-T001.1", "c07_p02-t001.1"),  # `.1` não é extensão de mídia
])
def test_o_nome_normalizado(nome, esperado):
    assert I.normalizar_nome(nome) == esperado


def _v(**k):
    base = {"tipo": "video", "nome_da_fonte": "X.mov", "fps": "24000/1001",
            "quadros": 1236, "tc": "23:16:47:11", "duracao_s": 51.55}
    base.update(k)
    return base


def test_candidato_de_video_exige_nome_taxa_quadros_e_tc():
    assert I.e_candidato(_v(), _v(nome_da_fonte="x.new.01", quadros=1235))
    assert not I.e_candidato(_v(), _v(quadros=1238))
    assert not I.e_candidato(_v(), _v(fps="25"))
    assert not I.e_candidato(_v(), _v(tc="23:17:38:23"))
    assert not I.e_candidato(_v(), _v(nome_da_fonte="Y.mov"))
    assert I.e_candidato(_v(tc=""), _v())  # quem não tem TC não reprova por TC
    assert not I.e_candidato(_v(), _v(tipo="audio"))


def test_candidato_de_som_e_nome_e_duracao_com_folga_de_um_quadro():
    a = {"tipo": "audio", "nome_da_fonte": "10 Car Interior B.wav", "duracao_s": 53.989}
    assert I.e_candidato(a, dict(a, duracao_s=54.012))  # o arredondamento do Avid, medido
    assert not I.e_candidato(a, dict(a, duracao_s=55.0))


# ── os apelidos no cache ─────────────────────────────────────────────────────

def test_o_apelido_leva_a_mesma_pasta_e_a_chave_de_verdade():
    m = _nascer(UMID_A, nome="PANA2774", tipo="video")
    outra = "ab" * 32
    assert m.apelidar(outra, "conteudo", arquivo="D:/x.mov")

    pelo_apelido = C.Midia(outra)
    assert pelo_apelido.existe
    assert pelo_apelido.chave == UMID_A
    assert len(C.todas()) == 1  # nunca uma pasta por apelido

    C._indices.clear()  # outro processo: o apelido vem do manifesto
    assert C.Midia(outra).existe
    assert C.com_apelidos({outra}) == {outra, UMID_A}


def test_chave_de_outra_midia_nunca_vira_apelido():
    """⛔ Juntaria duas mídias, e a busca apontaria uma pela outra para sempre."""
    a = _nascer(UMID_A, nome="A")
    _nascer(UMID_B, nome="B")
    assert a.apelidar(UMID_B, "mob_id") is False
    assert C.Midia(UMID_B).achada().name.startswith("B_")


def test_apelido_dado_ao_nascer():
    m = C.Midia("cd" * 32, tipo="conteudo", apelidos={UMID_A: "mob_id"},
                rotulo={"nome": "clip.mov"})
    m.pasta  # noqa: B018
    manifesto = m.manifesto()
    assert manifesto["identidades"] == {"conteudo": "cd" * 32}
    assert manifesto["apelidos"][0] == {"chave": UMID_A, "tipo": "mob_id"}
    pelo_mob = C.Midia(UMID_A)
    assert pelo_mob.existe and pelo_mob.chave == "cd" * 32


# ── o convertido, de ponta a ponta ───────────────────────────────────────────

def _ffmpeg(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True, timeout=120)


def _video(destino: Path, fonte: str, codec: list[str], tc="10:00:00:00"):
    _ffmpeg("-f", "lavfi", "-i", f"{fonte}=size=320x180:rate=24000/1001", "-t", "4",
            *codec, "-timecode", tc, str(destino))
    return destino


def _convertido(pasta, nome, arquivo, tipo):
    m = _nascer(UMID_A if tipo == "video" else UMID_B, nome=nome, tipo=tipo,
                arquivos=[str(arquivo)])
    return m


@tem_ffmpeg
def test_o_original_acha_o_convertido_pela_imagem_e_vira_apelido(tmp_path):
    original = _video(tmp_path / "PLANO01.mov", "testsrc2", ["-c:v", "prores_ks"])
    conv = _video(tmp_path / "A01.xyz.mxf", "testsrc2",
                  ["-c:v", "mpeg2video", "-q:v", "4"])
    m = _convertido(tmp_path, "PLANO01.new.01", conv, "video")

    achado = I.achar(original)
    assert achado.como == "convertido", achado.avisos
    assert achado.chave == m.chave
    assert achado.medida >= I.PISO_IMAGEM

    # A segunda pergunta não mede: o arquivo já é apelido.
    I.esquecer()
    C._indices.clear()
    de_novo = I.achar(original, medir=False)
    assert de_novo.como == "chave" and de_novo.chave == m.chave
    apelido = C.Midia(m.chave).apelidos()[0]
    assert apelido["fonte"] == "visual" and apelido["confianca"] == "confirmado"


@tem_ffmpeg
def test_mesmo_nome_e_duracao_com_outra_imagem_nao_e_o_mesmo(tmp_path):
    """O impostor que a regra do banco prevê: nome, TC e duração batem, o conteúdo não."""
    original = _video(tmp_path / "PLANO01.mov", "testsrc2", ["-c:v", "prores_ks"])
    impostor = _video(tmp_path / "B.mxf", "mandelbrot", ["-c:v", "mpeg2video"])
    _convertido(tmp_path, "PLANO01", impostor, "video")

    achado = I.achar(original)
    assert achado.como == "nada"
    assert achado.midia is None
    assert "não bate" in achado.avisos[0]


def _som(destino: Path, filtro: str, taxa: int, canais: int = 1):
    _ffmpeg("-f", "lavfi", "-i", filtro, "-t", "6", "-ar", str(taxa), "-ac", str(canais),
            str(destino))
    return destino


@tem_ffmpeg
def test_o_wav_acha_o_som_convertido_mesmo_deslocado(tmp_path):
    """MEDIDO no par real: o OP-Atom começa 8 ms depois do WAV. A folga cobre isso."""
    fonte = "anoisesrc=d=7:c=pink:seed=7"
    original = _som(tmp_path / "10 Car Interior B.wav", fonte, 96000, canais=2)
    conv = tmp_path / "A01.mxf.wav"
    _ffmpeg("-i", str(original), "-ss", "0.008", "-ar", "48000", "-ac", "1", str(conv))
    m = _convertido(tmp_path, "10 Car Interior B.wav", conv, "audio")

    achado = I.achar(original)
    assert achado.como == "convertido", achado.avisos
    assert achado.chave == m.chave
    assert achado.medida >= I.PISO_SOM


@tem_ffmpeg
def test_outro_som_com_o_mesmo_nome_nao_e_o_mesmo(tmp_path):
    original = _som(tmp_path / "Take.wav", "anoisesrc=d=7:c=pink:seed=7", 48000)
    outro = _som(tmp_path / "outro.wav", "anoisesrc=d=7:c=pink:seed=8", 48000)
    _convertido(tmp_path, "Take.wav", outro, "audio")
    assert I.achar(original).como == "nada"


@tem_ffmpeg
def test_sem_medir_o_desconhecido_nao_decodifica_nada(tmp_path, monkeypatch):
    original = _video(tmp_path / "PLANO01.mov", "testsrc2", ["-c:v", "prores_ks"])
    monkeypatch.setattr(I, "mesma_imagem", lambda *a: pytest.fail("mediu sem pedir"))
    achado = I.achar(original, medir=False)
    assert achado.como == "nada" and achado.tipo == "conteudo"


# ── o master AMA do Avid, e o cache de antes da P1 ───────────────────────────

from cicloassist.avid import take as T  # noqa: E402

MOB = "urn:smpte:umid:060a2b34.01010105.01010f10.13000000.80bb92e5.20a1d5de.e2eb46e0.54d39bdf"


def _mov(tmp_path) -> str:
    arq = tmp_path / "PANA2774.mov"
    arq.write_bytes(b"conteudo de camera" * 1000)
    return str(arq)


def test_ama_novo_nasce_pelo_conteudo_com_o_mob_id_de_apelido(tmp_path, monkeypatch):
    monkeypatch.setattr(I, "sondar", lambda a: {"umid": ""})
    arq = _mov(tmp_path)
    f = T.Fonte(master="PANA2774", mob_id=MOB, arquivos=[arq], inicio_frames=0,
                inicio_s=0, tracks=1, origem="ama", **T._chave_ama(MOB, arq))
    assert f.chave == I.impressao(arq) and f.tipo_da_chave == "conteudo"

    m = f.midia(rotulo={"nome": "PANA2774"})
    m.pasta  # noqa: B018
    # Outro projeto, outro link: um mob_id NOVO acha a mesma pasta pelo arquivo.
    outro_mob = MOB[:-4] + "0000"
    g = T._chave_ama(outro_mob, arq)
    assert g["chave"] == f.chave
    assert C.Midia(C.de_umid(outro_mob)).chave == f.chave
    assert C.Midia(C.de_umid(MOB)).chave == f.chave


def test_ama_processado_antes_da_p1_continua_na_pasta_do_mob_id(tmp_path, monkeypatch):
    """Nada é reprocessado: a pasta antiga é a dona, e o conteúdo vira apelido dela."""
    monkeypatch.setattr(I, "sondar", lambda a: {"umid": ""})
    antiga = _nascer(MOB, nome="PANA2774")
    arq = _mov(tmp_path)
    assert T._chave_ama(MOB, arq) == {}  # fica o mob_id
    assert C.Midia(I.impressao(arq)).chave == antiga.chave
    assert len(C.todas()) == 1


def test_ama_ilegivel_fica_com_o_mob_id(tmp_path):
    assert T._chave_ama(MOB, str(tmp_path / "sumiu.mov")) == {}
    f = T.Fonte(master="x", mob_id=MOB, arquivos=[], inicio_frames=0, inicio_s=0, tracks=1)
    assert f.chave == MOB


def test_apelidar_e_anotar_fonte_ao_mesmo_tempo_nao_perdem_um_ao_outro():
    """⛔ Os dois leem e regravam o MANIFESTO inteiro. Sem trava, o último apaga o outro —
    e o sintoma é uma identidade que some, sem erro nenhum."""
    import threading

    m = _nascer(UMID_A, nome="PANA2774")
    erros = []

    def apelidando(n):
        try:
            C.Midia(UMID_A).apelidar(f"{n:02x}" * 32, "conteudo")
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    def anotando(n):
        try:
            C.Midia(UMID_A).anotar_fonte({"master": f"PANA2774", "arquivo": f"D:/{n}.mov"})
        except Exception as e:  # noqa: BLE001
            erros.append(e)

    fios = [threading.Thread(target=apelidando if n % 2 else anotando, args=(n,))
            for n in range(16)]
    for f in fios:
        f.start()
    for f in fios:
        f.join()

    assert not erros
    manifesto = C.Midia(UMID_A).manifesto()
    assert len(manifesto.get("apelidos") or []) == 8   # nenhum apelido se perdeu
    assert manifesto.get("fonte", {}).get("master") == "PANA2774"


@tem_ffmpeg
def test_o_nao_e_nada_disto_tambem_fica_guardado(tmp_path, monkeypatch):
    """⭐ Sem isto, todo `ver_frames` de um clipe sem par no cache remedia o mesmo minuto de
    vídeo — para sempre. ⚠️ E o veredito cai quando o cache ganha mídia nova."""
    original = _video(tmp_path / "PLANO01.mov", "testsrc2", ["-c:v", "prores_ks"])
    impostor = _video(tmp_path / "B.mxf", "mandelbrot", ["-c:v", "mpeg2video"])
    _convertido(tmp_path, "PLANO01", impostor, "video")

    medidas = []
    real = I.mesma_imagem
    monkeypatch.setattr(I, "mesma_imagem", lambda *a: (medidas.append(1), real(*a))[1])

    assert I.achar(original).como == "nada"
    assert len(medidas) == 1
    assert I.achar(original).como == "nada"
    assert len(medidas) == 1, "mediu de novo o que já tinha sido medido"

    # Mídia nova no cache: o veredito de antes não vale mais.
    _nascer(UMID_B, nome="PLANO01", tipo="video", arquivos=[str(impostor)])
    assert I.achar(original).como == "nada"
    assert len(medidas) > 1


# ── o som do gravador: multipista, fora de ordem, e o rolo no nome ───────────
#
# ⛔⛔ Os dois defeitos abaixo foram achados juntos, em 2026-09-21, medindo o projeto do
# PREMIERE do editor contra o cache que o Avid tinha montado. A causa comum é que os pares
# medidos no porte (banco, `banco-de-midias-compartilhado.md` §8) eram os dois de IMAGEM:
# o som direto de cena — que é a camada MAIOR do acervo, a transcrita — nunca passou por
# ali, e trouxe duas formas que nenhuma das duas reguas de vídeo conhecia.


def test_o_rolo_no_nome_do_som_nao_separa_o_par():
    """⛔⛔ O `reel_name` do OP-Atom de som traz `:<data do rolo>` grudado no fim.

    MEDIDO: `PRODUCAO-A - 05-04 C14 P1-T010.WAV:2023-04-06` contra o arquivo
    `PRODUCAO-A - 05-04 C14 P1-T010.WAV`. Como o `.wav` deixava de ser o FIM do nome, a
    extensão não saía, os nomes divergiam, e o par nem virava candidato — com as durações
    **idênticas** (146,146 s). **36 das 332 mídias** daquele cache têm essa forma.
    """
    do_avid = "PRODUCAO-A - 05-04 C14 P1-T010.WAV:2023-04-06"
    do_disco = "PRODUCAO-A - 05-04 C14 P1-T010.WAV"
    assert I.normalizar_nome(do_avid) == I.normalizar_nome(do_disco)
    # ⚠️ E o que já funcionava continua: extensão no fim, `.new.NN`, pasta, caixa.
    assert I.normalizar_nome("D:/x/20240531_PANA2774.mov") == "20240531_pana2774"
    assert I.normalizar_nome("20240531_PANA2774.new.01") == "20240531_pana2774"

    a = {"tipo": "audio", "nome_da_fonte": do_disco, "duracao_s": 146.146}
    b = {"tipo": "audio", "nome_da_fonte": do_avid, "duracao_s": 146.146}
    assert I.e_candidato(a, b)


@tem_ffmpeg
def test_o_som_multipista_casa_fora_de_ordem(tmp_path):
    """⛔⛔ **Somar os dois lados não prova nada quando o som é multipista.**

    MEDIDO no `PRODUCAO-A - 05-04 C11 P1-T001` do editor: WAV de 5 canais contra 5
    OP-Atom, a soma de cada lado deu **0,876** — abaixo do piso, logo "não é o mesmo
    material" — porque o Avid guardou os mesmos canais **em outra ordem e com um
    duplicado** (A01 = A02 = ch2). Canal a canal, o pior par é **0,998**.

    ⚠️⚠️ **E a régua é o MELHOR par, não o pior — o material me corrigiu.** A primeira
    versão exigia que TODO canal de um dos lados achasse o seu, e reprovou um par
    verdadeiro: `A009_03190845_C003.BRAW` × o OP-Atom dele deu `ch1 +0,789 · ch2 +1,000`,
    com 547 quadros, TC e duração idênticos. O 0,789 é o transcode processando UMA pista —
    exigir que todas sobrevivam é exigir que o transcode seja sem perdas por canal.

    Aqui isso é reproduzido em miniatura: quatro fontes distintas, o WAV na ordem 1-2-3-4 e
    o "Avid" em 3-1-1-4 — trocado, com uma repetida e sem uma.
    """
    fontes = [f"anoisesrc=d=7:c=pink:seed={s}" for s in (11, 22, 33, 44)]
    monos = [_som(tmp_path / f"ch{i}.wav", f, 48000) for i, f in enumerate(fontes, 1)]
    poli = tmp_path / "C11 P1-T001.WAV"
    _ffmpeg(*sum((["-i", str(m)] for m in monos), []),
            "-filter_complex", "[0:a][1:a][2:a][3:a]amerge=inputs=4[o]", "-map", "[o]",
            "-ar", "48000", str(poli))
    fora_de_ordem = [monos[2], monos[0], monos[0], monos[3]]
    assert I.mesmo_som([poli], fora_de_ordem) >= I.PISO_SOM

    # ⭐ E o RECORTE: o editor importou 2 das 4 pistas. Continua sendo o mesmo material.
    assert I.mesmo_som([poli], monos[:2]) >= I.PISO_SOM

    # ⛔ O impostor de verdade não tem canal NENHUM em comum — é o take vizinho, e foi
    #   assim que ele se mediu no acervo real: 0,024 contra 1,000.
    outros = [_som(tmp_path / f"o{i}.wav", f"anoisesrc=d=7:c=pink:seed={9 + i}", 48000)
              for i in range(2)]
    assert I.mesmo_som([poli], outros) < I.PISO_SOM


@tem_ffmpeg
def test_a_sonda_conta_CANAIS_e_nao_so_pistas(tmp_path):
    """⚠️ Pista não é canal: o WAV do gravador é UMA pista com CINCO canais, e o Avid
    guarda o mesmo material como CINCO arquivos de uma pista cada."""
    poli = _som(tmp_path / "poli.wav", "anoisesrc=d=7:c=pink:seed=5", 48000, canais=4)
    s = I.sondar(poli)
    assert s["pistas_de_som"] == 1 and s["canais_de_som"] == [4]
    assert I._som_por_canal([poli]).shape[0] == 4


@tem_ffmpeg
def test_pista_em_silencio_nao_vota_mas_nao_derruba(tmp_path):
    """⚠️ Um canal mudo não tem o que correlacionar. Ele não pode valer −1 e reprovar um
    par verdadeiro — nem valer como prova de que os dois são o mesmo material."""
    real = _som(tmp_path / "real.wav", "anoisesrc=d=7:c=pink:seed=3", 48000)
    mudo = _som(tmp_path / "mudo.wav", "anullsrc=r=48000:cl=mono", 48000)
    poli = tmp_path / "com_mudo.wav"
    _ffmpeg("-i", str(real), "-i", str(mudo),
            "-filter_complex", "[0:a][1:a]amerge=inputs=2[o]", "-map", "[o]",
            "-ar", "48000", str(poli))
    assert I.mesmo_som([poli], [real]) >= I.PISO_SOM
    # ⛔ Só silêncio dos dois lados é "não sei", nunca "é o mesmo".
    assert I.mesmo_som([mudo], [mudo]) < I.PISO_SOM


@tem_ffmpeg
def test_clipe_mais_curto_que_as_posicoes_ainda_casa(tmp_path):
    """⚠️ **`-1` quer dizer "não consegui comparar", e era lido como "não é o mesmo".**

    Um clipe com menos quadros que `POSICOES` fazia `distribuir` repetir posição; o
    `select` do ffmpeg entrega cada quadro uma vez só, voltavam menos quadros que
    posições, e a conferência reprovava. MEDIDO no projeto do editor:
    `B001_03150154_C017`, de **4 quadros**, era o único vídeo que não casava — com nome,
    TC, taxa e número de quadros idênticos aos do cache.
    """
    curto = tmp_path / "PLANO_CURTO.mov"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=320x180:rate=24000/1001", "-t", "0.17",
            "-c:v", "prores_ks", str(curto))
    conv = tmp_path / "A01.xyz.mxf"
    _ffmpeg("-i", str(curto), "-c:v", "mpeg2video", "-q:v", "4", str(conv))
    quadros = int(I.sondar(curto)["quadros"])
    assert quadros < I.POSICOES, f"o teste precisa de um clipe curto (tem {quadros})"
    assert I.mesma_imagem(curto, conv, quadros) >= I.PISO_IMAGEM


@tem_ffmpeg
def test_o_take_renomeado_na_bin_ainda_acha_o_seu_par(tmp_path):
    """⛔⛔ **O editor RENOMEIA o take na bin, e o filtro barato de nome cegava.**

    MEDIDO em 2026-09-21: o arquivo é `PRODUCAO-A - 05-04 C14 P1-T010.WAV` e a bin do
    Avid chama o MESMO material de `PRODUCAO-A - 05-04 C14 P1/010`. Os OP-Atom trazem o
    `reel_name` certo e a duração idêntica (146,146 s), mas a mídia nem virava candidata —
    e o Premiere reprocessaria uma transcrição que já existia.

    ⚠️ A passada ampla só corre quando a barata não acha NADA: ela sonda o cache inteiro
    (10 s na primeira vez, aqui; depois guardado), e a alternativa nesse ponto é
    reprocessar.
    """
    original = _som(tmp_path / "C14 P1-T010.WAV", "anoisesrc=d=7:c=pink:seed=4", 48000)
    # ⭐ O ARQUIVO do cache carrega o nome de origem (é o `reel_name` do OP-Atom real); o
    #   MANIFESTO carrega o nome da BIN, que é o que o editor renomeou.
    (tmp_path / "op_atom").mkdir()
    conv = tmp_path / "op_atom" / "C14 P1-T010.wav"
    _ffmpeg("-i", str(original), "-ar", "48000", "-ac", "1", str(conv))
    _convertido(tmp_path, "C14 P1/010", conv, "audio")

    s = I.sondar(original)
    assert I.candidatos(s) == [], "pelo nome da bin, não casa mesmo"
    assert len(I.candidatos(s, ampliar=True)) == 1, "pelo nome de dentro do arquivo, casa"
    assert I.achar(original).como == "convertido"


# ── RAW de câmera: o que o ffmpeg NÃO decodifica ─────────────────────────────

def test_o_rolo_no_reel_name_nao_vence_o_nome_do_arquivo():
    """⛔⛔ O contêiner BRAW traz `reel_name = "1"` numa tag de stream — é o ROLO, não o
    clipe —, e ela vencia o nome do arquivo: `B001_03150115_C003.BRAW` virava a fonte
    `"1"`, e o BRAW não era candidato do próprio transcode que o Avid já processara (fps,
    nº de quadros e TC IDÊNTICOS). ⚠️ Nos 332 masters do cache real, NENHUM OP-Atom tem
    nome degenerado: a regra só alcança quem ela deve alcançar.

    ⚠️ Teste de unidade de propósito: o ffmpeg **não grava `reel_name` em MOV** (conferido
    em 2026-09-21), então a primeira versão deste teste, feita com arquivo de verdade,
    passava sem exercitar nada — o instrumento mentindo, de novo.
    """
    def nome(arquivo, tags_do_stream=None, **do_formato):
        fluxos = [{"tags": t} for t in (tags_do_stream or [])]
        return I._nome_da_fonte(Path(arquivo), do_formato, fluxos)

    # ⛔ O rolo do BRAW: só dígitos.
    assert nome("B001_03150115_C003.BRAW", [{"reel_name": "1"}]) == "B001_03150115_C003.BRAW"
    assert nome("X.mxf", [{"reel_name": "02"}]) == "X.mxf"
    assert nome("X.mxf", [{"reel_name": "A"}]) == "X.mxf"
    # ⭐ E um `reel_name` de verdade continua mandando — é o que faz o OP-Atom sem nome
    #   legível (`A01.E69C….mxf`) achar o original.
    assert nome("A01.E69C1234.mxf", [{"reel_name": "PLANO01"}]) == "PLANO01"
    # ⚠️ A precedência não muda: o stream ganha do formato, o formato ganha do arquivo.
    assert nome("X.mxf", [{"reel_name": "DO_STREAM"}], reel_name="DO_FORMATO") == "DO_STREAM"
    assert nome("X.mxf", [{"reel_name": "1"}], reel_name="DO_FORMATO") == "DO_FORMATO"
    assert nome("X.mxf", [], material_package_name="DA_BIN") == "DA_BIN"


@tem_ffmpeg
def test_imagem_que_nao_decodifica_e_confirmada_pelo_SOM(tmp_path):
    """⭐⭐ **O BRAW casa com o que o Avid já processou — sem SDK nenhum.**

    MEDIDO em 2026-09-21 nos BRAW do editor: o `ffprobe` lê fps, nº de quadros e TC do
    contêiner (idênticos aos do OP-Atom), mas a essência de vídeo não decodifica e a
    conferência por pixel devolve `-1`. Pelo som do próprio clipe: **+1,000 em 0,4 s**, e
    o OP-Atom já tinha quadros, fala e vetores. Impostor (outro take da mesma câmera, no
    mesmo dia): **+0,033**.

    ⛔⛔ Só o `-1` ("não consegui comparar") cai para o som. Pixel que diz "é outro
    material" é uma RESPOSTA, e deixá-la ser resgatada pelo som aceitaria um rewrap de
    imagem diferente com o mesmo áudio.
    """
    original = tmp_path / "A009_03190845_C003.mov"
    _ffmpeg("-f", "lavfi", "-i", "testsrc2=size=160x90:rate=24000/1001",
            "-f", "lavfi", "-i", "anoisesrc=d=7:c=pink:seed=21", "-t", "3",
            "-c:v", "prores_ks", "-c:a", "pcm_s16le", str(original))
    conv = tmp_path / "op" / "A009_03190845_C003.mov"
    conv.parent.mkdir()
    _ffmpeg("-i", str(original), "-c:v", "mpeg2video", "-q:v", "4",
            "-c:a", "pcm_s16le", str(conv))
    m = _convertido(tmp_path, "A009_03190845_C003", conv, "video")

    alvo = dict(I.sondar(original))
    # ⚠️ A imagem NÃO pôde ser comparada (é o que um RAW de câmera faz), e não "não bate".
    monkey = I.mesma_imagem
    try:
        I.mesma_imagem = lambda *a, **k: I.NAO_COMPAREI
        medida, piso, fonte = I._conferir(original, alvo, [conv])
        assert fonte == "sonora" and medida >= piso

        # ⛔ Mas um desacordo de PIXEL é veredito, e o som não o resgata.
        I.mesma_imagem = lambda *a, **k: 0.10
        medida, piso, fonte = I._conferir(original, alvo, [conv])
        assert fonte == "visual" and medida < piso
    finally:
        I.mesma_imagem = monkey

    # E de ponta a ponta, com a imagem real decodificando, nada muda.
    assert I.achar(original).chave == m.chave
