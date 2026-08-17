# Antigravity WebRemote v6 — Comprehensive Feature Specification

**Document Version:** 6.0.0  
**Author:** spec_miner_survey_1  
**Timestamp:** 2026-08-17T01:29:00Z  
**Target Environment:** Python 3.10+ (FastAPI / Uvicorn), Windows 11  
**Authoritative Sources:** 
- `ORIGINAL_REQUEST.md` (Authoritative User Specification)
- `_references_antigravity_mobile/ag2r` (AG2R Reference Architecture & CDP Scripts)
- `Local_AI_Mobile_Agent/server.py` (Existing Local AI Mobile Agent codebase)

---

## 1. Executive Summary & Scope

**Antigravity WebRemote v6** is a full-featured Python implementation of AG2R (Antigravity 2.0 Remote), bringing complete mobile web remote control and real-time visual parity to Antigravity AI coding sessions.

### Core Architectural Principle
> **AG2R is a bridge, not a reconstruction.**
1. **Capture views, don't construct them:** When Antigravity displays chat, plans, sidebars, dialogs, or dropdowns, WebRemote captures the live DOM via Chrome DevTools Protocol (CDP) and mirrors it faithfully.
2. **Proxy clicks, don't manage state:** Taps on the mobile interface proxy directly to Antigravity DOM elements via CDP. Antigravity updates its internal React state, and the subsequent capture cycle reflects the changes.
3. **Index-based click dispatch:** Interactive elements are tagged (`chat:N`, `left:N`, `right:N`, `perm:N`, `ask:N`, `sched:N`, etc.) during capture and triggered by index lookup.
4. **Native elements are exceptions:** The only UI created natively on mobile are the mobile text/speech input, attachment management, queued commenting system, and Web Push notifications.

---

## 2. System Architecture & Network Topology

```
+-------------------------------------------------------------------------+
|                              Desktop Host                               |
|                                                                         |
|  +--------------------------------+   CDP (ws/json)    +-------------+  |
|  | Antigravity IDE (Electron)     |<------------------>| cdp_bridge  |  |
|  | --remote-debugging-port=9000   |   Port 9000        | (Python)    |  |
|  +--------------------------------+                    +------+------+  |
|                                                               |         |
|  +--------------------------------+                    +------+------+  |
|  | Brain Directory / Transcripts  |<-------------------| FastAPI     |  |
|  | ~/.gemini/antigravity/brain    |   File I/O         | Server      |  |
|  +--------------------------------+                    | (Port 8888) |  |
|                                                        +------+------+  |
|  +--------------------------------+                           |         |
|  | Web Push Engine (pywebpush)    |<--------------------------+         |
|  | VAPID RFC 8292 / FCM Gateway   |                                     |
|  +--------------------------------+                                     |
+---------------------------------------------------------------|---------+
                                                                | HTTP / WS / WebPush
                                         +----------------------+----------------------+
                                         |                                             |
                                         v                                             v
                           +---------------------------+                 +---------------------------+
                           | Mobile Device (Tailscale) |                 | Mobile Device (Local Wi-Fi|
                           | http://100.89.122.63:8888 |                 | http://wahyuai.local:8888 |
                           +---------------------------+                 +---------------------------+
```

### Constraints & Runtime Specifications
- **Runtime:** Python 3.10+ only (FastAPI, Uvicorn, websockets, psutil, pywebpush, zeroconf, aiofiles). Strictly **no Node.js** runtime dependency.
- **Port:** Server binds to `0.0.0.0:8888`.
- **Accessibility:** Reachable via Tailscale IP `100.89.122.63:8888` and mDNS `wahyuai.local:8888`.
- **CDP Port:** Default `127.0.0.1:9000` (auto-detects fallback ports 9000-9003 and Electron DevToolsActivePort).
- **Target Antigravity Session ID:** `63fb64ac-9344-46a1-8d60-a891ba0835d8`.
- **Brain Directory:** `C:\Users\hando\.gemini\antigravity\brain` (configurable via `ANTIGRAVITY_BRAIN_DIR`).
- **Memory Footprint:** Idle server RAM `< 80MB`. Startup time `< 5s`.

---

## 3. Functional Requirements (R1 – R5)

### R1. CDP Live DOM Mirroring (`cdp_bridge.py`)
- **Connection Management:**
  - Connects to Antigravity CDP target (`http://127.0.0.1:9000/json/list`).
  - Target discovery prioritization:
    1. Workbench target (`workbench.html` or title containing `workbench`)
    2. Jetski / Launchpad target (`jetski` or title `Launchpad`)
    3. Any Page target (`type === 'page'`)
  - Tracks execution contexts (`Runtime.executionContextCreated`, `destroyed`, `cleared`). Supports Main World and Isolated Contexts.
  - Enables Focus Emulation (`Emulation.setFocusEmulationEnabled({enabled: true})`) so Antigravity renders in the background.
  - Auto-reconnects every 3 seconds if disconnected.

