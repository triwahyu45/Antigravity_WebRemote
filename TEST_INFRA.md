# E2E Test Infra: Antigravity WebRemote v6

## Test Philosophy
- **Opaque-box & Requirement-Driven**: Tests are derived strictly from `ORIGINAL_REQUEST.md` and `PROJECT.md` specifications, treating the server as an opaque black/grey box with defined HTTP REST, WebSocket, and CDP bridge interfaces.
- **Independence**: Test verification mechanisms do not rely on server internals, but verify real protocol contracts (JSON schemas, HTTP status codes, WebSocket broadcast envelopes, CDP message injection, VAPID crypto, and responsive static assets).
- **Multi-Tier Methodology**:
  - **Tier 1 (Feature Coverage)**: Equivalence class happy-path tests for all 32 inventoried features (>=5 test cases per feature = >=160 tests).
  - **Tier 2 (Boundary & Corner Cases)**: Boundary values, corrupt/empty payloads, malformed JSON, network disconnection, extreme sizes, invalid characters (>=5 test cases per feature = >=160 tests).
  - **Tier 3 (Cross-Feature Combinations)**: Pairwise interactions between features (e.g., Live DOM snapshot + Attention items + Push notification; Multi-tab visibility + Web Push suppression; Two-way Lexical injection + Stop button; Image upload + Permission dialog) (>=32 tests).
  - **Tier 4 (Real-World Application Scenarios)**: End-to-end mobile user workflows (mobile remote session, interactive tool call approval, background notification alerting, multi-client streaming, connection recovery, BTW side questions, subagent navigation) (>=16 tests).

## Feature Inventory & Test Mapping (32 Features)

| # | Feature | Scope / Source | Tier 1 (Min) | Tier 2 (Min) | Tier 3 | Tier 4 |
|---|---------|----------------|:------------:|:------------:|:------:|:------:|
| 1 | DevTools Port Discovery | `cdp_bridge.py` (ActivePort file & fallback 9000-9003) | 5 | 5 | ✓ | ✓ |
| 2 | CDP Target Discovery & Connection | `cdp_bridge.py` (`/json/list` targets, WS connection) | 5 | 5 | ✓ | ✓ |
| 3 | Multi-Context Execution Tracking | `cdp_bridge.py` (Main & Isolated execution contexts) | 5 | 5 | ✓ | ✓ |
| 4 | DOM Capture & Element Tagging | `cdp_bridge.py` (`data-ag-click-id`, clone chat DOM) | 5 | 5 | ✓ | ✓ |
| 5 | DOM Sanitization Pipeline | `cdp_bridge.py` (14-step sanitizer, span-div nesting) | 5 | 5 | ✓ | ✓ |
| 6 | Dynamic CSS Extraction | `cdp_bridge.py` (Harvest stylesheets & `--*` variables) | 5 | 5 | ✓ | ✓ |
| 7 | DJB2 Composite State Hashing | `cdp_bridge.py` (17 state flags hashed for diffing) | 5 | 5 | ✓ | ✓ |
| 8 | Attention State Detection | `cdp_bridge.py` (Question, command, completed icons) | 5 | 5 | ✓ | ✓ |
| 9 | Overlay Data Extraction | `cdp_bridge.py` (Permission, ask_question, dropdown) | 5 | 5 | ✓ | ✓ |
| 10 | VAPID Keypair Management | `push_notifications.py` (EC P-256 generation/storage) | 5 | 5 | ✓ | ✓ |
| 11 | Push Subscription Storage | `push_notifications.py` (JSON storage & persistence) | 5 | 5 | ✓ | ✓ |
| 12 | Background Push Dispatcher | `push_notifications.py` (pywebpush push delivery) | 5 | 5 | ✓ | ✓ |
| 13 | Client Visibility Suppression | `push_notifications.py` (Foreground tab suppression) | 5 | 5 | ✓ | ✓ |
| 14 | WebSocket Streaming Endpoint | `server.py` (`/ws/stream` live snapshot broadcasting) | 5 | 5 | ✓ | ✓ |
| 15 | Two-Way Chat Injection | `server.py` (`POST /api/chat/send` Lexical paste) | 5 | 5 | ✓ | ✓ |
| 16 | CDP Element Click Proxy | `server.py` (`POST /api/cdp/click` element click) | 5 | 5 | ✓ | ✓ |
| 17 | Agent Execution Stopper | `server.py` (`POST /api/cdp/stop` cancel generation) | 5 | 5 | ✓ | ✓ |
| 18 | Base64 Image Drag-Drop Upload | `server.py` (`POST /api/upload-image` drag event) | 5 | 5 | ✓ | ✓ |
| 19 | Interactive Overlay Routes | `server.py` (`/api/cdp/answer-question`, `/permission`) | 5 | 5 | ✓ | ✓ |
| 20 | Task & Session Navigation | `server.py` (`/api/running-tasks`, `/history`, etc.) | 5 | 5 | ✓ | ✓ |
| 21 | Legacy Route Compatibility | `server.py` (15 legacy endpoints returning 200) | 5 | 5 | ✓ | ✓ |
| 22 | Zeroconf mDNS Registration | `server.py` (`wahyuai.local:8888` mDNS service) | 5 | 5 | ✓ | ✓ |
| 23 | Process Lifecycle Management | `server.py` (`/api/restart-antigravity` taskkill) | 5 | 5 | ✓ | ✓ |
| 24 | Frontend Live Snapshot Renderer | `static/js/app.js` (DOM patching & CSS variable apply) | 5 | 5 | ✓ | ✓ |
| 25 | Interactive Overlays UI | `static/js/app.js` & `index.html` (Overlay modal cards) | 5 | 5 | ✓ | ✓ |
| 26 | Running Tasks Strip UI | `static/js/app.js` & `index.html` (Task strip & cancel) | 5 | 5 | ✓ | ✓ |
| 27 | Subagent View Bar UI | `static/js/app.js` & `index.html` (Subagent warning/back) | 5 | 5 | ✓ | ✓ |
| 28 | BTW Side Question Panel | `static/js/app.js` & `index.html` (Side question drawer) | 5 | 5 | ✓ | ✓ |
| 29 | Floating Action Buttons (FAB) | `static/js/app.js` & `index.html` (Scroll FAB & Comment) | 5 | 5 | ✓ | ✓ |
| 30 | Scheduled Tasks & History Modals | `static/js/app.js` & `index.html` (Fullscreen overlays) | 5 | 5 | ✓ | ✓ |
| 31 | Service Worker & Push Bell | `static/sw.js` (Push reception, notification click) | 5 | 5 | ✓ | ✓ |
| 32 | Mobile Responsive Styles | `static/css/app.css` (Dark theme, touch, safe area) | 5 | 5 | ✓ | ✓ |

