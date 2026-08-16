import os
import sys
import subprocess
import webbrowser
import time
import socket
from PIL import Image, ImageDraw

base_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, base_dir)

def create_tray_icon():
    width = 64
    height = 64
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    
    # Outer dark circle with cyan border
    draw.ellipse((4, 4, 60, 60), fill=(20, 20, 20, 255), outline=(0, 242, 254, 255), width=3)
    # Inner glowing cyan lightning symbol
    draw.polygon([(32, 12), (20, 34), (32, 34), (30, 52), (44, 28), (32, 28)], fill=(0, 242, 254, 255))
    
    return image

# Server Subprocess Manager
server_proc = None

def start_server_process():
    global server_proc
    python_exe = sys.executable
    if "pythonw.exe" in python_exe.lower():
        # Use python.exe for subprocess if available to ensure full standard library
        alt_py = python_exe.lower().replace("pythonw.exe", "python.exe")
        if os.path.exists(alt_py):
            python_exe = alt_py
            
    log_path = os.path.join(base_dir, "server.log")
    log_file = open(log_path, "a", encoding="utf-8")
    
    # Kill any existing process on port 8888 first
    try:
        subprocess.run(
            'powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"',
            shell=True,
            capture_output=True
        )
    except Exception:
        pass
        
    server_proc = subprocess.Popen(
        [python_exe, "server.py"],
        cwd=base_dir,
        stdout=log_file,
        stderr=log_file,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    )

def stop_server_process():
    global server_proc
    if server_proc:
        try:
            server_proc.terminate()
            server_proc.kill()
        except Exception:
            pass
    # Force kill port 8888
    try:
        subprocess.run(
            'powershell -Command "Get-NetTCPConnection -LocalPort 8888 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"',
            shell=True,
            capture_output=True
        )
    except Exception:
        pass

def run_tray():
    import pystray
    from pystray import MenuItem as item
    
    # Start server subprocess
    start_server_process()
    
    def on_open_browser(icon, item):
        webbrowser.open("http://localhost:8888")

    def on_copy_wifi(icon, item):
        subprocess.run('powershell -command "Set-Clipboard -Value \"http://wahyuai.local:8888\""', shell=True)

    def on_copy_tailscale(icon, item):
        subprocess.run('powershell -command "Set-Clipboard -Value \"http://100.89.122.63:8888\""', shell=True)

    def on_restart(icon, item):
        stop_server_process()
        time.sleep(1)
        start_server_process()

    def on_exit(icon, item):
        stop_server_process()
        icon.stop()
        os._exit(0)

    menu = (
        item("⚡ Antigravity Remote (Port 8888)", lambda: None, enabled=False),
        item("🌐 Buka di Browser", on_open_browser, default=True),
        item("🏠 Salin Link Wi-Fi (wahyuai.local:8888)", on_copy_wifi),
        item("🌍 Salin Link Tailscale (100.89.122.63:8888)", on_copy_tailscale),
        pystray.Menu.SEPARATOR,
        item("🔄 Restart Server", on_restart),
        item("❌ Keluar (Exit)", on_exit)
    )

    icon_img = create_tray_icon()
    icon = pystray.Icon("AntigravityRemote", icon_img, "Antigravity Remote (Port 8888)", menu)
    try:
        icon.run()
    finally:
        stop_server_process()

if __name__ == "__main__":
    run_tray()
