# Orchestration Plan — Antigravity WebRemote v6

## Goal
Achieve 100% full-featured Python port of AG2R in `Local_AI_Mobile_Agent` with FastAPI/uvicorn, WebSocket stream, CDP mirroring & interaction, Push notifications, and mobile-responsive frontend.

## Execution Pattern: Project Pattern (Dual Track)

### Phase 0: Survey & Requirements Discovery (Parallel Spec Mining)
- Dispatch 3 Explorers/Spec Miners in parallel:
  1. `explorer_spec`: Mine requirements from `ORIGINAL_REQUEST.md`.
  2. `explorer_existing`: Investigate `Local_AI_Mobile_Agent` current files, dependencies, server.py, endpoints, and gaps.
  3. `explorer_reference`: Investigate `_references_antigravity_mobile\ag2r` implementation, CDP capture logic, DOM sanitization, push notifications, and UI components.

### Phase 1: Synthesis & PROJECT.md
- Merge survey reports into unified Feature Inventory (Requirements R1, R2, R3, R4, R5).
- Structure Milestones and Interface Contracts in `PROJECT.md`.
- Establish Code Layout and writing ownership boundaries.

### Phase 2: Dual Track Dispatch
- **E2E Testing Track**: Spawn E2E Testing Orchestrator to build test harness and 4 Tiers of comprehensive opaque-box tests. Output `TEST_READY.md`.
- **Implementation Track**: Spawn Sub-orchestrators for milestones:
  - Milestone 1: CDP Live DOM Mirroring & WebSocket streaming (`cdp_bridge.py`, sanitization, hash diffing, `/ws/stream`).
  - Milestone 2: Two-Way Interaction & CDP Actions (`POST /api/chat/send`, `/api/cdp/click`, `/api/cdp/stop`, `/api/upload-image`).
  - Milestone 3: Interactive Overlays & Web Push (`push_notifications.py`, VAPID, overlays detection & interactions, `/api/vapid-key`, `/api/subscriptions/push`).
  - Milestone 4: Frontend Full AG2R Parity (`static/index.html`, `app.css`, `app.js` with task strip, subagent bar, BTW panel, scheduled tasks, FABs, image upload, status dot).

### Phase 3: Final Integration Milestone & Adversarial Hardening
- Run full test suite (Tiers 1-4).
- Challenger-led adversarial testing (Tier 5) for edge cases and regressions.
- Independent Forensic Audit (`teamwork_preview_auditor`).

### Phase 4: Verification & Handoff
- Verify all Acceptance Criteria.
- Produce comprehensive handoff report.
