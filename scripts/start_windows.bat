@echo off
cd /d "%~dp0.."
set "ROOT=%CD%"
echo === Crystal startup ===
echo ROOT=%ROOT%

start "crystal-collector" /D "%ROOT%" cmd /k python realtime\collector\collector.py
timeout /t 3 /nobreak >nul
start "crystal-processor" /D "%ROOT%" cmd /k python feature_processor.py
timeout /t 3 /nobreak >nul
start "crystal-bots" /D "%ROOT%" cmd /k python trading_bot.py
timeout /t 3 /nobreak >nul
start "crystal-mt5" /D "%ROOT%" cmd /k python mt5_connector.py
timeout /t 2 /nobreak >nul
start "crystal-watchdog" /D "%ROOT%" cmd /k scripts\watchdog.bat

echo Done. Only MT5 terminal needs to be open manually.
