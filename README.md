# Ciclo Assist

Um app de uma janela só para a montagem, que serve o **Media Composer**, o **Premiere Pro** e o **DaVinci Resolve**
por fora — sem painel dentro de nenhum deles — com o **Claude como motor**, na assinatura do próprio editor: sem chave
de API e sem modelo local. Faz parte do **KIT ABERTO DOS NLEs** (https://github.com/Lohan-Costa/kit-aberto-dos-nles).

> **A inversão que define o projeto:** não é o app que chama o Claude, é o Claude que chama o app. O código não é
> cliente de IA nenhuma — expõe ferramentas MCP e espera ser chamado. Quem paga o modelo é a assinatura logada na
> máquina do editor.

## As abas

| aba | o que faz |
|---|---|
| **Preparar** | o **Sincronizar**: câmera e som por timecode e forma de onda, com subclipes por cena (Media Composer) ou merged clips (Premiere) |
| **Assistir** | identificar material visualmente, separar as falas de uma cena, a busca por frase e por fala, a decupagem |
| **Conformar** | levar a montagem de um programa para outro sem formato intermediário (Premiere, Media Composer, Resolve, Baselight), com a rampa de velocidade quadro a quadro, as máscaras e a conferência visual contra o vídeo de referência |
| **Entregar** | em breve |

E os **Fluxos e Agentes**: receitas que encadeiam operações (abrir o Resolve, converter a diária, abrir o Media
Composer, importar, sincronizar, subclipar, salvar), com o piloto onde a API do programa não alcança.

## Como cada programa é servido

- **Media Composer:** a API gRPC local (porta 9100), sem nada instalado no programa.
- **Premiere Pro:** a **ponte** — uma extensão CEP invisível (`ponte_cep/`) que carrega quando o Premiere abre; é
  instalada pela ⚙ › Integrações da janela (ou `python tools/integracoes.py --fazer`).
- **DaVinci Resolve Studio:** a API de script externa (a versão gratuita não a tem).
- **Baselight:** a FLAPI e as ferramentas de linha de comando.

## Instalar

O app mora **dentro da pasta do kit**, para achar o banco, o piloto e o laboratório subindo de pasta:

```
kit-aberto-dos-nles/
├─ bancodedadosnles/  piloto/  laboratorio-de-midia/  …
└─ ciclo-assist-kit-nle/      ← este repositório
```

O jeito recomendado é pedir ao Claude do kit (a skill `ciclo-diagnostico` levanta a máquina e diz o que falta). À mão:

- **Requisitos:** Python 3.11 ou mais novo; `ffmpeg` e `ffprobe`; o [Claude Code](https://claude.com/claude-code)
  instalado e logado; e, para compilar a janela, o Rust (https://rustup.rs).
- **Windows:** duplo clique em `INSTALAR.bat` (seis passos, com o consentimento antes de cada um).
- **macOS:** crie o ambiente (`python3 -m venv .venv` e `.venv/bin/pip install -r requirements.lock`), depois
  `python tools/gerar_stubs.py` (os stubs da API do Media Composer, gerados do banco).
- **Abrir a janela:** `ABRIR-APP.bat` (Windows) ou `ABRIR-APP.command` (macOS, duplo clique no Finder). A primeira
  abertura compila a janela.

## Testes

```
python -m pytest                  # sem programa de edição aberto e sem gastar turno do modelo
```

Os spikes (`spikes/`) provam cada elo com o programa vivo e saem `0` se passaram; a lista e o que cada um exige estão em
`docs/conhecimento/spikes-e-servico.md`. Alguns testes usam dados de produções reais que não vêm neste repositório:
eles pulam, dizendo o que falta.

## Onde mora o conhecimento

Este repositório guarda a **implementação**. O conhecimento dos formatos, das APIs e do ambiente de cada programa mora
no banco do kit (`../bancodedadosnles/`): consulte antes de investigar, registre depois de descobrir. As decisões estão
em `docs/adr/`, os planos em `docs/plano/` e as convenções de trabalho no `CLAUDE.md`. Ameaças e o que **não** está
protegido: `docs/ameacas.md`.

## Licença

GPL-3.0 (`LICENSE`). Idealizado por Lohan Costa, edt.
