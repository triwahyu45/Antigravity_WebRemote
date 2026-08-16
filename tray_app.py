import os
import sys
import threading
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

def start_server_internal():
    import uvicorn
    from server import app
    config_p = os.path.join(base_dir, "config.json")
    if not os.path.exists(config_p):
        config_p = os.path.join(base_dir, "config.example.json")
    
    import json
    with open(config_p, "r", encoding="utf-8") as f:
        conf = json.load(f)
        
    host = conf.get("server", {}).get("host", "0.0.0.0")
    port = conf.get("server", {}).get("port", 8888)
    
    config = uvicorn.Config(app, host=host, port=port, log_level="warning")
    server = uvicorn.Server(config)
    server.run()

def run_tray():
    import pystray
    from pystray import MenuItem as item
    
    t = threading.Thread(target=start_server_internal, daemon=True)
    t.start()
    
    def on_open_browser(icon, item):
        webbrowser.open("http://localhost:8888")

    def on_copy_wifi(icon, item):
        import subprocess
        subprocess.run('powershell -command "Set-Clipboard -Value \"http://wahyuai.local:8888\""', shell=True)

    def on_copy_tailscale(icon, item):
        import subprocess
        subprocess.run('powershell -command "Set-Clipboard -Value \"http://100.89.122.63:8888\""', shell=True)

    def on_exit(icon, item):
        icon.stop()
        os._exit(0)

    menu = (
        item("⚡ Antigravity Remote (Active)", lambda: None, enabled=False),
        item("🌐 Buka di Browser", on_open_browser, default=True),
        item("🏠 Salin Link Wi-Fi (wahyuai.local:8888)", on_copy_wifi),
        item("🌍 Salin Link Tailscale (100.89.122.63:8888)", on_copy_tailscale),
        pystray.Menu.SEPARATOR,
        item("❌ Keluar (Exit)", on_exit)
    )

    icon_img = create_tray_icon()
    icon = pystray.Icon("AntigravityRemote", icon_img, "Antigravity Remote (Port 8888)", menu)
    icon.run()

if __name__ == "__main__":
    run_tray()
