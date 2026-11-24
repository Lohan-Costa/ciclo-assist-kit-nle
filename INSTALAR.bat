@echo off
rem ===========================================================================
rem  Ciclo Assist - instalar.  DE DUPLO CLIQUE NESTE ARQUIVO.
rem
rem  Este arquivo e' so' a porta de entrada. O trabalho esta' em instalar.ps1.
rem
rem  Por que existe um .bat, se ja' ha' um .ps1:
rem  duplo clique num .ps1 NAO o executa. O Windows abre o Bloco de Notas, ou
rem  recusa com "execucao de scripts desabilitada neste sistema" - a politica
rem  padrao (Restricted) bloqueia. O -ExecutionPolicy Bypass abaixo vale so'
rem  para esta chamada: nao muda configuracao nenhuma da maquina.
rem
rem  Este arquivo e' proposital e integralmente SEM ACENTOS. O cmd.exe interpreta
rem  o texto na codepage do console, que varia de maquina para maquina, e um
rem  acento vira lixo na tela (ou pior, quebra o comando). Quem fala portugues
rem  na tela e' o .ps1, que roda em UTF-8.
rem ===========================================================================

title Ciclo Assist - instalar

rem -NoProfile: ignora o perfil do usuario. Um perfil que imprima algo, ou que
rem demore, atrapalharia um script que a pessoa so' quer ver funcionar.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar.ps1"

rem O .ps1 espera um Enter no fim, no sucesso e no erro. Este pause so' cobre o
rem caso em que ele nem chegou a rodar (PowerShell ausente, arquivo movido) -
rem sem isto a janela fecharia levando a mensagem junto.
if errorlevel 1 pause