- **DOM Capture & Sanitization Pipeline (13-step transformation):**
  1. **Container Locator:** Finds `.scrollbar-hide[class*="overflow-y-auto"]`, `[data-testid="conversation-view"]`, `#conversation`, `#chat`, or `#cascade`. Detects "new session page" root (`.animate-fade-in` parent of `#antigravity.agentSidePanelInputBox`) if chat container is zero-height.
  2. **Generation Status Detector:** Inspects `[data-tooltip-id="input-send-button-cancel-tooltip"]` and `button svg.lucide-square` to set boolean `agentRunning`.
  3. **Scroll Metrics:** Captures `scrollTop`, `scrollHeight`, `clientHeight`.
  4. **Interactive Element Tagging:** Tags buttons, links, `[role="button"]`, `[role="option"]`, `[role="menuitem"]`, and interactive `cursor-pointer` elements with `data-ag-click-id="chat:N"` and label snippet.
  5. **Clone & Cleanup:** Clones chat container, restores original DOM tags.
  6. **Editor Stripping:** Removes `[contenteditable="true"]`, `[data-lexical-editor]`, `[role="textbox"]`, and input forms from chat clone (except on new session page).
  7. **Positioning Sanitization:** Strips fixed and absolute positioned elements unless they are action bars (`Allow`, `Deny`, `Review`, `Run`, `Confirm`, `Undo`).
  8. **Sticky Background Fixing:** Converts sticky headers to solid dark background (`#101010`) to prevent text overlapping during mobile scroll.
  9. **HTML Validation Fix:** Converts invalid inline `span > div` and `p > div` into `display: inline-flex` spans.
  10. **Paragraph Display:** Forces `p` tags to `display: block`.
  11. **Class Cleaning:** Strips React stringification artifacts `[object Object]` from class attributes.
  12. **CSS Extraction:** Collects all document stylesheet rules and dynamically extracts all DOM CSS custom properties (`--*`) into a `:root { ... }` block.
  13. **Cross-Context Portal & Overlay Capture:**
      - Left sidebar (`.bg-sidebar`) + ping attention items (detects `question`, `command`, `completed`).
      - Right sidebar signature (`[data-tab-id]`, open/collapse container state). Full DOM available via `GET /api/right-sidebar`.
      - Running tasks strip from input box (`.rounded-t-2xl`).
      - Scheduled tasks page & form dialogs (`[aria-label="Add scheduled task"]`, `.fixed.inset-0.z-[2550]`).
      - Conversation history page (`/history`).
      - Popover dropdowns and Radix portals (`role="listbox"`, `role="dialog"`).
      - Permission banner (`role="radiogroup"` with Allow/Deny buttons).
      - Ask question card (`Submit` / `Skip` radiogroup card).
      - Subagent view detection ("Cannot send" / "Cannot prompt" labels, parent breadcrumbs).
      - `/btw` side question panel.

- **Differential Broadcasting:**
  - Computes hash of concatenated HTML strings and states.
  - Broadcasts `{"type": "snapshot", "hash": "...", "agentRunning": bool, "timestamp": "..."}` via WebSocket only when hash changes or `agentRunning` transitions.

---

### R2. Two-Way Interaction via CDP
- **Message Injection (`POST /api/chat/send` & `POST /send`):**
  - Targets Lexical editor `[data-lexical-editor="true"]`.
  - In normal mode: selects all children, deletes, dispatches `ClipboardEvent('paste')` with plain text data to preserve multi-line formatting in Lexical, falls back to `execCommand('insertText')`, then clicks submit button `button[data-testid="send-button"]` or dispatches Enter key.
  - In append mode (`appendMode: true`): moves cursor to end, preserving pre-uploaded image tokens or `/macro` pills.
  - Server-side deduplication (2-second window for identical message text).

