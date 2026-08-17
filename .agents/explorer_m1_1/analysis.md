# Deep Architectural Analysis: Chrome DevTools Protocol (CDP) Bridge for Antigravity WebRemote v6

## Executive Summary

This document presents a comprehensive technical analysis of the Chrome DevTools Protocol (CDP) client and bridge architecture for **Antigravity WebRemote v6 (Python Port)**. The analysis is based on the reference Node.js codebase (`_references_antigravity_mobile/ag2r`), the active Antigravity desktop Electron runtime (`Antigravity 2.8.1` / `Electron 41.0.2` / `Chrome 146.0.7680.72`), and validated against live runtime probes on Windows.

The CDP bridge is the foundational engine of Antigravity WebRemote, responsible for dynamic port discovery, WebSocket communication with the Electron renderer, V8 multi-context execution tracking, DOM snapshot capturing and sanitization, click proxying, and message injection.

---

## 1. Dynamic Port Discovery Architecture

### 1.1 DevToolsActivePort Location & Format
When Antigravity (Electron/Chromium) launches with remote debugging enabled (either via `--remote-debugging-port=0` for ephemeral port assignment or `--remote-debugging-port=9000`), Chromium writes the active port and browser endpoint to the user data directory:

- **Windows**: `%APPDATA%\Antigravity\DevToolsActivePort`  
  (e.g., `C:\Users\<User>\AppData\Roaming\Antigravity\DevToolsActivePort`)
- **macOS**: `~/Library/Application Support/Antigravity/DevToolsActivePort`
- **Linux**: `~/.config/Antigravity/DevToolsActivePort` or `$XDG_CONFIG_HOME/Antigravity/DevToolsActivePort`

#### File Structure
The file contains exactly two newline-separated lines:
```text
<PortNumber>
<BrowserWebSocketPath>
```
*Live Example Verified on Windows*:
```text
49250
/devtools/browser/1f03aa63-ea9e-4845-9c97-478e74b7b2d9
```
- **Line 1 (`port`)**: String representation of an integer (e.g. `49250`). Must be validated to ensure `1 <= port <= 65535`.
- **Line 2 (`browser_path`)**: The browser-level WebSocket debug endpoint URL path (e.g. `/devtools/browser/<uuid>`).

### 1.2 Multi-Stage Discovery & Fallback Probing Algorithm
In order to handle varying launch configurations (static port 9000, dynamic port from `DevToolsActivePort`, or restarted processes), the port discovery routine follows a deterministic multi-stage priority list:

```
┌─────────────────────────────────────────────────────────────┐
│                 read_devtools_port()                        │
│ 1. Check %APPDATA%\Antigravity\DevToolsActivePort           │
│ 2. Parse Line 1 as int in range [1, 65535]                  │
└──────────────────────────────┬──────────────────────────────┘
                               │ Found Port (e.g. 49250) or None
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                 build_candidate_ports()                     │
│ Candidate Set: [DTP_Port, CDP_PORT (9000), 9001, 9002, 9003]│
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│                   probe_candidate_ports()                   │
│ For each port in candidate list:                            │
│   HTTP GET http://127.0.0.1:<port>/json/list (timeout 0.5s) │
│   If 200 OK & non-empty JSON list:                          │
│     Match Target (Workbench -> Jetski -> Page)              │
│     Return (port, target_descriptor)                        │
└─────────────────────────────────────────────────────────────┘
```

#### Python Implementation Blueprint
```python
import os
import sys
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
import aiohttp

def get_devtools_active_port_path() -> Path:
    """Returns platform-specific path to DevToolsActivePort."""
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "Antigravity" / "DevToolsActivePort"
        return Path.home() / "AppData" / "Roaming" / "Antigravity" / "DevToolsActivePort"
    elif sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Antigravity" / "DevToolsActivePort"
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        base = Path(xdg) if xdg else Path.home() / ".config"
        return base / "Antigravity" / "DevToolsActivePort"

def read_devtools_port() -> Optional[int]:
    """Reads port from DevToolsActivePort if file exists and is valid."""
    dtp_path = get_devtools_active_port_path()
    try:
        if dtp_path.is_file():
            content = dtp_path.read_text(encoding="utf-8").strip()
            lines = content.splitlines()
            if lines:
                port = int(lines[0].strip())
                if 0 < port < 65536:
                    return port
    except Exception:
        pass
    return None
```

