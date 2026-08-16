@echo off
powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo ========================================================
echo  [OK] WahyuAI Remote BERHASIL DIMATIKAN!
echo ========================================================
timeout /t 2 >nul
