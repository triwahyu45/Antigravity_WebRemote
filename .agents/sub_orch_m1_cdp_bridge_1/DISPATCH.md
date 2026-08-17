## 2026-08-17T01:30:12+07:00
You are sub_orch_m1_cdp_bridge_1, Sub-orchestrator for Milestone M1 (CDP Bridge & Scripts Engine).
Your working directory is: D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\.agents\sub_orch_m1_cdp_bridge_1\
The project root is: D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\
Reference codebase is: D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\_references_antigravity_mobile\ag2r\

Instructions:
1. Read `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\ORIGINAL_REQUEST.md` and `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\PROJECT.md`.
2. Implement `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\cdp_bridge.py`:
   - Dynamic port discovery: `%APPDATA%\Antigravity\DevToolsActivePort` with fallback probe for ports 9000..9003.
   - Async CDP WebSocket client with auto-reconnect, target finding (`workbench.html` / `page` / `jetski`), and session management.
   - Multi-context tracking (`executionContextCreated`, `executionContextDestroyed`, `executionContextsCleared`) and context evaluation helpers (`evaluateAcrossContexts`, `evaluateInBrowser`, `findEditorContext`).
   - Implement / embed all 31 CDP scripts from `ag2r/src/cdp-scripts/` with 100% logic fidelity:
     - `capture.js` (DOM container search, `data-ag-click-id` tagging, 14-step DOM sanitization, CSS rule & variable extraction, overlays, dialogs, attention items, subagent state, BTW panel).
     - `inject-message.js` (Lexical paste via ClipboardEvent and send button click).
     - `click-main.js` (index-based click proxy with hit-testing for Radix portals and label mismatch validation).
     - `stop.js` (agent generation stopper).
     - `upload-image.js` (Base64 decode to File and DragEvent sequence into Lexical editor).
     - `type-text.js` (React prototype value setter bypass).
     - `running-tasks.js`, `scheduled-tasks.js`, `conversation-history.js`, `right-sidebar.js`, etc.
   - DJB2 composite state hashing across 17 state properties.
3. Verify `cdp_bridge.py` functionality with unit tests (e.g. testing parsing, script generation, hashing, and live or mock CDP interactions).
4. Deliver `handoff.md` to your directory and send a completion message back to the orchestrator.
