@echo off
title Pasang Auto-Start Local AI Agent
color 0a
echo ==============================================================================
echo   MEMASANG AUTO-START LOCAL AI AGENT (NYALA OTOMATIS SAAT LAPTOP HIDUP)
echo ==============================================================================
echo.

powershell -Command "$ws = New-Object -ComObject WScript.Shell; $s = $ws.CreateShortcut(\"$env:APPDATA\Microsoft\Windows\Start Menu\Programs\Startup\Local_AI_Mobile_Agent.lnk\"); $s.TargetPath = \"wscript.exe\"; $s.Arguments = \"""%~dp0start_background.vbs""\"; $s.WorkingDirectory = \"%~dp0\"; $s.Save()"

echo [OK] Berhasil dipasang ke Windows Startup!
echo      Sekarang setiap kali laptop menyala, server otomatis berjalan di background!
echo.
pause