- **Click Proxying (`POST /api/cdp/click` & `POST /click`):**
  - Parses prefix and index from `clickId` (`prefix:index`):
    - `chat:N` — clicks Nth interactive in chat container
    - `left:N` — clicks Nth item in left sidebar (conversation switcher)
    - `right:N` — clicks Nth item in right sidebar (overview/review tab, file diff, artifact card)
    - `dropdown:N` — clicks Nth option in portal dropdown with hit-testing (`elementFromPoint` + `PointerEvent`/`MouseEvent`)
    - `dialog:N` — clicks Nth button in portal dialog
    - `settings:N` — clicks Nth button in settings modal
    - `perm:N` — clicks Nth item in permission approval banner
    - `ask:N` — clicks Nth option or Submit/Skip in ask_question card
    - `task:N` — clicks Nth task button in running tasks strip
    - `subinfo:N` — clicks subagent overview button
    - `btw:N` — clicks side-question action button
    - `model:0` — clicks model selector dropdown button
    - `project:0` — clicks project dropdown button
    - `sched:N` / `scheddlg:N` — clicks scheduled task item / dialog control
    - `history:N` — clicks conversation history card
  - Validates `expectedLabel` against actual DOM element label to prevent stale index clicks.
  - Executes **Burst Re-Captures** (at 150ms, 400ms, 700ms) after click to immediately catch React DOM updates.

- **Stop Generation (`POST /api/cdp/stop` & `POST /stop`):**
  - Clicks `[data-tooltip-id="input-send-button-cancel-tooltip"]` or `button svg.lucide-square`.

- **Image Drag-and-Drop Injection (`POST /api/upload-image` & `POST /upload`):**
  - Receives uploaded image file (multipart `image`), converts to base64, builds synthetic `File` and `DataTransfer`, dispatches `dragenter`, `dragover`, `drop` events on Lexical editor.

- **Atomic Dialog Submission (`POST /submit-dialog`):**
  - Injects custom write-in text into `textarea` inside radiogroup via React native setter, then clicks Submit button.

- **React Input Setter (`POST /type-text`):**
  - Dispatches text to `input` / `textarea` by placeholder or clickId, invoking `Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set` followed by `input` and `change` events.

- **Lexical Control:**
  - `POST /clear-editor`: clears Lexical root node.
  - `POST /type-slash`: clears editor, pastes `/` to open macro typeahead popup.

---

### R3. Interactive Overlays & Portal Detection
1. **Permission Overlay:**
   - Detects permission approval bars requiring user confirmation (Allow, Deny, Review, Run, Always Allow).
   - Renders fixed backdrop + floating interactive action card on mobile.
   - User tap proxies click to Antigravity immediately.

2. **`ask_question` Overlay:**
   - Detects interactive questions generated by agent tools with options and optional custom text entry.
   - Renders interactive multiple-choice list + text input box + Submit/Skip buttons.

3. **Dropdown Portal Overlay:**
   - Detects body-level React portals (`role="listbox"`, `role="dialog"`).
   - Renders backdrop overlay, proxies option selection to desktop.

4. **Settings & Scheduled Tasks Overlays:**
   - Fullscreen overlays for settings inspection, cron task schedules, and history navigation.

---

### R4. Web Push Notifications (`push_notifications.py`)
- **VAPID Key Management:**
  - Auto-generates VAPID keypair (`vapid-keys.json` or `config.json`) using standard elliptic curve (P-256).
  - Serves public key via `GET /api/vapid-key` and `GET /push/vapid-public-key`.
- **Subscription Management:**
  - Stores browser `PushSubscription` endpoints and authentication keys via `POST /api/subscriptions/push` / `POST /push/subscribe`.
  - Persists subscriptions to disk (`push-subscriptions.json`).
- **Push Trigger Rules:**
  1. **Agent Completed:** `agentRunning` transitions from `true` to `false`.
  2. **Command Permission Required:** Ping item with `type === 'command'` appears in left sidebar or chat.
  3. **Agent Question Blocked:** Ping item with `type === 'question'` appears.
- **Delivery & Notification Behavior:**
  - Background dispatch via `pywebpush` (webpush standard RFC 8292).
  - Skips sending push if client is active in foreground (`visibleClients > 0`).
  - Handles HTTP 410 Gone (auto-purges expired subscriptions).
  - Includes deep link URL (`?sidebar=open&conversationId=<id>`) to directly navigate mobile browser to blocked conversation.
  - Push pause/resume controls (`POST /push/pause`, `POST /push/resume`).

---

