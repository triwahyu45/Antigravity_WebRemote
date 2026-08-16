@echo off
title Stop Local AI Mobile Agent
color 0c
echo ==============================================================================
echo   MENGHENTIKAN LOCAL AI MOBILE AGENT DI BACKGROUND...
echo ==============================================================================
echo.

powershell -Command "Get-Process python*, pythonw* | Where-Object { $_.CommandLine -like '*Local_AI_Mobile_Agent*' -or $_.Path -like '*Local_AI_Mobile_Agent*' } | Stop-Process -Force -ErrorAction SilentlyContinue"
powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

echo [OK] Server di port 8888 berhasil dihentikan!
timeout /t 2 >nul
