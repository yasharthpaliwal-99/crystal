@echo off
cd /d "%~dp0\.."
echo Watchdog running — checks every 30s, restarts dead processes.
:loop
tasklist /FI "WINDOWTITLE eq crystal-collector*" | find "cmd.exe" >nul || start "crystal-collector" cmd /k python realtime\collector\collector.py
tasklist /FI "WINDOWTITLE eq crystal-processor*" | find "cmd.exe" >nul || start "crystal-processor" cmd /k python feature_processor.py
tasklist /FI "WINDOWTITLE eq crystal-bots*" | find "cmd.exe" >nul || start "crystal-bots" cmd /k python trading_bot.py
tasklist /FI "WINDOWTITLE eq crystal-mt5*" | find "cmd.exe" >nul || start "crystal-mt5" cmd /k python mt5_connector.py
timeout /t 30 /nobreak >nul
goto loop
