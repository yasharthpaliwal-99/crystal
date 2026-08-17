@echo off
cd /d "%~dp0.."
set "ROOT=%CD%"
echo Watchdog running — checks every 30s, restarts dead processes.
echo ROOT=%ROOT%
:loop
call :ensure collector.py realtime\collector\collector.py
call :ensure feature_processor.py feature_processor.py
call :ensure trading_bot.py trading_bot.py
call :ensure mt5_connector.py mt5_connector.py
timeout /t 30 /nobreak >nul
goto loop

:ensure
wmic process where "name='python.exe' or name='pythonw.exe' or name='py.exe'" get commandline 2>nul | find /I "%~1" >nul
if not errorlevel 1 goto :eof
start "" /D "%ROOT%" cmd /k python %~2
goto :eof
