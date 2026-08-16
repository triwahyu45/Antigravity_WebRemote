@echo off
cd /d "D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent"
powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
start "" pythonw.exe runner.py
echo [OK] Antigravity WebRemote BERHASIL DIAKTIFKAN DI BACKGROUND!
echo Akses: http://wahyuai.local:8888 atau http://100.89.122.63:8888
timeout /t 2 >nul
