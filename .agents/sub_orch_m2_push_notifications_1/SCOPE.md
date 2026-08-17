# Scope: Milestone M2 — Push Notifications Module

## Overview
Implement the complete Python Web Push Notifications system for Antigravity WebRemote v6 in `push_notifications.py` and update `requirements.txt`.

## Requirements & Specifications
1. **VAPID Keypair Management**:
   - Generate EC P-256 (NIST P-256 / secp256r1) keypair when initializing if not existing.
   - Support loading/saving keys to `vapid-keys.json` or `config.json`.
   - Provide base64url-encoded public VAPID key via `get_public_vapid_key()` for browser `subscribe({ applicationServerKey })`.
   - Provide private key and subject email/mailto for `webpush`.

2. **Push Subscriptions Persistence**:
   - Store browser push subscriptions (endpoint, keys: p256dh, auth, expirationTime, client metadata) in `push-subscriptions.json`.
   - Thread-safe / async-safe operations for `add_subscription(sub_data)`, `remove_subscription(endpoint)`, `get_subscriptions()`.
   - Avoid duplicate subscriptions (keyed on `endpoint`).

3. **Web Push Dispatcher (pywebpush)**:
   - Integrate with `pywebpush.webpush`.
   - Send payload formatted as JSON: `{"title": "...", "body": "...", "icon": "...", "badge": "...", "data": {"conversationId": "...", "url": "..."}}`.
   - Robust error handling: Handle `WebPushException` (status 410 Gone / 404 Not Found -> auto remove subscription; status 429 Too Many Requests -> retry/backoff; network errors).
   - Async dispatching (using `asyncio.to_thread` or non-blocking executor) so server event loop is not blocked by HTTP push calls.

4. **Attention State Watcher & Notification Triggers**:
   - Track previous attention state and detect state transitions:
     * Command approval needed (`command` / permission overlay)
     * Question asked (`question` / `ask_question`)
     * Task / agent execution complete (`agentRunning` transitioned from `True` to `False` or attention `completed`)
   - Dispatch appropriate title & body for each trigger.
   - Dedup mechanism to prevent sending repeated notifications for the same unacknowledged attention item.

5. **Client Visibility Suppression**:
   - Track active/connected clients and their visibility states (`set_client_visibility(client_id, is_visible)`).
   - Remove stale/disconnected clients after heartbeat timeout or explicit disconnect.
   - `is_any_client_visible()`: if any client tab is active/foreground, suppress background push notifications to avoid spamming the user when they are already looking at the screen.

6. **Requirements Update**:
   - Ensure `requirements.txt` contains `pywebpush>=1.14.0` and `cryptography>=41.0.0`.

7. **Interface Compliance**:
   - Must conform to `PROJECT.md § Interface Contracts`:
     ```python
     class PushNotificationManager:
         def __init__(self, config_path: str = "config.json", subscriptions_path: str = "push-subscriptions.json", vapid_path: str = "vapid-keys.json"): ...
         def get_public_vapid_key(self) -> str: ...
         def add_subscription(self, subscription_data: Dict[str, Any]) -> bool: ...
         def remove_subscription(self, endpoint: str) -> bool: ...
         def set_client_visibility(self, client_id: str, is_visible: bool) -> None: ...
         def is_any_client_visible(self) -> bool: ...
         async def check_and_send_attention_notifications(self, attention_items: List[Dict[str, Any]], agent_running: bool) -> int: ...
         async def send_notification(self, title: str, body: str, data: Optional[Dict[str, Any]] = None) -> int: ...
     ```

## Code Layout
- Implementation: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\push_notifications.py`
- Requirements: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\requirements.txt`
- Storage files: `vapid-keys.json`, `push-subscriptions.json`
- Tests: `D:\Data_Lokal\Kuliah\Tri Wahyu (22518241023)\Local_AI_Mobile_Agent\tests\test_push_notifications.py` (or unit test script)
