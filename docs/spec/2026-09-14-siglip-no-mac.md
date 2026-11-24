# Busca por frase no Mac mini — o servidor de vetores SigLIP 2

**Data:** 2026-09-14 · **Estado:** código pronto e testado no notebook (sem modelo); falta
instalar e medir no Mac · **Para quem:** a sessão do Claude que vai rodar isto no Mac mini.
Leia antes a spec do Ollama (`2026-09-13-servidor-de-percepcao-mac.md`): rede, energia,
firewall e a regra de "backend HTTP, não MCP" valem iguais aqui.

---

## 1. Por que isto existe, com o número

A aba **Busca IA** do painel responde *"close noturno no consultório"* sobre material que
ninguém decupou. A técnica é a do Premiere 26 e do Resolve 21: um par imagem–texto (SigLIP 2)
põe quadro e frase no mesmo espaço de vetores.

Medido no notebook em 2026-09-14 (`spikes/busca_por_frase.py`, 172 mídias decupadas pelo
`qwen3-vl` como gabarito, onnxruntime só CPU, Media Composer aberto):

| | valor |
|---|---|
| acerto médio (AUC) — frase em português | **0,79** |
| acerto médio (AUC) — frase em inglês | **0,84** |
| melhores atributos | close 0,94 · interior/exterior ~0,90 |
| piores | plano médio 0,54 · dia/noite ~0,70 |
| codificador de imagem · de texto | 152 ms/quadro · 31 ms/frase |
| ⛔ **RAM livre do notebook ao carregar a imagem** | **169 MB, carga 98%** |

⇒ **Decisão do editor, 2026-09-14: a busca por frase mora inteira no Mac.** O notebook tem
telas azuis no histórico com modelo local ao lado do Media Composer, e 169 MB é esse
terreno. A versão quantizada (int8) cabe mas não serve: AUC 0,58.

---

## 2. A forma: igual ao Ollama

```
notebook (serviço Ciclo Assist)                         Mac mini
  cache por UMID ── JPEG 768 px dos quadros ── POST /imagens ──→ siglip_servidor.py :7825
  índice (vetores) ←───────── float32 768-d ──────────────────     onnxruntime CPU
  frase do editor ─────────────────────────── POST /frases  ──→   (não guarda nada)
```

- O Claude não sabe que o Mac existe (não é MCP).
- **O índice mora no notebook**, ao lado do resto do cache, com a receita do servidor em
  `gerador.siglip.json`: mudou o modelo lá, o índice velho cai sozinho aqui.
- O Mac não guarda quadro nem frase, e nunca abre conexão para o notebook.

---

## 3. O que instalar no Mac

O código é **um arquivo**: `servidor_mac/siglip_servidor.py`, deste repositório. Não depende
de nada do produto. Chega ao Mac por cópia (o repositório vive no SSD `SSD`, que o Mac
monta como `/Volumes/SSD`).

```bash
python3 -m venv ~/siglip-venv
~/siglip-venv/bin/pip install numpy onnxruntime tokenizers pillow
~/siglip-venv/bin/python siglip_servidor.py --baixar      # ~926 MB, confere SHA-256
~/siglip-venv/bin/python siglip_servidor.py               # escuta em 0.0.0.0:7825
```

- Modelos em `~/siglip-modelos` (ou `--modelos` / `SIGLIP_MODELOS`, pode ser o SSD externo —
  com a mesma regra do Ollama: **volume desmontado = recusar subir**).
- ⚠️ Os três arquivos têm SHA-256 fixado no código. Hash diferente não carrega: seria outro
  modelo com o mesmo nome, e o placar medido deixaria de valer.
- ⚠️ **CPU, não CoreML.** Medido no `_PRODUCAO-V`: o provider do CoreML aceita 542 de 719 nós
  e falha na execução.
- **Memória:** os dois codificadores somam ~1,3 GB carregados. Com o `qwen3-vl:8b` do Ollama
  carregado (~6–7 GB), cabe nos 16 GB — **medir** (`memory_pressure`, `vm_stat`) com os dois
  quentes e dizer o número.
- Pôr no mesmo `iniciar`/`parar`/`status` do Ollama. O `status` ganha:
  ```
  siglip .................. escutando em 0.0.0.0:7825 · receita siglip2-base-patch16-256
  teste pelo IP da rede ... ok     ← curl no IP, não em localhost (a mesma armadilha)
  ```
- Firewall do macOS: aceitar conexões para o `python3` do venv. Negado = o notebook só vê
  timeout.

---

## 4. O contrato (não mude sem avisar o notebook)

