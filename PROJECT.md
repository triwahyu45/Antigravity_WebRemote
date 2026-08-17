# Project: Antigravity WebRemote v6 (Python Port)

## Architecture
Antigravity WebRemote v6 is a high-performance, asynchronous Python backend (FastAPI / Uvicorn) that connects directly to the desktop Antigravity Electron process via Chrome DevTools Protocol (CDP) WebSocket, providing real-time live DOM mirroring, two-way interaction, overlay dialog handling, and Web Push notifications to mobile and desktop browsers over local network (Tailscale / mDNS) without requiring Node.js.

```
┌────────────────────────────────────────────────────────┐
│             Antigravity Electron App (Desktop)         │
│  - DevTools Active Port (%APPDATA%\Antigravity\...)   │
│  - Main World + Extension Execution Contexts           │
└───────────────────────────▲────────────────────────────┘
                            │ CDP WebSocket (JSON-RPC)
┌───────────────────────────▼────────────────────────────┐
│         Local AI Mobile Agent (Python 3.12 Backend)    │
│  ┌───────────────────┐        ┌─────────────────────┐ │
│  │   cdp_bridge.py   │◄──────►│ push_notifications  │ │
│  │ - 31 CDP scripts  │        │ - VAPID Keypair     │ │
│  │ - Context Manager │        │ - Subscriptions     │ │
│  │ - DOM Sanitizer   │        │ - pywebpush sender  │ │
│  │ - DJB2 Hash Diff  │        └─────────────────────┘ │
│  └─────────▲─────────┘                                 │
│            │                                           │
│  ┌─────────▼────────────────────────────────────────┐ │
│  │                server.py (FastAPI)               │ │
│  │ - /ws/stream (DOM snapshot diff broadcasting)     │ │
│  │ - 32 WebRemote v6 API routes + 15 Legacy routes  │ │
│  │ - mDNS Zeroconf registration (wahyuai.local:8888)│ │
│  └─────────────────────▲────────────────────────────┘ │
└────────────────────────┼───────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼───────────────────────────────┐
│           Mobile & Web Clients (Android / iOS / PC)    │
│  - static/index.html (AG2R DOM Container & Overlays)   │
│  - static/js/app.js (Snapshot Patching, FABs, Push)    │
│  - static/css/app.css (Antigravity 2.0 Responsive CSS) │
│  - static/sw.js (Service Worker Web Push Handler)      │
└────────────────────────────────────────────────────────┘
```

