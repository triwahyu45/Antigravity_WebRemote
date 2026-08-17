# 🚀 Antigravity WebRemote

<div align="center">

**A lightweight, real-time web & mobile remote client for Google Antigravity.**  
*Mirroring conversations, live thinking/tool status, artifacts, and two-way chat directly from your smartphone.*

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-brightgreen.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688.svg)](https://fastapi.tiangolo.com/)
[![Tailscale Ready](https://img.shields.io/badge/Tailscale-Ready-4f46e5.svg)](https://tailscale.com/)

</div>

---

## ✨ Features

- 📱 **1:1 Antigravity Desktop Clone**: Dark Obsidian UI matching the exact desktop interface with full project tree, active session breadcrumbs, and right panel overview.
- ⚡ **Real-Time WebSocket Live Stream**: Sub-100ms streaming of agent responses, terminal outputs, and file modifications.
- 🧠 **Live Engine Status & Thinking Badge**: Animated pulsing badge displaying real-time agent status (`Idle` vs `Working`), live timer (`Worked for Xs`), and current executing tool actions.
- 💬 **Two-Way Interactive Chat**: Send prompts, select workflows (`/goal`, `/schedule`), or dictate voice prompts (Speech-to-Text) from your phone directly into Antigravity.
- 📖 **Artifact & Document Modal Viewer**: Click any artifact markdown or code file from the right panel to read it inside a popup viewer.
- 🌐 **Zero-Config Networking**:
  - **Local Wi-Fi (mDNS)**: Access via `http://wahyuai.local:8888`.
  - **Remote Anywhere (Tailscale)**: Access seamlessly over your secure Tailscale mesh VPN.
- 🤫 **Background Resilient**: Runs quietly as a detached background service on Windows/Linux/macOS without holding or blocking active agent sessions.

---

## 🏗️ Architecture

```mermaid
graph LR
    Phone["📱 Smartphone (PWA / Browser)"] <-->|WebSocket sub-100ms| Server["⚡ FastAPI Server (:8888)"]
    Server <-->|Live JSON Log Stream| Engine["🤖 Antigravity Core (~/.gemini/antigravity/brain)"]
```

---

## 🚀 Quick Start

### 1. Clone Repository
```bash
git clone https://github.com/triwahyu45/Antigravity_WebRemote.git
cd Antigravity_WebRemote
```

### 2. Install Dependencies
```bash
pip install -r requirements.txt
```

### 3. Configure
Copy the example configuration:
```bash
cp config.example.json config.json
```

### 4. Run Server
```bash
python server.py
```

Open on your phone:
- **Local Wi-Fi**: `http://wahyuai.local:8888`
- **Tailscale**: `http://<your-tailscale-ip>:8888`

---

## 🛠️ Tech Stack

- **Backend**: FastAPI, Uvicorn, WebSockets, Zeroconf (mDNS), psutil
- **Frontend**: Vanilla JS (PWA Ready), HTML5, CSS3 (Glassmorphism), Marked.js, Highlight.js
- **Network**: mDNS / Bonjour, Tailscale VPN

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).

---
<div align="center">
Built with ❤️ for Google Antigravity
</div>

---

## 💖 Support & Donations

If you find this project helpful or inspiring, consider supporting its maintenance and further development!

[![SociaBuzz](https://img.shields.io/badge/SociaBuzz-Support%20(Global%20%2F%20PayPal%20%2F%20QRIS)-2563eb?style=for-the-badge&logo=cashapp&logoColor=white)](https://sociabuzz.com/triwahyu45)
[![Saweria](https://img.shields.io/badge/Saweria-Dukung%20Kreator-fa709a?style=for-the-badge&logo=coffeescript&logoColor=black)](https://saweria.co/triwahyu45)
[![Trakteer](https://img.shields.io/badge/Trakteer-Traktir%20Kopi-be123c?style=for-the-badge&logo=trakteer&logoColor=white)](https://trakteer.id/triwahyu45)
