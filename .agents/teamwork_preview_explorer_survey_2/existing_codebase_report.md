# Existing Codebase Assessment & Architecture Audit Report

**Date**: 2026-08-17  
**Investigator**: explorer_survey_2  
**Target Repository**: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent`  
**Reference System**: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\_references_antigravity_mobile\ag2r`  

---

## 1. Executive Summary

The existing codebase at `Local_AI_Mobile_Agent` is an early prototype (dubbed "v5.0") that attempted to simulate an Antigravity remote interface using **log file polling** (`transcript.jsonl` in `~/.gemini/antigravity/brain/`) and **desktop GUI keystroke automation** (`win32gui`, `pyautogui`, `pyperclip`).

However, it **lacks the core architecture and feature parity of AG2R (v6.0)**:
1. **No CDP Connection**: `cdp_bridge.py` does not exist. It has zero Chrome DevTools Protocol integration to `127.0.0.1:9000` or `DevToolsActivePort`.
2. **No Real-Time DOM Snapshot Mirroring**: Instead of capturing and sanitizing DOM snapshots directly from Antigravity's Electron window, it reconstructs chat bubbles manually from `transcript.jsonl`.
3. **No Web Push Notifications / VAPID**: `push_notifications.py` does not exist. The service worker (`sw.js`) lacks push event handlers.
4. **No Interactive Overlays or CDP Click Handlers**: Routes for `/api/cdp/click`, `/api/cdp/stop`, `/api/upload-image`, `/api/vapid-key`, and `/api/subscriptions/push` are missing.
5. **Hardcoded Mock Data & Dead Code**: `server.py` contains hardcoded project trees, hardcoded session IDs (`63fb64ac-9344-46a1-8d60-a891ba0835d8`), and ~120 lines of unreachable duplicate code in `parse_transcript_file`.

The Python environment (Python 3.12) is already equipped with `fastapi`, `uvicorn`, `websockets` (v16.0), `httpx`, `aiohttp`, `zeroconf`, `psutil`, and `cryptography` (v48.0.0). Direct WebSocket communication with Antigravity's active CDP target (discovered via `%APPDATA%\Antigravity\DevToolsActivePort` or port 9000) was tested and verified working in sub-10ms latency.

---

## 2. Comprehensive Inventory of Existing Files