### R5. Frontend Full AG2R Feature Parity
- **Header:** Menu toggle (Left Sidebar), App Icon, Title ("WahyuAI Remote" / "AG2R"), Connection Status Dot (Green/Yellow/Red), Refresh button, Notification Bell toggle (Subscribed/Unsubscribed/Paused), Review Panel toggle (Right Sidebar).
- **Left Sidebar:** Full conversation list mirrored from Antigravity, active conversation indicator, unread ping attention markers, New Session trigger, settings link.
- **Right Sidebar (Code Review & Overview):** Overview tab, Review tab with syntax-highlighted unified diffs, modified file tree, artifact cards.
- **Running Tasks Strip:** Collapsible strip under header showing active subtasks/goals with progress counts and cancel/view buttons.
- **Subagent View Bar:** Yellow/amber banner and back button (`← Back to [Parent Name]`) when viewing a child subagent conversation.
- **BTW Panel:** Side Question panel displaying contextual responses without disrupting primary chat thread.
- **Input Area:** Textarea with auto-resize, direct photo capture / file attach button, model selector chip, voice input dictation button (Web Speech API), dynamic Send/Stop action button.
- **Macro Pill System:** Visual chips for slash commands (`/btw`, `/grill-me`, `/teamwork-preview`, `/plan`, etc.).
- **Queued Commenting System:** Highlight text anywhere in right sidebar diff/artifact -> Floating Comment FAB -> Add Comment modal -> Queued Comments Pill -> Batch Send to agent.
- **Scroll-to-Bottom FAB:** Floating action button that appears when scrolled away from bottom, with unread activity indicator.
- **PWA Service Worker (`sw.js`):** Push event handler, notification click routing, offline asset caching.

---

## 4. Complete API & WebSocket Specification

### 4.1 REST API Endpoints

| Endpoint | Method | Request Body / Query | Response Body | Description |
|---|---|---|---|---|
| `GET /api/vapid-key`<br>`GET /push/vapid-public-key` | GET | None | `{"publicKey": "..."}` | Returns VAPID public key for Web Push subscription |
| `POST /api/subscriptions/push`<br>`POST /push/subscribe` | POST | `PushSubscription` JSON | `{"ok": true}` | Registers mobile browser push subscription |
| `POST /push/unsubscribe` | POST | `{"endpoint": "..."}` | `{"ok": true}` | Removes push subscription |
| `GET /push/status` | GET | None | `{"subscribers": N, "vapidPublicKey": "..."}` | Status of push notification subscribers |
| `GET /push/state` | GET | None | `{"paused": bool, "subscribers": N}` | Check if notifications are paused |
| `POST /push/pause` | POST | None | `{"ok": true, "paused": true}` | Pauses push notification delivery |
| `POST /push/resume` | POST | None | `{"ok": true, "paused": false}` | Resumes push notification delivery |
| `POST /push/test` | POST | None | `{"ok": true, "subscribers": N}` | Sends test push notification |
| `GET /snapshot` | GET | None | `{"html": "...", "css": "...", "agentRunning": bool, "hash": "..."}` | HTTP snapshot fallback for initial load |
| `GET /right-sidebar`<br>`GET /api/right-sidebar` | GET | None | `{"html": "..."}` | Fetches full right sidebar DOM on demand |
| `POST /close-sidebar`<br>`POST /toggle-sidebar` | POST | None | `{"ok": true}` | Closes or toggles right sidebar in Antigravity |
| `GET /proxy-image` | GET | `?src=<url>` | `{"dataUrl": "data:image/png;base64,..."}` | Proxies local/blob images from Antigravity DOM |
| `POST /expand-left-sidebar` | POST | None | `{"ok": true}` | Expands collapsed left sidebar in Antigravity |
| `POST /navigate-conversation` | POST | `{"conversationId": "<uuid>"}` | `{"ok": true}` | Clicks conversation pill in Antigravity sidebar |
| `POST /copy-response` | POST | `{"clickId": "chat:N"}` | `{"ok": true, "text": "..."}` | Intercepts copy action and returns raw markdown |
| `POST /dismiss-portal` | POST | None | `{"ok": true}` | Sends Escape key to dismiss open popups |
| `POST /dismiss-scheduled-tasks` | POST | None | `{"ok": true}` | Navigates back from scheduled tasks view |
| `POST /history-back` | POST | None | `{"ok": true}` | Navigates back in conversation history |
| `POST /dismiss-settings` | POST | None | `{"ok": true}` | Dismisses settings modal |
| `POST /restart-antigravity` | POST | None | `{"ok": true}` | Restarts Antigravity desktop Electron process |
| `POST /api/cdp/click`<br>`POST /click` | POST | `{"clickId": "prefix:N", "label": "..."}` | `{"ok": true, "label": "...", "source": "..."}` | Main click proxy for all tagged elements |
| `POST /submit-dialog` | POST | `{"clickId": "...", "label": "...", "text": "..."}` | `{"ok": true}` | Submits dialog with optional write-in text |
| `POST /clear-editor` | POST | None | `{"ok": true}` | Clears Lexical editor content |
| `POST /type-slash` | POST | None | `{"ok": true}` | Clears editor and injects `/` for macro autocomplete |
| `POST /type-text` | POST | `{"placeholder": "...", "text": "...", "clickId": "..."}` | `{"ok": true}` | Types text into React input/textarea |
| `POST /api/upload-image`<br>`POST /upload` | POST | Multipart Form (`image` file) | `{"ok": true, "fileName": "...", "size": N}` | Uploads and injects image into Lexical editor |
| `POST /api/chat/send`<br>`POST /send` | POST | `{"message": "...", "hasImages": bool, "hasMacro": bool}` | `{"ok": true, "method": "button|enter"}` | Injects message into Lexical editor and submits |
| `POST /send-images` | POST | None | `{"ok": true}` | Submits already-staged images without text |
| `POST /api/cdp/stop`<br>`POST /stop` | POST | None | `{"ok": true}` | Clicks stop button to abort generation |
| `GET /health` | GET | None | `{"status": "ok", "cdpConnected": bool, "wsClients": N}` | System health status |
| `GET /manifest.json` | GET | None | Web App Manifest JSON | Dynamic PWA manifest |
| `GET /sw.js` | GET | None | JavaScript file | Service Worker script |

