@echo off
title Tri Wahyu Local AI Mobile Agent Server
color 0b
echo ==============================================================================
echo   TRI WAHYU HANDOYO - LOCAL AI AGENT MOBILE GATEWAY (mDNS ^& TAILSCALE PWA)
echo ==============================================================================
echo.

cd /d "%~dp0"

echo [1/3] Memeriksa dependensi Python (FastAPI, Zeroconf, dll)...
python -m pip install -r requirements.txt --quiet --disable-pip-version-check

echo [2/3] Memeriksa Alamat Akses HP...
for /f "tokens=*" %%i in ('powershell -Command "Get-NetIPAddress -InterfaceAlias 'Tailscale' -AddressFamily IPv4 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty IPAddress"') do set TAILSCALE_IP=%%i

echo.
echo   ================== ALAMAT BUKA DARI HP ==================
echo   [1] Local Wi-Fi (mDNS)   : http://wahyuai.local:8888
if defined TAILSCALE_IP (
    echo   [2] Tailscale (Luar Rumah): http://%TAILSCALE_IP%:8888
)
echo   =========================================================
echo.

echo [3/3] Menjalankan Server...
echo   Tekan CTRL + C untuk menghentikan server.
echo.
python server.py
pause
