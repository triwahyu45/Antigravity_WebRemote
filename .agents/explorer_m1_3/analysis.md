# Comprehensive Investigation: State Hashing, Interface Contracts, and Testing Strategy

## Executive Summary
This report provides the definitive architectural blueprint and verification specification for Milestone 1 (M1) of **Antigravity WebRemote v6 (Python Port)**. It covers:
1. **DJB2 Composite State Hashing**: The exact mathematical algorithm, 32-bit bitwise wrapping semantics, base-36 string encoding, property ordering across the base DOM and 17 state flags (18 tokens total), normalization rules, collision resistance, and cross-runtime verification between Node.js AG2R and Python.
2. **Interface Contracts**: The complete set of data classes, method signatures, parameter types, return models, and exception handling specifications exposed by `cdp_bridge.py` to `server.py`, `push_notifications.py`, and downstream interaction handlers.
3. **Testing Strategy**: A modular test suite architecture for `tests/test_cdp_bridge.py` and `tests/harness.py`, featuring an asynchronous mock Chrome DevTools Protocol (CDP) WebSocket server, multi-context lifecycle emulation, script execution fixtures, and exhaustive unit/integration test cases.

---

## 1. DJB2 Composite State Hashing (17 State Properties)

### 1.1 Algorithm Mechanics and Bitwise Semantics
In Node.js AG2R (`ag2r/server.js:285-291`), the state hash function is implemented as:
```javascript
function hashString(str) {
  let hash = 5381;
  for (let i = 0; i < str.length; i++) {
    hash = ((hash << 5) + hash) + str.charCodeAt(i);
  }
  return (hash >>> 0).toString(36);
}
```

#### Detailed Execution Step-by-Step:
1. **Initial Value**: `hash = 5381` (standard DJB2 initial prime seed).
2. **Per-Character Iteration**:
   - `hash << 5`: In JavaScript, bitwise shift operators evaluate the left operand as a signed 32-bit integer `ToInt32(hash) << 5`.
   - `+ hash`: Adds the current accumulator (`hash * 33`).
   - `+ str.charCodeAt(i)`: Adds the UTF-16 code unit of character `i`.
   - In 32-bit integer arithmetic with overflow wrapping, this is equivalent to `hash = (hash * 33 + char_code) & 0xFFFFFFFF`.
3. **Unsigned 32-bit Conversion**:
   - `(hash >>> 0)`: Zero-fill right shift converts the signed 32-bit integer into an unsigned 32-bit integer in the range `[0, 4294967295]`.
4. **Base-36 String Encoding**:
   - `.toString(36)`: Encodes the unsigned integer into base 36 using character set `0-9` followed by `a-z` (lowercase).

### 1.2 Python Implementation
The exact Python implementation matching Node.js JavaScript behavior across all character lengths, Unicode surrogate pairs, and UTF-16 encodings is:

```python
def compute_djb2_hash(s: str) -> str:
    """
    Computes a 32-bit DJB2 hash encoded as a base-36 string,
    fully compatible with Node.js AG2R hashString(str).
    """
    if not s:
        # Base case for empty string: 5381 in base-36 is '45h'
        return "45h"
    
    # Encode as UTF-16LE to match JS String.prototype.charCodeAt (UTF-16 code units)
    utf16_bytes = s.encode("utf-16le")
    code_units = [
        int.from_bytes(utf16_bytes[i : i + 2], "little")
        for i in range(0, len(utf16_bytes), 2)
    ]
    
    hash_val = 5381
    for code in code_units:
        # Bitwise 32-bit signed shift and add
        signed_hash = ((hash_val & 0xFFFFFFFF) ^ 0x80000000) - 0x80000000
        shifted = (signed_hash << 5) & 0xFFFFFFFF
        shifted_signed = ((shifted ^ 0x80000000) - 0x80000000)
        hash_val = shifted_signed + hash_val + code
    
    uint32_val = int(hash_val) % (2**32)
    
    # Convert uint32 to base-36 lowercase string
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    if uint32_val == 0:
        return "0"
    
    res = []
    n = uint32_val
    while n > 0:
        res.append(chars[n % 36])
        n //= 36
    return "".join(reversed(res))
```

