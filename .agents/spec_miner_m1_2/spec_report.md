# SPECIFICATION REPORT: Comprehensive Catalog & Architecture of 31 CDP Scripts

**Specification Miner**: `spec_miner_m1_2`  
**Target Component**: `cdp_bridge.py` & Browser-Side Automation Engine  
**Authoritative References**: `_references_antigravity_mobile/ag2r/src/cdp-scripts/` & `ag2r/server.js`  
**Date**: 2026-08-17  

---

## 1. Executive Summary & Architectural Overview

The Antigravity desktop application is an Electron-based environment rendering a React 18+ web interface (`workbench.html`). To achieve full feature parity with AG2R in a standalone Python 3.12 architecture without Node.js, `cdp_bridge.py` connects to the desktop Antigravity process via Chrome DevTools Protocol (CDP) WebSocket (`127.0.0.1:9000`).

Browser-side DOM inspection, sanitization, and two-way interaction are driven by **31 specialized JavaScript automation scripts** located in `src/cdp-scripts/`.

### Core Capabilities of the CDP Script Engine:
1. **Zero-Impact DOM Snapshot Mirroring**: Deep-cloning live chat hierarchies, stripping fixed/absolute overlays, rewriting illegal inline DOM nesting (span > div), solidifying sticky headers, and harvesting root/body CSS variables.
2. **Deterministic Element Tagging**: Bidirectionally tagging clickable and interactive elements with prefix-scoped indices (`chat:0`, `left:1`, `scheddlg:100`) and syncing dynamic `<input>`/`<textarea>` values into `data-ag-value` attributes before cloning.
3. **Two-Way Reactive Interaction**: Injecting multiline text into Lexical contenteditable editors via synthetic `ClipboardEvent` paste dispatch, bypassing React 18 controlled input blockers via native prototype property setters, and synthesizing file drag-and-drop events.
4. **Portal & Overlay Interception**: Navigating Radix UI portals rendered directly under `document.body` (outside `#root`), including listboxes, dialogs, and kebab popovers using coordinate-based hit-testing (`document.elementFromPoint`).
5. **Multi-Context Execution Navigation**: Dynamically detecting and routing operations between the Main World context and Isolated Extension contexts.

---

## 2. Features Discovered