| pedido | corpo | resposta |
|---|---|---|
| `GET /saude` | — | `{ok, receita, limites}` |
| `POST /imagens` | `{"imagens": [jpeg base64, … até 16]}` | `{ok, dim: 768, quantos, vetores, ms, receita}` |
| `POST /frases` | `{"frases": [texto, … até 32]}` | idem |

- `vetores`: **float32 little-endian em base64**, `quantos × 768`, já **normalizados** (produto
  escalar = parecença). O notebook lê com `numpy.frombuffer(..., "<f4")`.
- Pedido ruim → `400` com a frase em português; rota que não existe → `404` (caminho exato);
  cliente fora da rede local → `403`.
- ⛔⛔ **O pré-processamento É o modelo** (e está no código, não mude): 256×256 **bicúbico sem
  preservar proporção**, `/255`, média e desvio 0,5; texto em minúsculas, `<eos>` no fim,
  `<pad>` (id 0) até 64 tokens; saída `pooler_output`.

---

## 5. Aceitação — medida DO NOTEBOOK, combinada antes

```powershell
python spikes/busca_por_frase.py --mac http://192.168.1.4:7825
```

O spike manda os MESMOS quadros (os JPEG do cache) e as MESMAS 22 frases, e calcula o placar
com o mesmo gabarito de 172 mídias.

- ✅ **Passa** se a AUC média ficar a **±0,03** do notebook (0,79 pt / 0,84 en) — o modelo é o
  mesmo; diferença maior quer dizer pré-processamento diferente (o Mac usa Pillow para
  redimensionar, o notebook usou ffmpeg).
- ⚠️ E diga o tempo por quadro **com a rede** e com o Ollama carregado ao lado.
- ⛔ Não vale ajustar frase ou gabarito depois de ver o número.

---

## 6. O que devolver para o notebook

1. A saída do `status` com a linha do SigLIP e o teste pelo IP.
2. A memória com Ollama e SigLIP quentes ao mesmo tempo.
3. `curl http://<IP>:7825/saude` do Mac e do notebook.
4. Qualquer falha e como apareceu — o sintoma exato vale mais que o conserto.

Daqui, o notebook roda a aceitação (Seção 5) e só então o índice entra no produto.

---

## ⭐ Retorno do Mac (2026-09-14, manhã)

**Estado:** servidor no ar em `http://192.168.1.4:7825` (Wi-Fi, en1). Falta a aceitação do
notebook (Seção 5).

### Onde ficou (tudo no SSD PRODUCAO-G; o disco interno do Mac tem 15 GB livres)

| | |
|---|---|
| código | `/Volumes/PRODUCAO-G/CICLO ASSIST/siglip-server/siglip_servidor.py`: cópia byte a byte de `servidor_mac/` (sha256 `8ce0c1ba…`). ⚠️ Mudou aqui, copie de novo lá. |
| modelos | `siglip-server/modelos/`: **copiados do `_PRODUCAO-V`, não baixados**. Os três SHA-256 batem com os fixados no código. |
| ambiente | `siglip-server/venv/`: Python 3.11 do Homebrew (o do sistema é 3.9), onnxruntime 1.30.0, numpy 2.4.6, tokenizers 0.23.2, pillow 12.3.0 |
| scripts | `llm-server/iniciar|parar|status.command` agora ligam, param e mostram os dois. O SigLIP tem os próprios scripts em `siglip-server/`. |
| modelos do `_PRODUCAO-V` | todos copiados para `CICLO ASSIST/modelos-PRODUCAO-V/` (7 GB: SigLIP, whisper large-v3-turbo, VAD, diarização, Qwen3-8B MLX), porque o SSD volta ao Windows |

### 1. `status`

```
siglip .................  escutando em *:7825 · receita siglip2-base-patch16-256-ONNX
teste pelo IP da rede ..  ok  http://192.168.1.4:7825
memória do siglip ......  1411 MB (PID 1717)
```

⚠️ Na primeira versão do `status`, a memória vinha do RSS e mostrava **0,02 GB** com o modelo
carregado: o macOS comprime as páginas paradas. Usa-se `footprint`.

### 2. Memória com os dois quentes (`qwen3-vl:8b-instruct` a 100% GPU, ctx 12288)

| | pressão | livre |
|---|---|---|
| só Ollama | normal (nível 1) | 27% |
| Ollama + SigLIP (depois de codificar 12 quadros e uma frase) | ⚠️ **atenção** (nível 2 de 4) | 16–18% |

