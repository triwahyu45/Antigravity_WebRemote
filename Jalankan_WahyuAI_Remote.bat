@echo off
cd /d "D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent"
powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
start "" pythonw.exe tray_app.py
echo [OK] Antigravity Remote System Tray AKTIF di Taskbar Windows!
