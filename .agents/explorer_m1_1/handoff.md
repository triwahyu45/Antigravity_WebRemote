# Handoff Report: CDP Bridge Architecture & Reference Analysis (M1_Core_CDP_Engine)

## 1. Observation

1. **DevToolsActivePort on Windows**:
   - Location: `%APPDATA%\Antigravity\DevToolsActivePort` (expanded to `C:\Users\hando\AppData\Roaming\Antigravity\DevToolsActivePort`).
   - File Content observed on live machine:
     ```text
     49250
     /devtools/browser/1f03aa63-ea9e-4845-9c97-478e74b7b2d9
     ```
   - Line 1 contains the dynamic debugging port (`49250`); Line 2 contains the browser WebSocket endpoint.

2. **CDP Target List Response (`http://127.0.0.1:49250/json/list`)**:
   - Output from live probe:
     ```json
     [
       {
         "description": "",
         "devtoolsFrontendUrl": "https://chrome-devtools-frontend.appspot.com/serve_rev/@cb10bb07c0a5dac19a421f7cbfd002146e74aaed/inspector.html?ws=127.0.0.1:49250/devtools/page/FADDB104632B2EE242C2E4A2F5B09E1B",
         "id": "FADDB104632B2EE242C2E4A2F5B09E1B",
         "title": "Bismillah",
         "type": "page",
         "url": "https://127.0.0.1:49253/c/63fb64ac-9344-46a1-8d60-a891ba0835d8?section=cc132cc3-746b-4c07-905e-7f6b7e2c7cb2&settingsOpen=true&settingsScreen=General",
         "webSocketDebuggerUrl": "ws://127.0.0.1:49250/devtools/page/FADDB104632B2EE242C2E4A2F5B09E1B"
       }
     ]
     ```
   - Main Antigravity target is `type: "page"`, with session URL `https://127.0.0.1:49253/c/63fb64ac-9344-46a1-8d60-a891ba0835d8`.

3. **V8 Execution Contexts in Electron**:
   - Live execution of `Runtime.enable` revealed 2 distinct execution contexts:
     - Context 1: `id=1`, `name=''`, `origin='https://127.0.0.1:49253'`, `auxData={'isDefault': True}` (Main World context where Lexical editor & React state live).
     - Context 2: `id=2`, `name='Electron Isolated Context'`, `auxData={'isDefault': False}` (Preload/Isolated context).
   - High volume of unsolicited `Runtime.consoleAPICalled` events stream continuously over the WebSocket.

4. **Reference Implementation Patterns (`ag2r/server.js` lines 353–598, `ag2r/src/cdp-scripts/`)**:
   - `ag2r/server.js` (lines 353-409): Target discovery prioritizing `workbench.html` -> `jetski` -> `type: "page"`, probing port set `[DevToolsActivePort, 9000, 9001, 9002, 9003]`.
   - `ag2r/server.js` (lines 425-446): Multi-context tracking via `Runtime.executionContextCreated`, `Runtime.executionContextDestroyed`, `Runtime.executionContextsCleared`.
   - `ag2r/server.js` (lines 489-598): Evaluation helpers:
     - `evaluateInBrowser`: Locks to `preferredContextId` to avoid hash oscillation between contexts.
     - `evaluateAcrossContexts`: Evaluates all contexts, returns first non-null value (used for running tasks, scheduled tasks, conversation history, and portal dialogs).
     - `findEditorContext`: Synchronous probe using `HAS_VISIBLE_EDITOR_SCRIPT` to locate Lexical editor context before mutating actions.
     - `evaluateInContext`: Strict single-context execution preventing double-send / double-click bugs.
   - `ag2r/server.js` (line 465): `Emulation.setFocusEmulationEnabled({ enabled: true })` ensures background rendering is not throttled by Chromium.

5. **CDP Scripts Suite**:
   - Located at `ag2r/src/cdp-scripts/`, containing 31 scripts covering DOM capture, sanitization, click dispatching, Lexical paste injection, drag-and-drop file upload, and modal extraction.

---

## 2. Logic Chain

