"""O que o editor escolheu, e que precisa sobreviver ao fechamento do Media Composer.

Hoje é uma coisa só — **onde o cache de mídia mora** —, e o arquivo existe para que isso
não vire variável de ambiente na mão do editor. Um assistente de edição que exige
`setx CICLOASSIST_CACHE` não é um produto instalável.

```
%LOCALAPPDATA%\\CicloAssist\\config.json
```

## A ordem de precedência, e por que ela é essa

```
CICLOASSIST_CACHE  →  config.json  →  o padrão ao lado do log
  (ambiente)           (o editor)       (ninguém escolheu)
```

⭐ **O ambiente ganha do editor de propósito.** É o que o desenvolvimento e os testes usam
para não encostar no cache real de quem está usando a máquina — e quem exporta a variável
sabe o que está fazendo. O editor mexe pelo painel, e o painel escreve aqui.

⚠️ **Config ilegível vira config vazia, nunca exceção.** Mesma regra do cache e das
pendências: um JSON truncado por queda de energia não pode impedir o serviço de subir —
o preço de ignorá-lo é o editor reescolher a pasta, e o de estourar é o painel em branco.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("cicloassist.servico.config")

_trava = threading.Lock()

#: As chaves que o painel pode gravar. ⛔ Lista fechada: o corpo do POST vem da página, e
#: aceitar chave desconhecida transformaria a configuração num saco de coisas que ninguém
#: lê — e num lugar por onde escrever o que não foi previsto.
#: ⭐ `alinhador`: a pasta do modelo do alinhador por palavra (Mac), quando ele mora fora da pasta de dados — no SSD de
#: trabalho, porque o disco interno do Mac encheu em 07/11 (autor, 2026-11-11). Ver `midia/alinhamento.pasta_do_modelo`.
CHAVES = ("cache", "modelo", "auto", "ollama", "esforco", "alinhador")

#: Os modelos que o painel oferece, do mais capaz ao mais rápido.
#:
#: ⚠️ **Lista fechada, e não o que o CLI aceitar.** O valor vai para `--model` de um
#: subprocesso: aceitar texto livre da página seria deixar a página escolher um argumento
#: de linha de comando. E um id errado só falha quando o editor já perguntou alguma coisa.
#:
#: ⭐ O rótulo diz PARA QUE serve, não o benchmark. Quem edita escolhe por "preciso que
#: ele pense" ou "preciso que seja rápido" — não por nome de família de modelo.
#: ⛔ **Sem "modelo padrão" na lista.** Ele existia como primeira opção e era ruído: o
#: editor não tem como saber o que o padrão da conta dele é, e a barra passava a mostrar
#: um rótulo que não diz quem está respondendo. Três nomes, e um deles está sempre em uso.
MODELOS = (
    {"id": "claude-opus-5", "nome": "Opus 5",
     "para": "o mais capaz — decisões de montagem, cenas difíceis"},
    {"id": "claude-sonnet-5-5", "nome": "Sonnet 5.5",
     "para": "equilibrado — o dia a dia"},
    {"id": "claude-haiku-4-5-20251001", "nome": "Haiku 4.5",
     "para": "o mais rápido e barato — listar, procurar, conferir"},
)

#: Com o que o produto trabalha quando o editor ainda não escolheu.
#:
#: ⭐ Sonnet: é o que dá conta de uma montagem sem gastar a janela de cinco horas dele numa
#: tarde. Quem quiser mais cabeça ou mais velocidade troca na barra, e a troca vale já no
#: turno seguinte.
PADRAO = "claude-sonnet-5-5"

#: O prefixo de um modelo que responde do Mac (Ollama), e não da assinatura.
LOCAL = "ollama:"

#: ⭐ O MESMO `claude -p`, com a inferência no Ollama do Mac (spec do Mac, fase M2). O CLI
#: continua no notebook — portão, MCP, `--restricted`, `--resume` —, só o endereço muda.
#: Em AVALIAÇÃO: o editor quer saber se a resposta de um modelo de 8B basta.
#:
#: ⛔ `qwen3-vl:8b-instruct`, e não o `qwen3:8b`: o de texto tem teto de 40.960 tokens
#: (`/api/show`), e o VL é o que a decupagem já carrega — com `OLLAMA_MAX_LOADED_MODELS=1`
#: um segundo modelo derrubaria o primeiro a cada troca entre chat e fila.
#: Só aparece no painel com o endereço do Mac configurado.
MODELOS_LOCAIS = (
    {"id": LOCAL + "qwen3-vl:8b-instruct", "nome": "🖥 Qwen3-VL (Mac)",
     "para": "local, no Mac — não gasta a assinatura; em avaliação", "local": True},
)

#: ⭐ Em AVALIAÇÃO: aceitos pelo serviço (a bancada escolhe um pelo `/configuracoes`), mas FORA
#: do seletor do painel — o editor não vê um candidato que ainda não passou na prova. A busca é
#: o MENOR modelo local que dá conta do programa (autor, 2026-11-02: o Qwen3-VL 8B reprovou na
#: missão Resolve → MC → sync e no conselho; o Mac mini tem 16 GB, os modelos num SSD externo).
MODELOS_EM_AVALIACAO = (
    {"id": LOCAL + "qwen3.5:4b", "nome": "Qwen3.5 4B (Mac, avaliação)", "local": True},
    {"id": LOCAL + "qwen3.5:9b", "nome": "Qwen3.5 9B (Mac, avaliação)", "local": True},
)

#: O que vale como escolha de modelo. Vazio = o padrão da conta do editor.
IDS_DE_MODELO = {m["id"] for m in MODELOS + MODELOS_LOCAIS + MODELOS_EM_AVALIACAO}


def modelo_guardado() -> str:
    """O modelo que o editor escolheu, ou o PADRAO.

    ⛔ Escolha que saiu da lista cai no padrão (autor, 2026-10-29: o Sonnet 5 deu lugar ao
    5.5). Sem isto o `config.json` de quem escolheu o modelo antigo continuaria mandando no
    `--model`, e o seletor do painel não teria a opção para mostrar.
    """
    modelo = ler().get("modelo")
    return modelo if modelo in IDS_DE_MODELO else PADRAO


#: O `--effort` do CLI. ⛔ Lista fechada, pelo mesmo motivo de `MODELOS`: vira argumento de
#: linha de comando.
#:
#: ⭐⭐ MEDIDO no ensaio da C07 (2026-10-22, Sonnet 5, esforço padrão): 67,5 mil tokens de
#:    SAÍDA num turno de separar falas, 59% do custo — quase tudo pensamento (o bloco chega
#:    sem texto, só a assinatura cifrada, de até 86 mil caracteres). A barra das 5 h foi de
#:    18% a 41% num turno. O esforço é a alavanca desse pensamento; o efeito sobre a
#:    QUALIDADE ainda não foi medido. Sem escolha, vale o padrão do CLI.
ESFORCOS = ("low", "medium", "high")


def esforco() -> str:
    """O esforço escolhido, ou vazio (o padrão do CLI). Valor fora da lista é ignorado."""
    valor = str(ler().get("esforco") or "")
    return valor if valor in ESFORCOS else ""


def e_local(modelo: str | None) -> bool:
    """Se o modelo responde do Mac. ⚠️ Decide o ENDEREÇO do CLI, não só o nome."""
    return bool(modelo) and str(modelo).startswith(LOCAL)


def pasta() -> Path:
    """A pasta de dados do produto. A MESMA de `midia/cache.py` e `servico/diario.py`.

    ⛔ Uma conta só, e ela nasce aqui para os três. No projeto anterior esta conta existia
    em três lugares, e as cópias divergiram no macOS: log numa pasta, transcrição em
    outra, sem nada acusar. ⚠️ E neste projeto as três cópias voltaram a existir até
    2026-09-14 — agora `cache.raiz()` e `diario.pasta()` CHAMAM esta função.

    ⭐ `CICLOASSIST_DADOS` sobrepõe, em qualquer sistema: é como os testes isolam
    (`tests/conftest.py`). Isolar por `LOCALAPPDATA` só valia no Windows — MEDIDO no
    macOS, a suíte gravou `config.json` na pasta real do usuário.
    """
    do_ambiente = os.environ.get("CICLOASSIST_DADOS")
    if do_ambiente:
        return Path(do_ambiente)
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData/Local")
        return Path(base) / "CicloAssist"
    if sys.platform == "darwin":
        # ⚠️ Não `~/.local/share`: o Finder esconde, e "Abrir pasta" abriria o invisível.
        return Path.home() / "Library" / "Application Support" / "CicloAssist"
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share") / "cicloassist"


def arquivo() -> Path:
    return pasta() / "config.json"


def ler() -> dict[str, Any]:
    try:
        bruto = json.loads(arquivo().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(bruto, dict):
        log.warning("config.json não é um objeto; ignorando")
        return {}
    return {k: v for k, v in bruto.items() if k in CHAVES}


def gravar(mudancas: dict[str, Any]) -> dict[str, Any]:
    """Mescla `mudancas` no que já havia. Devolve a configuração resultante.

    ⚠️ Mescla, e não substitui: o painel manda só o que o editor mexeu, e um POST que
    trouxesse o objeto inteiro apagaria em silêncio o que uma versão futura tivesse
    acrescentado do outro lado.
    """
    with _trava:
        atual = ler()
        for k, v in mudancas.items():
            if k not in CHAVES:
                continue
            if v in (None, ""):
                atual.pop(k, None)     # voltar ao padrão é apagar a escolha
            else:
                atual[k] = v
        destino = arquivo()
        destino.parent.mkdir(parents=True, exist_ok=True)
        from ..midia.cache import escrever_atomico
        escrever_atomico(
            destino, json.dumps(atual, ensure_ascii=False, indent=1).encode("utf-8")
        )
        log.info("configuração gravada: %s", ", ".join(atual) or "(vazia)")
        return atual


# ── o que o SERVIÇO lembra ───────────────────────────────────────────────────
#
# ⚠️ Arquivo separado do `config.json` de propósito: aquele é o que o EDITOR escolheu, e
# ele pode querer abrir, ler e até apagar. Este é memória interna do produto — misturar os
# dois faria a tela de configurações mostrar coisa que não é dele.


def arquivo_de_estado() -> Path:
    return pasta() / "estado.json"


def ler_estado() -> dict[str, Any]:
    try:
        bruto = json.loads(arquivo_de_estado().read_text(encoding="utf-8"))
        return bruto if isinstance(bruto, dict) else {}
    except (OSError, ValueError):
        return {}


def gravar_estado(mudancas: dict[str, Any]) -> None:
    with _trava:
        atual = ler_estado()
        atual.update(mudancas)
        try:
            destino = arquivo_de_estado()
            destino.parent.mkdir(parents=True, exist_ok=True)
            from ..midia.cache import escrever_atomico
            escrever_atomico(
                destino, json.dumps(atual, ensure_ascii=False, indent=1).encode("utf-8")
            )
        except (OSError, ValueError) as e:
            log.warning("não consegui gravar o estado: %s", e)
