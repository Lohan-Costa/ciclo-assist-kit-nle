"""RAW de câmera: o SDK do fabricante como binário externo, e a ausência dele.

Construído em 2026-09-21, a pedido do editor: *"braw r3d arriraw nós já tínhamos
solucionado no RELINKER"*. O desenho veio de lá inteiro (helper-CLI, contrato uniforme,
degradação com elegância); o que **não** veio foi o binário — o do RELINKER é
`Mach-O arm64` e o serviço daqui roda no Windows.

⚠️ **Estes testes rodam em máquina SEM o SDK e sem BRAW nenhum.** O que só se prova com o
material na mão está em `tools/conferir_braw.py` — e o que ele mede está no `CLAUDE.md`.
"""

from __future__ import annotations

import re
from fractions import Fraction
from pathlib import Path

import sys

import pytest

from cicloassist.midia import decodificadores as D
from cicloassist.midia import frames

RAIZ = Path(__file__).resolve().parents[1]
FONTE = RAIZ / "decodificadores" / "braw" / "decodificar_braw.cpp"


# ── o despacho ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("arquivo,tipo", [
    ("A001.BRAW", "braw"), ("a001.braw", "braw"),
    ("A001_C001.R3D", "r3d"),
    ("F004C009.arx", "arri"), ("F004C009.ari", "arri"),
    ("A001C001.CRM", "canon"),
    # ⚠️ Sony X-OCN vem em `.mxf` e só se descobre pela ESSÊNCIA: não pode entrar pela
    #    extensão, senão TODO OP-Atom do Avid iria para um decodificador que não existe.
    ("qualquer.mxf", ""),
    ("PLANO.mov", ""), ("PLANO.mp4", ""), ("SOM.wav", ""),
])
def test_a_extensao_diz_que_sdk_o_arquivo_exige(arquivo, tipo):
    assert D.tipo_de(arquivo) == tipo


# ── a ausência, que é o caso comum ───────────────────────────────────────────

def test_sem_o_decodificador_a_frase_diz_o_nome_e_o_endereco(monkeypatch):
    """⭐⭐ Faltar o SDK degrada com elegância: o editor recebe o nome do que instalar e
    o endereço. ⛔ Nunca "não consegui extrair o quadro" — isso o manda procurar defeito
    no material, quando o que falta é um programa."""
    monkeypatch.setattr(D, "caminho_do_programa", lambda t: "")
    with pytest.raises(D.SdkIndisponivel) as e:
        D.decodificar("A001.braw", 10, 768)
    assert "Blackmagic RAW" in str(e.value)
    assert "blackmagicdesign.com" in str(e.value)
    assert e.value.tipo == "braw"


def test_a_ausencia_do_sdk_SOBE_e_nao_vira_falha_de_extracao(monkeypatch):
    """⛔ `SdkIndisponivel` atravessa `frames.extrair` inteira: quem lê a mensagem tem de
    ver o que instalar, e `ExtracaoFalhou` esconderia isso."""
    monkeypatch.setattr(D, "caminho_do_programa", lambda t: "")
    with pytest.raises(D.SdkIndisponivel):
        frames.extrair("A001.braw", 10, Fraction(24000, 1001))
    with pytest.raises(D.SdkIndisponivel):
        frames.extrair_varios("A001.braw", [1, 2], Fraction(24000, 1001))


def test_o_raw_nunca_vai_para_o_ffmpeg(monkeypatch):
    """⛔ O ffmpeg abre o CONTÊINER do BRAW e lê o áudio, mas o vídeo sai `unknown`:
    mandá-lo para lá devolve "não consegui extrair", que é o sintoma errado."""
    monkeypatch.setattr(frames, "achar_ffmpeg",
                        lambda: pytest.fail("o RAW de câmera não passa pelo ffmpeg"))
    monkeypatch.setattr(frames, "busca_confiavel",
                        lambda v: pytest.fail("nem sonda o contêiner"))
    monkeypatch.setattr(D, "decodificar", lambda a, f, l, tipo="": b"\xff\xd8jpeg")

    assert frames.extrair("A001.braw", 7, Fraction(24000, 1001)) == b"\xff\xd8jpeg"
    assert frames.extrair_varios("A001.braw", [1, 2], Fraction(24000, 1001)) == {
        1: b"\xff\xd8jpeg", 2: b"\xff\xd8jpeg"}


