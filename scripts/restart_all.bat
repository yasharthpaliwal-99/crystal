@echo off
cd /d "%~dp0\.."
echo [%date% %time%] Restarting Memurai + all processes...

net stop Memurai
timeout /t 2 /nobreak >nul
net start Memurai
timeout /t 3 /nobreak >nul

taskkill /FI "WINDOWTITLE eq crystal-collector*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-processor*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-bots*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-mt5*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-watchdog*" /F 2>nul

start "crystal-collector" cmd /k python realtime\collector\collector.py
timeout /t 2 /nobreak >nul
start "crystal-processor" cmd /k python feature_processor.py
timeout /t 2 /nobreak >nul
start "crystal-bots" cmd /k python trading_bot.py
timeout /t 2 /nobreak >nul
start "crystal-mt5" cmd /k python mt5_connector.py
timeout /t 2 /nobreak >nul
start "crystal-watchdog" cmd /k scripts\watchdog.bat

echo Done.
