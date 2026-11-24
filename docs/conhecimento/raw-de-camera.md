# RAW de câmera: o BRAW pelo som e o decodificador

> Movido INTEIRO do `CLAUDE.md` do app em 2026-11-20 (o enxugamento). Descoberta nova sobre este assunto entra AQUI;
> o `CLAUDE.md` só ganha uma linha no índice.

#### ⭐⭐ RAW de câmera: o BRAW casa pelo SOM, e isso não custa SDK nenhum (2026-09-21)

**MEDIDO nos 5 BRAW do editor: 5 de 5** acham o OP-Atom que o Avid já processou — e os
cinco já tinham **quadros, transcrição E vetores**. O `ffprobe` lê fps, nº de quadros e TC
do contêiner BRAW (idênticos aos do transcode); só a essência de vídeo não decodifica.

| | medida |
|---|---|
| BRAW × o OP-Atom dele, por PIXEL | **−1,000** (não abre) |
| o mesmo par, pelo SOM do próprio clipe | **+1,000** em 0,4 s |
| impostor: outro take da mesma câmera, no mesmo dia | **+0,033** |

⛔⛔ **Só o `-1` cai para o som.** `-1` é *"não consegui comparar"*; um desacordo de pixel é
uma RESPOSTA, e deixá-la ser resgatada pelo som aceitaria um rewrap de imagem diferente com
o mesmo áudio. É a mesma distinção do clipe de 4 quadros. ⭐ E a procedência acompanha:
`fonte` diz se quem confirmou foi o pixel ou a onda.

⛔⛔ **E o `reel_name` do BRAW é o ROLO, não o clipe:** ele vem `"1"` numa tag de stream e
vencia o nome do arquivo — `B001_03150115_C003.BRAW` virava a fonte `"1"`, e o clipe não era
candidato do próprio transcode. `_nome_da_fonte` recusa nome degenerado (só dígitos, ou 1–2
caracteres). ⚠️ Nos 332 masters deste cache, **nenhum** OP-Atom tem nome degenerado.

⚠️⚠️ **E o material corrigiu a minha régua no mesmo dia.** Eu tinha escrito que *toda* pista
de um dos lados precisava achar par (o PIOR par decide). Isso reprovou um BRAW verdadeiro:
`ch1 +0,789 · ch2 +1,000`, com 547 quadros, TC e duração idênticos. O 0,789 é o transcode
processando UMA pista — exigir que todas sobrevivam é exigir que o transcode seja sem perdas
por canal. ⇒ **o MELHOR par decide**, e quem discrimina é a porteira de metadado (nome,
taxa, nº de quadros, TC): impostor 0,024–0,033 contra 1,000.

#### ⭐⭐ E o que NÃO tem transcode: o decodificador de BRAW, construído (2026-09-21)

Para o RAW que **nunca** foi convertido não há o que reaproveitar, e o pixel é a única
resposta. `decodificadores/` traz o decodificador, e ele **funciona no Windows** — que é
onde este serviço roda, na mesma máquina do Media Composer.

```bash
.\decodificadores\braw\construir.ps1     # MIDL + cl.exe; acha o SDK e o VS sozinho
python tools\conferir_braw.py <X.braw>    # confere com os olhos, num clipe de verdade
```

**Medido nos BRAW 4K do editor:** `frames.extrair_varios` devolve **6 quadros em 0,94 s**
(0,13–0,18 s cada), pela MESMA chamada de sempre — `frames.py` despacha por extensão e o
resto do produto não sabe que houve SDK.

⭐⭐ **O desenho é o do RELINKER, de propósito** (`docs/raw-decoders.md` de lá): helper-CLI
por fabricante, contrato `--file --frame --out --max-width`, achado em runtime, ausência
degradando com elegância. Os dois apps da casa falam a mesma língua, e há teste para isso.
⛔ Binário externo e não binding: licença isolada, um decode que quebra não derruba o
serviço (e o serviço é o painel), e o build fica num lugar só.

⛔⛔ **O SDK é preciso no BUILD; o editor só precisa do RUNTIME** — e o decodificador
procura o runtime onde ele já estiver. ⭐ No Windows do Media Composer ele costuma **já
estar lá**: o plugin AMA de BRAW do próprio Avid instala o `BlackmagicRawAPI.dll`
(conferido nesta máquina). ⛔ Nada do fabricante entra no nosso pacote — e o que o MIDL
gera do `.idl` está no `.gitignore`, porque header é arquivo de desenvolvimento.

⚠️⚠️ **O porte não é de sintaxe, é de API** — quatro diferenças, todas medidas:

| | macOS (RELINKER) | Windows (aqui) |
|---|---|---|
| string | `CFStringRef` | **`BSTR`** (`SysAllocString`) |
| header | vem pronto no SDK | **gerado do `.idl` pelo MIDL**, no build |
| COM | não | **`CoInitializeEx` obrigatório** — sem ele a factory volta nula, calada |
| runtime | `BlackmagicRawAPI.framework` | `BlackmagicRawAPI.dll` + decoders |

⛔⛔ **E o BRAW "as shot" é LOG — o quadro saía LAVADO, sem erro nenhum.** MEDIDO: o mesmo
frame, céu branco pelo SDK contra céu azul pelo `.mp4` que o editor converteu. O clipe vem
em `Blackmagic Design Film` (Color Science Gen 5); o decodificador pede uma gamma de vídeo
antes de decodificar e **diz no stderr** quando não consegue. ⚠️ É o pior tipo de defeito —
decodifica, grava JPEG, sai 0, e faz o modelo descrever *"luz lavada, sem cor"* de um dia
de sol. Só aparece no olho, e é por isso que `tools/conferir_braw.py` existe.

⛔ **`GetClipAttributeList` DERRUBA o processo** (`0xC0000409`, sem uma linha no stderr).
Não insista: que gamma o SDK aceita sai de graça TENTANDO pôr cada uma.

⚠️ **A FERRAMENTA não entra na `frames.ASSINATURA`**, e é decisão: a receita é "JPEG de
768 px no tempo do master", e os dois caminhos a cumprem. Pôr a ferramenta ali invalidaria
os quadros de TODO o cache (118 mídias) para registrar algo que não muda o que sai.

⬜ **R3D, ARRIRAW, Canon e Sony**: o contrato está de pé e o despacho também; falta
construir cada helper — e cada um exige o SDK do fabricante na máquina de quem constrói.
⚠️ No RELINKER eles são **template nunca compilado** (R3D) e **esqueleto com `#error`**
(ARRI). ⚠️ E ARRIRAW é **sequência** (`.arx`, 1 arquivo = 1 frame): sem agrupar, os 602
arquivos de `SAMPLE FOOTAGE/ARRI` viram 602 mídias onde há **um** plano.

Ver o banco, `transversal/raw-de-camera-e-sdk.md`.