### 1.3 Verified Known Test Vectors
The following test vectors have been executed and verified across both Node.js (v20+) and Python (3.12+):

| Input String | Expected DJB2 Base-36 Hash | Verification Result |
| :--- | :--- | :--- |
| `""` (empty string) | `"45h"` | PASS |
| `"hello"` | `"4bj995"` | PASS |
| `"<div>Hello World!</div>10nullundefined"` | `"iuqgmx"` | PASS |
| `"Halo Dunia 🚀 123!"` (Unicode + Emoji) | `"1t6thvy"` | PASS |
| 10,000 repetitions of `<div></div>` (50KB) | `"d7440d"` | PASS |
| 10,000 repetitions of `"hello world "` (120KB) | `"1m5e75x"` | PASS |
| 100,000 sequential ASCII chars | `"vmhiid"` | PASS |

### 1.4 Composite State String: Exact Property Ordering & Normalization
The state hash is computed over a composite string formed by concatenating the base HTML DOM and **17 state properties** (18 tokens total). 

In `ag2r/server.js` (lines 749-768, 802-821):
```javascript
const compositeString =
  snapshot.html +
  (snapshot.leftSidebarHtml || '') +
  (snapshot.sidebarSignature || '') +
  (snapshot.isSidebarOpen ? '1' : '0') +
  (snapshot.dropdownHtml || '') +
  (snapshot.dialogHtml || '') +
  (snapshot.settingsHtml || '') +
  (snapshot.askQuestionHtml || '') +
  (snapshot.permissionHtml || '') +
  (snapshot.runningTasksHtml || '') +
  (snapshot.scheduledTasksHtml || '') +
  (snapshot.scheduledTasksDialogHtml || '') +
  (snapshot.conversationHistoryHtml || '') +
  (snapshot.subagentInfoHtml || '') +
  (snapshot.btwHtml || '') +
  (snapshot.modelName || '') +
  (snapshot.environmentName || '') +
  (snapshot.branchName || '');
```

#### Complete Specification of the 18 Composite Tokens:

| # | Property Key | Source Script | Description / Content | Normalization Rule |
| :--- | :--- | :--- | :--- | :--- |
| **0** | `html` | `capture.js` | Primary sanitized chat DOM innerHTML | `snapshot.html or ""` |
| **1** | `leftSidebarHtml` | `capture.js` (step 14) | Left sidebar outerHTML (`.bg-sidebar`) | `snapshot.leftSidebarHtml or ""` |
| **2** | `sidebarSignature` | `capture.js` (step 15) | Right sidebar tab signature (e.g. `overview*,review,diff`) | `snapshot.sidebarSignature or ""` |
| **3** | `isSidebarOpen` | `capture.js` (step 15) | Right sidebar collapse container visibility state | `"1" if snapshot.isSidebarOpen else "0"` |
| **4** | `dropdownHtml` | `capture.js` (step 8) | Radix/portal dropdown (`role="listbox"`) outerHTML | `snapshot.dropdownHtml or ""` |
| **5** | `dialogHtml` | `capture.js` (step 8) | Modal dialog (`role="dialog"` or `.fixed.inset-0`) outerHTML | `snapshot.dialogHtml or ""` |
| **6** | `settingsHtml` | `capture.js` (step 8b) | Settings overlay card outerHTML inside `#root` | `snapshot.settingsHtml or ""` |
| **7** | `askQuestionHtml` | `capture.js` (step 10) | Interactive `ask_question` tool card outerHTML | `snapshot.askQuestionHtml or ""` |
| **8** | `permissionHtml` | `capture.js` (step 11) | Interactive command permission / approval banner outerHTML | `snapshot.permissionHtml or ""` |
| **9** | `runningTasksHtml` | `running-tasks.js` | Running tasks strip / background tasks bar outerHTML | `snapshot.runningTasksHtml or ""` |
| **10** | `scheduledTasksHtml` | `scheduled-tasks.js` | Scheduled tasks full view outerHTML | `snapshot.scheduledTasksHtml or ""` |
| **11** | `scheduledTasksDialogHtml` | `scheduled-tasks-dialog.js`| New Scheduled Task form modal outerHTML | `snapshot.scheduledTasksDialogHtml or ""` |
| **12** | `conversationHistoryHtml` | `conversation-history.js` | Conversation history modal outerHTML | `snapshot.conversationHistoryHtml or ""` |
| **13** | `subagentInfoHtml` | `capture.js` (step 14b) | Subagent warning & "Open overview" panel outerHTML | `snapshot.subagentInfoHtml or ""` |
| **14** | `btwHtml` | `capture.js` (step 12/btw) | `/btw` side-question box container outerHTML | `snapshot.btwHtml or ""` |
| **15** | `modelName` | `capture.js` (step 13) | Current model selector text (e.g., `"Gemini 2.5 Pro"`) | `snapshot.modelName or ""` |
| **16** | `environmentName` | `capture.js` (step 12) | Selected workspace environment (e.g., `"Local"`, `"Worktree"`) | `snapshot.environmentName or ""` |
| **17** | `branchName` | `capture.js` (step 12) | Selected git default branch name | `snapshot.branchName or ""` |

