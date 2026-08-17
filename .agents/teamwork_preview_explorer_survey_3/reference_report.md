# AG2R Reference Architecture & Implementation Mapping Report

## Executive Summary
This report provides a comprehensive architectural and technical analysis of the **AG2R** reference codebase (`_references_antigravity_mobile/ag2r`). It details the exact mechanics of Chrome DevTools Protocol (CDP) live DOM mirroring, two-way interaction emulation, interactive overlay extractions, Web Push (VAPID) notification pipelines, and mobile-optimized frontend UI/UX components. This mapping serves as the direct technical specification for implementing **Antigravity WebRemote v6** in Python (FastAPI/uvicorn + WebSocket + pywebpush + Playwright/CDP).

---

## 1. System Architecture & CDP Connection Mechanism

### 1.1 High-Level Architecture
```
┌─────────────────────────────────────────────────────────────────┐
│                 Antigravity Desktop (Electron)                  │
│  Main World Context (Lexical Editor, React 18, Radix Portals)  │
│  Isolated Execution Contexts (Tasks, Scheduled Tasks, Sidebars) │
└───────────────────────┬─────────────────────────────────────────┘
                        │ CDP (Port 9000 / DevToolsActivePort)
┌───────────────────────▼─────────────────────────────────────────┐
│                 AG2R Server / Python CDP Bridge                 │
│  - Target Discovery (workbench.html / jetski / page)            │
│  - Runtime Execution Context Tracking (Created/Destroyed/Clear) │
│  - Context-Aware Script Evaluation (Locking / All / Specific)   │
│  - 300-500ms DOM Capture & Sanitization Pipeline               │
│  - DJB2 Content Hash Diffing & Change Detection                │
│  - VAPID Web Push Notification Manager (pywebpush)             │
│  - REST API & WebSocket Streaming Gateway                       │
└───────────────────────┬─────────────────────────────────────────┘
                        │ HTTPS / WSS (Tailscale / mDNS / Local)
┌───────────────────────▼─────────────────────────────────────────┐
│               Mobile Web Client (PWA / Responsive)              │
│  - DOM Mirroring & Injected Stylesheets                         │
│  - Floating Action Buttons (Scroll FAB, Comment FAB)           │
│  - Collapsible Running Tasks Strip                              │
│  - Subagent View Indicator & Navigation                         │
│  - Interactive Overlays (Permission, ask_question, Dropdowns)   │
│  - Service Worker Push Receiver & Notification Click Router    │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 CDP Discovery & Port Resolution
- **Port Discovery Sequence**:
  1. Reads `DevToolsActivePort` from the user application support directory (`~/Library/Application Support/Antigravity/DevToolsActivePort` on macOS, or `%APPDATA%\Antigravity\DevToolsActivePort` / `%LOCALAPPDATA%\Programs\Antigravity` on Windows).
  2. Falls back to configured port range: `CDP_PORT` (default `9000`), `9001`, `9002`, `9003`.
- **Target Selection Priority**:
  - Priority 1: Target whose `url` contains `workbench.html` or `title` contains `workbench`.
  - Priority 2: Target whose `url` contains `jetski` or `title` is `Launchpad`.
  - Priority 3: Any target with `type === 'page'`.

### 1.3 Execution Context Management & Evaluation Strategies
Antigravity uses multiple execution contexts (Main World, Extension/Isolated contexts for tasks and portals). AG2R manages contexts dynamically via `Runtime.executionContextCreated`, `Runtime.executionContextDestroyed`, and `Runtime.executionContextsCleared`.

Four evaluation modes are implemented:
1. **`evaluateInBrowser(expression)` (Preferred Context Locking)**:
   - Sorts execution contexts prioritizing `preferredContextId`, then default contexts.
   - On successful evaluation without exception, sets `preferredContextId = ctx.id`.
   - Prevents hash oscillation between polling cycles.
2. **`evaluateAcrossContexts(expression)` (First Non-Null Win)**:
   - Iterates all known execution contexts and executes the expression.
   - Returns the first non-null return value.
   - Critical for components rendered in separate React trees (Running Tasks, Scheduled Tasks, History, Kebab Popovers).
3. **`evaluateInContext(contextId, expression)` (Single Execution)**:
   - Executes strictly within a specified context ID without fallthrough.
   - Prevents double execution or race conditions for side-effect operations (e.g. sending text, clicking stop).
4. **`findEditorContext()` (Synchronous Editor Detection)**:
   - Runs synchronous probe `HAS_VISIBLE_EDITOR_SCRIPT` (`[data-lexical-editor="true"], [contenteditable="true"]`).
   - Identifies which execution context hosts the active Lexical editor instance.

---

## 2. DOM Capture, Sanitization & Diffing Algorithms

### 2.1 DOM Capture (`CAPTURE_SCRIPT` in `src/cdp-scripts/capture.js`)
1. **Chat Container Detection**:
   - Matches `.scrollbar-hide[class*="overflow-y-auto"]`, `[data-testid="conversation-view"]`, `#conversation`, `#chat`, `#cascade`.
   - New Session Page Fallback: if container missing or `clientHeight === 0`, walks up from `#antigravity.agentSidePanelInputBox` to find the `.animate-fade-in` root container.