### 4.2 Legacy & Compatibility Endpoints (15 Preserved Endpoints)

| Endpoint | Method | Compatibility Description |
|---|---|---|
| `GET /api/chat/incoming`<br>`GET /wahyuai/api/chat/incoming` | GET | Returns list of recorded incoming prompts from `incoming_web_chat.jsonl` |
| `POST /api/chat/send`<br>`POST /wahyuai/api/chat/send` | POST | Legacy chat send payload `{"message": "...", "session_id": "..."}` |
| `GET /api/uploads/{session_id}/{filename}`<br>`GET /wahyuai/api/uploads/{session_id}/{filename}` | GET | Serves uploaded images from session directory |
| `GET /api/review/diff`<br>`GET /wahyuai/api/review/diff` | GET | Returns git diff file summary for current working tree |
| `GET /api/projects`<br>`GET /wahyuai/api/projects` | GET | Returns project directory tree and session lists |
| `GET /api/sessions/{session_id}/steps`<br>`GET /wahyuai/api/sessions/{session_id}/steps` | GET | Returns parsed transcript steps for a session |
| `GET /api/sessions/{session_id}/details`<br>`GET /wahyuai/api/sessions/{session_id}/details` | GET | Returns files changed, artifacts list, and uploads count |
| `GET /api/artifacts/{session_id}/{artifact_name:path}`<br>`GET /wahyuai/api/artifacts/...` | GET | Returns contents of specific artifact file |
| `GET /wahyuai`, `GET /remote`, `GET /` | GET | Serves `static/index.html` |
| `GET /css/{file_path:path}` | GET | Serves stylesheet assets |
| `GET /js/{file_path:path}` | GET | Serves JavaScript assets |

### 4.3 WebSocket Protocol (`ws://<host>:8888/ws/stream`)

#### Server -> Client Messages:
1. **Connection State:**
   ```json
   {
     "type": "connection",
     "cdpConnected": true,
     "debugMode": false,
     "featureFlags": {}
   }
   ```
2. **Snapshot Notification:**
   ```json
   {
     "type": "snapshot",
     "hash": "3a9f1b",
     "agentRunning": true,
     "timestamp": "2026-08-17T01:30:00.000Z"
   }
   ```
3. **Status Update (State transition without DOM change):**
   ```json
   {
     "type": "status",
     "agentRunning": false
   }
   ```

#### Client -> Server Messages:
1. **Visibility State (Foreground / Background tracking):**
   ```json
   {
     "type": "visibility",
     "visible": true
   }
   ```

---

## 5. Acceptance Criteria (AC1 – AC14)

### Category: CDP Connectivity
- **AC1:** `python -c "import asyncio; from cdp_bridge import CDPBridge; b=CDPBridge(); asyncio.run(b.test_connect())"` connects to port 9000 and discovers target without error.
- **AC2:** WebSocket clients on `/ws/stream` receive initial `connection` and `snapshot` frames in `< 2 seconds` after connection establishment.

### Category: Two-Way Interaction
- **AC3:** A message sent from mobile UI via `POST /api/chat/send` or `POST /send` is injected into Antigravity Lexical editor and submitted (appearing as a user bubble in Antigravity desktop) in `< 3 seconds`.
- **AC4:** Invoking `POST /api/cdp/stop` or `POST /stop` during an active agent run immediately cancels generation in Antigravity.
- **AC5:** Uploading an image file via `POST /upload` injects the image into Antigravity editor as a valid dropped attachment.

