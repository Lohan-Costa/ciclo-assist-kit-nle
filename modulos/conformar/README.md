# De Lá Pra Cá

Ferramenta de pós-produção que **opera dentro do programa de edição**. O nome descreve o
fluxo inteiro, nos dois sentidos:

- **De Lá Pra Cá** — o material chega. No Media Composer: uma timeline offline, vinda de
  um AAF de montagem, é relinkada para a mídia original de câmera e vira uma timeline
  online. Apontando pastas, não lutando com Relink Settings.
- **Daqui Pra Lá** — o material sai. A timeline, arrastada da bin e lida direto da `.avb`
  (nunca por `ExportFile` — ADR 0015), vira **Carta Aberta** (o nosso JSON, legível —
  `docs/carta-aberta.md`) ou `.drt` do DaVinci Resolve. `.prproj`, AAF, XML e OTIO estão
  no seletor como "em breve".

Cada NLE tem lógica própria nos dois sentidos, porque a natureza dos programas difere.

## Por que dentro do editor

Com o programa aberto e dirigível, deixamos de precisar **imitar** o que decifrámos por
engenharia reversa: podemos pedir a ele que execute. No Media Composer isso é a diferença
entre reconstruir a timeline (e arriscar perder Titler+, FrameFlex e Matte Key) e deixar
que o próprio MC a monte, com os efeitos intactos.

## Como se distribui

```
App De Lá Pra Cá  ──instala uma vez──►  painel + serviço, por NLE
   · ponto de instalação                         │
   · janela agnóstica (para quem                 └─ opera com o App FECHADO
     não tem o programa de edição)
```

Cada plugin é **autônomo**: o painel dentro do NLE é a interface de um serviço local que
traz o motor embutido. O App instala o par e sai de cena.

## Estado

**Em construção.** Foco atual: relink no Media Composer.

| | |
|---|---|
| Fase 0 · fundação | ✅ painel abre, serviço fala com o MC |
| Fase 1 · rota de aplicação | ✅ **`ImportFile` aceita AAF** — quem monta a timeline é o MC, e os efeitos ficam intactos |
| Fase 2 · leitura | ✅ da bin viva (ou de um AAF) aos masters únicos |
| Fase 3 · matching | ✅ 45/45 masters de imagem por nome exato |
| Fase 4 · painel | ✅ 3 abas, revisão por master, progresso por SSE |
| Fase 5 · aplicar | ✅ **100/100 masters, 1121 segmentos, 81 s** |
| **Fase 5b · Windows nativo** | ✅ **serviço, painel e ferramentas rodando no Windows** — 96/96 na regressão |
| **Fase 5c · arrastar a timeline** | ✅ **arraste a timeline da bin para o painel** — validado no MC 25.6 |
| Fase 6 · App instalador e empacotamento | ⏳ |

Confirmado na GUI por um editor: timeline relinkada online, com **timewarp e
estabilizadores preservados**.

Não exercitado ainda: o caminho de *group clip* do achatamento (falta material com
multicam) e o segundo item de menu do manifesto (a janela larga de revisão).

## Plataformas

**Windows é a plataforma principal de instalação**; o macOS é onde o plugin nasceu e
continua funcionando. Toda diferença entre os dois mora num módulo só —
`plugins/media-composer/servico/plataforma.py` — com a medição ao lado de cada
constante ([ADR 0011](docs/adr/0011-uma-camada-de-plataforma-e-degradacao-por-versao.md)).

| | macOS | Windows |
|---|---|---|
| Ambiente de dev | `.venv` · `./dev.sh` | `.venv-win` · `.\dev.ps1` |
| Painel `.avpi` | `/Library/Application Support/Avid/PanelSDKPlugins` | `%PROGRAMDATA%\Avid\PanelSDKPlugins` |
| Settings do Avid | `/Users/Shared/AvidMediaComposer/Avid Users` | `C:\Users\Public\Documents\Avid Media Composer\Avid Users` |
| Trabalho do serviço | `~/Library/Application Support/DeLaPraCa` | `%LOCALAPPDATA%\DeLaPraCa` |

⚠️ **Dois venvs, um por sistema, e não um só compartilhado.** O disco atravessa as duas
máquinas, mas no Windows `.venv\Lib` e `.venv\lib` são a **mesma pasta** — o Win32 é
insensível à caixa mesmo em exFAT (medido) — e um venv seria escrito dentro do outro.

⚠️ **O painel pode aparecer em `Tools` OU em `Extensions`, e isso depende da VERSÃO do
Media Composer, não do sistema operacional.** O MC 25.6 honra o `menuName` do manifesto
e põe o painel em **Tools**; o 25.12 cria um menu top-level **Extensions** e agrupa por
conta própria.

