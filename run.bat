@echo off
cd /d "%~dp0"
:loop
.venv\Scripts\python -m bot.main
echo Bot durdu, 10 sn sonra yeniden baslatiliyor...
timeout /t 10 /nobreak >nul
goto loop