Swap em uso: 1,9 de 3 GB. Memória presa (a GPU do Ollama): 9,2 GB. **Cabe, mas sem folga.**
Não medi se a decupagem fica mais lenta com o SigLIP carregado. Se ficar, o remédio é não
ter os dois quentes ao mesmo tempo (a fila do notebook já roda uma tarefa por vez; o
`OLLAMA_KEEP_ALIVE` é 30 min).

### 3. `/saude`

Do Mac, pelo IP da rede: `{"ok": true, "receita": {… "visao_sha256": "f5cb16728a704703",
"texto_sha256": "80954edffdc68959", "lado": 256, "tokens": 64, "dim": 768 …}}`.
⬜ **Do notebook: falta** (`curl.exe http://192.168.1.4:7825/saude`).

### Medidas extras, feitas sem material de cliente

- ⭐ **Texto idêntico ao `_PRODUCAO-V`:** as 7 frases do `prompts.npz` dele (calculado com o
  `AutoTokenizer` do `transformers`) saem do servidor com **cos 1,00000**. O tokenizador cru
  (minúsculas, `<eos>`, pad 64) confere.
- ⚠️ **Imagem: Pillow × ffmpeg não é idêntico.** O mesmo JPEG, pelo servidor (Pillow
  bicúbico) e por ffmpeg `scale=256:256:flags=bicubic` no mesmo ONNX: **cos 0,976 / 0,989 /
  0,997 / 0,997** em 4 imagens. É a diferença que a Seção 5 previu (redimensionamento com e
  sem antialias). A AUC decide; se passar de ±0,03, é aqui que se olha primeiro.
- Tempo: **12 quadros em ~0,8 s** no servidor, ~66 ms/quadro (notebook: 152). Ida e volta
  pelo IP do próprio Mac: +7 ms. Frase: 35–100 ms. ⬜ Com a rede do notebook: falta.
- Sanidade da classificação por frase (papéis de parede do macOS): paisagens dão *outdoor* >
  *indoor*, e o padrão azul abstrato dá o maior valor em *an abstract blue pattern* (0,153)
  e em *padrão abstrato azul* (0,114). n = 4: **não é placar**.

### Falhas e como apareceram

1. O Ollama estava **parado** ao chegar (a fila da noite terminou às 23:29; último pedido às
   08:14; nenhum erro no log, e o Mac não tinha reiniciado). Religado pelo `iniciar`.
   ⚠️ Nada religa o servidor sozinho se ele cair.
2. `status`: `"$ESCUTA·"` imprimia `�`: o bash leu o primeiro byte do `·` como parte do
   nome da variável. Conserto: `${ESCUTA}`.
3. RSS enganoso (item 1 acima).

---

## ✅ Aceitação RODADA do notebook (2026-09-14, tarde) — PASSOU

```
python spikes/busca_por_frase.py --mac http://192.168.1.4:7825
```

| | notebook (CPU, 2026-09-14 manhã) | **Mac pela rede** |
|---|---|---|
| AUC média pt | 0,79 | **0,79** (±0,00) |
| AUC média en | 0,84 | **0,84** (±0,00) |
| tempo por quadro | 152 ms | **66 ms** (1.088 quadros em 72 s) |
| memória do processo AQUI | ⛔ 169 MB livres no sistema, carga 98% | ⭐ **43 MB** no processo, 6,1 GB livres, carga 61% |

Mesmos 1.088 quadros, mesmas 22 frases, mesmo gabarito de 172 mídias. A receita devolvida
pelo `/saude` é a fixada (`visao_sha256 f5cb1672…`), e o `siglip_servidor.py` do Mac é o
byte a byte deste repo (sha256 `8ce0c1ba…`, conferido daqui).

- ⭐ **A diferença Pillow × ffmpeg não moveu o placar.** A spec previa que, se a AUC saísse
  de ±0,03, se olharia primeiro para o redimensionamento (cos 0,976–0,997 entre os dois).
  Saiu em ±0,00, atributo a atributo — então o pré-processamento do servidor **serve como
  está**, e o notebook não precisa mandar quadro já redimensionado.
- ⚠️ **A rede não pesou no que dá para medir aqui:** 66 ms/quadro pela rede é o mesmo número
  do Mac medindo a si mesmo (66 ms). O lote de 16 imagens dilui a ida e volta.
- ⚠️ **Não medido:** com o Ollama QUENTE ao lado (a spec pedia). A fila de decupagem estava
  parada. Quando as duas coisas rodarem juntas, medir de novo — o Mac já acusou pressão de
  memória "atenção" com os dois carregados.
- ⛔ Nada foi ajustado depois de ver o número: frases e gabarito são os da manhã.

⇒ **O índice pode entrar no produto** (estágio `siglip` no cache, Seção 5 do handoff).