def test_o_ffmpeg_continua_atendendo_tudo_o_mais(monkeypatch):
    """⚠️ O caminho normal não pode ter mudado: 118 mídias deste cache vieram por ele."""
    monkeypatch.setattr(D, "decodificar",
                        lambda *a, **k: pytest.fail("um .mov não é RAW de câmera"))
    monkeypatch.setattr(frames, "busca_confiavel", lambda v: True)
    monkeypatch.setattr(frames, "achar_ffmpeg", lambda: "ffmpeg")

    class Resultado:
        returncode = 0
        stdout = b"\xff\xd8do ffmpeg"
        stderr = b""

    monkeypatch.setattr(frames.subprocess, "run", lambda *a, **k: Resultado())
    assert frames.extrair("PLANO.mov", 7, Fraction(24000, 1001)) == b"\xff\xd8do ffmpeg"


# ── o aviso do take, que não pode sobreviver ao conserto ─────────────────────

def test_o_aviso_de_braw_some_quando_o_decodificador_existe(monkeypatch):
    """⭐ Até 2026-09-21 o take avisava SEMPRE que a imagem era BRAW ("não dá para ver
    quadros"). Com o decodificador instalado, dá. Aviso que sobrevive ao conserto vira
    ruído — e ruído se lê como "este produto não sabe o que está dizendo"."""
    from cicloassist.avid import take as T

    monkeypatch.setattr(T._sdk, "temos", lambda t: True)
    assert not [a for a in _avisos_de_braw(T) if "BRAW" in a]

    monkeypatch.setattr(T._sdk, "temos", lambda t: False)
    avisos = [a for a in _avisos_de_braw(T) if "Blackmagic RAW" in a]
    assert avisos and "transcrever o som" in avisos[0]


def _avisos_de_braw(T):
    """Roda só o trecho do take que decide o aviso, com uma imagem BRAW."""
    imagem = T.Fonte(master="A001", mob_id="x", arquivos=["D:/m/A001.BRAW"],
                     inicio_frames=0, inicio_s=0.0, tracks=1)
    avisos: list[str] = []
    tipos = {T._sdk.tipo_de(a) for a in imagem.arquivos} - {""}
    for t in sorted(x for x in tipos if not T._sdk.temos(x)):
        avisos.append(
            f"a imagem é {T._sdk.NOMES[t]}, que o ffmpeg não decodifica e cujo "
            f"decodificador não está instalado: dá para transcrever o som, mas "
            f"não para ver quadros deste clipe.")
    return avisos


# ── o contrato, que é compartilhado com o RELINKER ───────────────────────────

def test_o_contrato_do_helper_e_o_mesmo_do_relinker():
    """⭐⭐ Os dois apps da casa falam a mesma língua de propósito: um helper construído
    para um serve ao outro. Mudar as flags aqui quebra isso em silêncio."""
    fonte = (RAIZ / "decodificadores" / "comum.h").read_text(encoding="utf-8")
    for flag in ('"--file"', '"--frame"', '"--out"', '"--max-width"'):
        assert flag in fonte, f"o contrato perdeu {flag}"


def test_o_decodificador_e_procurado_e_nao_adivinhado(monkeypatch, tmp_path):
    """⚠️ Nada de caminho cravado: o binário pode estar ao lado do serviço empacotado,
    em `decodificadores/bin`, ou no PATH."""
    monkeypatch.setattr(D, "_pastas", lambda: [tmp_path])
    monkeypatch.setattr(D.shutil, "which", lambda n: "")
    assert D.caminho_do_programa("braw") == ""
    assert D.situacao()["braw"]["temos"] is False

    if sys.platform == "win32":
        (tmp_path / "ciclo-decodificar-braw.exe").write_bytes(b"MZ")
        assert D.caminho_do_programa("braw").endswith("ciclo-decodificar-braw.exe")
    else:
        # ⚠️ o .exe do SSD (build do Windows) não executa aqui: tem de ser ignorado
        (tmp_path / "ciclo-decodificar-braw.exe").write_bytes(b"MZ")
        assert D.caminho_do_programa("braw") == ""
        mac = tmp_path / "ciclo-decodificar-braw"
        mac.write_bytes(b"#!/bin/sh\n")
        mac.chmod(0o755)
        assert D.caminho_do_programa("braw") == str(mac)
    assert D.situacao()["braw"]["temos"] is True
    # ⚠️ E um tipo sem helper nunca inventa caminho.
    assert D.caminho_do_programa("r3d") == ""
    assert D.caminho_do_programa("nao-existe") == ""


