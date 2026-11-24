# 0015 — O export lê a bin; nunca chama `ExportFile`

**Status:** decidido pelo usuário (2026-09-24) · em implementação · Data: 2026-09-24
**Relaciona-se com** o [ADR 0009](0009-preset-de-export-embarcado.md) e o
[ADR 0013](0013-a-rota-avb-volta-a-existir.md).

---

## Contexto

A aba **Daqui Pra Lá** leva uma timeline de dentro do Media Composer para outro NLE
(`.drt` do Resolve primeiro; Carta Aberta, nosso JSON, junto). Os writers de saída
(`motor/drp/writer.py::build_drt`, `motor/otio_export/writer.py::build_otio`) consomem
uma lista linear de segmentos no formato de `motor/aaf/parser.py::Segment.to_dict()`.

Havia dois jeitos de obter essa lista:

1. pedir ao MC um `ExportFile` de AAF e passar o arquivo por `parse_aaf` — o parser já
   existe, e a rota de import usa exatamente isso como caminho B (ADR 0009);
2. ler a `CompositionMob` direto da bin `.avb` com `pyavb`.

## Decisão

⛔⛔ **O export nunca chama `ExportFile`.** A timeline é sempre lida da bin `.avb`.
O usuário vetou o caminho 1 por riscos já conhecidos e vividos pelo time — não é
fallback, não é plano B, não se propõe de novo.

Consequência imediata: **o leitor `.avb → segments` precisou ser escrito**. Ele não
existia em nenhum app da família (RELINKER, De Lá Pra Cá, Assist anterior, Ciclo Assist,
DRAMASYNC) — o que existia era fingerprint para regressão
(`RELINKER/src-python/avb_export/nle_model.py`) e edição in-place (Ciclo Assist). Mora
em `motor/avb_bin/segmentos.py` e reaproveita os dataclasses de `aaf/parser.py`, de
modo que os writers não sabem de onde a lista veio.

## Consequências

- Achar a bin da sequência arrastada: `mcapi.bin_do_mob` (uma chamada), e **salvar a
  bin antes de ler** — senão o disco tem a casca antiga (armadilha já tratada na rota
  `.avb` de import).
- Arquivo de CADA CLIPE, nesta ordem (regra do autor: "a mídia que vale é a gerenciada"):
  1. a `.mxf` gerenciada da trilha, pelo índice do Avid (`media/pmr.py`, `msmFMID.pmr`) —
     online, como o Resolve liga importando o AAF (validado no Resolve 19 pelo autor);
  2. o arquivo AMA (locator da `.avb` ou colunas do MC);
  3. referência ao original, offline, com reel e TC de câmera — para quem recebe.
- O DRT é gerado sobre um esqueleto do **Resolve 19** (`drp/skeleton_r19.drt`): o 19 recusa o
  formato do 20.3, e as versões novas abrem as antigas.
  ⚠️ **`nle_model.locator_path` não serve**: só lê `path_posix` (macOS) e devolve `None` em
  toda bin gravada no Windows, onde o locator é `WinFileLocator` com `D//…` em
  `path_utf8`. Caminho UNC vindo da bin é recusado antes de tocar o disco.
- Escopo v1, medido em 5 sequências reais (todas as trilhas fecham no comprimento):
  cortes, TC, transições, velocidade (constante/conformação/congelamento/rampa), áudio
  (o `build_drt` já escreve), `Selector` de clipe desabilitado, efeitos embrulhando o
  clipe (nome exportado, parâmetros ainda não traduzidos). Multicam fica de fora, com aviso.
- Destino: seletor de PASTA + campo de nome com variáveis (`%{sequencia}`, `%{data}`…),
  como o autor desenhou — não o "Salvar como", que juntaria as duas coisas. Nunca
  sobrescreve: numera (`NOME_2.drt`).
- Gerar o primeiro DRT no Windows achou um defeito antigo em `drp/writer.py`: caminho com
  `\` na string de substituição do `re.sub` (`bad escape \M`). Corrigido com `lambda`
  (`tests/test_drp_windows.py`).
- ⚠️ **Tensão aberta, não resolvida aqui:** a rota de **import** (ADR 0009) segue usando
  `ExportFile` como caminho B. Este ADR não a remove — mudar o import é decisão própria.
