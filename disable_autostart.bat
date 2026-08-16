@echo off
title Hapus Auto-Start Local AI Agent
color 0e
echo ==============================================================================
echo   MENGHAPUS AUTO-START LOCAL AI AGENT
echo ==============================================================================
echo.

del "%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Local_AI_Mobile_Agent.lnk" 2>nul

echo [OK] Auto-start berhasil dinonaktifkan!
echo.
pause