| # | Category | Feature | Description | Inputs | Outputs | Error Behavior | Discovered Via |
|---|---|---|---|---|---|---|---|
| 1 | Shared Helper | `_shared.js` | Tagging & untagging helper functions interpolated into CDP script closures. | `root: Element`, `prefix: str`, `skipVisibility: bool`, `includePointer: bool`, `maxTextLength: int` | `tagged: Element[]` | Skips invisible elements unless `skipVisibility=true`; ignores large pointer blocks | `_shared.js` |
| 2 | Portal Capture | `capture-dropdown.js` (Listbox) | Captures body-level Radix listbox portals outside `#root`. | None | `outerHTML: str` or `null` | Returns `null` if no listbox portal exists | `capture-dropdown.js` |
| 3 | Portal Capture | `capture-dropdown.js` (Kebab Menu) | Captures context/kebab menus rendered as body-level popover portals. | None | `outerHTML: str` or `null` | Returns `null` if no menu exists | `capture-dropdown.js` |
| 4 | Core Snapshot | `capture.js` | 14-step chat snapshot, CSS variable harvester, overlays, subagent & BTW state extractor. | None (evaluates live DOM) | `Object` (24 state fields) | Returns `null` if no chat container / new session root found | `capture.js` |
| 5 | State Probe | `check-editor-image.js` | Detects presence of rendered image/decorator nodes in Lexical editor. | None | `boolean` | Returns `false` if editor missing or image not rendered | `check-editor-image.js` |
| 6 | Navigation | `click-conversation.js` | Expands sidebar if collapsed and navigates to conversation by UUID. | `safeConversationId: str` (UUID) | `{ ok: bool, conversationId: str, name?: str, fallback?: bool, reason?: str }` | Returns `{ ok: false, reason: 'pill_not_found' }` if UUID absent | `click-conversation.js` |
| 7 | Navigation | `click-history.js` | Clicks items on `/history` Conversation History overlay by ordered index. | `histIdx: int` | `{ ok: bool, label: str, source: 'history', reason?: str, total?: int }` | Returns `{ ok: false, reason: 'history_index_out_of_range' }` | `click-history.js` |
| 8 | Master Dispatch | `click-main.js` | Universal click proxy routing 12 sources with label verification and hit-testing. | `safeClickId: str` (`"prefix:idx"`), `safeLabel: str` | `{ ok: bool, label: str, source: str, debugNearby?: list, reason?: str }` | Returns `{ ok: false, reason: 'label_mismatch' }` with `debugNearby` | `click-main.js` |
| 9 | Dialog Interaction | `click-sched-dialog.js` | Clicks elements inside `z-[2550]` scheduled task modal dialog. | `dlgIdx: int`, `safeLabel: str` | `{ ok: bool, label: str, source: 'scheddlg', reason?: str, total?: int }` | Label fallback if index shifted; error if element missing | `click-sched-dialog.js` |
| 10 | Portal Interaction | `click-sched-portal.js` | Dispatches simulated pointer/mouse clicks to body portal dropdown options. | `optIdx: int` | `{ ok: bool, label: str, source: 'scheddlg_portal', reason?: str }` | Returns `{ ok: false, reason: 'option_index_out_of_range' }` | `click-sched-portal.js` |
| 11 | Task Interaction | `click-sched.js` | Clicks elements or focuses inputs in Scheduled Tasks list or detail view. | `schedIdx: int` | `{ ok: bool, label: str, source: 'sched', reason?: str, total?: int }` | Returns `{ ok: false, reason: 'sched_index_out_of_range' }` | `click-sched.js` |
| 12 | Interaction | `click-send-button.js` | Finds and clicks active send/submit button for image-only sends. | None | `{ ok: bool, method: 'button', reason?: str }` | Returns `{ ok: false, reason: 'no_send_button' }` | `click-send-button.js` |
| 13 | Task Interaction | `click-task.js` | Clicks running task or goal buttons inside the input box header. | `taskIdx: int` | `{ ok: bool, label: str, source: 'task', reason?: str, total?: int }` | Returns `{ ok: false, reason: 'task_index_out_of_range' }` | `click-task.js` |
| 14 | Sidebar Control | `close-right-sidebar.js` | Clicks native toggle button `[data-testid="toggle-aux-sidebar"]`. | None | `'closed'` or `null` | Returns `null` if close button not found | `close-right-sidebar.js` |
| 15 | Modal Capture | `conversation-history.js` | Captures DOM tree of `/history` Conversation History route. | None | `outerHTML: str` or `null` | Returns `null` if not on `/history` route | `conversation-history.js` |
| 16 | Clipboard | `copy-response.js` | Intercepts `clipboard.writeText` while triggering response copy button. | `safeClickId: str` (`"chat:N"`) | `{ ok: bool, text: str, reason?: str }` | Returns `{ ok: false, reason: 'element_not_found' }` | `copy-response.js` |
| 17 | Diagnostic | `discover.js` | Exhaustive layout inspection discovering sidebars, asides, tabs, panels. | None | `Object` (diagnostics trees) | Tolerant try/catch per selector group | `discover.js` |
| 18 | Navigation | `dismiss-scheduled-tasks.js` | Navigates back from task detail to list, or list to chat. | None | `{ ok: bool, method: 'detail-back' | 'sidebar-row' | 'history-back' }` | Fallback to `window.history.back()` | `dismiss-scheduled-tasks.js` |
| 19 | Dialog Control | `dismiss-settings.js` | Closes Settings modal by clicking backdrop coordinates or sending Escape key. | None | `{ ok: bool, method: 'backdrop' | 'escape' }` | Falls back to synthetic Escape keydown | `dismiss-settings.js` |
| 20 | Sidebar Control | `expand-left-sidebar.js` | Expands collapsed left sidebar via `[data-testid="sidebar-toggle"]`. | None | `{ ok: bool, wasCollapsed: bool, error?: str }` | Returns error if toggle button absent | `expand-left-sidebar.js` |
| 21 | Context Probe | `has-visible-editor.js` | Synchronously probes whether a visible Lexical editor exists in context. | None | `boolean` | Returns `false` without throwing (no GC risk) | `has-visible-editor.js` |
| 22 | Text Injection | `inject-message.js` | Injects text into Lexical editor via `ClipboardEvent` paste and clicks submit. | `safeText: str`, `appendMode: bool` | `{ ok: bool, method: 'button' | 'enter', reason?: str }` | Fallback: `execCommand('insertText')` + `KeyboardEvent('Enter')` | `inject-message.js` |
| 23 | Sidebar Control | `open-right-sidebar.js` | Opens right auxiliary sidebar via Review/Auxiliary toolbar buttons. | None | `'button'` or `null` | Returns `null` if no toggle found | `open-right-sidebar.js` |
| 24 | Asset Proxy | `proxy-image.js` | Renders completed image to Canvas (max 800px) and extracts data URL. | `safeSrc: str` | `data:image/png;base64,...` or `null` | Returns `null` on CORS/tainted canvas error | `proxy-image.js` |
| 25 | Sidebar Capture | `right-sidebar.js` | Captures right auxiliary sidebar DOM tagged `right:0..N`. | None | `outerHTML: str` or `null` | Returns `null` if sidebar not found | `right-sidebar.js` |
| 26 | Task Capture | `running-tasks.js` | Captures running tasks strip in input box header tagged `task:0..N`. | None | `outerHTML: str` or `null` | Returns `null` if no running task section | `running-tasks.js` |
| 27 | Dialog Capture | `scheduled-tasks-dialog.js` | Captures `z-[2550]` scheduled task modal card tagged `scheddlg:0..N`. | None | `outerHTML: str` or `null` | Returns `null` if overlay not present | `scheduled-tasks-dialog.js` |
| 28 | Modal Capture | `scheduled-tasks.js` | Captures Scheduled Tasks list or detail view tagged `sched:0..N`. | None | `outerHTML: str` or `null` | Returns `null` if not on Scheduled Tasks page | `scheduled-tasks.js` |
| 29 | Sidebar Control | `select-overview-tab.js` | Clicks Overview tab in auxiliary sidebar if no tab is currently active. | None | `void` | No-op if already active or overview tab missing | `select-overview-tab.js` |
| 30 | Control | `stop.js` | Halts generation via cancel tooltip button or `lucide-square` icon. | None | `{ ok: bool, method?: 'cancel-tooltip' | 'square-icon', reason?: str }` | Returns `{ ok: false, reason: 'no_stop_button' }` | `stop.js` |
| 31 | Input Typing | `type-text.js` | Types into input/textarea bypassing React 18 synthetic value blockers. | `safePlaceholder: str`, `safeClickId: str`, `safeText: str` | `{ ok: bool, tag: str, placeholder: str, valueLength: int, reason?: str }` | Returns `{ ok: false, reason: 'not_input' }` if target invalid | `type-text.js` |
| 32 | Image Upload | `upload-image.js` | Synthesizes File & DataTransfer, dispatches dragenter/dragover/drop. | `safeBase64: str`, `safeMimetype: str`, `safeFileName: str` | `{ ok: bool, method: 'drop', fileName: str, size: int, reason?: str }` | Returns `{ ok: false, reason: 'no_editor' }` | `upload-image.js` |