### 1.5 Hash Lifecycle & Differential Broadcasting
1. **Poll Loop / Capture Trigger**:
   - `captureSnapshot()` gathers DOM and evaluates cross-context scripts.
   - Composite string is constructed in the exact sequence 0..17.
   - `hash = compute_djb2_hash(composite_string)`.
2. **Change Detection**:
   - If `hash != last_snapshot_hash`:
     - Cache updated: `cached_snapshot = snapshot; cached_snapshot.hash = hash; last_snapshot_hash = hash`.
     - WebSocket broadcast: `{"type": "snapshot", "hash": hash, "agentRunning": snapshot.agentRunning, "timestamp": iso_time}`.
   - Else if `hash == last_snapshot_hash` AND `snapshot.agentRunning != cached_snapshot.agentRunning`:
     - Content is unchanged, but agent execution status transitioned (e.g., agent stopped or started).
     - Lightweight status broadcast: `{"type": "status", "agentRunning": snapshot.agentRunning}`.
   - Else:
     - No transmission (saves client battery and rendering overhead).

---

## 2. Interface Contracts (`cdp_bridge.py`)

### 2.1 Data Models (Pydantic / Dataclasses)

```python
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

@dataclass
class CDPTarget:
    id: str
    title: str
    type: str
    url: str
    webSocketDebuggerUrl: str
    devtoolsFrontendUrl: Optional[str] = None

@dataclass
class ExecutionContext:
    id: int
    origin: str
    name: str
    aux_data: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def is_default(self) -> bool:
        return bool(self.aux_data.get("isDefault", False))

@dataclass
class AttentionItem:
    id: str               # Conversation UUID
    type: str             # "question" | "command" | "completed"
    name: str             # Conversation title / label

@dataclass
class ScrollInfo:
    scrollTop: int
    scrollHeight: int
    clientHeight: int

@dataclass
class DOMSnapshot:
    html: str
    css: str
    agentRunning: bool
    hash: str = ""
    timestamp: str = ""
    scrollInfo: Optional[ScrollInfo] = None
    leftSidebarHtml: Optional[str] = None
    sidebarAttentionItems: List[AttentionItem] = field(default_factory=list)
    sidebarSignature: Optional[str] = None
    isSidebarOpen: bool = False
    isNewSessionPage: bool = False
    isInputBoxHidden: bool = False
    isSubagentView: bool = False
    parentConversationName: str = ""
    subagentInfoHtml: Optional[str] = None
    dropdownHtml: Optional[str] = None
    dialogHtml: Optional[str] = None
    settingsHtml: Optional[str] = None
    activeArtifactUri: Optional[str] = None
    activeFileUri: Optional[str] = None
    askQuestionHtml: Optional[str] = None
    permissionHtml: Optional[str] = None
    runningTasksHtml: Optional[str] = None
    scheduledTasksHtml: Optional[str] = None
    scheduledTasksDialogHtml: Optional[str] = None
    conversationHistoryHtml: Optional[str] = None
    btwHtml: Optional[str] = None
    environmentName: Optional[str] = None
    branchName: Optional[str] = None
    modelName: Optional[str] = None

@dataclass
class ActionResult:
    ok: bool
    error: Optional[str] = None
    data: Optional[Dict[str, Any]] = None
```

### 2.2 CDPBridge Public API Specification