2. **Agent Status Detection**:
   - Queries `[data-tooltip-id="input-send-button-cancel-tooltip"]` or `button svg.lucide-square`.
   - `agentRunning = true` if button exists and `offsetParent !== null`.
3. **Interactive Element Tagging (`tagInteractives`)**:
   - Assigns unique attributes `data-ag-click-id="<prefix>:<index>"` and `data-ag-click-label="<text>"` on:
     - Semantic elements: `button`, `a`, `[role="button"]`, `[role="option"]`, `[role="menuitem"]`, `[role="menuitemradio"]`.
     - Ambiguous pointer elements: `[class*="cursor-pointer"]` with text length <= 80 (or direct `onclick` handler).
   - Clones container (`container.cloneNode(true)`) and immediately untags originals to prevent DOM pollution in Antigravity.
4. **Sanitization / Cleaning Steps**:
   - Removes editor/input elements (`[contenteditable="true"]`, `[data-lexical-editor]`, `[role="textbox"]`, `form`), preserving action bars (`Allow`, `Deny`, `Review`, `Run`, `Confirm`, `Accept`, `Reject`).
   - Strips fixed/absolute positioned elements (`getComputedStyle(el).position === 'fixed'|'absolute'`), preserving action buttons.
   - Sets background color `#101010` on sticky elements (`[data-ag-sticky]`).
   - Transforms invalid inline `div` inside `span` or `p` into `span` with `display: inline-flex; align-items: center;`.
   - Sets `display: block` on all `p` tags.
   - Cleans Tailwind class strings containing `[object Object]`.
5. **CSS Extraction**:
   - Concatenates rules from all `document.styleSheets`.
   - Enumerates all CSS custom properties (`--*`) from `getComputedStyle(document.documentElement)` and `document.body` into `:root{...}` declarations.
6. **Sidebar Attention & Status Extraction**:
   - Scans `.bg-sidebar` for `.animate-unread-ping`.
   - Extracts conversation ID from `data-testid="convo-pill-<uuid>"`.
   - Classifies attention type:
     - `question`: Matches Material Symbols path `M477.92-295.77q17.15,0...` or `lucide-message*`.
     - `command`: Matches `lucide-terminal*` or generic SVG.
     - `completed`: Ping dot with no blocked intervention SVG.
7. **Auxiliary Element Extractions**:
   - Right sidebar signature: active tab IDs + `isSidebarOpen` (checks collapse container inline style `width !== '0%'`).
   - Portal dropdowns (`role="listbox"`) and dialog overlays (`role="dialog"`, `.fixed.inset-0`).
   - Settings modal (`#root .fixed.inset-0.z-[5000]`).
   - Active artifact/file URI detection (`[data-tab-id].bg-secondary`).
   - Inline `ask_question` card (Submit + Skip buttons + radiogroup).
   - Command permission banner (`role="radiogroup"` + Allow/Deny buttons).
   - Environment name (`aria-label="Select Environment"`), Branch (`aria-label="Select Default Branch"`), Model (`aria-label*="Select model"`).
   - Subagent view detection (`isInputBoxHidden` + "cannot prompt" text outside chat + parent breadcrumb name).
   - Side question / BTW panel (`Side Question` header).

