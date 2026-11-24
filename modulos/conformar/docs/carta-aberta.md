# Carta Aberta — formato de timeline (v1.1)

A Carta Aberta é o formato de timeline da Ciclo Media: **um JSON que gente e máquina leem**.
Não tenta substituir DRT, AAF ou PRPROJ — é o retrato fiel do que o motor leu da timeline,
com a origem, o comentário do editor e o que ficou de fora escritos junto. Uma carta que
diz o que **não** carrega.

⭐⭐ **Desde a 1.1 ela é o intermediário SEM PERDAS** (regra do autor: *"nada deve ser perdido
na carta aberta"*). Leva a leitura crua do Avid — segmentos de antes da resolução de mídia e
cada master inteiro no bloco `avid` — mais o que o remetente sabia da mídia. Quem recebe
refaz a timeline no formato do editor dele (no Resolve, um DRT temporário) e chega ao MESMO
resultado: `tests/test_carta_ida_e_volta.py` exige DRT da bin ≡ DRT da Carta (80 sequências
reais em 2026-09-24). É também o envelope do **Magic Link** (envio pela pasta combinada).

Quem escreve: `motor/carta_aberta/writer.py`. Quem lê: `motor/carta_aberta/reader.py`
(`ler_carta`, que trata a Carta como texto de terceiro — ver o fim deste documento).

## Estrutura

```json
{
  "carta_aberta": "1.1",
  "gerado_em": "2026-09-24T14:03:00-03:00",
  "gerado_por": "De Lá Pra Cá",
  "nome": "PRODA_CORTE_240924",
  "origem": {
    "aplicativo": "Avid Media Composer",
    "sequencia": "PRODA_CORTE.02.Exported.01",
    "mob_id": "urn:smpte:umid:060a2b34…",
    "leitura": "avb"
  },
  "tempo": {
    "fps": 23.976,
    "drop_frame": false,
    "tc_inicial": "01:00:00:00",
    "tc_inicial_frames": 86400,
    "base_dos_segmentos": "frames a partir do início da timeline (00:00:00:00), sem o TC inicial somado"
  },
  "comentario": "texto livre do editor, ou null",
  "marcadores": [],
  "segmentos": [ { "…": "um por evento da timeline, ver abaixo" } ],
  "masters": [ { "…": "um por original, ver abaixo" } ],
  "resumo": { "segmentos": 1192, "com_arquivo": 0, "offline": 844, "sem_arquivo": 0 },
  "avisos": [ { "texto": "efeito geométrico: nome exportado, parâmetros ainda não traduzidos", "vezes": 8 } ],
  "conferencia": [],
  "envio": { "id": "a1b2c3d4-…", "tipo": "insert_vfx",
             "remetente": { "maquina": "EDIT-02", "usuario": "editor" },
             "enviado_em": "2026-09-24T16:40:12-03:00" },
  "selecao": [ { "track": 1, "timeline_tc_in": "00:02:51:12", "timeline_tc_out": "00:03:11:08", "mob_id": "urn:…" } ]
}
```

- `conferencia` — trilhas cujo percurso não fechou no comprimento da sequência (vazio = tudo fechou).
- `envio` — no Magic Link e no insert exportado. `tipo`: `timeline` · `insert_cor` · `insert_vfx`
  · `insert` (insert exportado para um arquivo, sem canal). Desde 2026-09-25 o Magic Link é feito
  de canais por setor, e o envio de um canal traz também `canal` (`cor`, `vfx`…), `de` e `para`
  (`edicao` ou o setor). Quem lê uma Carta sem esses campos a trata como antes. Desde 2026-10-13
  o envio de uma TIMELINE saída do Media Composer leva a bin dela ANEXA (decisão do autor: Magic
  Link Avid → Avid = Carta + a bin): `bin_anexa` é o nome do `.avb` gravado ao lado da Carta (o
  mesmo nome, `.avb` no lugar de `.carta.json`). O Media Composer que recebe relinka por ela, com a
  composição do editor intacta; os outros NLEs usam a Carta e ignoram o campo.
- `selecao` — só nos inserts: os segmentos escolhidos. ⚠️ **A Carta de um insert leva a timeline
  INTEIRA** e a seleção à parte; quem recebe filtra. Assim nada se perde, e o mesmo arquivo abre o
  contexto completo.

### `masters[]` — quem é cada original

É por aqui que o lado de lá (o colorista, o plugin da Ciclo Media no Resolve) casa um clipe
com o arquivo em alta. Vale também para mídia gerenciada do Avid — é o caso normal de quem
edita offline.

| campo | o que é |
|---|---|
| `mob_id`, `nome` | o master no Avid |
| `reel` | o nome do arquivo de câmera (sem extensão), lido da bin |
| `tc_origem` | TC de câmera do 1º frame do master (`HH:MM:SS:FF`) |
| `duracao_frames`, `fps`, `resolucao` | da essência |
| `arquivo_original` | `Source File` do Media Composer, com extensão — quando ele sabe |
| `arquivo`, `offline` | o caminho que o export usou; `offline: true` = não está nesta máquina |
| `avid` | ⭐ **(1.1)** o master EXATAMENTE como a leitura da bin o deu: `nome`, `caminho_na_bin`, `descritor`, `fps` (nativo), `duracao_frames`, `identidade` (reel, TC, taxas, resolução, áudio), `essencias` (`{"picture:1": urn, "sound:2": urn}`), `colunas_mc`. **É o que uma máquina lê**; os campos de cima são para gente e misturam fontes |
| `arquivo_ama` | **(1.1)** o arquivo AMA que o REMETENTE achou, ou `null` |
| `gerenciadas` | **(1.1)** `{trilha: .mxf}` da mídia gerenciada que o REMETENTE achou, por essência |

### `segmentos[]`

Cada item tem **os campos de `aaf/parser.py::Segment.to_dict()`** — o modelo neutro que o
motor inteiro usa — mais `arquivo`:

| campo | o que é |
|---|---|
| `timeline_tc_in` / `timeline_tc_out` / `duration_frames` | posição na timeline (base 0, ver `tempo`) |
| `track` | `1, 2, …` = V1, V2…; `1000, 1001, …` = A1, A2… |
| `is_audio` / `is_gap` / `is_transition` / `is_effect` / `disabled` | a espécie do evento |
| `clip_name` | o nome que o editor vê na timeline (pode ser o de um subclipe) |
| `mob_id` | o MobID do **master** (URN) |
| `source_start_frames` / `source_fps` | onde o evento começa na fonte |
| `media_ref` | o master: `mob_name`, `local_path`, `source_duration_frames`, `source_fps` |
| `cutpoint` | só em transição: frames do lado A |
| `has_motion_effect`, `speed_ratio`, `motion_effect_type`, `source_offset_map`, `speed_curve` | velocidade. ⚠️ `speed_ratio` é **timeline ÷ fonte** (85% → 1,1617) |
| `effects[]` | `{name, category, reproducible, params}` — `reproducible: false` quando os parâmetros ainda não são traduzidos |
| `arquivo` | o arquivo do evento: físico, ou a REFERÊNCIA ao original quando `offline` |
| `offline` | `true` = o original não está nesta máquina (quem recebe religa) |

⚠️ `source_start_frames` na Carta é relativo ao início do MASTER (como o Avid o vê). O TC de
câmera do ponto de entrada é `masters[].tc_origem + source_start_frames`.

## Regras

- **O comentário não é marcador** nesta versão: é texto livre em `comentario`. Quando o
  export de DRT ganhar marcadores, o mesmo texto vira um marcador no início da timeline.
- **`avisos` é parte do contrato**: tudo que o leitor pulou ou não conferiu (multicam,
  parâmetros de efeito, velocidades não validadas) aparece ali com a contagem. Um consumidor
  que ignore `avisos` está lendo uma timeline incompleta sem saber.
- A versão sobe (`1.1`, `2.0`) quando um campo muda de sentido. Campo novo não quebra
  leitor antigo.

## ⚠️ Para quem for LER uma Carta Aberta

⭐ Em Python, use `carta_aberta.reader.ler_carta`: teto de 64 MB, só versão `1.x` (a `1.0` é
recusada — não traz o bloco `avid`), forma conferida, erro legível (`CartaInvalida`) e **nenhum
caminho de dentro da Carta tocado no disco**. O que existe NESTA máquina decide o receptor.

`clip_name`, `media_ref.mob_name`, `arquivo`, `arquivo_ama`, `gerenciadas`, `comentario` e os
nomes de efeito são **texto de terceiro** (nome dado pelo editor, caminho de disco). Um app que exibir esses campos em
HTML precisa escapá-los — é a mesma ameaça T-02 da modelagem (`modelagens/…/ameacas.yaml`),
agora do lado de quem lê. E `arquivo` é um caminho vindo de outra máquina: não abra, não
teste existência de caminho de rede (UNC) sem validar antes (banco,
`transversal/matriz-de-plataforma.md` §C).
