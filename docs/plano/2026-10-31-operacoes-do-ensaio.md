# As operações do ensaio — do que o Opus pilotou em 31/10 ao que o Ciclo Assist faz sozinho

Pedido do autor (31/10, noite): repetir o ensaio **puramente pelo Ciclo Assist, com o Sonnet 5.5**, e medir quanto tempo
e quanto consumo se gasta (ou economiza) contra esta sessão. Regra do plano `2026-10-31-o-assist-operador.md`: o fluxo é
COMPOSIÇÃO de operações genéricas com nome; nenhuma regra só para o ensaio. Cada operação abaixo é uma ferramenta MCP
(`mcp/ferramentas/`), com `escreve=` declarado, conferência ANTES do cartão e a medida que a sustenta.

## A linha de base (esta sessão, Opus 5.5 pilotando, 2026-10-31)

| | |
|---|---|
| do "pode pilotar" do roteiro limpo (Resolve aberto) até as bins por cena | ~19:42 → 20:35 ≈ **55 min** (com a investigação do 2º crash dentro) |
| a sessão inteira (bug + 2 causas + ensaio + passo 8) | ~18:55 → 20:45 ≈ **1 h 50 min** |
| consumo | janela de 5 h da assinatura: **6 % → ~70 %**; contexto: ~75 % de uma janela |
| ⚠️ | contas da linha de status, não de API: comparar com a MESMA medida na repetição |

## As operações, na ordem do fluxo

| # | operação | entra | faz | travas (cada uma paga com erro hoje) | já existe |
|---|---|---|---|---|---|
| 1 | `gerar_midia_de_teste` | receita do laboratório | `python -m lab.multicam <receita>` (processo filho; receita por NOME) | nunca por cima: pronto = reaproveita, `refazer` = pasta nova | ✅ **ferramenta** (`cicloassist/laboratorio.py`, 2026-11-01; M06 real reaproveitado) |
| 2 | `abrir_programa` | resolve/avid | abre e espera a API | Resolve: `fuscript` perdeu a corrida → reabrir (14 s); MC: FOCAR antes da foto, aviso de teclado → "Don't warn me again" | ✅ `abrir_programa` (Resolve); MC no piloto |
| 3 | `converter_para_opatom` | projeto Resolve, vídeos, pasta | preset nosso APAGADO e reinjetado, conferido (`mxf` + modo 0) e só então o codec; render direto numa pasta numérica NOVA | divergiu → PARAR (nunca forçar o codec: nasceu o `00090250`) | ✅ **ferramenta** (`cicloassist/resolve_opatom.py`, 2026-11-01): provada 2× no Resolve 19.1.4 (a 2ª com o preset já importado), 12 MXF em ~5 s, TCs = gabarito, som 24 bits; não apaga a fila nem usa a timeline do editor |
| 4 | `criar_projeto_avid` | nome, formato | Select Project → New Project → nome → Create | posição medida NESTA abertura; o formato já vinha certo | 🟡 piloto (bancada mede o 25.6) |
| 5 | `importar_masters_opatom` | MXF, bin, tape? | AAF de masters + `ImportFile`; tape = nome do clipe ou o rolo | `nao_indexados` (MXF mais novo que o `.mdb` = recusa) e `mobs_sem_offset` (recusa) | ✅ **ferramenta** (`cicloassist/avid/importar_opatom.py`, 2026-11-01): foco no MC para indexar (0,6 s), espera os masters CHEGAREM à bin antes do `CloseBin` (1,8 s; fechar colado gravou a bin vazia e derrubou o MC na 1ª prova), offsets exigidos de cada master; T01 online no Source a 10:00:05:00 |
| 6 | `montar_som_direto` | WAVs, bin, taxa | `autorar_masters(fps, drop)` sobre CÓPIAS dos WAV | `variante_trocada` dito; nunca `LinkFile` | ✅ **ferramenta** `montar_som_direto` (`cicloassist/avid/som_direto.py`, 2026-11-01): o motor do DLPC pelo Python dele, taxa/drop do projeto aberto, cópias em `_para_consolidar`, bin NOVA (grava ao lado + `OpenBin`); 4 masters em 3,3 s com os Starts do gabarito (10:00:03, :30, :58, 10:01:30), T01 no Source 24:00 |
| 7 | `consolidar_som` ⇒ ✅ **SUBSTITUÍDA** por `som_direto_gerenciado` (6+7 em uma, abaixo); o consolidar pela tela foi medido (banco `protocolos/msm`) mas exige um clique dentro da bin | bin | Clip → Consolidate/Transcode, D:, "Delete original" (CONFERIR o estado pela foto antes de clicar) → mover `MXF\1` para pasta numérica NOVA terminando em 1 → foco | pasta já indexada não reescaneia | 🟡 piloto (sem RPC) |
| 8 | `salvar_tudo` | — | foco num vazio da TIMELINE + Ctrl+S | sem isso bin/pasta escrita por fora não aparece; ⛔ só salva se houver algo MODIFICADO ("Save All Bins" cinza sem nada sujo — medido 01/11) | ✅ `salvar_tudo` (`cicloassist/avid/salvar.py` + `cicloassist/piloto/`): o ponto vazio da timeline pelo localizador (foto → `claude -p` → cruz conferida), prova pela data do `.avp`; 12 s e US$ 0,02 (1ª), ~US$ 0,008 com o ponto guardado |
| 9 | `sincronizar_com_o_orbita` | bins câmera/som, nome | o motor do Órbita (híbrido) | `SEQUERNCE_FORMAT_TYPE` da tabela (25p = 16) | ✅ (pelo chat, Sonnet 5.5, 31/10 21:46: 1 turno, 26 s) |
| 10 | `subclipar_por_cena` | a sequência, modelo de nome | o Órbita lê a claquete do NOME do WAV, apara, grava `CENAS/Cxx.avb` | arrastar pede o Assist por cima; via API dispensa o arrasto | ✅ `sincronizar_com_o_orbita(subclipes=por_cena)` no mesmo pedido (31/10) |

