# avb_export — backend AVB do Relinker

Autora uma timeline **.avb** (bin nativa do Avid Media Composer) a partir dos segmentos do parser
neutro do Relinker (`aaf/parser.py`), **dentro de uma bin de mídia AMA-online**. Resultado: bin única
que abre no MC com a timeline montada e a mídia online — **zero relink manual**. É mais um backend de
export, paralelo a `aaf/writer.py`, `drp/writer.py`, `otio_export/writer.py`.

Descoberta que destravou tudo: dá pra autorar uma CompositionMob que o MC aceita, e byte-surgery/clone
autora masters de mídia AMA — então o Relinker pode entregar **.avb** (não só AAF).

## Módulos

| arquivo | papel |
|---|---|
| `translate.py`        | tradutor timeline: segmentos → CompositionMob .avb (cortes, transições, efeitos geométricos, velocidade/motion incl. rampa, áudio combiner/awarp/ganho/AudioSuite, N trilhas, rate). |
| `templates.json`      | 16 templates de EFEITO serializados (project-neutral). Carregados em runtime; capturados dos GOLD só com `--build-templates`. |
| `video_descriptor.py` | autora o descriptor CDCI de um master de VÍDEO AMA genérico do ffprobe (resolve a corrupção de clone-de-template por dims). |
| `audio_templates.json`| templates de descriptor de ÁUDIO por formato (bits/canais/coding). |
| `clone.py` / `relink.py` / `merge.py` | byte-surgery: clona master de mídia (mob_id/duração/data/nome), repatcheia caminho (tamanho ≠), mescla bins. |
| `nle_model.py`        | fingerprint estrutural + diff (regressão e dump). |

## API

```python
from avb_export import build_avb          # sidecar: a partir de SEGMENTOS já parseados
build_avb(segments, timeline_fps, media_bin, out, seqname,
          aaf_path=..., remap={AAF_master_hex: media_hex}, media_map=..., fix_leaks=True)

from avb_export import build_avb_from_aaf  # CLI/regressão: a partir do AAF (reparse)
```

Sidecar: comando `export_avb` em `main.py` (params: segments, timeline_fps, media_bin, output_avb,
timeline_name, aaf_path, remap, media_map). CLI: `python avb_export/translate.py AAF MEDIA_BIN OUT SEQ`.

## Ponte de mob_id (remap)

O AAF referencia masters por mob_id (managed). A bin de mídia AMA tem mob_ids FRESCOS. `remap` =
`{AAF_master_hex → media_hex}`, emitido pelo media-bin builder. Só masters entram na ponte;
subclip/grupo/container são resolvidos aos originais pelo parser (sem entrar na ponte).

## Descriptor de vídeo AMA (video_descriptor.py) — pesquisa resolvida

Clonar 1 template de vídeo em todas as câmeras corrompe (`avc_sps_patcher r_crop_req`) quando as
DIMENSÕES diferem — a geometria CDCI é por clipe. Diff de descriptors reais aceitos pelo MC isolou os
campos derivados da geometria; o resto é boilerplate constante. Mapa ffprobe→CDCI (validado por diff:
autorar 2048 do skeleton 1920 saiu idêntico ao B001 real):

- `stored/sampled/display_width` = width; `aspect_ratio` = DAR reduzido
- caixas `valid/essence/source_box` em unidade 5/6 px: X=-(width·5/6)/2, W=width·5/6 (só largura muda
  entre clipes de mesma altura → Y/H do skeleton); `source` usa stored (crop), `valid/essence` display
- `stored_height` = ceil16(display_h) (1080→1088; MC tolera 1080 e 1088)
- `_SD_AVC_SUB_DESCRIPTOR` level/profile = ffprobe; `edit_rate`=fps; `length`=nb_frames;
  `_CONTAINER_HANDLER_GUID` por extensão

1 skeleton por classe de ALTURA cobre qualquer largura; alturas múltiplas de 16 (2160/720) sem crop
são computáveis por fórmula (`compute_boxes`).

## Project-neutral (sem amarra a projeto de estudo)

- Templates de efeito EMBUTIDOS (`templates.json`); GOLD só p/ regenerar (`AVB_GOLD_DIR`, dev-only).
- `media_map` e `remap` vêm por parâmetro/env (`AVB_MEDIA_MAP`/`AVB_REMAP`), nada hardcoded.
- Templates carregam mob_id dos gabaritos nos slots de inner-clip, mas o build SEMPRE substitui o
  inner; residual = só o placeholder benigno do AudioSuite (7f7f2a80, UMID nulo). `fix_leaks=True`
  (default no sidecar) troca qualquer mob estranho por Filler.

## Regressão

`tests/avb/regression.py` (12 casos FASE 1/2, snapshots de fingerprint). Gabaritos = fixtures de dev
(via `AVB_GOLD_DIR`), não runtime. Rodar: `.venv/bin/python tests/avb/regression.py`.

## PENDENTE (próxima sessão dedicada)

- **Media-bin builder genérico** (assembly): p/ cada arquivo original → descriptor (vídeo=video_descriptor;
  áudio=clone por formato) + mob_id fresco + locator/path + `_AMA_FILE_DATE_TIME`(mtime) + length → mescla
  numa bin; emite `media_map` + `remap`. Peças-base prontas (video_descriptor, audio_templates, clone/relink).
  Hoje o eng-rev usa `build_from_relinked` (extrai da bin relinkada do projeto de teste = STUDY-ONLY) — substituir.
- Efeitos de vídeo ainda dropados no front-end do Relinker: frameflex/Titler (reproduzir).
- UI Tauri (botão de export AVB) — só o backend/sidecar/CLI estão prontos.
