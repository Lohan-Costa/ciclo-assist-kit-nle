"""As defesas do documento de ameaças, travadas em teste.

⭐ Um documento de ameaças que descreve proteções sem testá-las é prosa. Cada caso aqui
corresponde a uma linha de `docs/ameacas.md`, e alguns foram achados escrevendo-o.
"""

from __future__ import annotations

import pytest

from cicloassist.mcp.ferramentas.corte import _nome_de_arquivo
from cicloassist.midia.cache import ChaveInvalida, de_umid
from cicloassist.plano import esquema as _plano
from cicloassist.servico.http import Pedido, cors_para, veio_do_painel


def pedido(**cabecalhos):
    return Pedido("POST", "/conversar",
                  {k.lower().replace("_", "-"): v for k, v in cabecalhos.items()})


# ── §3 · uma página web chamando o serviço ───────────────────────────────────

def test_site_qualquer_e_recusado():
    assert not veio_do_painel(pedido(sec_fetch_site="cross-site",
                                     origin="https://mau.example"))


def test_curl_sem_cabecalho_e_recusado():
    assert not veio_do_painel(pedido())


def test_cors_nunca_e_curinga():
    """⛔ Um `*` abriria o serviço para qualquer aba aberta no navegador do editor."""
    for c in ({}, {"origin": "https://mau.example"}, {"sec_fetch_site": "same-origin"}):
        assert "*" not in str(cors_para(pedido(**c)))


def test_o_segredo_do_mcp_tem_entropia():
    """Ele é o único porteiro da rota que o modelo usa para agir."""
    from cicloassist.servico.http import SEGREDO_DO_MCP

    assert len(SEGREDO_DO_MCP) >= 24


# ── §4 · arquivo de projeto hostil ───────────────────────────────────────────

@pytest.mark.parametrize("hostil", [
    "urn:smpte:umid:../../etc/passwd",
    "..",
    "/" + "a" * 63,
    "0" * 63,      # curto demais
    "0" * 65,      # longo demais
    "z" * 64,      # não é hex
    "",
])
def test_mobid_hostil_nao_vira_caminho(hostil):
    """⛔ A chave vira NOME DE DIRETÓRIO, e o `.avb` traz strings que não escolhemos."""
    with pytest.raises(ChaveInvalida):
        de_umid(hostil)


@pytest.mark.parametrize("bruto", [
    "..", "../../etc/passwd", "..\\..\\windows", "  ...  ", "C07/CORTE", "",
])
def test_nome_de_arquivo_nunca_tem_separador_nem_e_vazio(bruto):
    saida = _nome_de_arquivo(bruto)
    assert saida
    assert "/" not in saida and "\\" not in saida
    assert saida.strip(" .")          # nunca só pontos/espaços


@pytest.mark.parametrize("reservado", ["CON", "NUL", "PRN", "AUX", "COM1", "LPT9", "con",
                                       "Con.avb"])
def test_nome_de_dispositivo_do_windows_e_desviado(reservado):
    """⭐ Achado NESTA auditoria. `CON`, `NUL` e companhia não são arquivos: escrever em
    `CON.avb` vai para o console e em `NUL.avb` some — **sem erro na escrita**. O nome vem
    do modelo, que pode propor "CON" para uma cena de conversa."""
    assert _nome_de_arquivo(reservado).split(".")[0].upper() not in (
        "CON", "NUL", "PRN", "AUX", "COM1", "LPT9"
    )


@pytest.mark.parametrize("inocente", ["CONVERSA", "CONTATO", "AUXILIAR", "COMECO"])
def test_nome_que_so_comeca_com_reservado_passa_intacto(inocente):
    """A checagem é do NOME, não do prefixo — senão metade das palavras portuguesas que
    começam com "con" viraria arquivo com underline na frente."""
    assert _nome_de_arquivo(inocente) == inocente


