# macOS — a revisão de 2026-09-14

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

### macOS — revisão de 2026-09-14 (sem Media Composer: só código e suíte)

Todo o produto nasceu no Windows. A passada no Mac mini achou o que segue, e **cada item tem
teste**; a suíte roda inteira no Mac (Python 3.12 do lock, que exige ≥ 3.12).

- ⛔⛔ **Os testes isolavam por `LOCALAPPDATA`, que só o Windows lê** — no Mac a suíte gravou
  `config.json` na pasta REAL do usuário, e um teste passou a falhar pelo lixo do anterior.
  Agora `config.pasta()` aceita `CICLOASSIST_DADOS` em qualquer sistema, `tests/conftest.py`
  aponta para o tmp, e `cache.raiz()`/`diario.pasta()`/pendências/modelos DERIVAM dela (eram
  três cópias da conta — o defeito que o docstring dizia já ter pago no projeto anterior).
  No Mac a pasta é `~/Library/Application Support/CicloAssist`.
- ⛔⛔ **O PATH do serviço não é o do terminal.** Lançado por Finder/launchd ele recebe
  `/usr/bin:/bin:/usr/sbin:/sbin`: `claude`, `ffmpeg` e `ffprobe` "não encontrados" com eles
  instalados. `cicloassist/binarios.py` procura também `~/.local/bin` (ANTES do Homebrew:
  lá havia um `claude` 2.1.150 que recusa `--restricted`) e `/opt/homebrew/bin`.
- ⛔⛔ **CLI que morre na partida virava turno "pronto" vazio** — EOF sem `result` seguia para
  `fim`, e o motivo ficava no stderr. Agora é `erro` com o fim do stderr (sessão e decupador;
  o decupador também drena o stderr e o prazo mata o processo).
- ⛔ `Avid MediaFiles` mora DENTRO de cada volume (`/Volumes/*/…`) e, no disco de sistema, em
  `/Users/Shared/AvidMediaComposer/`. `take.raizes_de_midia` usava letras `C:`–`Z:` e o acervo
  procurava `/Volumes/Avid MediaFiles`: **nenhuma mídia gerenciada era achada**. Uma lista só
  (`acervo.pastas_de_midia`), sem entrar em pasta oculta (`.sync/` com 955 cópias de conflito).
- ⛔ **Arrastar do Finder dava caminho relativo** (`file:///Users/x` → `Users/x`): o regex comia
  a barra da raiz. E o nome chega em NFD — `arrastados`, o índice do cache e
  `mcapi.relativo_ao_projeto` comparam em NFC e sem maiúsculas.
- ⚠️ **As bins do MC do Mac levam estado em atributo estendido** (`BINSTATE_RSRC`, colunas e
  formatos). `os.replace` o apagava e `shutil.copy2` não o copia no macOS:
  `avid/atributos.py` o leva junto. ⬜ Efeito de perdê-lo no MC não medido.
- ⚠️ exFAT + macOS: cada arquivo gravado ganha um `._` na hora. Fica fora de contagem de
  quadros, de bytes e da lista de bins.
- ⚠️ `allow_reuse_address` desligado no POSIX segurava a porta em TIME_WAIT (~30 s) depois
  de cada turno; no POSIX ele NÃO deixa dois ouvintes, então fica ligado lá (`http._Servidor`).
- Seletor de pasta: `osascript` `choose folder` (cancelar = erro −128, nunca pelo texto
  traduzido). "Abrir pasta": `open`. Painel: `/Library/Application Support/Avid/PanelSDKPlugins`,
  menu **Extensions** (banco). `tools/lock.py` recusa gerar fora do Windows (perde `colorama`).
- ⬜ **Não conferido, precisa de MC na tela:** o drop do Finder no QtWebEngine do MC, o
  `choose folder` à frente do MC, `CloseBin`/`OpenBin` com caminho NFD, e a pausa de 3 s do
  monitor. ⬜ Sem `dev.sh`. ⬜ `percepcao` recusa `localhost` também no Mac, onde o Ollama
  local não é proibido — decidir se o serviço vai rodar no Mac.
- ⚠️ Os `__pycache__` do SSD foram compilados no Windows: traceback no Mac mostra `D:\…` e
  `???`. Rodar com `PYTHONPYCACHEPREFIX` fora do SSD.