```python
class CDPBridge:
    """
    Asynchronous Chrome DevTools Protocol (CDP) Bridge for Antigravity Desktop.
    Connects to Antigravity Electron process, manages execution contexts,
    evaluates CDP scripts, captures live DOM snapshots, and proxies user interactions.
    """

    def __init__(
        self,
        host: str = "127.0.0.1",
        port: Optional[int] = None,
        poll_interval: float = 0.5,
        app_data_dir: Optional[str] = None,
    ) -> None:
        """
        Initializes CDP Bridge configuration and connection parameters.
        :param host: CDP host (default 127.0.0.1)
        :param port: CDP port override (if None, dynamic discovery is used)
        :param poll_interval: Polling frequency for DOM capture in seconds
        :param app_data_dir: Custom path to Antigravity AppData (for DevToolsActivePort)
        """
        ...

    # --- Connection & Discovery Lifecycle ---
    def read_devtools_port(self) -> Optional[int]:
        """
        Reads DevTools port from %APPDATA%\\Antigravity\\DevToolsActivePort.
        Line 1 contains the listening port; Line 2 contains the browser WebSocket endpoint.
        Returns port integer, or None if unreadable/absent.
        """
        ...

    async def discover_target(self) -> Optional[tuple[int, CDPTarget]]:
        """
        Probes discovered DevTools port and fallback ports 9000..9003.
        Fetches http://{host}:{port}/json/list.
        Applies priority selection:
          1. Workbench target (url includes 'workbench.html' or title includes 'workbench')
          2. Jetski/Launchpad target (url includes 'jetski' or title == 'Launchpad')
          3. Any page target (type == 'page')
        Returns (port, CDPTarget) tuple, or None.
        """
        ...

    async def connect(self) -> bool:
        """
        Discovers target, opens WebSocket connection, enables Runtime domain,
        subscribes to executionContextCreated/Destroyed/Cleared events,
        and enables Emulation.setFocusEmulationEnabled.
        Returns True on successful connection, False otherwise.
        """
        ...

    async def disconnect(self) -> None:
        """
        Gracefully closes active CDP WebSocket session, cancels background polling tasks,
        and clears context caches.
        """
        ...

    async def test_connect(self) -> bool:
        """
        Lightweight diagnostic method to test if Antigravity CDP is reachable.
        Used directly in acceptance tests:
          python -c "import asyncio; from cdp_bridge import CDPBridge; b=CDPBridge(); asyncio.run(b.test_connect())"
        """
        ...

    @property
    def is_connected(self) -> bool:
        """Returns True if WebSocket client is active and Runtime is enabled."""
        ...

    # --- Multi-Context Evaluation Engine ---
    async def evaluate_in_browser(
        self,
        expression: str,
        await_promise: bool = True,
        return_by_value: bool = True,
        opts: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Evaluates JavaScript expression across contexts in priority order:
          1. Preferred Context (locked from previous successful eval)
          2. Default Contexts (auxData.isDefault == True)
          3. Other Contexts (isolated extension worlds)
        Locks to the first successfully evaluating context.
        """
        ...

    async def evaluate_across_contexts(
        self,
        expression: str,
        await_promise: bool = True,
        return_by_value: bool = True,
        opts: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Evaluates expression across all contexts and returns the FIRST NON-NULL result.
        Essential for portal elements, running tasks, and scheduled tasks that may live
        in isolated contexts.
        """
        ...

    async def evaluate_in_context(
        self,
        context_id: int,
        expression: str,
        await_promise: bool = True,
        return_by_value: bool = True,
    ) -> Any:
        """
        Evaluates expression in a specific execution context without fallthrough.
        Used for single-execution side-effect scripts (injectMessage, stopGeneration).
        """
        ...

    async def find_editor_context(self) -> Optional[int]:
        """
        Runs synchronous HAS_VISIBLE_EDITOR_SCRIPT across contexts to locate
        the exact context containing an active Lexical editor.
        Returns contextId, or None if no editor is visible.
        """
        ...

    # --- Snapshot Capture & State Hashing ---
    async def capture_snapshot(self) -> Optional[DOMSnapshot]:
        """
        Executes CAPTURE_SCRIPT, evaluates cross-context supplements (running tasks,
        scheduled tasks, conversation history, portals), computes the DJB2 composite
        state hash, and returns a fully populated DOMSnapshot instance.
        """
        ...

    def compute_composite_hash(self, snapshot: DOMSnapshot) -> str:
        """
        Constructs the 18-token composite string and computes the DJB2 base-36 hash.
        """
        ...

    async def fire_burst_captures(self, delays: Optional[List[float]] = None) -> None:
        """
        Fires rapid background snapshot recaptures at intervals (default: [0.1, 0.3, 0.6, 1.0]s)
        to capture instant DOM changes after user actions (e.g. portal opens).
        """
        ...

    # --- User Interaction Proxies ---
    async def inject_message(self, text: str, append_mode: bool = False) -> ActionResult:
        """
        Injects text into Antigravity Lexical editor via synthetic ClipboardEvent paste
        and clicks the send button.
        """
        ...

    async def click_element(
        self,
        click_id: str,
        click_type: str = "chat",
        label: Optional[str] = None,
    ) -> ActionResult:
        """
        Dispatches click to element tagged with data-ag-click-id.
        Supported click types: 'chat', 'left', 'task', 'sched', 'sched-portal',
        'sched-dialog', 'ask', 'perm', 'subinfo', 'btw'.
        """
        ...

    async def stop_generation(self) -> ActionResult:
        """
        Finds and clicks Antigravity stop button / cancel icon to halt LLM generation.
        """
        ...

    async def upload_image(
        self,
        base64_data: str,
        mime_type: str = "image/png",
        filename: str = "upload.png",
    ) -> ActionResult:
        """
        Synthesizes a File DragEvent / DataTransfer drop into the Lexical editor.
        """
        ...

    async def type_text(self, selector: str, text: str) -> ActionResult:
        """
        Types text into an input or textarea element using native value setter bypass.
        """
        ...

    async def execute_script(
        self,
        script_name: str,
        args: Optional[Dict[str, Any]] = None,
    ) -> Any:
        """
        Executes any named script from the 31 CDP script catalog.
        """
        ...
```