def test_plano_recusa_nome_com_caminho():
    for nome in ("../fora", "C07\\..", "a/b"):
        with pytest.raises(_plano.PlanoInvalido, match="caractere proibido"):
            _plano.validar({"bin": "x.avb", "nome": nome, "cortes": [
                {"take": "t", "duracao_frames": 10, "confianca": "inferido",
                 "fonte": "visual", "porque": "x"}]})


# ── §3 · a página não escolhe caminho, escolhe da LISTA ──────────────────────

def test_varrer_recusa_pasta_que_nao_esta_na_lista():
    """⛔⛔ O corpo de um POST vem da tela. Uma rota que varresse o caminho que recebesse
    seria "leia esta máquina inteira" dita por uma frase — e a varredura devolve NOMES de
    arquivo, então ela é leitura de disco com resposta.

    ⭐ A lista tem duas origens, e as duas são gestos: as `Avid MediaFiles` que existem
    nos volumes, e as que o editor apontou no seletor de pastas do Windows.
    """
    from cicloassist.servico.http import Pedido as P
    from cicloassist.servico.rotas import rota_varrer

    corpo = b'{"pasta": "C:\\\\Users\\\\usuario\\\\Documents"}'
    resposta = rota_varrer(P("POST", "/vetores/varrer", {}, corpo))
    assert resposta.status == 400
    assert b"n\\u00e3o conhe\\u00e7o" in resposta.corpo or "não conheço" in \
        resposta.corpo.decode("utf-8")


def test_varrer_recusa_caminho_vazio():
    from cicloassist.servico.http import Pedido as P
    from cicloassist.servico.rotas import rota_varrer

    assert rota_varrer(P("POST", "/vetores/varrer", {}, b"{}")).status == 400


# ── §2 · a contenção do subprocesso ──────────────────────────────────────────

def test_nenhuma_ferramenta_de_escrita_entra_na_allowlist():
    """⛔ A allowlist é o que dispensa o portão. Uma ferramenta de escrita ali dentro
    escreveria no projeto do editor sem ele ver."""
    from cicloassist.mcp import ferramentas  # noqa: F401
    from cicloassist.mcp.registro import FERRAMENTAS, somente_leitura

    livres = {n.removeprefix("mcp__ciclo__") for n in somente_leitura()}
    escritoras = {f.nome for f in FERRAMENTAS.values() if f.escreve}
    assert not (livres & escritoras), f"escrita sem portão: {livres & escritoras}"
    assert escritoras, "se não há ferramenta de escrita, este teste virou decorativo"


def test_a_persona_declara_que_nome_de_arquivo_e_dado():
    """Camada 5 do §2 — a mais fraca, e ainda assim a que dá ao modelo o enquadramento
    certo para o que chega pelas ferramentas."""
    from cicloassist.motor.claude import PERSONA

    baixa = PERSONA.lower()
    assert "dados" in baixa and "instruções" in baixa


# ── cadeia de suprimentos: os arquivos que o pip lê ──────────────────────────

@pytest.mark.parametrize("nome", ["requirements.txt", "requirements.lock"])
def test_arquivo_de_requisitos_e_ascii_puro(nome):
    """⚠️⚠️ **MEDIDO em 2026-09-10, e o modo de falha é total.** O pip decodifica
    requirements com a CODEPAGE DO SISTEMA quando não há BOM — não com UTF-8. Um símbolo
    de aviso carrega o byte `0x8F`, **indefinido em cp1252**: o pip levanta
    `UnicodeDecodeError` e **não instala nada**.

    A versão anterior do `requirements.txt` deste projeto era ilegível em cp1252 e só
    funcionava porque `dev.ps1` e `instalar.ps1` setam `PYTHONUTF8=1`. Quem digitasse
    `pip install -r requirements.txt` à mão não instalava nada, com um erro que fala de
    codec e não de dependência.

    ⚠️ Acento sozinho sobrevive (vira mojibake em cp1252 em vez de erro), então um arquivo
    acentuado e sem emoji funciona **por sorte**. Aqui não se conta com sorte.
    """
    from pathlib import Path

    bruto = (Path(__file__).resolve().parent.parent / nome).read_bytes()
    fora = [(i, b) for i, b in enumerate(bruto) if b > 127]
    assert not fora, (
        f"{nome} tem byte não-ASCII em {fora[0][0]} — o pip pode não conseguir lê-lo "
        f"no Windows. Prosa acentuada vai no CLAUDE.md, não aqui."
    )