---

## 3. Deep Architectural Analysis & DOM Mechanics

### 3.1 The 14-Step DOM Sanitization & Extraction Pipeline (`capture.js`)

`capture.js` is the core live-mirroring engine. It extracts the full chat stream and associated state in 14 distinct steps:

1. **Chat Container Discovery & New Session Fallback**:
   - Primary query: `.scrollbar-hide[class*="overflow-y-auto"]`, `[data-testid="conversation-view"]`, `#conversation`, `#chat`, `#cascade`.
   - New Session Fallback: If container is null or has `clientHeight === 0`, locates `#antigravity.agentSidePanelInputBox`, walks up ancestors (up to 10 levels) until finding an element containing class `animate-fade-in`. Sets `container = newSessionRoot` and `isNewSessionPage = true`.
2. **Agent Generating State Detection**:
   - Queries `[data-tooltip-id="input-send-button-cancel-tooltip"]` or `button svg.lucide-square` and tests `offsetParent !== null`.
   - Returns boolean `agentRunning`.
3. **Scroll Metrics Capture**:
   - Records `{ scrollTop, scrollHeight, clientHeight }` directly from the live DOM container.
4. **Element Marking & Live Interactive Tagging**:
   - Marks all `position: fixed` or `position: absolute` elements with `data-ag-remove="1"`.
   - Marks all `position: sticky` elements with `data-ag-sticky="1"`.
   - Invokes `tagInteractives(container, 'chat', false, true, 80)` to stamp `data-ag-click-id="chat:N"` and `data-ag-click-label`.
5. **Deep DOM Cloning**:
   - Clones entire container: `const clone = container.cloneNode(true)`.
6. **Live DOM Cleanup (Zero Impact)**:
   - Immediately strips `data-ag-remove`, `data-ag-sticky`, `data-ag-click-id`, `data-ag-click-label` from live DOM.
7. **Editor & Input Removal**:
   - If `!isNewSessionPage`, finds all `[contenteditable="true"]`, `[data-lexical-editor]`, `[role="textbox"]`, and `form` elements.
   - Unwinds ancestors towards clone root; halts unwinding if an action button (`Allow`, `Deny`, `Review`, `Run`, `Confirm`, `Accept`, `Reject`) is encountered to preserve permission prompts.
8. **Fixed/Absolute Overlay Stripping**:
   - Removes elements with `[data-ag-remove]`, preserving those containing permission/action buttons.
9. **Sticky Background Solidification**:
   - Enforces `style.backgroundColor = '#101010'` on elements with `[data-ag-sticky]` to eliminate transparent overlap artifacts during mobile scroll.
