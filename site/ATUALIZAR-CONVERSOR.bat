@echo off
cd /d "%~dp0"
copy /y ..\migrar.py public\migrar.py
copy /y ..\camada_mta.json public\camada_mta.json
pause
