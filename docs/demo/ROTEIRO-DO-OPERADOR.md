# Roteiro do operador: sync + subclipes + separar falas, pelo chat do Ciclo Assist

> O mesmo roteiro que o piloto rodou em 2026-10-29 (tabela em `docs/plano/2026-10-23-ensaio-da-demo.md`), agora com o
> autor operando. Os pedidos são os prompts FIXOS desta pasta, que também são os atalhos do menu ☰ do Assistir:
>
> | atalho no ☰ | arquivo |
> |---|---|
> | Sync + subclipes da D02 (Órbita) | `prompt-1-sincronizar.txt` |
> | Separar falas da C07 | `prompt-2-separar-falas.txt` |
>
> ⚠️ Os atalhos moram em `%LOCALAPPDATA%\CicloAssist\atalhos.json`, desta máquina. Em outra máquina, salvar de novo
> pelo ☰ ("Salvar como atalho…") colando o texto dos arquivos.

## Antes de subir ao palco (sem plateia)

1. **Projeto novo com a D02 crua.** Criar no MC (1080p/23,976), **fechar o MC** (ou File ▸ Close Project), copiar
   `D02\CAM A.avb` e `D02\SOM DIRETO.avb` para `Documents\Avid Projects\<projeto>\D02\`, e só então abrir o projeto.
   ⛔ Copiar com o projeto aberto não serve: as bins abrem, mas o MC não as registra no projeto, e o Órbita não acha a
   pasta D02 (medido em 29/10, banco `avid-panel-sdk/windows.md`).
   Fonte limpa das duas bins: `Documents\Avid Projects\ORBITA - APRESENTACAO\D02\`.
2. **Abrir o Ciclo Assist** (`ABRIR-APP.bat`) depois do projeto. Conferir no topo: "Media Composer 2024.6 · <projeto>".
3. Na barra do Assistir: **Sonnet 5.5** e o chip **automático** (sem cartão; com "perguntar" aparece um cartão por
   ação e é preciso clicar em permitir).
4. As transcrições da C07 estão no cache desta máquina (o passo 2 não roda reconhecimento de fala). ⛔ Não apagar o
   cache antes da apresentação.
5. Deixar o Explorer aberto em `D:\MIDIAS DE TESTES\1 PRODUCOES\PRODUCAO-A\ROTEIRO\`, ao lado do Assist.

## Ao vivo

| # | gesto | o que aparece | tempo medido |
|---|---|---|---|
| 1 | ☰ → **Sync + subclipes da D02 (Órbita)** → enviar | "sincronizar com o órbita · D02" com a barra; no MC nascem `D02 SYNC ORBITA` e as bins de cena | **~2 min** |
| 2 | ☰ → **Limpar conversa** → clicar de novo em "Limpar mesmo?" **em até 6 s** (ou digitar `/clear` + Enter) | "Conversa limpa." | — |
| 3 | Na bin **C07**: clicar num VAZIO da bin, Ctrl+A, e arrastar pelo **ícone** de um subclipe até o chat | chip "10 do Avid" (verde-água) | — |
| 4 | Arrastar `PRODUCAO-A CENA 7 roteiro.docx` do Explorer até o chat | "10 do Avid · 1 arquivo" (o arquivo em violeta) | — |
| 5 | ☰ → **Separar falas da C07** → enviar | consulta o método, estrutura o roteiro, "Ouve o take" ×10, "Separa as falas da cena C07" | **~2 min** |

Resultado esperado (29/10):
- Passo 1: 1 câmera (CAM A, 26 clipes), 24 de 26 casados, 2 clipes de câmera sem som; `CENAS/C04` 16 e
  `CENAS/C07` 10 subclipes, nomes `C07_P02_T001`.
- Passo 5: bin `C07 FALAS`, 17 falas + 1 variante; de fora P02_T001 (só claquete), P02_T001.1 (sem som direto) e
  P03_T002 (abortado; entram as falas 1 a 4).
- A conferência pode reprovar o pedido uma ou duas vezes antes de passar ("o trecho engole outra fala"): é o produto
  funcionando, não erro. O painel mostra.

## Cuidados de mão

- Item de bin do MC: clicar no **ícone**, nunca no nome (o nome abre a caixa de renomear).
- Não clicar num item e já arrastar: vira duplo clique. Selecionar, soltar, e arrastar.
- Plano B: a bin `C07 FALAS` e o `D02 SYNC ORBITA` do ensaio de 29/10 estão no projeto `ASSIST TESTE 29-10`.