10. **Inline Div-in-Span Correction**:
    - Rewrites invalid HTML where `div` is nested inside `span` or `p`. Converts `div` into `<span>` with `display: inline-flex; align-items: center;` while preserving all attributes and children.
11. **Paragraph Display Forcing**:
    - Enforces `style.display = 'block'` on all `<p>` tags.
12. **React Class Corruptions Cleanup**:
    - Scans clone HTML string and regex-strips `[object Object]` artifacts resulting from React class merging bugs: `html.replace(/class="([^"]*)"/g, ...)`.
13. **CSS Stylesheet & CSS Custom Properties Harvesting**:
    - Harvests all `cssRules[].cssText` across `document.styleSheets`.
    - Harvests all `--*` variables from `getComputedStyle(document.documentElement)` and `getComputedStyle(document.body)`.
    - Prepends `:root { --var: val; ... }` rules to captured CSS string.
14. **Peripheral State Extraction**:
    - **Left Sidebar**: Captures `.bg-sidebar` outerHTML with `left:N` tags. Classifies attention items via `animate-unread-ping` and Material path data into `question` (`QUESTION_ICON_PATH`), `command` (`lucide-terminal`), or `completed`.
    - **Right Sidebar Signature**: Extracts tab list (`overview*,review`) and measures collapse container `style.width !== '0%'`.
    - **Radix Body Portals**: Captures dropdown listboxes and dialog popovers from `document.body.children` and `#radix-:rXX:` wrappers.
    - **Settings Modal**: Captures `#root .fixed.inset-0[class*="z-[5000]"]` with `settings:N` tags.
    - **Active Tab URIs**: Resolves active file and artifact IDs from `[data-tab-id].bg-secondary`.
    - **Inline ask_question Modal**: Discovers cards with `Skip` + `Submit` buttons, tagged `ask:N`.
    - **Inline Permission Banner**: Discovers radiogroups with `Allow`/`Permission` text, tagged `perm:N`.
    - **Session Metadata**: Extracts `environmentName`, `branchName`, and `modelName`.
    - **Subagent View Detection**: Checks hidden input box + "Cannot send/prompt" text; extracts breadcrumb parent name; captures subagent info panel tagged `subinfo:N`.
    - **Side Question Box (`/btw`)**: Discovers `.border-border.rounded-md` container starting with "Side Question", tagged `btw:N`.

### 3.2 Bidirectional Element Tagging (`_shared.js`)

The tagging engine `tagInteractives(root, prefix, skipVisibilityCheck, includeCursorPointer, maxTextLength)` establishes interactive parity:
- Queries semantic elements: `button, a, [role="button"], [role="option"], [role="menuitem"], [role="menuitemradio"]`.
- Respects visibility (`skipVisibilityCheck || el.offsetParent !== null`).
- Queries `[class*="cursor-pointer"]`. Enforces `maxTextLength` (default 80) to avoid tagging paragraphs/codeblocks, unless `typeof el.onclick === 'function'` (identifying artifact cards).
- Sets `data-ag-click-id = prefix + ':' + idx` and `data-ag-click-label = text.substring(0, 50)`.
- Dynamic Value Sync: `scheduled-tasks.js` and `scheduled-tasks-dialog.js` stamp live `el.value` into `data-ag-value` attributes prior to cloning because `cloneNode(true)` drops live input buffers.

### 3.3 Universal Click Routing & Radix Hit-Testing (`click-main.js`)

`buildMainClickScript(safeClickId, safeLabel)` executes clicks across 12 prefix sources:
1. **Prefix Routing**: Routes to `chat`, `left`, `right`, `dropdown`, `dialog`, `settings`, `ask`, `perm`, `task`, `subinfo`, `btw`, `model`, `project`.
2. **Label Mismatch Guard**: Compares `actualLabel` with `expectedLabel`. If mismatched (due to DOM re-render), aborts and returns `{ ok: false, reason: 'label_mismatch', expected, actual, debugNearby }` with $\pm 3$ sibling diagnostics.
3. **Radix Portal Hit-Testing**: For `dropdown` and `btw` items where `.click()` fails on Radix virtual elements:
   - Focuses Lexical editor: `lexicalEditor.focus()`.
   - Computes target center: `x = rect.left + 5`, `y = rect.top + rect.height / 2`.
   - Hit-tests point: `hit = document.elementFromPoint(x, y) || target`.
   - Dispatches pointer lifecycle: `pointerdown` -> `mousedown` -> `pointerup` -> `mouseup` -> `clickTarget.click()`.

### 3.4 Lexical Editor & React Synthetic Setter Bypass

1. **Lexical Multiline Paste (`inject-message.js`)**:
   - Dispatches `ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true })` containing plain text DataTransfer to preserve line breaks.
   - Falls back to `document.execCommand('insertText', false, textVal)` if unhandled.
   - Locates submit button via testid/aria-label/icon or fires `KeyboardEvent('Enter')`.