---

## 2. Async CDP WebSocket Connection & Target Management

### 2.1 Target Discovery & Priority Matching
When querying `http://127.0.0.1:<port>/json/list`, Chrome returns a list of target objects:
```json
[
  {
    "description": "",
    "devtoolsFrontendUrl": "https://...",
    "id": "FADDB104632B2EE242C2E4A2F5B09E1B",
    "title": "Bismillah",
    "type": "page",
    "url": "https://127.0.0.1:49253/c/63fb64ac-9344-46a1-8d60-a891ba0835d8?section=...",
    "webSocketDebuggerUrl": "ws://127.0.0.1:49250/devtools/page/FADDB104632B2EE242C2E4A2F5B09E1B"
  },
  {
    "description": "",
    "id": "4C7FFA98C170590429124B08F6748466",
    "title": "",
    "type": "worker",
    "url": "",
    "webSocketDebuggerUrl": "ws://127.0.0.1:49250/devtools/page/4C7FFA98C170590429124B08F6748466"
  }
]
```

#### Target Matching Hierarchy
1. **Priority 1 (Workbench)**: Target URL containing `workbench.html` or title containing `workbench` (legacy VS Code / Electron shells).
2. **Priority 2 (Jetski/Launchpad)**: Target URL containing `jetski` or title exactly matching `Launchpad`.
3. **Priority 3 (Page Target)**: Any target where `type == "page"`. In Antigravity 2.x, the main application window is a `page` target whose URL points to `https://127.0.0.1:<internal_port>/c/<session_uuid>` and whose title matches the session title (e.g., `Bismillah`).

### 2.2 Connection Lifecycle & Session Management
1. **WebSocket Connect**: Connect directly to `target["webSocketDebuggerUrl"]` using `websockets.connect(..., max_size=100*1024*1024)`. Direct page connection operates in root session mode without requiring explicit `sessionId` multiplexing headers.
2. **Domain Initialization**:
   - `Runtime.enable`: Initiates V8 execution context tracking. Immediately triggers `Runtime.executionContextCreated` events for all active contexts.
   - `Emulation.setFocusEmulationEnabled({ "enabled": True })`: Crucial setting in Electron! Without focus emulation, Chromium defers background window rendering and batches React DOM updates, causing expanded cards or dropdowns to appear empty until the desktop window is physically clicked.
3. **Automatic Reconnection**:
   - On disconnect / socket drop:
     - Mark `is_connected = False`.
     - Clear contexts: `_contexts.clear()`, `_preferred_context_id = None`.
     - Notify downstream WebSocket clients (`broadcastStatus({"type": "connection", "cdpConnected": False})`).
     - Schedule asynchronous retry loop every 3.0s with port re-probing (since Antigravity restart may allocate a new ephemeral port).

---

## 3. Multi-Context Execution Tracking

### 3.1 Understanding Electron Contexts
Electron renderers contain multiple distinct V8 execution contexts within a single renderer process:

| Context Type | `name` | `isDefault` | Role in Antigravity |
|---|---|---|---|
| **Main World Context** | `""` | `True` | Lexical text editor, React state tree, chat messages container, active input box, React synthetic event handlers. |
| **Electron Isolated Context** | `"Electron Isolated Context"` | `False` | Electron internal APIs, preload scripts, extension portals, certain Scheduled Tasks pages, and popup menus. |

### 3.2 CDP Context Lifecycle Events
The CDP client must maintain a real-time registry of execution contexts by handling three asynchronous events from the `Runtime` domain:

1. **`Runtime.executionContextCreated`**:
   ```json
   {
     "method": "Runtime.executionContextCreated",
     "params": {
       "context": {
         "id": 1,
         "origin": "https://127.0.0.1:49253",
         "name": "",
         "auxData": { "isDefault": true, "type": "default", "frameId": "..." }
       }
     }
   }
   ```
   *Action*: Register context in `_contexts[id] = context`.