def test_o_lock_fixa_versoes_exatas():
    """Um lock com `>=` é um arquivo que MENTE sobre ser exato."""
    from pathlib import Path

    lock = (Path(__file__).resolve().parent.parent / "requirements.lock").read_text("ascii")
    # As linhas de `--hash` são continuação do pacote anterior, não requisitos.
    requisitos = [
        l.strip().rstrip("\\").strip() for l in lock.splitlines()
        if l.strip() and not l.strip().startswith(("#", "--hash="))
    ]
    assert requisitos, "o lock está vazio"
    soltos = [l for l in requisitos if "==" not in l]
    assert not soltos, f"linhas sem versão fixa no lock: {soltos}"


def test_todo_pacote_do_lock_tem_hash():
    """⛔ **Hash PARCIAL é pior que hash nenhum.** O pip entra em modo de verificação
    assim que vê um `--hash`, e aí RECUSA tudo que não tem — a instalação falha inteira.

    Este teste existe porque a perda de hashes seria silenciosa do outro lado: um lock
    regerado com `--sem-hash` continua instalando, só que **sem verificar nada**. Falhar
    aqui é melhor que descobrir na máquina do editor.
    """
    from pathlib import Path

    lock = (Path(__file__).resolve().parent.parent / "requirements.lock").read_text("ascii")
    pacote = None
    com_hash = set()
    pacotes = set()
    for linha in lock.splitlines():
        crua = linha.strip()
        if not crua or crua.startswith("#"):
            continue
        if crua.startswith("--hash="):
            assert pacote, f"hash solto, sem pacote antes: {crua[:40]}"
            com_hash.add(pacote)
            continue
        pacote = crua.split("==")[0].strip()
        pacotes.add(pacote)
    sem = pacotes - com_hash
    assert not sem, f"pacotes sem hash no lock: {sorted(sem)}"


def test_o_hash_e_sha256_de_64_digitos():
    """Um hash truncado ou de outro algoritmo não é recusado pelo pip com mensagem
    clara — ele vira "não bate", que manda procurar adulteração onde há erro de geração."""
    import re
    from pathlib import Path

    lock = (Path(__file__).resolve().parent.parent / "requirements.lock").read_text("ascii")
    hashes = re.findall(r"--hash=(\S+)", lock)
    assert hashes, "o lock não tem hash nenhum"
    tortos = [h for h in hashes if not re.fullmatch(r"sha256:[0-9a-f]{64}", h)]
    assert not tortos, f"hash fora do formato: {tortos[:3]}"


def test_o_lock_cobre_o_que_o_requirements_pede():
    """O lock é gerado do ambiente; se um pacote pedido não estiver nele, alguém gerou o
    lock num venv que não tinha tudo instalado — e a instalação do editor sairia sem."""
    from pathlib import Path

    raiz = Path(__file__).resolve().parent.parent
    pedidos = set()
    for linha in (raiz / "requirements.txt").read_text("ascii").splitlines():
        linha = linha.split("#")[0].strip()
        if linha:
            pedidos.add(linha.split(">=")[0].split("==")[0].strip().lower())
    travados = set()
    for linha in (raiz / "requirements.lock").read_text("ascii").splitlines():
        if linha.strip() and not linha.startswith("#"):
            travados.add(linha.split("==")[0].strip().lower().replace("_", "-"))
    faltando = {p for p in pedidos if p.replace("_", "-") not in travados}
    assert not faltando, f"pedidos no requirements.txt e ausentes do lock: {faltando}"