## Feature Inventory
Every feature from the specification survey is cataloged and assigned to a specific milestone below:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | DevTools Port Discovery | Auto-detect DevTools port from `%APPDATA%\Antigravity\DevToolsActivePort` with fallback to 9000..9003 | M1 | R1, AC1 |
| 2 | CDP Target Discovery & Connection | Locate `workbench.html` / `page` targets and establish async CDP WebSocket session | M1 | R1, AC1 |
| 3 | Multi-Context Execution Tracking | Track `executionContextCreated/Destroyed/Cleared` and evaluate across Main/Isolated contexts | M1 | R1, AC1 |
| 4 | DOM Capture & Element Tagging | Tag interactive elements with `data-ag-click-id`, clone chat container without modifying live DOM | M1 | R1, AC2 |
| 5 | DOM Sanitization Pipeline | 14-step cleaning: remove editors, strip fixed overlays, fix span-div nesting, remove object-object classes | M1 | R1, AC2 |
| 6 | Dynamic CSS Extraction | Harvest CSS stylesheets and all `--*` root/body variables from Antigravity | M1 | R1, AC2 |
| 7 | DJB2 Composite State Hashing | Hash 17 state flags (html, css, overlays, attention items, subagent state) to minimize payload traffic | M1 | R1, AC2 |
| 8 | Attention State Detection | Extract sidebar ping icons classified into `question`, `command`, and `completed` | M1 | R3, R4, AC5 |
| 9 | Overlay Data Extraction | Extract permission banners, ask_question cards, dropdowns, dialogs, running tasks, subagents, BTW panel | M1 | R3, R5, AC4 |
| 10 | VAPID Keypair Management | Generate and persist EC P-256 VAPID keys in `vapid-keys.json` / `config.json` | M2 | R4, AC5 |
| 11 | Push Subscription Storage | Store, update, and persist browser push subscriptions in `push-subscriptions.json` | M2 | R4, AC5 |
| 12 | Background Push Dispatcher | Trigger web push via `pywebpush` for task complete, permission approval, and questions with payload | M2 | R4, AC5 |
| 13 | Client Visibility Suppression | Track active/foreground browser tabs and suppress push notifications when user is actively viewing | M2 | R4, AC5 |
| 14 | WebSocket Streaming Endpoint | `/ws/stream` endpoint broadcasting live snapshots and handling client ping/visibility messages | M3 | R1, AC2 |
| 15 | Two-Way Chat Injection | `POST /api/chat/send` injecting text into Lexical editor via ClipboardEvent paste and clicking send | M3 | R2, AC3 |
| 16 | CDP Element Click Proxy | `POST /api/cdp/click` dispatching coordinated clicks to chat items, buttons, actions, and dropdowns | M3 | R2, AC3 |
| 17 | Agent Execution Stopper | `POST /api/cdp/stop` targeting stop button / square icon to halt generation | M3 | R2, AC3 |
| 18 | Base64 Image Drag-Drop Upload | `POST /api/upload-image` synthesizing File DragEvent into Lexical editor | M3 | R2, AC3 |
| 19 | Interactive Overlay Routes | Endpoints for `/api/cdp/answer-question`, `/api/cdp/permission`, `/api/cdp/dropdown-select` | M3 | R3, AC4 |
| 20 | Task & Session Navigation | `/api/running-tasks`, `/api/scheduled-tasks`, `/api/conversation-history`, `/api/right-sidebar` | M3 | R5, AC6 |
| 21 | Legacy Route Compatibility | Retain all 15 legacy routes (`/api/projects`, `/api/review/diff`, `/api/chat/incoming`, etc.) returning 200 | M3 | AC7 |
| 22 | Zeroconf mDNS Registration | Broadcast `wahyuai.local:8888` on local network alongside Tailscale `100.89.122.63:8888` | M3 | AC8 |
| 23 | Process Lifecycle Management | `/api/restart-antigravity` handling Windows `taskkill` and restart of Antigravity executable | M3 | AC9 |
| 24 | Frontend Live Snapshot Renderer | `static/js/app.js` rendering sanitized HTML, applying captured CSS styles and CSS variables | M4 | R5, AC2 |
| 25 | Interactive Overlays UI | Render permission banners, ask_question cards, and dropdown portals on top of mobile chat | M4 | R3, AC4 |
| 26 | Running Tasks Strip UI | `#running-tasks` bar inside input container with spinner, task name, and inline stop button | M4 | R5, AC6 |
| 27 | Subagent View Bar UI | `#subagent-bar` warning banner with back button and subagent details modal | M4 | R5, AC6 |
| 28 | BTW Side Question Panel | `#btw-panel` for asking side questions without disturbing active context | M4 | R5, AC6 |
| 29 | Floating Action Buttons (FAB) | `#scroll-fab` (scroll-to-bottom) and `#comment-fab` (sidebar text selection -> comment queue badge) | M4 | R5, AC6 |
| 30 | Scheduled Tasks & History Modals | Fullscreen overlays for Scheduled Tasks and Conversation History | M4 | R5, AC6 |
| 31 | Service Worker & Push Bell | `static/sw.js` handling push events and notification clicks; 3-state notification bell in header | M4 | R4, AC5 |
| 32 | Mobile Responsive Styles | `static/css/app.css` matching Antigravity 2.0 theme, safe areas, touch targets, and dark mode | M4 | R5, AC10 |

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | CDP Bridge & Scripts Engine | `cdp_bridge.py` with port discovery, WebSocket connection, 31 CDP scripts, DOM sanitization, CSS extraction, DJB2 hashing | none | PLANNED |
| M2 | Push Notifications Module | `push_notifications.py` with VAPID keypair generation, subscription persistence, pywebpush integration, visibility suppression, update `requirements.txt` | none | PLANNED |
| M3 | Server Core & API Parity | `server.py` integration: `/ws/stream`, 32 WebRemote v6 REST endpoints, 15 legacy endpoints, Zeroconf mDNS, Antigravity process restart | M1, M2 | PLANNED |
| M4 | Frontend AG2R Full Parity | `static/index.html`, `static/css/app.css`, `static/js/app.js`, `static/sw.js`, `static/manifest.json` | M1, M2, M3 | PLANNED |
| M5 | Final Integration & Adversarial Hardening | 100% E2E test suite pass (Tiers 1-4), adversarial test hardening (Tier 5), Forensic Audit | M1, M2, M3, M4 | PLANNED |