---

## 3. Downstream Interface Contracts

### 3.1 `cdp_bridge.py` ↔ `server.py`
`server.py` relies on `CDPBridge` for:
1. **Application Lifecycle**:
   - FastAPI `lifespan` startup hook initializes `bridge = CDPBridge()` and launches background polling task.
   - FastAPI shutdown hook calls `await bridge.disconnect()`.
2. **WebSocket `/ws/stream` Streaming**:
   - Polling loop calls `snapshot = await bridge.capture_snapshot()`.
   - On change (`snapshot.hash != last_hash`), server broadcasts JSON payload:
     ```json
     {
       "type": "snapshot",
       "hash": "...",
       "agentRunning": false,
       "timestamp": "2026-08-17T01:30:00.000Z"
     }
     ```
   - On HTTP `GET /snapshot`, server returns cached snapshot:
     ```python
     @app.get("/snapshot")
     async def get_snapshot():
         if not cached_snapshot:
             return {"html": "Waiting for Antigravity...", "css": "", "agentRunning": False}
         # Return all snapshot properties
         return asdict(cached_snapshot)
     ```
3. **Action REST Endpoints**:
   - `POST /api/chat/send` $\rightarrow$ `await bridge.inject_message(req.text)`
   - `POST /api/cdp/click` $\rightarrow$ `await bridge.click_element(req.clickId, req.clickType)`
   - `POST /api/cdp/stop` $\rightarrow$ `await bridge.stop_generation()`
   - `POST /api/upload-image` $\rightarrow$ `await bridge.upload_image(req.base64, req.mimeType)`
   - `POST /api/cdp/answer-question` $\rightarrow$ `await bridge.click_element(f"ask:{choice_idx}")`
   - `POST /api/cdp/permission` $\rightarrow$ `await bridge.click_element(f"perm:{btn_idx}")`

### 3.2 `cdp_bridge.py` ↔ `push_notifications.py`
`push_notifications.py` monitors snapshot transitions:
1. **Attention State Detection**:
   - `snapshot.sidebarAttentionItems` contains parsed attention objects (`id`, `type`: `question` | `command` | `completed`, `name`).
   - Push manager sends web push notifications if `visibleClients == 0` (user has no active foreground browser tabs).
