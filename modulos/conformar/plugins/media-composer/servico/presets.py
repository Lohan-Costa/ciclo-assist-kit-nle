"""O preset de export do plugin: garantir que o AAF sai como AAF.

## O problema, e por que não pode ficar na mão do editor

`GetListOfExportSettings` devolve **nomes**, e nome não diz formato. Disparar um export
com o preset errado não dá erro: o MC começa a **renderizar a timeline inteira** naquele
formato. Medido em 2026-08-10 — um WAVE de 26 minutos, com diálogo de progresso, que o
editor teve de cancelar na mão. (A causa foi mundana: um preset duplicado do `wav` e
renomeado para `AAF` sem reconfigurar.)

## ⭐ O campo que decide: `_EXPORTFORMAT`

Descoberto comparando um preset de AAF **correto** com o de WAV. É um atributo nomeado,
não um `AvProp` de primeiro nível — está sob `OMFI:ATTB:Name` = `_EXPORTFORMAT`:

| `_EXPORTFORMAT` | formato          |
|---|---|
| 8  | sequência de imagens |
| 9  | WAV                  |
| **20** | **AAF**          |
| 23 | XDCAM                |
| 24 | QuickTime / MP4      |
| 25 | Pro Tools            |

Medido em MC 25.12. É isto que torna a verificação **exata** em vez de heurística: dá
para saber o formato de qualquer preset sem exportar nada.

## Onde os presets moram, e quando o arquivo é escrito

`<Avid Users>/<usuário>/<usuário> Settings.xml` (5 MB), como blocos
`<AvClass id="EXst">` com `kind="Export"`. **Não** ficam no `Settings.xml` do projeto
nem em `Avid Templates`. A raiz `Avid Users` muda de sistema operacional — medida nos
dois, ela vive em `plataforma.raiz_settings_avid()`:

| SO | raiz |
|---|---|
| macOS | `/Users/Shared/AvidMediaComposer/Avid Users` |
| Windows | `C:\\Users\\Public\\Documents\\Avid Media Composer\\Avid Users` |

Nos dois é uma pasta **compartilhada entre usuários do sistema**, não do perfil — o
Avid trata "usuário" como conceito dele, não do SO.

⚠️⚠️ **O Media Composer só grava esse arquivo ao SAIR** (ou ao trocar de projeto), e o
reescreve inteiro a partir da memória. Duas consequências:

1. Um preset recém-criado **não está no disco** enquanto o MC estiver aberto — a API o
   lista, o arquivo não.
2. **Escrever no arquivo com o MC aberto é jogar fora**: ele sobrescreve tudo ao sair.
   Por isso `instalar()` recusa quando o MC está de pé.
"""

from __future__ import annotations

import logging
import re
import shutil
import time
from pathlib import Path

import plataforma

log = logging.getLogger("delapraca.presets")

# O nome do nosso preset. Fixo, e não escolhido pelo editor: o formato do export é
# requisito do plugin, não preferência.
NOME_PRESET = "AAF-DLPC"

# `_EXPORTFORMAT` de um AAF. Ver tabela na docstring.
FORMATO_AAF = "20"

_NOME = re.compile(r'name="name" type="string">([^<]*)')
_RECURSO = Path(__file__).resolve().parent / "recursos" / "preset_aaf.xml"

# Abertura/fechamento de `AvClass`, para contar profundidade. O grupo 1 distingue a
# forma vazia (`<AvClass id="SETG"/>`), que abre e fecha na mesma tag.
_TAG_AVCLASS = re.compile(r"<AvClass\b[^>]*?(/?)>|</AvClass>")


