@echo off
cd /d "%~dp0.."
set "ROOT=%CD%"
echo [%date% %time%] Restarting Memurai + all processes...
echo ROOT=%ROOT%

net stop Memurai
timeout /t 2 /nobreak >nul
net start Memurai
timeout /t 3 /nobreak >nul

taskkill /FI "WINDOWTITLE eq crystal-collector*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-processor*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-bots*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-mt5*" /F 2>nul
taskkill /FI "WINDOWTITLE eq crystal-watchdog*" /F 2>nul

start "crystal-collector" /D "%ROOT%" cmd /k python realtime\collector\collector.py
timeout /t 2 /nobreak >nul
start "crystal-processor" /D "%ROOT%" cmd /k python feature_processor.py
timeout /t 2 /nobreak >nul
start "crystal-bots" /D "%ROOT%" cmd /k python trading_bot.py
timeout /t 2 /nobreak >nul
start "crystal-mt5" /D "%ROOT%" cmd /k python mt5_connector.py
timeout /t 2 /nobreak >nul
start "crystal-watchdog" /D "%ROOT%" cmd /k scripts\watchdog.bat

echo Done.
