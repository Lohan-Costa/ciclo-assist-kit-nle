"""O aviso de versão nova (organograma aprovado pelo autor em 2026-10-05, https://claude.ai/artifact/1uRTv2MMSaFmJVn43jR4AS).

O motor pergunta ao GitHub qual é a versão mais recente do repositório público, ao subir pelo app e a cada
6 horas (decisão 2), e o editor vê o resultado onde já olha: a faixa na janela do app (que lê `versao.json`
na pasta de dados, como lê o `configuracoes.json` do convite), o bloco "Versão" nas Configurações e uma linha
no rodapé dos painéis (decisão 1). Nada se baixa sozinho: "Baixar" abre a página da versão no navegador.

Desenho do Órbita (`DRAMASYNC/src/lib/updateCheck.ts`): três estados — em dia, versão nova, "não consegui
conferir" (sem internet ou resposta estranha, que NÃO é "em dia") — e o link aceito só se for do NOSSO
repositório. Lá o `html_url` ia direto ao navegador: quem controlasse a resposta (conta comprometida, TLS
interceptado em rede de empresa) mandava o editor para onde quisesse, num botão "baixar atualização" dentro
do app em que ele confia. Aqui o endereço tem de ser EXATAMENTE a página de uma tag `vX.Y.Z` do repositório.

`releases/latest` ignora pré-lançamento: o release `vendor-ffmpeg-8.1.2` (marcado assim) nunca aparece como
versão do app. Só leitura: nada sobre a máquina ou o projeto vai ao GitHub. Sem login, o GitHub aceita 60
consultas por hora por endereço; 6 horas fica longe disso mesmo com várias máquinas na mesma rede.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
import urllib.request

import configuracoes
import plataforma

log = logging.getLogger("delapraca.versao")

REPO = "Lohan-Costa/delapraca"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
#: a única forma de link que se abre: a página de uma versão do repositório público
_URL = re.compile(r"https://github\.com/Lohan-Costa/delapraca/releases/tag/v\d{1,4}\.\d{1,4}\.\d{1,6}")
_VERSAO = re.compile(r"v?(\d{1,4})\.(\d{1,4})\.(\d{1,6})")

INTERVALO_S = 6 * 3600          # decisão 2
REPETIR_ERRO_S = 10 * 60        # "não consegui conferir": tenta de novo daqui a pouco
ARQUIVO = "versao.json"         # na pasta de DADOS: a janela do app lê (`lib.rs › versao_nova`)

_trava = threading.Lock()
_ultimo: dict | None = None


def numeros(v) -> tuple[int, int, int] | None:
    m = _VERSAO.fullmatch(v.strip()) if isinstance(v, str) else None
    return tuple(int(x) for x in m.groups()) if m else None


def mais_nova(remota: str, atual: str) -> bool:
    r, a = numeros(remota), numeros(atual)
    return bool(r and a and r > a)


def url_confiavel(url) -> bool:
    return isinstance(url, str) and _URL.fullmatch(url) is not None


def _consultar(atual: str, abrir=None) -> dict:
    pedido = urllib.request.Request(API, headers={
        "Accept": "application/vnd.github+json", "User-Agent": f"delapraca/{atual}"})
    try:
        with (abrir or urllib.request.urlopen)(pedido, timeout=5) as r:
            dado = json.loads(r.read(256_000))
    except (OSError, ValueError) as e:      # sem internet, DNS, TLS, HTTP 4xx/5xx, JSON quebrado
        log.info("versão nova: não consegui conferir (%s)", e)
        return {"estado": "erro"}
    tag = dado.get("tag_name") if isinstance(dado, dict) else None
    url = dado.get("html_url") if isinstance(dado, dict) else None
    if not numeros(tag) or not url_confiavel(url) or dado.get("draft") or dado.get("prerelease"):
        log.warning("versão nova: resposta inesperada do GitHub (tag %r, url %r)", tag, url)
        return {"estado": "erro"}
    if mais_nova(tag, atual):
        return {"estado": "nova", "versao": ".".join(map(str, numeros(tag))), "url": url}
    return {"estado": "em_dia"}


def _gravar(e: dict) -> None:
    """O que a janela do app precisa para a faixa. Acessório: falhar não derruba nada."""
    try:
        (plataforma.pasta_dados() / ARQUIVO).write_text(
            json.dumps({k: e.get(k) for k in ("estado", "versao", "url")}), encoding="utf-8")
    except OSError as erro:
        log.debug("não gravei %s: %s", ARQUIVO, erro)


def estado(forcar: bool = False, abrir=None) -> dict:
    """`{atual, avisar, estado: em_dia | nova | erro | desligado, versao?, url?}`. Consulta só se vencido."""
    global _ultimo
    atual = plataforma.versao()
    if not configuracoes.ler()["avisar_versao_nova"]:          # decisão 3: a caixa desliga
        _gravar({"estado": "desligado"})
        return {"atual": atual, "avisar": False, "estado": "desligado"}
    with _trava:
        e = _ultimo
        prazo = REPETIR_ERRO_S if e and e["estado"] == "erro" else INTERVALO_S
        if forcar or e is None or e.get("atual") != atual or time.time() - e["conferido"] >= prazo:
            e = {**_consultar(atual, abrir), "atual": atual, "conferido": time.time()}
            _ultimo = e
            _gravar(e)
            if e["estado"] == "nova":
                log.info("versão nova disponível: %s (instalada %s)", e["versao"], atual)
    return {"atual": atual, "avisar": True, **{k: v for k, v in e.items() if k in ("estado", "versao", "url")}}


def vigiar(parar: threading.Event) -> None:
    """Ao subir pelo app e a cada 6 horas (o erro tenta de novo em 10 min). Nunca levanta."""
    while True:
        try:
            e = estado()
            espera = REPETIR_ERRO_S if e["estado"] == "erro" else INTERVALO_S
        except Exception:  # noqa: BLE001 — o aviso é acessório
            log.debug("versão nova: a conferência falhou", exc_info=True)
            espera = REPETIR_ERRO_S
        if parar.wait(espera):
            return