## O que medir na repetição
- Tempo de parede por operação e do fluxo inteiro; a janela de 5 h antes e depois; o contexto do turno.
- Quantas vezes o modelo perguntou, errou de ferramenta ou repetiu um passo (o Sonnet é o editor de verdade aqui).
- A prova de cada passo é a mesma desta sessão: master toca, sync = gabarito (+50 quadros nas 4), `02_01_001` = TAKE 4.

## Pendências que a repetição herda
- iXML/bext (claquete do METADADO): o laboratório não grava, o Órbita não lê, o banco não tem — decidido para depois.
- O reel do Resolve por opção de projeto (`SetSetting`?): não achado; a reserva (tape no AAF) está feita.
- Nome de subclipe: `%{cena}` dá `01`, sem "C" — não é prioridade (autor).

## ⭐ 2026-11-01 — as operações 6 e 7 viraram UMA: `som_direto_gerenciado` (ideia do autor)

WAV → um OP-Atom por canal pelo ffmpeg (TC do bext, edit rate do projeto) → costura (`midia/opatom_costura.py`, cópia
do laboratório) → pasta NOVA `MXF\AAAAMMDD…1` → a importação da op. 5 com a FITA criada no AAF e a conferência de
online pela API (`GetMobInfo`, coluna `Offline`). Provado no MC 2024.6: 4 WAV do M06 → 4 masters gerenciados em
~24 s, Tape = o nome do WAV, Starts = o gabarito, PCM 24, toca. Sem consolidar e sem clique. `montar_som_direto`
(AMA) continua para quem quiser o link. ⚠️ Não vão ainda: bext/iXML além do TC; drop-frame recusado (não medido).

## ⬜ Frente separada — a ponte de comandos injetada no MC 24.6 (pergunta do autor, 2026-11-01)

O 24.6 não tem `DoCommand`, `MakeActiveWindow`, `GetListOfWindows`, `StartPlay`/`StopPlay` nem `SetPosition`. Uma
ponte injetada (Frida pelo REA, já medido no 24.6 para o arrasto) que chame o despachante interno de comandos tiraria
o clique de salvar, fechar projeto, ativar janela e tocar. Ressalvas: comando que abre diálogo (1810, Consolidate)
continua abrindo o diálogo; Frida em produção é pesado (banco: plano B); o exe de 59 MB não abre no Ghidra.
Investigação própria com o REA, antes de decidir.
