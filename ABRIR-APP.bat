@echo off
rem Abre a janela do Ciclo Assist (compila antes, se mudou). SEM ACENTOS: o cmd.exe le em cp850.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0app\abrir.ps1"
if errorlevel 1 pause
