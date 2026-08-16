@echo off
cd /d "%~dp0\.."
echo === Crystal startup ===

start "crystal-collector" cmd /k python realtime\collector\collector.py
timeout /t 3 /nobreak >nul
start "crystal-processor" cmd /k python feature_processor.py
timeout /t 3 /nobreak >nul
start "crystal-bots" cmd /k python trading_bot.py
timeout /t 3 /nobreak >nul
start "crystal-mt5" cmd /k python mt5_connector.py
timeout /t 2 /nobreak >nul
start "crystal-watchdog" cmd /k scripts\watchdog.bat

echo Done. Only MT5 terminal needs to be open manually.