## Interface Contracts

### `cdp_bridge.py` ↔ `server.py`
```python
class CDPBridge:
    def __init__(self, port: Optional[int] = None, host: str = "127.0.0.1"): ...
    async def connect(self) -> bool: ...
    async def disconnect(self) -> None: ...
    async def capture_snapshot(self) -> Optional[Dict[str, Any]]: ...
    async def inject_message(self, text: str, append_mode: bool = False) -> Dict[str, Any]: ...
    async def click_element(self, click_id: str, click_type: str = "chat") -> Dict[str, Any]: ...
    async def stop_generation(self) -> Dict[str, Any]: ...
    async def upload_image(self, base64_data: str, mime_type: str = "image/png", filename: str = "upload.png") -> Dict[str, Any]: ...
    async def type_text(self, selector: str, text: str) -> Dict[str, Any]: ...
    async def execute_script(self, script_name: str, args: Optional[Dict[str, Any]] = None) -> Any: ...
    @property
    def is_connected(self) -> bool: ...
```

### `push_notifications.py` ↔ `server.py`
```python
class PushNotificationManager:
    def __init__(self, config_path: str = "config.json", subscriptions_path: str = "push-subscriptions.json"): ...
    def get_public_vapid_key(self) -> str: ...
    def add_subscription(self, subscription_data: Dict[str, Any]) -> bool: ...
    def remove_subscription(self, endpoint: str) -> bool: ...
    def set_client_visibility(self, client_id: str, is_visible: bool) -> None: ...
    def is_any_client_visible(self) -> bool: ...
    async def check_and_send_attention_notifications(self, attention_items: List[Dict[str, Any]], agent_running: bool) -> int: ...
    async def send_notification(self, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> int: ...
```

### WebSocket `/ws/stream` Protocol
```json
// Server -> Client Snapshot Message
{
  "type": "snapshot",
  "hash": "djb2_hash_string",
  "html": "<sanitized_chat_html>",
  "css": "<extracted_stylesheets_and_variables>",
  "agentRunning": false,
  "isSubagentView": false,
  "subagentTitle": "",
  "attentionItems": [],
  "runningTasks": [],
  "permission": null,
  "askQuestion": null,
  "dropdown": null,
  "timestamp": 1723849200000
}

// Client -> Server Visibility Message
{
  "type": "visibility",
  "clientId": "uuid_v4",
  "visible": true
}
```

## Code Layout
```
Local_AI_Mobile_Agent/
├── server.py                 # FastAPI application, WebSocket streamer, REST routes
├── cdp_bridge.py             # CDP WebSocket client, context manager, 31 CDP scripts
├── push_notifications.py     # VAPID keys, subscription storage, pywebpush sender
├── requirements.txt          # Python dependencies (fastapi, uvicorn, websockets, pywebpush, etc.)
├── config.json               # Server configuration (port, VAPID keys, host)
├── push-subscriptions.json   # Persisted browser push subscriptions
├── static/
│   ├── index.html            # Main mobile web app UI matching AG2R layout
│   ├── css/
│   │   └── app.css           # Full AG2R responsive CSS with Antigravity 2.0 styling
│   ├── js/
│   │   └── app.js            # Snapshot renderer, interaction handlers, push manager, FABs
│   ├── sw.js                 # Service Worker for push notifications & caching
│   └── manifest.json         # PWA Web App Manifest
└── tests/                    # E2E Test Suite (Tiers 1-5)
    ├── harness.py            # Test runner and fixture utilities
    ├── test_tier1_features.py
    ├── test_tier2_boundaries.py
    ├── test_tier3_combinations.py
    ├── test_tier4_scenarios.py
    └── test_tier5_adversarial.py
```
