## 2026-08-16T18:33:56Z

You are worker_m2_1, the implementation worker for Milestone M2 (Push Notifications Module).
Your working directory is: D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\.agents\worker_m2_1\

Tasks to Complete:
1. Implement `push_notifications.py` with `PushNotificationManager` class conforming to the interface contract:
   - VAPID key generation and storage: generate EC P-256 (secp256r1) keypair using `cryptography` if not present. Format public key as 65-byte uncompressed point (`0x04 || X || Y`) base64url encoded without padding (87 chars) for `get_public_vapid_key()`. Persist in `vapid-keys.json` or `config.json`. Support PKCS#8 PEM private key format.
   - Browser push subscriptions management: `add_subscription`, `remove_subscription`, `get_subscriptions`. Persist atomically to `push-subscriptions.json`. Keyed by endpoint to avoid duplicates.
   - `pywebpush` integration: send RFC 8292 Web Push notifications asynchronously using `asyncio.to_thread` / `asyncio.gather` so the event loop is never blocked.
   - Handle `WebPushException`: automatically remove expired/invalid subscriptions (HTTP 410 Gone / 404 Not Found), handle rate limits (429) and errors gracefully.
   - Attention state watcher (`check_and_send_attention_notifications(attention_items, agent_running)`):
     * Detect attention state transitions: `command` (permission approval), `question` (ask_question), `agent_running: True -> False` (task completed).
     * Deduplicate alerts per `(item_id, item_type)` so duplicate notifications are not sent repeatedly for the same unhandled item, and prune items when they leave the attention list.
     * Guard against initial startup false alarms (`_previous_agent_running is None`).
   - Client visibility tracking & suppression:
     * `set_client_visibility(client_id, is_visible)` tracking active clients with heartbeat timestamps.
     * `is_any_client_visible()`: returns True if any client tab is currently visible (and active within 30s timeout).
     * If `is_any_client_visible()`, suppress push notifications but record the attention items in the notified set so they don't fire later when backgrounded.
   - Helper `send_notification(title, body, data)` to dispatch custom/general web push notifications.

2. Update `requirements.txt`:
   - Ensure `pywebpush>=1.14.0` and `cryptography>=41.0.0` are present alongside existing requirements.

3. Write comprehensive unit tests in `tests/test_push_notifications.py`:
   - Test VAPID key generation, format (87 chars base64url), persistence across reload.
   - Test subscription add/remove/persistence/deduplication.
   - Test visibility tracking, client heartbeat expiration, and `is_any_client_visible()` suppression.
   - Test `check_and_send_attention_notifications`: command approval, question, agent_running True->False, deduplication, item disappearance.
   - Test `pywebpush` mock sending: 201 success, 410 Gone (auto-unsub), 404, 429, network exception.
   - Run tests using `pytest` or `python` command and verify 100% pass.

4. Deliver `handoff.md` and report back with exact test results and command outputs.
