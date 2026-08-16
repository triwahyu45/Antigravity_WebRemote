@echo off
cd /d "%~dp0"
start "" pythonw.exe server.py
echo ========================================================
echo  [OK] WahyuAI Remote BERHASIL DIJALANKAN DI BACKGROUND!
echo  Akses HP: http://wahyuai.local:8888
echo ========================================================
timeout /t 2 >nul
