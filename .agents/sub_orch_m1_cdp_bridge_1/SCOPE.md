# Scope: Milestone M1 — CDP Bridge & Scripts Engine

## Architecture
- `cdp_bridge.py` acts as the low-level communication bridge to the Antigravity Desktop IDE via Chrome DevTools Protocol (CDP).
- It manages discovery, WebSocket connections, target/session attachment, execution context lifecycle tracking, script injection, and state computation.

## Features & Requirements
1. **Dynamic Port Discovery**:
   - Primary: Read port and browser path from `%APPDATA%\Antigravity\DevToolsActivePort` (or `%LOCALAPPDATA%\Programs\Antigravity\...`).
   - Fallback: Asynchronously probe localhost ports 9000..9003 (`http://127.0.0.1:<port>/json/version` or `/json/list`).
2. **Async CDP Client**:
   - WebSocket client using `websockets` or `aiohttp`.
   - Reconnection loop with exponential backoff.
   - Target finding for `workbench.html`, `page`, `jetski` targets.
   - Session management (`Target.attachToTarget` / `Target.setAutoAttach`).
3. **Multi-Context Tracking**:
   - Listen to `Runtime.executionContextCreated`, `Runtime.executionContextDestroyed`, `Runtime.executionContextsCleared`.
   - Methods: `evaluateAcrossContexts`, `evaluateInBrowser`, `findEditorContext`.
4. **Script Engine & 31 Embedded CDP Scripts**:
   - Fully embed or load and execute all 31 scripts from `ag2r/src/cdp-scripts/`:
     1. `capture.js`
     2. `inject-message.js`
     3. `click-main.js`
     4. `stop.js`
     5. `upload-image.js`
     6. `type-text.js`
     7. `running-tasks.js`
     8. `scheduled-tasks.js`
     9. `conversation-history.js`
     10. `right-sidebar.js`
     11. `select-dropdown.js`
     12. `toggle-switch.js`
     13. `scroll-element.js`
     14. `key-combination.js`
     15. `clear-input.js`
     16. `hover-element.js`
     17. `drag-drop.js`
     18. `focus-element.js`
     19. `blur-element.js`
     20. `copy-text.js`
     21. `paste-text.js`
     22. `expand-collapse.js`
     23. `close-tab.js`
     24. `switch-tab.js`
     25. `new-tab.js`
     26. `navigate-url.js`
     27. `get-element-bounds.js`
     28. `get-computed-style.js`
     29. `check-element-visibility.js`
     30. `wait-for-selector.js`
     31. `custom-eval.js`
     (and all actual scripts present in `_references_antigravity_mobile/ag2r/src/cdp-scripts/`)
5. **DJB2 Composite State Hashing**:
   - Compute deterministic hash across 17 state properties.

## Iteration Status
- Current Iteration: 1 / 32
- Status: Exploration Phase
