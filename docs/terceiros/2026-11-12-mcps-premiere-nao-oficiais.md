# Dois MCPs não oficiais do Premiere: o que trazem para o Ciclo Assist (2026-11-12)

Pedido do autor: "é sempre bom analisarmos o que cada um traz para ver se tem algo que possamos melhorar no nosso app".
Só leitura: clonados com `--depth 1` fora do SSD, sem instalar nem rodar. O que vem da página ou do README está dito;
o resto foi conferido no código.

## Os dois

**premiere-pro-mcp.com** (repo `leancoderkavy/premiere-pro-mcp`, MIT). A página diz "447 ferramentas", Mac e Windows.
No código: servidor Node; ponte de produção = painel CEP que troca JSON por uma pasta temporária e roda `evalScript`;
via opcional UXP (25.6+) por WebSocket `127.0.0.1:7777` com token. Script livre (`execute_extendscript`,
`send_raw_script`, `evaluate_expression`) DESLIGADO de fábrica (`src/security/capabilities.ts`); toda ferramenta aceita
`expected_project_path`; cada escrita devolve um recibo (`verified` / `committed_unverified` / `requested_unverified`).
~1.500 commits desde 02/2026, ~400 arquivos de teste — mas o próprio registro admite auditoria SEM Premiere licenciado.

**hetpatel-11/Adobe_Premiere_Pro_MCP** (MIT). Também ponte CEP por arquivo (`/tmp/premiere-bridge-<sessão>`, 0700),
painel com Node ligado. ~280 ferramentas atrás de `search_tools`/`invoke_tool`. ⛔ `execute_extendscript` sem trava
(`src/tools/expanded.ts:274`): texto do modelo vira ExtendScript; a proteção é uma frase na descrição.

Nenhum dos dois faz merged clip nem multicâmera (nós fazemos, pelo `.prproj`).

## O que é novo para nós

| eles fazem | nós temos? | vale trazer? |
|---|---|---|
| detecção de cenas nativa: `seq.performSceneEditDetectionOnSelection(ação, áudio, sensibilidade)` (`src/tools/advanced.ts:1556`) | não (temos o `cortes.json`) | sim: medir contra o nosso |
| transcrição pelo UXP: `ppro.Transcript.hasTranscript/exportToJSON/importFromJSON`, `createImportTextSegmentsAction` (`uxp-plugin/transcript-import.cjs:163-229`) | só o `createTranscript/getTranscript` do MCP nativo 27.1 | sim: a NOSSA transcrição no painel Texto (25.6+); exige plugin UXP — decidir se cabe na regra "nada dentro do NLE" |
| posição no histórico de desfazer: `qe.project.undoStackIndex()` (`src/bridge/script-builder.ts:3548`) | não | sim, como recibo depois do portão |
| fila do encoder: `app.encoder.encodeSequence/encodeProjectItem` | pouco | talvez, para a aba Entregar |
| conferir o projeto aberto antes de toda escrita (`expected_project_path`) | parcial (o projeto do turno) | sim, dentro das funções que escrevem no `host.jsx` |
| agulha, Source, seleção, marcadores, subclipe, legendas | já temos | não |

## Armadilhas que eles registram (`docs/host-api-limitations.md`; relato deles, não medição nossa)

- `changeMediaPath` **trava o Premiere** pela ponte CEP no 26.5 (issue #729) — o nosso banco usa essa chamada.
- `exportFramePNG` grava RGBA com alfa NÃO multiplicado: num fade a cor fica, a transparência só no alfa (#771).
- Legendas: nenhuma API estiliza nem lê o texto; dizem que o Export Frame OMITE legenda nas versões recentes — o nosso
  banco mediu que o 27.1 desenha. Reconciliar.
- `app.encoder.isRunning` não existe na maioria das versões; pedido aceito pelo Media Encoder não prova render.
- Efeito presente na cadeia não prova pixel renderizado (#735); nome de efeito por idioma quebra a remoção (#674).
- Ponte por arquivo: qualquer processo do usuário que escreva um `command-*.json` executa ExtendScript. A nossa
  (funções nomeadas, argumentos JSON) evita isso.

## Recomendações (à espera do autor)

1. Medir a detecção de cenas nativa (23.2 e 26) contra o `cortes.json` na mesma mídia.
2. Avaliar importar a nossa transcrição no painel Texto pelo UXP (25.6/26) — depois de decidir se um plugin UXP sem
   interface cabe na regra "nada dentro do NLE".
3. Recibo de desfazer no portão: `qe.project.undoStackIndex()` antes e depois de `cicloOrganizar/cicloEditar/cicloMontar`
   (a posição não diz QUAL ação).
4. Conferir o caminho do projeto aberto dentro das funções que escrevem, contra o projeto do turno.
5. Registrar as armadilhas acima no banco como `hipotese` com a fonte (sobretudo `changeMediaPath` e o alfa do PNG).