2. **`Runtime.executionContextDestroyed`**:
   ```json
   {
     "method": "Runtime.executionContextDestroyed",
     "params": { "executionContextId": 1 }
   }
   ```
   *Action*: Delete from `_contexts`. If `_preferred_context_id == executionContextId`, reset `_preferred_context_id = None`.

3. **`Runtime.executionContextsCleared`**:
   ```json
   {
     "method": "Runtime.executionContextsCleared",
     "params": {}
   }
   ```
   *Action*: Emitted when page navigates or reloads. Reset `_contexts.clear()` and `_preferred_context_id = None`.

---

## 4. Context Evaluation Helpers & Execution Strategies

Different operations require distinct evaluation paradigms to prevent race conditions, memory leaks, and duplicate execution.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                           EVALUATION STRATEGIES                          │
├────────────────────────────┬────────────────────────────┬────────────────┤
│ evaluateInBrowser          │ evaluateAcrossContexts     │ evaluateInCtx  │
├────────────────────────────┼────────────────────────────┼────────────────┤
│ • Locks preferredContextId │ • Iterates all contexts    │ • Strict ctxId │
│ • Prioritizes default ctx  │ • First NON-NULL wins      │ • No fallback  │
│ • For DOM snapshots / read │ • For portals & sched tasks│ • For mutations│
└────────────────────────────┴────────────────────────────┴────────────────┘
```

### 4.1 `evaluateInBrowser(expression, opts)`
- **Purpose**: Primary read execution for `captureSnapshot()`, left sidebar extraction, and standard click dispatching.
- **Sorting Logic**:
  1. `_preferred_context_id` (context that previously evaluated successfully).
  2. `isDefault == True` contexts (Main World).
  3. Isolated contexts.
- **Context Locking**: Upon receiving the first successful result without `exceptionDetails`, locks `_preferred_context_id = ctx.id`. This prevents *hash oscillation* where alternate polling ticks evaluate against different contexts and trigger false-positive diff broadcasts.

### 4.2 `evaluateAcrossContexts(expression, opts)`
- **Purpose**: Capturing elements rendered exclusively inside Electron Isolated Contexts or dynamic React portals:
  - `RUNNING_TASKS_SCRIPT`
  - `SCHEDULED_TASKS_SCRIPT`
  - `CONVERSATION_HISTORY_SCRIPT`
  - `SCHEDULED_TASKS_DIALOG_SCRIPT`
  - `buildCaptureKebabMenuScript()`
  - `DISMISS_SCHEDULED_TASKS_SCRIPT`
  - `buildTypeTextScript()`
- **Behavior**: Evaluates across every registered context in sequence and returns the **first non-null** return value. Does *not* lock `_preferred_context_id`.

### 4.3 `findEditorContext()` (Detect-Before-Execute)
- **Problem**: Side-effect operations (like message injection or clicking stop) must NEVER execute in a fallthrough loop across contexts, because if an async promise gets garbage-collected after pasting text, a fallback execution in the second context will cause a **double-send** or **duplicate action**.
- **Solution**: Execute `HAS_VISIBLE_EDITOR_SCRIPT` synchronously (no `awaitPromise` -> zero GC risk):
  ```javascript
  (() => {
    const candidates = document.querySelectorAll(
      '[data-lexical-editor="true"], [contenteditable="true"][role="textbox"], [contenteditable="true"]'
    );
    const hasLexicalNode = !!document.querySelector('[data-lexical-editor="true"]');
    for (const el of candidates) {
      if (el.offsetParent !== null) {
        if (hasLexicalNode && !el.__lexicalEditor) continue;
        return true;
      }
    }
    return false;
  })()
  ```
- Returns the exact `contextId` of the Main World where Lexical is mounted, or `None`.

### 4.4 `evaluateInContext(contextId, expression)`
- **Purpose**: Single-context targeted execution with zero fallthrough.
- Used exclusively with `findEditorContext()` for:
  - `buildInjectScript(text, appendMode)`
  - `STOP_SCRIPT`
  - `CLICK_SEND_BUTTON_SCRIPT`
  - `/clear-editor`
  - `/type-slash`

---

## 5. Error Handling, Timeout Mechanics, and Async Concurrency in Python

### 5.1 Asynchronous Concurrency Model (`websockets` + `asyncio`)
In Python 3.12, CDP WebSocket frames arrive concurrently (both command responses and unsolicited push events like `Runtime.consoleAPICalled` and `Runtime.executionContextCreated`).

A naive synchronous or sequential `ws.recv()` will fail because incoming console log frames will intercept command reply futures.

#### Concurrency Blueprint
1. **Background Reader Task (`_read_loop`)**: Runs continuously on the WebSocket connection.
2. **Command Dispatch Registry (`_pending_commands: Dict[int, asyncio.Future]`)**:
   - `send(method, params)` creates an `asyncio.Future`, stores it by incrementing `req_id`, sends the JSON-RPC frame, and awaits `asyncio.wait_for(fut, timeout)`.
   - `_read_loop` receives frame:
     - If frame has `"id"`: pops future from `_pending_commands` and sets result or exception.
     - If frame has `"method"`: dispatches to event router (`Runtime.executionContextCreated`, etc.).
     - Ignores high-volume noise events (`Runtime.consoleAPICalled`).

### 5.2 Timeout Mechanics
- **Probing Timeouts**: 0.5s–1.0s for `/json/list` HTTP probing and `findEditorContext`.
- **Standard Evaluation Timeouts**: 5.0s for `captureSnapshot` and `clickElement`.
- **Heavy Mutation Timeouts**: 10.0s for `uploadImage` (base64 payload + synthetic drag-drop reconciliation).
- On timeout: Cancel future, clean up pending map, and log without crashing the server loop.

### 5.3 Snapshot Caching & State Hashing Policy
- **Cache Preservation Rule**: When `captureSnapshot()` returns null (e.g. during a brief DOM transition or modal dismissal), **never wipe `cachedSnapshot`**. Preserve last known valid snapshot so web clients do not flicker to blank screens.
- **DJB2 State Hashing**: Hash composite state containing 18 discrete flags (HTML, sidebar HTML, sidebar signature, dropdowns, dialogs, settings, askQuestion, permission, runningTasks, scheduledTasks, subagents, modelName, environmentName, branchName). Only push updates to clients when the composite hash changes or `agentRunning` transitions.

---

## 6. Complete 31 CDP Scripts Inventory & Purpose

| # | Script File | Purpose | Context Strategy |
|---|---|---|---|
| 1 | `_shared.js` | Helper functions `tagInteractives` and `untagAll` for tagging `data-ag-click-id` | Embedded in scripts |
| 2 | `capture.js` | Full DOM capture, 14-step cleaning, CSS harvest, attention state, subagent detection | `evaluateInBrowser` |
| 3 | `click-main.js` | Main click dispatcher for `chat`, `left`, `right`, `dropdown`, `dialog`, `settings`, `ask`, `perm`, `btw`, `model`, `project` | `evaluateInBrowser` / `evaluateAcrossContexts` |
| 4 | `inject-message.js` | Injects text via `DataTransfer` ClipboardEvent into Lexical editor and triggers send | `findEditorContext` -> `evaluateInContext` |
| 5 | `has-visible-editor.js` | Synchronous probe checking if visible Lexical editor exists in context | `findEditorContext` |
| 6 | `stop.js` | Clicks cancel tooltip / square stop button to halt agent generation | `findEditorContext` -> `evaluateInContext` |
| 7 | `upload-image.js` | Synthesizes `DragEvent` (dragenter, dragover, drop) with base64 File into editor | `evaluateInBrowser` |
| 8 | `click-send-button.js` | Clicks send button after image attachment | `findEditorContext` -> `evaluateInContext` |
| 9 | `check-editor-image.js` | Polls until image decorator node appears in Lexical DOM | `evaluateInBrowser` |
| 10 | `capture-dropdown.js` | Captures listbox dropdowns and kebab context menus from Radix portals | `evaluateInBrowser` & `evaluateAcrossContexts` |
| 11 | `running-tasks.js` | Extracts `#running-tasks` bar and task stop buttons | `evaluateAcrossContexts` |
| 12 | `scheduled-tasks.js` | Extracts Scheduled Tasks page and syncs input attributes | `evaluateAcrossContexts` |
| 13 | `scheduled-tasks-dialog.js`| Extracts New Scheduled Task modal form | `evaluateAcrossContexts` |
| 14 | `click-task.js` | Clicks task rows or task stop button | `evaluateAcrossContexts` |
| 15 | `click-sched.js` | Clicks items on Scheduled Tasks page | `evaluateAcrossContexts` |
| 16 | `click-sched-portal.js` | Clicks dropdown/popover options inside scheduled tasks | `evaluateInBrowser` -> `evaluateAcrossContexts` |
| 17 | `click-sched-dialog.js` | Clicks buttons/inputs inside scheduled task dialog | `evaluateAcrossContexts` |
| 18 | `dismiss-scheduled-tasks.js`| Navigates back from task detail or list view | `evaluateAcrossContexts` |
| 19 | `conversation-history.js` | Extracts `/history` list and navigation elements | `evaluateAcrossContexts` |
| 20 | `click-history.js` | Clicks conversation entry in history list | `evaluateAcrossContexts` |
| 21 | `click-conversation.js` | Navigates to conversation by UUID from push notification click | `evaluateInBrowser` |
| 22 | `right-sidebar.js` | On-demand capture of full right sidebar (overview/diff) | `evaluateInBrowser` |
| 23 | `close-right-sidebar.js` | Syncs closing of right sidebar | `evaluateInBrowser` |
| 24 | `select-overview-tab.js` | Selects Overview tab in right sidebar | `evaluateInBrowser` |
| 25 | `proxy-image.js` | Renders unresolvable `blob:`/`vscode-file:` images to canvas and returns base64 | `evaluateInBrowser` |
| 26 | `type-text.js` | Types into input/textarea using React `nativeInputValueSetter` | `evaluateAcrossContexts` |
| 27 | `expand-left-sidebar.js` | Expands collapsed left sidebar | `evaluateInBrowser` |
| 28 | `dismiss-settings.js` | Clicks Go Back on settings overlay | `evaluateInBrowser` |
| 29 | `copy-response.js` | Intercepts clipboard markdown response for chat copy | `evaluateInBrowser` |
| 30 | `discover.js` | DOM discovery diagnostic tool | `evaluateInBrowser` |
| 31 | `_shared.js` | (Counted in total 31 CDP script assets) | - |