2. **React Prototype Value Setter Bypass (`type-text.js`)**:
   - Bypasses React 18 synthetic input state tracking:
     ```javascript
     const nativeSetter = el.tagName === 'TEXTAREA'
       ? Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, 'value').set
       : Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, 'value').set;
     nativeSetter.call(el, text);
     el.dispatchEvent(new Event('input', { bubbles: true }));
     el.dispatchEvent(new Event('change', { bubbles: true }));
     ```
3. **Synthetic File Drag & Drop (`upload-image.js`)**:
   - Decodes Base64 to `Uint8Array`, constructs synthetic `File`, attaches to `DataTransfer`, and dispatches `dragenter` -> `dragover` -> `drop` events.

---

## 4. Script-by-Script Detailed Specifications

### 1. `_shared.js`
- **Purpose**: Shared browser-side tagging routines.
- **Parameters & Invocations**: Injected into script templates.
- **Return Structure**: String function definitions (`tagInteractives`, `untagAll`).
- **DOM Mechanics & Operations**: Enumerates semantic interactive elements and cursor-pointer elements (with text length guard unless `onclick` is present). Stamps `data-ag-click-id` and `data-ag-click-label`. `untagAll` removes attributes.

### 2. `capture-dropdown.js`
- **Purpose**: Captures body-level Radix dropdown listboxes and kebab menus.
- **Parameters & Invocations**: `buildCaptureListboxScript()`, `buildCaptureKebabMenuScript()`
- **Return Structure**: String HTML clone or `null`.
- **DOM Mechanics & Operations**: Scans `document.body.children` for `role="listbox"`, `role="dialog"`, or `data-side` attributes. Stamps `scheddlg:100+` click IDs and clones outerHTML.

### 3. `capture.js`
- **Purpose**: Master snapshot capture and sanitization script.
- **Parameters & Invocations**: `CAPTURE_SCRIPT` (Static IIFE).
- **Return Structure**: Dict with 24 snapshot fields (`html`, `css`, `agentRunning`, `scrollInfo`, `leftSidebarHtml`, `sidebarAttentionItems`, `sidebarSignature`, `isSidebarOpen`, `isNewSessionPage`, `isInputBoxHidden`, `isSubagentView`, `parentConversationName`, `subagentInfoHtml`, `dropdownHtml`, `dialogHtml`, `settingsHtml`, `activeArtifactUri`, `activeFileUri`, `askQuestionHtml`, `permissionHtml`, `environmentName`, `branchName`, `modelName`, `btwHtml`).
- **DOM Mechanics & Operations**: Executes full 14-step cleanup pipeline, CSS stylesheet and `--*` custom properties extraction, sticky solidifier, inline div fixer, and peripheral component extraction.

### 4. `check-editor-image.js`
- **Purpose**: Verifies whether Lexical editor contains rendered image attachment.
- **Parameters & Invocations**: `CHECK_EDITOR_IMAGE_SCRIPT` (Static IIFE).
- **Return Structure**: Boolean (`true`/`false`).
- **DOM Mechanics & Operations**: Queries visible Lexical editor; checks for `img`, `[data-lexical-decorator]`, or non-placeholder text.

### 5. `click-conversation.js`
- **Purpose**: Navigates to conversation by UUID from left sidebar.
- **Parameters & Invocations**: `buildClickConversationScript(safeConversationId)`
- **Return Structure**: `{ ok: bool, conversationId: str, name?: str, fallback?: bool, reason?: str }`
- **DOM Mechanics & Operations**: Expands left sidebar if collapsed, queries `[data-testid="convo-pill-<uuid>"]`, climbs to parent `role="button"` and triggers `.click()`.

### 6. `click-history.js`
- **Purpose**: Clicks item in `/history` Conversation History overlay.
- **Parameters & Invocations**: `buildHistoryClickScript(histIdx)`
- **Return Structure**: `{ ok: bool, label: str, source: 'history', reason?: str, total?: int }`
- **DOM Mechanics & Operations**: Reconstructs ordered interactive element list in history container (x>200px), focuses input or clicks element.

### 7. `click-main.js`
- **Purpose**: Universal click proxy routing 12 sources with label verification.
- **Parameters & Invocations**: `buildMainClickScript(safeClickId, safeLabel)`
- **Return Structure**: `{ ok: bool, label: str, source: str, debugNearby?: list, reason?: str }`
- **DOM Mechanics & Operations**: Routes to 12 prefix sources (`chat`, `left`, `right`, `dropdown`, `dialog`, `settings`, `ask`, `perm`, `task`, `subinfo`, `btw`, `model`, `project`), validates `actualLabel === expectedLabel`, performs Radix hit-testing with PointerEvent chain.