2. **Agent Finished Notification**:
   - When `agentRunning` transitions from `True` $\rightarrow$ `False`, push notification `"Task Complete"` is dispatched to subscribed mobile devices.

---

## 4. Comprehensive Testing Strategy (`tests/test_cdp_bridge.py`)

### 4.1 Mock CDP Server Architecture (`tests/harness.py`)
To achieve hermetic, independent testing without needing a running desktop Antigravity instance, `tests/harness.py` provides `MockCDPServer`:

```python
import asyncio
import json
from aiohttp import web
import websockets

class MockCDPServer:
    """
    In-memory mock Chrome DevTools Protocol server supporting:
    - HTTP discovery endpoints (/json/list, /json/version)
    - WebSocket JSON-RPC 2.0 protocol
    - Execution context lifecycle events
    - Evaluated expression dispatching and script emulation
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9000):
        self.host = host
        self.port = port
        self.http_app = web.Application()
        self.http_runner = None
        self.ws_server = None
        self.connected_clients = set()
        self.contexts = [
            {"id": 1, "origin": "vscode-file://vscode-app", "name": "workbench", "auxData": {"isDefault": True}},
            {"id": 2, "origin": "chrome-extension://isolated", "name": "isolated", "auxData": {"isDefault": False}},
        ]
        self.mock_eval_handlers = {}
        self._setup_routes()

    def _setup_routes(self):
        self.http_app.router.add_get("/json/list", self._handle_json_list)
        self.http_app.router.add_get("/json/version", self._handle_json_version)

    async def _handle_json_list(self, request):
        data = [{
            "description": "",
            "devtoolsFrontendUrl": f"/devtools/inspector.html?ws={self.host}:{self.port}/devtools/page/test-target-1",
            "id": "test-target-1",
            "title": "workbench.html - Antigravity",
            "type": "page",
            "url": "vscode-file://vscode-app/workbench.html",
            "webSocketDebuggerUrl": f"ws://{self.host}:{self.port}/devtools/page/test-target-1"
        }]
        return web.json_response(data)

    async def _handle_json_version(self, request):
        return web.json_response({"Browser": "Antigravity/1.0.0", "Protocol-Version": "1.3"})

    async def start(self):
        # Start HTTP discovery
        self.http_runner = web.AppRunner(self.http_app)
        await self.http_runner.setup()
        site = web.TCPSite(self.http_runner, self.host, self.port)
        await site.start()

        # Start WebSocket RPC server
        self.ws_server = await websockets.serve(self._handle_ws, self.host, self.port + 100)

    async def _handle_ws(self, websocket):
        self.connected_clients.add(websocket)
        try:
            async for raw in websocket:
                msg = json.loads(raw)
                msg_id = msg.get("id")
                method = msg.get("method")
                params = msg.get("params", {})

                if method == "Runtime.enable":
                    await websocket.send(json.dumps({"id": msg_id, "result": {}}))
                    # Emit execution contexts
                    for ctx in self.contexts:
                        await websocket.send(json.dumps({
                            "method": "Runtime.executionContextCreated",
                            "params": {"context": ctx}
                        }))
                elif method == "Emulation.setFocusEmulationEnabled":
                    await websocket.send(json.dumps({"id": msg_id, "result": {}}))
                elif method == "Runtime.evaluate":
                    expr = params.get("expression", "")
                    ctx_id = params.get("contextId", 1)
                    val = self._resolve_eval(expr, ctx_id)
                    await websocket.send(json.dumps({
                        "id": msg_id,
                        "result": {"result": {"type": "object", "value": val}}
                    }))
        finally:
            self.connected_clients.remove(websocket)

    def _resolve_eval(self, expr: str, context_id: int) -> Any:
        for pattern, handler in self.mock_eval_handlers.items():
            if pattern in expr:
                return handler(expr, context_id)
        # Default empty snapshot payload
        if "scrollbar-hide" in expr or "CAPTURE_SCRIPT" in expr:
            return {
                "html": "<div class='chat-msg'>Hello from Antigravity</div>",
                "css": ":root{--bg:#1e1e1e}",
                "agentRunning": False,
                "scrollInfo": {"scrollTop": 0, "scrollHeight": 1000, "clientHeight": 500},
                "isSidebarOpen": False,
                "sidebarSignature": "overview*,review",
            }
        if "antigravity.agentSidePanelInputBox" in expr:
            return True
        return None

    async def stop(self):
        if self.ws_server:
            self.ws_server.close()
            await self.ws_server.wait_closed()
        if self.http_runner:
            await self.http_runner.cleanup()
```