| File / Path | Size / Lines | Purpose & Current Implementation Status |
| :--- | :--- | :--- |
| `server.py` | 33,989 B (855 lines) | **Main Backend Server**: FastAPI application. Currently runs transcript file watcher and GUI injection. Contains dead duplicate code (lines 213-333), hardcoded mock project lists, and legacy endpoints. Missing all CDP and Push endpoints. |
| `requirements.txt` | 105 B (7 lines) | **Python Dependencies**: Lists `fastapi`, `uvicorn`, `psutil`, `requests`, `aiofiles`, `zeroconf`. **Missing**: `pywebpush`, `websockets`, `httpx`, `cryptography`. |
| `config.json` | 684 B (16 lines) | **Server Configuration**: Configures host (`0.0.0.0`), port (`8888`), mDNS (`wahyuai.local`), auth PIN, system prompt, default workspace. Missing VAPID keys and CDP configuration fields. |
| `config.example.json` | 355 B (16 lines) | **Config Template**: Example JSON configuration. |
| `tray_app.py` | 3,730 B (113 lines) | **Windows System Tray App**: Uses `pystray` and `PIL` to show tray icon, copy Wi-Fi / Tailscale links, restart server, or open browser. |
| `runner.py` | 551 B (21 lines) | **Detached Process Spawner**: Runs `python server.py` using `DETACHED_PROCESS` and logs to `server.log`. |
| `static/index.html` | 13,620 B (212 lines) | **Frontend HTML**: Custom mockup with sidebar, chat area, right panel tabs, modals. Missing AG2R structural containers (`#chat-content`, `#subagent-bar`, `#running-tasks`, `#dropdown-overlay`, `#permission-overlay`, `#scheduled-tasks-overlay`, `#conversation-history-overlay`, `#comment-fab`, etc.). |
| `static/css/app.css` | 19,890 B (712 lines) | **Frontend CSS**: Stylesheet for custom mock layout. Missing AG2R CDP styles, overlay positioning, Material Symbols, and responsive layout classes. |
| `static/js/app.js` | 24,749 B (590 lines) | **Frontend Script**: Renders transcript messages, uses `marked.js` and `highlight.js`, handles mock tab switching. Missing AG2R DOM patching, click proxying, CDP event delegation, VAPID push registration, and subagent handling. |
| `static/manifest.json` | 502 B (23 lines) | **PWA Manifest**: Configures PWA metadata (`WahyuAI`, `/wahyuai`, standalone). |
| `static/sw.js` | 602 B (23 lines) | **Service Worker**: Caching only. Missing `push`, `notificationclick`, and `notificationclose` handlers. |
| `static/icons/` | Directory | Empty directory. |
| `data/conversations.db` | 0 B | Empty SQLite database placeholder. |
| `data/uploads/` | Directory | Empty upload storage. |
| `Jalankan_WahyuAI_Remote.bat` | 829 B | Batch launcher with ASCII header and IP printing. |
| `Matikan_WahyuAI_Remote.bat` | 385 B | Taskkill script targeting `server.py` and port 8888. |
| `run_server.bat` | 1,172 B | Batch script running pip install, resolving Tailscale IP, and executing `server.py`. |
| `stop_server.bat` | 764 B | Batch script terminating python processes on port 8888. |
| `enable_autostart.bat` | 778 B | Adds registry key for Windows startup. |
| `disable_autostart.bat` | 440 B | Removes Windows startup registry key. |
| `start_background.vbs` | 479 B | VBScript to spawn `runner.py` invisibly. |
| `run_silent.vbs` | 93 B | VBScript to spawn `run_server.bat` invisibly. |
| `ORIGINAL_REQUEST.md` | 5,739 B (84 lines) | Project specification for Antigravity WebRemote v6. |
| `README.md` | 3,056 B (87 lines) | Existing project documentation. |

---

## 3. Implementation Gap Analysis (Requirements vs. Existing Code)

### R1. CDP Live DOM Mirroring
- **Required**: `cdp_bridge.py` connecting to Antigravity CDP at `127.0.0.1:9000` (or dynamic `DevToolsActivePort`), capturing DOM snapshots every ~300ms, stripping fixed/absolute overlays, fixing inline div-in-span, computing hash, and broadcasting `{"type":"snapshot","html":"...","css":"...","hash":"...","agentRunning":bool}` via WebSocket `/ws/stream`.
- **Existing**: **0% implemented**. `cdp_bridge.py` does not exist. `server.py` polls `transcript.jsonl` on disk and sends `{"event":"transcript_update"}`.
- **Verification of CDP Capability**: We performed a live probe of the running Antigravity instance on Windows. The port was discovered at `C:\Users\hando\AppData\Roaming\Antigravity\DevToolsActivePort` (port 49250). A Python WebSocket probe evaluated `document.title` and confirmed `{"value":"Bismillah"}` and `.scrollbar-hide` container presence in sub-10ms.

### R2. Two-Way Interaction via CDP
- **Required**:
  1. `POST /api/chat/send` (or `/send`) — Injects message into Lexical editor via CDP `ClipboardEvent('paste')` + clicks send button.
  2. `POST /api/cdp/click` (or `/click`) — Proxies clicks by `data-ag-click-id` (Allow/Deny, radiogroup options, tabs, tasks).
  3. `POST /api/cdp/stop` (or `/stop`) — Clicks cancel tooltip / square stop button via CDP.
  4. `POST /api/upload-image` (or `/upload`) — Injects image into editor via DragEvent sequence (`dragenter` -> `dragover` -> `drop`).
