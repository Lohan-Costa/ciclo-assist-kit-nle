# VENDOR — o que veio de onde

Este projeto nasceu em 2026-08-10 compondo duas linhagens. Nada foi forkado: os arquivos abaixo
foram **copiados** e passam a viver aqui. `RELINKER/` e `DRAMASYNC/` continuam intactos e seguem
seu próprio caminho — divergência a partir daqui é esperada, não é bug.

| origem | commit | data |
|---|---|---|
| `PROGRAMAS COM CLAUDE/RELINKER` | `8f6c57af5845a85017c684e2730e92341ad752da` | 2026-07-11 |
| `PROGRAMAS COM CLAUDE/DRAMASYNC` (Órbita) | `25951757520f80fc02459d7d0e9e405e2ae8f947` | 2026-08-09 |

---

## Do RELINKER → `motor/`

Copiado de `RELINKER/src-python/`, sem `__pycache__`:

| aqui | lá | o que é |
|---|---|---|
| `motor/aaf/` | `aaf/` | `parser.py` (parse_aaf), `writer.py` (**relink_aaf**), `markers.py`, `speedcurve.py` |
| `motor/media/` | `media/` | `indexer.py` (varredura de pastas), `matcher.py` (cascata por segmento) |
| `motor/frames/` | `frames/` | extração de frame, pHash, cache, sequências de imagem, decoders RAW |
| `motor/avb_export/` | `avb_export/` | `build_avb` — autoria de `.avb`. Fallback da rota `.avb` |
| `motor/drp/` | `drp/` | writer do `.drt` do Resolve — **dormente** até a aba "Daqui Pra Lá" |
| `motor/otio_export/` | `otio_export/` | writer OTIO — **dormente** |
| `motor/bench.py`, `motor/control.py` | idem | benchmark opt-in e cancelamento cooperativo |
| `motor/tools/inspect_drp.py` | `tools/inspect_drp.py` | codecs de blob que `drp/writer.py` importa em runtime |

### Adaptações feitas na cópia

1. **`avb_export/repoint_subclips.py` NÃO veio.** É script de linha de comando do bancada de estudo,
   ninguém o importa, e ele referencia um módulo `avb_clone` que não existe no pacote — entraria
   quebrado.
2. **`tools/` veio só com `inspect_drp.py`.** O resto (`gen_chart`, `inspect_effects`,
   `test_*`…) é bancada de estudo do RELINKER e ficou lá. `tools/__init__.py` é novo, escrito aqui.
3. **`media/indexer.py` → `_build_hint_filter` agora aceita por chave FROUXA também.**
   No RELINKER o filtro do scan rápido era só estrito (preservando separadores), com o argumento
   de que variações ficariam para o botão "Scan completo". Medido neste acervo, o argumento não se
   sustenta: o Avid grava nomes por timecode e o mesmo item é `17;25;16 Cordas.wav` no disco e
   `17_25_16 Cordas.wav` no AAF. Com o filtro estrito o índice via **89 de 378** arquivos e 29
   trilhas não resolviam — não por ambiguidade, mas por nunca terem entrado no índice.

4. **Nada mais foi editado.** As correções previstas para o matcher (duração de áudio,
   `_MEDIA_EXT_RE`) não foram necessárias: `matcher_masters.py` é novo e não herda esses trechos.
   A normalização de UMID foi reescrita lá (`_chave_uid`), sem tocar no original.

### Dívida consciente: os imports são de topo

O motor usa imports absolutos **entre** pacotes (`from frames.extractor import …`, `import control`)
e relativos **dentro** de cada um. Isso é herança do RELINKER, que põe `src-python/` no `sys.path`.
Mantivemos como está — reescrever 88 KB de `translate.py` para imports relativos é risco sem retorno
agora.

**Consequência:** quem usa o motor põe `motor/` no `sys.path`, e `aaf`, `media`, `frames`, `control`
e `bench` passam a ser nomes de topo. São nomes genéricos e podem colidir. Aceitável porque o serviço
roda isolado (PyInstaller, processo próprio); revisitar se algum dia o motor virar biblioteca
publicada.

---

## Do Órbita (DRAMASYNC) → `plugins/media-composer/servico/avid/` e `motor/media/`

| aqui | lá | o que é |
|---|---|---|
| `servico/avid/mcapi.py` | `src-python/avid/mcapi.py` | cliente gRPC do MC em `[::1]:9100`, com os gotchas já resolvidos |
| `servico/avid/masters.py` | `src-python/avid/masters.py` | acha o MXF de um master por `material_package_umid` |
| `servico/avid/proto/` | `src-python/avid/proto/` | stubs protobuf gerados (`mcapi_types_pb2.py`) |
| `motor/media/opatom.py` | `src-python/media/opatom.py` | leitura de MXF OP-Atom |
| `motor/media/safepath.py` | `src-python/media/safepath.py` | ⭐ fronteira "string que alguém mandou" → arquivo em disco |
| `motor/media/fftools.py` | `src-python/media/fftools.py` | localizar ffmpeg/ffprobe |
| `tools/gen_mcapi_stubs.py` | `src-python/tools/gen_mcapi_stubs.py` | regerar os stubs a partir do `.proto` |

### Adaptações feitas na cópia

1. **`avid/adapter.py` e `avid/writer.py` NÃO vieram.** Dependem de `sync.model.Daily`, que é o
   domínio de sincronização de diárias do Órbita e não existe aqui. O `servico/avid/__init__.py` é
   novo, escrito aqui, e exporta só o cliente.
2. **`safepath.py` é peça de segurança, não utilitário.** Ele existe porque o `pymediainfo` **busca
   URLs** (pula `os.path.exists` quando a string tem `://`, e a libmediainfo traz `Reader_libcurl`
   compilado) e porque o ffprobe lê um arquivo começado em `-` como opção. `ff_input()` devolve
   `"file:" + absoluto`, o que fixa o protocolo e nunca começa com `-`. **Todo caminho vindo do
   painel passa por aqui** — é o que o plano chama de "pasta de rede é entrada não confiável".

---

## O que ainda não veio, e virá

- **Shell Tauri do Órbita** (`tray.rs`, `lib.rs`, `nle_install.rs`, `IntegrationBlock`) → `app/`,
  na Fase 6, quando o App instalador for construído.
- **Design system de painel** (`plugins/premiere-cep/index.html:11-23` e o CSS de abas) → a UI do
  painel, na Fase 4.
- **UI do RELINKER** para a janela agnóstica (quem não tem o NLE) — etapa posterior.

---

## Ambiente

- **Python 3.11** (`/opt/homebrew/bin/python3.11`). `.venv` criado com **`--copies`**: o volume é
  **ExFAT** e não tem symlinks.
- ExFAT também não guarda o bit de execução — chame os scripts como `bash tools/pack.sh`, não
  `./tools/pack.sh`.
- `ffmpeg` precisa estar no PATH.