### 2.2 Cross-Context Captures
- **`running-tasks.js`**: Captures `#antigravity.agentSidePanelInputBox .rounded-t-2xl` with tagged buttons (`task:0` toggle header, `task:1..N` name/stop pairs).
- **`scheduled-tasks.js`**: Captures content from `[aria-label="Add scheduled task"]` / `[aria-label="Edit task title"]`, syncing live input values to `data-ag-value`.
- **`scheduled-tasks-dialog.js`**: Captures `.fixed.inset-0.z-[2550]` card.
- **`conversation-history.js`**: Captures `.h-full.w-full.overflow-y-auto` right of sidebar with heading "Conversation History".
- **`capture-dropdown.js`**: Captures body-level listbox portals and kebab context menus with indices `scheddlg:100+`.

### 2.3 Diffing & Hashing Algorithm
- **Hash Function**: DJB2 string hashing (`hash = ((hash << 5) + hash) + charCode`).
- **Composite Hash Signature**:
  ```javascript
  const hash = hashString(
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
    (snapshot.branchName || '')
  );
  ```
- **Broadcasting Decision**:
  - `hash !== lastSnapshotHash`: Updates cached snapshot, broadcasts `{ type: 'snapshot', hash, agentRunning, timestamp }`.
  - `hash === lastSnapshotHash` and `agentRunning` changed: Broadcasts `{ type: 'status', agentRunning }`.
  - Otherwise skips re-broadcasting.

---

## 3. Two-Way Interaction & CDP Emulation

### 3.1 Lexical Editor Text Injection (`inject-message.js`)
- **Finding Editor**: Locates visible `[data-lexical-editor="true"]`, `[contenteditable="true"][role="textbox"]`.
- **Focus & Clearing**:
  - In normal mode: `window.getSelection().selectAllChildren(editor)`, `document.execCommand('delete', false, null)`.
  - In append mode (for images/macros): moves selection to end.
- **Paste Emulation**:
  - Creates `DataTransfer`, sets `text/plain` data.
  - Dispatches `ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })`.
  - Fallback: `document.execCommand('insertText', false, textVal)`.
- **Submission**:
  - Clicks `button[data-testid="send-button"]`, `button[aria-label*="send" i]`, or `svg.lucide-arrow-right`.
  - Fallback: Dispatches `KeyboardEvent('keydown', { key: 'Enter', keyCode: 13 })`.

### 3.2 Drag-and-Drop Image Upload (`upload-image.js`)
- **Flow**:
  1. Mobile client uploads file via `POST /upload` (multipart/form-data, max 10MB).
  2. Server converts image buffer to base64.
  3. CDP script decodes base64 into binary `Uint8Array` and creates `File` object.
  4. Attaches file to `DataTransfer.items.add(file)`.
  5. Dispatches full drag sequence on editor: `dragenter` -> `dragover` -> `drop`.
  6. Server awaits DOM node insertion with `waitForEditorImage()` (polls `CHECK_EDITOR_IMAGE_SCRIPT` up to 3s).

### 3.3 Click Proxying & Hit-Testing (`click-main.js`)
- **Prefix Dispatching**:
  - `chat:N` -> Reconstructs interactive element list in chat container and clicks index `N`.
  - `left:N` -> Targets `.bg-sidebar` item.
  - `right:N` -> Targets review panel item.
  - `dropdown:N` -> Targets portal listbox element; focuses Lexical editor first and performs coordinate hit testing (`elementFromPoint` + `PointerEvent`/`MouseEvent` sequence: `pointerdown`, `mousedown`, `pointerup`, `mouseup`, `.click()`).
  - `dialog:N` -> Targets modal/popover dialog button.
  - `settings:N` -> Targets settings modal item.
  - `ask:N` -> Targets `ask_question` radio label or button.
  - `perm:N` -> Targets permission banner radio label or button.
  - `task:N` -> Targets running tasks strip button.
  - `sched:N` / `scheddlg:N` -> Targets scheduled tasks list/dialog/portal.
  - `history:N` -> Targets conversation history row.
  - `subinfo:N` -> Targets subagent overview button.
  - `btw:N` -> Targets side question action button.
- **Label Validation**:
  - Compares `expectedLabel` against `actualLabel` to prevent stale clicks during dynamic DOM shifts.
- **Burst Re-Captures**:
  - Fires rapid snapshot re-captures after portal/dropdown/dialog clicks at `[150ms, 400ms, 700ms]` to immediately capture newly opened Radix UI elements.

