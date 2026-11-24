# Importar para o NLE com o piloto de prontidão (proposta, 2026-11-15)

Pedido do autor: *"nada impede da operação da carta ter ajuda de um piloto para lidar com possíveis erros. essa janela
por exemplo pode ser prevista como possibilidade pois ela pode aparecer em casos como braw que o usuário não instalou o
plugin da black magic… o media composer se lidar com mídias em link também pode ter cenários onde um arquivo não é
suportado"*.

## O que já está feito (medido no Premiere 27.0, Mac)

- A mídia vai em LOTE (`importFiles(lista)` por bin): 259 arquivos em 2,4 s.
- A sombra `._` do exFAT não vai (ignorada, dita); documento (pdf, doc, planilha, compactado…) não vai (recusado,
  "não é mídia", no relatório e no diário).
- O que o Premiere não importa volta pelo NOME na lista do `cicloImportar`.
- Se a importação não volta (o aviso "File Import Failure" SEGURA a resposta até o OK), a Carta diz o aviso e o gesto:
  fechar com OK e importar de novo (o que entrou não se repete).
- O Premiere não grava a falha em arquivo nenhum (banco `plugins/premiere-cep/api-extendscript.md`): quem sabe o que foi
  recusado é a nossa lista.

## A proposta: três camadas

### 1. Prevenir o que dá para saber antes (sem piloto)

- **BRAW sem o importador da Blackmagic**: o importador mora na pasta comum
  `/Library/Application Support/Adobe/Common/Plug-ins/7.0/MediaCore/BlackmagicRawPremiereImporter.bundle` (Windows:
  `C:\Program Files\Adobe\Common\Plug-ins\7.0\MediaCore\`, a medir). Lista com `.braw` e sem o importador ⇒ os `.braw`
  não vão, e a Carta diz "falta o plugin da Blackmagic (Blackmagic RAW for Adobe Premiere)".
- O mesmo desenho para os outros RAW quando aparecerem (R3D e ARRIRAW o Premiere lê nativo; Canon/Sony: medir).

### 2. O piloto de prontidão durante a importação (Premiere)

Enquanto a chamada de importação não volta, o serviço olha as janelas do Premiere (`piloto` / `cicloassist/piloto`):

- aparece **"File Import Failure"** ⇒ foto, clique no **OK** (botão único, aviso informativo — cabe na regra do agente do
  piloto: lista fechada, OK só quando é a única escolha), e a chamada volta sozinha;
- o que foi recusado já vem na lista do `cicloImportar` (não é preciso ler a janela); o motivo provável vai junto
  ("o Premiere não lê este arquivo — formato sem plugin?");
- janela DESCONHECIDA ⇒ o **agente do piloto com o Sonnet** (`cicloassist/piloto/auxilio.py`, autor 2026-11-15: "ele
  deve usar um agente sonnet para lidar com a janela caso seja desconhecida"): o modelo olha a foto e sugere, o CÓDIGO
  decide (lista fechada de botões; OK só quando é a única escolha; texto que fala em apagar, substituir ou falha vira
  pergunta ao editor; o mesmo clique não se repete; teto de consultas por operação). Só o que o agente não resolve para
  e é dito ao editor.
- ⚠️ É o piloto mexendo na tela do editor: a borda/aviso de "o Ciclo Assist está operando" e devolver o foco ao fim.

### 3. Media Composer (link AMA)

O MC tem os seus avisos para arquivo que o AMA não lê (BRAW sem o plugin AMA da Blackmagic). O piloto do MC já resolve
diálogos conhecidos (`avid/socorro.py`, `piloto/auxilio.py`). Falta MEDIR: linkar um BRAW sem o plugin AMA (numa máquina
de teste) e catalogar a janela que aparece, antes de escrever o tratamento.

## Decisões do autor (2026-11-15)

"tudo certo com o piloto": as três recomendações valem — o piloto fecha o aviso sozinho e conta depois;
BRAW sem o plugin não vai (dito); a camada 3 espera a medição.

## As perguntas que foram feitas

1. Na camada 2, o piloto clica OK **sozinho** e conta depois, ou **pergunta** ao editor antes? (Recomendo sozinho: é um
   aviso informativo com um botão só, e o que ele diz vai para o relatório.)
2. BRAW sem o plugin (camada 1): **não mandar** os `.braw` e dizer, ou mandar mesmo assim? (Recomendo não mandar: o
   resultado é o mesmo, sem a janela.)
3. A camada 3 depende de uma máquina sem o plugin AMA de BRAW: há uma, ou desinstalamos o plugin temporariamente aqui?