### 8. `click-sched-dialog.js`
- **Purpose**: Clicks elements inside `z-[2550]` scheduled task modal dialog.
- **Parameters & Invocations**: `buildSchedDialogClickScript(dlgIdx, safeLabel)`
- **Return Structure**: `{ ok: bool, label: str, source: 'scheddlg', reason?: str, total?: int }`
- **DOM Mechanics & Operations**: Enumerates dialog interactives, matches index or falls back to label search, focuses input or clicks button.

### 9. `click-sched-portal.js`
- **Purpose**: Clicks body-level portal dropdown options in scheduled tasks dialog.
- **Parameters & Invocations**: `buildSchedPortalClickScript(optIdx)`
- **Return Structure**: `{ ok: bool, label: str, source: 'scheddlg_portal', reason?: str }`
- **DOM Mechanics & Operations**: Locates body portal listbox/dialog, hit-tests option via `elementFromPoint`, dispatches pointerdown/mousedown/pointerup/mouseup/click.

### 10. `click-sched.js`
- **Purpose**: Clicks elements in Scheduled Tasks list or detail view.
- **Parameters & Invocations**: `buildSchedClickScript(schedIdx)`
- **Return Structure**: `{ ok: bool, label: str, source: 'sched', reason?: str, total?: int }`
- **DOM Mechanics & Operations**: Finds anchor button (`Add scheduled task` / `Edit task title`), walks up to content panel, indexes elements, executes click or focus.

### 11. `click-send-button.js`
- **Purpose**: Clicks send button for image-only messages.
- **Parameters & Invocations**: `CLICK_SEND_BUTTON_SCRIPT` (Static IIFE).
- **Return Structure**: `{ ok: bool, method: 'button', reason?: str }`
- **DOM Mechanics & Operations**: Queries `send-button` testid, aria-labels, and lucide-arrow icons; triggers `.click()`.

### 12. `click-task.js`
- **Purpose**: Clicks running task or goal buttons in input box header.
- **Parameters & Invocations**: `buildTaskClickScript(taskIdx)`
- **Return Structure**: `{ ok: bool, label: str, source: 'task', reason?: str, total?: int }`
- **DOM Mechanics & Operations**: Finds `#antigravity.agentSidePanelInputBox .rounded-t-2xl`, selects Nth button, triggers `.click()`.

### 13. `close-right-sidebar.js`
- **Purpose**: Closes auxiliary right sidebar.
- **Parameters & Invocations**: `CLOSE_RIGHT_SIDEBAR_SCRIPT` (Static IIFE).
- **Return Structure**: `'closed'` or `null`.
- **DOM Mechanics & Operations**: Queries `[data-testid="toggle-aux-sidebar"]`, triggers `.click()` if found.

### 14. `conversation-history.js`
- **Purpose**: Captures DOM of `/history` Conversation History route.
- **Parameters & Invocations**: `CONVERSATION_HISTORY_SCRIPT` (Static IIFE).
- **Return Structure**: String outerHTML or `null`.
- **DOM Mechanics & Operations**: Finds `.h-full.w-full.overflow-y-auto` (x>200px), validates heading, tags `hist:0..N`, syncs input values to `data-ag-value`, clones and strips styles.

### 15. `copy-response.js`
- **Purpose**: Intercepts clipboard write to capture raw markdown.
- **Parameters & Invocations**: `buildCopyResponseScript(safeClickId)`
- **Return Structure**: `{ ok: bool, text: str, reason?: str }`
- **DOM Mechanics & Operations**: Replaces `navigator.clipboard.writeText`, clicks target copy button, captures markdown text, restores original function.


### 16. `discover.js`
- **Purpose**: Comprehensive DOM layout diagnostics inspector.
- **Parameters & Invocations**: `DISCOVER_SCRIPT` (Static IIFE).
- **Return Structure**: Dict of layout hierarchies (asides, panels, tabs, rightEdgeElements, chatContainer, topLevel).
- **DOM Mechanics & Operations**: Probes layout hierarchy across contexts to locate unfamiliar panels and containers.

### 17. `dismiss-scheduled-tasks.js`
- **Purpose**: Navigates back from Scheduled Tasks views.
- **Parameters & Invocations**: `DISMISS_SCHEDULED_TASKS_SCRIPT` (Static IIFE).
- **Return Structure**: `{ ok: bool, method: 'detail-back' | 'sidebar-row' | 'history-back' }`
- **DOM Mechanics & Operations**: Checks detail view breadcrumb/back button; on list view clicks sidebar conversation row or triggers `window.history.back()`.