---

### 4.2 Test Suite Matrix (`tests/test_cdp_bridge.py`)

The unit/integration test suite for `cdp_bridge.py` covers 6 core test fixtures and over 35 concrete test cases:

```
tests/test_cdp_bridge.py
├── 1. TestDevToolsDiscovery
│   ├── test_read_active_port_file_windows_success
│   ├── test_read_active_port_file_missing
│   ├── test_read_active_port_corrupted
│   ├── test_fallback_port_probing_9000_to_9003
│   └── test_target_priority_workbench_over_page
│
├── 2. TestConnectionLifecycle
│   ├── test_connect_happy_path
│   ├── test_test_connect_success
│   ├── test_test_connect_failure_when_offline
│   ├── test_disconnect_clean_shutdown
│   ├── test_reconnect_exponential_backoff
│   └── test_focus_emulation_enabled_on_connect
│
├── 3. TestExecutionContextTracking
│   ├── test_context_created_event_registration
│   ├── test_context_destroyed_event_cleanup
│   ├── test_context_cleared_event_reset
│   ├── test_preferred_context_locking
│   └── test_preferred_context_reset_on_destroy
│
├── 4. TestContextEvaluationEngine
│   ├── test_evaluate_in_browser_default_context_priority
│   ├── test_evaluate_in_browser_fallback_on_exception
│   ├── test_evaluate_across_contexts_first_non_null
│   ├── test_evaluate_across_contexts_all_null
│   ├── test_evaluate_in_context_strict_single_target
│   └── test_find_editor_context_locates_active_editor
│
├── 5. TestScriptInjectionAndActions
│   ├── test_inject_message_detect_then_execute
│   ├── test_inject_message_append_mode
│   ├── test_click_element_chat_target
│   ├── test_click_element_permission_banner
│   ├── test_click_element_ask_question
│   ├── test_stop_generation_locates_and_clicks
│   ├── test_upload_image_synthesizes_drag_event
│   ├── test_type_text_dispatches_input_setter
│   └── test_fire_burst_captures_scheduling
│
└── 6. TestDJB2StateHashing
    ├── test_djb2_empty_string_vector
    ├── test_djb2_ascii_string_vector
    ├── test_djb2_complex_html_vector
    ├── test_djb2_unicode_and_emoji_vector
    ├── test_djb2_large_dom_vector_match_nodejs
    ├── test_composite_hash_17_properties_order
    ├── test_composite_hash_sidebar_open_diff
    ├── test_composite_hash_permission_overlay_diff
    └── test_composite_hash_idempotency
```

---

## 5. Implementation Roadmap for Milestone 1

1. **Step 1: Module Scaffolding**
   - Create `cdp_bridge.py` with full type annotations and dataclasses.
   - Implement `compute_djb2_hash` and `compute_composite_hash`.
2. **Step 2: Embedded CDP Script Library**
   - Port all 31 CDP scripts from `ag2r/src/cdp-scripts/` into Python constants/loader in `cdp_bridge.py`.
3. **Step 3: Port Discovery & Target Selector**
   - Implement Windows `%APPDATA%\Antigravity\DevToolsActivePort` reader and 9000..9003 HTTP probing.
4. **Step 4: WebSocket Client & Context Manager**
   - Implement `websockets` async client with `Runtime.executionContext*` tracking.
5. **Step 5: Snapshot & Evaluation Pipeline**
   - Implement `capture_snapshot()`, `evaluate_in_browser()`, `evaluate_across_contexts()`, and `find_editor_context()`.
6. **Step 6: User Interaction Handlers**
   - Implement `inject_message()`, `click_element()`, `stop_generation()`, `upload_image()`, `type_text()`.
7. **Step 7: Unit & Integration Verification**
   - Build `tests/harness.py` (MockCDPServer) and `tests/test_cdp_bridge.py`.
   - Run test suite to achieve 100% pass rate.