### 3.4 React Native Input Value Emulation (`type-text.js`)
- Uses prototype setter override to trigger React synthetic events:
  ```javascript
  const nativeSetter = el.tagName === 'TEXTAREA'
    ? Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
    : Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
  nativeSetter.call(el, safeText);
  el.dispatchEvent(new Event('input', { bubbles: true }));
  el.dispatchEvent(new Event('change', { bubbles: true }));
  ```

---

## 4. Web Push Notification Architecture

### 4.1 VAPID Configuration & Key Lifecycle
- **Key Generation & Storage**:
  - Stored in `vapid-keys.json` with keys `publicKey`, `privateKey`.
  - Generated via `webpush.generateVAPIDKeys()` on first boot.
  - VAPID details set with contact email: `mailto:ag2r@omercanyy.com`.
- **Public Key Endpoint**:
  - `GET /api/vapid-key` (or `/push/vapid-public-key`) returns `{ publicKey }` (base64url encoded).

### 4.2 Push Subscription Storage & Lifecycle
- **Storage**:
  - Stored in `push-subscriptions.json` as Map serialized to JSON.
  - Stores `{ endpoint, keys: { p256dh, auth }, origin }`.
- **Subscription Endpoints**:
  - `POST /api/subscriptions/push` (or `/push/subscribe`): Registers/updates subscription with client `origin`.
  - `POST /push/unsubscribe`: Removes endpoint from subscription registry.
  - `GET /push/status` & `GET /push/state`: Returns active subscription count and pause status.
  - `POST /push/pause` & `POST /push/resume`: Toggles notification silencing.

### 4.3 Triggering Logic & Deduplication
- **Trigger Conditions**:
  1. `snapshot.sidebarAttentionItems` contains an item with `type === 'question'` (`ask_question`).
  2. `snapshot.sidebarAttentionItems` contains an item with `type === 'command'` (command approval needed).
  3. Agent completion (`agentRunning` transitions to `false`).
- **Deduplication & Foreground Suppression**:
  - `notifiedConversations` Set tracks notified IDs so repeated notifications are blocked until the user attends to the conversation.
  - `visibleClients` counter tracks clients with `document.visibilityState === 'visible'`. If `visibleClients > 0`, notifications are suppressed.
  - Subscriptions returning HTTP 410 (Gone) are automatically purged from storage.

### 4.4 Service Worker Routing (`public/sw.js`)
- Listens to `push` event: displays notification with `tag: "ag2r-<id>"`, `requireInteraction: true`, and payload containing navigation URL `?sidebar=open&conversationId=<id>`.
- Listens to `notificationclick`:
  - Matches open window clients. If found, posts message `{ type: 'navigate-conversation', conversationId }` and focuses window.
  - If no open window exists, opens a new window at the target URL.

---

## 5. Frontend UI/UX & Component Mapping

### 5.1 Component Structure Mapping

| Component | DOM Element ID / Selector | Behavior & Reference Logic |
| :--- | :--- | :--- |
| **Header** | `header#header` | Sidebar toggle, AG2R logo, title, connection dot, refresh button, notification bell, review toggle button. |
| **Connection Dot** | `#connection-status` | `data-status="connected"` (green), `data-status="reconnecting"` (yellow pulse), `data-status="disconnected"` (red). |
| **Notification Bell** | `#notification-bell` | 3 states: `unsubscribed` (bell off), `active` (bell active), `paused` (bell standard + Zzz). Tap cycles states. |
| **Running Tasks Strip** | `#running-tasks` | Inside `#input-bar`. Collapsible list showing task count, spinner, task name (`.font-mono`), and stop button (`stop_circle`). |
| **Subagent View Bar** | `#subagent-bar` | Yellow banner below header with Back button + parent conversation name. Chat area gets `.subagent-view` yellow inset shadow. |
| **Subagent Info Panel** | `#subagent-info` | Above input bar. Displays captured "cannot prompt subagents" note and "Open Overview" button. |
| **Side Question (BTW)** | `#btw-panel` | Above input bar. Displays captured side question card with options and close button. |
| **Input Bar & Controls** | `#input-bar`, `.input-wrapper` | Textarea `#message-input` (auto-resize 63-120px), attach `+` menu (Media/Actions), model chip, mic button, send/stop action button. |
| **Scroll-to-Bottom FAB**| `#scroll-fab` | Floating bottom right button (`keyboard_arrow_down`), visible when user scrolls > 100px away from bottom. |
| **Quick Action Chips** | `#quick-actions` | Floating chips ("Continue", "Proceed") above input bar when idle. |
| **Comment FAB & Modals**| `#comment-fab`, `#comment-modal`, `#comment-review-modal`, `#comment-badge` | Text selection in right sidebar spawns FAB -> opens comment modal -> queues into `#comment-badge` -> formatted nested markdown on send. |
| **Scheduled Tasks View**| `#scheduled-tasks-overlay`, `#scheduled-tasks-dialog`, `#text-input-modal` | Full-screen overlay for tasks list, dialog overlay for new tasks, virtual keyboard text input modal for form editing. |
| **Conversation History**| `#conversation-history-overlay` | Full-screen overlay for `/history` page navigation. |
| **Interactive Overlays**| `#permission-overlay`, `#dropdown-overlay`, `#settings-overlay` | Bottom sheet / modal overlays rendering native AG captured HTML with full click proxying. |