- **Existing**: **Broken / Mocked**.
  - `server.py` attempts GUI keystroke automation (`pyautogui.hotkey('ctrl', 'v')`, `win32gui.SetForegroundWindow`) which steals focus, fails if screen is locked or window minimized, and is unreliable on mobile remote.
  - `/api/cdp/click`, `/api/cdp/stop`, and `/api/upload-image` are **completely missing**.

### R3. Interactive Overlays (Permission, ask_question, Dropdown)
- **Required**: Detection of permission banners (`Allow`/`Deny`/`Review`/`Run`), `ask_question` cards with selectable options, and dropdown/portal menus (worktree/branch selector, models), with tag-and-click forwarding.
- **Existing**: **0% implemented**. No overlay detection exists in `server.py` or `static/js/app.js`.

### R4. Web Push Notifications (VAPID)
- **Required**: `push_notifications.py` module generating and persisting VAPID keys, serving `GET /api/vapid-key` (and `/push/vapid-public-key`), saving subscriptions via `POST /api/subscriptions/push` (and `/push/subscribe`), and dispatching push notifications via `pywebpush` upon agent completion, permission request, or question prompt.
- **Existing**: **0% implemented**. `push_notifications.py` does not exist. `pywebpush` is missing in `requirements.txt`. `static/sw.js` does not handle push events.

### R5. Frontend Full AG2R Feature Parity
- **Required**: 1:1 parity with AG2R frontend (`ag2r/public/index.html`, `ag2r/public/js/app.js`, `ag2r/public/css/style.css`):
  - Running tasks strip (collapsible)
  - Subagent view bar + back button
  - BTW side-question panel
  - Scheduled tasks overlay (list, create form, kebab actions)
  - Conversation history overlay
  - Comment FAB (appears on text selection) & queued comment modal
  - Scroll-to-bottom FAB
  - Connection status dot (connected / reconnecting / disconnected)
  - Image upload button with camera/gallery
  - CDP click routing via `data-ag-click-id`
- **Existing**: `static/index.html` and `static/js/app.js` contain a custom v5.0 mockup that expects transcript arrays, hardcoded projects, and manually rendered markdown cards. It does not render captured DOM snapshots or handle AG2R overlay events.

---

## 4. Dependencies & Runtime Environment Audit

### Python Runtime
- **Python Executable**: `C:\Users\hando\AppData\Local\Programs\Python\Python312\python.exe`
- **Python Version**: `3.12.0` (64-bit Windows)

### Package Status Check

| Package | Status | Version / Notes |
| :--- | :--- | :--- |
| `fastapi` | **INSTALLED** | 0.110+ |
| `uvicorn` | **INSTALLED** | 0.41.0 |
| `websockets` | **INSTALLED** | 16.0 (supports modern async client context managers) |
| `cryptography` | **INSTALLED** | 48.0.0 (required for VAPID & ECE crypto) |
| `aiohttp` | **INSTALLED** | 3.13.5 (async HTTP client) |
| `httpx` | **INSTALLED** | 0.28.0+ |
| `zeroconf` | **INSTALLED** | 0.150.0 (mDNS discovery) |
| `psutil` | **INSTALLED** | 5.9.8+ |
| `requests` | **INSTALLED** | 2.34.2 |
| `aiofiles` | **INSTALLED** | 23.2.1 |
| `pyautogui` / `win32gui` | **INSTALLED** | Present (legacy GUI fallback) |
| `pystray` / `Pillow` | **INSTALLED** | Present (tray app support) |
| `pywebpush` | **MISSING** | Installable via pip (`http-ece`, `py-vapid`, `pywebpush`). |

### CDP Port Discovery Mechanics on Windows
1. **Dynamic Port File**: Antigravity writes its active DevTools port to `%APPDATA%\Antigravity\DevToolsActivePort` (e.g. `C:\Users\hando\AppData\Roaming\Antigravity\DevToolsActivePort`).
2. **Fixed Port Option**: When launched with `--remote-debugging-port=9000`, port 9000 is used.
3. **Multi-Port Probing Order**:
   - Priority 1: Port read from `DevToolsActivePort`
   - Priority 2: Configured `CDP_PORT` (default 9000)
   - Priority 3: Candidate fallback ports (9001, 9002, 9003)
