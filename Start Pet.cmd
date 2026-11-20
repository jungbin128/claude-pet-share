@echo off
cd /d "%~dp0"
start "" "%~dp0.runtime\Scripts\pythonw.exe" -X utf8 -I "%~dp0pet.pyw"
