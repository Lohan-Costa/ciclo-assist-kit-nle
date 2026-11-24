"""O que o editor arrastou para dentro do chat — e a lista de quem pode ser lido.

## Por que existe

O editor pediu para **arrastar** em vez de digitar: a bin da cena, a sequência que quer
mexer, o roteiro que está no Explorer, uma foto do personagem. Duas origens, um gesto:

```
do Media Composer   →  MIME text/x.avid.mc-api-asset-list+json  →  MobID + espécie
do Explorer/Finder  →  text/uri-list                            →  caminho no disco
```

## ⛔⛔ E é AQUI que mora a permissão de ler o disco

Sem este módulo, dar ao modelo uma ferramenta "leia este arquivo" seria dar a ele **a
máquina inteira** — e o caminho viria de texto que o próprio modelo escreve, que é a
definição da superfície que o ADR 0005 trata.

⇒ **Só é legível o que o editor ARRASTOU.** O gesto dele é a autorização, e ela vale para
aquele arquivo, não para a pasta, não para o padrão, não para o disco.

⚠️ **Uma pasta arrastada não autoriza o conteúdo dela.** O drop de uma pasta entrega o
caminho da pasta; ler "qualquer coisa dentro" transformaria um gesto em permissão
recursiva. Quem quiser um arquivo, arrasta aquele arquivo.

⚠️ **A lista é da SESSÃO, não do disco.** Ela morre com o serviço de propósito: uma
autorização dada num dia de trabalho não deve valer na semana que vem porque ficou escrita
num JSON.
"""

from __future__ import annotations

import logging
import threading
import unicodedata
from pathlib import Path
from typing import Any

log = logging.getLogger("cicloassist.servico.arrastados")

#: Teto do que uma ferramenta de leitura entrega de uma vez. Um roteiro de longa tem ~120
#: KB; 2 MB é folga larga e ainda barra alguém arrastar um .mxf achando que é texto.
TETO_DE_TEXTO = 2 * 1024 * 1024

#: O que o produto sabe ler como TEXTO. ⚠️ Lista fechada, e o editor descobre na hora do
#: arrasto — não depois de esperar um turno.
#:
#: ⭐ `.docx` entrou em 2026-09-11, depois de um teste de campo em que o editor arrastou o
#: roteiro da cena e levou "não sei ler este formato". É o formato em que roteiro chega, e
#: ele não custa dependência: `.docx` é ZIP com XML dentro (ver `cicloassist/documento.py`).
#:
#: ⛔ `.pdf` continua fora: exigiria dependência nova. E `.doc` (Word 97) não é ZIP.
TEXTO = {".txt", ".md", ".fdx", ".docx", ".csv", ".srt", ".vtt", ".json", ".xml",
         ".edl", ".rtf"}

#: O que o modelo consegue OLHAR. São os formatos que o protocolo MCP carrega como imagem.
IMAGEM = {".jpg", ".jpeg", ".png", ".gif", ".webp"}

_trava = threading.Lock()
#: chave normalizada → o caminho como chegou (é ele que se abre e que se mostra).
_permitidos: dict[str, str] = {}


def _chave(caminho: str | Path) -> str:
    # ⚠️ No Windows `D:\X` e `d:/x` são o mesmo arquivo. Sem normalizar, o editor arrasta
    # e a ferramenta recusa o que ele acabou de autorizar.
    # ⚠️ E no macOS o nome chega do Finder DECOMPOSTO (NFD: `c` + cedilha), enquanto o
    # modelo reescreve o caminho composto (NFC) — o mesmo arquivo para o APFS, outra string
    # para um `set`. Medido 2026-09-14: autorizado em NFD, recusado em NFC.
    return unicodedata.normalize("NFC", str(Path(caminho).resolve())).lower()


def papel(sufixo: str, pasta: bool) -> str:
    """O que este arrasto É para uma ferramenta que o usa — ou "" se nenhuma usa.

    ⭐ O chip dizia "não sei ler este formato" para o `.prproj` e o `.mov`, e "é uma pasta" para a
    pasta das mídias (pilotado em 2026-10-29): exatamente o material que `conformar_no_resolve`
    leva ao Resolve. Quem decide o papel é a MESMA separação da ferramenta
    (`conformar.separar_os_arrastos`), para o chip não prometer uma coisa e ela fazer outra."""
    from ..mcp.ferramentas import conformar as _conformar  # tardio: o servico importa o MCP

    if pasta:
        return "mídias"
    if sufixo in _conformar.TIMELINES:
        return "projeto"
    if sufixo in _conformar.VIDEOS:
        return "referência"
    return ""


def autorizar(caminho: str | Path) -> dict[str, Any]:
    """Registra o que o editor arrastou. Devolve o que dá para fazer com aquilo."""
    p = Path(caminho)
    with _trava:
        _permitidos[_chave(p)] = str(p)
    sufixo = p.suffix.lower()

    # ⚠️⚠️ **`exists()` LEVANTA em arquivo protegido do Windows.** Medido:
    # `C:\Windows\System32\config\SAM` dá `PermissionError [WinError 5]` — não devolve
    # `False`. Sem este `try`, arrastar um arquivo de sistema derrubava a rota inteira com
    # 500, e o painel dizia "não consegui falar com o serviço" para um arquivo que a
    # resposta certa era "não sei ler isso".
    try:
        existe = p.exists()
        tamanho = p.stat().st_size if existe and p.is_file() else 0
        pasta = existe and p.is_dir()
    except OSError:
        existe, tamanho, pasta = False, 0, False
    log.info("arrastado: %s (%s, %d bytes)", p.name, sufixo or "sem extensão", tamanho)
    return {
        "papel": papel(sufixo, pasta) if existe else "",
        "caminho": str(p),
        "nome": p.name,
        "existe": existe,
        "pasta": pasta,
        "bytes": tamanho,
        "legivel": sufixo in TEXTO,
        "visivel": sufixo in IMAGEM,
    }