4. **Target Selection**:
   - Priority 1: Target containing `workbench.html` or `workbench`
   - Priority 2: Target containing `jetski` or title `Launchpad`
   - Priority 3: Any target of type `page`

---

## 5. Server Configuration & Networking Audit

- **Host Binding**: `0.0.0.0` (accessible across all network interfaces).
- **Default Port**: `8888`.
- **CORS Configuration**: `CORSMiddleware` configured with `allow_origins=["*"]`, `allow_credentials=True`, `allow_methods=["*"]`, `allow_headers=["*"]`.
- **No-Cache Middleware**: `Cache-Control: no-store, no-cache, must-revalidate, max-age=0` enabled on all HTTP responses.
- **mDNS Service**: Registered via `zeroconf` as `WahyuAI._http._tcp.local.` announcing `http://wahyuai.local:8888`.
- **Tailscale Compatibility**: The server listens on `0.0.0.0:8888`, making it accessible via Tailscale IPv4 `100.89.122.63:8888`.
- **Static File Mounting**: `static/` mounted under `/static` and index served on `/`, `/wahyuai`, `/remote`.

---

## 6. Architecture & Implementation Plan for Feature Parity

To bring full AG2R feature parity (v6.0) to `Local_AI_Mobile_Agent`:

```
Local_AI_Mobile_Agent/
├── server.py                 # FastAPI backend: CDP lifecycle, WS snapshot stream, REST APIs
├── cdp_bridge.py             # CDP client: WebSocket connection, target discovery, eval scripts
├── push_notifications.py     # VAPID key generation, subscription persistence, pywebpush sender
├── cdp_scripts/              # Python dictionary / string modules for CDP JS injection
│   ├── capture.py            # Chat DOM capture, left sidebar, overlays, CSS custom props
│   ├── inject_message.py     # Lexical paste + send click
│   ├── click_main.py         # Multi-target click proxy
│   ├── stop.py               # Agent stop trigger
│   ├── upload_image.py       # Base64 drag-and-drop injection
│   ├── running_tasks.py      # Running tasks list extraction
│   ├── scheduled_tasks.py    # Scheduled tasks overlay & dialog
│   └── conversation_history.py# History navigation
├── static/
│   ├── index.html            # Full AG2R UI structure (matching ag2r/public/index.html)
│   ├── css/app.css           # AG2R styles, Material Symbols, dark theme
│   ├── js/app.js             # AG2R frontend engine, DOM patcher, click dispatcher, push client
│   ├── sw.js                 # PWA Service Worker with Push & NotificationClick handlers
│   └── manifest.json         # PWA Manifest
├── requirements.txt          # Updated with pywebpush, websockets, httpx
└── config.json               # Config with server, CDP, and VAPID settings
```

---

## 7. Conclusion & Recommendations

The existing codebase is structurally organized but functionally obsolete relative to the AG2R specifications. The optimal engineering path is:
1. Create `cdp_bridge.py` using Python's native `websockets` library with dynamic port resolution (`DevToolsActivePort` + port 9000).
2. Port the proven CDP injection scripts from `ag2r/src/cdp-scripts/` into Python modules (`cdp_scripts/`).
3. Create `push_notifications.py` using `pywebpush` and add `pywebpush` to `requirements.txt`.
4. Refactor `server.py` to route all chat, clicks, stops, and uploads through `cdp_bridge.py`, while broadcasting live DOM snapshots over `/ws/stream`.
5. Upgrade `static/index.html`, `static/css/app.css`, `static/js/app.js`, and `static/sw.js` to full AG2R parity.
6. Maintain backward compatibility for all existing endpoints (`/api/projects`, `/api/review/diff`, `/api/chat/incoming`, `/wahyuai`, etc.) so that existing scripts and bookmarks continue to function.
