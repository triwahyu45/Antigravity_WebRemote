@echo off
cd /d "%~dp0"
powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"

set "PY_EXE="
if exist "%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
) else if exist "%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe" (
    set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\pythonw.exe"
) else (
    for /f "delims=" %%i in ('where pythonw 2^>nul') do set "PY_EXE=%%i"
)

if "%PY_EXE%"=="" (
    for /f "delims=" %%i in ('where python 2^>nul') do set "PY_EXE=%%i"
)

if "%PY_EXE%"=="" (
    echo [ERROR] Python tidak ditemukan di sistem!
    pause
    exit /b 1
)

start "" "%PY_EXE%" tray_app.py
echo [OK] Antigravity Remote System Tray BERHASIL DIAKTIFKAN!
echo Ikon muncul di Taskbar pojok kanan bawah (dekat jam).
timeout /t 3 >nul