## Rodar em desenvolvimento

**Windows**

```powershell
.\dev.ps1              # confere o ambiente e sobe o serviço
.\dev.ps1 -Pack        # empacota e instala o painel antes de subir
.\dev.ps1 -Limpo       # recria o venv do zero
```

Se o PowerShell recusar o script: `powershell -ExecutionPolicy Bypass -File .\dev.ps1`.

**macOS**

```bash
./dev.sh              # confere o ambiente e sobe o serviço
./dev.sh --pack       # empacota e instala o painel antes de subir
./dev.sh --limpo      # recria o venv do zero
```

Os dois fazem o mesmo roteiro: Python 3.12+, ffmpeg, venv, dependências, e avisam se o
painel não está instalado, se a porta está ocupada, se o Media Composer está fechado ou
se há um `avid-api-gateway` órfão segurando as portas do Panel SDK.

Para instalar o painel no Media Composer (as ferramentas são as mesmas nos dois SOs):

```bash
python tools/pack.py        # empacota e instala o .avpi
python tools/reload.py      # com o MC FECHADO — mata o gateway órfão
# abra o MC → Tools ▸ De Lá Pra Cá   (ou Extensions, conforme a versão)
```

⚠️ **Painel já aberto não recarrega sozinho.** A webview do MC guarda a página. Para ver
uma alteração: botão direito na área vazia do painel → **Reload**. Fechar e reabrir o
painel *não* funciona. O número de versão no rodapé é o que denuncia build velha.

⚠️ **`tools/reload.py` existe por um motivo medido**: o `avid-api-gateway` não morre com o
Media Composer — vira órfão e segura as portas 4920/4930. No boot seguinte o menu dos
painéis simplesmente não é criado, sem erro e sem log.

⭐ **E a assinatura do órfão muda de sistema operacional.** No macOS o `launchd` o adota
(`ppid == 1`); o Windows não reparenta, então o órfão é aquele cujo `ppid` já não aponta
para ninguém vivo. Um zelador portado sem essa correção não encontra nada — e não
reclama.

## Testes

Nenhum precisa do Media Composer aberto.

```bash
# macOS                                    # Windows: .venv-win\Scripts\python
.venv/bin/python tests/test_portao.py      # a única tranca do serviço
.venv/bin/python tests/test_arquivos.py    # nada sai de fora de ui/
.venv/bin/python tests/test_nomes.py       # a regra dos nomes frouxos
.venv/bin/python tests/test_plataforma.py  # coluna Drive + degradação por versão do MC
.venv/bin/python tests/test_dialogo_win.py # o seletor moderno (pulado fora do Windows)
.venv/bin/python tests/test_arrasto_caminhos.py  # URI de arrasto → caminho (precisa de node)
.venv/bin/python tests/test_nome_de_bin.py # nome da bin entregue, e a política do número
.venv/bin/python tests/test_tempos_mcapi.py  # consulta tem prazo curto; arquivo, não
.venv/bin/python tests/test_banco_midias.py  # o mapa de mídias compartilhado
.venv/bin/python tests/test_banco_projeto.py # a config do banco vive na pasta do projeto
.venv/bin/python tests/test_duracao_aaf.py # duração do master: length e taxa do MESMO slot
```

## Como o De Lá Pra Cá é por dentro

- **[Arquitetura](docs/ARCHITECTURE.md)** — visão geral: os componentes, como
  conversam entre si, o que o serviço escreve no disco e o que sai da máquina.
- **[Decisões de arquitetura (ADRs)](docs/adr/)** — o *porquê* de cada escolha
  não-óbvia.

## Documentos

- `VENDOR.md` — o que veio do RELINKER e do Órbita, com commit e adaptações
- Base técnica: `../bancodedadosnles/plugins/avid-panel-sdk/`

## Ambiente

Python 3.12+ e `ffmpeg` no PATH, nos dois sistemas.

O volume de desenvolvimento é **ExFAT** e atravessa as duas máquinas. Consequências
práticas: os venvs são criados com `--copies` (o ExFAT não tem symlinks), o **bit de
execução não persiste** — no macOS chame os scripts com `bash` —, e o ExFAT **não guarda
permissão POSIX**, então nada que dependa de `chmod 0600` pode morar aqui.

⚠️ **`dev.ps1` precisa estar em UTF-8 COM BOM.** O Windows PowerShell 5.1 lê um `.ps1`
sem BOM como ANSI, e aí um traço longo (`—`) vira `â€"`, cujo `”` o parser aceita como
aspas de fechamento — o script morre com `Missing closing '}'` apontando dezenas de
linhas depois do acento que causou tudo. O próprio arquivo explica como regravar e como
conferir.