### Category: Interactive Overlays
- **AC6:** When Antigravity displays a command permission banner, the web client renders an interactive overlay with clickable Allow and Deny buttons.
- **AC7:** Clicking Allow on mobile triggers `POST /click` with `perm:N`, causing Antigravity to execute the approved command immediately.
- **AC8:** When Antigravity displays an `ask_question` tool card, the mobile client renders multiple-choice options and a custom input box; clicking an option or submitting text dismisses the prompt and resumes agent execution.

### Category: Web Push Notifications
- **AC9:** `GET /api/vapid-key` and `GET /push/vapid-public-key` return a valid base64url-encoded VAPID public key.
- **AC10:** Subscribing to push notifications via `POST /api/subscriptions/push` successfully persists the subscription, and when `agentRunning` transitions to `false` (or a permission/question is blocked), mobile receives a push notification in `< 5 seconds` (when app is in background).

### Category: UI Responsiveness & Compatibility
- **AC11:** All 15 existing REST endpoints from previous audits continue to return HTTP 200 with valid JSON.
- **AC12:** Clean JavaScript execution with zero unhandled exceptions in mobile browser console.
- **AC13:** Fluid responsive layout supporting 360px width (smartphones) up to 1280px+ (desktop/tablet).
- **AC14:** Idle server memory remains `< 80MB` RAM and server startup completes in `< 5 seconds`.

---

