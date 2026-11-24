# Aula (2026-11-19, 19h): o app do Claude converte, importa, sincroniza e corta por cena

O Ciclo Assist trabalha **sem janela**: o app do Claude chama as ferramentas dele por uma ponte local (`edicao`). A turma
vê o chat do Claude, o Resolve e o Media Composer.

## Antes da aula (5 min)

1. **Feche** o app do Ciclo Assist, o Resolve, o Premiere e o Media Composer (um programa por vez, quem abre é o Claude).
2. No terminal, na pasta do Ciclo Assist:
   ```
   .venv-win\Scripts\python tools\servico_sem_janela.py iniciar
   ```
   Tem de dizer `no ar em … s: serviço … (7824), Sincronizar … (7817)`. (`estado` confere; `parar` desliga.)
3. Abra o **app do Claude**. Em `+ › Conectores` deve aparecer **edicao** (17 ferramentas: as do ensaio, as de separar falas e o aguardar_operacao). Modelo: Sonnet 5.5; modo
   **Auto** (sem pedir permissão a cada ferramenta).
4. A mídia está em `Desktop\DIARIA 01` (CAM 1 = 4 vídeos ProRes; SOM DIRETO = 4 WAV com cena/plano/take no nome:
   C1 P1 T001, C1 P1 T002, C1 P2 T001, C2 P1 T001). Saiu do laboratório (`M06_4TOMADAS` + o som da `M06_CLAQUETE`).
5. Use nomes de projeto NOVOS (os ensaios usaram `ENSAIO AULA`, `ENSAIO AULA 2`, `ENSAIO AULA 3`).

## O pedido (colar no chat)

> Na pasta %USERPROFILE%\Desktop\DIARIA 01 está a mídia bruta da diária de hoje: a câmera em CAM 1 e o som direto
> em SOM DIRETO. Converta os vídeos para OP-Atom no DaVinci Resolve (projeto AULA), feche o Resolve, abra o Media
> Composer no projeto AULA, importe a câmera numa bin CAMERA D01 e o som numa bin SOM D01, sincronize e faça os
> subclipes por cena. No fim, salve tudo e me diga o que ficou em cada bin.

## O que esperar (ensaio 3, 2026-11-19 de manhã, SEM nenhuma mão)

| passo | tempo |
|---|---|
| abrir o Resolve | 15 s (83 s quando ele abre "mudo": o serviço o reabre sozinho) |
| converter (4 vídeos → OP-Atom) | 10 s |
| fechar o Resolve | 11 s |
| abrir o Media Composer, criar o projeto, aviso de teclado e de volume | ~70 s |
| importar câmera · som | 6–12 s · 8–16 s |
| sincronizar + subclipes por cena | 26–51 s |
| salvar | 14 s |

Resultado (iguais nos ensaios 2 e 3): CAMERA D01 (4), SOM D01 (4), D01 (a sequência sincronizada, sem órfãos),
CENAS › C01 (3 subclipes: T01, T02, T03) e C02 (1: T04). **5 a 6 minutos** do envio ao relatório.

## Se algo acontecer

- **Aviso de teclado** ao abrir o Media Composer: o piloto responde "Don't warn me again" sozinho.
- **"This volume has not yet been mounted…"** ao entrar no projeto (apareceu nas TRÊS rodadas, em todo projeto novo): o piloto clica
  "Mount All Volumes" sozinho (provado no ensaio 3). Se ainda assim o Claude pedir "Uso do computador", clique
  **Recusar**, clique você em **Mount All Volumes** e escreva no chat "já montei, pode continuar".
- **"continua rodando… chame aguardar_operacao"** no chat: é normal. O app do Claude desiste de uma ferramenta em
  ~1 min; a ponte responde e o Claude espera o resultado.
- ⛔ Não clique no app do Claude nem no Media Composer enquanto o cursor estiver se mexendo sozinho (o piloto está
  criando o projeto). Mexer no mouse PAUSA o piloto (borda âmbar); F12 para.
- Depois da aula: `tools\servico_sem_janela.py parar`. Para tirar a ponte do app do Claude, a configuração anterior
  está em `%LOCALAPPDATA%\Claude-Data\claude_pzs8sxrjxfjjc\claude_desktop_config.json.antes-da-aula-20261119-072909`.