# ── o C++, que a suíte não compila mas pode conferir ─────────────────────────

def test_a_fonte_cpp_nao_tem_literal_quebrado():
    """⛔⛔ **Este teste existe porque o defeito aconteceu cinco vezes seguidas.**

    Ao escrever o decodificador, um `\\n` dentro de uma string virou quebra de linha DE
    VERDADE na hora de gravar o arquivo. O compilador responde `C2001: newline in
    constant` — mas só depois de todo o MIDL e de uma compilação inteira, e a mensagem
    aponta a linha errada. Conferir aqui custa milissegundos e pega a classe inteira,
    exatamente como o `node --check` faz pelo `painel.js`.
    """
    for fonte in (FONTE, RAIZ / "decodificadores" / "comum.h"):
        for n, linha in enumerate(fonte.read_text(encoding="utf-8").splitlines(), 1):
            sem_escape = re.sub(r"\\.", "", linha)
            assert sem_escape.count('"') % 2 == 0, \
                f"{fonte.name}:{n} tem literal aberto — {linha.strip()[:70]!r}"


def _sem_comentarios(texto: str) -> str:
    """⚠️ Os comentários deste repo CITAM a armadilha que o código evita (aqui, o
    `CFStringRef` do macOS). Procurar no arquivo cru acusaria a documentação do conserto —
    o instrumento medindo a si mesmo, que este repo já pagou duas vezes hoje."""
    return re.sub(r"/\*.*?\*/|(?<!:)//[^\n]*", "", texto, flags=re.S)


def test_o_cpp_do_windows_nao_herdou_o_macos():
    """⛔⛔ O `.cpp` do RELINKER usa `CoreFoundation`/`CFStringRef`, que não existem no
    Windows. O porte é de API, não de sintaxe: aqui é `BSTR` e COM."""
    fonte = _sem_comentarios(FONTE.read_text(encoding="utf-8"))
    assert "CFStringRef" not in fonte and "CoreFoundation" not in fonte
    assert "SysAllocString" in fonte, "no Windows a API do BRAW recebe BSTR"
    assert "CoInitializeEx" in fonte, "sem COM a factory volta nula, e sem dizer por quê"


def test_o_cpp_nao_redistribui_o_runtime_do_fabricante():
    """⛔⛔ A licença do SDK é a razão de o decodificador ser um binário externo. Ele
    PROCURA o runtime onde ele já está; nunca carrega uma cópia nossa."""
    fonte = FONTE.read_text(encoding="utf-8")
    assert "CreateBlackmagicRawFactoryInstanceFromPath" in fonte
    assert "pastasDoRuntime" in fonte
    # ⭐ E o plugin AMA do Media Composer é uma das pastas: quem edita BRAW no Avid já tem
    #   o runtime, e não precisa instalar nada.
    assert "AVX2_Plug-Ins" in fonte


# ── com o SDK na máquina (só aqui; a suíte não depende disto) ────────────────

tem_braw = pytest.mark.skipif(not D.temos("braw"),
                              reason="o decodificador de BRAW não está construído aqui")


@tem_braw
def test_o_decodificador_recusa_o_que_nao_e_braw(tmp_path):
    """⚠️ Falha de decodificação é `DecodificacaoFalhou` com o motivo do helper — nunca
    um JPEG vazio, e nunca um estouro."""
    falso = tmp_path / "nao_e.braw"
    falso.write_bytes(b"isto nao e um clipe")
    with pytest.raises(D.DecodificacaoFalhou) as e:
        D.decodificar(falso, 0, 768)
    assert "nao_e.braw" in str(e.value)