### 18. `dismiss-settings.js`
- **Purpose**: Closes Settings modal overlay.
- **Parameters & Invocations**: `DISMISS_SETTINGS_SCRIPT` (Static IIFE).
- **Return Structure**: `{ ok: bool, method: 'backdrop' | 'escape' }`
- **DOM Mechanics & Operations**: Dispatches click at backdrop coordinates (5,5) on `z-[5000]` overlay, or dispatches Escape keydown.

### 19. `expand-left-sidebar.js`
- **Purpose**: Expands left sidebar if collapsed.
- **Parameters & Invocations**: `EXPAND_LEFT_SIDEBAR_SCRIPT` (Static IIFE).
- **Return Structure**: `{ ok: bool, wasCollapsed: bool, error?: str }`
- **DOM Mechanics & Operations**: Checks `.bg-sidebar` visibility, clicks `[data-testid="sidebar-toggle"]` if collapsed.

### 20. `has-visible-editor.js`
- **Purpose**: Synchronous probe checking for visible Lexical editor in context.
- **Parameters & Invocations**: `HAS_VISIBLE_EDITOR_SCRIPT` (Static sync IIFE).
- **Return Structure**: Boolean (`true`/`false`).
- **DOM Mechanics & Operations**: Safe synchronous inspection of `data-lexical-editor` and `__lexicalEditor` without async promise GC risk.

### 21. `inject-message.js`
- **Purpose**: Injects text into Lexical editor and triggers submit.
- **Parameters & Invocations**: `buildInjectScript(safeText, appendMode)`
- **Return Structure**: `{ ok: bool, method: 'button' | 'enter', reason?: str }`
- **DOM Mechanics & Operations**: Focuses editor, handles selection collapse/clear, dispatches `ClipboardEvent` paste with DataTransfer, falls back to `execCommand('insertText')`, clicks send button or sends Enter key.

### 22. `open-right-sidebar.js`
- **Purpose**: Opens right auxiliary sidebar.
- **Parameters & Invocations**: `OPEN_RIGHT_SIDEBAR_SCRIPT` (Static IIFE).
- **Return Structure**: `'button'` or `null`.
- **DOM Mechanics & Operations**: Searches buttons with aria-label or tooltip matching Review/Auxiliary/Secondary Side Bar and clicks.

### 23. `proxy-image.js`
- **Purpose**: Draws image element to HTML5 Canvas and exports base64 data URL.
- **Parameters & Invocations**: `buildProxyImageScript(safeSrc)`
- **Return Structure**: `data:image/png;base64,...` or `null`.
- **DOM Mechanics & Operations**: Draws completed img to Canvas (resizing to max 800px width), returns `canvas.toDataURL('image/png')`.

### 24. `right-sidebar.js`
- **Purpose**: Captures right sidebar DOM tree.
- **Parameters & Invocations**: `RIGHT_SIDEBAR_SCRIPT` (Static IIFE).
- **Return Structure**: String outerHTML or `null`.
- **DOM Mechanics & Operations**: Locates tab buttons or toggle-aux-sidebar, ascends to sidebar container, tags `right:0..N`, clones and cleans styles.

### 25. `running-tasks.js`
- **Purpose**: Captures running tasks section in input box header.
- **Parameters & Invocations**: `RUNNING_TASKS_SCRIPT` (Static IIFE).
- **Return Structure**: String outerHTML or `null`.
- **DOM Mechanics & Operations**: Finds `.rounded-t-2xl` in input box, validates minimum button count, tags `task:0..N`, returns outerHTML.

### 26. `scheduled-tasks-dialog.js`
- **Purpose**: Captures `z-[2550]` scheduled task dialog card.
- **Parameters & Invocations**: `SCHEDULED_TASKS_DIALOG_SCRIPT` (Static IIFE).
- **Return Structure**: String outerHTML or `null`.
- **DOM Mechanics & Operations**: Matches Scheduled Task or delete text, tags `scheddlg:0..N`, syncs input values to `data-ag-value`, clones inner card.

### 27. `scheduled-tasks.js`
- **Purpose**: Captures Scheduled Tasks page content.
- **Parameters & Invocations**: `SCHEDULED_TASKS_SCRIPT` (Static IIFE).
- **Return Structure**: String outerHTML or `null`.
- **DOM Mechanics & Operations**: Finds anchor button, ascends to content panel, tags `sched:0..N`, syncs input values to `data-ag-value`, clones and strips styles.

### 28. `select-overview-tab.js`
- **Purpose**: Selects Overview tab in auxiliary sidebar if none active.
- **Parameters & Invocations**: `SELECT_OVERVIEW_TAB_SCRIPT` (Static IIFE).
- **Return Structure**: `void` (executes click).
- **DOM Mechanics & Operations**: Checks if any `[data-tab-id]` has `bg-secondary` class; clicks overview tab if not.

