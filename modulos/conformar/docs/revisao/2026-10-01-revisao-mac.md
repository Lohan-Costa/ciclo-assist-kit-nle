# Revisão de código da sessão no Mac — 2026-10-01

Escopo: tudo o que mudou na primeira sessão no macOS (`e662992..ed13334`, 12 commits): caminhos do
Windows lidos no Mac, o `ATUALIZAR.command`, a casca no Electron 36, o `endFrame` exclusivo, os
marcadores na forma do Resolve 21, as transições no Atualizar e o título pelo AAF. Feita com o autor
ausente, a pedido dele ("bateria de revisão de código para buscar bugs ou inconsistências").

**Método:** `/code-review high e662992..HEAD` (10 achados). Cada achado foi conferido no código antes
de mexer; um deles foi MEDIDO no Resolve em vez de suposto. O que procedia foi corrigido com teste que
falha no código antigo, e o caso real (U03 do autor) foi refeito e importado no Resolve 21 no fim.

**Estado:** suíte 43/44 no Mac (o 44º é mídia gerenciada que só existe no Windows). O U03 com o código
final, importado no Resolve 21.1: contagem prevista nas 17 trilhas, o marcador da velocidade em 9697,
os 5 cross-fades do take trocado mantidos. Nada foi testado no Windows nem no Media Composer.

---

## Achados

| # | Onde | O que | Veredito | O que foi feito |
|---|---|---|---|---|
| 1 | `atualizacao.py` | o fim do plano novo usado nas transições conta quadros da FONTE, não da timeline | **não procede** | a casca insere a 100%: o plano ocupa `fim − início` quadros na timeline, que é a geometria certa. Ficou um comentário |
| 2 | `atualizacao.py` | tirar/acrescentar transições comparavam a posição ANTIGA com o DRT já movido: depois de um ripple, a que o editor tirou não saía; a que mudou de tamanho ficava EM DOBRO | **procede** | o reescritor devolve um rastro (`aplicar(rastro=…)`) de onde cada transição foi parar; as do editor são comparadas na posição nova |
| 3 | casca `main.js` | a conferência de tamanho pareava pelo índice do que a API DEVOLVEU; com mais itens que pedidos, a casca caía DEPOIS de importar e inserir | **procede** | percorre os pedidos; teste novo (falha no antigo: `ok: false`) |
| 4 | `atualizacao.py` | a transição que o COLORISTA tirou voltava, se o editor a mantinha | **procede** | não volta; é avisada ("não foi reposta; conferir"). As do colorista (fora da versão antiga) nunca são tocadas |
| 5 | `atualizar.ps1` | o app antigo era encerrado DEPOIS do `cargo build`; no Windows o .exe aberto fica travado e a compilação falhava antes | **procede** | encerrar o app e o serviço antigos vem ANTES da compilação (e no `ATUALIZAR.command`, por simetria) |
| 6 | `dev.sh`, `dev.ps1` | exigir 3.12 só na CRIAÇÃO deixava o venv 3.11 de antes em uso, com o numpy velho | **procede** | o venv existente abaixo de 3.12 é recriado; o `ATUALIZAR.command` recusa com instrução |
| 7 | `atualizacao.py` | os cortes que seguram a transição vinham de TODOS os planos novos, inclusive os sem mídia nesta máquina | **procede** | a mídia é buscada antes de reescrever; só o plano que vai entrar segura o corte |
| 8 | `reescrever.py` | o meio-quadro "× 2" dos marcadores do 21 só fora medido a 23,976; as duas formas eram aceitas em qualquer campo | **metade** | MEDIDO a 24, 25 e 29,97: é × 2 em qualquer taxa (refutado). As formas agora só no campo delas (19 no 1, 21 no 2) |
| 9 | `titulos/avid.py` | com MQP sem caixas, o título sumia mesmo com o texto lido; "Avid Title Tool" virava "… Legacy" | **procede** | cai para o texto com o estilo padrão; o titulador é o nome da operação |
| 10 | `writer.py`, `banco_midias.py`, `mcapi.py` | a regra do caminho de forma Windows copiada em três lugares; leitura dupla do DRT na conferência | **procede** | uma função só (`media/safepath.forma_windows`); a conferência das transições virou uma passada só |

## O que muda para o autor

- **Transições no Atualizar:** a que você (colorista) tirou não volta, e aparece como "conferir". Os dois
  fades do título "PRODUCAO-A" no U03 aparecem assim porque a timeline de trabalho daquele teste veio
  do Importar antigo (sem o título); reimportando a v01, eles vêm com o título.
- **Windows:** o `ATUALIZAR.bat` agora fecha o aplicativo antes de compilar. Conferir lá (item da lista
  "conferir no Windows" do handoff).

## Fora do escopo, visto de passagem

`pyflakes` aponta três avisos ANTERIORES a esta sessão: `reescrever.py:128` (`tipo` sem uso),
`mcapi.py:92` (`global _carregou_em` sem atribuição), `relink.py:32` (`chave_mob` importado sem uso).
