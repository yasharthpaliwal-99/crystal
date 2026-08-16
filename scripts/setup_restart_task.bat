@echo off
:: Run once as Administrator
schtasks /Create /TN "CrystalRestart" /TR "\"%~dp0restart_all.bat\"" /SC DAILY /MO 10 /RL HIGHEST /F
echo Task created: CrystalRestart (every 10 days)
pause