### 5.2 Responsive & Mobile Viewport CSS Rules
- **Viewport Constraints**: `width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no, viewport-fit=cover`.
- **CSS Safe Areas**: `padding-bottom: max(8px, env(safe-area-inset-bottom))`, `padding-top: env(safe-area-inset-top)`.
- **Virtual Keyboard Handling**: `window.visualViewport` resize listener dynamically adjusts `document.body.style.height = vh + 'px'`.
- **Desktop vs Mobile Behavior**:
  - Mobile: Enter inserts newline; send button submits.
  - Desktop: Enter submits; Shift+Enter inserts newline.
  - Desktop max width: `max(30vw, 40rem)` centered chat and input bar.
  - Mobile code copy: `.mobile-copy-btn` extracts text line-by-line from `.line-content`.

---

## 6. Complete Python Porting Mapping Table

| AG2R Reference (Node.js) | Python WebRemote v6 Implementation Target | Porting Notes & Specifications |
| :--- | :--- | :--- |
| `server.js` (Express + `ws`) | `server.py` (FastAPI + WebSocket + Starlette) | Convert all REST endpoints to FastAPI async routes; use Starlette WebSocket endpoints for `/ws/stream`. |
| `chrome-remote-interface` | `cdp_bridge.py` (`asyncio` + `websockets` / CDP) | Manage CDP WebSocket connection to `127.0.0.1:9000`; implement target discovery and context tracking. |
| `src/cdp-scripts/capture.js` | `cdp_bridge.py` (`CAPTURE_SCRIPT`) | Direct JavaScript script evaluated via CDP `Runtime.evaluate`. |
| `src/cdp-scripts/inject-message.js` | `cdp_bridge.py` (`inject_message()`) | Evaluates Lexical clipboard paste + send button click in detected editor context. |
| `src/cdp-scripts/upload-image.js` | `cdp_bridge.py` (`upload_image()`) | Evaluates base64 decode and drag/drop emulation on editor. |
| `src/cdp-scripts/click-*.js` | `cdp_bridge.py` (`click()`, `submit_dialog()`, `type_text()`) | Direct JavaScript scripts for main click dispatching and React property setter emulation. |
| `web-push` (Node.js) | `push_notifications.py` (`pywebpush` + `cryptography`) | VAPID key generation (`ec.SECP256R1`), subscription storage in `config.json` / `data/push_subs.json`, async push sending. |
| `public/index.html` | `static/index.html` | Match full DOM structure with all modals, overlays, FABs, running tasks strip, and subagent bar. |
| `public/css/style.css` | `static/css/app.css` | Match Antigravity 2.0 theme tokens, responsive breakpoints, animations, and overlay styling. |
| `public/js/app.js` | `static/js/app.js` | Match WebSocket reconnection, snapshot hash caching, inner scroll preservation, click proxying, comment queuing, and push setup. |
| `public/sw.js` | `static/sw.js` | Match service worker push handler, notification clicks, and window message routing. |

---

## Conclusion
The AG2R codebase provides a robust, battle-tested pattern for non-intrusive CDP DOM mirroring and two-way control of Antigravity. Porting this architecture into a clean, standalone Python FastAPI application (`Local_AI_Mobile_Agent`) will achieve 100% feature parity while maintaining lightweight resource usage (< 80MB RAM) and responsive mobile performance.