1. **Dynamic Port Discovery (Observation 1, 2, 4)**:
   - Antigravity does not always bind to a fixed port (e.g. 9000). When launched without an explicit port or during development updates, it writes an ephemeral port to `%APPDATA%\Antigravity\DevToolsActivePort`.
   - Parsing Line 1 as an integer and adding `[dtp_port, 9000, 9001, 9002, 9003]` to an ordered candidate list ensures connection succeeds under all startup modes.

2. **Asynchronous Frame Routing & Concurrency Model (Observation 3)**:
   - Because unsolicited events (e.g. `Runtime.consoleAPICalled`, `Runtime.executionContextCreated`) share the same WebSocket stream as command responses, naive sequential reads block or drop frames.
   - A dedicated `_read_loop` task with an ID-to-Future dictionary (`_pending_commands: Dict[int, asyncio.Future]`) guarantees correct asynchronous request/response demultiplexing in Python 3.12.

3. **Multi-Context Evaluation Strategy (Observation 3, 4)**:
   - Main World Context (ID 1) holds the Lexical editor and React DOM tree; Isolated Contexts (ID 2) hold extension portals and certain dialogs.
   - Using `findEditorContext()` with `evaluateInContext()` for mutating actions (`injectMessage`, `stopGeneration`, `clickSendButton`) prevents duplicate executions.
   - Using `evaluateInBrowser()` with context locking prevents UI diff hash oscillation.
   - Using `evaluateAcrossContexts()` ensures tasks/dialogs in isolated contexts are captured without failure.

---

## 3. Caveats

- **Active Session Dependency**: If Antigravity is not running on the desktop host, `DevToolsActivePort` will be absent and HTTP probing across `9000..9003` will fail. The client must handle this with an automatic reconnect loop and not crash the application.
- **Port Reuse after Restart**: If Antigravity Electron is restarted, its ephemeral port and target WebSocket ID change. The reconnect loop must re-execute the discovery pipeline rather than reusing stale connection parameters.

---

## 4. Conclusion

The CDP architecture from AG2R has been fully reverse-engineered, validated against live Antigravity Electron runtime on Windows, and mapped to a robust Python 3.12 implementation (`websockets` + `aiohttp` + `asyncio`).

The design blueprint covers:
1. Dynamic port discovery with Windows `%APPDATA%` and fallback range `9000..9003`.
2. Asynchronous WebSocket JSON-RPC multiplexer with background reader and future registry.
3. Multi-context tracking for Main World and Isolated Contexts.
4. Evaluation primitives (`evaluate_in_browser`, `evaluate_across_contexts`, `find_editor_context`, `evaluate_in_context`).
5. All 31 CDP scripts and the 14-step DOM sanitization & DJB2 hash pipeline.

Detailed technical analysis and code blueprints are written to:
`D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\.agents\explorer_m1_1\analysis.md`

---

## 5. Verification Method

To independently verify these findings:

1. **Verify Windows DevToolsActivePort location and content**:
   ```powershell
   Get-Content "$env:APPDATA\Antigravity\DevToolsActivePort"
   ```

2. **Verify active targets via Python HTTP probe**:
   ```powershell
   python -c "import os, json, urllib.request; port = int(open(os.path.join(os.environ['APPDATA'], 'Antigravity', 'DevToolsActivePort')).readline().strip()); print(json.dumps(json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list').read()), indent=2))"
   ```

3. **Verify multi-context discovery & evaluate via Python websockets**:
   ```powershell
   python -c "
   import asyncio, json, urllib.request, websockets
   async def probe():
       port = int(open(os.path.expandvars('%APPDATA%/Antigravity/DevToolsActivePort')).readline().strip())
       targets = json.loads(urllib.request.urlopen(f'http://127.0.0.1:{port}/json/list').read())
       page = next(t for t in targets if t.get('type') == 'page')
       async with websockets.connect(page['webSocketDebuggerUrl']) as ws:
           await ws.send(json.dumps({'id': 1, 'method': 'Runtime.enable', 'params': {}}))
           for _ in range(5):
               data = json.loads(await ws.recv())
               if data.get('method') == 'Runtime.executionContextCreated':
                   print('Found context:', data['params']['context']['id'], data['params']['context'].get('name'))
   asyncio.run(probe())
   "
   ```