def blocos_de_export(texto: str) -> list[str]:
    """Todo bloco `<AvClass id="EXst">…</AvClass>` **completo** do `Settings.xml`.

    ⚠️⚠️ **Conta profundidade; não use `.*?`.** `AvClass` ANINHA — cada preset de export
    tem um `AvClass` filho dentro de um `AvProp`. Um não-guloso
    (`r'<AvClass id="EXst">.*?</AvClass>'`, que era o que estava aqui) para no fechamento
    do FILHO e devolve o bloco **truncado**.

    **Medido em 2026-08-16** contra o `<usuário> Settings.xml` real (6,7 MB, MC 25.6 no
    Windows): os três presets de export perdiam **exatamente 31 caracteres** cada — a
    cauda `'\\n      </AvProp>\\n    </AvClass>'`, só fechamento, nenhum conteúdo.

    **O sintoma, e por que ele não aparecia:** o recurso embarcado
    (`recursos/preset_aaf.xml`) tinha sido extraído com essa regex e portanto não era XML
    bem-formado (2 `AvClass` abertos, 1 fechado). `instalar()` o inseria no `Settings.xml`
    do editor e o deixava **inválido** — 1935 aberturas contra 1934 fechamentos — enquanto
    devolvia `{'ok': True}`. E `diagnostico()` respondia `situacao: 'ok'` logo depois,
    porque truncava os DOIS lados com a mesma regex e a comparação batia: **o defeito
    escondia a si mesmo**.
    """
    fora: list[str] = []
    for m in re.finditer(r'<AvClass id="EXst">', texto):
        profundidade = 0
        for t in _TAG_AVCLASS.finditer(texto, m.start()):
            if t.group(0).startswith("</"):
                profundidade -= 1
            elif t.group(1) != "/":
                profundidade += 1
            if profundidade == 0:
                fora.append(texto[m.start():t.end()])
                break
    return fora


def caminho_das_settings(usuario: str | None = None) -> Path | None:
    """O `<usuário> Settings.xml` do Media Composer, se existir.

    A pasta `Avid Users` está em lugares diferentes nos dois SOs (ver
    `plataforma.raiz_settings_avid`), mas o layout de dentro é o mesmo: uma pasta por
    usuário do Avid, com um XML homônimo. Sem `usuario`, ganha o **mais recente** —
    uma máquina pode ter vários perfis do Avid, e o que o editor usa é o que ele
    mexeu por último.
    """
    raiz = plataforma.raiz_settings_avid()
    if raiz is None:
        return None
    pastas = [raiz / usuario] if usuario else sorted(
        (p for p in raiz.iterdir() if p.is_dir()),
        key=lambda p: p.stat().st_mtime, reverse=True)
    for pasta in pastas:
        alvo = pasta / f"{pasta.name} Settings.xml"
        if alvo.is_file():
            return alvo
    return None


def _nome_do(bloco: str) -> str:
    m = _NOME.search(bloco)
    return m.group(1) if m else ""


def formato_de(bloco: str) -> str | None:
    """O `_EXPORTFORMAT` de um bloco de preset."""
    m = re.search(
        r'name="OMFI:ATTB:Name" type="string">_EXPORTFORMAT</AvProp>\s*'
        r'<AvProp id="ATTR" name="OMFI:ATTB:IntAttribute"[^>]*>([^<]*)', bloco)
    return m.group(1) if m else None


def preset_embarcado() -> str | None:
    """O bloco de referência que vem com o plugin."""
    try:
        return _RECURSO.read_text(encoding="utf-8")
    except OSError as e:
        log.error("recurso do preset não encontrado (%s): %s", _RECURSO, e)
        return None


def presets_de_export(caminho: Path | None = None) -> dict[str, str]:
    """`{nome do preset → bloco}` lidos do arquivo de settings."""
    arquivo = caminho or caminho_das_settings()
    if not arquivo or not arquivo.is_file():
        return {}
    try:
        # 5 MB; ler inteiro é mais rápido que qualquer parser aqui.
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        log.debug("não consegui ler %s: %s", arquivo, e)
        return {}
    return {n: b for b in blocos_de_export(texto) if (n := _nome_do(b))}


def diagnostico(caminho: Path | None = None) -> dict:
    """O estado do nosso preset no disco: o que a UI e o instalador precisam saber.

    `situacao` ∈ ausente | divergente | ok | sem_settings
    """
    arquivo = caminho or caminho_das_settings()
    if not arquivo:
        return {"situacao": "sem_settings", "settings": None}

    todos = presets_de_export(arquivo)
    nosso = todos.get(NOME_PRESET)
    embarcado = preset_embarcado()

    base = {
        "settings": str(arquivo),
        "preset": NOME_PRESET,
        "formato_esperado": FORMATO_AAF,
        "mc_aberto": media_composer_aberto(),
    }
    if nosso is None:
        return {**base, "situacao": "ausente"}

    fmt = formato_de(nosso)
    igual = embarcado is not None and _comparavel(nosso) == _comparavel(embarcado)
    if igual and fmt == FORMATO_AAF:
        return {**base, "situacao": "ok", "formato": fmt}
    return {**base, "situacao": "divergente", "formato": fmt,
            "motivo": ("o preset no Media Composer não exporta AAF"
                       if fmt != FORMATO_AAF
                       else "o preset no Media Composer difere do que o plugin espera")}