#: Teto de um anexo mandado pelo CONTEÚDO. Roteiro de longa tem ~120 KB e foto de set
#: alguns MB; 25 MB é folga larga e ainda barra alguém soltar um `.mxf` no chat.
TETO_DE_ANEXO = 25 * 1024 * 1024


def pasta_dos_anexos() -> Path:
    from . import config as _config
    return _config.pasta() / "anexos"


def guardar_conteudo(nome: str, dados: bytes) -> dict[str, Any]:
    """Guarda um anexo que chegou pelo CONTEÚDO e o autoriza. Devolve o mesmo que `autorizar`.

    ⛔⛔ **Existe porque o CEP não entrega caminho.** MEDIDO em 2026-09-17, no Premiere 23.2:
    arrastar um arquivo do Explorer para o painel CEP não traz `text/uri-list` (o que o
    QtWebEngine do Media Composer traz) e o `File` do Chromium não tem caminho sem Node — que
    este painel não liga de propósito. O editor arrastava o roteiro e lia "não veio nada nesse
    arrasto".

    ⭐ O que chega é o CONTEÚDO, e ele basta: o produto lê roteiro e olha imagem, não precisa
    do lugar. A cópia nasce na pasta de dados do produto e é ela que fica autorizada — o
    gesto continua autorizando UM arquivo, não a pasta de onde ele veio.

    ⚠️ Nome saneado: o que vem do drop é texto de fora. Sem isso, `..\\..\\x` escreveria
    onde quisesse.
    """
    from ..midia import cache as _cache

    if len(dados) > TETO_DE_ANEXO:
        raise ValueError(f"esse arquivo tem {len(dados) // (1024 * 1024)} MB; o teto do "
                         f"anexo é {TETO_DE_ANEXO // (1024 * 1024)} MB")
    # ⚠️ A extensão vem do nome ORIGINAL, e só o miolo é saneado. O saneador corta em 40
    #    caracteres, e um roteiro de nome comprido perdia o `.txt` no corte — voltando como
    #    "não sei ler arquivo sem extensão", que manda o editor procurar o problema no
    #    formato certo do arquivo que ele arrastou.
    bruto = Path(str(nome)).name
    sufixo = Path(bruto).suffix.lower()
    limpo = (_cache._limpar(Path(bruto).stem) or "anexo") + sufixo
    if sufixo not in TEXTO and sufixo not in IMAGEM:
        # ⚠️ Recusa ANTES de gravar: guardar o que ninguém vai ler é lixo na pasta do editor.
        raise ValueError(f"não sei ler {sufixo or 'arquivo sem extensão'}. Dá para ler "
                         f"{', '.join(sorted(TEXTO))} e olhar {', '.join(sorted(IMAGEM))}")
    destino = pasta_dos_anexos()
    destino.mkdir(parents=True, exist_ok=True)
    caminho = destino / limpo
    if caminho.exists() and caminho.read_bytes() != dados:
        # Mesmo nome, outro conteúdo: os dois precisam existir (duas versões do roteiro).
        caminho = destino / f"{Path(limpo).stem}-{len(dados)}{Path(limpo).suffix}"
    _cache.escrever_atomico(caminho, dados)
    log.info("anexo pelo conteúdo: %s (%d bytes)", caminho.name, len(dados))
    return autorizar(caminho)


def autorizado(caminho: str | Path) -> bool:
    with _trava:
        return _chave(caminho) in _permitidos


def arquivos() -> list[str]:
    """Os caminhos arrastados nesta sessão, como chegaram.

    ⭐ Para quem precisa do roteiro sem depender de o modelo lembrar de passá-lo:
    `separar_falas` confere a cobertura contra ele (2026-09-15).
    """
    with _trava:
        return list(_permitidos.values())


#: Os NOMES dos clipes do NLE arrastados na última pergunta que trouxe algum.
#: ⭐ É o escopo que o editor escolheu: quem arrasta 3 takes da C07 está dizendo "estes", e
#:    `separar_falas` confere a cobertura contra eles em vez da bin inteira (2026-10-22, o
#:    caso "1 fala, 1 clipe" do Qwen: sem isto ele teria de declarar os outros 9 de fora).
#: ⚠️ Só é TROCADO por uma pergunta que traga clipes: "pode enviar", sem anexo, continua
#:    falando dos mesmos.
_clipes: list[str] = []


def lembrar_clipes(nomes: list[str]) -> None:
    nomes = [str(n).strip() for n in nomes if str(n or "").strip()]
    if nomes:
        with _trava:
            _clipes[:] = nomes


def clipes() -> list[str]:
    with _trava:
        return list(_clipes)


def esquecer_tudo() -> None:
    with _trava:
        _permitidos.clear()
        _clipes.clear()


def recusa(caminho: str | Path) -> str:
    """A frase que o modelo lê quando pede um arquivo que não foi arrastado.

    ⭐ Ela diz o que FAZER. Um "acesso negado" seco faria o modelo tentar outro caminho,
    outra grafia, outra pasta — e cada tentativa é um turno da assinatura do editor gasto
    numa porta que não vai abrir.
    """
    return (
        f"Não tenho permissão para abrir {Path(caminho).name}. Só consigo ler arquivos "
        f"que o editor arrastou para o chat — peça a ele para arrastar este, se for o "
        f"caso. Não tente outros caminhos."
    )