### 29. `stop.js`
- **Purpose**: Halts active agent generation.
- **Parameters & Invocations**: `STOP_SCRIPT` (Static IIFE).
- **Return Structure**: `{ ok: bool, method?: 'cancel-tooltip' | 'square-icon', reason?: str }`
- **DOM Mechanics & Operations**: Clicks cancel tooltip button or `svg.lucide-square` stop button.

### 30. `type-text.js`
- **Purpose**: Types text into input/textarea bypassing React synthetic event traps.
- **Parameters & Invocations**: `buildTypeTextScript(safePlaceholder, safeClickId, safeText)`
- **Return Structure**: `{ ok: bool, tag: str, placeholder: str, valueLength: int, reason?: str }`
- **DOM Mechanics & Operations**: Locates element by placeholder or click ID, focuses, invokes native prototype setter descriptor, dispatches input and change events.

### 31. `upload-image.js`
- **Purpose**: Uploads image into Lexical editor via synthetic DragEvent.
- **Parameters & Invocations**: `buildUploadImageScript(safeBase64, safeMimetype, safeFileName)`
- **Return Structure**: `{ ok: bool, method: 'drop', fileName: str, size: int, reason?: str }`
- **DOM Mechanics & Operations**: Decodes base64, builds File and DataTransfer, dispatches `dragenter`, `dragover`, and `drop` events to editor.

---

## 5. Python Packaging & CDP Bridge Architecture (`cdp_bridge.py`)

### 5.1 Script Embedding & Packaging

In Python, all 31 scripts should be packaged either as raw multiline string constants in `cdp_scripts.py` or modular builder functions. Arguments must be formatted using `json.dumps()` to guarantee escape safety against quote corruption, line breaks, and unicode.

### 5.2 Multi-Context Execution Implementation

`CDPBridge` tracks execution contexts via CDP WebSocket events:
- `Runtime.executionContextCreated`: Registers context `{ id, name, isDefault }`.
- `Runtime.executionContextDestroyed`: Removes context from internal pool.
- `Runtime.executionContextsCleared`: Flushes context pool.

The 4 Execution Methods in `CDPBridge`:
1. `evaluate_in_browser(expression)`: Tries preferred context first, falling back across contexts on error.
2. `evaluate_across_contexts(expression)`: Iterates all contexts and returns the **first non-null** result (used for body portals, running tasks, scheduled tasks).
3. `evaluate_in_context(context_id, expression)`: Runs strictly in a single context without fallthrough for state-mutating operations (`inject_message`, `stop`, `click_send`).
4. `find_editor_context()`: Runs synchronous `HAS_VISIBLE_EDITOR_SCRIPT` across contexts sorted by default priority to identify active editor context without GC risk.

---

## Edge Cases

| # | Feature | Input | Observed Behavior |
|---|---|---|---|
| 1 | `capture.js` | New session page (chat container height = 0) | Walks up 10 ancestors from input box to `.animate-fade-in` container and mirrors session setup UI with `isNewSessionPage=true`. |
| 2 | `capture.js` | Subagent view active ("Cannot send" label) | Detects hidden input box and "Cannot send" label, extracts breadcrumb parent name, captures subagent info panel. |
| 3 | `inject-message.js` | Multiline prompt with linebreaks (`\n`) | Uses `ClipboardEvent('paste')` DataTransfer to prevent Lexical newline truncation; falls back to `execCommand('insertText')`. |
| 4 | `type-text.js` | React controlled `<input>`/`<textarea>` | Calls native prototype setter (`HTMLInputElement.prototype.value`) and dispatches synthetic `input` and `change` events. |
| 5 | `click-main.js` | Radix UI portal item click | Focuses editor, performs `elementFromPoint` hit testing, and dispatches full PointerEvent/MouseEvent lifecycle. |
| 6 | `click-main.js` | Element index drift during DOM re-render | Compares `actualLabel` with `expectedLabel`; halts and returns `debugNearby` window of +-3 items on mismatch. |
| 7 | `capture.js` | React `[object Object]` class string bug | Cleanses malformed class attributes using regex replacement before returning HTML. |
| 8 | `capture.js` | Radix portals rendered in `document.body` | Scans `document.body.children` for `role="listbox"` and `div#radix-:rXX:` to capture dropdowns and dialogs. |
| 9 | `_shared.js` | Long content container with `cursor-pointer` | Enforces `maxTextLength=80` in chat, ignoring large blocks unless `typeof el.onclick === 'function'`. |
| 10 | `inject-message.js` | Context promise GC during async send | Resolves editor context synchronously via `HAS_VISIBLE_EDITOR_SCRIPT`, then evaluates strictly in target context to prevent double-send. |

