## 2026-08-17T01:30:54+07:00
You are subagent_test_writer_harness_1, a Test Harness Architect.
Your working directory is: D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\.agents\subagent_test_writer_harness_1\
The project root is: D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\

Mandatory Instructions:
1. Read `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\ORIGINAL_REQUEST.md`, `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\PROJECT.md`, and `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\TEST_INFRA.md`.
2. DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A forensic auditor will independently verify your work.
3. Your exclusive file ownership:
   - `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\tests\__init__.py`
   - `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\tests\harness.py`
4. Build `tests/harness.py` to support comprehensive opaque-box E2E testing for all 32 features. It must include:
   - `MockCDPServer`: In-process or async WebSocket mock server simulating Chrome DevTools Protocol at `127.0.0.1:9000` (or dynamic port) responding to `/json/list`, `Page.enable`, `Runtime.enable`, `DOM.enable`, `Runtime.evaluate`, `Input.dispatchMouseEvent`, `Input.dispatchKeyEvent`, `DOM.performSearch`, etc.
   - `MockPushService`: Helper to mock `pywebpush.webpush` and validate VAPID headers, crypto payloads, endpoints, and subscription JSON.
   - `MockDOMGenerator`: Utilities to create realistic Antigravity chat DOMs, Lexical editor HTML, permission dialog nodes (Allow/Deny/Run/Review), ask_question cards (multiple choice with data-ag-id), dropdown menus, running task progress indicators, subagent breadcrumbs, and CSS stylesheets/variables.
   - `TestClientWrapper`: FastAPI `TestClient` / async `httpx.AsyncClient` and WebSocket test client helpers for `/ws/stream` and all 32 REST endpoints + 15 legacy endpoints.
   - Assertion helpers: `assert_valid_snapshot(snapshot_dict)`, `assert_valid_djb2_hash(hash_val, content)`, `assert_sanitized_html(html)`, `assert_vapid_key_valid(key_str)`, etc.
   - Fallback and resilience: Ensure `harness.py` works seamlessly both with standard library `unittest` and `pytest` in asynchronous or synchronous test contexts.
5. Verify `tests/harness.py` imports and executes cleanly without syntax or runtime errors.
6. Write your handoff report to `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\.agents\subagent_test_writer_harness_1\handoff.md` and send a completion message back.