## Test Architecture & Directory Layout

```
Local_AI_Mobile_Agent/
├── tests/
│   ├── __init__.py
│   ├── harness.py                 # Mock CDP server, mock WebSocket fixture, FastAPI TestClient / async helpers
│   ├── test_tier1_features.py     # Tier 1: 32 Features x >=5 tests = >=160 tests
│   ├── test_tier2_boundaries.py   # Tier 2: 32 Features x >=5 tests = >=160 tests
│   ├── test_tier3_combinations.py # Tier 3: Cross-feature pairwise combinations (>=32 tests)
│   ├── test_tier4_scenarios.py    # Tier 4: Real-world mobile workflows & E2E flows (>=16 tests)
│   └── test_tier5_adversarial.py  # Tier 5: Adversarial hardening suite
```

### Execution Commands
- Standalone runner: `python -m unittest discover -s tests -p "test_*.py"`
- Pytest runner: `pytest tests -v`
- Individual tier runner: `python -m unittest tests/test_tier1_features.py`

### Test Harness Components (`tests/harness.py`)
1. **MockCDPServer**: Async WebSocket mock server emulating Chrome DevTools Protocol (port discovery, target list `/json/list`, execution contexts, DOM evaluation, script dispatching, click dispatching, keyboard/mouse events).
2. **MockFastAPIApp / TestClient**: Direct ASGI testing via `starlette.testclient.TestClient` / `httpx.AsyncClient` against `server.py` app routes.
3. **MockWebPushService**: Intercepts pywebpush HTTP requests, validating encryption headers, payload structures, and VAPID JWT tokens.
4. **DOMSnapshotGenerator**: Generates realistic Antigravity chat DOMs, Lexical editor HTML, permission dialog nodes, ask_question cards, and CSS root blocks.
5. **Assertion Helpers**: Assert valid DJB2 hashes, snapshot schemas, sanitized HTML safety, responsive CSS media query validity, and service worker push event compliance.

## Coverage Thresholds
- **Tier 1 (Feature Coverage)**: >= 160 test cases (5 per feature across 32 features)
- **Tier 2 (Boundary & Corner Cases)**: >= 160 test cases (5 per feature across 32 features)
- **Tier 3 (Cross-Feature Combinations)**: >= 32 test cases
- **Tier 4 (Real-World Application Scenarios)**: >= 16 comprehensive test cases
- **Total Minimum Test Count**: >= 368 test cases