def _comparavel(bloco: str) -> str:
    """O bloco sem espaçamento, para comparar conteúdo e não formatação. O VOLUME de cópia de mídia (vazio de sentido
    num AAF ligado à mídia) não conta: o embarcado trocou o nome de um volume de produção por "Macintosh HD" em
    2026-10-28 (banco, B104) e quem já tinha o preset instalado não pode virar "divergente" por isso."""
    bloco = re.sub(r"(ES_EXPORT(?:AUDIO|VIDEO)VOLUME</AvProp>\s*<AvProp[^>]*StringAttribute[^>]*>)[^<]*", r"\1", bloco)
    return re.sub(r"\s+", " ", bloco).strip()


def media_composer_aberto() -> bool:
    """O MC está de pé? (`instalar` recusa quando sim — ver a docstring do módulo.)"""
    try:
        return plataforma.media_composer_aberto()
    except Exception:  # noqa: BLE001
        # ⚠️ Na dúvida, dizer que NÃO está aberto seria liberar a escrita das settings
        # — e o MC descartaria tudo ao sair, em silêncio. Errar para o lado seguro.
        log.debug("não consegui enumerar processos", exc_info=True)
        return True


def instalar(caminho: Path | None = None, *, forcar: bool = False) -> dict:
    """Põe o nosso preset no arquivo de settings, sobrescrevendo o que houver.

    ⚠️ **Recusa com o Media Composer aberto.** Ele reescreve o arquivo inteiro ao sair,
    a partir da memória: qualquer coisa escrita agora seria descartada sem aviso — e o
    editor ficaria achando que instalou.

    Faz cópia de segurança antes de tocar em qualquer coisa. O arquivo tem **todas** as
    preferências do editor; estragá-lo é um prejuízo real, não um contratempo.
    """
    arquivo = caminho or caminho_das_settings()
    if not arquivo:
        return {"ok": False, "erro": "não achei o Settings.xml do Media Composer"}
    if media_composer_aberto() and not forcar:
        return {"ok": False, "erro":
                "feche o Media Composer antes de instalar o preset — ele reescreve as "
                "settings ao sair, e desfaria o que fizermos agora."}

    embarcado = preset_embarcado()
    if not embarcado:
        return {"ok": False, "erro": "o preset embarcado não veio no pacote"}
    if formato_de(embarcado) != FORMATO_AAF:
        # Guarda contra um recurso trocado por engano: instalar um preset que não
        # exporta AAF seria reproduzir exatamente o problema que ele existe para evitar.
        return {"ok": False, "erro": "o preset embarcado não é de AAF — pacote inválido"}

    try:
        texto = arquivo.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"ok": False, "erro": f"não consegui ler as settings: {e}"}

    copia = arquivo.with_suffix(f".xml.delapraca-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    try:
        shutil.copy2(arquivo, copia)
    except OSError as e:
        return {"ok": False, "erro": f"não consegui fazer a cópia de segurança: {e}"}

    antigos = [b for b in blocos_de_export(texto) if _nome_do(b) == NOME_PRESET]
    if antigos:
        novo_texto = texto.replace(antigos[0], embarcado, 1)
        for extra in antigos[1:]:            # duplicatas, se houver
            novo_texto = novo_texto.replace(extra, "", 1)
        acao = "substituído"
    else:
        # Entra ao lado dos outros presets de export, não em lugar arbitrário.
        outros = [b for b in blocos_de_export(texto) if b != embarcado]
        if not outros:
            return {"ok": False, "erro": "não achei onde inserir — nenhum preset de "
                                         "export no arquivo"}
        novo_texto = texto.replace(outros[-1], outros[-1] + "\n    " + embarcado, 1)
        acao = "inserido"

    try:
        arquivo.write_text(novo_texto, encoding="utf-8")
    except OSError as e:
        return {"ok": False, "erro": f"não consegui escrever as settings: {e}"}

    log.info("preset %r %s em %s (backup: %s)", NOME_PRESET, acao, arquivo, copia.name)
    return {"ok": True, "acao": acao, "backup": str(copia), "preset": NOME_PRESET}