## 6. Features Discovered Table

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|---|---|---|---|---|---|---|
| 1 | R1 CDP Mirroring | Auto Target Discovery | Scans ports 9000-9003 & DevToolsActivePort to find Workbench or Page target | None | CDP connection & target info | Returns 503 / retries every 3s | `ag2r/server.js:discoverTarget` |
| 2 | R1 CDP Mirroring | Execution Context Tracking | Listens to `Runtime.executionContextCreated/Destroyed` to route evals | Context lifecycle events | Context list & preferred ID | Context reset on cleared | `ag2r/server.js:connectCDP` |
| 3 | R1 CDP Mirroring | Focus Emulation | Forces Electron window to maintain active rendering even when minimized | `{enabled: true}` | Success status | Silently caught | `ag2r/server.js:465` |
| 4 | R1 CDP Mirroring | DOM Sanitization | 13-step pipeline stripping fixed/absolute, fixing div-in-span, CSS theme extraction | Raw chat container DOM | Sanitized HTML + CSS custom props | Returns fallback minimal HTML | `ag2r/src/cdp-scripts/capture.js` |
| 5 | R1 CDP Mirroring | Hash-Based Diffing | DJB2 string hashing over concatenated DOM snapshots to prevent re-render loops | Snapshot components | 36-base hash string | Falls back to re-render | `ag2r/server.js:hashString` |
| 6 | R1 CDP Mirroring | Cross-Context Captures | Evaluates across all contexts to capture isolated scheduled tasks, dialogs, running tasks | Script templates | HTML strings or null | Non-blocking try-catch | `ag2r/server.js:evaluateAcrossContexts` |
| 7 | R2 Interaction | Lexical Clipboard Paste | Dispatches DataTransfer ClipboardEvent to preserve formatting and newlines | Text string, appendMode | `{ok: true, method: 'button\|enter'}` | Fallback to `execCommand('insertText')` | `ag2r/src/cdp-scripts/inject-message.js` |
| 8 | R2 Interaction | Index-Based Click Dispatch | Tags interactive elements with prefix:index (`chat:N`, `left:N`, etc.) | `clickId`, `label` | `{ok: true, label: '...'}` | Label mismatch / index out of range | `ag2r/src/cdp-scripts/click-main.js` |
| 9 | R2 Interaction | Dropdown Hit-Testing | Dispatches pointerdown, mousedown, pointerup, mouseup, click for Radix popovers | `dropdown:N` | `{ok: true}` | Returns `no_portal` | `ag2r/src/cdp-scripts/click-main.js:335` |
| 10 | R2 Interaction | Burst Re-Capture | Schedules immediate snapshots (150ms, 400ms, 700ms) after click | Delay array | WS snapshot broadcast | Silently logs debug | `ag2r/server.js:fireBurstCaptures` |
| 11 | R2 Interaction | Stop Generation | Detects cancel tooltip button or lucide square icon | None | `{ok: true, method: '...'}` | Returns `{ok: false, reason: 'no_stop_button'}` | `ag2r/src/cdp-scripts/stop.js` |
| 12 | R2 Interaction | Image Drag & Drop | Injects File object via synthetic DragEvent sequence (dragenter, dragover, drop) | Base64 image, mime, filename | `{ok: true, method: 'drop'}` | Returns `{ok: false, reason: 'no_editor'}` | `ag2r/src/cdp-scripts/upload-image.js` |
| 13 | R2 Interaction | Native Value Setter | Bypasses React synthetic event wrappers on inputs via prototype descriptor set | Placeholder / clickId, text | `{ok: true, tag: '...'}` | Returns `element_not_found` | `ag2r/src/cdp-scripts/type-text.js` |
| 14 | R2 Interaction | Slash Command Trigger | Clears Lexical editor and pastes `/` to open macro picker | None | `{ok: true}` | Returns 503 if no editor | `ag2r/server.js:1534` |
| 15 | R3 Overlays | Permission Banner Capture | Detects radiogroup and Allow/Deny buttons, builds clickable modal | DOM search | `permissionHtml` | Ignored if ask_question active | `ag2r/src/cdp-scripts/capture.js:435` |
| 16 | R3 Overlays | ask_question Card Capture | Detects Submit + Skip buttons and radiogroup, tags options and buttons | DOM search | `askQuestionHtml` | Returns null if not present | `ag2r/src/cdp-scripts/capture.js:383` |
| 17 | R3 Overlays | Atomic Dialog Submit | Sets textarea value via React setter then clicks Submit in single flow | `text`, `clickId`, `label` | `{ok: true}` | Returns 400 if clickId missing | `ag2r/server.js:1444` |
| 18 | R3 Overlays | Portal Dialog & Popover | Captures direct body children with role="dialog" or fixed inset-0 | Body scan | `dialogHtml`, `dropdownHtml` | Returns null if none | `ag2r/src/cdp-scripts/capture.js:288` |
| 19 | R4 Web Push | VAPID Key Generation | Creates P-256 EC keypair on startup and stores in config | None | `vapid-keys.json` | Reuses existing keys | `ag2r/server.js:initVapid` |
| 20 | R4 Web Push | Attention State Detector | Scans sidebar ping dots (`.animate-unread-ping`) to classify command vs question | Snapshot attention items | Dispatches push notification | Skipped if visibleClients > 0 | `ag2r/server.js:checkAttentionState` |
| 21 | R4 Web Push | Stale Subscription Pruning | Automatically removes subscriptions that return HTTP 410 Gone | Push send failure | Pruned subscription list | Retries transient errors | `ag2r/server.js:206` |
| 22 | R4 Web Push | Push Pause / Resume | Allows user to temporarily silence mobile notifications from header bell | None | `{"ok": true, "paused": bool}` | Persisted in `push-paused.json` | `ag2r/server.js:1807` |
| 23 | R5 Frontend | Running Tasks Strip | Collapsible accordion showing background tool goals and subtasks | Snapshot `runningTasksHtml` | Interactive task row buttons | Collapses on header click | `ag2r/public/js/app.js:100` |
| 24 | R5 Frontend | Subagent View Mode | Shows yellow border, parent breadcrumbs, and "Back to parent" button | Server `isSubagentView` | UI banner & disabled main input | Navigates via click-conversation | `ag2r/public/js/app.js:106` |
| 25 | R5 Frontend | BTW Side Question Panel | Collapsible side-panel for auxiliary Q&A without primary thread interruption | Snapshot `btwHtml` | Side Q&A cards & response view | Renders in bottom bar wrapper | `ag2r/public/js/app.js:116` |
| 26 | R5 Frontend | Queued Comment System | Select text in Review Diff/Artifact -> FAB -> Add Comment -> Queued List -> Batch Send | Selection text + comment | Formatted batch quote markdown | Comments persist in localStorage | `ag2r/public/js/app.js:2562` |
| 27 | R5 Frontend | Voice Input Dictation | Uses Web Speech API (`webkitSpeechRecognition`) to dictate text | Microphone audio | Appends text to input | Gracefully handles unsupported | `ag2r/public/js/app.js:1410` |
| 28 | R5 Frontend | Model & Branch Badges | Displays active model and worktree branch chips in input bar | Snapshot `modelName`, `branchName` | Clickable chips opening picker | Disabled if not detected | `ag2r/public/js/app.js:1524` |
| 29 | R5 Frontend | Scroll-to-Bottom FAB | Appears when user scrolls >120px up; badge flashes when new content streams | Scroll event | Floating arrow button | Hidden when near bottom | `ag2r/public/js/app.js:1119` |
| 30 | R5 Frontend | Image Preview Strip | Previews staged camera/gallery uploads with remove buttons | File selection | Thumbnails above input | Cleared after send | `ag2r/public/js/app.js:1602` |
| 31 | R5 Frontend | Desktop Restart Trigger | Kill PID and relaunch Antigravity Electron in clean environment | `POST /restart-antigravity` | Process spawn | Fallback to graceful error | `ag2r/server.js:1218` |
| 32 | R5 Frontend | Image Proxying | Canvas export of local `blob:` / `vscode-file:` URLs to remote base64 data URLs | `GET /proxy-image?src=...` | Base64 PNG data URL | Returns null on draw fail | `ag2r/server.js:1087` |