---

## 7. Python Implementation Architecture for `cdp_bridge.py`

The Python implementation in `cdp_bridge.py` will consist of three cohesive classes:

1. **`CDPPortDiscovery`**:
   - `discover_port_and_target()`: Handles Windows `%APPDATA%` `DevToolsActivePort` reading and fallback probing across `9000..9003`.
2. **`AsyncCDPClient`**:
   - Manages raw WebSocket connection, request ID counter, `_pending_commands` futures, `_read_loop` message pump, and execution context tracking (`_contexts`).
   - Implements evaluation helpers: `evaluate_in_browser`, `evaluate_across_contexts`, `evaluate_in_context`, `find_editor_context`.
3. **`CDPBridge` (High-Level Service)**:
   - Houses the 31 CDP JavaScript script templates.
   - Exposes clean async API to `server.py`:
     - `capture_snapshot() -> Dict[str, Any]`
     - `inject_message(text, append_mode=False) -> Dict[str, Any]`
     - `click_element(click_id, label) -> Dict[str, Any]`
     - `stop_generation() -> Dict[str, Any]`
     - `upload_image(base64_data, mimetype, filename) -> Dict[str, Any]`
     - `type_text(placeholder, click_id, text) -> Dict[str, Any]`
     - `execute_script(script_name, args) -> Any`