---

## 7. Edge Cases & Robustness Behaviors

| # | Feature | Input / Condition | Observed Behavior & Safeguard |
|---|---|---|---|
| 1 | CDP Mirroring | Antigravity is minimized or in background | Focus emulation (`Emulation.setFocusEmulationEnabled`) prevents Electron from throttling DOM updates or deferring React batches. |
| 2 | CDP Mirroring | User is on "New Session" page (no chat container) | Fallback detects `#antigravity.agentSidePanelInputBox` and walks up to `.animate-fade-in` container, preventing null snapshot crash. |
| 3 | CDP Mirroring | Large code block or artifact in DOM | `maxTextLength` filter (80 chars) on `cursor-pointer` elements skips large content blocks while preserving interactive artifact cards. |
| 4 | Interaction | Rapid double-tap on Send button | Server-side deduplication check rejects identical message text received within a 2000ms window (`method: 'dedup'`). |
| 5 | Interaction | Image uploaded before text prompt | Server waits up to 3000ms (`waitForEditorImage`) for Lexical editor to render image decorator node before dispatching message text in append mode. |
| 6 | Interaction | Element index drifts during React re-render | `expectedLabel` validation compares target text with clicked element label; if mismatched, returns `label_mismatch` and dumps debug nearby elements instead of mis-clicking. |
| 7 | Overlays | Both `ask_question` and `permission` present | `ask_question` container guard prevents permission detector from capturing the ask_question radiogroup as a false permission banner. |
| 8 | Push Notifications | User is actively viewing the web app (`visibilityState === 'visible'`) | WebSocket client sends `visibility: true`; server tracks `visibleClients > 0` and suppresses push alerts to prevent noisy in-app spam while recording attention state. |
| 9 | Push Notifications | Mobile endpoint expired or unregistered (HTTP 410) | Push engine catches HTTP 410 and permanently removes the dead endpoint from `push-subscriptions.json`. |
| 10 | Mobile Keyboard | Mobile keyboard opens, resizing viewport | ResizeObserver on `#bottom-bar-wrapper` dynamically adjusts `#chat-area` bottom padding and scrolls active target into view without breaking layout. |
| 11 | Network Disconnect | Wi-Fi drops or laptop sleeps | WebSocket auto-reconnects with exponential backoff; connection dot turns red/yellow; last known snapshot stays rendered (never wipes content). |
| 12 | Commenting | Multiple comments added across different diff files | Comments are queued in `localStorage` with file URI, line snippet, and user text; "Send All" bundles them into a single formatted markdown prompt. |

---

## 8. Implementation Plan & Deliverables for Builder

The builder implementation should produce:
1. `cdp_bridge.py`: Async Python CDP client connecting via `websockets` to `127.0.0.1:9000`, containing discovery, execution context management, all 31 ported CDP JavaScript scripts, differential snapshot hashing, and burst capture scheduler.
2. `push_notifications.py`: VAPID key generator, subscription store, attention state tracker, and background push dispatcher using `pywebpush`.
3. `server.py`: FastAPI application serving all 32 WebRemote v6 endpoints + preserving all 15 legacy endpoints, WebSocket broadcaster on `/ws/stream`, static file server, mDNS zeroconf announcer on `wahyuai.local:8888`.
4. `static/index.html`: Fully updated HTML matching AG2R layout (Running Tasks strip, Subagent Bar, BTW panel, Input Bar, Attached Preview Strip, Comment Modals, Permission Overlays, Scheduled Tasks and History Overlays).
5. `static/css/app.css`: Updated dark-mode stylesheet supporting mobile touchscreen ergonomics, sticky headers, responsive FAB positioning, and overlay animations.
6. `static/js/app.js`: Updated client-side engine (WebSocket sync, snapshot renderer, click proxy, comment queue, push subscription, voice dictation, macro pills).
7. `static/sw.js`: Service Worker with Web Push notification receiver and deep-link click handler.
8. `requirements.txt`: Updated dependencies (`fastapi`, `uvicorn`, `psutil`, `requests`, `aiofiles`, `zeroconf`, `websockets`, `pywebpush`, `cryptography`).

---

**Specification Mining Status:** COMPLETE & AUTHORITATIVE  
*Ready for handoff to Orchestrator and Builder.*
